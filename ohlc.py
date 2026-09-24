import os
import numpy as np
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta
import pytz
import json
import time
import traceback
import re
import multiprocessing

AFRICA_TZ = pytz.timezone('Africa/Lagos')

BASE_ERROR_FOLDER = r"C:\xampp\htdocs\harvcore\harvox\invharv\usersdata\debugs"
BROKERS_JSON_PATH = r"C:\xampp\htdocs\harvcore\harvox\invharv\usersdata\developers\developers.json"
OHLC_FOLDER = r"C:\xampp\htdocs\harvcore\harvox\invharv\usersdata\developers"
MAX_TERMINALS_PER_DEVELOPER = 5

FULL_PROBE_ORDER = [1000000, 500000, 200000, 100000, 50000, 20000, 10000, 5000, 1000]
INCR_PROBE_ORDER = [1000, 5000, 10000, 20000, 50000, 100000, 200000]

FUTURE_TOLERANCE_HARD_SECONDS = 300

# Grid-alignment only enforced for intraday timeframes ≤ 1h. Larger TFs
# are anchored to broker session hours, not epoch 0, so the check
# produces false negatives (which is why every 4h and 1d bar was
# rejected as `invalid` in your log).
GRID_CHECK_TIMEFRAMES = {
    "1m", "2m", "3m", "4m", "5m", "6m",
    "10m", "12m", "15m", "20m", "30m", "1h",
}

MAX_HISTORY_BARS = {
    "1m": 200000, "2m": 150000, "3m": 120000, "4m": 100000, "5m": 100000,
    "6m": 80000, "10m": 60000, "12m": 50000, "15m": 60000, "20m": 40000,
    "30m": 40000, "1h": 30000, "2h": 20000, "3h": 15000, "4h": 15000,
    "6h": 10000, "8h": 8000, "12h": 6000, "1d": 5000, "1w": 2000, "1mo": 500,
}

TIMEFRAME_MAP = {
    "1m":  mt5.TIMEFRAME_M1,  "2m":  mt5.TIMEFRAME_M2,  "3m":  mt5.TIMEFRAME_M3,
    "4m":  mt5.TIMEFRAME_M4,  "5m":  mt5.TIMEFRAME_M5,  "6m":  mt5.TIMEFRAME_M6,
    "10m": mt5.TIMEFRAME_M10, "12m": mt5.TIMEFRAME_M12, "15m": mt5.TIMEFRAME_M15,
    "20m": mt5.TIMEFRAME_M20, "30m": mt5.TIMEFRAME_M30,
    "1h":  mt5.TIMEFRAME_H1,  "2h":  mt5.TIMEFRAME_H2,  "3h":  mt5.TIMEFRAME_H3,
    "4h":  mt5.TIMEFRAME_H4,  "6h":  mt5.TIMEFRAME_H6,  "8h":  mt5.TIMEFRAME_H8,
    "12h": mt5.TIMEFRAME_H12, "1d":  mt5.TIMEFRAME_D1,  "1w":  mt5.TIMEFRAME_W1,
    "1mo": mt5.TIMEFRAME_MN1,
}

TIMEFRAME_SECONDS = {
    "1m": 60, "2m": 120, "3m": 180, "4m": 240, "5m": 300, "6m": 360,
    "10m": 600, "12m": 720, "15m": 900, "20m": 1200, "30m": 1800,
    "1h": 3600, "2h": 7200, "3h": 10800, "4h": 14400, "6h": 21600,
    "8h": 28800, "12h": 43200, "1d": 86400, "1w": 604800, "1mo": 2592000,
}

ERROR_JSON_PATH = os.path.join(BASE_ERROR_FOLDER, "chart_errors.json")


# ==============================================================================
#  TIME HELPERS
# ==============================================================================
def now_africa():
    return datetime.now(AFRICA_TZ).replace(tzinfo=None)


def now_africa_aware():
    return datetime.now(AFRICA_TZ)


def _naive_africa_to_epoch(dt_naive):
    return int(dt_naive.replace(tzinfo=pytz.utc).timestamp())


def _current_candle_open_time(timeframe_key, now_dt=None):
    if now_dt is None:
        now_dt = now_africa()
    secs = TIMEFRAME_SECONDS.get(timeframe_key)
    if not secs:
        return None
    epoch = int(now_dt.replace(tzinfo=pytz.utc).timestamp())
    bucket = (epoch // secs) * secs
    return datetime.utcfromtimestamp(bucket)


def _future_tolerance_seconds(timeframe_key):
    tf_sec = TIMEFRAME_SECONDS.get(timeframe_key, 60)
    return max(tf_sec, FUTURE_TOLERANCE_HARD_SECONDS)


class CaseInsensitiveDict:
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


def log_and_print(message, level="INFO"):
    timestamp = now_africa_aware().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {level:8} | {message}", flush=True)


def _extract_terminal_paths(user_config):
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


# ==============================================================================
#  CANDLE VALIDATION
# ==============================================================================
def _parse_ts(ts_str):
    if not isinstance(ts_str, str):
        return None
    s = ts_str.strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _validate_candle(candle, timeframe, now_af, reference_ts=None):
    if not isinstance(candle, dict):
        return False, "not_a_dict"
    for k in ("timestamp", "open", "high", "low", "close"):
        if k not in candle:
            return False, f"missing_{k}"

    ts = _parse_ts(candle["timestamp"])
    if ts is None:
        return False, "bad_timestamp"

    if ts > now_af + timedelta(seconds=_future_tolerance_seconds(timeframe)):
        return False, "future_bar"

    try:
        o = float(candle["open"]); h = float(candle["high"])
        l = float(candle["low"]); c = float(candle["close"])
    except (TypeError, ValueError):
        return False, "non_numeric_ohlc"

    for v, name in ((o, "open"), (h, "high"), (l, "low"), (c, "close")):
        if not np.isfinite(v):
            return False, f"non_finite_{name}"
        if v <= 0:
            return False, f"non_positive_{name}"

    if h < l:
        return False, "high_below_low"
    if h < max(o, c) - 1e-12:
        return False, "high_below_body"
    if l > min(o, c) + 1e-12:
        return False, "low_above_body"

    # Grid alignment: only for intraday TFs ≤ 1h. Larger TFs are anchored
    # to broker session hours (e.g. 4h bars at 01:00, 05:00, ...) and would
    # always fail an epoch-modulo check.
    if timeframe in GRID_CHECK_TIMEFRAMES:
        secs = TIMEFRAME_SECONDS.get(timeframe)
        if secs:
            if ts.second != 0:
                return False, "not_grid_aligned"
            epoch = int(ts.replace(tzinfo=pytz.utc).timestamp())
            if epoch % secs != 0:
                return False, "not_grid_aligned"

    if reference_ts is not None:
        max_bars = MAX_HISTORY_BARS.get(timeframe, 200000)
        secs = TIMEFRAME_SECONDS.get(timeframe, 60)
        max_age_seconds = max_bars * secs
        if (reference_ts - ts).total_seconds() > max_age_seconds:
            return False, "too_old"

    return True, "ok"


def _sanitize_candle_list(candles, timeframe, now_af, symbol_label=""):
    stats = {"total": 0, "kept": 0, "dropped_future": 0, "dropped_invalid": 0,
             "dropped_out_of_range": 0, "dropped_duplicates": 0}
    if not isinstance(candles, list) or not candles:
        return [], stats
    stats["total"] = len(candles)

    prelim = []
    for c in candles:
        ok, reason = _validate_candle(c, timeframe, now_af, reference_ts=None)
        if ok:
            prelim.append(c)
        else:
            if reason == "future_bar":
                stats["dropped_future"] += 1
            else:
                stats["dropped_invalid"] += 1

    if not prelim:
        return [], stats

    prelim_ts = [(_parse_ts(c["timestamp"]), c) for c in prelim]
    prelim_ts = [(t, c) for t, c in prelim_ts if t is not None]
    if not prelim_ts:
        return [], stats
    newest_ts = max(t for t, _ in prelim_ts)

    kept = []
    for t, c in prelim_ts:
        ok, reason = _validate_candle(c, timeframe, now_af, reference_ts=newest_ts)
        if ok:
            kept.append((t, c))
        else:
            if reason == "too_old":
                stats["dropped_out_of_range"] += 1
            elif reason == "future_bar":
                stats["dropped_future"] += 1
            else:
                stats["dropped_invalid"] += 1

    dedup = {}
    for t, c in kept:
        if t in dedup:
            stats["dropped_duplicates"] += 1
        dedup[t] = c

    clean = [dedup[t] for t in sorted(dedup.keys())]
    stats["kept"] = len(clean)

    if any(stats[k] for k in ("dropped_future", "dropped_invalid",
                              "dropped_out_of_range", "dropped_duplicates")):
        log_and_print(
            f"  🧹 SANITIZE [{symbol_label}] tf={timeframe} — "
            f"total={stats['total']} kept={stats['kept']} | "
            f"future={stats['dropped_future']} invalid={stats['dropped_invalid']} "
            f"too_old={stats['dropped_out_of_range']} dupes={stats['dropped_duplicates']}",
            "WARNING"
        )
    return clean, stats


# ==============================================================================
#  DEVELOPERS.JSON HELPERS
# ==============================================================================
def _parse_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s or s.upper() == "NULL":
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def load_latest_recorded_map():
    result = {}
    if not os.path.exists(BROKERS_JSON_PATH):
        return result
    try:
        with open(BROKERS_JSON_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        log_and_print(f"Could not read developers.json: {e}", "WARNING")
        return result

    now_af = now_africa()
    for user_id, cfg in data.items():
        if not isinstance(cfg, dict):
            continue
        records = cfg.get("last_symbol_tf_time_candle_record")
        if not isinstance(records, list):
            continue
        for entry in records:
            if not isinstance(entry, dict):
                continue
            sym = entry.get("symbol"); tf = entry.get("timeframe")
            if not sym or not tf:
                continue
            dt = _parse_dt(entry.get("latest_recorded_candle"))
            if dt is None:
                continue
            if dt > now_af + timedelta(seconds=_future_tolerance_seconds(str(tf))):
                log_and_print(
                    f"  🧹 Rejecting future latest_recorded in developers.json: "
                    f"user={user_id} {sym} {tf} = {dt}",
                    "WARNING"
                )
                continue
            result[(str(user_id), str(sym).strip(), str(tf).strip())] = dt

    log_and_print(f"  📚 Loaded {len(result)} latest-recorded-candle entries", "INFO")
    return result


def save_latest_recorded_map(user_id, updated_entries):
    if not updated_entries:
        return True
    max_retries = 5
    delay = 0.5
    for attempt in range(max_retries):
        try:
            if not os.path.exists(BROKERS_JSON_PATH):
                return False
            with open(BROKERS_JSON_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            real_key = next((k for k in data.keys() if str(k) == str(user_id)), None)
            if real_key is None:
                return False
            cfg = data[real_key]
            existing = cfg.get("last_symbol_tf_time_candle_record")
            if not isinstance(existing, list):
                existing = []
            index = {}
            for entry in existing:
                if isinstance(entry, dict) and entry.get("symbol") and entry.get("timeframe"):
                    index[(str(entry["symbol"]).strip(), str(entry["timeframe"]).strip())] = entry
            for ne in updated_entries:
                sym = str(ne.get("symbol", "")).strip()
                tf = str(ne.get("timeframe", "")).strip()
                lrct = ne.get("latest_recorded_candle")
                if not sym or not tf or not lrct:
                    continue
                index[(sym, tf)] = {"symbol": sym, "timeframe": tf, "latest_recorded_candle": lrct}
            cfg["last_symbol_tf_time_candle_record"] = sorted(
                index.values(), key=lambda x: (x["symbol"], x["timeframe"])
            )
            tmp_path = BROKERS_JSON_PATH + ".tmp"
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, BROKERS_JSON_PATH)
            return True
        except Exception as e:
            log_and_print(f"  ⚠️ persist attempt {attempt+1}/{max_retries}: {e}", "WARNING")
            time.sleep(delay); delay *= 2
    return False


def load_ohlc_dictionary():
    if not os.path.exists(BROKERS_JSON_PATH):
        log_and_print(f"CRITICAL: {BROKERS_JSON_PATH} NOT FOUND!", "CRITICAL")
        return {}
    try:
        with open(BROKERS_JSON_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        transformed_data = {}
        for user_id, user_config in data.items():
            ci_config = CaseInsensitiveDict(user_config)
            login = (ci_config.get("login") or ci_config.get("LOGIN_ID")
                     or ci_config.get("login_id") or ci_config.get("loginId") or "")
            broker_password = (ci_config.get("broker_password") or ci_config.get("BROKER_PASSWORD")
                               or ci_config.get("brokerPassword") or "")
            server = ci_config.get("server") or ci_config.get("SERVER") or ci_config.get("Server") or ""
            broker_name = (ci_config.get("broker") or ci_config.get("BROKER")
                           or ci_config.get("Broker") or "deriv")

            raw_terminal_matches = _extract_terminal_paths(user_config)
            terminal_paths = []
            for raw_key, val, order in raw_terminal_matches:
                if os.path.exists(val):
                    terminal_paths.append((raw_key, val))
                else:
                    log_and_print(f"WARNING: {raw_key} file not found: {val}", "WARNING")

            selected_symbols = ci_config.get("selected_symbols") or ci_config.get("SELECTED_SYMBOLS")
            if not isinstance(selected_symbols, list):
                selected_symbols = []

            selected_timeframes = ci_config.get("selected_timeframes") or ci_config.get("SELECTED_TIMEFRAMES")
            if not isinstance(selected_timeframes, list) or not selected_timeframes:
                selected_timeframes = ["15m", "5m", "30m", "1h", "4h"]

            valid_timeframes = [tf for tf in selected_timeframes if tf in TIMEFRAME_MAP]
            if not valid_timeframes:
                valid_timeframes = ["15m", "5m", "30m", "1h", "4h"]

            base_folder = os.path.join(OHLC_FOLDER, str(user_id))
            if not terminal_paths:
                continue

            if len(selected_symbols) == 0:
                for idx, (raw_key, tp) in enumerate(terminal_paths, 1):
                    account_key = f"__metadata_only__{user_id}_terminal_{idx}"
                    transformed_data[account_key] = {
                        "LOGIN_ID": str(login), "broker_password": str(broker_password),
                        "SERVER": str(server), "BASE_FOLDER": base_folder,
                        "terminal_path": tp, "terminal_field": raw_key,
                        "USER_ID": str(user_id), "BROKER_NAME": str(broker_name),
                        "SYMBOLS_DICTIONARY": {}, "OHLC_TIMEFRAMES": valid_timeframes,
                        "SELECTED_SYMBOLS": [], "METADATA_ONLY": True,
                    }
                continue

            num_developers = len(data)
            terminals_to_use = (terminal_paths if num_developers == 1
                                else terminal_paths[:MAX_TERMINALS_PER_DEVELOPER])
            for idx, (raw_key, tp) in enumerate(terminals_to_use, 1):
                account_key = f"{broker_name.lower()}_{user_id}_terminal_{idx}"
                transformed_data[account_key] = {
                    "LOGIN_ID": str(login), "broker_password": str(broker_password),
                    "SERVER": str(server), "BASE_FOLDER": base_folder,
                    "terminal_path": tp, "terminal_field": raw_key,
                    "USER_ID": str(user_id), "BROKER_NAME": str(broker_name),
                    "SYMBOLS_DICTIONARY": {}, "OHLC_TIMEFRAMES": valid_timeframes,
                    "SELECTED_SYMBOLS": selected_symbols, "METADATA_ONLY": False,
                }
        log_and_print(f"Loaded {len(transformed_data)} configs", "SUCCESS")
        return transformed_data
    except Exception as e:
        log_and_print(f"Failed to load developers.json: {e}", "CRITICAL")
        traceback.print_exc()
        return {}


ohlcdictionary = load_ohlc_dictionary()


def initialize_mt5(terminal_path, login_id, broker_password, server):
    if not terminal_path or not os.path.exists(terminal_path):
        log_and_print(f"MT5 exe not found: {terminal_path}", "ERROR")
        return False
    try:
        try:
            login_int = int(login_id)
        except (ValueError, TypeError):
            log_and_print(f"Invalid login ID: {login_id}", "ERROR")
            return False
        if not mt5.initialize(path=terminal_path, login=login_int, server=server,
                              password=broker_password, timeout=30000):
            log_and_print(f"MT5 initialize failed: {mt5.last_error()}", "ERROR")
            return False
        if not mt5.login(login=login_int, server=server, password=broker_password):
            log_and_print(f"MT5 login failed: {mt5.last_error()}", "ERROR")
            mt5.shutdown()
            return False
        return True
    except Exception as e:
        log_and_print(f"Unexpected error in initialize_mt5: {str(e)}", "ERROR")
        return False


def _ensure_symbol_selected(symbol, retries=3):
    for _ in range(retries):
        if mt5.symbol_select(symbol, True):
            return True
        time.sleep(0.3)
    return False


def _rates_to_df(rates):
    if rates is None:
        return None
    if isinstance(rates, np.ndarray):
        if rates.size == 0:
            return None
        arr = rates
    else:
        if len(rates) == 0:
            return None
        first = rates[0]
        if hasattr(first, "dtype") and getattr(first.dtype, "names", None):
            arr = np.array(rates, dtype=first.dtype)
        else:
            arr = np.array(rates)

    names = arr.dtype.names
    if names is None:
        raise RuntimeError(f"_rates_to_df: no named fields (dtype={arr.dtype})")

    data = {n: arr[n] for n in names}
    df = pd.DataFrame(data)
    df["time"] = pd.to_datetime(df["time"], unit="s") + pd.Timedelta(hours=1)
    df = df.set_index("time")

    cast_map = {"open": float, "high": float, "low": float, "close": float,
                "tick_volume": float, "spread": int, "real_volume": float}
    df = df.astype({k: v for k, v in cast_map.items() if k in df.columns})
    if "tick_volume" in df.columns:
        df.rename(columns={"tick_volume": "volume"}, inplace=True)
    return df


def _probe_rates(symbol, mt5_timeframe, order):
    attempted = []
    for count in order:
        try:
            rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, count)
        except Exception as e:
            attempted.append((count, f"exception: {e}"))
            continue
        if rates is not None and len(rates) > 0:
            return rates, count, attempted
        attempted.append((count, "empty"))
    return None, None, attempted


def fetch_all_ohlcv_data(symbol, mt5_timeframe, tf_label="?"):
    if not _ensure_symbol_selected(symbol):
        log_and_print(f"  ❌ FULL-FETCH [{symbol} {tf_label}] symbol_select failed: {mt5.last_error()}", "ERROR")
        return None

    rates, used_count, attempted = _probe_rates(symbol, mt5_timeframe, FULL_PROBE_ORDER)
    if rates is None:
        log_and_print(f"  ❌ FULL-FETCH [{symbol} {tf_label}] no bars. Probes: {attempted}", "ERROR")
        return None

    now_af = now_africa()
    df = _rates_to_df(rates)
    if df is None or df.empty:
        return None

    raw_count = len(df)
    raw_last = df.index.max()
    df = df[df.index <= now_af + timedelta(seconds=_future_tolerance_seconds(tf_label))]

    if df.empty:
        log_and_print(f"  ❌ FULL-FETCH [{symbol} {tf_label}] all {raw_count} bars were in the future", "ERROR")
        return None

    log_and_print(
        f"  ✅ FULL-FETCH [{symbol} {tf_label}] {len(df)} bars via probe={used_count} "
        f"({df.index.min()} → {df.index.max()})  [raw={raw_count}, raw_last={raw_last}]",
        "SUCCESS"
    )
    return df


def fetch_incremental_ohlcv(symbol, mt5_timeframe, timeframe_key, latest_recorded_dt):
    tag = f"{symbol} {timeframe_key}"
    if not _ensure_symbol_selected(symbol):
        log_and_print(f"  ❌ INCR [{tag}] symbol_select failed: {mt5.last_error()}", "ERROR")
        return None

    tf_sec = TIMEFRAME_SECONDS.get(timeframe_key, 60)
    now_af = now_africa()

    from_dt = latest_recorded_dt - timedelta(seconds=tf_sec)
    to_dt = now_af + timedelta(seconds=tf_sec)
    from_epoch = _naive_africa_to_epoch(from_dt)
    to_epoch = _naive_africa_to_epoch(to_dt)

    rates = None
    used = None
    if hasattr(mt5, "copy_rates_range"):
        try:
            rates = mt5.copy_rates_range(symbol, mt5_timeframe, from_epoch, to_epoch)
            if rates is not None and len(rates) > 0:
                used = f"range=({from_epoch}, {to_epoch})"
            else:
                rates = None
        except Exception as e:
            log_and_print(f"  ⚠️ INCR [{tag}] copy_rates_range raised: {e}", "WARNING")
            rates = None

    if rates is None:
        rates, used_count, attempted = _probe_rates(symbol, mt5_timeframe, INCR_PROBE_ORDER)
        if rates is None:
            log_and_print(f"  ❌ INCR [{tag}] no bars. Probes: {attempted}", "ERROR")
            return None
        used = f"probe={used_count}"

    df = _rates_to_df(rates)
    if df is None or df.empty:
        return None

    raw_count = len(df)
    raw_first = df.index.min()
    raw_last = df.index.max()

    df = df[df.index <= now_af + timedelta(seconds=_future_tolerance_seconds(timeframe_key))]
    df = df[df.index > latest_recorded_dt]

    log_and_print(
        f"  🔍 INCR [{tag}] {used} | raw={raw_count} bars [{raw_first} → {raw_last}] | "
        f"threshold={latest_recorded_dt} | now={now_af}",
        "INFO"
    )

    if df.empty:
        log_and_print(f"  ⏸️  INCR [{tag}] nothing left after filter", "WARNING")
        return None

    log_and_print(f"  ✅ INCR [{tag}] kept {len(df)} bar(s) ({df.index.min()} → {df.index.max()})", "SUCCESS")
    return df


# ==============================================================================
#  CANDLE DICT
# ==============================================================================
def _candle_to_dict(symbol, timeframe, idx, row):
    o = float(row['open']); h = float(row['high']); l = float(row['low']); c = float(row['close'])
    tf_sec = TIMEFRAME_SECONDS.get(timeframe, 60)
    open_dt = idx
    close_dt = idx + timedelta(seconds=tf_sec)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "timestamp": idx.strftime('%Y-%m-%d %H:%M:%S'),
        "open_time":  open_dt.strftime('%Y-%m-%d %H:%M:%S'),
        "close_time": close_dt.strftime('%Y-%m-%d %H:%M:%S'),
        "high_time":  None,
        "low_time":   None,
        "open": o, "high": h, "low": l, "close": c,
        "volume": float(row['volume']),
        "candle_center": (h + l) / 2.0,
        "body_center": (o + c) / 2.0,
        "high_wick_center": (h + c) / 2.0,
        "low_wick_center": (l + o) / 2.0 if c >= o else (c + l) / 2.0,
        "candle_width_center": (h - l) / 2.0,
    }


def _backfill_open_close_fields(candle, timeframe):
    tf_sec = TIMEFRAME_SECONDS.get(timeframe, 60)
    ts = _parse_ts(candle.get("timestamp", ""))
    if ts is not None:
        if "open_time" not in candle or not candle["open_time"]:
            candle["open_time"] = ts.strftime('%Y-%m-%d %H:%M:%S')
        if "close_time" not in candle or not candle["close_time"]:
            close_dt = ts + timedelta(seconds=tf_sec)
            candle["close_time"] = close_dt.strftime('%Y-%m-%d %H:%M:%S')
    if "high_time" not in candle:
        candle["high_time"] = None
    if "low_time" not in candle:
        candle["low_time"] = None


# ==============================================================================
#  SAVE
# ==============================================================================
def save_candle_records(user_id, symbol, timeframe, df):
    if df is None or df.empty:
        return 0, None

    path = os.path.join(OHLC_FOLDER, str(user_id), "candle_records.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    all_data = {}
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                all_data = json.load(f)
            if not isinstance(all_data, dict):
                all_data = {}
        except (json.JSONDecodeError, IOError) as e:
            log_and_print(f"  ⚠️  Could not read candle_records.json: {e}", "WARNING")
            all_data = {}

    now_af = now_africa()

    existing = all_data.get(symbol)
    if not isinstance(existing, list):
        existing = []

    existing_for_tf = [c for c in existing
                       if isinstance(c, dict) and c.get("timeframe") == timeframe]
    existing_other_tfs = [c for c in existing
                          if isinstance(c, dict) and c.get("timeframe") != timeframe]

    for c in existing_for_tf:
        _backfill_open_close_fields(c, timeframe)

    clean_existing_tf, stats_before = _sanitize_candle_list(
        existing_for_tf, timeframe, now_af, symbol
    )

    for c in existing_other_tfs:
        if isinstance(c, dict):
            other_tf = c.get("timeframe")
            if other_tf in TIMEFRAME_SECONDS:
                _backfill_open_close_fields(c, other_tf)
    other_clean = [c for c in existing_other_tfs if isinstance(c, dict)]

    new_candles = [_candle_to_dict(symbol, timeframe, idx, row) for idx, row in df.iterrows()]

    combined = clean_existing_tf + new_candles
    clean_merged_tf, stats_after = _sanitize_candle_list(combined, timeframe, now_af, symbol)

    before_ts = {c["timestamp"] for c in clean_existing_tf}
    after_ts = {c["timestamp"] for c in clean_merged_tf}
    new_count = len(after_ts - before_ts)

    final_list = clean_merged_tf + other_clean
    final_list.sort(key=lambda c: c.get("timestamp", ""))

    if not final_list:
        if symbol in all_data:
            del all_data[symbol]
    else:
        all_data[symbol] = final_list

    try:
        tmp = path + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(all_data, f, indent=4)
        os.replace(tmp, path)

        matching_tf = [c for c in clean_merged_tf]
        newest_clean_dt = max(
            (_parse_ts(c["timestamp"]) for c in matching_tf),
            default=None
        )

        log_and_print(
            f"  💾 Saved {new_count} new candle(s) for {symbol} ({timeframe}); "
            f"tf_total={len(clean_merged_tf)} symbol_total={len(final_list)} | "
            f"removed: future={stats_after['dropped_future']} "
            f"invalid={stats_after['dropped_invalid']} "
            f"too_old={stats_after['dropped_out_of_range']} "
            f"dupes={stats_after['dropped_duplicates']}",
            "SUCCESS"
        )
        return new_count, newest_clean_dt
    except Exception as e:
        log_and_print(f"  ❌ Failed to save candle_records.json: {str(e)}", "ERROR")
        return 0, None


def update_available_symbols(user_id, available_symbols):
    try:
        if not os.path.exists(BROKERS_JSON_PATH):
            return False
        with open(BROKERS_JSON_PATH, 'r', encoding='utf-8') as f:
            dd = json.load(f)
        real_key = next((k for k in dd.keys() if str(k) == str(user_id)), None)
        if real_key is None:
            return False
        dd[real_key]["symbols"] = available_symbols
        tmp = BROKERS_JSON_PATH + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(dd, f, indent=4, ensure_ascii=False)
        os.replace(tmp, BROKERS_JSON_PATH)
        log_and_print(f"  ✅ Updated developers.json with {len(available_symbols)} symbols for user {user_id}", "SUCCESS")
        return True
    except Exception as e:
        log_and_print(f"ERROR updating developers.json: {str(e)}", "ERROR")
        return False


def _probe_timeframes_for_broker(available_symbols_set, sample_size=5):
    if not available_symbols_set:
        return []
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
    for tf_key, tf_const in TIMEFRAME_MAP.items():
        for sym in probes:
            try:
                if not mt5.symbol_select(sym, True):
                    continue
                rates = mt5.copy_rates_from_pos(sym, tf_const, 0, 5)
                if rates is not None and len(rates) > 0:
                    supported.append(tf_key)
                    break
            except Exception:
                continue
    return [tf for tf in TIMEFRAME_MAP.keys() if tf in supported]


def update_available_timeframes(user_id, available_timeframes):
    try:
        if not os.path.exists(BROKERS_JSON_PATH):
            return False
        with open(BROKERS_JSON_PATH, 'r', encoding='utf-8') as f:
            dd = json.load(f)
        real_key = next((k for k in dd.keys() if str(k) == str(user_id)), None)
        if real_key is None:
            return False
        dd[real_key]["timeframes"] = available_timeframes
        tmp = BROKERS_JSON_PATH + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(dd, f, indent=4, ensure_ascii=False)
        os.replace(tmp, BROKERS_JSON_PATH)
        log_and_print(f"  ✅ Updated developers.json with {len(available_timeframes)} timeframes for user {user_id}", "SUCCESS")
        return True
    except Exception as e:
        log_and_print(f"ERROR updating developers.json (timeframes): {str(e)}", "ERROR")
        return False


def process_account_worker(account_key, account_cfg, symbol_chunk, result_dict):
    processed_count = 0
    user_timeframes = account_cfg.get("OHLC_TIMEFRAMES", ["15m", "5m", "30m", "1h", "4h"])
    user_id = account_cfg.get("USER_ID", "unknown")
    metadata_only = bool(account_cfg.get("METADATA_ONLY", False))

    user_timeframe_map = {tf: TIMEFRAME_MAP[tf] for tf in user_timeframes if tf in TIMEFRAME_MAP}
    if not user_timeframe_map:
        user_timeframe_map = {tf: TIMEFRAME_MAP[tf] for tf in ["15m", "5m", "30m", "1h", "4h"]}

    symbols_to_process = [(item, "selected") if isinstance(item, str) else item for item in symbol_chunk]

    log_and_print(f"\n  ⚙️  {account_key.upper()} | Starting | {len(symbols_to_process)} symbols", "INFO")

    if not initialize_mt5(account_cfg["terminal_path"], account_cfg["LOGIN_ID"],
                          account_cfg["broker_password"], account_cfg["SERVER"]):
        result_dict[account_key] = 0
        return

    all_symbols = mt5.symbols_get()
    if all_symbols:
        broker_symbols = [s.name for s in all_symbols]
        available_symbols_set = set(broker_symbols)
        log_and_print(f"  ✅ Total symbols available: {len(broker_symbols)}", "SUCCESS")
        update_available_symbols(user_id, broker_symbols)
        try:
            supported_tfs = _probe_timeframes_for_broker(available_symbols_set, sample_size=5)
            if supported_tfs:
                update_available_timeframes(user_id, supported_tfs)
        except Exception as tf_err:
            log_and_print(f"  ⚠️ Timeframe probe failed: {tf_err}", "WARNING")

        if metadata_only:
            mt5.shutdown()
            result_dict[account_key] = 0
            return

        filtered = []
        for sym_item, cat in symbols_to_process:
            name = sym_item
            matched = None
            if name in available_symbols_set:
                matched = name
            else:
                for a in available_symbols_set:
                    if a.upper() == name.upper():
                        matched = a; break
            if matched:
                filtered.append((matched, cat))
        symbols_to_process = filtered
    mt5.shutdown()

    if not symbols_to_process:
        result_dict[account_key] = 0
        return

    latest_map = load_latest_recorded_map()
    pending_updates = []

    for symbol, cat in symbols_to_process:
        if not initialize_mt5(account_cfg["terminal_path"], account_cfg["LOGIN_ID"],
                              account_cfg["broker_password"], account_cfg["SERVER"]):
            continue
        try:
            log_and_print(f"  📈 {account_key.upper()} | Processing | {symbol} ({cat})", "INFO")
            _ensure_symbol_selected(symbol)

            for tf_str, mt5_tf in user_timeframe_map.items():
                now_af = now_africa()
                current_open = _current_candle_open_time(tf_str, now_af)
                latest_dt = latest_map.get((str(user_id), symbol, tf_str))

                if latest_dt is None:
                    log_and_print(
                        f"  🧭 {account_key.upper()} | {symbol} {tf_str} | "
                        f"now={now_af} | current_candle_open={current_open} | "
                        f"latest_recorded=None → FULL FETCH",
                        "INFO"
                    )
                    df = fetch_all_ohlcv_data(symbol, mt5_tf, tf_str)
                else:
                    gap_seconds = (now_af - latest_dt).total_seconds()
                    expected_new = max(0, int(gap_seconds // TIMEFRAME_SECONDS.get(tf_str, 60)))
                    log_and_print(
                        f"  🧭 {account_key.upper()} | {symbol} {tf_str} | "
                        f"now={now_af} | current_candle_open={current_open} | "
                        f"latest_recorded={latest_dt} | Expected New ≈ {expected_new} Bars",
                        "INFO"
                    )
                    if current_open is not None and latest_dt >= current_open:
                        log_and_print(f"  ⏭️  {account_key.upper()} | {symbol} {tf_str} up-to-date", "INFO")
                        continue
                    df = fetch_incremental_ohlcv(symbol, mt5_tf, tf_str, latest_dt)

                if df is None or df.empty:
                    continue

                new_count, newest_clean_dt = save_candle_records(user_id, symbol, tf_str, df)

                if newest_clean_dt is None:
                    log_and_print(
                        f"  ⚠️  {account_key.upper()} | {symbol} {tf_str} — no clean bars in file after save",
                        "WARNING"
                    )
                    continue

                if newest_clean_dt > now_af + timedelta(seconds=_future_tolerance_seconds(tf_str)):
                    log_and_print(
                        f"  🧹 newest_clean_dt={newest_clean_dt} is still future for {symbol} {tf_str}; skipping persist",
                        "WARNING"
                    )
                    continue

                latest_map[(str(user_id), symbol, tf_str)] = newest_clean_dt
                pending_updates.append({
                    "symbol": symbol, "timeframe": tf_str,
                    "latest_recorded_candle": newest_clean_dt.strftime('%Y-%m-%d %H:%M:%S'),
                })

            processed_count += 1
            log_and_print(f"  ✅ {account_key.upper()} | Completed | {symbol}", "SUCCESS")
        except Exception as e:
            log_and_print(f"   {account_key.upper()} | Error on {symbol}: {str(e)[:120]}", "ERROR")
            traceback.print_exc()
        finally:
            mt5.shutdown()

    if pending_updates:
        save_latest_recorded_map(user_id, pending_updates)
        log_and_print(f"  💾 {account_key.upper()} | Persisted {len(pending_updates)} entries", "SUCCESS")

    result_dict[account_key] = processed_count
    log_and_print(f"  🏁 {account_key.upper()} | Finished | {processed_count} symbols processed", "SUCCESS")


def fetch_charts_all_brokers():
    log_and_print("🚀 MULTI-ACCOUNT SYNCHRONIZATION ENGINE", "INFO")
    if not ohlcdictionary:
        log_and_print("⚠️  No MT5 configurations found.", "ERROR")
        return False

    user_accounts = {}
    for acc_key, acc_cfg in ohlcdictionary.items():
        user_id = acc_cfg.get("USER_ID", "unknown")
        user_accounts.setdefault(user_id, []).append((acc_key, acc_cfg))

    manager = multiprocessing.Manager()
    final_counts = manager.dict()
    processes = []

    for user_id, accounts in user_accounts.items():
        is_metadata_only = all(bool(cfg.get("METADATA_ONLY", False)) for _, cfg in accounts)
        log_and_print(f"📋 USER {user_id} | {len(accounts)} terminals", "INFO")
        if is_metadata_only:
            for acc_key, acc_cfg in accounts:
                p = multiprocessing.Process(target=process_account_worker,
                                            args=(acc_key, acc_cfg, [], final_counts))
                processes.append(p); p.start()
            continue

        user_symbols = [s for s in (accounts[0][1].get("SELECTED_SYMBOLS", []) or [])
                        if isinstance(s, str) and s]
        log_and_print(f"  📊 USER {user_id} | Found {len(user_symbols)} selected symbols", "INFO")
        if not user_symbols:
            continue

        num_terminals = len(accounts)
        per = len(user_symbols) // num_terminals
        rem = len(user_symbols) % num_terminals
        start = 0
        for i, (acc_key, acc_cfg) in enumerate(accounts):
            end = start + per + (1 if i < rem else 0)
            chunk = user_symbols[start:end]
            start = end
            p = multiprocessing.Process(target=process_account_worker,
                                        args=(acc_key, acc_cfg, chunk, final_counts))
            processes.append(p); p.start()
            log_and_print(f"  └─ {acc_key} | {len(chunk)} symbols", "INFO")

    for p in processes:
        p.join()

    log_and_print("🏁 PROCESSING COMPLETE", "SUCCESS")
    return True


def main_once():
    log_and_print("🔄 SYNAREX DATA PIPELINE — Africa/Lagos", "INFO")
    fetch_charts_all_brokers()


if __name__ == "__main__":
    main_once()