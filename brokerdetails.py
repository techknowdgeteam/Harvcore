# brokerdetails.py
"""
Handles MT5 broker detection for two independent account families:

    [SA]   sub-accounts / investors        (harvhub table)
    [PRG]  programme / trader accounts     (programme table)

Rules:
  * Read-only IPC probe (initialize with portable=True -> account_info ->
    shutdown). NEVER call mt5.login().
  * Two passes run every loop for EACH family:

      1. Disconnect-request pass
         For every row with disconnect_broker_request = 1:
           - Glob MT5_DESTINATION_PATH for every folder whose name ends in
             "_{U<user_id>_SA<sub_account_id>}" (SA)
             or "_{U<user_id>_P<programme_id>}"   (PRG).
           - For each matched folder:
               * kill every MT5 process (terminal64.exe, metatester64.exe,
                 mt5liveupdate.exe, metaeditor64.exe) — not just the ones
                 inside the folder, because MT5 helpers can hold files
                 from anywhere,
               * wait until the processes are gone,
               * try shutil.rmtree up to 10 times with 3s between retries,
               * if that fails, try `cmd /c rmdir /s /q "folder"`,
               * if that fails, rename the folder out of the way.
           - Only when every folder is gone: clear the flag and fire the
             "disconnection complete" notification.

      2. Normal owner + follower probe pass

    The two families are processed independently — a failing programme
    broker never stops an investor probe and vice versa.

Valid-credentials rule (both families)
--------------------------------------
  `broker_login_status = 'valid_credentials'` means "we already told the
  user this terminal is live". It must NOT short-circuit the probe.

  Every loop still:
      1. ensures the folder exists and launches the terminal if needed,
      2. probes the terminal via IPC,
      3. verifies the terminal login matches the DB login,
      4. verifies the terminal account name matches the HarvHub name.

  After probing:

      probe OK + row already 'valid_credentials'
          -> silent keep. Log OK-NO-EMAIL. No DB write. No email.

      probe OK + row NULL/empty
          -> stamp 'valid_credentials', reset attempts, fire success
             email ONCE, log OK-NEW.

      probe NOT ok (no session / wrong login / wrong name / unreachable)
          -> hand off to the manual-login window so the user can log in
             and confirm. No email, no DB changes on the failure path.

  Failure statuses (invalid_credentials, fullname_mismatch, and for
  SA-only: invalid_account) are still skipped — the terminal was already
  deleted and the user already notified.

Programme account demo rule
---------------------------
  Programme accounts are analysis-only. Demo accounts ARE allowed.
  The programme broker pass will never mark an account as
  `invalid_account` and will never delete a terminal because it's
  detected as demo. It just reports demo/real in the logs and in the
  success notification body.

VPS bindings — investor vs programme
------------------------------------
  The `vps` table has three possible binding shapes:

      (A) user_id + sub_account_id + programme_id IS NULL
          -> investor / sub-account candidate for the [SA] pass.

      (B) user_id + programme_id IS NOT NULL
          -> programme pinned to this VPS. Feeds the [PRG] pass
             directly by `programme.id`, independent of the investor
             row. `sub_account_id` is ignored here.

      (C) user_id only (legacy row with sub_account_id = 0 or NULL
          and no programme_id)
          -> still treated as an investor candidate for backwards
             compatibility (sub_id defaults to user_id).

  Programme candidates are gathered from BOTH:
      * rows with `programme_id IS NOT NULL` (option B above), and
      * the legacy fallback `_fetch_programmes_for_owner(uid)` for any
        vps owner who does not have a pinned programme row.
  A dedup set makes sure each `programme.id` is probed at most once
  per loop.

harvhub schema note
-------------------
`harvhub` has no `user_id` column. Match on:
    harvhub.id             = <user_id>
    harvhub.sub_account_id = <sub_account_id>

programme schema note
---------------------
`programme` has NO `email` column. Owner email is resolved from
`harvhub` via `programme.userid -> harvhub.id -> harvhub.email`.
The `_resolve_programme_owner_email` helper encapsulates that lookup,
and `_fetch_programme_row_for_notify` injects the resolved value into
the row dict so downstream notification helpers keep working.

Folder naming
-------------
  Investor / sub-account:  <server>_<login>_U<user_id>_SA<sub_account_id>
  Programme / trader:      <server>_<login>_U<user_id>_P<programme_id>
"""

import os
import re
import sys
import time
import shutil
import socket
import threading
import subprocess
import traceback
from datetime import datetime

import tkinter as tk
from tkinter import ttk

import mysqlremote as db

import notification_service as notifier

try:
    import MetaTrader5 as mt5
except Exception:
    mt5 = None


# ==============================================================================
#  CONFIG
# ==============================================================================
DEFAULT_MT5_PATH     = r"C:\xampp\htdocs\harvcore\mt5\MetaTrader 5"
MT5_DESTINATION_PATH = r"C:\xampp\htdocs\harvcore\mt5"

MANUAL_POLL_INTERVAL = 1.0
COPY_FEEDBACK_MS     = 1200

TERMINAL_BOOT_WAIT   = 6.0

# MT5 process image names we always kill before trying to delete a folder.
MT5_PROCESS_NAMES = (
    'terminal64.exe',
    'metatester64.exe',
    'mt5liveupdate.exe',
    'metaeditor64.exe',
)

# How long to wait for a killed process to disappear.
TERMINAL_KILL_WAIT_TOTAL = 15.0
TERMINAL_KILL_POLL       = 0.5

# Folder deletion retry policy.
DELETE_RETRY_COUNT = 10
DELETE_RETRY_WAIT  = 3.0

TERMINAL_NEGATIVE_STATUSES = (
    'invalid_credentials',
    'fullname_mismatch',
    'invalid_account',
)

# Programme broker: demo accounts are allowed by default, so only these
# two failure statuses ever apply.
PROGRAMME_NEGATIVE_STATUSES = (
    'invalid_credentials',
    'fullname_mismatch',
)

# A row with this status is already confirmed live AND the user was
# already emailed. The probe still runs every loop; only the email is
# suppressed on repeats.
VALID_STATUS = 'valid_credentials'

CREATE_NO_WINDOW = 0x08000000


# ==============================================================================
#  Local IP
# ==============================================================================
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
#  DB wrapper
# ==============================================================================
def db_query(sql, params=None, timeout=20.0, quiet=False):
    start = time.perf_counter()
    db.queryrequest.put({'sql': sql, 'params': params, 'timeout': timeout})

    try:
        result = db.queryresult.get(timeout=timeout + 30.0)
    except Exception as e:
        return {
            'status': 'error',
            'message': f'Timed out waiting for queryresult: {e}',
            'results': [], 'affected_rows': 0,
            'query_id': None, 'raw_sql': sql,
            'elapsed': time.perf_counter() - start,
        }

    if not quiet and result.get('status') != 'success':
        print(f"      [SQL FAIL] {result.get('message')}")
        print(f"      [SQL WAS ] {sql.strip()[:200]}")
        print(f"      [PARAMS  ] {params}")

    return result


_PDO = notifier.make_pdo(db_query)


# ==============================================================================
#  Helpers
# ==============================================================================
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


def _is_empty(value) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in ('', 'null', 'none', 'nan')


def _sanitize_folder_component(value):
    if value is None:
        return ''
    s = str(value).strip()
    s = re.sub(r'[<>:"/\\|?*]', '_', s)
    s = s.replace(' ', '_')
    return s


def _expected_fullname_from_row(row):
    first = (_pick_first_key(row, 'first_name') or '').strip()
    last  = (_pick_first_key(row, 'last_name')  or '').strip()
    if first or last:
        return (first + ' ' + last).strip()
    full = (_pick_first_key(row, 'fullname') or '').strip()
    return full


def _name_tokens(value):
    return set(re.findall(r'[a-z0-9]+', (value or '').lower()))


def _name_flat(value):
    return re.sub(r'[^a-z0-9]+', '', (value or '').lower())


def _names_match(expected, actual):
    e = (expected or '').strip().lower()
    a = (actual or '').strip().lower()
    if not e or not a:
        return True
    if _name_tokens(e) & _name_tokens(a):
        return True
    e_flat = _name_flat(e)
    a_flat = _name_flat(a)
    if e_flat and a_flat and (e_flat in a_flat or a_flat in e_flat):
        return True
    return False


def _normalize_row(row):
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
#  harvhub column whitelist
# ==============================================================================
HARVHUB_SELECT_COLUMNS = [
    'id',
    'main_account_id',
    'sub_account_id',
    'sub_account_name',
    'is_main_account',
    'broker',
    'email',
    'fullname',
    'first_name',
    'last_name',
    'username',
    'server',
    'login',
    'broker_password',
    'application_status',
    'broker_balance',
    'recent_highest_balance',
    'balance_verification',
    'profitandloss',
    'balance_display',
    'execution_start_date',
    'loyalties',
    'reset_contract',
    'contract_id',
    'account_mode',
    'demo_account',
    'Terminal_path',
    'broker_login_status',
    'broker_login_attempt_used',
    'broker_total_login_attempt',
    'disconnect_broker_request',
]


def _broker_select_sql():
    return ', '.join(HARVHUB_SELECT_COLUMNS)


# ==============================================================================
#  programme column whitelist
#  -------------------------------------------------------------
#  NOTE: the `programme` table has NO `email` column. Owner email is
#  resolved on demand from `harvhub` via `programme.userid`. That is
#  done in `_resolve_programme_owner_email` and injected by
#  `_fetch_programme_row_for_notify`.
# ==============================================================================
PROGRAMME_SELECT_COLUMNS = [
    'id',
    'userid',
    'program_name',
    'broker',
    'server',
    'login',
    'broker_password',
    'broker_login_status',
    'broker_login_attempt_used',
    'broker_total_login_attempt',
    'disconnect_broker_request',
    'demo_account',
]


def _programme_select_sql():
    return ', '.join(PROGRAMME_SELECT_COLUMNS)


# ==============================================================================
#  Folder / path
# ==============================================================================
def build_mt5_folder_name(server, login, user_id, kind, account_id):
    """
    kind = 'SA'  -> sub-account / investor suffix:  _U{user_id}_SA{account_id}
    kind = 'P'   -> programme / trader suffix:      _U{user_id}_P{account_id}
    """
    s   = _sanitize_folder_component(server)
    l   = _sanitize_folder_component(login)
    u   = _sanitize_folder_component(user_id)
    aid = _sanitize_folder_component(account_id)
    return f"{s}_{l}_U{u}_{kind}{aid}"


def build_mt5_terminal_path_sa(server, login, user_id, sub_account_id):
    folder_name = build_mt5_folder_name(
        server, login, user_id, 'SA', sub_account_id
    )
    folder_abs   = os.path.join(MT5_DESTINATION_PATH, folder_name)
    terminal_exe = os.path.join(folder_abs, "terminal64.exe")
    return folder_name, folder_abs, terminal_exe


def build_mt5_terminal_path_prog(server, login, user_id, programme_id):
    folder_name = build_mt5_folder_name(
        server, login, user_id, 'P', programme_id
    )
    folder_abs   = os.path.join(MT5_DESTINATION_PATH, folder_name)
    terminal_exe = os.path.join(folder_abs, "terminal64.exe")
    return folder_name, folder_abs, terminal_exe


def find_all_folders_for_sub_account(user_id, sub_account_id):
    """Investor folders: *_{U<user_id>_SA<sub_account_id>}"""
    matches = []
    if not os.path.isdir(MT5_DESTINATION_PATH):
        return matches
    suffix = f"_U{user_id}_SA{sub_account_id}"
    try:
        for name in os.listdir(MT5_DESTINATION_PATH):
            full = os.path.join(MT5_DESTINATION_PATH, name)
            if not os.path.isdir(full):
                continue
            if name.endswith(suffix):
                matches.append(full)
    except Exception as e:
        print(f"   [SA][GLOB] listdir failed: {e}")
    return matches


def find_all_folders_for_programme(user_id, programme_id):
    """Programme folders: *_{U<user_id>_P<programme_id>}"""
    matches = []
    if not os.path.isdir(MT5_DESTINATION_PATH):
        return matches
    suffix = f"_U{user_id}_P{programme_id}"
    try:
        for name in os.listdir(MT5_DESTINATION_PATH):
            full = os.path.join(MT5_DESTINATION_PATH, name)
            if not os.path.isdir(full):
                continue
            if name.endswith(suffix):
                matches.append(full)
    except Exception as e:
        print(f"   [PRG][GLOB] listdir failed: {e}")
    return matches


def ensure_mt5_folder(server, login, user_id, kind, account_id):
    """
    Generic folder creation. `kind` is 'SA' or 'P'.
    """
    if kind == 'SA':
        folder_name, folder_abs, terminal_exe = build_mt5_terminal_path_sa(
            server, login, user_id, account_id
        )
    else:
        folder_name, folder_abs, terminal_exe = build_mt5_terminal_path_prog(
            server, login, user_id, account_id
        )

    if not os.path.isdir(DEFAULT_MT5_PATH):
        return False, folder_abs, terminal_exe, (
            f"Source MT5 template not found: {DEFAULT_MT5_PATH}"
        )

    if os.path.isdir(folder_abs):
        if os.path.exists(terminal_exe):
            return True, folder_abs, terminal_exe, "Folder already exists"
        try:
            shutil.rmtree(folder_abs, ignore_errors=True)
        except Exception:
            pass

    os.makedirs(MT5_DESTINATION_PATH, exist_ok=True)

    try:
        print(f"   [{kind}][COPY-FOLDER] MT5 template -> {folder_name}")
        shutil.copytree(
            DEFAULT_MT5_PATH,
            folder_abs,
            ignore_dangling_symlinks=True,
            ignore=shutil.ignore_patterns('*.lock', '*.log'),
        )
    except Exception as e:
        if os.path.isdir(folder_abs):
            shutil.rmtree(folder_abs, ignore_errors=True)
        return False, folder_abs, terminal_exe, f"Copy failed: {e}"

    if not os.path.exists(terminal_exe):
        return False, folder_abs, terminal_exe, (
            f"terminal64.exe missing after copy: {terminal_exe}"
        )

    return True, folder_abs, terminal_exe, "Folder created"


def delete_mt5_folder(folder_abs, tag='SA'):
    if not folder_abs or not os.path.isdir(folder_abs):
        return False
    try:
        shutil.rmtree(folder_abs, ignore_errors=True)
        print(f"   [{tag}][DELETE-FOLDER] {folder_abs}")
        return True
    except Exception as e:
        print(f"   [{tag}][DELETE-FOLDER] failed: {e}")
        return False


# ==============================================================================
#  Terminal launcher
# ==============================================================================
_LAUNCHED_PATHS = set()
_LAUNCH_LOCK    = threading.Lock()


def launch_terminal(terminal_exe, folder_abs):
    with _LAUNCH_LOCK:
        already = terminal_exe in _LAUNCHED_PATHS
    if already:
        print(f"      [LAUNCH] already running: {terminal_exe}")
        return True

    try:
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        subprocess.Popen(
            [terminal_exe],
            cwd=folder_abs,
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    except Exception as e:
        print(f"      [LAUNCH] failed: {e}")
        return False

    with _LAUNCH_LOCK:
        _LAUNCHED_PATHS.add(terminal_exe)
    print(f"      [LAUNCH] started: {terminal_exe}")
    return True


def bring_terminal_to_front(terminal_exe):
    try:
        subprocess.Popen([terminal_exe])
        print(f"      [FOCUS] re-opened: {terminal_exe}")
        return True
    except Exception as e:
        print(f"      [FOCUS] failed: {e}")
        return False


# ==============================================================================
#  Terminal discovery + kill helpers
# ==============================================================================
def _run_shell(cmd, timeout=15):
    try:
        return subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=timeout,
        ).stdout.decode(errors='ignore')
    except Exception as e:
        print(f"      [CMD] failed: {cmd!r} -> {e}")
        return ''


def _list_pids_for_image(image_name):
    out = _run_shell(
        f'tasklist /FI "IMAGENAME eq {image_name}" /FO CSV /NH',
        timeout=10,
    )
    pids = []
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() == image_name.lower():
            try:
                pids.append(int(parts[1]))
            except Exception:
                pass
    return pids


def list_running_mt5_processes():
    found = []
    for image in MT5_PROCESS_NAMES:
        for pid in _list_pids_for_image(image):
            found.append((image, pid))
    return found


def _is_pid_alive(pid):
    out = _run_shell(f'tasklist /FI "PID eq {pid}" /FO CSV /NH', timeout=5)
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2:
            try:
                if int(parts[1]) == pid:
                    return True
            except Exception:
                pass
    return False


def kill_pids(pids):
    killed = []
    for pid in pids:
        if not _is_pid_alive(pid):
            killed.append(pid)
            continue
        _run_shell(f'taskkill /F /PID {pid}', timeout=10)
        killed.append(pid)
        print(f"      [KILL-TERMINAL] taskkill /F /PID {pid}")

    deadline = time.time() + TERMINAL_KILL_WAIT_TOTAL
    pending = list(killed)

    while pending and time.time() < deadline:
        still_alive = [pid for pid in pending if _is_pid_alive(pid)]
        if not still_alive:
            break
        time.sleep(TERMINAL_KILL_POLL)
        pending = still_alive

    if pending:
        print(f"      [KILL-TERMINAL] still alive after wait: {pending}")
    else:
        print(f"      [KILL-TERMINAL] all confirmed dead: {killed}")

    return killed


def kill_terminal_for_folder(folder_abs):
    procs = list_running_mt5_processes()

    if not procs:
        print(f"      [KILL-TERMINAL] no MT5 process running")
        with _LAUNCH_LOCK:
            _LAUNCHED_PATHS.discard(os.path.join(folder_abs, "terminal64.exe"))
        return 0

    print(f"      [KILL-TERMINAL] found running MT5 processes: {procs}")
    pids = [pid for _, pid in procs]
    kill_pids(pids)

    with _LAUNCH_LOCK:
        _LAUNCHED_PATHS.discard(os.path.join(folder_abs, "terminal64.exe"))

    return len(pids)


def _rmtree_via_cmd(folder_abs):
    try:
        result = subprocess.run(
            f'cmd /c rmdir /s /q "{folder_abs}"',
            shell=True,
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=60,
        )
        if not os.path.isdir(folder_abs):
            return True
        print(
            f"   [FORCE-DELETE] cmd rmdir exit={result.returncode} "
            f"stderr={result.stderr.decode(errors='ignore').strip()!r}"
        )
    except Exception as e:
        print(f"   [FORCE-DELETE] cmd rmdir failed: {e}")
    return False


def force_delete_folder(folder_abs, terminal_exe=None):
    if not folder_abs or not os.path.isdir(folder_abs):
        return True

    if terminal_exe is None:
        terminal_exe = os.path.join(folder_abs, "terminal64.exe")

    print(f"   [FORCE-DELETE] step 1: kill any MT5 process")
    kill_terminal_for_folder(folder_abs)

    last_err = None
    for attempt in range(1, DELETE_RETRY_COUNT + 1):
        try:
            shutil.rmtree(folder_abs, ignore_errors=False)
            print(f"   [FORCE-DELETE] removed on attempt {attempt}: {folder_abs}")
            return True
        except Exception as e:
            last_err = e
            print(f"   [FORCE-DELETE] attempt {attempt} failed: {e}")
            if not os.path.isdir(folder_abs):
                print(f"   [FORCE-DELETE] folder already gone")
                return True
            time.sleep(DELETE_RETRY_WAIT)

    print(f"   [FORCE-DELETE] step 3: cmd /c rmdir /s /q")
    if _rmtree_via_cmd(folder_abs):
        print(f"   [FORCE-DELETE] removed via cmd rmdir: {folder_abs}")
        return True

    try:
        trash = folder_abs + f"_trash_{int(time.time())}"
        os.rename(folder_abs, trash)
        time.sleep(0.5)
        _rmtree_via_cmd(trash)
        if not os.path.isdir(trash):
            print(f"   [FORCE-DELETE] renamed+removed: {trash}")
            return True
        else:
            print(f"   [FORCE-DELETE] renamed but still present: {trash}")
    except Exception as e:
        print(f"   [FORCE-DELETE] rename attempt failed: {e}")

    print(f"   [FORCE-DELETE] giving up, last error: {last_err}")
    return not os.path.isdir(folder_abs)


# ==============================================================================
#  Read-only IPC probe
# ==============================================================================
def probe_terminal_account(terminal_exe, folder_abs):
    if mt5 is None:
        return 'unreachable', {'error': 'MetaTrader5 module not available'}

    if not os.path.exists(terminal_exe):
        return 'unreachable', {'error': f'Terminal not found: {terminal_exe}'}

    try:
        mt5.shutdown()
    except Exception:
        pass

    try:
        ok = mt5.initialize(
            path=terminal_exe,
            timeout=10000,
            portable=True,
        )
    except Exception as e:
        return 'unreachable', {'error': f'initialize() raised: {e}'}

    if not ok:
        return 'unreachable', {'error': f'initialize() failed: {mt5.last_error()}'}

    info = None
    try:
        acc = mt5.account_info()
        if acc is not None and getattr(acc, 'login', None):
            info = {
                'login':    int(acc.login),
                'server':   getattr(acc, 'server', None),
                'name':     getattr(acc, 'name', None),
                'balance':  getattr(acc, 'balance', None),
                'currency': getattr(acc, 'currency', None),
                'leverage': getattr(acc, 'leverage', None),
            }
    except Exception:
        info = None

    try:
        mt5.shutdown()
    except Exception:
        pass

    if info is None:
        return 'not_logged_in', None
    return 'logged_in', info


# ==============================================================================
#  harvhub mutation helpers (sub-account / investor)
# ==============================================================================
def _get_broker_login_status(user_id):
    sql = "SELECT broker_login_status FROM harvhub WHERE id = %s LIMIT 1"
    res = db_query(sql, [user_id], timeout=10.0, quiet=True)
    if res.get('status') == 'success' and res.get('results'):
        row = res['results'][0]
        for v in row.values():
            if v is None:
                return None
            return str(v).strip()
    return None


def _fetch_row_for_notify(user_id, sub_account_id):
    sql = (
        "SELECT id, sub_account_id, main_account_id, email, "
        "broker, server, login, broker_password, "
        "broker_login_status, broker_login_attempt_used, "
        "broker_total_login_attempt, demo_account, "
        "disconnect_broker_request "
        "FROM harvhub WHERE id = %s LIMIT 1"
    )
    res = db_query(sql, [user_id], timeout=15.0, quiet=True)
    if res.get('status') == 'success' and res.get('results'):
        return _normalize_row(res['results'][0])

    if sub_account_id is not None and sub_account_id != user_id:
        sql2 = (
            "SELECT id, sub_account_id, main_account_id, email, "
            "broker, server, login, broker_password, "
            "broker_login_status, broker_login_attempt_used, "
            "broker_total_login_attempt, demo_account, "
            "disconnect_broker_request "
            "FROM harvhub WHERE sub_account_id = %s LIMIT 1"
        )
        res2 = db_query(sql2, [sub_account_id], timeout=15.0, quiet=True)
        if res2.get('status') == 'success' and res2.get('results'):
            return _normalize_row(res2['results'][0])

    return None


def _set_broker_login_status(user_id, status):
    sql = "UPDATE harvhub SET broker_login_status = %s WHERE id = %s"
    res = db_query(sql, [status, user_id], timeout=10.0, quiet=True)
    return res.get('status') == 'success'


def _increment_broker_login_attempt(user_id):
    sql = (
        "UPDATE harvhub "
        "SET broker_login_attempt_used = COALESCE(broker_login_attempt_used, 0) + 1 "
        "WHERE id = %s"
    )
    res = db_query(sql, [user_id], timeout=10.0, quiet=True)
    if res.get('status') != 'success':
        return None

    q = "SELECT broker_login_attempt_used FROM harvhub WHERE id = %s LIMIT 1"
    res2 = db_query(q, [user_id], timeout=10.0, quiet=True)
    if res2.get('status') == 'success' and res2.get('results'):
        row = res2['results'][0]
        for v in row.values():
            return _coerce_int(v)
    return None


def _reset_broker_login_attempt(user_id):
    sql = "UPDATE harvhub SET broker_login_attempt_used = NULL WHERE id = %s"
    res = db_query(sql, [user_id], timeout=10.0, quiet=True)
    return res.get('status') == 'success'


def _notify_broker_failure(user_id, sub_account_id, new_status):
    if new_status not in TERMINAL_NEGATIVE_STATUSES:
        return None

    clear_sql = (
        "UPDATE harvhub "
        "SET broker = NULL, server = NULL, login = NULL, broker_password = NULL "
        "WHERE id = %s"
    )
    db_query(clear_sql, [user_id], timeout=10.0, quiet=True)

    new_used = _increment_broker_login_attempt(user_id)
    _set_broker_login_status(user_id, new_status)

    row = _fetch_row_for_notify(user_id, sub_account_id)
    print(f"      [SA][NOTIFY-DEBUG] fetched row before dispatch = {row!r}")
    if row is None:
        print(f"      [SA][NOTIFY] could not re-fetch row for user={user_id}")
        return new_used

    try:
        notif_id = notifier.record_broker_login_status_notification(_PDO, row)
        if notif_id:
            print(
                f"      [SA][NOTIFY] user={user_id} status={new_status} "
                f"-> notification_id={notif_id} "
                f"(attempts used = {new_used})"
            )
        else:
            print(
                f"      [SA][NOTIFY] user={user_id} status={new_status} "
                f"-> no notification created (dedup or ineligible state)"
            )
    except Exception as e:
        print(f"      [SA][NOTIFY] raised: {e}")
        traceback.print_exc()

    return new_used


def _notify_broker_success(user_id, sub_account_id):
    row = _fetch_row_for_notify(user_id, sub_account_id)
    if row is None:
        print(f"      [SA][NOTIFY-SUCCESS] could not re-fetch row for user={user_id}")
        return None

    try:
        notif_id = notifier.record_broker_login_success_notification(_PDO, row)
        if notif_id:
            print(
                f"      [SA][NOTIFY-SUCCESS] user={user_id} "
                f"-> notification_id={notif_id}"
            )
        else:
            print(
                f"      [SA][NOTIFY-SUCCESS] user={user_id} "
                f"-> no notification created"
            )
        return notif_id
    except Exception as e:
        print(f"      [SA][NOTIFY-SUCCESS] raised: {e}")
        traceback.print_exc()
        return None


def _notify_disconnect_completed(user_id, sub_account_id):
    row = _fetch_row_for_notify(user_id, sub_account_id)
    if row is None:
        print(f"      [SA][NOTIFY-DISCONNECT] could not re-fetch row for user={user_id}")
        return None

    try:
        notif_id = notifier.record_disconnect_broker_completed_notification(_PDO, row)
        if notif_id:
            print(
                f"      [SA][NOTIFY-DISCONNECT] user={user_id} "
                f"-> notification_id={notif_id}"
            )
        else:
            print(
                f"      [SA][NOTIFY-DISCONNECT] user={user_id} "
                f"-> no notification created"
            )
        return notif_id
    except Exception as e:
        print(f"      [SA][NOTIFY-DISCONNECT] raised: {e}")
        traceback.print_exc()
        return None


def _clear_disconnect_request(user_id):
    sql = "UPDATE harvhub SET disconnect_broker_request = 0 WHERE id = %s"
    res = db_query(sql, [user_id], timeout=10.0, quiet=True)
    return res.get('status') == 'success'


# ==============================================================================
#  programme mutation helpers (trader)
# ==============================================================================
def _get_programme_broker_login_status(programme_id):
    sql = "SELECT broker_login_status FROM programme WHERE id = %s LIMIT 1"
    res = db_query(sql, [programme_id], timeout=10.0, quiet=True)
    if res.get('status') == 'success' and res.get('results'):
        row = res['results'][0]
        for v in row.values():
            if v is None:
                return None
            return str(v).strip()
    return None


def _resolve_programme_owner_email(user_id):
    """
    The `programme` table has NO `email` column. Owner email is a
    property of the user, so we resolve it from `harvhub` via
    `programme.userid == harvhub.id`.

    Returns a lowercase, stripped email string, or '' if not found.
    """
    if user_id is None:
        return ''
    uid = _coerce_int(user_id)
    if uid is None or uid <= 0:
        return ''

    q = db_query(
        "SELECT email FROM harvhub WHERE id = %s LIMIT 1",
        [uid], timeout=10.0, quiet=True,
    )
    if q.get('status') == 'success' and q.get('results'):
        row = q['results'][0]
        for v in row.values():
            if v is None:
                return ''
            return str(v).strip().lower()
    return ''


def _fetch_programme_row_for_notify(programme_id, user_id):
    """
    Fetches a programme row and injects the owner's email resolved
    from `harvhub` via `programme.userid`, so downstream notification
    helpers can uniformly access `row['email']`.
    """
    select_cols = _programme_select_sql()

    row = None

    if programme_id is not None:
        sql = f"SELECT {select_cols} FROM programme WHERE id = %s LIMIT 1"
        res = db_query(sql, [programme_id], timeout=15.0, quiet=True)
        if res.get('status') == 'success' and res.get('results'):
            row = _normalize_row(res['results'][0])

    if row is None and user_id is not None:
        sql2 = (
            f"SELECT {select_cols} FROM programme "
            f"WHERE userid = %s ORDER BY id ASC LIMIT 1"
        )
        res2 = db_query(sql2, [user_id], timeout=15.0, quiet=True)
        if res2.get('status') == 'success' and res2.get('results'):
            row = _normalize_row(res2['results'][0])

    if row is not None:
        # `programme` has no email column — resolve it from harvhub.
        owner_uid = _coerce_int(row.get('userid')) or user_id
        row['email'] = _resolve_programme_owner_email(owner_uid)

    return row


def _set_programme_broker_login_status(programme_id, status):
    sql = "UPDATE programme SET broker_login_status = %s WHERE id = %s"
    res = db_query(sql, [status, programme_id], timeout=10.0, quiet=True)
    return res.get('status') == 'success'


def _increment_programme_broker_login_attempt(programme_id):
    sql = (
        "UPDATE programme "
        "SET broker_login_attempt_used = COALESCE(broker_login_attempt_used, 0) + 1 "
        "WHERE id = %s"
    )
    res = db_query(sql, [programme_id], timeout=10.0, quiet=True)
    if res.get('status') != 'success':
        return None

    q = "SELECT broker_login_attempt_used FROM programme WHERE id = %s LIMIT 1"
    res2 = db_query(q, [programme_id], timeout=10.0, quiet=True)
    if res2.get('status') == 'success' and res2.get('results'):
        row = res2['results'][0]
        for v in row.values():
            return _coerce_int(v)
    return None


def _reset_programme_broker_login_attempt(programme_id):
    sql = "UPDATE programme SET broker_login_attempt_used = NULL WHERE id = %s"
    res = db_query(sql, [programme_id], timeout=10.0, quiet=True)
    return res.get('status') == 'success'


def _notify_programme_broker_failure(programme_id, user_id, new_status):
    """
    Programme equivalent of _notify_broker_failure. Demo is NEVER
    produced here — only 'invalid_credentials' or 'fullname_mismatch'.
    """
    if new_status not in PROGRAMME_NEGATIVE_STATUSES:
        return None

    clear_sql = (
        "UPDATE programme "
        "SET broker = NULL, server = NULL, login = NULL, broker_password = NULL "
        "WHERE id = %s"
    )
    db_query(clear_sql, [programme_id], timeout=10.0, quiet=True)

    new_used = _increment_programme_broker_login_attempt(programme_id)
    _set_programme_broker_login_status(programme_id, new_status)

    row = _fetch_programme_row_for_notify(programme_id, user_id)
    print(f"      [PRG][NOTIFY-DEBUG] fetched row before dispatch = {row!r}")
    if row is None:
        print(f"      [PRG][NOTIFY] could not re-fetch row for programme={programme_id}")
        return new_used

    try:
        notif_id = notifier.record_programme_broker_login_status_notification(_PDO, row)
        if notif_id:
            print(
                f"      [PRG][NOTIFY] programme={programme_id} status={new_status} "
                f"-> notification_id={notif_id} "
                f"(attempts used = {new_used})"
            )
        else:
            print(
                f"      [PRG][NOTIFY] programme={programme_id} status={new_status} "
                f"-> no notification created (dedup or ineligible state)"
            )
    except Exception as e:
        print(f"      [PRG][NOTIFY] raised: {e}")
        traceback.print_exc()

    return new_used


def _notify_programme_broker_success(programme_id, user_id):
    row = _fetch_programme_row_for_notify(programme_id, user_id)
    if row is None:
        print(f"      [PRG][NOTIFY-SUCCESS] could not re-fetch row for programme={programme_id}")
        return None

    try:
        notif_id = notifier.record_programme_broker_login_success_notification(_PDO, row)
        if notif_id:
            print(
                f"      [PRG][NOTIFY-SUCCESS] programme={programme_id} "
                f"-> notification_id={notif_id}"
            )
        else:
            print(
                f"      [PRG][NOTIFY-SUCCESS] programme={programme_id} "
                f"-> no notification created"
            )
        return notif_id
    except Exception as e:
        print(f"      [PRG][NOTIFY-SUCCESS] raised: {e}")
        traceback.print_exc()
        return None


def _notify_programme_disconnect_completed(programme_id, user_id):
    row = _fetch_programme_row_for_notify(programme_id, user_id)
    if row is None:
        print(f"      [PRG][NOTIFY-DISCONNECT] could not re-fetch row for programme={programme_id}")
        return None

    try:
        notif_id = notifier.record_programme_disconnect_broker_completed_notification(_PDO, row)
        if notif_id:
            print(
                f"      [PRG][NOTIFY-DISCONNECT] programme={programme_id} "
                f"-> notification_id={notif_id}"
            )
        else:
            print(
                f"      [PRG][NOTIFY-DISCONNECT] programme={programme_id} "
                f"-> no notification created"
            )
        return notif_id
    except Exception as e:
        print(f"      [PRG][NOTIFY-DISCONNECT] raised: {e}")
        traceback.print_exc()
        return None


def _clear_programme_disconnect_request(programme_id):
    sql = "UPDATE programme SET disconnect_broker_request = 0 WHERE id = %s"
    res = db_query(sql, [programme_id], timeout=10.0, quiet=True)
    return res.get('status') == 'success'


# ==============================================================================
#  DISCONNECT-REQUEST PASS — SUB-ACCOUNT / INVESTOR
# ==============================================================================
def _process_disconnect_requests():
    completed = 0

    sql = (
        "SELECT id, sub_account_id, main_account_id, email, "
        "server, login, disconnect_broker_request "
        "FROM harvhub "
        "WHERE disconnect_broker_request = 1"
    )
    res = db_query(sql, None, timeout=15.0, quiet=True)
    if not _is_ok(res):
        return 0

    rows = res.get('results') or []
    if not rows:
        return 0

    print(f"   [SA][DISCONNECT] pending rows: {len(rows)}")

    for raw in rows:
        row = _normalize_row(raw)

        user_id        = _coerce_int(row.get('id'))
        sub_account_id = _coerce_int(row.get('sub_account_id')) or user_id

        if not user_id or not sub_account_id:
            continue

        print(f"\n   [SA][DISCONNECT] user={user_id} sub={sub_account_id}")

        folders = find_all_folders_for_sub_account(user_id, sub_account_id)

        if not folders:
            print(
                f"   [SA][DISCONNECT] no folders matching "
                f"'*_U{user_id}_SA{sub_account_id}' found; nothing to delete"
            )
        else:
            print(
                f"   [SA][DISCONNECT] matched {len(folders)} folder(s) "
                f"for user={user_id} sub={sub_account_id}"
            )

            all_ok = True
            for folder_abs in folders:
                print(f"   [SA][DISCONNECT] processing: {folder_abs}")
                ok = force_delete_folder(folder_abs)
                if not ok:
                    all_ok = False
                    print(f"   [SA][DISCONNECT] failed to delete: {folder_abs}")

            if not all_ok:
                print(
                    "   [SA][DISCONNECT] one or more folders could not be "
                    "deleted; flag left as-is for next pass"
                )
                continue

        _clear_disconnect_request(user_id)
        _notify_disconnect_completed(user_id, sub_account_id)
        completed += 1

    return completed


# ==============================================================================
#  DISCONNECT-REQUEST PASS — PROGRAMME / TRADER
# ==============================================================================
def _process_programme_disconnect_requests():
    completed = 0

    sql = (
        "SELECT id, userid, program_name, "
        "server, login, disconnect_broker_request "
        "FROM programme "
        "WHERE disconnect_broker_request = 1"
    )
    res = db_query(sql, None, timeout=15.0, quiet=True)
    if not _is_ok(res):
        return 0

    rows = res.get('results') or []
    if not rows:
        return 0

    print(f"   [PRG][DISCONNECT] pending rows: {len(rows)}")

    for raw in rows:
        row = _normalize_row(raw)

        programme_id = _coerce_int(row.get('id'))
        user_id      = _coerce_int(row.get('userid'))

        if not programme_id or not user_id:
            continue

        print(f"\n   [PRG][DISCONNECT] programme={programme_id} user={user_id}")

        folders = find_all_folders_for_programme(user_id, programme_id)

        if not folders:
            print(
                f"   [PRG][DISCONNECT] no folders matching "
                f"'*_U{user_id}_P{programme_id}' found; nothing to delete"
            )
        else:
            print(
                f"   [PRG][DISCONNECT] matched {len(folders)} folder(s) "
                f"for programme={programme_id} user={user_id}"
            )

            all_ok = True
            for folder_abs in folders:
                print(f"   [PRG][DISCONNECT] processing: {folder_abs}")
                ok = force_delete_folder(folder_abs)
                if not ok:
                    all_ok = False
                    print(f"   [PRG][DISCONNECT] failed to delete: {folder_abs}")

            if not all_ok:
                print(
                    "   [PRG][DISCONNECT] one or more folders could not be "
                    "deleted; flag left as-is for next pass"
                )
                continue

        _clear_programme_disconnect_request(programme_id)
        _notify_programme_disconnect_completed(programme_id, user_id)
        completed += 1

    return completed


def _is_ok(res):
    return bool(res) and res.get('status') == 'success'


# ==============================================================================
#  SINGLE manual login window
# ==============================================================================
class SingleManualLoginWindow:
    def __init__(self):
        self._lock        = threading.Lock()
        self._items       = {}
        self._root        = None
        self._rows_holder = None
        self._started     = False
        self._stop_poll   = threading.Event()
        self._thread      = None

    def add_item(self, kind, owner_id, account_id, broker, server, login,
                 password, terminal_exe):
        """
        kind:    'SA'  (sub-account)   or 'PRG' (programme)
        owner_id: user_id
        account_id: sub_account_id (SA) or programme_id (PRG)
        """
        item_key = f"{kind}:{owner_id}:{account_id}"

        new_item = {
            'kind':         kind,
            'owner_id':     owner_id,
            'account_id':   account_id,
            'broker':       broker or 'N/A',
            'server':       server or 'N/A',
            'login':        login,
            'password':     password or '',
            'terminal_exe': terminal_exe,
        }

        with self._lock:
            existing = self._items.get(item_key)
            if existing is not None:
                same = all(
                    str(existing.get(k)) == str(new_item.get(k))
                    for k in ('account_id', 'broker', 'server',
                              'login', 'password', 'terminal_exe')
                )
                if same:
                    return
            self._items[item_key] = new_item

        self._ensure_started()
        self._refresh_rows()

    def remove_item(self, kind, owner_id, account_id):
        item_key = f"{kind}:{owner_id}:{account_id}"
        with self._lock:
            existed = self._items.pop(item_key, None) is not None
        if existed:
            self._refresh_rows()

    def stop(self):
        self._stop_poll.set()

    def _ensure_started(self):
        with self._lock:
            if self._started:
                return
            self._started = True
        self._thread = threading.Thread(
            target=self._run, name="single_manual_login", daemon=True)
        self._thread.start()

    def _run(self):
        try:
            self._build_and_loop()
        except Exception as e:
            print(f"      [WINDOW] Tk thread died: {e}")

    def _build_and_loop(self):
        self._root = tk.Tk()
        self._root.title("Manual MT5 Login — Accounts Needing Session")
        self._root.geometry("860x620")
        self._root.minsize(680, 400)

        try:
            self._root.attributes('-topmost', True)
            self._root.after(400, lambda: self._root.attributes('-topmost', False))
        except Exception:
            pass

        header = ttk.Frame(self._root, padding=(12, 10, 12, 4))
        header.pack(fill="x")

        ttk.Label(
            header,
            text="Login Manually to These Accounts",
            font=("Segoe UI", 13, "bold")
        ).pack(anchor="w")

        ttk.Label(
            header,
            text="Each MT5 terminal has been launched in the background. "
                 "Log in manually. Click Valid or Invalid per account to "
                 "record the result. Use Open Terminal to bring its window "
                 "forward. Rows are tagged [SA] (investor sub-account) or "
                 "[PRG] (programme).",
            foreground="#555",
            wraplength=820,
            justify="left"
        ).pack(anchor="w", pady=(4, 0))

        container = ttk.Frame(self._root)
        container.pack(fill="both", expand=True, padx=12, pady=(4, 8))

        canvas = tk.Canvas(container, borderwidth=0, highlightthickness=0)
        vbar   = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        vbar.pack(side="right", fill="y")

        self._rows_holder = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=self._rows_holder, anchor="nw")

        def _on_configure(_evt=None):
            try:
                canvas.configure(scrollregion=canvas.bbox("all"))
            except Exception:
                pass

        self._rows_holder.bind("<Configure>", _on_configure)

        def _on_mousewheel(event):
            try:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except Exception:
                pass
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        footer = ttk.Frame(self._root, padding=(12, 0, 12, 10))
        footer.pack(fill="x")
        ttk.Button(footer, text="Close (reopens if unresolved rows remain)",
                   command=self._on_close).pack(side="right")

        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._refresh_rows()
        self._schedule_db_poll()

        try:
            self._root.mainloop()
        except Exception:
            pass

    def _on_close(self):
        print("      [WINDOW] closed by user; will reopen if rows remain")
        try:
            self._root.quit()
            self._root.destroy()
        except Exception:
            pass
        with self._lock:
            self._started = False
            self._root = None
            self._rows_holder = None

    def _make_copy_button(self, parent, value, label="Copy"):
        btn = ttk.Button(parent, text=label, width=8)

        def _do_copy():
            try:
                self._root.clipboard_clear()
                self._root.clipboard_append(str(value))
                self._root.update_idletasks()
                print(f"      [COPY] {value}")
            except Exception:
                pass
            try:
                btn.configure(text="Copied!")
                btn.after(COPY_FEEDBACK_MS,
                          lambda: btn.configure(text=label))
            except Exception:
                pass

        btn.configure(command=_do_copy)
        return btn

    def _refresh_rows(self):
        holder = self._rows_holder
        if holder is None:
            return
        try:
            for child in holder.winfo_children():
                child.destroy()

            with self._lock:
                snapshot = list(self._items.values())

            if not snapshot:
                ttk.Label(
                    holder,
                    text="No accounts pending manual login.",
                    foreground="#666",
                    padding=12
                ).pack(anchor="w")
                return

            for idx, item in enumerate(snapshot, start=1):
                self._render_row(idx, item)
        except Exception as e:
            print(f"      [WINDOW] refresh error: {e}")

    def _render_row(self, idx, item):
        kind       = item['kind']
        owner_id   = item['owner_id']
        account_id = item['account_id']

        tag = 'SA' if kind == 'SA' else 'PRG'
        label_acct = 'sub account' if kind == 'SA' else 'programme'

        card = ttk.LabelFrame(
            self._rows_holder,
            text=f"{idx}. [{tag}] user {owner_id} | {label_acct} {account_id}",
            padding=10
        )
        card.pack(fill="x", expand=True, pady=6, padx=2)

        def _field(parent, label, value):
            row = ttk.Frame(parent)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=f"{label}:", width=12, anchor="w").pack(side="left")
            ttk.Label(row, text=str(value), anchor="w").pack(side="left")
            self._make_copy_button(row, value).pack(side="left", padx=(8, 0))

        _field(card, "Broker", item['broker'])
        _field(card, "Server", item['server'])
        _field(card, "Login",  item['login'])

        pw_row = ttk.Frame(card)
        pw_row.pack(fill="x", pady=2)
        ttk.Label(pw_row, text="Password:", width=12, anchor="w").pack(side="left")
        pw_var = tk.StringVar(value="••••••••")
        ttk.Label(pw_row, textvariable=pw_var, anchor="w").pack(side="left")

        def _toggle_pw():
            if pw_var.get().startswith("•"):
                pw_var.set(item['password'] or "(empty)")
            else:
                pw_var.set("••••••••")

        ttk.Button(pw_row, text="Show", width=8,
                   command=_toggle_pw).pack(side="left", padx=(8, 0))
        self._make_copy_button(pw_row, item['password']).pack(side="left", padx=(6, 0))

        row_actions = ttk.Frame(card)
        row_actions.pack(fill="x", pady=(8, 0))

        def _on_open_terminal():
            print(f"      [{tag}][OPEN] {item['terminal_exe']}")
            bring_terminal_to_front(item['terminal_exe'])

        ttk.Button(row_actions, text="Open Terminal",
                   command=_on_open_terminal).pack(side="left", padx=(0, 6))

        if kind == 'SA':
            def _on_valid():
                _set_broker_login_status(owner_id, VALID_STATUS)
                _reset_broker_login_attempt(owner_id)
                _notify_broker_success(owner_id, account_id)
                print(f"      [SA][MANUAL] user={owner_id} -> valid_credentials (attempts reset)")
                self.remove_item(kind, owner_id, account_id)

            def _on_invalid():
                _notify_broker_failure(
                    user_id=owner_id,
                    sub_account_id=account_id,
                    new_status='invalid_credentials',
                )
                print(f"      [SA][MANUAL] user={owner_id} -> invalid_credentials (broker cleared)")
                self.remove_item(kind, owner_id, account_id)
        else:
            def _on_valid():
                _set_programme_broker_login_status(account_id, VALID_STATUS)
                _reset_programme_broker_login_attempt(account_id)
                _notify_programme_broker_success(account_id, owner_id)
                print(f"      [PRG][MANUAL] programme={account_id} -> valid_credentials (attempts reset)")
                self.remove_item(kind, owner_id, account_id)

            def _on_invalid():
                _notify_programme_broker_failure(
                    programme_id=account_id,
                    user_id=owner_id,
                    new_status='invalid_credentials',
                )
                print(f"      [PRG][MANUAL] programme={account_id} -> invalid_credentials (broker cleared)")
                self.remove_item(kind, owner_id, account_id)

        ttk.Button(row_actions, text="Invalid Credentials",
                   command=_on_invalid).pack(side="left", expand=True,
                                             fill="x", padx=(0, 4))
        ttk.Button(row_actions, text="Valid Credentials",
                   command=_on_valid).pack(side="left", expand=True,
                                           fill="x", padx=(4, 0))

    def _schedule_db_poll(self):
        if self._stop_poll.is_set():
            return
        try:
            with self._lock:
                snapshot = list(self._items.items())

            changed = False
            for item_key, item in snapshot:
                kind       = item['kind']
                owner_id   = item['owner_id']
                account_id = item['account_id']

                if kind == 'SA':
                    status = _get_broker_login_status(owner_id)
                    resolved = (
                        status in TERMINAL_NEGATIVE_STATUSES
                        or status == VALID_STATUS
                    )
                else:
                    status = _get_programme_broker_login_status(account_id)
                    resolved = (
                        status in PROGRAMME_NEGATIVE_STATUSES
                        or status == VALID_STATUS
                    )

                if resolved:
                    print(
                        f"      [{kind}][MANUAL] owner={owner_id} "
                        f"account={account_id} resolved externally -> {status}"
                    )
                    with self._lock:
                        self._items.pop(item_key, None)
                    changed = True

            if changed:
                self._refresh_rows()
        except Exception:
            pass

        try:
            if self._root is not None:
                self._root.after(int(MANUAL_POLL_INTERVAL * 1000),
                                 self._schedule_db_poll)
        except Exception:
            pass


_MANUAL_WINDOW = SingleManualLoginWindow()


# ==============================================================================
#  Broker row fetch — sub-account / investor
# ==============================================================================
def _fetch_broker_row(user_id, sub_account_id):
    select_cols = _broker_select_sql()

    if user_id is not None:
        sql = f"SELECT {select_cols} FROM harvhub WHERE id = %s LIMIT 1"
        res = db_query(sql, [user_id], timeout=15.0, quiet=True)
        if res.get('status') == 'success' and res.get('results'):
            return _normalize_row(res['results'][0])

    if sub_account_id is not None and sub_account_id != user_id:
        sql = f"SELECT {select_cols} FROM harvhub WHERE sub_account_id = %s LIMIT 1"
        res = db_query(sql, [sub_account_id], timeout=15.0, quiet=True)
        if res.get('status') == 'success' and res.get('results'):
            return _normalize_row(res['results'][0])

    if sub_account_id is not None:
        sql = (f"SELECT {select_cols} FROM harvhub "
               f"WHERE main_account_id = %s "
               f"ORDER BY is_main_account ASC, id ASC LIMIT 1")
        res = db_query(sql, [sub_account_id], timeout=15.0, quiet=True)
        if res.get('status') == 'success' and res.get('results'):
            return _normalize_row(res['results'][0])

    return None


# ==============================================================================
#  Broker row fetch — programme / trader
#  -------------------------------------------------------------
#  Uses PROGRAMME_SELECT_COLUMNS (which no longer contains `email`).
#  We still inject the owner's email from harvhub so downstream code
#  that expects `row['email']` continues to work.
# ==============================================================================
def _fetch_programme_row(programme_id, user_id):
    select_cols = _programme_select_sql()

    row = None

    if programme_id is not None:
        sql = f"SELECT {select_cols} FROM programme WHERE id = %s LIMIT 1"
        res = db_query(sql, [programme_id], timeout=15.0, quiet=True)
        if res.get('status') == 'success' and res.get('results'):
            row = _normalize_row(res['results'][0])

    if row is None and user_id is not None:
        sql = (f"SELECT {select_cols} FROM programme "
               f"WHERE userid = %s ORDER BY id ASC LIMIT 1")
        res = db_query(sql, [user_id], timeout=15.0, quiet=True)
        if res.get('status') == 'success' and res.get('results'):
            row = _normalize_row(res['results'][0])

    if row is not None:
        owner_uid = _coerce_int(row.get('userid')) or user_id
        row['email'] = _resolve_programme_owner_email(owner_uid)

    return row


# ==============================================================================
#  SUB-ACCOUNT TARGET PROCESSING
# ==============================================================================
def _process_target(row, role, user_id, sub_account_id):
    """
    Sub-account / investor probe.

    `broker_login_status = 'valid_credentials'` does NOT skip the probe.
    It only means we already told the user the terminal was live, so we
    suppress a repeat success email — but we still confirm every loop
    that the terminal is genuinely logged in with the right login and
    the right fullname.
    """
    result = {
        'source':         'SA',
        'role':           role,
        'user_id':        user_id,
        'sub_account_id': sub_account_id,
        'ok':             False,
    }

    login         = _pick_first_key(row, 'login')
    server        = _pick_first_key(row, 'server') or ''
    broker        = _pick_first_key(row, 'broker') or ''
    password      = _pick_first_key(row, 'broker_password') or ''
    login_int     = _coerce_int(login)
    manual_status = (_pick_first_key(row, 'broker_login_status') or '').strip().lower()
    expected_name = _expected_fullname_from_row(row)
    demo_int      = _coerce_int(_pick_first_key(row, 'demo_account')) or 0

    already_notified = (manual_status == VALID_STATUS)

    # Failure statuses still skip — terminal was deleted, user notified.
    if manual_status in TERMINAL_NEGATIVE_STATUSES:
        print(f"      [SA][SKIP] sub={sub_account_id} — {manual_status}")
        result['reason'] = manual_status
        return result

    if login_int is None or not server:
        print(f"      [SA][SKIP] sub={sub_account_id} — missing login/server")
        result['reason'] = 'missing login or server'
        return result

    ok_folder, folder_abs, terminal_exe, msg_folder = ensure_mt5_folder(
        server=server, login=login_int,
        user_id=user_id, kind='SA', account_id=sub_account_id,
    )
    print(f"      [SA][FOLDER] {msg_folder}")

    if not ok_folder:
        result['reason'] = f'folder: {msg_folder}'
        return result

    ok_launch = launch_terminal(terminal_exe, folder_abs)
    if not ok_launch:
        result['reason'] = 'launch failed'
        return result

    time.sleep(TERMINAL_BOOT_WAIT)
    probe_state, probe_info = probe_terminal_account(terminal_exe, folder_abs)

    if probe_state == 'logged_in':
        term_login  = probe_info.get('login')
        term_server = probe_info.get('server')
        term_name   = probe_info.get('name') or ''

        if str(term_login) == str(login_int):
            if _names_match(expected_name, term_name):
                # Investor: demo check still applies.
                if demo_int == 0:
                    print(f"      [SA][INVALID-DEMO] sub={sub_account_id} | "
                          f"demo_account=0 but terminal is a demo "
                          f"({term_name}) — treating as invalid_account")

                    new_used = _notify_broker_failure(
                        user_id=user_id,
                        sub_account_id=sub_account_id,
                        new_status='invalid_account',
                    )
                    print(f"      [SA][ATTEMPT] broker_login_attempt_used -> "
                          f"{new_used if new_used is not None else '?'}")

                    delete_mt5_folder(folder_abs, tag='SA')
                    _MANUAL_WINDOW.remove_item('SA', user_id, sub_account_id)

                    result['reason'] = 'invalid_account'
                    result['login'] = term_login
                    result['server'] = term_server or server
                    result['broker'] = broker
                    result['folder'] = folder_abs
                    result['terminal_exe'] = terminal_exe
                    return result

                if already_notified:
                    # Probe OK, row already valid — silent keep.
                    print(f"      [SA][OK-NO-EMAIL] sub={sub_account_id} | "
                          f"still logged in as {term_login} @ {term_server} "
                          f"| name='{term_name}' matches "
                          f"'{expected_name}'; email already sent earlier")

                    _MANUAL_WINDOW.remove_item('SA', user_id, sub_account_id)
                    result['ok'] = True
                    result['reason'] = 'already_notified'
                    result['login'] = term_login
                    result['server'] = term_server or server
                    result['broker'] = broker
                    result['folder'] = folder_abs
                    result['terminal_exe'] = terminal_exe
                    result.update(probe_info or {})
                    return result

                # First-time confirmation — stamp + notify once.
                print(f"      [SA][OK-NEW] sub={sub_account_id} | logged in as "
                      f"{term_login} @ {term_server} | name='{term_name}' "
                      f"matches '{expected_name}' | demo_account={demo_int} "
                      f"— firing success email")

                _reset_broker_login_attempt(user_id)
                _set_broker_login_status(user_id, VALID_STATUS)
                _notify_broker_success(user_id, sub_account_id)

                result['ok'] = True
                result['reason'] = 'newly_valid'
                result['login'] = term_login
                result['server'] = term_server or server
                result['broker'] = broker
                result['folder'] = folder_abs
                result['terminal_exe'] = terminal_exe
                result.update(probe_info or {})
                _MANUAL_WINDOW.remove_item('SA', user_id, sub_account_id)
                return result

            print(f"      [SA][INVALID-FULLNAME] sub={sub_account_id} | terminal "
                  f"name='{term_name}' != expected '{expected_name}'")

            new_used = _notify_broker_failure(
                user_id=user_id,
                sub_account_id=sub_account_id,
                new_status='fullname_mismatch',
            )
            print(f"      [SA][ATTEMPT] broker_login_attempt_used -> "
                  f"{new_used if new_used is not None else '?'}")

            delete_mt5_folder(folder_abs, tag='SA')
            _MANUAL_WINDOW.remove_item('SA', user_id, sub_account_id)

            result['reason'] = 'fullname_mismatch'
            result['login'] = term_login
            result['server'] = term_server or server
            result['broker'] = broker
            result['folder'] = folder_abs
            result['terminal_exe'] = terminal_exe
            result['fullname_mismatch'] = {
                'expected': expected_name,
                'actual':   term_name,
            }
            return result

        print(f"      [SA][MANUAL] sub={sub_account_id} | terminal logged in as "
              f"{term_login} @ {term_server}, expected {login_int} @ {server} "
              f"— needs manual fix")

    elif probe_state == 'not_logged_in':
        print(f"      [SA][MANUAL] sub={sub_account_id} | terminal has no session "
              f"— needs manual login")

    else:
        print(f"      [SA][MANUAL] sub={sub_account_id} | probe unavailable "
              f"({probe_info.get('error')}) — needs manual login")

    _MANUAL_WINDOW.add_item(
        kind='SA',
        owner_id=user_id,
        account_id=sub_account_id,
        broker=broker,
        server=server,
        login=login_int,
        password=password,
        terminal_exe=terminal_exe,
    )
    result['reason'] = 'awaiting_manual_login'
    return result


# ==============================================================================
#  PROGRAMME TARGET PROCESSING
# ==============================================================================
def _process_programme_target(row, user_id, programme_id):
    """
    Programme / trader probe.

    Same rules as sub-account EXCEPT:
      * folder suffix is _U<user_id>_P<programme_id>
      * demo accounts are allowed by default; demo is never a failure
      * valid_credentials does NOT skip the probe — it only suppresses
        a repeat success email.
    """
    result = {
        'source':       'PRG',
        'role':         'programme',
        'user_id':      user_id,
        'programme_id': programme_id,
        'ok':           False,
    }

    login         = _pick_first_key(row, 'login')
    server        = _pick_first_key(row, 'server') or ''
    broker        = _pick_first_key(row, 'broker') or ''
    password      = _pick_first_key(row, 'broker_password') or ''
    login_int     = _coerce_int(login)
    manual_status = (_pick_first_key(row, 'broker_login_status') or '').strip().lower()
    expected_name = _expected_fullname_from_row(row)
    demo_int      = _coerce_int(_pick_first_key(row, 'demo_account')) or 0

    already_notified = (manual_status == VALID_STATUS)

    if manual_status in PROGRAMME_NEGATIVE_STATUSES:
        print(f"      [PRG][SKIP] programme={programme_id} — {manual_status}")
        result['reason'] = manual_status
        return result

    if login_int is None or not server:
        print(f"      [PRG][SKIP] programme={programme_id} — missing login/server")
        result['reason'] = 'missing login or server'
        return result

    ok_folder, folder_abs, terminal_exe, msg_folder = ensure_mt5_folder(
        server=server, login=login_int,
        user_id=user_id, kind='P', account_id=programme_id,
    )
    print(f"      [PRG][FOLDER] {msg_folder}")

    if not ok_folder:
        result['reason'] = f'folder: {msg_folder}'
        return result

    ok_launch = launch_terminal(terminal_exe, folder_abs)
    if not ok_launch:
        result['reason'] = 'launch failed'
        return result

    time.sleep(TERMINAL_BOOT_WAIT)
    probe_state, probe_info = probe_terminal_account(terminal_exe, folder_abs)

    if probe_state == 'logged_in':
        term_login  = probe_info.get('login')
        term_server = probe_info.get('server')
        term_name   = probe_info.get('name') or ''

        if str(term_login) == str(login_int):
            if _names_match(expected_name, term_name):
                # Programme accounts: demo allowed, no demo check.
                if already_notified:
                    print(f"      [PRG][OK-NO-EMAIL] programme={programme_id} | "
                          f"still logged in as {term_login} @ {term_server} "
                          f"| name='{term_name}' matches "
                          f"'{expected_name}' | demo_account={demo_int} "
                          f"(allowed); email already sent earlier")

                    _MANUAL_WINDOW.remove_item('PRG', user_id, programme_id)
                    result['ok'] = True
                    result['reason'] = 'already_notified'
                    result['login'] = term_login
                    result['server'] = term_server or server
                    result['broker'] = broker
                    result['folder'] = folder_abs
                    result['terminal_exe'] = terminal_exe
                    result['demo_account'] = demo_int
                    result.update(probe_info or {})
                    return result

                print(f"      [PRG][OK-NEW] programme={programme_id} | logged in as "
                      f"{term_login} @ {term_server} | name='{term_name}' "
                      f"matches '{expected_name}' | demo_account={demo_int} "
                      f"(allowed) — firing success email")

                _reset_programme_broker_login_attempt(programme_id)
                _set_programme_broker_login_status(programme_id, VALID_STATUS)
                _notify_programme_broker_success(programme_id, user_id)

                result['ok'] = True
                result['reason'] = 'newly_valid'
                result['login'] = term_login
                result['server'] = term_server or server
                result['broker'] = broker
                result['folder'] = folder_abs
                result['terminal_exe'] = terminal_exe
                result['demo_account'] = demo_int
                result.update(probe_info or {})
                _MANUAL_WINDOW.remove_item('PRG', user_id, programme_id)
                return result

            print(f"      [PRG][INVALID-FULLNAME] programme={programme_id} | "
                  f"terminal name='{term_name}' != expected '{expected_name}'")

            new_used = _notify_programme_broker_failure(
                programme_id=programme_id,
                user_id=user_id,
                new_status='fullname_mismatch',
            )
            print(f"      [PRG][ATTEMPT] broker_login_attempt_used -> "
                  f"{new_used if new_used is not None else '?'}")

            delete_mt5_folder(folder_abs, tag='PRG')
            _MANUAL_WINDOW.remove_item('PRG', user_id, programme_id)

            result['reason'] = 'fullname_mismatch'
            result['login'] = term_login
            result['server'] = term_server or server
            result['broker'] = broker
            result['folder'] = folder_abs
            result['terminal_exe'] = terminal_exe
            result['fullname_mismatch'] = {
                'expected': expected_name,
                'actual':   term_name,
            }
            return result

        print(f"      [PRG][MANUAL] programme={programme_id} | terminal logged in as "
              f"{term_login} @ {term_server}, expected {login_int} @ {server} "
              f"— needs manual fix")

    elif probe_state == 'not_logged_in':
        print(f"      [PRG][MANUAL] programme={programme_id} | terminal has no session "
              f"— needs manual login")

    else:
        print(f"      [PRG][MANUAL] programme={programme_id} | probe unavailable "
              f"({probe_info.get('error')}) — needs manual login")

    _MANUAL_WINDOW.add_item(
        kind='PRG',
        owner_id=user_id,
        account_id=programme_id,
        broker=broker,
        server=server,
        login=login_int,
        password=password,
        terminal_exe=terminal_exe,
    )
    result['reason'] = 'awaiting_manual_login'
    return result


# ==============================================================================
#  PROGRAMME DETECTION
# ==============================================================================
def _fetch_programmes_for_owner(user_id):
    select_cols = _programme_select_sql()
    sql = f"SELECT {select_cols} FROM programme WHERE userid = %s"
    res = db_query(sql, [user_id], timeout=15.0, quiet=True)
    if res.get('status') != 'success':
        return []
    out = []
    for raw in (res.get('results') or []):
        row = _normalize_row(raw)
        if row:
            out.append(row)
    return out


# ==============================================================================
#  MAIN
# ==============================================================================
def check_if_broker_is_logged_in(inv_id=None):
    report = {
        'investor_id':       str(inv_id) if inv_id is not None else None,
        'local_ip':          None,
        'owners':            [],
        'followers':         [],
        'programme_bindings': [],
        'owner_results':     [],
        'follower_results':  [],
        'programme_results': [],
        'success':           False,
        'message':           '',
    }

    print(f"\n{'='*70}")
    print(f"[CHECK] check_if_broker_is_logged_in(inv_id={inv_id})")
    print(f"{'='*70}")

    if not os.path.isdir(DEFAULT_MT5_PATH):
        report['message'] = f"DEFAULT_MT5_PATH missing: {DEFAULT_MT5_PATH}"
        print(f"   [ERROR] {report['message']}")
        return report

    if not os.path.isdir(MT5_DESTINATION_PATH):
        try:
            os.makedirs(MT5_DESTINATION_PATH, exist_ok=True)
        except Exception as e:
            report['message'] = f"Cannot create MT5_DESTINATION_PATH: {e}"
            print(f"   [ERROR] {report['message']}")
            return report

    print(f"   [PATH] DEFAULT : {DEFAULT_MT5_PATH}")
    print(f"   [PATH] DEST    : {MT5_DESTINATION_PATH}")

    # ----------------------------------------------------------------
    # DISCONNECT PASSES (SA + PRG)
    # ----------------------------------------------------------------
    try:
        completed = _process_disconnect_requests()
        if completed:
            print(f"   [SA][DISCONNECT] completed: {completed}")
    except Exception as e:
        print(f"   [SA][DISCONNECT] pass raised: {e}")
        traceback.print_exc()

    try:
        completed = _process_programme_disconnect_requests()
        if completed:
            print(f"   [PRG][DISCONNECT] completed: {completed}")
    except Exception as e:
        print(f"   [PRG][DISCONNECT] pass raised: {e}")
        traceback.print_exc()

    # ----------------------------------------------------------------
    # RESOLVE OWNERS / FOLLOWERS / PROGRAMME BINDINGS
    # ----------------------------------------------------------------
    local_ip = get_local_ip()
    report['local_ip'] = local_ip
    if not local_ip:
        report['message'] = 'Could not determine local IP'
        print(f"   [ERROR] {report['message']}")
        return report
    print(f"   [IP] {local_ip}")

    vps_sql = (
        "SELECT id, user_id, sub_account_id, programme_id, vps_ip_address "
        "FROM vps WHERE vps_ip_address = %s"
    )
    vps_res = db_query(vps_sql, [local_ip], timeout=15.0)
    if vps_res.get('status') != 'success':
        report['message'] = f"VPS lookup failed: {vps_res.get('message')}"
        print(f"   [ERROR] {report['message']}")
        return report

    vps_rows = vps_res.get('results', []) or []
    print(f"   [VPS] {len(vps_rows)} row(s) for IP")

    for row in vps_rows:
        uid   = _coerce_int(_pick_first_key(row, 'user_id', 'userid', 'uid'))
        sub   = _coerce_int(_pick_first_key(row, 'sub_account_id', 'subaccountid'))
        vpsid = _coerce_int(_pick_first_key(row, 'id', 'vps_id'))
        prog  = _coerce_int(_pick_first_key(row, 'programme_id', 'programmeid'))

        if uid is None:
            continue

        # ---- Programme-pinned VPS row --------------------------------
        if prog is not None and prog > 0:
            print(
                f"   [VPS] row id={vpsid} user_id={uid} "
                f"programme_id={prog} — programme binding"
            )
            report['programme_bindings'].append({
                'vps_row_id':   vpsid,
                'user_id':      uid,
                'programme_id': prog,
            })
            continue

        # ---- Investor / sub-account row ------------------------------
        sub_norm = sub if (sub is not None and sub > 0) else uid
        report['owners'].append({
            'vps_row_id':     vpsid,
            'user_id':        uid,
            'sub_account_id': sub_norm,
        })

    print(f"   [SA][OWNER] Detected: {len(report['owners'])}")
    print(f"   [PRG][BINDING] Detected: {len(report['programme_bindings'])}")

    if not report['owners'] and not report['programme_bindings']:
        report['message'] = f'No VPS owner found for IP {local_ip}'
        print(f"   [INFO] {report['message']}")
        return report

    # Followers are gathered from every investor owner row we saw.
    for owner in report['owners']:
        fol_sql = ("SELECT id, owner_id, sub_account_id, "
                   "follower_id, follower_sub_account_id, host_status "
                   "FROM vps_hosts_followers "
                   "WHERE owner_id = %s AND sub_account_id = %s "
                   "AND host_status = 'active'")
        fol_res = db_query(
            fol_sql,
            [owner['user_id'], owner['sub_account_id']],
            timeout=15.0,
        )
        if fol_res.get('status') != 'success':
            print(f"   [WARN] followers lookup failed: {fol_res.get('message')}")
            continue

        for row in fol_res.get('results', []) or []:
            fid  = _coerce_int(_pick_first_key(row, 'follower_id', 'followerid'))
            fsub = _coerce_int(_pick_first_key(
                row, 'follower_sub_account_id', 'followersubaccountid'))
            if fid is None:
                continue
            report['followers'].append({
                'owner_id':              owner['user_id'],
                'owner_sub_account_id':  owner['sub_account_id'],
                'follower_id':           fid,
                'follower_sub_account_id': fsub if fsub is not None else fid,
            })

    print(f"   [SA][FOLLOWER] Detected: {len(report['followers'])}")

    # ----------------------------------------------------------------
    # SUB-ACCOUNT PROBE PASS
    # ----------------------------------------------------------------
    print(f"\n   --- [SA] OWNERS ---")
    for owner in report['owners']:
        uid = owner['user_id']
        sub = owner['sub_account_id']
        print(f"\n   [SA][OWNER] user={uid} sub={sub}")
        row = _fetch_broker_row(user_id=uid, sub_account_id=sub)
        if not row:
            print(f"      [SA][WARN] No harvhub row")
            report['owner_results'].append({
                'source': 'SA',
                'user_id': uid, 'sub_account_id': sub,
                'ok': False, 'reason': 'no harvhub row',
            })
            continue
        res = _process_target(row, role='owner', user_id=uid, sub_account_id=sub)
        report['owner_results'].append(res)

    if report['followers']:
        print(f"\n   --- [SA] FOLLOWERS ---")

    for fol in report['followers']:
        uid = fol['follower_id']
        sub = fol['follower_sub_account_id']
        print(f"\n   [SA][FOLLOWER] user={uid} sub={sub}")
        row = _fetch_broker_row(user_id=uid, sub_account_id=sub)
        if not row:
            print(f"      [SA][WARN] No harvhub row")
            report['follower_results'].append({
                'source': 'SA',
                'user_id': uid, 'sub_account_id': sub,
                'ok': False, 'reason': 'no harvhub row',
            })
            continue
        res = _process_target(row, role='follower', user_id=uid, sub_account_id=sub)
        report['follower_results'].append(res)

    # ----------------------------------------------------------------
    # PROGRAMME PROBE PASS
    # ----------------------------------------------------------------
    print(f"\n   --- [PRG] PROGRAMMES ---")

    processed_programme_ids = set()

    def _process_one_programme(uid, programme_id):
        if programme_id in processed_programme_ids:
            return
        processed_programme_ids.add(programme_id)

        prog_row = _fetch_programme_row(programme_id=programme_id, user_id=uid)
        if not prog_row:
            print(f"      [PRG][WARN] No programme row for id={programme_id}")
            report['programme_results'].append({
                'source': 'PRG',
                'user_id': uid,
                'programme_id': programme_id,
                'ok': False,
                'reason': 'no programme row',
            })
            return

        manual_status = (
            _pick_first_key(prog_row, 'broker_login_status') or ''
        ).strip().lower()

        if manual_status in PROGRAMME_NEGATIVE_STATUSES:
            print(f"      [PRG][SKIP] programme={programme_id} — {manual_status}")
            report['programme_results'].append({
                'source': 'PRG',
                'user_id': uid,
                'programme_id': programme_id,
                'ok': False,
                'reason': manual_status,
            })
            return

        login_v  = _pick_first_key(prog_row, 'login')
        server_v = _pick_first_key(prog_row, 'server')
        if not _coerce_int(login_v) or not (server_v or '').strip():
            print(f"      [PRG][SKIP] programme={programme_id} — no broker details")
            report['programme_results'].append({
                'source': 'PRG',
                'user_id': uid,
                'programme_id': programme_id,
                'ok': False,
                'reason': 'no broker details',
            })
            return

        res = _process_programme_target(
            prog_row, user_id=uid, programme_id=programme_id
        )
        report['programme_results'].append(res)

    # 1) Direct bindings from `vps.programme_id`
    for binding in report['programme_bindings']:
        uid = binding['user_id']
        pid = binding['programme_id']
        print(f"\n   [PRG] user={uid} programme={pid} (VPS binding)")
        _process_one_programme(uid, pid)

    # 2) Legacy fallback: every candidate user_id discovered above
    candidate_user_ids = set()
    for owner in report['owners']:
        candidate_user_ids.add(owner['user_id'])
    for fol in report['followers']:
        candidate_user_ids.add(fol['follower_id'])

    for uid in sorted(candidate_user_ids):
        programmes = _fetch_programmes_for_owner(uid)
        if not programmes:
            continue

        for prog_row in programmes:
            programme_id = _coerce_int(prog_row.get('id'))
            if not programme_id:
                continue
            if programme_id in processed_programme_ids:
                continue

            print(f"\n   [PRG] user={uid} programme={programme_id} (owner lookup)")
            _process_one_programme(uid, programme_id)

    # ----------------------------------------------------------------
    # SUMMARY
    # ----------------------------------------------------------------
    ok_owners    = sum(1 for r in report['owner_results']    if r.get('ok'))
    ok_followers = sum(1 for r in report['follower_results'] if r.get('ok'))
    ok_progs     = sum(1 for r in report['programme_results'] if r.get('ok'))

    report['success'] = (ok_owners + ok_followers + ok_progs) > 0
    report['message'] = (
        f"[SA] owners={len(report['owners'])}({ok_owners} ok), "
        f"followers={len(report['followers'])}({ok_followers} ok) | "
        f"[PRG] programmes={len(report['programme_results'])}({ok_progs} ok)"
    )
    print(f"\n   [RESULT] {report['message']}")
    return report


# ==============================================================================
#  MAIN LOOP
# ==============================================================================
def main():
    print(f"\n{'#'*70}")
    print(f"#  brokerdetails — check_if_broker_is_logged_in loop")
    print(f"#  started at {datetime.now().isoformat(timespec='seconds')}")
    print(f"{'#'*70}")

    interval = 10
    for arg in sys.argv[1:]:
        if arg.startswith('--interval='):
            try:
                interval = max(1, int(arg.split('=', 1)[1]))
            except ValueError:
                pass

    try:
        while True:
            try:
                result = check_if_broker_is_logged_in()
                print(f"[main] {result.get('message')}")
            except Exception as e:
                print(f"[main] check_if_broker_is_logged_in raised: {e}")
                traceback.print_exc()

            print(f"[main] sleeping {interval}s...\n")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("[main] interrupted — shutting down mysqlremote")
        try:
            db.stop_worker()
        except Exception:
            pass


if __name__ == "__main__":
    main()