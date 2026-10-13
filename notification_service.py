# notification_service.py
"""
Python port of HarvHub's notification_service.php.

Public API (mirrors the PHP):

    record_contract_notification(pdo, payload)          -> int | None
    record_contract_notification_once(pdo, payload)     -> int | None
    record_programme_notification(pdo, programme_id,
                                  user_email, opts)     -> int | None
    record_programme_notification_once(pdo, programme_id,
                                       user_email, opts) -> int | None

    record_broker_login_status_notification(pdo, user)  -> int | None
    record_broker_login_success_notification(pdo, user) -> int | None
    record_broker_login_reconnected_notification(pdo, user) -> int | None

    record_programme_broker_login_status_notification(pdo, row) -> int | None
    record_programme_broker_login_success_notification(pdo, row) -> int | None
    record_programme_broker_login_reconnected_notification(pdo, row) -> int | None
    record_programme_disconnect_broker_completed_notification(pdo, row) -> int | None

    record_disconnect_broker_completed_notification(pdo, user) -> int | None

    record_balance_verification_notification(pdo, user) -> int | None

    # ---- Programme-scoped restriction + daily-target helpers ----
    record_programme_restriction_date_notification(pdo, ...)      -> int | None
    record_programme_restriction_day_full_notification(pdo, ...)  -> int | None
    record_programme_restriction_day_window_notification(pdo, ...)-> int | None
    record_programme_daily_target_summary_notification(pdo, ...)  -> int | None

    get_contract_notifications(pdo, email, sub_id, limit=100) -> list
    get_programme_notifications(pdo, programme_id, email, limit=100) -> list
    mark_contract_notifications_read(pdo, email, sub_id) -> bool
    mark_programme_notifications_seen(pdo, programme_id, email) -> bool

    get_notification_unread_count(pdo, email, sub_id) -> int
    get_programme_notification_unread_count(pdo, programme_id, email) -> int

    sync_notification_unread_flag(pdo, email, sub_id) -> None
"""

from __future__ import annotations

import re
import time
from typing import Any, Optional


# ==============================================================================
# CLEAN NOTIFICATION TEXT
# ==============================================================================

_TECH_WORDS = [
    'php', 'sql', 'mysql', 'pdo', 'database', 'db', 'query', 'script',
    'array', 'json', 'html', 'css', 'js', 'javascript', 'code', 'function',
    'class', 'method', 'variable', 'loop', 'if', 'else', 'echo', 'print',
    'var', 'const', 'let', 'table', 'column', 'row', 'insert', 'update',
    'delete', 'select', 'where', 'join', 'schema', 'api', 'endpoint',
    'http', 'https', 'url', 'www', 'com', 'net', 'org', 'io',
]
_TECH_RE = re.compile(
    r'\b(' + '|'.join(re.escape(w) for w in _TECH_WORDS) + r')\b',
    re.IGNORECASE,
)

_EMOJI_RE = re.compile(
    r'[\U0001F300-\U0001FAFF]',
    re.UNICODE,
)

_ACCOUNT_ID_RES = [
    re.compile(r'\baccount\s*_?\s*id\s*[:\-]?\s*\d+\b', re.IGNORECASE),
    re.compile(r'\bsub\s*_?\s*account\s*_?\s*id\s*[:\-]?\s*\d+\b', re.IGNORECASE),
    re.compile(r'\bmain\s*_?\s*account\s*_?\s*id\s*[:\-]?\s*\d+\b', re.IGNORECASE),
    re.compile(r'account\s*_?\s*id\s*[:\-]?\s*\d+', re.IGNORECASE),
]

_NULLY = {'', 'null', 'none', 'nan'}


def _is_empty_value(v) -> bool:
    if v is None:
        return True
    return str(v).strip().lower() in _NULLY


def _to_int_or_none(v) -> Optional[int]:
    if _is_empty_value(v):
        return None
    try:
        s = str(v).strip()
        if '.' in s:
            return int(float(s))
        return int(s)
    except (ValueError, TypeError):
        return None


def harvhub_notification_strip_tech_words(text: str) -> str:
    if not text:
        return ''
    cleaned = _TECH_RE.sub('', text)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)
    return cleaned.strip()


def harvhub_notification_strip_account_id(text: str) -> str:
    if not text:
        return ''
    for rx in _ACCOUNT_ID_RES:
        text = rx.sub('', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def harvhub_notification_clean_text(value: Any) -> str:
    s = '' if value is None else str(value)
    s = _EMOJI_RE.sub('', s)
    s = harvhub_notification_strip_tech_words(s)
    s = harvhub_notification_strip_account_id(s)
    return s.strip()


# ==============================================================================
# EMAIL ADAPTER
# ==============================================================================

def _send_notification_email(
    recipient: str,
    title: str,
    message: str,
    meta: dict,
) -> bool:
    try:
        from notification_email import send_notification_email
    except Exception as e:
        print(f"[HarvHub Notification Service] email module unavailable: {e}")
        return False

    try:
        return bool(send_notification_email(recipient, title, message, meta))
    except Exception as e:
        print(f"[HarvHub Notification Service] email send raised: {e}")
        return False


# ==============================================================================
# PDO ADAPTER
# ==============================================================================

class _PdoAdapter:
    def __init__(self, query_fn, default_timeout: float = 20.0):
        self._query_fn = query_fn
        self._timeout = default_timeout
        self._in_tx = False

    def query(self, sql: str, params: Optional[list] = None) -> dict:
        try:
            return self._query_fn(sql, params, timeout=self._timeout, quiet=True)
        except TypeError:
            return self._query_fn(sql, params)

    def begin_transaction(self) -> None:
        self._in_tx = True

    def commit(self) -> None:
        self._in_tx = False

    def rollback(self) -> None:
        self._in_tx = False

    @property
    def in_transaction(self) -> bool:
        return self._in_tx


def make_pdo(query_fn) -> _PdoAdapter:
    return _PdoAdapter(query_fn)


# ==============================================================================
# LOW-LEVEL HELPERS
# ==============================================================================

def _is_success(res: dict) -> bool:
    return bool(res) and res.get('status') == 'success'


def _rows(res: dict) -> list:
    if not _is_success(res):
        return []
    return res.get('results') or []


def _first_value(row) -> Any:
    if isinstance(row, dict):
        for v in row.values():
            return v
        return None
    if isinstance(row, (list, tuple)):
        return row[0] if row else None
    return None


def _row_get(row, key: str, default: Any = None) -> Any:
    if not isinstance(row, dict):
        return default
    lk = key.lower()
    for k, v in row.items():
        if isinstance(k, str) and k.strip().lower() == lk:
            return v
    return default


def _normalize_row(row) -> Optional[dict]:
    if row is None:
        return None
    if isinstance(row, dict):
        return {
            (k.strip().lower() if isinstance(k, str) else k): v
            for k, v in row.items()
        }
    if isinstance(row, (list, tuple)):
        return {
            'id':                         row[0]  if len(row) > 0  else None,
            'sub_account_id':             row[1]  if len(row) > 1  else None,
            'main_account_id':            row[2]  if len(row) > 2  else None,
            'email':                      row[3]  if len(row) > 3  else None,
            'broker':                     row[4]  if len(row) > 4  else None,
            'server':                     row[5]  if len(row) > 5  else None,
            'login':                      row[6]  if len(row) > 6  else None,
            'broker_password':            row[7]  if len(row) > 7  else None,
            'broker_login_status':        row[8]  if len(row) > 8  else None,
            'broker_login_attempt_used':  row[9]  if len(row) > 9  else None,
            'broker_total_login_attempt': row[10] if len(row) > 10 else None,
            'demo_account':               row[11] if len(row) > 11 else None,
        }
    return None


# ==============================================================================
# CONTRACT NOTIFICATIONS
# ==============================================================================

def record_contract_notification(pdo, payload: dict) -> Optional[int]:
    email = (payload.get('user_email') or '').strip().lower()
    sub_id = int(payload.get('sub_account_id') or 0)
    main_id = int(payload.get('main_account_id') or 0)
    key = (payload.get('notification_key') or '').strip()
    title = (payload.get('title') or 'Notification').strip()
    message = harvhub_notification_clean_text(payload.get('message') or '')
    ntype = (payload.get('type') or 'info').strip() or 'info'
    section = (payload.get('section') or 'General').strip() or 'General'
    action_tab = payload.get('action_tab')
    if isinstance(action_tab, str):
        action_tab = action_tab.strip() or None
    else:
        action_tab = None
    force = bool(payload.get('force'))

    if (not email or '@' not in email or sub_id <= 0 or not key or not message):
        print('[HarvHub Notification Service] Invalid notification payload.')
        return None

    if not force:
        q = pdo.query(
            "SELECT notification_key FROM contract_notifications "
            "WHERE LOWER(user_email) = %s AND sub_account_id = %s "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            [email, sub_id],
        )
        rows = _rows(q)
        if rows:
            latest_key = str(_first_value(rows[0]) or '')
            if latest_key == key:
                return None

    ins = pdo.query(
        "INSERT INTO contract_notifications "
        "(user_email, sub_account_id, main_account_id, notification_key, "
        " title, message, type, section, action_tab) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        [
            email,
            sub_id,
            main_id if main_id > 0 else 0,
            key[:64],
            title[:255],
            message,
            ntype[:32],
            section[:64],
            action_tab[:64] if action_tab else None,
        ],
    )
    if not _is_success(ins):
        print(
            '[HarvHub Notification Service] Failed to record notification'
            f" | email={email} | message={ins.get('message')}"
        )
        return None

    q = pdo.query(
        "SELECT id FROM contract_notifications "
        "WHERE LOWER(user_email) = %s AND sub_account_id = %s "
        "AND notification_key = %s "
        "ORDER BY id DESC LIMIT 1",
        [email, sub_id, key[:64]],
    )
    rows = _rows(q)
    new_id = int(_first_value(rows[0]) or 0) if rows else 0
    if new_id <= 0:
        return None

    pdo.query(
        "UPDATE harvhub SET unread_notifications = 1 "
        "WHERE LOWER(email) = %s AND sub_account_id = %s",
        [email, sub_id],
    )

    try:
        name_q = pdo.query(
            "SELECT fullname, first_name FROM harvhub "
            "WHERE LOWER(email) = %s ORDER BY id ASC LIMIT 1",
            [email],
        )
        name_rows = _rows(name_q)
        recipient_name = ''
        if name_rows:
            recipient_name = (
                (_row_get(name_rows[0], 'first_name') or '').strip()
                or (_row_get(name_rows[0], 'fullname') or '').strip()
            )

        mail_ok = _send_notification_email(
            email,
            title,
            message,
            {
                'pdo': pdo,
                'section': section,
                'notification_id': new_id,
                'action_tab': action_tab,
                'recipient_name': recipient_name,
            },
        )

        if mail_ok:
            pdo.query(
                "UPDATE contract_notifications "
                "SET email_sent = 1, email_sent_at = CURRENT_TIMESTAMP "
                "WHERE id = %s",
                [new_id],
            )
            print(
                '[HarvHub Notification Service] Notification email marked sent'
                f' | notification_id={new_id} | recipient={email}'
            )
        else:
            print(
                '[HarvHub Notification Service] Notification email returned FALSE'
                f' | notification_id={new_id} | recipient={email}'
            )
    except Exception as e:
        print(
            '[HarvHub Notification Service] Notification email exception'
            f' | notification_id={new_id} | recipient={email} | error={e}'
        )

    return new_id


def record_contract_notification_once(pdo, payload: dict) -> Optional[int]:
    email = (payload.get('user_email') or '').strip().lower()
    sub_id = int(payload.get('sub_account_id') or 0)
    key = (payload.get('notification_key') or '').strip()

    if not email or sub_id <= 0 or not key:
        return None

    q = pdo.query(
        "SELECT id FROM contract_notifications "
        "WHERE LOWER(user_email) = %s AND sub_account_id = %s "
        "AND notification_key = %s "
        "ORDER BY id DESC LIMIT 1",
        [email, sub_id, key[:64]],
    )
    if _rows(q):
        return None

    payload = dict(payload)
    payload['force'] = True
    return record_contract_notification(pdo, payload)


# ==============================================================================
# PROGRAMME NOTIFICATIONS
# ==============================================================================

_ALLOWED_TYPES = {'info', 'success', 'warning', 'danger'}


def record_programme_notification(
    pdo,
    programme_id: int,
    user_email: str,
    opts: dict,
) -> Optional[int]:
    programme_id = int(programme_id or 0)
    user_email = (user_email or '').strip().lower()

    if programme_id <= 0 or not user_email or '@' not in user_email:
        print('[HarvHub Notification Service] Invalid programme notification payload.')
        return None

    key = (opts.get('notification_key') or '').strip()
    if not key:
        key = f'pn-{programme_id}-{int(time.time())}-{id(opts)}'

    title = (opts.get('title') or 'Notification').strip() or 'Notification'
    message = harvhub_notification_clean_text(opts.get('message') or '')
    if not message:
        return None

    ntype = (opts.get('type') or 'info').strip()
    if ntype not in _ALLOWED_TYPES:
        ntype = 'info'

    section = (opts.get('section') or 'General').strip() or 'General'
    action_tab = opts.get('action_tab')
    if isinstance(action_tab, str):
        action_tab = action_tab.strip() or None
    else:
        action_tab = None

    force = bool(opts.get('force'))
    send_email = opts.get('send_email', True)
    if send_email is None:
        send_email = True

    if not force:
        q = pdo.query(
            "SELECT notification_key FROM programme_notifications "
            "WHERE programme_id = %s AND LOWER(user_email) = %s "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            [programme_id, user_email],
        )
        rows = _rows(q)
        if rows:
            latest_key = str(_first_value(rows[0]) or '')
            if latest_key == key:
                return None

    ins = pdo.query(
        "INSERT INTO programme_notifications "
        "(programme_id, user_email, notification_key, title, message, "
        " type, section, action_tab, seen) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0)",
        [
            programme_id,
            user_email,
            key[:190],
            title[:190],
            message,
            ntype,
            section[:60],
            action_tab[:60] if action_tab else None,
        ],
    )
    if not _is_success(ins):
        print(
            '[HarvHub Notification Service] recordProgrammeNotification failed'
            f" | programme_id={programme_id} | email={user_email}"
            f" | message={ins.get('message')}"
        )
        return None

    q = pdo.query(
        "SELECT id FROM programme_notifications "
        "WHERE programme_id = %s AND LOWER(user_email) = %s "
        "AND notification_key = %s "
        "ORDER BY id DESC LIMIT 1",
        [programme_id, user_email, key[:190]],
    )
    rows = _rows(q)
    new_id = int(_first_value(rows[0]) or 0) if rows else 0
    if new_id <= 0:
        return None

    if send_email:
        recipient_name = (opts.get('recipient_name') or '').strip()
        mail_ok = _send_notification_email(
            user_email,
            title,
            message,
            {
                'pdo': pdo,
                'section': section,
                'notification_id': new_id,
                'action_tab': action_tab,
                'recipient_name': recipient_name,
                'source': 'programme',
            },
        )
        if mail_ok:
            print(
                '[HarvHub Notification Service] Programme notification email sent'
                f' | programme_id={programme_id} | notification_id={new_id}'
                f' | recipient={user_email}'
            )
        else:
            print(
                '[HarvHub Notification Service] Programme notification email returned FALSE'
                f' | programme_id={programme_id} | notification_id={new_id}'
                f' | recipient={user_email}'
            )

    return new_id


def record_programme_notification_once(
    pdo,
    programme_id: int,
    user_email: str,
    opts: dict,
) -> Optional[int]:
    programme_id = int(programme_id or 0)
    user_email = (user_email or '').strip().lower()
    key = (opts.get('notification_key') or '').strip()

    if programme_id <= 0 or not user_email or not key:
        return None

    q = pdo.query(
        "SELECT id FROM programme_notifications "
        "WHERE programme_id = %s AND LOWER(user_email) = %s "
        "AND notification_key = %s "
        "ORDER BY id DESC LIMIT 1",
        [programme_id, user_email, key[:190]],
    )
    if _rows(q):
        return None

    opts = dict(opts)
    opts['force'] = True
    return record_programme_notification(pdo, programme_id, user_email, opts)


# ==============================================================================
# BROKER LOGIN STATUS NOTIFICATIONS — INVESTOR / SUB-ACCOUNT
# ==============================================================================

def record_broker_login_status_notification(pdo, user) -> Optional[int]:
    row = _normalize_row(user)
    if row is None:
        print('[HarvHub Notification Service] broker-login: unusable user row shape')
        return None

    email   = (str(row.get('email') or '')).strip().lower()
    sub_id  = _to_int_or_none(row.get('sub_account_id')) or 0
    main_id = _to_int_or_none(row.get('main_account_id')) or 0

    if not email or '@' not in email or sub_id <= 0:
        print(
            '[HarvHub Notification Service] broker-login: invalid identity'
            f' | email={email!r} | sub_id={sub_id!r}'
        )
        return None

    status = (str(row.get('broker_login_status') or '')).strip().lower()

    if status not in ('invalid_credentials', 'fullname_mismatch', 'invalid_account'):
        return None

    broker_cleared = all(
        _is_empty_value(row.get(col))
        for col in ('broker', 'server', 'login', 'broker_password')
    )
    if not broker_cleared:
        print(
            '[HarvHub Notification Service] broker-login: broker columns '
            'not cleared yet, skipping'
        )
        return None

    used_int      = _to_int_or_none(row.get('broker_login_attempt_used'))
    total_attempt = _to_int_or_none(row.get('broker_total_login_attempt')) or 0

    remaining = (
        max(0, total_attempt - used_int)
        if used_int is not None and total_attempt > 0
        else None
    )
    exhausted = (
        used_int is not None
        and total_attempt > 0
        and used_int >= total_attempt
    )

    # ----------------------------------------------------------------
    # INVALID CREDENTIALS
    # ----------------------------------------------------------------
    if status == 'invalid_credentials':
        if used_int is None:
            title = 'Broker Login Error'
            message = (
                'Your broker credentials are invalid. '
                'Please connect your broker details to continue.'
            )
        elif exhausted:
            title = 'Broker Connection Attempts Exhausted'
            message = (
                'Sorry, you have reached the maximum number of broker '
                'connection attempts. No more chances are available on '
                'this account. Please contact support if you believe '
                'this was a mistake.'
            )
        else:
            title = 'Broker Login Error'
            plural = '' if remaining == 1 else 's'
            message = (
                'Your broker credentials are invalid. '
                f'Please reconnect your broker details. '
                f'You have {remaining} connection attempt{plural} left.'
            )

        return record_contract_notification_once(pdo, {
            'user_email': email,
            'sub_account_id': sub_id,
            'main_account_id': main_id,
            'notification_key': f'broker-login-invalid-credentials-{sub_id}',
            'title': title,
            'message': message,
            'type': 'danger',
            'section': 'Broker',
            'action_tab': 'connect_investor_broker',
            'force': False,
        })

    # ----------------------------------------------------------------
    # FULLNAME MISMATCH
    # ----------------------------------------------------------------
    if status == 'fullname_mismatch':
        if used_int is None:
            title = 'Broker Name Mismatch'
            message = (
                "We removed your broker details because the name on your "
                "broker account does not match the name on your HarvHub "
                "profile."
            )
        elif exhausted:
            title = 'Broker Connection Attempts Exhausted'
            message = (
                'Sorry, you have reached the maximum number of broker '
                'connection attempts. No more chances are available on '
                'this account. Please contact support if you believe '
                'this was a mistake.'
            )
        else:
            title = 'Broker Name Mismatch'
            message = (
                "We removed your broker details because the name on your "
                "broker account does not match the name on your HarvHub "
                f"profile. You have {remaining} attempt"
                f"{'' if remaining == 1 else 's'} remaining."
            )

        return record_contract_notification_once(pdo, {
            'user_email': email,
            'sub_account_id': sub_id,
            'main_account_id': main_id,
            'notification_key': f'broker-login-fullname-mismatch-{sub_id}',
            'title': title,
            'message': message,
            'type': 'danger',
            'section': 'Broker',
            'action_tab': 'connect_investor_broker',
            'force': False,
        })

    # ----------------------------------------------------------------
    # INVALID ACCOUNT — demo account used when demo is disallowed
    # ----------------------------------------------------------------
    if status == 'invalid_account':
        if used_int is None or total_attempt <= 0:
            title = 'Demo Account Not Allowed'
            message = (
                'Demo accounts are not allowed on this account. '
                'We removed your broker details. '
                'Please connect a real trading account to continue.'
            )
        elif exhausted:
            title = 'Broker Connection Attempts Exhausted'
            message = (
                'Sorry, you have reached the maximum number of broker '
                'connection attempts. No more chances are available on '
                'this account. Please contact support if you believe '
                'this was a mistake.'
            )
        else:
            title = 'Demo Account Not Allowed'
            plural = '' if remaining == 1 else 's'
            message = (
                'Demo accounts are not allowed on this account. '
                'We removed your broker details. '
                'Please connect a real trading account to continue. '
                f'You have {remaining} attempt{plural} remaining.'
            )

        return record_contract_notification_once(pdo, {
            'user_email': email,
            'sub_account_id': sub_id,
            'main_account_id': main_id,
            'notification_key': f'broker-login-invalid-account-{sub_id}',
            'title': title,
            'message': message,
            'type': 'danger',
            'section': 'Broker',
            'action_tab': 'connect_investor_broker',
            'force': False,
        })

    return None


# ------------------------------------------------------------------------------
# BROKER LOGIN SUCCESS NOTIFICATION — INVESTOR / SUB-ACCOUNT
# ------------------------------------------------------------------------------

def record_broker_login_success_notification(pdo, user) -> Optional[int]:
    row = _normalize_row(user)
    if row is None:
        print('[HarvHub Notification Service] broker-success: unusable user row shape')
        return None

    email   = (str(row.get('email') or '')).strip().lower()
    sub_id  = _to_int_or_none(row.get('sub_account_id')) or 0
    main_id = _to_int_or_none(row.get('main_account_id')) or 0

    if not email or '@' not in email or sub_id <= 0:
        print(
            '[HarvHub Notification Service] broker-success: invalid identity'
            f' | email={email!r} | sub_id={sub_id!r}'
        )
        return None

    demo_raw = row.get('demo_account')
    demo_int = _to_int_or_none(demo_raw)
    is_demo  = (demo_int == 1)

    if is_demo:
        title   = 'Demo Broker Logged On'
        message = (
            'Your demo broker is now logged on to your VPS. '
            'Your terminal is live and ready for programme trades.'
        )
        ntype   = 'info'
    else:
        title   = 'Broker Logged On'
        message = (
            'Your broker is now logged on to your VPS. '
            'Your terminal is live and ready for programme trades.'
        )
        ntype   = 'success'

    return record_contract_notification(pdo, {
        'user_email': email,
        'sub_account_id': sub_id,
        'main_account_id': main_id,
        'notification_key': f'broker-login-success-{sub_id}-{int(time.time())}',
        'title': title,
        'message': message,
        'type': ntype,
        'section': 'Broker',
        'action_tab': 'connect_investor_broker',
        'force': True,
    })


# ------------------------------------------------------------------------------
# BROKER LOGIN RECONNECTED NOTIFICATION — INVESTOR / SUB-ACCOUNT
# ------------------------------------------------------------------------------
# Fires when the DB already said valid_credentials and the terminal was
# observed DARK (missing / IPC-failed) on a previous probe but is now
# live again. This is a status change, not a re-confirmation.

def record_broker_login_reconnected_notification(pdo, user) -> Optional[int]:
    row = _normalize_row(user)
    if row is None:
        print('[HarvHub Notification Service] broker-reconnected: unusable user row shape')
        return None

    email   = (str(row.get('email') or '')).strip().lower()
    sub_id  = _to_int_or_none(row.get('sub_account_id')) or 0
    main_id = _to_int_or_none(row.get('main_account_id')) or 0

    if not email or '@' not in email or sub_id <= 0:
        print(
            '[HarvHub Notification Service] broker-reconnected: invalid identity'
            f' | email={email!r} | sub_id={sub_id!r}'
        )
        return None

    demo_int = _to_int_or_none(row.get('demo_account'))
    is_demo  = (demo_int == 1)

    if is_demo:
        title   = 'Demo Broker Reconnected'
        message = (
            'Your demo broker terminal was inactive and has now been '
            'relaunched and logged back on to your VPS. Your terminal is '
            'live and ready for programme trades again.'
        )
        ntype   = 'info'
    else:
        title   = 'Broker Reconnected'
        message = (
            'Your broker terminal was inactive and has now been '
            'relaunched and logged back on to your VPS. Your terminal is '
            'live and ready for programme trades again.'
        )
        ntype   = 'success'

    return record_contract_notification(pdo, {
        'user_email': email,
        'sub_account_id': sub_id,
        'main_account_id': main_id,
        'notification_key': f'broker-login-reconnected-{sub_id}-{int(time.time())}',
        'title': title,
        'message': message,
        'type': ntype,
        'section': 'Broker',
        'action_tab': 'connect_investor_broker',
        'force': True,
    })


# ------------------------------------------------------------------------------
# DISCONNECT BROKER COMPLETED NOTIFICATION — INVESTOR / SUB-ACCOUNT
# ------------------------------------------------------------------------------

def record_disconnect_broker_completed_notification(pdo, user) -> Optional[int]:
    row = _normalize_row(user)
    if row is None:
        print('[HarvHub Notification Service] disconnect-completed: unusable row shape')
        return None

    email   = (str(row.get('email') or '')).strip().lower()
    sub_id  = _to_int_or_none(row.get('sub_account_id')) or 0
    main_id = _to_int_or_none(row.get('main_account_id')) or 0

    if not email or '@' not in email or sub_id <= 0:
        print(
            '[HarvHub Notification Service] disconnect-completed: invalid identity'
            f' | email={email!r} | sub_id={sub_id!r}'
        )
        return None

    return record_contract_notification(pdo, {
        'user_email': email,
        'sub_account_id': sub_id,
        'main_account_id': main_id,
        'notification_key': f'broker-disconnect-completed-{sub_id}-{int(time.time())}',
        'title': 'Broker Disconnection Complete',
        'message': (
            'Your broker terminal has been removed from the VPS and the '
            'disconnection process is now complete. You can add new '
            'broker details whenever you are ready.'
        ),
        'type': 'success',
        'section': 'Broker',
        'action_tab': 'connect_investor_broker',
        'force': True,
    })


# ------------------------------------------------------------------------------
# BALANCE VERIFICATION UPDATED NOTIFICATION — INVESTOR / SUB-ACCOUNT
# ------------------------------------------------------------------------------
# Fires once per sub-account the first time the harvhub row flips from
# balance_verification='applied-for-verification' to 'verified' (and
# broker_balance is written). Uses record_contract_notification_once so
# the user only ever receives ONE balance-verification email per
# sub-account, regardless of how many times the verification loop runs.

def record_balance_verification_notification(pdo, user) -> Optional[int]:
    row = _normalize_row(user)
    if row is None:
        print('[HarvHub Notification Service] balance-verification: unusable row shape')
        return None

    email   = (str(row.get('email') or '')).strip().lower()
    sub_id  = _to_int_or_none(row.get('sub_account_id')) or 0
    main_id = _to_int_or_none(row.get('main_account_id')) or 0

    if not email or '@' not in email or sub_id <= 0:
        print(
            '[HarvHub Notification Service] balance-verification: invalid identity'
            f' | email={email!r} | sub_id={sub_id!r}'
        )
        return None

    return record_contract_notification_once(pdo, {
        'user_email': email,
        'sub_account_id': sub_id,
        'main_account_id': main_id,
        'notification_key': f'balance-verification-{sub_id}',
        'title': 'MT5 Balance Verification Updated',
        'message': (
            'Your MT5 balance verification has been updated. '
            'Go to your dashboard for more details.'
        ),
        'type': 'success',
        'section': 'Broker',
        'action_tab': 'connect_investor_broker',
        'force': False,
    })


# ==============================================================================
# BROKER LOGIN STATUS NOTIFICATIONS — PROGRAMME / TRADER
# ==============================================================================

def record_programme_broker_login_status_notification(pdo, row) -> Optional[int]:
    row = _normalize_row(row)
    if row is None:
        print('[HarvHub Notification Service] prog-broker-login: unusable row shape')
        return None

    email        = (str(row.get('email') or '')).strip().lower()
    programme_id = _to_int_or_none(row.get('id')) or 0

    if not email or '@' not in email or programme_id <= 0:
        print(
            '[HarvHub Notification Service] prog-broker-login: invalid identity'
            f' | email={email!r} | programme_id={programme_id!r}'
        )
        return None

    status = (str(row.get('broker_login_status') or '')).strip().lower()

    if status not in ('invalid_credentials', 'fullname_mismatch'):
        return None

    broker_cleared = all(
        _is_empty_value(row.get(col))
        for col in ('broker', 'server', 'login', 'broker_password')
    )
    if not broker_cleared:
        print(
            '[HarvHub Notification Service] prog-broker-login: broker columns '
            'not cleared yet, skipping'
        )
        return None

    used_int      = _to_int_or_none(row.get('broker_login_attempt_used'))
    total_attempt = _to_int_or_none(row.get('broker_total_login_attempt')) or 0

    remaining = (
        max(0, total_attempt - used_int)
        if used_int is not None and total_attempt > 0
        else None
    )
    exhausted = (
        used_int is not None
        and total_attempt > 0
        and used_int >= total_attempt
    )

    if status == 'invalid_credentials':
        if used_int is None:
            title = 'Programme Broker Login Error'
            message = (
                'Your programme broker credentials are invalid. '
                'Please connect your programme broker details to continue.'
            )
        elif exhausted:
            title = 'Programme Broker Connection Attempts Exhausted'
            message = (
                'Sorry, you have reached the maximum number of programme '
                'broker connection attempts. No more chances are available '
                'on this programme. Please contact support if you believe '
                'this was a mistake.'
            )
        else:
            title = 'Programme Broker Login Error'
            plural = '' if remaining == 1 else 's'
            message = (
                'Your programme broker credentials are invalid. '
                f'Please reconnect your programme broker details. '
                f'You have {remaining} connection attempt{plural} left.'
            )

        return record_programme_notification_once(
            pdo,
            programme_id,
            email,
            {
                'notification_key': f'prog-broker-login-invalid-credentials-{programme_id}',
                'title': title,
                'message': message,
                'type': 'danger',
                'section': 'Broker',
                'action_tab': 'connect_trader_broker',
                'force': False,
            },
        )

    if status == 'fullname_mismatch':
        if used_int is None:
            title = 'Programme Broker Name Mismatch'
            message = (
                "We removed your programme broker details because the name "
                "on your broker account does not match the name registered "
                "on your HarvHub profile."
            )
        elif exhausted:
            title = 'Programme Broker Connection Attempts Exhausted'
            message = (
                'Sorry, you have reached the maximum number of programme '
                'broker connection attempts. No more chances are available '
                'on this programme. Please contact support if you believe '
                'this was a mistake.'
            )
        else:
            title = 'Programme Broker Name Mismatch'
            message = (
                "We removed your programme broker details because the name "
                "on your broker account does not match the name registered "
                f"on your HarvHub profile. You have {remaining} attempt"
                f"{'' if remaining == 1 else 's'} remaining."
            )

        return record_programme_notification_once(
            pdo,
            programme_id,
            email,
            {
                'notification_key': f'prog-broker-login-fullname-mismatch-{programme_id}',
                'title': title,
                'message': message,
                'type': 'danger',
                'section': 'Broker',
                'action_tab': 'connect_trader_broker',
                'force': False,
            },
        )

    return None


# ------------------------------------------------------------------------------
# BROKER LOGIN SUCCESS NOTIFICATION — PROGRAMME / TRADER
# ------------------------------------------------------------------------------

def record_programme_broker_login_success_notification(pdo, row) -> Optional[int]:
    row = _normalize_row(row)
    if row is None:
        print('[HarvHub Notification Service] prog-broker-success: unusable row shape')
        return None

    email        = (str(row.get('email') or '')).strip().lower()
    programme_id = _to_int_or_none(row.get('id')) or 0

    if not email or '@' not in email or programme_id <= 0:
        print(
            '[HarvHub Notification Service] prog-broker-success: invalid identity'
            f' | email={email!r} | programme_id={programme_id!r}'
        )
        return None

    demo_int = _to_int_or_none(row.get('demo_account'))
    is_demo  = (demo_int == 1)

    if is_demo:
        title   = 'Programme Demo Broker Logged On'
        message = (
            'Your programme demo broker is now logged on to your VPS. '
            'Your terminal is live and ready to analyse the programme.'
        )
        ntype   = 'info'
    else:
        title   = 'Programme Broker Logged On'
        message = (
            'Your programme broker is now logged on to your VPS. '
            'Your terminal is live and ready to analyse the programme.'
        )
        ntype   = 'success'

    return record_programme_notification(
        pdo,
        programme_id,
        email,
        {
            'notification_key': f'prog-broker-login-success-{programme_id}-{int(time.time())}',
            'title': title,
            'message': message,
            'type': ntype,
            'section': 'Broker',
            'action_tab': 'connect_trader_broker',
            'force': True,
            'send_email': True,
        },
    )


# ------------------------------------------------------------------------------
# BROKER LOGIN RECONNECTED NOTIFICATION — PROGRAMME / TRADER
# ------------------------------------------------------------------------------
# Fires when the DB already said valid_credentials and the terminal was
# observed DARK (missing / IPC-failed) on a previous probe but is now
# live again.

def record_programme_broker_login_reconnected_notification(pdo, row) -> Optional[int]:
    row = _normalize_row(row)
    if row is None:
        print('[HarvHub Notification Service] prog-broker-reconnected: unusable row shape')
        return None

    email        = (str(row.get('email') or '')).strip().lower()
    programme_id = _to_int_or_none(row.get('id')) or 0

    if not email or '@' not in email or programme_id <= 0:
        print(
            '[HarvHub Notification Service] prog-broker-reconnected: invalid identity'
            f' | email={email!r} | programme_id={programme_id!r}'
        )
        return None

    demo_int = _to_int_or_none(row.get('demo_account'))
    is_demo  = (demo_int == 1)

    if is_demo:
        title   = 'Programme Demo Broker Reconnected'
        message = (
            'Your programme demo broker terminal was inactive and has now '
            'been relaunched and logged back on to your VPS. Your terminal '
            'is live and ready to analyse the programme again.'
        )
        ntype   = 'info'
    else:
        title   = 'Programme Broker Reconnected'
        message = (
            'Your programme broker terminal was inactive and has now '
            'been relaunched and logged back on to your VPS. Your terminal '
            'is live and ready to analyse the programme again.'
        )
        ntype   = 'success'

    return record_programme_notification(
        pdo,
        programme_id,
        email,
        {
            'notification_key': f'prog-broker-login-reconnected-{programme_id}-{int(time.time())}',
            'title': title,
            'message': message,
            'type': ntype,
            'section': 'Broker',
            'action_tab': 'connect_trader_broker',
            'force': True,
            'send_email': True,
        },
    )


# ------------------------------------------------------------------------------
# DISCONNECT BROKER COMPLETED NOTIFICATION — PROGRAMME / TRADER
# ------------------------------------------------------------------------------

def record_programme_disconnect_broker_completed_notification(pdo, row) -> Optional[int]:
    row = _normalize_row(row)
    if row is None:
        print('[HarvHub Notification Service] prog-disconnect-completed: unusable row shape')
        return None

    email        = (str(row.get('email') or '')).strip().lower()
    programme_id = _to_int_or_none(row.get('id')) or 0

    if not email or '@' not in email or programme_id <= 0:
        print(
            '[HarvHub Notification Service] prog-disconnect-completed: invalid identity'
            f' | email={email!r} | programme_id={programme_id!r}'
        )
        return None

    return record_programme_notification(
        pdo,
        programme_id,
        email,
        {
            'notification_key': f'prog-broker-disconnect-completed-{programme_id}-{int(time.time())}',
            'title': 'Programme Broker Disconnection Complete',
            'message': (
                'Your programme broker terminal has been removed from the VPS '
                'and the disconnection process is now complete. You can add '
                'new programme broker details whenever you are ready.'
            ),
            'type': 'success',
            'section': 'Broker',
            'action_tab': 'connect_trader_broker',
            'force': True,
            'send_email': True,
        },
    )


# ==============================================================================
# PROGRAMME-SCOPED RESTRICTION + DAILY-TARGET NOTIFICATIONS
# ==============================================================================
# All of these go ONLY to the programme owner (email is resolved by the
# caller from programme.userid -> harvhub.email). Nothing is ever sent
# to investors. All use dedup keys so a repeated run within the same
# day does not spam the programme owner.

def _format_time_label_12h(raw: str) -> str:
    """
    Best-effort normaliser. The caller already passes a 12h label
    ('9:00 AM'), but if raw is 24h ('09:00') we still convert.
    """
    s = (raw or '').strip()
    if not s:
        return ''
    if re.search(r'\b(am|pm)\b', s, re.IGNORECASE):
        return s
    m = re.match(r'^(\d{1,2}):(\d{2})(?::\d{2})?$', s)
    if not m:
        return s
    try:
        h = int(m.group(1))
        mi = int(m.group(2))
    except Exception:
        return s
    period = 'AM' if h < 12 else 'PM'
    h12 = h % 12 or 12
    return f"{h12}:{mi:02d} {period}"


# ------------------------------------------------------------------------------
# RESTRICTED DATE — full-day lockout from accountmanagement_restricted_dates
# ------------------------------------------------------------------------------

def record_programme_restriction_date_notification(
    pdo,
    programme_id: int,
    programme_name: str,
    owner_email: str,
    restricted_date: str,
    timezone_str: str,
) -> Optional[int]:
    programme_id = int(programme_id or 0)
    owner_email = (owner_email or '').strip().lower()
    programme_name = (programme_name or '').strip() or f"programme {programme_id}"
    restricted_date = (restricted_date or '').strip()
    timezone_str = (timezone_str or '').strip() or 'your configured'

    if programme_id <= 0 or not owner_email or '@' not in owner_email:
        print('[HarvHub Notification Service] restriction-date: invalid identity')
        return None
    if not restricted_date:
        return None

    title = 'Trading Paused Today'
    message = (
        f"Just a heads-up: today is the date {restricted_date} you added "
        f"to pause trading. No trading activity will "
        f"take place today in the {timezone_str} timezone for your investors as well."
    )

    return record_programme_notification_once(
        pdo,
        programme_id,
        owner_email,
        {
            'notification_key': (
                f'prog-restricted-date-{programme_id}-{restricted_date}'
            ),
            'title': title,
            'message': message,
            'type': 'warning',
            'section': 'Programme',
            'action_tab': 'account_management',
            'force': False,
            'send_email': True,
            'recipient_name': programme_name,
        },
    )


# ------------------------------------------------------------------------------
# RESTRICTED DAY — FULL DAY (from accountmanagement_restricted_days)
# ------------------------------------------------------------------------------

def record_programme_restriction_day_full_notification(
    pdo,
    programme_id: int,
    programme_name: str,
    owner_email: str,
    day_name: str,
    restricted_date: str,
    timezone_str: str,
) -> Optional[int]:
    programme_id = int(programme_id or 0)
    owner_email = (owner_email or '').strip().lower()
    programme_name = (programme_name or '').strip() or f"programme {programme_id}"
    day_name = (day_name or '').strip() or 'today'
    restricted_date = (restricted_date or '').strip()
    timezone_str = (timezone_str or '').strip() or 'your configured'

    if programme_id <= 0 or not owner_email or '@' not in owner_email:
        print('[HarvHub Notification Service] restriction-day-full: invalid identity')
        return None

    title = f'Trading Paused All Day on {day_name}'
    message = (
        f"Your programme has {day_name} set as a fully paused trading day, "
        f"so your investors get a breather today. No trading activity will "
        f"take place for your investors."
    )

    return record_programme_notification_once(
        pdo,
        programme_id,
        owner_email,
        {
            'notification_key': (
                f'prog-restricted-day-full-{programme_id}-{restricted_date}'
            ),
            'title': title,
            'message': message,
            'type': 'warning',
            'section': 'Programme',
            'action_tab': 'account_management',
            'force': False,
            'send_email': True,
            'recipient_name': programme_name,
        },
    )


# ------------------------------------------------------------------------------
# RESTRICTED DAY — TIME WINDOW
# ------------------------------------------------------------------------------

def record_programme_restriction_day_window_notification(
    pdo,
    programme_id: int,
    programme_name: str,
    owner_email: str,
    day_name: str,
    restricted_date: str,
    from_label: str,
    to_label: str,
    timezone_str: str,
) -> Optional[int]:
    programme_id = int(programme_id or 0)
    owner_email = (owner_email or '').strip().lower()
    programme_name = (programme_name or '').strip() or f"programme {programme_id}"
    day_name = (day_name or '').strip() or 'today'
    restricted_date = (restricted_date or '').strip()
    timezone_str = (timezone_str or '').strip() or 'your configured'

    from_label = _format_time_label_12h(from_label)
    to_label = _format_time_label_12h(to_label)

    if programme_id <= 0 or not owner_email or '@' not in owner_email:
        print('[HarvHub Notification Service] restriction-day-window: invalid identity')
        return None

    if from_label and to_label:
        window_text = f"from {from_label} to {to_label}"
    elif from_label:
        window_text = f"from {from_label} onwards"
    elif to_label:
        window_text = f"up to {to_label}"
    else:
        window_text = "for the configured window"

    title = f'Trading Paused on {day_name}'
    message = (
        f"Today is {day_name}, and your programme has a trading pause "
        f"scheduled {window_text} in the {timezone_str} timezone, giving "
        f"your investors a short break during that window. Trade activity "
        f"across your investors is paused for that period."
    )

    return record_programme_notification_once(
        pdo,
        programme_id,
        owner_email,
        {
            'notification_key': (
                f'prog-restricted-day-window-{programme_id}-'
                f'{restricted_date}-{from_label}-{to_label}'
            ),
            'title': title,
            'message': message,
            'type': 'warning',
            'section': 'Programme',
            'action_tab': 'account_management',
            'force': False,
            'send_email': True,
            'recipient_name': programme_name,
        },
    )


# ------------------------------------------------------------------------------
# DAILY TARGET SUMMARY (roll-up)
# ------------------------------------------------------------------------------

def record_programme_daily_target_summary_notification(
    pdo,
    programme_id: int,
    programme_name: str,
    owner_email: str,
    met_count: int,
    total_count: int,
    trade_date: str,
    timezone_str: str = 'Africa/Lagos',
) -> Optional[int]:
    """
    Roll-up notification sent to the programme owner whenever at least
    one investor has met the daily target for the given trade date.

    Called from `recent_highest_balance_target()` (later). This helper
    is intentionally decoupled so you can wire it in without touching
    the existing stats flow.

    Dedup: keyed on (programme_id, trade_date, met_count, total_count)
    so repeated runs with the same numbers do not spam, but a change in
    the counts re-sends (that's the point of a progress signal).
    """
    programme_id = int(programme_id or 0)
    owner_email = (owner_email or '').strip().lower()
    programme_name = (programme_name or '').strip() or f"programme {programme_id}"
    trade_date = (trade_date or '').strip()
    timezone_str = (timezone_str or '').strip() or 'Africa/Lagos'

    try:
        met_count = int(met_count or 0)
        total_count = int(total_count or 0)
    except Exception:
        return None

    if programme_id <= 0 or not owner_email or '@' not in owner_email:
        print('[HarvHub Notification Service] daily-target-summary: invalid identity')
        return None

    if total_count <= 0:
        return None

    # Only send when at least one investor has met the target, per spec.
    if met_count <= 0:
        return None

    pending_count = max(0, total_count - met_count)

    if pending_count == 0:
        title = 'All Investors Met Their Daily Target'
        message = (
            f"Great news. All {total_count} of your active investors have "
            f"met their daily target for {trade_date} "
            f"({timezone_str} timezone)."
        )
        ntype = 'success'
    else:
        title = 'Daily Target Progress'
        message = (
            f"{met_count} of your investors have met their daily target "
            f"while {pending_count} are yet to meet theirs for {trade_date} "
            f"({timezone_str} timezone)."
        )
        ntype = 'info'

    return record_programme_notification(
        pdo,
        programme_id,
        owner_email,
        {
            'notification_key': (
                f'prog-daily-target-summary-{programme_id}-{trade_date}-'
                f'{met_count}-{total_count}'
            ),
            'title': title,
            'message': message,
            'type': ntype,
            'section': 'Programme',
            'action_tab': 'programme_statistics',
            'force': True,
            'send_email': True,
            'recipient_name': programme_name,
        },
    )


# ==============================================================================
# READ HELPERS
# ==============================================================================

def get_contract_notifications(
    pdo, email: str, sub_account_id: int, limit: int = 100
) -> list:
    email = (email or '').strip().lower()
    sub_account_id = int(sub_account_id or 0)
    limit = max(1, min(200, int(limit or 100)))

    q = pdo.query(
        "SELECT id, notification_key, title, message, type, section, "
        "action_tab, read_at, created_at "
        "FROM contract_notifications "
        "WHERE LOWER(user_email) = %s AND sub_account_id = %s "
        "ORDER BY created_at DESC, id DESC "
        f"LIMIT {limit}",
        [email, sub_account_id],
    )
    out = []
    for row in _rows(q):
        out.append({
            'id': int(_row_get(row, 'id') or 0),
            'notification_key': str(_row_get(row, 'notification_key') or ''),
            'title': str(_row_get(row, 'title') or ''),
            'section': str(_row_get(row, 'section') or 'General'),
            'message': harvhub_notification_clean_text(_row_get(row, 'message')),
            'time': _row_get(row, 'created_at'),
            'type': str(_row_get(row, 'type') or 'info'),
            'action_tab': _row_get(row, 'action_tab'),
            'update': 'read' if _row_get(row, 'read_at') else 'new',
        })
    return out


def get_programme_notifications(
    pdo, programme_id: int, user_email: str, limit: int = 100
) -> list:
    programme_id = int(programme_id or 0)
    user_email = (user_email or '').strip().lower()
    limit = max(1, min(200, int(limit or 100)))

    if programme_id <= 0 or not user_email:
        return []

    q = pdo.query(
        "SELECT id, notification_key, title, message, type, section, "
        "action_tab, seen, created_at "
        "FROM programme_notifications "
        "WHERE programme_id = %s AND LOWER(user_email) = %s "
        "ORDER BY created_at DESC, id DESC "
        f"LIMIT {limit}",
        [programme_id, user_email],
    )
    out = []
    for row in _rows(q):
        out.append({
            'id': int(_row_get(row, 'id') or 0),
            'notification_key': str(_row_get(row, 'notification_key') or ''),
            'title': str(_row_get(row, 'title') or ''),
            'section': str(_row_get(row, 'section') or 'General'),
            'message': harvhub_notification_clean_text(_row_get(row, 'message')),
            'time': _row_get(row, 'created_at'),
            'type': str(_row_get(row, 'type') or 'info'),
            'action_tab': _row_get(row, 'action_tab'),
            'update': 'read' if int(_row_get(row, 'seen') or 0) == 1 else 'new',
        })
    return out


def get_notification_unread_count(pdo, email: str, sub_account_id: int) -> int:
    email = (email or '').strip().lower()
    sub_account_id = int(sub_account_id or 0)
    if not email or sub_account_id <= 0:
        return 0
    q = pdo.query(
        "SELECT COUNT(*) AS c FROM contract_notifications "
        "WHERE LOWER(user_email) = %s AND sub_account_id = %s "
        "AND read_at IS NULL",
        [email, sub_account_id],
    )
    rows = _rows(q)
    return int(_first_value(rows[0]) or 0) if rows else 0


def get_programme_notification_unread_count(
    pdo, programme_id: int, user_email: str
) -> int:
    programme_id = int(programme_id or 0)
    user_email = (user_email or '').strip().lower()
    if programme_id <= 0 or not user_email:
        return 0
    q = pdo.query(
        "SELECT COUNT(*) AS c FROM programme_notifications "
        "WHERE programme_id = %s AND LOWER(user_email) = %s "
        "AND seen = 0",
        [programme_id, user_email],
    )
    rows = _rows(q)
    return int(_first_value(rows[0]) or 0) if rows else 0


def mark_contract_notifications_read(
    pdo, email: str, sub_account_id: int
) -> bool:
    email = (email or '').strip().lower()
    sub_account_id = int(sub_account_id or 0)
    if not email or sub_account_id <= 0:
        return False

    pdo.query(
        "UPDATE contract_notifications "
        "SET read_at = COALESCE(read_at, CURRENT_TIMESTAMP) "
        "WHERE LOWER(user_email) = %s AND sub_account_id = %s "
        "AND read_at IS NULL",
        [email, sub_account_id],
    )
    pdo.query(
        "UPDATE harvhub SET unread_notifications = 0 "
        "WHERE LOWER(email) = %s AND sub_account_id = %s",
        [email, sub_account_id],
    )
    return True


def mark_programme_notifications_seen(
    pdo, programme_id: int, user_email: str
) -> bool:
    programme_id = int(programme_id or 0)
    user_email = (user_email or '').strip().lower()
    if programme_id <= 0 or not user_email:
        return False
    pdo.query(
        "UPDATE programme_notifications SET seen = 1 "
        "WHERE programme_id = %s AND LOWER(user_email) = %s AND seen = 0",
        [programme_id, user_email],
    )
    return True


def sync_notification_unread_flag(
    pdo, email: str, sub_account_id: int
) -> None:
    email = (email or '').strip().lower()
    sub_account_id = int(sub_account_id or 0)
    if not email or sub_account_id <= 0:
        return
    q = pdo.query(
        "SELECT COUNT(*) AS c FROM contract_notifications "
        "WHERE LOWER(user_email) = %s AND sub_account_id = %s "
        "AND read_at IS NULL",
        [email, sub_account_id],
    )
    rows = _rows(q)
    count = int(_first_value(rows[0]) or 0) if rows else 0
    pdo.query(
        "UPDATE harvhub SET unread_notifications = %s "
        "WHERE sub_account_id = %s AND LOWER(email) = %s",
        [1 if count > 0 else 0, sub_account_id, email],
    )
# ==============================================================================
# INVESTOR-SIDE UNAUTHORIZED ACTION NOTIFICATION
# ==============================================================================
# Fires when an investor's sub-account has actions that do not belong to
# any magic number issued by the programme. One notification per investor
# per programme per day (dedup by date).

def record_investor_unauthorized_action_notification(
    pdo,
    programme_id: int,
    programme_name: str,
    investor_email: str,
    investor_id: int,
    sub_account_id: int,
    unauthorized_types: list,
    unauthorized_pnl: float,
    unaccounted_deficit: float,
) -> Optional[int]:
    """
    Notify the investor's sub-account that unauthorized actions were
    detected on a programme they invested in.

    unauthorized_types is a list of strings such as:
        ['unauthorized_trades', 'unauthorized_orders',
         'unauthorized_positions', 'unaccounted_balance_deficit']
    """
    programme_id = int(programme_id or 0)
    investor_email = (investor_email or '').strip().lower()
    programme_name = (programme_name or '').strip() or f"programme {programme_id}"

    if programme_id <= 0 or not investor_email or '@' not in investor_email:
        print('[HarvHub Notification Service] investor-unauth: invalid identity')
        return None

    today = _unauth_today_key()
    parts = _unauth_summary_parts(
        unauthorized_types, unauthorized_pnl, unaccounted_deficit
    )

    if not parts:
        return None

    summary = ", ".join(parts)

    # Danger if anything more serious than pending orders was found
    has_serious = any(
        t in ('unauthorized_trades', 'unauthorized_positions',
              'unaccounted_balance_deficit')
        for t in (unauthorized_types or [])
    )
    ntype = 'danger' if has_serious else 'warning'

    title = 'Unauthorized Actions Detected'
    message = (
        f"We detected unauthorized actions on your programme "
        f"'{programme_name}': {summary}. This means trading activity was "
        f"observed outside the magic numbers issued by the programme. "
        f"Please stop any manual or third-party trading on this "
        f"sub-account immediately to avoid contract violations."
    )

    return record_programme_notification_once(
        pdo,
        programme_id,
        investor_email,
        {
            'notification_key': (
                f'prog-unauth-investor-{programme_id}-{sub_account_id}-{today}'
            ),
            'title': title,
            'message': message,
            'type': ntype,
            'section': 'Unauthorized',
            'action_tab': 'activity',
            'force': False,
            'send_email': True,
            'recipient_name': f"investor {investor_id}",
        },
    )


# ==============================================================================
# PROGRAMME-OWNER-SIDE UNAUTHORIZED ACTION NOTIFICATION
# ==============================================================================
# Fires when one of the programme owner's investors has actions that do
# not belong to any magic number the programme issued. One notification
# per investor per programme per day (dedup by date).

def record_programme_owner_unauthorized_action_notification(
    pdo,
    programme_id: int,
    programme_name: str,
    owner_email: str,
    investor_id: int,
    sub_account_id: int,
    unauthorized_types: list,
    unauthorized_pnl: float,
    unaccounted_deficit: float,
) -> Optional[int]:
    """
    Notify the programme owner that one of their investors violated the
    contract agreement.
    """
    programme_id = int(programme_id or 0)
    owner_email = (owner_email or '').strip().lower()
    programme_name = (programme_name or '').strip() or f"programme {programme_id}"

    if programme_id <= 0 or not owner_email or '@' not in owner_email:
        print('[HarvHub Notification Service] owner-unauth: invalid identity')
        return None

    today = _unauth_today_key()
    parts = _unauth_summary_parts(
        unauthorized_types, unauthorized_pnl, unaccounted_deficit
    )

    if not parts:
        return None

    summary = ", ".join(parts)

    title = f'Contract Violation — Investor {investor_id}'
    message = (
        f"Investor {investor_id} (sub-account {sub_account_id}) on your "
        f"programme '{programme_name}' has violated the contract "
        f"agreement: {summary}. The investor's trading activity is "
        f"outside the magic numbers your programme issued. Please review "
        f"and take the appropriate action."
    )

    return record_programme_notification_once(
        pdo,
        programme_id,
        owner_email,
        {
            'notification_key': (
                f'prog-unauth-owner-{programme_id}-{sub_account_id}-{today}'
            ),
            'title': title,
            'message': message,
            'type': 'danger',
            'section': 'Unauthorized',
            'action_tab': 'programme_investors',
            'force': False,
            'send_email': True,
            'recipient_name': programme_name,
        },
    )


# ==============================================================================
# INTERNAL HELPERS FOR THE TWO HELPERS ABOVE
# ==============================================================================

def _unauth_today_key() -> str:
    from datetime import datetime, timezone, timedelta
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Africa/Lagos")
    except Exception:
        tz = timezone(timedelta(hours=1))
    return datetime.now(tz).strftime("%Y-%m-%d")


def _unauth_summary_parts(unauthorized_types, unauthorized_pnl, unaccounted_deficit) -> list:
    """
    Turn the raw classification into the human-readable fragments used
    by both the investor-side and owner-side messages.
    """
    parts = []
    ut = set(unauthorized_types or [])

    if 'unauthorized_trades' in ut:
        if unauthorized_pnl > 0.01:
            parts.append(
                f"closed trades placed outside the programme "
                f"(net P&L +${unauthorized_pnl:.2f})"
            )
        elif unauthorized_pnl < -0.01:
            parts.append(
                f"closed trades placed outside the programme "
                f"(net P&L −${abs(unauthorized_pnl):.2f})"
            )
        else:
            parts.append("closed trades placed outside the programme")

    if 'unauthorized_orders' in ut:
        parts.append("pending orders placed outside the programme")

    if 'unauthorized_positions' in ut:
        parts.append("open positions placed outside the programme")

    if 'unaccounted_balance_deficit' in ut or (unaccounted_deficit or 0.0) > 0.01:
        parts.append(
            f"an unaccounted balance deficit of "
            f"${float(unaccounted_deficit or 0.0):.2f}"
        )

    return parts