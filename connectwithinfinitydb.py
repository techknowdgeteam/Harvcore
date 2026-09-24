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
from bs4 import BeautifulSoup
import re
import json
from datetime import datetime
import psutil
import shutil
import traceback
import threading
import subprocess
import tempfile
import glob
import uuid as _uuid_module

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
temp_download_dir = r'C:\xampp\htdocs\CIPHER\temp_downloads'
json_log_path = r'C:\xampp\htdocs\CIPHER\cipher trader\market\dbserver\connectwithdb.json'

driver = None
session = None
current_servers = primary_servers
_browser_lock = threading.Lock()
_is_shutdown = False

DEFAULT_WAIT_TIMEOUT = 10.0

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


def print_header(t, w=70):
    print(f"\n{'='*w}\n  {t}\n{'='*w}")

def print_step(n, total, d):
    print(f"\n   [{n}/{total}] {d}")

def print_success(m): print(f"   ✅ {m}")
def print_error(m, d=None):
    print(f"   ❌ {m}")
    if d: print(f"     └─ Details: {d}")
def print_warning(m): print(f"   ⚠️  {m}")
def print_info(m): print(f"   ℹ️  {m}")
def print_divider(c="─", w=70): print(f"  {c*w}")


# ==============================================================================
#  CHROME VERSION
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
    except Exception as e:
        print_warning(f"Could not detect Chrome version: {e}")
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
    r = requests.get(url, headers=_HEADERS, timeout=timeout, verify=False, stream=True)
    r.raise_for_status()
    buf = io.BytesIO()
    for chunk in r.iter_content(chunk_size=64 * 1024):
        if chunk:
            buf.write(chunk)
    return buf.getvalue()


# ==============================================================================
#  VERSION PICKING
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


# ==============================================================================
#  ZIP EXTRACTION
# ==============================================================================
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


# ==============================================================================
#  MIRROR-BASED DOWNLOAD
# ==============================================================================
def _fetch_catalog():
    for url in CFT_JSON_URLS:
        try:
            print_info(f"  Trying catalog: {url}")
            data = _http_get_json(url)
            versions = data.get("versions")
            if versions:
                print_success(f"  ✅ Catalog from: {url}  ({len(versions)} versions)")
                return versions
        except Exception as e:
            print_warning(f"  ❌ Failed: {str(e)[:140]}")
    return None


def _try_download_zip_for_version(version):
    for url in _cft_zip_candidates(version):
        try:
            print_info(f"  Trying ZIP: {url}")
            blob = _http_get_bytes(url)
            print_success(f"  ✅ Downloaded {len(blob):,} bytes")
            return blob
        except Exception as e:
            print_warning(f"  ❌ Failed: {str(e)[:140]}")
    return None


def _download_via_mirrors(target_version):
    catalog = _fetch_catalog()
    if not catalog:
        print_warning("No catalog mirror reachable")
        return None

    versions = [v.get("version") for v in catalog if v.get("version")]
    picked = _pick_best_cft_version(versions, target_version)
    if not picked:
        print_warning("Could not pick a version")
        return None
    print_info(f"Picked version: {picked}")

    blob = _try_download_zip_for_version(picked)
    if not blob:
        print_warning(f"No mirror served the ZIP for {picked}")
        return None

    try:
        return _extract_chromedriver_from_zip(blob)
    except Exception as e:
        print_warning(f"ZIP extract failed: {e}")
        return None


def _download_via_pip_binary(target_version):
    if not target_version:
        print_warning("No target version — cannot use pip fallback")
        return None

    major = target_version.split('.')[0]
    candidates = [target_version, f"{major}.0.0.0"]

    for pkg_version in candidates:
        try:
            print_info(f"Trying pip install chromedriver-binary=={pkg_version} ...")
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet",
                 "--disable-pip-version-check",
                 f"chromedriver-binary=={pkg_version}"],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode != 0:
                print_warning(f"  pip failed: {(r.stderr or '')[:160]}")
                continue

            import importlib.util
            spec = importlib.util.find_spec("chromedriver_binary")
            if spec and spec.submodule_search_locations:
                for base in spec.submodule_search_locations:
                    found = glob.glob(os.path.join(base, "chromedriver*.exe"))
                    if found:
                        os.makedirs(CHROMEDRIVER_CACHE_DIR, exist_ok=True)
                        shutil.copy2(found[0], CHROMEDRIVER_EXE)
                        print_success(f"Installed via pip: {CHROMEDRIVER_EXE}")
                        return CHROMEDRIVER_EXE
        except Exception as e:
            print_warning(f"  pip attempt failed: {str(e)[:160]}")

    return None


# ==============================================================================
#  DRIVER CACHE
# ==============================================================================
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
        print_info(f"Recorded driver version: {version}")
    except Exception as e:
        print_warning(f"Could not record version: {e}")


def _resolve_chromedriver():
    chrome_version = _get_installed_chrome_version()
    chrome_major = chrome_version.split('.')[0] if chrome_version else None
    if chrome_version:
        print_info(f"Detected Chrome: {chrome_version}")

    cached = _read_cached_driver_version()
    if cached:
        print_info(f"Cached driver: {cached}")

    if chrome_major and cached and cached.split('.')[0] == chrome_major:
        print_success("Cached driver matches Chrome — using it")
        return CHROMEDRIVER_EXE

    print_info("Attempting mirror-based ChromeDriver download...")
    try:
        path = _download_via_mirrors(chrome_version)
        if path:
            _record_driver_version(path, chrome_version)
            return path
    except Exception as e:
        print_warning(f"Mirror download error: {str(e)[:200]}")

    print_info("Attempting pip-based ChromeDriver install...")
    try:
        path = _download_via_pip_binary(chrome_version)
        if path:
            _record_driver_version(path, chrome_version)
            return path
    except Exception as e:
        print_warning(f"pip fallback error: {str(e)[:200]}")

    try:
        print_info("Trying webdriver-manager as last network fallback...")
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
        print_warning(f"webdriver-manager failed: {str(e)[:160]}")

    if os.path.exists(CHROMEDRIVER_EXE):
        print_warning("Using STALE cached ChromeDriver")
        return CHROMEDRIVER_EXE

    raise RuntimeError("ChromeDriver resolution failed — all sources exhausted")


# ==============================================================================
#  BROWSER / PROCESS MANAGEMENT
# ==============================================================================
def is_browser_alive():
    global driver
    if driver is None:
        return False
    try:
        u = driver.current_url
        return bool(u and "data:" not in u)
    except Exception:
        return False


def kill_chrome_processes_and_clean_locks():
    print_info("Cleaning Chrome processes and locks...")
    killed = 0
    try:
        r = subprocess.run(["taskkill", "/f", "/im", "chrome.exe", "/t"],
                           capture_output=True, text=True)
        if "SUCCESS" in r.stdout or r.returncode == 0:
            killed += 1; print_success("Killed Chrome")
        r = subprocess.run(["taskkill", "/f", "/im", "chromedriver.exe", "/t"],
                           capture_output=True, text=True)
        if "SUCCESS" in r.stdout or r.returncode == 0:
            killed += 1; print_success("Killed ChromeDriver")
        if killed:
            time.sleep(2)
    except Exception as e:
        print_warning(f"Error killing: {e}")

    wdm = os.path.expanduser(r"~\.wdm")
    if os.path.exists(wdm):
        try:
            shutil.rmtree(wdm, ignore_errors=True)
            killed += 1; print_success("Removed .wdm")
        except Exception as e:
            print_warning(f"Could not remove .wdm: {e}")
    return killed > 0


def _build_chrome_options(temp_dir):
    opts = Options()

    if os.path.exists(CHROME_PATH):
        opts.binary_location = CHROME_PATH
        print_info(f"Using manual Chrome path: {CHROME_PATH}")

    # ── Core headless hygiene ────────────────────────────────────────────
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

    # ── DNS / network overrides ──────────────────────────────────────────
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
        print_info(f"Pinned DNS: {KNOWN_HOST_NAME} → {KNOWN_HOST_IP}")

    print_info("🔧 Headless mode enabled (DoH + no-proxy + host-pin)")
    return opts


def initialize_browser(force_new=False):
    global driver, session, current_servers, _is_shutdown

    with _browser_lock:
        if _is_shutdown and not force_new:
            print_warning("Browser was shut down. Use force_new=True")
            return False

        if not force_new and is_browser_alive():
            print_info("Reusing existing browser session...")
            try:
                driver.get(current_servers['query_page'])
                if session:
                    session.close()
                session = requests.Session()
                for c in driver.get_cookies():
                    session.cookies.set(c['name'], c['value'])
                print_success("Existing browser reused")
                return True
            except Exception as e:
                print_warning(f"Existing session invalid: {str(e)[:100]}")
                try: driver.quit()
                except Exception: pass
                driver = None
                session = None

        print_info("Cleaning up Chrome processes...")
        kill_chrome_processes_and_clean_locks()

        print_header("BROWSER INITIALIZATION (HEADLESS MODE)")

        print_step(1, 3, "Setting Up Chrome Environment (Headless)")
        temp_dir = tempfile.mkdtemp(prefix='chrome_selenium_')
        opts = _build_chrome_options(temp_dir)

        print_step(2, 3, "Initializing ChromeDriver")

        for attempt in range(1, 4):
            try:
                if attempt > 1:
                    print_info(f"Retry attempt {attempt}/3...")
                    kill_chrome_processes_and_clean_locks()
                    time.sleep(2)

                path = _resolve_chromedriver()
                service = Service(path)
                driver = webdriver.Chrome(service=service, options=opts)
                print_success("ChromeDriver initialized in HEADLESS mode")
                break

            except Exception as e:
                msg = str(e)
                if "only supports Chrome version" in msg:
                    print_warning("Version mismatch detected")
                    try:
                        if os.path.exists(CHROMEDRIVER_VERSION_FILE):
                            os.remove(CHROMEDRIVER_VERSION_FILE)
                    except Exception:
                        pass
                if attempt < 3:
                    print_warning(f"Attempt {attempt} failed: {msg[:180]}")
                    time.sleep(3)
                else:
                    print_error("Failed to initialize ChromeDriver", msg)
                    return False

        if not driver:
            return False

        print_step(3, 3, "Authenticating and Accessing Query Page")

        for servers, label in [(primary_servers, "Primary"),
                               (backup_servers, "Backup"),
                               (server3, "Server 3")]:
            current_servers = servers
            print_info(f"Trying {label} server: {servers['query_page']}")
            try:
                driver.get(servers['query_page'])
                driver.execute_script(f"localStorage.setItem('admin_email', '{admin_email}');")
                driver.execute_script(f"localStorage.setItem('admin_password', '{admin_password}');")
                driver.get(servers['query_page'])
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.ID, "sql-query")))
                print_success(f"Authenticated on {label} server")

                if session:
                    session.close()
                session = requests.Session()
                for c in driver.get_cookies():
                    session.cookies.set(c['name'], c['value'])
                append_to_json_log(label, servers['query_page'])
                _is_shutdown = False
                return True
            except Exception as e:
                print_warning(f"{label} failed: {str(e)[:100]}")

        print_error("All servers failed authentication")
        return False


def append_to_json_log(server_type, server_url):
    entry = {'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
             'server_type': server_type, 'server_url': server_url, 'status': 'success'}
    data = []
    try:
        if os.path.exists(json_log_path):
            with open(json_log_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not isinstance(data, list):
                    data = []
    except Exception:
        data = []
    if data and data[-1].get('server_url') == server_url:
        return
    data.append(entry)
    try:
        os.makedirs(os.path.dirname(json_log_path), exist_ok=True)
        with open(json_log_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print_warning(f"Failed to write JSON log: {str(e)[:100]}")


def signal_handler(sig, frame):
    print_warning("\nScript interrupted. Cleaning up...")
    cleanup()
    sys.exit(0)


def cleanup():
    global driver, session, _is_shutdown
    if _is_shutdown:
        print_info("Browser already shut down")
        return
    print_header("CLEANUP")
    if driver:
        try:
            if "data:" not in driver.current_url:
                driver.execute_script("localStorage.clear();")
                print_success("LocalStorage cleared")
        except Exception as e:
            print_warning(f"Failed to clear localStorage: {e}")
        try: driver.quit()
        except Exception: pass
        driver = None
        print_success("Browser closed")
    if session:
        try: session.close()
        except Exception: pass
        session = None
        print_success("HTTP session closed")
    if os.path.exists(temp_download_dir):
        try:
            for f in os.listdir(temp_download_dir):
                p = os.path.join(temp_download_dir, f)
                if os.path.isfile(p):
                    os.remove(p)
            os.rmdir(temp_download_dir)
            print_success("Temp directory removed")
        except Exception as e:
            print_warning(f"Failed to clean temp: {e}")
    _is_shutdown = True


def shutdown():
    global _is_shutdown
    print_info("Explicit shutdown requested...")
    cleanup()


def check_server_availability(url):
    try:
        r = requests.head(url, headers=_HEADERS, timeout=10, verify=False)
        return r.status_code == 200
    except Exception:
        return False


# ==============================================================================
#  EXEC STATUS BANNER READERS
#  The page exposes #exec-status[data-state=idle|loading|success|empty|error]
#  and data-rows / data-affected / data-query-id attributes.
# ==============================================================================
def _read_exec_status(d):
    """
    Read the machine-readable execution banner.
    Returns dict {state, rows, affected, query_id, label} or None if the banner
    is not present (i.e. running against the legacy page version).
    """
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
    """
    True when the banner is in a terminal state (success|empty|error).
    If query_id is provided, also require the banner's query-id to match,
    so we don't read the result of a *previous* run.
    """
    s = _read_exec_status(d)
    if not s:
        return False
    if s['state'] not in ('success', 'empty', 'error'):
        return False
    if query_id is not None and str(s.get('query_id') or '') != str(query_id):
        return False
    return True


# ==============================================================================
#  LEGACY COMPLETION DETECTION (fallback when banner is absent)
# ==============================================================================
def _js_display_ready(d):
    try: return d.find_element(By.ID, "sql-query-display").is_displayed()
    except Exception: return False


def _btn_re_enabled(d):
    try: return d.find_element(By.ID, "execute-btn").is_enabled()
    except Exception: return False


def _result_table_ready(d):
    try:
        if d.find_elements(By.CSS_SELECTOR, "#message.error"):
            return True

        for container_id in ("query-result", "column-data"):
            try:
                containers = d.find_elements(By.ID, container_id)
                for c in containers:
                    if c.find_elements(By.CSS_SELECTOR, "table"):
                        return True
                    for p in c.find_elements(By.CSS_SELECTOR, "p"):
                        txt = (p.text or "").lower()
                        if ("no results" in txt
                                or "no records" in txt
                                or "0 rows" in txt
                                or "query executed successfully" in txt):
                            return True
            except Exception:
                continue

        if d.find_elements(By.CSS_SELECTOR, "#query-result table"):
            return True
    except Exception:
        pass
    return False


def _any_terminal_state(d):
    if _js_display_ready(d) or _btn_re_enabled(d):
        return True
    if _result_table_ready(d):
        return True
    return False


def _wait_for_completion(wait_hint, sql_query, query_id=None):
    """
    Wait until the execution banner leaves 'loading'.

    Primary path:  #exec-status[data-state] transitions loading → terminal.
    Fallback path: legacy detection (js-display / button-enabled / table)
                   if the banner is not present on the page at all.

    Returns: (ready: bool, elapsed: float, reason: str)
    """
    if wait_hint is None:
        wait_hint = {}
    timeout = float(wait_hint.get('timeout', DEFAULT_WAIT_TIMEOUT))
    t0 = time.perf_counter()

    banner_present = False
    try:
        banner_present = bool(driver.find_elements(By.ID, "exec-status"))
    except Exception:
        banner_present = False

    if not banner_present:
        sig = wait_hint.get('signal', 'any-of')
        det = {
            'js-display':     _js_display_ready,
            'button-enabled': _btn_re_enabled,
            'table':          _result_table_ready,
        }.get(sig, _any_terminal_state)
        try:
            WebDriverWait(driver, timeout, poll_frequency=0.15).until(det)
            return True, time.perf_counter() - t0, f"legacy signal '{sig}'"
        except Exception:
            return False, time.perf_counter() - t0, f"legacy timeout after {timeout:.1f}s"

    try:
        WebDriverWait(driver, min(3.0, timeout), poll_frequency=0.1).until(
            lambda d: (_read_exec_status(d) or {}).get('state') == 'loading'
        )
    except Exception:
        pass

    try:
        WebDriverWait(driver, timeout, poll_frequency=0.1).until(
            lambda d: _status_terminal(d, query_id)
        )
        s = _read_exec_status(driver) or {}
        return (True, time.perf_counter() - t0,
                f"exec-status={s.get('state')} rows={s.get('rows')}")
    except Exception:
        s = _read_exec_status(driver) or {}
        return (False, time.perf_counter() - t0,
                f"timeout after {timeout:.1f}s (last state={s.get('state')!r})")


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
            s = s[nl+1:] if nl != -1 else ''
        elif s.startswith('/*'):
            end = s.find('*/')
            s = s[end+2:] if end != -1 else ''
        if s == prev:
            break
    if not s:
        return False
    upper = s.upper()
    return any(upper.startswith(kw) for kw in _READ_KEYWORDS)


# ==============================================================================
#  MAIN QUERY EXECUTOR
# ==============================================================================
def execute_query(sql_query, params=None, reuse_browser=True, wait_hint=None):
    global driver, session

    if params:
        if not isinstance(params, (tuple, list)):
            params = (params,)
        final_sql = sql_query
        for p in params:
            if '%s' not in final_sql: break
            if p is None: final_sql = final_sql.replace('%s', 'NULL', 1)
            elif isinstance(p, bool): final_sql = final_sql.replace('%s', '1' if p else '0', 1)
            elif isinstance(p, (int, float)): final_sql = final_sql.replace('%s', str(p), 1)
            elif isinstance(p, (dict, list)):
                js = json.dumps(p, ensure_ascii=False)
                esc = js.replace("'", "''").replace("\\", "\\\\")
                final_sql = final_sql.replace('%s', f"'{esc}'", 1)
            else:
                esc = str(p).replace("'", "''").replace("\\", "\\\\")
                final_sql = final_sql.replace('%s', f"'{esc}'", 1)
    else:
        final_sql = sql_query

    print_divider()

    try:
        for attempt in range(3):
            if attempt > 0:
                print_info(f"Retry {attempt + 1}/3 for browser init...")
                time.sleep(3)
                kill_chrome_processes_and_clean_locks()
            if initialize_browser(force_new=False):
                break
            elif attempt == 2:
                return {'status': 'error',
                        'message': 'Browser initialization failed',
                        'results': [], 'affected_rows': 0}

        # ── Reset banner to idle so we can detect the next transition ────
        try:
            driver.execute_script("""
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

        query_id = str(_uuid_module.uuid4().int)[:12]
        try:
            driver.execute_script(
                "window.__harvhub_query_id = arguments[0];", query_id)
        except Exception:
            pass

        print_step(4, 6, "Injecting SQL Query")
        try:
            ta = None
            for sel in ["#sql-query", "textarea#sql-query", "textarea[name='sql-query']"]:
                try:
                    ta = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                    break
                except Exception:
                    continue
            if not ta:
                try: ta = driver.find_element(By.TAG_NAME, "textarea")
                except Exception: pass
            if not ta:
                raise Exception("Could not find query textarea")

            driver.execute_script("arguments[0].value = '';", ta)
            driver.execute_script("arguments[0].value = arguments[1];", ta, final_sql)
            driver.execute_script("arguments[0].dispatchEvent(new Event('input', {bubbles:true}));", ta)
            driver.execute_script("arguments[0].dispatchEvent(new Event('change', {bubbles:true}));", ta)
            time.sleep(0.3)

            btn = None
            for sel in ["#execute-btn",
                        "//button[text()='Execute Query']",
                        "//button[contains(text(), 'Execute')]",
                        "//button[@type='submit']"]:
                try:
                    btn = driver.find_element(By.XPATH, sel) if sel.startswith("//") \
                          else driver.find_element(By.CSS_SELECTOR, sel)
                    if btn: break
                except Exception:
                    continue

            if btn:
                driver.execute_script("arguments[0].click();", btn)
                print_success("Query injected and executed")
            else:
                print_warning("Execute button not found, submitting form...")
                try:
                    driver.execute_script("document.querySelector('form').submit();")
                    print_success("Form submitted")
                except Exception:
                    raise Exception("Could not find execute button or form")

        except Exception as e:
            print_error("Failed to inject query", str(e))
            return {'status': 'error',
                    'message': f"Query input failed: {str(e)}",
                    'results': [], 'affected_rows': 0}

        print_step(5, 6, "Waiting for Server Response")

        results = []
        affected_rows = 0
        is_read = _is_read_query(final_sql)

        hint = {
            'timeout': (wait_hint or {}).get('timeout', DEFAULT_WAIT_TIMEOUT),
            'signal':  (wait_hint or {}).get('signal', 'table' if is_read else 'button-enabled'),
        }

        ready, el, reason = _wait_for_completion(hint, final_sql, query_id)
        if ready:
            print_success(f"Server response ready ({reason}, {el:.2f}s)")
        else:
            print_warning(f"Status banner did not reach terminal state ({reason})")

        # ── Read the authoritative status ─────────────────────────────────
        status = _read_exec_status(driver) or {}
        state = (status.get('state') or '').lower()
        banner_rows = status.get('rows')
        banner_affected = status.get('affected')

        print_info(f"  📟 exec-status: state={state!r} "
                   f"rows={banner_rows!r} affected={banner_affected!r}")

        # ── Hard error from page ──────────────────────────────────────────
        if state == 'error':
            err_msg = ""
            try:
                err_els = driver.find_elements(By.CSS_SELECTOR, "#message.error")
                if err_els:
                    err_msg = (err_els[0].text or "").strip()
            except Exception:
                pass
            if not err_msg:
                err_msg = (status.get('label') or "").strip() or "query failed"
            print_error(f"Query error: {err_msg}")
            return {'status': 'error', 'message': err_msg,
                    'results': [], 'affected_rows': 0}

        # ── Empty result (query ran fine, zero rows) ──────────────────────
        if state == 'empty':
            print_info("Query returned 0 rows (per exec-status banner)")
            print_divider()
            print_success("Query execution complete - 0 results")
            print_divider("═")
            return {'status': 'success', 'results': [],
                    'affected_rows': 0,
                    'message': 'Query executed successfully (empty result)'}

        # ── Success: parse the result table ───────────────────────────────
        print_step(6, 6, "Parsing Query Results")
        try:
            # Parse affected_rows from banner first (authoritative for writes)
            try:
                if banner_affected is not None and str(banner_affected).strip() != '':
                    affected_rows = int(str(banner_affected).strip())
            except (ValueError, TypeError):
                affected_rows = 0

            # For write queries, the banner is the source of truth.
            # There will be NO result <table> in the DOM.
            if not is_read:
                # Also try to scrape the legacy #message banner text as a
                # secondary source, but do NOT fail if it's absent.
                try:
                    soup = BeautifulSoup(driver.page_source, 'html.parser')
                    msg = soup.find('div', id='message')
                    if msg:
                        m = re.search(r'(\d+)\s+row\(s\)\s+affected',
                                      msg.get_text().strip(), re.IGNORECASE)
                        if m:
                            affected_rows = int(m.group(1))
                except Exception:
                    pass

                # If we never got a count from the banner or the message div,
                # we still consider this a success — the page said so.
                if affected_rows:
                    print_success(f"Query affected {affected_rows} row(s)")
                else:
                    print_info("Write query completed (no affected-row count available)")

                print_divider()
                print_success("Query execution complete - 0 results")
                print_divider("═")
                return {'status': 'success', 'results': [],
                        'affected_rows': affected_rows,
                        'message': f'Write query executed successfully '
                                   f'({affected_rows} row(s) affected)'}

            # ── Read query: parse the result table ────────────────────────
            soup = BeautifulSoup(driver.page_source, 'html.parser')

            msg = soup.find('div', id='message')
            if msg and not affected_rows:
                m = re.search(r'(\d+)\s+row\(s\)\s+affected',
                              msg.get_text().strip(), re.IGNORECASE)
                if m:
                    affected_rows = int(m.group(1))

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
                print_success(f"Parsed {len(results)} rows with {len(headers)} cols")
            else:
                # Read query with no table — treat as a successful empty result.
                print_warning("No result table found for read query "
                              "(treating as empty result)")
                results = []

        except Exception as e:
            print_error("Failed to parse results", str(e))
            return {'status': 'error', 'message': f"Parse error: {str(e)}",
                    'results': [], 'affected_rows': 0}

        print_divider()
        print_success(f"Query execution complete - {len(results)} results")
        print_divider("═")
        return {'status': 'success', 'results': results,
                'affected_rows': affected_rows,
                'message': 'Query executed successfully'}

    except Exception as e:
        print_error("Critical error", str(e))
        traceback.print_exc()
        return {'status': 'error', 'message': str(e),
                'results': [], 'affected_rows': 0}


signal.signal(signal.SIGINT, signal_handler)