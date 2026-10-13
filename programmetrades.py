# programmetrades.py
"""
Programme-scoped trade pipeline orchestrator.

Currently ships ONLY the restricted-timerange stage + recent-highest-balance
target stage. Future functions (candle fetch, crosser analysis, liquidator,
ranging, order placement, risk audit, etc.) will be dropped into
process_single_investor_from_db() in the priority order shown by the commented
section.

ARCHITECTURE
------------
* Same bridge pattern as brokerdetails.py: this file is a TCP CLIENT of
  the long-running mysqlremote.py bridge. It does NOT launch Chrome.
* The DATABASE is the source of truth. No local folder scanning, no JSON
  reads, no JSON writes. EVER.
* Every worker process (one per investor) acquires its OWN dedicated
  channel from the bridge. Channels are isolated.
* Helpers (db_query, _BridgeClient, channel mgmt, time helpers) live at
  MODULE scope so all future functions in this file can share one channel
  per worker.

RESTRICTED TIMERANGE SEMANTICS
------------------------------
Restriction is PROGRAMME-SCOPED, not investor-scoped.

Two stages, evaluated in order:

  STAGE 1 — Restricted Dates
    Query `accountmanagement_restricted_dates` for the programme.
    Convert "now" to the programme's timezone, format as YYYY-MM-DD.
    If that exact date appears in the list -> FULL-DAY LOCKOUT.
    No further checks are performed for that programme.

  STAGE 2 — Restricted Days
    Only reached when Stage 1 finds nothing for today.
    Query `accountmanagement_restricted_days` for the programme and
    evaluate the window for today's weekday using the strict rule
    below.

WINDOW RULE (strict, Stage 2 only)
----------------------------------
`from_time` and `to_time` define an inclusive span. `now` is RESTRICTED
if it lies between `from_time` and `to_time` inclusive. Anything outside
that span is FREE.

  * 12:00 AM -> 12:00 PM  restricts 12:00 AM..11:59 AM. Noon onward = free.
  * 12:00 AM -> 12:00 AM  restricts the WHOLE day.
  * 12:00 AM -> 2:00 AM   restricts 12:00 AM..2:00 AM. 2:01 AM onward = free.
  * Cross-midnight windows (e.g. 10:00 PM -> 2:00 AM) are handled.

A "NULL" timezone (or empty) is NOT an error — it means the programme has
not configured a timezone, and the restriction check is skipped for that
programme.

ACTIVE INVESTOR DETECTION
-------------------------
An investor is considered active for a programme when a row exists in
`programme_revenue_deals` joined to `harvhub` on
(investor_id, sub_account_id) with `harvhub.account_contract_status =
'contract_active'`. This mirrors the signals dashboard exactly. No
accepted_at / contract_duration date math is performed here.

PIPELINE GATES (mirrors process_single_investor_from_db_local semantics)
----------------------------------------------------------------
Two short-circuits run in order inside process_single_investor_from_db():

  GATE 1 — Restricted timerange
    If the investor's programme is currently restricted (restricted
    date / full restricted day / inside restricted time window), skip
    EVERY other stage, including recent_highest_balance_target_db.

  GATE 2 — Daily-target alarm
    recent_highest_balance_target_db() populates the module-global
    `recent_highest_alert`. If `is_triggered` is True after that stage
    runs (target met, or pre-pending alarm fired), skip every future
    trading stage. No trading decisions are made by this file yet — the
    gate is here so that when future stages are wired in, they never
    run while an alarm is active.
"""

import os
import sys
import time
import json
import socket
import struct
import threading
import traceback
import multiprocessing as mp
from datetime import datetime, timedelta

try:
    import pytz
    from zoneinfo import ZoneInfo
except Exception:
    pytz = None
    ZoneInfo = None

# ---------------------------------------------------------------------------
# MT5 import guard — everything MT5-related must go through mt5_available().
# ---------------------------------------------------------------------------
try:
    import MetaTrader5 as mt5
except Exception:
    mt5 = None


# ==============================================================================
#  REBRANDED MT5 PATHS — must match brokerdetails.py exactly
# ==============================================================================
DEFAULT_MT5_PATH     = r"C:\xampp\htdocs\harvcore\mt5\MetaTrader 5"
MT5_DESTINATION_PATH = r"C:\xampp\htdocs\harvcore\mt5"


# ==============================================================================
#  BRIDGE CLIENT — same protocol as brokerdetails.py, one channel per worker
# ==============================================================================
BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 5599

BRIDGE_OWNER = "programmetrades"

_HEADER = struct.Struct(">I")
MAX_FRAME = 64 * 1024 * 1024

_MT5_IPC_LOCK = threading.RLock()


class _BridgeError(Exception):
    pass


class _BridgeClient:
    def __init__(self, host=BRIDGE_HOST, port=BRIDGE_PORT, owner=BRIDGE_OWNER):
        self.host = host
        self.port = port
        self.owner = owner
        self.channel_id = None
        self._channel_lock = threading.Lock()

    @staticmethod
    def _recv_exact(sock, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)

    def _send_request(self, req):
        try:
            sock = socket.create_connection((self.host, self.port), timeout=15)
        except Exception as e:
            raise _BridgeError(
                f"cannot connect to bridge {self.host}:{self.port}: {e}"
            )

        try:
            payload = json.dumps(req, ensure_ascii=False).encode('utf-8')
            sock.sendall(_HEADER.pack(len(payload)) + payload)

            header = self._recv_exact(sock, _HEADER.size)
            if header is None:
                raise _BridgeError("bridge closed the connection (no header)")
            (length,) = _HEADER.unpack(header)
            if length == 0 or length > MAX_FRAME:
                raise _BridgeError(f"bad frame length from bridge: {length}")

            body = self._recv_exact(sock, length)
            if body is None:
                raise _BridgeError("bridge closed the connection (no body)")

            return json.loads(body.decode('utf-8'))
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def acquire_channel(self):
        with self._channel_lock:
            if self.channel_id is not None:
                return self.channel_id
            resp = self._send_request({
                'op': 'acquire_channel',
                'owner': self.owner,
            })
            if resp.get('status') != 'success':
                raise _BridgeError(
                    f"acquire_channel failed: {resp.get('message')}"
                )
            self.channel_id = int(resp['channel_id'])
            print(f"[bridge] {self.owner}: acquired channel "
                  f"queryrequest_{self.channel_id} / "
                  f"queryresult_{self.channel_id} "
                  f"(window #{resp.get('window_id')})")
            return self.channel_id

    def release_channel(self):
        with self._channel_lock:
            if self.channel_id is None:
                return
            cid = self.channel_id
            self.channel_id = None
            try:
                self._send_request({'op': 'release_channel',
                                    'channel_id': cid})
                print(f"[bridge] {self.owner}: released channel {cid}")
            except Exception as e:
                print(f"[bridge] release_channel({cid}) failed: {e}")

    def put(self, request, timeout=None):
        req = dict(request)
        if 'sql' in req and 'channel_id' not in req:
            req['channel_id'] = self.acquire_channel()
        return self._send_request(req)


# ==============================================================================
#  MODULE-SCOPE HELPERS (shared by all future functions)
# ==============================================================================
_db = None
recent_highest_alert = None
martingale_alert = None   # populated by martingale_system_db()


def _worker_init():
    """Each worker process gets its own bridge client -> its own channel."""
    global _db
    _db = _BridgeClient()


def db_query(sql, params=None, timeout=20.0, quiet=False):
    global _db
    if _db is None:
        _db = _BridgeClient()

    start = time.perf_counter()
    try:
        result = _db.put(
            {'sql': sql, 'params': params, 'timeout': timeout},
        )
    except _BridgeError as e:
        return {
            'status': 'error',
            'message': f'bridge error: {e}',
            'results': [], 'affected_rows': 0,
            'query_id': None, 'raw_sql': sql,
            'elapsed': time.perf_counter() - start,
        }

    if not quiet and result.get('status') != 'success':
        print(f"      [SQL FAIL] {result.get('message')}")
        print(f"      [SQL WAS ] {sql.strip()[:200]}")
        print(f"      [PARAMS  ] {params}")

    return result


# ---------------------------------------------------------------------------
# Programme-scoped notification PDO adapter (single instance per worker)
# ---------------------------------------------------------------------------
try:
    import notification_service as _notif_service
    _NOTIF_PDO = _notif_service.make_pdo(db_query)
except Exception:
    _notif_service = None
    _NOTIF_PDO = None


def _is_ok(res):
    return bool(res) and res.get('status') == 'success'


def db_fetch_all(sql, params=None, timeout=20.0, quiet=True):
    """SELECT ... -> list[dict]. Empty list on failure."""
    res = db_query(sql, params, timeout=timeout, quiet=quiet)
    if not _is_ok(res):
        return []
    return [_normalize_row(r) for r in (res.get('results') or [])]


def db_fetch_one(sql, params=None, timeout=20.0, quiet=True):
    """SELECT ... LIMIT 1 -> dict or None."""
    rows = db_fetch_all(sql, params, timeout=timeout, quiet=quiet)
    return rows[0] if rows else None


def db_fetch_scalar(sql, params=None, timeout=20.0, quiet=True, default=None):
    """SELECT one-col one-row -> value or default."""
    row = db_fetch_one(sql, params, timeout=timeout, quiet=quiet)
    if not row:
        return default
    for v in row.values():
        return v
    return default


def db_execute(sql, params=None, timeout=20.0, quiet=True):
    """INSERT/UPDATE/DELETE -> (ok: bool, affected: int, message: str)."""
    res = db_query(sql, params, timeout=timeout, quiet=quiet)
    if not _is_ok(res):
        return False, 0, res.get('message', 'error')
    return True, int(res.get('affected_rows') or 0), res.get('message', '')


def _pick_first_key(row, *candidate_keys):
    if not isinstance(row, dict):
        return None
    lowered = {(k.strip().lower() if isinstance(k, str) else k): v
               for k, v in row.items()}
    for key in candidate_keys:
        if key is None:
            continue
        lk = key.strip().lower()
        if lk in lowered and lowered[lk] not in (None, '', 'NULL'):
            return lowered[lk]
    return None


def _raw_first_key(row, *candidate_keys):
    if not isinstance(row, dict):
        return None
    lowered = {(k.strip().lower() if isinstance(k, str) else k): v
               for k, v in row.items()}
    for key in candidate_keys:
        if key is None:
            continue
        lk = key.strip().lower()
        if lk in lowered:
            return lowered[lk]
    return None


def _coerce_int(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        s = str(value).strip()
        if not s or s.lower() in ('null', 'none', 'nan'):
            return None
        if '.' in s:
            return int(float(s))
        return int(s)
    except (ValueError, TypeError):
        return None


def _coerce_float(value, default=None):
    if value is None:
        return default
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    try:
        s = str(value).strip()
        if not s or s.lower() in ('null', 'none', 'nan'):
            return default
        return float(s)
    except (ValueError, TypeError):
        return default


def _normalize_row(row):
    if row is None:
        return None
    if isinstance(row, dict):
        return {
            (k.strip().lower() if isinstance(k, str) else k): v
            for k, v in row.items()
        }
    return None


def _is_nullish(value):
    """True if the value is effectively unset (None, '', 'NULL', 'null')."""
    if value is None:
        return True
    s = str(value).strip().lower()
    return s in ('', 'null', 'none', 'nan')


def to_bool(value, default=False):
    """Parse booleans from strings/numbers/bools."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "enabled")
    return default


def to_float(value, default=None):
    """Safe float parser (handles numbers, strings, one-element lists)."""
    if value is None:
        return default
    if isinstance(value, (list, tuple, set)):
        for item in value:
            result = to_float(item, default=None)
            if result is not None:
                return result
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        v = value.strip()
        if v == "":
            return default
        v = v.replace('%', '').strip()
        try:
            return float(v)
        except ValueError:
            return default
    return default


def parse_pct(value, default=0.0):
    f = to_float(value, default=None)
    if f is None:
        return default
    return float(f)


def format_money(v, decimals=2):
    try:
        return f"${float(v):,.{decimals}f}"
    except (TypeError, ValueError):
        return "$0.00"


def format_datetime(dt):
    if not dt:
        return "—"
    try:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(dt)


def extract_volume_from_signal(order_data):
    """Return the first `*_volume` field as float, or plain `volume`."""
    if not isinstance(order_data, dict):
        return None
    for key, value in order_data.items():
        if key.endswith('_volume'):
            try:
                return float(value)
            except (ValueError, TypeError):
                continue
    if 'volume' in order_data:
        try:
            return float(order_data['volume'])
        except (ValueError, TypeError):
            return None
    return None


def get_volume_field_from_order(order):
    """Return (key, value) for the first `_volume` field, else `volume`."""
    if not isinstance(order, dict):
        return None, None
    for key, value in order.items():
        if '_volume' in key.lower() and isinstance(value, (int, float)):
            return key, value
    if 'volume' in order and isinstance(order['volume'], (int, float)):
        return 'volume', order['volume']
    return None, None


def extract_rr_from_comment(comment):
    """Parse 'R<number>' from a trade comment. Returns float or 0."""
    import re as _re
    if not comment or not isinstance(comment, str):
        return 0
    m = _re.search(r'R([0-9]+(?:\.[0-9]+)?)', comment)
    if m:
        try:
            return float(m.group(1))
        except (ValueError, TypeError):
            return 0
    return 0


# ---------- time / timezone helpers ----------
def parse_time_string(time_str):
    """Parse '9:00 am', '17:30', '9:00:00', '09:00' -> (hour, minute)."""
    if not time_str:
        return None, None

    s = str(time_str).strip().lower()
    is_pm = 'pm' in s
    is_am = 'am' in s
    clean = s.replace('pm', '').replace('am', '').replace(' ', '').strip()

    try:
        if ':' in clean:
            parts = clean.split(':')
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
        else:
            hour = int(clean)
            minute = 0
    except (ValueError, TypeError):
        return None, None

    if is_pm and hour != 12:
        hour += 12
    elif is_am and hour == 12:
        hour = 0

    return hour, minute


def to_12hr(hour, minute):
    period = "AM" if hour < 12 else "PM"
    h12 = hour % 12
    if h12 == 0:
        h12 = 12
    return f"{h12}:{minute:02d} {period}"


def get_current_time_in_timezone(timezone_str):
    """
    Convert 'now' to the given IANA timezone.
    Returns (datetime, resolved: bool). resolved=False means the timezone
    was null/unusable and local time was returned as a fallback.
    """
    if _is_nullish(timezone_str):
        return datetime.now(), False

    tz_name = str(timezone_str).strip()

    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo(tz_name)), True
        except Exception:
            pass

    if pytz is not None:
        try:
            return datetime.now(pytz.timezone(tz_name)), True
        except Exception:
            pass

    print(f"  ⚠️ Unknown timezone '{tz_name}' — falling back to local time")
    return datetime.now(), False


def is_time_in_window(now_h, now_m, sh, sm, eh, em):
    """
    True if (now_h, now_m) is INSIDE the inclusive span [sh:sm .. eh:em].
    Handles cross-midnight windows. An empty/locked window (from == to)
    means the WHOLE day is restricted.
    """
    now_min = now_h * 60 + now_m
    start_min = sh * 60 + sm
    end_min = eh * 60 + em

    # from == to -> full day restriction
    if start_min == end_min:
        return True

    # cross-midnight window (e.g. 22:00 -> 02:00)
    if end_min < start_min:
        return now_min >= start_min or now_min <= end_min

    # normal span (inclusive on both ends)
    return start_min <= now_min <= end_min


def is_full_day_window(from_h, from_m, to_h, to_m):
    """
    A day-row is a FULL-DAY restriction when its span covers the whole day.
    Canonical shapes:
      * 00:00 -> 00:00  (literal 12am to 12am)
      * 00:00 -> 23:59  (00:00 through the last minute)
    """
    f_min = from_h * 60 + from_m
    t_min = to_h * 60 + to_m
    if f_min == 0 and t_min == 0:
        return True
    if f_min == 0 and to_h == 23 and to_m == 59:
        return True
    return False


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


# ==============================================================================
#  REBRANDED TERMINAL PATH RESOLUTION — mirrors brokerdetails.py exactly
# ==============================================================================
def _sanitize_folder_component(value):
    import re as _re
    if value is None:
        return ''
    s = str(value).strip()
    s = _re.sub(r'[<>:"/\\|?*]', '_', s)
    s = s.replace(' ', '_')
    return s


def build_mt5_terminal_path_sa(server, login, user_id, sub_account_id):
    """
    Same formula as brokerdetails.build_mt5_terminal_path_sa.
    Returns (folder_name, folder_abs, terminal_exe).
    """
    s   = _sanitize_folder_component(server)
    l   = _sanitize_folder_component(login)
    u   = _sanitize_folder_component(user_id)
    aid = _sanitize_folder_component(sub_account_id)
    folder_name  = f"{s}_{l}_U{u}_SA{aid}"
    folder_abs   = os.path.join(MT5_DESTINATION_PATH, folder_name)
    terminal_exe = os.path.join(folder_abs, "terminal64.exe")
    return folder_name, folder_abs, terminal_exe


def resolve_investor_terminal_path(inv_db_id, sub_id):
    """
    Return the correct terminal64.exe path for this investor sub-account.

    Priority:
      1. harvhub.Terminal_path — IF the file exists on disk
      2. Rebuild from server+login using brokerdetails' formula
         — IF the rebuilt folder + exe exist on disk
      3. None (caller falls back to mt5.initialize() with no path)
    """
    row = db_fetch_one(
        "SELECT login, server, Terminal_path FROM harvhub "
        "WHERE id = %s AND sub_account_id = %s LIMIT 1",
        [inv_db_id, sub_id], timeout=10.0, quiet=True,
    )
    if not row:
        print(f"[MT5-PATH] no harvhub row for investor={inv_db_id} sub={sub_id}")
        return None

    db_terminal_path = _raw_first_key(row, 'Terminal_path')
    login_v  = _raw_first_key(row, 'login')
    server_v = _raw_first_key(row, 'server')

    # 1. DB value, if file exists
    if db_terminal_path and str(db_terminal_path).strip():
        p = str(db_terminal_path).strip()
        if os.path.isfile(p):
            print(f"[MT5-PATH] using harvhub.Terminal_path = {p}")
            return p
        print(f"[MT5-PATH] harvhub.Terminal_path='{p}' does NOT exist on disk — "
              f"falling back to rebuild")

    # 2. Rebuild using brokerdetails formula
    if login_v and server_v:
        _, folder_abs, terminal_exe = build_mt5_terminal_path_sa(
            server_v, login_v, inv_db_id, sub_id
        )
        if os.path.isfile(terminal_exe):
            print(f"[MT5-PATH] rebuilt from server+login = {terminal_exe}")
            # Write back to DB so next run doesn't have to rebuild
            try:
                db_execute(
                    "UPDATE harvhub SET Terminal_path = %s "
                    "WHERE id = %s AND sub_account_id = %s",
                    [terminal_exe, inv_db_id, sub_id],
                    timeout=10.0, quiet=True,
                )
                print(f"[MT5-PATH] wrote rebuilt path back to harvhub.Terminal_path")
            except Exception:
                pass
            return terminal_exe
        print(f"[MT5-PATH] rebuilt path also missing on disk: {terminal_exe}")
        return terminal_exe  # let mt5_connect fail with a clear error

    print(f"[MT5-PATH] no login/server in harvhub — cannot resolve terminal path")
    return None


# ==============================================================================
#  MT5 — thin, locked wrappers (available to every future stage)
# ==============================================================================
def mt5_available():
    return mt5 is not None


def mt5_connect(terminal_path=None, timeout_ms=10000):
    """Initialize MT5. Idempotent — safe to call multiple times."""
    with _MT5_IPC_LOCK:
        if not mt5_available():
            return False
        try:
            mt5.shutdown()
        except Exception:
            pass
        try:
            if terminal_path:
                return bool(mt5.initialize(
                    path=terminal_path, timeout=timeout_ms, portable=True,
                ))
            return bool(mt5.initialize(timeout=timeout_ms))
        except Exception as e:
            print(f"  ⚠️ mt5.initialize failed: {e}")
            return False


def mt5_disconnect():
    with _MT5_IPC_LOCK:
        if not mt5_available():
            return
        try:
            mt5.shutdown()
        except Exception:
            pass


def mt5_account_info():
    with _MT5_IPC_LOCK:
        if not mt5_available():
            return None
        try:
            return mt5.account_info()
        except Exception:
            return None


def mt5_terminal_info():
    with _MT5_IPC_LOCK:
        if not mt5_available():
            return None
        try:
            return mt5.terminal_info()
        except Exception:
            return None


def mt5_last_error():
    with _MT5_IPC_LOCK:
        if not mt5_available():
            return None
        try:
            return mt5.last_error()
        except Exception:
            return None


def mt5_balance():
    acc = mt5_account_info()
    if acc is None:
        return None
    try:
        return float(acc.balance)
    except Exception:
        return None


def mt5_symbol_info(symbol):
    with _MT5_IPC_LOCK:
        if not mt5_available():
            return None
        try:
            return mt5.symbol_info(symbol)
        except Exception:
            return None


def mt5_symbol_tick(symbol):
    with _MT5_IPC_LOCK:
        if not mt5_available():
            return None
        try:
            return mt5.symbol_info_tick(symbol)
        except Exception:
            return None


def mt5_symbol_select(symbol, enable=True):
    with _MT5_IPC_LOCK:
        if not mt5_available():
            return False
        try:
            return bool(mt5.symbol_select(symbol, enable))
        except Exception:
            return False


def mt5_symbols_get():
    with _MT5_IPC_LOCK:
        if not mt5_available():
            return []
        try:
            return mt5.symbols_get() or []
        except Exception:
            return []


def mt5_orders_get(**kwargs):
    with _MT5_IPC_LOCK:
        if not mt5_available():
            return []
        try:
            return mt5.orders_get(**kwargs) or []
        except Exception:
            return []


def mt5_positions_get(**kwargs):
    with _MT5_IPC_LOCK:
        if not mt5_available():
            return []
        try:
            return mt5.positions_get(**kwargs) or []
        except Exception:
            return []


def mt5_history_deals(start_naive, end_naive):
    with _MT5_IPC_LOCK:
        if not mt5_available():
            return []
        try:
            return mt5.history_deals_get(start_naive, end_naive) or []
        except Exception:
            return []


def mt5_history_orders(start_naive, end_naive):
    with _MT5_IPC_LOCK:
        if not mt5_available():
            return []
        try:
            return mt5.history_orders_get(start_naive, end_naive) or []
        except Exception:
            return []


def mt5_order_send(request):
    with _MT5_IPC_LOCK:
        if not mt5_available():
            return None
        try:
            return mt5.order_send(request)
        except Exception:
            return None


def mt5_order_calc_profit(order_type, symbol, volume, price_open, price_close):
    with _MT5_IPC_LOCK:
        if not mt5_available():
            return None
        try:
            return mt5.order_calc_profit(
                order_type, symbol, volume, price_open, price_close
            )
        except Exception:
            return None


def mt5_order_calc_margin(order_type, symbol, volume, price):
    with _MT5_IPC_LOCK:
        if not mt5_available():
            return None
        try:
            return mt5.order_calc_margin(order_type, symbol, volume, price)
        except Exception:
            return None


# ==============================================================================
#  DB-DRIVEN DISCOVERY: investors associated with this VPS
# ==============================================================================
def fetch_vps_programmes(local_ip):
    """
    Return list of {programme_id, userid} for every programme whose VPS is
    this machine, INCLUDING follower programmes of those owners.
    """
    out = []
    seen_pids = set()

    sql = """
        SELECT id, programme_id, user_id
        FROM programme_vps
        WHERE programme_vps_ip_address = %s
    """
    res = db_query(sql, [local_ip], timeout=15.0, quiet=True)
    if not _is_ok(res):
        print(f"   [VPS] programme_vps lookup failed: {res.get('message')}")
        return out

    owner_pids = []
    for raw in res.get('results') or []:
        row = _normalize_row(raw)
        pid = _coerce_int(_pick_first_key(row, 'programme_id'))
        uid = _coerce_int(_pick_first_key(row, 'user_id'))
        if pid is None or pid <= 0:
            continue
        owner_pids.append(pid)
        if pid not in seen_pids:
            seen_pids.add(pid)
            out.append({'programme_id': pid, 'userid': uid})

    if owner_pids:
        placeholders = ','.join(['%s'] * len(owner_pids))
        fol_sql = f"""
            SELECT owner_programme_id, follower_programme_id
            FROM programme_vps_hosts_followers
            WHERE owner_programme_id IN ({placeholders})
              AND host_status = 'active'
        """
        fol_res = db_query(fol_sql, owner_pids, timeout=15.0, quiet=True)
        if _is_ok(fol_res):
            for raw in fol_res.get('results') or []:
                row = _normalize_row(raw)
                fpid = _coerce_int(_pick_first_key(row, 'follower_programme_id'))
                if fpid is None or fpid <= 0 or fpid in seen_pids:
                    continue
                uid_res = db_query(
                    "SELECT userid FROM programme WHERE id = %s LIMIT 1",
                    [fpid], timeout=10.0, quiet=True,
                )
                fuid = None
                if _is_ok(uid_res) and uid_res.get('results'):
                    for v in uid_res['results'][0].values():
                        fuid = _coerce_int(v)
                        break
                seen_pids.add(fpid)
                out.append({'programme_id': fpid, 'userid': fuid})

    return out


def fetch_active_investors_for_programme(programme_id):
    """
    Mirror of signals_dashboard.getActiveInvestorsForProgramme.
    Returns list of {investor_id, sub_account_id}.
    """
    out = []
    seen = set()

    sql = """
        SELECT DISTINCT
            d.investor_id,
            d.investor_sub_account_id
        FROM programme_revenue_deals d
        INNER JOIN harvhub h
                ON h.id = d.investor_id
               AND h.sub_account_id = d.investor_sub_account_id
        WHERE d.programme_id = %s
          AND d.investor_id > 0
          AND h.account_contract_status = 'contract_active'
    """
    res = db_query(sql, [programme_id], timeout=15.0, quiet=True)
    if not _is_ok(res):
        print(f"   [ACTIVE] lookup failed for programme={programme_id}: "
              f"{res.get('message')}")
        return out

    for raw in res.get('results') or []:
        row = _normalize_row(raw)
        inv_db_id = _coerce_int(_pick_first_key(row, 'investor_id'))
        sub_id = _coerce_int(_pick_first_key(row, 'investor_sub_account_id'))
        if inv_db_id is None or inv_db_id <= 0 or sub_id is None or sub_id <= 0:
            continue
        key = (inv_db_id, sub_id)
        if key in seen:
            continue
        seen.add(key)
        out.append({'investor_id': inv_db_id, 'sub_account_id': sub_id})
    return out


def fetch_vps_investor_jobs(local_ip):
    jobs = []
    seen = set()

    programmes = fetch_vps_programmes(local_ip)
    if not programmes:
        return jobs

    for prog in programmes:
        programme_id = prog['programme_id']
        programme_name = fetch_programme_name(programme_id)

        investors = fetch_active_investors_for_programme(programme_id)
        for inv in investors:
            inv_db_id = inv['investor_id']
            sub_id = inv['sub_account_id']
            key = (inv_db_id, sub_id, programme_id)
            if key in seen:
                continue
            seen.add(key)
            jobs.append({
                'investor_id':    inv_db_id,
                'sub_account_id': sub_id,
                'programme_id':   programme_id,
                'programme_name': programme_name,
            })

    return jobs


# ==============================================================================
#  PROGRAMME RESTRICTION LOADERS
# ==============================================================================
def fetch_programme_timezone(programme_id):
    """
    Return the programme's timezone string, or None if NULL/empty.
    """
    tz_res = db_query(
        "SELECT timezone FROM programme WHERE id = %s LIMIT 1",
        [programme_id], timeout=10.0, quiet=True,
    )
    if _is_ok(tz_res) and tz_res.get('results'):
        row = tz_res['results'][0]
        for k, v in row.items():
            if isinstance(k, str) and k.strip().lower() == 'timezone':
                if _is_nullish(v):
                    return None
                return str(v).strip()
    return None


def fetch_programme_restricted_dates(programme_id):
    """
    Return list of dates (as YYYY-MM-DD strings) from
    accountmanagement_restricted_dates for this programme.
    """
    out = []
    res = db_query(
        "SELECT restricted_date "
        "FROM accountmanagement_restricted_dates "
        "WHERE programme_id = %s ORDER BY restricted_date ASC",
        [programme_id], timeout=15.0, quiet=True,
    )
    if not _is_ok(res):
        return out

    for raw in res.get('results') or []:
        row = _normalize_row(raw)
        val = _pick_first_key(row, 'restricted_date')
        if val is None:
            continue
        s = str(val).strip()
        if s:
            out.append(s[:10])  # normalise to YYYY-MM-DD
    return out


def fetch_programme_restricted_days(programme_id):
    """
    Return list of {day, from_time, to_time} rows from
    accountmanagement_restricted_days for this programme.
    """
    rows = []
    r_res = db_query(
        "SELECT day, from_time, to_time "
        "FROM accountmanagement_restricted_days "
        "WHERE programme_id = %s ORDER BY id ASC",
        [programme_id], timeout=15.0, quiet=True,
    )
    if _is_ok(r_res):
        for raw in r_res.get('results') or []:
            row = _normalize_row(raw)
            rows.append({
                'day':       (_pick_first_key(row, 'day') or '').strip(),
                'from_time': str(_pick_first_key(row, 'from_time') or '').strip(),
                'to_time':   str(_pick_first_key(row, 'to_time') or '').strip(),
            })
    return rows


def fetch_investor_identity(investor_id):
    res = db_query(
        "SELECT id, fullname, username, email "
        "FROM harvhub WHERE id = %s LIMIT 1",
        [investor_id], timeout=10.0, quiet=True,
    )
    if _is_ok(res) and res.get('results'):
        row = _normalize_row(res['results'][0])
        return {
            'id':       _coerce_int(_pick_first_key(row, 'id')) or investor_id,
            'fullname': (_pick_first_key(row, 'fullname') or '').strip(),
            'username': (_pick_first_key(row, 'username') or '').strip(),
            'email':    (_pick_first_key(row, 'email') or '').strip(),
        }
    return {'id': investor_id, 'fullname': '', 'username': '', 'email': ''}


def fetch_programme_name(programme_id):
    res = db_query(
        "SELECT program_name FROM programme WHERE id = %s LIMIT 1",
        [programme_id], timeout=10.0, quiet=True,
    )
    if _is_ok(res) and res.get('results'):
        for v in res['results'][0].values():
            return '' if v is None else str(v).strip()
    return ''

# ==============================================================================
#  CHECK AND RECORD UNAUTHORIZED ACTIONS — DB version
#
#  Investor-scoped, MT5-facing, magic-number-driven.
#
#  A trade (pending order, open position, or closed deal) is AUTHORIZED for
#  an investor iff its `magic` is present in that investor's
#  programme_trades.magic set. Otherwise it is UNAUTHORIZED.
#
#  On every run:
#    * classify MT5 orders / positions / history deals as authorized or not
#    * compute an expected current balance from an anchor + authorized P&L
#    * detect an unaccounted deficit (MT5 < expected) → "unaccounted deficit"
#    * write one row into `balance_log` for the current Lagos day
#    * if any unauthorized action or deficit was detected, notify the
#      investor's sub-account AND the programme owner (dedup per day, per
#      kind) via the notification service
#
#  Nothing here touches JSON files.
# ==============================================================================
def check_and_record_unauthorized_actions_db(inv_db_id=None):
    """
    Reads:
        * programme_trades        -> this investor's authorized magic set
        * harvhub                 -> anchor (broker_balance, execution_start_date)
                                     + current_balance semantics
        * balance_log             -> last known closing balance for continuity
        * MT5                     -> live orders / positions / history deals

    Writes:
        * balance_log             -> one row per investor per Lagos day
        * programme_notifications -> investor-side + programme-side alerts
                                     via notification_service (dedup keyed)

    Populates the module-global `unauthorized_alert` with:
        {
          'is_triggered': bool,
          'investor_id': int,
          'sub_account_id': int,
          'programme_id': int,
          'investor_authorized_magics': set,
          'unauthorized_trades': [...],
          'unauthorized_orders': [...],
          'unauthorized_positions': [...],
          'unauthorized_pnl_total': float,
          'unaccounted_deficit': float,
          'unauthorized_types': [...],
          'application_status': str,
          'errors': [...],
        }
    """

    global unauthorized_alert
    from datetime import datetime, timedelta, timezone

    # ------------------------------------------------------------------
    # LAGOS TIMEZONE
    # ------------------------------------------------------------------
    try:
        from zoneinfo import ZoneInfo
        LAGOS_TZ = ZoneInfo("Africa/Lagos")
        _LAGOS_TZ_SOURCE = "zoneinfo"
    except Exception:
        LAGOS_TZ = timezone(timedelta(hours=1))
        _LAGOS_TZ_SOURCE = "fixed_utc+1"

    def lagos_now():
        return datetime.now(LAGOS_TZ)

    def lagos_now_str():
        return lagos_now().strftime("%Y-%m-%d %H:%M:%S")

    def lagos_today_str():
        return lagos_now().strftime("%Y-%m-%d")

    def lagos_from_timestamp(ts):
        if not ts:
            return None
        try:
            ts_float = float(ts)
        except (TypeError, ValueError):
            return None
        if ts_float > 1e11:
            ts_float = ts_float / 1000.0
        try:
            return datetime.fromtimestamp(ts_float, tz=timezone.utc).astimezone(LAGOS_TZ)
        except Exception:
            return None

    unauthorized_alert = {
        'is_triggered': False,
        'investor_id': inv_db_id if inv_db_id else 'all',
        'sub_account_id': None,
        'programme_id': None,
        'investor_authorized_magics': set(),
        'unauthorized_trades': [],
        'unauthorized_orders': [],
        'unauthorized_positions': [],
        'unauthorized_pnl_total': 0.0,
        'unaccounted_deficit': 0.0,
        'unauthorized_types': [],
        'application_status': 'approved',
        'errors': [],
        'timestamp': lagos_now_str(),
    }

    print(f"\n{'='*10} 🔍 AUTHORIZED-ACTIONS AUDIT (DB) {'='*10}")
    print(f" 🕒 Lagos time now: {lagos_now().strftime('%Y-%m-%d %H:%M:%S %Z')} (source: {_LAGOS_TZ_SOURCE})")

    stats = {
        'investor_id': inv_db_id if inv_db_id else 'all',
        'investors_processed': 0,
        'investors_with_unauthorized': 0,
        'unauthorized_orders_found': 0,
        'unauthorized_positions_found': 0,
        'unauthorized_trades_found': 0,
        'unaccounted_deficits_found': 0,
        'balance_log_rows_written': 0,
        'notifications_queued': 0,
        'errors': [],
        'processing_success': False,
        'details': [],
    }

    # ==================================================================
    # SECTION 1 — PROGRAMME-SCOPED READERS
    # ==================================================================
    def programme_fetch_owner_email(programme_id):
        """
        Resolve the programme owner's email via programme.userid -> harvhub.email.
        Returns (owner_email, programme_name) — both may be empty.
        """
        row = db_fetch_one(
            """
            SELECT p.program_name AS programme_name,
                   h.email        AS owner_email
              FROM programme p
              LEFT JOIN harvhub h ON h.id = p.userid AND h.is_main_account = 1
             WHERE p.id = %s
             LIMIT 1
            """,
            [programme_id], timeout=10.0, quiet=True,
        )
        if not row:
            return '', ''
        owner_email = (_pick_first_key(row, 'owner_email') or '').strip().lower()
        programme_name = (_pick_first_key(row, 'programme_name') or '').strip()
        return owner_email, programme_name

    # ==================================================================
    # SECTION 2 — INVESTOR-SCOPED READERS
    # ==================================================================
    def investor_fetch_identity(investor_id, sub_account_id):
        row = db_fetch_one(
            """
            SELECT id, sub_account_id, main_account_id,
                   fullname, username, email
              FROM harvhub
             WHERE id = %s AND sub_account_id = %s
             LIMIT 1
            """,
            [investor_id, sub_account_id], timeout=10.0, quiet=True,
        )
        return row or {}

    def investor_fetch_anchor(investor_id, sub_account_id):
        """broker_balance = execution-start balance; also gives execution_start_date."""
        return db_fetch_one(
            """
            SELECT id, sub_account_id, broker_balance, execution_start_date
              FROM harvhub
             WHERE id = %s AND sub_account_id = %s
             LIMIT 1
            """,
            [investor_id, sub_account_id], timeout=10.0, quiet=True,
        ) or {}

    def investor_fetch_authorized_magics(investor_id, sub_account_id, programme_id):
        """
        Every pending programme_trades.magic for THIS investor under THIS
        programme is an authorized magic. Anything MT5 shows with a
        different magic is unauthorized.
        """
        rows = db_fetch_all(
            """
            SELECT magic
              FROM programme_trades
             WHERE userid = %s
               AND programmeid = %s
               AND investor_id = %s
               AND investor_sub_account_id = %s
               AND orderstatus = 'pending'
               AND magic IS NOT NULL
            """,
            [investor_id, programme_id, investor_id, sub_account_id],
            timeout=10.0, quiet=True,
        )
        out = set()
        for r in rows:
            m = _coerce_int(_raw_first_key(r, 'magic'))
            if m is not None and m > 0:
                out.add(m)
        return out

    def balance_log_fetch_last_closing(investor_id, sub_account_id):
        """Look up the last recorded closing balance for continuity."""
        row = db_fetch_one(
            """
            SELECT date, day_closing_balance
              FROM balance_log
             WHERE userid = %s AND sub_account_id = %s
             ORDER BY id DESC
             LIMIT 1
            """,
            [investor_id, sub_account_id], timeout=10.0, quiet=True,
        )
        if not row:
            return None, None
        return (_raw_first_key(row, 'date'),
                _coerce_float(_raw_first_key(row, 'day_closing_balance'), default=None))

    def balance_log_upsert(investor_id, sub_account_id, date_str,
                           day_start_balance, auth_pnl, unauth_pnl,
                           unauth_withdrawals, closing_balance,
                           unusual, auth_count, unauth_count):
        existing = db_fetch_one(
            """
            SELECT id FROM balance_log
             WHERE userid = %s AND sub_account_id = %s AND date = %s
             LIMIT 1
            """,
            [investor_id, sub_account_id, date_str], timeout=10.0, quiet=True,
        )
        if existing and _raw_first_key(existing, 'id'):
            row_id = _coerce_int(_raw_first_key(existing, 'id'))
            ok, _, _ = db_execute(
                """
                UPDATE balance_log
                   SET day_starting_balance         = %s,
                       day_authorized_trades_pnl    = %s,
                       day_unauthorized_trades_pnl  = %s,
                       day_unauthorized_withdrawals = %s,
                       day_closing_balance          = %s,
                       unusual_activity             = %s,
                       authorized_trades_count      = %s,
                       unauthorized_trades_count    = %s
                 WHERE id = %s
                """,
                [round(day_start_balance, 8), round(auth_pnl, 8),
                 round(unauth_pnl, 8), round(unauth_withdrawals, 8),
                 round(closing_balance, 8), 1 if unusual else 0,
                 int(auth_count), int(unauth_count), row_id],
                timeout=15.0, quiet=True,
            )
            return ok, 'updated'
        else:
            ok, _, _ = db_execute(
                """
                INSERT INTO balance_log
                    (userid, sub_account_id, date,
                     day_starting_balance, day_authorized_trades_pnl,
                     day_unauthorized_trades_pnl, day_unauthorized_withdrawals,
                     day_closing_balance, unusual_activity,
                     authorized_trades_count, unauthorized_trades_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [investor_id, sub_account_id, date_str,
                 round(day_start_balance, 8), round(auth_pnl, 8),
                 round(unauth_pnl, 8), round(unauth_withdrawals, 8),
                 round(closing_balance, 8), 1 if unusual else 0,
                 int(auth_count), int(unauth_count)],
                timeout=15.0, quiet=True,
            )
            return ok, 'inserted'

    # ==================================================================
    # SECTION 3 — MT5 READS (investor-scoped)
    # ==================================================================
    def mt5_history_deals_for_investor(execution_start_dt):
        if execution_start_dt is None:
            execution_start_dt = lagos_now() - timedelta(days=30)
        try:
            deals = mt5_history_deals(execution_start_dt, lagos_now())
        except Exception:
            deals = []
        return deals or []

    def mt5_open_positions():
        try:
            return mt5_positions_get() or []
        except Exception:
            return []

    def mt5_pending_orders():
        try:
            return mt5_orders_get() or []
        except Exception:
            return []

    # ==================================================================
    # SECTION 4 — NOTIFICATION HOOKS
    # ==================================================================
    def notify_investor_and_owner(investor_id, sub_account_id, programme_id,
                                  investor_email, owner_email,
                                  programme_name,
                                  unauth_trades, unauth_orders,
                                  unauth_positions, unauth_pnl,
                                  unaccounted_deficit):
        """
        Fire investor-side + programme-side notifications about the
        violations found. Uses record_programme_notification for BOTH
        (the service exposes programme-scoped rows keyed by programme_id).

        For investor-side we also use record_programme_notification with
        the investor's own email — the row is scoped by
        (programme_id, email), so the investor receives their own copy
        while the owner receives theirs, without collision.
        """
        try:
            from notification_service import (
                record_programme_notification_once,
            )
        except Exception as e:
            print(f"      [NOTIF] notification_service unavailable: {e}")
            return 0

        today = lagos_today_str()
        sent = 0

        # ---- Build the human-readable summary once ----
        parts = []
        if unauth_trades:
            parts.append(f"{len(unauth_trades)} unauthorized closed trade(s)")
        if unauth_orders:
            parts.append(f"{len(unauth_orders)} unauthorized pending order(s)")
        if unauth_positions:
            parts.append(f"{len(unauth_positions)} unauthorized open position(s)")
        if unaccounted_deficit > 0.01:
            parts.append(
                f"an unaccounted balance deficit of ${unaccounted_deficit:.2f}"
            )
        if not parts:
            return 0
        summary = ", ".join(parts)

        # ---- How severe? ----
        # Any unauthorized trade / position / deficit → danger
        # Only unauthorized pending orders → warning
        if unauth_trades or unauth_positions or unaccounted_deficit > 0.01:
            ntype = 'danger'
            title_core = 'Unauthorized Actions Detected'
        else:
            ntype = 'warning'
            title_core = 'Unauthorized Pending Orders Detected'

        # ---- Investor-side message ----
        investor_msg = (
            f"We detected unauthorized actions on your programme "
            f"'{programme_name}': {summary}. This means trades were "
            f"placed outside the magic numbers issued by the programme. "
            f"Please stop manual or third-party trading on this sub-account "
            f"immediately to avoid contract violations."
        )
        try:
            nid = record_programme_notification_once(
                _NOTIF_PDO,
                int(programme_id),
                investor_email,
                {
                    'notification_key': f'prog-unauth-investor-{programme_id}-{sub_account_id}-{today}',
                    'title': title_core,
                    'message': investor_msg,
                    'type': ntype,
                    'section': 'Unauthorized',
                    'action_tab': 'activity',
                    'force': False,
                    'send_email': True,
                },
            )
            if nid:
                sent += 1
                print(f"      [NOTIF] investor {investor_email} notified (id={nid})")
            else:
                print(f"      [NOTIF] investor {investor_email} — already notified today (dedup)")
        except Exception as e:
            print(f"      [NOTIF] investor notify failed: {e}")

        # ---- Programme-owner message ----
        if owner_email and '@' in owner_email:
            owner_msg = (
                f"Investor {investor_id} (sub-account {sub_account_id}) on "
                f"programme '{programme_name}' has violated the contract "
                f"agreement: {summary}. The investor's trading activity is "
                f"outside the magic numbers your programme issued. Please "
                f"review and take action."
            )
            try:
                nid = record_programme_notification_once(
                    _NOTIF_PDO,
                    int(programme_id),
                    owner_email,
                    {
                        'notification_key': f'prog-unauth-owner-{programme_id}-{sub_account_id}-{today}',
                        'title': f'Contract Violation — Investor {investor_id}',
                        'message': owner_msg,
                        'type': 'danger',
                        'section': 'Unauthorized',
                        'action_tab': 'programme_investors',
                        'force': False,
                        'send_email': True,
                    },
                )
                if nid:
                    sent += 1
                    print(f"      [NOTIF] owner {owner_email} notified (id={nid})")
                else:
                    print(f"      [NOTIF] owner {owner_email} — already notified today (dedup)")
            except Exception as e:
                print(f"      [NOTIF] owner notify failed: {e}")

        return sent

    # ==================================================================
    # SECTION 5 — PER-INVESTOR PIPELINE
    # ==================================================================
    def process_investor(investor_id, sub_account_id, programme_id, programme_name):
        detail = {
            'investor_id': investor_id,
            'sub_account_id': sub_account_id,
            'programme_id': programme_id,
            'investor_email': None,
            'owner_email': None,
            'authorized_magic_count': 0,
            'unauthorized_orders': 0,
            'unauthorized_positions': 0,
            'unauthorized_trades': 0,
            'unauthorized_pnl_total': 0.0,
            'unaccounted_deficit': 0.0,
            'unauthorized_types': [],
            'balance_log_action': None,
            'notifications_sent': 0,
            'application_status': 'approved',
            'error': None,
        }

        # -------- identity + anchor + programme owner --------
        identity = investor_fetch_identity(investor_id, sub_account_id)
        investor_email = (_pick_first_key(identity, 'email') or '').strip().lower()
        fullname = _pick_first_key(identity, 'fullname') or f"user{investor_id}"
        detail['investor_email'] = investor_email

        owner_email, prog_name = programme_fetch_owner_email(programme_id)
        if not programme_name:
            programme_name = prog_name
        detail['owner_email'] = owner_email

        print(f"\n{'─'*72}")
        print(f" 🔍 Investor {investor_id} (sub {sub_account_id}) | "
              f"programme '{programme_name}' (id={programme_id})")
        print(f"{'─'*72}")
        print(f"  │ Investor email      : {investor_email or '—'}")
        print(f"  │ Programme owner     : {owner_email or '—'}")

        # -------- authorized magic set --------
        authorized_magics = investor_fetch_authorized_magics(
            investor_id, sub_account_id, programme_id)
        detail['authorized_magic_count'] = len(authorized_magics)
        if authorized_magics:
            sample = sorted(authorized_magics)[:8]
            print(f"  │ Authorized magics   : {len(authorized_magics)} "
                  f"(sample: {sample}{'…' if len(authorized_magics) > 8 else ''})")
        else:
            print(f"  │ Authorized magics   : NONE — every MT5 action will be flagged")

        # -------- anchor: broker_balance = execution-start balance --------
        anchor = investor_fetch_anchor(investor_id, sub_account_id)
        broker_balance = _coerce_float(_raw_first_key(anchor, 'broker_balance'), default=None)
        execution_start_date = _raw_first_key(anchor, 'execution_start_date')

        mt5_balance_now = None
        try:
            acc = mt5_account_info()
            if acc is not None:
                mt5_balance_now = float(acc.balance)
        except Exception:
            mt5_balance_now = None

        if broker_balance is None:
            # no anchor at all — we can still audit but cannot compute a deficit
            broker_balance = mt5_balance_now
            print(f"  │ ⚠️ harvhub.broker_balance NULL — using MT5 balance "
                  f"as anchor (${(mt5_balance_now or 0):.2f})")

        # -------- MT5: pending orders / open positions --------
        pending_orders = mt5_pending_orders()
        open_positions = mt5_open_positions()

        unauth_orders = []
        for order in pending_orders:
            try:
                om = int(getattr(order, 'magic', 0) or 0)
            except Exception:
                om = 0
            if om not in authorized_magics:
                unauth_orders.append({
                    'ticket': getattr(order, 'ticket', None),
                    'symbol': getattr(order, 'symbol', None),
                    'volume': float(getattr(order, 'volume_current', 0) or 0),
                    'price': float(getattr(order, 'price_open', 0) or 0),
                    'magic': om,
                })

        unauth_positions = []
        for pos in open_positions:
            try:
                pm = int(getattr(pos, 'magic', 0) or 0)
            except Exception:
                pm = 0
            if pm not in authorized_magics:
                unauth_positions.append({
                    'ticket': getattr(pos, 'ticket', None),
                    'symbol': getattr(pos, 'symbol', None),
                    'volume': float(getattr(pos, 'volume', 0) or 0),
                    'price': float(getattr(pos, 'price_open', 0) or 0),
                    'profit': float(getattr(pos, 'profit', 0) or 0),
                    'magic': pm,
                })

        # -------- MT5: closed deals since execution start --------
        start_dt = None
        if execution_start_date:
            for fmt in ("%Y-%m-%d", "%B %d, %Y", "%Y/%m/%d",
                        "%Y-%m-%d %H:%M:%S"):
                try:
                    start_dt = datetime.strptime(str(execution_start_date), fmt)
                    break
                except Exception:
                    continue
        if start_dt is None:
            start_dt = lagos_now() - timedelta(days=30)
        # Make naive for MT5
        start_dt_naive = start_dt.replace(tzinfo=None)

        deals = mt5_history_deals_for_investor(start_dt_naive)

        authorized_deals = []
        unauthorized_deals = []
        total_auth_pnl = 0.0
        total_unauth_pnl = 0.0
        auth_count = 0
        unauth_count = 0

        for deal in deals:
            try:
                dm = int(getattr(deal, 'magic', 0) or 0)
            except Exception:
                dm = 0
            pnl = float(getattr(deal, 'profit', 0) or 0) \
                + float(getattr(deal, 'commission', 0) or 0) \
                + float(getattr(deal, 'swap', 0) or 0)
            deal_ts = getattr(deal, 'time', None) or getattr(deal, 'time_msc', None)
            deal_lagos = lagos_from_timestamp(deal_ts)
            rec = {
                'ticket': getattr(deal, 'ticket', None),
                'symbol': getattr(deal, 'symbol', None),
                'volume': float(getattr(deal, 'volume', 0) or 0),
                'pnl': pnl,
                'magic': dm,
                'time': deal_lagos.strftime('%Y-%m-%d %H:%M:%S') if deal_lagos else None,
            }
            if dm in authorized_magics:
                authorized_deals.append(rec)
                total_auth_pnl += pnl
                auth_count += 1
            else:
                unauthorized_deals.append(rec)
                total_unauth_pnl += pnl
                unauth_count += 1

        # -------- expected balance + unaccounted deficit --------
        expected_balance = None
        if broker_balance is not None:
            expected_balance = float(broker_balance) + total_auth_pnl + total_unauth_pnl

        unaccounted_deficit = 0.0
        if expected_balance is not None and mt5_balance_now is not None:
            if mt5_balance_now + 0.01 < expected_balance:
                unaccounted_deficit = round(expected_balance - mt5_balance_now, 2)

        # -------- classify status --------
        has_trades = bool(unauthorized_deals)
        has_orders = bool(unauth_orders)
        has_positions = bool(unauth_positions)
        has_deficit = unaccounted_deficit > 0.01
        any_unauthorized = has_trades or has_orders or has_positions or has_deficit

        unauth_types = []
        if has_trades:
            unauth_types.append('unauthorized_trades')
        if has_orders:
            unauth_types.append('unauthorized_orders')
        if has_positions:
            unauth_types.append('unauthorized_positions')
        if has_deficit:
            unauth_types.append('unaccounted_balance_deficit')

        if any_unauthorized:
            application_status = 'approved_with_issues' if not has_deficit else 'approved_with_issues'
        else:
            application_status = 'approved'

        detail['unauthorized_orders'] = len(unauth_orders)
        detail['unauthorized_positions'] = len(unauth_positions)
        detail['unauthorized_trades'] = len(unauthorized_deals)
        detail['unauthorized_pnl_total'] = round(total_unauth_pnl, 2)
        detail['unaccounted_deficit'] = unaccounted_deficit
        detail['unauthorized_types'] = unauth_types
        detail['application_status'] = application_status

        # -------- summary print --------
        print(f"  │ Authorized closed   : {auth_count} (P&L ${total_auth_pnl:+.2f})")
        print(f"  │ Unauthorized closed : {len(unauthorized_deals)} "
              f"(P&L ${total_unauth_pnl:+.2f})")
        print(f"  │ Unauthorized orders : {len(unauth_orders)}")
        print(f"  │ Unauthorized pos.   : {len(unauth_positions)}")
        if expected_balance is not None and mt5_balance_now is not None:
            print(f"  │ Expected balance    : ${expected_balance:.2f}")
            print(f"  │ MT5 balance         : ${mt5_balance_now:.2f}")
            if unaccounted_deficit > 0.01:
                print(f"  │ 🚫 Unaccounted deficit: ${unaccounted_deficit:.2f}")
        if any_unauthorized:
            print(f"  │ Status              : ⚠️ UNAUTHORIZED — {', '.join(unauth_types)}")
        else:
            print(f"  │ Status              : ✅ clean")

        # -------- upsert balance_log row for today --------
        today = lagos_today_str()

        # day-start balance: the last recorded closing balance if any, else
        # MT5 balance minus today's realized P&L
        last_date, last_closing = balance_log_fetch_last_closing(
            investor_id, sub_account_id)
        if last_date == today and last_closing is not None:
            day_start_balance = float(last_closing)
        else:
            day_start_balance = float(mt5_balance_now or 0.0) - total_auth_pnl - total_unauth_pnl
            # but that may drift — prefer last_closing if available and
            # today is a fresh row
            if last_closing is not None:
                day_start_balance = float(last_closing)

        closing_balance = float(mt5_balance_now or 0.0)

        unusual = any_unauthorized
        ok, action = balance_log_upsert(
            investor_id, sub_account_id, today,
            day_start_balance=day_start_balance,
            auth_pnl=total_auth_pnl,
            unauth_pnl=total_unauth_pnl,
            unauth_withdrawals=unaccounted_deficit,
            closing_balance=closing_balance,
            unusual=unusual,
            auth_count=auth_count,
            unauth_count=unauth_count,
        )
        if ok:
            detail['balance_log_action'] = action
            print(f"  │ 📝 balance_log {action} for {today}")
        else:
            print(f"  │ ⚠️ balance_log upsert failed")

        # -------- notify if any violation --------
        if any_unauthorized:
            sent = notify_investor_and_owner(
                investor_id=investor_id,
                sub_account_id=sub_account_id,
                programme_id=programme_id,
                investor_email=investor_email,
                owner_email=owner_email,
                programme_name=programme_name,
                unauth_trades=unauthorized_deals,
                unauth_orders=unauth_orders,
                unauth_positions=unauth_positions,
                unauth_pnl=total_unauth_pnl,
                unaccounted_deficit=unaccounted_deficit,
            )
            detail['notifications_sent'] = sent

        return detail

    # ==================================================================
    # SECTION 6 — TOP-LEVEL ENUMERATION
    # ==================================================================
    print("\n" + "─"*80)
    print(" 📁 LOADING INVESTOR JOBS FROM DB (VPS-scoped)")
    print("─"*80)

    local_ip = get_local_ip()
    if not local_ip:
        print(" ⚠️ Could not determine local IP")
        stats['errors'].append('local IP unknown')
        stats['processing_success'] = False
        unauthorized_alert['errors'] = list(stats['errors'])
        return stats
    print(f" │ Local IP: {local_ip}")

    all_jobs = fetch_vps_investor_jobs(local_ip)
    if not all_jobs:
        print(" │ ℹ️ No active investor jobs found for this VPS")
        stats['processing_success'] = True
        return stats

    if inv_db_id:
        jobs = [j for j in all_jobs if str(j.get('investor_id')) == str(inv_db_id)]
        if not jobs:
            print(f" ⚠️ Investor {inv_db_id} not found in any VPS-scoped job")
            stats['errors'].append(f"Investor {inv_db_id} not found")
            stats['processing_success'] = False
            unauthorized_alert['errors'] = list(stats['errors'])
            return stats
    else:
        jobs = all_jobs

    print(f" │ Loaded {len(jobs)} investor job(s) from DB")
    print("─"*80)

    for job in jobs:
        investor_id = job.get('investor_id')
        sub_account_id = job.get('sub_account_id')
        programme_id = job.get('programme_id')
        programme_name = job.get('programme_name') or f"programme_{programme_id}"

        if investor_id is None or sub_account_id is None or programme_id is None:
            continue

        try:
            detail = process_investor(investor_id, sub_account_id,
                                      programme_id, programme_name)
            stats['details'].append(detail)
            stats['investors_processed'] += 1
            stats['unauthorized_orders_found'] += detail.get('unauthorized_orders', 0)
            stats['unauthorized_positions_found'] += detail.get('unauthorized_positions', 0)
            stats['unauthorized_trades_found'] += detail.get('unauthorized_trades', 0)
            if detail.get('unaccounted_deficit', 0.0) > 0.01:
                stats['unaccounted_deficits_found'] += 1
            if detail.get('unauthorized_types'):
                stats['investors_with_unauthorized'] += 1
            if detail.get('balance_log_action'):
                stats['balance_log_rows_written'] += 1
            stats['notifications_queued'] += detail.get('notifications_sent', 0)

            if not unauthorized_alert.get('programme_id'):
                unauthorized_alert['programme_id'] = programme_id
                unauthorized_alert['investor_id'] = investor_id
                unauthorized_alert['sub_account_id'] = sub_account_id
                unauthorized_alert['investor_authorized_magics'] = set()
                unauthorized_alert['application_status'] = detail.get('application_status', 'approved')
                if detail.get('unauthorized_types'):
                    unauthorized_alert['is_triggered'] = True
                    unauthorized_alert['unauthorized_types'] = detail['unauthorized_types']
                    unauthorized_alert['unauthorized_pnl_total'] = detail.get('unauthorized_pnl_total', 0.0)
                    unauthorized_alert['unaccounted_deficit'] = detail.get('unaccounted_deficit', 0.0)
        except Exception as e:
            print(f"\n[CRITICAL] unauthorized-audit investor={investor_id}: {e}")
            traceback.print_exc()
            stats['errors'].append(f"investor={investor_id}: {e}")

    print(f"\n{'='*10} 🔍 AUTHORIZED-ACTIONS AUDIT SUMMARY (DB) {'='*10}")
    print(f"  Investors processed        : {stats['investors_processed']}")
    print(f"  Investors with unauthorized: {stats['investors_with_unauthorized']}")
    print(f"  Unauthorized orders        : {stats['unauthorized_orders_found']}")
    print(f"  Unauthorized positions     : {stats['unauthorized_positions_found']}")
    print(f"  Unauthorized trades        : {stats['unauthorized_trades_found']}")
    print(f"  Unaccounted deficits       : {stats['unaccounted_deficits_found']}")
    print(f"  balance_log rows written   : {stats['balance_log_rows_written']}")
    print(f"  Notifications queued       : {stats['notifications_queued']}")
    print(f"  Errors                     : {len(stats['errors'])}")
    for e in stats['errors']:
        print(f"     • {e}")
    print(f"{'='*10} 🏁 COMPLETE {'='*10}\n")

    stats['processing_success'] = True
    return stats

# ==============================================================================
#  RESTRICTED TIMERANGE — Restricted Dates FIRST, then Restricted Days
# ==============================================================================
def restricted_timerange_db(inv_db_id=None):
    print(f"\n{'='*10} ⏰ PROGRAMME RESTRICTED TIMERANGE {'='*10}")

    local_ip = get_local_ip()
    if not local_ip:
        print("  ⚠️ Could not determine local IP")
        return {
            'investor_id': inv_db_id if inv_db_id else 'all',
            'processing_success': False,
            'errors': ['local IP unknown'],
            'restriction_map': {},
            'any_restricted': False,
        }

    print(f"  🌐 Local IP: {local_ip}")

    programmes = fetch_vps_programmes(local_ip)
    if not programmes:
        print("  ℹ️ No programmes bound to this VPS")
        return {
            'investor_id': inv_db_id if inv_db_id else 'all',
            'processing_success': True,
            'programmes_checked': 0,
            'restriction_map': {},
            'any_restricted': False,
        }

    total_programmes = len(programmes)
    print(f"  📋 Found {total_programmes} programme(s) bound to this VPS")

    # ------------------------------------------------------------------
    # Per-programme restriction verdict, populated as we go.
    # ------------------------------------------------------------------
    restriction_map = {}

    # ------------------------------------------------------------------
    # Helper: fire a programme-scoped restriction notification.
    # ------------------------------------------------------------------
    def _notify_programme_restriction(programme_id, programme_name,
                                      userid, notif_kind,
                                      today_date_str, tz_str,
                                      extra=None):
        extra = extra or {}
        try:
            from notification_service import (
                record_programme_restriction_date_notification,
                record_programme_restriction_day_full_notification,
                record_programme_restriction_day_window_notification,
            )
        except Exception as e:
            print(f"      [PRG][NOTIFY] notification_service unavailable: {e}")
            return None

        owner_email = ''
        try:
            if userid:
                q = db_query(
                    "SELECT email FROM harvhub WHERE id = %s LIMIT 1",
                    [userid], timeout=10.0, quiet=True,
                )
                if _is_ok(q) and q.get('results'):
                    for v in q['results'][0].values():
                        if v is not None:
                            owner_email = str(v).strip().lower()
                            break
        except Exception:
            owner_email = ''

        if not owner_email or '@' not in owner_email:
            print(f"      [PRG][NOTIFY] programme={programme_id} "
                  f"owner email unresolved (userid={userid}) — "
                  f"notification skipped")
            return None

        try:
            if notif_kind == 'restricted_date':
                nid = record_programme_restriction_date_notification(
                    _NOTIF_PDO,
                    programme_id=programme_id,
                    programme_name=programme_name,
                    owner_email=owner_email,
                    restricted_date=today_date_str,
                    timezone_str=tz_str,
                )
            elif notif_kind == 'restricted_day_full':
                nid = record_programme_restriction_day_full_notification(
                    _NOTIF_PDO,
                    programme_id=programme_id,
                    programme_name=programme_name,
                    owner_email=owner_email,
                    day_name=extra.get('day_name', ''),
                    restricted_date=today_date_str,
                    timezone_str=tz_str,
                )
            elif notif_kind == 'restricted_day_window':
                nid = record_programme_restriction_day_window_notification(
                    _NOTIF_PDO,
                    programme_id=programme_id,
                    programme_name=programme_name,
                    owner_email=owner_email,
                    day_name=extra.get('day_name', ''),
                    restricted_date=today_date_str,
                    from_label=extra.get('from_label', ''),
                    to_label=extra.get('to_label', ''),
                    timezone_str=tz_str,
                )
            else:
                return None

            if nid:
                print(f"      [PRG][NOTIFY] programme={programme_id} "
                      f"({notif_kind}) -> notification_id={nid}")
            else:
                print(f"      [PRG][NOTIFY] programme={programme_id} "
                      f"({notif_kind}) -> already sent or ineligible (dedup)")
            return nid
        except Exception as e:
            print(f"      [PRG][NOTIFY] {notif_kind} raised: {e}")
            traceback.print_exc()
            return None

    for idx, prog in enumerate(programmes, start=1):
        programme_id = prog['programme_id']
        developer_id = prog['userid']

        programme_name = fetch_programme_name(programme_id)
        tz_str = fetch_programme_timezone(programme_id)

        if tz_str is None:
            print(f"\n  [{idx}/{total_programmes}] 📊 Programme "
                  f"'{programme_name}' (id={programme_id}) | "
                  f"⚠️ timezone NOT configured — skipping restriction check")
            restriction_map[programme_id] = {
                'is_restricted': False,
                'kind':          None,
                'day_name':      '',
                'window_desc':   'timezone not configured',
            }
            continue

        now_local, resolved = get_current_time_in_timezone(tz_str)
        if not resolved:
            print(f"\n  [{idx}/{total_programmes}] 📊 Programme "
                  f"'{programme_name}' (id={programme_id}) | "
                  f"⚠️ Could not resolve timezone '{tz_str}' "
                  f"— skipping restriction check")
            restriction_map[programme_id] = {
                'is_restricted': False,
                'kind':          None,
                'day_name':      '',
                'window_desc':   f"timezone '{tz_str}' unresolvable",
            }
            continue

        now_day_name = now_local.strftime("%A")
        today_date_str = now_local.strftime("%Y-%m-%d")

        print(f"\n  [{idx}/{total_programmes}] 📊 Programme '{programme_name}' "
              f"(id={programme_id}) | timezone='{tz_str}'")
        print(f"      🕐 Programme now: "
              f"{now_local.strftime('%Y-%m-%d %I:%M:%S %p')} | "
              f"day={now_day_name}")

        # =====================================================================
        # STAGE 1 — Restricted Dates (full-day lockout if today is listed)
        # =====================================================================
        restricted_dates = fetch_programme_restricted_dates(programme_id)

        today_in_dates = False
        if restricted_dates:
            for d in restricted_dates:
                if d == today_date_str:
                    today_in_dates = True
                    break

        print(f"      📋 Restricted dates for '{programme_name}':")
        if not restricted_dates:
            print(f"         (none configured)")
        else:
            for d in restricted_dates:
                marker = "  ⬅ TODAY" if d == today_date_str else ""
                print(f"         • {d}{marker}")

        if today_in_dates:
            print(f"      🚨 {today_date_str} IS a restricted date "
                  f"— FULL-DAY LOCKOUT (Stage 1)")
            day_state = "full_day_date"
            window_desc = "FULL DAY (restricted date)"

            restriction_map[programme_id] = {
                'is_restricted': True,
                'kind':          'restricted_date',
                'day_name':      now_day_name,
                'window_desc':   window_desc,
            }

            _notify_programme_restriction(
                programme_id=programme_id,
                programme_name=programme_name,
                userid=developer_id,
                notif_kind='restricted_date',
                today_date_str=today_date_str,
                tz_str=tz_str,
            )
        else:
            # =================================================================
            # STAGE 2 — Restricted Days (only when Stage 1 did not hit)
            # =================================================================
            print(f"      ℹ️ {today_date_str} is not a restricted date "
                  f"— falling through to Restricted Days")

            restriction_rows = fetch_programme_restricted_days(programme_id)

            today_row = None
            for r in restriction_rows:
                if r['day'].lower() == now_day_name.lower():
                    today_row = r
                    break

            if not restriction_rows:
                print("      ✅ No restricted days configured for this programme")
                day_state = "no_restriction"
                window_desc = "—"

                restriction_map[programme_id] = {
                    'is_restricted': False,
                    'kind':          None,
                    'day_name':      now_day_name,
                    'window_desc':   window_desc,
                }

            elif today_row is None:
                print(f"      ✅ {now_day_name} is NOT restricted for this programme")
                day_state = "not_today"
                window_desc = "—"

                restriction_map[programme_id] = {
                    'is_restricted': False,
                    'kind':          None,
                    'day_name':      now_day_name,
                    'window_desc':   window_desc,
                }

            else:
                from_h, from_m = parse_time_string(today_row['from_time'])
                to_h, to_m = parse_time_string(today_row['to_time'])

                if from_h is None or to_h is None:
                    print(f"      ⚠️ Invalid time format for today's row: "
                          f"{today_row['from_time']} -> {today_row['to_time']}")
                    day_state = "invalid"
                    window_desc = "invalid"

                    restriction_map[programme_id] = {
                        'is_restricted': False,
                        'kind':          None,
                        'day_name':      now_day_name,
                        'window_desc':   window_desc,
                    }

                elif is_full_day_window(from_h, from_m, to_h, to_m):
                    print(f"      🚨 {now_day_name} is FULLY RESTRICTED "
                          f"(no trading allowed all day)")
                    day_state = "full_day"
                    window_desc = "12:00 AM - 12:00 AM (FULL DAY)"

                    restriction_map[programme_id] = {
                        'is_restricted': True,
                        'kind':          'restricted_day_full',
                        'day_name':      now_day_name,
                        'window_desc':   window_desc,
                    }

                    _notify_programme_restriction(
                        programme_id=programme_id,
                        programme_name=programme_name,
                        userid=developer_id,
                        notif_kind='restricted_day_full',
                        today_date_str=today_date_str,
                        tz_str=tz_str,
                        extra={'day_name': now_day_name},
                    )
                else:
                    in_window = is_time_in_window(
                        now_local.hour, now_local.minute,
                        from_h, from_m, to_h, to_m,
                    )
                    window_desc = (f"{to_12hr(from_h, from_m)} - "
                                   f"{to_12hr(to_h, to_m)}")
                    day_state = "in_window" if in_window else "outside_window"
                    marker = ("🔴 WITHIN (restricted)" if in_window
                              else "🟢 OUTSIDE (free)")
                    print(f"      📅 {now_day_name} restricted window: "
                          f"{window_desc} | {marker}")

                    if in_window:
                        restriction_map[programme_id] = {
                            'is_restricted': True,
                            'kind':          'restricted_day_window',
                            'day_name':      now_day_name,
                            'window_desc':   window_desc,
                        }
                    else:
                        restriction_map[programme_id] = {
                            'is_restricted': False,
                            'kind':          None,
                            'day_name':      now_day_name,
                            'window_desc':   window_desc,
                        }

                    if in_window:
                        _notify_programme_restriction(
                            programme_id=programme_id,
                            programme_name=programme_name,
                            userid=developer_id,
                            notif_kind='restricted_day_window',
                            today_date_str=today_date_str,
                            tz_str=tz_str,
                            extra={
                                'day_name':   now_day_name,
                                'from_label': to_12hr(from_h, from_m),
                                'to_label':   to_12hr(to_h, to_m),
                            },
                        )

            print(f"      📋 Restricted days for '{programme_name}':")
            if not restriction_rows:
                print(f"         (none configured)")
            else:
                for r in restriction_rows:
                    fh, fm = parse_time_string(r['from_time'])
                    th, tm = parse_time_string(r['to_time'])
                    if fh is None or th is None:
                        label = f"{r['from_time'] or '—'} -> {r['to_time'] or '—'}"
                    elif is_full_day_window(fh, fm, th, tm):
                        label = "FULL DAY (12:00 AM -> 12:00 AM)"
                    else:
                        label = f"{to_12hr(fh, fm)} -> {to_12hr(th, tm)}"
                    print(f"         • {r['day']:<10} {label}")

        # =====================================================================
        # Per-investor printing (display only, no notifications sent)
        # =====================================================================
        investors = fetch_active_investors_for_programme(programme_id)
        if not investors:
            print(f"      ℹ️ No ACTIVE investors associated with this programme")
            continue

        print(f"      👥 {len(investors)} active investor(s) associated:")

        for inv in investors:
            inv_db_id_val = inv['investor_id']
            sub_id_val = inv['sub_account_id']

            if inv_db_id is not None:
                try:
                    if str(inv_db_id_val) != str(inv_db_id):
                        continue
                except Exception:
                    pass

            identity = fetch_investor_identity(inv_db_id_val)
            username = (identity.get('username')
                        or identity.get('fullname')
                        or f"user{inv_db_id_val}")

            print(
                f"\n         👤 Investor {username} "
                f"id{sub_id_val} is associated with this vps and invested "
                f"in Trader's {programme_name} id{programme_id}"
            )
            print(f"            so according to the trader programme:")

            if day_state == "full_day_date":
                print(f"            Restricted dates:")
                for d in restricted_dates:
                    marker = "  ⬅ TODAY" if d == today_date_str else ""
                    print(f"               • {d}{marker}")
                print(f"            Status right now: 🚨 FULL-DAY LOCKOUT "
                      f"(today is a configured restricted date) "
                      f"— no activities allowed")

            elif day_state == "no_restriction":
                print(f"            Restricted days:")
                print(f"               (none)")
                print(f"            Status right now: no restriction configured")

            elif day_state == "not_today":
                print(f"            Restricted days:")
                for r in restriction_rows:
                    fh, fm = parse_time_string(r['from_time'])
                    th, tm = parse_time_string(r['to_time'])
                    if fh is None or th is None:
                        label = f"{r['from_time'] or '—'} -> {r['to_time'] or '—'}"
                    elif is_full_day_window(fh, fm, th, tm):
                        label = "FULL DAY (12:00 AM -> 12:00 AM)"
                    else:
                        label = f"{to_12hr(fh, fm)} -> {to_12hr(th, tm)}"
                    print(f"               • {r['day']:<10} {label}")
                print(f"            Status right now: {now_day_name} is not restricted")

            elif day_state == "full_day":
                print(f"            Restricted days:")
                for r in restriction_rows:
                    fh, fm = parse_time_string(r['from_time'])
                    th, tm = parse_time_string(r['to_time'])
                    if fh is None or th is None:
                        label = f"{r['from_time'] or '—'} -> {r['to_time'] or '—'}"
                    elif is_full_day_window(fh, fm, th, tm):
                        label = "FULL DAY (12:00 AM -> 12:00 AM)"
                    else:
                        label = f"{to_12hr(fh, fm)} -> {to_12hr(th, tm)}"
                    print(f"               • {r['day']:<10} {label}")
                print(f"            Status right now: 🚨 FULL-DAY RESTRICTION ACTIVE "
                      f"— no activities allowed")

            elif day_state == "in_window":
                print(f"            Restricted days:")
                for r in restriction_rows:
                    fh, fm = parse_time_string(r['from_time'])
                    th, tm = parse_time_string(r['to_time'])
                    if fh is None or th is None:
                        label = f"{r['from_time'] or '—'} -> {r['to_time'] or '—'}"
                    elif is_full_day_window(fh, fm, th, tm):
                        label = "FULL DAY (12:00 AM -> 12:00 AM)"
                    else:
                        label = f"{to_12hr(fh, fm)} -> {to_12hr(th, tm)}"
                    print(f"               • {r['day']:<10} {label}")
                print(f"            Status right now: 🔴 WITHIN restricted window "
                      f"({window_desc}) — no activities allowed")

            elif day_state == "outside_window":
                print(f"            Restricted days:")
                for r in restriction_rows:
                    fh, fm = parse_time_string(r['from_time'])
                    th, tm = parse_time_string(r['to_time'])
                    if fh is None or th is None:
                        label = f"{r['from_time'] or '—'} -> {r['to_time'] or '—'}"
                    elif is_full_day_window(fh, fm, th, tm):
                        label = "FULL DAY (12:00 AM -> 12:00 AM)"
                    else:
                        label = f"{to_12hr(fh, fm)} -> {to_12hr(th, tm)}"
                    print(f"               • {r['day']:<10} {label}")
                print(f"            Status right now: 🟢 outside restricted window "
                      f"({window_desc}) — free to trade")

            else:
                print(f"            Status right now: ⚠️ restriction row is invalid")

    return {
        'investor_id':        inv_db_id if inv_db_id else 'all',
        'processing_success': True,
        'programmes_checked': total_programmes,
        'restriction_map':    restriction_map,
        'any_restricted':     any(
            v.get('is_restricted') for v in restriction_map.values()
        ),
    }


# ==============================================================================
#  RECENT HIGHEST BALANCE TARGET — DB-driven, programme-scoped
# ==============================================================================
def recent_highest_balance_target_db(inv_db_id=None):
    """
    DB-driven recent_highest_balance tracker + daily_target_revenue writer.

    READS:
      * programme_revenue_target          -> daily target config (per programme)
      * harvhub.recent_highest_balance    -> stored last-seen balance per sub-account
      * harvhub.recent_highest_balance_last_update -> last update date per sub-account
      * harvhub.execution_start_date / broker_balance -> contract anchors

    WRITES:
      * harvhub.recent_highest_balance (+ last_update)         per sub-account
      * daily_target_revenue              -> daily target met rows per sub-account
                                            INCLUDING:
                                              - daily_target_owed
                                              - daily_target_owed_day_balance
                                              - daily_target_owed_date

    No JSON. No files. No folders.
    """

    global recent_highest_alert

    from datetime import datetime, timedelta, timezone

    # ------------------------------------------------------------------
    # LAGOS TIMEZONE SETUP
    # ------------------------------------------------------------------
    try:
        from zoneinfo import ZoneInfo
        LAGOS_TZ = ZoneInfo("Africa/Lagos")
        _LAGOS_TZ_SOURCE = "zoneinfo"
    except Exception:
        LAGOS_TZ = timezone(timedelta(hours=1))
        _LAGOS_TZ_SOURCE = "fixed_utc+1"

    def lagos_now():
        return datetime.now(LAGOS_TZ)

    def lagos_today_str():
        return lagos_now().strftime("%Y-%m-%d")

    def lagos_yesterday_str():
        return (lagos_now() - timedelta(days=1)).strftime("%Y-%m-%d")

    def lagos_naive_now():
        return lagos_now().replace(tzinfo=None)

    def lagos_from_timestamp(ts):
        if not ts:
            return None
        try:
            ts_float = float(ts)
        except (TypeError, ValueError):
            return None
        if ts_float > 1e11:
            ts_float = ts_float / 1000.0
        try:
            return datetime.fromtimestamp(ts_float, tz=timezone.utc).astimezone(LAGOS_TZ)
        except Exception:
            return None

    def detect_mt5_server_offset_hours():
        try:
            if not mt5.terminal_info():
                return 0
            candidate_symbols = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US30"]
            tick = None
            for sym in candidate_symbols:
                try:
                    tick = mt5.symbol_info_tick(sym)
                except Exception:
                    tick = None
                if tick is not None:
                    break
            if tick is None or not getattr(tick, 'time', None):
                return 0
            server_naive = datetime.fromtimestamp(tick.time)
            utc_naive = datetime.utcnow()
            diff_seconds = (server_naive - utc_naive).total_seconds()
            diff_seconds = round(diff_seconds / 900.0) * 900.0
            offset_hours = diff_seconds / 3600.0
            if offset_hours < -12 or offset_hours > 14:
                return 0
            return offset_hours
        except Exception:
            return 0

    def lagos_window_to_server_naive(lagos_start_aware, lagos_end_aware):
        server_offset = detect_mt5_server_offset_hours()
        start_utc_naive = lagos_start_aware.astimezone(timezone.utc).replace(tzinfo=None)
        end_utc_naive = lagos_end_aware.astimezone(timezone.utc).replace(tzinfo=None)
        start_server_naive = start_utc_naive + timedelta(hours=server_offset)
        end_server_naive = end_utc_naive + timedelta(hours=server_offset)
        return start_server_naive, end_server_naive, server_offset

    recent_highest_alert = {
        'is_triggered': False,
        'investor_id': inv_db_id if inv_db_id else "all",
        'old_balance': None,
        'new_balance': None,
        'difference': None,
        'timestamp': lagos_now().strftime('%I:%M:%S %p'),
        'action': None,
        'last_update_date': None,
        'today_profit': None,
        'daily_target_risk': None,
        'profit_met_risk_threshold': False,
        'alarm_blocked_reason': None
    }

    print(f"\n{'='*10} 📊 RECENT HIGHEST BALANCE TARGET (DB) {'='*10}")
    print(f" 🕒 Lagos time now: {lagos_now().strftime('%Y-%m-%d %H:%M:%S %Z')} (source: {_LAGOS_TZ_SOURCE})")
    if inv_db_id:
        print(f" 🎯 Target Investor: {inv_db_id}")

    stats = {
        "investor_id": inv_db_id if inv_db_id else "all",
        "investors_checked": 0,
        "investors_updated": 0,
        "investors_skipped": 0,
        "new_high_alerts": 0,
        "new_high_recorded_only": 0,
        "field_created": 0,
        "broker_balance_corrections": 0,
        "stale_record_resets": 0,
        "alarm_confirmations_blocked": 0,
        "activities_updated": 0,
        "daily_target_rows_written": 0,
        "errors": [],
        "current_time": lagos_now().strftime('%I:%M:%S %p'),
        "processing_success": False,
        "details": []
    }

    # ----------------------------------------------------------------
    # DB helpers specific to this stage
    # ----------------------------------------------------------------
    def db_get_harvhub_row(investor_id, sub_account_id):
        sql = """
            SELECT id, sub_account_id, main_account_id, fullname, username, email,
                   broker_balance, execution_start_date,
                   recent_highest_balance, recent_highest_balance_last_update
              FROM harvhub
             WHERE id = %s
               AND sub_account_id = %s
             LIMIT 1
        """
        return db_fetch_one(sql, [investor_id, sub_account_id], timeout=15.0, quiet=True)

    def db_write_recent_balance(investor_id, sub_account_id, balance, date_str):
        sql = """
            UPDATE harvhub
               SET recent_highest_balance = %s,
                   recent_highest_balance_last_update = %s
             WHERE id = %s
               AND sub_account_id = %s
        """
        ok, affected, msg = db_execute(
            sql, [balance, date_str, investor_id, sub_account_id],
            timeout=15.0, quiet=True,
        )
        return ok and affected >= 0

    def db_write_recent_balance_balance_only(investor_id, sub_account_id, balance):
        sql = """
            UPDATE harvhub
               SET recent_highest_balance = %s
             WHERE id = %s
               AND sub_account_id = %s
        """
        ok, affected, msg = db_execute(
            sql, [balance, investor_id, sub_account_id],
            timeout=15.0, quiet=True,
        )
        return ok

    def db_fetch_daily_target_config_for_programme(programme_id):
        rows = db_fetch_all(
            """
            SELECT week_no, day_name, from_balance, to_balance,
                   target_amount, pre_pending_sum,
                   target_daily_profit, include_missed_days,
                   include_current_day_as_owed, loss_streak_chances
              FROM programme_revenue_target
             WHERE programme_id = %s
             ORDER BY week_no ASC, id ASC
            """,
            [programme_id], timeout=15.0, quiet=True,
        )
        if not rows:
            return None

        first = rows[0]
        cfg = {
            'include_missed_days': to_bool(_raw_first_key(first, 'include_missed_days')),
            'include_current_day_as_owed': to_bool(_raw_first_key(first, 'include_current_day_as_owed')),
            'loss_streak_chances': _coerce_int(_raw_first_key(first, 'loss_streak_chances')) or 0,
        }

        for r in rows:
            wk = _coerce_int(_raw_first_key(r, 'week_no')) or 1
            day_name = (_raw_first_key(r, 'day_name') or '').strip()
            if not day_name:
                continue
            day_lower = day_name.lower()

            frm = _coerce_float(_raw_first_key(r, 'from_balance'), default=0.0)
            to_raw = _raw_first_key(r, 'to_balance')
            to_val = _coerce_float(to_raw, default=None)
            target = _coerce_float(_raw_first_key(r, 'target_amount'), default=0.0)
            pre_pending = to_bool(_raw_first_key(r, 'pre_pending_sum'))

            if to_val is None:
                range_key = f"{int(frm)}_risk"
            else:
                range_key = f"{int(frm)}-{int(to_val)}_risk"

            week_key = f"week_{wk}"
            cfg.setdefault(week_key, {})
            cfg[week_key].setdefault('daily_target', {})
            cfg[week_key]['daily_target'].setdefault(day_lower, {})
            cfg[week_key]['daily_target'][day_lower][range_key] = float(target)
            cfg[week_key]['daily_target'][day_lower]['pre-pending_sum'] = pre_pending

        return cfg

    def db_upsert_daily_target_row(userid, sub_account_id,
                                   week_label, day_label, date_str,
                                   daily_target, status,
                                   profit_allocated, remaining_needed,
                                   daily_target_owed=None,
                                   daily_target_owed_day_balance=None,
                                   daily_target_owed_date=None):
        existing = db_fetch_one(
            """
            SELECT id FROM daily_target_revenue
             WHERE userid = %s
               AND sub_account_id = %s
               AND week = %s
               AND day = %s
               AND date = %s
             LIMIT 1
            """,
            [userid, sub_account_id, week_label, day_label, date_str],
            timeout=10.0, quiet=True,
        )
        if existing and _raw_first_key(existing, 'id'):
            row_id = _coerce_int(_raw_first_key(existing, 'id'))
            ok, _, _ = db_execute(
                """
                UPDATE daily_target_revenue
                   SET daily_target = %s,
                       status = %s,
                       profit_allocated = %s,
                       remaining_needed = %s,
                       daily_target_owed = %s,
                       daily_target_owed_day_balance = %s,
                       daily_target_owed_date = %s
                 WHERE id = %s
                """,
                [daily_target, status, profit_allocated, remaining_needed,
                 daily_target_owed, daily_target_owed_day_balance,
                 daily_target_owed_date, row_id],
                timeout=15.0, quiet=True,
            )
            return ok
        else:
            ok, _, _ = db_execute(
                """
                INSERT INTO daily_target_revenue
                    (userid, sub_account_id, week, day, date,
                     daily_target, status, profit_allocated, remaining_needed,
                     daily_target_owed, daily_target_owed_day_balance,
                     daily_target_owed_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [userid, sub_account_id, week_label, day_label, date_str,
                 daily_target, status, profit_allocated, remaining_needed,
                 daily_target_owed, daily_target_owed_day_balance,
                 daily_target_owed_date],
                timeout=15.0, quiet=True,
            )
            return ok

    # ----------------------------------------------------------------
    # Existing logic helpers (no JSON, all DB-driven)
    # ----------------------------------------------------------------
    def get_mt5_balance():
        try:
            if not mt5.terminal_info():
                print(f"   MT5 not connected")
                return None
            account_info = mt5.account_info()
            if account_info:
                return account_info.balance
            return None
        except Exception as e:
            print(f"   Error getting MT5 balance: {e}")
            return None

    def get_mt5_today_profit_and_latest_trade_date():
        try:
            if not mt5.terminal_info():
                return 0.0, None, 0
            lagos_now_aware = lagos_now()
            lagos_start_aware = lagos_now_aware.replace(hour=0, minute=0, second=0, microsecond=0)
            start_srv, end_srv, srv_offset = lagos_window_to_server_naive(lagos_start_aware, lagos_now_aware)
            deals = mt5.history_deals_get(start_srv, end_srv)
            total = 0.0
            latest_time_lagos = None
            if deals:
                for deal in deals:
                    if deal.profit is None:
                        continue
                    total += deal.profit
                    deal_ts = getattr(deal, 'time', None)
                    if not deal_ts:
                        deal_ts = getattr(deal, 'time_msc', None)
                    deal_time_lagos = lagos_from_timestamp(deal_ts)
                    if deal_time_lagos is not None:
                        if latest_time_lagos is None or deal_time_lagos > latest_time_lagos:
                            latest_time_lagos = deal_time_lagos
            return total, latest_time_lagos, srv_offset
        except Exception as e:
            print(f"  ⚠️ Could not get today's profit / trade date: {e}")
            return 0.0, None, 0

    def get_week_number_from_date(start_date, target_date):
        if not start_date or not target_date:
            return 1
        diff_days = (target_date - start_date).days
        if diff_days < 0:
            return 1
        return (diff_days // 7) + 1

    def get_week_config(investor_data, week_number):
        daily_target_config = investor_data.get('daily_target_config', {})
        week_key = f"week_{week_number}"
        week_config = daily_target_config.get(week_key, {})
        if week_config:
            return week_config.get('daily_target', {})
        return None

    def _parse_range_key(range_str):
        if not range_str:
            return None
        try:
            if '-' in range_str:
                lo_str, hi_str = range_str.split('-', 1)
                return float(lo_str), float(hi_str)
            else:
                return 0.0, float(range_str)
        except (TypeError, ValueError):
            return None

    def _resolve_target_for_balance(day_config, balance):
        risk_pairs = []
        for key, value in day_config.items():
            if '_risk' not in key:
                continue
            clean = key.replace('_risk', '').strip()
            parsed = _parse_range_key(clean)
            if parsed is None:
                continue
            lo, hi = parsed
            try:
                target_val = float(value)
            except (TypeError, ValueError):
                continue
            risk_pairs.append((lo, hi, target_val, key))
        if not risk_pairs:
            return 0.0
        if balance is None:
            return risk_pairs[0][2]
        for lo, hi, target_val, _key in risk_pairs:
            if lo <= balance <= hi:
                return target_val
        below = [p for p in risk_pairs if p[0] <= balance]
        if below:
            below.sort(key=lambda p: p[0])
            return below[-1][2]
        risk_pairs.sort(key=lambda p: p[0])
        return risk_pairs[0][2]

    def get_weekly_targets_from_config(investor_data, week_number, balance=None):
        week_config = get_week_config(investor_data, week_number)
        if not week_config:
            return {}
        targets = {}
        for day_name_lower, day_config in week_config.items():
            if isinstance(day_config, dict):
                resolved = _resolve_target_for_balance(day_config, balance)
                targets[day_name_lower] = float(resolved) if resolved is not None else 0.0
            elif isinstance(day_config, (int, float)):
                targets[day_name_lower] = float(day_config)
            else:
                targets[day_name_lower] = 0.0
        return targets

    def get_week_pre_pending_flags(investor_data, week_number):
        week_config = get_week_config(investor_data, week_number)
        if not week_config:
            return {}
        flags = {}
        for day_name_lower, day_config in week_config.items():
            if isinstance(day_config, dict):
                flags[day_name_lower] = bool(day_config.get('pre-pending_sum', False))
            else:
                flags[day_name_lower] = False
        return flags

    def parse_date_flexible(date_str):
        if not date_str:
            return None
        if isinstance(date_str, str) and date_str.strip().upper() == "NULL":
            return None
        if isinstance(date_str, datetime):
            return date_str
        formats = [
            "%Y-%m-%d", "%B %d, %Y", "%B %d %Y", "%Y/%m/%d",
            "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y",
            "%Y-%m-%d %H:%M:%S", "%B %d, %Y %H:%M:%S"
        ]
        for fmt in formats:
            try:
                return datetime.strptime(str(date_str), fmt)
            except:
                continue
        return None

    def get_days_ordered_from_start(start_date, listed_days):
        if not start_date:
            return listed_days
        start_day_name = start_date.strftime("%A").lower()
        standard_days = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday']
        try:
            start_index = standard_days.index(start_day_name)
        except ValueError:
            start_index = 0
        ordered_days = standard_days[start_index:] + standard_days[:start_index]
        listed_days_lower = [day.lower() for day in listed_days]
        result = []
        for day in ordered_days:
            if day in listed_days_lower:
                result.append(day.capitalize())
        return result

    def _get_deals_for_lagos_day(day_date):
        try:
            if not mt5.terminal_info():
                return []
            lagos_start_aware = datetime.combine(
                day_date, datetime.min.time()
            ).replace(tzinfo=LAGOS_TZ)
            lagos_end_aware = lagos_start_aware + timedelta(days=1)
            start_srv, end_srv, _ = lagos_window_to_server_naive(
                lagos_start_aware, lagos_end_aware
            )
            deals = mt5.history_deals_get(start_srv, end_srv)
            if not deals:
                return []
            out = []
            for deal in deals:
                if deal.profit is None:
                    continue
                deal_ts = getattr(deal, 'time', None)
                if not deal_ts:
                    deal_ts = getattr(deal, 'time_msc', None)
                deal_time_lagos = lagos_from_timestamp(deal_ts)
                if deal_time_lagos is None:
                    continue
                out.append((deal_time_lagos, float(deal.profit)))
            out.sort(key=lambda x: x[0])
            return out
        except Exception as e:
            print(f"  ⚠️ Could not fetch deals for {day_date}: {e}")
            return []

    def find_progress_halter_day(investor_data, execution_start_date, effective_today,
                                 contract_start_balance, srv_offset,
                                 current_mt5_balance=None):
        result = {
            'anchor_found': False,
            'anchor_date': '',
            'anchor_day_balance': 0.0,
            'anchor_daily_target': 0.0,
            'anchor_net_profit': 0.0,
            'anchor_week': 0,
            'anchor_day_name': '',
            'is_contract_start_day': False
        }

        start_date = parse_date_flexible(execution_start_date)
        if not start_date:
            return result

        if effective_today is None:
            effective_today = lagos_naive_now()
        if effective_today.tzinfo is not None:
            effective_today = effective_today.astimezone(LAGOS_TZ).replace(tzinfo=None)

        start_date_only = start_date.date()
        scan_date = start_date_only
        end_date = effective_today.date()

        week_targets_cache = {}

        while scan_date <= end_date:
            scan_dt = datetime.combine(scan_date, datetime.min.time())
            wk = get_week_number_from_date(start_date, scan_dt)

            if wk not in week_targets_cache:
                week_targets_cache[wk] = get_weekly_targets_from_config(
                    investor_data, wk, balance=contract_start_balance
                )
            week_targets = week_targets_cache.get(wk, {})

            day_name_lower = scan_date.strftime("%A").lower()
            day_target = week_targets.get(day_name_lower, 0.0) or 0.0

            is_contract_start_day = (scan_date == start_date_only)

            if is_contract_start_day and (current_mt5_balance is not None) and (contract_start_balance is not None):
                day_profit = float(current_mt5_balance) - float(contract_start_balance)
                print(f"  🧮 CONTRACT-START DAY NET P/L:")
                print(f"     Contract-aware start balance (C): ${float(contract_start_balance):.2f}")
                print(f"     Current live MT5 balance (M):    ${float(current_mt5_balance):.2f}")
                print(f"     Contract net P/L for day = M - C: ${day_profit:.2f}")
                print(f"     → {'LOSS' if day_profit < 0 else 'PROFIT / FLAT'}")
            else:
                day_deals = _get_deals_for_lagos_day(scan_date)
                day_profit = sum(p for _, p in day_deals)

            if day_profit < 0:
                halter_balance = contract_start_balance

                result['anchor_found'] = True
                result['anchor_date'] = scan_date.strftime("%Y-%m-%d")
                result['anchor_day_balance'] = float(halter_balance) if halter_balance is not None else 0.0
                result['anchor_daily_target'] = float(day_target)
                result['anchor_net_profit'] = float(day_profit)
                result['anchor_week'] = wk
                result['anchor_day_name'] = scan_date.strftime("%A")
                result['is_contract_start_day'] = is_contract_start_day

                print(f"  🎯 PROGRESS-HALTER DAY FOUND: {result['anchor_date']} ({result['anchor_day_name']}, week {wk})")
                print(f"     Start-of-day balance: ${result['anchor_day_balance']:.2f}")
                print(f"     Daily target: ${result['anchor_daily_target']:.2f}")
                print(f"     Net P/L for day: ${result['anchor_net_profit']:.2f}")
                if is_contract_start_day:
                    print(f"     ⚠️ Contract-start day: the recorded loss IS what halts progress.")
                return result

            scan_date += timedelta(days=1)

        print(f"  ✅ No progress-halter (loss) day found from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        return result

    def compute_loss_streak_from_halter(anchor_info, srv_offset, loss_streak_chances,
                                        contract_start_balance=None,
                                        current_mt5_balance=None):
        out = {
            'streak_position': 0,
            'remaining_chances': int(loss_streak_chances) if loss_streak_chances else 0,
            'total_losses': 0,
            'total_wins': 0,
            'streak_started_at': None,
            'last_trade_time': None,
            'skipped_previous_contract_deals': 0,
            'reconciled': False,
            'boundary_index': None,
            'first_counted_deal_time': None,
            'streak_skipped_reason': None
        }

        if not anchor_info or not anchor_info.get('anchor_found'):
            return out

        is_contract_start_day = bool(anchor_info.get('is_contract_start_day', False))

        if is_contract_start_day:
            out['streak_skipped_reason'] = (
                "halter is the contract-start day — the recorded loss itself "
                "halts progress; no streak is counted"
            )
            print(f"  📉 Loss-streak: SKIPPED — {out['streak_skipped_reason']}")
            return out

        try:
            if not mt5.terminal_info():
                return out

            anchor_date_str = anchor_info['anchor_date']
            anchor_date = parse_date_flexible(anchor_date_str)
            if not anchor_date:
                return out

            lagos_start_aware = datetime.combine(
                anchor_date.date(), datetime.min.time()
            ).replace(tzinfo=LAGOS_TZ)
            lagos_now_aware = lagos_now()

            start_srv, end_srv, _ = lagos_window_to_server_naive(
                lagos_start_aware, lagos_now_aware
            )

            deals = mt5.history_deals_get(start_srv, end_srv)
            if not deals:
                return out

            trades = []
            for deal in deals:
                if deal.profit is None:
                    continue
                deal_ts = getattr(deal, 'time', None)
                if not deal_ts:
                    deal_ts = getattr(deal, 'time_msc', None)
                deal_time_lagos = lagos_from_timestamp(deal_ts)
                if deal_time_lagos is None:
                    continue
                trades.append((deal_time_lagos, float(deal.profit)))

            trades.sort(key=lambda x: x[0])
            if not trades:
                return out

            out['boundary_index'] = 0
            out['first_counted_deal_time'] = trades[0][0].strftime("%Y-%m-%d %H:%M:%S")

            cumulative = 0.0
            peak = 0.0
            streak = 0
            total_losses = 0
            total_wins = 0
            streak_started_at = None

            for t_time, t_profit in trades:
                cumulative += t_profit
                if t_profit < 0:
                    streak += 1
                    total_losses += 1
                    if streak == 1:
                        streak_started_at = t_time
                elif t_profit > 0:
                    total_wins += 1
                    if cumulative >= peak:
                        streak = 0
                        streak_started_at = None
                        peak = cumulative

            out['streak_position'] = streak
            out['total_losses'] = total_losses
            out['total_wins'] = total_wins
            if loss_streak_chances:
                out['remaining_chances'] = max(0, int(loss_streak_chances) - streak)
            else:
                out['remaining_chances'] = 0

            if streak_started_at:
                out['streak_started_at'] = streak_started_at.strftime("%Y-%m-%d %H:%M:%S")
            out['last_trade_time'] = trades[-1][0].strftime("%Y-%m-%d %H:%M:%S")

            print(f"  📉 Loss-streak from halter: position={streak}, "
                  f"remaining={out['remaining_chances']}, "
                  f"losses={total_losses}, wins={total_wins}")
            return out
        except Exception as e:
            print(f"  ⚠️ Could not compute loss streak from halter: {e}")
            return out

    def calculate_daily_target_status(investor_data, profit, execution_start_date,
                                      inv_db_id=None, starting_balance_for_today=None,
                                      effective_today=None,
                                      anchor_info=None,
                                      halter_recovered=False):
        result = {
            'weekly_targets': {},
            'today_met': False,
            'alarm_trigger': False,
            'total_owed': 0.0,
            'total_owed_with_shortage': 0.0,
            'today_target_met': False,
            'pre_pending_total': 0.0,
            'pre_pending_enabled': False,
            'total_all_debt': 0.0,
            'daily_target_owed': 0.0,
            'balance_used_for_bracket': starting_balance_for_today,
            'include_missed_days': False,
            'include_current_day_as_owed': False,
            'effective_today': effective_today.strftime("%Y-%m-%d") if effective_today else None,
            'anchor_found': bool(anchor_info and anchor_info.get('anchor_found')),
            'anchor_date': anchor_info.get('anchor_date') if anchor_info else '',
            'anchor_day_balance': anchor_info.get('anchor_day_balance') if anchor_info else 0.0,
            'anchor_daily_target': anchor_info.get('anchor_daily_target') if anchor_info else 0.0,
            'anchor_net_profit': anchor_info.get('anchor_net_profit') if anchor_info else 0.0,
            'halter_recovered': bool(halter_recovered),
        }

        if not execution_start_date:
            print(f"  ⚠️ No execution start date, cannot calculate daily targets")
            return result

        start_date = parse_date_flexible(execution_start_date)
        if not start_date:
            print(f"  ⚠️ Could not parse execution start date: {execution_start_date}")
            return result

        if effective_today is None:
            effective_today = lagos_naive_now()
        else:
            if effective_today.tzinfo is not None:
                effective_today = effective_today.astimezone(LAGOS_TZ).replace(tzinfo=None)

        current_date = effective_today
        today_str = current_date.strftime("%Y-%m-%d")
        current_week = get_week_number_from_date(start_date, current_date)

        lagos_wall_now = lagos_naive_now()

        daily_target_config = investor_data.get('daily_target_config', {})
        include_missed_days = daily_target_config.get('include_missed_days', False) if daily_target_config else False
        include_current_day_as_owed = daily_target_config.get('include_current_day_as_owed', False) if daily_target_config else False
        result['include_missed_days'] = include_missed_days
        result['include_current_day_as_owed'] = include_current_day_as_owed

        print(f"\n  📊 CALCULATING DAILY TARGET STATUS (SECTION 2)")
        print(f"  ──────────────────────────────────────────")
        print(f"  📅 Execution Start: {start_date.strftime('%Y-%m-%d')} ({start_date.strftime('%A')})")
        print(f"  📅 Current Date (Lagos wall clock): {lagos_wall_now.strftime('%Y-%m-%d')} ({lagos_wall_now.strftime('%A')})")
        if effective_today.strftime("%Y-%m-%d") != lagos_wall_now.strftime("%Y-%m-%d"):
            print(f"  📅 EFFECTIVE TODAY (trade-date aligned, Lagos): {effective_today.strftime('%Y-%m-%d')} ({effective_today.strftime('%A')})")
            print(f"     ⚠️ Profit attributed to trade date, NOT calendar date")
        else:
            print(f"  📅 Effective Date (Lagos): {effective_today.strftime('%Y-%m-%d')} ({effective_today.strftime('%A')})")
        print(f"  📆 Current Week: {current_week}")
        print(f"  💰 Total Profit: ${profit:.2f}")
        print(f"  📌 Week starts on: {start_date.strftime('%A')} (execution start day)")
        print(f"  🔁 Include Missed Days: {'YES ✅' if include_missed_days else 'NO ⏭️ (past missed days will be skipped)'}")
        print(f"  🔁 Include Current Day As Owed: {'YES ✅' if include_current_day_as_owed else 'NO ⏭️ (today is always PENDING)'}")
        if starting_balance_for_today is not None:
            print(f"  🎯 Balance used for bracket resolution: ${starting_balance_for_today:.2f}")
        else:
            print(f"  🎯 Balance used for bracket resolution: N/A (will use first bracket)")

        if anchor_info and anchor_info.get('anchor_found'):
            if halter_recovered:
                print(f"  ✅ PROGRESS-HALTER RECOVERED: {anchor_info['anchor_date']} ({anchor_info['anchor_day_name']})")
                print(f"     The loss has been bought back — normal daily-target logic resumed.")
            else:
                print(f"  🛑 PROGRESS-HALTER ACTIVE: {anchor_info['anchor_date']} ({anchor_info['anchor_day_name']})")
                print(f"     Progress HALTED at this day until its loss is recovered.")
                print(f"     Halter net P/L: ${anchor_info['anchor_net_profit']:.2f}")
                print(f"     Halter daily target: ${anchor_info['anchor_daily_target']:.2f}")

        anchor_date_str = anchor_info.get('anchor_date') if anchor_info else None
        halt_active = bool(anchor_info and anchor_info.get('anchor_found')) and not halter_recovered

        for week_num in range(1, current_week + 1):
            week_key = f"week_{week_num}"
            week_targets = get_weekly_targets_from_config(
                investor_data, week_num, balance=starting_balance_for_today
            )
            week_pre_pending_flags = get_week_pre_pending_flags(investor_data, week_num)

            if not week_targets:
                print(f"  ⚠️ No targets found for {week_key} - skipping")
                continue

            week_start_date = start_date + timedelta(days=(week_num - 1) * 7)
            week_end_date = week_start_date + timedelta(days=6)

            week_is_entirely_past = week_end_date.date() < current_date.date()
            if week_is_entirely_past and not include_missed_days:
                print(f"\n  📆 {week_key.upper()}: {week_start_date.strftime('%Y-%m-%d')} ({week_start_date.strftime('%A')}) to {week_end_date.strftime('%Y-%m-%d')} ({week_end_date.strftime('%A')})")
                print(f"  ⏭️ SKIPPED (fully past week, include_missed_days=False) — no debt, no profit consumed")
                continue

            result['weekly_targets'][week_key] = {}

            print(f"\n  📆 {week_key.upper()}: {week_start_date.strftime('%Y-%m-%d')} ({week_start_date.strftime('%A')}) to {week_end_date.strftime('%Y-%m-%d')} ({week_end_date.strftime('%A')})")

            listed_days = list(week_targets.keys())
            ordered_days = get_days_ordered_from_start(week_start_date, listed_days)
            print(f"  📋 Ordered days (starting from {week_start_date.strftime('%A')}): {', '.join(ordered_days)}")

            remaining_profit = profit

            week_pre_pending_enabled = any(week_pre_pending_flags.values()) if week_pre_pending_flags else False
            week_pre_pending_total = 0.0

            for day_name_proper in ordered_days:
                day_name_lower = day_name_proper.lower()

                day_index = None
                for offset in range(7):
                    check_date = week_start_date + timedelta(days=offset)
                    if check_date.strftime("%A").lower() == day_name_lower:
                        day_index = offset
                        break

                if day_index is None:
                    continue

                check_date = week_start_date + timedelta(days=day_index)
                day_date_str = check_date.strftime("%Y-%m-%d")
                target = week_targets.get(day_name_lower, 0.0) or 0.0
                pre_pending_flag = week_pre_pending_flags.get(day_name_lower, False)

                is_today = (day_date_str == today_str)
                is_past_day = check_date.date() < current_date.date()
                is_future = check_date.date() > current_date.date()

                is_halter_day = bool(anchor_date_str) and (day_date_str == anchor_date_str)
                is_halted = bool(halt_active and anchor_date_str and (day_date_str >= anchor_date_str))

                if is_past_day:
                    if not include_missed_days:
                        status = 'skipped'
                        profit_allocated = 0.0
                    else:
                        if remaining_profit >= target:
                            if is_halted:
                                status = 'owed'
                                profit_allocated = remaining_profit
                                remaining_profit = 0
                            else:
                                status = 'met'
                                profit_allocated = target
                                remaining_profit -= target
                        else:
                            status = 'owed'
                            profit_allocated = remaining_profit
                            remaining_profit = 0
                elif is_today:
                    if remaining_profit >= target:
                        if is_halted:
                            if include_current_day_as_owed:
                                status = 'owed'
                                profit_allocated = remaining_profit
                                remaining_profit = 0
                            else:
                                status = 'pending'
                                profit_allocated = remaining_profit
                                remaining_profit = 0
                        else:
                            status = 'met'
                            profit_allocated = target
                            remaining_profit -= target
                    else:
                        if include_current_day_as_owed:
                            status = 'owed'
                            profit_allocated = remaining_profit
                            remaining_profit = 0
                        else:
                            status = 'pending'
                            profit_allocated = remaining_profit
                            remaining_profit = 0
                else:
                    status = 'pending'
                    profit_allocated = 0.0

                is_pre_pending_day = False
                if (week_num == current_week
                        and is_future
                        and pre_pending_flag):
                    is_pre_pending_day = True
                    week_pre_pending_total += target

                result['weekly_targets'][week_key][day_name_proper] = {
                    "date": day_date_str,
                    "daily_target": target,
                    "status": status,
                    "profit_allocated": profit_allocated,
                    "is_listed": True,
                    "remaining_needed": max(0, target - profit_allocated),
                    "pre_pending_sum": pre_pending_flag,
                    "is_pre_pending_day": is_pre_pending_day,
                    "is_halter_day": is_halter_day,
                    "is_halted": is_halted,
                    "at_or_after_anchor": is_halted,
                    "halted": is_halted,
                }

                if is_today:
                    if status == 'met':
                        result['today_met'] = True
                        result['today_target_met'] = True
                        print(f"\n  ✅ TODAY ({day_name_proper}): Target MET! Profit allocation: ${profit_allocated:.2f} >= ${target:.2f}")
                    elif status == 'owed':
                        result['today_met'] = False
                        result['today_target_met'] = False
                        print(f"\n  ⚠️ TODAY ({day_name_proper}): Target OWED (include_current_day_as_owed=True). "
                              f"Profit allocation: ${profit_allocated:.2f} < ${target:.2f}")
                        print(f"     Remaining needed today (now added to owed debt): ${target - profit_allocated:.2f}")
                    else:
                        result['today_met'] = False
                        result['today_target_met'] = False
                        print(f"\n  ⏳ TODAY ({day_name_proper}): Target PENDING (in-progress). Profit allocation: ${profit_allocated:.2f} < ${target:.2f}")
                        print(f"     Remaining needed today: ${target - profit_allocated:.2f}")
                        print(f"     📌 Today is NEVER declared OWED — it is always PENDING until met.")
                        if is_halted and not is_halter_day:
                            print(f"     🛑 Progress still halted by the {anchor_date_str} loss.")

            week_met = sum(1 for d in result['weekly_targets'][week_key].values() if d['status'] == 'met')
            week_owed = sum(1 for d in result['weekly_targets'][week_key].values() if d['status'] == 'owed')
            week_pending = sum(1 for d in result['weekly_targets'][week_key].values() if d['status'] == 'pending')
            week_skipped = sum(1 for d in result['weekly_targets'][week_key].values() if d['status'] == 'skipped')
            week_profit_allocated = sum(d['profit_allocated'] for d in result['weekly_targets'][week_key].values())

            print(f"\n  💰 Week {week_num} allocated: ${week_profit_allocated:.2f}, Remaining profit: ${remaining_profit:.2f}")
            print(f"  📊 Week {week_num} summary: {week_met} MET, {week_owed} OWED, {week_pending} PENDING, {week_skipped} SKIPPED")
            if week_pre_pending_enabled:
                print(f"  🔮 Week {week_num} pre-pending total (forward, tomorrow->end of week): ${week_pre_pending_total:.2f}")

            if week_num == current_week:
                result['pre_pending_total'] = week_pre_pending_total
                result['pre_pending_enabled'] = week_pre_pending_enabled

            profit = remaining_profit

        total_owed = 0.0
        for week_key, week_data in result['weekly_targets'].items():
            for day, day_data in week_data.items():
                if day_data.get('is_listed', True) and day_data['status'] == 'owed':
                    total_owed += (day_data['daily_target'] - day_data['profit_allocated'])

        result['total_owed'] = total_owed
        result['total_owed_with_shortage'] = total_owed

        total_all_debt = total_owed + result['pre_pending_total']
        result['total_all_debt'] = total_all_debt
        result['daily_target_owed'] = total_all_debt

        if result['pre_pending_enabled']:
            print(f"\n  🔮 PRE-PENDING MODE ACTIVE (current week)")
            print(f"  ──────────────────────────────────────")
            print(f"  💰 Owed Debt (backward, PAST days only): ${total_owed:.2f}")
            print(f"  🔮 Pre-Pending Sum (forward, current week): ${result['pre_pending_total']:.2f}")
            print(f"  📊 Total All Debt (daily_target_owed): ${total_all_debt:.2f}")
            if not include_missed_days:
                print(f"  ⏭️ Note: past missed days were SKIPPED (include_missed_days=False)")

            if total_all_debt <= 0:
                result['alarm_trigger'] = True
                print(f"\n  🚨 ALARM TRIGGERED: Owed debt + pre-pending sum fully covered!")
                print(f"  📌 Today's date is IGNORED in pre-pending mode.")
                print(f"  📌 Alarm stays ON until a new week begins.")
            else:
                result['alarm_trigger'] = False
                print(f"\n  🔇 Alarm OFF: Total debt still outstanding (${total_all_debt:.2f} remaining needed)")
        else:
            if result['today_met'] and total_owed == 0:
                result['alarm_trigger'] = True
                print(f"\n  🚨 ALARM TRIGGERED: Today's target met and no owed debts!")
            else:
                result['alarm_trigger'] = False
                if not result['today_met']:
                    print(f"\n  🔇 Alarm OFF: Today's target not met (still PENDING)")
                if total_owed > 0:
                    print(f"\n  🔇 Alarm OFF: Owed debts exist (${total_owed:.2f} remaining needed)")

        print(f"\n  📊 FINAL STATUS:")
        print(f"  ──────────────────")
        print(f"  Include Missed Days: {'YES ✅' if include_missed_days else 'NO ⏭️'}")
        print(f"  Include Current Day As Owed: {'YES ✅' if include_current_day_as_owed else 'NO ⏭️'}")
        print(f"  Today's Target Met: {'YES ✅' if result['today_met'] else 'NO ⏳ (PENDING)'}")
        print(f"  Total Owed (backward, PAST days only): ${total_owed:.2f}")
        print(f"  Pre-Pending Total (forward, current week): ${result['pre_pending_total']:.2f}")
        print(f"  Pre-Pending Enabled: {'YES 🔮' if result['pre_pending_enabled'] else 'NO'}")
        print(f"  Total All Debt: ${total_all_debt:.2f}")
        print(f"  Daily Target Owed (combined): ${result['daily_target_owed']:.2f}")
        print(f"  Alarm Trigger: {'YES 🚨' if result['alarm_trigger'] else 'NO 🔇'}")

        return result

    def confirm_alarm_with_mt5(alarm_result, mt5_balance, starting_balance,
                               today_profit, latest_trade_dt):
        try:
            if not alarm_result.get('alarm_trigger'):
                return False, "alarm_not_requested", 0.0
            if mt5_balance is None:
                return False, "mt5_balance_unavailable", 0.0
            starting_balance = float(starting_balance or 0.0)

            today_target = 0.0
            for week_data in alarm_result.get('weekly_targets', {}).values():
                for day_name, day_data in week_data.items():
                    if day_data.get('date') == alarm_result.get('effective_today'):
                        today_target = float(day_data.get('daily_target', 0.0) or 0.0)
                        break

            if alarm_result.get('pre_pending_enabled'):
                total_debt = float(alarm_result.get('total_all_debt', 0.0) or 0.0)
                required_minimum = starting_balance + total_debt
                mode_label = "PRE-PENDING"
            else:
                total_debt = 0.0
                required_minimum = starting_balance + today_target
                mode_label = "DAILY"

            print(f"\n  🔐 ALARM CONFIRMATION GUARD ({mode_label}):")
            print(f"     Stored recent_highest_balance math has triggered the alarm")
            print(f"     Now verifying against LIVE MT5 balance...")
            print(f"     ├─ Starting balance: ${starting_balance:.2f}")
            if alarm_result.get('pre_pending_enabled'):
                print(f"     ├─ Total debt (owed + pre-pending): ${total_debt:.2f}")
            else:
                print(f"     ├─ Today's target: ${today_target:.2f}")
            print(f"     ├─ Required minimum live MT5 balance: ${required_minimum:.2f}")
            print(f"     └─ Actual LIVE MT5 balance: ${mt5_balance:.2f}")

            if mt5_balance + 0.01 < required_minimum:
                shortfall = required_minimum - mt5_balance
                reason = (
                    f"live MT5 balance ${mt5_balance:.2f} is below required minimum "
                    f"${required_minimum:.2f} (shortfall ${shortfall:.2f})"
                )
                print(f"     🚫 ALARM BLOCKED — {reason}")
                return False, reason, required_minimum

            print(f"     ✅ ALARM CONFIRMED — live balance meets the required minimum")
            return True, "confirmed", required_minimum
        except Exception as e:
            return False, f"confirmation_error: {e}", 0.0

    # ================================================================
    # ENUMERATE INVESTORS (DB-driven)
    # ================================================================
    print("\n" + "─"*80)
    print(" 📁 LOADING INVESTOR JOBS FROM DB (VPS-scoped)")
    print("─"*80)

    local_ip = get_local_ip()
    if not local_ip:
        print(" ⚠️ Could not determine local IP — cannot enumerate investors")
        stats["errors"].append("local IP unknown")
        stats["processing_success"] = False
        return stats

    print(f" │ Local IP: {local_ip}")

    all_jobs = fetch_vps_investor_jobs(local_ip)
    if not all_jobs:
        print(" │ ℹ️ No active investor jobs found for this VPS")
        stats["processing_success"] = True
        return stats

    if inv_db_id:
        jobs = [j for j in all_jobs if str(j.get('investor_id')) == str(inv_db_id)]
        if not jobs:
            print(f" ⚠️ Investor {inv_db_id} not found in any VPS-scoped job")
            stats["errors"].append(f"Investor {inv_db_id} not found")
            stats["processing_success"] = False
            return stats
    else:
        jobs = all_jobs

    print(f" │ Loaded {len(jobs)} investor job(s) from DB")
    print("─"*80)

    investors_to_process = jobs

    print(f"\n 📋 Processing {len(investors_to_process)} investors...")

    has_updates = False

    for job in investors_to_process:
        inv_db_id_db = job.get('investor_id')
        sub_id_db = job.get('sub_account_id')
        programme_id = job.get('programme_id')
        programme_name = job.get('programme_name') or f"programme_{programme_id}"

        inv_db_id_str = str(inv_db_id_db)

        print(f"\n{'─'*80}")
        print(f" 📊 INVESTOR: {inv_db_id_db} (sub {sub_id_db}) | Programme: {programme_name} (id={programme_id})")
        print(f"{'─'*80}")

        identity = fetch_investor_identity(inv_db_id_db)
        username = (identity.get('username')
                    or identity.get('fullname')
                    or f"user{inv_db_id_db}")

        print(f"\n  📌 According to this programme '{programme_name}' (id={programme_id}):")
        print(f"     Investor {username} sub account {sub_id_db} "
              f"is bound to this programme's revenue target configuration.")

        # ============================================================
        # SECTION 1: MT5 BALANCE MANAGEMENT
        # ============================================================
        print(f"\n  🔵 SECTION 1: MT5 BALANCE MANAGEMENT")
        print(f"  ─────────────────────────────────────")

        mt5_balance = get_mt5_balance()
        if mt5_balance is None:
            print(f"  ⚠️ Could not get MT5 balance - Skipping investor {inv_db_id_db}")
            stats["errors"].append(f"Could not get MT5 balance for {inv_db_id_db}")
            stats["investors_skipped"] += 1
            continue

        print(f"  💰 Current MT5 Balance: ${mt5_balance:.2f}")

        hub_row = db_get_harvhub_row(inv_db_id_db, sub_id_db)
        if not hub_row:
            print(f"  ⚠️ No harvhub row found for id={inv_db_id_db} sub={sub_id_db} - skipping")
            stats["errors"].append(f"No harvhub row for {inv_db_id_db}/{sub_id_db}")
            stats["investors_skipped"] += 1
            continue

        broker_balance = _coerce_float(_raw_first_key(hub_row, 'broker_balance'), default=None)
        execution_start_date = _raw_first_key(hub_row, 'execution_start_date')

        existing_recent = _coerce_float(_raw_first_key(hub_row, 'recent_highest_balance'), default=None)
        existing_last_update = _raw_first_key(hub_row, 'recent_highest_balance_last_update')

        print(f"  📁 Recent highest balance last updated for {username} sub account {sub_id_db}: "
              f"{existing_last_update if existing_last_update else 'NEVER'}")
        if existing_recent is not None:
            print(f"  📁 Recent highest balance for {username} sub account {sub_id_db} is: "
                  f"${existing_recent:.2f}")

        today_profit, latest_trade_dt, srv_offset = get_mt5_today_profit_and_latest_trade_date()
        today_start_balance = mt5_balance - today_profit

        wall_clock_now = lagos_naive_now()
        effective_today = wall_clock_now

        if today_profit > 0 and latest_trade_dt is not None:
            latest_trade_lagos_naive = latest_trade_dt.replace(tzinfo=None)
            if latest_trade_lagos_naive.date() < wall_clock_now.date():
                effective_today = latest_trade_lagos_naive
                print(f"  📅 Today's realised profit: ${today_profit:.2f} (Lagos day)")
                print(f"  🎯 Today's START-OF-DAY balance: ${today_start_balance:.2f}")
                print(f"  🕒 Latest contributing trade (Lagos): {latest_trade_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                print(f"  🌐 MT5 server offset detected: {srv_offset:+.2f}h from UTC")
                print(f"  ⚠️ TRADE-DATE MISMATCH (Lagos): Profit was made on "
                      f"{latest_trade_lagos_naive.strftime('%A %Y-%m-%d')}, "
                      f"but processing on {wall_clock_now.strftime('%A %Y-%m-%d')}")
                print(f"  🔁 SHIFTING target resolution to trade date: "
                      f"{effective_today.strftime('%Y-%m-%d')} ({effective_today.strftime('%A')})")
            else:
                print(f"  📅 Today's realised profit: ${today_profit:.2f} (Lagos day)")
                print(f"  🎯 Today's START-OF-DAY balance: ${today_start_balance:.2f}")
                print(f"  🕒 Latest contributing trade (Lagos): {latest_trade_dt.strftime('%Y-%m-%d %H:%M:%S %Z')} (same Lagos day ✅)")
                print(f"  🌐 MT5 server offset detected: {srv_offset:+.2f}h from UTC")
        else:
            print(f"  📅 Today's realised profit: ${today_profit:.2f} (Lagos day)")
            print(f"  🎯 Today's START-OF-DAY balance: ${today_start_balance:.2f}")
            print(f"  🌐 MT5 server offset detected: {srv_offset:+.2f}h from UTC")
            if today_profit > 0:
                print(f"  🕒 Latest contributing trade date: unavailable (using Lagos wall clock)")

        yesterday_str = lagos_yesterday_str()
        today_str = lagos_today_str()

        if execution_start_date:
            exec_start_parsed = parse_date_flexible(execution_start_date)
            if exec_start_parsed:
                exec_start_date_str = exec_start_parsed.strftime("%Y-%m-%d")
                if exec_start_date_str == today_str:
                    print(f"\n  🛡️ START-OF-DAY BALANCE GUARD:")
                    print(f"     Execution start date ({exec_start_date_str}) == today ({today_str})")
                    print(f"     → Falling back to broker_balance for bracket resolution")
                    print(f"     → Using contract-aware balance: ${broker_balance if broker_balance is not None else mt5_balance:.2f}")
                    today_start_balance = broker_balance if broker_balance is not None else mt5_balance
                else:
                    print(f"\n  🛡️ START-OF-DAY BALANCE GUARD:")
                    print(f"     Execution start date ({exec_start_date_str}) != today ({today_str})")
                    print(f"     → Using MT5 start-of-day balance for bracket resolution: ${today_start_balance:.2f}")
        else:
            print(f"\n  🛡️ START-OF-DAY BALANCE GUARD:")
            print(f"     No execution start date found — using MT5 start-of-day balance: ${today_start_balance:.2f}")

        stale_record_detected = False
        if existing_recent is not None and existing_last_update and execution_start_date:
            exec_start_parsed = parse_date_flexible(execution_start_date)
            stored_date_parsed = parse_date_flexible(existing_last_update)
            if exec_start_parsed and stored_date_parsed:
                if stored_date_parsed.date() < exec_start_parsed.date():
                    stale_record_detected = True

        if stale_record_detected:
            print(f"\n  🧹 STALE RECORD GUARD:")
            print(f"     Stored recent_highest_balance_last_update = {existing_last_update}")
            print(f"     Execution start date = {execution_start_date}")
            print(f"     → Stored record is from a PREVIOUS contract (date is behind execution start)")
            print(f"     → Resetting recent_highest_balance recording for the new contract")

            if broker_balance is not None:
                reset_balance = broker_balance
            else:
                reset_balance = mt5_balance

            if mt5_balance < reset_balance:
                print(f"     ⚠️ MT5 balance ${mt5_balance:.2f} < reset anchor ${reset_balance:.2f}")
                print(f"     → Using broker_balance as reset anchor: ${reset_balance:.2f}")
            else:
                reset_balance = mt5_balance
                print(f"     → Using MT5 balance as reset anchor: ${reset_balance:.2f}")

            print(f"     → New date: {yesterday_str} (yesterday, Lagos)")
            print(f"     → New balance: ${reset_balance:.2f}")

            db_write_recent_balance(inv_db_id_db, sub_id_db, round(reset_balance, 2), yesterday_str)

            existing_recent = reset_balance
            existing_last_update = yesterday_str
            stats["stale_record_resets"] += 1
            has_updates = True

            print(f"     ✅ Record reset complete")

        if existing_recent is None:
            print(f"\n  📝 RECENT HIGHEST BALANCE DOES NOT EXIST - INITIALIZING")
            print(f"  ─────────────────────────────────────────────────────")
            print(f"  💰 Current MT5 Balance: ${mt5_balance:.2f}")

            if broker_balance is not None:
                starting_balance = broker_balance
            else:
                starting_balance = mt5_balance

            print(f"  📊 Starting Balance (Broker): ${starting_balance:.2f}")

            if mt5_balance < starting_balance:
                init_balance = starting_balance
                print(f"\n  ⚠️ MT5 Balance (${mt5_balance:.2f}) is less than Starting Balance (${starting_balance:.2f})")
                print(f"  🔧 Using Starting Balance as initial Recent Highest Balance: ${init_balance:.2f}")
            else:
                init_balance = mt5_balance
                print(f"\n  ✅ Using MT5 Balance as initial Recent Highest Balance: ${init_balance:.2f}")

            total_profit = init_balance - starting_balance
            print(f"  📈 Total Profit: ${total_profit:.2f}")

            if not execution_start_date:
                execution_start_date = today_str

            print(f"\n  ✅ INITIALIZED: Recent Highest Balance = ${init_balance:.2f}")
            print(f"  📅 Date set to: {yesterday_str} (YESTERDAY, Lagos)")
            print(f"  🔇 Alarm OFF - Trading allowed")

            recent_highest_alert = {
                'is_triggered': False,
                'investor_id': inv_db_id_db,
                'old_balance': None,
                'new_balance': init_balance,
                'difference': None,
                'timestamp': lagos_now().strftime('%I:%M:%S %p'),
                'action': 'initialized',
                'last_update_date': yesterday_str,
                'today_profit': None,
                'daily_target_risk': None,
                'profit_met_risk_threshold': False,
                'alarm_blocked_reason': None,
                'init_source': 'mt5_balance' if mt5_balance >= starting_balance else 'starting_balance'
            }

            db_write_recent_balance(inv_db_id_db, sub_id_db, round(init_balance, 2), yesterday_str)
            print(f"  💾 Recent highest balance initialised for {username} sub account {sub_id_db}: "
                  f"${init_balance:.2f} on {yesterday_str}")

            stats["investors_updated"] += 1
            stats["investors_checked"] += 1
            stats["field_created"] += 1
            has_updates = True
            continue

        print(f"\n  📊 Checking for new high...")
        print(f"  📊 Stored Recent Highest: ${existing_recent:.2f}")
        print(f"  📊 Current MT5 Balance: ${mt5_balance:.2f}")

        if mt5_balance > existing_recent:
            print(f"\n  📈 NEW HIGHER BALANCE DETECTED!")
            print(f"  ──────────────────────────────")
            print(f"  🆕 New Balance: ${mt5_balance:.2f} (↑${mt5_balance - existing_recent:.2f})")
            print(f"  📅 Date NOT updated yet - waiting for daily target check")

            stats["investors_updated"] += 1
            stats["new_high_recorded_only"] += 1
            has_updates = True

            db_write_recent_balance_balance_only(inv_db_id_db, sub_id_db, round(mt5_balance, 2))
            print(f"  💾 Recent highest balance for {username} sub account {sub_id_db} updated to: "
                  f"${mt5_balance:.2f} (date preserved: {existing_last_update})")

            existing_recent = mt5_balance

            print(f"  ✅ Balance updated to: ${mt5_balance:.2f}")
            print(f"  📅 Date preserved: {existing_last_update}")

        # ============================================================
        # SECTION 2: DAILY TARGET CALCULATIONS
        # ============================================================
        print(f"\n  🟢 SECTION 2: DAILY TARGET CALCULATIONS")
        print(f"  ────────────────────────────────────────")
        print(f"  📊 Using recent_highest_balance (from harvhub): ${existing_recent:.2f}")

        daily_target_config = db_fetch_daily_target_config_for_programme(programme_id)

        if not daily_target_config:
            print(f"  ⚠️ No programme revenue target config found for programme "
                  f"'{programme_name}' (id={programme_id}) — skipping daily target calculations")
            stats["investors_skipped"] += 1
            stats["investors_checked"] += 1
            continue

        print(f"  ✅ Loaded programme revenue target config for '{programme_name}' (id={programme_id})")

        starting_balance = broker_balance
        if starting_balance is None:
            starting_balance = existing_recent
            print(f"  ⚠️ No broker_balance on harvhub — falling back to recent_highest_balance as anchor")

        total_profit = existing_recent - starting_balance
        print(f"  💰 Starting Balance: ${starting_balance:.2f}")
        print(f"  💰 Total Profit: ${total_profit:.2f}")

        if not execution_start_date:
            execution_start_date = today_str
            print(f"  ⚠️ No execution start date found - using today (Lagos): {execution_start_date}")

        contract_start_balance = broker_balance
        if contract_start_balance is None:
            contract_start_balance = starting_balance
        if contract_start_balance is None:
            contract_start_balance = today_start_balance

        print(f"  🎯 Contract-aware start balance (for halter + reconciliation): ${contract_start_balance:.2f}")

        print(f"\n  🔍 SCANNING FOR PROGRESS-HALTER DAY (contract start → today)...")

        loss_streak_chances = daily_target_config.get('loss_streak_chances', 0) or 0
        print(f"  📊 loss_streak_chances (from programme_revenue_target): {loss_streak_chances}")

        anchor_info = find_progress_halter_day(
            {'daily_target_config': daily_target_config},
            execution_start_date,
            effective_today,
            contract_start_balance,
            srv_offset,
            current_mt5_balance=mt5_balance
        )

        halter_recovered = False
        if anchor_info.get('anchor_found'):
            halter_net_profit = float(anchor_info.get('anchor_net_profit', 0.0) or 0.0)
            if contract_start_balance is not None:
                c = float(contract_start_balance)
                live = float(mt5_balance)
                if live + 1e-9 >= c:
                    halter_recovered = True
            if halter_net_profit >= 0:
                halter_recovered = True

            print(f"\n  🧮 HALTER RECOVERY CHECK:")
            print(f"     Contract-aware start balance (C): ${float(contract_start_balance):.2f}")
            print(f"     Live MT5 balance (M):            ${float(mt5_balance):.2f}")
            print(f"     Halter net P/L (loss):           ${halter_net_profit:.2f}")
            if halter_recovered:
                print(f"     → M >= C → loss bought back → RECOVERED")
            else:
                shortfall = float(contract_start_balance) - float(mt5_balance)
                print(f"     → M < C  → loss NOT bought back → STILL HALTED")
                print(f"       Shortfall to recover: ${shortfall:.2f}")

        if anchor_info.get('anchor_found'):
            print(f"\n  🛑 PROGRESS-HALTER DAY: {anchor_info['anchor_date']} "
                  f"({anchor_info['anchor_day_name']}, week {anchor_info['anchor_week']})")
            print(f"     Balance at halter start: ${anchor_info['anchor_day_balance']:.2f}")
            print(f"     Daily target at halter: ${anchor_info['anchor_daily_target']:.2f}")
            print(f"     Net P/L that day: ${anchor_info['anchor_net_profit']:.2f}")
            print(f"     Contract-start day? {'YES' if anchor_info.get('is_contract_start_day') else 'NO'}")
            if halter_recovered:
                print(f"     ✅ RECOVERED — the loss has been bought back; normal logic resumes.")
            else:
                print(f"     🛑 ACTIVE — progress halted until the loss is recovered.")
        else:
            print(f"\n  ✅ NO PROGRESS-HALTER (loss) DAY FOUND — progress flows freely.")

        loss_streak_info = compute_loss_streak_from_halter(
            anchor_info, srv_offset, loss_streak_chances,
            contract_start_balance=contract_start_balance,
            current_mt5_balance=mt5_balance
        )

        result = calculate_daily_target_status(
            {'daily_target_config': daily_target_config},
            total_profit,
            execution_start_date,
            inv_db_id_db,
            starting_balance_for_today=today_start_balance,
            effective_today=effective_today,
            anchor_info=anchor_info,
            halter_recovered=halter_recovered
        )

        weekly_targets = result['weekly_targets']
        today_met = result['today_met']
        alarm_trigger = result['alarm_trigger']
        total_owed = result['total_owed']
        total_owed_with_shortage = result['total_owed_with_shortage']
        today_target_met = result['today_target_met']
        pre_pending_total = result['pre_pending_total']
        pre_pending_enabled = result['pre_pending_enabled']
        total_all_debt = result['total_all_debt']
        daily_target_owed_combined = result['daily_target_owed']

        daily_target_owed_value = float(daily_target_owed_combined or 0.0)

        if anchor_info.get('anchor_found'):
            owed_day_balance_value = float(anchor_info.get('anchor_day_balance', 0.0) or 0.0)
            owed_date_value = anchor_info.get('anchor_date', '') or ''
        else:
            if contract_start_balance is not None:
                owed_day_balance_value = float(contract_start_balance)
            elif starting_balance is not None:
                owed_day_balance_value = float(starting_balance)
            else:
                owed_day_balance_value = float(today_start_balance or 0.0)
            owed_date_value = ''

        print(f"\n  📌 HANDOFF FIELDS (persisted to daily_target_revenue):")
        print(f"     daily_target_owed              : ${daily_target_owed_value:.2f}")
        print(f"     daily_target_owed_day_balance  : ${owed_day_balance_value:.2f}")
        print(f"     daily_target_owed_date         : {owed_date_value or 'NULL'}")

        alarm_confirmed = False
        alarm_block_reason = None
        alarm_required_minimum = 0.0

        if alarm_trigger:
            print(f"\n  🔐 MATH SAYS ALARM SHOULD TRIGGER — requesting live confirmation...")
            alarm_confirmed, alarm_block_reason, alarm_required_minimum = confirm_alarm_with_mt5(
                result, mt5_balance, starting_balance, today_profit, latest_trade_dt
            )
            if not alarm_confirmed:
                alarm_trigger = False
                stats["alarm_confirmations_blocked"] += 1
                print(f"  🚫 ALARM DOWNGRADED to OFF due to failed confirmation")

        if weekly_targets:
            print(f"\n  📊 WEEKLY TARGET BREAKDOWN:")
            print(f"  ──────────────────────────")
            for week_key, week_data in weekly_targets.items():
                print(f"\n  📆 {week_key.upper()}:")
                for day, day_data in week_data.items():
                    status = day_data['status']
                    allocated = day_data['profit_allocated']
                    target = day_data['daily_target']
                    date_str = day_data['date']
                    is_listed = day_data.get('is_listed', True)
                    remaining_needed = day_data.get('remaining_needed', 0)
                    pre_pending_flag = day_data.get('pre_pending_sum', False)
                    is_pre_pending_day = day_data.get('is_pre_pending_day', False)

                    is_halter_day = day_data.get('is_halter_day', False)
                    is_halted = day_data.get('is_halted', False)

                    if not is_listed:
                        print(f"    ℹ️ {day} ({date_str}): NOT LISTED, no analysis")
                        continue

                    status_emoji = "✅" if status == 'met' else "⚠️" if status == 'owed' else "⏳"
                    status_text = "MET" if status == 'met' else "OWED" if status == 'owed' else "PENDING"
                    pre_pending_tag = " 🔮[PRE-PENDING]" if pre_pending_flag else ""
                    pre_pending_active = " ⬅️ ADDED TO PRE-PENDING" if is_pre_pending_day else ""
                    halter_tag = " 🛑[PROGRESS-HALTER]" if is_halter_day else ""
                    held_note = ""
                    if is_halted and not is_halter_day and not halter_recovered:
                        held_note = " (held by halter)"

                    print(f"    {status_emoji} {day} ({date_str}){pre_pending_tag}{pre_pending_active}{halter_tag}{held_note}:")
                    print(f"       Target: ${target:.2f}")
                    print(f"       Allocated: ${allocated:.2f}")
                    print(f"       Status: {status_text}")
                    if status == 'owed':
                        print(f"       Remaining Needed: ${remaining_needed:.2f}")
                    if is_pre_pending_day:
                        print(f"       ⬅️ Counted toward pre-pending sum: ${target:.2f}")

        rows_written = 0
        for week_key, week_data in weekly_targets.items():
            for day_name, day_data in week_data.items():
                status = day_data['status']
                target = day_data['daily_target']
                allocated = day_data['profit_allocated']
                remaining = day_data.get('remaining_needed', 0.0)
                date_str = day_data['date']

                ok = db_upsert_daily_target_row(
                    userid=inv_db_id_db,
                    sub_account_id=sub_id_db,
                    week_label=week_key,
                    day_label=day_name,
                    date_str=date_str,
                    daily_target=round(target, 8),
                    status=status,
                    profit_allocated=round(allocated, 8),
                    remaining_needed=round(remaining, 8),
                    daily_target_owed=round(daily_target_owed_value, 8),
                    daily_target_owed_day_balance=round(owed_day_balance_value, 8),
                    daily_target_owed_date=owed_date_value or None,
                )
                if ok:
                    rows_written += 1

        stats["daily_target_rows_written"] += rows_written

        print(f"\n  💾 Daily target met updated to {username} sub account {sub_id_db}: "
              f"{rows_written} row(s) written to daily_target_revenue")
        print(f"     ├─ daily_target_owed             : ${daily_target_owed_value:.2f}")
        print(f"     ├─ daily_target_owed_day_balance : ${owed_day_balance_value:.2f}")
        print(f"     └─ daily_target_owed_date        : {owed_date_value or 'NULL'}")

        if alarm_trigger:
            print(f"\n  🚨 ALARM TRIGGERED (CONFIRMED)!")
            print(f"  ───────────────────")
            if pre_pending_enabled:
                print(f"  🔮 Pre-Pending Mode: All debt (owed + current-week pre-pending) covered")
                print(f"     Owed Debt (backward, PAST days only): ${total_owed:.2f}")
                print(f"     Pre-Pending Sum (forward): ${pre_pending_total:.2f}")
                print(f"     Daily Target Owed (combined): ${daily_target_owed_combined:.2f}")
                print(f"     📌 Today's date IGNORED - alarm stays ON until new week")
            else:
                print(f"  ✅ Today's target met: {today_met}")
                print(f"  ✅ No owed debts (PAST days only): {total_owed == 0}")
            print(f"  📅 Updating recent_highest_balance_last_update to TODAY (Lagos): {today_str}")
            print(f"  🚨 TRADING SUSPENDED!")

            recent_highest_alert = {
                'is_triggered': True,
                'investor_id': inv_db_id_db,
                'old_balance': existing_recent,
                'new_balance': existing_recent,
                'difference': 0,
                'timestamp': lagos_now().strftime('%I:%M:%S %p'),
                'action': 'alarm_triggered',
                'last_update_date': today_str,
                'today_profit': today_profit,
                'daily_target_risk': None,
                'profit_met_risk_threshold': True,
                'alarm_blocked_reason': None,
                'pre_pending_enabled': pre_pending_enabled,
                'pre_pending_total': pre_pending_total,
                'total_all_debt': total_all_debt,
                'daily_target_owed': daily_target_owed_combined,
                'effective_today': effective_today.strftime("%Y-%m-%d"),
                'trade_date_aligned': False,
                'timezone': "Africa/Lagos",
                'alarm_confirmed_against_live_mt5': True,
                'alarm_required_minimum': alarm_required_minimum
            }

            db_write_recent_balance(inv_db_id_db, sub_id_db,
                                    round(existing_recent, 2), today_str)

            print(f"  💾 Recent highest balance last updated for {username} sub account "
                  f"{sub_id_db} set to {today_str}")

            stats["new_high_alerts"] += 1
            stats["investors_updated"] += 1

        else:
            print(f"\n  🔇 ALARM OFF - Trading continues")
            if alarm_block_reason:
                print(f"  🚫 ALARM WAS BLOCKED BY CONFIRMATION GUARD:")
                print(f"     Reason: {alarm_block_reason}")
                if alarm_required_minimum > 0:
                    print(f"     Required live MT5 minimum: ${alarm_required_minimum:.2f}")
                    print(f"     Actual live MT5 balance:   ${mt5_balance:.2f}")
            if pre_pending_enabled:
                print(f"  🔮 Pre-Pending Mode Active - Total debt still outstanding")
                print(f"     Owed Debt (backward, PAST days only): ${total_owed:.2f}")
                print(f"     Pre-Pending Sum (forward): ${pre_pending_total:.2f}")
                print(f"     Daily Target Owed (combined): ${daily_target_owed_combined:.2f}")
            else:
                if not today_met:
                    print(f"   Today's target not met (still PENDING)")
                if total_owed > 0:
                    print(f"  ⚠️ Owed debts exist (PAST days only): ${total_owed:.2f} remaining needed")
            if anchor_info.get('anchor_found'):
                if halter_recovered:
                    print(f"  ✅ Progress-halter recovered: {anchor_info['anchor_date']}")
                else:
                    print(f"  🛑 Progress-halter active: {anchor_info['anchor_date']} — progress halted until recovered")
            print(f"  📅 Date NOT updated - kept as: {existing_last_update}")

            recent_highest_alert = {
                'is_triggered': False,
                'investor_id': inv_db_id_db,
                'old_balance': existing_recent,
                'new_balance': existing_recent,
                'difference': 0,
                'timestamp': lagos_now().strftime('%I:%M:%S %p'),
                'action': 'alarm_off',
                'last_update_date': existing_last_update,
                'today_profit': today_profit,
                'daily_target_risk': None,
                'profit_met_risk_threshold': today_met,
                'alarm_blocked_reason': (
                    alarm_block_reason
                    if alarm_block_reason
                    else (
                        f"Total debt outstanding: ${daily_target_owed_combined:.2f}" if pre_pending_enabled
                        else (f"Today's target still PENDING" if not today_met else f"Owed debts (PAST days): ${total_owed:.2f}")
                    )
                ),
                'pre_pending_enabled': pre_pending_enabled,
                'pre_pending_total': pre_pending_total,
                'total_all_debt': total_all_debt,
                'daily_target_owed': daily_target_owed_combined,
                'effective_today': effective_today.strftime("%Y-%m-%d"),
                'trade_date_aligned': False,
                'timezone': "Africa/Lagos"
            }

        stats["investors_checked"] += 1
        stats["investors_updated"] += 1
        has_updates = True

        stats["details"].append({
            "investor_id": inv_db_id_db,
            "sub_account_id": sub_id_db,
            "programme_id": programme_id,
            "action": "alarm_triggered" if alarm_trigger else "alarm_off",
            "recent_highest_balance": existing_recent,
            "starting_balance": starting_balance,
            "today_start_balance": today_start_balance,
            "contract_start_balance": contract_start_balance,
            "total_profit": total_profit,
            "today_target_met": today_met,
            "alarm_triggered": alarm_trigger,
            "alarm_confirmed_against_live_mt5": alarm_confirmed,
            "alarm_blocked_reason": alarm_block_reason,
            "alarm_required_minimum": alarm_required_minimum,
            "total_owed": total_owed,
            "total_owed_with_shortage": total_owed_with_shortage,
            "pre_pending_enabled": pre_pending_enabled,
            "pre_pending_total": pre_pending_total,
            "total_all_debt": total_all_debt,
            "daily_target_owed": daily_target_owed_combined,
            "daily_target_owed_day_balance": owed_day_balance_value,
            "daily_target_owed_date": owed_date_value,
            "include_current_day_as_owed": result.get('include_current_day_as_owed', False),
            "last_update_date": today_str if alarm_trigger else existing_last_update,
            "effective_today": effective_today.strftime("%Y-%m-%d"),
            "latest_trade_date": latest_trade_dt.strftime("%Y-%m-%d %H:%M:%S %Z") if latest_trade_dt else None,
            "trade_date_aligned": False,
            "timezone": "Africa/Lagos",
            "mt5_server_offset_hours": srv_offset,
            "recent_balance_source": "harvhub.recent_highest_balance",
            "daily_target_rows_written": rows_written,
            "anchor_found": bool(anchor_info.get('anchor_found')),
            "anchor_recovered": bool(halter_recovered),
            "anchor_date": anchor_info.get('anchor_date', ''),
            "anchor_day_balance": anchor_info.get('anchor_day_balance', 0.0),
            "anchor_daily_target": anchor_info.get('anchor_daily_target', 0.0),
            "anchor_net_profit": anchor_info.get('anchor_net_profit', 0.0),
            "anchor_is_contract_start_day": bool(anchor_info.get('is_contract_start_day', False)),
            "loss_streak_position": loss_streak_info.get('streak_position', 0),
            "loss_streak_remaining": loss_streak_info.get('remaining_chances', 0),
            "loss_streak_skipped_reason": loss_streak_info.get('skipped_reason'),
            "timestamp": lagos_now().strftime("%Y-%m-%d %H:%M:%S")
        })

    print(f"\n{'='*10} 📊 RECENT BROKER BALANCE SUMMARY (DB) {'='*10}")
    print(f"  Investors checked: {stats['investors_checked']}")
    print(f"  Field created: {stats['field_created']}")
    print(f"  Stale record resets: {stats['stale_record_resets']}")
    print(f"  Alarm confirmations blocked: {stats['alarm_confirmations_blocked']}")
    print(f"  New highs recorded (total): {stats['new_high_recorded_only']}")
    print(f"  New high alerts triggered: {stats['new_high_alerts']}")
    print(f"  Investors updated: {stats['investors_updated']}")
    print(f"  Investors skipped: {stats['investors_skipped']}")
    print(f"  daily_target_revenue rows written: {stats['daily_target_rows_written']}")

    if stats['new_high_alerts'] > 0:
        print(f"\n  🚨 ALARM ACTIVE: {stats['new_high_alerts']} investor(s)")
        for detail in stats['details']:
            if detail.get('alarm_triggered'):
                mode = "PRE-PENDING" if detail.get('pre_pending_enabled') else "DAILY"
                print(f"     • {detail['investor_id']}: Balance: ${detail['recent_highest_balance']:.2f} [{mode}] 🔴")

    if stats['alarm_confirmations_blocked'] > 0:
        print(f"\n  🚫 ALARM CONFIRMATIONS BLOCKED: {stats['alarm_confirmations_blocked']} investor(s)")
        for detail in stats['details']:
            if detail.get('alarm_blocked_reason'):
                print(f"     • {detail['investor_id']}: {detail['alarm_blocked_reason']}")

    if stats['stale_record_resets'] > 0:
        print(f"\n  🧹 STALE RECORD RESETS: {stats['stale_record_resets']} investor(s)")

    if stats['new_high_recorded_only'] > 0:
        print(f"\n  📈 NEW HIGHS RECORDED: {stats['new_high_recorded_only']} investor(s)")
        for detail in stats['details']:
            if detail.get('action') == 'alarm_off' and detail.get('total_owed', 0) == 0:
                print(f"     • {detail['investor_id']}: New high ${detail['recent_highest_balance']:.2f} recorded (alarm OFF) 📈")

    if recent_highest_alert and recent_highest_alert.get('is_triggered'):
        print(f"\n  🚨 ALARM ACTIVE: {recent_highest_alert['investor_id']} - Trading SUSPENDED")

    print(f"{'='*10} 🏁 COMPLETE {'='*10}\n")

    stats["processing_success"] = True
    return stats


# ==============================================================================
#  STAGE RUNNER — isolate any future stage failure
# ==============================================================================
def run_stage(name, fn, **kwargs):
    t0 = time.time()
    print(f"\n[STAGE ▶] {name}")
    try:
        result = fn(**kwargs)
        if not isinstance(result, dict):
            result = {'result': result}
        result.setdefault('processing_success', True)
        result['_stage_name'] = name
        result['_elapsed'] = round(time.time() - t0, 3)
        print(f"[STAGE ✓] {name} ({result['_elapsed']}s)")
        return result
    except Exception as e:
        print(f"[STAGE ✗] {name} raised: {e}")
        traceback.print_exc()
        return {
            '_stage_name': name,
            '_elapsed': round(time.time() - t0, 3),
            'processing_success': False,
            'error': str(e),
        }


def run_stages_sequential(stages, **common_kwargs):
    out = {}
    for name, fn in stages:
        out[name] = run_stage(name, fn, **common_kwargs)
    return out


# ==============================================================================
#  RESTRICTION GATE HELPERS
# ==============================================================================
def _programme_restriction_verdict(timerange_stats, programme_id):
    """
    Extract the restriction verdict for a specific programme from the
    result of restricted_timerange_db(). Returns {} if the programme was not
    classified (treated as "not restricted").
    """
    if not isinstance(timerange_stats, dict):
        return {}
    rmap = timerange_stats.get('restriction_map') or {}
    if not isinstance(rmap, dict):
        return {}
    verdict = rmap.get(programme_id)
    if not isinstance(verdict, dict):
        return {}
    return verdict


def _restriction_skip_banner(inv_db_id, sub_id, programme_id, programme_name,
                             verdict):
    kind = verdict.get('kind') or 'unknown'
    day_name = verdict.get('day_name') or ''
    window_desc = verdict.get('window_desc') or ''

    reason_map = {
        'restricted_date':      'today is a configured restricted date',
        'restricted_day_full':  'today is a fully paused trading day',
        'restricted_day_window':'the current time falls inside a paused window',
    }
    reason = reason_map.get(kind, 'a restriction is active')

    print(f"\n[STAGE ⏭] Investor {inv_db_id} (sub {sub_id}) | "
          f"programme '{programme_name}' (id={programme_id})")
    print(f"           🚫 RESTRICTED — {reason}")
    if day_name:
        print(f"           📅 Day: {day_name}")
    if window_desc:
        print(f"           🕐 Window: {window_desc}")
    print(f"           ⏭️  Skipping recent_highest_balance_target_db and every "
          f"future stage — no trade activity allowed right now.")


def _daily_target_alarm_banner(inv_db_id, sub_id, programme_id, programme_name,
                               alert):
    """
    Uniform log banner for the daily-target alarm short-circuit. Mirrors
    the local file's `recent_highest_hit` path.
    """
    mode = "PRE-PENDING" if alert.get('pre_pending_enabled') else "DAILY"
    owed = alert.get('daily_target_owed')
    pre_pending = alert.get('pre_pending_total')
    total_debt = alert.get('total_all_debt')
    effective_today = alert.get('effective_today')

    print(f"\n[STAGE ⏭] Investor {inv_db_id} (sub {sub_id}) | "
          f"programme '{programme_name}' (id={programme_id})")
    print(f"           🚨 DAILY-TARGET ALARM ACTIVE [{mode}] — "
          f"trading suspended, all future stages skipped.")
    if effective_today:
        print(f"           📅 Effective trade date: {effective_today}")
    if owed is not None:
        print(f"           💰 Daily target owed (combined): ${float(owed):.2f}")
    if pre_pending is not None:
        print(f"           🔮 Pre-pending total: ${float(pre_pending):.2f}")
    if total_debt is not None:
        print(f"           📊 Total all debt: ${float(total_debt):.2f}")

# ==============================================================================
#  MARTINGALE — DB version (complete, non-grid)
#
#  Configuration ownership:
#    ┌─────────────────────────────────────────────────────────────────────┐
#    │ PROGRAMME CONFIGURATION  (fetched ONCE per programme, shared)        │
#    │   source: accountmanagement_trades_martingale                        │
#    │           accountmanagement_balance_default_risk                     │
#    │           accountmanagement.fixed_risk_reward / minimum_risk_reward  │
#    │           programme_revenue_target.loss_streak_chances               │
#    │           signals_provider_interest.risk_reward  (profit_factor R:R) │
#    ├─────────────────────────────────────────────────────────────────────┤
#    │ INVESTOR STATE  (fetched PER INVESTOR, independent per investor)     │
#    │   source: harvhub (broker_balance = execution-start balance)         │
#    │           daily_target_revenue (owed, day_balance, owed_date)        │
#    │           MT5 (current balance, positions, pending orders)           │
#    │           programme_trades (investor-scoped pending rows)            │
#    └─────────────────────────────────────────────────────────────────────┘
#
#  profit_factor semantics:
#     The R:R is a multiplier that turns RISK into REWARD.
#     The target we must recover is the REWARD. So:
#
#         required_risk   = target_reward / rr
#         required_volume = required_risk / (SL_distance × contract)
#
#     If the SL is reached: volume × SL_distance × contract is lost.
#     If the TP is reached: that amount × rr is gained.
#
#     Rows are PENDING — no event has occurred. Log lines use "risk X
#     → reward Y" (or "risk X" for stoploss_factor). Never "hit".
#
#  stoploss_factor semantics: unchanged — risk = target.
# ==============================================================================
def martingale_system_db(inv_db_id=None):
    global martingale_alert
    from datetime import datetime, timedelta, timezone

    # ------------------------------------------------------------------
    # LAGOS TIMEZONE
    # ------------------------------------------------------------------
    try:
        from zoneinfo import ZoneInfo
        LAGOS_TZ = ZoneInfo("Africa/Lagos")
        _LAGOS_TZ_SOURCE = "zoneinfo"
    except Exception:
        LAGOS_TZ = timezone(timedelta(hours=1))
        _LAGOS_TZ_SOURCE = "fixed_utc+1"

    def lagos_now():
        return datetime.now(LAGOS_TZ)

    def lagos_now_str():
        return lagos_now().strftime("%Y-%m-%d %H:%M:%S")

    martingale_alert = {
        'is_triggered': False,
        'investor_id': inv_db_id if inv_db_id else 'all',
        'programme_id': None,
        'stage': 0,
        'stage_drawdown': 0.0,
        'total_drawdown': 0.0,
        'sequence_next_risk': 0.0,
        'rows_updated': 0,
        'rows_restored': 0,
        'mt5_cancelled': 0,
        'mode': None,
        'factor': None,
        'programme_rr': None,
        'errors': [],
        'timestamp': lagos_now_str(),
    }

    print(f"\n{'='*10} 🎰 MARTINGALE SYSTEM (DB) {'='*10}")
    print(f" 🕒 Lagos time now: {lagos_now().strftime('%Y-%m-%d %H:%M:%S %Z')} (source: {_LAGOS_TZ_SOURCE})")
    if inv_db_id:
        print(f" 🎯 Target Investor: {inv_db_id}")

    stats = {
        'investor_id': inv_db_id if inv_db_id else 'all',
        'investors_processed': 0,
        'investors_skipped': 0,
        'programmes_processed': 0,
        'rows_updated': 0,
        'rows_restored': 0,
        'mt5_cancelled': 0,
        'errors': [],
        'processing_success': False,
        'details': [],
    }

    # ==================================================================
    # SECTION 1 — PROGRAMME CONFIGURATION READERS
    # ==================================================================
    def programme_fetch_martingale_config(programme_id):
        return db_fetch_all(
            """
            SELECT id, developerid, programme_id,
                   from_balance, to_balance,
                   enable_martingale, martingale_type, martingale_factor,
                   martingale_for_position_order_scale,
                   martingale_loss_recovery_adder_percentage,
                   pre_drawdown_assumption, martingale_pre_scaling,
                   martingale_linear_scaling,
                   enable_initial_risk_retention,
                   initial_risk_retention_percentage,
                   martingale_per_stage_drawdown_amount
              FROM accountmanagement_trades_martingale
             WHERE programme_id = %s
             ORDER BY from_balance ASC, id ASC
            """,
            [programme_id], timeout=15.0, quiet=True,
        )

    def programme_fetch_default_risk_rows(programme_id):
        return db_fetch_all(
            """
            SELECT from_balance_range, to_balance_range, risk_amount
              FROM accountmanagement_balance_default_risk
             WHERE programme_id = %s
            """,
            [programme_id], timeout=10.0, quiet=True,
        )

    def programme_fetch_rr_config(programme_id):
        return db_fetch_one(
            """
            SELECT fixed_risk_reward, minimum_risk_reward
              FROM accountmanagement
             WHERE developerid = 0 AND programme_id = %s AND investorid = 0
             LIMIT 1
            """,
            [programme_id], timeout=10.0, quiet=True,
        )

    def programme_fetch_loss_streak_chances(programme_id):
        row = db_fetch_one(
            """
            SELECT loss_streak_chances
              FROM programme_revenue_target
             WHERE programme_id = %s
             LIMIT 1
            """,
            [programme_id], timeout=10.0, quiet=True,
        )
        return _coerce_int(_raw_first_key(row or {}, 'loss_streak_chances')) or 0

    def programme_fetch_signal_provider_risk_reward(programme_id):
        row = db_fetch_one(
            """
            SELECT risk_reward, risk_reward_type
              FROM signals_provider_interest
             WHERE programme_id = %s
               AND risk_reward IS NOT NULL
               AND risk_reward > 0
             ORDER BY id DESC
             LIMIT 1
            """,
            [programme_id], timeout=10.0, quiet=True,
        )
        if not row:
            return None
        rr = _coerce_float(_raw_first_key(row, 'risk_reward'), default=None)
        if rr is None or rr <= 0:
            return None
        return float(rr)

    # ==================================================================
    # SECTION 2 — INVESTOR-SPECIFIC READERS
    # ==================================================================
    def investor_fetch_harvhub_anchor(investor_id, sub_account_id):
        return db_fetch_one(
            """
            SELECT id, sub_account_id, broker_balance, execution_start_date
              FROM harvhub
             WHERE id = %s AND sub_account_id = %s
             LIMIT 1
            """,
            [investor_id, sub_account_id], timeout=15.0, quiet=True,
        )

    def investor_fetch_daily_target(investor_id, sub_account_id):
        return db_fetch_one(
            """
            SELECT id, userid, sub_account_id, week, day, date,
                   daily_target, status, profit_allocated, remaining_needed,
                   daily_target_owed, daily_target_owed_day_balance,
                   daily_target_owed_date
              FROM daily_target_revenue
             WHERE userid = %s
               AND sub_account_id = %s
               AND daily_target_owed IS NOT NULL
             ORDER BY updated_at DESC, id DESC
             LIMIT 1
            """,
            [investor_id, sub_account_id], timeout=15.0, quiet=True,
        )

    def investor_fetch_pending_trades(investor_id, sub_account_id, programme_id):
        return db_fetch_all(
            """
            SELECT id, tradeid, userid, programmeid,
                   investor_id, investor_sub_account_id,
                   symbol, ordertype, orderstatus, timeframe,
                   entry, stoploss, takeprofit,
                   trade_risk_reward, volume,
                   created_at, updated_at
              FROM programme_trades
             WHERE userid = %s
               AND programmeid = %s
               AND investor_id = %s
               AND investor_sub_account_id = %s
               AND orderstatus = 'pending'
             ORDER BY id ASC
            """,
            [investor_id, programme_id, investor_id, sub_account_id],
            timeout=15.0, quiet=True,
        )

    def update_trade_volume(trade_row_id, new_volume):
        ok, affected, msg = db_execute(
            "UPDATE programme_trades SET volume = %s WHERE id = %s",
            [round(float(new_volume), 8), trade_row_id],
            timeout=15.0, quiet=True,
        )
        return ok and affected >= 0

    def delete_trade_row(trade_row_id):
        ok, affected, msg = db_execute(
            "DELETE FROM programme_trades WHERE id = %s",
            [trade_row_id], timeout=15.0, quiet=True,
        )
        return ok

    def restore_trade_row(investor_id, sub_account_id, programme_id,
                          tradeid, symbol, ordertype, entry, stoploss,
                          takeprofit, volume, timeframe=None,
                          trade_risk_reward=None):
        existing = db_fetch_one(
            """
            SELECT id FROM programme_trades
             WHERE userid = %s AND programmeid = %s
               AND investor_id = %s AND investor_sub_account_id = %s
               AND tradeid = %s
             LIMIT 1
            """,
            [investor_id, programme_id, investor_id, sub_account_id, tradeid],
            timeout=10.0, quiet=True,
        )
        if existing:
            return False
        tf = timeframe or 'M1'
        ok, _, _ = db_execute(
            """
            INSERT INTO programme_trades
                (userid, programmeid, investor_id, investor_sub_account_id,
                 tradeid, symbol, ordertype, orderstatus, timeframe,
                 entry, stoploss, takeprofit, trade_risk_reward, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s,
                    %s, %s, %s, %s, %s)
            """,
            [investor_id, programme_id, investor_id, sub_account_id,
             tradeid, symbol, ordertype, tf,
             entry, stoploss, takeprofit, trade_risk_reward,
             round(float(volume), 8)],
            timeout=15.0, quiet=True,
        )
        return ok

    # ==================================================================
    # SECTION 3 — MT5 READERS (investor-specific)
    # ==================================================================
    def get_effective_current_balance():
        acc = mt5_account_info()
        if acc is None:
            return None
        try:
            return float(acc.balance)
        except Exception:
            return None

    def get_open_positions_total_risk():
        positions = mt5_positions_get()
        if not positions:
            return 0.0, []
        total_risk = 0.0
        details = []
        skipped_no_sl = 0
        skipped_breakeven = 0
        for pos in positions:
            sym = pos.symbol
            info = mt5_symbol_info(sym)
            if not info:
                continue
            if pos.sl is None or pos.sl == 0:
                skipped_no_sl += 1
                continue
            if pos.type == 0:
                price_diff = pos.price_open - pos.sl
                direction = 'BUY'
            else:
                price_diff = pos.sl - pos.price_open
                direction = 'SELL'
            if price_diff <= 0:
                skipped_breakeven += 1
                print(f"  │ ⏭️ {sym} {direction}: SL at/beyond breakeven "
                      f"(entry={pos.price_open:.5f}, SL={pos.sl:.5f}) → NO RISK")
                continue
            contract_size = float(getattr(info, 'trade_contract_size', 1.0))
            risk = price_diff * pos.volume * contract_size
            total_risk += risk
            details.append({
                'ticket': pos.ticket, 'symbol': sym, 'volume': pos.volume,
                'entry': pos.price_open, 'sl': pos.sl, 'type': direction,
                'risk': risk,
            })
        if skipped_no_sl:
            print(f"  │ ℹ️ Skipped {skipped_no_sl} position(s) with no stop loss")
        if skipped_breakeven:
            print(f"  │ ℹ️ Skipped {skipped_breakeven} position(s) at breakeven/profit-locked")
        return total_risk, details

    def mt5_pending_orders_for_symbols(symbols):
        out = []
        for sym in symbols:
            orders = mt5_orders_get(symbol=sym) or []
            out.extend(orders)
        return out

    # ==================================================================
    # SECTION 4 — MARGIN / LEVERAGE
    # ==================================================================
    def _get_account_margin_state():
        acc = mt5_account_info()
        if acc is None:
            return None
        return {
            "balance": float(acc.balance),
            "equity": float(acc.equity),
            "margin": float(acc.margin),
            "free_margin": float(acc.margin_free),
            "margin_level": float(acc.margin_level) if acc.margin_level else None,
            "leverage": int(acc.leverage),
            "currency": acc.currency,
        }

    def _calc_order_margin(order_type_str, symbol, volume, price):
        try:
            ot = order_type_str.strip().lower()
            if ot.startswith("buy"):
                mt5_type = 0
            elif ot.startswith("sell"):
                mt5_type = 1
            else:
                mt5_type = 0 if 'buy' in ot else 1
            margin = mt5_order_calc_margin(mt5_type, symbol, float(volume), float(price))
            if margin is None or margin <= 0:
                return None
            return float(margin)
        except Exception:
            return None

    def _shrink_volume_to_fit_margin(order, side, symbol_info, desired_volume,
                                     max_margin_allowed, price):
        if desired_volume is None or desired_volume <= 0:
            return 0.0, 0.0, False
        min_vol = symbol_info.volume_min if symbol_info else 0.01
        step = symbol_info.volume_step if symbol_info and symbol_info.volume_step > 0 else 0.01
        margin = _calc_order_margin(side, order.get("symbol"), desired_volume, price)
        if margin is None:
            return desired_volume, 0.0, False
        if margin <= max_margin_allowed:
            return desired_volume, margin, False
        low = min_vol
        high = desired_volume
        best_vol = 0.0
        best_margin = 0.0
        low_margin = _calc_order_margin(side, order.get("symbol"), low, price)
        if low_margin is None or low_margin > max_margin_allowed:
            return 0.0, 0.0, True
        best_vol = low
        best_margin = low_margin
        for _ in range(40):
            mid = (low + high) / 2.0
            steps = round(mid / step) if step > 0 else 0
            mid = max(min_vol, round(steps * step, 2))
            if mid <= best_vol:
                break
            m = _calc_order_margin(side, order.get("symbol"), mid, price)
            if m is None:
                high = mid
                continue
            if m <= max_margin_allowed:
                best_vol = mid
                best_margin = m
                low = mid
            else:
                high = mid
        steps = round(best_vol / step) if step > 0 else 0
        best_vol = max(min_vol, round(steps * step, 2))
        best_margin = _calc_order_margin(side, order.get("symbol"), best_vol, price) or 0.0
        return best_vol, best_margin, True

    def _validate_single_order_margin(order, side, desired_volume, buffer_pct=10.0):
        acc_state = _get_account_margin_state()
        if acc_state is None:
            return desired_volume, 0.0, 0.0, True, False, "no_account_info"
        symbol = order.get("symbol")
        entry = order.get("entry")
        if not symbol or entry is None:
            return desired_volume, 0.0, 0.0, False, False, "missing_data"
        symbol_info = mt5_symbol_info(symbol)
        if not symbol_info:
            return desired_volume, 0.0, 0.0, False, False, "no_symbol_info"
        free_margin = acc_state["free_margin"]
        allowed_margin = free_margin * (1.0 - buffer_pct / 100.0)
        if allowed_margin <= 0:
            return 0.0, 0.0, free_margin, False, True, "no_free_margin"
        margin = _calc_order_margin(side, symbol, desired_volume, entry)
        if margin is None:
            return desired_volume, 0.0, free_margin, False, False, "margin_calc_failed"
        if margin <= allowed_margin:
            return desired_volume, margin, free_margin, True, False, "fits"
        final_vol, final_margin, shrunk = _shrink_volume_to_fit_margin(
            order, side, symbol_info, desired_volume, allowed_margin, entry
        )
        if final_vol <= 0:
            return 0.0, 0.0, free_margin, False, True, "cannot_fit_min_volume"
        return final_vol, final_margin, free_margin, True, True, "shrunk_to_fit"

    # ==================================================================
    # SECTION 5 — SEQUENCE / RISK MATHS
    # ==================================================================
    def parse_percent(value):
        if value is None:
            return 0.0
        s = str(value).strip().replace('%', '')
        try:
            return float(s)
        except (TypeError, ValueError):
            return 0.0

    def resolve_default_risk_from_rows(rows, balance, fallback):
        if not rows:
            return float(fallback), 'fallback_default_minimum_risk'
        best = None
        for r in rows:
            try:
                lo = float(_coerce_float(_raw_first_key(r, 'from_balance_range'), default=0.0) or 0.0)
                hi = float(_coerce_float(_raw_first_key(r, 'to_balance_range'), default=0.0) or 0.0)
                amt = float(_coerce_float(_raw_first_key(r, 'risk_amount'), default=0.0) or 0.0)
            except Exception:
                continue
            if lo <= balance <= hi:
                return amt, f"range:{lo}-{hi}"
            if best is None:
                best = (lo, hi, amt)
        if best:
            return best[2], 'fallback_nearest'
        return float(fallback), 'fallback_default_minimum_risk'

    def resolve_rr_from_cfg(rr_cfg):
        am = rr_cfg or {}
        fixed = _coerce_float(_raw_first_key(am, 'fixed_risk_reward'), default=None)
        minimum = _coerce_float(_raw_first_key(am, 'minimum_risk_reward'), default=None)
        if fixed is not None and fixed > 0:
            if minimum is None or fixed >= minimum:
                return 1.0, float(fixed), f"fixed_risk_reward = 1:{fixed}"
        if minimum is not None and minimum > 0:
            return 1.0, float(minimum), f"minimum_risk_reward = 1:{minimum}"
        return None, None, None

    def build_target_sum_sequence(target_balance, target_owed, reward_ratio,
                                  max_count_hint=None):
        if target_balance <= 0 or target_owed <= 0:
            return [], {'count': 0, 'within_chances': 0, 'excess_count': 0,
                        'excess_sequence': [], 'natural_sum': 0.0,
                        'capped': False, 'target_owed': target_owed,
                        'target_balance': target_balance}
        reward_ratio = max(1e-9, float(reward_ratio))
        sequence = []
        S = 0.0
        safety_limit = 10000
        while S < target_balance and len(sequence) < safety_limit:
            r = round((S + target_owed) / reward_ratio, 2)
            if r <= 0:
                r = 0.01
            if S + r >= target_balance:
                remainder = round(target_balance - S, 2)
                if remainder > 0:
                    sequence.append(remainder)
                    S += remainder
                break
            sequence.append(r)
            S += r
        sequence = [round(v, 2) for v in sequence]
        residual_cents = int(round((target_balance - sum(sequence)) * 100))
        if residual_cents != 0 and sequence:
            sequence[-1] = round(sequence[-1] + residual_cents * 0.01, 2)
            if sequence[-1] <= 0:
                sequence[-1] = 0.01
        natural_sum = round(sum(sequence), 2)
        max_count_hint = max_count_hint if max_count_hint and max_count_hint > 0 else len(sequence)
        within = min(len(sequence), max_count_hint)
        excess_sequence = sequence[max_count_hint:] if len(sequence) > max_count_hint else []
        return sequence, {
            'count': len(sequence),
            'within_chances': within,
            'excess_count': len(excess_sequence),
            'excess_sequence': excess_sequence,
            'natural_sum': natural_sum,
            'capped': natural_sum >= target_balance - 0.01,
            'target_owed': target_owed,
            'target_balance': target_balance,
        }

    def stage_max_risk_for_balance(config_rows, balance):
        if not config_rows:
            return 100.0
        for r in config_rows:
            lo = _coerce_float(_raw_first_key(r, 'from_balance'), default=None)
            hi = _coerce_float(_raw_first_key(r, 'to_balance'), default=None)
            amt = _coerce_float(_raw_first_key(r, 'martingale_per_stage_drawdown_amount'),
                                default=None)
            if lo is None or amt is None:
                continue
            if hi is None:
                if balance >= lo:
                    return float(amt)
                continue
            if lo <= balance <= hi:
                return float(amt)
        last_amt = _coerce_float(
            _raw_first_key(config_rows[-1], 'martingale_per_stage_drawdown_amount'),
            default=100.0,
        )
        return float(last_amt or 100.0)

    # ==================================================================
    # SECTION 6 — SIZE HELPERS
    # ==================================================================
    def _risk_per_lot(order, symbol_info):
        entry = _coerce_float(order.get('entry'), default=None)
        stop  = _coerce_float(order.get('stoploss'), default=None)
        if entry is None or stop is None:
            return 0.0
        sl_distance = abs(entry - stop)
        contract_size = float(getattr(symbol_info, 'trade_contract_size', 1.0))
        return sl_distance * contract_size

    def _size_volume_from_risk_target(order, symbol_info, target_risk_dollars):
        risk_per_lot = _risk_per_lot(order, symbol_info)
        if risk_per_lot <= 0:
            return 0.0, 0.0, 0.0
        vol = target_risk_dollars / risk_per_lot
        step = float(getattr(symbol_info, 'volume_step', 0.01)) or 0.01
        min_vol = float(getattr(symbol_info, 'volume_min', 0.01)) or 0.01
        steps = round(vol / step) if step > 0 else 0
        vol = max(min_vol, round(steps * step, 2))
        actual_risk = vol * risk_per_lot
        return vol, actual_risk, risk_per_lot

    def _size_volume_from_tp_target(order, symbol_info, target_reward_dollars, programme_rr):
        """
        profit_factor: size so that volume × SL_distance × contract × rr
        equals the target reward. Equivalent to:
            required_risk   = target_reward / rr
            required_volume = required_risk / risk_per_lot
        Returns (volume, reward_if_tp, risk_if_sl).
        """
        if programme_rr is None or programme_rr <= 0:
            return 0.0, 0.0, 0.0
        risk_per_lot = _risk_per_lot(order, symbol_info)
        if risk_per_lot <= 0:
            return 0.0, 0.0, 0.0

        required_risk = target_reward_dollars / float(programme_rr)
        vol = required_risk / risk_per_lot

        step = float(getattr(symbol_info, 'volume_step', 0.01)) or 0.01
        min_vol = float(getattr(symbol_info, 'volume_min', 0.01)) or 0.01
        steps = round(vol / step) if step > 0 else 0
        vol = max(min_vol, round(steps * step, 2))

        risk_if_sl = vol * risk_per_lot
        reward_if_tp = risk_if_sl * float(programme_rr)
        return vol, reward_if_tp, risk_if_sl

    def _reward_per_lot_from_programme_rr(order, symbol_info, programme_rr):
        if programme_rr is None or programme_rr <= 0:
            return 0.0
        risk_per_lot = _risk_per_lot(order, symbol_info)
        if risk_per_lot <= 0:
            return 0.0
        return risk_per_lot * float(programme_rr)

    def get_direction_from_order(order):
        ot = (order.get('ordertype') or '').lower()
        if 'sell-limit' in ot or 'buy-stop' in ot:
            return "STEPUP"
        if 'buy-limit' in ot or 'sell-stop' in ot:
            return "STEPDOWN"
        return "UNKNOWN"

    def group_rows_by_linear(rows):
        stepup_linear = []
        stepdown_linear = []
        for idx, order in enumerate(rows):
            ot = (order.get('ordertype') or '').lower()
            entry = order.get('entry')
            if entry is None:
                continue
            info = {'order': order, 'index': idx}
            if 'sell-limit' in ot or 'buy-stop' in ot:
                stepup_linear.append(info)
            elif 'buy-limit' in ot or 'sell-stop' in ot:
                stepdown_linear.append(info)
        stepup_linear.sort(key=lambda x: _coerce_float(x['order'].get('entry'), default=0) or 0)
        stepdown_linear.sort(key=lambda x: _coerce_float(x['order'].get('entry'), default=0) or 0, reverse=True)
        return stepup_linear, stepdown_linear

    # ==================================================================
    # SECTION 7 — PER-INVESTOR PIPELINE
    # ==================================================================
    def process_investor(investor_id, sub_account_id, programme_id,
                         programme_name, programme_cfg):
        detail = {
            'investor_id': investor_id,
            'sub_account_id': sub_account_id,
            'programme_id': programme_id,
            'programme_name': programme_name,
            'mt5_balance': None,
            'execution_start_balance': None,
            'daily_target_owed': 0.0,
            'daily_target_owed_day_balance': 0.0,
            'daily_target_owed_date': None,
            'drawdown': 0.0,
            'stage': 0,
            'stage_drawdown': 0.0,
            'sequence_next_risk': 0.0,
            'final_target_risk': 0.0,
            'per_symbol_target': 0.0,
            'programme_rr': None,
            'rows_seen': 0,
            'rows_updated': 0,
            'rows_deleted': 0,
            'rows_restored': 0,
            'mt5_cancelled': 0,
            'mode': None,
            'factor': None,
            'error': None,
        }

        enable_martingale = programme_cfg['enable_martingale']
        martingale_type = programme_cfg['martingale_type']
        martingale_factor = programme_cfg['martingale_factor']
        recovery_adder_pct = programme_cfg['recovery_adder_pct']
        pre_drawdown_assumption = programme_cfg['pre_drawdown_assumption']
        martingale_pre_scaling = programme_cfg['martingale_pre_scaling']
        linear_scaling = programme_cfg['linear_scaling']
        enable_retention = programme_cfg['enable_retention']
        retention_pct = programme_cfg['retention_pct']
        config_rows = programme_cfg['config_rows']
        default_risk_rows = programme_cfg['default_risk_rows']
        rr_cfg = programme_cfg['rr_cfg']
        loss_streak_chances = programme_cfg['loss_streak_chances']
        programme_rr = programme_cfg.get('programme_rr')

        detail['mode'] = martingale_type
        detail['factor'] = martingale_factor
        detail['programme_rr'] = programme_rr

        if not enable_martingale:
            print(f"\n  ⏭️ Investor {investor_id} | programme '{programme_name}' "
                  f"(id={programme_id}) — martingale DISABLED")
            detail['error'] = 'martingale_disabled'
            return detail

        if martingale_factor == 'profit_factor' and (programme_rr is None or programme_rr <= 0):
            print(f"\n  ⚠️ Investor {investor_id} | programme '{programme_name}' "
                  f"(id={programme_id}) — profit_factor set but no "
                  f"signals_provider_interest.risk_reward available; skipping")
            detail['error'] = 'programme_rr_missing'
            return detail

        print(f"\n{'─'*72}")
        print(f" 🎰 Investor {investor_id} (sub {sub_account_id}) | "
              f"programme '{programme_name}' (id={programme_id})")
        print(f"{'─'*72}")
        print(f"  PROGRAMME CONFIGURATION (id={programme_id}):")
        print(f"  │ Mode              : {martingale_type}")
        print(f"  │ Factor            : {martingale_factor}")
        if martingale_factor == 'profit_factor':
            print(f"  │ Programme R:R     : 1:{programme_rr}  "
                  f"(risk → reward multiplier; the target is a reward)")
        print(f"  │ Pre-drawdown      : {'ON' if pre_drawdown_assumption else 'OFF'}")
        print(f"  │ Pre-scaling       : {'ON' if martingale_pre_scaling else 'OFF'}")
        print(f"  │ Linear scaling    : {'ON' if linear_scaling else 'OFF'}")
        print(f"  │ Retention         : {'ON' if enable_retention else 'OFF'} ({retention_pct}%)")
        print(f"  │ Recovery adder    : {recovery_adder_pct}%")
        print(f"  │ Loss streak chance: {loss_streak_chances}")
        print(f"  INVESTOR STATE (sub {sub_account_id}):")

        effective_balance = get_effective_current_balance()
        if effective_balance is None:
            detail['error'] = 'mt5_balance_unavailable'
            print(f"  ✗ Failed to get MT5 balance")
            return detail
        current_balance = effective_balance
        detail['mt5_balance'] = current_balance
        print(f"  │ Current MT5 balance: ${current_balance:.2f}")

        hub = investor_fetch_harvhub_anchor(investor_id, sub_account_id) or {}
        broker_balance = _coerce_float(_raw_first_key(hub, 'broker_balance'), default=None)
        if broker_balance is None:
            detail['error'] = 'broker_balance_missing'
            print(f"  ⚠️ harvhub.broker_balance is NULL — skipping investor")
            return detail
        detail['execution_start_balance'] = broker_balance
        print(f"  │ Execution-start balance: ${broker_balance:.2f}")

        dtr = investor_fetch_daily_target(investor_id, sub_account_id) or {}
        daily_target_owed = _coerce_float(_raw_first_key(dtr, 'daily_target_owed'), default=0.0) or 0.0
        owed_day_balance = _coerce_float(
            _raw_first_key(dtr, 'daily_target_owed_day_balance'), default=None)
        if owed_day_balance is None:
            owed_day_balance = daily_target_owed
        owed_date = _raw_first_key(dtr, 'daily_target_owed_date')
        detail['daily_target_owed'] = daily_target_owed
        detail['daily_target_owed_day_balance'] = owed_day_balance
        detail['daily_target_owed_date'] = owed_date
        print(f"  │ Daily target owed : ${daily_target_owed:.2f} "
              f"(day balance ${owed_day_balance:.2f}, date {owed_date or '—'})")

        default_minimum_risk = 2.0
        default_risk_value, default_risk_src = resolve_default_risk_from_rows(
            default_risk_rows, current_balance, default_minimum_risk)
        print(f"  │ Default risk floor: ${default_risk_value:.2f} ({default_risk_src})")

        base_drawdown = max(0.0, float(broker_balance) - float(current_balance))
        total_drawdown = base_drawdown + daily_target_owed
        if pre_drawdown_assumption:
            print(f"\n  🔄 PRE-DRAWDOWN ASSUMPTION ENABLED:")
            positions_risk, positions_details = get_open_positions_total_risk()
            if positions_risk > 0:
                print(f"  │ Found {len(positions_details)} open position(s) with stop losses:")
                for pos in positions_details:
                    print(f"  │   ├─ {pos['symbol']} {pos['type']}: ${pos['risk']:.2f} risk")
                print(f"  │ Total open positions risk: ${positions_risk:.2f}")
                print(f"  │ ${total_drawdown:.2f} + ${positions_risk:.2f} = "
                      f"${total_drawdown + positions_risk:.2f}")
                total_drawdown += positions_risk
            else:
                print(f"  │ No open positions with stop losses found")
        else:
            print(f"  │ Pre-drawdown assumption DISABLED")
        detail['drawdown'] = total_drawdown
        print(f"  │ Base drawdown    : ${base_drawdown:.2f}")
        print(f"  │ Total drawdown   : ${total_drawdown:.2f}")

        stage_max_risk = stage_max_risk_for_balance(config_rows, current_balance)
        print(f"  │ Stage max risk (per round): ${stage_max_risk:.2f}")
        if total_drawdown > 0 and stage_max_risk > 0:
            current_stage = int(total_drawdown // stage_max_risk) + 1
            current_stage_drawdown = total_drawdown % stage_max_risk
            if current_stage_drawdown == 0 and current_stage > 1:
                current_stage_drawdown = default_risk_value
                print(f"  │ EXACT STAGE COMPLETION - using floor risk: ${default_risk_value:.2f}")
            print(f"  │ Current stage: {current_stage}")
            print(f"  │ Stage drawdown: ${current_stage_drawdown:.2f}")
            print(f"  │ Total drawdown across all stages: ${total_drawdown:.2f}")
        else:
            current_stage = 1
            current_stage_drawdown = 0.0
            print(f"  │ No drawdown to recover")
        detail['stage'] = current_stage
        detail['stage_drawdown'] = current_stage_drawdown

        sequence_risk = None

        if martingale_type == 'loss_streak':
            print(f"\n  📊 LOSS_STREAK TARGET CALCULATION")
            if daily_target_owed <= 0:
                print(f"  │ No daily_target_owed — falling back to default risk floor")
                sequence_risk = default_risk_value
            else:
                risk_ratio, reward_ratio, rr_src = resolve_rr_from_cfg(rr_cfg)
                if risk_ratio is None or reward_ratio is None:
                    print(f"  │ ⚠️ R:R unavailable — falling back to default risk")
                    sequence_risk = default_risk_value
                else:
                    target_balance = owed_day_balance if owed_day_balance > 0 else daily_target_owed
                    target_owed = daily_target_owed

                    sequence, meta = build_target_sum_sequence(
                        target_balance=target_balance,
                        target_owed=target_owed,
                        reward_ratio=reward_ratio,
                        max_count_hint=loss_streak_chances or None,
                    )
                    if not sequence:
                        print(f"  │ ⚠️ Empty sequence — falling back to default risk")
                        sequence_risk = default_risk_value
                    else:
                        rr_display = reward_ratio / risk_ratio if risk_ratio > 0 else reward_ratio
                        print(f"\n{'='*60}")
                        print(f"  🎰 LOSS STREAK PURE SEQUENCE")
                        print(f"{'='*60}")
                        print(f"  │ Daily target owed   : ${target_owed:.2f}")
                        print(f"  │ Daily target balance: ${target_balance:.2f}")
                        print(f"  │ Loss streak chances : {loss_streak_chances}")
                        print(f"  │ R:R                 : 1:{rr_display:.0f} ({rr_src})")
                        print(f"  │ Total risks needed  : {meta['count']}")
                        print(f"  │ Total (sum)         : ${round(sum(sequence), 2):.2f}")
                        print(f"  {'─'*58}")
                        chunk_size = 5
                        print(f"  📋 Risks sequence:")
                        for i in range(0, len(sequence), chunk_size):
                            chunk = sequence[i:i + chunk_size]
                            print("     " + ", ".join(f"${v:.2f}" for v in chunk))
                        if meta["excess_count"] > 0:
                            print(f"  {'─'*58}")
                            print(f"  📈 EXCESS sequence ({meta['excess_count']} risk(s)):")
                            for i in range(0, len(meta["excess_sequence"]), chunk_size):
                                chunk = meta["excess_sequence"][i:i + chunk_size]
                                print("     " + ", ".join(f"${v:.2f}" for v in chunk))
                        print(f"  {'─'*58}")

                        base_drawdown_loss = max(0.0, round(total_drawdown - daily_target_owed, 2))
                        cumulative = 0.0
                        loss_prefix = []
                        approx_position = 0
                        for i, r in enumerate(sequence):
                            cumulative = round(cumulative + r, 2)
                            loss_prefix.append(r)
                            approx_position = i + 1
                            if cumulative + 1e-9 >= base_drawdown_loss:
                                break
                        if base_drawdown_loss <= 0:
                            loss_prefix = []
                            approx_position = 0
                            cumulative = 0.0

                        next_index = approx_position
                        if next_index >= len(sequence):
                            next_index = len(sequence) - 1

                        positions_exist = bool(mt5_positions_get())
                        advanced = False
                        if positions_exist and pre_drawdown_assumption:
                            next_index = min(next_index + 1, len(sequence) - 1)
                            advanced = True

                        sequence_risk = float(sequence[next_index])
                        remaining_chances = max(0, len(sequence) - (next_index + 1))

                        print(f"\n  🎯 DRAWDOWN / NEXT RISK ANALYSIS")
                        print(f"  │ Base loss to recover   : ${base_drawdown_loss:.2f}")
                        print(f"  │ Approx current drawdown: ${cumulative:.2f} "
                              f"(≈ position {approx_position}, ceil-fit)")
                        print(f"  │ Position exists        : {'YES' if positions_exist else 'NO'}")
                        print(f"  │ Pre-drawdown assumption: {'ON' if pre_drawdown_assumption else 'OFF'}")
                        if advanced:
                            print(f"  │ → advanced 1 step")
                        print(f"  │ NEXT RISK to use       : ${sequence_risk:.2f}")
                        print(f"  │   ├─ Position in sequence: #{next_index + 1} of {len(sequence)}")
                        print(f"  │   ├─ Recovers previous  : ${cumulative:.2f}")
                        print(f"  │   ├─ Plus daily target  : ${target_owed:.2f}")
                        print(f"  │   └─ Total win target   : ${round(cumulative + target_owed, 2):.2f}")
                        print(f"  │ Remaining Chances       : {remaining_chances}")
                        print(f"{'='*60}\n")

        else:  # balance_based
            print(f"\n  📊 BALANCE-BASED TARGET CALCULATION")
            base_target_risk = total_drawdown
            if base_target_risk == 0:
                print(f"  │ No drawdown — using default risk from config")
                base_target_risk = default_risk_value
            sequence_risk = base_target_risk
            print(f"  │ Base target risk: ${base_target_risk:.2f}")

        detail['sequence_next_risk'] = float(sequence_risk or 0.0)

        pending_rows = investor_fetch_pending_trades(
            investor_id, sub_account_id, programme_id)
        detail['rows_seen'] = len(pending_rows)
        print(f"\n  📋 Pending trades for this investor: {len(pending_rows)}")
        if not pending_rows:
            print(f"  │ ℹ️ Nothing to modify")
            return detail

        symbol_info_cache = {}
        def get_symbol_info(sym):
            si = symbol_info_cache.get(sym)
            if si is None:
                si = mt5_symbol_info(sym)
                if si is None:
                    mt5_symbol_select(sym, True)
                    si = mt5_symbol_info(sym)
                symbol_info_cache[sym] = si
            return si

        rows_updated_vol = 0
        rows_deleted = 0

        # ------------------------------------------------------------------
        # STEP 1: recovery / reset (sequence-driven)
        # ------------------------------------------------------------------
        if current_stage_drawdown > 0 or martingale_type == 'loss_streak':
            print(f"\n  📝 STEP 1: Recovery Processing (SEQUENCE-DRIVEN)")
        else:
            print(f"\n  📝 STEP 1: Reset to SEQUENCE RISK")

        print(f"  {'─'*40}")
        print(f"  │ SEQUENCE NEXT RISK : ${sequence_risk:.2f}")

        # --- remove invalid price levels ---
        print(f"\n  🗑️ STEP: Removing Invalid Price Levels")
        print(f"  {'─'*60}")
        total_removed = 0
        for row in pending_rows[:]:
            sym = (_raw_first_key(row, 'symbol') or '').strip()
            rid = _coerce_int(_raw_first_key(row, 'id'))
            if not sym:
                continue
            si = get_symbol_info(sym)
            if not si:
                continue
            entry = _coerce_float(_raw_first_key(row, 'entry'), default=None)
            ot = (_raw_first_key(row, 'ordertype') or '').lower()
            if entry is None:
                continue
            bid = getattr(si, 'bid', None)
            ask = getattr(si, 'ask', None)
            if bid is None or ask is None:
                continue
            is_valid = True
            if ot in ('buy-stop', 'sell-limit'):
                if entry <= ask:
                    is_valid = False
            elif ot in ('sell-stop', 'buy-limit'):
                if entry >= bid:
                    is_valid = False
            if not is_valid:
                if delete_trade_row(rid):
                    total_removed += 1
                    pending_rows.remove(row)
                    print(f"  │ ✗ Removed invalid row {rid} ({sym} {ot} entry={entry})")
        if total_removed:
            print(f"  │ Removed {total_removed} invalid row(s)")

        # --- apply sequence risk ---
        for row in pending_rows:
            rid = _coerce_int(_raw_first_key(row, 'id'))
            tradeid = _coerce_int(_raw_first_key(row, 'tradeid'))
            sym = (_raw_first_key(row, 'symbol') or '').strip()
            ot = (_raw_first_key(row, 'ordertype') or '').lower()
            entry = _coerce_float(_raw_first_key(row, 'entry'), default=None)
            stoploss = _coerce_float(_raw_first_key(row, 'stoploss'), default=None)

            if not sym or entry is None:
                print(f"  │ ⚠️ row {rid}: missing symbol/entry — skipped")
                continue
            si = get_symbol_info(sym)
            if si is None:
                print(f"  │ ⚠️ row {rid}: no symbol_info for {sym} — skipped")
                continue

            if martingale_factor == 'profit_factor':
                new_vol, reward_if_tp, risk_if_sl = _size_volume_from_tp_target(
                    row, si, sequence_risk, programme_rr)
                if new_vol > 0:
                    print(f"  │ 🧮 row {rid}: recover ${sequence_risk:.2f} at 1:{programme_rr} "
                          f"→ {new_vol:.2f} lots | risk ${risk_if_sl:.2f} → "
                          f"reward ${reward_if_tp:.2f}")
            else:
                if stoploss is None:
                    print(f"  │ ⚠️ row {rid}: no stoploss — skipped")
                    continue
                new_vol, risk_if_sl, _per_lot = _size_volume_from_risk_target(
                    row, si, sequence_risk)
                reward_if_tp = 0.0

            if new_vol <= 0:
                print(f"  │ ⚠️ row {rid}: could not size volume — skipped")
                continue

            order_for_margin = {"symbol": sym, "entry": entry, "ordertype": ot}
            side = "buy" if 'buy' in ot else "sell"
            valid_vol, margin, free_margin, ok, shrunk, reason = \
                _validate_single_order_margin(order_for_margin, side, new_vol, buffer_pct=10.0)
            if not ok or valid_vol <= 0:
                print(f"  │ ⚠️ row {rid}: LEVERAGE CHECK failed "
                      f"(free ${free_margin:.2f}, reason: {reason})")
                continue
            if shrunk:
                print(f"  │ 🔻 row {rid}: LEVERAGE shrunk {new_vol:.2f} → {valid_vol:.2f}")
                new_vol = valid_vol
                risk_per_lot = _risk_per_lot(row, si)
                risk_if_sl = new_vol * risk_per_lot
                reward_if_tp = risk_if_sl * float(programme_rr) if martingale_factor == 'profit_factor' else 0.0

            if update_trade_volume(rid, new_vol):
                rows_updated_vol += 1
                if martingale_factor == 'profit_factor':
                    print(f"  │ ✓ row {rid} ({sym} {ot} tradeid={tradeid}) "
                          f"→ {new_vol:.2f} lots | risk ${risk_if_sl:.2f} → "
                          f"reward ${reward_if_tp:.2f}")
                else:
                    print(f"  │ ✓ row {rid} ({sym} {ot} tradeid={tradeid}) "
                          f"→ {new_vol:.2f} lots | risk ${risk_if_sl:.2f}")
            else:
                print(f"  │ ✗ row {rid}: volume update failed")

        # ------------------------------------------------------------------
        # STEP 2: pre-scaling
        # ------------------------------------------------------------------
        if martingale_pre_scaling:
            print(f"\n{'='*60}")
            print(f"  🎯 PRE-SCALING ANALYSIS")
            print(f"{'='*60}")
            print(f"  │ Mode: {martingale_type.upper()}")
            print(f"  │ Assumption: {martingale_factor.upper()}")
            if martingale_factor == 'profit_factor':
                print(f"  │ Programme R:R: 1:{programme_rr} "
                      f"(risk → reward multiplier)")
            print(f"  │ Linear scaling: {'✓ ENABLED' if linear_scaling else '✗ DISABLED'}")
            print(f"  │ Initial risk adder: {'✓ ENABLED' if enable_retention else '✗ DISABLED'}")
            print(f"  │   - retention: {retention_pct}%")
            print(f"  │ Pre-drawdown assumption: {'✓ ENABLED' if pre_drawdown_assumption else '✗ DISABLED'}")
            print(f"  │ Stage max risk: ${stage_max_risk:.2f}")
            print(f"  │ Recovery adder: {recovery_adder_pct}%")
            print(f"  │ Total drawdown: ${total_drawdown:.2f}")
            print(f"{'─'*60}")

            base_target_risk = total_drawdown if total_drawdown > 0 else default_risk_value

            print(f"\n{'='*60}")
            print(f"  📊 CALCULATING FINAL TARGET RISK")
            print(f"{'='*60}")
            print(f"  │ Base target risk: ${base_target_risk:.2f}")

            final_target_risk = base_target_risk

            if enable_retention:
                print(f"\n  │ Initial-risk retention ON — computing contribution")
                default_risk_val_for_bal, _ = resolve_default_risk_from_rows(
                    default_risk_rows, current_balance, default_minimum_risk)
                kept = default_risk_val_for_bal * (retention_pct / 100.0)
                print(f"  │   ├─ Default risk for balance: ${default_risk_val_for_bal:.2f}")
                print(f"  │   ├─ Keeping {retention_pct}%: ${kept:.2f}")
                print(f"  │   └─ Added to target: +${kept:.2f}")
                final_target_risk += kept

            if recovery_adder_pct > 0:
                applied = final_target_risk * (recovery_adder_pct / 100.0)
                print(f"\n  │ Recovery adder ({recovery_adder_pct}%): +${applied:.2f}")
                final_target_risk += applied

            detail['final_target_risk'] = final_target_risk
            print(f"\n  │ ✅ FINAL TARGET RISK: ${final_target_risk:.2f}")
            print(f"{'='*60}")

            symbols_in_rows = set()
            for row in pending_rows:
                sym = (_raw_first_key(row, 'symbol') or '').strip()
                if sym:
                    symbols_in_rows.add(sym)
            num_symbols = max(1, len(symbols_in_rows))
            per_symbol_target = final_target_risk / num_symbols
            detail['per_symbol_target'] = per_symbol_target
            print(f"\n  📊 SYMBOL-INDEPENDENT PRE-SCALING TARGETS:")
            print(f"  │ Total symbols: {num_symbols}")
            print(f"  │ Symbols: {', '.join(sorted(symbols_in_rows))}")
            print(f"  │ Target per symbol: ${per_symbol_target:.2f}")

            print(f"\n  📈 STEP: Scaling Limit Orders")
            print(f"  {'─'*60}")

            for sym in sorted(symbols_in_rows):
                si = get_symbol_info(sym)
                if not si:
                    continue
                symbol_rows = [r for r in pending_rows
                               if (_raw_first_key(r, 'symbol') or '').strip() == sym]
                if not symbol_rows:
                    continue

                print(f"\n  🔹 [NON-GRID] Scaling {sym} orders "
                      f"(independent target: ${per_symbol_target:.2f}):")

                if martingale_factor == 'profit_factor':
                    print(f"     Target ${per_symbol_target:.2f} is the reward to earn at 1:{programme_rr}")
                    for row in symbol_rows:
                        rid = _coerce_int(_raw_first_key(row, 'id'))
                        entry = _coerce_float(_raw_first_key(row, 'entry'), default=None)
                        sl = _coerce_float(_raw_first_key(row, 'stoploss'), default=None)
                        if entry is None or sl is None:
                            continue
                        risk_per_lot = _risk_per_lot(row, si)
                        if risk_per_lot <= 0:
                            print(f"        ⚠️ row {rid}: invalid entry/SL — skipped")
                            continue
                        required_risk = per_symbol_target / float(programme_rr)
                        required_vol = required_risk / risk_per_lot
                        step = float(getattr(si, 'volume_step', 0.01)) or 0.01
                        min_vol = float(getattr(si, 'volume_min', 0.01)) or 0.01
                        steps = round(required_vol / step)
                        required_vol = max(min_vol, round(steps * step, 2))
                        risk_if_sl = required_vol * risk_per_lot
                        reward_if_tp = risk_if_sl * float(programme_rr)

                        order_for_margin = {
                            "symbol": sym, "entry": entry,
                            "ordertype": (_raw_first_key(row, 'ordertype') or '').lower(),
                        }
                        side = "buy" if 'buy' in order_for_margin["ordertype"] else "sell"
                        valid_vol, margin, free_margin, ok, shrunk, reason = \
                            _validate_single_order_margin(order_for_margin, side,
                                                          required_vol, buffer_pct=10.0)
                        if not ok or valid_vol <= 0:
                            print(f"        ⚠️ row {rid}: LEVERAGE failed "
                                  f"(free ${free_margin:.2f}, {reason})")
                            continue
                        if shrunk:
                            print(f"        🔻 row {rid}: LEVERAGE shrink "
                                  f"{required_vol:.2f} → {valid_vol:.2f}")
                            required_vol = valid_vol
                            risk_if_sl = required_vol * risk_per_lot
                            reward_if_tp = risk_if_sl * float(programme_rr)
                        if update_trade_volume(rid, required_vol):
                            rows_updated_vol += 1
                            print(f"        ✅ row {rid} [{sym}]: {required_vol:.2f} lots | "
                                  f"risk ${risk_if_sl:.2f} → reward ${reward_if_tp:.2f} "
                                  f"(target ${per_symbol_target:.2f})")
                else:
                    print(f"     Target ${per_symbol_target:.2f} is the risk")
                    for row in symbol_rows:
                        rid = _coerce_int(_raw_first_key(row, 'id'))
                        entry = _coerce_float(_raw_first_key(row, 'entry'), default=None)
                        sl = _coerce_float(_raw_first_key(row, 'stoploss'), default=None)
                        if entry is None or sl is None:
                            continue
                        risk_per_lot = _risk_per_lot(row, si)
                        if risk_per_lot <= 0:
                            continue
                        required_vol = per_symbol_target / risk_per_lot
                        step = float(getattr(si, 'volume_step', 0.01)) or 0.01
                        min_vol = float(getattr(si, 'volume_min', 0.01)) or 0.01
                        steps = round(required_vol / step)
                        required_vol = max(min_vol, round(steps * step, 2))
                        risk_if_sl = required_vol * risk_per_lot

                        order_for_margin = {
                            "symbol": sym, "entry": entry,
                            "ordertype": (_raw_first_key(row, 'ordertype') or '').lower(),
                        }
                        side = "buy" if 'buy' in order_for_margin["ordertype"] else "sell"
                        valid_vol, margin, free_margin, ok, shrunk, reason = \
                            _validate_single_order_margin(order_for_margin, side,
                                                          required_vol, buffer_pct=10.0)
                        if not ok or valid_vol <= 0:
                            print(f"        ⚠️ row {rid}: LEVERAGE failed "
                                  f"(free ${free_margin:.2f}, {reason})")
                            continue
                        if shrunk:
                            print(f"        🔻 row {rid}: LEVERAGE shrink "
                                  f"{required_vol:.2f} → {valid_vol:.2f}")
                            required_vol = valid_vol
                            risk_if_sl = required_vol * risk_per_lot
                        if update_trade_volume(rid, required_vol):
                            rows_updated_vol += 1
                            print(f"        ✅ row {rid} [{sym}]: {required_vol:.2f} lots | "
                                  f"risk ${risk_if_sl:.2f}")

            if linear_scaling:
                print(f"\n{'─'*60}")
                print(f"  📈 STEP: Linear Scaling (Progressive)")
                print(f"{'─'*60}")
                print(f"  IMPORTANT: NEVER scales DOWN, only UP or keep same")

                for sym in sorted(symbols_in_rows):
                    si = get_symbol_info(sym)
                    if not si:
                        continue
                    symbol_rows = [r for r in pending_rows
                                   if (_raw_first_key(r, 'symbol') or '').strip() == sym]
                    if not symbol_rows:
                        continue

                    print(f"\n  🔹 Linear Scaling {sym} "
                          f"(independent target: ${per_symbol_target:.2f}):")

                    stepup_linear, stepdown_linear = group_rows_by_linear(symbol_rows)

                    first_row = symbol_rows[0]
                    first_vol = _coerce_float(_raw_first_key(first_row, 'volume'), default=0.01) or 0.01
                    leader_amount = 0.0
                    if martingale_factor == 'profit_factor':
                        per_lot = _reward_per_lot_from_programme_rr(first_row, si, programme_rr)
                        if per_lot > 0:
                            leader_amount = per_lot * first_vol - per_symbol_target
                            if leader_amount < 0:
                                leader_amount = per_symbol_target * 0.01
                            print(f"     LEADER reward after recovery: ${leader_amount:.2f}")
                    else:
                        per_lot = _risk_per_lot(first_row, si)
                        if per_lot > 0:
                            leader_amount = per_lot * first_vol
                            print(f"     LEADER risk: ${leader_amount:.2f}")

                    if leader_amount <= 0:
                        print(f"     No valid leader amount for {sym}")
                        continue

                    def apply_linear(linear_group, name):
                        if not linear_group:
                            return
                        print(f"\n     📊 {name.upper()} LINEAR SCALING ({len(linear_group)} orders):")
                        prev_amount = None
                        for item in linear_group:
                            row = item['order']
                            rid = _coerce_int(_raw_first_key(row, 'id'))
                            entry = _coerce_float(_raw_first_key(row, 'entry'), default=None)
                            vol = _coerce_float(_raw_first_key(row, 'volume'), default=0.01) or 0.01
                            ot = (_raw_first_key(row, 'ordertype') or '').lower()
                            if entry is None:
                                continue

                            if martingale_factor == 'profit_factor':
                                per_lot = _reward_per_lot_from_programme_rr(row, si, programme_rr)
                            else:
                                per_lot = _risk_per_lot(row, si)
                            if per_lot <= 0:
                                continue
                            amount = per_lot * vol

                            if prev_amount is None:
                                print(f"        🔹 Order #{rid} (LEADER) amount=${amount:.2f} vol={vol:.2f}")
                                prev_amount = amount
                                continue

                            if amount >= prev_amount:
                                print(f"        #{rid}: already ≥ target (${amount:.2f} vs ${prev_amount:.2f}) — keep")
                                prev_amount = amount
                                continue

                            needed_amount = prev_amount
                            needed_vol = needed_amount / per_lot
                            step = float(getattr(si, 'volume_step', 0.01)) or 0.01
                            min_vol = float(getattr(si, 'volume_min', 0.01)) or 0.01
                            steps = round(needed_vol / step)
                            needed_vol = max(min_vol, round(steps * step, 2))

                            order_for_margin = {"symbol": sym, "entry": entry,
                                                "ordertype": ot}
                            side = "buy" if 'buy' in ot else "sell"
                            valid_vol, margin, free_margin, ok, shrunk, reason = \
                                _validate_single_order_margin(order_for_margin, side,
                                                              needed_vol, buffer_pct=10.0)
                            if not ok or valid_vol <= 0:
                                print(f"        ⚠️ #{rid}: LEVERAGE failed — keep current vol")
                                prev_amount = amount
                                continue
                            if shrunk:
                                print(f"        🔻 #{rid}: LEVERAGE shrink "
                                      f"{needed_vol:.2f} → {valid_vol:.2f}")
                                needed_vol = valid_vol
                            if update_trade_volume(rid, needed_vol):
                                nonlocal_updated[0] += 1
                                print(f"        ✅ #{rid}: {vol:.2f} → {needed_vol:.2f} lots "
                                      f"(cascade to ${needed_amount:.2f})")
                                prev_amount = needed_amount
                            else:
                                prev_amount = amount

                    nonlocal_updated = [0]
                    if stepup_linear:
                        apply_linear(stepup_linear, "STEPUP")
                    if stepdown_linear:
                        apply_linear(stepdown_linear, "STEPDOWN")
                    rows_updated_vol += nonlocal_updated[0]

        # ------------------------------------------------------------------
        # STEP 3: MT5 reconciliation (cancel mismatches)
        # ------------------------------------------------------------------
        print(f"\n{'='*60}")
        print(f"  🗑️ CHECKING MT5 PENDING ORDERS")
        print(f"{'='*60}")

        pending_rows = investor_fetch_pending_trades(
            investor_id, sub_account_id, programme_id)

        system_analysis_results = {}
        for row in pending_rows:
            sym = (_raw_first_key(row, 'symbol') or '').strip()
            if not sym:
                continue
            si = get_symbol_info(sym)
            if not si:
                continue
            entry = _coerce_float(_raw_first_key(row, 'entry'), default=None)
            sl = _coerce_float(_raw_first_key(row, 'stoploss'), default=None)
            vol = _coerce_float(_raw_first_key(row, 'volume'), default=0.0) or 0.0
            if entry is None or sl is None or vol <= 0:
                continue
            per_lot_risk = abs(entry - sl) * float(getattr(si, 'trade_contract_size', 1.0))
            risk = per_lot_risk * vol
            if martingale_factor == 'profit_factor':
                reward = risk * float(programme_rr)
                system_analysis_results[sym] = {
                    'volume': vol, 'risk': risk, 'reward': reward,
                }
            else:
                system_analysis_results[sym] = {
                    'volume': vol, 'risk': risk, 'reward': 0.0,
                }

        print(f"\n  📊 System Analysis Results:")
        for sym, res in system_analysis_results.items():
            if martingale_factor == 'profit_factor':
                print(f"     {sym}: {res['volume']:.2f} lots | "
                      f"risk ${res['risk']:.2f} → reward ${res['reward']:.2f}")
            else:
                print(f"     {sym}: {res['volume']:.2f} lots | "
                      f"risk ${res['risk']:.2f}")

        cancelled = 0
        symbols_in_rows = set(system_analysis_results.keys())
        if symbols_in_rows:
            mt5_orders = mt5_pending_orders_for_symbols(list(symbols_in_rows))
            for order in mt5_orders:
                sym = order.symbol
                order_ticket = order.ticket
                volume = float(getattr(order, 'volume_current', None)
                               or getattr(order, 'volume_initial', 0) or 0)
                entry_o = float(order.price_open)
                sl_o = float(order.sl) if order.sl else None
                magic = getattr(order, 'magic', None)

                sys_res = system_analysis_results.get(sym)
                if sys_res is None:
                    print(f"  ❌ {sym} ticket#{order_ticket}: symbol not in system analysis — DELETE")
                    try:
                        req = {"action": mt5.TRADE_ACTION_REMOVE, "order": order_ticket}
                        res = mt5_order_send(req)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            cancelled += 1
                            if magic is not None and int(magic) > 0:
                                row_id = None
                                for r in pending_rows:
                                    if _coerce_int(_raw_first_key(r, 'tradeid')) == int(magic):
                                        row_id = _coerce_int(_raw_first_key(r, 'id'))
                                        break
                                if row_id is not None:
                                    delete_trade_row(row_id)
                                    rows_deleted += 1
                    except Exception as e:
                        print(f"     delete error: {e}")
                    continue

                si = get_symbol_info(sym)
                contract_size = float(getattr(si, 'trade_contract_size', 1.0)) if si else 1.0

                if martingale_factor == 'profit_factor':
                    if sl_o is None:
                        continue
                    live_risk = abs(entry_o - sl_o) * volume * contract_size
                    live_amount = live_risk * float(programme_rr)
                    sys_amount = sys_res['reward']
                else:
                    if sl_o is None:
                        continue
                    live_amount = abs(entry_o - sl_o) * volume * contract_size
                    sys_amount = sys_res['risk']

                sys_vol = sys_res['volume']
                tolerance = 0.10
                amount_match = (abs(live_amount - sys_amount) / sys_amount <= tolerance
                                if sys_amount > 0 else False)
                volume_match = abs(volume - sys_vol) <= 0.001

                if amount_match and volume_match:
                    print(f"  ✓ {sym} ticket#{order_ticket}: PRESERVED "
                          f"(amount ${live_amount:.2f} ≈ ${sys_amount:.2f}, vol {volume:.2f})")
                    continue

                print(f"  ❌ {sym} ticket#{order_ticket}: mismatch "
                      f"(amount ${live_amount:.2f} vs ${sys_amount:.2f}, "
                      f"vol {volume:.2f} vs {sys_vol:.2f}) — DELETE")
                try:
                    req = {"action": mt5.TRADE_ACTION_REMOVE, "order": order_ticket}
                    res = mt5_order_send(req)
                    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                        cancelled += 1
                        if magic is not None and int(magic) > 0:
                            row_id = None
                            for r in pending_rows:
                                if _coerce_int(_raw_first_key(r, 'tradeid')) == int(magic):
                                    row_id = _coerce_int(_raw_first_key(r, 'id'))
                                    break
                            if row_id is not None:
                                delete_trade_row(row_id)
                                rows_deleted += 1
                except Exception as e:
                    print(f"     delete error: {e}")

        # ------------------------------------------------------------------
        # STEP 4: restore MT5 orders not in DB (magic → tradeid)
        # ------------------------------------------------------------------
        symbols_in_rows = set()
        for row in pending_rows:
            sym = (_raw_first_key(row, 'symbol') or '').strip()
            if sym:
                symbols_in_rows.add(sym)

        if symbols_in_rows:
            mt5_orders = mt5_pending_orders_for_symbols(list(symbols_in_rows))
            existing_tradeids = set()
            for row in pending_rows:
                tid = _coerce_int(_raw_first_key(row, 'tradeid'))
                if tid is not None:
                    existing_tradeids.add(tid)

            type_map = {0: 'buy', 1: 'sell',
                        2: 'buy-limit', 3: 'sell-limit',
                        4: 'buy-stop', 5: 'sell-stop'}

            for order in mt5_orders:
                magic = getattr(order, 'magic', None)
                if magic is None or int(magic) <= 0:
                    continue
                if int(magic) in existing_tradeids:
                    continue

                sym = order.symbol
                typ = int(order.type)
                ordertype = type_map.get(typ, 'buy-limit')
                entry = float(order.price_open)
                sl = float(order.sl) if order.sl else None
                tp = float(order.tp) if order.tp else None
                vol = float(getattr(order, 'volume_current', None)
                            or getattr(order, 'volume_initial', 0) or 0)

                restored = restore_trade_row(
                    investor_id=investor_id,
                    sub_account_id=sub_account_id,
                    programme_id=programme_id,
                    tradeid=int(magic),
                    symbol=sym,
                    ordertype=ordertype,
                    entry=entry,
                    stoploss=sl,
                    takeprofit=tp,
                    volume=vol,
                    timeframe=(_raw_first_key(pending_rows[0], 'timeframe') or 'M1')
                              if pending_rows else 'M1',
                    trade_risk_reward=None,
                )
                if restored:
                    existing_tradeids.add(int(magic))
                    print(f"  ♻️ Restored MT5 order magic={magic} ({sym} {ordertype}) "
                          f"→ programme_trades as tradeid={magic}, vol={vol:.2f}")

        detail['rows_updated'] = rows_updated_vol
        detail['rows_deleted'] = rows_deleted
        detail['mt5_cancelled'] = cancelled

        print(f"\n  📊 Investor {investor_id} summary: "
              f"updated={rows_updated_vol} deleted={rows_deleted} cancelled={cancelled}")

        return detail

    # ==================================================================
    # SECTION 8 — TOP-LEVEL ENUMERATION
    # ==================================================================
    print("\n" + "─"*80)
    print(" 📁 LOADING INVESTOR JOBS FROM DB (VPS-scoped)")
    print("─"*80)

    local_ip = get_local_ip()
    if not local_ip:
        print(" ⚠️ Could not determine local IP")
        stats['errors'].append('local IP unknown')
        stats['processing_success'] = False
        martingale_alert['errors'] = list(stats['errors'])
        return stats
    print(f" │ Local IP: {local_ip}")

    all_jobs = fetch_vps_investor_jobs(local_ip)
    if not all_jobs:
        print(" │ ℹ️ No active investor jobs found for this VPS")
        stats['processing_success'] = True
        martingale_alert['errors'] = []
        return stats

    if inv_db_id:
        jobs = [j for j in all_jobs if str(j.get('investor_id')) == str(inv_db_id)]
        if not jobs:
            print(f" ⚠️ Investor {inv_db_id} not found in any VPS-scoped job")
            stats['errors'].append(f"Investor {inv_db_id} not found")
            stats['processing_success'] = False
            martingale_alert['errors'] = list(stats['errors'])
            return stats
    else:
        jobs = all_jobs

    print(f" │ Loaded {len(jobs)} investor job(s) from DB")
    print("─"*80)

    programme_cfg_cache = {}

    def build_programme_cfg(programme_id, programme_name):
        print(f"\n{'='*60}")
        print(f"  📦 LOADING PROGRAMME CONFIGURATION (id={programme_id})")
        print(f"{'='*60}")

        config_rows = programme_fetch_martingale_config(programme_id)
        if not config_rows:
            print(f"  │ ⚠️ No martingale rows for programme {programme_id}")
            return None

        first = config_rows[0]
        programme_rr = programme_fetch_signal_provider_risk_reward(programme_id)

        cfg = {
            'config_rows': config_rows,
            'default_risk_rows': programme_fetch_default_risk_rows(programme_id),
            'rr_cfg': programme_fetch_rr_config(programme_id),
            'loss_streak_chances': programme_fetch_loss_streak_chances(programme_id),
            'programme_rr': programme_rr,
            'enable_martingale': to_bool(_raw_first_key(first, 'enable_martingale'), default=False),
            'martingale_type': (_raw_first_key(first, 'martingale_type') or 'balance_based').strip(),
            'martingale_factor': (_raw_first_key(first, 'martingale_factor') or 'stoploss_factor').strip(),
            'recovery_adder_pct': parse_percent(_raw_first_key(first, 'martingale_loss_recovery_adder_percentage')),
            'pre_drawdown_assumption': to_bool(_raw_first_key(first, 'pre_drawdown_assumption'), default=False),
            'martingale_pre_scaling': to_bool(_raw_first_key(first, 'martingale_pre_scaling'), default=False),
            'linear_scaling': to_bool(_raw_first_key(first, 'martingale_linear_scaling'), default=False),
            'enable_retention': to_bool(_raw_first_key(first, 'enable_initial_risk_retention'), default=False),
            'retention_pct': parse_percent(_raw_first_key(first, 'initial_risk_retention_percentage')),
        }

        print(f"  │ enable_martingale        : {cfg['enable_martingale']}")
        print(f"  │ martingale_type          : {cfg['martingale_type']}")
        print(f"  │ martingale_factor        : {cfg['martingale_factor']}")
        if cfg['martingale_factor'] == 'profit_factor':
            print(f"  │ programme_rr             : {cfg['programme_rr']}  "
                  f"(risk → reward multiplier)")
        print(f"  │ recovery_adder_pct       : {cfg['recovery_adder_pct']}%")
        print(f"  │ pre_drawdown_assumption  : {cfg['pre_drawdown_assumption']}")
        print(f"  │ martingale_pre_scaling   : {cfg['martingale_pre_scaling']}")
        print(f"  │ linear_scaling           : {cfg['linear_scaling']}")
        print(f"  │ enable_retention         : {cfg['enable_retention']} ({cfg['retention_pct']}%)")
        print(f"  │ loss_streak_chances      : {cfg['loss_streak_chances']}")
        print(f"  │ default_risk_rows        : {len(cfg['default_risk_rows'])}")
        print(f"  │ rr_cfg                   : {cfg['rr_cfg']}")
        print(f"{'='*60}\n")
        return cfg

    for job in jobs:
        investor_id = job.get('investor_id')
        sub_account_id = job.get('sub_account_id')
        programme_id = job.get('programme_id')
        programme_name = job.get('programme_name') or f"programme_{programme_id}"

        if investor_id is None or sub_account_id is None or programme_id is None:
            stats['investors_skipped'] += 1
            continue

        try:
            if programme_id not in programme_cfg_cache:
                programme_cfg_cache[programme_id] = build_programme_cfg(
                    programme_id, programme_name)
                stats['programmes_processed'] += 1
            programme_cfg = programme_cfg_cache[programme_id]

            if not programme_cfg:
                print(f"\n ⏭️ Investor {investor_id}: no programme cfg — skipped")
                stats['investors_skipped'] += 1
                continue

            detail = process_investor(investor_id, sub_account_id, programme_id,
                                      programme_name, programme_cfg)
            stats['details'].append(detail)
            stats['investors_processed'] += 1

            if not martingale_alert.get('programme_id'):
                martingale_alert['programme_id'] = programme_id
                martingale_alert['investor_id'] = investor_id
                martingale_alert['stage'] = detail.get('stage', 0)
                martingale_alert['stage_drawdown'] = detail.get('stage_drawdown', 0.0)
                martingale_alert['total_drawdown'] = detail.get('drawdown', 0.0)
                martingale_alert['sequence_next_risk'] = detail.get('sequence_next_risk', 0.0)
                martingale_alert['mode'] = detail.get('mode')
                martingale_alert['factor'] = detail.get('factor')
                martingale_alert['programme_rr'] = detail.get('programme_rr')
        except Exception as e:
            print(f"\n[CRITICAL] martingale investor={investor_id}: {e}")
            traceback.print_exc()
            stats['errors'].append(f"investor={investor_id}: {e}")
            stats['investors_skipped'] += 1

    stats['rows_updated'] = sum(d.get('rows_updated', 0) for d in stats['details'])
    stats['rows_restored'] = sum(d.get('rows_restored', 0) for d in stats['details'])
    stats['mt5_cancelled'] = sum(d.get('mt5_cancelled', 0) for d in stats['details'])

    martingale_alert['rows_updated'] = stats['rows_updated']
    martingale_alert['rows_restored'] = stats['rows_restored']
    martingale_alert['mt5_cancelled'] = stats['mt5_cancelled']
    martingale_alert['errors'] = list(stats['errors'])

    print(f"\n{'='*10} 🎰 MARTINGALE SUMMARY (DB) {'='*10}")
    print(f"  Programmes processed: {stats['programmes_processed']}")
    print(f"  Investors processed : {stats['investors_processed']}")
    print(f"  Investors skipped   : {stats['investors_skipped']}")
    print(f"  Rows volume-updated : {stats['rows_updated']}")
    print(f"  Rows restored       : {stats['rows_restored']}")
    print(f"  MT5 cancelled       : {stats['mt5_cancelled']}")
    print(f"  Errors              : {len(stats['errors'])}")
    for e in stats['errors']:
        print(f"     • {e}")
    print(f"{'='*10} 🏁 COMPLETE {'='*10}\n")

    stats['processing_success'] = True
    return stats


# ==============================================================================
#  WORKER: one process per investor job (DB-driven)
#
#  MIRRORS process_single_investor_from_db_local ROUTING, BUT DB-ONLY.
#
#  Gate order (matches the local file's conditional routing):
#    1. restricted_timerange_db  -> if restricted, skip everything else.
#    2. recent_highest_balance_target_db -> populates recent_highest_alert.
#    3. If recent_highest_alert['is_triggered'] -> skip every future
#       trading stage (local file deletes open orders/positions at this
#       point; the DB orchestrator will do the same once that stage is
#       ported, via a DB-driven delete function).
# ==============================================================================
def process_single_investor_from_db(job):
    """
    DB version of process_single_investor_test_one_function().

    Purpose: run ONLY the unauthorized-actions auditor against a single
    investor so it can be tested solo without the rest of the pipeline.

    No restriction gate. No alarm gate. No cleanup. Only the audit stage.
    """

    global unauthorized_alert

    inv_db_id = job.get('investor_id')
    sub_id = job.get('sub_account_id')
    programme_id = job.get('programme_id')
    programme_name = job.get('programme_name') or ''

    print(f"\n[START][TEST] ⚙️ Unauthorized-actions-audit-only run for "
          f"Investor {inv_db_id} (sub {sub_id}) | "
          f"programme '{programme_name}' (id={programme_id})")

    account_stats = {
        'investor_id':    inv_db_id,
        'sub_account_id': sub_id,
        'programme_id':   programme_id,
        'success':        False,
        'stages':         {},
    }

    _worker_init()

    # ------------------------------------------------------------------
    # MT5 CONNECT
    # ------------------------------------------------------------------
    try:
        terminal_path = resolve_investor_terminal_path(inv_db_id, sub_id)
        print(f"[MT5-PATH] final resolved terminal = {terminal_path}")

        mt5_ok = mt5_connect(terminal_path=terminal_path, timeout_ms=15000)
        if mt5_ok:
            print(f"[MT5] ✅ Connected "
                  f"({'custom path' if terminal_path else 'default install'}) "
                  f"for investor {inv_db_id} (sub {sub_id})")
        else:
            print(f"[MT5] ⚠️ mt5_connect returned False "
                  f"(last_error={mt5_last_error()})")
    except Exception as e:
        print(f"[MT5] ⚠️ mt5_connect raised: {e}")

    try:
        # ==============================================================
        # UNAUTHORIZED-ACTIONS AUDIT — THE ONLY STAGE
        # ==============================================================
        audit_stats = run_stage(
            'check_and_record_unauthorized_actions_db',
            check_and_record_unauthorized_actions_db,
            inv_db_id=inv_db_id,
        )
        account_stats['stages']['check_and_record_unauthorized_actions_db'] = audit_stats
        account_stats['unauthorized_actions_stats'] = audit_stats

        account_stats['success'] = bool(
            audit_stats.get('processing_success', False)
        )

    except Exception as e:
        print(f"[CRITICAL ERROR][TEST] investor={inv_db_id}: {e}")
        traceback.print_exc()
        account_stats['success'] = False
        account_stats['error'] = str(e)

    finally:
        try:
            mt5_disconnect()
        except Exception:
            pass
        try:
            if _db is not None:
                _db.release_channel()
        except Exception:
            pass

    return account_stats

def process_single_investor_from_db_(job):
    """
    DB version of process_single_investor_local().

    Mirrors the LOCAL file's stage order exactly:
        gate 1 (restriction)  -> skip-all + delete_all_orders_and_positions
        gate 2 (alarm)        -> skip-all + delete_all_orders_and_positions
        else                  -> full trading pipeline in local's exact order

    Grid is out of scope: every grid-only stage is dropped from the pipeline
    (they were previously behind `if grid_strategy_enabled:` in local).

    Every stage that has not yet been ported to DB is present as a
    commented stub, positioned exactly where the local file calls it.
    Uncomment as each DB stage becomes available.

    Note: `check_and_record_unauthorized_actions` and `trades_analytics`
    are called TWICE in the local file (top and bottom of the pipeline).
    That duplication is preserved here. Both calls are now live against
    the DB port `check_and_record_unauthorized_actions_db`.
    """

    global martingale_alert
    global unauthorized_alert

    inv_db_id = job.get('investor_id')
    sub_id = job.get('sub_account_id')
    programme_id = job.get('programme_id')
    programme_name = job.get('programme_name') or ''

    print(f"\n[START] ⚙️ Investor {inv_db_id} (sub {sub_id}) | "
          f"programme '{programme_name}' (id={programme_id})")

    account_stats = {
        'investor_id':    inv_db_id,
        'sub_account_id': sub_id,
        'programme_id':   programme_id,
        'success':        False,
        'restricted':     False,
        'restricted_kind': None,
        'restricted_window': None,
        'restricted_day': None,
        'alarm_hit':      False,
        'alarm_mode':     None,
        'alarm_details':  None,
        'unauthorized_hit': False,
        'unauthorized_types': [],
        'account_mode':   'UNKNOWN',
        'account_type':   'UNKNOWN',
        'is_real_account': False,
        'stages': {},
    }

    _worker_init()

    # ------------------------------------------------------------------
    # MT5 CONNECT
    # ------------------------------------------------------------------
    mt5_ok = False
    try:
        terminal_path = resolve_investor_terminal_path(inv_db_id, sub_id)
        print(f"[MT5-PATH] final resolved terminal = {terminal_path}")

        mt5_ok = mt5_connect(terminal_path=terminal_path, timeout_ms=15000)
        if mt5_ok:
            print(f"[MT5] ✅ Connected "
                  f"({'custom path' if terminal_path else 'default install'}) "
                  f"for investor {inv_db_id} (sub {sub_id})")
        else:
            print(f"[MT5] ⚠️ mt5_connect returned False "
                  f"(last_error={mt5_last_error()})")
    except Exception as e:
        print(f"[MT5] ⚠️ mt5_connect raised: {e}")
        mt5_ok = False

    try:
        # ==================================================================
        # ACCOUNT INFO / TYPE (mirrors local's account_mode classification)
        # ==================================================================
        try:
            acc = mt5_account_info()
            if acc is not None:
                account_stats['account_type'] = 'REAL' if getattr(acc, 'trade_mode', 0) == 0 else 'DEMO'
                account_stats['account_mode'] = 'real' if getattr(acc, 'trade_mode', 0) == 0 else 'demo'
                account_stats['is_real_account'] = bool(getattr(acc, 'trade_mode', 0) == 0)
                print(f"[{inv_db_id}] Account mode: {account_stats['account_mode'].upper()} "
                      f"({account_stats['account_type']})")
        except Exception as acc_err:
            print(f"[{inv_db_id}] ⚠️ account_info failed: {acc_err}")

        # ==================================================================
        # GATE 1 — RESTRICTED TIMERANGE
        # ==================================================================
        timerange_stats = run_stage(
            'restricted_timerange_db',
            restricted_timerange_db,
            inv_db_id=inv_db_id,
        )
        account_stats['stages']['restricted_timerange_db'] = timerange_stats
        account_stats['restricted_timerange_db_stats'] = timerange_stats

        verdict = _programme_restriction_verdict(timerange_stats, programme_id)
        is_restricted_now = bool(verdict.get('is_restricted'))

        if is_restricted_now:
            _restriction_skip_banner(
                inv_db_id=inv_db_id,
                sub_id=sub_id,
                programme_id=programme_id,
                programme_name=programme_name,
                verdict=verdict,
            )

            # --- Local CONDITION B/C: cleanup only ---
            # delete_all_orders_and_positions(inv_db_id=inv_db_id)
            # ^^^ DB port not yet available. Uncomment when ready.

            account_stats['restricted'] = True
            account_stats['restricted_kind'] = verdict.get('kind')
            account_stats['restricted_window'] = verdict.get('window_desc')
            account_stats['restricted_day'] = verdict.get('day_name')
            account_stats['success'] = True
            return account_stats

        account_stats['restricted'] = False

        # ==================================================================
        # GATE 2 — RECENT HIGHEST BALANCE TARGET + DAILY-TARGET ALARM
        # ==================================================================
        recent_balance_stats = run_stage(
            'recent_highest_balance_target_db',
            recent_highest_balance_target_db,
            inv_db_id=inv_db_id,
        )
        account_stats['stages']['recent_highest_balance_target_db'] = recent_balance_stats
        account_stats['recent_highest_balance_stats'] = recent_balance_stats

        alert = recent_highest_alert or {}
        alarm_hit = bool(alert.get('is_triggered'))

        if alarm_hit:
            _daily_target_alarm_banner(
                inv_db_id=inv_db_id,
                sub_id=sub_id,
                programme_id=programme_id,
                programme_name=programme_name,
                alert=alert,
            )

            # --- Local: if recent_highest_hit -> delete_all_orders_and_positions ---
            # delete_all_orders_and_positions(inv_db_id=inv_db_id)
            # ^^^ DB port not yet available. Uncomment when ready.

            account_stats['alarm_hit'] = True
            account_stats['alarm_mode'] = (
                "PRE-PENDING" if alert.get('pre_pending_enabled') else "DAILY"
            )
            account_stats['alarm_details'] = {
                'daily_target_owed': alert.get('daily_target_owed'),
                'pre_pending_total': alert.get('pre_pending_total'),
                'total_all_debt':    alert.get('total_all_debt'),
                'effective_today':   alert.get('effective_today'),
                'action':            alert.get('action'),
            }
            account_stats['success'] = True
            return account_stats

        account_stats['alarm_hit'] = False

        # ==================================================================
        # CONDITION A — NO RESTRICTIONS: RUN THE FULL TRADING PIPELINE
        # ==================================================================
        print(f"  ✅ Trading allowed for {inv_db_id}")

        # ------------------------------------------------------------------
        # A1. Stages that ALWAYS run (top of local's Condition A)
        # ------------------------------------------------------------------
        audit_stats_top = run_stage(
            'check_and_record_unauthorized_actions_db',
            check_and_record_unauthorized_actions_db,
            inv_db_id=inv_db_id,
        )
        account_stats['stages']['check_and_record_unauthorized_actions_db_top'] = audit_stats_top
        account_stats['unauthorized_actions_stats_top'] = audit_stats_top

        # delete_unauthorized_symbol_files(inv_db_id=inv_db_id)
        # ^^^ DB port not yet available. Uncomment when ready.

        # OHLC and GRID callings or executions are not needed in this!!!
        # regardless of them present in the local process single investor
        # don't include them here.

        # ------------------------------------------------------------------
        # A2. Stages that ALWAYS run (middle of local's Condition A)
        # ------------------------------------------------------------------
        # deduplicate_orders(inv_db_id=inv_db_id)
        # validate_strategy_authorized_orders(inv_db_id=inv_db_id)
        # backup_limit_orders(inv_db_id=inv_db_id)
        # populate_orders_missing_fields(inv_db_id=inv_db_id)
        # calculate_investor_symbols_orders(inv_db_id=inv_db_id)
        # live_usd_risk_and_scaling(inv_db_id=inv_db_id)
        # apply_default_prices(inv_db_id=inv_db_id)
        # ^^^ DB ports not yet available. Uncomment when ready.

        # ------------------------------------------------------------------
        # A5. MARTINGALE — same position as the local file.
        # ------------------------------------------------------------------
        martingale_stats = run_stage(
            'martingale_system_db',
            martingale_system_db,
            inv_db_id=inv_db_id,
        )
        account_stats['stages']['martingale_system_db'] = martingale_stats
        account_stats['martingale_stats'] = martingale_stats

        # ------------------------------------------------------------------
        # A6. Stages that ALWAYS run (after martingale in local)
        # ------------------------------------------------------------------
        # padding_stoploss_below_minimum_risk_to_maximum_risk(inv_db_id=inv_db_id)
        # maximum_risk_distance_and_adjust_to_max_risk_distance_no_removal(inv_db_id=inv_db_id)
        # pending_orders_per_symbol_limitation(inv_db_id=inv_db_id)
        # chunk_orders_with_volume_beyond_max(inv_db_id=inv_db_id)
        # place_usd_orders(inv_db_id=inv_db_id)
        # ^^^ DB ports not yet available. Uncomment when ready.

        # ------------------------------------------------------------------
        # A7. GRID-gated manage block — OUT OF SCOPE.
        # ------------------------------------------------------------------

        # ------------------------------------------------------------------
        # A8. Stages that ALWAYS run (tail of local's Condition A)
        # ------------------------------------------------------------------
        # close_unauthorized_orders(inv_db_id=inv_db_id)
        # orders_reward_correction(inv_db_id=inv_db_id)
        # check_pending_orders_risk(inv_db_id=inv_db_id)
        # apply_dynamic_breakeven(inv_db_id=inv_db_id)

        # 2nd call, same as local
        audit_stats_tail = run_stage(
            'check_and_record_unauthorized_actions_db',
            check_and_record_unauthorized_actions_db,
            inv_db_id=inv_db_id,
        )
        account_stats['stages']['check_and_record_unauthorized_actions_db_tail'] = audit_stats_tail
        account_stats['unauthorized_actions_stats_tail'] = audit_stats_tail

        # trades_analytics(inv_db_id=inv_db_id)
        # ^^^ DB port not yet available. Uncomment when ready.

        # Surface the auditor's verdict on the account_stats
        ua = unauthorized_alert or {}
        account_stats['unauthorized_hit'] = bool(ua.get('is_triggered'))
        account_stats['unauthorized_types'] = list(ua.get('unauthorized_types') or [])

        account_stats['success'] = True
        print(f"[SUCCESS] Finished full pipeline execution context for "
              f"Investor {inv_db_id} ({account_stats['account_mode']})")

    except Exception as e:
        print(f"[CRITICAL ERROR] investor={inv_db_id}: {e}")
        traceback.print_exc()
        account_stats['success'] = False
        account_stats['error'] = str(e)

    finally:
        try:
            mt5_disconnect()
        except Exception:
            pass
        try:
            if _db is not None:
                _db.release_channel()
        except Exception:
            pass

    return account_stats

# ==============================================================================
#  ORCHESTRATOR — DB-driven, no local folders
# ==============================================================================
def discover_investor_jobs():
    local_ip = get_local_ip()
    if not local_ip:
        print("⚠️ Could not determine local IP — no jobs will be created")
        return []
    return fetch_vps_investor_jobs(local_ip)


def main_loop():
    run_as_loop = False
    loop_interval = 5
    max_loops = None

    for arg in sys.argv[1:]:
        if arg.startswith('--loop='):
            run_as_loop = arg.split('=')[1].lower() in ('true', 'yes', '1', 'on')
        elif arg.startswith('--interval='):
            try:
                loop_interval = int(arg.split('=')[1])
            except ValueError:
                pass
        elif arg.startswith('--max-loops='):
            try:
                max_loops = int(arg.split('=')[1])
            except ValueError:
                pass

    print("\n" + "=" * 60)
    print("         PROGRAMMETRADES — RESTRICTED TIMERANGE ORCHESTRATOR")
    print("=" * 60)
    print(f"  Loop Mode: {'ENABLED' if run_as_loop else 'DISABLED'}")
    if run_as_loop:
        print(f"  Interval: {loop_interval}s")
        print(f"  Max Loops: {max_loops if max_loops else 'Infinite'}")
    print("=" * 60 + "\n")

    _worker_init()

    cpu_cores = os.cpu_count() or 1
    pool_size = max(1, min(cpu_cores, 4))
    print(f"🖥️  Cores detected: {cpu_cores} | Persistent worker count: {pool_size}")

    pool = mp.Pool(processes=pool_size)
    print(f"✅ Persistent pool ready ({pool_size} workers).\n")

    loop_count = 0
    try:
        while True:
            loop_count += 1
            if run_as_loop:
                print("\n" + "=" * 60)
                print(f"LOOP #{loop_count} STARTED")
                print("=" * 60)

            try:
                jobs = discover_investor_jobs()

                if not jobs:
                    print(f" └─ 🔘 No active investor jobs returned by DB for "
                          f"this VPS. Sleeping {loop_interval}s.")
                    time.sleep(loop_interval)
                    continue

                print(f"📊 Submitting {len(jobs)} investor job(s) "
                      f"via persistent pool")

                t0 = time.time()
                async_jobs = [
                    pool.apply_async(process_single_investor_from_db, args=(job,))
                    for job in jobs
                ]

                results = []
                for aj in async_jobs:
                    try:
                        results.append(aj.get(timeout=600))
                    except mp.TimeoutError:
                        print("⚠️ A worker timed out; moving on.")
                        results.append(None)
                    except Exception as job_err:
                        print(f"⚠️ Worker raised: {job_err}")
                        results.append(None)

                elapsed = time.time() - t0
                ok = sum(1 for r in results if r and r.get('success'))
                print(f"--- Cycle Complete in {elapsed:.2f}s | "
                      f"ok={ok}/{len(jobs)} ---")

            except Exception as e:
                print(f"Critical Error in Orchestrator Loop: {e}")
                traceback.print_exc()
                time.sleep(5)

            if not run_as_loop:
                print("Single execution completed. Exiting...")
                break

            if max_loops and loop_count >= max_loops:
                print(f"Maximum loops ({max_loops}) reached. Exiting...")
                break

            if run_as_loop and loop_interval > 0:
                time.sleep(loop_interval)

    except KeyboardInterrupt:
        print("\n[main] interrupted — shutting down")

    finally:
        print("Shutting down persistent pool...")
        try:
            pool.close()
            pool.join()
        except Exception as shutdown_err:
            print(f"[WARN] Pool shutdown issue: {shutdown_err}")

        try:
            if _db is not None:
                _db.release_channel()
        except Exception:
            pass

        print("Pool shut down cleanly.")


if __name__ == "__main__":
    main_loop()
