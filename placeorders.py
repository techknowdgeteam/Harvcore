import os
import MetaTrader5 as mt5
import pandas as pd
import mplfinance as mpf
from datetime import datetime
import json
from PIL import Image
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from datetime import datetime
from datetime import timedelta
import traceback
import shutil
from datetime import datetime
import re
from pathlib import Path
import math
import multiprocessing as mp
from pathlib import Path
import time
import random

INV_PATH = r"C:\xampp\htdocs\chronedge\synarex\usersdata\investors"
UPDATED_INVESTORS = r"C:\xampp\htdocs\chronedge\synarex\updated_investors.json"
INVESTOR_USERS = r"C:\xampp\htdocs\chronedge\synarex\usersdata\investors\investors.json"
VERIFIED_INVESTORS = r"C:\xampp\htdocs\chronedge\synarex\verified_investors.json"
ISSUES_INVESTORS = r"C:\xampp\htdocs\chronedge\synarex\issues_investors.json"
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

def debug_print_all_broker_symbols():
    """
    Connects to the currently active MT5 terminal and prints 
    every available symbol name to the console.
    """
    # Ensure MT5 is initialized (if not already)
    if not mt5.initialize():
        print(f"FAILED to initialize MT5: {mt5.last_error()}")
        return

    # Get all symbols from the terminal
    symbols = mt5.symbols_get()
    
    if symbols is None:
        print("No symbols found. This might be a connection issue.")
    else:
        print(f"\n{'='*40}")
        print(f"BROKER: {mt5.account_info().server if mt5.account_info() else 'Unknown'}")
        print(f"TOTAL SYMBOLS FOUND: {len(symbols)}")
        print(f"{'='*40}")
        
        # Extract names and sort them alphabetically for easier reading
        all_names = sorted([s.name for s in symbols])
        
        for i, name in enumerate(all_names, 1):
            print(f"{i}. {name}")
            
        print(f"{'='*40}\nEND OF LIST\n{'='*40}")

def update_verified_investors_file():
    """
    Updates verified_investors.json by:
    1. Removing the MESSAGE field after moving them to activities.json
    2. Verifying that investors have the required files at INV_PATH/{investor_id}/
    3. Moving investors to issues if they're missing critical files
    """
    print("\n" + "="*80)
    print("📋 CLEANING AND VERIFYING INVESTORS FILE")
    print("="*80)
    
    verified_investors_path = Path(VERIFIED_INVESTORS)
    updated_investors_path = Path(UPDATED_INVESTORS)
    issues_investors_path = Path(ISSUES_INVESTORS)
    
    if not verified_investors_path.exists():
        print(f"⚠️  {VERIFIED_INVESTORS} not found")
        return False
    
    # Load existing files
    try:
        with open(verified_investors_path, 'r', encoding='utf-8') as f:
            verified_investors = json.load(f)
    except Exception as e:
        print(f"❌ Error reading verified_investors.json: {e}")
        return False
    
    # Load updated_investors if exists
    if updated_investors_path.exists():
        try:
            with open(updated_investors_path, 'r', encoding='utf-8') as f:
                updated_investors = json.load(f)
        except:
            updated_investors = {}
    else:
        updated_investors = {}
    
    # Load issues_investors if exists
    if issues_investors_path.exists():
        try:
            with open(issues_investors_path, 'r', encoding='utf-8') as f:
                issues_investors = json.load(f)
        except:
            issues_investors = {}
    else:
        issues_investors = {}
    
    updated = False
    investors_to_remove = []
    investors_to_move_to_issues = []
    
    for inv_id, investor_data in verified_investors.items():
        print(f"\n📋 Checking investor: {inv_id}")
        print("-" * 40)
        
        # Check if investor folder exists at new path
        inv_folder = Path(INV_PATH) / inv_id
        
        if not inv_folder.exists():
            print(f"  ❌ Investor folder not found at: {inv_folder}")
            investors_to_remove.append(inv_id)
            
            # Add to issues_investors with reason
            if inv_id not in issues_investors:
                investor_data_copy = investor_data.copy()
                investor_data_copy['MESSAGE'] = f"Investor folder missing at {inv_folder}"
                investor_data_copy['verified_status'] = 'folder_missing'
                issues_investors[inv_id] = investor_data_copy
                print(f"  ⚠️  Added to issues_investors.json (folder missing)")
            continue
        
        # Check for required files
        required_files = ['activities.json', 'tradeshistory.json']
        missing_files = []
        
        for file in required_files:
            file_path = inv_folder / file
            if not file_path.exists():
                missing_files.append(file)
        
        if missing_files:
            print(f"  ⚠️  Missing required files: {', '.join(missing_files)}")
            
            # Check if investor is already in updated_investors or issues_investors
            if inv_id not in updated_investors and inv_id not in issues_investors:
                investor_data_copy = investor_data.copy()
                investor_data_copy['MESSAGE'] = f"Missing required files: {', '.join(missing_files)}"
                investor_data_copy['verified_status'] = 'missing_files'
                issues_investors[inv_id] = investor_data_copy
                print(f"  ⚠️  Added to issues_investors.json (missing files)")
                investors_to_remove.append(inv_id)
            else:
                print(f"  ℹ️  Investor already in updated/issues, skipping removal")
        else:
            print(f"  ✅ All required files present: {', '.join(required_files)}")
            
            # Check if activities.json has required data
            activities_path = inv_folder / "activities.json"
            try:
                with open(activities_path, 'r', encoding='utf-8') as f:
                    activities = json.load(f)
                
                # Validate critical fields
                execution_start_date = activities.get('execution_start_date')
                if not execution_start_date:
                    print(f"  ⚠️  Missing execution_start_date in activities.json")
                    
                    if inv_id not in updated_investors and inv_id not in issues_investors:
                        investor_data_copy = investor_data.copy()
                        investor_data_copy['MESSAGE'] = "Missing execution_start_date in activities.json"
                        investor_data_copy['verified_status'] = 'missing_start_date'
                        issues_investors[inv_id] = investor_data_copy
                        print(f"  ⚠️  Added to issues_investors.json (missing start date)")
                        investors_to_remove.append(inv_id)
                    continue
                
                # Check if tradeshistory.json has data
                tradeshistory_path = inv_folder / "tradeshistory.json"
                if tradeshistory_path.exists():
                    with open(tradeshistory_path, 'r', encoding='utf-8') as f:
                        tradeshistory = json.load(f)
                    
                    if tradeshistory:
                        print(f"  ✅ Found {len(tradeshistory)} authorized trades in tradeshistory.json")
                    else:
                        print(f"  ℹ️  tradeshistory.json is empty")
                
                # Remove MESSAGE field if it exists
                if 'MESSAGE' in investor_data:
                    print(f"  🧹 Removing MESSAGE field for investor {inv_id}")
                    del investor_data['MESSAGE']
                    updated = True
                
                # Add verification status
                investor_data['verified_status'] = 'verified'
                
            except Exception as e:
                print(f"  ❌ Error reading activities.json: {e}")
                if inv_id not in updated_investors and inv_id not in issues_investors:
                    investor_data_copy = investor_data.copy()
                    investor_data_copy['MESSAGE'] = f"Error reading activities.json: {str(e)}"
                    investor_data_copy['verified_status'] = 'read_error'
                    issues_investors[inv_id] = investor_data_copy
                    investors_to_remove.append(inv_id)
    
    # Remove investors from verified_investors that were moved to issues
    for inv_id in investors_to_remove:
        if inv_id in verified_investors:
            print(f"  🗑️  Removing {inv_id} from verified_investors.json")
            del verified_investors[inv_id]
            updated = True
    
    # Save updated files
    try:
        # Save verified_investors.json
        with open(verified_investors_path, 'w', encoding='utf-8') as f:
            json.dump(verified_investors, f, indent=4)
        
        # Save issues_investors.json
        with open(issues_investors_path, 'w', encoding='utf-8') as f:
            json.dump(issues_investors, f, indent=4)
        
        print(f"\n" + "="*80)
        if updated:
            print(f"✅ Updated verified_investors.json - removed {len(investors_to_remove)} investors and cleaned MESSAGE fields")
        else:
            print(f"ℹ️  No changes made to verified_investors.json")
        
        if issues_investors:
            print(f"⚠️  Issues investors file updated with {len(issues_investors)} investors")
        print("="*80)
        
    except Exception as e:
        print(f"❌ Error saving files: {e}")
        return False
    
    return True

def get_requirements_old(inv_id):
    """
    Mirroring the logic of update_investor_info to find the date 
    in subfolders or root files. Also checks if investor balance
    meets minimum requirement from requirements.json and moves
    them to issues_investors.json with a message if not.
    """
    execution_start_date = None
    inv_root = Path(INV_PATH) / inv_id
    
    if not inv_root.exists():
        print(f"❌ Path not found: {inv_root}")
        return None

    # 1. Search subfolders for activities.json (Original Logic)
    pending_folders = list(inv_root.rglob("*/pending_orders"))
    for folder in pending_folders:
        act_path = folder / "activities.json"
        if act_path.exists():
            try:
                with open(act_path, 'r', encoding='utf-8') as f:
                    activities = json.load(f)
                    execution_start_date = activities.get('execution_start_date')
                    if execution_start_date: break 
            except: pass

    # 2. Backup: Check root accountmanagement.json
    if not execution_start_date:
        acc_mgmt_path = inv_root / "accountmanagement.json"
        if acc_mgmt_path.exists():
            try:
                with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                    acc_mgmt = json.load(f)
                    execution_start_date = acc_mgmt.get('execution_start_date')
            except: pass

    if not execution_start_date:
        print(f"❌ Date not found for {inv_id} in any activities.json or accountmanagement.json")
        return None

    # 3. MT5 Calculation
    start_datetime = None
    for fmt in ["%B %d, %Y", "%Y-%m-%d"]:
        try:
            start_datetime = datetime.strptime(execution_start_date, fmt).replace(hour=0, minute=0, second=0)
            break
        except: continue

    if start_datetime:
        all_deals = mt5.history_deals_get(start_datetime, datetime.now())
        account_info = mt5.account_info()
        
        if account_info:
            # Calculate net profit (profit + swap + commission)
            total_pnl = sum((d.profit + d.swap + d.commission) for d in all_deals if d.type in [0, 1])
            starting_bal = account_info.balance - total_pnl
            
            print(f"📊 {inv_id} | Start: {execution_start_date} | Balance: ${starting_bal:.2f}")
            
            # --- CHECK minimum balance requirement from strategy folder requirements.json ---
            try:
                # Look for requirements.json in strategy subfolders (inv_id/*/requirements.json)
                requirements_path = None
                strategy_folders = [f for f in inv_root.iterdir() if f.is_dir()]
                
                for strategy_folder in strategy_folders:
                    test_path = strategy_folder / "requirements.json"
                    if test_path.exists():
                        requirements_path = test_path
                        break
                
                if requirements_path and requirements_path.exists():
                    print(f"  🔍 Found requirements.json ")
                    with open(requirements_path, 'r', encoding='utf-8') as f:
                        requirements_config = json.load(f)
                        
                        # Handle both list format and direct object format
                        if isinstance(requirements_config, list) and len(requirements_config) > 0:
                            # It's a list with config object
                            min_balance = requirements_config[0].get('minimum_balance')
                        elif isinstance(requirements_config, dict):
                            # It's a direct object/dictionary
                            min_balance = requirements_config.get('minimum_balance')
                        else:
                            min_balance = None
                            print(f"  ⚠️  requirements.json has unexpected format: {type(requirements_config)}")
                        
                        if min_balance is not None:
                            print(f"  📊 Minimum balance requirement: ${min_balance}")
                            
                            if starting_bal < min_balance:
                                print(f"  ⚠️  Balance ${starting_bal:.2f} is BELOW minimum requirement ${min_balance}")
                                print(f"  ❌ Moving investor {inv_id} to issues_investors.json")
                                
                                # Move investor logic
                                if os.path.exists(INVESTOR_USERS):
                                    with open(INVESTOR_USERS, 'r', encoding='utf-8') as f:
                                        investors_data = json.load(f)
                                    
                                    investor_data_to_move = None
                                    if isinstance(investors_data, list):
                                        for i, inv in enumerate(investors_data):
                                            if inv_id in inv:
                                                investor_data_to_move = inv[inv_id]
                                                investors_data.pop(i)
                                                break
                                    else:
                                        if inv_id in investors_data:
                                            investor_data_to_move = investors_data[inv_id]
                                            del investors_data[inv_id]
                                    
                                    if investor_data_to_move:
                                        investor_data_to_move['MESSAGE'] = f"Balance ${starting_bal:.2f} is below minimum requirement ${min_balance}"
                                        with open(INVESTOR_USERS, 'w', encoding='utf-8') as f:
                                            json.dump(investors_data, f, indent=4)
                                        
                                        issues_data = {}
                                        if os.path.exists(ISSUES_INVESTORS):
                                            try:
                                                with open(ISSUES_INVESTORS, 'r', encoding='utf-8') as f:
                                                    issues_data = json.load(f)
                                            except: issues_data = {}
                                        
                                        issues_data[inv_id] = investor_data_to_move
                                        with open(ISSUES_INVESTORS, 'w', encoding='utf-8') as f:
                                            json.dump(issues_data, f, indent=4)
                                        
                                        print(f"  ✅ Successfully moved investor {inv_id} to issues_investors.json")
                                    else:
                                        print(f"  ⚠️  Investor {inv_id} not found in investors.json")
                                
                                return None  # Return None since investor is being moved
                            else:
                                print(f"  ✅ Balance ${starting_bal:.2f} MEETS minimum requirement (${min_balance})")
                        else:
                            print(f"  ⚠️  No minimum_balance found in requirements.json")
                else:
                    print(f"  ℹ️  No requirements.json found in any strategy folder for {inv_id} - skipping minimum balance check")
                    
            except Exception as e:
                print(f"  ⚠️  Error checking minimum balance requirement: {e}")
            
            return starting_bal

        else:
            # --- NEW LOGIC: Handle Invalid Broker Login / No Account Info ---
            print(f"  ⚠️  Could not get account info for {inv_id}")
            print(f"  ❌ Moving investor {inv_id} to issues_investors.json due to invalid login")
            
            if os.path.exists(INVESTOR_USERS):
                with open(INVESTOR_USERS, 'r', encoding='utf-8') as f:
                    investors_data = json.load(f)
                
                investor_data_to_move = None
                if isinstance(investors_data, list):
                    for i, inv in enumerate(investors_data):
                        if inv_id in inv:
                            investor_data_to_move = inv[inv_id]
                            investors_data.pop(i)
                            break
                else:
                    if inv_id in investors_data:
                        investor_data_to_move = investors_data[inv_id]
                        del investors_data[inv_id]
                
                if investor_data_to_move:
                    # Specific message for login failure
                    investor_data_to_move['MESSAGE'] = "invalid broker login please check your login details"
                    
                    with open(INVESTOR_USERS, 'w', encoding='utf-8') as f:
                        json.dump(investors_data, f, indent=4)
                    
                    issues_data = {}
                    if os.path.exists(ISSUES_INVESTORS):
                        try:
                            with open(ISSUES_INVESTORS, 'r', encoding='utf-8') as f:
                                issues_data = json.load(f)
                        except: issues_data = {}
                    
                    issues_data[inv_id] = investor_data_to_move
                    with open(ISSUES_INVESTORS, 'w', encoding='utf-8') as f:
                        json.dump(issues_data, f, indent=4)
                    
                    print(f"  ✅ Successfully moved investor {inv_id} to issues_investors.json")
                else:
                    print(f"  ⚠️  Investor {inv_id} not found in investors.json")
            
            return None

    else:
        print(f"  ⚠️  Could not parse start date: {execution_start_date}")

    return None

def get_requirements(inv_id):
    """
    Mirroring the logic of update_investor_info to find the date 
    directly in root files (new path structure). Also checks if investor balance
    meets minimum requirement from requirements.json and moves
    them to issues_investors.json with a message if not.
    
    Core Functions:
    1. Read execution_start_date from activities.json in root folder
    2. Connect to MT5 and calculate starting balance
    3. Check minimum balance requirement from investor root folder
    4. Move non-compliant investors to issues_investors.json with error messages
    """
    execution_start_date = None
    inv_root = Path(INV_PATH) / inv_id
    
    if not inv_root.exists():
        print(f"❌ Path not found: {inv_root}")
        return None

    # 1. Check activities.json directly in root folder (NEW PATH)
    activities_path = inv_root / "activities.json"
    if activities_path.exists():
        try:
            with open(activities_path, 'r', encoding='utf-8') as f:
                activities = json.load(f)
                execution_start_date = activities.get('execution_start_date')
                if execution_start_date:
                    print(f"  📋 Found execution_start_date in activities.json: {execution_start_date}")
        except Exception as e:
            print(f"  ⚠️  Error reading activities.json: {e}")

    # 2. Backup: Check accountmanagement.json if not found in activities.json
    if not execution_start_date:
        acc_mgmt_path = inv_root / "accountmanagement.json"
        if acc_mgmt_path.exists():
            try:
                with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                    acc_mgmt = json.load(f)
                    execution_start_date = acc_mgmt.get('execution_start_date')
                    if execution_start_date:
                        print(f"  📋 Found execution_start_date in accountmanagement.json: {execution_start_date}")
            except Exception as e:
                print(f"  ⚠️  Error reading accountmanagement.json: {e}")

    if not execution_start_date:
        print(f"❌ Date not found for {inv_id} in activities.json or accountmanagement.json")
        return None

    # 3. MT5 Calculation
    start_datetime = None
    for fmt in ["%B %d, %Y", "%Y-%m-%d"]:
        try:
            start_datetime = datetime.strptime(execution_start_date, fmt).replace(hour=0, minute=0, second=0)
            break
        except: continue

    if start_datetime:
        print(f"  🔍 Fetching trades from: {start_datetime.strftime('%Y-%m-%d')}")
        all_deals = mt5.history_deals_get(start_datetime, datetime.now())
        account_info = mt5.account_info()
        
        if account_info:
            # Calculate net profit (profit + swap + commission)
            total_pnl = sum((d.profit + d.swap + d.commission) for d in all_deals if d.type in [0, 1])
            starting_bal = account_info.balance - total_pnl
            
            print(f"📊 {inv_id} | Start: {execution_start_date} | Starting Balance: ${starting_bal:.2f}")
            print(f"   Current Balance: ${account_info.balance:.2f} | Total P&L: ${total_pnl:.2f}")
            
            # --- CHECK minimum balance requirement from investor root folder (NEW PATH) ---
            try:
                # Look for requirements.json in the investor's root folder (NEW PATH)
                requirements_path = inv_root / "requirements.json"
                
                if requirements_path.exists():
                    print(f"  🔍 Found requirements.json at: {requirements_path}")
                    with open(requirements_path, 'r', encoding='utf-8') as f:
                        requirements_config = json.load(f)
                        
                        # Handle both list format and direct object format
                        min_balance = None
                        if isinstance(requirements_config, list) and len(requirements_config) > 0:
                            # It's a list with config object
                            min_balance = requirements_config[0].get('minimum_balance')
                        elif isinstance(requirements_config, dict):
                            # It's a direct object/dictionary
                            min_balance = requirements_config.get('minimum_balance')
                        else:
                            print(f"  ⚠️  requirements.json has unexpected format: {type(requirements_config)}")
                        
                        if min_balance is not None:
                            print(f"  📊 Minimum balance requirement: ${min_balance}")
                            
                            if starting_bal < min_balance:
                                print(f"  ⚠️  Balance ${starting_bal:.2f} is BELOW minimum requirement ${min_balance}")
                                print(f"  ❌ Moving investor {inv_id} to issues_investors.json")
                                
                                # Move investor logic
                                if os.path.exists(INVESTOR_USERS):
                                    with open(INVESTOR_USERS, 'r', encoding='utf-8') as f:
                                        investors_data = json.load(f)
                                    
                                    investor_data_to_move = None
                                    if isinstance(investors_data, list):
                                        for i, inv in enumerate(investors_data):
                                            if inv_id in inv:
                                                investor_data_to_move = inv[inv_id]
                                                investors_data.pop(i)
                                                break
                                    else:
                                        if inv_id in investors_data:
                                            investor_data_to_move = investors_data[inv_id]
                                            del investors_data[inv_id]
                                    
                                    if investor_data_to_move:
                                        investor_data_to_move['MESSAGE'] = f"Balance ${starting_bal:.2f} is below minimum requirement ${min_balance}"
                                        with open(INVESTOR_USERS, 'w', encoding='utf-8') as f:
                                            json.dump(investors_data, f, indent=4)
                                        
                                        issues_data = {}
                                        if os.path.exists(ISSUES_INVESTORS):
                                            try:
                                                with open(ISSUES_INVESTORS, 'r', encoding='utf-8') as f:
                                                    issues_data = json.load(f)
                                            except: issues_data = {}
                                        
                                        issues_data[inv_id] = investor_data_to_move
                                        with open(ISSUES_INVESTORS, 'w', encoding='utf-8') as f:
                                            json.dump(issues_data, f, indent=4)
                                        
                                        print(f"  ✅ Successfully moved investor {inv_id} to issues_investors.json")
                                    else:
                                        print(f"  ⚠️  Investor {inv_id} not found in investors.json")
                                
                                return None  # Return None since investor is being moved
                            else:
                                print(f"  ✅ Balance ${starting_bal:.2f} MEETS minimum requirement (${min_balance})")
                        else:
                            print(f"  ⚠️  No minimum_balance found in requirements.json")
                else:
                    print(f"  ℹ️  No requirements.json found in investor root folder - skipping minimum balance check")
                    
            except Exception as e:
                print(f"  ⚠️  Error checking minimum balance requirement: {e}")
            
            return starting_bal

        else:
            # --- Handle Invalid Broker Login / No Account Info ---
            print(f"  ⚠️  Could not get account info for {inv_id}")
            print(f"  ❌ Moving investor {inv_id} to issues_investors.json due to invalid login")
            
            if os.path.exists(INVESTOR_USERS):
                with open(INVESTOR_USERS, 'r', encoding='utf-8') as f:
                    investors_data = json.load(f)
                
                investor_data_to_move = None
                if isinstance(investors_data, list):
                    for i, inv in enumerate(investors_data):
                        if inv_id in inv:
                            investor_data_to_move = inv[inv_id]
                            investors_data.pop(i)
                            break
                else:
                    if inv_id in investors_data:
                        investor_data_to_move = investors_data[inv_id]
                        del investors_data[inv_id]
                
                if investor_data_to_move:
                    # Specific message for login failure
                    investor_data_to_move['MESSAGE'] = "invalid broker login please check your login details"
                    
                    with open(INVESTOR_USERS, 'w', encoding='utf-8') as f:
                        json.dump(investors_data, f, indent=4)
                    
                    issues_data = {}
                    if os.path.exists(ISSUES_INVESTORS):
                        try:
                            with open(ISSUES_INVESTORS, 'r', encoding='utf-8') as f:
                                issues_data = json.load(f)
                        except: issues_data = {}
                    
                    issues_data[inv_id] = investor_data_to_move
                    with open(ISSUES_INVESTORS, 'w', encoding='utf-8') as f:
                        json.dump(issues_data, f, indent=4)
                    
                    print(f"  ✅ Successfully moved investor {inv_id} to issues_investors.json")
                else:
                    print(f"  ⚠️  Investor {inv_id} not found in investors.json")
            
            return None

    else:
        print(f"  ⚠️  Could not parse start date: {execution_start_date}")

    return None

def accountmanagement_manager(inv_id):
    """
    Updates accountmanagement.json field-by-field.
    Maintains 'Flex' look: lists on one line, dictionaries vertical.
    Handles both Default and Maximum risk management tables.
    """
    print(f"\n{'='*10} ⚙️ MANAGING ACCOUNT MANAGEMENT: {inv_id} {'='*10}")
    
    # 1. Setup Paths
    inv_folder = Path(INV_PATH) / inv_id
    inv_acc_mgmt_path = inv_folder / "accountmanagement.json"
    
    # 2. Identify Broker Template
    broker_cfg = usersdictionary.get(inv_id)
    if not broker_cfg:
        print(f" [!] Error: No broker config for {inv_id}")
        return False
    
    server = broker_cfg.get('SERVER', '')
    inv_broker_name = server.split('-')[0].split('.')[0].lower() if server else 'broker'
    template_filename = f"default{inv_broker_name}_accountmanagement.json"
    template_path = Path(DEFAULT_PATH) / template_filename

    if not template_path.exists():
        template_path = Path(DEFAULT_PATH) / "default_accountmanagement.json"
        if not template_path.exists(): return False

    # 3. Load Data
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            template_data = json.load(f)
        if inv_acc_mgmt_path.exists():
            with open(inv_acc_mgmt_path, 'r', encoding='utf-8') as f:
                inv_data = json.load(f)
        else:
            inv_data = {}
    except Exception as e:
        print(f" [!] Load Error: {e}"); return False

    modified = False

    # --- FIELD-BY-FIELD FLEXIBLE LOGIC ---

    # selected_risk_reward
    curr_rr = inv_data.get("selected_risk_reward")
    if "selected_risk_reward" not in inv_data or curr_rr in [None, 0, [], [0], ""]:
        inv_data["selected_risk_reward"] = template_data.get("selected_risk_reward", [3])
        modified = True

    # symbols_dictionary
    if "symbols_dictionary" not in inv_data or not inv_data.get("symbols_dictionary"):
        inv_data["symbols_dictionary"] = template_data.get("symbols_dictionary", {})
        modified = True

    # settings (Sub-field check)
    template_settings = template_data.get("settings", {})
    if "settings" not in inv_data:
        inv_data["settings"] = template_settings
        modified = True
    else:
        for key, value in template_settings.items():
            if key not in inv_data["settings"]:
                inv_data["settings"][key] = value
                modified = True

    # account_balance_default_risk_management
    def_risk_key = "account_balance_default_risk_management"
    if def_risk_key not in inv_data or not inv_data.get(def_risk_key):
        inv_data[def_risk_key] = template_data.get(def_risk_key, {})
        modified = True

    # account_balance_maximum_risk_management (NEW)
    max_risk_key = "account_balance_maximum_risk_management"
    if max_risk_key not in inv_data or not inv_data.get(max_risk_key):
        inv_data[max_risk_key] = template_data.get(max_risk_key, {})
        modified = True
        print(f" └─ ✅ Added/Updated Maximum Risk Management table")

    # 4. Save with "Flex" Formatting
    if modified:
        try:
            # Generate standard JSON
            json_string = json.dumps(inv_data, indent=4)
            
            # Logic to flatten ONLY lists [ ... ] to keep them 'flex'
            # This regex captures lists but leaves large dictionaries vertical
            flex_format = re.sub(
                r'\[\s+([^\]\{\}]+?)\s+\]', 
                lambda m: "[ " + re.sub(r'\s+', ' ', m.group(1)).strip() + " ]", 
                json_string
            )

            with open(inv_acc_mgmt_path, 'w', encoding='utf-8') as f:
                f.write(flex_format)
                
            print(f" └─ 💾 {inv_id} accountmanagement.json synced successfully.")
            return True
        except Exception as e:
            print(f" └─ ❌ Save Error: {e}"); return False
    
    print(f" └─ 🔘 {inv_id} already contains all required fields.")
    return True

def get_normalized_symbol(record_symbol, risk_keys=None):
    """
    Standardizes symbols with a 'Broker-First' priority.
    If 'US OIL' is passed, it finds the USOIL family, then checks if the broker
    uses USOUSD, USOIL, or WTI.
    """
    if not record_symbol: return None

    NORM_PATH = Path(r"C:\xampp\htdocs\chronedge\synarex\symbols_normalization.json")
    
    def clean(s): 
        return str(s).replace(" ", "").replace("_", "").replace("/", "").replace(".", "").upper()

    search_term = clean(record_symbol)
    
    # 1. Load Normalization Map
    norm_data = {}
    if NORM_PATH.exists():
        try:
            with open(NORM_PATH, 'r', encoding='utf-8') as f:
                norm_data = json.load(f).get("NORMALIZATION", {})
        except: pass

    # 2. Find the "Family"
    target_family_key = None
    all_family_variants = []
    
    for std_key, synonyms in norm_data.items():
        family_variants = [clean(std_key)] + [clean(s) for s in synonyms]
        if any(search_term == v or search_term.startswith(v) or v.startswith(search_term) for v in family_variants):
            target_family_key = std_key
            all_family_variants = family_variants
            break

    # 3. IF RISK_KEYS ARE PROVIDED (For Risk Enforcement)
    if risk_keys:
        clean_risk_map = {clean(k): k for k in risk_keys}
        if target_family_key and clean(target_family_key) in clean_risk_map:
            return clean_risk_map[clean(target_family_key)]
        for v in all_family_variants:
            if v in clean_risk_map: return clean_risk_map[v]

    # 4. IF NO RISK_KEYS (For Populating Order Fields / MT5 Specs)
    # Check what the broker actually has in MarketWatch
    all_symbols = mt5.symbols_get()
    if all_symbols:
        broker_symbols = {clean(s.name): s.name for s in all_symbols}
        
        # Try to find which variant the broker uses
        for v in all_family_variants:
            if v in broker_symbols:
                return broker_symbols[v]
            # Handle suffixes (e.g., USOIL.m)
            for b_clean, b_raw in broker_symbols.items():
                if b_clean.startswith(v):
                    return b_raw

    # Fallback
    return target_family_key if target_family_key else record_symbol.upper()

def deduplicate_orders(inv_id=None):
    """
    Scans all pending_orders/limit_orders.json, pending_orders/limit_orders_backup.json, 
    and pending_orders/signals.json files and removes duplicate orders based on: 
    Symbol, Timeframe, Order Type, and Entry Price.
    
    Args:
        inv_id (str, optional): Specific investor ID to process. If None, processes all investors.
        This function does NOT require MT5.
    
    Returns:
        bool: True if any duplicates were removed, False otherwise
    """
    print(f"\n{'='*10} 🧹 DEDUPLICATING ORDERS {'='*10}")
    
    total_files_cleaned = 0
    total_duplicates_removed = 0
    total_limit_files_cleaned = 0
    total_signal_files_cleaned = 0
    total_limit_backup_files_cleaned = 0
    total_limit_duplicates = 0
    total_signal_duplicates = 0
    total_limit_backup_duplicates = 0
    inv_base_path = Path(INV_PATH)

    if not inv_base_path.exists():
        print(f" [!] Error: Investor path {INV_PATH} does not exist.")
        return False

    # Determine which investors to process
    if inv_id:
        inv_folder = inv_base_path / inv_id
        investor_folders = [inv_folder] if inv_folder.exists() else []
        if not investor_folders:
            print(f" [!] Error: Investor folder {inv_id} does not exist.")
            return False
    else:
        investor_folders = [f for f in inv_base_path.iterdir() if f.is_dir()]
    
    if not investor_folders:
        print(" └─ 🔘 No investor directories found for deduplication.")
        return False

    any_duplicates_removed = False

    for inv_folder in investor_folders:
        current_inv_id = inv_folder.name
        print(f"\n [{current_inv_id}] 🔍 Checking for duplicate entries...")

        # 2. Search for pending_orders folders
        pending_orders_folders = list(inv_folder.rglob("*/pending_orders/"))
        
        investor_limit_duplicates = 0
        investor_signal_duplicates = 0
        investor_limit_backup_duplicates = 0
        investor_limit_files_cleaned = 0
        investor_signal_files_cleaned = 0
        investor_limit_backup_files_cleaned = 0

        for pending_folder in pending_orders_folders:
            # Process limit_orders.json
            limit_file = pending_folder / "limit_orders.json"
            if limit_file.exists():
                try:
                    with open(limit_file, 'r', encoding='utf-8') as f:
                        orders = json.load(f)

                    if orders:
                        original_count = len(orders)
                        seen_orders = set()
                        unique_orders = []

                        for order in orders:
                            # Create a unique key based on Symbol, Timeframe, Order Type, and Entry
                            unique_key = (
                                str(order.get("symbol", "")).strip(),
                                str(order.get("timeframe", "")).strip(),
                                str(order.get("order_type", "")).strip(),
                                float(order.get("entry", 0))
                            )

                            if unique_key not in seen_orders:
                                seen_orders.add(unique_key)
                                unique_orders.append(order)
                        
                        # Only write back if duplicates were actually found
                        if len(unique_orders) < original_count:
                            removed = original_count - len(unique_orders)
                            with open(limit_file, 'w', encoding='utf-8') as f:
                                json.dump(unique_orders, f, indent=4)
                            
                            investor_limit_duplicates += removed
                            investor_limit_files_cleaned += 1
                            total_limit_duplicates += removed
                            total_limit_files_cleaned += 1
                            any_duplicates_removed = True
                            
                            folder_name = pending_folder.parent.name
                            print(f"  └─ 📄 {folder_name}/limit_orders.json - Removed {removed} duplicates")

                except Exception as e:
                    print(f"  └─ ❌ Error processing {limit_file}: {e}")

            # Process limit_orders_backup.json
            limit_backup_file = pending_folder / "limit_orders_backup.json"
            if limit_backup_file.exists():
                try:
                    with open(limit_backup_file, 'r', encoding='utf-8') as f:
                        backup_orders = json.load(f)

                    if backup_orders:
                        original_count = len(backup_orders)
                        seen_orders = set()
                        unique_backup_orders = []

                        for order in backup_orders:
                            # Create a unique key based on Symbol, Timeframe, Order Type, and Entry
                            unique_key = (
                                str(order.get("symbol", "")).strip(),
                                str(order.get("timeframe", "")).strip(),
                                str(order.get("order_type", "")).strip(),
                                float(order.get("entry", 0))
                            )

                            if unique_key not in seen_orders:
                                seen_orders.add(unique_key)
                                unique_backup_orders.append(order)
                        
                        # Only write back if duplicates were actually found
                        if len(unique_backup_orders) < original_count:
                            removed = original_count - len(unique_backup_orders)
                            with open(limit_backup_file, 'w', encoding='utf-8') as f:
                                json.dump(unique_backup_orders, f, indent=4)
                            
                            investor_limit_backup_duplicates += removed
                            investor_limit_backup_files_cleaned += 1
                            total_limit_backup_duplicates += removed
                            total_limit_backup_files_cleaned += 1
                            any_duplicates_removed = True
                            
                            folder_name = pending_folder.parent.name
                            print(f"  └─ 📄 {folder_name}/limit_orders_backup.json - Removed {removed} duplicates")

                except Exception as e:
                    print(f"  └─ ❌ Error processing {limit_backup_file}: {e}")

            # Process signals.json
            signals_file = pending_folder / "signals.json"
            if signals_file.exists():
                try:
                    with open(signals_file, 'r', encoding='utf-8') as f:
                        signals = json.load(f)

                    if signals:
                        original_count = len(signals)
                        seen_orders = set()
                        unique_signals = []

                        for signal in signals:
                            # Create a unique key based on Symbol, Timeframe, Order Type, and Entry
                            unique_key = (
                                str(signal.get("symbol", "")).strip(),
                                str(signal.get("timeframe", "")).strip(),
                                str(signal.get("order_type", "")).strip(),
                                float(signal.get("entry", 0))
                            )

                            if unique_key not in seen_orders:
                                seen_orders.add(unique_key)
                                unique_signals.append(signal)
                        
                        # Only write back if duplicates were actually found
                        if len(unique_signals) < original_count:
                            removed = original_count - len(unique_signals)
                            with open(signals_file, 'w', encoding='utf-8') as f:
                                json.dump(unique_signals, f, indent=4)
                            
                            investor_signal_duplicates += removed
                            investor_signal_files_cleaned += 1
                            total_signal_duplicates += removed
                            total_signal_files_cleaned += 1
                            any_duplicates_removed = True
                            
                            folder_name = pending_folder.parent.name
                            print(f"  └─ 📄 {folder_name}/signals.json - Removed {removed} duplicates")

                except Exception as e:
                    print(f"  └─ ❌ Error processing {signals_file}: {e}")

        # Summary for the current investor
        if investor_limit_duplicates > 0 or investor_signal_duplicates > 0 or investor_limit_backup_duplicates > 0:
            print(f"\n  └─ ✨ Investor {current_inv_id} Cleanup Summary:")
            if investor_limit_duplicates > 0:
                print(f"      • limit_orders.json: Cleaned {investor_limit_files_cleaned} files | Removed {investor_limit_duplicates} duplicates")
            if investor_limit_backup_duplicates > 0:
                print(f"      • limit_orders_backup.json: Cleaned {investor_limit_backup_files_cleaned} files | Removed {investor_limit_backup_duplicates} duplicates")
            if investor_signal_duplicates > 0:
                print(f"      • signals.json: Cleaned {investor_signal_files_cleaned} files | Removed {investor_signal_duplicates} duplicates")
        else:
            print(f"  └─ ✅ No duplicates found in any order files")

    # Final Global Summary
    print(f"\n{'='*10} DEDUPLICATION COMPLETE {'='*10}")
    
    total_files_cleaned = total_limit_files_cleaned + total_signal_files_cleaned + total_limit_backup_files_cleaned
    total_duplicates_removed = total_limit_duplicates + total_signal_duplicates + total_limit_backup_duplicates
    
    if total_duplicates_removed > 0:
        print(f" Total Duplicates Purged: {total_duplicates_removed}")
        print(f" Total Files Modified:    {total_files_cleaned}")
        print(f"\n Breakdown by file type:")
        print(f"   • limit_orders.json:        {total_limit_files_cleaned} files | {total_limit_duplicates} duplicates")
        print(f"   • limit_orders_backup.json: {total_limit_backup_files_cleaned} files | {total_limit_backup_duplicates} duplicates")
        print(f"   • signals.json:             {total_signal_files_cleaned} files | {total_signal_duplicates} duplicates")
    else:
        print(" ✅ Everything was already clean - no duplicates found!")
    print(f"{'='*33}\n")
    
    return any_duplicates_removed

def detect_unauthorized_action(inv_id=None):
    """
    Detects unauthorized trading activities and withdrawals for investors.
    Compares MT5 activity with tradeshistory.json from execution start date.
    Ensures NO other trades exist in MT5 history except those recorded in tradeshistory.json
    activities.json is located directly in INV_PATH/{investor_id}/ (new path structure)
    """
    
    def load_activities_config(inv_root):
        """Load activities.json directly from investor root folder"""
        activities_path = inv_root / "activities.json"
        if not activities_path.exists():
            print(f"    ⚠️  activities.json not found at {activities_path}")
            return None, None
        
        try:
            with open(activities_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            return config, activities_path
        except Exception as e:
            print(f"    ❌ Error loading activities.json: {e}")
            return None, None

    def load_trades_history(inv_root):
        """Load all trades from tradeshistory.json directly from investor root (the ONLY source of truth)"""
        history_path = inv_root / "tradeshistory.json"
        if not history_path.exists():
            print(f"    ⚠️  tradeshistory.json not found at {history_path}")
            return []
        
        try:
            with open(history_path, 'r', encoding='utf-8') as f:
                trades = json.load(f)
            return trades if isinstance(trades, list) else []
        except Exception as e:
            print(f"    ⚠️  Error loading tradeshistory.json: {e}")
            return []

    def get_mt5_activity_since(start_date, authorized_trades_list):
        """
        Get all MT5 trades since start_date
        Returns ONLY trades that are NOT in tradeshistory.json as unauthorized
        """
        # Convert start_date string to datetime
        try:
            # Try parsing "March 03, 2026" format
            start_datetime = datetime.strptime(start_date, "%B %d, %Y")
            # Set to beginning of the day
            start_datetime = start_datetime.replace(hour=0, minute=0, second=0)
        except:
            try:
                # Fallback to ISO format
                start_datetime = datetime.strptime(start_date, "%Y-%m-%d")
                start_datetime = start_datetime.replace(hour=0, minute=0, second=0)
            except:
                print(f"    ❌ Invalid date format: {start_date}")
                return [], []

        print(f"    🔍 Checking MT5 history from: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Create lookup of authorized tickets from tradeshistory.json (the ONLY source)
        authorized_tickets = set()
        for trade in authorized_trades_list:
            if 'ticket' in trade and trade['ticket']:
                authorized_tickets.add(int(trade['ticket']))

        # Get ALL deals (completed trades) since start date
        all_deals = mt5.history_deals_get(start_datetime, datetime.now()) or []
        
        print(f"    📊 Total MT5 deals found: {len(all_deals)}")
        print(f"    📋 Authorized tickets in tradeshistory.json: {len(authorized_tickets)}")
        
        unauthorized_trades = []
        withdrawals = []
        
        # Track processed tickets to avoid duplicates
        processed_tickets = set()
        
        # Check all deals (completed and closed trades)
        for deal in all_deals:
            deal_ticket = deal.ticket
            
            # Skip if already processed
            if deal_ticket in processed_tickets:
                continue
            processed_tickets.add(deal_ticket)
            
            # Check if this is a withdrawal (balance operation)
            if deal.type == mt5.DEAL_TYPE_BALANCE:
                if deal.profit < 0:  # Withdrawal
                    withdrawals.append({
                        'ticket': deal_ticket,
                        'amount': abs(deal.profit),
                        'balance': deal.balance,
                        'time': datetime.fromtimestamp(deal.time).strftime("%Y-%m-%d %H:%M:%S"),
                        'timestamp': deal.time,
                        'comment': deal.comment or 'Unknown',
                        'reason': 'Funds withdrawn',
                        'detected_at': datetime.now().isoformat()
                    })
                continue
            
            # For regular trades, check if this deal is authorized
            # A trade is authorized ONLY if its ticket exists in tradeshistory.json
            if deal_ticket not in authorized_tickets:
                # This is an unauthorized trade - NOT in tradeshistory.json
                deal_time = datetime.fromtimestamp(deal.time).strftime("%Y-%m-%d %H:%M:%S")
                deal_type = "BUY" if deal.type == mt5.DEAL_TYPE_BUY else "SELL" if deal.type == mt5.DEAL_TYPE_SELL else "UNKNOWN"
                
                unauthorized_trades.append({
                    'ticket': deal_ticket,
                    'order': deal.order,
                    'symbol': deal.symbol,
                    'volume': deal.volume,
                    'price': deal.price,
                    'type': deal_type,
                    'time': deal_time,
                    'timestamp': deal.time,
                    'magic': deal.magic,
                    'commission': deal.commission,
                    'swap': deal.swap,
                    'profit': deal.profit,
                    'reason': f"Trade NOT in tradeshistory.json (Ticket: {deal_ticket})",
                    'detected_at': datetime.now().isoformat()
                })
                print(f"      ⚠️  Found unauthorized trade: Ticket {deal_ticket} ({deal.symbol}) not in tradeshistory.json")
        
        return unauthorized_trades, withdrawals

    # --- MAIN EXECUTION ---
    print("\n" + "="*80)
    print("🔍 DETECTING UNAUTHORIZED ACTIONS")
    print("="*80)
    print("📋 Checking that ONLY trades in tradeshistory.json have been executed")
    
    # Get investor IDs to check
    investor_ids = [inv_id] if inv_id else list(usersdictionary.keys())
    unauthorized_detected = False

    for user_brokerid in investor_ids:
        print(f"\n📋 INVESTOR: {user_brokerid}")
        print("-" * 60)
        
        # Setup paths - DIRECTLY in investor root folder (new path structure)
        inv_root = Path(INV_PATH) / user_brokerid
        
        if not inv_root.exists():
            print(f"  ❌ Path not found: {inv_root}")
            continue

        # Load activities.json directly from investor root
        config, activities_path = load_activities_config(inv_root)
        if not config:
            print(f"  ⚠️  No activities.json found at {inv_root / 'activities.json'}, skipping...")
            continue
        
        # Check if autotrading is activated
        if not config.get('activate_autotrading', False):
            print(f"  ⏭️  AutoTrading not activated, skipping...")
            continue
        
        # Get execution start date
        execution_start = config.get('execution_start_date')
        if not execution_start:
            print(f"  ⚠️  No execution start date found, using today")
            execution_start = datetime.now().strftime("%B %d, %Y")
        
        print(f"  📅 Checking activity since: {execution_start}")
        
        # Load trades history from tradeshistory.json (the ONLY authorized trades)
        trades_history = load_trades_history(inv_root)
        print(f"  📊 Authorized trades in tradeshistory.json: {len(trades_history)}")
        
        # Get MT5 activity since execution start
        unauthorized_trades, withdrawals = get_mt5_activity_since(
            execution_start, 
            trades_history
        )
        
        # Update config with findings
        config_updated = False
        
        # Format unauthorized trades for storage (using ticket numbers as keys)
        new_unauthorized_trades = {}
        for trade in unauthorized_trades:
            ticket = trade.get('ticket')
            if ticket:
                new_unauthorized_trades[f"ticket_{ticket}"] = trade
        
        if new_unauthorized_trades:
            print(f"  ⚠️  Found {len(unauthorized_trades)} UNAUTHORIZED trades!")
            print(f"  ⚠️  These trades exist in MT5 but NOT in tradeshistory.json")
            if new_unauthorized_trades != config.get('unauthorized_trades', {}):
                config['unauthorized_trades'] = new_unauthorized_trades
                config_updated = True
                unauthorized_detected = True
        else:
            if config.get('unauthorized_trades'):
                config['unauthorized_trades'] = {}
                config_updated = True
            print(f"  ✅ ALL trades in MT5 match tradeshistory.json - No unauthorized trades")
        
        # Format withdrawals for storage
        new_withdrawals = {}
        for wd in withdrawals:
            ticket = wd.get('ticket')
            if ticket:
                new_withdrawals[f"withdrawal_{ticket}"] = wd
        
        if new_withdrawals:
            print(f"  ⚠️  Found {len(withdrawals)} unauthorized withdrawals!")
            if new_withdrawals != config.get('unauthorized_withdrawals', {}):
                config['unauthorized_withdrawals'] = new_withdrawals
                config_updated = True
                unauthorized_detected = True
        else:
            if config.get('unauthorized_withdrawals'):
                config['unauthorized_withdrawals'] = {}
                config_updated = True
            print(f"  ✅ No unauthorized withdrawals detected")
        
        # Update detection flag
        new_detection_status = bool(unauthorized_trades or withdrawals)
        if new_detection_status != config.get('unauthorized_action_detected', False):
            config['unauthorized_action_detected'] = new_detection_status
            config_updated = True
        
        # Save updated config if changes were made
        if config_updated:
            try:
                with open(activities_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=4)
                print(f"  💾 Updated activities.json at: {activities_path}")
                
                # Print detailed summary of unauthorized activities
                if unauthorized_trades:
                    print(f"\n  🚨 UNAUTHORIZED TRADES DETAILS:")
                    for trade in unauthorized_trades:
                        print(f"      - Ticket: {trade['ticket']} | {trade.get('symbol', 'N/A')} | "
                              f"{trade.get('type', 'N/A')} | {trade.get('volume', 'N/A')} lots | "
                              f"Price: {trade.get('price', 'N/A')} | Profit: ${trade.get('profit', 0):.2f}")
                        print(f"        Time: {trade.get('time', 'N/A')}")
                        print(f"        Reason: {trade.get('reason', 'Unknown')}")
                        print()
                
                if withdrawals:
                    print(f"\n  🚨 UNAUTHORIZED WITHDRAWALS DETAILS:")
                    for wd in withdrawals:
                        print(f"      - Ticket: {wd['ticket']} | Amount: ${wd['amount']:.2f} | "
                              f"Time: {wd['time']} | Comment: {wd['comment']}")
                        print()
                        
            except Exception as e:
                print(f"  ❌ Failed to save activities.json: {e}")
        else:
            print(f"  ℹ️  No changes to activities.json")

    print("\n" + "="*80)
    if unauthorized_detected:
        print("⚠️  UNAUTHORIZED ACTIONS DETECTED!")
        print("⚠️  Some trades in MT5 are NOT recorded in tradeshistory.json")
        print("⚠️  Check activities.json for complete details")
    else:
        print("✅ NO UNAUTHORIZED ACTIONS DETECTED")
        print("✅ All MT5 trades match records in tradeshistory.json")
    print("="*80)
    
    return unauthorized_detected

def filter_unauthorized_symbols(inv_id=None):
    """
    Verifies and filters pending order files based on allowed symbols defined in accountmanagement.json.
    Now filters both limit_orders.json and signals.json files, removing any entries with unauthorized symbols.
    Matches sanitized versions of symbols to handle broker suffixes (e.g., EURUSDm vs EURUSD).
    
    Args:
        inv_id (str, optional): Specific investor ID to process. If None, processes all investors.
        This function does NOT require MT5.
    
    Returns:
        bool: True if any unauthorized symbols were removed, False otherwise
    """
    print(f"\n{'='*10} 🛡️  SYMBOL AUTHORIZATION FILTER {'='*10}")

    def sanitize(sym):
        if not sym: return ""
        # Remove non-alphanumeric, uppercase, and strip trailing M/PRO suffixes
        clean = re.sub(r'[^a-zA-Z0-9]', '', str(sym)).upper()
        return re.sub(r'(PRO|M)$', '', clean)

    if not os.path.exists(INV_PATH):
        print(f" [!] Error: Investor path {INV_PATH} not found.")
        return False

    # Determine which investors to process
    if inv_id:
        investor_ids = [inv_id]
    else:
        investor_ids = [f for f in os.listdir(INV_PATH) if os.path.isdir(os.path.join(INV_PATH, f))]
    
    if not investor_ids:
        print(" └─ 🔘 No investor directories found for filtering.")
        return False

    total_files_cleaned = 0
    total_entries_removed = 0
    total_limit_files_cleaned = 0
    total_signal_files_cleaned = 0
    total_limit_removed = 0
    total_signal_removed = 0
    any_symbols_removed = False

    for current_inv_id in investor_ids:
        print(f"\n [{current_inv_id}] 🔍 Verifying symbol permissions...")
        inv_folder = Path(INV_PATH) / current_inv_id
        acc_mgmt_path = inv_folder / "accountmanagement.json"
        
        if not acc_mgmt_path.exists():
            print(f"  └─ ⚠️  Account config missing. Skipping.")
            continue

        try:
            with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Extract and sanitize the list of allowed symbols
            sym_dict = config.get("symbols_dictionary", {})
            allowed_sanitized = {sanitize(s) for sublist in sym_dict.values() for s in sublist}
            
            if not allowed_sanitized:
                print(f"  └─ 🔘 No symbols defined in dictionary. Skipping filter.")
                continue

            print(f"  └─ ✅ Found {len(allowed_sanitized)} authorized symbols")

            # Search for pending_orders folders
            pending_orders_folders = list(inv_folder.rglob("*/pending_orders/"))
            
            investor_limit_removed = 0
            investor_signal_removed = 0
            investor_limit_files_cleaned = 0
            investor_signal_files_cleaned = 0

            for pending_folder in pending_orders_folders:
                # Process limit_orders.json
                limit_file = pending_folder / "limit_orders.json"
                if limit_file.exists():
                    try:
                        with open(limit_file, 'r', encoding='utf-8') as f:
                            orders = json.load(f)

                        if orders and isinstance(orders, list):
                            original_count = len(orders)
                            
                            # Filter: Keep only if the sanitized symbol exists in our allowed set
                            filtered_orders = [
                                order for order in orders 
                                if sanitize(order.get("symbol", "")) in allowed_sanitized
                            ]
                            
                            # Only write back if entries were actually removed
                            if len(filtered_orders) < original_count:
                                removed = original_count - len(filtered_orders)
                                with open(limit_file, 'w', encoding='utf-8') as f:
                                    json.dump(filtered_orders, f, indent=4)
                                
                                investor_limit_removed += removed
                                investor_limit_files_cleaned += 1
                                total_limit_removed += removed
                                total_limit_files_cleaned += 1
                                any_symbols_removed = True
                                
                                folder_name = pending_folder.parent.name
                                print(f"    └─ 📄 {folder_name}/limit_orders.json - Removed {removed} unauthorized entries")
                            elif original_count > 0:
                                folder_name = pending_folder.parent.name
                                print(f"    └─ ✅ {folder_name}/limit_orders.json - All symbols authorized ({original_count} entries)")

                    except Exception as e:
                        print(f"    └─ ❌ Error processing {limit_file}: {e}")

                # Process signals.json
                signals_file = pending_folder / "signals.json"
                if signals_file.exists():
                    try:
                        with open(signals_file, 'r', encoding='utf-8') as f:
                            signals = json.load(f)

                        if signals and isinstance(signals, list):
                            original_count = len(signals)
                            
                            # Filter: Keep only if the sanitized symbol exists in our allowed set
                            filtered_signals = [
                                signal for signal in signals 
                                if sanitize(signal.get("symbol", "")) in allowed_sanitized
                            ]
                            
                            # Only write back if entries were actually removed
                            if len(filtered_signals) < original_count:
                                removed = original_count - len(filtered_signals)
                                with open(signals_file, 'w', encoding='utf-8') as f:
                                    json.dump(filtered_signals, f, indent=4)
                                
                                investor_signal_removed += removed
                                investor_signal_files_cleaned += 1
                                total_signal_removed += removed
                                total_signal_files_cleaned += 1
                                any_symbols_removed = True
                                
                                folder_name = pending_folder.parent.name
                                print(f"    └─ 📄 {folder_name}/signals.json - Removed {removed} unauthorized entries")
                            elif original_count > 0:
                                folder_name = pending_folder.parent.name
                                print(f"    └─ ✅ {folder_name}/signals.json - All symbols authorized ({original_count} entries)")

                    except Exception as e:
                        print(f"    └─ ❌ Error processing {signals_file}: {e}")

            # Summary for the current investor
            if investor_limit_removed > 0 or investor_signal_removed > 0:
                print(f"\n  └─ ✨ Investor {current_inv_id} Filter Summary:")
                if investor_limit_removed > 0:
                    print(f"      • limit_orders.json: Cleaned {investor_limit_files_cleaned} files | Removed {investor_limit_removed} unauthorized entries")
                if investor_signal_removed > 0:
                    print(f"      • signals.json: Cleaned {investor_signal_files_cleaned} files | Removed {investor_signal_removed} unauthorized entries")
            else:
                # Check if any files were found at all
                if pending_orders_folders:
                    print(f"  └─ ✅ All symbols in order files are authorized")
                else:
                    print(f"  └─ 🔘 No pending_orders folders found")

        except Exception as e:
            print(f"  └─ ❌ Error processing {current_inv_id}: {e}")

    # Final Global Summary
    print(f"\n{'='*10} SYMBOL FILTERING COMPLETE {'='*10}")
    
    total_files_cleaned = total_limit_files_cleaned + total_signal_files_cleaned
    total_entries_removed = total_limit_removed + total_signal_removed
    
    if total_entries_removed > 0:
        print(f" Total Unauthorized Entries Removed: {total_entries_removed}")
        print(f" Total Files Modified:               {total_files_cleaned}")
        print(f"\n Breakdown by file type:")
        print(f"   • limit_orders.json:   {total_limit_files_cleaned} files | {total_limit_removed} entries removed")
        print(f"   • signals.json:        {total_signal_files_cleaned} files | {total_signal_removed} entries removed")
    else:
        if total_files_cleaned == 0:
            print(" ✅ No files needed filtering - all symbols were already authorized!")
        else:
            print(" ✅ All files checked and verified - no unauthorized symbols found!")
    print(f"{'='*39}\n")
    
    return any_symbols_removed

def filter_unauthorized_timeframes(inv_id=None):
    """
    Verifies and filters pending order files based on restricted timeframes defined in accountmanagement.json.
    Now filters both limit_orders.json and signals.json files, removing any entries with restricted timeframes.
    Matches the 'timeframe' key in order files against the 'restrict_order_from_timeframe' setting.
    
    Args:
        inv_id (str, optional): Specific investor ID to process. If None, processes all investors.
        This function does NOT require MT5.
    
    Returns:
        bool: True if any restricted timeframes were removed, False otherwise
    """
    print(f"\n{'='*10} 🛡️  TIMEFRAME AUTHORIZATION FILTER {'='*10}")

    def sanitize_tf(tf):
        if not tf: return ""
        # Ensure uniform comparison (lowercase, stripped)
        return str(tf).strip().lower()

    if not os.path.exists(INV_PATH):
        print(f" [!] Error: Investor path {INV_PATH} not found.")
        return False

    # Determine which investors to process
    if inv_id:
        investor_ids = [inv_id]
    else:
        investor_ids = [f for f in os.listdir(INV_PATH) if os.path.isdir(os.path.join(INV_PATH, f))]
    
    if not investor_ids:
        print(" └─ 🔘 No investor directories found for filtering.")
        return False

    total_files_cleaned = 0
    total_entries_removed = 0
    total_limit_files_cleaned = 0
    total_signal_files_cleaned = 0
    total_limit_removed = 0
    total_signal_removed = 0
    any_timeframes_removed = False

    for current_inv_id in investor_ids:
        print(f"\n [{current_inv_id}] 🔍 Checking timeframe restrictions...")
        inv_folder = Path(INV_PATH) / current_inv_id
        acc_mgmt_path = inv_folder / "accountmanagement.json"
        
        if not acc_mgmt_path.exists():
            print(f"  └─ ⚠️  Account config missing. Skipping.")
            continue

        try:
            with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Extract restriction setting
            # Supports: "5m" OR ["1m", "5m"]
            raw_restrictions = config.get("settings", {}).get("restrict_order_from_timeframe", [])
            
            if isinstance(raw_restrictions, str):
                # Handle comma separated strings or single strings
                restricted_list = [s.strip() for s in raw_restrictions.split(',')]
            elif isinstance(raw_restrictions, list):
                restricted_list = raw_restrictions
            else:
                restricted_list = []

            restricted_set = {sanitize_tf(t) for t in restricted_list if t}

            if not restricted_set:
                print(f"  └─ ✅ No timeframe restrictions active.")
                continue

            print(f"  └─ 🚫 Restricted timeframes: {', '.join(restricted_set)}")

            # Search for pending_orders folders
            pending_orders_folders = list(inv_folder.rglob("*/pending_orders/"))
            
            investor_limit_removed = 0
            investor_signal_removed = 0
            investor_limit_files_cleaned = 0
            investor_signal_files_cleaned = 0

            for pending_folder in pending_orders_folders:
                # Process limit_orders.json
                limit_file = pending_folder / "limit_orders.json"
                if limit_file.exists():
                    try:
                        with open(limit_file, 'r', encoding='utf-8') as f:
                            orders = json.load(f)

                        if orders and isinstance(orders, list):
                            original_count = len(orders)
                            
                            # Filter: Keep only if the entry's timeframe is NOT in the restricted set
                            filtered_orders = [
                                order for order in orders 
                                if sanitize_tf(order.get("timeframe")) not in restricted_set
                            ]
                            
                            # Only write back if entries were actually removed
                            if len(filtered_orders) < original_count:
                                removed = original_count - len(filtered_orders)
                                with open(limit_file, 'w', encoding='utf-8') as f:
                                    json.dump(filtered_orders, f, indent=4)
                                
                                investor_limit_removed += removed
                                investor_limit_files_cleaned += 1
                                total_limit_removed += removed
                                total_limit_files_cleaned += 1
                                any_timeframes_removed = True
                                
                                folder_name = pending_folder.parent.name
                                print(f"    └─ 📄 {folder_name}/limit_orders.json - Removed {removed} restricted timeframe entries")
                            elif original_count > 0:
                                folder_name = pending_folder.parent.name
                                print(f"    └─ ✅ {folder_name}/limit_orders.json - All timeframes authorized ({original_count} entries)")

                    except Exception as e:
                        print(f"    └─ ❌ Error processing {limit_file}: {e}")

                # Process signals.json
                signals_file = pending_folder / "signals.json"
                if signals_file.exists():
                    try:
                        with open(signals_file, 'r', encoding='utf-8') as f:
                            signals = json.load(f)

                        if signals and isinstance(signals, list):
                            original_count = len(signals)
                            
                            # Filter: Keep only if the entry's timeframe is NOT in the restricted set
                            filtered_signals = [
                                signal for signal in signals 
                                if sanitize_tf(signal.get("timeframe")) not in restricted_set
                            ]
                            
                            # Only write back if entries were actually removed
                            if len(filtered_signals) < original_count:
                                removed = original_count - len(filtered_signals)
                                with open(signals_file, 'w', encoding='utf-8') as f:
                                    json.dump(filtered_signals, f, indent=4)
                                
                                investor_signal_removed += removed
                                investor_signal_files_cleaned += 1
                                total_signal_removed += removed
                                total_signal_files_cleaned += 1
                                any_timeframes_removed = True
                                
                                folder_name = pending_folder.parent.name
                                print(f"    └─ 📄 {folder_name}/signals.json - Removed {removed} restricted timeframe entries")
                            elif original_count > 0:
                                folder_name = pending_folder.parent.name
                                print(f"    └─ ✅ {folder_name}/signals.json - All timeframes authorized ({original_count} entries)")

                    except Exception as e:
                        print(f"    └─ ❌ Error processing {signals_file}: {e}")

            # Summary for the current investor
            if investor_limit_removed > 0 or investor_signal_removed > 0:
                print(f"\n  └─ ✨ Investor {current_inv_id} Filter Summary:")
                if investor_limit_removed > 0:
                    print(f"      • limit_orders.json: Cleaned {investor_limit_files_cleaned} files | Removed {investor_limit_removed} restricted entries")
                if investor_signal_removed > 0:
                    print(f"      • signals.json: Cleaned {investor_signal_files_cleaned} files | Removed {investor_signal_removed} restricted entries")
                print(f"     (Blocked timeframes: {', '.join(restricted_set)})")
            else:
                # Check if any files were found at all
                if pending_orders_folders:
                    print(f"  └─ ✅ All timeframes in order files are authorized")
                else:
                    print(f"  └─ 🔘 No pending_orders folders found")

        except Exception as e:
            print(f"  └─ ❌ Error processing {current_inv_id}: {e}")

    # Final Global Summary
    print(f"\n{'='*10} TIMEFRAME FILTERING COMPLETE {'='*10}")
    
    total_files_cleaned = total_limit_files_cleaned + total_signal_files_cleaned
    total_entries_removed = total_limit_removed + total_signal_removed
    
    if total_entries_removed > 0:
        print(f" Total Restricted Entries Removed: {total_entries_removed}")
        print(f" Total Files Modified:              {total_files_cleaned}")
        print(f"\n Breakdown by file type:")
        print(f"   • limit_orders.json:   {total_limit_files_cleaned} files | {total_limit_removed} entries removed")
        print(f"   • signals.json:        {total_signal_files_cleaned} files | {total_signal_removed} entries removed")
    else:
        if total_files_cleaned == 0:
            print(" ✅ No files needed filtering - no restricted timeframes found!")
        else:
            print(" ✅ All files checked and verified - no restricted timeframes found!")
    print(f"{'='*41}\n")
    
    return any_timeframes_removed

def backup_limit_orders(inv_id=None):
    """
    Finds all limit_orders.json files and creates a copy named 
    limit_orders_backup.json in the same directory.
    
    Args:
        inv_id (str, optional): Specific investor ID to process. 
                               If None, processes all investors.
    """
    print(f"\n{'='*10} 📂 CREATING LIMIT ORDERS BACKUP {'='*10}")
    
    inv_base_path = Path(INV_PATH)
    total_backups_created = 0

    if not inv_base_path.exists():
        print(f" [!] Error: Investor path {INV_PATH} does not exist.")
        return False

    # 1. Determine which investors to process
    if inv_id:
        investor_folders = [inv_base_path / inv_id]
    else:
        investor_folders = [f for f in inv_base_path.iterdir() if f.is_dir()]

    # 2. Loop through each investor folder
    for inv_folder in investor_folders:
        if not inv_folder.exists():
            continue
            
        print(f" [{inv_folder.name}] Scanning for limit_orders.json...")

        # 3. Find all limit_orders.json files (using rglob for subfolders)
        # Specifically targeting the 'pending_orders' subfolder pattern
        target_files = list(inv_folder.rglob("*/pending_orders/limit_orders.json"))

        for source_path in target_files:
            # Define the backup path in the same directory
            backup_path = source_path.parent / "limit_orders_backup.json"
            
            try:
                # 4. Create the copy (overwrites existing backup)
                shutil.copy2(source_path, backup_path)
                
                print(f"  └─ ✅ Backed up: {source_path.parent.parent.name} -> limit_orders_backup.json")
                total_backups_created += 1
                
            except Exception as e:
                print(f"  └─ ❌ Error backing up {source_path}: {e}")

    print(f"\n{'='*10} BACKUP PROCESS COMPLETE {'='*10}")
    print(f" Total backups created: {total_backups_created}")
    return total_backups_created > 0

def populate_orders_missing_fields(inv_id=None, callback_function=None):
    print(f"\n{'='*10} 📊 POPULATING ORDER FIELDS {'='*10}")
    
    total_files_updated = 0
    total_orders_updated = 0
    total_symbols_normalized = 0
    inv_base_path = Path(INV_PATH)

    investor_folders = [inv_base_path / inv_id] if inv_id else [f for f in inv_base_path.iterdir() if f.is_dir()]
    
    for inv_folder in investor_folders:
        current_inv_id = inv_folder.name
        print(f" [{current_inv_id}] 🔍 Processing orders...")

        # Local Cache for this investor to prevent redundant lookups
        # Format: { "raw_symbol": {"broker_sym": "normalized", "info": mt5_obj} }
        resolution_cache = {}

        order_files = list(inv_folder.rglob("*/pending_orders/limit_orders.json"))
        if not order_files: continue
            
        broker_cfg = usersdictionary.get(current_inv_id)
        if not broker_cfg: continue
            
        server = broker_cfg.get('SERVER', '')
        broker_prefix = server.split('-')[0].split('.')[0].lower() if server else 'broker'
        v_field, ts_field, tv_field = f"{broker_prefix}_volume", f"{broker_prefix}_tick_size", f"{broker_prefix}_tick_value"

        for file_path in order_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    orders = json.load(f)
                if not orders: continue
                
                modified = False
                for order in orders:
                    raw_symbol = order.get("symbol")
                    if not raw_symbol: continue

                    # Check Cache First
                    if raw_symbol in resolution_cache:
                        res = resolution_cache[raw_symbol]
                        broker_symbol = res['broker_sym']
                        symbol_info = res['info']
                    else:
                        # Perform mapping only once
                        broker_symbol = get_normalized_symbol(raw_symbol)
                        symbol_info = mt5.symbol_info(broker_symbol)
                        
                        resolution_cache[raw_symbol] = {'broker_sym': broker_symbol, 'info': symbol_info}
                        
                        # Detailed Log only on first discovery
                        if symbol_info:
                            if broker_symbol != raw_symbol:
                                print(f"    └─ ✅ {raw_symbol} -> {broker_symbol} (Mapped & Cached)")
                                total_symbols_normalized += 1
                        else:
                            print(f"    └─ ❌ MT5: '{broker_symbol}' (from '{raw_symbol}') not found in MarketWatch")

                    if symbol_info:
                        order['symbol'] = broker_symbol
                        
                        # Cleanup and Update
                        for key in list(order.keys()):
                            if any(x in key.lower() for x in ['volume', 'tick_size', 'tick_value']) and key not in [v_field, ts_field, tv_field]:
                                del order[key]

                        order[v_field] = symbol_info.volume_min
                        order[ts_field] = symbol_info.trade_tick_size
                        order[tv_field] = symbol_info.trade_tick_value
                        total_orders_updated += 1
                        modified = True

                if modified:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(orders, f, indent=4)
                    total_files_updated += 1

            except Exception as e:
                print(f"  └─ ❌ Error: {e}")

    print(f"\n{'='*10} POPULATION COMPLETE {'='*10}")
    print(f" Total Orders Updated:      {total_orders_updated}")
    print(f" Total Symbols Normalized:  {total_symbols_normalized}")
    return True

def activate_usd_based_risk_on_empty_pricelevels(inv_id=None):
    print(f"\n{'='*10} 📊 INVESTOR EMPTY TARGET CHECK - USD RISK ENFORCEMENT {'='*10}")
    
    total_orders_processed = 0
    total_orders_enforced = 0
    total_files_updated = 0
    inv_base_path = Path(INV_PATH)

    if not inv_base_path.exists():
        print(f" [!] Error: Investor path {INV_PATH} does not exist.")
        return False

    investor_folders = [inv_base_path / inv_id] if inv_id else [f for f in inv_base_path.iterdir() if f.is_dir()]
    
    for inv_folder in investor_folders:
        current_inv_id = inv_folder.name
        print(f"\n [{current_inv_id}] 🔍 Processing empty target check...")

        # Cache for risk mappings to avoid re-calculating family logic 1000s of times
        risk_map_cache = {}

        broker_cfg = usersdictionary.get(current_inv_id)
        if not broker_cfg:
            print(f"  └─ ❌ No broker config found")
            continue
        
        broker_name = broker_cfg.get('BROKER_NAME', '').lower() or \
                      broker_cfg.get('SERVER', 'default').split('-')[0].split('.')[0].lower()

        default_config_path = Path(DEFAULT_PATH) / f"{broker_name}_default_allowedsymbolsandvolumes.json"
        
        risk_lookup = {}
        if default_config_path.exists():
            try:
                with open(default_config_path, 'r', encoding='utf-8') as f:
                    default_config = json.load(f)
                    for category, items in default_config.items():
                        if not isinstance(items, list): continue
                        for item in items:
                            sym = str(item.get("symbol", "")).upper()
                            if sym:
                                risk_lookup[sym] = {
                                    k.replace("_specs", "").upper(): v.get("usd_risk", 0)
                                    for k, v in item.items() if k.endswith("_specs")
                                }
                print(f"  └─ ✅ Loaded risk config for {len(risk_lookup)} symbols")
            except Exception as e:
                print(f"  └─ ❌ Risk config error: {e}")
                continue

        known_risk_symbols = list(risk_lookup.keys())
        order_files = list(inv_folder.rglob("*/pending_orders/limit_orders.json"))
        signals_files = list(inv_folder.rglob("*/signals/signals.json"))
        
        for file_list, label in [(order_files, "LIMITS"), (signals_files, "SIGNALS")]:
            for file_path in file_list:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    if not data: continue
                    modified = False
                    
                    for item in data:
                        if item.get('exit') in [0, "0", None, 0.0] and \
                           item.get('target') in [0, "0", None, 0.0]:
                            
                            total_orders_processed += 1
                            raw_sym = str(item.get('symbol', '')).upper()
                            raw_tf = str(item.get('timeframe', '')).upper()
                            
                            # Cache Logic for Risk Mapping
                            if raw_sym not in risk_map_cache:
                                matched_sym = get_normalized_symbol(raw_sym, risk_keys=known_risk_symbols)
                                risk_map_cache[raw_sym] = matched_sym
                                
                                # Print mapping only once per symbol type
                                if matched_sym not in risk_lookup:
                                    print(f"      ❌ [{label}] {raw_sym}: Not in risk config (Mapped as: {matched_sym})")
                            else:
                                matched_sym = risk_map_cache[raw_sym]
                            
                            if matched_sym in risk_lookup:
                                tf_risks = risk_lookup[matched_sym]
                                risk_value = tf_risks.get(raw_tf, 0)
                                
                                if risk_value > 0:
                                    item.update({
                                        'exit': 0, 'target': 0, 'usd_risk': risk_value,
                                        'usd_based_risk_only': True, 'symbol': matched_sym
                                    })
                                    modified = True
                                    total_orders_enforced += 1
                                    
                                    # Logic to avoid spamming the same enforcement 1000 times in logs
                                    # Only log the first time we enforce this symbol/tf pair for this file
                                    if f"{raw_sym}_{raw_tf}" not in risk_map_cache:
                                        print(f"      ✅ [{label}] {matched_sym} ({raw_sym}) {raw_tf}: Enforced ${risk_value} risk")
                                        risk_map_cache[f"{raw_sym}_{raw_tf}"] = True
                                
                    if modified:
                        with open(file_path, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=4)
                        total_files_updated += 1

                except Exception as e:
                    print(f"    └─ ❌ Error processing {file_path.name}: {e}")

    print(f"\n{'='*10} ENFORCEMENT COMPLETE {'='*10}")
    print(f" Total Targetless Found:  {total_orders_processed}")
    print(f" Total Risk Enforced:    {total_orders_enforced}")
    print(f" Files Updated:          {total_files_updated}")
    
    return total_orders_enforced > 0

def enforce_investors_risk(inv_id=None):
    """
    Enforces risk rules for investors based on accountmanagement.json settings.
    Enhanced with Smart Normalization Caching and optimized lookup logic.
    """
    print(f"\n{'='*10} 📊 SMART INVESTOR RISK ENFORCEMENT {'='*10}")
    
    total_orders_processed = 0
    total_orders_enforced = 0
    total_files_updated = 0
    total_symbols_normalized = 0
    inv_base_path = Path(INV_PATH)

    if not inv_base_path.exists():
        print(f" [!] Error: Investor path {INV_PATH} does not exist.")
        return False

    investor_folders = [inv_base_path / inv_id] if inv_id else [f for f in inv_base_path.iterdir() if f.is_dir()]
    
    if not investor_folders:
        print(" └─ 🔘 No investor directories found.")
        return False

    any_orders_enforced = False
    
    for inv_folder in investor_folders:
        current_inv_id = inv_folder.name
        
        # --- INVESTOR LOCAL CACHE ---
        # Stores: { "RAW_SYM": {"matched": "NORM_SYM", "is_norm": True/False, "risk": {TF_DATA}} }
        resolution_cache = {}
        
        print(f"\n [{current_inv_id}] 🔍 Initializing smart enforcement...")

        # 1. Load accountmanagement.json
        acc_mgmt_path = inv_folder / "accountmanagement.json"
        if not acc_mgmt_path.exists():
            print(f"  └─ ⚠️  accountmanagement.json not found, skipping")
            continue

        try:
            with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                acc_mgmt_data = json.load(f)
            
            enforce_default = acc_mgmt_data.get("settings", {}).get("enforce_default_usd_risk", False)
            print(f"  └─ 🎯 Master Switch: {enforce_default}")
            
            if not enforce_default:
                print(f"  └─ ⏭️  Master switch is OFF - skipping")
                continue
        except Exception as e:
            print(f"  └─ ❌ Failed to load accountmanagement.json: {e}")
            continue

        # 2. Get Broker and Config Path
        broker_cfg = usersdictionary.get(current_inv_id)
        if not broker_cfg:
            continue
        
        broker_name = broker_cfg.get('BROKER_NAME', '').lower() or \
                      broker_cfg.get('SERVER', 'default').split('-')[0].split('.')[0].lower()

        default_config_path = Path(DEFAULT_PATH) / f"{broker_name}_default_allowedsymbolsandvolumes.json"
        if not default_config_path.exists():
            print(f"  └─ ❌ Default config not found: {default_config_path.name}")
            continue
        
        # 3. Build Risk Lookup Table
        risk_lookup = {}
        try:
            with open(default_config_path, 'r', encoding='utf-8') as f:
                default_config = json.load(f)
                for category, items in default_config.items():
                    if not isinstance(items, list): continue
                    for item in items:
                        sym = str(item.get("symbol", "")).upper()
                        if sym:
                            risk_lookup[sym] = {
                                k.replace("_specs", "").upper(): {
                                    "volume": v.get("volume", 0.01),
                                    "usd_risk": v.get("usd_risk", 0)
                                } for k, v in item.items() if k.endswith("_specs")
                            }
            known_risk_symbols = list(risk_lookup.keys())
            print(f"  └─ ✅ Loaded risk config for {len(risk_lookup)} symbols")
        except Exception as e:
            print(f"  └─ ❌ Failed to parse default config: {e}")
            continue

        # 4. Gather Files
        order_files = list(inv_folder.rglob("*/pending_orders/limit_orders.json"))
        signals_files = list(inv_folder.rglob("*/signals/signals.json"))
        
        investor_orders_enforced = 0
        investor_files_updated = 0
        
        # 5. Process Unified Pipeline
        for file_list, label in [(order_files, "LIMITS"), (signals_files, "SIGNALS")]:
            for file_path in file_list:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if not data: continue
                    
                    modified = False
                    for item in data:
                        total_orders_processed += 1
                        raw_sym = str(item.get('symbol', '')).upper()
                        raw_tf = str(item.get('timeframe', '')).upper()
                        
                        # --- SMART RESOLUTION LOGIC ---
                        if raw_sym not in resolution_cache:
                            # Helper does the heavy lifting: USOUSD -> USOIL
                            matched_sym = get_normalized_symbol(raw_sym, risk_keys=known_risk_symbols)
                            was_normalized = (matched_sym != raw_sym)
                            
                            # Cache the result
                            resolution_cache[raw_sym] = {
                                "matched": matched_sym,
                                "is_norm": was_normalized,
                                "risk_data": risk_lookup.get(matched_sym, {})
                            }
                            
                            # Log first-time discovery
                            if was_normalized and matched_sym in risk_lookup:
                                print(f"    └─ ✅ Normalized: {raw_sym} -> {matched_sym}")
                                total_symbols_normalized += 1
                        
                        res = resolution_cache[raw_sym]
                        matched_sym = res["matched"]
                        tf_data = res["risk_data"].get(raw_tf)

                        if tf_data and tf_data["usd_risk"] > 0:
                            # Apply Enforcement
                            item.update({
                                'exit': 0,
                                'target': 0,
                                'usd_risk': tf_data["usd_risk"],
                                'usd_based_risk_only': True,
                                'symbol': matched_sym
                            })
                            
                            # Update volume if specified
                            if tf_data["volume"] > 0:
                                for key in list(item.keys()):
                                    if 'volume' in key.lower():
                                        item[key] = tf_data["volume"]
                                        break
                                        
                            modified = True
                            investor_orders_enforced += 1
                            total_orders_enforced += 1
                        
                    if modified:
                        with open(file_path, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=4)
                        investor_files_updated += 1
                        total_files_updated += 1
                        
                except Exception as e:
                    print(f"    └─ ❌ Error in {file_path.name}: {e}")

        # Summary for this investor
        if investor_orders_enforced > 0:
            any_orders_enforced = True
            print(f"  └─ 📊 {current_inv_id} Complete: Enforced {investor_orders_enforced} orders across {investor_files_updated} files.")

    # Final Global Summary
    print(f"\n{'='*10} RISK ENFORCEMENT COMPLETE {'='*10}")
    print(f" Total Files Updated:   {total_files_updated}")
    print(f" Total Enforced:        {total_orders_enforced} / {total_orders_processed}")
    print(f" Symbols Normalized:    {total_symbols_normalized}")
    print(f"{'='*50}\n")
    
    return any_orders_enforced
    
def calculate_investor_symbols_orders(inv_id=None, callback_function=None):
    """
    Calculates Exit/Target prices for ALL orders in limit_orders.json files for investors.
    Uses strategy-specific risk_reward from strategies_risk_reward object in accountmanagement.json,
    falling back to selected_risk_reward if strategy not defined.
    
    Args:
        inv_id (str, optional): Specific investor ID to process. If None, processes all investors.
        callback_function (callable, optional): A function to call with the opened file data.
            The callback will receive (inv_id, file_path, orders_list, strategy_name, rr_ratio) parameters.
    
    Returns:
        bool: True if any orders were calculated, False otherwise
    """
    print(f"\n{'='*10} 📊 CALCULATING INVESTOR ORDER PRICES (Strategy-Specific R:R) {'='*10}")
    
    total_files_updated = 0
    total_orders_processed = 0
    total_orders_calculated = 0
    total_orders_skipped = 0
    total_symbols_normalized = 0
    strategies_used = {}  # Track which strategies used which R:R
    inv_base_path = Path(INV_PATH)

    if not inv_base_path.exists():
        print(f" [!] Error: Investor path {INV_PATH} does not exist.")
        return False

    # Determine which investors to process
    if inv_id:
        inv_folder = inv_base_path / inv_id
        investor_folders = [inv_folder] if inv_folder.exists() else []
        if not investor_folders:
            print(f" [!] Error: Investor folder {inv_id} does not exist.")
            return False
    else:
        investor_folders = [f for f in inv_base_path.iterdir() if f.is_dir()]
    
    if not investor_folders:
        print(" └─ 🔘 No investor directories found.")
        return False

    any_orders_calculated = False

    for inv_folder in investor_folders:
        current_inv_id = inv_folder.name
        print(f"\n [{current_inv_id}] 🔍 Processing orders with strategy-aware R:R...")

        # --- INVESTOR LOCAL CACHE for symbol normalization ---
        resolution_cache = {}

        # 1. Load accountmanagement.json to get risk reward configurations
        acc_mgmt_path = inv_folder / "accountmanagement.json"
        if not acc_mgmt_path.exists():
            print(f"  └─ ⚠️  accountmanagement.json not found for {current_inv_id}, skipping")
            continue

        try:
            with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                acc_mgmt_data = json.load(f)
            
            # Get default selected_risk_reward
            selected_rr = acc_mgmt_data.get("selected_risk_reward", [1.0])
            if isinstance(selected_rr, list) and len(selected_rr) > 0:
                default_rr_ratio = float(selected_rr[0])
            else:
                default_rr_ratio = float(selected_rr) if selected_rr else 1.0
            
            # Get strategy-specific risk rewards
            strategies_rr = acc_mgmt_data.get("strategies_risk_reward", {})
            
            print(f"  └─ 📊 Default R:R ratio: {default_rr_ratio}")
            if strategies_rr:
                print(f"  └─ 📋 Strategy-specific R:R configured for: {', '.join(strategies_rr.keys())}")
            
        except Exception as e:
            print(f"  └─ ❌ Failed to load accountmanagement.json: {e}")
            continue

        # 2. Get broker config for potential symbol mapping context
        broker_cfg = usersdictionary.get(current_inv_id)
        if not broker_cfg:
            print(f"  └─ ⚠️  No broker config found for {current_inv_id}")
            # Continue anyway as normalization might still work

        # 3. Find all limit_orders.json files
        order_files = list(inv_folder.rglob("*/pending_orders/limit_orders.json"))
        
        if not order_files:
            print(f"  └─ 🔘 No limit order files found")
            continue
            
        investor_files_updated = 0
        investor_orders_processed = 0
        investor_orders_calculated = 0
        investor_orders_skipped = 0
        
        # Process each file individually
        for file_path in order_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    orders = json.load(f)
                
                if not orders:
                    continue
                
                # --- GET STRATEGY NAME FROM FOLDER STRUCTURE ---
                # Strategy folder is the parent of the pending_orders folder
                strategy_name = file_path.parent.parent.name
                
                # --- DETERMINE WHICH R:R RATIO TO USE FOR THIS STRATEGY ---
                # Check if this strategy has a specific R:R configured
                if strategy_name in strategies_rr:
                    rr_ratio = float(strategies_rr[strategy_name])
                    rr_source = f"strategy-specific ({strategy_name}: {rr_ratio})"
                else:
                    rr_ratio = default_rr_ratio
                    rr_source = f"default (selected_risk_reward: {rr_ratio})"
                
                # Track strategy usage
                if strategy_name not in strategies_used:
                    strategies_used[strategy_name] = {
                        'investor': current_inv_id,
                        'rr_ratio': rr_ratio,
                        'source': 'specific' if strategy_name in strategies_rr else 'default'
                    }
                
                print(f"  └─ 📂 Strategy: '{strategy_name}' using {rr_source}")
                
                # Call callback function if provided with the original data (now including strategy info)
                if callback_function:
                    try:
                        callback_function(current_inv_id, file_path, orders, strategy_name, rr_ratio)
                    except Exception as e:
                        print(f"    └─ ⚠️  Callback error for {file_path.name}: {e}")
                
                # Track original orders for this file
                original_count = len(orders)
                investor_orders_processed += original_count
                
                # Process each order in this file
                orders_updated = False
                file_orders_calculated = 0
                file_orders_skipped = 0
                
                for order in orders:
                    try:
                        # --- SYMBOL NORMALIZATION with Caching ---
                        raw_symbol = order.get("symbol", "")
                        if not raw_symbol:
                            file_orders_skipped += 1
                            continue
                        
                        # Check Cache First
                        if raw_symbol in resolution_cache:
                            normalized_symbol = resolution_cache[raw_symbol]
                        else:
                            # Perform mapping only once
                            normalized_symbol = get_normalized_symbol(raw_symbol)
                            resolution_cache[raw_symbol] = normalized_symbol
                            
                            # Log normalization on first discovery
                            if normalized_symbol != raw_symbol:
                                print(f"    └─ ✅ {raw_symbol} -> {normalized_symbol} (Mapped & Cached)")
                                total_symbols_normalized += 1
                        
                        # Update the symbol in the order
                        if normalized_symbol:
                            order['symbol'] = normalized_symbol
                        
                        # --- CHECK FOR USD-BASED RISK FIRST (doesn't require volume) ---
                        if order.get("usd_based_risk_only") is True:
                            risk_val = float(order.get("usd_risk", 0))
                            
                            if risk_val > 0:
                                # For USD-based, we need volume but it might be named differently
                                # Try to find volume field
                                volume_value = None
                                for key, value in order.items():
                                    if 'volume' in key.lower() and isinstance(value, (int, float)):
                                        volume_value = float(value)
                                        break
                                
                                if volume_value is None or volume_value <= 0:
                                    print(f"      ⚠️  USD-based order missing volume for {order.get('symbol', 'Unknown')}, skipping")
                                    file_orders_skipped += 1
                                    continue
                                
                                # Find tick_size field
                                tick_size_value = None
                                for key, value in order.items():
                                    if 'tick_size' in key.lower() and isinstance(value, (int, float)):
                                        tick_size_value = float(value)
                                        break
                                
                                if tick_size_value is None or tick_size_value <= 0:
                                    tick_size_value = 0.00001
                                    print(f"      ⚠️  No tick_size found for {order.get('symbol', 'Unknown')}, using default")
                                
                                # Find tick_value field
                                tick_value_value = None
                                for key, value in order.items():
                                    if 'tick_value' in key.lower() and isinstance(value, (int, float)):
                                        tick_value_value = float(value)
                                        break
                                
                                if tick_value_value is None or tick_value_value <= 0:
                                    tick_value_value = 1.0
                                    print(f"      ⚠️  No tick_value found for {order.get('symbol', 'Unknown')}, using default")
                                
                                # Extract required order data
                                entry = float(order.get('entry', 0))
                                if entry == 0:
                                    file_orders_skipped += 1
                                    continue
                                    
                                order_type = str(order.get('order_type', '')).upper()
                                
                                # Calculate digits for rounding based on tick_size
                                if tick_size_value < 1:
                                    digits = len(str(tick_size_value).split('.')[-1])
                                else:
                                    digits = 0
                                
                                # Calculate using USD risk
                                sl_dist = (risk_val * tick_size_value) / (tick_value_value * volume_value)
                                tp_dist = sl_dist * rr_ratio
                                
                                if "BUY" in order_type:
                                    order["exit"] = round(entry - sl_dist, digits)
                                    order["target"] = round(entry + tp_dist, digits)
                                elif "SELL" in order_type:
                                    order["exit"] = round(entry + sl_dist, digits)
                                    order["target"] = round(entry - tp_dist, digits)
                                else:
                                    file_orders_skipped += 1
                                    continue
                                
                                file_orders_calculated += 1
                                any_orders_calculated = True
                                
                                # Update metadata with strategy info
                                order['risk_reward'] = rr_ratio
                                order['risk_reward_source'] = 'strategy_specific' if strategy_name in strategies_rr else 'default'
                                order['strategy_name'] = strategy_name
                                order['status'] = "Calculated"
                                order['calculated_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                orders_updated = True
                                continue  # Skip the rest of the processing for this order
                            else:
                                file_orders_skipped += 1
                                continue
                        
                        # --- NON-USD BASED ORDERS (require volume) ---
                        # Check for required volume field
                        volume_field = None
                        volume_value = None
                        
                        for key, value in order.items():
                            if 'volume' in key.lower() and isinstance(value, (int, float)):
                                volume_field = key
                                volume_value = float(value)
                                break
                        
                        if volume_value is None or volume_value <= 0:
                            file_orders_skipped += 1
                            continue
                        
                        # Find tick_size field
                        tick_size_field = None
                        tick_size_value = None
                        
                        for key, value in order.items():
                            if 'tick_size' in key.lower() and isinstance(value, (int, float)):
                                tick_size_field = key
                                tick_size_value = float(value)
                                break
                        
                        if tick_size_value is None or tick_size_value <= 0:
                            tick_size_value = 0.00001
                            print(f"      ⚠️  No tick_size found for {order.get('symbol', 'Unknown')}, using default")
                        
                        # Find tick_value field
                        tick_value_field = None
                        tick_value_value = None
                        
                        for key, value in order.items():
                            if 'tick_value' in key.lower() and isinstance(value, (int, float)):
                                tick_value_field = key
                                tick_value_value = float(value)
                                break
                        
                        if tick_value_value is None or tick_value_value <= 0:
                            tick_value_value = 1.0
                            print(f"      ⚠️  No tick_value found for {order.get('symbol', 'Unknown')}, using default")
                        
                        # Extract required order data
                        entry = float(order.get('entry', 0))
                        if entry == 0:
                            file_orders_skipped += 1
                            continue
                            
                        order_type = str(order.get('order_type', '')).upper()
                        
                        # Calculate digits for rounding based on tick_size
                        if tick_size_value < 1:
                            digits = len(str(tick_size_value).split('.')[-1])
                        else:
                            digits = 0
                        
                        # Standard calculation based on exit or target
                        sl_price = float(order.get('exit', 0))
                        tp_price = float(order.get('target', 0))
                        
                        # Case 1: Target provided, need to calculate exit
                        if sl_price == 0 and tp_price > 0:
                            risk_dist = abs(tp_price - entry) / rr_ratio
                            if "BUY" in order_type:
                                order['exit'] = round(entry - risk_dist, digits)
                            elif "SELL" in order_type:
                                order['exit'] = round(entry + risk_dist, digits)
                            else:
                                file_orders_skipped += 1
                                continue
                            
                            file_orders_calculated += 1
                            any_orders_calculated = True
                        
                        # Case 2: Exit provided, need to calculate target
                        elif sl_price > 0:
                            risk_dist = abs(entry - sl_price)
                            if "BUY" in order_type:
                                order['target'] = round(entry + (risk_dist * rr_ratio), digits)
                            elif "SELL" in order_type:
                                order['target'] = round(entry - (risk_dist * rr_ratio), digits)
                            else:
                                file_orders_skipped += 1
                                continue
                            
                            file_orders_calculated += 1
                            any_orders_calculated = True
                            print(f"      ✅ [{strategy_name}] {order.get('symbol')} - Target calculated: {order['target']} (R:R={rr_ratio})")
                        
                        # Case 3: Neither exit nor target provided, skip
                        else:
                            file_orders_skipped += 1
                            continue
                        
                        # --- METADATA UPDATES with Strategy Info ---
                        order['risk_reward'] = rr_ratio
                        order['risk_reward_source'] = 'strategy_specific' if strategy_name in strategies_rr else 'default'
                        order['strategy_name'] = strategy_name
                        order['status'] = "Calculated"
                        order['calculated_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        orders_updated = True
                        
                    except (ValueError, KeyError, TypeError, ZeroDivisionError) as e:
                        file_orders_skipped += 1
                        print(f"      ⚠️  Error processing order {order.get('symbol', 'Unknown')}: {e}")
                        continue
                
                # Save the updated orders back to the same file
                if orders_updated:
                    try:
                        with open(file_path, 'w', encoding='utf-8') as f:
                            json.dump(orders, f, indent=4)
                        
                        investor_files_updated += 1
                        total_files_updated += 1
                        
                        # Update counters
                        investor_orders_calculated += file_orders_calculated
                        investor_orders_skipped += file_orders_skipped
                        
                        print(f"    └─ 📁 {strategy_name}/{file_path.parent.name}/limit_orders.json: "
                              f"Processed: {original_count}, Calculated: {file_orders_calculated}, "
                              f"Skipped: {file_orders_skipped} [R:R={rr_ratio}]")
                        
                    except Exception as e:
                        print(f"    └─ ❌ Failed to save {file_path}: {e}")
                
            except Exception as e:
                print(f"    └─ ❌ Error reading {file_path}: {e}")
                continue
        
        # Summary for current investor
        if investor_orders_processed > 0:
            total_orders_processed += investor_orders_processed
            total_orders_calculated += investor_orders_calculated
            total_orders_skipped += investor_orders_skipped
            
            print(f"\n  └─ ✨ Investor {current_inv_id} Summary:")
            print(f"      Files updated: {investor_files_updated}")
            print(f"      Orders processed: {investor_orders_processed}")
            print(f"      Orders calculated: {investor_orders_calculated}")
            print(f"      Orders skipped: {investor_orders_skipped}")
            
            if investor_orders_processed > 0:
                calc_rate = (investor_orders_calculated / investor_orders_processed) * 100
                print(f"      Calculation rate: {calc_rate:.1f}%")
        else:
            print(f"  └─ ⚠️  No orders processed for {current_inv_id}")

    # Final Global Summary with Strategy Breakdown
    print(f"\n{'='*10} INVESTOR CALCULATION COMPLETE {'='*10}")
    if total_orders_processed > 0:
        print(f" Total Files Modified:    {total_files_updated}")
        print(f" Total Orders Processed:  {total_orders_processed}")
        print(f" Total Orders Calculated: {total_orders_calculated}")
        print(f" Total Orders Skipped:    {total_orders_skipped}")
        print(f" Symbols Normalized:      {total_symbols_normalized}")
        
        if total_orders_processed > 0:
            overall_rate = (total_orders_calculated / total_orders_processed) * 100
            print(f" Overall Calculation Rate: {overall_rate:.1f}%")
        
        # Show strategy R:R usage breakdown
        if strategies_used:
            print(f"\n {'='*10} STRATEGY R:R USAGE {'='*10}")
            for strategy, info in strategies_used.items():
                source_indicator = "🎯" if info['source'] == 'specific' else "📋"
                print(f" {source_indicator} {strategy}: R:R={info['rr_ratio']} ({info['source']})")
    else:
        print(" No orders were processed.")
    
    return any_orders_calculated

def padding_tight_usd_risk(inv_id=None):
    """
    Ranks orders, adjusts 'too tight' risk to 50% of the next order in line,
    and saves results back to the original limit_orders.json.
    """
    print(f"\n{'='*10} ⚖️ DYNAMIC RISK RANKING & SPACING {'='*10}")
    
    inv_base_path = Path(INV_PATH) 
    if not inv_base_path.exists(): 
        return False

    investor_folders = [inv_base_path / inv_id] if inv_id and (inv_base_path / inv_id).exists() else [f for f in inv_base_path.iterdir() if f.is_dir()]

    for inv_folder in investor_folders:
        current_inv_id = inv_folder.name
        # Target the standard limit_orders.json files
        order_files = list(inv_folder.rglob("*/pending_orders/limit_orders.json"))
        
        for file_path in order_files:
            try:
                # 1. Load the original file
                with open(file_path, 'r', encoding='utf-8') as f:
                    orders = json.load(f)
                if not orders: 
                    continue

                # 2. Group by timeframe and extract agnostic broker data
                timeframe_groups = {}
                for order in orders:
                    tf = order.get("timeframe", "Unknown")
                    if tf not in timeframe_groups: 
                        timeframe_groups[tf] = []
                    
                    # Agnostic extraction (suffix-based)
                    vol = next((v for k, v in order.items() if k.endswith("_volume")), 0)
                    t_size = next((v for k, v in order.items() if k.endswith("_tick_size")), 0)
                    t_val = next((v for k, v in order.items() if k.endswith("_tick_value")), 0)
                    entry = order.get("entry", 0)
                    exit_p = order.get("exit", 0)

                    # Initial risk calc
                    if vol > 0 and t_size > 0 and entry > 0 and exit_p > 0:
                        ticks = abs(entry - exit_p) / t_size
                        order["live_risk_usd"] = round(vol * ticks * t_val, 2)
                    else:
                        order["live_risk_usd"] = 0.0
                    
                    timeframe_groups[tf].append(order)

                rank_words = ["first", "second", "third", "fourth", "fifth"]
                updated_orders_list = []

                # 3. Process each group for the 50% spacing rule
                for tf, group in timeframe_groups.items():
                    # Sort by risk lowest -> highest
                    group.sort(key=lambda x: x.get("live_risk_usd", 0))
                    
                    for i in range(len(group)):
                        current = group[i]
                        
                        # Apply spacing if there's a higher risk order next in line
                        if i + 1 < len(group):
                            next_order = group[i+1]
                            curr_risk = current.get("live_risk_usd", 0)
                            next_risk = next_order.get("live_risk_usd", 0)
                            
                            threshold = round(next_risk / 2, 2)
                            
                            if curr_risk < threshold and threshold > 0:
                                vol = next((v for k, v in current.items() if k.endswith("_volume")), 0)
                                t_size = next((v for k, v in current.items() if k.endswith("_tick_size")), 0)
                                t_val = next((v for k, v in current.items() if k.endswith("_tick_value")), 0)
                                entry = current.get("entry")
                                
                                if vol > 0 and t_val > 0:
                                    new_dist = (threshold * t_size) / (vol * t_val)
                                    if "buy" in current.get("order_type", "").lower():
                                        current["exit"] = round(entry - new_dist, 5)
                                    else:
                                        current["exit"] = round(entry + new_dist, 5)
                                    
                                    current["live_risk_usd"] = threshold
                                    current["adjustment_note"] = f"Spaced to 50% of rank {i+2} (${threshold})"

                        # Remove old rank flags
                        for k in list(current.keys()):
                            if "_usd_risk" in k and any(w in k for w in rank_words):
                                del current[k]

                        # Apply current ranking flag (only for True values as requested)
                        if i < len(rank_words):
                            flag_name = f"{rank_words[i]}_lowest_{tf}_usd_risk"
                            current[flag_name] = True
                        
                        current["risk_calculated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        updated_orders_list.append(current)

                # 4. Save back to original limit_orders.json
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(updated_orders_list, f, indent=4)
                
                # 5. Cleanup: Remove the order_risks.json file if it exists
                legacy_risks_file = file_path.parent / "order_risks.json"
                if legacy_risks_file.exists():
                    os.remove(legacy_risks_file)
                
                print(f"  └─ [{current_inv_id}] Updated {file_path.name} and cleaned legacy files.")

            except Exception as e:
                print(f"  └─ ❌ Error processing {file_path}: {e}")

    return True

def live_usd_risk_and_scaling(inv_id=None, callback_function=None):
    """
    Calculates and populates the live USD risk for all orders in pending_orders/limit_orders.json files.
    Deduplicates orders first, scales volume, and SPLITS orders if they exceed max volume.
    """
    print(f"\n{'='*10} 💰 CALCULATING LIVE USD RISK WITH DEDUPLICATION & SPLITTING {'='*10}")
    
    total_files_updated = 0
    total_orders_updated = 0
    total_risk_usd = 0.0
    total_signals_created = 0
    total_symbols_normalized = 0
    inv_base_path = Path(INV_PATH)

    if not inv_base_path.exists():
        print(f" [!] Error: Investor path {INV_PATH} does not exist.")
        return False

    if inv_id:
        inv_folder = inv_base_path / inv_id
        investor_folders = [inv_folder] if inv_folder.exists() else []
        if not investor_folders:
            print(f" [!] Error: Investor folder {inv_id} does not exist.")
            return False
    else:
        investor_folders = [f for f in inv_base_path.iterdir() if f.is_dir()]
    
    if not investor_folders:
        print(" └─ 🔘 No investor directories found.")
        return False

    any_orders_processed = False

    for inv_folder in investor_folders:
        current_inv_id = inv_folder.name
        print(f"\n [{current_inv_id}] 🔍 Initializing pre-process cleanup and risk scaling...")

        resolution_cache = {}

        # 1. Load account management data
        account_mgmt_path = inv_folder / "accountmanagement.json"
        risk_ranges = {}
        account_balance = None
        
        if account_mgmt_path.exists():
            try:
                with open(account_mgmt_path, 'r', encoding='utf-8') as f:
                    account_data = json.load(f)
                risk_ranges = account_data.get('account_balance_default_risk_management', {})
                print(f"  └─ 📊 Loaded risk management ranges: {len(risk_ranges)} ranges")
            except Exception as e:
                print(f"  └─ ⚠️  Could not load accountmanagement.json: {e}")
        else:
            print(f"  └─ ⚠️  No accountmanagement.json found, skipping risk-based scaling")
            continue

        broker_cfg = usersdictionary.get(current_inv_id)
        if not broker_cfg:
            print(f"  └─ ❌ No broker config found for {current_inv_id}")
            continue
        
        account_info = mt5.account_info()
        if account_info:
            account_balance = account_info.balance
            print(f"  └─ 💵 Live account balance: ${account_balance:,.2f}")
        else:
            print(f"  └─ ⚠️  Could not fetch account balance from broker")
            continue
        
        required_risk = 0
        tolerance_min = 0
        tolerance_max = 0
        
        for range_str, risk_value in risk_ranges.items():
            try:
                if '_risk' in range_str:
                    range_part = range_str.replace('_risk', '')
                    if '-' in range_part:
                        min_val, max_val = map(float, range_part.split('-'))
                        if min_val <= account_balance <= max_val:
                            required_risk = float(risk_value)
                            tolerance_min = required_risk
                            tolerance_max = required_risk + 0.99
                            print(f"  └─ 🎯 Balance ${account_balance:,.2f} falls in range {range_part}")
                            print(f"  └─ 🎯 Required risk: ${required_risk:.2f} (tolerance: ${tolerance_min:.2f} - ${tolerance_max:.2f})")
                            break
            except Exception as e:
                continue
        
        if required_risk == 0:
            print(f"  └─ ⚠️  No matching risk range found for balance ${account_balance:,.2f}")
            continue
        
        order_files = list(inv_folder.rglob("*/pending_orders/limit_orders.json"))
        
        if not order_files:
            print(f"  └─ 🔘 No limit order files found")
            continue
            
        investor_files_updated = 0
        investor_orders_updated = 0
        investor_risk_usd = 0.0
        investor_signals_count = 0
        
        broker_prefix = broker_cfg.get('BROKER_NAME', '').lower()
        if not broker_prefix:
            server = broker_cfg.get('SERVER', '')
            broker_prefix = server.split('-')[0].split('.')[0].lower() if server else 'broker'
        
        print(f"  └─ 🏷️  Using broker prefix: '{broker_prefix}' for field names")
        
        for file_path in order_files:
            try:
                # --- PRE-PROCESS DEDUPLICATION ---
                with open(file_path, 'r', encoding='utf-8') as f:
                    raw_orders = json.load(f)
                
                if not raw_orders:
                    continue

                # Deduplicate based on symbol, entry, and exit
                unique_orders = []
                seen_keys = set()
                for o in raw_orders:
                    key = (o.get('symbol'), o.get('entry'), o.get('exit'))
                    if key not in seen_keys:
                        unique_orders.append(o)
                        seen_keys.add(key)
                
                if len(unique_orders) < len(raw_orders):
                    print(f"    └─ 🧹 Cleaned {len(raw_orders) - len(unique_orders)} duplicate orders from {file_path.name}")
                
                orders = unique_orders

                # Clear signals.json for this specific folder to prevent stale data mixing with splits
                signals_path = file_path.parent / "signals.json"
                if signals_path.exists():
                    with open(signals_path, 'w', encoding='utf-8') as f:
                        json.dump([], f)
                    print(f"    └─ 🚿 Cleared existing signals.json for fresh split generation")

                # --- START PROCESSING ---
                if callback_function:
                    try:
                        callback_function(current_inv_id, file_path, orders)
                    except Exception as e:
                        print(f"    └─ ⚠️  Callback error: {e}")
                
                orders_modified = False
                file_risk_total = 0.0
                file_signals = []
                
                for order in orders:
                    raw_symbol = order.get("symbol", "")
                    if not raw_symbol:
                        continue
                    
                    if raw_symbol in resolution_cache:
                        normalized_symbol = resolution_cache[raw_symbol]
                    else:
                        normalized_symbol = get_normalized_symbol(raw_symbol)
                        resolution_cache[raw_symbol] = normalized_symbol
                        if normalized_symbol != raw_symbol:
                            print(f"    └─ ✅ {raw_symbol} -> {normalized_symbol} (Mapped & Cached)")
                            total_symbols_normalized += 1
                    
                    symbol = normalized_symbol if normalized_symbol else raw_symbol
                    order['symbol'] = symbol
                    
                    volume_field = f"{broker_prefix}_volume"
                    tick_size_field = f"{broker_prefix}_tick_size"
                    tick_value_field = f"{broker_prefix}_tick_value"
                    
                    current_volume = order.get(volume_field)
                    tick_size = order.get(tick_size_field)
                    tick_value = order.get(tick_value_field)
                    
                    if None in (current_volume, tick_size, tick_value):
                        print(f"    └─ ⚠️  Missing broker fields for {symbol}, skipping")
                        continue
                    
                    symbol_info = mt5.symbol_info(symbol)
                    if not symbol_info:
                        print(f"    └─ ⚠️  Could not fetch current price for {symbol}, skipping")
                        continue
                    
                    entry_price = order.get("entry")
                    exit_price = order.get("exit")
                    
                    if not entry_price or not exit_price:
                        continue
                    
                    stop_distance_pips = abs(entry_price - exit_price)
                    ticks_in_stop = stop_distance_pips / tick_size if tick_size > 0 else 0
                    
                    volume_step = symbol_info.volume_step
                    min_volume = symbol_info.volume_min
                    max_volume = symbol_info.volume_max
                    
                    best_volume = current_volume
                    best_risk = 0
                    test_volume = current_volume if current_volume >= min_volume else min_volume
                    test_risk = test_volume * ticks_in_stop * tick_value
                    
                    print(f"    └─ 📈 {symbol}: Starting volume {test_volume} -> risk ${test_risk:.2f}")
                    
                    if test_risk > tolerance_max:
                        print(f"      └─ ⬇️  Risk too high (${test_risk:.2f} > ${tolerance_max:.2f}), scaling down...")
                        while test_risk > tolerance_max and test_volume > min_volume:
                            test_volume = max(min_volume, test_volume - volume_step)
                            test_risk = test_volume * ticks_in_stop * tick_value
                        best_volume = test_volume
                        best_risk = test_risk
                    
                    elif test_risk < tolerance_min:
                        print(f"      └─ ⬆️  Risk too low (${test_risk:.2f} < ${tolerance_min:.2f}), scaling up...")
                        while test_risk < tolerance_min:
                            previous_volume = test_volume
                            previous_risk = test_risk
                            test_volume = test_volume + volume_step
                            test_risk = test_volume * ticks_in_stop * tick_value
                            
                            if test_risk > tolerance_max:
                                best_volume = previous_volume
                                best_risk = previous_risk
                                print(f"      └─ ✅ Using volume: {best_volume:.3f} (risk ${best_risk:.2f}) to avoid overshoot")
                                break
                        else:
                            best_volume = test_volume
                            best_risk = test_risk
                    else:
                        best_volume = test_volume
                        best_risk = test_risk
                        print(f"      └─ ✅ Already within tolerance: volume {best_volume:.3f} (risk ${best_risk:.2f})")

                    order[volume_field] = round(best_volume, 2)
                    order["risk_in_usd"] = round(best_risk, 2)
                    order["risk_calculated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    order["required_risk_target"] = required_risk
                    order["risk_tolerance_min"] = round(tolerance_min, 2)
                    order["risk_tolerance_max"] = round(tolerance_max, 2)
                    order["account_balance_at_calc"] = round(account_balance, 2)
                    order["current_bid"] = round(symbol_info.bid, 6) if hasattr(symbol_info, 'bid') else None
                    order["current_ask"] = round(symbol_info.ask, 6) if hasattr(symbol_info, 'ask') else None
                    
                    orders_modified = True
                    investor_orders_updated += 1
                    total_orders_updated += 1
                    file_risk_total += best_risk
                    
                    # --- SPLITTING LOGIC ---
                    if best_risk >= tolerance_min * 0.5 and best_risk > 0:
                        remaining_volume = best_volume
                        is_split = best_volume > max_volume
                        
                        while remaining_volume > 0.0001:
                            chunk_volume = min(remaining_volume, max_volume)
                            if chunk_volume < min_volume and remaining_volume != best_volume:
                                break
                                
                            signal_order = order.copy()
                            signal_order[volume_field] = round(chunk_volume, 2)
                            signal_order["split_order"] = is_split
                            signal_order["moved_to_signals_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            
                            file_signals.append(signal_order)
                            investor_signals_count += 1
                            total_signals_created += 1
                            remaining_volume -= chunk_volume

                        if is_split:
                            print(f"      └─ 🟢 Qualified & SPLIT (Total Vol: {best_volume:.2f}, Max Vol: {max_volume})")
                        else:
                            print(f"      └─ 🟢 Qualified for signals.json (risk ${best_risk:.2f})")
                
                # Save cleaned and updated limit orders
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(orders, f, indent=4)
                
                investor_files_updated += 1
                total_files_updated += 1
                investor_risk_usd += file_risk_total
                total_risk_usd += file_risk_total
                any_orders_processed = True
                
                if file_signals:
                    try:
                        # We already cleared signals.json at the start, so we just write the new ones
                        with open(signals_path, 'w', encoding='utf-8') as f:
                            json.dump(file_signals, f, indent=4)
                        
                        print(f"  └─ 📊 signals.json: Created {len(file_signals)} clean signals (splits included)")
                    except Exception as e:
                        print(f"  └─ ❌ Error writing signals.json: {e}")
                
            except Exception as e:
                print(f"  └─ ❌ Error processing {file_path}: {e}")
                continue
        
        # Summary for current investor
        if investor_orders_updated > 0:
            print(f"\n  └─ {'='*40}")
            print(f"  └─ ✨ Investor {current_inv_id} Summary:")
            print(f"  └─     Files Processed:    {investor_files_updated}")
            print(f"  └─     Orders Risk-Scaled: {investor_orders_updated}")
            print(f"  └─     Total Risk:         ${investor_risk_usd:,.2f}")
            print(f"  └─     Signals Generated:  {investor_signals_count}")
            print(f"  └─ {'='*40}")

    print(f"\n{'='*10} USD RISK CALCULATION COMPLETE {'='*10}")
    return any_orders_processed

def apply_default_prices(inv_id=None, callback_function=None):
    """
    Applies default prices from limit_orders_backup.json to signals.json when default_price is true.
    Copies exit/target prices from backup to matching orders in signals.json, handling symbol normalization.
    
    Args:
        inv_id (str, optional): Specific investor ID to process. If None, processes all investors.
        callback_function (callable, optional): A function to call with the opened file data.
            The callback will receive (inv_id, backup_file_path, signals_file_path, modifications) parameters.
    
    Returns:
        bool: True if any orders were modified, False otherwise
    """
    print(f"\n{'='*10} 💰 APPLYING DEFAULT PRICES FROM BACKUP {'='*10}")
    
    total_orders_modified = 0
    total_files_updated = 0
    total_symbols_normalized = 0
    inv_base_path = Path(INV_PATH)

    if not inv_base_path.exists():
        print(f" [!] Error: Investor path {INV_PATH} does not exist.")
        return False

    # Determine which investors to process
    if inv_id:
        inv_folder = inv_base_path / inv_id
        investor_folders = [inv_folder] if inv_folder.exists() else []
        if not investor_folders:
            print(f" [!] Error: Investor folder {inv_id} does not exist.")
            return False
    else:
        investor_folders = [f for f in inv_base_path.iterdir() if f.is_dir()]
    
    if not investor_folders:
        print(" └─ 🔘 No investor directories found.")
        return False

    any_orders_modified = False

    for inv_folder in investor_folders:
        current_inv_id = inv_folder.name
        print(f"\n [{current_inv_id}] 🔍 Checking default price setting...")

        # --- INVESTOR LOCAL CACHE for symbol normalization ---
        resolution_cache = {}

        # 1. Load accountmanagement.json to check default_price setting
        account_mgmt_path = inv_folder / "accountmanagement.json"
        if not account_mgmt_path.exists():
            print(f"  └─ ⚠️  accountmanagement.json not found, skipping")
            continue

        try:
            with open(account_mgmt_path, 'r', encoding='utf-8') as f:
                account_data = json.load(f)
            
            settings = account_data.get('settings', {})
            default_price_enabled = settings.get('default_price', False)
            
            if not default_price_enabled:
                print(f"  └─ ⏭️  default_price is FALSE - skipping investor (set to true to apply default prices)")
                continue
                
            print(f"  └─ ✅ default_price is TRUE - will apply prices from backup")
            
        except Exception as e:
            print(f"  └─ ❌ Error reading accountmanagement.json: {e}")
            continue

        # 2. Load broker config for symbol handling
        broker_cfg = usersdictionary.get(current_inv_id)
        if not broker_cfg:
            print(f"  └─ ❌ No broker config found for {current_inv_id}")
            continue

        # 3. Find all limit_orders_backup.json files
        backup_files = list(inv_folder.rglob("*/pending_orders/limit_orders_backup.json"))
        
        if not backup_files:
            print(f"  └─ 🔘 No limit_orders_backup.json files found")
            continue
        
        print(f"  └─ 📁 Found {len(backup_files)} backup files to process")

        investor_orders_modified = 0
        investor_files_updated = 0
        investor_symbols_normalized = 0

        # 4. Process each backup file
        for backup_path in backup_files:
            folder_path = backup_path.parent.parent  # Gets the strategy folder (e.g., double-levels)
            signals_path = backup_path.parent / "signals.json"  # Same directory as backup
            
            # Check if signals.json exists
            if not signals_path.exists():
                print(f"  └─ ⚠️  No signals.json found in {backup_path.parent} (same folder as backup), skipping")
                continue
            
            print(f"\n  └─ 📂 Processing folder: {folder_path.name}")
            print(f"      ├─ Backup: {backup_path.name}")
            print(f"      └─ Signals: {signals_path.name}")
            
            try:
                # Load backup orders
                with open(backup_path, 'r', encoding='utf-8') as f:
                    backup_orders = json.load(f)
                
                # Load signals
                with open(signals_path, 'r', encoding='utf-8') as f:
                    signals = json.load(f)
                
                if not backup_orders:
                    print(f"    └─ ⚠️  Empty backup file")
                    continue
                    
                if not signals:
                    print(f"    └─ ⚠️  Empty signals file")
                    continue
                
                # Create lookup dictionaries for backup orders with multiple matching strategies
                backup_lookup = {}  # (symbol, timeframe, order_type) -> order
                
                print(f"    └─ 📊 Processing {len(backup_orders)} backup orders and {len(signals)} signals")
                
                # First, let's analyze what's in the backup for AUDCAD 15m sell_limit
                audcad_backups = []
                for order in backup_orders:
                    # --- SYMBOL NORMALIZATION for backup symbols ---
                    raw_symbol = str(order.get('symbol', '')).upper()
                    if not raw_symbol:
                        continue
                    
                    # Check Cache First for backup symbol
                    if raw_symbol in resolution_cache:
                        normalized_symbol = resolution_cache[raw_symbol]
                    else:
                        # Perform mapping only once
                        normalized_symbol = get_normalized_symbol(raw_symbol)
                        resolution_cache[raw_symbol] = normalized_symbol
                        
                        # Log normalization on first discovery
                        if normalized_symbol != raw_symbol:
                            print(f"      └─ ✅ Backup: {raw_symbol} -> {normalized_symbol} (Mapped & Cached)")
                            investor_symbols_normalized += 1
                            total_symbols_normalized += 1
                    
                    # Use normalized symbol for lookup
                    symbol = normalized_symbol if normalized_symbol else raw_symbol
                    timeframe = str(order.get('timeframe', '')).upper()
                    order_type = str(order.get('order_type', '')).lower()
                    
                    if symbol == 'AUDCAD' and timeframe == '15M' and order_type == 'sell_limit':
                        audcad_backups.append(order)
                        print(f"      └─ 📌 Found AUDCAD 15M sell_limit in backup with exit: {order.get('exit')}")
                    
                    if symbol and timeframe and order_type:
                        # Store with normalized symbol
                        key = (symbol, timeframe, order_type)
                        backup_lookup[key] = order
                
                print(f"    └─ 📊 Created lookup for {len(backup_lookup)} backup orders")
                
                # Process signals and apply default prices
                modified = False
                signals_modified_count = 0
                modifications_log = []
                
                for signal in signals:
                    # --- SYMBOL NORMALIZATION for signal symbols ---
                    raw_signal_symbol = str(signal.get('symbol', '')).upper()
                    if not raw_signal_symbol:
                        continue
                    
                    # Check Cache First for signal symbol
                    if raw_signal_symbol in resolution_cache:
                        signal_symbol = resolution_cache[raw_signal_symbol]
                    else:
                        # Perform mapping only once
                        signal_symbol = get_normalized_symbol(raw_signal_symbol)
                        resolution_cache[raw_signal_symbol] = signal_symbol
                        
                        # Log normalization on first discovery
                        if signal_symbol != raw_signal_symbol:
                            print(f"      └─ ✅ Signal: {raw_signal_symbol} -> {signal_symbol} (Mapped & Cached)")
                            investor_symbols_normalized += 1
                            total_symbols_normalized += 1
                    
                    signal_timeframe = str(signal.get('timeframe', '')).upper()
                    signal_type = str(signal.get('order_type', '')).lower()
                    
                    if not all([signal_symbol, signal_timeframe, signal_type]):
                        print(f"      └─ ⚠️  Signal missing required fields: {signal}")
                        continue
                    
                    # Special debug for AUDCAD+ 15M (now normalized to AUDCAD)
                    if raw_signal_symbol == 'AUDCAD+' and signal_timeframe == '15M' and signal_type == 'sell_limit':
                        print(f"      └─ 🔍 DEBUG: Processing AUDCAD+ 15M sell_limit signal (normalized to {signal_symbol})")
                        print(f"          Current exit: {signal.get('exit')}, target: {signal.get('target')}")
                    
                    # Try to find matching backup order
                    matched_backup = None
                    match_method = None
                    
                    # Method 1: Direct symbol match with normalized symbols
                    backup_key = (signal_symbol, signal_timeframe, signal_type)
                    if backup_key in backup_lookup:
                        matched_backup = backup_lookup[backup_key]
                        match_method = "direct match"
                        if raw_signal_symbol == 'AUDCAD+':
                            print(f"      └─ ✓ Found direct match for normalized AUDCAD")
                    
                    if matched_backup:
                        # Check if we need to update any prices
                        updates_made = False
                        
                        # Get backup values
                        backup_exit = matched_backup.get('exit', 0)
                        backup_target = matched_backup.get('target', 0)
                        
                        # Current signal values
                        current_exit = signal.get('exit', 0)
                        current_target = signal.get('target', 0)
                        
                        update_details = []
                        
                        # Apply backup exit if not zero and different from current
                        if backup_exit != 0 and backup_exit != current_exit:
                            signal['exit'] = backup_exit
                            updates_made = True
                            update_details.append(f"exit: {current_exit} -> {backup_exit}")
                        
                        # Apply backup target if not zero and different from current
                        if backup_target != 0 and backup_target != current_target:
                            signal['target'] = backup_target
                            updates_made = True
                            update_details.append(f"target: {current_target} -> {backup_target}")
                        
                        if updates_made:
                            # Add metadata about the update
                            signal['price_updated_from_backup'] = True
                            signal['price_updated_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            signal['backup_match_method'] = match_method
                            signal['original_symbol'] = raw_signal_symbol
                            
                            signals_modified_count += 1
                            investor_orders_modified += 1
                            total_orders_modified += 1
                            any_orders_modified = True
                            modified = True
                            
                            modifications_log.append({
                                'symbol': raw_signal_symbol,
                                'normalized_symbol': signal_symbol,
                                'timeframe': signal_timeframe,
                                'type': signal_type,
                                'updates': {
                                    'exit': backup_exit if backup_exit != 0 else None,
                                    'target': backup_target if backup_target != 0 else None
                                },
                                'match_method': match_method,
                                'update_details': ', '.join(update_details)
                            })
                            
                            print(f"      └─ 🔄 [{raw_signal_symbol} -> {signal_symbol}] {', '.join(update_details)} [{match_method}]")
                        else:
                            if raw_signal_symbol == 'AUDCAD+':
                                print(f"      └─ ✓ AUDCAD+ already has correct prices (exit={current_exit}, target={current_target})")
                    else:
                        # Debug: Show unmatched signals with more detail
                        if raw_signal_symbol == 'AUDCAD+':
                            print(f"      └─ ❌ FAILED to find match for AUDCAD+ 15M sell_limit (normalized to {signal_symbol})")
                            print(f"          Looking for backup_key: ({signal_symbol}, {signal_timeframe}, {signal_type})")
                            
                            # Show all available backup keys
                            print(f"          Available backup keys:")
                            for (bsym, btf, btype) in list(backup_lookup.keys())[:10]:
                                if btf == signal_timeframe and btype == signal_type:
                                    print(f"            • ({bsym}, {btf}, {btype})")
                        else:
                            print(f"      └─ ⚠️  No backup match for: {raw_signal_symbol} -> {signal_symbol} ({signal_timeframe}, {signal_type})")
                
                # Save modified signals file
                if modified:
                    try:
                        with open(signals_path, 'w', encoding='utf-8') as f:
                            json.dump(signals, f, indent=4)
                        
                        investor_files_updated += 1
                        total_files_updated += 1
                        
                        print(f"    └─ 📝 Updated {signals_modified_count} orders in signals.json")
                        
                        # Call callback if provided
                        if callback_function:
                            try:
                                callback_function(current_inv_id, backup_path, signals_path, modifications_log)
                            except Exception as e:
                                print(f"    └─ ⚠️  Callback error: {e}")
                        
                        # Show summary of modifications
                        if modifications_log:
                            print(f"    └─ 📋 Modification Summary:")
                            for mod in modifications_log[:5]:  # Show first 5
                                norm_info = f" -> {mod['normalized_symbol']}" if mod['symbol'] != mod['normalized_symbol'] else ""
                                print(f"      • {mod['symbol']}{norm_info} ({mod['timeframe']}): {mod['update_details']} [{mod['match_method']}]")
                            if len(modifications_log) > 5:
                                print(f"      • ... and {len(modifications_log) - 5} more")
                    
                    except Exception as e:
                        print(f"    └─ ❌ Error saving signals.json: {e}")
                else:
                    print(f"    └─ ✓ No price updates needed for signals in {folder_path.name}")
                
            except Exception as e:
                print(f"  └─ ❌ Error processing {backup_path}: {e}")
                continue

        # Investor summary
        if investor_orders_modified > 0:
            print(f"\n  └─ {'='*40}")
            print(f"  └─ ✨ Investor {current_inv_id} Summary:")
            print(f"  └─    Folders Processed:   {len(backup_files)}")
            print(f"  └─    Signals Files Updated: {investor_files_updated}")
            print(f"  └─    Orders Modified:     {investor_orders_modified}")
            if investor_symbols_normalized > 0:
                print(f"  └─    Symbols Normalized:   {investor_symbols_normalized}")
            print(f"  └─ {'='*40}")
        else:
            print(f"\n  └─ ⚠️  No modifications made for {current_inv_id}")

    # Final Global Summary
    print(f"\n{'='*10} DEFAULT PRICE APPLICATION COMPLETE {'='*10}")
    if total_orders_modified > 0:
        print(f" Total Files Updated:       {total_files_updated}")
        print(f" Total Orders Modified:     {total_orders_modified}")
        if total_symbols_normalized > 0:
            print(f" Total Symbols Normalized:  {total_symbols_normalized}")
        print(f"\n ✓ Default prices successfully applied from backup files")
    else:
        print(" No orders were modified.")
        print(" └─ Possible reasons:")
        print("    • default_price is false in accountmanagement.json")
        print("    • No matching orders found between backup and signals")
        print("    • All exit/target prices already match backup values")
        print("    • No limit_orders_backup.json files found")
    
    return any_orders_modified

def place_usd_orders(inv_id=None):
    """
    Places pending orders from signals.json files for investors.
    Performs a global existence check at the start to filter out duplicates.
    Syncs tradeshistory.json with actual MT5 terminal status (Pending vs Closed).
    """
    
    # --- SUB-FUNCTION 1: CHECK AUTHORIZATION STATUS ---
    def check_authorization_status(pending_folder):
        """Check activities.json for unauthorized actions and bypass status"""
        activities_path = pending_folder / "activities.json"
        if not activities_path.exists():
            print(f"    ✅ No activities.json found - proceeding with order placement")
            return True, None
        
        try:
            with open(activities_path, 'r', encoding='utf-8') as f:
                activities = json.load(f)
            unauthorized_detected = activities.get('unauthorized_action_detected', False)
            bypass_active = activities.get('bypass_restriction', False)
            autotrading_active = activities.get('activate_autotrading', False)
            
            if unauthorized_detected:
                if bypass_active and autotrading_active:
                    print(f"    ✅ Unauthorized actions detected but BYPASS ACTIVE - proceeding with order placement")
                    return True, activities
                else:
                    print(f"  Unauthorized actions detected")
                    if not bypass_active: print(f"       - you have been restricted")
                    if not autotrading_active: print(f"       - AutoTrading is FALSE")
                    return False, activities
            print(f"    ✅ No unauthorized actions detected - proceeding with order placement")
            return True, activities
        except Exception as e:
            print(f"    ⚠️  Error reading activities.json: {e}")
            return True, None

    # --- SUB-FUNCTION 2: CANCEL AUTHORIZED ORDERS AND POSITIONS ---
    def cancel_authorized_orders_and_positions(inv_root, pending_folder):
        """Cancel ONLY authorized pending orders and close authorized positions"""
        print(f"\n  🚫 RESTRICTION ACTIVE - Cancelling authorized orders and positions...")
        try:
            history_path = pending_folder / "tradeshistory.json"
            authorized_tickets = set()
            authorized_magics = set()
            
            if history_path.exists():
                with open(history_path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                    for trade in history:
                        if trade.get('ticket'): authorized_tickets.add(int(trade['ticket']))
                        if trade.get('magic'): authorized_magics.add(int(trade['magic']))
            
            if not authorized_tickets and not authorized_magics:
                print(f"  ℹ️  No authorized trades found in tradeshistory.json")
                return
            
            pending_orders = mt5.orders_get() or []
            orders_cancelled = 0
            for order in pending_orders:
                if order.ticket in authorized_tickets or order.magic in authorized_magics:
                    request = {"action": mt5.TRADE_ACTION_REMOVE, "order": order.ticket}
                    result = mt5.order_send(request)
                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        print(f"      ✅ Cancelled authorized pending order: {order.ticket} ({order.symbol})")
                        orders_cancelled += 1

            positions = mt5.positions_get() or []
            positions_closed = 0
            for position in positions:
                if position.ticket in authorized_tickets or position.magic in authorized_magics:
                    close_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
                    tick = mt5.symbol_info_tick(position.symbol)
                    if not tick: continue
                    price = tick.ask if close_type == mt5.ORDER_TYPE_BUY else tick.bid
                    request = {
                        "action": mt5.TRADE_ACTION_DEAL, "symbol": position.symbol, "volume": position.volume,
                        "type": close_type, "position": position.ticket, "price": price, "deviation": 20,
                        "magic": position.magic, "comment": "Closed by restriction"
                    }
                    result = mt5.order_send(request)
                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        print(f"      ✅ Closed authorized position: {position.ticket} ({position.symbol})")
                        positions_closed += 1
            
            print(f"  ✅ Cleanup complete: {orders_cancelled} cancelled, {positions_closed} closed")
        except Exception as e:
            print(f"  ❌ Error during cleanup: {e}")

    # --- SUB-FUNCTION 3: COLLECT ORDERS FROM SIGNALS ---
    def collect_orders_from_signals(inv_root, resolution_cache):
        """Collect all orders from signals.json files in investor root"""
        signals_files = list(inv_root.rglob("*/pending_orders/signals.json"))
        entries_with_paths = [] 
        for signals_path in signals_files:
            try:
                with open(signals_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for entry in data:
                    raw_symbol = entry.get("symbol", "")
                    if raw_symbol in resolution_cache: 
                        normalized_symbol = resolution_cache[raw_symbol]
                    else:
                        normalized_symbol = get_normalized_symbol(raw_symbol)
                        resolution_cache[raw_symbol] = normalized_symbol
                    entry['symbol'] = normalized_symbol
                    entries_with_paths.append({'data': entry, 'path': signals_path})
            except Exception as e:
                print(f"      ⚠️  Error reading signals file {signals_path}: {e}")
                continue
        return entries_with_paths

    # --- SUB-FUNCTION 4: SYNC & SAVE HISTORY (UPDATED) ---
    def sync_and_save_history(signals_path, new_trade=None):
        """
        Synchronizes tradeshistory.json with MT5 terminal.
        Updates 'status' to 'pending' if still open, or 'closed' if found in MT5 history.
        
        NEW PATH STRUCTURE:
        - tradeshistory.json is now stored directly in the investor root folder
        - signals_path should be the path to signals.json in the investor root
        """
        try:
            # Determine the investor root folder
            # signals_path could be INV_PATH/{investor_id}/signals.json
            # So parent of signals_path is the investor root
            if signals_path.name == "signals.json":
                investor_root = signals_path.parent
            else:
                # Fallback: try to find investor root from pending_orders structure (backward compatibility)
                # Look for pending_orders folder in the path
                if "pending_orders" in str(signals_path):
                    investor_root = signals_path.parents[2] if len(signals_path.parents) > 2 else signals_path.parent
                else:
                    investor_root = signals_path.parent
            
            # NEW PATH: tradeshistory.json directly in investor root
            history_path = investor_root / "tradeshistory.json"
            
            print(f"      📂 Tradeshistory path: {history_path}")
            
            history = []
            if history_path.exists():
                try:
                    with open(history_path, 'r', encoding='utf-8') as f:
                        history = json.load(f)
                    print(f"      📋 Loaded {len(history)} existing trades from tradeshistory.json")
                except Exception as e:
                    print(f"      ⚠️  Error reading tradeshistory.json: {e}")
                    history = []

            # 1. Add new trade if provided
            if new_trade:
                # Check if trade already exists to avoid duplicates
                existing_ticket = any(t.get('ticket') == new_trade.get('ticket') for t in history)
                if not existing_ticket:
                    history.append(new_trade)
                    print(f"      ➕ Added new trade: Ticket {new_trade.get('ticket')}")
                else:
                    print(f"      ℹ️  Trade Ticket {new_trade.get('ticket')} already exists in history")

            # 2. Sync all records with MT5
            active_orders = {o.ticket for o in (mt5.orders_get() or [])}
            active_positions = {p.ticket for p in (mt5.positions_get() or [])}
            
            # Fetch history for the last 24 hours to check recently closed
            from_date = datetime.now() - timedelta(days=1)
            history_deals = mt5.history_deals_get(from_date, datetime.now())
            history_tickets = {d.order for d in history_deals} if history_deals else set()
            
            # Also fetch older history to ensure complete sync (up to 7 days)
            from_date_7days = datetime.now() - timedelta(days=7)
            older_history_deals = mt5.history_deals_get(from_date_7days, datetime.now())
            if older_history_deals:
                older_tickets = {d.order for d in older_history_deals}
                history_tickets.update(older_tickets)
            
            print(f"      🔍 MT5 Status: {len(active_orders)} active orders, {len(active_positions)} active positions, {len(history_tickets)} recent closed trades")
            
            updated_count = 0
            for trade in history:
                ticket = trade.get('ticket')
                if not ticket:
                    continue
                
                old_status = trade.get('status', 'unknown')
                
                # Logic: If ticket is in active orders or active positions, it's pending/active
                if ticket in active_orders or ticket in active_positions:
                    trade['status'] = 'pending'
                    if old_status != 'pending':
                        print(f"      🔄 Trade {ticket}: {old_status} → pending (still open)")
                        updated_count += 1
                # If not active, check if it exists in MT5 history deals
                elif ticket in history_tickets:
                    trade['status'] = 'closed'
                    if old_status != 'closed':
                        # Get profit from history deals for closed trades
                        for deal in (history_deals or older_history_deals or []):
                            if deal.order == ticket:
                                trade['profit'] = deal.profit
                                trade['close_price'] = deal.price
                                trade['close_time'] = datetime.fromtimestamp(deal.time).strftime('%Y-%m-%d %H:%M:%S')
                                break
                        print(f"      🔄 Trade {ticket}: {old_status} → closed (found in MT5 history)")
                        updated_count += 1
                # If not found in either, mark as closed/expired (MT5 might have cleared it)
                else:
                    if trade.get('status') == 'pending':
                        trade['status'] = 'closed'
                        print(f"      🔄 Trade {ticket}: pending → closed (expired/not found in MT5)")
                        updated_count += 1
                    elif trade.get('status') != 'closed':
                        trade['status'] = 'closed'
                        print(f"      🔄 Trade {ticket}: {old_status} → closed (default)")
                        updated_count += 1

            # Save updated history
            try:
                with open(history_path, 'w', encoding='utf-8') as f:
                    json.dump(history, f, indent=4)
                
                if new_trade:
                    print(f"      ✅ Saved new trade to tradeshistory.json (Ticket: {new_trade['ticket']})")
                elif updated_count > 0:
                    print(f"      ✅ Updated {updated_count} trades in tradeshistory.json")
                else:
                    print(f"      ℹ️  No changes to tradeshistory.json")
                    
                # Also save a backup copy in the investor root for safety
                backup_path = investor_root / "tradeshistory_backup.json"
                try:
                    with open(backup_path, 'w', encoding='utf-8') as f:
                        json.dump(history, f, indent=4)
                    print(f"      💾 Backup saved to: {backup_path}")
                except Exception as e:
                    print(f"      ⚠️  Could not save backup: {e}")
                    
            except Exception as e:
                print(f"      ❌ Failed to save tradeshistory.json: {e}")
                return False
                
            return True
            
        except Exception as e:
            print(f"      ❌ Error in sync_and_save_history: {e}")
            return False
    
    # --- SUB-FUNCTION 5: ORDER EXECUTION ---
    def execute_missing_orders(valid_entries, default_magic, trade_allowed):
        if not trade_allowed:
            print("  ⚠️  AutoTrading is DISABLED in Terminal")
            return 0, 0, 0
        placed = failed = skipped = 0
        for entry_wrapper in valid_entries:
            entry = entry_wrapper['data']
            symbol = entry["symbol"]
            signals_path = entry_wrapper['path']
            
            if not mt5.symbol_select(symbol, True): failed += 1; continue
            symbol_info = mt5.symbol_info(symbol)
            
            vol_key = next((k for k in entry.keys() if k.endswith("volume")), "volume")
            raw_vol = float(entry.get(vol_key, 0))
            volume = max(symbol_info.volume_min, min(symbol_info.volume_max, raw_vol))
            
            magic_number = int(entry.get("magic", default_magic))
            request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": symbol,
                "volume": round(volume, 2),
                "type": mt5.ORDER_TYPE_BUY_LIMIT if "buy" in entry.get("order_type", "").lower() else mt5.ORDER_TYPE_SELL_LIMIT,
                "price": round(float(entry["entry"]), symbol_info.digits),
                "sl": round(float(entry["exit"]), symbol_info.digits),
                "tp": round(float(entry["target"]), symbol_info.digits),
                "magic": magic_number,
                "comment": f"RR{entry.get('risk_reward', '?')}",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            res = mt5.order_send(request)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"      ✅ SUCCESS: {symbol} @ {request['price']} (Ticket: {res.order})")
                new_rec = entry.copy()
                new_rec.update({'ticket': res.order, 'magic': magic_number, 'placed_timestamp': datetime.now().isoformat(), 'status': 'pending'})
                sync_and_save_history(signals_path, new_trade=new_rec)
                placed += 1
            else:
                print(f"      ⚠️  REJECTED: {symbol} -> {res.comment if res else 'No Response'}")
                failed += 1
        return placed, failed, skipped

    # --- SUB-FUNCTION 6: CLEANUP SIGNALS ---
    def cleanup_signals_file(item):
        try:
            signals_path = item['path']
            with open(signals_path, 'r', encoding='utf-8') as sf:
                current_sigs = json.load(sf)
            new_sigs = [s for s in current_sigs if not (s.get('symbol') == item['data'].get('symbol') and abs(float(s.get('entry', 0)) - float(item['data'].get('entry', 0))) < 0.00001)]
            with open(signals_path, 'w', encoding='utf-8') as sf:
                json.dump(new_sigs, sf, indent=4)
        except: pass

    # --- MAIN EXECUTION FLOW ---
    print("\n" + "="*80)
    print("🚀 STARTING USD ORDER PLACEMENT ENGINE (GLOBAL CHECK)")
    print("="*80)
    
    investor_ids = [inv_id] if inv_id else list(usersdictionary.keys()) 
    any_orders_placed = False

    for user_brokerid in investor_ids:
        print(f"\n📋 INVESTOR: {user_brokerid}")
        resolution_cache = {}
        inv_root = Path(INV_PATH) / user_brokerid 
        if not inv_root.exists(): continue

        # CALL COLLECT_ORDERS_FROM_SIGNALS - This is where the function is called
        # Collect all orders from signals.json files
        all_entries_with_paths = collect_orders_from_signals(inv_root, resolution_cache)
        
        if not all_entries_with_paths:
            print(f"  ℹ️  No signals found for {user_brokerid}")
            continue

        # Group signals by their pending_orders folder for authorization checking
        folders_to_process = {}
        for entry_wrapper in all_entries_with_paths:
            signals_path = entry_wrapper['path']
            pending_folder = signals_path.parent
            if pending_folder not in folders_to_process:
                folders_to_process[pending_folder] = []
            folders_to_process[pending_folder].append(entry_wrapper)
        
        authorized_entries = []
        for pending_folder, folder_entries in folders_to_process.items():
            # ALWAYS SYNC HISTORY first even if no new signals exist
            if folder_entries:
                sync_and_save_history(folder_entries[0]['path'])
            
            can_proceed, activities = check_authorization_status(pending_folder)
            if can_proceed:
                authorized_entries.extend(folder_entries)
            else:
                print(f"  ⛔ SKIPPING all orders in this folder due to authorization block")
                if activities and activities.get('unauthorized_action_detected', False) and not activities.get('bypass_restriction', False):
                    cancel_authorized_orders_and_positions(inv_root, pending_folder)
        
        if not authorized_entries:
            print(f"  ℹ️  No authorized entries found for {user_brokerid}")
            continue

        print(f"  🔍 Performing Global Existence Check on {len(authorized_entries)} authorized signals...")
        active_positions = mt5.positions_get() or []
        pending_orders = mt5.orders_get() or []
        existing_lookup = {(p.symbol, round(p.price_open, 5), round(p.volume, 2)) for p in active_positions}
        existing_lookup.update({(o.symbol, round(o.price_open, 5), round(o.volume_initial, 2)) for o in pending_orders})

        to_place = []
        for item in authorized_entries:
            data = item['data']
            vol_key = next((k for k in data.keys() if k.endswith("volume")), "volume")
            sig_key = (data['symbol'], round(float(data['entry']), 5), round(float(data.get(vol_key, 0)), 2))
            
            if sig_key in existing_lookup:
                # Move to placed_orders.json logic
                hist_path = item['path'].parent / "placed_orders.json"
                current_hist = []
                if hist_path.exists():
                    try:
                        with open(hist_path, 'r', encoding='utf-8') as hf: 
                            current_hist = json.load(hf)
                    except: pass
                moved_record = item['data'].copy()
                moved_record.update({'moved_timestamp': datetime.now().isoformat(), 'reason': 'already_exists'})
                current_hist.append(moved_record)
                with open(hist_path, 'w', encoding='utf-8') as hf: 
                    json.dump(current_hist, hf, indent=4)
                cleanup_signals_file(item)
            else:
                to_place.append(item)

        if to_place:
            print(f"  📊 Attempting to place {len(to_place)} new orders...")
            acc_mgmt_path = inv_root / "accountmanagement.json"
            if acc_mgmt_path.exists():
                with open(acc_mgmt_path, 'r', encoding='utf-8') as f: 
                    config = json.load(f)
                p, f, s = execute_missing_orders(to_place, config.get("magic_number", 123456), mt5.terminal_info().trade_allowed)
                if p > 0:
                    any_orders_placed = True
                    for item in to_place[:p]: 
                        cleanup_signals_file(item)
                print(f"      📊 Summary: {p} placed, {f} failed")
        else:
            print("  ℹ️  No new unique orders to place.")

    print("\n" + "="*80)
    print("✅ PROCESS COMPLETE")
    print("="*80)
    return any_orders_placed
     
def check_pending_orders_risk(inv_id=None):
    """
    Function 3: Validates live pending orders against the account's current risk bucket.
     VERSION: Uses the EXACT account initialization logic from place_usd_orders_for_accounts()
    Only removes orders with risk HIGHER than allowed (lower risk orders are kept).
    
    NOW CHECKS: ALL pending orders (LIMIT, STOP, STOP-LIMIT)
    
    RISK CONFIGURATION LOGIC:
    - If enable_maximum_account_balance_management = true -> use account_balance_maximum_risk_management
    - Else if enable_default_account_balance_management = true -> use account_balance_default_risk_management
    - Else (both false) -> default to account_balance_default_risk_management
    
    Args:
        inv_id: Optional specific investor ID to process. If None, processes all investors.
        
    Returns:
        dict: Statistics about the processing
    """
    print(f"\n{'='*10} 🛡️ LIVE RISK AUDIT: ALL PENDING ORDERS (LIMIT + STOP)  {'='*10}")
    if inv_id:
        print(f" Processing single investor: {inv_id}")

    # --- DATA INITIALIZATION ---
    stats = {
        "investor_id": inv_id if inv_id else "all",
        "orders_checked": 0,
        "orders_removed": 0,
        "orders_kept_lower": 0,
        "orders_kept_in_range": 0,
        "risk_config_used": None,
        "processing_success": False
    }
    
    try:
        if not os.path.exists(NORMALIZE_SYMBOLS_PATH):
            print(" [!] CRITICAL ERROR: Normalization map path missing.")
            return stats
        with open(NORMALIZE_SYMBOLS_PATH, 'r') as f:
            norm_map = json.load(f)
    except Exception as e:
        print(f" [!] CRITICAL ERROR: Normalization map load failed: {e}")
        return stats

    # Define MT5 order types for better readability
    ORDER_TYPES = {
        mt5.ORDER_TYPE_BUY_LIMIT: "BUY LIMIT",
        mt5.ORDER_TYPE_SELL_LIMIT: "SELL LIMIT",
        mt5.ORDER_TYPE_BUY_STOP: "BUY STOP",
        mt5.ORDER_TYPE_SELL_STOP: "SELL STOP",
        mt5.ORDER_TYPE_BUY_STOP_LIMIT: "BUY STOP-LIMIT",
        mt5.ORDER_TYPE_SELL_STOP_LIMIT: "SELL STOP-LIMIT"
    }

    # Determine which investors to process
    investors_to_process = [inv_id] if inv_id else usersdictionary.keys()
    total_investors = len(investors_to_process) if not inv_id else 1
    processed = 0

    for user_brokerid in investors_to_process:
        processed += 1
        print(f"\n[{processed}/{total_investors}] {user_brokerid} 🔍 Auditing live risk limits...")
        
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

        # --- LOAD CONFIG AND DETERMINE RISK CONFIGURATION TO USE ---
        try:
            with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Get settings flags
            settings = config.get("settings", {})
            enable_default = settings.get("enable_default_account_balance_management", False)
            enable_maximum = settings.get("enable_maximum_account_balance_management", False)
            
            print(f"  └─ ⚙️  Risk Configuration Settings:")
            print(f"      • enable_default_account_balance_management: {enable_default}")
            print(f"      • enable_maximum_account_balance_management: {enable_maximum}")
            
            # Determine which risk config to use
            risk_map = None
            risk_config_used = None
            
            # LOGIC: If maximum is enabled, use maximum (even if default is also enabled)
            if enable_maximum:
                risk_map = config.get("account_balance_maximum_risk_management", {})
                risk_config_used = "maximum"
                print(f"      📋 USING: account_balance_maximum_risk_management (maximum enabled)")
            
            # Else if default is enabled (and maximum is false), use default
            elif enable_default:
                risk_map = config.get("account_balance_default_risk_management", {})
                risk_config_used = "default"
                print(f"      📋 USING: account_balance_default_risk_management (default enabled)")
            
            # Else (both false), default to default risk management
            else:
                risk_map = config.get("account_balance_default_risk_management", {})
                risk_config_used = "default (fallback)"
                print(f"      📋 USING: account_balance_default_risk_management (fallback - both flags false)")
            
            if not risk_map:
                print(f"  └─ ⚠️  Selected risk configuration is empty or missing")
                continue
                
        except Exception as e:
            print(f"  └─ ❌ Failed to read config: {e}")
            continue

        # --- ACCOUNT CONNECTION CHECK (NO INIT/SHUTDOWN) ---
        print(f"  └─ 🔌 Checking account connection...")
        
        login_id = int(broker_cfg['LOGIN_ID'])
        mt5_path = broker_cfg["TERMINAL_PATH"]
        
        print(f"      • Terminal Path: {mt5_path}")
        print(f"      • Login ID: {login_id}")

        # Check if already logged into correct account
        acc = mt5.account_info()
        if acc is None or acc.login != login_id:
            print(f"  └─ ❌ Not logged into the correct account. Expected: {login_id}, Found: {acc.login if acc else 'None'}")
            continue
        else:
            print(f"      ✅ Connected to account: {acc.login}")

        acc_info = mt5.account_info()
        if not acc_info:
            print(f"  └─ ❌ Failed to get account info")
            continue
            
        balance = acc_info.balance

        # Get terminal info for additional details
        term_info = mt5.terminal_info()
        
        print(f"\n  └─ 📊 Account Details:")
        print(f"      • Balance: ${acc_info.balance:,.2f}")
        print(f"      • Equity: ${acc_info.equity:,.2f}")
        print(f"      • Free Margin: ${acc_info.margin_free:,.2f}")
        print(f"      • Margin Level: {acc_info.margin_level:.2f}%" if acc_info.margin_level else "      • Margin Level: N/A")
        print(f"      • AutoTrading: {'✅ ENABLED' if term_info.trade_allowed else '❌ DISABLED'}")

        # Determine Primary Risk Value based on selected risk map
        primary_risk = None
        for range_str, r_val in risk_map.items():
            try:
                raw_range = range_str.split("_")[0]
                low, high = map(float, raw_range.split("-"))
                if low <= balance <= high:
                    primary_risk = float(r_val)
                    break
            except Exception as e:
                print(f"  └─ ⚠️  Error parsing range '{range_str}': {e}")
                continue

        if primary_risk is None:
            print(f"  └─ ⚠️  No risk mapping for balance ${balance:,.2f} in selected config")
            continue

        print(f"\n  └─ 💰 Target Risk (from {risk_config_used} config): ${primary_risk:.2f}")
        
        # Store which config was used in stats
        stats["risk_config_used"] = risk_config_used

        # Check ALL Live Pending Orders (LIMIT, STOP, STOP-LIMIT)
        pending_orders = mt5.orders_get()
        investor_orders_checked = 0
        investor_orders_removed = 0
        investor_orders_kept_lower = 0
        investor_orders_kept_in_range = 0

        if pending_orders:
            print(f"  └─ 🔍 Scanning {len(pending_orders)} pending orders (ALL types)...")
            
            for order in pending_orders:
                # Skip if not a pending order type
                if order.type not in ORDER_TYPES.keys():
                    continue

                investor_orders_checked += 1
                stats["orders_checked"] += 1
                
                order_type_name = ORDER_TYPES.get(order.type, f"Unknown Type {order.type}")
                
                # Determine order direction for calculations
                is_buy = order.type in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP, mt5.ORDER_TYPE_BUY_STOP_LIMIT]
                calc_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
                
                # Calculate risk (stop loss distance in money)
                if order.sl == 0:
                    print(f"    └─ ⚠️  Order #{order.ticket} | {order_type_name} | {order.symbol} - No SL set, skipping risk check")
                    continue
                
                sl_profit = mt5.order_calc_profit(calc_type, order.symbol, order.volume_initial, 
                                                  order.price_open, order.sl)
                
                if sl_profit is not None:
                    order_risk_usd = round(abs(sl_profit), 2)
                    
                    # Use a percentage-based threshold instead of absolute dollar difference
                    # For small balances, absolute differences can be misleading
                    risk_difference = order_risk_usd - primary_risk
                    
                    # For very small balances (like $2), a difference of $0.50 is significant
                    # Use a relative threshold: 20% of primary risk or $0.50, whichever is smaller
                    relative_threshold = max(0.50, primary_risk * 0.2)
                    
                    print(f"    └─ 📋 Order #{order.ticket} | {order_type_name} | {order.symbol}")
                    print(f"       Risk: ${order_risk_usd:.2f} | Target Risk: ${primary_risk:.2f}")
                    
                    # Only remove if risk is significantly higher than allowed
                    if risk_difference > relative_threshold: 
                        print(f"       🗑️ PURGING: Risk too high")
                        print(f"       Risk: ${order_risk_usd:.2f} > Allowed: ${primary_risk:.2f} (Δ: ${risk_difference:.2f})")
                        
                        cancel_request = {
                            "action": mt5.TRADE_ACTION_REMOVE,
                            "order": order.ticket
                        }
                        result = mt5.order_send(cancel_request)
                        
                        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                            investor_orders_removed += 1
                            stats["orders_removed"] += 1
                            print(f"       ✅ Order removed successfully")
                        else:
                            error_msg = result.comment if result else "No response"
                            print(f"       ❌ Cancel failed: {error_msg}")
                    
                    elif order_risk_usd < primary_risk - relative_threshold:
                        # Lower risk - keep it (good for the account)
                        investor_orders_kept_lower += 1
                        stats["orders_kept_lower"] += 1
                        print(f"       ✅ KEEPING: Lower risk than allowed")
                        print(f"       Risk: ${order_risk_usd:.2f} < Allowed: ${primary_risk:.2f} (Δ: ${primary_risk - order_risk_usd:.2f})")
                    
                    else:
                        # Within tolerance - keep it
                        investor_orders_kept_in_range += 1
                        stats["orders_kept_in_range"] += 1
                        print(f"       ✅ KEEPING: Risk within tolerance")
                        print(f"       Risk: ${order_risk_usd:.2f} vs Allowed: ${primary_risk:.2f} (Δ: ${abs(risk_difference):.2f})")
                else:
                    print(f"    └─ ⚠️  Order #{order.ticket} - Could not calculate risk")

        # Investor final summary
        if investor_orders_checked > 0:
            print(f"\n  └─ 📊 Audit Results for {user_brokerid}:")
            print(f"       • Risk config used: {risk_config_used}")
            print(f"       • Orders checked: {investor_orders_checked}")
            if investor_orders_kept_lower > 0:
                print(f"       • Kept (lower risk): {investor_orders_kept_lower}")
            if investor_orders_kept_in_range > 0:
                print(f"       • Kept (in tolerance): {investor_orders_kept_in_range}")
            if investor_orders_removed > 0:
                print(f"       • Removed (too high): {investor_orders_removed}")
            else:
                print(f"       ✅ No orders needed removal")
            stats["processing_success"] = True
        else:
            print(f"  └─ 🔘 No pending orders found.")

    # --- FINAL SUMMARY ---
    print(f"\n{'='*10} 📊 RISK AUDIT SUMMARY {'='*10}")
    print(f"   Investor ID: {stats['investor_id']}")
    print(f"   Risk config used: {stats['risk_config_used']}")
    print(f"   Orders checked: {stats['orders_checked']}")
    print(f"   Orders removed: {stats['orders_removed']}")
    print(f"   Orders kept (lower risk): {stats['orders_kept_lower']}")
    print(f"   Orders kept (in tolerance): {stats['orders_kept_in_range']}")
    
    if stats['orders_checked'] > 0:
        removal_rate = (stats['orders_removed'] / stats['orders_checked']) * 100
        print(f"   Removal rate: {removal_rate:.1f}%")
    
    print(f"\n{'='*10} 🏁 RISK AUDIT COMPLETE {'='*10}\n")
    return stats

def orders_risk_correction_old(inv_id=None):
    """
    Function: Checks both live pending orders AND open positions (LIMIT, STOP, and MARKET)
    and adjusts their take profit levels based on the selected risk-reward ratio from
    accountmanagement.json. Only executes if risk_reward_correction setting is True.
    
     VERSION: Uses the EXACT account initialization logic from place_usd_orders_for_accounts()
    
    Args:
        inv_id: Optional specific investor ID to process. If None, processes all investors.
        
    Returns:
        dict: Statistics about the processing
    """
    print(f"\n{'='*10} 📐 RISK-REWARD CORRECTION: ALL POSITIONS & PENDING ORDERS (MARKET + LIMIT + STOP)  {'='*10}")
    if inv_id:
        print(f" Processing single investor: {inv_id}")

    # Track statistics
    stats = {
        "investor_id": inv_id if inv_id else "all",
        "orders_checked": 0,
        "orders_adjusted": 0,
        "orders_skipped": 0,
        "orders_error": 0,
        "positions_checked": 0,
        "positions_adjusted": 0,
        "processing_success": False
    }

    # Determine which investors to process
    investors_to_process = [inv_id] if inv_id else usersdictionary.keys()
    total_investors = len(investors_to_process) if not inv_id else 1
    processed = 0

    for user_brokerid in investors_to_process:
        processed += 1
        print(f"\n[{processed}/{total_investors}] {user_brokerid} 🔍 Checking risk-reward configurations...")
        
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
            
            # Check if risk_reward_correction is enabled
            settings = config.get("settings", {})
            if not settings.get("risk_reward_correction", False):
                print(f"  └─ ⏭️  Risk-reward correction disabled in settings. Skipping.")
                continue
            
            # Get selected risk-reward ratios
            selected_rr = config.get("selected_risk_reward", [2])
            if not selected_rr:
                print(f"  └─ ⚠️  No risk-reward ratios selected. Using default [2]")
                selected_rr = [2]
            
            # Use the first ratio in the list (typically the preferred one)
            target_rr_ratio = float(selected_rr[0])
            print(f"  └─ ✅ Target R:R Ratio: 1:{target_rr_ratio}")
            
            # Get risk management mapping for balance-based risk
            risk_map = config.get("account_balance_default_risk_management", {})
            
        except Exception as e:
            print(f"  └─ ❌ Failed to read config: {e}")
            stats["orders_error"] += 1
            continue

        # --- ACCOUNT INITIALIZATION (EXACT COPY FROM place_usd_orders_for_accounts) ---
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
                print(f"  └─ ❌  login failed: {error}")
                stats["orders_error"] += 1
                continue
            print(f"      ✅ Successfully logged into account")
        else:
            print(f"      ✅ Already logged into account")
        # --- END EXACT INITIALIZATION COPY ---

        acc_info = mt5.account_info()
        if not acc_info:
            print(f"  └─ ❌ Failed to get account info")
            stats["orders_error"] += 1
            continue
            
        balance = acc_info.balance

        # Get terminal info for additional details
        term_info = mt5.terminal_info()
        
        print(f"\n  └─ 📊 Account Details:")
        print(f"      • Balance: ${acc_info.balance:,.2f}")
        print(f"      • Equity: ${acc_info.equity:,.2f}")
        print(f"      • Free Margin: ${acc_info.margin_free:,.2f}")
        print(f"      • Margin Level: {acc_info.margin_level:.2f}%" if acc_info.margin_level else "      • Margin Level: N/A")
        print(f"      • AutoTrading: {'✅ ENABLED' if term_info.trade_allowed else '❌ DISABLED'}")

        # --- DETERMINE PRIMARY RISK VALUE BASED ON BALANCE ---
        primary_risk = None
        for range_str, r_val in risk_map.items():
            try:
                raw_range = range_str.split("_")[0]
                low, high = map(float, raw_range.split("-"))
                if low <= balance <= high:
                    primary_risk = float(r_val)
                    break
            except Exception as e:
                print(f"  └─ ⚠️  Error parsing range '{range_str}': {e}")
                continue

        if primary_risk is None:
            print(f"  └─ ⚠️  No risk mapping for balance ${balance:,.2f}")
            stats["orders_skipped"] += 1
            continue

        print(f"\n  └─ 💰 Balance: ${balance:,.2f} | Base Risk: ${primary_risk:.2f} | Target R:R: 1:{target_rr_ratio}")

        # --- CHECK AND ADJUST ALL POSITIONS (OPEN MARKET ORDERS) ---
        positions = mt5.positions_get()
        investor_positions_checked = 0
        investor_positions_adjusted = 0
        investor_positions_skipped = 0
        investor_positions_error = 0

        # Define MT5 position/order types for better readability
        POSITION_TYPES = {
            mt5.POSITION_TYPE_BUY: "BUY (MARKET)",
            mt5.POSITION_TYPE_SELL: "SELL (MARKET)"
        }
        
        ORDER_TYPES = {
            mt5.ORDER_TYPE_BUY_LIMIT: "BUY LIMIT",
            mt5.ORDER_TYPE_SELL_LIMIT: "SELL LIMIT",
            mt5.ORDER_TYPE_BUY_STOP: "BUY STOP",
            mt5.ORDER_TYPE_SELL_STOP: "SELL STOP",
            mt5.ORDER_TYPE_BUY_STOP_LIMIT: "BUY STOP-LIMIT",
            mt5.ORDER_TYPE_SELL_STOP_LIMIT: "SELL STOP-LIMIT"
        }

        # Process OPEN POSITIONS first
        if positions:
            print(f"\n  └─ 🔍 Scanning {len(positions)} open positions (MARKET)...")
            
            for position in positions:
                investor_positions_checked += 1
                stats["positions_checked"] += 1
                
                position_type_name = POSITION_TYPES.get(position.type, f"Unknown Type {position.type}")
                
                # Get symbol info
                symbol_info = mt5.symbol_info(position.symbol)
                if not symbol_info:
                    print(f"    └─ ⚠️  Cannot get symbol info for {position.symbol}")
                    investor_positions_skipped += 1
                    stats["orders_skipped"] += 1
                    continue

                # Determine position direction
                is_buy = position.type == mt5.POSITION_TYPE_BUY
                
                print(f"\n    └─ 📋 Position #{position.ticket} | {position_type_name} | {position.symbol}")
                
                # Calculate current risk (stop loss distance in money)
                if position.sl == 0:
                    print(f"       ⚠️  No SL set - cannot calculate risk. Skipping TP adjustment.")
                    investor_positions_skipped += 1
                    stats["orders_skipped"] += 1
                    continue
                
                # For positions, risk is from current price to SL (or entry to SL if price moved favorably)
                # We use the more conservative approach: risk based on original entry to SL
                # This ensures we don't reduce TP if price has moved in our favor
                if is_buy:
                    # For BUY: entry price is position.price_open
                    risk_price = position.price_open - position.sl
                else:
                    # For SELL: entry price is position.price_open
                    risk_price = position.sl - position.price_open
                
                # Calculate risk in money
                risk_points = abs(risk_price) / symbol_info.point
                point_value = symbol_info.trade_tick_value / symbol_info.trade_tick_size * symbol_info.point
                current_risk_usd = round(risk_points * point_value * position.volume, 2)
                
                # Alternative: calculate using MT5 profit calculator for accuracy
                calc_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
                sl_profit = mt5.order_calc_profit(calc_type, position.symbol, position.volume, 
                                                  position.price_open, position.sl)
                
                if sl_profit is not None:
                    current_risk_usd = round(abs(sl_profit), 2)
                
                # Calculate required take profit based on risk and target R:R ratio
                target_profit_usd = current_risk_usd * target_rr_ratio
                
                print(f"       Risk (from entry): ${current_risk_usd:.2f} | Target Profit: ${target_profit_usd:.2f}")
                
                # Calculate the take profit price that would achieve this profit
                tick_value = symbol_info.trade_tick_value
                tick_size = symbol_info.trade_tick_size
                
                if tick_value > 0 and tick_size > 0:
                    # Calculate how many ticks we need to move to achieve target profit
                    ticks_needed = target_profit_usd / (position.volume * tick_value)
                    
                    # Convert ticks to price movement
                    price_move_needed = ticks_needed * tick_size
                    
                    # Round to symbol digits
                    digits = symbol_info.digits
                    price_move_needed = round(price_move_needed, digits)
                    
                    # Calculate new take profit price based on position type (from entry price, not current price)
                    if is_buy:
                        # For BUY positions: TP above entry price
                        new_tp = round(position.price_open + price_move_needed, digits)
                    else:
                        # For SELL positions: TP below entry price
                        new_tp = round(position.price_open - price_move_needed, digits)
                    
                    # Check if current TP is significantly different from calculated TP
                    if position.tp == 0:
                        target_move = abs(new_tp - position.price_open)
                        print(f"       📝 No TP currently set")
                        print(f"       Target TP: {new_tp:.{digits}f} (Move from entry: {target_move:.{digits}f})")
                        should_adjust = True
                    else:
                        current_move = abs(position.tp - position.price_open)
                        target_move = abs(new_tp - position.price_open)
                        
                        # Calculate threshold (10% of target move or 2 pips, whichever is larger)
                        pip_threshold = max(target_move * 0.1, symbol_info.point * 20)
                        
                        if abs(current_move - target_move) > pip_threshold:
                            print(f"       📐 TP needs adjustment")
                            print(f"       Current TP: {position.tp:.{digits}f} (Move from entry: {current_move:.{digits}f})")
                            print(f"       Target TP:  {new_tp:.{digits}f} (Move from entry: {target_move:.{digits}f})")
                            should_adjust = True
                        else:
                            print(f"       ✅ TP already correct")
                            print(f"       TP: {position.tp:.{digits}f} | Risk: ${current_risk_usd:.2f}")
                            investor_positions_skipped += 1
                            stats["orders_skipped"] += 1
                            continue
                    
                    if should_adjust:
                        # Prepare modification request for position
                        modify_request = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "position": position.ticket,
                            "sl": position.sl,
                            "tp": new_tp,
                        }
                        
                        # Send modification
                        result = mt5.order_send(modify_request)
                        
                        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                            investor_positions_adjusted += 1
                            stats["positions_adjusted"] += 1
                            stats["orders_adjusted"] += 1
                            print(f"       ✅ TP adjusted successfully to {new_tp:.{digits}f}")
                        else:
                            investor_positions_error += 1
                            stats["orders_error"] += 1
                            error_msg = result.comment if result else f"Error code: {result.retcode if result else 'Unknown'}"
                            print(f"       ❌ Modification failed: {error_msg}")
                else:
                    print(f"       ⚠️  Invalid tick values - using fallback calculation")
                    # Fallback method using profit calculation for a small price movement
                    try:
                        test_move = symbol_info.point * 10
                        if is_buy:
                            test_price = position.price_open + test_move
                        else:
                            test_price = position.price_open - test_move
                            
                        test_profit = mt5.order_calc_profit(calc_type, position.symbol, position.volume, 
                                                            position.price_open, test_price)
                        
                        if test_profit and test_profit != 0:
                            point_value = abs(test_profit) / 10
                            price_move_needed = target_profit_usd / point_value * symbol_info.point
                            
                            digits = symbol_info.digits
                            price_move_needed = round(price_move_needed, digits)
                            
                            if is_buy:
                                new_tp = round(position.price_open + price_move_needed, digits)
                            else:
                                new_tp = round(position.price_open - price_move_needed, digits)
                            
                            print(f"       Using fallback calculation")
                            
                            if position.tp == 0 or abs(position.tp - new_tp) > symbol_info.point * 20:
                                modify_request = {
                                    "action": mt5.TRADE_ACTION_SLTP,
                                    "position": position.ticket,
                                    "sl": position.sl,
                                    "tp": new_tp,
                                }
                                
                                result = mt5.order_send(modify_request)
                                
                                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                                    investor_positions_adjusted += 1
                                    stats["positions_adjusted"] += 1
                                    stats["orders_adjusted"] += 1
                                    print(f"       ✅ TP adjusted using fallback method to {new_tp:.{digits}f}")
                                else:
                                    investor_positions_error += 1
                                    stats["orders_error"] += 1
                                    print(f"       ❌ Fallback modification failed")
                            else:
                                investor_positions_skipped += 1
                                stats["orders_skipped"] += 1
                                print(f"       ✅ TP already correct (fallback check)")
                        else:
                            investor_positions_skipped += 1
                            stats["orders_skipped"] += 1
                            print(f"       ⚠️  Cannot calculate using fallback method")
                    except Exception as e:
                        investor_positions_error += 1
                        stats["orders_error"] += 1
                        print(f"       ❌ Fallback calculation error: {e}")
        
        # --- CHECK AND ADJUST ALL PENDING ORDERS (LIMIT AND STOP) ---
        pending_orders = mt5.orders_get()
        investor_orders_checked = 0
        investor_orders_adjusted = 0
        investor_orders_skipped = 0
        investor_orders_error = 0

        if pending_orders:
            print(f"\n  └─ 🔍 Scanning {len(pending_orders)} pending orders (LIMIT & STOP)...")
            
            for order in pending_orders:
                # Skip if not a pending order (only process pending order types)
                if order.type not in ORDER_TYPES.keys():
                    continue

                investor_orders_checked += 1
                stats["orders_checked"] += 1
                
                order_type_name = ORDER_TYPES.get(order.type, f"Unknown Type {order.type}")
                
                # Get symbol info
                symbol_info = mt5.symbol_info(order.symbol)
                if not symbol_info:
                    print(f"    └─ ⚠️  Cannot get symbol info for {order.symbol}")
                    investor_orders_skipped += 1
                    stats["orders_skipped"] += 1
                    continue

                # Determine order direction for calculations
                is_buy = order.type in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP, mt5.ORDER_TYPE_BUY_STOP_LIMIT]
                calc_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
                
                print(f"\n    └─ 📋 Order #{order.ticket} | {order_type_name} | {order.symbol}")
                
                # Calculate current risk (stop loss distance in money)
                if order.sl == 0:
                    print(f"       ⚠️  No SL set - cannot calculate risk. Skipping TP adjustment.")
                    investor_orders_skipped += 1
                    stats["orders_skipped"] += 1
                    continue
                    
                # For pending orders, risk is from entry to SL
                sl_profit = mt5.order_calc_profit(calc_type, order.symbol, order.volume_initial, 
                                                  order.price_open, order.sl)
                
                if sl_profit is None:
                    print(f"       ⚠️  Cannot calculate risk. Skipping.")
                    investor_orders_skipped += 1
                    stats["orders_skipped"] += 1
                    continue

                current_risk_usd = round(abs(sl_profit), 2)
                
                # Calculate required take profit based on risk and target R:R ratio
                target_profit_usd = current_risk_usd * target_rr_ratio
                
                print(f"       Risk: ${current_risk_usd:.2f} | Target Profit: ${target_profit_usd:.2f}")
                
                # Calculate the take profit price that would achieve this profit
                tick_value = symbol_info.trade_tick_value
                tick_size = symbol_info.trade_tick_size
                
                if tick_value > 0 and tick_size > 0:
                    # Calculate how many ticks we need to move to achieve target profit
                    ticks_needed = target_profit_usd / (order.volume_initial * tick_value)
                    
                    # Convert ticks to price movement
                    price_move_needed = ticks_needed * tick_size
                    
                    # Round to symbol digits
                    digits = symbol_info.digits
                    price_move_needed = round(price_move_needed, digits)
                    
                    # Calculate new take profit price based on order type
                    if is_buy:
                        # For BUY orders: TP above entry
                        new_tp = round(order.price_open + price_move_needed, digits)
                    else:
                        # For SELL orders: TP below entry
                        new_tp = round(order.price_open - price_move_needed, digits)
                    
                    # Check if current TP is significantly different from calculated TP
                    current_move = abs(order.tp - order.price_open) if order.tp != 0 else 0
                    target_move = abs(new_tp - order.price_open)
                    
                    # Calculate threshold (10% of target move or 2 pips, whichever is larger)
                    pip_threshold = max(target_move * 0.1, symbol_info.point * 20)
                    
                    should_adjust = False
                    
                    if order.tp == 0:
                        print(f"       📝 No TP currently set")
                        print(f"       Target TP: {new_tp:.{digits}f} (Move: {target_move:.{digits}f})")
                        should_adjust = True
                    elif abs(current_move - target_move) > pip_threshold:
                        print(f"       📐 TP needs adjustment")
                        print(f"       Current TP: {order.tp:.{digits}f} (Move: {current_move:.{digits}f})")
                        print(f"       Target TP:  {new_tp:.{digits}f} (Move: {target_move:.{digits}f})")
                        should_adjust = True
                    else:
                        print(f"       ✅ TP already correct")
                        print(f"       TP: {order.tp:.{digits}f} | Risk: ${current_risk_usd:.2f}")
                        investor_orders_skipped += 1
                        stats["orders_skipped"] += 1
                        continue
                    
                    if should_adjust:
                        # Prepare modification request
                        modify_request = {
                            "action": mt5.TRADE_ACTION_MODIFY,
                            "order": order.ticket,
                            "price": order.price_open,
                            "sl": order.sl,
                            "tp": new_tp,
                        }
                        
                        # Send modification
                        result = mt5.order_send(modify_request)
                        
                        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                            investor_orders_adjusted += 1
                            stats["orders_adjusted"] += 1
                            print(f"       ✅ TP adjusted successfully to {new_tp:.{digits}f}")
                        else:
                            investor_orders_error += 1
                            stats["orders_error"] += 1
                            error_msg = result.comment if result else f"Error code: {result.retcode if result else 'Unknown'}"
                            print(f"       ❌ Modification failed: {error_msg}")
                else:
                    print(f"       ⚠️  Invalid tick values - using fallback calculation")
                    # Fallback method using profit calculation for a small price movement
                    try:
                        test_move = symbol_info.point * 10
                        if is_buy:
                            test_price = order.price_open + test_move
                        else:
                            test_price = order.price_open - test_move
                            
                        test_profit = mt5.order_calc_profit(calc_type, order.symbol, order.volume_initial, 
                                                            order.price_open, test_price)
                        
                        if test_profit and test_profit != 0:
                            point_value = abs(test_profit) / 10
                            price_move_needed = target_profit_usd / point_value * symbol_info.point
                            
                            digits = symbol_info.digits
                            price_move_needed = round(price_move_needed, digits)
                            
                            if is_buy:
                                new_tp = round(order.price_open + price_move_needed, digits)
                            else:
                                new_tp = round(order.price_open - price_move_needed, digits)
                            
                            print(f"       Using fallback calculation")
                            
                            if order.tp == 0 or abs(order.tp - new_tp) > symbol_info.point * 20:
                                modify_request = {
                                    "action": mt5.TRADE_ACTION_MODIFY,
                                    "order": order.ticket,
                                    "price": order.price_open,
                                    "sl": order.sl,
                                    "tp": new_tp,
                                }
                                
                                result = mt5.order_send(modify_request)
                                
                                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                                    investor_orders_adjusted += 1
                                    stats["orders_adjusted"] += 1
                                    print(f"       ✅ TP adjusted using fallback method to {new_tp:.{digits}f}")
                                else:
                                    investor_orders_error += 1
                                    stats["orders_error"] += 1
                                    print(f"       ❌ Fallback modification failed")
                            else:
                                investor_orders_skipped += 1
                                stats["orders_skipped"] += 1
                                print(f"       ✅ TP already correct (fallback check)")
                        else:
                            investor_orders_skipped += 1
                            stats["orders_skipped"] += 1
                            print(f"       ⚠️  Cannot calculate using fallback method")
                    except Exception as e:
                        investor_orders_error += 1
                        stats["orders_error"] += 1
                        print(f"       ❌ Fallback calculation error: {e}")

        # --- INVESTOR SUMMARY ---
        total_checked = investor_positions_checked + investor_orders_checked
        total_adjusted = investor_positions_adjusted + investor_orders_adjusted
        
        if total_checked > 0:
            print(f"\n  └─ 📊 Risk-Reward Correction Results for {user_brokerid}:")
            if investor_positions_checked > 0:
                print(f"       • Positions checked: {investor_positions_checked}")
                print(f"       • Positions adjusted: {investor_positions_adjusted}")
                print(f"       • Positions skipped: {investor_positions_skipped}")
            if investor_orders_checked > 0:
                print(f"       • Pending orders checked: {investor_orders_checked}")
                print(f"       • Pending orders adjusted: {investor_orders_adjusted}")
                print(f"       • Pending orders skipped: {investor_orders_skipped}")
            if investor_positions_error + investor_orders_error > 0:
                print(f"       • Errors: {investor_positions_error + investor_orders_error}")
            else:
                print(f"       ✅ All adjustments completed successfully")
            stats["processing_success"] = True
        else:
            print(f"  └─ 🔘 No positions or pending orders found.")

    # --- FINAL SUMMARY ---
    print(f"\n{'='*10} 📊 RISK-REWARD CORRECTION SUMMARY {'='*10}")
    print(f"   Investor ID: {stats['investor_id']}")
    print(f"   Positions checked: {stats['positions_checked']}")
    print(f"   Positions adjusted: {stats['positions_adjusted']}")
    print(f"   Pending orders checked: {stats['orders_checked']}")
    print(f"   Pending orders adjusted: {stats['orders_adjusted']}")
    print(f"   Total checked: {stats['positions_checked'] + stats['orders_checked']}")
    print(f"   Total adjusted: {stats['positions_adjusted'] + stats['orders_adjusted']}")
    print(f"   Orders skipped: {stats['orders_skipped']}")
    print(f"   Errors: {stats['orders_error']}")
    
    total_checked = stats['positions_checked'] + stats['orders_checked']
    total_adjusted = stats['positions_adjusted'] + stats['orders_adjusted']
    if total_checked > 0:
        success_rate = (total_adjusted / total_checked) * 100
        print(f"   Adjustment success rate: {success_rate:.1f}%")
    
    print(f"\n{'='*10} 🏁 POSITIONS & PENDING ORDERS RISK-REWARD CORRECTION COMPLETE {'='*10}\n")
    return stats

def orders_risk_correction(inv_id=None):
    """
    Function: Checks both live pending orders AND open positions (LIMIT, STOP, and MARKET)
    and adjusts their take profit levels based on the NEAREST MATCHING strategy risk-reward ratio.
    
    INTELLIGENT APPROACH:
    1. Calculate current R:R from order's exit/target prices
    2. Compare with strategy-specific R:R values from accountmanagement.json
    3. Find the nearest matching R:R (next higher value) and use that
    4. Fall back to default selected_risk_reward if no match found
    
    Args:
        inv_id: Optional specific investor ID to process. If None, processes all investors.
        
    Returns:
        dict: Statistics about the processing
    """
    print(f"\n{'='*10} 📐 INTELLIGENT R:R CORRECTION: FINDING NEAREST STRATEGY MATCH {'='*10}")
    if inv_id:
        print(f" Processing single investor: {inv_id}")

    # Track statistics
    stats = {
        "investor_id": inv_id if inv_id else "all",
        "orders_checked": 0,
        "orders_adjusted": 0,
        "orders_skipped": 0,
        "orders_error": 0,
        "positions_checked": 0,
        "positions_adjusted": 0,
        "rr_matches": {},  # Track which R:R ratios were used
        "rr_mismatches": 0,  # Track orders that didn't match any strategy
        "processing_success": False
    }

    # Determine which investors to process
    investors_to_process = [inv_id] if inv_id else usersdictionary.keys()
    total_investors = len(investors_to_process) if not inv_id else 1
    processed = 0

    for user_brokerid in investors_to_process:
        processed += 1
        print(f"\n[{processed}/{total_investors}] {user_brokerid} 🔍 Loading R:R configurations...")
        
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

        # --- LOAD CONFIG AND EXTRACT ALL AVAILABLE R:R VALUES ---
        try:
            with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Check if risk_reward_correction is enabled
            settings = config.get("settings", {})
            if not settings.get("risk_reward_correction", False):
                print(f"  └─ ⏭️  Risk-reward correction disabled in settings. Skipping.")
                continue
            
            # Get ALL available R:R values (both default and strategy-specific)
            all_rr_values = []
            
            # Add default selected_risk_reward
            selected_rr = config.get("selected_risk_reward", [2])
            if isinstance(selected_rr, list) and selected_rr:
                default_rr = float(selected_rr[0])
                all_rr_values.append(default_rr)
            else:
                default_rr = 2.0
                all_rr_values.append(default_rr)
            
            # Add all strategy-specific R:R values
            strategies_rr = config.get("strategies_risk_reward", {})
            strategy_rr_values = []
            for strategy, rr_value in strategies_rr.items():
                try:
                    rr_float = float(rr_value)
                    strategy_rr_values.append(rr_float)
                    all_rr_values.append(rr_float)
                except (ValueError, TypeError):
                    continue
            
            # Sort and deduplicate all available R:R values
            all_rr_values = sorted(set(all_rr_values))
            
            print(f"  └─ 📊 Default R:R: 1:{default_rr}")
            if strategy_rr_values:
                print(f"  └─ 📋 Strategy R:R values: {', '.join([f'1:{v}' for v in sorted(set(strategy_rr_values))])}")
            print(f"  └─ 🎯 All available R:R targets: {', '.join([f'1:{v}' for v in all_rr_values])}")
            
            # Get risk management mapping for balance-based risk
            risk_map = config.get("account_balance_default_risk_management", {})
            
        except Exception as e:
            print(f"  └─ ❌ Failed to read config: {e}")
            stats["orders_error"] += 1
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
                print(f"  └─ ❌  login failed: {error}")
                stats["orders_error"] += 1
                continue
            print(f"      ✅ Successfully logged into account")
        else:
            print(f"      ✅ Already logged into account")

        acc_info = mt5.account_info()
        if not acc_info:
            print(f"  └─ ❌ Failed to get account info")
            stats["orders_error"] += 1
            continue
            
        balance = acc_info.balance

        # Get terminal info for additional details
        term_info = mt5.terminal_info()
        
        print(f"\n  └─ 📊 Account Details:")
        print(f"      • Balance: ${acc_info.balance:,.2f}")
        print(f"      • Equity: ${acc_info.equity:,.2f}")
        print(f"      • Free Margin: ${acc_info.margin_free:,.2f}")
        print(f"      • Margin Level: {acc_info.margin_level:.2f}%" if acc_info.margin_level else "      • Margin Level: N/A")
        print(f"      • AutoTrading: {'✅ ENABLED' if term_info.trade_allowed else '❌ DISABLED'}")

        # --- DETERMINE PRIMARY RISK VALUE BASED ON BALANCE ---
        primary_risk = None
        for range_str, r_val in risk_map.items():
            try:
                raw_range = range_str.split("_")[0]
                low, high = map(float, raw_range.split("-"))
                if low <= balance <= high:
                    primary_risk = float(r_val)
                    break
            except Exception as e:
                print(f"  └─ ⚠️  Error parsing range '{range_str}': {e}")
                continue

        if primary_risk is None:
            print(f"  └─ ⚠️  No risk mapping for balance ${balance:,.2f}")
            stats["orders_skipped"] += 1
            continue

        print(f"\n  └─ 💰 Balance: ${balance:,.2f} | Base Risk: ${primary_risk:.2f}")

        # --- HELPER FUNCTION: Find nearest matching R:R ---
        def find_nearest_rr(current_rr, available_rr_values):
            """
            Find the nearest matching R:R value from available options.
            Prefers next higher value, but if none exists, uses the closest.
            """
            if not available_rr_values:
                return None, "none"
            
            # Sort available values
            sorted_values = sorted(available_rr_values)
            
            # Find the next higher value (preferred)
            next_higher = None
            for val in sorted_values:
                if val >= current_rr:
                    next_higher = val
                    break
            
            if next_higher is not None:
                return next_higher, "next_higher"
            
            # If no higher value, use the closest (should be the maximum)
            closest = min(sorted_values, key=lambda x: abs(x - current_rr))
            return closest, "closest"

        # --- CHECK AND ADJUST ALL POSITIONS (OPEN MARKET ORDERS) ---
        positions = mt5.positions_get()
        investor_positions_checked = 0
        investor_positions_adjusted = 0
        investor_positions_skipped = 0
        investor_positions_error = 0

        # Define MT5 position/order types for better readability
        POSITION_TYPES = {
            mt5.POSITION_TYPE_BUY: "BUY (MARKET)",
            mt5.POSITION_TYPE_SELL: "SELL (MARKET)"
        }
        
        ORDER_TYPES = {
            mt5.ORDER_TYPE_BUY_LIMIT: "BUY LIMIT",
            mt5.ORDER_TYPE_SELL_LIMIT: "SELL LIMIT",
            mt5.ORDER_TYPE_BUY_STOP: "BUY STOP",
            mt5.ORDER_TYPE_SELL_STOP: "SELL STOP",
            mt5.ORDER_TYPE_BUY_STOP_LIMIT: "BUY STOP-LIMIT",
            mt5.ORDER_TYPE_SELL_STOP_LIMIT: "SELL STOP-LIMIT"
        }

        # Process OPEN POSITIONS first
        if positions:
            print(f"\n  └─ 🔍 Scanning {len(positions)} open positions (MARKET)...")
            
            for position in positions:
                investor_positions_checked += 1
                stats["positions_checked"] += 1
                
                position_type_name = POSITION_TYPES.get(position.type, f"Unknown Type {position.type}")
                
                # Get symbol info
                symbol_info = mt5.symbol_info(position.symbol)
                if not symbol_info:
                    print(f"    └─ ⚠️  Cannot get symbol info for {position.symbol}")
                    investor_positions_skipped += 1
                    stats["orders_skipped"] += 1
                    continue

                # Determine position direction
                is_buy = position.type == mt5.POSITION_TYPE_BUY
                
                print(f"\n    └─ 📋 Position #{position.ticket} | {position_type_name} | {position.symbol}")
                
                # Calculate current risk (stop loss distance in money)
                if position.sl == 0:
                    print(f"       ⚠️  No SL set - cannot calculate risk. Skipping TP adjustment.")
                    investor_positions_skipped += 1
                    stats["orders_skipped"] += 1
                    continue
                
                # For positions, risk is from entry to SL
                if is_buy:
                    risk_distance = position.price_open - position.sl
                else:
                    risk_distance = position.sl - position.price_open
                
                # Calculate risk in money using MT5 profit calculator for accuracy
                calc_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
                sl_profit = mt5.order_calc_profit(calc_type, position.symbol, position.volume, 
                                                  position.price_open, position.sl)
                
                if sl_profit is not None:
                    current_risk_usd = round(abs(sl_profit), 2)
                else:
                    # Fallback calculation
                    risk_points = abs(risk_distance) / symbol_info.point
                    point_value = symbol_info.trade_tick_value / symbol_info.trade_tick_size * symbol_info.point
                    current_risk_usd = round(risk_points * point_value * position.volume, 2)
                
                # Calculate current R:R if TP exists
                current_rr = None
                if position.tp != 0:
                    if is_buy:
                        tp_distance = position.tp - position.price_open
                    else:
                        tp_distance = position.price_open - position.tp
                    
                    if risk_distance > 0:
                        current_rr = round(tp_distance / risk_distance, 2)
                        print(f"       Current R:R: 1:{current_rr}")
                    else:
                        current_rr = None
                
                # Find target R:R based on current value
                if current_rr is not None:
                    target_rr, match_type = find_nearest_rr(current_rr, all_rr_values)
                    
                    if match_type == "next_higher":
                        print(f"       🔍 Using next higher R:R: 1:{target_rr} (from 1:{current_rr})")
                    elif match_type == "closest":
                        print(f"       🔍 Using closest R:R: 1:{target_rr} (from 1:{current_rr}) - no higher value")
                    else:
                        target_rr = default_rr
                        print(f"       ℹ️  Using default R:R: 1:{target_rr}")
                    
                    # Track R:R usage
                    rr_key = str(target_rr)
                    if rr_key not in stats["rr_matches"]:
                        stats["rr_matches"][rr_key] = 0
                    stats["rr_matches"][rr_key] += 1
                else:
                    # If no current R:R, use default
                    target_rr = default_rr
                    print(f"       ℹ️  No current R:R found, using default: 1:{target_rr}")
                    stats["rr_mismatches"] += 1
                
                # Calculate required take profit based on risk and target R:R ratio
                target_profit_usd = current_risk_usd * target_rr
                
                print(f"       Risk: ${current_risk_usd:.2f} | Target Profit: ${target_profit_usd:.2f} (1:{target_rr})")
                
                # Calculate the take profit price that would achieve this profit
                tick_value = symbol_info.trade_tick_value
                tick_size = symbol_info.trade_tick_size
                
                if tick_value > 0 and tick_size > 0:
                    # Calculate how many ticks we need to move to achieve target profit
                    ticks_needed = target_profit_usd / (position.volume * tick_value)
                    
                    # Convert ticks to price movement
                    price_move_needed = ticks_needed * tick_size
                    
                    # Round to symbol digits
                    digits = symbol_info.digits
                    price_move_needed = round(price_move_needed, digits)
                    
                    # Calculate new take profit price based on position type (from entry price)
                    if is_buy:
                        new_tp = round(position.price_open + price_move_needed, digits)
                    else:
                        new_tp = round(position.price_open - price_move_needed, digits)
                    
                    # Check if current TP is significantly different from calculated TP
                    if position.tp == 0:
                        target_move = abs(new_tp - position.price_open)
                        print(f"       📝 No TP currently set")
                        print(f"       Target TP: {new_tp:.{digits}f} (Move from entry: {target_move:.{digits}f})")
                        should_adjust = True
                    else:
                        current_move = abs(position.tp - position.price_open)
                        target_move = abs(new_tp - position.price_open)
                        
                        # Calculate threshold (10% of target move or 2 pips, whichever is larger)
                        pip_threshold = max(target_move * 0.1, symbol_info.point * 20)
                        
                        if abs(current_move - target_move) > pip_threshold:
                            print(f"       📐 TP needs adjustment")
                            print(f"       Current TP: {position.tp:.{digits}f} (Move from entry: {current_move:.{digits}f})")
                            print(f"       Target TP:  {new_tp:.{digits}f} (Move from entry: {target_move:.{digits}f})")
                            should_adjust = True
                        else:
                            print(f"       ✅ TP already correct")
                            print(f"       TP: {position.tp:.{digits}f} | Risk: ${current_risk_usd:.2f}")
                            investor_positions_skipped += 1
                            stats["orders_skipped"] += 1
                            continue
                    
                    if should_adjust:
                        # Prepare modification request for position
                        modify_request = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "position": position.ticket,
                            "sl": position.sl,
                            "tp": new_tp,
                        }
                        
                        # Send modification
                        result = mt5.order_send(modify_request)
                        
                        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                            investor_positions_adjusted += 1
                            stats["positions_adjusted"] += 1
                            stats["orders_adjusted"] += 1
                            print(f"       ✅ TP adjusted successfully to {new_tp:.{digits}f} (Target R:R: 1:{target_rr})")
                        else:
                            investor_positions_error += 1
                            stats["orders_error"] += 1
                            error_msg = result.comment if result else f"Error code: {result.retcode if result else 'Unknown'}"
                            print(f"       ❌ Modification failed: {error_msg}")
                else:
                    print(f"       ⚠️  Invalid tick values - using fallback calculation")
                    # Fallback method using profit calculation for a small price movement
                    try:
                        test_move = symbol_info.point * 10
                        if is_buy:
                            test_price = position.price_open + test_move
                        else:
                            test_price = position.price_open - test_move
                            
                        test_profit = mt5.order_calc_profit(calc_type, position.symbol, position.volume, 
                                                            position.price_open, test_price)
                        
                        if test_profit and test_profit != 0:
                            point_value = abs(test_profit) / 10
                            price_move_needed = target_profit_usd / point_value * symbol_info.point
                            
                            digits = symbol_info.digits
                            price_move_needed = round(price_move_needed, digits)
                            
                            if is_buy:
                                new_tp = round(position.price_open + price_move_needed, digits)
                            else:
                                new_tp = round(position.price_open - price_move_needed, digits)
                            
                            print(f"       Using fallback calculation")
                            
                            if position.tp == 0 or abs(position.tp - new_tp) > symbol_info.point * 20:
                                modify_request = {
                                    "action": mt5.TRADE_ACTION_SLTP,
                                    "position": position.ticket,
                                    "sl": position.sl,
                                    "tp": new_tp,
                                }
                                
                                result = mt5.order_send(modify_request)
                                
                                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                                    investor_positions_adjusted += 1
                                    stats["positions_adjusted"] += 1
                                    stats["orders_adjusted"] += 1
                                    print(f"       ✅ TP adjusted using fallback method to {new_tp:.{digits}f}")
                                else:
                                    investor_positions_error += 1
                                    stats["orders_error"] += 1
                                    print(f"       ❌ Fallback modification failed")
                            else:
                                investor_positions_skipped += 1
                                stats["orders_skipped"] += 1
                                print(f"       ✅ TP already correct (fallback check)")
                        else:
                            investor_positions_skipped += 1
                            stats["orders_skipped"] += 1
                            print(f"       ⚠️  Cannot calculate using fallback method")
                    except Exception as e:
                        investor_positions_error += 1
                        stats["orders_error"] += 1
                        print(f"       ❌ Fallback calculation error: {e}")
        
        # --- CHECK AND ADJUST ALL PENDING ORDERS (LIMIT AND STOP) ---
        pending_orders = mt5.orders_get()
        investor_orders_checked = 0
        investor_orders_adjusted = 0
        investor_orders_skipped = 0
        investor_orders_error = 0

        if pending_orders:
            print(f"\n  └─ 🔍 Scanning {len(pending_orders)} pending orders (LIMIT & STOP)...")
            
            for order in pending_orders:
                # Skip if not a pending order (only process pending order types)
                if order.type not in ORDER_TYPES.keys():
                    continue

                investor_orders_checked += 1
                stats["orders_checked"] += 1
                
                order_type_name = ORDER_TYPES.get(order.type, f"Unknown Type {order.type}")
                
                # Get symbol info
                symbol_info = mt5.symbol_info(order.symbol)
                if not symbol_info:
                    print(f"    └─ ⚠️  Cannot get symbol info for {order.symbol}")
                    investor_orders_skipped += 1
                    stats["orders_skipped"] += 1
                    continue

                # Determine order direction for calculations
                is_buy = order.type in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP, mt5.ORDER_TYPE_BUY_STOP_LIMIT]
                calc_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
                
                print(f"\n    └─ 📋 Order #{order.ticket} | {order_type_name} | {order.symbol}")
                
                # Calculate current risk (stop loss distance in money)
                if order.sl == 0:
                    print(f"       ⚠️  No SL set - cannot calculate risk. Skipping TP adjustment.")
                    investor_orders_skipped += 1
                    stats["orders_skipped"] += 1
                    continue
                    
                # For pending orders, risk is from entry to SL
                sl_profit = mt5.order_calc_profit(calc_type, order.symbol, order.volume_initial, 
                                                  order.price_open, order.sl)
                
                if sl_profit is None:
                    print(f"       ⚠️  Cannot calculate risk. Skipping.")
                    investor_orders_skipped += 1
                    stats["orders_skipped"] += 1
                    continue

                current_risk_usd = round(abs(sl_profit), 2)
                
                # Calculate current R:R if TP exists
                current_rr = None
                if order.tp != 0:
                    if is_buy:
                        tp_distance = order.tp - order.price_open
                    else:
                        tp_distance = order.price_open - order.tp
                    
                    risk_distance = abs(order.sl - order.price_open)
                    if risk_distance > 0:
                        current_rr = round(tp_distance / risk_distance, 2)
                        print(f"       Current R:R: 1:{current_rr}")
                    else:
                        current_rr = None
                
                # Find target R:R based on current value
                if current_rr is not None:
                    target_rr, match_type = find_nearest_rr(current_rr, all_rr_values)
                    
                    if match_type == "next_higher":
                        print(f"       🔍 Using next higher R:R: 1:{target_rr} (from 1:{current_rr})")
                    elif match_type == "closest":
                        print(f"       🔍 Using closest R:R: 1:{target_rr} (from 1:{current_rr}) - no higher value")
                    else:
                        target_rr = default_rr
                        print(f"       ℹ️  Using default R:R: 1:{target_rr}")
                    
                    # Track R:R usage
                    rr_key = str(target_rr)
                    if rr_key not in stats["rr_matches"]:
                        stats["rr_matches"][rr_key] = 0
                    stats["rr_matches"][rr_key] += 1
                else:
                    # If no current R:R, use default
                    target_rr = default_rr
                    print(f"       ℹ️  No current R:R found, using default: 1:{target_rr}")
                    stats["rr_mismatches"] += 1
                
                # Calculate required take profit based on risk and target R:R ratio
                target_profit_usd = current_risk_usd * target_rr
                
                print(f"       Risk: ${current_risk_usd:.2f} | Target Profit: ${target_profit_usd:.2f} (1:{target_rr})")
                
                # Calculate the take profit price that would achieve this profit
                tick_value = symbol_info.trade_tick_value
                tick_size = symbol_info.trade_tick_size
                
                if tick_value > 0 and tick_size > 0:
                    # Calculate how many ticks we need to move to achieve target profit
                    ticks_needed = target_profit_usd / (order.volume_initial * tick_value)
                    
                    # Convert ticks to price movement
                    price_move_needed = ticks_needed * tick_size
                    
                    # Round to symbol digits
                    digits = symbol_info.digits
                    price_move_needed = round(price_move_needed, digits)
                    
                    # Calculate new take profit price based on order type
                    if is_buy:
                        new_tp = round(order.price_open + price_move_needed, digits)
                    else:
                        new_tp = round(order.price_open - price_move_needed, digits)
                    
                    # Check if current TP is significantly different from calculated TP
                    current_move = abs(order.tp - order.price_open) if order.tp != 0 else 0
                    target_move = abs(new_tp - order.price_open)
                    
                    # Calculate threshold (10% of target move or 2 pips, whichever is larger)
                    pip_threshold = max(target_move * 0.1, symbol_info.point * 20)
                    
                    should_adjust = False
                    
                    if order.tp == 0:
                        print(f"       📝 No TP currently set")
                        print(f"       Target TP: {new_tp:.{digits}f} (Move: {target_move:.{digits}f})")
                        should_adjust = True
                    elif abs(current_move - target_move) > pip_threshold:
                        print(f"       📐 TP needs adjustment")
                        print(f"       Current TP: {order.tp:.{digits}f} (Move: {current_move:.{digits}f})")
                        print(f"       Target TP:  {new_tp:.{digits}f} (Move: {target_move:.{digits}f})")
                        should_adjust = True
                    else:
                        print(f"       ✅ TP already correct")
                        print(f"       TP: {order.tp:.{digits}f} | Risk: ${current_risk_usd:.2f}")
                        investor_orders_skipped += 1
                        stats["orders_skipped"] += 1
                        continue
                    
                    if should_adjust:
                        # Prepare modification request
                        modify_request = {
                            "action": mt5.TRADE_ACTION_MODIFY,
                            "order": order.ticket,
                            "price": order.price_open,
                            "sl": order.sl,
                            "tp": new_tp,
                        }
                        
                        # Send modification
                        result = mt5.order_send(modify_request)
                        
                        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                            investor_orders_adjusted += 1
                            stats["orders_adjusted"] += 1
                            print(f"       ✅ TP adjusted successfully to {new_tp:.{digits}f} (Target R:R: 1:{target_rr})")
                        else:
                            investor_orders_error += 1
                            stats["orders_error"] += 1
                            error_msg = result.comment if result else f"Error code: {result.retcode if result else 'Unknown'}"
                            print(f"       ❌ Modification failed: {error_msg}")
                else:
                    print(f"       ⚠️  Invalid tick values - using fallback calculation")
                    # Fallback method using profit calculation for a small price movement
                    try:
                        test_move = symbol_info.point * 10
                        if is_buy:
                            test_price = order.price_open + test_move
                        else:
                            test_price = order.price_open - test_move
                            
                        test_profit = mt5.order_calc_profit(calc_type, order.symbol, order.volume_initial, 
                                                            order.price_open, test_price)
                        
                        if test_profit and test_profit != 0:
                            point_value = abs(test_profit) / 10
                            price_move_needed = target_profit_usd / point_value * symbol_info.point
                            
                            digits = symbol_info.digits
                            price_move_needed = round(price_move_needed, digits)
                            
                            if is_buy:
                                new_tp = round(order.price_open + price_move_needed, digits)
                            else:
                                new_tp = round(order.price_open - price_move_needed, digits)
                            
                            print(f"       Using fallback calculation")
                            
                            if order.tp == 0 or abs(order.tp - new_tp) > symbol_info.point * 20:
                                modify_request = {
                                    "action": mt5.TRADE_ACTION_MODIFY,
                                    "order": order.ticket,
                                    "price": order.price_open,
                                    "sl": order.sl,
                                    "tp": new_tp,
                                }
                                
                                result = mt5.order_send(modify_request)
                                
                                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                                    investor_orders_adjusted += 1
                                    stats["orders_adjusted"] += 1
                                    print(f"       ✅ TP adjusted using fallback method to {new_tp:.{digits}f}")
                                else:
                                    investor_orders_error += 1
                                    stats["orders_error"] += 1
                                    print(f"       ❌ Fallback modification failed")
                            else:
                                investor_orders_skipped += 1
                                stats["orders_skipped"] += 1
                                print(f"       ✅ TP already correct (fallback check)")
                        else:
                            investor_orders_skipped += 1
                            stats["orders_skipped"] += 1
                            print(f"       ⚠️  Cannot calculate using fallback method")
                    except Exception as e:
                        investor_orders_error += 1
                        stats["orders_error"] += 1
                        print(f"       ❌ Fallback calculation error: {e}")

        # --- INVESTOR SUMMARY ---
        total_checked = investor_positions_checked + investor_orders_checked
        total_adjusted = investor_positions_adjusted + investor_orders_adjusted
        
        if total_checked > 0:
            print(f"\n  └─ 📊 Intelligent R:R Correction Results for {user_brokerid}:")
            if investor_positions_checked > 0:
                print(f"       • Positions checked: {investor_positions_checked}")
                print(f"       • Positions adjusted: {investor_positions_adjusted}")
                print(f"       • Positions skipped: {investor_positions_skipped}")
            if investor_orders_checked > 0:
                print(f"       • Pending orders checked: {investor_orders_checked}")
                print(f"       • Pending orders adjusted: {investor_orders_adjusted}")
                print(f"       • Pending orders skipped: {investor_orders_skipped}")
            if investor_positions_error + investor_orders_error > 0:
                print(f"       • Errors: {investor_positions_error + investor_orders_error}")
            else:
                print(f"       ✅ All adjustments completed successfully")
            stats["processing_success"] = True
        else:
            print(f"  └─ 🔘 No positions or pending orders found.")

    # --- FINAL SUMMARY ---
    print(f"\n{'='*10} 📊 INTELLIGENT R:R CORRECTION SUMMARY {'='*10}")
    print(f"   Investor ID: {stats['investor_id']}")
    print(f"   Positions checked: {stats['positions_checked']}")
    print(f"   Positions adjusted: {stats['positions_adjusted']}")
    print(f"   Pending orders checked: {stats['orders_checked']}")
    print(f"   Pending orders adjusted: {stats['orders_adjusted']}")
    print(f"   Total checked: {stats['positions_checked'] + stats['orders_checked']}")
    print(f"   Total adjusted: {stats['positions_adjusted'] + stats['orders_adjusted']}")
    print(f"   Orders skipped: {stats['orders_skipped']}")
    print(f"   Errors: {stats['orders_error']}")
    
    if stats["rr_matches"]:
        print(f"\n   📊 R:R Usage Breakdown:")
        for rr, count in sorted(stats["rr_matches"].items()):
            print(f"       • 1:{rr}: {count} orders")
    if stats["rr_mismatches"] > 0:
        print(f"   ⚠️  Orders using default R:R (no match): {stats['rr_mismatches']}")
    
    total_checked = stats['positions_checked'] + stats['orders_checked']
    total_adjusted = stats['positions_adjusted'] + stats['orders_adjusted']
    if total_checked > 0:
        success_rate = (total_adjusted / total_checked) * 100
        print(f"   Adjustment success rate: {success_rate:.1f}%")
    
    print(f"\n{'='*10} 🏁 INTELLIGENT R:R CORRECTION COMPLETE {'='*10}\n")
    return stats

def history_closed_orders_removal_in_pendingorders(inv_id=None):
    """
    Scans history for the last 48 hours. If a position was closed, 
    any pending limit orders with the same first 4 digits in the price 
    are cancelled to prevent re-entry.
    
    Args:
        inv_id (str, optional): Specific investor ID to process. If None, processes all investors.
        MT5 should already be initialized and logged in for this investor.
    
    Returns:
        bool: True if any orders were removed, False otherwise
    """
    from datetime import datetime, timedelta
    print(f"\n{'='*10} 📜 HISTORY AUDIT: PREVENTING RE-ENTRY {'='*10}")

    # Determine which investors to process
    if inv_id:
        investor_ids = [inv_id]
    else:
        investor_ids = list(usersdictionary.keys())
    
    if not investor_ids:
        print(" └─ 🔘 No investors found.")
        return False

    any_orders_removed = False

    for user_brokerid in investor_ids:
        print(f" [{user_brokerid}] 🔍 Checking 48h history for duplicates...")
        
        broker_cfg = usersdictionary.get(user_brokerid)
        if not broker_cfg:
            print(f"  └─ ❌ No broker config found for {user_brokerid}")
            continue

        # 1. Define the 48-hour window
        from_date = datetime.now() - timedelta(hours=48)
        to_date = datetime.now()

        # 2. Get Closed Positions (Deals)
        history_deals = mt5.history_deals_get(from_date, to_date)
        if history_deals is None:
            print(f"  └─ ⚠️ Could not access history for {user_brokerid}")
            continue

        # 3. Create a set of "Used Price Prefixes"
        # We store: (symbol, price_prefix)
        used_entries = set()
        for deal in history_deals:
            # Only look at actual trades (buy/sell) that were closed
            if deal.entry in [mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT]:
                # Extract first 3 significant digits of the price
                # We remove the decimal to handle 0.856 and 1901 uniformly
                clean_price = str(deal.price).replace('.', '')[:4]
                used_entries.add((deal.symbol, clean_price))

        if not used_entries:
            print(f"  └─ ✅ No closed orders found in last 48h.")
            continue

        # 4. Check Current Pending Orders
        pending_orders = mt5.orders_get()
        removed_count = 0
        orders_checked = 0

        if pending_orders:
            for order in pending_orders:
                # Only target limit orders
                if order.type in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_SELL_LIMIT]:
                    orders_checked += 1
                    order_price_prefix = str(order.price_open).replace('.', '')[:4]
                    
                    # If this symbol + price prefix exists in history, kill the order
                    if (order.symbol, order_price_prefix) in used_entries:
                        print(f"  └─ 🚫 DUPLICATE FOUND: {order.symbol} at {order.price_open}")
                        print(f"     Match found in history (Prefix: {order_price_prefix}). Cancelling...")
                        
                        cancel_request = {
                            "action": mt5.TRADE_ACTION_REMOVE,
                            "order": order.ticket
                        }
                        res = mt5.order_send(cancel_request)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            removed_count += 1
                            any_orders_removed = True
                            print(f"     ✅ Order #{order.ticket} cancelled successfully")
                        else:
                            error_msg = res.comment if res else f"Error code: {res.retcode if res else 'Unknown'}"
                            print(f"     ❌ Failed to cancel #{order.ticket}: {error_msg}")

        print(f"  └─ 📊 Cleanup Result: {removed_count} duplicate limit orders removed out of {orders_checked} checked.")

    print(f"\n{'='*10} 🏁 HISTORY AUDIT COMPLETE {'='*10}\n")
    return any_orders_removed

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

def history_closed_orders_removal_in_pendingorders(inv_id=None):
    """
    Scans history for the last 48 hours. If a position was closed, 
    any pending limit orders with the same first 4 digits in the price 
    are cancelled to prevent re-entry.
    
    Args:
        inv_id (str, optional): Specific investor ID to process. If None, processes all investors.
        MT5 should already be initialized and logged in for this investor.
    
    Returns:
        bool: True if any orders were removed, False otherwise
    """
    from datetime import datetime, timedelta
    print(f"\n{'='*10} 📜 HISTORY AUDIT: PREVENTING RE-ENTRY {'='*10}")

    # Determine which investors to process
    if inv_id:
        investor_ids = [inv_id]
    else:
        investor_ids = list(usersdictionary.keys())
    
    if not investor_ids:
        print(" └─ 🔘 No investors found.")
        return False

    any_orders_removed = False

    for user_brokerid in investor_ids:
        print(f" [{user_brokerid}] 🔍 Checking 48h history for duplicates...")
        
        broker_cfg = usersdictionary.get(user_brokerid)
        if not broker_cfg:
            print(f"  └─ ❌ No broker config found for {user_brokerid}")
            continue

        # 1. Define the 48-hour window
        from_date = datetime.now() - timedelta(hours=48)
        to_date = datetime.now()

        # 2. Get Closed Positions (Deals)
        history_deals = mt5.history_deals_get(from_date, to_date)
        if history_deals is None:
            print(f"  └─ ⚠️ Could not access history for {user_brokerid}")
            continue

        # 3. Create a set of "Used Price Prefixes"
        # We store: (symbol, price_prefix)
        used_entries = set()
        for deal in history_deals:
            # Only look at actual trades (buy/sell) that were closed
            if deal.entry in [mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT]:
                # Extract first 3 significant digits of the price
                # We remove the decimal to handle 0.856 and 1901 uniformly
                clean_price = str(deal.price).replace('.', '')[:4]
                used_entries.add((deal.symbol, clean_price))

        if not used_entries:
            print(f"  └─ ✅ No closed orders found in last 48h.")
            continue

        # 4. Check Current Pending Orders
        pending_orders = mt5.orders_get()
        removed_count = 0
        orders_checked = 0

        if pending_orders:
            for order in pending_orders:
                # Only target limit orders
                if order.type in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_SELL_LIMIT]:
                    orders_checked += 1
                    order_price_prefix = str(order.price_open).replace('.', '')[:4]
                    
                    # If this symbol + price prefix exists in history, kill the order
                    if (order.symbol, order_price_prefix) in used_entries:
                        print(f"  └─ 🚫 DUPLICATE FOUND: {order.symbol} at {order.price_open}")
                        print(f"     Match found in history (Prefix: {order_price_prefix}). Cancelling...")
                        
                        cancel_request = {
                            "action": mt5.TRADE_ACTION_REMOVE,
                            "order": order.ticket
                        }
                        res = mt5.order_send(cancel_request)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            removed_count += 1
                            any_orders_removed = True
                            print(f"     ✅ Order #{order.ticket} cancelled successfully")
                        else:
                            error_msg = res.comment if res else f"Error code: {res.retcode if res else 'Unknown'}"
                            print(f"     ❌ Failed to cancel #{order.ticket}: {error_msg}")

        print(f"  └─ 📊 Cleanup Result: {removed_count} duplicate limit orders removed out of {orders_checked} checked.")

    print(f"\n{'='*10} 🏁 HISTORY AUDIT COMPLETE {'='*10}\n")
    return any_orders_removed

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

def update_investor_info(inv_id=None):
    """
    Updates investor information in UPDATED_INVESTORS.json including:
    - Balance at execution start date
    - P&L from authorized trades only
    - Trade statistics (won/lost) with negative signs for losses
    - Detailed authorized closed trades list (with buy/sell type)
    - Unauthorized actions detection
    
    Investors with unauthorized actions (and no bypass) are moved to issues_investors.json
    When investors are added to updated_investors.json, their application_status is set to "approved"
    """
    print("\n" + "="*80)
    print("📊 UPDATING INVESTOR INFORMATION")
    print("="*80)
    
    updated_investors_path = Path(UPDATED_INVESTORS)
    issues_investors_path = Path(ISSUES_INVESTORS)
    
    if updated_investors_path.exists():
        try:
            with open(updated_investors_path, 'r', encoding='utf-8') as f:
                updated_investors = json.load(f)
        except:
            updated_investors = {}
    else:
        updated_investors = {}
    
    # Load existing issues investors
    if issues_investors_path.exists():
        try:
            with open(issues_investors_path, 'r', encoding='utf-8') as f:
                issues_investors = json.load(f)
        except:
            issues_investors = {}
    else:
        issues_investors = {}
    
    investor_ids = [inv_id] if inv_id else list(usersdictionary.keys())
    
    for user_brokerid in investor_ids:
        print(f"\n📋 INVESTOR: {user_brokerid} Current Info")
        print("-" * 60)
        
        if user_brokerid not in usersdictionary:
            print(f"  ❌ Investor {user_brokerid} not found in usersdictionary")
            continue
            
        base_info = usersdictionary[user_brokerid].copy()
        inv_root = Path(INV_PATH) / user_brokerid
        
        if not inv_root.exists():
            print(f"  ❌ Path not found: {inv_root}")
            continue
        
        # Initialize aggregated data
        total_authorized_pnl = 0.0
        authorized_closed_trades_list = []
        won_trades = 0
        lost_trades = 0
        symbols_lost = {}
        symbols_won = {}
        execution_start_date = None
        starting_balance = None
        unauthorized_detected = False
        bypass_active = False
        autotrading_active = False
        unauthorized_type = set()
        unauthorized_trades_list = []
        unauthorized_withdrawals_list = []
        authorized_tickets = set()
        
        # Look for activities.json directly in investor root folder
        activities_path = inv_root / "activities.json"
        if activities_path.exists():
            try:
                with open(activities_path, 'r', encoding='utf-8') as f:
                    activities = json.load(f)
                
                # Check authorization status using same logic as place_usd_orders
                unauthorized_detected = activities.get('unauthorized_action_detected', False)
                bypass_active = activities.get('bypass_restriction', False)
                autotrading_active = activities.get('activate_autotrading', False)
                
                if unauthorized_detected:
                    unauthorized_trades = activities.get('unauthorized_trades', {})
                    if unauthorized_trades:
                        unauthorized_type.add('trades')
                        for ticket_key, trade in unauthorized_trades.items():
                            unauthorized_trades_list.append({
                                'ticket': trade.get('ticket'),
                                'symbol': trade.get('symbol'),
                                'type': trade.get('type'),
                                'volume': trade.get('volume'),
                                'profit': round(float(trade.get('profit', 0)), 2),
                                'time': trade.get('time'),
                                'reason': trade.get('reason')
                            })
                    unauthorized_withdrawals = activities.get('unauthorized_withdrawals', {})
                    if unauthorized_withdrawals:
                        unauthorized_type.add('withdrawal')
                        for wd_key, withdrawal in unauthorized_withdrawals.items():
                            unauthorized_withdrawals_list.append({
                                'ticket': withdrawal.get('ticket'),
                                'amount': withdrawal.get('amount'),
                                'time': withdrawal.get('time'),
                                'comment': withdrawal.get('comment')
                            })
                
                execution_start_date = activities.get('execution_start_date')
                print(f"    📋 Found activities.json with execution_start_date: {execution_start_date}")
            except Exception as e:
                print(f"    ⚠️  Error reading activities.json: {e}")
        else:
            print(f"    ⚠️  activities.json not found in {inv_root}")
        
        # Look for tradeshistory.json directly in investor root folder
        history_path = inv_root / "tradeshistory.json"
        if history_path.exists():
            try:
                with open(history_path, 'r', encoding='utf-8') as f:
                    authorized_trades = json.load(f)
                for trade in authorized_trades:
                    if 'ticket' in trade and trade['ticket']:
                        authorized_tickets.add(int(trade['ticket']))
                print(f"    📋 Found {len(authorized_tickets)} authorized tickets in tradeshistory.json")
            except Exception as e:
                print(f"    ⚠️  Error reading tradeshistory.json: {e}")
        else:
            print(f"    ⚠️  tradeshistory.json not found in {inv_root}")

        # Fallback to accountmanagement.json if execution_start_date not found
        if not execution_start_date:
            acc_mgmt_path = inv_root / "accountmanagement.json"
            if acc_mgmt_path.exists():
                try:
                    with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                        acc_mgmt = json.load(f)
                    execution_start_date = acc_mgmt.get('execution_start_date')
                    print(f"    📋 Found execution_start_date in accountmanagement.json: {execution_start_date}")
                except: pass
        
        if execution_start_date:
            try:
                start_datetime = None
                for date_format in ["%B %d, %Y", "%Y-%m-%d"]:
                    try:
                        start_datetime = datetime.strptime(execution_start_date, date_format)
                        start_datetime = start_datetime.replace(hour=0, minute=0, second=0)
                        break
                    except: continue
                
                if start_datetime:
                    print(f"    🔍 Looking for trades from: {start_datetime.strftime('%Y-%m-%d')}")
                    all_deals = mt5.history_deals_get(start_datetime, datetime.now())
                    
                    if all_deals and len(all_deals) > 0:
                        all_deals = sorted(list(all_deals), key=lambda x: x.time)
                        total_profit_all_trades = 0
                        
                        for deal in all_deals:
                            if deal.type in [0, 1]:  # 0=BUY, 1=SELL
                                total_profit_all_trades += deal.profit
                                symbol = deal.symbol if hasattr(deal, 'symbol') else 'Unknown'
                                
                                # Process ONLY authorized trades for the summary and stats
                                if deal.ticket in authorized_tickets:
                                    total_authorized_pnl += deal.profit
                                    
                                    authorized_closed_trades_list.append({
                                        'ticket': deal.ticket,
                                        'symbol': symbol,
                                        'type': 'BUY' if deal.type == 0 else 'SELL',
                                        'volume': deal.volume,
                                        'profit': round(deal.profit, 2),
                                        'time': datetime.fromtimestamp(deal.time).strftime('%Y-%m-%d %H:%M:%S')
                                    })
                                    
                                    if deal.profit > 0:
                                        won_trades += 1
                                        symbols_won[symbol] = symbols_won.get(symbol, 0.0) + deal.profit
                                    elif deal.profit < 0:
                                        lost_trades += 1
                                        # Keep the negative sign for losses in summary
                                        symbols_lost[symbol] = symbols_lost.get(symbol, 0.0) + deal.profit
                                else:
                                    # Process as unauthorized
                                    ticket_exists = any(t.get('ticket') == deal.ticket for t in unauthorized_trades_list)
                                    if not ticket_exists:
                                        unauthorized_trades_list.append({
                                            'ticket': deal.ticket,
                                            'symbol': symbol,
                                            'type': 'BUY' if deal.type == 0 else 'SELL',
                                            'volume': deal.volume,
                                            'profit': round(deal.profit, 2),
                                            'time': datetime.fromtimestamp(deal.time).strftime('%Y-%m-%d %H:%M:%S'),
                                            'reason': f"Trade NOT in tradeshistory.json (Ticket: {deal.ticket})"
                                        })
                                        if 'trades' not in unauthorized_type: unauthorized_type.add('trades')
                                        unauthorized_detected = True
                        
                        account_info = mt5.account_info()
                        if account_info:
                            starting_balance = account_info.balance - total_profit_all_trades
                            print(f"    ✅ Calculated starting balance: ${starting_balance:.2f}")
                            print(f"       Current balance: ${account_info.balance:.2f}")
                            print(f"       Total profits all trades: ${total_profit_all_trades:.2f}")
                            print(f"       Authorized trades P&L: ${total_authorized_pnl:.2f}")
                    else:
                        account_info = mt5.account_info()
                        if account_info:
                            starting_balance = account_info.balance
                            print(f"    ✅ No trades since start, using current balance: ${starting_balance:.2f}")
            except Exception as e:
                print(f"    ⚠️  Error getting starting balance: {e}")

        # Build Structured Trades Dict with Negative signs preserved
        trades_info = {
            "summary": {
                "total_trades": len(authorized_closed_trades_list),
                "won": won_trades,
                "lost": lost_trades,
                "symbols_that_lost": {k: round(v, 2) for k, v in symbols_lost.items()},
                "symbols_that_won": {k: round(v, 2) for k, v in symbols_won.items()}
            },
            "authorized_closed_trades": authorized_closed_trades_list
        }

        # Contract days logic
        contract_days_left = "30"
        if execution_start_date:
            try:
                start = None
                for fmt in ["%Y-%m-%d", "%B %d, %Y"]:
                    try: 
                        start = datetime.strptime(execution_start_date, fmt)
                        break
                    except: continue
                if start:
                    days_passed = (datetime.now() - start).days
                    contract_days_left = str(max(0, 30 - days_passed))
            except: pass

        investor_info = {
            "id": user_brokerid,
            "server": base_info.get("SERVER", base_info.get("server", "")),
            "login": base_info.get("LOGIN_ID", base_info.get("login", "")),
            "password": base_info.get("PASSWORD", base_info.get("password", "")),
            "application_status": base_info.get("application_status", "pending"),
            "broker_balance": round(starting_balance, 2) if starting_balance is not None else None,
            "profitandloss": round(total_authorized_pnl, 2),
            "contract_days_left": contract_days_left,
            "execution_start_date": execution_start_date if execution_start_date else "",
            "trades": trades_info,
            "unauthorized_actions": {
                "detected": unauthorized_detected,
                "bypass_active": bypass_active,
                "autotrading_active": autotrading_active,
                "type": list(unauthorized_type) if unauthorized_type else [],
                "unauthorized_trades": unauthorized_trades_list,
                "unauthorized_withdrawals": unauthorized_withdrawals_list
            }
        }
        
        # --- CRITICAL: Check if investor should be moved to issues ---
        # Using the EXACT same logic as place_usd_orders:
        # From place_usd_orders:
        # if unauthorized_detected:
        #     if bypass_active:
        #         # proceed with order placement
        #     else:
        #         # block orders
        #
        # Therefore:
        # - If unauthorized_detected AND bypass_active → keep in updated_investors
        # - If unauthorized_detected AND NOT bypass_active → move to issues_investors
        
        should_move_to_issues = False
        issue_message = ""
        
        if unauthorized_detected:
            if bypass_active:
                # Bypass active - keep in updated investors (same as place_usd_orders allowing orders)
                print(f"  ⚠️  Unauthorized actions detected but BYPASS ACTIVE - keeping in updated_investors.json")
                should_move_to_issues = False
            else:
                # No bypass - move to issues (same as place_usd_orders blocking orders)
                should_move_to_issues = True
                issue_message = "Unauthorized action detected - restricted (bypass inactive)"
        
        if should_move_to_issues:
            print(f"  ⛔ Investor has unauthorized actions without bypass - MOVING TO ISSUES INVESTORS")
            print(f"      Message: {issue_message}")
            
            # Add message to investor info
            investor_info['MESSAGE'] = issue_message
            
            # Remove from updated_investors if exists
            if user_brokerid in updated_investors:
                del updated_investors[user_brokerid]
            
            # Add to issues_investors
            issues_investors[user_brokerid] = investor_info
            
        else:
            # Investor is clean or has bypass - add to updated investors
            # Set application_status to "approved" for investors in updated_investors
            investor_info['application_status'] = "approved"
            
            print(f"\n  📊 INVESTOR SUMMARY (added to updated_investors.json with status: APPROVED):")
            print(f"    • Starting Balance: ${investor_info['broker_balance'] if investor_info['broker_balance'] else 0.0:.2f}")
            print(f"    • Authorized P&L: ${investor_info['profitandloss']:.2f}")
            print(f"    • Authorized Trade Stats: {won_trades} Won / {lost_trades} Lost")
            print(f"    • Unauthorized: {'YES (BYPASS ACTIVE)' if unauthorized_detected else 'NO'}")
            print(f"    • Application Status: {investor_info['application_status']}")
            
            updated_investors[user_brokerid] = investor_info

    # Save updated_investors.json
    try:
        with open(updated_investors_path, 'w', encoding='utf-8') as f:
            json.dump(updated_investors, f, indent=4)
    except Exception as e:
        print(f"\n❌ Failed to save updated_investors.json: {e}")
    
    # Save issues_investors.json
    try:
        with open(issues_investors_path, 'w', encoding='utf-8') as f:
            json.dump(issues_investors, f, indent=4)
    except Exception as e:
        print(f"\n❌ Failed to save issues_investors.json: {e}")
    
    print("\n" + "="*80)
    print("✅ INVESTOR INFORMATION UPDATE COMPLETE")
    print("="*80)
    
    return updated_investors

# real accounts 
def process_single_investor(inv_id):
    """
    WORKER FUNCTION: Handles the entire pipeline for ONE investor ID.
    """
    account_stats = {"inv_id": inv_id, "success": False}
    
    try:
        with open(INVESTOR_USERS, 'r') as f:
            investor_users = json.load(f)
        broker_cfg = investor_users.get(inv_id)
    except Exception as e:
        print(f" [{inv_id}] ❌ JSON Read Error: {e}")
        return account_stats

    if not broker_cfg:
        return account_stats

    # Small jitter to prevent OS file-lock collisions when launching multiple .exe files
    time.sleep(random.uniform(0.1, 1.5)) 
    
    login_id = int(broker_cfg['LOGIN_ID'])
    mt5_path = broker_cfg["TERMINAL_PATH"]
    
    try:
        # Increase timeout slightly but keep it non-blocking for other processes
        # If this fails, it only kills this specific worker.
        if not mt5.initialize(path=mt5_path, timeout=60000): # 60 sec limit
            print(f" [{inv_id}] ❌ MT5 Init Timeout/Failed")
            
            # --- MOVE TO ISSUES_INVESTORS ON INIT FAILURE ---
            print(f"  ❌ Moving investor {inv_id} to issues_investors.json due to MT5 initialization failure")
            
            if os.path.exists(INVESTOR_USERS):
                with open(INVESTOR_USERS, 'r', encoding='utf-8') as f:
                    investors_data = json.load(f)
                
                investor_data_to_move = None
                if isinstance(investors_data, list):
                    for i, inv in enumerate(investors_data):
                        if inv_id in inv:
                            investor_data_to_move = inv[inv_id]
                            investors_data.pop(i)
                            break
                else:
                    if inv_id in investors_data:
                        investor_data_to_move = investors_data[inv_id]
                        del investors_data[inv_id]
                
                if investor_data_to_move:
                    # Specific message for MT5 initialization failure
                    investor_data_to_move['MESSAGE'] = "invalid broker login please check your login details"
                    
                    with open(INVESTOR_USERS, 'w', encoding='utf-8') as f:
                        json.dump(investors_data, f, indent=4)
                    
                    issues_data = {}
                    if os.path.exists(ISSUES_INVESTORS):
                        try:
                            with open(ISSUES_INVESTORS, 'r', encoding='utf-8') as f:
                                issues_data = json.load(f)
                        except: issues_data = {}
                    
                    issues_data[inv_id] = investor_data_to_move
                    with open(ISSUES_INVESTORS, 'w', encoding='utf-8') as f:
                        json.dump(issues_data, f, indent=4)
                    
                    print(f"  ✅ Successfully moved investor {inv_id} to issues_investors.json")
                else:
                    print(f"  ⚠️  Investor {inv_id} not found in investors.json")
            
            mt5.shutdown()
            return account_stats

        if not mt5.login(login_id, password=broker_cfg["PASSWORD"], server=broker_cfg["SERVER"]):
            print(f" [{inv_id}] ❌ Login failed")
            
            # --- MOVE TO ISSUES_INVESTORS ON LOGIN FAILURE ---
            print(f"  ❌ Moving investor {inv_id} to issues_investors.json due to login failure")
            
            if os.path.exists(INVESTOR_USERS):
                with open(INVESTOR_USERS, 'r', encoding='utf-8') as f:
                    investors_data = json.load(f)
                
                investor_data_to_move = None
                if isinstance(investors_data, list):
                    for i, inv in enumerate(investors_data):
                        if inv_id in inv:
                            investor_data_to_move = inv[inv_id]
                            investors_data.pop(i)
                            break
                else:
                    if inv_id in investors_data:
                        investor_data_to_move = investors_data[inv_id]
                        del investors_data[inv_id]
                
                if investor_data_to_move:
                    # Specific message for login failure
                    investor_data_to_move['MESSAGE'] = "invalid broker login please check your login details"
                    
                    with open(INVESTOR_USERS, 'w', encoding='utf-8') as f:
                        json.dump(investors_data, f, indent=4)
                    
                    issues_data = {}
                    if os.path.exists(ISSUES_INVESTORS):
                        try:
                            with open(ISSUES_INVESTORS, 'r', encoding='utf-8') as f:
                                issues_data = json.load(f)
                        except: issues_data = {}
                    
                    issues_data[inv_id] = investor_data_to_move
                    with open(ISSUES_INVESTORS, 'w', encoding='utf-8') as f:
                        json.dump(issues_data, f, indent=4)
                    
                    print(f"  ✅ Successfully moved investor {inv_id} to issues_investors.json")
                else:
                    print(f"  ⚠️  Investor {inv_id} not found in investors.json")
            
            mt5.shutdown()
            return account_stats

        # --- EXECUTION PIPELINE ---
        # If any of these functions have internal delays, they won't affect other investors
        get_requirements(inv_id=inv_id)
        detect_unauthorized_action(inv_id=inv_id)
        accountmanagement_manager(inv_id=inv_id)
        deduplicate_orders(inv_id=inv_id)
        filter_unauthorized_symbols(inv_id=inv_id)
        filter_unauthorized_timeframes(inv_id=inv_id)
        backup_limit_orders(inv_id=inv_id)
        populate_orders_missing_fields(inv_id=inv_id)
        activate_usd_based_risk_on_empty_pricelevels(inv_id=inv_id)
        enforce_investors_risk(inv_id=inv_id)
        calculate_investor_symbols_orders(inv_id=inv_id)
        padding_tight_usd_risk(inv_id=inv_id)
        live_usd_risk_and_scaling(inv_id=inv_id)
        apply_default_prices(inv_id=inv_id)
        place_usd_orders(inv_id=inv_id)
        orders_risk_correction(inv_id=inv_id)
        check_pending_orders_risk(inv_id=inv_id)
        history_closed_orders_removal_in_pendingorders(inv_id=inv_id)
        apply_dynamic_breakeven(inv_id=inv_id)
        update_investor_info(inv_id=inv_id)

        mt5.shutdown()
        account_stats["success"] = True
        print(f" [{inv_id}] ✅ Processed Successfully")
        
    except Exception as e:
        print(f" [{inv_id}] ❌ Pipeline Error: {e}")
        
        # --- MOVE TO ISSUES_INVESTORS ON ANY UNEXPECTED ERROR ---
        print(f"  ❌ Moving investor {inv_id} to issues_investors.json due to unexpected error: {e}")
        
        try:
            if os.path.exists(INVESTOR_USERS):
                with open(INVESTOR_USERS, 'r', encoding='utf-8') as f:
                    investors_data = json.load(f)
                
                investor_data_to_move = None
                if isinstance(investors_data, list):
                    for i, inv in enumerate(investors_data):
                        if inv_id in inv:
                            investor_data_to_move = inv[inv_id]
                            investors_data.pop(i)
                            break
                else:
                    if inv_id in investors_data:
                        investor_data_to_move = investors_data[inv_id]
                        del investors_data[inv_id]
                
                if investor_data_to_move:
                    # Generic message for unexpected errors
                    investor_data_to_move['MESSAGE'] = f"unexpected error: {str(e)[:100]}"  # Truncate long errors
                    
                    with open(INVESTOR_USERS, 'w', encoding='utf-8') as f:
                        json.dump(investors_data, f, indent=4)
                    
                    issues_data = {}
                    if os.path.exists(ISSUES_INVESTORS):
                        try:
                            with open(ISSUES_INVESTORS, 'r', encoding='utf-8') as f:
                                issues_data = json.load(f)
                        except: issues_data = {}
                    
                    issues_data[inv_id] = investor_data_to_move
                    with open(ISSUES_INVESTORS, 'w', encoding='utf-8') as f:
                        json.dump(issues_data, f, indent=4)
                    
                    print(f"  ✅ Successfully moved investor {inv_id} to issues_investors.json")
                else:
                    print(f"  ⚠️  Investor {inv_id} not found in investors.json")
        except Exception as move_error:
            print(f"  ❌ Failed to move investor to issues_investors.json: {move_error}")
        
        mt5.shutdown()
    
    return account_stats

def place_orders_parallel():
    """
    ORCHESTRATOR: Spawns processes. If one hangs, others continue.
    """
    print(f"\n{'='*10} 🚀 MULTIPROCESSING ENGINE START {'='*10}")
    
    try:
        with open(INVESTOR_USERS, 'r') as f:
            investor_users = json.load(f)
    except Exception as e:
        print(f" ❌ Could not load JSON: {e}")
        return False

    investor_ids = list(investor_users.keys())
    if not investor_ids:
        return False

    # Define number of workers (max cores or number of accounts)
    num_processes = len(investor_ids)
    
    
    
    # Using a context manager ensures the pool is cleaned up properly
    with mp.Pool(processes=num_processes) as pool:
        # map() is blocking until all are done, but the executions are parallel.
        # This means the script waits for the SLOWEST investor to finish 
        # before printing the final summary.
        results = pool.map(process_single_investor, investor_ids)

    successful = sum(1 for r in results if r.get("success"))
    print(f"\n{'='*10} ALL TASKS FINISHED {'='*10}")
    print(f" Success: {successful} | Failed: {len(investor_ids)-successful}")
    
    return successful > 0
#--


# demo
def process_demo_single_investor(inv_id):
    """
    WORKER FUNCTION: Handles the entire pipeline for ONE investor (DEMO VERSION).
    Uses demo-style initialization with account info check before login.
    """
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
    
    try:
        with open(INVESTOR_USERS, 'r') as f:
            investor_users = json.load(f)
        broker_cfg = investor_users.get(inv_id)
    except Exception as e:
        print(f" [{inv_id}] ❌ JSON Read Error: {e}")
        return account_stats

    if not broker_cfg:
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
        if not mt5.initialize(path=mt5_path, timeout=500):
            print(f" [{inv_id}] ❌ MT5 Init failed at {mt5_path}")
            
            # --- MOVE TO ISSUES_INVESTORS ON INIT FAILURE ---
            print(f"  ❌ Moving investor {inv_id} to issues_investors.json due to MT5 initialization failure")
            
            if os.path.exists(INVESTOR_USERS):
                with open(INVESTOR_USERS, 'r', encoding='utf-8') as f:
                    investors_data = json.load(f)
                
                investor_data_to_move = None
                if isinstance(investors_data, list):
                    for i, inv in enumerate(investors_data):
                        if inv_id in inv:
                            investor_data_to_move = inv[inv_id]
                            investors_data.pop(i)
                            break
                else:
                    if inv_id in investors_data:
                        investor_data_to_move = investors_data[inv_id]
                        del investors_data[inv_id]
                
                if investor_data_to_move:
                    # Specific message for MT5 initialization failure
                    investor_data_to_move['MESSAGE'] = "invalid broker login please check your login details"
                    
                    with open(INVESTOR_USERS, 'w', encoding='utf-8') as f:
                        json.dump(investors_data, f, indent=4)
                    
                    issues_data = {}
                    if os.path.exists(ISSUES_INVESTORS):
                        try:
                            with open(ISSUES_INVESTORS, 'r', encoding='utf-8') as f:
                                issues_data = json.load(f)
                        except: issues_data = {}
                    
                    issues_data[inv_id] = investor_data_to_move
                    with open(ISSUES_INVESTORS, 'w', encoding='utf-8') as f:
                        json.dump(issues_data, f, indent=4)
                    
                    print(f"  ✅ Successfully moved investor {inv_id} to issues_investors.json")
                else:
                    print(f"  ⚠️  Investor {inv_id} not found in investors.json")
            
            mt5.shutdown()
            return account_stats

        # DEMO STYLE LOGIN: Check if already logged in correctly
        acc = mt5.account_info()
        if acc is None or acc.login != login_id:
            if not mt5.login(login_id, password=broker_cfg["PASSWORD"], server=broker_cfg["SERVER"]):
                print(f" [{inv_id}] ❌ Login failed")
                
                # --- MOVE TO ISSUES_INVESTORS ON LOGIN FAILURE ---
                print(f"  ❌ Moving investor {inv_id} to issues_investors.json due to login failure")
                
                if os.path.exists(INVESTOR_USERS):
                    with open(INVESTOR_USERS, 'r', encoding='utf-8') as f:
                        investors_data = json.load(f)
                    
                    investor_data_to_move = None
                    if isinstance(investors_data, list):
                        for i, inv in enumerate(investors_data):
                            if inv_id in inv:
                                investor_data_to_move = inv[inv_id]
                                investors_data.pop(i)
                                break
                    else:
                        if inv_id in investors_data:
                            investor_data_to_move = investors_data[inv_id]
                            del investors_data[inv_id]
                    
                    if investor_data_to_move:
                        # Specific message for login failure
                        investor_data_to_move['MESSAGE'] = "invalid broker login please check your login details"
                        
                        with open(INVESTOR_USERS, 'w', encoding='utf-8') as f:
                            json.dump(investors_data, f, indent=4)
                        
                        issues_data = {}
                        if os.path.exists(ISSUES_INVESTORS):
                            try:
                                with open(ISSUES_INVESTORS, 'r', encoding='utf-8') as f:
                                    issues_data = json.load(f)
                            except: issues_data = {}
                        
                        issues_data[inv_id] = investor_data_to_move
                        with open(ISSUES_INVESTORS, 'w', encoding='utf-8') as f:
                            json.dump(issues_data, f, indent=4)
                        
                        print(f"  ✅ Successfully moved investor {inv_id} to issues_investors.json")
                    else:
                        print(f"  ⚠️  Investor {inv_id} not found in investors.json")
                
                mt5.shutdown()
                return account_stats

        # --- RUN ALL SEQUENTIAL STEPS FOR THIS BROKER (SAME AS REAL VERSION) ---
        get_requirements(inv_id=inv_id)
        detect_unauthorized_action(inv_id=inv_id)
        accountmanagement_manager(inv_id=inv_id)
        deduplicate_orders(inv_id=inv_id)
        filter_unauthorized_symbols(inv_id=inv_id)
        filter_unauthorized_timeframes(inv_id=inv_id)
        backup_limit_orders(inv_id=inv_id)
        populate_orders_missing_fields(inv_id=inv_id)
        activate_usd_based_risk_on_empty_pricelevels(inv_id=inv_id)
        enforce_investors_risk(inv_id=inv_id)
        calculate_investor_symbols_orders(inv_id=inv_id)
        padding_tight_usd_risk(inv_id=inv_id)
        live_usd_risk_and_scaling(inv_id=inv_id)
        apply_default_prices(inv_id=inv_id)
        place_usd_orders(inv_id=inv_id)
        orders_risk_correction(inv_id=inv_id)
        check_pending_orders_risk(inv_id=inv_id)
        history_closed_orders_removal_in_pendingorders(inv_id=inv_id)
        apply_dynamic_breakeven(inv_id=inv_id)
        update_investor_info(inv_id=inv_id)
        
        # Update demo-specific stats if needed
        # (You might want to collect stats from these functions)
        
        mt5.shutdown()
        account_stats["success"] = True
        print(f" [{inv_id}] ✅ Demo processing complete")
        
    except Exception as e:
        print(f" [{inv_id}] ❌ Critical Error: {e}")
        
        # --- MOVE TO ISSUES_INVESTORS ON ANY UNEXPECTED ERROR ---
        print(f"  ❌ Moving investor {inv_id} to issues_investors.json due to unexpected error: {e}")
        
        try:
            if os.path.exists(INVESTOR_USERS):
                with open(INVESTOR_USERS, 'r', encoding='utf-8') as f:
                    investors_data = json.load(f)
                
                investor_data_to_move = None
                if isinstance(investors_data, list):
                    for i, inv in enumerate(investors_data):
                        if inv_id in inv:
                            investor_data_to_move = inv[inv_id]
                            investors_data.pop(i)
                            break
                else:
                    if inv_id in investors_data:
                        investor_data_to_move = investors_data[inv_id]
                        del investors_data[inv_id]
                
                if investor_data_to_move:
                    # Generic message for unexpected errors
                    investor_data_to_move['MESSAGE'] = f"unexpected error: {str(e)[:100]}"  # Truncate long errors
                    
                    with open(INVESTOR_USERS, 'w', encoding='utf-8') as f:
                        json.dump(investors_data, f, indent=4)
                    
                    issues_data = {}
                    if os.path.exists(ISSUES_INVESTORS):
                        try:
                            with open(ISSUES_INVESTORS, 'r', encoding='utf-8') as f:
                                issues_data = json.load(f)
                        except: issues_data = {}
                    
                    issues_data[inv_id] = investor_data_to_move
                    with open(ISSUES_INVESTORS, 'w', encoding='utf-8') as f:
                        json.dump(issues_data, f, indent=4)
                    
                    print(f"  ✅ Successfully moved investor {inv_id} to issues_investors.json")
                else:
                    print(f"  ⚠️  Investor {inv_id} not found in investors.json")
        except Exception as move_error:
            print(f"  ❌ Failed to move investor to issues_investors.json: {move_error}")
        
        try:
            mt5.shutdown()
        except:
            pass
    
    return account_stats

def place_demo_orders_parallel():
    """
    ORCHESTRATOR: Spawns multiple processes to handle investors in parallel
    based on the investor_users JSON file.
    """
    print(f"\n{'='*10} 🚀 STARTING DEMO MULTIPROCESSING ENGINE {'='*10}")
    
    
    # 1. Load the investor data directly from the JSON
    try:
        with open(INVESTOR_USERS, 'r') as f:
            investor_users = json.load(f)
    except Exception as e:
        print(f" ❌ Critical Error: Could not read {INVESTOR_USERS}: {e}")
        return False

    # 2. Extract investor IDs (keys from the JSON)
    investor_ids = list(investor_users.keys())
    
    if not investor_ids:
        print(" └─ 🔘 No investors found in JSON config.")
        return False

    print(f" 📝 Found {len(investor_ids)} accounts in config. Initializing parallel pool...")

    # 3. Create a pool based on the number of accounts found
    # We pass the ID string (e.g., 'bybit1') to the worker
    with mp.Pool(processes=len(investor_ids)) as pool:
        results = pool.map(process_demo_single_investor, investor_ids)

    # 4. Summary logic
    successful = sum(1 for r in results if r and r.get("success"))
    print(f"\n{'='*10} DEMO PARALLEL PROCESSING COMPLETE {'='*10}")
    print(f" Total Configured: {len(investor_ids)} | Successful: {successful} | Failed: {len(investor_ids)-successful}")
    
    return successful > 0

if __name__ == "__main__":
    place_orders_parallel()


