import ohlc
import techniques
import placeorders
import insiders
import time
import MetaTrader5 as mt5
from pathlib import Path
import json
import os
import time
import random
import multiprocessing as mp

INVESTOR_USERS = r"C:\xampp\htdocs\chronedge\synarex\usersdata\investors\investors.json"
INV_PATH = r"C:\xampp\htdocs\chronedge\synarex\usersdata\investors"
NORMALIZE_SYMBOLS_PATH = r"C:\xampp\htdocs\chronedge\synarex\symbols_normalization.json"
DEFAULT_ACCOUNTMANAGEMENT = r"C:\xampp\htdocs\chronedge\synarex\default_accountmanagement.json"
DEFAULT_PATH = r"C:\xampp\htdocs\chronedge\synarex"
NORM_FILE_PATH = Path(DEFAULT_PATH) / "symbols_normalization.json"

def load_investors_dictionary():
    BROKERS_JSON_PATH = r"C:\xampp\htdocs\chronedge\synarex\usersdata\investors\investors.json"
    """Load brokers config from JSON file with error handling and fallback."""
    if not os.path.exists(BROKERS_JSON_PATH):
        print(f"CRITICAL: {BROKERS_JSON_PATH} NOT FOUND! Using empty config.", "CRITICAL")
        return {}

    try:
        with open(BROKERS_JSON_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Optional: Convert numeric strings back to int where needed
        for user_brokerid, cfg in data.items():
            if "LOGIN_ID" in cfg and isinstance(cfg["LOGIN_ID"], str):
                cfg["LOGIN_ID"] = cfg["LOGIN_ID"].strip()
            if "RISKREWARD" in cfg and isinstance(cfg["RISKREWARD"], (str, float)):
                cfg["RISKREWARD"] = int(cfg["RISKREWARD"])
        
        return data

    except json.JSONDecodeError as e:
        print(f"Invalid JSON in investors.json: {e}", "CRITICAL")
        return {}
    except Exception as e:
        print(f"Failed to load investors.json: {e}", "CRITICAL")
        return {}
usersdictionary = load_investors_dictionary()

def fetch_ohlc():
    try:
        ohlc.main()
        print("ohlc completed.")
    except Exception as e:
        print(f"Error in ohlc: {e}")

def technical_analysis():
    try:
        techniques.main()
        print("technical analysis completed.")
    except Exception as e:
        print(f"Error in techniques: {e}")

def place_orders():
    try:
        placeorders.place_orders_parallel()
        print("Placing real account orders completed.")
    except Exception as e:
        print(f"Error in placeorders: {e}")

def place_demo_orders():
    try:
        placeorders.place_demo_orders_parallel()
        print("Placing demo account orders completed.")
    except Exception as e:
        print(f"Error in placeorders: {e}")

def apply_dynamic_breakeven(inv_id=None):
    """
    Function: Dynamically moves stop loss to breakeven or partial profit levels based on
    running profit reward multiples. Uses breakeven_dictionary from accountmanagement.json
    to determine at which reward levels to adjust SL.
    
    Args:
        inv_id: Optional specific investor ID to process. If None, processes all investors.
        
    Returns:
        dict: Statistics about the processing
    """
    print(f"\n{'='*10} 🎯 DYNAMIC BREAKEVEN: MONITORING RUNNING PROFIT REWARDS {'='*10}")
    if inv_id:
        print(f" Processing single investor: {inv_id}")

    # Track statistics
    stats = {
        "investor_id": inv_id if inv_id else "all",
        "positions_checked": 0,
        "positions_adjusted": 0,
        "positions_skipped": 0,
        "positions_error": 0,
        "breakeven_events": 0,
        "processing_success": False
    }

    # Determine which investors to process
    investors_to_process = [inv_id] if inv_id else usersdictionary.keys()
    total_investors = len(investors_to_process) if not inv_id else 1
    processed = 0

    for user_brokerid in investors_to_process:
        processed += 1
        print(f"\n[{processed}/{total_investors}] {user_brokerid} 🔍 Checking breakeven configurations...")
        
        # Get broker config
        broker_cfg = usersdictionary.get(user_brokerid)
        if not broker_cfg:
            print(f"  └─ ❌ No broker config found")
            continue
        
        inv_root = Path(INV_PATH) / user_brokerid
        acc_mgmt_path = inv_root / "accountmanagement.json"

        if not acc_mgmt_path.exists():
            print(f"  └─ ⚠️  Account config missing. Skipping.")
            continue

        # --- LOAD CONFIG AND CHECK SETTINGS ---
        try:
            with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Check if breakeven is enabled
            settings = config.get("settings", {})
            if not settings.get("enable_breakeven", False):
                print(f"  └─ ⏭️  Breakeven disabled in settings. Skipping.")
                continue
            
            # Get breakeven dictionary
            breakeven_config = settings.get("breakeven_dictionary", [])
            if not breakeven_config:
                print(f"  └─ ⚠️  No breakeven configuration found. Using default.")
                # Default configuration if none provided
                breakeven_config = [
                    {"reward": 1, "breakeven_at_reward": 0.5},
                    {"reward": 2, "breakeven_at_reward": 1},
                    {"reward": 3, "breakeven_at_reward": 1.5}
                ]
            
            # Sort by reward level (ascending) to process in order
            breakeven_config.sort(key=lambda x: x["reward"])
            
            print(f"  └─ ✅ Breakeven enabled with {len(breakeven_config)} reward levels:")
            for level in breakeven_config:
                print(f"       • At {level['reward']}R profit → Move SL to {level['breakeven_at_reward']}R")
            
        except Exception as e:
            print(f"  └─ ❌ Failed to read config: {e}")
            stats["positions_error"] += 1
            continue

        # --- ACCOUNT INITIALIZATION ---
        print(f"  └─ 🔌 Initializing account connection...")
        
        login_id = int(broker_cfg['LOGIN_ID'])
        mt5_path = broker_cfg["TERMINAL_PATH"]
        
        print(f"      • Terminal Path: {mt5_path}")
        print(f"      • Login ID: {login_id}")

        # Check login status
        acc = mt5.account_info()
        if acc is None or acc.login != login_id:
            print(f"      🔑 Logging into account...")
            if not mt5.login(login_id, password=broker_cfg["PASSWORD"], server=broker_cfg["SERVER"]):
                error = mt5.last_error()
                print(f"  └─ ❌ login failed: {error}")
                stats["positions_error"] += 1
                continue
            print(f"      ✅ Successfully logged into account")
        else:
            print(f"      ✅ Already logged into account")

        acc_info = mt5.account_info()
        if not acc_info:
            print(f"  └─ ❌ Failed to get account info")
            stats["positions_error"] += 1
            continue
            
        balance = acc_info.balance
        print(f"\n  └─ 📊 Account Balance: ${balance:,.2f}")

        # --- CHECK ALL OPEN POSITIONS ---
        positions = mt5.positions_get()
        investor_positions_checked = 0
        investor_positions_adjusted = 0
        investor_positions_skipped = 0
        investor_positions_error = 0
        investor_breakeven_events = 0

        # Define position types for better readability
        POSITION_TYPES = {
            mt5.POSITION_TYPE_BUY: "BUY",
            mt5.POSITION_TYPE_SELL: "SELL"
        }

        if positions:
            print(f"\n  └─ 🔍 Scanning {len(positions)} open positions for breakeven opportunities...")
            
            for position in positions:
                investor_positions_checked += 1
                stats["positions_checked"] += 1
                
                position_type_name = POSITION_TYPES.get(position.type, f"Unknown Type {position.type}")
                
                # Skip positions without SL
                if position.sl == 0:
                    print(f"\n    └─ 📋 Position #{position.ticket} | {position_type_name} | {position.symbol}")
                    print(f"       ⚠️  No SL set - cannot manage breakeven. Skipping.")
                    investor_positions_skipped += 1
                    stats["positions_skipped"] += 1
                    continue

                # Get symbol info
                symbol_info = mt5.symbol_info(position.symbol)
                if not symbol_info:
                    print(f"\n    └─ 📋 Position #{position.ticket} | {position.symbol}")
                    print(f"       ⚠️  Cannot get symbol info. Skipping.")
                    investor_positions_skipped += 1
                    stats["positions_skipped"] += 1
                    continue

                # Determine position direction
                is_buy = position.type == mt5.POSITION_TYPE_BUY
                
                print(f"\n    └─ 📋 Position #{position.ticket} | {position_type_name} | {position.symbol}")
                
                # Calculate current risk (from entry to original SL)
                if is_buy:
                    risk_distance = position.price_open - position.sl
                else:
                    risk_distance = position.sl - position.price_open
                
                risk_points = abs(risk_distance) / symbol_info.point
                
                # Calculate point value
                tick_value = symbol_info.trade_tick_value
                tick_size = symbol_info.trade_tick_size
                
                if tick_value > 0 and tick_size > 0:
                    point_value = tick_value / tick_size * symbol_info.point
                    risk_usd = round(risk_points * point_value * position.volume, 2)
                else:
                    # Fallback: calculate risk using profit calculator
                    calc_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
                    sl_profit = mt5.order_calc_profit(calc_type, position.symbol, position.volume, 
                                                      position.price_open, position.sl)
                    if sl_profit is not None:
                        risk_usd = round(abs(sl_profit), 2)
                    else:
                        print(f"       ⚠️  Cannot calculate risk. Skipping.")
                        investor_positions_skipped += 1
                        stats["positions_skipped"] += 1
                        continue

                # Calculate current profit in R multiples
                current_profit_usd = position.profit
                
                if risk_usd > 0:
                    current_r_multiple = current_profit_usd / risk_usd
                else:
                    print(f"       ⚠️  Invalid risk value. Skipping.")
                    investor_positions_skipped += 1
                    stats["positions_skipped"] += 1
                    continue

                print(f"       • Risk: ${risk_usd:.2f} | Current P/L: ${current_profit_usd:.2f} ({current_r_multiple:.2f}R)")

                # Skip if position is not in profit
                if current_profit_usd <= 0:
                    print(f"       ⏭️  Position not in profit. Skipping.")
                    investor_positions_skipped += 1
                    stats["positions_skipped"] += 1
                    continue

                # Find applicable breakeven rules
                applicable_rules = []
                for rule in breakeven_config:
                    reward_threshold = rule["reward"]
                    if current_r_multiple >= reward_threshold:
                        applicable_rules.append(rule)
                
                if not applicable_rules:
                    print(f"       ⏭️  No breakeven threshold reached (current: {current_r_multiple:.2f}R)")
                    investor_positions_skipped += 1
                    stats["positions_skipped"] += 1
                    continue

                # Get the highest applicable rule (last in sorted list)
                highest_rule = applicable_rules[-1]
                target_reward = highest_rule["breakeven_at_reward"]
                
                print(f"       🎯 Reached {highest_rule['reward']}R threshold")
                print(f"       Target SL position: {target_reward}R")

                # Calculate target SL price based on target reward
                if target_reward >= 0:
                    # For positive target reward, we want SL at entry + (risk_distance * target_reward)
                    # But direction matters
                    if is_buy:
                        # For BUY: entry + (risk * target_reward)
                        target_sl_price = position.price_open + (risk_distance * target_reward)
                    else:
                        # For SELL: entry - (risk * target_reward)
                        target_sl_price = position.price_open - (risk_distance * target_reward)
                    
                    # Round to symbol digits
                    digits = symbol_info.digits
                    target_sl_price = round(target_sl_price, digits)
                    
                    print(f"       Current SL: {position.sl:.{digits}f}")
                    print(f"       Target SL:  {target_sl_price:.{digits}f} ({target_reward}R)")
                    
                    # Check if SL needs adjustment
                    current_sl_distance = abs(position.sl - position.price_open) if position.sl != 0 else 0
                    target_sl_distance = abs(target_sl_price - position.price_open)
                    
                    # Calculate threshold (10% of target distance or 2 pips)
                    pip_threshold = max(target_sl_distance * 0.1, symbol_info.point * 20)
                    
                    should_adjust = False
                    
                    if position.sl == 0:
                        print(f"       📝 No SL currently set")
                        should_adjust = True
                    elif abs(current_sl_distance - target_sl_distance) > pip_threshold:
                        print(f"       📐 SL needs adjustment")
                        should_adjust = True
                    else:
                        # Check if we're moving in the right direction (should only move SL towards profit)
                        if is_buy and target_sl_price > position.sl:
                            print(f"       ✅ SL already at or beyond target")
                            investor_positions_skipped += 1
                            stats["positions_skipped"] += 1
                            continue
                        elif not is_buy and target_sl_price < position.sl:
                            print(f"       ✅ SL already at or beyond target")
                            investor_positions_skipped += 1
                            stats["positions_skipped"] += 1
                            continue
                        else:
                            should_adjust = True
                    
                    if should_adjust:
                        # Ensure we're only moving SL in the profit direction
                        if is_buy and target_sl_price <= position.sl:
                            print(f"       ⚠️  Target SL would not improve position. Skipping.")
                            investor_positions_skipped += 1
                            stats["positions_skipped"] += 1
                            continue
                        elif not is_buy and target_sl_price >= position.sl:
                            print(f"       ⚠️  Target SL would not improve position. Skipping.")
                            investor_positions_skipped += 1
                            stats["positions_skipped"] += 1
                            continue
                        
                        # Prepare modification request
                        modify_request = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "position": position.ticket,
                            "sl": target_sl_price,
                            "tp": position.tp,  # Keep existing TP
                        }
                        
                        # Send modification
                        result = mt5.order_send(modify_request)
                        
                        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                            investor_positions_adjusted += 1
                            investor_breakeven_events += 1
                            stats["positions_adjusted"] += 1
                            stats["breakeven_events"] += 1
                            print(f"       ✅ SL adjusted successfully to {target_sl_price:.{digits}f} ({target_reward}R)")
                        else:
                            investor_positions_error += 1
                            stats["positions_error"] += 1
                            error_msg = result.comment if result else f"Error code: {result.retcode if result else 'Unknown'}"
                            print(f"       ❌ Modification failed: {error_msg}")
                else:
                    print(f"       ⚠️  Invalid target reward: {target_reward}")
                    investor_positions_skipped += 1
                    stats["positions_skipped"] += 1

        # --- INVESTOR SUMMARY ---
        if investor_positions_checked > 0:
            print(f"\n  └─ 📊 Breakeven Results for {user_brokerid}:")
            print(f"       • Positions checked: {investor_positions_checked}")
            print(f"       • Positions adjusted: {investor_positions_adjusted}")
            print(f"       • Breakeven events: {investor_breakeven_events}")
            print(f"       • Positions skipped: {investor_positions_skipped}")
            if investor_positions_error > 0:
                print(f"       • Errors: {investor_positions_error}")
            else:
                print(f"       ✅ All breakeven checks completed successfully")
            stats["processing_success"] = True
        else:
            print(f"  └─ 🔘 No open positions found.")

    # --- FINAL SUMMARY ---
    print(f"\n{'='*10} 📊 DYNAMIC BREAKEVEN SUMMARY {'='*10}")
    print(f"   Investor ID: {stats['investor_id']}")
    print(f"   Positions checked: {stats['positions_checked']}")
    print(f"   Positions adjusted: {stats['positions_adjusted']}")
    print(f"   Breakeven events: {stats['breakeven_events']}")
    print(f"   Positions skipped: {stats['positions_skipped']}")
    print(f"   Errors: {stats['positions_error']}")
    
    if stats['positions_checked'] > 0:
        adjustment_rate = (stats['positions_adjusted'] / stats['positions_checked']) * 100
        print(f"   Adjustment rate: {adjustment_rate:.1f}%")
    
    print(f"\n{'='*10} 🏁 DYNAMIC BREAKEVEN MONITORING COMPLETE {'='*10}\n")
    return stats

def fetch_insiders():
    try:
        insiders.fetch_insiders_rows()
    except Exception as e:
        print(f"Error in fetching insiders{e}")

def update_insiders():
    try:
        insiders.update_insiders_from_json()
    except Exception as e:
        print(f"Error in updating insiders{e}")




# real account 
def process_single_investor(inv_folder):
    """
    WORKER FUNCTION: Handles the entire pipeline for ONE investor.
    Each process calls this independently.
    """
    inv_id = inv_folder.name
    # Results dictionary to pass back to the main process for statistics
    account_stats = {"inv_id": inv_id, "success": False, "details": {}}
    
    # 1. Get broker config
    broker_cfg = usersdictionary.get(inv_id)
    if not broker_cfg:
        print(f" [{inv_id}] ❌ No broker config found")
        return account_stats

    # --- ISOLATION START ---
    # Give a small random offset to avoid exact simultaneous initialization hits on the OS
    time.sleep(random.uniform(0.1, 2.0)) 
    
    login_id = int(broker_cfg['LOGIN_ID'])
    mt5_path = broker_cfg["TERMINAL_PATH"]

    try:
        # Initialize and Login (Local to this process)
        if not mt5.initialize(path=mt5_path, timeout=180000):
            print(f" [{inv_id}] ❌ MT5 Init failed at {mt5_path}")
            return account_stats

        if not mt5.login(login_id, password=broker_cfg["PASSWORD"], server=broker_cfg["SERVER"]):
            print(f" [{inv_id}] ❌ Login failed")
            mt5.shutdown()
            return account_stats

        # --- RUN ALL SEQUENTIAL STEPS FOR THIS BROKER ---
        # Note: All your functions (deduplicate_orders, etc.) must accept inv_id
        apply_dynamic_breakeven(inv_id=inv_id)

        mt5.shutdown()
        account_stats["success"] = True
        print(f" [{inv_id}] ✅ Processing complete")
        
    except Exception as e:
        print(f" [{inv_id}] ❌ Critical Error: {e}")
        mt5.shutdown()
    
    return account_stats
#--

# demo
def process_demo_single_investor(inv_folder):
    """
    WORKER FUNCTION: Handles the entire pipeline for ONE investor (DEMO VERSION).
    Uses demo-style initialization with account info check before login.
    """
    inv_id = inv_folder.name
    
    account_stats = {
        "inv_id": inv_id, 
        "success": False, 
        "price_collection_stats": {},
        "candle_fetch_stats": {},
        "crosser_analysis_stats": {},
        "trapped_analysis_stats": {},
        "liquidator_analysis_stats": {},
        "ranging_analysis_stats": {},
        "order_placement_stats": {},
        "risk_correction_stats": {},
        "risk_audit_stats": {},
        "symbols_filtered": 0,
        "orders_filtered": 0,
        "symbols_processed": 0,
        "symbols_successful": 0,
        "orders_placed": 0,
        "counter_orders_placed": 0,
        "total_active_orders": 0,
        "orders_adjusted": 0,
        "orders_removed": 0,
        "current_candle_forming": False,
        "bid_wins": 0,
        "ask_wins": 0,
        "trapped_candles_found": 0,
        "symbols_with_trapped": 0,
        "symbols_with_liquidator": 0,
        "liquidator_candles_found": 0,
        "bullish_liquidators": 0,
        "bearish_liquidators": 0,
        "symbols_ranging": 0,
        "avg_ranging_cycles": 0
    }
    
    # 1. Get broker config
    broker_cfg = usersdictionary.get(inv_id)
    if not broker_cfg:
        print(f" [{inv_id}] ❌ No broker config found")
        return account_stats

    # --- ISOLATION START ---
    # Give a small random offset to avoid exact simultaneous initialization hits on the OS
    import random
    import time
    time.sleep(random.uniform(0.1, 2.0)) 
    
    login_id = int(broker_cfg['LOGIN_ID'])
    mt5_path = broker_cfg["TERMINAL_PATH"]

    try:
        # DEMO STYLE INITIALIZATION: Initialize first, then check account info
        if not mt5.initialize(path=mt5_path, timeout=180000):
            print(f" [{inv_id}] ❌ MT5 Init failed at {mt5_path}")
            return account_stats

        # DEMO STYLE LOGIN: Check if already logged in correctly
        acc = mt5.account_info()
        if acc is None or acc.login != login_id:
            if not mt5.login(login_id, password=broker_cfg["PASSWORD"], server=broker_cfg["SERVER"]):
                print(f" [{inv_id}] ❌ Login failed")
                mt5.shutdown()
                return account_stats

        # --- RUN ALL SEQUENTIAL STEPS FOR THIS BROKER (SAME AS REAL VERSION) ---
        apply_dynamic_breakeven(inv_id=inv_id)
        

        # Update demo-specific stats if needed
        # (You might want to collect stats from these functions)
        
        mt5.shutdown()
        account_stats["success"] = True
        print(f" [{inv_id}] ✅ Demo processing complete")
        
    except Exception as e:
        print(f" [{inv_id}] ❌ Critical Error: {e}")
        try:
            mt5.shutdown()
        except:
            pass
    
    return account_stats
#---



# multiprocessor
def background_breakeven_process():
    """
    Runs as separate process for breakeven checks - WITHOUT nested Pool
    """
    while True:
        print(f"\n{'='*10} 🔄 BACKGROUND BREAKEVEN CHECK {'='*10}")
        
        inv_base_path = Path(INV_PATH)
        investor_folders = [f for f in inv_base_path.iterdir() if f.is_dir()]
        
        if investor_folders:
            print(f"Found {len(investor_folders)} investors to process")
            
            # Process investors SEQUENTIALLY (no nested Pool)
            results = []
            for folder in investor_folders:
                try:
                    # Call your function directly
                    result = process_demo_single_investor(folder)
                    results.append(result)
                except Exception as e:
                    print(f"Error processing {folder}: {e}")
                    results.append({"success": False})
            
            successful = sum(1 for r in results if r.get("success", False))
            print(f" ✅ Breakeven complete: {successful}/{len(results)} successful")
        
        print(f"⏰ Next breakeven check in x seconds...")
        time.sleep(300)

def run_trade():
    """
    Main trading loop
    """
    # Start background breakeven process
    breakeven_proc = mp.Process(
        target=background_breakeven_process, 
        daemon=True  # Will exit when main process exits
    )
    breakeven_proc.start()
    print(f"🚀 Background breakeven process started (PID: {breakeven_proc.pid})")
    
    # Main trading loop
    cycle_count = 0
    while True:
        cycle_count += 1
        print(f"\n{'='*10} 📊 MAIN TRADING CYCLE #{cycle_count} {'='*10}")
        
        try:
            # Your sequential trading functions
            print("📥 Fetching OHLC data...")
            fetch_ohlc()
            
            print("📈 Running technical analysis...")
            technical_analysis()
            
            print("📤 Placing orders...")
            place_demo_orders()
            
            print(f"✅ Cycle #{cycle_count} complete. Sleeping 300s...")
            time.sleep(300)
            
        except Exception as e:
            print(f"❌ Error in trading cycle: {e}")
            # Continue running despite errors
           
def main():
    """
    Main entry point with proper setup and cleanup
    """
    # Required for Windows
    mp.freeze_support()
    
    print("="*50)
    print("🚀 TRADING BOT STARTING")
    print("="*50)
    print(f"📅 Start time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"💻 CPU cores available: {mp.cpu_count()}")
    print("="*50)
    
    try:
        run_trade()
    except KeyboardInterrupt:
        print("\n👋 Shutting down gracefully...")
        print(f"📅 Shutdown time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("🔚 Trading bot terminated")
        print("="*50)

if __name__ == "__main__":
    main()

