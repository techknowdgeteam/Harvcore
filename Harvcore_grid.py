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
import pytz
from pathlib import Path
import math
import multiprocessing as mp
import time
import sys

INVESTOR_USERS = r"C:\xampp\htdocs\harvcore\harvox\usersdata\investors\investors.json"
INV_PATH = r"C:\xampp\htdocs\harvcore\harvox\usersdata\investors"
NORMALIZE_SYMBOLS_PATH = r"C:\xampp\htdocs\harvcore\harvox\symbols_normalization.json"
DEFAULT_ACCOUNTMANAGEMENT = r"C:\xampp\htdocs\harvcore\harvox\default_accountmanagement.json"
VERIFIED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\verified_investors.json"
UPDATED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\updated_investors.json"
ISSUES_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\issues_investors.json"

def load_investors_dictionary():
    BROKERS_JSON_PATH = r"C:\xampp\htdocs\harvcore\harvox\usersdata\investors\investors.json"
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

#--VERIFICATIONS AND AUTHORIZATIONS--
def move_verified_investors():
    """
    Moves verified investors from verified_investors.json to:
    Step 1: investors.json (with limited fields: LOGIN_ID, PASSWORD, SERVER, INVESTED_WITH, TERMINAL_PATH)
    Step 2: Create activities.json directly in investor root folder (NEW PATH STRUCTURE)
    Step 3: Create empty tradeshistory.json if it doesn't exist
    
    Verified investors must have:
    - INVESTED_WITH (not empty)
    - execution_start_date (not empty)
    - contract_days_left (not empty)
    - TERMINAL_PATH (not empty) - MANDATORY FIELD
    
    Strategy name is extracted by splitting INVESTED_WITH on first underscore
    e.g., "deriv6_double-levels" → strategy = "double-levels"
    
    SUPPORTS MULTI-STRATEGY: INVESTED_WITH can contain comma-separated values
    e.g., "deriv6_strat1, deriv6_strat2, deriv6_strat3"
    
    For Step 2, activities.json is created directly in INV_PATH/{inv_id}/activities.json
    This simplifies the structure and removes the need for strategy subfolders.
    
    For Step 3, tradeshistory.json is created as an empty array if it doesn't exist.
    
    NOTE: Investors are NOT removed from verified_investors.json after processing
    """
    
    print(f"\n{'='*70}")
    print(f"📦 MOVE VERIFIED INVESTORS TO INVESTOR USERS".center(70))
    print(f"{'='*70}")
    
    # Default activities template for NEW PATH structure
    DEFAULT_ACTIVITIES = {
        "activate_autotrading": True,
        "bypass_restriction": True,
        "execution_start_date": "",
        "contract_duration": 30,
        "contract_expiry_date": "",
        "unauthorized_trades": {},
        "unauthorized_withdrawals": {},
        "unauthorized_action_detected": False,
        "strategies": []  # Store all strategies in a list for the new structure
    }
    
    # Check if verified investors file exists
    if not os.path.exists(VERIFIED_INVESTORS):
        print(f" Verified investors file not found: {VERIFIED_INVESTORS}")
        return False
    
    try:
        with open(VERIFIED_INVESTORS, 'r', encoding='utf-8') as f:
            verified_data = json.load(f)
    except Exception as e:
        print(f" Error loading verified investors: {e}")
        return False
    
    if not isinstance(verified_data, dict):
        print(f" Invalid format: expected dictionary")
        return False
    
    print(f"\n📋 Found {len(verified_data)} investors in verified list")
    
    # ============================================
    # STEP 1: Move to investors.json with limited fields
    # ============================================
    print(f"\n{'─'*70}")
    print(f"🔹 STEP 1: ADDING TO INVESTORS.JSON")
    print(f"{'─'*70}")
    
    # Load existing investors.json if it exists
    investors_data = {}
    if os.path.exists(INVESTOR_USERS):
        try:
            with open(INVESTOR_USERS, 'r', encoding='utf-8') as f:
                investors_data = json.load(f)
            print(f"📄 Loaded existing investors.json with {len(investors_data)} investors")
        except Exception as e:
            print(f"⚠️ Error loading existing investors.json: {e}")
            investors_data = {}
    
    investors_updated = []
    investors_skipped = []
    
    for inv_id, investor_data in verified_data.items():
        # Case-insensitive lookup
        investor_data_upper = {k.upper(): v for k, v in investor_data.items()}
        
        # Check required fields
        invested_with = investor_data_upper.get('INVESTED_WITH', '').strip()
        execution_start = investor_data_upper.get('EXECUTION_START_DATE', '').strip()
        contract_days = investor_data_upper.get('CONTRACT_DAYS_LEFT', '').strip()
        terminal_path = investor_data_upper.get('TERMINAL_PATH', '').strip()
        login_id = investor_data_upper.get('LOGIN_ID') or investor_data_upper.get('LOGIN', '')
        password = investor_data_upper.get('PASSWORD', '').strip()
        server = investor_data_upper.get('SERVER', '').strip()
        
        missing_fields = []
        if not invested_with: missing_fields.append('INVESTED_WITH')
        if not execution_start: missing_fields.append('execution_start_date')
        if not contract_days: missing_fields.append('contract_days_left')
        if not terminal_path: missing_fields.append('TERMINAL_PATH')
        if not login_id: missing_fields.append('LOGIN_ID')
        if not password: missing_fields.append('PASSWORD')
        if not server: missing_fields.append('SERVER')
        
        if missing_fields:
            investors_skipped.append(f"{inv_id} (missing: {', '.join(missing_fields)})")
            continue
        
        # Create minimal investor record
        minimal_investor = {
            "LOGIN_ID": str(login_id).strip(),
            "PASSWORD": password,
            "SERVER": server,
            "INVESTED_WITH": invested_with,
            "TERMINAL_PATH": terminal_path
        }
        
        investors_data[inv_id] = minimal_investor
        investors_updated.append(inv_id)
    
    # Save updated investors.json
    if investors_updated:
        os.makedirs(os.path.dirname(INVESTOR_USERS), exist_ok=True)
        with open(INVESTOR_USERS, 'w', encoding='utf-8') as f:
            json.dump(investors_data, f, indent=4)
        
        print(f"\n  ✅ Added/Updated: {len(investors_updated)} investors")
        if investors_updated:
            print(f"     {', '.join(investors_updated[:5])}{'...' if len(investors_updated) > 5 else ''}")
        if investors_skipped:
            print(f"  ⏭️  Skipped: {len(investors_skipped)} investors")
    
    # ============================================
    # STEP 2: Create activities.json in INVESTOR ROOT (NEW PATH)
    # ============================================
    print(f"\n{'─'*70}")
    print(f"🔹 STEP 2: CREATING ACTIVITIES.JSON IN INVESTOR ROOT (NEW PATH)")
    print(f"{'─'*70}")
    
    # ============================================
    # STEP 3: Create empty tradeshistory.json if it doesn't exist
    # ============================================
    print(f"\n{'─'*70}")
    print(f"🔹 STEP 3: CREATING EMPTY TRADESHISTORY.JSON IF NEEDED")
    print(f"{'─'*70}")
    
    processed_summary = []
    skipped_summary = []
    created_activities_summary = []
    updated_activities_summary = []
    created_tradeshistory_summary = []
    expiry_calculation_errors = []  # Track expiry calculation errors
    
    for inv_id, investor_data in verified_data.items():
        print(f"\n{'─'*50}")
        print(f"📁 Processing investor: {inv_id}")
        print(f"{'─'*50}")
        
        # Case-insensitive lookup
        investor_data_upper = {k.upper(): v for k, v in investor_data.items()}
        
        invested_with = investor_data_upper.get('INVESTED_WITH', '').strip()
        execution_start = investor_data_upper.get('EXECUTION_START_DATE', '').strip()
        contract_days_raw = investor_data_upper.get('CONTRACT_DAYS_LEFT', '').strip()
        terminal_path = investor_data_upper.get('TERMINAL_PATH', '').strip()
        
        # Debug: Show raw values
        print(f"  📋 Raw data:")
        print(f"     INVESTED_WITH: '{invested_with}'")
        print(f"     EXECUTION_START_DATE: '{execution_start}'")
        print(f"     CONTRACT_DAYS_LEFT: '{contract_days_raw}'")
        print(f"     TERMINAL_PATH: '{terminal_path}'")
        
        # Skip if missing required fields
        if not all([invested_with, execution_start, terminal_path]):
            skipped_summary.append(inv_id)
            print(f"  ⏭️  Skipped: missing required fields (invested_with, execution_start, or terminal_path)")
            continue
        
        # Handle contract_days - check for NULL, empty, or invalid values
        contract_days = None
        contract_duration_val = 30  # Default value
        contract_days_valid = False
        
        if contract_days_raw and contract_days_raw.upper() not in ['NULL', 'NONE', '']:
            try:
                contract_days = int(contract_days_raw)
                contract_duration_val = contract_days
                contract_days_valid = True
                print(f"  ✓ Contract days valid: {contract_days}")
            except ValueError:
                print(f"  ⚠️ Invalid contract_days value: '{contract_days_raw}' - using default: 30")
        else:
            print(f"  ⚠️ contract_days is NULL or empty - using default: 30")
        
        # Split INVESTED_WITH by comma to handle multiple strategies
        strategies = [s.strip() for s in invested_with.split(",") if s.strip()]
        
        # Extract strategy names (without the prefix)
        strategy_names = []
        for strat_full in strategies:
            try:
                underscore_index = strat_full.find('_')
                if underscore_index != -1:
                    strategy_name = strat_full[underscore_index + 1:]
                    strategy_names.append(strategy_name)
                else:
                    strategy_names.append(strat_full)  # Use full name if no underscore
            except:
                strategy_names.append(strat_full)
        
        print(f"  🎯 Strategies: {strategy_names}")
        
        # Format execution start date
        formatted_start_date = execution_start
        date_parse_success = False
        
        try:
            date_obj = datetime.strptime(execution_start, "%Y-%m-%d")
            formatted_start_date = date_obj.strftime("%B %d, %Y")
            date_parse_success = True
            print(f"  📅 Parsed as YYYY-MM-DD: {execution_start} → {formatted_start_date}")
        except:
            try:
                date_obj = datetime.strptime(execution_start, "%B %d, %Y")
                formatted_start_date = execution_start
                date_parse_success = True
                print(f"  📅 Already in Month DD, YYYY format: {execution_start}")
            except Exception as e:
                print(f"  ⚠️ Could not parse date: {execution_start} - {e}")
        
        # Calculate expiry date
        expiry_date_str = ""
        
        if date_parse_success and contract_days_valid:
            print(f"  🔢 Calculating expiry date with {contract_duration_val} days...")
            
            try:
                # Parse start date
                start_date = None
                try:
                    # Try parsing as YYYY-MM-DD first
                    start_date = datetime.strptime(execution_start, "%Y-%m-%d")
                    print(f"     ✓ Start date (YYYY-MM-DD): {start_date}")
                except ValueError:
                    try:
                        # Try parsing as Month DD, YYYY
                        start_date = datetime.strptime(formatted_start_date, "%B %d, %Y")
                        print(f"     ✓ Start date (Month DD, YYYY): {start_date}")
                    except ValueError as e:
                        print(f"     No Failed to parse start date: {e}")
                        start_date = None
                
                if start_date:
                    # Calculate expiry date
                    expiry_date = start_date + timedelta(days=contract_duration_val)
                    expiry_date_str = expiry_date.strftime("%B %d, %Y")
                    print(f"     ✓ Expiry date calculated: {expiry_date_str}")
                    
            except Exception as e:
                error_msg = f"Expiry calculation error for {inv_id}: {e}"
                print(f"  No {error_msg}")
                expiry_calculation_errors.append(error_msg)
        else:
            if not date_parse_success:
                print(f"  ⚠️ Skipping expiry calculation: date parse failed")
            if not contract_days_valid:
                print(f"  ⚠️ Skipping expiry calculation: using default duration without expiry date")
        
        # Create investor root folder if it doesn't exist
        inv_root = Path(INV_PATH) / inv_id
        try:
            inv_root.mkdir(parents=True, exist_ok=True)
            print(f"  📁 Investor folder: {inv_root}")
        except Exception as e:
            print(f"  No Could not create investor folder: {e}")
            continue
        
        # ============================================
        # STEP 2: Create/Update activities.json
        # ============================================
        activities_path = inv_root / "activities.json"
        
        # Load existing activities.json if it exists
        existing_activities = {}
        is_new_activities = False
        if activities_path.exists():
            try:
                with open(activities_path, 'r', encoding='utf-8') as f:
                    existing_activities = json.load(f)
                print(f"  📄 Existing activities.json found")
            except Exception as e:
                print(f"  ⚠️ Could not load existing activities.json: {e}")
                existing_activities = {}
                is_new_activities = True
        else:
            is_new_activities = True
            print(f"  ✨ Creating new activities.json")
        
        # Prepare activities data (merge with existing)
        activities_data = DEFAULT_ACTIVITIES.copy()
        activities_data.update(existing_activities)
        
        # Update with new values
        changed = False
        
        # Update strategies list
        if activities_data.get("strategies") != strategy_names:
            activities_data["strategies"] = strategy_names
            changed = True
            print(f"  📋 Updated strategies: {', '.join(strategy_names)}")
        
        # Update execution_start_date
        if activities_data.get("execution_start_date") != formatted_start_date:
            old_value = activities_data.get("execution_start_date")
            activities_data["execution_start_date"] = formatted_start_date
            changed = True
            print(f"  📅 Updated execution_start_date: '{old_value}' → '{formatted_start_date}'")
        
        # Update contract_duration (always update if we have a valid value)
        if contract_days_valid and activities_data.get("contract_duration") != contract_duration_val:
            old_value = activities_data.get("contract_duration")
            activities_data["contract_duration"] = contract_duration_val
            changed = True
            print(f"  ⏱️  Updated contract_duration: {old_value} → {contract_duration_val}")
        elif not contract_days_valid and contract_duration_val == 30:
            # Ensure default is set if not present
            if activities_data.get("contract_duration") is None:
                activities_data["contract_duration"] = 30
                changed = True
                print(f"  ⏱️  Set default contract_duration: 30")
        
        # Update contract_expiry_date
        if expiry_date_str and activities_data.get("contract_expiry_date") != expiry_date_str:
            old_value = activities_data.get("contract_expiry_date")
            activities_data["contract_expiry_date"] = expiry_date_str
            changed = True
            print(f"  📆 Updated contract_expiry_date: '{old_value}' → '{expiry_date_str}'")
        elif not expiry_date_str and activities_data.get("contract_expiry_date"):
            # Optionally clear expiry date if it was previously set but now invalid
            # Uncomment if you want to clear it
            # activities_data["contract_expiry_date"] = ""
            # changed = True
            print(f"  ℹ️  No expiry date to set (calculation failed or skipped)")
        
        # Update terminal_path if provided
        if terminal_path and activities_data.get("terminal_path") != terminal_path:
            activities_data["terminal_path"] = terminal_path
            changed = True
            print(f"  💾 Updated terminal_path")
        
        # Ensure default values for other fields
        for field, default_value in DEFAULT_ACTIVITIES.items():
            if field not in activities_data or activities_data[field] is None:
                activities_data[field] = default_value
                changed = True
        
        # Save activities.json
        try:
            with open(activities_path, 'w', encoding='utf-8') as f:
                json.dump(activities_data, f, indent=4)
            
            if is_new_activities:
                created_activities_summary.append(inv_id)
                print(f"  ✅ Created new activities.json")
            elif changed:
                updated_activities_summary.append(inv_id)
                print(f"  ✅ Updated existing activities.json")
            else:
                print(f"  ℹ️  No changes needed")
            
        except Exception as e:
            print(f"  No Failed to save activities.json: {e}")
            continue
        
        # ============================================
        # STEP 3: Create empty tradeshistory.json if it doesn't exist
        # ============================================
        tradeshistory_path = inv_root / "tradeshistory.json"
        
        if not tradeshistory_path.exists():
            try:
                # Create empty trades history array
                with open(tradeshistory_path, 'w', encoding='utf-8') as f:
                    json.dump([], f, indent=4)
                created_tradeshistory_summary.append(inv_id)
                print(f"  ✅ Created empty tradeshistory.json")
            except Exception as e:
                print(f"  No Failed to create tradeshistory.json: {e}")
        else:
            print(f"  ℹ️  tradeshistory.json already exists - skipping creation")
        
        processed_summary.append(inv_id)
    
    # ============================================
    # SUMMARY
    # ============================================
    print(f"\n{'─'*70}")
    print(f"📊 SUMMARY")
    print(f"{'─'*70}")
    
    print(f"\n🔹 STEP 1 - INVESTORS.JSON:")
    print(f"   ✅ Added/Updated: {len(investors_updated)}")
    if investors_updated:
        print(f"      {', '.join(investors_updated[:3])}{'...' if len(investors_updated) > 3 else ''}")
    if investors_skipped:
        print(f"   ⏭️  Skipped: {len(investors_skipped)}")
        for skip in investors_skipped[:2]:
            print(f"      • {skip}")
    
    print(f"\n🔹 STEP 2 - ACTIVITIES.JSON:")
    print(f"   ✅ Created: {len(created_activities_summary)} new activities.json files")
    if created_activities_summary:
        for inv in created_activities_summary[:5]:
            print(f"      • {inv}")
        if len(created_activities_summary) > 5:
            print(f"      ... and {len(created_activities_summary)-5} more")
    
    print(f"   🔄 Updated: {len(updated_activities_summary)} existing activities.json files")
    if updated_activities_summary:
        for inv in updated_activities_summary[:3]:
            print(f"      • {inv}")
        if len(updated_activities_summary) > 3:
            print(f"      ... and {len(updated_activities_summary)-3} more")
    
    print(f"\n🔹 STEP 3 - TRADESHISTORY.JSON:")
    print(f"   ✅ Created: {len(created_tradeshistory_summary)} new tradeshistory.json files")
    if created_tradeshistory_summary:
        for inv in created_tradeshistory_summary[:5]:
            print(f"      • {inv}")
        if len(created_tradeshistory_summary) > 5:
            print(f"      ... and {len(created_tradeshistory_summary)-5} more")
    
    if skipped_summary:
        print(f"\n   ⏭️  Skipped (missing fields): {len(skipped_summary)}")
        for inv in skipped_summary[:3]:
            print(f"      • {inv}")
    
    if expiry_calculation_errors:
        print(f"\n🔹 EXPIRY CALCULATION ERRORS:")
        print(f"   No {len(expiry_calculation_errors)} errors occurred:")
        for error in expiry_calculation_errors:
            print(f"      • {error}")
    
    print(f"\n🔹 VERIFIED LIST:")
    print(f"   📁 All {len(verified_data)} investors remain in verified_investors.json")
    
    print(f"\n{'='*70}")
    print(f"✅ MOVE COMPLETE".center(70))
    print(f"{'='*70}")
    
    return True

def update_verified_investors_file():
    """
    Updates verified_investors.json by:
    1. Removing the MESSAGE field after moving them to activities.json
    2. Verifying that investors have the required files at INV_PATH/{investor_id}/
    3. Moving investors to issues if they're missing critical files
    4. Removing investors from verified_investors.json if they have any issues
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
        print(f" Error reading verified_investors.json: {e}")
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
    investors_moved_to_issues = []
    
    for inv_id, investor_data in verified_investors.items():
        print(f"\n📋 Checking investor: {inv_id}")
        print("-" * 40)
        
        # Check if investor folder exists at new path
        inv_folder = Path(INV_PATH) / inv_id
        
        if not inv_folder.exists():
            print(f"   No Investor folder not found at: {inv_folder}")
            investors_to_remove.append(inv_id)
            
            # Add to issues_investors with reason
            if inv_id not in issues_investors:
                investor_data_copy = investor_data.copy()
                investor_data_copy['MESSAGE'] = f"Investor folder missing at {inv_folder}"
                investor_data_copy['verified_status'] = 'folder_missing'
                issues_investors[inv_id] = investor_data_copy
                investors_moved_to_issues.append(inv_id)
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
            print(f"  No Missing required files: {', '.join(missing_files)}")
            
            # Always add to issues and remove from verified if files are missing
            investor_data_copy = investor_data.copy()
            investor_data_copy['MESSAGE'] = f"Missing required files: {', '.join(missing_files)}"
            investor_data_copy['verified_status'] = 'missing_files'
            issues_investors[inv_id] = investor_data_copy
            investors_moved_to_issues.append(inv_id)
            investors_to_remove.append(inv_id)
            print(f"  ⚠️  Added to issues_investors.json (missing files)")
            continue
        
        print(f"  ✅ All required files present: {', '.join(required_files)}")
        
        # Check if activities.json has required data
        activities_path = inv_folder / "activities.json"
        try:
            with open(activities_path, 'r', encoding='utf-8') as f:
                activities = json.load(f)
            
            # Validate critical fields
            execution_start_date = activities.get('execution_start_date')
            if not execution_start_date:
                print(f"  No Missing execution_start_date in activities.json")
                
                # Always add to issues and remove from verified if execution_start_date is missing
                investor_data_copy = investor_data.copy()
                investor_data_copy['MESSAGE'] = "Missing execution_start_date in activities.json"
                investor_data_copy['verified_status'] = 'missing_start_date'
                issues_investors[inv_id] = investor_data_copy
                investors_moved_to_issues.append(inv_id)
                investors_to_remove.append(inv_id)
                print(f"  ⚠️  Added to issues_investors.json (missing start date)")
                continue
            
            # Check if tradeshistory.json exists (empty is acceptable)
            tradeshistory_path = inv_folder / "tradeshistory.json"
            if tradeshistory_path.exists():
                try:
                    with open(tradeshistory_path, 'r', encoding='utf-8') as f:
                        tradeshistory = json.load(f)
                    
                    if tradeshistory:
                        print(f"  ✅ Found {len(tradeshistory)} authorized trades in tradeshistory.json")
                    else:
                        print(f"  ℹ️  tradeshistory.json exists but is empty (acceptable)")
                except Exception as e:
                    print(f"  ⚠️  Error reading tradeshistory.json: {e}")
                    # Note: If tradeshistory.json is corrupted, that's an issue
                    investor_data_copy = investor_data.copy()
                    investor_data_copy['MESSAGE'] = f"Error reading tradeshistory.json: {str(e)}"
                    investor_data_copy['verified_status'] = 'tradeshistory_read_error'
                    issues_investors[inv_id] = investor_data_copy
                    investors_moved_to_issues.append(inv_id)
                    investors_to_remove.append(inv_id)
                    continue
            else:
                print(f"  No tradeshistory.json missing")
                # Missing tradeshistory.json is an issue
                investor_data_copy = investor_data.copy()
                investor_data_copy['MESSAGE'] = "tradeshistory.json missing"
                investor_data_copy['verified_status'] = 'missing_tradeshistory'
                issues_investors[inv_id] = investor_data_copy
                investors_moved_to_issues.append(inv_id)
                investors_to_remove.append(inv_id)
                continue
            
            # Remove MESSAGE field if it exists
            if 'MESSAGE' in investor_data:
                print(f"  🧹 Removing MESSAGE field for investor {inv_id}")
                del investor_data['MESSAGE']
                updated = True
            
            # Add verification status
            investor_data['verified_status'] = 'verified'
            
        except Exception as e:
            print(f"  No Error reading activities.json: {e}")
            # Always add to issues and remove from verified on read error
            investor_data_copy = investor_data.copy()
            investor_data_copy['MESSAGE'] = f"Error reading activities.json: {str(e)}"
            investor_data_copy['verified_status'] = 'read_error'
            issues_investors[inv_id] = investor_data_copy
            investors_moved_to_issues.append(inv_id)
            investors_to_remove.append(inv_id)
            continue
    
    # Remove investors from verified_investors that were moved to issues
    if investors_to_remove:
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
            print(f"✅ Updated verified_investors.json")
            if investors_to_remove:
                print(f"   - Removed {len(investors_to_remove)} investors with issues:")
                for inv_id in investors_to_remove:
                    print(f"     • {inv_id}")
        else:
            print(f"ℹ️  No changes made to verified_investors.json")
        
        if issues_investors:
            print(f"⚠️  Issues investors file updated with {len(issues_investors)} investors")
            if investors_moved_to_issues:
                print(f"   - Newly added investors with issues:")
                for inv_id in investors_moved_to_issues:
                    print(f"     • {inv_id}")
        print("="*80)
        
    except Exception as e:
        print(f" Error saving files: {e}")
        return False
    
    return True

def get_requirements(inv_id):
    """
    Mirroring the logic of update_investor_info to find the date 
    directly in root files (new path structure). Also checks if investor balance
    meets minimum requirement from requirements.json and moves
    them to issues_investors.json with a message if not.
    
    Core Functions:
    1. Read execution_start_date from activities.json in root folder
    2. Connect to MT5 and calculate starting balance by:
       a. Finding first deposit after execution start date
       b. Searching for existing balance between execution start date and first deposit
       c. If existing balance found, use it; otherwise use first deposit
       d. If existing balance < minimum requirement, add first deposit to check again
    3. Check minimum balance requirement from investor root folder
    4. Move non-compliant investors to issues_investors.json with error messages
    5. Update activities.json with broker_balance field (starting balance or first deposit)
    """
    execution_start_date = None
    inv_root = Path(INV_PATH) / inv_id
    
    if not inv_root.exists():
        print(f"No Path not found: {inv_root}")
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
        print(f"No Date not found for {inv_id} in activities.json or accountmanagement.json")
        return None

    # 3. MT5 Calculation with enhanced balance logic
    start_datetime = None
    for fmt in ["%B %d, %Y", "%Y-%m-%d"]:
        try:
            start_datetime = datetime.strptime(execution_start_date, fmt).replace(hour=0, minute=0, second=0)
            break
        except: continue

    if start_datetime:
        print(f"  🔍 Fetching deals from: {start_datetime.strftime('%Y-%m-%d')}")
        all_deals = mt5.history_deals_get(start_datetime, datetime.now())
        account_info = mt5.account_info()
        
        if account_info:
            # Find the FIRST DEPOSIT after execution start date
            first_deposit_amount = None
            first_deposit_time = None
            all_deposits = []
            
            # Collect all deposits (type = 2 for deposit in MT5)
            for deal in all_deals:
                if deal.type == 2:  # 2 = DEPOSIT in MT5
                    all_deposits.append({
                        'amount': deal.profit,
                        'time': deal.time,
                        'datetime': datetime.fromtimestamp(deal.time)
                    })
            
            # Find the first deposit (earliest timestamp)
            if all_deposits:
                all_deposits.sort(key=lambda x: x['time'])
                first_deposit = all_deposits[0]
                first_deposit_amount = first_deposit['amount']
                first_deposit_time = first_deposit['datetime'].strftime('%Y-%m-%d %H:%M:%S')
                print(f"  💰 Found first deposit: ${first_deposit_amount:.2f} at {first_deposit_time}")
                print(f"  ℹ️  Total deposits found: {len(all_deposits)}")
            
            # ENHANCED LOGIC: Search for existing balance between execution start date and first deposit
            existing_balance = None
            if first_deposit_time:
                # Get deals BEFORE the first deposit (from execution start date up to first deposit)
                deals_before_first_deposit = []
                first_deposit_timestamp = first_deposit['time']
                
                for deal in all_deals:
                    if deal.time < first_deposit_timestamp:
                        deals_before_first_deposit.append(deal)
                
                if deals_before_first_deposit:
                    # Calculate balance from trades before first deposit
                    trades_pnl_before_deposit = sum((d.profit + d.swap + d.commission) for d in deals_before_first_deposit if d.type in [0, 1])
                    withdrawals_before_deposit = sum(d.profit for d in deals_before_first_deposit if d.type == 3)
                    
                    # The existing balance would be the starting balance from execution date
                    # We need to calculate what the balance was before the first deposit
                    # Current balance minus all deposits and trades gives us the initial balance
                    all_deposits_before_first = [d for d in all_deposits if d['time'] < first_deposit_timestamp]
                    total_deposits_before_first = sum(d['amount'] for d in all_deposits_before_first)
                    
                    # Calculate existing balance = current_balance - (first_deposit + other_deposits + trades + withdrawals)
                    # But we want the balance right before the first deposit
                    # Let's get the balance at the time just before first deposit
                    
                    # Get all deals up to (but not including) first deposit
                    balance_at_time = 0
                    for deal in sorted(deals_before_first_deposit, key=lambda x: x.time):
                        if deal.type in [0, 1]:  # Trade
                            balance_at_time += (deal.profit + deal.swap + deal.commission)
                        elif deal.type == 2:  # Deposit
                            balance_at_time += deal.profit
                        elif deal.type == 3:  # Withdrawal
                            balance_at_time += deal.profit
                    
                    # The existing balance would be the initial deposit (if any) plus trades
                    # But we need to find if there was an initial balance before any deposit
                    # Check if there were any deposits before first deposit (unlikely but possible)
                    if total_deposits_before_first > 0:
                        # There was a deposit before the first deposit we found (shouldn't happen if we sorted correctly)
                        existing_balance = total_deposits_before_first + trades_pnl_before_deposit + withdrawals_before_deposit
                    else:
                        # No deposits before first deposit, so existing balance comes from initial funds + trades
                        # Calculate starting balance from execution date
                        total_pnl_all = sum((d.profit + d.swap + d.commission) for d in all_deals if d.type in [0, 1])
                        total_withdrawals_all = sum(d.profit for d in all_deals if d.type == 3)
                        total_deposits_all = sum(d['amount'] for d in all_deposits)
                        
                        # current_balance = starting_balance + total_deposits_all + total_pnl_all + total_withdrawals_all
                        # starting_balance = current_balance - total_deposits_all - total_pnl_all - total_withdrawals_all
                        starting_balance_from_exec = account_info.balance - total_deposits_all - total_pnl_all - total_withdrawals_all
                        
                        # The existing balance before first deposit would be starting_balance_from_exec + trades_before_first
                        existing_balance = starting_balance_from_exec + trades_pnl_before_deposit + withdrawals_before_deposit
                    
                    print(f"  🔍 Found existing balance before first deposit: ${existing_balance:.2f}")
                else:
                    # No deals before first deposit
                    existing_balance = 0
                    print(f"  🔍 No deals found before first deposit, existing balance = $0")
            
            # Determine starting balance based on existing balance
            broker_balance = None
            starting_bal = None
            
            if existing_balance is not None and existing_balance > 0:
                starting_bal = existing_balance
                broker_balance = existing_balance
                print(f"  📊 Using EXISTING BALANCE (found before first deposit): ${starting_bal:.2f}")
            elif first_deposit_amount is not None:
                starting_bal = first_deposit_amount
                broker_balance = first_deposit_amount
                print(f"  📊 Using FIRST DEPOSIT (no existing balance found): ${starting_bal:.2f}")
            else:
                # Fallback: No deposits found
                total_pnl = sum((d.profit + d.swap + d.commission) for d in all_deals if d.type in [0, 1])
                starting_bal = account_info.balance - total_pnl
                broker_balance = starting_bal
                print(f"  ℹ️  No deposits found, using traditional calculation: ${starting_bal:.2f}")
            
            # Calculate additional metrics for reporting
            total_trades_pnl = sum((d.profit + d.swap + d.commission) for d in all_deals if d.type in [0, 1])
            total_withdrawals = sum(d.profit for d in all_deals if d.type == 3)
            other_deposits_total = sum(d['amount'] for d in all_deposits[1:]) if len(all_deposits) > 1 else 0
            
            print(f"  📊 Balance breakdown:")
            print(f"     Starting balance: ${starting_bal:.2f}")
            if existing_balance and existing_balance > 0:
                print(f"     (Existing balance before first deposit: ${existing_balance:.2f})")
            if first_deposit_amount:
                print(f"     First deposit: ${first_deposit_amount:.2f}")
            print(f"     Other deposits (ignored): ${other_deposits_total:.2f}")
            print(f"     Trades P&L: ${total_trades_pnl:.2f}")
            print(f"     Withdrawals: ${total_withdrawals:.2f}")
            print(f"     Current balance: ${account_info.balance:.2f}")
            
            print(f"📊 {inv_id} | Start: {execution_start_date} | Starting Balance: ${starting_bal:.2f}")
            print(f"   Current Balance: ${account_info.balance:.2f}")
            
            # --- UPDATE ACTIVITIES.JSON WITH BROKER_BALANCE ---
            if broker_balance is not None:
                try:
                    # Load current activities.json
                    if activities_path.exists():
                        with open(activities_path, 'r', encoding='utf-8') as f:
                            activities_data = json.load(f)
                    else:
                        # Create new activities.json if it doesn't exist
                        activities_data = {
                            "activate_autotrading": True,
                            "bypass_restriction": True,
                            "execution_start_date": execution_start_date,
                            "contract_duration": 30,
                            "contract_expiry_date": "",
                            "unauthorized_trades": {},
                            "unauthorized_withdrawals": {},
                            "unauthorized_action_detected": False,
                            "strategies": []
                        }
                    
                    # Update broker_balance
                    old_broker_balance = activities_data.get('broker_balance')
                    activities_data['broker_balance'] = float(broker_balance)
                    
                    # Save updated activities.json
                    with open(activities_path, 'w', encoding='utf-8') as f:
                        json.dump(activities_data, f, indent=4)
                    
                    if old_broker_balance is None:
                        print(f"  💾 Added broker_balance to activities.json: ${broker_balance:.2f}")
                    elif old_broker_balance != broker_balance:
                        print(f"  💾 Updated broker_balance in activities.json: ${old_broker_balance:.2f} → ${broker_balance:.2f}")
                    else:
                        print(f"  ℹ️  broker_balance already correct in activities.json: ${broker_balance:.2f}")
                        
                except Exception as e:
                    print(f"  ⚠️  Error updating activities.json with broker_balance: {e}")
            
            # --- CHECK minimum balance requirement with enhanced verification ---
            try:
                requirements_path = inv_root / "requirements.json"
                
                if requirements_path.exists():
                    print(f"  🔍 Found requirements.json at: {requirements_path}")
                    with open(requirements_path, 'r', encoding='utf-8') as f:
                        requirements_config = json.load(f)
                        
                        min_balance = None
                        if isinstance(requirements_config, list) and len(requirements_config) > 0:
                            min_balance = requirements_config[0].get('minimum_balance')
                        elif isinstance(requirements_config, dict):
                            min_balance = requirements_config.get('minimum_balance')
                        else:
                            print(f"  ⚠️  requirements.json has unexpected format: {type(requirements_config)}")
                        
                        if min_balance is not None:
                            print(f"  📊 Minimum balance requirement: ${min_balance}")
                            
                            # ENHANCED VERIFICATION: Check if existing balance alone meets requirement
                            balance_to_check = starting_bal
                            meets_requirement = starting_bal >= min_balance
                            
                            # If using existing balance and it doesn't meet requirement, check with first deposit added
                            if existing_balance is not None and existing_balance > 0 and not meets_requirement and first_deposit_amount:
                                combined_balance = existing_balance + first_deposit_amount
                                print(f"  🔍 Existing balance ${existing_balance:.2f} does NOT meet minimum requirement")
                                print(f"  🔍 Checking combined balance (existing + first deposit): ${combined_balance:.2f}")
                                
                                if combined_balance >= min_balance:
                                    meets_requirement = True
                                    balance_to_check = combined_balance
                                    print(f"  ✅ Combined balance MEETS minimum requirement")
                                    
                                    # Update broker_balance with combined balance if it meets requirement
                                    if combined_balance != broker_balance:
                                        broker_balance = combined_balance
                                        try:
                                            with open(activities_path, 'r', encoding='utf-8') as f:
                                                activities_data = json.load(f)
                                            activities_data['broker_balance'] = float(combined_balance)
                                            with open(activities_path, 'w', encoding='utf-8') as f:
                                                json.dump(activities_data, f, indent=4)
                                            print(f"  💾 Updated broker_balance to combined balance: ${combined_balance:.2f}")
                                        except Exception as e:
                                            print(f"  ⚠️  Error updating broker_balance with combined balance: {e}")
                                else:
                                    print(f"  No Combined balance still BELOW minimum requirement")
                            
                            if meets_requirement:
                                print(f"  ✅ Balance ${balance_to_check:.2f} MEETS minimum requirement (${min_balance})")
                            else:
                                print(f"  ⚠️  Balance ${balance_to_check:.2f} is BELOW minimum requirement ${min_balance}")
                                print(f"  No Moving investor {inv_id} to issues_investors.json")
                                
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
                                        message = f"Balance ${balance_to_check:.2f} is below minimum requirement ${min_balance}"
                                        if existing_balance and existing_balance > 0 and first_deposit_amount:
                                            message = f"Existing balance ${existing_balance:.2f} + first deposit ${first_deposit_amount:.2f} = ${balance_to_check:.2f} is below minimum requirement ${min_balance}"
                                        investor_data_to_move['MESSAGE'] = message
                                        
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
                            print(f"  ⚠️  No minimum_balance found in requirements.json")
                else:
                    print(f"  ℹ️  No requirements.json found in investor root folder - skipping minimum balance check")
                    
            except Exception as e:
                print(f"  ⚠️  Error checking minimum balance requirement: {e}")
            
            return starting_bal

        else:
            # --- Handle Invalid Broker Login / No Account Info ---
            print(f"  ⚠️  Could not get account info for {inv_id}")
            print(f"  No Moving investor {inv_id} to issues_investors.json due to invalid login")
            
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

def check_and_record_authorized_actions(inv_id=None):
    """
    Check and record authorized/unauthorized actions for investors based on signals.json and tradeshistory.json.
    
    This function:
    1. Reads tradeshistory.json to get authorized trades (tickets and magics)
    2. Compares with MT5 pending orders and open positions
    3. Fetches history orders from execution start date to present
    4. Identifies unauthorized orders and positions
    5. Records them in activities.json with detailed information
    6. Records completed history orders with profit/loss information
    7. Calculates profit and loss (current balance - starting balance)
    8. Records trades (both authorized and unauthorized) in proper format
    
    MATCHING STRATEGY (in order):
    1. Direct ticket number match
    2. Magic number match
    3. Placed timestamp match (within 5 seconds)
    4. Volume + symbol + time window match
    5. Original order data match (entry, SL, TP from signals.json)
    
    Args:
        inv_id: Optional specific investor ID to process. If None, processes all investors.
        
    Returns:
        dict: Statistics about authorized/unauthorized actions found
    """
    
    print("\n" + "="*80)
    print("  🔍 AUTHORIZED ACTIONS AUDIT".ljust(79) + "=")
    print("="*80)
    
    stats = {
        "investor_id": inv_id if inv_id else "all",
        "investors_processed": 0,
        "investors_with_unauthorized": 0,
        "unauthorized_orders_found": 0,
        "unauthorized_positions_found": 0,
        "history_matched": {"ticket": 0, "magic": 0, "timestamp": 0, "volume_symbol": 0, "order_data": 0, "synthetic": 0},
        "history_orders_recorded": 0,
        "history_orders_updated": 0,
        "bypass_active_investors": 0,
        "autotrading_active_investors": 0,
        "unauthorized_by_investor": {},
        "processing_success": False
    }
    
    investor_ids = [inv_id] if inv_id else list(usersdictionary.keys())
    
    if not investor_ids:
        print("│\n├─ No No investors found.")
        print("="*80)
        return stats
    
    for user_brokerid in investor_ids:
        # ============================================================
        # HEADER
        # ============================================================
        print(f"\n├{'─'*78}┤")
        print(f"│  📋 INVESTOR: {user_brokerid}")
        print(f"├{'─'*78}┤")
        
        inv_root = Path(INV_PATH) / user_brokerid
        if not inv_root.exists():
            print(f"│  No Path not found: {inv_root}")
            continue
        
        stats["investors_processed"] += 1
        
        # ============================================================
        # LOAD CONFIGURATION FILES
        # ============================================================
        acc_mgmt_path = inv_root / "accountmanagement.json"
        tradeshistory_path = inv_root / "tradeshistory.json"
        activities_path = inv_root / "activities.json"
        signals_path = inv_root / "signals.json"
        
        # Load existing activities.json to get starting balance
        existing_activities = {}
        starting_balance = None
        if activities_path.exists():
            try:
                with open(activities_path, 'r', encoding='utf-8') as f:
                    existing_activities = json.load(f)
                    starting_balance = existing_activities.get('broker_balance')
                if starting_balance:
                    print(f"│  💰 Starting balance from activities.json: ${starting_balance:.2f}")
            except Exception as e:
                print(f"│  ⚠️ Error reading activities.json: {e}")
        
        # Load tradeshistory.json
        existing_history_dict = {}
        if tradeshistory_path.exists():
            try:
                with open(tradeshistory_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    items = data if isinstance(data, list) else list(data.values())
                    for trade in items:
                        ticket = trade.get('ticket')
                        if ticket:
                            existing_history_dict[str(ticket)] = trade
                print(f"│  📚 Loaded {len(existing_history_dict)} trades from tradeshistory.json")
            except Exception as e:
                print(f"│  ⚠️ Error reading tradeshistory.json: {e}")
        
        # Load signals.json for original order data
        signals_dict = {}
        if signals_path.exists():
            try:
                with open(signals_path, 'r', encoding='utf-8') as f:
                    signals = json.load(f)
                    if isinstance(signals, list):
                        for signal in signals:
                            ticket = signal.get('ticket')
                            if ticket:
                                signals_dict[str(ticket)] = signal
                    print(f"│  📡 Loaded {len(signals_dict)} signals from signals.json")
            except Exception as e:
                print(f"│  ⚠️ Error reading signals.json: {e}")
        
        # Load account settings
        bypass_active = False
        autotrading_active = False
        magic_number = 0
        execution_start_date = None
        
        if acc_mgmt_path.exists():
            try:
                with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                    acc_config = json.load(f)
                    settings = acc_config.get("settings", {})
                    bypass_active = settings.get("enable_authorization_bypass", False)
                    autotrading_active = settings.get("enable_auto_trading", False)
                    magic_number = acc_config.get("magic_number", 0)
                    execution_start_date = acc_config.get('execution_start_date')
                print(f"│  ⚙️ Bypass: {bypass_active} | Auto-trading: {autotrading_active} | Magic: {magic_number}")
            except Exception as e:
                print(f"│  ⚠️ Error reading accountmanagement.json: {e}")
        
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
        
        # Parse start date
        start_datetime = None
        if execution_start_date:
            for fmt in ["%B %d, %Y", "%Y-%m-%d"]:
                try:
                    start_datetime = datetime.strptime(execution_start_date, fmt)
                    print(f"│  📅 Fetching history from: {start_datetime.strftime('%Y-%m-%d')}")
                    break
                except:
                    continue
        
        # ============================================================
        # BUILD AUTHORIZED INDEXES
        # ============================================================
        authorized_tickets = set()
        authorized_magics = set()
        authorized_by_timestamp = {}  # timestamp -> ticket
        authorized_by_volume_symbol = {}  # (symbol, volume, approx_time) -> ticket
        
        for ticket, trade in existing_history_dict.items():
            # Add ticket
            try:
                authorized_tickets.add(int(ticket))
            except:
                authorized_tickets.add(ticket)
            
            # Add magic
            magic = trade.get('magic')
            if magic:
                try:
                    authorized_magics.add(int(magic))
                except:
                    authorized_magics.add(magic)
            
            # Index by placed timestamp (for matching)
            placed_ts = trade.get('placed_timestamp')
            if placed_ts:
                try:
                    # Parse timestamp and store with 5-second tolerance
                    dt = datetime.fromisoformat(placed_ts.replace('Z', '+00:00'))
                    ts_key = int(dt.timestamp() / 5)  # 5-second windows
                    if ts_key not in authorized_by_timestamp:
                        authorized_by_timestamp[ts_key] = []
                    authorized_by_timestamp[ts_key].append(ticket)
                except:
                    pass
            
            # Index by symbol + volume + time window (15 minutes)
            symbol = trade.get('symbol')
            volume = trade.get('volume')
            if symbol and volume and placed_ts:
                try:
                    dt = datetime.fromisoformat(placed_ts.replace('Z', '+00:00'))
                    time_window = int(dt.timestamp() / 900)  # 15-minute windows
                    key = f"{symbol}_{volume}_{time_window}"
                    if key not in authorized_by_volume_symbol:
                        authorized_by_volume_symbol[key] = []
                    authorized_by_volume_symbol[key].append(ticket)
                except:
                    pass
        
        print(f"│  🔑 Authorized: {len(authorized_tickets)} tickets, {len(authorized_magics)} magics")
        
        # ============================================================
        # CONNECT TO MT5
        # ============================================================
        broker_cfg = usersdictionary.get(user_brokerid)
        if not broker_cfg:
            print(f"│  No No broker config found")
            continue
        
        login_id = int(broker_cfg['LOGIN_ID'])
        mt5_path = broker_cfg["TERMINAL_PATH"]
        
        acc = mt5.account_info()
        if acc is None or acc.login != login_id:
            print(f"│  🔌 Logging into account {login_id}...")
            if not mt5.login(login_id, password=broker_cfg["PASSWORD"], server=broker_cfg["SERVER"]):
                print(f"│  No Login failed: {mt5.last_error()}")
                continue
            print(f"│  ✅ Successfully logged in")
        else:
            print(f"│  ✅ Already logged in")
        
        # Get current balance after login
        current_balance = mt5.account_info().balance
        print(f"│  💰 Current balance: ${current_balance:.2f}")
        
        # Calculate profit and loss if starting balance exists
        profit_and_loss = 0.0
        if starting_balance is not None:
            profit_and_loss = current_balance - starting_balance
            print(f"│  📈 Profit & Loss: ${profit_and_loss:.2f}")
        
        # ============================================================
        # FETCH HISTORY DEALS
        # ============================================================
        history_matched = {"ticket": 0, "magic": 0, "timestamp": 0, "volume_symbol": 0, "order_data": 0, "synthetic": 0}
        history_recorded = 0
        history_updated = 0
        
        # Initialize trades lists
        authorized_closed_trades = []
        unauthorized_trades_list = []
        won_trades = 0
        lost_trades = 0
        symbols_won = {}
        symbols_lost = {}
        
        if start_datetime:
            print(f"│\n├─ 📜 FETCHING HISTORY DEALS".ljust(79) + "┤")
            
            history_deals = mt5.history_deals_get(start_datetime, datetime.now())
            history_orders = mt5.history_orders_get(start_datetime, datetime.now())
            
            # Index orders by ticket for quick lookup
            orders_by_ticket = {order.ticket: order for order in (history_orders or [])}
            
            if history_deals:
                print(f"│  ✅ Found {len(history_deals)} deals, {len(orders_by_ticket)} orders")
                
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
                    deal_types = [d.type for d in deals]
                    
                    # Find entry and exit deals
                    entry_deal = next((d for d in deals if d.type in [0, 1]), None)
                    exit_deal = next((d for d in deals if d.type in [0, 1] and d != entry_deal), None)
                    
                    # Generate ticket ID
                    ticket_id = None
                    if isinstance(order_key, int) and order_key != 0:
                        ticket_id = order_key
                    elif entry_deal and entry_deal.order != 0:
                        ticket_id = entry_deal.order
                    else:
                        ticket_id = abs(hash(order_key)) % 100000000
                    
                    # ================================================
                    # MATCHING LOGIC (FALLBACK CHAIN)
                    # ================================================
                    is_authorized = False
                    match_method = None
                    matched_ticket = None
                    
                    # Method 1: Direct ticket match
                    if ticket_id and str(ticket_id) in existing_history_dict:
                        is_authorized = True
                        match_method = "ticket"
                        matched_ticket = ticket_id
                        history_matched["ticket"] += 1
                    
                    # Method 2: Magic number match
                    if not is_authorized and entry_deal and entry_deal.magic in authorized_magics:
                        is_authorized = True
                        match_method = "magic"
                        matched_ticket = f"magic_{entry_deal.magic}"
                        history_matched["magic"] += 1
                    
                    # Method 3: Placed timestamp match (within 5 seconds)
                    if not is_authorized and entry_deal:
                        deal_time = int(entry_deal.time)
                        ts_window = int(deal_time / 5)
                        if ts_window in authorized_by_timestamp:
                            is_authorized = True
                            match_method = "timestamp"
                            matched_ticket = authorized_by_timestamp[ts_window][0]
                            history_matched["timestamp"] += 1
                    
                    # Method 4: Volume + Symbol + Time window match (15 min)
                    if not is_authorized and entry_deal:
                        symbol = entry_deal.symbol
                        volume = entry_deal.volume
                        time_window = int(entry_deal.time / 900)
                        key = f"{symbol}_{volume}_{time_window}"
                        if key in authorized_by_volume_symbol:
                            is_authorized = True
                            match_method = "volume_symbol"
                            matched_ticket = authorized_by_volume_symbol[key][0]
                            history_matched["volume_symbol"] += 1
                    
                    # Method 5: Original order data from signals.json
                    if not is_authorized and ticket_id and str(ticket_id) in signals_dict:
                        signal = signals_dict[str(ticket_id)]
                        signal_entry = signal.get('entry')
                        signal_volume = signal.get('volume')
                        signal_type = signal.get('order_type')
                        
                        if entry_deal and signal_entry and signal_volume:
                            price_diff = abs(entry_deal.price - signal_entry)
                            volume_match = abs(entry_deal.volume - signal_volume) < 0.001
                            
                            if price_diff <= 0.0010 and volume_match:  # Within 10 pips
                                is_authorized = True
                                match_method = "order_data"
                                matched_ticket = ticket_id
                                history_matched["order_data"] += 1
                    
                    # Method 6: Synthetic record for non-trade operations
                    if not is_authorized and entry_deal is None and (total_profit != 0 or total_commission != 0):
                        is_authorized = True
                        match_method = "synthetic"
                        history_matched["synthetic"] += 1
                    
                    # ================================================
                    # CREATE OR UPDATE TRADE RECORD
                    # ================================================
                    if entry_deal and entry_deal.type in [0, 1]:  # Only process actual trades
                        trade_record = {
                            'ticket': ticket_id,
                            'symbol': entry_deal.symbol,
                            'type': 'BUY' if entry_deal.type == 0 else 'SELL',
                            'volume': entry_deal.volume,
                            'profit': round(total_pnl, 2),
                            'time': datetime.fromtimestamp(entry_deal.time).strftime('%Y-%m-%d %H:%M:%S'),
                            'match_method': match_method if match_method else 'unauthorized'
                        }
                        
                        if is_authorized:
                            # Authorized trade
                            authorized_closed_trades.append(trade_record)
                            total_authorized_pnl = total_pnl
                            
                            # Update win/loss statistics
                            if total_pnl > 0:
                                won_trades += 1
                                symbols_won[entry_deal.symbol] = symbols_won.get(entry_deal.symbol, 0.0) + total_pnl
                            elif total_pnl < 0:
                                lost_trades += 1
                                symbols_lost[entry_deal.symbol] = symbols_lost.get(entry_deal.symbol, 0.0) + total_pnl
                            
                            profit_symbol = "📈" if total_pnl > 0 else "📉" if total_pnl < 0 else "⚖️"
                            print(f"│     {profit_symbol} Authorized #{ticket_id}: ${total_pnl:.2f} [{match_method}]")
                        else:
                            # Unauthorized trade
                            trade_record['reason'] = f"Trade NOT authorized (Ticket: {ticket_id})"
                            unauthorized_trades_list.append(trade_record)
                            profit_symbol = "🚫" if total_pnl > 0 else "⚠️" if total_pnl < 0 else "⚖️"
                            print(f"│     {profit_symbol} UNAUTHORIZED #{ticket_id}: ${total_pnl:.2f}")
                    
                    # Update existing history dictionary if needed
                    if is_authorized and ticket_id and str(ticket_id) in existing_history_dict:
                        # Update existing trade status if closed
                        trade = existing_history_dict[str(ticket_id)]
                        if trade.get('status') != 'closed' and (exit_deal or len(deals) > 1):
                            trade['status'] = 'closed'
                            trade['close_price'] = exit_deal.price if exit_deal else entry_deal.price if entry_deal else 0
                            trade['close_time'] = datetime.fromtimestamp(exit_deal.time).strftime('%Y-%m-%d %H:%M:%S') if exit_deal else datetime.fromtimestamp(entry_deal.time).strftime('%Y-%m-%d %H:%M:%S') if entry_deal else ''
                            trade['profit'] = total_pnl
                            trade['profit_and_loss'] = float(total_pnl)
                            trade['history_match_method'] = match_method
                            history_updated += 1
                
                # Print matching summary
                print(f"│\n├─ 📊 MATCHING SUMMARY")
                print(f"│  • Ticket match:     {history_matched['ticket']:>3}")
                print(f"│  • Magic match:      {history_matched['magic']:>3}")
                print(f"│  • Timestamp match:  {history_matched['timestamp']:>3}")
                print(f"│  • Volume+Symbol:    {history_matched['volume_symbol']:>3}")
                print(f"│  • Order data match: {history_matched['order_data']:>3}")
                print(f"│  • Synthetic:        {history_matched['synthetic']:>3}")
                print(f"│  • Authorized trades: {len(authorized_closed_trades)}")
                print(f"│  • Unauthorized trades: {len(unauthorized_trades_list)}")
                
                # Update stats
                for key in history_matched:
                    stats["history_matched"][key] += history_matched[key]
                stats["history_orders_recorded"] += len(authorized_closed_trades)
                stats["history_orders_updated"] += history_updated
                
            else:
                print(f"│  ℹ️ No history deals found")
        else:
            print(f"│  ⚠️ No execution start date - skipping history")
        
        # ============================================================
        # CHECK CURRENT ORDERS & POSITIONS
        # ============================================================
        print(f"│\n├─ 🔄 CHECKING CURRENT STATE".ljust(79) + "┤")
        
        pending_orders = mt5.orders_get() or []
        open_positions = mt5.positions_get() or []
        
        print(f"│  📊 Pending orders: {len(pending_orders)} | Open positions: {len(open_positions)}")
        
        # Find unauthorized items
        unauthorized_orders = []
        unauthorized_positions = []
        
        for order in pending_orders:
            if order.ticket not in authorized_tickets and order.magic not in authorized_magics and order.magic != magic_number:
                unauthorized_orders.append({
                    'ticket': order.ticket,
                    'symbol': order.symbol,
                    'type': order.type,
                    'volume': order.volume_current,
                    'price': order.price_open,
                    'magic': order.magic
                })
        
        for pos in open_positions:
            if pos.ticket not in authorized_tickets and pos.magic not in authorized_magics and pos.magic != magic_number:
                unauthorized_positions.append({
                    'ticket': pos.ticket,
                    'symbol': pos.symbol,
                    'type': 'BUY' if pos.type == 0 else 'SELL',
                    'volume': pos.volume,
                    'price': pos.price_open,
                    'profit': pos.profit,
                    'magic': pos.magic
                })
        
        stats["unauthorized_orders_found"] += len(unauthorized_orders)
        stats["unauthorized_positions_found"] += len(unauthorized_positions)
        
        if unauthorized_orders or unauthorized_positions:
            stats["investors_with_unauthorized"] += 1
            stats["unauthorized_by_investor"][user_brokerid] = {
                'orders': len(unauthorized_orders),
                'positions': len(unauthorized_positions)
            }
            
            print(f"│\n├─ 🚫 UNAUTHORIZED ITEMS FOUND")
            for order in unauthorized_orders[:3]:
                print(f"│     Order #{order['ticket']}: {order['symbol']} @ {order['price']}")
            if len(unauthorized_orders) > 3:
                print(f"│     ... and {len(unauthorized_orders)-3} more orders")
            for pos in unauthorized_positions[:3]:
                print(f"│     Position #{pos['ticket']}: {pos['symbol']} ${pos['profit']:.2f}")
        else:
            print(f"│  ✅ No unauthorized items found")
        
        # ============================================================
        # BUILD TRADES STRUCTURE
        # ============================================================
        trades_structure = {
            "summary": {
                "total_trades": len(authorized_closed_trades),
                "won": won_trades,
                "lost": lost_trades,
                "symbols_that_lost": {k: round(v, 2) for k, v in symbols_lost.items()},
                "symbols_that_won": {k: round(v, 2) for k, v in symbols_won.items()}
            },
            "authorized_closed_trades": authorized_closed_trades
        }
        
        # ============================================================
        # SAVE ACTIVITIES.JSON WITH ALL DATA
        # ============================================================
        print(f"│\n├─ 💾 SAVING ACTIVITIES.JSON".ljust(79) + "┤")
        
        # Prepare activities data
        unauthorized_detected = len(unauthorized_orders) > 0 or len(unauthorized_positions) > 0 or len(unauthorized_trades_list) > 0
        
        # Determine unauthorized types
        unauthorized_type = set()
        if unauthorized_trades_list:
            unauthorized_type.add('trades')
        if unauthorized_orders or unauthorized_positions:
            unauthorized_type.add('positions')
        
        activities_data = {
            'execution_start_date': execution_start_date,
            'broker_balance': starting_balance if starting_balance is not None else 0.0,
            'profitandloss': round(profit_and_loss, 2),
            'current_balance': current_balance,
            'trades': json.dumps(trades_structure),
            'unauthorized_action_detected': unauthorized_detected,
            'bypass_restriction': bypass_active,
            'activate_autotrading': autotrading_active,
            'last_audit_timestamp': datetime.now().isoformat(),
            'history_matching_stats': history_matched,
            'unauthorized_actions': {
                'detected': unauthorized_detected,
                'bypass_active': bypass_active,
                'autotrading_active': autotrading_active,
                'type': list(unauthorized_type) if unauthorized_type else [],
                'unauthorized_trades': unauthorized_trades_list,
                'unauthorized_withdrawals': [],  # Can be populated if needed
                'unauthorized_orders': unauthorized_orders,
                'unauthorized_positions': unauthorized_positions
            },
            'authorized_summary': {
                'tickets': len(authorized_tickets),
                'magics': len(authorized_magics),
                'pending_orders': len(pending_orders),
                'open_positions': len(open_positions),
                'unauthorized_orders': len(unauthorized_orders),
                'unauthorized_positions': len(unauthorized_positions)
            }
        }
        
        # Merge with existing activities if any
        if existing_activities:
            activities_data.update(existing_activities)
            # Override with new data
            activities_data.update({
                'broker_balance': starting_balance if starting_balance is not None else existing_activities.get('broker_balance', 0.0),
                'profitandloss': round(profit_and_loss, 2),
                'current_balance': current_balance,
                'trades': json.dumps(trades_structure),
                'unauthorized_action_detected': unauthorized_detected,
                'last_audit_timestamp': datetime.now().isoformat(),
                'unauthorized_actions': activities_data['unauthorized_actions']
            })
        
        # Save activities.json
        try:
            with open(activities_path, 'w', encoding='utf-8') as f:
                json.dump(activities_data, f, indent=4)
            print(f"│  ✅ activities.json saved")
            print(f"│     • Broker balance: ${activities_data['broker_balance']:.2f}")
            print(f"│     • P&L: ${activities_data['profitandloss']:.2f}")
            print(f"│     • Authorized trades: {trades_structure['summary']['total_trades']}")
            print(f"│     • Unauthorized trades: {len(unauthorized_trades_list)}")
        except Exception as e:
            print(f"│  No Error saving activities.json: {e}")
        
        # ============================================================
        # UPDATE TRADESHISTORY.JSON IF NEEDED
        # ============================================================
        if history_updated > 0:
            try:
                history_list = list(existing_history_dict.values())
                with open(tradeshistory_path, 'w', encoding='utf-8') as f:
                    json.dump(history_list, f, indent=4)
                print(f"│  ✅ tradeshistory.json updated ({len(history_list)} trades)")
            except Exception as e:
                print(f"│  ⚠️ Error saving tradeshistory.json: {e}")
        
        # Update stats
        stats["bypass_active_investors"] += 1 if bypass_active else 0
        stats["autotrading_active_investors"] += 1 if autotrading_active else 0
        
        # Print investor summary
        print(f"│\n├─ 📈 INVESTOR SUMMARY")
        print(f"│  • Starting Balance: ${starting_balance if starting_balance else 0.0:.2f}")
        print(f"│  • Current Balance: ${current_balance:.2f}")
        print(f"│  • P&L: ${profit_and_loss:.2f}")
        print(f"│  • Authorized trades: {len(authorized_closed_trades)} ({won_trades}W/{lost_trades}L)")
        print(f"│  • Unauthorized trades: {len(unauthorized_trades_list)}")
        print(f"│  • Unauthorized items: {len(unauthorized_orders)} orders, {len(unauthorized_positions)} positions")
        
        if bypass_active:
            print(f"│  ⚠️ BYPASS ACTIVE - unauthorized actions allowed")
        elif unauthorized_detected:
            print(f"│  ⛔ RESTRICTIONS ACTIVE - will be moved to issues")
    
    # ============================================================
    # FINAL SUMMARY
    # ============================================================
    print("\n" + "="*80)
    print("  📊 FINAL SUMMARY".ljust(79) + "=")
    print("="*80)
    print(f"│  Investors processed:     {stats['investors_processed']}")
    print(f"│  Unauthorized investors:  {stats['investors_with_unauthorized']}")
    print(f"│  History matched:")
    print(f"│    • Ticket:     {stats['history_matched']['ticket']:>4}")
    print(f"│    • Magic:      {stats['history_matched']['magic']:>4}")
    print(f"│    • Timestamp:  {stats['history_matched']['timestamp']:>4}")
    print(f"│    • Vol+Symbol: {stats['history_matched']['volume_symbol']:>4}")
    print(f"│    • Order data: {stats['history_matched']['order_data']:>4}")
    print(f"│    • Synthetic:  {stats['history_matched']['synthetic']:>4}")
    print(f"│  History recorded:        {stats['history_orders_recorded']}")
    print(f"│  History updated:         {stats['history_orders_updated']}")
    print(f"│  Unauthorized orders:     {stats['unauthorized_orders_found']}")
    print(f"│  Unauthorized positions:  {stats['unauthorized_positions_found']}")
    print(f"│  Bypass active:           {stats['bypass_active_investors']}")
    print(f"│  Auto-trading active:     {stats['autotrading_active_investors']}")
    
    if stats["unauthorized_by_investor"]:
        print(f"│\n├─ 🚫 UNAUTHORIZED BY INVESTOR")
        for inv_id, counts in stats["unauthorized_by_investor"].items():
            print(f"│    {inv_id}: {counts['orders']} orders, {counts['positions']} positions")
    
    print("="*80 + "\n")
    
    stats["processing_success"] = True
    return stats

def update_investor_info(inv_id=None):
    """
    Updates investor information in UPDATED_INVESTORS.json including:
    - Balance at execution start date (from activities.json)
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
    
    # Load existing updated investors
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
        print(f"\n{'='*60}")
        print(f"📋 INVESTOR: {user_brokerid}")
        print(f"{'='*60}")
        
        if user_brokerid not in usersdictionary:
            print(f"   No Investor {user_brokerid} not found in usersdictionary")
            continue
            
        base_info = usersdictionary[user_brokerid].copy()
        inv_root = Path(INV_PATH) / user_brokerid
        
        if not inv_root.exists():
            print(f"   No Path not found: {inv_root}")
            continue
        
        # ============================================================
        # READ FROM ACTIVITIES.JSON (Primary Source)
        # ============================================================
        activities_path = inv_root / "activities.json"
        
        if not activities_path.exists():
            print(f"   ⚠️  activities.json not found in {inv_root} - skipping investor")
            continue
        
        try:
            with open(activities_path, 'r', encoding='utf-8') as f:
                activities = json.load(f)
            print(f"   ✅ Loaded activities.json")
        except Exception as e:
            print(f"   No Error reading activities.json: {e}")
            continue
        
        # Extract data from activities.json
        execution_start_date = activities.get('execution_start_date')
        starting_balance = activities.get('broker_balance', 0.0)
        profit_and_loss = activities.get('profitandloss', 0.0)
        current_balance = activities.get('current_balance', 0.0)
        bypass_active = activities.get('bypass_restriction', False)
        autotrading_active = activities.get('activate_autotrading', False)
        unauthorized_detected = activities.get('unauthorized_action_detected', False)
        last_audit_timestamp = activities.get('last_audit_timestamp', '')
        
        # Extract trades data (stored as JSON string in activities.json)
        trades_data = {}
        trades_json_str = activities.get('trades', '{}')
        if trades_json_str:
            try:
                if isinstance(trades_json_str, str):
                    trades_data = json.loads(trades_json_str)
                else:
                    trades_data = trades_json_str
                print(f"   📊 Loaded trades data from activities.json")
            except Exception as e:
                print(f"   ⚠️  Error parsing trades JSON: {e}")
                trades_data = {}
        
        # Extract unauthorized actions
        unauthorized_actions = activities.get('unauthorized_actions', {})
        unauthorized_type = unauthorized_actions.get('type', [])
        unauthorized_trades_list = unauthorized_actions.get('unauthorized_trades', [])
        unauthorized_orders = unauthorized_actions.get('unauthorized_orders', [])
        unauthorized_positions = unauthorized_actions.get('unauthorized_positions', [])
        unauthorized_withdrawals = unauthorized_actions.get('unauthorized_withdrawals', [])
        
        # Extract authorized summary
        authorized_summary = activities.get('authorized_summary', {})
        
        # Extract trades summary
        trades_summary = trades_data.get('summary', {})
        authorized_closed_trades = trades_data.get('authorized_closed_trades', [])
        
        # Get trade statistics
        won_trades = trades_summary.get('won', 0)
        lost_trades = trades_summary.get('lost', 0)
        symbols_won = trades_summary.get('symbols_that_won', {})
        symbols_lost = trades_summary.get('symbols_that_lost', {})
        
        # Print extracted information
        print(f"\n   📋 ACTIVITIES.JSON DATA:")
        print(f"      • Execution Start Date: {execution_start_date}")
        print(f"      • Starting Balance: ${starting_balance:.2f}")
        print(f"      • Current Balance: ${current_balance:.2f}")
        print(f"      • P&L: ${profit_and_loss:.2f}")
        print(f"      • Bypass Active: {bypass_active}")
        print(f"      • Auto-trading Active: {autotrading_active}")
        print(f"      • Unauthorized Detected: {unauthorized_detected}")
        print(f"      • Last Audit: {last_audit_timestamp}")
        
        print(f"\n   📊 TRADES SUMMARY:")
        print(f"      • Total Authorized Trades: {len(authorized_closed_trades)}")
        print(f"      • Won Trades: {won_trades}")
        print(f"      • Lost Trades: {lost_trades}")
        if symbols_won:
            print(f"      • Symbols Won: {symbols_won}")
        if symbols_lost:
            print(f"      • Symbols Lost: {symbols_lost}")
        
        print(f"\n   🚫 UNAUTHORIZED ACTIONS:")
        print(f"      • Type: {unauthorized_type if unauthorized_type else 'None'}")
        print(f"      • Unauthorized Trades: {len(unauthorized_trades_list)}")
        print(f"      • Unauthorized Orders: {len(unauthorized_orders)}")
        print(f"      • Unauthorized Positions: {len(unauthorized_positions)}")
        print(f"      • Unauthorized Withdrawals: {len(unauthorized_withdrawals)}")
        
        # ============================================================
        # READ FROM TRADESHISTORY.JSON (if needed for additional data)
        # ============================================================
        history_path = inv_root / "tradeshistory.json"
        authorized_tickets_count = 0
        
        if history_path.exists():
            try:
                with open(history_path, 'r', encoding='utf-8') as f:
                    history_trades = json.load(f)
                authorized_tickets_count = len(history_trades) if isinstance(history_trades, list) else len(history_trades.keys())
                print(f"\n   📚 TRADESHISTORY.JSON: {authorized_tickets_count} authorized tickets")
            except Exception as e:
                print(f"   ⚠️  Error reading tradeshistory.json: {e}")
        
        # ============================================================
        # READ FROM ACCOUNTMANAGEMENT.JSON (fallback for some data)
        # ============================================================
        acc_mgmt_path = inv_root / "accountmanagement.json"
        magic_number = 0
        
        if acc_mgmt_path.exists():
            try:
                with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                    acc_config = json.load(f)
                    magic_number = acc_config.get('magic_number', 0)
                print(f"   ⚙️  Magic Number from accountmanagement.json: {magic_number}")
            except Exception as e:
                print(f"   ⚠️  Error reading accountmanagement.json: {e}")
        
        # ============================================================
        # CONTRACT DAYS CALCULATION
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
                    days_passed = (datetime.now() - start).days
                    contract_days_left = str(max(0, 30 - days_passed))
                    print(f"\n   📅 Contract Days Left: {contract_days_left} (Started: {execution_start_date}, Days passed: {days_passed})")
            except Exception as e:
                print(f"   ⚠️  Error calculating contract days: {e}")
        
        # ============================================================
        # BUILD TRADES STRUCTURE
        # ============================================================
        trades_info = {
            "summary": {
                "total_trades": len(authorized_closed_trades),
                "won": won_trades,
                "lost": lost_trades,
                "symbols_that_lost": {k: round(float(v), 2) for k, v in symbols_lost.items()},
                "symbols_that_won": {k: round(float(v), 2) for k, v in symbols_won.items()}
            },
            "authorized_closed_trades": authorized_closed_trades
        }
        
        # ============================================================
        # BUILD INVESTOR INFO DICTIONARY
        # ============================================================
        investor_info = {
            "id": user_brokerid,
            "server": base_info.get("SERVER", base_info.get("server", "")),
            "login": base_info.get("LOGIN_ID", base_info.get("login", "")),
            "password": base_info.get("PASSWORD", base_info.get("password", "")),
            "application_status": "approved",  # Will be overridden if moved to issues
            "broker_balance": round(float(starting_balance), 2) if starting_balance is not None else 0.0,
            "profitandloss": round(float(profit_and_loss), 2),
            "contract_days_left": contract_days_left,
            "execution_start_date": execution_start_date if execution_start_date else "",
            "last_audit_timestamp": last_audit_timestamp,
            "current_balance": round(float(current_balance), 2),
            "trades": trades_info,
            "authorized_tickets_count": authorized_tickets_count,
            "magic_number": magic_number,
            "unauthorized_actions": {
                "detected": unauthorized_detected,
                "bypass_active": bypass_active,
                "autotrading_active": autotrading_active,
                "type": unauthorized_type if unauthorized_type else [],
                "unauthorized_trades": unauthorized_trades_list,
                "unauthorized_withdrawals": unauthorized_withdrawals,
                "unauthorized_orders": unauthorized_orders,
                "unauthorized_positions": unauthorized_positions
            }
        }
        
        # ============================================================
        # DETERMINE IF INVESTOR SHOULD BE MOVED TO ISSUES
        # ============================================================
        should_move_to_issues = False
        issue_message = ""
        
        if unauthorized_detected:
            if bypass_active:
                print(f"\n   ⚠️  UNAUTHORIZED ACTIONS DETECTED BUT BYPASS ACTIVE")
                print(f"      → Keeping in updated_investors.json (bypass enabled)")
                should_move_to_issues = False
                investor_info['application_status'] = "approved_with_bypass"
                investor_info['bypass_note'] = "Unauthorized actions detected but bypass is active"
            else:
                should_move_to_issues = True
                issue_message = "Unauthorized action detected - restricted (bypass inactive)"
                print(f"\n   ⛔ UNAUTHORIZED ACTIONS DETECTED WITHOUT BYPASS")
                print(f"      → MOVING TO ISSUES INVESTORS")
                print(f"      → Reason: {issue_message}")
        else:
            print(f"\n   ✅ NO UNAUTHORIZED ACTIONS DETECTED")
            print(f"      → Keeping in updated_investors.json")
            investor_info['application_status'] = "approved"
        
        # ============================================================
        # MOVE TO ISSUES OR UPDATE UPDATED INVESTORS
        # ============================================================
        if should_move_to_issues:
            investor_info['message'] = issue_message
            investor_info['application_status'] = "rejected"
            
            # Remove from updated_investors if exists
            if user_brokerid in updated_investors:
                del updated_investors[user_brokerid]
                print(f"   🗑️  Removed from updated_investors.json")
            
            # Add to issues_investors
            issues_investors[user_brokerid] = investor_info
            print(f"   📝 Added to issues_investors.json")
            
        else:
            # Update or add to updated_investors
            updated_investors[user_brokerid] = investor_info
            print(f"\n   ✅ INVESTOR SUMMARY (Added to updated_investors.json):")
            print(f"      • Application Status: {investor_info['application_status']}")
            print(f"      • Starting Balance: ${investor_info['broker_balance']:.2f}")
            print(f"      • Current Balance: ${investor_info['current_balance']:.2f}")
            print(f"      • P&L: ${investor_info['profitandloss']:.2f}")
            print(f"      • Authorized Trades: {trades_info['summary']['total_trades']} ({won_trades}W/{lost_trades}L)")
            print(f"      • Unauthorized Detected: {unauthorized_detected}")
            if bypass_active:
                print(f"      • ⚠️  BYPASS ACTIVE - unauthorized actions allowed")
            print(f"      • Contract Days Left: {contract_days_left}")
        
        print(f"\n{'-'*60}")
    
    # ============================================================
    # SAVE UPDATED INVESTORS JSON
    # ============================================================
    try:
        with open(updated_investors_path, 'w', encoding='utf-8') as f:
            json.dump(updated_investors, f, indent=4)
        print(f"\n✅ Saved updated_investors.json with {len(updated_investors)} investors")
    except Exception as e:
        print(f"\nNo Failed to save updated_investors.json: {e}")
    
    # ============================================================
    # SAVE ISSUES INVESTORS JSON
    # ============================================================
    try:
        with open(issues_investors_path, 'w', encoding='utf-8') as f:
            json.dump(issues_investors, f, indent=4)
        print(f"✅ Saved issues_investors.json with {len(issues_investors)} investors")
    except Exception as e:
        print(f"No Failed to save issues_investors.json: {e}")
    
    # ============================================================
    # FINAL SUMMARY
    # ============================================================
    print("\n" + "="*80)
    print("📊 FINAL UPDATE SUMMARY")
    print("="*80)
    print(f"   • Total investors processed: {len(investor_ids)}")
    print(f"   • Updated investors: {len(updated_investors)}")
    print(f"   • Issues investors: {len(issues_investors)}")
    print(f"   • Active bypass investors: {sum(1 for v in updated_investors.values() if v.get('unauthorized_actions', {}).get('bypass_active', False))}")
    print("="*80 + "\n")
    
    return updated_investors
#---         ----           --#

def get_normalized_symbol(record_symbol, risk_keys=None):
    """
    Standardizes symbols with a 'Broker-First' priority.
    If 'US OIL' is passed, it finds the USOIL family, then checks if the broker
    uses USOUSD, USOIL, or WTI.
    """
    if not record_symbol: return None

    NORM_PATH = Path(r"C:\xampp\htdocs\harvcore\harvox\symbols_normalization.json")
    
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

def symbols_dynamic_grid_prices(inv_id=None):
    """
    DYNAMIC grid price collection - Single function to rule them all!
    
    Reads from accountmanagement.json:
    {
        "grid_prices_setup": {
            "grid_levels": 6,              # Number of levels per side (bid/ask)
            "grid_multiplier": 25,         # Pattern increment (25, 50, 250, etc.)
            "bid_prices_order_type": "buy_stop",
            "ask_prices_order_type": "sell_stop"
        }
    }
    
    Grid patterns are automatically generated based on multiplier:
    - Multiplier 25: Patterns end in 000, 025, 050, 075, 100, 125
    - Multiplier 50: Patterns end in 000, 050, 100, 150, 200, 250...
    - Multiplier 250: Patterns end in 000, 250, 500, 750, 1000...
    
    Args:
        inv_id: Optional specific investor ID to process
        
    Returns:
        dict: Statistics about the processing
    """
    print(f"\n{'='*10} 💰  DYNAMIC SYMBOL PRICE COLLECTION {'='*10}")
    if inv_id:
        print(f" Processing single investor: {inv_id}")
    
    # Statistics for this run
    stats = {
        "investor_id": inv_id if inv_id else "all",
        "total_symbols": 0,
        "successful_symbols": 0,
        "failed_symbols": 0,
        "total_categories": 0,
        "symbols_mapped": 0,
        "symbols_unchanged": 0,
        "signals_generated": False,
        "grid_configuration": {}
    }

    def clean(s): 
        """Clean symbol string by removing special chars and converting to uppercase"""
        if s is None:
            return ""
        return str(s).replace(" ", "").replace("_", "").replace("/", "").replace(".", "").upper()
    
    def get_grid_configuration(config):
        """
        Extract dynamic grid configuration from account management.
        
        Args:
            config: Loaded account management configuration
            
        Returns:
            tuple: (grid_levels, grid_multiplier, bid_order_type, ask_order_type, risk_reward_value)
        """
        grid_prices_setup = config.get("grid_prices_setup", {})
        selected_risk_reward = config.get("selected_risk_reward", [2])
        
        # REQUIRED: grid_levels and grid_multiplier must be present
        grid_levels = grid_prices_setup.get("grid_levels")
        grid_multiplier = grid_prices_setup.get("grid_multiplier")
        
        # Validation - if missing, don't process
        if grid_levels is None:
            raise ValueError("❌ CRITICAL: 'grid_levels' not defined in grid_prices_setup. Cannot process.")
        if grid_multiplier is None:
            raise ValueError("❌ CRITICAL: 'grid_multiplier' not defined in grid_prices_setup. Cannot process.")
        
        # Optional with defaults
        bid_order_type = grid_prices_setup.get("bid_prices_order_type", "buy_stop")
        ask_order_type = grid_prices_setup.get("ask_prices_order_type", "sell_stop")
        
        risk_reward_value = selected_risk_reward[0] if isinstance(selected_risk_reward, list) and selected_risk_reward else 2
        
        print(f"  📋 DYNAMIC Grid Configuration:")
        print(f"    • Grid Levels: {grid_levels} (per side)")
        print(f"    • Grid Multiplier: {grid_multiplier}")
        print(f"    • Pattern Unit: {grid_multiplier}")
        print(f"    • Bid Prices Order Type: {bid_order_type}")
        print(f"    • Ask Prices Order Type: {ask_order_type}")
        print(f"    • Selected Risk/Reward: {risk_reward_value}")
        
        # Store in stats for return
        stats["grid_configuration"] = {
            "levels": grid_levels,
            "multiplier": grid_multiplier,
            "bid_order_type": bid_order_type,
            "ask_order_type": ask_order_type,
            "risk_reward": risk_reward_value
        }
        
        return grid_levels, grid_multiplier, bid_order_type, ask_order_type, risk_reward_value
    
    def get_risk_requirement(config, account_balance):
        """
        Get risk requirement based on account balance from account_balance_default_risk_management.
        
        Args:
            config: Loaded account management configuration
            account_balance: Current account balance
            
        Returns:
            tuple: (target_risk_min, target_risk_max, target_risk_value)
        """
        risk_management = config.get("account_balance_default_risk_management", {})
        
        if not risk_management:
            print(f"        ⚠️  No risk management configuration found - using default 10 USD risk")
            return 10.0, 10.99, 10.0  # Default fallback
        
        # Find matching range for account balance
        target_risk_value = None
        target_risk_min = None
        target_risk_max = None
        
        for range_str, risk_value in risk_management.items():
            if "_risk" in range_str:
                # Parse range like "100-109.99_risk"
                range_part = range_str.replace("_risk", "")
                if "-" in range_part:
                    min_val, max_val = range_part.split("-")
                    try:
                        min_balance = float(min_val)
                        max_balance = float(max_val)
                        
                        if min_balance <= account_balance <= max_balance:
                            target_risk_value = float(risk_value)
                            target_risk_min = float(risk_value)
                            target_risk_max = float(risk_value) + 0.99  # Add 99 cents tolerance
                            break
                    except ValueError:
                        continue
        
        if target_risk_value is None:
            print(f"        ⚠️  No matching risk range found for balance {account_balance} - using default")
            return 10.0, 10.99, 10.0  # Default fallback
        
        print(f"        📊 Risk requirement from account management:")
        print(f"          • Account balance: ${account_balance:.2f}")
        print(f"          • Target risk: ${target_risk_min:.2f} - ${target_risk_max:.2f}")
        print(f"          • Base risk value: {target_risk_value}")
        
        return target_risk_min, target_risk_max, target_risk_value
    
    def fetch_current_prices(symbol, resolution_cache):
        """
        Fetch current bid/ask prices for a symbol using external helper for normalization
        and cache for efficiency.
        
        Args:
            symbol: Raw symbol to fetch prices for
            resolution_cache: Cache dictionary for symbol resolution
            
        Returns:
            tuple: (success, normalized_symbol, current_bid, current_ask, current_price, tick, symbol_info, error_message)
        """
        try:
            # Check Cache First
            if symbol in resolution_cache:
                res = resolution_cache[symbol]
                normalized_symbol = res['broker_sym']
                symbol_info = res['info']
                
                if symbol_info is None:
                    return False, None, None, None, None, None, None, f"Symbol '{symbol}' previously failed to resolve"
            else:
                normalized_symbol = get_normalized_symbol(symbol)
                symbol_info = mt5.symbol_info(normalized_symbol)
                resolution_cache[symbol] = {'broker_sym': normalized_symbol, 'info': symbol_info}
                
                if symbol_info:
                    if normalized_symbol != symbol:
                        print(f"    └─ ✅ {symbol} -> {normalized_symbol} (Mapped & Cached)")
                        stats["symbols_mapped"] += 1
                    else:
                        print(f"    └─ ✅ {symbol} (Direct match, cached)")
                        stats["symbols_unchanged"] += 1
                else:
                    print(f"    └─  MT5: '{normalized_symbol}' (from '{symbol}') not found in MarketWatch")
                    return False, None, None, None, None, None, None, f"Symbol '{normalized_symbol}' not found in MarketWatch"
            
            if not symbol_info:
                return False, None, None, None, None, None, None, f"Symbol info not available for {normalized_symbol}"
            
            if not mt5.symbol_select(normalized_symbol, True):
                return False, normalized_symbol, None, None, None, None, None, f"Failed to select symbol: {normalized_symbol}"
            
            tick = mt5.symbol_info_tick(normalized_symbol)
            if not tick:
                return False, normalized_symbol, None, None, None, None, None, "Tick data not available"
            
            current_bid = tick.bid
            current_ask = tick.ask
            current_price = (current_bid + current_ask) / 2
            
            digits = symbol_info.digits
            print(f"✅ {normalized_symbol} (Bid: {current_bid:.{digits}f}, Ask: {current_ask:.{digits}f})")
            
            return True, normalized_symbol, current_bid, current_ask, current_price, tick, symbol_info, None
            
        except Exception as e:
            return False, None, None, None, None, None, None, str(e)
    
    def get_min_volume(symbol_info):
        """Get the minimum allowed volume for a symbol from the broker."""
        try:
            volume_min = symbol_info.volume_min
            volume_step = symbol_info.volume_step
            
            print(f"        📊 Live volume information:")
            print(f"          • Minimum volume: {volume_min}")
            print(f"          • Volume step: {volume_step}")
            print(f"          • Maximum volume: {symbol_info.volume_max}")
            
            return volume_min, volume_step
            
        except Exception as e:
            print(f"        ⚠️  Could not get minimum volume: {e}")
            return 0.01, 0.01
    
    def calculate_risk_in_usd(symbol_info, entry_price, exit_price, volume, account_currency):
        """Calculate the risk amount in USD for a given trade level."""
        try:
            risk_distance_points = abs(exit_price - entry_price)
            tick_size = symbol_info.trade_tick_size
            tick_value = symbol_info.trade_tick_value
            risk_in_account_currency = (risk_distance_points / tick_size) * tick_value * volume
            
            if account_currency != 'USD':
                usd_symbol = f"{account_currency}USD"
                if mt5.symbol_select(usd_symbol, True):
                    usd_tick = mt5.symbol_info_tick(usd_symbol)
                    if usd_tick:
                        conversion_rate = usd_tick.bid or 1.0
                        risk_in_usd = risk_in_account_currency * conversion_rate
                    else:
                        risk_in_usd = risk_in_account_currency
                else:
                    usd_symbol = f"USD{account_currency}"
                    if mt5.symbol_select(usd_symbol, True):
                        usd_tick = mt5.symbol_info_tick(usd_symbol)
                        if usd_tick:
                            conversion_rate = 1.0 / usd_tick.ask if usd_tick.ask > 0 else 1.0
                            risk_in_usd = risk_in_account_currency * conversion_rate
                        else:
                            risk_in_usd = risk_in_account_currency
                    else:
                        risk_in_usd = risk_in_account_currency
            else:
                risk_in_usd = risk_in_account_currency
            
            return risk_in_usd
            
        except Exception as e:
            print(f"        ⚠️  Could not calculate risk in USD: {e}")
            return 0.0
    
    def scale_volume_to_target_risk(symbol_info, entry_price, exit_price, min_volume, volume_step, 
                                   account_currency, target_risk_min, target_risk_max, max_iterations=100):
        """Scale volume to achieve target risk range."""
        print(f"        📊 Scaling volume to match target risk range:")
        print(f"          • Target risk range: ${target_risk_min:.2f} - ${target_risk_max:.2f}")
        print(f"          • Starting volume: {min_volume}")
        
        current_volume = min_volume
        best_volume = min_volume
        best_risk = 0
        scaling_attempts = []
        
        for iteration in range(max_iterations):
            current_risk = calculate_risk_in_usd(
                symbol_info, entry_price, exit_price, current_volume, account_currency
            )
            
            scaling_attempts.append({
                "volume": current_volume,
                "risk_usd": round(current_risk, 2)
            })
            
            print(f"          • Attempt {iteration + 1}: Volume={current_volume}, Risk=${current_risk:.2f}")
            
            if target_risk_min <= current_risk <= target_risk_max:
                print(f"          ✅ Target risk achieved with volume {current_volume} (${current_risk:.2f})")
                return current_volume, round(current_risk, 2), scaling_attempts
            elif current_risk > target_risk_max:
                if iteration == 0:
                    print(f"          ⚠️  Minimum volume already exceeds target range")
                    return min_volume, round(current_risk, 2), scaling_attempts
                else:
                    print(f"          ✅ Using previous volume {best_volume} (${best_risk:.2f}) - below target")
                    return best_volume, round(best_risk, 2), scaling_attempts
            else:
                best_volume = current_volume
                best_risk = current_risk
                current_volume = round(current_volume + volume_step, 2)
        
        print(f"          ⚠️  Max iterations reached. Using best volume {best_volume} (${best_risk:.2f})")
        return best_volume, round(best_risk, 2), scaling_attempts
    
    def generate_pattern_levels(price, direction, num_levels, multiplier, price_digits=None):
        """
        DYNAMIC pattern level generator based on multiplier.
        
        Args:
            price: Current price
            direction: 'below' or 'above'
            num_levels: Number of levels to generate
            multiplier: Pattern increment (25, 50, 250, etc.)
            price_digits: Price digits for rounding
            
        Returns:
            list: Generated price levels
        """
        # Determine if integer-based (>=1000) or fractional-based
        if price >= 1000:
            # Integer-based prices (Gold, indices)
            price_int = int(price)
            base_int = (price_int // multiplier) * multiplier
            
            print(f"        📊 Generating integer-based patterns (multiplier={multiplier}):")
            print(f"          • Original price: {price}")
            print(f"          • Integer value: {price_int}")
            print(f"          • Base integer: {base_int}")
            print(f"          • Pattern unit: {multiplier}")
            
            pattern_levels = []
            if direction == 'below':
                for i in range(num_levels):
                    level_int = base_int - (i * multiplier)
                    pattern_levels.append(float(level_int))
            else:  # above
                for i in range(num_levels):
                    level_int = base_int + ((i + 1) * multiplier)
                    pattern_levels.append(float(level_int))
            
            return pattern_levels
            
        else:
            # Fractional-based prices (Forex)
            # Determine multiplier based on price digits
            if price_digits and price_digits >= 5:
                scale = 100000  # 5-digit forex
            elif price_digits and price_digits == 4:
                scale = 10000   # 4-digit forex
            else:
                scale = 10000   # Default
            
            price_scaled = int(round(price * scale))
            base_scaled = (price_scaled // multiplier) * multiplier
            
            print(f"        📊 Generating fractional-based patterns (multiplier={multiplier}):")
            print(f"          • Original price: {price}")
            print(f"          • Scaled integer: {price_scaled}")
            print(f"          • Base scaled: {base_scaled}")
            print(f"          • Scale factor: {scale}")
            print(f"          • Pattern unit: {multiplier}")
            
            pattern_levels = []
            if direction == 'below':
                for i in range(num_levels):
                    level_int = base_scaled - (i * multiplier)
                    level_price = level_int / scale
                    pattern_levels.append(level_price)
            else:  # above
                for i in range(num_levels):
                    level_int = base_scaled + ((i + 1) * multiplier)
                    level_price = level_int / scale
                    pattern_levels.append(level_price)
            
            return pattern_levels
    
    def generate_exit_and_tp_prices(entry_price, order_type, risk_reward, multiplier, price_digits):
        """
        Generate exit and TP prices based on order type, risk/reward ratio, and multiplier.
        """
        if entry_price >= 1000:  # Integer-based
            pattern_unit = multiplier
            entry_scaled = int(entry_price)
            base_scaled = (entry_scaled // pattern_unit) * pattern_unit
            
            if order_type in ["sell_stop", "sell_limit"]:
                exit_scaled = base_scaled + pattern_unit
                exit_price = float(exit_scaled)
                risk_distance = exit_price - entry_price
                tp_price = entry_price - (risk_distance * risk_reward)
            elif order_type in ["buy_stop", "buy_limit"]:
                exit_scaled = base_scaled - pattern_unit
                exit_price = float(exit_scaled)
                risk_distance = entry_price - exit_price
                tp_price = entry_price + (risk_distance * risk_reward)
            else:
                exit_price = entry_price
                tp_price = entry_price
                
        else:  # Fractional-based
            if price_digits >= 5:
                scale = 100000
                pattern_unit = multiplier
            elif price_digits == 4:
                scale = 10000
                pattern_unit = multiplier // 10 if multiplier >= 10 else multiplier
            else:
                scale = 10000
                pattern_unit = multiplier
            
            entry_scaled = int(round(entry_price * scale))
            base_scaled = (entry_scaled // pattern_unit) * pattern_unit
            
            if order_type in ["sell_stop", "sell_limit"]:
                exit_scaled = base_scaled + pattern_unit
                exit_price = exit_scaled / scale
                risk_distance = exit_price - entry_price
                tp_price = entry_price - (risk_distance * risk_reward)
            elif order_type in ["buy_stop", "buy_limit"]:
                exit_scaled = base_scaled - pattern_unit
                exit_price = exit_scaled / scale
                risk_distance = entry_price - exit_price
                tp_price = entry_price + (risk_distance * risk_reward)
            else:
                exit_price = entry_price
                tp_price = entry_price
        
        # Round appropriately
        if entry_price >= 1000:
            exit_price = round(exit_price, 2)
            tp_price = round(tp_price, 2)
        else:
            exit_price = round(exit_price, price_digits)
            tp_price = round(tp_price, price_digits)
        
        return exit_price, tp_price
    
    def invert_order_type(order_type):
        """Invert order type (buy <-> sell, stop/limit preserved)."""
        order_type_map = {
            "buy_stop": "sell_stop",
            "sell_stop": "buy_stop",
            "buy_limit": "sell_limit",
            "sell_limit": "buy_limit"
        }
        return order_type_map.get(order_type, order_type)
    
    def calculate_counter_tp(entry_price, exit_price, order_type, risk_reward, price_digits):
        """Calculate TP for counter order based on inverted position."""
        if order_type in ["sell_stop", "sell_limit"]:
            risk_distance = exit_price - entry_price
            tp_price = entry_price - (risk_distance * risk_reward)
        elif order_type in ["buy_stop", "buy_limit"]:
            risk_distance = entry_price - exit_price
            tp_price = entry_price + (risk_distance * risk_reward)
        else:
            tp_price = entry_price
        
        if entry_price >= 1000:
            tp_price = round(tp_price, 2)
        else:
            tp_price = round(tp_price, price_digits)
        
        return tp_price
    
    def generate_order_counter(level_data, price_digits):
        """Generate a counter order for a given grid level."""
        original_order_type = level_data.get("order_type", "")
        inverted_order_type = invert_order_type(original_order_type)
        counter_entry = level_data.get("exit")
        counter_exit = level_data.get("entry")
        risk_reward = level_data.get("risk_reward", 1)
        counter_tp = calculate_counter_tp(
            counter_entry, counter_exit, inverted_order_type, risk_reward, price_digits
        )
        
        counter_order = {
            "entry": counter_entry,
            "exit": counter_exit,
            "tp": counter_tp,
            "volume": level_data.get("volume"),
            "risk_in_usd": level_data.get("risk_in_usd"),
            "min_volume_risk": level_data.get("min_volume_risk"),
            "order_type": inverted_order_type,
            "risk_reward": risk_reward
        }
        
        if "scaling_attempts" in level_data:
            counter_order["scaling_attempts"] = level_data["scaling_attempts"]
        
        return counter_order
    
    def add_order_counters_to_grid_levels(grid_bid_levels, grid_ask_levels, digits):
        """Add order counters to both bid and ask grid levels."""
        print(f"\n      📊 GENERATING ORDER COUNTERS:")
        
        for level in grid_bid_levels:
            level["order_counter"] = generate_order_counter(level, digits)
        
        for level in grid_ask_levels:
            level["order_counter"] = generate_order_counter(level, digits)
        
        print(f"        • Added counters to {len(grid_bid_levels)} sell levels")
        print(f"        • Added counters to {len(grid_ask_levels)} buy levels")
        
        return grid_bid_levels, grid_ask_levels

    def create_grid_orders_structure(bid_pattern_levels, ask_pattern_levels, bid_order_type, ask_order_type, 
                                    risk_reward_value, digits, min_volume, volume_step, symbol_info, 
                                    account_currency, target_risk_min, target_risk_max, multiplier):
        """
        Create enhanced grid orders structure with dynamic configuration.
        """
        print(f"\n      📊 Creating grid orders structure with exit/TP prices:")
        print(f"      📊 Using multiplier: {multiplier} for pattern generation")
        print(f"      📊 Adding live broker volume: min={min_volume}, step={volume_step}")
        print(f"      📊 Calculating risk in USD for each level")
        print(f"      📊 Target risk range: ${target_risk_min:.2f} - ${target_risk_max:.2f}")
        
        # Create sell levels (below bid)
        grid_bid_levels = []
        for level_price in bid_pattern_levels:
            exit_price, tp_price = generate_exit_and_tp_prices(
                level_price, ask_order_type, risk_reward_value, multiplier, digits
            )
            
            optimal_volume, actual_risk, scaling_attempts = scale_volume_to_target_risk(
                symbol_info, level_price, exit_price, min_volume, volume_step,
                account_currency, target_risk_min, target_risk_max
            )
            
            grid_bid_levels.append({
                "entry": level_price,
                "exit": exit_price,
                "tp": tp_price,
                "volume": optimal_volume,
                "risk_in_usd": actual_risk,
                "min_volume_risk": scaling_attempts[0]["risk_usd"] if scaling_attempts else 0,
                "scaling_attempts": scaling_attempts,
                "order_type": ask_order_type,
                "risk_reward": risk_reward_value
            })
        
        # Create buy levels (above ask)
        grid_ask_levels = []
        for level_price in ask_pattern_levels:
            exit_price, tp_price = generate_exit_and_tp_prices(
                level_price, bid_order_type, risk_reward_value, multiplier, digits
            )
            
            optimal_volume, actual_risk, scaling_attempts = scale_volume_to_target_risk(
                symbol_info, level_price, exit_price, min_volume, volume_step,
                account_currency, target_risk_min, target_risk_max
            )
            
            grid_ask_levels.append({
                "entry": level_price,
                "exit": exit_price,
                "tp": tp_price,
                "volume": optimal_volume,
                "risk_in_usd": actual_risk,
                "min_volume_risk": scaling_attempts[0]["risk_usd"] if scaling_attempts else 0,
                "scaling_attempts": scaling_attempts,
                "order_type": bid_order_type,
                "risk_reward": risk_reward_value
            })
        
        # Selection flags
        if grid_bid_levels:
            max_entry_bid = max(level["entry"] for level in grid_bid_levels)
            for level in grid_bid_levels:
                level["selected_bid"] = (level["entry"] == max_entry_bid)
                if level["selected_bid"]:
                    print(f"        • Selected BID level at {max_entry_bid:.{digits}f} as oldest")
        
        if grid_ask_levels:
            min_entry_ask = min(level["entry"] for level in grid_ask_levels)
            for level in grid_ask_levels:
                level["selected_ask"] = (level["entry"] == min_entry_ask)
                if level["selected_ask"]:
                    print(f"        • Selected ASK level at {min_entry_ask:.{digits}f} as youngest")
        
        # Add counters
        grid_bid_levels, grid_ask_levels = add_order_counters_to_grid_levels(
            grid_bid_levels, grid_ask_levels, digits
        )
        
        print(f"        • Grid sell levels: {len(grid_bid_levels)} levels (with counters)")
        print(f"        • Grid buy levels: {len(grid_ask_levels)} levels (with counters)")
        print(f"        • Risk/Reward: {risk_reward_value}:1 for all levels")
        
        return grid_bid_levels, grid_ask_levels
   
    def save_individual_symbol_price(prices_dir, symbol, price_data):
        """Save individual symbol price data to JSON file."""
        symbol_file = prices_dir / f"{symbol}.json"
        with open(symbol_file, 'w', encoding='utf-8') as f:
            json.dump(price_data, f, indent=4)
    
    def save_all_symbols_prices(prices_dir, all_symbols_price_data, acc_info, bid_order_type, ask_order_type, 
                                risk_reward_value, target_risk_range, total_categories, total_symbols, 
                                successful_symbols, failed_symbols, category_results, grid_levels, grid_multiplier):
        """Save all symbols' price data to a single symbols_prices.json file."""
        symbols_file = prices_dir / "symbols_prices.json"
        
        final_data = {
            "account_type": "",
            "account_login": acc_info.login,
            "account_server": acc_info.server,
            "account_balance": acc_info.balance,
            "account_currency": acc_info.currency,
            "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "grid_configuration": {
                "levels": grid_levels,
                "multiplier": grid_multiplier,
                "bid_order_type": bid_order_type,
                "ask_order_type": ask_order_type,
                "risk_reward": risk_reward_value
            },
            "target_risk_range_usd": {
                "min": target_risk_range[0],
                "max": target_risk_range[1],
                "base": target_risk_range[2]
            },
            "total_categories": total_categories,
            "total_symbols": total_symbols,
            "successful_symbols": successful_symbols,
            "failed_symbols": failed_symbols,
            "success_rate_percent": round((successful_symbols/total_symbols*100), 1) if total_symbols > 0 else 0,
            "categories": category_results,
            **all_symbols_price_data
        }
        
        with open(symbols_file, 'w', encoding='utf-8') as f:
            json.dump(final_data, f, indent=4, default=str)
        
        print(f"    📁 Saved all symbol prices to: {symbols_file}")
        print(f"    📊 Total symbols in file: {len(all_symbols_price_data)}")
    
    def save_category_summary(prices_dir, category, symbols, category_price_data, 
                             category_symbols_success, category_symbols_failed, 
                             login_id, bid_order_type, ask_order_type, risk_reward_value, 
                             target_risk_range, grid_levels, grid_multiplier):
        """Save category summary with all symbols data."""
        category_file = prices_dir / f"{category}_prices.json"
        category_summary = {
            "category": category,
            "account_type": "",
            "account_login": login_id,
            "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_symbols": len(symbols),
            "successful_symbols": category_symbols_success,
            "failed_symbols": category_symbols_failed,
            "grid_configuration": {
                "levels": grid_levels,
                "multiplier": grid_multiplier,
                "bid_order_type": bid_order_type,
                "ask_order_type": ask_order_type,
                "risk_reward": risk_reward_value
            },
            "target_risk_range_usd": {
                "min": target_risk_range[0],
                "max": target_risk_range[1],
                "base": target_risk_range[2]
            },
            "symbols": category_price_data
        }
        with open(category_file, 'w', encoding='utf-8') as f:
            json.dump(category_summary, f, indent=4)
    
    def filter_signals_with_counters(prices_dir, category_price_data, symbols_dict, 
                                     target_risk_min, target_risk_max, 
                                     bid_order_type, ask_order_type, risk_reward_value, 
                                     account_balance, account_currency, grid_levels, grid_multiplier):
        """Filter orders that meet the risk requirement and save them to signals.json."""
        print(f"\n      📊 FILTERING SIGNALS WITH COUNTERS - Risk Requirement: ≤ ${target_risk_max:.2f} AND > $0")
        
        signals_data = {
            "account_type": "",
            "account_balance": account_balance,
            "account_currency": account_currency,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "risk_requirement": {
                "min_usd": target_risk_min,
                "max_usd": target_risk_max,
                "filter_criteria": f"$0 < risk_in_usd ≤ ${target_risk_max:.2f}"
            },
            "grid_configuration": {
                "levels": grid_levels,
                "multiplier": grid_multiplier,
                "bid_order_type": bid_order_type,
                "ask_order_type": ask_order_type,
                "risk_reward": risk_reward_value
            },
            "categories": {},
            "summary": {
                "total_symbols_with_signals": 0,
                "total_bid_orders": 0,
                "total_ask_orders": 0,
                "total_counter_orders": 0,
                "total_orders": 0
            }
        }
        
        total_bid_orders = 0
        total_ask_orders = 0
        total_counter_orders = 0
        symbols_with_signals = 0
        
        for category, symbols in symbols_dict.items():
            category_signals = {}
            category_bid_count = 0
            category_ask_count = 0
            category_counter_count = 0
            
            for raw_symbol in symbols:
                normalized_symbol = get_normalized_symbol(raw_symbol)
                if normalized_symbol in category_price_data:
                    price_data = category_price_data[normalized_symbol]
                    
                    filtered_bid_levels = []
                    for level in price_data["grid_orders"]["bid_levels"]:
                        if level["risk_in_usd"] <= target_risk_max and level["risk_in_usd"] > 0:
                            filtered_level = {
                                "entry": level["entry"],
                                "exit": level["exit"],
                                "tp": level["tp"],
                                "volume": level["volume"],
                                "risk_in_usd": level["risk_in_usd"],
                                "min_volume_risk": level["min_volume_risk"],
                                "order_type": level["order_type"],
                                "risk_reward": level["risk_reward"],
                                "order_counter": level["order_counter"]
                            }
                            filtered_bid_levels.append(filtered_level)
                    
                    filtered_ask_levels = []
                    for level in price_data["grid_orders"]["ask_levels"]:
                        if level["risk_in_usd"] <= target_risk_max and level["risk_in_usd"] > 0:
                            filtered_level = {
                                "entry": level["entry"],
                                "exit": level["exit"],
                                "tp": level["tp"],
                                "volume": level["volume"],
                                "risk_in_usd": level["risk_in_usd"],
                                "min_volume_risk": level["min_volume_risk"],
                                "order_type": level["order_type"],
                                "risk_reward": level["risk_reward"],
                                "order_counter": level["order_counter"]
                            }
                            filtered_ask_levels.append(filtered_level)
                    
                    if filtered_bid_levels or filtered_ask_levels:
                        category_signals[raw_symbol] = {
                            "digits": price_data["digits"],
                            "current_prices": price_data["current_prices"],
                            "bid_orders": filtered_bid_levels,
                            "ask_orders": filtered_ask_levels
                        }
                        
                        symbols_with_signals += 1
                        category_bid_count += len(filtered_bid_levels)
                        category_ask_count += len(filtered_ask_levels)
                        category_counter_count += len(filtered_bid_levels) + len(filtered_ask_levels)
                        
                        total_bid_orders += len(filtered_bid_levels)
                        total_ask_orders += len(filtered_ask_levels)
                        total_counter_orders += len(filtered_bid_levels) + len(filtered_ask_levels)
            
            if category_signals:
                signals_data["categories"][category] = {
                    "symbols": category_signals,
                    "summary": {
                        "symbols_with_signals": len(category_signals),
                        "bid_orders": category_bid_count,
                        "ask_orders": category_ask_count,
                        "counter_orders": category_counter_count,
                        "total_orders": category_bid_count + category_ask_count + category_counter_count
                    }
                }
        
        signals_data["summary"]["total_symbols_with_signals"] = symbols_with_signals
        signals_data["summary"]["total_bid_orders"] = total_bid_orders
        signals_data["summary"]["total_ask_orders"] = total_ask_orders
        signals_data["summary"]["total_counter_orders"] = total_counter_orders
        signals_data["summary"]["total_orders"] = total_bid_orders + total_ask_orders + total_counter_orders
        
        signals_file = prices_dir / "signals.json"
        with open(signals_file, 'w', encoding='utf-8') as f:
            json.dump(signals_data, f, indent=4)
        
        print(f"      📊 SIGNALS WITH COUNTERS SUMMARY:")
        print(f"        • Symbols with signals: {symbols_with_signals}")
        print(f"        • Total bid orders: {total_bid_orders}")
        print(f"        • Total ask orders: {total_ask_orders}")
        print(f"        • Total counter orders: {total_counter_orders}")
        print(f"        • Total orders: {total_bid_orders + total_ask_orders + total_counter_orders}")
        print(f"        • Filter criteria: $0 < risk_in_usd ≤ ${target_risk_max:.2f}")
        
        stats["signals_generated"] = True
        return signals_data, signals_file
    
    def rearrange_orders_with_counters(signals_file_path):
        """
        Rearrange orders by extracting order_counter entries and placing them as separate order objects.
        
        This function takes the signals.json structure and transforms it so that each
        order_counter is moved out of its parent order and becomes a standalone order
        at the same level as the original order.
        
        Args:
            signals_file_path: Path to signals.json file
            
        Returns:
            dict: Transformed signals data with rearranged orders
        """
        print(f"\n      🔄 REARRANGING ORDERS - Extracting counter orders...")
        
        # Load the signals data
        with open(signals_file_path, 'r', encoding='utf-8') as f:
            signals_data = json.load(f)
        
        # Create a deep copy to avoid modifying original
        rearranged_signals = {
            "account_type": signals_data.get("account_type", ""),
            "account_balance": signals_data.get("account_balance", 0),
            "account_currency": signals_data.get("account_currency", "USD"),
            "generated_at": signals_data.get("generated_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "risk_requirement": signals_data.get("risk_requirement", {}),
            "grid_configuration": signals_data.get("grid_configuration", {}),
            "categories": {},
            "summary": {
                "total_symbols_with_signals": 0,
                "total_bid_orders": 0,
                "total_ask_orders": 0,
                "total_orders": 0
            }
        }
        
        # Process each category
        for category_name, category_data in signals_data.get("categories", {}).items():
            rearranged_category = {
                "symbols": {},
                "summary": {
                    "symbols_with_signals": 0,
                    "bid_orders": 0,
                    "ask_orders": 0,
                    "total_orders": 0
                }
            }
            
            category_bid_total = 0
            category_ask_total = 0
            category_symbols_count = 0
            
            for symbol, symbol_data in category_data.get("symbols", {}).items():
                # Process bid_orders
                new_bid_orders = []
                if "bid_orders" in symbol_data:
                    for order in symbol_data["bid_orders"]:
                        # Add the original order without order_counter
                        order_copy = {k: v for k, v in order.items() if k != "order_counter"}
                        new_bid_orders.append(order_copy)
                        
                        # Add the counter order as a separate order if it exists
                        if "order_counter" in order:
                            counter_order = order["order_counter"]
                            new_bid_orders.append(counter_order)
                
                # Process ask_orders
                new_ask_orders = []
                if "ask_orders" in symbol_data:
                    for order in symbol_data["ask_orders"]:
                        # Add the original order without order_counter
                        order_copy = {k: v for k, v in order.items() if k != "order_counter"}
                        new_ask_orders.append(order_copy)
                        
                        # Add the counter order as a separate order if it exists
                        if "order_counter" in order:
                            counter_order = order["order_counter"]
                            new_ask_orders.append(counter_order)
                
                # Only include symbol if it has orders
                if new_bid_orders or new_ask_orders:
                    rearranged_category["symbols"][symbol] = {
                        "digits": symbol_data.get("digits", 0),
                        "current_prices": symbol_data.get("current_prices", {}),
                        "bid_orders": new_bid_orders,
                        "ask_orders": new_ask_orders
                    }
                    
                    category_symbols_count += 1
                    category_bid_total += len(new_bid_orders)
                    category_ask_total += len(new_ask_orders)
            
            # Update category summary
            rearranged_category["summary"]["symbols_with_signals"] = category_symbols_count
            rearranged_category["summary"]["bid_orders"] = category_bid_total
            rearranged_category["summary"]["ask_orders"] = category_ask_total
            rearranged_category["summary"]["total_orders"] = category_bid_total + category_ask_total
            
            rearranged_signals["categories"][category_name] = rearranged_category
        
        # Update main summary
        total_symbols = 0
        total_bid_orders = 0
        total_ask_orders = 0
        
        for category_data in rearranged_signals["categories"].values():
            total_symbols += category_data["summary"]["symbols_with_signals"]
            total_bid_orders += category_data["summary"]["bid_orders"]
            total_ask_orders += category_data["summary"]["ask_orders"]
        
        rearranged_signals["summary"]["total_symbols_with_signals"] = total_symbols
        rearranged_signals["summary"]["total_bid_orders"] = total_bid_orders
        rearranged_signals["summary"]["total_ask_orders"] = total_ask_orders
        rearranged_signals["summary"]["total_orders"] = total_bid_orders + total_ask_orders
        
        # Save rearranged file
        rearranged_path = signals_file_path.parent / f"signals.json"
        with open(rearranged_path, 'w', encoding='utf-8') as f:
            json.dump(rearranged_signals, f, indent=4)
        
        print(f"      ✅ Rearranged signals saved to: {rearranged_path}")
        print(f"      📊 REARRANGED SUMMARY:")
        print(f"        • Symbols with signals: {total_symbols}")
        print(f"        • Total bid orders: {total_bid_orders}")
        print(f"        • Total ask orders: {total_ask_orders}")
        print(f"        • Total orders: {total_bid_orders + total_ask_orders}")
        print(f"        • Note: Counter orders have been extracted as standalone orders")
        
        return rearranged_signals
    
    def print_investor_summary(user_brokerid, total_categories, total_symbols, successful_symbols, 
                              failed_symbols, bid_order_type, ask_order_type, risk_reward_value, 
                              target_risk_range, prices_dir, grid_levels, grid_multiplier):
        """Print summary for an investor."""
        print(f"\n  📊  INVESTOR SUMMARY: {user_brokerid}")
        print(f"    • Grid Configuration: {grid_levels} levels, multiplier={grid_multiplier}")
        print(f"    • Categories processed: {total_categories}")
        print(f"    • Total symbols: {total_symbols}")
        print(f"    • Successful: {successful_symbols}")
        print(f"    • Failed: {failed_symbols}")
        print(f"    • Success rate: {(successful_symbols/total_symbols*100):.1f}%")
        print(f"    • Order Types: Bid={bid_order_type}, Ask={ask_order_type}, R:R={risk_reward_value}")
        print(f"    • Target Risk Range: ${target_risk_range[0]:.2f} - ${target_risk_range[1]:.2f} USD")
        print(f"    • Price files saved to: {prices_dir}")
    
    # Main processing
    if inv_id:
        broker_cfg = usersdictionary.get(inv_id)
        if not broker_cfg:
            print(f" [{inv_id}]  No broker config found")
            return stats
        
        inv_root = Path(INV_PATH) / inv_id
        acc_mgmt_path = inv_root / "accountmanagement.json"
        
        if not acc_mgmt_path.exists():
            print(f" [{inv_id}] ⚠️ Account management file not found")
            return stats
        
        try:
            with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Extract symbols dictionary
            symbols_dict = config.get("symbols_dictionary", {})
            if not symbols_dict:
                print(f" [{inv_id}] ⚠️ No symbols_dictionary found")
                return stats
            
            # Get dynamic grid configuration (REQUIRED)
            try:
                grid_levels, grid_multiplier, bid_order_type, ask_order_type, risk_reward_value = get_grid_configuration(config)
            except ValueError as e:
                print(f" [{inv_id}] {e}")
                return stats
            
            # Get account info
            acc_info = mt5.account_info()
            if not acc_info:
                print(f" [{inv_id}]  Failed to get account info - MT5 not initialized?")
                return stats
            
            account_currency = acc_info.currency
            account_balance = acc_info.balance
            
            # Get risk requirement
            target_risk_min, target_risk_max, target_risk_base = get_risk_requirement(config, account_balance)
            target_risk_range = (target_risk_min, target_risk_max, target_risk_base)
            
            print(f"\n  📊  Account Details:")
            print(f"    • Balance: ${account_balance:,.2f}")
            print(f"    • Equity: ${acc_info.equity:,.2f}")
            print(f"    • Server: {acc_info.server}")
            print(f"    • Currency: {account_currency}")
            print(f"    • Target Risk Range: ${target_risk_min:.2f} - ${target_risk_max:.2f}")
            
            # Create prices directory
            prices_dir = inv_root / "prices"
            prices_dir.mkdir(exist_ok=True)
            print(f"\n  📁 Prices will be saved to: {prices_dir}")
            
            # Track statistics
            total_categories = len(symbols_dict)
            total_symbols = 0
            successful_symbols = 0
            failed_symbols = 0
            category_results = {}
            all_category_price_data = {}
            all_symbols_price_data = {}
            resolution_cache = {}
            
            # Generate pattern descriptions for logging
            pattern_desc = []
            for i in range(grid_levels):
                pattern_desc.append(f"{i * grid_multiplier:03d}")
            print(f"\n  🎯 DYNAMIC PATTERN: Levels will end in: {', '.join(pattern_desc)}")
            
            # Process each category
            for category, symbols in symbols_dict.items():
                print(f"\n  📂 Category: {category.upper()} ({len(symbols)} symbols)")
                category_symbols_success = 0
                category_symbols_failed = 0
                category_price_data = {}
                
                for raw_symbol in symbols:
                    total_symbols += 1
                    print(f"    🔍 Processing: {raw_symbol}...", end=" ")
                    
                    success, normalized_symbol, current_bid, current_ask, current_price, tick, symbol_info, error = fetch_current_prices(
                        raw_symbol, resolution_cache
                    )
                    
                    if not success:
                        print(f" {error[:50] if error else 'Unknown error'}")
                        failed_symbols += 1
                        category_symbols_failed += 1
                        continue
                    
                    digits = symbol_info.digits
                    
                    # Generate pattern levels dynamically
                    print(f"\n      📊 Generating pattern-based levels (multiplier={grid_multiplier}, {grid_levels} levels):")
                    bid_pattern_levels = generate_pattern_levels(current_bid, 'below', grid_levels, grid_multiplier, digits)
                    ask_pattern_levels = generate_pattern_levels(current_ask, 'above', grid_levels, grid_multiplier, digits)
                    
                    if not bid_pattern_levels or not ask_pattern_levels:
                        print(f"        ⚠️  Could not generate pattern levels for {normalized_symbol}")
                        failed_symbols += 1
                        category_symbols_failed += 1
                        continue
                    
                    # Log generated levels
                    if bid_pattern_levels:
                        print(f"        SELL levels below BID {current_bid:.{digits}f}:")
                        for i, level in enumerate(bid_pattern_levels[:5]):  # Show first 5
                            if level >= 1000:
                                print(f"          {i+1}. {level:.{digits if digits < 3 else 2}f}")
                            else:
                                print(f"          {i+1}. {level:.{digits}f}")
                    
                    if ask_pattern_levels:
                        print(f"        BUY levels above ASK {current_ask:.{digits}f}:")
                        for i, level in enumerate(ask_pattern_levels[:5]):  # Show first 5
                            if level >= 1000:
                                print(f"          {i+1}. {level:.{digits if digits < 3 else 2}f}")
                            else:
                                print(f"          {i+1}. {level:.{digits}f}")
                    
                    # Get minimum volume
                    min_volume, volume_step = get_min_volume(symbol_info)
                    
                    # Create grid orders structure
                    grid_bid_levels, grid_ask_levels = create_grid_orders_structure(
                        bid_pattern_levels, ask_pattern_levels, bid_order_type, ask_order_type, 
                        risk_reward_value, digits, min_volume, volume_step, symbol_info, 
                        account_currency, target_risk_min, target_risk_max, grid_multiplier
                    )
                    
                    # Create complete price data structure
                    price_data = {
                        "original_symbol": raw_symbol,
                        "symbol": normalized_symbol,
                        "digits": digits,
                        "tick_size": symbol_info.trade_tick_size,
                        "tick_value": symbol_info.trade_tick_value,
                        "contract_size": symbol_info.trade_contract_size,
                        "account_type": "",
                        "account_login": int(broker_cfg['LOGIN_ID']),
                        "account_server": acc_info.server,
                        "account_balance": account_balance,
                        "account_currency": account_currency,
                        "category": category,
                        "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "current_prices": {
                            "bid": current_bid,
                            "ask": current_ask,
                            "mid": current_price,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        },
                        "generated_levels": {
                            "levels_below_bid": [round(price, digits) for price in bid_pattern_levels],
                            "levels_above_ask": [round(price, digits) for price in ask_pattern_levels],
                            "generation_method": f"dynamic_pattern_multiplier_{grid_multiplier}",
                            "levels_requested": grid_levels,
                            "multiplier": grid_multiplier,
                            "patterns": pattern_desc,
                            "price_type": "integer_based" if bid_pattern_levels and bid_pattern_levels[0] >= 1000 else "fractional_based"
                        },
                        "risk_requirements": {
                            "target_risk_range_usd": {
                                "min": target_risk_min,
                                "max": target_risk_max,
                                "base": target_risk_base
                            },
                            "account_balance": account_balance,
                            "source_range": "account_balance_default_risk_management"
                        },
                        "grid_orders": {
                            "bid_levels": grid_bid_levels,
                            "ask_levels": grid_ask_levels,
                            "configuration": {
                                "bid_order_type": bid_order_type,
                                "ask_order_type": ask_order_type,
                                "risk_reward": risk_reward_value,
                                "min_volume": min_volume,
                                "volume_step": volume_step,
                                "account_currency": account_currency,
                                "target_risk_range_usd": {
                                    "min": target_risk_min,
                                    "max": target_risk_max
                                },
                                "source": "accountmanagement.json & live broker",
                                "levels": grid_levels,
                                "multiplier": grid_multiplier
                            }
                        }
                    }
                    
                    category_price_data[normalized_symbol] = price_data
                    all_symbols_price_data[normalized_symbol] = price_data
                    save_individual_symbol_price(prices_dir, normalized_symbol, price_data)
                    
                    successful_symbols += 1
                    category_symbols_success += 1
                
                if category_price_data:
                    save_category_summary(
                        prices_dir, category, symbols, category_price_data, 
                        category_symbols_success, category_symbols_failed, 
                        int(broker_cfg['LOGIN_ID']), bid_order_type, ask_order_type, 
                        risk_reward_value, target_risk_range, grid_levels, grid_multiplier
                    )
                    
                    category_results[category] = {
                        "total": len(symbols),
                        "success": category_symbols_success,
                        "failed": category_symbols_failed
                    }
                    
                    print(f"    📁 Saved category file: {category}_prices.json ({category_symbols_success}/{len(symbols)} symbols)")
                    all_category_price_data.update(category_price_data)
            
            # Save master price file and generate signals
            if successful_symbols > 0:
                save_all_symbols_prices(
                    prices_dir, all_symbols_price_data, acc_info,
                    bid_order_type, ask_order_type, risk_reward_value, target_risk_range,
                    total_categories, total_symbols, successful_symbols, failed_symbols,
                    category_results, grid_levels, grid_multiplier
                )
                
                # Generate signals and get the signals file path
                signals_data, signals_file = filter_signals_with_counters(
                    prices_dir, all_category_price_data, symbols_dict, 
                    target_risk_min, target_risk_max, 
                    bid_order_type, ask_order_type, risk_reward_value,
                    account_balance, account_currency, grid_levels, grid_multiplier
                )
                
                # FINAL STEP: Rearrange orders by extracting counter orders
                rearrange_orders_with_counters(signals_file)
                
                print_investor_summary(
                    inv_id, total_categories, total_symbols, successful_symbols,
                    failed_symbols, bid_order_type, ask_order_type, risk_reward_value,
                    target_risk_range, prices_dir, grid_levels, grid_multiplier
                )
                
                stats["total_symbols"] = total_symbols
                stats["successful_symbols"] = successful_symbols
                stats["failed_symbols"] = failed_symbols
                stats["total_categories"] = total_categories
            
        except Exception as e:
            print(f" [{inv_id}]  Error: {e}")
            import traceback
            traceback.print_exc()
            
    return stats

def filter_unauthorized_symbols(inv_id=None):
    """
    Verifies and filters risk entries based on allowed symbols defined in accountmanagement.json.
    Targets signals.json records and removes unauthorized symbol orders.
    Matches sanitized versions of symbols to handle broker suffixes (e.g., EURUSDm vs EURUSD).
    
    Args:
        inv_id: Optional specific investor ID to process. If None, processes all investors.
        
    Returns:
        dict: Statistics about the filtering process
    """
    print(f"\n{'='*10} 🛡️ SYMBOL AUTHORIZATION FILTER - SIGNALS.JSON TARGET {'='*10}")
    if inv_id:
        print(f" Processing single investor: {inv_id}")

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
        investor_ids = [inv_id] if os.path.isdir(os.path.join(INV_PATH, inv_id)) else []
    else:
        investor_ids = [f for f in os.listdir(INV_PATH) if os.path.isdir(os.path.join(INV_PATH, f))]
    
    total_investors_processed = 0
    total_investors_modified = 0
    total_symbols_removed = 0
    total_orders_removed = 0
    
    # Statistics dictionary for return
    filter_stats = {
        "investor_id": inv_id if inv_id else "all",
        "investors_processed": 0,
        "investors_modified": 0,
        "total_symbols_removed": 0,
        "total_orders_removed": 0,
        "categories_removed": 0,
        "processing_success": False
    }

    for current_inv_id in investor_ids:
        print(f"\n [{current_inv_id}] 🔍 Verifying symbol permissions in signals.json...")
        inv_folder = Path(INV_PATH) / current_inv_id
        acc_mgmt_path = inv_folder / "accountmanagement.json"
        signals_path = inv_folder / "prices" / "signals.json"
        
        if not acc_mgmt_path.exists():
            print(f"  └─ ⚠️  Account config missing. Skipping.")
            continue
            
        if not signals_path.exists():
            print(f"  └─ ⚠️  signals.json not found. Skipping.")
            continue

        try:
            # Load account management configuration
            with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Load signals.json
            with open(signals_path, 'r', encoding='utf-8') as f:
                signals_data = json.load(f)
            
            # Extract and sanitize the list of allowed symbols
            sym_dict = config.get("symbols_dictionary", {})
            allowed_sanitized = {sanitize(s) for sublist in sym_dict.values() for s in sublist}
            
            if not allowed_sanitized:
                print(f"  └─ 🔘 No symbols defined in dictionary. Skipping filter.")
                continue

            print(f"  └─ 📋 Allowed symbols (sanitized): {', '.join(sorted(allowed_sanitized))}")
            
            # Track removed orders
            investor_symbols_removed = 0
            investor_orders_removed = 0
            categories_modified = 0
            symbols_removed_list = []
            
            # Process each category in signals.json
            modified = False
            categories_to_remove = []
            
            for category, category_data in signals_data.get("categories", {}).items():
                symbols_in_category = category_data.get("symbols", {})
                original_symbol_count = len(symbols_in_category)
                
                # Filter symbols in this category
                filtered_symbols = {}
                symbols_removed_in_category = []
                
                for symbol, symbol_data in symbols_in_category.items():
                    # Check if symbol is allowed
                    if sanitize(symbol) in allowed_sanitized:
                        filtered_symbols[symbol] = symbol_data
                    else:
                        symbols_removed_in_category.append(symbol)
                        symbols_removed_list.append(f"{category}.{symbol}")
                        
                        # Count orders removed for this symbol
                        bid_orders = len(symbol_data.get("bid_orders", []))
                        ask_orders = len(symbol_data.get("ask_orders", []))
                        counter_orders = bid_orders + ask_orders  # One counter per order
                        investor_orders_removed += bid_orders + ask_orders + counter_orders
                
                # Update category data if symbols were removed
                if symbols_removed_in_category:
                    modified = True
                    categories_modified += 1
                    investor_symbols_removed += len(symbols_removed_in_category)
                    
                    if filtered_symbols:
                        # Update category with filtered symbols
                        signals_data["categories"][category]["symbols"] = filtered_symbols
                        
                        # Update category summary
                        signals_data["categories"][category]["summary"] = {
                            "symbols_with_signals": len(filtered_symbols),
                            "bid_orders": sum(len(s.get("bid_orders", [])) for s in filtered_symbols.values()),
                            "ask_orders": sum(len(s.get("ask_orders", [])) for s in filtered_symbols.values()),
                            "counter_orders": sum(len(s.get("bid_orders", [])) + len(s.get("ask_orders", [])) for s in filtered_symbols.values()),
                            "total_orders": sum(
                                len(s.get("bid_orders", [])) + len(s.get("ask_orders", [])) + 
                                (len(s.get("bid_orders", [])) + len(s.get("ask_orders", [])))  # counters
                                for s in filtered_symbols.values()
                            )
                        }
                        
                        print(f"    └─ 📌 Category '{category}': Removed {len(symbols_removed_in_category)} unauthorized symbols")
                        for sym in symbols_removed_in_category[:3]:  # Show first 3 removed
                            print(f"       • Removed: {sym}")
                        if len(symbols_removed_in_category) > 3:
                            print(f"       • ... and {len(symbols_removed_in_category) - 3} more")
                    else:
                        # No symbols left in this category, mark for removal
                        categories_to_remove.append(category)
                        print(f"    └─ 📌 Category '{category}': All symbols unauthorized - will remove category")
            
            # Remove empty categories
            for category in categories_to_remove:
                del signals_data["categories"][category]
                print(f"    └─ 🗑️ Removed empty category: {category}")
            
            # Update main summary if modifications were made
            if modified or categories_to_remove:
                # Recalculate global summary
                total_symbols = 0
                total_bid_orders = 0
                total_ask_orders = 0
                total_counter_orders = 0
                
                for cat_data in signals_data.get("categories", {}).values():
                    cat_symbols = cat_data.get("symbols", {})
                    total_symbols += len(cat_symbols)
                    
                    for sym_data in cat_symbols.values():
                        bid_count = len(sym_data.get("bid_orders", []))
                        ask_count = len(sym_data.get("ask_orders", []))
                        total_bid_orders += bid_count
                        total_ask_orders += ask_count
                        total_counter_orders += bid_count + ask_count
                
                signals_data["summary"] = {
                    "total_symbols_with_signals": total_symbols,
                    "total_bid_orders": total_bid_orders,
                    "total_ask_orders": total_ask_orders,
                    "total_counter_orders": total_counter_orders,
                    "total_orders": total_bid_orders + total_ask_orders + total_counter_orders
                }
                
                # Add filter metadata
                signals_data["filter_applied"] = {
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "unauthorized_symbols_removed": symbols_removed_list,
                    "total_orders_removed": investor_orders_removed,
                    "filter_type": "symbol_authorization"
                }
                
                # Save modified signals.json
                with open(signals_path, 'w', encoding='utf-8') as f:
                    json.dump(signals_data, f, indent=4)
                
                total_investors_modified += 1
                total_symbols_removed += investor_symbols_removed
                total_orders_removed += investor_orders_removed
                
                print(f"\n  └─ 📊 FILTER SUMMARY for {current_inv_id}:")
                print(f"     • Categories modified: {categories_modified}")
                print(f"     • Categories removed: {len(categories_to_remove)}")
                print(f"     • Unauthorized symbols removed: {investor_symbols_removed}")
                print(f"     • Total orders purged: {investor_orders_removed}")
                print(f"     • Remaining symbols: {total_symbols}")
                print(f"     • Remaining orders (with counters): {total_bid_orders + total_ask_orders + total_counter_orders}")
                print(f"     • ✅ signals.json updated successfully")
            else:
                print(f"  └─ ✅ All symbols in signals.json are authorized. No changes needed.")

            total_investors_processed += 1

        except json.JSONDecodeError as e:
            print(f"  └─  Invalid JSON in {current_inv_id}: {e}")
        except Exception as e:
            print(f"  └─  Error processing {current_inv_id}: {e}")
            import traceback
            traceback.print_exc()

    # Update statistics
    filter_stats["investors_processed"] = total_investors_processed
    filter_stats["investors_modified"] = total_investors_modified
    filter_stats["total_symbols_removed"] = total_symbols_removed
    filter_stats["total_orders_removed"] = total_orders_removed
    filter_stats["processing_success"] = total_investors_processed > 0

    print(f"\n{'='*10} 🏁 FILTERING COMPLETE {'='*10}")
    print(f"   Processed: {total_investors_processed} investors")
    print(f"   Modified: {total_investors_modified} investors")
    print(f"   Total symbols removed: {total_symbols_removed}")
    print(f"   Total orders removed: {total_orders_removed}")
    print(f"{'='*10}\n")
    
    return filter_stats

def fetch_15m_candles(inv_id=None):
    """
    Fetch 15-minute candles (100 candles) for all symbols in symbols_dictionary.
    Uses same symbol normalization pattern as symbols_grid_prices.
    Saves all symbols' candle data to symbols_prices.json as [symbol]_tf_candles top-level keys.
    
    Args:
        inv_id: Optional specific investor ID to process
        
    Returns:
        dict: Statistics about the candle fetching
    """
    print(f"\n{'='*10} 🕯️ FETCHING 15M CANDLES (100 CANDLES) {'='*10}")
    if inv_id:
        print(f" Processing single investor: {inv_id}")
    
    # Statistics for this run
    stats = {
        "investor_id": inv_id if inv_id else "all",
        "total_symbols": 0,
        "successful_symbols": 0,
        "failed_symbols": 0,
        "total_candles_fetched": 0,
        "symbols_mapped": 0,
        "symbols_unchanged": 0,
        "current_candle_forming": False  # Flag to mark current forming candle
    }

    def clean(s): 
        """Clean symbol string by removing special chars and converting to uppercase"""
        if s is None:
            return ""
        return str(s).replace(" ", "").replace("_", "").replace("/", "").replace(".", "").upper()
    
    def fetch_symbol_candles(symbol, resolution_cache):
        """
        Fetch 100 15-minute candles for a symbol using external helper for normalization
        and cache for efficiency. Numbers candles from 100 (current forming) down to 1 (oldest).
        
        Args:
            symbol: Raw symbol to fetch candles for
            resolution_cache: Cache dictionary for symbol resolution
            
        Returns:
            tuple: (success, normalized_symbol, candles_data, current_candle, error_message)
        """
        try:
            # Check Cache First - exactly like populate_orders_missing_fields
            if symbol in resolution_cache:
                res = resolution_cache[symbol]
                normalized_symbol = res['broker_sym']
                symbol_info = res['info']
                
                # If we have cached info but it's None (previously failed), return error
                if symbol_info is None:
                    return False, None, None, None, f"Symbol '{symbol}' previously failed to resolve"
            else:
                # Perform mapping only once using external helper
                normalized_symbol = get_normalized_symbol(symbol)
                
                # Get symbol info from MT5 to verify it exists
                symbol_info = mt5.symbol_info(normalized_symbol)
                
                # Store in cache - exactly like populate_orders_missing_fields
                resolution_cache[symbol] = {'broker_sym': normalized_symbol, 'info': symbol_info}
                
                # Detailed log only on first discovery
                if symbol_info:
                    if normalized_symbol != symbol:
                        print(f"    └─ ✅ {symbol} -> {normalized_symbol} (Mapped & Cached)")
                        stats["symbols_mapped"] += 1
                    else:
                        print(f"    └─ ✅ {symbol} (Direct match, cached)")
                        stats["symbols_unchanged"] += 1
                else:
                    print(f"    └─  MT5: '{normalized_symbol}' (from '{symbol}') not found in MarketWatch")
                    return False, None, None, None, f"Symbol '{normalized_symbol}' not found in MarketWatch"
            
            # If we get here, we have valid symbol_info from cache or fresh lookup
            if not symbol_info:
                return False, None, None, None, f"Symbol info not available for {normalized_symbol}"
            
            # Select symbol in Market Watch (required for data)
            if not mt5.symbol_select(normalized_symbol, True):
                return False, normalized_symbol, None, None, f"Failed to select symbol: {normalized_symbol}"
            
            # Define timeframe (15 minutes)
            timeframe = mt5.TIMEFRAME_M15
            
            # Get current time
            current_time = datetime.now()
            
            # Fetch 100 candles (plus 1 extra to account for current forming candle)
            rates = mt5.copy_rates_from(normalized_symbol, timeframe, current_time, 101)
            
            if rates is None or len(rates) == 0:
                return False, normalized_symbol, None, None, "No candle data available"
            
            # Separate completed candles and current forming candle
            completed_candles = rates[:-1] if len(rates) > 1 else []  # All except last
            current_candle = rates[-1] if len(rates) > 0 else None  # Last candle (may be forming)
            
            # Reverse the completed candles so newest is first (index 0)
            completed_candles_reversed = list(reversed(completed_candles))
            
            # Convert to list of dictionaries for JSON serialization with explicit type conversion
            # Number from 100 down to 1, where 100 is current forming (if exists)
            candles_list = []
            
            # Start numbering from 100 (if we have current forming candle)
            next_number = 100
            
            # Add current forming candle first (as number 100) if it exists
            if current_candle is not None:
                current_candle_dict = {
                    'candle_number': next_number,  # Always 100 for current forming
                    'time': int(current_candle[0]),  # Convert numpy.int64 to Python int
                    'time_str': datetime.fromtimestamp(int(current_candle[0])).strftime('%Y-%m-%d %H:%M:%S'),
                    'open': float(current_candle[1]),
                    'high': float(current_candle[2]),
                    'low': float(current_candle[3]),
                    'close': float(current_candle[4]),
                    'tick_volume': int(current_candle[5]),
                    'spread': int(current_candle[6]),
                    'real_volume': int(current_candle[7]) if current_candle[7] is not None else 0,
                    'is_forming': True  # Flag to indicate this is the current forming candle
                }
                
                # Log the current forming candle
                print(f"      🕯️ Current forming 15m candle (#{current_candle_dict['candle_number']}) starting at {current_candle_dict['time_str']}:")
                print(f"        Open: {current_candle_dict['open']:.{symbol_info.digits}f}, "
                      f"High: {current_candle_dict['high']:.{symbol_info.digits}f}, "
                      f"Low: {current_candle_dict['low']:.{symbol_info.digits}f}, "
                      f"Close: {current_candle_dict['close']:.{symbol_info.digits}f}")
                
                # Add current forming candle to list
                candles_list.append(current_candle_dict)
                next_number -= 1
            
            # Add completed candles in reverse order (newest to oldest)
            for i, rate in enumerate(completed_candles_reversed[:100]):  # Limit to 100 total candles
                # Convert numpy types to Python native types
                candle_dict = {
                    'candle_number': next_number - i,  # Decreasing numbers: 99, 98, 97...
                    'time': int(rate[0]),  # Convert numpy.int64 to Python int
                    'time_str': datetime.fromtimestamp(int(rate[0])).strftime('%Y-%m-%d %H:%M:%S'),
                    'open': float(rate[1]),  # Convert to float
                    'high': float(rate[2]),
                    'low': float(rate[3]),
                    'close': float(rate[4]),
                    'tick_volume': int(rate[5]),  # Convert to int
                    'spread': int(rate[6]),  # Convert to int
                    'real_volume': int(rate[7]) if rate[7] is not None else 0,  # Convert to int
                    'is_forming': False  # Completed candle
                }
                candles_list.append(candle_dict)
            
            # Ensure candles are sorted by number descending (highest first)
            candles_list.sort(key=lambda x: x['candle_number'], reverse=True)
            
            # Separate current forming candle for return value
            current_candle_dict = next((c for c in candles_list if c['is_forming']), None)
            
            # Prepare candles data structure for this symbol
            symbol_candles_data = {
                'symbol': normalized_symbol,
                'original_symbol': symbol,
                'timeframe': 'M15',
                'total_candles_fetched': len([c for c in candles_list if not c['is_forming']]),
                'has_current_forming': current_candle_dict is not None,
                'current_forming_candle': current_candle_dict,
                'candles': candles_list,  # Now includes numbered candles with current forming first
                'candle_numbering': {
                    'current_forming_number': 100,
                    'oldest_completed_number': 100 - len([c for c in candles_list if not c['is_forming']]),
                    'numbering_scheme': '100 (current forming) down to 1 (oldest)'
                },
                'fetched_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'digits': int(symbol_info.digits) if symbol_info.digits is not None else 5
            }
            
            return True, normalized_symbol, symbol_candles_data, current_candle_dict, None
            
        except Exception as e:
            return False, None, None, None, str(e)
    
    def save_candles_to_symbols_prices(prices_dir, all_symbols_candle_data, symbols_prices_data):
        """
        Save candle data to symbols_prices.json as [symbol]_tf_candles top-level keys.
        
        Args:
            prices_dir: Directory containing the files
            all_symbols_candle_data: Dictionary with symbol as key and candle data as value
            symbols_prices_data: Existing symbols_prices.json data
        """
        symbols_prices_path = prices_dir / "symbols_prices.json"
        
        # Add each symbol's candle data as a top-level key
        candles_added = 0
        for symbol, candle_data in all_symbols_candle_data.items():
            candle_key = f"{symbol}_tf_candles"
            symbols_prices_data[candle_key] = candle_data
            candles_added += 1
        
        # Add metadata about candle fetching
        symbols_prices_data['candles_fetch_metadata'] = {
            'fetched_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'timeframe': 'M15',
            'total_symbols_fetched': len(all_symbols_candle_data),
            'current_candle_forming': any(data.get('has_current_forming', False) for data in all_symbols_candle_data.values()),
            'note': 'Candle data stored as [symbol]_tf_candles top-level keys'
        }
        
        # Save back to file
        with open(symbols_prices_path, 'w', encoding='utf-8') as f:
            json.dump(symbols_prices_data, f, indent=4, default=str)
        
        print(f"    📁 Saved candle data to symbols_prices.json as {candles_added} [symbol]_tf_candles entries")
    
    # If inv_id is provided, process only that investor
    if inv_id:
        # Get broker config
        broker_cfg = usersdictionary.get(inv_id)
        if not broker_cfg:
            print(f" [{inv_id}]  No broker config found")
            return stats
        
        inv_root = Path(INV_PATH) / inv_id
        prices_dir = inv_root / "prices"
        prices_dir.mkdir(exist_ok=True)
        
        # Path to symbols_prices.json
        symbols_prices_path = prices_dir / "symbols_prices.json"
        
        # Check if symbols_prices.json exists, if not create basic structure
        if symbols_prices_path.exists():
            print(f" [{inv_id}] 📂 Loading existing symbols_prices.json...")
            with open(symbols_prices_path, 'r', encoding='utf-8') as f:
                symbols_prices_data = json.load(f)
        else:
            print(f" [{inv_id}] ⚠️ symbols_prices.json not found, creating new file...")
            symbols_prices_data = {
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'account_type': '',
                'account_login': int(broker_cfg['LOGIN_ID']) if 'LOGIN_ID' in broker_cfg else None
            }
        
        acc_mgmt_path = inv_root / "accountmanagement.json"
        
        if not acc_mgmt_path.exists():
            print(f" [{inv_id}] ⚠️ Account management file not found")
            return stats
        
        try:
            with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Extract symbols dictionary
            symbols_dict = config.get("symbols_dictionary", {})
            if not symbols_dict:
                print(f" [{inv_id}] ⚠️ No symbols_dictionary found")
                return stats
            
            print(f"\n  📁 Candle data will be saved to symbols_prices.json")
            
            # Track statistics
            total_symbols = 0
            successful_symbols = 0
            failed_symbols = 0
            total_candles_fetched = 0
            current_candle_forming = False
            
            # Symbol resolution cache - exactly like populate_orders_missing_fields
            resolution_cache = {}
            
            # Dictionary to store all symbols' candle data
            all_symbols_candle_data = {}
            
            # Process each category in symbols_dictionary
            for category, symbols in symbols_dict.items():
                print(f"\n  📂 Category: {category.upper()} ({len(symbols)} symbols)")
                
                for raw_symbol in symbols:
                    total_symbols += 1
                    print(f"    🔍 Fetching 15m candles for: {raw_symbol}...", end=" ")
                    
                    # Fetch candles with resolution cache
                    success, normalized_symbol, symbol_candles_data, current_candle, error = fetch_symbol_candles(
                        raw_symbol, resolution_cache
                    )
                    
                    if not success:
                        print(f" {error[:50] if error else 'Unknown error'}")
                        failed_symbols += 1
                        continue
                    
                    # Check if we have a current forming candle
                    if current_candle is not None:
                        current_candle_forming = True
                        print(f"✅ (has forming candle)")
                    else:
                        print(f"✅")
                    
                    # Store in the all symbols dictionary using normalized symbol as key
                    all_symbols_candle_data[normalized_symbol] = symbol_candles_data
                    
                    successful_symbols += 1
                    total_candles_fetched += symbol_candles_data['total_candles_fetched']
                    
                    # Print sample of fetched candles with numbers
                    if symbol_candles_data['candles']:
                        # Show first few candles (newest/current)
                        print(f"        📊 Fetched {symbol_candles_data['total_candles_fetched']} completed candles + 1 forming = {len(symbol_candles_data['candles'])} total")
                        print(f"        📋 Candle numbering: 100 = current forming, 99-1 = completed (newest to oldest)")
                        
                        # Show current forming (if exists)
                        if symbol_candles_data['has_current_forming']:
                            current = symbol_candles_data['current_forming_candle']
                            print(f"          • Current Forming #{current['candle_number']}: {current['time_str']} (O:{current['open']:.{symbol_candles_data['digits']}f}, "
                                  f"H:{current['high']:.{symbol_candles_data['digits']}f}, L:{current['low']:.{symbol_candles_data['digits']}f}, C:{current['close']:.{symbol_candles_data['digits']}f})")
                        
                        # Show first completed candle (most recent completed)
                        first_completed = next((c for c in symbol_candles_data['candles'] if not c['is_forming']), None)
                        if first_completed:
                            print(f"          • Most Recent Completed #{first_completed['candle_number']}: {first_completed['time_str']} (O:{first_completed['open']:.{symbol_candles_data['digits']}f}, "
                                  f"C:{first_completed['close']:.{symbol_candles_data['digits']}f})")
                        
                        # Show oldest candle
                        oldest = symbol_candles_data['candles'][-1]
                        print(f"          • Oldest #{oldest['candle_number']}: {oldest['time_str']} (O:{oldest['open']:.{symbol_candles_data['digits']}f}, "
                              f"C:{oldest['close']:.{symbol_candles_data['digits']}f})")
            
            # Save all candle data to symbols_prices.json
            if all_symbols_candle_data:
                save_candles_to_symbols_prices(prices_dir, all_symbols_candle_data, symbols_prices_data)
            
            # Update stats
            stats["total_symbols"] = total_symbols
            stats["successful_symbols"] = successful_symbols
            stats["failed_symbols"] = failed_symbols
            stats["total_candles_fetched"] = total_candles_fetched
            stats["current_candle_forming"] = current_candle_forming
            
            print(f"\n  📊 CANDLE FETCHING SUMMARY:")
            print(f"    • Total symbols: {total_symbols}")
            print(f"    • Successful: {successful_symbols}")
            print(f"    • Failed: {failed_symbols}")
            print(f"    • Total completed candles: {total_candles_fetched}")
            print(f"    • Current forming candle: {'✅ Yes' if current_candle_forming else ' No'}")
            print(f"    • Numbering scheme: 100 = current forming, 99-1 = completed (newest to oldest)")
            print(f"    • Symbols mapped: {stats['symbols_mapped']}")
            print(f"    • Symbols unchanged: {stats['symbols_unchanged']}")
            print(f"    • All candle data saved to symbols_prices.json as [symbol]_tf_candles")
            
        except Exception as e:
            print(f" [{inv_id}]  Error: {e}")
            import traceback
            traceback.print_exc()
    
    return stats

def timeframe_countdown(inv_id=None):
    """
    Countdown to candle close based on timeframe list from config.
    Automatically picks the SMALLEST timeframe (e.g., "1m" over "5m").
    Locks onto the FIRST valid symbol found per user and sticks to it.
    EXITS IMMEDIATELY once the candle closes - NO LOOPING AFTER.
    """

    print(f"\n{'='*10} ⏰ TIMEFRAME COUNTDOWN: CANDLE CLOSE MONITOR {'='*10}")
    
    stats = {
        "investor_id": inv_id if inv_id else "all",
        "timeframe_used": None,
        "countdown_completed": False,
        "processing_success": False,
    }
    
    def clean(s): 
        return str(s).replace(" ", "").replace("_", "").replace("/", "").replace(".", "").upper() if s else ""
    
    def is_symbol_market_open(symbol):
        if not mt5.symbol_select(symbol, True):
            return False, None
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info or symbol_info.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
            return False, None
        return True, symbol_info

    def get_all_symbols_from_config(config):
        all_symbols = []
        for category, symbols in config.get("symbols_dictionary", {}).items():
            all_symbols.extend(symbols)
        for strategy in config.get("strategies", []):
            s = strategy.get("symbol")
            if s and s not in all_symbols: all_symbols.append(s)
        return list(set(all_symbols))

    def get_smallest_timeframe(timeframe_list):
        """Extract and return the smallest timeframe from a list like ['1m','5m','1h']"""
        if not timeframe_list:
            return None
        
        # Convert timeframe strings to seconds for comparison
        def tf_to_seconds(tf_str):
            m = re.match(r'(\d+)([a-z]+)', tf_str.lower())
            if not m:
                return None
            value = int(m.group(1))
            unit = m.group(2)
            mult = {'m': 60, 'h': 3600, 'd': 86400}
            return value * mult.get(unit, 60)
        
        # Filter valid timeframes and find smallest
        valid_timeframes = []
        for tf in timeframe_list:
            seconds = tf_to_seconds(tf)
            if seconds:
                valid_timeframes.append((tf, seconds))
        
        if not valid_timeframes:
            return None
        
        # Return the timeframe with smallest seconds
        smallest = min(valid_timeframes, key=lambda x: x[1])
        return smallest[0]

    # Determine which users to process
    investors_to_process = [inv_id] if inv_id else list(usersdictionary.keys())

    for user_brokerid in investors_to_process:
        broker_cfg = usersdictionary.get(user_brokerid)
        if not broker_cfg: continue
        
        acc_mgmt_path = Path(INV_PATH) / user_brokerid / "accountmanagement.json"
        if not acc_mgmt_path.exists(): continue

        try:
            with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # --- GET TIMEFRAME LIST FROM CONFIG ---
            timeframe_list = config.get("timeframe", [])
            if not timeframe_list:
                print(f" └─ ⚠️ No 'timeframe' list found for {user_brokerid}. Skipping.")
                continue
            
            # Pick the smallest timeframe
            strategy_tf = get_smallest_timeframe(timeframe_list)
            if not strategy_tf:
                print(f" └─ ⚠️ No valid timeframe found in {timeframe_list} for {user_brokerid}. Skipping.")
                continue
            
            # --- TIMEFRAME MAPPING ---
            TIMEFRAME_MAP = {
                "1m": mt5.TIMEFRAME_M1, "2m": mt5.TIMEFRAME_M2, "3m": mt5.TIMEFRAME_M3,
                "5m": mt5.TIMEFRAME_M5, "15m": mt5.TIMEFRAME_M15, "30m": mt5.TIMEFRAME_M30,
                "1h": mt5.TIMEFRAME_H1, "4h": mt5.TIMEFRAME_H4, "1d": mt5.TIMEFRAME_D1
            }
            
            def _get_sec(tf_str):
                m = re.match(r'(\d+)([a-z]+)', tf_str)
                mult = {'m': 60, 'h': 3600, 'd': 86400}
                return int(m.group(1)) * mult.get(m.group(2), 60) if m else 60

            timeframe = TIMEFRAME_MAP.get(strategy_tf, mt5.TIMEFRAME_M1)
            period_sec = _get_sec(strategy_tf)
            stats["timeframe_used"] = strategy_tf

            print(f"📊 Selected smallest timeframe: {strategy_tf} from list {timeframe_list}")

            # --- ONE-TIME SYMBOL LOCK ---
            all_symbols = get_all_symbols_from_config(config)
            selected_symbol, s_info = None, None
            
            for s in all_symbols:
                is_open, info = is_symbol_market_open(clean(s))
                if is_open:
                    selected_symbol, s_info = clean(s), info
                    break

            if not selected_symbol:
                print(f" └─ ⚠️ No open symbols found for {user_brokerid}. Skipping.")
                continue

            # --- INITIAL STATE CAPTURE ---
            rates = mt5.copy_rates_from_pos(selected_symbol, timeframe, 0, 1)
            if rates is None or len(rates) == 0:
                continue
            
            initial_candle_time = int(rates[0]['time'])
            target_close_time = initial_candle_time + period_sec

            print(f"⏳ Monitoring {strategy_tf} on {selected_symbol}. Target Close: {time.strftime('%H:%M:%S', time.localtime(target_close_time))}")
            print(f"🔒 Countdown will EXIT and CLOSE immediately when candle closes.\n")

            # --- THE RIGID COUNTDOWN LOOP ---
            loop_count = 0
            max_loops = (period_sec * 10) + 100  # 10x period seconds + buffer, prevents infinite loop
            
            while loop_count < max_loops:
                loop_count += 1
                
                # Get current MT5 server time from the locked symbol
                tick = mt5.symbol_info_tick(selected_symbol)
                if not tick:
                    time.sleep(0.1)
                    continue

                current_mt5_time = tick.time
                remaining = target_close_time - current_mt5_time

                # Verify candle rollover (safety check)
                check_rates = mt5.copy_rates_from_pos(selected_symbol, timeframe, 0, 1)
                new_candle_time = int(check_rates[0]['time']) if (check_rates is not None and len(check_rates) > 0) else initial_candle_time

                # UI Update
                if remaining > 0:
                    m, s = divmod(int(remaining), 60)
                    time_str = f"{m:02d}:{s:02d}"
                    print(f"\r    ⏱️  Remaining: {time_str} | Bid: {tick.bid:.{s_info.digits}f}", end="", flush=True)

                # EXIT CONDITION: Server time passed target OR MT5 generated a new candle
                if remaining <= 0 or new_candle_time > initial_candle_time:
                    print(f"\n\n🎯 CANDLE CLOSED - TERMINATING COUNTDOWN.")
                    stats["countdown_completed"] = True
                    stats["processing_success"] = True
                    
                    # FORCE EXIT - Multiple methods to ensure closure
                    print(f"\n{'='*10} 🏁 EXITING FUNCTION NOW {'='*10}\n")
                    
                    # Flush all output buffers
                    sys.stdout.flush()
                    
                    # Return stats and exit function
                    return stats 

                # Small sleep to prevent CPU overload
                time.sleep(0.2)
            
            # If we somehow hit max loops, exit anyway
            print(f"\n\n⚠️ MAX LOOPS REACHED - FORCING EXIT")
            stats["processing_success"] = False
            return stats

        except Exception as e:
            print(f"\n └─  Error processing {user_brokerid}: {e}")
            stats["processing_success"] = False
            return stats

    # If no valid investors found, exit with stats as is
    print(f"\n{'='*10} 🏁 FUNCTION ENDED - NO VALID INVESTORS {'='*10}\n")
    return stats

def place_signals_orders(inv_id=None):
    """
    Place orders from signals.json for specified investor(s).
    
    EXECUTION LOGIC:
    1. Check accountmanagement.json settings:
       - If enable_auto_trading is false, skip order placement
       - Check allow_order_type_conversion for conversion permission
       - Check opposite_order_restriction for opposite-direction proximity checks
    
    2. For each symbol with signals:
       - Process ALL orders from both bid_orders and ask_orders arrays
       - For each order, check if an identical order already exists in:
         * Pending orders (same symbol, order_type, entry price, volume)
         * Open positions (same symbol, order_type, entry price, volume)
       - Skip if identical order exists
       
    3. Check if order is too close to any running position using risk-based detection:
       - Get all open positions for the symbol
       - For each position, calculate the risk if the pending order were to be triggered
       
       A. SAME DIRECTION CHECK (SELL vs SELL, BUY vs BUY):
          - Compare this risk against the position's own risk
          - If calculated risk < position_risk/2, orders are too close - SKIP placement
          - If calculated risk >= position_risk/2, orders are sufficiently far - ALLOW placement
       
       B. OPPOSITE DIRECTION CHECK (SELL vs BUY, BUY vs SELL):
          - Only applies if opposite_order_restriction = true in settings
          - Calculate risk if opposite orders were to trigger toward each other
          - If calculated risk < position_risk/2, orders are too close - SKIP placement
          - If opposite_order_restriction = false, skip this check entirely
    
    4. Place new order if no duplicate found and not too close to positions
       - If order has order_counter, also place the counter order IMMEDIATELY
       - Pending orders are placed with TRADE_ACTION_PENDING and will auto-execute when price reaches them
       - If order fails with "Invalid price" (code 10015) AND conversion is allowed:
         * Convert order type with adjusted price
         * NEW CONVERSION LOGIC: buy_stop → sell_limit, sell_stop → buy_limit
         * Original stop order is NOT placed, only the converted limit order is placed
    
    5. Track placement statistics
    
    Args:
        inv_id: Optional specific investor ID to process
        
    Returns:
        dict: Statistics about order placement
    """
    
    # =====================================================
    # SUB-FUNCTION: Sync and save trade history
    # =====================================================
    def sync_and_save_trade_history(investor_root, new_trade=None):
        """
        Synchronize tradeshistory.json with MT5 terminal status.
        
        NEW PATH STRUCTURE:
        - tradeshistory.json is stored directly in the investor root folder
        
        Args:
            investor_root: Path to the investor's root directory
            new_trade: Optional new trade record to add
            
        Returns:
            bool: Success status
        """
        try:
            # Define the history file path
            history_path = investor_root / "tradeshistory.json"
            
            print(f"      📂 Tradeshistory path: {history_path}")
            
            # Load existing history if it exists
            history = []
            if history_path.exists():
                try:
                    with open(history_path, 'r', encoding='utf-8') as f:
                        history = json.load(f)
                    print(f"      📋 Loaded {len(history)} existing trades from tradeshistory.json")
                except Exception as e:
                    print(f"      ⚠️ Error reading tradeshistory.json: {e}")
                    history = []
            
            # 1. Add new trade if provided
            if new_trade:
                # Check if trade already exists to avoid duplicates
                existing_ticket = any(t.get('ticket') == new_trade.get('ticket') for t in history)
                if not existing_ticket:
                    history.append(new_trade)
                    print(f"      ➕ Added new trade: Ticket {new_trade.get('ticket')}")
                else:
                    print(f"      ℹ️ Trade Ticket {new_trade.get('ticket')} already exists in history")
            
            # 2. Sync all records with MT5
            active_orders = {o.ticket for o in (mt5.orders_get() or [])}
            active_positions = {p.ticket for p in (mt5.positions_get() or [])}
            
            # Fetch history for the last 24 hours to check recently closed
            from datetime import datetime, timedelta
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
                        # Get profit and close details from history deals
                        all_deals = []
                        if history_deals:
                            all_deals.extend(history_deals)
                        if older_history_deals:
                            all_deals.extend(older_history_deals)
                        
                        for deal in all_deals:
                            if deal.order == ticket:
                                trade['profit'] = deal.profit
                                trade['close_price'] = deal.price
                                trade['close_time'] = datetime.fromtimestamp(deal.time).strftime('%Y-%m-%d %H:%M:%S')
                                trade['commission'] = deal.commission
                                trade['swap'] = deal.swap
                                break
                        print(f"      🔄 Trade {ticket}: {old_status} → closed (found in MT5 history)")
                        updated_count += 1
                # If not found in either, mark as closed/expired
                else:
                    if trade.get('status') == 'pending':
                        trade['status'] = 'closed'
                        trade['close_reason'] = 'expired_or_not_found'
                        print(f"      🔄 Trade {ticket}: pending → closed (expired/not found in MT5)")
                        updated_count += 1
                    elif trade.get('status') != 'closed':
                        trade['status'] = 'closed'
                        trade['close_reason'] = 'default_closure'
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
                    print(f"      ℹ️ No changes to tradeshistory.json")
                    
                # Also save a backup copy in the investor root for safety
                backup_path = investor_root / "tradeshistory_backup.json"
                try:
                    with open(backup_path, 'w', encoding='utf-8') as f:
                        json.dump(history, f, indent=4)
                    print(f"      💾 Backup saved to: {backup_path}")
                except Exception as e:
                    print(f"      ⚠️ Could not save backup: {e}")
                    
            except Exception as e:
                print(f"      No Failed to save tradeshistory.json: {e}")
                return False
                
            return True
            
        except Exception as e:
            print(f"      No Error in sync_and_save_trade_history: {e}")
            return False
    
    # =====================================================
    # SUB-FUNCTION: Record trade in history
    # =====================================================
    def record_trade_in_history(investor_root, order_data, mt5_result, is_counter=False, is_converted=False, final_price=None, final_type=None):
        """
        Record a successfully placed trade in tradeshistory.json.
        
        Args:
            investor_root: Path to the investor's root directory
            order_data: Original order data from signals.json
            mt5_result: Result object from mt5.order_send()
            is_counter: Whether this is a counter order
            is_converted: Whether this order was converted
            final_price: The final price at which order was placed (if converted)
            final_type: The final order type (if converted)
            
        Returns:
            bool: Success status
        """
        try:
            # Create trade record
            trade_record = order_data.copy()
            
            # Add MT5-specific information
            trade_record['ticket'] = mt5_result.order
            trade_record['magic'] = order_data.get('magic', 0)
            trade_record['placed_timestamp'] = datetime.now().isoformat()
            trade_record['status'] = 'pending'
            trade_record['is_counter'] = is_counter
            trade_record['is_converted'] = is_converted
            
            # Record the actual placed price and type (might differ from original if converted)
            if final_price:
                trade_record['original_entry'] = trade_record.get('entry')
                trade_record['entry'] = final_price
                trade_record['final_order_type'] = final_type or trade_record.get('order_type')
            else:
                trade_record['final_order_type'] = trade_record.get('order_type')
            
            # Add execution details
            trade_record['mt5_order_retcode'] = mt5_result.retcode
            trade_record['mt5_order_comment'] = mt5_result.comment
            
            # If this is a counter order, link it to the main order
            if is_counter:
                trade_record['type'] = 'counter_order'
            
            # If converted, note the original order type
            if is_converted:
                trade_record['converted_from'] = order_data.get('order_type')
                trade_record['conversion_reason'] = 'invalid_price_conversion'
            
            # Sync and save to history
            return sync_and_save_trade_history(investor_root, trade_record)
            
        except Exception as e:
            print(f"      No Failed to record trade in history: {e}")
            return False
    
    # =====================================================
    # SUB-FUNCTION: Get investor root from signals path
    # =====================================================
    def get_investor_root(investor_id):
        """Get the investor root directory path"""
        return Path(INV_PATH) / investor_id
    
    # =====================================================
    # SUB-FUNCTION: Get all existing pending orders
    # =====================================================
    def get_all_existing_pending_orders():
        """
        Get ALL pending orders from MT5 for this account (no symbol filter).
        
        Returns:
            dict: Dictionary of existing orders keyed by unique identifier
        """
        existing_orders = {}
        
        # Get all pending orders (no symbol parameter to avoid errors)
        orders = mt5.orders_get()
        if orders is None:
            error_code = mt5.last_error()
            print(f"        ℹ️ Could not fetch pending orders: {error_code}")
            return existing_orders
        
        for order in orders:
            try:
                # For pending orders, use price (not price_open)
                # Different MT5 versions might use different attribute names
                order_price = getattr(order, 'price', None)
                if order_price is None:
                    order_price = getattr(order, 'price_open', 0)
                
                order_volume = getattr(order, 'volume_current', getattr(order, 'volume_initial', 0))
                
                # Create a unique key for this order
                order_key = f"{order.symbol}_{order.type}_{order_price}_{order_volume}"
                existing_orders[order_key] = {
                    'ticket': order.ticket,
                    'symbol': order.symbol,
                    'type': order.type,
                    'price': order_price,
                    'volume': order_volume,
                    'sl': order.sl,
                    'time_setup': getattr(order, 'time_setup', 0),
                    'type_string': "PENDING"
                }
            except Exception as e:
                print(f"        ⚠️ Error processing pending order: {e}")
                continue
        
        print(f"        📋 Found {len(existing_orders)} existing pending orders")
        return existing_orders
    
    # =====================================================
    # SUB-FUNCTION: Get all existing positions
    # =====================================================
    def get_all_existing_positions():
        """
        Get ALL open positions from MT5 for this account (no symbol filter).
        
        Returns:
            dict: Dictionary of existing positions keyed by unique identifier
        """
        existing_positions = {}
        
        # Get all open positions (no symbol parameter to avoid errors)
        positions = mt5.positions_get()
        if positions is None:
            error_code = mt5.last_error()
            print(f"        ℹ️ Could not fetch open positions: {error_code}")
            return existing_positions
        
        for position in positions:
            try:
                # For positions, use price_open
                position_key = f"{position.symbol}_{position.type}_{position.price_open}_{position.volume}"
                existing_positions[position_key] = {
                    'ticket': position.ticket,
                    'symbol': position.symbol,
                    'type': position.type,
                    'price': position.price_open,
                    'volume': position.volume,
                    'sl': position.sl,
                    'tp': position.tp,
                    'time': getattr(position, 'time', 0),
                    'type_string': "POSITION"
                }
            except Exception as e:
                print(f"        ⚠️ Error processing position: {e}")
                continue
        
        print(f"        📋 Found {len(existing_positions)} existing open positions")
        return existing_positions
    
    # =====================================================
    # SUB-FUNCTION: Regulate and authorize orders
    # =====================================================
    def regulate_and_authorize_orders(symbol, pending_orders_to_keep, magic_number):
        """
        Cancel/delete any pending orders in the account that are not in signals.json.
        
        Args:
            symbol: Symbol to regulate
            pending_orders_to_keep: List of order keys that should be kept
            magic_number: Magic number for orders
            
        Returns:
            int: Number of orders cancelled
        """
        cancelled_count = 0
        
        # Get all pending orders for this symbol
        orders = mt5.orders_get(symbol=symbol)
        if orders is None:
            print(f"      ℹ️ No pending orders found for {symbol} to regulate")
            return cancelled_count
        
        for order in orders:
            try:
                # Only manage orders with our magic number
                if order.magic != magic_number:
                    continue
                
                # Create key for this order
                order_price = getattr(order, 'price', getattr(order, 'price_open', 0))
                order_volume = getattr(order, 'volume_current', getattr(order, 'volume_initial', 0))
                order_key = f"{order.symbol}_{order.type}_{order_price}_{order_volume}"
                
                # Check if this order should be kept
                if order_key not in pending_orders_to_keep:
                    print(f"      🔍 Found unauthorized pending order: Ticket #{order.ticket} - {order_key}")
                    
                    # Prepare cancel request
                    request = {
                        "action": mt5.TRADE_ACTION_REMOVE,
                        "order": order.ticket,
                        "magic": magic_number,
                        "comment": "Cancelled by regulation"
                    }
                    
                    # Send cancel request
                    result = mt5.order_send(request)
                    
                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        print(f"      ✅ Cancelled unauthorized order: Ticket #{order.ticket}")
                        cancelled_count += 1
                    else:
                        error_msg = result.comment if result else "Unknown error"
                        print(f"       Failed to cancel order #{order.ticket}: {error_msg}")
                        
            except Exception as e:
                print(f"      ⚠️ Error processing order for cancellation: {e}")
                continue
        
        if cancelled_count > 0:
            print(f"      🧹 Regulation complete: Cancelled {cancelled_count} unauthorized orders")
        
        return cancelled_count
    
    # =====================================================
    # SUB-FUNCTION: Check if order is too close to positions
    # =====================================================
    def is_order_too_close_to_positions(order_to_check, existing_positions, check_opposite=False):
        """
        Check if a pending order is too close to any existing open position
        using risk-based proximity detection with halved risk threshold.
        
        Performs two types of checks:
        1. SAME DIRECTION: Compares SELL orders with SELL positions, BUY with BUY
        2. OPPOSITE DIRECTION (optional): Compares SELL orders with BUY positions,
           BUY orders with SELL positions (if check_opposite=True)
        
        The risk threshold is HALF (position_risk / 2) for both check types.
        
        Args:
            order_to_check: Order dictionary from signals.json
            existing_positions: Dictionary of ALL existing positions from MT5
            check_opposite: Boolean, whether to check opposite directions
            
        Returns:
            tuple: (is_too_close, closest_position_details, reason, check_type)
        """
        symbol = order_to_check.get('symbol', '')
        order_type = order_to_check.get('order_type', '')
        entry_price = order_to_check.get('entry', 0)
        volume = order_to_check.get('volume', 0.01)
        
        # Determine direction of the pending order
        is_pending_buy = 'buy' in order_type.lower()
        is_pending_sell = 'sell' in order_type.lower()
        
        if not is_pending_buy and not is_pending_sell:
            return False, None, "Not a buy/sell order", "none"
        
        # Filter positions for this symbol only
        symbol_positions = []
        for pos_key, position in existing_positions.items():
            if position['symbol'] == symbol:
                symbol_positions.append(position)
        
        if not symbol_positions:
            return False, None, "No positions to check against", "none"
        
        print(f"          🔍 Checking against {len(symbol_positions)} existing positions for closeness...")
        
        # Check each position for closeness
        for position in symbol_positions:
            position_type = position['type']  # mt5.ORDER_TYPE_BUY or mt5.ORDER_TYPE_SELL
            position_entry = position['price']
            position_sl = position['sl']
            position_volume = position['volume']
            position_ticket = position['ticket']
            
            is_position_buy = (position_type == mt5.ORDER_TYPE_BUY)
            is_position_sell = (position_type == mt5.ORDER_TYPE_SELL)
            
            # =====================================================
            # DETERMINE WHICH CHECK TO PERFORM
            # =====================================================
            
            # CASE 1: SAME DIRECTION CHECK
            if (is_pending_buy and is_position_buy) or (is_pending_sell and is_position_sell):
                check_type = "same_direction"
                print(f"            ✅ Same direction: {'BUY' if is_pending_buy else 'SELL'} pending with {'BUY' if is_position_buy else 'SELL'} position #{position_ticket}")
                
                # Calculate position's own risk
                position_risk = 0
                if position_sl and position_sl > 0:
                    if is_position_buy:
                        # For buy position, risk is entry - SL
                        position_risk_profit = mt5.order_calc_profit(
                            mt5.ORDER_TYPE_BUY, symbol, position_volume,
                            position_entry, position_sl
                        )
                    else:  # sell position
                        # For sell position, risk is SL - entry
                        position_risk_profit = mt5.order_calc_profit(
                            mt5.ORDER_TYPE_SELL, symbol, position_volume,
                            position_entry, position_sl
                        )
                    
                    if position_risk_profit is not None:
                        position_risk = abs(position_risk_profit)
                
                if position_risk == 0:
                    print(f"            ⚠️ Position #{position_ticket} has no SL or risk calc failed - skipping closeness check")
                    continue
                
                # HALVE THE POSITION RISK FOR THRESHOLD
                risk_threshold = position_risk / 2
                
                print(f"            Position #{position_ticket}: {'BUY' if is_position_buy else 'SELL'} @ {position_entry}, Risk: ${position_risk:.2f}")
                print(f"            📊 Risk threshold (50%): ${risk_threshold:.2f}")
                
                # SAME DIRECTION RISK CALCULATION
                if is_pending_sell and is_position_sell:
                    if entry_price < position_entry:
                        # SELL pending below SELL position
                        print(f"            📐 SELL pending @ {entry_price} below SELL position @ {position_entry}")
                        print(f"            🧮 Calculating risk: Entry={entry_price}, Exit={position_entry}")
                        
                        potential_risk_profit = mt5.order_calc_profit(
                            mt5.ORDER_TYPE_SELL, symbol, volume,
                            entry_price, position_entry
                        )
                    else:
                        # SELL pending above SELL position
                        print(f"            📐 SELL pending @ {entry_price} above SELL position @ {position_entry}")
                        print(f"            🧮 Calculating risk: Entry={position_entry}, Exit={entry_price}")
                        
                        potential_risk_profit = mt5.order_calc_profit(
                            mt5.ORDER_TYPE_SELL, symbol, volume,
                            position_entry, entry_price
                        )
                    
                    if potential_risk_profit is not None:
                        potential_risk = abs(potential_risk_profit)
                        print(f"            💰 Potential risk if triggered: ${potential_risk:.2f}")
                        print(f"            📊 Position risk threshold: ${risk_threshold:.2f}")
                        
                        if potential_risk < risk_threshold:
                            print(f"             TOO CLOSE (same direction): ${potential_risk:.2f} < ${risk_threshold:.2f}")
                            return True, position, f"Too close to same-direction {('BUY' if is_position_buy else 'SELL')} position #{position_ticket}", check_type
                        else:
                            print(f"            ✅ SAFE DISTANCE: ${potential_risk:.2f} >= ${risk_threshold:.2f}")
                
                elif is_pending_buy and is_position_buy:
                    if entry_price > position_entry:
                        # BUY pending above BUY position
                        print(f"            📐 BUY pending @ {entry_price} above BUY position @ {position_entry}")
                        print(f"            🧮 Calculating risk: Entry={position_entry}, Exit={entry_price}")
                        
                        potential_risk_profit = mt5.order_calc_profit(
                            mt5.ORDER_TYPE_BUY, symbol, volume,
                            position_entry, entry_price
                        )
                    else:
                        # BUY pending below BUY position
                        print(f"            📐 BUY pending @ {entry_price} below BUY position @ {position_entry}")
                        print(f"            🧮 Calculating risk: Entry={entry_price}, Exit={position_entry}")
                        
                        potential_risk_profit = mt5.order_calc_profit(
                            mt5.ORDER_TYPE_BUY, symbol, volume,
                            entry_price, position_entry
                        )
                    
                    if potential_risk_profit is not None:
                        potential_risk = abs(potential_risk_profit)
                        print(f"            💰 Potential risk if triggered: ${potential_risk:.2f}")
                        print(f"            📊 Position risk threshold: ${risk_threshold:.2f}")
                        
                        if potential_risk < risk_threshold:
                            print(f"             TOO CLOSE (same direction): ${potential_risk:.2f} < ${risk_threshold:.2f}")
                            return True, position, f"Too close to same-direction {('BUY' if is_position_buy else 'SELL')} position #{position_ticket}", check_type
                        else:
                            print(f"            ✅ SAFE DISTANCE: ${potential_risk:.2f} >= ${risk_threshold:.2f}")
            
            # =====================================================
            # CASE 2: OPPOSITE DIRECTION CHECK (if enabled)
            # =====================================================
            elif check_opposite and ((is_pending_buy and is_position_sell) or (is_pending_sell and is_position_buy)):
                check_type = "opposite_direction"
                print(f"            🔄 Opposite direction: {'BUY' if is_pending_buy else 'SELL'} pending with {'SELL' if is_position_sell else 'BUY'} position #{position_ticket}")
                
                # Calculate position's own risk
                position_risk = 0
                if position_sl and position_sl > 0:
                    if is_position_buy:
                        # For buy position, risk is entry - SL
                        position_risk_profit = mt5.order_calc_profit(
                            mt5.ORDER_TYPE_BUY, symbol, position_volume,
                            position_entry, position_sl
                        )
                    else:  # sell position
                        # For sell position, risk is SL - entry
                        position_risk_profit = mt5.order_calc_profit(
                            mt5.ORDER_TYPE_SELL, symbol, position_volume,
                            position_entry, position_sl
                        )
                    
                    if position_risk_profit is not None:
                        position_risk = abs(position_risk_profit)
                
                if position_risk == 0:
                    print(f"            ⚠️ Position #{position_ticket} has no SL or risk calc failed - skipping closeness check")
                    continue
                
                # HALVE THE POSITION RISK FOR THRESHOLD
                risk_threshold = position_risk / 2
                
                print(f"            Position #{position_ticket}: {'BUY' if is_position_buy else 'SELL'} @ {position_entry}, Risk: ${position_risk:.2f}")
                print(f"            📊 Risk threshold (50%): ${risk_threshold:.2f}")
                
                # OPPOSITE DIRECTION RISK CALCULATION
                # We calculate the risk if both orders were to move toward each other
                
                if is_pending_buy and is_position_sell:
                    # Pending BUY order vs existing SELL position
                    # They are moving in opposite directions
                    # The risk scenario: BUY pending triggers, price goes down to SELL position's entry
                    
                    if entry_price > position_entry:
                        # BUY pending above SELL position
                        print(f"            📐 BUY pending @ {entry_price} above SELL position @ {position_entry}")
                        print(f"            🧮 Calculating opposite risk: Entry={position_entry}, Exit={entry_price}")
                        
                        # Risk = from SELL position's entry to BUY pending's entry
                        potential_risk_profit = mt5.order_calc_profit(
                            mt5.ORDER_TYPE_SELL, symbol, min(volume, position_volume),
                            position_entry, entry_price
                        )
                    else:
                        # BUY pending below SELL position
                        print(f"            📐 BUY pending @ {entry_price} below SELL position @ {position_entry}")
                        print(f"            🧮 Calculating opposite risk: Entry={entry_price}, Exit={position_entry}")
                        
                        # Risk = from BUY pending's entry to SELL position's entry
                        potential_risk_profit = mt5.order_calc_profit(
                            mt5.ORDER_TYPE_BUY, symbol, min(volume, position_volume),
                            entry_price, position_entry
                        )
                    
                    if potential_risk_profit is not None:
                        potential_risk = abs(potential_risk_profit)
                        print(f"            💰 Potential opposite risk: ${potential_risk:.2f}")
                        print(f"            📊 Position risk threshold: ${risk_threshold:.2f}")
                        
                        if potential_risk < risk_threshold:
                            print(f"             TOO CLOSE (opposite direction): ${potential_risk:.2f} < ${risk_threshold:.2f}")
                            return True, position, f"Too close to opposite-direction SELL position #{position_ticket}", check_type
                        else:
                            print(f"            ✅ SAFE DISTANCE (opposite): ${potential_risk:.2f} >= ${risk_threshold:.2f}")
                
                elif is_pending_sell and is_position_buy:
                    # Pending SELL order vs existing BUY position
                    
                    if entry_price < position_entry:
                        # SELL pending below BUY position
                        print(f"            📐 SELL pending @ {entry_price} below BUY position @ {position_entry}")
                        print(f"            🧮 Calculating opposite risk: Entry={entry_price}, Exit={position_entry}")
                        
                        # Risk = from SELL pending's entry to BUY position's entry
                        potential_risk_profit = mt5.order_calc_profit(
                            mt5.ORDER_TYPE_SELL, symbol, min(volume, position_volume),
                            entry_price, position_entry
                        )
                    else:
                        # SELL pending above BUY position
                        print(f"            📐 SELL pending @ {entry_price} above BUY position @ {position_entry}")
                        print(f"            🧮 Calculating opposite risk: Entry={position_entry}, Exit={entry_price}")
                        
                        # Risk = from BUY position's entry to SELL pending's entry
                        potential_risk_profit = mt5.order_calc_profit(
                            mt5.ORDER_TYPE_BUY, symbol, min(volume, position_volume),
                            position_entry, entry_price
                        )
                    
                    if potential_risk_profit is not None:
                        potential_risk = abs(potential_risk_profit)
                        print(f"            💰 Potential opposite risk: ${potential_risk:.2f}")
                        print(f"            📊 Position risk threshold: ${risk_threshold:.2f}")
                        
                        if potential_risk < risk_threshold:
                            print(f"             TOO CLOSE (opposite direction): ${potential_risk:.2f} < ${risk_threshold:.2f}")
                            return True, position, f"Too close to opposite-direction BUY position #{position_ticket}", check_type
                        else:
                            print(f"            ✅ SAFE DISTANCE (opposite): ${potential_risk:.2f} >= ${risk_threshold:.2f}")
            
            else:
                # Skip if not matching either check type
                continue
        
        return False, None, "All positions are at safe distance", "none"

    # =====================================================
    # SUB-FUNCTION: Check if order exists
    # =====================================================
    def order_exists(order_to_check, existing_orders, existing_positions):
        """
        Check if an order already exists in MT5 (either pending or as open position).
        
        Args:
            order_to_check: Order dictionary from signals.json
            existing_orders: Dictionary of ALL existing pending orders from MT5
            existing_positions: Dictionary of ALL existing positions from MT5
            
        Returns:
            tuple: (exists, type) where type is 'pending', 'position', or None
        """
        order_type = order_to_check.get('order_type', '')
        entry_price = order_to_check.get('entry', 0)
        volume = order_to_check.get('volume', 0.01)
        symbol = order_to_check.get('symbol', '')
        
        # Round volume to avoid floating point precision issues
        volume = round(volume, 2)
        
        # Map order type string to MT5 order type for pending orders
        mt5_pending_type = None
        if order_type == 'buy_stop':
            mt5_pending_type = mt5.ORDER_TYPE_BUY_STOP
        elif order_type == 'buy_limit':
            mt5_pending_type = mt5.ORDER_TYPE_BUY_LIMIT
        elif order_type == 'sell_stop':
            mt5_pending_type = mt5.ORDER_TYPE_SELL_STOP
        elif order_type == 'sell_limit':
            mt5_pending_type = mt5.ORDER_TYPE_SELL_LIMIT
        
        # Map order type string to MT5 position type
        mt5_position_type = None
        if order_type in ['buy_stop', 'buy_limit']:
            mt5_position_type = mt5.ORDER_TYPE_BUY
        elif order_type in ['sell_stop', 'sell_limit']:
            mt5_position_type = mt5.ORDER_TYPE_SELL
        
        # Check pending orders first
        if mt5_pending_type:
            pending_key = f"{symbol}_{mt5_pending_type}_{entry_price}_{volume}"
            if pending_key in existing_orders:
                print(f"          🔍 Found duplicate PENDING: {symbol} {order_type} @ {entry_price}")
                return True, 'pending'
        
        # Check open positions
        if mt5_position_type:
            position_key = f"{symbol}_{mt5_position_type}_{entry_price}_{volume}"
            if position_key in existing_positions:
                print(f"          🔍 Found duplicate POSITION: {symbol} {order_type} @ {entry_price}")
                return True, 'position'
        
        return False, None
    
    # =====================================================
    # SUB-FUNCTION: Convert order type logic
    # =====================================================
    def convert_order_type_logic(order_type):
        """
        Convert order type according to new logic:
        - buy_stop → sell_limit
        - sell_stop → buy_limit
        - buy_limit → sell_stop (if needed for other conversions)
        - sell_limit → buy_stop (if needed for other conversions)
        
        Args:
            order_type: Original order type string
            
        Returns:
            str: Converted order type
        """
        conversion_map = {
            'buy_stop': 'sell_limit',
            'sell_stop': 'buy_limit',
            'buy_limit': 'sell_stop',
            'sell_limit': 'buy_stop'
        }
        return conversion_map.get(order_type, order_type)
    
    # =====================================================
    # SUB-FUNCTION: Get valid price for conversion
    # =====================================================
    def get_valid_price_for_conversion(original_order_type, target_order_type, current_price, original_entry):
        """
        Get a valid price for the converted order type.
        
        Args:
            original_order_type: Original order type
            target_order_type: Target order type after conversion
            current_price: Current market price (bid or ask as appropriate)
            original_entry: Original entry price
            
        Returns:
            float: Valid price for the target order type
        """
        # For buy orders (now converted to sell orders)
        if target_order_type == 'sell_limit':
            # Sell limit must be above bid - use original price if it's above bid, otherwise use bid + 1 pip
            if original_entry > current_price:
                return original_entry
            else:
                # Use current price plus a small buffer (1 point)
                return current_price + 0.01
        
        elif target_order_type == 'sell_stop':
            # Sell stop must be below bid - use original price if it's below bid, otherwise use bid - 1 pip
            if original_entry < current_price:
                return original_entry
            else:
                # Use current price minus a small buffer (1 point)
                return current_price - 0.01
        
        # For sell orders (now converted to buy orders)
        elif target_order_type == 'buy_limit':
            # Buy limit must be below ask - use original price if it's below ask, otherwise use ask - 1 pip
            if original_entry < current_price:
                return original_entry
            else:
                # Use current price minus a small buffer (1 point)
                return current_price - 0.01
        
        elif target_order_type == 'buy_stop':
            # Buy stop must be above ask - use original price if it's above ask, otherwise use ask + 1 pip
            if original_entry > current_price:
                return original_entry
            else:
                # Use current price plus a small buffer (1 point)
                return current_price + 0.01
        
        return original_entry
    
    # =====================================================
    # SUB-FUNCTION: Get current price
    # =====================================================
    def get_current_price(symbol):
        """
        Get current market price for a symbol.
        
        Args:
            symbol: Symbol name
            
        Returns:
            tuple: (bid, ask) current prices or (None, None) if error
        """
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None, None
        return tick.bid, tick.ask
    
    # =====================================================
    # SUB-FUNCTION: Place exact order type
    # =====================================================
    def place_exact_order_type(order_data, investor_root, is_counter=False, is_converted=False):
        """
        Place an order in MT5 with the exact order type and price.
        
        Args:
            order_data: Dictionary with order parameters
            investor_root: Path to investor root for history recording
            is_counter: Boolean indicating if this is a counter order
            is_converted: Boolean indicating if this is a converted order type
            
        Returns:
            tuple: (success, order_result, error_message, final_order_type, final_price)
        """
        try:
            # Prepare order request
            symbol = order_data.get('symbol')
            order_type = order_data.get('order_type')
            volume = order_data.get('volume', 0.01)
            entry_price = order_data.get('entry')
            stoploss = order_data.get('exit')
            comment = order_data.get('comment', '')
            magic = order_data.get('magic', 0)
            
            # Map order type string to MT5 order type
            if order_type == 'buy_stop':
                mt5_type = mt5.ORDER_TYPE_BUY_STOP
                order_direction = "BUY STOP"
            elif order_type == 'buy_limit':
                mt5_type = mt5.ORDER_TYPE_BUY_LIMIT
                order_direction = "BUY LIMIT"
            elif order_type == 'sell_stop':
                mt5_type = mt5.ORDER_TYPE_SELL_STOP
                order_direction = "SELL STOP"
            elif order_type == 'sell_limit':
                mt5_type = mt5.ORDER_TYPE_SELL_LIMIT
                order_direction = "SELL LIMIT"
            else:
                return False, None, f"Invalid order type: {order_type}", order_type, entry_price
            
            # Get symbol info
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                return False, None, f"Cannot get symbol info for {symbol}", order_type, entry_price
            
            # Prepare the request
            request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": symbol,
                "volume": float(volume),
                "type": mt5_type,
                "price": float(entry_price),
                "sl": float(stoploss) if stoploss else 0.0,
                "tp": 0.0,
                "deviation": 20,
                "magic": magic,
                "comment": comment[:31] if comment else f"{'COUNTER' if is_counter else 'MAIN'}{' (CONVERTED)' if is_converted else ''}",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_RETURN,
            }
            
            # Send order
            result = mt5.order_send(request)
            
            # Check if result is None
            if result is None:
                error_code = mt5.last_error()
                error_msg = f"Order send failed: {error_code}"
                print(f"           {error_msg}")
                return False, None, error_msg, order_type, entry_price
            
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                error_msg = f"Order failed: {result.comment} (code: {result.retcode})"
                print(f"           {error_msg}")
                return False, None, error_msg, order_type, entry_price
            
            print(f"          ✅ {order_direction} placed successfully: Ticket #{result.order}{' (CONVERTED)' if is_converted else ''} at {entry_price:.2f}")
            print(f"          ℹ️ This is a PENDING ORDER - will auto-execute when price reaches {entry_price}")
            
            # RECORD TRADE IN HISTORY
            record_trade_in_history(investor_root, order_data, result, is_counter, is_converted, entry_price, order_type)
            
            return True, result, None, order_type, entry_price
            
        except Exception as e:
            error_msg = f"Exception placing order: {str(e)}"
            print(f"           {error_msg}")
            return False, None, error_msg, order_data.get('order_type', 'unknown'), order_data.get('entry', 0)
    
    # =====================================================
    # SUB-FUNCTION: Convert and place order
    # =====================================================
    def convert_and_place_order(order_data, original_error, investor_root, is_counter=False, conversion_attempts=0, existing_pending_orders=None, existing_positions=None):
        """
        Convert order type and place with adjusted price when original order fails.
        NEW LOGIC: Convert stop orders to limit orders:
        - buy_stop → sell_limit
        - sell_stop → buy_limit
        
        Also handles existing stop orders by modifying them to limit orders.
        
        Args:
            order_data: Original order dictionary
            original_error: Original error message
            investor_root: Path to investor root for history recording
            is_counter: Boolean indicating if this is a counter order
            conversion_attempts: Number of conversion attempts already made
            existing_pending_orders: Dictionary of existing pending orders to check/modify
            existing_positions: Dictionary of existing positions to check/modify
            
        Returns:
            tuple: (success, order_result, error_message, was_converted, final_order_type, final_price)
        """
        if conversion_attempts >= 2:
            return False, None, f"Max conversion attempts reached. Original error: {original_error}", False, order_data.get('order_type'), order_data.get('entry')
        
        symbol = order_data.get('symbol')
        original_order_type = order_data.get('order_type')
        entry_price = order_data.get('entry')
        stoploss = order_data.get('exit')
        volume = round(order_data.get('volume', 0.01), 2)
        magic = order_data.get('magic', 0)
        
        # Get current price for conversion
        bid, ask = get_current_price(symbol)
        
        # Convert order type using new logic
        converted_type = convert_order_type_logic(original_order_type)
        
        # Determine which price to use based on converted order type
        if 'sell' in converted_type:
            # For sell orders, use bid price
            current_price = bid
        else:
            # For buy orders, use ask price
            current_price = ask
        
        # Get valid price for converted order
        valid_price = get_valid_price_for_conversion(original_order_type, converted_type, current_price, entry_price)
        
        print(f"          🔄 CONVERTING {original_order_type.upper()} @ {entry_price:.2f} → {converted_type.upper()} @ {valid_price:.2f}")
        print(f"          ℹ️ Original stop order will NOT be placed - only converted limit order will be placed")
        
        # =====================================================
        # CHECK FOR EXISTING STOP ORDERS TO CONVERT
        # =====================================================
        existing_stop_orders_found = []
        
        # Check if there are existing pending stop orders of the original type
        if existing_pending_orders:
            # Map original order type to MT5 order type
            original_mt5_type = None
            if original_order_type == 'buy_stop':
                original_mt5_type = mt5.ORDER_TYPE_BUY_STOP
            elif original_order_type == 'sell_stop':
                original_mt5_type = mt5.ORDER_TYPE_SELL_STOP
            elif original_order_type == 'buy_limit':
                original_mt5_type = mt5.ORDER_TYPE_BUY_LIMIT
            elif original_order_type == 'sell_limit':
                original_mt5_type = mt5.ORDER_TYPE_SELL_LIMIT
            
            # Look for existing pending stop orders with the same parameters
            if original_mt5_type:
                for order_key, pending_order in existing_pending_orders.items():
                    if (pending_order['symbol'] == symbol and 
                        pending_order['type'] == original_mt5_type and
                        abs(pending_order['price'] - entry_price) < 0.01 and  # Small tolerance for price
                        abs(pending_order['volume'] - volume) < 0.01):  # Small tolerance for volume
                        
                        existing_stop_orders_found.append(pending_order)
                        print(f"          🔍 Found existing pending stop order: Ticket #{pending_order['ticket']}")
        
        # =====================================================
        # HANDLE EXISTING STOP ORDERS BY MODIFYING THEM
        # =====================================================
        if existing_stop_orders_found:
            print(f"          🔄 Found {len(existing_stop_orders_found)} existing stop orders to convert/modify")
            
            # Process each existing stop order
            for existing_order in existing_stop_orders_found:
                print(f"          📝 Modifying existing order Ticket #{existing_order['ticket']}...")
                
                # Step 1: Remove the existing order
                remove_request = {
                    "action": mt5.TRADE_ACTION_REMOVE,
                    "order": existing_order['ticket'],
                    "magic": magic,
                    "comment": "Removed for conversion"
                }
                
                remove_result = mt5.order_send(remove_request)
                
                if remove_result and remove_result.retcode == mt5.TRADE_RETCODE_DONE:
                    print(f"          ✅ Removed existing stop order Ticket #{existing_order['ticket']} for conversion")
                    
                    # Step 2: Create converted order data
                    converted_order = order_data.copy()
                    converted_order['order_type'] = converted_type
                    converted_order['entry'] = valid_price
                    
                    # Adjust stoploss proportionally if present
                    if stoploss:
                        original_distance = abs(entry_price - stoploss)
                        if 'sell' in converted_type:
                            converted_order['exit'] = valid_price + original_distance
                        else:
                            converted_order['exit'] = valid_price - original_distance
                    
                    # Step 3: Place the new converted order
                    print(f"          📤 Placing converted order: {converted_type} @ {valid_price:.2f}")
                    success, result, error, final_type, final_price = place_exact_order_type(
                        converted_order, investor_root, is_counter, True
                    )
                    
                    if success:
                        print(f"          ✅ SUCCESSFULLY CONVERTED EXISTING STOP ORDER: Ticket #{existing_order['ticket']} → {converted_type.upper()} @ {valid_price:.2f}")
                        
                        # Update existing_pending_orders dictionary
                        if existing_pending_orders is not None:
                            # Remove old order from dictionary
                            old_key = f"{symbol}_{original_mt5_type}_{entry_price}_{volume}"
                            if old_key in existing_pending_orders:
                                del existing_pending_orders[old_key]
                            
                            # Add new order to dictionary
                            new_mt5_type = None
                            if converted_type == 'buy_stop':
                                new_mt5_type = mt5.ORDER_TYPE_BUY_STOP
                            elif converted_type == 'buy_limit':
                                new_mt5_type = mt5.ORDER_TYPE_BUY_LIMIT
                            elif converted_type == 'sell_stop':
                                new_mt5_type = mt5.ORDER_TYPE_SELL_STOP
                            elif converted_type == 'sell_limit':
                                new_mt5_type = mt5.ORDER_TYPE_SELL_LIMIT
                            
                            if new_mt5_type:
                                new_key = f"{symbol}_{new_mt5_type}_{valid_price}_{volume}"
                                existing_pending_orders[new_key] = {
                                    'ticket': result.order,
                                    'symbol': symbol,
                                    'type': new_mt5_type,
                                    'price': valid_price,
                                    'volume': volume,
                                    'type_string': "PENDING"
                                }
                        
                        return success, result, error, True, final_type, final_price
                    else:
                        print(f"           Failed to place converted order after removing existing stop order: {error}")
                        return False, None, f"Failed to place converted order after removal: {error}", False, original_order_type, entry_price
                else:
                    error_msg = remove_result.comment if remove_result else "Unknown error"
                    print(f"           Failed to remove existing stop order Ticket #{existing_order['ticket']}: {error_msg}")
                    return False, None, f"Failed to remove existing stop order: {error_msg}", False, original_order_type, entry_price
        
        # =====================================================
        # CREATE NEW CONVERTED ORDER (NO EXISTING STOP ORDERS)
        # =====================================================
        # Create converted order data
        converted_order = order_data.copy()
        converted_order['order_type'] = converted_type
        converted_order['entry'] = valid_price
        
        # Adjust stoploss proportionally if present
        if stoploss:
            original_distance = abs(entry_price - stoploss)
            if 'sell' in converted_type:
                converted_order['exit'] = valid_price + original_distance
            else:
                converted_order['exit'] = valid_price - original_distance
        
        # Try to place the converted order
        success, result, error, final_type, final_price = place_exact_order_type(
            converted_order, investor_root, is_counter, True
        )
        
        if success:
            print(f"          ✅ SUCCESSFULLY CONVERTED AND PLACED: {original_order_type.upper()} → {converted_type.upper()}")
            return success, result, error, True, final_type, final_price
        else:
            # If conversion fails, try one more time with different adjustment
            if conversion_attempts < 1:
                print(f"          🔄 First conversion attempt failed, trying alternative adjustment...")
                # Adjust price differently based on converted order type
                if converted_type in ['buy_limit', 'sell_stop']:
                    # Need lower price
                    valid_price = current_price - 0.02
                else:
                    # Need higher price
                    valid_price = current_price + 0.02
                
                converted_order['entry'] = valid_price
                if stoploss:
                    original_distance = abs(entry_price - stoploss)
                    if 'sell' in converted_type:
                        converted_order['exit'] = valid_price + original_distance
                    else:
                        converted_order['exit'] = valid_price - original_distance
                
                success, result, error, final_type, final_price = place_exact_order_type(
                    converted_order, investor_root, is_counter, True
                )
                
                if success:
                    print(f"          ✅ SUCCESSFULLY CONVERTED AND PLACED (alternative): {original_order_type.upper()} → {converted_type.upper()}")
                    return success, result, error, True, final_type, final_price
            
            return False, None, f"Conversion failed: {error}", False, original_order_type, entry_price

    # =====================================================
    # SUB-FUNCTION: Convert existing stop orders
    # =====================================================
    def convert_existing_stop_orders(symbol, magic_number, existing_orders, allow_conversion=True):
        """
        Helper function to convert all existing stop orders to limit orders.
        Scans all pending orders and converts buy_stop → sell_limit and sell_stop → buy_limit.
        
        Args:
            symbol: Symbol to check
            magic_number: Magic number to identify orders
            existing_orders: Dictionary of existing pending orders
            allow_conversion: Whether conversion is allowed
            
        Returns:
            int: Number of orders converted
        """
        if not allow_conversion:
            return 0
        
        converted_count = 0
        orders_to_convert = []
        
        # Get all pending orders for this symbol and magic number
        orders = mt5.orders_get(symbol=symbol)
        if orders is None:
            return 0
        
        for order in orders:
            # Only manage orders with our magic number
            if order.magic != magic_number:
                continue
            
            # Check if this is a stop order that needs conversion
            order_type = order.type
            should_convert = False
            target_type = None
            
            if order_type == mt5.ORDER_TYPE_BUY_STOP:
                should_convert = True
                target_type = mt5.ORDER_TYPE_SELL_LIMIT
                print(f"      🔄 Found BUY_STOP order #{order.ticket} to convert to SELL_LIMIT")
            elif order_type == mt5.ORDER_TYPE_SELL_STOP:
                should_convert = True
                target_type = mt5.ORDER_TYPE_BUY_LIMIT
                print(f"      🔄 Found SELL_STOP order #{order.ticket} to convert to BUY_LIMIT")
            
            if should_convert:
                orders_to_convert.append({
                    'order': order,
                    'target_type': target_type
                })
        
        # Convert each order
        for convert_info in orders_to_convert:
            order = convert_info['order']
            target_type = convert_info['target_type']
            
            # Get current price for conversion
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                print(f"      ⚠️ Could not get price for {symbol}, skipping conversion")
                continue
            
            current_price = tick.ask if target_type in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP] else tick.bid
            
            # Calculate new price (simple conversion - use same price or adjust)
            original_price = order.price
            new_price = original_price
            
            # Ensure price is valid for the target order type
            if target_type == mt5.ORDER_TYPE_SELL_LIMIT:
                # Sell limit must be above current price
                if new_price <= current_price:
                    new_price = current_price + 0.01  # Add 1 point buffer
            elif target_type == mt5.ORDER_TYPE_BUY_LIMIT:
                # Buy limit must be below current price
                if new_price >= current_price:
                    new_price = current_price - 0.01  # Subtract 1 point buffer
            
            print(f"      🔄 Converting order #{order.ticket}: {order_type_to_string(order.type)} @ {original_price} → {order_type_to_string(target_type)} @ {new_price}")
            
            # Step 1: Remove existing order
            remove_request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": order.ticket,
                "magic": magic_number,
                "comment": "Removed for conversion"
            }
            
            remove_result = mt5.order_send(remove_request)
            
            if remove_result and remove_result.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"      ✅ Removed original stop order #{order.ticket}")
                
                # Step 2: Place new converted order
                request = {
                    "action": mt5.TRADE_ACTION_PENDING,
                    "symbol": symbol,
                    "volume": order.volume_current,
                    "type": target_type,
                    "price": new_price,
                    "sl": order.sl,
                    "tp": order.tp,
                    "deviation": 20,
                    "magic": magic_number,
                    "comment": f"Converted from {order_type_to_string(order.type)}",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_RETURN,
                }
                
                result = mt5.order_send(request)
                
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    print(f"      ✅ Successfully placed converted order: Ticket #{result.order}")
                    converted_count += 1
                    
                    # Update the existing_orders dictionary
                    if existing_orders is not None:
                        # Remove old order from dict
                        old_key = f"{symbol}_{order.type}_{original_price}_{round(order.volume_current, 2)}"
                        if old_key in existing_orders:
                            del existing_orders[old_key]
                        
                        # Add new order to dict
                        new_key = f"{symbol}_{target_type}_{new_price}_{round(order.volume_current, 2)}"
                        existing_orders[new_key] = {
                            'ticket': result.order,
                            'symbol': symbol,
                            'type': target_type,
                            'price': new_price,
                            'volume': order.volume_current,
                            'type_string': "PENDING"
                        }
                else:
                    error_msg = result.comment if result else "Unknown error"
                    print(f"       Failed to place converted order: {error_msg}")
            else:
                error_msg = remove_result.comment if remove_result else "Unknown error"
                print(f"       Failed to remove order #{order.ticket}: {error_msg}")
        
        return converted_count

    # =====================================================
    # SUB-FUNCTION: Order type to string helper
    # =====================================================
    def order_type_to_string(order_type):
        """Helper to convert MT5 order type to string"""
        type_map = {
            mt5.ORDER_TYPE_BUY_STOP: "BUY_STOP",
            mt5.ORDER_TYPE_SELL_STOP: "SELL_STOP",
            mt5.ORDER_TYPE_BUY_LIMIT: "BUY_LIMIT",
            mt5.ORDER_TYPE_SELL_LIMIT: "SELL_LIMIT",
            mt5.ORDER_TYPE_BUY: "BUY",
            mt5.ORDER_TYPE_SELL: "SELL"
        }
        return type_map.get(order_type, "UNKNOWN")

    # =====================================================
    # SUB-FUNCTION: Process single order with history recording
    # =====================================================
    def process_single_order(order, symbol, magic_number, investor_root, existing_orders, existing_positions, 
                        is_counter=False, allow_conversion=False, check_opposite=False):
        """
        Process and place a single order with enhanced conversion that handles existing orders.
        """
        # Add symbol and magic to order data
        order['symbol'] = symbol
        order['magic'] = magic_number
        
        # STEP 0: Convert any existing stop orders before processing
        if allow_conversion:
            print(f"          🔄 Checking for existing stop orders to convert...")
            converted_count = convert_existing_stop_orders(symbol, magic_number, existing_orders, allow_conversion)
            if converted_count > 0:
                print(f"          ✅ Converted {converted_count} existing stop orders to limit orders")
                # Refresh existing_orders after conversion
                existing_orders = get_all_existing_pending_orders()
        
        # STEP 1: Check if order already exists (either pending or as position)
        exists, exists_type = order_exists(order, existing_orders, existing_positions)
        
        if exists:
            order_type = order.get('order_type', 'unknown')
            entry = order.get('entry', 0)
            if exists_type == 'pending':
                print(f"          ⏭️ {'Counter' if is_counter else 'Main'} {order_type} @ {entry} - SKIP (already exists as PENDING order)")
                return False, None, None, True, 'pending', False, entry, 'duplicate_pending'
            else:  # position
                print(f"          ⏭️ {'Counter' if is_counter else 'Main'} {order_type} @ {entry} - SKIP (already exists as OPEN POSITION)")
                return False, None, None, True, 'position', False, entry, 'duplicate_position'
        
        # STEP 2: Check if order is too close to any existing position - SAME DIRECTION first
        is_too_close_same, close_position_same, close_reason_same, check_type_same = is_order_too_close_to_positions(
            order, existing_positions, check_opposite=False
        )
        
        if is_too_close_same:
            order_type = order.get('order_type', 'unknown')
            entry = order.get('entry', 0)
            print(f"          ⏭️ {'Counter' if is_counter else 'Main'} {order_type} @ {entry} - SKIP (too close to same-direction position)")
            print(f"          📋 Reason: {close_reason_same}")
            return False, None, None, True, 'too_close_same', False, entry, 'same_direction'
        
        # STEP 3: Check opposite direction if enabled
        if check_opposite:
            is_too_close_opposite, close_position_opposite, close_reason_opposite, check_type_opposite = is_order_too_close_to_positions(
                order, existing_positions, check_opposite=True
            )
            
            if is_too_close_opposite:
                order_type = order.get('order_type', 'unknown')
                entry = order.get('entry', 0)
                print(f"          ⏭️ {'Counter' if is_counter else 'Main'} {order_type} @ {entry} - SKIP (too close to opposite-direction position)")
                print(f"          📋 Reason: {close_reason_opposite}")
                return False, None, None, True, 'too_close_opposite', False, entry, 'opposite_direction'
        
        # STEP 4: Place the order with potential conversion BEFORE placement
        order_type = order.get('order_type', 'unknown')
        entry = order.get('entry', 0)
        
        # Check if this is a stop order that needs conversion BEFORE placement attempt
        should_convert_preemptively = allow_conversion and (order_type in ['buy_stop', 'sell_stop'])
        
        if should_convert_preemptively:
            print(f"          🔄 CONVERSION MODE ACTIVE: {order_type.upper()} will be converted to opposite limit order")
            print(f"          ℹ️ Original stop order will NOT be placed - only converted limit order will be attempted")
            
            # Convert the order before trying to place (pass existing_orders and existing_positions for conversion)
            success, result, error, was_converted, final_type, final_price = convert_and_place_order(
                order, "Preemptive conversion", investor_root, is_counter, 0, existing_orders, existing_positions
            )
            return success, result, error, False, None, was_converted, final_price, 'pre_converted'
        
        else:
            # No pre-conversion needed, try to place the original order type
            print(f"          📤 Placing {'counter' if is_counter else 'main'} {order_type} @ {entry}...")
            
            # Try to place the exact order type
            success, result, error, final_type, final_price = place_exact_order_type(order, investor_root, is_counter, False)
            
            # If failed due to invalid price, check if conversion is allowed (for non-stop orders)
            if not success and error and ("Invalid price" in error or "10015" in error):
                if allow_conversion:
                    print(f"          🔄 Invalid price detected and conversion is ALLOWED, attempting conversion...")
                    success, result, error, was_converted, final_type, final_price = convert_and_place_order(
                        order, error, investor_root, is_counter, 0, existing_orders, existing_positions
                    )
                    return success, result, error, False, None, was_converted, final_price, 'converted'
                else:
                    print(f"          ⚠️ Invalid price detected but conversion is NOT ALLOWED (allow_order_type_conversion=false)")
                    print(f"           Order failed permanently: {error}")
                    return False, None, error, False, None, False, final_price, 'conversion_skipped'
            
            return success, result, error, False, None, False, final_price, 'placed'
    
    # =====================================================
    # MAIN EXECUTION
    # =====================================================
    def main():
        # Statistics for this run
        stats = {
            "investor_id": inv_id if inv_id else "all",
            "investors_processed": 0,
            "investors_skipped_due_to_settings": 0,
            "investors_skipped_due_to_position_flag": 0,
            "symbols_processed": 0,
            "orders_attempted": 0,
            "orders_placed": 0,
            "orders_skipped_duplicate_pending": 0,
            "orders_skipped_duplicate_position": 0,
            "orders_skipped_too_close_same_direction": 0,
            "orders_skipped_too_close_opposite_direction": 0,
            "orders_failed": 0,
            "orders_converted_and_placed": 0,
            "orders_conversion_skipped_permission": 0,
            "orders_cancelled_during_regulation": 0,
            "main_orders_placed": 0,
            "counter_orders_placed": 0,
            "counter_orders_skipped": 0,
            "counter_orders_failed": 0,
            "total_active_pending": 0,
            "total_open_positions": 0,
            "placement_errors": [],
            "symbol_details": {},
            "trades_recorded": 0
        }
        
        if inv_id:
            inv_root = get_investor_root(inv_id)
            prices_dir = inv_root / "prices"
            
            # Path to accountmanagement.json and signals.json
            acc_mgmt_path = inv_root / "accountmanagement.json"
            signals_path = prices_dir / "signals.json"
            
            # =====================================================
            # STEP 1: CALL manage_single_position_and_pending FIRST
            # =====================================================
            print(f"\n [{inv_id}] 🔍 Checking single position/pending management flag...")
            
            # Call the function to get the upload_orders flag
            try:
                # Import the function (assuming it's in the same module or imported)
                # If it's in the same file, just call it directly
                management_result = manage_position_and_pending_orders(inv_id=inv_id)
                upload_orders_flag = management_result.get("upload_orders", True)
                stats["upload_orders_flag"] = upload_orders_flag
                
                print(f" [{inv_id}] 🚩 upload_orders flag: {upload_orders_flag}")
                
                # If upload_orders is False, skip order placement entirely
                if not upload_orders_flag:
                    print(f" [{inv_id}] ⏭️ SKIPPING order placement - position with close opposite order exists")
                    print(f"     Reason: A position with a close opposite pending order was found and kept")
                    stats["investors_skipped_due_to_position_flag"] += 1
                    return stats
                else:
                    print(f" [{inv_id}] ✅ PROCEEDING with order placement - no conflicting position/order pair found")
                    
            except Exception as e:
                print(f" [{inv_id}] ⚠️ Could not check manage_single_position_and_pending: {e}")
                print(f" [{inv_id}] ⏭️ Proceeding with order placement by default (upload_orders assumed True)")
                stats["upload_orders_flag"] = True  # Default to True if function fails
            
            # =====================================================
            # STEP 2: Check account management settings
            # =====================================================
            print(f"\n [{inv_id}] 🔍 Checking account management settings...")
            
            if not acc_mgmt_path.exists():
                print(f" [{inv_id}] ⚠️ accountmanagement.json not found at {acc_mgmt_path}")
                print(f" [{inv_id}] ⏭️ Skipping order placement (no settings to check)")
                stats["investors_skipped_due_to_settings"] += 1
                return stats
            
            try:
                with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                    acc_config = json.load(f)
                
                # Check if auto trading is enabled
                settings = acc_config.get("settings", {})
                enable_auto_trading = settings.get("enable_auto_trading", False)
                
                if not enable_auto_trading:
                    print(f" [{inv_id}] ⏭️ Auto trading is DISABLED in accountmanagement.json")
                    print(f"     (settings.enable_auto_trading = false)")
                    stats["investors_skipped_due_to_settings"] += 1
                    return stats
                
                # Check if order type conversion is allowed
                allow_order_type_conversion = settings.get("enable_order_type_conversion", False)
                
                # Check if opposite order restriction is enabled
                opposite_order_restriction = settings.get("opposite_order_restriction", False)
                
                # Get trading parameters
                max_spread = settings.get("max_spread", 50)
                max_slippage = settings.get("max_slippage", 20)
                order_ttl = settings.get("order_ttl", 3600)
                
                print(f" [{inv_id}] ✅ Auto trading is ENABLED")
                print(f"     • Order type conversion: {'ALLOWED' if allow_order_type_conversion else 'NOT ALLOWED'}")
                print(f"     • Opposite order restriction: {'ENABLED' if opposite_order_restriction else 'DISABLED'}")
                print(f"     • Max spread: {max_spread} points")
                print(f"     • Max slippage: {max_slippage} points")
                print(f"     • Order TTL: {order_ttl} seconds")
                print(f"     • Pending orders: Will auto-execute when price reaches entry level")
                print(f"     • Conversion logic: STOP → LIMIT (buy_stop→sell_limit, sell_stop→buy_limit)")
                
                stats["investors_processed"] += 1
                
            except json.JSONDecodeError as e:
                print(f" [{inv_id}]  Invalid JSON in accountmanagement.json: {e}")
                print(f" [{inv_id}] ⏭️ Skipping order placement due to config error")
                stats["investors_skipped_due_to_settings"] += 1
                return stats
            except Exception as e:
                print(f" [{inv_id}]  Error reading accountmanagement.json: {e}")
                print(f" [{inv_id}] ⏭️ Skipping order placement due to config error")
                stats["investors_skipped_due_to_settings"] += 1
                return stats
            
            # Continue with order placement if enabled
            if not signals_path.exists():
                print(f" [{inv_id}]  signals.json not found at {signals_path}")
                return stats
            
            try:
                print(f" [{inv_id}] 📂 Loading signals.json...")
                with open(signals_path, 'r', encoding='utf-8') as f:
                    signals_data = json.load(f)
                
                # Get ALL existing pending orders for this account (no symbol filter)
                print(f" [{inv_id}] 🔍 Checking ALL existing pending orders...")
                existing_orders = get_all_existing_pending_orders()
                stats["total_active_pending"] = len(existing_orders)
                
                # Get ALL existing open positions for this account (no symbol filter)
                print(f" [{inv_id}] 🔍 Checking ALL existing open positions...")
                existing_positions = get_all_existing_positions()
                stats["total_open_positions"] = len(existing_positions)
                
                print(f" [{inv_id}] 📊 Account summary: {stats['total_active_pending']} pending, {stats['total_open_positions']} positions")
                
                # Magic number from investor ID
                magic_number = int(inv_id) if inv_id.isdigit() else 0
                
                # Process each category and symbol
                for category_name, category_data in signals_data.get('categories', {}).items():
                    symbols_in_category = category_data.get('symbols', {})
                    
                    for symbol, symbol_signals in symbols_in_category.items():
                        stats["symbols_processed"] += 1
                        
                        print(f"\n    🔍 Processing {symbol} for order placement:")
                        
                        # Initialize symbol details
                        symbol_detail = {
                            "symbol": symbol,
                            "category": category_name,
                            "orders_attempted": 0,
                            "orders_placed": 0,
                            "orders_converted": 0,
                            "orders_conversion_skipped_permission": 0,
                            "orders_skipped_pending": 0,
                            "orders_skipped_position": 0,
                            "orders_skipped_too_close_same": 0,
                            "orders_skipped_too_close_opposite": 0,
                            "orders_failed": 0,
                            "orders_cancelled_during_regulation": 0,
                            "main_orders_placed": 0,
                            "counter_orders_placed": 0,
                            "counter_orders_skipped": 0,
                            "counter_orders_failed": 0,
                            "trades_recorded": 0,
                            "errors": []
                        }
                        
                        # Check spread for this symbol
                        symbol_info = mt5.symbol_info(symbol)
                        if symbol_info:
                            current_spread = symbol_info.spread
                            print(f"      📊 Current spread for {symbol}: {current_spread} points")
                            
                            if current_spread > max_spread:
                                print(f"      ⚠️ Spread {current_spread} exceeds max allowed {max_spread} - may affect order placement")
                        
                        # Get current prices for reference
                        bid, ask = get_current_price(symbol)
                        if bid and ask:
                            print(f"      💵 Current prices - Bid: {bid:.2f}, Ask: {ask:.2f}")
                        
                        # COLLECT ALL ORDERS FROM BOTH ARRAYS - INCLUDING COUNTERS
                        all_orders_to_process = []
                        pending_orders_to_keep = set()  # Track orders that should be kept for regulation
                        
                        # Helper function to add an order to processing list
                        def add_order_to_process(order_obj, source, is_counter_val):
                            all_orders_to_process.append({
                                'order': order_obj,
                                'source': source,
                                'is_counter': is_counter_val
                            })
                            
                            # Generate key for regulation - but note: if conversion happens, we need to keep the converted order type
                            ord_type = order_obj.get('order_type', '')
                            ord_entry = order_obj.get('entry', 0)
                            ord_volume = round(order_obj.get('volume', 0.01), 2)
                            
                            # If conversion is allowed and this is a stop order, we need to keep the limit order instead
                            if allow_order_type_conversion and ord_type in ['buy_stop', 'sell_stop']:
                                # Convert the type for regulation key
                                converted_type = convert_order_type_logic(ord_type)
                                mt5_type = None
                                if converted_type == 'buy_stop':
                                    mt5_type = mt5.ORDER_TYPE_BUY_STOP
                                elif converted_type == 'buy_limit':
                                    mt5_type = mt5.ORDER_TYPE_BUY_LIMIT
                                elif converted_type == 'sell_stop':
                                    mt5_type = mt5.ORDER_TYPE_SELL_STOP
                                elif converted_type == 'sell_limit':
                                    mt5_type = mt5.ORDER_TYPE_SELL_LIMIT
                                
                                if mt5_type:
                                    pending_orders_to_keep.add(f"{symbol}_{mt5_type}_{ord_entry}_{ord_volume}")
                            else:
                                mt5_type = None
                                if ord_type == 'buy_stop':
                                    mt5_type = mt5.ORDER_TYPE_BUY_STOP
                                elif ord_type == 'buy_limit':
                                    mt5_type = mt5.ORDER_TYPE_BUY_LIMIT
                                elif ord_type == 'sell_stop':
                                    mt5_type = mt5.ORDER_TYPE_SELL_STOP
                                elif ord_type == 'sell_limit':
                                    mt5_type = mt5.ORDER_TYPE_SELL_LIMIT
                                
                                if mt5_type:
                                    pending_orders_to_keep.add(f"{symbol}_{mt5_type}_{ord_entry}_{ord_volume}")
                        
                        # Process bid_orders
                        bid_orders = symbol_signals.get('bid_orders', [])
                        for order in bid_orders:
                            # Add main bid order
                            add_order_to_process(order, 'bid_orders', False)
                            
                            # Add counter order if present
                            if 'order_counter' in order and order['order_counter']:
                                add_order_to_process(order['order_counter'], 'bid_orders_counter', True)
                        
                        # Process ask_orders
                        ask_orders = symbol_signals.get('ask_orders', [])
                        for order in ask_orders:
                            # Add main ask order
                            add_order_to_process(order, 'ask_orders', False)
                            
                            # Add counter order if present
                            if 'order_counter' in order and order['order_counter']:
                                add_order_to_process(order['order_counter'], 'ask_orders_counter', True)
                        
                        print(f"      📦 Found {len(all_orders_to_process)} total orders to process (including counters)")
                        
                        # =====================================================
                        # STEP 3: Regulate and authorize orders
                        # =====================================================
                        print(f"      🧹 Regulating pending orders for {symbol}...")
                        cancelled_count = regulate_and_authorize_orders(symbol, pending_orders_to_keep, magic_number)
                        symbol_detail["orders_cancelled_during_regulation"] = cancelled_count
                        stats["orders_cancelled_during_regulation"] += cancelled_count
                        
                        # Process ALL orders (main and counter) in a single pass
                        for idx, order_info in enumerate(all_orders_to_process):
                            order = order_info['order']
                            is_counter = order_info['is_counter']
                            
                            stats["orders_attempted"] += 1
                            symbol_detail["orders_attempted"] += 1
                            
                            # Process the order with opposite restriction setting
                            success, result, error, was_skipped, skip_reason, was_converted, final_price, check_type = process_single_order(
                                order, symbol, magic_number, inv_root, existing_orders, existing_positions, 
                                is_counter, allow_order_type_conversion, opposite_order_restriction
                            )
                            
                            if was_skipped:
                                if skip_reason == 'pending':
                                    stats["orders_skipped_duplicate_pending"] += 1
                                    symbol_detail["orders_skipped_pending"] += 1
                                elif skip_reason == 'position':
                                    stats["orders_skipped_duplicate_position"] += 1
                                    symbol_detail["orders_skipped_position"] += 1
                                elif skip_reason == 'too_close_same':
                                    stats["orders_skipped_too_close_same_direction"] += 1
                                    symbol_detail["orders_skipped_too_close_same"] += 1
                                elif skip_reason == 'too_close_opposite':
                                    stats["orders_skipped_too_close_opposite_direction"] += 1
                                    symbol_detail["orders_skipped_too_close_opposite"] += 1
                                
                                # Track counter order skips separately
                                if is_counter:
                                    stats["counter_orders_skipped"] += 1
                                    symbol_detail["counter_orders_skipped"] += 1
                                
                            elif success:
                                stats["orders_placed"] += 1
                                stats["trades_recorded"] += 1
                                symbol_detail["orders_placed"] += 1
                                symbol_detail["trades_recorded"] += 1
                                
                                if was_converted:
                                    stats["orders_converted_and_placed"] += 1
                                    symbol_detail["orders_converted"] += 1
                                
                                if is_counter:
                                    stats["counter_orders_placed"] += 1
                                    symbol_detail["counter_orders_placed"] += 1
                                else:
                                    stats["main_orders_placed"] += 1
                                    symbol_detail["main_orders_placed"] += 1
                                
                                # Map order type string to MT5 order type for the key
                                # Use the final order type that was actually placed
                                final_order_type = order.get('final_order_type', order.get('order_type', ''))
                                if was_converted:
                                    # If converted, use the converted type
                                    final_order_type = convert_order_type_logic(order.get('order_type', ''))
                                
                                mt5_pending_type = None
                                
                                if final_order_type == 'buy_stop':
                                    mt5_pending_type = mt5.ORDER_TYPE_BUY_STOP
                                elif final_order_type == 'buy_limit':
                                    mt5_pending_type = mt5.ORDER_TYPE_BUY_LIMIT
                                elif final_order_type == 'sell_stop':
                                    mt5_pending_type = mt5.ORDER_TYPE_SELL_STOP
                                elif final_order_type == 'sell_limit':
                                    mt5_pending_type = mt5.ORDER_TYPE_SELL_LIMIT
                                
                                # Round volume for key
                                volume_rounded = round(order.get('volume', 0.01), 2)
                                
                                # Add to existing_orders to prevent duplicate placement in same run
                                if mt5_pending_type:
                                    pending_key = f"{symbol}_{mt5_pending_type}_{final_price}_{volume_rounded}"
                                    existing_orders[pending_key] = {
                                        'ticket': result.order,
                                        'symbol': symbol,
                                        'type': mt5_pending_type,
                                        'price': final_price,
                                        'volume': volume_rounded,
                                        'type_string': "PENDING"
                                    }
                                    print(f"          🔒 Added to duplicate prevention cache: {pending_key}")
                                
                            else:
                                stats["orders_failed"] += 1
                                symbol_detail["orders_failed"] += 1
                                
                                if is_counter:
                                    stats["counter_orders_failed"] += 1
                                    symbol_detail["counter_orders_failed"] += 1
                                
                                # Track if failure was due to conversion not being allowed
                                if error and "conversion is NOT ALLOWED" in error:
                                    stats["orders_conversion_skipped_permission"] += 1
                                    symbol_detail["orders_conversion_skipped_permission"] += 1
                                
                                if error:
                                    symbol_detail["errors"].append(f"{'Counter' if is_counter else 'Main'} order {idx+1}: {error}")
                        
                        # Store symbol details
                        stats["symbol_details"][symbol] = symbol_detail
                
                # Print summary
                print(f"\n  📊 ORDER PLACEMENT SUMMARY:")
                print(f"    • Upload Orders Flag: {stats['upload_orders_flag']}")
                print(f"    • Investors skipped due to position flag: {stats['investors_skipped_due_to_position_flag']}")
                print(f"    • Symbols processed: {stats['symbols_processed']}")
                print(f"    • Total orders attempted: {stats['orders_attempted']}")
                print(f"    • Orders placed: {stats['orders_placed']}")
                print(f"      - Main orders: {stats['main_orders_placed']}")
                print(f"      - Counter orders: {stats['counter_orders_placed']}")
                print(f"      - Converted orders: {stats['orders_converted_and_placed']}")
                print(f"    • Counter orders skipped: {stats.get('counter_orders_skipped', 0)}")
                print(f"    • Counter orders failed: {stats['counter_orders_failed']}")
                print(f"    • Orders cancelled during regulation: {stats['orders_cancelled_during_regulation']}")
                print(f"    • Orders skipped (duplicate pending): {stats['orders_skipped_duplicate_pending']}")
                print(f"    • Orders skipped (duplicate position): {stats['orders_skipped_duplicate_position']}")
                print(f"    • Orders skipped (too close - same direction): {stats.get('orders_skipped_too_close_same_direction', 0)}")
                print(f"    • Orders skipped (too close - opposite direction): {stats.get('orders_skipped_too_close_opposite_direction', 0)}")
                print(f"    • Orders conversion skipped (permission denied): {stats['orders_conversion_skipped_permission']}")
                print(f"    • Orders failed: {stats['orders_failed']}")
                print(f"    • Total active pending orders: {stats['total_active_pending']}")
                print(f"    • Total open positions: {stats['total_open_positions']}")
                print(f"    • Trades recorded in history: {stats['trades_recorded']}")
                
                if stats['orders_failed'] > 0:
                    print(f"\n   FAILED ORDER DETAILS:")
                    for symbol, detail in stats["symbol_details"].items():
                        if detail["orders_failed"] > 0:
                            print(f"    • {symbol}: {detail['orders_failed']} failures")
                            for error in detail["errors"][:5]:
                                print(f"        • {error}")
                
            except Exception as e:
                print(f" [{inv_id}]  Error in order placement: {e}")
                import traceback
                traceback.print_exc()
                stats["placement_errors"].append(str(e))
        
        return stats
    
    return main()

def manage_position_and_pending_orders(inv_id=None):
    """
    Function: Manages positions and pending orders to ensure controlled number of items PER SYMBOL
    
    Dynamic count management:
    - count = 0: Default to strict 2-item management (original behavior with SL matching)
    - count = 1: Keep ONLY the closest order (either BUY or SELL) to current price, delete all others
    - count = 2: Strict SL price matching between position and opposite pending order
    - count >= 3: 
        * First 2 items: Strict SL matching (position + opposite pending OR closest BUY/SELL pair with SL match)
        * Remaining items (count-2): Keep additional orders closest to current price, no relationship checks
        * Delete any orders beyond the count limit
    
    INTEGRITY RULE: upload_orders = False ONLY IF (positions + pending orders) == count for EACH symbol
                    Otherwise upload_orders = True
    
    Args:
        inv_id: Optional specific investor ID to process. If None, processes all investors.
        
    Returns:
        dict: Statistics about the processing including 'upload_orders' flag
    """
    print(f"\n{'='*10} 🎯 DYNAMIC POSITION & PENDING ORDER MANAGEMENT (PER SYMBOL) {'='*10}")
    if inv_id:
        print(f" Processing single investor: {inv_id}")

    # Track statistics
    stats = {
        "investor_id": inv_id if inv_id else "all",
        "investors_processed": 0,
        "positions_found": 0,
        "pending_orders_found": 0,
        "symbols_processed": 0,
        "orders_kept": 0,
        "orders_deleted": 0,
        "errors": 0,
        "processing_success": False,
        "upload_orders": True,
        "symbol_status": {},
        "management_counts": {}
    }

    # Determine which investors to process
    investors_to_process = [inv_id] if inv_id else usersdictionary.keys()
    total_investors = len(investors_to_process) if not inv_id else 1
    processed = 0

    for user_brokerid in investors_to_process:
        processed += 1
        print(f"\n[{processed}/{total_investors}] {user_brokerid} 🔍 Checking dynamic position/pending configuration...")
        
        # Reset per-investor flags
        investor_has_valid_integrity = True  # Start with True, becomes False if any symbol violates
        management_count = 2  # Default count
        
        # Get broker config
        broker_cfg = usersdictionary.get(user_brokerid)
        if not broker_cfg:
            print(f"  └─  No broker config found")
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
            
            # Check management configuration
            settings = config.get("settings", {})
            manage_config = settings.get("manage_position_and_pending_orders", {})
            management_count = manage_config.get("count", 2)
            
            # Validate count (0, 1, 2, or higher)
            if management_count < 0:
                management_count = 2
            
            print(f"  └─ ✅ Dynamic management ENABLED with count = {management_count}")
            print(f"      • count=0: Default strict 2-item management (SL matching)")
            print(f"      • count=1: Keep single closest order")
            print(f"      • count=2: Strict SL price matching")
            print(f"      • count={management_count}: {management_count - 2} additional order(s) beyond strict pair")
            print(f"      • INTEGRITY RULE: upload_orders = False ONLY IF total items == {management_count} for EACH symbol")
            
        except Exception as e:
            print(f"  └─  Failed to read config: {e}")
            stats["errors"] += 1
            continue

        # --- ACCOUNT INITIALIZATION ---
        print(f"  └─ 🔌 Initializing account connection...")
        
        login_id = int(broker_cfg['LOGIN_ID'])
        mt5_path = broker_cfg["TERMINAL_PATH"]
        
        print(f"      • Terminal Path: {mt5_path}")
        print(f"      • Login ID: {login_id}")

        # Initialize MT5 connection if needed
        if not mt5.initialize(path=mt5_path):
            print(f"  └─  MT5 initialization failed")
            stats["errors"] += 1
            continue

        # Check login status
        acc = mt5.account_info()
        if acc is None or acc.login != login_id:
            print(f"      🔑 Logging into account...")
            if not mt5.login(login_id, password=broker_cfg["PASSWORD"], server=broker_cfg["SERVER"]):
                error = mt5.last_error()
                print(f"  └─  Login failed: {error}")
                stats["errors"] += 1
                continue
            print(f"      ✅ Successfully logged into account")
        else:
            print(f"      ✅ Already logged into account")

        # --- GET ALL POSITIONS AND PENDING ORDERS ---
        positions = mt5.positions_get()
        pending_orders = mt5.orders_get()
        
        stats["investors_processed"] += 1
        stats["positions_found"] += len(positions) if positions else 0
        stats["pending_orders_found"] += len(pending_orders) if pending_orders else 0
        
        # Count total trading items (positions + pending orders)
        total_positions = len(positions) if positions else 0
        total_pending = len(pending_orders) if pending_orders else 0
        total_items = total_positions + total_pending
        
        print(f"\n  └─ 📊 Account Summary:")
        print(f"      • Positions: {total_positions}")
        print(f"      • Pending Orders: {total_pending}")
        print(f"      • Total Items: {total_items}")
        
        # CRITICAL RULE: If there's only ONE item total (either one position OR one pending order)
        if total_items == 1:
            print(f"\n  └─ 🚩 Only 1 trading item found (total positions + pending orders = 1)")
            print(f"  └─ 🚩 upload_orders = True (insufficient items for management)")
            stats["upload_orders"] = True
            stats["processing_success"] = True
            continue
        
        # --- GROUP POSITIONS BY SYMBOL ---
        positions_by_symbol = {}
        if positions:
            for pos in positions:
                symbol = pos.symbol
                if symbol not in positions_by_symbol:
                    positions_by_symbol[symbol] = []
                positions_by_symbol[symbol].append(pos)
        
        # Group pending orders by symbol
        orders_by_symbol = {}
        if pending_orders:
            for order in pending_orders:
                symbol = order.symbol
                if symbol not in orders_by_symbol:
                    orders_by_symbol[symbol] = []
                orders_by_symbol[symbol].append(order)
        
        print(f"\n  └─ 📊 Symbols with positions: {list(positions_by_symbol.keys())}")
        print(f"  └─ 📊 Symbols with pending orders: {list(orders_by_symbol.keys())}")
        
        # --- GET CURRENT PRICES FOR ALL SYMBOLS ---
        current_prices = {}
        all_symbols = set(positions_by_symbol.keys()) | set(orders_by_symbol.keys())
        for symbol in all_symbols:
            tick = mt5.symbol_info_tick(symbol)
            if tick:
                current_prices[symbol] = tick.ask
            else:
                print(f"      ⚠️  Could not get current price for {symbol}")
                current_prices[symbol] = None
        
        # --- PROCESS EACH SYMBOL INDEPENDENTLY ---
        symbol_results = []
        
        # Process ALL symbols that have pending orders (with or without positions)
        all_symbols_with_items = set(positions_by_symbol.keys()) | set(orders_by_symbol.keys())
        
        for symbol in all_symbols_with_items:
            print(f"\n  └─ 🔄 Processing symbol: {symbol}")
            
            symbol_positions = positions_by_symbol.get(symbol, [])
            symbol_orders = orders_by_symbol.get(symbol, [])
            current_price = current_prices.get(symbol)
            
            total_symbol_items = len(symbol_positions) + len(symbol_orders)
            
            symbol_stats = {
                "symbol": symbol,
                "positions_count": len(symbol_positions),
                "pending_orders_count": len(symbol_orders),
                "total_items": total_symbol_items,
                "target_count": management_count,
                "management_count": management_count,
                "has_valid_pair": False,
                "orders_kept": 0,
                "orders_deleted": 0,
                "action_taken": False,
                "management_type": "",
                "additional_orders_kept": 0,
                "integrity_valid": False  # Track if this symbol meets the count requirement
            }
            
            # Check integrity BEFORE any deletion
            if total_symbol_items == management_count:
                symbol_stats["integrity_valid"] = True
                print(f"      ✅ INTEGRITY OK: {total_symbol_items} items == target count {management_count}")
            else:
                print(f"      ⚠️  INTEGRITY VIOLATION: {total_symbol_items} items != target count {management_count}")
                investor_has_valid_integrity = False
            
            # Determine management strategy based on count
            if management_count == 0:
                # Count 0: Default to strict 2-item management
                symbol_stats["management_type"] = "COUNT0_DEFAULT_STRICT_2"
                print(f"      📍 Count=0 mode: Using default strict 2-item management")
                
                orders_to_keep = []
                orders_to_delete = []
                
                if symbol_positions:
                    position = symbol_positions[0]
                    
                    is_buy_position = position.type == mt5.POSITION_TYPE_BUY
                    position_type_str = "BUY" if is_buy_position else "SELL"
                    
                    if position.sl is None or position.sl == 0:
                        print(f"      ⚠️  Position has no SL - deleting ALL pending orders")
                        orders_to_delete = symbol_orders.copy()
                    else:
                        opposite_order_types = [mt5.ORDER_TYPE_SELL_LIMIT, mt5.ORDER_TYPE_SELL_STOP] if is_buy_position else [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP]
                        target_sl_price = position.sl
                        
                        matching_orders = []
                        other_orders = []
                        
                        for order in symbol_orders:
                            if order.type in opposite_order_types:
                                if abs(order.price_open - target_sl_price) < 0.00001:
                                    matching_orders.append(order)
                                else:
                                    other_orders.append(order)
                            else:
                                other_orders.append(order)
                        
                        if matching_orders:
                            orders_to_keep = [matching_orders[0]]
                            orders_to_delete = matching_orders[1:] + other_orders
                            symbol_stats["has_valid_pair"] = True
                        else:
                            orders_to_delete = symbol_orders.copy()
                
                else:
                    # No position: find closest BUY and SELL with SL match
                    buy_orders = [o for o in symbol_orders if o.type in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP]]
                    sell_orders = [o for o in symbol_orders if o.type in [mt5.ORDER_TYPE_SELL_LIMIT, mt5.ORDER_TYPE_SELL_STOP]]
                    
                    closest_buy = min(buy_orders, key=lambda o: abs(o.price_open - current_price)) if buy_orders else None
                    closest_sell = min(sell_orders, key=lambda o: abs(o.price_open - current_price)) if sell_orders else None
                    
                    if closest_buy and closest_sell:
                        valid_match = False
                        if closest_buy.sl and abs(closest_buy.sl - closest_sell.price_open) < 0.00001:
                            valid_match = True
                        elif closest_sell.sl and abs(closest_sell.sl - closest_buy.price_open) < 0.00001:
                            valid_match = True
                        
                        if valid_match:
                            orders_to_keep = [closest_buy, closest_sell]
                            orders_to_delete = [o for o in symbol_orders if o.ticket not in [closest_buy.ticket, closest_sell.ticket]]
                            symbol_stats["has_valid_pair"] = True
                        else:
                            orders_to_delete = symbol_orders.copy()
                    else:
                        orders_to_delete = symbol_orders.copy()
            
            elif management_count == 1:
                # Count 1: Keep ONLY the single closest order to current price (BUY or SELL)
                symbol_stats["management_type"] = "COUNT1_SINGLE_CLOSEST"
                print(f"      📍 Count=1 mode: Keeping single closest order to current price")
                
                if not current_price:
                    print(f"      ⚠️  Cannot get current price - deleting ALL orders")
                    orders_to_delete = symbol_orders.copy()
                    orders_to_keep = []
                else:
                    # Find the single order closest to current price
                    closest_order = min(symbol_orders, key=lambda o: abs(o.price_open - current_price))
                    closest_distance = abs(closest_order.price_open - current_price)
                    
                    order_type_name = "BUY" if closest_order.type in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP] else "SELL"
                    print(f"      🎯 Closest order: {order_type_name} #{closest_order.ticket} @ {closest_order.price_open} (distance: {closest_distance:.5f})")
                    
                    orders_to_keep = [closest_order]
                    orders_to_delete = [o for o in symbol_orders if o.ticket != closest_order.ticket]
                    symbol_stats["has_valid_pair"] = True  # Count 1 always considered valid
            
            elif management_count == 2:
                # Count 2: Strict SL matching (original behavior)
                symbol_stats["management_type"] = "COUNT2_STRICT_SL_MATCHING"
                print(f"      📍 Count=2 mode: Strict SL price matching")
                
                orders_to_keep = []
                orders_to_delete = []
                
                if symbol_positions:
                    position = symbol_positions[0]
                    
                    is_buy_position = position.type == mt5.POSITION_TYPE_BUY
                    position_type_str = "BUY" if is_buy_position else "SELL"
                    
                    if position.sl is None or position.sl == 0:
                        print(f"      ⚠️  Position has no SL - deleting ALL pending orders")
                        orders_to_delete = symbol_orders.copy()
                    else:
                        opposite_order_types = [mt5.ORDER_TYPE_SELL_LIMIT, mt5.ORDER_TYPE_SELL_STOP] if is_buy_position else [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP]
                        target_sl_price = position.sl
                        
                        matching_orders = []
                        other_orders = []
                        
                        for order in symbol_orders:
                            if order.type in opposite_order_types:
                                if abs(order.price_open - target_sl_price) < 0.00001:
                                    matching_orders.append(order)
                                else:
                                    other_orders.append(order)
                            else:
                                other_orders.append(order)
                        
                        if matching_orders:
                            orders_to_keep = [matching_orders[0]]
                            orders_to_delete = matching_orders[1:] + other_orders
                            symbol_stats["has_valid_pair"] = True
                        else:
                            orders_to_delete = symbol_orders.copy()
                
                else:
                    # No position: find closest BUY/SELL pair with SL match
                    buy_orders = [o for o in symbol_orders if o.type in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP]]
                    sell_orders = [o for o in symbol_orders if o.type in [mt5.ORDER_TYPE_SELL_LIMIT, mt5.ORDER_TYPE_SELL_STOP]]
                    
                    closest_buy = min(buy_orders, key=lambda o: abs(o.price_open - current_price)) if buy_orders else None
                    closest_sell = min(sell_orders, key=lambda o: abs(o.price_open - current_price)) if sell_orders else None
                    
                    if closest_buy and closest_sell:
                        valid_match = False
                        if closest_buy.sl and abs(closest_buy.sl - closest_sell.price_open) < 0.00001:
                            valid_match = True
                        elif closest_sell.sl and abs(closest_sell.sl - closest_buy.price_open) < 0.00001:
                            valid_match = True
                        
                        if valid_match:
                            orders_to_keep = [closest_buy, closest_sell]
                            orders_to_delete = [o for o in symbol_orders if o.ticket not in [closest_buy.ticket, closest_sell.ticket]]
                            symbol_stats["has_valid_pair"] = True
                        else:
                            orders_to_delete = symbol_orders.copy()
                    else:
                        orders_to_delete = symbol_orders.copy()
            
            else:  # management_count >= 3
                # Count >= 3: Strict pair for first 2 items, then keep additional closest orders
                symbol_stats["management_type"] = f"COUNT{management_count}_HYBRID"
                print(f"      📍 Count={management_count} mode: Strict pair + {management_count - 2} additional closest orders")
                
                # Step 1: Identify the strict pair (same logic as count=2)
                strict_orders_to_keep = []
                remaining_orders = symbol_orders.copy()
                
                if symbol_positions:
                    # Try to find SL-matching pair with position
                    position = symbol_positions[0]
                    
                    is_buy_position = position.type == mt5.POSITION_TYPE_BUY
                    
                    if position.sl and position.sl != 0:
                        opposite_order_types = [mt5.ORDER_TYPE_SELL_LIMIT, mt5.ORDER_TYPE_SELL_STOP] if is_buy_position else [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP]
                        target_sl_price = position.sl
                        
                        for order in symbol_orders:
                            if order.type in opposite_order_types:
                                if abs(order.price_open - target_sl_price) < 0.00001:
                                    strict_orders_to_keep.append(order)
                                    break
                    
                    # If no SL match found with position, try to find BUY/SELL pair among orders
                    if not strict_orders_to_keep:
                        buy_orders = [o for o in symbol_orders if o.type in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP]]
                        sell_orders = [o for o in symbol_orders if o.type in [mt5.ORDER_TYPE_SELL_LIMIT, mt5.ORDER_TYPE_SELL_STOP]]
                        
                        closest_buy = min(buy_orders, key=lambda o: abs(o.price_open - current_price)) if buy_orders else None
                        closest_sell = min(sell_orders, key=lambda o: abs(o.price_open - current_price)) if sell_orders else None
                        
                        if closest_buy and closest_sell:
                            valid_match = False
                            if closest_buy.sl and abs(closest_buy.sl - closest_sell.price_open) < 0.00001:
                                valid_match = True
                            elif closest_sell.sl and abs(closest_sell.sl - closest_buy.price_open) < 0.00001:
                                valid_match = True
                            
                            if valid_match:
                                strict_orders_to_keep = [closest_buy, closest_sell]
                else:
                    # No position: find BUY/SELL pair with SL match
                    buy_orders = [o for o in symbol_orders if o.type in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP]]
                    sell_orders = [o for o in symbol_orders if o.type in [mt5.ORDER_TYPE_SELL_LIMIT, mt5.ORDER_TYPE_SELL_STOP]]
                    
                    closest_buy = min(buy_orders, key=lambda o: abs(o.price_open - current_price)) if buy_orders else None
                    closest_sell = min(sell_orders, key=lambda o: abs(o.price_open - current_price)) if sell_orders else None
                    
                    if closest_buy and closest_sell:
                        valid_match = False
                        if closest_buy.sl and abs(closest_buy.sl - closest_sell.price_open) < 0.00001:
                            valid_match = True
                        elif closest_sell.sl and abs(closest_sell.sl - closest_buy.price_open) < 0.00001:
                            valid_match = True
                        
                        if valid_match:
                            strict_orders_to_keep = [closest_buy, closest_sell]
                
                # Remove strict orders from remaining list
                if strict_orders_to_keep:
                    strict_tickets = [o.ticket for o in strict_orders_to_keep]
                    remaining_orders = [o for o in symbol_orders if o.ticket not in strict_tickets]
                    symbol_stats["has_valid_pair"] = True
                    print(f"      • Strict pair found: {len(strict_orders_to_keep)} order(s)")
                else:
                    print(f"      • No valid strict pair found - will keep only closest orders")
                
                # Step 2: Calculate how many additional orders we can keep
                additional_needed = management_count - len(strict_orders_to_keep)
                
                if additional_needed > 0 and remaining_orders:
                    # Sort remaining orders by distance to current price
                    if current_price:
                        remaining_orders.sort(key=lambda o: abs(o.price_open - current_price))
                        additional_to_keep = remaining_orders[:additional_needed]
                        orders_to_keep = strict_orders_to_keep + additional_to_keep
                        orders_to_delete = [o for o in symbol_orders if o.ticket not in [k.ticket for k in orders_to_keep]]
                        
                        symbol_stats["additional_orders_kept"] = len(additional_to_keep)
                        print(f"      • Keeping {len(additional_to_keep)} additional order(s) closest to price")
                    else:
                        orders_to_keep = strict_orders_to_keep
                        orders_to_delete = remaining_orders
                else:
                    orders_to_keep = strict_orders_to_keep
                    orders_to_delete = remaining_orders
                
                # Final check: ensure we don't exceed management count
                if len(orders_to_keep) > management_count:
                    # Trim to management count (keep the strict ones first, then closest)
                    if current_price:
                        # Sort by distance, but prioritize strict orders
                        strict_tickets = [o.ticket for o in strict_orders_to_keep]
                        non_strict = [o for o in orders_to_keep if o.ticket not in strict_tickets]
                        if non_strict:
                            non_strict.sort(key=lambda o: abs(o.price_open - current_price))
                            orders_to_keep = strict_orders_to_keep + non_strict[:management_count - len(strict_orders_to_keep)]
                            orders_to_delete = [o for o in symbol_orders if o.ticket not in [k.ticket for k in orders_to_keep]]
                
                # If no valid pair found and count>=3, just keep closest orders up to count
                if not strict_orders_to_keep and current_price:
                    symbol_orders_sorted = sorted(symbol_orders, key=lambda o: abs(o.price_open - current_price))
                    orders_to_keep = symbol_orders_sorted[:management_count]
                    orders_to_delete = symbol_orders_sorted[management_count:]
                    print(f"      • No valid pair - keeping {len(orders_to_keep)} closest order(s)")
            
            # --- DELETE ORDERS ---
            if orders_to_delete:
                print(f"      🗑️  Deleting {len(orders_to_delete)} order(s)...")
                symbol_stats["action_taken"] = True
                
                for order in orders_to_delete:
                    order_type_name = "UNKNOWN"
                    if order.type == mt5.ORDER_TYPE_BUY_LIMIT:
                        order_type_name = "BUY LIMIT"
                    elif order.type == mt5.ORDER_TYPE_SELL_LIMIT:
                        order_type_name = "SELL LIMIT"
                    elif order.type == mt5.ORDER_TYPE_BUY_STOP:
                        order_type_name = "BUY STOP"
                    elif order.type == mt5.ORDER_TYPE_SELL_STOP:
                        order_type_name = "SELL STOP"
                    
                    print(f"        • Deleting order #{order.ticket} ({order_type_name} @ {order.price_open})...")
                    
                    delete_request = {
                        "action": mt5.TRADE_ACTION_REMOVE,
                        "order": order.ticket,
                    }
                    
                    result = mt5.order_send(delete_request)
                    
                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        symbol_stats["orders_deleted"] += 1
                        stats["orders_deleted"] += 1
                        print(f"          ✅ Deleted successfully")
                    else:
                        stats["errors"] += 1
                        error_msg = result.comment if result else f"Error code: {result.retcode if result else 'Unknown'}"
                        print(f"           Deletion failed: {error_msg}")
            
            symbol_stats["orders_kept"] = len(orders_to_keep) if orders_to_keep else 0
            stats["orders_kept"] += symbol_stats["orders_kept"]
            
            symbol_results.append(symbol_stats)
            stats["symbols_processed"] += 1
            
            # Display per-symbol summary
            print(f"      📊 {symbol} Summary:")
            print(f"      • Management Type: {symbol_stats['management_type']}")
            print(f"      • Target count: {management_count}")
            print(f"      • Initial items: {total_symbol_items}")
            print(f"      • Orders kept: {symbol_stats['orders_kept']}")
            print(f"      • Orders deleted: {symbol_stats['orders_deleted']}")
            print(f"      • Integrity valid: {'✅ YES' if symbol_stats['integrity_valid'] else '❌ NO'}")
            if symbol_stats.get('additional_orders_kept', 0) > 0:
                print(f"      • Additional orders kept: {symbol_stats['additional_orders_kept']}")
            
            # Store status
            if management_count == 0:
                stats["symbol_status"][symbol] = "COUNT0_DEFAULT_STRICT" + ("_VALID" if symbol_stats["has_valid_pair"] else "_NO_MATCH")
            elif management_count == 1:
                stats["symbol_status"][symbol] = "COUNT1_SINGLE_ORDER"
            elif management_count == 2:
                stats["symbol_status"][symbol] = "COUNT2_STRICT" + ("_VALID" if symbol_stats["has_valid_pair"] else "_NO_MATCH")
            else:
                stats["symbol_status"][symbol] = f"COUNT{management_count}_HYBRID" + ("_WITH_PAIR" if symbol_stats["has_valid_pair"] else "_NO_PAIR")
        
        # --- DETERMINE FINAL upload_orders FLAG BASED ON INTEGRITY ---
        # upload_orders = False ONLY IF every symbol has total_items == management_count
        if investor_has_valid_integrity and len(symbol_results) > 0:
            stats["upload_orders"] = False
            print(f"\n  └─ 🚩 upload_orders = False (All symbols have exactly {management_count} items)")
        else:
            stats["upload_orders"] = True
            if not investor_has_valid_integrity:
                print(f"\n  └─ 🚩 upload_orders = True (Some symbols violate the count requirement)")
            elif len(symbol_results) == 0:
                print(f"\n  └─ 🚩 upload_orders = True (No symbols with items to check)")
        
        stats["management_counts"][user_brokerid] = management_count
        stats["processing_success"] = True
        
        # --- INVESTOR SUMMARY ---
        print(f"\n  └─ 📊 Management Results for {user_brokerid}:")
        print(f"      • Management count: {management_count}")
        print(f"      • Symbols processed: {len(symbol_results)}")
        print(f"      • Total positions: {total_positions}")
        print(f"      • Total pending orders: {total_pending}")
        print(f"      • Orders kept: {stats['orders_kept']}")
        print(f"      • Orders deleted: {stats['orders_deleted']}")
        print(f"      • upload_orders flag: {stats['upload_orders']}")
        
        # Show per-symbol breakdown
        if symbol_results:
            print(f"      • Per-symbol breakdown:")
            for sym_result in symbol_results:
                integrity_status = "✅" if sym_result['integrity_valid'] else "❌"
                status = f"{sym_result['management_type']} (items: {sym_result['total_items']}/{sym_result['target_count']} {integrity_status}, kept: {sym_result['orders_kept']}, deleted: {sym_result['orders_deleted']})"
                print(f"        - {sym_result['symbol']}: {status}")
        
        if stats['errors'] > 0:
            print(f"      • Errors: {stats['errors']}")
        else:
            print(f"      ✅ Management completed successfully")

    # --- FINAL SUMMARY ---
    print(f"\n{'='*10} 📊 DYNAMIC POSITION & PENDING ORDER MANAGEMENT SUMMARY {'='*10}")
    print(f"   Investor ID: {stats['investor_id']}")
    print(f"   Investors processed: {stats['investors_processed']}")
    print(f"   Total positions found: {stats['positions_found']}")
    print(f"   Total pending orders found: {stats['pending_orders_found']}")
    print(f"   Symbols processed: {stats['symbols_processed']}")
    print(f"   Orders kept: {stats['orders_kept']}")
    print(f"   Orders deleted: {stats['orders_deleted']}")
    print(f"   Errors: {stats['errors']}")
    print(f"   FINAL upload_orders flag: {stats['upload_orders']}")
    
    # Show management counts used
    if stats['management_counts']:
        print(f"\n   Management Counts by Investor:")
        for inv_id, count in stats['management_counts'].items():
            print(f"      • {inv_id}: count={count}")
    
    # Show symbol status summary
    if stats['symbol_status']:
        print(f"\n   Symbol Status Summary:")
        for symbol, status in stats['symbol_status'].items():
            print(f"      • {symbol}: {status}")
    
    if stats['orders_deleted'] > 0 or stats['orders_kept'] > 0:
        print(f"\n   Management Action: {'✅ COMPLETED' if stats['processing_success'] else '⚠️  PARTIAL'}")
    else:
        print(f"\n   Management Action: ℹ️  No action needed")
    
    print(f"\n{'='*10} 🏁 DYNAMIC POSITION & PENDING ORDER MANAGEMENT COMPLETE {'='*10}\n")
    return stats

def manage_single_position_and_pending(inv_id=None):
    """
    Function: Manages positions and pending orders to ensure only one position exists PER SYMBOL
    and only the opposite pending order with entry price matching the position's SL price remains.
    
    If enable_single_position_and_pending is True:
    - For each symbol with a position:
        - For a SELL position: Keeps only the BUY order with entry price EQUAL to the SELL position's SL price
        - For a BUY position: Keeps only the SELL order with entry price EQUAL to the BUY position's SL price
        - Deletes all other pending orders for that symbol
    
    - For each symbol WITHOUT a position but WITH pending orders:
        - First, identify the closest BUY order to current price and closest SELL order to current price
        - Then, check if these two orders have a valid SL relationship:
          * BUY entry price equals SELL SL price, OR
          * SELL entry price equals BUY SL price
        - If valid SL relationship exists: keep these two orders, delete all others
        - If no valid SL relationship: delete ALL pending orders
    
    Args:
        inv_id: Optional specific investor ID to process. If None, processes all investors.
        
    Returns:
        dict: Statistics about the processing including 'upload_orders' flag
    """
    print(f"\n{'='*10} 🎯 SINGLE POSITION & PENDING ORDER MANAGEMENT (PER SYMBOL) {'='*10}")
    if inv_id:
        print(f" Processing single investor: {inv_id}")

    # Track statistics
    stats = {
        "investor_id": inv_id if inv_id else "all",
        "investors_processed": 0,
        "positions_found": 0,
        "pending_orders_found": 0,
        "symbols_processed": 0,
        "orders_kept": 0,
        "orders_deleted": 0,
        "errors": 0,
        "processing_success": False,
        "upload_orders": True,  # Will be set to False ONLY if ANY symbol has valid SL match
        "symbol_status": {}  # Track per symbol status for debugging
    }

    # Determine which investors to process
    investors_to_process = [inv_id] if inv_id else usersdictionary.keys()
    total_investors = len(investors_to_process) if not inv_id else 1
    processed = 0

    for user_brokerid in investors_to_process:
        processed += 1
        print(f"\n[{processed}/{total_investors}] {user_brokerid} 🔍 Checking single position/pending configuration...")
        
        # Reset per-investor flags
        investor_has_valid_pair = False
        
        # Get broker config
        broker_cfg = usersdictionary.get(user_brokerid)
        if not broker_cfg:
            print(f"  └─  No broker config found")
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
            
            # Check if single position and pending management is enabled
            settings = config.get("settings", {})
            if not settings.get("enable_single_position_and_pending", False):
                print(f"  └─ ⏭️  Single position/pending management disabled in settings. Skipping.")
                continue
            
            print(f"  └─ ✅ Single position/pending management ENABLED (SL PRICE MATCHING MODE)")
            
        except Exception as e:
            print(f"  └─  Failed to read config: {e}")
            stats["errors"] += 1
            continue

        # --- ACCOUNT INITIALIZATION ---
        print(f"  └─ 🔌 Initializing account connection...")
        
        login_id = int(broker_cfg['LOGIN_ID'])
        mt5_path = broker_cfg["TERMINAL_PATH"]
        
        print(f"      • Terminal Path: {mt5_path}")
        print(f"      • Login ID: {login_id}")

        # Initialize MT5 connection if needed
        if not mt5.initialize(path=mt5_path):
            print(f"  └─  MT5 initialization failed")
            stats["errors"] += 1
            continue

        # Check login status
        acc = mt5.account_info()
        if acc is None or acc.login != login_id:
            print(f"      🔑 Logging into account...")
            if not mt5.login(login_id, password=broker_cfg["PASSWORD"], server=broker_cfg["SERVER"]):
                error = mt5.last_error()
                print(f"  └─  Login failed: {error}")
                stats["errors"] += 1
                continue
            print(f"      ✅ Successfully logged into account")
        else:
            print(f"      ✅ Already logged into account")

        # --- GET ALL POSITIONS AND PENDING ORDERS ---
        positions = mt5.positions_get()
        pending_orders = mt5.orders_get()
        
        stats["investors_processed"] += 1
        stats["positions_found"] += len(positions) if positions else 0
        stats["pending_orders_found"] += len(pending_orders) if pending_orders else 0
        
        # Count total trading items (positions + pending orders)
        total_positions = len(positions) if positions else 0
        total_pending = len(pending_orders) if pending_orders else 0
        total_items = total_positions + total_pending
        
        print(f"\n  └─ 📊 Account Summary:")
        print(f"      • Positions: {total_positions}")
        print(f"      • Pending Orders: {total_pending}")
        print(f"      • Total Items: {total_items}")
        
        # CRITICAL RULE: If there's only ONE item total (either one position OR one pending order)
        if total_items == 1:
            print(f"\n  └─ 🚩 Only 1 trading item found (total positions + pending orders = 1)")
            print(f"  └─ 🚩 upload_orders = True (insufficient items for management)")
            stats["upload_orders"] = True
            stats["processing_success"] = True
            continue
        
        # --- GROUP POSITIONS BY SYMBOL ---
        positions_by_symbol = {}
        if positions:
            for pos in positions:
                symbol = pos.symbol
                if symbol not in positions_by_symbol:
                    positions_by_symbol[symbol] = []
                positions_by_symbol[symbol].append(pos)
        
        # Group pending orders by symbol
        orders_by_symbol = {}
        if pending_orders:
            for order in pending_orders:
                symbol = order.symbol
                if symbol not in orders_by_symbol:
                    orders_by_symbol[symbol] = []
                orders_by_symbol[symbol].append(order)
        
        print(f"\n  └─ 📊 Symbols with positions: {list(positions_by_symbol.keys())}")
        print(f"  └─ 📊 Symbols with pending orders: {list(orders_by_symbol.keys())}")
        
        # --- GET CURRENT PRICES FOR ALL SYMBOLS ---
        current_prices = {}
        all_symbols = set(positions_by_symbol.keys()) | set(orders_by_symbol.keys())
        for symbol in all_symbols:
            tick = mt5.symbol_info_tick(symbol)
            if tick:
                current_prices[symbol] = tick.ask  # Use ask for calculations
            else:
                print(f"      ⚠️  Could not get current price for {symbol}")
                current_prices[symbol] = None
        
        # --- PROCESS EACH SYMBOL INDEPENDENTLY ---
        symbol_results = []
        
        # Process ALL symbols that have pending orders (with or without positions)
        all_symbols_with_orders = set(orders_by_symbol.keys())
        
        for symbol in all_symbols_with_orders:
            print(f"\n  └─ 🔄 Processing symbol: {symbol}")
            
            has_position = symbol in positions_by_symbol
            symbol_orders = orders_by_symbol.get(symbol, [])
            current_price = current_prices.get(symbol)
            
            symbol_stats = {
                "symbol": symbol,
                "has_position": has_position,
                "positions_count": len(positions_by_symbol.get(symbol, [])),
                "pending_orders_count": len(symbol_orders),
                "has_valid_pair": False,
                "orders_kept": 0,
                "orders_deleted": 0,
                "action_taken": False,
                "management_type": "WITH_POSITION" if has_position else "NO_POSITION"
            }
            
            if has_position:
                # --- CASE 1: Symbol HAS a position ---
                print(f"      📍 Symbol has a position - checking for opposite order with matching SL price")
                
                symbol_positions = positions_by_symbol[symbol]
                
                # Check if multiple positions exist for this symbol
                if len(symbol_positions) > 1:
                    print(f"      ⚠️  WARNING: Found {len(symbol_positions)} open positions for {symbol}!")
                    print(f"      This function expects a single position per symbol. Processing based on the first position only.")
                
                # Get the first position for this symbol
                position = symbol_positions[0]
                
                # Determine position type
                is_buy_position = position.type == mt5.POSITION_TYPE_BUY
                position_type_str = "BUY" if is_buy_position else "SELL"
                
                print(f"      • Position Ticket: {position.ticket}")
                print(f"      • Type: {position_type_str}")
                print(f"      • Volume: {position.volume}")
                print(f"      • Entry Price: {position.price_open}")
                print(f"      • SL Price: {position.sl}")
                print(f"      • Current Price: {position.price_current}")
                print(f"      • Found {len(symbol_orders)} pending orders for {symbol}")
                
                # Check if position has SL
                if position.sl is None or position.sl == 0:
                    print(f"      ⚠️  Position has no SL price set. Deleting ALL pending orders.")
                    # Delete all pending orders for this symbol
                    orders_to_delete = symbol_orders.copy()
                    symbol_stats["has_valid_pair"] = False
                else:
                    # Define opposite order type based on position direction
                    opposite_order_types = []
                    target_sl_price = position.sl
                    
                    if is_buy_position:
                        # For BUY position, look for SELL orders with entry price EQUAL to BUY SL
                        opposite_order_types = [mt5.ORDER_TYPE_SELL_LIMIT, mt5.ORDER_TYPE_SELL_STOP]
                        print(f"      • Looking for SELL order with entry price = BUY SL ({target_sl_price})")
                    else:
                        # For SELL position, look for BUY orders with entry price EQUAL to SELL SL
                        opposite_order_types = [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP]
                        print(f"      • Looking for BUY order with entry price = SELL SL ({target_sl_price})")
                    
                    # Find opposite orders with entry price exactly matching SL
                    matching_orders = []
                    other_orders = []
                    
                    for order in symbol_orders:
                        if order.type in opposite_order_types:
                            if abs(order.price_open - target_sl_price) < 0.00001:  # Float comparison with tolerance
                                matching_orders.append(order)
                                print(f"      ✅ Found matching order #{order.ticket} with entry price {order.price_open} = SL {target_sl_price}")
                            else:
                                other_orders.append(order)
                                print(f"       Order #{order.ticket} entry price {order.price_open} does NOT match SL {target_sl_price}")
                        else:
                            # Orders in same direction or other types
                            other_orders.append(order)
                    
                    # Keep only the first matching order (if any), delete all others
                    if matching_orders:
                        # Keep the first matching order
                        order_to_keep = matching_orders[0]
                        orders_to_keep = [order_to_keep]
                        orders_to_delete = matching_orders[1:] + other_orders
                        
                        order_type_name = "SELL" if is_buy_position else "BUY"
                        print(f"      🎯 Keeping opposite {order_type_name} order #{order_to_keep.ticket} with entry price matching SL")
                        symbol_stats["has_valid_pair"] = True
                        investor_has_valid_pair = True
                        symbol_stats["orders_kept"] = len(orders_to_keep)
                        stats["orders_kept"] += len(orders_to_keep)
                    else:
                        # No matching order found
                        orders_to_delete = symbol_orders.copy()
                        print(f"       No opposite order found with entry price matching SL ({target_sl_price})")
                        symbol_stats["has_valid_pair"] = False
                
                # Delete all non-matching orders
                if orders_to_delete:
                    print(f"      🗑️  Deleting {len(orders_to_delete)} order(s)...")
                    symbol_stats["action_taken"] = True
                    
                    for order in orders_to_delete:
                        order_type_name = "UNKNOWN"
                        if order.type == mt5.ORDER_TYPE_BUY_LIMIT:
                            order_type_name = "BUY LIMIT"
                        elif order.type == mt5.ORDER_TYPE_SELL_LIMIT:
                            order_type_name = "SELL LIMIT"
                        elif order.type == mt5.ORDER_TYPE_BUY_STOP:
                            order_type_name = "BUY STOP"
                        elif order.type == mt5.ORDER_TYPE_SELL_STOP:
                            order_type_name = "SELL STOP"
                        
                        print(f"        • Deleting order #{order.ticket} ({order_type_name} @ {order.price_open})...")
                        
                        delete_request = {
                            "action": mt5.TRADE_ACTION_REMOVE,
                            "order": order.ticket,
                        }
                        
                        result = mt5.order_send(delete_request)
                        
                        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                            symbol_stats["orders_deleted"] += 1
                            stats["orders_deleted"] += 1
                            print(f"          ✅ Deleted successfully")
                        else:
                            stats["errors"] += 1
                            error_msg = result.comment if result else f"Error code: {result.retcode if result else 'Unknown'}"
                            print(f"           Deletion failed: {error_msg}")
            
            else:
                # --- CASE 2: Symbol has NO position, only pending orders ---
                print(f"      📍 Symbol has NO position - finding closest BUY/SELL orders to current price")
                
                if not current_price:
                    print(f"      ⚠️  Cannot get current price for {symbol}. Deleting all pending orders.")
                    orders_to_delete = symbol_orders.copy()
                    symbol_stats["has_valid_pair"] = False
                    symbol_stats["orders_deleted"] = len(orders_to_delete)
                    stats["orders_deleted"] += len(orders_to_delete)
                    symbol_stats["action_taken"] = True if orders_to_delete else False
                    
                    # Delete all orders
                    for order in orders_to_delete:
                        delete_request = {
                            "action": mt5.TRADE_ACTION_REMOVE,
                            "order": order.ticket,
                        }
                        result = mt5.order_send(delete_request)
                        if result and result.retcode != mt5.TRADE_RETCODE_DONE:
                            stats["errors"] += 1
                    
                    symbol_results.append(symbol_stats)
                    stats["symbols_processed"] += 1
                    continue
                
                print(f"      • Current Price: {current_price}")
                print(f"      • Found {len(symbol_orders)} pending orders for {symbol}")
                
                # Separate BUY and SELL orders
                buy_orders = []
                sell_orders = []
                
                for order in symbol_orders:
                    if order.type in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP]:
                        buy_orders.append(order)
                    elif order.type in [mt5.ORDER_TYPE_SELL_LIMIT, mt5.ORDER_TYPE_SELL_STOP]:
                        sell_orders.append(order)
                
                print(f"      • Found {len(buy_orders)} BUY orders")
                print(f"      • Found {len(sell_orders)} SELL orders")
                
                # STEP 1: Find closest BUY order to current price
                closest_buy = None
                if buy_orders:
                    closest_buy = min(buy_orders, key=lambda o: abs(o.price_open - current_price))
                    buy_distance = abs(closest_buy.price_open - current_price)
                    print(f"      🎯 Closest BUY order to CURRENT PRICE ({current_price}):")
                    print(f"      • Ticket: {closest_buy.ticket}")
                    print(f"      • Type: {'BUY LIMIT' if closest_buy.type == mt5.ORDER_TYPE_BUY_LIMIT else 'BUY STOP'}")
                    print(f"      • Entry: {closest_buy.price_open}")
                    print(f"      • SL: {closest_buy.sl}")
                    print(f"      • Distance: {buy_distance:.5f}")
                else:
                    print(f"      ℹ️  No BUY orders found")
                
                # STEP 2: Find closest SELL order to current price
                closest_sell = None
                if sell_orders:
                    closest_sell = min(sell_orders, key=lambda o: abs(o.price_open - current_price))
                    sell_distance = abs(closest_sell.price_open - current_price)
                    print(f"      🎯 Closest SELL order to CURRENT PRICE ({current_price}):")
                    print(f"      • Ticket: {closest_sell.ticket}")
                    print(f"      • Type: {'SELL LIMIT' if closest_sell.type == mt5.ORDER_TYPE_SELL_LIMIT else 'SELL STOP'}")
                    print(f"      • Entry: {closest_sell.price_open}")
                    print(f"      • SL: {closest_sell.sl}")
                    print(f"      • Distance: {sell_distance:.5f}")
                else:
                    print(f"      ℹ️  No SELL orders found")
                
                # STEP 3: Check if we have both a BUY and SELL order
                if closest_buy and closest_sell:
                    # Check for valid SL relationship
                    valid_sl_match = False
                    
                    # Check if BUY entry equals SELL SL
                    if closest_buy.sl is not None and abs(closest_buy.sl - closest_sell.price_open) < 0.00001:
                        valid_sl_match = True
                        print(f"      ✅ Valid SL match: BUY SL ({closest_buy.sl}) = SELL entry ({closest_sell.price_open})")
                    
                    # Check if SELL entry equals BUY SL
                    elif closest_sell.sl is not None and abs(closest_sell.sl - closest_buy.price_open) < 0.00001:
                        valid_sl_match = True
                        print(f"      ✅ Valid SL match: SELL SL ({closest_sell.sl}) = BUY entry ({closest_buy.price_open})")
                    
                    if valid_sl_match:
                        # Keep both closest orders, delete all others
                        orders_to_keep = [closest_buy, closest_sell]
                        orders_to_delete = [o for o in symbol_orders if o.ticket not in [closest_buy.ticket, closest_sell.ticket]]
                        
                        print(f"      🎯 Keeping valid BUY/SELL pair (closest to current price with SL match)")
                        symbol_stats["has_valid_pair"] = True
                        investor_has_valid_pair = True
                        symbol_stats["orders_kept"] = len(orders_to_keep)
                        stats["orders_kept"] += len(orders_to_keep)
                    else:
                        # No valid SL relationship - delete ALL orders
                        orders_to_delete = symbol_orders.copy()
                        orders_to_keep = []
                        print(f"       Closest orders do NOT have valid SL relationship - deleting ALL orders")
                        symbol_stats["has_valid_pair"] = False
                else:
                    # Missing either BUY or SELL order - delete ALL orders
                    orders_to_delete = symbol_orders.copy()
                    orders_to_keep = []
                    print(f"       Missing either BUY or SELL order - deleting ALL orders")
                    symbol_stats["has_valid_pair"] = False
                
                # Delete orders
                if orders_to_delete:
                    print(f"      🗑️  Deleting {len(orders_to_delete)} order(s)...")
                    symbol_stats["action_taken"] = True
                    
                    for order in orders_to_delete:
                        order_type_name = "UNKNOWN"
                        if order.type == mt5.ORDER_TYPE_BUY_LIMIT:
                            order_type_name = "BUY LIMIT"
                        elif order.type == mt5.ORDER_TYPE_SELL_LIMIT:
                            order_type_name = "SELL LIMIT"
                        elif order.type == mt5.ORDER_TYPE_BUY_STOP:
                            order_type_name = "BUY STOP"
                        elif order.type == mt5.ORDER_TYPE_SELL_STOP:
                            order_type_name = "SELL STOP"
                        
                        print(f"        • Deleting order #{order.ticket} ({order_type_name} @ {order.price_open})...")
                        
                        delete_request = {
                            "action": mt5.TRADE_ACTION_REMOVE,
                            "order": order.ticket,
                        }
                        
                        result = mt5.order_send(delete_request)
                        
                        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                            symbol_stats["orders_deleted"] += 1
                            stats["orders_deleted"] += 1
                            print(f"          ✅ Deleted successfully")
                        else:
                            stats["errors"] += 1
                            error_msg = result.comment if result else f"Error code: {result.retcode if result else 'Unknown'}"
                            print(f"           Deletion failed: {error_msg}")
            
            symbol_results.append(symbol_stats)
            stats["symbols_processed"] += 1
            
            # Display per-symbol summary
            print(f"      📊 {symbol} Summary:")
            print(f"      • Management Type: {symbol_stats['management_type']}")
            print(f"      • Has valid SL match: {'✅ YES' if symbol_stats['has_valid_pair'] else ' NO'}")
            print(f"      • Orders kept: {symbol_stats['orders_kept']}")
            print(f"      • Orders deleted: {symbol_stats['orders_deleted']}")
            
            # Store status
            if has_position:
                stats["symbol_status"][symbol] = "VALID_SL_MATCH" if symbol_stats["has_valid_pair"] else "NO_SL_MATCH"
            else:
                if symbol_stats["has_valid_pair"]:
                    stats["symbol_status"][symbol] = "VALID_PAIR_CLOSEST_WITH_SL_MATCH"
                else:
                    stats["symbol_status"][symbol] = "NO_VALID_PAIR_ALL_DELETED"
        
        # --- DETERMINE FINAL upload_orders FLAG ---
        # CRITICAL: upload_orders should be:
        # - True if NO symbol has a valid SL match
        # - False if AT LEAST ONE symbol has a valid SL match
        
        if investor_has_valid_pair:
            stats["upload_orders"] = False
            print(f"\n  └─ 🚩 upload_orders = False (At least one symbol has valid SL match)")
        else:
            stats["upload_orders"] = True
            print(f"\n  └─ 🚩 upload_orders = True (No symbol has valid SL match)")
        
        stats["processing_success"] = True
        
        # --- INVESTOR SUMMARY ---
        print(f"\n  └─ 📊 Management Results for {user_brokerid}:")
        print(f"      • Symbols processed: {len(symbol_results)}")
        print(f"      • Total positions: {total_positions}")
        print(f"      • Total pending orders: {total_pending}")
        print(f"      • Orders kept: {stats['orders_kept']}")
        print(f"      • Orders deleted: {stats['orders_deleted']}")
        print(f"      • upload_orders flag: {stats['upload_orders']}")
        
        # Show per-symbol breakdown
        if symbol_results:
            print(f"      • Per-symbol breakdown:")
            for sym_result in symbol_results:
                if sym_result['has_position']:
                    status = "✅ VALID SL MATCH" if sym_result['has_valid_pair'] else " NO SL MATCH"
                else:
                    if sym_result['has_valid_pair']:
                        status = "✅ VALID PAIR (closest orders with SL match)"
                    else:
                        status = " NO VALID PAIR (all orders deleted)"
                print(f"        - {sym_result['symbol']}: {status} (kept: {sym_result['orders_kept']}, deleted: {sym_result['orders_deleted']})")
        
        if stats['errors'] > 0:
            print(f"      • Errors: {stats['errors']}")
        else:
            print(f"      ✅ Management completed successfully")

    # --- FINAL SUMMARY ---
    print(f"\n{'='*10} 📊 SINGLE POSITION & PENDING ORDER MANAGEMENT SUMMARY (PER SYMBOL) {'='*10}")
    print(f"   Investor ID: {stats['investor_id']}")
    print(f"   Investors processed: {stats['investors_processed']}")
    print(f"   Total positions found: {stats['positions_found']}")
    print(f"   Total pending orders found: {stats['pending_orders_found']}")
    print(f"   Symbols processed: {stats['symbols_processed']}")
    print(f"   Orders kept: {stats['orders_kept']}")
    print(f"   Orders deleted: {stats['orders_deleted']}")
    print(f"   Errors: {stats['errors']}")
    print(f"   FINAL upload_orders flag: {stats['upload_orders']}")
    
    # Show symbol status summary
    if stats['symbol_status']:
        print(f"\n   Symbol Status Summary:")
        for symbol, status in stats['symbol_status'].items():
            print(f"      • {symbol}: {status}")
    
    if stats['orders_deleted'] > 0 or stats['orders_kept'] > 0:
        print(f"\n   Management Action: {'✅ COMPLETED' if stats['processing_success'] else '⚠️  PARTIAL'}")
    else:
        print(f"\n   Management Action: ℹ️  No action needed")
    
    print(f"\n{'='*10} 🏁 SINGLE POSITION & PENDING ORDER MANAGEMENT COMPLETE {'='*10}\n")
    return stats

def martingale_old(inv_id=None):
    """
    Function: Checks martingale status using staged drawdown approach.
    
    STAGED DRAWDOWN LOGIC:
    - Each stage has a maximum loss limit defined by martingale_risk_management
    - When drawdown exceeds the stage limit, we move to the next stage
    - Only the CURRENT STAGE DRAWDOWN (remainder) is processed for recovery
    - If remainder = 0 (exact multiple), we use account_balance_default_risk_management as floor
    
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
        "current_balance": 0.0,
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

        # ========== SECTION 3: GET EXECUTION START BALANCE ==========
        def get_execution_start_balance():
            """Get the exact balance on execution start date"""
            execution_start_date = None
            
            # Try to get execution_start_date from activities.json
            activities_path = inv_root / "activities.json"
            if activities_path.exists():
                try:
                    with open(activities_path, 'r', encoding='utf-8') as f:
                        activities = json.load(f)
                        execution_start_date = activities.get('execution_start_date')
                except Exception:
                    pass
            
            # If not found, try accountmanagement.json
            if not execution_start_date and acc_mgmt_path.exists():
                try:
                    with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                        acc_mgmt = json.load(f)
                        execution_start_date = acc_mgmt.get('execution_start_date')
                except Exception:
                    pass
            
            # If no execution start date found, use current balance
            if not execution_start_date:
                print(f"  │ ⚠️ No execution start date found - using current balance as baseline")
                return current_balance
            
            # Parse the execution start date
            start_datetime = None
            for fmt in ["%B %d, %Y", "%Y-%m-%d"]:
                try:
                    start_datetime = datetime.strptime(execution_start_date, fmt).replace(hour=0, minute=0, second=0)
                    break
                except:
                    continue
            
            if not start_datetime:
                print(f"  │ ⚠️ Could not parse execution start date: {execution_start_date}")
                return current_balance
            
            print(f"  │ Execution start date: {start_datetime.strftime('%Y-%m-%d')}")
            
            # Get all deals from execution start date to now
            all_deals = mt5.history_deals_get(start_datetime, datetime.now())
            
            if not all_deals:
                print(f"  │ No deals found since execution start - using current balance")
                return current_balance
            
            # Calculate the starting balance by reversing all transactions
            # Starting Balance = Current Balance - (Total Profits) + (Total Losses) - (Net Deposits)
            total_profits = 0.0
            total_losses = 0.0
            total_deposits = 0.0
            total_withdrawals = 0.0
            
            for deal in all_deals:
                total_pl = deal.profit + deal.commission + deal.swap
                
                if deal.type == 2:  # Deposit
                    total_deposits += deal.profit
                elif deal.type == 3:  # Withdrawal
                    withdrawal_amount = abs(deal.profit) if deal.profit < 0 else deal.profit
                    total_withdrawals += withdrawal_amount
                elif deal.type in [0, 1]:  # Deal types for trades
                    if total_pl > 0:
                        total_profits += total_pl
                    elif total_pl < 0:
                        total_losses += abs(total_pl)
            
            # Calculate net deposits
            net_deposits = total_deposits - total_withdrawals
            
            # Starting balance = current - profits + losses - net_deposits
            starting_balance = current_balance - total_profits + total_losses - net_deposits
            
            # Ensure starting balance is not negative
            if starting_balance < 0:
                print(f"  │ ⚠WARNING: Calculated negative starting balance - using current balance")
                starting_balance = current_balance
            
            print(f"  │ Starting balance (on execution start): ${starting_balance:.2f}")
            print(f"  │   ├─ Total profits: ${total_profits:.2f}")
            print(f"  │   ├─ Total losses: ${total_losses:.2f}")
            print(f"  │   ├─ Net deposits: ${net_deposits:.2f}")
            print(f"  │   └─ Formula: {current_balance:.2f} - {total_profits:.2f} + {total_losses:.2f} - {net_deposits:.2f}")
            
            return starting_balance
        
        execution_start_balance = get_execution_start_balance()
        stats["execution_start_balance"] = execution_start_balance
        
        # Calculate total drawdown from execution start balance
        total_drawdown = execution_start_balance - current_balance
        total_drawdown = max(0, total_drawdown)
        stats["total_drawdown"] = total_drawdown
        
        print(f"\n  📉 Drawdown Analysis:")
        print(f"  │ Execution start balance: ${execution_start_balance:.2f}")
        print(f"  │ Current balance: ${current_balance:.2f}")
        print(f"  │ Total drawdown: ${total_drawdown:.2f}")
        
        if total_drawdown == 0:
            print(f"  │ ✓ No drawdown - account is at or above starting balance")
        else:
            print(f"  │ ⚠️ Drawdown detected: ${total_drawdown:.2f} ({(total_drawdown/execution_start_balance*100):.2f}%)")

        # ========== SECTION 4: STAGED DRAWDOWN CALCULATION ==========
        print(f"\n  🎯 STEP 2: Staged Drawdown Analysis")
        print(f"  {'─'*40}")
        
        def get_stage_max_risk():
            """Get martingale maximum risk per stage based on current balance"""
            martingale_risk_map = config.get("martingale_risk_management", {})
            
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
        
        # Calculate current stage and drawdown
        if total_drawdown > 0 and stage_max_risk > 0:
            current_stage = int(total_drawdown // stage_max_risk) + 1
            current_stage_drawdown = total_drawdown % stage_max_risk
            is_exact_stage_completion = (current_stage_drawdown == 0)
            
            # If exact completion, we need to use default_minimum_risk as the drawdown target
            if is_exact_stage_completion and current_stage > 1:
                # We completed a stage exactly, so we're at the start of next stage
                current_stage_drawdown = default_minimum_risk
                stats["used_minimum_risk"] = True
                print(f"  │ ⚠️ EXACT STAGE COMPLETION - using floor risk: ${default_minimum_risk:.2f}")
            
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
                print(f"        │ ⚠️ WARNING: Minimum volume {min_volume} lots has risk ${min_risk:.2f} which exceeds limit ${stage_max_risk:.2f}")
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
                
                print(f"        │ ⚠️ Risk limit would be exceeded: ${required_risk:.2f} > ${stage_max_risk:.2f}")
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
                    print(f"        │ ⚠️ Exact stage completion but floor volume would exceed risk limit - keeping reduced volume")
            
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
                print(f"  │ ⚠️ No limit_orders.json found")
                return False, {}
            
            try:
                volumes_to_update = {}
                all_symbols = get_all_symbols_from_limit_orders(orders_data)
                
                if not all_symbols:
                    print(f"  │ ⚠️ No symbols found")
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
                        status = "✓" if risk_check_passed else "⚠️"
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
                print(f"  │ ⚠️ signals.json not found")
                return False, {}
            
            try:
                volumes_to_update = {}
                all_symbols = set()
                
                for category_name, category_data in signals_data.get('categories', {}).items():
                    symbols_in_category = category_data.get('symbols', {})
                    for symbol in symbols_in_category.keys():
                        all_symbols.add(symbol)
                
                if not all_symbols:
                    print(f"  │ ⚠️ No symbols found")
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
                        status = "✓" if risk_check_passed else "⚠️"
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
                    print(f"  │ ⚠️ No open positions found - pre-scaling skipped")
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
                            print(f"     ⚠️ No stop loss set - skipping pre-scaling for {symbol}")
                            continue
                        
                        print(f"     Stop Loss: {position_sl:.5f}")
                        
                        symbol_info = mt5.symbol_info(symbol)
                        if not symbol_info:
                            print(f"     ⚠️ No symbol info for {symbol}")
                            continue
                        
                        contract_size = symbol_info.trade_contract_size
                        
                        # Calculate price difference based on position type
                        if position_type == mt5.POSITION_TYPE_BUY:
                            price_diff = position_entry - position_sl
                        else:
                            price_diff = position_sl - position_entry
                        
                        if price_diff <= 0:
                            print(f"     ⚠️ Invalid price difference: {price_diff}")
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
        print(f"  │ Current balance: ${stats['current_balance']:.2f}")
        print(f"  │ Total drawdown: ${stats['total_drawdown']:.2f}")
        
        print(f"\n  🎯 Staged Drawdown:")
        print(f"  │ Stage max risk: ${stats['stage_max_risk']:.2f}")
        print(f"  │ Current stage: {stats['current_stage']}")
        print(f"  │ Stage drawdown: ${stats['current_stage_drawdown']:.2f}")
        
        if stats.get('used_minimum_risk'):
            print(f"  │ ⚠️ Used floor risk: ${stats['default_minimum_risk']:.2f}")
        
        if stats.get('risk_exceeded'):
            print(f"  │ ⚠️ Risk limit was exceeded and adjusted")
        
        print(f"\n  📝 Modifications:")
        print(f"  │ limit_orders.json: {'✓' if stats.get('limit_orders_modified') else '−'}")
        print(f"  │ signals.json: {'✓' if stats.get('signals_modified') else '−'}")
        print(f"  │ Pre-scaling: {'✓' if stats.get('pre_scaling_applied') else '−'}")
        print(f"  │ Orders cancelled: {stats.get('safety_cancellations_count', 0)}")
        
        # Display risk validation details
        if stats.get('order_risk_validation'):
            print(f"\n  🔒 Risk Validation:")
            for symbol, details in stats['order_risk_validation'].items():
                status = "✓" if details.get('risk_check_passed') else "⚠️"
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

def martingale(inv_id=None):
    """
    Function: Checks martingale status using staged drawdown approach.
    
    STAGED DRAWDOWN LOGIC:
    - Each stage has a maximum loss limit defined by martingale_risk_management
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
            """Get execution start balance, trade statistics, and calculate later-balance"""
            execution_start_date = None
            
            # Try to get execution_start_date from activities.json
            activities_path = inv_root / "activities.json"
            if activities_path.exists():
                try:
                    with open(activities_path, 'r', encoding='utf-8') as f:
                        activities = json.load(f)
                        execution_start_date = activities.get('execution_start_date')
                except Exception:
                    pass
            
            # If not found, try accountmanagement.json
            if not execution_start_date and acc_mgmt_path.exists():
                try:
                    with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                        acc_mgmt = json.load(f)
                        execution_start_date = acc_mgmt.get('execution_start_date')
                except Exception:
                    pass
            
            # If no execution start date found, use current balance
            if not execution_start_date:
                print(f"  │ ⚠️ No execution start date found - using current balance as baseline")
                return current_balance, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
            
            # Parse the execution start date
            start_datetime = None
            for fmt in ["%B %d, %Y", "%Y-%m-%d"]:
                try:
                    start_datetime = datetime.strptime(execution_start_date, fmt).replace(hour=0, minute=0, second=0)
                    break
                except:
                    continue
            
            if not start_datetime:
                print(f"  │ ⚠️ Could not parse execution start date: {execution_start_date}")
                return current_balance, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
            
            print(f"  │ Execution start date: {start_datetime.strftime('%Y-%m-%d')}")
            
            # Get all deals from execution start date to now
            all_deals = mt5.history_deals_get(start_datetime, datetime.now())
            
            if not all_deals:
                print(f"  │ No deals found since execution start - using current balance")
                return current_balance, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
            
            # Calculate starting balance and trade statistics
            total_profits = 0.0
            total_losses = 0.0
            total_deposits = 0.0
            total_withdrawals = 0.0
            total_wins_value = 0.0
            total_losses_value = 0.0
            winning_trades_count = 0
            losing_trades_count = 0
            
            for deal in all_deals:
                total_pl = deal.profit + deal.commission + deal.swap
                
                if deal.type == 2:  # Deposit
                    total_deposits += deal.profit
                elif deal.type == 3:  # Withdrawal
                    withdrawal_amount = abs(deal.profit) if deal.profit < 0 else deal.profit
                    total_withdrawals += withdrawal_amount
                elif deal.type in [0, 1]:  # Deal types for trades
                    if total_pl > 0:
                        total_profits += total_pl
                        total_wins_value += total_pl
                        winning_trades_count += 1
                    elif total_pl < 0:
                        total_losses += abs(total_pl)
                        total_losses_value += abs(total_pl)
                        losing_trades_count += 1
            
            # Calculate net deposits
            net_deposits = total_deposits - total_withdrawals
            
            # Calculate starting balance
            starting_balance = current_balance - total_profits + total_losses - net_deposits
            
            # Ensure starting balance is not negative
            if starting_balance < 0:
                print(f"  │ ⚠️ WARNING: Calculated negative starting balance - using current balance")
                starting_balance = current_balance
            
            # Calculate later-balance (starting balance + total profits)
            later_balance = starting_balance + total_profits
            
            # Calculate winrate and lossrate based on monetary value
            total_value = total_wins_value + total_losses_value
            if total_value > 0:
                winrate = (total_wins_value / total_value) * 100
                lossrate = (total_losses_value / total_value) * 100
            else:
                winrate = 0
                lossrate = 0
            
            total_trades_count = winning_trades_count + losing_trades_count
            
            print(f"  │ Starting balance (on execution start): ${starting_balance:.2f}")
            print(f"  │ Total profits since start: ${total_profits:.2f}")
            print(f"  │ Total losses since start: ${total_losses:.2f}")
            print(f"  │ Net deposits: ${net_deposits:.2f}")
            print(f"  │ Later-balance (start + profits): ${later_balance:.2f}")
            print(f"  │ Trade Statistics (By Monetary Value):")
            print(f"  │   ├─ Total trades: {total_trades_count}")
            print(f"  │   ├─ Winning trades: {winning_trades_count} (${total_wins_value:.2f})")
            print(f"  │   ├─ Losing trades: {losing_trades_count} (${total_losses_value:.2f})")
            print(f"  │   ├─ Winrate (by value): {winrate:.2f}%")
            print(f"  │   └─ Lossrate (by value): {lossrate:.2f}%")
            print(f"  │ Formula: {current_balance:.2f} - {total_profits:.2f} + {total_losses:.2f} - {net_deposits:.2f}")
            
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
            print(f"  │ ⚠️ Drawdown detected: ${total_drawdown:.2f} ({(total_drawdown/later_balance*100):.2f}% from later-balance)")

        # ========== SECTION 4: STAGED DRAWDOWN CALCULATION ==========
        print(f"\n  🎯 STEP 2: Staged Drawdown Analysis")
        print(f"  {'─'*40}")
        
        def get_stage_max_risk():
            """Get martingale maximum risk per stage based on current balance"""
            martingale_risk_map = config.get("martingale_risk_management", {})
            
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
                print(f"  │ ⚠️ EXACT STAGE COMPLETION - using floor risk: ${default_minimum_risk:.2f}")
            
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
                print(f"        │ ⚠️ WARNING: Minimum volume {min_volume} lots has risk ${min_risk:.2f} which exceeds limit ${stage_max_risk:.2f}")
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
                
                print(f"        │ ⚠️ Risk limit would be exceeded: ${required_risk:.2f} > ${stage_max_risk:.2f}")
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
                    print(f"        │ ⚠️ Exact stage completion but floor volume would exceed risk limit - keeping reduced volume")
            
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
                print(f"  │ ⚠️ No limit_orders.json found")
                return False, {}
            
            try:
                volumes_to_update = {}
                all_symbols = get_all_symbols_from_limit_orders(orders_data)
                
                if not all_symbols:
                    print(f"  │ ⚠️ No symbols found")
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
                        status = "✓" if risk_check_passed else "⚠️"
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
                print(f"  │ ⚠️ signals.json not found")
                return False, {}
            
            try:
                volumes_to_update = {}
                all_symbols = set()
                
                for category_name, category_data in signals_data.get('categories', {}).items():
                    symbols_in_category = category_data.get('symbols', {})
                    for symbol in symbols_in_category.keys():
                        all_symbols.add(symbol)
                
                if not all_symbols:
                    print(f"  │ ⚠️ No symbols found")
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
                        status = "✓" if risk_check_passed else "⚠️"
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
                    print(f"  │ ⚠️ No open positions found - pre-scaling skipped")
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
                            print(f"     ⚠️ No stop loss set - skipping pre-scaling for {symbol}")
                            continue
                        
                        print(f"     Stop Loss: {position_sl:.5f}")
                        
                        symbol_info = mt5.symbol_info(symbol)
                        if not symbol_info:
                            print(f"     ⚠️ No symbol info for {symbol}")
                            continue
                        
                        contract_size = symbol_info.trade_contract_size
                        
                        # Calculate price difference based on position type
                        if position_type == mt5.POSITION_TYPE_BUY:
                            price_diff = position_entry - position_sl
                        else:
                            price_diff = position_sl - position_entry
                        
                        if price_diff <= 0:
                            print(f"     ⚠️ Invalid price difference: {price_diff}")
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
            print(f"  │ ⚠️ Used floor risk: ${stats['default_minimum_risk']:.2f}")
        
        if stats.get('risk_exceeded'):
            print(f"  │ ⚠️ Risk limit was exceeded and adjusted")
        
        print(f"\n  📝 Modifications:")
        print(f"  │ limit_orders.json: {'✓' if stats.get('limit_orders_modified') else '−'}")
        print(f"  │ signals.json: {'✓' if stats.get('signals_modified') else '−'}")
        print(f"  │ Pre-scaling: {'✓' if stats.get('pre_scaling_applied') else '−'}")
        print(f"  │ Orders cancelled: {stats.get('safety_cancellations_count', 0)}")
        
        # Display risk validation details
        if stats.get('order_risk_validation'):
            print(f"\n  🔒 Risk Validation:")
            for symbol, details in stats['order_risk_validation'].items():
                status = "✓" if details.get('risk_check_passed') else "⚠️"
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

def check_pending_orders_risk(inv_id=None):
    """
    Function 3: Validates live pending orders against the account's current risk bucket.
     VERSION: Uses the EXACT account initialization logic from place_usd_orders_for_accounts()
    Only removes orders with risk HIGHER than allowed (lower risk orders are kept).
    
    NOW CHECKS: ALL pending orders (LIMIT, STOP, STOP-LIMIT)
    
    RISK CONFIGURATION LOGIC:
    - If enable_martingale = true: USE martingale_risk_management (balance-based risk from dedicated section)
    - Else if enable_maximum_account_balance_management = true -> use account_balance_maximum_risk_management
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
        "martingale_active": False,
        "martingale_max_risk": 0.0,
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
            print(f"  └─ ⚠️  Account config missing. Skipping.")
            continue

        # --- LOAD CONFIG AND DETERMINE RISK CONFIGURATION TO USE ---
        try:
            with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Get settings flags
            settings = config.get("settings", {})
            enable_martingale = settings.get("enable_martingale", False)
            enable_default = settings.get("enable_default_account_balance_management", False)
            enable_maximum = settings.get("enable_maximum_account_balance_management", False)
            
            print(f"  └─ ⚙️  Risk Configuration Settings:")
            print(f"      • enable_martingale: {enable_martingale}")
            print(f"      • enable_default_account_balance_management: {enable_default}")
            print(f"      • enable_maximum_account_balance_management: {enable_maximum}")
            
            # Determine which risk config to use
            risk_map = None
            risk_config_used = None
            primary_risk = None
            
            # Get account info first to get current balance
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
            print(f"      • Current Balance: ${balance:.2f}")
            
            # NEW LOGIC: If martingale is enabled, USE martingale_risk_management section
            if enable_martingale:
                martingale_risk_map = config.get("account_balance_maximum_risk_management", {})
                
                if martingale_risk_map:
                    print(f"      📋 USING: martingale risk management (balance-based)")
                    print(f"      🔍 Finding risk for balance ${balance:.2f}...")
                    
                    # Parse the risk map to find the appropriate risk for current balance
                    for range_str, risk_value in martingale_risk_map.items():
                        try:
                            # Extract the balance range from the key (e.g., "1000-90000.99_risk" -> "1000-90000.99")
                            raw_range = range_str.split("_")[0]
                            low_str, high_str = raw_range.split("-")
                            low = float(low_str)
                            high = float(high_str)
                            
                            if low <= balance <= high:
                                primary_risk = float(risk_value)
                                risk_config_used = f"martingale_risk_management ({range_str})"
                                stats["martingale_active"] = True
                                stats["martingale_max_risk"] = primary_risk
                                print(f"      • Found matching range: {range_str}")
                                print(f"      • Risk limit: ${primary_risk:.2f}")
                                break
                        except Exception as e:
                            print(f"      ⚠️  Error parsing range '{range_str}': {e}")
                            continue
                    
                    if primary_risk is None:
                        print(f"      ⚠️  No risk mapping found for balance ${balance:.2f} in martingale_risk_management")
                        print(f"      Using default risk: $500")
                        primary_risk = 500
                        risk_config_used = "martingale_risk_management (default fallback)"
                        stats["martingale_max_risk"] = primary_risk
                else:
                    print(f"      ⚠️  No martingale_risk_management section found in config")
                    print(f"      Using default risk: $500")
                    primary_risk = 500
                    risk_config_used = "martingale_risk_management (missing section - fallback)"
                    stats["martingale_max_risk"] = primary_risk
                
                stats["martingale_active"] = True
                print(f"      ℹ️  martingale is enabled - using balance-based martingale risk management")
            
            # If martingale is NOT enabled, use account balance risk management
            else:
                stats["martingale_active"] = False
                
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
                
                # Determine Primary Risk Value based on selected risk map
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

        except Exception as e:
            print(f"  └─  Failed to read config: {e}")
            continue

        print(f"\n  └─ 💰 Target Risk: ${primary_risk:.2f}")
        print(f"  └─ 📋 Risk Source: {risk_config_used}")
        
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
                            print(f"        Cancel failed: {error_msg}")
                    
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
            print(f"       • Risk source: {risk_config_used}")
            if stats["martingale_active"]:
                print(f"       • martingale Active: ✅ YES (risk limit: ${primary_risk:.2f})")
            else:
                print(f"       • martingale Active:  NO")
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
    if stats['martingale_active']:
        print(f"   martingale Active: ✅ YES (using martingale_risk_management)")
        print(f"   martingale Max Risk: ${stats['martingale_max_risk']:.2f}")
    else:
        print(f"   martingale Active:  NO (using account balance management)")
    print(f"   Orders checked: {stats['orders_checked']}")
    print(f"   Orders removed: {stats['orders_removed']}")
    print(f"   Orders kept (lower risk): {stats['orders_kept_lower']}")
    print(f"   Orders kept (in tolerance): {stats['orders_kept_in_range']}")
    
    if stats['orders_checked'] > 0:
        removal_rate = (stats['orders_removed'] / stats['orders_checked']) * 100
        print(f"   Removal rate: {removal_rate:.1f}%")
    
    print(f"\n{'='*10} 🏁 RISK AUDIT COMPLETE {'='*10}\n")
    return stats

def orders_risk_correction(inv_id=None):
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
            print(f"  └─  No broker config found")
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
            print(f"  └─  Failed to read config: {e}")
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
                print(f"  └─   login failed: {error}")
                stats["orders_error"] += 1
                continue
            print(f"      ✅ Successfully logged into account")
        else:
            print(f"      ✅ Already logged into account")
        # --- END EXACT INITIALIZATION COPY ---

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
                            print(f"        Modification failed: {error_msg}")
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
                                    print(f"        Fallback modification failed")
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
                        print(f"        Fallback calculation error: {e}")
        
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
                            print(f"        Modification failed: {error_msg}")
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
                                    print(f"        Fallback modification failed")
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
                        print(f"        Fallback calculation error: {e}")

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

def adjust_pending_orders_to_max_risk(inv_id=None):
    """
    Adjust pending orders to match maximum risk configuration.
    
    ONLY ACTIVE WHEN: enable_maximum_account_balance_management = true
    
    Uses the SAME risk calculation method as orders_risk_correction() for consistency.
    
    Args:
        inv_id: Optional specific investor ID to process
        
    Returns:
        dict: Statistics about the adjustments
    """
    print(f"\n{'='*10} 🎯 ADJUST PENDING ORDERS TO MAX RISK {'='*10}")
    if inv_id:
        print(f" Processing single investor: {inv_id}")
    
    # Statistics for this run
    stats = {
        "investor_id": inv_id if inv_id else "all",
        "investors_skipped_due_to_settings": 0,
        "investors_with_max_config": 0,
        "total_symbols_analyzed": 0,
        "symbols_with_liquidator_orders": 0,
        "liquidator_orders_found": 0,
        "pending_orders_found": 0,
        "pending_orders_matched": 0,
        "pending_orders_adjusted": 0,
        "pending_orders_skipped_error": 0,
        "adjustment_failures": 0,
        "orders_increased_risk": 0,
        "orders_decreased_risk": 0,
        "max_risk_values": {},
        "adjustments_made": [],
        "symbol_details": {}
    }
    
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
        print(f"\n[{processed}/{total_investors}] {user_brokerid} 🔍 Checking maximum risk configuration...")
        
        # Get broker config
        broker_cfg = usersdictionary.get(user_brokerid)
        if not broker_cfg:
            print(f"  └─  No broker config found")
            continue
        
        inv_root = Path(INV_PATH) / user_brokerid
        prices_dir = inv_root / "prices"
        acc_mgmt_path = inv_root / "accountmanagement.json"
        signals_path = prices_dir / "signals.json"
        
        if not acc_mgmt_path.exists():
            print(f"  └─ ⚠️  accountmanagement.json not found - skipping")
            stats["investors_skipped_due_to_settings"] += 1
            continue
        
        # =====================================================
        # STEP 1: Check account management settings for maximum config
        # =====================================================
        try:
            with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                acc_config = json.load(f)
            
            # Check if maximum account balance management is enabled
            settings = acc_config.get("settings", {})
            enable_maximum = settings.get("enable_maximum_account_balance_management", False)
            
            if not enable_maximum:
                print(f"  └─ ⏭️ Maximum account balance management is DISABLED")
                stats["investors_skipped_due_to_settings"] += 1
                continue
            
            print(f"  └─ ✅ Maximum account balance management is ENABLED")
            
            # Get maximum risk configuration
            max_risk_config = acc_config.get("account_balance_maximum_risk_management", {})
            if not max_risk_config:
                print(f"  └─ ⚠️ account_balance_maximum_risk_management is empty or missing")
                continue
            
            stats["investors_with_max_config"] += 1
            
        except Exception as e:
            print(f"  └─  Error reading accountmanagement.json: {e}")
            stats["investors_skipped_due_to_settings"] += 1
            continue
        
        # =====================================================
        # STEP 2: Load signals.json to find orders with liquidator flags
        # =====================================================
        if not signals_path.exists():
            print(f"  └─  signals.json not found at {signals_path}")
            continue
        
        try:
            with open(signals_path, 'r', encoding='utf-8') as f:
                signals_data = json.load(f)
            print(f"  └─ 📂 Loaded signals.json")
        except Exception as e:
            print(f"  └─  Failed to load signals.json: {e}")
            continue
        
        # =====================================================
        # STEP 3: Account connection check
        # =====================================================
        print(f"  └─ 🔌 Checking account connection...")
        
        login_id = int(broker_cfg['LOGIN_ID'])
        mt5_path = broker_cfg["TERMINAL_PATH"]
        
        print(f"      • Terminal Path: {mt5_path}")
        print(f"      • Login ID: {login_id}")
        
        # Check if already logged into correct account
        acc = mt5.account_info()
        if acc is None or acc.login != login_id:
            print(f"      🔑 Logging into account...")
            if not mt5.login(login_id, password=broker_cfg["PASSWORD"], server=broker_cfg["SERVER"]):
                error = mt5.last_error()
                print(f"  └─  Login failed: {error}")
                stats["adjustment_failures"] += 1
                continue
            print(f"      ✅ Successfully logged into account")
        else:
            print(f"      ✅ Already logged into account")
        
        acc_info = mt5.account_info()
        if not acc_info:
            print(f"  └─  Failed to get account info")
            stats["adjustment_failures"] += 1
            continue
        
        balance = acc_info.balance
        print(f"      • Balance: ${balance:,.2f}")
        
        # Determine maximum risk value based on balance
        max_risk = None
        for range_str, risk_val in max_risk_config.items():
            try:
                raw_range = range_str.split("_")[0]
                low, high = map(float, raw_range.split("-"))
                if low <= balance <= high:
                    max_risk = float(risk_val)
                    break
            except Exception as e:
                print(f"      ⚠️ Error parsing range '{range_str}': {e}")
                continue
        
        if max_risk is None:
            print(f"  └─ ⚠️ No maximum risk mapping for balance ${balance:,.2f}")
            continue
        
        print(f"  └─ 💰 Maximum Risk Target: ${max_risk:.2f}")
        stats["max_risk_values"][user_brokerid] = max_risk
        
        # =====================================================
        # STEP 4: Get all live pending orders
        # =====================================================
        pending_orders = mt5.orders_get()
        if not pending_orders:
            print(f"  └─ 🔘 No pending orders found")
            continue
        
        # Create lookup dictionary for pending orders by ticket number
        pending_by_ticket = {}
        for order in pending_orders:
            if order.type not in ORDER_TYPES.keys():
                continue
            
            pending_by_ticket[order.ticket] = {
                'ticket': order.ticket,
                'type': order.type,
                'type_name': ORDER_TYPES.get(order.type, f"Unknown"),
                'symbol': order.symbol,
                'volume': order.volume_initial,
                'price_open': order.price_open,
                'sl': order.sl,
                'tp': order.tp,
                'comment': order.comment
            }
        
        print(f"  └─ 📊 Found {len(pending_orders)} total pending orders")
        stats["pending_orders_found"] += len(pending_orders)
        
        # =====================================================
        # STEP 5: Process each symbol for liquidator orders
        # =====================================================
        changes_made_to_signals = False
        investor_orders_adjusted = 0
        investor_orders_increased = 0
        investor_orders_decreased = 0
        investor_orders_skipped_error = 0
        investor_liquidator_orders_found = 0
        
        for category_name, category_data in signals_data.get('categories', {}).items():
            symbols_in_category = category_data.get('symbols', {})
            
            for symbol in symbols_in_category:
                symbol_signals = symbols_in_category[symbol]
                stats["total_symbols_analyzed"] += 1
                
                print(f"\n    🔍 Analyzing {symbol} for liquidator orders...")
                
                # Collect all orders with liquidator flags
                liquidator_orders = []
                
                # Check bid_orders
                for idx, order in enumerate(symbol_signals.get('bid_orders', [])):
                    # Check main order
                    if (order.get('first_both_levels_green_liquidator') or 
                        order.get('first_both_levels_red_liquidator')):
                        order_copy = order.copy()
                        order_copy['_location'] = 'bid'
                        order_copy['_is_main'] = True
                        order_copy['_signal_index'] = idx
                        liquidator_orders.append(order_copy)
                    
                    # Check counter order
                    if 'order_counter' in order:
                        counter = order['order_counter']
                        if (counter.get('first_both_levels_green_liquidator') or 
                            counter.get('first_both_levels_red_liquidator')):
                            counter_copy = counter.copy()
                            counter_copy['_location'] = 'bid'
                            counter_copy['_is_main'] = False
                            counter_copy['_parent_entry'] = order.get('entry')
                            counter_copy['_signal_index'] = idx
                            liquidator_orders.append(counter_copy)
                
                # Check ask_orders
                for idx, order in enumerate(symbol_signals.get('ask_orders', [])):
                    # Check main order
                    if (order.get('first_both_levels_green_liquidator') or 
                        order.get('first_both_levels_red_liquidator')):
                        order_copy = order.copy()
                        order_copy['_location'] = 'ask'
                        order_copy['_is_main'] = True
                        order_copy['_signal_index'] = idx
                        liquidator_orders.append(order_copy)
                    
                    # Check counter order
                    if 'order_counter' in order:
                        counter = order['order_counter']
                        if (counter.get('first_both_levels_green_liquidator') or 
                            counter.get('first_both_levels_red_liquidator')):
                            counter_copy = counter.copy()
                            counter_copy['_location'] = 'ask'
                            counter_copy['_is_main'] = False
                            counter_copy['_parent_entry'] = order.get('entry')
                            counter_copy['_signal_index'] = idx
                            liquidator_orders.append(counter_copy)
                
                if not liquidator_orders:
                    print(f"      ⏳ No liquidator orders found for {symbol}")
                    continue
                
                stats["symbols_with_liquidator_orders"] += 1
                investor_liquidator_orders_found += len(liquidator_orders)
                stats["liquidator_orders_found"] += len(liquidator_orders)
                print(f"      🎯 Found {len(liquidator_orders)} liquidator order(s)")
                
                # For each liquidator order, try to find matching pending order
                for sig_order in liquidator_orders:
                    sig_entry = sig_order.get('entry')
                    sig_exit = sig_order.get('exit')
                    sig_order_type = sig_order.get('order_type')
                    sig_volume = sig_order.get('volume')
                    
                    # Skip if missing critical data
                    if not all([sig_entry, sig_exit, sig_order_type, sig_volume]):
                        print(f"        ⚠️ Liquidator order missing critical data - skipping")
                        investor_orders_skipped_error += 1
                        stats["pending_orders_skipped_error"] += 1
                        continue
                    
                    # Determine order direction
                    is_buy = sig_order_type.startswith('buy_')
                    calc_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
                    
                    # =====================================================
                    # STEP 6: Calculate current risk using MT5's order_calc_profit (same as orders_risk_correction)
                    # =====================================================
                    sl_profit = mt5.order_calc_profit(calc_type, symbol, sig_volume, sig_entry, sig_exit)
                    
                    if sl_profit is None:
                        print(f"        ⚠️ Could not calculate risk for order at {sig_entry}")
                        investor_orders_skipped_error += 1
                        stats["pending_orders_skipped_error"] += 1
                        continue
                    
                    current_risk = abs(sl_profit)
                    
                    print(f"\n        📋 Liquidator Order Details:")
                    print(f"          • Type: {sig_order_type}")
                    print(f"          • Entry: {sig_entry}")
                    print(f"          • Exit: {sig_exit}")
                    print(f"          • Volume: {sig_volume}")
                    print(f"          • Current Risk: ${current_risk:.2f}")
                    print(f"          • Target Max Risk: ${max_risk:.2f}")
                    
                    # Calculate risk difference
                    risk_difference = current_risk - max_risk
                    
                    # Determine adjustment direction
                    if abs(risk_difference) < 0.01:  # Within 1 cent, no adjustment needed
                        print(f"          ✅ Risk already exactly at maximum (${current_risk:.2f} = ${max_risk:.2f})")
                        continue
                    
                    if risk_difference < 0:
                        direction = "increase"
                        print(f"          📊 Need to INCREASE risk by: ${abs(risk_difference):.2f}")
                    else:
                        direction = "decrease"
                        print(f"          📊 Need to DECREASE risk by: ${risk_difference:.2f}")
                    
                    # =====================================================
                    # STEP 7: Find matching pending order by properties
                    # =====================================================
                    matching_pending = None
                    
                    # Search through all pending orders for this symbol
                    for ticket, pending in pending_by_ticket.items():
                        if pending['symbol'] != symbol:
                            continue
                        
                        pending_type = pending['type']
                        pending_price = pending['price_open']
                        pending_volume = pending['volume']
                        
                        # Check if order types match
                        type_matches = False
                        if sig_order_type == "buy_stop" and pending_type == mt5.ORDER_TYPE_BUY_STOP:
                            type_matches = True
                        elif sig_order_type == "sell_stop" and pending_type == mt5.ORDER_TYPE_SELL_STOP:
                            type_matches = True
                        elif sig_order_type == "buy_limit" and pending_type == mt5.ORDER_TYPE_BUY_LIMIT:
                            type_matches = True
                        elif sig_order_type == "sell_limit" and pending_type == mt5.ORDER_TYPE_SELL_LIMIT:
                            type_matches = True
                        elif sig_order_type == "buy_stop_limit" and pending_type == mt5.ORDER_TYPE_BUY_STOP_LIMIT:
                            type_matches = True
                        elif sig_order_type == "sell_stop_limit" and pending_type == mt5.ORDER_TYPE_SELL_STOP_LIMIT:
                            type_matches = True
                        
                        if not type_matches:
                            continue
                        
                        # Check if prices match (allow small tolerance based on symbol)
                        symbol_info = mt5.symbol_info(symbol)
                        if symbol_info:
                            tolerance = symbol_info.point * 10  # 10 points tolerance
                            if abs(pending_price - sig_entry) > tolerance:
                                continue
                        else:
                            # Fallback tolerance if can't get symbol info
                            if abs(pending_price - sig_entry) > 0.001:
                                continue
                        
                        # Check if volume matches (allow small tolerance)
                        if abs(pending_volume - sig_volume) > 0.001:
                            continue
                        
                        # Found a match
                        matching_pending = pending
                        break
                    
                    if not matching_pending:
                        print(f"           No matching pending order found for this liquidator order")
                        investor_orders_skipped_error += 1
                        stats["pending_orders_skipped_error"] += 1
                        continue
                    
                    stats["pending_orders_matched"] += 1
                    print(f"          ✅ Found matching pending order #{matching_pending['ticket']}")
                    
                    # =====================================================
                    # STEP 8: Calculate new exit price to achieve EXACT max risk
                    # =====================================================
                    # Get symbol info for price rounding
                    symbol_info = mt5.symbol_info(symbol)
                    if not symbol_info:
                        print(f"          ⚠️ Could not get symbol info for {symbol}")
                        investor_orders_skipped_error += 1
                        stats["pending_orders_skipped_error"] += 1
                        continue
                    
                    digits = symbol_info.digits
                    point = symbol_info.point
                    
                    # Calculate the price movement needed for target risk
                    # We need to find a new exit price where the SL profit = max_risk
                    # This is an iterative process since order_calc_profit is not linear in all cases
                    
                    # Start with a binary search to find the correct price
                    if is_buy:
                        # For BUY: exit price is lower than entry
                        min_exit = point * 10  # Minimum positive price
                        max_exit = sig_entry - point  # Just below entry
                        
                        # Ensure we don't go negative
                        if min_exit > max_exit:
                            min_exit = point * 10
                        
                        # Binary search for the exit price that gives exactly max_risk
                        for _ in range(50):  # Limit iterations
                            test_exit = (min_exit + max_exit) / 2
                            test_risk = mt5.order_calc_profit(calc_type, symbol, sig_volume, sig_entry, test_exit)
                            
                            if test_risk is None:
                                break
                            
                            test_risk_abs = abs(test_risk)
                            
                            if abs(test_risk_abs - max_risk) < 0.01:  # Within 1 cent
                                new_exit = test_exit
                                break
                            elif test_risk_abs > max_risk:
                                # Risk too high, move exit closer to entry (increase exit price)
                                min_exit = test_exit
                            else:
                                # Risk too low, move exit away from entry (decrease exit price)
                                max_exit = test_exit
                        else:
                            # If binary search didn't converge, use linear approximation
                            # Calculate approximate price movement needed
                            if current_risk > 0:
                                # Linear approximation: price_diff_needed = (max_risk / current_risk) * (entry - sig_exit)
                                current_price_diff = abs(sig_entry - sig_exit)
                                target_price_diff = (max_risk / current_risk) * current_price_diff
                                
                                if is_buy:
                                    new_exit = sig_entry - target_price_diff
                                else:
                                    new_exit = sig_entry + target_price_diff
                            else:
                                new_exit = sig_exit
                    
                    else:  # SELL order
                        # For SELL: exit price is higher than entry
                        min_exit = sig_entry + point  # Just above entry
                        max_exit = sig_entry + (10000 * point)  # Far above entry
                        
                        # Binary search for the exit price that gives exactly max_risk
                        for _ in range(50):  # Limit iterations
                            test_exit = (min_exit + max_exit) / 2
                            test_risk = mt5.order_calc_profit(calc_type, symbol, sig_volume, sig_entry, test_exit)
                            
                            if test_risk is None:
                                break
                            
                            test_risk_abs = abs(test_risk)
                            
                            if abs(test_risk_abs - max_risk) < 0.01:  # Within 1 cent
                                new_exit = test_exit
                                break
                            elif test_risk_abs > max_risk:
                                # Risk too high, move exit closer to entry (decrease exit price)
                                max_exit = test_exit
                            else:
                                # Risk too low, move exit away from entry (increase exit price)
                                min_exit = test_exit
                        else:
                            # If binary search didn't converge, use linear approximation
                            if current_risk > 0:
                                current_price_diff = abs(sig_exit - sig_entry)
                                target_price_diff = (max_risk / current_risk) * current_price_diff
                                
                                if is_buy:
                                    new_exit = sig_entry - target_price_diff
                                else:
                                    new_exit = sig_entry + target_price_diff
                            else:
                                new_exit = sig_exit
                    
                    # Round to symbol digits
                    new_exit = round(new_exit, digits)
                    
                    # Verify the new risk calculation
                    new_risk = mt5.order_calc_profit(calc_type, symbol, sig_volume, sig_entry, new_exit)
                    if new_risk is not None:
                        new_risk_abs = abs(new_risk)
                        print(f"          📊 Calculated adjustment:")
                        print(f"            • Current Exit: {sig_exit:.{digits}f}")
                        print(f"            • New Exit: {new_exit:.{digits}f}")
                        print(f"            • Verified New Risk: ${new_risk_abs:.2f}")
                        
                        # Check if we're close enough to target
                        risk_diff = abs(new_risk_abs - max_risk)
                        if risk_diff > 0.10:  # More than 10 cents off
                            print(f"          ⚠️ Calculated risk off by ${risk_diff:.2f} - may need manual adjustment")
                    else:
                        print(f"          ⚠️ Could not verify new risk calculation")
                    
                    # =====================================================
                    # STEP 9: Modify the pending order in MT5
                    # =====================================================
                    modify_request = {
                        "action": mt5.TRADE_ACTION_MODIFY,
                        "order": matching_pending['ticket'],
                        "price": matching_pending['price_open'],  # Keep original entry price
                        "sl": new_exit,
                        "tp": matching_pending['tp']  # Keep original TP
                    }
                    
                    result = mt5.order_send(modify_request)
                    
                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        print(f"          ✅ Order #{matching_pending['ticket']} adjusted successfully")
                        
                        # Track if we increased or decreased risk
                        if risk_difference < 0:
                            investor_orders_increased += 1
                            stats["orders_increased_risk"] += 1
                        else:
                            investor_orders_decreased += 1
                            stats["orders_decreased_risk"] += 1
                        
                        # Update the order in signals.json
                        location = sig_order.get('_location')
                        is_main = sig_order.get('_is_main', True)
                        signal_index = sig_order.get('_signal_index')
                        
                        # Prepare update data
                        update_data = {
                            'exit': new_exit,
                            'risk_in_usd': round(new_risk_abs if new_risk is not None else max_risk, 2),
                            'adjusted_to_max_risk': True,
                            'previous_exit': sig_exit,
                            'previous_risk': round(current_risk, 2),
                            'max_risk_target': max_risk,
                            'adjustment_direction': 'increased' if risk_difference < 0 else 'decreased'
                        }
                        
                        # Apply update based on location
                        if location == 'bid':
                            if is_main:
                                symbol_signals['bid_orders'][signal_index].update(update_data)
                            else:
                                symbol_signals['bid_orders'][signal_index]['order_counter'].update(update_data)
                        elif location == 'ask':
                            if is_main:
                                symbol_signals['ask_orders'][signal_index].update(update_data)
                            else:
                                symbol_signals['ask_orders'][signal_index]['order_counter'].update(update_data)
                        
                        investor_orders_adjusted += 1
                        stats["pending_orders_adjusted"] += 1
                        stats["adjustments_made"].append({
                            "investor": user_brokerid,
                            "symbol": symbol,
                            "ticket": matching_pending['ticket'],
                            "order_type": sig_order_type,
                            "entry": sig_entry,
                            "old_exit": sig_exit,
                            "new_exit": new_exit,
                            "old_risk": round(current_risk, 2),
                            "new_risk": round(new_risk_abs if new_risk is not None else max_risk, 2),
                            "adjustment": "increased" if risk_difference < 0 else "decreased"
                        })
                        changes_made_to_signals = True
                    else:
                        error_msg = result.comment if result else "No response"
                        retcode = result.retcode if result else "No retcode"
                        print(f"           Failed to adjust order: {error_msg} (Code: {retcode})")
                        
                        # Provide more helpful error messages
                        if retcode == 10013:
                            print(f"            ℹ️ This error (Invalid request) often means:")
                            print(f"               • The SL price is too close to current market price")
                            print(f"               • The SL price violates broker minimum distance rules")
                            print(f"               • Try adjusting by smaller increments")
                        stats["adjustment_failures"] += 1
        
        # =====================================================
        # STEP 10: Save updated signals.json if changes were made
        # =====================================================
        if changes_made_to_signals:
            try:
                with open(signals_path, 'w', encoding='utf-8') as f:
                    json.dump(signals_data, f, indent=4)
                print(f"\n  └─ ✅ Updated signals.json with adjusted orders")
            except Exception as e:
                print(f"\n  └─  Failed to save signals.json: {e}")
        
        # Investor summary
        print(f"\n  └─ 📊 Results for {user_brokerid}:")
        print(f"     • Max risk target: ${max_risk:.2f}")
        print(f"     • Liquidator orders found: {investor_liquidator_orders_found}")
        print(f"     • Matched with pending: {stats['pending_orders_matched']}")
        print(f"     • Adjusted to max: {investor_orders_adjusted}")
        if investor_orders_increased > 0:
            print(f"       └─ 🔼 Increased risk (was below max): {investor_orders_increased}")
        if investor_orders_decreased > 0:
            print(f"       └─ 🔽 Decreased risk (was above max): {investor_orders_decreased}")
        print(f"     • Adjustment failures: {stats['adjustment_failures']}")
        print(f"     • Skipped (errors): {investor_orders_skipped_error}")
    
    # =====================================================
    # FINAL SUMMARY
    # =====================================================
    print(f"\n{'='*10} 📊 MAX RISK ADJUSTMENT SUMMARY {'='*10}")
    print(f"   Investor ID: {stats['investor_id']}")
    print(f"   Investors with max config enabled: {stats['investors_with_max_config']}")
    print(f"   Investors skipped (config disabled): {stats['investors_skipped_due_to_settings']}")
    print(f"   Symbols analyzed: {stats['total_symbols_analyzed']}")
    print(f"   Symbols with liquidator orders: {stats['symbols_with_liquidator_orders']}")
    print(f"   Liquidator orders found: {stats['liquidator_orders_found']}")
    print(f"   Pending orders found: {stats['pending_orders_found']}")
    print(f"   Pending orders matched: {stats['pending_orders_matched']}")
    print(f"   Pending orders adjusted: {stats['pending_orders_adjusted']}")
    if stats['orders_increased_risk'] > 0:
        print(f"     └─ 🔼 Increased risk (was below max): {stats['orders_increased_risk']}")
    if stats['orders_decreased_risk'] > 0:
        print(f"     └─ 🔽 Decreased risk (was above max): {stats['orders_decreased_risk']}")
    print(f"   Adjustment failures: {stats['adjustment_failures']}")
    print(f"   Pending orders skipped (errors): {stats['pending_orders_skipped_error']}")
    
    if stats['adjustments_made']:
        print(f"\n   📋 Adjustments made (last 5):")
        for adj in stats['adjustments_made'][-5:]:
            arrow = "🔼" if adj['adjustment'] == "increased" else "🔽"
            print(f"     • {adj['investor']} - {adj['symbol']} #{adj['ticket']} {arrow}")
            print(f"       {adj['order_type']} @ {adj['entry']}")
            print(f"       Exit: {adj['old_exit']} → {adj['new_exit']}")
            print(f"       Risk: ${adj['old_risk']:.2f} → ${adj['new_risk']:.2f}")
        if len(stats['adjustments_made']) > 5:
            print(f"       ... and {len(stats['adjustments_made']) - 5} more")
    
    print(f"\n{'='*10} 🏁 MAX RISK ADJUSTMENT COMPLETE {'='*10}\n")
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
            print(f"  └─  No broker config found")
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
            print(f"  └─  Failed to read config: {e}")
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
                print(f"  └─  login failed: {error}")
                stats["positions_error"] += 1
                continue
            print(f"      ✅ Successfully logged into account")
        else:
            print(f"      ✅ Already logged into account")

        acc_info = mt5.account_info()
        if not acc_info:
            print(f"  └─  Failed to get account info")
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
                # risk_distance should always be positive
                if is_buy:
                    risk_distance = position.price_open - position.sl
                else:  # SELL
                    risk_distance = abs(position.sl - position.price_open)
                
                # Ensure risk_distance is positive
                if risk_distance <= 0:
                    print(f"       ⚠️  Invalid risk distance (SL at or beyond entry). Skipping.")
                    investor_positions_skipped += 1
                    stats["positions_skipped"] += 1
                    continue
                
                risk_points = risk_distance / symbol_info.point
                
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

                # Validate risk_usd is positive
                if risk_usd <= 0:
                    print(f"       ⚠️  Invalid risk value: ${risk_usd:.2f}. Skipping.")
                    investor_positions_skipped += 1
                    stats["positions_skipped"] += 1
                    continue

                # Calculate current profit in R multiples
                current_profit_usd = position.profit
                current_r_multiple = current_profit_usd / risk_usd

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
                # target_reward can be positive (move SL into profit) or zero (breakeven)
                if target_reward >= 0:
                    # Calculate target SL price
                    if is_buy:
                        # For BUY: entry + (risk_distance * target_reward)
                        # When target_reward = 0: SL at entry (breakeven)
                        # When target_reward = 0.5: SL at entry + 0.5R (partial profit protection)
                        target_sl_price = position.price_open + (risk_distance * target_reward)
                    else:  # SELL
                        # For SELL: entry - (risk_distance * target_reward)
                        # When target_reward = 0: SL at entry (breakeven)
                        # When target_reward = 0.5: SL at entry - 0.5R (partial profit protection)
                        target_sl_price = position.price_open - (risk_distance * target_reward)
                    
                    # Round to symbol digits
                    digits = symbol_info.digits
                    target_sl_price = round(target_sl_price, digits)
                    
                    print(f"       Current SL: {position.sl:.{digits}f}")
                    print(f"       Target SL:  {target_sl_price:.{digits}f} ({target_reward}R)")
                    
                    # Check if SL needs adjustment
                    # Calculate the distance from entry to current SL and target SL
                    if is_buy:
                        current_sl_distance = position.price_open - position.sl if position.sl != 0 else 0
                        target_sl_distance = position.price_open - target_sl_price
                        
                        # For BUY: A better SL is higher (closer to entry or above entry for profit)
                        # Check if target SL would actually improve the position
                        if target_sl_price <= position.sl:
                            print(f"       ℹ️  Target SL would not improve protection (not moving higher). Skipping.")
                            investor_positions_skipped += 1
                            stats["positions_skipped"] += 1
                            continue
                        
                    else:  # SELL
                        current_sl_distance = position.sl - position.price_open if position.sl != 0 else 0
                        target_sl_distance = target_sl_price - position.price_open
                        
                        # For SELL: A better SL is lower (closer to entry or below entry for profit)
                        # Check if target SL would actually improve the position
                        if target_sl_price >= position.sl:
                            print(f"       ℹ️  Target SL would not improve protection (not moving lower). Skipping.")
                            investor_positions_skipped += 1
                            stats["positions_skipped"] += 1
                            continue
                    
                    # Calculate threshold for adjustment (10% of target distance or 2 pips)
                    pip_threshold = max(abs(target_sl_distance) * 0.1, symbol_info.point * 20)
                    
                    # Check if SL needs adjustment (if current SL is significantly different from target)
                    if abs(current_sl_distance - target_sl_distance) > pip_threshold:
                        print(f"       📐 SL needs adjustment (distance difference: {abs(current_sl_distance - target_sl_distance):.{digits}f})")
                        
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
                            print(f"        Modification failed: {error_msg}")
                    else:
                        print(f"       ✅ SL already at optimal level (within threshold)")
                        investor_positions_skipped += 1
                        stats["positions_skipped"] += 1
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

def place_instant_stop_orders(inv_id=None):
    """
    Places buy/sell stop orders at the minimum allowed distance from market price.
    """
    print(f"\n{'='*10} ⚡ INSTANT STOP ORDERS {'='*10}")
    if inv_id:
        print(f" Processing single investor: {inv_id}")
    
    stats = {
        "investors_processed": 0,
        "investors_skipped": 0,
        "buy_stops_placed": 0,
        "sell_stops_placed": 0,
        "orders_failed": 0
    }
    
    # Process investors
    investors_to_process = [inv_id] if inv_id else usersdictionary.keys()
    
    for user_brokerid in investors_to_process:
        print(f"\n[{user_brokerid}] Processing...")
        
        # Get broker config
        broker_cfg = usersdictionary.get(user_brokerid)
        if not broker_cfg:
            print(f"  └─  No broker config")
            stats["investors_skipped"] += 1
            continue
        
        inv_root = Path(INV_PATH) / user_brokerid
        acc_mgmt_path = inv_root / "accountmanagement.json"
        
        if not acc_mgmt_path.exists():
            print(f"  └─ ⚠️ No accountmanagement.json")
            stats["investors_skipped"] += 1
            continue
        
        # Load config
        try:
            with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            symbols_dict = config.get("symbols_dictionary", {})
            all_symbols = []
            for category, symbols in symbols_dict.items():
                all_symbols.extend(symbols)
            
            selected_rr = config.get("selected_risk_reward", [2])
            risk_reward = float(selected_rr[0]) if selected_rr else 2
            
        except Exception as e:
            print(f"  └─  Error: {e}")
            stats["investors_skipped"] += 1
            continue
        
        # Check account
        login_id = int(broker_cfg['LOGIN_ID'])
        acc = mt5.account_info()
        
        if acc is None or acc.login != login_id:
            print(f"  └─  Wrong account")
            stats["investors_skipped"] += 1
            continue
        
        magic_number = int(user_brokerid) if user_brokerid.isdigit() else 0
        
        # Process each symbol
        for raw_symbol in all_symbols:
            print(f"\n    {raw_symbol}:")
            
            # Normalize symbol
            normalized_symbol = get_normalized_symbol(raw_symbol)
            
            # Get symbol info
            symbol_info = mt5.symbol_info(normalized_symbol)
            if not symbol_info:
                print(f"       Cannot get symbol info")
                stats["orders_failed"] += 1
                continue
            
            # Select symbol
            if not mt5.symbol_select(normalized_symbol, True):
                print(f"       Cannot select symbol")
                stats["orders_failed"] += 1
                continue
            
            # Get tick
            tick = mt5.symbol_info_tick(normalized_symbol)
            if not tick:
                print(f"       No tick data")
                stats["orders_failed"] += 1
                continue
            
            # Get minimum allowed distance
            stops_level = getattr(symbol_info, 'trade_stops_level', 0)
            if stops_level <= 0:
                stops_level = getattr(symbol_info, 'freeze_level', 100)
            
            # Use the minimum distance (but cap at reasonable values if needed)
            min_distance_points = stops_level
            point = symbol_info.point
            digits = symbol_info.digits
            
            # Calculate entry prices at minimum distance
            buy_stop_price = round(tick.ask + (min_distance_points * point), digits)
            sell_stop_price = round(tick.bid - (min_distance_points * point), digits)
            
            print(f"      Distance: {min_distance_points} points")
            print(f"      BUY STOP: {buy_stop_price}")
            print(f"      SELL STOP: {sell_stop_price}")
            
            # Delete existing orders for this symbol
            orders = mt5.orders_get(symbol=normalized_symbol)
            if orders:
                for order in orders:
                    if order.magic == magic_number:
                        mt5.order_send({
                            "action": mt5.TRADE_ACTION_REMOVE,
                            "order": order.ticket
                        })
            
            # Use minimum volume
            volume = symbol_info.volume_min
            
            # Calculate SL (15 points or minimum distance, whichever is larger)
            sl_distance = max(15, min_distance_points)
            
            # Place BUY STOP
            buy_sl = round(buy_stop_price - (sl_distance * point), digits)
            buy_tp = round(buy_stop_price + ((buy_stop_price - buy_sl) * risk_reward), digits)
            
            buy_request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": normalized_symbol,
                "volume": float(volume),
                "type": mt5.ORDER_TYPE_BUY_STOP,
                "price": float(buy_stop_price),
                "sl": float(buy_sl),
                "tp": float(buy_tp),
                "deviation": 20,
                "magic": magic_number,
                "comment": "INSTANT_BUY",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_RETURN,
            }
            
            result = mt5.order_send(buy_request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"      ✅ BUY STOP placed")
                stats["buy_stops_placed"] += 1
            else:
                print(f"       BUY STOP failed: {result.comment if result else 'Unknown'}")
                stats["orders_failed"] += 1
            
            # Place SELL STOP
            sell_sl = round(sell_stop_price + (sl_distance * point), digits)
            sell_tp = round(sell_stop_price - ((sell_sl - sell_stop_price) * risk_reward), digits)
            
            sell_request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": normalized_symbol,
                "volume": float(volume),
                "type": mt5.ORDER_TYPE_SELL_STOP,
                "price": float(sell_stop_price),
                "sl": float(sell_sl),
                "tp": float(sell_tp),
                "deviation": 20,
                "magic": magic_number,
                "comment": "INSTANT_SELL",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_RETURN,
            }
            
            result = mt5.order_send(sell_request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"      ✅ SELL STOP placed")
                stats["sell_stops_placed"] += 1
            else:
                print(f"       SELL STOP failed: {result.comment if result else 'Unknown'}")
                stats["orders_failed"] += 1
        
        stats["investors_processed"] += 1
    
    # Simple summary
    print(f"\n{'='*10} SUMMARY {'='*10}")
    print(f"BUY STOPs: {stats['buy_stops_placed']}")
    print(f"SELL STOPs: {stats['sell_stops_placed']}")
    print(f"Failed: {stats['orders_failed']}")
    
    return stats

def process_single_real_investor(inv_folder):
    """
    WORKER FUNCTION: Handles the entire pipeline for ONE investor.
    Sequential execution without console output.
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
    
    broker_cfg = usersdictionary.get(inv_id)
    if not broker_cfg:
        return account_stats

    import random
    import time
    time.sleep(random.uniform(0.1, 2.0)) 
    
    login_id = int(broker_cfg['LOGIN_ID'])
    mt5_path = broker_cfg["TERMINAL_PATH"]

    try:
        if not mt5.initialize(path=mt5_path, timeout=180000):
            return account_stats

        acc = mt5.account_info()
        if acc is None or acc.login != login_id:
            if not mt5.login(login_id, password=broker_cfg["PASSWORD"], server=broker_cfg["SERVER"]):
                mt5.shutdown()
                return account_stats
            
        # STEP 0: SYMBOL AUTHORIZATION FILTER
        martingale(inv_id=inv_id)
        
        
        mt5.shutdown()
        account_stats["success"] = True
        
    except Exception as e:
        try:
            mt5.shutdown()
        except:
            pass
    
    return account_stats

def process_single_investor(inv_folder):
    """
    WORKER FUNCTION: Handles the entire pipeline for ONE investor.
    Sequential execution without console output.
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
    
    broker_cfg = usersdictionary.get(inv_id)
    if not broker_cfg:
        return account_stats

    import random
    import time
    time.sleep(random.uniform(0.1, 2.0)) 
    
    login_id = int(broker_cfg['LOGIN_ID'])
    mt5_path = broker_cfg["TERMINAL_PATH"]

    try:
        if not mt5.initialize(path=mt5_path, timeout=180000):
            return account_stats

        acc = mt5.account_info()
        if acc is None or acc.login != login_id:
            if not mt5.login(login_id, password=broker_cfg["PASSWORD"], server=broker_cfg["SERVER"]):
                mt5.shutdown()
                return account_stats
            
        #timeframe_countdown(inv_id=inv_id)
        move_verified_investors()
        update_verified_investors_file()

        get_requirements(inv_id=inv_id)

        # STEP 0: SYMBOL AUTHORIZATION FILTER
        filter_stats = filter_unauthorized_symbols(inv_id=inv_id)
        account_stats["symbols_filtered"] = filter_stats.get("symbols_filtered", 0)
        account_stats["orders_filtered"] = filter_stats.get("orders_filtered", 0)

        # STEP 1: PRICE COLLECTION
        price_stats = symbols_dynamic_grid_prices(inv_id=inv_id)
        account_stats["price_collection_stats"] = price_stats
        account_stats["symbols_processed"] = price_stats.get("total_symbols", 0)
        account_stats["symbols_successful"] = price_stats.get("successful_symbols", 0)
        
        # STEP 1.5: FETCH 15-MINUTE CANDLES
        candle_stats = fetch_15m_candles(inv_id=inv_id)
        account_stats["candle_fetch_stats"] = candle_stats
        account_stats["current_candle_forming"] = candle_stats.get("current_candle_forming", False)
        

        # STEP 2: ORDER PLACEMENT
        manage_single_position_and_pending(inv_id=inv_id)
        martingale(inv_id=inv_id)
        order_stats = place_signals_orders(inv_id=inv_id)
        manage_single_position_and_pending(inv_id=inv_id)
        apply_dynamic_breakeven(inv_id=inv_id)
        account_stats["order_placement_stats"] = order_stats
        account_stats["orders_placed"] = order_stats.get("orders_placed", 0)
        account_stats["counter_orders_placed"] = order_stats.get("counter_orders_placed", 0)
        account_stats["total_active_orders"] = order_stats.get("total_active_orders", 0)

        adjust_pending_orders_to_max_risk(inv_id=inv_id)

        # STEP 4: RISK AUDIT
        #audit_stats = check_pending_orders_risk(inv_id=inv_id)
        #account_stats["risk_audit_stats"] = audit_stats
        #account_stats["orders_removed"] = audit_stats.get("orders_removed", 0)

        correction_stats = orders_risk_correction(inv_id=inv_id)
        account_stats["risk_correction_stats"] = correction_stats
        account_stats["orders_adjusted"] = correction_stats.get("orders_adjusted", 0)

        check_and_record_authorized_actions(inv_id=inv_id)
        update_investor_info(inv_id=inv_id)
        update_verified_investors_file()
        
        mt5.shutdown()
        account_stats["success"] = True
        
    except Exception as e:
        try:
            mt5.shutdown()
        except:
            pass
    
    return account_stats

def place_orders_parallel():
    """
    ORCHESTRATOR: Spawns multiple processes to handle investors in parallel.
    Uses the account initialization logic.
    Checks harvcore setting in accountmanagement.json before processing.
    """
    inv_base_path = Path(INV_PATH)
    investor_folders = [f for f in inv_base_path.iterdir() if f.is_dir()]
    
    if not investor_folders:
        print(" └─ 🔘 No investor directories found.")
        return False

    print(f" 📋 Found {len(investor_folders)} investors to process")
    
    # Filter investors based on harvcore setting
    eligible_investors = []
    skipped_investors = []
    
    for inv_folder in investor_folders:
        inv_id = inv_folder.name
        acc_mgmt_path = inv_folder / "accountmanagement.json"
        
        if not acc_mgmt_path.exists():
            print(f" ⚠️  {inv_id}: No accountmanagement.json found. Skipping.")
            skipped_investors.append(inv_id)
            continue
            
        try:
            with open(acc_mgmt_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            settings = config.get("settings", {})
            harvcore_enabled = settings.get("harvester", False)
            
            if harvcore_enabled:
                eligible_investors.append(inv_folder)
                print(f" ✅ {inv_id}: harvcore = TRUE - Will process")
            else:
                skipped_investors.append(inv_id)
                print(f" ⏭️  {inv_id}: harvcore = FALSE - Skipping")
                
        except Exception as e:
            print(f" No {inv_id}: Error reading accountmanagement.json: {e}. Skipping.")
            skipped_investors.append(inv_id)
            continue
    
    if not eligible_investors:
        print(f"\n └─ 🔘 No eligible investors found (harvcore = true).")
        if skipped_investors:
            print(f"    Skipped {len(skipped_investors)} investors due to harvcore = false or config errors.")
        return False
    
    print(f"\n 📊 Processing {len(eligible_investors)} out of {len(investor_folders)} investors")
    if skipped_investors:
        print(f"    Skipped: {', '.join(skipped_investors[:5])}{'...' if len(skipped_investors) > 5 else ''}")
    
    print(f" 🔧 Creating pool with {len(eligible_investors)} processes...")
    
    # Create a pool based on the number of eligible accounts
    with mp.Pool(processes=len(eligible_investors)) as pool:
        results = pool.map(process_single_investor, eligible_investors)
    
    # Optional: Print summary of results
    successful = sum(1 for r in results if r.get("success", False))
    print(f"\n{'='*10} 📊 PARALLEL PROCESSING SUMMARY {'='*10}")
    print(f"   Total investors processed: {len(eligible_investors)}")
    print(f"   Successful: {successful}")
    print(f"   Failed: {len(eligible_investors) - successful}")
    print(f"   Skipped (harvcore=false/config error): {len(skipped_investors)}")
    print(f"{'='*10} 🏁 PARALLEL PROCESSING COMPLETE {'='*10}\n")
    #place_orders_parallel()
    return True

if __name__ == "__main__":
   place_orders_parallel()