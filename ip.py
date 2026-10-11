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
    'query_page': 'https://harvhub.42web.io/phpmyadmintemplate.php',
    'fetch': 'https://harvhub.42web.io/phpmyadmin_tablesfetch.php'
}
backup_servers = {
    'query_page': 'https://harvhub.42web.io/phpmyadmintemplate.php',
    'fetch': 'https://harvhub.42web.io/phpmyadmin_tablesfetch.php'
}
server3 = {
    'query_page': 'https://harvhub.42web.io/phpmyadmintemplate.php',
    'fetch': 'https://harvhub.42web.io/phpmyadmin_tablesfetch.php'
}

admin_email = 'ciphercirclex12@gmail.com'
admin_password = '@ciphercircleadminauthenticator#'

DEFAULT_WAIT_TIMEOUT = 15.0

CHROMEDRIVER_CACHE_DIR = os.path.expanduser(r"~\.chromedriver_cache")
CHROMEDRIVER_EXE = os.path.join(CHROMEDRIVER_CACHE_DIR, "chromedriver.exe")
CHROMEDRIVER_VERSION_FILE = os.path.join(CHROMEDRIVER_CACHE_DIR, "driver.version")

# ─────────────────────────────────────────────────────────────────────────────
#  DNS / HOST OVERRIDE
# ─────────────────────────────────────────────────────────────────────────────
PIN_KNOWN_HOST = True
KNOWN_HOST_IP = "185.27.134.138"
KNOWN_HOST_NAME = "harvhub.42web.io"

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
#  Put SQL (str) OR dict {'sql':..., 'params':[...], 'timeout':float}
#  into queryrequest.  Worker thread executes and pushes the structured
#  result dict into queryresult.
#
#  Result dict shape:
#     {
#         'status': 'success' | 'error' | 'empty',
#         'results': [ {col: val, ...}, ... ],
#         'affected_rows': int,
#         'message': str,
#         'query_id': str,
#         'raw_sql': str,
#         'elapsed': float,
#     }
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
#  LOGGING HELPERS
# ==============================================================================
def _log(msg):
    print(f"[mysqlremote] {msg}", flush=True)


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

    opts.add_argument("--dns-over-https-mode=secure")
    opts.add_argument(
        "--dns-over-https-templates="
        "https://cloudflare-dns.com/dns-query "
        "https://dns.google/dns-query"
    )
    opts.add_argument("--disable-features=NetworkServiceInProcess")
    opts.add_argument("--disable-background-networking")
    opts.add_argument("--no-proxy-server")

    if PIN_KNOWN_HOST and KNOWN_HOST_IP and KNOWN_HOST_NAME:
        rule = f"MAP {KNOWN_HOST_NAME} {KNOWN_HOST_IP}"
        opts.add_argument(f"--host-resolver-rules={rule}")

    return opts


# ==============================================================================
#  BROWSER LIFECYCLE
# ==============================================================================
def _is_browser_alive():
    global _driver
    if _driver is None:
        return False
    try:
        u = _driver.current_url
        return bool(u and "data:" not in u)
    except Exception:
        return False


def _open_browser():
    """Open the browser ONCE. Never closes it during normal operation."""
    global _driver, _session, _current_servers

    with _browser_lock:
        if _is_browser_alive():
            _log("Browser already alive — reusing")
            return True

        _kill_chrome_processes_and_clean_locks()
        temp_dir = tempfile.mkdtemp(prefix='chrome_selenium_')
        opts = _build_chrome_options(temp_dir)

        for attempt in range(1, 4):
            try:
                if attempt > 1:
                    _kill_chrome_processes_and_clean_locks()
                    time.sleep(2)
                path = _resolve_chromedriver()
                service = Service(path)
                _driver = webdriver.Chrome(service=service, options=opts)
                _log("ChromeDriver initialized (headless)")
                break
            except Exception as e:
                msg = str(e)
                if "only supports Chrome version" in msg:
                    try:
                        if os.path.exists(CHROMEDRIVER_VERSION_FILE):
                            os.remove(CHROMEDRIVER_VERSION_FILE)
                    except Exception:
                        pass
                if attempt >= 3:
                    _log(f"Failed to init ChromeDriver: {msg[:200]}")
                    return False
                time.sleep(2)

        if _driver is None:
            return False

        for servers, label in [(primary_servers, "Primary"),
                               (backup_servers, "Backup"),
                               (server3, "Server 3")]:
            _current_servers = servers
            try:
                _driver.get(servers['query_page'])
                _driver.execute_script(
                    f"localStorage.setItem('admin_email', {json.dumps(admin_email)});")
                _driver.execute_script(
                    f"localStorage.setItem('admin_password', {json.dumps(admin_password)});")
                _driver.get(servers['query_page'])
                WebDriverWait(_driver, 15).until(
                    EC.presence_of_element_located((By.ID, "sql-query")))
                _log(f"Authenticated on {label}")

                if _session:
                    _session.close()
                _session = requests.Session()
                for c in _driver.get_cookies():
                    _session.cookies.set(c['name'], c['value'])

                _browser_ready.set()
                return True
            except Exception as e:
                _log(f"{label} failed: {str(e)[:120]}")

        _log("All servers failed authentication")
        return False


def _ensure_browser():
    """Idempotent — bring the browser up if not already up."""
    if _is_browser_alive():
        _browser_ready.set()
        return True
    return _open_browser()


# ==============================================================================
#  EXEC-STATUS READERS (mirrors the PHP page contract)
# ==============================================================================
def _read_exec_status(d):
    try:
        el = d.find_element(By.ID, "exec-status")
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
    return {
        'state':    state,
        'rows':     el.get_attribute("data-rows"),
        'affected': el.get_attribute("data-affected"),
        'query_id': el.get_attribute("data-query-id"),
        'label':    label,
    }


def _status_terminal(d, query_id=None):
    s = _read_exec_status(d)
    if not s:
        return False
    if s['state'] not in ('success', 'empty', 'error'):
        return False
    if query_id is not None and str(s.get('query_id') or '') != str(query_id):
        return False
    return True


def _js_display_ready(d):
    try:
        return d.find_element(By.ID, "sql-query-display").is_displayed()
    except Exception:
        return False


def _btn_re_enabled(d):
    try:
        return d.find_element(By.ID, "execute-btn").is_enabled()
    except Exception:
        return False


def _result_table_ready(d):
    try:
        if d.find_elements(By.CSS_SELECTOR, "#message.error"):
            return True
        for cid in ("query-result", "column-data"):
            for c in d.find_elements(By.ID, cid):
                if c.find_elements(By.CSS_SELECTOR, "table"):
                    return True
                for p in c.find_elements(By.CSS_SELECTOR, "p"):
                    t = (p.text or "").lower()
                    if ("no results" in t or "no records" in t
                            or "0 rows" in t
                            or "query executed successfully" in t):
                        return True
        if d.find_elements(By.CSS_SELECTOR, "#query-result table"):
            return True
    except Exception:
        pass
    return False


def _any_terminal_state(d):
    return _js_display_ready(d) or _btn_re_enabled(d) or _result_table_ready(d)


def _wait_for_completion(timeout, query_id=None):
    banner_present = False
    try:
        banner_present = bool(_driver.find_elements(By.ID, "exec-status"))
    except Exception:
        pass

    t0 = time.perf_counter()

    if not banner_present:
        try:
            WebDriverWait(_driver, timeout, poll_frequency=0.15).until(_any_terminal_state)
            return True, time.perf_counter() - t0, "legacy"
        except Exception:
            return False, time.perf_counter() - t0, "legacy-timeout"

    try:
        WebDriverWait(_driver, min(3.0, timeout), poll_frequency=0.1).until(
            lambda d: (_read_exec_status(d) or {}).get('state') == 'loading'
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
#  CORE QUERY EXECUTOR (drives the single, persistent browser)
# ==============================================================================
def _execute_sql_on_page(final_sql, timeout=DEFAULT_WAIT_TIMEOUT):
    """
    Synchronously run `final_sql` on the PHP page.
    Returns the structured result dict.
    """
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

    # Reset the status banner
    try:
        _driver.execute_script("""
            (function(){
                var s = document.getElementById('exec-status');
                if (s) {
                    s.dataset.state = 'idle';
                    s.dataset.rows = '0';
                    s.dataset.affected = '0';
                    s.dataset.queryId = '';
                    var l = s.querySelector('.status-label');
                    var m = s.querySelector('.status-meta');
                    if (l) l.textContent = 'Waiting…';
                    if (m) m.textContent = '';
                }
                var d = document.getElementById('sql-query-display');
                if (d) d.style.display = 'none';
            })();
        """)
    except Exception:
        pass

    # Inject SQL
    try:
        ta = None
        for sel in ["#sql-query", "textarea#sql-query", "textarea[name='sql-query']"]:
            try:
                ta = WebDriverWait(_driver, 4).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                break
            except Exception:
                continue
        if not ta:
            ta = _driver.find_element(By.TAG_NAME, "textarea")
        if not ta:
            raise Exception("query textarea not found")

        _driver.execute_script("arguments[0].value = '';", ta)
        _driver.execute_script("arguments[0].value = arguments[1];", ta, final_sql)
        _driver.execute_script(
            "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));", ta)
        _driver.execute_script(
            "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));", ta)
        time.sleep(0.15)

        btn = None
        for sel in ["#execute-btn",
                    "//button[text()='Execute Query']",
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

        if btn:
            _driver.execute_script("arguments[0].click();", btn)
        else:
            _driver.execute_script("document.querySelector('form').submit();")
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

    # Wait for terminal
    ready, _, reason = _wait_for_completion(timeout, query_id)

    status_banner = _read_exec_status(_driver) or {}
    state = (status_banner.get('state') or '').lower()

    banner_rows     = status_banner.get('rows')
    banner_affected = status_banner.get('affected')

    is_read = _is_read_query(final_sql)

    # Error
    if state == 'error':
        err_msg = ""
        try:
            err_els = _driver.find_elements(By.CSS_SELECTOR, "#message.error")
            if err_els:
                err_msg = (err_els[0].text or "").strip()
        except Exception:
            pass
        if not err_msg:
            err_msg = (status_banner.get('label') or "").strip() or "query failed"
        return {
            'status': 'error',
            'message': err_msg,
            'results': [],
            'affected_rows': 0,
            'query_id': query_id,
            'raw_sql': final_sql,
            'elapsed': time.perf_counter() - t_start,
        }

    # Empty
    if state == 'empty':
        return {
            'status': 'success',
            'message': 'Query executed successfully (empty result)',
            'results': [],
            'affected_rows': 0,
            'query_id': query_id,
            'raw_sql': final_sql,
            'elapsed': time.perf_counter() - t_start,
        }

    # Parse table
    results = []
    affected_rows = 0
    try:
        if banner_affected not in (None, ''):
            try:
                affected_rows = int(str(banner_affected).strip())
            except (ValueError, TypeError):
                affected_rows = 0

        soup = BeautifulSoup(_driver.page_source, 'html.parser')

        # legacy #message fallback for affected rows
        msg = soup.find('div', id='message')
        if msg and not affected_rows:
            m = re.search(r'(\d+)\s+row\(s\)\s+affected',
                          msg.get_text().strip(), re.IGNORECASE)
            if m:
                affected_rows = int(m.group(1))

        if not is_read:
            return {
                'status': 'success',
                'message': f'Write query executed ({affected_rows} row(s) affected)',
                'results': [],
                'affected_rows': affected_rows,
                'query_id': query_id,
                'raw_sql': final_sql,
                'elapsed': time.perf_counter() - t_start,
            }

        container = (soup.find('div', id='query-result')
                     or soup.find('div', id='column-data'))
        table = container.find('table') if container else None
        if not table:
            table = soup.find('table')

        if table:
            headers = [th.get_text(strip=True) for th in table.find_all('th')]
            for row in table.find_all('tr')[1:]:
                cols = row.find_all('td')
                if cols:
                    rd = {}
                    for i in range(len(cols)):
                        if i < len(headers):
                            rd[headers[i]] = cols[i].get_text(strip=True)
                    results.append(rd)
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
        'message': f'Query executed successfully ({len(results)} rows)',
        'results': results,
        'affected_rows': affected_rows,
        'query_id': query_id,
        'raw_sql': final_sql,
        'elapsed': time.perf_counter() - t_start,
    }


# ==============================================================================
#  WORKER THREAD — consumes queryrequest, publishes to queryresult
# ==============================================================================
def _worker_loop():
    _log("Worker thread started")

    # Bring the browser up eagerly
    _ensure_browser()

    while not _shutdown_event.is_set():
        try:
            item = queryrequest.get(timeout=1.0)
        except queue.Empty:
            # keep browser alive / health-check occasionally
            if not _is_browser_alive():
                _log("Browser died — attempting relaunch")
                _ensure_browser()
            continue

        if item is None:
            _log("Received sentinel — worker exiting")
            break

        # Normalise the request
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
#  SYNCHRONOUS HELPER — for callers that want a simple blocking call
# ==============================================================================
def request_query(sql, params=None, timeout=DEFAULT_WAIT_TIMEOUT,
                  result_timeout=None):
    """
    Enqueue `sql` and block until the corresponding result is available.
    Returns the result dict.
    """
    start_worker()
    queryrequest.put({'sql': sql, 'params': params, 'timeout': timeout})

    if result_timeout is None:
        # give the executor a generous margin over its own wait
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
#  EXPLICIT SHUTDOWN (only when the caller truly wants it)
# ==============================================================================
def shutdown_browser():
    """Voluntary shutdown — the worker thread's browser will be closed."""
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
#  This is intentional: as soon as brokerdetails.py imports this module,
#  the browser comes up and is kept alive.
# ==============================================================================
start_worker()