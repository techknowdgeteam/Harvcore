# mysqlremote.py
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import requests
import urllib3
import zipfile
import io
import time
import signal
import sys
import os
import re
import json
import subprocess
import tempfile
import glob
import shutil
import threading
import queue
import uuid as _uuid_module
from datetime import datetime, date
from decimal import Decimal
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==============================================================================
#  CONFIG
# ==============================================================================
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

primary_servers = {
    'query_page': 'https://harvhub.wuaze.com/phpmyadmintemplate.php',
    'fetch': 'https://harvhub.wuaze.com/phpmyadmin_tablesfetch.php'
}
backup_servers = {
    'query_page': 'https://harvhub.wuaze.com/phpmyadmintemplate.php',
    'fetch': 'https://harvhub.wuaze.com/phpmyadmin_tablesfetch.php'
}
server3 = {
    'query_page': 'https://harvhub.wuaze.com/phpmyadmintemplate.php',
    'fetch': 'https://harvhub.wuaze.com/phpmyadmin_tablesfetch.php'
}

DEFAULT_WAIT_TIMEOUT = 20.0

CHROMEDRIVER_CACHE_DIR = os.path.expanduser(r"~\.chromedriver_cache")
CHROMEDRIVER_EXE = os.path.join(CHROMEDRIVER_CACHE_DIR, "chromedriver.exe")
CHROMEDRIVER_VERSION_FILE = os.path.join(CHROMEDRIVER_CACHE_DIR, "driver.version")

# ─────────────────────────────────────────────────────────────────────────────
#  DNS / HOST OVERRIDE (disabled — InfinityFree rotates edge IPs)
# ─────────────────────────────────────────────────────────────────────────────
PIN_KNOWN_HOST = False
KNOWN_HOST_IP = "185.27.134.138"
KNOWN_HOST_NAME = "harvhub.wuaze.com"

CFT_JSON_URLS = [
    "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json",
    "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json",
    "https://raw.githubusercontent.com/GoogleChromeLabs/chrome-for-testing/main/data/known-good-versions-with-downloads.json",
    "https://raw.githubusercontent.com/GoogleChromeLabs/chrome-for-testing/main/data/last-known-good-versions-with-downloads.json",
    "https://cdn.npmmirror.com/binaries/chrome-for-testing/known-good-versions-with-downloads.json",
    "https://registry.npmmirror.com/-/binary/chrome-for-testing/known-good-versions-with-downloads.json",
]


def _cft_zip_candidates(version):
    return [
        f"https://storage.googleapis.com/chrome-for-testing-public/{version}/win64/chromedriver-win64.zip",
        f"https://cdn.npmmirror.com/binaries/chrome-for-testing/{version}/win64/chromedriver-win64.zip",
        f"https://registry.npmmirror.com/-/binary/chrome-for-testing/{version}/win64/chromedriver-win64.zip",
        f"https://chromedriver.storage.googleapis.com/{version}/chromedriver_win32.zip",
        f"https://cdn.npmmirror.com/binaries/chromedriver/{version}/chromedriver_win32.zip",
    ]


# ==============================================================================
#  PUBLIC API — QUEUES
# ==============================================================================
queryrequest: "queue.Queue" = queue.Queue()
queryresult:  "queue.Queue" = queue.Queue()

_browser_lock = threading.Lock()
_shutdown_event = threading.Event()
_worker_thread = None
_driver = None
_session = None
_current_servers = primary_servers
_browser_ready = threading.Event()


# ==============================================================================
#  LOGGING
# ==============================================================================
def _log(msg):
    try:
        print(f"[mysqlremote] {msg}", flush=True)
    except Exception:
        pass


# ==============================================================================
#  CHROME VERSION DETECTION
# ==============================================================================
def _get_installed_chrome_version():
    if not os.path.exists(CHROME_PATH):
        return None
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-Item '{CHROME_PATH}').VersionInfo.ProductVersion"],
            capture_output=True, text=True, timeout=10)
        v = (r.stdout or "").strip()
        if v and re.match(r'^\d+\.\d+\.\d+\.\d+$', v):
            return v
    except Exception:
        pass
    try:
        parent = os.path.dirname(CHROME_PATH)
        for entry in os.listdir(parent):
            if re.match(r'^\d+\.\d+\.\d+\.\d+$', entry):
                return entry
    except Exception:
        pass
    return None


# ==============================================================================
#  HTTP HELPERS
# ==============================================================================
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


def _http_get_json(url, timeout=15):
    r = requests.get(url, headers=_HEADERS, timeout=timeout, verify=False)
    r.raise_for_status()
    return r.json()


def _http_get_bytes(url, timeout=90):
    r = requests.get(url, headers=_HEADERS, timeout=timeout,
                     verify=False, stream=True)
    r.raise_for_status()
    buf = io.BytesIO()
    for chunk in r.iter_content(chunk_size=64 * 1024):
        if chunk:
            buf.write(chunk)
    return buf.getvalue()


# ==============================================================================
#  VERSION PICKING / ZIP EXTRACT
# ==============================================================================
def _pick_best_cft_version(versions, target):
    if not versions:
        return None
    target = target or ""
    target_major = target.split('.')[0] if target else None

    def _key(v):
        try:
            return tuple(int(x) for x in v.split('.'))
        except Exception:
            return (0,)

    versions = sorted(set(versions), key=_key, reverse=True)
    if target in versions:
        return target
    if target_major:
        same = [v for v in versions if v.split('.')[0] == target_major]
        if same:
            return same[0]
        try:
            prev = str(int(target_major) - 1)
            prev_list = [v for v in versions if v.split('.')[0] == prev]
            if prev_list:
                return prev_list[0]
        except Exception:
            pass
    return versions[0]


def _extract_chromedriver_from_zip(zip_bytes):
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    target = None
    for name in zf.namelist():
        if os.path.basename(name).lower() == "chromedriver.exe":
            target = name
            break
    if not target:
        for name in zf.namelist():
            if name.lower().endswith(".exe"):
                target = name
                break
    if not target:
        raise RuntimeError("chromedriver.exe not found in ZIP")
    os.makedirs(CHROMEDRIVER_CACHE_DIR, exist_ok=True)
    with zf.open(target) as src:
        data = src.read()
    with open(CHROMEDRIVER_EXE, "wb") as dst:
        dst.write(data)
    return CHROMEDRIVER_EXE


def _fetch_catalog():
    for url in CFT_JSON_URLS:
        try:
            _log(f"  Trying catalog: {url}")
            data = _http_get_json(url)
            versions = data.get("versions")
            if versions:
                _log(f"  ✅ Catalog from: {url} ({len(versions)} versions)")
                return versions
        except Exception as e:
            _log(f"  ❌ Failed: {str(e)[:140]}")
    return None


def _try_download_zip_for_version(version):
    for url in _cft_zip_candidates(version):
        try:
            _log(f"  Trying ZIP: {url}")
            blob = _http_get_bytes(url)
            _log(f"  ✅ Downloaded {len(blob):,} bytes")
            return blob
        except Exception as e:
            _log(f"  ❌ Failed: {str(e)[:140]}")
    return None


def _download_via_mirrors(target_version):
    catalog = _fetch_catalog()
    if not catalog:
        return None
    versions = [v.get("version") for v in catalog if v.get("version")]
    picked = _pick_best_cft_version(versions, target_version)
    if not picked:
        return None
    _log(f"Picked version: {picked}")
    blob = _try_download_zip_for_version(picked)
    if not blob:
        return None
    try:
        return _extract_chromedriver_from_zip(blob)
    except Exception as e:
        _log(f"ZIP extract failed: {e}")
        return None


def _download_via_pip_binary(target_version):
    if not target_version:
        return None
    major = target_version.split('.')[0]
    candidates = [target_version, f"{major}.0.0.0"]
    for pkg_version in candidates:
        try:
            _log(f"Trying pip install chromedriver-binary=={pkg_version} ...")
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet",
                 "--disable-pip-version-check",
                 f"chromedriver-binary=={pkg_version}"],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode != 0:
                continue
            import importlib.util
            spec = importlib.util.find_spec("chromedriver_binary")
            if spec and spec.submodule_search_locations:
                for base in spec.submodule_search_locations:
                    found = glob.glob(os.path.join(base, "chromedriver*.exe"))
                    if found:
                        os.makedirs(CHROMEDRIVER_CACHE_DIR, exist_ok=True)
                        shutil.copy2(found[0], CHROMEDRIVER_EXE)
                        _log(f"Installed via pip: {CHROMEDRIVER_EXE}")
                        return CHROMEDRIVER_EXE
        except Exception as e:
            _log(f"  pip attempt failed: {str(e)[:160]}")
    return None


def _read_cached_driver_version():
    if not os.path.exists(CHROMEDRIVER_VERSION_FILE):
        return None
    try:
        with open(CHROMEDRIVER_VERSION_FILE, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except Exception:
        return None


def _record_driver_version(driver_path, fallback):
    try:
        os.makedirs(CHROMEDRIVER_CACHE_DIR, exist_ok=True)
        version = fallback
        try:
            r = subprocess.run([driver_path, "--version"],
                               capture_output=True, text=True, timeout=5)
            out = (r.stdout or r.stderr or "").strip()
            m = re.search(r'ChromeDriver\s+(\d+\.\d+\.\d+\.\d+)', out)
            if m:
                version = m.group(1)
        except Exception:
            pass
        with open(CHROMEDRIVER_VERSION_FILE, 'w', encoding='utf-8') as f:
            f.write(version)
    except Exception:
        pass


def _resolve_chromedriver():
    chrome_version = _get_installed_chrome_version()
    chrome_major = chrome_version.split('.')[0] if chrome_version else None
    if chrome_version:
        _log(f"Detected Chrome: {chrome_version}")
    cached = _read_cached_driver_version()
    if chrome_major and cached and cached.split('.')[0] == chrome_major:
        _log("Cached driver matches Chrome — using it")
        return CHROMEDRIVER_EXE

    _log("Attempting mirror-based ChromeDriver download...")
    try:
        path = _download_via_mirrors(chrome_version)
        if path:
            _record_driver_version(path, chrome_version)
            return path
    except Exception as e:
        _log(f"Mirror download error: {str(e)[:200]}")

    _log("Attempting pip-based ChromeDriver install...")
    try:
        path = _download_via_pip_binary(chrome_version)
        if path:
            _record_driver_version(path, chrome_version)
            return path
    except Exception as e:
        _log(f"pip fallback error: {str(e)[:200]}")

    try:
        _log("Trying webdriver-manager as last network fallback...")
        from webdriver_manager.chrome import ChromeDriverManager
        path = ChromeDriverManager().install()
        try:
            os.makedirs(CHROMEDRIVER_CACHE_DIR, exist_ok=True)
            shutil.copy2(path, CHROMEDRIVER_EXE)
            _record_driver_version(CHROMEDRIVER_EXE, chrome_version)
            return CHROMEDRIVER_EXE
        except Exception:
            return path
    except Exception as e:
        _log(f"webdriver-manager failed: {str(e)[:160]}")

    if os.path.exists(CHROMEDRIVER_EXE):
        _log("Using STALE cached ChromeDriver")
        return CHROMEDRIVER_EXE

    raise RuntimeError("ChromeDriver resolution failed — all sources exhausted")


# ==============================================================================
#  PROCESS / BROWSER HYGIENE
# ==============================================================================
def _kill_chrome_processes_and_clean_locks():
    _log("Cleaning Chrome processes and locks...")
    try:
        subprocess.run(["taskkill", "/f", "/im", "chrome.exe", "/t"],
                       capture_output=True, text=True)
        subprocess.run(["taskkill", "/f", "/im", "chromedriver.exe", "/t"],
                       capture_output=True, text=True)
        time.sleep(1.5)
    except Exception as e:
        _log(f"Error killing: {e}")


def _build_chrome_options(temp_dir):
    opts = Options()
    if os.path.exists(CHROME_PATH):
        opts.binary_location = CHROME_PATH

    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--log-level=3")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument(f"--user-data-dir={temp_dir}")
    opts.add_experimental_option("excludeSwitches", ["enable-logging"])
    opts.add_experimental_option("useAutomationExtension", False)

    opts.add_argument("--no-proxy-server")

    opts.add_argument("--disable-background-timer-throttling")
    opts.add_argument("--disable-renderer-backgrounding")
    opts.add_argument("--disable-backgrounding-occluded-windows")

    if PIN_KNOWN_HOST and KNOWN_HOST_IP and KNOWN_HOST_NAME:
        rule = f"MAP {KNOWN_HOST_NAME} {KNOWN_HOST_IP}"
        opts.add_argument(f"--host-resolver-rules={rule}")
        _log(f"Pinned DNS: {KNOWN_HOST_NAME} → {KNOWN_HOST_IP}")

    return opts


# ==============================================================================
#  BROWSER LIFECYCLE
# ==============================================================================
def _is_browser_alive():
    global _driver
    if _driver is None:
        return False
    try:
        _ = _driver.title
        u = _driver.current_url
        if not u:
            return False
        if u.strip() in ("data:,", "about:blank"):
            return False
        return True
    except Exception:
        return False


def _open_browser():
    global _driver, _session, _current_servers

    with _browser_lock:
        if _is_browser_alive():
            _log("Browser already alive — reusing")
            return True

        if _driver is not None:
            try:
                _driver.quit()
            except Exception:
                pass
            _driver = None

        _kill_chrome_processes_and_clean_locks()
        temp_dir = tempfile.mkdtemp(prefix='chrome_selenium_')
        opts = _build_chrome_options(temp_dir)

        for attempt in range(1, 4):
            try:
                if attempt > 1:
                    _kill_chrome_processes_and_clean_locks()
                    time.sleep(2)
                _log(f"[driver attempt {attempt}/3] resolving chromedriver")
                path = _resolve_chromedriver()
                service = Service(path)
                _driver = webdriver.Chrome(service=service, options=opts)
                _log("ChromeDriver initialized (headless)")
                break
            except Exception as e:
                msg = str(e)
                _log(f"[driver attempt {attempt}/3] failed: {msg[:200]}")
                if "only supports Chrome version" in msg:
                    try:
                        if os.path.exists(CHROMEDRIVER_VERSION_FILE):
                            os.remove(CHROMEDRIVER_VERSION_FILE)
                    except Exception:
                        pass
                _driver = None
                if attempt >= 3:
                    _log("Could not start ChromeDriver after 3 attempts")
                    return False
                time.sleep(2)

        if _driver is None:
            return False

        # ── Navigate to the query page. The textarea is built by JS, so we
        #    wait for `textarea.sql-query` to appear inside a `.db-window`.
        last_error = None
        for servers, label in [(primary_servers, "Primary"),
                               (backup_servers, "Backup"),
                               (server3, "Server 3")]:
            _current_servers = servers
            try:
                _log(f"[{label}] driver.get(query_page)")
                _driver.get(servers['query_page'])

                _log(f"[{label}] waiting for textarea.sql-query")
                try:
                    WebDriverWait(_driver, 25).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, "textarea.sql-query")))
                except Exception as wait_err:
                    try:
                        cur_url = _driver.current_url
                    except Exception:
                        cur_url = "<unavailable>"
                    try:
                        cur_title = _driver.title
                    except Exception:
                        cur_title = "<unavailable>"
                    try:
                        body_text = _driver.find_element(
                            By.TAG_NAME, "body").text[:600]
                    except Exception:
                        body_text = "<no body>"
                    try:
                        win_count = len(_driver.find_elements(
                            By.CSS_SELECTOR, ".db-window"))
                        ta_count = len(_driver.find_elements(
                            By.CSS_SELECTOR, "textarea.sql-query"))
                    except Exception:
                        win_count = ta_count = -1
                    _log(f"[{label}] ❌ wait for textarea.sql-query failed")
                    _log(f"[{label}]    url   = {cur_url}")
                    _log(f"[{label}]    title = {cur_title!r}")
                    _log(f"[{label}]    windows={win_count} textareas={ta_count}")
                    _log(f"[{label}]    body  = {body_text!r}")
                    _log(f"[{label}]    err   = {type(wait_err).__name__}: {wait_err}")
                    raise

                _log(f"[{label}] ✅ ready (found textarea.sql-query)")

                if _session:
                    try:
                        _session.close()
                    except Exception:
                        pass
                _session = requests.Session()
                for c in _driver.get_cookies():
                    _session.cookies.set(c['name'], c['value'])

                _browser_ready.set()
                return True

            except Exception as e:
                last_error = f"{label}: {type(e).__name__}: {e}"
                _log(f"[{label}] ❌ {str(e)[:200]}")

        _log(f"All servers failed. Last error: {last_error}")
        try:
            _driver.quit()
        except Exception:
            pass
        _driver = None
        _browser_ready.clear()
        return False


def _ensure_browser():
    if _is_browser_alive():
        _browser_ready.set()
        return True
    return _open_browser()


# ==============================================================================
#  DOM HELPERS — scoped to the focused / first .db-window
# ==============================================================================
def _active_window(d):
    """Return the focused .db-window element or the first one, or None."""
    try:
        els = d.find_elements(By.CSS_SELECTOR, ".db-window.focused")
        if els:
            return els[0]
        els = d.find_elements(By.CSS_SELECTOR, ".db-window")
        if els:
            return els[0]
    except Exception:
        pass
    return None


def _read_exec_status(d):
    """
    Read the per-window status banner:
        <div class="win-exec-status" data-state="idle|loading|success|partial|empty|error">
          <span class="status-label">…</span>
          <span class="status-meta">…</span>
        </div>
    """
    win = _active_window(d)
    if win is None:
        return None
    try:
        el = win.find_element(By.CSS_SELECTOR, ".win-exec-status")
    except Exception:
        return None

    try:
        state = (el.get_attribute("data-state") or "").strip().lower()
    except Exception:
        state = ""
    if not state:
        return None

    label = ""
    try:
        label = (el.find_element(By.CSS_SELECTOR, ".status-label").text or "").strip()
    except Exception:
        pass
    meta = ""
    try:
        meta = (el.find_element(By.CSS_SELECTOR, ".status-meta").text or "").strip()
    except Exception:
        pass

    return {
        'state':    state,
        'label':    label,
        'meta':     meta,
        'rows':     None,
        'affected': None,
        'query_id': None,
    }


def _status_terminal(d, query_id=None):
    """This page uses: idle | loading | success | partial | empty | error."""
    s = _read_exec_status(d)
    if not s:
        return False
    return s['state'] in ('success', 'partial', 'empty', 'error')


def _js_display_ready(d):
    """The 'SQL Query' display block is shown once execution starts."""
    win = _active_window(d)
    if win is None:
        return False
    try:
        for el in win.find_elements(By.CSS_SELECTOR, ".win-sql-display"):
            if el.is_displayed():
                return True
    except Exception:
        pass
    return False


def _btn_re_enabled(d):
    win = _active_window(d)
    if win is None:
        return False
    try:
        for el in win.find_elements(By.CSS_SELECTOR, ".exec-btn"):
            if el.is_enabled() and (el.text or "").strip() == "Execute Query":
                return True
    except Exception:
        pass
    return False


def _result_table_ready(d):
    """True once the page has rendered any per-statement block or result."""
    win = _active_window(d)
    if win is None:
        return False
    try:
        if win.find_elements(By.CSS_SELECTOR, ".stmt-block"):
            return True
        if win.find_elements(By.CSS_SELECTOR, ".win-message.error"):
            return True
        for el in win.find_elements(By.CSS_SELECTOR, ".win-results-summary"):
            if el.is_displayed():
                return True
    except Exception:
        pass
    return False


def _any_terminal_state(d):
    return _js_display_ready(d) or _btn_re_enabled(d) or _result_table_ready(d)


def _wait_for_completion(timeout, query_id=None):
    """
    Wait until the status banner reaches a terminal state.
    The banner is guaranteed to exist (built with the window), so we can
    rely purely on the exec-status state machine here.
    """
    t0 = time.perf_counter()

    # Give the page a brief moment to enter 'loading' if it's going to.
    try:
        WebDriverWait(_driver, min(2.0, timeout), poll_frequency=0.1).until(
            lambda d: (_read_exec_status(d) or {}).get('state') in
                      ('loading', 'success', 'partial', 'empty', 'error')
        )
    except Exception:
        pass

    try:
        WebDriverWait(_driver, timeout, poll_frequency=0.1).until(
            lambda d: _status_terminal(d, query_id))
        s = _read_exec_status(_driver) or {}
        return True, time.perf_counter() - t0, f"exec-status={s.get('state')}"
    except Exception:
        s = _read_exec_status(_driver) or {}
        return False, time.perf_counter() - t0, f"timeout (last={s.get('state')!r})"


# ==============================================================================
#  QUERY CLASSIFICATION
# ==============================================================================
_READ_KEYWORDS = ('SELECT', 'SHOW', 'DESCRIBE', 'DESC', 'EXPLAIN', 'WITH')


def _is_read_query(sql):
    s = sql.strip()
    while True:
        prev = s
        s = s.lstrip()
        if s.startswith('--'):
            nl = s.find('\n')
            s = s[nl + 1:] if nl != -1 else ''
        elif s.startswith('/*'):
            end = s.find('*/')
            s = s[end + 2:] if end != -1 else ''
        if s == prev:
            break
    if not s:
        return False
    upper = s.upper()
    return any(upper.startswith(kw) for kw in _READ_KEYWORDS)


# ==============================================================================
#  PARAM SUBSTITUTION
# ==============================================================================
def _substitute_params(sql_query, params):
    if not params:
        return sql_query
    if not isinstance(params, (tuple, list)):
        params = (params,)
    final_sql = sql_query
    for p in params:
        if '%s' not in final_sql:
            break
        if p is None:
            final_sql = final_sql.replace('%s', 'NULL', 1)
        elif isinstance(p, bool):
            final_sql = final_sql.replace('%s', '1' if p else '0', 1)
        elif isinstance(p, (int, float, Decimal)):
            final_sql = final_sql.replace('%s', str(p), 1)
        elif isinstance(p, (datetime, date)):
            final_sql = final_sql.replace('%s', f"'{p.isoformat()}'", 1)
        elif isinstance(p, (dict, list)):
            js = json.dumps(p, ensure_ascii=False)
            esc = js.replace("\\", "\\\\").replace("'", "''")
            final_sql = final_sql.replace('%s', f"'{esc}'", 1)
        else:
            esc = str(p).replace("\\", "\\\\").replace("'", "''")
            final_sql = final_sql.replace('%s', f"'{esc}'", 1)
    return final_sql


# ==============================================================================
#  CORE QUERY EXECUTOR
# ==============================================================================
def _execute_sql_on_page(final_sql, timeout=DEFAULT_WAIT_TIMEOUT):
    global _driver

    if not _ensure_browser():
        return {
            'status': 'error',
            'message': 'Browser not available',
            'results': [],
            'affected_rows': 0,
            'query_id': None,
            'raw_sql': final_sql,
            'elapsed': 0.0,
        }

    t_start = time.perf_counter()
    query_id = str(_uuid_module.uuid4().int)[:12]

    # ── Reset per-window UI state for a clean read ─────────────────────────
    try:
        _driver.execute_script("""
            (function(){
                var w = document.querySelector('.db-window.focused')
                     || document.querySelector('.db-window');
                if (!w) return;
                var s = w.querySelector('.win-exec-status');
                if (s) {
                    s.dataset.state = 'idle';
                    var l = s.querySelector('.status-label');
                    var m = s.querySelector('.status-meta');
                    if (l) l.textContent = 'Waiting…';
                    if (m) m.textContent = '';
                }
                var d = w.querySelector('.win-sql-display');
                if (d) d.style.display = 'none';
                var r = w.querySelector('.win-query-result');
                if (r) r.innerHTML = '';
                var sm = w.querySelector('.win-results-summary');
                if (sm) { sm.style.display = 'none'; sm.innerHTML = ''; }
                var msg = w.querySelector('.win-message');
                if (msg) { msg.style.display = 'none'; msg.textContent = ''; }
            })();
        """)
    except Exception:
        pass

    # ── Inject SQL and click Execute ───────────────────────────────────────
    try:
        ta = None
        for sel in ["textarea.sql-query", ".sql-query", "textarea"]:
            try:
                ta = WebDriverWait(_driver, 4).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                break
            except Exception:
                continue
        if not ta:
            raise Exception("query textarea (textarea.sql-query) not found")

        # Native setter so JS frameworks see the change
        _driver.execute_script("""
            var el = arguments[0], val = arguments[1];
            var proto = Object.getPrototypeOf(el);
            var desc  = Object.getOwnPropertyDescriptor(proto, 'value');
            if (desc && desc.set) { desc.set.call(el, val); }
            else { el.value = val; }
            el.dispatchEvent(new Event('input',  { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        """, ta, final_sql)
        time.sleep(0.15)

        btn = None
        for sel in [".exec-btn",
                    "//button[contains(text(), 'Execute')]",
                    "//button[@type='submit']"]:
            try:
                btn = (_driver.find_element(By.XPATH, sel)
                       if sel.startswith("//")
                       else _driver.find_element(By.CSS_SELECTOR, sel))
                if btn:
                    break
            except Exception:
                continue

        if btn is None:
            raise Exception("execute button (.exec-btn) not found")

        _driver.execute_script("arguments[0].click();", btn)
    except Exception as e:
        return {
            'status': 'error',
            'message': f"Query input failed: {e}",
            'results': [],
            'affected_rows': 0,
            'query_id': query_id,
            'raw_sql': final_sql,
            'elapsed': time.perf_counter() - t_start,
        }

    # ── Wait for terminal state ────────────────────────────────────────────
    ready, _, reason = _wait_for_completion(timeout, query_id)

    status_banner = _read_exec_status(_driver) or {}
    state = (status_banner.get('state') or '').lower()
    banner_meta = (status_banner.get('meta') or '').strip()
    banner_label = (status_banner.get('label') or '').strip()

    is_read = _is_read_query(final_sql)

    # Pull the per-window message banner (error/success text)
    def _win_message():
        try:
            win = _active_window(_driver)
            if win is None:
                return ""
            els = win.find_elements(By.CSS_SELECTOR, ".win-message")
            if els and els[0].is_displayed():
                return (els[0].text or "").strip()
        except Exception:
            pass
        return ""

    # ── Error ──────────────────────────────────────────────────────────────
    if state == 'error':
        err_msg = _win_message() or banner_label or "query failed"
        return {
            'status': 'error',
            'message': err_msg,
            'results': [],
            'affected_rows': 0,
            'query_id': query_id,
            'raw_sql': final_sql,
            'elapsed': time.perf_counter() - t_start,
        }

    # ── Empty ──────────────────────────────────────────────────────────────
    if state == 'empty':
        return {
            'status': 'success',
            'message': banner_label or 'Query executed successfully (0 rows)',
            'results': [],
            'affected_rows': 0,
            'query_id': query_id,
            'raw_sql': final_sql,
            'elapsed': time.perf_counter() - t_start,
        }

    # ── Parse results ──────────────────────────────────────────────────────
    results = []
    affected_rows = 0
    try:
        soup = BeautifulSoup(_driver.page_source, 'html.parser')

        # Find the active window in the soup
        win = (soup.find('div', class_='db-window focused')
               or soup.find('div', class_='db-window'))

        # Non-read queries: affected rows reported in the message/summary
        if not is_read:
            # Try to extract from statement blocks first
            if win:
                for blk in win.select('.stmt-block[data-status="success"]'):
                    body = blk.find('div', class_='stmt-affected-body')
                    if body:
                        m = re.search(r'Affected rows:\s*(\d+)', body.get_text())
                        if m:
                            affected_rows += int(m.group(1))
            # Fallback: status-meta "N affected"
            if not affected_rows and banner_meta:
                m = re.search(r'(\d+)\s*affected', banner_meta, re.IGNORECASE)
                if m:
                    affected_rows = int(m.group(1))

            return {
                'status': 'success',
                'message': banner_label or
                           f'Write query executed ({affected_rows} row(s) affected)',
                'results': [],
                'affected_rows': affected_rows,
                'query_id': query_id,
                'raw_sql': final_sql,
                'elapsed': time.perf_counter() - t_start,
            }

        # Read queries: parse statement blocks
        if win:
            for blk in win.select('.stmt-block'):
                blk_status = (blk.get('data-status') or '').strip().lower()
                if blk_status not in ('success',):
                    continue
                tbl = blk.find('table')
                if not tbl:
                    continue
                headers = [th.get_text(strip=True)
                           for th in tbl.find_all('th')]
                for tr in tbl.find_all('tr')[1:]:
                    tds = tr.find_all('td')
                    if not tds:
                        continue
                    row = {}
                    for i, td in enumerate(tds):
                        key = headers[i] if i < len(headers) else f"col{i}"
                        # Cell content lives in span.cell-content; fall back to td text
                        span = td.find('span', class_='cell-content')
                        row[key] = (span.get_text() if span
                                    else td.get_text(strip=True))
                    results.append(row)

            # Fallback: classic container / table search
            if not results:
                container = (win.find('div', class_='win-query-result') if win
                             else None)
                tbl = container.find('table') if container else None
                if tbl:
                    headers = [th.get_text(strip=True)
                               for th in tbl.find_all('th')]
                    for tr in tbl.find_all('tr')[1:]:
                        tds = tr.find_all('td')
                        if not tds:
                            continue
                        row = {}
                        for i, td in enumerate(tds):
                            key = headers[i] if i < len(headers) else f"col{i}"
                            span = td.find('span', class_='cell-content')
                            row[key] = (span.get_text() if span
                                        else td.get_text(strip=True))
                        results.append(row)
    except Exception as e:
        return {
            'status': 'error',
            'message': f"Parse error: {e}",
            'results': [],
            'affected_rows': 0,
            'query_id': query_id,
            'raw_sql': final_sql,
            'elapsed': time.perf_counter() - t_start,
        }

    return {
        'status': 'success',
        'message': banner_label or f'Query executed successfully ({len(results)} rows)',
        'results': results,
        'affected_rows': affected_rows,
        'query_id': query_id,
        'raw_sql': final_sql,
        'elapsed': time.perf_counter() - t_start,
    }


# ==============================================================================
#  WORKER THREAD
# ==============================================================================
def _worker_loop():
    _log("Worker thread started")

    _ensure_browser()

    while not _shutdown_event.is_set():
        try:
            item = queryrequest.get(timeout=1.0)
        except queue.Empty:
            if not _is_browser_alive():
                _log("Browser died — attempting relaunch")
                _ensure_browser()
            continue

        if item is None:
            _log("Received sentinel — worker exiting")
            break

        if isinstance(item, str):
            sql = item
            params = None
            timeout = DEFAULT_WAIT_TIMEOUT
        elif isinstance(item, dict):
            sql = item.get('sql', '')
            params = item.get('params')
            timeout = float(item.get('timeout', DEFAULT_WAIT_TIMEOUT))
        else:
            queryresult.put({
                'status': 'error',
                'message': f'Unsupported queryrequest item type: {type(item).__name__}',
                'results': [],
                'affected_rows': 0,
                'query_id': None,
                'raw_sql': None,
                'elapsed': 0.0,
            })
            continue

        if not sql or not sql.strip():
            queryresult.put({
                'status': 'error',
                'message': 'Empty SQL',
                'results': [],
                'affected_rows': 0,
                'query_id': None,
                'raw_sql': sql,
                'elapsed': 0.0,
            })
            continue

        final_sql = _substitute_params(sql, params)

        try:
            result = _execute_sql_on_page(final_sql, timeout=timeout)
        except Exception as e:
            result = {
                'status': 'error',
                'message': f'Unhandled executor error: {e}',
                'results': [],
                'affected_rows': 0,
                'query_id': None,
                'raw_sql': final_sql,
                'elapsed': 0.0,
            }

        queryresult.put(result)

    _log("Worker thread exiting")


def start_worker():
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return
    _shutdown_event.clear()
    _worker_thread = threading.Thread(
        target=_worker_loop, name="mysqlremote-worker", daemon=True)
    _worker_thread.start()


# ==============================================================================
#  SYNCHRONOUS HELPER
# ==============================================================================
def request_query(sql, params=None, timeout=DEFAULT_WAIT_TIMEOUT,
                  result_timeout=None):
    start_worker()
    queryrequest.put({'sql': sql, 'params': params, 'timeout': timeout})

    if result_timeout is None:
        result_timeout = timeout + 30.0

    try:
        return queryresult.get(timeout=result_timeout)
    except queue.Empty:
        return {
            'status': 'error',
            'message': f'No result within {result_timeout:.1f}s',
            'results': [],
            'affected_rows': 0,
            'query_id': None,
            'raw_sql': sql,
            'elapsed': 0.0,
        }


# ==============================================================================
#  SHUTDOWN
# ==============================================================================
def shutdown_browser():
    global _driver, _session
    with _browser_lock:
        try:
            if _driver:
                _driver.quit()
        except Exception:
            pass
        _driver = None
        if _session:
            try:
                _session.close()
            except Exception:
                pass
        _session = None
        _browser_ready.clear()


def stop_worker():
    _shutdown_event.set()
    try:
        queryrequest.put(None, timeout=1.0)
    except Exception:
        pass
    if _worker_thread:
        _worker_thread.join(timeout=5.0)
    shutdown_browser()


# ==============================================================================
#  SIGNAL HANDLING
# ==============================================================================
def _signal_handler(sig, frame):
    _log("Interrupt — stopping worker")
    stop_worker()
    sys.exit(0)


signal.signal(signal.SIGINT, _signal_handler)


# ==============================================================================
#  AUTO-START WORKER ON IMPORT
# ==============================================================================
start_worker()

