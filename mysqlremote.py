# mysqlremote.py
#
# Long-running Chrome/Selenium bridge with MULTI-WINDOW CHANNEL MULTIPLEXING.
#
#   * Launches Chrome ONCE at startup (headless).
#   * Listens on 127.0.0.1:5599 for length-prefixed JSON requests.
#   * Mints dynamic channel IDs (queryrequest_{n} / queryresult_{n}).
#   * Creates one DOM window per channel inside phpmyadmintemplate.php.
#   * Each channel gets its own per-channel lock -> no cross-script overwrite.
#
# Protocol (all length-prefixed JSON):
#   {"op":"acquire_channel","owner":"brokerdetails"}   -> {"channel_id":N,"window_id":N}
#   {"op":"release_channel","channel_id":N}            -> {"ok":true}
#   {"op":"channel_status","channel_id":N}             -> {"in_use":bool,"owner":str}
#   {"op":"list_channels"}                             -> {"channels":[{...}]}
#   {"op":"sql","channel_id":N,"sql":"...","params":[...],"timeout":20.0}
#                                                      -> standard result dict
#   {"sql":"..."}   (legacy)                           -> auto-temp-channel
#
# Nothing is written to disk. Everything is live over the socket.

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, TimeoutException

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
import socket
import struct
import subprocess
import tempfile
import glob
import shutil
import threading
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
backup_servers = dict(primary_servers)
server3 = {
    'query_page': 'https://harvhub.free.nf/phpmyadmintemplate.php',
    'fetch': 'https://harvhub.free.nf/phpmyadmin_tablesfetch.php'
}

DEFAULT_WAIT_TIMEOUT = 20.0

CHROMEDRIVER_CACHE_DIR = os.path.expanduser(r"~\.chromedriver_cache")
CHROMEDRIVER_EXE = os.path.join(CHROMEDRIVER_CACHE_DIR, "chromedriver.exe")
CHROMEDRIVER_VERSION_FILE = os.path.join(CHROMEDRIVER_CACHE_DIR, "driver.version")

BIND_HOST = "127.0.0.1"
BIND_PORT = 5599

_HEADER = struct.Struct(">I")
MAX_FRAME = 64 * 1024 * 1024

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

# Auto-close windows after this many seconds idle (0 = never auto-close).
CHANNEL_IDLE_CLOSE_SECONDS = 0

# Max concurrent channels (windows) to keep resource use bounded.
MAX_CHANNELS = 32


def _cft_zip_candidates(version):
    return [
        f"https://storage.googleapis.com/chrome-for-testing-public/{version}/win64/chromedriver-win64.zip",
        f"https://cdn.npmmirror.com/binaries/chrome-for-testing/{version}/win64/chromedriver-win64.zip",
        f"https://registry.npmmirror.com/-/binary/chrome-for-testing/{version}/win64/chromedriver-win64.zip",
        f"https://chromedriver.storage.googleapis.com/{version}/chromedriver_win32.zip",
        f"https://cdn.npmmirror.com/binaries/chromedriver/{version}/chromedriver_win32.zip",
    ]


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
                _log(f"  OK Catalog from: {url} ({len(versions)} versions)")
                return versions
        except Exception as e:
            _log(f"  FAILED: {str(e)[:140]}")
    return None


def _try_download_zip_for_version(version):
    for url in _cft_zip_candidates(version):
        try:
            _log(f"  Trying ZIP: {url}")
            blob = _http_get_bytes(url)
            _log(f"  OK Downloaded {len(blob):,} bytes")
            return blob
        except Exception as e:
            _log(f"  FAILED: {str(e)[:140]}")
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
        _log(f"Pinned DNS: {KNOWN_HOST_NAME} -> {KNOWN_HOST_IP}")

    return opts


# ==============================================================================
#  BROWSER STATE
# ==============================================================================
_browser_lock = threading.Lock()          # protects _driver lifecycle
_driver = None
_session = None
_current_servers = primary_servers


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
                    _log(f"[{label}] wait failed | url={cur_url} | title={cur_title!r} | err={wait_err}")
                    raise

                _log(f"[{label}] ready")

                if _session:
                    try:
                        _session.close()
                    except Exception:
                        pass
                _session = requests.Session()
                for c in _driver.get_cookies():
                    _session.cookies.set(c['name'], c['value'])
                return True

            except Exception as e:
                last_error = f"{label}: {type(e).__name__}: {e}"
                _log(f"[{label}] FAILED {str(e)[:200]}")

        _log(f"All servers failed. Last error: {last_error}")
        try:
            _driver.quit()
        except Exception:
            pass
        _driver = None
        return False


def _ensure_browser():
    if _is_browser_alive():
        return True
    return _open_browser()


# ==============================================================================
#  CHANNEL REGISTRY  (queryrequest_{id} / queryresult_{id})
# ==============================================================================
class _Channel:
    __slots__ = ('channel_id', 'owner', 'created_at', 'last_used_at',
                 'lock', 'window_handle', 'window_ready')

    def __init__(self, channel_id, owner):
        self.channel_id = channel_id
        self.owner = owner
        self.created_at = time.time()
        self.last_used_at = time.time()
        # Per-channel lock: SQL from two channels never interleave inside
        # the same window, and two threads on the same channel are serialized.
        self.lock = threading.Lock()
        self.window_handle = None
        self.window_ready = threading.Event()


_channels = {}                # channel_id -> _Channel
_channels_lock = threading.Lock()
_next_channel_id = 1


def _alloc_channel_id_locked():
    """Caller must hold _channels_lock."""
    global _next_channel_id
    # Sequential 1..1_000_000, reuse freed IDs.
    start = _next_channel_id
    while True:
        cid = _next_channel_id
        _next_channel_id += 1
        if _next_channel_id > 1_000_000:
            _next_channel_id = 1
        if cid not in _channels:
            return cid
        if _next_channel_id == start:
            return None  # exhausted


def _acquire_channel(owner):
    with _channels_lock:
        if len(_channels) >= MAX_CHANNELS:
            return None, f"channel limit reached ({MAX_CHANNELS})"
        # Reuse: if a channel with same owner exists and is idle, reuse it.
        for ch in _channels.values():
            if ch.owner == owner and not ch.lock.locked():
                ch.last_used_at = time.time()
                return ch, None
        cid = _alloc_channel_id_locked()
        if cid is None:
            return None, "channel id space exhausted"
        ch = _Channel(cid, owner)
        _channels[cid] = ch
    # Create the DOM window OUTSIDE the registry lock.
    ok = _spawn_window_for_channel(ch)
    if not ok:
        with _channels_lock:
            _channels.pop(ch.channel_id, None)
        return None, "failed to spawn DOM window"
    return ch, None


def _release_channel(cid):
    with _channels_lock:
        ch = _channels.pop(cid, None)
    if ch is None:
        return False
    # Destroy the DOM window.
    try:
        _destroy_window_for_channel(cid)
    except Exception as e:
        _log(f"destroy window for channel {cid} failed: {e}")
    return True


def _channel_status(cid):
    with _channels_lock:
        ch = _channels.get(cid)
        if ch is None:
            return {'in_use': False, 'owner': None}
        return {
            'in_use': ch.lock.locked(),
            'owner': ch.owner,
            'created_at': ch.created_at,
            'last_used_at': ch.last_used_at,
        }


def _list_channels():
    with _channels_lock:
        return [
            {
                'channel_id': ch.channel_id,
                'owner': ch.owner,
                'in_use': ch.lock.locked(),
                'created_at': ch.created_at,
                'last_used_at': ch.last_used_at,
            }
            for ch in _channels.values()
        ]


def _get_channel(cid):
    with _channels_lock:
        return _channels.get(cid)


# ==============================================================================
#  DOM WINDOW MANAGEMENT (one window per channel)
# ==============================================================================
def _find_window_handles():
    return list(_driver.window_handles)


def _spawn_window_for_channel(ch):
    """
    Click the floating '+' button in the template, wait for the new
    .db-window[data-window-id] to appear, then tag it with
    data-channel-id so we can address it reliably later.
    """
    global _driver
    if not _ensure_browser():
        return False

    try:
        # Snapshot existing window ids in the workspace.
        existing_ids = set(_driver.execute_script("""
            return Array.from(document.querySelectorAll('.db-window'))
                        .map(w => w.dataset.windowId);
        """) or [])

        # Click the '+' button.
        btn = _driver.find_element(By.CSS_SELECTOR, "#new-window-btn")
        _driver.execute_script("arguments[0].click();", btn)

        # Wait for a new .db-window to appear.
        deadline = time.time() + 5.0
        new_id = None
        while time.time() < deadline:
            cur_ids = set(_driver.execute_script("""
                return Array.from(document.querySelectorAll('.db-window'))
                            .map(w => w.dataset.windowId);
            """) or [])
            diff = cur_ids - existing_ids
            if diff:
                new_id = sorted(diff)[-1]
                break
            time.sleep(0.1)

        if new_id is None:
            _log(f"channel {ch.channel_id}: no new window appeared")
            return False

        # Tag the new window with the channel id and remember its DOM id.
        _driver.execute_script("""
            var w = document.querySelector('.db-window[data-window-id="' + arguments[0] + '"]');
            if (w) {
                w.setAttribute('data-channel-id', String(arguments[1]));
            }
        """, str(new_id), int(ch.channel_id))

        ch.window_handle = str(new_id)
        ch.window_ready.set()
        _log(f"channel {ch.channel_id}: window #{new_id} ready (owner={ch.owner})")
        return True
    except Exception as e:
        _log(f"channel {ch.channel_id}: spawn failed: {e}")
        return False


def _destroy_window_for_channel(cid):
    global _driver
    if _driver is None:
        return
    try:
        _driver.execute_script("""
            var w = document.querySelector('.db-window[data-channel-id="' + arguments[0] + '"]');
            if (w) {
                var closeBtn = w.querySelector('.close-btn');
                if (closeBtn) closeBtn.click();
                else w.remove();
            }
        """, int(cid))
        time.sleep(0.1)
    except Exception as e:
        _log(f"channel {cid}: destroy failed: {e}")


# ==============================================================================
#  PER-WINDOW DOM HELPERS
# ==============================================================================
def _channel_window_selector(cid):
    # Escape not needed since cid is numeric, but keep it safe.
    return f'.db-window[data-channel-id="{int(cid)}"]'


def _channel_read_status(cid):
    if _driver is None:
        return None
    try:
        return _driver.execute_script("""
            var w = document.querySelector(arguments[0]);
            if (!w) return null;
            var s = w.querySelector('.win-exec-status');
            if (!s) return null;
            var state = (s.dataset.state || '').toLowerCase();
            var labelEl = s.querySelector('.status-label');
            var metaEl  = s.querySelector('.status-meta');
            return {
                state: state,
                label: labelEl ? labelEl.textContent.trim() : '',
                meta:  metaEl  ? metaEl.textContent.trim()  : ''
            };
        """, _channel_window_selector(cid))
    except Exception:
        return None


def _channel_reset_status(cid):
    if _driver is None:
        return
    try:
        _driver.execute_script("""
            var w = document.querySelector(arguments[0]);
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
        """, _channel_window_selector(cid))
    except Exception:
        pass


def _channel_set_sql(cid, sql):
    if _driver is None:
        return False
    try:
        return bool(_driver.execute_script("""
            var w = document.querySelector(arguments[0]);
            if (!w) return false;
            var ta = w.querySelector('textarea.sql-query');
            if (!ta) return false;
            var val = arguments[1];
            var proto = Object.getPrototypeOf(ta);
            var desc  = Object.getOwnPropertyDescriptor(proto, 'value');
            if (desc && desc.set) { desc.set.call(ta, val); }
            else { ta.value = val; }
            ta.dispatchEvent(new Event('input',  { bubbles: true }));
            ta.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        """, _channel_window_selector(cid), sql))
    except Exception:
        return False


def _channel_click_execute(cid):
    if _driver is None:
        return False
    try:
        return bool(_driver.execute_script("""
            var w = document.querySelector(arguments[0]);
            if (!w) return false;
            var btn = w.querySelector('.exec-btn');
            if (!btn) return false;
            btn.click();
            return true;
        """, _channel_window_selector(cid)))
    except Exception:
        return False


def _channel_wait_completion(cid, timeout):
    """Wait until this specific window's status is terminal."""
    t0 = time.perf_counter()
    # Small grace period for the state to flip to loading.
    deadline_loading = time.time() + min(2.0, timeout)
    while time.time() < deadline_loading:
        s = _channel_read_status(cid)
        if s and s.get('state') in ('loading', 'success', 'partial', 'empty', 'error'):
            break
        time.sleep(0.1)

    deadline = time.time() + timeout
    while time.time() < deadline:
        s = _channel_read_status(cid) or {}
        if s.get('state') in ('success', 'partial', 'empty', 'error'):
            return True, time.perf_counter() - t0, f"exec-status={s.get('state')}"
        time.sleep(0.1)
    s = _channel_read_status(cid) or {}
    return False, time.perf_counter() - t0, f"timeout (last={s.get('state')!r})"


def _channel_read_message(cid):
    if _driver is None:
        return ""
    try:
        return (_driver.execute_script("""
            var w = document.querySelector(arguments[0]);
            if (!w) return '';
            var m = w.querySelector('.win-message');
            if (!m) return '';
            var st = (m.style.display || '').toLowerCase();
            if (st === 'none') return '';
            return (m.textContent || '').trim();
        """, _channel_window_selector(cid)) or "").strip()
    except Exception:
        return ""


def _channel_collect_results(cid, is_read):
    """Extract rows/affected from this channel's window."""
    results = []
    affected_rows = 0
    if _driver is None:
        return results, affected_rows
    try:
        html = _driver.execute_script("""
            var w = document.querySelector(arguments[0]);
            if (!w) return '';
            var r = w.querySelector('.win-query-result');
            return r ? r.innerHTML : '';
        """, _channel_window_selector(cid))
        soup = BeautifulSoup(html, 'html.parser')

        if not is_read:
            for blk in soup.select('.stmt-block[data-status="success"]'):
                body = blk.find('div', class_='stmt-affected-body')
                if body:
                    m = re.search(r'Affected rows:\s*(\d+)', body.get_text())
                    if m:
                        affected_rows += int(m.group(1))
            return results, affected_rows

        for blk in soup.select('.stmt-block'):
            blk_status = (blk.get('data-status') or '').strip().lower()
            if blk_status != 'success':
                continue
            tbl = blk.find('table')
            if not tbl:
                continue
            headers = [th.get_text(strip=True) for th in tbl.find_all('th')]
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
        _log(f"channel {cid}: collect results failed: {e}")
    return results, affected_rows


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
#  SQL EXECUTION ON A SPECIFIC CHANNEL
# ==============================================================================
def _execute_sql_on_channel(ch, sql, timeout):
    """Runs inside ch.lock. Assumes browser is alive."""
    t_start = time.perf_counter()
    query_id = str(_uuid_module.uuid4().int)[:12]

    if not _ensure_browser():
        return {
            'status': 'error', 'message': 'Browser not available',
            'results': [], 'affected_rows': 0, 'query_id': query_id,
            'raw_sql': sql, 'elapsed': 0.0,
            'channel_id': ch.channel_id,
        }

    # Make sure the window still exists; recreate if it vanished.
    if not _channel_exists(ch.channel_id):
        _log(f"channel {ch.channel_id}: window missing, respawning")
        ch.window_ready.clear()
        ch.window_handle = None
        if not _spawn_window_for_channel(ch):
            return {
                'status': 'error', 'message': 'Channel window missing',
                'results': [], 'affected_rows': 0, 'query_id': query_id,
                'raw_sql': sql, 'elapsed': 0.0,
                'channel_id': ch.channel_id,
            }

    try:
        _channel_reset_status(ch.channel_id)
        if not _channel_set_sql(ch.channel_id, sql):
            raise RuntimeError("could not write into channel textarea")
        time.sleep(0.1)
        if not _channel_click_execute(ch.channel_id):
            raise RuntimeError("could not click execute in channel window")
    except Exception as e:
        return {
            'status': 'error', 'message': f"Query input failed: {e}",
            'results': [], 'affected_rows': 0, 'query_id': query_id,
            'raw_sql': sql, 'elapsed': time.perf_counter() - t_start,
            'channel_id': ch.channel_id,
        }

    ready, _, reason = _channel_wait_completion(ch.channel_id, timeout)

    status_banner = _channel_read_status(ch.channel_id) or {}
    state = (status_banner.get('state') or '').lower()
    banner_meta = (status_banner.get('meta') or '').strip()
    banner_label = (status_banner.get('label') or '').strip()

    is_read = _is_read_query(sql)

    if state == 'error':
        err_msg = _channel_read_message(ch.channel_id) or banner_label or "query failed"
        return {
            'status': 'error', 'message': err_msg,
            'results': [], 'affected_rows': 0, 'query_id': query_id,
            'raw_sql': sql, 'elapsed': time.perf_counter() - t_start,
            'channel_id': ch.channel_id,
        }

    if state == 'empty':
        return {
            'status': 'success',
            'message': banner_label or 'Query executed successfully (0 rows)',
            'results': [], 'affected_rows': 0, 'query_id': query_id,
            'raw_sql': sql, 'elapsed': time.perf_counter() - t_start,
            'channel_id': ch.channel_id,
        }

    results, affected_rows = _channel_collect_results(ch.channel_id, is_read)

    if not is_read:
        if not affected_rows and banner_meta:
            m = re.search(r'(\d+)\s*affected', banner_meta, re.IGNORECASE)
            if m:
                affected_rows = int(m.group(1))
        return {
            'status': 'success',
            'message': banner_label or
                       f'Write query executed ({affected_rows} row(s) affected)',
            'results': [], 'affected_rows': affected_rows,
            'query_id': query_id, 'raw_sql': sql,
            'elapsed': time.perf_counter() - t_start,
            'channel_id': ch.channel_id,
        }

    return {
        'status': 'success',
        'message': banner_label or f'Query executed successfully ({len(results)} rows)',
        'results': results, 'affected_rows': affected_rows,
        'query_id': query_id, 'raw_sql': sql,
        'elapsed': time.perf_counter() - t_start,
        'channel_id': ch.channel_id,
    }


def _channel_exists(cid):
    if _driver is None:
        return False
    try:
        return bool(_driver.execute_script(
            "return !!document.querySelector(arguments[0]);",
            _channel_window_selector(cid)))
    except Exception:
        return False


# ==============================================================================
#  PARAM SUBSTITUTION  (mirrors the client-side behaviour)
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
#  REQUEST DISPATCH
# ==============================================================================
def _handle_request(req):
    if not isinstance(req, dict):
        return {
            'status': 'error', 'message': 'request must be a JSON object',
            'results': [], 'affected_rows': 0, 'query_id': None,
            'raw_sql': None, 'elapsed': 0.0,
        }

    op = (req.get('op') or '').strip().lower()

    # ---- Channel management ops ----
    if op == 'acquire_channel':
        owner = (req.get('owner') or 'anonymous').strip() or 'anonymous'
        ch, err = _acquire_channel(owner)
        if ch is None:
            return {'status': 'error', 'message': err}
        return {
            'status': 'success',
            'channel_id': ch.channel_id,
            'window_id': ch.channel_id,   # template window id == channel id
            'owner': ch.owner,
        }

    if op == 'release_channel':
        cid = int(req.get('channel_id') or 0)
        ok = _release_channel(cid)
        return {'status': 'success' if ok else 'error',
                'released': ok, 'channel_id': cid}

    if op == 'channel_status':
        cid = int(req.get('channel_id') or 0)
        st = _channel_status(cid)
        return {'status': 'success', 'channel_id': cid, **st}

    if op == 'list_channels':
        return {'status': 'success', 'channels': _list_channels()}

    # ---- SQL op (channel-bound or legacy auto) ----
    sql = req.get('sql', '')
    params = req.get('params')
    timeout = float(req.get('timeout', DEFAULT_WAIT_TIMEOUT))

    if not sql or not sql.strip():
        return {
            'status': 'error', 'message': 'Empty SQL',
            'results': [], 'affected_rows': 0, 'query_id': None,
            'raw_sql': sql, 'elapsed': 0.0,
        }

    final_sql = _substitute_params(sql, params)

    cid = req.get('channel_id')
    if cid is None:
        # Legacy call — use a hidden auto-channel that lives in a fresh
        # window. We allocate, run, release.
        ch, err = _acquire_channel('legacy-auto')
        if ch is None:
            return {
                'status': 'error', 'message': f'auto-channel failed: {err}',
                'results': [], 'affected_rows': 0, 'query_id': None,
                'raw_sql': final_sql, 'elapsed': 0.0,
            }
        try:
            with ch.lock:
                ch.last_used_at = time.time()
                return _execute_sql_on_channel(ch, final_sql, timeout)
        finally:
            _release_channel(ch.channel_id)

    # Channel-bound.
    ch = _get_channel(int(cid))
    if ch is None:
        return {
            'status': 'error',
            'message': f'unknown channel_id {cid} (acquire_channel first)',
            'results': [], 'affected_rows': 0, 'query_id': None,
            'raw_sql': final_sql, 'elapsed': 0.0,
        }

    with ch.lock:
        ch.last_used_at = time.time()
        try:
            return _execute_sql_on_channel(ch, final_sql, timeout)
        except Exception as e:
            return {
                'status': 'error', 'message': f'Unhandled executor error: {e}',
                'results': [], 'affected_rows': 0, 'query_id': None,
                'raw_sql': final_sql, 'elapsed': 0.0,
                'channel_id': ch.channel_id,
            }


# ==============================================================================
#  SOCKET FRAMING
# ==============================================================================
def _recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def _send_frame(sock, obj):
    payload = json.dumps(obj, ensure_ascii=False).encode('utf-8')
    if len(payload) > MAX_FRAME:
        raise ValueError("frame too large")
    sock.sendall(_HEADER.pack(len(payload)) + payload)


def _recv_frame(sock):
    header = _recv_exact(sock, _HEADER.size)
    if header is None:
        return None
    (length,) = _HEADER.unpack(header)
    if length == 0:
        return None
    if length > MAX_FRAME:
        raise ValueError(f"frame too large: {length}")
    payload = _recv_exact(sock, length)
    if payload is None:
        return None
    return json.loads(payload.decode('utf-8'))


# ==============================================================================
#  CLIENT HANDLER
# ==============================================================================
def _client_loop(conn, addr):
    _log(f"client connected: {addr}")
    try:
        while True:
            try:
                req = _recv_frame(conn)
            except Exception as e:
                _log(f"client {addr} recv error: {e}")
                break
            if req is None:
                _log(f"client {addr} closed")
                break

            op = (req.get('op') or 'sql').lower() if isinstance(req, dict) else '?'
            _log(f"client {addr} op={op} "
                 f"channel={req.get('channel_id') if isinstance(req, dict) else '-'}")
            try:
                resp = _handle_request(req)
            except Exception as e:
                resp = {
                    'status': 'error',
                    'message': f'bridge dispatcher error: {e}',
                    'results': [], 'affected_rows': 0, 'query_id': None,
                    'raw_sql': None, 'elapsed': 0.0,
                }
            try:
                _send_frame(conn, resp)
            except Exception as e:
                _log(f"client {addr} send error: {e}")
                break
    finally:
        try:
            conn.close()
        except Exception:
            pass
        _log(f"client disconnected: {addr}")


# ==============================================================================
#  SERVER
# ==============================================================================
_shutdown_event = threading.Event()
_server_sock = None


def _serve():
    global _server_sock

    _server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    _server_sock.bind((BIND_HOST, BIND_PORT))
    _server_sock.listen(32)
    _server_sock.settimeout(1.0)
    _log(f"listening on {BIND_HOST}:{BIND_PORT}")

    while not _shutdown_event.is_set():
        try:
            conn, addr = _server_sock.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        except Exception as e:
            _log(f"accept error: {e}")
            continue

        t = threading.Thread(target=_client_loop, args=(conn, addr), daemon=True)
        t.start()


def _idle_reaper():
    """Optional: close channels idle for a long time."""
    if CHANNEL_IDLE_CLOSE_SECONDS <= 0:
        return
    while not _shutdown_event.is_set():
        time.sleep(30)
        now = time.time()
        with _channels_lock:
            stale = [c.channel_id for c in _channels.values()
                     if not c.lock.locked()
                     and (now - c.last_used_at) > CHANNEL_IDLE_CLOSE_SECONDS]
        for cid in stale:
            _log(f"reaping idle channel {cid}")
            _release_channel(cid)


def _signal_handler(sig, frame):
    _log("interrupt — shutting down")
    _shutdown_event.set()
    try:
        if _server_sock:
            _server_sock.close()
    except Exception:
        pass
    try:
        if _driver:
            _driver.quit()
    except Exception:
        pass
    sys.exit(0)


signal.signal(signal.SIGINT, _signal_handler)
try:
    signal.signal(signal.SIGTERM, _signal_handler)
except Exception:
    pass


# ==============================================================================
#  MAIN
# ==============================================================================
def main():
    _log(f"starting at {datetime.now().isoformat(timespec='seconds')}")

    if not _ensure_browser():
        _log("WARNING: initial browser launch failed — will retry on first request")

    # Start idle reaper if configured.
    if CHANNEL_IDLE_CLOSE_SECONDS > 0:
        threading.Thread(target=_idle_reaper, daemon=True).start()

    _log("bridge is up. Ctrl+C to stop.")
    _serve()


if __name__ == "__main__":
    main()