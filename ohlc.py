import os
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
import pytz
import json
import time
import traceback
import shutil
import re
import multiprocessing
import sys

BASE_ERROR_FOLDER = r"C:\xampp\htdocs\harvcore\harvox\invharv\usersdata\debugs"
BROKERS_JSON_PATH = r"C:\xampp\htdocs\harvcore\harvox\invharv\usersdata\developers\developers.json"
OHLC_FOLDER = r"C:\xampp\htdocs\harvcore\harvox\invharv\usersdata\developers"
MAX_TERMINALS_PER_DEVELOPER = 5

# ==============================================================================
#  EXHAUSTIVE TIMEFRAME MAP
#
#  Covers EVERY timeframe that MT5's Python binding exposes.
#  Declared ASCENDING so:
#    - the probe tests lowest first
#    - the stored `timeframes` array is lowest → highest
#
#  If a broker doesn't offer a timeframe, `copy_rates_from_pos` returns
#  None / empty and the probe simply omits it from the output.
# ==============================================================================
TIMEFRAME_MAP = {
    # ── Minutes ──
    "1m":  mt5.TIMEFRAME_M1,
    "2m":  mt5.TIMEFRAME_M2,
    "3m":  mt5.TIMEFRAME_M3,
    "4m":  mt5.TIMEFRAME_M4,
    "5m":  mt5.TIMEFRAME_M5,
    "6m":  mt5.TIMEFRAME_M6,
    "10m": mt5.TIMEFRAME_M10,
    "12m": mt5.TIMEFRAME_M12,
    "15m": mt5.TIMEFRAME_M15,
    "20m": mt5.TIMEFRAME_M20,
    "30m": mt5.TIMEFRAME_M30,

    # ── Hours ──
    "1h":  mt5.TIMEFRAME_H1,
    "2h":  mt5.TIMEFRAME_H2,
    "3h":  mt5.TIMEFRAME_H3,
    "4h":  mt5.TIMEFRAME_H4,
    "6h":  mt5.TIMEFRAME_H6,
    "8h":  mt5.TIMEFRAME_H8,
    "12h": mt5.TIMEFRAME_H12,

    # ── Days / Weeks / Months ──
    "1d":  mt5.TIMEFRAME_D1,
    "1w":  mt5.TIMEFRAME_W1,
    "1mo": mt5.TIMEFRAME_MN1,
}

ERROR_JSON_PATH = os.path.join(BASE_ERROR_FOLDER, "chart_errors.json")


class CaseInsensitiveDict:
    """A dictionary that allows case-insensitive key access while preserving original keys."""
    def __init__(self, data=None):
        self._data = data or {}
        self._key_map = {k.lower(): k for k in self._data.keys() if isinstance(k, str)}

    def get(self, key, default=None):
        if key is None:
            return default
        key_lower = str(key).lower()
        if key_lower in self._key_map:
            return self._data[self._key_map[key_lower]]
        return default

    def get_all(self):
        return self._data

    def get_key_insensitive(self, key):
        if key is None:
            return None
        key_lower = str(key).lower()
        return self._key_map.get(key_lower)

    def __contains__(self, key):
        if key is None:
            return False
        return str(key).lower() in self._key_map

    def __getitem__(self, key):
        if key is None:
            raise KeyError("None key")
        key_lower = str(key).lower()
        if key_lower in self._key_map:
            return self._data[self._key_map[key_lower]]
        raise KeyError(key)


def log_and_print(message, level="INFO"):
    """Log and print messages in a structured format."""
    timestamp = datetime.now(pytz.timezone('Africa/Lagos')).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {level:8} | {message}")


def _extract_terminal_paths(user_config):
    """
    Dynamically discover ALL terminal path fields in the developer record.
    """
    if not isinstance(user_config, dict):
        return []

    pattern = re.compile(r'^terminal[_]?path(?:[_]?(\d+))?$', re.IGNORECASE)

    matches = []
    for raw_key, raw_val in user_config.items():
        if not isinstance(raw_key, str):
            continue

        m = pattern.match(raw_key.strip())
        if not m:
            continue

        if not isinstance(raw_val, str):
            continue
        val = raw_val.strip()
        if not val or val.upper() == "NULL":
            continue

        suffix = m.group(1)
        try:
            order = int(suffix) if suffix is not None else 0
        except (ValueError, TypeError):
            order = 0

        matches.append((raw_key, val, order))

    matches.sort(key=lambda x: (x[2], x[0]))
    return matches


def load_ohlc_dictionary():
    """
    Load brokers config from JSON file with case-insensitive field handling.
    """

    if not os.path.exists(BROKERS_JSON_PATH):
        log_and_print(f"CRITICAL: {BROKERS_JSON_PATH} NOT FOUND! Using empty config.", "CRITICAL")
        return {}

    try:
        with open(BROKERS_JSON_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)

        transformed_data = {}

        for user_id, user_config in data.items():
            ci_config = CaseInsensitiveDict(user_config)

            # ── Credentials ──
            login = (
                ci_config.get("login")
                or ci_config.get("LOGIN_ID")
                or ci_config.get("login_id")
                or ci_config.get("loginId")
                or ""
            )
            broker_password = (
                ci_config.get("broker_password")
                or ci_config.get("BROKER_PASSWORD")
                or ci_config.get("brokerPassword")
                or ""
            )
            server = (
                ci_config.get("server")
                or ci_config.get("SERVER")
                or ci_config.get("Server")
                or ""
            )
            broker_name = (
                ci_config.get("broker")
                or ci_config.get("BROKER")
                or ci_config.get("Broker")
                or "deriv"
            )

            if server and server.lower().startswith('derivsvg'):
                if 'derivsvg' in server.lower():
                    server = server.replace('derivsvg', 'DerivSVG')

            # ── Terminal paths ──
            raw_terminal_matches = _extract_terminal_paths(user_config)
            terminal_paths = []

            for raw_key, val, order in raw_terminal_matches:
                if os.path.exists(val):
                    terminal_paths.append((raw_key, val))
                    log_and_print(f"Found {raw_key}: {val}", "INFO")
                else:
                    log_and_print(
                        f"WARNING: {raw_key} value exists but file not found: {val}",
                        "WARNING"
                    )

            # ── Selected symbols ──
            selected_symbols = ci_config.get("selected_symbols")
            if selected_symbols is None:
                selected_symbols = ci_config.get("SELECTED_SYMBOLS")
            if not isinstance(selected_symbols, list):
                selected_symbols = []

            # ── Account management / timeframes ──
            account_management = (
                ci_config.get("accountmanagement")
                or ci_config.get("ACCOUNTMANAGEMENT")
                or {}
            )
            if isinstance(account_management, dict):
                am_ci = CaseInsensitiveDict(account_management)
                symbols_dict = (
                    am_ci.get("symbols_dictionary")
                    or am_ci.get("SYMBOLS_DICTIONARY")
                    or {}
                )
                if isinstance(symbols_dict, dict):
                    sd_ci = CaseInsensitiveDict(symbols_dict)
                    ohlc_timeframes = (
                        sd_ci.get("ohlc_timeframes")
                        or sd_ci.get("OHLC_TIMEFRAMES")
                        or ["15m", "5m", "30m", "1h", "4h"]
                    )
                else:
                    ohlc_timeframes = ["15m", "5m", "30m", "1h", "4h"]
            else:
                symbols_dict = {}
                ohlc_timeframes = ["15m", "5m", "30m", "1h", "4h"]

            valid_timeframes = []
            for tf in ohlc_timeframes:
                if tf in TIMEFRAME_MAP:
                    valid_timeframes.append(tf)
                else:
                    log_and_print(f"WARNING: Timeframe '{tf}' not supported. Skipping.", "WARNING")
            if not valid_timeframes:
                valid_timeframes = ["15m", "5m", "30m", "1h", "4h"]
                log_and_print(f"No valid timeframes found for user {user_id}. Using defaults.", "WARNING")

            if isinstance(symbols_dict, dict):
                clean_symbols_dict = {
                    k: v for k, v in symbols_dict.items()
                    if str(k).lower() not in ["ohlc_bars", "ohlc_timeframes"]
                }
            else:
                clean_symbols_dict = {}

            base_folder = os.path.join(OHLC_FOLDER, str(user_id))

            if not terminal_paths:
                log_and_print(
                    f"SKIP user {user_id}: no valid terminal_path field found.",
                    "WARNING"
                )
                continue

            # ── No selected symbols → metadata-only per terminal ──
            if len(selected_symbols) == 0:
                log_and_print(
                    f"METADATA-ONLY user {user_id}: no selected_symbols — "
                    f"will refresh symbols + timeframes only.",
                    "WARNING"
                )
                for idx, (raw_key, tp) in enumerate(terminal_paths, 1):
                    account_key = f"__metadata_only__{user_id}_terminal_{idx}"
                    transformed_data[account_key] = {
                        "LOGIN_ID": str(login),
                        "broker_password": str(broker_password),
                        "SERVER": str(server),
                        "BASE_FOLDER": base_folder,
                        "terminal_path": tp,
                        "terminal_field": raw_key,
                        "USER_ID": str(user_id),
                        "BROKER_NAME": str(broker_name),
                        "SYMBOLS_DICTIONARY": clean_symbols_dict,
                        "OHLC_TIMEFRAMES": valid_timeframes,
                        "SELECTED_SYMBOLS": [],
                        "METADATA_ONLY": True,
                    }
                    log_and_print(f"Created metadata-only config for {account_key}", "INFO")
                continue

            # ── Has selected symbols → one config per terminal ──
            num_developers = len(data)
            terminals_to_use = (
                terminal_paths if num_developers == 1
                else terminal_paths[:MAX_TERMINALS_PER_DEVELOPER]
            )

            log_and_print(
                f"Found {len(terminal_paths)} terminal path(s) for user {user_id} "
                f"(using {len(terminals_to_use)})",
                "INFO"
            )

            for idx, (raw_key, tp) in enumerate(terminals_to_use, 1):
                account_key = f"{broker_name.lower()}_{user_id}_terminal_{idx}"
                transformed_data[account_key] = {
                    "LOGIN_ID": str(login),
                    "broker_password": str(broker_password),
                    "SERVER": str(server),
                    "BASE_FOLDER": base_folder,
                    "terminal_path": tp,
                    "terminal_field": raw_key,
                    "USER_ID": str(user_id),
                    "BROKER_NAME": str(broker_name),
                    "SYMBOLS_DICTIONARY": clean_symbols_dict,
                    "OHLC_TIMEFRAMES": valid_timeframes,
                    "SELECTED_SYMBOLS": selected_symbols,
                    "METADATA_ONLY": False,
                }
                log_and_print(f"Created config for {account_key} ({raw_key})", "INFO")

        log_and_print(
            f"Loaded {len(transformed_data)} terminal configurations from "
            f"{len(data)} developers",
            "SUCCESS"
        )
        return transformed_data

    except json.JSONDecodeError as e:
        log_and_print(f"Invalid JSON in developers.json: {e}", "CRITICAL")
        return {}
    except Exception as e:
        log_and_print(f"Failed to load developers.json: {e}", "CRITICAL")
        traceback.print_exc()
        return {}


ohlcdictionary = load_ohlc_dictionary()


def get_user_id_from_account(account_key):
    """Extract user ID from account key: deriv_6_terminal_1 -> 6"""
    parts = account_key.split('_')
    if len(parts) >= 3:
        for i, part in enumerate(parts):
            if part.lower() == 'terminal' and i > 0:
                return parts[i-1]
    return None


def save_errors(error_log):
    """Save error log to JSON file."""
    try:
        os.makedirs(BASE_ERROR_FOLDER, exist_ok=True)
        with open(ERROR_JSON_PATH, 'w') as f:
            json.dump(error_log, f, indent=4)
        log_and_print("Error log saved", "ERROR")
    except Exception as e:
        log_and_print(f"Failed to save error log: {str(e)}", "ERROR")


def initialize_mt5(terminal_path, login_id, broker_password, server):
    """Initialize MetaTrader 5 terminal for a specific broker."""
    error_log = []
    if not terminal_path or not os.path.exists(terminal_path):
        error_log.append({
            "timestamp": datetime.now(pytz.timezone('Africa/Lagos')).strftime('%Y-%m-%d %H:%M:%S.%f+01:00'),
            "error": f"MT5 terminal executable not found: {terminal_path}",
            "broker": server
        })
        save_errors(error_log)
        log_and_print(f"MT5 terminal executable not found: {terminal_path}", "ERROR")
        return False, error_log

    try:
        try:
            login_int = int(login_id)
        except (ValueError, TypeError):
            error_log.append({
                "timestamp": datetime.now(pytz.timezone('Africa/Lagos')).strftime('%Y-%m-%d %H:%M:%S.%f+01:00'),
                "error": f"Invalid login ID: {login_id} (must be numeric)",
                "broker": server
            })
            save_errors(error_log)
            return False, error_log

        if not mt5.initialize(
            path=terminal_path,
            login=login_int,
            server=server,
            password=broker_password,
            timeout=30000
        ):
            error_log.append({
                "timestamp": datetime.now(pytz.timezone('Africa/Lagos')).strftime('%Y-%m-%d %H:%M:%S.%f+01:00'),
                "error": f"Failed to initialize MT5: {mt5.last_error()}",
                "broker": server
            })
            save_errors(error_log)
            log_and_print(f"Failed to initialize MT5: {mt5.last_error()}", "ERROR")
            return False, error_log

        if not mt5.login(login=login_int, server=server, password=broker_password):
            error_log.append({
                "timestamp": datetime.now(pytz.timezone('Africa/Lagos')).strftime('%Y-%m-%d %H:%M:%S.%f+01:00'),
                "error": f"Failed to login to MT5: {mt5.last_error()}",
                "broker": server
            })
            save_errors(error_log)
            log_and_print(f"Failed to login to MT5: {mt5.last_error()}", "ERROR")
            mt5.shutdown()
            return False, error_log

        return True, error_log
    except Exception as e:
        error_log.append({
            "timestamp": datetime.now(pytz.timezone('Africa/Lagos')).strftime('%Y-%m-%d %H:%M:%S.%f+01:00'),
            "error": f"Unexpected error in initialize_mt5: {str(e)}",
            "broker": server
        })
        save_errors(error_log)
        log_and_print(f"Unexpected error in initialize_mt5: {str(e)}", "ERROR")
        return False, error_log


def fetch_all_ohlcv_data(symbol, mt5_timeframe):
    """Fetch ALL available OHLCV data for a symbol/timeframe."""
    error_log = []
    lagos_tz = pytz.timezone('Africa/Lagos')
    timestamp = datetime.now(lagos_tz).strftime('%Y-%m-%d %H:%M:%S.%f%z')

    selected = False
    for attempt in range(3):
        if mt5.symbol_select(symbol, True):
            selected = True
            break
        time.sleep(0.5)

    if not selected:
        last_err = mt5.last_error()
        err_msg = f"FAILED symbol_select('{symbol}'): {last_err}"
        log_and_print(err_msg, "ERROR")
        return None, [{"error": err_msg, "timestamp": timestamp}]

    bars_available = 0
    for test_count in [100000, 50000, 20000, 10000, 5000, 1000]:
        try:
            test_rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, test_count)
            if test_rates is not None and len(test_rates) > 0:
                bars_available = len(test_rates)
                log_and_print(f"Found {bars_available} bars available for {symbol}", "INFO")
                break
        except Exception:
            continue

    if bars_available == 0:
        try:
            test_rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, 10)
            if test_rates is not None and len(test_rates) > 0:
                bars_available = len(test_rates)
                log_and_print(f"Found {bars_available} bars available for {symbol} (small sample)", "INFO")
        except Exception as e:
            log_and_print(f"Cannot fetch any bars for {symbol}: {str(e)}", "ERROR")

    if bars_available > 0:
        rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, bars_available)
        if rates is None or len(rates) == 0:
            err_msg = f"No data for {symbol}"
            log_and_print(err_msg, "ERROR")
            return None, [{"error": err_msg, "timestamp": timestamp}]

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.set_index("time")
        df = df.astype({
            "open": float, "high": float, "low": float, "close": float,
            "tick_volume": float, "spread": int, "real_volume": float
        })
        df.rename(columns={"tick_volume": "volume"}, inplace=True)

        log_and_print(f"Fetched {len(df)} bars for {symbol}", "INFO")
        return df, error_log

    log_and_print(f"No bars available for {symbol}", "WARNING")
    return None, error_log


def save_candle_records(user_id, symbol, timeframe, df):
    """
    Save candle data to: developers/{user_id}/candle_records.json

    New derived fields per candle:
      candle_center, body_center, high_wick_center, low_wick_center,
      candle_width_center
    """
    if df is None or df.empty:
        log_and_print(f"⚠️  No data to save for {symbol} ({timeframe})", "WARNING")
        return

    candle_records_path = os.path.join(OHLC_FOLDER, str(user_id), "candle_records.json")
    os.makedirs(os.path.dirname(candle_records_path), exist_ok=True)

    all_candle_data = {}
    if os.path.exists(candle_records_path):
        try:
            with open(candle_records_path, 'r', encoding='utf-8') as f:
                all_candle_data = json.load(f)
            log_and_print(f"📂 Loaded existing data with {len(all_candle_data)} symbols", "DEBUG")
        except (json.JSONDecodeError, IOError) as e:
            log_and_print(f"⚠️  Could not read existing candle_records.json: {e}", "WARNING")
            all_candle_data = {}

    candle_list = []
    for idx, row in df.iterrows():
        o = float(row['open'])
        h = float(row['high'])
        l = float(row['low'])
        c = float(row['close'])

        candle_center = (h + l) / 2.0
        body_center = (o + c) / 2.0
        high_wick_center = (h + c) / 2.0
        low_wick_center = (l + o) / 2.0 if c >= o else (c + l) / 2.0
        candle_width_center = (h - l) / 2.0

        candle = {
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": idx.strftime('%Y-%m-%d %H:%M:%S'),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": float(row['volume']),
            "candle_center": candle_center,
            "body_center": body_center,
            "high_wick_center": high_wick_center,
            "low_wick_center": low_wick_center,
            "candle_width_center": candle_width_center,
        }
        candle_list.append(candle)

    all_candle_data[symbol] = candle_list

    log_and_print(f"📝 Updated data for symbol: {symbol} ({timeframe}) - {len(candle_list)} candles", "INFO")
    log_and_print(f"📊 Total symbols in file: {len(all_candle_data)}", "DEBUG")

    try:
        with open(candle_records_path, 'w', encoding='utf-8') as f:
            json.dump(all_candle_data, f, indent=4)
        log_and_print(f"✅ Saved {len(candle_list)} candles for {symbol} ({timeframe})", "SUCCESS")
    except Exception as e:
        log_and_print(f"❌ Failed to save candle_records.json: {str(e)}", "ERROR")


def update_available_symbols(user_id, available_symbols):
    """Update developers.json with the broker's available symbols under `symbols`."""
    try:
        if not os.path.exists(BROKERS_JSON_PATH):
            log_and_print(f"ERROR: {BROKERS_JSON_PATH} not found. Cannot update symbols.", "ERROR")
            return False

        with open(BROKERS_JSON_PATH, 'r', encoding='utf-8') as f:
            developers_data = json.load(f)

        real_key = None
        for k in developers_data.keys():
            if str(k) == str(user_id):
                real_key = k
                break
        if real_key is None:
            log_and_print(f"WARNING: User {user_id} not found in developers.json", "WARNING")
            return False

        developers_data[real_key]["symbols"] = available_symbols

        with open(BROKERS_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(developers_data, f, indent=4, ensure_ascii=False)

        log_and_print(
            f"  ✅ Updated developers.json with {len(available_symbols)} symbols "
            f"for user {user_id} (written to `symbols`)",
            "SUCCESS"
        )
        return True

    except json.JSONDecodeError as e:
        log_and_print(f"ERROR: Invalid JSON in developers.json: {e}", "ERROR")
        return False
    except Exception as e:
        log_and_print(f"ERROR: Failed to update developers.json: {str(e)}", "ERROR")
        traceback.print_exc()
        return False


# =====================================================================
#  DYNAMIC TIMEFRAME DISCOVERY
# =====================================================================
def _probe_timeframes_for_broker(available_symbols_set, sample_size=5):
    """
    Given the set of symbols the broker offers, return the sorted list of
    timeframe keys (from TIMEFRAME_MAP) that actually return at least one
    bar for at least one sampled symbol.

    Every timeframe in TIMEFRAME_MAP is probed. If the broker doesn't offer
    a given timeframe, `copy_rates_from_pos` returns None/empty and it's
    omitted from the result.

    The returned list preserves TIMEFRAME_MAP's declaration order, which is
    ascending (1m → 2m → ... → 4h → ... → 1mo).
    """
    if not available_symbols_set:
        return []

    # Prefer well-known active symbols as probes to reduce false negatives.
    preferred = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD", "ETHUSD",
                 "US30", "NAS100", "SPX500", "AUDUSD", "USDCAD", "USDCHF"]
    probes = [s for s in preferred if s in available_symbols_set]
    for s in available_symbols_set:
        if s not in probes:
            probes.append(s)
        if len(probes) >= sample_size:
            break
    probes = probes[:sample_size]

    supported = []

    log_and_print(f"  🧪 Probing {len(TIMEFRAME_MAP)} timeframe(s) across "
                  f"{len(probes)} sample symbol(s): {probes}", "INFO")

    for tf_key, tf_const in TIMEFRAME_MAP.items():
        found_for_tf = False
        for sym in probes:
            try:
                if not mt5.symbol_select(sym, True):
                    continue
                rates = mt5.copy_rates_from_pos(sym, tf_const, 0, 5)
                if rates is not None and len(rates) > 0:
                    found_for_tf = True
                    break
            except Exception:
                continue

        if found_for_tf:
            supported.append(tf_key)
            log_and_print(f"  ✅ Timeframe '{tf_key}' supported", "INFO")
        else:
            log_and_print(f"  ⏭️  Timeframe '{tf_key}' unsupported — skipped", "INFO")

    # Return in canonical TIMEFRAME_MAP order (ascending)
    ordered = [tf for tf in TIMEFRAME_MAP.keys() if tf in supported]
    return ordered


def update_available_timeframes(user_id, available_timeframes):
    """
    Update developers.json with the broker's available timeframes
    under the `timeframes` field. `selected_timeframes` is NOT touched.
    """
    try:
        if not os.path.exists(BROKERS_JSON_PATH):
            log_and_print(f"ERROR: {BROKERS_JSON_PATH} not found. Cannot update timeframes.", "ERROR")
            return False

        with open(BROKERS_JSON_PATH, 'r', encoding='utf-8') as f:
            developers_data = json.load(f)

        real_key = None
        for k in developers_data.keys():
            if str(k) == str(user_id):
                real_key = k
                break
        if real_key is None:
            log_and_print(f"WARNING: User {user_id} not found in developers.json", "WARNING")
            return False

        developers_data[real_key]["timeframes"] = available_timeframes

        with open(BROKERS_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(developers_data, f, indent=4, ensure_ascii=False)

        log_and_print(
            f"  ✅ Updated developers.json with {len(available_timeframes)} timeframes "
            f"for user {user_id} (written to `timeframes`)",
            "SUCCESS"
        )
        return True

    except json.JSONDecodeError as e:
        log_and_print(f"ERROR: Invalid JSON in developers.json: {e}", "ERROR")
        return False
    except Exception as e:
        log_and_print(f"ERROR: Failed to update developers.json (timeframes): {str(e)}", "ERROR")
        traceback.print_exc()
        return False
# =====================================================================


def process_account_worker(account_key, account_cfg, symbol_chunk, TIMEFRAME_MAP, result_dict):
    """
    Worker: initialize MT5, refresh symbols + timeframes, then fetch OHLC
    bars for the assigned symbol chunk.
    """
    processed_count = 0

    user_timeframes = account_cfg.get("OHLC_TIMEFRAMES", ["15m", "5m", "30m", "1h", "4h"])
    user_id = account_cfg.get("USER_ID", "unknown")
    metadata_only = bool(account_cfg.get("METADATA_ONLY", False))

    required_keys = ["terminal_path", "LOGIN_ID", "broker_password", "SERVER"]
    missing = [k for k in required_keys if not account_cfg.get(k)]
    if missing:
        log_and_print(
            f"   {account_key.upper()} | Missing required config keys: {missing} — skipping",
            "ERROR"
        )
        result_dict[account_key] = 0
        return

    user_timeframe_map = {}
    for tf_str in user_timeframes:
        if tf_str in TIMEFRAME_MAP:
            user_timeframe_map[tf_str] = TIMEFRAME_MAP[tf_str]

    if not user_timeframe_map:
        log_and_print(f"⚠️  No valid timeframes for {account_key}. Using defaults.", "WARNING")
        user_timeframe_map = {tf: TIMEFRAME_MAP[tf] for tf in ["15m", "5m", "30m", "1h", "4h"]}

    if symbol_chunk and len(symbol_chunk) > 0:
        symbols_to_process = symbol_chunk
    else:
        symbols_dict = account_cfg.get("SYMBOLS_DICTIONARY", {})
        symbols_to_process = []
        for category, symbol_list in symbols_dict.items():
            if isinstance(symbol_list, list):
                for sym in symbol_list:
                    if sym:
                        symbols_to_process.append((sym, category))

    total_in_chunk = len(symbols_to_process)
    log_and_print(f"\n  ⚙️  {account_key.upper()} | Starting | {total_in_chunk} symbols", "INFO")
    if not metadata_only:
        log_and_print(
            f"  ⚙️  {account_key.upper()} | Fetching ALL available bars | "
            f"Timeframes: {list(user_timeframe_map.keys())}",
            "INFO"
        )
    else:
        log_and_print(f"  ⚙️  {account_key.upper()} | METADATA-ONLY mode | No selected_symbols", "INFO")

    broker_symbols = []
    available_symbols_set = set()
    symbol_timeframes_map = {}

    try:
        ok, _ = initialize_mt5(
            account_cfg["terminal_path"],
            account_cfg["LOGIN_ID"],
            account_cfg["broker_password"],
            account_cfg["SERVER"]
        )

        if ok:
            all_symbols = mt5.symbols_get()
            if all_symbols:
                broker_symbols = [s.name for s in all_symbols]
                available_symbols_set = set(broker_symbols)

                log_and_print(f"  ✅ Total symbols available: {len(broker_symbols)}", "SUCCESS")

                # Persist broker symbol list to developers.json under `symbols`
                update_available_symbols(user_id, broker_symbols)

                # ── Discover timeframes the broker actually supports ──
                log_and_print(f"  🔎 Probing supported timeframes...", "INFO")
                try:
                    supported_tfs = _probe_timeframes_for_broker(available_symbols_set, sample_size=5)
                    if supported_tfs:
                        log_and_print(
                            f"  ✅ Detected {len(supported_tfs)} supported timeframe(s): "
                            f"{supported_tfs}",
                            "SUCCESS"
                        )
                        update_available_timeframes(user_id, supported_tfs)
                    else:
                        log_and_print(
                            f"  ⚠️ No timeframes detected — leaving `timeframes` unchanged",
                            "WARNING"
                        )
                except Exception as tf_err:
                    log_and_print(
                        f"  ⚠️ Timeframe probe failed: {tf_err}",
                        "WARNING"
                    )

                if metadata_only:
                    mt5.shutdown()
                    result_dict[account_key] = 0
                    log_and_print(f"  🏁 {account_key.upper()} | Metadata-only update done", "SUCCESS")
                    log_and_print(f"  {'='*60}\n", "INFO")
                    return

                filtered_symbols = []
                missing_symbols = []

                for sym_item, cat in symbols_to_process:
                    symbol_name = sym_item
                    custom_timeframes = None

                    if isinstance(sym_item, str):
                        if 'specific_timeframes[' in sym_item and ']' in sym_item:
                            parts = sym_item.split('specific_timeframes[')
                            symbol_name = parts[0].strip()
                            if symbol_name.endswith(','):
                                symbol_name = symbol_name[:-1].strip()

                            timeframe_part = parts[1].split(']')[0].strip()
                            custom_timeframes = []
                            for tf in timeframe_part.split(','):
                                tf_clean = tf.strip()
                                if tf_clean in TIMEFRAME_MAP:
                                    custom_timeframes.append(tf_clean)

                            if custom_timeframes:
                                log_and_print(
                                    f"  📌 {symbol_name} has custom timeframes: {custom_timeframes}",
                                    "INFO"
                                )
                                symbol_timeframes_map[symbol_name] = custom_timeframes

                    symbol_found = False
                    matched_symbol = None

                    if symbol_name in available_symbols_set:
                        symbol_found = True
                        matched_symbol = symbol_name
                    elif not symbol_found:
                        for avail_sym in available_symbols_set:
                            if avail_sym.upper() == symbol_name.upper():
                                symbol_found = True
                                matched_symbol = avail_sym
                                break
                    if not symbol_found:
                        for avail_sym in available_symbols_set:
                            if (avail_sym.upper().startswith(symbol_name.upper())
                                    or symbol_name.upper() in avail_sym.upper()):
                                symbol_found = True
                                matched_symbol = avail_sym
                                break

                    if symbol_found and matched_symbol:
                        filtered_symbols.append((matched_symbol, cat))
                        if symbol_name in symbol_timeframes_map:
                            symbol_timeframes_map[matched_symbol] = symbol_timeframes_map.pop(symbol_name)
                    else:
                        missing_symbols.append(symbol_name)

                symbols_to_process = filtered_symbols

                if missing_symbols:
                    log_and_print(f"   Skipped: {len(missing_symbols)} symbols", "WARNING")
            else:
                log_and_print(f"   {account_key.upper()} | No symbols retrieved from MT5", "ERROR")
                mt5.shutdown()
                result_dict[account_key] = 0
                return

            mt5.shutdown()
        else:
            log_and_print(f"   {account_key.upper()} | Failed to initialize MT5 to fetch symbols", "ERROR")
            result_dict[account_key] = 0
            return

    except Exception as e:
        log_and_print(f"   {account_key.upper()} | Error fetching symbols: {str(e)}", "ERROR")
        try:
            mt5.shutdown()
        except Exception:
            pass
        result_dict[account_key] = 0
        return

    if not symbols_to_process:
        log_and_print(f"  ⚠️  {account_key.upper()} | No symbols to process. Skipping.", "WARNING")
        result_dict[account_key] = 0
        return

    for symbol, cat in symbols_to_process:
        ok, _ = initialize_mt5(
            account_cfg["terminal_path"],
            account_cfg["LOGIN_ID"],
            account_cfg["broker_password"],
            account_cfg["SERVER"]
        )

        if not ok:
            log_and_print(f"  ⚠️  {account_key.upper()} | Connection failed | {symbol}", "ERROR")
            continue

        try:
            if symbol in symbol_timeframes_map:
                symbol_timeframes = symbol_timeframes_map[symbol]
                symbol_tf_map = {}
                for tf_str in symbol_timeframes:
                    if tf_str in TIMEFRAME_MAP:
                        symbol_tf_map[tf_str] = TIMEFRAME_MAP[tf_str]
                log_and_print(
                    f"  📌 {account_key.upper()} | {symbol} custom timeframes: {list(symbol_tf_map.keys())}",
                    "INFO"
                )
            else:
                symbol_tf_map = user_timeframe_map
                log_and_print(
                    f"  📌 {account_key.upper()} | {symbol} global timeframes: {list(symbol_tf_map.keys())}",
                    "INFO"
                )

            if not symbol_tf_map:
                log_and_print(f"  ⚠️  {account_key.upper()} | {symbol} no valid timeframes. Skipping.", "WARNING")
                mt5.shutdown()
                continue

            log_and_print(f"  📈 {account_key.upper()} | Processing | {symbol} ({cat})", "INFO")

            for tf_str, mt5_tf in symbol_tf_map.items():
                df, _ = fetch_all_ohlcv_data(symbol, mt5_tf)
                if df is not None and not df.empty:
                    save_candle_records(user_id, symbol, tf_str, df)

            processed_count += 1
            log_and_print(f"  ✅ {account_key.upper()} | Completed | {symbol}", "SUCCESS")

        except Exception as e:
            log_and_print(f"   {account_key.upper()} | Error on {symbol}: {str(e)[:50]}", "ERROR")
        finally:
            mt5.shutdown()

    result_dict[account_key] = processed_count
    log_and_print(
        f"  🏁 {account_key.upper()} | Finished | {processed_count}/{len(symbols_to_process)} symbols processed",
        "SUCCESS"
    )
    log_and_print(f"  {'='*60}\n", "INFO")


def fetch_charts_all_brokers():
    """
    Fetch charts for all brokers.
    """
    log_and_print("\n" + "╔" + "═"*58 + "╗", "INFO")
    log_and_print("║           🚀 MULTI-ACCOUNT SYNCHRONIZATION ENGINE           ║", "INFO")
    log_and_print("╚" + "═"*58 + "╝\n", "INFO")

    try:
        if not ohlcdictionary:
            log_and_print("⚠️  No MT5 configurations found. Cannot process symbols.", "ERROR")
            return False

        user_accounts = {}
        for acc_key, acc_cfg in ohlcdictionary.items():
            user_id = acc_cfg.get("USER_ID", "unknown")
            if user_id not in user_accounts:
                user_accounts[user_id] = []
            user_accounts[user_id].append((acc_key, acc_cfg))

        manager = multiprocessing.Manager()
        final_counts = manager.dict()
        processes = []

        for user_id, accounts in user_accounts.items():
            is_metadata_only = all(
                bool(cfg.get("METADATA_ONLY", False)) for _, cfg in accounts
            )

            log_and_print(
                f"\n📋 USER {user_id} | {len(accounts)} terminals"
                + (" [METADATA-ONLY: no selected_symbols]" if is_metadata_only else ""),
                "INFO"
            )

            if is_metadata_only:
                for acc_key, acc_cfg in accounts:
                    p = multiprocessing.Process(
                        target=process_account_worker,
                        args=(acc_key, acc_cfg, [], TIMEFRAME_MAP, final_counts)
                    )
                    processes.append(p)
                    p.start()
                    log_and_print(
                        f"  └─ {acc_key} | metadata-only (refresh `symbols` + `timeframes`)",
                        "INFO"
                    )
                continue

            user_symbols = []
            for acc_key, acc_cfg in accounts:
                symbols_dict = acc_cfg.get("SYMBOLS_DICTIONARY", {})
                for category, symbol_list in symbols_dict.items():
                    if isinstance(symbol_list, list):
                        for sym in symbol_list:
                            if sym and sym not in user_symbols:
                                user_symbols.append((sym, category))

            log_and_print(f"  📊 USER {user_id} | Found {len(user_symbols)} unique symbols", "INFO")

            if not user_symbols:
                log_and_print(f"  ⚠️  USER {user_id} | No symbols found in dictionary", "WARNING")
                continue

            num_terminals = len(accounts)
            total_symbols = len(user_symbols)
            symbols_per_terminal = total_symbols // num_terminals
            remainder = total_symbols % num_terminals

            start = 0
            for i, (acc_key, acc_cfg) in enumerate(accounts):
                end = start + symbols_per_terminal + (1 if i < remainder else 0)
                chunk = user_symbols[start:end]
                start = end

                p = multiprocessing.Process(
                    target=process_account_worker,
                    args=(acc_key, acc_cfg, chunk, TIMEFRAME_MAP, final_counts)
                )
                processes.append(p)
                p.start()
                log_and_print(
                    f"  └─ {acc_key} | {len(chunk)} symbols | "
                    f"TFs: {acc_cfg.get('OHLC_TIMEFRAMES', [])}",
                    "INFO"
                )

        for p in processes:
            p.join()

        total_processed = sum(final_counts.values())

        log_and_print("\n" + "╔" + "═"*58 + "╗", "SUCCESS")
        log_and_print("║                    🏁 PROCESSING COMPLETE                    ║", "SUCCESS")
        log_and_print("╠" + "═"*58 + "╣", "SUCCESS")

        for acc_key, count in final_counts.items():
            percentage = (count / total_processed) * 100 if total_processed > 0 else 0
            log_and_print(f"║ {acc_key[:30]:30} │ {count:3} symbols │ {percentage:5.1f}%", "SUCCESS")

        log_and_print("╠" + "═"*58 + "╣", "SUCCESS")
        log_and_print(f"║ {'TOTAL':30} │ {total_processed:3} symbols │ 100.0%", "SUCCESS")
        log_and_print("╚" + "═"*58 + "╝\n", "SUCCESS")

        return True

    except Exception as e:
        log_and_print("\n" + "╔" + "═"*58 + "╗", "CRITICAL")
        log_and_print("║                    💥 SYSTEM ERROR                            ║", "CRITICAL")
        log_and_print("╠" + "═"*58 + "╣", "CRITICAL")
        log_and_print(f"║ {str(e):56}", "CRITICAL")
        log_and_print("╚" + "═"*58 + "╝\n", "CRITICAL")
        traceback.print_exc()
        return False


def main_once():
    """Main execution function - single run."""
    log_and_print("\n" + "┌" + "─"*58 + "┐", "INFO")
    log_and_print("│                 🔄 SYNAREX DATA PIPELINE                   │", "INFO")
    log_and_print("│                                                          │", "INFO")
    log_and_print("│  Loop Mode: DISABLED                                     │", "INFO")
    log_and_print("└" + "─"*58 + "┘\n", "INFO")

    success = fetch_charts_all_brokers()

    if success:
        log_and_print("\n" + "┌" + "─"*58 + "┐", "SUCCESS")
        log_and_print("│                   ✅ PIPELINE COMPLETED                     │", "SUCCESS")
        log_and_print("├" + "─"*58 + "┤", "SUCCESS")
        log_and_print("│ • All candle data saved to candle_records.json               │", "SUCCESS")
        log_and_print("│ • All available bars fetched per symbol/timeframe            │", "SUCCESS")
        log_and_print("│ • `symbols` + `timeframes` refreshed in developers.json      │", "SUCCESS")
        log_and_print("└" + "─"*58 + "┘\n", "SUCCESS")
    else:
        log_and_print("\n" + "┌" + "─"*58 + "┐", "ERROR")
        log_and_print("│                   PIPELINE FAILED                        │", "ERROR")
        log_and_print("├" + "─"*58 + "┤", "ERROR")
        log_and_print("│ Check error log for details                                  │", "ERROR")
        log_and_print("└" + "─"*58 + "┘\n", "ERROR")


if __name__ == "__main__":
    main_once()