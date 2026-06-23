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






INV_PATH = r"C:\xampp\htdocs\synapse\synarex\usersdata\investors"
UPDATED_INVESTORS = r"C:\xampp\htdocs\synapse\synarex\updated_investors.json"
INVESTOR_USERS = r"C:\xampp\htdocs\synapse\synarex\usersdata\investors\investors.json"
VERIFIED_INVESTORS = r"C:\xampp\htdocs\synapse\synarex\verified_investors.json"
ISSUES_INVESTORS = r"C:\xampp\htdocs\synapse\synarex\issues_investors.json"
NORMALIZE_SYMBOLS_PATH = r"C:\xampp\htdocs\synapse\synarex\symbols_normalization.json"
DEFAULT_ACCOUNTMANAGEMENT = r"C:\xampp\htdocs\synapse\synarex\default_accountmanagement.json"
DEFAULT_PATH = r"C:\xampp\htdocs\synapse\synarex"
NORM_FILE_PATH = Path(DEFAULT_PATH) / "symbols_normalization.json"
BASE_ERROR_FOLDER = r"C:\xampp\htdocs\synapse\synarex\usersdata\debugs"
TIMEFRAME_MAP = {
    "1m": mt5.TIMEFRAME_M1,
    "5m": mt5.TIMEFRAME_M5,
    "15m": mt5.TIMEFRAME_M15,
    "30m": mt5.TIMEFRAME_M30,
    "1h": mt5.TIMEFRAME_H1,
    "4h": mt5.TIMEFRAME_H4
}
ERROR_JSON_PATH = os.path.join(BASE_ERROR_FOLDER, "chart_errors.json")

def load_investor_users():
    """Load investor users config from JSON file."""
    INVESTOR_USERS_PATH = r"C:\xampp\htdocs\synapse\synarex\usersdata\investors\investors.json"
    
    if not os.path.exists(INVESTOR_USERS_PATH):
        print(f"CRITICAL: {INVESTOR_USERS_PATH} NOT FOUND! Using empty config.", "CRITICAL")
        return {}

    try:
        with open(INVESTOR_USERS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Convert numeric strings back to int where needed
        for investor_id, cfg in data.items():
            if "LOGIN_ID" in cfg and isinstance(cfg["LOGIN_ID"], str):
                cfg["LOGIN_ID"] = cfg["LOGIN_ID"].strip()
        
        return data

    except json.JSONDecodeError as e:
        print(f"Invalid JSON in investors.json: {e}", "CRITICAL")
        return {}
    except Exception as e:
        print(f"Failed to load investors.json: {e}", "CRITICAL")
        return {}          
investor_users = load_investor_users()

def save_errors(error_log):
    """Save error log to JSON file."""
    try:
        os.makedirs(BASE_ERROR_FOLDER, exist_ok=True)
        with open(ERROR_JSON_PATH, 'w') as f:
            json.dump(error_log, f, indent=4)
        print("Error log saved", "ERROR")
    except Exception as e:
        print(f"Failed to save error log: {str(e)}", "ERROR")

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
        print(f"MT5 terminal executable not found: {terminal_path}", "ERROR")
        return False, error_log

    try:
        if not mt5.initialize(
            path=terminal_path,
            login=int(login_id),
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
            print(f"Failed to initialize MT5: {mt5.last_error()}", "ERROR")
            return False, error_log

        if not mt5.login(login=int(login_id), server=server, password=password):
            error_log.append({
                "timestamp": datetime.now(pytz.timezone('Africa/Lagos')).strftime('%Y-%m-%d %H:%M:%S.%f+01:00'),
                "error": f"Failed to login to MT5: {mt5.last_error()}",
                "broker": server
            })
            save_errors(error_log)
            print(f"Failed to login to MT5: {mt5.last_error()}", "ERROR")
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
        print(f"Unexpected error in initialize_mt5: {str(e)}", "ERROR")
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
        print(f"Failed to retrieve symbols: {mt5.last_error()}", "ERROR")
        return [], error_log

    available_symbols = [s.name for s in symbols]
    print(f"Retrieved {len(available_symbols)} symbols", "INFO")
    return available_symbols, error_log

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
        print(err_msg, "ERROR")
        return None, [{"error": err_msg, "timestamp": timestamp}]

    # --- Step 2: Fetch rates ---
    # Position 0 is the current forming candle. 
    # This fetches 'bars' number of candles ending at the current live one.
    rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, bars)

    if rates is None or len(rates) == 0:
        last_err = mt5.last_error()
        err_msg = f"No data for {symbol}: {last_err}"
        print(err_msg, "ERROR")
        return None, [{"error": err_msg, "timestamp": timestamp}]

    available_bars = len(rates)
    
    # Convert to DataFrame
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.set_index("time")

    # Standardize dtypes
    df = df.astype({
        "open": float, "high": float, "low": float, "close": float,
        "tick_volume": float, "spread": int, "real_volume": float
    })
    df.rename(columns={"tick_volume": "volume"}, inplace=True)

    print(f"Fetched {available_bars} bars (including live candle) for {symbol}", "INFO")
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
            print(error_msg, "ERROR")
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

        # Latest completed candle: second from end (-1)
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

        print(f"✓ {symbol} {timeframe_str} | JSON saved | {len(all_candles)} candles", "SUCCESS")

    except Exception as e:
        err = f"save_newest_oldest_df failed: {str(e)}"
        print(err, "ERROR")
        error_log.append({"error": err, "timestamp": now.isoformat()})
        save_errors(error_log)

    return error_log

def generate_and_save_chart_df(df, symbol, timeframe_str, timeframe_folder):
    """Generate and save only the basic full chart. Sliced charts have been removed."""
    error_log = []
    
    chart_path = os.path.join(timeframe_folder, "chart.png")
    
    try:
        # -----------------------------------------------------------------
        # DYNAMIC WIDTH CALCULATION
        # -----------------------------------------------------------------
        num_candles = len(df)
        
        # Configuration for readable candles
        MIN_CANDLE_WIDTH = 20  # Minimum pixels per candle for readability
        MAX_CANDLE_WIDTH = 40  # Maximum pixels per candle (prevents extremely wide images)
        MIN_CANDLE_SPACING = 10  # Minimum pixels between candles
        BASE_HEIGHT = 100  # Base height in inches (original was 10)
        MAX_IMAGE_WIDTH = 90000000  # Maximum width to prevent insane image sizes
        
        # Determine optimal candle width based on number of candles
        if num_candles <= 50:
            # Few candles - make them larger for better visibility
            base_candle_width = 30
            base_spacing_multiplier = 1.8
        elif num_candles <= 200:
            # Medium number of candles - moderate size
            base_candle_width = 20
            base_spacing_multiplier = 1.6
        elif num_candles <= 1000:
            # Many candles - smaller but still readable
            base_candle_width = 12
            base_spacing_multiplier = 1.4
        else:
            # Very many candles - minimum readable size
            base_candle_width = MIN_CANDLE_WIDTH
            base_spacing_multiplier = 1.3
        
        # Apply constraints to candle width
        target_candle_width = max(base_candle_width, MIN_CANDLE_WIDTH)
        target_candle_width = min(target_candle_width, MAX_CANDLE_WIDTH)
        
        # Calculate spacing based on candle width and multiplier
        desired_spacing = target_candle_width * base_spacing_multiplier
        
        # Apply minimum spacing constraint
        actual_spacing = max(desired_spacing, MIN_CANDLE_SPACING)
        
        # Calculate total width needed in pixels
        if num_candles > 1:
            total_width_pixels = actual_spacing * (num_candles - 1) + target_candle_width
        else:
            total_width_pixels = target_candle_width * 2  # For single candle, give it some space
        
        # Add padding for margins (left and right)
        padding_pixels = 200  # Extra space for labels, titles, etc.
        img_width_pixels = int(total_width_pixels + padding_pixels)
        
        # Cap width to prevent insane image sizes
        img_width_pixels = min(img_width_pixels, MAX_IMAGE_WIDTH)
        
        # If width is less than minimum, use minimum
        min_width_pixels = 800
        if img_width_pixels < min_width_pixels:
            img_width_pixels = min_width_pixels
        
        # Convert pixels to inches for matplotlib (assuming 100 dpi as base)
        img_width_inches = img_width_pixels / 100
        
        # Log the dynamic sizing
        print(f"📊 {symbol} {timeframe_str} | {num_candles} candles → {img_width_pixels}px", "INFO")
        
        # -----------------------------------------------------------------
        # ORIGINAL CHART GENERATION WITH DYNAMIC WIDTH
        # -----------------------------------------------------------------
        custom_style = mpf.make_mpf_style(
            base_mpl_style="default",
            marketcolors=mpf.make_marketcolors(
                up="green", down="red", edge="inherit",
                wick={"up": "green", "down": "red"}, volume="gray"
            )
        )

        # Check DataFrame columns to handle different naming conventions
        required_cols = ['Open', 'High', 'Low', 'Close']
        df_cols = df.columns.tolist()
        
        # Check if required columns exist (case-insensitive)
        col_mapping = {}
        for req_col in required_cols:
            found = False
            for df_col in df_cols:
                if df_col.lower() == req_col.lower():
                    col_mapping[req_col] = df_col
                    found = True
                    break
            if not found:
                # If column not found, raise error with helpful message
                raise KeyError(f"Required column '{req_col}' not found in DataFrame. Available columns: {df_cols}")
        
        # Rename columns if necessary to match expected format
        if col_mapping:
            df_plot = df.rename(columns={v: k for k, v in col_mapping.items()})
        else:
            df_plot = df

        # Generate and save only the full chart with dynamic size
        fig, axlist = mpf.plot(
            df_plot, 
            type='candle', 
            style=custom_style, 
            volume=False,
            title=f"{symbol} ({timeframe_str}) - {num_candles} candles", 
            returnfig=True,
            warn_too_much_data=5000,
            figsize=(img_width_inches, BASE_HEIGHT),  # Dynamic width, fixed height
            scale_padding={'left': 0.5, 'right': 1.5, 'top': 0.5, 'bottom': 0.5}  # Add padding
        )
        
        # Set size explicitly (redundant but safe)
        fig.set_size_inches(img_width_inches, BASE_HEIGHT)
        
        # Customize the plot
        for ax in axlist:
            ax.grid(False)
            for line in ax.get_lines():
                if line.get_label() == '':
                    line.set_linewidth(0.5)

        # Save with appropriate DPI - NO CROPPING, save directly
        fig.savefig(chart_path, bbox_inches="tight", dpi=100)  # 100 DPI gives good quality
        plt.close(fig)

        print(f"✓ {symbol} {timeframe_str} | Chart saved | {num_candles} candles", "SUCCESS")

        return chart_path, error_log

    except KeyError as e:
        print(f"Error in chart generation - column error: {e}", "ERROR")
        error_log.append(str(e))
        return None, error_log
    except Exception as e:
        print(f"Error in chart generation: {e}", "ERROR")
        error_log.append(str(e))
        return None, error_log

def backup_investor_users():
    """Backup investor users configuration."""
    main_path = Path(r"C:\xampp\htdocs\synapse\synarex\usersdata\investors\investors.json")
    backup_path = Path(r"C:\xampp\htdocs\synapse\synarex\investors_backup.json")
    
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
        print("Main investor file has valid data → syncing to backup")
        write_json(backup_path, main_data)
        return

    print("Main investor file is empty or invalid → checking backup")
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
    print("Created fresh empty investors.json and backup")

def clear_chart_folder(base_folder: str):
    """Delete ONLY symbols that have NO valid OB-none-OI record on 15m-4h."""
    error_log = []
    IMPORTANT_TFS = {"15m", "30m", "1h", "4h"}

    if not os.path.exists(base_folder):
        print(f"Chart folder {base_folder} does not exist – nothing to clear.", "INFO")
        return True, error_log

    deleted = 0
    kept    = 0

    for item in os.listdir(base_folder):
        item_path = os.path.join(base_folder, item)
        if not os.path.isdir(item_path):
            continue                                 # skip stray files

        # --------------------------------------------------
        # Look for ob_none_oi_data.json inside any timeframe folder
        # --------------------------------------------------
        keep_symbol = False
        for tf in IMPORTANT_TFS:
            json_path = os.path.join(item_path, tf, "ob_none_oi_data.json")
            if not os.path.exists(json_path):
                continue
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # file exists → assume it contains at least one team entry
                keep_symbol = True
                break
            except Exception:
                pass                                 # corrupted → treat as “missing”

        # --------------------------------------------------
        # Delete or keep
        # --------------------------------------------------
        try:
            if keep_symbol:
                kept += 1
                print(f"KEEP   {item_path} (has 15m-4h OB-none-OI)", "INFO")
            else:
                shutil.rmtree(item_path)
                deleted += 1
                print(f"DELETE {item_path} (no 15m-4h record)", "INFO")
        except Exception as e:
            error_log.append({
                "timestamp": datetime.now(pytz.timezone('Africa/Lagos')).strftime(
                    '%Y-%m-%d %H:%M:%S.%f+01:00'),
                "error": f"Failed to handle {item_path}: {str(e)}",
                "broker": base_folder
            })
            print(f"Failed to handle {item_path}: {str(e)}", "ERROR")

    print(
        f"Smart clean finished → {deleted} folders deleted, {kept} folders kept.",
        "SUCCESS")
    return True, error_log

def clear_unknown_investors():
    """Clear unknown investor folders."""
    base_path = INV_PATH
    
    if not os.path.exists(base_path):
        print(f"ERROR: Base directory does not exist:\n    {base_path}")
        return
    
    if not investor_users:
        print("No investors found in investors.json.")
        return

    print("Configured Investors & Folder Check:")
    print("=" * 90)
    
    configured_ids = set()
    investor_details = []
    existing = 0
    missing = 0
    
    for investor_id in investor_users.keys():
        configured_ids.add(investor_id)
        
        folder_path = os.path.join(base_path, investor_id)
        exists = os.path.isdir(folder_path)
        
        marker = "Success" if exists else "Error"
        status = "EXISTS" if exists else "MISSING"
        
        print(f"{marker} Investor {investor_id.ljust(25)} → {status}")
        print(f"    Path: {folder_path}\n")
        
        investor_details.append({
            'id': investor_id,
            'path': folder_path,
            'exists': exists
        })
        
        if exists: existing += 1
        else: missing += 1
    
    print("=" * 90)
    print(f"Total configured: {len(investor_users)} investor(s) | {existing} folder(s) exist | {missing} missing")

    # Auto-delete orphaned folders
    print("\nCleaning Orphaned Investor Folders (AUTO-DELETE enabled)...")
    print("-" * 70)
    
    if not os.path.isdir(base_path):
        print("Base path not accessible.")
    else:
        orphaned = []
        all_folders = [f for f in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, f))]
        
        for folder in all_folders:
            folder_path = os.path.join(base_path, folder)
            if folder not in configured_ids:
                orphaned.append((folder, folder_path))
        
        if orphaned:
            print(f"Deleting {len(orphaned)} orphaned investor folder(s):")
            deleted_count = 0
            for folder, folder_path in orphaned:
                try:
                    shutil.rmtree(folder_path)
                    print(f"  Deleted: {folder}")
                    deleted_count += 1
                except Exception as e:
                    print(f"  Failed to delete {folder}: {e}")
            print(f"\nAuto-clean complete: {deleted_count}/{len(orphaned)} orphaned folders removed.")
        else:
            print("No orphaned investor folders found. Directory is clean!")

    print("-" * 70)
    
    if missing > 0:
        print(f"\nReminder: {missing} configured investor(s) missing their folder!")

def load_accountmanagement_old(investor_id):
    """Load account management config for a specific investor."""
    accountmanagement_path = os.path.join(INV_PATH, investor_id, "accountmanagement.json")
    
    if not os.path.exists(accountmanagement_path):
        print(f"  ⚠️  Investor {investor_id} | accountmanagement.json not found", "WARNING")
        return None
    
    try:
        with open(accountmanagement_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Extract bars value if present
        bars = data.get("bars")
        if bars is None:
            print(f"  ⚠️  Investor {investor_id} | 'bars' not defined in accountmanagement.json", "WARNING")
            return None
        
        # Validate bars is a positive integer
        if not isinstance(bars, int) or bars <= 0:
            print(f"  ⚠️  Investor {investor_id} | 'bars' must be a positive integer, got: {bars}", "WARNING")
            return None
        
        print(f"  📊  Investor {investor_id} | Using bars={bars} from accountmanagement.json", "INFO")
        return bars
        
    except json.JSONDecodeError as e:
        print(f"  ❌  Investor {investor_id} | Invalid JSON in accountmanagement.json: {e}", "ERROR")
        return None
    except Exception as e:
        print(f"  ❌  Investor {investor_id} | Failed to load accountmanagement.json: {e}", "ERROR")
        return None
    
def process_account_worker_old(investor_id, investor_cfg, symbol_chunk, TIMEFRAME_MAP, result_dict):
    """
    This function runs in its own process.
    It stays dedicated to ONE terminal path and processes its specific list of symbols.
    """
    processed_count = 0
    
    # Load bars from accountmanagement.json for this investor
    bars = load_accountmanagement(investor_id)
    
    # Skip this investor if bars is not defined
    if bars is None:
        print(f"  ❌  Investor {investor_id} | SKIPPED - No valid 'bars' value in accountmanagement.json", "ERROR")
        result_dict[investor_id] = 0
        return
    
    # Group symbols by category for cleaner logging
    categories = {}
    for symbol, cat in symbol_chunk:
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(symbol)
    
    # Log the workload for this account
    total_in_chunk = len(symbol_chunk)
    print(f"\n  ⚙️  Investor {investor_id} | Starting | {total_in_chunk} symbols | bars={bars}", "INFO")
    
    for symbol, cat in symbol_chunk:
        # Initialize MT5 for this specific terminal
        ok, _ = initialize_mt5(
            investor_cfg["TERMINAL_PATH"], 
            investor_cfg["LOGIN_ID"], 
            investor_cfg["PASSWORD"], 
            investor_cfg["SERVER"]
        )
        
        if not ok:
            print(f"  ⚠️  Investor {investor_id} | Connection failed | {symbol}", "ERROR")
            continue

        try:
            print(f"  📈 Investor {investor_id} | Processing | {symbol} ({cat}) | bars={bars}", "INFO")
            
            # Use INV_PATH with investor_id as the base folder
            sym_folder = os.path.join(INV_PATH, investor_id, symbol.replace(" ", "_"))
            os.makedirs(sym_folder, exist_ok=True)

            for tf_str, mt5_tf in TIMEFRAME_MAP.items():
                tf_folder = os.path.join(sym_folder, tf_str)
                os.makedirs(tf_folder, exist_ok=True)

                df, _ = fetch_ohlcv_data(symbol, mt5_tf, bars)
                if df is not None and not df.empty:
                    df["symbol"] = symbol
                    save_newest_oldest_df(df, symbol, tf_str, tf_folder)
                    
                    # Generate charts directly without cropping
                    chart_path, _ = generate_and_save_chart_df(df, symbol, tf_str, tf_folder)
                    
                    # CROP CHART REMOVED - Charts are saved as-is without cropping
            processed_count += 1
            print(f"  ✅ Investor {investor_id} | Completed | {symbol}", "SUCCESS")
            
        except Exception as e:
            print(f"  ❌ Investor {investor_id} | Error on {symbol}: {str(e)[:50]}", "ERROR")
        finally:
            mt5.shutdown()
    
    result_dict[investor_id] = processed_count
    print(f"  🏁 Investor {investor_id} | Finished | {processed_count}/{total_in_chunk} symbols processed\n", "SUCCESS")

def load_accountmanagement(investor_id):
    """Load account management config for a specific investor."""
    accountmanagement_path = os.path.join(INV_PATH, investor_id, "accountmanagement.json")
    
    if not os.path.exists(accountmanagement_path):
        print(f"  ⚠️  Investor {investor_id} | accountmanagement.json not found", "WARNING")
        return None, None
    
    try:
        with open(accountmanagement_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Extract bars value if present
        bars = data.get("bars")
        if bars is None:
            print(f"  ⚠️  Investor {investor_id} | 'bars' not defined in accountmanagement.json", "WARNING")
            return None, None
        
        # Validate bars is a positive integer
        if not isinstance(bars, int) or bars <= 0:
            print(f"  ⚠️  Investor {investor_id} | 'bars' must be a positive integer, got: {bars}", "WARNING")
            return None, None
        
        # Extract timeframe list (dynamic)
        timeframes = data.get("timeframe")
        if timeframes is None:
            print(f"  ⚠️  Investor {investor_id} | 'timeframe' not defined in accountmanagement.json", "WARNING")
            return None, None
        
        # Validate timeframe is a list
        if not isinstance(timeframes, list):
            print(f"  ⚠️  Investor {investor_id} | 'timeframe' must be a list, got: {type(timeframes)}", "WARNING")
            return None, None
        
        # Validate each timeframe is supported
        valid_timeframes = []
        for tf in timeframes:
            if tf in TIMEFRAME_MAP:
                valid_timeframes.append(tf)
            else:
                print(f"  ⚠️  Investor {investor_id} | Unsupported timeframe '{tf}', skipping", "WARNING")
        
        if not valid_timeframes:
            print(f"  ❌  Investor {investor_id} | No valid timeframes provided", "ERROR")
            return None, None
        
        print(f"  📊  Investor {investor_id} | Using bars={bars}, timeframes={valid_timeframes}", "INFO")
        return bars, valid_timeframes
        
    except json.JSONDecodeError as e:
        print(f"  ❌  Investor {investor_id} | Invalid JSON in accountmanagement.json: {e}", "ERROR")
        return None, None
    except Exception as e:
        print(f"  ❌  Investor {investor_id} | Failed to load accountmanagement.json: {e}", "ERROR")
        return None, None

def process_account_worker(investor_id, investor_cfg, symbol_chunk, TIMEFRAME_MAP, result_dict):
    """
    This function runs in its own process.
    It stays dedicated to ONE terminal path and processes its specific list of symbols.
    """
    processed_count = 0
    
    # Load bars and timeframes from accountmanagement.json for this investor
    bars, timeframes = load_accountmanagement(investor_id)
    
    # Skip this investor if bars or timeframes is not defined
    if bars is None or timeframes is None:
        print(f"  ❌  Investor {investor_id} | SKIPPED - Missing 'bars' or 'timeframe' in accountmanagement.json", "ERROR")
        result_dict[investor_id] = 0
        return
    
    # Build dynamic timeframe map for this investor
    investor_timeframe_map = {}
    for tf in timeframes:
        if tf in TIMEFRAME_MAP:
            investor_timeframe_map[tf] = TIMEFRAME_MAP[tf]
    
    # Group symbols by category for cleaner logging
    categories = {}
    for symbol, cat in symbol_chunk:
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(symbol)
    
    # Log the workload for this account
    total_in_chunk = len(symbol_chunk)
    print(f"\n  ⚙️  Investor {investor_id} | Starting | {total_in_chunk} symbols | bars={bars} | timeframes={timeframes}", "INFO")
    
    for symbol, cat in symbol_chunk:
        # Initialize MT5 for this specific terminal
        ok, _ = initialize_mt5(
            investor_cfg["TERMINAL_PATH"], 
            investor_cfg["LOGIN_ID"], 
            investor_cfg["PASSWORD"], 
            investor_cfg["SERVER"]
        )
        
        if not ok:
            print(f"  ⚠️  Investor {investor_id} | Connection failed | {symbol}", "ERROR")
            continue

        try:
            print(f"  📈 Investor {investor_id} | Processing | {symbol} ({cat}) | bars={bars} | timeframes={timeframes}", "INFO")
            
            # Use INV_PATH with investor_id as the base folder
            sym_folder = os.path.join(INV_PATH, investor_id, symbol.replace(" ", "_"))
            os.makedirs(sym_folder, exist_ok=True)

            # Process only the timeframes specified in accountmanagement.json
            for tf_str, mt5_tf in investor_timeframe_map.items():
                tf_folder = os.path.join(sym_folder, tf_str)
                os.makedirs(tf_folder, exist_ok=True)

                df, _ = fetch_ohlcv_data(symbol, mt5_tf, bars)
                if df is not None and not df.empty:
                    df["symbol"] = symbol
                    save_newest_oldest_df(df, symbol, tf_str, tf_folder)
                    
                    # Generate charts directly without cropping
                    chart_path, _ = generate_and_save_chart_df(df, symbol, tf_str, tf_folder)
                    
            processed_count += 1
            print(f"  ✅ Investor {investor_id} | Completed | {symbol}", "SUCCESS")
            
        except Exception as e:
            print(f"  ❌ Investor {investor_id} | Error on {symbol}: {str(e)[:50]}", "ERROR")
        finally:
            mt5.shutdown()
    
    result_dict[investor_id] = processed_count
    print(f"  🏁 Investor {investor_id} | Finished | {processed_count}/{total_in_chunk} symbols processed\n", "SUCCESS")

def fetch_charts_all_brokers():
    """Fetch charts for all investors."""
    backup_investor_users()
    category_path = r"C:\xampp\htdocs\synapse\synarex\symbolscategory.json"

    print("\n" + "╔" + "═"*58 + "╗", "INFO")
    print("║           🚀 MULTI-INVESTOR SYNCHRONIZATION ENGINE           ║", "INFO")
    print("╚" + "═"*58 + "╝\n", "INFO")

    try:
        # 1. Load symbols
        with open(category_path, "r", encoding="utf-8") as f:
            categories_data = json.load(f)

        # 2. Get the master list of all symbols to process
        print("📡 Discovering available symbols...", "INFO")
        
        # We use the first available investor to see what symbols are actually on the server
        first_cfg = list(investor_users.values())[0]
        
        ok, _ = initialize_mt5(first_cfg["TERMINAL_PATH"], first_cfg["LOGIN_ID"], first_cfg["PASSWORD"], first_cfg["SERVER"])
        if ok:
            mt5_available, _ = get_symbols()
            mt5.shutdown()
            
            # Build master list with validation
            master_symbol_list = []
            for cat, symbol_list in categories_data.items():
                for sym in symbol_list:
                    if sym in mt5_available:
                        master_symbol_list.append((sym, cat))
        
        total_symbols = len(master_symbol_list)
        if total_symbols == 0:
            print("⚠️  No symbols found to process.", "WARNING")
            return True

        # 3. Split symbols equally across all investors in investor_users
        investors = list(investor_users.items())
        num_investors = len(investors)
        
        # Math to divide symbols into chunks
        avg = total_symbols // num_investors
        rem = total_symbols % num_investors
        chunks = []
        start = 0
        for i in range(num_investors):
            end = start + avg + (1 if i < rem else 0)
            chunks.append(master_symbol_list[start:end])
            start = end

        print("\n" + "─"*60, "INFO")
        print("📋 WORKLOAD DISTRIBUTION", "INFO")
        print("─"*60, "INFO")
        
        for i, (investor_id, _) in enumerate(investors):
            chunk_size = len(chunks[i])
            percentage = (chunk_size / total_symbols) * 100
            bar = "█" * int(percentage/5) + "░" * (20 - int(percentage/5))
            print(f"   Investor {investor_id:18} | {bar} | {chunk_size:3} symbols ({percentage:5.1f}%)", "SUCCESS")
        
        print("─"*60 + "\n", "INFO")
        print(f"🚀 Launching {num_investors} parallel processes...\n", "INFO")

        # 4. Launch Processes
        manager = multiprocessing.Manager()
        final_counts = manager.dict()
        processes = []

        for i, (investor_id, investor_cfg) in enumerate(investors):
            chunk = chunks[i]
            if not chunk: continue
            
            p = multiprocessing.Process(
                target=process_account_worker, 
                args=(investor_id, investor_cfg, chunk, TIMEFRAME_MAP, final_counts)
            )
            processes.append(p)
            p.start()

        # Wait for all investors to finish their work
        for p in processes:
            p.join()

        # 5. Final Summary
        total_processed = sum(final_counts.values())
        
        print("\n" + "╔" + "═"*58 + "╗", "SUCCESS")
        print("║                    🏁 PROCESSING COMPLETE                    ║", "SUCCESS")
        print("╠" + "═"*58 + "╣", "SUCCESS")
        
        for investor_id, count in final_counts.items():
            percentage = (count / total_processed) * 100 if total_processed > 0 else 0
            print(f"║ Investor {investor_id:26} │ {count:3} symbols │ {percentage:5.1f}%", "SUCCESS")
        
        print("╠" + "═"*58 + "╣", "SUCCESS")
        print(f"║ {'TOTAL':30} │ {total_processed:3} symbols │ 100.0%", "SUCCESS")
        print("╚" + "═"*58 + "╝\n", "SUCCESS")

        return True

    except Exception as e:
        print("\n" + "╔" + "═"*58 + "╗", "CRITICAL")
        print("║                    💥 SYSTEM ERROR                            ║", "CRITICAL")
        print("╠" + "═"*58 + "╣", "CRITICAL")
        print(f"║ {str(e):56}", "CRITICAL")
        print("╚" + "═"*58 + "╝\n", "CRITICAL")
        return False

def main():
    print("\n" + "┌" + "─"*58 + "┐", "INFO")
    print("│                 🔄 SYNAREX DATA PIPELINE                   │", "INFO")
    print("└" + "─"*58 + "┘\n", "INFO")
    
    success = fetch_charts_all_brokers()

    if success:
        print("\n" + "┌" + "─"*58 + "┐", "SUCCESS")
        print("│                   ✅ PIPELINE COMPLETED                     │", "SUCCESS")
        print("├" + "─"*58 + "┤", "SUCCESS")
        print("│ • Charts generated                • Candle data saved        │", "SUCCESS")
        print("│ • PH/PL analysis completed        • Arrow detection done     │", "SUCCESS")
        print("└" + "─"*58 + "┘\n", "SUCCESS")
    else:
        print("\n" + "┌" + "─"*58 + "┐", "ERROR")
        print("│                   ❌ PIPELINE FAILED                        │", "ERROR")
        print("├" + "─"*58 + "┤", "ERROR")
        print("│ Check error log for details                                  │", "ERROR")
        print("└" + "─"*58 + "┘\n", "ERROR")

if __name__ == "__main__":
    main()
    


        
         