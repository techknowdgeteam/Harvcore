# notification_email.py
"""
Python port of HarvHub's notification_email.php.

Credentials are pulled from `server_account` on every call:
    server_account.mailer_email    -> Brevo verified sender email
    server_account.mailer_password -> Brevo API key

Brevo endpoint: POST https://api.brevo.com/v3/smtp/email
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Any


_BREVO_URL = 'https://api.brevo.com/v3/smtp/email'


def _row_get(row: dict, key: str, default: Any = None) -> Any:
    if not isinstance(row, dict):
        return default
    lk = key.lower()
    for k, v in row.items():
        if isinstance(k, str) and k.strip().lower() == lk:
            return v
    return default


def _fetch_mailer_credentials(pdo) -> tuple[str, str]:
    """
    Returns (mailer_email, brevo_api_key). Empty strings on failure.
    """
    try:
        res = pdo.query(
            "SELECT mailer_email, mailer_password "
            "FROM server_account WHERE id = 1 LIMIT 1",
            None,
        )
    except Exception as e:
        print(f'[HarvHub Notification Email] credentials query raised: {e}')
        return '', ''

    if not res or res.get('status') != 'success':
        print(
            '[HarvHub Notification Email] credentials query failed: '
            f"{res.get('message') if res else 'no response'}"
        )
        return '', ''

    rows = res.get('results') or []
    if not rows:
        print('[HarvHub Notification Email] server_account row missing.')
        return '', ''

    mailer_email = str(_row_get(rows[0], 'mailer_email') or '').strip()
    api_key = str(_row_get(rows[0], 'mailer_password') or '').strip()
    return mailer_email, api_key


def _html_escape(text: str) -> str:
    return (
        text.replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&#39;')
    )


def _build_html(safe_title: str, safe_message: str) -> str:
    safe_message_html = _html_escape(safe_message).replace('\n', '<br>')
    safe_title_esc = _html_escape(safe_title)
    return (
        '<!DOCTYPE html>'
        '<html lang="en"><head>'
        '<meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        f'<title>{safe_title_esc}</title>'
        '</head>'
        '<body style="margin:0;padding:0;background-color:#f4f5f7;'
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,"
        'Helvetica,Arial,sans-serif;color:#111827;">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        'border="0" style="background-color:#f4f5f7;padding:40px 16px;">'
        '<tr><td align="center">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        'border="0" style="max-width:620px;background-color:#ffffff;'
        'border-radius:14px;box-shadow:0 2px 8px rgba(0,0,0,0.05);overflow:hidden;">'
        '<tr><td style="padding:32px 28px 28px;">'
        f'<p style="font-size:15px;line-height:1.7;margin:0;color:#4b5563;">'
        f'{safe_message_html}</p>'
        '</td></tr></table></td></tr></table></body></html>'
    )


def send_notification_email(
    recipient: str,
    title: str,
    message: str,
    meta: dict | None = None,
) -> bool:
    meta = meta or {}
    recipient = (recipient or '').strip().lower()
    if not recipient or '@' not in recipient:
        print(f'[HarvHub Notification Email] Invalid recipient: {recipient}')
        return False

    pdo = meta.get('pdo')
    if pdo is None:
        print('[HarvHub Notification Email] Missing PDO.')
        return False

    mailer_email, api_key = _fetch_mailer_credentials(pdo)
    if not mailer_email:
        print('[HarvHub Notification Email] server_account.mailer_email empty.')
        return False
    if '@' not in mailer_email:
        print(f'[HarvHub Notification Email] Invalid sender: {mailer_email}')
        return False
    if not api_key:
        print('[HarvHub Notification Email] server_account.mailer_password empty.')
        return False

    safe_title = (title or '').strip() or 'Notification'
    safe_message = (message or '').strip()
    notification_id = int(meta.get('notification_id') or 0)
    recipient_name = (meta.get('recipient_name') or '').strip()

    if not recipient_name:
        try:
            res = pdo.query(
                "SELECT fullname, first_name FROM harvhub "
                "WHERE LOWER(email) = %s ORDER BY id ASC LIMIT 1",
                [recipient],
            )
            rows = (res or {}).get('results') or []
            if rows:
                recipient_name = (
                    str(_row_get(rows[0], 'first_name') or '').strip()
                    or str(_row_get(rows[0], 'fullname') or '').strip()
                )
        except Exception as e:
            print(f'[HarvHub Notification Email] name lookup failed: {e}')

    payload = {
        'sender': {
            'name': 'HarvHub',
            'email': mailer_email,
        },
        'to': [{'email': recipient, **({'name': recipient_name} if recipient_name else {})}],
        'subject': safe_title,
        'htmlContent': _build_html(safe_title, safe_message),
        'textContent': safe_message,
    }

    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')

    req = urllib.request.Request(
        _BREVO_URL,
        data=body,
        method='POST',
        headers={
            'accept': 'application/json',
            'api-key': api_key,
            'content-type': 'application/json',
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            status = resp.getcode()
            resp_body = resp.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        err_body = ''
        try:
            err_body = e.read().decode('utf-8', errors='replace')
        except Exception:
            pass
        print(
            '[HarvHub Notification Email] BREVO FAILURE'
            f' | notification_id={notification_id}'
            f' | recipient={recipient}'
            f' | http_code={e.code}'
            f' | response={err_body}'
        )
        return False
    except Exception as e:
        print(
            '[HarvHub Notification Email] CURL FAILURE'
            f' | notification_id={notification_id}'
            f' | recipient={recipient}'
            f' | error={e}'
        )
        return False

    if not (200 <= status < 300):
        print(
            '[HarvHub Notification Email] BREVO FAILURE'
            f' | notification_id={notification_id}'
            f' | recipient={recipient}'
            f' | http_code={status}'
            f' | response={resp_body}'
        )
        return False

    print(
        '[HarvHub Notification Email] BREVO SUCCESS'
        f' | notification_id={notification_id}'
        f' | recipient={recipient}'
        f' | http_code={status}'
    )
    return True