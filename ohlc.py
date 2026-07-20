import os
import MetaTrader5 as mt5
import pandas as pd
import mplfinance as mpf
from datetime import datetime
import pytz
import json
from PIL import Image
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from datetime import datetime
import time
from datetime import timedelta
import traceback
import shutil
from datetime import datetime
import re
import multiprocessing
import os
import json
import time
import re
import sys


BASE_ERROR_FOLDER = r"C:\xampp\htdocs\harvcore\harvox\invharv\usersdata\debugs"
BROKERS_JSON_PATH = r"C:\xampp\htdocs\harvcore\harvox\invharv\usersdata\developers\developers.json"
OHLC_FOLDER = r"C:\xampp\htdocs\harvcore\harvox\invharv\usersdata\developers"
MAX_TERMINALS_PER_DEVELOPER = 5

# Default timeframe map - will be filtered per user
TIMEFRAME_MAP = {
    "5m": mt5.TIMEFRAME_M5,
    "15m": mt5.TIMEFRAME_M15,
    "30m": mt5.TIMEFRAME_M30,
    "1h": mt5.TIMEFRAME_H1,
    "2h": mt5.TIMEFRAME_H2,
    "4h": mt5.TIMEFRAME_H4
}
ERROR_JSON_PATH = os.path.join(BASE_ERROR_FOLDER, "chart_errors.json")

class CaseInsensitiveDict:
    """A dictionary that allows case-insensitive key access while preserving original keys."""
    def __init__(self, data=None):
        self._data = data or {}
        self._key_map = {k.lower(): k for k in self._data.keys()}
    
    def get(self, key, default=None):
        if key is None:
            return default
        key_lower = key.lower()
        if key_lower in self._key_map:
            return self._data[self._key_map[key_lower]]
        return default
    
    def get_all(self):
        return self._data
    
    def get_key_insensitive(self, key):
        if key is None:
            return None
        key_lower = key.lower()
        return self._key_map.get(key_lower)
    
    def __contains__(self, key):
        if key is None:
            return False
        return key.lower() in self._key_map
    
    def __getitem__(self, key):
        if key is None:
            raise KeyError("None key")
        key_lower = key.lower()
        if key_lower in self._key_map:
            return self._data[self._key_map[key_lower]]
        raise KeyError(key)

def log_and_print(message, level="INFO"):
    """Log and print messages in a structured format."""
    timestamp = datetime.now(pytz.timezone('Africa/Lagos')).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {level:8} | {message}")
    
def load_ohlc_dictionary():
    """Load brokers config from JSON file with case-insensitive field handling."""
    
    if not os.path.exists(BROKERS_JSON_PATH):
        print(f"CRITICAL: {BROKERS_JSON_PATH} NOT FOUND! Using empty config.", "CRITICAL")
        return {}

    try:
        with open(BROKERS_JSON_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        transformed_data = {}
        
        for user_id, user_config in data.items():
            # Create case-insensitive wrapper for user config
            ci_config = CaseInsensitiveDict(user_config)
            
            # Extract login credentials with case-insensitive lookups
            login = ci_config.get("login") or ci_config.get("LOGIN_ID") or ci_config.get("Login") or ""
            password = ci_config.get("password") or ci_config.get("PASSWORD") or ci_config.get("Password") or ""
            server = ci_config.get("server") or ci_config.get("SERVER") or ci_config.get("Server") or ""
            broker_name = ci_config.get("broker") or ci_config.get("BROKER") or ci_config.get("Broker") or "deriv"
            
            # Clean up server name
            if server and server.lower().startswith('derivsvg'):
                if 'derivsvg' in server.lower():
                    server = server.replace('derivsvg', 'DerivSVG')
            
            # Collect ALL terminal paths that exist (don't break on first missing)
            terminal_paths = []
            terminal_counter = 1
            
            # Keep looking for terminal_path_1, terminal_path_2, etc. until we find a missing one
            while True:
                terminal_key = f"terminal_path_{terminal_counter}"
                terminal_path = None
                
                # Check various possible keys
                if terminal_key in user_config:
                    terminal_path = user_config[terminal_key]
                elif terminal_key.lower() in user_config:
                    terminal_path = user_config[terminal_key.lower()]
                elif f"terminal_path_{terminal_counter}" in user_config:
                    terminal_path = user_config[f"terminal_path_{terminal_counter}"]
                
                # If we found a path, add it and continue to next counter
                if terminal_path:
                    if isinstance(terminal_path, str) and os.path.exists(terminal_path):
                        terminal_paths.append(terminal_path)
                        log_and_print(f"Found terminal_path_{terminal_counter}: {terminal_path}", "INFO")
                    else:
                        log_and_print(f"WARNING: terminal_path_{terminal_counter} exists but file not found: {terminal_path}", "WARNING")
                    terminal_counter += 1
                else:
                    # No more terminal paths found - stop looking
                    break
            
            # If no terminal paths found at all, skip this user
            if not terminal_paths:
                log_and_print(f"WARNING: No valid terminal paths found for user {user_id}", "WARNING")
                continue
            
            log_and_print(f"Found {len(terminal_paths)} terminal path(s) for user {user_id}", "INFO")
            
            # Determine how many terminals to use
            num_developers = len(data)
            terminals_to_use = terminal_paths if num_developers == 1 else terminal_paths[:MAX_TERMINALS_PER_DEVELOPER]
            
            # Get symbols dictionary
            account_management = ci_config.get("accountmanagement") or {}
            if isinstance(account_management, dict):
                symbols_dict = account_management.get("symbols_dictionary", {})
                
                # Extract custom bars and timeframes from symbols_dictionary
                ohlc_bars = symbols_dict.get("ohlc_bars", 500)
                ohlc_timeframes = symbols_dict.get("ohlc_timeframes", ["15m", "5m", "30m", "1h", "4h"])
                
                # Clean timeframes - remove any that aren't in TIMEFRAME_MAP
                valid_timeframes = []
                for tf in ohlc_timeframes:
                    if tf in TIMEFRAME_MAP:
                        valid_timeframes.append(tf)
                    else:
                        log_and_print(f"WARNING: Timeframe '{tf}' not supported. Skipping.", "WARNING")
                
                # If no valid timeframes, use default ones
                if not valid_timeframes:
                    valid_timeframes = ["15m", "5m", "30m", "1h", "4h"]
                    log_and_print(f"No valid timeframes found for user {user_id}. Using defaults.", "WARNING")
                
                # Remove the custom config keys from symbols_dict so they don't get processed as symbols
                clean_symbols_dict = {k: v for k, v in symbols_dict.items() 
                                     if k not in ["ohlc_bars", "ohlc_timeframes"]}
            else:
                clean_symbols_dict = {}
                ohlc_bars = 500
                valid_timeframes = ["15m", "5m", "30m", "1h", "4h"]
            
            # Create entries for each terminal
            for idx, terminal_path in enumerate(terminals_to_use, 1):
                account_key = f"{broker_name.lower()}_{user_id}_terminal_{idx}"
                base_folder = os.path.join(OHLC_FOLDER, str(user_id), "ohlc")
                
                transformed_data[account_key] = {
                    "LOGIN_ID": str(login),
                    "PASSWORD": str(password),
                    "SERVER": str(server),
                    "BASE_FOLDER": base_folder,
                    "terminal_path": terminal_path,
                    "USER_ID": str(user_id),
                    "BROKER_NAME": str(broker_name),
                    "SYMBOLS_DICTIONARY": clean_symbols_dict,
                    "OHLC_BARS": int(ohlc_bars) if ohlc_bars else 500,
                    "OHLC_TIMEFRAMES": valid_timeframes
                }
                
                log_and_print(f"Created config for {account_key}", "INFO")
        
        log_and_print(f"Loaded {len(transformed_data)} terminal configurations from {len(data)} developers", "SUCCESS")
        return transformed_data

    except json.JSONDecodeError as e:
        log_and_print(f"Invalid JSON in developers.json: {e}", "CRITICAL")
        return {}
    except Exception as e:
        log_and_print(f"Failed to load developers.json: {e}", "CRITICAL")
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

def log_and_print(message, level="INFO"):
    """Log and print messages in a structured format."""
    timestamp = datetime.now(pytz.timezone('Africa/Lagos')).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {level:8} | {message}")

def save_errors(error_log):
    """Save error log to JSON file."""
    try:
        os.makedirs(BASE_ERROR_FOLDER, exist_ok=True)
        with open(ERROR_JSON_PATH, 'w') as f:
            json.dump(error_log, f, indent=4)
        log_and_print("Error log saved", "ERROR")
    except Exception as e:
        log_and_print(f"Failed to save error log: {str(e)}", "ERROR")

def initialize_mt5(terminal_path, login_id, password, server):
    """Initialize MetaTrader 5 terminal for a specific broker."""
    error_log = []
    if not os.path.exists(terminal_path):
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
            password=password,
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

        if not mt5.login(login=login_int, server=server, password=password):
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

def get_symbols():
    """Retrieve all available symbols from MT5."""
    error_log = []
    symbols = mt5.symbols_get()
    if not symbols:
        error_log.append({
            "timestamp": datetime.now(pytz.timezone('Africa/Lagos')).strftime('%Y-%m-%d %H:%M:%S.%f+01:00'),
            "error": f"Failed to retrieve symbols: {mt5.last_error()}",
            "broker": mt5.terminal_info().name if mt5.terminal_info() else "unknown"
        })
        save_errors(error_log)
        log_and_print(f"Failed to retrieve symbols: {mt5.last_error()}", "ERROR")
        return [], error_log

    available_symbols = [s.name for s in symbols]
    log_and_print(f"Retrieved {len(available_symbols)} symbols", "INFO")
    return available_symbols, error_log

def identifyparenthighsandlows(df, neighborcandles_left, neighborcandles_right):
    """Identify Parent Highs (PH) and Parent Lows (PL) based on neighbor candles."""
    error_log = []
    ph_indices = []
    pl_indices = []
    ph_labels = []
    pl_labels = []

    try:
        for i in range(len(df)):
            if i >= len(df) - neighborcandles_right:
                continue

            current_high = df.iloc[i]['high']
            current_low = df.iloc[i]['low']
            right_highs = df.iloc[i + 1:i + neighborcandles_right + 1]['high']
            right_lows = df.iloc[i + 1:i + neighborcandles_right + 1]['low']
            left_highs = df.iloc[max(0, i - neighborcandles_left):i]['high']
            left_lows = df.iloc[max(0, i - neighborcandles_left):i]['low']

            if len(right_highs) == neighborcandles_right:
                is_ph = True
                if len(left_highs) > 0:
                    is_ph = current_high > left_highs.max()
                is_ph = is_ph and current_high > right_highs.max()
                if is_ph:
                    ph_indices.append(df.index[i])
                    ph_labels.append(('PH', current_high, df.index[i]))

            if len(right_lows) == neighborcandles_right:
                is_pl = True
                if len(left_lows) > 0:
                    is_pl = current_low < left_lows.min()
                is_pl = is_pl and current_low < right_lows.min()
                if is_pl:
                    pl_indices.append(df.index[i])
                    pl_labels.append(('PL', current_low, df.index[i]))

        log_and_print(f"Identified {len(ph_indices)} PH and {len(pl_indices)} PL for {df['symbol'].iloc[0]}", "INFO")
        return ph_labels, pl_labels, error_log
    except Exception as e:
        error_log.append({
            "timestamp": datetime.now(pytz.timezone('Africa/Lagos')).strftime('%Y-%m-%d %H:%M:%S.%f+01:00'),
            "error": f"Failed to identify PH/PL: {str(e)}",
            "broker": mt5.terminal_info().name if mt5.terminal_info() else "unknown"
        })
        save_errors(error_log)
        log_and_print(f"Failed to identify PH/PL: {str(e)}", "ERROR")
        return [], [], error_log

def fetch_ohlcv_data(symbol, mt5_timeframe, bars):
    """
    Fetch OHLCV data including the currently forming candle (index 0).
    """
    error_log = []
    lagos_tz = pytz.timezone('Africa/Lagos')
    timestamp = datetime.now(lagos_tz).strftime('%Y-%m-%d %H:%M:%S.%f%z')

    broker_name = mt5.terminal_info().name if mt5.terminal_info() else "unknown"

    # --- Step 1: Ensure symbol is selected ---
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

    # --- Step 2: Fetch rates ---
    rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, bars)

    if rates is None or len(rates) == 0:
        last_err = mt5.last_error()
        err_msg = f"No data for {symbol}: {last_err}"
        log_and_print(err_msg, "ERROR")
        return None, [{"error": err_msg, "timestamp": timestamp}]

    available_bars = len(rates)
    
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.set_index("time")

    df = df.astype({
        "open": float, "high": float, "low": float, "close": float,
        "tick_volume": float, "spread": int, "real_volume": float
    })
    df.rename(columns={"tick_volume": "volume"}, inplace=True)

    log_and_print(f"Fetched {available_bars} bars (including live candle) for {symbol}", "INFO")
    return df, error_log

def save_newest_oldest_df(df, symbol, timeframe_str, timeframe_folder):
    """Save candles: oldest → newest, candle_number 0 = oldest. Fixed filenames."""
    error_log = []
    
    target_subfolder = os.path.join(timeframe_folder, "candlesdetails")
    os.makedirs(target_subfolder, exist_ok=True)
    
    all_json_path = os.path.join(target_subfolder, "newest_oldest.json")
    latest_json_path = os.path.join(target_subfolder, "latest_completed_candle.json")
    
    lagos_tz = pytz.timezone('Africa/Lagos')
    now = datetime.now(lagos_tz)

    try:
        if len(df) < 2:
            error_msg = f"Not enough data for {symbol} ({timeframe_str})"
            log_and_print(error_msg, "ERROR")
            error_log.append({"error": error_msg, "timestamp": now.isoformat()})
            save_errors(error_log)
            return error_log

        all_candles = []
        for i, (ts, row) in enumerate(df.iterrows()):
            candle = row.to_dict()
            candle.update({
                "time": ts.strftime('%Y-%m-%d %H:%M:%S'),
                "candle_number": i,
                "symbol": symbol,
                "timeframe": timeframe_str
            })
            all_candles.append(candle)

        with open(all_json_path, 'w', encoding='utf-8') as f:
            json.dump(all_candles, f, indent=4)

        previous_latest_candle = all_candles[-1].copy()
        candle_time = lagos_tz.localize(datetime.strptime(previous_latest_candle["time"], '%Y-%m-%d %H:%M:%S'))
        delta = now - candle_time
        total_hours = delta.total_seconds() / 3600
        age_str = f"{int(total_hours)}h old" if total_hours <= 24 else f"{int(total_hours // 24)}d old"

        previous_latest_candle.update({"age": age_str, "id": "x"})
        if "candle_number" in previous_latest_candle:
            del previous_latest_candle["candle_number"]

        with open(latest_json_path, 'w', encoding='utf-8') as f:
            json.dump(previous_latest_candle, f, indent=4)

        log_and_print(f"✓ {symbol} {timeframe_str} | JSON saved | {len(all_candles)} candles", "SUCCESS")

    except Exception as e:
        err = f"save_newest_oldest_df failed: {str(e)}"
        log_and_print(err, "ERROR")
        error_log.append({"error": err, "timestamp": now.isoformat()})
        save_errors(error_log)

    return error_log

def generate_and_save_chart_df(df, symbol, timeframe_str, timeframe_folder):
    """Generate and save only the basic full chart."""
    error_log = []
    
    chart_path = os.path.join(timeframe_folder, "chart.png")
    
    try:
        num_candles = len(df)
        
        MIN_CANDLE_WIDTH = 20
        MAX_CANDLE_WIDTH = 40
        MIN_CANDLE_SPACING = 10
        BASE_HEIGHT = 100
        MAX_IMAGE_WIDTH = 90000000
        
        if num_candles <= 50:
            base_candle_width = 30
            base_spacing_multiplier = 1.8
        elif num_candles <= 200:
            base_candle_width = 20
            base_spacing_multiplier = 1.6
        elif num_candles <= 1000:
            base_candle_width = 12
            base_spacing_multiplier = 1.4
        else:
            base_candle_width = MIN_CANDLE_WIDTH
            base_spacing_multiplier = 1.3
        
        target_candle_width = max(base_candle_width, MIN_CANDLE_WIDTH)
        target_candle_width = min(target_candle_width, MAX_CANDLE_WIDTH)
        
        desired_spacing = target_candle_width * base_spacing_multiplier
        actual_spacing = max(desired_spacing, MIN_CANDLE_SPACING)
        
        if num_candles > 1:
            total_width_pixels = actual_spacing * (num_candles - 1) + target_candle_width
        else:
            total_width_pixels = target_candle_width * 2
        
        padding_pixels = 200
        img_width_pixels = int(total_width_pixels + padding_pixels)
        img_width_pixels = min(img_width_pixels, MAX_IMAGE_WIDTH)
        
        min_width_pixels = 800
        if img_width_pixels < min_width_pixels:
            img_width_pixels = min_width_pixels
        
        img_width_inches = img_width_pixels / 100
        
        log_and_print(f"📊 {symbol} {timeframe_str} | {num_candles} candles → {img_width_pixels}px", "INFO")
        
        custom_style = mpf.make_mpf_style(
            base_mpl_style="default",
            marketcolors=mpf.make_marketcolors(
                up="green", down="red", edge="inherit",
                wick={"up": "green", "down": "red"}, volume="gray"
            )
        )

        required_cols = ['Open', 'High', 'Low', 'Close']
        df_cols = df.columns.tolist()
        
        col_mapping = {}
        for req_col in required_cols:
            found = False
            for df_col in df_cols:
                if df_col.lower() == req_col.lower():
                    col_mapping[req_col] = df_col
                    found = True
                    break
            if not found:
                raise KeyError(f"Required column '{req_col}' not found in DataFrame. Available columns: {df_cols}")
        
        if col_mapping:
            df_plot = df.rename(columns={v: k for k, v in col_mapping.items()})
        else:
            df_plot = df

        fig, axlist = mpf.plot(
            df_plot, 
            type='candle', 
            style=custom_style, 
            volume=False,
            title=f"{symbol} ({timeframe_str}) - {num_candles} candles", 
            returnfig=True,
            warn_too_much_data=5000,
            figsize=(img_width_inches, BASE_HEIGHT),
            scale_padding={'left': 0.5, 'right': 1.5, 'top': 0.5, 'bottom': 0.5}
        )
        
        fig.set_size_inches(img_width_inches, BASE_HEIGHT)
        
        for ax in axlist:
            ax.grid(False)
            for line in ax.get_lines():
                if line.get_label() == '':
                    line.set_linewidth(0.5)

        fig.savefig(chart_path, bbox_inches="tight", dpi=100)
        plt.close(fig)

        log_and_print(f"✓ {symbol} {timeframe_str} | Chart saved | {num_candles} candles", "SUCCESS")

        return chart_path, error_log

    except KeyError as e:
        log_and_print(f"Error in chart generation - column error: {e}", "ERROR")
        error_log.append(str(e))
        return None, error_log
    except Exception as e:
        log_and_print(f"Error in chart generation: {e}", "ERROR")
        error_log.append(str(e))
        return None, error_log

def generate_and_save_chart_slice(symbol, timeframe_str, timeframe_folder):
    """Generate sliced charts with dynamic sizing."""
    error_log = []

    target_subfolder = os.path.join(timeframe_folder, "candlesdetails")
    json_path = os.path.join(target_subfolder, "newest_oldest.json")

    candle_slices = [500]

    generated_slice_counts = []

    try:
        if not os.path.exists(json_path):
            err = f"JSON file not found: {json_path}"
            log_and_print(err, "ERROR")
            error_log.append({"error": err})
            return [], error_log

        with open(json_path, 'r', encoding='utf-8') as f:
            all_candles = json.load(f)

        if len(all_candles) < 11:
            err = f"Not enough candles in JSON (need at least 11) for {symbol} {timeframe_str}"
            log_and_print(err, "WARNING")
            return [], error_log

        df = pd.DataFrame(all_candles)
        df["time"] = pd.to_datetime(df["time"])
        df = df.set_index("time")
        df = df[["open", "high", "low", "close", "volume"]]
        df = df.astype(float)
        df = df.sort_index()

        custom_style = mpf.make_mpf_style(
            base_mpl_style="default",
            marketcolors=mpf.make_marketcolors(
                up="green", down="red", edge="inherit",
                wick={"up": "green", "down": "red"}, volume="gray"
            )
        )

        generated_slices = 0
        for count in candle_slices:
            if len(df) >= count:
                df_slice = df.iloc[-count:]
                slice_path = os.path.join(timeframe_folder, f"chart_{count}.png")
                
                num_candles = len(df_slice)
                
                MIN_CANDLE_WIDTH = 20
                MAX_CANDLE_WIDTH = 40
                MIN_CANDLE_SPACING = 10
                BASE_HEIGHT = 50
                MAX_IMAGE_WIDTH = 90000000
                
                if num_candles <= 50:
                    base_candle_width = 30
                    base_spacing_multiplier = 1.8
                elif num_candles <= 200:
                    base_candle_width = 20
                    base_spacing_multiplier = 1.6
                elif num_candles <= 1000:
                    base_candle_width = 12
                    base_spacing_multiplier = 1.4
                else:
                    base_candle_width = MIN_CANDLE_WIDTH
                    base_spacing_multiplier = 1.3
                
                target_candle_width = max(base_candle_width, MIN_CANDLE_WIDTH)
                target_candle_width = min(target_candle_width, MAX_CANDLE_WIDTH)
                
                desired_spacing = target_candle_width * base_spacing_multiplier
                actual_spacing = max(desired_spacing, MIN_CANDLE_SPACING)
                
                if num_candles > 1:
                    total_width_pixels = actual_spacing * (num_candles - 1) + target_candle_width
                else:
                    total_width_pixels = target_candle_width * 2
                
                padding_pixels = 200
                img_width_pixels = int(total_width_pixels + padding_pixels)
                img_width_pixels = min(img_width_pixels, MAX_IMAGE_WIDTH)
                
                min_width_pixels = 800
                if img_width_pixels < min_width_pixels:
                    img_width_pixels = min_width_pixels
                
                img_width_inches = img_width_pixels / 100
                
                log_and_print(f"📊 {symbol} {timeframe_str} | Last {count}: {num_candles} candles → {img_width_pixels}px", "INFO")

                fig, axlist = mpf.plot(
                    df_slice,
                    type='candle',
                    style=custom_style,
                    title=f"{symbol} ({timeframe_str}) - Last {count}",
                    returnfig=True,
                    warn_too_much_data=5000,
                    figsize=(img_width_inches, BASE_HEIGHT),
                    scale_padding={'left': 0.5, 'right': 1.5, 'top': 0.5, 'bottom': 0.5}
                )

                fig.set_size_inches(img_width_inches, BASE_HEIGHT)
                
                for ax in axlist:
                    ax.grid(False)
                    for line in ax.get_lines():
                        if line.get_label() == '':
                            line.set_linewidth(0.5)

                fig.savefig(slice_path, bbox_inches="tight", dpi=100)
                plt.close(fig)

                generated_slice_counts.append(count)
                generated_slices += 1
                
                log_and_print(f"✓ {symbol} {timeframe_str} | chart_{count}.png saved | {num_candles} candles", "SUCCESS")

        if generated_slices > 0:
            log_and_print(f"✓ {symbol} {timeframe_str} | {generated_slices} sliced charts saved", "SUCCESS")
        return generated_slice_counts, error_log

    except Exception as e:
        log_and_print(f"Error in sliced chart generation (from JSON): {e}", "ERROR")
        error_log.append({"error": str(e)})
        return [], error_log
    
def save_sliced_newest_oldest_json(symbol, timeframe_str, timeframe_folder, slice_counts):
    """Save sliced versions: oldest → newest."""
    error_log = []

    target_subfolder = os.path.join(timeframe_folder, "candlesdetails")
    full_json_path = os.path.join(target_subfolder, "newest_oldest.json")

    lagos_tz = pytz.timezone('Africa/Lagos')
    now = datetime.now(lagos_tz)

    try:
        if not os.path.exists(full_json_path):
            err = f"Full JSON not found for slicing: {full_json_path}"
            log_and_print(err, "ERROR")
            error_log.append({"error": err})
            return error_log

        with open(full_json_path, 'r', encoding='utf-8') as f:
            all_candles = json.load(f)

        if len(all_candles) < 11:
            return error_log

        generated = 0
        for count in slice_counts:
            if len(all_candles) < count:
                continue

            sliced_candles = all_candles[-count:]

            reordered = []
            for i, candle in enumerate(sliced_candles):
                c = candle.copy()
                c["candle_number"] = i
                reordered.append(c)

            slice_json_path = os.path.join(target_subfolder, f"new_old_{count}.json")
            with open(slice_json_path, 'w', encoding='utf-8') as f:
                json.dump(reordered, f, indent=4)

            if len(reordered) >= 2:
                prev_candle = reordered[-1].copy()
                candle_time = lagos_tz.localize(datetime.strptime(prev_candle["time"], '%Y-%m-%d %H:%M:%S'))
                delta = now - candle_time
                total_hours = delta.total_seconds() / 3600
                age_str = f"{int(total_hours)}h old" if total_hours <= 24 else f"{int(total_hours // 24)}d old"
                prev_candle.update({"age": age_str, "id": "x"})
                if "candle_number" in prev_candle:
                    del prev_candle["candle_number"]

                latest_slice_path = os.path.join(target_subfolder, f"latest_completed_candle.json")
                with open(latest_slice_path, 'w', encoding='utf-8') as f:
                    json.dump(prev_candle, f, indent=4)

            generated += 1

        if generated > 0:
            log_and_print(f"✓ {symbol} {timeframe_str} | {generated} sliced JSONs saved", "SUCCESS")

    except Exception as e:
        err = f"save_sliced_newest_oldest_json failed: {str(e)}"
        log_and_print(err, "ERROR")
        error_log.append({"error": err, "timestamp": now.isoformat()})

    return error_log

def ticks_value(symbol, symbol_folder, user_brokerid, base_folder, all_symbols):
    error_log = []
    
    user_id = get_user_id_from_account(user_brokerid)
    if not user_id:
        config = ohlcdictionary.get(user_brokerid, {})
        user_id = config.get("USER_ID", "unknown")
    
    cleaned_broker = ''.join([char for char in user_brokerid if not char.isdigit()])
    cleaned_broker = re.sub(r'_terminal_\d+$', '', cleaned_broker)
    
    safe_symbol = symbol.replace('/', '_').replace(' ', '_').upper()
    output_json_filename = f"{safe_symbol}_ticks.json"
    output_json_path = os.path.join(symbol_folder, output_json_filename)
    
    combined_path = r"C:\xampp\htdocs\harvcore\harvox\invharv\usersdata\symbolstick\symbolstick.json"
    
    tick_size = None
    tick_value = None
    
    try:
        config = ohlcdictionary.get(user_brokerid)
        if not config:
            raise Exception(f"No configuration found for broker '{user_brokerid}' in ohlcdictionary")
        
        success, init_errors = initialize_mt5(
            config["terminal_path"],
            config["LOGIN_ID"],
            config["PASSWORD"],
            config["SERVER"]
        )
        error_log.extend(init_errors)
        
        if not success:
            raise Exception("MT5 initialization failed")
        
        sym_info = mt5.symbol_info(symbol)
        if sym_info is None:
            raise Exception(f"Symbol '{symbol}' not found or not available in MT5 terminal")
        
        tick_size = sym_info.point
        tick_value = sym_info.trade_tick_value
        
        log_and_print(
            f"[{user_brokerid}] Retrieved for {symbol}: tick_size={tick_size}, tick_value={tick_value}",
            "SUCCESS"
        )
        
        mt5.shutdown()
        
    except Exception as e:
        error_msg = f"Failed to retrieve tick info for {symbol} ({user_brokerid}): {str(e)}"
        error_log.append({
            "timestamp": datetime.now(pytz.timezone('Africa/Lagos')).strftime('%Y-%m-%d %H:%M:%S.%f+01:00'),
            "error": error_msg,
            "broker": user_brokerid
        })
        log_and_print(error_msg, "ERROR")
    
    output_data = {
        "market": symbol,
        "broker": cleaned_broker,
        "user_id": user_id,
        "tick_size": tick_size,
        "tick_value": tick_value
    }
    
    try:
        with open(output_json_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=4)
        log_and_print(f"Saved tick info to {output_json_path}", "SUCCESS")
    except Exception as e:
        error_log.append({
            "timestamp": datetime.now(pytz.timezone('Africa/Lagos')).strftime('%Y-%m-%d %H:%M:%S.%f+01:00'),
            "error": f"Failed to write {output_json_path}: {str(e)}",
            "broker": user_brokerid
        })
        log_and_print(f"Failed to save individual JSON: {str(e)}", "ERROR")
    
    combined_data = {}
    file_exists = os.path.exists(combined_path)
    
    if file_exists:
        try:
            with open(combined_path, 'r', encoding='utf-8') as f:
                combined_data = json.load(f)
        except Exception as e:
            error_log.append({
                "timestamp": datetime.now(pytz.timezone('Africa/Lagos')).strftime('%Y-%m-%d %H:%M:%S.%f+01:00'),
                "error": f"Failed to read combined JSON: {str(e)}",
                "broker": user_brokerid
            })
            log_and_print(f"Failed to read combined JSON: {str(e)}", "ERROR")
            combined_data = {}
    
    entry = {
        "market": symbol,
        "broker": cleaned_broker,
        "user_id": user_id,
        "tick_size": tick_size,
        "tick_value": tick_value
    }
    
    previous_entry = combined_data.get(safe_symbol)
    
    if previous_entry != entry:
        combined_data[safe_symbol] = entry
        
        try:
            os.makedirs(os.path.dirname(combined_path), exist_ok=True)
            
            with open(combined_path, 'w', encoding='utf-8') as f:
                json.dump(combined_data, f, indent=4)
            
            action = "Updated" if previous_entry is not None else "Added"
            log_and_print(f"{action} {safe_symbol} (user: {user_id}) in combined symbolstick.json", "SUCCESS")
        except Exception as e:
            error_log.append({
                "timestamp": datetime.now(pytz.timezone('Africa/Lagos')).strftime('%Y-%m-%d %H:%M:%S.%f+01:00'),
                "error": f"Failed to write combined JSON: {str(e)}",
                "broker": user_brokerid
            })
            log_and_print(f"Failed to save combined JSON: {str(e)}", "ERROR")
    
    if error_log:
        save_errors(error_log)
    
    return error_log

def crop_chart(chart_path, symbol, timeframe_str, timeframe_folder):
    """Crop all charts in the folder including slices."""
    error_log = []
    
    images_to_crop = [f for f in os.listdir(timeframe_folder) if f.endswith(".png") and "chart" in f]

    try:
        cropped_count = 0
        skipped_count = 0
        
        for filename in images_to_crop:
            full_path = os.path.join(timeframe_folder, filename)
            
            try:
                with Image.open(full_path) as img:
                    if img.width * img.height > 150000000:
                        log_and_print(f"SKIPPED cropping for {filename} - image too large ({img.width}×{img.height} = {img.width * img.height} pixels)", "WARNING")
                        skipped_count += 1
                        continue
                    
                    left, top, right, bottom = 0, 0, 0, 0 
                    crop_box = (left, top, img.width - right, img.height - bottom)
                    cropped_img = img.crop(crop_box)
                    cropped_img.save(full_path, "PNG")
                    cropped_count += 1
                    
            except Exception as e:
                log_and_print(f"Failed to crop {filename}: {str(e)}", "WARNING")
                skipped_count += 1
                continue
        
        log_and_print(f"Chart cropping for {symbol} ({timeframe_str}): {cropped_count} cropped, {skipped_count} skipped (too large)", "SUCCESS")
        
    except Exception as e:
        err_msg = f"Failed to crop charts: {str(e)}"
        log_and_print(err_msg, "ERROR")
        error_log.append({"error": err_msg})

    return error_log

def backup_ohlc_dictionary():
    """Backup the developers.json file instead of ohlc.json"""
    main_path = Path(r"C:\xampp\htdocs\harvcore\harvox\invharv\usersdata\developers\developers.json")
    backup_path = Path(r"C:\xampp\htdocs\harvcore\harvox\invharv\usersdata\developers\developersbackup.json")
    
    main_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    

    def read_json_safe(path: Path) -> dict | None:
        if not path.exists() or path.stat().st_size == 0:
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data == {}:
                return None
            return data
        except json.JSONDecodeError:
            return None

    def write_json(path: Path, data: dict):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    main_data = read_json_safe(main_path)
    
    if main_data is not None:
        print("Main has valid data → syncing to backup")
        write_json(backup_path, main_data)
        return

    print("Main is empty or invalid → checking backup")
    backup_data = read_json_safe(backup_path)

    if backup_data is not None:
        print("Backup has valid data → restoring to main")
        write_json(main_path, backup_data)
        print(f"Restored: {backup_path} → {main_path}")
        return

    print("Both files empty or corrupted → initializing clean empty state")
    empty_dict = {}
    write_json(main_path, empty_dict)
    write_json(backup_path, empty_dict)
    print("Created fresh empty developers.json and backup")

def clear_chart_folder(base_folder: str):
    """Delete ONLY symbols that have NO valid OB-none-OI record on 15m-4h."""
    error_log = []
    IMPORTANT_TFS = {"15m", "30m", "1h", "4h"}

    if not os.path.exists(base_folder):
        log_and_print(f"Chart folder {base_folder} does not exist – nothing to clear.", "INFO")
        return True, error_log

    deleted = 0
    kept    = 0

    for item in os.listdir(base_folder):
        item_path = os.path.join(base_folder, item)
        if not os.path.isdir(item_path):
            continue

        keep_symbol = False
        for tf in IMPORTANT_TFS:
            json_path = os.path.join(item_path, tf, "ob_none_oi_data.json")
            if not os.path.exists(json_path):
                continue
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                keep_symbol = True
                break
            except Exception:
                pass

        try:
            if keep_symbol:
                kept += 1
                log_and_print(f"KEEP   {item_path} (has 15m-4h OB-none-OI)", "INFO")
            else:
                shutil.rmtree(item_path)
                deleted += 1
                log_and_print(f"DELETE {item_path} (no 15m-4h record)", "INFO")
        except Exception as e:
            error_log.append({
                "timestamp": datetime.now(pytz.timezone('Africa/Lagos')).strftime(
                    '%Y-%m-%d %H:%M:%S.%f+01:00'),
                "error": f"Failed to handle {item_path}: {str(e)}",
                "broker": base_folder
            })
            log_and_print(f"Failed to handle {item_path}: {str(e)}", "ERROR")

    log_and_print(
        f"Smart clean finished → {deleted} folders deleted, {kept} folders kept.",
        "SUCCESS")
    return True, error_log

def clear_unknown_broker():
    """Clear unknown broker folders based on new JSON structure."""
    base_path = r"C:\xampp\htdocs\harvcore\harvox\invharv\usersdata\developers"
    
    if not os.path.exists(base_path):
        print(f"ERROR: Base directory does not exist:\n    {base_path}")
        return
    
    if not ohlcdictionary:
        print("No brokers found in ohlcdictionary.")
        return

    print("Configured Brokers & Folder Check (Human-readable folders):")
    print("=" * 90)
    
    configured_displays = set()
    known_broker_bases = set()
    broker_details = []
    existing = 0
    missing = 0
    
    def format_user_brokerid(name):
        parts = name.split('_')
        if len(parts) >= 3 and parts[-2].lower() == 'terminal':
            broker_base = parts[0].capitalize()
            user_id = parts[1]
            known_broker_bases.add(broker_base)
            return f"{broker_base} (User {user_id})"
        return name.capitalize()

    for user_brokerid, config in ohlcdictionary.items():
        display_name = format_user_brokerid(user_brokerid)
        lower_display = display_name.lower()
        
        configured_displays.add(lower_display)
        
        base_folder = config.get("BASE_FOLDER", "")
        user_id = config.get("USER_ID", "unknown")
        folder_path = os.path.join(OHLC_FOLDER, str(user_id))
        
        exists = os.path.isdir(folder_path)
        
        marker = "Success" if exists else "Error"
        status = "EXISTS" if exists else "MISSING"
        
        print(f"{marker} {user_brokerid.ljust(30)} → {display_name.ljust(25)} → {status}")
        print(f"    Path: {folder_path}\n")
        
        broker_details.append({
            'original': user_brokerid,
            'display': display_name,
            'lower': lower_display,
            'path': folder_path,
            'exists': exists,
            'user_id': user_id
        })
        
        if exists: existing += 1
        else: missing += 1
    
    print("=" * 90)
    print(f"Total configured: {len(ohlcdictionary)} terminal(s) | {existing} folder(s) exist | {missing} missing")

    print("\nUnique Configured Broker Types:")
    print("-" * 60)
    for base in sorted(known_broker_bases):
        instances = [b['display'] for b in broker_details if b['display'].startswith(base)]
        print(f"• {base.ljust(15)} → {len(instances)} terminal(s): {', '.join(instances)}")
    print("-" * 60)
    print(f"Unique broker types: {len(known_broker_bases)}")

    print("\nCleaning Orphaned Broker Folders (AUTO-DELETE enabled)...")
    print("-" * 70)
    
    if not os.path.isdir(base_path):
        print("Base path not accessible.")
    else:
        orphaned = []
        all_folders = [f for f in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, f))]
        
        for folder in all_folders:
            folder_lower = folder.lower()
            full_path = os.path.join(base_path, folder)
            
            if folder_lower in configured_displays:
                continue
                
            suspected_base = None
            for base in known_broker_bases:
                if folder_lower.startswith(base.lower()):
                    suspected_base = base
                    break
            
            if suspected_base:
                orphaned.append((folder, full_path, suspected_base))
        
        if orphaned:
            print(f"Deleting {len(orphaned)} orphaned broker folder(s):")
            deleted_count = 0
            for folder, full_path, base in orphaned:
                try:
                    shutil.rmtree(full_path)
                    print(f"  Deleted: {folder}  (was {base})")
                    deleted_count += 1
                except Exception as e:
                    print(f"  Failed to delete {folder}: {e}")
            print(f"\nAuto-clean complete: {deleted_count}/{len(orphaned)} orphaned folders removed.")
        else:
            print("No orphaned broker folders found. Directory is clean!")

    print("-" * 70)
    
    if missing > 0:
        print(f"\nReminder: {missing} configured terminal(s) missing their folder!")

def fetch_charts_all_brokers():
    """
    Fetch charts for all brokers.
    Each user specifies their own symbols, bars, and timeframes in their config.
    No external category file needed - symbols are taken directly from each user's symbols_dictionary.
    """
    log_and_print("\n" + "╔" + "═"*58 + "╗", "INFO")
    log_and_print("║           🚀 MULTI-ACCOUNT SYNCHRONIZATION ENGINE           ║", "INFO")
    log_and_print("╚" + "═"*58 + "╝\n", "INFO")

    try:
        if not ohlcdictionary:
            log_and_print("⚠️  No MT5 configurations found. Cannot process symbols.", "ERROR")
            return False

        # 1. Group accounts by user
        user_accounts = {}
        for acc_key, acc_cfg in ohlcdictionary.items():
            user_id = acc_cfg.get("USER_ID", "unknown")
            if user_id not in user_accounts:
                user_accounts[user_id] = []
            user_accounts[user_id].append((acc_key, acc_cfg))
        
        # 2. Process each user's accounts
        manager = multiprocessing.Manager()
        final_counts = manager.dict()
        processes = []
        
        for user_id, accounts in user_accounts.items():
            log_and_print(f"\n📋 USER {user_id} | {len(accounts)} terminals", "INFO")
            
            # Collect all unique symbols from this user's accounts
            user_symbols = []
            for acc_key, acc_cfg in accounts:
                symbols_dict = acc_cfg.get("SYMBOLS_DICTIONARY", {})
                for category, symbol_list in symbols_dict.items():
                    if isinstance(symbol_list, list):
                        for sym in symbol_list:
                            if sym and sym not in user_symbols:
                                user_symbols.append((sym, category))
            
            log_and_print(f"  📊 USER {user_id} | Found {len(user_symbols)} unique symbols", "INFO")
            
            # ============================================================
            # DELETE ORPHANED FOLDERS (not in the user's symbol list)
            # ============================================================
            base_folder = accounts[0][1].get("BASE_FOLDER", "")  # Get base folder from first account
            if base_folder and os.path.exists(base_folder):
                # Get all symbol folder names from the user's symbols list
                valid_symbol_names = set()
                for sym, cat in user_symbols:
                    valid_symbol_names.add(sym.replace(" ", "_"))
                
                # Scan the base folder for existing symbol folders
                orphaned_folders = []
                for item in os.listdir(base_folder):
                    item_path = os.path.join(base_folder, item)
                    if os.path.isdir(item_path):
                        # Check if this folder is a symbol folder (not a system folder like __pycache__)
                        if item not in valid_symbol_names:
                            orphaned_folders.append(item_path)
                
                # Delete orphaned folders
                if orphaned_folders:
                    log_and_print(f"  🗑️  USER {user_id} | Found {len(orphaned_folders)} orphaned folders to delete", "INFO")
                    for folder_path in orphaned_folders:
                        try:
                            shutil.rmtree(folder_path)
                            log_and_print(f"  🗑️  USER {user_id} | Deleted orphaned folder: {os.path.basename(folder_path)}", "INFO")
                        except Exception as e:
                            log_and_print(f"  ⚠️  USER {user_id} | Failed to delete {folder_path}: {str(e)}", "WARNING")
                else:
                    log_and_print(f"  ✅ USER {user_id} | No orphaned folders found", "INFO")
            
            if not user_symbols:
                log_and_print(f"  ⚠️  USER {user_id} | No symbols found in dictionary", "WARNING")
                continue
            
            if len(user_accounts) == 1:
                # Single user - use all terminals with distributed symbols
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
                    
                    log_and_print(f"  └─ {acc_key} | {len(chunk)} symbols | Bars: {acc_cfg.get('OHLC_BARS', 500)} | TFs: {acc_cfg.get('OHLC_TIMEFRAMES', [])}", "INFO")
            else:
                # Multiple users - each terminal gets its own symbols from its symbols_dictionary
                for acc_key, acc_cfg in accounts:
                    symbols_dict = acc_cfg.get("SYMBOLS_DICTIONARY", {})
                    account_symbols = []
                    for cat, symbol_list in symbols_dict.items():
                        if isinstance(symbol_list, list):
                            for sym in symbol_list:
                                if sym and sym not in account_symbols:
                                    account_symbols.append((sym, cat))
                    
                    if account_symbols:
                        p = multiprocessing.Process(
                            target=process_account_worker, 
                            args=(acc_key, acc_cfg, account_symbols, TIMEFRAME_MAP, final_counts)
                        )
                        processes.append(p)
                        p.start()
                        log_and_print(f"  └─ {acc_key} | {len(account_symbols)} symbols | Bars: {acc_cfg.get('OHLC_BARS', 500)} | TFs: {acc_cfg.get('OHLC_TIMEFRAMES', [])}", "INFO")
                    else:
                        log_and_print(f"  └─ {acc_key} | No symbols in dictionary", "WARNING")

        # Wait for all processes to finish
        for p in processes:
            p.join()

        # 3. Final Summary
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
        import traceback
        traceback.print_exc()
        return False
     
def process_account_worker_old(account_key, account_cfg, symbol_chunk, TIMEFRAME_MAP, result_dict):
    """
    This function runs in its own process.
    Uses dynamic bars and timeframes from user config.
    Filters symbols to only those available from the broker.
    """
    processed_count = 0
    
    # Get user-specific configuration
    user_bars = account_cfg.get("OHLC_BARS", 500)
    user_timeframes = account_cfg.get("OHLC_TIMEFRAMES", ["15m", "5m", "30m", "1h", "4h"])
    
    # Build timeframe map for this user
    user_timeframe_map = {}
    for tf_str in user_timeframes:
        if tf_str in TIMEFRAME_MAP:
            user_timeframe_map[tf_str] = TIMEFRAME_MAP[tf_str]
    
    if not user_timeframe_map:
        log_and_print(f"⚠️  No valid timeframes for {account_key}. Using defaults.", "WARNING")
        user_timeframe_map = {tf: TIMEFRAME_MAP[tf] for tf in ["15m", "5m", "30m", "1h", "4h"]}
        user_bars = 500
    
    # If symbol_chunk is provided and not empty, use it
    if symbol_chunk and len(symbol_chunk) > 0:
        symbols_to_process = symbol_chunk
    else:
        # Fallback: extract from config
        symbols_dict = account_cfg.get("SYMBOLS_DICTIONARY", {})
        symbols_to_process = []
        for category, symbol_list in symbols_dict.items():
            if isinstance(symbol_list, list):
                for sym in symbol_list:
                    if sym:
                        symbols_to_process.append((sym, category))
    
    total_in_chunk = len(symbols_to_process)
    log_and_print(f"\n  ⚙️  {account_key.upper()} | Starting | {total_in_chunk} symbols", "INFO")
    log_and_print(f"  ⚙️  {account_key.upper()} | Bars: {user_bars} | Timeframes: {list(user_timeframe_map.keys())}", "INFO")
    
    # ============================================================
    # FETCH AND FILTER SYMBOLS OFFERED BY THE BROKER
    # ============================================================
    broker_symbols = []
    available_symbols_set = set()
    
    try:
        # Initialize MT5 once to fetch all symbols
        ok, _ = initialize_mt5(
            account_cfg["terminal_path"], 
            account_cfg["LOGIN_ID"], 
            account_cfg["PASSWORD"], 
            account_cfg["SERVER"]
        )
        
        if ok:
            # Get all symbols from MT5
            all_symbols = mt5.symbols_get()
            if all_symbols:
                broker_symbols = [s.name for s in all_symbols]
                available_symbols_set = set(broker_symbols)
                
                # Group symbols by category (common prefixes)
                symbol_groups = {}
                for sym in broker_symbols:
                    # Try to categorize by common prefixes
                    prefix = sym.split('.')[0] if '.' in sym else sym[:3]
                    if prefix not in symbol_groups:
                        symbol_groups[prefix] = []
                    symbol_groups[prefix].append(sym)
                
                # ============================================================
                # COMPACT FLEXIBLE DISPLAY WITH BRACKETS
                # ============================================================
                log_and_print(f"\n  📊 {account_key.upper()} | Offered Symbols:", "INFO")
                
                # Build compact display string
                offered_parts = []
                for group, symbols in sorted(symbol_groups.items()):
                    # Format: 📁 GROUP: N symbols
                    part = f"📁 {group.upper()}: {len(symbols)}"
                    offered_parts.append(part)
                
                # Join with commas and wrap in brackets
                offered_display = f"[{', '.join(offered_parts)}]"
                
                # Print in a single line with wrapping if too long
                if len(offered_display) > 200:  # If too long, split into multiple lines
                    log_and_print(f"  {offered_display[:200]}...", "INFO")
                    # Print remaining groups in chunks
                    remaining = offered_display[200:]
                    while remaining:
                        chunk = remaining[:200]
                        log_and_print(f"    {chunk}", "INFO")
                        remaining = remaining[200:]
                else:
                    log_and_print(f"  {offered_display}", "INFO")
                
                # Print total count
                log_and_print(f"  ✅ Total symbols available: {len(broker_symbols)}", "SUCCESS")
                
                # ============================================================
                # FILTER: Only keep symbols that are available from the broker
                # ============================================================
                original_symbols = [sym for sym, _ in symbols_to_process]
                filtered_symbols = []
                missing_symbols = []
                
                for sym, cat in symbols_to_process:
                    if sym in available_symbols_set:
                        filtered_symbols.append((sym, cat))
                    else:
                        missing_symbols.append(sym)
                
                # Update symbols_to_process with only available symbols
                symbols_to_process = filtered_symbols
                
                # Compact display for filtered results
                log_and_print(f"\n  📌 {account_key.upper()} | Filtering Results:", "INFO")
                
                # Show available symbols in compact format
                if filtered_symbols:
                    available_names = [sym for sym, _ in filtered_symbols]
                    available_display = f"  ✅ Process: [{', '.join(available_names)}]"
                    if len(available_display) > 200:
                        log_and_print(f"  ✅ Process: [{', '.join(available_names[:10])} ... and {len(available_names) - 10} more]", "INFO")
                    else:
                        log_and_print(available_display, "INFO")
                    log_and_print(f"     Total: {len(filtered_symbols)} symbols", "INFO")
                
                if missing_symbols:
                    missing_display = f"   Skipped: [{', '.join(missing_symbols)}]"
                    if len(missing_display) > 200:
                        log_and_print(f"   Skipped: [{', '.join(missing_symbols[:10])} ... and {len(missing_symbols) - 10} more]", "WARNING")
                    else:
                        log_and_print(missing_display, "WARNING")
                    log_and_print(f"     Total skipped: {len(missing_symbols)} symbols", "WARNING")
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
        mt5.shutdown()
        result_dict[account_key] = 0
        return
    
    log_and_print(f"\n  {'='*60}", "INFO")
    
    # Check if there are any symbols to process after filtering
    if not symbols_to_process:
        log_and_print(f"  ⚠️  {account_key.upper()} | No symbols to process after filtering. Skipping.", "WARNING")
        result_dict[account_key] = 0
        return
    
    # ============================================================
    # CONTINUE WITH NORMAL PROCESSING - ONLY FOR FILTERED SYMBOLS
    # ============================================================
    
    for symbol, cat in symbols_to_process:
        # Initialize MT5
        ok, _ = initialize_mt5(
            account_cfg["terminal_path"], 
            account_cfg["LOGIN_ID"], 
            account_cfg["PASSWORD"], 
            account_cfg["SERVER"]
        )
        
        if not ok:
            log_and_print(f"  ⚠️  {account_key.upper()} | Connection failed | {symbol}", "ERROR")
            continue

        try:
            log_and_print(f"  📈 {account_key.upper()} | Processing | {symbol} ({cat})", "INFO")
            
            base_folder = account_cfg["BASE_FOLDER"]
            sym_folder = os.path.join(base_folder, symbol.replace(" ", "_"))
            
            # ============================================================
            # DELETE EXISTING SYMBOL FOLDER BEFORE PROCESSING (FRESH START)
            # ============================================================
            if os.path.exists(sym_folder):
                try:
                    shutil.rmtree(sym_folder)
                    log_and_print(f"  🗑️  {account_key.upper()} | Deleted existing folder: {sym_folder}", "INFO")
                except Exception as e:
                    log_and_print(f"  ⚠️  {account_key.upper()} | Failed to delete folder {sym_folder}: {str(e)}", "WARNING")
            
            # Create fresh folder
            os.makedirs(sym_folder, exist_ok=True)

            # Use user-specific timeframes
            for tf_str, mt5_tf in user_timeframe_map.items():
                tf_folder = os.path.join(sym_folder, tf_str)
                os.makedirs(tf_folder, exist_ok=True)

                # Use user-specific bars
                df, _ = fetch_ohlcv_data(symbol, mt5_tf, user_bars)
                if df is not None and not df.empty:
                    df["symbol"] = symbol
                    save_newest_oldest_df(df, symbol, tf_str, tf_folder)
                    
                    chart_path, _ = generate_and_save_chart_df(df, symbol, tf_str, tf_folder)
                    slice_counts, _ = generate_and_save_chart_slice(symbol, tf_str, tf_folder)
                    
                    if slice_counts:
                        save_sliced_newest_oldest_json(symbol, tf_str, tf_folder, slice_counts)
            
            ticks_value(symbol, sym_folder, account_key, account_cfg["BASE_FOLDER"], [symbol])
            processed_count += 1
            log_and_print(f"  ✅ {account_key.upper()} | Completed | {symbol}", "SUCCESS")
            
        except Exception as e:
            log_and_print(f"   {account_key.upper()} | Error on {symbol}: {str(e)[:50]}", "ERROR")
        finally:
            mt5.shutdown()
    
    result_dict[account_key] = processed_count
    
    # Final summary for this account
    log_and_print(f"  🏁 {account_key.upper()} | Finished | {processed_count}/{len(symbols_to_process)} symbols processed", "SUCCESS")
    if processed_count < len(symbols_to_process):
        log_and_print(f"  ⚠️  {account_key.upper()} | {len(symbols_to_process) - processed_count} symbols failed", "WARNING")
    log_and_print(f"  {'='*60}\n", "INFO")

def process_account_worker(account_key, account_cfg, symbol_chunk, TIMEFRAME_MAP, result_dict):
    """
    This function runs in its own process.
    Uses dynamic bars and timeframes from user config.
    Filters symbols to only those available from the broker.
    Supports per-symbol timeframes: "BTCUSD, specific_timeframes[15m]"
    """
    processed_count = 0
    
    # Get user-specific configuration
    user_bars = account_cfg.get("OHLC_BARS", 500)
    user_timeframes = account_cfg.get("OHLC_TIMEFRAMES", ["15m", "5m", "30m", "1h", "4h"])
    
    # Build timeframe map for this user
    user_timeframe_map = {}
    for tf_str in user_timeframes:
        if tf_str in TIMEFRAME_MAP:
            user_timeframe_map[tf_str] = TIMEFRAME_MAP[tf_str]
    
    if not user_timeframe_map:
        log_and_print(f"⚠️  No valid timeframes for {account_key}. Using defaults.", "WARNING")
        user_timeframe_map = {tf: TIMEFRAME_MAP[tf] for tf in ["15m", "5m", "30m", "1h", "4h"]}
        user_bars = 500
    
    # If symbol_chunk is provided and not empty, use it
    if symbol_chunk and len(symbol_chunk) > 0:
        symbols_to_process = symbol_chunk
    else:
        # Fallback: extract from config
        symbols_dict = account_cfg.get("SYMBOLS_DICTIONARY", {})
        symbols_to_process = []
        for category, symbol_list in symbols_dict.items():
            if isinstance(symbol_list, list):
                for sym in symbol_list:
                    if sym:
                        symbols_to_process.append((sym, category))
    
    total_in_chunk = len(symbols_to_process)
    log_and_print(f"\n  ⚙️  {account_key.upper()} | Starting | {total_in_chunk} symbols", "INFO")
    log_and_print(f"  ⚙️  {account_key.upper()} | Bars: {user_bars} | Global Timeframes: {list(user_timeframe_map.keys())}", "INFO")
    
    # ============================================================
    # FETCH AND FILTER SYMBOLS OFFERED BY THE BROKER
    # ============================================================
    broker_symbols = []
    available_symbols_set = set()
    
    try:
        # Initialize MT5 once to fetch all symbols
        ok, _ = initialize_mt5(
            account_cfg["terminal_path"], 
            account_cfg["LOGIN_ID"], 
            account_cfg["PASSWORD"], 
            account_cfg["SERVER"]
        )
        
        if ok:
            # Get all symbols from MT5
            all_symbols = mt5.symbols_get()
            if all_symbols:
                broker_symbols = [s.name for s in all_symbols]
                available_symbols_set = set(broker_symbols)
                
                # Group symbols by category (common prefixes)
                symbol_groups = {}
                for sym in broker_symbols:
                    # Try to categorize by common prefixes
                    prefix = sym.split('.')[0] if '.' in sym else sym[:3]
                    if prefix not in symbol_groups:
                        symbol_groups[prefix] = []
                    symbol_groups[prefix].append(sym)
                
                # ============================================================
                # COMPACT FLEXIBLE DISPLAY WITH BRACKETS
                # ============================================================
                log_and_print(f"\n  📊 {account_key.upper()} | Offered Symbols:", "INFO")
                
                # Build compact display string
                offered_parts = []
                for group, symbols in sorted(symbol_groups.items()):
                    # Format: 📁 GROUP: N symbols
                    part = f"📁 {group.upper()}: {len(symbols)}"
                    offered_parts.append(part)
                
                # Join with commas and wrap in brackets
                offered_display = f"[{', '.join(offered_parts)}]"
                
                # Print in a single line with wrapping if too long
                if len(offered_display) > 200:  # If too long, split into multiple lines
                    log_and_print(f"  {offered_display[:200]}...", "INFO")
                    # Print remaining groups in chunks
                    remaining = offered_display[200:]
                    while remaining:
                        chunk = remaining[:200]
                        log_and_print(f"    {chunk}", "INFO")
                        remaining = remaining[200:]
                else:
                    log_and_print(f"  {offered_display}", "INFO")
                
                # Print total count
                log_and_print(f"  ✅ Total symbols available: {len(broker_symbols)}", "SUCCESS")
                
                # ============================================================
                # FILTER: Only keep symbols that are available from the broker
                # AND extract per-symbol timeframes using new syntax
                # ============================================================
                filtered_symbols = []
                missing_symbols = []
                
                # Dictionary to store per-symbol timeframes
                symbol_timeframes_map = {}
                
                for sym_item, cat in symbols_to_process:
                    # Initialize variables
                    symbol_name = sym_item
                    custom_timeframes = None
                    
                    # Check if this is a string with custom timeframes
                    # Format: "BTCUSD, specific_timeframes[15m, 1h, 4h]"
                    # or: "BTCUSD, specific_timeframes[15m]"
                    if isinstance(sym_item, str):
                        # Look for the pattern: "symbol, specific_timeframes[timeframes]"
                        if 'specific_timeframes[' in sym_item and ']' in sym_item:
                            # Split by the specific_timeframes pattern
                            parts = sym_item.split('specific_timeframes[')
                            # First part is the symbol name (remove trailing comma and spaces)
                            symbol_name = parts[0].strip()
                            # Remove trailing comma if present
                            if symbol_name.endswith(','):
                                symbol_name = symbol_name[:-1].strip()
                            
                            # Second part contains the timeframes (remove closing bracket)
                            timeframe_part = parts[1].split(']')[0].strip()
                            
                            # Parse timeframe strings like "15m, 1h, 4h" or "15m"
                            custom_timeframes = []
                            # Split by comma and clean
                            for tf in timeframe_part.split(','):
                                tf_clean = tf.strip()
                                if tf_clean in TIMEFRAME_MAP:
                                    custom_timeframes.append(tf_clean)
                                else:
                                    # Try to extract timeframe from patterns like "15m" or "1h"
                                    for word in tf_clean.split():
                                        if word in TIMEFRAME_MAP:
                                            custom_timeframes.append(word)
                            
                            # If we found valid timeframes, store them
                            if custom_timeframes:
                                log_and_print(f"  📌 {symbol_name} has custom timeframes: {custom_timeframes}", "INFO")
                                symbol_timeframes_map[symbol_name] = custom_timeframes
                            else:
                                log_and_print(f"  ⚠️  {symbol_name} specified timeframes but none were valid: {sym_item}", "WARNING")
                    
                    # Now check if the symbol exists in the broker
                    symbol_found = False
                    matched_symbol = None
                    
                    # Strategy 1: Exact match
                    if symbol_name in available_symbols_set:
                        symbol_found = True
                        matched_symbol = symbol_name
                        log_and_print(f"  ✅ {symbol_name} matched exactly", "INFO")
                    
                    # Strategy 2: Case-insensitive match
                    if not symbol_found:
                        for avail_sym in available_symbols_set:
                            if avail_sym.upper() == symbol_name.upper():
                                symbol_found = True
                                matched_symbol = avail_sym
                                log_and_print(f"  ✅ {symbol_name} matched as {avail_sym} (case-insensitive)", "INFO")
                                break
                    
                    # Strategy 3: Partial match (for symbols with suffixes like .M, .pro, .cash)
                    if not symbol_found:
                        for avail_sym in available_symbols_set:
                            # Check if symbol_name is a prefix of the available symbol
                            if avail_sym.upper().startswith(symbol_name.upper()) or \
                               symbol_name.upper() in avail_sym.upper():
                                symbol_found = True
                                matched_symbol = avail_sym
                                log_and_print(f"  ✅ {symbol_name} matched as {avail_sym} (partial match)", "INFO")
                                break
                    
                    # Use the matched symbol if found
                    if symbol_found and matched_symbol:
                        filtered_symbols.append((matched_symbol, cat))
                        
                        # If this symbol had custom timeframes, store them with the matched name
                        if symbol_name in symbol_timeframes_map:
                            # Store with the actual MT5 symbol name
                            symbol_timeframes_map[matched_symbol] = symbol_timeframes_map.pop(symbol_name)
                    else:
                        missing_symbols.append(symbol_name)
                        log_and_print(f"  ❌ {symbol_name} not found in MT5 symbols", "WARNING")
                
                # Update symbols_to_process with only available symbols
                symbols_to_process = filtered_symbols
                
                # Compact display for filtered results
                log_and_print(f"\n  📌 {account_key.upper()} | Filtering Results:", "INFO")
                
                # Show available symbols in compact format
                if filtered_symbols:
                    available_names = [sym for sym, _ in filtered_symbols]
                    available_display = f"  ✅ Process: [{', '.join(available_names)}]"
                    if len(available_display) > 200:
                        log_and_print(f"  ✅ Process: [{', '.join(available_names[:10])} ... and {len(available_names) - 10} more]", "INFO")
                    else:
                        log_and_print(available_display, "INFO")
                    log_and_print(f"     Total: {len(filtered_symbols)} symbols", "INFO")
                    
                    # Show which symbols have custom timeframes
                    if symbol_timeframes_map:
                        custom_symbols = list(symbol_timeframes_map.keys())
                        log_and_print(f"     Custom timeframes: {len(custom_symbols)} symbols", "INFO")
                        for sym in custom_symbols:
                            log_and_print(f"       - {sym}: {symbol_timeframes_map[sym]}", "INFO")
                
                if missing_symbols:
                    missing_display = f"   Skipped: [{', '.join(missing_symbols)}]"
                    if len(missing_display) > 200:
                        log_and_print(f"   Skipped: [{', '.join(missing_symbols[:10])} ... and {len(missing_symbols) - 10} more]", "WARNING")
                    else:
                        log_and_print(missing_display, "WARNING")
                    log_and_print(f"     Total skipped: {len(missing_symbols)} symbols", "WARNING")
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
        mt5.shutdown()
        result_dict[account_key] = 0
        return
    
    log_and_print(f"\n  {'='*60}", "INFO")
    
    # Check if there are any symbols to process after filtering
    if not symbols_to_process:
        log_and_print(f"  ⚠️  {account_key.upper()} | No symbols to process after filtering. Skipping.", "WARNING")
        result_dict[account_key] = 0
        return
    
    # ============================================================
    # CONTINUE WITH NORMAL PROCESSING - ONLY FOR FILTERED SYMBOLS
    # ============================================================
    
    for symbol, cat in symbols_to_process:
        # Initialize MT5
        ok, _ = initialize_mt5(
            account_cfg["terminal_path"], 
            account_cfg["LOGIN_ID"], 
            account_cfg["PASSWORD"], 
            account_cfg["SERVER"]
        )
        
        if not ok:
            log_and_print(f"  ⚠️  {account_key.upper()} | Connection failed | {symbol}", "ERROR")
            continue

        try:
            # ============================================================
            # DETERMINE TIMEFRAMES FOR THIS SYMBOL
            # ============================================================
            # Check if this symbol has custom timeframes
            if symbol in symbol_timeframes_map:
                # Use custom timeframes for this symbol
                symbol_timeframes = symbol_timeframes_map[symbol]
                # Build timeframe map for this specific symbol
                symbol_tf_map = {}
                for tf_str in symbol_timeframes:
                    if tf_str in TIMEFRAME_MAP:
                        symbol_tf_map[tf_str] = TIMEFRAME_MAP[tf_str]
                
                log_and_print(f"  📌 {account_key.upper()} | {symbol} using custom timeframes: {list(symbol_tf_map.keys())}", "INFO")
            else:
                # Use global timeframes for this symbol
                symbol_tf_map = user_timeframe_map
                log_and_print(f"  📌 {account_key.upper()} | {symbol} using global timeframes: {list(symbol_tf_map.keys())}", "INFO")
            
            # Skip if no valid timeframes
            if not symbol_tf_map:
                log_and_print(f"  ⚠️  {account_key.upper()} | {symbol} has no valid timeframes. Skipping.", "WARNING")
                mt5.shutdown()
                continue
            
            log_and_print(f"  📈 {account_key.upper()} | Processing | {symbol} ({cat})", "INFO")
            
            base_folder = account_cfg["BASE_FOLDER"]
            sym_folder = os.path.join(base_folder, symbol.replace(" ", "_"))
            
            # ============================================================
            # DELETE EXISTING SYMBOL FOLDER BEFORE PROCESSING (FRESH START)
            # ============================================================
            if os.path.exists(sym_folder):
                try:
                    shutil.rmtree(sym_folder)
                    log_and_print(f"  🗑️  {account_key.upper()} | Deleted existing folder: {sym_folder}", "INFO")
                except Exception as e:
                    log_and_print(f"  ⚠️  {account_key.upper()} | Failed to delete folder {sym_folder}: {str(e)}", "WARNING")
            
            # Create fresh folder
            os.makedirs(sym_folder, exist_ok=True)

            # Use symbol-specific timeframes
            for tf_str, mt5_tf in symbol_tf_map.items():
                tf_folder = os.path.join(sym_folder, tf_str)
                os.makedirs(tf_folder, exist_ok=True)

                # Use user-specific bars
                df, _ = fetch_ohlcv_data(symbol, mt5_tf, user_bars)
                if df is not None and not df.empty:
                    df["symbol"] = symbol
                    save_newest_oldest_df(df, symbol, tf_str, tf_folder)
                    
                    chart_path, _ = generate_and_save_chart_df(df, symbol, tf_str, tf_folder)
                    slice_counts, _ = generate_and_save_chart_slice(symbol, tf_str, tf_folder)
                    
                    if slice_counts:
                        save_sliced_newest_oldest_json(symbol, tf_str, tf_folder, slice_counts)
            
            ticks_value(symbol, sym_folder, account_key, account_cfg["BASE_FOLDER"], [symbol])
            processed_count += 1
            log_and_print(f"  ✅ {account_key.upper()} | Completed | {symbol}", "SUCCESS")
            
        except Exception as e:
            log_and_print(f"   {account_key.upper()} | Error on {symbol}: {str(e)[:50]}", "ERROR")
        finally:
            mt5.shutdown()
    
    result_dict[account_key] = processed_count
    
    # Final summary for this account
    log_and_print(f"  🏁 {account_key.upper()} | Finished | {processed_count}/{len(symbols_to_process)} symbols processed", "SUCCESS")
    if processed_count < len(symbols_to_process):
        log_and_print(f"  ⚠️  {account_key.upper()} | {len(symbols_to_process) - processed_count} symbols failed", "WARNING")
    log_and_print(f"  {'='*60}\n", "INFO")
      
def main_once():
    """Main execution function with loop support."""
    
    # Parse command line arguments
    run_as_loop = False
    loop_interval = 0  # Default 5 minutes between loops
    max_loops = None  # None means infinite
    
    # Check for command line arguments
    for arg in sys.argv[1:]:
        if arg.startswith('--loop='):
            loop_value = arg.split('=')[1].lower()
            run_as_loop = loop_value in ['true', 'yes', '1', 'on']
        elif arg.startswith('--interval='):
            try:
                loop_interval = int(arg.split('=')[1])
            except ValueError:
                log_and_print(f"Invalid interval value: {arg.split('=')[1]}. Using default 300 seconds.", "WARNING")
        elif arg.startswith('--max-loops='):
            try:
                max_loops = int(arg.split('=')[1])
            except ValueError:
                log_and_print(f"Invalid max-loops value: {arg.split('=')[1]}. Running infinite loops.", "WARNING")
    
    log_and_print("\n" + "┌" + "─"*58 + "┐", "INFO")
    log_and_print("│                 🔄 SYNAREX DATA PIPELINE                   │", "INFO")
    log_and_print("│" + " " * 58 + "│", "INFO")
    log_and_print(f"│  Loop Mode: {'ENABLED' if run_as_loop else 'DISABLED'}" + " " * (58 - len(f"│  Loop Mode: {'ENABLED' if run_as_loop else 'DISABLED'}")) + "│", "INFO")
    if run_as_loop:
        log_and_print(f"│  Interval: {loop_interval}s" + " " * (58 - len(f"│  Interval: {loop_interval}s")) + "│", "INFO")
        if max_loops:
            log_and_print(f"│  Max Loops: {max_loops}" + " " * (58 - len(f"│  Max Loops: {max_loops}")) + "│", "INFO")
        else:
            log_and_print("│  Max Loops: Infinite" + " " * (58 - len("│  Max Loops: Infinite")) + "│", "INFO")
    log_and_print("└" + "─"*58 + "┘\n", "INFO")
    
    loop_count = 0
    
    while True:
        loop_count += 1
        
        if run_as_loop:
            log_and_print("\n" + "="*60, "INFO")
            log_and_print(f"🔄 LOOP #{loop_count} STARTED", "INFO")
            log_and_print("="*60, "INFO")
        
        # Execute the main pipeline
        success = fetch_charts_all_brokers()
        
        if success:
            log_and_print("\n" + "┌" + "─"*58 + "┐", "SUCCESS")
            log_and_print("│                   ✅ PIPELINE COMPLETED                     │", "SUCCESS")
            log_and_print("├" + "─"*58 + "┤", "SUCCESS")
            log_and_print("│ • Charts generated                • Candle data saved        │", "SUCCESS")
            log_and_print("│ • PH/PL analysis completed        • Arrow detection done     │", "SUCCESS")
            log_and_print("└" + "─"*58 + "┘\n", "SUCCESS")
        else:
            log_and_print("\n" + "┌" + "─"*58 + "┐", "ERROR")
            log_and_print("│                   PIPELINE FAILED                        │", "ERROR")
            log_and_print("├" + "─"*58 + "┤", "ERROR")
            log_and_print("│ Check error log for details                                  │", "ERROR")
            log_and_print("└" + "─"*58 + "┘\n", "ERROR")
        
        # Check loop conditions
        if not run_as_loop:
            # Single execution - exit
            log_and_print("🏁 Single execution completed. Exiting...", "INFO")
            break
        
        # Check max loops
        if max_loops and loop_count >= max_loops:
            log_and_print(f"🏁 Maximum loops ({max_loops}) reached. Exiting...", "INFO")
            break
        
        # Wait before next iteration
        log_and_print(f"⏳ Waiting {loop_interval} seconds before next loop...", "INFO")
        time.sleep(loop_interval)
        
        # Optional: Reload configuration for next loop
        global ohlcdictionary
        log_and_print("🔄 Reloading configuration...", "INFO")
        ohlcdictionary = load_ohlc_dictionary()

def main_loop():
    """Main execution function with loop support."""
    
    # Parse command line arguments
    run_as_loop = True
    loop_interval = 0  # Default 5 minutes between loops
    max_loops = None  # None means infinite
    
    # Check for command line arguments
    for arg in sys.argv[1:]:
        if arg.startswith('--loop='):
            loop_value = arg.split('=')[1].lower()
            run_as_loop = loop_value in ['true', 'yes', '1', 'on']
        elif arg.startswith('--interval='):
            try:
                loop_interval = int(arg.split('=')[1])
            except ValueError:
                log_and_print(f"Invalid interval value: {arg.split('=')[1]}. Using default 300 seconds.", "WARNING")
        elif arg.startswith('--max-loops='):
            try:
                max_loops = int(arg.split('=')[1])
            except ValueError:
                log_and_print(f"Invalid max-loops value: {arg.split('=')[1]}. Running infinite loops.", "WARNING")
    
    log_and_print("\n" + "┌" + "─"*58 + "┐", "INFO")
    log_and_print("│                 🔄 SYNAREX DATA PIPELINE                   │", "INFO")
    log_and_print("│" + " " * 58 + "│", "INFO")
    log_and_print(f"│  Loop Mode: {'ENABLED' if run_as_loop else 'DISABLED'}" + " " * (58 - len(f"│  Loop Mode: {'ENABLED' if run_as_loop else 'DISABLED'}")) + "│", "INFO")
    if run_as_loop:
        log_and_print(f"│  Interval: {loop_interval}s" + " " * (58 - len(f"│  Interval: {loop_interval}s")) + "│", "INFO")
        if max_loops:
            log_and_print(f"│  Max Loops: {max_loops}" + " " * (58 - len(f"│  Max Loops: {max_loops}")) + "│", "INFO")
        else:
            log_and_print("│  Max Loops: Infinite" + " " * (58 - len("│  Max Loops: Infinite")) + "│", "INFO")
    log_and_print("└" + "─"*58 + "┘\n", "INFO")
    
    loop_count = 0
    
    while True:
        loop_count += 1
        
        if run_as_loop:
            log_and_print("\n" + "="*60, "INFO")
            log_and_print(f"🔄 LOOP #{loop_count} STARTED", "INFO")
            log_and_print("="*60, "INFO")
        
        # Execute the main pipeline
        success = fetch_charts_all_brokers()
        
        if success:
            log_and_print("\n" + "┌" + "─"*58 + "┐", "SUCCESS")
            log_and_print("│                   ✅ PIPELINE COMPLETED                     │", "SUCCESS")
            log_and_print("├" + "─"*58 + "┤", "SUCCESS")
            log_and_print("│ • Charts generated                • Candle data saved        │", "SUCCESS")
            log_and_print("│ • PH/PL analysis completed        • Arrow detection done     │", "SUCCESS")
            log_and_print("└" + "─"*58 + "┘\n", "SUCCESS")
        else:
            log_and_print("\n" + "┌" + "─"*58 + "┐", "ERROR")
            log_and_print("│                   PIPELINE FAILED                        │", "ERROR")
            log_and_print("├" + "─"*58 + "┤", "ERROR")
            log_and_print("│ Check error log for details                                  │", "ERROR")
            log_and_print("└" + "─"*58 + "┘\n", "ERROR")
        
        # Check loop conditions
        if not run_as_loop:
            # Single execution - exit
            log_and_print("🏁 Single execution completed. Exiting...", "INFO")
            break
        
        # Check max loops
        if max_loops and loop_count >= max_loops:
            log_and_print(f"🏁 Maximum loops ({max_loops}) reached. Exiting...", "INFO")
            break
        
        # Wait before next iteration
        log_and_print(f"⏳ Waiting {loop_interval} seconds before next loop...", "INFO")
        time.sleep(loop_interval)
        
        # Optional: Reload configuration for next loop
        global ohlcdictionary
        log_and_print("🔄 Reloading configuration...", "INFO")
        ohlcdictionary = load_ohlc_dictionary()

if __name__ == "__main__":
    main_loop()
