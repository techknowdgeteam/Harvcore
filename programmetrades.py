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
#  CHECK AND RECORD UNAUTHORIZED ACTIONS — DB version (tradeid-based)
#
#  Investor-scoped, MT5-facing.
#
#  A trade (pending order, open position, or closed deal) is AUTHORIZED for
#  an investor iff its `magic` (as seen by MT5) is present in that
#  investor's programme_trades.tradeid set for THIS programme.
#
#  Because the magic column has been dropped, MT5's `order.magic` is matched
#  directly against programme_trades.tradeid. tradeid is a per-programme
#  counter, so cross-programme collisions are impossible when the
#  (programmeid, tradeid, owner) tuple is used as the lookup key.
#
#  Nothing here touches JSON files.
# ==============================================================================
def check_and_record_unauthorized_actions_db(inv_db_id=None):
    """
    Reads:
        * programme_trades        -> this investor's authorized tradeid set
        * harvhub                 -> anchor (broker_balance, execution_start_date)
                                     + identity
        * balance_log             -> last known closing balance for continuity
        * MT5                     -> live orders / positions / history deals

    Writes:
        * balance_log             -> ONE ROW PER LAGOS DAY from execution_start_date
                                     through today (not just today)
        * contract_notifications  -> INVESTOR-SIDE alert (per investor, per event)
                                     via notification_service.record_contract_notification
        * programme_notifications -> PROGRAMME-OWNER-SIDE aggregated alert
                                     (one per programme per run) via
                                     notification_service.record_programme_notification

        NOTE: NO DAY-LEVEL DEDUP on either side. A notification fires every
        time unauthorized activity is detected.

    ENFORCEMENT:
        * Any MT5 pending order whose magic is NOT in the investor's
          authorized tradeid set is CANCELLED immediately.
        * Any MT5 open position whose magic is NOT in the investor's
          authorized tradeid set is CLOSED immediately.
    """

    global unauthorized_alert
    from datetime import datetime, timedelta, timezone
    import time as _time

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

    def lagos_date_str(dt):
        if dt is None:
            return None
        try:
            return dt.astimezone(LAGOS_TZ).strftime("%Y-%m-%d")
        except Exception:
            return None

    def lagos_date_add(date_str, days):
        try:
            base = datetime.strptime(date_str, "%Y-%m-%d")
            return (base + timedelta(days=days)).strftime("%Y-%m-%d")
        except Exception:
            return None

    def lagos_daterange(start_str, end_str):
        cur = start_str
        guard = 0
        while cur is not None and cur <= end_str and guard < 4000:
            yield cur
            cur = lagos_date_add(cur, 1)
            guard += 1

    unauthorized_alert = {
        'is_triggered': False,
        'investor_id': inv_db_id if inv_db_id else 'all',
        'sub_account_id': None,
        'programme_id': None,
        'investor_authorized_tradeids': set(),
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
        'unauthorized_orders_cancelled': 0,
        'unauthorized_positions_found': 0,
        'unauthorized_positions_closed': 0,
        'unauthorized_trades_found': 0,
        'unaccounted_deficits_found': 0,
        'balance_log_rows_written': 0,
        'notifications_queued': 0,
        'errors': [],
        'processing_success': False,
        'details': [],
    }

    # ==================================================================
    # PROGRAMME-LEVEL VIOLATOR AGGREGATION
    # ------------------------------------------------------------------
    # One owner-side notification per programme per run. The owner's
    # email is resolved here, at aggregation time, using a robust
    # fallback chain (main account -> any harvhub row for that userid).
    # ==================================================================
    programme_violators = {}

    def _register_programme_violator(
        programme_id, programme_name,
        investor_id, sub_account_id,
        total_unauth_pnl, unauth_types,
    ):
        if not programme_id:
            return
        entry = programme_violators.setdefault(programme_id, {
            'programme_name': programme_name or f"programme {programme_id}",
            'violators': [],
        })
        if not entry['programme_name'] and programme_name:
            entry['programme_name'] = programme_name
        entry['violators'].append({
            'investor_id': investor_id,
            'sub_account_id': sub_account_id,
            'pnl': float(total_unauth_pnl or 0.0),
            'types': list(unauth_types or []),
        })

    # ==================================================================
    # SECTION 1 — PROGRAMME-SCOPED READERS
    # ==================================================================
    def programme_fetch_owner_identity(programme_id):
        """
        Resolve (owner_email, programme_name, owner_userid) for the programme.

        Robust resolution strategy:
          1. programme.program_name
          2. programme.userid  -> harvhub.is_main_account = 1  (preferred)
          3. programme.userid  -> any harvhub row (fallback)

        Returns (owner_email, programme_name, owner_userid); any may be
        empty/None.
        """
        prog_row = db_fetch_one(
            "SELECT program_name, userid FROM programme WHERE id = %s LIMIT 1",
            [programme_id], timeout=10.0, quiet=True,
        )
        if not prog_row:
            return '', '', None

        programme_name = (
            _pick_first_key(prog_row, 'program_name') or ''
        ).strip()
        owner_userid = _coerce_int(_raw_first_key(prog_row, 'userid'))

        owner_email = ''
        if owner_userid is not None and owner_userid > 0:
            # Preferred: main account
            main_row = db_fetch_one(
                """
                SELECT email FROM harvhub
                 WHERE id = %s AND is_main_account = 1
                 ORDER BY id ASC
                 LIMIT 1
                """,
                [owner_userid], timeout=10.0, quiet=True,
            )
            if main_row:
                owner_email = (
                    _pick_first_key(main_row, 'email') or ''
                ).strip().lower()

            # Fallback: any harvhub row for this userid
            if not owner_email:
                any_row = db_fetch_one(
                    """
                    SELECT email FROM harvhub
                     WHERE id = %s
                       AND email IS NOT NULL
                       AND email <> ''
                     ORDER BY is_main_account DESC, id ASC
                     LIMIT 1
                    """,
                    [owner_userid], timeout=10.0, quiet=True,
                )
                if any_row:
                    owner_email = (
                        _pick_first_key(any_row, 'email') or ''
                    ).strip().lower()

        if not owner_email:
            print(f"      [NOTIF] ⚠️ Could not resolve owner email for "
                  f"programme={programme_id} (userid={owner_userid})")

        return owner_email, programme_name, owner_userid

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
        return db_fetch_one(
            """
            SELECT id, sub_account_id, broker_balance, execution_start_date
              FROM harvhub
             WHERE id = %s AND sub_account_id = %s
             LIMIT 1
            """,
            [investor_id, sub_account_id], timeout=10.0, quiet=True,
        ) or {}

    def investor_fetch_authorized_tradeids(investor_id, sub_account_id, programme_id):
        rows = db_fetch_all(
            """
            SELECT tradeid
              FROM programme_trades
             WHERE userid = %s
               AND programmeid = %s
               AND investor_id = %s
               AND investor_sub_account_id = %s
               AND orderstatus = 'pending'
               AND tradeid IS NOT NULL
            """,
            [investor_id, programme_id, investor_id, sub_account_id],
            timeout=10.0, quiet=True,
        )
        out = set()
        for r in rows:
            t = _coerce_int(_raw_first_key(r, 'tradeid'))
            if t is not None and t > 0:
                out.add(t)
        return out

    def balance_log_fetch_day(investor_id, sub_account_id, date_str):
        return db_fetch_one(
            """
            SELECT id, date, day_starting_balance, day_closing_balance,
                   day_authorized_trades_pnl, day_unauthorized_trades_pnl,
                   unusual_activity
              FROM balance_log
             WHERE userid = %s AND sub_account_id = %s AND date = %s
             LIMIT 1
            """,
            [investor_id, sub_account_id, date_str], timeout=10.0, quiet=True,
        ) or {}

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
    # SECTION 3 — MT5 READS
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
    # SECTION 3b — MT5 ENFORCEMENT
    # ==================================================================
    def mt5_cancel_pending_order(order):
        ticket = getattr(order, 'ticket', None)
        if ticket is None:
            return False, "no_ticket"
        try:
            req = {"action": mt5.TRADE_ACTION_REMOVE, "order": int(ticket)}
            res = mt5_order_send(req)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                return True, "cancelled"
            if res:
                return False, f"retcode={res.retcode} comment={getattr(res, 'comment', '')}"
            return False, f"no_response last_error={mt5_last_error()}"
        except Exception as e:
            return False, f"exception: {e}"

    def mt5_close_position(pos):
        ticket = getattr(pos, 'ticket', None)
        symbol = getattr(pos, 'symbol', None)
        volume = getattr(pos, 'volume', None)
        if ticket is None or not symbol or not volume:
            return False, "missing_position_fields", None

        tick = mt5_symbol_tick(symbol)
        if tick is None:
            return False, f"no_tick_for_{symbol}", None

        if getattr(pos, 'type', None) == 0:
            close_type = mt5.ORDER_TYPE_SELL if mt5 is not None else 1
            close_price = tick.bid
        else:
            close_type = mt5.ORDER_TYPE_BUY if mt5 is not None else 0
            close_price = tick.ask

        attempts = [
            {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(volume),
                "type": close_type,
                "position": int(ticket),
                "price": float(close_price),
                "deviation": 20,
                "magic": int(getattr(pos, 'magic', 0) or 0),
                "comment": "UNAUTH-CLOSE",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            },
            {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(volume),
                "type": close_type,
                "position": int(ticket),
                "price": float(close_price),
                "deviation": 50,
                "magic": int(getattr(pos, 'magic', 0) or 0),
                "comment": "UNAUTH-CLOSE-RETRY",
                "type_filling": mt5.ORDER_FILLING_RETURN,
            },
        ]
        last_msg = "no_attempt"
        for req in attempts:
            try:
                res = mt5_order_send(req)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    return True, "closed", float(close_price)
                if res:
                    last_msg = f"retcode={res.retcode} comment={getattr(res, 'comment', '')}"
                else:
                    last_msg = f"no_response last_error={mt5_last_error()}"
            except Exception as e:
                last_msg = f"exception: {e}"
        return False, last_msg, None

    # ==================================================================
    # SECTION 4 — NOTIFICATION HOOKS
    # ==================================================================

    # ------------------------------------------------------------------
    # INVESTOR-SIDE notification — contract-scoped.
    #
    # Investors live on contract_notifications, not programme_notifications.
    # This uses record_contract_notification (not the _once variant) so
    # it fires on EVERY detection — no day-level dedup.
    # ------------------------------------------------------------------
    def notify_investor_unauthorized(investor_id, sub_account_id,
                                     investor_email, main_account_id):
        if not investor_email or '@' not in investor_email:
            print(f"      [NOTIF] investor email invalid — skip")
            return 0

        try:
            from notification_service import (
                record_contract_notification,
            )
        except Exception as e:
            print(f"      [NOTIF] notification_service unavailable: {e}")
            return 0

        message = (
            "We detected unauthorized actions on your account. "
            "This means trades were placed outside your contract trades. "
            "Unfortunately your contract has been cancelled."
        )

        event_id = f"{int(_time.time() * 1000)}"
        try:
            nid = record_contract_notification(
                _NOTIF_PDO,
                {
                    'user_email': investor_email,
                    'sub_account_id': int(sub_account_id),
                    'main_account_id': int(main_account_id or 0),
                    'notification_key': (
                        f'contract-unauth-investor-{investor_id}-'
                        f'{sub_account_id}-{event_id}'
                    ),
                    'title': 'Unauthorized Actions Detected',
                    'message': message,
                    'type': 'danger',
                    'section': 'Unauthorized',
                    'action_tab': 'activity',
                    'force': False,
                    'send_email': True,
                },
            )
            if nid:
                print(f"      [NOTIF] ✅ investor {investor_email} notified (id={nid})")
                return 1
            print(f"      [NOTIF] investor {investor_email} — record returned None")
            return 0
        except Exception as e:
            print(f"      [NOTIF] investor notify failed: {e}")
            return 0

    # ------------------------------------------------------------------
    # PROGRAMME-OWNER-SIDE aggregated notification — programme-scoped.
    # Fires on EVERY detection run. No dedup.
    #
    # Wording: proper pluralisation ("investor" / "investors",
    # "violator" / "violators"). No parenthesised "(s)" forms anywhere.
    # ------------------------------------------------------------------
    def notify_programme_owner_violators(
        programme_id, programme_name, owner_email, violators,
    ):
        if not owner_email or '@' not in owner_email:
            print(f"      [NOTIF] owner email missing/invalid for "
                  f"programme={programme_id} — skip owner notify")
            return 0
        if not violators:
            return 0

        try:
            from notification_service import (
                record_programme_notification,
            )
        except Exception as e:
            print(f"      [NOTIF] notification_service unavailable: {e}")
            return 0

        count = len(violators)
        violator_word = "violator" if count == 1 else "violators"
        investor_word = "investor" if count == 1 else "investors"
        have_word = "has" if count == 1 else "have"

        profit_violators = [v for v in violators if (v.get('pnl') or 0.0) > 0.01]
        noprofit_violators = [v for v in violators if (v.get('pnl') or 0.0) <= 0.01]

        profit_count = len(profit_violators)
        noprofit_count = len(noprofit_violators)

        base = (
            f"We detected {count} of your {programme_name} {investor_word} "
            f"{have_word} violated the programme trades thus the "
            f"{violator_word} {have_word} been paused and can no longer "
            f"proceed with this contract."
        )

        clauses = []

        if profit_count > 0:
            profit_violator_word = (
                "violator" if profit_count == 1 else "violators"
            )
            clauses.append(
                f"Profit percentage made within the periods will be paid "
                f"for the {profit_count} {profit_violator_word} that "
                f"recorded profit."
            )

        if noprofit_count > 0:
            noprofit_violator_word = (
                "violator" if noprofit_count == 1 else "violators"
            )
            clauses.append(
                f"Unfortunately no profit has been made for the "
                f"{noprofit_count} {noprofit_violator_word} that did not "
                f"record profit, so no profit percentage will be paid."
            )

        if not clauses:
            clauses.append(
                "No profit percentage is payable to the violator or violators."
            )

        message = base + " " + " ".join(clauses)

        event_id = f"{int(_time.time() * 1000)}"
        try:
            nid = record_programme_notification(
                _NOTIF_PDO,
                int(programme_id),
                owner_email,
                {
                    'notification_key': (
                        f'prog-unauth-owner-{programme_id}-{event_id}'
                    ),
                    'title': 'Programme Contract Violation Detected',
                    'message': message,
                    'type': 'danger',
                    'section': 'Unauthorized',
                    'action_tab': 'programme_investors',
                    'force': False,
                    'send_email': True,
                },
            )
            if nid:
                print(f"      [NOTIF] ✅ owner {owner_email} notified (id={nid})")
                return 1
            print(f"      [NOTIF] owner {owner_email} — record returned None")
            return 0
        except Exception as e:
            print(f"      [NOTIF] owner notify failed: {e}")
            return 0

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
            'main_account_id': 0,
            'authorized_tradeid_count': 0,
            'unauthorized_orders': 0,
            'unauthorized_orders_cancelled': 0,
            'unauthorized_positions': 0,
            'unauthorized_positions_closed': 0,
            'unauthorized_trades': 0,
            'unauthorized_pnl_total': 0.0,
            'unaccounted_deficit': 0.0,
            'unauthorized_types': [],
            'balance_log_action': None,
            'balance_log_days_written': 0,
            'notifications_sent': 0,
            'application_status': 'approved',
            'error': None,
        }

        # -------- identity + anchor + programme owner --------
        identity = investor_fetch_identity(investor_id, sub_account_id)
        investor_email = (_pick_first_key(identity, 'email') or '').strip().lower()
        main_account_id = _coerce_int(
            _raw_first_key(identity, 'main_account_id')
        ) or 0
        fullname = _pick_first_key(identity, 'fullname') or f"user{investor_id}"
        detail['investor_email'] = investor_email
        detail['main_account_id'] = main_account_id

        owner_email, prog_name, owner_userid = programme_fetch_owner_identity(programme_id)
        if not programme_name:
            programme_name = prog_name
        detail['owner_email'] = owner_email

        print(f"\n{'─'*72}")
        print(f" 🔍 Investor {investor_id} (sub {sub_account_id}) | "
              f"programme '{programme_name}' (id={programme_id})")
        print(f"{'─'*72}")
        print(f"  │ Investor email      : {investor_email or '—'}")
        print(f"  │ Programme owner     : {owner_email or '—'}"
              f"{f' (userid={owner_userid})' if owner_userid else ''}")

        # -------- authorized tradeid set --------
        authorized_tradeids = investor_fetch_authorized_tradeids(
            investor_id, sub_account_id, programme_id)
        detail['authorized_tradeid_count'] = len(authorized_tradeids)
        if authorized_tradeids:
            sample = sorted(authorized_tradeids)[:8]
            print(f"  │ Authorized trade IDs: {len(authorized_tradeids)} "
                  f"(sample: {sample}{'…' if len(authorized_tradeids) > 8 else ''})")
        else:
            print(f"  │ Authorized trade IDs: NONE — every MT5 action will be flagged")

        # -------- anchor --------
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
            broker_balance = mt5_balance_now
            print(f"  │ ⚠️ harvhub.broker_balance NULL — using MT5 balance "
                  f"as anchor (${(mt5_balance_now or 0):.2f})")

        # -------- MT5: pending orders / open positions --------
        pending_orders = mt5_pending_orders()
        open_positions = mt5_open_positions()

        # -------- ENFORCEMENT A: cancel unauthorized pending --------
        unauth_orders = []
        cancelled_orders = 0
        for order in pending_orders:
            try:
                om = int(getattr(order, 'magic', 0) or 0)
            except Exception:
                om = 0
            if om in authorized_tradeids:
                continue

            order_rec = {
                'ticket': getattr(order, 'ticket', None),
                'symbol': getattr(order, 'symbol', None),
                'volume': float(getattr(order, 'volume_current', 0) or 0),
                'price': float(getattr(order, 'price_open', 0) or 0),
                'magic': om,
                'action': 'pending',
            }
            print(f"  │ 🚫 UNAUTHORIZED PENDING #{order_rec['ticket']} "
                  f"{order_rec['symbol']} magic={om} — cancelling…")
            ok, msg = mt5_cancel_pending_order(order)
            if ok:
                order_rec['action'] = 'cancelled'
                cancelled_orders += 1
                print(f"  │    ✅ cancelled")
            else:
                order_rec['action'] = 'cancel_failed'
                print(f"  │    ✗ cancel failed: {msg}")
            unauth_orders.append(order_rec)

        # -------- ENFORCEMENT B: close unauthorized positions --------
        unauth_positions = []
        closed_positions = 0
        for pos in open_positions:
            try:
                pm = int(getattr(pos, 'magic', 0) or 0)
            except Exception:
                pm = 0
            if pm in authorized_tradeids:
                continue

            pos_rec = {
                'ticket': getattr(pos, 'ticket', None),
                'symbol': getattr(pos, 'symbol', None),
                'volume': float(getattr(pos, 'volume', 0) or 0),
                'price': float(getattr(pos, 'price_open', 0) or 0),
                'profit': float(getattr(pos, 'profit', 0) or 0),
                'magic': pm,
                'action': 'open',
            }
            print(f"  │ 🚫 UNAUTHORIZED POSITION #{pos_rec['ticket']} "
                  f"{pos_rec['symbol']} magic={pm} — closing…")
            ok, msg, close_price = mt5_close_position(pos)
            if ok:
                pos_rec['action'] = 'closed'
                pos_rec['close_price'] = close_price
                closed_positions += 1
                print(f"  │    ✅ closed @ {close_price}")
            else:
                pos_rec['action'] = 'close_failed'
                print(f"  │    ✗ close failed: {msg}")
            unauth_positions.append(pos_rec)

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
        start_dt_naive = start_dt.replace(tzinfo=None)

        deals = mt5_history_deals_for_investor(start_dt_naive)

        authorized_deals = []
        unauthorized_deals = []
        total_auth_pnl = 0.0
        total_unauth_pnl = 0.0
        auth_count = 0
        unauth_count = 0

        per_day = {}

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
            day_key = lagos_date_str(deal_lagos)
            if day_key is None:
                continue

            rec = {
                'ticket': getattr(deal, 'ticket', None),
                'symbol': getattr(deal, 'symbol', None),
                'volume': float(getattr(deal, 'volume', 0) or 0),
                'pnl': pnl,
                'magic': dm,
                'time': deal_lagos.strftime('%Y-%m-%d %H:%M:%S') if deal_lagos else None,
            }

            bucket = per_day.setdefault(day_key, {
                'auth': 0.0, 'unauth': 0.0,
                'auth_n': 0, 'unauth_n': 0,
                'records': [],
            })
            bucket['records'].append(rec)

            if dm in authorized_tradeids:
                authorized_deals.append(rec)
                total_auth_pnl += pnl
                auth_count += 1
                bucket['auth'] += pnl
                bucket['auth_n'] += 1
            else:
                unauthorized_deals.append(rec)
                total_unauth_pnl += pnl
                unauth_count += 1
                bucket['unauth'] += pnl
                bucket['unauth_n'] += 1

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
            application_status = 'approved_with_issues'
        else:
            application_status = 'approved'

        detail['unauthorized_orders'] = len(unauth_orders)
        detail['unauthorized_orders_cancelled'] = cancelled_orders
        detail['unauthorized_positions'] = len(unauth_positions)
        detail['unauthorized_positions_closed'] = closed_positions
        detail['unauthorized_trades'] = len(unauthorized_deals)
        detail['unauthorized_pnl_total'] = round(total_unauth_pnl, 2)
        detail['unaccounted_deficit'] = unaccounted_deficit
        detail['unauthorized_types'] = unauth_types
        detail['application_status'] = application_status

        print(f"  │ Authorized closed   : {auth_count} (P&L ${total_auth_pnl:+.2f})")
        print(f"  │ Unauthorized closed : {len(unauthorized_deals)} "
              f"(P&L ${total_unauth_pnl:+.2f})")
        print(f"  │ Unauthorized orders : {len(unauth_orders)} "
              f"(cancelled {cancelled_orders})")
        print(f"  │ Unauthorized pos.   : {len(unauth_positions)} "
              f"(closed {closed_positions})")
        if expected_balance is not None and mt5_balance_now is not None:
            print(f"  │ Expected balance    : ${expected_balance:.2f}")
            print(f"  │ MT5 balance         : ${mt5_balance_now:.2f}")
            if unaccounted_deficit > 0.01:
                print(f"  │ 🚫 Unaccounted deficit: ${unaccounted_deficit:.2f}")
        if any_unauthorized:
            print(f"  │ Status              : ⚠️ UNAUTHORIZED — {', '.join(unauth_types)}")
        else:
            print(f"  │ Status              : ✅ clean")

        # ==================================================================
        # SECTION 5b — PER-DAY balance_log WRITE
        # ==================================================================
        today = lagos_today_str()
        exec_start_str = None
        if execution_start_date:
            for fmt in ("%Y-%m-%d", "%B %d, %Y", "%Y/%m/%d",
                        "%Y-%m-%d %H:%M:%S"):
                try:
                    exec_start_str = datetime.strptime(
                        str(execution_start_date), fmt
                    ).strftime("%Y-%m-%d")
                    break
                except Exception:
                    continue

        if not exec_start_str:
            exec_start_str = today
        if exec_start_str > today:
            exec_start_str = today

        running_balance = float(broker_balance or 0.0)

        days_written = 0
        last_action = None

        print(f"\n  📅 BALANCE_LOG HISTORY WRITE — {exec_start_str} → {today}")
        print(f"     ├─ Anchor (execution-start broker_balance): ${running_balance:.2f}")
        print(f"     ├─ Days with deals in window              : {len(per_day)}")
        print(f"     └─ Days to write                          : "
              f"{len(list(lagos_daterange(exec_start_str, today)))}")

        for day_key in lagos_daterange(exec_start_str, today):
            bucket = per_day.get(day_key, {
                'auth': 0.0, 'unauth': 0.0,
                'auth_n': 0, 'unauth_n': 0,
                'records': [],
            })

            day_open = running_balance
            day_auth = float(bucket['auth'])
            day_unauth = float(bucket['unauth'])

            if day_key == today and mt5_balance_now is not None:
                day_close = float(mt5_balance_now)
            else:
                day_close = day_open + day_auth + day_unauth

            existing_row = balance_log_fetch_day(
                investor_id, sub_account_id, day_key)
            existing_withdrawals = _coerce_float(
                _raw_first_key(existing_row, 'day_unauthorized_withdrawals'),
                default=0.0,
            ) or 0.0

            day_unusual = (bucket['unauth_n'] > 0)

            ok, action = balance_log_upsert(
                investor_id, sub_account_id, day_key,
                day_start_balance=day_open,
                auth_pnl=day_auth,
                unauth_pnl=day_unauth,
                unauth_withdrawals=existing_withdrawals,
                closing_balance=day_close,
                unusual=day_unusual,
                auth_count=bucket['auth_n'],
                unauth_count=bucket['unauth_n'],
            )

            marker = ''
            if day_key == today:
                marker = '  ← today'
            elif bucket['auth_n'] + bucket['unauth_n'] > 0:
                marker = f"  ({bucket['auth_n']+bucket['unauth_n']} deal(s))"

            if ok:
                days_written += 1
                last_action = action
                print(f"     │ {day_key}: open=${day_open:.2f} "
                      f"auth=${day_auth:+.2f} unauth=${day_unauth:+.2f} "
                      f"close=${day_close:.2f} [{action}]{marker}")
            else:
                print(f"     │ {day_key}: ⚠️ upsert failed{marker}")

            running_balance = day_close

        detail['balance_log_action'] = last_action
        detail['balance_log_days_written'] = days_written
        print(f"     └─ {days_written} row(s) written to balance_log")

        # -------- notify if any violation --------
        if any_unauthorized:
            notif_count = 0

            # 1) INVESTOR side — contract_notifications
            notif_count += notify_investor_unauthorized(
                investor_id=investor_id,
                sub_account_id=sub_account_id,
                investor_email=investor_email,
                main_account_id=main_account_id,
            )

            # 2) Register for the aggregated owner-side alert
            _register_programme_violator(
                programme_id=programme_id,
                programme_name=programme_name,
                investor_id=investor_id,
                sub_account_id=sub_account_id,
                total_unauth_pnl=total_unauth_pnl,
                unauth_types=unauth_types,
            )

            detail['notifications_sent'] = notif_count

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
            stats['unauthorized_orders_cancelled'] += detail.get('unauthorized_orders_cancelled', 0)
            stats['unauthorized_positions_found'] += detail.get('unauthorized_positions', 0)
            stats['unauthorized_positions_closed'] += detail.get('unauthorized_positions_closed', 0)
            stats['unauthorized_trades_found'] += detail.get('unauthorized_trades', 0)
            if detail.get('unaccounted_deficit', 0.0) > 0.01:
                stats['unaccounted_deficits_found'] += 1
            if detail.get('unauthorized_types'):
                stats['investors_with_unauthorized'] += 1
            stats['balance_log_rows_written'] += detail.get('balance_log_days_written', 0)
            stats['notifications_queued'] += detail.get('notifications_sent', 0)

            if not unauthorized_alert.get('programme_id'):
                unauthorized_alert['programme_id'] = programme_id
                unauthorized_alert['investor_id'] = investor_id
                unauthorized_alert['sub_account_id'] = sub_account_id
                unauthorized_alert['investor_authorized_tradeids'] = set()
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

    # ==================================================================
    # SECTION 7 — AGGREGATED PROGRAMME-OWNER NOTIFICATIONS
    # ==================================================================
    if programme_violators:
        print(f"\n{'='*10} 📣 AGGREGATED PROGRAMME-OWNER NOTIFICATIONS {'='*10}")
        for pid, entry in programme_violators.items():
            programme_name = entry.get('programme_name') or f"programme {pid}"
            violators = entry.get('violators') or []
            if not violators:
                continue

            # Resolve owner email HERE, at aggregation time, robustly.
            owner_email, resolved_name, owner_userid = programme_fetch_owner_identity(pid)
            if resolved_name and not entry.get('programme_name'):
                programme_name = resolved_name

            print(f"  │ Programme {pid} ('{programme_name}') — "
                  f"{len(violators)} violator(s) | owner={owner_email or '—'}")

            sent = notify_programme_owner_violators(
                programme_id=pid,
                programme_name=programme_name,
                owner_email=owner_email,
                violators=violators,
            )
            stats['notifications_queued'] += sent

    print(f"\n{'='*10} 🔍 AUTHORIZED-ACTIONS AUDIT SUMMARY (DB) {'='*10}")
    print(f"  Investors processed        : {stats['investors_processed']}")
    print(f"  Investors with unauthorized: {stats['investors_with_unauthorized']}")
    print(f"  Unauthorized orders        : {stats['unauthorized_orders_found']}")
    print(f"  Unauthorized orders cancelled: {stats['unauthorized_orders_cancelled']}")
    print(f"  Unauthorized positions     : {stats['unauthorized_positions_found']}")
    print(f"  Unauthorized positions closed: {stats['unauthorized_positions_closed']}")
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
               AND (orderstatus = 'pending'
                    OR orderstatus IS NULL
                    OR orderstatus = '')
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
                order_magic = getattr(order, 'magic', None)

                sys_res = system_analysis_results.get(sym)
                if sys_res is None:
                    print(f"  ❌ {sym} ticket#{order_ticket}: symbol not in system analysis — DELETE")
                    try:
                        req = {"action": mt5.TRADE_ACTION_REMOVE, "order": order_ticket}
                        res = mt5_order_send(req)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            cancelled += 1
                            if order_magic is not None and int(order_magic) > 0:
                                row_id = None
                                for r in pending_rows:
                                    if _coerce_int(_raw_first_key(r, 'tradeid')) == int(order_magic):
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
                        if order_magic is not None and int(order_magic) > 0:
                            row_id = None
                            for r in pending_rows:
                                if _coerce_int(_raw_first_key(r, 'tradeid')) == int(order_magic):
                                    row_id = _coerce_int(_raw_first_key(r, 'id'))
                                    break
                            if row_id is not None:
                                delete_trade_row(row_id)
                                rows_deleted += 1
                except Exception as e:
                    print(f"     delete error: {e}")

        # ------------------------------------------------------------------
        # STEP 4: restore MT5 orders not in DB (order.magic → tradeid)
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
                order_magic = getattr(order, 'magic', None)
                if order_magic is None or int(order_magic) <= 0:
                    continue
                if int(order_magic) in existing_tradeids:
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
                    tradeid=int(order_magic),
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
                    existing_tradeids.add(int(order_magic))
                    print(f"  ♻️ Restored MT5 order magic={order_magic} ({sym} {ordertype}) "
                          f"→ programme_trades as tradeid={order_magic}, vol={vol:.2f}")

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
#  CALCULATE INVESTOR SYMBOLS ORDERS — DB version
#
#  Source of truth for R:R:  signals_provider_interest (programme-scoped)
#      interest_risk_reward       -> numeric R:R ratio (e.g. 8 means 1:8)
#      interest_risk_reward_type  -> string classifier:
#
#          'custom minimum risk reward'   minimum floor
#              - compute current R:R from entry to takeprofit
#              - if current < value  -> recalculate volume so R:R == value
#              - if current >= value -> NO change
#
#          'fixed risk reward'            exact rewrite
#              - compute current R:R
#              - if current != value -> recalculate volume so R:R == value
#
#          'custom fixed risk reward'     do nothing
#              - no recalculation at all
#              - EXCEPT: if current R:R < 1.0, force recalc to R:R == 1.0
#
#  The function ALSO syncs the per-investor authorisation snapshot:
#  it copies interest_risk_reward + interest_risk_reward_type down to each
#  investor row (same values the signals dashboard uses) so downstream
#  consumers see a consistent view.
#
#  Per row it:
#    * reads entry, takeprofit, stoploss (stoploss is required to solve
#      for volume: volume = (|entry - tp| / (rr * |entry - sl|)) * base_volume)
#    * computes the R:R of the CURRENT record
#    * applies the classifier rules above
#    * writes back the new volume (and nothing else) via
#      UPDATE programme_trades SET volume = %s WHERE id = %s
#
#  It is PROGRAMME-SCOPED for config, INVESTOR-SCOPED for writes.
#  It does NOT touch MT5. It does NOT read or write JSON. It only touches
#  the DB.
# ==============================================================================

def _validate_single_order_margin_for_calc(order, side, desired_volume, buffer_pct=10.0):
    """
    Module-level wrapper around MT5 margin validation for the calculate
    stage. Returns (final_volume, margin_used, free_margin, allowed,
    shrunk, reason). Falls back to a no-op "allowed" result when the
    account is unavailable, so the calculate stage never blocks on a
    missing MT5 connection.
    """
    acc = mt5_account_info()
    if acc is None:
        return desired_volume, 0.0, 0.0, True, False, "no_account_info"
    symbol = order.get("symbol")
    entry = order.get("entry")
    if not symbol or entry is None:
        return desired_volume, 0.0, 0.0, False, False, "missing_data"
    si = mt5_symbol_info(symbol)
    if not si:
        return desired_volume, 0.0, 0.0, False, False, "no_symbol_info"
    try:
        free_margin = float(acc.margin_free)
    except Exception:
        return desired_volume, 0.0, 0.0, True, False, "no_free_margin_field"
    allowed = free_margin * (1.0 - buffer_pct / 100.0)
    if allowed <= 0:
        return 0.0, 0.0, free_margin, False, True, "no_free_margin"
    mt5_type = 0 if side == "buy" else 1
    try:
        margin = mt5_order_calc_margin(mt5_type, symbol, float(desired_volume), float(entry))
    except Exception:
        margin = None
    if margin is None or margin <= 0:
        return desired_volume, 0.0, free_margin, True, False, "margin_calc_failed"
    if margin <= allowed:
        return desired_volume, float(margin), free_margin, True, False, "fits"
    # shrink linearly
    step = float(getattr(si, 'volume_step', 0.01) or 0.01)
    min_vol = float(getattr(si, 'volume_min', 0.01) or 0.01)
    ratio = allowed / margin
    raw = max(min_vol, desired_volume * ratio)
    steps = round(raw / step) if step > 0 else 0
    shrunk_vol = max(min_vol, round(steps * step, 2))
    try:
        shrunk_margin = mt5_order_calc_margin(mt5_type, symbol, shrunk_vol, float(entry))
    except Exception:
        shrunk_margin = None
    if shrunk_margin is None or shrunk_margin > allowed:
        return 0.0, 0.0, free_margin, False, True, "cannot_fit_min_volume"
    return shrunk_vol, float(shrunk_margin), free_margin, True, True, "shrunk_to_fit"

# ==============================================================================
#  CALCULATE INVESTOR SYMBOLS ORDERS — DB version
#
#  Source of truth for R:R:  signals_provider_interest (programme-scoped)
#      interest_risk_reward       -> numeric R:R ratio (e.g. 8 means 1:8)
#      interest_risk_reward_type  -> string classifier:
#
#          'custom minimum risk reward'   minimum floor
#              - compute current R:R from entry to takeprofit
#              - if current < value  -> recalculate volume so R:R == value
#              - if current >= value -> NO change
#
#          'fixed risk reward'            exact rewrite
#              - compute current R:R
#              - if current != value -> recalculate volume so R:R == value
#
#          'custom fixed risk reward'     do nothing
#              - no recalculation at all
#              - EXCEPT: if current R:R < 1.0, force recalc to R:R == 1.0
#
#  The function ALSO syncs the per-investor authorisation snapshot:
#  it copies interest_risk_reward + interest_risk_reward_type down to each
#  investor row (same values the signals dashboard uses) so downstream
#  consumers see a consistent view.
#
#  ACTIONABLE-ROW PREDICATE (must match every other stage):
#      orderstatus = 'pending'  OR  orderstatus IS NULL  OR  orderstatus = ''
#
#  NO files, NO JSON, NO local folders. Pure DB.
# ==============================================================================
def calculate_investor_symbols_orders_db(inv_db_id=None):
    print(f"\n{'='*10} 📐 CALCULATE INVESTOR SYMBOLS ORDERS (DB) {'='*10}")

    stats = {
        'investor_id': inv_db_id if inv_db_id else 'all',
        'programmes_processed': 0,
        'investors_processed': 0,
        'rows_seen': 0,
        'rows_calculated': 0,
        'rows_skipped': 0,
        'rows_synced_only': 0,
        'rows_volume_seeded': 0,
        'rows_risk_resized': 0,
        'rows_rr_resized': 0,
        'rows_tp_synthesized': 0,
        'errors': [],
        'details': [],
        'processing_success': False,
    }

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _norm_rr_type(raw):
        """Canonicalise any stored risk_reward_type into one of three keys."""
        if raw is None:
            return 'fixed risk reward'
        s = str(raw).strip().lower()
        s = s.replace('_', ' ').replace('-', ' ')
        s = ' '.join(s.split())
        if not s:
            return 'fixed risk reward'
        for filler in (' and ', ' & ', ' + ', '  and  '):
            s = s.replace(filler, ' ')
        s = ' '.join(s.split())

        aliases = {
            'custom fixed risk reward':     'custom fixed risk reward',
            'customfixed risk reward':      'custom fixed risk reward',
            'custom fixed':                 'custom fixed risk reward',
            'customfixed':                  'custom fixed risk reward',
            'fixed custom':                 'custom fixed risk reward',
            'custom risk reward':           'custom fixed risk reward',

            'custom minimum risk reward':   'custom minimum risk reward',
            'customminimum risk reward':    'custom minimum risk reward',
            'custom minimum':               'custom minimum risk reward',
            'customminimum':                'custom minimum risk reward',
            'minimum risk reward':          'custom minimum risk reward',
            'minimum':                      'custom minimum risk reward',
            'min':                          'custom minimum risk reward',
            'floor':                        'custom minimum risk reward',

            'fixed risk reward':            'fixed risk reward',
            'fixedrisk reward':             'fixed risk reward',
            'fixed':                        'fixed risk reward',
            'fixed rr':                     'fixed risk reward',
            'exact':                        'fixed risk reward',
            'exact risk reward':            'fixed risk reward',
        }
        if s in aliases:
            return aliases[s]

        has_custom = 'custom' in s
        has_min    = ('minimum' in s) or ('min' in s.split()) or ('floor' in s)
        has_fixed  = ('fixed' in s)

        if has_custom and has_min and not has_fixed:
            return 'custom minimum risk reward'
        if has_custom and has_fixed:
            return 'custom fixed risk reward'
        if has_fixed:
            return 'fixed risk reward'
        if has_min:
            return 'custom minimum risk reward'
        return s

    def _fetch_programme_rr(programme_id):
        row = db_fetch_one(
            """
            SELECT id, risk_reward, risk_reward_type
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
            return None, None, None
        rr_val  = _coerce_float(_raw_first_key(row, 'risk_reward'), default=None)
        rr_type = _raw_first_key(row, 'risk_reward_type')
        if rr_val is None or rr_val <= 0:
            return None, None, row
        return float(rr_val), rr_type, row

    def _fetch_programme_default_risk_brackets(programme_id):
        rows = db_fetch_all(
            """
            SELECT from_balance_range, to_balance_range, risk_amount
              FROM accountmanagement_balance_default_risk
             WHERE programme_id = %s
             ORDER BY from_balance_range ASC, id ASC
            """,
            [programme_id], timeout=10.0, quiet=True,
        )
        out = []
        for r in rows:
            try:
                lo = _coerce_float(_raw_first_key(r, 'from_balance_range'), default=None)
                hi = _coerce_float(_raw_first_key(r, 'to_balance_range'),   default=None)
                rk = _coerce_float(_raw_first_key(r, 'risk_amount'),        default=None)
            except Exception:
                continue
            if lo is None or rk is None:
                continue
            if hi is None or hi <= 0:
                hi = float('inf')
            out.append({'from': float(lo), 'to': float(hi), 'risk': float(rk)})
        return out

    def _resolve_default_risk_for_balance(brackets, balance):
        if not brackets or balance is None:
            return None, None
        for b in brackets:
            if b['from'] <= balance <= b['to']:
                return b['risk'], b
        below = [b for b in brackets if b['from'] <= balance]
        if below:
            chosen = below[-1]
            return chosen['risk'], chosen
        return brackets[0]['risk'], brackets[0]

    def _compute_current_rr(entry, sl, tp):
        if entry is None or sl is None or tp is None:
            return None, None, None
        risk   = abs(float(entry) - float(sl))
        reward = abs(float(tp) - float(entry))
        if risk <= 0:
            return None, risk, reward
        return reward / risk, risk, reward

    def _round_volume_to_symbol(volume, symbol_info):
        if volume is None or volume <= 0:
            return 0.0
        step    = float(getattr(symbol_info, 'volume_step', 0.01) or 0.01)
        min_vol = float(getattr(symbol_info, 'volume_min', 0.01) or 0.01)
        max_vol = float(getattr(symbol_info, 'volume_max', 100.0) or 100.0)
        if step <= 0:
            step = 0.01
        steps = round(volume / step)
        return max(min_vol, min(max_vol, round(steps * step, 2)))

    def _min_volume_for_symbol(symbol_info):
        if symbol_info is None:
            return 0.01
        try:
            v = float(getattr(symbol_info, 'volume_min', 0.01) or 0.01)
            return v if v > 0 else 0.01
        except Exception:
            return 0.01

    def _price_digits(symbol_info, tick_size):
        try:
            if symbol_info is not None and hasattr(symbol_info, 'digits'):
                d = int(symbol_info.digits)
                if d >= 0:
                    return d
        except Exception:
            pass
        try:
            ts = float(tick_size) if tick_size else 0.00001
            if ts <= 0:
                ts = 0.00001
            if ts < 1:
                return len(f"{ts:.10f}".rstrip('0').split('.')[-1])
        except Exception:
            pass
        return 5

    def _synthesize_tp(entry, sl, rr_value, is_buy, digits):
        if entry is None or sl is None or rr_value is None or rr_value <= 0:
            return None
        try:
            entry_f = float(entry)
            sl_f    = float(sl)
            risk_dist = abs(entry_f - sl_f)
            if risk_dist <= 0:
                return None
            reward_dist = risk_dist * float(rr_value)
            tp = (entry_f + reward_dist) if is_buy else (entry_f - reward_dist)
            return round(tp, digits)
        except Exception:
            return None

    def _risk_per_lot(entry, sl, symbol_info):
        if entry is None or sl is None or symbol_info is None:
            return 0.0
        try:
            price_dist = abs(float(entry) - float(sl))
            contract   = float(getattr(symbol_info, 'trade_contract_size', 1.0) or 1.0)
            return price_dist * contract
        except Exception:
            return 0.0

    def _risk_driven_volume(target_risk, risk_per_lot, symbol_info):
        if target_risk is None or target_risk <= 0:
            return None
        if risk_per_lot is None or risk_per_lot <= 0:
            return None
        try:
            raw = float(target_risk) / float(risk_per_lot)
        except Exception:
            return None
        return _round_volume_to_symbol(raw, symbol_info)

    def _rr_driven_volume(current_volume, current_rr, target_rr, symbol_info):
        if current_rr is None or current_rr <= 0 or target_rr <= 0:
            return None
        try:
            scale = current_rr / float(target_rr)
            raw   = float(current_volume) * scale
        except Exception:
            return None
        return _round_volume_to_symbol(raw, symbol_info)

    # ==================================================================
    # TOP-LEVEL ENUMERATION (VPS-scoped)
    # ==================================================================
    print("\n" + "─"*80)
    print(" 📁 LOADING INVESTOR JOBS FROM DB (VPS-scoped)")
    print("─"*80)

    local_ip = get_local_ip()
    if not local_ip:
        print(" ⚠️ Could not determine local IP")
        stats['errors'].append('local IP unknown')
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
            return stats
    else:
        jobs = all_jobs

    print(f" │ Loaded {len(jobs)} investor job(s) from DB")
    print("─"*80)

    programme_rr_cache      = {}
    programme_bracket_cache = {}
    symbol_info_cache       = {}

    def get_symbol_info(sym):
        si = symbol_info_cache.get(sym)
        if si is None:
            si = mt5_symbol_info(sym)
            if si is None:
                mt5_symbol_select(sym, True)
                si = mt5_symbol_info(sym)
            symbol_info_cache[sym] = si
        return si

    def _current_balance():
        acc = mt5_account_info()
        if acc is None:
            return None
        try:
            return float(acc.balance)
        except Exception:
            return None

    # ==================================================================
    # PER-INVESTOR PIPELINE
    # ==================================================================
    for job in jobs:
        investor_id    = job.get('investor_id')
        sub_account_id = job.get('sub_account_id')
        programme_id   = job.get('programme_id')
        programme_name = job.get('programme_name') or f"programme_{programme_id}"

        if investor_id is None or sub_account_id is None or programme_id is None:
            stats['rows_skipped'] += 1
            continue

        cfg = programme_rr_cache.get(programme_id)
        if cfg is None:
            rr_val, rr_type, raw_row = _fetch_programme_rr(programme_id)
            cfg = {
                'rr_value':     rr_val,
                'rr_type_raw':  rr_type,
                'rr_type_norm': _norm_rr_type(rr_type),
                'raw_row':      raw_row,
            }
            programme_rr_cache[programme_id] = cfg
            stats['programmes_processed'] += 1

        brackets = programme_bracket_cache.get(programme_id)
        if brackets is None:
            brackets = _fetch_programme_default_risk_brackets(programme_id)
            programme_bracket_cache[programme_id] = brackets

        print(f"\n{'─'*72}")
        print(f" 📐 Investor {investor_id} (sub {sub_account_id}) | "
              f"programme '{programme_name}' (id={programme_id})")
        print(f"{'─'*72}")
        print(f"  │ Programme R:R value : "
              f"{'1:' + str(cfg['rr_value']) if cfg['rr_value'] is not None else '—'}")
        print(f"  │ Programme R:R type  : {cfg['rr_type_raw'] or '—'}")
        print(f"  │ Normalised type     : '{cfg['rr_type_norm']}'")
        print(f"  │ Default risk brackets: {len(brackets)}")

        if cfg['rr_value'] is None:
            print(f"  │ ⚠️ No usable signals_provider_interest.risk_reward — "
                  f"skipping investor")
            stats['rows_skipped'] += 1
            continue

        balance = _current_balance()
        target_risk     = None
        matched_bracket = None
        if balance is not None and brackets:
            target_risk, matched_bracket = _resolve_default_risk_for_balance(brackets, balance)
        print(f"  │ Live MT5 balance    : "
              f"{'$' + format(balance, '.2f') if balance is not None else '—'}")
        if matched_bracket is not None and target_risk is not None:
            print(f"  │ Default risk applied: ${target_risk:.2f} "
                  f"(bracket {matched_bracket['from']:.2f} - {matched_bracket['to']:.2f})")
        else:
            print(f"  │ Default risk applied: — (no bracket available)")

        # ------------------------------------------------------------------
        # ACTIONABLE ROWS
        # Same predicate as place_usd_orders_db, chunk, martingale:
        #   orderstatus = 'pending'  OR  IS NULL  OR  = ''
        # ------------------------------------------------------------------
        rows = db_fetch_all(
            """
            SELECT id, tradeid, userid, programmeid,
                   investor_id, investor_sub_account_id,
                   symbol, ordertype, orderstatus, timeframe,
                   entry, stoploss, takeprofit, volume,
                   trade_risk_reward,
                   interest_risk_reward, interest_risk_reward_type
              FROM programme_trades
             WHERE userid = %s
               AND programmeid = %s
               AND investor_id = %s
               AND investor_sub_account_id = %s
               AND (orderstatus = 'pending'
                    OR orderstatus IS NULL
                    OR orderstatus = '')
             ORDER BY id ASC
            """,
            [investor_id, programme_id, investor_id, sub_account_id],
            timeout=15.0, quiet=True,
        )

        stats['rows_seen'] += len(rows)
        stats['investors_processed'] += 1

        if not rows:
            print(f"  │ ℹ️ No actionable rows for this investor")
            continue

        print(f"  │ Actionable rows     : {len(rows)}")

        for r in rows:
            row_id  = _coerce_int(_raw_first_key(r, 'id'))
            tradeid = _coerce_int(_raw_first_key(r, 'tradeid'))
            sym     = (_raw_first_key(r, 'symbol') or '').strip()
            ot      = (_raw_first_key(r, 'ordertype') or '').strip().lower()
            entry   = _coerce_float(_raw_first_key(r, 'entry'), default=None)
            sl      = _coerce_float(_raw_first_key(r, 'stoploss'), default=None)
            tp      = _coerce_float(_raw_first_key(r, 'takeprofit'), default=None)
            cur_vol = _coerce_float(_raw_first_key(r, 'volume'), default=None)

            if row_id is None:
                stats['rows_skipped'] += 1
                continue

            try:
                db_execute(
                    """
                    UPDATE programme_trades
                       SET interest_risk_reward      = %s,
                           interest_risk_reward_type = %s
                     WHERE id = %s
                    """,
                    [cfg['rr_value'], cfg['rr_type_raw'], row_id],
                    timeout=10.0, quiet=True,
                )
                stats['rows_synced_only'] += 1
            except Exception:
                pass

            if not sym or entry is None or sl is None:
                stats['rows_skipped'] += 1
                print(f"  │ ⚠️ row {row_id}: missing symbol/entry/sl — skipped")
                continue

            si = get_symbol_info(sym)
            if si is None:
                stats['rows_skipped'] += 1
                print(f"  │ ⚠️ row {row_id}: no symbol_info for {sym} — skipped")
                continue

            is_buy = 'buy' in ot

            # ---------- 1. SYNTHESIZE TP IF MISSING ----------
            tp_synthesized = False
            if tp is None:
                synth_rr = float(cfg['rr_value'])
                digits   = _price_digits(si, getattr(si, 'trade_tick_size', None))
                new_tp   = _synthesize_tp(entry, sl, synth_rr, is_buy, digits)

                if new_tp is None:
                    stats['rows_skipped'] += 1
                    print(f"  │ ⚠️ row {row_id}: could not synthesize TP "
                          f"(entry={entry}, sl={sl}, rr=1:{synth_rr})")
                    continue

                try:
                    db_execute(
                        "UPDATE programme_trades SET takeprofit = %s WHERE id = %s",
                        [new_tp, row_id], timeout=10.0, quiet=True,
                    )
                except Exception:
                    pass

                tp = new_tp
                tp_synthesized = True
                stats['rows_tp_synthesized'] += 1
                print(f"  │ 🎯 row {row_id}: TP was NULL — synthesized to "
                      f"{tp}  (programme R:R = 1:{synth_rr}, is_buy={is_buy})")

            # ---------- 2. SELF-HEALING BASELINE VOLUME ----------
            vol_seeded = False
            if cur_vol is None or cur_vol <= 0:
                cur_vol = _min_volume_for_symbol(si)
                vol_seeded = True
                stats['rows_volume_seeded'] += 1
                print(f"  │ 🩹 row {row_id}: volume was NULL — seeding from "
                      f"{sym} volume_min = {cur_vol}")

            # ---------- 3. RISK-DRIVEN RESIZE ----------
            risk_resized = False
            if target_risk is not None:
                rpl = _risk_per_lot(entry, sl, si)
                if rpl > 0:
                    risk_vol = _risk_driven_volume(target_risk, rpl, si)
                    if risk_vol is not None and risk_vol > 0:
                        if abs(risk_vol - cur_vol) > 1e-9:
                            risk_resized = True
                            stats['rows_risk_resized'] += 1
                        cur_vol = risk_vol

            # ---------- 4. R:R CLASSIFIER ----------
            current_rr, risk_dist, reward_dist = _compute_current_rr(entry, sl, tp)
            if current_rr is None:
                if risk_resized or vol_seeded or tp_synthesized:
                    ok_w, _, _ = db_execute(
                        "UPDATE programme_trades SET volume = %s WHERE id = %s",
                        [round(float(cur_vol), 8), row_id],
                        timeout=15.0, quiet=True,
                    )
                    if ok_w:
                        stats['rows_calculated'] += 1
                        print(f"  │    ✅ row {row_id}: volume written "
                              f"({cur_vol:.2f}) — risk-sized only")
                    else:
                        stats['rows_skipped'] += 1
                        print(f"  │    ✗ row {row_id}: write failed")
                else:
                    stats['rows_skipped'] += 1
                    print(f"  │    ℹ️ row {row_id}: risk_dist=0 — no change")
                continue

            target_rr = float(cfg['rr_value'])
            rr_type   = cfg['rr_type_norm']

            decision = 'noop'
            target_for_calc = None
            reason = ''

            if rr_type == 'custom minimum risk reward':
                if current_rr < target_rr - 1e-9:
                    decision = 'raise'
                    target_for_calc = target_rr
                    reason = f"custom minimum floor: current 1:{round(current_rr, 4)} < 1:{target_rr}"
                else:
                    decision = 'noop'
                    reason = f"custom minimum floor: current 1:{round(current_rr, 4)} >= 1:{target_rr} — no change"
            elif rr_type == 'fixed risk reward':
                if abs(current_rr - target_rr) > 1e-9:
                    decision = 'rewrite'
                    target_for_calc = target_rr
                    reason = f"fixed: current 1:{round(current_rr, 4)} != 1:{target_rr}"
                else:
                    decision = 'noop'
                    reason = f"fixed: current already equals 1:{target_rr}"
            elif rr_type == 'custom fixed risk reward':
                if current_rr < 1.0 - 1e-9:
                    decision = 'raise'
                    target_for_calc = 1.0
                    reason = f"custom fixed: current 1:{round(current_rr, 4)} < 1:1 — forcing 1:1"
                else:
                    decision = 'noop'
                    reason = f"custom fixed: current 1:{round(current_rr, 4)} — no change by design"
            else:
                if abs(current_rr - target_rr) > 1e-9:
                    decision = 'rewrite'
                    target_for_calc = target_rr
                    reason = f"unrecognised type '{rr_type}' -> treating as fixed; current 1:{round(current_rr, 4)} != 1:{target_rr}"
                else:
                    decision = 'noop'
                    reason = f"unrecognised type '{rr_type}' -> treating as fixed; current already 1:{target_rr}"

            print(f"\n  │ 📄 row {row_id} (tradeid={tradeid}, {sym} {ot.upper()})")
            print(f"  │    entry={entry}  sl={sl}  tp={tp}"
                  f"{'  (synthesized)' if tp_synthesized else ''}")
            print(f"  │    baseline vol      : {cur_vol}"
                  f"{'  (seeded)' if vol_seeded else ''}"
                  f"{'  (risk-resized)' if risk_resized else ''}")
            print(f"  │    current R:R       = 1:{round(current_rr, 4)}")
            print(f"  │    target R:R        = 1:{target_rr}")
            print(f"  │    type              = '{rr_type}'")
            print(f"  │    decision          : {decision.upper()} — {reason}")

            # ---------- 5. APPLY R:R REWRITE IF NEEDED ----------
            final_vol = cur_vol
            rr_resized = False
            if decision != 'noop':
                new_vol = _rr_driven_volume(
                    current_volume=cur_vol,
                    current_rr=current_rr,
                    target_rr=target_for_calc,
                    symbol_info=si,
                )
                if new_vol is not None and new_vol > 0:
                    if abs(new_vol - cur_vol) > 1e-9:
                        rr_resized = True
                        stats['rows_rr_resized'] += 1
                    final_vol = new_vol

            if (not risk_resized) and (not rr_resized) and (not vol_seeded) and (not tp_synthesized):
                stats['rows_skipped'] += 1
                print(f"  │    ℹ️ no change")
                continue

            # ---------- 6. MARGIN GUARD (best effort) ----------
            order_for_margin = {"symbol": sym, "entry": entry, "ordertype": ot}
            side = "buy" if is_buy else "sell"
            try:
                valid_vol, margin, free_margin, ok, shrunk, mreason = \
                    _validate_single_order_margin_for_calc(
                        order_for_margin, side, final_vol, buffer_pct=10.0
                    )
                if not ok or valid_vol <= 0:
                    stats['rows_skipped'] += 1
                    print(f"  │    ⚠️ margin check failed ({mreason}) — skipped")
                    continue
                if shrunk:
                    print(f"  │    🔻 margin shrink: {final_vol:.2f} -> {valid_vol:.2f}")
                    final_vol = valid_vol
            except NameError:
                pass

            # ---------- 7. WRITE VOLUME ----------
            ok_w, _, _ = db_execute(
                "UPDATE programme_trades SET volume = %s WHERE id = %s",
                [round(float(final_vol), 8), row_id],
                timeout=15.0, quiet=True,
            )
            if not ok_w:
                stats['rows_skipped'] += 1
                print(f"  │    ✗ volume write failed for row {row_id}")
                continue

            stats['rows_calculated'] += 1
            print(f"  │    ✅ final volume    = {final_vol}"
                  f"  (risk target ${target_risk if target_risk is not None else '—'})")

            stats['details'].append({
                'row_id':          row_id,
                'tradeid':         tradeid,
                'symbol':          sym,
                'ordertype':       ot,
                'old_volume':      cur_vol,
                'final_volume':    float(final_vol),
                'current_rr':      round(current_rr, 6),
                'target_rr':       float(target_for_calc) if target_for_calc is not None else None,
                'rr_type':         rr_type,
                'decision':        decision,
                'volume_seeded':   vol_seeded,
                'risk_resized':    risk_resized,
                'rr_resized':      rr_resized,
                'tp_synthesized':  tp_synthesized,
                'target_risk':     float(target_risk) if target_risk is not None else None,
            })

    # ==================================================================
    # SUMMARY
    # ==================================================================
    print(f"\n{'='*10} 📐 CALCULATE SUMMARY (DB) {'='*10}")
    print(f"  Programmes processed : {stats['programmes_processed']}")
    print(f"  Investors processed  : {stats['investors_processed']}")
    print(f"  Rows seen            : {stats['rows_seen']}")
    print(f"  Rows calculated      : {stats['rows_calculated']}")
    print(f"  Rows synced only     : {stats['rows_synced_only']}")
    print(f"  Rows volume-seeded   : {stats['rows_volume_seeded']}")
    print(f"  Rows risk-resized    : {stats['rows_risk_resized']}")
    print(f"  Rows R:R-resized     : {stats['rows_rr_resized']}")
    print(f"  Rows TP-synthesized  : {stats['rows_tp_synthesized']}")
    print(f"  Rows skipped         : {stats['rows_skipped']}")
    print(f"  Errors               : {len(stats['errors'])}")
    for e in stats['errors']:
        print(f"     • {e}")
    print(f"{'='*10} 🏁 COMPLETE {'='*10}\n")

    stats['processing_success'] = True
    return stats

# ==============================================================================
#  CHUNK ORDERS WITH VOLUME BEYOND MAX — DB version
#
#  SEMANTICS
#  ---------
#  Reads programme_trades rows where orderstatus = 'pending' for the investor
#  (VPS-scoped via fetch_vps_investor_jobs) and, for each row:
#
#    * Looks up the symbol's MT5 volume_max / volume_min / volume_step.
#    * IF volume <= volume_max:
#         -> chunked_pieces is forced to 0 (idempotent).
#         -> volume is NEVER touched.
#    * IF volume > volume_max:
#         -> chunked_pieces = ceil(volume / volume_max).
#         -> volume is NEVER touched.
#         -> No new rows are inserted; no rows are deleted.
#         -> The `volume` column keeps the full original volume. The chunk
#            count is the only thing this stage writes.
#
#  WHY CHUNKED_PIECES AND NOT CHILD ROWS?
#  --------------------------------------
#  The downstream placer (place_usd_orders) reads chunked_pieces and
#  iterates the MT5 submission in `chunked_pieces` pieces of ≤ volume_max
#  each. The DB row remains the single source of truth for the trade; the
#  piece count is metadata.
#
#  GUARANTEES
#  ----------
#  * volume is NEVER updated by this stage.
#  * chunked_pieces is the ONLY field written.
#  * Idempotent: safe to run every cycle.
#  * No JSON. No local folders. No MT5 order submission.
# ==============================================================================

def chunk_orders_with_volume_beyond_max_db(inv_db_id=None):
    """
    DB version of chunk_orders_with_volume_beyond_max_local_version.

    INVESTOR-SCOPED, NOT ID-SCOPED:
        Every pending programme_trades row belonging to the investor
        (matched by investor_id + investor_sub_account_id + programmeid,
        and further guarded by userid) is processed. Row `id` is only
        read so we can write back to the correct row. The `tradeid` is
        NOT used as a unique key — multiple rows may share the same
        tradeid (e.g. tree pieces), and ALL of them are chunked.

    For each pending row:
      * Look up the symbol's MT5 volume_max.
      * If volume > volume_max:
            chunked_pieces = ceil(volume / volume_max)
            volume is NEVER touched.
      * If volume <= volume_max:
            chunked_pieces = 0
            volume is NEVER touched.

    Returns a stats dict.
    """
    import math

    print(f"\n{'='*10} 📦 CHUNKING ORDERS WITH VOLUME BEYOND MAX (DB) {'='*10}")

    stats = {
        'investor_id':          inv_db_id if inv_db_id else 'all',
        'investors_processed':  0,
        'rows_seen':            0,
        'rows_chunked':         0,
        'rows_unchanged':       0,
        'rows_skipped':         0,
        'total_pieces_created': 0,
        'total_volume_chunked': 0.0,
        'errors':               [],
        'details':              [],
        'processing_success':   False,
    }

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _floor_to_step(value, step):
        if step <= 0:
            return value
        try:
            multiples = math.floor(round(value / step, 10))
            return round(multiples * step, 10)
        except Exception:
            return value

    def _ceil_to_step(value, step):
        if step <= 0:
            return value
        try:
            multiples = math.ceil(round(value / step, 10))
            return round(multiples * step, 10)
        except Exception:
            return value

    _symbol_info_cache = {}

    def _get_symbol_info(sym):
        si = _symbol_info_cache.get(sym)
        if si is None:
            si = mt5_symbol_info(sym)
            if si is None:
                mt5_symbol_select(sym, True)
                si = mt5_symbol_info(sym)
            _symbol_info_cache[sym] = si
        return si

    # ------------------------------------------------------------------
    # enumeration (VPS-scoped)
    # ------------------------------------------------------------------
    print("\n" + "─" * 80)
    print(" 📁 LOADING INVESTOR JOBS FROM DB (VPS-scoped)")
    print("─" * 80)

    local_ip = get_local_ip()
    if not local_ip:
        print(" ⚠️ Could not determine local IP")
        stats['errors'].append('local IP unknown')
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
            return stats
    else:
        jobs = all_jobs

    print(f" │ Loaded {len(jobs)} investor job(s) from DB")
    print("─" * 80)

    # ------------------------------------------------------------------
    # per-investor processing
    # ------------------------------------------------------------------
    for job in jobs:
        investor_id    = job.get('investor_id')
        sub_account_id = job.get('sub_account_id')
        programme_id   = job.get('programme_id')
        programme_name = job.get('programme_name') or f"programme_{programme_id}"

        if investor_id is None or sub_account_id is None or programme_id is None:
            stats['rows_skipped'] += 1
            continue

        print(f"\n{'─'*72}")
        print(f" 📦 Investor {investor_id} (sub {sub_account_id}) | "
              f"programme '{programme_name}' (id={programme_id})")
        print(f"{'─'*72}")

        # ---- fetch ALL pending rows for THIS investor (investor-scoped, NOT id-scoped) ----
        # Multiple rows may share the same tradeid — every one of them is
        # processed. `userid` is included as the ownership guard.
        rows = db_fetch_all(
            """
            SELECT id, tradeid, userid, programmeid,
                   investor_id, investor_sub_account_id,
                   symbol, ordertype, orderstatus,
                   volume, chunked_pieces
              FROM programme_trades
             WHERE investor_id = %s
               AND investor_sub_account_id = %s
               AND programmeid = %s
               AND userid = %s
               AND (orderstatus = 'pending'
                    OR orderstatus IS NULL
                    OR orderstatus = '')
             ORDER BY id ASC
            """,
            [investor_id, sub_account_id, programme_id, investor_id],
            timeout=15.0, quiet=True,
        )

        stats['rows_seen'] += len(rows)
        stats['investors_processed'] += 1

        if not rows:
            print(f"  │ ℹ️ No pending rows for this investor")
            continue

        print(f"  │ Pending rows: {len(rows)}")

        investor_chunked = 0
        investor_unchanged = 0
        investor_skipped = 0
        investor_pieces = 0
        investor_volume = 0.0

        for r in rows:
            row_id    = _coerce_int(_raw_first_key(r, 'id'))
            tradeid   = _coerce_int(_raw_first_key(r, 'tradeid'))
            sym       = (_raw_first_key(r, 'symbol') or '').strip()
            ot        = (_raw_first_key(r, 'ordertype') or '').strip().lower()
            volume    = _coerce_float(_raw_first_key(r, 'volume'), default=None)
            existing_pieces = _coerce_int(_raw_first_key(r, 'chunked_pieces')) or 0

            if row_id is None:
                stats['rows_skipped'] += 1
                investor_skipped += 1
                continue

            if not sym or volume is None or volume <= 0:
                # Nothing to chunk — mark chunked_pieces = 0
                if existing_pieces != 0:
                    db_execute(
                        "UPDATE programme_trades SET chunked_pieces = 0 WHERE id = %s",
                        [row_id], timeout=10.0, quiet=True,
                    )
                stats['rows_unchanged'] += 1
                investor_unchanged += 1
                continue

            si = _get_symbol_info(sym)
            if si is None:
                print(f"  │ ⚠️ row {row_id}: no symbol_info for {sym} — skipped")
                stats['rows_skipped'] += 1
                investor_skipped += 1
                continue

            try:
                max_volume = float(getattr(si, 'volume_max', 0) or 0)
                min_volume = float(getattr(si, 'volume_min', 0.01) or 0.01)
                volume_step = float(getattr(si, 'volume_step', 0.01) or 0.01)
            except Exception:
                print(f"  │ ⚠️ row {row_id}: cannot read volume limits for {sym} — skipped")
                stats['rows_skipped'] += 1
                investor_skipped += 1
                continue

            if max_volume <= 0:
                # No max limit → never chunk
                if existing_pieces != 0:
                    db_execute(
                        "UPDATE programme_trades SET chunked_pieces = 0 WHERE id = %s",
                        [row_id], timeout=10.0, quiet=True,
                    )
                stats['rows_unchanged'] += 1
                investor_unchanged += 1
                continue

            # ============================================================
            # CASE 1: volume within max → chunked_pieces = 0
            # ============================================================
            if volume <= max_volume + 1e-9:
                if existing_pieces != 0:
                    db_execute(
                        "UPDATE programme_trades SET chunked_pieces = 0 WHERE id = %s",
                        [row_id], timeout=10.0, quiet=True,
                    )
                    print(f"  │ ✓ row {row_id} ({sym}) tradeid={tradeid}: "
                          f"volume {volume:.2f} ≤ max {max_volume:.2f} "
                          f"→ chunked_pieces = 0 (reset from {existing_pieces})")
                else:
                    print(f"  │ − row {row_id} ({sym}) tradeid={tradeid}: "
                          f"volume {volume:.2f} ≤ max {max_volume:.2f} "
                          f"→ chunked_pieces = 0")
                stats['rows_unchanged'] += 1
                investor_unchanged += 1
                continue

            # ============================================================
            # CASE 2: volume exceeds max → chunked_pieces = ceil(volume / max)
            # ============================================================
            needed_pieces = int(math.ceil(round(volume / max_volume, 10)))
            if needed_pieces < 1:
                needed_pieces = 1

            print(f"\n  │ 📦 row {row_id} ({sym} {ot}) tradeid={tradeid}")
            print(f"  │    volume        : {volume:.8f}")
            print(f"  │    volume_max    : {max_volume:.2f}")
            print(f"  │    volume_step   : {volume_step}")
            print(f"  │    volume_min    : {min_volume}")
            print(f"  │    needed pieces : {needed_pieces}")
            print(f"  │    current pieces: {existing_pieces}")

            if needed_pieces == existing_pieces:
                print(f"  │    ℹ️ chunked_pieces already = {existing_pieces} — no change")
                stats['rows_unchanged'] += 1
                investor_unchanged += 1
                continue

            # ---- Only chunked_pieces is written. volume is NEVER touched. ----
            ok, _, msg = db_execute(
                "UPDATE programme_trades SET chunked_pieces = %s WHERE id = %s",
                [int(needed_pieces), row_id],
                timeout=15.0, quiet=True,
            )

            if not ok:
                print(f"  │    ✗ failed to write chunked_pieces: {msg}")
                stats['errors'].append(f"row {row_id}: write failed")
                stats['rows_skipped'] += 1
                investor_skipped += 1
                continue

            stats['rows_chunked'] += 1
            investor_chunked += 1
            stats['total_pieces_created'] += needed_pieces
            investor_pieces += needed_pieces
            stats['total_volume_chunked'] += volume
            investor_volume += volume

            print(f"  │    ✅ chunked_pieces = {needed_pieces} "
                  f"(volume left at {volume:.8f})")

            stats['details'].append({
                'row_id':          row_id,
                'tradeid':         tradeid,
                'symbol':          sym,
                'ordertype':       ot,
                'volume':          volume,
                'volume_max':      max_volume,
                'needed_pieces':   needed_pieces,
                'previous_pieces': existing_pieces,
            })

        print(f"\n  │ Investor summary:")
        print(f"  │   chunked   : {investor_chunked}")
        print(f"  │   unchanged : {investor_unchanged}")
        print(f"  │   skipped   : {investor_skipped}")
        print(f"  │   pieces    : {investor_pieces}")
        print(f"  │   volume    : {investor_volume:.8f}")

    # ------------------------------------------------------------------
    # summary
    # ------------------------------------------------------------------
    print(f"\n{'='*10} 📦 CHUNKING SUMMARY (DB) {'='*10}")
    print(f"  Investors processed  : {stats['investors_processed']}")
    print(f"  Rows seen            : {stats['rows_seen']}")
    print(f"  Rows chunked         : {stats['rows_chunked']}")
    print(f"  Rows unchanged       : {stats['rows_unchanged']}")
    print(f"  Rows skipped         : {stats['rows_skipped']}")
    print(f"  Total pieces created : {stats['total_pieces_created']}")
    print(f"  Total volume chunked : {stats['total_volume_chunked']:.8f}")
    print(f"  Errors               : {len(stats['errors'])}")
    for e in stats['errors']:
        print(f"     • {e}")
    print(f"{'='*10} 🏁 COMPLETE {'='*10}\n")

    stats['processing_success'] = True
    return stats

# ==============================================================================
#  PLACE USD ORDERS — DB version (reconciliation-aware, chunked-pieces, no grid)
#
#  READS:
#    * programme_trades     -> pending rows for this investor
#    * harvhub              -> execution_start_date (for MT5 history anchoring)
#    * accountmanagement    -> default / maximum risk brackets (per programme)
#    * MT5                  -> pending orders / open positions / history deals
#
#  WRITES:
#    * programme_trades     -> orderstatus reflects what was placed at MT5:
#                                 'pending'  → MT5 pending order (limit / stop)
#                                 'running'  → MT5 open position (instant buy/sell)
#                                 'closed'   → row is done (found in MT5 history)
#    * (No JSON. No local files. No grid.)
#
#  ORDERSTATUS vs MT5 RECONCILIATION (BEFORE ANY PLACEMENT)
#  ---------------------------------------------------------
#  For every DB row the placer examines (investor-scoped, ordered by id):
#
#    STEP 1 — DB orderstatus pre-filter
#      * 'closed' or 'running'  → SKIP ENTIRELY (no reconciliation, no placement).
#      * 'pending' or NULL/''   → proceed to MT5 reconciliation.
#
#    STEP 2 — MT5 history deals (magic == tradeid)  ← CHECKED FIRST!
#      * found in MT5 history   → ROW IS CLOSED.
#                                 - Delete any MT5 pending order with the
#                                   same magic (the "bypassed" order) via
#                                   TRADE_ACTION_REMOVE.
#                                 - Force DB orderstatus = 'closed'.
#                                 - SKIP placement.
#
#    STEP 3 — MT5 open positions (magic == tradeid)
#      * found in MT5 positions → ROW IS RUNNING.
#                                 Ensure DB orderstatus = 'running'. SKIP.
#
#    STEP 4 — MT5 pending orders (magic == tradeid)
#      * found in MT5 pending   → ROW IS A PENDING ORDER.
#                                 Ensure DB orderstatus = 'pending'. SKIP.
#
#    STEP 5 — Not found anywhere → PLACE
#      * If orderstatus = 'pending' → PLACE (subject to risk guard + chunks).
#      * If orderstatus = NULL/''   → PLACE (subject to risk guard + chunks).
#      * If orderstatus = 'closed' / 'running' (handled at step 1) → never reach here.
#
#  POST-PLACEMENT DB STATUS (STEP 5)
#  ---------------------------------
#    * If the MT5 type we sent is a PENDING order (buy-limit / sell-limit /
#      buy-stop / sell-stop) → DB orderstatus = 'pending'.
#    * If the MT5 type we sent is an INSTANT MARKET order (buy / sell)
#      → DB orderstatus = 'running'.
#
#  CHUNKING SEMANTICS:
#    * chunked_pieces <= 1 → place ONE order of `volume`.
#    * chunked_pieces  > 1 → place `chunked_pieces` pieces of volume / pieces,
#                            capped by volume_max, floored by volume_min, and
#                            every piece subject to the max-risk guard.
#
#  NO GRID LOGIC. NO JSON. NO LOCAL FOLDERS.
# ==============================================================================

def place_usd_orders_db(inv_db_id=None):
    """
    Reconciliation-aware DB placer.

    Key safety rule enforced here:
    * A tradeid/magic that already appears in MT5 HISTORY (closed) is
      considered DONE. Any live MT5 pending order carrying that same
      magic is a leak — it is CANCELLED in MT5 immediately, and the
      DB row is forced to orderstatus='closed'. The row is never
      re-placed.

    Reconciliation order (per row, when DB says pending/NULL):
        STEP 2 — MT5 history deals (magic == tradeid)  → cancel live pending, mark closed, skip.
        STEP 3 — MT5 open positions (magic == tradeid) → mark running, skip.
        STEP 4 — MT5 pending orders (magic == tradeid) → mark pending, skip.
        STEP 5 — Not found anywhere                    → PLACE.
    """
    from datetime import datetime, timedelta, timezone
    import math

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

    print(f"\n{'='*10} 🚀 PLACE USD ORDERS (DB) {'='*10}")
    print(f" 🕒 Lagos time now: {lagos_now().strftime('%Y-%m-%d %H:%M:%S %Z')} (source: {_LAGOS_TZ_SOURCE})")
    if inv_db_id:
        print(f" 🎯 Target Investor: {inv_db_id}")

    stats = {
        'investor_id':                       inv_db_id if inv_db_id else 'all',
        'investors_processed':               0,
        'investors_skipped':                 0,
        'programmes_processed':              0,
        'rows_seen':                         0,
        'rows_skipped_closed':               0,
        'rows_skipped_running':              0,
        'rows_marked_pending':               0,
        'rows_marked_running':               0,
        'rows_marked_closed':                0,
        'rows_skipped_found_pending':        0,
        'rows_closed_and_pending_purged':    0,   # history hit → cancel leaked MT5 pending + mark closed
        'mt5_pending_purged_count':          0,   # individual MT5 pending orders removed
        'rows_placed':                       0,
        'rows_skipped':                      0,
        'pieces_placed':                     0,
        'pieces_failed':                     0,
        'orders_rejected_by_risk':           0,
        'errors':                            [],
        'details':                           [],
        'processing_success':                False,
    }

    # ==================================================================
    # SECTION 1 — SYMBOL / MT5 HELPERS
    # ==================================================================
    _symbol_info_cache = {}

    def _get_symbol_info(sym):
        si = _symbol_info_cache.get(sym)
        if si is None:
            si = mt5_symbol_info(sym)
            if si is None:
                mt5_symbol_select(sym, True)
                si = mt5_symbol_info(sym)
            _symbol_info_cache[sym] = si
        return si

    def _get_tick(sym):
        return mt5_symbol_tick(sym)

    def _round_to_step(value, step):
        if step is None or step <= 0:
            return value
        try:
            multiples = round(round(value / step, 10))
            return round(multiples * step, 10)
        except Exception:
            return value

    def _price_digits(si):
        try:
            if si is not None and hasattr(si, 'digits'):
                d = int(si.digits)
                if d >= 0:
                    return d
        except Exception:
            pass
        return 5

    def _order_type_to_mt5(order_type_str, entry=None, ask=None, bid=None):
        """
        Map DB ordertype to MT5 constant. Falls back to instant market
        if the pending type is invalid for the current price.
        Returns (mt5_type, was_converted, reason).
        """
        ot = (order_type_str or '').strip().lower()
        mapping = {
            'buy':        mt5.ORDER_TYPE_BUY,
            'sell':       mt5.ORDER_TYPE_SELL,
            'buy-limit':  mt5.ORDER_TYPE_BUY_LIMIT,
            'sell-limit': mt5.ORDER_TYPE_SELL_LIMIT,
            'buy-stop':   mt5.ORDER_TYPE_BUY_STOP,
            'sell-stop':  mt5.ORDER_TYPE_SELL_STOP,
        }
        mt5_type = mapping.get(ot)
        if mt5_type is None:
            return None, False, f"unknown order type '{order_type_str}'"

        if entry is None or ask is None or bid is None:
            return mt5_type, False, "no price context"

        if mt5_type == mt5.ORDER_TYPE_BUY_STOP and entry <= ask:
            return mt5.ORDER_TYPE_BUY, True, "buy-stop below ask -> instant buy"
        if mt5_type == mt5.ORDER_TYPE_SELL_STOP and entry >= bid:
            return mt5.ORDER_TYPE_SELL, True, "sell-stop above bid -> instant sell"
        if mt5_type == mt5.ORDER_TYPE_BUY_LIMIT and entry >= ask:
            return mt5.ORDER_TYPE_BUY, True, "buy-limit above ask -> instant buy"
        if mt5_type == mt5.ORDER_TYPE_SELL_LIMIT and entry <= bid:
            return mt5.ORDER_TYPE_SELL, True, "sell-limit below bid -> instant sell"

        return mt5_type, False, "valid pending"

    def _get_supported_filling_modes(si, is_pending_order=False):
        if si is None:
            return [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
        try:
            execution_mode = si.trade_exemode
            filling_mode_mask = si.filling_mode
        except Exception:
            return [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]

        SYMBOL_FILLING_FOK = 0x01
        SYMBOL_FILLING_IOC = 0x02
        SYMBOL_FILLING_BOC = 0x04

        if is_pending_order:
            return [mt5.ORDER_FILLING_RETURN]

        modes = []
        try:
            if execution_mode == mt5.SYMBOL_TRADE_EXECUTION_EXCHANGE:
                if filling_mode_mask & SYMBOL_FILLING_BOC:
                    modes.append(mt5.ORDER_FILLING_BOC)
                if filling_mode_mask & SYMBOL_FILLING_IOC:
                    modes.append(mt5.ORDER_FILLING_IOC)
                if filling_mode_mask & SYMBOL_FILLING_FOK:
                    modes.append(mt5.ORDER_FILLING_FOK)
                modes.append(mt5.ORDER_FILLING_RETURN)
            elif execution_mode == mt5.SYMBOL_TRADE_EXECUTION_MARKET:
                if filling_mode_mask & SYMBOL_FILLING_IOC:
                    modes.append(mt5.ORDER_FILLING_IOC)
                modes.append(mt5.ORDER_FILLING_RETURN)
                if filling_mode_mask & SYMBOL_FILLING_FOK:
                    modes.append(mt5.ORDER_FILLING_FOK)
            elif execution_mode in (mt5.SYMBOL_TRADE_EXECUTION_INSTANT,
                                    mt5.SYMBOL_TRADE_EXECUTION_REQUEST):
                if filling_mode_mask & SYMBOL_FILLING_FOK:
                    modes.append(mt5.ORDER_FILLING_FOK)
                modes.append(mt5.ORDER_FILLING_RETURN)
            else:
                modes = [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
        except Exception:
            modes = [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]

        uniq = []
        for m in modes:
            if m not in uniq:
                uniq.append(m)
        return uniq

    def _send_order_with_auto_filling(request_template, filling_modes, is_pending_order):
        last_err = None
        for filling_mode in filling_modes:
            req = dict(request_template)
            req["type_filling"] = filling_mode
            req["action"] = (mt5.TRADE_ACTION_PENDING if is_pending_order
                             else mt5.TRADE_ACTION_DEAL)
            res = mt5_order_send(req)
            if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
                return res, filling_mode, None
            if res is not None and res.retcode == 10009:
                last_err = f"filling {filling_mode} not supported"
                continue
            if res is not None:
                return res, filling_mode, f"retcode={res.retcode} comment={getattr(res, 'comment', '')}"
            last_err = f"no_response last_error={mt5_last_error()}"
        return None, None, (last_err or "all filling modes failed")

    # ==================================================================
    # SECTION 2 — RECONCILIATION HELPERS (magic == tradeid)
    # ==================================================================
    def _row_is_in_mt5_history(tradeid, execution_start_date):
        """
        True iff an MT5 history deal exists with magic == tradeid,
        between execution_start_date (parsed from DB) and now.
        Falls back to 30 days if execution_start_date is unusable.
        """
        if not tradeid:
            return False

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

        start_naive = start_dt.replace(tzinfo=None)
        end_naive = lagos_now().replace(tzinfo=None)

        try:
            deals = mt5_history_deals(start_naive, end_naive) or []
        except Exception:
            return False

        for d in deals:
            try:
                if int(getattr(d, 'magic', 0) or 0) == int(tradeid):
                    return True
            except Exception:
                continue
        return False

    def _cancel_mt5_pending_by_magic(tradeid):
        """
        Delete every live MT5 pending order whose magic == tradeid.
        Used to purge leaked pending orders when the trade is already
        found in MT5 history (i.e. the trade has closed).
        Returns list of cancelled tickets.
        """
        cancelled_tickets = []
        if not tradeid:
            return cancelled_tickets
        try:
            live_pending = mt5_orders_get() or []
        except Exception:
            return cancelled_tickets

        for o in live_pending:
            try:
                if int(getattr(o, 'magic', 0) or 0) != int(tradeid):
                    continue
            except Exception:
                continue

            ticket = getattr(o, 'ticket', None)
            if ticket is None:
                continue

            print(f"  │    🗑️ Cancelling leaked MT5 pending #{ticket} "
                  f"(magic={tradeid}, symbol={getattr(o, 'symbol', '?')})")
            try:
                req = {"action": mt5.TRADE_ACTION_REMOVE, "order": int(ticket)}
                res = mt5_order_send(req)
                if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
                    cancelled_tickets.append(int(ticket))
                    print(f"  │       ✅ MT5 pending #{ticket} cancelled")
                else:
                    err = (getattr(res, 'comment', '') if res is not None
                           else f"no_response last_error={mt5_last_error()}")
                    print(f"  │       ✗ cancel #{ticket} failed — {err}")
            except Exception as e:
                print(f"  │       ✗ cancel #{ticket} raised: {e}")

        return cancelled_tickets

    def _set_orderstatus(row_id, new_status):
        """Write a new orderstatus to programme_trades for a row."""
        ok, _, msg = db_execute(
            "UPDATE programme_trades SET orderstatus = %s WHERE id = %s",
            [new_status, row_id], timeout=10.0, quiet=True,
        )
        return ok, msg

    # ==================================================================
    # SECTION 3 — RISK GUARD (per symbol + direction + EXACT entry)
    # ==================================================================
    def _order_risk_in_dollars(entry, sl, symbol, volume, is_buy):
        if entry is None or sl is None or sl == 0:
            return 0.0
        try:
            calc_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
            profit = mt5_order_calc_profit(calc_type, symbol, float(volume),
                                           float(entry), float(sl))
            return abs(float(profit)) if profit else 0.0
        except Exception:
            return 0.0

    def _normalize_mt5_direction(order_or_position):
        t = getattr(order_or_position, 'type', None)
        if t in (mt5.ORDER_TYPE_BUY, mt5.ORDER_TYPE_BUY_LIMIT,
                 mt5.ORDER_TYPE_BUY_STOP, mt5.ORDER_TYPE_BUY_STOP_LIMIT):
            return 'buy'
        if t in (mt5.ORDER_TYPE_SELL, mt5.ORDER_TYPE_SELL_LIMIT,
                 mt5.ORDER_TYPE_SELL_STOP, mt5.ORDER_TYPE_SELL_STOP_LIMIT):
            return 'sell'
        return None

    def _collect_existing_risk_for_entry(symbol, direction, entry):
        """Sum the risk (USD) of all MT5 pending orders + open positions
        matching (symbol, direction, exact entry)."""
        total = 0.0
        try:
            pending = mt5_orders_get(symbol=symbol) or []
        except Exception:
            pending = []
        try:
            positions = mt5_positions_get(symbol=symbol) or []
        except Exception:
            positions = []

        for o in pending:
            if _normalize_mt5_direction(o) != direction:
                continue
            try:
                if abs(float(o.price_open) - float(entry)) > 1e-6:
                    continue
            except Exception:
                continue
            vol = float(getattr(o, 'volume_initial', 0) or getattr(o, 'volume_current', 0) or 0)
            sl = getattr(o, 'sl', None)
            total += _order_risk_in_dollars(o.price_open, sl, symbol, vol, direction == 'buy')

        for p in positions:
            if _normalize_mt5_direction(p) != direction:
                continue
            try:
                if abs(float(p.price_open) - float(entry)) > 1e-6:
                    continue
            except Exception:
                continue
            vol = float(getattr(p, 'volume', 0) or 0)
            sl = getattr(p, 'sl', None)
            total += _order_risk_in_dollars(p.price_open, sl, symbol, vol, direction == 'buy')

        return total

    # ==================================================================
    # SECTION 4 — PROGRAMME RISK CONFIG (default + maximum)
    # ==================================================================
    _risk_cfg_cache = {}

    def _load_programme_risk_cfg(programme_id):
        cfg = _risk_cfg_cache.get(programme_id)
        if cfg is not None:
            return cfg

        rows = db_fetch_all(
            """
            SELECT from_balance_range, to_balance_range, risk_amount
              FROM accountmanagement_balance_default_risk
             WHERE programme_id = %s
             ORDER BY from_balance_range ASC, id ASC
            """,
            [programme_id], timeout=10.0, quiet=True,
        )
        brackets = []
        for r in rows:
            try:
                lo = _coerce_float(_raw_first_key(r, 'from_balance_range'), default=None)
                hi = _coerce_float(_raw_first_key(r, 'to_balance_range'),   default=None)
                rk = _coerce_float(_raw_first_key(r, 'risk_amount'),        default=None)
            except Exception:
                continue
            if lo is None or rk is None:
                continue
            if hi is None or hi <= 0:
                hi = float('inf')
            brackets.append({'from': float(lo), 'to': float(hi), 'risk': float(rk)})

        max_rows = db_fetch_all(
            """
            SELECT from_balance_range, to_balance_range, risk_amount
              FROM accountmanagement_balance_maximum_risk
             WHERE programme_id = %s
             ORDER BY from_balance_range ASC, id ASC
            """,
            [programme_id], timeout=10.0, quiet=True,
        )
        max_brackets = []
        for r in max_rows:
            try:
                lo = _coerce_float(_raw_first_key(r, 'from_balance_range'), default=None)
                hi = _coerce_float(_raw_first_key(r, 'to_balance_range'),   default=None)
                rk = _coerce_float(_raw_first_key(r, 'risk_amount'),        default=None)
            except Exception:
                continue
            if lo is None or rk is None:
                continue
            if hi is None or hi <= 0:
                hi = float('inf')
            max_brackets.append({'from': float(lo), 'to': float(hi), 'risk': float(rk)})

        def _pick(brackets, balance, fallback=None):
            if not brackets or balance is None:
                return fallback
            for b in brackets:
                if b['from'] <= balance <= b['to']:
                    return b['risk']
            below = [b for b in brackets if b['from'] <= balance]
            if below:
                return below[-1]['risk']
            return brackets[0]['risk']

        cfg = {
            'default_brackets': brackets,
            'max_brackets':     max_brackets,
            'pick_default':     lambda bal: _pick(brackets, bal),
            'pick_max':         lambda bal: _pick(max_brackets, bal) or _pick(brackets, bal),
        }
        _risk_cfg_cache[programme_id] = cfg
        return cfg

    def _resolve_risk_for_balance(programme_id, balance):
        cfg = _load_programme_risk_cfg(programme_id)
        default_r = cfg['pick_default'](balance)
        maximum_r = cfg['pick_max'](balance)
        if default_r is None and maximum_r is None:
            return None, None
        if default_r is None:
            default_r = maximum_r
        if maximum_r is None:
            maximum_r = default_r
        if maximum_r < default_r:
            maximum_r = default_r
        return float(default_r), float(maximum_r)

    # ==================================================================
    # SECTION 5 — MT5 CONNECTION CHECK
    # ==================================================================
    acc = mt5_account_info()
    if acc is None:
        print(f"  ⚠️ MT5 not connected — cannot place orders")
        stats['errors'].append('MT5 not connected')
        return stats

    try:
        current_balance = float(acc.balance)
    except Exception:
        current_balance = 0.0
    print(f"  💰 Current MT5 balance: ${current_balance:.2f}")

    # ==================================================================
    # SECTION 6 — ENUMERATION (VPS-scoped)
    # ==================================================================
    print("\n" + "─"*80)
    print(" 📁 LOADING INVESTOR JOBS FROM DB (VPS-scoped)")
    print("─"*80)

    local_ip = get_local_ip()
    if not local_ip:
        print(" ⚠️ Could not determine local IP")
        stats['errors'].append('local IP unknown')
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
            return stats
    else:
        jobs = all_jobs

    print(f" │ Loaded {len(jobs)} investor job(s) from DB")
    print("─"*80)

    # ==================================================================
    # SECTION 7 — PER-INVESTOR PIPELINE
    # ==================================================================
    for job in jobs:
        investor_id    = job.get('investor_id')
        sub_account_id = job.get('sub_account_id')
        programme_id   = job.get('programme_id')
        programme_name = job.get('programme_name') or f"programme_{programme_id}"

        if investor_id is None or sub_account_id is None or programme_id is None:
            stats['investors_skipped'] += 1
            continue

        print(f"\n{'─'*72}")
        print(f" 🚀 Investor {investor_id} (sub {sub_account_id}) | "
              f"programme '{programme_name}' (id={programme_id})")
        print(f"{'─'*72}")

        stats['investors_processed'] += 1
        stats['programmes_processed'] += 1

        # --- resolve risk brackets for this programme / balance ---
        default_risk, maximum_risk = _resolve_risk_for_balance(programme_id, current_balance)
        if default_risk is None or maximum_risk is None:
            print(f"  ⚠️ No risk brackets for programme {programme_id} — skipping")
            stats['errors'].append(f"programme {programme_id}: no risk brackets")
            stats['investors_skipped'] += 1
            continue
        print(f"  🎯 Risk guard: default=${default_risk:.2f}  maximum=${maximum_risk:.2f}")

        # --- fetch execution_start_date once (used by history reconciliation) ---
        exec_row = db_fetch_one(
            """
            SELECT execution_start_date
              FROM harvhub
             WHERE id = %s AND sub_account_id = %s
             LIMIT 1
            """,
            [investor_id, sub_account_id], timeout=10.0, quiet=True,
        ) or {}
        execution_start_date = _raw_first_key(exec_row, 'execution_start_date')

        # --- fetch ALL pending-or-null rows for THIS investor (investor-scoped) ---
        rows = db_fetch_all(
            """
            SELECT id, tradeid, userid, programmeid,
                   investor_id, investor_sub_account_id,
                   symbol, ordertype, orderstatus, timeframe,
                   entry, stoploss, takeprofit,
                   volume, chunked_pieces
              FROM programme_trades
             WHERE investor_id = %s
               AND investor_sub_account_id = %s
               AND programmeid = %s
               AND userid = %s
               AND (orderstatus = 'pending' OR orderstatus IS NULL OR orderstatus = '')
             ORDER BY id ASC
            """,
            [investor_id, sub_account_id, programme_id, investor_id],
            timeout=15.0, quiet=True,
        )

        stats['rows_seen'] += len(rows)
        if not rows:
            print(f"  │ ℹ️ No pending/NULL rows for this investor")
            continue

        print(f"  │ Candidate rows: {len(rows)}")

        # ---------- Pre-fetch MT5 snapshots once per investor ----------
        try:
            pending_snapshot = mt5_orders_get() or []
        except Exception:
            pending_snapshot = []
        try:
            positions_snapshot = mt5_positions_get() or []
        except Exception:
            positions_snapshot = []

        # Build magic → presence lookups (magic == tradeid)
        pending_magics = set()
        for o in pending_snapshot:
            try:
                m = int(getattr(o, 'magic', 0) or 0)
                if m > 0:
                    pending_magics.add(m)
            except Exception:
                continue

        position_magics = set()
        for p in positions_snapshot:
            try:
                m = int(getattr(p, 'magic', 0) or 0)
                if m > 0:
                    position_magics.add(m)
            except Exception:
                continue

        # History is only consulted for rows that aren't found in pending/positions.
        _history_cache = {}

        def _history_has_magic(tid):
            if not tid:
                return False
            cached = _history_cache.get(tid)
            if cached is not None:
                return cached
            found = _row_is_in_mt5_history(tid, execution_start_date)
            _history_cache[tid] = found
            return found

        for r in rows:
            row_id    = _coerce_int(_raw_first_key(r, 'id'))
            tradeid   = _coerce_int(_raw_first_key(r, 'tradeid'))
            db_status = (_raw_first_key(r, 'orderstatus') or '')
            if isinstance(db_status, str):
                db_status = db_status.strip().lower()
            else:
                db_status = ''

            sym       = (_raw_first_key(r, 'symbol') or '').strip()
            ot        = (_raw_first_key(r, 'ordertype') or '').strip().lower()
            entry     = _coerce_float(_raw_first_key(r, 'entry'), default=None)
            sl        = _coerce_float(_raw_first_key(r, 'stoploss'), default=None)
            tp        = _coerce_float(_raw_first_key(r, 'takeprofit'), default=None)
            volume    = _coerce_float(_raw_first_key(r, 'volume'), default=None)
            pieces    = _coerce_int(_raw_first_key(r, 'chunked_pieces')) or 0

            print(f"\n  │ 📄 row {row_id} (tradeid={tradeid}, {sym} {ot}, db_status='{db_status or 'NULL'}')")
            print(f"  │    entry={entry}  sl={sl}  tp={tp}")
            print(f"  │    volume={volume}  chunked_pieces={pieces}")

            if row_id is None:
                stats['rows_skipped'] += 1
                continue

            # ==============================================================
            # STEP 1 — DB orderstatus pre-filter
            # --------------------------------------------------------------
            # 'closed' / 'running' → skip entirely (no reconciliation, no placement).
            # 'pending' / NULL / ''  → proceed to MT5 reconciliation.
            # ==============================================================
            if db_status == 'closed':
                print(f"  │    ⏭️ DB says 'closed' — SKIPPING without reconciliation")
                stats['rows_skipped_closed'] += 1
                stats['details'].append({
                    'row_id': row_id, 'tradeid': tradeid, 'symbol': sym,
                    'ordertype': ot, 'action': 'skipped_db_closed',
                })
                continue

            if db_status == 'running':
                print(f"  │    ⏭️ DB says 'running' — SKIPPING without reconciliation")
                stats['rows_skipped_running'] += 1
                stats['details'].append({
                    'row_id': row_id, 'tradeid': tradeid, 'symbol': sym,
                    'ordertype': ot, 'action': 'skipped_db_running',
                })
                continue

            # From here on, db_status is 'pending' or NULL/''.

            # ==============================================================
            # STEP 2 — MT5 HISTORY (magic == tradeid)  ← CHECKED FIRST
            # --------------------------------------------------------------
            # If the trade already appears in MT5 history, it has been closed
            # at the broker. Any live MT5 pending order carrying the same
            # magic is a leak that must be purged. Then force the DB to
            # 'closed' and never place again.
            # ==============================================================
            if tradeid and _history_has_magic(tradeid):
                print(f"  │    🕓 Found in MT5 history (magic={tradeid}) — "
                      f"trade is CLOSED. Reconciling.")

                # 2a — purge any leaked MT5 pending order(s) with this magic
                leaked_before = int(tradeid) in pending_magics
                if leaked_before:
                    print(f"  │       ⚠️ Leaked MT5 pending order(s) detected for "
                          f"magic={tradeid} — purging…")
                cancelled_tickets = _cancel_mt5_pending_by_magic(tradeid)
                if cancelled_tickets:
                    stats['mt5_pending_purged_count'] += len(cancelled_tickets)
                    stats['rows_closed_and_pending_purged'] += 1
                    # Immediately drop them from the in-memory snapshot so
                    # later rows in the same run don't see them as live.
                    for tkt in cancelled_tickets:
                        pending_magics.discard(int(tradeid))  # magic-keyed, so just drop the magic
                    # Also remove from pending_snapshot list (defensive)
                    try:
                        pending_snapshot[:] = [
                            o for o in pending_snapshot
                            if int(getattr(o, 'magic', 0) or 0) != int(tradeid)
                        ]
                    except Exception:
                        pass

                # 2b — force DB to 'closed'
                if db_status != 'closed':
                    ok, msg = _set_orderstatus(row_id, 'closed')
                    if ok:
                        stats['rows_marked_closed'] += 1
                        print(f"  │       DB updated: orderstatus='closed'")
                    else:
                        print(f"  │       ⚠️ DB update failed: {msg}")
                        stats['errors'].append(f"row {row_id}: mark closed failed — {msg}")
                else:
                    print(f"  │       DB already 'closed'")

                print(f"  │    ⏭️ Row is CLOSED — not placing")
                stats['details'].append({
                    'row_id': row_id, 'tradeid': tradeid, 'symbol': sym,
                    'ordertype': ot,
                    'action': 'closed_history_purged_pending',
                    'purged_tickets': cancelled_tickets,
                })
                continue

            # ==============================================================
            # STEP 3 — MT5 open positions (magic == tradeid)
            # --------------------------------------------------------------
            # Found in MT5 positions → row IS a running market position.
            # Ensure the DB says 'running', then skip placement.
            # ==============================================================
            if tradeid and int(tradeid) in position_magics:
                if db_status != 'running':
                    print(f"  │    ✅ Found in MT5 open positions (magic={tradeid}) — "
                          f"marking DB as 'running'")
                    ok, msg = _set_orderstatus(row_id, 'running')
                    if ok:
                        stats['rows_marked_running'] += 1
                        print(f"  │       DB updated: orderstatus='running'")
                    else:
                        print(f"  │       ⚠️ DB update failed: {msg}")
                        stats['errors'].append(f"row {row_id}: mark running failed — {msg}")
                else:
                    print(f"  │    ✅ Found in MT5 open positions (magic={tradeid}) — "
                          f"DB already 'running', SKIPPING placement")
                stats['details'].append({
                    'row_id': row_id, 'tradeid': tradeid, 'symbol': sym,
                    'ordertype': ot, 'action': 'marked_running_from_mt5_position',
                })
                continue

            # ==============================================================
            # STEP 4 — MT5 pending orders (magic == tradeid)
            # --------------------------------------------------------------
            # Found in MT5 pending → row IS a pending order.
            # Ensure the DB says 'pending', then skip placement.
            # ==============================================================
            if tradeid and int(tradeid) in pending_magics:
                if db_status != 'pending':
                    print(f"  │    ✅ Found in MT5 pending (magic={tradeid}) — "
                          f"DB was '{db_status or 'NULL'}' → marking 'pending'")
                    ok, msg = _set_orderstatus(row_id, 'pending')
                    if ok:
                        stats['rows_marked_pending'] += 1
                        print(f"  │       DB updated: orderstatus='pending'")
                    else:
                        print(f"  │       ⚠️ DB update failed: {msg}")
                        stats['errors'].append(f"row {row_id}: mark pending failed — {msg}")
                else:
                    print(f"  │    ✅ Found in MT5 pending (magic={tradeid}) — "
                          f"DB already 'pending', SKIPPING placement")
                stats['rows_skipped_found_pending'] += 1
                stats['details'].append({
                    'row_id': row_id, 'tradeid': tradeid, 'symbol': sym,
                    'ordertype': ot, 'action': 'skipped_found_in_mt5_pending',
                })
                continue

            # ==============================================================
            # STEP 5 — Not found anywhere → PLACE
            # --------------------------------------------------------------
            # Only reached for rows whose DB status is 'pending' or NULL/''
            # AND which are not present in MT5 pending/positions/history.
            #
            # Post-placement DB status:
            #   'pending'  if we sent an MT5 PENDING order (limit / stop)
            #   'running'  if we sent an MT5 INSTANT MARKET order (buy / sell)
            # ==============================================================
            print(f"  │    🎯 Not found in MT5 pending/positions/history — PLACING")

            if not sym or volume is None or volume <= 0:
                print(f"  │    ⚠️ incomplete row — skipped")
                stats['rows_skipped'] += 1
                continue

            si = _get_symbol_info(sym)
            if si is None:
                print(f"  │    ⚠️ no symbol_info for {sym} — skipped")
                stats['rows_skipped'] += 1
                continue

            tick = _get_tick(sym)
            if tick is None:
                print(f"  │    ⚠️ no tick for {sym} — skipped")
                stats['rows_skipped'] += 1
                continue

            digits   = _price_digits(si)
            vol_min  = float(getattr(si, 'volume_min', 0.01) or 0.01)
            vol_max  = float(getattr(si, 'volume_max', 100.0) or 100.0)
            vol_step = float(getattr(si, 'volume_step', 0.01) or 0.01)

            # -------- DECOMPOSE INTO PIECES --------
            num_pieces = 1
            if pieces and pieces > 1:
                num_pieces = int(pieces)

            raw_piece_vol = float(volume) / float(num_pieces)
            if raw_piece_vol > vol_max:
                num_pieces = int(math.ceil(volume / vol_max))
                raw_piece_vol = float(volume) / float(num_pieces)

            piece_vol = _round_to_step(raw_piece_vol, vol_step)
            if piece_vol < vol_min:
                piece_vol = vol_min
            if piece_vol > vol_max:
                piece_vol = vol_max

            print(f"  │    pieces={num_pieces}  piece_vol≈{piece_vol}  "
                  f"(vol_min={vol_min}, vol_max={vol_max}, step={vol_step})")

            # -------- DETERMINE MT5 ORDER TYPE --------
            mt5_type, converted, conv_reason = _order_type_to_mt5(
                ot, entry=entry, ask=tick.ask, bid=tick.bid
            )
            if mt5_type is None:
                print(f"  │    ⚠️ {conv_reason} — skipped")
                stats['rows_skipped'] += 1
                continue
            if converted:
                print(f"  │    🔄 {conv_reason}")

            is_pending = mt5_type in (mt5.ORDER_TYPE_BUY_LIMIT,
                                      mt5.ORDER_TYPE_SELL_LIMIT,
                                      mt5.ORDER_TYPE_BUY_STOP,
                                      mt5.ORDER_TYPE_SELL_STOP)
            direction = 'buy' if mt5_type in (mt5.ORDER_TYPE_BUY,
                                              mt5.ORDER_TYPE_BUY_LIMIT,
                                              mt5.ORDER_TYPE_BUY_STOP) else 'sell'

            # DB status we will write after a fully successful placement
            target_status = 'pending' if is_pending else 'running'

            if is_pending and (entry is None or entry <= 0):
                print(f"  │    ⚠️ pending order needs entry price — skipped")
                stats['rows_skipped'] += 1
                continue

            # -------- PLACE PIECES ONE BY ONE --------
            pieces_placed_this_row  = 0
            pieces_failed_this_row  = 0
            pieces_skipped_this_row = 0

            for piece_i in range(1, num_pieces + 1):
                entry_for_risk = entry if is_pending else (
                    tick.ask if direction == 'buy' else tick.bid
                )
                piece_risk = _order_risk_in_dollars(
                    entry_for_risk, sl, sym, piece_vol, direction == 'buy'
                )
                existing_risk = _collect_existing_risk_for_entry(
                    sym, direction, entry_for_risk
                )
                total_risk = existing_risk + piece_risk

                if piece_risk > 0 and total_risk > maximum_risk:
                    print(f"  │    🚫 piece {piece_i}/{num_pieces}: "
                          f"total risk ${total_risk:.2f} > max ${maximum_risk:.2f} "
                          f"(existing ${existing_risk:.2f} + piece ${piece_risk:.2f}) — STOP")
                    stats['orders_rejected_by_risk'] += 1
                    pieces_skipped_this_row += 1
                    break

                req_price = entry_for_risk
                if not is_pending:
                    req_price = tick.ask if direction == 'buy' else tick.bid

                request = {
                    "symbol": sym,
                    "volume": float(piece_vol),
                    "type": mt5_type,
                    "price": round(float(req_price), digits),
                    "deviation": 20,
                    "magic": int(tradeid or 0),
                    "comment": f"DBPIECE{piece_i}OF{num_pieces}"[:31],
                    "type_time": mt5.ORDER_TIME_GTC,
                }
                if sl is not None and sl > 0:
                    request["sl"] = round(float(sl), digits)
                if tp is not None and tp > 0:
                    request["tp"] = round(float(tp), digits)

                filling_modes = _get_supported_filling_modes(si, is_pending_order=is_pending)

                res, used_mode, err = _send_order_with_auto_filling(
                    request, filling_modes, is_pending_order=is_pending
                )

                if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
                    pieces_placed_this_row += 1
                    stats['pieces_placed'] += 1
                    print(f"  │    ✅ piece {piece_i}/{num_pieces}: "
                          f"{sym} {direction.upper()} {piece_vol} lots "
                          f"@ {request['price']} ticket={res.order} "
                          f"[filling={used_mode}]")
                else:
                    pieces_failed_this_row += 1
                    stats['pieces_failed'] += 1
                    print(f"  │    ✗ piece {piece_i}/{num_pieces}: "
                          f"placement failed — {err}")

            # -------- UPDATE ROW STATUS --------
            if num_pieces == 1:
                if pieces_placed_this_row == 1:
                    ok, msg = _set_orderstatus(row_id, target_status)
                    if ok:
                        stats['rows_placed'] += 1
                        print(f"  │    🏁 row {row_id} → orderstatus='{target_status}' "
                              f"(single piece)")
                    else:
                        print(f"  │    ⚠️ row {row_id}: status update failed — {msg}")
                        stats['errors'].append(f"row {row_id}: status update failed — {msg}")
                else:
                    stats['rows_skipped'] += 1
                    print(f"  │    ✗ row {row_id}: single piece failed, row unchanged in DB")
            else:
                if pieces_placed_this_row == num_pieces:
                    ok, msg = _set_orderstatus(row_id, target_status)
                    if ok:
                        stats['rows_placed'] += 1
                        print(f"  │    🏁 row {row_id} → orderstatus='{target_status}' "
                              f"(all {num_pieces} pieces placed)")
                    else:
                        print(f"  │    ⚠️ row {row_id}: status update failed — {msg}")
                        stats['errors'].append(f"row {row_id}: status update failed — {msg}")
                else:
                    stats['rows_skipped'] += 1
                    print(f"  │    ⏸ row {row_id}: only {pieces_placed_this_row}/"
                          f"{num_pieces} pieces placed — row unchanged in DB")

            stats['details'].append({
                'row_id':            row_id,
                'tradeid':           tradeid,
                'symbol':            sym,
                'ordertype':         ot,
                'chunked_pieces':    num_pieces,
                'piece_volume':      piece_vol,
                'pieces_placed':     pieces_placed_this_row,
                'pieces_failed':     pieces_failed_this_row,
                'pieces_skipped':    pieces_skipped_this_row,
                'converted':         converted,
                'target_status':     target_status,
                'action':            'placed',
            })

    # ==================================================================
    # SECTION 8 — SUMMARY
    # ==================================================================
    print(f"\n{'='*10} 🚀 PLACE USD ORDERS SUMMARY (DB) {'='*10}")
    print(f"  Investors processed                : {stats['investors_processed']}")
    print(f"  Investors skipped                  : {stats['investors_skipped']}")
    print(f"  Rows seen (pending/NULL)           : {stats['rows_seen']}")
    print(f"  -- DB-side skips --")
    print(f"  Skipped (DB 'closed')              : {stats['rows_skipped_closed']}")
    print(f"  Skipped (DB 'running')             : {stats['rows_skipped_running']}")
    print(f"  -- MT5 reconciliation --")
    print(f"  Closed via MT5 history + purged    : {stats['rows_closed_and_pending_purged']}")
    print(f"  MT5 pending orders purged          : {stats['mt5_pending_purged_count']}")
    print(f"  Skipped (found in MT5 pending)     : {stats['rows_skipped_found_pending']}")
    print(f"  Marked 'pending' (MT5 pending)     : {stats['rows_marked_pending']}")
    print(f"  Marked 'running' (MT5 position)    : {stats['rows_marked_running']}")
    print(f"  Marked 'closed'  (MT5 history)     : {stats['rows_marked_closed']}")
    print(f"  -- placement --")
    print(f"  Rows placed                        : {stats['rows_placed']}")
    print(f"  Rows skipped                       : {stats['rows_skipped']}")
    print(f"  Pieces placed                      : {stats['pieces_placed']}")
    print(f"  Pieces failed                      : {stats['pieces_failed']}")
    print(f"  Rejected by risk guard             : {stats['orders_rejected_by_risk']}")
    print(f"  Errors                             : {len(stats['errors'])}")
    for e in stats['errors']:
        print(f"     • {e}")
    print(f"{'='*10} 🏁 COMPLETE {'='*10}\n")

    stats['processing_success'] = True
    return stats
    
# ==============================================================================
#  CHECK PENDING ORDERS RISK — DB version
#
#  Enforces the programme's risk ceiling (accountmanagement_balance_maximum_risk)
#  against every live MT5 pending order for the investor, and purges any order
#  whose REAL risk (entry -> SL, in account currency) exceeds the hard cap.
#
#  SOURCES
#  -------
#  READS:
#    * accountmanagement_balance_default_risk  -> per-programme target risk
#                                                 (fallback when maximum is missing)
#    * accountmanagement_balance_maximum_risk  -> per-programme hard cap
#    * programme_trades                        -> row identity (tradeid <-> magic)
#    * MT5                                     -> live pending orders + SL
#  WRITES:
#    * MT5  -> TRADE_ACTION_REMOVE for offending tickets
#    * programme_trades -> orderstatus = 'closed' for the matching tradeid
#                          (the pending order is gone; nothing left to place)
#
#  RULES (mirrors check_pending_orders_risk_local)
#  ----------------------------------------------
#    0. Order has no SL                        -> REMOVE
#    1. risk <= default                        -> KEEP
#    2. default < risk <= maximum              -> KEEP
#    3. risk > maximum                         -> REMOVE
#    4. default missing                        -> maximum used as both
#    5. maximum missing                        -> default used as both
#    6. both missing                           -> skip investor
#
#  Magic semantics: order.magic == programme_trades.tradeid (same as the
#  rest of programmetrades.py).
# ==============================================================================
def check_pending_orders_risk_db(inv_db_id=None):
    print(f"\n{'='*10} 🛡️ PENDING ORDERS RISK AUDIT (DB) {'='*10}")

    stats = {
        'investor_id':                       inv_db_id if inv_db_id else 'all',
        'investors_processed':               0,
        'investors_skipped':                 0,
        'programmes_processed':              0,
        'orders_checked':                    0,
        'orders_kept':                       0,
        'orders_removed':                    0,
        'orders_removed_no_sl':              0,
        'orders_removed_exceeded_max':       0,
        'cancel_failures':                   0,
        'rows_marked_closed':                0,
        'errors':                            [],
        'details':                           [],
        'processing_success':                False,
    }

    # ------------------------------------------------------------------
    # MT5 helpers
    # ------------------------------------------------------------------
    def _digits(si):
        try:
            if si is not None and hasattr(si, 'digits'):
                d = int(si.digits)
                if d >= 0:
                    return d
        except Exception:
            pass
        return 5

    def _order_risk_usd(order, si):
        """
        Risk (account currency) from order.price_open -> order.sl.
        Returns (risk_abs, sl_distance, contract_size, direction) or
        (None, ...) when it cannot be computed.
        """
        try:
            entry = float(order.price_open)
            sl = float(order.sl) if order.sl else 0.0
        except Exception:
            return None, 0.0, 1.0, None

        if sl <= 0:
            return None, 0.0, 1.0, None

        t = int(getattr(order, 'type', -1))
        is_buy = t in (mt5.ORDER_TYPE_BUY_LIMIT,
                       mt5.ORDER_TYPE_BUY_STOP,
                       mt5.ORDER_TYPE_BUY_STOP_LIMIT)
        direction = 'buy' if is_buy else 'sell'

        sl_distance = abs(entry - sl)
        if sl_distance <= 0:
            return 0.0, 0.0, 1.0, direction

        contract = 1.0
        try:
            if si is not None:
                contract = float(getattr(si, 'trade_contract_size', 1.0) or 1.0)
        except Exception:
            contract = 1.0

        vol = float(getattr(order, 'volume_current', 0)
                    or getattr(order, 'volume_initial', 0) or 0)
        if vol <= 0:
            return 0.0, sl_distance, contract, direction

        try:
            calc_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
            profit = mt5_order_calc_profit(
                calc_type, order.symbol, vol, entry, sl
            )
            if profit is None:
                return sl_distance * vol * contract, sl_distance, contract, direction
            return abs(float(profit)), sl_distance, contract, direction
        except Exception:
            return sl_distance * vol * contract, sl_distance, contract, direction

    def _cancel_pending(ticket):
        try:
            req = {"action": mt5.TRADE_ACTION_REMOVE, "order": int(ticket)}
            res = mt5_order_send(req)
            if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
                return True, 'cancelled'
            if res is not None:
                return False, f"retcode={res.retcode} comment={getattr(res, 'comment', '')}"
            return False, f"no_response last_error={mt5_last_error()}"
        except Exception as e:
            return False, f"exception: {e}"

    def _mark_row_closed_by_tradeid(tradeid, investor_id, sub_account_id, programme_id):
        if tradeid is None:
            return False
        ok, affected, msg = db_execute(
            """
            UPDATE programme_trades
               SET orderstatus = 'closed'
             WHERE userid = %s
               AND programmeid = %s
               AND investor_id = %s
               AND investor_sub_account_id = %s
               AND tradeid = %s
               AND orderstatus = 'pending'
            """,
            [investor_id, programme_id, investor_id, sub_account_id, int(tradeid)],
            timeout=15.0, quiet=True,
        )
        return bool(ok) and (affected or 0) >= 0

    # ------------------------------------------------------------------
    # Programme risk-bracket readers (cached)
    # ------------------------------------------------------------------
    _risk_cfg_cache = {}

    def _load_programme_risk_cfg(programme_id):
        cfg = _risk_cfg_cache.get(programme_id)
        if cfg is not None:
            return cfg

        def _read(table):
            rows = db_fetch_all(
                f"""
                SELECT from_balance_range, to_balance_range, risk_amount
                  FROM {table}
                 WHERE programme_id = %s
                 ORDER BY from_balance_range ASC, id ASC
                """,
                [programme_id], timeout=10.0, quiet=True,
            )
            out = []
            for r in rows:
                try:
                    lo = _coerce_float(_raw_first_key(r, 'from_balance_range'), default=None)
                    hi = _coerce_float(_raw_first_key(r, 'to_balance_range'),   default=None)
                    rk = _coerce_float(_raw_first_key(r, 'risk_amount'),        default=None)
                except Exception:
                    continue
                if lo is None or rk is None:
                    continue
                if hi is None or hi <= 0:
                    hi = float('inf')
                out.append({'from': float(lo), 'to': float(hi), 'risk': float(rk)})
            return out

        def _pick(brackets, balance):
            if not brackets or balance is None:
                return None
            for b in brackets:
                if b['from'] <= balance <= b['to']:
                    return b['risk']
            below = [b for b in brackets if b['from'] <= balance]
            if below:
                return below[-1]['risk']
            return brackets[0]['risk']

        cfg = {
            'default_brackets': _read('accountmanagement_balance_default_risk'),
            'max_brackets':     _read('accountmanagement_balance_maximum_risk'),
            'pick_default':     lambda bal: _pick(
                _read('accountmanagement_balance_default_risk'), bal
            ),
            'pick_max':         lambda bal: _pick(
                _read('accountmanagement_balance_maximum_risk'), bal
            ),
        }
        _risk_cfg_cache[programme_id] = cfg
        return cfg

    def _resolve_risk_pair(programme_id, balance):
        cfg = _load_programme_risk_cfg(programme_id)
        default_r = cfg['pick_default'](balance)
        maximum_r = cfg['pick_max'](balance)

        if default_r is None and maximum_r is None:
            return None, None, 'no_config'
        if default_r is None:
            return float(maximum_r), float(maximum_r), 'max_only'
        if maximum_r is None:
            return float(default_r), float(default_r), 'default_only'
        if maximum_r < default_r:
            maximum_r = default_r
        return float(default_r), float(maximum_r), 'both'

    # ------------------------------------------------------------------
    # MT5 connection check
    # ------------------------------------------------------------------
    acc = mt5_account_info()
    if acc is None:
        print(f"  ⚠️ MT5 not connected — cannot audit pending risk")
        stats['errors'].append('MT5 not connected')
        return stats

    try:
        current_balance = float(acc.balance)
    except Exception:
        current_balance = 0.0
    print(f"  💰 Current MT5 balance: ${current_balance:.2f}")

    # ------------------------------------------------------------------
    # Enumeration
    # ------------------------------------------------------------------
    print("\n" + "─" * 80)
    print(" 📁 LOADING INVESTOR JOBS FROM DB (VPS-scoped)")
    print("─" * 80)

    local_ip = get_local_ip()
    if not local_ip:
        print(" ⚠️ Could not determine local IP")
        stats['errors'].append('local IP unknown')
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
            return stats
    else:
        jobs = all_jobs

    print(f" │ Loaded {len(jobs)} investor job(s) from DB")
    print("─" * 80)

    # ------------------------------------------------------------------
    # Per-investor loop
    # ------------------------------------------------------------------
    for job in jobs:
        investor_id    = job.get('investor_id')
        sub_account_id = job.get('sub_account_id')
        programme_id   = job.get('programme_id')
        programme_name = job.get('programme_name') or f"programme_{programme_id}"

        if investor_id is None or sub_account_id is None or programme_id is None:
            stats['investors_skipped'] += 1
            continue

        print(f"\n{'─'*72}")
        print(f" 🛡️ Investor {investor_id} (sub {sub_account_id}) | "
              f"programme '{programme_name}' (id={programme_id})")
        print(f"{'─'*72}")

        stats['investors_processed'] += 1
        stats['programmes_processed']  += 1

        default_risk, maximum_risk, cfg_src = _resolve_risk_pair(
            programme_id, current_balance
        )
        if default_risk is None or maximum_risk is None:
            print(f"  │ ⚠️ No risk configuration — skipping investor")
            stats['investors_skipped'] += 1
            continue
        if cfg_src == 'max_only':
            print(f"  │ ℹ️ default missing → using maximum for both")
        elif cfg_src == 'default_only':
            print(f"  │ ℹ️ maximum missing → using default for both")
        print(f"  │ Target risk (default) : ${default_risk:.2f}")
        print(f"  │ Maximum allowed (cap) : ${maximum_risk:.2f}")

        # Build a tradeid lookup for row-status flips after removal.
        row_lookup = {}
        try:
            rows = db_fetch_all(
                """
                SELECT id, tradeid
                  FROM programme_trades
                 WHERE userid = %s
                   AND programmeid = %s
                   AND investor_id = %s
                   AND investor_sub_account_id = %s
                   AND orderstatus = 'pending'
                """,
                [investor_id, programme_id, investor_id, sub_account_id],
                timeout=15.0, quiet=True,
            )
            for r in rows:
                tid = _coerce_int(_raw_first_key(r, 'tradeid'))
                rid = _coerce_int(_raw_first_key(r, 'id'))
                if tid is not None and rid is not None:
                    row_lookup[tid] = rid
        except Exception:
            pass

        # Snapshot live pending orders
        try:
            live_pending = mt5_orders_get() or []
        except Exception:
            live_pending = []

        if not live_pending:
            print(f"  │ 🔘 No live pending orders")
            continue

        print(f"  │ 🔍 Scanning {len(live_pending)} pending order(s)…")

        symbol_info_cache = {}

        def _si(sym):
            si = symbol_info_cache.get(sym)
            if si is None:
                si = mt5_symbol_info(sym)
                if si is None:
                    mt5_symbol_select(sym, True)
                    si = mt5_symbol_info(sym)
                symbol_info_cache[sym] = si
            return si

        for order in live_pending:
            ticket = getattr(order, 'ticket', None)
            sym = getattr(order, 'symbol', '?')
            tradeid = None
            try:
                tradeid = int(getattr(order, 'magic', 0) or 0)
            except Exception:
                tradeid = 0

            si = _si(sym)
            digits = _digits(si)

            print(f"\n  │ 📋 ticket #{ticket} | {sym} | magic={tradeid} "
                  f"| vol={float(getattr(order, 'volume_current', 0) or 0):.2f}")

            # Rule 0 — no SL
            sl_raw = getattr(order, 'sl', None)
            try:
                sl_val = float(sl_raw) if sl_raw else 0.0
            except Exception:
                sl_val = 0.0

            if sl_val <= 0:
                print(f"  │    🗑️ PURGING: no stoploss protection detected")
                ok, msg = _cancel_pending(ticket)
                stats['orders_checked'] += 1
                if ok:
                    stats['orders_removed'] += 1
                    stats['orders_removed_no_sl'] += 1
                    print(f"  │    ✅ Order removed")
                    if tradeid and tradeid in row_lookup:
                        if _mark_row_closed_by_tradeid(
                            tradeid, investor_id, sub_account_id, programme_id
                        ):
                            stats['rows_marked_closed'] += 1
                else:
                    stats['cancel_failures'] += 1
                    print(f"  │    ✗ Cancel failed: {msg}")
                continue

            # Compute real risk
            risk_usd, sl_dist, contract, direction = _order_risk_usd(order, si)
            stats['orders_checked'] += 1
            if risk_usd is None:
                print(f"  │    ⚠️ Could not compute risk — leaving order alone")
                stats['orders_kept'] += 1
                continue

            print(f"  │    order risk : ${risk_usd:.2f}  "
                  f"(SL dist={sl_dist}, contract={contract}, {direction})")
            print(f"  │    target     : ${default_risk:.2f} | "
                  f"maximum: ${maximum_risk:.2f}")

            if risk_usd > maximum_risk + 1e-9:
                print(f"  │    🗑️ PURGING: risk exceeds maximum threshold")
                print(f"  │       ${risk_usd:.2f} > ${maximum_risk:.2f} "
                      f"(excess ${risk_usd - maximum_risk:.2f})")
                ok, msg = _cancel_pending(ticket)
                if ok:
                    stats['orders_removed'] += 1
                    stats['orders_removed_exceeded_max'] += 1
                    print(f"  │    ✅ Order removed")
                    if tradeid and tradeid in row_lookup:
                        if _mark_row_closed_by_tradeid(
                            tradeid, investor_id, sub_account_id, programme_id
                        ):
                            stats['rows_marked_closed'] += 1
                else:
                    stats['cancel_failures'] += 1
                    print(f"  │    ✗ Cancel failed: {msg}")
            elif risk_usd <= default_risk + 1e-9:
                stats['orders_kept'] += 1
                print(f"  │    ✅ KEEPING: within target range")
            else:
                stats['orders_kept'] += 1
                print(f"  │    ✅ KEEPING: between target and maximum")

            stats['details'].append({
                'investor_id':     investor_id,
                'sub_account_id':  sub_account_id,
                'programme_id':    programme_id,
                'ticket':          ticket,
                'symbol':          sym,
                'magic_tradeid':   tradeid,
                'risk_usd':        float(risk_usd),
                'default_risk':    float(default_risk),
                'maximum_risk':    float(maximum_risk),
                'action':          'removed_exceeded_max' if risk_usd > maximum_risk + 1e-9
                                   else 'kept',
            })

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\n{'='*10} 🛡️ PENDING ORDERS RISK SUMMARY (DB) {'='*10}")
    print(f"  Investors processed            : {stats['investors_processed']}")
    print(f"  Investors skipped              : {stats['investors_skipped']}")
    print(f"  Orders checked                 : {stats['orders_checked']}")
    print(f"  Orders kept                    : {stats['orders_kept']}")
    print(f"  Orders removed (total)         : {stats['orders_removed']}")
    print(f"    - No stoploss                : {stats['orders_removed_no_sl']}")
    print(f"    - Exceeded maximum risk      : {stats['orders_removed_exceeded_max']}")
    print(f"  Cancel failures                : {stats['cancel_failures']}")
    print(f"  programme_trades marked closed : {stats['rows_marked_closed']}")
    print(f"  Errors                         : {len(stats['errors'])}")
    for e in stats['errors']:
        print(f"     • {e}")
    print(f"{'='*10} 🏁 COMPLETE {'='*10}\n")

    stats['processing_success'] = True
    return stats

# ==============================================================================
#  ORDERS REWARD CORRECTION — DB version
#
#  Aligns live MT5 pending orders AND open positions' TPs to the programme's
#  R:R configuration, using the SAME classifier semantics as
#  calculate_investor_symbols_orders_db.
#
#  SOURCES
#  -------
#  READS:
#    * signals_provider_interest.risk_reward
#      signals_provider_interest.risk_reward_type   (programme-scoped)
#    * accountmanagement.fixed_risk_reward
#      accountmanagement.minimum_risk_reward        (fallback when
#                                                    signals_provider_interest
#                                                    has no usable row)
#    * accountmanagement_balance_default_risk       (only used for logging the
#                                                    base risk alongside)
#    * programme_trades                             (for the magic <-> tradeid
#                                                    link, so we can look up
#                                                    ordertype/comment when
#                                                    MT5 doesn't carry it)
#    * MT5                                          (live pending + positions)
#
#  WRITES:
#    * MT5 -> TRADE_ACTION_MODIFY on pending orders (tp only)
#    * MT5 -> TRADE_ACTION_SLTP  on open positions  (tp only)
#    * programme_trades -> takeprofit is NOT touched. The DB is the source of
#      the ORIGINAL signal; the R:R applied at MT5 is a live correction.
#
#  R:R CLASSIFIER (identical to calculate_investor_symbols_orders_db)
#  ---------------------------------------------------------------
#    'custom minimum risk reward'   minimum floor
#        current_rr <  value   -> raise to value (new TP)
#        current_rr >= value   -> NO change
#
#    'fixed risk reward'            exact rewrite
#        current_rr != value   -> rewrite to value
#        current_rr == value   -> NO change
#
#    'custom fixed risk reward'     do nothing by design
#        current_rr >= 1.0     -> NO change
#        current_rr <  1.0     -> force to 1.0
#
#  TP SYNTHESIS
#  ------------
#  If takeprofit is missing (tp == 0), the correct TP is synthesized from
#  entry + SL and the target R:R, exactly as the DB calculate stage does.
#  Rounded to symbol digits.
#
#  ORDER TYPE
#  ----------
#  Applies to BOTH pending orders (TRADE_ACTION_MODIFY, tp only) and open
#  positions (TRADE_ACTION_SLTP, sl preserved + tp updated). Market orders
#  and pending orders are treated identically — the target R:R is the same.
#
#  No JSON. No local folders. No grid. Magic == programme_trades.tradeid.
# ==============================================================================
def orders_reward_correction_db(inv_db_id=None):
    print(f"\n{'='*10} 📐 ORDERS REWARD CORRECTION (DB) {'='*10}")

    stats = {
        'investor_id':                  inv_db_id if inv_db_id else 'all',
        'investors_processed':          0,
        'investors_skipped':            0,
        'programmes_processed':         0,
        'orders_checked':               0,
        'orders_adjusted':              0,
        'orders_skipped':               0,
        'orders_error':                 0,
        'positions_checked':            0,
        'positions_adjusted':           0,
        'positions_skipped':            0,
        'positions_error':              0,
        'rows_tp_synthesized':          0,
        'rr_matches':                   {},
        'rr_mismatches':                0,
        'mode':                         None,
        'programme_rr':                 None,
        'programme_rr_type_raw':        None,
        'programme_rr_type_norm':       None,
        'errors':                       [],
        'details':                      [],
        'processing_success':           False,
    }

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _norm_rr_type(raw):
        """Canonicalise risk_reward_type into one of three keys."""
        if raw is None:
            return 'fixed risk reward'
        s = str(raw).strip().lower()
        s = s.replace('_', ' ').replace('-', ' ')
        s = ' '.join(s.split())
        if not s:
            return 'fixed risk reward'
        for filler in (' and ', ' & ', ' + '):
            s = s.replace(filler, ' ')
        s = ' '.join(s.split())

        aliases = {
            'custom fixed risk reward':     'custom fixed risk reward',
            'customfixed risk reward':      'custom fixed risk reward',
            'custom fixed':                 'custom fixed risk reward',
            'customfixed':                  'custom fixed risk reward',
            'fixed custom':                 'custom fixed risk reward',
            'custom risk reward':           'custom fixed risk reward',

            'custom minimum risk reward':   'custom minimum risk reward',
            'customminimum risk reward':    'custom minimum risk reward',
            'custom minimum':               'custom minimum risk reward',
            'customminimum':                'custom minimum risk reward',
            'minimum risk reward':          'custom minimum risk reward',
            'minimum':                      'custom minimum risk reward',
            'min':                          'custom minimum risk reward',
            'floor':                        'custom minimum risk reward',

            'fixed risk reward':            'fixed risk reward',
            'fixedrisk reward':             'fixed risk reward',
            'fixed':                        'fixed risk reward',
            'fixed rr':                     'fixed risk reward',
            'exact':                        'fixed risk reward',
            'exact risk reward':            'fixed risk reward',
        }
        if s in aliases:
            return aliases[s]

        has_custom = 'custom' in s
        has_min    = ('minimum' in s) or ('min' in s.split()) or ('floor' in s)
        has_fixed  = ('fixed' in s)

        if has_custom and has_min and not has_fixed:
            return 'custom minimum risk reward'
        if has_custom and has_fixed:
            return 'custom fixed risk reward'
        if has_fixed:
            return 'fixed risk reward'
        if has_min:
            return 'custom minimum risk reward'
        return s

    def _digits(si):
        try:
            if si is not None and hasattr(si, 'digits'):
                d = int(si.digits)
                if d >= 0:
                    return d
        except Exception:
            pass
        return 5

    def _min_volume_for_symbol(si):
        if si is None:
            return 0.01
        try:
            v = float(getattr(si, 'volume_min', 0.01) or 0.01)
            return v if v > 0 else 0.01
        except Exception:
            return 0.01

    def _compute_current_rr(entry, sl, tp):
        if entry is None or sl is None or tp is None:
            return None, None, None
        risk   = abs(float(entry) - float(sl))
        reward = abs(float(tp) - float(entry))
        if risk <= 0:
            return None, risk, reward
        return reward / risk, risk, reward

    def _synthesize_tp(entry, sl, rr_value, is_buy, digits):
        if entry is None or sl is None or rr_value is None or rr_value <= 0:
            return None
        try:
            entry_f = float(entry)
            sl_f    = float(sl)
            risk_dist = abs(entry_f - sl_f)
            if risk_dist <= 0:
                return None
            reward_dist = risk_dist * float(rr_value)
            tp = (entry_f + reward_dist) if is_buy else (entry_f - reward_dist)
            return round(tp, digits)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Programme-scoped readers (cached per run)
    # ------------------------------------------------------------------
    _prog_cfg_cache = {}
    _symbol_info_cache = {}

    def _get_symbol_info(sym):
        si = _symbol_info_cache.get(sym)
        if si is None:
            si = mt5_symbol_info(sym)
            if si is None:
                mt5_symbol_select(sym, True)
                si = mt5_symbol_info(sym)
            _symbol_info_cache[sym] = si
        return si

    def _fetch_programme_rr(programme_id):
        """
        Returns (rr_value, rr_type_raw, rr_type_norm, source_label).

        Priority:
          1. signals_provider_interest (risk_reward + risk_reward_type)
          2. accountmanagement (fixed_risk_reward / minimum_risk_reward)
        """
        row = db_fetch_one(
            """
            SELECT id, risk_reward, risk_reward_type
              FROM signals_provider_interest
             WHERE programme_id = %s
               AND risk_reward IS NOT NULL
               AND risk_reward > 0
             ORDER BY id DESC
             LIMIT 1
            """,
            [programme_id], timeout=10.0, quiet=True,
        )
        if row:
            rr_val  = _coerce_float(_raw_first_key(row, 'risk_reward'), default=None)
            rr_type = _raw_first_key(row, 'risk_reward_type')
            if rr_val is not None and rr_val > 0:
                return (
                    float(rr_val),
                    rr_type,
                    _norm_rr_type(rr_type),
                    'signals_provider_interest',
                )

        # Fallback — accountmanagement
        am = db_fetch_one(
            """
            SELECT fixed_risk_reward, minimum_risk_reward
              FROM accountmanagement
             WHERE developerid = 0 AND programme_id = %s AND investorid = 0
             LIMIT 1
            """,
            [programme_id], timeout=10.0, quiet=True,
        )
        if not am:
            return None, None, None, None

        fixed   = _coerce_float(_raw_first_key(am, 'fixed_risk_reward'),   default=None)
        minimum = _coerce_float(_raw_first_key(am, 'minimum_risk_reward'), default=None)

        if fixed is not None and fixed > 0 and (minimum is None or fixed >= minimum):
            return float(fixed), 'fixed_risk_reward', 'fixed risk reward', 'accountmanagement.fixed_risk_reward'
        if minimum is not None and minimum > 0:
            return float(minimum), 'minimum_risk_reward', 'custom minimum risk reward', 'accountmanagement.minimum_risk_reward'
        return None, None, None, None

    def _programme_cfg(programme_id):
        cfg = _prog_cfg_cache.get(programme_id)
        if cfg is not None:
            return cfg
        rr_val, rr_type_raw, rr_type_norm, src = _fetch_programme_rr(programme_id)
        cfg = {
            'rr_value':       rr_val,
            'rr_type_raw':    rr_type_raw,
            'rr_type_norm':   rr_type_norm,
            'source':         src,
        }
        _prog_cfg_cache[programme_id] = cfg
        return cfg

    # ------------------------------------------------------------------
    # MT5 modify helpers
    # ------------------------------------------------------------------
    def _modify_pending_tp(ticket, entry, sl, new_tp, digits):
        req = {
            "action": mt5.TRADE_ACTION_MODIFY,
            "order":  int(ticket),
            "price":  round(float(entry), digits),
            "sl":     round(float(sl), digits) if sl else 0.0,
            "tp":     round(float(new_tp), digits),
        }
        try:
            res = mt5_order_send(req)
            if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
                return True, 'ok'
            if res is not None:
                return False, f"retcode={res.retcode} comment={getattr(res, 'comment', '')}"
            return False, f"no_response last_error={mt5_last_error()}"
        except Exception as e:
            return False, f"exception: {e}"

    def _modify_position_tp(ticket, sl, new_tp, digits):
        req = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "position": int(ticket),
            "sl":       round(float(sl), digits) if sl else 0.0,
            "tp":       round(float(new_tp), digits),
        }
        try:
            res = mt5_order_send(req)
            if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
                return True, 'ok'
            if res is not None:
                return False, f"retcode={res.retcode} comment={getattr(res, 'comment', '')}"
            return False, f"no_response last_error={mt5_last_error()}"
        except Exception as e:
            return False, f"exception: {e}"

    # ------------------------------------------------------------------
    # R:R classifier (identical semantics to calculate_investor_symbols_orders_db)
    # ------------------------------------------------------------------
    def _decide_action(current_rr, target_rr, rr_type):
        """
        Returns (decision, target_for_calc, reason).

        decision ∈ {'noop', 'raise', 'rewrite', 'force_1to1'}
        target_for_calc is the R:R to align to (None when noop).
        """
        if rr_type == 'custom minimum risk reward':
            if current_rr is None:
                return 'raise', target_rr, f"minimum floor: no TP set — apply 1:{target_rr}"
            if current_rr < target_rr - 1e-9:
                return 'raise', target_rr, f"minimum floor: current 1:{round(current_rr, 4)} < 1:{target_rr}"
            return 'noop', None, f"minimum floor: current 1:{round(current_rr, 4)} >= 1:{target_rr}"

        if rr_type == 'fixed risk reward':
            if current_rr is None:
                return 'rewrite', target_rr, f"fixed: no TP set — rewrite to 1:{target_rr}"
            if abs(current_rr - target_rr) > 1e-9:
                return 'rewrite', target_rr, f"fixed: current 1:{round(current_rr, 4)} != 1:{target_rr}"
            return 'noop', None, f"fixed: current already equals 1:{target_rr}"

        if rr_type == 'custom fixed risk reward':
            if current_rr is None:
                # No TP — do nothing. Custom-fixed says "leave it alone".
                return 'noop', None, "custom fixed: no TP set — no change by design"
            if current_rr < 1.0 - 1e-9:
                return 'force_1to1', 1.0, f"custom fixed: current 1:{round(current_rr, 4)} < 1:1 — forcing 1:1"
            return 'noop', None, f"custom fixed: current 1:{round(current_rr, 4)} — no change by design"

        # Unknown -> treat as fixed (safest fallback)
        if current_rr is None:
            return 'rewrite', target_rr, f"unrecognised type '{rr_type}' -> fixed: no TP set — rewrite to 1:{target_rr}"
        if abs(current_rr - target_rr) > 1e-9:
            return 'rewrite', target_rr, f"unrecognised type '{rr_type}' -> fixed: 1:{round(current_rr, 4)} != 1:{target_rr}"
        return 'noop', None, f"unrecognised type '{rr_type}' -> fixed: current already 1:{target_rr}"

    # ------------------------------------------------------------------
    # MT5 connection check
    # ------------------------------------------------------------------
    acc = mt5_account_info()
    if acc is None:
        print(f"  ⚠️ MT5 not connected — cannot correct reward")
        stats['errors'].append('MT5 not connected')
        return stats

    try:
        current_balance = float(acc.balance)
    except Exception:
        current_balance = 0.0
    print(f"  💰 Current MT5 balance: ${current_balance:.2f}")

    # ------------------------------------------------------------------
    # Enumeration
    # ------------------------------------------------------------------
    print("\n" + "─" * 80)
    print(" 📁 LOADING INVESTOR JOBS FROM DB (VPS-scoped)")
    print("─" * 80)

    local_ip = get_local_ip()
    if not local_ip:
        print(" ⚠️ Could not determine local IP")
        stats['errors'].append('local IP unknown')
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
            return stats
    else:
        jobs = all_jobs

    print(f" │ Loaded {len(jobs)} investor job(s) from DB")
    print("─" * 80)

    # ------------------------------------------------------------------
    # Per-investor loop
    # ------------------------------------------------------------------
    for job in jobs:
        investor_id    = job.get('investor_id')
        sub_account_id = job.get('sub_account_id')
        programme_id   = job.get('programme_id')
        programme_name = job.get('programme_name') or f"programme_{programme_id}"

        if investor_id is None or sub_account_id is None or programme_id is None:
            stats['investors_skipped'] += 1
            continue

        print(f"\n{'─'*72}")
        print(f" 📐 Investor {investor_id} (sub {sub_account_id}) | "
              f"programme '{programme_name}' (id={programme_id})")
        print(f"{'─'*72}")

        stats['investors_processed'] += 1

        cfg = _programme_cfg(programme_id)
        if cfg is None or cfg['rr_value'] is None or cfg['rr_value'] <= 0:
            print(f"  │ ⚠️ No usable R:R config for programme {programme_id} — skipping investor")
            stats['investors_skipped'] += 1
            continue

        rr_value    = float(cfg['rr_value'])
        rr_type_raw = cfg['rr_type_raw']
        rr_type     = cfg['rr_type_norm']
        rr_source   = cfg['source']

        stats['programme_rr'] = rr_value
        stats['programme_rr_type_raw'] = rr_type_raw
        stats['programme_rr_type_norm'] = rr_type
        stats['mode'] = rr_type

        print(f"  │ Programme R:R value : 1:{rr_value}")
        print(f"  │ Programme R:R type  : {rr_type_raw or '—'}")
        print(f"  │ Normalised type     : '{rr_type}'")
        print(f"  │ Source              : {rr_source}")

        # Pre-load known tradeids for this investor so we can annotate logs
        known_tradeids = set()
        try:
            tradeid_rows = db_fetch_all(
                """
                SELECT tradeid
                  FROM programme_trades
                 WHERE userid = %s
                   AND programmeid = %s
                   AND investor_id = %s
                   AND investor_sub_account_id = %s
                   AND tradeid IS NOT NULL
                """,
                [investor_id, programme_id, investor_id, sub_account_id],
                timeout=15.0, quiet=True,
            )
            for tr in tradeid_rows:
                tid = _coerce_int(_raw_first_key(tr, 'tradeid'))
                if tid is not None and tid > 0:
                    known_tradeids.add(tid)
        except Exception:
            pass

        # Snapshot MT5 once per investor
        try:
            live_pending = mt5_orders_get() or []
        except Exception:
            live_pending = []
        try:
            live_positions = mt5_positions_get() or []
        except Exception:
            live_positions = []

        # ==============================================================
        # SECTION A — OPEN POSITIONS (MARKET)
        # ==============================================================
        if live_positions:
            print(f"\n  └─ 🔍 Scanning {len(live_positions)} open positions (MARKET)…")

        for pos in live_positions:
            stats['positions_checked'] += 1

            sym  = getattr(pos, 'symbol', None)
            tkt  = getattr(pos, 'ticket', None)
            mt5_type_pos = int(getattr(pos, 'type', -1))
            is_buy = (mt5_type_pos == 0)

            if not sym:
                stats['positions_skipped'] += 1
                continue

            si = _get_symbol_info(sym)
            if si is None:
                stats['positions_skipped'] += 1
                continue

            digits = _digits(si)

            print(f"\n    └─ 📋 Position #{tkt} | "
                  f"{'BUY (MARKET)' if is_buy else 'SELL (MARKET)'} | {sym}")

            entry = float(getattr(pos, 'price_open', 0) or 0)
            sl    = float(getattr(pos, 'sl', 0) or 0)
            tp    = float(getattr(pos, 'tp', 0) or 0)

            if sl <= 0:
                print(f"       ⏭️ No SL — cannot compute R:R. Skipping.")
                stats['positions_skipped'] += 1
                continue

            current_rr, risk_dist, reward_dist = _compute_current_rr(entry, sl, tp)

            decision, target_for_calc, reason = _decide_action(
                current_rr, rr_value, rr_type
            )
            print(f"       → {reason}")

            if decision == 'noop':
                stats['positions_skipped'] += 1
                stats['rr_matches'][f"noop_{rr_type}"] = (
                    stats['rr_matches'].get(f"noop_{rr_type}", 0) + 1
                )
                continue

            # Effective target R:R for this action
            effective_rr = float(target_for_calc)

            # Synthesize TP if needed (tp == 0)
            tp_synthesized = False
            if tp <= 0:
                new_tp = _synthesize_tp(entry, sl, effective_rr, is_buy, digits)
                if new_tp is None:
                    print(f"       ⚠️ Could not synthesize TP (entry={entry}, sl={sl}, "
                          f"rr=1:{effective_rr})")
                    stats['positions_error'] += 1
                    stats['orders_error'] += 1
                    continue
                tp_synthesized = True
                stats['rows_tp_synthesized'] += 1
                print(f"       📝 No TP set — synthesizing to {new_tp} "
                      f"(target R:R = 1:{effective_rr})")
                new_tp_final = new_tp
            else:
                current_rr_v, _, _ = _compute_current_rr(entry, sl, tp)
                if current_rr_v is None:
                    print(f"       ⚠️ Cannot compute current R:R. Skipping.")
                    stats['positions_error'] += 1
                    stats['orders_error'] += 1
                    continue
                # Build the new TP that yields effective_rr
                synthesized = _synthesize_tp(entry, sl, effective_rr, is_buy, digits)
                if synthesized is None:
                    print(f"       ⚠️ Could not synthesize TP. Skipping.")
                    stats['positions_error'] += 1
                    stats['orders_error'] += 1
                    continue
                new_tp_final = synthesized

            # Direction sanity
            if is_buy and new_tp_final <= entry:
                print(f"       ⚠️ Synthesized TP ({new_tp_final}) not above entry — skipping")
                stats['positions_skipped'] += 1
                continue
            if (not is_buy) and new_tp_final >= entry:
                print(f"       ⚠️ Synthesized TP ({new_tp_final}) not below entry — skipping")
                stats['positions_skipped'] += 1
                continue

            old_rr_disp = f"{round(current_rr, 4)}" if current_rr is not None else "—"
            print(f"       entry={entry}  sl={sl}  tp={tp if tp > 0 else '—'}")
            print(f"       current R:R = 1:{old_rr_disp}  →  target R:R = 1:{effective_rr}")
            print(f"       new TP = {new_tp_final}")

            ok, msg = _modify_position_tp(tkt, sl, new_tp_final, digits)
            if ok:
                stats['positions_adjusted'] += 1
                stats['orders_adjusted'] += 1
                stats['rr_matches'][f"{rr_type}_{effective_rr}"] = (
                    stats['rr_matches'].get(f"{rr_type}_{effective_rr}", 0) + 1
                )
                print(f"       ✅ TP adjusted successfully to {new_tp_final}")
            else:
                stats['positions_error'] += 1
                stats['orders_error'] += 1
                print(f"       ✗ Modify failed: {msg}")

        # ==============================================================
        # SECTION B — PENDING ORDERS (LIMIT & STOP)
        # ==============================================================
        if live_pending:
            print(f"\n  └─ 🔍 Scanning {len(live_pending)} pending orders (LIMIT & STOP)…")

        for order in live_pending:
            stats['orders_checked'] += 1

            sym = getattr(order, 'symbol', None)
            tkt = getattr(order, 'ticket', None)
            mt5_type_ord = int(getattr(order, 'type', -1))
            is_buy = mt5_type_ord in (
                mt5.ORDER_TYPE_BUY_LIMIT,
                mt5.ORDER_TYPE_BUY_STOP,
                mt5.ORDER_TYPE_BUY_STOP_LIMIT,
            )

            if not sym:
                stats['orders_skipped'] += 1
                continue

            si = _get_symbol_info(sym)
            if si is None:
                stats['orders_skipped'] += 1
                continue

            digits = _digits(si)

            # Magic == tradeid lookup for logging
            try:
                tradeid = int(getattr(order, 'magic', 0) or 0)
            except Exception:
                tradeid = 0
            in_db = tradeid in known_tradeids if tradeid else False

            print(f"\n    └─ 📋 Order #{tkt} | "
                  f"{'BUY' if is_buy else 'SELL'} | {sym} | magic={tradeid}"
                  f"{'  (known)' if in_db else ''}")

            entry = float(getattr(order, 'price_open', 0) or 0)
            sl    = float(getattr(order, 'sl', 0) or 0)
            tp    = float(getattr(order, 'tp', 0) or 0)

            if sl <= 0:
                print(f"       ⏭️ No SL — cannot compute R:R. Skipping.")
                stats['orders_skipped'] += 1
                continue

            current_rr, risk_dist, reward_dist = _compute_current_rr(entry, sl, tp)

            decision, target_for_calc, reason = _decide_action(
                current_rr, rr_value, rr_type
            )
            print(f"       → {reason}")

            if decision == 'noop':
                stats['orders_skipped'] += 1
                stats['rr_matches'][f"noop_{rr_type}"] = (
                    stats['rr_matches'].get(f"noop_{rr_type}", 0) + 1
                )
                continue

            effective_rr = float(target_for_calc)

            tp_synthesized = False
            if tp <= 0:
                new_tp = _synthesize_tp(entry, sl, effective_rr, is_buy, digits)
                if new_tp is None:
                    print(f"       ⚠️ Could not synthesize TP (entry={entry}, sl={sl}, "
                          f"rr=1:{effective_rr})")
                    stats['orders_error'] += 1
                    continue
                tp_synthesized = True
                stats['rows_tp_synthesized'] += 1
                print(f"       📝 No TP set — synthesizing to {new_tp} "
                      f"(target R:R = 1:{effective_rr})")
                new_tp_final = new_tp
            else:
                synthesized = _synthesize_tp(entry, sl, effective_rr, is_buy, digits)
                if synthesized is None:
                    print(f"       ⚠️ Could not synthesize TP. Skipping.")
                    stats['orders_error'] += 1
                    continue
                new_tp_final = synthesized

            if is_buy and new_tp_final <= entry:
                print(f"       ⚠️ Synthesized TP ({new_tp_final}) not above entry — skipping")
                stats['orders_skipped'] += 1
                continue
            if (not is_buy) and new_tp_final >= entry:
                print(f"       ⚠️ Synthesized TP ({new_tp_final}) not below entry — skipping")
                stats['orders_skipped'] += 1
                continue

            old_rr_disp = f"{round(current_rr, 4)}" if current_rr is not None else "—"
            print(f"       entry={entry}  sl={sl}  tp={tp if tp > 0 else '—'}")
            print(f"       current R:R = 1:{old_rr_disp}  →  target R:R = 1:{effective_rr}")
            print(f"       new TP = {new_tp_final}")

            ok, msg = _modify_pending_tp(tkt, entry, sl, new_tp_final, digits)
            if ok:
                stats['orders_adjusted'] += 1
                stats['rr_matches'][f"{rr_type}_{effective_rr}"] = (
                    stats['rr_matches'].get(f"{rr_type}_{effective_rr}", 0) + 1
                )
                print(f"       ✅ TP adjusted successfully to {new_tp_final}")
            else:
                stats['orders_error'] += 1
                print(f"       ✗ Modify failed: {msg}")

        stats['programmes_processed'] += 1

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\n{'='*10} 📐 ORDERS REWARD CORRECTION SUMMARY (DB) {'='*10}")
    print(f"  Investor ID                     : {stats['investor_id']}")
    print(f"  Investors processed             : {stats['investors_processed']}")
    print(f"  Investors skipped               : {stats['investors_skipped']}")
    print(f"  Mode (R:R type)                 : {stats['mode'] or '—'}")
    if stats['programme_rr'] is not None:
        print(f"  Programme R:R value             : 1:{stats['programme_rr']}")
    print(f"  Positions checked               : {stats['positions_checked']}")
    print(f"  Positions adjusted              : {stats['positions_adjusted']}")
    print(f"  Positions skipped               : {stats['positions_skipped']}")
    print(f"  Positions errors                : {stats['positions_error']}")
    print(f"  Pending orders checked          : {stats['orders_checked']}")
    print(f"  Pending orders adjusted         : {stats['orders_adjusted']}")
    print(f"  Pending orders skipped          : {stats['orders_skipped']}")
    print(f"  Pending orders errors           : {stats['orders_error']}")
    print(f"  Rows TP synthesized             : {stats['rows_tp_synthesized']}")
    print(f"  Total checked                   : {stats['positions_checked'] + stats['orders_checked']}")
    print(f"  Total adjusted                  : {stats['positions_adjusted'] + stats['orders_adjusted']}")
    if stats['rr_matches']:
        print(f"\n  📊 R:R Usage Breakdown:")
        for k, v in sorted(stats['rr_matches'].items()):
            print(f"     • [{k}]: {v}")
    print(f"  Errors                          : {len(stats['errors'])}")
    for e in stats['errors']:
        print(f"     • {e}")
    print(f"{'='*10} 🏁 COMPLETE {'='*10}\n")

    stats['processing_success'] = True
    return stats

# ==============================================================================
#  APPLY DYNAMIC BREAKEVEN — DB version
#
#  Investor-scoped. For every OPEN MT5 position belonging to the investor
#  (magic == programme_trades.tradeid), compute the running reward multiple
#  (current floating profit / risk at SL) and — if it meets a threshold from
#  accountmanagement_trades_breakeven — push the stop loss forward.
#
#  READS:
#    * accountmanagement_trades_breakeven   -> programme-scoped rules:
#                                                floating_profit_at_risk_reward
#                                                breakeven_at_risk_reward
#    * harvhub                              -> investor identity (for logs)
#    * MT5                                  -> open positions + tick data
#
#  WRITES:
#    * MT5 -> TRADE_ACTION_SLTP on open positions (sl only; tp preserved)
#
#  RULES (mirrors apply_dynamic_breakeven_local)
#  ---------------------------------------------
#    * Only PROFITABLE positions are considered (position.profit > 0).
#    * Risk is computed as |entry - SL| × volume × contract_size
#      (falls back to mt5.order_calc_profit on the SL leg, then to
#       0.5 × profit as a last resort — same as the local version).
#    * current_r_multiple = position.profit / risk_usd
#    * Match the HIGHEST rule whose if_floating_profit_at_risk_reward is
#      satisfied by current_r_multiple.
#    * Target SL = entry ± (risk_distance × breakeven_at_risk_reward)
#      (plus for BUY, minus for SELL).
#    * Fallback ladder: if the target SL violates stops_level or the
#      direction check, drop to the next-lower rule and retry.
#
#  NO DEDUP:
#    Every row in accountmanagement_trades_breakeven is respected exactly
#    as it exists in the DB. Rows that share a breakeven_at_risk_reward
#    (but differ in trigger) are ALL loaded. The fallback ladder resolves
#    any practical overlap at runtime.
#
#  Note: MT5 preserves our tp as-is; we only push the SL.
# ==============================================================================
def apply_dynamic_breakeven_db(inv_db_id=None):
    print(f"\n{'='*10} 🎯 DYNAMIC BREAKEVEN (DB) {'='*10}")

    stats = {
        'investor_id':                inv_db_id if inv_db_id else 'all',
        'investors_processed':        0,
        'investors_skipped':          0,
        'programmes_processed':       0,
        'positions_checked':          0,
        'positions_profitable':       0,
        'positions_adjusted':         0,
        'positions_skipped':          0,
        'positions_error':            0,
        'breakeven_events':           0,
        'rules_loaded':               0,
        'errors':                     [],
        'details':                    [],
        'processing_success':         False,
    }

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    _symbol_info_cache = {}
    _tick_cache = {}

    def _get_symbol_info(sym):
        si = _symbol_info_cache.get(sym)
        if si is None:
            si = mt5_symbol_info(sym)
            if si is None:
                mt5_symbol_select(sym, True)
                si = mt5_symbol_info(sym)
            _symbol_info_cache[sym] = si
        return si

    def _get_tick(sym):
        t = _tick_cache.get(sym)
        if t is None:
            t = mt5_symbol_tick(sym)
            _tick_cache[sym] = t
        return t

    def _digits(si):
        try:
            if si is not None and hasattr(si, 'digits'):
                d = int(si.digits)
                if d >= 0:
                    return d
        except Exception:
            pass
        return 5

    # ------------------------------------------------------------------
    # Programme-scoped reader (cached per run)
    #
    # NO DEDUP: every row returned by the DB is preserved. Rows are
    # ordered ascending by trigger so the per-position code can pick
    # `applicable_rules[-1]` (the highest-trigger match) and then walk
    # downward through every lower-index rule as a fallback.
    # ------------------------------------------------------------------
    _breakeven_cache = {}

    def _load_breakeven_rules(programme_id):
        cached = _breakeven_cache.get(programme_id)
        if cached is not None:
            return cached

        rows = db_fetch_all(
            """
            SELECT id,
                   floating_profit_at_risk_reward,
                   breakeven_at_risk_reward
              FROM accountmanagement_trades_breakeven
             WHERE programme_id = %s
             ORDER BY floating_profit_at_risk_reward ASC, id ASC
            """,
            [programme_id], timeout=10.0, quiet=True,
        )

        cleaned = []
        for r in rows:
            trig = _coerce_float(
                _raw_first_key(r, 'floating_profit_at_risk_reward'),
                default=None,
            )
            tgt = _coerce_float(
                _raw_first_key(r, 'breakeven_at_risk_reward'),
                default=None,
            )
            if trig is None or tgt is None:
                continue
            row_id = _coerce_int(_raw_first_key(r, 'id'))
            cleaned.append({
                'id':                                 row_id,
                'if_floating_profit_at_risk_reward':  float(trig),
                'breakeven_at_risk_reward':           float(tgt),
            })

        # Stable ascending sort by trigger, then by id — no dedup.
        cleaned.sort(
            key=lambda x: (
                x['if_floating_profit_at_risk_reward'],
                x['id'] if x['id'] is not None else 0,
            )
        )

        print(f"  │ [BE] loaded {len(cleaned)} rule(s) "
              f"from DB (rows fetched = {len(rows)})")

        _breakeven_cache[programme_id] = cleaned
        return cleaned

    # ------------------------------------------------------------------
    # MT5 connection check
    # ------------------------------------------------------------------
    acc = mt5_account_info()
    if acc is None:
        print(f"  ⚠️ MT5 not connected — cannot apply dynamic breakeven")
        stats['errors'].append('MT5 not connected')
        return stats

    # ------------------------------------------------------------------
    # Enumeration
    # ------------------------------------------------------------------
    print("\n" + "─" * 80)
    print(" 📁 LOADING INVESTOR JOBS FROM DB (VPS-scoped)")
    print("─" * 80)

    local_ip = get_local_ip()
    if not local_ip:
        print(" ⚠️ Could not determine local IP")
        stats['errors'].append('local IP unknown')
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
            return stats
    else:
        jobs = all_jobs

    print(f" │ Loaded {len(jobs)} investor job(s) from DB")
    print("─" * 80)

    # ------------------------------------------------------------------
    # Per-investor loop
    # ------------------------------------------------------------------
    for job in jobs:
        investor_id    = job.get('investor_id')
        sub_account_id = job.get('sub_account_id')
        programme_id   = job.get('programme_id')
        programme_name = job.get('programme_name') or f"programme_{programme_id}"

        if investor_id is None or sub_account_id is None or programme_id is None:
            stats['investors_skipped'] += 1
            continue

        print(f"\n{'─'*72}")
        print(f" 🎯 Investor {investor_id} (sub {sub_account_id}) | "
              f"programme '{programme_name}' (id={programme_id})")
        print(f"{'─'*72}")

        stats['investors_processed'] += 1
        stats['programmes_processed'] += 1

        # -------- load programme breakeven rules --------
        breakeven_config = _load_breakeven_rules(programme_id)
        if not breakeven_config:
            print(f"  │ ⏭️ No breakeven rules configured for programme {programme_id}")
            stats['investors_skipped'] += 1
            continue

        stats['rules_loaded'] += len(breakeven_config)
        print(f"  │ ✅ Loaded {len(breakeven_config)} breakeven level(s):")
        for rule in breakeven_config:
            rid_display = f"id={rule['id']}" if rule.get('id') is not None else "id=—"
            print(f"  │    • [{rid_display}] Floating profit at >= "
                  f"{rule['if_floating_profit_at_risk_reward']}R → "
                  f"SL at {rule['breakeven_at_risk_reward']}R")

        # -------- load known tradeids (magic filter) for this investor --------
        known_tradeids = set()
        try:
            tradeid_rows = db_fetch_all(
                """
                SELECT tradeid
                  FROM programme_trades
                 WHERE userid = %s
                   AND programmeid = %s
                   AND investor_id = %s
                   AND investor_sub_account_id = %s
                   AND tradeid IS NOT NULL
                """,
                [investor_id, programme_id, investor_id, sub_account_id],
                timeout=15.0, quiet=True,
            )
            for tr in tradeid_rows:
                tid = _coerce_int(_raw_first_key(tr, 'tradeid'))
                if tid is not None and tid > 0:
                    known_tradeids.add(tid)
        except Exception:
            pass

        # -------- snapshot live positions --------
        try:
            positions = mt5_positions_get() or []
        except Exception:
            positions = []

        if not positions:
            print(f"  │ 📭 No open positions")
            continue

        # Filter by known tradeids (magic == tradeid)
        investor_positions = []
        for pos in positions:
            try:
                m = int(getattr(pos, 'magic', 0) or 0)
            except Exception:
                m = 0
            if m in known_tradeids:
                investor_positions.append(pos)

        if not investor_positions:
            print(f"  │ 📭 No positions belonging to this investor "
                  f"(by magic/tradeid match)")
            continue

        # -------- keep only profitable ones --------
        profitable_positions = [p for p in investor_positions
                                if float(getattr(p, 'profit', 0) or 0) > 0]

        stats['positions_checked'] += len(investor_positions)
        stats['positions_profitable'] += len(profitable_positions)

        if not profitable_positions:
            print(f"  │ 📭 {len(investor_positions)} position(s) checked, "
                  f"none profitable — nothing to do")
            continue

        print(f"  │ 🔍 {len(profitable_positions)} profitable position(s) to audit")

        for idx, position in enumerate(profitable_positions, 1):
            print(f"\n  📊 POSITION #{idx}/{len(profitable_positions)}")
            print(f"  ────────────────────────────────────────")
            print(f"    Ticket:      #{position.ticket}")
            print(f"    Symbol:      {position.symbol}")
            print(f"    Type:        {'BUY' if position.type == 0 else 'SELL'}")
            print(f"    Volume:      {position.volume}")
            print(f"    Open Price:  {position.price_open:.5f}")
            print(f"    Current SL:  {position.sl:.5f}")
            print(f"    Current TP:  {position.tp:.5f}")
            print(f"    Profit/Loss: ${position.profit:.2f}")

            si = _get_symbol_info(position.symbol)
            if si is None:
                print(f"    ⚠️ Symbol info not found — skipping")
                stats['positions_skipped'] += 1
                continue

            tick = _get_tick(position.symbol)
            if tick is None:
                print(f"    ⚠️ Tick info not found — skipping")
                stats['positions_skipped'] += 1
                continue

            is_buy = (position.type == 0)
            current_price = tick.ask if is_buy else tick.bid
            digits = _digits(si)

            print(f"    Current Price: {current_price:.5f}")

            # -------- risk distance --------
            if position.sl == 0:
                print(f"    ⚠️ No stop loss set — skipping")
                stats['positions_skipped'] += 1
                continue

            if is_buy:
                risk_distance = position.price_open - position.sl
            else:
                risk_distance = position.sl - position.price_open

            if risk_distance <= 0:
                print(f"    ⚠️ Invalid risk distance: {risk_distance:.5f} — skipping")
                stats['positions_error'] += 1
                continue

            print(f"    Risk Distance: {risk_distance:.5f} points")

            # -------- risk USD (with local's fallback ladder) --------
            calc_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
            sl_profit = mt5_order_calc_profit(
                calc_type, position.symbol, position.volume,
                position.price_open, position.sl,
            )

            if sl_profit is None or sl_profit == 0:
                print(f"    ⚠️ order_calc_profit returned {sl_profit} — using fallback")
                try:
                    contract_size = float(getattr(si, 'trade_contract_size', 0) or 0)
                    if contract_size > 0:
                        risk_usd = abs(risk_distance * position.volume * contract_size)
                    else:
                        risk_usd = abs(float(position.profit)) * 0.5
                except Exception:
                    risk_usd = abs(float(position.profit)) * 0.5
            else:
                risk_usd = round(abs(float(sl_profit)), 2)

            if risk_usd <= 0:
                print(f"    ⚠️ Risk USD is zero or negative ({risk_usd:.2f}) — skipping")
                stats['positions_skipped'] += 1
                continue

            current_r_multiple = float(position.profit) / risk_usd if risk_usd > 0 else 0.0

            print(f"    Risk Amount:  ${risk_usd:.2f}")
            print(f"    Current R/R:  {current_r_multiple:.2f}R")

            # -------- find applicable rules --------
            applicable_rules = [
                rule for rule in breakeven_config
                if current_r_multiple >= rule['if_floating_profit_at_risk_reward']
            ]

            if not applicable_rules:
                min_thresh = breakeven_config[0]['if_floating_profit_at_risk_reward']
                print(f"    ⏭️ Current R/R ({current_r_multiple:.2f}R) below minimum "
                      f"threshold ({min_thresh}R) — skipping")
                stats['positions_skipped'] += 1
                continue

            highest_rule = applicable_rules[-1]
            target_reward = highest_rule['breakeven_at_risk_reward']

            print(f"    ✅ Matched: floating >= "
                  f"{highest_rule['if_floating_profit_at_risk_reward']}R "
                  f"→ SL at {target_reward}R "
                  f"(rule id={highest_rule.get('id')})")

            # -------- stops level --------
            try:
                stops_level_points = max(int(getattr(si, 'trade_stops_level', 0) or 0), 10)
            except Exception:
                stops_level_points = 10
            try:
                point = float(getattr(si, 'point', 0.0) or 0.0)
                if point <= 0:
                    point = 0.00001
            except Exception:
                point = 0.00001
            stoplevel = stops_level_points * point
            print(f"    Stop Level:   {stoplevel:.5f}")

            # -------- fallback ladder --------
            # Walk from the highest-trigger match downward through every
            # lower-index rule. Rows sharing a breakeven level are still
            # tried independently because nothing is deduped.
            current_index = breakeven_config.index(highest_rule)
            sl_set = False

            for i in range(current_index, -1, -1):
                test_reward = breakeven_config[i]['breakeven_at_risk_reward']
                test_rule_id = breakeven_config[i].get('id')

                if is_buy:
                    target_sl = position.price_open + (risk_distance * test_reward)
                    is_valid_direction = (
                        target_sl < current_price - stoplevel and
                        target_sl >= position.sl - (point * 5)
                    )
                    print(f"    └─ BUY attempt: target SL={target_sl:.5f} "
                          f"({test_reward}R, id={test_rule_id}) "
                          f"valid={'YES' if is_valid_direction else 'NO'}")
                else:
                    target_sl = position.price_open - (risk_distance * test_reward)
                    is_valid_direction = (
                        target_sl > current_price + stoplevel and
                        target_sl <= position.sl + (point * 5)
                    )
                    print(f"    └─ SELL attempt: target SL={target_sl:.5f} "
                          f"({test_reward}R, id={test_rule_id}) "
                          f"valid={'YES' if is_valid_direction else 'NO'}")

                if not is_valid_direction:
                    continue

                target_sl = round(target_sl, digits)
                if target_sl <= 0:
                    print(f"       ⚠️ Invalid target SL value {target_sl} — skipping")
                    continue

                # ---- send modify ----
                req = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": int(position.ticket),
                    "sl": float(target_sl),
                    "tp": float(position.tp),
                }
                try:
                    res = mt5_order_send(req)
                except Exception as e:
                    print(f"       ✗ Modify raised: {e}")
                    res = None

                if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
                    stats['positions_adjusted'] += 1
                    stats['breakeven_events'] += 1
                    sl_set = True
                    print(f"       ✅ SUCCESS — SL moved to {target_sl:.5f} "
                          f"({test_reward}R)")
                    stats['details'].append({
                        'investor_id':    investor_id,
                        'sub_account_id': sub_account_id,
                        'programme_id':   programme_id,
                        'ticket':         position.ticket,
                        'symbol':         position.symbol,
                        'direction':      'buy' if is_buy else 'sell',
                        'r_multiple':     round(current_r_multiple, 4),
                        'target_r':       float(test_reward),
                        'rule_id':        test_rule_id,
                        'new_sl':         float(target_sl),
                        'old_sl':         float(position.sl),
                        'action':         'sl_moved',
                    })
                    break
                else:
                    err = (getattr(res, 'comment', '') if res is not None
                           else f"no_response last_error={mt5_last_error()}")
                    retcode = getattr(res, 'retcode', 'None') if res is not None else 'None'
                    print(f"       ✗ Modify failed: {err} (retcode={retcode})")

            if not sl_set:
                stats['positions_error'] += 1
                print(f"    ✗ All fallback attempts failed for #{position.ticket}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\n{'='*10} 🎯 DYNAMIC BREAKEVEN SUMMARY (DB) {'='*10}")
    print(f"  Investors processed       : {stats['investors_processed']}")
    print(f"  Investors skipped         : {stats['investors_skipped']}")
    print(f"  Programmes processed      : {stats['programmes_processed']}")
    print(f"  Rules loaded (total)      : {stats['rules_loaded']}")
    print(f"  Positions checked         : {stats['positions_checked']}")
    print(f"  Positions profitable      : {stats['positions_profitable']}")
    print(f"  Positions adjusted        : {stats['positions_adjusted']}")
    print(f"  Positions skipped         : {stats['positions_skipped']}")
    print(f"  Positions errors          : {stats['positions_error']}")
    print(f"  Breakeven events          : {stats['breakeven_events']}")
    print(f"  Errors                    : {len(stats['errors'])}")
    for e in stats['errors']:
        print(f"     • {e}")
    print(f"{'='*10} 🏁 COMPLETE {'='*10}\n")

    stats['processing_success'] = True
    return stats

# ==============================================================================
#  TRADES ANALYTICS — DB version
#
#  Investor-scoped. Walks MT5 history from execution_start_date → contract
#  expiry (or now), groups deals by position_id, and writes:
#
#    * investors_analytics   — ONE row per (userid, sub_account_id) with all the
#                              flat scalars your useranalytics.php consumes.
#    * authorized_trades     — one row per authorized closed trade.
#    * unauthorized_trades   — one row per unauthorized closed trade.
#
#  AUTHORIZATION
#  -------------
#  A trade is AUTHORIZED iff its entry_deal.magic is in the investor's
#  programme_trades.tradeid set for this programme (same convention used by
#  check_and_record_unauthorized_actions_db).
#
#  WRITES (all idempotent — upsert where a natural key exists):
#    investors_analytics:
#      total_trades, total_pnl, profit_trades, loss_trades,
#      profit_amount, loss_amount,
#      lowest_trades_per_day, highest_trades_per_day, average_trades_per_day,
#      lowest_trades_per_week, highest_trades_per_week, average_trades_per_week,
#      highest_loss_per_trade, highest_drawdown,
#      symbols_traded, closed_deals_with_sl_tp, closed_deals_without_sl_tp,
#      consecutive_losses_count, total_loss_pnl,
#      consecutive_days_in_loss_count,
#      consecutive_days_in_loss_count_total_loss_pnl,
#      revenue_percentage, revenue_profit_percentage, revenue_loss_percentage,
#      recent_risk_reward
#    authorized_trades / unauthorized_trades:
#      one row per trade (dedup by ticket).
#
#  No JSON. No local folders. Magic == programme_trades.tradeid.
# ==============================================================================
def trades_analytics_db(inv_db_id=None):
    print(f"\n{'='*10} 📊 TRADES ANALYTICS (DB) {'='*10}")

    from datetime import datetime, timedelta, timezone
    import re as _re

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

    stats = {
        'investor_id':             inv_db_id if inv_db_id else 'all',
        'investors_processed':     0,
        'investors_skipped':       0,
        'programmes_processed':    0,
        'total_deals_seen':        0,
        'total_trades_grouped':    0,
        'authorized_trades':       0,
        'unauthorized_trades':     0,
        'analytics_rows_upserted': 0,
        'authorized_rows_written': 0,
        'unauthorized_rows_written': 0,
        'errors':                  [],
        'details':                 [],
        'processing_success':      False,
    }

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _extract_rr_from_comment(comment):
        if not comment or not isinstance(comment, str):
            return 0.0
        m = _re.search(r'R([0-9]+(?:\.[0-9]+)?)', comment)
        if m:
            try:
                return float(m.group(1))
            except (ValueError, TypeError):
                return 0.0
        return 0.0

    def _day_key(ts):
        try:
            return datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d')
        except Exception:
            return None

    def _week_key(ts):
        try:
            d = datetime.fromtimestamp(int(ts)).isocalendar()
            return f"{d[0]}-W{d[1]:02d}"
        except Exception:
            return None

    def _iso(ts):
        try:
            return datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            return None

    def _parse_date_flexible(date_str):
        if not date_str:
            return None
        if isinstance(date_str, datetime):
            return date_str
        s = str(date_str).strip()
        if s.upper() == "NULL" or s == "":
            return None
        for fmt in ("%Y-%m-%d", "%B %d, %Y", "%B %d %Y", "%Y/%m/%d",
                    "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y",
                    "%Y-%m-%d %H:%M:%S", "%B %d, %Y %H:%M:%S"):
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                continue
        return None

    def _ensure_analytics_row(investor_id, sub_account_id):
        """Guarantee a row exists so the UPDATE below has somewhere to land."""
        row = db_fetch_one(
            """
            SELECT id FROM investors_analytics
             WHERE userid = %s AND sub_account_id = %s
             LIMIT 1
            """,
            [investor_id, sub_account_id], timeout=10.0, quiet=True,
        )
        if row and _raw_first_key(row, 'id'):
            return _coerce_int(_raw_first_key(row, 'id'))
        ok, new_id, _ = db_execute(
            """
            INSERT INTO investors_analytics (userid, sub_account_id)
            VALUES (%s, %s)
            """,
            [investor_id, sub_account_id], timeout=10.0, quiet=True,
        )
        if not ok:
            return None
        row = db_fetch_one(
            """
            SELECT id FROM investors_analytics
             WHERE userid = %s AND sub_account_id = %s
             ORDER BY id DESC
             LIMIT 1
            """,
            [investor_id, sub_account_id], timeout=10.0, quiet=True,
        )
        return _coerce_int(_raw_first_key(row or {}, 'id'))

    # ------------------------------------------------------------------
    # MT5 connection check
    # ------------------------------------------------------------------
    acc = mt5_account_info()
    if acc is None:
        print(f"  ⚠️ MT5 not connected — cannot read trade history")
        stats['errors'].append('MT5 not connected')
        return stats

    # ------------------------------------------------------------------
    # Enumeration
    # ------------------------------------------------------------------
    print("\n" + "─" * 80)
    print(" 📁 LOADING INVESTOR JOBS FROM DB (VPS-scoped)")
    print("─" * 80)

    local_ip = get_local_ip()
    if not local_ip:
        print(" ⚠️ Could not determine local IP")
        stats['errors'].append('local IP unknown')
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
            return stats
    else:
        jobs = all_jobs

    print(f" │ Loaded {len(jobs)} investor job(s) from DB")
    print("─" * 80)

    # ------------------------------------------------------------------
    # Per-investor pipeline
    # ------------------------------------------------------------------
    for job in jobs:
        investor_id    = job.get('investor_id')
        sub_account_id = job.get('sub_account_id')
        programme_id   = job.get('programme_id')
        programme_name = job.get('programme_name') or f"programme_{programme_id}"

        if investor_id is None or sub_account_id is None or programme_id is None:
            stats['investors_skipped'] += 1
            continue

        print(f"\n{'─'*72}")
        print(f" 📊 Investor {investor_id} (sub {sub_account_id}) | "
              f"programme '{programme_name}' (id={programme_id})")
        print(f"{'─'*72}")

        stats['investors_processed'] += 1
        stats['programmes_processed'] += 1

        # -------- anchor + window --------
        anchor = db_fetch_one(
            """
            SELECT broker_balance, execution_start_date
              FROM harvhub
             WHERE id = %s AND sub_account_id = %s
             LIMIT 1
            """,
            [investor_id, sub_account_id], timeout=10.0, quiet=True,
        ) or {}
        execution_start_date = _raw_first_key(anchor, 'execution_start_date')
        start_dt = _parse_date_flexible(execution_start_date)
        if start_dt is None:
            print(f"  │ ⚠️ No usable execution_start_date — skipping investor")
            stats['investors_skipped'] += 1
            continue

        # Contract end = start + duration from accountmanagement if available
        contract_days = None
        am = db_fetch_one(
            """
            SELECT contract_duration
              FROM accountmanagement
             WHERE developerid = 0 AND programme_id = %s AND investorid = 0
             LIMIT 1
            """,
            [programme_id], timeout=10.0, quiet=True,
        )
        if am:
            try:
                contract_days = int(_coerce_int(_raw_first_key(am, 'contract_duration')) or 0)
            except Exception:
                contract_days = None

        end_dt = lagos_now().replace(tzinfo=None)
        if contract_days and contract_days > 0:
            candidate = start_dt + timedelta(days=contract_days)
            if candidate < end_dt:
                end_dt = candidate
        if end_dt < start_dt:
            end_dt = lagos_now().replace(tzinfo=None)

        print(f"  │ Window : {start_dt.strftime('%Y-%m-%d')} → {end_dt.strftime('%Y-%m-%d')}")

        # -------- authorized tradeid set --------
        authorized_tradeids = set()
        try:
            rows = db_fetch_all(
                """
                SELECT tradeid
                  FROM programme_trades
                 WHERE userid = %s
                   AND programmeid = %s
                   AND investor_id = %s
                   AND investor_sub_account_id = %s
                   AND tradeid IS NOT NULL
                """,
                [investor_id, programme_id, investor_id, sub_account_id],
                timeout=15.0, quiet=True,
            )
            for r in rows:
                tid = _coerce_int(_raw_first_key(r, 'tradeid'))
                if tid is not None and tid > 0:
                    authorized_tradeids.add(tid)
        except Exception:
            pass
        print(f"  │ Authorized trade IDs: {len(authorized_tradeids)}")

        # -------- pull MT5 history --------
        try:
            deals = mt5_history_deals(start_dt, end_dt) or []
        except Exception as e:
            print(f"  │ ✗ Could not read MT5 history: {e}")
            stats['errors'].append(f"investor {investor_id}: mt5 history error: {e}")
            stats['investors_skipped'] += 1
            continue

        stats['total_deals_seen'] += len(deals)
        if not deals:
            print(f"  │ 📭 No closed deals in window")
            continue

        try:
            hist_orders = mt5_history_orders(start_dt, end_dt) or []
        except Exception:
            hist_orders = []

        # Collect order comments + SL/TP per position_id
        order_comments = {}
        order_sl_tp = {}
        for o in hist_orders:
            pid = getattr(o, 'position_id', None)
            if pid is None:
                continue
            if pid not in order_comments:
                order_comments[pid] = getattr(o, 'comment', '') or ''
            sl = float(getattr(o, 'sl', 0) or 0)
            tp = float(getattr(o, 'tp', 0) or 0)
            cur = order_sl_tp.setdefault(pid, {'sl': 0.0, 'tp': 0.0})
            if sl > 0 and cur['sl'] == 0.0:
                cur['sl'] = sl
            if tp > 0 and cur['tp'] == 0.0:
                cur['tp'] = tp

        # -------- group deals by position_id --------
        deals_by_position = {}
        for d in deals:
            # Only entry/exit deal types (0=BUY, 1=SELL). Ignore balance ops.
            if getattr(d, 'type', None) in (0, 1):
                deals_by_position.setdefault(d.position_id, []).append(d)

        master_trades = []
        for position_id, dlist in deals_by_position.items():
            dlist.sort(key=lambda x: x.time)
            if len(dlist) < 2:
                continue

            total_profit     = sum(float(getattr(d, 'profit', 0) or 0) for d in dlist)
            total_commission = sum(float(getattr(d, 'commission', 0) or 0) for d in dlist)
            total_swap       = sum(float(getattr(d, 'swap', 0) or 0) for d in dlist)
            total_pnl        = total_profit + total_commission + total_swap

            entry_deal = dlist[0]
            exit_deal  = dlist[-1]

            try:
                entry_magic = int(getattr(entry_deal, 'magic', 0) or 0)
            except Exception:
                entry_magic = 0
            is_authorized = entry_magic in authorized_tradeids
            auth_group = 'authorized' if is_authorized else 'unauthorized'

            trade_type = 'BUY' if entry_deal.type == 0 else 'SELL'
            mt5_action = mt5.ORDER_TYPE_BUY if entry_deal.type == 0 else mt5.ORDER_TYPE_SELL

            total_volume = float(getattr(entry_deal, 'volume', 0) or 0)
            entry_price  = float(getattr(entry_deal, 'price', 0) or 0)
            exit_price   = float(getattr(exit_deal,  'price', 0) or 0)

            sl_tp_rec = order_sl_tp.get(position_id, {})
            stoploss   = float(getattr(entry_deal, 'sl', 0) or 0) or sl_tp_rec.get('sl', 0.0)
            takeprofit = float(getattr(entry_deal, 'tp', 0) or 0) or sl_tp_rec.get('tp', 0.0)

            trade_risk = 0.0
            if stoploss > 0:
                calc = mt5_order_calc_profit(
                    mt5_action, entry_deal.symbol, total_volume,
                    entry_price, stoploss,
                )
                if calc is not None:
                    trade_risk = abs(float(calc))

            risk_reward = 0.0
            if stoploss > 0 and stoploss != entry_price and takeprofit > 0:
                risk_dist = abs(entry_price - stoploss)
                if risk_dist > 0:
                    risk_reward = round(abs(takeprofit - entry_price) / risk_dist, 2)

            comment = getattr(entry_deal, 'comment', '') or order_comments.get(position_id, '')
            if risk_reward == 0 and comment:
                rr = _extract_rr_from_comment(comment)
                if rr > 0:
                    risk_reward = rr

            close_ts = int(getattr(exit_deal, 'time', 0) or 0)

            master_trades.append({
                'ticket':         position_id,
                'symbol':         getattr(entry_deal, 'symbol', '') or '',
                'type':           trade_type,
                'entry_price':    round(entry_price, 5),
                'exit_price':     round(exit_price, 5),
                'stoploss':       round(stoploss, 5),
                'take_profit':    round(takeprofit, 5),
                'trade_risk':     round(trade_risk, 2),
                'risk_reward':    float(risk_reward),
                'volume':         round(total_volume, 2),
                'time_open':      _iso(getattr(entry_deal, 'time', 0)),
                'time_close':     _iso(close_ts),
                'closed_time':    _iso(close_ts),
                'magic':          entry_magic,
                'total_pnl':      round(total_pnl, 2),
                'state':          'CLOSED',
                'raw_close_time': close_ts,
                'auth_group':     auth_group,
                'comment':        comment,
            })

        stats['total_trades_grouped'] += len(master_trades)

        if not master_trades:
            print(f"  │ 📭 No grouped trades after filtering")
            continue

        # -------- build scalar analytics --------
        ordered = sorted(master_trades, key=lambda x: x['raw_close_time'])
        p_list = [t for t in ordered if t['total_pnl'] > 0]
        l_list = [t for t in ordered if t['total_pnl'] < 0]

        total_pnl_all = sum(t['total_pnl'] for t in ordered)
        p_rev = sum(t['total_pnl'] for t in p_list)
        l_rev = sum(t['total_pnl'] for t in l_list)

        highest_loss_per_trade = 0.0
        for t in ordered:
            if t['total_pnl'] < 0:
                v = abs(t['total_pnl'])
                if v > highest_loss_per_trade:
                    highest_loss_per_trade = v

        sl_tp   = sum(1 for t in ordered if t['stoploss'] > 0 and t['take_profit'] > 0)
        no_sl_tp = sum(1 for t in ordered if not (t['stoploss'] > 0 and t['take_profit'] > 0))

        # per-day counts
        per_day = {}
        for t in ordered:
            d = _day_key(t['raw_close_time'])
            if not d:
                continue
            per_day[d] = per_day.get(d, 0) + 1

        if per_day:
            values = list(per_day.values())
            lowest  = min(values)
            highest = max(values)
            average = round(sum(values) / len(values))
        else:
            lowest = highest = average = 0

        # per-week counts
        per_week = {}
        for t in ordered:
            w = _week_key(t['raw_close_time'])
            if not w:
                continue
            per_week[w] = per_week.get(w, 0) + 1

        if per_week:
            wvalues = list(per_week.values())
            wlowest  = min(wvalues)
            whighest = max(wvalues)
            waverage = round(sum(wvalues) / len(wvalues))
        else:
            wlowest = whighest = waverage = 0

        # drawdown
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in ordered:
            equity += t['total_pnl']
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd

        # consecutive losing trades
        max_loss_count = 0
        max_loss_amount = 0.0
        cur_count = 0
        cur_amount = 0.0
        for t in ordered:
            if t['total_pnl'] < 0:
                cur_count += 1
                cur_amount += abs(t['total_pnl'])
                if cur_count > max_loss_count:
                    max_loss_count = cur_count
                    max_loss_amount = cur_amount
                elif cur_count == max_loss_count and cur_amount > max_loss_amount:
                    max_loss_amount = cur_amount
            else:
                cur_count = 0
                cur_amount = 0.0

        # consecutive losing days
        day_pnl = {}
        for t in ordered:
            d = _day_key(t['raw_close_time'])
            if not d:
                continue
            day_pnl[d] = day_pnl.get(d, 0.0) + t['total_pnl']

        max_days = 0
        max_days_loss = 0.0
        cur_days = 0
        cur_days_loss = 0.0
        for d in sorted(day_pnl.keys()):
            if day_pnl[d] < 0:
                cur_days += 1
                cur_days_loss += abs(day_pnl[d])
                if cur_days > max_days:
                    max_days = cur_days
                    max_days_loss = cur_days_loss
                elif cur_days == max_days and cur_days_loss > max_days_loss:
                    max_days_loss = cur_days_loss
            else:
                cur_days = 0
                cur_days_loss = 0.0

        # symbols count + highest rr
        sym_set = set()
        highest_rr = 0.0
        for t in ordered:
            sym_set.add(t['symbol'])
            rr = t.get('risk_reward', 0) or 0
            if rr > highest_rr:
                highest_rr = rr

        # revenue split
        total_rev = abs(p_rev) + abs(l_rev)
        if total_rev > 0:
            p_pct = round((abs(p_rev) / total_rev) * 100.0, 2)
            l_pct = round((abs(l_rev) / total_rev) * 100.0, 2)
            rev_pct = round(p_pct - l_pct, 2)
            if rev_pct < 0:
                rev_pct = 0.0
        else:
            p_pct = l_pct = rev_pct = 0.0

        # -------- upsert investors_analytics --------
        _ensure_analytics_row(investor_id, sub_account_id)

        upd_sql = """
            UPDATE investors_analytics
               SET total_trades                               = %s,
                   total_pnl                                  = %s,
                   profit_trades                              = %s,
                   loss_trades                                = %s,
                   profit_amount                              = %s,
                   loss_amount                                = %s,
                   lowest_trades_per_day                      = %s,
                   highest_trades_per_day                     = %s,
                   average_trades_per_day                     = %s,
                   lowest_trades_per_week                     = %s,
                   highest_trades_per_week                    = %s,
                   average_trades_per_week                    = %s,
                   highest_loss_per_trade                     = %s,
                   highest_drawdown                           = %s,
                   symbols_traded                             = %s,
                   closed_deals_with_sl_tp                    = %s,
                   closed_deals_without_sl_tp                 = %s,
                   consecutive_losses_count                   = %s,
                   total_loss_pnl                             = %s,
                   consecutive_days_in_loss_count             = %s,
                   consecutive_days_in_loss_count_total_loss_pnl = %s,
                   revenue_percentage                         = %s,
                   revenue_profit_percentage                  = %s,
                   revenue_loss_percentage                    = %s,
                   recent_risk_reward                         = %s
             WHERE userid = %s
               AND sub_account_id = %s
        """
        params = [
            int(len(ordered)),
            round(total_pnl_all, 2),
            int(len(p_list)),
            int(len(l_list)),
            round(p_rev, 2),
            round(abs(l_rev), 2),
            int(lowest),
            int(highest),
            int(average),
            int(wlowest),
            int(whighest),
            int(waverage),
            round(highest_loss_per_trade, 2),
            round(max_dd, 2),
            int(len(sym_set)),
            int(sl_tp),
            int(no_sl_tp),
            int(max_loss_count),
            round(-max_loss_amount, 2),
            int(max_days),
            round(-max_days_loss, 2),
            round(rev_pct, 2),
            round(p_pct, 2),
            round(l_pct, 2),
            round(highest_rr, 4),
            investor_id,
            sub_account_id,
        ]
        ok, affected, msg = db_execute(upd_sql, params, timeout=20.0, quiet=True)
        if ok:
            stats['analytics_rows_upserted'] += 1
            print(f"  │ ✅ investors_analytics upserted "
                  f"(trades={len(ordered)}, pnl=${total_pnl_all:+.2f}, "
                  f"profit={len(p_list)}, loss={len(l_list)}, "
                  f"dd=${max_dd:.2f}, symbols={len(sym_set)})")
        else:
            print(f"  │ ✗ investors_analytics upsert failed: {msg}")
            stats['errors'].append(f"investor {investor_id}: analytics upsert: {msg}")

        # -------- write authorized/unauthorized trade rows --------
        def _write_trade_rows(table, trades):
            written = 0
            for t in trades:
                exists = db_fetch_one(
                    f"""
                    SELECT id FROM {table}
                     WHERE userid = %s
                       AND sub_account_id = %s
                       AND ticket = %s
                     LIMIT 1
                    """,
                    [investor_id, sub_account_id, int(t['ticket'])],
                    timeout=10.0, quiet=True,
                )
                if exists and _raw_first_key(exists, 'id'):
                    ok_up, _, _ = db_execute(
                        f"""
                        UPDATE {table}
                           SET symbol        = %s,
                               type          = %s,
                               volume        = %s,
                               entry         = %s,
                               exit_price    = %s,
                               stoploss      = %s,
                               target        = %s,
                               pnl           = %s,
                               risk_reward   = %s,
                               closed_time   = %s,
                               comment       = %s,
                               magic         = %s
                         WHERE id = %s
                        """,
                        [
                            t['symbol'], t['type'], t['volume'],
                            t['entry_price'], t['exit_price'],
                            t['stoploss'], t['take_profit'],
                            t['total_pnl'], t['risk_reward'],
                            t['closed_time'], t['comment'], t['magic'],
                            _coerce_int(_raw_first_key(exists, 'id')),
                        ],
                        timeout=15.0, quiet=True,
                    )
                    if ok_up:
                        written += 1
                else:
                    ok_ins, _, _ = db_execute(
                        f"""
                        INSERT INTO {table}
                            (userid, sub_account_id, ticket, symbol, type,
                             volume, entry, exit_price, stoploss, target,
                             pnl, risk_reward, closed_time, comment, magic)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s)
                        """,
                        [
                            investor_id, sub_account_id, int(t['ticket']),
                            t['symbol'], t['type'], t['volume'],
                            t['entry_price'], t['exit_price'],
                            t['stoploss'], t['take_profit'],
                            t['total_pnl'], t['risk_reward'],
                            t['closed_time'], t['comment'], t['magic'],
                        ],
                        timeout=15.0, quiet=True,
                    )
                    if ok_ins:
                        written += 1
            return written

        auth_trades   = [t for t in ordered if t['auth_group'] == 'authorized']
        unauth_trades = [t for t in ordered if t['auth_group'] == 'unauthorized']

        auth_written = _write_trade_rows('authorized_trades', auth_trades)
        stats['authorized_trades'] += len(auth_trades)
        stats['authorized_rows_written'] += auth_written
        print(f"  │ ✅ authorized_trades : {auth_written} row(s) written "
              f"({len(auth_trades)} trade(s))")

        if unauth_trades:
            unauth_written = _write_trade_rows('unauthorized_trades', unauth_trades)
            stats['unauthorized_trades'] += len(unauth_trades)
            stats['unauthorized_rows_written'] += unauth_written
            print(f"  │ ⚠️ unauthorized_trades: {unauth_written} row(s) written "
                  f"({len(unauth_trades)} trade(s))")
        else:
            print(f"  │ ✅ unauthorized_trades: none")

        stats['details'].append({
            'investor_id':          investor_id,
            'sub_account_id':       sub_account_id,
            'programme_id':         programme_id,
            'total_trades':         len(ordered),
            'authorized_trades':    len(auth_trades),
            'unauthorized_trades':  len(unauth_trades),
            'total_pnl':            round(total_pnl_all, 2),
            'highest_drawdown':     round(max_dd, 2),
            'symbols_traded':       len(sym_set),
        })

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\n{'='*10} 📊 TRADES ANALYTICS SUMMARY (DB) {'='*10}")
    print(f"  Investors processed        : {stats['investors_processed']}")
    print(f"  Investors skipped          : {stats['investors_skipped']}")
    print(f"  Programmes processed       : {stats['programmes_processed']}")
    print(f"  MT5 deals seen             : {stats['total_deals_seen']}")
    print(f"  Trades grouped             : {stats['total_trades_grouped']}")
    print(f"  Authorized trades          : {stats['authorized_trades']}  "
          f"(rows written {stats['authorized_rows_written']})")
    print(f"  Unauthorized trades        : {stats['unauthorized_trades']}  "
          f"(rows written {stats['unauthorized_rows_written']})")
    print(f"  investors_analytics upserts: {stats['analytics_rows_upserted']}")
    print(f"  Errors                     : {len(stats['errors'])}")
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
def process_single_investor_from_db_(job):
    """
    SOLO TEST PATH — runs:
        1. chunk_orders_with_volume_beyond_max_db(inv_db_id=...)
        2. place_usd_orders_db(inv_db_id=...)
        3. check_pending_orders_risk_db(inv_db_id=...)
        4. orders_reward_correction_db(inv_db_id=...)
        5. apply_dynamic_breakeven_db(inv_db_id=...)
        6. trades_analytics_db(inv_db_id=...)              ← NEW, at the end

    No restriction gate, no alarm gate, no cleanup, no grid.
    """

    global unauthorized_alert

    inv_db_id = job.get('investor_id')
    sub_id = job.get('sub_account_id')
    programme_id = job.get('programme_id')
    programme_name = job.get('programme_name') or ''

    print(f"\n[START][TEST] ⚙️ Full solo pipeline for "
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

        place_stats = run_stage(
            'place_usd_orders_db',
            place_usd_orders_db,
            inv_db_id=inv_db_id,
        )
        account_stats['stages']['place_usd_orders_db'] = place_stats
        account_stats['place_stats'] = place_stats

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

def process_single_investor_from_db(job):
    """
    DB version of process_single_investor_local().

    Stage order (mirrors the LOCAL file, minus grid):
        gate 1 (restriction)
        gate 2 (alarm)
        else:
            check_and_record_unauthorized_actions_db
            calculate_investor_symbols_orders_db
            chunk_orders_with_volume_beyond_max_db
            martingale_system_db
            place_usd_orders_db
            check_pending_orders_risk_db
            orders_reward_correction_db
            apply_dynamic_breakeven_db
            trades_analytics_db              ← NEW, at the very end

    No JSON. No local folders. No grid logic.
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
        # ACCOUNT INFO / TYPE
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
        # A1. Unauthorized-actions audit
        # ------------------------------------------------------------------
        audit_stats_top = run_stage(
            'check_and_record_unauthorized_actions_db',
            check_and_record_unauthorized_actions_db,
            inv_db_id=inv_db_id,
        )
        account_stats['stages']['check_and_record_unauthorized_actions_db_top'] = audit_stats_top
        account_stats['unauthorized_actions_stats_top'] = audit_stats_top

        # ------------------------------------------------------------------
        # A2. CALCULATE INVESTOR SYMBOLS ORDERS
        # ------------------------------------------------------------------
        calc_stats = run_stage(
            'calculate_investor_symbols_orders_db',
            calculate_investor_symbols_orders_db,
            inv_db_id=inv_db_id,
        )
        account_stats['stages']['calculate_investor_symbols_orders_db'] = calc_stats
        account_stats['calculate_stats'] = calc_stats

        # ------------------------------------------------------------------
        # A3. CHUNK ORDERS WITH VOLUME BEYOND MAX
        # ------------------------------------------------------------------
        chunk_stats = run_stage(
            'chunk_orders_with_volume_beyond_max_db',
            chunk_orders_with_volume_beyond_max_db,
            inv_db_id=inv_db_id,
        )
        account_stats['stages']['chunk_orders_with_volume_beyond_max_db'] = chunk_stats
        account_stats['chunk_stats'] = chunk_stats

        # ------------------------------------------------------------------
        # A4. MARTINGALE
        # ------------------------------------------------------------------
        martingale_stats = run_stage(
            'martingale_system_db',
            martingale_system_db,
            inv_db_id=inv_db_id,
        )
        account_stats['stages']['martingale_system_db'] = martingale_stats
        account_stats['martingale_stats'] = martingale_stats

        # ------------------------------------------------------------------
        # A5. PLACE USD ORDERS
        # ------------------------------------------------------------------
        place_stats = run_stage(
            'place_usd_orders_db',
            place_usd_orders_db,
            inv_db_id=inv_db_id,
        )
        account_stats['stages']['place_usd_orders_db'] = place_stats
        account_stats['place_stats'] = place_stats

        # ------------------------------------------------------------------
        # A6. CHECK PENDING ORDERS RISK
        # ------------------------------------------------------------------
        risk_stats = run_stage(
            'check_pending_orders_risk_db',
            check_pending_orders_risk_db,
            inv_db_id=inv_db_id,
        )
        account_stats['stages']['check_pending_orders_risk_db'] = risk_stats
        account_stats['pending_risk_stats'] = risk_stats

        # ------------------------------------------------------------------
        # A7. ORDERS REWARD CORRECTION
        # ------------------------------------------------------------------
        reward_stats = run_stage(
            'orders_reward_correction_db',
            orders_reward_correction_db,
            inv_db_id=inv_db_id,
        )
        account_stats['stages']['orders_reward_correction_db'] = reward_stats
        account_stats['reward_correction_stats'] = reward_stats

        # ------------------------------------------------------------------
        # A8. APPLY DYNAMIC BREAKEVEN
        # ------------------------------------------------------------------
        breakeven_stats = run_stage(
            'apply_dynamic_breakeven_db',
            apply_dynamic_breakeven_db,
            inv_db_id=inv_db_id,
        )
        account_stats['stages']['apply_dynamic_breakeven_db'] = breakeven_stats
        account_stats['breakeven_stats'] = breakeven_stats

        # ------------------------------------------------------------------
        # A9. TRADES ANALYTICS DB                ← NEW, VERY LAST STAGE
        # ------------------------------------------------------------------
        analytics_stats = run_stage(
            'trades_analytics_db',
            trades_analytics_db,
            inv_db_id=inv_db_id,
        )
        account_stats['stages']['trades_analytics_db'] = analytics_stats
        account_stats['analytics_stats'] = analytics_stats

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
