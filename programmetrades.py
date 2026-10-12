# programmetrades.py
"""
Programme-scoped trade pipeline orchestrator.

Currently ships ONLY the restricted-timerange stage. Future functions
(candle fetch, crosser analysis, liquidator, ranging, order placement,
risk audit, etc.) will be dropped into process_single_investor() in the
priority order shown by the commented section.

ARCHITECTURE
------------
* Same bridge pattern as brokerdetails.py: this file is a TCP CLIENT of
  the long-running mysqlremote.py bridge. It does NOT launch Chrome.
* The DATABASE is the source of truth. No local folder scanning, no JSON
  reads, no JSON writes.
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


def resolve_investor_terminal_path(inv_id, sub_id):
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
        [inv_id, sub_id], timeout=10.0, quiet=True,
    )
    if not row:
        print(f"[MT5-PATH] no harvhub row for investor={inv_id} sub={sub_id}")
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
            server_v, login_v, inv_id, sub_id
        )
        if os.path.isfile(terminal_exe):
            print(f"[MT5-PATH] rebuilt from server+login = {terminal_exe}")
            # Write back to DB so next run doesn't have to rebuild
            try:
                db_execute(
                    "UPDATE harvhub SET Terminal_path = %s "
                    "WHERE id = %s AND sub_account_id = %s",
                    [terminal_exe, inv_id, sub_id],
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
        inv_id = _coerce_int(_pick_first_key(row, 'investor_id'))
        sub_id = _coerce_int(_pick_first_key(row, 'investor_sub_account_id'))
        if inv_id is None or inv_id <= 0 or sub_id is None or sub_id <= 0:
            continue
        key = (inv_id, sub_id)
        if key in seen:
            continue
        seen.add(key)
        out.append({'investor_id': inv_id, 'sub_account_id': sub_id})
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
            inv_id = inv['investor_id']
            sub_id = inv['sub_account_id']
            key = (inv_id, sub_id, programme_id)
            if key in seen:
                continue
            seen.add(key)
            jobs.append({
                'investor_id':    inv_id,
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
#  RESTRICTED TIMERANGE — Restricted Dates FIRST, then Restricted Days
#  (DETAILED VERSION — restored)
# ==============================================================================
def restricted_timerange(inv_id=None):
    print(f"\n{'='*10} ⏰ PROGRAMME RESTRICTED TIMERANGE {'='*10}")

    local_ip = get_local_ip()
    if not local_ip:
        print("  ⚠️ Could not determine local IP")
        return {
            'investor_id': inv_id if inv_id else 'all',
            'processing_success': False,
            'errors': ['local IP unknown'],
        }

    print(f"  🌐 Local IP: {local_ip}")

    programmes = fetch_vps_programmes(local_ip)
    if not programmes:
        print("  ℹ️ No programmes bound to this VPS")
        return {
            'investor_id': inv_id if inv_id else 'all',
            'processing_success': True,
            'programmes_checked': 0,
        }

    total_programmes = len(programmes)
    print(f"  📋 Found {total_programmes} programme(s) bound to this VPS")

    for idx, prog in enumerate(programmes, start=1):
        programme_id = prog['programme_id']
        developer_id = prog['userid']

        programme_name = fetch_programme_name(programme_id)
        tz_str = fetch_programme_timezone(programme_id)

        if tz_str is None:
            print(f"\n  [{idx}/{total_programmes}] 📊 Programme "
                  f"'{programme_name}' (id={programme_id}) | "
                  f"⚠️ timezone NOT configured — skipping restriction check")
            continue

        now_local, resolved = get_current_time_in_timezone(tz_str)
        if not resolved:
            print(f"\n  [{idx}/{total_programmes}] 📊 Programme "
                  f"'{programme_name}' (id={programme_id}) | "
                  f"⚠️ Could not resolve timezone '{tz_str}' "
                  f"— skipping restriction check")
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
            # Stage 1 wins — full-day lockout. Skip day-of-week evaluation.
            print(f"      🚨 {today_date_str} IS a restricted date "
                  f"— FULL-DAY LOCKOUT (Stage 1)")
            day_state = "full_day_date"
            window_desc = "FULL DAY (restricted date)"
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
            elif today_row is None:
                print(f"      ✅ {now_day_name} is NOT restricted for this programme")
                day_state = "not_today"
                window_desc = "—"
            else:
                from_h, from_m = parse_time_string(today_row['from_time'])
                to_h, to_m = parse_time_string(today_row['to_time'])

                if from_h is None or to_h is None:
                    print(f"      ⚠️ Invalid time format for today's row: "
                          f"{today_row['from_time']} -> {today_row['to_time']}")
                    day_state = "invalid"
                    window_desc = "invalid"
                elif is_full_day_window(from_h, from_m, to_h, to_m):
                    print(f"      🚨 {now_day_name} is FULLY RESTRICTED "
                          f"(no trading allowed all day)")
                    day_state = "full_day"
                    window_desc = "12:00 AM - 12:00 AM (FULL DAY)"
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

            # Print day list for this programme
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
        # Per-investor printing
        # =====================================================================
        investors = fetch_active_investors_for_programme(programme_id)
        if not investors:
            print(f"      ℹ️ No ACTIVE investors associated with this programme")
            continue

        print(f"      👥 {len(investors)} active investor(s) associated:")

        for inv in investors:
            inv_id_val = inv['investor_id']
            sub_id_val = inv['sub_account_id']

            if inv_id is not None:
                try:
                    if str(inv_id_val) != str(inv_id):
                        continue
                except Exception:
                    pass

            identity = fetch_investor_identity(inv_id_val)
            username = (identity.get('username')
                        or identity.get('fullname')
                        or f"user{inv_id_val}")

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
        'investor_id': inv_id if inv_id else 'all',
        'processing_success': True,
        'programmes_checked': total_programmes,
    }


# ==============================================================================
#  RECENT HIGHEST BALANCE TARGET — DB-driven, programme-scoped
# ==============================================================================
def recent_highest_balance_target(inv_id=None):
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
        'investor_id': inv_id if inv_id else "all",
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
    if inv_id:
        print(f" 🎯 Target Investor: {inv_id}")

    stats = {
        "investor_id": inv_id if inv_id else "all",
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
        """Fetch the harvhub row for this investor + sub-account."""
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
        """
        Read `programme_revenue_target` and reshape into the same dict
        structure that the old JSON daily_target_config used.
        """
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
        """
        Upsert into daily_target_revenue for this investor sub-account.
        Match key: (userid, sub_account_id, week, day, date).

        Also persists the per-investor handoff fields:
          - daily_target_owed
          - daily_target_owed_day_balance
          - daily_target_owed_date
        These are investor-level totals, so they are written to every
        day row produced in this run. Downstream consumers read the
        latest row by date to obtain the current values.
        """
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
                                      inv_id=None, starting_balance_for_today=None,
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
    # ENUMERATE INVESTORS (DB-driven, same pattern as restricted_timerange)
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

    if inv_id:
        jobs = [j for j in all_jobs if str(j.get('investor_id')) == str(inv_id)]
        if not jobs:
            print(f" ⚠️ Investor {inv_id} not found in any VPS-scoped job")
            stats["errors"].append(f"Investor {inv_id} not found")
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
        inv_id_db = job.get('investor_id')
        sub_id_db = job.get('sub_account_id')
        programme_id = job.get('programme_id')
        programme_name = job.get('programme_name') or f"programme_{programme_id}"

        inv_id_str = str(inv_id_db)

        print(f"\n{'─'*80}")
        print(f" 📊 INVESTOR: {inv_id_db} (sub {sub_id_db}) | Programme: {programme_name} (id={programme_id})")
        print(f"{'─'*80}")

        # ============================================================
        # SECTION 0: PROGRAMME CONTEXT
        # ============================================================
        identity = fetch_investor_identity(inv_id_db)
        username = (identity.get('username')
                    or identity.get('fullname')
                    or f"user{inv_id_db}")

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
            print(f"  ⚠️ Could not get MT5 balance - Skipping investor {inv_id_db}")
            stats["errors"].append(f"Could not get MT5 balance for {inv_id_db}")
            stats["investors_skipped"] += 1
            continue

        print(f"  💰 Current MT5 Balance: ${mt5_balance:.2f}")

        # --- Fetch the harvhub row for this investor + sub-account ---
        hub_row = db_get_harvhub_row(inv_id_db, sub_id_db)
        if not hub_row:
            print(f"  ⚠️ No harvhub row found for id={inv_id_db} sub={sub_id_db} - skipping")
            stats["errors"].append(f"No harvhub row for {inv_id_db}/{sub_id_db}")
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

        # ------------------------------------------------------------------
        # START-OF-DAY BALANCE GUARD
        # ------------------------------------------------------------------
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

        # ------------------------------------------------------------------
        # STALE RECORD GUARD
        # ------------------------------------------------------------------
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

            db_write_recent_balance(inv_id_db, sub_id_db, round(reset_balance, 2), yesterday_str)

            existing_recent = reset_balance
            existing_last_update = yesterday_str
            stats["stale_record_resets"] += 1
            has_updates = True

            print(f"     ✅ Record reset complete")

        # Initialize if doesn't exist
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
                'investor_id': inv_id_db,
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

            db_write_recent_balance(inv_id_db, sub_id_db, round(init_balance, 2), yesterday_str)
            print(f"  💾 Recent highest balance initialised for {username} sub account {sub_id_db}: "
                  f"${init_balance:.2f} on {yesterday_str}")

            stats["investors_updated"] += 1
            stats["investors_checked"] += 1
            stats["field_created"] += 1
            has_updates = True
            continue

        # Check if MT5 balance > stored recent_highest_balance
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

            db_write_recent_balance_balance_only(inv_id_db, sub_id_db, round(mt5_balance, 2))
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

        # Starting balance from harvhub.broker_balance (contract anchor)
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

        # ---- Halter recovery check (compare LIVE MT5 balance vs C) ----
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
            inv_id_db,
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

        # ------------------------------------------------------------------
        # HANDOFF FIELDS (persisted to daily_target_revenue)
        # ------------------------------------------------------------------
        # daily_target_owed             -> combined owed debt
        # daily_target_owed_day_balance -> anchor day balance if halter found,
        #                                  otherwise the contract-aware start
        #                                  balance (falls back so downstream
        #                                  consumers always get a meaningful
        #                                  number even with no halter yet)
        # daily_target_owed_date        -> halter anchor date (NULL if none)
        # ------------------------------------------------------------------
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

        # ============================================================
        # WRITE daily_target_revenue ROWS (per investor sub-account)
        #   -> now also persists the handoff fields:
        #        daily_target_owed
        #        daily_target_owed_day_balance
        #        daily_target_owed_date
        # ============================================================
        rows_written = 0
        for week_key, week_data in weekly_targets.items():
            for day_name, day_data in week_data.items():
                status = day_data['status']
                target = day_data['daily_target']
                allocated = day_data['profit_allocated']
                remaining = day_data.get('remaining_needed', 0.0)
                date_str = day_data['date']

                ok = db_upsert_daily_target_row(
                    userid=inv_id_db,
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
                'investor_id': inv_id_db,
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

            db_write_recent_balance(inv_id_db, sub_id_db,
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
                'investor_id': inv_id_db,
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
            "investor_id": inv_id_db,
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

    if recent_highest_alert['is_triggered']:
        print(f"\n  🚨 ALARM ACTIVE: {recent_highest_alert['investor_id']} - Trading SUSPENDED")

    print(f"{'='*10} 🏁 COMPLETE {'='*10}\n")

    stats["processing_success"] = True
    return stats

# ==============================================================================
#  STAGE RUNNER — isolate any future stage failure
# ==============================================================================
def run_stage(name, fn, **kwargs):
    """
    Run a single stage function safely.

    - Any exception is caught, logged, and returned as a stage result
      with processing_success=False so the orchestrator keeps going.
    - The returned dict is stored under account_stats['stages'][name].
    """
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
    """
    Run a list of (name, fn) pairs in order, sharing common kwargs.
    Returns dict {name: stage_result}.
    """
    out = {}
    for name, fn in stages:
        out[name] = run_stage(name, fn, **common_kwargs)
    return out


# ==============================================================================
#  WORKER: one process per investor job (DB-driven)
# ==============================================================================
def process_single_investor(job):
    inv_id = job.get('investor_id')
    sub_id = job.get('sub_account_id')
    programme_id = job.get('programme_id')
    programme_name = job.get('programme_name') or ''

    print(f"\n[START] ⚙️ Investor {inv_id} (sub {sub_id}) | "
          f"programme '{programme_name}' (id={programme_id})")

    account_stats = {
        'investor_id':   inv_id,
        'sub_account_id': sub_id,
        'programme_id':  programme_id,
        'success': False,
        'stages': {},
    }

    _worker_init()

    # ------------------------------------------------------------------
    # MT5 CONNECT — must happen BEFORE any stage that reads MT5 state.
    # Uses the REBRANDED terminal-path resolution (mirrors brokerdetails.py):
    #   1. harvhub.Terminal_path — if the file exists on disk
    #   2. Rebuild from server+login using brokerdetails' formula
    # ------------------------------------------------------------------
    mt5_ok = False
    try:
        terminal_path = resolve_investor_terminal_path(inv_id, sub_id)
        print(f"[MT5-PATH] final resolved terminal = {terminal_path}")

        mt5_ok = mt5_connect(terminal_path=terminal_path, timeout_ms=15000)
        if mt5_ok:
            print(f"[MT5] ✅ Connected "
                  f"({'custom path' if terminal_path else 'default install'}) "
                  f"for investor {inv_id} (sub {sub_id})")
        else:
            print(f"[MT5] ⚠️ mt5_connect returned False "
                  f"(last_error={mt5_last_error()})")
    except Exception as e:
        print(f"[MT5] ⚠️ mt5_connect raised: {e}")
        mt5_ok = False

    try:
        # =====================================================================
        # 1. RESTRICTED TIMERANGE (Restricted Dates first, then Days)
        # =====================================================================
        timerange_stats = run_stage(
            'restricted_timerange',
            restricted_timerange,
            inv_id=inv_id,
        )
        account_stats['stages']['restricted_timerange'] = timerange_stats
        account_stats['restricted_timerange_stats'] = timerange_stats

        # =====================================================================
        # 2. RECENT HIGHEST BALANCE TARGET + DAILY TARGET REVENUE (DB-driven)
        # =====================================================================
        recent_balance_stats = run_stage(
            'recent_highest_balance_target',
            recent_highest_balance_target,
            inv_id=inv_id,
        )
        account_stats['stages']['recent_highest_balance_target'] = recent_balance_stats
        account_stats['recent_highest_balance_stats'] = recent_balance_stats

        account_stats['success'] = bool(
            timerange_stats.get('processing_success', False)
            and recent_balance_stats.get('processing_success', False)
        )

        # =====================================================================
        # FUTURE FUNCTIONS — insert here, in priority order.
        # =====================================================================
        #
        # from programmetrades_impl import (
        #     fetch_ohlc_data_for_investor,
        #     directional_bias,
        #     additional_candles_for_orders_limitation,
        #     create_position_hedge,
        #     symbols_dynamic_grid_prices,
        #     manage_each_direction_levels_count_in_json,
        #     deduplicate_orders,
        #     validate_strategy_authorized_orders,
        #     backup_limit_orders,
        #     populate_orders_missing_fields,
        #     calculate_investor_symbols_orders,
        #     live_usd_risk_and_scaling,
        #     apply_default_prices,
        #     martingale_system,
        #     padding_stoploss_below_minimum_risk_to_maximum_risk,
        #     maximum_risk_distance_and_adjust_to_max_risk_distance_no_removal,
        #     pending_orders_per_symbol_limitation,
        #     chunk_orders_with_volume_beyond_max,
        #     place_usd_orders,
        #     manage_position_and_pending_orders,
        #     manage_single_position_and_pending,
        #     close_unauthorized_orders,
        #     orders_reward_correction,
        #     check_pending_orders_risk,
        #     apply_dynamic_breakeven,
        #     check_and_record_unauthorized_actions,
        #     trades_analytics,
        # )
        #
        # ---------------------------------------------------------------------
        # Always-run stages:
        # ---------------------------------------------------------------------
        # account_stats['stages']['check_and_record_unauthorized_actions'] = run_stage(
        #     'check_and_record_unauthorized_actions',
        #     check_and_record_unauthorized_actions,
        #     inv_id=inv_id,
        # )
        #
        # ---------------------------------------------------------------------
        # OHLC / directional bias block (when enabled):
        # ---------------------------------------------------------------------
        # account_stats['stages']['additional_candles_for_orders_limitation_1'] = run_stage(
        #     'additional_candles_for_orders_limitation_1',
        #     additional_candles_for_orders_limitation,
        #     inv_id=inv_id,
        # )
        # account_stats['stages']['fetch_ohlc_data_for_investor'] = run_stage(
        #     'fetch_ohlc_data_for_investor',
        #     fetch_ohlc_data_for_investor,
        #     inv_id=inv_id,
        # )
        # account_stats['stages']['directional_bias'] = run_stage(
        #     'directional_bias',
        #     directional_bias,
        #     inv_id=inv_id,
        # )
        # account_stats['stages']['additional_candles_for_orders_limitation_2'] = run_stage(
        #     'additional_candles_for_orders_limitation_2',
        #     additional_candles_for_orders_limitation,
        #     inv_id=inv_id,
        # )
        # account_stats['stages']['create_position_hedge'] = run_stage(
        #     'create_position_hedge',
        #     create_position_hedge,
        #     inv_id=inv_id,
        # )
        #
        # ---------------------------------------------------------------------
        # Grid block (when enabled):
        # ---------------------------------------------------------------------
        # account_stats['stages']['symbols_dynamic_grid_prices'] = run_stage(
        #     'symbols_dynamic_grid_prices',
        #     symbols_dynamic_grid_prices,
        #     inv_id=inv_id,
        # )
        # account_stats['stages']['manage_each_direction_levels_count_in_json'] = run_stage(
        #     'manage_each_direction_levels_count_in_json',
        #     manage_each_direction_levels_count_in_json,
        #     inv_id=inv_id,
        # )
        #
        # ---------------------------------------------------------------------
        # Order pipeline:
        # ---------------------------------------------------------------------
        # account_stats['stages']['deduplicate_orders'] = run_stage(
        #     'deduplicate_orders', deduplicate_orders, inv_id=inv_id,
        # )
        # account_stats['stages']['validate_strategy_authorized_orders'] = run_stage(
        #     'validate_strategy_authorized_orders',
        #     validate_strategy_authorized_orders, inv_id=inv_id,
        # )
        # account_stats['stages']['backup_limit_orders'] = run_stage(
        #     'backup_limit_orders', backup_limit_orders, inv_id=inv_id,
        # )
        # account_stats['stages']['populate_orders_missing_fields'] = run_stage(
        #     'populate_orders_missing_fields',
        #     populate_orders_missing_fields, inv_id=inv_id,
        # )
        # account_stats['stages']['calculate_investor_symbols_orders'] = run_stage(
        #     'calculate_investor_symbols_orders',
        #     calculate_investor_symbols_orders, inv_id=inv_id,
        # )
        # account_stats['stages']['live_usd_risk_and_scaling'] = run_stage(
        #     'live_usd_risk_and_scaling',
        #     live_usd_risk_and_scaling, inv_id=inv_id,
        # )
        # account_stats['stages']['apply_default_prices'] = run_stage(
        #     'apply_default_prices', apply_default_prices, inv_id=inv_id,
        # )
        # account_stats['stages']['martingale_system'] = run_stage(
        #     'martingale_system', martingale_system, inv_id=inv_id,
        # )
        # account_stats['stages']['padding_stoploss_below_minimum_risk_to_maximum_risk'] = run_stage(
        #     'padding_stoploss_below_minimum_risk_to_maximum_risk',
        #     padding_stoploss_below_minimum_risk_to_maximum_risk,
        #     inv_id=inv_id,
        # )
        # account_stats['stages']['maximum_risk_distance_and_adjust_to_max_risk_distance_no_removal'] = run_stage(
        #     'maximum_risk_distance_and_adjust_to_max_risk_distance_no_removal',
        #     maximum_risk_distance_and_adjust_to_max_risk_distance_no_removal,
        #     inv_id=inv_id,
        # )
        # account_stats['stages']['pending_orders_per_symbol_limitation'] = run_stage(
        #     'pending_orders_per_symbol_limitation',
        #     pending_orders_per_symbol_limitation, inv_id=inv_id,
        # )
        # account_stats['stages']['chunk_orders_with_volume_beyond_max'] = run_stage(
        #     'chunk_orders_with_volume_beyond_max',
        #     chunk_orders_with_volume_beyond_max, inv_id=inv_id,
        # )
        # account_stats['stages']['place_usd_orders'] = run_stage(
        #     'place_usd_orders', place_usd_orders, inv_id=inv_id,
        # )
        #
        # ---------------------------------------------------------------------
        # Grid runtime block (when enabled):
        # ---------------------------------------------------------------------
        # account_stats['stages']['manage_position_and_pending_orders'] = run_stage(
        #     'manage_position_and_pending_orders',
        #     manage_position_and_pending_orders, inv_id=inv_id,
        # )
        # account_stats['stages']['manage_single_position_and_pending'] = run_stage(
        #     'manage_single_position_and_pending',
        #     manage_single_position_and_pending, inv_id=inv_id,
        # )
        #
        # ---------------------------------------------------------------------
        # Closing / cleanup:
        # ---------------------------------------------------------------------
        # account_stats['stages']['close_unauthorized_orders'] = run_stage(
        #     'close_unauthorized_orders', close_unauthorized_orders, inv_id=inv_id,
        # )
        # account_stats['stages']['orders_reward_correction'] = run_stage(
        #     'orders_reward_correction', orders_reward_correction, inv_id=inv_id,
        # )
        # account_stats['stages']['check_pending_orders_risk'] = run_stage(
        #     'check_pending_orders_risk', check_pending_orders_risk, inv_id=inv_id,
        # )
        # account_stats['stages']['apply_dynamic_breakeven'] = run_stage(
        #     'apply_dynamic_breakeven', apply_dynamic_breakeven, inv_id=inv_id,
        # )
        # account_stats['stages']['check_and_record_unauthorized_actions_final'] = run_stage(
        #     'check_and_record_unauthorized_actions_final',
        #     check_and_record_unauthorized_actions, inv_id=inv_id,
        # )
        # account_stats['stages']['trades_analytics'] = run_stage(
        #     'trades_analytics', trades_analytics, inv_id=inv_id,
        # )

    except Exception as e:
        print(f"[CRITICAL ERROR] investor={inv_id}: {e}")
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
                    pool.apply_async(process_single_investor, args=(job,))
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