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
import pytz
import multiprocessing as mp
import multiprocessing
from pathlib import Path
import time
import random
import psutil


INV_PATH = r"C:\xampp\htdocs\harvcore\harvox\usersdata\investors"
UPDATED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\updated_investors.json"
INVESTOR_USERS = r"C:\xampp\htdocs\harvcore\harvox\usersdata\investors\investors.json"
FETCHED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\fetched_investors.json"
ISSUES_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\issues_investors.json"
DEFAULT_ACCOUNTMANAGEMENT = r"C:\xampp\htdocs\harvcore\harvox\harvcore_accountmanagement.json"
TECHNICAL_UPDATES = r"C:\xampp\htdocs\harvcore\harvox\server_updates.json"
DEFAULT_PATH = r"C:\xampp\htdocs\harvcore\harvox"
BASE_ERROR_FOLDER = r"C:\xampp\htdocs\harvcore\harvox\usersdata\debugs"
NORM_FILE_PATH = Path(DEFAULT_PATH) / "symbols_normalization.json"
ERROR_JSON_PATH = os.path.join(BASE_ERROR_FOLDER, "chart_errors.json")
TIMEFRAME_MAP = {
        "1m": mt5.TIMEFRAME_M1,
        "5m": mt5.TIMEFRAME_M5,
        "15m": mt5.TIMEFRAME_M15,
        "30m": mt5.TIMEFRAME_M30,
        "1h": mt5.TIMEFRAME_H1,
        "4h": mt5.TIMEFRAME_H4,
        "1d": mt5.TIMEFRAME_D1,
        "1w": mt5.TIMEFRAME_W1,
        "1mn": mt5.TIMEFRAME_MN1
}
NORMALIZE_SYMBOLS_PATH = Path(r"C:\xampp\htdocs\harvcore\harvox\symbols_normalization.json")

def load_investors_dictionary():
    """Load brokers config from JSON file with error handling and fallback."""
    if not os.path.exists(INVESTOR_USERS):
        print(f"CRITICAL: {INVESTOR_USERS} NOT FOUND! Using empty config.", "CRITICAL")
        return {}

    try:
        with open(INVESTOR_USERS, 'r', encoding='utf-8') as f:
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


#--VERIFICATIONS AND AUTHORIZATIONS--
def move_fetched_investors():
    """
    Moves verified investors from fetched_investors.json to:
    - investors.json (limited fields)
    - activities.json (with notifications)
    - tradeshistory.json (empty array)
    - accountmanagement.json (using defaults from fetched data or no defaults)
    
    Removes investors from investors.json if:
    - Not in fetched_investors.json
    - Missing required fields
    - activate_autotrading is False
    - broker_balance < min_broker_balance (insufficient funds)
    - demo_account is "0" when account_mode is "demo"
    
    Uses DEFAULT_ACCOUNTMANAGEMENT as fallback for contract_duration and min_broker_balance
    
    Handles database values: "1"/1 = True, "0"/0 = False
    """
    
    print(f"\n{'='*60}")
    print(f"MOVE VERIFIED INVESTORS".center(60))
    print(f"{'='*60}")
    
    # Helper function to convert database values to boolean
    def db_to_bool(value):
        """Convert database values (1, '1', 0, '0') to boolean"""
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value == 1
        if isinstance(value, str):
            return value.strip().lower() in ['1', 'true', 'yes', 'on']
        return False
    
    # Helper function to convert boolean to database string format '1' or '0'
    def bool_to_db_string(value):
        """Convert boolean to database string format '1' or '0'"""
        return '1' if value else '0'
    
    def normalize_date(date_value):
        """Convert invalid date values (0000-00-00, 0000-00-00 00:00:00, etc.) to empty string"""
        if date_value is None:
            return ""
        if not isinstance(date_value, str):
            date_value = str(date_value)
        date_value = date_value.strip()
        # Check for patterns like 0000-00-00, 0000-00-00 00:00:00, 0000-00-00T00:00:00
        if date_value.replace('-', '').replace(':', '').replace(' ', '').replace('T', '').strip('0') == '':
            return ""
        # Also check if it starts with 0000-00-00
        if date_value.startswith('0000-00-00'):
            return ""
        return date_value
    
    # Helper function to get the last message for a specific section
    def get_last_message(notifications_dict, section_key):
        """Get the most recent message for a specific section"""
        if not notifications_dict:
            return None
        
        latest_message = None
        latest_time = None
        latest_id = None
        
        for msg_id, msg_data in notifications_dict.items():
            if isinstance(msg_data, dict) and msg_data.get('section') == section_key:
                try:
                    msg_time = datetime.strptime(msg_data['time'], "%Y-%m-%d %H:%M:%S")
                    if latest_time is None or msg_time > latest_time:
                        latest_time = msg_time
                        latest_message = msg_data
                        latest_id = msg_id
                except:
                    pass
        
        if latest_message:
            return {
                'type': latest_message.get('type'),
                'time': latest_time,
                'id': latest_id,
                'data': latest_message
            }
        return None
    
    # Helper function to add notification with individual section tracking
    def add_notification(notifications_dict, section_key, message, message_type, timestamp=None):
        """
        Add notification with individual section tracking.
        Only adds if the message type is different from the last message type for that section.
        """
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        last_msg = get_last_message(notifications_dict, section_key)
        
        # Check if we should add this notification
        should_add = False
        if last_msg is None:
            # No message exists for this section, add it
            should_add = True
        else:
            # Only add if the type is different from the last message type
            if last_msg['type'] != message_type:
                should_add = True
        
        if not should_add:
            return False
        
        # Find next available ID
        next_id = 1
        if notifications_dict:
            try:
                existing_ids = [int(k) for k in notifications_dict.keys() if k.isdigit()]
                next_id = max(existing_ids) + 1 if existing_ids else 1
            except:
                next_id = len(notifications_dict) + 1
        
        notifications_dict[str(next_id)] = {
            "section": section_key,
            "message": message,
            "time": timestamp,
            "type": message_type,
            "update": "new"
        }
        return True
    
    # Helper function to add execution notification with individual section tracking
    def add_execution_notification(executions_dict, section_key, message, message_type, timestamp=None):
        """
        Add execution notification with individual section tracking.
        Only adds if the message type is different from the last message type for that section.
        """
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        last_msg = get_last_message(executions_dict, section_key)
        
        # Check if we should add this notification
        should_add = False
        if last_msg is None:
            # No message exists for this section, add it
            should_add = True
        else:
            # Only add if the type is different from the last message type
            if last_msg['type'] != message_type:
                should_add = True
        
        if not should_add:
            return False
        
        # Find next available ID
        next_id = 1
        if executions_dict:
            try:
                existing_ids = [int(k) for k in executions_dict.keys() if k.isdigit()]
                next_id = max(existing_ids) + 1 if existing_ids else 1
            except:
                next_id = len(executions_dict) + 1
        
        executions_dict[str(next_id)] = {
            "section": section_key,
            "message": message,
            "time": timestamp,
            "type": message_type,
            "update": "new"
        }
        return True
    
    # Load default accountmanagement.json for fallbacks
    default_contract_duration = None
    default_min_broker_balance = None
    
    if os.path.exists(DEFAULT_ACCOUNTMANAGEMENT):
        try:
            with open(DEFAULT_ACCOUNTMANAGEMENT, 'r', encoding='utf-8') as f:
                default_acct_mgmt = json.load(f)
            default_requirements = default_acct_mgmt.get('requirements', {})
            default_contract_duration = default_requirements.get('contract_duration')
            default_min_broker_balance = default_requirements.get('min_broker_balance')
            
            if default_contract_duration is not None:
                try:
                    default_contract_duration = int(default_contract_duration)
                except:
                    default_contract_duration = None
            if default_min_broker_balance is not None:
                try:
                    default_min_broker_balance = float(default_min_broker_balance)
                except:
                    default_min_broker_balance = None
                    
            print(f"   📋 Loaded defaults: contract_duration={default_contract_duration}, min_broker_balance={default_min_broker_balance}")
        except Exception as e:
            print(f"Error loading default_accountmanagement.json: {e}")
    else:
        print(f"Default accountmanagement file not found: {DEFAULT_ACCOUNTMANAGEMENT}")
    
    # Default activities template
    DEFAULT_ACTIVITIES = {
        "activate_autotrading": None,
        "bypass_restriction": None,
        "execution_start_date": "",
        "contract_duration": None,
        "contract_expiry_date": "",
        "min_broker_balance": None,
        "broker_balance": None,
        "unauthorized_trades": {},
        "unauthorized_withdrawals": {},
        "unauthorized_action_detected": False,
        "strategies": [],
        "notifications": {},
        "executions_notification": {},
        "_initial_notifications_sent": False,
        "_meets_balance_requirement": False,
        "_last_balance_notification_time": None
    }
    
    # Load or initialize updated_investors.json
    updated_investors_data = {}
    if os.path.exists(UPDATED_INVESTORS):
        try:
            with open(UPDATED_INVESTORS, 'r', encoding='utf-8') as f:
                updated_investors_data = json.load(f)
        except Exception as e:
            print(f"Error loading updated_investors.json: {e}")
    
    # Check if verified investors file exists
    if not os.path.exists(FETCHED_INVESTORS):
        print(f"File not found: {FETCHED_INVESTORS}")
        return False
    
    try:
        with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
            verified_data = json.load(f)
    except Exception as e:
        print(f"Error loading: {e}")
        return False
    
    print(f"📋 Found {len(verified_data)} investors")
    
    # ============================================
    # STEP 1: UPDATE investors.json
    # ============================================
    print(f"\n[1/4] Updating investors.json...")
    
    investors_data = {}
    if os.path.exists(INVESTOR_USERS):
        try:
            with open(INVESTOR_USERS, 'r', encoding='utf-8') as f:
                investors_data = json.load(f)
        except:
            pass
    
    valid_investors = set()
    investors_updated = []
    investors_skipped = []
    investors_removed = []
    
    # Track incomplete investors
    incomplete_investors = []
    # Track demo account restricted investors
    demo_restricted_investors = []
    
    for inv_id, investor_data in verified_data.items():
        # Extract required fields (case-insensitive)
        invested_with = investor_data.get('invested_with', investor_data.get('INVESTED_WITH', '')).strip()
        execution_start = normalize_date(investor_data.get('execution_start_date', investor_data.get('EXECUTION_START_DATE', '')))
        terminal_path = investor_data.get('TERMINAL_PATH', investor_data.get('terminal_path', '')).strip()
        login = investor_data.get('login', investor_data.get('LOGIN', investor_data.get('LOGIN_ID', '')))
        password = investor_data.get('password', investor_data.get('PASSWORD', '')).strip()
        server = investor_data.get('server', investor_data.get('SERVER', '')).strip()
        
        # Extract account mode and demo account fields
        account_mode = investor_data.get('account_mode', investor_data.get('ACCOUNT_MODE', '')).strip().lower()
        demo_account_raw = investor_data.get('demo_account', investor_data.get('DEMO_ACCOUNT', '0'))
        demo_account = db_to_bool(demo_account_raw)
        
        # Required fields check
        missing_required = []
        if not invested_with: missing_required.append('invested_with')
        if not execution_start: missing_required.append('execution_start_date')
        if not terminal_path: missing_required.append('TERMINAL_PATH')
        
        missing_investor_fields = []
        if not login: missing_investor_fields.append('login')
        if not password: missing_investor_fields.append('password')
        if not server: missing_investor_fields.append('server')
        
        is_complete = len(missing_required) == 0 and len(missing_investor_fields) == 0
        
        if not is_complete:
            investors_skipped.append(inv_id)
            incomplete_investors.append({
                'inv_id': inv_id,
                'missing_required': missing_required,
                'missing_investor_fields': missing_investor_fields,
                'investor_data': investor_data
            })
            
            # FIX: Create folder and add notifications for incomplete investors
            inv_root = Path(INV_PATH) / inv_id
            inv_root.mkdir(parents=True, exist_ok=True)
            
            # Create activities.json with notifications for missing fields
            activities_path = inv_root / "activities.json"
            existing_activities = {}
            if activities_path.exists():
                try:
                    with open(activities_path, 'r') as f:
                        existing_activities = json.load(f)
                except:
                    pass
            
            activities_data = DEFAULT_ACTIVITIES.copy()
            activities_data.update(existing_activities)
            
            if 'notifications' not in activities_data:
                activities_data['notifications'] = {}
            if 'executions_notification' not in activities_data:
                activities_data['executions_notification'] = {}
            
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Add AccountMode notification for incomplete investors
            if not account_mode:
                account_mode_msg = "Account mode is not specified. The system cannot determine if this is a demo or live account. Trading will proceed once account mode is confirmed."
                add_notification(activities_data['notifications'], 'AccountMode', account_mode_msg, 'error', timestamp)
                add_execution_notification(activities_data['executions_notification'], 'AccountMode', f"SERVER NOTIFICATION: Investor {inv_id} has unknown account mode.", 'error', timestamp)
            elif account_mode == 'demo':
                if demo_account is False:
                    account_mode_msg = "This is a demo account but demo trading is disabled. Demo accounts must have demo trading enabled to proceed."
                    add_notification(activities_data['notifications'], 'AccountMode', account_mode_msg, 'error', timestamp)
                    add_execution_notification(activities_data['executions_notification'], 'AccountMode', f"SERVER NOTIFICATION: Investor {inv_id} has demo account mode but demo_account is disabled.", 'error', timestamp)
                elif demo_account is True:
                    account_mode_msg = "This is a demo account with demo trading enabled. Trading will proceed in demo mode."
                    add_notification(activities_data['notifications'], 'AccountMode', account_mode_msg, 'success', timestamp)
                    add_execution_notification(activities_data['executions_notification'], 'AccountMode', f"SERVER NOTIFICATION: Investor {inv_id} demo account mode confirmed and enabled.", 'success', timestamp)
                else:
                    account_mode_msg = "This is a demo account but demo trading status is unknown. Please verify your demo account settings."
                    add_notification(activities_data['notifications'], 'AccountMode', account_mode_msg, 'error', timestamp)
                    add_execution_notification(activities_data['executions_notification'], 'AccountMode', f"SERVER NOTIFICATION: Investor {inv_id} demo account mode but demo_account status unknown.", 'error', timestamp)
            else:
                account_mode_msg = f"Account mode is set to '{account_mode}'. Trading will proceed with this configuration."
                add_notification(activities_data['notifications'], 'AccountMode', account_mode_msg, 'success', timestamp)
                add_execution_notification(activities_data['executions_notification'], 'AccountMode', f"SERVER NOTIFICATION: Investor {inv_id} account mode: {account_mode}.", 'success', timestamp)
            
            # Add notifications for missing required fields
            if missing_required:
                missing_fields_str = ', '.join(missing_required)
                missing_message = f" Please contact support for terminal configuration"
                add_notification(activities_data['notifications'], 'RegistrationRequired', missing_message, 'error', timestamp)
                add_execution_notification(activities_data['executions_notification'], 'RegistrationRequired', f"SERVER NOTIFICATION: Investor {inv_id} has missing required fields: {missing_fields_str}", 'error', timestamp)
            
            # Add notifications for missing investor credentials
            if missing_investor_fields:
                missing_creds_str = ', '.join(missing_investor_fields)
                creds_message = f" ACCOUNT CREDENTIALS MISSING: The following account information is incomplete: {missing_creds_str}. Trading cannot be activated until this information is provided."
                add_notification(activities_data['notifications'], 'CredentialsMissing', creds_message, 'error', timestamp)
                add_execution_notification(activities_data['executions_notification'], 'CredentialsMissing', f"SERVER NOTIFICATION: Investor {inv_id} has missing credentials: {missing_creds_str}", 'error', timestamp)
            
            # Add overall incomplete registration message if both types missing
            if missing_required and missing_investor_fields:
                overall_message = "Your investor registration is incomplete. Please provide all required information to begin automated trading."
                add_notification(activities_data['notifications'], 'RegistrationStatus', overall_message, 'error', timestamp)
            
            # Set initial notifications flag
            if activities_data['notifications']:
                activities_data['_initial_notifications_sent'] = True
            
            # Save activities.json
            with open(activities_path, 'w', encoding='utf-8') as f:
                json.dump(activities_data, f, indent=4)
            
            # Create empty tradeshistory.json
            tradeshistory_path = inv_root / "tradeshistory.json"
            if not tradeshistory_path.exists():
                with open(tradeshistory_path, 'w', encoding='utf-8') as f:
                    json.dump([], f, indent=4)
            
            # Create empty accountmanagement.json
            accountmanagement_path = inv_root / "accountmanagement.json"
            if not accountmanagement_path.exists():
                accountmanagement_data = {}
                if login and password and server:
                    if login: accountmanagement_data['login'] = str(login).strip()
                    if password: accountmanagement_data['password'] = password
                    if server: accountmanagement_data['server'] = server
                with open(accountmanagement_path, 'w', encoding='utf-8') as f:
                    json.dump(accountmanagement_data, f, indent=4)
            
            # Update investors.json if credentials are present
            investor_entry = {
                "LOGIN_ID": str(login).strip() if login else "",
                "PASSWORD": password if password else "",
                "SERVER": server if server else "",
                "DEMO_ACCOUNT": str(demo_account_raw) if demo_account_raw is not None else "0",
                "INVESTED_WITH": invested_with if invested_with else "",
                "TERMINAL_PATH": terminal_path if terminal_path else ""
            }
            
            if login and password and server:
                investors_data[inv_id] = investor_entry
                investors_updated.append(inv_id)
            else:
                # Still add to investors_data but mark as incomplete
                investor_entry["_incomplete"] = True
                investor_entry["_missing_fields"] = missing_required + missing_investor_fields
                investors_data[inv_id] = investor_entry
                investors_updated.append(inv_id)
            
            continue
        
        valid_investors.add(inv_id)
        
        investor_entry = {
            "LOGIN_ID": str(login).strip(),
            "PASSWORD": password,
            "SERVER": server,
            "DEMO_ACCOUNT": str(demo_account_raw) if demo_account_raw is not None else "0",
            "INVESTED_WITH": invested_with,
            "TERMINAL_PATH": terminal_path
        }
        investors_data[inv_id] = investor_entry
        investors_updated.append(inv_id)
    
    # Remove invalid investors
    investors_to_remove = []
    for inv_id in list(investors_data.keys()):
        if inv_id not in verified_data:
            investors_to_remove.append(inv_id)
            continue
        
        investor_data = verified_data.get(inv_id, {})
        login = investor_data.get('login', investor_data.get('LOGIN', investor_data.get('LOGIN_ID', '')))
        password = investor_data.get('password', investor_data.get('PASSWORD', '')).strip()
        server = investor_data.get('server', investor_data.get('SERVER', '')).strip()
        
        if not login or not password or not server:
            investors_to_remove.append(inv_id)
            continue
        
        # Check auto-trading status
        fetched_activate = None
        if 'enable_autotrading' in investor_data:
            fetched_activate = investor_data['enable_autotrading']
        elif 'activate_autotrading' in investor_data:
            fetched_activate = investor_data['activate_autotrading']
        
        if fetched_activate is not None:
            final_activate = db_to_bool(fetched_activate)
            if final_activate is False:
                investors_to_remove.append(inv_id)
                continue
    
    for inv_id in investors_to_remove:
        if inv_id in investors_data:
            del investors_data[inv_id]
            investors_removed.append(inv_id)
            if inv_id in valid_investors:
                valid_investors.discard(inv_id)
    
    if investors_updated or investors_removed:
        os.makedirs(os.path.dirname(INVESTOR_USERS), exist_ok=True)
        with open(INVESTOR_USERS, 'w', encoding='utf-8') as f:
            json.dump(investors_data, f, indent=4)
    
    print(f"   ✅ Added/Updated: {len(investors_updated)} | 🗑️ Removed: {len(investors_removed)} | ⏭️ Skipped: {len(investors_skipped)}")
    
    # ============================================
    # STEP 2: RECORD INCOMPLETE INVESTORS
    # ============================================
    print(f"\n[2/4] Recording incomplete investors...")
    
    for incomplete in incomplete_investors:
        inv_id = incomplete['inv_id']
        missing_required = incomplete['missing_required']
        missing_investor_fields = incomplete['missing_investor_fields']
        investor_data = incomplete['investor_data'].copy()
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        missing_fields_readable = ', '.join(missing_required + missing_investor_fields)
        
        # Copy all existing fields
        updated_record = investor_data.copy()
        
        # Add/update required fields
        updated_record["id"] = inv_id
        updated_record["last_updated"] = timestamp
        updated_record["has_error"] = True
        updated_record["error_messages"] = [f"Missing required fields: {missing_fields_readable}"]
        updated_record["status"] = "incomplete_registration"
        updated_record["processed"] = False
        
        # FIX: Add notification data to the record
        inv_root = Path(INV_PATH) / inv_id
        activities_path = inv_root / "activities.json"
        if activities_path.exists():
            try:
                with open(activities_path, 'r') as f:
                    activities_data = json.load(f)
                updated_record["notifications"] = activities_data.get('notifications', {})
                updated_record["executions_notification"] = activities_data.get('executions_notification', {})
            except:
                pass
        
        updated_investors_data[inv_id] = updated_record
        print(f"   📝 Recorded incomplete investor: {inv_id} (notifications added)")
    
    # ============================================
    # STEP 3: PROCESS COMPLETE INVESTORS
    # ============================================
    print(f"\n[3/4] Processing complete investors...")
    
    processed_summary = []
    autotrading_disabled_investors = []
    error_investors_to_delete = []
    balance_insufficient_investors = []
    demo_restricted_investors = []
    
    for inv_id, investor_data in verified_data.items():
        # Skip incomplete investors
        if inv_id in [inv['inv_id'] for inv in incomplete_investors]:
            continue
        
        print(f"\n   🔄 Processing investor: {inv_id}")
        
        # Extract fields
        invested_with = investor_data.get('invested_with', investor_data.get('INVESTED_WITH', '')).strip()
        execution_start = normalize_date(investor_data.get('execution_start_date', investor_data.get('EXECUTION_START_DATE', '')))
        contract_days_raw = investor_data.get('contract_days_left', investor_data.get('CONTRACT_DAYS_LEFT', '')).strip()
        terminal_path = investor_data.get('TERMINAL_PATH', investor_data.get('terminal_path', '')).strip()
        accountmanagement_data = investor_data.get('accountmanagement', {})
        
        # Extract account mode and demo account fields
        account_mode = investor_data.get('account_mode', investor_data.get('ACCOUNT_MODE', '')).strip().lower()
        demo_account_raw = investor_data.get('demo_account', investor_data.get('DEMO_ACCOUNT', '0'))
        demo_account = db_to_bool(demo_account_raw)
        
        # Get broker_balance (keep as string)
        broker_balance_str = investor_data.get('broker_balance', investor_data.get('BROKER_BALANCE', '0'))
        broker_balance_val = None
        if broker_balance_str and str(broker_balance_str).upper() not in ['NULL', 'NONE', '']:
            try:
                broker_balance_val = float(broker_balance_str)
            except:
                pass
        
        has_error = False
        error_messages = []
        
        # Handle activate_autotrading
        fetched_activate = None
        if 'enable_autotrading' in investor_data:
            fetched_activate = investor_data['enable_autotrading']
        elif 'activate_autotrading' in investor_data:
            fetched_activate = investor_data['activate_autotrading']
        
        final_activate = None
        if fetched_activate is not None:
            final_activate = db_to_bool(fetched_activate)
            if final_activate is None:
                final_activate = True
        
        # Handle bypass_restriction
        fetched_bypass = None
        if 'bypass_restriction' in investor_data:
            fetched_bypass = investor_data['bypass_restriction']
        
        final_bypass = None
        if fetched_bypass is not None:
            final_bypass = db_to_bool(fetched_bypass)
            if final_bypass is None:
                final_bypass = False
        
        # Handle contract_duration
        contract_duration_val = None
        if contract_days_raw and str(contract_days_raw).upper() not in ['NULL', 'NONE', '']:
            try:
                contract_days = int(contract_days_raw)
                if contract_days > 0:
                    contract_duration_val = contract_days
            except:
                pass
        
        if contract_duration_val is None and default_contract_duration is not None:
            contract_duration_val = default_contract_duration
        
        # Handle min_broker_balance
        min_broker_balance = None
        if 'min_broker_balance' in investor_data:
            try:
                min_broker_balance = float(investor_data['min_broker_balance'])
            except:
                pass
        
        if min_broker_balance is None and default_min_broker_balance is not None:
            min_broker_balance = default_min_broker_balance
        
        # Check balance requirement
        meets_balance_requirement = True
        balance_check_message = None
        balance_message_type = None
        
        if broker_balance_val is not None and min_broker_balance is not None:
            if broker_balance_val < min_broker_balance:
                meets_balance_requirement = False
                has_error = True
                error_messages.append(f"Insufficient balance: ${broker_balance_val:.2f} < ${min_broker_balance:.2f}")
                balance_check_message = f"💰 BALANCE VERIFICATION: Broker balance of ${broker_balance_val:.2f} is below the minimum requirement of ${min_broker_balance:.2f}. Trading operations are paused until minimum balance is met."
                balance_message_type = 'error'
                balance_insufficient_investors.append(inv_id)
            else:
                balance_check_message = f"💰 BALANCE VERIFICATION: Investor's broker balance of ${broker_balance_val:.2f} meets the minimum requirement of ${min_broker_balance:.2f}. Trading operations can proceed normally."
                balance_message_type = 'success'
        
        # Check demo account restriction
        demo_account_restricted = False
        demo_account_message = None
        demo_account_message_type = None
        
        if account_mode == 'demo':
            if demo_account is False:
                demo_account_restricted = True
                has_error = True
                error_messages.append("Demo account mode but demo_account is disabled")
                demo_account_message = f"🚫 DEMO ACCOUNT RESTRICTION: Demo accounts are not allowed"
                demo_account_message_type = 'error'
                demo_restricted_investors.append(inv_id)
            elif demo_account is True:
                demo_account_message = f"✅ ACCOUNT VERIFICATION: Trading will proceed in this account. "
                demo_account_message_type = 'success'
            elif demo_account is None:
                demo_account_message = f"⚠️ DEMO ACCOUNT UNKNOWN: Account mode is 'demo' but demo_account status is unknown. Please verify your account configuration."
                demo_account_message_type = 'error'
                has_error = True
                error_messages.append("Demo account mode but demo_account status unknown")
                demo_restricted_investors.append(inv_id)
        elif not account_mode:
            demo_account_message = f"⚠️ ACCOUNT MODE UNKNOWN: Account mode is not specified. Trading will proceed but account type cannot be verified."
            demo_account_message_type = 'error'
            # Not adding to demo_restricted since mode is unknown, just warning
        else:
            demo_account_message = f"ℹ️ ACCOUNT MODE: This is a '{account_mode}' account. Standard trading rules apply."
            demo_account_message_type = 'success'
        
        # Extract strategies
        strategies = [s.strip() for s in invested_with.split(",") if s.strip()]
        strategy_names = []
        for strat_full in strategies:
            underscore_index = strat_full.find('_')
            if underscore_index != -1:
                strategy_names.append(strat_full[underscore_index + 1:])
            else:
                strategy_names.append(strat_full)
        
        # Format date and calculate expiry
        formatted_start_date = execution_start
        expiry_date_str = ""
        
        if execution_start:
            try:
                date_obj = datetime.strptime(execution_start, "%Y-%m-%d")
                formatted_start_date = date_obj.strftime("%B %d, %Y")
                
                if contract_duration_val is not None and contract_duration_val > 0:
                    expiry_date = date_obj + timedelta(days=contract_duration_val)
                    expiry_date_str = expiry_date.strftime("%B %d, %Y")
            except:
                try:
                    date_obj = datetime.strptime(execution_start, "%B %d, %Y")
                    formatted_start_date = execution_start
                    if contract_duration_val is not None and contract_duration_val > 0:
                        expiry_date = date_obj + timedelta(days=contract_duration_val)
                        expiry_date_str = expiry_date.strftime("%B %d, %Y")
                except:
                    pass
        
        # Create investor folder
        inv_root = Path(INV_PATH) / inv_id
        inv_root.mkdir(parents=True, exist_ok=True)
        
        # Create/Update activities.json
        activities_path = inv_root / "activities.json"
        existing_activities = {}
        if activities_path.exists():
            try:
                with open(activities_path, 'r') as f:
                    existing_activities = json.load(f)
            except:
                pass
        
        activities_data = DEFAULT_ACTIVITIES.copy()
        activities_data.update(existing_activities)
        
        if final_activate is not None:
            activities_data["activate_autotrading"] = final_activate
        if final_bypass is not None:
            activities_data["bypass_restriction"] = final_bypass
        if contract_duration_val is not None:
            activities_data["contract_duration"] = contract_duration_val
        if min_broker_balance is not None:
            activities_data["min_broker_balance"] = min_broker_balance
        if broker_balance_val is not None:
            activities_data["broker_balance"] = broker_balance_val
        if execution_start:
            activities_data["execution_start_date"] = formatted_start_date
        if expiry_date_str:
            activities_data["contract_expiry_date"] = expiry_date_str
        
        if 'notifications' not in activities_data:
            activities_data['notifications'] = {}
        if 'executions_notification' not in activities_data:
            activities_data['executions_notification'] = {}
        if '_initial_notifications_sent' not in activities_data:
            activities_data['_initial_notifications_sent'] = False
        if '_meets_balance_requirement' not in activities_data:
            activities_data['_meets_balance_requirement'] = meets_balance_requirement
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # ============================================
        # ADD ACCOUNT MODE NOTIFICATION (NEW SECTION)
        # ============================================
        if demo_account_message:
            add_notification(activities_data['notifications'], 'AccountMode', demo_account_message, demo_account_message_type, timestamp)
            add_execution_notification(activities_data['executions_notification'], 'AccountMode', demo_account_message, demo_account_message_type, timestamp)
        
        # Add notifications with individual section tracking
        
        # 1. STRATEGIES section
        if not strategy_names:
            strategy_message = "You are currently not enrolled in any trading strategy partnership. Please contact your account manager to enroll in a strategy to begin automated trading."
            add_notification(activities_data['notifications'], 'Strategies', strategy_message, 'error', timestamp)
            add_execution_notification(activities_data['executions_notification'], 'Strategies', f"SERVER NOTIFICATION: Investor {inv_id} has no strategy partnership.", 'error', timestamp)
            has_error = True
            error_messages.append("No strategy partnership")
        else:
            strategy_message = f"Your account has been configured with the following trading strategy(s): {', '.join(strategy_names)}. The system will execute trades according to this strategy configuration."
            add_notification(activities_data['notifications'], 'Strategies', strategy_message, 'success', timestamp)
            add_execution_notification(activities_data['executions_notification'], 'Strategies', f"SERVER NOTIFICATION: Investor {inv_id} successfully configured with strategies: {', '.join(strategy_names)}", 'success', timestamp)
            activities_data["strategies"] = strategy_names
        
        # 2. START DATE section
        if not execution_start:
            start_message = "Your program start date is not set. You haven't officially enrolled in the trading program. Please complete your enrollment to activate trading."
            add_notification(activities_data['notifications'], 'StartDate', start_message, 'error', timestamp)
            add_execution_notification(activities_data['executions_notification'], 'StartDate', f"SERVER NOTIFICATION: Investor {inv_id} has no execution start date.", 'error', timestamp)
            has_error = True
            error_messages.append("No execution start date")
        else:
            start_message = f"Your trading program is active as of {formatted_start_date}. Welcome aboard!"
            add_notification(activities_data['notifications'], 'StartDate', start_message, 'success', timestamp)
            add_execution_notification(activities_data['executions_notification'], 'StartDate', f"SERVER NOTIFICATION: Investor {inv_id} enrollment confirmed. Start date: {formatted_start_date}", 'success', timestamp)
        
        # 3. AUTOTRADING section
        if final_activate is False:
            autotrading_message = "Auto-trading has been disabled on your account. No automated trades will be executed. Please contact support."
            add_notification(activities_data['notifications'], 'Autotrading', autotrading_message, 'error', timestamp)
            add_execution_notification(activities_data['executions_notification'], 'Autotrading', f"SERVER NOTIFICATION: Investor {inv_id} has auto-trading disabled.", 'error', timestamp)
            autotrading_disabled_investors.append(inv_id)
            has_error = True
            error_messages.append("Auto-trading disabled by user")
        elif final_activate is True:
            autotrading_message = "Your auto-trading feature is now active. The system will automatically execute trades according to your strategy configuration."
            add_notification(activities_data['notifications'], 'Autotrading', autotrading_message, 'success', timestamp)
            add_execution_notification(activities_data['executions_notification'], 'Autotrading', f"SERVER NOTIFICATION: Investor {inv_id} auto-trading is active and ready for automated execution.", 'success', timestamp)
        
        # 4. BYPASS RESTRICTION section
        if final_bypass is True:
            bypass_message = "Your account has bypass restrictions enabled. Unauthorized actions will be automatically bypassed without triggering restrictions. Please monitor your account activity."
            add_notification(activities_data['notifications'], 'BypassRestriction', bypass_message, 'error', timestamp)
            add_execution_notification(activities_data['executions_notification'], 'BypassRestriction', f"SERVER NOTIFICATION: Investor {inv_id} has bypass_restriction ENABLED.", 'error', timestamp)
        elif final_bypass is False:
            bypass_message = "Standard trading restrictions are in place. Ensure to avoid unauthorized actions such as manual trades, withdrawals and deposits during this contract duration."
            add_notification(activities_data['notifications'], 'BypassRestriction', bypass_message, 'success', timestamp)
            add_execution_notification(activities_data['executions_notification'], 'BypassRestriction', f"SERVER NOTIFICATION: Investor {inv_id} has bypass_restriction disabled.", 'success', timestamp)
        
        # 5. CONTRACT DURATION section
        if contract_duration_val is None or contract_duration_val == 0:
            duration_message = "Your contract duration is not set. Trading will continue without a contract end date."
            add_notification(activities_data['notifications'], 'ContractDuration', duration_message, 'success', timestamp)
        else:
            if expiry_date_str:
                duration_message = f"Your trading contract duration is set to {contract_duration_val} days. Your contract will expire on {expiry_date_str}. You are currently within your active trading period."
            else:
                duration_message = f"Your trading contract duration is set to {contract_duration_val} days. You are currently within your active trading period."
            add_notification(activities_data['notifications'], 'ContractDuration', duration_message, 'success', timestamp)
            add_execution_notification(activities_data['executions_notification'], 'ContractDuration', f"SERVER NOTIFICATION: Investor {inv_id} contract duration configured: {contract_duration_val} days.", 'success', timestamp)
        
        # 6. TERMINAL PATH section
        if not terminal_path or terminal_path.strip() == '':
            terminal_message = "Your terminal path is missing. Please contact support to resolve your account status."
            add_notification(activities_data['notifications'], 'TerminalPath', terminal_message, 'error', timestamp)
            add_execution_notification(activities_data['executions_notification'], 'TerminalPath', f"SERVER NOTIFICATION: Investor {inv_id} has NO TERMINAL PATH.", 'error', timestamp)
            has_error = True
            error_messages.append("Terminal path missing")
        else:
            terminal_message = "Your trading terminal has been configured and is ready for automated trading."
            add_notification(activities_data['notifications'], 'TerminalPath', terminal_message, 'success', timestamp)
            add_execution_notification(activities_data['executions_notification'], 'TerminalPath', f"SERVER NOTIFICATION: Investor {inv_id} terminal path configured successfully.", 'success', timestamp)
        
        # 7. BALANCE CHECK section
        if balance_check_message:
            old_meets_requirement = activities_data.get('_meets_balance_requirement', True)
            add_notification(activities_data['notifications'], 'BalanceCheck', balance_check_message, balance_message_type, timestamp)
            
            # Check if we need to add execution notification (when type changes or first time)
            last_exec_msg = get_last_message(activities_data['executions_notification'], 'BalanceCheck')
            if not meets_balance_requirement or (meets_balance_requirement and not old_meets_requirement):
                if last_exec_msg is None or last_exec_msg['type'] != balance_message_type:
                    add_execution_notification(activities_data['executions_notification'], 'BalanceCheck', balance_check_message, balance_message_type, timestamp)
            
            activities_data['_meets_balance_requirement'] = meets_balance_requirement
            activities_data['_last_balance_notification_time'] = timestamp
        
        # Set initial notifications flag if any notifications were added
        if activities_data['notifications'] and not activities_data['_initial_notifications_sent']:
            activities_data['_initial_notifications_sent'] = True
        
        # Save activities.json
        with open(activities_path, 'w', encoding='utf-8') as f:
            json.dump(activities_data, f, indent=4)
        
        # Create tradeshistory.json
        tradeshistory_path = inv_root / "tradeshistory.json"
        if not tradeshistory_path.exists():
            with open(tradeshistory_path, 'w', encoding='utf-8') as f:
                json.dump([], f, indent=4)
        
        # Create/Update accountmanagement.json
        accountmanagement_path = inv_root / "accountmanagement.json"
        final_accountmanagement = {}
        
        if accountmanagement_data:
            final_accountmanagement.update(accountmanagement_data)
        
        if contract_duration_val is not None:
            if 'requirements' not in final_accountmanagement:
                final_accountmanagement['requirements'] = {}
            final_accountmanagement['requirements']['contract_duration'] = str(contract_duration_val)
        
        if min_broker_balance is not None:
            if 'requirements' not in final_accountmanagement:
                final_accountmanagement['requirements'] = {}
            final_accountmanagement['requirements']['min_broker_balance'] = f"{min_broker_balance:.2f}"
        
        if final_bypass is not None:
            final_accountmanagement['bypass_restriction'] = final_bypass
        if final_activate is not None:
            final_accountmanagement['activate_autotrading'] = final_activate
        if broker_balance_val is not None:
            final_accountmanagement['broker_balance'] = broker_balance_val
        
        # Add account mode info to accountmanagement
        if account_mode:
            final_accountmanagement['account_mode'] = account_mode
        if demo_account_raw is not None:
            final_accountmanagement['demo_account'] = str(demo_account_raw)
        
        with open(accountmanagement_path, 'w', encoding='utf-8') as f:
            json.dump(final_accountmanagement, f, indent=4)
        
        # Build updated record - copy ALL existing fields first
        updated_record = investor_data.copy()
        
        # Add/update with our processed fields
        updated_record["id"] = inv_id
        updated_record["last_updated"] = timestamp
        updated_record["has_error"] = has_error
        updated_record["processed"] = True
        updated_record["folder_created"] = True
        updated_record["contract_expiry_date_calculated"] = expiry_date_str if expiry_date_str else None
        updated_record["meets_balance_requirement"] = meets_balance_requirement
        updated_record["min_broker_balance"] = min_broker_balance
        updated_record["error_messages"] = error_messages if has_error else []
        updated_record["notifications"] = activities_data.get('notifications', {})
        updated_record["executions_notification"] = activities_data.get('executions_notification', {})
        updated_record["strategies"] = strategy_names
        updated_record["execution_start_date"] = formatted_start_date if execution_start and execution_start != '0' else None
        updated_record["account_mode"] = account_mode if account_mode else "unknown"
        updated_record["demo_account"] = str(demo_account_raw) if demo_account_raw is not None else "0"
        updated_record["demo_account_restricted"] = demo_account_restricted
        
        # Convert booleans to database format '1'/'0' for these specific fields
        updated_record["enable_autotrading"] = bool_to_db_string(final_activate) if final_activate is not None else investor_data.get('enable_autotrading', '0')
        updated_record["bypass_restriction"] = bool_to_db_string(final_bypass) if final_bypass is not None else investor_data.get('bypass_restriction', '0')
        
        # Ensure broker_balance is string
        if 'broker_balance' in updated_record:
            updated_record['broker_balance'] = str(updated_record['broker_balance'])
        
        updated_investors_data[inv_id] = updated_record
        
        if has_error:
            if demo_account_restricted:
                # Demo restricted investors are handled separately
                pass
            else:
                error_investors_to_delete.append(inv_id)
        else:
            processed_summary.append(inv_id)
    
    # ============================================
    # DELETE ERROR INVESTORS
    # ============================================
    if error_investors_to_delete:
        print(f"\n[4/4] Removing error investors...")
        for inv_id in error_investors_to_delete:
            if inv_id in investors_data:
                del investors_data[inv_id]
                if inv_id in valid_investors:
                    valid_investors.discard(inv_id)
            
            inv_folder = Path(INV_PATH) / inv_id
            if inv_folder.exists():
                import shutil
                shutil.rmtree(inv_folder)
            
            if inv_id in updated_investors_data:
                updated_investors_data[inv_id]["folder_deleted"] = True
                updated_investors_data[inv_id]["removed_from_investors"] = True
        
        if error_investors_to_delete:
            with open(INVESTOR_USERS, 'w', encoding='utf-8') as f:
                json.dump(investors_data, f, indent=4)
        
        print(f"   ✅ Removed {len(error_investors_to_delete)} error investors")
    
    # ============================================
    # REMOVE AUTOTRADING DISABLED INVESTORS
    # ============================================
    if autotrading_disabled_investors:
        removed_count = 0
        for inv_id in autotrading_disabled_investors:
            if inv_id in investors_data:
                del investors_data[inv_id]
                removed_count += 1
                if inv_id in valid_investors:
                    valid_investors.discard(inv_id)
            
            if inv_id in updated_investors_data:
                updated_investors_data[inv_id]["auto_trading_disabled"] = True
                updated_investors_data[inv_id]["removed_from_investors"] = True
        
        if removed_count > 0:
            with open(INVESTOR_USERS, 'w', encoding='utf-8') as f:
                json.dump(investors_data, f, indent=4)
        print(f"   🚫 Removed {removed_count} investors (auto-trading disabled)")
    
    # ============================================
    # HANDLE DEMO RESTRICTED INVESTORS (NEW SECTION)
    # ============================================
    if demo_restricted_investors:
        print(f"\n🚫 Handling demo restricted investors...")
        removed_count = 0
        for inv_id in demo_restricted_investors:
            # Remove from investors.json
            if inv_id in investors_data:
                del investors_data[inv_id]
                removed_count += 1
                if inv_id in valid_investors:
                    valid_investors.discard(inv_id)
            
            # Delete investor folder
            inv_folder = Path(INV_PATH) / inv_id
            if inv_folder.exists():
                import shutil
                shutil.rmtree(inv_folder)
            
            # Update record
            if inv_id in updated_investors_data:
                updated_investors_data[inv_id]["demo_account_restricted"] = True
                updated_investors_data[inv_id]["removed_from_investors"] = True
                updated_investors_data[inv_id]["folder_deleted"] = True
        
        if removed_count > 0:
            with open(INVESTOR_USERS, 'w', encoding='utf-8') as f:
                json.dump(investors_data, f, indent=4)
        print(f"   🚫 Removed {removed_count} investors (demo account restricted)")
    
    # ============================================
    # MOVE INSUFFICIENT BALANCE INVESTORS
    # ============================================
    if balance_insufficient_investors:
        print(f"\n💰 Moving insufficient balance investors to issues_investors.json...")
        moved_to_issues = []
        
        for inv_id in balance_insufficient_investors:
            if inv_id in investors_data:
                investor_data = investors_data[inv_id]
                balance_info = updated_investors_data.get(inv_id, {})
                
                investor_data['MESSAGE'] = f"Insufficient balance: ${balance_info.get('broker_balance', 'Unknown')} is below minimum requirement ${balance_info.get('min_broker_balance', 'Unknown')}"
                investor_data['insufficient_balance'] = True
                investor_data['moved_to_issues_date'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                del investors_data[inv_id]
                
                issues_data = {}
                if os.path.exists(ISSUES_INVESTORS):
                    try:
                        with open(ISSUES_INVESTORS, 'r', encoding='utf-8') as f:
                            issues_data = json.load(f)
                    except: 
                        issues_data = {}
                
                issues_data[inv_id] = investor_data
                with open(ISSUES_INVESTORS, 'w', encoding='utf-8') as f:
                    json.dump(issues_data, f, indent=4)
                
                moved_to_issues.append(inv_id)
                
                if inv_id in updated_investors_data:
                    updated_investors_data[inv_id]['moved_to_issues'] = True
                    updated_investors_data[inv_id]['moved_to_issues_reason'] = 'insufficient_balance'
        
        if moved_to_issues:
            with open(INVESTOR_USERS, 'w', encoding='utf-8') as f:
                json.dump(investors_data, f, indent=4)
            print(f"   ✅ Moved {len(moved_to_issues)} investors to issues_investors.json")
    
    # ============================================
    # SAVE UPDATED_INVESTORS.JSON
    # ============================================
    if updated_investors_data:
        os.makedirs(os.path.dirname(UPDATED_INVESTORS), exist_ok=True)
        with open(UPDATED_INVESTORS, 'w', encoding='utf-8') as f:
            json.dump(updated_investors_data, f, indent=4)
        print(f"\n📝 Updated updated_investors.json with {len(updated_investors_data)} investor records")
    
    # ============================================
    # CLEANUP ORPHANED FOLDERS
    # ============================================
    print(f"\n🧹 Cleaning up orphaned folders...")
    deleted_folders = []
    
    try:
        inv_path_obj = Path(INV_PATH)
        if inv_path_obj.exists():
            for folder_path in inv_path_obj.iterdir():
                if folder_path.is_dir():
                    should_have_folder = (
                        folder_path.name in valid_investors and 
                        folder_path.name not in error_investors_to_delete and
                        folder_path.name not in balance_insufficient_investors and
                        folder_path.name not in demo_restricted_investors and
                        folder_path.name not in [inv['inv_id'] for inv in incomplete_investors]
                    )
                    
                    if not should_have_folder and folder_path.name not in processed_summary:
                        import shutil
                        shutil.rmtree(folder_path)
                        deleted_folders.append(folder_path.name)
        print(f"   🗑️ Deleted {len(deleted_folders)} orphaned folders")
    except Exception as e:
        print(f"   Cleanup error: {e}")
    
    # ============================================
    # FINAL SUMMARY
    # ============================================
    print(f"\n{'='*60}")
    print(f"SUMMARY".center(60))
    print(f"{'='*60}")
    print(f"✅ Processed (complete): {len(processed_summary)} investors")
    print(f"Incomplete (recorded only): {len(incomplete_investors)} investors")
    print(f"Error investors (removed): {len(error_investors_to_delete)}")
    print(f"Auto-trading disabled (removed): {len(autotrading_disabled_investors)}")
    print(f"Demo restricted (removed): {len(demo_restricted_investors)}")
    print(f"Insufficient balance (moved to issues): {len(balance_insufficient_investors)}")
    print(f"📁 investors.json: +{len(investors_updated)} -{len(investors_removed)} -{len(autotrading_disabled_investors)} -{len(error_investors_to_delete)} -{len(balance_insufficient_investors)} -{len(demo_restricted_investors)}")
    print(f"📝 activities.json: {len(processed_summary) + len(incomplete_investors)} updated (including incomplete investors)")
    print(f"💰 accountmanagement.json: {len(processed_summary)} updated")
    print(f"📋 updated_investors.json: {len(updated_investors_data)} investor records")
    print(f"🗑️ Folders cleaned: {len(deleted_folders)}")
    print(f"{'='*60}")
    print(f"✅ MOVE COMPLETE".center(60))
    print(f"{'='*60}")
    
    return True

def check_and_record_unauthorized_actions(inv_id=None):
    """
    Check and record authorized/unauthorized actions for investors based on Magic Number only.
    
    MAGIC NUMBER STRATEGY:
    - Magic Number = int(str(LOGIN_ID) + str(USER_ID))
    - Example: LOGIN_ID=5996427, USER_ID=10 -> Magic Number = 599642710
    
    This function:
    1. Constructs authorized magic number from investor's LOGIN_ID and USER_ID
    2. Compares with MT5 pending orders and open positions (by magic number only)
    3. Fetches history orders from execution start date to present
    4. Identifies unauthorized orders and positions (those with different magic number)
    5. Records them in activities.json with detailed information
    6. Records completed history orders with profit/loss information
    7. Calculates profit and loss (sum of all closed trade profits)
    8. Calculates current balance = starting_balance + total_profit_from_closed_trades
    9. Updates notifications for unauthorized actions, balance discrepancies, and status changes
    
    Args:
        inv_id: Optional specific investor ID to process. If None, processes all investors.
        
    Returns:
        dict: Statistics about authorized/unauthorized actions found
    """
    
    # Helper function to get the last message for a specific section
    def get_last_message(notifications_dict, section_key):
        """Get the most recent message for a specific section"""
        if not notifications_dict:
            return None
        
        latest_message = None
        latest_time = None
        latest_id = None
        
        for msg_id, msg_data in notifications_dict.items():
            if isinstance(msg_data, dict) and msg_data.get('section') == section_key:
                try:
                    msg_time = datetime.strptime(msg_data['time'], "%Y-%m-%d %H:%M:%S")
                    if latest_time is None or msg_time > latest_time:
                        latest_time = msg_time
                        latest_message = msg_data
                        latest_id = msg_id
                except:
                    pass
        
        if latest_message:
            return {
                'type': latest_message.get('type'),
                'time': latest_time,
                'id': latest_id,
                'data': latest_message
            }
        return None
    
    # Helper function to add notification with individual section tracking
    def add_notification(notifications_dict, section_key, message, message_type, timestamp=None):
        """
        Add notification with individual section tracking.
        Only adds if the message type is different from the last message type for that section.
        """
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        last_msg = get_last_message(notifications_dict, section_key)
        
        # Check if we should add this notification
        should_add = False
        if last_msg is None:
            # No message exists for this section, add it
            should_add = True
        else:
            # Only add if the type is different from the last message type
            if last_msg['type'] != message_type:
                should_add = True
        
        if not should_add:
            return False
        
        # Find next available ID
        next_id = 1
        if notifications_dict:
            try:
                existing_ids = [int(k) for k in notifications_dict.keys() if k.isdigit()]
                next_id = max(existing_ids) + 1 if existing_ids else 1
            except:
                next_id = len(notifications_dict) + 1
        
        notifications_dict[str(next_id)] = {
            "section": section_key,
            "message": message,
            "time": timestamp,
            "type": message_type,
            "update": "new"
        }
        return True
    
    # Helper function to add execution notification with individual section tracking
    def add_execution_notification(executions_dict, section_key, message, message_type, timestamp=None):
        """
        Add execution notification with individual section tracking.
        Only adds if the message type is different from the last message type for that section.
        """
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        last_msg = get_last_message(executions_dict, section_key)
        
        # Check if we should add this notification
        should_add = False
        if last_msg is None:
            # No message exists for this section, add it
            should_add = True
        else:
            # Only add if the type is different from the last message type
            if last_msg['type'] != message_type:
                should_add = True
        
        if not should_add:
            return False
        
        # Find next available ID
        next_id = 1
        if executions_dict:
            try:
                existing_ids = [int(k) for k in executions_dict.keys() if k.isdigit()]
                next_id = max(existing_ids) + 1 if existing_ids else 1
            except:
                next_id = len(executions_dict) + 1
        
        executions_dict[str(next_id)] = {
            "section": section_key,
            "message": message,
            "time": timestamp,
            "type": message_type,
            "update": "new"
        }
        return True
    
    print("\n" + "="*80)
    print("  🔍 AUTHORIZED ACTIONS AUDIT (MAGIC NUMBER ONLY)".ljust(79) + "=")
    print("="*80)
    
    stats = {
        "investor_id": inv_id if inv_id else "all",
        "investors_processed": 0,
        "investors_with_unauthorized": 0,
        "unauthorized_orders_found": 0,
        "unauthorized_positions_found": 0,
        "unauthorized_trades_found": 0,
        "history_orders_recorded": 0,
        "history_orders_updated": 0,
        "bypass_active_investors": 0,
        "autotrading_active_investors": 0,
        "unauthorized_by_investor": {},
        "processing_success": False
    }
    
    investor_ids = [inv_id] if inv_id else list(usersdictionary.keys())
    
    if not investor_ids:
        print("│\n├─  No investors found.")
        print("="*80)
        return stats
    
    # Load or initialize updated_investors.json for tracking audit history
    updated_investors_data = {}
    if os.path.exists(UPDATED_INVESTORS):
        try:
            with open(UPDATED_INVESTORS, 'r', encoding='utf-8') as f:
                updated_investors_data = json.load(f)
        except Exception as e:
            print(f"Error loading updated_investors.json: {e}")
    
    for user_brokerid in investor_ids:
        # ============================================================
        # HEADER
        # ============================================================
        print(f"\n├{'─'*78}┤")
        print(f"│  📋 INVESTOR: {user_brokerid}")
        print(f"├{'─'*78}┤")
        
        inv_root = Path(INV_PATH) / user_brokerid
        if not inv_root.exists():
            print(f"│   Path not found: {inv_root}")
            continue
        
        stats["investors_processed"] += 1
        
        # ============================================================
        # LOAD CONFIGURATION FILES
        # ============================================================
        acc_mgmt_path = inv_root / "accountmanagement.json"
        activities_path = inv_root / "activities.json"
        
        # Load existing activities.json to get starting balance and existing notifications
        existing_activities = {}
        starting_balance = None
        previous_application_status = None
        
        if activities_path.exists():
            try:
                with open(activities_path, 'r', encoding='utf-8') as f:
                    existing_activities = json.load(f)
                    starting_balance = existing_activities.get('broker_balance')
                    previous_application_status = existing_activities.get('application_status')
                    if starting_balance:
                        print(f"│  💰 Starting balance from activities.json: ${starting_balance:.2f}")
                    if previous_application_status:
                        print(f"│  📋 Previous status: {previous_application_status}")
            except Exception as e:
                print(f"│  Error reading activities.json: {e}")
        
        # ============================================================
        # GET BROKER CONFIG AND BUILD MAGIC NUMBER
        # ============================================================
        broker_cfg = usersdictionary.get(user_brokerid)
        if not broker_cfg:
            print(f"│   No broker config found for investor {user_brokerid}")
            continue
        
        login_id = broker_cfg.get('LOGIN_ID', '')
        if not login_id:
            print(f"│   No LOGIN_ID found for investor {user_brokerid}")
            continue
        
        # Construct Magic Number: LOGIN_ID + USER_ID
        try:
            authorized_magic_number = int(str(login_id) + str(user_brokerid))
            print(f"│  🔑 Authorized Magic Number: {authorized_magic_number}")
            print(f"│     (LOGIN_ID: {login_id} + USER_ID: {user_brokerid})")
        except (ValueError, TypeError) as e:
            print(f"│   Error creating magic number: {e}")
            continue
        
        # ============================================================
        # LOAD ACCOUNT SETTINGS
        # ============================================================
        bypass_active = False
        autotrading_active = False
        execution_start_date = None
        
        if acc_mgmt_path.exists():
            try:
                with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                    acc_config = json.load(f)
                    bypass_active = acc_config.get("bypass_restriction", False)
                    autotrading_active = acc_config.get("activate_autotrading", False)
                    execution_start_date = acc_config.get('execution_start_date')
                print(f"│  ⚙️ Bypass: {bypass_active} | Auto-trading: {autotrading_active}")
            except Exception as e:
                print(f"│  Error reading accountmanagement.json: {e}")
        
        # Get execution start date from activities.json if not found
        if not execution_start_date and activities_path.exists():
            try:
                with open(activities_path, 'r', encoding='utf-8') as f:
                    activities_data = json.load(f)
                    execution_start_date = activities_data.get('execution_start_date')
                if execution_start_date:
                    print(f"│  📅 Start date from activities.json: {execution_start_date}")
            except:
                pass
        
        # If still no execution start date, use today as default
        if not execution_start_date:
            execution_start_date = datetime.now().strftime("%Y-%m-%d")
            print(f"│  📅 No start date found, using today: {execution_start_date}")
        
        # Parse start date
        start_datetime = None
        for fmt in ["%B %d, %Y", "%Y-%m-%d", "%Y/%m/%d"]:
            try:
                start_datetime = datetime.strptime(execution_start_date, fmt)
                print(f"│  📅 Fetching history from: {start_datetime.strftime('%Y-%m-%d')}")
                break
            except:
                continue
        
        if not start_datetime:
            start_datetime = datetime.now()
            print(f"│  📅 Using current date as start: {start_datetime.strftime('%Y-%m-%d')}")
        
        # ============================================================
        # CONNECT TO MT5
        # ============================================================
        mt5_path = broker_cfg.get("TERMINAL_PATH", "")
        password = broker_cfg.get("PASSWORD", "")
        server = broker_cfg.get("SERVER", "")
        
        if not mt5.initialize(path=mt5_path):
            print(f"│   MT5 initialization failed: {mt5.last_error()}")
            continue
        
        acc = mt5.account_info()
        if acc is None or acc.login != int(login_id):
            print(f"│  🔌 Logging into account {login_id}...")
            if not mt5.login(int(login_id), password=password, server=server):
                print(f"│   Login failed: {mt5.last_error()}")
                mt5.shutdown()
                continue
            print(f"│  ✅ Successfully logged in")
        else:
            print(f"│  ✅ Already logged in")
        
        # Get MT5 account balance (actual broker balance)
        mt5_balance = mt5.account_info().balance
        print(f"│  💰 MT5 Actual Balance: ${mt5_balance:.2f}")
        
        # ============================================================
        # FETCH HISTORY DEALS (Magic Number Only)
        # ============================================================
        history_updated = 0
        
        # Initialize trades lists
        authorized_closed_trades = []
        unauthorized_trades_list = []
        won_trades = 0
        lost_trades = 0
        symbols_won = {}
        symbols_lost = {}
        total_authorized_profit = 0.0
        total_unauthorized_profit = 0.0
        
        if start_datetime:
            print(f"│\n├─ 📜 FETCHING HISTORY DEALS".ljust(79) + "┤")
            
            history_deals = mt5.history_deals_get(start_datetime, datetime.now())
            history_orders = mt5.history_orders_get(start_datetime, datetime.now())
            
            if history_deals:
                print(f"│  ✅ Found {len(history_deals)} deals, {len(history_orders or [])} orders")
                
                # Group deals by order ticket
                deals_by_order = {}
                for deal in history_deals:
                    order_key = deal.order if deal.order != 0 else f"{deal.symbol}_{deal.time}_{deal.price}"
                    if order_key not in deals_by_order:
                        deals_by_order[order_key] = []
                    deals_by_order[order_key].append(deal)
                
                print(f"│  📊 Grouped into {len(deals_by_order)} unique orders")
                
                # Process each order group
                for order_key, deals in deals_by_order.items():
                    deals.sort(key=lambda x: x.time)
                    
                    # Calculate totals
                    total_profit = sum(d.profit for d in deals)
                    total_commission = sum(d.commission for d in deals)
                    total_swap = sum(d.swap for d in deals)
                    total_pnl = total_profit + total_commission + total_swap
                    
                    # Find entry deal
                    entry_deal = next((d for d in deals if d.type in [0, 1]), None)
                    
                    # Determine if authorized based on Magic Number
                    is_authorized = False
                    trade_magic_number = None
                    if entry_deal:
                        trade_magic_number = entry_deal.magic
                        if trade_magic_number == authorized_magic_number:
                            is_authorized = True
                    
                    # Generate ticket ID for reference
                    ticket_id = None
                    if isinstance(order_key, int) and order_key != 0:
                        ticket_id = order_key
                    elif entry_deal and entry_deal.order != 0:
                        ticket_id = entry_deal.order
                    else:
                        ticket_id = abs(hash(order_key)) % 100000000
                    
                    # ================================================
                    # CREATE TRADE RECORD
                    # ================================================
                    if entry_deal and entry_deal.type in [0, 1]:
                        trade_record = {
                            'ticket': ticket_id,
                            'symbol': entry_deal.symbol,
                            'type': 'BUY' if entry_deal.type == 0 else 'SELL',
                            'volume': entry_deal.volume,
                            'profit': round(total_pnl, 2),
                            'time': datetime.fromtimestamp(entry_deal.time).strftime('%Y-%m-%d %H:%M:%S'),
                            'magic': trade_magic_number,
                            'unique_magicnumber': trade_magic_number,
                            'is_authorized': is_authorized
                        }
                        
                        if is_authorized:
                            authorized_closed_trades.append(trade_record)
                            total_authorized_profit += total_pnl
                            
                            if total_pnl > 0:
                                won_trades += 1
                                symbols_won[entry_deal.symbol] = symbols_won.get(entry_deal.symbol, 0.0) + total_pnl
                            elif total_pnl < 0:
                                lost_trades += 1
                                symbols_lost[entry_deal.symbol] = symbols_lost.get(entry_deal.symbol, 0.0) + total_pnl
                            
                            profit_symbol = "📈" if total_pnl > 0 else "📉" if total_pnl < 0 else "⚖️"
                            print(f"│     {profit_symbol} Authorized #{ticket_id}: ${total_pnl:.2f} [Magic: {trade_magic_number}]")
                        else:
                            trade_record['reason'] = f"Magic Number {trade_magic_number} != {authorized_magic_number}"
                            trade_record['unique_magicnumber'] = trade_magic_number
                            unauthorized_trades_list.append(trade_record)
                            total_unauthorized_profit += total_pnl
                            stats["unauthorized_trades_found"] += 1
                            profit_symbol = "🚫" if total_pnl > 0 else "🔴" if total_pnl < 0 else "⚠️"
                            print(f"│     {profit_symbol} UNAUTHORIZED #{ticket_id}: ${total_pnl:.2f} [Magic: {trade_magic_number}]")
                
                print(f"│\n├─ 📊 HISTORY SUMMARY")
                print(f"│  • Authorized trades: {len(authorized_closed_trades)} (Total P&L: ${total_authorized_profit:.2f})")
                print(f"│  • Unauthorized trades: {len(unauthorized_trades_list)} (Total P&L: ${total_unauthorized_profit:.2f})")
                
                stats["history_orders_recorded"] += len(authorized_closed_trades)
                stats["history_orders_updated"] += history_updated
                
            else:
                print(f"│  ℹ️ No history deals found")
        else:
            print(f"│  No execution start date - skipping history")
        
        # ============================================================
        # CHECK CURRENT ORDERS & POSITIONS (Magic Number Only)
        # ============================================================
        print(f"│\n├─ 🔄 CHECKING CURRENT STATE".ljust(79) + "┤")
        
        pending_orders = mt5.orders_get() or []
        open_positions = mt5.positions_get() or []
        
        print(f"│  📊 Pending orders: {len(pending_orders)} | Open positions: {len(open_positions)}")
        
        # Find unauthorized items
        unauthorized_orders = []
        unauthorized_positions = []
        
        for order in pending_orders:
            if order.magic != authorized_magic_number:
                unauthorized_orders.append({
                    'ticket': order.ticket,
                    'symbol': order.symbol,
                    'type': order.type,
                    'volume': order.volume_current,
                    'price': order.price_open,
                    'magic': order.magic,
                    'unique_magicnumber': order.magic,
                    'reason': f"Magic Number {order.magic} != {authorized_magic_number}"
                })
        
        for pos in open_positions:
            if pos.magic != authorized_magic_number:
                unauthorized_positions.append({
                    'ticket': pos.ticket,
                    'symbol': pos.symbol,
                    'type': 'BUY' if pos.type == 0 else 'SELL',
                    'volume': pos.volume,
                    'price': pos.price_open,
                    'profit': pos.profit,
                    'magic': pos.magic,
                    'unique_magicnumber': pos.magic,
                    'reason': f"Magic Number {pos.magic} != {authorized_magic_number}"
                })
        
        stats["unauthorized_orders_found"] += len(unauthorized_orders)
        stats["unauthorized_positions_found"] += len(unauthorized_positions)
        
        # ============================================================
        # CALCULATE CORRECT CURRENT BALANCE
        # ============================================================
        if starting_balance is not None:
            calculated_balance = starting_balance + total_authorized_profit
        else:
            calculated_balance = mt5_balance
            starting_balance = mt5_balance - total_authorized_profit
        
        profit_and_loss = total_authorized_profit
        
        print(f"│\n├─ 💰 BALANCE CALCULATION")
        print(f"│  • Starting Balance: ${starting_balance:.2f}")
        print(f"│  • Authorized Trades P&L: ${total_authorized_profit:.2f}")
        print(f"│  • Calculated Current Balance: ${calculated_balance:.2f}")
        print(f"│  • MT5 Actual Balance: ${mt5_balance:.2f}")
        
        balance_discrepancy = mt5_balance - calculated_balance
        if abs(balance_discrepancy) > 0.01:
            print(f"│  ⚠️  Balance discrepancy: ${balance_discrepancy:.2f} (from unauthorized trades/other operations)")
        
        # ============================================================
        # DETERMINE STATUS
        # ============================================================
        unauthorized_detected = (len(unauthorized_orders) > 0 or 
                                  len(unauthorized_positions) > 0 or 
                                  len(unauthorized_trades_list) > 0)
        
        if unauthorized_detected:
            if bypass_active:
                application_status = "approved_with_bypass"
                status_message = "⚠️ BYPASS ACTIVE - unauthorized actions allowed but flagged"
            else:
                application_status = "approved_with_issues"
                status_message = "⚠️ UNAUTHORIZED ACTIONS DETECTED - needs review"
        else:
            application_status = "approved"
            status_message = "✅ No unauthorized actions"
        
        # Determine unauthorized types
        unauthorized_type = set()
        if unauthorized_trades_list:
            unauthorized_type.add('trades')
        if unauthorized_orders:
            unauthorized_type.add('orders')
        if unauthorized_positions:
            unauthorized_type.add('positions')
        
        # ============================================================
        # UPDATE STATS
        # ============================================================
        if unauthorized_detected:
            stats["investors_with_unauthorized"] += 1
            stats["unauthorized_by_investor"][user_brokerid] = {
                'orders': len(unauthorized_orders),
                'positions': len(unauthorized_positions),
                'trades': len(unauthorized_trades_list)
            }
            
            print(f"│\n├─ 🚫 UNAUTHORIZED ITEMS FOUND")
            for order in unauthorized_orders[:3]:
                print(f"│     Order #{order['ticket']}: {order['symbol']} @ {order['price']} [Magic: {order['magic']}]")
            if len(unauthorized_orders) > 3:
                print(f"│     ... and {len(unauthorized_orders)-3} more orders")
            for pos in unauthorized_positions[:3]:
                print(f"│     Position #{pos['ticket']}: {pos['symbol']} ${pos['profit']:.2f} [Magic: {pos['magic']}]")
            if len(unauthorized_positions) > 3:
                print(f"│     ... and {len(unauthorized_positions)-3} more positions")
        else:
            print(f"│  ✅ No unauthorized items found")
        
        # ============================================================
        # UPDATE ACTIVITIES.JSON WITH NOTIFICATIONS
        # ============================================================
        print(f"│\n├─ 💾 SAVING ACTIVITIES.JSON WITH NOTIFICATIONS".ljust(79) + "┤")
        
        # Use existing activities or create new
        activities_data = existing_activities.copy() if existing_activities else {}
        
        # Ensure notification dictionaries exist
        if 'notifications' not in activities_data:
            activities_data['notifications'] = {}
        if 'executions_notification' not in activities_data:
            activities_data['executions_notification'] = {}
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # ============================================================
        # NOTIFICATION 1: UNAUTHORIZED TRADES
        # ============================================================
        if unauthorized_trades_list:
            unauthorized_count = len(unauthorized_trades_list)
            unauthorized_profit_total = sum(t.get('profit', 0) for t in unauthorized_trades_list)
            profit_symbol = "📈" if unauthorized_profit_total > 0 else "📉" if unauthorized_profit_total < 0 else "⚖️"
            
            trade_message = f"🚫 UNAUTHORIZED TRADES DETECTED: {unauthorized_count} unauthorized trade(s) found with total P&L {profit_symbol} ${abs(unauthorized_profit_total):.2f}. This trade does not match our authorized system activity."
            add_notification(activities_data['notifications'], 'UnauthorizedTrades', trade_message, 'error', timestamp)
            add_execution_notification(activities_data['executions_notification'], 'UnauthorizedTrades', f"SERVER NOTIFICATION: Investor {user_brokerid} has {unauthorized_count} unauthorized trades with total P&L ${unauthorized_profit_total:.2f}. Magic mismatch with authorized {authorized_magic_number}.", 'error', timestamp)
        
        # ============================================================
        # NOTIFICATION 2: UNAUTHORIZED ORDERS
        # ============================================================
        if unauthorized_orders:
            order_symbols = list(set(o['symbol'] for o in unauthorized_orders[:3]))
            order_message = f"⚠️ UNAUTHORIZED PENDING ORDERS: {len(unauthorized_orders)} unauthorized pending order(s) detected for symbol(s): {', '.join(order_symbols)}{'...' if len(unauthorized_orders) > 3 else ''}. These orders have Magic Numbers that do not match your authorized Magic Number ({authorized_magic_number}). Please review immediately."
            add_notification(activities_data['notifications'], 'UnauthorizedOrders', order_message, 'error', timestamp)
            add_execution_notification(activities_data['executions_notification'], 'UnauthorizedOrders', f"SERVER NOTIFICATION: Investor {user_brokerid} has {len(unauthorized_orders)} unauthorized pending orders. Authorized magic: {authorized_magic_number}", 'error', timestamp)
        
        # ============================================================
        # NOTIFICATION 3: UNAUTHORIZED POSITIONS
        # ============================================================
        if unauthorized_positions:
            position_profit = sum(p.get('profit', 0) for p in unauthorized_positions)
            profit_symbol = "📈" if position_profit > 0 else "📉" if position_profit < 0 else "⚖️"
            position_message = f"🔴 UNAUTHORIZED OPEN POSITIONS: {len(unauthorized_positions)} unauthorized open position(s) detected with current total P&L {profit_symbol} ${abs(position_profit):.2f}. These positions have Magic Numbers that do not match your authorized Magic Number ({authorized_magic_number})."
            add_notification(activities_data['notifications'], 'UnauthorizedPositions', position_message, 'error', timestamp)
            add_execution_notification(activities_data['executions_notification'], 'UnauthorizedPositions', f"SERVER NOTIFICATION: Investor {user_brokerid} has {len(unauthorized_positions)} unauthorized open positions with current P&L ${position_profit:.2f}. Authorized magic: {authorized_magic_number}", 'error', timestamp)
        
        # ============================================================
        # NOTIFICATION 4: BALANCE DISCREPANCY
        # ============================================================
        if abs(balance_discrepancy) > 0.01:
            discrepancy_type = "higher" if balance_discrepancy > 0 else "lower"
            discrepancy_message = f"💰 BALANCE MISMATCH DETECTED: Your calculated balance (${calculated_balance:.2f}) is {discrepancy_type} than your MT5 actual balance (${mt5_balance:.2f}) by ${abs(balance_discrepancy):.2f}. This indicates that an unauthorized activity has been taken.."
            add_notification(activities_data['notifications'], 'BalanceDiscrepancy', discrepancy_message, 'error', timestamp)
            add_execution_notification(activities_data['executions_notification'], 'BalanceDiscrepancy', f"SERVER NOTIFICATION: Investor {user_brokerid} balance discrepancy of ${abs(balance_discrepancy):.2f} detected. Calculated: ${calculated_balance:.2f}, MT5 Actual: ${mt5_balance:.2f}", 'error', timestamp)
        
        # ============================================================
        # NOTIFICATION 5: STATUS CHANGE
        # ============================================================
        if previous_application_status != application_status:
            if application_status == "approved_with_issues":
                status_message_text = f"⚠️ APPLICATION STATUS CHANGE: Your account status has changed from '{previous_application_status or 'unknown'}' to 'APPROVED WITH ISSUES'. Unauthorized actions have been detected in your account. Please contact support for review."
                add_notification(activities_data['notifications'], 'ApplicationStatus', status_message_text, 'error', timestamp)
                add_execution_notification(activities_data['executions_notification'], 'ApplicationStatus', f"SERVER NOTIFICATION: Investor {user_brokerid} status changed from {previous_application_status} to approved_with_issues due to unauthorized actions.", 'error', timestamp)
            elif application_status == "approved_with_bypass":
                status_message_text = f"⚠️ APPLICATION STATUS CHANGE: Your account status has changed from '{previous_application_status or 'unknown'}' to 'APPROVED WITH BYPASS'. Unauthorized actions are being automatically bypassed but are still being flagged for monitoring."
                add_notification(activities_data['notifications'], 'ApplicationStatus', status_message_text, 'error', timestamp)
                add_execution_notification(activities_data['executions_notification'], 'ApplicationStatus', f"SERVER NOTIFICATION: Investor {user_brokerid} status changed to approved_with_bypass. Bypass mode active.", 'error', timestamp)
            elif application_status == "approved" and previous_application_status in ["approved_with_issues", "approved_with_bypass"]:
                status_message_text = f"✅ APPLICATION STATUS RESTORED: Your account status has been restored to 'APPROVED'. No unauthorized actions are currently detected."
                add_notification(activities_data['notifications'], 'ApplicationStatus', status_message_text, 'success', timestamp)
                add_execution_notification(activities_data['executions_notification'], 'ApplicationStatus', f"SERVER NOTIFICATION: Investor {user_brokerid} status restored to approved. No unauthorized actions detected.", 'success', timestamp)
        
        # ============================================================
        # NOTIFICATION 6: AUDIT COMPLETION (only if status changed or unauthorized found)
        # ============================================================
        if unauthorized_detected or previous_application_status != application_status:
            audit_summary_parts = []
            if unauthorized_trades_list:
                audit_summary_parts.append(f"{len(unauthorized_trades_list)} trades")
            if unauthorized_orders:
                audit_summary_parts.append(f"{len(unauthorized_orders)} orders")
            if unauthorized_positions:
                audit_summary_parts.append(f"{len(unauthorized_positions)} positions")
            
            if audit_summary_parts:
                audit_message = f"🔍 AUDIT COMPLETED: System audit detected {', '.join(audit_summary_parts)} requiring attention. Please review your account activity."
                add_notification(activities_data['notifications'], 'AuditComplete', audit_message, 'error', timestamp)
                add_execution_notification(activities_data['executions_notification'], 'AuditComplete', f"SERVER NOTIFICATION: Investor {user_brokerid} audit completed. Found: {', '.join(audit_summary_parts)}", 'error', timestamp)
        
        # ============================================================
        # UPDATE CONTRACT DAYS LEFT (refresh from move function's logic)
        # ============================================================
        contract_days_left = "30"
        if execution_start_date:
            try:
                start = None
                for fmt in ["%Y-%m-%d", "%B %d, %Y", "%Y/%m/%d"]:
                    try: 
                        start = datetime.strptime(execution_start_date, fmt)
                        break
                    except: 
                        continue
                if start:
                    contract_duration = activities_data.get('contract_duration', 30)
                    if isinstance(contract_duration, str):
                        try:
                            contract_duration = int(contract_duration)
                        except:
                            contract_duration = 30
                    days_passed = (datetime.now() - start).days
                    contract_days_left = str(max(0, contract_duration - days_passed))
            except:
                pass
        
        # ============================================================
        # BUILD TRADES STRUCTURE
        # ============================================================
        trades_structure = {
            "summary": {
                "total_trades": len(authorized_closed_trades),
                "won": won_trades,
                "lost": lost_trades,
                "total_profit": round(total_authorized_profit, 2),
                "symbols_that_lost": {k: round(v, 2) for k, v in symbols_lost.items()},
                "symbols_that_won": {k: round(v, 2) for k, v in symbols_won.items()}
            },
            "authorized_closed_trades": authorized_closed_trades
        }
        
        # ============================================================
        # UPDATE ACTIVITIES.JSON WITH ALL DATA
        # ============================================================
        activities_data.update({
            'execution_start_date': execution_start_date,
            'broker_balance': round(starting_balance, 2),
            'profitandloss': round(profit_and_loss, 2),
            'current_balance': round(calculated_balance, 2),
            'mt5_actual_balance': round(mt5_balance, 2),
            'authorized_magic_number': authorized_magic_number,
            'unique_magicnumber': authorized_magic_number,
            'unauthorized_action_detected': unauthorized_detected,
            'bypass_restriction': bypass_active,
            'activate_autotrading': autotrading_active,
            'application_status': application_status,
            'contract_days_left': contract_days_left,
            'last_audit_timestamp': datetime.now().isoformat(),
            'unauthorized_actions': {
                'detected': unauthorized_detected,
                'bypass_active': bypass_active,
                'autotrading_active': autotrading_active,
                'type': list(unauthorized_type) if unauthorized_type else [],
                'unauthorized_withdrawals': [],
                'unauthorized_orders': unauthorized_orders,
                'unauthorized_positions': unauthorized_positions
            },
            'authorized_summary': {
                'authorized_magic_number': authorized_magic_number,
                'unique_magicnumber': authorized_magic_number,
                'authorized_trades_count': len(authorized_closed_trades),
                'authorized_trades_profit': round(total_authorized_profit, 2),
                'pending_orders': len(pending_orders),
                'open_positions': len(open_positions),
                'authorized_orders': len(pending_orders) - len(unauthorized_orders),
                'authorized_positions': len(open_positions) - len(unauthorized_positions),
                'unauthorized_orders': len(unauthorized_orders),
                'unauthorized_positions': len(unauthorized_positions),
                'unauthorized_trades': len(unauthorized_trades_list)
            }
        })
        
        # Save activities.json
        try:
            with open(activities_path, 'w', encoding='utf-8') as f:
                json.dump(activities_data, f, indent=4)
            print(f"│  ✅ activities.json saved with notifications")
            print(f"│     • Starting Balance: ${starting_balance:.2f}")
            print(f"│     • Current Balance: ${calculated_balance:.2f}")
            print(f"│     • P&L: ${profit_and_loss:.2f}")
            print(f"│     • Status: {application_status}")
            print(f"│     • Authorized Magic Number: {authorized_magic_number}")
            print(f"│     • Authorized trades: {trades_structure['summary']['total_trades']}")
            print(f"│     • Unauthorized trades: {len(unauthorized_trades_list)}")
            print(f"│     • Notifications added: {len(activities_data['notifications'])} total")
        except Exception as e:
            print(f"│   Error saving activities.json: {e}")
        
        # ============================================================
        # UPDATE UPDATED_INVESTORS.JSON WITH AUDIT DATA
        # ============================================================
        if user_brokerid in updated_investors_data:
            updated_record = updated_investors_data[user_brokerid].copy()
        else:
            updated_record = {}
        
        # Add audit-specific fields without overwriting existing data
        if 'audit_history' not in updated_record:
            updated_record['audit_history'] = []
        
        # Add this audit entry
        audit_entry = {
            'audit_timestamp': datetime.now().isoformat(),
            'application_status': application_status,
            'unauthorized_detected': unauthorized_detected,
            'unauthorized_orders_count': len(unauthorized_orders),
            'unauthorized_positions_count': len(unauthorized_positions),
            'balance_discrepancy': round(balance_discrepancy, 2) if abs(balance_discrepancy) > 0.01 else 0,
            'calculated_balance': round(calculated_balance, 2),
            'mt5_actual_balance': round(mt5_balance, 2),
            'profit_and_loss': round(profit_and_loss, 2),
            'authorized_trades_count': len(authorized_closed_trades)
        }
        
        updated_record['audit_history'].append(audit_entry)
        
        # Keep only last 10 audit entries
        if len(updated_record['audit_history']) > 10:
            updated_record['audit_history'] = updated_record['audit_history'][-10:]
        
        # Update current status fields
        updated_record['last_audit_status'] = application_status
        updated_record['last_audit_timestamp'] = datetime.now().isoformat()
        updated_record['current_unauthorized_detected'] = unauthorized_detected
        updated_record['current_balance'] = round(calculated_balance, 2)
        updated_record['current_pnl'] = round(profit_and_loss, 2)
        
        # Preserve notification data
        updated_record['notifications'] = activities_data.get('notifications', {})
        updated_record['executions_notification'] = activities_data.get('executions_notification', {})
        
        updated_investors_data[user_brokerid] = updated_record
        
        # Update stats
        stats["bypass_active_investors"] += 1 if bypass_active else 0
        stats["autotrading_active_investors"] += 1 if autotrading_active else 0
        
        # Print investor summary
        print(f"│\n├─ 📈 INVESTOR SUMMARY")
        print(f"│  • Status: {status_message}")
        print(f"│  • Application Status: {application_status}")
        print(f"│  • Authorized Magic Number: {authorized_magic_number}")
        print(f"│  • Starting Balance: ${starting_balance:.2f}")
        print(f"│  • Current Balance: ${calculated_balance:.2f}")
        print(f"│  • P&L: ${profit_and_loss:.2f}")
        print(f"│  • Authorized trades: {len(authorized_closed_trades)} ({won_trades}W/{lost_trades}L)")
        print(f"│  • Unauthorized trades: {len(unauthorized_trades_list)}")
        print(f"│  • Unauthorized items: {len(unauthorized_orders)} orders, {len(unauthorized_positions)} positions")
        print(f"│  • Contract Days Left: {contract_days_left}")
        
        # Shutdown MT5 connection for this investor
        mt5.shutdown()
    
    # ============================================================
    # SAVE UPDATED_INVESTORS.JSON
    # ============================================================
    if updated_investors_data:
        os.makedirs(os.path.dirname(UPDATED_INVESTORS), exist_ok=True)
        with open(UPDATED_INVESTORS, 'w', encoding='utf-8') as f:
            json.dump(updated_investors_data, f, indent=4)
        print(f"\n📝 Updated updated_investors.json with audit data for {len(updated_investors_data)} investors")
    
    # ============================================================
    # FINAL SUMMARY
    # ============================================================
    print("\n" + "="*80)
    print("  📊 FINAL SUMMARY".ljust(79) + "=")
    print("="*80)
    print(f"│  Investors processed:        {stats['investors_processed']}")
    print(f"│  Investors with unauthorized: {stats['investors_with_unauthorized']}")
    print(f"│  Authorized trades recorded: {stats['history_orders_recorded']}")
    print(f"│  Unauthorized trades found:  {stats['unauthorized_trades_found']}")
    print(f"│  Unauthorized orders found:  {stats['unauthorized_orders_found']}")
    print(f"│  Unauthorized positions found: {stats['unauthorized_positions_found']}")
    print(f"│  Bypass active:              {stats['bypass_active_investors']}")
    print(f"│  Auto-trading active:        {stats['autotrading_active_investors']}")
    
    if stats["unauthorized_by_investor"]:
        print(f"│\n├─ 🚫 UNAUTHORIZED BY INVESTOR")
        for inv_id, counts in stats["unauthorized_by_investor"].items():
            print(f"│    {inv_id}: {counts.get('trades', 0)} trades, {counts.get('orders', 0)} orders, {counts.get('positions', 0)} positions")
    
    print("="*80 + "\n")
    
    stats["processing_success"] = True
    return stats
#---         ----           --#

#    safety checks  #

def restricted_timerange(inv_id=None):
    """
    Function: Checks if current time falls within the restricted time range
    from accountmanagement.json.
    
    If no time range is configured or values are 0/0.00/00:00, there is NO RESTRICTION.
    
    Args:
        inv_id: Optional specific investor ID to process. If None, processes all investors.
        
    Returns:
        dict: Statistics about the time range check
    """
    global restricted_timerange_alert
    
    # Helper function to get the last message for a specific section
    def get_last_message(notifications_dict, section_key):
        """Get the most recent message for a specific section"""
        if not notifications_dict:
            return None
        
        latest_message = None
        latest_time = None
        latest_id = None
        
        for msg_id, msg_data in notifications_dict.items():
            if isinstance(msg_data, dict) and msg_data.get('section') == section_key:
                try:
                    msg_time = datetime.strptime(msg_data['time'], "%Y-%m-%d %H:%M:%S")
                    if latest_time is None or msg_time > latest_time:
                        latest_time = msg_time
                        latest_message = msg_data
                        latest_id = msg_id
                except:
                    pass
        
        if latest_message:
            return {
                'type': latest_message.get('type'),
                'time': latest_time,
                'id': latest_id,
                'data': latest_message
            }
        return None
    
    # Helper function to add notification with individual section tracking
    def add_notification(notifications_dict, section_key, message, message_type, timestamp=None):
        """Add notification with individual section tracking."""
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        last_msg = get_last_message(notifications_dict, section_key)
        
        should_add = False
        if last_msg is None:
            should_add = True
            print(f"      📝 No existing {section_key} notification, will add")
        else:
            if last_msg['type'] != message_type:
                should_add = True
                print(f"      📝 Type changed from {last_msg['type']} to {message_type}, will add")
        
        if not should_add:
            return False
        
        next_id = 1
        if notifications_dict:
            try:
                existing_ids = [int(k) for k in notifications_dict.keys() if k.isdigit()]
                next_id = max(existing_ids) + 1 if existing_ids else 1
            except:
                next_id = len(notifications_dict) + 1
        
        notifications_dict[str(next_id)] = {
            "section": section_key,
            "message": message,
            "time": timestamp,
            "type": message_type,
            "update": "new"
        }
        return True
    
    # Helper function to add execution notification
    def add_execution_notification(executions_dict, section_key, message, message_type, timestamp=None):
        """Add execution notification with individual section tracking."""
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        last_msg = get_last_message(executions_dict, section_key)
        
        should_add = False
        if last_msg is None:
            should_add = True
            print(f"      📝 No existing execution {section_key} notification, will add")
        else:
            if last_msg['type'] != message_type:
                should_add = True
                print(f"      📝 Execution type changed from {last_msg['type']} to {message_type}, will add")
        
        if not should_add:
            return False
        
        next_id = 1
        if executions_dict:
            try:
                existing_ids = [int(k) for k in executions_dict.keys() if k.isdigit()]
                next_id = max(existing_ids) + 1 if existing_ids else 1
            except:
                next_id = len(executions_dict) + 1
        
        executions_dict[str(next_id)] = {
            "section": section_key,
            "message": message,
            "time": timestamp,
            "type": message_type,
            "update": "new"
        }
        return True
    
    print(f"\n{'='*10} ⏰ RESTRICTED TIME CHECK {'='*10}")
    if inv_id:
        print(f" Investor: {inv_id}")

    current_time = datetime.now()

    if not mt5.terminal_info():
        print(f"  MT5 not connected")
        restricted_timerange_alert = {
            'is_triggered': False,
            'investor_id': inv_id if inv_id else "all",
            'reason': 'MT5 not connected',
            'timestamp': current_time.strftime('%I:%M:%S %p')
        }
        return {
            "investor_id": inv_id if inv_id else "all",
            "investors_checked": 0,
            "investors_in_window": 0,
            "processing_success": False,
            "current_time": current_time.strftime('%I:%M:%S %p'),
            "errors": ["MT5 not connected"]
        }
    
    stats = {
        "investor_id": inv_id if inv_id else "all",
        "investors_checked": 0,
        "investors_in_window": 0,
        "no_restriction_configured": 0,
        "notifications_added": 0,
        "processing_success": False,
        "current_time": current_time.strftime('%I:%M:%S %p'),
        "errors": []
    }
    
    any_in_window = False
    alert_details = {
        'investors_processed': [],
        'investors_in_window': [],
        'time_windows': {}
    }
    
    # Load updated_investors.json
    updated_investors_data = {}
    if os.path.exists(UPDATED_INVESTORS):
        try:
            with open(UPDATED_INVESTORS, 'r', encoding='utf-8') as f:
                updated_investors_data = json.load(f)
        except Exception as e:
            print(f"  Error loading updated_investors.json: {e}")
    
    investors_to_process = [inv_id] if inv_id else usersdictionary.keys()
    total_investors = len(investors_to_process) if not inv_id else 1
    processed = 0

    for user_brokerid in investors_to_process:
        processed += 1
        print(f"\n[{processed}/{total_investors}] ⏰ {user_brokerid}")
        
        inv_root = Path(INV_PATH) / user_brokerid
        acc_mgmt_path = inv_root / "accountmanagement.json"
        activities_path = inv_root / "activities.json"
        
        # Load existing activities.json
        existing_activities = {}
        if activities_path.exists():
            try:
                with open(activities_path, 'r', encoding='utf-8') as f:
                    existing_activities = json.load(f)
            except Exception as e:
                print(f"  Error reading activities.json: {e}")
        
        # Initialize with NO RESTRICTION (None means no restriction configured)
        window_start_hour = None
        window_start_minute = None
        window_end_hour = None
        window_end_minute = None
        time_range_config = None
        has_restriction = False
        
        # Load time range from accountmanagement.json ONLY if values exist and are valid (> 0)
        if acc_mgmt_path.exists():
            try:
                with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                settings = config.get("settings", {})
                time_range = settings.get("restrict_orders_in_time_range_of", {})
                
                if time_range and "from" in time_range and "to" in time_range:
                    from_str = time_range["from"]
                    to_str = time_range["to"]
                    
                    def is_zero_value(time_str):
                        if not time_str:
                            return True
                        # Clean up string to check numerical substance
                        clean = time_str.lower().strip().replace(" ", "").replace("am", "").replace("pm", "").replace(":", "")
                        try:
                            # If it converts cleanly to 0 numeric value (e.g. "0", "0.00", "0000")
                            if float(clean) == 0.0:
                                return True
                        except ValueError:
                            pass
                        return False

                    # Check if ANY value acts as a zero setup
                    if is_zero_value(from_str) or is_zero_value(to_str):
                        print(f"  ℹ️ Zero value detected in 'from' ({from_str}) or 'to' ({to_str}). Ignoring AM/PM. No restriction will be applied.")
                        has_restriction = False
                    elif from_str and to_str:
                        has_restriction = True
                        time_range_config = time_range
                        
                        def parse_time_string(time_str):
                            time_str = time_str.lower().strip().replace(" ", "")
                            is_pm = "pm" in time_str
                            is_am = "am" in time_str
                            clean_time = time_str.replace("pm", "").replace("am", "")
                            
                            if ":" in clean_time:
                                parts = clean_time.split(":")
                                hour = int(parts[0])
                                minute = int(parts[1]) if len(parts) > 1 else 0
                            else:
                                hour = int(clean_time)
                                minute = 0
                            
                            if is_pm and hour != 12:
                                hour += 12
                            elif is_am and hour == 12:
                                hour = 0
                            
                            return hour, minute
                        
                        try:
                            window_start_hour, window_start_minute = parse_time_string(from_str)
                            window_end_hour, window_end_minute = parse_time_string(to_str)
                            
                            # Handle midnight (12:00 am) as end of day
                            if window_end_hour == 0 and window_end_minute == 0:
                                window_end_hour = 23
                                window_end_minute = 59
                            
                            print(f"  📅 Loaded restriction: {from_str} -> {to_str} (parsed: {window_start_hour:02d}:{window_start_minute:02d} to {window_end_hour:02d}:{window_end_minute:02d})")
                        except Exception as e:
                            print(f"  Error parsing time strings: {e}")
                            has_restriction = False
            except Exception as e:
                print(f"  Error reading accountmanagement.json: {e}")
        
        # If no restriction configured or zeros stripped it out, skip and continue
        if not has_restriction:
            print(f"  ℹ️ NO RESTRICTION CONFIGURED - All trading allowed")
            stats["no_restriction_configured"] += 1
            
            current_time_window_status = "no_restriction"
            
            # Update activities.json with no restriction status
            activities_data = existing_activities.copy() if existing_activities else {}
            
            if 'notifications' not in activities_data:
                activities_data['notifications'] = {}
            if 'executions_notification' not in activities_data:
                activities_data['executions_notification'] = {}
            
            activities_data['time_window_status'] = current_time_window_status
            activities_data['time_window_details'] = {
                'has_restriction': False,
                'last_check': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'message': 'No time restriction configured - all trading allowed'
            }
            
            try:
                with open(activities_path, 'w', encoding='utf-8') as f:
                    json.dump(activities_data, f, indent=4)
                print(f"  ✅ activities.json updated (no restriction)")
            except Exception as e:
                print(f"  Error saving activities.json: {e}")
            
            # Update updated_investors.json
            if user_brokerid in updated_investors_data:
                updated_record = updated_investors_data[user_brokerid].copy()
            else:
                updated_record = {}
            
            updated_record['notifications'] = activities_data.get('notifications', {})
            updated_record['executions_notification'] = activities_data.get('executions_notification', {})
            updated_record['current_time_window_status'] = current_time_window_status
            updated_record['last_time_window_check'] = datetime.now().isoformat()
            updated_investors_data[user_brokerid] = updated_record
            
            stats["processing_success"] = True
            continue
        
        # Calculate window status (restriction exists and is valid)
        window_start_minutes = window_start_hour * 60 + window_start_minute
        window_end_minutes = window_end_hour * 60 + window_end_minute
        crosses_midnight = window_end_minutes < window_start_minutes
        current_time_minutes = current_time.hour * 60 + current_time.minute
        
        if crosses_midnight:
            is_within_window = (current_time_minutes >= window_start_minutes or 
                                current_time_minutes <= window_end_minutes)
        else:
            is_within_window = window_start_minutes <= current_time_minutes <= window_end_minutes
        
        def to_12hr(hour, minute):
            period = "AM" if hour < 12 else "PM"
            hour_12 = hour % 12
            if hour_12 == 0:
                hour_12 = 12
            return f"{hour_12}:{minute:02d} {period}"
        
        start_12hr = to_12hr(window_start_hour, window_start_minute)
        end_12hr = to_12hr(window_end_hour, window_end_minute)
        
        print(f"  Line Window: {start_12hr} - {end_12hr}")
        print(f"  🕐 Now: {current_time.strftime('%I:%M:%S %p')}")
        
        stats["investors_checked"] += 1
        
        current_time_window_status = "in_window" if is_within_window else "outside_window"
        
        if is_within_window:
            print(f"  🔴 WITHIN restricted time window - TRADING RESTRICTED")
            stats["investors_in_window"] += 1
            any_in_window = True
            expected_message_type = "warning"
            alert_details['investors_in_window'].append({
                'investor': user_brokerid,
                'time_window': f"{start_12hr} - {end_12hr}",
                'current_time': current_time.strftime('%I:%M:%S %p')
            })
        else:
            print(f"  ✅ Outside restricted window - TRADING ALLOWED")
            expected_message_type = "success"
        
        alert_details['time_windows'][user_brokerid] = {
            'start': f"{window_start_hour:02d}:{window_start_minute:02d}",
            'end': f"{window_end_hour:02d}:{window_end_minute:02d}",
            'is_in_window': is_within_window
        }
        alert_details['investors_processed'].append(user_brokerid)
        
        # ============================================================
        # UPDATE ACTIVITIES.JSON WITH NOTIFICATIONS
        # ============================================================
        activities_data = existing_activities.copy() if existing_activities else {}
        
        if 'notifications' not in activities_data:
            activities_data['notifications'] = {}
        if 'executions_notification' not in activities_data:
            activities_data['executions_notification'] = {}
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # CHECK CURRENT NOTIFICATION STATUS
        print(f"\n  🔍 Checking current notification status:")
        last_notification = get_last_message(activities_data['notifications'], 'RestrictedTimeWindow')
        last_execution = get_last_message(activities_data['executions_notification'], 'RestrictedTimeWindow')
        
        if last_notification:
            print(f"     Last notification type: {last_notification['type']}")
        else:
            print(f"     Last notification type: None")
        
        if last_execution:
            print(f"     Last execution type: {last_execution['type']}")
        else:
            print(f"     Last execution type: None")
        
        print(f"     Expected type for current status: {expected_message_type}")
        
        # ALWAYS try to add notification based on current status
        if is_within_window:
            # INSIDE restricted window - WARNING message
            window_message = f"⚠️ RESTRICTED TIME WINDOW: You are currently in the restricted trading window ({start_12hr} - {end_12hr}). Trading activities are LIMITED during this time. Current time: {current_time.strftime('%I:%M:%S %p')}"
            execution_message = f"SERVER NOTIFICATION: Investor {user_brokerid} is IN restricted time window ({start_12hr} - {end_12hr}) at {current_time.strftime('%I:%M:%S %p')}. Trading restrictions active."
            
            added = add_notification(activities_data['notifications'], 'RestrictedTimeWindow', window_message, 'warning', timestamp)
            if added:
                stats["notifications_added"] += 1
                print(f"  ✅ Added WARNING notification for 'in_window' status")
            
            added_exec = add_execution_notification(activities_data['executions_notification'], 'RestrictedTimeWindow', execution_message, 'warning', timestamp)
            if added_exec:
                stats["notifications_added"] += 1
                print(f"  ✅ Added execution WARNING notification for 'in_window' status")
        else:
            # OUTSIDE restricted window - SUCCESS message
            window_message = f"✅ NORMAL TRADING HOURS: You are outside the restricted trading window ({start_12hr} - {end_12hr}). Trading activities can proceed normally. Current time: {current_time.strftime('%I:%M:%S %p')}"
            execution_message = f"SERVER NOTIFICATION: Investor {user_brokerid} is OUTSIDE restricted time window ({start_12hr} - {end_12hr}) at {current_time.strftime('%I:%M:%S %p')}. Normal trading allowed."
            
            added = add_notification(activities_data['notifications'], 'RestrictedTimeWindow', window_message, 'success', timestamp)
            if added:
                stats["notifications_added"] += 1
                print(f"  ✅ Added SUCCESS notification for 'outside_window' status")
            
            added_exec = add_execution_notification(activities_data['executions_notification'], 'RestrictedTimeWindow', execution_message, 'success', timestamp)
            if added_exec:
                stats["notifications_added"] += 1
                print(f"  ✅ Added execution SUCCESS notification for 'outside_window' status")
        
        # Update time window status in activities.json
        activities_data['time_window_status'] = current_time_window_status
        activities_data['time_window_details'] = {
            'start_time': start_12hr,
            'end_time': end_12hr,
            'start_raw': f"{window_start_hour:02d}:{window_start_minute:02d}",
            'end_raw': f"{window_end_hour:02d}:{window_end_minute:02d}",
            'crosses_midnight': crosses_midnight,
            'has_restriction': True,
            'last_check': timestamp,
            'is_in_window': is_within_window
        }
        
        try:
            with open(activities_path, 'w', encoding='utf-8') as f:
                json.dump(activities_data, f, indent=4)
            print(f"\n  ✅ activities.json saved")
            print(f"     • Time window status: {current_time_window_status}")
            print(f"     • Notifications count: {len(activities_data['notifications'])}")
            print(f"     • Executions count: {len(activities_data['executions_notification'])}")
        except Exception as e:
            print(f"  Error saving activities.json: {e}")
        
        # ============================================================
        # UPDATE UPDATED_INVESTORS.JSON
        # ============================================================
        if user_brokerid in updated_investors_data:
            updated_record = updated_investors_data[user_brokerid].copy()
        else:
            updated_record = {}
        
        # Preserve notification data from activities.json
        updated_record['notifications'] = activities_data.get('notifications', {})
        updated_record['executions_notification'] = activities_data.get('executions_notification', {})
        updated_record['current_time_window_status'] = current_time_window_status
        updated_record['last_time_window_check'] = datetime.now().isoformat()
        updated_record['time_window_config'] = {
            'start': start_12hr,
            'end': end_12hr,
            'has_restriction': True
        }
        
        updated_investors_data[user_brokerid] = updated_record
        stats["processing_success"] = True

    # Save updated_investors.json
    if updated_investors_data:
        os.makedirs(os.path.dirname(UPDATED_INVESTORS), exist_ok=True)
        try:
            with open(UPDATED_INVESTORS, 'w', encoding='utf-8') as f:
                json.dump(updated_investors_data, f, indent=4)
            print(f"\n📝 Updated updated_investors.json")
        except Exception as e:
            print(f"\nError saving updated_investors.json: {e}")

    restricted_timerange_alert = {
        'is_triggered': any_in_window,
        'investor_id': inv_id if inv_id else "all",
        'timestamp': current_time.strftime('%I:%M:%S %p'),
        'investors_checked': stats['investors_checked'],
        'investors_in_window': stats['investors_in_window'],
        'no_restriction_configured': stats['no_restriction_configured'],
        'notifications_added': stats['notifications_added'],
        'investors_processed': alert_details['investors_processed'],
        'investors_in_window_details': alert_details['investors_in_window'],
        'time_windows': alert_details['time_windows']
    }

    print(f"\n{'='*10} 📊 SUMMARY {'='*10}")
    print(f"  Investors checked: {stats['investors_checked']}")
    print(f"  Investors with no restriction: {stats['no_restriction_configured']}")
    print(f"  Investors in restricted window: {stats['investors_in_window']}")
    print(f"  Notifications added this run: {stats['notifications_added']}")
    if stats['investors_in_window'] > 0:
        print(f"\n  ⚠️  ALERT: {stats['investors_in_window']} investor(s) currently in restricted time window")
    print(f"{'='*10} 🏁 COMPLETE {'='*10}\n")
    
    return stats

def investor_broker_symbols(inv_id=None):
    """
    Display and compare broker symbols with investor's configured symbols.
    Helps identify symbol naming mismatches.
    Records broker symbols to activities.json and updated_investors.json for each investor.
    
    Parameters:
    - inv_id: Optional investor ID to compare against their config
    
    Returns:
    - dict: Broker symbols info and comparison results
    """
    
    print(f"\n{'='*80}")
    print(f"🔍 BROKER SYMBOLS DIAGNOSTIC TOOL")
    print(f"{'='*80}\n")
    
    result = {
        'broker_symbols': [],
        'broker_symbols_lower': [],
        'investor_symbols': [],
        'matches': [],
        'close_matches': [],
        'suggestions': []
    }
    
    # Get all symbols from MT5
    if not mt5.terminal_info():
        print("MT5 is not initialized or not logged in!")
        print("   Make sure MT5 is connected first (call initialize() and login())")
        return result
    
    symbols = mt5.symbols_get()
    if not symbols:
        print(f"Failed to retrieve symbols: {mt5.last_error()}")
        return result
    
    # Extract all symbol names
    broker_symbols = [s.name for s in symbols]
    broker_symbols_lower = [s.lower() for s in broker_symbols]
    result['broker_symbols'] = broker_symbols
    result['broker_symbols_lower'] = broker_symbols_lower
    
    
    # ============================================================
    # RECORD BROKER SYMBOLS TO ACTIVITIES.JSON AND UPDATED_INVESTORS.JSON
    # ============================================================
    print(f"📝 RECORDING BROKER SYMBOLS TO JSON FILES:\n")
    
    # Determine which investors to process
    investors_to_process = [inv_id] if inv_id else list(usersdictionary.keys())
    
    if not investors_to_process:
        print("   No investors found to update")
    else:
        updated_count = 0
        
        # Load updated_investors.json
        updated_investors_data = {}
        if os.path.exists(UPDATED_INVESTORS):
            try:
                with open(UPDATED_INVESTORS, 'r', encoding='utf-8') as f:
                    updated_investors_data = json.load(f)
            except Exception as e:
                print(f"   Error loading updated_investors.json: {e}")
        
        for user_brokerid in investors_to_process:
            inv_root = Path(INV_PATH) / user_brokerid
            activities_path = inv_root / "activities.json"
            
            if not inv_root.exists():
                print(f"   ⚠️ Investor {user_brokerid}: Path not found - {inv_root}")
                continue
            
            # ============================================================
            # UPDATE ACTIVITIES.JSON
            # ============================================================
            activities_data = {}
            if activities_path.exists():
                try:
                    with open(activities_path, 'r', encoding='utf-8') as f:
                        activities_data = json.load(f)
                except Exception as e:
                    print(f"   ⚠️ Investor {user_brokerid}: Error reading activities.json - {e}")
            
            # Add broker_symbols field with ONLY total_symbols and symbols
            activities_data['broker_symbols'] = {
                'total_symbols': len(broker_symbols),
                'symbols': broker_symbols
            }
            
            # Save activities.json
            try:
                with open(activities_path, 'w', encoding='utf-8') as f:
                    json.dump(activities_data, f, indent=4)
                print(f"   ✅ Investor {user_brokerid}: Recorded {len(broker_symbols)} broker symbols to activities.json")
            except Exception as e:
                print(f"   Investor {user_brokerid}: Error saving activities.json - {e}")
            
            # ============================================================
            # UPDATE UPDATED_INVESTORS.JSON
            # ============================================================
            if user_brokerid in updated_investors_data:
                updated_record = updated_investors_data[user_brokerid].copy()
            else:
                updated_record = {}
            
            # Add broker_symbols field to updated record
            updated_record['broker_symbols'] = {
                'total_symbols': len(broker_symbols),
                'symbols': broker_symbols
            }
            
            # Preserve existing notifications
            if 'notifications' not in updated_record:
                updated_record['notifications'] = activities_data.get('notifications', {})
            if 'executions_notification' not in updated_record:
                updated_record['executions_notification'] = activities_data.get('executions_notification', {})
            
            updated_investors_data[user_brokerid] = updated_record
            updated_count += 1
        
        # Save updated_investors.json
        if updated_investors_data:
            os.makedirs(os.path.dirname(UPDATED_INVESTORS), exist_ok=True)
            try:
                with open(UPDATED_INVESTORS, 'w', encoding='utf-8') as f:
                    json.dump(updated_investors_data, f, indent=4)
            except Exception as e:
                print(f"\n   Error saving updated_investors.json: {e}")
        
        print(f"\n   📊 Updated {updated_count} investor(s) with broker symbols")
    
    print()
    
    # If investor ID provided, compare against their symbols
    if inv_id:
        # Load investor config
        if os.path.exists(INVESTOR_USERS):
            with open(INVESTOR_USERS, 'r', encoding='utf-8') as f:
                investor_users = json.load(f)
            
            investor_cfg = investor_users.get(inv_id)
            if investor_cfg:
                # Get symbols from investor's accountmanagement.json
                accountmanagement_path = os.path.join(INV_PATH, inv_id, "accountmanagement.json")
                
                if os.path.exists(accountmanagement_path):
                    with open(accountmanagement_path, 'r', encoding='utf-8') as f:
                        am_data = json.load(f)
                    
                    symbols_dict = am_data.get("symbols_dictionary", {})
                    investor_symbols = []
                    for category, symbol_list in symbols_dict.items():
                        if isinstance(symbol_list, list):
                            investor_symbols.extend(symbol_list)
                        elif isinstance(symbol_list, str):
                            investor_symbols.append(symbol_list)
                    
                    investor_symbols = list(set(investor_symbols))  # Remove duplicates
                    result['investor_symbols'] = investor_symbols
                    
                    
                    # Find matches and close matches
                    for inv_sym in investor_symbols:
                        inv_sym_lower = inv_sym.lower()
                        
                        # Exact match (case-insensitive)
                        if inv_sym_lower in broker_symbols_lower:
                            exact_match = broker_symbols[broker_symbols_lower.index(inv_sym_lower)]
                            result['matches'].append({
                                'config': inv_sym,
                                'broker': exact_match,
                                'type': 'exact'
                            })
                        # Close matches (containment or similarity)
                        else:
                            close_matches = []
                            for broker_sym in broker_symbols:
                                broker_lower = broker_sym.lower()
                                
                                # Check if config symbol is contained in broker symbol
                                if inv_sym_lower in broker_lower:
                                    close_matches.append(broker_sym)
                                # Check if broker symbol is contained in config symbol
                                elif broker_lower in inv_sym_lower:
                                    close_matches.append(broker_sym)
                                
                                # Check word-by-word (for symbols with spaces)
                                inv_words = set(inv_sym_lower.split())
                                broker_words = set(broker_lower.split())
                                if inv_words.intersection(broker_words) and len(inv_words) > 0:
                                    if broker_sym not in close_matches:
                                        close_matches.append(broker_sym)
                            
                            if close_matches:
                                result['close_matches'].append({
                                    'config': inv_sym,
                                    'broker_matches': close_matches[:5]
                                })
                                print(f"\n   🔍 CLOSE MATCHES for '{inv_sym}':")
                                for match in close_matches[:5]:
                                    print(f"      → {match}")
                                
                                # Generate suggestions
                                suggestions = []
                                for match in close_matches:
                                    if '_' in match:
                                        parts = match.split('_')
                                        for part in parts:
                                            if part.lower() in inv_sym_lower:
                                                suggestions.append(match)
                                                break
                                    elif match.isalpha() and inv_sym_lower in match.lower():
                                        suggestions.append(match)
                                
                                if suggestions:
                                    result['suggestions'].append({
                                        'config': inv_sym,
                                        'suggested': suggestions[:3]
                                    })
                                    print(f"   💡 SUGGESTION: Try using '{suggestions[0]}' instead of '{inv_sym}'")
                            else:
                                print(f"   NO MATCH found for '{inv_sym}'")
                    
                    print()
                    
                   
                    if len(result['matches']) == 0 and len(result['close_matches']) == 0:
                        print(f"\n   ⚠️ WARNING: No matches found at all!")
                        print(f"   💡 Common issues:")
                        print(f"      - Symbol name has spaces (MT5 usually uses underscores or no spaces)")
                        print(f"      - Wrong symbol case (though MT5 is usually case-insensitive)")
                        print(f"      - Symbol not available on this broker")
                        print(f"      - Need to add suffix like '.m' for mini contracts or '.ecn'")
                    
                else:
                    print(f"   accountmanagement.json not found for investor '{inv_id}'")
            else:
                print(f"   Investor '{inv_id}' not found in investors.json")
        else:
            print(f"   investors.json not found")
    
    print(f"{'='*80}\n")
    
    return result

def delete_all_orders_and_positions(inv_id=None):
    """
    Function: Deletes ALL pending orders and closes ALL open positions unconditionally.
    Uses EXISTING MT5 connection - does NOT initialize or shutdown MT5.
    
    This function removes all pending orders and closes all open positions for the specified
    investor(s) without any risk checks or conditions. Use with EXTREME CAUTION.
    
    Args:
        inv_id: Optional specific investor ID to process. If None, processes all investors.
        
    Returns:
        dict: Statistics about the deletion process
    """
    print(f"\n{'='*10} 🔥 EMERGENCY PURGE: DELETING ALL ORDERS & POSITIONS {'='*10}")
    if inv_id:
        print(f" Processing single investor: {inv_id}")

    # --- DATA INITIALIZATION ---
    stats = {
        "investor_id": inv_id if inv_id else "all",
        "pending_orders_found": 0,
        "pending_orders_deleted": 0,
        "pending_orders_failed": 0,
        "positions_found": 0,
        "positions_closed": 0,
        "positions_failed": 0,
        "processing_success": False,
        "errors": []
    }
    
    # ========== VERIFY EXISTING MT5 CONNECTION ==========
    if not mt5.terminal_info():
        print(f"  MT5 not connected. Cannot proceed.")
        stats["errors"].append("MT5 not connected")
        return stats
    
    print(f" ✅ Using existing MT5 connection")
    
    # Determine which investors to process
    investors_to_process = [inv_id] if inv_id else usersdictionary.keys()
    total_investors = len(investors_to_process) if not inv_id else 1
    processed = 0

    for user_brokerid in investors_to_process:
        processed += 1
        print(f"\n[{processed}/{total_investors}] 🔥 PURGING: {user_brokerid}")
        
        # Verify account
        acc_info = mt5.account_info()
        if not acc_info:
            print(f"  └─  Failed to get account info")
            stats["errors"].append(f"{user_brokerid}: Cannot fetch account info")
            continue
            
        print(f"  └─ ✅ Connected to account: {acc_info.login} | Balance: ${acc_info.balance:,.2f}")
        
        # --- STEP 1: DELETE ALL PENDING ORDERS ---
        print(f"\n  └─ 📋 STEP 1: Deleting ALL pending orders...")
        pending_orders = mt5.orders_get()
        
        if pending_orders:
            print(f"      • Found {len(pending_orders)} pending order(s)")
            stats["pending_orders_found"] = len(pending_orders)
            
            for order in pending_orders:
                order_type_name = "ORDER"
                if hasattr(order, 'type'):
                    order_type_names = {
                        mt5.ORDER_TYPE_BUY_LIMIT: "BUY LIMIT",
                        mt5.ORDER_TYPE_SELL_LIMIT: "SELL LIMIT",
                        mt5.ORDER_TYPE_BUY_STOP: "BUY STOP",
                        mt5.ORDER_TYPE_SELL_STOP: "SELL STOP",
                        mt5.ORDER_TYPE_BUY_STOP_LIMIT: "BUY STOP-LIMIT",
                        mt5.ORDER_TYPE_SELL_STOP_LIMIT: "SELL STOP-LIMIT"
                    }
                    order_type_name = order_type_names.get(order.type, f"Type {order.type}")
                
                print(f"      • Deleting {order_type_name} #{order.ticket} | {order.symbol} @ {order.price_open:.5f}")
                
                cancel_request = {
                    "action": mt5.TRADE_ACTION_REMOVE,
                    "order": order.ticket
                }
                result = mt5.order_send(cancel_request)
                
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    stats["pending_orders_deleted"] += 1
                    print(f"          ✅ Deleted successfully")
                else:
                    error_msg = result.comment if result else f"Error code: {mt5.last_error()}"
                    stats["pending_orders_failed"] += 1
                    stats["errors"].append(f"{user_brokerid}: Failed to delete order #{order.ticket}: {error_msg}")
                    print(f"           Delete failed: {error_msg}")
        else:
            print(f"      • No pending orders found")
        
        # --- STEP 2: CLOSE ALL OPEN POSITIONS ---
        print(f"\n  └─ 💼 STEP 2: Closing ALL open positions...")
        positions = mt5.positions_get()
        
        if positions:
            print(f"      • Found {len(positions)} open position(s)")
            stats["positions_found"] = len(positions)
            
            for position in positions:
                # Determine if position is buy or sell
                is_buy = position.type == mt5.POSITION_TYPE_BUY
                position_type = "BUY" if is_buy else "SELL"
                
                # Get current price
                tick = mt5.symbol_info_tick(position.symbol)
                if not tick:
                    stats["positions_failed"] += 1
                    stats["errors"].append(f"{user_brokerid}: Cannot get tick for {position.symbol}")
                    print(f"           Cannot get current price for {position.symbol}")
                    continue
                
                close_price = tick.bid if is_buy else tick.ask
                
                print(f"      • Closing {position_type} position #{position.ticket} | {position.symbol}")
                print(f"          Volume: {position.volume:.2f} | Open Price: {position.price_open:.5f} | Current: {close_price:.5f}")
                print(f"          Profit/Loss: ${position.profit:.2f}")
                
                close_request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": position.symbol,
                    "volume": position.volume,
                    "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
                    "position": position.ticket,
                    "price": close_price,
                    "deviation": 20,
                    "magic": position.magic if hasattr(position, 'magic') else 0
                }
                
                result = mt5.order_send(close_request)
                
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    stats["positions_closed"] += 1
                    print(f"          ✅ Closed successfully")
                else:
                    error_msg = result.comment if result else f"Error code: {mt5.last_error()}"
                    stats["positions_failed"] += 1
                    stats["errors"].append(f"{user_brokerid}: Failed to close position #{position.ticket}: {error_msg}")
                    print(f"           Close failed: {error_msg}")
        else:
            print(f"      • No open positions found")
        
        # --- INVESTOR SUMMARY ---
        print(f"\n  └─ 📊 Purge Results for {user_brokerid}:")
        print(f"      • Pending Orders: {stats['pending_orders_deleted']}/{stats['pending_orders_found']} deleted")
        if stats['pending_orders_failed'] > 0:
            print(f"           {stats['pending_orders_failed']} failed to delete")
        print(f"      • Positions: {stats['positions_closed']}/{stats['positions_found']} closed")
        if stats['positions_failed'] > 0:
            print(f"           {stats['positions_failed']} failed to close")
        
        stats["processing_success"] = True

    # --- FINAL SUMMARY ---
    print(f"\n{'='*10} 📊 EMERGENCY PURGE SUMMARY {'='*10}")
    print(f"   Investor(s) processed: {processed}/{total_investors}")
    print(f"   Total pending orders found: {stats['pending_orders_found']}")
    print(f"   Total pending orders deleted: {stats['pending_orders_deleted']}")
    print(f"   Total positions found: {stats['positions_found']}")
    print(f"   Total positions closed: {stats['positions_closed']}")
    
    if stats['pending_orders_failed'] > 0 or stats['positions_failed'] > 0:
        print(f"\n    ERRORS ENCOUNTERED: {len(stats['errors'])}")
        for error in stats['errors'][:5]:
            print(f"      • {error}")
        if len(stats['errors']) > 5:
            print(f"      • ... and {len(stats['errors']) - 5} more errors")
    
    total_actions = stats['pending_orders_deleted'] + stats['positions_closed']
    if total_actions > 0:
        print(f"\n   ✅ Successfully executed {total_actions} purge actions")
    else:
        print(f"\n   ℹ️  No orders or positions to purge")
    
    print(f"\n{'='*10} 🏁 EMERGENCY PURGE COMPLETE {'='*10}\n")
    
    return stats
#         --        #


#---   ##STRATEGY##  ----#   
def fetch_ohlc_data_for_investor(inv_id):
    """
    Fetch OHLCV data and generate charts for a specific investor.
    This function combines all OHLCV/chart generation functionality into one.
    
    ASSUMES: MT5 is already initialized and logged in by the caller (process_single_investor)
    
    Parameters:
    - inv_id: The investor ID to process
    
    Returns:
    - dict: Processing results including counts, errors, and status
    """
    
    
    # =========================================================================
    # CONSTANTS
    # =========================================================================
    
    # =========================================================================
    # HELPER FUNCTIONS (nested within main function)
    # =========================================================================
    
    def save_errors(error_log):
        """Save error log to JSON file."""
        try:
            os.makedirs(BASE_ERROR_FOLDER, exist_ok=True)
            with open(ERROR_JSON_PATH, 'w') as f:
                json.dump(error_log, f, indent=4)
        except Exception as e:
            print(f"Failed to save error log: {str(e)}")
            
    def load_investor_users():
        """Load investor users config from JSON file."""
        if not os.path.exists(INVESTOR_USERS):
            print(f"CRITICAL: {INVESTOR_USERS} NOT FOUND! Using empty config.")
            return {}

        try:
            with open(INVESTOR_USERS, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Convert numeric strings back to int where needed
            for investor_id, cfg in data.items():
                if "LOGIN_ID" in cfg and isinstance(cfg["LOGIN_ID"], str):
                    cfg["LOGIN_ID"] = cfg["LOGIN_ID"].strip()
                
                # Extract target folder from INVESTED_WITH (text after underscore)
                if "INVESTED_WITH" in cfg:
                    invested_with = cfg["INVESTED_WITH"]
                    if "_" in invested_with:
                        target_folder = invested_with.split("_", 1)[1]
                        cfg["TARGET_FOLDER"] = target_folder
                    else:
                        cfg["TARGET_FOLDER"] = invested_with
            
            return data

        except json.JSONDecodeError as e:
            print(f"Invalid JSON in investors.json: {e}")
            return {}
        except Exception as e:
            print(f"Failed to load investors.json: {e}")
            return {}
    
    def load_accountmanagement(investor_id):
        """Load account management config for a specific investor."""
        accountmanagement_path = os.path.join(INV_PATH, investor_id, "accountmanagement.json")
        
        if not os.path.exists(accountmanagement_path):
            print(f"   Investor {investor_id} | accountmanagement.json not found")
            return None, None
        
        try:
            with open(accountmanagement_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Extract bars value if present
            bars = data.get("bars")
            if bars is None:
                print(f"   Investor {investor_id} | 'bars' not defined in accountmanagement.json")
                return None, None
            
            # Validate bars is a positive integer
            if not isinstance(bars, int) or bars <= 0:
                print(f"   Investor {investor_id} | 'bars' must be a positive integer, got: {bars}")
                return None, None
            
            # Extract timeframe list (dynamic)
            timeframes = data.get("timeframe")
            if timeframes is None:
                print(f"   Investor {investor_id} | 'timeframe' not defined in accountmanagement.json")
                return None, None
            
            # Validate timeframe is a list
            if not isinstance(timeframes, list):
                print(f"   Investor {investor_id} | 'timeframe' must be a list, got: {type(timeframes)}")
                return None, None
            
            # Validate each timeframe is supported
            valid_timeframes = []
            for tf in timeframes:
                if tf in TIMEFRAME_MAP:
                    valid_timeframes.append(tf)
                else:
                    print(f"   Investor {investor_id} | Unsupported timeframe '{tf}', skipping")
            
            if not valid_timeframes:
                print(f"    Investor {investor_id} | No valid timeframes provided")
                return None, None
            
            print(f"  📊  Investor {investor_id} | Using bars={bars}, timeframes={valid_timeframes}")
            return bars, valid_timeframes
            
        except json.JSONDecodeError as e:
            print(f"    Investor {investor_id} | Invalid JSON in accountmanagement.json: {e}")
            return None, None
        except Exception as e:
            print(f"    Investor {investor_id} | Failed to load accountmanagement.json: {e}")
            return None, None
    
    def load_investor_symbols(investor_id):
        """Load symbols from accountmanagement.json for a specific investor."""
        accountmanagement_path = os.path.join(INV_PATH, investor_id, "accountmanagement.json")
        
        if not os.path.exists(accountmanagement_path):
            print(f"   Investor {investor_id} | accountmanagement.json not found")
            return []
        
        try:
            with open(accountmanagement_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Extract symbols from symbols_dictionary
            symbols_dict = data.get("symbols_dictionary", {})
            
            if not symbols_dict:
                print(f"   Investor {investor_id} | No symbols_dictionary found in accountmanagement.json")
                return []
            
            # Collect all symbols from all arrays in the dictionary
            all_symbols = []
            for category, symbol_list in symbols_dict.items():
                if isinstance(symbol_list, list):
                    all_symbols.extend(symbol_list)
                elif isinstance(symbol_list, str):
                    all_symbols.append(symbol_list)
            
            # Remove duplicates while preserving order
            unique_symbols = []
            seen = set()
            for symbol in all_symbols:
                if symbol not in seen:
                    unique_symbols.append(symbol)
                    seen.add(symbol)
            
            print(f"  📊  Investor {investor_id} | Loaded {len(unique_symbols)} symbols from accountmanagement.json")
            return unique_symbols
            
        except json.JSONDecodeError as e:
            print(f"    Investor {investor_id} | Invalid JSON in accountmanagement.json: {e}")
            return []
        except Exception as e:
            print(f"    Investor {investor_id} | Failed to load symbols from accountmanagement.json: {e}")
            return []
    
    def fetch_ohlcv_data(symbol, mt5_timeframe, bars):
        """Fetch OHLCV data including the currently forming candle (index 0)."""
        error_log = []
        lagos_tz = pytz.timezone('Africa/Lagos')
        timestamp = datetime.now(lagos_tz).strftime('%Y-%m-%d %H:%M:%S.%f%z')

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
            print(err_msg)
            return None, [{"error": err_msg, "timestamp": timestamp}]

        # --- Step 2: Fetch rates ---
        rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, bars)

        if rates is None or len(rates) == 0:
            last_err = mt5.last_error()
            err_msg = f"No data for {symbol}: {last_err}"
            print(err_msg)
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

        print(f"Fetched {available_bars} bars (including live candle) for {symbol}")
        return df, error_log
    
    def save_newest_oldest_df(df, symbol, timeframe_str, base_output_dir):
        """Save candles directly to base directory with filename: {symbol}_{timeframe}_candledetails.json"""
        error_log = []
        
        # Create filename with symbol and timeframe
        filename = f"{symbol}_{timeframe_str}_candledetails.json"
        file_path = os.path.join(base_output_dir, filename)
        
        lagos_tz = pytz.timezone('Africa/Lagos')
        now = datetime.now(lagos_tz)

        try:
            if len(df) < 2:
                error_msg = f"Not enough data for {symbol} ({timeframe_str})"
                print(error_msg)
                error_log.append({"error": error_msg, "timestamp": now.isoformat()})
                save_errors(error_log)
                return error_log

            # Prepare all candles (oldest first, newest last)
            all_candles = []
            for i, (ts, row) in enumerate(df.iterrows()):
                candle = row.to_dict()
                candle.update({
                    "time": ts.strftime('%Y-%m-%d %H:%M:%S'),
                    "candle_number": i,  # 0 = oldest
                    "symbol": symbol,
                    "timeframe": timeframe_str
                })
                all_candles.append(candle)

            # Save all candles to single JSON file
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(all_candles, f, indent=4)

            print(f"✓ {symbol} {timeframe_str} | JSON saved to {filename} | {len(all_candles)} candles")

        except Exception as e:
            err = f"save_newest_oldest_df failed: {str(e)}"
            print(err)
            error_log.append({"error": err, "timestamp": now.isoformat()})
            save_errors(error_log)

        return error_log
    
    def generate_and_save_chart(df, symbol, timeframe_str, base_output_dir):
        """Generate and save chart with filename: {symbol}_{timeframe}_chart.png directly in base directory."""
        error_log = []
        
        # Create filename with symbol and timeframe
        filename = f"{symbol}_{timeframe_str}_chart.png"
        chart_path = os.path.join(base_output_dir, filename)
        
        try:
            # Dynamic width calculation
            num_candles = len(df)
            
            # Configuration for readable candles
            MIN_CANDLE_WIDTH = 20
            MAX_CANDLE_WIDTH = 40
            MIN_CANDLE_SPACING = 10
            BASE_HEIGHT = 30
            MAX_IMAGE_WIDTH = 90000000
            
            # Determine optimal candle width based on number of candles
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
            
            # Apply constraints to candle width
            target_candle_width = max(base_candle_width, MIN_CANDLE_WIDTH)
            target_candle_width = min(target_candle_width, MAX_CANDLE_WIDTH)
            
            # Calculate spacing based on candle width and multiplier
            desired_spacing = target_candle_width * base_spacing_multiplier
            actual_spacing = max(desired_spacing, MIN_CANDLE_SPACING)
            
            # Calculate total width needed in pixels
            if num_candles > 1:
                total_width_pixels = actual_spacing * (num_candles - 1) + target_candle_width
            else:
                total_width_pixels = target_candle_width * 2
            
            # Add padding for margins
            padding_pixels = 200
            img_width_pixels = int(total_width_pixels + padding_pixels)
            img_width_pixels = min(img_width_pixels, MAX_IMAGE_WIDTH)
            
            min_width_pixels = 800
            if img_width_pixels < min_width_pixels:
                img_width_pixels = min_width_pixels
            
            # Convert pixels to inches for matplotlib
            img_width_inches = img_width_pixels / 100
            
            print(f"📊 {symbol} {timeframe_str} | {num_candles} candles → {img_width_pixels}px")
            
            # Chart style
            custom_style = mpf.make_mpf_style(
                base_mpl_style="default",
                marketcolors=mpf.make_marketcolors(
                    up="green", down="red", edge="inherit",
                    wick={"up": "green", "down": "red"}, volume="gray"
                )
            )

            # Check DataFrame columns
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
                    raise KeyError(f"Required column '{req_col}' not found. Available: {df_cols}")
            
            if col_mapping:
                df_plot = df.rename(columns={v: k for k, v in col_mapping.items()})
            else:
                df_plot = df

            # Generate and save chart
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

            print(f"✓ {symbol} {timeframe_str} | Chart saved to {filename} | {num_candles} candles")
            return chart_path, error_log

        except KeyError as e:
            print(f"Error in chart generation - column error: {e}")
            error_log.append(str(e))
            return None, error_log
        except Exception as e:
            print(f"Error in chart generation: {e}")
            error_log.append(str(e))
            return None, error_log
    
    def get_symbols_from_mt5():
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
            print(f"Failed to retrieve symbols: {mt5.last_error()}")
            return [], error_log

        available_symbols = [s.name for s in symbols]
        print(f"Retrieved {len(available_symbols)} symbols")
        return available_symbols, error_log
    
    def process_account_worker(investor_id, symbol_list, investor_timeframe_map, bars, base_output_dir):
        """Process symbols for a single investor."""
        processed_count = 0
        
        for symbol in symbol_list:
            try:
                print(f"  📈 Investor {investor_id} | Processing | {symbol} | bars={bars} | timeframes={list(investor_timeframe_map.keys())}")

                # Process only the timeframes specified in accountmanagement.json
                for tf_str, mt5_tf in investor_timeframe_map.items():
                    df, _ = fetch_ohlcv_data(symbol, mt5_tf, bars)
                    if df is not None and not df.empty:
                        df["symbol"] = symbol
                        
                        # Save candle details directly to base directory
                        save_newest_oldest_df(df, symbol, tf_str, base_output_dir)
                        
                        # Generate and save chart directly to base directory
                        chart_path, _ = generate_and_save_chart(df, symbol, tf_str, base_output_dir)
                        
                processed_count += 1
                print(f"  ✅ Investor {investor_id} | Completed | {symbol}")
                
            except Exception as e:
                print(f"   Investor {investor_id} | Error on {symbol}: {str(e)[:100]}")
                continue
        
        return processed_count
    
    # =========================================================================
    # MAIN EXECUTION FOR THE INVESTOR
    # =========================================================================
    
    print(f"\n{'='*80}")
    print(f"📊 FETCHING OHLCV DATA FOR INVESTOR: {inv_id}")
    print(f"{'='*80}")
    
    result = {
        'investor_id': inv_id,
        'success': False,
        'symbols_processed': 0,
        'total_symbols': 0,
        'errors': [],
        'output_directory': None
    }
    
    try:
        # Step 1: Load investor users configuration
        investor_users = load_investor_users()
        
        # Step 2: Get investor config
        investor_cfg = investor_users.get(inv_id)
        if not investor_cfg:
            print(f"    Investor {inv_id} | Config not found in investors.json")
            result['errors'].append("Investor config not found")
            return result
        
        # Step 3: Get target folder from INVESTED_WITH
        target_folder = investor_cfg.get("TARGET_FOLDER")
        if not target_folder:
            print(f"    Investor {inv_id} | SKIPPED - No TARGET_FOLDER extracted from INVESTED_WITH")
            result['errors'].append("No TARGET_FOLDER found")
            return result
        
        # Step 4: Load bars and timeframes from accountmanagement.json
        bars, timeframes = load_accountmanagement(inv_id)
        
        if bars is None or timeframes is None:
            print(f"    Investor {inv_id} | SKIPPED - Missing 'bars' or 'timeframe' in accountmanagement.json")
            result['errors'].append("Missing bars or timeframe configuration")
            return result
        
        # Step 5: Load symbols from accountmanagement.json
        symbol_list = load_investor_symbols(inv_id)
        
        if not symbol_list:
            print(f"   Investor {inv_id} | No symbols to process")
            result['errors'].append("No symbols found")
            return result
        
        result['total_symbols'] = len(symbol_list)
        
        # Step 6: Build dynamic timeframe map for this investor
        investor_timeframe_map = {}
        for tf in timeframes:
            if tf in TIMEFRAME_MAP:
                investor_timeframe_map[tf] = TIMEFRAME_MAP[tf]
        
        # Step 7: Create base output directory
        base_output_dir = os.path.join(INV_PATH, inv_id, target_folder)
        os.makedirs(base_output_dir, exist_ok=True)
        result['output_directory'] = base_output_dir
        
        # Step 8: MT5 is already initialized and logged in by process_single_investor
        print(f"  ✅ Using existing MT5 connection (initialized by process_single_investor)")

        # Step 9: Validate symbols against MT5 availability (CASE-INSENSITIVE FIX)
        mt5_symbols, _ = get_symbols_from_mt5()
        mt5_symbols_lower_map = {s.lower(): s for s in mt5_symbols}  # Create lookup map

        valid_symbols = []
        case_corrected_count = 0
        for sym in symbol_list:
            sym_lower = sym.lower()
            if sym_lower in mt5_symbols_lower_map:
                correct_symbol = mt5_symbols_lower_map[sym_lower]
                valid_symbols.append(correct_symbol)
                if sym != correct_symbol:
                    case_corrected_count += 1
                    print(f"  🔧 Investor {inv_id} | Case corrected: '{sym}' → '{correct_symbol}'")
            else:
                print(f"   Investor {inv_id} | Symbol '{sym}' not found in MT5")

        invalid_count = len(symbol_list) - len(valid_symbols)

        if case_corrected_count > 0:
            print(f"  ✅ Investor {inv_id} | Case-corrected {case_corrected_count} symbol(s)")

        if invalid_count > 0:
            print(f"   Investor {inv_id} | {len(valid_symbols)} valid / {len(symbol_list)} total symbols ({invalid_count} invalid)")

        if not valid_symbols:
            print(f"   Investor {inv_id} | No valid symbols to process")
            result['errors'].append("No valid symbols found on MT5")
            return result

        # Step 10: Process the symbols
        processed_count = process_account_worker(
            inv_id, 
            valid_symbols,  # Now contains exact broker symbols like "Volatility 75 Index"
            investor_timeframe_map, 
            bars, 
            base_output_dir
        )
                
        result['symbols_processed'] = processed_count
        result['success'] = processed_count > 0
        
        print(f"\n  🏁 Investor {inv_id} | Finished | {processed_count}/{len(valid_symbols)} symbols processed\n")
        
        return result
        
    except Exception as e:
        print(f"   Investor {inv_id} | Error in fetch_ohlc_data_for_investor: {str(e)}")
        traceback.print_exc()
        result['errors'].append(str(e))
        return result

def delete_unauthorized_symbol_files(inv_id):
    """
    Delete files for symbols not listed in the investor's accountmanagement.json.
    Checks and protects only the listed symbols, deletes unlisted symbols' files
    including JSON, PNG, and spread JSON files for all timeframes.
    
    Parameters:
    - inv_id: The investor ID to process
    
    Returns:
    - dict: Results including deleted files, protected files, and errors
    """
    
    # =========================================================================
    # CONSTANTS
    # =========================================================================
    DELETE_SLEEP_BETWEEN_FILES = 0.05  # Small delay between deletions
    
    # =========================================================================
    # HELPER FUNCTIONS
    # =========================================================================
    
    def load_investor_users():
        """Load investor users config from JSON file."""
        if not os.path.exists(INVESTOR_USERS):
            return {}
        
        try:
            with open(INVESTOR_USERS, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Extract target folder from INVESTED_WITH
            for investor_id, cfg in data.items():
                if "INVESTED_WITH" in cfg:
                    invested_with = cfg["INVESTED_WITH"]
                    if "_" in invested_with:
                        target_folder = invested_with.split("_", 1)[1]
                        cfg["TARGET_FOLDER"] = target_folder
                    else:
                        cfg["TARGET_FOLDER"] = invested_with
            
            return data
        except Exception:
            return {}
    
    def load_investor_symbols_and_timeframes(investor_id):
        """
        Load symbols and timeframes from accountmanagement.json.
        Returns tuple: (symbols_list, timeframes_list)
        """
        accountmanagement_path = os.path.join(INV_PATH, investor_id, "accountmanagement.json")
        
        if not os.path.exists(accountmanagement_path):
            print(f"   Investor {investor_id} | accountmanagement.json not found")
            return [], []
        
        try:
            with open(accountmanagement_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Extract symbols from symbols_dictionary
            symbols_dict = data.get("symbols_dictionary", {})
            symbols = []
            
            if symbols_dict:
                for category, symbol_list in symbols_dict.items():
                    if isinstance(symbol_list, list):
                        symbols.extend(symbol_list)
                    elif isinstance(symbol_list, str):
                        symbols.append(symbol_list)
            
            # Remove duplicates while preserving order
            unique_symbols = []
            seen = set()
            for symbol in symbols:
                if symbol not in seen:
                    unique_symbols.append(symbol)
                    seen.add(symbol)
            
            # Extract timeframes
            timeframes = data.get("timeframe", [])
            if isinstance(timeframes, str):
                timeframes = [timeframes]
            elif not isinstance(timeframes, list):
                timeframes = []
            
            print(f"  📊  Investor {investor_id} | Loaded {len(unique_symbols)} symbols, {len(timeframes)} timeframes")
            return unique_symbols, timeframes
            
        except Exception as e:
            print(f"   Investor {investor_id} | Failed to load config: {str(e)}")
            return [], []
    
    def get_target_folder(investor_id, investor_users):
        """Get target folder for the investor."""
        investor_cfg = investor_users.get(investor_id)
        if not investor_cfg:
            return None
        
        return investor_cfg.get("TARGET_FOLDER")
    
    def is_protected_file(filename, protected_symbols, timeframes):
        """
        Check if a file should be protected (kept) based on symbols and timeframes.
        
        File patterns to protect:
        - {symbol}_{timeframe}_candledetails.json
        - {symbol}_{timeframe}_chart.png
        - {symbol}_spread.json
        
        Returns: (is_protected, symbol, file_type)
        """
        # Pattern 1: {symbol}_spread.json
        if filename.endswith('_spread.json'):
            symbol = filename.replace('_spread.json', '')
            if symbol in protected_symbols:
                return True, symbol, 'spread_json'
            return False, symbol, 'spread_json'
        
        # Pattern 2: {symbol}_{timeframe}_candledetails.json
        if filename.endswith('_candledetails.json'):
            # Remove suffix
            base = filename.replace('_candledetails.json', '')
            # Split by underscore to separate symbol and timeframe
            parts = base.rsplit('_', 1)
            if len(parts) == 2:
                symbol, timeframe = parts
                if symbol in protected_symbols and timeframe in timeframes:
                    return True, symbol, 'candledetails_json'
            return False, base.split('_')[0] if '_' in base else base, 'candledetails_json'
        
        # Pattern 3: {symbol}_{timeframe}_chart.png
        if filename.endswith('_chart.png'):
            # Remove suffix
            base = filename.replace('_chart.png', '')
            # Split by underscore to separate symbol and timeframe
            parts = base.rsplit('_', 1)
            if len(parts) == 2:
                symbol, timeframe = parts
                if symbol in protected_symbols and timeframe in timeframes:
                    return True, symbol, 'chart_png'
            return False, base.split('_')[0] if '_' in base else base, 'chart_png'
        
        # Not a recognized file pattern - don't touch
        return True, None, 'unknown'
    
    def delete_file(file_path, filename):
        """Delete a file and return success status."""
        try:
            os.remove(file_path)
            print(f"      🗑️  DELETED: {filename}")
            return True
        except Exception as e:
            print(f"       Failed to delete {filename}: {str(e)[:100]}")
            return False
    
    # =========================================================================
    # MAIN EXECUTION
    # =========================================================================
    
    print(f"\n{'='*80}")
    print(f"🗑️  CLEANING UNAUTHORIZED SYMBOL FILES FOR INVESTOR: {inv_id}")
    print(f"{'='*80}")
    
    result = {
        'investor_id': inv_id,
        'success': False,
        'protected_files': [],
        'deleted_files': [],
        'errors': [],
        'total_files_found': 0,
        'output_directory': None
    }
    
    try:
        # Step 1: Load investor configuration
        investor_users = load_investor_users()
        if not investor_users:
            result['errors'].append("Failed to load investor users config")
            return result
        
        # Step 2: Get target folder
        target_folder = get_target_folder(inv_id, investor_users)
        if not target_folder:
            print(f"  ✗ Investor {inv_id} | No TARGET_FOLDER found")
            result['errors'].append("No TARGET_FOLDER found")
            return result
        
        # Step 3: Load authorized symbols and timeframes from accountmanagement.json
        authorized_symbols, authorized_timeframes = load_investor_symbols_and_timeframes(inv_id)
        
        if not authorized_symbols:
            print(f"   Investor {inv_id} | No authorized symbols found - will delete ALL symbol files!")
        
        if not authorized_timeframes:
            print(f"   Investor {inv_id} | No authorized timeframes found - will keep NO timeframe files!")
        
        # Step 4: Build output directory path
        output_dir = os.path.join(INV_PATH, inv_id, target_folder)
        
        if not os.path.exists(output_dir):
            print(f"   Investor {inv_id} | Output directory does not exist: {output_dir}")
            result['success'] = True  # Nothing to delete is considered success
            result['output_directory'] = output_dir
            return result
        
        result['output_directory'] = output_dir
        
        # Step 5: Scan directory for symbol files
        all_files = os.listdir(output_dir)
        
        # Filter for relevant files (JSON and PNG that match our patterns)
        relevant_files = []
        for filename in all_files:
            if (filename.endswith('_spread.json') or 
                filename.endswith('_candledetails.json') or 
                filename.endswith('_chart.png')):
                relevant_files.append(filename)
        
        result['total_files_found'] = len(relevant_files)
        
        if not relevant_files:
            print(f"  ✅ Investor {inv_id} | No symbol files found in {output_dir}")
            result['success'] = True
            return result
        
        print(f"  📂 Scanning {len(relevant_files)} files in: {output_dir}")
        print(f"  🛡️  Protected symbols: {authorized_symbols if authorized_symbols else 'NONE'}")
        print(f"  🛡️  Protected timeframes: {authorized_timeframes if authorized_timeframes else 'NONE'}")
        print()
        
        # Step 6: Process each file
        protected_set = set(authorized_symbols)
        timeframe_set = set(authorized_timeframes)
        
        for filename in relevant_files:
            file_path = os.path.join(output_dir, filename)
            
            # Check if file should be protected
            is_protected, symbol, file_type = is_protected_file(
                filename, 
                protected_set, 
                timeframe_set
            )
            
            if is_protected:
                print(f"      ✅ PROTECTED: {filename} (symbol: {symbol}, type: {file_type})")
                result['protected_files'].append({
                    'filename': filename,
                    'symbol': symbol,
                    'type': file_type
                })
            else:
                # Delete unauthorized file
                if delete_file(file_path, filename):
                    result['deleted_files'].append({
                        'filename': filename,
                        'symbol': symbol if symbol else 'unknown',
                        'type': file_type,
                        'reason': f"Symbol '{symbol}' not authorized" if symbol not in protected_set else f"Timeframe not authorized"
                    })
                else:
                    result['errors'].append(f"Failed to delete: {filename}")
                
                time.sleep(DELETE_SLEEP_BETWEEN_FILES)
        
        # Step 7: Summary
        print(f"\n{'='*80}")
        print(f"📊 CLEANUP SUMMARY FOR INVESTOR: {inv_id}")
        print(f"{'='*80}")
        print(f"  📂 Directory: {output_dir}")
        print(f"  🛡️  Protected files: {len(result['protected_files'])}")
        print(f"  🗑️  Deleted files: {len(result['deleted_files'])}")
        print(f"   Errors: {len(result['errors'])}")
        
        if result['deleted_files']:
            print(f"\n  Deleted files by type:")
            deleted_by_type = {}
            for deleted in result['deleted_files']:
                file_type = deleted['type']
                deleted_by_type[file_type] = deleted_by_type.get(file_type, 0) + 1
            for file_type, count in deleted_by_type.items():
                print(f"    - {file_type}: {count}")
        
        result['success'] = True
        return result
        
    except Exception as e:
        print(f"   Investor {inv_id} | Error in delete_unauthorized_symbol_files: {str(e)}")
        traceback.print_exc()
        result['errors'].append(str(e))
        return result
    
def directional_bias(inv_id=None):
    """
    Analyze directional bias based on the 2 most recent completed candles.
    Reads candle data from pre-generated JSON files.
    
    Checks for bullish (both green candles with higher highs/higher lows) or 
    bearish (both red candles with lower highs/lower lows) patterns.
    
    Timeframe is read from accountmanagement.json "timeframe" field (can be string or list).
    Supported timeframes: 1m, 5m, 15m, 30m, 45m, 1h, 2h, 4h (4h is max)
    
    Saves limit orders ONLY to: INV_PATH/{investor_id}/{strategy_name}/pending_orders/limit_orders.json
    Manages multiple orders per symbol/type: allows 2 orders, deletes oldest when 3rd appears.
    
    Args:
        inv_id: Optional specific investor ID to process
        
    Returns:
        dict: Statistics and signals for directional bias
    """
    print(f"\n{'='*10} 🧭  DIRECTIONAL BIAS ANALYSIS {'='*10}")
    if inv_id:
        print(f" Processing investor: {inv_id}")
    
    # Statistics for this run
    stats = {
        "investor_id": inv_id if inv_id else "all",
        "total_symbols": 0,
        "successful_symbols": 0,
        "failed_symbols": 0,
        "bullish_signals": 0,
        "bearish_signals": 0,
        "total_signals": 0,
        "signals_generated": False,
        "timeframes_used": [],
        "skipped_signals": 0,
        "cancelled_pending_orders": 0
    }
    
    def get_candle_center(candle):
        """Calculate center price of a candle using HIGH and LOW (not open/close)"""
        return (candle['high'] + candle['low']) / 2
    
    def normalize_symbol_for_filename(raw_symbol):
        """Remove special characters from symbol for filename"""
        normalized = raw_symbol.replace('+', '').replace('-', '').replace('.', '')
        return normalized
    
    def load_investor_config(investor_id):
        """Load investor configuration from accountmanagement.json"""
        acc_mgmt_path = Path(INV_PATH) / investor_id / "accountmanagement.json"
        
        if not acc_mgmt_path.exists():
            print(f" [{investor_id}]  Account management file not found")
            return None, None, None, None, None
        
        try:
            with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Get symbols dictionary
            symbols_dict = config.get("symbols_dictionary", {})
            if not symbols_dict:
                print(f" [{investor_id}] No symbols_dictionary found")
                return None, None, None, None, None
            
            # Get timeframe (can be string or list)
            timeframe_config = config.get("timeframe", "15m")
            
            # Convert to list if it's a string
            if isinstance(timeframe_config, str):
                timeframes = [timeframe_config]
            elif isinstance(timeframe_config, list):
                timeframes = timeframe_config
            else:
                print(f" [{investor_id}] Invalid timeframe format: {type(timeframe_config)}")
                return None, None, None, None, None
            
            # Validate timeframes
            valid_timeframes = []
            for tf in timeframes:
                if tf in TIMEFRAME_MAP:
                    valid_timeframes.append(tf)
                else:
                    print(f" [{investor_id}] Unsupported timeframe '{tf}', skipping")
            
            if not valid_timeframes:
                print(f" [{investor_id}]  No valid timeframes provided")
                return None, None, None, None, None
            
            print(f" [{investor_id}] 📊 Using timeframes: {valid_timeframes}")
            
            # Get selected risk reward
            selected_risk_reward = config.get("selected_risk_reward", [1])
            if isinstance(selected_risk_reward, list) and len(selected_risk_reward) > 0:
                risk_reward = selected_risk_reward[0]
            else:
                risk_reward = 1
            
            print(f" [{investor_id}] 📈 Risk/Reward: {risk_reward}")
            
            # Get target folder and strategy name from investor config using GLOBAL FETCHED_INVESTORS
            target_folder = None
            strategy_name = None
            
            # Use the global FETCHED_INVESTORS variable
            if FETCHED_INVESTORS:
                try:
                    with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
                        investor_users = json.load(f)
                    
                    investor_cfg = investor_users.get(investor_id)
                    if investor_cfg:
                        invested_with = investor_cfg.get("INVESTED_WITH", "")
                        if "_" in invested_with:
                            target_folder = invested_with.split("_", 1)[1]
                            strategy_name = target_folder
                        else:
                            target_folder = invested_with
                            strategy_name = invested_with
                except Exception as e:
                    print(f" [{investor_id}] Error reading verified investors: {e}")
            
            if not target_folder:
                print(f" [{investor_id}] No TARGET_FOLDER found, using 'prices'")
                target_folder = "prices"
                strategy_name = "prices"
            
            print(f" [{investor_id}] 📁 Strategy name: {strategy_name}")
            
            return symbols_dict, valid_timeframes, target_folder, risk_reward, strategy_name
            
        except Exception as e:
            print(f" [{investor_id}]  Error loading config: {e}")
            import traceback
            traceback.print_exc()
            return None, None, None, None, None
    
    def load_candle_data(investor_id, symbol, timeframe, target_folder):
        """Load candle data from pre-generated JSON file"""
        normalized_symbol = normalize_symbol_for_filename(symbol)
        
        filename = f"{normalized_symbol}_{timeframe}_candledetails.json"
        file_path = Path(INV_PATH) / investor_id / target_folder / filename
        
        if not file_path.exists():
            filename_original = f"{symbol}_{timeframe}_candledetails.json"
            file_path = Path(INV_PATH) / investor_id / target_folder / filename_original
            
            if not file_path.exists():
                return None, f"File not found: {filename} or {filename_original}"
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                candles = json.load(f)
            
            if len(candles) < 3:
                return None, f"Only {len(candles)} candles available (need at least 3)"
            
            current_candle = candles[-1]
            candle_2 = candles[-2]
            candle_1 = candles[-3]
            
            return {
                'current': current_candle,
                'candle_2': candle_2,
                'candle_1': candle_1
            }, None
            
        except Exception as e:
            return None, f"Error reading {filename}: {e}"
    
    def print_candle_details(symbol, timeframe, candle_data, digits):
        """Print detailed candle information"""
        current = candle_data['current']
        candle_2 = candle_data['candle_2']
        candle_1 = candle_data['candle_1']
        
        print(f"\n  📊 {symbol} [{timeframe}]")
        print(f"  ┌{'─' * 65}")
        print(f"  │ 🔄 CURRENT FORMING CANDLE:")
        print(f"  │    Time: {current.get('time', 'N/A')}")
        print(f"  │    Open: {current.get('open', 0):.{digits}f}")
        print(f"  │    High: {current.get('high', 0):.{digits}f}")
        print(f"  │    Low:  {current.get('low', 0):.{digits}f}")
        print(f"  │    Close:{current.get('close', 0):.{digits}f}")
        print(f"  │")
        
        candle_type = "🟢 BULLISH" if candle_2['close'] > candle_2['open'] else "🔴 BEARISH"
        print(f"  │ ✅ CANDLE 2 (Most Recent Completed): {candle_type}")
        print(f"  │    Time: {candle_2.get('time', 'N/A')}")
        print(f"  │    Open: {candle_2['open']:.{digits}f}")
        print(f"  │    High: {candle_2['high']:.{digits}f}")
        print(f"  │    Low:  {candle_2['low']:.{digits}f}")
        print(f"  │    Close:{candle_2['close']:.{digits}f}")
        print(f"  │")
        
        candle_type = "🟢 BULLISH" if candle_1['close'] > candle_1['open'] else "🔴 BEARISH"
        print(f"  │ 📊 CANDLE 1 (Second Most Recent): {candle_type}")
        print(f"  │    Time: {candle_1.get('time', 'N/A')}")
        print(f"  │    Open: {candle_1['open']:.{digits}f}")
        print(f"  │    High: {candle_1['high']:.{digits}f}")
        print(f"  │    Low:  {candle_1['low']:.{digits}f}")
        print(f"  │    Close:{candle_1['close']:.{digits}f}")
        print(f"  └{'─' * 65}")
    
    def calculate_exit_price(bias_type, candle_data, digits):
        """
        Calculate exit price based on bias type and current forming candle
        
        For bullish: 
          - Default exit: high price of candle 2
          - If current candle's high > candle 2 high, use current candle's high instead
        
        For bearish:
          - Default exit: low price of candle 2
          - If current candle's low < candle 2 low, use current candle's low instead
        """
        candle_2 = candle_data['candle_2']
        current_candle = candle_data['current']
        
        if bias_type == 'bullish':
            exit_price = candle_2['high']
            if current_candle['high'] > candle_2['high']:
                exit_price = current_candle['high']
                print(f"     📈 Exit updated: Current candle high ({current_candle['high']:.{digits}f}) > Candle 2 high ({candle_2['high']:.{digits}f})")
            else:
                print(f"     📈 Exit (Candle 2 high): {exit_price:.{digits}f}")
        else:
            exit_price = candle_2['low']
            if current_candle['low'] < candle_2['low']:
                exit_price = current_candle['low']
                print(f"     📉 Exit updated: Current candle low ({current_candle['low']:.{digits}f}) < Candle 2 low ({candle_2['low']:.{digits}f})")
            else:
                print(f"     📉 Exit (Candle 2 low): {exit_price:.{digits}f}")
        
        return exit_price
    
    def manage_existing_orders(investor_root, symbol, order_type, new_signal_time):
        """
        Manage existing pending orders for a specific symbol with matching order type.
        NEW LOGIC:
        - Allows up to 2 orders of the same type
        - If 3rd order appears, delete the OLDEST (earliest timestamp) from MT5 and local storage
        - Returns: (cancelled_count, orders_to_keep, is_first_order, is_second_order)
        """
        cancelled_count = 0
        orders_to_keep = []
        is_first_order = False
        is_second_order = False
        
        try:
            # Ensure MT5 is initialized
            if not mt5.terminal_info():
                if not mt5.initialize():
                    print(f"     Failed to initialize MT5, skipping order management")
                    return 0, [], False, False
            
            # Get all pending orders
            pending_orders = mt5.orders_get()
            if not pending_orders:
                print(f"     📭 No existing pending orders found")
                is_first_order = True  # This will be the first order
                return 0, [], is_first_order, is_second_order
            
            # Collect matching orders with their timestamps
            matching_orders = []
            for order in pending_orders:
                order_symbol = order.symbol
                order_type_int = order.type
                
                # Map MT5 order type to string
                order_type_str = None
                if order_type_int == mt5.ORDER_TYPE_BUY_STOP:
                    order_type_str = "buy_stop"
                elif order_type_int == mt5.ORDER_TYPE_SELL_STOP:
                    order_type_str = "sell_stop"
                else:
                    continue
                
                # Check if symbol matches
                normalized_order_symbol = normalize_symbol_for_filename(order_symbol)
                normalized_target_symbol = normalize_symbol_for_filename(symbol)
                
                symbol_matches = (order_symbol == symbol or normalized_order_symbol == normalized_target_symbol)
                
                if symbol_matches and order_type_str == order_type:
                    # Get order time (using creation time if available, otherwise current time)
                    order_time = getattr(order, 'time_setup', None) or getattr(order, 'time_done', None) or order.time_expiration
                    matching_orders.append({
                        'ticket': order.ticket,
                        'price': order.price_open,
                        'time': order_time,
                        'order_obj': order
                    })
            
            # Sort by time (oldest first)
            matching_orders.sort(key=lambda x: x['time'] if x['time'] else 0)
            
            order_count = len(matching_orders)
            print(f"     📊 Found {order_count} existing {order_type} orders for {symbol}")
            
            # Determine order flags based on count
            if order_count == 0:
                is_first_order = True
                print(f"     🆕 No existing orders - this will be the FIRST order")
                return 0, [], is_first_order, is_second_order
            elif order_count == 1:
                is_second_order = True
                print(f"     📌 One existing order - this will be the SECOND order")
                orders_to_keep = matching_orders  # Keep the existing one
                return 0, orders_to_keep, is_first_order, is_second_order
            elif order_count == 2:
                # We have 2 orders already, need to delete the oldest (first) to make room for new one
                oldest_order = matching_orders[0]  # Oldest
                newest_existing = matching_orders[1]  # Newest existing
                
                print(f"     Already have 2 orders. Deleting OLDEST order from {datetime.fromtimestamp(oldest_order['time']).strftime('%Y-%m-%d %H:%M:%S') if oldest_order['time'] else 'unknown time'}")
                print(f"     📌 Keeping NEWEST order from {datetime.fromtimestamp(newest_existing['time']).strftime('%Y-%m-%d %H:%M:%S') if newest_existing['time'] else 'unknown time'}")
                
                # Delete the oldest order from MT5
                delete_request = {
                    "action": mt5.TRADE_ACTION_REMOVE,
                    "order": oldest_order['ticket'],
                }
                
                result = mt5.order_send(delete_request)
                
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    print(f"     ✅ DELETED oldest pending order: #{oldest_order['ticket']} ({symbol}) {order_type} @ {oldest_order['price']}")
                    cancelled_count += 1
                    # Keep the newest existing order
                    orders_to_keep = [newest_existing]
                    is_second_order = True  # New order will be second
                else:
                    error_msg = result.comment if result else f"Error code: {result.retcode if result else 'Unknown'}"
                    print(f"     Could not delete oldest order #{oldest_order['ticket']}: {error_msg}")
                    # If deletion fails, keep both and don't add new order
                    orders_to_keep = matching_orders
                    is_second_order = False
                
                return cancelled_count, orders_to_keep, is_first_order, is_second_order
            else:
                # More than 2 orders (unusual), delete all but the newest one
                print(f"     Found {order_count} orders (more than expected). Cleaning up...")
                orders_to_keep_temp = []
                for idx, order_info in enumerate(matching_orders):
                    if idx == order_count - 1:  # Keep the newest
                        orders_to_keep_temp.append(order_info)
                    else:
                        # Delete older orders
                        delete_request = {
                            "action": mt5.TRADE_ACTION_REMOVE,
                            "order": order_info['ticket'],
                        }
                        result = mt5.order_send(delete_request)
                        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                            print(f"     ✅ DELETED order: #{order_info['ticket']}")
                            cancelled_count += 1
                
                orders_to_keep = orders_to_keep_temp
                if len(orders_to_keep) == 0:
                    is_first_order = True
                elif len(orders_to_keep) == 1:
                    is_second_order = True
                
                return cancelled_count, orders_to_keep, is_first_order, is_second_order
            
        except Exception as e:
            print(f"     Error managing pending orders: {e}")
            import traceback
            traceback.print_exc()
            return 0, [], False, False
    
    def is_candle_time_already_recorded(records_file, symbol, timeframe, current_candle_time):
        """Check if the current forming candle time is already recorded"""
        if not records_file.exists():
            return False
        
        try:
            with open(records_file, 'r', encoding='utf-8') as f:
                records = json.load(f)
            
            for record in records:
                if (record.get('symbol') == symbol and 
                    record.get('timeframe') == timeframe and 
                    record.get('current_candle_time') == current_candle_time):
                    return True
            return False
        except Exception as e:
            print(f"     Error reading records file: {e}")
            return False
    
    def save_candle_time_record(records_file, symbol, timeframe, current_candle_time, signal_info, candle_data, digits, order_flags):
        """
        Save the current forming candle time record after generating a signal.
        Also saves candle_1 and candle_2 details with their tags and order flags.
        """
        try:
            if records_file.exists():
                with open(records_file, 'r', encoding='utf-8') as f:
                    records = json.load(f)
            else:
                records = []
            
            # Extract candle data
            candle_1 = candle_data['candle_1']
            candle_2 = candle_data['candle_2']
            current_candle = candle_data['current']
            
            new_record = {
                "symbol": symbol,
                "timeframe": timeframe,
                "current_candle_time": current_candle_time,
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "signal_type": signal_info.get('order_type'),
                "entry_price": signal_info.get('entry'),
                "exit_price": signal_info.get('exit'),
                # Order management flags
                "order_flags": order_flags,
                # Current forming candle details
                "current_candle": {
                    "time": current_candle.get('time', ''),
                    "open": round(current_candle['open'], digits),
                    "high": round(current_candle['high'], digits),
                    "low": round(current_candle['low'], digits),
                    "close": round(current_candle['close'], digits)
                },
                # Candle 1 (second most recent) details
                "candle_1": {
                    "time": candle_1.get('time', ''),
                    "open": round(candle_1['open'], digits),
                    "high": round(candle_1['high'], digits),
                    "low": round(candle_1['low'], digits),
                    "close": round(candle_1['close'], digits),
                    "type": "bullish" if candle_1['close'] > candle_1['open'] else "bearish"
                },
                # Candle 2 (most recent completed) details
                "candle_2": {
                    "time": candle_2.get('time', ''),
                    "open": round(candle_2['open'], digits),
                    "high": round(candle_2['high'], digits),
                    "low": round(candle_2['low'], digits),
                    "close": round(candle_2['close'], digits),
                    "type": "bullish" if candle_2['close'] > candle_2['open'] else "bearish"
                }
            }
            
            records.append(new_record)
            
            with open(records_file, 'w', encoding='utf-8') as f:
                json.dump(records, f, indent=4)
            
            print(f"     📝 Recorded candle time: {current_candle_time}")
            print(f"     📝 Recorded candle_1 and candle_2 details")
            print(f"     🏷️ Order flags: {order_flags}")
            return True
        except Exception as e:
            print(f"     Error saving candle time record: {e}")
            return False
    
    def analyze_directional_bias(candle_data, symbol, digits):
        """Analyze directional bias based on the 2 most recent completed candles"""
        candle_1 = candle_data['candle_1']
        candle_2 = candle_data['candle_2']
        
        # Check for bullish pattern
        candle_2_bullish = candle_2['close'] > candle_2['open']
        candle_1_bullish = candle_1['close'] > candle_1['open']
        
        print(f"\n  🔍 PATTERN CHECK:")
        print(f"     Candle 2 Bullish: {candle_2_bullish} (Close: {candle_2['close']:.{digits}f} > Open: {candle_2['open']:.{digits}f})")
        print(f"     Candle 1 Bullish: {candle_1_bullish} (Close: {candle_1['close']:.{digits}f} > Open: {candle_1['open']:.{digits}f})")
        
        if candle_2_bullish and candle_1_bullish:
            print(f"     Both candles are bullish, checking higher highs/lows...")
            print(f"     Candle 2 High: {candle_2['high']:.{digits}f} > Candle 1 High: {candle_1['high']:.{digits}f}: {candle_2['high'] > candle_1['high']}")
            print(f"     Candle 2 Low: {candle_2['low']:.{digits}f} > Candle 1 Low: {candle_1['low']:.{digits}f}: {candle_2['low'] > candle_1['low']}")
            
            if candle_2['high'] > candle_1['high'] and candle_2['low'] > candle_1['low']:
                entry_price = get_candle_center(candle_1)
                exit_price = calculate_exit_price('bullish', candle_data, digits)
                
                print(f"\n  ✅ BULLISH PATTERN DETECTED")
                print(f"     • Entry (Candle 1 Center): {entry_price:.{digits}f}")
                print(f"     • Exit: {exit_price:.{digits}f}")
                print(f"     • Order Type: sell_stop")
                
                # Get candle types
                candle_1_type = "bullish" if candle_1['close'] > candle_1['open'] else "bearish"
                candle_2_type = "bullish" if candle_2['close'] > candle_2['open'] else "bearish"
                
                return 'bullish', entry_price, exit_price, candle_1, candle_2, candle_1_type, candle_2_type
            else:
                print(f"      Failed higher highs/lows condition")
        
        # Check for bearish pattern
        candle_2_bearish = candle_2['close'] < candle_2['open']
        candle_1_bearish = candle_1['close'] < candle_1['open']
        
        print(f"     Candle 2 Bearish: {candle_2_bearish} (Close: {candle_2['close']:.{digits}f} < Open: {candle_2['open']:.{digits}f})")
        print(f"     Candle 1 Bearish: {candle_1_bearish} (Close: {candle_1['close']:.{digits}f} < Open: {candle_1['open']:.{digits}f})")
        
        if candle_2_bearish and candle_1_bearish:
            print(f"     Both candles are bearish, checking lower highs/lows...")
            print(f"     Candle 2 Low: {candle_2['low']:.{digits}f} < Candle 1 Low: {candle_1['low']:.{digits}f}: {candle_2['low'] < candle_1['low']}")
            print(f"     Candle 2 High: {candle_2['high']:.{digits}f} < Candle 1 High: {candle_1['high']:.{digits}f}: {candle_2['high'] < candle_1['high']}")
            
            if candle_2['low'] < candle_1['low'] and candle_2['high'] < candle_1['high']:
                entry_price = get_candle_center(candle_1)
                exit_price = calculate_exit_price('bearish', candle_data, digits)
                
                print(f"\n  ✅ BEARISH PATTERN DETECTED")
                print(f"     • Entry (Candle 1 Center): {entry_price:.{digits}f}")
                print(f"     • Exit: {exit_price:.{digits}f}")
                print(f"     • Order Type: buy_stop")
                
                # Get candle types
                candle_1_type = "bullish" if candle_1['close'] > candle_1['open'] else "bearish"
                candle_2_type = "bullish" if candle_2['close'] > candle_2['open'] else "bearish"
                
                return 'bearish', entry_price, exit_price, candle_1, candle_2, candle_1_type, candle_2_type
            else:
                print(f"      Failed lower highs/lows condition")
        
        print(f"\n   NO PATTERN DETECTED")
        return None, None, None, None, None, None, None
    
    def save_directional_signals(strategy_path, new_signals, strategy_name, investor_id):
        """
        Save directional bias signals to limit_orders.json file.
        OVERWRITES the file completely with only the new signals.
        """
        pending_orders_dir = strategy_path / "pending_orders"
        pending_orders_dir.mkdir(exist_ok=True)
        
        signals_file = pending_orders_dir / "limit_orders.json"
        
        # Overwrite with fresh signals
        with open(signals_file, 'w', encoding='utf-8') as f:
            json.dump(new_signals, f, indent=4)
        
        # Count order types by symbol
        symbol_stats = {}
        for signal in new_signals:
            sym = signal.get('symbol')
            order_type = signal.get('order_type')
            if sym not in symbol_stats:
                symbol_stats[sym] = {'buy_stop': 0, 'sell_stop': 0}
            symbol_stats[sym][order_type] = symbol_stats[sym].get(order_type, 0) + 1
        
        print(f"\n  💾 Signals saved to: {signals_file}")
        if symbol_stats:
            print(f"     📊 Per-symbol order counts:")
            for sym, counts in symbol_stats.items():
                print(f"        • {sym}: Buy Stop: {counts.get('buy_stop', 0)}, Sell Stop: {counts.get('sell_stop', 0)}")
        print(f"     📊 Total signals saved: {len(new_signals)}")
        
        return signals_file
    
    def get_min_volume(symbol_info=None):
        """Get minimum volume for symbol"""
        return 0.01
    
    # Main execution
    if inv_id:
        # Load investor configuration
        symbols_dict, timeframes, target_folder, risk_reward, strategy_name = load_investor_config(inv_id)
        
        if not symbols_dict or not timeframes:
            print(f" [{inv_id}]  Failed to load configuration")
            return stats
        
        print(f"\n  ⏰ Timeframes: {timeframes}")
        print(f"  📁 Target folder: {target_folder}")
        print(f"  📁 Strategy name: {strategy_name}")
        print(f"  📈 Risk/Reward: {risk_reward}")
        
        # Initialize MT5 for order management
        if not mt5.terminal_info():
            print(f" [{inv_id}] Initializing MT5 connection...")
            if not mt5.initialize():
                print(f" [{inv_id}] Failed to initialize MT5, order management disabled")
        
        # Strategy base directory
        strategy_base_dir = Path(INV_PATH) / inv_id / strategy_name
        
        # Create records directory
        records_dir = strategy_base_dir / "pending_orders"
        records_dir.mkdir(exist_ok=True)
        records_file = records_dir / "candle_time_records.json"
        
        total_symbols = 0
        successful_symbols = 0
        failed_symbols = 0
        skipped_signals = 0
        all_signals = []
        total_cancelled = 0
        
        # Process each timeframe
        for timeframe in timeframes:
            print(f"\n{'='*50}")
            print(f"  Processing timeframe: {timeframe}")
            print(f"{'='*50}")
            
            timeframe_bullish = 0
            timeframe_bearish = 0
            timeframe_signals = []
            timeframe_symbols_processed = 0
            
            # Process each symbol
            for category, symbols in symbols_dict.items():
                for raw_symbol in symbols:
                    if not raw_symbol:
                        continue
                    
                    symbol = raw_symbol.upper()
                    
                    # Load candle data
                    candle_data, error = load_candle_data(inv_id, symbol, timeframe, target_folder)
                    
                    if candle_data is None:
                        print(f"\n   {symbol} [{timeframe}]: {error}")
                        failed_symbols += 1
                        continue
                    
                    # Get current forming candle time
                    current_candle_time = candle_data['current'].get('time', '')
                    
                    # Check for duplicate
                    if is_candle_time_already_recorded(records_file, symbol, timeframe, current_candle_time):
                        print(f"\n  ⏭️ SKIPPING {symbol} [{timeframe}]: Signal already generated for candle: {current_candle_time}")
                        skipped_signals += 1
                        stats["skipped_signals"] += 1
                        continue
                    
                    # Determine digits for rounding
                    test_price = candle_data['candle_1']['close']
                    if test_price < 1:
                        digits = 5
                    else:
                        str_price = f"{test_price:.10f}".rstrip('0')
                        if '.' in str_price:
                            digits = len(str_price.split('.')[1])
                        else:
                            digits = 2
                    
                    # Print candle details
                    print_candle_details(symbol, timeframe, candle_data, digits)
                    
                    # Analyze directional bias
                    bias_type, entry_price, exit_price, candle_1, candle_2, candle_1_type, candle_2_type = analyze_directional_bias(candle_data, symbol, digits)
                    
                    if bias_type is None:
                        failed_symbols += 1
                        continue
                    
                    # Set order type
                    if bias_type == 'bullish':
                        order_type = "sell_stop"
                        timeframe_bullish += 1
                    else:
                        order_type = "buy_stop"
                        timeframe_bearish += 1
                    
                    # MANAGE existing orders (allow up to 2, delete oldest if 3rd appears)
                    print(f"\n  🔄 Managing existing {order_type} orders for {symbol}...")
                    current_time = datetime.now().timestamp()
                    cancelled, orders_to_keep, is_first_order, is_second_order = manage_existing_orders(
                        Path(INV_PATH) / inv_id, symbol, order_type, current_time
                    )
                    
                    if cancelled > 0:
                        total_cancelled += cancelled
                        stats["cancelled_pending_orders"] += cancelled
                    
                    # Build order flags
                    order_flags = {}
                    if is_first_order:
                        order_flags["unique_order_type"] = True
                        print(f"     🏷️ This is the FIRST/UNIQUE {order_type} order")
                    elif is_second_order:
                        if order_type == "buy_stop":
                            order_flags["buy_stop_order_2"] = True
                            print(f"     🏷️ This is the SECOND buy_stop order")
                        else:
                            order_flags["sell_stop_order_2"] = True
                            print(f"     🏷️ This is the SECOND sell_stop order")
                        order_flags[f"{order_type}_latest_order_1"] = True
                        print(f"     🏷️ This is the LATEST {order_type} order")
                    else:
                        # This shouldn't happen with new logic, but as fallback
                        order_flags["unique_order_type"] = True
                        print(f"     🏷️ This is a UNIQUE order (fallback)")
                    
                    # Get minimum volume
                    min_volume = get_min_volume()
                    
                    # Extract candle times
                    candle_1_time = candle_1.get('time', '')
                    candle_2_time = candle_2.get('time', '')
                    
                    # Create signal with candle price levels, candle times, and order flags
                    signal = {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "risk_reward": risk_reward,
                        "order_type": order_type,
                        "entry": round(entry_price, digits),
                        "exit": round(exit_price, digits),
                        # Order management flags
                        "order_flags": order_flags,
                        # Candle 1 (second most recent) details
                        "candle_1_time": candle_1_time,
                        "candle_1_high": round(candle_1['high'], digits),
                        "candle_1_low": round(candle_1['low'], digits),
                        "candle_1_type": candle_1_type,
                        # Candle 2 (most recent completed) details
                        "candle_2_time": candle_2_time,
                        "candle_2_high": round(candle_2['high'], digits),
                        "candle_2_low": round(candle_2['low'], digits),
                        "candle_2_type": candle_2_type,
                        "volume": min_volume,
                        "current_candle_time": current_candle_time,
                        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "strategy": strategy_name
                    }
                    
                    # Save candle time record with full candle details and order flags
                    signal_info = {
                        'order_type': order_type,
                        'entry': round(entry_price, digits),
                        'exit': round(exit_price, digits)
                    }
                    
                    if save_candle_time_record(records_file, symbol, timeframe, current_candle_time, signal_info, candle_data, digits, order_flags):
                        timeframe_signals.append(signal)
                        all_signals.append(signal)
                        timeframe_symbols_processed += 1
                        successful_symbols += 1
                        total_symbols += 1
                        
                        print(f"\n  💾 SIGNAL GENERATED: {symbol} [{timeframe}] [{bias_type.upper()}]")
                        print(f"     Order: {order_type} at {round(entry_price, digits)}")
                        print(f"     Exit: {round(exit_price, digits)}")
                        print(f"     Order Flags: {order_flags}")
                        print(f"     Candle 1 Time: {candle_1_time}")
                        print(f"     Candle 1: {candle_1_type} | High: {round(candle_1['high'], digits)} | Low: {round(candle_1['low'], digits)}")
                        print(f"     Candle 2 Time: {candle_2_time}")
                        print(f"     Candle 2: {candle_2_type} | High: {round(candle_2['high'], digits)} | Low: {round(candle_2['low'], digits)}")
                        print(f"     Volume: {min_volume}")
                        print(f"     Risk/Reward: {risk_reward}")
                        print(f"     Strategy: {strategy_name}")
                    else:
                        print(f"\n   FAILED to record signal for {symbol} [{timeframe}]")
                        failed_symbols += 1
            
            # Update stats
            stats["bullish_signals"] += timeframe_bullish
            stats["bearish_signals"] += timeframe_bearish
            stats["total_signals"] += len(timeframe_signals)
            stats["timeframes_used"].append(timeframe)
            
            if timeframe_signals:
                print(f"\n  📊 SUMMARY for {timeframe}:")
                print(f"     • Symbols processed: {timeframe_symbols_processed}")
                print(f"     • Bullish signals (sell_stop): {timeframe_bullish}")
                print(f"     • Bearish signals (buy_stop): {timeframe_bearish}")
                print(f"     • Total signals: {len(timeframe_signals)}")
        
        # Save signals
        if all_signals:
            save_directional_signals(strategy_base_dir, all_signals, strategy_name, inv_id)
            stats["signals_generated"] = True
        else:
            # Remove existing file if no signals
            signals_file = strategy_base_dir / "pending_orders" / "limit_orders.json"
            if signals_file.exists():
                signals_file.unlink()
                print(f"\n  🗑️ No signals generated - removed existing limit_orders.json")
        
        # Final summary
        stats["total_symbols"] = total_symbols
        stats["successful_symbols"] = successful_symbols
        stats["failed_symbols"] = failed_symbols
        
        print(f"\n{'='*60}")
        print(f"  📊 FINAL SUMMARY for Investor {inv_id}")
        print(f"  {'='*60}")
        print(f"  • Strategy: {strategy_name}")
        print(f"  • Timeframes processed: {timeframes}")
        print(f"  • Total symbols: {total_symbols}")
        print(f"  • Successful: {successful_symbols}")
        print(f"  • Failed: {failed_symbols}")
        print(f"  • Skipped (duplicate): {skipped_signals}")
        print(f"  • Bullish signals (sell_stop): {stats['bullish_signals']}")
        print(f"  • Bearish signals (buy_stop): {stats['bearish_signals']}")
        print(f"  • Total signals generated: {stats['total_signals']}")
        print(f"  • Pending orders cancelled/deleted: {total_cancelled}")
        print(f"  • Signals saved to: {strategy_base_dir}/pending_orders/limit_orders.json")
        print(f"  {'='*60}")
        
        # Create master summary file
        if stats["signals_generated"]:
            master_signals_file = strategy_base_dir / "pending_orders" / "directional_signals_all.json"
            
            master_data = {
                "account_balance": 10000.0,
                "account_currency": "USD",
                "strategy": strategy_name,
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "timeframes_processed": timeframes,
                "total_signals": stats['total_signals'],
                "pending_orders_deleted": total_cancelled,
                "signals_summary": {
                    "bullish_sell_stop": stats['bullish_signals'],
                    "bearish_buy_stop": stats['bearish_signals'],
                    "skipped_duplicates": skipped_signals
                },
                "signals_detail": all_signals
            }
            
            with open(master_signals_file, 'w', encoding='utf-8') as f:
                json.dump(master_data, f, indent=4)
            
            print(f"\n  📁 Master summary saved to: {master_signals_file}")
            print(f"  📝 Candle time records saved to: {records_file}")
        else:
            print(f"\n  No signals generated for user {inv_id}")
    
    return stats

def additional_candles_for_orders_limitation(inv_id=None):
    """
    Fetch the 20 most recent candles for each symbol/timeframe combination
    found in tradeshistory.json (pending orders) and save to additional_candles.json.
    
    Identifies and flags candle_1 and candle_2 from the trade records by TIME only.
    Deletes all candles older than candle_1 (candles that come after candle_1 in time),
    keeping only candles from candle_1 to the most recent (newer candles).
    
    If no candle_1 or candle_2 is found for a symbol/timeframe, the entire record is emptied
    and all candles are deleted.
    
    Removes orders from limit_orders.json based on additional candles count
    configured in accountmanagement.json settings.remove_orders_if_additonal_candles_is_more_than
    
    Cancels MT5 pending orders by looking up ticket numbers from tradeshistory.json
    and cancelling them directly.
    
    Parameters:
    - inv_id: Optional specific investor ID to process
    
    Returns:
    - dict: Processing statistics including counts of fetched candles and removed orders
    """
    print(f"\n{'='*10} 🕯️ FETCH ADDITIONAL CANDLES {'='*10}")
    if inv_id:
        print(f" Processing investor: {inv_id}")
    
    # Constants
    NUM_CANDLES_TO_FETCH = 20  # Fetch 20 most recent candles
    
    # Statistics for this run
    stats = {
        "investor_id": inv_id if inv_id else "all",
        "symbols_processed": 0,
        "total_candles_fetched": 0,
        "records_saved": 0,
        "candle_1_matches": 0,
        "candle_2_matches": 0,
        "empty_records": 0,
        "errors": [],
        "orders_removed": 0,  # Track removed orders from JSON
        "mt5_orders_cancelled": 0,  # Track MT5 orders cancelled
        "removal_threshold": None  # Track the configured threshold
    }
    
    def normalize_symbol_for_filename(raw_symbol):
        """Remove special characters from symbol for filename"""
        normalized = raw_symbol.replace('+', '').replace('-', '').replace('.', '')
        return normalized
    
    def load_investor_config(investor_id):
        """Load investor configuration to get strategy name and settings"""
        acc_mgmt_path = Path(INV_PATH) / investor_id / "accountmanagement.json"
        
        if not acc_mgmt_path.exists():
            return None, None
        
        try:
            with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Get target folder and strategy name from investor config using GLOBAL FETCHED_INVESTORS
            strategy_name = None
            removal_threshold = None
            
            # Get removal threshold from settings
            settings = config.get("settings", {})
            removal_threshold = settings.get("remove_orders_if_additonal_candles_is_more_than")
            
            if FETCHED_INVESTORS:
                try:
                    with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
                        investor_users = json.load(f)
                    
                    investor_cfg = investor_users.get(investor_id)
                    if investor_cfg:
                        invested_with = investor_cfg.get("INVESTED_WITH", "")
                        if "_" in invested_with:
                            strategy_name = invested_with.split("_", 1)[1]
                        else:
                            strategy_name = invested_with
                except Exception as e:
                    pass  # Silent fail
            
            if not strategy_name:
                strategy_name = "prices"
            
            return strategy_name, removal_threshold
            
        except Exception as e:
            return None, None
    
    def load_tradeshistory_for_candle_reference(investor_id, strategy_name):
        """
        Load tradeshistory.json to get symbol/timeframe pairs and candle reference times.
        Only includes pending orders that have candle_1_time and candle_2_time.
        
        Returns:
        - symbol_timeframe_pairs: List of unique symbol/timeframe combinations
        - candle_reference_data: Dict mapping key to candle_1_time and candle_2_time
        """
        investor_root = Path(INV_PATH) / investor_id
        history_path = investor_root / "tradeshistory.json"
        
        if not history_path.exists():
            print(f"  ℹ️ No tradeshistory.json found for investor {investor_id}")
            return [], {}
        
        try:
            with open(history_path, 'r', encoding='utf-8') as f:
                trades = json.load(f)
            
            symbol_timeframe_pairs = []
            candle_reference_data = {}
            seen = set()
            
            for trade in trades:
                # Only process pending orders that have the required candle times
                status = trade.get('status', '')
                if status != 'pending':
                    continue
                
                symbol = trade.get('symbol_used') or trade.get('symbol')
                timeframe = trade.get('timeframe')
                candle_1_time = trade.get('candle_1_time', '')
                candle_2_time = trade.get('candle_2_time', '')
                
                # Skip if missing required data
                if not symbol or not timeframe or not candle_1_time or not candle_2_time:
                    continue
                
                key = f"{symbol}_{timeframe}"
                
                if key not in seen:
                    symbol_timeframe_pairs.append({
                        "symbol": symbol,
                        "timeframe": timeframe
                    })
                    seen.add(key)
                    
                    # Store the candle times for this symbol/timeframe
                    # Note: If multiple trades exist for same symbol/timeframe, 
                    # we use the first one's candle times (they should be consistent)
                    candle_reference_data[key] = {
                        "candle_1_time": candle_1_time,
                        "candle_2_time": candle_2_time
                    }
            
            print(f"  📋 Loaded {len(symbol_timeframe_pairs)} unique symbol/timeframe pairs from tradeshistory.json (pending orders only)")
            return symbol_timeframe_pairs, candle_reference_data
            
        except Exception as e:
            print(f"  Error loading tradeshistory.json: {e}")
            return [], {}
    
    def fetch_recent_candles_with_matching(symbol, mt5_timeframe, num_candles, reference_data):
        """Fetch recent candles and flag matches"""
        try:
            selected = False
            for attempt in range(3):
                if mt5.symbol_select(symbol, True):
                    selected = True
                    break
                time.sleep(0.5)
            
            if not selected:
                return [], {"candle_1_matched": False, "candle_2_matched": False}
            
            rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, num_candles)
            
            if rates is None or len(rates) == 0:
                return [], {"candle_1_matched": False, "candle_2_matched": False}
            
            candles = []
            match_stats = {"candle_1_matched": False, "candle_2_matched": False}
            
            candle_1_time = reference_data.get("candle_1_time", "")
            candle_2_time = reference_data.get("candle_2_time", "")
            
            total_rates = len(rates)
            
            for i, rate in enumerate(rates):
                candle_time_utc = datetime.fromtimestamp(rate['time'], tz=pytz.UTC)
                candle_time_str = candle_time_utc.strftime('%Y-%m-%d %H:%M:%S')
                candle_type = "bullish" if rate['close'] > rate['open'] else "bearish"
                is_current_forming = (i == total_rates - 1)
                
                candle_data = {
                    "time": candle_time_str,
                    "open": float(rate['open']),
                    "high": float(rate['high']),
                    "low": float(rate['low']),
                    "close": float(rate['close']),
                    "type": candle_type,
                    "current_forming_candle": is_current_forming,
                    "candle_1_from_current_candle_time_record": False,
                    "candle_2_from_current_candle_time_record": False
                }
                
                if candle_1_time and candle_time_str == candle_1_time:
                    candle_data["candle_1_from_current_candle_time_record"] = True
                    match_stats["candle_1_matched"] = True
                
                if candle_2_time and candle_time_str == candle_2_time:
                    candle_data["candle_2_from_current_candle_time_record"] = True
                    match_stats["candle_2_matched"] = True
                
                candles.append(candle_data)
            
            candles.reverse()
            return candles, match_stats
            
        except Exception as e:
            return [], {"candle_1_matched": False, "candle_2_matched": False}
    
    def filter_candles_from_candle_1(candles_list, candle_1_time):
        """
        Delete all candles older than candle_1 (candles that come after candle_1 in the list),
        keeping only candle_1, candle_2, and all newer candles.
        
        Since candles are ordered newest to oldest:
        - Index 0 = newest (current forming)
        - Higher index = older
        
        We want to KEEP: candles from index 0 up to and including candle_1
        We want to DELETE: all candles after candle_1 (older candles)
        
        Parameters:
        - candles_list: List of candles in newest to oldest order
        - candle_1_time: Time string of candle_1 to find
        
        Returns:
        - tuple: (filtered_candles_list, deleted_count, candle_1_found, candle_2_found)
        """
        if not candle_1_time:
            return [], len(candles_list), False, False
        
        candle_1_index = -1
        candle_2_found = False
        
        for idx, candle in enumerate(candles_list):
            if candle.get("time") == candle_1_time:
                candle_1_index = idx
            if candle.get("candle_2_from_current_candle_time_record"):
                candle_2_found = True
        
        # If candle_1 not found, return empty list (delete all candles)
        if candle_1_index == -1:
            return [], len(candles_list), False, candle_2_found
        
        # Keep candles from index 0 up to and including candle_1_index
        # These are the newer candles (candle_1 and all candles more recent than it)
        filtered_candles = candles_list[:candle_1_index + 1]
        deleted_count = len(candles_list) - len(filtered_candles)
        
        return filtered_candles, deleted_count, True, candle_2_found
    
    def count_additional_candles(candles_list):
        """
        Count additional candles excluding:
        - current forming candle
        - candle_1
        - candle_2
        
        Parameters:
        - candles_list: List of candles in newest to oldest order
        
        Returns:
        - int: Count of additional candles
        """
        count = 0
        for candle in candles_list:
            # Skip current forming candle
            if candle.get("current_forming_candle"):
                continue
            # Skip candle_1
            if candle.get("candle_1_from_current_candle_time_record"):
                continue
            # Skip candle_2
            if candle.get("candle_2_from_current_candle_time_record"):
                continue
            count += 1
        return count
    
    def save_additional_candles(investor_id, strategy_name, additional_candles_data):
        """Save additional candles to additional_candles.json"""
        strategy_base_dir = Path(INV_PATH) / investor_id / strategy_name
        pending_orders_dir = strategy_base_dir / "pending_orders"
        pending_orders_dir.mkdir(exist_ok=True)
        
        output_file = pending_orders_dir / "additional_candles.json"
        
        output_data = {
            "generated_at": datetime.now(pytz.UTC).strftime("%Y-%m-%d %H:%M:%S"),
            "generated_at_timezone": "UTC",
            "investor_id": investor_id,
            "strategy": strategy_name,
            "num_candles_fetched": NUM_CANDLES_TO_FETCH,
            "symbols_processed": len(additional_candles_data),
            "candles_data": additional_candles_data
        }
        
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=4)
            return True
        except Exception as e:
            return False
    
    # SUBFUNCTION: Load tradeshistory and build order lookup map
    def load_tradeshistory_lookup(investor_root):
        """
        Load tradeshistory.json and build a lookup map by symbol, order_type, entry, volume.
        Returns a dictionary with ticket numbers for quick lookup.
        """
        history_path = investor_root / "tradeshistory.json"
        order_lookup = {}
        
        if not history_path.exists():
            print(f"     ℹ️ No tradeshistory.json found")
            return order_lookup
        
        try:
            with open(history_path, 'r', encoding='utf-8') as f:
                history = json.load(f)
            
            for trade in history:
                # Only include pending orders (not yet executed or closed)
                status = trade.get('status', '')
                if status == 'pending':
                    ticket = trade.get('ticket')
                    symbol = trade.get('symbol_used') or trade.get('symbol')
                    order_type = trade.get('placed_order_type', '')
                    entry = trade.get('placed_price') or trade.get('entry')
                    volume = trade.get('placed_volume') or trade.get('volume')
                    magic = trade.get('magic')
                    
                    if ticket and symbol and order_type and entry:
                        # Create multiple lookup keys for flexibility
                        key1 = f"{symbol}_{order_type}_{entry}_{volume}" if volume else f"{symbol}_{order_type}_{entry}"
                        key2 = f"{symbol}_{order_type}_{entry}"
                        key3 = f"ticket_{ticket}"
                        
                        order_lookup[key1] = ticket
                        order_lookup[key2] = ticket
                        order_lookup[key3] = ticket
                        
                        # Also store by magic number if available
                        if magic:
                            order_lookup[f"magic_{magic}_{symbol}_{order_type}"] = ticket
            
            print(f"     📋 Loaded {len(history)} trades from tradeshistory.json, {len([t for t in history if t.get('status') == 'pending'])} pending orders found")
            return order_lookup
            
        except Exception as e:
            print(f"     Error loading tradeshistory.json: {e}")
            return order_lookup
    
    # SUBFUNCTION: Cancel MT5 pending orders using ticket from tradeshistory
    def cancel_mt5_pending_orders_by_ticket(orders_to_cancel_info, investor_root):
        """
        Cancel MT5 pending orders by looking up their ticket numbers from tradeshistory.json.
        
        Parameters:
        - orders_to_cancel_info: List of order info dictionaries with symbol, order_type, entry, volume
        - investor_root: Path to investor root directory (to load tradeshistory.json)
        
        Returns:
        - int: Number of successfully cancelled orders
        """
        if not orders_to_cancel_info:
            return 0
        
        # Load trade history lookup
        order_lookup = load_tradeshistory_lookup(investor_root)
        
        if not order_lookup:
            print(f"     No pending orders found in tradeshistory.json")
            return 0
        
        cancelled_count = 0
        
        for order_info in orders_to_cancel_info:
            symbol = order_info.get("symbol")
            order_type = order_info.get("order_type", "").lower()
            entry = order_info.get("entry")
            volume = order_info.get("volume")
            
            # Build lookup key to find ticket number
            lookup_key = f"{symbol}_{order_type}_{entry}"
            
            # Try with volume first if available
            if volume:
                lookup_key_with_vol = f"{symbol}_{order_type}_{entry}_{volume}"
                ticket = order_lookup.get(lookup_key_with_vol)
                if not ticket:
                    ticket = order_lookup.get(lookup_key)
            else:
                ticket = order_lookup.get(lookup_key)
            
            # If not found by key, try to find by iterating (fallback)
            if not ticket:
                print(f"     🔍 Searching for pending order: {order_type.upper()} {symbol} @ {entry}")
                # Try to find by scanning MT5 orders
                mt5_pending_orders = mt5.orders_get()
                if mt5_pending_orders:
                    for mt5_order in mt5_pending_orders:
                        if (mt5_order.symbol == symbol and 
                            abs(mt5_order.price_open - entry) < 0.00001):
                            ticket = mt5_order.ticket
                            print(f"     ✅ Found MT5 order ticket {ticket} by direct scan")
                            break
            
            if ticket:
                # Cancel the order using ticket number
                request = {
                    "action": mt5.TRADE_ACTION_REMOVE,
                    "order": ticket,
                }
                
                result = mt5.order_send(request)
                
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    print(f"     ✅ Cancelled MT5 order: #{ticket} ({order_type.upper()} {symbol} @ {entry})")
                    cancelled_count += 1
                else:
                    error_msg = result.comment if result else "Unknown error"
                    print(f"      Failed to cancel MT5 order #{ticket}: {error_msg}")
            else:
                print(f"     ℹ️ No pending order found in tradeshistory for: {order_type.upper()} {symbol} @ {entry}")
        
        return cancelled_count
    
    # SUBFUNCTION: Remove orders based on additional candles count
    def remove_orders_based_on_additional_candles_config(investor_id, strategy_name, removal_threshold, additional_candles_data, investor_root):
        """
        Check additional_candles count for each symbol/timeframe and remove orders from limit_orders.json
        if additional candles count exceeds the configured threshold.
        
        Also cancels MT5 pending orders using ticket lookup from tradeshistory.json.
        
        Parameters:
        - investor_id: The investor ID
        - strategy_name: The strategy name/folder
        - removal_threshold: Maximum allowed additional candles (from config)
        - additional_candles_data: List of additional candles data for each symbol/timeframe
        - investor_root: Path to investor root directory
        
        Returns:
        - tuple: (orders_removed_count, mt5_orders_cancelled_count)
        """
        if removal_threshold is None:
            print(f"  ℹ️ No removal threshold configured (remove_orders_if_additonal_candles_is_more_than not set)")
            return 0, 0
        
        print(f"\n  🔍 Checking orders against additional candles threshold: > {removal_threshold}")
        
        strategy_base_dir = Path(INV_PATH) / investor_id / strategy_name
        limit_orders_file = strategy_base_dir / "pending_orders" / "limit_orders.json"
        
        if not limit_orders_file.exists():
            print(f"  ℹ️ No limit_orders.json found, nothing to remove")
            return 0, 0
        
        try:
            # Load existing limit orders
            with open(limit_orders_file, 'r', encoding='utf-8') as f:
                limit_orders = json.load(f)
            
            if not limit_orders:
                print(f"  ℹ️ limit_orders.json is empty")
                return 0, 0
            
            print(f"  📋 Loaded {len(limit_orders)} limit orders")
            
            # Build a map of additional candles count per symbol/timeframe
            additional_candles_map = {}
            for item in additional_candles_data:
                symbol = item.get("symbol")
                timeframe = item.get("timeframe")
                additional_count = item.get("additional_candles_count", 0)
                key = f"{symbol}_{timeframe}"
                additional_candles_map[key] = additional_count
                print(f"     📊 {symbol} [{timeframe}]: {additional_count} additional candles")
            
            # Filter orders - keep only those that meet the threshold
            orders_to_keep = []
            orders_to_cancel = []  # Store orders to cancel in MT5
            
            for order in limit_orders:
                symbol = order.get("symbol")
                timeframe = order.get("timeframe")
                key = f"{symbol}_{timeframe}"
                
                additional_count = additional_candles_map.get(key, 0)
                
                if additional_count > removal_threshold:
                    # Store this order for MT5 cancellation
                    orders_to_cancel.append({
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "order_type": order.get("order_type"),
                        "entry": order.get("entry"),
                        "volume": order.get("volume"),
                        "additional_candles_count": additional_count,
                        "threshold": removal_threshold,
                        "magic": order.get("magic")
                    })
                    print(f"      🗑️ MARKED FOR REMOVAL: {symbol} [{timeframe}] | {additional_count} candles > {removal_threshold}")
                else:
                    # Keep this order
                    orders_to_keep.append(order)
                    print(f"     ✅ KEPT: {symbol} [{timeframe}] | {additional_count} candles <= {removal_threshold}")
            
            # Cancel MT5 pending orders using ticket lookup from tradeshistory
            mt5_cancelled = 0
            if orders_to_cancel:
                print(f"\n  🔄 Cancelling {len(orders_to_cancel)} MT5 pending orders via tradeshistory lookup...")
                mt5_cancelled = cancel_mt5_pending_orders_by_ticket(orders_to_cancel, investor_root)
            
            # Save the filtered orders back to limit_orders.json
            if orders_to_keep:
                with open(limit_orders_file, 'w', encoding='utf-8') as f:
                    json.dump(orders_to_keep, f, indent=4)
                print(f"\n  💾 Updated limit_orders.json with {len(orders_to_keep)} orders (removed {len(orders_to_cancel)})")
            else:
                # Remove the file if no orders remain
                if limit_orders_file.exists():
                    limit_orders_file.unlink()
                    print(f"\n  🗑️ Removed limit_orders.json (no orders left)")
            
            # Also update tradeshistory.json to mark cancelled orders as 'cancelled'
            if mt5_cancelled > 0:
                update_tradeshistory_status(investor_root, orders_to_cancel)
            
            return len(orders_to_cancel), mt5_cancelled
            
        except Exception as e:
            print(f"   Error removing orders: {e}")
            import traceback
            traceback.print_exc()
            return 0, 0
    
    # SUBFUNCTION: Update tradeshistory.json to mark orders as cancelled
    def update_tradeshistory_status(investor_root, cancelled_orders_info):
        """
        Update tradeshistory.json to mark cancelled orders as 'cancelled_by_additional_candles'
        """
        history_path = investor_root / "tradeshistory.json"
        
        if not history_path.exists():
            return False
        
        try:
            with open(history_path, 'r', encoding='utf-8') as f:
                history = json.load(f)
            
            updated_count = 0
            
            for cancelled_order in cancelled_orders_info:
                symbol = cancelled_order.get("symbol")
                order_type = cancelled_order.get("order_type")
                entry = cancelled_order.get("entry")
                volume = cancelled_order.get("volume")
                
                # Find matching trade in history
                for trade in history:
                    if (trade.get('status') == 'pending' and
                        trade.get('symbol_used') == symbol and
                        trade.get('placed_order_type') == order_type and
                        trade.get('placed_price') == entry):
                        
                        # Check volume if available
                        trade_volume = trade.get('placed_volume') or trade.get('volume')
                        if volume and trade_volume and abs(trade_volume - volume) > 0.01:
                            continue
                        
                        # Update status
                        trade['status'] = 'cancelled_by_additional_candles'
                        trade['cancelled_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        trade['cancelled_reason'] = f"Additional candles ({cancelled_order.get('additional_candles_count', 0)}) exceeded threshold ({cancelled_order.get('threshold', 0)})"
                        updated_count += 1
                        print(f"     📝 Updated tradeshistory: Ticket {trade.get('ticket')} status → cancelled_by_additional_candles")
                        break
            
            if updated_count > 0:
                with open(history_path, 'w', encoding='utf-8') as f:
                    json.dump(history, f, indent=4)
                print(f"     💾 Updated {updated_count} order(s) in tradeshistory.json to 'cancelled' status")
            
            return updated_count > 0
            
        except Exception as e:
            print(f"     Error updating tradeshistory.json: {e}")
            return False
    
    # Main execution
    if inv_id:
        strategy_name, removal_threshold = load_investor_config(inv_id)
        
        if not strategy_name:
            return stats
        
        investor_root = Path(INV_PATH) / inv_id
        stats["removal_threshold"] = removal_threshold
        
        print(f"\n  📁 Strategy: {strategy_name}")
        if removal_threshold is not None:
            print(f"  ⚙️ Removal threshold: additional candles > {removal_threshold} will be removed")
        else:
            print(f"  ⚙️ No removal threshold configured")
        
        # Initialize MT5 if needed
        if not mt5.terminal_info():
            if not mt5.initialize():
                stats["errors"].append("MT5 initialization failed")
                return stats
        
        # REPLACED: Now loading from tradeshistory.json instead of candle_time_records.json
        symbol_timeframe_pairs, candle_reference_data = load_tradeshistory_for_candle_reference(inv_id, strategy_name)
        
        if not symbol_timeframe_pairs:
            print(f"  ℹ️ No pending orders with candle reference times found in tradeshistory.json")
            return stats
        
        additional_candles_data = []
        total_candles = 0
        total_candle_1_matches = 0
        total_candle_2_matches = 0
        empty_records = 0
        
        for pair in symbol_timeframe_pairs:
            symbol = pair["symbol"]
            timeframe = pair["timeframe"]
            key = f"{symbol}_{timeframe}"
            
            mt5_timeframe = TIMEFRAME_MAP.get(timeframe)
            if not mt5_timeframe:
                continue
            
            reference_data = candle_reference_data.get(key, {})
            
            candles, match_stats = fetch_recent_candles_with_matching(
                symbol, mt5_timeframe, NUM_CANDLES_TO_FETCH, reference_data
            )
            
            if candles:
                filtered_candles, deleted_count, candle_1_found, candle_2_found = filter_candles_from_candle_1(
                    candles, reference_data.get("candle_1_time", "")
                )
                
                # If candle_1 not found OR candle_2 not found, empty the record (delete all candles)
                if not candle_1_found or not candle_2_found:
                    filtered_candles = []
                    empty_records += 1
                    stats["empty_records"] += 1
                    
                    # Still add record but with empty candles
                    additional_candles_data.append({
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "timezone": "UTC",
                        "reference_candle_1_time": reference_data.get("candle_1_time", ""),
                        "reference_candle_2_time": reference_data.get("candle_2_time", ""),
                        "candle_1_matched": candle_1_found,
                        "candle_2_matched": candle_2_found,
                        "additional_candles_count": 0,
                        "candles": []
                    })
                    continue
                
                # Count additional candles (excluding current forming, candle_1, candle_2)
                additional_count = count_additional_candles(filtered_candles)
                
                if match_stats["candle_1_matched"]:
                    total_candle_1_matches += 1
                if match_stats["candle_2_matched"]:
                    total_candle_2_matches += 1
                
                additional_candles_data.append({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "timezone": "UTC",
                    "reference_candle_1_time": reference_data.get("candle_1_time", ""),
                    "reference_candle_2_time": reference_data.get("candle_2_time", ""),
                    "candle_1_matched": match_stats["candle_1_matched"],
                    "candle_2_matched": match_stats["candle_2_matched"],
                    "additional_candles_count": additional_count,
                    "candles": filtered_candles
                })
                
                total_candles += len(filtered_candles)
                stats["symbols_processed"] += 1
            else:
                # No candles fetched - add empty record
                empty_records += 1
                stats["empty_records"] += 1
                additional_candles_data.append({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "timezone": "UTC",
                    "reference_candle_1_time": reference_data.get("candle_1_time", ""),
                    "reference_candle_2_time": reference_data.get("candle_2_time", ""),
                    "candle_1_matched": False,
                    "candle_2_matched": False,
                    "additional_candles_count": 0,
                    "candles": []
                })
        
        stats["candle_1_matches"] = total_candle_1_matches
        stats["candle_2_matches"] = total_candle_2_matches
        
        if additional_candles_data:
            save_additional_candles(inv_id, strategy_name, additional_candles_data)
            stats["records_saved"] = 1
            stats["total_candles_fetched"] = total_candles
            
            # Remove orders based on additional candles count (includes MT5 cancellation via tradeshistory)
            if removal_threshold is not None:
                orders_removed, mt5_cancelled = remove_orders_based_on_additional_candles_config(
                    inv_id, strategy_name, removal_threshold, additional_candles_data, investor_root
                )
                stats["orders_removed"] = orders_removed
                stats["mt5_orders_cancelled"] = mt5_cancelled
        
        print(f"\n  ✅ Saved {total_candles} candles for {stats['symbols_processed']} symbols")
        if stats["orders_removed"] > 0:
            print(f"  🗑️ Removed {stats['orders_removed']} orders from limit_orders.json")
        if stats["mt5_orders_cancelled"] > 0:
            print(f"  🔄 Cancelled {stats['mt5_orders_cancelled']} pending orders in MT5 (via tradeshistory lookup)")
    
    return stats

def create_position_hedge_old(inv_id=None):
    """
    Creates hedge orders for existing running positions by analyzing MT5 positions AND tradeshistory.json.
    
    Process:
    1. Gets ALL running positions directly from MT5 terminal
    2. Checks MT5 history for any closed positions that were previously running
    3. REMOVES ORPHANED HEDGES: If hedge's parent is NOT in running positions AND NOT in pending orders
       -> Parent has been closed -> Remove hedge using same logic as close_unauthorized_orders
    4. If closed position found in profit -> removes associated hedge from limit_orders.json
    5. For each remaining MT5 position, creates hedge order using parent's exit price as entry
    6. Updates trade history with status tracking
    7. Saves hedge orders to limit_orders.json
    """
    
    print("\n" + "="*80)
    print("🔒 CREATING HEDGE ORDERS FOR RUNNING POSITIONS")
    print("="*80)
    
    # Ensure MT5 is initialized
    if not mt5.terminal_info():
        print("  Initializing MT5 connection...")
        if not mt5.initialize():
            print("   Failed to initialize MT5")
            return False
    
    investor_ids = [inv_id] if inv_id else list(usersdictionary.keys())
    hedge_stats = {
        'investors_processed': 0,
        'positions_analyzed': 0,
        'hedges_created': 0,
        'hedges_removed': 0,
        'orphaned_hedges_closed': 0,
        'orphaned_hedges_cancelled': 0,
        'positions_closed_profit': 0,
        'positions_closed_loss': 0,
        'errors': 0
    }
    
    # --- HELPER: Dynamic broker volume extraction ---
    def get_broker_volume_field(trade_record):
        """
        Find ANY *_volume field in a trade record and return (field_name, value).
        Returns (None, None) if no volume field found.
        """
        for key, value in trade_record.items():
            if key.endswith('_volume'):
                try:
                    return key, float(value)
                except (ValueError, TypeError):
                    continue
        return None, None
    
    for user_brokerid in investor_ids:
        print(f"\n{'='*60}")
        print(f"📋 INVESTOR: {user_brokerid}")
        print(f"{'='*60}")
        
        investor_root = Path(INV_PATH) / user_brokerid
        
        if not investor_root.exists():
            print(f"   Investor root not found: {investor_root}")
            continue
        
        # Step 1: Get strategy name using GLOBAL FETCHED_INVESTORS (same as directional_bias)
        acc_mgmt_path = investor_root / "accountmanagement.json"
        strategy_name = "prices"
        target_folder = "prices"
        
        if acc_mgmt_path.exists():
            try:
                with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                # Use the global FETCHED_INVESTORS variable (same as directional_bias)
                if FETCHED_INVESTORS:
                    try:
                        with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
                            investor_users = json.load(f)
                        
                        investor_cfg = investor_users.get(user_brokerid)
                        if investor_cfg:
                            invested_with = investor_cfg.get("INVESTED_WITH", "")
                            if "_" in invested_with:
                                target_folder = invested_with.split("_", 1)[1]
                                strategy_name = target_folder
                            else:
                                target_folder = invested_with
                                strategy_name = invested_with
                    except Exception as e:
                        print(f"  Error reading verified investors: {e}")
                
                # Also get risk_reward from config if needed
                selected_risk_reward = config.get("selected_risk_reward", [3])
                if isinstance(selected_risk_reward, list) and len(selected_risk_reward) > 0:
                    risk_reward_default = selected_risk_reward[0]
                else:
                    risk_reward_default = 3
                    
            except Exception as e:
                print(f"  Error reading config: {e}")
                risk_reward_default = 3
        else:
            risk_reward_default = 3
        
        print(f"  📁 Strategy name: {strategy_name}")
        print(f"  📁 Target folder: {target_folder}")
        
        # Connect to MT5 account
        broker_cfg = usersdictionary.get(user_brokerid)
        if not broker_cfg:
            print(f"  No broker configuration found for {user_brokerid}")
            continue
        
        login_id = int(broker_cfg['LOGIN_ID'])
        mt5_path = broker_cfg["TERMINAL_PATH"]
        
        # Check if already connected to correct account
        acc = mt5.account_info()
        if acc is None or acc.login != login_id:
            print(f"  Not logged into correct account. Expected: {login_id}")
            if not mt5.initialize(path=mt5_path, login=login_id, 
                                   password=broker_cfg["PASSWORD"], 
                                   server=broker_cfg["SERVER"]):
                print(f"   Failed to initialize MT5 for {user_brokerid}")
                continue
        else:
            print(f"  ✅ Connected to account: {acc.login}")
        
        # Step 2: Load tradeshistory.json
        history_path = investor_root / "tradeshistory.json"
        trade_details_by_ticket = {}
        trade_history_list = []
        
        if history_path.exists():
            try:
                with open(history_path, 'r', encoding='utf-8') as f:
                    trade_history_list = json.load(f)
                
                for trade in trade_history_list:
                    ticket = trade.get('ticket')
                    if ticket:
                        trade_details_by_ticket[ticket] = trade
                
                print(f"  📋 Loaded {len(trade_details_by_ticket)} trade records from tradeshistory.json")
            except Exception as e:
                print(f"  Error reading tradeshistory.json: {e}")
        
        # Step 3: Get MT5 running positions AND pending orders
        print(f"  🔍 Fetching running positions from MT5 terminal...")
        mt5_positions = mt5.positions_get()
        mt5_pending_orders = mt5.orders_get()
        
        if mt5_positions is None:
            print(f"  No MT5 positions found or error retrieving positions")
        
        # Filter by magic numbers
        investor_magics = set()
        for trade in trade_history_list:
            magic = trade.get('magic')
            if magic:
                investor_magics.add(int(magic))
        
        if investor_magics:
            running_positions = [p for p in mt5_positions if p.magic in investor_magics] if mt5_positions else []
            pending_orders = [o for o in mt5_pending_orders if o.magic in investor_magics] if mt5_pending_orders else []
            print(f"  📊 Found {len(running_positions)} running positions in MT5")
            print(f"  📊 Found {len(pending_orders)} pending orders in MT5")
        else:
            running_positions = list(mt5_positions) if mt5_positions else []
            pending_orders = list(mt5_pending_orders) if mt5_pending_orders else []
            print(f"  📊 Found {len(running_positions)} running positions in MT5")
            print(f"  📊 Found {len(pending_orders)} pending orders in MT5")
        
        # Create sets of ALL active tickets (running + pending)
        running_tickets = {p.ticket for p in running_positions} if running_positions else set()
        pending_tickets = {o.ticket for o in pending_orders} if pending_orders else set()
        all_active_tickets = running_tickets | pending_tickets
        
        print(f"  🎫 All active tickets (running + pending): {len(all_active_tickets)}")
        
        # ============================================================
        # NEW STEP: CLEANUP ORPHANED HEDGE ORDERS
        # Check if hedge's parent ticket is NOT in active positions/pending orders
        # If parent is gone -> close/cancel the hedge using close_unauthorized_orders logic
        # ============================================================
        print(f"\n  🧹 CHECKING FOR ORPHANED HEDGE ORDERS...")
        
        orphaned_hedges_removed = 0
        
        # Check running positions that are hedges
        if running_positions:
            for position in running_positions:
                # Check if this position is a hedge order
                # Look for it in trade history
                pos_ticket = position.ticket
                trade_record = trade_details_by_ticket.get(pos_ticket, {})
                
                if trade_record.get('is_hedge_order'):
                    parent_ticket = trade_record.get('parent_ticket')
                    
                    if parent_ticket and parent_ticket not in all_active_tickets:
                        # Parent is no longer active - close this hedge position
                        print(f"\n    🚨 ORPHANED HEDGE FOUND: Position #{pos_ticket}")
                        print(f"       • Symbol: {position.symbol}")
                        print(f"       • Type: {'BUY' if position.type == mt5.POSITION_TYPE_BUY else 'SELL'}")
                        print(f"       • Parent ticket {parent_ticket} is NOT active anymore")
                        print(f"       → Closing this orphaned hedge...")
                        
                        # Get current market price
                        tick = mt5.symbol_info_tick(position.symbol)
                        if not tick:
                            print(f"         Cannot get price for {position.symbol} - cannot close")
                            hedge_stats['errors'] += 1
                            continue
                        
                        # Determine closing order type
                        if position.type == mt5.POSITION_TYPE_BUY:
                            close_type = mt5.ORDER_TYPE_SELL
                            close_price = tick.bid
                        else:
                            close_type = mt5.ORDER_TYPE_BUY
                            close_price = tick.ask
                        
                        close_request = {
                            "action": mt5.TRADE_ACTION_DEAL,
                            "symbol": position.symbol,
                            "volume": position.volume,
                            "type": close_type,
                            "position": pos_ticket,
                            "price": close_price,
                            "deviation": 20,
                            "magic": position.magic if hasattr(position, 'magic') else 0,
                            "comment": "ORPHANED HEDGE - Parent closed",
                            "type_time": mt5.ORDER_TIME_GTC,
                            "type_filling": mt5.ORDER_FILLING_IOC,
                        }
                        
                        try:
                            result = mt5.order_send(close_request)
                            
                            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                                print(f"         ✅ SUCCESS: Orphaned hedge #{pos_ticket} CLOSED")
                                orphaned_hedges_removed += 1
                                hedge_stats['orphaned_hedges_closed'] += 1
                                
                                # Update trade history
                                trade_record['status'] = 'closed'
                                trade_record['closed_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                trade_record['closed_reason'] = 'orphaned_hedge_parent_closed'
                            else:
                                error_msg = result.comment if result else "No response"
                                error_code = result.retcode if result else "Unknown"
                                print(f"          FAILED: {error_msg} (code: {error_code})")
                                
                                # Try alternative closure
                                print(f"         🔄 Attempting alternative closure...")
                                alt_close_request = {
                                    "action": mt5.TRADE_ACTION_DEAL,
                                    "symbol": position.symbol,
                                    "volume": position.volume,
                                    "type": close_type,
                                    "position": pos_ticket,
                                    "price": close_price,
                                    "deviation": 50,
                                    "comment": "ORPHANED HEDGE - Retry",
                                    "type_filling": mt5.ORDER_FILLING_RETURN,
                                }
                                
                                alt_result = mt5.order_send(alt_close_request)
                                if alt_result and alt_result.retcode == mt5.TRADE_RETCODE_DONE:
                                    print(f"         ✅ SUCCESS (alt): Orphaned hedge #{pos_ticket} CLOSED")
                                    orphaned_hedges_removed += 1
                                    hedge_stats['orphaned_hedges_closed'] += 1
                                    
                                    trade_record['status'] = 'closed'
                                    trade_record['closed_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    trade_record['closed_reason'] = 'orphaned_hedge_parent_closed'
                                else:
                                    alt_error = alt_result.comment if alt_result else "No response"
                                    print(f"          Alternative also FAILED: {alt_error}")
                                    hedge_stats['errors'] += 1
                        except Exception as e:
                            print(f"          EXCEPTION: {e}")
                            hedge_stats['errors'] += 1
        
        # Check pending orders that are hedges
        if pending_orders:
            for order in pending_orders:
                order_ticket = order.ticket
                trade_record = trade_details_by_ticket.get(order_ticket, {})
                
                if trade_record.get('is_hedge_order'):
                    parent_ticket = trade_record.get('parent_ticket')
                    
                    if parent_ticket and parent_ticket not in all_active_tickets:
                        # Parent is no longer active - cancel this hedge pending order
                        print(f"\n    🚨 ORPHANED HEDGE PENDING ORDER: #{order_ticket}")
                        print(f"       • Symbol: {order.symbol}")
                        print(f"       • Type: {order.type}")
                        print(f"       • Parent ticket {parent_ticket} is NOT active anymore")
                        print(f"       → Cancelling this orphaned hedge order...")
                        
                        cancel_request = {
                            "action": mt5.TRADE_ACTION_REMOVE,
                            "order": order_ticket
                        }
                        
                        try:
                            result = mt5.order_send(cancel_request)
                            
                            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                                print(f"         ✅ SUCCESS: Orphaned hedge order #{order_ticket} CANCELLED")
                                orphaned_hedges_removed += 1
                                hedge_stats['orphaned_hedges_cancelled'] += 1
                                
                                # Update trade history
                                trade_record['status'] = 'cancelled'
                                trade_record['cancelled_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                trade_record['cancelled_reason'] = 'orphaned_hedge_parent_closed'
                            else:
                                error_msg = result.comment if result else "No response"
                                error_code = result.retcode if result else "Unknown"
                                print(f"          FAILED: {error_msg} (code: {error_code})")
                                hedge_stats['errors'] += 1
                        except Exception as e:
                            print(f"          EXCEPTION: {e}")
                            hedge_stats['errors'] += 1
        
        if orphaned_hedges_removed > 0:
            print(f"\n  ✅ Removed {orphaned_hedges_removed} orphaned hedge(s) from MT5")
        
        # Step 4: CRITICAL - Check for closed positions in MT5 history
        print(f"\n  🔍 Checking MT5 history for closed positions...")
        
        # Get history deals from last 7 days
        from_date = datetime.now() - timedelta(days=7)
        to_date = datetime.now()
        
        # Get all closed positions from MT5 history
        history_deals = mt5.history_deals_get(from_date, to_date)
        
        # Track which positions we've processed for hedging
        positions_to_hedge = []
        positions_closed_profit_tickets = []
        positions_closed_loss_tickets = []
        
        if history_deals:
            # Group deals by position_id to find closed positions
            closed_positions = {}
            for deal in history_deals:
                if deal.type in [mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL]:
                    pos_id = deal.position_id
                    if pos_id not in closed_positions:
                        closed_positions[pos_id] = []
                    closed_positions[pos_id].append(deal)
            
            # Check each closed position against our trade history
            for pos_id, deals in closed_positions.items():
                # Find the closing deal (profit/loss)
                closing_deal = None
                total_profit = 0
                
                for deal in deals:
                    if deal.type in [mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL]:
                        total_profit += deal.profit
                        # The last deal in the sequence is usually the closing one
                        closing_deal = deal
                
                # Check if this position exists in our trade history
                if pos_id in trade_details_by_ticket:
                    trade_record = trade_details_by_ticket[pos_id]
                    current_status = trade_record.get('status')
                    
                    # If position is not running in MT5 but was previously running
                    if pos_id not in running_tickets and current_status == 'running_position':
                        is_profitable = total_profit > 0
                        
                        print(f"\n    📍 Closed position found: Ticket {pos_id}")
                        print(f"       • Profit/Loss: ${total_profit:.2f}")
                        print(f"       • Profitable: {is_profitable}")
                        
                        # Update trade history
                        trade_record['status'] = 'closed'
                        trade_record['closed_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        trade_record['closed_profit'] = total_profit
                        trade_record['closed_profitable'] = is_profitable
                        
                        if is_profitable:
                            positions_closed_profit_tickets.append(pos_id)
                            print(f"       ✅ Closed in PROFIT - will remove hedge")
                        else:
                            positions_closed_loss_tickets.append(pos_id)
                            print(f"        Closed in LOSS - keeping hedge for protection")
            
            # Save updated trade history
            if positions_closed_profit_tickets or positions_closed_loss_tickets:
                try:
                    with open(history_path, 'w', encoding='utf-8') as f:
                        json.dump(trade_history_list, f, indent=4)
                    print(f"\n  💾 Updated trade history with closed position statuses")
                except Exception as e:
                    print(f"   Error saving trade history: {e}")
        
        # Step 5: Remove hedges for positions that closed in profit
        if positions_closed_profit_tickets:
            print(f"\n  🗑️ REMOVING HEDGES FOR PROFITABLE CLOSED POSITIONS...")
            
            strategy_base_dir = investor_root / strategy_name
            signals_file = strategy_base_dir / "pending_orders" / "limit_orders.json"
            
            if signals_file.exists():
                try:
                    with open(signals_file, 'r', encoding='utf-8') as f:
                        limit_orders = json.load(f)
                    
                    original_count = len(limit_orders)
                    orders_to_keep = []
                    removed_count = 0
                    
                    for order in limit_orders:
                        # Check if this order is a hedge for a closed profitable position
                        parent_ticket = order.get('parent_ticket')
                        is_hedge = order.get('is_hedge_order', False)
                        
                        if is_hedge and parent_ticket in positions_closed_profit_tickets:
                            # Remove this hedge order
                            print(f"    🗑️ Removing hedge for ticket {parent_ticket}: {order.get('order_type', 'unknown')} {order.get('symbol', 'unknown')} @ {order.get('entry', 'unknown')}")
                            removed_count += 1
                            hedge_stats['hedges_removed'] += 1
                            continue
                        else:
                            # Keep this order
                            orders_to_keep.append(order)
                    
                    if removed_count > 0:
                        # Save the filtered orders
                        with open(signals_file, 'w', encoding='utf-8') as f:
                            json.dump(orders_to_keep, f, indent=4)
                        
                        print(f"\n  ✅ Removed {removed_count} hedge(s) from limit_orders.json")
                        print(f"  📊 Remaining orders: {len(orders_to_keep)}")
                        hedge_stats['positions_closed_profit'] += len(positions_closed_profit_tickets)
                    else:
                        print(f"  ℹ️ No hedge orders found for closed profitable positions")
                        
                except Exception as e:
                    print(f"   Error processing limit_orders.json: {e}")
                    hedge_stats['errors'] += 1
        
        # Update statistics for loss positions
        if positions_closed_loss_tickets:
            hedge_stats['positions_closed_loss'] += len(positions_closed_loss_tickets)
            print(f"\n  ℹ️ {len(positions_closed_loss_tickets)} position(s) closed in loss - hedges kept as protection")
        
        # Step 6: Only process positions that are still running AND not yet hedged
        if not running_positions:
            print(f"\n  ℹ️ No running positions found for {user_brokerid}")
            continue
        
        hedge_stats['investors_processed'] += 1
        hedge_stats['positions_analyzed'] += len(running_positions)
        
        # Step 7: Load existing signals to check for existing hedges
        strategy_base_dir = investor_root / strategy_name
        pending_orders_dir = strategy_base_dir / "pending_orders"
        signals_file = pending_orders_dir / "limit_orders.json"
        pending_orders_dir.mkdir(parents=True, exist_ok=True)
        
        existing_signals = []
        if signals_file.exists():
            try:
                with open(signals_file, 'r', encoding='utf-8') as f:
                    existing_signals = json.load(f)
                print(f"\n  📋 Loaded {len(existing_signals)} existing signals from limit_orders.json")
            except Exception as e:
                print(f"  Error reading existing signals: {e}")
        
        # Step 8: Create hedges for remaining running positions
        hedges_created_for_investor = 0
        
        for position in running_positions:
            # Skip if this position itself is a hedge order
            pos_ticket = position.ticket
            pos_trade = trade_details_by_ticket.get(pos_ticket, {})
            if pos_trade.get('is_hedge_order'):
                print(f"\n  ⏭️ Position #{pos_ticket} is a hedge order - skipping")
                continue
            
            print(f"\n  🔍 Analyzing MT5 position: Ticket {position.ticket}")
            print(f"     • Symbol: {position.symbol}")
            print(f"     • Type: {'BUY' if position.type == mt5.ORDER_TYPE_BUY else 'SELL'}")
            print(f"     • Entry: {position.price_open}")
            print(f"     • Current: {position.price_current}")
            print(f"     • Volume: {position.volume}")
            print(f"     • Profit: ${position.profit:.2f}")
            
            # Check if hedge already exists for this position
            hedge_exists = False
            for signal in existing_signals:
                if signal.get('parent_ticket') == position.ticket and signal.get('is_hedge_order'):
                    hedge_exists = True
                    print(f"     ⏭️ Hedge already exists for this position")
                    hedge_stats['hedges_skipped'] = hedge_stats.get('hedges_skipped', 0) + 1
                    break
            
            if hedge_exists:
                continue
            
            # Get trade details from history
            trade_detail = trade_details_by_ticket.get(position.ticket, {})
            
            if trade_detail:
                print(f"     ✅ Found matching trade record")
                original_order_type = trade_detail.get('placed_order_type', '')
                exit_price = trade_detail.get('exit', 0)  # This is the stop loss
                candle_1_high = trade_detail.get('candle_1_high')
                candle_1_low = trade_detail.get('candle_1_low')
                candle_1_type = trade_detail.get('candle_1_type', '').lower()
                timeframe = trade_detail.get('timeframe', '')
                risk_reward = trade_detail.get('risk_reward', risk_reward_default)
                magic = trade_detail.get('magic', position.magic)
                
                # ========== DYNAMIC BROKER VOLUME EXTRACTION ==========
                # Find the broker-specific volume field from the parent trade
                volume_field_name, volume = get_broker_volume_field(trade_detail)
                
                if volume_field_name:
                    print(f"     📊 Found broker volume field '{volume_field_name}': {volume}")
                else:
                    # Fallback to standardized 'volume' field or position volume
                    volume = trade_detail.get('volume', trade_detail.get('placed_volume', position.volume))
                    print(f"     No *_volume field found, using fallback volume: {volume}")
                # ========== END DYNAMIC VOLUME EXTRACTION ==========
            else:
                print(f"     No trade record - using MT5 data")
                original_order_type = 'buy' if position.type == mt5.ORDER_TYPE_BUY else 'sell'
                exit_price = 0
                candle_1_high = None
                candle_1_low = None
                candle_1_type = ''
                timeframe = ''
                risk_reward = risk_reward_default
                volume = position.volume
                volume_field_name = None  # No broker field to preserve
                magic = position.magic
            
            # Create hedge (opposite direction)
            is_position_buy = (position.type == mt5.ORDER_TYPE_BUY)
            
            # Flip order type
            def flip_order_type(original_type, is_buy_position):
                if original_type:
                    original_lower = original_type.lower()
                else:
                    original_lower = 'buy' if is_buy_position else 'sell'
                
                if original_lower == 'instant_buy':
                    return 'instant_sell'
                if original_lower == 'instant_sell':
                    return 'instant_buy'
                
                if '_' in original_lower:
                    parts = original_lower.split('_', 1)
                    direction = parts[0]
                    suffix = parts[1]
                    new_direction = 'sell' if direction == 'buy' else 'buy'
                    return f"{new_direction}_{suffix}"
                else:
                    if original_lower == 'buy':
                        return 'sell'
                    elif original_lower == 'sell':
                        return 'buy'
                    return original_lower
            
            opposite_order_type = flip_order_type(original_order_type, is_position_buy)
            is_hedge_buy = 'buy' in opposite_order_type.lower()
            
            # Hedge entry = parent's exit (stop loss)
            if exit_price and exit_price > 0:
                hedge_entry = exit_price
                print(f"     🎯 Hedge entry (parent SL): {hedge_entry}")
            else:
                tick = mt5.symbol_info_tick(position.symbol)
                hedge_entry = tick.ask if is_hedge_buy else tick.bid if tick else position.price_current
                print(f"     No SL found - using current price: {hedge_entry}")
            
            # Determine digits
            digits = 5 if hedge_entry < 1 else len(f"{hedge_entry:.10f}".rstrip('0').split('.')[1]) if '.' in f"{hedge_entry:.10f}" else 2
            
            # Hedge stop loss based on candle
            if candle_1_type == "bearish" and candle_1_high:
                hedge_exit = candle_1_high
            elif candle_1_type == "bullish" and candle_1_low:
                hedge_exit = candle_1_low
            else:
                hedge_exit = hedge_entry - (hedge_entry * 0.005) if is_hedge_buy else hedge_entry + (hedge_entry * 0.005)
            
            hedge_entry = round(hedge_entry, digits)
            hedge_exit = round(hedge_exit, digits)
            
            # Take profit based on risk/reward
            risk_amount = abs(hedge_entry - hedge_exit)
            target_distance = risk_amount * risk_reward
            hedge_target = round(hedge_entry + target_distance if is_hedge_buy else hedge_entry - target_distance, digits)
            
            # Validate volume against symbol limits (NO ROUNDING)
            symbol_info = mt5.symbol_info(position.symbol)
            if symbol_info:
                volume = max(symbol_info.volume_min, min(symbol_info.volume_max, volume))
            
            # Create hedge order
            hedge_id = f"hedge_{position.ticket}_{position.symbol}_{int(datetime.now().timestamp())}"
            
            hedge_order = {
                "symbol": position.symbol,
                "timeframe": timeframe,
                "risk_reward": risk_reward,
                "order_type": opposite_order_type,
                "entry": hedge_entry,
                "exit": hedge_exit,
                "target": hedge_target,
                "is_hedge_order": True,
                "hedge_type": "position_hedge",
                "candle_1_high": round(candle_1_high, digits) if candle_1_high else None,
                "candle_1_low": round(candle_1_low, digits) if candle_1_low else None,
                "candle_1_type": candle_1_type,
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "strategy": strategy_name,
                "magic": magic,
                "volume": volume,
                "hedge_id": hedge_id,
                "parent_ticket": position.ticket,
                "parent_order_type": original_order_type,
                "parent_entry": position.price_open,
                "parent_exit": exit_price,
                "parent_profit": position.profit,
                "status": "Calculated",
                "created_by": "create_position_hedge_function"
            }
            
            # ========== PRESERVE BROKER VOLUME FIELD ==========
            # If parent had a broker-specific volume field (e.g., deriv_volume, bybit_volume),
            # add the same field to the hedge order
            if volume_field_name:
                hedge_order[volume_field_name] = volume
                print(f"     📊 Preserved broker volume field: {volume_field_name} = {volume}")
            # ========== END BROKER VOLUME PRESERVATION ==========
            
            # Remove None values
            hedge_order = {k: v for k, v in hedge_order.items() if v is not None}
            
            # Add to signals
            existing_signals.append(hedge_order)
            hedges_created_for_investor += 1
            hedge_stats['hedges_created'] += 1
            
            print(f"\n     ✅ HEDGE CREATED: {opposite_order_type.upper()} @ {hedge_entry}")
            print(f"        • Stop Loss: {hedge_exit} | Target: {hedge_target}")
            print(f"        • Hedge ID: {hedge_id}")
            print(f"        • Volume: {volume}" + (f" (via {volume_field_name})" if volume_field_name else ""))
        
        # Step 9: Save updated signals
        if hedges_created_for_investor > 0 or hedge_stats['hedges_removed'] > 0 or orphaned_hedges_removed > 0:
            try:
                # Save trade history if we made changes
                if orphaned_hedges_removed > 0 or positions_closed_profit_tickets or positions_closed_loss_tickets:
                    with open(history_path, 'w', encoding='utf-8') as f:
                        json.dump(trade_history_list, f, indent=4)
                
                # Save limit orders
                if hedges_created_for_investor > 0 or hedge_stats['hedges_removed'] > 0:
                    with open(signals_file, 'w', encoding='utf-8') as f:
                        json.dump(existing_signals, f, indent=4)
                    
                    hedge_count = sum(1 for s in existing_signals if s.get('is_hedge_order', False))
                    print(f"\n  💾 Saved {len(existing_signals)} signals to {signals_file}")
                    print(f"     • Hedges in file: {hedge_count}")
                    print(f"     • New hedges added: {hedges_created_for_investor}")
                    print(f"     • Hedges removed: {hedge_stats['hedges_removed']}")
                
            except Exception as e:
                print(f"   Error saving signals: {e}")
                hedge_stats['errors'] += 1
        
        # Investor summary
        print(f"\n  📊 SUMMARY for {user_brokerid}:")
        print(f"     • Running positions: {len(running_positions)}")
        print(f"     • Pending orders: {len(pending_orders)}")
        print(f"     • Closed in profit: {len(positions_closed_profit_tickets)}")
        print(f"     • Closed in loss: {len(positions_closed_loss_tickets)}")
        print(f"     • Orphaned hedges removed: {orphaned_hedges_removed}")
        print(f"     • Hedges created: {hedges_created_for_investor}")
        print(f"     • Hedges removed from JSON: {hedge_stats['hedges_removed']}")
    
    # Global summary
    print("\n" + "="*80)
    print("📊 GLOBAL HEDGE SUMMARY")
    print("="*80)
    print(f"  • Investors processed: {hedge_stats['investors_processed']}")
    print(f"  • Positions analyzed: {hedge_stats['positions_analyzed']}")
    print(f"  • Hedges created: {hedge_stats['hedges_created']}")
    print(f"  • Hedges removed from JSON: {hedge_stats['hedges_removed']}")
    print(f"  • Orphaned hedges closed: {hedge_stats['orphaned_hedges_closed']}")
    print(f"  • Orphaned hedges cancelled: {hedge_stats['orphaned_hedges_cancelled']}")
    print(f"  • Positions closed profit: {hedge_stats['positions_closed_profit']}")
    print(f"  • Positions closed loss: {hedge_stats['positions_closed_loss']}")
    print(f"  • Errors: {hedge_stats['errors']}")
    print("="*80)
    
    return hedge_stats['hedges_created'] > 0 or hedge_stats['hedges_removed'] > 0 or hedge_stats['orphaned_hedges_closed'] > 0 or hedge_stats['orphaned_hedges_cancelled'] > 0

def create_position_hedge(inv_id=None):
    """
    Creates hedge orders for existing running positions by analyzing MT5 positions AND tradeshistory.json.
    
    Process:
    1. Gets ALL running positions directly from MT5 terminal
    2. Checks MT5 history for any closed positions that were previously running
    3. REMOVES ORPHANED HEDGES: If hedge's parent is NOT in running positions AND NOT in pending orders
       -> Parent has been closed -> Remove hedge using same logic as close_unauthorized_orders
    4. If closed position found in profit -> removes associated hedge from limit_orders.json
    5. For each remaining MT5 position, creates hedge order using parent's exit price as entry
    6. Updates trade history with status tracking
    7. Saves hedge orders to limit_orders.json
    """
    
    print("\n" + "="*80)
    print("🔒 CREATING HEDGE ORDERS FOR RUNNING POSITIONS")
    print("="*80)
    
    # Ensure MT5 is initialized
    if not mt5.terminal_info():
        print("  Initializing MT5 connection...")
        if not mt5.initialize():
            print("   Failed to initialize MT5")
            return False
    
    investor_ids = [inv_id] if inv_id else list(usersdictionary.keys())
    hedge_stats = {
        'investors_processed': 0,
        'investors_skipped': 0,  # New: track investors skipped due to disabled hedging
        'positions_analyzed': 0,
        'hedges_created': 0,
        'hedges_removed': 0,
        'orphaned_hedges_closed': 0,
        'orphaned_hedges_cancelled': 0,
        'positions_closed_profit': 0,
        'positions_closed_loss': 0,
        'errors': 0
    }
    
    # --- HELPER: Dynamic broker volume extraction ---
    def get_broker_volume_field(trade_record):
        """
        Find ANY *_volume field in a trade record and return (field_name, value).
        Returns (None, None) if no volume field found.
        """
        for key, value in trade_record.items():
            if key.endswith('_volume'):
                try:
                    return key, float(value)
                except (ValueError, TypeError):
                    continue
        return None, None
    
    for user_brokerid in investor_ids:
        print(f"\n{'='*60}")
        print(f"📋 INVESTOR: {user_brokerid}")
        print(f"{'='*60}")
        
        investor_root = Path(INV_PATH) / user_brokerid
        
        if not investor_root.exists():
            print(f"   Investor root not found: {investor_root}")
            continue
        
        # Step 1: Get strategy name using GLOBAL FETCHED_INVESTORS (same as directional_bias)
        acc_mgmt_path = investor_root / "accountmanagement.json"
        strategy_name = "prices"
        target_folder = "prices"
        
        # ============================================================
        # NEW: CHECK FOR create_hedge_order SETTING
        # ============================================================
        create_hedge_enabled = True  # Default to True if not specified
        risk_reward_default = 3
        
        if acc_mgmt_path.exists():
            try:
                with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                # Check the create_hedge_order setting
                settings = config.get("settings", {})
                create_hedge_enabled = settings.get("create_hedge_order", True)
                
                # If hedging is disabled, skip this investor entirely
                if not create_hedge_enabled:
                    print(f"  ⏭️ HEDGING DISABLED for {user_brokerid} (create_hedge_order = false)")
                    print(f"     → Skipping hedge creation for this investor")
                    hedge_stats['investors_skipped'] += 1
                    continue
                
                print(f"  ✅ Hedging ENABLED for {user_brokerid}")
                
                # Use the global FETCHED_INVESTORS variable (same as directional_bias)
                if FETCHED_INVESTORS:
                    try:
                        with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
                            investor_users = json.load(f)
                        
                        investor_cfg = investor_users.get(user_brokerid)
                        if investor_cfg:
                            invested_with = investor_cfg.get("INVESTED_WITH", "")
                            if "_" in invested_with:
                                target_folder = invested_with.split("_", 1)[1]
                                strategy_name = target_folder
                            else:
                                target_folder = invested_with
                                strategy_name = invested_with
                    except Exception as e:
                        print(f"  Error reading verified investors: {e}")
                
                # Also get risk_reward from config if needed
                selected_risk_reward = config.get("selected_risk_reward", [3])
                if isinstance(selected_risk_reward, list) and len(selected_risk_reward) > 0:
                    risk_reward_default = selected_risk_reward[0]
                else:
                    risk_reward_default = 3
                    
            except Exception as e:
                print(f"  Error reading config: {e}")
                risk_reward_default = 3
        else:
            print(f"  ⚠️ accountmanagement.json not found, using default settings (hedging enabled)")
            risk_reward_default = 3
        
        print(f"  📁 Strategy name: {strategy_name}")
        print(f"  📁 Target folder: {target_folder}")
        
        # Connect to MT5 account
        broker_cfg = usersdictionary.get(user_brokerid)
        if not broker_cfg:
            print(f"  No broker configuration found for {user_brokerid}")
            continue
        
        login_id = int(broker_cfg['LOGIN_ID'])
        mt5_path = broker_cfg["TERMINAL_PATH"]
        
        # Check if already connected to correct account
        acc = mt5.account_info()
        if acc is None or acc.login != login_id:
            print(f"  Not logged into correct account. Expected: {login_id}")
            if not mt5.initialize(path=mt5_path, login=login_id, 
                                   password=broker_cfg["PASSWORD"], 
                                   server=broker_cfg["SERVER"]):
                print(f"   Failed to initialize MT5 for {user_brokerid}")
                continue
        else:
            print(f"  ✅ Connected to account: {acc.login}")
        
        # Step 2: Load tradeshistory.json
        history_path = investor_root / "tradeshistory.json"
        trade_details_by_ticket = {}
        trade_history_list = []
        
        if history_path.exists():
            try:
                with open(history_path, 'r', encoding='utf-8') as f:
                    trade_history_list = json.load(f)
                
                for trade in trade_history_list:
                    ticket = trade.get('ticket')
                    if ticket:
                        trade_details_by_ticket[ticket] = trade
                
                print(f"  📋 Loaded {len(trade_details_by_ticket)} trade records from tradeshistory.json")
            except Exception as e:
                print(f"  Error reading tradeshistory.json: {e}")
        
        # Step 3: Get MT5 running positions AND pending orders
        print(f"  🔍 Fetching running positions from MT5 terminal...")
        mt5_positions = mt5.positions_get()
        mt5_pending_orders = mt5.orders_get()
        
        if mt5_positions is None:
            print(f"  No MT5 positions found or error retrieving positions")
        
        # Filter by magic numbers
        investor_magics = set()
        for trade in trade_history_list:
            magic = trade.get('magic')
            if magic:
                investor_magics.add(int(magic))
        
        if investor_magics:
            running_positions = [p for p in mt5_positions if p.magic in investor_magics] if mt5_positions else []
            pending_orders = [o for o in mt5_pending_orders if o.magic in investor_magics] if mt5_pending_orders else []
            print(f"  📊 Found {len(running_positions)} running positions in MT5")
            print(f"  📊 Found {len(pending_orders)} pending orders in MT5")
        else:
            running_positions = list(mt5_positions) if mt5_positions else []
            pending_orders = list(mt5_pending_orders) if mt5_pending_orders else []
            print(f"  📊 Found {len(running_positions)} running positions in MT5")
            print(f"  📊 Found {len(pending_orders)} pending orders in MT5")
        
        # Create sets of ALL active tickets (running + pending)
        running_tickets = {p.ticket for p in running_positions} if running_positions else set()
        pending_tickets = {o.ticket for o in pending_orders} if pending_orders else set()
        all_active_tickets = running_tickets | pending_tickets
        
        print(f"  🎫 All active tickets (running + pending): {len(all_active_tickets)}")
        
        # ============================================================
        # NEW STEP: CLEANUP ORPHANED HEDGE ORDERS
        # Check if hedge's parent ticket is NOT in active positions/pending orders
        # If parent is gone -> close/cancel the hedge using close_unauthorized_orders logic
        # ============================================================
        print(f"\n  🧹 CHECKING FOR ORPHANED HEDGE ORDERS...")
        
        orphaned_hedges_removed = 0
        
        # Check running positions that are hedges
        if running_positions:
            for position in running_positions:
                # Check if this position is a hedge order
                # Look for it in trade history
                pos_ticket = position.ticket
                trade_record = trade_details_by_ticket.get(pos_ticket, {})
                
                if trade_record.get('is_hedge_order'):
                    parent_ticket = trade_record.get('parent_ticket')
                    
                    if parent_ticket and parent_ticket not in all_active_tickets:
                        # Parent is no longer active - close this hedge position
                        print(f"\n    🚨 ORPHANED HEDGE FOUND: Position #{pos_ticket}")
                        print(f"       • Symbol: {position.symbol}")
                        print(f"       • Type: {'BUY' if position.type == mt5.POSITION_TYPE_BUY else 'SELL'}")
                        print(f"       • Parent ticket {parent_ticket} is NOT active anymore")
                        print(f"       → Closing this orphaned hedge...")
                        
                        # Get current market price
                        tick = mt5.symbol_info_tick(position.symbol)
                        if not tick:
                            print(f"         Cannot get price for {position.symbol} - cannot close")
                            hedge_stats['errors'] += 1
                            continue
                        
                        # Determine closing order type
                        if position.type == mt5.POSITION_TYPE_BUY:
                            close_type = mt5.ORDER_TYPE_SELL
                            close_price = tick.bid
                        else:
                            close_type = mt5.ORDER_TYPE_BUY
                            close_price = tick.ask
                        
                        close_request = {
                            "action": mt5.TRADE_ACTION_DEAL,
                            "symbol": position.symbol,
                            "volume": position.volume,
                            "type": close_type,
                            "position": pos_ticket,
                            "price": close_price,
                            "deviation": 20,
                            "magic": position.magic if hasattr(position, 'magic') else 0,
                            "comment": "ORPHANED HEDGE - Parent closed",
                            "type_time": mt5.ORDER_TIME_GTC,
                            "type_filling": mt5.ORDER_FILLING_IOC,
                        }
                        
                        try:
                            result = mt5.order_send(close_request)
                            
                            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                                print(f"         ✅ SUCCESS: Orphaned hedge #{pos_ticket} CLOSED")
                                orphaned_hedges_removed += 1
                                hedge_stats['orphaned_hedges_closed'] += 1
                                
                                # Update trade history
                                trade_record['status'] = 'closed'
                                trade_record['closed_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                trade_record['closed_reason'] = 'orphaned_hedge_parent_closed'
                            else:
                                error_msg = result.comment if result else "No response"
                                error_code = result.retcode if result else "Unknown"
                                print(f"          FAILED: {error_msg} (code: {error_code})")
                                
                                # Try alternative closure
                                print(f"         🔄 Attempting alternative closure...")
                                alt_close_request = {
                                    "action": mt5.TRADE_ACTION_DEAL,
                                    "symbol": position.symbol,
                                    "volume": position.volume,
                                    "type": close_type,
                                    "position": pos_ticket,
                                    "price": close_price,
                                    "deviation": 50,
                                    "comment": "ORPHANED HEDGE - Retry",
                                    "type_filling": mt5.ORDER_FILLING_RETURN,
                                }
                                
                                alt_result = mt5.order_send(alt_close_request)
                                if alt_result and alt_result.retcode == mt5.TRADE_RETCODE_DONE:
                                    print(f"         ✅ SUCCESS (alt): Orphaned hedge #{pos_ticket} CLOSED")
                                    orphaned_hedges_removed += 1
                                    hedge_stats['orphaned_hedges_closed'] += 1
                                    
                                    trade_record['status'] = 'closed'
                                    trade_record['closed_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    trade_record['closed_reason'] = 'orphaned_hedge_parent_closed'
                                else:
                                    alt_error = alt_result.comment if alt_result else "No response"
                                    print(f"          Alternative also FAILED: {alt_error}")
                                    hedge_stats['errors'] += 1
                        except Exception as e:
                            print(f"          EXCEPTION: {e}")
                            hedge_stats['errors'] += 1
        
        # Check pending orders that are hedges
        if pending_orders:
            for order in pending_orders:
                order_ticket = order.ticket
                trade_record = trade_details_by_ticket.get(order_ticket, {})
                
                if trade_record.get('is_hedge_order'):
                    parent_ticket = trade_record.get('parent_ticket')
                    
                    if parent_ticket and parent_ticket not in all_active_tickets:
                        # Parent is no longer active - cancel this hedge pending order
                        print(f"\n    🚨 ORPHANED HEDGE PENDING ORDER: #{order_ticket}")
                        print(f"       • Symbol: {order.symbol}")
                        print(f"       • Type: {order.type}")
                        print(f"       • Parent ticket {parent_ticket} is NOT active anymore")
                        print(f"       → Cancelling this orphaned hedge order...")
                        
                        cancel_request = {
                            "action": mt5.TRADE_ACTION_REMOVE,
                            "order": order_ticket
                        }
                        
                        try:
                            result = mt5.order_send(cancel_request)
                            
                            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                                print(f"         ✅ SUCCESS: Orphaned hedge order #{order_ticket} CANCELLED")
                                orphaned_hedges_removed += 1
                                hedge_stats['orphaned_hedges_cancelled'] += 1
                                
                                # Update trade history
                                trade_record['status'] = 'cancelled'
                                trade_record['cancelled_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                trade_record['cancelled_reason'] = 'orphaned_hedge_parent_closed'
                            else:
                                error_msg = result.comment if result else "No response"
                                error_code = result.retcode if result else "Unknown"
                                print(f"          FAILED: {error_msg} (code: {error_code})")
                                hedge_stats['errors'] += 1
                        except Exception as e:
                            print(f"          EXCEPTION: {e}")
                            hedge_stats['errors'] += 1
        
        if orphaned_hedges_removed > 0:
            print(f"\n  ✅ Removed {orphaned_hedges_removed} orphaned hedge(s) from MT5")
        
        # Step 4: CRITICAL - Check for closed positions in MT5 history
        print(f"\n  🔍 Checking MT5 history for closed positions...")
        
        # Get history deals from last 7 days
        from_date = datetime.now() - timedelta(days=7)
        to_date = datetime.now()
        
        # Get all closed positions from MT5 history
        history_deals = mt5.history_deals_get(from_date, to_date)
        
        # Track which positions we've processed for hedging
        positions_to_hedge = []
        positions_closed_profit_tickets = []
        positions_closed_loss_tickets = []
        
        if history_deals:
            # Group deals by position_id to find closed positions
            closed_positions = {}
            for deal in history_deals:
                if deal.type in [mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL]:
                    pos_id = deal.position_id
                    if pos_id not in closed_positions:
                        closed_positions[pos_id] = []
                    closed_positions[pos_id].append(deal)
            
            # Check each closed position against our trade history
            for pos_id, deals in closed_positions.items():
                # Find the closing deal (profit/loss)
                closing_deal = None
                total_profit = 0
                
                for deal in deals:
                    if deal.type in [mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL]:
                        total_profit += deal.profit
                        # The last deal in the sequence is usually the closing one
                        closing_deal = deal
                
                # Check if this position exists in our trade history
                if pos_id in trade_details_by_ticket:
                    trade_record = trade_details_by_ticket[pos_id]
                    current_status = trade_record.get('status')
                    
                    # If position is not running in MT5 but was previously running
                    if pos_id not in running_tickets and current_status == 'running_position':
                        is_profitable = total_profit > 0
                        
                        print(f"\n    📍 Closed position found: Ticket {pos_id}")
                        print(f"       • Profit/Loss: ${total_profit:.2f}")
                        print(f"       • Profitable: {is_profitable}")
                        
                        # Update trade history
                        trade_record['status'] = 'closed'
                        trade_record['closed_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        trade_record['closed_profit'] = total_profit
                        trade_record['closed_profitable'] = is_profitable
                        
                        if is_profitable:
                            positions_closed_profit_tickets.append(pos_id)
                            print(f"       ✅ Closed in PROFIT - will remove hedge")
                        else:
                            positions_closed_loss_tickets.append(pos_id)
                            print(f"        Closed in LOSS - keeping hedge for protection")
            
            # Save updated trade history
            if positions_closed_profit_tickets or positions_closed_loss_tickets:
                try:
                    with open(history_path, 'w', encoding='utf-8') as f:
                        json.dump(trade_history_list, f, indent=4)
                    print(f"\n  💾 Updated trade history with closed position statuses")
                except Exception as e:
                    print(f"   Error saving trade history: {e}")
        
        # Step 5: Remove hedges for positions that closed in profit
        if positions_closed_profit_tickets:
            print(f"\n  🗑️ REMOVING HEDGES FOR PROFITABLE CLOSED POSITIONS...")
            
            strategy_base_dir = investor_root / strategy_name
            signals_file = strategy_base_dir / "pending_orders" / "limit_orders.json"
            
            if signals_file.exists():
                try:
                    with open(signals_file, 'r', encoding='utf-8') as f:
                        limit_orders = json.load(f)
                    
                    original_count = len(limit_orders)
                    orders_to_keep = []
                    removed_count = 0
                    
                    for order in limit_orders:
                        # Check if this order is a hedge for a closed profitable position
                        parent_ticket = order.get('parent_ticket')
                        is_hedge = order.get('is_hedge_order', False)
                        
                        if is_hedge and parent_ticket in positions_closed_profit_tickets:
                            # Remove this hedge order
                            print(f"    🗑️ Removing hedge for ticket {parent_ticket}: {order.get('order_type', 'unknown')} {order.get('symbol', 'unknown')} @ {order.get('entry', 'unknown')}")
                            removed_count += 1
                            hedge_stats['hedges_removed'] += 1
                            continue
                        else:
                            # Keep this order
                            orders_to_keep.append(order)
                    
                    if removed_count > 0:
                        # Save the filtered orders
                        with open(signals_file, 'w', encoding='utf-8') as f:
                            json.dump(orders_to_keep, f, indent=4)
                        
                        print(f"\n  ✅ Removed {removed_count} hedge(s) from limit_orders.json")
                        print(f"  📊 Remaining orders: {len(orders_to_keep)}")
                        hedge_stats['positions_closed_profit'] += len(positions_closed_profit_tickets)
                    else:
                        print(f"  ℹ️ No hedge orders found for closed profitable positions")
                        
                except Exception as e:
                    print(f"   Error processing limit_orders.json: {e}")
                    hedge_stats['errors'] += 1
        
        # Update statistics for loss positions
        if positions_closed_loss_tickets:
            hedge_stats['positions_closed_loss'] += len(positions_closed_loss_tickets)
            print(f"\n  ℹ️ {len(positions_closed_loss_tickets)} position(s) closed in loss - hedges kept as protection")
        
        # Step 6: Only process positions that are still running AND not yet hedged
        if not running_positions:
            print(f"\n  ℹ️ No running positions found for {user_brokerid}")
            continue
        
        hedge_stats['investors_processed'] += 1
        hedge_stats['positions_analyzed'] += len(running_positions)
        
        # Step 7: Load existing signals to check for existing hedges
        strategy_base_dir = investor_root / strategy_name
        pending_orders_dir = strategy_base_dir / "pending_orders"
        signals_file = pending_orders_dir / "limit_orders.json"
        pending_orders_dir.mkdir(parents=True, exist_ok=True)
        
        existing_signals = []
        if signals_file.exists():
            try:
                with open(signals_file, 'r', encoding='utf-8') as f:
                    existing_signals = json.load(f)
                print(f"\n  📋 Loaded {len(existing_signals)} existing signals from limit_orders.json")
            except Exception as e:
                print(f"  Error reading existing signals: {e}")
        
        # Step 8: Create hedges for remaining running positions
        hedges_created_for_investor = 0
        
        for position in running_positions:
            # Skip if this position itself is a hedge order
            pos_ticket = position.ticket
            pos_trade = trade_details_by_ticket.get(pos_ticket, {})
            if pos_trade.get('is_hedge_order'):
                print(f"\n  ⏭️ Position #{pos_ticket} is a hedge order - skipping")
                continue
            
            print(f"\n  🔍 Analyzing MT5 position: Ticket {position.ticket}")
            print(f"     • Symbol: {position.symbol}")
            print(f"     • Type: {'BUY' if position.type == mt5.ORDER_TYPE_BUY else 'SELL'}")
            print(f"     • Entry: {position.price_open}")
            print(f"     • Current: {position.price_current}")
            print(f"     • Volume: {position.volume}")
            print(f"     • Profit: ${position.profit:.2f}")
            
            # Check if hedge already exists for this position
            hedge_exists = False
            for signal in existing_signals:
                if signal.get('parent_ticket') == position.ticket and signal.get('is_hedge_order'):
                    hedge_exists = True
                    print(f"     ⏭️ Hedge already exists for this position")
                    hedge_stats['hedges_skipped'] = hedge_stats.get('hedges_skipped', 0) + 1
                    break
            
            if hedge_exists:
                continue
            
            # Get trade details from history
            trade_detail = trade_details_by_ticket.get(position.ticket, {})
            
            if trade_detail:
                print(f"     ✅ Found matching trade record")
                original_order_type = trade_detail.get('placed_order_type', '')
                exit_price = trade_detail.get('exit', 0)  # This is the stop loss
                candle_1_high = trade_detail.get('candle_1_high')
                candle_1_low = trade_detail.get('candle_1_low')
                candle_1_type = trade_detail.get('candle_1_type', '').lower()
                timeframe = trade_detail.get('timeframe', '')
                risk_reward = trade_detail.get('risk_reward', risk_reward_default)
                magic = trade_detail.get('magic', position.magic)
                
                # ========== DYNAMIC BROKER VOLUME EXTRACTION ==========
                # Find the broker-specific volume field from the parent trade
                volume_field_name, volume = get_broker_volume_field(trade_detail)
                
                if volume_field_name:
                    print(f"     📊 Found broker volume field '{volume_field_name}': {volume}")
                else:
                    # Fallback to standardized 'volume' field or position volume
                    volume = trade_detail.get('volume', trade_detail.get('placed_volume', position.volume))
                    print(f"     No *_volume field found, using fallback volume: {volume}")
                # ========== END DYNAMIC VOLUME EXTRACTION ==========
            else:
                print(f"     No trade record - using MT5 data")
                original_order_type = 'buy' if position.type == mt5.ORDER_TYPE_BUY else 'sell'
                exit_price = 0
                candle_1_high = None
                candle_1_low = None
                candle_1_type = ''
                timeframe = ''
                risk_reward = risk_reward_default
                volume = position.volume
                volume_field_name = None  # No broker field to preserve
                magic = position.magic
            
            # Create hedge (opposite direction)
            is_position_buy = (position.type == mt5.ORDER_TYPE_BUY)
            
            # Flip order type
            def flip_order_type(original_type, is_buy_position):
                if original_type:
                    original_lower = original_type.lower()
                else:
                    original_lower = 'buy' if is_buy_position else 'sell'
                
                if original_lower == 'instant_buy':
                    return 'instant_sell'
                if original_lower == 'instant_sell':
                    return 'instant_buy'
                
                if '_' in original_lower:
                    parts = original_lower.split('_', 1)
                    direction = parts[0]
                    suffix = parts[1]
                    new_direction = 'sell' if direction == 'buy' else 'buy'
                    return f"{new_direction}_{suffix}"
                else:
                    if original_lower == 'buy':
                        return 'sell'
                    elif original_lower == 'sell':
                        return 'buy'
                    return original_lower
            
            opposite_order_type = flip_order_type(original_order_type, is_position_buy)
            is_hedge_buy = 'buy' in opposite_order_type.lower()
            
            # Hedge entry = parent's exit (stop loss)
            if exit_price and exit_price > 0:
                hedge_entry = exit_price
                print(f"     🎯 Hedge entry (parent SL): {hedge_entry}")
            else:
                tick = mt5.symbol_info_tick(position.symbol)
                hedge_entry = tick.ask if is_hedge_buy else tick.bid if tick else position.price_current
                print(f"     No SL found - using current price: {hedge_entry}")
            
            # Determine digits
            digits = 5 if hedge_entry < 1 else len(f"{hedge_entry:.10f}".rstrip('0').split('.')[1]) if '.' in f"{hedge_entry:.10f}" else 2
            
            # Hedge stop loss based on candle
            if candle_1_type == "bearish" and candle_1_high:
                hedge_exit = candle_1_high
            elif candle_1_type == "bullish" and candle_1_low:
                hedge_exit = candle_1_low
            else:
                hedge_exit = hedge_entry - (hedge_entry * 0.005) if is_hedge_buy else hedge_entry + (hedge_entry * 0.005)
            
            hedge_entry = round(hedge_entry, digits)
            hedge_exit = round(hedge_exit, digits)
            
            # Take profit based on risk/reward
            risk_amount = abs(hedge_entry - hedge_exit)
            target_distance = risk_amount * risk_reward
            hedge_target = round(hedge_entry + target_distance if is_hedge_buy else hedge_entry - target_distance, digits)
            
            # Validate volume against symbol limits (NO ROUNDING)
            symbol_info = mt5.symbol_info(position.symbol)
            if symbol_info:
                volume = max(symbol_info.volume_min, min(symbol_info.volume_max, volume))
            
            # Create hedge order
            hedge_id = f"hedge_{position.ticket}_{position.symbol}_{int(datetime.now().timestamp())}"
            
            hedge_order = {
                "symbol": position.symbol,
                "timeframe": timeframe,
                "risk_reward": risk_reward,
                "order_type": opposite_order_type,
                "entry": hedge_entry,
                "exit": hedge_exit,
                "target": hedge_target,
                "is_hedge_order": True,
                "hedge_type": "position_hedge",
                "candle_1_high": round(candle_1_high, digits) if candle_1_high else None,
                "candle_1_low": round(candle_1_low, digits) if candle_1_low else None,
                "candle_1_type": candle_1_type,
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "strategy": strategy_name,
                "magic": magic,
                "volume": volume,
                "hedge_id": hedge_id,
                "parent_ticket": position.ticket,
                "parent_order_type": original_order_type,
                "parent_entry": position.price_open,
                "parent_exit": exit_price,
                "parent_profit": position.profit,
                "status": "Calculated",
                "created_by": "create_position_hedge_function"
            }
            
            # ========== PRESERVE BROKER VOLUME FIELD ==========
            # If parent had a broker-specific volume field (e.g., deriv_volume, bybit_volume),
            # add the same field to the hedge order
            if volume_field_name:
                hedge_order[volume_field_name] = volume
                print(f"     📊 Preserved broker volume field: {volume_field_name} = {volume}")
            # ========== END BROKER VOLUME PRESERVATION ==========
            
            # Remove None values
            hedge_order = {k: v for k, v in hedge_order.items() if v is not None}
            
            # Add to signals
            existing_signals.append(hedge_order)
            hedges_created_for_investor += 1
            hedge_stats['hedges_created'] += 1
            
            print(f"\n     ✅ HEDGE CREATED: {opposite_order_type.upper()} @ {hedge_entry}")
            print(f"        • Stop Loss: {hedge_exit} | Target: {hedge_target}")
            print(f"        • Hedge ID: {hedge_id}")
            print(f"        • Volume: {volume}" + (f" (via {volume_field_name})" if volume_field_name else ""))
        
        # Step 9: Save updated signals
        if hedges_created_for_investor > 0 or hedge_stats['hedges_removed'] > 0 or orphaned_hedges_removed > 0:
            try:
                # Save trade history if we made changes
                if orphaned_hedges_removed > 0 or positions_closed_profit_tickets or positions_closed_loss_tickets:
                    with open(history_path, 'w', encoding='utf-8') as f:
                        json.dump(trade_history_list, f, indent=4)
                
                # Save limit orders
                if hedges_created_for_investor > 0 or hedge_stats['hedges_removed'] > 0:
                    with open(signals_file, 'w', encoding='utf-8') as f:
                        json.dump(existing_signals, f, indent=4)
                    
                    hedge_count = sum(1 for s in existing_signals if s.get('is_hedge_order', False))
                    print(f"\n  💾 Saved {len(existing_signals)} signals to {signals_file}")
                    print(f"     • Hedges in file: {hedge_count}")
                    print(f"     • New hedges added: {hedges_created_for_investor}")
                    print(f"     • Hedges removed: {hedge_stats['hedges_removed']}")
                
            except Exception as e:
                print(f"   Error saving signals: {e}")
                hedge_stats['errors'] += 1
        
        # Investor summary
        print(f"\n  📊 SUMMARY for {user_brokerid}:")
        print(f"     • Running positions: {len(running_positions)}")
        print(f"     • Pending orders: {len(pending_orders)}")
        print(f"     • Closed in profit: {len(positions_closed_profit_tickets)}")
        print(f"     • Closed in loss: {len(positions_closed_loss_tickets)}")
        print(f"     • Orphaned hedges removed: {orphaned_hedges_removed}")
        print(f"     • Hedges created: {hedges_created_for_investor}")
        print(f"     • Hedges removed from JSON: {hedge_stats['hedges_removed']}")
    
    # Global summary
    print("\n" + "="*80)
    print("📊 GLOBAL HEDGE SUMMARY")
    print("="*80)
    print(f"  • Investors processed: {hedge_stats['investors_processed']}")
    print(f"  • Investors skipped (hedging disabled): {hedge_stats['investors_skipped']}")
    print(f"  • Positions analyzed: {hedge_stats['positions_analyzed']}")
    print(f"  • Hedges created: {hedge_stats['hedges_created']}")
    print(f"  • Hedges removed from JSON: {hedge_stats['hedges_removed']}")
    print(f"  • Orphaned hedges closed: {hedge_stats['orphaned_hedges_closed']}")
    print(f"  • Orphaned hedges cancelled: {hedge_stats['orphaned_hedges_cancelled']}")
    print(f"  • Positions closed profit: {hedge_stats['positions_closed_profit']}")
    print(f"  • Positions closed loss: {hedge_stats['positions_closed_loss']}")
    print(f"  • Errors: {hedge_stats['errors']}")
    print("="*80)
    
    return hedge_stats['hedges_created'] > 0 or hedge_stats['hedges_removed'] > 0 or hedge_stats['orphaned_hedges_closed'] > 0 or hedge_stats['orphaned_hedges_cancelled'] > 0
#-------   ###   -------#

def get_normalized_symbol(record_symbol, risk_keys=None):
    """
    Standardizes symbols with a 'Broker-First' priority.
    If 'US OIL' is passed, it finds the USOIL family, then checks if the broker
    uses USOUSD, USOIL, or WTI.
    """
    if not record_symbol: 
        return None
    
    def clean(s): 
        return str(s).replace(" ", "").replace("_", "").replace("/", "").replace(".", "").upper()

    search_term = clean(record_symbol)
    
    # Convert NORMALIZE_SYMBOLS_PATH to Path object if it's a string
    normalize_path = Path(NORMALIZE_SYMBOLS_PATH) if isinstance(NORMALIZE_SYMBOLS_PATH, str) else NORMALIZE_SYMBOLS_PATH
    
    # 1. Load Normalization Map
    norm_data = {}
    if normalize_path.exists():
        try:
            with open(normalize_path, 'r', encoding='utf-8') as f:
                norm_data = json.load(f).get("NORMALIZATION", {})
        except: 
            pass

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
            if v in clean_risk_map: 
                return clean_risk_map[v]

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
    and pending_orders/limit_orders.json files and removes duplicate orders based on: 
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
                    print(f"  └─  Error processing {limit_file}: {e}")

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
                    print(f"  └─  Error processing {limit_backup_file}: {e}")

            # Process limit_orders.json
            signals_file = pending_folder / "limit_orders.json"
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
                            print(f"  └─ 📄 {folder_name}/limit_orders.json - Removed {removed} duplicates")

                except Exception as e:
                    print(f"  └─  Error processing {signals_file}: {e}")

        # Summary for the current investor
        if investor_limit_duplicates > 0 or investor_signal_duplicates > 0 or investor_limit_backup_duplicates > 0:
            print(f"\n  └─ ✨ Investor {current_inv_id} Cleanup Summary:")
            if investor_limit_duplicates > 0:
                print(f"      • limit_orders.json: Cleaned {investor_limit_files_cleaned} files | Removed {investor_limit_duplicates} duplicates")
            if investor_limit_backup_duplicates > 0:
                print(f"      • limit_orders_backup.json: Cleaned {investor_limit_backup_files_cleaned} files | Removed {investor_limit_backup_duplicates} duplicates")
            if investor_signal_duplicates > 0:
                print(f"      • limit_orders.json: Cleaned {investor_signal_files_cleaned} files | Removed {investor_signal_duplicates} duplicates")
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
        print(f"   • limit_orders.json:             {total_signal_files_cleaned} files | {total_signal_duplicates} duplicates")
    else:
        print(" ✅ Everything was already clean - no duplicates found!")
    print(f"{'='*33}\n")
    
    return any_duplicates_removed

def filter_unauthorized_symbols(inv_id=None):
    """
    Verifies and filters pending order files based on allowed symbols defined in accountmanagement.json.
    Now filters both limit_orders.json and signal_orders.json files, removing any entries with unauthorized symbols.
    Also cancels unauthorized pending orders in MT5.
    Matches sanitized versions of symbols to handle broker suffixes (e.g., EURUSDm vs EURUSD).
    
    Args:
        inv_id (str, optional): Specific investor ID to process. If None, processes all investors.
        This function DOES require MT5 for order cancellation.
    
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
    total_mt5_orders_cancelled = 0
    total_mt5_orders_failed = 0
    any_symbols_removed = False

    for current_inv_id in investor_ids:
        print(f"\n [{current_inv_id}] 🔍 Verifying symbol permissions...")
        inv_folder = Path(INV_PATH) / current_inv_id
        acc_mgmt_path = inv_folder / "accountmanagement.json"
        
        if not acc_mgmt_path.exists():
            print(f"  └─  Account config missing. Skipping.")
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

            # ===================================================================
            # PART 1: Filter pending order FILES
            # ===================================================================
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
                        print(f"    └─  Error processing {limit_file}: {e}")

                # Process signal_orders.json
                signals_file = pending_folder / "signal_orders.json"
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
                                print(f"    └─ 📄 {folder_name}/signal_orders.json - Removed {removed} unauthorized entries")
                            elif original_count > 0:
                                folder_name = pending_folder.parent.name
                                print(f"    └─ ✅ {folder_name}/signal_orders.json - All symbols authorized ({original_count} entries)")

                    except Exception as e:
                        print(f"    └─  Error processing {signals_file}: {e}")

            # Summary for file filtering
            if investor_limit_removed > 0 or investor_signal_removed > 0:
                print(f"\n  └─ 📁 File Filter Summary for {current_inv_id}:")
                if investor_limit_removed > 0:
                    print(f"      • limit_orders.json: Cleaned {investor_limit_files_cleaned} files | Removed {investor_limit_removed} unauthorized entries")
                if investor_signal_removed > 0:
                    print(f"      • signal_orders.json: Cleaned {investor_signal_files_cleaned} files | Removed {investor_signal_removed} unauthorized entries")

            # ===================================================================
            # PART 2: Cancel unauthorized MT5 pending orders
            # ===================================================================
            print(f"\n  └─ 📡 Checking MT5 pending orders for unauthorized symbols...")
            
            # ========== USE EXISTING MT5 CONNECTION - NO INITIALIZE/SHUTDOWN ==========
            # Verify MT5 is connected
            if not mt5.terminal_info():
                print(f"     └─  MT5 not connected. Skipping MT5 check.")
                continue
            
            # Verify we're on the correct account
            broker_cfg = usersdictionary.get(current_inv_id)
            if broker_cfg:
                expected_login = int(broker_cfg.get("LOGIN_ID", 0))
                acc = mt5.account_info()
                if acc and acc.login != expected_login:
                    print(f"     └─  Not on expected account (current: {acc.login}, expected: {expected_login}). Skipping.")
                    continue
            
            try:
                # Get all pending orders
                pending_orders = mt5.orders_get()
                
                if pending_orders is None or len(pending_orders) == 0:
                    print(f"     └─ 🔘 No pending orders found in MT5")
                else:
                    unauthorized_orders = []
                    authorized_orders = []
                    
                    for order in pending_orders:
                        order_symbol = order.symbol
                        sanitized_symbol = sanitize(order_symbol)
                        
                        if sanitized_symbol in allowed_sanitized:
                            authorized_orders.append(order)
                        else:
                            unauthorized_orders.append(order)
                    
                    print(f"     └─ 📊 MT5 Orders: {len(pending_orders)} total | {len(authorized_orders)} authorized | {len(unauthorized_orders)} unauthorized")
                    
                    # Cancel unauthorized orders
                    if unauthorized_orders:
                        print(f"\n     └─ 🚫 Cancelling {len(unauthorized_orders)} unauthorized MT5 orders...")
                        
                        for order in unauthorized_orders:
                            order_type_names = {
                                mt5.ORDER_TYPE_BUY_LIMIT: "BUY LIMIT",
                                mt5.ORDER_TYPE_SELL_LIMIT: "SELL LIMIT",
                                mt5.ORDER_TYPE_BUY_STOP: "BUY STOP",
                                mt5.ORDER_TYPE_SELL_STOP: "SELL STOP",
                                mt5.ORDER_TYPE_BUY_STOP_LIMIT: "BUY STOP-LIMIT",
                                mt5.ORDER_TYPE_SELL_STOP_LIMIT: "SELL STOP-LIMIT"
                            }
                            order_type_name = order_type_names.get(order.type, f"Type {order.type}")
                            
                            print(f"        • Cancelling {order_type_name} #{order.ticket} | Symbol: {order.symbol} (unauthorized)")
                            
                            cancel_request = {
                                "action": mt5.TRADE_ACTION_REMOVE,
                                "order": order.ticket
                            }
                            result = mt5.order_send(cancel_request)
                            
                            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                                total_mt5_orders_cancelled += 1
                                any_symbols_removed = True
                                print(f"          ✅ Cancelled successfully")
                            else:
                                total_mt5_orders_failed += 1
                                error_msg = result.comment if result else f"Error code: {mt5.last_error()}"
                                print(f"           Cancel failed: {error_msg}")
                        
                        if total_mt5_orders_failed > 0:
                            print(f"\n         {total_mt5_orders_failed} orders failed to cancel")
                    else:
                        print(f"     └─ ✅ All MT5 pending orders use authorized symbols")
                
                # MT5 summary for this investor
                if total_mt5_orders_cancelled > 0:
                    print(f"\n     └─ 📡 MT5 Filter Summary for {current_inv_id}:")
                    print(f"         • Unauthorized orders cancelled: {total_mt5_orders_cancelled}")
                    if total_mt5_orders_failed > 0:
                        print(f"         • Failed cancellations: {total_mt5_orders_failed}")
                
            except Exception as e:
                print(f"     └─  Error during MT5 order filtering: {e}")
            
            # ========== NO mt5.shutdown() - keep connection alive ==========

            # Overall investor summary
            print(f"\n  └─ ✨ Investor {current_inv_id} Complete Filter Summary:")
            if investor_limit_removed > 0 or investor_signal_removed > 0 or total_mt5_orders_cancelled > 0:
                if investor_limit_removed > 0:
                    print(f"      • 📁 limit_orders.json: {investor_limit_files_cleaned} files cleaned | {investor_limit_removed} entries removed")
                if investor_signal_removed > 0:
                    print(f"      • 📁 signal_orders.json: {investor_signal_files_cleaned} files cleaned | {investor_signal_removed} entries removed")
                if total_mt5_orders_cancelled > 0:
                    print(f"      • 📡 MT5 Orders: {total_mt5_orders_cancelled} cancelled | {total_mt5_orders_failed} failed")
            else:
                # Check if any files or orders were found at all
                if pending_orders_folders or (pending_orders and len(pending_orders) > 0):
                    print(f"  └─ ✅ All symbols in order files and MT5 orders are authorized")
                else:
                    print(f"  └─ 🔘 No pending orders or order files found")

        except Exception as e:
            print(f"  └─  Error processing {current_inv_id}: {e}")

    # Final Global Summary
    print(f"\n{'='*10} SYMBOL FILTERING COMPLETE {'='*10}")
    
    total_files_cleaned = total_limit_files_cleaned + total_signal_files_cleaned
    total_entries_removed = total_limit_removed + total_signal_removed
    
    if total_entries_removed > 0 or total_mt5_orders_cancelled > 0:
        print(f" 📊 GRAND TOTAL:")
        if total_entries_removed > 0:
            print(f"   📁 File entries removed: {total_entries_removed}")
            print(f"   📁 Files modified:       {total_files_cleaned}")
            print(f"     • limit_orders.json:   {total_limit_files_cleaned} files | {total_limit_removed} entries removed")
            print(f"     • signal_orders.json:  {total_signal_files_cleaned} files | {total_signal_removed} entries removed")
        if total_mt5_orders_cancelled > 0:
            print(f"   📡 MT5 orders cancelled:  {total_mt5_orders_cancelled}")
            if total_mt5_orders_failed > 0:
                print(f"    MT5 cancellations failed: {total_mt5_orders_failed}")
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
    Now filters both limit_orders.json and limit_orders.json files, removing any entries with restricted timeframes.
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
            print(f"  └─  Account config missing. Skipping.")
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
                        print(f"    └─  Error processing {limit_file}: {e}")

                # Process limit_orders.json
                signals_file = pending_folder / "limit_orders.json"
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
                                print(f"    └─ 📄 {folder_name}/limit_orders.json - Removed {removed} restricted timeframe entries")
                            elif original_count > 0:
                                folder_name = pending_folder.parent.name
                                print(f"    └─ ✅ {folder_name}/limit_orders.json - All timeframes authorized ({original_count} entries)")

                    except Exception as e:
                        print(f"    └─  Error processing {signals_file}: {e}")

            # Summary for the current investor
            if investor_limit_removed > 0 or investor_signal_removed > 0:
                print(f"\n  └─ ✨ Investor {current_inv_id} Filter Summary:")
                if investor_limit_removed > 0:
                    print(f"      • limit_orders.json: Cleaned {investor_limit_files_cleaned} files | Removed {investor_limit_removed} restricted entries")
                if investor_signal_removed > 0:
                    print(f"      • limit_orders.json: Cleaned {investor_signal_files_cleaned} files | Removed {investor_signal_removed} restricted entries")
                print(f"     (Blocked timeframes: {', '.join(restricted_set)})")
            else:
                # Check if any files were found at all
                if pending_orders_folders:
                    print(f"  └─ ✅ All timeframes in order files are authorized")
                else:
                    print(f"  └─ 🔘 No pending_orders folders found")

        except Exception as e:
            print(f"  └─  Error processing {current_inv_id}: {e}")

    # Final Global Summary
    print(f"\n{'='*10} TIMEFRAME FILTERING COMPLETE {'='*10}")
    
    total_files_cleaned = total_limit_files_cleaned + total_signal_files_cleaned
    total_entries_removed = total_limit_removed + total_signal_removed
    
    if total_entries_removed > 0:
        print(f" Total Restricted Entries Removed: {total_entries_removed}")
        print(f" Total Files Modified:              {total_files_cleaned}")
        print(f"\n Breakdown by file type:")
        print(f"   • limit_orders.json:   {total_limit_files_cleaned} files | {total_limit_removed} entries removed")
        print(f"   • limit_orders.json:        {total_signal_files_cleaned} files | {total_signal_removed} entries removed")
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
    old_limit_orders.json in the same directory.
    
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
            backup_path = source_path.parent / "old_limit_orders.json"
            
            try:
                # 4. Create the copy (overwrites existing backup)
                shutil.copy2(source_path, backup_path)
                
                print(f"  └─ ✅ Backed up: {source_path.parent.parent.name} -> old_limit_orders.json")
                total_backups_created += 1
                
            except Exception as e:
                print(f"  └─  Error backing up {source_path}: {e}")

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
                        # Perform mapping only once
                        broker_symbol = get_normalized_symbol(raw_symbol)

                        # CASE-INSENSITIVE FIX: Try to find the symbol with correct case
                        symbol_info = mt5.symbol_info(broker_symbol)
                        if symbol_info is None and broker_symbol:
                            # Try case-insensitive lookup
                            all_symbols = mt5.symbols_get()
                            if all_symbols:
                                symbols_lower_map = {s.name.lower(): s.name for s in all_symbols}
                                symbol_lower = broker_symbol.lower()
                                if symbol_lower in symbols_lower_map:
                                    correct_symbol = symbols_lower_map[symbol_lower]
                                    if correct_symbol != broker_symbol:
                                        print(f"    └─ 🔧 Case correction: '{broker_symbol}' → '{correct_symbol}'")
                                        broker_symbol = correct_symbol
                                        symbol_info = mt5.symbol_info(broker_symbol)
                        
                        resolution_cache[raw_symbol] = {'broker_sym': broker_symbol, 'info': symbol_info}
                        
                        # Detailed Log only on first discovery
                        if symbol_info:
                            if broker_symbol != raw_symbol:
                                print(f"    └─ ✅ {raw_symbol} -> {broker_symbol} (Mapped & Cached)")
                                total_symbols_normalized += 1
                        else:
                            print(f"    └─  MT5: '{broker_symbol}' (from '{raw_symbol}') not found in MarketWatch")

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
                print(f"  └─  Error: {e}")

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
            print(f"  └─  No broker config found")
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
                print(f"  └─  Risk config error: {e}")
                continue

        known_risk_symbols = list(risk_lookup.keys())
        order_files = list(inv_folder.rglob("*/pending_orders/limit_orders.json"))
        signals_files = list(inv_folder.rglob("*/signals/limit_orders.json"))
        
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
                                    print(f"       [{label}] {raw_sym}: Not in risk config (Mapped as: {matched_sym})")
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
                    print(f"    └─  Error processing {file_path.name}: {e}")

    print(f"\n{'='*10} ENFORCEMENT COMPLETE {'='*10}")
    print(f" Total Targetless Found:  {total_orders_processed}")
    print(f" Total Risk Enforced:    {total_orders_enforced}")
    print(f" Files Updated:          {total_files_updated}")
    
    return total_orders_enforced > 0

def enforce_investor_symbols_specific_risks(inv_id=None):
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
            print(f"  └─  accountmanagement.json not found, skipping")
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
            print(f"  └─  Failed to load accountmanagement.json: {e}")
            continue

        # 2. Get Broker and Config Path
        broker_cfg = usersdictionary.get(current_inv_id)
        if not broker_cfg:
            continue
        
        broker_name = broker_cfg.get('BROKER_NAME', '').lower() or \
                      broker_cfg.get('SERVER', 'default').split('-')[0].split('.')[0].lower()

        default_config_path = Path(DEFAULT_PATH) / f"{broker_name}_default_allowedsymbolsandvolumes.json"
        if not default_config_path.exists():
            print(f"  └─  Default config not found: {default_config_path.name}")
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
            print(f"  └─  Failed to parse default config: {e}")
            continue

        # 4. Gather Files
        order_files = list(inv_folder.rglob("*/pending_orders/limit_orders.json"))
        signals_files = list(inv_folder.rglob("*/signals/limit_orders.json"))
        
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
                    print(f"    └─  Error in {file_path.name}: {e}")

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
            print(f"  └─  accountmanagement.json not found for {current_inv_id}, skipping")
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
            print(f"  └─  Failed to load accountmanagement.json: {e}")
            continue

        # 2. Get broker config for potential symbol mapping context
        broker_cfg = usersdictionary.get(current_inv_id)
        if not broker_cfg:
            print(f"  └─  No broker config found for {current_inv_id}")
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
                        print(f"    └─  Callback error for {file_path.name}: {e}")
                
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
                                    print(f"       USD-based order missing volume for {order.get('symbol', 'Unknown')}, skipping")
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
                                    print(f"       No tick_size found for {order.get('symbol', 'Unknown')}, using default")
                                
                                # Find tick_value field
                                tick_value_value = None
                                for key, value in order.items():
                                    if 'tick_value' in key.lower() and isinstance(value, (int, float)):
                                        tick_value_value = float(value)
                                        break
                                
                                if tick_value_value is None or tick_value_value <= 0:
                                    tick_value_value = 1.0
                                    print(f"       No tick_value found for {order.get('symbol', 'Unknown')}, using default")
                                
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
                            print(f"       No tick_size found for {order.get('symbol', 'Unknown')}, using default")
                        
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
                            print(f"       No tick_value found for {order.get('symbol', 'Unknown')}, using default")
                        
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
                        print(f"       Error processing order {order.get('symbol', 'Unknown')}: {e}")
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
                        print(f"    └─  Failed to save {file_path}: {e}")
                
            except Exception as e:
                print(f"    └─  Error reading {file_path}: {e}")
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
            print(f"  └─  No orders processed for {current_inv_id}")

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

def padding_stoploss_below_minimum_risk_to_minimum_risk(inv_id=None):
    """
    Function: Adjusts stoploss levels for LIMIT orders in limit_orders.json files based on
    minimum risk distance requirements from accountmanagement.json.
    
    Uses minimum_balance_risk_distance configuration to ensure each order has
    at least the minimum risk amount in USD. If order risk is below minimum,
    stoploss is recalculated to achieve the minimum risk level and the limit_orders.json
    file is updated with new exit (stoploss) and target (takeprofit) prices.
    
    Uses LIVE MT5 calculations to determine current risk and required adjustments.
    
    NO FALLBACKS - only uses exact values from minimum_balance_risk_distance.
    If threshold is missing or not configured for current balance, check is SKIPPED.
    
    Args:
        inv_id: Optional specific investor ID to process. If None, processes all investors.
        
    Returns:
        dict: Statistics about the processing
    """
    print(f"\n{'='*10} 🎯 STOPLOSS CORRECTION: MINIMUM RISK DISTANCE {'='*10}")
    if inv_id:
        print(f" Processing single investor: {inv_id}")
    
    # Track statistics
    stats = {
        "investor_id": inv_id if inv_id else "all",
        "orders_checked": 0,
        "orders_adjusted": 0,
        "orders_skipped": 0,
        "orders_error": 0,
        "insufficient_risk_found": 0,
        "minimum_risk_used": 0,
        "processing_success": False
    }
    
    # Determine which investors to process
    investors_to_process = [inv_id] if inv_id else usersdictionary.keys()
    total_investors = len(investors_to_process) if not inv_id else 1
    processed = 0
    
    for user_brokerid in investors_to_process:
        processed += 1
        print(f"\n[{processed}/{total_investors}] {user_brokerid} 🔍 Loading minimum risk configuration...")
        
        # Get broker config
        broker_cfg = usersdictionary.get(user_brokerid)
        if not broker_cfg:
            print(f"  └─  No broker config found")
            continue
        
        inv_root = Path(INV_PATH) / user_brokerid
        acc_mgmt_path = inv_root / "accountmanagement.json"
        
        if not acc_mgmt_path.exists():
            print(f"  └─  Account config missing. Skipping.")
            continue
        
        # --- LOAD CONFIG AND GET MINIMUM RISK THRESHOLD ---
        try:
            with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Check if stoploss correction is enabled in settings
            settings = config.get("settings", {})
            if not settings.get("enable_stoploss_correction", True):
                print(f"  └─ ⏭️ Stoploss correction disabled in settings. Skipping.")
                continue
            
            # Get selected risk reward
            selected_rr = config.get("selected_risk_reward", [3])
            if isinstance(selected_rr, list) and selected_rr:
                risk_reward = float(selected_rr[0])
            else:
                risk_reward = 3.0
            
            # Get minimum balance risk distance (NO FALLBACKS)
            min_risk_config = config.get("minimum_balance_risk_distance", {})
            
            # Get account balance (MT5 should already be initialized)
            account_info = mt5.account_info()
            if not account_info:
                print(f"  └─  Cannot get account info - MT5 not initialized?")
                stats["orders_error"] += 1
                continue
            
            account_balance = account_info.balance
            print(f"  └─ 💰 Account Balance: ${account_balance:.2f}")
            
            # Find matching minimum risk threshold
            min_risk_usd = None
            for range_str, risk_value in min_risk_config.items():
                try:
                    range_part = range_str.split('_')[0]
                    if '-' in range_part:
                        low, high = map(float, range_part.split('-'))
                        if low <= account_balance <= high:
                            min_risk_usd = float(risk_value)
                            print(f"  └─ 📊 Minimum risk required: ${min_risk_usd:.2f}")
                            break
                except (ValueError, IndexError):
                    continue
            
            # Skip if no matching threshold found
            if min_risk_usd is None:
                print(f"  └─ ⚠️ No minimum_balance_risk_distance configured for balance ${account_balance:.2f} - SKIPPING")
                stats["orders_skipped"] += 1
                continue
            
            print(f"  └─ 🎯 Target R:R: 1:{risk_reward}")
            
        except Exception as e:
            print(f"  └─  Failed to read config: {e}")
            stats["orders_error"] += 1
            continue
        
        # --- HELPER FUNCTION: GET VOLUME FROM SIGNAL ---
        def get_volume_from_signal(order_data):
            """Extract volume from signal data dynamically."""
            for key, value in order_data.items():
                if key.endswith('_volume'):
                    try:
                        return float(value)
                    except (ValueError, TypeError):
                        continue
            return None
        
        # --- HELPER FUNCTION: FIND TRADEABLE SYMBOL ---
        def find_tradeable_symbol(base_symbol):
            """Find tradeable symbol by checking MT5 symbols."""
            all_symbols = mt5.symbols_get()
            if not all_symbols:
                return base_symbol
            
            symbols_lower_map = {s.name.lower(): s.name for s in all_symbols}
            base_lower = base_symbol.lower()
            
            if base_lower in symbols_lower_map:
                return symbols_lower_map[base_lower]
            
            # Try common suffixes
            suffixes = ["", "+", ".m", "pro", ".pro", "c", ".c", "fx", ".fx", "e", ".e"]
            for suffix in suffixes:
                test_symbol = base_symbol + suffix
                test_lower = test_symbol.lower()
                if test_lower in symbols_lower_map:
                    return symbols_lower_map[test_lower]
            
            return base_symbol
        
        # --- HELPER FUNCTION: Calculate current risk using LIVE MT5 ---
        def calculate_current_risk_usd(symbol, volume, entry_price, stoploss_price, is_buy):
            """Calculate current risk in USD using MT5's order_calc_profit."""
            try:
                # Ensure symbol is selected
                if not mt5.symbol_select(symbol, True):
                    print(f"        Failed to select symbol: {symbol}")
                    return None
                
                # Get symbol info for validation
                symbol_info = mt5.symbol_info(symbol)
                if not symbol_info:
                    print(f"        Cannot get symbol info for: {symbol}")
                    return None
                
                # Validate stoploss distance is acceptable to broker
                point = symbol_info.point
                min_stop_distance = max(symbol_info.trade_stops_level, 10) * point
                
                if is_buy:
                    # For buy: SL must be below entry
                    if stoploss_price >= entry_price - min_stop_distance:
                        print(f"        SL {stoploss_price} too close to entry {entry_price} (min dist: {min_stop_distance})")
                        return None
                else:
                    # For sell: SL must be above entry
                    if stoploss_price <= entry_price + min_stop_distance:
                        print(f"        SL {stoploss_price} too close to entry {entry_price} (min dist: {min_stop_distance})")
                        return None
                
                order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
                risk_profit = mt5.order_calc_profit(order_type, symbol, volume, entry_price, stoploss_price)
                
                if risk_profit is None:
                    print(f"        MT5 order_calc_profit returned None")
                    return None
                
                return abs(risk_profit)
                
            except Exception as e:
                print(f"        Error calculating risk: {e}")
                return None
        
        # --- HELPER FUNCTION: Calculate required stoploss price ---
        def calculate_required_stoploss(symbol, volume, entry_price, min_risk_usd, is_buy, current_sl):
            """Calculate required stoploss price to achieve minimum risk."""
            try:
                if not mt5.symbol_select(symbol, True):
                    return None
                
                symbol_info = mt5.symbol_info(symbol)
                if not symbol_info:
                    return None
                
                digits = symbol_info.digits
                point = symbol_info.point
                # Get minimum stop distance in price units
                min_stop_distance_points = max(symbol_info.trade_stops_level, 10)
                min_stop_distance = min_stop_distance_points * point
                
                # Start with a safe distance that will definitely give us at least min_risk_usd
                # We'll increase distance until risk is achieved
                if is_buy:
                    # For buy: SL below entry - start with reasonable distance
                    # Start with current SL if it's valid, otherwise start wider
                    if current_sl and current_sl < entry_price:
                        test_distance = entry_price - current_sl
                    else:
                        test_distance = min_stop_distance * 10
                    
                    # Increase distance in steps until we achieve desired risk
                    max_attempts = 50
                    for attempt in range(max_attempts):
                        test_sl = entry_price - test_distance
                        
                        # Ensure minimum stop distance
                        if test_sl >= entry_price - min_stop_distance:
                            test_sl = entry_price - min_stop_distance - (point * 10)
                        
                        # Round to valid digits
                        test_sl = round(test_sl, digits)
                        
                        # Calculate risk with this SL
                        test_risk = calculate_current_risk_usd(symbol, volume, entry_price, test_sl, is_buy)
                        
                        if test_risk is None:
                            # If MT5 rejects this SL, increase distance
                            test_distance *= 1.5
                            continue
                        
                        # Check if risk meets or exceeds target
                        if test_risk >= min_risk_usd - 0.01:
                            # Found a valid SL
                            return test_sl
                        
                        # Risk too low, increase distance
                        test_distance *= 1.2
                    
                else:
                    # For sell: SL above entry
                    if current_sl and current_sl > entry_price:
                        test_distance = current_sl - entry_price
                    else:
                        test_distance = min_stop_distance * 10
                    
                    for attempt in range(max_attempts):
                        test_sl = entry_price + test_distance
                        
                        # Ensure minimum stop distance
                        if test_sl <= entry_price + min_stop_distance:
                            test_sl = entry_price + min_stop_distance + (point * 10)
                        
                        test_sl = round(test_sl, digits)
                        test_risk = calculate_current_risk_usd(symbol, volume, entry_price, test_sl, is_buy)
                        
                        if test_risk is None:
                            test_distance *= 1.5
                            continue
                        
                        if test_risk >= min_risk_usd - 0.01:
                            return test_sl
                        
                        test_distance *= 1.2
                
                print(f"        Could not find valid SL after {max_attempts} attempts")
                return None
                        
            except Exception as e:
                print(f"        Error calculating required stoploss: {e}")
                import traceback
                traceback.print_exc()
                return None
        
        # --- HELPER FUNCTION: Calculate new TP ---
        def calculate_new_tp(entry_price, sl_price, risk_reward, is_buy, symbol_info):
            """Calculate new TP price based on adjusted SL and risk-reward ratio."""
            if symbol_info is None:
                return None
            
            if is_buy:
                risk_distance = entry_price - sl_price
            else:
                risk_distance = sl_price - entry_price
            
            if risk_distance <= 0:
                return None
            
            profit_distance = risk_distance * risk_reward
            digits = symbol_info.digits
            
            if is_buy:
                new_tp = round(entry_price + profit_distance, digits)
            else:
                new_tp = round(entry_price - profit_distance, digits)
            
            return new_tp
        
        # --- FIND ALL LIMIT_ORDERS.JSON FILES ---
        signals_files = list(inv_root.rglob("limit_orders.json"))
        
        if not signals_files:
            print(f"  └─ ℹ️  No limit_orders.json files found")
            continue
        
        print(f"\n  └─ 📁 Found {len(signals_files)} limit_orders.json files")
        
        for signals_path in signals_files:
            strategy_name = signals_path.parent.name
            print(f"\n    📂 Strategy: {strategy_name}")
            
            try:
                with open(signals_path, 'r', encoding='utf-8') as f:
                    signals = json.load(f)
                
                if not signals:
                    print(f"       Empty file - skipping")
                    continue
                
                print(f"       Checking {len(signals)} signal(s)...")
                
                signals_modified_count = 0
                
                for idx, signal in enumerate(signals):
                    stats["orders_checked"] += 1
                    
                    # Only check LIMIT and STOP orders (not instant)
                    order_type = signal.get('order_type', '').lower()
                    if order_type in ['instant_buy', 'instant_sell']:
                        print(f"        ⏭️  Skipping instant order: {order_type}")
                        stats["orders_skipped"] += 1
                        continue
                    
                    # Get required fields
                    raw_symbol = signal.get('symbol', '')
                    entry_price = signal.get('entry', 0)
                    current_sl = signal.get('exit', 0)  # This is the stoploss
                    
                    if not entry_price or not current_sl:
                        print(f"        ⏭️  Skipping signal - missing entry ({entry_price}) or exit ({current_sl})")
                        stats["orders_skipped"] += 1
                        continue
                    
                    # Get volume
                    volume = get_volume_from_signal(signal)
                    if volume is None:
                        print(f"        ⏭️  Skipping signal - no volume field found")
                        stats["orders_skipped"] += 1
                        continue
                    
                    # Find tradeable symbol
                    tradeable_symbol = find_tradeable_symbol(raw_symbol)
                    
                    # Determine direction
                    is_buy = 'buy' in order_type
                    is_sell = 'sell' in order_type
                    
                    if not is_buy and not is_sell:
                        print(f"        ⏭️  Skipping signal - unknown direction: {order_type}")
                        stats["orders_skipped"] += 1
                        continue
                    
                    # Get symbol info for display
                    symbol_info = mt5.symbol_info(tradeable_symbol)
                    if not symbol_info:
                        print(f"        ⚠️ Cannot get symbol info for {tradeable_symbol}")
                        stats["orders_skipped"] += 1
                        continue
                    
                    digits = symbol_info.digits
                    
                    # Calculate current risk
                    current_risk_usd = calculate_current_risk_usd(
                        tradeable_symbol, 
                        volume, 
                        float(entry_price), 
                        float(current_sl), 
                        is_buy
                    )
                    
                    if current_risk_usd is None:
                        print(f"        ⚠️ Could not calculate risk for {raw_symbol} {order_type}")
                        stats["orders_skipped"] += 1
                        continue
                    
                    # Format numbers safely
                    entry_display = f"{entry_price:.{digits}f}" if digits > 0 else str(entry_price)
                    sl_display = f"{current_sl:.{digits}f}" if digits > 0 else str(current_sl)
                    
                    print(f"\n        📋 {order_type.upper()} {raw_symbol} @ {entry_display}")
                    print(f"           Current SL: {sl_display} | Risk: ${current_risk_usd:.2f}")
                    print(f"           Minimum required risk: ${min_risk_usd:.2f}")
                    
                    # Check if current risk meets minimum
                    if current_risk_usd >= min_risk_usd - 0.01:
                        print(f"           ✅ Risk meets minimum requirement")
                        stats["orders_skipped"] += 1
                        continue
                    
                    # Risk is insufficient
                    stats["insufficient_risk_found"] += 1
                    print(f"           ⚠️ INSUFFICIENT RISK: Need to adjust stoploss")
                    
                    # Calculate required stoploss
                    new_sl = calculate_required_stoploss(
                        tradeable_symbol,
                        volume,
                        float(entry_price),
                        min_risk_usd,
                        is_buy,
                        float(current_sl)
                    )
                    
                    if new_sl is None:
                        print(f"           Cannot calculate required stoploss. Skipping.")
                        stats["orders_skipped"] += 1
                        continue
                    
                    # Calculate new TP based on new SL
                    new_tp = calculate_new_tp(
                        float(entry_price),
                        new_sl,
                        risk_reward,
                        is_buy,
                        symbol_info
                    )
                    
                    if new_tp is None:
                        print(f"           Cannot calculate TP. Skipping.")
                        stats["orders_skipped"] += 1
                        continue
                    
                    # Verify new risk
                    new_risk_usd = calculate_current_risk_usd(
                        tradeable_symbol,
                        volume,
                        float(entry_price),
                        new_sl,
                        is_buy
                    )
                    
                    if new_risk_usd is None:
                        print(f"           ⚠️ Warning: Could not verify new risk, but proceeding with calculated SL")
                        # Still proceed even if verification fails, as we already validated the SL calculation
                    else:
                        # Format new values safely
                        new_sl_display = f"{new_sl:.{digits}f}" if digits > 0 else str(new_sl)
                        new_tp_display = f"{new_tp:.{digits}f}" if digits > 0 else str(new_tp)
                        
                        print(f"           📐 New SL: {new_sl_display} (New risk: ${new_risk_usd:.2f})")
                        print(f"           📍 New TP: {new_tp_display}")
                    
                    # Update the signal
                    signal['exit'] = new_sl
                    signal['target'] = new_tp
                    signals_modified_count += 1
                    stats["orders_adjusted"] += 1
                    stats["minimum_risk_used"] += 1
                    
                # Save modified signals back to file if any were modified
                if signals_modified_count > 0:
                    with open(signals_path, 'w', encoding='utf-8') as f:
                        json.dump(signals, f, indent=4)
                    
                    print(f"\n       📊 Summary for {strategy_name}:")
                    print(f"          • Total signals checked: {len(signals)}")
                    print(f"          • Signals adjusted: {signals_modified_count}")
                    print(f"          • Signals unchanged: {len(signals) - signals_modified_count}")
                else:
                    print(f"\n       ✅ No signals needed adjustment")
                    
            except json.JSONDecodeError as e:
                print(f"       Invalid JSON in {signals_path}: {e}")
                stats["orders_error"] += 1
                continue
            except Exception as e:
                print(f"       Error processing {signals_path}: {e}")
                import traceback
                traceback.print_exc()
                stats["orders_error"] += 1
                continue
    
    # --- FINAL SUMMARY ---
    print(f"\n{'='*10} 📊 STOPLOSS CORRECTION SUMMARY {'='*10}")
    print(f"   Investor ID: {stats['investor_id']}")
    print(f"   Signals checked: {stats['orders_checked']}")
    print(f"   Signals adjusted: {stats['orders_adjusted']}")
    print(f"   Signals skipped: {stats['orders_skipped']}")
    print(f"   Errors: {stats['orders_error']}")
    
    if stats["insufficient_risk_found"] > 0:
        print(f"\n   ⚠️  Insufficient risk signals found: {stats['insufficient_risk_found']}")
        print(f"   ✅ Corrected to minimum risk: {stats['minimum_risk_used']}")
    
    if stats["orders_checked"] > 0:
        success_rate = (stats['orders_adjusted'] / stats['orders_checked']) * 100
        print(f"\n   Adjustment rate: {success_rate:.1f}%")
    
    print(f"\n{'='*10} 🏁 STOPLOSS CORRECTION COMPLETE {'='*10}\n")
    
    stats["processing_success"] = True
    return stats

def maximum_risk_distance(inv_id=None):
    """
    Checks all limit orders for maximum risk distance requirements.
    Removes signals where the calculated risk in USD is:
    - GREATER than maximum_risk_distance threshold
    
    NO FALLBACKS - only uses exact values from:
    - maximum_risk_distance
    
    If the threshold is missing or not configured for the current balance,
    the check is SKIPPED entirely for that investor.
    """
    
    # --- SUB-FUNCTION: LOAD MAXIMUM RISK DISTANCE THRESHOLD (NO FALLBACKS) ---
    def load_maximum_risk_distance_threshold(investor_root, account_balance):
        """
        Load maximum risk distance threshold from accountmanagement.json.
        NO FALLBACKS - only uses exactly what's specified.
        
        Returns:
            float: max_risk_usd, or None if not found or error
        """
        acc_mgmt_path = investor_root / "accountmanagement.json"
        
        if not acc_mgmt_path.exists():
            print(f"    ℹ️  No accountmanagement.json found - maximum risk distance check SKIPPED")
            return None
        
        try:
            with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # ONLY get the specified maximum risk distance setting
            max_risk_config = config.get("maximum_balance_risk_distance", {})
            
            max_risk_usd = None
            
            # Find matching range for maximum risk distance (EXACT, NO FALLBACK)
            for range_str, risk_value in max_risk_config.items():
                try:
                    # Parse range like "1-10000000.99_risk"
                    range_part = range_str.split('_')[0]
                    if '-' in range_part:
                        low, high = map(float, range_part.split('-'))
                        if low <= account_balance <= high:
                            max_risk_usd = float(risk_value)
                            print(f"        📊 Maximum risk distance: ${max_risk_usd:.2f} (balance: ${account_balance:.2f})")
                            break
                except (ValueError, IndexError):
                    continue
            
            # If threshold is missing, skip entirely (NO FALLBACKS)
            if max_risk_usd is None:
                print(f"        ⚠️ No maximum_risk_distance configured for balance ${account_balance:.2f} - SKIPPING check")
            
            return max_risk_usd
            
        except Exception as e:
            print(f"     Error reading maximum risk distance threshold: {e}")
            return None
    
    # --- SUB-FUNCTION: CALCULATE ORDER RISK IN USD ---
    def calculate_order_risk_usd(symbol, entry_price, stoploss_price, volume, is_buy):
        """
        Calculate the risk in USD for a limit/stop order.
        Returns risk amount in USD, or None if calculation fails.
        """
        if stoploss_price == 0 or stoploss_price is None:
            return None
        
        try:
            # Ensure symbol is selected
            if not mt5.symbol_select(symbol, True):
                return None
            
            # Get symbol info for precision
            symbol_info = mt5.symbol_info(symbol)
            if not symbol_info:
                return None
            
            # Calculate profit/loss between entry and stoploss
            if is_buy:
                # For BUY orders: risk = entry - stoploss (if stoploss is below entry)
                if entry_price <= stoploss_price:
                    return None  # No risk (stoploss above entry for buy)
                calc_type = mt5.ORDER_TYPE_BUY
                risk_profit = mt5.order_calc_profit(calc_type, symbol, volume, entry_price, stoploss_price)
            else:
                # For SELL orders: risk = stoploss - entry (if stoploss is above entry)
                if entry_price >= stoploss_price:
                    return None  # No risk (stoploss below entry for sell)
                calc_type = mt5.ORDER_TYPE_SELL
                risk_profit = mt5.order_calc_profit(calc_type, symbol, volume, entry_price, stoploss_price)
            
            return abs(risk_profit) if risk_profit else None
            
        except Exception as e:
            print(f"        Error calculating risk: {e}")
            return None
    
    # --- SUB-FUNCTION: GET VOLUME FROM SIGNAL ---
    def get_volume_from_signal(order_data):
        """Extract volume from signal data dynamically."""
        for key, value in order_data.items():
            if key.endswith('_volume'):
                try:
                    return float(value)
                except (ValueError, TypeError):
                    continue
        return None
    
    # --- SUB-FUNCTION: REMOVE SIGNAL FROM LIMIT_ORDERS.JSON ---
    def remove_signal_from_limit_orders(limit_orders_path, signal_to_remove):
        """Remove a specific signal from limit_orders.json file."""
        try:
            if not limit_orders_path.exists():
                return False
            
            with open(limit_orders_path, 'r', encoding='utf-8') as f:
                signals = json.load(f)
            
            original_count = len(signals)
            
            # Find and remove the matching signal
            filtered_signals = []
            for signal in signals:
                # Match by symbol, order_type, entry, and current_candle_time
                if (signal.get('symbol') == signal_to_remove.get('symbol') and
                    signal.get('order_type') == signal_to_remove.get('order_type') and
                    signal.get('entry') == signal_to_remove.get('entry') and
                    signal.get('current_candle_time') == signal_to_remove.get('current_candle_time')):
                    print(f"        🗑️ Removing signal due to maximum risk distance violation")
                    continue
                filtered_signals.append(signal)
            
            if len(filtered_signals) < original_count:
                with open(limit_orders_path, 'w', encoding='utf-8') as f:
                    json.dump(filtered_signals, f, indent=4)
                print(f"        ✅ Removed {original_count - len(filtered_signals)} signal(s) from {limit_orders_path.name}")
                return True
            else:
                return False
                
        except Exception as e:
            print(f"        Error removing signal from limit_orders.json: {e}")
            return False
    
    # --- SUB-FUNCTION: FIND TRADEABLE SYMBOL ---
    def find_tradeable_symbol(base_symbol):
        """Find tradeable symbol by checking MT5 symbols."""
        all_symbols = mt5.symbols_get()
        if not all_symbols:
            return base_symbol
        
        symbols_lower_map = {s.name.lower(): s.name for s in all_symbols}
        base_lower = base_symbol.lower()
        
        if base_lower in symbols_lower_map:
            return symbols_lower_map[base_lower]
        
        # Try common suffixes
        suffixes = ["", "+", ".m", "pro", ".pro", "c", ".c", "fx", ".fx", "e", ".e"]
        for suffix in suffixes:
            test_symbol = base_symbol + suffix
            test_lower = test_symbol.lower()
            if test_lower in symbols_lower_map:
                return symbols_lower_map[test_lower]
        
        return base_symbol
    
    # --- MAIN EXECUTION ---
    print("\n" + "="*80)
    print("🔍 MAXIMUM RISK DISTANCE CHECKER (NO FALLBACKS)")
    print("="*80)
    
    investor_ids = [inv_id] if inv_id else list(usersdictionary.keys())
    total_removed = 0
    total_checked = 0
    total_skipped = 0
    
    for user_brokerid in investor_ids:
        print(f"\n{'='*60}")
        print(f"📋 INVESTOR: {user_brokerid}")
        print(f"{'='*60}")
        
        investor_root = Path(INV_PATH) / user_brokerid
        
        if not investor_root.exists():
            print(f"   Investor root not found: {investor_root}")
            continue
        
        # Get account balance for threshold determination
        account_info = mt5.account_info()
        if not account_info:
            print(f"  Cannot get account info for {user_brokerid}")
            continue
        
        account_balance = account_info.balance
        print(f"  💰 Account Balance: ${account_balance:.2f}")
        
        # Load maximum risk distance threshold (NO FALLBACKS)
        max_risk_usd = load_maximum_risk_distance_threshold(
            investor_root, account_balance
        )
        
        # Skip if threshold is missing (NO FALLBACKS)
        if max_risk_usd is None:
            print(f"  ⚠️ MISSING REQUIRED CONFIGURATION - SKIPPING investor {user_brokerid}")
            print(f"     maximum_risk_distance must be configured for balance ${account_balance:.2f}")
            total_skipped += 1
            continue
        
        print(f"\n  🎯 Maximum Risk Distance Rule (EXACT MATCH ONLY, NO FALLBACKS):")
        print(f"     • Maximum risk allowed: ${max_risk_usd:.2f}")
        print(f"     • Orders with risk > ${max_risk_usd:.2f} will be REMOVED")
        
        # Find all limit_orders.json files
        signals_files = list(investor_root.rglob("limit_orders.json"))
        
        if not signals_files:
            print(f"  ℹ️  No limit_orders.json files found")
            continue
        
        print(f"\n  📁 Found {len(signals_files)} limit_orders.json files")
        
        for signals_path in signals_files:
            strategy_name = signals_path.parent.name
            print(f"\n    📂 Strategy: {strategy_name}")
            
            try:
                with open(signals_path, 'r', encoding='utf-8') as f:
                    signals = json.load(f)
                
                if not signals:
                    print(f"       Empty file - skipping")
                    continue
                
                print(f"       Checking {len(signals)} signal(s)...")
                
                signals_to_remove = []
                
                for signal in signals:
                    total_checked += 1
                    
                    # Only check LIMIT and STOP orders (not instant)
                    order_type = signal.get('order_type', '').lower()
                    if order_type in ['instant_buy', 'instant_sell']:
                        print(f"        ⏭️  Skipping instant order - not applicable for maximum risk distance check")
                        continue
                    
                    # Get required fields
                    raw_symbol = signal.get('symbol', '')
                    entry_price = signal.get('entry', 0)
                    exit_price = signal.get('exit', 0)  # This is the stoploss
                    
                    if not entry_price or not exit_price:
                        print(f"        ⏭️  Skipping signal - missing entry or exit price")
                        continue
                    
                    # Get volume
                    volume = get_volume_from_signal(signal)
                    if volume is None:
                        print(f"        ⏭️  Skipping signal - no volume field found")
                        continue
                    
                    # Find tradeable symbol
                    tradeable_symbol = find_tradeable_symbol(raw_symbol)
                    
                    # Determine direction
                    is_buy = 'buy' in order_type
                    is_sell = 'sell' in order_type
                    
                    if not is_buy and not is_sell:
                        print(f"        ⏭️  Skipping signal - unknown direction: {order_type}")
                        continue
                    
                    # Calculate risk in USD
                    risk_usd = calculate_order_risk_usd(
                        tradeable_symbol, 
                        float(entry_price), 
                        float(exit_price), 
                        volume, 
                        is_buy
                    )
                    
                    if risk_usd is None:
                        print(f"        ⚠️ Could not calculate risk for {raw_symbol} {order_type}")
                        continue
                    
                    # Check against maximum threshold (REMOVE if risk EXCEEDS maximum)
                    if risk_usd > max_risk_usd:
                        print(f"        REMOVING: {order_type.upper()} {raw_symbol} @ {entry_price}")
                        print(f"           RISK TOO HIGH: ${risk_usd:.2f} > maximum ${max_risk_usd:.2f}")
                        signals_to_remove.append(signal)
                    else:
                        print(f"        ✅ KEEPING: {order_type.upper()} {raw_symbol} @ {entry_price} (risk: ${risk_usd:.2f} ≤ ${max_risk_usd:.2f})")
                
                # Remove violating signals
                if signals_to_remove:
                    original_count = len(signals)
                    for signal in signals_to_remove:
                        remove_signal_from_limit_orders(signals_path, signal)
                    
                    # Reload and save updated signals
                    with open(signals_path, 'r', encoding='utf-8') as f:
                        updated_signals = json.load(f)
                    
                    # Filter out removed signals
                    final_signals = [s for s in updated_signals if s not in signals_to_remove]
                    
                    with open(signals_path, 'w', encoding='utf-8') as f:
                        json.dump(final_signals, f, indent=4)
                    
                    removed_count = len(signals_to_remove)
                    total_removed += removed_count
                    print(f"\n       📊 Summary for {strategy_name}:")
                    print(f"          • Total signals checked: {len(signals)}")
                    print(f"          • Signals removed (exceeded max risk): {removed_count}")
                    print(f"          • Signals kept: {len(final_signals)}")
                else:
                    print(f"\n       ✅ No signals exceeded maximum risk distance")
                    
            except json.JSONDecodeError as e:
                print(f"       Invalid JSON in {signals_path}: {e}")
                continue
            except Exception as e:
                print(f"       Error processing {signals_path}: {e}")
                continue
    
    # Final summary
    print("\n" + "="*80)
    print("  📊 MAXIMUM RISK DISTANCE CHECK SUMMARY (NO FALLBACKS)".ljust(79) + "=")
    print("="*80)
    print(f"│  Investors processed:        {len(investor_ids) - total_skipped}")
    print(f"│  Investors skipped:          {total_skipped}")
    print(f"│  Total signals checked:      {total_checked}")
    print(f"│  Total signals removed:      {total_removed}")
    print("="*80)
    
    if total_removed > 0:
        print(f"✅ Removed {total_removed} signal(s) that exceeded maximum risk distance")
    else:
        print("✅ No signals exceeded maximum risk distance")
    print("="*80 + "\n")
    
    return total_removed

def live_usd_risk_and_scaling(inv_id=None, callback_function=None):
    """
    Calculates and populates the live USD risk for all orders in pending_orders/limit_orders.json files.
    Uses SMART RISK SCALING with target and maximum thresholds:
    - Scales volume UP if risk < target_risk
    - Scales volume DOWN if risk > max_risk
    - Rejects orders that cannot fit within max_risk constraints
    - Splits orders ONLY when volume exceeds broker max volume limits
    
    USES MT5 order_calc_profit FOR ALL RISK CALCULATIONS - EXACT MATCH with check_pending_orders_risk.
    Steps through broker-allowed volume increments only.
    """
    print(f"\n{'='*10} 💰 CALCULATING LIVE USD RISK WITH SMART SCALING {'='*10}")
    
    total_files_updated = 0
    total_orders_updated = 0
    total_risk_usd = 0.0
    total_signals_created = 0
    total_signals_rejected = 0
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

    # --- RISK SAFETY CHECK SUB-FUNCTION USING MT5 order_calc_profit ---
    def verify_risk_via_mt5(symbol, order_type_str, entry_price, exit_price, volume):
        """
        Verifies the actual USD risk using MT5's order_calc_profit.
        This is the EXACT same calculation used by check_pending_orders_risk.
        
        Args:
            symbol: Normalized symbol name
            order_type_str: 'BUY' or 'SELL' string  
            entry_price: Order entry/trigger price
            exit_price: Stop loss price
            volume: Order volume to check
            
        Returns:
            float: Absolute USD risk value, or None if calculation fails
        """
        try:
            # Determine the correct MT5 order type
            order_type_upper = order_type_str.upper()
            
            if "BUY" in order_type_upper:
                if "STOP" in order_type_upper:
                    calc_type = mt5.ORDER_TYPE_BUY_STOP
                elif "LIMIT" in order_type_upper:
                    calc_type = mt5.ORDER_TYPE_BUY_LIMIT
                else:
                    calc_type = mt5.ORDER_TYPE_BUY
            else:
                if "STOP" in order_type_upper:
                    calc_type = mt5.ORDER_TYPE_SELL_STOP
                elif "LIMIT" in order_type_upper:
                    calc_type = mt5.ORDER_TYPE_SELL_LIMIT
                else:
                    calc_type = mt5.ORDER_TYPE_SELL
            
            # Use order_calc_profit to get the EXACT profit/loss at SL
            profit = mt5.order_calc_profit(calc_type, symbol, volume, entry_price, exit_price)
            
            if profit is not None:
                return abs(profit)
            else:
                # Fallback: try with simpler direction-only types
                if "BUY" in order_type_upper:
                    profit = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, symbol, volume, entry_price, exit_price)
                else:
                    profit = mt5.order_calc_profit(mt5.ORDER_TYPE_SELL, symbol, volume, entry_price, exit_price)
                
                if profit is not None:
                    return abs(profit)
                    
            return None
                    
        except Exception as e:
            print(f"          MT5 risk verification error: {e}")
            return None

    # --- CHECK IF VOLUME IS VALID FOR THE BROKER ---
    def is_valid_broker_volume(symbol_info, volume):
        """
        Checks if a volume is valid according to broker constraints.
        Returns the nearest valid volume or None if impossible.
        """
        volume_step = symbol_info.volume_step
        min_volume = symbol_info.volume_min
        max_volume = symbol_info.volume_max
        
        # Check bounds
        if volume < min_volume - 0.000001:
            return None
        if volume > max_volume + 0.000001:
            return None
        
        # Round to nearest valid step
        steps = round(volume / volume_step) if volume_step > 0 else 0
        valid_volume = round(steps * volume_step, 8)
        
        # Ensure it's at least min_volume
        valid_volume = max(valid_volume, min_volume)
        
        # Ensure it's at most max_volume
        valid_volume = min(valid_volume, max_volume)
        
        return valid_volume

    for inv_folder in investor_folders:
        current_inv_id = inv_folder.name
        print(f"\n [{current_inv_id}] 🔍 Initializing smart risk scaling...")

        # Cache stores: { lower_case_raw_symbol: corrected_mt5_symbol }
        resolution_cache = {}
        
        # Build MT5 symbol map ONCE for this investor (case-insensitive lookup)
        mt5_symbol_map = {}
        try:
            all_symbols = mt5.symbols_get()
            if all_symbols:
                mt5_symbol_map = {s.name.lower(): s.name for s in all_symbols}
                print(f"  └─ 📋 Loaded {len(mt5_symbol_map)} MT5 symbols for case correction")
        except Exception as e:
            print(f"  └─  Could not load MT5 symbols: {e}")

        # 1. Load account management data with BOTH risk configurations
        account_mgmt_path = inv_folder / "accountmanagement.json"
        default_risk_map = {}
        maximum_risk_map = {}
        account_balance = None
        
        if account_mgmt_path.exists():
            try:
                with open(account_mgmt_path, 'r', encoding='utf-8') as f:
                    account_data = json.load(f)
                default_risk_map = account_data.get('account_balance_default_risk_management', {})
                maximum_risk_map = account_data.get('account_balance_maximum_risk_management', {})
                print(f"  └─ 📊 Loaded risk configurations:")
                print(f"      • Default (target) ranges: {len(default_risk_map)}")
                print(f"      • Maximum (hard cap) ranges: {len(maximum_risk_map)}")
            except Exception as e:
                print(f"  └─  Could not load accountmanagement.json: {e}")
                continue
        else:
            print(f"  └─  No accountmanagement.json found, skipping risk-based scaling")
            continue

        broker_cfg = usersdictionary.get(current_inv_id)
        if not broker_cfg:
            print(f"  └─  No broker config found for {current_inv_id}")
            continue
        
        account_info = mt5.account_info()
        if account_info:
            account_balance = account_info.balance
            print(f"  └─ 💵 Live account balance: ${account_balance:,.2f}")
        else:
            print(f"  └─  Could not fetch account balance from broker")
            continue
        
        # --- DETERMINE DEFAULT RISK (TARGET) ---
        target_risk = None
        if default_risk_map:
            for range_str, risk_value in default_risk_map.items():
                try:
                    range_part = range_str.split('_')[0] if '_' in range_str else range_str
                    if '-' in range_part:
                        min_val, max_val = map(float, range_part.split('-'))
                        if min_val <= account_balance <= max_val:
                            target_risk = float(risk_value)
                            print(f"  └─ 🎯 Target risk range: ${min_val:,.2f} - ${max_val:,.2f}")
                            print(f"  └─ 🎯 Target risk: ${target_risk:.2f}")
                            break
                except Exception as e:
                    continue
        
        # --- DETERMINE MAXIMUM RISK (HARD CAP) ---
        max_risk = None
        if maximum_risk_map:
            for range_str, risk_value in maximum_risk_map.items():
                try:
                    range_part = range_str.split('_')[0] if '_' in range_str else range_str
                    if '-' in range_part:
                        min_val, max_val = map(float, range_part.split('-'))
                        if min_val <= account_balance <= max_val:
                            max_risk = float(risk_value)
                            print(f"  └─ 🔒 Maximum risk (hard cap): ${max_risk:.2f}")
                            break
                except Exception as e:
                    continue
        
        # --- APPLY FALLBACK LOGIC (same as check_pending_orders_risk) ---
        if target_risk is None and max_risk is None:
            print(f"  └─  No risk configuration found for balance ${account_balance:,.2f}. Skipping.")
            continue
        elif target_risk is None:
            target_risk = max_risk
            print(f"  └─  Target risk missing. Using maximum (${max_risk:.2f}) as both target and cap.")
        elif max_risk is None:
            max_risk = target_risk
            print(f"  └─  Maximum risk missing. Using target (${target_risk:.2f}) as both target and cap.")
        
        # Ensure max_risk >= target_risk
        if max_risk < target_risk:
            print(f"  └─  Max risk (${max_risk:.2f}) < target (${target_risk:.2f}). Adjusting max to target.")
            max_risk = target_risk
        
        print(f"\n  └─ 💰 SMART RISK CONFIGURATION:")
        print(f"      • Target Risk: ${target_risk:.2f}")
        print(f"      • Maximum Risk (hard cap): ${max_risk:.2f}")
        print(f"      • Acceptable range: ${target_risk:.2f} - ${max_risk:.2f}")
        
        order_files = list(inv_folder.rglob("*/pending_orders/limit_orders.json"))
        
        if not order_files:
            print(f"  └─ 🔘 No limit order files found")
            continue
            
        investor_files_updated = 0
        investor_orders_updated = 0
        investor_risk_usd = 0.0
        investor_signals_count = 0
        investor_signals_rejected = 0
        
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

                # Clear limit_orders.json for this specific folder
                signals_path = file_path.parent / "limit_orders.json"
                if signals_path.exists():
                    with open(signals_path, 'w', encoding='utf-8') as f:
                        json.dump([], f)
                    print(f"    └─ 🚿 Cleared existing limit_orders.json for fresh split generation")

                # --- START PROCESSING ---
                if callback_function:
                    try:
                        callback_function(current_inv_id, file_path, orders)
                    except Exception as e:
                        print(f"    └─  Callback error: {e}")
                
                orders_modified = False
                file_risk_total = 0.0
                file_signals = []
                file_rejected = 0
                
                # Track which orders to keep (for removing rejected ones)
                kept_orders = []
                
                for order in orders:
                    raw_symbol = order.get("symbol", "")
                    if not raw_symbol:
                        continue
                    
                    # --- SYMBOL NORMALIZATION WITH CASE CORRECTION ---
                    cache_key = raw_symbol.lower()
                    if cache_key in resolution_cache:
                        normalized_symbol = resolution_cache[cache_key]
                    else:
                        # Step 1: Get initial normalized symbol
                        normalized_symbol = get_normalized_symbol(raw_symbol)
                        
                        # Step 2: CASE CORRECTION - Check against MT5 symbols
                        if mt5_symbol_map and normalized_symbol:
                            normalized_lower = normalized_symbol.lower()
                            if normalized_lower in mt5_symbol_map:
                                correct_symbol = mt5_symbol_map[normalized_lower]
                                if correct_symbol != normalized_symbol:
                                    print(f"    └─ 🔧 Case correction: '{normalized_symbol}' → '{correct_symbol}'")
                                    normalized_symbol = correct_symbol
                        
                        # Store in cache with lowercase key
                        resolution_cache[cache_key] = normalized_symbol
                        
                        if normalized_symbol and normalized_symbol != raw_symbol:
                            print(f"    └─ ✅ {raw_symbol} -> {normalized_symbol} (Mapped & Cached)")
                            total_symbols_normalized += 1
                    
                    symbol = normalized_symbol if normalized_symbol else raw_symbol
                    
                    # Get MT5 symbol info
                    symbol_info = mt5.symbol_info(symbol)
                    if not symbol_info:
                        # Try case-insensitive lookup as fallback
                        if mt5_symbol_map:
                            symbol_lower = symbol.lower()
                            if symbol_lower in mt5_symbol_map:
                                correct_symbol = mt5_symbol_map[symbol_lower]
                                print(f"    └─ 🔧 Fallback case correction: '{symbol}' → '{correct_symbol}'")
                                symbol = correct_symbol
                                symbol_info = mt5.symbol_info(symbol)
                        
                        if not symbol_info:
                            print(f"    └─  Could not fetch symbol info for {symbol}, skipping")
                            continue
                    
                    # Get broker volume constraints
                    volume_step = symbol_info.volume_step
                    min_volume = symbol_info.volume_min
                    max_volume = symbol_info.volume_max
                    
                    entry_price = order.get("entry")
                    exit_price = order.get("exit")
                    
                    if not entry_price or not exit_price:
                        print(f"    └─  Missing entry/exit for {symbol}, skipping")
                        continue
                    
                    # Determine order direction
                    order_type = str(order.get('order_type', '')).upper()
                    is_buy = "BUY" in order_type
                    
                    # Stop distance in price
                    stop_distance = abs(entry_price - exit_price)
                    
                    print(f"\n    └─ 📈 {symbol}: Calculating optimal volume...")
                    print(f"       Order type: {'BUY' if is_buy else 'SELL'}")
                    print(f"       Entry: {entry_price}, Exit/SL: {exit_price}")
                    print(f"       Stop distance: {stop_distance:.6f}")
                    print(f"       Broker volume limits: Min={min_volume}, Max={max_volume}, Step={volume_step}")
                    
                    # ============================================
                    # PHASE 1: INITIAL SAFETY CHECK AT MINIMUM VOLUME
                    # Use MT5's order_calc_profit for accurate risk
                    # ============================================
                    print(f"\n       🔍 PHASE 1: INITIAL SAFETY CHECK AT MINIMUM VOLUME")
                    
                    # Start at minimum allowed volume
                    current_volume = min_volume
                    
                    # Verify this volume is valid for broker
                    valid_volume = is_valid_broker_volume(symbol_info, current_volume)
                    if valid_volume is None:
                        print(f"       REJECTED: Minimum volume {min_volume} is not valid for broker")
                        file_rejected += 1
                        investor_signals_rejected += 1
                        total_signals_rejected += 1
                        continue
                    
                    current_volume = valid_volume
                    
                    # Get MT5 risk at minimum volume
                    mt5_risk = verify_risk_via_mt5(symbol, order_type, entry_price, exit_price, current_volume)
                    
                    if mt5_risk is None:
                        print(f"       REJECTED: MT5 could not calculate risk for {symbol}")
                        file_rejected += 1
                        investor_signals_rejected += 1
                        total_signals_rejected += 1
                        continue
                    
                    current_risk = mt5_risk
                    print(f"       MT5 Risk at min vol ({current_volume}): ${current_risk:.2f}")
                    
                    # Check if minimum volume already exceeds max_risk
                    if current_risk > max_risk:
                        print(f"       REJECTED: Minimum risk ${current_risk:.2f} exceeds hard cap ${max_risk:.2f}")
                        print(f"       🗑️  Order cannot fit within risk constraints at any volume")
                        file_rejected += 1
                        investor_signals_rejected += 1
                        total_signals_rejected += 1
                        continue
                    
                    # ============================================
                    # PHASE 2: SMART SCALING USING BROKER-ALLOWED STEPS
                    # Walk through each valid volume step and check with MT5
                    # ============================================
                    print(f"\n       🎯 PHASE 2: SMART SCALING WITH BROKER VOLUME STEPS")
                    
                    optimal_volume = current_volume
                    optimal_risk = current_risk
                    
                    # Check if we're already at or above target
                    if current_risk >= target_risk:
                        print(f"       ✅ Risk already in target range: ${current_risk:.2f} >= ${target_risk:.2f}")
                    else:
                        print(f"       ⬆️  Need to scale UP: ${current_risk:.2f} < ${target_risk:.2f}")
                        print(f"       Walking through broker volume steps...")
                        
                        # Track if we found a valid volume that meets target
                        found_target = False
                        last_valid_volume = current_volume
                        last_valid_risk = current_risk
                        
                        # Walk through each volume step
                        test_volume = current_volume
                        while test_volume < max_volume:
                            # Calculate next broker-allowed volume
                            next_volume = round(test_volume + volume_step, 8)
                            
                            # Validate with broker
                            valid_next = is_valid_broker_volume(symbol_info, next_volume)
                            if valid_next is None or valid_next <= test_volume:
                                # This step isn't valid, try next
                                test_volume = next_volume
                                continue
                            
                            test_volume = valid_next
                            
                            # Verify risk with MT5 at this volume
                            test_risk = verify_risk_via_mt5(symbol, order_type, entry_price, exit_price, test_volume)
                            
                            if test_risk is None:
                                print(f"        MT5 failed at volume {test_volume}, trying next step")
                                continue
                            
                            print(f"       🔍 Step: vol={test_volume:.3f}, risk=${test_risk:.2f}")
                            
                            # Check if this volume exceeds max_risk
                            if test_risk > max_risk:
                                print(f"        Volume {test_volume:.3f} exceeds max risk: ${test_risk:.2f} > ${max_risk:.2f}")
                                print(f"       Using previous valid volume: {last_valid_volume:.3f} (risk: ${last_valid_risk:.2f})")
                                break
                            
                            # This volume is valid - update our best option
                            last_valid_volume = test_volume
                            last_valid_risk = test_risk
                            
                            # Check if we've reached target
                            if test_risk >= target_risk:
                                optimal_volume = test_volume
                                optimal_risk = test_risk
                                found_target = True
                                print(f"       ✅ REACHED TARGET at volume {optimal_volume:.3f}: risk ${optimal_risk:.2f} >= ${target_risk:.2f}")
                                break
                        
                        if not found_target:
                            # Use the best volume we found (last valid before hitting max risk or max volume)
                            optimal_volume = last_valid_volume
                            optimal_risk = last_valid_risk
                            
                            if optimal_volume >= max_volume - 0.000001:
                                print(f"        Reached broker max volume ({max_volume}) without hitting target")
                                print(f"       Best available: volume {optimal_volume:.3f}, risk ${optimal_risk:.2f} (below target ${target_risk:.2f})")
                            elif optimal_risk < max_risk:
                                print(f"        Could not reach target before hitting max risk")
                                print(f"       Best available: volume {optimal_volume:.3f}, risk ${optimal_risk:.2f} (below target ${target_risk:.2f})")
                    
                    # ============================================
                    # PHASE 3: FINAL CONFIRMATION CHECK
                    # Re-verify the final volume with MT5
                    # ============================================
                    print(f"\n       ✅ PHASE 3: FINAL CONFIRMATION CHECK")
                    
                    final_risk = verify_risk_via_mt5(symbol, order_type, entry_price, exit_price, optimal_volume)
                    
                    if final_risk is None:
                        print(f"       REJECTED: MT5 failed to verify final volume {optimal_volume}")
                        file_rejected += 1
                        investor_signals_rejected += 1
                        total_signals_rejected += 1
                        continue
                    
                    print(f"       Final MT5 Risk: ${final_risk:.2f} at volume {optimal_volume:.3f}")
                    
                    # Verify it's still within max_risk
                    if final_risk > max_risk:
                        print(f"       FINAL REJECTION: Risk ${final_risk:.2f} exceeds cap ${max_risk:.2f}")
                        file_rejected += 1
                        investor_signals_rejected += 1
                        total_signals_rejected += 1
                        continue
                    
                    # Check if final risk is at least target_risk
                    if final_risk >= target_risk:
                        print(f"       ✅ Risk meets target: ${final_risk:.2f} >= ${target_risk:.2f}")
                    else:
                        print(f"        Risk below target but acceptable: ${final_risk:.2f} < ${target_risk:.2f}")
                    
                    # ============================================
                    # UPDATE ORDER WITH CORRECT VOLUME AND RISK
                    # ============================================
                    
                    # IMPORTANT: Use the SCALED optimal_volume, not the original min_volume
                    order['symbol'] = symbol  # Update symbol with correct case
                    order[f"{broker_prefix}_volume"] = round(optimal_volume, 3)  # More precision for small volumes
                    order[f"{broker_prefix}_tick_size"] = symbol_info.trade_tick_size
                    order[f"{broker_prefix}_tick_value"] = symbol_info.trade_tick_value
                    order["risk_in_usd"] = round(final_risk, 2)
                    order["risk_calculated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    order["target_risk"] = round(target_risk, 2)
                    order["max_risk_allowed"] = round(max_risk, 2)
                    order["account_balance_at_calc"] = round(account_balance, 2)
                    order["current_bid"] = round(symbol_info.bid, 6) if hasattr(symbol_info, 'bid') else None
                    order["current_ask"] = round(symbol_info.ask, 6) if hasattr(symbol_info, 'ask') else None
                    order["stop_distance_pips"] = round(stop_distance, 6)
                    order["order_is_buy"] = is_buy
                    order["risk_verified_by_mt5"] = True
                    order["volume_step_used"] = volume_step
                    order["scaled_volume"] = round(optimal_volume, 3)  # Track the actual scaled volume
                    order["scaled_risk"] = round(final_risk, 2)  # Track the actual scaled risk
                    
                    # Keep this order (it passed all checks)
                    kept_orders.append(order)
                    
                    orders_modified = True
                    investor_orders_updated += 1
                    total_orders_updated += 1
                    file_risk_total += final_risk
                    
                    # ============================================
                    # SPLITTING LOGIC - ONLY if volume exceeds broker max
                    # ============================================
                    need_split = optimal_volume > max_volume
                    
                    if need_split:
                        print(f"\n       🟢 SPLITTING REQUIRED: Optimal volume {optimal_volume:.3f} exceeds broker max {max_volume}")
                        
                        remaining_volume = optimal_volume
                        split_counter = 0
                        
                        while remaining_volume > 0.0001:
                            # Take either max_volume or the remaining, whichever is smaller
                            chunk_volume = min(remaining_volume, max_volume)
                            
                            # Validate chunk volume
                            valid_chunk = is_valid_broker_volume(symbol_info, chunk_volume)
                            if valid_chunk is None:
                                print(f"        Chunk volume {chunk_volume} not valid, trying smaller")
                                chunk_volume = round(chunk_volume - volume_step, 8)
                                valid_chunk = is_valid_broker_volume(symbol_info, chunk_volume)
                                if valid_chunk is None or valid_chunk < min_volume - 0.000001:
                                    print(f"        Cannot create valid chunk, breaking")
                                    break
                            
                            chunk_volume = valid_chunk
                            
                            # Create signal order (copy of original with chunk volume)
                            signal_order = order.copy()
                            signal_order[f"{broker_prefix}_volume"] = round(chunk_volume, 3)
                            signal_order["split_order"] = True
                            signal_order["parent_volume"] = round(optimal_volume, 3)
                            signal_order["split_number"] = split_counter + 1
                            signal_order["total_splits"] = 0  # Will update after loop
                            signal_order["moved_to_signals_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            
                            # Calculate split risk using MT5
                            split_risk = verify_risk_via_mt5(symbol, order_type, entry_price, exit_price, chunk_volume)
                            if split_risk is None:
                                # Fallback: proportional risk
                                split_risk = final_risk * (chunk_volume / optimal_volume)
                                print(f"        MT5 risk failed for chunk, using proportional: ${split_risk:.2f}")
                            
                            signal_order["split_risk"] = round(split_risk, 2)
                            signal_order["risk_verified_by_mt5"] = True
                            
                            file_signals.append(signal_order)
                            investor_signals_count += 1
                            total_signals_created += 1
                            remaining_volume -= chunk_volume
                            split_counter += 1
                            
                            print(f"       🟢 Split #{split_counter}: vol={chunk_volume:.3f}, risk=${split_risk:.2f}, remaining={remaining_volume:.3f}")
                        
                        # Update total_splits in all split orders
                        for sig in file_signals:
                            if sig.get("split_order") and sig.get("split_number", 0) <= split_counter:
                                sig["total_splits"] = split_counter
                        
                        print(f"       🟢 SPLIT COMPLETE: {split_counter} orders created")
                        print(f"          Total Volume: {optimal_volume:.3f}, Total Risk: ${final_risk:.2f}")
                    else:
                        # No splitting needed - single order
                        print(f"\n       🟢 SINGLE ORDER (No split needed)")
                        print(f"          Volume: {optimal_volume:.3f} (within broker max: {max_volume})")
                        
                        # Create single signal order
                        signal_order = order.copy()
                        signal_order["split_order"] = False
                        signal_order["parent_volume"] = round(optimal_volume, 3)
                        signal_order["split_risk"] = round(final_risk, 2)
                        signal_order["moved_to_signals_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        signal_order["split_number"] = 1
                        signal_order["total_splits"] = 1
                        
                        file_signals.append(signal_order)
                        investor_signals_count += 1
                        total_signals_created += 1
                        
                        print(f"       🟢 Signal created: vol={optimal_volume:.3f}, risk=${final_risk:.2f}")
                
                # Replace original orders list with only kept orders
                orders[:] = kept_orders
                
                # Save updated limit orders (only kept orders)
                if orders_modified:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(orders, f, indent=4)
                    
                    investor_files_updated += 1
                    total_files_updated += 1
                    investor_risk_usd += file_risk_total
                    total_risk_usd += file_risk_total
                    any_orders_processed = True
                    
                    print(f"\n    └─ 💾 Saved {len(kept_orders)} orders to {file_path.name}")
                
                # Save signal orders
                if file_signals:
                    try:
                        with open(signals_path, 'w', encoding='utf-8') as f:
                            json.dump(file_signals, f, indent=4)
                        
                        strategy_folder = file_path.parent.parent.name
                        print(f"    └─ 📊 {strategy_folder}: Created {len(file_signals)} signals, Rejected: {file_rejected}")
                        print(f"    └─ 📁 Signals saved to: {signals_path}")
                    except Exception as e:
                        print(f"    └─  Error writing limit_orders.json: {e}")
                
            except Exception as e:
                print(f"    └─  Error processing {file_path}: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        # Summary for current investor
        if investor_orders_updated > 0:
            print(f"\n  └─ {'='*40}")
            print(f"  └─ ✨ Investor {current_inv_id} Summary:")
            print(f"  └─     Files Processed:    {investor_files_updated}")
            print(f"  └─     Orders Risk-Scaled: {investor_orders_updated}")
            print(f"  └─     Total Risk:         ${investor_risk_usd:,.2f}")
            print(f"  └─     Signals Generated:  {investor_signals_count}")
            print(f"  └─     Signals Rejected:   {investor_signals_rejected}")
            print(f"  └─ {'='*40}")
        else:
            if investor_signals_rejected > 0:
                print(f"\n  └─  Investor {current_inv_id}: All {investor_signals_rejected} orders were rejected")
            else:
                print(f"\n  └─ 🔘 Investor {current_inv_id}: No orders processed")

    # Final summary
    print(f"\n{'='*10} USD RISK CALCULATION COMPLETE {'='*10}")
    print(f" Total Files Modified:     {total_files_updated}")
    print(f" Total Orders Updated:     {total_orders_updated}")
    print(f" Total Risk USD:           ${total_risk_usd:,.2f}")
    print(f" Total Signals Created:    {total_signals_created}")
    print(f" Total Signals Rejected:   {total_signals_rejected}")
    print(f" Symbols Normalized:       {total_symbols_normalized}")
    
    if total_orders_updated > 0:
        print(f" Average Risk per Order:   ${total_risk_usd / total_orders_updated if total_orders_updated > 0 else 0:.2f}")
    
    return any_orders_processed

def apply_default_prices(inv_id=None, callback_function=None):
    """
    Applies default prices from limit_orders_backup.json to limit_orders.json when default_price is true.
    Copies exit/target prices from backup to matching orders in limit_orders.json, handling symbol normalization.
    
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
            print(f"  └─  accountmanagement.json not found, skipping")
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
            print(f"  └─  Error reading accountmanagement.json: {e}")
            continue

        # 2. Load broker config for symbol handling
        broker_cfg = usersdictionary.get(current_inv_id)
        if not broker_cfg:
            print(f"  └─  No broker config found for {current_inv_id}")
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
            signals_path = backup_path.parent / "limit_orders.json"  # Same directory as backup
            
            # Check if limit_orders.json exists
            if not signals_path.exists():
                print(f"  └─  No limit_orders.json found in {backup_path.parent} (same folder as backup), skipping")
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
                    print(f"    └─  Empty backup file")
                    continue
                    
                if not signals:
                    print(f"    └─  Empty signals file")
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
                        print(f"      └─  Signal missing required fields: {signal}")
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
                            print(f"      └─  FAILED to find match for AUDCAD+ 15M sell_limit (normalized to {signal_symbol})")
                            print(f"          Looking for backup_key: ({signal_symbol}, {signal_timeframe}, {signal_type})")
                            
                            # Show all available backup keys
                            print(f"          Available backup keys:")
                            for (bsym, btf, btype) in list(backup_lookup.keys())[:10]:
                                if btf == signal_timeframe and btype == signal_type:
                                    print(f"            • ({bsym}, {btf}, {btype})")
                        else:
                            print(f"      └─  No backup match for: {raw_signal_symbol} -> {signal_symbol} ({signal_timeframe}, {signal_type})")
                
                # Save modified signals file
                if modified:
                    try:
                        with open(signals_path, 'w', encoding='utf-8') as f:
                            json.dump(signals, f, indent=4)
                        
                        investor_files_updated += 1
                        total_files_updated += 1
                        
                        print(f"    └─ 📝 Updated {signals_modified_count} orders in limit_orders.json")
                        
                        # Call callback if provided
                        if callback_function:
                            try:
                                callback_function(current_inv_id, backup_path, signals_path, modifications_log)
                            except Exception as e:
                                print(f"    └─  Callback error: {e}")
                        
                        # Show summary of modifications
                        if modifications_log:
                            print(f"    └─ 📋 Modification Summary:")
                            for mod in modifications_log[:5]:  # Show first 5
                                norm_info = f" -> {mod['normalized_symbol']}" if mod['symbol'] != mod['normalized_symbol'] else ""
                                print(f"      • {mod['symbol']}{norm_info} ({mod['timeframe']}): {mod['update_details']} [{mod['match_method']}]")
                            if len(modifications_log) > 5:
                                print(f"      • ... and {len(modifications_log) - 5} more")
                    
                    except Exception as e:
                        print(f"    └─  Error saving limit_orders.json: {e}")
                else:
                    print(f"    └─ ✓ No price updates needed for signals in {folder_path.name}")
                
            except Exception as e:
                print(f"  └─  Error processing {backup_path}: {e}")
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
            print(f"\n  └─  No modifications made for {current_inv_id}")

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

def martingale(inv_id=None):
    """
    Function: Checks martingale status using staged drawdown approach.
    
    STAGED DRAWDOWN LOGIC:
    - Each stage has a maximum loss limit defined by account_balance_maximum_risk_management
    - When drawdown exceeds the stage limit, we move to the next stage
    - Only the CURRENT STAGE DRAWDOWN (remainder) is processed for recovery
    - If remainder = 0 (exact multiple), we use account_balance_default_risk_management as floor
    
    LATER-BALANCE LOGIC:
    - Starting balance is the balance on execution start date
    - Profits are added to the starting balance to create a "later balance"
    - Drawdown is calculated from the highest later-balance (peak including profits)
    
    WINRATE/LOSSRATE LOGIC:
    - Winrate = Total Profits / (Total Profits + Total Losses) * 100
    - Lossrate = Total Losses / (Total Profits + Total Losses) * 100
    - Based on monetary value, not trade count
    
    IMPORTANT: MT5 connection must already be initialized by the calling function!
    
    Args:
        inv_id: Optional specific investor ID to process. If None, processes all investors.
        
    Returns:
        dict: Statistics about the martingale status
    """
    print(f"\n{'='*10} 🎰 MARTINGALE STAGED DRAWDOWN SYSTEM {'='*10}")
    if inv_id:
        print(f" Processing single investor: {inv_id}")

    # Track statistics
    stats = {
        "investor_id": inv_id if inv_id else "all",
        "investors_processed": 0,
        "martingale_enabled": False,
        "martingale_maximum_risk": 0,
        "martingale_loss_recovery_adder_percentage": 0,
        "martingale_for_position_order_scale": False,
        "martingale_pre_scaling": False,
        "martingale_pre_scale_highest_risk_adder": False,
        "highest_risk_reduction_percentage": 0,
        "martingale_pre_scale_expected_loss_adder": False,
        "expected_loss_reduction_percentage": 0,
        "has_loss": False,
        "execution_start_balance": 0.0,
        "later_balance": 0.0,
        "current_balance": 0.0,
        "total_profits_since_start": 0.0,
        "total_losses_since_start": 0.0,
        "total_drawdown": 0.0,
        "current_stage": 1,
        "current_stage_drawdown": 0.0,
        "stage_max_risk": 0.0,
        "is_exact_stage_completion": False,
        "default_minimum_risk": 0,
        "used_minimum_risk": False,
        "signals_modified": False,
        "limit_orders_modified": False,
        "pending_orders_modified": False,
        "risk_check_passed": False,
        "risk_exceeded": False,
        "order_risk_validation": {},
        "pending_order_sync_results": {},
        "pre_scaling_applied": False,
        "pre_scaling_details": {},
        "safety_cancellations": {},
        "safety_cancellations_count": 0,
        "orders_modified_count": 0,
        "winrate_percentage": 0.0,  # Based on monetary value
        "lossrate_percentage": 0.0,  # Based on monetary value
        "total_wins_value": 0.0,     # Total profit amount from winning trades
        "total_losses_value": 0.0,   # Total loss amount from losing trades
        "total_trades_count": 0,     # Number of trades (for reference only)
        "winning_trades_count": 0,   # Number of winning trades
        "losing_trades_count": 0,    # Number of losing trades
        "errors": 0,
        "processing_success": False
    }

    # Determine which investors to process
    investors_to_process = [inv_id] if inv_id else usersdictionary.keys()
    total_investors = len(investors_to_process) if not inv_id else 1
    processed = 0

    for user_brokerid in investors_to_process:
        processed += 1
        print(f"\n[{processed}/{total_investors}] {user_brokerid}")
        print(f"{'─'*50}")
        
        # Reset per-investor variables
        pre_scaling_details = {}
        safety_cancellations = {}
        safety_cancellations_count = 0
        
        # Get broker config
        broker_cfg = usersdictionary.get(user_brokerid)
        if not broker_cfg:
            print(f"  ✗ No broker config found")
            continue
        
        inv_root = Path(INV_PATH) / user_brokerid
        acc_mgmt_path = inv_root / "accountmanagement.json"

        if not acc_mgmt_path.exists():
            print(f"  ✗ Account config missing. Skipping.")
            continue

        # ========== SECTION 1: LOAD CONFIGURATION ==========
        def load_configuration():
            """Load and parse martingale configuration from accountmanagement.json"""
            try:
                with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                settings = config.get("settings", {})
                martingale_config = settings.get("martingale_config", {})
                
                if martingale_config:
                    martingale_enabled = martingale_config.get("enable_martingale", False)
                    recovery_adder_str = martingale_config.get("martingale_loss_recovery_adder_percentage", "0%")
                    martingale_for_position_order_scale = martingale_config.get("martingale_for_position_order_scale", False)
                    
                    pre_scaling_config = martingale_config.get("pre_scaling", {})
                    if pre_scaling_config:
                        martingale_pre_scaling = pre_scaling_config.get("martingale_pre_scaling", False)
                        martingale_pre_scale_highest_risk_adder = pre_scaling_config.get("martingale_pre_scale_highest_risk_adder", False)
                        highest_risk_reduction_str = pre_scaling_config.get("highest_risk_reduction_percentage", "0%")
                        martingale_pre_scale_expected_loss_adder = pre_scaling_config.get("martingale_pre_scale_expected_loss_adder", False)
                        expected_loss_reduction_str = pre_scaling_config.get("expected_loss_reduction_percentage", "0%")
                    else:
                        martingale_pre_scaling = martingale_config.get("martingale_pre_scaling", False)
                        martingale_pre_scale_highest_risk_adder = False
                        highest_risk_reduction_str = "0%"
                        martingale_pre_scale_expected_loss_adder = False
                        expected_loss_reduction_str = "0%"
                else:
                    martingale_enabled = settings.get("enable_martingale", False)
                    recovery_adder_str = settings.get("martingale_loss_recovery_adder_percentage", "0%")
                    martingale_for_position_order_scale = settings.get("martingale_for_position_order_scale", False)
                    martingale_pre_scaling = settings.get("martingale_pre_scaling", False)
                    martingale_pre_scale_highest_risk_adder = False
                    highest_risk_reduction_str = "0%"
                    martingale_pre_scale_expected_loss_adder = False
                    expected_loss_reduction_str = "0%"
                
                recovery_adder_percentage = 0
                if recovery_adder_str:
                    try:
                        recovery_adder_percentage = float(recovery_adder_str.replace('%', ''))
                    except:
                        recovery_adder_percentage = 0
                
                highest_risk_reduction_percentage = 0
                if highest_risk_reduction_str:
                    try:
                        highest_risk_reduction_percentage = float(highest_risk_reduction_str.replace('%', ''))
                    except:
                        highest_risk_reduction_percentage = 0
                
                expected_loss_reduction_percentage = 0
                if expected_loss_reduction_str:
                    try:
                        expected_loss_reduction_percentage = float(expected_loss_reduction_str.replace('%', ''))
                    except:
                        expected_loss_reduction_percentage = 0
                
                default_risk_map = config.get("account_balance_default_risk_management", {})
                default_minimum_risk = 2  # Default floor value
                
                if default_risk_map:
                    for range_str, risk_value in default_risk_map.items():
                        try:
                            raw_range = range_str.split("_")[0]
                            low_str, high_str = raw_range.split("-")
                            low = float(low_str)
                            high = float(high_str)
                            default_minimum_risk = float(risk_value)
                            break
                        except Exception as e:
                            continue
                
                return {
                    "config": config,
                    "martingale_enabled": martingale_enabled,
                    "recovery_adder_percentage": recovery_adder_percentage,
                    "martingale_for_position_order_scale": martingale_for_position_order_scale,
                    "martingale_pre_scaling": martingale_pre_scaling,
                    "martingale_pre_scale_highest_risk_adder": martingale_pre_scale_highest_risk_adder,
                    "highest_risk_reduction_percentage": highest_risk_reduction_percentage,
                    "martingale_pre_scale_expected_loss_adder": martingale_pre_scale_expected_loss_adder,
                    "expected_loss_reduction_percentage": expected_loss_reduction_percentage,
                    "default_minimum_risk": default_minimum_risk
                }
            except Exception as e:
                print(f"  ✗ Failed to read config: {e}")
                return None
        
        config_data = load_configuration()
        if config_data is None:
            stats["errors"] += 1
            continue
        
        config = config_data["config"]
        martingale_enabled = config_data["martingale_enabled"]
        recovery_adder_percentage = config_data["recovery_adder_percentage"]
        martingale_for_position_order_scale = config_data["martingale_for_position_order_scale"]
        martingale_pre_scaling = config_data["martingale_pre_scaling"]
        martingale_pre_scale_highest_risk_adder = config_data["martingale_pre_scale_highest_risk_adder"]
        highest_risk_reduction_percentage = config_data["highest_risk_reduction_percentage"]
        martingale_pre_scale_expected_loss_adder = config_data["martingale_pre_scale_expected_loss_adder"]
        expected_loss_reduction_percentage = config_data["expected_loss_reduction_percentage"]
        default_minimum_risk = config_data["default_minimum_risk"]
        
        stats.update({
            "martingale_enabled": martingale_enabled,
            "martingale_loss_recovery_adder_percentage": recovery_adder_percentage,
            "martingale_for_position_order_scale": martingale_for_position_order_scale,
            "martingale_pre_scaling": martingale_pre_scaling,
            "martingale_pre_scale_highest_risk_adder": martingale_pre_scale_highest_risk_adder,
            "highest_risk_reduction_percentage": highest_risk_reduction_percentage,
            "martingale_pre_scale_expected_loss_adder": martingale_pre_scale_expected_loss_adder,
            "expected_loss_reduction_percentage": expected_loss_reduction_percentage,
            "default_minimum_risk": default_minimum_risk
        })
        
        if not martingale_enabled:
            print(f"  ⏭️ Martingale DISABLED")
            stats["processing_success"] = True
            continue
        
        print(f"  ✓ Martingale ENABLED")
        print(f"  │ Recovery adder: {recovery_adder_percentage}%")
        print(f"  │ Pre-scaling: {'ON' if martingale_pre_scaling else 'OFF'}")
        print(f"  │ Default min risk floor: ${default_minimum_risk:.2f}")

        # ========== SECTION 2: GET CURRENT BALANCE ==========
        print(f"\n  📊 STEP 1: Balance Analysis")
        print(f"  {'─'*40}")
        
        account_info = mt5.account_info()
        if not account_info:
            print(f"  ✗ Failed to get account info - MT5 not initialized?")
            stats["errors"] += 1
            continue
        
        current_balance = account_info.balance
        stats["current_balance"] = current_balance
        print(f"  │ Current balance: ${current_balance:.2f}")

        # ========== SECTION 3: GET EXECUTION START BALANCE & TRADE STATS ==========
        def get_execution_start_balance_and_stats():
            """Get starting balance from activities.json's broker_balance field"""
            
            # Load activities.json to get broker_balance as starting balance
            activities_path = inv_root / "activities.json"
            starting_balance = current_balance  # fallback to current balance
            total_profits = 0.0
            total_losses = 0.0
            net_deposits = 0.0
            later_balance = current_balance
            winrate = 0
            lossrate = 0
            total_wins_value = 0
            total_losses_value = 0
            winning_trades_count = 0
            losing_trades_count = 0
            
            if activities_path.exists():
                try:
                    with open(activities_path, 'r', encoding='utf-8') as f:
                        activities = json.load(f)
                    
                    # Get broker_balance from activities.json as starting balance
                    broker_balance = activities.get('broker_balance')
                    if broker_balance is not None:
                        try:
                            starting_balance = float(broker_balance)
                            print(f"  │ Starting balance from activities.json (broker_balance): ${starting_balance:.2f}")
                        except (ValueError, TypeError):
                            print(f"  │ Could not parse broker_balance: {broker_balance}, using current balance")
                            starting_balance = current_balance
                    else:
                        print(f"  │ No broker_balance in activities.json, using current balance")
                        starting_balance = current_balance
                    
                    # Get execution_start_date for display only
                    execution_start_date = activities.get('execution_start_date')
                    if execution_start_date:
                        print(f"  │ Execution start date: {execution_start_date}")
                    
                except Exception as e:
                    print(f"  │ Could not load activities.json: {e}")
                    starting_balance = current_balance
            else:
                print(f"  │ No activities.json found, using current balance")
                starting_balance = current_balance
            
            # Calculate later-balance (starting balance + total profits)
            later_balance = starting_balance + total_profits
            
            print(f"  │ Starting balance: ${starting_balance:.2f}")
            print(f"  │ Current balance: ${current_balance:.2f}")
            print(f"  │ Later-balance (start + profits): ${later_balance:.2f}")
            
            return starting_balance, total_profits, total_losses, net_deposits, later_balance, winrate, lossrate, total_wins_value, total_losses_value, winning_trades_count, losing_trades_count

        execution_start_balance, total_profits_since_start, total_losses_since_start, net_deposits, later_balance, winrate, lossrate, total_wins_value, total_losses_value, winning_trades_count, losing_trades_count = get_execution_start_balance_and_stats()
        
        stats["execution_start_balance"] = execution_start_balance
        stats["later_balance"] = later_balance
        stats["total_profits_since_start"] = total_profits_since_start
        stats["total_losses_since_start"] = total_losses_since_start
        stats["winrate_percentage"] = winrate
        stats["lossrate_percentage"] = lossrate
        stats["total_wins_value"] = total_wins_value
        stats["total_losses_value"] = total_losses_value
        stats["total_trades_count"] = winning_trades_count + losing_trades_count
        stats["winning_trades_count"] = winning_trades_count
        stats["losing_trades_count"] = losing_trades_count
        
        # Calculate total drawdown from later-balance (starting balance + profits)
        # This respects profits as part of the balance
        total_drawdown = later_balance - current_balance
        total_drawdown = max(0, total_drawdown)
        stats["total_drawdown"] = total_drawdown
        
        print(f"\n  📉 Drawdown Analysis (Later-Balance Method):")
        print(f"  │ Execution start balance: ${execution_start_balance:.2f}")
        print(f"  │ Later-balance (start + profits): ${later_balance:.2f}")
        print(f"  │ Current balance: ${current_balance:.2f}")
        print(f"  │ Total drawdown from later-balance: ${total_drawdown:.2f}")
        
        if total_drawdown == 0:
            print(f"  │ ✓ No drawdown - account is at or above later-balance")
        else:
            print(f"  │ Drawdown detected: ${total_drawdown:.2f} ({(total_drawdown/later_balance*100):.2f}% from later-balance)")

        # ========== SECTION 4: STAGED DRAWDOWN CALCULATION ==========
        print(f"\n  🎯 STEP 2: Staged Drawdown Analysis")
        print(f"  {'─'*40}")
        
        def get_stage_max_risk():
            """Get martingale maximum risk per stage based on current balance"""
            martingale_risk_map = config.get("account_balance_maximum_risk_management", {})
            
            if martingale_risk_map:
                for range_str, risk_value in martingale_risk_map.items():
                    try:
                        raw_range = range_str.split("_")[0]
                        low_str, high_str = raw_range.split("-")
                        low = float(low_str)
                        high = float(high_str)
                        
                        if low <= current_balance <= high:
                            risk = float(risk_value)
                            return risk
                    except Exception:
                        continue
                
                return 100.0
            else:
                return 100.0
        
        stage_max_risk = get_stage_max_risk()
        stats["martingale_maximum_risk"] = stage_max_risk
        stats["stage_max_risk"] = stage_max_risk
        
        print(f"  │ Stage max risk (per round): ${stage_max_risk:.2f}")
        
        # Calculate current stage and drawdown based on later-balance
        if total_drawdown > 0 and stage_max_risk > 0:
            current_stage = int(total_drawdown // stage_max_risk) + 1
            current_stage_drawdown = total_drawdown % stage_max_risk
            is_exact_stage_completion = (current_stage_drawdown == 0)
            
            # If exact completion, we need to use default_minimum_risk as the drawdown target
            if is_exact_stage_completion and current_stage > 1:
                # We completed a stage exactly, so we're at the start of next stage
                current_stage_drawdown = default_minimum_risk
                stats["used_minimum_risk"] = True
                print(f"  │ EXACT STAGE COMPLETION - using floor risk: ${default_minimum_risk:.2f}")
            
            print(f"  │ Current stage: {current_stage}")
            print(f"  │ Stage drawdown to recover: ${current_stage_drawdown:.2f}")
            print(f"  │ Total drawdown across all stages: ${total_drawdown:.2f}")
            
            stats["current_stage"] = current_stage
            stats["current_stage_drawdown"] = current_stage_drawdown
            stats["is_exact_stage_completion"] = is_exact_stage_completion
            stats["has_loss"] = current_stage_drawdown > 0
        else:
            current_stage = 1
            current_stage_drawdown = 0
            is_exact_stage_completion = False
            stats["current_stage"] = 1
            stats["current_stage_drawdown"] = 0
            stats["has_loss"] = False
            print(f"  │ No drawdown to recover")

        # ========== SECTION 5: FILE LOADING UTILITIES ==========
        def load_limit_orders():
            """Load limit_orders.json file from original paths"""
            limit_orders_path = inv_root / "prices" / "pending_orders" / "limit_orders.json"
            
            if limit_orders_path.exists():
                with open(limit_orders_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return limit_orders_path, data
            
            fallback_path1 = inv_root / "pending_orders" / "limit_orders.json"
            if fallback_path1.exists():
                with open(fallback_path1, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return fallback_path1, data
            
            fallback_path2 = inv_root / "prices" / "limit_orders.json"
            if fallback_path2.exists():
                with open(fallback_path2, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return fallback_path2, data
            
            fallback_path3 = inv_root / "limit_orders.json"
            if fallback_path3.exists():
                with open(fallback_path3, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return fallback_path3, data
            
            return None, None

        def load_signals_json():
            """Load signals.json file from original path"""
            signals_path = inv_root / "prices" / "signals.json"
            
            if signals_path.exists():
                with open(signals_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return signals_path, data
            
            return None, None
        
        def save_limit_orders(file_path, data):
            """Save limit_orders.json file"""
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        
        def save_signals_json(file_path, data):
            """Save signals.json file"""
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        
        def get_all_symbols_from_limit_orders(data):
            """Get all symbols from limit_orders.json"""
            symbols = set()
            if isinstance(data, list):
                for order in data:
                    if isinstance(order, dict) and order.get('symbol'):
                        symbols.add(order['symbol'])
            return symbols
        
        def get_sample_order_from_limit_orders(data, symbol):
            """Get a sample order for a specific symbol from limit_orders.json"""
            if isinstance(data, list):
                for order in data:
                    if isinstance(order, dict) and order.get('symbol') == symbol:
                        entry = order.get('entry')
                        stop = order.get('exit') or order.get('stop_loss')
                        order_type = order.get('order_type')
                        if entry and stop and order_type:
                            return entry, stop, order_type
            return None, None, None
        
        def get_volume_field_from_order(order):
            """Extract volume field from order dict regardless of key name"""
            for key, value in order.items():
                if 'volume' in key.lower() and isinstance(value, (int, float)):
                    return key, value
            return None, None
        
        def update_volumes_in_limit_orders(orders_list, symbol_volumes):
            """Update volume fields for specific symbols in limit_orders.json"""
            updates_summary = {}
            
            for symbol, new_volume in symbol_volumes.items():
                updated_count = 0
                
                for order in orders_list:
                    if isinstance(order, dict) and order.get('symbol') == symbol:
                        volume_key, old_volume = get_volume_field_from_order(order)
                        
                        if volume_key:
                            if abs(old_volume - new_volume) > 0.001:
                                order[volume_key] = new_volume
                                updated_count += 1
                                print(f"        │ Updated {symbol} {volume_key}: {old_volume:.2f} → {new_volume:.2f} lots")
                
                updates_summary[symbol] = updated_count
            
            return updates_summary
        
        def get_default_volume_from_limit_orders(orders_data, symbol):
            """Get the default volume for a symbol from limit_orders.json"""
            if isinstance(orders_data, list):
                for order in orders_data:
                    if isinstance(order, dict) and order.get('symbol') == symbol:
                        volume_key, volume = get_volume_field_from_order(order)
                        if volume:
                            return volume
            return 0.01

        def update_volume_in_signals_recursive(data, symbol, new_volume, updated_count):
            """Recursively update volume fields for a specific symbol in signals.json"""
            if isinstance(data, dict):
                # Check if this is a trade dictionary with order_type
                if data.get("order_type") and ("entry" in data or "exit" in data):
                    if "volume" in data:
                        old_volume = data["volume"]
                        if abs(old_volume - new_volume) > 0.001:
                            data["volume"] = new_volume
                            updated_count += 1
                            print(f"        │ Updated {symbol} volume: {old_volume:.2f} → {new_volume:.2f} lots")
                
                # Recursively process all values
                for key, value in data.items():
                    if isinstance(value, (dict, list)):
                        updated_count = update_volume_in_signals_recursive(value, symbol, new_volume, updated_count)
            
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, (dict, list)):
                        updated_count = update_volume_in_signals_recursive(item, symbol, new_volume, updated_count)
            
            return updated_count
        
        def update_all_symbol_volumes_in_signals(signals_data, symbol_volumes):
            """Update all volume entries for specified symbols in signals.json"""
            updates_summary = {}
            
            for symbol, new_volume in symbol_volumes.items():
                updated_count = 0
                
                for category_name, category_data in signals_data.get('categories', {}).items():
                    symbols_in_category = category_data.get('symbols', {})
                    if symbol in symbols_in_category:
                        symbol_data = symbols_in_category[symbol]
                        updated_count = update_volume_in_signals_recursive(symbol_data, symbol, new_volume, updated_count)
                
                updates_summary[symbol] = updated_count
            
            return updates_summary
        
        def find_first_order_in_signals(signals_data, symbol):
            """Find first order for a symbol in signals.json"""
            for category_name, category_data in signals_data.get('categories', {}).items():
                symbols_in_category = category_data.get('symbols', {})
                if symbol in symbols_in_category:
                    symbol_data = symbols_in_category[symbol]
                    
                    def find_first_order(data):
                        if isinstance(data, dict):
                            if "order_type" in data and "entry" in data and "exit" in data:
                                return data.get('entry'), data.get('exit'), data.get('order_type')
                            for key, value in data.items():
                                if isinstance(value, (dict, list)):
                                    result = find_first_order(value)
                                    if result[0] is not None:
                                        return result
                        elif isinstance(data, list):
                            for item in data:
                                if isinstance(item, (dict, list)):
                                    result = find_first_order(item)
                                    if result[0] is not None:
                                        return result
                        return None, None, None
                    
                    return find_first_order(symbol_data)
            
            return None, None, None
        
        def get_current_volumes_from_signals(signals_data):
            """Extract current volumes for all symbols from signals.json"""
            volumes = {}
            
            def extract_volumes(data, symbol):
                if isinstance(data, dict):
                    if data.get("order_type") and "entry" in data and "exit" in data:
                        if "volume" in data:
                            volumes[symbol] = data["volume"]
                    for key, value in data.items():
                        if isinstance(value, (dict, list)):
                            extract_volumes(value, symbol)
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, (dict, list)):
                            extract_volumes(item, symbol)
            
            for category_name, category_data in signals_data.get('categories', {}).items():
                symbols_in_category = category_data.get('symbols', {})
                for symbol, symbol_signals in symbols_in_category.items():
                    extract_volumes(symbol_signals, symbol)
            
            return volumes
        
        def get_current_volumes_from_limit_orders(orders_data):
            """Extract current volumes for all symbols from limit_orders.json"""
            volumes = {}
            if isinstance(orders_data, list):
                for order in orders_data:
                    if isinstance(order, dict):
                        symbol = order.get('symbol')
                        if symbol:
                            volume_key, volume = get_volume_field_from_order(order)
                            if volume:
                                volumes[symbol] = volume
            return volumes

        # ========== SECTION 6: LIMIT_ORDERS RECOVERY ==========
        def calculate_safe_volume(required_volume, symbol, entry, stop, order_type, stage_max_risk, is_exact_stage_completion, default_volume):
            """
            Calculate safe volume that respects stage_max_risk limit.
            Returns: (safe_volume, risk_check_passed, actual_risk)
            """
            # Determine order type for MT5
            is_buy = 'buy' in order_type.lower() if order_type else False
            calc_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
            
            # Get symbol info
            symbol_info = mt5.symbol_info(symbol)
            if not symbol_info:
                return 0, False, 0
            
            if not symbol_info.visible:
                mt5.symbol_select(symbol, True)
            
            # Calculate risk for a given volume
            def calculate_risk(volume):
                profit = mt5.order_calc_profit(calc_type, symbol, volume, entry, stop)
                return abs(profit) if profit is not None else None
            
            # First, check if minimum volume (0.01) is even allowed
            min_volume = 0.01
            min_risk = calculate_risk(min_volume)
            
            if min_risk is None:
                return 0, False, 0
            
            # If minimum risk already exceeds stage_max_risk, we cannot trade
            if min_risk > stage_max_risk:
                print(f"        │ WARNING: Minimum volume {min_volume} lots has risk ${min_risk:.2f} which exceeds limit ${stage_max_risk:.2f}")
                print(f"        │ → Cannot place any order for {symbol} (risk limit too low)")
                return 0, False, 0
            
            # Calculate risk for required volume
            required_risk = calculate_risk(required_volume)
            if required_risk is None:
                return 0, False, 0
            
            # If required risk is within limit, use required volume
            if required_risk <= stage_max_risk:
                safe_volume = required_volume
                risk_check_passed = True
                actual_risk = required_risk
            else:
                # Binary search for maximum safe volume
                low = min_volume
                high = required_volume
                safe_volume = low
                
                for _ in range(30):  # More iterations for precision
                    mid = (low + high) / 2
                    mid_risk = calculate_risk(mid)
                    if mid_risk is None:
                        break
                    if mid_risk <= stage_max_risk:
                        safe_volume = mid
                        low = mid
                    else:
                        high = mid
                
                safe_volume = round(safe_volume, 2)
                actual_risk = calculate_risk(safe_volume)
                risk_check_passed = False
                stats["risk_exceeded"] = True
                
                print(f"        │ Risk limit would be exceeded: ${required_risk:.2f} > ${stage_max_risk:.2f}")
                print(f"        │ → Reduced volume from {required_volume:.2f} to {safe_volume:.2f} lots (risk: ${actual_risk:.2f})")
            
            # Apply floor if needed (for exact stage completion)
            # But ONLY if it doesn't exceed risk limit
            if is_exact_stage_completion and safe_volume < default_volume:
                default_risk = calculate_risk(default_volume)
                if default_risk and default_risk <= stage_max_risk:
                    safe_volume = default_volume
                    actual_risk = default_risk
                    stats["used_minimum_risk"] = True
                    print(f"        │ → Exact stage completion: using floor volume {default_volume:.2f} lots (risk: ${actual_risk:.2f})")
                else:
                    print(f"        │ Exact stage completion but floor volume would exceed risk limit - keeping reduced volume")
            
            return safe_volume, risk_check_passed, actual_risk

        def process_limit_orders_recovery(recovery_amount):
            """Process recovery for limit_orders.json using current stage drawdown"""
            print(f"\n  📝 STEP 3: Processing limit_orders.json")
            print(f"  {'─'*40}")
            
            if recovery_amount <= 0:
                print(f"  │ No recovery amount")
                return False, {}
            
            print(f"  │ Recovery target: ${recovery_amount:.2f}")
            
            if recovery_adder_percentage > 0:
                adder_amount = recovery_amount * (recovery_adder_percentage / 100)
                total_recovery = recovery_amount + adder_amount
                print(f"  │ +{recovery_adder_percentage}% adder: ${adder_amount:.2f}")
                print(f"  │ Total to recover: ${total_recovery:.2f}")
            else:
                total_recovery = recovery_amount
            
            orders_path, orders_data = load_limit_orders()
            if orders_path is None or orders_data is None:
                print(f"  │ No limit_orders.json found")
                return False, {}
            
            try:
                volumes_to_update = {}
                all_symbols = get_all_symbols_from_limit_orders(orders_data)
                
                if not all_symbols:
                    print(f"  │ No symbols found")
                    return False, {}
                
                print(f"  │ Symbols: {', '.join(all_symbols)}")
                
                for symbol in all_symbols:
                    default_volume = get_default_volume_from_limit_orders(orders_data, symbol)
                    sample_entry, sample_stop, sample_order_type = get_sample_order_from_limit_orders(orders_data, symbol)
                    
                    if not sample_entry or not sample_stop:
                        continue
                    
                    symbols_count = len(all_symbols)
                    symbol_recovery = total_recovery / symbols_count
                    
                    # Get symbol info
                    symbol_info = mt5.symbol_info(symbol)
                    if not symbol_info:
                        continue
                    
                    if not symbol_info.visible:
                        mt5.symbol_select(symbol, True)
                    
                    # Calculate price difference
                    is_buy = 'buy' in sample_order_type.lower() if sample_order_type else False
                    price_diff = abs(sample_entry - sample_stop)
                    contract_size = symbol_info.trade_contract_size
                    
                    if price_diff * contract_size <= 0:
                        continue
                    
                    # Calculate required volume based on recovery amount
                    estimated_volume = symbol_recovery / (price_diff * contract_size)
                    required_volume = round(estimated_volume, 2)
                    
                    if required_volume < 0.01:
                        required_volume = 0.01
                    
                    # Calculate safe volume respecting risk limits
                    safe_volume, risk_check_passed, actual_risk = calculate_safe_volume(
                        required_volume, symbol, sample_entry, sample_stop, 
                        sample_order_type, stage_max_risk, is_exact_stage_completion, default_volume
                    )
                    
                    if safe_volume >= 0.01:
                        volumes_to_update[symbol] = safe_volume
                        status = "✓" if risk_check_passed else ""
                        print(f"  │ {status} {symbol}: {safe_volume:.2f} lots (risk: ${actual_risk:.2f} / limit: ${stage_max_risk:.2f})")
                        
                        stats["order_risk_validation"][symbol] = {
                            "symbol": symbol,
                            "safe_volume": safe_volume,
                            "safe_risk": actual_risk,
                            "risk_limit": stage_max_risk,
                            "risk_check_passed": risk_check_passed,
                            "required_volume": required_volume,
                            "required_risk": None  # Will be filled if needed
                        }
                        
                        # Calculate and store required risk for debugging
                        calc_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
                        required_risk_calc = mt5.order_calc_profit(calc_type, symbol, required_volume, sample_entry, sample_stop)
                        if required_risk_calc:
                            stats["order_risk_validation"][symbol]["required_risk"] = abs(required_risk_calc)
                
                if volumes_to_update:
                    updates_summary = update_volumes_in_limit_orders(orders_data, volumes_to_update)
                    if any(count > 0 for count in updates_summary.values()):
                        save_limit_orders(orders_path, orders_data)
                        stats["limit_orders_modified"] = True
                        stats["orders_modified_count"] = len(volumes_to_update)
                        print(f"\n  ✓ limit_orders.json updated")
                        return True, get_current_volumes_from_limit_orders(orders_data)
                
                return False, get_current_volumes_from_limit_orders(orders_data)
                
            except Exception as e:
                print(f"  ✗ Error: {e}")
                stats["errors"] += 1
                return False, {}

        # ========== SECTION 7: SIGNALS.JSON RECOVERY ==========
        def process_signals_recovery(recovery_amount):
            """Process recovery for signals.json using current stage drawdown"""
            print(f"\n  📝 STEP 4: Processing signals.json")
            print(f"  {'─'*40}")
            
            if recovery_amount <= 0:
                print(f"  │ No recovery amount")
                return False, {}
            
            print(f"  │ Recovery target: ${recovery_amount:.2f}")
            
            if recovery_adder_percentage > 0:
                adder_amount = recovery_amount * (recovery_adder_percentage / 100)
                total_recovery = recovery_amount + adder_amount
                print(f"  │ +{recovery_adder_percentage}% adder: ${adder_amount:.2f}")
                print(f"  │ Total to recover: ${total_recovery:.2f}")
            else:
                total_recovery = recovery_amount
            
            signals_path, signals_data = load_signals_json()
            if signals_path is None or signals_data is None:
                print(f"  │ signals.json not found")
                return False, {}
            
            try:
                volumes_to_update = {}
                all_symbols = set()
                
                for category_name, category_data in signals_data.get('categories', {}).items():
                    symbols_in_category = category_data.get('symbols', {})
                    for symbol in symbols_in_category.keys():
                        all_symbols.add(symbol)
                
                if not all_symbols:
                    print(f"  │ No symbols found")
                    return False, {}
                
                print(f"  │ Symbols: {', '.join(all_symbols)}")
                
                for symbol in all_symbols:
                    symbol_share = total_recovery / len(all_symbols)
                    
                    if symbol_share == 0:
                        continue
                    
                    sample_entry, sample_stop, sample_order_type = find_first_order_in_signals(signals_data, symbol)
                    
                    if not sample_entry or not sample_stop:
                        continue
                    
                    # Get default volume from signals (if exists)
                    default_volume = 0.01
                    def get_default_volume_from_signals(signals_data, symbol):
                        for category_name, category_data in signals_data.get('categories', {}).items():
                            symbols_in_category = category_data.get('symbols', {})
                            if symbol in symbols_in_category:
                                symbol_data = symbols_in_category[symbol]
                                def find_volume(data):
                                    if isinstance(data, dict):
                                        if "volume" in data:
                                            return data["volume"]
                                        for key, value in data.items():
                                            if isinstance(value, (dict, list)):
                                                result = find_volume(value)
                                                if result:
                                                    return result
                                    elif isinstance(data, list):
                                        for item in data:
                                            if isinstance(item, (dict, list)):
                                                result = find_volume(item)
                                                if result:
                                                    return result
                                    return None
                                vol = find_volume(symbol_data)
                                if vol:
                                    return vol
                        return 0.01
                    
                    default_volume = get_default_volume_from_signals(signals_data, symbol)
                    
                    # Get symbol info
                    symbol_info = mt5.symbol_info(symbol)
                    if not symbol_info:
                        continue
                    
                    if not symbol_info.visible:
                        mt5.symbol_select(symbol, True)
                    
                    # Calculate price difference
                    price_diff = abs(sample_entry - sample_stop)
                    contract_size = symbol_info.trade_contract_size
                    
                    if price_diff * contract_size <= 0:
                        continue
                    
                    # Calculate required volume based on recovery amount
                    estimated_volume = symbol_share / (price_diff * contract_size)
                    required_volume = round(estimated_volume, 2)
                    
                    if required_volume < 0.01:
                        required_volume = 0.01
                    
                    # Calculate safe volume respecting risk limits
                    safe_volume, risk_check_passed, actual_risk = calculate_safe_volume(
                        required_volume, symbol, sample_entry, sample_stop, 
                        sample_order_type, stage_max_risk, is_exact_stage_completion, default_volume
                    )
                    
                    if safe_volume >= 0.01:
                        volumes_to_update[symbol] = safe_volume
                        status = "✓" if risk_check_passed else ""
                        print(f"  │ {status} {symbol}: {safe_volume:.2f} lots (risk: ${actual_risk:.2f} / limit: ${stage_max_risk:.2f})")
                        
                        stats["order_risk_validation"][symbol] = {
                            "symbol": symbol,
                            "safe_volume": safe_volume,
                            "safe_risk": actual_risk,
                            "risk_limit": stage_max_risk,
                            "risk_check_passed": risk_check_passed,
                            "required_volume": required_volume
                        }
                        
                        # Calculate and store required risk for debugging
                        is_buy = 'buy' in sample_order_type.lower() if sample_order_type else False
                        calc_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
                        required_risk_calc = mt5.order_calc_profit(calc_type, symbol, required_volume, sample_entry, sample_stop)
                        if required_risk_calc:
                            stats["order_risk_validation"][symbol]["required_risk"] = abs(required_risk_calc)
                
                if volumes_to_update:
                    updates_summary = update_all_symbol_volumes_in_signals(signals_data, volumes_to_update)
                    if any(count > 0 for count in updates_summary.values()):
                        save_signals_json(signals_path, signals_data)
                        stats["signals_modified"] = True
                        print(f"\n  ✓ signals.json updated")
                        return True, get_current_volumes_from_signals(signals_data)
                
                return False, get_current_volumes_from_signals(signals_data)
                
            except Exception as e:
                print(f"  ✗ Error: {e}")
                stats["errors"] += 1
                return False, {}

        # ========== SECTION 8: PRE-SCALING (INDEPENDENT FOR EACH FILE) ==========
        def analyze_highest_risk_from_limit_orders(limit_orders_data):
            """Analyze highest risk orders from limit_orders.json only"""
            highest_risk_orders = {}
            
            if not limit_orders_data or not isinstance(limit_orders_data, list):
                return highest_risk_orders
            
            symbol_orders = {}
            for order in limit_orders_data:
                if isinstance(order, dict):
                    symbol = order.get('symbol')
                    if symbol:
                        if symbol not in symbol_orders:
                            symbol_orders[symbol] = []
                        symbol_orders[symbol].append(order)
            
            for symbol, orders_list in symbol_orders.items():
                highest_risk = 0
                highest_risk_order_info = None
                
                for order in orders_list:
                    entry = order.get('entry')
                    stop = order.get('exit') or order.get('stop_loss')
                    volume_key, volume = get_volume_field_from_order(order)
                    order_type = order.get('order_type', 'Unknown')
                    
                    if entry and stop and volume and volume > 0:
                        symbol_info = mt5.symbol_info(symbol)
                        if symbol_info:
                            contract_size = symbol_info.trade_contract_size
                            price_diff = abs(entry - stop)
                            risk = price_diff * volume * contract_size
                            
                            if risk > highest_risk:
                                highest_risk = risk
                                highest_risk_order_info = {
                                    'order_type': order_type,
                                    'entry': entry,
                                    'stop': stop,
                                    'volume': volume,
                                    'risk': risk,
                                    'original_risk': risk,
                                    'source': 'limit_orders'
                                }
                
                if highest_risk_order_info:
                    if highest_risk_reduction_percentage > 0:
                        reduction_amount = highest_risk * (highest_risk_reduction_percentage / 100)
                        highest_risk = highest_risk - reduction_amount
                        highest_risk_order_info['risk'] = highest_risk
                        highest_risk_order_info['reduction_applied'] = reduction_amount
                    
                    highest_risk_orders[symbol] = highest_risk_order_info
            
            return highest_risk_orders
        
        def analyze_highest_risk_from_signals(signals_data):
            """Analyze highest risk orders from signals.json only"""
            highest_risk_orders = {}
            
            if not signals_data:
                return highest_risk_orders
            
            def find_all_orders(data, symbol, orders_list):
                if isinstance(data, dict):
                    if data.get("order_type") and "entry" in data and "exit" in data:
                        entry = data.get('entry')
                        stop = data.get('exit')
                        volume = data.get('volume', 0)
                        order_type = data.get('order_type', 'Unknown')
                        
                        if entry and stop and volume and volume > 0:
                            orders_list.append({
                                'entry': entry,
                                'stop': stop,
                                'volume': volume,
                                'order_type': order_type
                            })
                    
                    for key, value in data.items():
                        if isinstance(value, (dict, list)):
                            find_all_orders(value, symbol, orders_list)
                
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, (dict, list)):
                            find_all_orders(item, symbol, orders_list)
            
            for category_name, category_data in signals_data.get('categories', {}).items():
                symbols_in_category = category_data.get('symbols', {})
                for symbol, symbol_signals in symbols_in_category.items():
                    orders_list = []
                    find_all_orders(symbol_signals, symbol, orders_list)
                    
                    highest_risk = 0
                    highest_risk_order_info = None
                    
                    for order in orders_list:
                        entry = order['entry']
                        stop = order['stop']
                        volume = order['volume']
                        order_type = order['order_type']
                        
                        symbol_info = mt5.symbol_info(symbol)
                        if symbol_info:
                            contract_size = symbol_info.trade_contract_size
                            price_diff = abs(entry - stop)
                            risk = price_diff * volume * contract_size
                            
                            if risk > highest_risk:
                                highest_risk = risk
                                highest_risk_order_info = {
                                    'order_type': order_type,
                                    'entry': entry,
                                    'stop': stop,
                                    'volume': volume,
                                    'risk': risk,
                                    'original_risk': risk,
                                    'source': 'signals'
                                }
                    
                    if highest_risk_order_info:
                        if highest_risk_reduction_percentage > 0:
                            reduction_amount = highest_risk * (highest_risk_reduction_percentage / 100)
                            highest_risk = highest_risk - reduction_amount
                            highest_risk_order_info['risk'] = highest_risk
                            highest_risk_order_info['reduction_applied'] = reduction_amount
                        
                        highest_risk_orders[symbol] = highest_risk_order_info
            
            return highest_risk_orders
        
        def process_pre_scaling():
            """Process pre-scaling independently for limit_orders.json and signals.json"""
            if not martingale_pre_scaling:
                return False
            
            print(f"\n{'='*60}")
            print(f"  🎯 PRE-SCALING ANALYSIS")
            print(f"{'='*60}")
            print(f"  │ Highest risk adder: {'✓ ENABLED' if martingale_pre_scale_highest_risk_adder else '✗ DISABLED'}")
            print(f"  │   - Reduction: {highest_risk_reduction_percentage}%")
            print(f"  │ Expected loss adder: {'✓ ENABLED' if martingale_pre_scale_expected_loss_adder else '✗ DISABLED'}")
            print(f"  │   - Reduction: {expected_loss_reduction_percentage}%")
            print(f"{'─'*60}")
            
            try:
                # Get current open positions
                positions = mt5.positions_get()
                if positions is None or not positions:
                    print(f"  │ No open positions found - pre-scaling skipped")
                    return False
                
                print(f"  │ 📊 Open Positions: {len(positions)}")
                print()
                
                # Display current positions details
                for pos in positions:
                    print(f"    Position #{pos.ticket}: {pos.symbol}")
                    print(f"      ├─ Type: {'BUY' if pos.type == 0 else 'SELL'}")
                    print(f"      ├─ Volume: {pos.volume:.2f} lots")
                    print(f"      ├─ Entry: {pos.price_open:.5f}")
                    print(f"      ├─ Current: {pos.price_current:.5f}")
                    print(f"      ├─ Stop Loss: {pos.sl if pos.sl else 'None'}")
                    print(f"      ├─ Take Profit: {pos.tp if pos.tp else 'None'}")
                    print(f"      └─ Profit: ${pos.profit:.2f}")
                    print()
                
                # Load order files independently
                limit_orders_path, limit_orders_data = load_limit_orders()
                signals_path, signals_data = load_signals_json()
                
                # Get current volumes from both files independently
                current_limit_volumes = {}
                if limit_orders_data:
                    current_limit_volumes = get_current_volumes_from_limit_orders(limit_orders_data)
                    print(f"  📄 Current limit_orders.json volumes:")
                    for symbol, vol in current_limit_volumes.items():
                        print(f"     {symbol}: {vol:.2f} lots")
                
                current_signals_volumes = {}
                if signals_data:
                    current_signals_volumes = get_current_volumes_from_signals(signals_data)
                    print(f"  📄 Current signals.json volumes:")
                    for symbol, vol in current_signals_volumes.items():
                        print(f"     {symbol}: {vol:.2f} lots")
                
                # Analyze highest risk orders from limit_orders.json only
                limit_highest_risk_orders = {}
                if martingale_pre_scale_highest_risk_adder and limit_orders_data:
                    print(f"\n  🔍 Analyzing highest risk orders from limit_orders.json:")
                    print(f"  {'─'*50}")
                    limit_highest_risk_orders = analyze_highest_risk_from_limit_orders(limit_orders_data)
                    
                    for symbol, order_info in limit_highest_risk_orders.items():
                        print(f"\n    📌 {symbol} (from limit_orders.json) - Highest Risk Order:")
                        print(f"       ├─ Type: {order_info['order_type']}")
                        print(f"       ├─ Entry: {order_info['entry']:.5f}")
                        print(f"       ├─ Stop: {order_info['stop']:.5f}")
                        print(f"       ├─ Volume: {order_info['volume']:.2f} lots")
                        print(f"       ├─ Original Risk: ${order_info['original_risk']:.2f}")
                        if highest_risk_reduction_percentage > 0:
                            print(f"       ├─ Reduction ({highest_risk_reduction_percentage}%): ${order_info.get('reduction_applied', 0):.2f}")
                            print(f"       └─ Adjusted Risk: ${order_info['risk']:.2f}")
                        else:
                            print(f"       └─ Risk: ${order_info['risk']:.2f}")
                
                # Analyze highest risk orders from signals.json only
                signals_highest_risk_orders = {}
                if martingale_pre_scale_highest_risk_adder and signals_data:
                    print(f"\n  🔍 Analyzing highest risk orders from signals.json:")
                    print(f"  {'─'*50}")
                    signals_highest_risk_orders = analyze_highest_risk_from_signals(signals_data)
                    
                    for symbol, order_info in signals_highest_risk_orders.items():
                        print(f"\n    📌 {symbol} (from signals.json) - Highest Risk Order:")
                        print(f"       ├─ Type: {order_info['order_type']}")
                        print(f"       ├─ Entry: {order_info['entry']:.5f}")
                        print(f"       ├─ Stop: {order_info['stop']:.5f}")
                        print(f"       ├─ Volume: {order_info['volume']:.2f} lots")
                        print(f"       ├─ Original Risk: ${order_info['original_risk']:.2f}")
                        if highest_risk_reduction_percentage > 0:
                            print(f"       ├─ Reduction ({highest_risk_reduction_percentage}%): ${order_info.get('reduction_applied', 0):.2f}")
                            print(f"       └─ Adjusted Risk: ${order_info['risk']:.2f}")
                        else:
                            print(f"       └─ Risk: ${order_info['risk']:.2f}")
                
                # Pre-scale calculation for each position - INDEPENDENT FOR LIMIT ORDERS
                pre_scale_volumes_limit = {}
                pre_scale_volumes_signals = {}
                pre_scaling_details = {}
                
                print(f"\n{'─'*60}")
                print(f"  📈 Calculating pre-scaling requirements per symbol:")
                print(f"{'─'*60}")
                
                for position in positions:
                    try:
                        symbol = position.symbol
                        position_sl = position.sl
                        position_type = position.type
                        position_volume = position.volume
                        position_entry = position.price_open
                        
                        print(f"\n  🔹 Processing {symbol}:")
                        print(f"     Position: {position_volume:.2f} lots @ {position_entry:.5f}")
                        
                        if position_sl is None or position_sl == 0:
                            print(f"     No stop loss set - skipping pre-scaling for {symbol}")
                            continue
                        
                        print(f"     Stop Loss: {position_sl:.5f}")
                        
                        symbol_info = mt5.symbol_info(symbol)
                        if not symbol_info:
                            print(f"     No symbol info for {symbol}")
                            continue
                        
                        contract_size = symbol_info.trade_contract_size
                        
                        # Calculate price difference based on position type
                        if position_type == mt5.POSITION_TYPE_BUY:
                            price_diff = position_entry - position_sl
                        else:
                            price_diff = position_sl - position_entry
                        
                        if price_diff <= 0:
                            print(f"     Invalid price difference: {price_diff}")
                            continue
                        
                        # Calculate expected loss from position
                        expected_loss_original = price_diff * position_volume * contract_size
                        expected_loss = abs(expected_loss_original)
                        
                        if expected_loss_reduction_percentage > 0:
                            reduction_amount = expected_loss * (expected_loss_reduction_percentage / 100)
                            expected_loss = expected_loss - reduction_amount
                        
                        print(f"     📉 Expected Loss Calculation:")
                        print(f"        ├─ Price diff: {price_diff:.5f}")
                        print(f"        ├─ Contract size: {contract_size}")
                        print(f"        ├─ Original loss: ${abs(expected_loss_original):.2f}")
                        if expected_loss_reduction_percentage > 0:
                            print(f"        ├─ Reduction ({expected_loss_reduction_percentage}%): ${reduction_amount:.2f}")
                        print(f"        └─ Adjusted loss: ${expected_loss:.2f}")
                        
                        # Risk per lot
                        risk_per_lot = price_diff * contract_size
                        print(f"     Risk per lot: ${risk_per_lot:.2f}")
                        
                        # ===== PROCESS LIMIT_ORDERS.JSON INDEPENDENTLY =====
                        if limit_orders_data and current_limit_volumes.get(symbol, 0) > 0:
                            print(f"\n     📄 PROCESSING LIMIT_ORDERS.JSON for {symbol}:")
                            
                            total_extra_limit = 0
                            calculation_details_limit = {
                                "symbol": symbol,
                                "file_type": "limit_orders",
                                "expected_loss": expected_loss,
                                "expected_loss_original": abs(expected_loss_original),
                                "expected_loss_reduction": reduction_amount if expected_loss_reduction_percentage > 0 else 0,
                                "highest_risk": 0,
                                "highest_risk_original": 0,
                                "highest_risk_reduction": 0,
                                "total_extra": 0,
                                "additional_volume": 0
                            }
                            
                            # Add expected loss if enabled
                            if martingale_pre_scale_expected_loss_adder:
                                total_extra_limit += expected_loss
                                print(f"        ├─ Expected loss adder: ${expected_loss:.2f}")
                            
                            # Add highest risk from limit orders if enabled
                            if martingale_pre_scale_highest_risk_adder and symbol in limit_highest_risk_orders:
                                highest_risk_info = limit_highest_risk_orders[symbol]
                                highest_risk_value = highest_risk_info['risk']
                                calculation_details_limit["highest_risk_original"] = highest_risk_info['original_risk']
                                calculation_details_limit["highest_risk"] = highest_risk_value
                                if highest_risk_reduction_percentage > 0:
                                    calculation_details_limit["highest_risk_reduction"] = highest_risk_info.get('reduction_applied', 0)
                                total_extra_limit += highest_risk_value
                                print(f"        ├─ Highest risk adder (from limit_orders): ${highest_risk_value:.2f}")
                            
                            calculation_details_limit["total_extra"] = total_extra_limit
                            
                            if total_extra_limit > 0:
                                print(f"        └─ TOTAL EXTRA RISK FOR LIMIT ORDERS: ${total_extra_limit:.2f}")
                                
                                # Calculate additional volume needed
                                additional_volume_needed = total_extra_limit / risk_per_lot
                                additional_volume_needed = round(additional_volume_needed, 2)
                                calculation_details_limit["additional_volume"] = additional_volume_needed
                                
                                current_volume = current_limit_volumes.get(symbol, 0)
                                new_volume = current_volume + additional_volume_needed
                                new_volume = round(new_volume, 2)
                                
                                print(f"        ├─ Current volume: {current_volume:.2f} lots")
                                print(f"        ├─ Additional needed: {additional_volume_needed:.2f} lots")
                                print(f"        └─ NEW TOTAL VOLUME: {new_volume:.2f} lots")
                                
                                if new_volume >= 0.01 and new_volume != current_volume:
                                    pre_scale_volumes_limit[symbol] = new_volume
                                
                                pre_scaling_details[f"{symbol}_limit"] = calculation_details_limit
                            else:
                                print(f"        └─ No extra risk to cover for limit orders")
                        
                        # ===== PROCESS SIGNALS.JSON INDEPENDENTLY =====
                        if signals_data and current_signals_volumes.get(symbol, 0) > 0:
                            print(f"\n     📄 PROCESSING SIGNALS.JSON for {symbol}:")
                            
                            total_extra_signals = 0
                            calculation_details_signals = {
                                "symbol": symbol,
                                "file_type": "signals",
                                "expected_loss": expected_loss,
                                "expected_loss_original": abs(expected_loss_original),
                                "expected_loss_reduction": reduction_amount if expected_loss_reduction_percentage > 0 else 0,
                                "highest_risk": 0,
                                "highest_risk_original": 0,
                                "highest_risk_reduction": 0,
                                "total_extra": 0,
                                "additional_volume": 0
                            }
                            
                            # Add expected loss if enabled
                            if martingale_pre_scale_expected_loss_adder:
                                total_extra_signals += expected_loss
                                print(f"        ├─ Expected loss adder: ${expected_loss:.2f}")
                            
                            # Add highest risk from signals if enabled
                            if martingale_pre_scale_highest_risk_adder and symbol in signals_highest_risk_orders:
                                highest_risk_info = signals_highest_risk_orders[symbol]
                                highest_risk_value = highest_risk_info['risk']
                                calculation_details_signals["highest_risk_original"] = highest_risk_info['original_risk']
                                calculation_details_signals["highest_risk"] = highest_risk_value
                                if highest_risk_reduction_percentage > 0:
                                    calculation_details_signals["highest_risk_reduction"] = highest_risk_info.get('reduction_applied', 0)
                                total_extra_signals += highest_risk_value
                                print(f"        ├─ Highest risk adder (from signals): ${highest_risk_value:.2f}")
                            
                            calculation_details_signals["total_extra"] = total_extra_signals
                            
                            if total_extra_signals > 0:
                                print(f"        └─ TOTAL EXTRA RISK FOR SIGNALS: ${total_extra_signals:.2f}")
                                
                                # Calculate additional volume needed
                                additional_volume_needed = total_extra_signals / risk_per_lot
                                additional_volume_needed = round(additional_volume_needed, 2)
                                calculation_details_signals["additional_volume"] = additional_volume_needed
                                
                                current_volume = current_signals_volumes.get(symbol, 0)
                                new_volume = current_volume + additional_volume_needed
                                new_volume = round(new_volume, 2)
                                
                                print(f"        ├─ Current volume: {current_volume:.2f} lots")
                                print(f"        ├─ Additional needed: {additional_volume_needed:.2f} lots")
                                print(f"        └─ NEW TOTAL VOLUME: {new_volume:.2f} lots")
                                
                                if new_volume >= 0.01 and new_volume != current_volume:
                                    pre_scale_volumes_signals[symbol] = new_volume
                                
                                pre_scaling_details[f"{symbol}_signals"] = calculation_details_signals
                            else:
                                print(f"        └─ No extra risk to cover for signals")
                        
                    except Exception as e:
                        print(f"     ✗ Error processing {symbol}: {e}")
                        import traceback
                        traceback.print_exc()
                        continue
                
                # Apply updates to files independently
                print(f"\n{'─'*60}")
                print(f"  💾 APPLYING PRE-SCALING UPDATES")
                print(f"{'─'*60}")
                
                updated = False
                
                # Update limit_orders.json independently
                if pre_scale_volumes_limit and limit_orders_data:
                    print(f"\n  📄 Updating limit_orders.json:")
                    updates_summary = update_volumes_in_limit_orders(limit_orders_data, pre_scale_volumes_limit)
                    if any(count > 0 for count in updates_summary.values()):
                        save_limit_orders(limit_orders_path, limit_orders_data)
                        updated = True
                        for symbol, count in updates_summary.items():
                            if count > 0:
                                print(f"     ✓ {symbol}: updated {count} order(s) in limit_orders.json")
                    else:
                        print(f"     ℹ️ No changes needed for limit_orders.json")
                
                # Update signals.json independently
                if pre_scale_volumes_signals and signals_data:
                    print(f"\n  📄 Updating signals.json:")
                    updates_summary = update_all_symbol_volumes_in_signals(signals_data, pre_scale_volumes_signals)
                    if any(count > 0 for count in updates_summary.values()):
                        save_signals_json(signals_path, signals_data)
                        updated = True
                        for symbol, count in updates_summary.items():
                            if count > 0:
                                print(f"     ✓ {symbol}: updated {count} order(s) in signals.json")
                    else:
                        print(f"     ℹ️ No changes needed for signals.json")
                
                # Store pre-scaling details in stats
                stats["pre_scaling_details"] = pre_scaling_details
                
                if updated:
                    print(f"\n  ✅ PRE-SCALING COMPLETE")
                    print(f"     ├─ Total symbols processed: {len(set([k.split('_')[0] for k in pre_scaling_details.keys()]))}")
                    print(f"     ├─ Limit orders updated: {len(pre_scale_volumes_limit)}")
                    print(f"     └─ Signals updated: {len(pre_scale_volumes_signals)}")
                else:
                    print(f"\n  ℹ️ No pre-scaling updates needed")
                
                return updated
                
            except Exception as e:
                print(f"  ✗ Pre-scaling error: {e}")
                import traceback
                traceback.print_exc()
                return False

        # ========== SECTION 9: SAFETY CHECK ==========
        def safety_check_pending_orders():
            """Cancel MT5 orders that don't match volumes in both files"""
            print(f"\n  🛡️ STEP 6: Safety Check")
            print(f"  {'─'*40}")
            
            # Use nonlocal variable from outer scope
            nonlocal safety_cancellations, safety_cancellations_count
            
            try:
                pending_orders = mt5.orders_get()
                if pending_orders is None:
                    pending_orders = []
                
                print(f"  │ Found {len(pending_orders)} pending orders")
                
                if not pending_orders:
                    return
                
                limit_orders_path, limit_orders_data = load_limit_orders()
                signals_path, signals_data = load_signals_json()
                
                expected_volumes = {}
                
                # Get from limit_orders.json
                if limit_orders_data and isinstance(limit_orders_data, list):
                    for order in limit_orders_data:
                        if isinstance(order, dict):
                            symbol = order.get('symbol')
                            order_type = order.get('order_type', '').lower()
                            
                            volume_key, expected_volume = get_volume_field_from_order(order)
                            
                            if symbol and expected_volume and expected_volume > 0:
                                if symbol not in expected_volumes:
                                    expected_volumes[symbol] = {}
                                if "buy" in order_type:
                                    expected_volumes[symbol]['bid'] = expected_volume
                                elif "sell" in order_type:
                                    expected_volumes[symbol]['ask'] = expected_volume
                
                # Get from signals.json
                if signals_data:
                    def collect_expected_volumes(data, symbol):
                        if isinstance(data, dict):
                            if data.get("order_type") and "entry" in data and "exit" in data:
                                order_type = data.get("order_type", "").lower()
                                expected_volume = data.get("volume", 0)
                                
                                if expected_volume > 0:
                                    if symbol not in expected_volumes:
                                        expected_volumes[symbol] = {}
                                    if "buy" in order_type:
                                        expected_volumes[symbol]['bid'] = expected_volume
                                    elif "sell" in order_type:
                                        expected_volumes[symbol]['ask'] = expected_volume
                            
                            for key, value in data.items():
                                if isinstance(value, (dict, list)):
                                    collect_expected_volumes(value, symbol)
                        
                        elif isinstance(data, list):
                            for item in data:
                                if isinstance(item, (dict, list)):
                                    collect_expected_volumes(item, symbol)
                    
                    for category_name, category_data in signals_data.get('categories', {}).items():
                        symbols_in_category = category_data.get('symbols', {})
                        for symbol, symbol_signals in symbols_in_category.items():
                            collect_expected_volumes(symbol_signals, symbol)
                
                orders_to_cancel = []
                
                for order in pending_orders:
                    symbol = order.symbol
                    order_type = order.type
                    order_volume = order.volume_initial
                    
                    is_buy = order_type in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP]
                    is_sell = order_type in [mt5.ORDER_TYPE_SELL_LIMIT, mt5.ORDER_TYPE_SELL_STOP]
                    
                    order_direction = 'bid' if is_buy else 'ask' if is_sell else None
                    
                    if not order_direction:
                        continue
                    
                    expected_volume = expected_volumes.get(symbol, {}).get(order_direction, 0)
                    
                    if expected_volume == 0 or abs(order_volume - expected_volume) > 0.001:
                        orders_to_cancel.append(order)
                
                if orders_to_cancel:
                    print(f"  │ Cancelling {len(orders_to_cancel)} mismatched orders...")
                    
                    for order in orders_to_cancel:
                        try:
                            cancel_request = {
                                "action": mt5.TRADE_ACTION_REMOVE,
                                "order": order.ticket,
                            }
                            
                            cancel_result = mt5.order_send(cancel_request)
                            
                            if cancel_result and cancel_result.retcode == mt5.TRADE_RETCODE_DONE:
                                safety_cancellations[order.ticket] = {"success": True}
                                safety_cancellations_count += 1
                            else:
                                safety_cancellations[order.ticket] = {"success": False}
                                stats["errors"] += 1
                                
                        except Exception as e:
                            safety_cancellations[order.ticket] = {"success": False, "error": str(e)}
                            stats["errors"] += 1
                    
                    if safety_cancellations_count > 0:
                        stats["pending_orders_modified"] = True
                        print(f"  │ ✓ Cancelled {safety_cancellations_count} orders")
                
                stats["safety_cancellations"] = safety_cancellations
                stats["safety_cancellations_count"] = safety_cancellations_count
                
            except Exception as e:
                print(f"  ✗ Safety check error: {e}")
                import traceback
                traceback.print_exc()

        # ========== MAIN EXECUTION ==========
        def main():
            """Main execution - staged drawdown recovery with independent pre-scaling"""
            # Use nonlocal variables
            nonlocal safety_cancellations, safety_cancellations_count
            
            print(f"\n{'='*50}")
            print(f"  STAGE {current_stage} RECOVERY - ${current_stage_drawdown:.2f}")
            print(f"{'='*50}")
            
            # Process limit_orders.json (only if there's drawdown to recover)
            limit_orders_updated = False
            if current_stage_drawdown > 0:
                limit_orders_updated, _ = process_limit_orders_recovery(current_stage_drawdown)
            
            # Process signals.json (only if there's drawdown to recover)
            signals_updated = False
            if current_stage_drawdown > 0:
                signals_updated, _ = process_signals_recovery(current_stage_drawdown)
            
            # ⭐ PRE-SCALING - ALWAYS RUNS INDEPENDENTLY WHEN ENABLED ⭐
            pre_scaling_updated = process_pre_scaling()
            stats["pre_scaling_applied"] = pre_scaling_updated
            
            # Safety check (always run)
            safety_check_pending_orders()
            
            stats["signals_modified"] = signals_updated
            stats["limit_orders_modified"] = limit_orders_updated
            
            print(f"\n{'='*50}")
            print(f"  STAGE {current_stage} COMPLETE")
            print(f"  │ Limit orders: {'✓' if limit_orders_updated else '−'}")
            print(f"  │ Signals: {'✓' if signals_updated else '−'}")
            print(f"  │ Pre-scaling: {'✓' if pre_scaling_updated else '−'}")
            print(f"  │ Orders cancelled: {safety_cancellations_count}")
            print(f"{'='*50}")
        
        # Execute main
        main()
        
        stats["investors_processed"] += 1
        stats["processing_success"] = True

    # --- FINAL SUMMARY ---
    print(f"\n{'='*50}")
    print(f"  MARTINGALE SUMMARY")
    print(f"{'='*50}")
    print(f"  Investor: {stats['investor_id']}")
    print(f"  Status: {'✓ SUCCESS' if stats['processing_success'] else '✗ FAILED'}")
    
    if stats['martingale_enabled']:
        print(f"\n  📊 Balance:")
        print(f"  │ Execution start balance: ${stats['execution_start_balance']:.2f}")
        print(f"  │ Later-balance (start + profits): ${stats['later_balance']:.2f}")
        print(f"  │ Current balance: ${stats['current_balance']:.2f}")
        print(f"  │ Total drawdown from later-balance: ${stats['total_drawdown']:.2f}")
        
        print(f"\n  📈 Trade Statistics (By Monetary Value):")
        print(f"  │ Total trades: {stats['total_trades_count']}")
        print(f"  │ Winning trades: {stats['winning_trades_count']} (${stats['total_wins_value']:.2f})")
        print(f"  │ Losing trades: {stats['losing_trades_count']} (${stats['total_losses_value']:.2f})")
        print(f"  │ Winrate (by value): {stats['winrate_percentage']:.2f}%")
        print(f"  │ Lossrate (by value): {stats['lossrate_percentage']:.2f}%")
        print(f"  │ Total profits: ${stats['total_profits_since_start']:.2f}")
        print(f"  │ Total losses: ${stats['total_losses_since_start']:.2f}")
        
        print(f"\n  🎯 Staged Drawdown:")
        print(f"  │ Stage max risk: ${stats['stage_max_risk']:.2f}")
        print(f"  │ Current stage: {stats['current_stage']}")
        print(f"  │ Stage drawdown: ${stats['current_stage_drawdown']:.2f}")
        
        if stats.get('used_minimum_risk'):
            print(f"  │ Used floor risk: ${stats['default_minimum_risk']:.2f}")
        
        if stats.get('risk_exceeded'):
            print(f"  │ Risk limit was exceeded and adjusted")
        
        print(f"\n  📝 Modifications:")
        print(f"  │ limit_orders.json: {'✓' if stats.get('limit_orders_modified') else '−'}")
        print(f"  │ signals.json: {'✓' if stats.get('signals_modified') else '−'}")
        print(f"  │ Pre-scaling: {'✓' if stats.get('pre_scaling_applied') else '−'}")
        print(f"  │ Orders cancelled: {stats.get('safety_cancellations_count', 0)}")
        
        # Display risk validation details
        if stats.get('order_risk_validation'):
            print(f"\n  🔒 Risk Validation:")
            for symbol, details in stats['order_risk_validation'].items():
                status = "✓" if details.get('risk_check_passed') else ""
                print(f"  │ {status} {symbol}: {details['safe_volume']:.2f} lots → ${details['safe_risk']:.2f} risk (limit: ${details['risk_limit']:.2f})")
                if not details.get('risk_check_passed'):
                    print(f"  │   └─ Was: ${details.get('required_risk', 0):.2f} risk with {details.get('required_volume', 0):.2f} lots")
        
        # Display pre-scaling details if available
        if stats.get('pre_scaling_details'):
            print(f"\n  📈 Pre-scaling Details:")
            for key, details in stats['pre_scaling_details'].items():
                file_type = details.get('file_type', 'unknown')
                symbol = details.get('symbol', key)
                print(f"  │ {symbol} ({file_type}):")
                if details.get('expected_loss', 0) > 0:
                    print(f"  │   ├─ Expected loss: ${details['expected_loss']:.2f}")
                if details.get('highest_risk', 0) > 0:
                    print(f"  │   ├─ Highest risk: ${details['highest_risk']:.2f}")
                print(f"  │   ├─ Total extra: ${details['total_extra']:.2f}")
                if details.get('additional_volume', 0) > 0:
                    print(f"  │   └─ Additional volume: {details['additional_volume']:.2f} lots")
    
    print(f"\n  Errors: {stats['errors']}")
    print(f"{'='*50}\n")
    
    return stats

def close_unauthorized_orders_old(inv_id=None):
    """
    CLOSE UNAUTHORIZED ORDERS - ENFORCEMENT FUNCTION
    
    This function ensures that EVERY pending order and open position is properly
    accounted for in tradeshistory.json. Any order/position NOT found in the
    history file is immediately terminated (cancelled or closed).
    
    RULES:
    1. Scans ALL open positions and pending orders in MT5
    2. For each item, checks if it exists in tradeshistory.json (by ticket number)
    3. If NOT found → IMMEDIATELY CANCEL/CLOSE (unauthorized)
    4. If found → KEEP (authorized)
    5. Does NOT modify any JSON files - only closes/cancels orders
    
    Args:
        inv_id: Optional specific investor ID. If None, processes all investors.
        
    Returns:
        dict: Statistics about closed/cancelled unauthorized orders
    """
    print("\n" + "="*80)
    print("🔒 CLOSE UNAUTHORIZED ORDERS - ENFORCEMENT MODE")
    print("="*80)
    print("   RULE: EVERY order/position MUST be in tradeshistory.json")
    print("   If NOT found → IMMEDIATE TERMINATION")
    print("   NOTE: No JSON files are modified, only MT5 orders are cancelled/closed")
    print("="*80)
    
    investor_ids = [inv_id] if inv_id else list(usersdictionary.keys())
    
    global_stats = {
        'investors_processed': 0,
        'investors_with_issues': 0,
        'total_pending_orders_found': 0,
        'total_positions_found': 0,
        'total_pending_cancelled': 0,
        'total_positions_closed': 0,
        'total_unauthorized_found': 0,
        'errors_encountered': 0
    }
    
    for user_brokerid in investor_ids:
        print(f"\n{'='*60}")
        print(f"📋 INVESTOR: {user_brokerid}")
        print(f"{'='*60}")
        
        investor_stats = {
            'pending_orders_found': 0,
            'positions_found': 0,
            'pending_cancelled': 0,
            'positions_closed': 0,
            'unauthorized_count': 0,
            'errors': 0
        }
        
        inv_root = Path(INV_PATH) / user_brokerid
        
        if not inv_root.exists():
            print(f"    Investor root not found: {inv_root}")
            continue
        
        # Load tradeshistory.json
        history_path = inv_root / "tradeshistory.json"
        
        if not history_path.exists():
            print(f"    CRITICAL: tradeshistory.json NOT FOUND!")
            print(f"   📁 Expected at: {history_path}")
            print(f"    Cannot verify authorization - SKIPPING this investor")
            global_stats['errors_encountered'] += 1
            continue
        
        try:
            with open(history_path, 'r', encoding='utf-8') as f:
                history = json.load(f)
            print(f"   ✅ Loaded tradeshistory.json ({len(history)} total records)")
        except Exception as e:
            print(f"    Failed to read tradeshistory.json: {e}")
            global_stats['errors_encountered'] += 1
            continue
        
        # Extract ALL valid ticket numbers from history
        # Skip current_orders snapshot entries and non-dict items
        authorized_tickets = set()
        authorized_position_ids = set()
        
        for record in history:
            if isinstance(record, dict) and 'current_orders' not in record:
                # Check for order ticket
                ticket = record.get('ticket')
                if ticket:
                    authorized_tickets.add(int(ticket))
                
                # Check for position ticket (if different from order ticket)
                position_ticket = record.get('position_ticket')
                if position_ticket:
                    authorized_position_ids.add(int(position_ticket))
                
                # Check for position_id (might be stored differently)
                position_id = record.get('position_id')
                if position_id and isinstance(position_id, (int, str)):
                    try:
                        # Convert POS_123 to 123 if needed
                        if isinstance(position_id, str) and position_id.startswith('POS_'):
                            pos_num = int(position_id.split('_')[1])
                            authorized_position_ids.add(pos_num)
                        elif isinstance(position_id, int):
                            authorized_position_ids.add(position_id)
                    except (ValueError, IndexError):
                        pass
        
        print(f"   🔑 Authorized tickets in history: {len(authorized_tickets)}")
        if authorized_position_ids:
            print(f"   🔑 Authorized position tickets: {len(authorized_position_ids)}")
        
        # Connect to MT5 account
        broker_cfg = usersdictionary.get(user_brokerid)
        if not broker_cfg:
            print(f"    No broker configuration found")
            continue
        
        login_id = int(broker_cfg['LOGIN_ID'])
        mt5_path = broker_cfg["TERMINAL_PATH"]
        
        # Check if already connected to correct account
        acc = mt5.account_info()
        if acc is None or acc.login != login_id:
            print(f"    Not logged into correct account. Expected: {login_id}")
            # Try to initialize MT5 connection
            if not mt5.initialize(path=mt5_path, login=login_id, 
                                   password=broker_cfg["PASSWORD"], 
                                   server=broker_cfg["SERVER"]):
                print(f"    Failed to initialize MT5 for {user_brokerid}")
                global_stats['errors_encountered'] += 1
                continue
        else:
            print(f"   ✅ Connected to account: {acc.login}")
        
        # STEP 1: SCAN ALL PENDING ORDERS
        pending_orders = mt5.orders_get()
        if pending_orders:
            print(f"\n   📋 SCANNING PENDING ORDERS...")
            investor_stats['pending_orders_found'] = len(pending_orders)
            
            for order in pending_orders:
                order_ticket = order.ticket
                order_symbol = order.symbol
                order_type_map = {
                    mt5.ORDER_TYPE_BUY_LIMIT: "BUY_LIMIT",
                    mt5.ORDER_TYPE_SELL_LIMIT: "SELL_LIMIT",
                    mt5.ORDER_TYPE_BUY_STOP: "BUY_STOP",
                    mt5.ORDER_TYPE_SELL_STOP: "SELL_STOP",
                    mt5.ORDER_TYPE_BUY_STOP_LIMIT: "BUY_STOP_LIMIT",
                    mt5.ORDER_TYPE_SELL_STOP_LIMIT: "SELL_STOP_LIMIT"
                }
                order_type_name = order_type_map.get(order.type, f"TYPE_{order.type}")
                
                # Check if ticket is authorized
                if order_ticket in authorized_tickets:
                    print(f"      ✅ Pending #{order_ticket}: {order_type_name} {order_symbol} - AUTHORIZED")
                    continue
                
                # UNAUTHORIZED - MUST CANCEL (USING SAME LOGIC AS check_pending_orders_risk)
                print(f"      🚨 UNAUTHORIZED Pending #{order_ticket}: {order_type_name} {order_symbol}")
                print(f"         → Ticket NOT found in tradeshistory.json")
                print(f"         → Initiating IMMEDIATE CANCELLATION...")
                
                # USE SAME SIMPLE REQUEST AS check_pending_orders_risk
                cancel_request = {
                    "action": mt5.TRADE_ACTION_REMOVE,
                    "order": order_ticket
                }
                
                try:
                    result = mt5.order_send(cancel_request)
                    
                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        print(f"         ✅ SUCCESS: Order #{order_ticket} CANCELLED")
                        investor_stats['pending_cancelled'] += 1
                        investor_stats['unauthorized_count'] += 1
                    else:
                        error_msg = result.comment if result else "No response"
                        error_code = result.retcode if result else "Unknown"
                        print(f"          FAILED: Could not cancel #{order_ticket}")
                        print(f"            Error: {error_msg} (code: {error_code})")
                        investor_stats['errors'] += 1
                        
                except Exception as e:
                    print(f"          EXCEPTION: {e}")
                    investor_stats['errors'] += 1
        
        else:
            print(f"\n   ℹ️  No pending orders found")
        
        # STEP 2: SCAN ALL OPEN POSITIONS
        open_positions = mt5.positions_get()
        if open_positions:
            print(f"\n   💼 SCANNING OPEN POSITIONS...")
            investor_stats['positions_found'] = len(open_positions)
            
            for position in open_positions:
                pos_ticket = position.ticket
                pos_symbol = position.symbol
                pos_type = "BUY" if position.type == mt5.POSITION_TYPE_BUY else "SELL"
                
                # Check if ticket is authorized (either as order or position)
                is_authorized = False
                
                # Check direct position ticket
                if pos_ticket in authorized_tickets:
                    is_authorized = True
                elif pos_ticket in authorized_position_ids:
                    is_authorized = True
                
                # Also check if there's a record with this position_ticket
                # (some brokers may use different ticket numbers)
                if not is_authorized:
                    # Search history for any record referencing this position
                    for record in history:
                        if isinstance(record, dict):
                            if record.get('position_ticket') == pos_ticket:
                                is_authorized = True
                                break
                            if record.get('ticket') == pos_ticket and record.get('status') == 'running_position':
                                is_authorized = True
                                break
                
                if is_authorized:
                    print(f"      ✅ Position #{pos_ticket}: {pos_type} {pos_symbol} - AUTHORIZED")
                    continue
                
                # UNAUTHORIZED - MUST CLOSE
                print(f"      🚨 UNAUTHORIZED Position #{pos_ticket}: {pos_type} {pos_symbol}")
                print(f"         → Ticket NOT found in tradeshistory.json")
                print(f"         → Initiating IMMEDIATE CLOSURE...")
                
                # Get current market price
                tick = mt5.symbol_info_tick(pos_symbol)
                if not tick:
                    print(f"          Cannot get price for {pos_symbol} - cannot close")
                    investor_stats['errors'] += 1
                    continue
                
                # Determine closing order type
                if position.type == mt5.POSITION_TYPE_BUY:
                    # Close BUY position by SELLING
                    close_type = mt5.ORDER_TYPE_SELL
                    close_price = tick.bid
                else:
                    # Close SELL position by BUYING
                    close_type = mt5.ORDER_TYPE_BUY
                    close_price = tick.ask
                
                close_request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": pos_symbol,
                    "volume": position.volume,
                    "type": close_type,
                    "position": pos_ticket,
                    "price": close_price,
                    "deviation": 20,
                    "magic": position.magic if hasattr(position, 'magic') else 0,
                    "comment": "UNAUTHORIZED - Not in tradeshistory.json",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                
                try:
                    result = mt5.order_send(close_request)
                    
                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        print(f"         ✅ SUCCESS: Position #{pos_ticket} CLOSED")
                        investor_stats['positions_closed'] += 1
                        investor_stats['unauthorized_count'] += 1
                    else:
                        error_msg = result.comment if result else "No response"
                        error_code = result.retcode if result else "Unknown"
                        print(f"          FAILED: Could not close #{pos_ticket}")
                        print(f"            Error: {error_msg} (code: {error_code})")
                        
                        # Try alternative approach if first attempt fails
                        print(f"         🔄 Attempting alternative closure method...")
                        
                        alt_close_request = {
                            "action": mt5.TRADE_ACTION_DEAL,
                            "symbol": pos_symbol,
                            "volume": position.volume,
                            "type": close_type,
                            "position": pos_ticket,
                            "price": close_price,
                            "deviation": 50,  # Increased deviation
                            "comment": "UNAUTHORIZED - Retry",
                            "type_filling": mt5.ORDER_FILLING_RETURN,  # Different filling mode
                        }
                        
                        alt_result = mt5.order_send(alt_close_request)
                        
                        if alt_result and alt_result.retcode == mt5.TRADE_RETCODE_DONE:
                            print(f"         ✅ SUCCESS (alt): Position #{pos_ticket} CLOSED")
                            investor_stats['positions_closed'] += 1
                            investor_stats['unauthorized_count'] += 1
                        else:
                            alt_error = alt_result.comment if alt_result else "No response"
                            alt_code = alt_result.retcode if alt_result else "Unknown"
                            print(f"          Alternative also FAILED: {alt_error} (code: {alt_code})")
                            investor_stats['errors'] += 1
                        
                except Exception as e:
                    print(f"          EXCEPTION: {e}")
                    investor_stats['errors'] += 1
        
        else:
            print(f"\n   ℹ️  No open positions found")
        
        # Investor summary (NO JSON UPDATES)
        print(f"\n   📊 INVESTOR {user_brokerid} SUMMARY:")
        print(f"      • Pending orders found: {investor_stats['pending_orders_found']}")
        print(f"      • Open positions found: {investor_stats['positions_found']}")
        if investor_stats['pending_cancelled'] > 0:
            print(f"      •  Pending orders CANCELLED (unauthorized): {investor_stats['pending_cancelled']}")
        if investor_stats['positions_closed'] > 0:
            print(f"      •  Positions CLOSED (unauthorized): {investor_stats['positions_closed']}")
        if investor_stats['unauthorized_count'] > 0:
            print(f"      • 🚨 TOTAL UNAUTHORIZED: {investor_stats['unauthorized_count']}")
        if investor_stats['errors'] > 0:
            print(f"      •  Errors encountered: {investor_stats['errors']}")
        
        if investor_stats['unauthorized_count'] == 0:
            print(f"      • ✅ ALL ORDERS AUTHORIZED - Clean account")
        
        # Update global stats
        global_stats['investors_processed'] += 1
        global_stats['total_pending_orders_found'] += investor_stats['pending_orders_found']
        global_stats['total_positions_found'] += investor_stats['positions_found']
        global_stats['total_pending_cancelled'] += investor_stats['pending_cancelled']
        global_stats['total_positions_closed'] += investor_stats['positions_closed']
        global_stats['total_unauthorized_found'] += investor_stats['unauthorized_count']
        global_stats['errors_encountered'] += investor_stats['errors']
        
        if investor_stats['unauthorized_count'] > 0:
            global_stats['investors_with_issues'] += 1
    
    # FINAL GLOBAL SUMMARY
    print("\n" + "="*80)
    print("🏁 ENFORCEMENT COMPLETE - FINAL REPORT")
    print("="*80)
    print(f"   Investors processed: {global_stats['investors_processed']}")
    print(f"   Investors with unauthorized orders: {global_stats['investors_with_issues']}")
    print(f"\n   📊 TOTAL SCANNED:")
    print(f"      • Pending orders: {global_stats['total_pending_orders_found']}")
    print(f"      • Open positions: {global_stats['total_positions_found']}")
    print(f"\n   🔒 ENFORCEMENT ACTIONS:")
    print(f"      • Pending orders CANCELLED: {global_stats['total_pending_cancelled']}")
    print(f"      • Open positions CLOSED: {global_stats['total_positions_closed']}")
    print(f"      • TOTAL UNAUTHORIZED REMOVED: {global_stats['total_unauthorized_found']}")
    print(f"\n    Errors: {global_stats['errors_encountered']}")
    
    if global_stats['total_unauthorized_found'] > 0:
        print(f"\n    WARNING: Unauthorized orders were found and terminated!")
        print(f"   💡 Check strategy signals that generated these orders")
        print(f"   💡 Run again to ensure all unauthorized orders are removed")
    else:
        print(f"\n   ✅ SUCCESS: All orders are authorized!")
        print(f"   ✅ No unauthorized orders found in any account")
    
    print("="*80 + "\n")
    
    return global_stats

def close_unauthorized_orders(inv_id=None):
    """
    CLOSE UNAUTHORIZED ORDERS - ENFORCEMENT FUNCTION (MAGIC NUMBER STRATEGY)
    
    This function uses Magic Number to identify authorized vs unauthorized orders.
    - Authorized Magic Number = LOGIN_ID + USER_ID (e.g., 5996427 + 10 = 599642710)
    - ANY order/position WITHOUT the correct magic number is immediately terminated
    
    RULES:
    1. Connects to MT5 and scans ALL open positions and pending orders
    2. For each item, checks if its magic number matches authorized_magic_number
    3. If magic number DOES NOT match → IMMEDIATELY CANCEL/CLOSE (unauthorized)
    4. If magic number matches → KEEP (authorized)
    5. tradeshistory.json is ONLY used for closed order tracking, NOT for authorization
    
    Args:
        inv_id: Optional specific investor ID. If None, processes all investors.
        
    Returns:
        dict: Statistics about closed/cancelled unauthorized orders
    """
    print("\n" + "="*80)
    print("🔒 CLOSE UNAUTHORIZED ORDERS - ENFORCEMENT MODE (MAGIC NUMBER STRATEGY)")
    print("="*80)
    print("   RULE: Order/Position magic number MUST equal LOGIN_ID + USER_ID")
    print("   If magic number mismatch → IMMEDIATE TERMINATION")
    print("   tradeshistory.json is for tracking only - NOT used for authorization")
    print("="*80)
    
    investor_ids = [inv_id] if inv_id else list(usersdictionary.keys())
    
    global_stats = {
        'investors_processed': 0,
        'investors_with_issues': 0,
        'total_pending_orders_found': 0,
        'total_positions_found': 0,
        'total_pending_cancelled': 0,
        'total_positions_closed': 0,
        'total_unauthorized_found': 0,
        'errors_encountered': 0
    }
    
    for user_brokerid in investor_ids:
        print(f"\n{'='*60}")
        print(f"📋 INVESTOR: {user_brokerid}")
        print(f"{'='*60}")
        
        investor_stats = {
            'pending_orders_found': 0,
            'positions_found': 0,
            'pending_cancelled': 0,
            'positions_closed': 0,
            'unauthorized_count': 0,
            'errors': 0,
            'authorized_magic_number': None
        }
        
        inv_root = Path(INV_PATH) / user_brokerid
        
        if not inv_root.exists():
            print(f"    Investor root not found: {inv_root}")
            continue
        
        # ============================================================
        # GET AUTHORIZED MAGIC NUMBER FROM CONFIGURATION
        # ============================================================
        broker_cfg = usersdictionary.get(user_brokerid)
        if not broker_cfg:
            print(f"    No broker configuration found for investor {user_brokerid}")
            continue
        
        login_id = broker_cfg.get('LOGIN_ID', '')
        if not login_id:
            print(f"    No LOGIN_ID found for investor {user_brokerid}")
            continue
        
        # Construct Magic Number: LOGIN_ID + USER_ID
        try:
            authorized_magic_number = int(str(login_id) + str(user_brokerid))
            investor_stats['authorized_magic_number'] = authorized_magic_number
            print(f"   🔑 Authorized Magic Number: {authorized_magic_number}")
            print(f"      (LOGIN_ID: {login_id} + USER_ID: {user_brokerid})")
        except (ValueError, TypeError) as e:
            print(f"    Error creating magic number: {e}")
            continue
        
        # ============================================================
        # LOAD tradeshistory.json (FOR TRACKING ONLY - NOT AUTHORIZATION)
        # ============================================================
        history_path = inv_root / "tradeshistory.json"
        closed_trades_for_tracking = []
        
        if history_path.exists():
            try:
                with open(history_path, 'r', encoding='utf-8') as f:
                    closed_trades_for_tracking = json.load(f)
                print(f"   📝 Loaded tradeshistory.json ({len(closed_trades_for_tracking)} total records for tracking only)")
            except Exception as e:
                print(f"    ⚠️ Could not read tradeshistory.json: {e}")
                print(f"    Continuing with magic number authorization only...")
        else:
            print(f"    ℹ️ tradeshistory.json not found - will create when orders close")
        
        # ============================================================
        # CONNECT TO MT5 ACCOUNT
        # ============================================================
        mt5_path = broker_cfg.get("TERMINAL_PATH", "")
        password = broker_cfg.get("PASSWORD", "")
        server = broker_cfg.get("SERVER", "")
        
        # Check if already connected to correct account
        acc = mt5.account_info()
        if acc is None or acc.login != int(login_id):
            print(f"    🔌 Connecting to account {login_id}...")
            if not mt5.initialize(path=mt5_path, login=int(login_id), 
                                   password=password, server=server):
                print(f"    Failed to initialize MT5 for {user_brokerid}: {mt5.last_error()}")
                global_stats['errors_encountered'] += 1
                continue
            print(f"   ✅ Connected to account: {login_id}")
        else:
            print(f"   ✅ Already connected to account: {acc.login}")
        
        # ============================================================
        # STEP 1: SCAN ALL PENDING ORDERS
        # ============================================================
        pending_orders = mt5.orders_get()
        if pending_orders:
            print(f"\n   📋 SCANNING PENDING ORDERS (by Magic Number)...")
            investor_stats['pending_orders_found'] = len(pending_orders)
            
            for order in pending_orders:
                order_ticket = order.ticket
                order_symbol = order.symbol
                order_magic = order.magic
                order_type_map = {
                    mt5.ORDER_TYPE_BUY_LIMIT: "BUY_LIMIT",
                    mt5.ORDER_TYPE_SELL_LIMIT: "SELL_LIMIT",
                    mt5.ORDER_TYPE_BUY_STOP: "BUY_STOP",
                    mt5.ORDER_TYPE_SELL_STOP: "SELL_STOP",
                    mt5.ORDER_TYPE_BUY_STOP_LIMIT: "BUY_STOP_LIMIT",
                    mt5.ORDER_TYPE_SELL_STOP_LIMIT: "SELL_STOP_LIMIT"
                }
                order_type_name = order_type_map.get(order.type, f"TYPE_{order.type}")
                
                # Check if magic number matches authorized magic number
                if order_magic == authorized_magic_number:
                    print(f"      ✅ Pending #{order_ticket}: {order_type_name} {order_symbol} - AUTHORIZED (Magic: {order_magic})")
                    continue
                
                # UNAUTHORIZED - Magic number mismatch - MUST CANCEL
                print(f"      🚨 UNAUTHORIZED Pending #{order_ticket}: {order_type_name} {order_symbol}")
                print(f"         → Magic Number: {order_magic} (Expected: {authorized_magic_number})")
                print(f"         → Initiating IMMEDIATE CANCELLATION...")
                
                cancel_request = {
                    "action": mt5.TRADE_ACTION_REMOVE,
                    "order": order_ticket
                }
                
                try:
                    result = mt5.order_send(cancel_request)
                    
                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        print(f"         ✅ SUCCESS: Order #{order_ticket} CANCELLED")
                        investor_stats['pending_cancelled'] += 1
                        investor_stats['unauthorized_count'] += 1
                        
                        # Record cancellation in tradeshistory.json (for tracking)
                        cancellation_record = {
                            'timestamp': datetime.now().isoformat(),
                            'action': 'UNAUTHORIZED_ORDER_CANCELLED',
                            'ticket': order_ticket,
                            'symbol': order_symbol,
                            'type': order_type_name,
                            'magic_number': order_magic,
                            'expected_magic': authorized_magic_number,
                            'reason': f'Magic number mismatch: {order_magic} != {authorized_magic_number}'
                        }
                        closed_trades_for_tracking.append(cancellation_record)
                        
                    else:
                        error_msg = result.comment if result else "No response"
                        error_code = result.retcode if result else "Unknown"
                        print(f"          FAILED: Could not cancel #{order_ticket}")
                        print(f"            Error: {error_msg} (code: {error_code})")
                        investor_stats['errors'] += 1
                        
                except Exception as e:
                    print(f"          EXCEPTION: {e}")
                    investor_stats['errors'] += 1
        
        else:
            print(f"\n   ℹ️  No pending orders found")
        
        # ============================================================
        # STEP 2: SCAN ALL OPEN POSITIONS
        # ============================================================
        open_positions = mt5.positions_get()
        if open_positions:
            print(f"\n   💼 SCANNING OPEN POSITIONS (by Magic Number)...")
            investor_stats['positions_found'] = len(open_positions)
            
            for position in open_positions:
                pos_ticket = position.ticket
                pos_symbol = position.symbol
                pos_type = "BUY" if position.type == mt5.POSITION_TYPE_BUY else "SELL"
                pos_magic = position.magic
                current_profit = position.profit
                
                # Check if magic number matches authorized magic number
                if pos_magic == authorized_magic_number:
                    print(f"      ✅ Position #{pos_ticket}: {pos_type} {pos_symbol} - AUTHORIZED (Magic: {pos_magic})")
                    continue
                
                # UNAUTHORIZED - Magic number mismatch - MUST CLOSE
                print(f"      🚨 UNAUTHORIZED Position #{pos_ticket}: {pos_type} {pos_symbol}")
                print(f"         → Magic Number: {pos_magic} (Expected: {authorized_magic_number})")
                print(f"         → Current P&L: ${current_profit:.2f}")
                print(f"         → Initiating IMMEDIATE CLOSURE...")
                
                # Get current market price
                tick = mt5.symbol_info_tick(pos_symbol)
                if not tick:
                    print(f"          Cannot get price for {pos_symbol} - cannot close")
                    investor_stats['errors'] += 1
                    continue
                
                # Determine closing order type
                if position.type == mt5.POSITION_TYPE_BUY:
                    # Close BUY position by SELLING
                    close_type = mt5.ORDER_TYPE_SELL
                    close_price = tick.bid
                else:
                    # Close SELL position by BUYING
                    close_type = mt5.ORDER_TYPE_BUY
                    close_price = tick.ask
                
                close_request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": pos_symbol,
                    "volume": position.volume,
                    "type": close_type,
                    "position": pos_ticket,
                    "price": close_price,
                    "deviation": 20,
                    "magic": pos_magic,  # Keep original magic for tracking
                    "comment": f"UNAUTHORIZED - Magic {pos_magic} != {authorized_magic_number}",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                
                try:
                    result = mt5.order_send(close_request)
                    
                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        print(f"         ✅ SUCCESS: Position #{pos_ticket} CLOSED")
                        investor_stats['positions_closed'] += 1
                        investor_stats['unauthorized_count'] += 1
                        
                        # Record closure in tradeshistory.json (for tracking)
                        closure_record = {
                            'timestamp': datetime.now().isoformat(),
                            'action': 'UNAUTHORIZED_POSITION_CLOSED',
                            'ticket': pos_ticket,
                            'symbol': pos_symbol,
                            'type': pos_type,
                            'volume': position.volume,
                            'profit': current_profit,
                            'magic_number': pos_magic,
                            'expected_magic': authorized_magic_number,
                            'close_price': close_price,
                            'reason': f'Magic number mismatch: {pos_magic} != {authorized_magic_number}'
                        }
                        closed_trades_for_tracking.append(closure_record)
                        
                    else:
                        error_msg = result.comment if result else "No response"
                        error_code = result.retcode if result else "Unknown"
                        print(f"          FAILED: Could not close #{pos_ticket}")
                        print(f"            Error: {error_msg} (code: {error_code})")
                        
                        # Try alternative approach if first attempt fails
                        print(f"         🔄 Attempting alternative closure method...")
                        
                        alt_close_request = {
                            "action": mt5.TRADE_ACTION_DEAL,
                            "symbol": pos_symbol,
                            "volume": position.volume,
                            "type": close_type,
                            "position": pos_ticket,
                            "price": close_price,
                            "deviation": 50,  # Increased deviation
                            "comment": f"UNAUTHORIZED - Retry (Magic mismatch)",
                            "type_filling": mt5.ORDER_FILLING_RETURN,
                        }
                        
                        alt_result = mt5.order_send(alt_close_request)
                        
                        if alt_result and alt_result.retcode == mt5.TRADE_RETCODE_DONE:
                            print(f"         ✅ SUCCESS (alt): Position #{pos_ticket} CLOSED")
                            investor_stats['positions_closed'] += 1
                            investor_stats['unauthorized_count'] += 1
                            
                            # Record closure
                            closure_record['note'] = 'Closed via alternative method'
                            closed_trades_for_tracking.append(closure_record)
                        else:
                            alt_error = alt_result.comment if alt_result else "No response"
                            alt_code = alt_result.retcode if alt_result else "Unknown"
                            print(f"          Alternative also FAILED: {alt_error} (code: {alt_code})")
                            investor_stats['errors'] += 1
                        
                except Exception as e:
                    print(f"          EXCEPTION: {e}")
                    investor_stats['errors'] += 1
        
        else:
            print(f"\n   ℹ️  No open positions found")
        
        # ============================================================
        # UPDATE tradeshistory.json (FOR TRACKING ONLY)
        # ============================================================
        if closed_trades_for_tracking and history_path.exists():
            try:
                # Load existing history if available
                existing_history = []
                if history_path.exists():
                    with open(history_path, 'r', encoding='utf-8') as f:
                        existing_history = json.load(f)
                
                # Append new records
                updated_history = existing_history + closed_trades_for_tracking
                
                # Save back to file
                with open(history_path, 'w', encoding='utf-8') as f:
                    json.dump(updated_history, f, indent=4)
                
                print(f"\n   📝 Updated tradeshistory.json with {len(closed_trades_for_tracking)} enforcement actions")
            except Exception as e:
                print(f"\n   ⚠️ Could not update tradeshistory.json: {e}")
        
        # ============================================================
        # INVESTOR SUMMARY
        # ============================================================
        print(f"\n   📊 INVESTOR {user_brokerid} SUMMARY:")
        print(f"      • Authorized Magic Number: {investor_stats['authorized_magic_number']}")
        print(f"      • Pending orders found: {investor_stats['pending_orders_found']}")
        print(f"      • Open positions found: {investor_stats['positions_found']}")
        if investor_stats['pending_cancelled'] > 0:
            print(f"      •  Pending orders CANCELLED (unauthorized): {investor_stats['pending_cancelled']}")
        if investor_stats['positions_closed'] > 0:
            print(f"      •  Positions CLOSED (unauthorized): {investor_stats['positions_closed']}")
        if investor_stats['unauthorized_count'] > 0:
            print(f"      • 🚨 TOTAL UNAUTHORIZED: {investor_stats['unauthorized_count']}")
        if investor_stats['errors'] > 0:
            print(f"      •  Errors encountered: {investor_stats['errors']}")
        
        if investor_stats['unauthorized_count'] == 0:
            print(f"      • ✅ ALL ORDERS AUTHORIZED - Clean account (all have correct magic number)")
        
        # Update global stats
        global_stats['investors_processed'] += 1
        global_stats['total_pending_orders_found'] += investor_stats['pending_orders_found']
        global_stats['total_positions_found'] += investor_stats['positions_found']
        global_stats['total_pending_cancelled'] += investor_stats['pending_cancelled']
        global_stats['total_positions_closed'] += investor_stats['positions_closed']
        global_stats['total_unauthorized_found'] += investor_stats['unauthorized_count']
        global_stats['errors_encountered'] += investor_stats['errors']
        
        if investor_stats['unauthorized_count'] > 0:
            global_stats['investors_with_issues'] += 1
        
        # Shutdown MT5 connection
        mt5.shutdown()
    
    # ============================================================
    # FINAL GLOBAL SUMMARY
    # ============================================================
    print("\n" + "="*80)
    print("🏁 ENFORCEMENT COMPLETE - FINAL REPORT (MAGIC NUMBER STRATEGY)")
    print("="*80)
    print(f"   Investors processed: {global_stats['investors_processed']}")
    print(f"   Investors with unauthorized orders: {global_stats['investors_with_issues']}")
    print(f"\n   📊 TOTAL SCANNED:")
    print(f"      • Pending orders: {global_stats['total_pending_orders_found']}")
    print(f"      • Open positions: {global_stats['total_positions_found']}")
    print(f"\n   🔒 ENFORCEMENT ACTIONS:")
    print(f"      • Pending orders CANCELLED: {global_stats['total_pending_cancelled']}")
    print(f"      • Open positions CLOSED: {global_stats['total_positions_closed']}")
    print(f"      • TOTAL UNAUTHORIZED REMOVED: {global_stats['total_unauthorized_found']}")
    print(f"\n   📝 Errors: {global_stats['errors_encountered']}")
    
    if global_stats['total_unauthorized_found'] > 0:
        print(f"\n   ⚠️  WARNING: Unauthorized orders were found and terminated!")
        print(f"   💡 Unauthorized orders had magic numbers that didn't match")
        print(f"   💡 Expected format: LOGIN_ID + USER_ID")
        print(f"   💡 Run again to ensure all unauthorized orders are removed")
    else:
        print(f"\n   ✅ SUCCESS: All orders are authorized!")
        print(f"   ✅ Every order/position has the correct magic number")
        print(f"   ✅ No unauthorized orders found in any account")
    
    print("="*80 + "\n")
    
    return global_stats

def place_usd_orders(inv_id=None):
    
    # --- SUFFIX DICTIONARY FOR RETRY LOGIC ---
    SYMBOL_SUFFIXES = [
        "",      # Original symbol first
        "+",     # Common suffix for some brokers
        ".m",    # Micro accounts
        "pro",   # Pro accounts
        ".pro",  # Pro accounts with dot
        "c",     # Cent accounts
        ".c",    # Cent accounts with dot
        "fx",    # Forex suffix
        ".fx",   # Forex with dot
        "e",     # ECN accounts
        ".e",    # ECN with dot
        "std",   # Standard accounts
        ".std",  # Standard with dot
        "m",     # Mini accounts
        ".mini", # Mini accounts
        "micro", # Micro accounts
        ".micro", # Micro with dot
        "-",     # Dash suffix
        ".-",    # Dot dash
        "_",     # Underscore
        "._",    # Dot underscore
        "ecn",   # ECN suffix
        ".ecn",  # Dot ECN
        "real",  # Real account
        ".real", # Dot real
        "demo",  # Demo account
        ".demo"  # Dot demo
    ]
    
    # --- SUB-FUNCTION 1: LOAD PROXIMITY RISK SETTING FROM ACCOUNTMANAGEMENT.JSON ---
    def get_proximity_risk_setting(investor_root):
        """
        Load skip_orders_close_to_position setting from accountmanagement.json.
        Returns True if orders should be skipped when too close to positions.
        Returns False if orders should be placed regardless of proximity.
        Default: False (don't skip)
        """
        acc_mgmt_path = investor_root / "accountmanagement.json"
        
        if not acc_mgmt_path.exists():
            print(f"    ℹ️  No accountmanagement.json found - proximity risk check DISABLED")
            return False
        
        try:
            with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            settings = config.get("settings", {})
            skip_close = settings.get("skip_orders_close_to_position", False)
            
            if skip_close:
                print(f"     Proximity risk check ENABLED (skip_orders_close_to_position: true)")
                print(f"       - Orders too close to existing positions will be SKIPPED")
            else:
                print(f"    ✅ Proximity risk check DISABLED (skip_orders_close_to_position: false)")
                print(f"       - All orders will be placed regardless of proximity")
            
            return skip_close
            
        except Exception as e:
            print(f"     Error reading accountmanagement.json: {e}")
            print(f"       - Defaulting to proximity risk check DISABLED")
            return False
    
    # --- SUB-FUNCTION 2: LOAD INVALID ORDER CONVERSION SETTING ---
    def get_switch_invalid_setting(investor_root):
        """
        Load switch_invalid_to_instant_order setting from accountmanagement.json.
        Returns True if invalid stop orders should be converted to instant market orders.
        Returns False if invalid orders should be rejected.
        Default: False (don't convert)
        """
        acc_mgmt_path = investor_root / "accountmanagement.json"
        
        if not acc_mgmt_path.exists():
            print(f"    ℹ️  No accountmanagement.json found - invalid order conversion DISABLED")
            return False
        
        try:
            with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            settings = config.get("settings", {})
            switch_invalid = settings.get("switch_invalid_to_instant_order", False)
            
            if switch_invalid:
                print(f"    🔄 Invalid order conversion ENABLED (switch_invalid_to_instant_order: true)")
                print(f"       - Invalid BUY_STOP orders will convert to INSTANT_BUY")
                print(f"       - Invalid SELL_STOP orders will convert to INSTANT_SELL")
            else:
                print(f"    ℹ️  Invalid order conversion DISABLED (switch_invalid_to_instant_order: false)")
                print(f"       - Invalid stop orders will be REJECTED")
            
            return switch_invalid
            
        except Exception as e:
            print(f"     Error reading switch_invalid_to_instant setting: {e}")
            print(f"       - Defaulting to conversion DISABLED")
            return False
    
    # --- SUB-FUNCTION 3: REMOVE CANDLE TIME RECORD ON FAILURE ---
    def remove_candle_time_record(investor_root, symbol, timeframe, current_candle_time):
        """
        Remove a candle time record when order placement fails.
        This allows directional_bias to reprocess the same candle.
        """
        # Find the candle_time_records.json file in any strategy folder
        records_files = list(investor_root.rglob("candle_time_records.json"))
        
        if not records_files:
            print(f"        No candle_time_records.json found to remove record from")
            return False
        
        removed_count = 0
        
        for records_file in records_files:
            try:
                if not records_file.exists():
                    continue
                
                with open(records_file, 'r', encoding='utf-8') as f:
                    records = json.load(f)
                
                original_count = len(records)
                
                # Find and remove matching record
                filtered_records = []
                for record in records:
                    if (record.get('symbol') == symbol and 
                        record.get('timeframe') == timeframe and 
                        record.get('current_candle_time') == current_candle_time):
                        print(f"        🗑️ Removing candle time record: {symbol} [{timeframe}] @ {current_candle_time}")
                        removed_count += 1
                        continue  # Skip this record
                    filtered_records.append(record)
                
                if len(filtered_records) < original_count:
                    # Save updated records
                    with open(records_file, 'w', encoding='utf-8') as f:
                        json.dump(filtered_records, f, indent=4)
                    print(f"        ✅ Removed {original_count - len(filtered_records)} record(s) from {records_file.name}")
                else:
                    print(f"        ℹ️ No matching record found in {records_file.name}")
                    
            except Exception as e:
                print(f"        Error processing {records_file}: {e}")
        
        return removed_count > 0
    
    # --- SUB-FUNCTION 3B: REMOVE SIGNAL FROM LIMIT_ORDERS.JSON ---
    def remove_signal_from_limit_orders(limit_orders_path, signal_to_remove):
        """
        Remove a specific signal from limit_orders.json file.
        This prevents reprocessing failed signals.
        """
        try:
            if not limit_orders_path.exists():
                return False
            
            with open(limit_orders_path, 'r', encoding='utf-8') as f:
                signals = json.load(f)
            
            original_count = len(signals)
            
            # Find and remove the matching signal
            filtered_signals = []
            for signal in signals:
                # Match by symbol, order_type, entry, and current_candle_time
                if (signal.get('symbol') == signal_to_remove.get('symbol') and
                    signal.get('order_type') == signal_to_remove.get('order_type') and
                    signal.get('entry') == signal_to_remove.get('entry') and
                    signal.get('current_candle_time') == signal_to_remove.get('current_candle_time')):
                    print(f"        🗑️ Removing failed signal from limit_orders.json")
                    continue
                filtered_signals.append(signal)
            
            if len(filtered_signals) < original_count:
                with open(limit_orders_path, 'w', encoding='utf-8') as f:
                    json.dump(filtered_signals, f, indent=4)
                print(f"        ✅ Removed {original_count - len(filtered_signals)} signal(s) from limit_orders.json")
                return True
            else:
                print(f"        ℹ️ No matching signal found in limit_orders.json")
                return False
                
        except Exception as e:
            print(f"        Error removing signal from limit_orders.json: {e}")
            return False
    
    # --- SUB-FUNCTION 4: CHECK AUTHORIZATION STATUS ---
    def check_authorization_status_old(investor_root):
        """Check activities.json for unauthorized actions and bypass status"""
        activities_path = investor_root / "activities.json"
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
                    print(f"     Unauthorized actions detected but BYPASS ACTIVE - proceeding")
                    return True, activities
                else:
                    print(f"    🚫 Unauthorized actions detected - ORDER PLACEMENT BLOCKED")
                    if not bypass_active: print(f"       - Bypass restriction: DISABLED")
                    if not autotrading_active: print(f"       - Auto-trading: DISABLED")
                    return False, activities
            print(f"    ✅ No unauthorized actions detected - proceeding")
            return True, activities
        except Exception as e:
            print(f"     Error reading activities.json: {e}")
            return True, None
    
    # --- SUB-FUNCTION 4: CHECK AUTHORIZATION STATUS & GET MAGIC NUMBER ---
    def check_authorization_status(investor_root, login_id=None, user_id=None):
        """
        Check activities.json for unauthorized actions and bypass status.
        Also constructs and returns the authorized magic number.
        
        Returns:
            tuple: (can_proceed, activities, authorized_magic_number)
        """
        activities_path = investor_root / "activities.json"
        
        # Construct magic number from login_id and user_id if provided
        authorized_magic_number = None
        if login_id is not None and user_id is not None:
            try:
                authorized_magic_number = int(str(login_id) + str(user_id))
                print(f"    🔑 Authorized Magic Number: {authorized_magic_number}")
            except (ValueError, TypeError):
                print(f"    ⚠️ Could not create magic number from LOGIN_ID={login_id} and USER_ID={user_id}")
        
        if not activities_path.exists():
            print(f"    ✅ No activities.json found - proceeding with order placement")
            return True, None, authorized_magic_number
        
        try:
            with open(activities_path, 'r', encoding='utf-8') as f:
                activities = json.load(f)
            unauthorized_detected = activities.get('unauthorized_action_detected', False)
            bypass_active = activities.get('bypass_restriction', False)
            autotrading_active = activities.get('activate_autotrading', False)
            
            # Also try to get magic number from activities if not provided
            if authorized_magic_number is None:
                authorized_magic_number = activities.get('authorized_magic_number')
            
            if unauthorized_detected:
                if bypass_active and autotrading_active:
                    print(f"     Unauthorized actions detected but BYPASS ACTIVE - proceeding")
                    return True, activities, authorized_magic_number
                else:
                    print(f"    🚫 Unauthorized actions detected - ORDER PLACEMENT BLOCKED")
                    if not bypass_active: print(f"       - Bypass restriction: DISABLED")
                    if not autotrading_active: print(f"       - Auto-trading: DISABLED")
                    return False, activities, authorized_magic_number
            print(f"    ✅ No unauthorized actions detected - proceeding")
            return True, activities, authorized_magic_number
        except Exception as e:
            print(f"     Error reading activities.json: {e}")
            return True, None, authorized_magic_number
    
    # --- SUB-FUNCTION 5: GET ORDER TYPE CONSTANTS ---
    def get_mt5_order_type(order_type_str):
        """Convert order type string to MT5 constant"""
        order_type_map = {
            'buy_stop': mt5.ORDER_TYPE_BUY_STOP,
            'sell_stop': mt5.ORDER_TYPE_SELL_STOP,
            'buy_limit': mt5.ORDER_TYPE_BUY_LIMIT,
            'sell_limit': mt5.ORDER_TYPE_SELL_LIMIT,
            'instant_buy': mt5.ORDER_TYPE_BUY,
            'instant_sell': mt5.ORDER_TYPE_SELL
        }
        return order_type_map.get(order_type_str.lower())

    # --- SUB-FUNCTION 6: GET VOLUME FROM SIGNAL ---
    def get_volume_from_signal(order_data):
        """
        Extract volume from signal data dynamically.
        Looks for any field ending with '_volume' (e.g., deriv_volume, bybit_volume, a_volume, etc.)
        Returns None if no volume field is found (caller must handle).
        """
        # Look for any field ending with '_volume' (anonymous/dynamic broker prefix)
        for key, value in order_data.items():
            if key.endswith('_volume'):
                try:
                    return float(value)
                except (ValueError, TypeError):
                    continue
        
        # No volume field found
        return None
   
    # --- SUB-FUNCTION 7: CHECK PROXIMITY RISK ---
    def check_proximity_risk(order, existing_positions):
        """
        Check if order is too close to existing positions using risk-based calculation.
        Returns (is_risk, closest_position, risk_amount, threshold)
        """
        symbol = order.get('symbol')
        order_type = order.get('order_type', '').lower()
        entry_price = float(order.get('entry', 0))
        volume = get_volume_from_signal(order)
        
        is_buy = 'buy' in order_type
        is_sell = 'sell' in order_type
        
        if not is_buy and not is_sell:
            return False, None, 0, 0
        
        # Filter positions for this symbol (exact match, including suffixes)
        symbol_positions = [p for p in existing_positions if p.symbol == symbol]
        if not symbol_positions:
            return False, None, 0, 0
        
        for position in symbol_positions:
            position_type = position.type
            position_entry = position.price_open
            position_volume = position.volume
            position_sl = position.sl
            position_ticket = position.ticket
            
            is_position_buy = (position_type == mt5.ORDER_TYPE_BUY)
            is_position_sell = (position_type == mt5.ORDER_TYPE_SELL)
            
            # Calculate position risk from SL
            position_risk = 0
            if position_sl and position_sl > 0:
                if is_position_buy:
                    risk_profit = mt5.order_calc_profit(
                        mt5.ORDER_TYPE_BUY, symbol, position_volume,
                        position_entry, position_sl
                    )
                else:
                    risk_profit = mt5.order_calc_profit(
                        mt5.ORDER_TYPE_SELL, symbol, position_volume,
                        position_entry, position_sl
                    )
                if risk_profit:
                    position_risk = abs(risk_profit)
            
            if position_risk == 0:
                continue
            
            risk_threshold = position_risk / 2  # 50% threshold
            
            # SAME DIRECTION CHECK
            if (is_buy and is_position_buy) or (is_sell and is_position_sell):
                # Calculate potential risk if order triggers
                if is_sell and is_position_sell:
                    if entry_price < position_entry:
                        potential_risk = abs(mt5.order_calc_profit(
                            mt5.ORDER_TYPE_SELL, symbol, min(volume, position_volume),
                            entry_price, position_entry
                        ) or 0)
                    else:
                        potential_risk = abs(mt5.order_calc_profit(
                            mt5.ORDER_TYPE_SELL, symbol, min(volume, position_volume),
                            position_entry, entry_price
                        ) or 0)
                elif is_buy and is_position_buy:
                    if entry_price > position_entry:
                        potential_risk = abs(mt5.order_calc_profit(
                            mt5.ORDER_TYPE_BUY, symbol, min(volume, position_volume),
                            position_entry, entry_price
                        ) or 0)
                    else:
                        potential_risk = abs(mt5.order_calc_profit(
                            mt5.ORDER_TYPE_BUY, symbol, min(volume, position_volume),
                            entry_price, position_entry
                        ) or 0)
                else:
                    continue
                
                if potential_risk and potential_risk < risk_threshold:
                    return True, position, potential_risk, risk_threshold
            
            # OPPOSITE DIRECTION CHECK
            elif (is_buy and is_position_sell) or (is_sell and is_position_buy):
                if is_buy and is_position_sell:
                    if entry_price > position_entry:
                        potential_risk = abs(mt5.order_calc_profit(
                            mt5.ORDER_TYPE_SELL, symbol, min(volume, position_volume),
                            position_entry, entry_price
                        ) or 0)
                    else:
                        potential_risk = abs(mt5.order_calc_profit(
                            mt5.ORDER_TYPE_BUY, symbol, min(volume, position_volume),
                            entry_price, position_entry
                        ) or 0)
                elif is_sell and is_position_buy:
                    if entry_price < position_entry:
                        potential_risk = abs(mt5.order_calc_profit(
                            mt5.ORDER_TYPE_SELL, symbol, min(volume, position_volume),
                            entry_price, position_entry
                        ) or 0)
                    else:
                        potential_risk = abs(mt5.order_calc_profit(
                            mt5.ORDER_TYPE_BUY, symbol, min(volume, position_volume),
                            position_entry, entry_price
                        ) or 0)
                else:
                    continue
                
                if potential_risk and potential_risk < risk_threshold:
                    return True, position, potential_risk, risk_threshold
        
        return False, None, 0, 0

    # --- SUB-FUNCTION 9: CURRENT PENDING ORDERS AND POSITIONS SNAPSHOT ---
    def update_orders_status_in_tradeshistory(investor_root):
        """
        Checks MT5 for current pending orders and open positions.
        Records them in tradeshistory.json as a "current_orders" entry within the array.
        Does NOT include closed orders or historical deals.
        """
        def get_current_orders_from_mt5():
            """Fetch current pending orders and open positions from MT5."""
            pending_orders = []
            open_positions = []
            
            # Get all pending orders
            orders = mt5.orders_get()
            if orders:
                for order in orders:
                    order_dict = {
                        'ticket': order.ticket,
                        'symbol': order.symbol,
                        'type': order.type,
                        'type_name': get_order_type_name(order.type),
                        'volume_initial': order.volume_initial,
                        'volume_current': order.volume_current,
                        'price_open': order.price_open,
                        'sl': order.sl,
                        'tp': order.tp,
                        'magic': order.magic,
                        'comment': order.comment,
                        'time_setup': datetime.fromtimestamp(order.time_setup).strftime('%Y-%m-%d %H:%M:%S')
                    }
                    pending_orders.append(order_dict)
            
            # Get all open positions
            positions = mt5.positions_get()
            if positions:
                for pos in positions:
                    position_dict = {
                        'ticket': pos.ticket,
                        'symbol': pos.symbol,
                        'type': pos.type,
                        'type_name': get_position_type_name(pos.type),
                        'volume': pos.volume,
                        'price_open': pos.price_open,
                        'price_current': pos.price_current,
                        'sl': pos.sl,
                        'tp': pos.tp,
                        'magic': pos.magic,
                        'comment': pos.comment,
                        'time_open': datetime.fromtimestamp(pos.time).strftime('%Y-%m-%d %H:%M:%S'),
                        'profit': pos.profit,
                        'swap': pos.swap if hasattr(pos, 'swap') else 0,
                        'commission': pos.commission if hasattr(pos, 'commission') else 0
                    }
                    open_positions.append(position_dict)
            
            return pending_orders, open_positions
        
        def get_order_type_name(order_type):
            type_names = {
                mt5.ORDER_TYPE_BUY: 'BUY',
                mt5.ORDER_TYPE_SELL: 'SELL',
                mt5.ORDER_TYPE_BUY_LIMIT: 'BUY_LIMIT',
                mt5.ORDER_TYPE_SELL_LIMIT: 'SELL_LIMIT',
                mt5.ORDER_TYPE_BUY_STOP: 'BUY_STOP',
                mt5.ORDER_TYPE_SELL_STOP: 'SELL_STOP'
            }
            return type_names.get(order_type, f'UNKNOWN_{order_type}')
        
        def get_position_type_name(pos_type):
            type_names = {
                mt5.POSITION_TYPE_BUY: 'BUY',
                mt5.POSITION_TYPE_SELL: 'SELL'
            }
            return type_names.get(pos_type, f'UNKNOWN_{pos_type}')
        
        def check_existing_ticket(history, ticket, ticket_type):
            """Check if a ticket already exists in the current_orders snapshot."""
            for item in history:
                if isinstance(item, dict) and "current_orders" in item:
                    current_orders = item["current_orders"]
                    
                    # Check in pending orders
                    for order in current_orders.get("pending_orders", []):
                        if order.get("ticket") == ticket:
                            return True, "pending_order"
                    
                    # Check in open positions
                    for position in current_orders.get("open_positions", []):
                        if position.get("ticket") == ticket:
                            return True, "open_position"
            return False, None
        
        print(f"    📊 Taking current orders & positions snapshot...")
        
        # Read existing tradeshistory.json first to check for duplicates
        history_path = investor_root / "tradeshistory.json"
        history = []
        
        if history_path.exists():
            try:
                with open(history_path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            except Exception as e:
                print(f"     Error reading tradeshistory.json: {e}")
                history = []
        
        # Fetch current state from MT5
        pending_orders, open_positions = get_current_orders_from_mt5()
        
        # Create sets of active tickets for quick lookup
        active_pending_tickets = {order['ticket'] for order in pending_orders}
        active_position_tickets = {pos['ticket'] for pos in open_positions}
        
        print(f"    📋 Found: {len(pending_orders)} pending orders, {len(open_positions)} open positions")
        
        # Update status for existing records in history (not just current_orders)
        print(f"    🔄 Updating status for existing records...")
        
        # Iterate through all items in history to update status
        for item in history:
            if isinstance(item, dict):
                # Skip the current_orders entry for now, handle separately
                if "current_orders" in item:
                    continue
                
                ticket = item.get("ticket")
                if ticket:
                    if ticket in active_pending_tickets:
                        if item.get("status") != "pending":
                            item["status"] = "pending"
                            print(f"       - Ticket {ticket}: status updated to 'pending'")
                    elif ticket in active_position_tickets:
                        if item.get("status") != "running_position":
                            item["status"] = "running_position"
                            print(f"       - Ticket {ticket}: status updated to 'running_position'")
                    else:
                        if item.get("status") != "closed":
                            item["status"] = "closed"
                            print(f"       - Ticket {ticket}: status updated to 'closed'")
        
        # Check pending orders
        if pending_orders:
            print(f"    🎫 Pending Orders Tickets:")
            for order in pending_orders:
                ticket = order['ticket']
                exists, location = check_existing_ticket(history, ticket, "pending")
                if exists:
                    print(f"       - Ticket {ticket} ({order['type_name']}) - ✅ EXISTS! (in {location})")
                else:
                    print(f"       - Ticket {ticket} ({order['type_name']}) - 🆕 New")
        
        # Check open positions
        if open_positions:
            print(f"    💼 Open Positions Tickets:")
            for position in open_positions:
                ticket = position['ticket']
                exists, location = check_existing_ticket(history, ticket, "position")
                if exists:
                    print(f"       - Ticket {ticket} ({position['type_name']}) - ✅ EXISTS! (in {location})")
                else:
                    print(f"       - Ticket {ticket} ({position['type_name']}) - 🆕 New")
        
        # Prepare current_orders data
        current_orders_data = {
            'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'pending_orders': pending_orders,
            'open_positions': open_positions
        }
        
        # Remove any existing "current_orders" entry
        history = [item for item in history if not isinstance(item, dict) or "current_orders" not in item]
        
        # Append the new current_orders entry
        history.append({"current_orders": current_orders_data})
        
        # Save back to file
        try:
            with open(history_path, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=4)
            
            print(f"    ✅ Saved current orders snapshot to tradeshistory.json")
            print(f"       - Pending orders: {len(pending_orders)}")
            print(f"       - Open positions: {len(open_positions)}")
            
            return True, {
                'pending_orders': len(pending_orders),
                'open_positions': len(open_positions)
            }
            
        except Exception as e:
            print(f"     Error saving tradeshistory.json: {e}")
            return False, None

    # --- SUB-FUNCTION 10: SYNC & SAVE DETAILED HISTORY WITH RUNNING POSITION TRACKING ---
    def syncing_orders_and_pnl_details(investor_root, new_trade=None, original_signal_fields=None):
        """
        Synchronizes tradeshistory.json with MT5 terminal.
        Stores COMPLETE order information including all signal fields.
        Tracks running positions with unique IDs.
        
        NOTE: Status updates are now handled by update_orders_status_in_tradeshistory().
        This function ONLY adds new trades, assigns position IDs, and updates position details.
        It does NOT change the status of existing trades.
        """
        try:
            history_path = investor_root / "tradeshistory.json"
            
            print(f"      📂 Tradeshistory path: {history_path}")
            
            history = []
            if history_path.exists():
                try:
                    with open(history_path, 'r', encoding='utf-8') as f:
                        history = json.load(f)
                    print(f"      📋 Loaded {len(history)} existing trades")
                except Exception as e:
                    print(f"       Error reading tradeshistory.json: {e}")
                    history = []

            # ========== Get CURRENT state for new trade and position ID assignment ==========
            # Get current pending orders directly from MT5
            active_orders = {}
            orders = mt5.orders_get()
            if orders:
                for order in orders:
                    active_orders[order.ticket] = order
            
            # Get current open positions directly from MT5
            active_positions = {}
            positions = mt5.positions_get()
            if positions:
                for pos in positions:
                    active_positions[pos.ticket] = pos
            
            print(f"      📊 MT5 Current State: {len(active_orders)} pending orders, {len(active_positions)} open positions")
            
            # ========== Build order-to-position mapping for reference ==========
            order_to_position_map = {}
            
            if positions:
                for pos in positions:
                    pos_ticket = pos.ticket
                    
                    # Method 1: Direct match (some brokers reuse ticket)
                    if pos_ticket in active_orders:
                        order_to_position_map[pos_ticket] = pos_ticket
                    
                    # Method 2: Query history orders to find the order that created this position
                    from_date = datetime.now() - timedelta(days=7)
                    history_orders = mt5.history_orders_get(from_date, datetime.now())
                    
                    if history_orders:
                        for hist_order in history_orders:
                            if hasattr(hist_order, 'position_id') and hist_order.position_id == pos_ticket:
                                order_to_position_map[hist_order.ticket] = pos_ticket
                                break
                            if hasattr(hist_order, 'position_by_id') and hist_order.position_by_id == pos_ticket:
                                order_to_position_map[hist_order.ticket] = pos_ticket
                                break
            
            print(f"      🔗 Order-to-Position mapping: {len(order_to_position_map)} links found")
            
            # Track next position ID
            position_counter = 1
            # Filter out non-dict entries and current_orders snapshots
            # FIX: Only process dictionary items, skip strings or other types
            valid_trades = []
            for t in history:
                if isinstance(t, dict) and 'current_orders' not in t:
                    valid_trades.append(t)
            
            existing_position_ids = [t.get('position_id') for t in valid_trades if t.get('position_id')]
            if existing_position_ids:
                max_id = 0
                for pid in existing_position_ids:
                    if pid and str(pid).startswith('POS_'):
                        try:
                            num = int(str(pid).split('_')[1])
                            max_id = max(max_id, num)
                        except (IndexError, ValueError):
                            pass
                position_counter = max_id + 1
            
            # ========== Add new trade if provided ==========
            if new_trade:
                existing_ticket = any(t.get('ticket') == new_trade.get('ticket') for t in valid_trades if isinstance(t, dict))
                if not existing_ticket:
                    # Preserve ALL original signal fields
                    complete_trade_record = new_trade.copy()
                    
                    # Add any additional fields from original signal
                    if original_signal_fields:
                        for key, value in original_signal_fields.items():
                            if key not in complete_trade_record:
                                complete_trade_record[key] = value
                    
                    # Set initial status based on CURRENT MT5 state (ONLY for NEW trades)
                    order_ticket = new_trade.get('ticket')
                    
                    if order_ticket in active_orders:
                        complete_trade_record['status'] = 'pending'
                    elif order_ticket in active_positions:
                        complete_trade_record['status'] = 'running_position'
                        if not complete_trade_record.get('position_id'):
                            complete_trade_record['position_id'] = f"POS_{position_counter}"
                            position_counter += 1
                    elif order_ticket in order_to_position_map:
                        position_ticket = order_to_position_map[order_ticket]
                        if position_ticket in active_positions:
                            complete_trade_record['status'] = 'running_position'
                            if not complete_trade_record.get('position_id'):
                                complete_trade_record['position_id'] = f"POS_{position_counter}"
                                position_counter += 1
                            complete_trade_record['position_ticket'] = position_ticket
                    else:
                        complete_trade_record['status'] = 'pending'  # Default for new orders
                    
                    history.append(complete_trade_record)
                    print(f"      ➕ Added new trade: Ticket {new_trade.get('ticket')} with status '{complete_trade_record.get('status')}'")
                else:
                    print(f"      ℹ️  Trade Ticket {new_trade.get('ticket')} already exists")

            # ========== FRESH FETCH for updating existing records (position details only, NO status changes) ==========
            # Re-fetch current state to ensure we have the absolute latest data
            fresh_active_positions = {}
            fresh_positions = mt5.positions_get()
            if fresh_positions:
                for pos in fresh_positions:
                    fresh_active_positions[pos.ticket] = pos
            
            # Rebuild order-to-position mapping with fresh data
            fresh_order_to_position_map = {}
            if fresh_positions:
                for pos in fresh_positions:
                    pos_ticket = pos.ticket
                    if pos_ticket in active_orders:
                        fresh_order_to_position_map[pos_ticket] = pos_ticket
                    
                    from_date = datetime.now() - timedelta(days=7)
                    history_orders = mt5.history_orders_get(from_date, datetime.now())
                    if history_orders:
                        for hist_order in history_orders:
                            if hasattr(hist_order, 'position_id') and hist_order.position_id == pos_ticket:
                                fresh_order_to_position_map[hist_order.ticket] = pos_ticket
                                break
                            if hasattr(hist_order, 'position_by_id') and hist_order.position_by_id == pos_ticket:
                                fresh_order_to_position_map[hist_order.ticket] = pos_ticket
                                break
            
            # Also get history deals for closure data (profit/commission/swap)
            from_date = datetime.now() - timedelta(days=7)
            history_deals = mt5.history_deals_get(from_date, datetime.now()) or []
            
            # Build deal lookup by order ticket and position ticket
            deals_by_order = {}
            deals_by_position = {}
            for deal in history_deals:
                if hasattr(deal, 'order') and deal.order:
                    if deal.order not in deals_by_order:
                        deals_by_order[deal.order] = []
                    deals_by_order[deal.order].append(deal)
                if hasattr(deal, 'position_id') and deal.position_id:
                    if deal.position_id not in deals_by_position:
                        deals_by_position[deal.position_id] = []
                    deals_by_position[deal.position_id].append(deal)
            
            # ========== Update existing records (position details, IDs, P&L - NO STATUS CHANGES) ==========
            updated_count = 0
                
            # FIX: Only iterate through items that are dictionaries
            for idx, trade in enumerate(history):
                # Skip non-dictionary entries (like strings) and current_orders snapshots
                if not isinstance(trade, dict):
                    continue
                if 'current_orders' in trade:
                    continue
                    
                ticket = trade.get('ticket')
                if not ticket:
                    continue
                
                needs_update = False
                
                # ========== ONLY update position details for running positions ==========
                # We do NOT change the status field - that's handled by update_orders_status_in_tradeshistory()
                
                # Check if this ticket is currently an open position (Direct match)
                if ticket in fresh_active_positions:
                    position = fresh_active_positions[ticket]
                    
                    # Assign position ID if not already assigned
                    if not trade.get('position_id'):
                        trade['position_id'] = f"POS_{position_counter}"
                        position_counter += 1
                        needs_update = True
                        print(f"      🆔 Assigned position ID {trade['position_id']} to ticket {ticket}")
                    
                    # Update position details (prices, profits, etc.)
                    trade['current_price'] = position.price_current
                    trade['current_profit'] = position.profit
                    trade['open_time'] = datetime.fromtimestamp(position.time).strftime('%Y-%m-%d %H:%M:%S')
                    trade['open_price'] = position.price_open
                    trade['volume_current'] = position.volume
                    trade['current_swap'] = position.swap if hasattr(position, 'swap') else 0
                    trade['position_ticket'] = position.ticket
                    
                    if hasattr(position, 'commission'):
                        trade['current_commission'] = position.commission
                    
                    needs_update = True
                    
                # Check if this ticket is mapped to an active position
                elif ticket in fresh_order_to_position_map:
                    position_ticket = fresh_order_to_position_map[ticket]
                    if position_ticket in fresh_active_positions:
                        position = fresh_active_positions[position_ticket]
                        
                        # Assign position ID if not already assigned
                        if not trade.get('position_id'):
                            trade['position_id'] = f"POS_{position_counter}"
                            position_counter += 1
                            needs_update = True
                            print(f"      🆔 Assigned position ID {trade['position_id']} to ticket {ticket} (position: {position_ticket})")
                        
                        # Update position details
                        trade['current_price'] = position.price_current
                        trade['current_profit'] = position.profit
                        trade['open_time'] = datetime.fromtimestamp(position.time).strftime('%Y-%m-%d %H:%M:%S')
                        trade['open_price'] = position.price_open
                        trade['volume_current'] = position.volume
                        trade['current_swap'] = position.swap if hasattr(position, 'swap') else 0
                        trade['position_ticket'] = position_ticket
                        
                        if hasattr(position, 'commission'):
                            trade['current_commission'] = position.commission
                        
                        needs_update = True
                
                # ========== Update closed position P&L data (but NOT the status) ==========
                # Only update financial data for positions that already have 'closed' status
                if trade.get('status') == 'closed':
                    # Check deals by order ticket
                    related_deals = deals_by_order.get(ticket, [])
                    
                    # Also check deals by position ticket (if we have one stored)
                    position_ticket = trade.get('position_ticket')
                    if position_ticket and position_ticket in deals_by_position:
                        related_deals.extend(deals_by_position[position_ticket])
                    
                    if related_deals:
                        # Calculate totals from deals
                        total_profit = 0
                        total_commission = 0
                        total_swap = 0
                        close_price = None
                        close_time = None
                        close_reason = None
                        
                        for deal in related_deals:
                            if hasattr(deal, 'profit'):
                                total_profit += deal.profit
                            if hasattr(deal, 'commission'):
                                total_commission += deal.commission
                            if hasattr(deal, 'swap'):
                                total_swap += deal.swap
                            if hasattr(deal, 'price') and deal.price > 0:
                                close_price = deal.price
                                close_time = datetime.fromtimestamp(deal.time).strftime('%Y-%m-%d %H:%M:%S')
                            if hasattr(deal, 'comment') and deal.comment:
                                close_reason = deal.comment
                        
                        # Update financial data if changed
                        current_profit = trade.get('profit', 0)
                        current_commission = trade.get('commission', 0)
                        current_swap = trade.get('swap', 0)
                        
                        if (current_profit != total_profit or 
                            current_commission != total_commission or 
                            current_swap != total_swap):
                            
                            trade['profit'] = total_profit
                            trade['commission'] = total_commission
                            trade['swap'] = total_swap
                            trade['total_pnl'] = total_profit + total_commission + total_swap
                            
                            if close_price and not trade.get('close_price'):
                                trade['close_price'] = close_price
                            if close_time and not trade.get('close_time'):
                                trade['close_time'] = close_time
                            if close_reason and not trade.get('close_reason'):
                                trade['close_reason'] = close_reason
                            
                            needs_update = True
                
                if needs_update:
                    updated_count += 1
            
            # Second pass: ensure all running positions have position_id
            for trade in history:
                if isinstance(trade, dict) and 'current_orders' not in trade:
                    if trade.get('status') == 'running_position' and not trade.get('position_id'):
                        trade['position_id'] = f"POS_{position_counter}"
                        position_counter += 1
                        updated_count += 1
                        print(f"      🆔 Assigned position ID {trade['position_id']} to running position ticket {trade.get('ticket')}")
            
            # Third pass: calculate total P&L for closed positions if not already calculated
            for trade in history:
                if isinstance(trade, dict) and 'current_orders' not in trade:
                    if trade.get('status') == 'closed' and 'total_pnl' not in trade:
                        profit = trade.get('profit', 0)
                        commission = trade.get('commission', 0)
                        swap = trade.get('swap', 0)
                        trade['total_pnl'] = profit + commission + swap
                        updated_count += 1

            # Save updated history
            with open(history_path, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=4)
            
            if new_trade:
                print(f"      ✅ Saved new trade to tradeshistory.json")
            elif updated_count > 0:
                print(f"      ✅ Updated {updated_count} trades in tradeshistory.json (position details, IDs, P&L)")
            else:
                print(f"      ✅ No updates needed")
            
            
            # Return statistics (counts based on CURRENT statuses)
            running_count = sum(1 for t in history if isinstance(t, dict) and 'current_orders' not in t and t.get('status') == 'running_position')
            pending_count = sum(1 for t in history if isinstance(t, dict) and 'current_orders' not in t and t.get('status') == 'pending')
            closed_count = sum(1 for t in history if isinstance(t, dict) and 'current_orders' not in t and t.get('status') == 'closed')
            
            print(f"      📊 Current status counts: {running_count} running, {pending_count} pending, {closed_count} closed")
            
            return True, {
                'running_positions': running_count,
                'pending_orders': pending_count,
                'closed_trades': closed_count,
                'last_position_id': position_counter - 1
            }
            
        except Exception as e:
            print(f"       Error in sync_and_save_history: {e}")
            import traceback
            traceback.print_exc()
            return False, None
    
    # --- SUB-FUNCTION 11: CHECK IF SYMBOL IS TRADEABLE ---
    def is_symbol_tradeable_old(symbol):
        """
        Check if a symbol exists AND trading is enabled (CASE-INSENSITIVE).
        Returns True if tradeable, False otherwise.
        """
        # First try direct lookup (case-sensitive)
        symbol_info = mt5.symbol_info(symbol)
        
        # If direct lookup fails, try case-insensitive lookup
        if symbol_info is None:
            # Get all symbols from MT5
            all_symbols = mt5.symbols_get()
            if all_symbols:
                # Create case-insensitive mapping
                symbols_lower_map = {s.name.lower(): s.name for s in all_symbols}
                symbol_lower = symbol.lower()
                
                if symbol_lower in symbols_lower_map:
                    correct_symbol = symbols_lower_map[symbol_lower]
                    if correct_symbol != symbol:
                        print(f"          🔧 Case correction: '{symbol}' → '{correct_symbol}'")
                    symbol_info = mt5.symbol_info(correct_symbol)
                    
                    # Also try to select the correct symbol
                    if symbol_info:
                        mt5.symbol_select(correct_symbol, True)
        
        if symbol_info is None:
            return False
        
        # Check if trading is enabled
        if hasattr(symbol_info, 'trade_mode') and symbol_info.trade_mode == 0:
            return False
        
        # Check contract size
        if hasattr(symbol_info, 'trade_contract_size') and symbol_info.trade_contract_size <= 0:
            return False
        
        # Check if we can get a valid tick
        tick = mt5.symbol_info_tick(symbol_info.name)  # Use the correct symbol name
        if tick is None or (tick.ask == 0 and tick.bid == 0):
            return False
        
        return True

    # --- SUB-FUNCTION 12: FIND TRADEABLE SYMBOL WITH SUFFIX RETRY ---
    def find_tradeable_symbol_with_retry_old(base_symbol, resolution_cache):
        """
        Try ALL suffixes one after another until a tradeable symbol is found.
        Now with CASE-INSENSITIVE matching.
        Returns (tradeable_symbol, used_suffix) or (None, None) if none found.
        """
        # Check cache first
        cache_key = f"tradeable_{base_symbol.lower()}"  # Use lowercase for cache key
        if cache_key in resolution_cache:
            cached_result = resolution_cache[cache_key]
            if cached_result is None:
                return None, None
            return cached_result, resolution_cache.get(f"suffix_{base_symbol.lower()}", "")
        
        print(f"        🔍 Searching for tradeable symbol for '{base_symbol}'...")
        
        # Try each suffix in order
        for idx, suffix in enumerate(SYMBOL_SUFFIXES):
            test_symbol = base_symbol + suffix if suffix else base_symbol
            
            # Skip if we already know this exact symbol is not tradeable
            symbol_cache_key = f"checked_{test_symbol.lower()}"  # Use lowercase for cache
            if symbol_cache_key in resolution_cache and not resolution_cache[symbol_cache_key]:
                continue
            
            print(f"          Trying: {test_symbol} (suffix {idx+1}/{len(SYMBOL_SUFFIXES)})")
            
            # Check if this symbol is tradeable (case-insensitive)
            if is_symbol_tradeable(test_symbol):
                # Get the actual symbol name from MT5 (with correct case)
                actual_symbol = None
                all_symbols = mt5.symbols_get()
                if all_symbols:
                    symbols_lower_map = {s.name.lower(): s.name for s in all_symbols}
                    test_lower = test_symbol.lower()
                    if test_lower in symbols_lower_map:
                        actual_symbol = symbols_lower_map[test_lower]
                
                if actual_symbol:
                    print(f"          ✅ SUCCESS! {actual_symbol} IS TRADEABLE!")
                    resolution_cache[cache_key] = actual_symbol
                    resolution_cache[f"suffix_{base_symbol.lower()}"] = suffix
                    resolution_cache[symbol_cache_key] = True
                    return actual_symbol, suffix
                else:
                    print(f"          ✅ SUCCESS! {test_symbol} IS TRADEABLE!")
                    resolution_cache[cache_key] = test_symbol
                    resolution_cache[f"suffix_{base_symbol.lower()}"] = suffix
                    resolution_cache[symbol_cache_key] = True
                    return test_symbol, suffix
            else:
                resolution_cache[symbol_cache_key] = False
        
        # No tradeable symbol found
        print(f"         FAILED: No tradeable symbol found for '{base_symbol}' after trying {len(SYMBOL_SUFFIXES)} suffixes")
        resolution_cache[cache_key] = None
        return None, None
    

    def is_symbol_tradeable(symbol):
        """
        Check if a symbol exists AND trading is enabled (CASE-INSENSITIVE).
        Returns True if tradeable, False otherwise.
        FIXED: Uses the same working approach as fetch_ohlc_data_for_investor
        """
        # First try to select the symbol (this often resolves case issues)
        selected = False
        for attempt in range(3):
            if mt5.symbol_select(symbol, True):
                selected = True
                break
            time.sleep(0.1)
        
        if not selected:
            # Try case-insensitive lookup
            all_symbols = mt5.symbols_get()
            if all_symbols:
                symbols_lower_map = {s.name.lower(): s.name for s in all_symbols}
                symbol_lower = symbol.lower()
                
                if symbol_lower in symbols_lower_map:
                    correct_symbol = symbols_lower_map[symbol_lower]
                    if correct_symbol != symbol:
                        print(f"          🔧 Case correction: '{symbol}' → '{correct_symbol}'")
                    # Try to select the correctly cased symbol
                    for attempt in range(3):
                        if mt5.symbol_select(correct_symbol, True):
                            selected = True
                            symbol = correct_symbol
                            break
                        time.sleep(0.1)
        
        if not selected:
            return False
        
        # Get symbol info
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            return False
        
        # Check if trading is enabled
        if hasattr(symbol_info, 'trade_mode') and symbol_info.trade_mode == 0:
            return False
        
        # Check contract size
        if hasattr(symbol_info, 'trade_contract_size') and symbol_info.trade_contract_size <= 0:
            return False
        
        # Try to get a tick (but don't fail if we can't - some symbols might not have ticks yet)
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            # Symbol might be tradeable but no tick yet (e.g., market closed)
            # Return True anyway if other checks passed
            print(f"          ⚠️ No tick available for {symbol}, but symbol exists - assuming tradeable")
            return True
        
        # Check if we have valid prices
        if tick.ask == 0 and tick.bid == 0:
            return False
        
        return True

    def find_tradeable_symbol_with_retry(base_symbol, resolution_cache):
        """
        Try ALL suffixes one after another until a tradeable symbol is found.
        FIRST tries the exact symbol with case-insensitive matching.
        Returns (tradeable_symbol, used_suffix) or (None, None) if none found.
        """
        # Check cache first
        cache_key = f"tradeable_{base_symbol.lower()}"
        if cache_key in resolution_cache:
            cached_result = resolution_cache[cache_key]
            if cached_result is None:
                return None, None
            return cached_result, resolution_cache.get(f"suffix_{base_symbol.lower()}", "")
        
        print(f"        🔍 Searching for tradeable symbol for '{base_symbol}'...")
        
        # Get all symbols from MT5 once for case-insensitive lookups
        all_symbols = mt5.symbols_get()
        if not all_symbols:
            print(f"          ERROR: Cannot get symbols from MT5")
            resolution_cache[cache_key] = None
            return None, None
        
        symbols_lower_map = {s.name.lower(): s.name for s in all_symbols}
        base_lower = base_symbol.lower()
        
        # ========== STEP 1: Try direct case-insensitive match (NO SUFFIX) ==========
        # This is what works in fetch_ohlc_data_for_investor
        if base_lower in symbols_lower_map:
            exact_symbol = symbols_lower_map[base_lower]
            if exact_symbol != base_symbol:
                print(f"          🔧 Direct case correction: '{base_symbol}' → '{exact_symbol}'")
            
            # Try to select the symbol
            if mt5.symbol_select(exact_symbol, True):
                print(f"          ✅ SUCCESS! {exact_symbol} IS TRADEABLE (direct match)!")
                resolution_cache[cache_key] = exact_symbol
                resolution_cache[f"suffix_{base_symbol.lower()}"] = ""
                return exact_symbol, ""
            else:
                print(f"          ⚠️ Symbol '{exact_symbol}' exists but cannot be selected")
        else:
            print(f"          ℹ️ No direct match for '{base_symbol}' in MT5 symbols")
        
        # ========== STEP 2: Try all suffixes ==========
        for idx, suffix in enumerate(SYMBOL_SUFFIXES, 1):
            test_symbol = base_symbol + suffix
            
            # Skip if we already know this exact symbol is not tradeable
            symbol_cache_key = f"checked_{test_symbol.lower()}"
            if symbol_cache_key in resolution_cache and not resolution_cache[symbol_cache_key]:
                continue
            
            test_lower = test_symbol.lower()
            
            if test_lower in symbols_lower_map:
                actual_symbol = symbols_lower_map[test_lower]
                print(f"          Trying: {test_symbol} (suffix {idx}/{len(SYMBOL_SUFFIXES)}) - found as '{actual_symbol}'")
                
                # Try to select the symbol
                if mt5.symbol_select(actual_symbol, True):
                    print(f"          ✅ SUCCESS! {actual_symbol} IS TRADEABLE!")
                    resolution_cache[cache_key] = actual_symbol
                    resolution_cache[f"suffix_{base_symbol.lower()}"] = suffix
                    resolution_cache[symbol_cache_key] = True
                    return actual_symbol, suffix
                else:
                    print(f"          ⚠️ Symbol '{actual_symbol}' exists but cannot be selected")
                    resolution_cache[symbol_cache_key] = False
            else:
                print(f"          Trying: {test_symbol} (suffix {idx}/{len(SYMBOL_SUFFIXES)}) - NOT FOUND")
                resolution_cache[symbol_cache_key] = False
        
        # No tradeable symbol found
        print(f"         FAILED: No tradeable symbol found for '{base_symbol}' after trying {len(SYMBOL_SUFFIXES)} suffixes")
        resolution_cache[cache_key] = None
        return None, None

    # --- SUB-FUNCTION 13: COLLECT ORDERS FROM SIGNALS WITH FULL FIELD PRESERVATION ---
    def collect_orders_from_signals(investor_root, resolution_cache):
        """
        Collect all orders from limit_orders.json files in ALL strategy subfolders.
        PRESERVES ALL FIELDS from the original signal for later recording.
        Separates hedge orders from regular orders.
        """
        entries_with_paths = []
        hedge_entries = []
        regular_entries = []
        
        # Find ALL limit_orders.json files in any subfolder of investor_root
        signals_files = list(investor_root.rglob("limit_orders.json"))
        
        if not signals_files:
            print(f"    ℹ️  No limit_orders.json files found in {investor_root} or its subfolders")
            return [], [], []
        
        print(f"    📁 Found {len(signals_files)} limit_orders.json files in strategy folders:")
        
        for signals_path in signals_files:
            # Extract strategy name from parent folder
            strategy_name = signals_path.parent.name
            print(f"       • Strategy: {strategy_name} - {signals_path}")
            
            try:
                with open(signals_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if not data:
                    print(f"          Empty limit_orders.json file")
                    continue
                
                print(f"         📡 Found {len(data)} signals")
                
                for entry in data:
                    # Check if this is a hedge order
                    is_hedge = entry.get('is_hedge_order', False)
                    
                    # Get the raw symbol exactly as specified in the JSON
                    raw_symbol = entry.get("symbol", "")
                    
                    # Find tradeable symbol by trying ALL suffixes
                    tradeable_symbol, used_suffix = find_tradeable_symbol_with_retry(raw_symbol, resolution_cache)
                    
                    if tradeable_symbol is None:
                        print(f"          Cannot find ANY tradeable symbol for '{raw_symbol}' - skipping signal")
                        continue
                    
                    # Create a copy of the original entry with ALL fields preserved
                    enhanced_entry = entry.copy()
                    
                    # ========== DYNAMIC VOLUME EXTRACTION (ANY *_volume FIELD) ==========
                    volume = None
                    for key, value in enhanced_entry.items():
                        if key.endswith('_volume'):
                            try:
                                volume = float(value)
                                print(f"         📊 Extracted volume from '{key}': {volume}")
                                break
                            except (ValueError, TypeError):
                                continue
                    
                    # SKIP SIGNAL IF NO VOLUME FOUND
                    if volume is None:
                        print(f"          SKIPPING SIGNAL - No *_volume field found (required for placement)")
                        continue
                    
                    # Store volume in guaranteed standard field
                    enhanced_entry['volume'] = volume
                    # ========== END VOLUME EXTRACTION ==========
                    
                    # Update symbol fields
                    enhanced_entry['symbol'] = tradeable_symbol
                    enhanced_entry['strategy_name'] = strategy_name
                    enhanced_entry['original_symbol'] = raw_symbol
                    enhanced_entry['used_suffix'] = used_suffix if used_suffix else "none"
                    enhanced_entry['suffix_applied'] = used_suffix if used_suffix else "original"
                    enhanced_entry['signals_path'] = str(signals_path)  # Store path for removal if needed
                    
                    # Store the complete original entry for later reference
                    enhanced_entry['_original_signal'] = entry.copy()
                    
                    wrapper = {
                        'data': enhanced_entry,
                        'path': signals_path,
                        'strategy': strategy_name,
                        'original_signal': entry,  # Keep original for field preservation
                        'is_hedge': is_hedge
                    }
                    
                    entries_with_paths.append(wrapper)
                    
                    if is_hedge:
                        hedge_entries.append(wrapper)
                        print(f"            🛡️ HEDGE ORDER: {tradeable_symbol} - {entry.get('order_type')} (will ALWAYS be placed)")
                    else:
                        regular_entries.append(wrapper)
                        print(f"            📊 REGULAR ORDER: {tradeable_symbol} - {entry.get('order_type')} (will follow uniqueness rules)")
                    
                    if used_suffix:
                        print(f"               ✅ Using tradeable symbol: {tradeable_symbol} (original: {raw_symbol}, added suffix: '{used_suffix}')")
                    else:
                        print(f"               ✅ Using tradeable symbol: {tradeable_symbol} (original: {raw_symbol})")
                    
            except json.JSONDecodeError as e:
                print(f"          Invalid JSON in {signals_path}: {e}")
                continue
            except Exception as e:
                print(f"          Error reading {signals_path}: {e}")
                continue
        
        print(f"    📡 Total signals collected: {len(entries_with_paths)} (Hedge: {len(hedge_entries)}, Regular: {len(regular_entries)})")
        return entries_with_paths, hedge_entries, regular_entries

    # --- SUB-FUNCTION 17: RISK MANAGEMENT FOR DUPLICATE ORDERS (FIXED WITH PROPER CANCELLATION) ---
    def risk_management_for_duplicates(investor_root, new_order_data, existing_pending_orders, cancel_exceeding=True, check_only=False):
        """
        Check and manage duplicate orders risk.
        
        FOR SCAN MODE (check_only=True):
            - Groups ALL pending orders AND open positions by (symbol, direction, ENTRY PRICE - exact match)
            - Calculates total combined risk per unique entry
            - Cancels/Closes orders ONE BY ONE until total directional risk is within maximum threshold
        
        FOR NEW ORDER MODE (check_only=False):
            - Same cleanup first, then evaluates new order against TOTAL risk for SAME ENTRY PRICE
        """
        
        def calculate_order_risk(order_entry, order_sl, symbol, volume, is_buy):
            """Calculate risk in USD for an order or position"""
            if order_sl == 0 or order_sl is None:
                return 0
            try:
                calc_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
                risk_profit = mt5.order_calc_profit(calc_type, symbol, volume, order_entry, order_sl)
                return abs(risk_profit) if risk_profit else 0
            except Exception as e:
                return 0
        
        def normalize_order_direction(order_type_or_constant):
            """Get buy/sell direction from order type string or MT5 constant"""
            if isinstance(order_type_or_constant, str):
                order_lower = order_type_or_constant.lower()
                if 'buy' in order_lower:
                    return 'buy'
                elif 'sell' in order_lower:
                    return 'sell'
            else:
                # MT5 constant
                if order_type_or_constant in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP, 
                                            mt5.ORDER_TYPE_BUY_STOP_LIMIT, mt5.ORDER_TYPE_BUY]:
                    return 'buy'
                elif order_type_or_constant in [mt5.ORDER_TYPE_SELL_LIMIT, mt5.ORDER_TYPE_SELL_STOP,
                                            mt5.ORDER_TYPE_SELL_STOP_LIMIT, mt5.ORDER_TYPE_SELL]:
                    return 'sell'
            return None
        
        def cancel_single_order(order_ticket, reason):
            """Cancel a single pending order using MT5"""
            try:
                # First, verify the order still exists
                orders = mt5.orders_get(ticket=order_ticket)
                
                if not orders or len(orders) == 0:
                    print(f"            Order #{order_ticket} not found (may have been filled/cancelled)")
                    return False
                
                order = orders[0]
                
                # Verify it's still a pending order
                if order.type not in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_SELL_LIMIT,
                                    mt5.ORDER_TYPE_BUY_STOP, mt5.ORDER_TYPE_SELL_STOP]:
                    print(f"            Order #{order_ticket} is no longer a pending order (type: {order.type})")
                    return False
                
                # Create cancellation request
                cancel_request = {
                    "action": mt5.TRADE_ACTION_REMOVE,
                    "order": order_ticket
                }
                
                print(f"            📤 Cancelling pending order #{order_ticket}...")
                
                # Send cancellation request
                result = mt5.order_send(cancel_request)
                
                if result is None:
                    print(f"             No response from MT5 for #{order_ticket}")
                    error = mt5.last_error()
                    print(f"            🔍 MT5 Last Error: {error}")
                    return False
                
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    print(f"            ✅ Successfully cancelled order #{order_ticket}")
                    return True
                else:
                    error_codes = {
                        10004: "Trade timeout",
                        10006: "Invalid order",
                        10009: "Order already canceled",
                        10010: "Insufficient rights",
                        10011: "Too many requests",
                        10012: "Trade disabled",
                        10013: "Market closed",
                        10014: "Invalid price",
                        10015: "Invalid stops",
                        10016: "Invalid volume",
                        10017: "Order not found",
                        10018: "Order already filled",
                        10019: "Order canceled",
                        10020: "No changes",
                        10021: "Order locked",
                        10022: "Invalid order type"
                    }
                    error_msg = error_codes.get(result.retcode, f"Unknown error ({result.retcode})")
                    print(f"             Failed to cancel #{order_ticket}: {error_msg}")
                    if result.comment:
                        print(f"            📝 Broker comment: {result.comment}")
                    return False
                        
            except Exception as e:
                print(f"             Exception cancelling #{order_ticket}: {e}")
                import traceback
                traceback.print_exc()
                return False
        
        def close_single_position(position_ticket, symbol, volume, is_buy, reason):
            """Close a single open position using MT5"""
            try:
                # First, verify the position still exists
                positions = mt5.positions_get(ticket=position_ticket)
                
                if not positions or len(positions) == 0:
                    print(f"            Position #{position_ticket} not found (may have been closed)")
                    return False
                
                position = positions[0]
                
                # Get current market price for the symbol
                tick = mt5.symbol_info_tick(symbol)
                if not tick:
                    print(f"             Cannot get price for {symbol}")
                    return False
                
                # Determine order type for closing
                if is_buy:
                    # To close a buy position, we sell
                    order_type = mt5.ORDER_TYPE_SELL
                    price = tick.bid
                else:
                    # To close a sell position, we buy
                    order_type = mt5.ORDER_TYPE_BUY
                    price = tick.ask
                
                # Create close request
                close_request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": symbol,
                    "volume": volume,
                    "type": order_type,
                    "position": position_ticket,
                    "price": price,
                    "deviation": 20,
                    "magic": position.magic if hasattr(position, 'magic') else 0,
                    "comment": reason[:31],  # Max 31 characters
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                
                print(f"            📤 Closing position #{position_ticket} ({symbol}, {volume} lots)...")
                
                # Send close request
                result = mt5.order_send(close_request)
                
                if result is None:
                    print(f"             No response from MT5 for position #{position_ticket}")
                    error = mt5.last_error()
                    print(f"            🔍 MT5 Last Error: {error}")
                    return False
                
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    print(f"            ✅ Successfully closed position #{position_ticket}")
                    return True
                else:
                    error_codes = {
                        10004: "Trade timeout",
                        10006: "Invalid request",
                        10009: "Position already closed",
                        10010: "Insufficient rights",
                        10011: "Too many requests",
                        10012: "Trade disabled",
                        10013: "Market closed",
                        10014: "Invalid price",
                        10015: "Invalid stops",
                        10016: "Invalid volume",
                        10017: "Position not found",
                        10018: "Position already closed",
                        10019: "Position closed",
                        10020: "No changes",
                        10021: "Position locked",
                        10022: "Invalid order type"
                    }
                    error_msg = error_codes.get(result.retcode, f"Unknown error ({result.retcode})")
                    print(f"             Failed to close position #{position_ticket}: {error_msg}")
                    if result.comment:
                        print(f"            📝 Broker comment: {result.comment}")
                    return False
                        
            except Exception as e:
                print(f"             Exception closing position #{position_ticket}: {e}")
                import traceback
                traceback.print_exc()
                return False
        
        def load_risk_thresholds(investor_root, balance):
            """Load risk thresholds from accountmanagement.json"""
            acc_mgmt_path = investor_root / "accountmanagement.json"
            if not acc_mgmt_path.exists():
                return None, None, False
            
            try:
                with open(acc_mgmt_path, 'r') as f:
                    config = json.load(f)
                
                default_map = config.get("account_balance_default_risk_management", {})
                maximum_map = config.get("account_balance_maximum_risk_management", {})
                
                default_risk = None
                maximum_risk = None
                
                for range_str, r_val in default_map.items():
                    try:
                        parts = range_str.split("_")[0]
                        low, high = map(float, parts.split("-"))
                        if low <= balance <= high:
                            default_risk = float(r_val)
                            break
                    except:
                        continue
                
                for range_str, r_val in maximum_map.items():
                    try:
                        parts = range_str.split("_")[0]
                        low, high = map(float, parts.split("-"))
                        if low <= balance <= high:
                            maximum_risk = float(r_val)
                            break
                    except:
                        continue
                
                if default_risk is None and maximum_risk is None:
                    return None, None, False
                if default_risk is None:
                    default_risk = maximum_risk
                if maximum_risk is None:
                    maximum_risk = default_risk
                if maximum_risk < default_risk:
                    maximum_risk = default_risk
                
                return default_risk, maximum_risk, True
                
            except Exception as e:
                print(f"        Error loading risk thresholds: {e}")
                return None, None, False
        
        # --- Get account balance and thresholds ---
        account_info = mt5.account_info()
        if not account_info:
            print(f"         Cannot get account info")
            return False, {'error': 'No account info'}
        
        balance = account_info.balance
        default_risk, max_risk, found = load_risk_thresholds(investor_root, balance)
        
        if not found:
            print(f"        ℹ️ No risk thresholds configured - skipping")
            return True, {'skipped': True}
        
        print(f"        🎯 Risk Limits: Target=${default_risk:.2f}, Maximum=${max_risk:.2f}")
        print(f"        🔍 AutoTrading: {'✅ ENABLED' if mt5.terminal_info().trade_allowed else ' DISABLED'}")
        
        # --- GET ALL OPEN POSITIONS ---
        open_positions = mt5.positions_get() or []
        print(f"        📊 Found {len(open_positions)} open position(s)")
        
        # --- AGGREGATE ALL PENDING ORDERS AND OPEN POSITIONS BY (SYMBOL, DIRECTION, ENTRY PRICE - EXACT) ---
        # KEY CHANGE: Now grouping by symbol, direction, AND exact entry price (no rounding)
        entry_groups = {}
        
        # Process pending orders
        for order in existing_pending_orders:
            # Skip non-pending order types
            if order.type not in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_SELL_LIMIT,
                                mt5.ORDER_TYPE_BUY_STOP, mt5.ORDER_TYPE_SELL_STOP]:
                continue
            
            direction = normalize_order_direction(order.type)
            if not direction:
                continue
            
            # KEY CHANGE: Group by symbol + direction + EXACT entry price (as float, no rounding)
            # Use the raw float value - exact match required
            entry_price = order.price_open
            group_key = f"{order.symbol}_{direction}_{entry_price}"
            
            # Calculate risk for this order
            is_buy = direction == 'buy'
            risk = calculate_order_risk(order.price_open, order.sl, order.symbol, order.volume_initial, is_buy)
            
            if group_key not in entry_groups:
                entry_groups[group_key] = {
                    'symbol': order.symbol,
                    'direction': direction,
                    'entry_price': entry_price,
                    'orders': [],
                    'positions': [],
                    'total_risk': 0
                }
            
            entry_groups[group_key]['orders'].append({
                'ticket': order.ticket,
                'risk': risk,
                'entry': order.price_open,
                'volume': order.volume_initial,
                'sl': order.sl,
                'type': 'pending_order'
            })
            entry_groups[group_key]['total_risk'] += risk
        
        # Process open positions
        for position in open_positions:
            # Determine direction
            direction = normalize_order_direction(position.type)
            if not direction:
                continue
            
            # KEY CHANGE: Group by symbol + direction + EXACT entry price
            entry_price = position.price_open
            group_key = f"{position.symbol}_{direction}_{entry_price}"
            
            # Calculate risk for this position
            is_buy = direction == 'buy'
            risk = calculate_order_risk(position.price_open, position.sl, position.symbol, position.volume, is_buy)
            
            if group_key not in entry_groups:
                entry_groups[group_key] = {
                    'symbol': position.symbol,
                    'direction': direction,
                    'entry_price': entry_price,
                    'orders': [],
                    'positions': [],
                    'total_risk': 0
                }
            
            entry_groups[group_key]['positions'].append({
                'ticket': position.ticket,
                'risk': risk,
                'entry': position.price_open,
                'volume': position.volume,
                'is_buy': is_buy,
                'type': 'open_position'
            })
            entry_groups[group_key]['total_risk'] += risk
        
        # --- SCAN AND CANCEL/CLOSE ORDERS/POSITIONS ONE BY ONE UNTIL WITHIN LIMITS ---
        total_cancelled = 0
        total_closed = 0
        
        # Log the grouping for debugging
        if entry_groups:
            print(f"        🔍 Found {len(entry_groups)} unique entry price group(s)")
            for group_key, group in entry_groups.items():
                total_items = len(group['orders']) + len(group['positions'])
                print(f"           - {group['symbol']} {group['direction'].upper()} @ {group['entry_price']}: {total_items} item(s), total risk: ${group['total_risk']:.2f}")
            
            for group_key, group in entry_groups.items():
                # Combine all items (orders and positions) and sort by risk (highest first)
                all_items = []
                all_items.extend([(item, 'order') for item in group['orders']])
                all_items.extend([(item, 'position') for item in group['positions']])
                
                # Sort by risk (highest first) - remove most risky first
                all_items.sort(key=lambda x: x[0]['risk'], reverse=True)
                
                current_risk = group['total_risk']
                
                total_items = len(group['orders']) + len(group['positions'])
                print(f"\n        📋 Entry Group: {group['symbol']} {group['direction'].upper()} @ {group['entry_price']}")
                print(f"           Total items: {total_items} ({len(group['orders'])} orders, {len(group['positions'])} positions) | Total risk: ${current_risk:.2f}")
                
                # If group risk exceeds maximum, cancel/close items one by one
                if current_risk > max_risk and cancel_exceeding:
                    print(f"           🚨 Total entry risk exceeds maximum (${current_risk:.2f} > ${max_risk:.2f})")
                    print(f"           🔄 Closing/Cancelling items one by one until risk is within limit...")
                    
                    # Track what we close/cancel
                    cancelled_in_group = 0
                    closed_in_group = 0
                    
                    for item, item_type in all_items:
                        # Check current risk after previous cancellations/closures
                        if current_risk <= max_risk:
                            print(f"           ✅ Risk now within limit: ${current_risk:.2f} ≤ ${max_risk:.2f}")
                            print(f"           📊 Cancelled {cancelled_in_group} order(s), closed {closed_in_group} position(s)")
                            break
                        
                        if item_type == 'order':
                            # Try to cancel this order
                            print(f"           🗑️ Attempting to cancel order #{item['ticket']} (entry: {item['entry']}, risk: ${item['risk']:.2f})")
                            
                            if cancel_single_order(item['ticket'], f"Entry risk ${current_risk:.2f} exceeds max ${max_risk:.2f}"):
                                cancelled_in_group += 1
                                total_cancelled += 1
                                current_risk -= item['risk']
                                print(f"           📊 Remaining entry risk: ${current_risk:.2f}")
                            else:
                                print(f"           Failed to cancel order #{item['ticket']}, skipping...")
                                continue
                                
                        elif item_type == 'position':
                            # Try to close this position
                            print(f"           🔒 Attempting to close position #{item['ticket']} (entry: {item['entry']}, risk: ${item['risk']:.2f})")
                            
                            if close_single_position(
                                item['ticket'], 
                                group['symbol'], 
                                item['volume'], 
                                item['is_buy'],
                                f"Entry risk ${current_risk:.2f} exceeds max ${max_risk:.2f}"
                            ):
                                closed_in_group += 1
                                total_closed += 1
                                current_risk -= item['risk']
                                print(f"           📊 Remaining entry risk: ${current_risk:.2f}")
                            else:
                                print(f"           Failed to close position #{item['ticket']}, skipping...")
                                continue
                    
                    # Final status for this group
                    if current_risk > max_risk:
                        print(f"           Group still exceeds limit after cleanup attempts! Risk: ${current_risk:.2f}")
                        print(f"           💡 Some items may have been filled/closed by other processes")
                    else:
                        print(f"           ✅ Entry risk now within limit: ${current_risk:.2f} ≤ ${max_risk:.2f}")
                
                # Check individual items that exceed maximum by themselves (even if total is fine)
                else:
                    for item, item_type in all_items:
                        if item['risk'] > max_risk and cancel_exceeding:
                            if item_type == 'order':
                                print(f"           🚨 Individual order #{item['ticket']} exceeds maximum (${item['risk']:.2f} > ${max_risk:.2f})")
                                if cancel_single_order(item['ticket'], f"Individual risk ${item['risk']:.2f} exceeds max ${max_risk:.2f}"):
                                    total_cancelled += 1
                                else:
                                    print(f"           Failed to cancel order #{item['ticket']}")
                            elif item_type == 'position':
                                print(f"           🚨 Individual position #{item['ticket']} exceeds maximum (${item['risk']:.2f} > ${max_risk:.2f})")
                                if close_single_position(
                                    item['ticket'], 
                                    group['symbol'], 
                                    item['volume'], 
                                    item['is_buy'],
                                    f"Individual risk ${item['risk']:.2f} exceeds max ${max_risk:.2f}"
                                ):
                                    total_closed += 1
                                else:
                                    print(f"           Failed to close position #{item['ticket']}")
        else:
            print(f"        ℹ️ No pending orders or open positions found to scan")
        
        if total_cancelled > 0 or total_closed > 0:
            print(f"\n        ✅ Cleanup complete: Cancelled {total_cancelled} order(s), Closed {total_closed} position(s)")
        else:
            print(f"\n        ℹ️ No items needed to be cancelled or closed")
        
        # If check_only mode, return here
        if check_only or new_order_data is None:
            return True, {
                'cancelled_count': total_cancelled, 
                'closed_count': total_closed,
                'check_only': True
            }
        
        # Refresh pending orders and positions list after cleanup
        import time
        time.sleep(0.5)  # Small delay to ensure MT5 processes cancellations/closures
        refreshed_pending = mt5.orders_get() or []
        refreshed_positions = mt5.positions_get() or []
        
        # --- EVALUATE NEW ORDER AGAINST TOTAL RISK FOR EXACT ENTRY MATCH ---
        new_symbol = new_order_data.get('symbol')
        new_entry = new_order_data.get('entry')
        
        # Dynamic volume extraction for new order evaluation (same logic)
        new_volume = None
        for key, value in new_order_data.items():
            if key.endswith('_volume'):
                try:
                    new_volume = float(value)
                    break
                except (ValueError, TypeError):
                    continue
        
        # Also check standardized 'volume' field
        if new_volume is None:
            new_volume = new_order_data.get('volume', None)
        
        # Skip if no volume found
        if new_volume is None:
            print(f"         Cannot evaluate risk - no volume field in order data")
            return False, {'reason': 'No volume field found'}
        
        new_sl = new_order_data.get('exit', 0)
        new_type = new_order_data.get('order_type', '').lower()
        new_direction = normalize_order_direction(new_type)
        new_is_buy = new_direction == 'buy'
        
        print(f"\n        📋 Evaluating New Order: {new_direction.upper()} {new_symbol} @ {new_entry} vol {new_volume}")
        
        # Calculate new order risk
        new_risk = calculate_order_risk(new_entry, new_sl, new_symbol, new_volume, new_is_buy)
        print(f"        📊 New order risk: ${new_risk:.2f}")
        
        # KEY CHANGE: Calculate total risk for orders/positions with EXACT same entry price
        new_entry_group_key = f"{new_symbol}_{new_direction}_{new_entry}"
        existing_entry_risk = 0
        
        # Sum up risk from refreshed pending orders for same entry price
        for order in refreshed_pending:
            if order.type not in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_SELL_LIMIT,
                                mt5.ORDER_TYPE_BUY_STOP, mt5.ORDER_TYPE_SELL_STOP]:
                continue
            
            dir = normalize_order_direction(order.type)
            if not dir:
                continue
            
            # IMPORTANT: Compare entry prices exactly (no rounding)
            if order.symbol == new_symbol and dir == new_direction and order.price_open == new_entry:
                is_buy = dir == 'buy'
                rsk = calculate_order_risk(order.price_open, order.sl, order.symbol, order.volume_initial, is_buy)
                existing_entry_risk += rsk
                print(f"        📋 Existing order #{order.ticket}: {order.symbol} {dir} @ {order.price_open} vol {order.volume_initial} risk ${rsk:.2f}")
        
        # Sum up risk from refreshed positions for same entry price
        for position in refreshed_positions:
            dir = normalize_order_direction(position.type)
            if not dir:
                continue
            
            # IMPORTANT: Compare entry prices exactly (no rounding)
            if position.symbol == new_symbol and dir == new_direction and position.price_open == new_entry:
                is_buy = dir == 'buy'
                rsk = calculate_order_risk(position.price_open, position.sl, position.symbol, position.volume, is_buy)
                existing_entry_risk += rsk
                print(f"        📋 Existing position #{position.ticket}: {position.symbol} {dir} @ {position.price_open} vol {position.volume} risk ${rsk:.2f}")
        
        print(f"        📊 Total existing risk for EXACT entry {new_entry}: ${existing_entry_risk:.2f}")
        
        # Calculate total risk including new order
        total_entry_risk = existing_entry_risk + new_risk
        print(f"        📊 Total entry risk if placed: ${total_entry_risk:.2f}")
        
        # Decision based on total risk for this specific entry price
        if total_entry_risk > max_risk:
            print(f"        🚨 TOTAL ENTRY RISK (${total_entry_risk:.2f}) EXCEEDS MAXIMUM (${max_risk:.2f})")
            print(f"         ORDER REJECTED - would exceed maximum by ${total_entry_risk - max_risk:.2f}")
            return False, {'reason': f'Entry risk ${total_entry_risk:.2f} exceeds max ${max_risk:.2f} for entry {new_entry}'}
        
        if total_entry_risk <= default_risk:
            print(f"        ✅ Within TARGET range: ${total_entry_risk:.2f} ≤ ${default_risk:.2f}")
        else:
            print(f"        ✅ Within TOLERANCE range: ${default_risk:.2f} < ${total_entry_risk:.2f} ≤ ${max_risk:.2f}")
        
        return True, {
            'total_risk': total_entry_risk, 
            'existing_risk': existing_entry_risk, 
            'new_risk': new_risk, 
            'cancelled_count': total_cancelled,
            'closed_count': total_closed
        }

    def execute_order_old(order_data, investor_root, per_order_cache, existing_positions, original_signal, skip_proximity_check, switch_invalid_to_instant=False):
        """
        Execute a single order based on its order_type.
        PRESERVES ALL FIELDS from original signal for tradeshistory.
        REMOVES CANDLE TIME RECORD IF ORDER PLACEMENT FAILS.
        
        Args:
            skip_proximity_check: If True, skips proximity risk check entirely
            switch_invalid_to_instant: (KEPT FOR COMPATIBILITY BUT NOT USED)
        """
        
        # --- SUB-FUNCTION: GET SUPPORTED FILLING MODES ---
        def get_supported_filling_modes(symbol_info, is_pending_order=False):
            """
            Determine supported filling modes for a symbol based on its properties.
            Returns list of filling modes to try in order of preference.
            
            Args:
                symbol_info: MT5 symbol info object
                is_pending_order: True for pending orders, False for market orders
            
            Returns:
                list: List of filling mode constants to try
            """
            if is_pending_order:
                # For pending orders, most brokers only support RETURN mode
                # Some brokers don't support any filling mode for pending orders
                return [mt5.ORDER_FILLING_RETURN]
            
            # For market orders, check symbol properties
            execution_mode = symbol_info.trade_exemode
            filling_mode_mask = symbol_info.filling_mode
            
            # Debug output
            print(f"        📋 Symbol filling mode mask: {filling_mode_mask}")
            print(f"        📋 Execution mode: {execution_mode}")
            
            # SYMBOL_FILLING flags
            SYMBOL_FILLING_FOK = 0x01  # Fill or Kill
            SYMBOL_FILLING_IOC = 0x02  # Immediate or Cancel
            SYMBOL_FILLING_BOC = 0x04  # Book or Cancel (since build 3800)
            
            filling_modes = []
            
            # Strategy 1: For Exchange Execution, try BOC, IOC, FOK
            if execution_mode == mt5.SYMBOL_TRADE_EXECUTION_EXCHANGE:
                if filling_mode_mask & SYMBOL_FILLING_BOC:
                    filling_modes.append(mt5.ORDER_FILLING_BOC)
                if filling_mode_mask & SYMBOL_FILLING_IOC:
                    filling_modes.append(mt5.ORDER_FILLING_IOC)
                if filling_mode_mask & SYMBOL_FILLING_FOK:
                    filling_modes.append(mt5.ORDER_FILLING_FOK)
                # Always add RETURN as fallback
                filling_modes.append(mt5.ORDER_FILLING_RETURN)
            
            # Strategy 2: For Market Execution, try IOC first, then RETURN
            elif execution_mode == mt5.SYMBOL_TRADE_EXECUTION_MARKET:
                if filling_mode_mask & SYMBOL_FILLING_IOC:
                    filling_modes.append(mt5.ORDER_FILLING_IOC)
                # Some brokers with Market Execution work better with RETURN
                filling_modes.append(mt5.ORDER_FILLING_RETURN)
                if filling_mode_mask & SYMBOL_FILLING_FOK:
                    filling_modes.append(mt5.ORDER_FILLING_FOK)
            
            # Strategy 3: For Instant/Request Execution, try FOK
            elif execution_mode in [mt5.SYMBOL_TRADE_EXECUTION_INSTANT, mt5.SYMBOL_TRADE_EXECUTION_REQUEST]:
                if filling_mode_mask & SYMBOL_FILLING_FOK:
                    filling_modes.append(mt5.ORDER_FILLING_FOK)
                filling_modes.append(mt5.ORDER_FILLING_RETURN)
            
            # Strategy 4: Unknown execution mode - try common modes
            else:
                filling_modes = [
                    mt5.ORDER_FILLING_IOC,
                    mt5.ORDER_FILLING_FOK,
                    mt5.ORDER_FILLING_RETURN
                ]
            
            # Remove duplicates while preserving order
            unique_modes = []
            for mode in filling_modes:
                if mode not in unique_modes:
                    unique_modes.append(mode)
            
            print(f"        📋 Will try filling modes in order: {unique_modes}")
            return unique_modes
        
        # --- SUB-FUNCTION: SEND ORDER WITH AUTO FILLING MODE RETRY ---
        def send_order_with_auto_filling(request_template, filling_modes, is_pending_order=False):
            """
            Send order with automatic retry using different filling modes.
            
            Args:
                request_template: Base request dictionary (without type_filling)
                filling_modes: List of filling modes to try
                is_pending_order: True for pending orders
            
            Returns:
                tuple: (result, used_filling_mode, error_message)
            """
            for filling_mode in filling_modes:
                # Create request copy with current filling mode
                request = request_template.copy()
                request["type_filling"] = filling_mode
                
                # For pending orders, ensure action is PENDING
                if is_pending_order:
                    request["action"] = mt5.TRADE_ACTION_PENDING
                else:
                    request["action"] = mt5.TRADE_ACTION_DEAL
                
                # Send order
                result = mt5.order_send(request)
                
                # Check if successful
                if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                    print(f"        ✅ Order successful with filling mode: {filling_mode}")
                    return result, filling_mode, None
                
                # Check if we should try next filling mode
                if result is not None and result.retcode == 10009:  # Unsupported filling mode
                    print(f"         Filling mode {filling_mode} not supported, trying next...")
                    continue
                elif result is not None and result.retcode != mt5.TRADE_RETCODE_DONE:
                    # Other error - don't retry, return the error
                    return result, filling_mode, f"Order failed: {result.comment} (code: {result.retcode})"
            
            # All filling modes failed
            return None, None, "All filling modes failed"
        
        symbol = order_data.get('symbol')
        order_type = order_data.get('order_type', '').lower()
        entry_price = float(order_data.get('entry', 0))
        exit_price = float(order_data.get('exit', 0)) if order_data.get('exit') else 0
        target_price = float(order_data.get('target', 0)) if order_data.get('target') else 0
        volume = get_volume_from_signal(order_data)
        
        # SKIP ORDER IF NO VOLUME FOUND
        if volume is None:
            error_msg = "No volume field found in signal - cannot place order"
            print(f"         {error_msg}")
            
            if timeframe and current_candle_time:
                print(f"        🗑️ Removing candle time record due to missing volume...")
                remove_candle_time_record(investor_root, order_data.get('original_symbol', symbol), timeframe, current_candle_time)
            
            return False, None, error_msg, None
        
        magic_number = int(order_data.get('magic', int(investor_root.name) if investor_root.name.isdigit() else 123456))
        strategy_name = order_data.get('strategy_name', 'unknown')
        timeframe = order_data.get('timeframe', '')
        current_candle_time = order_data.get('current_candle_time', '')
        signals_path = order_data.get('signals_path', '')
        is_hedge = order_data.get('is_hedge_order', False)
        
        # Get symbol info - use exact symbol name
        if not mt5.symbol_select(symbol, True):
            error_msg = f"Failed to select symbol {symbol}"
            print(f"         {error_msg}")
            
            if timeframe and current_candle_time:
                print(f"        🗑️ Removing candle time record due to symbol selection failure...")
                remove_candle_time_record(investor_root, order_data.get('original_symbol', symbol), timeframe, current_candle_time)
            
            return False, None, error_msg, None
        
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            error_msg = f"Cannot get symbol info for {symbol}"
            print(f"         {error_msg}")
            
            if timeframe and current_candle_time:
                print(f"        🗑️ Removing candle time record due to symbol info failure...")
                remove_candle_time_record(investor_root, order_data.get('original_symbol', symbol), timeframe, current_candle_time)
            
            return False, None, error_msg, None
        
        # Get current market prices for reference
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            error_msg = f"Cannot get tick for {symbol}"
            print(f"         {error_msg}")
            
            if timeframe and current_candle_time:
                print(f"        🗑️ Removing candle time record due to tick retrieval failure...")
                remove_candle_time_record(investor_root, order_data.get('original_symbol', symbol), timeframe, current_candle_time)
            
            return False, None, error_msg, None
        
        current_ask = tick.ask
        current_bid = tick.bid
        
        print(f"        📊 {order_type.upper()} order: Entry={entry_price}, Current ASK={current_ask}, Current BID={current_bid}")
        
        # Round values to symbol digits
        entry_price = round(entry_price, symbol_info.digits)
        exit_price = round(exit_price, symbol_info.digits) if exit_price else 0
        target_price = round(target_price, symbol_info.digits) if target_price else 0

        # Clamp volume to symbol's min/max limits WITHOUT rounding
        volume = max(symbol_info.volume_min, min(symbol_info.volume_max, volume))
        
        print(f"        📊 Final volume: {volume} (min: {symbol_info.volume_min}, max: {symbol_info.volume_max})")
        
        # Get MT5 order type constant
        mt5_order_type = get_mt5_order_type(order_type)
        if mt5_order_type is None:
            error_msg = f"Invalid order type: {order_type}"
            print(f"         {error_msg}")
            
            if timeframe and current_candle_time:
                print(f"        🗑️ Removing candle time record due to invalid order type...")
                remove_candle_time_record(investor_root, order_data.get('original_symbol', symbol), timeframe, current_candle_time)
            
            return False, None, error_msg, None
        
        # Generate cache key (includes exact symbol with suffix)
        cache_key = f"{symbol}_{mt5_order_type}_{entry_price}_{volume}"
        
        # Check per-order cache
        if cache_key in per_order_cache:
            error_msg = "Already placed in this run"
            print(f"        ⏭️  SKIP - {error_msg}")
            return False, None, error_msg, cache_key
        
        # ========== RISK MANAGEMENT CHECK ==========
        # Get current pending orders from MT5
        current_pending = mt5.orders_get() or []
        
        # Run risk management check
        risk_allowed, risk_info = risk_management_for_duplicates(
            investor_root, order_data, current_pending, cancel_exceeding=True
        )
        
        if not risk_allowed:
            error_msg = f"Risk management rejected: {risk_info.get('reason', 'Unknown reason')}"
            print(f"         {error_msg}")
            
            if timeframe and current_candle_time:
                remove_candle_time_record(investor_root, order_data.get('original_symbol', symbol), 
                                        timeframe, current_candle_time)
            
            return False, None, error_msg, cache_key
        elif risk_info.get('cancelled_count', 0) > 0:
            print(f"        ✅ Cleaned up {risk_info['cancelled_count']} exceeding orders")
        # ========== END OF RISK MANAGEMENT CHECK ==========
        
        # Check proximity risk ONLY if enabled in settings (but skip for hedge orders)
        if is_hedge:
            print(f"        🛡️ HEDGE ORDER: Skipping proximity risk check")
        elif skip_proximity_check:
            print(f"        ℹ️  Proximity risk check DISABLED - placing order regardless of position proximity")
        else:
            is_risk, risk_position, risk_amount, risk_threshold = check_proximity_risk(order_data, existing_positions)
            
            if is_risk:
                error_msg = f"Too close to position #{risk_position.ticket if risk_position else 'unknown'}"
                print(f"         RISK SKIP - {error_msg} (risk: ${risk_amount:.2f} < threshold: ${risk_threshold:.2f})")
                
                if timeframe and current_candle_time:
                    print(f"        🗑️ Removing candle time record due to proximity risk...")
                    remove_candle_time_record(investor_root, order_data.get('original_symbol', symbol), timeframe, current_candle_time)
                
                return False, None, error_msg, cache_key
        
        # --- GET SUPPORTED FILLING MODES ---
        is_pending = order_type not in ['instant_buy', 'instant_sell']
        filling_modes = get_supported_filling_modes(symbol_info, is_pending)
        
        # --- PREPARE REQUEST TEMPLATE (without type_filling) ---
        if order_type in ['instant_buy', 'instant_sell']:
            # Market order (instant execution)
            price = current_ask if order_type == 'instant_buy' else current_bid
            
            request_template = {
                "symbol": symbol,
                "volume": volume,
                "type": mt5_order_type,
                "price": price,
                "deviation": 20,
                "magic": magic_number,
                "comment": f"{strategy_name[:20]} RR{order_data.get('risk_reward', '?')}",
                "type_time": mt5.ORDER_TIME_GTC,
            }
            
            if exit_price:
                request_template["sl"] = exit_price
            if target_price:
                request_template["tp"] = target_price
                
        else:
            # Pending order - place exactly as specified
            request_template = {
                "symbol": symbol,
                "volume": volume,
                "type": mt5_order_type,
                "price": entry_price,
                "deviation": 20,
                "magic": magic_number,
                "comment": f"{strategy_name[:20]} RR{order_data.get('risk_reward', '?')}",
                "type_time": mt5.ORDER_TIME_GTC,
            }
            
            if exit_price:
                request_template["sl"] = exit_price
            if target_price:
                request_template["tp"] = target_price
        
        # --- SEND ORDER WITH AUTO FILLING MODE RETRY ---
        result, used_filling_mode, error_msg = send_order_with_auto_filling(
            request_template, filling_modes, is_pending
        )
        
        # Handle order send failure
        if result is None:
            error_msg = f"Order send failed: {error_msg or mt5.last_error()}"
            print(f"         {error_msg}")
            
            if timeframe and current_candle_time:
                print(f"        🗑️ Removing candle time record due to order send failure...")
                remove_candle_time_record(investor_root, order_data.get('original_symbol', symbol), timeframe, current_candle_time)
            
            return False, None, error_msg, cache_key
        
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            error_msg = f"Order failed: {result.comment} (code: {result.retcode})"
            print(f"         {error_msg}")
            
            if timeframe and current_candle_time:
                print(f"        🗑️ Removing candle time record due to order placement failure...")
                remove_candle_time_record(investor_root, order_data.get('original_symbol', symbol), timeframe, current_candle_time)
            
            return False, None, error_msg, cache_key
        
        # Create detailed trade record with ALL fields from original signal
        trade_record = {}
        
        # First, copy ALL fields from the processed order_data
        for key, value in order_data.items():
            if not key.startswith('_'):  # Skip internal fields
                trade_record[key] = value
        
        # Add filling mode info
        if used_filling_mode:
            trade_record['filling_mode_used'] = used_filling_mode
        
        # Then add MT5-specific fields
        trade_record.update({
            'ticket': result.order,
            'magic': magic_number,
            'placed_timestamp': datetime.now().isoformat(),
            'status': 'pending',
            'mt5_retcode': result.retcode,
            'mt5_comment': result.comment,
            'placed_price': entry_price if order_type not in ['instant_buy', 'instant_sell'] else (request_template['price'] if 'price' in request_template else entry_price),
            'placed_volume': volume,
            'placed_order_type': order_type,
            'strategy_name': strategy_name,
            'symbol_used': symbol,
            'original_symbol_requested': order_data.get('original_symbol', symbol),
            'is_hedge_order': is_hedge
        })
        
        # Add any fields from original_signal that might have been missed
        if original_signal:
            for key, value in original_signal.items():
                if key not in trade_record:
                    trade_record[f'original_{key}'] = value
        
        # Save to history
        syncing_orders_and_pnl_details(investor_root, trade_record, original_signal)
        
        hedge_msg = " 🛡️[HEDGE]" if is_hedge else ""
        print(f"        ✅ SUCCESS: {order_type.upper()} {symbol} @ {request_template['price'] if 'price' in request_template else entry_price} (Ticket: {result.order}) [Strategy: {strategy_name}]{hedge_msg}")
        return True, result, None, cache_key
    
    def execute_order(order_data, investor_root, per_order_cache, existing_positions, 
                  original_signal, skip_proximity_check, switch_invalid_to_instant,
                  authorized_magic_number):
        """
        Execute a single order based on its order_type.
        Uses the authorized magic number (LOGIN_ID + USER_ID) for ALL order placements.
        """
        
        # --- SUB-FUNCTION: GET SUPPORTED FILLING MODES ---
        def get_supported_filling_modes(symbol_info, is_pending_order=False):
            # ... (same as before, no changes needed)
            if is_pending_order:
                return [mt5.ORDER_FILLING_RETURN]
            
            execution_mode = symbol_info.trade_exemode
            filling_mode_mask = symbol_info.filling_mode
            
            SYMBOL_FILLING_FOK = 0x01
            SYMBOL_FILLING_IOC = 0x02
            SYMBOL_FILLING_BOC = 0x04
            
            filling_modes = []
            
            if execution_mode == mt5.SYMBOL_TRADE_EXECUTION_EXCHANGE:
                if filling_mode_mask & SYMBOL_FILLING_BOC:
                    filling_modes.append(mt5.ORDER_FILLING_BOC)
                if filling_mode_mask & SYMBOL_FILLING_IOC:
                    filling_modes.append(mt5.ORDER_FILLING_IOC)
                if filling_mode_mask & SYMBOL_FILLING_FOK:
                    filling_modes.append(mt5.ORDER_FILLING_FOK)
                filling_modes.append(mt5.ORDER_FILLING_RETURN)
            elif execution_mode == mt5.SYMBOL_TRADE_EXECUTION_MARKET:
                if filling_mode_mask & SYMBOL_FILLING_IOC:
                    filling_modes.append(mt5.ORDER_FILLING_IOC)
                filling_modes.append(mt5.ORDER_FILLING_RETURN)
                if filling_mode_mask & SYMBOL_FILLING_FOK:
                    filling_modes.append(mt5.ORDER_FILLING_FOK)
            elif execution_mode in [mt5.SYMBOL_TRADE_EXECUTION_INSTANT, mt5.SYMBOL_TRADE_EXECUTION_REQUEST]:
                if filling_mode_mask & SYMBOL_FILLING_FOK:
                    filling_modes.append(mt5.ORDER_FILLING_FOK)
                filling_modes.append(mt5.ORDER_FILLING_RETURN)
            else:
                filling_modes = [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
            
            unique_modes = []
            for mode in filling_modes:
                if mode not in unique_modes:
                    unique_modes.append(mode)
            
            print(f"        📋 Will try filling modes in order: {unique_modes}")
            return unique_modes
        
        # --- SUB-FUNCTION: SEND ORDER WITH AUTO FILLING MODE RETRY ---
        def send_order_with_auto_filling(request_template, filling_modes, is_pending_order=False):
            # ... (same as before, no changes needed)
            for filling_mode in filling_modes:
                request = request_template.copy()
                request["type_filling"] = filling_mode
                
                if is_pending_order:
                    request["action"] = mt5.TRADE_ACTION_PENDING
                else:
                    request["action"] = mt5.TRADE_ACTION_DEAL
                
                result = mt5.order_send(request)
                
                if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                    print(f"        ✅ Order successful with filling mode: {filling_mode}")
                    return result, filling_mode, None
                
                if result is not None and result.retcode == 10009:
                    print(f"         Filling mode {filling_mode} not supported, trying next...")
                    continue
                elif result is not None and result.retcode != mt5.TRADE_RETCODE_DONE:
                    return result, filling_mode, f"Order failed: {result.comment} (code: {result.retcode})"
            
            return None, None, "All filling modes failed"
        
        # --- MAIN EXECUTION ---
        symbol = order_data.get('symbol')
        order_type = order_data.get('order_type', '').lower()
        entry_price = float(order_data.get('entry', 0))
        exit_price = float(order_data.get('exit', 0)) if order_data.get('exit') else 0
        target_price = float(order_data.get('target', 0)) if order_data.get('target') else 0
        volume = get_volume_from_signal(order_data)
        
        # SKIP ORDER IF NO VOLUME FOUND
        if volume is None:
            error_msg = "No volume field found in signal - cannot place order"
            print(f"         {error_msg}")
            
            timeframe = order_data.get('timeframe', '')
            current_candle_time = order_data.get('current_candle_time', '')
            if timeframe and current_candle_time:
                print(f"        🗑️ Removing candle time record due to missing volume...")
                remove_candle_time_record(investor_root, order_data.get('original_symbol', symbol), timeframe, current_candle_time)
            
            return False, None, error_msg, None
        
        # CRITICAL: USE AUTHORIZED MAGIC NUMBER (LOGIN_ID + USER_ID)
        magic_number = authorized_magic_number
        
        # Fallback only if authorized_magic_number is None (should never happen)
        if magic_number is None:
            magic_number = int(order_data.get('magic', int(investor_root.name) if investor_root.name.isdigit() else 123456))
            print(f"        ⚠️ WARNING: Using fallback magic number {magic_number} (authorized not available)")
        
        strategy_name = order_data.get('strategy_name', 'unknown')
        timeframe = order_data.get('timeframe', '')
        current_candle_time = order_data.get('current_candle_time', '')
        signals_path = order_data.get('signals_path', '')
        is_hedge = order_data.get('is_hedge_order', False)
        
        # Get symbol info - use exact symbol name
        if not mt5.symbol_select(symbol, True):
            error_msg = f"Failed to select symbol {symbol}"
            print(f"         {error_msg}")
            
            if timeframe and current_candle_time:
                print(f"        🗑️ Removing candle time record due to symbol selection failure...")
                remove_candle_time_record(investor_root, order_data.get('original_symbol', symbol), timeframe, current_candle_time)
            
            return False, None, error_msg, None
        
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            error_msg = f"Cannot get symbol info for {symbol}"
            print(f"         {error_msg}")
            
            if timeframe and current_candle_time:
                print(f"        🗑️ Removing candle time record due to symbol info failure...")
                remove_candle_time_record(investor_root, order_data.get('original_symbol', symbol), timeframe, current_candle_time)
            
            return False, None, error_msg, None
        
        # Get current market prices for reference
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            error_msg = f"Cannot get tick for {symbol}"
            print(f"         {error_msg}")
            
            if timeframe and current_candle_time:
                print(f"        🗑️ Removing candle time record due to tick retrieval failure...")
                remove_candle_time_record(investor_root, order_data.get('original_symbol', symbol), timeframe, current_candle_time)
            
            return False, None, error_msg, None
        
        current_ask = tick.ask
        current_bid = tick.bid
        
        print(f"        📊 {order_type.upper()} order: Entry={entry_price}, Current ASK={current_ask}, Current BID={current_bid}")
        
        # Round values to symbol digits
        entry_price = round(entry_price, symbol_info.digits)
        exit_price = round(exit_price, symbol_info.digits) if exit_price else 0
        target_price = round(target_price, symbol_info.digits) if target_price else 0

        # Clamp volume to symbol's min/max limits
        volume = max(symbol_info.volume_min, min(symbol_info.volume_max, volume))
        
        print(f"        📊 Final volume: {volume} (min: {symbol_info.volume_min}, max: {symbol_info.volume_max})")
        print(f"        🔑 Using Magic Number: {magic_number} (Authorized)")
        
        # Get MT5 order type constant
        mt5_order_type = get_mt5_order_type(order_type)
        if mt5_order_type is None:
            error_msg = f"Invalid order type: {order_type}"
            print(f"         {error_msg}")
            
            if timeframe and current_candle_time:
                print(f"        🗑️ Removing candle time record due to invalid order type...")
                remove_candle_time_record(investor_root, order_data.get('original_symbol', symbol), timeframe, current_candle_time)
            
            return False, None, error_msg, None
        
        # Generate cache key (includes exact symbol with suffix)
        cache_key = f"{symbol}_{mt5_order_type}_{entry_price}_{volume}_{magic_number}"
        
        # Check per-order cache
        if cache_key in per_order_cache:
            error_msg = "Already placed in this run"
            print(f"        ⏭️  SKIP - {error_msg}")
            return False, None, error_msg, cache_key
        
        # ========== RISK MANAGEMENT CHECK ==========
        current_pending = mt5.orders_get() or []
        
        risk_allowed, risk_info = risk_management_for_duplicates(
            investor_root, order_data, current_pending, cancel_exceeding=True
        )
        
        if not risk_allowed:
            error_msg = f"Risk management rejected: {risk_info.get('reason', 'Unknown reason')}"
            print(f"         {error_msg}")
            
            if timeframe and current_candle_time:
                remove_candle_time_record(investor_root, order_data.get('original_symbol', symbol), 
                                        timeframe, current_candle_time)
            
            return False, None, error_msg, cache_key
        elif risk_info.get('cancelled_count', 0) > 0:
            print(f"        ✅ Cleaned up {risk_info['cancelled_count']} exceeding orders")
        
        # Check proximity risk
        if is_hedge:
            print(f"        🛡️ HEDGE ORDER: Skipping proximity risk check")
        elif skip_proximity_check:
            print(f"        ℹ️  Proximity risk check DISABLED - placing order regardless of position proximity")
        else:
            is_risk, risk_position, risk_amount, risk_threshold = check_proximity_risk(order_data, existing_positions)
            
            if is_risk:
                error_msg = f"Too close to position #{risk_position.ticket if risk_position else 'unknown'}"
                print(f"         RISK SKIP - {error_msg} (risk: ${risk_amount:.2f} < threshold: ${risk_threshold:.2f})")
                
                if timeframe and current_candle_time:
                    print(f"        🗑️ Removing candle time record due to proximity risk...")
                    remove_candle_time_record(investor_root, order_data.get('original_symbol', symbol), timeframe, current_candle_time)
                
                return False, None, error_msg, cache_key
        
        # --- GET SUPPORTED FILLING MODES ---
        is_pending = order_type not in ['instant_buy', 'instant_sell']
        filling_modes = get_supported_filling_modes(symbol_info, is_pending)
        
        # --- PREPARE REQUEST TEMPLATE ---
        if order_type in ['instant_buy', 'instant_sell']:
            price = current_ask if order_type == 'instant_buy' else current_bid
            
            request_template = {
                "symbol": symbol,
                "volume": volume,
                "type": mt5_order_type,
                "price": price,
                "deviation": 20,
                "magic": magic_number,  # CRITICAL: Uses authorized magic number
                "comment": f"{strategy_name[:20]} RR{order_data.get('risk_reward', '?')}",
                "type_time": mt5.ORDER_TIME_GTC,
            }
            
            if exit_price:
                request_template["sl"] = exit_price
            if target_price:
                request_template["tp"] = target_price
                
        else:
            request_template = {
                "symbol": symbol,
                "volume": volume,
                "type": mt5_order_type,
                "price": entry_price,
                "deviation": 20,
                "magic": magic_number,  # CRITICAL: Uses authorized magic number
                "comment": f"{strategy_name[:20]} RR{order_data.get('risk_reward', '?')}",
                "type_time": mt5.ORDER_TIME_GTC,
            }
            
            if exit_price:
                request_template["sl"] = exit_price
            if target_price:
                request_template["tp"] = target_price
        
        # --- SEND ORDER ---
        result, used_filling_mode, error_msg = send_order_with_auto_filling(
            request_template, filling_modes, is_pending
        )
        
        if result is None:
            error_msg = f"Order send failed: {error_msg or mt5.last_error()}"
            print(f"         {error_msg}")
            
            if timeframe and current_candle_time:
                print(f"        🗑️ Removing candle time record due to order send failure...")
                remove_candle_time_record(investor_root, order_data.get('original_symbol', symbol), timeframe, current_candle_time)
            
            return False, None, error_msg, cache_key
        
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            error_msg = f"Order failed: {result.comment} (code: {result.retcode})"
            print(f"         {error_msg}")
            
            if timeframe and current_candle_time:
                print(f"        🗑️ Removing candle time record due to order placement failure...")
                remove_candle_time_record(investor_root, order_data.get('original_symbol', symbol), timeframe, current_candle_time)
            
            return False, None, error_msg, cache_key
        
        # Create detailed trade record
        trade_record = {}
        
        for key, value in order_data.items():
            if not key.startswith('_'):
                trade_record[key] = value
        
        if used_filling_mode:
            trade_record['filling_mode_used'] = used_filling_mode
        
        trade_record.update({
            'ticket': result.order,
            'magic': magic_number,  # Record the authorized magic number used
            'placed_timestamp': datetime.now().isoformat(),
            'status': 'pending',
            'mt5_retcode': result.retcode,
            'mt5_comment': result.comment,
            'placed_price': entry_price if order_type not in ['instant_buy', 'instant_sell'] else (request_template['price'] if 'price' in request_template else entry_price),
            'placed_volume': volume,
            'placed_order_type': order_type,
            'strategy_name': strategy_name,
            'symbol_used': symbol,
            'original_symbol_requested': order_data.get('original_symbol', symbol),
            'is_hedge_order': is_hedge
        })
        
        if original_signal:
            for key, value in original_signal.items():
                if key not in trade_record:
                    trade_record[f'original_{key}'] = value
        
        syncing_orders_and_pnl_details(investor_root, trade_record, original_signal)
        
        hedge_msg = " 🛡️[HEDGE]" if is_hedge else ""
        print(f"        ✅ SUCCESS: {order_type.upper()} {symbol} @ {request_template['price'] if 'price' in request_template else entry_price} (Ticket: {result.order}) [Magic: {magic_number}]{hedge_msg}")
        return True, result, None, cache_key

    # --- NEW SUB-FUNCTION 15: PROCESS HEDGE ORDS (NO UNIQUENESS RULES) ---
    def process_hedge_orders_old(hedge_signals, investor_root, per_order_cache, existing_positions, 
                              skip_proximity_check, switch_invalid_to_instant, stats):
        """
        Process all hedge orders without any uniqueness restrictions.
        ALL hedge orders are placed regardless of order type or quantity.
        """
        if not hedge_signals:
            return stats
        
        print(f"\n  🛡️ PROCESSING HEDGE ORDERS ({len(hedge_signals)} signals)")
        print(f"     📌 Hedge orders are EXEMPT from uniqueness rules - ALL will be placed")
        
        hedge_placed = 0
        hedge_failed = 0
        
        for idx, signal_wrapper in enumerate(hedge_signals):
            order_data = signal_wrapper['data']
            original_signal = signal_wrapper.get('original_signal', {})
            signals_path = signal_wrapper.get('path')
            strategy = signal_wrapper.get('strategy', 'unknown')
            symbol = order_data.get('symbol', '')
            order_type = order_data.get('order_type', '').lower()
            hedge_id = order_data.get('hedge_id', 'N/A')
            
            print(f"\n      🛡️ Hedge Order {idx+1}/{len(hedge_signals)}: {order_type} {symbol} [ID: {hedge_id[:20]}...]")
            
            # Execute the order
            success, result, error, cache_key = execute_order(
                order_data, investor_root, per_order_cache, existing_positions,
                original_signal, skip_proximity_check, switch_invalid_to_instant
            )
            
            if success:
                print(f"      ✅ HEDGE ORDER SUCCESS: {order_type} {symbol}")
                hedge_placed += 1
                stats['orders_placed'] += 1
                stats['per_order_cache'].add(cache_key)
                stats['authorized_keys'].add(cache_key)
            else:
                print(f"       HEDGE ORDER FAILED: {error}")
                hedge_failed += 1
                stats['orders_failed'] += 1
                
                # Remove the failed signal from limit_orders.json
                if signals_path:
                    signals_file = Path(signals_path)
                    if signals_file.exists():
                        remove_signal_from_limit_orders(signals_file, order_data)
                        stats['records_removed'] += 1
        
        print(f"\n  🛡️ HEDGE ORDERS SUMMARY: {hedge_placed} placed, {hedge_failed} failed")
        return stats
    
    def process_hedge_orders(hedge_signals, investor_root, per_order_cache, existing_positions, 
                          skip_proximity_check, switch_invalid_to_instant, stats, authorized_magic_number):
        """
        Process all hedge orders without any uniqueness restrictions.
        Uses authorized magic number for all placements.
        """
        if not hedge_signals:
            return stats
        
        print(f"\n  🛡️ PROCESSING HEDGE ORDERS ({len(hedge_signals)} signals)")
        print(f"     📌 Hedge orders are EXEMPT from uniqueness rules - ALL will be placed")
        print(f"     🔑 Using authorized Magic Number: {authorized_magic_number}")
        
        hedge_placed = 0
        hedge_failed = 0
        
        for idx, signal_wrapper in enumerate(hedge_signals):
            order_data = signal_wrapper['data']
            original_signal = signal_wrapper.get('original_signal', {})
            signals_path = signal_wrapper.get('path')
            strategy = signal_wrapper.get('strategy', 'unknown')
            symbol = order_data.get('symbol', '')
            order_type = order_data.get('order_type', '').lower()
            hedge_id = order_data.get('hedge_id', 'N/A')
            
            print(f"\n      🛡️ Hedge Order {idx+1}/{len(hedge_signals)}: {order_type} {symbol} [ID: {hedge_id[:20]}...]")
            
            # Set the magic number in the order data
            order_data['magic'] = authorized_magic_number
            
            success, result, error, cache_key = execute_order(
                order_data, investor_root, per_order_cache, existing_positions,
                original_signal, skip_proximity_check, switch_invalid_to_instant,
                authorized_magic_number  # Pass the authorized magic number
            )
            
            if success:
                print(f"      ✅ HEDGE ORDER SUCCESS: {order_type} {symbol} [Magic: {authorized_magic_number}]")
                hedge_placed += 1
                stats['orders_placed'] += 1
                stats['per_order_cache'].add(cache_key)
                stats['authorized_keys'].add(cache_key)
            else:
                print(f"       HEDGE ORDER FAILED: {error}")
                hedge_failed += 1
                stats['orders_failed'] += 1
                
                if signals_path:
                    signals_file = Path(signals_path)
                    if signals_file.exists():
                        remove_signal_from_limit_orders(signals_file, order_data)
                        stats['records_removed'] += 1
        
        print(f"\n  🛡️ HEDGE ORDERS SUMMARY: {hedge_placed} placed, {hedge_failed} failed")
        return stats

    # --- NEW SUB-FUNCTION 16: PROCESS REGULAR ORDERS WITH FALLBACK LOGIC ---
    def process_regular_orders_with_fallback_old(regular_signals_by_key, investor_root, per_order_cache, existing_positions,
                                      skip_proximity_check, switch_invalid_to_instant, stats):
        """
        Process regular (non-hedge) orders with strict uniqueness rules.
        Only ONE order per (symbol, order_type) will be placed (the newest).
        If the newest fails, falls back to the second newest.
        AFTER placing the latest successfully, cancel all older orders for the same (symbol, order_type).
        
        This function ONLY applies the fallback logic if enable_latest_fallback_to_older_order 
        is set to true in accountmanagement.json. Otherwise, it skips immediately.
        """
        if not regular_signals_by_key:
            return stats
        
        # --- CANCEL OLDER ORDERS SUB-FUNCTION ---
        def cancel_older_orders_for_group(symbol, order_type, placed_ticket):
            """
            Cancel all pending orders for the same (symbol, order_type) that are OLDER
            than the successfully placed order. Keeps only the latest order.
            
            Args:
                symbol: The trading symbol (with suffix)
                order_type: Order type string (buy_stop, sell_stop, etc.)
                placed_ticket: The ticket number of the successfully placed order (to KEEP)
            
            Returns:
                int: Number of orders cancelled
            """
            try:
                # Get all current pending orders
                all_pending = mt5.orders_get(symbol=symbol)
                
                if not all_pending or len(all_pending) == 0:
                    return 0
                
                # Normalize order type for comparison
                order_type_lower = order_type.lower()
                if 'buy' in order_type_lower and 'stop' in order_type_lower:
                    mt5_type_to_match = mt5.ORDER_TYPE_BUY_STOP
                elif 'sell' in order_type_lower and 'stop' in order_type_lower:
                    mt5_type_to_match = mt5.ORDER_TYPE_SELL_STOP
                elif 'buy' in order_type_lower and 'limit' in order_type_lower:
                    mt5_type_to_match = mt5.ORDER_TYPE_BUY_LIMIT
                elif 'sell' in order_type_lower and 'limit' in order_type_lower:
                    mt5_type_to_match = mt5.ORDER_TYPE_SELL_LIMIT
                else:
                    print(f"         Unknown order type for cancellation: {order_type}")
                    return 0
                
                # Find orders to cancel (same symbol, same type, NOT the placed ticket)
                orders_to_cancel = []
                for order in all_pending:
                    if order.type == mt5_type_to_match and order.ticket != placed_ticket:
                        orders_to_cancel.append(order)
                
                if not orders_to_cancel:
                    print(f"         ℹ️ No older orders to cancel for {symbol} {order_type}")
                    return 0
                
                print(f"         🧹 Found {len(orders_to_cancel)} older order(s) for {symbol} {order_type} to clean up...")
                
                cancelled_count = 0
                for order in orders_to_cancel:
                    # Get order timeframe from comment or magic for logging
                    order_comment = order.comment if hasattr(order, 'comment') else ''
                    order_time = datetime.fromtimestamp(order.time_setup).strftime('%Y-%m-%d %H:%M:%S') if hasattr(order, 'time_setup') else 'unknown'
                    
                    print(f"         🗑️ Cancelling older order #{order.ticket} ({symbol} @ {order.price_open}, setup: {order_time})")
                    
                    # Create cancellation request
                    cancel_request = {
                        "action": mt5.TRADE_ACTION_REMOVE,
                        "order": order.ticket
                    }
                    
                    # Send cancellation request
                    result = mt5.order_send(cancel_request)
                    
                    if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                        cancelled_count += 1
                        print(f"         ✅ Successfully cancelled older order #{order.ticket}")
                        
                        # Also remove from tradeshistory.json if it exists
                        try:
                            history_path = investor_root / "tradeshistory.json"
                            if history_path.exists():
                                with open(history_path, 'r', encoding='utf-8') as f:
                                    history = json.load(f)
                                
                                # Update the cancelled order status
                                for trade in history:
                                    if isinstance(trade, dict) and trade.get('ticket') == order.ticket:
                                        trade['status'] = 'cancelled'
                                        trade['cancelled_reason'] = f'Replaced by newer order #{placed_ticket}'
                                        trade['cancelled_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                        break
                                
                                with open(history_path, 'w', encoding='utf-8') as f:
                                    json.dump(history, f, indent=4)
                        except Exception as e:
                            print(f"         Error updating tradeshistory for cancelled order: {e}")
                    else:
                        error_msg = f"Unknown error ({result.retcode})" if result else "No response"
                        if result and result.comment:
                            error_msg = result.comment
                        print(f"         Failed to cancel order #{order.ticket}: {error_msg}")
                
                print(f"         ✅ Cleanup complete: Cancelled {cancelled_count}/{len(orders_to_cancel)} older order(s)")
                return cancelled_count
                
            except Exception as e:
                print(f"         Error during order cleanup: {e}")
                import traceback
                traceback.print_exc()
                return 0
        
        # --- LOAD CONFIGURATION SETTING FOR FALLBACK LOGIC ---
        acc_mgmt_path = investor_root / "accountmanagement.json"
        enable_fallback = False  # Default to disabled
        
        if acc_mgmt_path.exists():
            try:
                with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                settings = config.get("settings", {})
                enable_fallback = settings.get("enable_latest_fallback_to_older_order", False)
                
                if enable_fallback:
                    print(f"\n  📊 PROCESSING REGULAR ORDERS ({len(regular_signals_by_key)} groups)")
                    print(f"     📌 Fallback logic ENABLED - only ONE order per symbol/type (newest first, fallback if needed)")
                    print(f"     🧹 Older orders will be CANCELLED after latest is placed")
                else:
                    print(f"\n  📊 PROCESSING REGULAR ORDERS - FALLBACK LOGIC DISABLED")
                    print(f"     📌 Placing ALL regular orders unconditionally (no grouping, no fallback)")
                    print(f"     💡 To enable latest-fallback logic, set enable_latest_fallback_to_older_order: true in accountmanagement.json")
            except Exception as e:
                print(f"    Error reading accountmanagement.json: {e}")
                print(f"    Defaulting to fallback logic DISABLED - placing all orders")
                enable_fallback = False
        else:
            print(f"    ℹ️ No accountmanagement.json found - fallback logic DISABLED")
            print(f"    📌 Placing ALL regular orders unconditionally")
            enable_fallback = False
        
        # --- IF FALLBACK LOGIC IS DISABLED, PLACE ALL ORDERS WITHOUT GROUPING/FALLBACK ---
        if not enable_fallback:
            print(f"\n  🚀 Placing ALL regular orders unconditionally (fallback logic OFF)")
            
            all_regular_signals = []
            for key, symbol_signals in regular_signals_by_key.items():
                all_regular_signals.extend(symbol_signals)
            
            print(f"     📊 Total regular signals to place: {len(all_regular_signals)}")
            
            for idx, signal_wrapper in enumerate(all_regular_signals):
                order_data = signal_wrapper['data']
                original_signal = signal_wrapper.get('original_signal', {})
                signals_path = signal_wrapper.get('path')
                symbol = order_data.get('symbol', '')
                order_type = order_data.get('order_type', '')
                
                print(f"\n      📊 [{idx+1}/{len(all_regular_signals)}] Placing {order_type} for {symbol}...")
                
                # Execute the order
                success, result, error, cache_key = execute_order(
                    order_data, investor_root, per_order_cache, existing_positions,
                    original_signal, skip_proximity_check, switch_invalid_to_instant
                )
                
                if success:
                    print(f"      ✅ SUCCESS: {order_type} order placed for {symbol}")
                    stats['orders_placed'] += 1
                    per_order_cache.add(cache_key)
                    stats['authorized_keys'].add(cache_key)
                else:
                    print(f"       FAILED: {error}")
                    stats['orders_failed'] += 1
                    
                    # Remove the failed signal from limit_orders.json
                    if signals_path:
                        signals_file = Path(signals_path)
                        if signals_file.exists():
                            remove_signal_from_limit_orders(signals_file, order_data)
                            stats['records_removed'] += 1
            
            stats['fallback_used'] = 0
            stats['older_orders_cancelled'] = 0
            return stats
        
        # --- FALLBACK LOGIC IS ENABLED - PROCEED WITH NORMAL FALLBACK PROCESSING ---
        print(f"\n  🔄 FALLBACK LOGIC ENABLED - applying latest-first ordering with fallback and old order cleanup")
        
        fallback_used_count = 0
        older_orders_cancelled_count = 0
        
        for key, symbol_signals in regular_signals_by_key.items():
            # Sort signals by current_candle_time (newest first)
            sorted_signals = sorted(symbol_signals, 
                                key=lambda x: x['data'].get('current_candle_time', ''), 
                                reverse=True)
            
            symbol = sorted_signals[0]['data'].get('symbol', '')
            order_type = sorted_signals[0]['data'].get('order_type', '')
            
            print(f"\n    🎯 Processing group: {key} ({len(sorted_signals)} signals)")
            print(f"       - Newest signal time: {sorted_signals[0]['data'].get('current_candle_time', 'N/A')}")
            if len(sorted_signals) > 1:
                print(f"       - Has {len(sorted_signals)-1} fallback/older signal(s) available")
            
            # Track if we successfully placed an order for this group
            placed_ticket = None
            
            # Try to place the newest order first
            for idx, signal_wrapper in enumerate(sorted_signals):
                order_data = signal_wrapper['data']
                original_signal = signal_wrapper.get('original_signal', {})
                signals_path = signal_wrapper.get('path')
                
                is_fallback = idx > 0
                order_label = "FALLBACK" if is_fallback else "PRIMARY"
                
                print(f"\n      🔄 [{order_label}] Attempting to place {order_type} for {symbol}...")
                
                # Execute the order
                success, result, error, cache_key = execute_order(
                    order_data, investor_root, per_order_cache, existing_positions,
                    original_signal, skip_proximity_check, switch_invalid_to_instant
                )
                
                if success:
                    placed_ticket = result.order
                    print(f"      ✅ [{order_label}] SUCCESS: {order_type} order placed for {symbol} (Ticket: {placed_ticket})")
                    stats['orders_placed'] += 1
                    per_order_cache.add(cache_key)
                    stats['authorized_keys'].add(cache_key)
                    
                    if is_fallback:
                        fallback_used_count += 1
                        print(f"      🔄 FALLBACK SUCCESSFUL: Used fallback signal for {symbol} {order_type}")
                    
                    # --- 🧹 CLEANUP: Cancel all older orders for the same (symbol, order_type) ---
                    print(f"\n      🧹 CLEANUP: Cancelling older orders for {symbol} {order_type}...")
                    cancelled = cancel_older_orders_for_group(symbol, order_type, placed_ticket)
                    older_orders_cancelled_count += cancelled
                    
                    # If order succeeded, break out of fallback loop
                    break
                    
                else:
                    print(f"       [{order_label}] FAILED: {error}")
                    
                    # Remove the failed signal from limit_orders.json
                    if signals_path:
                        signals_file = Path(signals_path)
                        if signals_file.exists():
                            remove_signal_from_limit_orders(signals_file, order_data)
                            stats['records_removed'] += 1
                    
                    # If this was the last signal and it failed
                    if idx == len(sorted_signals) - 1:
                        print(f"       All attempts failed for {symbol} {order_type}")
                        stats['orders_failed'] += 1
        
        # Update stats
        stats['fallback_used'] = fallback_used_count
        stats['older_orders_cancelled'] = older_orders_cancelled_count
        
        if older_orders_cancelled_count > 0:
            print(f"\n  🧹 CLEANUP SUMMARY: Cancelled {older_orders_cancelled_count} older order(s) across all groups")
        
        return stats
    
    def process_regular_orders_with_fallback(regular_signals_by_key, investor_root, per_order_cache, existing_positions,
                                          skip_proximity_check, switch_invalid_to_instant, stats, authorized_magic_number):
        """
        Process regular (non-hedge) orders with strict uniqueness rules.
        Uses authorized magic number for all placements.
        """
        if not regular_signals_by_key:
            return stats
        
        # --- CANCEL OLDER ORDERS SUB-FUNCTION ---
        def cancel_older_orders_for_group(symbol, order_type, placed_ticket):
            # ... (same as before, no changes needed)
            try:
                all_pending = mt5.orders_get(symbol=symbol)
                
                if not all_pending or len(all_pending) == 0:
                    return 0
                
                order_type_lower = order_type.lower()
                if 'buy' in order_type_lower and 'stop' in order_type_lower:
                    mt5_type_to_match = mt5.ORDER_TYPE_BUY_STOP
                elif 'sell' in order_type_lower and 'stop' in order_type_lower:
                    mt5_type_to_match = mt5.ORDER_TYPE_SELL_STOP
                elif 'buy' in order_type_lower and 'limit' in order_type_lower:
                    mt5_type_to_match = mt5.ORDER_TYPE_BUY_LIMIT
                elif 'sell' in order_type_lower and 'limit' in order_type_lower:
                    mt5_type_to_match = mt5.ORDER_TYPE_SELL_LIMIT
                else:
                    print(f"         Unknown order type for cancellation: {order_type}")
                    return 0
                
                orders_to_cancel = []
                for order in all_pending:
                    if order.type == mt5_type_to_match and order.ticket != placed_ticket:
                        orders_to_cancel.append(order)
                
                if not orders_to_cancel:
                    print(f"         ℹ️ No older orders to cancel for {symbol} {order_type}")
                    return 0
                
                print(f"         🧹 Found {len(orders_to_cancel)} older order(s) for {symbol} {order_type} to clean up...")
                
                cancelled_count = 0
                for order in orders_to_cancel:
                    order_time = datetime.fromtimestamp(order.time_setup).strftime('%Y-%m-%d %H:%M:%S') if hasattr(order, 'time_setup') else 'unknown'
                    
                    print(f"         🗑️ Cancelling older order #{order.ticket} ({symbol} @ {order.price_open}, setup: {order_time})")
                    
                    cancel_request = {
                        "action": mt5.TRADE_ACTION_REMOVE,
                        "order": order.ticket
                    }
                    
                    result = mt5.order_send(cancel_request)
                    
                    if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                        cancelled_count += 1
                        print(f"         ✅ Successfully cancelled older order #{order.ticket}")
                        
                        try:
                            history_path = investor_root / "tradeshistory.json"
                            if history_path.exists():
                                with open(history_path, 'r', encoding='utf-8') as f:
                                    history = json.load(f)
                                
                                for trade in history:
                                    if isinstance(trade, dict) and trade.get('ticket') == order.ticket:
                                        trade['status'] = 'cancelled'
                                        trade['cancelled_reason'] = f'Replaced by newer order #{placed_ticket}'
                                        trade['cancelled_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                        break
                                
                                with open(history_path, 'w', encoding='utf-8') as f:
                                    json.dump(history, f, indent=4)
                        except Exception as e:
                            print(f"         Error updating tradeshistory for cancelled order: {e}")
                    else:
                        error_msg = f"Unknown error ({result.retcode})" if result else "No response"
                        if result and result.comment:
                            error_msg = result.comment
                        print(f"         Failed to cancel order #{order.ticket}: {error_msg}")
                
                print(f"         ✅ Cleanup complete: Cancelled {cancelled_count}/{len(orders_to_cancel)} older order(s)")
                return cancelled_count
                
            except Exception as e:
                print(f"         Error during order cleanup: {e}")
                import traceback
                traceback.print_exc()
                return 0
        
        # --- LOAD CONFIGURATION SETTING FOR FALLBACK LOGIC ---
        acc_mgmt_path = investor_root / "accountmanagement.json"
        enable_fallback = False
        
        if acc_mgmt_path.exists():
            try:
                with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                settings = config.get("settings", {})
                enable_fallback = settings.get("enable_latest_fallback_to_older_order", False)
                
                if enable_fallback:
                    print(f"\n  📊 PROCESSING REGULAR ORDERS ({len(regular_signals_by_key)} groups)")
                    print(f"     📌 Fallback logic ENABLED - only ONE order per symbol/type (newest first, fallback if needed)")
                    print(f"     🧹 Older orders will be CANCELLED after latest is placed")
                    print(f"     🔑 Using authorized Magic Number: {authorized_magic_number}")
                else:
                    print(f"\n  📊 PROCESSING REGULAR ORDERS - FALLBACK LOGIC DISABLED")
                    print(f"     📌 Placing ALL regular orders unconditionally (no grouping, no fallback)")
                    print(f"     🔑 Using authorized Magic Number: {authorized_magic_number}")
            except Exception as e:
                print(f"    Error reading accountmanagement.json: {e}")
                print(f"    Defaulting to fallback logic DISABLED - placing all orders")
                enable_fallback = False
        else:
            print(f"    ℹ️ No accountmanagement.json found - fallback logic DISABLED")
            print(f"    📌 Placing ALL regular orders unconditionally")
            print(f"    🔑 Using authorized Magic Number: {authorized_magic_number}")
            enable_fallback = False
        
        # --- IF FALLBACK LOGIC IS DISABLED ---
        if not enable_fallback:
            print(f"\n  🚀 Placing ALL regular orders unconditionally (fallback logic OFF)")
            
            all_regular_signals = []
            for key, symbol_signals in regular_signals_by_key.items():
                all_regular_signals.extend(symbol_signals)
            
            print(f"     📊 Total regular signals to place: {len(all_regular_signals)}")
            
            for idx, signal_wrapper in enumerate(all_regular_signals):
                order_data = signal_wrapper['data']
                original_signal = signal_wrapper.get('original_signal', {})
                signals_path = signal_wrapper.get('path')
                symbol = order_data.get('symbol', '')
                order_type = order_data.get('order_type', '')
                
                print(f"\n      📊 [{idx+1}/{len(all_regular_signals)}] Placing {order_type} for {symbol}...")
                
                # Set the magic number in the order data
                order_data['magic'] = authorized_magic_number
                
                success, result, error, cache_key = execute_order(
                    order_data, investor_root, per_order_cache, existing_positions,
                    original_signal, skip_proximity_check, switch_invalid_to_instant,
                    authorized_magic_number
                )
                
                if success:
                    print(f"      ✅ SUCCESS: {order_type} order placed for {symbol} [Magic: {authorized_magic_number}]")
                    stats['orders_placed'] += 1
                    per_order_cache.add(cache_key)
                    stats['authorized_keys'].add(cache_key)
                else:
                    print(f"       FAILED: {error}")
                    stats['orders_failed'] += 1
                    
                    if signals_path:
                        signals_file = Path(signals_path)
                        if signals_file.exists():
                            remove_signal_from_limit_orders(signals_file, order_data)
                            stats['records_removed'] += 1
            
            stats['fallback_used'] = 0
            stats['older_orders_cancelled'] = 0
            return stats
        
        # --- FALLBACK LOGIC IS ENABLED ---
        print(f"\n  🔄 FALLBACK LOGIC ENABLED - applying latest-first ordering with fallback and old order cleanup")
        
        fallback_used_count = 0
        older_orders_cancelled_count = 0
        
        for key, symbol_signals in regular_signals_by_key.items():
            sorted_signals = sorted(symbol_signals, 
                                key=lambda x: x['data'].get('current_candle_time', ''), 
                                reverse=True)
            
            symbol = sorted_signals[0]['data'].get('symbol', '')
            order_type = sorted_signals[0]['data'].get('order_type', '')
            
            print(f"\n    🎯 Processing group: {key} ({len(sorted_signals)} signals)")
            print(f"       - Newest signal time: {sorted_signals[0]['data'].get('current_candle_time', 'N/A')}")
            if len(sorted_signals) > 1:
                print(f"       - Has {len(sorted_signals)-1} fallback/older signal(s) available")
            
            placed_ticket = None
            
            for idx, signal_wrapper in enumerate(sorted_signals):
                order_data = signal_wrapper['data']
                original_signal = signal_wrapper.get('original_signal', {})
                signals_path = signal_wrapper.get('path')
                
                is_fallback = idx > 0
                order_label = "FALLBACK" if is_fallback else "PRIMARY"
                
                print(f"\n      🔄 [{order_label}] Attempting to place {order_type} for {symbol}...")
                
                # Set the magic number in the order data
                order_data['magic'] = authorized_magic_number
                
                success, result, error, cache_key = execute_order(
                    order_data, investor_root, per_order_cache, existing_positions,
                    original_signal, skip_proximity_check, switch_invalid_to_instant,
                    authorized_magic_number
                )
                
                if success:
                    placed_ticket = result.order
                    print(f"      ✅ [{order_label}] SUCCESS: {order_type} order placed for {symbol} (Ticket: {placed_ticket}) [Magic: {authorized_magic_number}]")
                    stats['orders_placed'] += 1
                    per_order_cache.add(cache_key)
                    stats['authorized_keys'].add(cache_key)
                    
                    if is_fallback:
                        fallback_used_count += 1
                        print(f"      🔄 FALLBACK SUCCESSFUL: Used fallback signal for {symbol} {order_type}")
                    
                    print(f"\n      🧹 CLEANUP: Cancelling older orders for {symbol} {order_type}...")
                    cancelled = cancel_older_orders_for_group(symbol, order_type, placed_ticket)
                    older_orders_cancelled_count += cancelled
                    break
                    
                else:
                    print(f"       [{order_label}] FAILED: {error}")
                    
                    if signals_path:
                        signals_file = Path(signals_path)
                        if signals_file.exists():
                            remove_signal_from_limit_orders(signals_file, order_data)
                            stats['records_removed'] += 1
                    
                    if idx == len(sorted_signals) - 1:
                        print(f"       All attempts failed for {symbol} {order_type}")
                        stats['orders_failed'] += 1
        
        stats['fallback_used'] = fallback_used_count
        stats['older_orders_cancelled'] = older_orders_cancelled_count
        
        if older_orders_cancelled_count > 0:
            print(f"\n  🧹 CLEANUP SUMMARY: Cancelled {older_orders_cancelled_count} older order(s) across all groups")
        
        return stats

    # --- MAIN EXECUTION FLOW ---
    def main_old():
        print("\n" + "="*80)
        print("🚀 STARTING ENHANCED ORDER PLACEMENT ENGINE (WITH HEDGE ORDER EXEMPTION & FALLBACK)")
        print("="*80)
        
        investor_ids = [inv_id] if inv_id else list(usersdictionary.keys())
        any_orders_placed = False
        global_stats = {
            'investors_processed': 0,
            'investors_blocked': 0,
            'total_signals_found': 0,
            'total_hedge_signals': 0,
            'total_regular_signals': 0,
            'total_orders_placed': 0,
            'total_orders_failed': 0,
            'total_orders_cancelled_regulation': 0,
            'total_suffix_retries_successful': 0,
            'total_running_positions': 0,
            'total_pending_orders': 0,
            'total_candle_records_removed': 0,
            'total_proximity_check_disabled': 0,
            'total_orders_converted': 0,
            'total_fallback_used': 0,
            'total_hedge_orders_placed': 0,
            'total_hedge_orders_failed': 0
        }

        for user_brokerid in investor_ids:
            print(f"\n{'='*60}")
            print(f"📋 INVESTOR: {user_brokerid}")
            print(f"{'='*60}")
            
            resolution_cache = {}
            investor_root = Path(INV_PATH) / user_brokerid
            
            if not investor_root.exists():
                print(f"   Investor root not found: {investor_root}")
                continue
            
            # STEP 1: Check authorization status
            can_proceed, activities = check_authorization_status(investor_root)
            
            if not can_proceed:
                print(f"  🚫 INVESTOR BLOCKED - unauthorized actions detected without bypass")
                global_stats['investors_blocked'] += 1
                continue
            
            # STEP 2: Load proximity risk setting from accountmanagement.json
            print(f"\n  ⚙️  Loading configuration from accountmanagement.json...")
            skip_proximity_check = not get_proximity_risk_setting(investor_root)
            
            if skip_proximity_check:
                global_stats['total_proximity_check_disabled'] += 1
            
            # STEP 3: Load invalid order conversion setting
            switch_invalid_to_instant = get_switch_invalid_setting(investor_root)
            
            # STEP 4: Take initial snapshot of current pending orders and positions (BEFORE sync)
            print(f"\n  📸 Taking initial snapshot of current orders/positions...")
            snapshot_success, snapshot_stats = update_orders_status_in_tradeshistory(investor_root)
            
            # STEP 5: Sync existing tradeshistory.json (to get current status and assign position IDs)
            print(f"\n  🔄 Syncing tradeshistory.json with MT5 (checking all orders/positions)...")
            sync_success, sync_stats = syncing_orders_and_pnl_details(investor_root)
            
            if sync_stats:
                global_stats['total_running_positions'] += sync_stats.get('running_positions', 0)
                global_stats['total_pending_orders'] += sync_stats.get('pending_orders', 0)
                print(f"  📊 Current status: {sync_stats.get('running_positions', 0)} running positions, "
                    f"{sync_stats.get('pending_orders', 0)} pending orders")
            
            # ========== SCAN AND CLEANUP EXISTING PENDING ORDERS ==========
            print(f"\n  🧹 SCANNING EXISTING PENDING ORDERS FOR RISK VIOLATIONS...")
            current_pending_orders = mt5.orders_get() or []
            
            if current_pending_orders:
                print(f"  📋 Found {len(current_pending_orders)} existing pending orders:")
                for order in current_pending_orders:
                    order_type_name = "BUY_STOP" if order.type == mt5.ORDER_TYPE_BUY_STOP else "SELL_STOP" if order.type == mt5.ORDER_TYPE_SELL_STOP else "BUY_LIMIT" if order.type == mt5.ORDER_TYPE_BUY_LIMIT else "SELL_LIMIT"
                    print(f"     - #{order.ticket}: {order_type_name} {order.symbol} @ {order.price_open} vol {order.volume_initial}")
                
                # Run cleanup scan without evaluating a new order
                risk_allowed, cleanup_info = risk_management_for_duplicates(
                    investor_root, None, current_pending_orders, cancel_exceeding=True, check_only=True
                )
                
                if cleanup_info.get('cancelled_count', 0) > 0:
                    print(f"\n  ✅ Cleaned up {cleanup_info['cancelled_count']} violating order(s)")
                    
                    # Refresh tradeshistory after cleanup
                    print(f"  🔄 Refreshing tradeshistory after cleanup...")
                    final_sync, final_stats = syncing_orders_and_pnl_details(investor_root)
                else:
                    print(f"\n  ✅ No risk violations found in existing orders")
            else:
                print(f"  ℹ️ No existing pending orders to scan")
            # ========== END OF SCAN ==========
            
            # STEP 6: Collect signals from ALL strategy folders (separate hedge from regular)
            all_signals, hedge_signals, regular_signals = collect_orders_from_signals(investor_root, resolution_cache)
            
            if not all_signals:
                print(f"  ℹ️  No signals found for {user_brokerid}")
                continue
            
            global_stats['investors_processed'] += 1
            global_stats['total_signals_found'] += len(all_signals)
            global_stats['total_hedge_signals'] += len(hedge_signals)
            global_stats['total_regular_signals'] += len(regular_signals)
            
            # Count successful suffix retries
            suffix_retries = sum(1 for s in all_signals if s['data'].get('used_suffix', 'none') != 'none')
            global_stats['total_suffix_retries_successful'] += suffix_retries
            if suffix_retries > 0:
                print(f"  🔄 Successfully applied suffix retry to {suffix_retries} signals")
            
            # STEP 7: Get existing positions for risk check
            existing_positions = mt5.positions_get() or []
            print(f"  📊 Found {len(existing_positions)} existing open positions for risk check")
            
            # STEP 8: Group regular signals by symbol and order_type (buy_stop/sell_stop)
            # Hedge orders are handled separately without grouping
            regular_signals_by_key = {}
            
            for signal_wrapper in regular_signals:
                order_data = signal_wrapper['data']
                symbol = order_data.get('symbol', '')
                order_type = order_data.get('order_type', '').lower()
                
                # Only process stop orders for regular signals
                if order_type not in ['buy_stop', 'sell_stop']:
                    print(f"  ℹ️  Skipping non-stop regular order: {order_type} for {symbol}")
                    continue
                
                key = f"{symbol}_{order_type}"
                
                if key not in regular_signals_by_key:
                    regular_signals_by_key[key] = []
                
                regular_signals_by_key[key].append(signal_wrapper)
            
            print(f"  📊 Grouped regular signals into {len(regular_signals_by_key)} symbol/order_type groups")
            print(f"  🛡️ Hedge signals: {len(hedge_signals)} (will ALL be placed)")
            
            # STEP 9: Per-order cache for this run
            per_order_cache = set()
            
            # STEP 10: Build authorized keys for regulation
            authorized_keys = set()
            
            # STEP 11: Process hedge orders FIRST (no uniqueness rules, all placed)
            investor_stats = {
                'orders_placed': 0,
                'orders_failed': 0,
                'records_removed': 0,
                'per_order_cache': per_order_cache,
                'authorized_keys': authorized_keys,
                'fallback_used': 0
            }
            
            if hedge_signals:
                investor_stats = process_hedge_orders(
                    hedge_signals, investor_root, per_order_cache, existing_positions,
                    skip_proximity_check, switch_invalid_to_instant, investor_stats
                )
            
            # STEP 12: Process regular orders with fallback logic (only ONE per symbol/type)
            if regular_signals_by_key:
                investor_stats = process_regular_orders_with_fallback(
                    regular_signals_by_key, investor_root, per_order_cache, existing_positions,
                    skip_proximity_check, switch_invalid_to_instant, investor_stats
                )
            
            # Update global stats
            global_stats['total_orders_placed'] += investor_stats['orders_placed']
            global_stats['total_orders_failed'] += investor_stats['orders_failed']
            global_stats['total_candle_records_removed'] += investor_stats['records_removed']
            global_stats['total_fallback_used'] += investor_stats['fallback_used']
            
            # Track hedge-specific stats
            hedge_placed = sum(1 for s in hedge_signals if s.get('_placed', False))
            global_stats['total_hedge_orders_placed'] += hedge_placed
            global_stats['total_hedge_orders_failed'] += len(hedge_signals) - hedge_placed
          
            # STEP 14: Take final snapshot of current pending orders and positions (AFTER placement and regulation)
            print(f"\n  📸 Taking final snapshot of current orders/positions...")
            final_snapshot_success, final_snapshot_stats = update_orders_status_in_tradeshistory(investor_root)
            
            # STEP 15: Final sync to capture any changes from regulation (ONLY position details, NO status changes)
            print(f"\n  🔄 Final sync to capture position details...")
            final_sync, final_stats = syncing_orders_and_pnl_details(investor_root)
            
            if final_stats:
                print(f"  📊 Final status: {final_stats.get('running_positions', 0)} running positions, "
                    f"{final_stats.get('pending_orders', 0)} pending orders")
            
            
            if investor_stats['orders_placed'] > 0:
                any_orders_placed = True
        return any_orders_placed
    
    # --- MAIN EXECUTION FLOW ---
    def main():
        print("\n" + "="*80)
        print("🚀 STARTING ENHANCED ORDER PLACEMENT ENGINE (WITH HEDGE ORDER EXEMPTION & FALLBACK)")
        print("="*80)
        
        investor_ids = [inv_id] if inv_id else list(usersdictionary.keys())
        any_orders_placed = False
        global_stats = {
            'investors_processed': 0,
            'investors_blocked': 0,
            'total_signals_found': 0,
            'total_hedge_signals': 0,
            'total_regular_signals': 0,
            'total_orders_placed': 0,
            'total_orders_failed': 0,
            'total_orders_cancelled_regulation': 0,
            'total_suffix_retries_successful': 0,
            'total_running_positions': 0,
            'total_pending_orders': 0,
            'total_candle_records_removed': 0,
            'total_proximity_check_disabled': 0,
            'total_orders_converted': 0,
            'total_fallback_used': 0,
            'total_hedge_orders_placed': 0,
            'total_hedge_orders_failed': 0
        }

        for user_brokerid in investor_ids:
            print(f"\n{'='*60}")
            print(f"📋 INVESTOR: {user_brokerid}")
            print(f"{'='*60}")
            
            resolution_cache = {}
            investor_root = Path(INV_PATH) / user_brokerid
            
            if not investor_root.exists():
                print(f"   Investor root not found: {investor_root}")
                continue
            
            # ============================================================
            # GET LOGIN_ID FROM BROKER CONFIG FOR MAGIC NUMBER
            # ============================================================
            broker_cfg = usersdictionary.get(user_brokerid)
            if not broker_cfg:
                print(f"  No broker config found for {user_brokerid}")
                continue
            
            login_id = broker_cfg.get('LOGIN_ID', '')
            if not login_id:
                print(f"  No LOGIN_ID found for {user_brokerid}")
                continue
            
            # Construct authorized magic number: LOGIN_ID + USER_ID
            authorized_magic_number = None
            try:
                authorized_magic_number = int(str(login_id) + str(user_brokerid))
                print(f"  🔑 Authorized Magic Number: {authorized_magic_number}")
                print(f"     (LOGIN_ID: {login_id} + USER_ID: {user_brokerid})")
            except (ValueError, TypeError) as e:
                print(f"  Could not create magic number: {e}")
                continue
            
            # ============================================================
            # STEP 1: Check authorization status (bypass, auto-trading)
            # ============================================================
            can_proceed, activities, magic_from_activities = check_authorization_status(
                investor_root, login_id, user_brokerid
            )
            
            # Use the magic number from activities if available, otherwise use constructed
            if magic_from_activities:
                authorized_magic_number = magic_from_activities
                print(f"  🔑 Using Magic Number from activities.json: {authorized_magic_number}")
            
            if not can_proceed:
                print(f"  🚫 INVESTOR BLOCKED - unauthorized actions detected without bypass")
                global_stats['investors_blocked'] += 1
                continue
            
            # ============================================================
            # STEP 2: Load proximity risk setting from accountmanagement.json
            # ============================================================
            print(f"\n  ⚙️  Loading configuration from accountmanagement.json...")
            skip_proximity_check = not get_proximity_risk_setting(investor_root)
            
            if skip_proximity_check:
                global_stats['total_proximity_check_disabled'] += 1
            
            # ============================================================
            # STEP 3: Load invalid order conversion setting
            # ============================================================
            switch_invalid_to_instant = get_switch_invalid_setting(investor_root)
            
            # ============================================================
            # STEP 4: Take initial snapshot of current pending orders and positions
            # ============================================================
            print(f"\n  📸 Taking initial snapshot of current orders/positions...")
            snapshot_success, snapshot_stats = update_orders_status_in_tradeshistory(investor_root)
            
            # ============================================================
            # STEP 5: Sync existing tradeshistory.json
            # ============================================================
            print(f"\n  🔄 Syncing tradeshistory.json with MT5 (checking all orders/positions)...")
            sync_success, sync_stats = syncing_orders_and_pnl_details(investor_root)
            
            if sync_stats:
                global_stats['total_running_positions'] += sync_stats.get('running_positions', 0)
                global_stats['total_pending_orders'] += sync_stats.get('pending_orders', 0)
                print(f"  📊 Current status: {sync_stats.get('running_positions', 0)} running positions, "
                    f"{sync_stats.get('pending_orders', 0)} pending orders")
            
            # ============================================================
            # STEP 6: SCAN AND CLEANUP EXISTING PENDING ORDERS FOR RISK VIOLATIONS
            # ============================================================
            print(f"\n  🧹 SCANNING EXISTING PENDING ORDERS FOR RISK VIOLATIONS...")
            current_pending_orders = mt5.orders_get() or []
            
            if current_pending_orders:
                print(f"  📋 Found {len(current_pending_orders)} existing pending orders:")
                for order in current_pending_orders:
                    if order.type == mt5.ORDER_TYPE_BUY_STOP:
                        order_type_name = "BUY_STOP"
                    elif order.type == mt5.ORDER_TYPE_SELL_STOP:
                        order_type_name = "SELL_STOP"
                    elif order.type == mt5.ORDER_TYPE_BUY_LIMIT:
                        order_type_name = "BUY_LIMIT"
                    elif order.type == mt5.ORDER_TYPE_SELL_LIMIT:
                        order_type_name = "SELL_LIMIT"
                    else:
                        order_type_name = f"TYPE_{order.type}"
                    print(f"     - #{order.ticket}: {order_type_name} {order.symbol} @ {order.price_open} vol {order.volume_initial} [Magic: {order.magic}]")
                
                # Run cleanup scan without evaluating a new order
                risk_allowed, cleanup_info = risk_management_for_duplicates(
                    investor_root, None, current_pending_orders, cancel_exceeding=True, check_only=True
                )
                
                if cleanup_info.get('cancelled_count', 0) > 0:
                    print(f"\n  ✅ Cleaned up {cleanup_info['cancelled_count']} violating order(s)")
                    global_stats['total_orders_cancelled_regulation'] += cleanup_info['cancelled_count']
                    
                    # Refresh tradeshistory after cleanup
                    print(f"  🔄 Refreshing tradeshistory after cleanup...")
                    final_sync, final_stats = syncing_orders_and_pnl_details(investor_root)
                else:
                    print(f"\n  ✅ No risk violations found in existing orders")
            else:
                print(f"  ℹ️ No existing pending orders to scan")
            
            # ============================================================
            # STEP 7: Collect signals from ALL strategy folders
            # ============================================================
            all_signals, hedge_signals, regular_signals = collect_orders_from_signals(investor_root, resolution_cache)
            
            if not all_signals:
                print(f"  ℹ️  No signals found for {user_brokerid}")
                continue
            
            global_stats['investors_processed'] += 1
            global_stats['total_signals_found'] += len(all_signals)
            global_stats['total_hedge_signals'] += len(hedge_signals)
            global_stats['total_regular_signals'] += len(regular_signals)
            
            # Count successful suffix retries
            suffix_retries = sum(1 for s in all_signals if s['data'].get('used_suffix', 'none') != 'none')
            global_stats['total_suffix_retries_successful'] += suffix_retries
            if suffix_retries > 0:
                print(f"  🔄 Successfully applied suffix retry to {suffix_retries} signals")
            
            # ============================================================
            # STEP 8: Get existing positions for risk check
            # ============================================================
            existing_positions = mt5.positions_get() or []
            print(f"  📊 Found {len(existing_positions)} existing open positions for risk check")
            
            # ============================================================
            # STEP 9: Group regular signals by symbol and order_type
            # ============================================================
            regular_signals_by_key = {}
            
            for signal_wrapper in regular_signals:
                order_data = signal_wrapper['data']
                symbol = order_data.get('symbol', '')
                order_type = order_data.get('order_type', '').lower()
                
                # Only process stop orders for regular signals
                if order_type not in ['buy_stop', 'sell_stop']:
                    print(f"  ℹ️  Skipping non-stop regular order: {order_type} for {symbol}")
                    continue
                
                key = f"{symbol}_{order_type}"
                
                if key not in regular_signals_by_key:
                    regular_signals_by_key[key] = []
                
                regular_signals_by_key[key].append(signal_wrapper)
            
            print(f"  📊 Grouped regular signals into {len(regular_signals_by_key)} symbol/order_type groups")
            print(f"  🛡️ Hedge signals: {len(hedge_signals)} (will ALL be placed)")
            print(f"  🔑 All orders will use Magic Number: {authorized_magic_number}")
            
            # ============================================================
            # STEP 10: Per-order cache for this run
            # ============================================================
            per_order_cache = set()
            
            # ============================================================
            # STEP 11: Build authorized keys for regulation
            # ============================================================
            authorized_keys = set()
            
            # ============================================================
            # STEP 12: Process hedge orders FIRST (no uniqueness rules)
            # ============================================================
            investor_stats = {
                'orders_placed': 0,
                'orders_failed': 0,
                'records_removed': 0,
                'per_order_cache': per_order_cache,
                'authorized_keys': authorized_keys,
                'fallback_used': 0,
                'older_orders_cancelled': 0
            }
            
            if hedge_signals:
                investor_stats = process_hedge_orders(
                    hedge_signals, investor_root, per_order_cache, existing_positions,
                    skip_proximity_check, switch_invalid_to_instant, investor_stats,
                    authorized_magic_number
                )
            
            # ============================================================
            # STEP 13: Process regular orders with fallback logic
            # ============================================================
            if regular_signals_by_key:
                investor_stats = process_regular_orders_with_fallback(
                    regular_signals_by_key, investor_root, per_order_cache, existing_positions,
                    skip_proximity_check, switch_invalid_to_instant, investor_stats,
                    authorized_magic_number
                )
            
            # Update global stats
            global_stats['total_orders_placed'] += investor_stats['orders_placed']
            global_stats['total_orders_failed'] += investor_stats['orders_failed']
            global_stats['total_candle_records_removed'] += investor_stats['records_removed']
            global_stats['total_fallback_used'] += investor_stats['fallback_used']
            
            # Track hedge-specific stats (approximate - actual placed tracked in process_hedge_orders)
            hedge_placed = investor_stats['orders_placed'] - len(regular_signals_by_key) if regular_signals_by_key else investor_stats['orders_placed']
            global_stats['total_hedge_orders_placed'] += hedge_placed if hedge_placed > 0 else 0
            global_stats['total_hedge_orders_failed'] += len(hedge_signals) - hedge_placed if hedge_signals else 0
        
            # ============================================================
            # STEP 14: Take final snapshot after placement
            # ============================================================
            print(f"\n  📸 Taking final snapshot of current orders/positions...")
            final_snapshot_success, final_snapshot_stats = update_orders_status_in_tradeshistory(investor_root)
            
            # ============================================================
            # STEP 15: Final sync to capture position details
            # ============================================================
            print(f"\n  🔄 Final sync to capture position details...")
            final_sync, final_stats = syncing_orders_and_pnl_details(investor_root)
            
            if final_stats:
                print(f"  📊 Final status: {final_stats.get('running_positions', 0)} running positions, "
                    f"{final_stats.get('pending_orders', 0)} pending orders")
            
            # ============================================================
            # STEP 16: Investor Summary
            # ============================================================
            print(f"\n  └─ 📈 INVESTOR {user_brokerid} SUMMARY")
            print(f"       • Magic Number: {authorized_magic_number}")
            print(f"       • Orders Placed: {investor_stats['orders_placed']}")
            print(f"       • Orders Failed: {investor_stats['orders_failed']}")
            print(f"       • Fallback Used: {investor_stats['fallback_used']}")
            print(f"       • Old Orders Cancelled: {investor_stats['older_orders_cancelled']}")
            
            if investor_stats['orders_placed'] > 0:
                any_orders_placed = True
        
        # ============================================================
        # FINAL GLOBAL SUMMARY
        # ============================================================
        print("\n" + "="*80)
        print("  📊 FINAL EXECUTION SUMMARY".ljust(79) + "=")
        print("="*80)
        print(f"│  Investors processed:        {global_stats['investors_processed']}")
        print(f"│  Investors blocked:          {global_stats['investors_blocked']}")
        print(f"│  Total signals found:        {global_stats['total_signals_found']}")
        print(f"│    - Hedge signals:          {global_stats['total_hedge_signals']}")
        print(f"│    - Regular signals:        {global_stats['total_regular_signals']}")
        print(f"│  Orders placed:              {global_stats['total_orders_placed']}")
        print(f"│  Orders failed:              {global_stats['total_orders_failed']}")
        print(f"│  Orders cancelled (risk):    {global_stats['total_orders_cancelled_regulation']}")
        print(f"│  Fallback used:              {global_stats['total_fallback_used']}")
        print(f"│  Suffix retries successful:  {global_stats['total_suffix_retries_successful']}")
        print(f"│  Candle records removed:     {global_stats['total_candle_records_removed']}")
        print(f"│  Proximity check disabled:   {global_stats['total_proximity_check_disabled']}")
        print("="*80)
        
        if any_orders_placed:
            print("✅ ORDER PLACEMENT ENGINE COMPLETED SUCCESSFULLY")
        else:
            print("⚠️ NO ORDERS WERE PLACED")
        print("="*80 + "\n")
        
        return any_orders_placed
    main()

def clean_trades_history(inv_id=None):
    """
    Clean tradeshistory.json files - remove records older than execution start date.
    Records without valid dates are ALWAYS removed.
    If no start date found, ALL records are removed.
    """
    import json
    from pathlib import Path
    from datetime import datetime
    
    print("\n" + "="*60)
    print("🧹 CLEANING TRADES HISTORY")
    print("="*60)
    
    # Get investors
    if inv_id:
        investor_ids = [inv_id] if inv_id in usersdictionary else []
        if not investor_ids:
            print(f"Investor {inv_id} not found")
            return {'error': f'Investor {inv_id} not found'}
    else:
        investor_ids = list(usersdictionary.keys())
    
    print(f"📋 Investors: {len(investor_ids)}\n")
    
    stats = {
        'investors': 0,
        'files': 0,
        'records_removed': 0,
        'files_deleted': 0,
        'oldest_removed': None,
        'newest_removed': None
    }
    
    for user_brokerid in investor_ids:
        investor_root = Path(INV_PATH) / user_brokerid
        if not investor_root.exists():
            continue
        
        # Get execution start date
        start_datetime = None
        
        # Check accountmanagement.json
        acc_mgmt = investor_root / "accountmanagement.json"
        if acc_mgmt.exists():
            try:
                with open(acc_mgmt, 'r') as f:
                    config = json.load(f)
                    start_date = config.get('execution_start_date')
                    if start_date:
                        for fmt in ["%Y-%m-%d", "%B %d, %Y", "%Y/%m/%d", "%d/%m/%Y"]:
                            try:
                                start_datetime = datetime.strptime(start_date, fmt)
                                break
                            except:
                                continue
            except:
                pass
        
        # Check activities.json if not found
        if not start_datetime:
            activities = investor_root / "activities.json"
            if activities.exists():
                try:
                    with open(activities, 'r') as f:
                        data = json.load(f)
                        start_date = data.get('execution_start_date')
                        if start_date:
                            for fmt in ["%Y-%m-%d", "%B %d, %Y", "%Y/%m/%d", "%d/%m/%Y"]:
                                try:
                                    start_datetime = datetime.strptime(start_date, fmt)
                                    break
                                except:
                                    continue
                except:
                    pass
        
        delete_all = (start_datetime is None)
        
        if delete_all:
            print(f"📁 Investor {user_brokerid}: NO START DATE - will delete ALL records")
        else:
            print(f"📁 Investor {user_brokerid}: Keeping records from {start_datetime.strftime('%Y-%m-%d')}")
        
        # Process all tradeshistory.json files
        for history_path in investor_root.rglob("tradeshistory.json"):
            if not history_path.exists():
                continue
            
            try:
                with open(history_path, 'r') as f:
                    history = json.load(f)
                
                if not history:
                    continue
                
                original_count = len(history)
                kept = []
                removed_records = []  # Store removed records with their ages
                
                for record in history:
                    keep = False
                    record_date = None
                    date_source = None
                    
                    # Try multiple date fields in priority order
                    date_fields = [
                        ('placed_timestamp', record.get('placed_timestamp')),
                        ('close_time', record.get('close_time')),
                        ('current_candle_time', record.get('current_candle_time')),
                        ('open_time', record.get('open_time')),
                        ('cancelled_time', record.get('cancelled_time')),
                        ('generated_at', record.get('generated_at')),
                        ('calculated_at', record.get('calculated_at')),
                        ('moved_to_signals_at', record.get('moved_to_signals_at')),
                        ('timestamp', record.get('timestamp'))
                    ]
                    
                    for field_name, date_str in date_fields:
                        if date_str and isinstance(date_str, str):
                            try:
                                # Handle various formats
                                if 'T' in date_str:
                                    # ISO format
                                    clean_date = date_str.split('.')[0] if '.' in date_str else date_str
                                    record_date = datetime.strptime(clean_date, '%Y-%m-%dT%H:%M:%S')
                                else:
                                    # Standard format
                                    record_date = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
                                date_source = field_name
                                break
                            except:
                                continue
                    
                    if delete_all:
                        # Remove everything
                        removed_records.append({'date': record_date, 'source': date_source})
                    elif record_date:
                        # Keep if on or after start date
                        if record_date >= start_datetime:
                            keep = True
                        else:
                            removed_records.append({'date': record_date, 'source': date_source, 'age_days': (datetime.now() - record_date).days})
                    else:
                        # No valid date found - remove
                        removed_records.append({'date': None, 'source': 'no_date', 'age_days': 'unknown'})
                    
                    if keep:
                        kept.append(record)
                
                removed_count = len(removed_records)
                
                if removed_count > 0:
                    # Calculate age statistics
                    ages = []
                    for r in removed_records:
                        if r.get('age_days') and isinstance(r['age_days'], int):
                            ages.append(r['age_days'])
                    
                    oldest_days = max(ages) if ages else None
                    newest_days = min(ages) if ages else None
                    
                    # Format age string
                    age_info = ""
                    if oldest_days and newest_days:
                        if oldest_days == newest_days:
                            age_info = f" (all {oldest_days} days old)"
                        else:
                            age_info = f" (oldest: {oldest_days} days, newest: {newest_days} days)"
                    
                    if delete_all and len(kept) == 0:
                        # Delete the file entirely
                        history_path.unlink()
                        stats['files_deleted'] += 1
                        print(f"   🗑️ {history_path.parent.name}: DELETED ({removed_count} records{age_info})")
                    else:
                        # Write back kept records
                        with open(history_path, 'w') as f:
                            json.dump(kept, f, indent=4)
                        print(f"   ✅ {history_path.parent.name}: {removed_count} removed{age_info}, {len(kept)} kept")
                    
                    stats['records_removed'] += removed_count
                    stats['files'] += 1
                    
                    # Track global oldest/newest
                    if ages:
                        if stats['oldest_removed'] is None or max(ages) > stats['oldest_removed']:
                            stats['oldest_removed'] = max(ages)
                        if stats['newest_removed'] is None or min(ages) < stats['newest_removed']:
                            stats['newest_removed'] = min(ages)
                else:
                    print(f"   ℹ️ {history_path.parent.name}: No old records")
                    
                stats['investors'] += 1
                
            except Exception as e:
                print(f"   {history_path.parent.name}: {str(e)[:50]}")
    
    # Summary
    print("\n" + "="*60)
    print(f"📊 SUMMARY")
    print(f"   Investors: {stats['investors']}")
    print(f"   Files cleaned: {stats['files']}")
    print(f"   Records removed: {stats['records_removed']}")
    
    if stats['records_removed'] > 0:
        if stats['oldest_removed'] and stats['newest_removed']:
            if stats['oldest_removed'] == stats['newest_removed']:
                print(f"   Age of removed: {stats['oldest_removed']} days old")
            else:
                print(f"   Age range: {stats['newest_removed']} to {stats['oldest_removed']} days old")
    
    print(f"   Files deleted: {stats['files_deleted']}")
    print("="*60 + "\n")
    
    return stats

def update_orders_status_in_tradeshistory(inv_id=None):
    """
    Checks MT5 for current pending orders and open positions.
    Records them in tradeshistory.json as a "current_orders" entry within the array.
    Does NOT include closed orders or historical deals.
    """

    def get_current_orders_from_mt5():
        """Fetch current pending orders and open positions from MT5."""
        pending_orders = []
        open_positions = []
        
        # Get all pending orders
        orders = mt5.orders_get()
        if orders:
            for order in orders:
                order_dict = {
                    'ticket': order.ticket,
                    'symbol': order.symbol,
                    'type': order.type,
                    'type_name': get_order_type_name(order.type),
                    'volume_initial': order.volume_initial,
                    'volume_current': order.volume_current,
                    'price_open': order.price_open,
                    'sl': order.sl,
                    'tp': order.tp,
                    'magic': order.magic,
                    'comment': order.comment,
                    'time_setup': datetime.fromtimestamp(order.time_setup).strftime('%Y-%m-%d %H:%M:%S')
                }
                pending_orders.append(order_dict)
        
        # Get all open positions
        positions = mt5.positions_get()
        if positions:
            for pos in positions:
                position_dict = {
                    'ticket': pos.ticket,
                    'symbol': pos.symbol,
                    'type': pos.type,
                    'type_name': get_position_type_name(pos.type),
                    'volume': pos.volume,
                    'price_open': pos.price_open,
                    'price_current': pos.price_current,
                    'sl': pos.sl,
                    'tp': pos.tp,
                    'magic': pos.magic,
                    'comment': pos.comment,
                    'time_open': datetime.fromtimestamp(pos.time).strftime('%Y-%m-%d %H:%M:%S'),
                    'profit': pos.profit,
                    'swap': pos.swap if hasattr(pos, 'swap') else 0,
                    'commission': pos.commission if hasattr(pos, 'commission') else 0
                }
                open_positions.append(position_dict)
        
        return pending_orders, open_positions
    
    def get_order_type_name(order_type):
        type_names = {
            mt5.ORDER_TYPE_BUY: 'BUY',
            mt5.ORDER_TYPE_SELL: 'SELL',
            mt5.ORDER_TYPE_BUY_LIMIT: 'BUY_LIMIT',
            mt5.ORDER_TYPE_SELL_LIMIT: 'SELL_LIMIT',
            mt5.ORDER_TYPE_BUY_STOP: 'BUY_STOP',
            mt5.ORDER_TYPE_SELL_STOP: 'SELL_STOP'
        }
        return type_names.get(order_type, f'UNKNOWN_{order_type}')
    
    def get_position_type_name(pos_type):
        type_names = {
            mt5.POSITION_TYPE_BUY: 'BUY',
            mt5.POSITION_TYPE_SELL: 'SELL'
        }
        return type_names.get(pos_type, f'UNKNOWN_{pos_type}')
    
    def check_existing_ticket(history, ticket, ticket_type):
        """Check if a ticket already exists in the current_orders snapshot."""
        for item in history:
            if isinstance(item, dict) and "current_orders" in item:
                current_orders = item["current_orders"]
                
                # Check in pending orders
                for order in current_orders.get("pending_orders", []):
                    if order.get("ticket") == ticket:
                        return True, "pending_order"
                
                # Check in open positions
                for position in current_orders.get("open_positions", []):
                    if position.get("ticket") == ticket:
                        return True, "open_position"
        return False, None
    
    def update_status_in_history(history, ticket, new_status):
        """Update the status field for a specific ticket in all records."""
        updated = False
        for item in history:
            if isinstance(item, dict):
                # Check if this item has a ticket field (individual order/position record)
                if item.get("ticket") == ticket:
                    item["status"] = new_status
                    updated = True
                # Also check if it's part of current_orders (though we handle separately)
                elif "current_orders" in item:
                    for order in item["current_orders"].get("pending_orders", []):
                        if order.get("ticket") == ticket:
                            # This is in current_orders, we'll update in the main loop
                            pass
                    for position in item["current_orders"].get("open_positions", []):
                        if position.get("ticket") == ticket:
                            # This is in current_orders, we'll update in the main loop
                            pass
        return updated
    
    # --- MAIN EXECUTION ---
    print("\n" + "="*60)
    print("📊 CURRENT ORDERS & POSITIONS SNAPSHOT")
    print("="*60)
    
    investor_ids = [inv_id] if inv_id else list(usersdictionary.keys())
    any_updates = False
    
    for user_brokerid in investor_ids:
        print(f"\n  👤 Investor: {user_brokerid}")
        
        investor_root = Path(INV_PATH) / user_brokerid
        
        if not investor_root.exists():
            print(f"     Investor root not found: {investor_root}")
            continue
        
        # Read existing tradeshistory.json first to check for duplicates
        history_path = investor_root / "tradeshistory.json"
        history = []
        
        if history_path.exists():
            try:
                with open(history_path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            except Exception as e:
                print(f"     Error reading tradeshistory.json: {e}")
                history = []
        
        # Fetch current state from MT5
        print(f"    🔍 Fetching current orders and positions from MT5...")
        pending_orders, open_positions = get_current_orders_from_mt5()
        
        # Create sets of active tickets for quick lookup
        active_pending_tickets = {order['ticket'] for order in pending_orders}
        active_position_tickets = {pos['ticket'] for pos in open_positions}
        
        # Print tickets found and check for duplicates
        print(f"\n    📋 Found: {len(pending_orders)} pending orders, {len(open_positions)} open positions")
        
        # Update status for existing records in history (not just current_orders)
        print(f"\n    🔄 Updating status for existing records...")
        
        # Iterate through all items in history to update status
        for item in history:
            if isinstance(item, dict):
                # Skip the current_orders entry for now, handle separately
                if "current_orders" in item:
                    continue
                
                ticket = item.get("ticket")
                if ticket:
                    if ticket in active_pending_tickets:
                        if item.get("status") != "pending":
                            item["status"] = "pending"
                            print(f"       - Ticket {ticket}: status updated to 'pending'")
                        else:
                            print(f"       - Ticket {ticket}: already 'pending'")
                    elif ticket in active_position_tickets:
                        if item.get("status") != "running_position":
                            item["status"] = "running_position"
                            print(f"       - Ticket {ticket}: status updated to 'running_position'")
                        else:
                            print(f"       - Ticket {ticket}: already 'running_position'")
                    else:
                        if item.get("status") != "closed":
                            item["status"] = "closed"
                            print(f"       - Ticket {ticket}: status updated to 'closed'")
        
        # Check pending orders
        if pending_orders:
            print(f"\n    🎫 Pending Orders Tickets:")
            for order in pending_orders:
                ticket = order['ticket']
                exists, location = check_existing_ticket(history, ticket, "pending")
                if exists:
                    print(f"       - Ticket {ticket} ({order['type_name']}) - ✅ EXISTS! (in {location})")
                else:
                    print(f"       - Ticket {ticket} ({order['type_name']}) - 🆕 New")
        
        # Check open positions
        if open_positions:
            print(f"\n    💼 Open Positions Tickets:")
            for position in open_positions:
                ticket = position['ticket']
                exists, location = check_existing_ticket(history, ticket, "position")
                if exists:
                    print(f"       - Ticket {ticket} ({position['type_name']}) - ✅ EXISTS! (in {location})")
                else:
                    print(f"       - Ticket {ticket} ({position['type_name']}) - 🆕 New")
        
        # Prepare current_orders data
        current_orders_data = {
            'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'pending_orders': pending_orders,
            'open_positions': open_positions
        }
        
        # Remove any existing "current_orders" entry
        history = [item for item in history if not isinstance(item, dict) or "current_orders" not in item]
        
        # Append the new current_orders entry
        history.append({"current_orders": current_orders_data})
        
        # Save back to file
        try:
            with open(history_path, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=4)
            
            print(f"\n    ✅ Saved current orders snapshot to tradeshistory.json")
            print(f"       - Pending orders: {len(pending_orders)}")
            print(f"       - Open positions: {len(open_positions)}")
            
            any_updates = True
            
        except Exception as e:
            print(f"     Error saving tradeshistory.json: {e}")
    
    print("\n" + "="*60)
    if any_updates:
        print("✅ Current orders snapshot completed")
    else:
        print(" No updates made")
    print("="*60)
    
    return any_updates

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
            print(f"  └─  No broker config found for {user_brokerid}")
            continue

        # 1. Define the 48-hour window
        from_date = datetime.now() - timedelta(hours=48)
        to_date = datetime.now()

        # 2. Get Closed Positions (Deals)
        history_deals = mt5.history_deals_get(from_date, to_date)
        if history_deals is None:
            print(f"  └─ Could not access history for {user_brokerid}")
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
                            print(f"      Failed to cancel #{order.ticket}: {error_msg}")

        print(f"  └─ 📊 Cleanup Result: {removed_count} duplicate limit orders removed out of {orders_checked} checked.")

    print(f"\n{'='*10} 🏁 HISTORY AUDIT COMPLETE {'='*10}\n")
    return any_orders_removed

def check_pending_orders_risk(inv_id=None):
    """
    Function 3: Validates live pending orders against the account's current risk bucket.
    
    NEW LOGIC:
    - account_balance_default_risk_management = Target risk range (what we want)
    - account_balance_maximum_risk_management = Maximum allowed threshold (hard cap)
    
    RULES:
    0. If order has no SL → REMOVED immediately (no stoploss protection)
    1. If order risk <= default_risk → ALLOWED (within target)
    2. If default_risk < order risk <= maximum_risk → ALLOWED (between target and max)
    3. If order risk > maximum_risk → REMOVED (exceeds hard cap)
    4. If default_risk missing → use maximum_risk as both target and max
    5. If maximum_risk missing → use default_risk as both target and max
    6. If both missing or empty → skip checking
    
    Args:
        inv_id: Optional specific investor ID to process. If None, processes all investors.
        
    Returns:
        dict: Statistics about the processing
    """
    print(f"\n{'='*10} 🛡️ LIVE RISK AUDIT: TARGET + MAXIMUM THRESHOLD {'='*10}")
    if inv_id:
        print(f" Processing single investor: {inv_id}")

    # --- DATA INITIALIZATION ---
    stats = {
        "investor_id": inv_id if inv_id else "all",
        "orders_checked": 0,
        "orders_removed": 0,
        "orders_removed_no_sl": 0,
        "orders_removed_exceeded_max": 0,
        "orders_kept": 0,
        "default_risk_used": None,
        "maximum_risk_used": None,
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
            print(f"  └─  No broker config found")
            continue
        
        inv_root = Path(INV_PATH) / user_brokerid
        acc_mgmt_path = inv_root / "accountmanagement.json"

        if not acc_mgmt_path.exists():
            print(f"  └─  Account config missing. Skipping.")
            continue

        # --- LOAD CONFIG AND GET RISK VALUES ---
        try:
            with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Get both risk configurations
            default_risk_map = config.get("account_balance_default_risk_management", {})
            maximum_risk_map = config.get("account_balance_maximum_risk_management", {})
            
            print(f"  └─ ⚙️  Risk Configuration Loading:")
            print(f"      • account_balance_default_risk_management: {'✅ Found' if default_risk_map else ' Missing'}")
            print(f"      • account_balance_maximum_risk_management: {'✅ Found' if maximum_risk_map else ' Missing'}")
            
        except Exception as e:
            print(f"  └─  Failed to read config: {e}")
            continue

        # --- ACCOUNT CONNECTION CHECK ---
        print(f"  └─ 🔌 Checking account connection...")
        
        login_id = int(broker_cfg['LOGIN_ID'])
        mt5_path = broker_cfg["TERMINAL_PATH"]
        
        print(f"      • Terminal Path: {mt5_path}")
        print(f"      • Login ID: {login_id}")

        # Check if already logged into correct account
        acc = mt5.account_info()
        if acc is None or acc.login != login_id:
            print(f"  └─  Not logged into the correct account. Expected: {login_id}, Found: {acc.login if acc else 'None'}")
            continue
        else:
            print(f"      ✅ Connected to account: {acc.login}")

        acc_info = mt5.account_info()
        if not acc_info:
            print(f"  └─  Failed to get account info")
            continue
            
        balance = acc_info.balance

        # Get terminal info for additional details
        term_info = mt5.terminal_info()
        
        print(f"\n  └─ 📊 Account Details:")
        print(f"      • Balance: ${acc_info.balance:,.2f}")
        print(f"      • Equity: ${acc_info.equity:,.2f}")
        print(f"      • Free Margin: ${acc_info.margin_free:,.2f}")
        print(f"      • Margin Level: {acc_info.margin_level:.2f}%" if acc_info.margin_level else "      • Margin Level: N/A")
        print(f"      • AutoTrading: {'✅ ENABLED' if term_info.trade_allowed else ' DISABLED'}")

        # --- DETERMINE DEFAULT RISK VALUE (Target) ---
        default_risk = None
        if default_risk_map:
            for range_str, r_val in default_risk_map.items():
                try:
                    raw_range = range_str.split("_")[0]
                    low, high = map(float, raw_range.split("-"))
                    if low <= balance <= high:
                        default_risk = float(r_val)
                        break
                except Exception as e:
                    print(f"  └─  Error parsing default range '{range_str}': {e}")
                    continue

        # --- DETERMINE MAXIMUM RISK VALUE (Hard Cap) ---
        maximum_risk = None
        if maximum_risk_map:
            for range_str, r_val in maximum_risk_map.items():
                try:
                    raw_range = range_str.split("_")[0]
                    low, high = map(float, raw_range.split("-"))
                    if low <= balance <= high:
                        maximum_risk = float(r_val)
                        break
                except Exception as e:
                    print(f"  └─  Error parsing maximum range '{range_str}': {e}")
                    continue

        # --- APPLY FALLBACK LOGIC ---
        if default_risk is None and maximum_risk is None:
            print(f"  └─  No risk configuration found for balance ${balance:,.2f}. Skipping check.")
            continue
        elif default_risk is None:
            # No default found, use maximum as both target and cap
            default_risk = maximum_risk
            print(f"  └─  Default risk missing. Using maximum (${maximum_risk:.2f}) as both target and cap.")
        elif maximum_risk is None:
            # No maximum found, use default as both target and cap
            maximum_risk = default_risk
            print(f"  └─  Maximum risk missing. Using default (${default_risk:.2f}) as both target and cap.")
        
        # Ensure maximum is at least default (if not, use default as maximum)
        if maximum_risk < default_risk:
            print(f"  └─  Maximum risk (${maximum_risk:.2f}) is less than default (${default_risk:.2f}). Adjusting maximum to match default.")
            maximum_risk = default_risk

        print(f"\n  └─ 💰 Risk Configuration Applied:")
        print(f"      • Target Risk (default): ${default_risk:.2f}")
        print(f"      • Maximum Allowed (hard cap): ${maximum_risk:.2f}")
        
        # Store which configs were used in stats
        stats["default_risk_used"] = default_risk
        stats["maximum_risk_used"] = maximum_risk

        # --- CHECK ALL LIVE PENDING ORDERS ---
        pending_orders = mt5.orders_get()
        investor_orders_checked = 0
        investor_orders_removed = 0
        investor_orders_removed_no_sl = 0
        investor_orders_removed_exceeded_max = 0
        investor_orders_kept = 0

        if pending_orders:
            print(f"  └─ 🔍 Scanning {len(pending_orders)} pending orders (ALL types)...")
            
            for order in pending_orders:
                # Skip if not a pending order type
                if order.type not in ORDER_TYPES.keys():
                    continue

                investor_orders_checked += 1
                stats["orders_checked"] += 1
                
                order_type_name = ORDER_TYPES.get(order.type, f"Unknown Type {order.type}")
                
                print(f"    └─ 📋 Order #{order.ticket} | {order_type_name} | {order.symbol}")
                
                # --- RULE 0: Check if order has no SL → REMOVE IMMEDIATELY ---
                if order.sl == 0:
                    print(f"       🗑️ PURGING: No stoploss protection detected")
                    print(f"       SL value is 0 or not set - order not allowed")
                    
                    cancel_request = {
                        "action": mt5.TRADE_ACTION_REMOVE,
                        "order": order.ticket
                    }
                    result = mt5.order_send(cancel_request)
                    
                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        investor_orders_removed += 1
                        investor_orders_removed_no_sl += 1
                        stats["orders_removed"] += 1
                        stats["orders_removed_no_sl"] += 1
                        print(f"       ✅ Order removed successfully")
                    else:
                        error_msg = result.comment if result else "No response"
                        print(f"        Cancel failed: {error_msg}")
                    continue
                
                # Determine order direction for calculations
                is_buy = order.type in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP, mt5.ORDER_TYPE_BUY_STOP_LIMIT]
                calc_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
                
                # Calculate risk (stop loss distance in money)
                sl_profit = mt5.order_calc_profit(calc_type, order.symbol, order.volume_initial, 
                                                  order.price_open, order.sl)
                
                if sl_profit is not None:
                    order_risk_usd = round(abs(sl_profit), 2)
                    
                    print(f"       Order Risk: ${order_risk_usd:.2f}")
                    print(f"       Target: ${default_risk:.2f} | Maximum: ${maximum_risk:.2f}")
                    
                    # --- NEW LOGIC: Check against both thresholds ---
                    if order_risk_usd > maximum_risk:
                        # Case 3: Exceeds maximum hard cap → REMOVE
                        print(f"       🗑️ PURGING: Risk exceeds maximum threshold")
                        print(f"       ${order_risk_usd:.2f} > ${maximum_risk:.2f} (exceeds by ${order_risk_usd - maximum_risk:.2f})")
                        
                        cancel_request = {
                            "action": mt5.TRADE_ACTION_REMOVE,
                            "order": order.ticket
                        }
                        result = mt5.order_send(cancel_request)
                        
                        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                            investor_orders_removed += 1
                            investor_orders_removed_exceeded_max += 1
                            stats["orders_removed"] += 1
                            stats["orders_removed_exceeded_max"] += 1
                            print(f"       ✅ Order removed successfully")
                        else:
                            error_msg = result.comment if result else "No response"
                            print(f"        Cancel failed: {error_msg}")
                    
                    elif order_risk_usd <= default_risk:
                        # Case 1: Within target range → KEEP
                        investor_orders_kept += 1
                        stats["orders_kept"] += 1
                        print(f"       ✅ KEEPING: Risk within target range")
                        print(f"       ${order_risk_usd:.2f} ≤ ${default_risk:.2f}")
                    
                    elif default_risk < order_risk_usd <= maximum_risk:
                        # Case 2: Between target and maximum → KEEP (allowed but noted)
                        investor_orders_kept += 1
                        stats["orders_kept"] += 1
                        print(f"       ✅ KEEPING: Risk between target and maximum")
                        print(f"       ${default_risk:.2f} < ${order_risk_usd:.2f} ≤ ${maximum_risk:.2f}")
                    
                else:
                    print(f"        Could not calculate risk")

        # Investor final summary
        if investor_orders_checked > 0:
            print(f"\n  └─ 📊 Audit Results for {user_brokerid}:")
            print(f"       • Target Risk: ${default_risk:.2f}")
            print(f"       • Maximum Risk: ${maximum_risk:.2f}")
            print(f"       • Orders checked: {investor_orders_checked}")
            print(f"       • Orders kept: {investor_orders_kept}")
            if investor_orders_removed > 0:
                print(f"       • Orders removed (total): {investor_orders_removed}")
                if investor_orders_removed_no_sl > 0:
                    print(f"         - No stoploss: {investor_orders_removed_no_sl}")
                if investor_orders_removed_exceeded_max > 0:
                    print(f"         - Exceeded maximum risk: {investor_orders_removed_exceeded_max}")
            else:
                print(f"       ✅ No orders exceeded maximum threshold or missing stoploss")
            stats["processing_success"] = True
        else:
            print(f"  └─ 🔘 No pending orders found.")

    # --- FINAL SUMMARY ---
    print(f"\n{'='*10} 📊 RISK AUDIT SUMMARY (TARGET + MAXIMUM) {'='*10}")
    print(f"   Investor ID: {stats['investor_id']}")
    print(f"   Orders checked: {stats['orders_checked']}")
    print(f"   Orders kept: {stats['orders_kept']}")
    print(f"   Orders removed (total): {stats['orders_removed']}")
    print(f"     - No stoploss: {stats['orders_removed_no_sl']}")
    print(f"     - Exceeded maximum risk: {stats['orders_removed_exceeded_max']}")
    
    if stats['default_risk_used'] is not None:
        print(f"   Target risk used: ${stats['default_risk_used']:.2f}")
    if stats['maximum_risk_used'] is not None:
        print(f"   Maximum risk used: ${stats['maximum_risk_used']:.2f}")
    
    if stats['orders_checked'] > 0:
        removal_rate = (stats['orders_removed'] / stats['orders_checked']) * 100
        print(f"   Removal rate: {removal_rate:.1f}%")
    
    print(f"\n{'='*10} 🏁 RISK AUDIT COMPLETE {'='*10}\n")
    return stats

def orders_reward_correction(inv_id=None):
    """
    Function: Checks both live pending orders AND open positions (LIMIT, STOP, and MARKET)
    and adjusts their take profit levels based on the NEAREST MATCHING strategy risk-reward ratio.
    
    INTELLIGENT APPROACH:
    1. Calculate current R:R from order's exit/target prices
    2. Compare with strategy-specific R:R values from accountmanagement.json
    3. Find the nearest matching R:R (next higher value) and use that
    4. Fall back to default selected_risk_reward if no match found
    5. Checks tradeshistory.json for hedge orders and applies hedge_orders_risk_reward
    
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
        "hedge_orders_found": 0,  # Track hedge orders found in history
        "hedge_orders_adjusted": 0,  # Track hedge orders adjusted
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
            print(f"  └─  No broker config found")
            continue
        
        inv_root = Path(INV_PATH) / user_brokerid
        acc_mgmt_path = inv_root / "accountmanagement.json"
        tradeshistory_path = inv_root / "tradeshistory.json"

        if not acc_mgmt_path.exists():
            print(f"  └─  Account config missing. Skipping.")
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
            hedge_rr_values = []
            regular_rr_values = []
            
            # Add default selected_risk_reward
            selected_rr = config.get("selected_risk_reward", [2])
            if isinstance(selected_rr, list) and selected_rr:
                default_rr = float(selected_rr[0])
            else:
                default_rr = 2.0
            
            regular_rr_values.append(default_rr)
            all_rr_values.append(default_rr)
            
            # Add hedge orders risk reward
            hedge_rr_config = config.get("hedge_orders_risk_reward", [2])
            if isinstance(hedge_rr_config, list) and hedge_rr_config:
                hedge_default_rr = float(hedge_rr_config[0])
            else:
                hedge_default_rr = 2.0
            
            hedge_rr_values.append(hedge_default_rr)
            if hedge_default_rr not in all_rr_values:
                all_rr_values.append(hedge_default_rr)
            
            # Add all strategy-specific R:R values
            strategies_rr = config.get("strategies_risk_reward", {})
            strategy_rr_values = []
            for strategy, rr_value in strategies_rr.items():
                try:
                    rr_float = float(rr_value)
                    strategy_rr_values.append(rr_float)
                    all_rr_values.append(rr_float)
                    regular_rr_values.append(rr_float)
                except (ValueError, TypeError):
                    continue
            
            # Sort and deduplicate all available R:R values
            all_rr_values = sorted(set(all_rr_values))
            hedge_rr_values = sorted(set(hedge_rr_values))
            regular_rr_values = sorted(set(regular_rr_values))
            
            print(f"  └─ 📊 Default R:R (Regular): 1:{default_rr}")
            print(f"  └─ 📊 Default R:R (Hedge): 1:{hedge_default_rr}")
            if strategy_rr_values:
                print(f"  └─ 📋 Strategy R:R values: {', '.join([f'1:{v}' for v in sorted(set(strategy_rr_values))])}")
            print(f"  └─ 🎯 All available R:R targets: {', '.join([f'1:{v}' for v in all_rr_values])}")
            
            # Get risk management mapping for balance-based risk
            risk_map = config.get("account_balance_default_risk_management", {})
            
        except Exception as e:
            print(f"  └─  Failed to read config: {e}")
            stats["orders_error"] += 1
            continue

        # --- LOAD TRADESHISTORY TO IDENTIFY HEDGE ORDERS ---
        hedge_ticket_map = {}  # Maps ticket numbers to their hedge status
        hedge_tickets_list = []  # List for debugging
        trades_history = []  # Initialize for later use
        
        if tradeshistory_path.exists():
            try:
                with open(tradeshistory_path, 'r', encoding='utf-8') as f:
                    trades_history = json.load(f)
                
                # Build a map of ticket -> is_hedge_order
                for trade in trades_history:
                    if isinstance(trade, dict) and 'current_orders' not in trade:
                        ticket = trade.get('ticket')
                        is_hedge = trade.get('is_hedge_order', False)
                        if ticket is not None:
                            hedge_ticket_map[ticket] = is_hedge
                            if is_hedge:
                                hedge_tickets_list.append(ticket)
                                stats["hedge_orders_found"] += 1
                
                print(f"  └─ 📜 Loaded {len(hedge_ticket_map)} trades from history")
                if stats["hedge_orders_found"] > 0:
                    print(f"  └─ 🛡️  Found {stats['hedge_orders_found']} hedge orders in trade history")
                    print(f"  └─ 🛡️  Hedge ticket examples: {hedge_tickets_list[:5]}")
                else:
                    print(f"  └─ ℹ️  No hedge orders found in trade history")
            except Exception as e:
                print(f"  └─  Error reading tradeshistory.json: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"  └─ ℹ️  No tradeshistory.json found - all orders treated as regular")

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
                print(f"  └─   login failed: {error}")
                stats["orders_error"] += 1
                continue
            print(f"      ✅ Successfully logged into account")
        else:
            print(f"      ✅ Already logged into account")

        acc_info = mt5.account_info()
        if not acc_info:
            print(f"  └─  Failed to get account info")
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
        print(f"      • AutoTrading: {'✅ ENABLED' if term_info.trade_allowed else ' DISABLED'}")

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
                print(f"  └─  Error parsing range '{range_str}': {e}")
                continue

        if primary_risk is None:
            print(f"  └─  No risk mapping for balance ${balance:,.2f}")
            stats["orders_skipped"] += 1
            continue

        print(f"\n  └─ 💰 Balance: ${balance:,.2f} | Base Risk: ${primary_risk:.2f}")

        # --- HELPER FUNCTION: Determine if order/position is a hedge order ---
        def is_hedge_order(ticket, comment="", symbol="", order_type=""):
            """
            Check if an order/position is a hedge order by:
            1. Checking tradeshistory.json ticket map (MOST RELIABLE)
            2. Checking order/position comment for hedge indicators
            3. Searching tradeshistory for similar orders with hedge flags
            
            Returns:
                tuple: (is_hedge, detection_method)
            """
            # Method 1: Check ticket map first (direct match)
            if ticket in hedge_ticket_map:
                is_hedge = hedge_ticket_map[ticket]
                if is_hedge:
                    return True, "ticket_map"
                else:
                    return False, "ticket_map"
            
            # Method 2: Check comment for hedge indicators
            if comment:
                comment_lower = comment.lower()
                hedge_indicators = ["hedge", "🛡️", "h_edge", "hedg", "h_dge", "[h]", "h-"]
                for indicator in hedge_indicators:
                    if indicator in comment_lower:
                        return True, "comment"
            
            # Method 3: Search tradeshistory for same symbol/type with hedge flag
            # This handles cases where the ticket might have changed
            if symbol and order_type:
                for trade in trades_history:
                    if isinstance(trade, dict) and 'current_orders' not in trade:
                        if (trade.get('symbol') == symbol or trade.get('symbol_used') == symbol or trade.get('original_symbol') == symbol):
                            if trade.get('is_hedge_order', False):
                                # Found a hedge order with same symbol - likely related
                                # Check if prices are close (within 1%)
                                if ticket and trade.get('ticket'):
                                    # Could add price proximity check here
                                    pass
                                return True, "symbol_match"
            
            return False, "none"

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

        # --- HELPER FUNCTION: Calculate risk in USD ---
        def calculate_risk_usd(volume, stop_distance_pips, tick_size, tick_value):
            """
            Calculate risk in USD using the proven formula.
            """
            if tick_size <= 0:
                return 0
            
            ticks_in_stop = stop_distance_pips / tick_size
            risk_usd = volume * ticks_in_stop * tick_value
            return abs(risk_usd)

        # --- HELPER FUNCTION: Calculate TP price based on risk, RR, and direction ---
        def calculate_tp_price_from_risk(price_open, risk_usd, target_rr, is_buy, symbol_info, volume, tick_size, tick_value):
            """
            Calculate take profit price based on target risk-reward ratio.
            """
            target_profit_usd = risk_usd * target_rr
            
            if tick_size <= 0 or tick_value <= 0:
                return None
            
            # Calculate required ticks for target profit
            ticks_needed = target_profit_usd / (volume * tick_value)
            
            # Convert ticks to price movement
            price_move_needed = ticks_needed * tick_size
            
            # Get symbol digits for rounding
            digits = symbol_info.digits
            
            # Ensure minimum movement (at least 1 point)
            # 🔧 FIX: Changed from 10 points to 1 point to allow cent-level precision
            min_move = symbol_info.point * 1
            if abs(price_move_needed) < min_move:
                price_move_needed = min_move if price_move_needed >= 0 else -min_move
            
            # Round to symbol digits
            price_move_needed = round(price_move_needed, digits)
            
            # Calculate TP based on direction
            if is_buy:
                new_tp = round(price_open + price_move_needed, digits)
            else:
                new_tp = round(price_open - price_move_needed, digits)
            
            # 🔧 FIX: Removed the 50% cap that was causing issues
            # Instead, just validate it's reasonable (max 100% move)
            max_move = price_open * 1.0  # Changed from 0.5 to 1.0 (100%)
            move_abs = abs(new_tp - price_open)
            if move_abs > max_move:
                print(f"         Calculated move {move_abs:.{digits}f} exceeds 100% of price, capping...")
                if is_buy:
                    new_tp = round(price_open + max_move, digits)
                else:
                    new_tp = round(price_open - max_move, digits)
            
            return new_tp

        # --- DEFINE ORDER AND POSITION TYPES WITH DIRECTION ---
        BUY_TYPES = {
            mt5.POSITION_TYPE_BUY: "BUY (MARKET)",
            mt5.ORDER_TYPE_BUY_LIMIT: "BUY LIMIT",
            mt5.ORDER_TYPE_BUY_STOP: "BUY STOP",
            mt5.ORDER_TYPE_BUY_STOP_LIMIT: "BUY STOP-LIMIT"
        }
        
        SELL_TYPES = {
            mt5.POSITION_TYPE_SELL: "SELL (MARKET)",
            mt5.ORDER_TYPE_SELL_LIMIT: "SELL LIMIT",
            mt5.ORDER_TYPE_SELL_STOP: "SELL STOP",
            mt5.ORDER_TYPE_SELL_STOP_LIMIT: "SELL STOP-LIMIT"
        }
        
        PENDING_ORDER_TYPES = set(BUY_TYPES.keys()) | set(SELL_TYPES.keys())
        PENDING_ORDER_TYPES.discard(mt5.POSITION_TYPE_BUY)
        PENDING_ORDER_TYPES.discard(mt5.POSITION_TYPE_SELL)

        # --- PROCESS OPEN POSITIONS (MARKET ORDERS) ---
        positions = mt5.positions_get()
        investor_positions_checked = 0
        investor_positions_adjusted = 0
        investor_positions_skipped = 0
        investor_positions_error = 0

        if positions:
            print(f"\n  └─ 🔍 Scanning {len(positions)} open positions (MARKET)...")
            
            for position in positions:
                investor_positions_checked += 1
                stats["positions_checked"] += 1
                
                # Determine position direction
                is_buy = position.type in BUY_TYPES
                position_type_name = BUY_TYPES.get(position.type, SELL_TYPES.get(position.type, f"Unknown Type {position.type}"))
                
                # Get symbol info
                symbol_info = mt5.symbol_info(position.symbol)
                if not symbol_info:
                    print(f"    └─  Cannot get symbol info for {position.symbol}")
                    investor_positions_skipped += 1
                    stats["orders_skipped"] += 1
                    continue
                
                # Ensure symbol is selected
                mt5.symbol_select(position.symbol, True)
                symbol_info = mt5.symbol_info(position.symbol)
                
                # Get comment for hedge detection
                position_comment = position.comment if hasattr(position, 'comment') else ""
                
                print(f"\n    └─ 📋 Position #{position.ticket} | {position_type_name} | {position.symbol}")
                if position_comment:
                    print(f"       Comment: {position_comment[:50]}")
                
                # Check if this is a hedge position with enhanced detection
                is_hedge, detection_method = is_hedge_order(
                    position.ticket, 
                    position_comment, 
                    position.symbol,
                    position_type_name
                )
                
                if is_hedge:
                    print(f"       🛡️  HEDGE POSITION IDENTIFIED (via {detection_method})")
                    position_default_rr, position_rr_values = hedge_default_rr, hedge_rr_values
                else:
                    print(f"       📊 REGULAR POSITION (checked via {detection_method})")
                    position_default_rr, position_rr_values = default_rr, regular_rr_values
                
                # Calculate current risk using the proven formula
                if position.sl == 0:
                    print(f"        No SL set - cannot calculate risk. Skipping TP adjustment.")
                    investor_positions_skipped += 1
                    stats["orders_skipped"] += 1
                    continue
                
                # Get tick size and tick value from symbol info
                tick_size = symbol_info.trade_tick_size
                tick_value = symbol_info.trade_tick_value
                
                if tick_size <= 0 or tick_value <= 0:
                    print(f"        Invalid tick size/value for {position.symbol}")
                    investor_positions_skipped += 1
                    stats["orders_skipped"] += 1
                    continue
                
                # Calculate stop distance in price units
                if is_buy:
                    stop_distance = position.price_open - position.sl
                else:
                    stop_distance = position.sl - position.price_open
                
                if stop_distance <= 0:
                    print(f"        Invalid stop distance: {stop_distance}")
                    investor_positions_skipped += 1
                    stats["orders_skipped"] += 1
                    continue
                
                # Calculate current risk in USD with more precision
                current_risk_usd = calculate_risk_usd(position.volume, stop_distance, tick_size, tick_value)
                # 🔧 FIX: Keep full precision for risk calculation, don't round prematurely
                
                print(f"       Volume: {position.volume} | Stop distance: {stop_distance:.{symbol_info.digits}f} | Risk: ${current_risk_usd:.2f}")
                print(f"       Using {'HEDGE' if is_hedge else 'REGULAR'} R:R default: 1:{position_default_rr}")
                
                # Calculate current R:R if TP exists
                current_rr = None
                if position.tp != 0:
                    if is_buy:
                        tp_distance = position.tp - position.price_open
                    else:
                        tp_distance = position.price_open - position.tp
                    
                    if stop_distance > 0:
                        current_rr = round(tp_distance / stop_distance, 2)
                        print(f"       Current R:R: 1:{current_rr}")
                    else:
                        current_rr = None
                
                # Find target R:R based on current value using appropriate R:R values
                if current_rr is not None:
                    target_rr, match_type = find_nearest_rr(current_rr, position_rr_values)
                    
                    if match_type == "next_higher":
                        print(f"       🔍 Using next higher R:R: 1:{target_rr} (from 1:{current_rr})")
                    elif match_type == "closest":
                        print(f"       🔍 Using closest R:R: 1:{target_rr} (from 1:{current_rr}) - no higher value")
                    else:
                        target_rr = position_default_rr
                        print(f"       ℹ️  Using default R:R: 1:{target_rr}")
                    
                    # Track R:R usage
                    rr_key = f"{'hedge' if is_hedge else 'regular'}_{str(target_rr)}"
                    if rr_key not in stats["rr_matches"]:
                        stats["rr_matches"][rr_key] = 0
                    stats["rr_matches"][rr_key] += 1
                else:
                    target_rr = position_default_rr
                    print(f"       ℹ️  No current R:R found, using default: 1:{target_rr}")
                    stats["rr_mismatches"] += 1
                
                # Calculate new take profit price with full precision
                new_tp = calculate_tp_price_from_risk(position.price_open, current_risk_usd, target_rr, 
                                                     is_buy, symbol_info, position.volume, tick_size, tick_value)
                
                if new_tp is None:
                    print(f"        Cannot calculate TP price. Skipping.")
                    investor_positions_skipped += 1
                    stats["orders_skipped"] += 1
                    continue
                
                # 🔧 FIX: Validate TP price makes sense for direction with tolerance
                digits = symbol_info.digits
                # Add small tolerance for floating-point comparison (0.1 pips)
                tolerance = symbol_info.point * 0.1
                
                if is_buy and new_tp <= position.price_open + tolerance:
                    print(f"        Calculated TP {new_tp:.{digits}f} is not above entry {position.price_open:.{digits}f} (with tolerance). Skipping.")
                    investor_positions_skipped += 1
                    stats["orders_skipped"] += 1
                    continue
                elif not is_buy and new_tp >= position.price_open - tolerance:
                    print(f"        Calculated TP {new_tp:.{digits}f} is not below entry {position.price_open:.{digits}f} (with tolerance). Skipping.")
                    investor_positions_skipped += 1
                    stats["orders_skipped"] += 1
                    continue
                
                # Calculate target profit with full precision
                target_profit = current_risk_usd * target_rr
                print(f"       Target R:R: 1:{target_rr} | Risk: ${current_risk_usd:.4f} | Target Profit: ${target_profit:.4f}")
                
                # 🔧 FIX: Improved comparison that allows cent-level precision
                if position.tp == 0:
                    target_move = abs(new_tp - position.price_open)
                    print(f"       📝 No TP currently set")
                    print(f"       Target TP: {new_tp:.{digits}f} (Move from entry: {target_move:.{digits}f})")
                    should_adjust = True
                else:
                    current_move = abs(position.tp - position.price_open)
                    target_move = abs(new_tp - position.price_open)
                    
                    # 🔧 FIX: Use absolute difference threshold (1 point) instead of percentage
                    # This allows cent-level adjustments for small moves
                    point_threshold = symbol_info.point * 1  # Just 1 point difference
                    
                    if abs(current_move - target_move) > point_threshold:
                        print(f"       📐 TP needs adjustment (difference: {abs(current_move - target_move):.{digits}f} > {point_threshold:.{digits}f})")
                        print(f"       Current TP: {position.tp:.{digits}f} (Move: {current_move:.{digits}f})")
                        print(f"       Target TP:  {new_tp:.{digits}f} (Move: {target_move:.{digits}f})")
                        should_adjust = True
                    else:
                        print(f"       ✅ TP already correct (within {point_threshold:.{digits}f})")
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
                        if is_hedge:
                            stats["hedge_orders_adjusted"] += 1
                        print(f"       ✅ TP adjusted successfully to {new_tp:.{digits}f}")
                    else:
                        investor_positions_error += 1
                        stats["orders_error"] += 1
                        error_msg = result.comment if result else f"Error code: {result.retcode if result else 'Unknown'}"
                        print(f"        Modification failed: {error_msg}")

        # --- PROCESS PENDING ORDERS (LIMIT AND STOP) ---
        pending_orders = mt5.orders_get()
        investor_orders_checked = 0
        investor_orders_adjusted = 0
        investor_orders_skipped = 0
        investor_orders_error = 0

        if pending_orders:
            print(f"\n  └─ 🔍 Scanning {len(pending_orders)} pending orders (LIMIT & STOP)...")
            
            for order in pending_orders:
                # Skip if not a pending order
                if order.type not in PENDING_ORDER_TYPES:
                    continue
                
                investor_orders_checked += 1
                stats["orders_checked"] += 1
                
                # Determine order direction
                is_buy = order.type in BUY_TYPES
                order_type_name = BUY_TYPES.get(order.type, SELL_TYPES.get(order.type, f"Unknown Type {order.type}"))
                
                # Get symbol info
                symbol_info = mt5.symbol_info(order.symbol)
                if not symbol_info:
                    print(f"    └─  Cannot get symbol info for {order.symbol}")
                    investor_orders_skipped += 1
                    stats["orders_skipped"] += 1
                    continue
                
                # Ensure symbol is selected
                mt5.symbol_select(order.symbol, True)
                symbol_info = mt5.symbol_info(order.symbol)
                
                # Get comment for hedge detection
                order_comment = order.comment if hasattr(order, 'comment') else ""
                
                print(f"\n    └─ 📋 Order #{order.ticket} | {order_type_name} | {order.symbol}")
                if order_comment:
                    print(f"       Comment: {order_comment[:50]}")
                
                # Check if this is a hedge order with enhanced detection
                is_hedge, detection_method = is_hedge_order(
                    order.ticket, 
                    order_comment, 
                    order.symbol,
                    order_type_name
                )
                
                if is_hedge:
                    print(f"       🛡️  HEDGE ORDER IDENTIFIED (via {detection_method})")
                    order_default_rr, order_rr_values = hedge_default_rr, hedge_rr_values
                else:
                    print(f"       📊 REGULAR ORDER (checked via {detection_method})")
                    order_default_rr, order_rr_values = default_rr, regular_rr_values
                
                # Calculate current risk using the proven formula
                if order.sl == 0:
                    print(f"        No SL set - cannot calculate risk. Skipping TP adjustment.")
                    investor_orders_skipped += 1
                    stats["orders_skipped"] += 1
                    continue
                
                # Get tick size and tick value from symbol info
                tick_size = symbol_info.trade_tick_size
                tick_value = symbol_info.trade_tick_value
                
                if tick_size <= 0 or tick_value <= 0:
                    print(f"        Invalid tick size/value for {order.symbol}")
                    investor_orders_skipped += 1
                    stats["orders_skipped"] += 1
                    continue
                
                # Calculate stop distance in price units
                stop_distance = abs(order.price_open - order.sl)
                
                if stop_distance <= 0:
                    print(f"        Invalid stop distance: {stop_distance}")
                    investor_orders_skipped += 1
                    stats["orders_skipped"] += 1
                    continue
                
                # Calculate current risk in USD with full precision
                current_risk_usd = calculate_risk_usd(order.volume_initial, stop_distance, tick_size, tick_value)
                # 🔧 FIX: Keep full precision for risk calculation
                
                print(f"       Volume: {order.volume_initial} | Stop distance: {stop_distance:.{symbol_info.digits}f} | Risk: ${current_risk_usd:.2f}")
                print(f"       Using {'HEDGE' if is_hedge else 'REGULAR'} R:R default: 1:{order_default_rr}")
                
                # Calculate current R:R if TP exists
                current_rr = None
                if order.tp != 0:
                    if is_buy:
                        tp_distance = order.tp - order.price_open
                    else:
                        tp_distance = order.price_open - order.tp
                    
                    if stop_distance > 0:
                        current_rr = round(tp_distance / stop_distance, 2)
                        print(f"       Current R:R: 1:{current_rr}")
                    else:
                        current_rr = None
                
                # Find target R:R based on current value using appropriate R:R values
                if current_rr is not None:
                    target_rr, match_type = find_nearest_rr(current_rr, order_rr_values)
                    
                    if match_type == "next_higher":
                        print(f"       🔍 Using next higher R:R: 1:{target_rr} (from 1:{current_rr})")
                    elif match_type == "closest":
                        print(f"       🔍 Using closest R:R: 1:{target_rr} (from 1:{current_rr}) - no higher value")
                    else:
                        target_rr = order_default_rr
                        print(f"       ℹ️  Using default R:R: 1:{target_rr}")
                    
                    # Track R:R usage
                    rr_key = f"{'hedge' if is_hedge else 'regular'}_{str(target_rr)}"
                    if rr_key not in stats["rr_matches"]:
                        stats["rr_matches"][rr_key] = 0
                    stats["rr_matches"][rr_key] += 1
                else:
                    target_rr = order_default_rr
                    print(f"       ℹ️  No current R:R found, using default: 1:{target_rr}")
                    stats["rr_mismatches"] += 1
                
                # Calculate new take profit price with full precision
                new_tp = calculate_tp_price_from_risk(order.price_open, current_risk_usd, target_rr, 
                                                     is_buy, symbol_info, order.volume_initial, tick_size, tick_value)
                
                if new_tp is None:
                    print(f"        Cannot calculate TP price. Skipping.")
                    investor_orders_skipped += 1
                    stats["orders_skipped"] += 1
                    continue
                
                # 🔧 FIX: Validate TP price with tolerance
                digits = symbol_info.digits
                tolerance = symbol_info.point * 0.1
                
                if is_buy and new_tp <= order.price_open + tolerance:
                    print(f"        Calculated TP {new_tp:.{digits}f} is not above entry {order.price_open:.{digits}f} (with tolerance). Skipping.")
                    investor_orders_skipped += 1
                    stats["orders_skipped"] += 1
                    continue
                elif not is_buy and new_tp >= order.price_open - tolerance:
                    print(f"        Calculated TP {new_tp:.{digits}f} is not below entry {order.price_open:.{digits}f} (with tolerance). Skipping.")
                    investor_orders_skipped += 1
                    stats["orders_skipped"] += 1
                    continue
                
                # Calculate target profit with full precision
                target_profit = current_risk_usd * target_rr
                print(f"       Target R:R: 1:{target_rr} | Risk: ${current_risk_usd:.4f} | Target Profit: ${target_profit:.4f}")
                
                # 🔧 FIX: Improved comparison for cent-level precision
                current_move = abs(order.tp - order.price_open) if order.tp != 0 else 0
                target_move = abs(new_tp - order.price_open)
                
                should_adjust = False
                
                if order.tp == 0:
                    print(f"       📝 No TP currently set")
                    print(f"       Target TP: {new_tp:.{digits}f} (Move: {target_move:.{digits}f})")
                    should_adjust = True
                else:
                    # 🔧 FIX: Use absolute 1-point threshold instead of percentage
                    point_threshold = symbol_info.point * 1
                    
                    if abs(current_move - target_move) > point_threshold:
                        print(f"       📐 TP needs adjustment (difference: {abs(current_move - target_move):.{digits}f} > {point_threshold:.{digits}f})")
                        print(f"       Current TP: {order.tp:.{digits}f} (Move: {current_move:.{digits}f})")
                        print(f"       Target TP:  {new_tp:.{digits}f} (Move: {target_move:.{digits}f})")
                        should_adjust = True
                    else:
                        print(f"       ✅ TP already correct (within {point_threshold:.{digits}f})")
                        investor_orders_skipped += 1
                        stats["orders_skipped"] += 1
                        continue
                
                if should_adjust:
                    # Prepare modification request for pending order
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
                        if is_hedge:
                            stats["hedge_orders_adjusted"] += 1
                        print(f"       ✅ TP adjusted successfully to {new_tp:.{digits}f}")
                    else:
                        investor_orders_error += 1
                        stats["orders_error"] += 1
                        error_msg = result.comment if result else f"Error code: {result.retcode if result else 'Unknown'}"
                        print(f"        Modification failed: {error_msg}")

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
    
    if stats["hedge_orders_found"] > 0:
        print(f"\n   🛡️  Hedge Orders:")
        print(f"       • Found in history: {stats['hedge_orders_found']}")
        print(f"       • Adjusted: {stats['hedge_orders_adjusted']}")
    
    if stats["rr_matches"]:
        print(f"\n   📊 R:R Usage Breakdown:")
        for rr, count in sorted(stats["rr_matches"].items()):
            rr_type, rr_value = rr.split('_', 1)
            print(f"       • [{rr_type.upper()}] 1:{rr_value}: {count} orders")
    if stats["rr_mismatches"] > 0:
        print(f"    Orders using default R:R (no match): {stats['rr_mismatches']}")
    
    total_checked = stats['positions_checked'] + stats['orders_checked']
    total_adjusted = stats['positions_adjusted'] + stats['orders_adjusted']
    if total_checked > 0:
        success_rate = (total_adjusted / total_checked) * 100
        print(f"   Adjustment success rate: {success_rate:.1f}%")
    
    print(f"\n{'='*10} 🏁 INTELLIGENT R:R CORRECTION COMPLETE {'='*10}\n")
    return stats

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
    print(f"\n{'='*10} 🎯 DYNAMIC BREAKEVEN {'='*10}")
    if inv_id:
        print(f" Processing: {inv_id}")
    
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
        print(f"\n[{processed}/{total_investors}] {user_brokerid}")
        
        # Get broker config
        broker_cfg = usersdictionary.get(user_brokerid)
        if not broker_cfg:
            print(f"  └─  No broker config")
            continue
        
        inv_root = Path(INV_PATH) / user_brokerid
        acc_mgmt_path = inv_root / "accountmanagement.json"
        if not acc_mgmt_path.exists():
            print(f"  └─ Account config missing")
            continue
        
        # --- LOAD CONFIG AND CHECK SETTINGS ---
        try:
            with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            settings = config.get("settings", {})
            if not settings.get("enable_breakeven", False):
                print(f"  └─ ⏭️ Breakeven disabled")
                continue
            
            # Get breakeven dictionary and remove duplicates
            breakeven_config = settings.get("breakeven_dictionary", [])
            if not breakeven_config:
                breakeven_config = [
                    {"reward": 1, "breakeven_at_reward": 0.5},
                    {"reward": 2, "breakeven_at_reward": 1},
                    {"reward": 3, "breakeven_at_reward": 1.5}
                ]
            
            # Sort and remove duplicates (keep highest reward threshold for same breakeven)
            breakeven_config.sort(key=lambda x: x["reward"])
            unique_config = []
            seen_breakevens = set()
            for rule in reversed(breakeven_config):  # Reverse to keep higher thresholds
                key = rule["breakeven_at_reward"]
                if key not in seen_breakevens:
                    unique_config.insert(0, rule)
                    seen_breakevens.add(key)
            breakeven_config = unique_config
            
            print(f"  └─ ✅ {len(breakeven_config)} levels loaded")
            
        except Exception as e:
            print(f"  └─  Config error: {e}")
            stats["positions_error"] += 1
            continue
        
        # --- ACCOUNT INITIALIZATION ---
        login_id = int(broker_cfg['LOGIN_ID'])
        mt5_path = broker_cfg["TERMINAL_PATH"]
        
        acc = mt5.account_info()
        if acc is None or acc.login != login_id:
            if not mt5.login(login_id, password=broker_cfg["PASSWORD"], server=broker_cfg["SERVER"]):
                print(f"  └─  Login failed: {mt5.last_error()}")
                stats["positions_error"] += 1
                continue
        
        acc_info = mt5.account_info()
        if not acc_info:
            print(f"  └─  No account info")
            stats["positions_error"] += 1
            continue
            
        # --- CHECK ALL OPEN POSITIONS ---
        positions = mt5.positions_get()
        investor_positions_adjusted = 0
        investor_breakeven_events = 0
        investor_positions_error = 0
        
        if positions:
            positions_to_check = [p for p in positions if p.sl != 0 and p.profit > 0]
            
            if positions_to_check:
                print(f"  └─ 🔍 Checking {len(positions_to_check)} profitable positions...")
                
                for position in positions_to_check:
                    # Get symbol info
                    symbol_info = mt5.symbol_info(position.symbol)
                    if not symbol_info:
                        continue
                    
                    is_buy = position.type == mt5.POSITION_TYPE_BUY
                    
                    # Calculate risk
                    if is_buy:
                        risk_distance = position.price_open - position.sl
                    else:
                        risk_distance = position.sl - position.price_open
                    
                    # Calculate risk in USD
                    calc_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
                    sl_profit = mt5.order_calc_profit(calc_type, position.symbol, position.volume, 
                                                      position.price_open, position.sl)
                    if sl_profit is None:
                        continue
                    
                    risk_usd = round(abs(sl_profit), 2)
                    current_r_multiple = position.profit / risk_usd if risk_usd > 0 else 0
                    
                    # Find applicable rules
                    applicable_rules = [rule for rule in breakeven_config if current_r_multiple >= rule["reward"]]
                    if not applicable_rules:
                        continue
                    
                    # Get highest applicable rule
                    highest_rule = applicable_rules[-1]
                    target_reward = highest_rule["breakeven_at_reward"]
                    
                    # Get market info for validation
                    tick = mt5.symbol_info_tick(position.symbol)
                    if not tick:
                        continue
                    
                    current_price = tick.bid if not is_buy else tick.ask
                    digits = symbol_info.digits
                    stoplevel = max(symbol_info.trade_stops_level, 10) * symbol_info.point
                    
                    # Try fallback levels in order
                    current_index = breakeven_config.index(highest_rule)
                    sl_set = False
                    
                    for i in range(current_index, -1, -1):
                        test_reward = breakeven_config[i]["breakeven_at_reward"]
                        
                        # Calculate target SL
                        if is_buy:
                            target_sl = position.price_open + (risk_distance * test_reward)
                            is_valid_direction = target_sl < current_price - stoplevel and target_sl > position.sl
                        else:
                            target_sl = position.price_open - (risk_distance * test_reward)
                            is_valid_direction = target_sl > current_price + stoplevel and target_sl < position.sl
                        
                        if is_valid_direction:
                            target_sl = round(target_sl, digits)
                            
                            # Send modification
                            modify_request = {
                                "action": mt5.TRADE_ACTION_SLTP,
                                "position": position.ticket,
                                "sl": target_sl,
                                "tp": position.tp,
                            }
                            
                            result = mt5.order_send(modify_request)
                            
                            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                                investor_positions_adjusted += 1
                                investor_breakeven_events += 1
                                stats["positions_adjusted"] += 1
                                stats["breakeven_events"] += 1
                                print(f"     ✅ #{position.ticket} → SL @ {test_reward}R")
                                sl_set = True
                                break
                    
                    if not sl_set:
                        investor_positions_error += 1
                        stats["positions_error"] += 1
                        print(f"      #{position.ticket} → fallback failed")
            
            else:
                print(f"  └─ 🔘 No profitable positions")
        
        stats["positions_checked"] += len(positions_to_check) if positions else 0
        
        # --- INVESTOR SUMMARY ---
        print(f"  └─ 📊 Adjusted: {investor_positions_adjusted} | Errors: {investor_positions_error}")
        stats["processing_success"] = True
    
    # --- FINAL SUMMARY ---
    print(f"\n{'='*10} 📊 SUMMARY {'='*10}")
    print(f"  Adjusted: {stats['positions_adjusted']}/{stats['positions_checked']}")
    print(f"  Errors: {stats['positions_error']}")
    print(f"{'='*10} 🏁 COMPLETE {'='*10}\n")
    
    return stats

def trades_analytics(inv_id=None):
    """
    Fetch and record all individual trades grouped by risk configurations,
    segregated into dual chronological windows:
      - from_execution_start_date: Full lifetime history since broker launch.
      - last_28_days: A rolling snapshot tracking the immediate trailing 28 days.
    
    Reconciles missing profiles and fields between FETCHED_INVESTORS and UPDATED_INVESTORS.
    """
    
    print("\n" + "="*80)
    print(" 📊 TRADES ANALYTICS SYSTEM DIAGNOSTIC INITIALIZED".ljust(79) + "=")
    print("="*80)
    
    stats = {
        "investor_id": inv_id if inv_id else "all",
        "investors_processed": 0,
        "total_trades_recorded": 0,
        "processing_success": False
    }
    
    # Check usersdictionary presence (assumed defined globally in your script context)
    try:
        active_users_dict = usersdictionary
    except NameError:
        active_users_dict = {}
        print(" ⚠️ Warning: 'usersdictionary' not found globally. Initializing blank fallback context.")

    investor_ids = [inv_id] if inv_id else list(active_users_dict.keys())
    if not investor_ids:
        print(" No active investors discovered inside runtime context properties.")
        print("="*80)
        return stats
    
    # Dictionary to keep track of generated analytics structures for synchronization later
    generated_analytics_registry = {}
    
    # Iterate System Investors
    for user_brokerid in investor_ids:
        print(f"\n" + "═"*80)
        print(f" PROFILE ANALYSIS: INVESTOR ID -> {user_brokerid}".ljust(79) + "═")
        print("═"*80)
        
        # Note: INV_PATH assumed defined globally in your environment
        try:
            root_dir_base = INV_PATH
        except NameError:
            root_dir_base = r"C:\xampp\htdocs\harvcore\users"
            
        inv_root = Path(root_dir_base) / str(user_brokerid)
        if not inv_root.exists():
            print(f" │ Operational folder structure missing: {inv_root}")
            continue
        
        activities_path = inv_root / "activities.json"
        acct_mgmt_path = inv_root / "accountmanagement.json"
        
        if not activities_path.exists():
            print(f" │ Profile tracking state file missing: {activities_path}")
            continue
        
        try:
            with open(activities_path, 'r', encoding='utf-8') as f:
                activities_data = json.load(f)
        except Exception as e:
            print(f" │ Error parsing profile tracking state: {e}")
            continue
        
        execution_start_date = activities_data.get('execution_start_date')
        if not execution_start_date:
            print(f" │ No operational start boundary 'execution_start_date' flagged inside tracking state.")
            continue

        broker_cfg = active_users_dict.get(user_brokerid)
        if not broker_cfg:
            print(f" │ Critical authorization mapping criteria missing inside system dictionary.")
            continue

        login_id = broker_cfg.get('LOGIN_ID', '')
        if not login_id:
            print(f" │ System environment mapping requires an active 'LOGIN_ID'.")
            continue

        try:
            unique_magic_number = int(str(login_id) + str(user_brokerid))
        except (ValueError, TypeError) as e:
            print(f" │ Failed to construct transaction cryptographic signature: {e}")
            continue

        activities_data['authorized_magic_number'] = unique_magic_number
        activities_data['unique_magicnumber'] = unique_magic_number

        # LOAD CONFIGURATION TARGETS
        max_allowable_risk_threshold = 0.0
        be_dict_sorted = []

        if acct_mgmt_path.exists():
            try:
                with open(acct_mgmt_path, 'r', encoding='utf-8') as f:
                    acct_config = json.load(f)
                    default_risks = acct_config.get("account_balance_default_risk_management", {})
                    max_risks = acct_config.get("account_balance_maximum_risk_management", {})
                    
                    settings = acct_config.get("settings", {})
                    be_dict = settings.get("breakeven_dictionary", [])
                    be_dict_sorted = sorted(be_dict, key=lambda x: float(x.get("reward", 0.0)), reverse=True)
                    
                    extracted_values = []
                    for risk_dict in [default_risks, max_risks]:
                        for k, target_val in risk_dict.items():
                            try:
                                extracted_values.append(float(target_val))
                            except (ValueError, TypeError):
                                continue
                    
                    if extracted_values:
                        max_allowable_risk_threshold = max(extracted_values)
            except Exception as e:
                print(f" │ └── Error parsing accountmanagement.json: {e}")

        start_datetime = None
        for fmt in ["%Y-%m-%d", "%B %d, %Y", "%Y/%m/%d"]:
            try:
                start_datetime = datetime.strptime(str(execution_start_date), fmt)
                break
            except:
                continue
        
        if not start_datetime:
            print(f" │ Failed to parse operational start boundary string format: {execution_start_date}")
            continue
        
        # Calculate trailing 28-day boundary floor
        now_time = datetime.now()
        trailing_28d_floor = now_time - timedelta(days=28)
        
        # Fetch widest window possible to cover both segments
        query_start_datetime = min(start_datetime, trailing_28d_floor)
        history_deals = mt5.history_deals_get(query_start_datetime, now_time)
        if not history_deals:
            print(f" │ ℹ️ Zero closed trade records detected on account terminal layer history.")
            continue
        
        deals_by_position = {}
        for deal in history_deals:
            if deal.type in [0, 1]:
                position_key = deal.position_id
                if position_key not in deals_by_position:
                    deals_by_position[position_key] = []
                deals_by_position[position_key].append(deal)
        
        master_flat_processed_trades = []
        
        # EVALUATE INDIVIDUAL POSITION RECORDS
        for position_id, deals in deals_by_position.items():
            deals.sort(key=lambda x: x.time)
            
            total_profit = sum(deal.profit for deal in deals)
            total_commission = sum(deal.commission for deal in deals)
            total_swap = sum(deal.swap for deal in deals)
            total_pnl = total_profit + total_commission + total_swap
            
            entry_deal = deals[0]
            exit_deal = deals[-1] if len(deals) > 1 else None
            is_closed = len(deals) > 1 
            
            if not is_closed:
                continue
                
            is_authorized = (entry_deal.magic == unique_magic_number)
            auth_group = "authorized" if is_authorized else "unauthorized"
            
            trade_type = "BUY" if entry_deal.type == 0 else "SELL"
            mt5_action = mt5.ORDER_TYPE_BUY if entry_deal.type == 0 else mt5.ORDER_TYPE_SELL
            total_volume = entry_deal.volume
            entry_price = entry_deal.price
            
            stoploss = getattr(entry_deal, 'sl', 0.0)
            takeprofit = getattr(entry_deal, 'tp', 0.0)
            
            if stoploss == 0.0 or takeprofit == 0.0:
                related_orders = mt5.history_orders_get(position=position_id)
                if related_orders:
                    for order in related_orders:
                        if order.sl > 0.0 and stoploss == 0.0:
                            stoploss = order.sl
                        if order.tp > 0.0 and takeprofit == 0.0:
                            takeprofit = order.tp
            
            trade_risk = 0.0
            risk_reward = "N/A"
            max_possible_r = None
            
            if stoploss > 0.0:
                calculated_risk_pnl = mt5.order_calc_profit(mt5_action, entry_deal.symbol, total_volume, entry_price, stoploss)
                if calculated_risk_pnl is not None:
                    trade_risk = abs(calculated_risk_pnl)
            
            if stoploss > 0.0 and stoploss != entry_price:
                price_risk_distance = abs(entry_price - stoploss)
                if price_risk_distance > 0:
                    if takeprofit > 0.0:
                        price_reward_distance = abs(takeprofit - entry_price)
                        max_possible_r = round(price_reward_distance / price_risk_distance, 2)
                        risk_reward = max_possible_r
                    elif total_pnl < 0:
                        risk_reward = 1.0

            resolved_risk = trade_risk if trade_risk > 0 else abs(total_pnl) if total_pnl < 0 else 0.0

            trade_owned_by_rr = "N/A"
            trade_owned_by_rr_raw = "N/A"
            closed_at_reward = 0.0
            claimed_reason = "N/A"
            inherited_beneficiaries = []
            
            if resolved_risk > 0:
                realized_r_multiplier = total_pnl / resolved_risk
                closed_at_reward = round(realized_r_multiplier, 2)
                
                is_flat_breakeven = (0.0 <= total_pnl <= 0.10)
                is_half_risk_breakeven = (total_pnl > 0.10 and total_pnl <= (resolved_risk * 0.50))
                
                matched_explicitly = False
                
                if (is_flat_breakeven or is_half_risk_breakeven) and be_dict_sorted:
                    lowest_rule = be_dict_sorted[-1]
                    target_reward_value = float(lowest_rule.get("reward", 0.0))
                    trade_owned_by_rr = f"primary target:{lowest_rule.get('reward')}"
                    
                    reason_type = "flat market friction noise" if is_flat_breakeven else "structural exit within 50% risk boundary"
                    claimed_reason = f"claimed because trade qualified as a breakeven exit ({reason_type}) consolidated into lowest tier {target_reward_value}"
                    trade_owned_by_rr_raw = str(lowest_rule.get("reward"))
                    matched_explicitly = True
                else:
                    for rule in be_dict_sorted:
                        target_reward_value = float(rule.get("reward", 0.0))
                        be_trigger_threshold = float(rule.get("breakeven_at_reward", 0.0))
                        
                        if max_possible_r is not None and realized_r_multiplier >= be_trigger_threshold and max_possible_r >= target_reward_value:
                            trade_owned_by_rr = f"primary target:{rule.get('reward')}"
                            claimed_reason = f"claimed because reward at {target_reward_value} requested to breakeven at {be_trigger_threshold}"
                            trade_owned_by_rr_raw = str(rule.get("reward"))
                            matched_explicitly = True
                            break
                
                if matched_explicitly:
                    primary_value = float(trade_owned_by_rr_raw)
                    for rule in be_dict_sorted:
                        loop_val = float(rule.get("reward", 0.0))
                        if loop_val < primary_value:
                            inherited_beneficiaries.append(str(rule.get("reward")))
                    
                    def internal_sort(v):
                        try: return float(v)
                        except: return 0.0
                    inherited_beneficiaries = sorted(list(set(inherited_beneficiaries)), key=internal_sort)
                    
                    if inherited_beneficiaries:
                        trade_owned_by_rr = f"primary target:{trade_owned_by_rr_raw}"
                        trade_record_beneficiary_string = ",".join(inherited_beneficiaries)
                    else:
                        trade_record_beneficiary_string = "none"
                else:
                    if max_possible_r is not None and total_pnl > 0:
                        trade_owned_by_rr = f"primary target:{max_possible_r}"
                        trade_owned_by_rr_raw = str(max_possible_r)
                        claimed_reason = f"claimed by the actual trade risk reward potential of {max_possible_r}"
                        trade_record_beneficiary_string = "none"
                    elif total_pnl <= 0:
                        trade_owned_by_rr = "N/A"
                        trade_owned_by_rr_raw = "N/A"
                        claimed_reason = "unclaimed because trade closed out at a loss"
                        trade_record_beneficiary_string = "none"

            is_within_risk = (0.0 < resolved_risk <= max_allowable_risk_threshold)
            
            trade_record = {
                "ticket": position_id,
                "symbol": entry_deal.symbol,
                "type": trade_type,
                "entry_price": round(entry_price, 5),
                "stoploss": round(stoploss, 5),
                "take_profit": round(takeprofit, 5),
                "trade_risk": resolved_risk,
                "risk_reward": risk_reward,
                "trade_owned_by_risk_reward": trade_owned_by_rr,
                "trade_owned_by_risk_reward_raw_target": trade_owned_by_rr_raw,
                "beneficiaries": trade_record_beneficiary_string,
                "closed_at_reward": closed_at_reward,
                "claimed_reason": claimed_reason,
                "volume": round(total_volume, 2),
                "time_open": datetime.fromtimestamp(entry_deal.time).strftime('%Y-%m-%d %H:%M:%S'),
                "time_close": datetime.fromtimestamp(exit_deal.time).strftime('%Y-%m-%d %H:%M:%S'),
                "magic": entry_deal.magic,
                "total_pnl": round(total_pnl, 2),
                "state": "CLOSED",
                "raw_close_time": exit_deal.time,
                "is_within_risk": is_within_risk,
                "auth_group": auth_group
            }
            master_flat_processed_trades.append(trade_record)

        # SEPARATE PIPELINE STATISTICS BUILDER UTILITY
        def run_segment_analytics(trades_pool, window_start_dt, mode="full"):
            trades_pool.sort(key=lambda x: x["raw_close_time"])
            t_count = len(trades_pool)
            
            p_list = [t for t in trades_pool if t["total_pnl"] > 0]
            l_list = [t for t in trades_pool if t["total_pnl"] < 0]
            
            p_count, l_count = len(p_list), len(l_list)
            t_pnl = sum(t["total_pnl"] for t in trades_pool)
            
            w_rate = round((p_count / t_count * 100), 2) if t_count > 0 else 0.0
            l_rate = round((l_count / t_count * 100), 2) if t_count > 0 else 0.0
            
            sym_map = {}
            sl_tp_count, no_sl_tp_count = 0, 0
            for t in trades_pool:
                s = t["symbol"]
                if t["stoploss"] > 0 and t["take_profit"] > 0:
                    sl_tp_count += 1
                else:
                    no_sl_tp_count += 1
                    
                if s not in sym_map:
                    sym_map[s] = {"total_trades": 0, "wins_count": 0, "gross_profit_revenue": 0.0, "gross_loss_revenue": 0.0, "total_pnl": 0.0}
                m = sym_map[s]
                m["total_trades"] += 1
                m["total_pnl"] += t["total_pnl"]
                if t["total_pnl"] > 0:
                    m["wins_count"] += 1
                    m["gross_profit_revenue"] += t["total_pnl"]
                elif t["total_pnl"] < 0:
                    m["gross_loss_revenue"] += abs(t["total_pnl"])

            processed_symbols = []
            for s_name, sm in sym_map.items():
                denom_rev = sm["gross_profit_revenue"] + sm["gross_loss_revenue"]
                processed_symbols.append({
                    "symbol": s_name,
                    "winrate_by_count": round((sm["wins_count"] / sm["total_trades"] * 100), 2) if sm["total_trades"] > 0 else 0.0,
                    "winrate_by_revenue": round((sm["gross_profit_revenue"] / denom_rev * 100), 2) if denom_rev > 0 else 0.0,
                    "pnl": round(sm["total_pnl"], 2)
                })

            best_c, best_r, poor_c, poor_r = {}, {}, {}, {}
            if processed_symbols:
                v_bc = [s for s in processed_symbols if s["winrate_by_count"] >= 20.0]
                if v_bc: 
                    top_c = sorted(v_bc, key=lambda x: x["winrate_by_count"], reverse=True)[0]
                    best_c = {"symbol": top_c["symbol"], "winrate_by_count": top_c["winrate_by_count"], "pnl": top_c["pnl"]}
                
                pc = sorted(processed_symbols, key=lambda x: x["winrate_by_count"])[0]
                poor_c = {"symbol": pc["symbol"], "winrate_by_count": pc["winrate_by_count"], "pnl": pc["pnl"]}
                
                if mode == "full":
                    v_br = [s for s in processed_symbols if s["winrate_by_revenue"] >= 20.0]
                    if v_br: 
                        top_r = sorted(v_br, key=lambda x: x["winrate_by_revenue"], reverse=True)[0]
                        best_r = {"symbol": top_r["symbol"], "winrate_by_revenue": top_r["winrate_by_revenue"], "pnl": top_r["pnl"]}
                    pr = sorted(processed_symbols, key=lambda x: x["winrate_by_revenue"])[0]
                    poor_r = {"symbol": pr["symbol"], "winrate_by_revenue": pr["winrate_by_revenue"], "pnl": pr["pnl"]}

            hi_losses = {}
            curr_streak = []
            max_loss_streak = 0.0
            for t in trades_pool:
                if t["total_pnl"] >= 0.01:
                    if len(curr_streak) >= 3:
                        s_loss = abs(sum(x["total_pnl"] for x in curr_streak))
                        if s_loss > max_loss_streak:
                            max_loss_streak = s_loss
                            hi_losses = {"consecutive_losses_count": len(curr_streak), "total_loss_pnl": round(-s_loss, 2), "trades": [{**x} for x in curr_streak]}
                    curr_streak = []
                elif t["total_pnl"] < 0:
                    curr_streak.append(t)
            if len(curr_streak) >= 3:
                s_loss = abs(sum(x["total_pnl"] for x in curr_streak))
                if s_loss > max_loss_streak: hi_losses = {"consecutive_losses_count": len(curr_streak), "total_loss_pnl": round(-s_loss, 2), "trades": [{**x} for x in curr_streak]}

            hi_days = {}
            d_pnl_map, d_trades_map = {}, {}
            for t in trades_pool:
                td = datetime.fromtimestamp(t["raw_close_time"]).strftime('%Y-%m-%d')
                d_pnl_map[td] = d_pnl_map.get(td, 0.0) + t["total_pnl"]
                if td not in d_trades_map: d_trades_map[td] = []
                d_trades_map[td].append(t)

            chron_days = sorted(d_pnl_map.keys())
            curr_day_streak = []
            max_day_streak_loss = 0.0
            
            def finish_day_streak(streak):
                nonlocal max_day_streak_loss, hi_days
                if len(streak) >= 2:
                    s_loss = abs(sum(d_pnl_map[d] for d in streak))
                    if s_loss > max_day_streak_loss:
                        max_day_streak_loss = s_loss
                        hi_days = {"consecutive_days_count": len(streak), "total_loss_pnl": round(-s_loss, 2), "days": {d: [{**w} for w in d_trades_map[d]] for d in streak}}

            for d in chron_days:
                if d_pnl_map[d] >= 0.01:
                    finish_day_streak(curr_day_streak)
                    curr_day_streak = []
                elif d_pnl_map[d] < 0:
                    curr_day_streak.append(d)
            finish_day_streak(curr_day_streak)

            cal_matrix = {}
            loop_date = window_start_dt.date()
            while loop_date <= datetime.now().date():
                cal_matrix[loop_date.strftime('%Y-%m-%d')] = []
                loop_date += timedelta(days=1)
            for t in trades_pool:
                t_dt = datetime.fromtimestamp(t["raw_close_time"]).strftime('%Y-%m-%d')
                if t_dt in cal_matrix:
                    c_trade = {**t}
                    c_trade.pop("raw_close_time", None)
                    c_trade.pop("is_within_risk", None)
                    c_trade.pop("auth_group", None)
                    c_trade.pop("trade_owned_by_risk_reward_raw_target", None)
                    cal_matrix[t_dt].append(c_trade)

            for x in hi_losses.get("trades", []): 
                x.pop("raw_close_time", None)
                x.pop("is_within_risk", None)
                x.pop("auth_group", None)
                x.pop("trade_owned_by_risk_reward_raw_target", None)
            for d in hi_days.get("days", {}):
                for x in hi_days["days"][d]: 
                    x.pop("raw_close_time", None)
                    x.pop("is_within_risk", None)
                    x.pop("auth_group", None)
                    x.pop("trade_owned_by_risk_reward_raw_target", None)

            if mode == "count_only":
                return {
                    "total_trades": t_count, "total_pnl": round(t_pnl, 2),
                    "profit_trades": p_count, "loss_trades": l_count,
                    "win_rate_by_count": w_rate, "loss_rate_by_count": l_rate,
                    "symbols_traded": len(sym_map), "closed_deals_with_sl_tp": sl_tp_count, "closed_deals_without_sl_tp": no_sl_tp_count,
                    "symbols_contest": {"best_symbol_winrate_by_count": best_c, "poorest_symbol_winrate_by_count": poor_c},
                    "highest_sequential_losses": hi_losses, "highest_sequential_days_in_loss": hi_days, "all_trades": cal_matrix
                }
            else:
                p_rev = sum(t["total_pnl"] for t in p_list)
                l_rev = sum(t["total_pnl"] for t in l_list)
                turnover = p_rev + abs(l_rev)
                w_rev_rate = round((p_rev / turnover * 100), 2) if turnover > 0 else 0.0
                l_rev_rate = round((abs(l_rev) / turnover * 100), 2) if turnover > 0 else 0.0
                
                return {
                    "total_trades": t_count, "total_pnl": round(t_pnl, 2),
                    "profit_trades": p_count, "loss_trades": l_count, "profit_amount": p_count, "loss_amount": l_count,
                    "win_rate_by_count": w_rate, "loss_rate_by_count": l_rate, "win_rate_by_revenue": w_rev_rate, "loss_rate_by_revenue": l_rev_rate,
                    "symbols_traded": len(sym_map), "closed_deals_with_sl_tp": sl_tp_count, "closed_deals_without_sl_tp": no_sl_tp_count,
                    "symbols_contest": {"best_symbol_winrate_by_count": best_c, "best_symbol_winrate_by_revenue": best_r, "poorest_symbol_winrate_by_count": poor_c, "poorest_symbol_winrate_by_revenue": poor_r},
                    "highest_sequential_losses": hi_losses, "highest_sequential_days_in_loss": hi_days, "all_trades": cal_matrix
                }

        # FINAL ANALYTICS JSON CONTAINER GENERATOR
        final_analytics_payload = {
            "from_execution_start_date": {
                "start_date": execution_start_date,
                "end_date": now_time.strftime('%Y-%m-%d'),
                "last_updated": now_time.isoformat()
            },
            "last_28_days": {
                "start_date": trailing_28d_floor.strftime("%B %d, %Y"),
                "end_date": now_time.strftime('%Y-%m-%d'),
                "last_updated": now_time.isoformat()
            }
        }
        
        total_combined_trades = 0

        # EXECUTE MATRIX POPULATION PER TIMELINE ROOT NODE
        for window_key in ["from_execution_start_date", "last_28_days"]:
            window_floor_ts = start_datetime.timestamp() if window_key == "from_execution_start_date" else trailing_28d_floor.timestamp()
            window_start_dt_obj = start_datetime if window_key == "from_execution_start_date" else trailing_28d_floor
            
            timeframe_filtered_pool = [t for t in master_flat_processed_trades if t["raw_close_time"] >= window_floor_ts]
            
            for c_group in ["trades_within_risks_config", "trades_outside_risks_config"]:
                final_analytics_payload[window_key][c_group] = {
                    "summaries": {
                        "summaries_of_profits_only": {},
                        "summaries_of_profits_and_flat_breakeven": {}
                    },
                    "regular_data": {}
                }
                
                is_within = (c_group == "trades_within_risks_config")
                bracket_trades = [t for t in timeframe_filtered_pool if t["is_within_risk"] == is_within]
                
                all_discovered_rewards = set(str(t["trade_owned_by_risk_reward_raw_target"]) for t in bracket_trades if t["trade_owned_by_risk_reward_raw_target"] != "N/A")
                
                def numeric_sort(val):
                    try: return float(val)
                    except ValueError: return 999.0
                sorted_rewards = sorted(list(all_discovered_rewards), key=numeric_sort)

                # --- CATEGORY A: SUMMARIES OF PROFITS ONLY ---
                total_losses_profits_only = sum(1 for t in bracket_trades if t["total_pnl"] <= 0)
                total_won_profits_only = sum(1 for t in bracket_trades if t["total_pnl"] > 0)
                
                # Revenue Calculations
                revenue_lost_profits_only = sum(abs(t["total_pnl"]) for t in bracket_trades if t["total_pnl"] <= 0)
                revenue_won_profits_only = sum(t["total_pnl"] for t in bracket_trades if t["total_pnl"] > 0)
                
                for reward_key in sorted_rewards:
                    claimed_pool = []
                    for t in bracket_trades:
                        is_primary = (str(t["trade_owned_by_risk_reward_raw_target"]) == reward_key)
                        is_beneficiary = (reward_key in [b.strip() for b in t["beneficiaries"].split(",")])
                        if (is_primary or is_beneficiary) and t["total_pnl"] > 0:
                            claimed_pool.append(t)
                            
                    total_claimed = len(claimed_pool)
                    denom = total_claimed + total_losses_profits_only
                    winrate = round((total_claimed / denom * 100), 2) if denom > 0 else 0.0
                    
                    final_analytics_payload[window_key][c_group]["summaries"]["summaries_of_profits_only"][f"total_claimed_trades_by_risk_reward_{reward_key}"] = total_claimed
                    final_analytics_payload[window_key][c_group]["summaries"]["summaries_of_profits_only"][f"total_claimed_trades_by_risk_reward_{reward_key}_winrate_by_count"] = winrate

                final_analytics_payload[window_key][c_group]["summaries"]["summaries_of_profits_only"]["total_lost_trades_by_count"] = total_losses_profits_only
                final_analytics_payload[window_key][c_group]["summaries"]["summaries_of_profits_only"]["total_won_trades_by_count"] = total_won_profits_only
                final_analytics_payload[window_key][c_group]["summaries"]["summaries_of_profits_only"]["total_lost_trades_by_revenue"] = round(revenue_lost_profits_only, 2)
                final_analytics_payload[window_key][c_group]["summaries"]["summaries_of_profits_only"]["total_won_trades_by_revenue"] = round(revenue_won_profits_only, 2)

                # --- CATEGORY B: SUMMARIES OF PROFITS AND FLAT BREAKEVEN ---
                total_losses_with_be = 0
                total_won_with_be = 0
                
                revenue_lost_with_be = 0.0
                revenue_won_with_be = 0.0
                
                for t in bracket_trades:
                    if t["total_pnl"] > 0:
                        total_won_with_be += 1
                        revenue_won_with_be += t["total_pnl"]
                    else:
                        if t["trade_risk"] > 0 and t["total_pnl"] >= (-0.50 * t["trade_risk"]):
                            total_won_with_be += 1
                            # Treat flat/breakeven balance adjustments under won-revenue metrics
                            revenue_won_with_be += t["total_pnl"]
                        else:
                            total_losses_with_be += 1
                            revenue_lost_with_be += abs(t["total_pnl"])

                for reward_key in sorted_rewards:
                    claimed_pool = []
                    for t in bracket_trades:
                        is_primary = (str(t["trade_owned_by_risk_reward_raw_target"]) == reward_key)
                        is_beneficiary = (reward_key in [b.strip() for b in t["beneficiaries"].split(",")])
                        
                        if is_primary or is_beneficiary:
                            if t["total_pnl"] > 0:
                                claimed_pool.append(t)
                            elif t["total_pnl"] <= 0 and t["trade_risk"] > 0 and t["total_pnl"] >= (-0.50 * t["trade_risk"]):
                                claimed_pool.append(t)
                                
                    total_claimed = len(claimed_pool)
                    denom = total_claimed + total_losses_with_be
                    winrate = round((total_claimed / denom * 100), 2) if denom > 0 else 0.0
                    
                    final_analytics_payload[window_key][c_group]["summaries"]["summaries_of_profits_and_flat_breakeven"][f"total_claimed_trades_by_risk_reward_{reward_key}"] = total_claimed
                    final_analytics_payload[window_key][c_group]["summaries"]["summaries_of_profits_and_flat_breakeven"][f"total_claimed_trades_by_risk_reward_{reward_key}_winrate_by_count"] = winrate

                final_analytics_payload[window_key][c_group]["summaries"]["summaries_of_profits_and_flat_breakeven"]["total_lost_trades_by_count"] = total_losses_with_be
                final_analytics_payload[window_key][c_group]["summaries"]["summaries_of_profits_and_flat_breakeven"]["total_won_trades_by_count"] = total_won_with_be
                final_analytics_payload[window_key][c_group]["summaries"]["summaries_of_profits_and_flat_breakeven"]["total_lost_trades_by_revenue"] = round(revenue_lost_with_be, 2)
                final_analytics_payload[window_key][c_group]["summaries"]["summaries_of_profits_and_flat_breakeven"]["total_won_trades_by_revenue"] = round(revenue_won_with_be, 2)

                # 2. Compile standard baseline regular datasets
                for a_group in ["authorized", "unauthorized"]:
                    source_trades = [t for t in bracket_trades if t["auth_group"] == a_group]
                    if window_key == "from_execution_start_date":
                        total_combined_trades += len(source_trades)
                    
                    regular_summary = run_segment_analytics([{**t} for t in source_trades], window_start_dt_obj, mode="full")
                    final_analytics_payload[window_key][c_group]["regular_data"][a_group] = regular_summary

                    # 3. Dynamic sub-nest creation using Milestone Waterfall Inheritance arrays
                    for reward_key in sorted_rewards:
                        reward_nest_key = f"risk_reward_{reward_key}"
                        if reward_nest_key not in final_analytics_payload[window_key][c_group]:
                            final_analytics_payload[window_key][c_group][reward_nest_key] = {}

                        allocated_pool = []
                        for t in source_trades:
                            is_primary = (str(t["trade_owned_by_risk_reward_raw_target"]) == reward_key)
                            is_beneficiary = (reward_key in [b.strip() for b in t["beneficiaries"].split(",")])
                            
                            if (is_primary or is_beneficiary) and t["total_pnl"] > 0:
                                allocated_pool.append({**t})
                            elif t["total_pnl"] <= 0:
                                allocated_pool.append({**t})

                        final_analytics_payload[window_key][c_group][reward_nest_key][a_group] = run_segment_analytics(allocated_pool, window_start_dt_obj, mode="count_only")

        # Strip internal temporary tracking keys before dumping analytics payload to files
        for window_key in ["from_execution_start_date", "last_28_days"]:
            for c_group in ["trades_within_risks_config", "trades_outside_risks_config"]:
                for key in list(final_analytics_payload[window_key][c_group].keys()):
                    if key.startswith("risk_reward_"):
                        for auth in ["authorized", "unauthorized"]:
                            if auth in final_analytics_payload[window_key][c_group][key]:
                                for day in final_analytics_payload[window_key][c_group][key][auth].get("all_trades", {}):
                                    for trd in final_analytics_payload[window_key][c_group][key][auth]["all_trades"][day]:
                                        trd.pop("trade_owned_by_risk_reward_raw_target", None)

        # LOCAL DISK ACTIVITIES ENGINE COMMIT
        for old_key in ['Analytics', 'AnalyticsSummary', 'AllTradesDetailed', 'last_analytics_update']:
            activities_data.pop(old_key, None)
            
        activities_data['analytics'] = final_analytics_payload
        
        try:
            with open(activities_path, 'w', encoding='utf-8') as f:
                json.dump(activities_data, f, indent=4)
            print(f" │ ✅ Performance payload successfully updated in: activities.json")
            # Cache payload internally for cross-file synchronization sequence below
            generated_analytics_registry[str(user_brokerid)] = final_analytics_payload
        except Exception as e:
            print(f" │ Error recording analytics payload to profile file: {e}")
            continue

        stats["investors_processed"] += 1
        stats["total_trades_recorded"] += total_combined_trades

    # =========================================================================
    # 🔄 CROSS-FILE DATABASE SYNCHRONIZATION BACKEND ENGINE
    # =========================================================================
    print("\n" + "═"*80)
    print(" 🔄 INITIATING CROSS-FILE INVESTOR MATRIX RECONCILIATION LAYER".ljust(79) + "═")
    print("═"*80)

    # 1. Load Primary Source (FETCHED_INVESTORS)
    fetched_data = {}
    if os.path.exists(FETCHED_INVESTORS):
        try:
            with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
                fetched_data = json.load(f)
            print(f" │ Loaded {len(fetched_data)} raw profiles from upstream source matrix.")
        except Exception as e:
            print(f" │ Error loading FETCHED_INVESTORS: {e}")
    else:
        print(f" │ ⚠️ Warning: Upstream source file missing at configured path: {FETCHED_INVESTORS}")

    # 2. Load Destination Storage Matrix (UPDATED_INVESTORS)
    updated_data = {}
    if os.path.exists(UPDATED_INVESTORS):
        try:
            with open(UPDATED_INVESTORS, 'r', encoding='utf-8') as f:
                updated_data = json.load(f)
            print(f" │ Loaded {len(updated_data)} profiles from active destination database.")
        except Exception as e:
            print(f" │ Error parsing UPDATED_INVESTORS: {e}. Resetting to an empty dictionary.")
            updated_data = {}

    # Define the base universe of user profiles to sync across files
    all_target_keys = set(list(fetched_data.keys()) + list(updated_data.keys()) + [str(uid) for uid in investor_ids])
    has_mutated_database = False

    for current_id in sorted(all_target_keys):
        # Determine tracking reference vectors
        upstream_source_record = fetched_data.get(current_id)
        destination_record = updated_data.get(current_id)
        runtime_broker_config = active_users_dict.get(int(current_id) if current_id.isdigit() else current_id)

        # ACTION A: Record does not exist in destination at all
        if destination_record is None:
            print(f" │ ➕ Destination Record '{current_id}' missing entirely. Creating target entry...")
            has_mutated_database = True
            
            if upstream_source_record is not None:
                # Copy entire object structure cleanly from primary master file
                destination_record = json.loads(json.dumps(upstream_source_record))
            else:
                # Upstream file is missing this ID. Fall back to local investor runtime metadata properties
                print(f" │   ⚠️ ID '{current_id}' missing from upstream source. Building placeholder structure...")
                destination_record = {
                    "id": str(current_id),
                    "broker": runtime_broker_config.get("BROKER", "NULL") if runtime_broker_config else "NULL",
                    "email": "NULL",
                    "fullname": "NULL",
                    "server": "NULL",
                    "login": str(runtime_broker_config.get("LOGIN_ID", "NULL")) if runtime_broker_config else "NULL",
                    "password": "NULL",
                    "application_status": "Approved",
                    "broker_balance": "0.00",
                    "profitandloss": "0.00",
                    "execution_start_date": datetime.now().strftime('%Y-%m-%d'),
                    "accountmanagement": {},
                    "analytics": {}
                }
            updated_data[current_id] = destination_record

        # ACTION B: Record exists but may have missing attributes
        elif upstream_source_record is not None:
            for field_key, field_value in upstream_source_record.items():
                if field_key not in destination_record:
                    print(f" │   ↳ Synchronizing missing schema property: [{field_key}] into record '{current_id}'")
                    destination_record[field_key] = json.loads(json.dumps(field_value))
                    has_mutated_database = True

        # ACTION C: Intercept and normalize analytics format states
        current_analytics_value = destination_record.get("analytics")
        if isinstance(current_analytics_value, str):
            # Convert raw SQL placeholder text structures to standard native JSON blocks
            if current_analytics_value.strip().upper() in ["NULL", '"NULL"', "'NULL'"]:
                destination_record["analytics"] = {}
                has_mutated_database = True
            else:
                try:
                    destination_record["analytics"] = json.loads(current_analytics_value)
                    has_mutated_database = True
                except Exception:
                    destination_record["analytics"] = {}
                    has_mutated_database = True

        # ACTION D: Inject fresh analytics data blocks if generated during this execution run
        if current_id in generated_analytics_registry:
            print(f" │   📦 Injecting fresh chronological analytics payload for client profile: {current_id}")
            destination_record.pop('trades_analytics', None)  # Scrub deprecated keys
            destination_record["analytics"] = generated_analytics_registry[current_id]
            has_mutated_database = True

    # 3. Save updates back to disk if modifications occurred
    if has_mutated_database:
        try:
            with open(UPDATED_INVESTORS, 'w', encoding='utf-8') as f:
                json.dump(updated_data, f, indent=4)
            print(f" │\n │ ✅ Synchronization transaction committed to: {UPDATED_INVESTORS}")
        except Exception as e:
            print(f" │ Critical failure saving database matrix to storage path: {e}")
    else:
        print(" │ ℹ️ Storage verification completed. Destination schema is perfectly synchronized.")

    stats["processing_success"] = True
    print("\n" + "="*80)
    print(" ✅ ANALYTICS RUN PROCESSING TASK COMPLETED".ljust(79) + "=")
    print("="*80)
    return stats


#  accounts 

def process_single_invest(inv_folder):
    """
    WORKER FUNCTION: Handles the entire pipeline for ONE investor.
    Dynamically initializes MT5 on whatever instance is globally available
    on the system, completely decoupled from specific process tracking.
    """
    global restricted_timerange_alert
    
    inv_id = inv_folder.name
    print(f"\n[START] ⚙️ Registering and handling Investor ID: {inv_id}")
    
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
        "avg_ranging_cycles": 0,
        "spread_check_skipped": False,
        "spread_warning_details": None,
        "restricted_timerange_purge": False,
        "execution_skipped": False,
        "skip_reason": None,
        "account_type": "UNKNOWN",
        "account_mode": "UNKNOWN",  
        "is_real_account": False 
    }
    
    # 1. Extract structural demo permission policies from investor JSON log
    allow_demo_processing = True 
    try:
        if Path(INVESTOR_USERS).exists():
            with open(INVESTOR_USERS, 'r') as f:
                investor_registry = json.load(f)
            
            user_meta = investor_registry.get(str(inv_id))
            if user_meta:
                demo_rule = user_meta.get("DEMO_ACCOUNT", "1")
                if str(demo_rule).strip().lower() in ["0", "false"]:
                    allow_demo_processing = False
                    print(f"[{inv_id}] Registry Flag Loaded: DEMO_ACCOUNT processing is DISABLED for this user.")
                else:
                    print(f"[{inv_id}] Registry Flag Loaded: DEMO_ACCOUNT processing is ALLOWED for this user.")
    except Exception as json_err:
        print(f"[ERROR] Failed to safely parse investor configuration file: {str(json_err)}")

    broker_cfg = usersdictionary.get(inv_id)
    if not broker_cfg:
        print(f"[ERROR] No broker configuration found for Investor: {inv_id}")
        return account_stats

    # =====================================================================
    # UNRESTRICTED SYSTEM TRACKING SYNCHRONIZATION
    # =====================================================================
    mode_label = "UNKNOWN_BEFORE_INITIALIZATION" 
    fetched_json_path = Path(FETCHED_INVESTORS)
    inv_str_id = str(inv_id)
    
    try:
        investors_data = {}
        if fetched_json_path.exists() and fetched_json_path.stat().st_size > 0:
            with open(fetched_json_path, 'r') as f_inv:
                investors_data = json.load(f_inv)
        
        if inv_str_id not in investors_data:
            investors_data[inv_str_id] = {}
            
        print(f"📝 [{inv_id}] Synchronized system data tracking JSON.")
    except Exception as io_err:
        print(f"[ERROR] Failed to verify tracking record entry: {str(io_err)}")
    
    # Always fire tracking file-movement tasks regardless of connection state
    move_fetched_investors()

    # =====================================================================
    # DYNAMIC MT5 INITIALIZATION & PASSIVE ROUTING LAYER
    # =====================================================================
    delay = random.uniform(0.2, 1.5)
    time.sleep(delay) 
    
    login_id = int(broker_cfg['LOGIN_ID'])
    password_str = broker_cfg["PASSWORD"]
    server_str = broker_cfg["SERVER"]
    
    configured_path = broker_cfg.get("TERMINAL_PATH", "")
    init_successful = False
    
    # Attempt 1: Dynamic Attachment Strategy
    print(f"🔗 Attempting dynamic routing connection to any active global MT5 module...")
    if mt5.initialize(timeout=30000):
        init_successful = True
        print(f"✅ Connected seamlessly to an active background MT5 system engine.")
    
    # Attempt 2: Fallback to direct pathing routing matrix
    if not init_successful and configured_path:
        print(f"⚠️ [WARN] Dynamic routing failed. Falling back to targeted terminal initialization profile...")
        fallback_path = os.path.abspath(configured_path)
        if os.path.exists(fallback_path):
            if mt5.initialize(path=fallback_path, timeout=60000, portable=True):
                init_successful = True
                print(f"🧭 Successfully hooked terminal via explicit path matrix shortcut.")

    if not init_successful:
        print(f"[FAIL] 🛑 System Engine Error: Failed to discover, initialize, or bind to any available MT5 module.")
        print(f"   Terminal Last Reported Internal Error Context: {mt5.last_error()}")
        account_stats["skip_reason"] = "MT5 Dynamic Initialization Engine Failure"
        return account_stats

    # =====================================================================
    # SESSION ACCOUNT RE-AUTHENTICATION GATEWAY
    # =====================================================================
    try:
        acc = mt5.account_info()
        
        if acc is None or acc.login != login_id:
            print(f"🔐 Account focus shift detected. Swapping session terminal context to ID: {login_id}...")
            
            if not mt5.login(login_id, password=password_str, server=server_str):
                print(f"[FAIL] Server rejected routing authentication parameters for ID: {login_id}.")
                print(f"       Rejection details from API: {mt5.last_error()}")
                mt5.shutdown()
                return account_stats
                
            acc = mt5.account_info()
            
        if acc is None:
            print(f"[FAIL] Critical terminal memory fault. Bound data stream context returned empty parameters.")
            mt5.shutdown()
            return account_stats

        # =================================================================
        # ACCOUNT TYPE IDENTIFICATION HIERARCHY
        # =================================================================
        is_real = False
        type_label = "UNKNOWN"
        mode_label = "demo"

        if acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL:
            is_real = True
            type_label = "REAL"
        elif acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO:
            is_real = False
            type_label = "DEMO"
        elif acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_CONTEST:
            is_real = False
            type_label = "CONTEST"
        elif acc.margin_so_mode == mt5.ACCOUNT_STOPOUT_MODE_MONEY:
            is_real = False
            type_label = "DEMO (MONETARY SO FOOTPRINT)"
        else:
            server_upper = acc.server.upper() if acc.server else ""
            if any(indicator in server_upper for indicator in ["DEMO", "STAGE", "TEST", "PRELIVE", "SIMULATION"]):
                is_real = False
                type_label = "DEMO (SERVER STR MATCH)"
            else:
                is_real = True
                type_label = "REAL (FALLBACK)"

        if is_real:
            mode_label = "real"

        account_stats["account_type"] = type_label
        account_stats["account_mode"] = mode_label
        account_stats["is_real_account"] = is_real
        
        print(f"[{inv_id}] Server: '{acc.server}' | Mode Detected: '{mode_label.upper()}' ({type_label})")

        # Synchronize finalized account authentication parameters with database records
        try:
            if fetched_json_path.exists():
                with open(fetched_json_path, 'r') as f_inv:
                    investors_data = json.load(f_inv)
                investors_data[inv_str_id]["account_mode"] = mode_label
                with open(fetched_json_path, 'w') as f_inv:
                    json.dump(investors_data, f_inv, indent=2)
        except Exception as update_err:
            print(f"[WARN] Non-critical error updating tracking JSON: {str(update_err)}")

        # Safety policy gate check
        if not is_real and not allow_demo_processing:
            print(f"[ABORT] Account {inv_id} is a DEMO environment, but JSON permissions forbid execution. Skipping.")
            account_stats["execution_skipped"] = True
            account_stats["skip_reason"] = "Execution Blocked: DEMO_ACCOUNT rule is configured to 0"
            mt5.shutdown()
            return account_stats

        # =====================================================================
        # Execute here
        # =====================================================================
        populate_orders_missing_fields(inv_id=inv_id)
        maximum_risk_distance(inv_id=inv_id)
        
        mt5.shutdown()
        
    except Exception as e:
        print(f"[CRITICAL ERROR] Exception caught for {inv_id}: {str(e)}")
        try:
            mt5.shutdown()
        except:
            pass
    
    return account_stats

def process_single_investor(inv_folder):
    """
    WORKER FUNCTION: Handles the entire pipeline for ONE investor.
    Dynamically initializes MT5 on whatever instance is globally available
    on the system, completely decoupled from specific process tracking.
    """
    global restricted_timerange_alert
    
    inv_id = inv_folder.name
    print(f"\n[START] ⚙️ Registering and handling Investor ID: {inv_id}")
    
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
        "avg_ranging_cycles": 0,
        "spread_check_skipped": False,
        "spread_warning_details": None,
        "restricted_timerange_purge": False,
        "execution_skipped": False,
        "skip_reason": None,
        "account_type": "UNKNOWN",
        "account_mode": "UNKNOWN",  
        "is_real_account": False 
    }
    
    # 1. Extract structural demo permission policies from investor JSON log
    allow_demo_processing = True 
    try:
        if Path(INVESTOR_USERS).exists():
            with open(INVESTOR_USERS, 'r') as f:
                investor_registry = json.load(f)
            
            user_meta = investor_registry.get(str(inv_id))
            if user_meta:
                demo_rule = user_meta.get("DEMO_ACCOUNT", "1")
                if str(demo_rule).strip().lower() in ["0", "false"]:
                    allow_demo_processing = False
                    print(f"[{inv_id}] Registry Flag Loaded: DEMO_ACCOUNT processing is DISABLED for this user.")
                else:
                    print(f"[{inv_id}] Registry Flag Loaded: DEMO_ACCOUNT processing is ALLOWED for this user.")
    except Exception as json_err:
        print(f"[ERROR] Failed to safely parse investor configuration file: {str(json_err)}")

    broker_cfg = usersdictionary.get(inv_id)
    if not broker_cfg:
        print(f"[ERROR] No broker configuration found for Investor: {inv_id}")
        return account_stats

    # =====================================================================
    # UNRESTRICTED SYSTEM TRACKING SYNCHRONIZATION
    # =====================================================================
    mode_label = "UNKNOWN_BEFORE_INITIALIZATION" 
    fetched_json_path = Path(FETCHED_INVESTORS)
    inv_str_id = str(inv_id)
    
    try:
        investors_data = {}
        if fetched_json_path.exists() and fetched_json_path.stat().st_size > 0:
            with open(fetched_json_path, 'r') as f_inv:
                investors_data = json.load(f_inv)
        
        if inv_str_id not in investors_data:
            investors_data[inv_str_id] = {}
            
        print(f"📝 [{inv_id}] Synchronized system data tracking JSON.")
    except Exception as io_err:
        print(f"[ERROR] Failed to verify tracking record entry: {str(io_err)}")
    
    # Always fire tracking file-movement tasks regardless of connection state
    move_fetched_investors()

    # =====================================================================
    # DYNAMIC MT5 INITIALIZATION & PASSIVE ROUTING LAYER
    # =====================================================================
    delay = random.uniform(0.2, 1.5)
    time.sleep(delay) 
    
    login_id = int(broker_cfg['LOGIN_ID'])
    password_str = broker_cfg["PASSWORD"]
    server_str = broker_cfg["SERVER"]
    
    configured_path = broker_cfg.get("TERMINAL_PATH", "")
    init_successful = False
    
    # Attempt 1: Dynamic Attachment Strategy
    print(f"🔗 Attempting dynamic routing connection to any active global MT5 module...")
    if mt5.initialize(timeout=30000):
        init_successful = True
        print(f"✅ Connected seamlessly to an active background MT5 system engine.")
    
    # Attempt 2: Fallback to direct pathing routing matrix
    if not init_successful and configured_path:
        print(f"⚠️ [WARN] Dynamic routing failed. Falling back to targeted terminal initialization profile...")
        fallback_path = os.path.abspath(configured_path)
        if os.path.exists(fallback_path):
            if mt5.initialize(path=fallback_path, timeout=60000, portable=True):
                init_successful = True
                print(f"🧭 Successfully hooked terminal via explicit path matrix shortcut.")

    if not init_successful:
        print(f"[FAIL] 🛑 System Engine Error: Failed to discover, initialize, or bind to any available MT5 module.")
        print(f"   Terminal Last Reported Internal Error Context: {mt5.last_error()}")
        account_stats["skip_reason"] = "MT5 Dynamic Initialization Engine Failure"
        return account_stats

    # =====================================================================
    # SESSION ACCOUNT RE-AUTHENTICATION GATEWAY
    # =====================================================================
    try:
        acc = mt5.account_info()
        
        if acc is None or acc.login != login_id:
            print(f"🔐 Account focus shift detected. Swapping session terminal context to ID: {login_id}...")
            
            if not mt5.login(login_id, password=password_str, server=server_str):
                print(f"[FAIL] Server rejected routing authentication parameters for ID: {login_id}.")
                print(f"       Rejection details from API: {mt5.last_error()}")
                mt5.shutdown()
                return account_stats
                
            acc = mt5.account_info()
            
        if acc is None:
            print(f"[FAIL] Critical terminal memory fault. Bound data stream context returned empty parameters.")
            mt5.shutdown()
            return account_stats

        # =================================================================
        # ACCOUNT TYPE IDENTIFICATION HIERARCHY
        # =================================================================
        is_real = False
        type_label = "UNKNOWN"
        mode_label = "demo"

        if acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL:
            is_real = True
            type_label = "REAL"
        elif acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO:
            is_real = False
            type_label = "DEMO"
        elif acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_CONTEST:
            is_real = False
            type_label = "CONTEST"
        elif acc.margin_so_mode == mt5.ACCOUNT_STOPOUT_MODE_MONEY:
            is_real = False
            type_label = "DEMO (MONETARY SO FOOTPRINT)"
        else:
            server_upper = acc.server.upper() if acc.server else ""
            if any(indicator in server_upper for indicator in ["DEMO", "STAGE", "TEST", "PRELIVE", "SIMULATION"]):
                is_real = False
                type_label = "DEMO (SERVER STR MATCH)"
            else:
                is_real = True
                type_label = "REAL (FALLBACK)"

        if is_real:
            mode_label = "real"

        account_stats["account_type"] = type_label
        account_stats["account_mode"] = mode_label
        account_stats["is_real_account"] = is_real
        
        print(f"[{inv_id}] Server: '{acc.server}' | Mode Detected: '{mode_label.upper()}' ({type_label})")

        # Synchronize finalized account authentication parameters with database records
        try:
            if fetched_json_path.exists():
                with open(fetched_json_path, 'r') as f_inv:
                    investors_data = json.load(f_inv)
                investors_data[inv_str_id]["account_mode"] = mode_label
                with open(fetched_json_path, 'w') as f_inv:
                    json.dump(investors_data, f_inv, indent=2)
        except Exception as update_err:
            print(f"[WARN] Non-critical error updating tracking JSON: {str(update_err)}")

        # Safety policy gate check
        if not is_real and not allow_demo_processing:
            print(f"[ABORT] Account {inv_id} is a DEMO environment, but JSON permissions forbid execution. Skipping.")
            account_stats["execution_skipped"] = True
            account_stats["skip_reason"] = "Execution Blocked: DEMO_ACCOUNT rule is configured to 0"
            mt5.shutdown()
            return account_stats

        # =====================================================================
        # MASTER CONDITIONAL ROUTING (TIME RANGE FILTER)
        # =====================================================================
        print(f"🔍 [{inv_id}] Evaluating system run constraints...")
        
        timerange_result = restricted_timerange(inv_id=inv_id)
        
        # Determine strict truthiness for restriction tracking
        # If the result points to a true block, or a dictionary indicating true, it's restricted.
        is_restricted = False
        if isinstance(timerange_result, dict):
            is_restricted = timerange_result.get('is_restricted', False)
        elif str(timerange_result).strip().lower() in ["true", "1"]:
            is_restricted = True
            
        # =====================================================================
        # CONDITION A: OUTSIDE RESTRICTED TIME RANGE -> EXECUTE ALL ENGINES
        # =====================================================================
        if not is_restricted:
            print(f"🛡️ [{inv_id}] Validation Clear. Explicitly OUTSIDE restricted window -> Running core trade logic...")
            
            # Run security safety tracking
            check_and_record_unauthorized_actions(inv_id=inv_id)
            delete_unauthorized_symbol_files(inv_id=inv_id)

            # Core processing sequence execution
            additional_candles_for_orders_limitation(inv_id=inv_id)
            fetch_ohlc_data_for_investor(inv_id=inv_id)
            directional_bias(inv_id=inv_id)
            additional_candles_for_orders_limitation(inv_id=inv_id)
            create_position_hedge(inv_id=inv_id)
            deduplicate_orders(inv_id=inv_id)
            filter_unauthorized_symbols(inv_id=inv_id)
            filter_unauthorized_timeframes(inv_id=inv_id)
            backup_limit_orders(inv_id=inv_id)
            populate_orders_missing_fields(inv_id=inv_id)
            activate_usd_based_risk_on_empty_pricelevels(inv_id=inv_id)
            enforce_investor_symbols_specific_risks(inv_id=inv_id)
            calculate_investor_symbols_orders(inv_id=inv_id)
            padding_stoploss_below_minimum_risk_to_minimum_risk(inv_id=inv_id)   
            maximum_risk_distance(inv_id=inv_id) 
            live_usd_risk_and_scaling(inv_id=inv_id)
            apply_default_prices(inv_id=inv_id)
            martingale(inv_id=inv_id)
            clean_trades_history(inv_id=inv_id)
            place_usd_orders(inv_id=inv_id)
            close_unauthorized_orders(inv_id=inv_id)
            orders_reward_correction(inv_id=inv_id)
            check_pending_orders_risk(inv_id=inv_id)
            history_closed_orders_removal_in_pendingorders(inv_id=inv_id)
            apply_dynamic_breakeven(inv_id=inv_id)
            check_and_record_unauthorized_actions(inv_id=inv_id)
            trades_analytics(inv_id=inv_id)

            account_stats["success"] = True
            print(f"[SUCCESS] Finished full pipeline execution context for Investor: {inv_id} ({mode_label})")

        # =====================================================================
        # CONDITION B: INSIDE RESTRICTED TIME RANGE -> SKIP ENGINE
        # =====================================================================
        else:
            print(f"🚨 [ALERT] Account {inv_id} is operating within an active restricted time range block.")
            print(f"⏭️ in restricted timerange")
            
            delete_all_orders_and_positions(inv_id=inv_id)
        
        mt5.shutdown()
        
    except Exception as e:
        print(f"[CRITICAL ERROR] Exception caught for {inv_id}: {str(e)}")
        try:
            mt5.shutdown()
        except:
            pass
    
    return account_stats

def place_orders_parallel():
    """
    ORCHESTRATOR (Dynamic One-Shot): Spawns a process pool sized dynamically
    by inspecting live CPU and RAM specs. Deducts resources already consumed 
    by active MT5 terminals running across other system setups.
    """
    inv_base_path = Path(INV_PATH)
    investor_folders = [f for f in inv_base_path.iterdir() if f.is_dir()]
    
    if not investor_folders:
        print(" └─ 🔘 No investor directories found. Calling move_fetched_investors() and retrying...")
        try:
            move_fetched_investors()
        except Exception as err:
            print(f"[ERROR] Failed to run move_fetched_investors: {err}")
            
        return place_orders_parallel()

    # --- SENSE RAW HARDWARE SPECS ---
    cpu_cores = os.cpu_count() or 1
    available_ram_bytes = psutil.virtual_memory().available
    available_ram_mb = available_ram_bytes / (1024 * 1024)

    max_by_cpu = cpu_cores * 4  
    max_by_ram = int(available_ram_mb // 300)  
    hardware_max_limit = max(1, min(max_by_cpu, max_by_ram))

    print(f"🖥️  Hardware Profile Sensed -> Cores: {cpu_cores} (Cap: {max_by_cpu}) | Free RAM: {available_ram_mb:.1f}MB (Cap: {max_by_ram})")

    # --- CROSS-WINDOW SYSTEM DEDUCTION ---
    active_mt5_count = 0
    for proc in psutil.process_iter(['name']):
        try:
            pname = proc.info['name'].lower() if proc.info['name'] else ""
            if "terminal.exe" in pname or "terminal64.exe" in pname:
                active_mt5_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    remaining_slots_left = max(0, hardware_max_limit - active_mt5_count)
    
    print(f"📊 Global System Load -> Active MT5 instances in other windows: {active_mt5_count}")
    print(f"🔒 Adjusted Safe Limit for THIS Window: {remaining_slots_left} available slots remaining.")

    if remaining_slots_left == 0:
        print("⚠️  SYSTEM AT MAXIMUM SAFE CAPACITY: No resource slots left. Deferring execution to protect VPS.")
        return

    # --- BATCH LOAD BALANCING ---
    total_detected = len(investor_folders)
    if total_detected > remaining_slots_left:
        print(f" ⚠️  OVERLOAD PREVENTED: {total_detected} folders detected exceeds adjusted limit of {remaining_slots_left}.")
        active_batch = investor_folders[:remaining_slots_left]
        print(f" ⏳ Sliced batch: Processing first {remaining_slots_left} accounts. Deferring remaining {total_detected - remaining_slots_left} folders.")
    else:
        active_batch = investor_folders

    if not active_batch:
        return

    print(f" 📋 Processing batch of {len(active_batch)} investors across {len(active_batch)} execution channels.")
    
    # --- EXECUTE ACROSS DYNAMIC POOL ---
    try:
        with mp.Pool(processes=len(active_batch)) as pool:
            results = pool.map(process_single_investor, active_batch)
    except Exception as pool_err:
        print(f"[CRITICAL] Error executing multiprocessing pool: {pool_err}")

    return

def place_orders_parallel_loop():
    """
    ORCHESTRATOR (Persistent Loop): Senses hardware capabilities at launch to lock 
    in a safe maximum process pool, then dynamically monitors global background terminal 
    footprints on EVERY loop cycle to safely adapt execution queues.
    """
    try:
        move_fetched_investors()
    except:
        pass
        
    inv_base_path = Path(INV_PATH)
    print(f"🚀 Initializing Self-Sensing Persistent Trading Engine Pool...")

    initial_folders = [f for f in inv_base_path.iterdir() if f.is_dir()]
    
    if not initial_folders:
        print(" └─ 🔘 No initial investor directories found. Calling fallback and retrying...")
        time.sleep(5)
        return place_orders_parallel_loop() 

    # --- SENSE HARDWARE SPECS DYNAMICALLY AT BOOT ---
    cpu_cores = os.cpu_count() or 1
    available_ram_mb = psutil.virtual_memory().available / (1024 * 1024)

    max_by_cpu = cpu_cores * 4
    max_by_ram = int(available_ram_mb // 300)
    hardware_max_limit = max(1, min(max_by_cpu, max_by_ram))

    num_workers = min(len(initial_folders), hardware_max_limit)
    
    print(f"🖥️  Hardware Profile Sensed -> Cores: {cpu_cores} | Free RAM: {available_ram_mb:.1f}MB")
    print(f" 🔧 Hardware Gate: Locking maximum worker pool at {num_workers} processes (Max Engine Capacity: {hardware_max_limit}).")

    pool = mp.Pool(processes=num_workers)

    while True:
        try:
            all_investor_folders = [f for f in inv_base_path.iterdir() if f.is_dir()]
            
            if not all_investor_folders:
                print(" └─ 🔘 No investor directories found during loop. Executing move_fetched_investors() & retrying...")
                try:
                    move_fetched_investors()
                except Exception as inner_err:
                    print(f" [ERROR] Fallback shift error: {inner_err}")
                continue

            # --- LIVE GLOBAL RESOURCE AUDIT ON EVERY LOOP CYCLE ---
            active_mt5_count = 0
            
            for proc in psutil.process_iter(['name', 'ppid']):
                try:
                    pname = proc.info['name'].lower() if proc.info['name'] else ""
                    if "terminal.exe" in pname or "terminal64.exe" in pname:
                        # Stripped child process checking to rely purely on active platform presence
                        active_mt5_count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass

            adjusted_capacity = max(0, hardware_max_limit - active_mt5_count)
            current_safe_cap = min(num_workers, adjusted_capacity)

            # Dynamic Load Balancing Slice
            if current_safe_cap <= 0:
                print(f"⏳ [STANDBY] System capacity fully utilized by other windows ({active_mt5_count} active terminals). Waiting for free space...")
                time.sleep(3)
                continue

            if len(all_investor_folders) > current_safe_cap:
                print(f" ⚠️  RESOURCE CEILING APPLIED: {len(all_investor_folders)} investors active. Capping this cycle's slice to {current_safe_cap}.")
                active_batch = all_investor_folders[:current_safe_cap]
                deferred_count = len(all_investor_folders) - current_safe_cap
                print(f" ⏳ Slicing batch: Running first {current_safe_cap} accounts. {deferred_count} deferred to next loop.")
            else:
                active_batch = all_investor_folders

            print(f"\n--- Cycle Start: Processing {len(active_batch)} investors within safe limits ---")
            
            jobs = []
            for folder in active_batch:
                job = pool.apply_async(process_single_investor, args=(folder,))
                jobs.append(job)
            
            results = [job.get() for job in jobs]
            print(f"--- Cycle Complete. Safe execution maintained. Sleeping for 1 second ---")
            
        except Exception as e:
            print(f"Critical Error in Orchestrator Loop: {e}")
            time.sleep(5)
            
        time.sleep(1)

if __name__ == "__main__":
   move_fetched_investors()


