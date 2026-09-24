import connectwithinfinitydb as db
from connectwithinfinitydb import initialize_browser
import json
import os
from datetime import datetime
import time
import MetaTrader5 as mt5
import multiprocessing as mp
from pathlib import Path
from webdriver_manager.chrome import ChromeDriverManager
import shutil
from datetime import datetime, date
from decimal import Decimal
import json
import psutil
import re
from typing import Any, Dict, List, Union
import socket
import sys
import random
import time
import os
import sys
import Harvhub


DEFAULT_MT5_PATH = r"C:\xampp\htdocs\harvcore\mt5\MetaTrader 5"
MT5_DESTINATION_PATH = r"C:\xampp\htdocs\harvcore\mt5"
INV_PATH = r"C:\xampp\htdocs\harvcore\harvox\invharv\usersdata\investors"
DEFAULT_PATH = r"C:\xampp\htdocs\harvcore\harvox"
DEFAULT_ACCOUNTMANAGEMENT = r"C:\xampp\htdocs\harvcore\harvox\harvcore_accountmanagement.json"
SUSPENDED_ACCOUNTS = r"C:\xampp\htdocs\harvcore\harvox\invharv\suspended_accounts.json"
FETCHED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\invharv\fetched_investors.json"
UPDATED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\invharv\updated_investors.json"

INVHARV_FETCHED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\invharv\fetched_investors.json"
INVHARV_UPDATED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\invharv\updated_investors.json"
HARVHUB_FETCHED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\harvhub\fetched_harvhub_investors.json"
HARVHUB_UPDATED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\harvhub\updated_harvhub_investors.json"
ALL_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\all_investors.json"
ALL_FETCHED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\fetched_investors.json"
ALL_INVESTORS_BACKUP = r"C:\xampp\htdocs\harvcore\harvox\backup_fetched_investors.json"
ALL_UPDATED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\updated_investors.json"

def delete_investor_files():
    """
    Delete all files in DEFAULT_PATH that contain 'investor' or 'investors' in their filename.
    Recursively searches through all subfolders. Only deletes files, not folders.
    Case-insensitive search.
    
    This function:
    1. Recursively scans DEFAULT_PATH and all subdirectories
    2. Checks each filename (case-insensitive) for 'investor' or 'investors'
    3. Deletes matching files
    4. Provides detailed logging and statistics
    
    Returns:
        dict: Statistics about the deletion process
    """
    print("\n" + "="*70)
    print(f"  DELETE INVESTOR FILES (RECURSIVE)")
    print("="*70)
    print(f"  Start Time  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-"*70)
    print(f"  Target Path : {DEFAULT_PATH}")
    print(f"  Pattern     : *investor* or *investors* (case-insensitive)")
    print(f"  Mode        : RECURSIVE (searches all subfolders)")
    print("="*70)
    
    stats = {
        "processing_success": False,
        "path": DEFAULT_PATH,
        "path_exists": False,
        "files_scanned": 0,
        "files_deleted": 0,
        "files_skipped": 0,
        "folders_scanned": 0,
        "deleted_files": [],
        "skipped_files": [],
        "folders_with_deletions": [],
        "errors": [],
        "timestamp": datetime.now().isoformat()
    }
    
    # Check if path exists
    if not os.path.exists(DEFAULT_PATH):
        error_msg = f"Path does not exist: {DEFAULT_PATH}"
        print(f"  ❌ {error_msg}")
        stats["errors"].append(error_msg)
        stats["processing_success"] = False
        return stats
    
    stats["path_exists"] = True
    print(f"  ✅ Path exists: {DEFAULT_PATH}")
    print(f"\n  🔍 Starting recursive scan...")
    print("-"*70)
    
    try:
        # Pattern to match 'investor' or 'investors' (case-insensitive)
        pattern = re.compile(r'investor(s)?', re.IGNORECASE)
        
        # Walk through all directories recursively
        for root, dirs, files in os.walk(DEFAULT_PATH):
            # Track the current folder
            current_folder = os.path.basename(root)
            stats["folders_scanned"] += 1
            
            # Show current folder being processed (only if it has investor files)
            folder_has_matches = False
            
            # Process each file in the current folder
            for file in files:
                stats["files_scanned"] += 1
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, DEFAULT_PATH)
                
                # Check if filename contains 'investor' or 'investors'
                if pattern.search(file):
                    try:
                        # Delete the file
                        os.remove(file_path)
                        stats["files_deleted"] += 1
                        stats["deleted_files"].append(relative_path)
                        
                        # Track which folders had deletions
                        if root not in stats["folders_with_deletions"]:
                            stats["folders_with_deletions"].append(root)
                            folder_has_matches = True
                            # Print folder header when first deletion found
                            print(f"\n  📁 Processing: {relative_path.split(os.sep)[0] if os.sep in relative_path else '.'}")
                            print(f"     Path: {root}")
                        
                        print(f"     🗑️  DELETED: {file}")
                        
                    except Exception as e:
                        error_msg = f"Error deleting {relative_path}: {str(e)}"
                        print(f"     ❌ {error_msg}")
                        stats["errors"].append(error_msg)
                        stats["files_skipped"] += 1
                        stats["skipped_files"].append({
                            "name": relative_path,
                            "reason": f"Error: {str(e)}"
                        })
                else:
                    # File doesn't match pattern - only log if verbose mode is needed
                    # Uncomment the line below for very verbose output
                    # print(f"     ℹ️  Skipped (no match): {file}")
                    stats["files_skipped"] += 1
                    stats["skipped_files"].append({
                        "name": relative_path,
                        "reason": "No match"
                    })
            
            # Print summary for this folder if it had matches
            if folder_has_matches:
                print(f"     ✅ Folder processed: {len([f for f in files if pattern.search(f)])} files deleted")
        
        stats["processing_success"] = True
        
        # ============================================================
        # FINAL SUMMARY
        # ============================================================
        print("\n" + "="*70)
        print(f"  DELETION SUMMARY")
        print("="*70)
        print(f"\n  📂 Base Path: {DEFAULT_PATH}")
        print(f"  📁 Folders scanned: {stats['folders_scanned']}")
        print(f"  📄 Total files scanned: {stats['files_scanned']}")
        print(f"  🗑️  Files deleted: {stats['files_deleted']}")
        print(f"  ℹ️  Files skipped: {stats['files_skipped']}")
        print(f"  📁 Folders with deletions: {len(stats['folders_with_deletions'])}")
        
        if stats['files_deleted'] > 0:
            print(f"\n  📋 Deleted files ({stats['files_deleted']}):")
            # Group deleted files by folder for better readability
            deleted_by_folder = {}
            for filepath in stats['deleted_files']:
                folder = os.path.dirname(filepath) if os.path.dirname(filepath) else "."
                if folder not in deleted_by_folder:
                    deleted_by_folder[folder] = []
                deleted_by_folder[folder].append(os.path.basename(filepath))
            
            for folder, files in sorted(deleted_by_folder.items()):
                print(f"\n     📁 {folder}:")
                for file in files:
                    print(f"        - {file}")
        
        if stats['errors']:
            print(f"\n  ❌ Errors ({len(stats['errors'])}):")
            for error in stats['errors']:
                print(f"     - {error}")
        
        print(f"\n  ✅ Status : {'SUCCESS' if stats['processing_success'] else 'FAILED'}")
        print(f"  🕐 Time   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*70)
        
        return stats
        
    except Exception as e:
        print(f"\n{'='*70}")
        print(f"   CRITICAL ERROR")
        print(f"{'='*70}")
        print(f"  Error Type : {type(e).__name__}")
        print(f"  Message    : {str(e)}")
        print(f"{'='*70}")
        
        import traceback
        print(f"\n  📜 Full Traceback:")
        traceback.print_exc()
        
        stats["processing_success"] = False
        stats["errors"].append(f"Critical error: {str(e)}")
        return stats
   
def work_only_in_specific_timerange():
    """
    Function: Checks if current time falls within any of the allowed work time ranges
    from default_accountmanagement.json (global setting).
    Function will ONLY work during specified time windows.
    Does NOT need MT5 connection - just checks time configuration.
    
    Looks for 'working_hours' key at the root level of the JSON.
    
    If 'from' or 'to' values parse to 0 (e.g., "0", "0.00", "0:00 am", "00:00"), 
    it overrides all restrictions and assumes work is always allowed.
    
    Features:
    - Automatic backup of working hours data to workinghours_backup.txt
    - Self-repair: If JSON is corrupted, restores from backup
    - Maintains multiple backup versions
    
    Returns:
        dict: Statistics about the time range check including whether function should work
    """
    global restricted_timerange_alert
    
    from datetime import datetime
    from pathlib import Path
    import json
    import shutil
    
    print(f"\n{'='*10} ⏰ WORK TIME CHECK (Only work during specified hours) {'='*10}")
    
    # --- DISPLAY JSON PATH ---
    print(f"\n   📂 Looking for config at: {DEFAULT_ACCOUNTMANAGEMENT}")
    
    # --- TIME CHECK ---
    current_time = datetime.now()
    
    # --- DATA INITIALIZATION ---
    stats = {
        "processing_success": False,
        "current_time": current_time.strftime('%I:%M:%S %p'),
        "should_work": False,
        "has_time_restriction": False,
        "time_windows": [],
        "errors": [],
        "config_path_checked": str(DEFAULT_ACCOUNTMANAGEMENT),
        "json_structure_found": None,
        "backup_restored": False,
        "backup_created": False
    }
    
    # Define backup file path (same directory as config)
    config_path = Path(DEFAULT_ACCOUNTMANAGEMENT)
    backup_path = config_path.parent / "workinghours_backup.txt"
    temp_backup_path = config_path.parent / "workinghours_backup_temp.txt"
    
    # --- FUNCTION TO LOAD JSON WITH ERROR HANDLING ---
    def load_json_config(file_path):
        """Attempt to load JSON config, return (config_data, error)"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f), None
        except json.JSONDecodeError as e:
            return None, f"JSON decode error: {e}"
        except Exception as e:
            return None, f"File read error: {e}"
    
    # --- FUNCTION TO RESTORE FROM BACKUP ---
    def restore_from_backup():
        """Restore config from backup file. Returns (success, error_message)"""
        try:
            if not backup_path.exists():
                return False, f"Backup file not found: {backup_path}"
            
            print(f"   🔧 Attempting to restore from backup: {backup_path}")
            
            # Read backup data
            with open(backup_path, 'r', encoding='utf-8') as f:
                backup_data = f.read()
            
            # Verify backup contains valid JSON
            try:
                backup_json = json.loads(backup_data)
            except json.JSONDecodeError as e:
                return False, f"Backup file contains invalid JSON: {e}"
            
            # Write backup data to config file
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(backup_data)
            
            print(f"   ✅ Config restored from backup successfully")
            return True, None
            
        except Exception as e:
            return False, f"Failed to restore from backup: {e}"
    
    # --- FUNCTION TO CREATE BACKUP ---
    def create_backup(config_data):
        """Create backup of current config. Returns (success, error_message)"""
        try:
            # Ensure backup directory exists
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Convert to JSON string with proper formatting
            backup_content = json.dumps(config_data, indent=4, ensure_ascii=False)
            
            # Check if backup already exists
            if backup_path.exists():
                # Create temporary backup first (for safety)
                shutil.copy2(backup_path, temp_backup_path)
            
            # Write new backup
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(backup_content)
            
            # Remove temp backup if exists
            if temp_backup_path.exists():
                temp_backup_path.unlink()
            
            print(f"   ✅ Backup created: {backup_path}")
            return True, None
            
        except Exception as e:
            # Restore temp backup if it exists
            if temp_backup_path.exists():
                shutil.copy2(temp_backup_path, backup_path)
                temp_backup_path.unlink()
            return False, f"Failed to create backup: {e}"
    
    # --- LOAD CONFIGURATION WITH AUTO-REPAIR ---
    default_config = None
    
    # Try to load config file
    if not config_path.exists():
        print(f"    Config file not found: {DEFAULT_ACCOUNTMANAGEMENT}")
        stats["errors"].append(f"Config file not found: {DEFAULT_ACCOUNTMANAGEMENT}")
        
        # Try to restore from backup
        restored, error = restore_from_backup()
        if restored:
            # Reload the restored config
            default_config, load_error = load_json_config(config_path)
            if default_config:
                stats["backup_restored"] = True
                stats["json_structure_found"] = "RESTORED_FROM_BACKUP"
                print(f"   ✅ Config restored from backup successfully")
            else:
                stats["errors"].append(f"Failed to load restored config: {load_error}")
                stats["processing_success"] = True
                stats["should_work"] = True
                stats["json_structure_found"] = "RESTORE_FAILED"
                return stats
        else:
            stats["errors"].append(f"Backup restoration failed: {error}")
            stats["processing_success"] = True
            stats["should_work"] = True
            stats["json_structure_found"] = "FILE_AND_BACKUP_NOT_FOUND"
            return stats
    else:
        # Config exists, try to load it
        default_config, load_error = load_json_config(config_path)
        
        if default_config is None:
            # Config exists but is corrupted
            print(f"    Config file corrupted: {load_error}")
            stats["errors"].append(f"Config file corrupted: {load_error}")
            
            # Try to restore from backup
            restored, restore_error = restore_from_backup()
            if restored:
                # Reload the restored config
                default_config, reload_error = load_json_config(config_path)
                if default_config:
                    stats["backup_restored"] = True
                    stats["json_structure_found"] = "RESTORED_FROM_BACKUP"
                    print(f"   ✅ Config restored from backup successfully")
                else:
                    stats["errors"].append(f"Failed to load restored config: {reload_error}")
                    stats["processing_success"] = True
                    stats["should_work"] = True
                    stats["json_structure_found"] = "RESTORE_LOAD_FAILED"
                    return stats
            else:
                stats["errors"].append(f"Backup restoration failed: {restore_error}")
                stats["processing_success"] = True
                stats["should_work"] = True
                stats["json_structure_found"] = "CORRUPTED_AND_NO_BACKUP"
                return stats
    
    # --- CREATE BACKUP IF CONFIG LOADED SUCCESSFULLY ---
    if default_config is not None:
        backup_success, backup_error = create_backup(default_config)
        if backup_success:
            stats["backup_created"] = True
        else:
            stats["errors"].append(f"Backup creation warning: {backup_error}")
            print(f"   ⚠️ Backup creation failed: {backup_error}")
    
    print(f"   ✅ Config file loaded successfully")
    
    # --- DISPLAY JSON STRUCTURE FOUND ---
    print(f"\n   📋 JSON Structure Analysis:")
    print(f"   {'-'*40}")
    
    # Check root level keys
    root_keys = list(default_config.keys())
    
    # Look for 'working_hours' at root level
    time_ranges = []
    has_time_restriction = False
    time_windows_list = []
    is_within_any_window = False
    matched_window = None
    zero_override_triggered = False
    
    if "working_hours" in default_config:
        print(f"   ✅ Found 'working_hours' key at root level")
        stats["json_structure_found"] = "ROOT_LEVEL_WORKING_HOURS"
        time_ranges = default_config.get("working_hours", [])
        
        if isinstance(time_ranges, dict):
            time_ranges = [time_ranges]
        
        print(f"   📊 Found {len(time_ranges) if time_ranges else 0} time window(s) in working_hours")
    else:
        print(f"    No 'working_hours' key found at root level")
        stats["json_structure_found"] = "NO_WORKING_HOURS_KEY"
        time_ranges = []
    
    # Parse time strings (e.g., "12:00 am" or "12:30 pm" or "21:00" or "0:00 am")
    def parse_time_string(time_str):
        # Handle edge cases like raw numbers or floats passed as strings/ints
        time_str_clean = str(time_str).lower().strip().replace(" ", "")
        
        # Check for explicit override ONLY if it's literally "0", "0.00", "0.0", "00:00"
        # NOT "12:00 am" which should be treated as midnight (0:00) but NOT an override
        # We need to detect if it's ACTUALLY a zero value, not "12:00 am" converted
        
        # First check if it's a literal zero string (without am/pm)
        if time_str_clean in ["0", "0.00", "0.0", "00:00"]:
            return 0, 0, True  # Return True for override flag
            
        is_pm = "pm" in time_str_clean
        is_am = "am" in time_str_clean
        
        clean_time = time_str_clean.replace("pm", "").replace("am", "")
        
        if ":" in clean_time:
            parts = clean_time.split(":")
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
        else:
            try:
                hour = int(clean_time)
            except ValueError:
                hour = int(float(clean_time))
            minute = 0
        
        # Handle 12-hour to 24-hour conversion
        if is_pm and hour != 12:
            hour += 12
        elif is_am and hour == 12:
            hour = 0
        
        # Check if this is a zero time (midnight) but NOT an override
        # Only return override=True if it's literally "0" without am/pm
        is_override = False
        
        return hour, minute, is_override
    
    # Convert to 12-hour format for display
    def to_12hr(hour, minute):
        period = "AM" if hour < 12 else "PM"
        hour_12 = hour % 12
        if hour_12 == 0:
            hour_12 = 12
        return f"{hour_12}:{minute:02d} {period}"
    
    try:
        if time_ranges and len(time_ranges) > 0:
            print(f"\n   🎯 Processing {len(time_ranges)} time window(s)")
            
            # FIRST: Check for explicit override - only literal "0", "0.00", etc.
            for idx, time_range in enumerate(time_ranges):
                if "from" in time_range and "to" in time_range:
                    # Check if the raw string is "0", "0.00", "0.0", "00:00" WITHOUT am/pm
                    from_raw = str(time_range["from"]).lower().strip().replace(" ", "")
                    to_raw = str(time_range["to"]).lower().strip().replace(" ", "")
                    
                    # Only trigger override if it's literally "0" or "0.00" without am/pm
                    if from_raw in ["0", "0.00", "0.0", "00:00"] or to_raw in ["0", "0.00", "0.0", "00:00"]:
                        print(f"   ⚠️ Window {idx + 1} has explicit '0' or '0.00' value ({time_range['from']} -> {time_range['to']}).")
                        print(f"   👉 Always Work Rule Activated! Restrictions completely bypassed.")
                        zero_override_triggered = True
                        break
            
            # SECOND: Process active time windows ONLY if no zero rule was triggered
            if not zero_override_triggered:
                current_time_minutes = current_time.hour * 60 + current_time.minute
                
                for idx, time_range in enumerate(time_ranges):
                    if "from" in time_range and "to" in time_range:
                        try:
                            # Parse start time - ignore override flag
                            start_hour, start_minute, _ = parse_time_string(time_range["from"])
                            # Parse end time - ignore override flag
                            end_hour, end_minute, _ = parse_time_string(time_range["to"])
                            
                            # Calculate minutes
                            start_minutes = start_hour * 60 + start_minute
                            end_minutes = end_hour * 60 + end_minute
                            
                            # Check if window crosses midnight
                            crosses_midnight = end_minutes < start_minutes
                            
                            if crosses_midnight:
                                is_in_window = (current_time_minutes >= start_minutes or 
                                                current_time_minutes <= end_minutes)
                            else:
                                is_in_window = start_minutes <= current_time_minutes <= end_minutes
                            
                            # Format for display
                            start_12hr = to_12hr(start_hour, start_minute)
                            end_12hr = to_12hr(end_hour, end_minute)
                            
                            window_info = {
                                'index': idx + 1,
                                'from': time_range['from'],
                                'to': time_range['to'],
                                'from_24hr': f"{start_hour:02d}:{start_minute:02d}",
                                'to_24hr': f"{end_hour:02d}:{end_minute:02d}",
                                'from_12hr': start_12hr,
                                'to_12hr': end_12hr,
                                'is_within': is_in_window
                            }
                            
                            time_windows_list.append(window_info)
                            has_time_restriction = True
                            
                            if is_in_window:
                                is_within_any_window = True
                                matched_window = window_info
                                print(f"   ✅ Window {idx + 1}: {time_range['from']} - {time_range['to']}  WITHIN")
                            else:
                                print(f"    Window {idx + 1}: {time_range['from']} - {time_range['to']}  OUTSIDE")
                                
                        except Exception as e:
                            stats["errors"].append(f"Failed to parse time range {idx}: {e}")
                            print(f"   ⚠️ Failed to parse window {idx + 1}: {e}")
                
                if has_time_restriction:
                    print(f"   📋 System evaluated {len(time_windows_list)} filtering time window(s)")
                    if is_within_any_window and matched_window:
                        print(f"\n   🕐 Current time {current_time.strftime('%I:%M:%S %p')} is WITHIN window {matched_window['index']}: {matched_window['from']} - {matched_window['to']}")
                    else:
                        print(f"\n   🕐 Current time {current_time.strftime('%I:%M:%S %p')} is NOT within ANY work window")
            else:
                # Force settings to wide open execution state
                has_time_restriction = False
                is_within_any_window = True
                time_windows_list = []
                matched_window = None
                print(f"   🚫 Zero override active - all time restrictions bypassed")
                
    except Exception as e:
        stats["errors"].append(f"Error processing time ranges: {e}")
        print(f"    Error processing time ranges: {e}")
    
    # If no time restriction defined or zero override caught = work always allowed
    if not has_time_restriction and not zero_override_triggered:
        is_within_any_window = True
        print(f"   ℹ️ No active time restriction - work always allowed")
    elif not has_time_restriction and zero_override_triggered:
        print(f"   ℹ️ Zero override active - work always allowed")
    
    # Display current time
    print(f"\n   🕐 Current time: {current_time.strftime('%I:%M:%S %p')}")
    
    # Final decision
    if is_within_any_window:
        print(f"   🟢 WITHIN work parameters - Function CAN work")
        stats["should_work"] = True
    else:
        print(f"   🔴 OUTSIDE work parameters - Function CANNOT work")
        stats["should_work"] = False
    
    stats["has_time_restriction"] = has_time_restriction
    stats["time_windows"] = time_windows_list
    stats["matched_window"] = matched_window
    stats["processing_success"] = True

    # --- SET GLOBAL ALERT FLAG ---
    restricted_timerange_alert = {
        'is_triggered': is_within_any_window,
        'timestamp': current_time.strftime('%I:%M:%S %p'),
        'time_windows': time_windows_list,
        'matched_window': matched_window,
        'should_work': is_within_any_window
    }

    # --- FINAL SUMMARY ---
    print(f"\n{'='*10} 📊 SUMMARY {'='*10}")
    print(f"   Config path: {DEFAULT_ACCOUNTMANAGEMENT}")
    print(f"   Backup path: {backup_path}")
    print(f"   JSON structure: {stats['json_structure_found']}")
    print(f"   Backup restored: {stats.get('backup_restored', False)}")
    print(f"   Backup created: {stats.get('backup_created', False)}")
    print(f"   Has time restriction: {has_time_restriction}")
    if has_time_restriction:
        print(f"   Total active windows: {len(time_windows_list)}")
        print(f"   Within active window: {is_within_any_window}")
        if matched_window:
            print(f"   Matched window: {matched_window['from']} - {matched_window['to']}")
    else:
        if zero_override_triggered:
            print(f"   Within work window: {is_within_any_window} (Always allowed due to '0/0.00' override)")
        else:
            print(f"   Within work window: {is_within_any_window} (Always allowed - no working_hours configured)")
    print(f"   Function should work: {is_within_any_window}")
    
    # --- DISPLAY BACKUP INFORMATION ---
    if stats.get('backup_created', False):
        print(f"   💾 Backup file: {backup_path}")
        try:
            if backup_path.exists():
                size = backup_path.stat().st_size
                print(f"   📊 Backup size: {size:,} bytes")
        except:
            pass
    
    print(f"{'='*10} 🏁 COMPLETE {'='*10}\n")
    
    return stats

def restore_missing_fields():
    """
    Heal missing fields across JSON files using hierarchical field-by-field merging.
    
    Priority order:
    1. INVHARV_UPDATED_INVESTORS and HARVHUB_UPDATED_INVESTORS (highest priority)
    2. INVHARV_FETCHED_INVESTORS and HARVHUB_FETCHED_INVESTORS
    3. ALL_UPDATED_INVESTORS
    4. ALL_FETCHED_INVESTORS (lowest priority)
    
    Rules:
    - Individual files (invharv/harvhub) ONLY heal their own users
    - ALL files can receive from individual files
    - Individual files can receive from ALL files if they're missing fields
    - Field-by-field merging (not whole record replacement)
    - Files heal each other if individual files are empty
    """
    
    print("\n" + "="*70)
    print(f"  HEALING MISSING FIELDS (FIELD-BY-FIELD MERGE)")
    print("="*70)
    print(f"  Start Time  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-"*70)
    
    def safe_read_json(file_path, default={}):
        """Safely read JSON file with error handling"""
        if not os.path.exists(file_path):
            print(f"    ⚠️ File not found: {file_path}")
            return default
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            print(f"    ❌ JSON decode error in {file_path}: {str(e)}")
            return default
        except PermissionError as e:
            print(f"    ⚠️ Permission denied reading {file_path}")
            return default
        except Exception as e:
            print(f"    ❌ Error reading {file_path}: {str(e)}")
            return default
    
    def safe_write_json(file_path, data):
        """Safely write JSON file with permission handling"""
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except PermissionError as e:
            print(f"    ⚠️ Permission denied writing {file_path}")
            # Try to delete and retry
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    return True
            except:
                pass
            return False
        except Exception as e:
            print(f"    ❌ Error writing {file_path}: {str(e)}")
            return False
    
    def merge_fields(source_record, target_record):
        """
        Merge fields from source to target where target is missing fields.
        Returns: (merged_record, fields_added)
        """
        if not source_record or not target_record:
            return target_record, 0
        
        merged = dict(target_record)  # Start with target
        fields_added = 0
        
        for key, value in source_record.items():
            # Skip 'id' field as it's the key
            if key == 'id':
                continue
            
            # Only add if target doesn't have this field OR target has it as None/null
            if key not in merged or merged[key] is None:
                merged[key] = value
                fields_added += 1
        
        return merged, fields_added
    
    def get_record_id(record):
        """Extract record ID from record dict"""
        if isinstance(record, dict):
            return str(record.get('id', ''))
        return None
    
    def merge_file_pair(source_data, target_data, source_name, target_name, skip_missing_ids=False):
        """
        Merge fields from source to target for matching IDs.
        If skip_missing_ids=True, only merge for IDs that exist in target.
        """
        if not source_data or not target_data:
            return target_data, 0, 0, 0
        
        merged_target = dict(target_data)
        total_records_healed = 0
        total_fields_added = 0
        total_records_skipped = 0
        
        for record_id, source_record in source_data.items():
            if record_id in merged_target:
                # Merge fields from source to target
                target_record = merged_target[record_id]
                merged_record, fields_added = merge_fields(source_record, target_record)
                
                if fields_added > 0:
                    merged_target[record_id] = merged_record
                    total_records_healed += 1
                    total_fields_added += fields_added
                    print(f"      ✅ Healed record {record_id}: added {fields_added} field(s)")
            else:
                if not skip_missing_ids:
                    # If target doesn't have this ID, add the whole record
                    merged_target[record_id] = source_record
                    total_records_healed += 1
                    print(f"      ➕ Added new record {record_id} from {source_name}")
                else:
                    total_records_skipped += 1
        
        return merged_target, total_records_healed, total_fields_added, total_records_skipped
    
    # Step 1: Load all JSON files
    print("\n📁 [1/4] Loading JSON Files...")
    
    invharv_fetched = safe_read_json(INVHARV_FETCHED_INVESTORS, {})
    invharv_updated = safe_read_json(INVHARV_UPDATED_INVESTORS, {})
    harvhub_fetched = safe_read_json(HARVHUB_FETCHED_INVESTORS, {})
    harvhub_updated = safe_read_json(HARVHUB_UPDATED_INVESTORS, {})
    all_fetched = safe_read_json(ALL_FETCHED_INVESTORS, {})
    all_updated = safe_read_json(ALL_UPDATED_INVESTORS, {})
    
    print(f"    📊 INVHARV_FETCHED: {len(invharv_fetched):,} records")
    print(f"    📊 INVHARV_UPDATED: {len(invharv_updated):,} records")
    print(f"    📊 HARVHUB_FETCHED: {len(harvhub_fetched):,} records")
    print(f"    📊 HARVHUB_UPDATED: {len(harvhub_updated):,} records")
    print(f"    📊 ALL_FETCHED: {len(all_fetched):,} records")
    print(f"    📊 ALL_UPDATED: {len(all_updated):,} records")
    
    # Step 2: Determine which individual files have data
    invharv_has_data = len(invharv_fetched) > 0 or len(invharv_updated) > 0
    harvhub_has_data = len(harvhub_fetched) > 0 or len(harvhub_updated) > 0
    
    print(f"\n📊 [2/4] Analyzing Data Sources...")
    print(f"    INVHARV has data: {invharv_has_data}")
    print(f"    HARVHUB has data: {harvhub_has_data}")
    
    all_fetched_modified = False
    all_updated_modified = False
    invharv_fetched_modified = False
    invharv_updated_modified = False
    harvhub_fetched_modified = False
    harvhub_updated_modified = False
    
    total_fields_added_all_fetched = 0
    total_fields_added_all_updated = 0
    total_fields_added_invharv_fetched = 0
    total_fields_added_invharv_updated = 0
    total_fields_added_harvhub_fetched = 0
    total_fields_added_harvhub_updated = 0
    
    print("\n🔧 [3/4] Healing Files...")
    print("-"*70)
    
    # CASE 1: Individual files have data - heal ALL files from individual files
    if invharv_has_data or harvhub_has_data:
        print("\n  📋 Using INDIVIDUAL files as primary source...")
        
        # 1A: Heal ALL_UPDATED from INVHARV_UPDATED
        if invharv_updated:
            print("\n    🔄 INVHARV_UPDATED → ALL_UPDATED")
            all_updated, healed, fields, skipped = merge_file_pair(
                invharv_updated, all_updated, "INVHARV_UPDATED", "ALL_UPDATED", skip_missing_ids=True
            )
            if healed > 0:
                all_updated_modified = True
                total_fields_added_all_updated += fields
                print(f"      ✅ Healed {healed} records, added {fields} fields")
            else:
                print(f"      ℹ️ No healing needed")
        
        # 1B: Heal ALL_UPDATED from HARVHUB_UPDATED
        if harvhub_updated:
            print("\n    🔄 HARVHUB_UPDATED → ALL_UPDATED")
            all_updated, healed, fields, skipped = merge_file_pair(
                harvhub_updated, all_updated, "HARVHUB_UPDATED", "ALL_UPDATED", skip_missing_ids=True
            )
            if healed > 0:
                all_updated_modified = True
                total_fields_added_all_updated += fields
                print(f"      ✅ Healed {healed} records, added {fields} fields")
            else:
                print(f"      ℹ️ No healing needed")
        
        # 1C: Heal ALL_FETCHED from INVHARV_FETCHED
        if invharv_fetched:
            print("\n    🔄 INVHARV_FETCHED → ALL_FETCHED")
            all_fetched, healed, fields, skipped = merge_file_pair(
                invharv_fetched, all_fetched, "INVHARV_FETCHED", "ALL_FETCHED", skip_missing_ids=True
            )
            if healed > 0:
                all_fetched_modified = True
                total_fields_added_all_fetched += fields
                print(f"      ✅ Healed {healed} records, added {fields} fields")
            else:
                print(f"      ℹ️ No healing needed")
        
        # 1D: Heal ALL_FETCHED from HARVHUB_FETCHED
        if harvhub_fetched:
            print("\n    🔄 HARVHUB_FETCHED → ALL_FETCHED")
            all_fetched, healed, fields, skipped = merge_file_pair(
                harvhub_fetched, all_fetched, "HARVHUB_FETCHED", "ALL_FETCHED", skip_missing_ids=True
            )
            if healed > 0:
                all_fetched_modified = True
                total_fields_added_all_fetched += fields
                print(f"      ✅ Healed {healed} records, added {fields} fields")
            else:
                print(f"      ℹ️ No healing needed")
        
        # 1E: Also heal ALL_FETCHED from ALL_UPDATED (in case updated has fields fetched doesn't)
        if all_updated:
            print("\n    🔄 ALL_UPDATED → ALL_FETCHED (cross-healing)")
            all_fetched, healed, fields, skipped = merge_file_pair(
                all_updated, all_fetched, "ALL_UPDATED", "ALL_FETCHED", skip_missing_ids=True
            )
            if healed > 0:
                all_fetched_modified = True
                total_fields_added_all_fetched += fields
                print(f"      ✅ Healed {healed} records, added {fields} fields")
            else:
                print(f"      ℹ️ No healing needed")
        
        # 1F: Heal ALL_UPDATED from ALL_FETCHED (cross-healing)
        if all_fetched:
            print("\n    🔄 ALL_FETCHED → ALL_UPDATED (cross-healing)")
            all_updated, healed, fields, skipped = merge_file_pair(
                all_fetched, all_updated, "ALL_FETCHED", "ALL_UPDATED", skip_missing_ids=True
            )
            if healed > 0:
                all_updated_modified = True
                total_fields_added_all_updated += fields
                print(f"      ✅ Healed {healed} records, added {fields} fields")
            else:
                print(f"      ℹ️ No healing needed")
        
        # 1G: Heal individual files from ALL files (if individual is missing fields)
        print("\n    🔄 ALL_UPDATED → INVHARV_UPDATED (if needed)")
        if invharv_updated and all_updated:
            invharv_updated, healed, fields, skipped = merge_file_pair(
                all_updated, invharv_updated, "ALL_UPDATED", "INVHARV_UPDATED", skip_missing_ids=True
            )
            if healed > 0:
                invharv_updated_modified = True
                total_fields_added_invharv_updated += fields
                print(f"      ✅ Healed {healed} INVHARV records, added {fields} fields from ALL_UPDATED")
            else:
                print(f"      ℹ️ No healing needed for INVHARV_UPDATED")
        
        print("\n    🔄 ALL_UPDATED → HARVHUB_UPDATED (if needed)")
        if harvhub_updated and all_updated:
            harvhub_updated, healed, fields, skipped = merge_file_pair(
                all_updated, harvhub_updated, "ALL_UPDATED", "HARVHUB_UPDATED", skip_missing_ids=True
            )
            if healed > 0:
                harvhub_updated_modified = True
                total_fields_added_harvhub_updated += fields
                print(f"      ✅ Healed {healed} HARVHUB records, added {fields} fields from ALL_UPDATED")
            else:
                print(f"      ℹ️ No healing needed for HARVHUB_UPDATED")
        
        print("\n    🔄 ALL_FETCHED → INVHARV_FETCHED (if needed)")
        if invharv_fetched and all_fetched:
            invharv_fetched, healed, fields, skipped = merge_file_pair(
                all_fetched, invharv_fetched, "ALL_FETCHED", "INVHARV_FETCHED", skip_missing_ids=True
            )
            if healed > 0:
                invharv_fetched_modified = True
                total_fields_added_invharv_fetched += fields
                print(f"      ✅ Healed {healed} INVHARV records, added {fields} fields from ALL_FETCHED")
            else:
                print(f"      ℹ️ No healing needed for INVHARV_FETCHED")
        
        print("\n    🔄 ALL_FETCHED → HARVHUB_FETCHED (if needed)")
        if harvhub_fetched and all_fetched:
            harvhub_fetched, healed, fields, skipped = merge_file_pair(
                all_fetched, harvhub_fetched, "ALL_FETCHED", "HARVHUB_FETCHED", skip_missing_ids=True
            )
            if healed > 0:
                harvhub_fetched_modified = True
                total_fields_added_harvhub_fetched += fields
                print(f"      ✅ Healed {healed} HARVHUB records, added {fields} fields from ALL_FETCHED")
            else:
                print(f"      ℹ️ No healing needed for HARVHUB_FETCHED")
    
    # CASE 2: Individual files are empty - heal between ALL files only
    else:
        print("\n  📋 Individual files EMPTY - healing between ALL files only...")
        
        # 2A: Heal ALL_UPDATED from ALL_FETCHED
        if all_fetched:
            print("\n    🔄 ALL_FETCHED → ALL_UPDATED")
            all_updated, healed, fields, skipped = merge_file_pair(
                all_fetched, all_updated, "ALL_FETCHED", "ALL_UPDATED", skip_missing_ids=False
            )
            if healed > 0:
                all_updated_modified = True
                total_fields_added_all_updated += fields
                print(f"      ✅ Healed {healed} records, added {fields} fields")
            else:
                print(f"      ℹ️ No healing needed")
        
        # 2B: Heal ALL_FETCHED from ALL_UPDATED
        if all_updated:
            print("\n    🔄 ALL_UPDATED → ALL_FETCHED")
            all_fetched, healed, fields, skipped = merge_file_pair(
                all_updated, all_fetched, "ALL_UPDATED", "ALL_FETCHED", skip_missing_ids=False
            )
            if healed > 0:
                all_fetched_modified = True
                total_fields_added_all_fetched += fields
                print(f"      ✅ Healed {healed} records, added {fields} fields")
            else:
                print(f"      ℹ️ No healing needed")
    
    # Step 4: Write back all modified files
    print("\n💾 [4/4] Saving Modified Files...")
    print("-"*70)
    
    if all_fetched_modified:
        if safe_write_json(ALL_FETCHED_INVESTORS, all_fetched):
            print(f"    ✅ Saved: {ALL_FETCHED_INVESTORS}")
        else:
            print(f"    ❌ Failed to save: {ALL_FETCHED_INVESTORS}")
    else:
        print(f"    ℹ️ No changes to: {ALL_FETCHED_INVESTORS}")
    
    if all_updated_modified:
        if safe_write_json(ALL_UPDATED_INVESTORS, all_updated):
            print(f"    ✅ Saved: {ALL_UPDATED_INVESTORS}")
        else:
            print(f"    ❌ Failed to save: {ALL_UPDATED_INVESTORS}")
    else:
        print(f"    ℹ️ No changes to: {ALL_UPDATED_INVESTORS}")
    
    if invharv_fetched_modified:
        if safe_write_json(INVHARV_FETCHED_INVESTORS, invharv_fetched):
            print(f"    ✅ Saved: {INVHARV_FETCHED_INVESTORS}")
        else:
            print(f"    ❌ Failed to save: {INVHARV_FETCHED_INVESTORS}")
    else:
        print(f"    ℹ️ No changes to: {INVHARV_FETCHED_INVESTORS}")
    
    if invharv_updated_modified:
        if safe_write_json(INVHARV_UPDATED_INVESTORS, invharv_updated):
            print(f"    ✅ Saved: {INVHARV_UPDATED_INVESTORS}")
        else:
            print(f"    ❌ Failed to save: {INVHARV_UPDATED_INVESTORS}")
    else:
        print(f"    ℹ️ No changes to: {INVHARV_UPDATED_INVESTORS}")
    
    if harvhub_fetched_modified:
        if safe_write_json(HARVHUB_FETCHED_INVESTORS, harvhub_fetched):
            print(f"    ✅ Saved: {HARVHUB_FETCHED_INVESTORS}")
        else:
            print(f"    ❌ Failed to save: {HARVHUB_FETCHED_INVESTORS}")
    else:
        print(f"    ℹ️ No changes to: {HARVHUB_FETCHED_INVESTORS}")
    
    if harvhub_updated_modified:
        if safe_write_json(HARVHUB_UPDATED_INVESTORS, harvhub_updated):
            print(f"    ✅ Saved: {HARVHUB_UPDATED_INVESTORS}")
        else:
            print(f"    ❌ Failed to save: {HARVHUB_UPDATED_INVESTORS}")
    else:
        print(f"    ℹ️ No changes to: {HARVHUB_UPDATED_INVESTORS}")
    
    # Final Summary
    print("\n" + "="*70)
    print(f"  HEALING SUMMARY")
    print("="*70)
    print(f"\n  📊 FILES PROCESSED:")
    print(f"     ALL_FETCHED     : {'✅ MODIFIED' if all_fetched_modified else 'ℹ️ NO CHANGES'}")
    print(f"     ALL_UPDATED     : {'✅ MODIFIED' if all_updated_modified else 'ℹ️ NO CHANGES'}")
    print(f"     INVHARV_FETCHED : {'✅ MODIFIED' if invharv_fetched_modified else 'ℹ️ NO CHANGES'}")
    print(f"     INVHARV_UPDATED : {'✅ MODIFIED' if invharv_updated_modified else 'ℹ️ NO CHANGES'}")
    print(f"     HARVHUB_FETCHED : {'✅ MODIFIED' if harvhub_fetched_modified else 'ℹ️ NO CHANGES'}")
    print(f"     HARVHUB_UPDATED : {'✅ MODIFIED' if harvhub_updated_modified else 'ℹ️ NO CHANGES'}")
    
    print(f"\n  📈 FIELDS ADDED BY FILE:")
    print(f"     ALL_FETCHED     : {total_fields_added_all_fetched:,} fields")
    print(f"     ALL_UPDATED     : {total_fields_added_all_updated:,} fields")
    print(f"     INVHARV_FETCHED : {total_fields_added_invharv_fetched:,} fields")
    print(f"     INVHARV_UPDATED : {total_fields_added_invharv_updated:,} fields")
    print(f"     HARVHUB_FETCHED : {total_fields_added_harvhub_fetched:,} fields")
    print(f"     HARVHUB_UPDATED : {total_fields_added_harvhub_updated:,} fields")
    
    print(f"\n  🕐 Completion Time  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    
    return {
        'all_fetched_modified': all_fetched_modified,
        'all_updated_modified': all_updated_modified,
        'invharv_fetched_modified': invharv_fetched_modified,
        'invharv_updated_modified': invharv_updated_modified,
        'harvhub_fetched_modified': harvhub_fetched_modified,
        'harvhub_updated_modified': harvhub_updated_modified
    }

def update_fresh_data_from_fetched_to_all_files():
    """
    Distribute fresh data from ALL_FETCHED_INVESTORS to all other files.
    FIELD-BY-FIELD DISTRIBUTION: ALL_FETCHED → ALL_INVESTORS, ALL_UPDATED, INVHARV_FETCHED, HARVHUB_FETCHED, INVHARV_UPDATED, HARVHUB_UPDATED, ALL_INVESTORS_BACKUP
    
    This function performs:
    1. Reads ALL_FETCHED_INVESTORS (the source of truth for fresh data)
    2. Distributes each field to matching records in:
       - ALL_INVESTORS
       - ALL_UPDATED_INVESTORS
       - INVHARV_FETCHED_INVESTORS
       - HARVHUB_FETCHED_INVESTORS
       - INVHARV_UPDATED_INVESTORS
       - HARVHUB_UPDATED_INVESTORS
       - ALL_INVESTORS_BACKUP
    3. Field-by-field merging (source takes precedence for each field)
    4. Adds new records if they don't exist in target files
    5. Updates existing fields if values differ
    
    This ensures that all individual files (both fetched and updated) have the latest fresh data.
    
    Reads:
        - ALL_FETCHED_INVESTORS (source of truth)
    
    Writes:
        - ALL_INVESTORS
        - ALL_UPDATED_INVESTORS
        - INVHARV_FETCHED_INVESTORS
        - HARVHUB_FETCHED_INVESTORS
        - INVHARV_UPDATED_INVESTORS
        - HARVHUB_UPDATED_INVESTORS
        - ALL_INVESTORS_BACKUP
    
    Returns:
        dict: Statistics about the distribution process
    """
    print("\n" + "="*70)
    print(f"  FRESH DATA DISTRIBUTION (ALL_FETCHED → ALL OTHER FILES)")
    print("="*70)
    print(f"  Start Time  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-"*70)
    print("  Direction: ALL_FETCHED → ALL_INVESTORS, ALL_UPDATED, INVHARV_FETCHED, HARVHUB_FETCHED, INVHARV_UPDATED, HARVHUB_UPDATED, ALL_INVESTORS_BACKUP")
    print("  Mode     : FIELD-BY-FIELD DISTRIBUTION")
    print("="*70)
    
    stats = {
        "processing_success": False,
        "source": {
            "path": ALL_FETCHED_INVESTORS,
            "count": 0,
            "loaded": False
        },
        "targets": {
            ALL_INVESTORS: {
                "name": "ALL_INVESTORS",
                "records_updated": 0,
                "records_added": 0,
                "fields_merged": 0,
                "field_changes": {},
                "modified": False
            },
            ALL_UPDATED_INVESTORS: {
                "name": "ALL_UPDATED_INVESTORS",
                "records_updated": 0,
                "records_added": 0,
                "fields_merged": 0,
                "field_changes": {},
                "modified": False
            },
            INVHARV_FETCHED_INVESTORS: {
                "name": "INVHARV_FETCHED_INVESTORS",
                "records_updated": 0,
                "records_added": 0,
                "fields_merged": 0,
                "field_changes": {},
                "modified": False
            },
            HARVHUB_FETCHED_INVESTORS: {
                "name": "HARVHUB_FETCHED_INVESTORS",
                "records_updated": 0,
                "records_added": 0,
                "fields_merged": 0,
                "field_changes": {},
                "modified": False
            },
            INVHARV_UPDATED_INVESTORS: {
                "name": "INVHARV_UPDATED_INVESTORS",
                "records_updated": 0,
                "records_added": 0,
                "fields_merged": 0,
                "field_changes": {},
                "modified": False
            },
            HARVHUB_UPDATED_INVESTORS: {
                "name": "HARVHUB_UPDATED_INVESTORS",
                "records_updated": 0,
                "records_added": 0,
                "fields_merged": 0,
                "field_changes": {},
                "modified": False
            },
            ALL_INVESTORS_BACKUP: {
                "name": "ALL_INVESTORS_BACKUP",
                "records_updated": 0,
                "records_added": 0,
                "fields_merged": 0,
                "field_changes": {},
                "modified": False
            }
        },
        "errors": [],
        "warnings": [],
        "timestamp": datetime.now().isoformat()
    }
    
    def field_by_field_merge(source_record, target_record, record_id="unknown"):
        """
        Merge source_record into target_record field-by-field.
        Each field from source overrides the corresponding field in target.
        
        Returns:
            tuple: (merged_record, fields_merged_count, merged_fields_list, added_fields, updated_fields)
        """
        if not source_record:
            return target_record, 0, [], [], []
        
        if not target_record:
            return source_record.copy(), len(source_record) - 1, list(source_record.keys()), list(source_record.keys()), []
        
        merged = dict(target_record)  # Start with target
        fields_merged = []
        fields_added = []
        fields_updated = []
        
        for field, value in source_record.items():
            # Skip 'id' field as it's the key
            if field == 'id':
                continue
            
            # Check if field exists in target
            if field not in merged:
                # Field doesn't exist - add it
                merged[field] = value
                fields_added.append(field)
                fields_merged.append(field)
                print(f"            ➕ Added field '{field}' to investor {record_id}")
            else:
                # Field exists - check if value is different
                if merged[field] != value:
                    # Special handling for nested structures
                    if isinstance(value, dict) and isinstance(merged[field], dict):
                        # Deep merge nested dicts
                        merged[field] = deep_merge_nested(merged[field], value)
                        fields_updated.append(field)
                        fields_merged.append(field)
                        print(f"            🔄 Updated nested field '{field}' for investor {record_id}")
                    elif isinstance(value, list) and isinstance(merged[field], list):
                        # For lists, replace entire list (source takes precedence)
                        old_value = merged[field]
                        merged[field] = value
                        fields_updated.append(field)
                        fields_merged.append(field)
                        print(f"            🔄 Updated list field '{field}' for investor {record_id}")
                    else:
                        # Simple value override
                        old_value = merged[field]
                        merged[field] = value
                        fields_updated.append(field)
                        fields_merged.append(field)
                        # Print change for debugging
                        if field in ['balance_verification', 'application_status', 'broker_balance']:
                            print(f"            🔄 Changed {field}: '{old_value}' → '{value}' for investor {record_id}")
                        else:
                            print(f"            🔄 Updated field '{field}' for investor {record_id}")
        
        return merged, len(fields_merged), fields_merged, fields_added, fields_updated
    
    def deep_merge_nested(base_dict, override_dict):
        """
        Deep merge two dictionaries. override_dict takes precedence.
        For nested structures, recursively merge.
        """
        result = base_dict.copy() if base_dict else {}
        
        for key, value in override_dict.items():
            if key in result:
                if isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = deep_merge_nested(result[key], value)
                else:
                    result[key] = value
            else:
                result[key] = value
        
        return result
    
    def distribute_to_target(source_data, target_path, target_stats):
        """
        Distribute source_data to a target file field-by-field.
        
        Returns:
            tuple: (target_data, records_added, records_updated, fields_merged, field_changes)
        """
        # Load target data
        if os.path.exists(target_path):
            try:
                with open(target_path, 'r', encoding='utf-8') as f:
                    target_data = json.load(f)
                    if not isinstance(target_data, dict):
                        target_data = {}
            except Exception as e:
                stats["warnings"].append(f"Could not load {target_path}: {str(e)}. Starting with empty dict.")
                target_data = {}
        else:
            target_data = {}
        
        records_added = 0
        records_updated = 0
        total_fields_merged = 0
        field_changes = {}
        
        if not source_data:
            return target_data, 0, 0, 0, {}
        
        # Process each record in source
        for investor_id, source_record in source_data.items():
            if not isinstance(source_record, dict):
                continue
            
            # Check if investor exists in target
            if investor_id not in target_data:
                # New investor - add entire record
                target_data[investor_id] = source_record.copy()
                records_added += 1
                field_count = len([k for k in source_record.keys() if k != 'id'])
                total_fields_merged += field_count
                field_changes[investor_id] = {
                    'status': 'added',
                    'fields': list(source_record.keys()),
                    'field_count': field_count
                }
                print(f"         ➕ Added new investor {investor_id} with {field_count} fields")
                continue
            
            # Investor exists - merge field-by-field
            target_record = target_data[investor_id]
            
            # Perform field-by-field merge with record ID for debugging
            merged_record, fields_merged_count, merged_fields, added_fields, updated_fields = field_by_field_merge(
                source_record, target_record, investor_id
            )
            
            # Track changes - ALWAYS update if ANY fields were merged
            if fields_merged_count > 0:
                target_data[investor_id] = merged_record
                records_updated += 1
                total_fields_merged += fields_merged_count
                field_changes[investor_id] = {
                    'status': 'updated',
                    'fields': merged_fields,
                    'field_count': fields_merged_count,
                    'added_fields': added_fields,
                    'updated_fields': updated_fields
                }
                if len(merged_fields) <= 5:
                    print(f"         🔄 Updated investor {investor_id}: {', '.join(merged_fields)}")
                else:
                    print(f"         🔄 Updated investor {investor_id}: {', '.join(merged_fields[:5])} ... (+{len(merged_fields)-5} more)")
            else:
                # No changes detected - but still check if we need to sync
                # This ensures we catch cases where values are the same but fields might be missing
                print(f"         ℹ️  No changes for investor {investor_id}")
        
        return target_data, records_added, records_updated, total_fields_merged, field_changes
    
    def load_json_file(filepath, name):
        """Load a JSON file safely."""
        if not os.path.exists(filepath):
            stats["warnings"].append(f"{name} file not found: {filepath}")
            return None, False
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data, True
                else:
                    stats["errors"].append(f"{name} has invalid format (expected dict)")
                    return None, False
        except Exception as e:
            error_msg = f"Error loading {name}: {str(e)}"
            print(f"   ❌ {error_msg}")
            stats["errors"].append(error_msg)
            return None, False
    
    def save_json_file(filepath, data, name):
        """Save JSON data to file safely."""
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            error_msg = f"Error saving {name}: {str(e)}"
            print(f"   ❌ {error_msg}")
            stats["errors"].append(error_msg)
            return False
    
    try:
        # ============================================================
        # 1. LOAD SOURCE DATA (ALL_FETCHED_INVESTORS)
        # ============================================================
        print("\n📖 [1/4] Loading Source Data (ALL_FETCHED_INVESTORS)...")
        print("-"*40)
        
        source_data, loaded = load_json_file(ALL_FETCHED_INVESTORS, "ALL_FETCHED_INVESTORS")
        if not loaded or not source_data:
            print(f"   ❌ Source file not available or empty: {ALL_FETCHED_INVESTORS}")
            stats["processing_success"] = False
            stats["errors"].append("Source file not available or empty")
            return stats
        
        stats["source"]["loaded"] = True
        stats["source"]["count"] = len(source_data)
        print(f"   ✅ Loaded source: {len(source_data):,} records")
        
        # Show sample data from source
        if source_data and "1" in source_data:
            source_status = source_data["1"].get("balance_verification", "unknown")
            print(f"      ℹ️  Investor 1 balance_verification in source: {source_status}")
        
        total_fields = sum(len(record.keys()) - 1 for record in source_data.values())
        print(f"   📋 Total fields in source: {total_fields:,}")
        
        # ============================================================
        # 2. DISTRIBUTE TO ALL TARGETS - FORCE UPDATE ALL
        # ============================================================
        print("\n🔄 [2/4] Distributing Fresh Data to ALL Targets...")
        print("-"*40)
        print("   ⚠️  FORCE MODE: All targets will be updated with source data")
        print()
        
        targets_to_process = [
            (ALL_INVESTORS, stats["targets"][ALL_INVESTORS]),
            (ALL_UPDATED_INVESTORS, stats["targets"][ALL_UPDATED_INVESTORS]),
            (INVHARV_FETCHED_INVESTORS, stats["targets"][INVHARV_FETCHED_INVESTORS]),
            (HARVHUB_FETCHED_INVESTORS, stats["targets"][HARVHUB_FETCHED_INVESTORS]),
            (INVHARV_UPDATED_INVESTORS, stats["targets"][INVHARV_UPDATED_INVESTORS]),
            (HARVHUB_UPDATED_INVESTORS, stats["targets"][HARVHUB_UPDATED_INVESTORS]),
            (ALL_INVESTORS_BACKUP, stats["targets"][ALL_INVESTORS_BACKUP])
        ]
        
        for target_path, target_stats in targets_to_process:
            print(f"\n   📤 Processing: {target_stats['name']}")
            print(f"      Path: {target_path}")
            
            # Check if target file exists and show current status
            if os.path.exists(target_path):
                try:
                    with open(target_path, 'r', encoding='utf-8') as f:
                        check_data = json.load(f)
                        if check_data and "1" in check_data:
                            current_status = check_data["1"].get("balance_verification", "unknown")
                            print(f"      📊 Current balance_verification for investor 1: {current_status}")
                except:
                    pass
            else:
                print(f"      ℹ️  Target file does not exist, will be created")
            
            # Distribute data to this target
            target_data, records_added, records_updated, fields_merged, field_changes = distribute_to_target(
                source_data, target_path, target_stats
            )
            
            # Update stats
            target_stats["records_added"] = records_added
            target_stats["records_updated"] = records_updated
            target_stats["fields_merged"] = fields_merged
            target_stats["field_changes"] = field_changes
            
            # Show summary
            print(f"      📊 Added: {records_added} records | Updated: {records_updated} records | Fields: {fields_merged}")
            
            # Show specific change for investor 1 if available
            if field_changes and "1" in field_changes:
                change = field_changes["1"]
                if change['status'] == 'updated':
                    print(f"      🔑 Investor 1 updated: {change['field_count']} fields changed")
                    if 'balance_verification' in change['fields']:
                        print(f"         - balance_verification was updated")
            
            # ALWAYS save if we have target data, even if no changes detected
            # This ensures the file gets updated with any new fields from source
            if target_data:
                if save_json_file(target_path, target_data, target_stats['name']):
                    target_stats["modified"] = True
                    print(f"      ✅ Saved: {target_path}")
                    
                    # Verify the saved data
                    if target_data and "1" in target_data:
                        saved_status = target_data["1"].get("balance_verification", "unknown")
                        print(f"      🔍 Verified balance_verification for investor 1: {saved_status}")
                else:
                    print(f"      ❌ Failed to save: {target_path}")
            else:
                print(f"      ⚠️  No target data to save")
        
        # ============================================================
        # 3. FORCE SYNC: Explicitly update HARVHUB_UPDATED_INVESTORS
        # ============================================================
        print("\n🔄 [3/4] FORCE SYNC: Explicitly updating HARVHUB_UPDATED_INVESTORS...")
        print("-"*40)
        
        # Load HARVHUB_UPDATED_INVESTORS
        harvhub_updated_path = HARVHUB_UPDATED_INVESTORS
        if os.path.exists(harvhub_updated_path):
            try:
                with open(harvhub_updated_path, 'r', encoding='utf-8') as f:
                    harvhub_updated_data = json.load(f)
                    if not isinstance(harvhub_updated_data, dict):
                        harvhub_updated_data = {}
            except Exception as e:
                print(f"   ⚠️  Error loading HARVHUB_UPDATED: {str(e)}")
                harvhub_updated_data = {}
        else:
            harvhub_updated_data = {}
            print(f"   ℹ️  HARVHUB_UPDATED_INVESTORS does not exist, will create")
        
        force_updated = False
        force_fields_updated = 0
        force_records_updated = 0
        
        # Force update each record from source to HARVHUB_UPDATED
        for investor_id, source_record in source_data.items():
            if investor_id in harvhub_updated_data:
                # Update existing record
                target_record = harvhub_updated_data[investor_id]
                fields_changed = 0
                
                for field, value in source_record.items():
                    if field == 'id':
                        continue
                    # Always update with source value (force sync)
                    if field not in target_record or target_record[field] != value:
                        target_record[field] = value
                        fields_changed += 1
                        force_updated = True
                
                if fields_changed > 0:
                    harvhub_updated_data[investor_id] = target_record
                    force_records_updated += 1
                    force_fields_updated += fields_changed
                    print(f"      ✅ Force updated investor {investor_id}: {fields_changed} fields")
            else:
                # Add new record
                harvhub_updated_data[investor_id] = source_record.copy()
                force_records_updated += 1
                force_fields_updated += len(source_record) - 1
                force_updated = True
                print(f"      ✅ Force added investor {investor_id}")
        
        if force_updated:
            if save_json_file(harvhub_updated_path, harvhub_updated_data, "HARVHUB_UPDATED_INVESTORS (force sync)"):
                # Update stats for HARVHUB_UPDATED
                stats["targets"][HARVHUB_UPDATED_INVESTORS]["records_updated"] = force_records_updated
                stats["targets"][HARVHUB_UPDATED_INVESTORS]["fields_merged"] = force_fields_updated
                stats["targets"][HARVHUB_UPDATED_INVESTORS]["modified"] = True
                print(f"      ✅ Force sync completed: {force_records_updated} records, {force_fields_updated} fields")
            else:
                print(f"      ❌ Failed to save force synced HARVHUB_UPDATED")
        else:
            print(f"      ℹ️ No changes needed for HARVHUB_UPDATED")
        
        # ============================================================
        # 4. FINAL SUMMARY
        # ============================================================
        stats["processing_success"] = True
        
        print("\n" + "="*70)
        print(f"  FRESH DATA DISTRIBUTION SUMMARY")
        print("="*70)
        
        print(f"\n  📖 SOURCE FILE:")
        print(f"     File    : {ALL_FETCHED_INVESTORS}")
        print(f"     Records : {stats['source']['count']:,}")
        print(f"     Status  : {'✅ Loaded' if stats['source']['loaded'] else '❌ Failed'}")
        
        if source_data and "1" in source_data:
            source_status = source_data["1"].get("balance_verification", "unknown")
            print(f"     Sample  : Investor 1 balance_verification = {source_status}")
        
        print(f"\n  📤 TARGET FILES (ALL_FETCHED → Each Target):")
        
        total_records_added = 0
        total_records_updated = 0
        total_fields_merged = 0
        
        for target_path, target_stats in stats["targets"].items():
            status_emoji = "✅" if target_stats["modified"] else "ℹ️"
            print(f"\n     {status_emoji} {target_stats['name']}:")
            print(f"        Records Added   : {target_stats['records_added']:,}")
            print(f"        Records Updated : {target_stats['records_updated']:,}")
            print(f"        Fields Merged   : {target_stats['fields_merged']:,}")
            print(f"        Modified        : {'Yes' if target_stats['modified'] else 'No'}")
            print(f"        Path            : {target_path}")
            
            # Show if investor 1 was updated in this target
            if target_stats["field_changes"] and "1" in target_stats["field_changes"]:
                change = target_stats["field_changes"]["1"]
                if change['status'] == 'updated':
                    print(f"        🔑 Investor 1 updated: {', '.join(change['fields'][:5])}")
            
            total_records_added += target_stats['records_added']
            total_records_updated += target_stats['records_updated']
            total_fields_merged += target_stats['fields_merged']
        
        print(f"\n  📊 GRAND TOTALS:")
        print(f"     Total Records Added   : {total_records_added:,}")
        print(f"     Total Records Updated : {total_records_updated:,}")
        print(f"     Total Fields Merged   : {total_fields_merged:,}")
        
        # Special check for ALL_INVESTORS
        all_investors_stats = stats["targets"][ALL_INVESTORS]
        if all_investors_stats["modified"]:
            print(f"\n  ✅ ALL_INVESTORS was successfully updated!")
        else:
            print(f"\n  ⚠️  ALL_INVESTORS was NOT updated - check for issues")
        
        # Special check for HARVHUB_UPDATED
        harvhub_updated_stats = stats["targets"][HARVHUB_UPDATED_INVESTORS]
        if harvhub_updated_stats["modified"]:
            print(f"\n  ✅ HARVHUB_UPDATED_INVESTORS was successfully updated!")
        else:
            print(f"\n  ⚠️  HARVHUB_UPDATED_INVESTORS was NOT updated - check for issues")
        
        # Special check for ALL_INVESTORS_BACKUP
        backup_stats = stats["targets"][ALL_INVESTORS_BACKUP]
        if backup_stats["modified"]:
            print(f"\n  ✅ ALL_INVESTORS_BACKUP was successfully updated!")
        else:
            print(f"\n  ℹ️  ALL_INVESTORS_BACKUP - no changes needed")
        
        if stats["warnings"]:
            print(f"\n  ⚠️  WARNINGS ({len(stats['warnings'])}):")
            for warning in stats["warnings"]:
                print(f"     - {warning}")
        
        if stats["errors"]:
            print(f"\n  ❌ ERRORS ({len(stats['errors'])}):")
            for error in stats["errors"]:
                print(f"     - {error}")
        
        print(f"\n  ✅ Status : {'SUCCESS' if stats['processing_success'] else 'FAILED'}")
        print(f"  🕐 Time   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*70)
        
        return stats
        
    except Exception as e:
        print(f"\n{'='*70}")
        print(f"   CRITICAL ERROR")
        print(f"{'='*70}")
        print(f"  Error Type : {type(e).__name__}")
        print(f"  Message    : {str(e)}")
        print(f"{'='*70}")
        
        import traceback
        print(f"\n  📜 Full Traceback:")
        traceback.print_exc()
        
        stats["processing_success"] = False
        stats["errors"].append(f"Critical error: {str(e)}")
        return stats
 
def restore_empty_investor_files():
    """
    Checks and synchronizes investor files between main and backup.
    
    This function handles two scenarios:
    1. If main file is empty/doesn't exist -> Restore from backup
    2. If main file has data -> Check backup and update if needed:
       - If backup is empty -> Copy main to backup
       - If backup has fewer records -> Add missing records from main
       - If backup has missing fields -> Update with complete data from main
    
    Returns:
        dict: Status of the synchronization process
    """
    
    print(f"\n{'='*70}")
    print(f"SYNCHRONIZE INVESTOR FILES".center(70))
    print(f"{'='*70}")
    print(f"  Start Time  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-"*70)
    
    result = {
        "fetched_synced": False,
        "updated_synced": False,
        "fetched_main_exists": False,
        "fetched_main_empty": False,
        "fetched_main_records": 0,
        "fetched_backup_exists": False,
        "fetched_backup_empty": False,
        "fetched_backup_records": 0,
        "fetched_restored_from_backup": False,
        "fetched_backup_updated_from_main": False,
        "fetched_backup_records_added": 0,
        "fetched_backup_fields_updated": 0,
        "updated_main_exists": False,
        "updated_main_empty": False,
        "updated_main_records": 0,
        "updated_backup_exists": False,
        "updated_backup_empty": False,
        "updated_backup_records": 0,
        "updated_restored_from_main": False,
        "updated_backup_updated_from_main": False,
        "updated_backup_records_added": 0,
        "updated_backup_fields_updated": 0,
        "errors": [],
        "warnings": [],
        "timestamp": datetime.now().isoformat()
    }
    
    def is_file_empty(filepath):
        """Check if a JSON file exists and is empty or contains empty data"""
        if not os.path.exists(filepath):
            return True, "File does not exist"
        
        try:
            if os.path.getsize(filepath) == 0:
                return True, "File is empty (0 bytes)"
            
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    return True, "File contains only whitespace"
                
                data = json.loads(content)
                
                if isinstance(data, dict) and len(data) == 0:
                    return True, "File contains empty dictionary {}"
                elif isinstance(data, list) and len(data) == 0:
                    return True, "File contains empty list []"
                elif data is None:
                    return True, "File contains null"
                
                return False, "File has valid data"
                
        except json.JSONDecodeError as e:
            return True, f"Invalid JSON: {str(e)}"
        except Exception as e:
            return True, f"Error reading file: {str(e)}"
    
    def load_json_data(filepath):
        """Load JSON data from file"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            return None
    
    def save_json_data(filepath, data):
        """Save JSON data to file"""
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            return False
    
    def count_non_empty_fields(obj, ignore_keys=[]):
        """Count non-empty fields in an object."""
        if not isinstance(obj, dict):
            return 0
        
        count = 0
        for key, value in obj.items():
            if key in ignore_keys:
                continue
            if value is not None and value != "" and value != "NULL":
                if isinstance(value, dict):
                    count += count_non_empty_fields(value, ignore_keys)
                elif isinstance(value, list) and len(value) > 0:
                    count += 1
                elif not isinstance(value, list):
                    count += 1
        return count
    
    def deep_merge(base_dict, override_dict):
        """
        Deep merge two dictionaries, preferring override_dict values.
        
        Returns:
            dict: Merged dictionary
        """
        result = base_dict.copy() if base_dict else {}
        
        for key, value in override_dict.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = deep_merge(result[key], value)
            elif value is not None and value != "NULL" and value != "":
                result[key] = value
        
        return result
    
    def compare_and_update_backup(main_data, backup_data, file_type):
        """
        Compare main and backup data, update backup if main has more/better data.
        
        Returns:
            tuple: (updated_backup, records_added, fields_updated)
        """
        if not main_data:
            return backup_data, 0, 0
        
        if not backup_data:
            return main_data.copy(), len(main_data), 0
        
        updated_backup = backup_data.copy()
        records_added = 0
        fields_updated = 0
        
        # Check each record in main
        for investor_id, main_record in main_data.items():
            if not isinstance(main_record, dict):
                continue
            
            # If investor doesn't exist in backup, add it
            if investor_id not in updated_backup:
                updated_backup[investor_id] = main_record.copy()
                records_added += 1
                continue
            
            # Investor exists, check if main has more/better data
            backup_record = updated_backup[investor_id]
            
            # Count fields in both
            main_fields = count_non_empty_fields(main_record)
            backup_fields = count_non_empty_fields(backup_record)
            
            # If main has more fields, merge/update
            if main_fields > backup_fields:
                # Deep merge: main updates take precedence
                merged_record = deep_merge(backup_record, main_record)
                updated_backup[investor_id] = merged_record
                fields_updated += 1
            elif main_fields == backup_fields:
                # Same number of fields, check if any fields are different
                merged_record = deep_merge(backup_record, main_record)
                if merged_record != backup_record:
                    updated_backup[investor_id] = merged_record
                    fields_updated += 1
        
        return updated_backup, records_added, fields_updated
    
    def get_file_stats(filepath):
        """Get basic stats about a JSON file"""
        if not os.path.exists(filepath):
            return {"exists": False, "size": 0, "count": 0}
        
        try:
            size = os.path.getsize(filepath)
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                count = len(data) if isinstance(data, dict) else 0
            return {"exists": True, "size": size, "count": count}
        except:
            return {"exists": True, "size": size, "count": 0}
    
    def get_backup_path(main_path):
        """Get backup path for a given main file"""
        if "fetched" in main_path.lower():
            return ALL_INVESTORS_BACKUP
        else:
            # For updated files, we'll use fetched as source if needed
            return None
    
    try:
        # ============================================
        # CHECK FETCHED FILE
        # ============================================
        
        print("\n📋 Checking ALL_FETCHED_INVESTORS...")
        print("-"*40)
        
        # Load main file
        fetched_main_exists = os.path.exists(ALL_FETCHED_INVESTORS)
        result["fetched_main_exists"] = fetched_main_exists
        
        if fetched_main_exists:
            fetched_main_empty, reason = is_file_empty(ALL_FETCHED_INVESTORS)
            result["fetched_main_empty"] = fetched_main_empty
            
            fetched_main_data = load_json_data(ALL_FETCHED_INVESTORS)
            fetched_main_count = len(fetched_main_data) if fetched_main_data else 0
            result["fetched_main_records"] = fetched_main_count
            
            print(f"   📄 Main file exists: {ALL_FETCHED_INVESTORS}")
            print(f"   📊 Records: {fetched_main_count:,}")
            
            if fetched_main_empty:
                print(f"   ⚠️ Main file is empty: {reason}")
                result["warnings"].append(f"ALL_FETCHED_INVESTORS is empty: {reason}")
                
                # Scenario 1: Main is empty -> Restore from backup
                backup_exists = os.path.exists(ALL_INVESTORS_BACKUP)
                result["fetched_backup_exists"] = backup_exists
                
                if backup_exists:
                    backup_empty, backup_reason = is_file_empty(ALL_INVESTORS_BACKUP)
                    result["fetched_backup_empty"] = backup_empty
                    
                    if not backup_empty:
                        backup_data = load_json_data(ALL_INVESTORS_BACKUP)
                        backup_count = len(backup_data) if backup_data else 0
                        result["fetched_backup_records"] = backup_count
                        
                        print(f"   📄 Backup found: {ALL_INVESTORS_BACKUP}")
                        print(f"   📊 Backup records: {backup_count:,}")
                        
                        # Restore from backup
                        print(f"   🔄 Restoring from backup...")
                        if save_json_data(ALL_FETCHED_INVESTORS, backup_data):
                            print(f"   ✅ Restored {backup_count:,} records from backup")
                            result["fetched_restored_from_backup"] = True
                            result["fetched_synced"] = True
                        else:
                            print(f"   ❌ Failed to restore from backup")
                            result["errors"].append("Failed to restore fetched from backup")
                    else:
                        print(f"   ❌ Backup exists but is empty: {backup_reason}")
                        result["errors"].append("Backup file is empty, cannot restore")
                else:
                    print(f"   ❌ No backup file found")
                    result["errors"].append("No backup file found for fetched investors")
            else:
                print(f"   ✅ Main file has valid data")
                
                # Scenario 2: Main has data -> Check/update backup
                backup_exists = os.path.exists(ALL_INVESTORS_BACKUP)
                result["fetched_backup_exists"] = backup_exists
                
                if backup_exists:
                    backup_empty, backup_reason = is_file_empty(ALL_INVESTORS_BACKUP)
                    result["fetched_backup_empty"] = backup_empty
                    
                    backup_data = load_json_data(ALL_INVESTORS_BACKUP)
                    backup_count = len(backup_data) if backup_data else 0
                    result["fetched_backup_records"] = backup_count
                    
                    print(f"   📄 Backup exists: {ALL_INVESTORS_BACKUP}")
                    print(f"   📊 Backup records: {backup_count:,}")
                    
                    # Compare and update backup if needed
                    if backup_empty or backup_count < fetched_main_count:
                        print(f"   🔄 Updating backup from main...")
                        
                        updated_backup, records_added, fields_updated = compare_and_update_backup(
                            fetched_main_data, 
                            backup_data if not backup_empty else {},
                            "fetched"
                        )
                        
                        if save_json_data(ALL_INVESTORS_BACKUP, updated_backup):
                            print(f"   ✅ Backup updated successfully")
                            print(f"      📝 Records added: {records_added:,}")
                            print(f"      🔄 Records updated: {fields_updated:,}")
                            
                            result["fetched_backup_updated_from_main"] = True
                            result["fetched_backup_records_added"] = records_added
                            result["fetched_backup_fields_updated"] = fields_updated
                            result["fetched_synced"] = True
                        else:
                            print(f"   ❌ Failed to update backup")
                            result["errors"].append("Failed to update fetched backup")
                    else:
                        print(f"   ✅ Backup is up to date ({backup_count:,} records)")
                        result["fetched_synced"] = True
                else:
                    # Backup doesn't exist, create it
                    print(f"   📄 No backup exists, creating from main...")
                    if save_json_data(ALL_INVESTORS_BACKUP, fetched_main_data):
                        print(f"   ✅ Created backup with {fetched_main_count:,} records")
                        result["fetched_backup_updated_from_main"] = True
                        result["fetched_synced"] = True
                    else:
                        print(f"   ❌ Failed to create backup")
                        result["errors"].append("Failed to create fetched backup")
        else:
            print(f"   ❌ Main file does not exist: {ALL_FETCHED_INVESTORS}")
            result["warnings"].append("ALL_FETCHED_INVESTORS does not exist")
            
            # Try to restore from backup
            backup_exists = os.path.exists(ALL_INVESTORS_BACKUP)
            result["fetched_backup_exists"] = backup_exists
            
            if backup_exists:
                backup_empty, backup_reason = is_file_empty(ALL_INVESTORS_BACKUP)
                result["fetched_backup_empty"] = backup_empty
                
                if not backup_empty:
                    backup_data = load_json_data(ALL_INVESTORS_BACKUP)
                    backup_count = len(backup_data) if backup_data else 0
                    result["fetched_backup_records"] = backup_count
                    
                    print(f"   📄 Creating from backup: {ALL_INVESTORS_BACKUP}")
                    print(f"   📊 Backup records: {backup_count:,}")
                    
                    if save_json_data(ALL_FETCHED_INVESTORS, backup_data):
                        print(f"   ✅ Created main from backup ({backup_count:,} records)")
                        result["fetched_restored_from_backup"] = True
                        result["fetched_synced"] = True
                    else:
                        print(f"   ❌ Failed to create from backup")
                        result["errors"].append("Failed to create fetched from backup")
                else:
                    print(f"   ❌ Backup exists but is empty: {backup_reason}")
                    result["errors"].append("Backup file is empty")
            else:
                print(f"   ❌ No backup file found")
                result["errors"].append("No backup file found to create fetched investors")
        
        # ============================================
        # CHECK UPDATED FILE
        # ============================================
        
        print("\n📋 Checking ALL_UPDATED_INVESTORS...")
        print("-"*40)
        
        updated_main_exists = os.path.exists(ALL_UPDATED_INVESTORS)
        result["updated_main_exists"] = updated_main_exists
        
        if updated_main_exists:
            updated_main_empty, reason = is_file_empty(ALL_UPDATED_INVESTORS)
            result["updated_main_empty"] = updated_main_empty
            
            updated_main_data = load_json_data(ALL_UPDATED_INVESTORS)
            updated_main_count = len(updated_main_data) if updated_main_data else 0
            result["updated_main_records"] = updated_main_count
            
            print(f"   📄 Main file exists: {ALL_UPDATED_INVESTORS}")
            print(f"   📊 Records: {updated_main_count:,}")
            
            if updated_main_empty:
                print(f"   ⚠️ Main file is empty: {reason}")
                result["warnings"].append("ALL_UPDATED_INVESTORS is empty")
                
                # Restore updated from fetched (since updated doesn't have a dedicated backup)
                if result["fetched_synced"] and not result["fetched_main_empty"]:
                    fetched_data = load_json_data(ALL_FETCHED_INVESTORS)
                    if fetched_data:
                        print(f"   🔄 Restoring from ALL_FETCHED_INVESTORS...")
                        if save_json_data(ALL_UPDATED_INVESTORS, fetched_data):
                            print(f"   ✅ Restored {len(fetched_data):,} records from fetched")
                            result["updated_restored_from_main"] = True
                            result["updated_synced"] = True
                        else:
                            print(f"   ❌ Failed to restore updated from fetched")
                            result["errors"].append("Failed to restore updated from fetched")
                    else:
                        print(f"   ❌ Cannot restore: fetched data is empty")
                        result["errors"].append("Cannot restore updated (fetched is empty)")
                else:
                    print(f"   ❌ Cannot restore: fetched file is empty or invalid")
                    result["errors"].append("Cannot restore updated (fetched is empty or invalid)")
            else:
                print(f"   ✅ Main file has valid data")
                
                # Check if updated has data and fetched has more/better data
                if result["fetched_synced"] and not result["fetched_main_empty"]:
                    fetched_data = load_json_data(ALL_FETCHED_INVESTORS)
                    fetched_count = len(fetched_data) if fetched_data else 0
                    
                    # If fetched has more records or is newer, update updated from fetched
                    if fetched_count > updated_main_count:
                        print(f"   🔄 Updating from ALL_FETCHED_INVESTORS...")
                        print(f"      Fetched records: {fetched_count:,}")
                        print(f"      Updated records: {updated_main_count:,}")
                        
                        updated_backup, records_added, fields_updated = compare_and_update_backup(
                            fetched_data,
                            updated_main_data,
                            "updated"
                        )
                        
                        if save_json_data(ALL_UPDATED_INVESTORS, updated_backup):
                            print(f"   ✅ Updated from fetched successfully")
                            print(f"      📝 Records added: {records_added:,}")
                            print(f"      🔄 Records updated: {fields_updated:,}")
                            
                            result["updated_backup_updated_from_main"] = True
                            result["updated_backup_records_added"] = records_added
                            result["updated_backup_fields_updated"] = fields_updated
                            result["updated_synced"] = True
                        else:
                            print(f"   ❌ Failed to update from fetched")
                            result["errors"].append("Failed to update updated from fetched")
                    else:
                        print(f"   ✅ Updated file is up to date")
                        result["updated_synced"] = True
                else:
                    print(f"   ✅ Updated file is valid (no sync needed)")
                    result["updated_synced"] = True
        else:
            print(f"   ❌ Main file does not exist: {ALL_UPDATED_INVESTORS}")
            result["warnings"].append("ALL_UPDATED_INVESTORS does not exist")
            
            # Create updated from fetched if available
            if result["fetched_synced"] and not result["fetched_main_empty"]:
                fetched_data = load_json_data(ALL_FETCHED_INVESTORS)
                if fetched_data:
                    print(f"   🔄 Creating from ALL_FETCHED_INVESTORS...")
                    if save_json_data(ALL_UPDATED_INVESTORS, fetched_data):
                        print(f"   ✅ Created updated from fetched ({len(fetched_data):,} records)")
                        result["updated_restored_from_main"] = True
                        result["updated_synced"] = True
                    else:
                        print(f"   ❌ Failed to create updated from fetched")
                        result["errors"].append("Failed to create updated from fetched")
                else:
                    print(f"   ❌ Cannot create: fetched data is empty")
                    result["errors"].append("Cannot create updated (fetched is empty)")
            else:
                print(f"   ❌ Cannot create: fetched file is empty or invalid")
                result["errors"].append("Cannot create updated (fetched is empty or invalid)")
        
        # ============================================
        # SUMMARY
        # ============================================
        
        print("\n" + "="*70)
        print(f"SYNCHRONIZATION SUMMARY".center(70))
        print("="*70)
        
        print(f"\n📊 FETCHED FILES:")
        if result["fetched_restored_from_backup"]:
            print(f"   ✅ Restored from backup to main")
        elif result["fetched_backup_updated_from_main"]:
            print(f"   ✅ Updated backup from main")
            if result["fetched_backup_records_added"] > 0:
                print(f"      📝 Records added to backup: {result['fetched_backup_records_added']:,}")
            if result["fetched_backup_fields_updated"] > 0:
                print(f"      🔄 Records updated in backup: {result['fetched_backup_fields_updated']:,}")
        elif result["fetched_synced"]:
            print(f"   ✅ Files are synchronized (no changes needed)")
        else:
            print(f"   ❌ Synchronization failed")
        
        print(f"\n📊 UPDATED FILES:")
        if result["updated_restored_from_main"]:
            print(f"   ✅ Created/restored from fetched")
        elif result["updated_backup_updated_from_main"]:
            print(f"   ✅ Updated from fetched")
            if result["updated_backup_records_added"] > 0:
                print(f"      📝 Records added: {result['updated_backup_records_added']:,}")
            if result["updated_backup_fields_updated"] > 0:
                print(f"      🔄 Records updated: {result['updated_backup_fields_updated']:,}")
        elif result["updated_synced"]:
            print(f"   ✅ File is up to date (no changes needed)")
        else:
            print(f"   ❌ Synchronization failed")
        
        if result["errors"]:
            print(f"\n❌ ERRORS ({len(result['errors'])}):")
            for error in result["errors"]:
                print(f"   - {error}")
        
        if result["warnings"]:
            print(f"\n⚠️ WARNINGS ({len(result['warnings'])}):")
            for warning in result["warnings"]:
                print(f"   - {warning}")
        
        print(f"\n🕐 Time   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*70)
        
        return result
        
    except Exception as e:
        print(f"\n{'='*70}")
        print(f"CRITICAL ERROR".center(70))
        print(f"{'='*70}")
        print(f"  Error Type : {type(e).__name__}")
        print(f"  Message    : {str(e)}")
        print(f"{'='*70}")
        
        import traceback
        print(f"\n📜 Full Traceback:")
        traceback.print_exc()
        
        result["errors"].append(f"Critical error: {str(e)}")
        return result
 
def sync_and_distribute_investors():
    """
    Synchronizes and distributes investors between invharv and harvhub files.
    
    This function performs three main tasks:
    1. For existing investors in both files:
       - Updates missing fields in invharv/harvhub from ALL files
       - Updates ALL files with new data from invharv/harvhub
       - Filters grid traders to HARVHUB and non-grid traders to INVHARV
    2. For new investors not yet distributed:
       - Copies grid traders to harvhub with complete data
       - Copies non-grid traders to invharv with complete data
    3. Validation and cleanup:
       - Removes any investors from incorrect files
       - Ensures grid traders are only in HARVHUB
       - Ensures non-grid traders are only in INVHARV
    
    PRIORITY: FETCHED data takes precedence over UPDATED data
    - First process fetched files to get the latest data
    - Then apply fetched data to updated files (override)
    
    Uses ALL_FETCHED_INVESTORS and ALL_UPDATED_INVESTORS as the source of truth.
    """
    restore_empty_investor_files()
    
    print(f"\n{'='*70}")
    print(f"SYNC AND DISTRIBUTE INVESTORS".center(70))
    print(f"{'='*70}")
    print(f"  Start Time  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-"*70)
    print("  PRIORITY: FETCHED data takes precedence over UPDATED data")
    print("="*70)
    
    stats = {
        "processing_success": False,
        "fetched": {
            "existing_investors": {"processed": 0, "fields_filled": 0, "fields_updated": 0},
            "grid_traders_moved_to_harvhub": 0,
            "non_grid_traders_moved_to_invharv": 0,
            "new_grid_traders": {"copied_to_harvhub": 0, "ids": []},
            "new_non_grid_traders": {"copied_to_invharv": 0, "ids": []},
            "invharv_count": 0,
            "harvhub_count": 0,
            "all_count": 0,
            "cleanup": {
                "removed_from_invharv": 0,
                "removed_from_harvhub": 0,
                "invalid_grid_in_invharv": [],
                "invalid_non_grid_in_harvhub": []
            }
        },
        "updated": {
            "existing_investors": {"processed": 0, "fields_filled": 0, "fields_updated": 0},
            "grid_traders_moved_to_harvhub": 0,
            "non_grid_traders_moved_to_invharv": 0,
            "new_grid_traders": {"copied_to_harvhub": 0, "ids": []},
            "new_non_grid_traders": {"copied_to_invharv": 0, "ids": []},
            "invharv_count": 0,
            "harvhub_count": 0,
            "all_count": 0,
            "cleanup": {
                "removed_from_invharv": 0,
                "removed_from_harvhub": 0,
                "invalid_grid_in_invharv": [],
                "invalid_non_grid_in_harvhub": []
            }
        },
        "sync_from_fetched_to_updated": {
            "records_updated": 0,
            "fields_synced": 0,
            "records_added": 0,
            "field_changes": {}
        },
        "errors": [],
        "warnings": [],
        "timestamp": datetime.now().isoformat()
    }
    
    # ============================================
    # HELPER FUNCTIONS
    # ============================================
    
    def safe_json_load(filepath, default=None):
        """Safely load JSON"""
        if default is None:
            default = {}
        
        if not os.path.exists(filepath):
            return default
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                return default
        except Exception as e:
            print(f"   ⚠️ Error loading {filepath}: {e}")
            return default
    
    def safe_json_write(filepath, data):
        """Safely write JSON"""
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            temp_file = filepath + '.tmp'
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            if os.path.exists(filepath):
                os.remove(filepath)
            os.rename(temp_file, filepath)
            return True
        except Exception as e:
            print(f"   ❌ Write error to {filepath}: {e}")
            return False
    
    def deep_merge(base_dict, override_dict, prefer_override=True):
        """
        Deep merge two dictionaries.
        
        Args:
            base_dict: The base dictionary to merge into
            override_dict: The dictionary with potential updates
            prefer_override: If True, override_dict values take precedence
        
        Returns:
            dict: Merged dictionary
        """
        result = base_dict.copy()
        
        for key, value in override_dict.items():
            if key in result:
                # If both are dicts, recursively merge
                if isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = deep_merge(result[key], value, prefer_override)
                # If value is not None or empty, update based on preference
                elif value is not None and value != "NULL" and value != "":
                    if prefer_override:
                        result[key] = value
                    # If we prefer base, only update if base value is empty/missing
                    elif result.get(key) is None or result.get(key) == "NULL" or result.get(key) == "":
                        result[key] = value
            else:
                # Key doesn't exist in base, add it
                result[key] = value
        
        return result
    
    def count_non_empty_fields(obj, ignore_keys=[]):
        """Count non-empty fields in an object."""
        if not isinstance(obj, dict):
            return 0
        
        count = 0
        for key, value in obj.items():
            if key in ignore_keys:
                continue
            if value is not None and value != "" and value != "NULL":
                if isinstance(value, dict):
                    # Recursively count nested dict fields
                    count += count_non_empty_fields(value, ignore_keys)
                elif isinstance(value, list) and len(value) > 0:
                    count += 1
                elif not isinstance(value, list):
                    count += 1
        return count
    
    def merge_investor_records(source_data, target_data, source_name):
        """
        Merge source_data into target_data at the field level.
        
        Returns:
            tuple: (updated_target, missing_fields_count, updated_fields_count)
        """
        updated_target = target_data.copy() if target_data else {}
        total_missing_fields = 0
        total_updated_fields = 0
        
        # For each investor in source_data
        for investor_id, source_record in source_data.items():
            if not isinstance(source_record, dict):
                continue
                
            # If investor doesn't exist in target, add the entire record
            if investor_id not in updated_target:
                updated_target[investor_id] = source_record.copy()
                # Count fields added
                total_missing_fields += count_non_empty_fields(source_record)
                continue
            
            # Investor exists, merge fields
            target_record = updated_target[investor_id]
            
            # Count fields before merge
            before_fields = count_non_empty_fields(target_record)
            
            # Deep merge: source updates take precedence for existing fields,
            # but we also fill missing fields from target if source has them
            merged_record = deep_merge(target_record, source_record, prefer_override=True)
            
            # Now fill any fields that exist in target but missing in source
            # This ensures bidirectionality
            merged_record = deep_merge(merged_record, target_record, prefer_override=False)
            
            after_fields = count_non_empty_fields(merged_record)
            
            # Count changes
            if before_fields < after_fields:
                total_missing_fields += (after_fields - before_fields)
            elif before_fields > after_fields:
                total_updated_fields += (before_fields - after_fields)
            
            updated_target[investor_id] = merged_record
        
        return updated_target, total_missing_fields, total_updated_fields
    
    def is_grid_trader(investor_data):
        """
        Check if investor belongs to HARVHUB.
        
        An investor goes to HARVHUB if it is a grid trader OR if it matches
        any of the additional HARVHUB keywords:
            - Boom and Crash
            - Trailing spike
            - Trailing price
            - Stalking Price
            - Stalking Spike
        
        Matching strategy:
            1. Regex match against the full cleaned value using patterns that
               tolerate any non-word separator (space, _, -, or nothing).
            2. "Squashed" normalized substring match (strip all non-alphanumerics).
            3. Token-based match for single-word keywords.
        
        Returns:
            bool: True if investor belongs to HARVHUB, False otherwise
        """
        if not isinstance(investor_data, dict):
            return False
        
        # Fields to check for grid trader indicators
        fields_to_check = [
            'invested_with',
            'strategy',
            'type',
            'category',
            'investment_type',
            'trader_type',
            'description',
            'notes',
            'tags'
        ]
        
        # Grid-related regex patterns (match anywhere in the cleaned value)
        grid_patterns = [
            r'grid',
            r'grid_trade',
            r'grid_trades',
            r'dynamic_grid',
            r'dynamic_grid_trade',
            r'dynamic_grid_trades',
            r'grid[-_]?trade',
            r'grid[-_]?trades',
            r'dynamic[-_]?grid',
            r'^grid',
            r'grid$',
        ]
        
        # Additional HARVHUB keyword regex patterns
        # Use \W* (any non-word chars) between words so " ", "_", "-", or
        # no separator at all will all match.
        harvhub_patterns = [
            r'boom\W*and\W*crash',
            r'trailing\W*spike',
            r'trailing\W*price',
            r'stalking\W*price',
            r'stalking\W*spike',
        ]
        
        # Compile regex patterns for case-insensitive matching
        compiled_grid_patterns = [re.compile(p, re.IGNORECASE) for p in grid_patterns]
        compiled_harvhub_patterns = [re.compile(p, re.IGNORECASE) for p in harvhub_patterns]
        
        # Normalized (squashed) keyword lists — strip all non-alphanumerics
        # e.g. "boom and crash", "boom_and_crash", "boomandcrash" all become
        # "boomandcrash" and match.
        harvhub_normalized = [
            'boomandcrash',
            'trailingspike',
            'trailingprice',
            'stalkingprice',
            'stalkingspike',
        ]
        
        grid_keywords = [
            'grid', 'gridtrade', 'grid_trade', 'gridtrades', 'grid_trades',
            'dynamic_grid', 'dynamicgrid', 'dynamic_grid_trade', 'dynamicgridtrade',
            'gridding', 'gridder', 'gridbot', 'grid_bot', 'gridrobot'
        ]
        grid_normalized = [re.sub(r'[^a-z0-9]', '', kw.lower()) for kw in grid_keywords]
        grid_normalized = [kw for kw in grid_normalized if kw]
        
        # Check all relevant fields
        for field in fields_to_check:
            value = investor_data.get(field, '')
            
            # Skip if value is not a string or is empty
            if not isinstance(value, str) or not value.strip():
                continue
            
            # Clean and normalize the value
            clean_value = value.strip().lower()
            
            # ---- 1) Regex match on FULL cleaned value (multi-word phrases) ----
            for pattern in compiled_grid_patterns:
                if pattern.search(clean_value):
                    return True
            for pattern in compiled_harvhub_patterns:
                if pattern.search(clean_value):
                    return True
            
            # ---- 2) Squashed normalized substring match ----
            squashed = re.sub(r'[^a-z0-9]', '', clean_value)
            for kw in harvhub_normalized:
                if kw in squashed:
                    return True
            for kw in grid_normalized:
                if kw in squashed:
                    return True
            
            # ---- 3) Token-based match (single-word keywords) ----
            delimiters = [' ', '_', '-', '.', ',', ';', '|', '/', '\\', ':', ';']
            parts = [clean_value]
            for delimiter in delimiters:
                new_parts = []
                for part in parts:
                    new_parts.extend(part.split(delimiter))
                parts = new_parts
            
            for part in parts:
                if not part:
                    continue
                if part in grid_keywords:
                    return True
                if part in harvhub_normalized:
                    return True
        
        return False
    
    def validate_and_cleanup(invharv_data, harvhub_data, all_data, category_name, file_type, stats_section):
        """
        Validate and cleanup investor distribution.
        """
        print(f"\n   🔍 Validating and cleaning up {category_name} {file_type}...")
        print("-"*40)
        
        cleanup_stats = {
            "removed_from_invharv": 0,
            "removed_from_harvhub": 0,
            "invalid_grid_in_invharv": [],
            "invalid_non_grid_in_harvhub": [],
            "moved_to_correct_file": 0
        }
        
        # Create working copies
        working_invharv = invharv_data.copy() if invharv_data else {}
        working_harvhub = harvhub_data.copy() if harvhub_data else {}
        working_all = all_data.copy() if all_data else {}
        
        # Track all investor IDs
        invharv_ids = set(working_invharv.keys())
        harvhub_ids = set(working_harvhub.keys())
        
        print(f"      📊 Before cleanup:")
        print(f"         INVHARV: {len(invharv_ids):,} investors")
        print(f"         HARVHUB: {len(harvhub_ids):,} investors")
        
        # STEP 1: Check INVHARV for grid traders (or HARVHUB keyword matches)
        invalid_in_invharv = []
        for inv_id in list(invharv_ids):
            investor_data = working_all.get(inv_id, {})
            if not investor_data:
                investor_data = working_invharv.get(inv_id, {})
            
            if is_grid_trader(investor_data):
                invalid_in_invharv.append(inv_id)
                cleanup_stats["invalid_grid_in_invharv"].append(inv_id)
                
                if inv_id in harvhub_ids:
                    del working_invharv[inv_id]
                    cleanup_stats["removed_from_invharv"] += 1
                    print(f"         🗑️  Removed grid trader {inv_id} from INVHARV (already in HARVHUB)")
                else:
                    working_harvhub[inv_id] = working_invharv[inv_id].copy()
                    del working_invharv[inv_id]
                    cleanup_stats["removed_from_invharv"] += 1
                    cleanup_stats["moved_to_correct_file"] += 1
                    print(f"         📦 Moved grid trader {inv_id} from INVHARV to HARVHUB")
        
        # STEP 2: Check HARVHUB for non-grid traders
        invalid_in_harvhub = []
        for hub_id in list(harvhub_ids):
            investor_data = working_all.get(hub_id, {})
            if not investor_data:
                investor_data = working_harvhub.get(hub_id, {})
            
            if not is_grid_trader(investor_data):
                invalid_in_harvhub.append(hub_id)
                cleanup_stats["invalid_non_grid_in_harvhub"].append(hub_id)
                
                if hub_id in invharv_ids:
                    del working_harvhub[hub_id]
                    cleanup_stats["removed_from_harvhub"] += 1
                    print(f"         🗑️  Removed non-grid trader {hub_id} from HARVHUB (already in INVHARV)")
                else:
                    working_invharv[hub_id] = working_harvhub[hub_id].copy()
                    del working_harvhub[hub_id]
                    cleanup_stats["removed_from_harvhub"] += 1
                    cleanup_stats["moved_to_correct_file"] += 1
                    print(f"         📦 Moved non-grid trader {hub_id} from HARVHUB to INVHARV")
        
        # STEP 3: Update ALL with cleaned data
        for inv_id, inv_data in working_invharv.items():
            if inv_id in working_all:
                working_all[inv_id], _, _ = merge_investor_records(
                    {inv_id: inv_data},
                    {inv_id: working_all[inv_id]},
                    "INVHARV -> ALL"
                )
                working_all[inv_id] = working_all[inv_id][inv_id]
            else:
                working_all[inv_id] = inv_data.copy()
        
        for hub_id, hub_data in working_harvhub.items():
            if hub_id in working_all:
                working_all[hub_id], _, _ = merge_investor_records(
                    {hub_id: hub_data},
                    {hub_id: working_all[hub_id]},
                    "HARVHUB -> ALL"
                )
                working_all[hub_id] = working_all[hub_id][hub_id]
            else:
                working_all[hub_id] = hub_data.copy()
        
        print(f"\n      📊 After cleanup:")
        print(f"         INVHARV: {len(working_invharv):,} investors")
        print(f"         HARVHUB: {len(working_harvhub):,} investors")
        print(f"         ALL: {len(working_all):,} investors")
        print(f"      🗑️  Removed from INVHARV: {cleanup_stats['removed_from_invharv']}")
        print(f"      🗑️  Removed from HARVHUB: {cleanup_stats['removed_from_harvhub']}")
        print(f"      📦 Moved to correct file: {cleanup_stats['moved_to_correct_file']}")
        
        # Update stats
        stats_section["cleanup"]["removed_from_invharv"] = cleanup_stats["removed_from_invharv"]
        stats_section["cleanup"]["removed_from_harvhub"] = cleanup_stats["removed_from_harvhub"]
        stats_section["cleanup"]["invalid_grid_in_invharv"] = cleanup_stats["invalid_grid_in_invharv"]
        stats_section["cleanup"]["invalid_non_grid_in_harvhub"] = cleanup_stats["invalid_non_grid_in_harvhub"]
        
        return working_invharv, working_harvhub, working_all, cleanup_stats
    
    def process_category(all_data, invharv_data, harvhub_data, category_name, file_type):
        """
        Process a category (fetched or updated) for sync and distribution.
        """
        print(f"\n📊 Processing {category_name} {file_type}...")
        print("-"*40)
        
        category_stats = {
            "existing_processed": 0,
            "fields_filled": 0,
            "fields_updated": 0,
            "grid_moved_to_harvhub": 0,
            "non_grid_moved_to_invharv": 0,
            "new_grid_copied": 0,
            "new_grid_ids": [],
            "new_non_grid_copied": 0,
            "new_non_grid_ids": []
        }
        
        working_all = all_data.copy() if all_data else {}
        working_invharv = {}
        working_harvhub = {}
        
        all_investor_ids = set(working_all.keys())
        invharv_ids = set(invharv_data.keys()) if invharv_data else set()
        harvhub_ids = set(harvhub_data.keys()) if harvhub_data else set()
        
        print(f"   📋 ALL investors: {len(working_all):,}")
        print(f"   📋 INVHARV investors: {len(invharv_ids):,}")
        print(f"   📋 HARVHUB investors: {len(harvhub_ids):,}")
        
        # PART 1: SYNC AND FILTER EXISTING INVESTORS
        print(f"\n   🔄 Syncing and filtering existing investors...")
        
        for inv_id, investor_data in working_all.items():
            if not isinstance(investor_data, dict):
                continue
            
            is_grid = is_grid_trader(investor_data)
            in_invharv = inv_id in invharv_ids
            in_harvhub = inv_id in harvhub_ids
            
            invharv_record = invharv_data.get(inv_id, {}) if invharv_data else {}
            harvhub_record = harvhub_data.get(inv_id, {}) if harvhub_data else {}
            
            all_fields = count_non_empty_fields(investor_data)
            inv_fields = count_non_empty_fields(invharv_record)
            hub_fields = count_non_empty_fields(harvhub_record)
            
            base_record = investor_data.copy()
            
            if inv_fields > all_fields:
                base_record, _, _ = merge_investor_records(
                    {inv_id: invharv_record}, 
                    {inv_id: base_record}, 
                    "INVHARV -> BASE"
                )
                base_record = base_record[inv_id]
            
            if hub_fields > all_fields:
                base_record, _, _ = merge_investor_records(
                    {inv_id: harvhub_record}, 
                    {inv_id: base_record}, 
                    "HARVHUB -> BASE"
                )
                base_record = base_record[inv_id]
            
            working_all[inv_id] = base_record.copy()
            
            if is_grid:
                working_harvhub[inv_id] = base_record.copy()
                category_stats["grid_moved_to_harvhub"] += 1
                print(f"      ➡️  Grid trader {inv_id} -> HARVHUB")
            else:
                working_invharv[inv_id] = base_record.copy()
                category_stats["non_grid_moved_to_invharv"] += 1
                print(f"      ➡️  Non-grid {inv_id} -> INVHARV")
            
            category_stats["existing_processed"] += 1
            
            if invharv_record:
                invharv_merged, missing, updated = merge_investor_records(
                    {inv_id: base_record},
                    {inv_id: invharv_record},
                    "BASE -> INVHARV"
                )
                category_stats["fields_filled"] += missing
                category_stats["fields_updated"] += updated
        
        # PART 2: HANDLE NEW INVESTORS
        existing_in_sources = set(working_invharv.keys()) | set(working_harvhub.keys())
        new_investors = all_investor_ids - existing_in_sources
        
        if new_investors:
            print(f"\n   📦 Distributing {len(new_investors):,} new investors...")
            
            for inv_id in new_investors:
                investor_data = working_all.get(inv_id, {})
                
                if not investor_data:
                    continue
                
                if is_grid_trader(investor_data):
                    working_harvhub[inv_id] = investor_data.copy()
                    category_stats["new_grid_copied"] += 1
                    category_stats["new_grid_ids"].append(inv_id)
                    print(f"      ➡️  New grid trader {inv_id} -> HARVHUB")
                else:
                    working_invharv[inv_id] = investor_data.copy()
                    category_stats["new_non_grid_copied"] += 1
                    category_stats["new_non_grid_ids"].append(inv_id)
                    print(f"      ➡️  New non-grid {inv_id} -> INVHARV")
        
        updated_all = working_all.copy()
        
        return working_invharv, working_harvhub, updated_all, category_stats
    
    def sync_fetched_to_updated(fetched_invharv, fetched_harvhub, updated_invharv, updated_harvhub):
        """
        Sync data from fetched files to updated files.
        FETCHED data takes precedence over UPDATED data.
        """
        print("\n🔄 SYNCING FETCHED → UPDATED (FETCHED TAKES PRECEDENCE)")
        print("-"*40)
        
        sync_stats = {
            "records_updated": 0,
            "fields_synced": 0,
            "records_added": 0,
            "field_changes": {}
        }
        
        # Sync INVHARV fetched → INVHARV updated
        print("\n   📤 Syncing INVHARV fetched → INVHARV updated...")
        updated_invharv_working = updated_invharv.copy() if updated_invharv else {}
        
        for inv_id, fetched_record in fetched_invharv.items():
            if inv_id in updated_invharv_working:
                # Update existing record with fetched data (FETCHED takes precedence)
                updated_record = updated_invharv_working[inv_id]
                fields_changed = 0
                changed_fields = []
                
                for field, value in fetched_record.items():
                    if field == 'id':
                        continue
                    # Fetched data overrides updated data
                    if field not in updated_record or updated_record[field] != value:
                        updated_record[field] = value
                        fields_changed += 1
                        changed_fields.append(field)
                
                if fields_changed > 0:
                    updated_invharv_working[inv_id] = updated_record
                    sync_stats["records_updated"] += 1
                    sync_stats["fields_synced"] += fields_changed
                    sync_stats["field_changes"][f"INVHARV_{inv_id}"] = {
                        'fields': changed_fields,
                        'count': fields_changed
                    }
                    print(f"      ✅ Updated investor {inv_id} in INVHARV updated ({fields_changed} fields)")
            else:
                # Add new record from fetched
                updated_invharv_working[inv_id] = fetched_record.copy()
                sync_stats["records_added"] += 1
                fields_count = len(fetched_record) - 1
                sync_stats["fields_synced"] += fields_count
                sync_stats["field_changes"][f"INVHARV_{inv_id}"] = {
                    'fields': list(fetched_record.keys()),
                    'count': fields_count,
                    'status': 'added'
                }
                print(f"      ➕ Added investor {inv_id} to INVHARV updated ({fields_count} fields)")
        
        # Sync HARVHUB fetched → HARVHUB updated
        print("\n   📤 Syncing HARVHUB fetched → HARVHUB updated...")
        updated_harvhub_working = updated_harvhub.copy() if updated_harvhub else {}
        
        for hub_id, fetched_record in fetched_harvhub.items():
            if hub_id in updated_harvhub_working:
                # Update existing record with fetched data
                updated_record = updated_harvhub_working[hub_id]
                fields_changed = 0
                changed_fields = []
                
                for field, value in fetched_record.items():
                    if field == 'id':
                        continue
                    if field not in updated_record or updated_record[field] != value:
                        updated_record[field] = value
                        fields_changed += 1
                        changed_fields.append(field)
                
                if fields_changed > 0:
                    updated_harvhub_working[hub_id] = updated_record
                    sync_stats["records_updated"] += 1
                    sync_stats["fields_synced"] += fields_changed
                    sync_stats["field_changes"][f"HARVHUB_{hub_id}"] = {
                        'fields': changed_fields,
                        'count': fields_changed
                    }
                    print(f"      ✅ Updated investor {hub_id} in HARVHUB updated ({fields_changed} fields)")
            else:
                # Add new record from fetched
                updated_harvhub_working[hub_id] = fetched_record.copy()
                sync_stats["records_added"] += 1
                fields_count = len(fetched_record) - 1
                sync_stats["fields_synced"] += fields_count
                sync_stats["field_changes"][f"HARVHUB_{hub_id}"] = {
                    'fields': list(fetched_record.keys()),
                    'count': fields_count,
                    'status': 'added'
                }
                print(f"      ➕ Added investor {hub_id} to HARVHUB updated ({fields_count} fields)")
        
        print(f"\n   📊 Sync summary:")
        print(f"      Records updated: {sync_stats['records_updated']:,}")
        print(f"      Records added: {sync_stats['records_added']:,}")
        print(f"      Fields synced: {sync_stats['fields_synced']:,}")
        
        return updated_invharv_working, updated_harvhub_working, sync_stats
    
    try:
        # ============================================
        # LOAD ALL FILES
        # ============================================
        
        print("\n📂 Loading files...")
        print("-"*40)
        
        # Load fetched files
        all_fetched = safe_json_load(ALL_FETCHED_INVESTORS)
        invharv_fetched = safe_json_load(INVHARV_FETCHED_INVESTORS)
        harvhub_fetched = safe_json_load(HARVHUB_FETCHED_INVESTORS)
        
        print(f"   ✅ Loaded ALL fetched: {len(all_fetched):,} records")
        print(f"   ✅ Loaded INVHARV fetched: {len(invharv_fetched):,} records")
        print(f"   ✅ Loaded HARVHUB fetched: {len(harvhub_fetched):,} records")
        
        # Load updated files
        all_updated = safe_json_load(ALL_UPDATED_INVESTORS)
        invharv_updated = safe_json_load(INVHARV_UPDATED_INVESTORS)
        harvhub_updated = safe_json_load(HARVHUB_UPDATED_INVESTORS)
        
        print(f"   ✅ Loaded ALL updated: {len(all_updated):,} records")
        print(f"   ✅ Loaded INVHARV updated: {len(invharv_updated):,} records")
        print(f"   ✅ Loaded HARVHUB updated: {len(harvhub_updated):,} records")
        
        # ============================================
        # PROCESS FETCHED FILES
        # ============================================
        
        print("\n" + "="*70)
        print("STEP 1: PROCESSING FETCHED FILES".center(70))
        print("="*70)
        
        updated_invharv_fetched, updated_harvhub_fetched, updated_all_fetched, fetched_stats = process_category(
            all_fetched, invharv_fetched, harvhub_fetched, "FETCHED", "fetched"
        )
        
        stats["fetched"]["existing_investors"]["processed"] = fetched_stats["existing_processed"]
        stats["fetched"]["existing_investors"]["fields_filled"] = fetched_stats["fields_filled"]
        stats["fetched"]["existing_investors"]["fields_updated"] = fetched_stats["fields_updated"]
        stats["fetched"]["grid_traders_moved_to_harvhub"] = fetched_stats["grid_moved_to_harvhub"]
        stats["fetched"]["non_grid_traders_moved_to_invharv"] = fetched_stats["non_grid_moved_to_invharv"]
        stats["fetched"]["new_grid_traders"]["copied_to_harvhub"] = fetched_stats["new_grid_copied"]
        stats["fetched"]["new_grid_traders"]["ids"] = fetched_stats["new_grid_ids"]
        stats["fetched"]["new_non_grid_traders"]["copied_to_invharv"] = fetched_stats["new_non_grid_copied"]
        stats["fetched"]["new_non_grid_traders"]["ids"] = fetched_stats["new_non_grid_ids"]
        
        # ============================================
        # VALIDATE AND CLEANUP FETCHED FILES
        # ============================================
        
        cleaned_invharv_fetched, cleaned_harvhub_fetched, cleaned_all_fetched, fetched_cleanup = validate_and_cleanup(
            updated_invharv_fetched, updated_harvhub_fetched, updated_all_fetched, 
            "FETCHED", "fetched", stats["fetched"]
        )
        
        # ============================================
        # PROCESS UPDATED FILES (USING FETCHED AS SOURCE)
        # ============================================
        
        print("\n" + "="*70)
        print("STEP 2: PROCESSING UPDATED FILES".center(70))
        print("="*70)
        
        # Process updated files using fetched data as the source
        updated_invharv_updated, updated_harvhub_updated, updated_all_updated, updated_stats = process_category(
            all_updated, invharv_updated, harvhub_updated, "UPDATED", "updated"
        )
        
        stats["updated"]["existing_investors"]["processed"] = updated_stats["existing_processed"]
        stats["updated"]["existing_investors"]["fields_filled"] = updated_stats["fields_filled"]
        stats["updated"]["existing_investors"]["fields_updated"] = updated_stats["fields_updated"]
        stats["updated"]["grid_traders_moved_to_harvhub"] = updated_stats["grid_moved_to_harvhub"]
        stats["updated"]["non_grid_traders_moved_to_invharv"] = updated_stats["non_grid_moved_to_invharv"]
        stats["updated"]["new_grid_traders"]["copied_to_harvhub"] = updated_stats["new_grid_copied"]
        stats["updated"]["new_grid_traders"]["ids"] = updated_stats["new_grid_ids"]
        stats["updated"]["new_non_grid_traders"]["copied_to_invharv"] = updated_stats["new_non_grid_copied"]
        stats["updated"]["new_non_grid_traders"]["ids"] = updated_stats["new_non_grid_ids"]
        
        # ============================================
        # VALIDATE AND CLEANUP UPDATED FILES
        # ============================================
        
        cleaned_invharv_updated, cleaned_harvhub_updated, cleaned_all_updated, updated_cleanup = validate_and_cleanup(
            updated_invharv_updated, updated_harvhub_updated, updated_all_updated,
            "UPDATED", "updated", stats["updated"]
        )
        
        # ============================================
        # SYNC FETCHED → UPDATED (FETCHED TAKES PRECEDENCE)
        # ============================================
        
        print("\n" + "="*70)
        print("STEP 3: SYNCING FETCHED → UPDATED (FETCHED PRIORITY)".center(70))
        print("="*70)
        
        synced_invharv_updated, synced_harvhub_updated, sync_stats = sync_fetched_to_updated(
            cleaned_invharv_fetched, cleaned_harvhub_fetched, 
            cleaned_invharv_updated, cleaned_harvhub_updated
        )
        
        stats["sync_from_fetched_to_updated"] = sync_stats
        
        # ============================================
        # UPDATE ALL_UPDATED WITH SYNCED DATA
        # ============================================
        
        print("\n🔄 Updating ALL_UPDATED with synced data...")
        print("-"*40)
        
        # Create final ALL_UPDATED by merging synced invharv and harvhub
        final_all_updated = {}
        
        # Add all INVHARV updated records
        for inv_id, inv_data in synced_invharv_updated.items():
            final_all_updated[inv_id] = inv_data.copy()
        
        # Add all HARVHUB updated records
        for hub_id, hub_data in synced_harvhub_updated.items():
            if hub_id in final_all_updated:
                # Merge if exists
                final_all_updated[hub_id], _, _ = merge_investor_records(
                    {hub_id: hub_data},
                    {hub_id: final_all_updated[hub_id]},
                    "HARVHUB -> ALL_UPDATED"
                )
                final_all_updated[hub_id] = final_all_updated[hub_id][hub_id]
            else:
                final_all_updated[hub_id] = hub_data.copy()
        
        print(f"   ✅ Created ALL_UPDATED with {len(final_all_updated):,} records")
        
        # ============================================
        # SAVE ALL FILES
        # ============================================
        
        print("\n💾 Saving files...")
        print("-"*40)
        
        # Save fetched files
        if safe_json_write(ALL_FETCHED_INVESTORS, cleaned_all_fetched):
            print(f"   ✅ Saved ALL fetched: {len(cleaned_all_fetched):,} records")
            stats["fetched"]["all_count"] = len(cleaned_all_fetched)
        
        if safe_json_write(INVHARV_FETCHED_INVESTORS, cleaned_invharv_fetched):
            print(f"   ✅ Saved INVHARV fetched: {len(cleaned_invharv_fetched):,} records")
            stats["fetched"]["invharv_count"] = len(cleaned_invharv_fetched)
        
        if safe_json_write(HARVHUB_FETCHED_INVESTORS, cleaned_harvhub_fetched):
            print(f"   ✅ Saved HARVHUB fetched: {len(cleaned_harvhub_fetched):,} records")
            stats["fetched"]["harvhub_count"] = len(cleaned_harvhub_fetched)
        
        # Save updated files (using synced data)
        if safe_json_write(ALL_UPDATED_INVESTORS, final_all_updated):
            print(f"   ✅ Saved ALL updated: {len(final_all_updated):,} records")
            stats["updated"]["all_count"] = len(final_all_updated)
        
        if safe_json_write(INVHARV_UPDATED_INVESTORS, synced_invharv_updated):
            print(f"   ✅ Saved INVHARV updated: {len(synced_invharv_updated):,} records")
            stats["updated"]["invharv_count"] = len(synced_invharv_updated)
        
        if safe_json_write(HARVHUB_UPDATED_INVESTORS, synced_harvhub_updated):
            print(f"   ✅ Saved HARVHUB updated: {len(synced_harvhub_updated):,} records")
            stats["updated"]["harvhub_count"] = len(synced_harvhub_updated)
        
        # ============================================
        # SUMMARY
        # ============================================
        
        stats["processing_success"] = True
        
        print("\n" + "="*70)
        print(f"SYNC AND DISTRIBUTION SUMMARY".center(70))
        print("="*70)
        
        print(f"\n📥 FETCHED FILES SUMMARY:")
        print(f"   🔄 Existing investors processed: {stats['fetched']['existing_investors']['processed']:,}")
        print(f"      📝 Missing fields filled: {stats['fetched']['existing_investors']['fields_filled']:,}")
        print(f"      🔄 Fields updated: {stats['fetched']['existing_investors']['fields_updated']:,}")
        print(f"   🔀 Grid traders moved to HARVHUB: {stats['fetched']['grid_traders_moved_to_harvhub']:,}")
        print(f"   🔀 Non-grid traders moved to INVHARV: {stats['fetched']['non_grid_traders_moved_to_invharv']:,}")
        print(f"   📦 New grid traders copied to HARVHUB: {stats['fetched']['new_grid_traders']['copied_to_harvhub']:,}")
        if stats['fetched']['new_grid_traders']['ids']:
            print(f"      IDs: {', '.join(stats['fetched']['new_grid_traders']['ids'][:10])}")
            if len(stats['fetched']['new_grid_traders']['ids']) > 10:
                print(f"      ... and {len(stats['fetched']['new_grid_traders']['ids']) - 10} more")
        print(f"   📦 New non-grid traders copied to INVHARV: {stats['fetched']['new_non_grid_traders']['copied_to_invharv']:,}")
        if stats['fetched']['new_non_grid_traders']['ids']:
            print(f"      IDs: {', '.join(stats['fetched']['new_non_grid_traders']['ids'][:10])}")
            if len(stats['fetched']['new_non_grid_traders']['ids']) > 10:
                print(f"      ... and {len(stats['fetched']['new_non_grid_traders']['ids']) - 10} more")
        
        print(f"\n   🧹 CLEANUP SUMMARY (FETCHED):")
        print(f"      🗑️  Removed from INVHARV: {stats['fetched']['cleanup']['removed_from_invharv']}")
        print(f"      🗑️  Removed from HARVHUB: {stats['fetched']['cleanup']['removed_from_harvhub']}")
        
        print(f"\n   📊 Final counts:")
        print(f"      ALL: {stats['fetched']['all_count']:,} investors")
        print(f"      INVHARV: {stats['fetched']['invharv_count']:,} investors")
        print(f"      HARVHUB: {stats['fetched']['harvhub_count']:,} investors")
        
        print(f"\n📤 UPDATED FILES SUMMARY:")
        print(f"   🔄 Existing investors processed: {stats['updated']['existing_investors']['processed']:,}")
        print(f"      📝 Missing fields filled: {stats['updated']['existing_investors']['fields_filled']:,}")
        print(f"      🔄 Fields updated: {stats['updated']['existing_investors']['fields_updated']:,}")
        print(f"   🔀 Grid traders moved to HARVHUB: {stats['updated']['grid_traders_moved_to_harvhub']:,}")
        print(f"   🔀 Non-grid traders moved to INVHARV: {stats['updated']['non_grid_traders_moved_to_invharv']:,}")
        print(f"   📦 New grid traders copied to HARVHUB: {stats['updated']['new_grid_traders']['copied_to_harvhub']:,}")
        if stats['updated']['new_grid_traders']['ids']:
            print(f"      IDs: {', '.join(stats['updated']['new_grid_traders']['ids'][:10])}")
            if len(stats['updated']['new_grid_traders']['ids']) > 10:
                print(f"      ... and {len(stats['updated']['new_grid_traders']['ids']) - 10} more")
        print(f"   📦 New non-grid traders copied to INVHARV: {stats['updated']['new_non_grid_traders']['copied_to_invharv']:,}")
        if stats['updated']['new_non_grid_traders']['ids']:
            print(f"      IDs: {', '.join(stats['updated']['new_non_grid_traders']['ids'][:10])}")
            if len(stats['updated']['new_non_grid_traders']['ids']) > 10:
                print(f"      ... and {len(stats['updated']['new_non_grid_traders']['ids']) - 10} more")
        
        print(f"\n   🧹 CLEANUP SUMMARY (UPDATED):")
        print(f"      🗑️  Removed from INVHARV: {stats['updated']['cleanup']['removed_from_invharv']}")
        print(f"      🗑️  Removed from HARVHUB: {stats['updated']['cleanup']['removed_from_harvhub']}")
        
        print(f"\n   📊 Final counts:")
        print(f"      ALL: {stats['updated']['all_count']:,} investors")
        print(f"      INVHARV: {stats['updated']['invharv_count']:,} investors")
        print(f"      HARVHUB: {stats['updated']['harvhub_count']:,} investors")
        
        print(f"\n🔄 FETCHED → UPDATED SYNC SUMMARY:")
        print(f"   📝 Records updated: {stats['sync_from_fetched_to_updated']['records_updated']:,}")
        print(f"   ➕ Records added: {stats['sync_from_fetched_to_updated']['records_added']:,}")
        print(f"   📊 Fields synced: {stats['sync_from_fetched_to_updated']['fields_synced']:,}")
        
        if stats["warnings"]:
            print(f"\n⚠️ WARNINGS ({len(stats['warnings'])}):")
            for warning in stats["warnings"]:
                print(f"   - {warning}")
        
        if stats["errors"]:
            print(f"\n❌ ERRORS ({len(stats['errors'])}):")
            for error in stats["errors"]:
                print(f"   - {error}")
        
        print(f"\n✅ Status : {'SUCCESS' if stats['processing_success'] else 'FAILED'}")
        print(f"🕐 Time   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*70)
        
        return stats
        
    except Exception as e:
        print(f"\n{'='*70}")
        print(f"CRITICAL ERROR".center(70))
        print(f"{'='*70}")
        print(f"  Error Type : {type(e).__name__}")
        print(f"  Message    : {str(e)}")
        print(f"{'='*70}")
        
        import traceback
        print(f"\n📜 Full Traceback:")
        traceback.print_exc()
        
        stats["processing_success"] = False
        stats["errors"].append(f"Critical error: {str(e)}")
        return stats   
 
def fetch_investors():
    """Stream all results directly to file - VPS-based identification with followers fallback"""
    
    # ── Diagnostic helper: time every DB call + pass fast-completion hints ──
    def _timed_db_call(label, query, params=None, wait_hint=None):
        import time as _time
        t0 = _time.perf_counter()
        if wait_hint is not None:
            try:
                result = db.execute_query(query, params=params, wait_hint=wait_hint)
            except TypeError:
                print(f"    ℹ️  [{label}] wrapper does not accept wait_hint — using default wait")
                result = db.execute_query(query, params=params)
        else:
            result = db.execute_query(query, params=params)
        elapsed = _time.perf_counter() - t0
        print(f"    ⏱️  [{label}] took {elapsed:.2f}s")
        return result, elapsed
    
    def _diag_dump(label, result):
        print(f"    🔎 [DIAG] {label} response dump:")
        if not isinstance(result, dict):
            print(f"        ⚠️ result is not a dict — type = {type(result).__name__}")
            print(f"        ⚠️ repr(result) = {repr(result)[:400]}")
            return
        print(f"        status  : {result.get('status')!r}")
        print(f"        message : {result.get('message')!r}")
        results_val = result.get('results')
        if results_val is None:
            print(f"        results : None (key missing or null)")
        elif not isinstance(results_val, list):
            print(f"        results : not a list — type = {type(results_val).__name__}")
            print(f"        results : repr = {repr(results_val)[:400]}")
        else:
            print(f"        results : list of {len(results_val)} item(s)")
            if results_val:
                first = results_val[0]
                print(f"        first item type: {type(first).__name__}")
                if isinstance(first, dict):
                    keys = list(first.keys())
                    print(f"        first item keys: {keys[:20]}{'...' if len(keys) > 20 else ''}")
                    print(f"        first item sample: { {k: first.get(k) for k in keys[:5]} }")
                else:
                    print(f"        first item repr: {repr(first)[:300]}")
        other_keys = [k for k in result.keys() if k not in ('status', 'message', 'results')]
        if other_keys:
            print(f"        other top-level keys: {other_keys}")
    
    FAST_HINT = {'signal': 'js-display', 'timeout': 8, 'expect_empty': True}
    BULK_HINT = {'signal': 'js-display', 'timeout': 15, 'expect_empty': False}
    
    def _normalize_keys(row):
        if not isinstance(row, dict):
            return row
        normalized = {}
        for k, v in row.items():
            if isinstance(k, str):
                normalized[k.strip().lower()] = v
            else:
                normalized[k] = v
        return normalized
    
    def _coerce_int(value):
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        try:
            s = str(value).strip()
            if not s or s.lower() in ('null', 'none', 'nan'):
                return None
            if '.' in s:
                return int(float(s))
            return int(s)
        except (ValueError, TypeError):
            return None
    
    def _pick_first_key(row, *candidate_keys):
        if not isinstance(row, dict):
            return None
        lowered = { (k.strip().lower() if isinstance(k, str) else k): v
                    for k, v in row.items() }
        for key in candidate_keys:
            if key is None:
                continue
            lk = key.strip().lower()
            if lk in lowered and lowered[lk] is not None:
                return lowered[lk]
        return None
    
    def get_local_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip_address = s.getsockname()[0]
            s.close()
            print(f"  🌐 Local IP Address detected: {ip_address}")
            return ip_address
        except Exception as e:
            print(f"    Error getting IP address: {e}")
            return None
    
    def get_vscode_machine_id():
        try:
            appdata = os.environ.get("APPDATA", "")
            if not appdata:
                return None
            global_storage = os.path.join(appdata, "Code", "User", "globalStorage")
            storage_json_path = os.path.join(global_storage, "storage.json")
            if os.path.exists(storage_json_path):
                with open(storage_json_path, 'r', encoding='utf-8') as f:
                    storage_data = json.load(f)
                    for key in ['telemetry.machineId', 'machineId', 'machine.id', 'vscode.machineId']:
                        if key in storage_data and storage_data[key]:
                            print(f"  🖥️ VS Code Machine ID detected: {storage_data[key][:32]}...")
                            return storage_data[key]
            return None
        except Exception as e:
            print(f"    Error getting VS Code ID: {e}")
            return None
    
    def parse_json_safe(value):
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            return None
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            return repair_json_field(value)
        except Exception:
            pass
        try:
            import ast
            return ast.literal_eval(value)
        except Exception:
            pass
        return value
    
    def repair_json_field(value):
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not (value.startswith('{') or value.startswith('[')):
            if (value.startswith('"{') and value.endswith('}"')) or \
               (value.startswith("'{") and value.endswith("}'")) or \
               (value.startswith('"[') and value.endswith(']"')) or \
               (value.startswith("'[") and value.endswith("]'")) :
                value = value[1:-1]
            if not (value.strip().startswith('{') or value.strip().startswith('[')):
                return value
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass
        try:
            fixed = value.replace('\\"', '"').replace("\\'", "'")
            fixed = re.sub(r'(?<!")\n(?!")', '\\n', fixed)
            fixed = re.sub(r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', fixed)
            fixed = fixed.replace("'", '"')
            fixed = re.sub(r',\s*}', '}', fixed)
            fixed = re.sub(r',\s*\]', ']', fixed)
            if fixed.startswith('\ufeff'):
                fixed = fixed[1:]
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass
        try:
            import ast
            result = ast.literal_eval(value)
            if isinstance(result, (dict, list, tuple)):
                return result
        except (ValueError, SyntaxError):
            pass
        try:
            unescaped = value
            for _ in range(5):
                if '\\"' in unescaped:
                    unescaped = unescaped.replace('\\"', '"')
                elif "\\'" in unescaped:
                    unescaped = unescaped.replace("\\'", "'")
                else:
                    break
            if unescaped != value:
                return json.loads(unescaped)
        except json.JSONDecodeError:
            pass
        try:
            if (value.startswith('{') and value.endswith('}')) or (value.startswith('[') and value.endswith(']')):
                fixed = value.replace(': "NULL"', ': null').replace(': NULL', ': null')
                fixed = fixed.replace('"NULL"', 'null')
                fixed = fixed.replace(': "true"', ': true').replace(': "false"', ': false')
                fixed = fixed.replace('"true"', 'true').replace('"false"', 'false')
                fixed = re.sub(r'"(\d+\.\d+)"', r'\1', fixed)
                return json.loads(fixed)
        except json.JSONDecodeError:
            pass
        return value
    
    def denormalize_path_value(value, field_name):
        if value is None:
            return None
        if 'path' not in field_name.lower():
            return value
        if not isinstance(value, str):
            return value
        denormalized = value.replace('_', '\\')
        denormalized = re.sub(r'([A-Za-z]):\\', r'\1:\\', denormalized)
        denormalized = re.sub(r'([A-Za-z]):\\', r'\1:\\', denormalized)
        return denormalized
    
    def normalize_gmail_path(value):
        if value is None or not isinstance(value, str):
            return value
        if 'at\\gmail\\dot\\com' in value or 'at/gmail/dot/com' in value:
            if '\\at\\gmail\\dot\\com' in value:
                value = value.replace('\\at\\gmail\\dot\\com', '_at_gmail_dot_com')
            elif '/at/gmail/dot/com' in value:
                value = value.replace('/at/gmail/dot/com', '_at_gmail_dot_com')
            else:
                value = re.sub(r'[\\/]at[\\/]gmail[\\/]dot[\\/]com', '_at_gmail_dot_com', value)
        return value
    
    def safe_write_file(file_path, mode, content):
        max_retries = 3
        retry_delay = 1
        for attempt in range(max_retries):
            try:
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                if mode == 'w':
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                elif mode == 'a':
                    with open(file_path, 'a', encoding='utf-8') as f:
                        f.write(content)
                elif mode == 'overwrite':
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write('{\n')
                return True
            except PermissionError:
                print(f"    ⚠️ Permission denied (attempt {attempt+1}/{max_retries})")
                if attempt < max_retries - 1:
                    try:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                            print(f"       ✅ File deleted, retrying...")
                        time.sleep(retry_delay)
                        retry_delay *= 2
                    except Exception as delete_error:
                        print(f"       ❌ Could not delete file: {delete_error}")
                        time.sleep(retry_delay)
                        retry_delay *= 2
                else:
                    raise
        return False
    
    def move_temp_to_final(temp_file_path, final_file_path):
        try:
            os.makedirs(os.path.dirname(final_file_path), exist_ok=True)
            if os.path.exists(final_file_path):
                os.remove(final_file_path)
            shutil.move(temp_file_path, final_file_path)
            print(f"    ✅ Moved: {os.path.basename(temp_file_path)} → {os.path.basename(final_file_path)}")
            return True
        except Exception as e:
            print(f"    ❌ Error moving file: {str(e)}")
            return False
    
    # =========================================================================
    # STEP 1: Find the investor IDs associated with this computer
    # =========================================================================
    def find_investor_ids_for_this_computer(local_ip):
        investor_ids = set()
        matched_vps_user_id = None
        identification_method = None
        vps_row_existed = False
        vps_row_dump = None
        
        if not local_ip:
            print("  ⚠️ No local IP available for VPS matching")
            return [], None, None, False
        
        print(f"\n  🔍 Checking VPS table for IP: {local_ip}")
        vps_query = """
            SELECT id, user_id, vps_ip_address
            FROM vps
            WHERE vps_ip_address = %s
            LIMIT 1
        """
        vps_result, _ = _timed_db_call(
            "vps lookup", vps_query, [local_ip], wait_hint=FAST_HINT
        )
        
        if vps_result.get('status') == 'success':
            vps_rows = vps_result.get('results', [])
            if vps_rows and len(vps_rows) > 0:
                vps_row_existed = True
                raw_row = vps_rows[0]
                if isinstance(raw_row, dict):
                    print(f"    🔎 VPS row keys: {list(raw_row.keys())}")
                    print(f"    🔎 VPS row data: {raw_row}")
                else:
                    print(f"    🔎 VPS row (non-dict, {type(raw_row).__name__}): {repr(raw_row)[:300]}")
                normalized_row = _normalize_keys(raw_row) if isinstance(raw_row, dict) else {}
                vps_row_dump = normalized_row
                raw_user_id = _pick_first_key(
                    raw_row,
                    'user_id', 'userid', 'user-id', 'user id',
                    'uid', 'user', 'USER_ID', 'UserId',
                )
                print(f"    🔎 Resolved raw user_id value: {raw_user_id!r} "
                      f"(type={type(raw_user_id).__name__})")
                matched_vps_user_id = _coerce_int(raw_user_id)
                if matched_vps_user_id is not None:
                    investor_ids.add(matched_vps_user_id)
                    identification_method = 'vps_ip'
                    print(f"  ✅ VPS match found! user_id = {matched_vps_user_id}")
                else:
                    print(f"  ⚠️ VPS row found (id={normalized_row.get('id')}) "
                          f"but user_id is NULL/unparseable — nothing to fetch")
            else:
                print(f"  ℹ️ No VPS row with vps_ip_address = {local_ip}")
        else:
            print(f"  ⚠️ VPS query failed: {vps_result.get('message')}")
        
        if matched_vps_user_id is not None:
            print(f"\n  🔍 Fetching followers for owner_id = {matched_vps_user_id}")
            followers_query = """
                SELECT follower_id
                FROM vps_hosts_followers
                WHERE owner_id = %s
                  AND host_status = 'active'
            """
            followers_result, _ = _timed_db_call(
                "followers lookup", followers_query, [matched_vps_user_id],
                wait_hint=FAST_HINT,
            )
            if followers_result.get('status') == 'success':
                follower_rows = followers_result.get('results', [])
                for row in follower_rows:
                    fid = _pick_first_key(row, 'follower_id', 'followerid', 'follower id')
                    fid_int = _coerce_int(fid)
                    if fid_int is not None:
                        investor_ids.add(fid_int)
                print(f"  ✅ Found {len(follower_rows)} active follower(s)")
            else:
                print(f"  ⚠️ Followers query failed: {followers_result.get('message')}")
        
        return sorted(investor_ids), identification_method, matched_vps_user_id, vps_row_existed
    
    # =========================================================================
    # STEP 1b: Fetch DEFAULT_ACCOUNTMANAGEMENT from server_account
    #          and WRITE IT DIRECTLY TO THE FILE (global, not per-investor)
    # =========================================================================
    def fetch_and_save_default_accountmanagement(output_path):
        """
        Fetch accountmanagement_configs from server_account (single global row,
        NOT user/VPS-specific) and write it directly to `output_path` as a
        standalone JSON file.

        This is COMPLETELY SEPARATE from the `accountmanagement` table.
          * server_account.accountmanagement_configs → DEFAULT_ACCOUNTMANAGEMENT file
          * accountmanagement table                  → per-investor records
        They must never be mixed.
        """
        print(f"\n📝 [0b/6] Fetching server_account accountmanagement_configs → {output_path}")
        try:
            query = "SELECT accountmanagement_configs FROM server_account LIMIT 1"
            result, _ = _timed_db_call(
                "server_account accountmanagement_configs", query, None,
                wait_hint=FAST_HINT,
            )
            if result.get('status') != 'success' or not result.get('results'):
                print(f"  ⚠️ Could not fetch server_account accountmanagement_configs: "
                      f"{result.get('message')}")
                return False

            raw = _pick_first_key(
                result['results'][0],
                'accountmanagement_configs', 'accountmanagementconfigs',
                'accountmanagement configs', 'accountmanagement_config',
            )
            parsed = parse_json_safe(raw)
            if not isinstance(parsed, dict):
                print(f"  ⚠️ accountmanagement_configs parsed to non-dict "
                      f"({type(parsed).__name__}) — writing raw value anyway")
            else:
                print(f"  ✅ Loaded DEFAULT_ACCOUNTMANAGEMENT with {len(parsed)} top-level key(s): "
                      f"{', '.join(list(parsed.keys())[:8])}")

            # ── Write the parsed dict straight to the target file ──
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(parsed, f, indent=2, default=str)
            size = os.path.getsize(output_path)
            print(f"  💾 Wrote DEFAULT_ACCOUNTMANAGEMENT → {output_path} ({size:,} bytes)")
            return True

        except Exception as e:
            print(f"  ❌ Error fetching/writing DEFAULT_ACCOUNTMANAGEMENT: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    # =========================================================================
    # STEP 2: Build invested_with mapping for the given investor IDs
    # =========================================================================
    def fetch_invested_with_map(investor_ids):
        invested_map = {}
        pi_rows_map = {}
        if not investor_ids:
            return invested_map, pi_rows_map
        placeholders = ','.join(['%s'] * len(investor_ids))
        query = f"""
            SELECT pi.id, pi.investorid, pi.developerid, pi.programme_id,
                   pi.contract_duration, pi.developer_percentage, pi.investor_percentage,
                   pi.minimum_investment_amount, pi.maximum_investment_amount,
                   pi.invested_at, pi.status,
                   p.program_name
            FROM programme_investors pi
            LEFT JOIN programme p ON p.id = pi.programme_id
            WHERE pi.investorid IN ({placeholders})
        """
        result, _ = _timed_db_call(
            "programme_investors lookup", query, investor_ids,
            wait_hint=FAST_HINT,
        )
        if result.get('status') == 'success':
            for row in result.get('results', []):
                inv_id = _pick_first_key(row, 'investorid', 'investor_id', 'investor id')
                dev_id = _pick_first_key(row, 'developerid', 'developer_id', 'developer id')
                prog_name = _pick_first_key(row, 'program_name', 'programname', 'program name') or ''
                prog_id = _pick_first_key(row, 'programme_id', 'programmeid', 'programme id')
                if inv_id is None or dev_id is None:
                    continue
                inv_id = _coerce_int(inv_id)
                dev_id = _coerce_int(dev_id)
                if inv_id is None or dev_id is None:
                    continue
                key = f"{dev_id}_{prog_name}"
                invested_map.setdefault(inv_id, [])
                if key not in invested_map[inv_id]:
                    invested_map[inv_id].append(key)
                pi_rows_map[(inv_id, dev_id, prog_id)] = row
        return invested_map, pi_rows_map
    
    # =========================================================================
    # STEP 3: Fetch accountmanagement rows for investor+developer pairs
    #         (THIS IS THE `accountmanagement` TABLE — NOT server_account!)
    # =========================================================================
    def fetch_accountmanagement_map(investor_developer_pairs):
        am_map = {}
        if not investor_developer_pairs:
            return am_map
        conditions = []
        params = []
        for inv_id, dev_id in investor_developer_pairs:
            conditions.append("(investorid = %s AND developerid = %s)")
            params.extend([inv_id, dev_id])
        where_clause = " OR ".join(conditions)
        query = f"""
            SELECT *
            FROM accountmanagement
            WHERE {where_clause}
        """
        result, _ = _timed_db_call(
            "accountmanagement lookup", query, params,
            wait_hint=FAST_HINT,
        )
        if result.get('status') == 'success':
            for row in result.get('results', []):
                inv_id = _pick_first_key(row, 'investorid', 'investor_id', 'investor id')
                dev_id = _pick_first_key(row, 'developerid', 'developer_id', 'developer id')
                inv_int = _coerce_int(inv_id)
                dev_int = _coerce_int(dev_id)
                if inv_int is not None and dev_int is not None:
                    am_map[(inv_int, dev_int)] = row
        else:
            print(f"    ⚠️ accountmanagement query failed: {result.get('message')}")
        return am_map
    
    # =========================================================================
    # STEP 3b: Fetch server_account tier_limit
    # =========================================================================
    def fetch_server_tier_limit():
        print(f"\n📝 [2b/6] Fetching server_account tier_limit...")
        try:
            query = "SELECT tier_limit FROM server_account LIMIT 1"
            result, _ = _timed_db_call(
                "server_account tier_limit", query, None,
                wait_hint=FAST_HINT,
            )
            if result.get('status') == 'success' and result.get('results'):
                raw = _pick_first_key(
                    result['results'][0],
                    'tier_limit', 'tierlimit', 'tier limit',
                )
                parsed = parse_json_safe(raw)
                if isinstance(parsed, dict):
                    print(f"  ✅ Loaded {len(parsed)} tier(s): {', '.join(list(parsed.keys())[:5])}")
                    return parsed
                elif parsed is not None:
                    print(f"  ⚠️ tier_limit parsed to non-dict type: {type(parsed).__name__}")
                    return parsed
                else:
                    print(f"  ℹ️ tier_limit is empty/null")
                    return {}
            else:
                print(f"  ⚠️ Could not fetch server_account tier_limit: {result.get('message')}")
                return {}
        except Exception as e:
            print(f"  ❌ Error fetching server_account tier_limit: {e}")
            return {}
    
    # =========================================================================
    # STEP 4: Build the accountmanagement object (per-investor, from `accountmanagement` table)
    # =========================================================================
    SETTINGS_FIELDS = [
        'use_recent_highest_balance_as_current_balance',
        'additional_configurations',
        'skip_orders_close_to_position',
        'cancel_orders_close_to_position',
        'also_restrict_opposite_order_too_close_to_position',
        'switch_invalid_to_instant_order',
        'enable_order_type_conversion',
        'restrictions_duration',
        'enable_breakeven',
        'breakeven_dictionary',
        'restrict_order_from_timeframe',
    ]
    JSON_LIKE_FIELDS = [
        'breakeven_dictionary',
        'restrictions_duration',
        'minimum_balance_risk_distance',
        'maximum_balance_risk_distance',
        'account_balance_default_risk_management',
        'account_balance_maximum_risk_management',
        'daily_target_config',
        'additional_configurations',
    ]
    AM_EXCLUDED_COLUMNS = {'id', 'investorid', 'developerid'}
    RISK_REWARD_ARRAY_FIELDS = {
        'minimum_risk_reward',
        'fixed_risk_reward',
    }
    FLATTEN_INTO_SETTINGS_COLUMN = 'additional_configurations'
    
    def _coerce_json_scalar(val):
        if isinstance(val, Decimal):
            return float(val)
        if isinstance(val, datetime):
            return val.isoformat()
        if isinstance(val, date):
            return val.isoformat()
        return val
    
    def build_accountmanagement_object(am_row):
        if not am_row:
            return {}
        am_obj = {}
        settings_obj = {}
        for col, val in am_row.items():
            if col in AM_EXCLUDED_COLUMNS:
                continue
            if col in JSON_LIKE_FIELDS:
                parsed = parse_json_safe(val)
                val = parsed if parsed is not None else val
            if col in RISK_REWARD_ARRAY_FIELDS:
                if isinstance(val, str):
                    val = val.strip()
                    if val:
                        try:
                            val = [float(val)]
                        except (ValueError, TypeError):
                            val = [val]
                    else:
                        val = None
                elif isinstance(val, (int, float)):
                    val = [float(val)]
                elif isinstance(val, list):
                    converted = []
                    for item in val:
                        try:
                            converted.append(float(item))
                        except (ValueError, TypeError):
                            converted.append(item)
                    val = converted
                elif isinstance(val, Decimal):
                    val = [float(val)]
            if isinstance(val, Decimal):
                val = float(val)
            elif isinstance(val, datetime):
                val = val.isoformat()
            elif isinstance(val, date):
                val = val.isoformat()
            if col == FLATTEN_INTO_SETTINGS_COLUMN:
                if isinstance(val, dict):
                    for sub_key, sub_val in val.items():
                        if sub_key == 'settings' and isinstance(sub_val, dict):
                            for inner_key, inner_val in sub_val.items():
                                settings_obj[inner_key] = _coerce_json_scalar(inner_val)
                        else:
                            settings_obj[sub_key] = _coerce_json_scalar(sub_val)
                elif val is not None:
                    settings_obj[col] = _coerce_json_scalar(val)
                continue
            if col in SETTINGS_FIELDS:
                settings_obj[col] = val
            else:
                am_obj[col] = val
        am_obj['settings'] = settings_obj
        return am_obj
    
    # =========================================================================
    # STEP 5: Build the requirements object
    # =========================================================================
    def build_requirements_object(pi_row):
        if not pi_row:
            return {
                'contract_duration': None,
                'minimum_investment_amount': None,
                'maximum_investment_amount': None,
                'investor_percentage': None,
                'developer_percentage': None,
                'invested_at': None,
                'status': None,
            }
        def _dec(v):
            if isinstance(v, Decimal):
                return float(v)
            if isinstance(v, datetime):
                return v.isoformat()
            if isinstance(v, date):
                return v.isoformat()
            return v
        return {
            'contract_duration': _dec(_pick_first_key(pi_row, 'contract_duration', 'contractduration')),
            'minimum_investment_amount': _dec(_pick_first_key(pi_row, 'minimum_investment_amount', 'minimuminvestmentamount')),
            'maximum_investment_amount': _dec(_pick_first_key(pi_row, 'maximum_investment_amount', 'maximuminvestmentamount')),
            'investor_percentage': _dec(_pick_first_key(pi_row, 'investor_percentage', 'investorpercentage')),
            'developer_percentage': _dec(_pick_first_key(pi_row, 'developer_percentage', 'developerpercentage')),
            'invested_at': _dec(_pick_first_key(pi_row, 'invested_at', 'investedat')),
            'status': _pick_first_key(pi_row, 'status'),
        }
    
    # =========================================================================
    # STEP 5b: Build the tier_limit object
    # =========================================================================
    def build_tier_limit_object(user_tier_limit_value, server_tier_limit):
        if server_tier_limit is None or not isinstance(server_tier_limit, dict):
            return user_tier_limit_value
        if user_tier_limit_value is None:
            return None
        if isinstance(user_tier_limit_value, (dict, list)):
            return user_tier_limit_value
        user_tier_str = str(user_tier_limit_value).strip()
        if not user_tier_str:
            return user_tier_limit_value
        for key, val in server_tier_limit.items():
            if str(key).strip().lower() == user_tier_str.lower():
                print(f"       🎫 Matched tier '{key}' → enriched tier_limit")
                return {key: val}
        for key, val in server_tier_limit.items():
            if user_tier_str.lower() in str(key).lower() or str(key).lower() in user_tier_str.lower():
                print(f"       🎫 Matched tier '{key}' (fuzzy) → enriched tier_limit")
                return {key: val}
        return user_tier_limit_value
    
    # =========================================================================
    # STEP 6: Clean a record
    # =========================================================================
    def clean_record(record, investor_id, invested_map, pi_rows_map, am_map, server_tier_limit):
        cleaned = {}
        for key, value in record.items():
            if isinstance(value, str) and len(value) > 0:
                value = denormalize_path_value(value, key)
                repaired = repair_json_field(value)
                cleaned[key] = repaired
            else:
                cleaned[key] = value
        inv_list = invested_map.get(investor_id, [])
        cleaned['invested_with'] = '_AND_'.join(inv_list) if inv_list else None
        am_obj = {}
        req_obj = None
        matching_pi = []
        for (inv_id, dev_id, prog_id), pi_row in pi_rows_map.items():
            if inv_id == investor_id:
                matching_pi.append((dev_id, prog_id, pi_row))
        if matching_pi:
            for dev_id, prog_id, pi_row in matching_pi:
                am_row = am_map.get((investor_id, dev_id))
                if am_row:
                    am_obj = build_accountmanagement_object(am_row)
                    req_obj = build_requirements_object(pi_row)
                    break
            if req_obj is None:
                req_obj = build_requirements_object(matching_pi[0][2])
        if req_obj is not None:
            am_obj['requirements'] = req_obj
        cleaned['accountmanagement'] = am_obj if am_obj else {}
        if 'tier_limit' in cleaned:
            cleaned['tier_limit'] = build_tier_limit_object(
                cleaned.get('tier_limit'), server_tier_limit
            )
        for key, value in cleaned.items():
            if isinstance(value, str):
                if 'path' in key.lower() or '\\at\\gmail\\dot\\com' in value or '/at/gmail/dot/com' in value:
                    cleaned[key] = normalize_gmail_path(value)
        return cleaned
    
    # =========================================================================
    # STEP 7: Write records to file
    # =========================================================================
    def write_all_to_file(temp_file_path, data, first_record_status):
        if not data:
            return first_record_status, 0
        bytes_written = 0
        content_parts = []
        for record in data:
            record_id = str(record.get('id') or record.get('ID') or f"record_{hash(str(record))}")
            if not first_record_status:
                content_parts.append(',\n')
            json_str = json.dumps(record, default=str, indent=2)
            lines = json_str.split('\n')
            indented_lines = ['    ' + line for line in lines]
            formatted_json = '\n'.join(indented_lines)
            line = f'  "{record_id}": {formatted_json}'
            content_parts.append(line)
            bytes_written += len(line.encode('utf-8'))
            first_record_status = False
        content = ''.join(content_parts)
        safe_write_file(temp_file_path, 'a', content)
        return first_record_status, bytes_written
    
    # =========================================================================
    # MAIN EXECUTION
    # =========================================================================
    print("\n" + "="*70)
    print(f"  FETCHING TABLES (VPS-BASED IDENTIFICATION)")
    print("="*70)
    print(f"  Start Time  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Output Files: 2 files (ALL_FETCHED_INVESTORS & ALL_UPDATED_INVESTORS)")
    print("-"*70)
    
    try:
        # ---------------------------------------------------------------------
        # STEP 0: Get local IP and find investor IDs
        # ---------------------------------------------------------------------
        print("\n🖥️ [0/6] Getting Computer Identifiers...")
        local_ip = get_local_ip()
        if not local_ip:
            print("\n  🛑 Could not determine local IP address. Aborting.")
            return
        
        investor_ids_to_fetch, identification_method, matched_vps_user_id, vps_row_existed = \
            find_investor_ids_for_this_computer(local_ip)
        
        if not investor_ids_to_fetch:
            print(f"\n{'='*70}")
            print(f"  EXPORT SKIPPED - NO INVESTOR IDS FOUND")
            print(f"{'='*70}")
            if vps_row_existed:
                print(f"  Reason: A VPS row EXISTS for IP {local_ip}, but its user_id is")
                print(f"          NULL or could not be parsed. Set a valid user_id:")
                print(f"          UPDATE vps SET user_id = <ID> WHERE vps_ip_address = '{local_ip}';")
            else:
                print(f"  Reason: No VPS row matches IP {local_ip}")
                print(f"  ℹ️ Please add your IP to the vps table with an associated user_id:")
                print(f"          INSERT INTO vps (user_id, vps_ip_address) VALUES (<ID>, '{local_ip}');")
            print(f"{'='*70}")
            return
        
        print(f"\n  ✅ Total investor IDs to fetch: {len(investor_ids_to_fetch)}")
        print(f"  📋 IDs: {investor_ids_to_fetch[:30]}{'...' if len(investor_ids_to_fetch) > 30 else ''}")
        
        # ---------------------------------------------------------------------
        # STEP 0b: Fetch DEFAULT_ACCOUNTMANAGEMENT from server_account
        #          and WRITE IT DIRECTLY TO THE GLOBAL FILE.
        #          NOT per-investor. NOT merged. Just a standalone file.
        # ---------------------------------------------------------------------
        fetch_and_save_default_accountmanagement(
            r"C:\xampp\htdocs\harvcore\harvox\harvcore_accountmanagement.json"
        )
        
        # ---------------------------------------------------------------------
        # STEP 1: Build invested_with map and programme_investors rows
        # ---------------------------------------------------------------------
        print(f"\n📝 [1/6] Fetching programme_investors for invested_with...")
        invested_map, pi_rows_map = fetch_invested_with_map(investor_ids_to_fetch)
        if invested_map:
            print(f"  ✅ invested_with data found for {len(invested_map)} investor(s)")
        else:
            print(f"  ℹ️ No programme_investors records found")
        
        # ---------------------------------------------------------------------
        # STEP 2: Build accountmanagement map (from `accountmanagement` TABLE)
        # ---------------------------------------------------------------------
        print(f"\n📝 [2/6] Fetching accountmanagement records...")
        investor_developer_pairs = set()
        for (inv_id, dev_id, prog_id) in pi_rows_map.keys():
            investor_developer_pairs.add((inv_id, dev_id))
        if investor_developer_pairs:
            print(f"  🔍 Looking up {len(investor_developer_pairs)} (investor, developer) pair(s)")
            am_map = fetch_accountmanagement_map(list(investor_developer_pairs))
            print(f"  ✅ Found {len(am_map)} accountmanagement record(s)")
        else:
            am_map = {}
            print(f"  ℹ️ No investor-developer pairs to look up")
        
        # ---------------------------------------------------------------------
        # STEP 2b: Fetch server_account tier_limit
        # ---------------------------------------------------------------------
        server_tier_limit = fetch_server_tier_limit()
        
        # ---------------------------------------------------------------------
        # STEP 3: Get harvhub columns
        # ---------------------------------------------------------------------
        print("\n📡 [3/6] Fetching harvhub Schema...")
        EXCLUDED_COLUMNS = {
            'analytics_history', 'analytics', 'invested_with',
            'reset_contract', 'revenue_history',
            'password', 'paymentdetails', 'balance_display', 'message',
        }
        show_columns_query = "SHOW COLUMNS FROM harvhub"
        columns_result, _ = _timed_db_call(
            "harvhub schema (SHOW COLUMNS)", show_columns_query, None,
            wait_hint=FAST_HINT,
        )
        columns = []
        if columns_result.get('status') == 'success' and columns_result.get('results'):
            for row in columns_result['results']:
                col = _pick_first_key(row, 'field', 'column_name', 'columnname', 'column')
                if col and col.lower() not in EXCLUDED_COLUMNS:
                    columns.append(col)
            print(f"  📋 Found {len(columns)} columns via SHOW COLUMNS "
                  f"(excluding: {', '.join(sorted(EXCLUDED_COLUMNS))})")
        else:
            print(f"  ⚠️ SHOW COLUMNS returned no usable results.")
            _diag_dump("harvhub schema (SHOW COLUMNS)", columns_result)
            print(f"  ⚠️ Trying fallback: information_schema.COLUMNS with DATABASE()...")
            info_schema_query = """
                SELECT COLUMN_NAME
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'harvhub'
                ORDER BY ORDINAL_POSITION
            """
            info_result, _ = _timed_db_call(
                "harvhub schema (information_schema)", info_schema_query, None,
                wait_hint=FAST_HINT,
            )
            if info_result.get('status') == 'success' and info_result.get('results'):
                for row in info_result['results']:
                    col = _pick_first_key(row, 'column_name', 'columnname', 'column')
                    if col and col.lower() not in EXCLUDED_COLUMNS:
                        columns.append(col)
                print(f"  📋 Found {len(columns)} columns via information_schema")
            else:
                print(f"  ⚠️ information_schema also returned nothing.")
                _diag_dump("harvhub schema (information_schema)", info_result)
                print(f"  ⚠️ Trying final fallback: SELECT * FROM harvhub LIMIT 1...")
                sample_result, _ = _timed_db_call(
                    "harvhub sample row", "SELECT * FROM harvhub LIMIT 1", None,
                    wait_hint=FAST_HINT,
                )
                if sample_result.get('status') == 'success' and sample_result.get('results'):
                    sample_row = sample_result['results'][0]
                    if isinstance(sample_row, dict):
                        all_cols = list(sample_row.keys())
                        columns = [c for c in all_cols if c.lower() not in EXCLUDED_COLUMNS]
                        print(f"  📋 Found {len(columns)} columns from sample row keys")
                        print(f"       (raw sample keys: {all_cols})")
                    else:
                        print(f"  ❌ Sample row is not a dict — type={type(sample_row).__name__}")
                        _diag_dump("harvhub sample row", sample_result)
                else:
                    print(f"  ❌ Sample row query also returned nothing.")
                    _diag_dump("harvhub sample row", sample_result)
        if not columns:
            print(f"\n{'='*70}")
            print(f"  🛑 ABORTING — could not determine harvhub columns")
            print(f"{'='*70}")
            return
        
        # ---------------------------------------------------------------------
        # STEP 4: Count records
        # ---------------------------------------------------------------------
        print("\n📊 [4/6] Counting Records...")
        id_placeholders = ','.join(['%s'] * len(investor_ids_to_fetch))
        count_query = f"SELECT COUNT(*) as total FROM harvhub WHERE id IN ({id_placeholders})"
        count_result, _ = _timed_db_call(
            "harvhub count", count_query, investor_ids_to_fetch,
            wait_hint=FAST_HINT,
        )
        total_rows = 0
        if count_result.get('status') == 'success' and count_result.get('results'):
            raw_total = _pick_first_key(count_result['results'][0], 'total', 'count', 'COUNT(*)')
            total_rows = _coerce_int(raw_total) or 0
        else:
            print(f"  ⚠️ COUNT query returned no usable results.")
            _diag_dump("harvhub count", count_result)
        print(f"  📈 Total harvhub records: {total_rows:,}")
        
        # ---------------------------------------------------------------------
        # STEP 5: Prepare output files
        # ---------------------------------------------------------------------
        print(f"\n📁 [5/6] Preparing Output Directories...")
        output_files = [ALL_FETCHED_INVESTORS, ALL_UPDATED_INVESTORS]
        temp_files = []
        for i, file_path in enumerate(output_files):
            dir_path = os.path.dirname(file_path)
            temp_name = 'newfetcheddata_fetched.temp' if i == 0 else 'newfetcheddata_updated.temp'
            temp_path = os.path.join(dir_path, temp_name)
            temp_files.append(temp_path)
            os.makedirs(dir_path, exist_ok=True)
            safe_write_file(temp_path, 'overwrite', None)
            print(f"   Initialized temp file: {os.path.basename(temp_path)}")
        
        # ---------------------------------------------------------------------
        # STEP 6: Fetch all harvhub records
        # ---------------------------------------------------------------------
        print(f"\n📥 [6/6] Fetching ALL harvhub Records...")
        print(f"  🖥️ Method: {identification_method}")
        print(f"  🎯 Filter: {len(investor_ids_to_fetch)} investor ID(s)")
        print(f"  📋 Columns: {', '.join(columns[:5])}{'...' if len(columns) > 5 else ''}")
        print("-"*70)
        start_time = datetime.now()
        select_clause = ", ".join([f"`{col}`" for col in columns])
        query = f"""
            SELECT {select_clause}
            FROM harvhub
            WHERE id IN ({id_placeholders})
            ORDER BY id
        """
        print(f"  ⏳ Executing query...")
        result, _ = _timed_db_call(
            "harvhub fetch", query, investor_ids_to_fetch,
            wait_hint=BULK_HINT,
        )
        if result.get('status') != 'success':
            print(f"   ❌ QUERY ERROR: {result.get('message')}")
            _diag_dump("harvhub fetch", result)
            for temp_path in temp_files:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except:
                        pass
            return
        rows = result.get('results', [])
        print(f"  ✅ Retrieved {len(rows):,} records")
        all_records = []
        tier_enriched_count = 0
        for row in rows:
            investor_id = _pick_first_key(row, 'id', 'ID')
            investor_id = _coerce_int(investor_id)
            cleaned = clean_record(
                row, investor_id, invested_map, pi_rows_map, am_map, server_tier_limit
            )
            if isinstance(cleaned.get('tier_limit'), dict):
                tier_enriched_count += 1
            for key, value in cleaned.items():
                if isinstance(value, (datetime, date)):
                    cleaned[key] = value.isoformat()
                elif isinstance(value, Decimal):
                    cleaned[key] = float(value)
            all_records.append(cleaned)
        print(f"  ✍️ Writing {len(all_records):,} records to temp files...")
        first_record_status = {tp: True for tp in temp_files}
        total_bytes_written = 0
        for i, temp_path in enumerate(temp_files):
            print(f"    Writing to: {os.path.basename(temp_path)}")
            first_record_status[temp_path], bw = write_all_to_file(
                temp_path, all_records, first_record_status[temp_path]
            )
            total_bytes_written += bw
        for temp_path in temp_files:
            safe_write_file(temp_path, 'a', '\n}')
            print(f"  ✅ Closed: {os.path.basename(temp_path)}")
        temp_files_valid = True
        for temp_path in temp_files:
            if os.path.exists(temp_path):
                file_size = os.path.getsize(temp_path)
                if file_size >= 4:
                    print(f"  ✅ Valid: {os.path.basename(temp_path)} ({file_size} bytes)")
                else:
                    print(f"  ❌ Too small: {os.path.basename(temp_path)} ({file_size} bytes)")
                    temp_files_valid = False
            else:
                print(f"  ❌ Missing: {os.path.basename(temp_path)}")
                temp_files_valid = False
        if temp_files_valid:
            print(f"\n🗑️ [SUCCESS] Deleting old files and moving to final destinations...")
            try:
                delete_investor_files()
                print(f"   ✅ Old files deleted")
            except Exception as e:
                print(f"   ⚠️ Error deleting old files: {e}")
            for i, temp_path in enumerate(temp_files):
                final_path = output_files[i]
                print(f"  🔄 Moving: {os.path.basename(temp_path)} → {os.path.basename(final_path)}")
                move_temp_to_final(temp_path, final_path)
        else:
            print(f"\n⚠️ [SKIPPED] Temp files invalid. Keeping existing files intact.")
            for temp_path in temp_files:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except:
                        pass
            return
        
        # ---------------------------------------------------------------------
        # SUMMARY
        # ---------------------------------------------------------------------
        elapsed_time = (datetime.now() - start_time).total_seconds()
        final_sizes = {}
        for fp in output_files:
            final_sizes[fp] = os.path.getsize(fp) if os.path.exists(fp) else 0
        print("-"*70)
        print(f"\n📋 EXPORT SUMMARY")
        print("="*70)
        print(f"   Status           : SUCCESS")
        print(f"  🖥️  Method          : {identification_method}")
        print(f"  🌐 Local IP        : {local_ip}")
        if matched_vps_user_id:
            print(f"  🔑 VPS user_id     : {matched_vps_user_id}")
        print(f"  👥 Investor IDs    : {len(investor_ids_to_fetch)}")
        print(f"  📊 Records Exported: {len(rows):,} / {total_rows:,}")
        print(f"  🔗 invested_with   : {len(invested_map)} investor(s) with programme data")
        print(f"  📋 accountmanagement: {len(am_map)} record(s) found")
        print(f"  🎫 tier_limit tiers : {len(server_tier_limit) if isinstance(server_tier_limit, dict) else 0} available")
        print(f"  🎫 tier_limit enrich: {tier_enriched_count} user(s) enriched")
        print(f"  💾 File 1 Size     : {final_sizes[ALL_FETCHED_INVESTORS]/1024:,.1f} KB")
        print(f"  📁 File 1 Path     : {ALL_FETCHED_INVESTORS}")
        print(f"  💾 File 2 Size     : {final_sizes[ALL_UPDATED_INVESTORS]/1024:,.1f} KB")
        print(f"  📁 File 2 Path     : {ALL_UPDATED_INVESTORS}")
        print(f"  ⏱️  Total Time      : {elapsed_time:.1f} seconds")
        print("="*70)
        print(f"  🕐 Completion Time : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*70)
        
        if os.path.exists(ALL_FETCHED_INVESTORS):
            try:
                with open(ALL_FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content.startswith('{') and content.endswith('}'):
                        update_fresh_data_from_fetched_to_all_files()
                    else:
                        print(f"  ⚠️ Skipping update: invalid JSON structure")
            except:
                print(f"  ⚠️ Skipping update: unable to read file")
        
    except PermissionError as e:
        print(f"\n{'='*70}")
        print(f"   PERMISSION ERROR")
        print(f"{'='*70}")
        print(f"  Error Type : {type(e).__name__}")
        print(f"  Message    : {str(e)}")
        print(f"  File Path  : {e.filename if hasattr(e, 'filename') else 'Unknown'}")
        print(f"{'='*70}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"\n{'='*70}")
        print(f"   CRITICAL ERROR")
        print(f"{'='*70}")
        print(f"  Error Type : {type(e).__name__}")
        print(f"  Message    : {str(e)}")
        print(f"{'='*70}")
        import traceback
        traceback.print_exc()
                            
def hello():
    try:
        Harvhub.main_once()
        print("technical analysis completed.")
    except Exception as e:
        print(f"Error in techniques: {e}")

def updated_individual_records_to_all_files():
    """
    Intelligently merges investor data from invharv and harvhub into all files.
    ONE-WAY SYNC ONLY: INVHARV + HARVHUB → ALL_FETCHED / ALL_UPDATED
    
    This function performs a one-way merge with FIELD-BY-FIELD precedence:
    1. HARVHUB takes precedence over INVHARV (field-by-field)
    2. Merged data updates ALL_FETCHED_INVESTORS and ALL_UPDATED_INVESTORS
    3. If investor exists in individual files but not in ALL files, add them
    
    Key: HARVHUB overrides INVHARV for conflicting fields
    
    After merging, performs a confirmation check to ensure ALL_UPDATED matches
    the individual fetched files (HARVHUB priority over INVHARV).
    """
    print("\n" + "="*70)
    print(f"   INTELLIGENT INVESTOR MERGE (FIELD-BY-FIELD ONE-WAY SYNC)")
    print("="*70)
    print(f"   Start Time  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-"*70)
    print("   Direction: INVHARV + HARVHUB → ALL FILES (HARVHUB PRIORITY)")
    print("   Confirmation: Validating ALL_UPDATED matches individual fetched")
    print("="*70)
    
    stats = {
        "processing_success": False,
        "fetched": {
            "invharv": {"loaded": False, "count": 0, "path": INVHARV_FETCHED_INVESTORS},
            "harvhub": {"loaded": False, "count": 0, "path": HARVHUB_FETCHED_INVESTORS},
            "combined_count": 0,
            "output_path": ALL_FETCHED_INVESTORS,
            "fields_merged": 0,
            "investors_added_to_all": 0,
            "investors_updated_in_all": 0,
            "field_changes": {}
        },
        "updated": {
            "invharv": {"loaded": False, "count": 0, "path": INVHARV_UPDATED_INVESTORS},
            "harvhub": {"loaded": False, "count": 0, "path": HARVHUB_UPDATED_INVESTORS},
            "combined_count": 0,
            "output_path": ALL_UPDATED_INVESTORS,
            "fields_merged": 0,
            "investors_added_to_all": 0,
            "investors_updated_in_all": 0,
            "field_changes": {}
        },
        "confirmation": {
            "performed": False,
            "all_updated_matches_fetched": False,
            "mismatches_found": [],
            "total_mismatches": 0,
            "records_checked": 0,
            "fields_checked": 0
        },
        "errors": [],
        "warnings": [],
        "timestamp": datetime.now().isoformat()
    }
    
    def field_by_field_merge(source_record, target_record, source_name="HARVHUB"):
        """
        Merge source_record into target_record field-by-field.
        Each field from source overrides the corresponding field in target.
        
        Returns:
            tuple: (merged_record, fields_merged_count, merged_fields_list)
        """
        if not source_record:
            return target_record, 0, []
        
        if not target_record:
            return source_record.copy(), len(source_record), list(source_record.keys())
        
        merged = dict(target_record)  # Start with target
        fields_merged = []
        fields_added = []
        fields_updated = []
        
        for field, value in source_record.items():
            if field == 'id':
                continue
            
            if field not in merged:
                merged[field] = value
                fields_added.append(field)
            else:
                if isinstance(value, dict) and isinstance(merged[field], dict):
                    merged[field] = deep_merge_nested(merged[field], value)
                    fields_updated.append(field)
                elif isinstance(value, list) and isinstance(merged[field], list):
                    merged[field] = value
                    fields_updated.append(field)
                else:
                    merged[field] = value
                    fields_updated.append(field)
        
        fields_merged = fields_added + fields_updated
        return merged, len(fields_merged), fields_merged
    
    def deep_merge_nested(base_dict, override_dict):
        result = base_dict.copy() if base_dict else {}
        for key, value in override_dict.items():
            if key in result:
                if isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = deep_merge_nested(result[key], value)
                else:
                    result[key] = value
            else:
                result[key] = value
        return result
    
    def merge_investors_into_all(source_data, all_data, source_name, stats_section, merge_type="fetched"):
        merged = all_data.copy() if all_data else {}
        investors_added = 0
        investors_updated = 0
        total_fields_merged = 0
        field_changes = {}
        
        if not source_data:
            return merged, 0, 0, 0, {}
        
        for investor_id, source_record in source_data.items():
            if not isinstance(source_record, dict):
                continue
            
            if investor_id not in merged:
                merged[investor_id] = source_record.copy()
                investors_added += 1
                field_count = len(source_record) - 1
                total_fields_merged += field_count
                field_changes[investor_id] = {
                    'status': 'added',
                    'fields': [k for k in source_record.keys() if k != 'id'],
                    'field_count': field_count
                }
                print(f"        [+] Added investor {investor_id} to ALL_{merge_type} ({field_count} fields)")
                continue
            
            target_record = merged[investor_id]
            merged_record, fields_merged_count, merged_fields = field_by_field_merge(
                source_record, target_record, source_name
            )
            
            # Ensure records from individual files update ALL files
            merged[investor_id] = merged_record
            
            if fields_merged_count > 0:
                investors_updated += 1
                total_fields_merged += fields_merged_count
                field_changes[investor_id] = {
                    'status': 'updated',
                    'fields': merged_fields,
                    'field_count': fields_merged_count
                }
                print(f"        [~] Updated investor {investor_id} in ALL_{merge_type} ({fields_merged_count} fields)")
            else:
                field_changes[investor_id] = {
                    'status': 'synced',
                    'fields': [],
                    'field_count': 0
                }
        
        return merged, investors_added, investors_updated, total_fields_merged, field_changes
    
    def load_json_file(filepath, stats_section, name):
        if not os.path.exists(filepath):
            stats["warnings"].append(f"{name} file not found: {filepath}")
            return None, False
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    stats_section["loaded"] = True
                    stats_section["count"] = len(data)
                    print(f"   ✅ Loaded {name}: {len(data):,} records")
                    return data, True
                else:
                    stats["errors"].append(f"{name} has invalid format (expected dict)")
                    return None, False
        except Exception as e:
            error_msg = f"Error loading {name}: {str(e)}"
            print(f"   ❌ {error_msg}")
            stats["errors"].append(error_msg)
            return None, False
    
    def save_json_file(filepath, data, name):
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            error_msg = f"Error saving {name}: {str(e)}"
            print(f"   ❌ {error_msg}")
            stats["errors"].append(error_msg)
            return False
    
    def merge_two_sources_with_priority(source1, source2, priority_source_name="HARVHUB"):
        result = {}
        if source1:
            result = source1.copy()
        if source2:
            for investor_id, source2_record in source2.items():
                if investor_id in result:
                    result[investor_id], _, _ = field_by_field_merge(
                        source2_record, 
                        result[investor_id], 
                        priority_source_name
                    )
                else:
                    result[investor_id] = source2_record.copy()
        return result
    
    def confirm_all_updated_matches_individual_fetched(invharv_fetched, harvhub_fetched, all_updated):
        """
        Confirmation check: Ensures ALL_UPDATED has the same data as the combined
        individual fetched files (HARVHUB priority over INVHARV).
        
        Returns:
            tuple: (is_matching, mismatches_list, total_checked, total_fields_checked)
        """
        print("\n" + "="*70)
        print("   🔍 CONFIRMATION CHECK: Validating ALL_UPDATED matches Individual Fetched")
        print("="*70)
        
        if not all_updated:
            print("   ❌ ALL_UPDATED is empty or not loaded")
            return False, [], 0, 0
        
        # Combine individual fetched sources (HARVHUB priority)
        combined_expected = merge_two_sources_with_priority(invharv_fetched, harvhub_fetched, "HARVHUB")
        
        if not combined_expected:
            print("   ❌ No individual fetched data to compare against")
            return False, [], 0, 0
        
        print(f"   📊 Expected records (from individual fetched): {len(combined_expected):,}")
        print(f"   📊 Actual records (in ALL_UPDATED): {len(all_updated):,}")
        print("-"*70)
        
        mismatches = []
        records_checked = 0
        total_fields_checked = 0
        records_matching = 0
        records_with_differences = 0
        
        # Check each record in the expected combined data
        for investor_id, expected_record in combined_expected.items():
            records_checked += 1
            
            if investor_id not in all_updated:
                mismatches.append({
                    'investor_id': investor_id,
                    'type': 'missing_in_all_updated',
                    'message': f"Investor {investor_id} exists in fetched files but not in ALL_UPDATED",
                    'fields': []
                })
                print(f"   ❌ Investor {investor_id}: MISSING from ALL_UPDATED")
                continue
            
            actual_record = all_updated[investor_id]
            field_differences = []
            
            # Compare each field (excluding 'id')
            for field, expected_value in expected_record.items():
                if field == 'id':
                    continue
                
                total_fields_checked += 1
                actual_value = actual_record.get(field)
                
                if expected_value != actual_value:
                    field_differences.append({
                        'field': field,
                        'expected': expected_value,
                        'actual': actual_value
                    })
            
            if field_differences:
                records_with_differences += 1
                mismatches.append({
                    'investor_id': investor_id,
                    'type': 'field_mismatch',
                    'message': f"Investor {investor_id} has {len(field_differences)} field differences",
                    'fields': field_differences
                })
                print(f"   ⚠️  Investor {investor_id}: {len(field_differences)} field differences")
                # Show first 3 differences
                for diff in field_differences[:3]:
                    print(f"        - {diff['field']}: expected '{diff['expected']}' | actual '{diff['actual']}'")
                if len(field_differences) > 3:
                    print(f"        ... and {len(field_differences) - 3} more differences")
            else:
                records_matching += 1
        
        # Check if there are extra records in ALL_UPDATED that aren't in fetched
        for investor_id in all_updated:
            if investor_id not in combined_expected:
                mismatches.append({
                    'investor_id': investor_id,
                    'type': 'extra_in_all_updated',
                    'message': f"Investor {investor_id} exists in ALL_UPDATED but not in fetched files",
                    'fields': []
                })
                print(f"   ⚠️  Investor {investor_id}: EXTRA in ALL_UPDATED (not in fetched)")
        
        # Summary
        print("-"*70)
        print(f"   📊 Confirmation Summary:")
        print(f"      Records checked: {records_checked:,}")
        print(f"      Fields checked: {total_fields_checked:,}")
        print(f"      Records matching: {records_matching:,}")
        print(f"      Records with differences: {records_with_differences:,}")
        print(f"      Mismatches found: {len(mismatches):,}")
        
        is_matching = len(mismatches) == 0
        
        if is_matching:
            print("   ✅ SUCCESS: ALL_UPDATED matches individual fetched files perfectly!")
        else:
            print(f"   ❌ FAILED: {len(mismatches)} mismatches found between ALL_UPDATED and individual fetched files")
        
        stats["confirmation"]["performed"] = True
        stats["confirmation"]["all_updated_matches_fetched"] = is_matching
        stats["confirmation"]["mismatches_found"] = mismatches
        stats["confirmation"]["total_mismatches"] = len(mismatches)
        stats["confirmation"]["records_checked"] = records_checked
        stats["confirmation"]["fields_checked"] = total_fields_checked
        
        return is_matching, mismatches, records_checked, total_fields_checked
    
    try:
        # ============================================================
        # 1. PROCESS FETCHED INVESTORS
        # ============================================================
        print("\n📥 [1/3] Processing FETCHED investors (FIELD-BY-FIELD)...")
        print("-"*40)
        print(f"   Source 1: {INVHARV_FETCHED_INVESTORS}")
        print(f"   Source 2: {HARVHUB_FETCHED_INVESTORS}")
        print(f"   Output : {ALL_FETCHED_INVESTORS}")
        print()
        
        invharv_fetched, _ = load_json_file(INVHARV_FETCHED_INVESTORS, stats["fetched"]["invharv"], "INVHARV fetched")
        harvhub_fetched, _ = load_json_file(HARVHUB_FETCHED_INVESTORS, stats["fetched"]["harvhub"], "HARVHUB fetched")
        all_fetched, _ = load_json_file(ALL_FETCHED_INVESTORS, {"loaded": False, "count": 0}, "ALL fetched (existing)")
        
        if not all_fetched:
            all_fetched = {}
            print(f"   ℹ️  No existing ALL fetched file, starting fresh")
        
        print(f"\n   🔄 Step 1: Merging individual sources (HARVHUB takes precedence)...")
        combined_individual_fetched = merge_two_sources_with_priority(invharv_fetched, harvhub_fetched, "HARVHUB")
        print(f"      ✅ Combined individual sources: {len(combined_individual_fetched)} investors")
        
        print(f"\n   🔄 Step 2: Merging into ALL_FETCHED...")
        merged_fetched, added, updated, fields, changes = merge_investors_into_all(
            combined_individual_fetched, all_fetched, "INDIVIDUAL SOURCES", stats["fetched"], "fetched"
        )
        
        stats["fetched"]["investors_added_to_all"] = added
        stats["fetched"]["investors_updated_in_all"] = updated
        stats["fetched"]["fields_merged"] = fields
        stats["fetched"]["field_changes"] = changes
        
        print(f"\n      ✅ Merge complete: {added} investors added, {updated} investors updated, {fields} fields merged")
        
        if changes:
            sample_ids = list(changes.keys())[:5]
            for investor_id in sample_ids:
                change = changes[investor_id]
                field_list = change['fields'][:5]
                field_str = ', '.join(field_list)
                if len(change['fields']) > 5:
                    field_str += f" ... (+{len(change['fields']) - 5} more)"
                print(f"        - ID {investor_id}: {change['status']} ({change['field_count']} fields: {field_str})")
        
        if merged_fetched:
            stats["fetched"]["combined_count"] = len(merged_fetched)
            if save_json_file(ALL_FETCHED_INVESTORS, merged_fetched, "ALL fetched combined"):
                print(f"\n   💾 Saved ALL_FETCHED: {len(merged_fetched):,} records")
        
        # ============================================================
        # 2. PROCESS UPDATED INVESTORS
        # ============================================================
        print("\n📤 [2/3] Processing UPDATED investors (FIELD-BY-FIELD)...")
        print("-"*40)
        print(f"   Source 1: {INVHARV_UPDATED_INVESTORS}")
        print(f"   Source 2: {HARVHUB_UPDATED_INVESTORS}")
        print(f"   Output : {ALL_UPDATED_INVESTORS}")
        print()
        
        invharv_updated, _ = load_json_file(INVHARV_UPDATED_INVESTORS, stats["updated"]["invharv"], "INVHARV updated")
        harvhub_updated, _ = load_json_file(HARVHUB_UPDATED_INVESTORS, stats["updated"]["harvhub"], "HARVHUB updated")
        all_updated, _ = load_json_file(ALL_UPDATED_INVESTORS, {"loaded": False, "count": 0}, "ALL updated (existing)")
        
        if not all_updated:
            all_updated = {}
            print(f"   ℹ️  No existing ALL updated file, starting fresh")
        
        print(f"\n   🔄 Step 1: Merging individual sources (HARVHUB takes precedence)...")
        combined_individual_updated = merge_two_sources_with_priority(invharv_updated, harvhub_updated, "HARVHUB")
        print(f"      ✅ Combined individual sources: {len(combined_individual_updated)} investors")
        
        print(f"\n   🔄 Step 2: Merging into ALL_UPDATED...")
        merged_updated, added, updated, fields, changes = merge_investors_into_all(
            combined_individual_updated, all_updated, "INDIVIDUAL SOURCES", stats["updated"], "updated"
        )
        
        stats["updated"]["investors_added_to_all"] = added
        stats["updated"]["investors_updated_in_all"] = updated
        stats["updated"]["fields_merged"] = fields
        stats["updated"]["field_changes"] = changes
        
        print(f"\n      ✅ Merge complete: {added} investors added, {updated} investors updated, {fields} fields merged")
        
        if changes:
            sample_ids = list(changes.keys())[:5]
            for investor_id in sample_ids:
                change = changes[investor_id]
                field_list = change['fields'][:5]
                field_str = ', '.join(field_list)
                if len(change['fields']) > 5:
                    field_str += f" ... (+{len(change['fields']) - 5} more)"
                print(f"        - ID {investor_id}: {change['status']} ({change['field_count']} fields: {field_str})")
        
        if merged_updated:
            stats["updated"]["combined_count"] = len(merged_updated)
            if save_json_file(ALL_UPDATED_INVESTORS, merged_updated, "ALL updated combined"):
                print(f"\n   💾 Saved ALL_UPDATED: {len(merged_updated):,} records")
        
        # ============================================================
        # 3. CONFIRMATION CHECK
        # ============================================================
        print("\n✅ [3/3] Running Confirmation Check...")
        print("-"*40)
        print("   Validating that ALL_UPDATED matches individual fetched files")
        print("   (HARVHUB priority over INVHARV)")
        print()
        
        # Reload ALL_UPDATED after save to ensure we have the latest
        all_updated_reloaded, _ = load_json_file(
            ALL_UPDATED_INVESTORS, 
            {"loaded": False, "count": 0}, 
            "ALL updated (reloaded for confirmation)"
        )
        
        if not all_updated_reloaded:
            print("   ❌ Could not reload ALL_UPDATED for confirmation")
            stats["errors"].append("Confirmation failed: Could not reload ALL_UPDATED")
        else:
            # Run confirmation check
            is_matching, mismatches, records_checked, fields_checked = confirm_all_updated_matches_individual_fetched(
                invharv_fetched, harvhub_fetched, all_updated_reloaded
            )
            
            # Update stats
            stats["confirmation"]["performed"] = True
            stats["confirmation"]["all_updated_matches_fetched"] = is_matching
            stats["confirmation"]["mismatches_found"] = mismatches
            stats["confirmation"]["total_mismatches"] = len(mismatches)
            stats["confirmation"]["records_checked"] = records_checked
            stats["confirmation"]["fields_checked"] = fields_checked
            
            # If mismatches found, log them
            if not is_matching:
                print(f"\n   ⚠️  Mismatches found: {len(mismatches)} issues")
                stats["warnings"].append(f"Confirmation check found {len(mismatches)} mismatches between ALL_UPDATED and individual fetched files")
                
                # Show detailed mismatches
                for mismatch in mismatches[:5]:
                    if mismatch['type'] == 'missing_in_all_updated':
                        print(f"      - {mismatch['message']}")
                    elif mismatch['type'] == 'extra_in_all_updated':
                        print(f"      - {mismatch['message']}")
                    elif mismatch['type'] == 'field_mismatch':
                        print(f"      - {mismatch['message']}")
                        for field_diff in mismatch['fields'][:2]:
                            print(f"          {field_diff['field']}: expected '{field_diff['expected']}' | actual '{field_diff['actual']}'")
                if len(mismatches) > 5:
                    print(f"      ... and {len(mismatches) - 5} more mismatches")
        
        # ============================================================
        # 4. FINAL SUMMARY
        # ============================================================
        stats["processing_success"] = True
        
        print("\n" + "="*70)
        print(f"  MERGE SUMMARY (HARVHUB TAKES PRECEDENCE: INVHARV + HARVHUB → ALL)")
        print("="*70)
        
        print(f"\n   📥 FETCHED FILES:")
        print(f"     INVHARV  : {'✅' if stats['fetched']['invharv']['loaded'] else '❌'} {stats['fetched']['invharv']['count']:,} records")
        print(f"     HARVHUB  : {'✅' if stats['fetched']['harvhub']['loaded'] else '❌'} {stats['fetched']['harvhub']['count']:,} records")
        print(f"     → Individual Combined : {len(combined_individual_fetched):,} records")
        print(f"     → ALL_FETCHED After Sync : {stats['fetched']['combined_count']:,} records")
        print(f"       (Added: {stats['fetched']['investors_added_to_all']:,} | Updated: {stats['fetched']['investors_updated_in_all']:,} | Fields: {stats['fetched']['fields_merged']:,})")
        print(f"     Output   : {ALL_FETCHED_INVESTORS}")
        
        print(f"\n   📤 UPDATED FILES:")
        print(f"     INVHARV  : {'✅' if stats['updated']['invharv']['loaded'] else '❌'} {stats['updated']['invharv']['count']:,} records")
        print(f"     HARVHUB  : {'✅' if stats['updated']['harvhub']['loaded'] else '❌'} {stats['updated']['harvhub']['count']:,} records")
        print(f"     → Individual Combined : {len(combined_individual_updated):,} records")
        print(f"     → ALL_UPDATED After Sync : {stats['updated']['combined_count']:,} records")
        print(f"       (Added: {stats['updated']['investors_added_to_all']:,} | Updated: {stats['updated']['investors_updated_in_all']:,} | Fields: {stats['updated']['fields_merged']:,})")
        print(f"     Output   : {ALL_UPDATED_INVESTORS}")
        
        print(f"\n   🔍 CONFIRMATION CHECK:")
        if stats["confirmation"]["performed"]:
            status = "✅ PASSED" if stats["confirmation"]["all_updated_matches_fetched"] else "❌ FAILED"
            print(f"     Status     : {status}")
            print(f"     Records    : {stats['confirmation']['records_checked']:,} checked")
            print(f"     Fields     : {stats['confirmation']['fields_checked']:,} checked")
            print(f"     Mismatches : {stats['confirmation']['total_mismatches']:,} found")
            
            if not stats["confirmation"]["all_updated_matches_fetched"]:
                print(f"     ⚠️  ALL_UPDATED does NOT match individual fetched files!")
                print(f"     Please review the mismatches listed above.")
        else:
            print(f"     ❌ Confirmation check was not performed")
        
        print(f"\n   ✅ Status : {'SUCCESS' if stats['processing_success'] else 'FAILED'}")
        print(f"   🕐 Time   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*70)
        
        return stats
        
    except Exception as e:
        print(f"\n{'='*70}")
        print(f"   CRITICAL ERROR")
        print(f"{'='*70}")
        print(f"   Error Type : {type(e).__name__}")
        print(f"   Message    : {str(e)}")
        print(f"{'='*70}")
        
        import traceback
        traceback.print_exc()
        
        stats["processing_success"] = False
        stats["errors"].append(f"Critical error: {str(e)}")
        return stats
                 
def update_investors():
    """
    Update database from JSON files (batched, no delete-insert for multi-row tables).

    Reads from BOTH ALL_UPDATED_INVESTORS and ALL_FETCHED_INVESTORS, merges
    them, then splits each merged investor record back into the underlying
    source tables:

      - harvhub                 ← flat fields
      - investors_analytics     ← analytics.*  (UNIQUE per userid)
      - daily_target_revenue    ← daily_target_met.week_*.<Day>
      - balance_log             ← daily_balance_log.<dd-mm-yyyy>
      - unauthorized_trades     ← unauthorized_trades[]  (root)
      - authorized_trades       ← authorized_trades[]    (root)

    ⚠️  accountmanagement is deliberately EXCLUDED from this updater.
        Its data is owned exclusively by fetch_investors(); any changes to
        accountmanagement made in the JSON files are NOT pushed back to the
        DB.  This prevents the fetch-side snapshot from clobbering the
        authoritative accountmanagement rows (which may be edited directly
        in the database or by another service).

    All writes are batched (200 rows per statement).  Multi-row tables are
    updated in place — NO DELETE. Rows absent from JSON are left untouched.
    """

    updated_individual_records_to_all_files()
    restore_missing_fields()

    # =====================================================================
    # IO / value helpers
    # =====================================================================
    def safe_read_file(file_path):
        if not os.path.exists(file_path):
            return None
        max_retries = 3
        retry_delay = 1
        for attempt in range(max_retries):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except PermissionError:
                print(f"    ⚠️ Permission denied reading {file_path} (attempt {attempt+1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    raise
            except json.JSONDecodeError as e:
                print(f"    ❌ JSON decode error in {file_path}: {str(e)}")
                return None
            except Exception as e:
                print(f"    ❌ Error reading {file_path}: {str(e)}")
                return None
        return None

    def is_json_like(value):
        if value is None: return False
        if isinstance(value, (dict, list)): return True
        if isinstance(value, str):
            s = value.strip()
            return (s.startswith('{') and s.endswith('}')) or \
                   (s.startswith('[') and s.endswith(']'))
        return False

    def normalize_path_value(value, field_name):
        if value is None or 'path' not in field_name.lower(): return value
        if not isinstance(value, str): return value
        return value.replace('\\', '_')

    def normalize_execution_start_date(value):
        if value is None or not isinstance(value, str): return value
        fmts = ["%B %d, %Y", "%b %d, %Y", "%d-%b-%Y", "%Y-%m-%d",
                "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"]
        v = value.strip()
        for fmt in fmts:
            try: return datetime.strptime(v, fmt).strftime("%Y-%m-%d")
            except ValueError: continue
        return value

    def normalize_json_value(value):
        if value is None: return None
        if isinstance(value, (dict, list)): return json.dumps(value, ensure_ascii=False)
        if isinstance(value, str):
            s = value.strip()
            if s.upper() == 'NULL': return None
            if s == '' or s == '{}': return '{}'
            return s
        return value

    def sql_literal(value):
        if value is None: return 'NULL'
        if isinstance(value, bool): return '1' if value else '0'
        if isinstance(value, (int, float)): return str(value)
        if isinstance(value, str):
            if value.strip().upper() == 'NULL': return 'NULL'
            return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
        s = str(value)
        return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"

    def sql_kv(field_name, value, field_lower=None):
        if field_lower is None: field_lower = field_name.lower()
        if field_lower == 'execution_start_date':
            value = normalize_execution_start_date(value)
        if 'path' in field_lower:
            value = normalize_path_value(value, field_name)
        if is_json_like(value):
            jv = normalize_json_value(value)
            if jv is None: return f"`{field_name}` = NULL"
            esc = jv.replace("\\", "\\\\").replace("'", "\\'")
            return f"`{field_name}` = '{esc}'"
        return f"`{field_name}` = {sql_literal(value)}"

    def to_int_safe(value, default=None):
        if value is None: return default
        try: return int(float(value))
        except (ValueError, TypeError): return default

    def coerce_date(value):
        if value is None: return None
        if isinstance(value, str):
            v = value.strip()
            if not v or v.upper() == 'NULL': return None
            fmts = ["%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y",
                    "%Y/%m/%d", "%B %d, %Y", "%b %d, %Y", "%d-%b-%Y"]
            for fmt in fmts:
                try: return datetime.strptime(v, fmt).strftime("%Y-%m-%d")
                except ValueError: continue
            try: return datetime.fromisoformat(v).strftime("%Y-%m-%d")
            except Exception: return None
        return None

    def coerce_datetime(value):
        if value is None: return None
        if isinstance(value, str):
            v = value.strip()
            if not v or v.upper() == 'NULL': return None
            try: return datetime.fromisoformat(v).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try: return datetime.strptime(v, fmt).strftime("%Y-%m-%d %H:%M:%S")
                    except ValueError: continue
        return None

    def chunked(seq, size):
        for i in range(0, len(seq), size):
            yield seq[i:i + size]

    # =====================================================================
    # Batched upsert for single-row-per-user tables
    # =====================================================================
    def batch_upsert_single_row(table, rows, key_cols, cols):
        """
        rows: list of dict {key_col: value, col: literal, ...}
        key_cols: list of key column names (e.g. ['id'] or ['investorid','developerid'])
        cols: list of all writable column names (excluding keys)
        Uses: INSERT INTO t (k..., c...) VALUES (...),(...)
              ON DUPLICATE KEY UPDATE c = VALUES(c), ...
        """
        if not rows:
            return 0
        all_cols = list(dict.fromkeys(list(key_cols) + list(cols)))
        value_groups = []
        for r in rows:
            vals = []
            for c in all_cols:
                vals.append(r.get(c, 'NULL'))
            value_groups.append("(" + ", ".join(vals) + ")")

        update_cols = [c for c in cols if c not in key_cols]
        if update_cols:
            upd = ", ".join(f"`{c}` = VALUES(`{c}`)" for c in update_cols)
            tail = f"ON DUPLICATE KEY UPDATE {upd}"
        else:
            # Nothing to update — skip conflicting rows entirely
            tail = "ON DUPLICATE KEY UPDATE " + f"`{key_cols[0]}` = `{key_cols[0]}`"

        total = 0
        for grp in chunked(value_groups, BATCH_SIZE):
            q = (f"INSERT INTO {table} "
                 f"({', '.join(f'`{c}`' for c in all_cols)}) "
                 f"VALUES {', '.join(grp)} {tail}")
            r = db.execute_query(q, wait_hint={'signal': 'any-of', 'timeout': 25})
            if r.get('status') == 'success':
                total += len(grp)
        return total

    # =====================================================================
    # Multi-row tables: no delete. Update existing, insert new.
    # =====================================================================
    def sync_multi_row_table(table, userid, rows, columns, pk_col='id',
                             existing_cache=None, match_key_fn=None):
        """
        rows: list of dicts {col: value, ...} — all for one user.
        columns: list of writable columns (excluding pk/userid which are added)
        pk_col: primary key column of the table
        existing_cache: {userid: {match_key: pk_id}}  — populated lazily
        match_key_fn: given a row dict, return the tuple that identifies it
                      (used to look up the PK in existing_cache)

        Returns (updated_count, inserted_count).
        """
        if not rows:
            return 0, 0
        if existing_cache is None:
            existing_cache = {}
        if match_key_fn is None:
            # default: use ('userid',) - meaning single row per user; but this
            # shouldn't happen because multi-row tables always need a key.
            match_key_fn = lambda r: (userid,)

        # Lazily fetch existing PKs for this user
        if userid not in existing_cache:
            r = db.execute_query(
                f"SELECT {pk_col} FROM {table} WHERE userid = {int(userid)}",
                wait_hint={'signal': 'table', 'timeout': 10},
            )
            cache_map = {}
            if r.get('status') == 'success':
                for row in r.get('results', []):
                    rid = to_int_safe(row.get(pk_col))
                    if rid is None:
                        continue
                    # We don't know the match key from a bare PK fetch — so we
                    # also need the other columns that form the key. Fall back
                    # to fetching them.
                    pass
            existing_cache[userid] = cache_map  # will be re-fetched below

        # We need the match columns too, so do a richer fetch.
        if not existing_cache.get(userid):
            # Determine match columns from the first row
            sample = rows[0]
            match_cols = [c for c in columns if c in sample]
            select_cols = [pk_col] + [c for c in match_cols if c != pk_col]
            r = db.execute_query(
                f"SELECT {', '.join(f'`{c}`' for c in select_cols)} "
                f"FROM {table} WHERE userid = {int(userid)}",
                wait_hint={'signal': 'table', 'timeout': 10},
            )
            cmap = {}
            if r.get('status') == 'success':
                for row in r.get('results', []):
                    rid = to_int_safe(row.get(pk_col))
                    if rid is None:
                        continue
                    key = tuple(
                        (row.get(c) if row.get(c) is not None else '')
                        for c in match_cols if c != pk_col
                    )
                    cmap[key] = rid
            existing_cache[userid] = cmap

        cache = existing_cache[userid]

        to_update = []  # list of (pk_id, {col: literal})
        to_insert = []  # list of {col: literal, 'userid': literal}

        for row in rows:
            if not isinstance(row, dict):
                continue
            # Build per-row literals
            row_lit = {}
            for c in columns:
                if c not in row or row[c] is None:
                    continue
                val = row[c]
                if c == 'closed_time':
                    val = coerce_datetime(val)
                    if val is None:
                        continue
                elif c == 'date':
                    coerced = coerce_date(val)
                    if coerced is not None:
                        val = coerced
                row_lit[c] = sql_literal(val)

            key = match_key_fn(row)
            if key in cache:
                pk_id = cache[key]
                to_update.append((pk_id, row_lit))
            else:
                ins = dict(row_lit)
                ins['userid'] = str(int(userid))
                to_insert.append(ins)

        updated = 0
        inserted = 0

        # --- batched UPDATE by PK using CASE ---
        for grp in chunked(to_update, BATCH_SIZE):
            col_set = set()
            for _, d in grp:
                col_set.update(d.keys())
            if not col_set:
                continue
            cols = [c for c in columns if c in col_set]
            ids = [str(rid) for rid, _ in grp]
            case_parts = []
            for c in cols:
                whens = []
                for rid, d in grp:
                    lit = d.get(c, 'NULL')
                    whens.append(f"WHEN {rid} THEN {lit}")
                case_parts.append(f"`{c}` = CASE `{pk_col}` {' '.join(whens)} END")
            q = (f"UPDATE {table} SET {', '.join(case_parts)} "
                 f"WHERE `{pk_col}` IN ({', '.join(ids)})")
            r = db.execute_query(q, wait_hint={'signal': 'any-of', 'timeout': 25})
            if r.get('status') == 'success':
                updated += len(grp)
                # Update cache with new literals (so subsequent rows in same
                # user match correctly — unlikely here but safe)
                for rid, d in grp:
                    for k, v in cache.items():
                        if v == rid:
                            cache[k] = rid
                            break

        # --- batched INSERT ---
        for grp in chunked(to_insert, BATCH_SIZE):
            col_set = set()
            for d in grp:
                col_set.update(d.keys())
            cols = [c for c in ['userid'] + columns if c in col_set]
            value_groups = []
            for d in grp:
                vals = [d.get(c, 'NULL') for c in cols]
                value_groups.append("(" + ", ".join(vals) + ")")
            q = (f"INSERT INTO {table} "
                 f"({', '.join(f'`{c}`' for c in cols)}) "
                 f"VALUES {', '.join(value_groups)}")
            r = db.execute_query(q, wait_hint={'signal': 'any-of', 'timeout': 25})
            if r.get('status') == 'success':
                inserted += len(grp)

        return updated, inserted

    # =====================================================================
    # Header
    # =====================================================================
    print("\n" + "="*70)
    print(f"  UPDATING TABLES (SPLIT-BACK MODE — batched, no delete)")
    print("="*70)
    print(f"  Start Time  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  ℹ️  accountmanagement is FETCH-ONLY and will NOT be written by this updater")
    print("-"*70)

    BATCH_SIZE = 200

    try:
        # =====================================================================
        # [1/7] Load source files
        # =====================================================================
        print("\n📁 [1/7] Checking Source Files...")
        merged_data = {}
        files_loaded = []

        if os.path.exists(ALL_UPDATED_INVESTORS):
            try:
                updated_data = safe_read_file(ALL_UPDATED_INVESTORS)
                if updated_data and isinstance(updated_data, dict):
                    merged_data.update(updated_data)
                    files_loaded.append('ALL_UPDATED_INVESTORS.json')
                    print(f"   ✅ Loaded: {ALL_UPDATED_INVESTORS} ({len(updated_data):,} records)")
            except Exception as e:
                print(f"   🛑 Error reading update file: {str(e)}")

        if os.path.exists(ALL_FETCHED_INVESTORS):
            try:
                fetched_data = safe_read_file(ALL_FETCHED_INVESTORS)
                if fetched_data and isinstance(fetched_data, dict):
                    for key, value in fetched_data.items():
                        if key not in merged_data:
                            merged_data[key] = value
                    files_loaded.append('ALL_FETCHED_INVESTORS.json')
                    print(f"   ✅ Loaded: {ALL_FETCHED_INVESTORS} ({len(fetched_data):,} records)")
            except Exception as e:
                print(f"   🛑 Error reading fetched file: {str(e)}")

        if not merged_data:
            print(f"\n   ❌ No data loaded from any source file")
            return

        total_investors = len(merged_data)
        print(f"\n  📊 Total Records Merged: {total_investors:,}")
        print(f"  📁 Source Files: {', '.join(files_loaded)}")

        # =====================================================================
        # [2/7] Discover schemas  (accountmanagement intentionally NOT discovered)
        # =====================================================================
        print("\n📡 [2/7] Discovering target table schemas...")

        def _schema(table, retries=2):
            queries = [
                (
                    f"SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                    f"WHERE TABLE_SCHEMA = DATABASE() "
                    f"AND TABLE_NAME = '{table}' "
                    f"ORDER BY ORDINAL_POSITION"
                ),
                f"SHOW COLUMNS FROM {table}",
            ]
            for attempt in range(retries):
                for q in queries:
                    r = db.execute_query(
                        q,
                        wait_hint={'signal': 'table', 'timeout': 10,
                                   'expect_empty': True},
                    )
                    if r.get('status') == 'success' and r.get('results'):
                        cols = set()
                        for row in r['results']:
                            c = (
                                row.get('Field')
                                or row.get('FIELD')
                                or row.get('COLUMN_NAME')
                                or row.get('column_name')
                                or ''
                            )
                            if c:
                                cols.add(c.lower())
                        if cols:
                            return cols
                if attempt < retries - 1:
                    time.sleep(0.6)
            print(f"   ⚠️ Could not read {table} schema")
            return set()

        harvhub_columns   = _schema('harvhub');               print(f"   ✅ harvhub                : {len(harvhub_columns)} cols")
        ia_columns        = _schema('investors_analytics');    print(f"   ✅ investors_analytics    : {len(ia_columns)} cols")
        dtr_columns       = _schema('daily_target_revenue');   print(f"   ✅ daily_target_revenue   : {len(dtr_columns)} cols")
        bl_columns        = _schema('balance_log');            print(f"   ✅ balance_log            : {len(bl_columns)} cols")
        ut_columns        = _schema('unauthorized_trades');    print(f"   ✅ unauthorized_trades    : {len(ut_columns)} cols")
        at_columns        = _schema('authorized_trades');      print(f"   ✅ authorized_trades      : {len(at_columns)} cols")
        print(f"   ⏭️  accountmanagement      : SKIPPED (fetch-only table)")

        # =====================================================================
        # [3/7] Fetch existing harvhub IDs
        # =====================================================================
        print("\n🔍 [3/7] Fetching Existing harvhub IDs...")
        existing_result = db.execute_query(
            "SELECT id FROM harvhub",
            wait_hint={'signal': 'table', 'timeout': 10},
        )
        existing_ids = set()
        if existing_result.get('status') == 'success':
            for row in existing_result.get('results', []):
                v = row.get('id')
                if v is not None:
                    existing_ids.add(str(v))
        print(f"  📊 Existing Records in harvhub: {len(existing_ids):,}")

        HARVHUB_EXCLUDED = {
            'analytics_history', 'revenue_history', 'reset_contract',
            'invested_with', 'accountmanagement', 'tier_limit',
            'mt5_folder_name', 'verified_at',
            'daily_target_met', 'daily_balance_log',
            'unauthorized_trades', 'authorized_trades',
            'id',
        }
        ANALYTICS_FIELDS = [
            'start_date', 'end_date', 'last_updated',
            'total_trades', 'total_pnl', 'profit_trades', 'loss_trades',
            'profit_amount', 'loss_amount',
            'lowest_trades_per_day', 'highest_trades_per_day', 'average_trades_per_day',
            'lowest_trades_per_week', 'highest_trades_per_week', 'average_trades_per_week',
            'highest_loss_per_trade', 'highest_drawdown', 'symbols_traded',
            'closed_deals_with_sl_tp', 'closed_deals_without_sl_tp',
            'consecutive_losses_count', 'total_loss_pnl',
            'consecutive_days_in_loss_count',
            'consecutive_days_in_loss_count_total_loss_pnl',
            'revenue_percentage', 'revenue_profit_percentage', 'revenue_loss_percentage',
        ]
        TRADE_FIELDS = ['symbol', 'entry', 'stoploss', 'target',
                        'ticket', 'pnl', 'closed_time']

        # =====================================================================
        # [4/7] Accumulator buffers
        # =====================================================================
        print(f"\n📤 [4/7] Processing records into all target tables...")
        print("-"*70)

        start_time = datetime.now()
        counters = {
            'harvhub_inserted': 0, 'harvhub_updated': 0, 'harvhub_failed': 0,
            'ia_inserted': 0, 'ia_updated': 0, 'ia_failed': 0,
            'dtr_users': 0, 'dtr_rows_updated': 0, 'dtr_rows_inserted': 0,
            'bl_users': 0,  'bl_rows_updated': 0,  'bl_rows_inserted': 0,
            'ut_users': 0,  'ut_rows_updated': 0,  'ut_rows_inserted': 0,
            'at_users': 0,  'at_rows_updated': 0,  'at_rows_inserted': 0,
        }
        harvhub_unmapped = set()
        ia_unmapped = set()

        # Cache for existing PKs per multi-row table: {userid: {match_key: pk_id}}
        existing_cache = {
            'daily_target_revenue': {},
            'balance_log': {},
            'unauthorized_trades': {},
            'authorized_trades': {},
        }

        # --- harvhub / investors_analytics buffers ---
        harvhub_updates = []   # list of (id_int, {col: literal})
        harvhub_inserts = []   # list of {col: literal, 'id': str}
        ia_updates = []        # list of (userid, {col: literal})
        ia_inserts = []        # list of {col: literal, 'userid': str}

        def flush_harvhub():
            nonlocal harvhub_updates, harvhub_inserts
            if harvhub_inserts:
                for grp in chunked(harvhub_inserts, BATCH_SIZE):
                    col_set = set()
                    for d in grp: col_set.update(d.keys())
                    all_cols = [c for c in ['id'] + sorted(col_set - {'id'}) if c in col_set or c == 'id']
                    # ensure id is first
                    all_cols = ['id'] + [c for c in all_cols if c != 'id']
                    vgroups = []
                    for d in grp:
                        vals = [d.get(c, 'NULL') for c in all_cols]
                        vgroups.append("(" + ", ".join(vals) + ")")
                    update_cols = [c for c in all_cols if c != 'id']
                    if update_cols:
                        tail = "ON DUPLICATE KEY UPDATE " + ", ".join(
                            f"`{c}` = VALUES(`{c}`)" for c in update_cols)
                    else:
                        tail = "ON DUPLICATE KEY UPDATE `id` = `id`"
                    q = (f"INSERT INTO harvhub "
                         f"({', '.join(f'`{c}`' for c in all_cols)}) "
                         f"VALUES {', '.join(vgroups)} {tail}")
                    r = db.execute_query(q, wait_hint={'signal': 'any-of', 'timeout': 25})
                    if r.get('status') == 'success':
                        counters['harvhub_inserted'] += len(grp)
                        for d in grp: existing_ids.add(d.get('id', '').strip("'"))
                    else:
                        counters['harvhub_failed'] += len(grp)
                harvhub_inserts = []

            if harvhub_updates:
                for grp in chunked(harvhub_updates, BATCH_SIZE):
                    col_set = set()
                    for _, d in grp: col_set.update(d.keys())
                    cols = sorted(col_set)
                    if not cols:
                        continue
                    ids = [str(rid) for rid, _ in grp]
                    case_parts = []
                    for c in cols:
                        whens = []
                        for rid, d in grp:
                            lit = d.get(c, 'NULL')
                            whens.append(f"WHEN {rid} THEN {lit}")
                        case_parts.append(f"`{c}` = CASE `id` {' '.join(whens)} END")
                    q = (f"UPDATE harvhub SET {', '.join(case_parts)} "
                         f"WHERE `id` IN ({', '.join(ids)})")
                    r = db.execute_query(q, wait_hint={'signal': 'any-of', 'timeout': 25})
                    if r.get('status') == 'success':
                        counters['harvhub_updated'] += len(grp)
                    else:
                        counters['harvhub_failed'] += len(grp)
                harvhub_updates = []

        def flush_investors_analytics():
            nonlocal ia_updates, ia_inserts
            if ia_inserts:
                for grp in chunked(ia_inserts, BATCH_SIZE):
                    col_set = set()
                    for d in grp: col_set.update(d.keys())
                    all_cols = ['userid'] + [
                        c for c in sorted(col_set) if c != 'userid'
                    ]
                    vgroups = []
                    for d in grp:
                        vals = [d.get(c, 'NULL') for c in all_cols]
                        vgroups.append("(" + ", ".join(vals) + ")")
                    update_cols = [c for c in all_cols if c != 'userid']
                    if update_cols:
                        tail = "ON DUPLICATE KEY UPDATE " + ", ".join(
                            f"`{c}` = VALUES(`{c}`)" for c in update_cols)
                    else:
                        tail = "ON DUPLICATE KEY UPDATE `userid` = `userid`"
                    q = (f"INSERT INTO investors_analytics "
                         f"({', '.join(f'`{c}`' for c in all_cols)}) "
                         f"VALUES {', '.join(vgroups)} {tail}")
                    r = db.execute_query(q, wait_hint={'signal': 'any-of', 'timeout': 25})
                    if r.get('status') == 'success':
                        counters['ia_inserted'] += len(grp)
                    else:
                        counters['ia_failed'] += len(grp)
                ia_inserts = []

            if ia_updates:
                for grp in chunked(ia_updates, BATCH_SIZE):
                    col_set = set()
                    for _, d in grp: col_set.update(d.keys())
                    cols = sorted(col_set)
                    if not cols:
                        continue
                    ids = [str(uid) for uid, _ in grp]
                    case_parts = []
                    for c in cols:
                        whens = []
                        for uid, d in grp:
                            lit = d.get(c, 'NULL')
                            whens.append(f"WHEN {uid} THEN {lit}")
                        case_parts.append(f"`{c}` = CASE `userid` {' '.join(whens)} END")
                    q = (f"UPDATE investors_analytics SET {', '.join(case_parts)} "
                         f"WHERE `userid` IN ({', '.join(ids)})")
                    r = db.execute_query(q, wait_hint={'signal': 'any-of', 'timeout': 25})
                    if r.get('status') == 'success':
                        counters['ia_updated'] += len(grp)
                    else:
                        counters['ia_failed'] += len(grp)
                ia_updates = []

        # =====================================================================
        # Main loop
        # =====================================================================
        total_to_update = len(merged_data)
        print(f"  🚀 Processing {total_to_update:,} record(s) in batches of {BATCH_SIZE}...")
        print()

        for index, (investor_id, investor) in enumerate(merged_data.items(), 1):
            if index % 50 == 0 or index == total_to_update:
                pct = (index / total_to_update) * 100
                bar_len = 30
                filled = int(bar_len * index // total_to_update)
                bar = '█' * filled + '░' * (bar_len - filled)
                print(f"  [{bar}] {pct:5.1f}% | {index:,}/{total_to_update:,}", end='\r')

            userid = to_int_safe(investor_id)
            if userid is None:
                continue
            if not isinstance(investor, dict):
                continue

            # ── (A) harvhub ──
            harvhub_payload = {}
            for field, value in investor.items():
                if field in HARVHUB_EXCLUDED:
                    continue
                if field.lower() not in harvhub_columns:
                    harvhub_unmapped.add(field); continue
                # get literal
                lit_kv = sql_kv(field, value)
                # extract RHS
                _, _, rhs = lit_kv.partition('=')
                harvhub_payload[field] = rhs.strip()

            if harvhub_payload:
                if str(investor_id) in existing_ids:
                    harvhub_updates.append((userid, harvhub_payload))
                else:
                    ins = dict(harvhub_payload)
                    ins['id'] = str(userid)
                    harvhub_inserts.append(ins)

            # ── (B) accountmanagement — INTENTIONALLY SKIPPED ──
            # accountmanagement is owned exclusively by fetch_investors().
            # We never write to it here so that any DB-side edits (or edits by
            # another service) are never clobbered by a stale JSON snapshot.
            # (No am_payload / am_inserts built; nothing flushed below.)

            # ── (C) investors_analytics ──
            analytics = investor.get('analytics')
            if isinstance(analytics, dict) and ia_columns:
                ia_payload = {}
                for f in ANALYTICS_FIELDS:
                    if f not in analytics: continue
                    if f.lower() not in ia_columns:
                        ia_unmapped.add(f); continue
                    val = analytics[f]
                    if f in ('start_date', 'end_date'):
                        val = coerce_date(val)
                    elif f == 'last_updated':
                        val = coerce_datetime(val)
                    lit_kv = sql_kv(f, val)
                    _, _, rhs = lit_kv.partition('=')
                    ia_payload[f] = rhs.strip()

                if ia_payload:
                    ins = dict(ia_payload)
                    ins['userid'] = str(userid)
                    ia_inserts.append(ins)

            # ── (D) daily_target_revenue ──
            dtm = investor.get('daily_target_met')
            if isinstance(dtm, dict) and dtr_columns:
                rows = []
                for wk_key, wk_val in dtm.items():
                    if not isinstance(wk_val, dict): continue
                    if not wk_key.lower().startswith('week_'): continue
                    for day_name, day_val in wk_val.items():
                        if not isinstance(day_val, dict): continue
                        rows.append({
                            'week': wk_key, 'day': day_name,
                            'date': day_val.get('date'),
                            'daily_target': day_val.get('daily_target'),
                            'status': day_val.get('status'),
                            'profit_allocated': day_val.get('profit_allocated'),
                            'remaining_needed': day_val.get('remaining_needed'),
                        })
                if rows:
                    u, i = sync_multi_row_table(
                        'daily_target_revenue', userid, rows,
                        columns=['week', 'day', 'date', 'daily_target',
                                 'status', 'profit_allocated', 'remaining_needed'],
                        pk_col='id',
                        existing_cache=existing_cache['daily_target_revenue'],
                        match_key_fn=lambda r: (str(r.get('week', '')),
                                                str(r.get('day', ''))),
                    )
                    counters['dtr_users'] += 1
                    counters['dtr_rows_updated'] += u
                    counters['dtr_rows_inserted'] += i

            # ── (E) balance_log ──
            dbl = investor.get('daily_balance_log')
            if isinstance(dbl, dict) and bl_columns:
                rows = []
                for day_key, day_val in dbl.items():
                    if not isinstance(day_val, dict): continue
                    rows.append({
                        'date': day_key,
                        'day_starting_balance': day_val.get('day_starting_balance'),
                        'day_authorized_trades_pnl': day_val.get('day_authorized_trades_pnl'),
                        'day_unauthorized_trades_pnl': day_val.get('day_unauthorized_trades_pnl'),
                        'day_unauthorized_withdrawals': day_val.get('day_unauthorized_withdrawals'),
                        'day_closing_balance': day_val.get('day_closing_balance'),
                        'unusual_activity': day_val.get('unusual_activity'),
                        'authorized_trades_count': day_val.get('authorized_trades_count'),
                        'unauthorized_trades_count': day_val.get('unauthorized_trades_count'),
                    })
                if rows:
                    u, i = sync_multi_row_table(
                        'balance_log', userid, rows,
                        columns=['date', 'day_starting_balance',
                                 'day_authorized_trades_pnl',
                                 'day_unauthorized_trades_pnl',
                                 'day_unauthorized_withdrawals',
                                 'day_closing_balance', 'unusual_activity',
                                 'authorized_trades_count', 'unauthorized_trades_count'],
                        pk_col='id',
                        existing_cache=existing_cache['balance_log'],
                        match_key_fn=lambda r: (str(r.get('date', '')),),
                    )
                    counters['bl_users'] += 1
                    counters['bl_rows_updated'] += u
                    counters['bl_rows_inserted'] += i

            # ── (F) unauthorized_trades ──
            ut = investor.get('unauthorized_trades')
            if isinstance(ut, list) and ut_columns:
                rows = [{f: t.get(f) for f in TRADE_FIELDS}
                        for t in ut if isinstance(t, dict)]
                if rows:
                    u, i = sync_multi_row_table(
                        'unauthorized_trades', userid, rows,
                        columns=TRADE_FIELDS, pk_col='id',
                        existing_cache=existing_cache['unauthorized_trades'],
                        match_key_fn=lambda r: (str(r.get('ticket', '')),),
                    )
                    counters['ut_users'] += 1
                    counters['ut_rows_updated'] += u
                    counters['ut_rows_inserted'] += i

            # ── (G) authorized_trades ──
            at = investor.get('authorized_trades')
            if isinstance(at, list) and at_columns:
                rows = [{f: t.get(f) for f in TRADE_FIELDS}
                        for t in at if isinstance(t, dict)]
                if rows:
                    u, i = sync_multi_row_table(
                        'authorized_trades', userid, rows,
                        columns=TRADE_FIELDS, pk_col='id',
                        existing_cache=existing_cache['authorized_trades'],
                        match_key_fn=lambda r: (str(r.get('ticket', '')),),
                    )
                    counters['at_users'] += 1
                    counters['at_rows_updated'] += u
                    counters['at_rows_inserted'] += i

            # ── Flush top-level single-row buffers ──
            if (len(harvhub_inserts) >= BATCH_SIZE or
                len(harvhub_updates) >= BATCH_SIZE or
                len(ia_inserts) >= BATCH_SIZE):
                flush_harvhub()
                flush_investors_analytics()

        # ── Final flush ──
        flush_harvhub()
        flush_investors_analytics()

        print()
        elapsed_time = (datetime.now() - start_time).total_seconds()

        # =====================================================================
        # Summary
        # =====================================================================
        print(f"\n💾 [5/7] Source files preserved (no deletion)")
        print(f"\n📋 [6/7] SPLIT-BACK UPDATE SUMMARY")
        print("="*70)
        print(f"\n  📊 harvhub:")
        print(f"     Inserted/Upserted : {counters['harvhub_inserted']:,}")
        print(f"     Updated           : {counters['harvhub_updated']:,}")
        print(f"     Failed            : {counters['harvhub_failed']:,}")
        print(f"     Skipped flds      : {len(harvhub_unmapped)}")
        print(f"\n  📊 accountmanagement:")
        print(f"     ⏭️  SKIPPED (fetch-only table — never written by updater)")
        print(f"\n  📊 investors_analytics:")
        print(f"     Inserted/Upserted : {counters['ia_inserted']:,}")
        print(f"     Updated           : {counters['ia_updated']:,}")
        print(f"     Failed            : {counters['ia_failed']:,}")
        print(f"     Skipped flds      : {len(ia_unmapped)}")
        print(f"\n  📊 daily_target_revenue:    Users: {counters['dtr_users']:,}  "
              f"UPDATED: {counters['dtr_rows_updated']:,}  INSERTED: {counters['dtr_rows_inserted']:,}")
        print(f"\n  📊 balance_log:             Users: {counters['bl_users']:,}  "
              f"UPDATED: {counters['bl_rows_updated']:,}  INSERTED: {counters['bl_rows_inserted']:,}")
        print(f"\n  📊 unauthorized_trades:     Users: {counters['ut_users']:,}  "
              f"UPDATED: {counters['ut_rows_updated']:,}  INSERTED: {counters['ut_rows_inserted']:,}")
        print(f"\n  📊 authorized_trades:       Users: {counters['at_users']:,}  "
              f"UPDATED: {counters['at_rows_updated']:,}  INSERTED: {counters['at_rows_inserted']:,}")
        print(f"\n  🚫 NO DELETE statements executed — rows kept and updated in place")
        print(f"  🚫 accountmanagement left untouched (owned by fetch_investors)")
        print(f"  ⏱️  Total Time : {elapsed_time:.1f}s")
        print(f"  🕐 Completion  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*70)

    except json.JSONDecodeError as e:
        print(f"\n{'='*70}\n   JSON PARSE ERROR\n{'='*70}\n  Error: {str(e)}\n{'='*70}")
    except PermissionError as e:
        print(f"\n{'='*70}\n   PERMISSION ERROR\n{'='*70}")
        print(f"  Error   : {type(e).__name__}\n  Message : {str(e)}")
        print(f"  File    : {e.filename if hasattr(e, 'filename') else 'Unknown'}\n{'='*70}")
        import traceback; traceback.print_exc()
    except Exception as e:
        print(f"\n{'='*70}\n   CRITICAL ERROR\n{'='*70}")
        print(f"  Error   : {type(e).__name__}\n  Message : {str(e)}\n{'='*70}")
        import traceback; traceback.print_exc()       

def close_db_browser():
    db.shutdown()
    print(f"\n🔒 Database connection closed.")
    
def create_investor_mt5_files(inv_id=None):
    """
    Creates MT5 terminal folders for investors by copying from DEFAULT_MT5_PATH.

    Guarantees:
      - The folder name, `Terminal_path`, and `mt5_folder_name` in the JSON
        always match what the current `broker` + `id` + `email` produce.
      - If any of the three disagree with the expected value, they are all
        rewritten (via updated_data → merge_create_results).
      - This check runs on EVERY invocation, whether the folder exists or not.

    Args:
        inv_id: Required - specific investor ID to process (for multiprocessing)

    Returns:
        dict: {
            'investor_id': str,
            'success': bool,
            'created': bool,
            'deleted': bool,
            'message': str,
            'updated_data': dict  # The updated investor data to merge
        }
    """

    import os
    import json
    import shutil
    import re
    import tempfile

    # MUST have inv_id for multiprocessing
    if inv_id is None:
        return {
            'investor_id': 'unknown',
            'success': False,
            'created': False,
            'deleted': False,
            'message': 'inv_id is required for multiprocessing',
            'updated_data': None
        }

    result = {
        'investor_id': str(inv_id),
        'success': False,
        'created': False,
        'deleted': False,
        'message': '',
        'updated_data': None
    }

    print(f"\n{'='*60}")
    print(f"📦 CREATE/MAINTAIN MT5 FILES - ID: {inv_id}")
    print(f"{'='*60}")

    # Check if source MT5 folder exists
    if not os.path.exists(DEFAULT_MT5_PATH) or not os.path.isdir(DEFAULT_MT5_PATH):
        msg = f"Source MT5 folder not found: {DEFAULT_MT5_PATH}"
        print(f" {msg}")
        result['message'] = msg
        return result

    # Check if fetched investors file exists
    if not os.path.exists(ALL_FETCHED_INVESTORS):
        msg = f"Fetched investors file not found: {ALL_FETCHED_INVESTORS}"
        print(f" {msg}")
        result['message'] = msg
        return result

    # Load suspended accounts (read-only)
    suspended_ids = set()
    suspended_data = {}
    if os.path.exists(SUSPENDED_ACCOUNTS):
        try:
            with open(SUSPENDED_ACCOUNTS, 'r', encoding='utf-8') as f:
                suspended_json = json.load(f)
                suspended_accounts = suspended_json.get('suspended_accounts', [])
                for account in suspended_accounts:
                    account_id = str(account.get('id')) if account.get('id') else None
                    if account_id:
                        suspended_ids.add(account_id)
                        suspended_data[account_id] = account
            if suspended_ids:
                print(f"🚫 Loaded {len(suspended_ids)} suspended/blacklisted accounts")
        except Exception as e:
            print(f"🛑 Error loading suspended accounts: {e}")
    else:
        print(f"ℹ️ No suspended accounts file found - all users will be processed normally")

    # Load fetched investors data (read-only)
    try:
        with open(ALL_FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
            investors_data = json.load(f)
        print(f"📋 Loaded investors data")
    except Exception as e:
        msg = f"Error loading investors: {e}"
        print(f" {msg}")
        result['message'] = msg
        return result

    inv_id_str = str(inv_id)
    if inv_id_str not in investors_data:
        msg = f"Investor {inv_id} not found in data"
        print(f" {msg}")
        result['message'] = msg
        return result

    # Work on a copy of the investor data
    investor_data = investors_data[inv_id_str].copy()
    investor_id_str = str(inv_id)

    # =========================================================================
    # RULE 1: Suspended / blacklisted → delete folder, clear paths
    # =========================================================================
    if investor_id_str in suspended_ids:
        broker = (investor_data.get('broker') or '').strip()
        investor_id_value = (investor_data.get('id') or '').strip()
        email = (investor_data.get('email') or '').strip()

        if broker and investor_id_value and email:
            safe_email = email.replace('@', '_at_').replace('.', '_dot_')
            safe_email = re.sub(r'[<>:"/\\|?*]', '_', safe_email)
            folder_name = f"MetaTrader 5 {safe_email} {investor_id_value} {broker}"
        elif broker and investor_id_value:
            folder_name = f"MetaTrader 5 {broker} {investor_id_value}"
        else:
            folder_name = ""

        target_folder = os.path.join(MT5_DESTINATION_PATH, folder_name) if folder_name else None

        if target_folder and os.path.exists(target_folder):
            try:
                print(f"🗑️  SUSPENDED ID:{inv_id} - Deleting active folder for blacklisted user...")
                shutil.rmtree(target_folder, ignore_errors=True)
                result['deleted'] = True
                result['message'] = "Suspended user - folder deleted"

                result['updated_data'] = {
                    inv_id_str: {
                        'Terminal_path': '',
                        'mt5_folder_name': ''
                    }
                }
                result['success'] = True

                temp_result_file = os.path.join(tempfile.gettempdir(), f"create_result_{inv_id}.json")
                with open(temp_result_file, 'w', encoding='utf-8') as f:
                    json.dump(result, f, indent=2)

                return result
            except Exception as e:
                msg = f"Failed to delete folder: {str(e)[:100]}"
                print(f"    {msg}")
                result['message'] = msg
                return result
        else:
            # Suspended but no folder to delete → still enforce empty paths
            msg = f"SUSPENDED ID:{inv_id} - Blacklisted, no folder to delete"
            print(f"🚫 {msg}")
            result['message'] = msg
            result['success'] = True
            result['updated_data'] = {
                inv_id_str: {
                    'Terminal_path': '',
                    'mt5_folder_name': ''
                }
            }
            temp_result_file = os.path.join(tempfile.gettempdir(), f"create_result_{inv_id}.json")
            with open(temp_result_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2)
            return result

    # =========================================================================
    # Extract fields from investor data
    # =========================================================================
    broker = (investor_data.get('broker') or '').strip()
    investor_id_value = (investor_data.get('id') or '').strip()
    email = (investor_data.get('email') or '').strip()

    if not broker or not investor_id_value:
        msg = f"Investor {inv_id} missing broker or id, skipping"
        print(f"🛑 {msg}")
        result['message'] = msg
        return result

    # Sanitize email for folder name
    if email:
        safe_email = email.replace('@', '_at_').replace('.', '_dot_')
        safe_email = re.sub(r'[<>:"/\\|?*]', '_', safe_email)
        print(f"📧 Email: {email} -> {safe_email}")
    else:
        safe_email = "no_email"
        print(f"🛑 ID:{inv_id} has no email address - using 'no_email' in folder name")

    # =========================================================================
    # Compute the EXPECTED folder name + path from current broker/id/email
    # =========================================================================
    folder_name = f"MetaTrader 5 {safe_email} {investor_id_value} {broker}"
    target_folder = os.path.join(MT5_DESTINATION_PATH, folder_name)
    target_exe = os.path.join(target_folder, "terminal64.exe")
    # NOTE: json.dump handles backslash escaping — do NOT double them here.
    normalized_path = target_exe

    # Normalized comparisons (case-insensitive on Windows, slash-insensitive)
    def _norm(p):
        if p is None:
            return ""
        return os.path.normcase(os.path.normpath(str(p).strip()))

    current_path = (investor_data.get('Terminal_path') or '').strip()
    current_folder = (investor_data.get('mt5_folder_name') or '').strip()

    path_matches = _norm(current_path) == _norm(normalized_path)
    folder_matches = current_folder == folder_name

    print(f"   Expected folder : {folder_name}")
    print(f"   Expected path   : {normalized_path}")
    print(f"   Current folder  : {current_folder or '(empty)'}")
    print(f"   Current path    : {current_path or '(empty)'}")
    print(f"   Path matches    : {path_matches}")
    print(f"   Folder matches  : {folder_matches}")

    folder_exists = os.path.exists(target_folder)
    current_status = investor_data.get('application_status', '')

    # =========================================================================
    # ALWAYS build the canonical update payload regardless of folder existence.
    # This ensures the JSON is monitored and corrected on every run.
    # =========================================================================
    update_data = {
        'Terminal_path': normalized_path,
        'mt5_folder_name': folder_name
    }

    if not path_matches:
        print(f"   🔧 Terminal_path corrected")
    else:
        print(f"   ✓ Terminal_path verified")

    if not folder_matches:
        print(f"   🔧 mt5_folder_name corrected")
    else:
        print(f"   ✓ mt5_folder_name verified")

    # Status transition (pending → just-joined) applies in both branches
    status_changed = False
    if current_status == "pending":
        update_data['application_status'] = 'just-joined'
        status_changed = True
        print(f"   🔄 Status: pending → just-joined")
    else:
        print(f"   ℹ️ Status: {current_status} (unchanged)")

    # =========================================================================
    # RULE 2: Folder exists → just emit the canonical + corrected values
    # =========================================================================
    if folder_exists:
        print(f"✓ Folder exists: {folder_name}")

        result['success'] = True
        result['created'] = False
        result['message'] = (
            "Folder exists | Terminal_path " +
            ("corrected" if not path_matches else "verified") +
            " | mt5_folder_name " +
            ("corrected" if not folder_matches else "verified") +
            (" | Status: pending → just-joined" if status_changed else "")
        )
        result['updated_data'] = {inv_id_str: update_data}

        temp_result_file = os.path.join(tempfile.gettempdir(), f"create_result_{inv_id}.json")
        with open(temp_result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2)

        return result

    # =========================================================================
    # RULE 3: Folder missing → create it, then emit fresh canonical values
    # =========================================================================
    print(f"🆕 Creating new folder: {folder_name}")
    print(f"   Email: {email}")
    print(f"   Broker: {broker}")
    print(f"   ID: {investor_id_value}")

    try:
        print(f"   📁 Copying from {DEFAULT_MT5_PATH}...")
        shutil.copytree(
            DEFAULT_MT5_PATH,
            target_folder,
            ignore_dangling_symlinks=True,
            ignore=shutil.ignore_patterns('*.lock', '*.log'),
        )

        result['message'] = (
            "Folder created" +
            (" | Status: pending → just-joined" if status_changed else f" | Status kept: {current_status}")
        )

        result['success'] = True
        result['created'] = True
        result['updated_data'] = {inv_id_str: update_data}

        print(f"   ✅ Folder created successfully!")
        print(f"   📍 Path: {normalized_path[:100]}...")

        temp_result_file = os.path.join(tempfile.gettempdir(), f"create_result_{inv_id}.json")
        with open(temp_result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2)

        return result

    except Exception as e:
        msg = f"Failed to copy folder: {str(e)[:200]}"
        print(f"    {msg}")
        result['message'] = msg

        if os.path.exists(target_folder):
            try:
                shutil.rmtree(target_folder, ignore_errors=True)
                print(f"   🧹 Cleaned up partial folder")
            except Exception:
                pass

        return result  
   
def merge_create_results():
    """
    Merge all individual MT5 folder creation results from temp files back to
    ALL_FETCHED_INVESTORS, then propagate the same updates to every other
    investor file (ALL_INVESTORS, ALL_UPDATED_INVESTORS, INVHARV_FETCHED_INVESTORS,
    HARVHUB_FETCHED_INVESTORS, INVHARV_UPDATED_INVESTORS, HARVHUB_UPDATED_INVESTORS,
    ALL_INVESTORS_BACKUP). Each target file is updated only if the investor ID is found.
    """
    import os
    import json
    import tempfile
    import shutil
    import glob

    print(f"\n{'='*60}")
    print(f"📦 MERGING MT5 FOLDER CREATION RESULTS")
    print(f"{'='*60}")

    if not os.path.exists(ALL_FETCHED_INVESTORS):
        print(f" Fetched investors file not found")
        return {'total_processed': 0, 'created': 0, 'deleted': 0, 'updated': 0, 'errors': 0}

    try:
        with open(ALL_FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
            investors_data = json.load(f)
        print(f"📋 Loaded current investors data")
    except Exception as e:
        print(f" Error loading investors: {e}")
        return {'total_processed': 0, 'created': 0, 'deleted': 0, 'updated': 0, 'errors': 0}

    temp_dir = tempfile.gettempdir()
    result_files = glob.glob(os.path.join(temp_dir, "create_result_*.json"))

    stats = {
        'total_processed': len(result_files),
        'created': 0,
        'deleted': 0,
        'updated': 0,
        'errors': 0
    }

    # Collector of per-investor field updates to propagate to all other files
    propagated_updates = {}   # {investor_id: {field: value}}

    print(f"\n📁 Found {len(result_files)} result files to merge")

    for result_file in result_files:
        try:
            with open(result_file, 'r', encoding='utf-8') as f:
                result = json.load(f)

            if result.get('success') and result.get('updated_data'):
                investor_id = result['investor_id']
                updated_data = result['updated_data']

                if investor_id in investors_data:
                    new_data = updated_data.get(investor_id, {})
                    old_data = investors_data[investor_id]

                    updated = False
                    for field, value in new_data.items():
                        if field in old_data and value != old_data.get(field):
                            investors_data[investor_id][field] = value
                            updated = True
                            propagated_updates.setdefault(investor_id, {})[field] = value
                            print(f"   🔄 Updated {field} for investor {investor_id}")
                        elif field not in old_data:
                            investors_data[investor_id][field] = value
                            updated = True
                            propagated_updates.setdefault(investor_id, {})[field] = value
                            print(f"   ➕ Added {field} for investor {investor_id}")

                    if result.get('created'):
                        stats['created'] += 1
                    elif result.get('deleted'):
                        stats['deleted'] += 1
                    elif updated:
                        stats['updated'] += 1

                    if updated or result.get('created') or result.get('deleted'):
                        print(f"✅ Merged update for investor {investor_id}: {result.get('message', '')[:60]}")
                else:
                    investors_data[investor_id] = updated_data.get(investor_id, {})
                    stats['created'] += 1
                    propagated_updates[investor_id] = dict(updated_data.get(investor_id, {}))
                    print(f"➕ Added new investor {investor_id}")
            else:
                stats['errors'] += 1
                print(f"🛑 Failed result for investor {result.get('investor_id', 'unknown')}: {result.get('message', 'No message')}")

            try:
                os.remove(result_file)
            except:
                pass

        except Exception as e:
            stats['errors'] += 1
            print(f"🛑 Error processing {result_file}: {e}")

    # Save merged data if there were changes
    if stats['total_processed'] > 0 and stats['errors'] < stats['total_processed']:
        backup_path = ALL_FETCHED_INVESTORS.replace('.json', '_backup.json')
        if not os.path.exists(backup_path):
            shutil.copy2(ALL_FETCHED_INVESTORS, backup_path)
            print(f"\n📦 Created backup: {backup_path}")

        with open(ALL_FETCHED_INVESTORS, 'w', encoding='utf-8') as f:
            json.dump(investors_data, f, indent=2)

        print(f"\n💾 Saved merged data to {ALL_FETCHED_INVESTORS}")

        # ------------------------------------------------------------
        # PROPAGATE to every other investor file if the ID is found
        # ------------------------------------------------------------
        if propagated_updates:
            other_targets = [
                ("ALL_INVESTORS", ALL_INVESTORS),
                ("ALL_UPDATED_INVESTORS", ALL_UPDATED_INVESTORS),
                ("INVHARV_FETCHED_INVESTORS", INVHARV_FETCHED_INVESTORS),
                ("HARVHUB_FETCHED_INVESTORS", HARVHUB_FETCHED_INVESTORS),
                ("INVHARV_UPDATED_INVESTORS", INVHARV_UPDATED_INVESTORS),
                ("HARVHUB_UPDATED_INVESTORS", HARVHUB_UPDATED_INVESTORS),
                ("ALL_INVESTORS_BACKUP", ALL_INVESTORS_BACKUP),
            ]

            print(f"\n📤 Propagating folder-creation updates to other investor files...")

            for target_name, target_path in other_targets:
                if not os.path.exists(target_path):
                    print(f"   ℹ️  {target_name}: not found, skipping")
                    continue
                try:
                    with open(target_path, 'r', encoding='utf-8') as f:
                        target_data = json.load(f)
                    if not isinstance(target_data, dict):
                        print(f"   ⚠️  {target_name}: invalid format, skipping")
                        continue
                except Exception as e:
                    print(f"   ⚠️  {target_name}: could not load ({e}), skipping")
                    continue

                changed = 0
                for inv_id, fields in propagated_updates.items():
                    if inv_id not in target_data:
                        continue
                    if not isinstance(target_data[inv_id], dict):
                        continue
                    for field, value in fields.items():
                        if target_data[inv_id].get(field) != value:
                            target_data[inv_id][field] = value
                            changed += 1

                if changed > 0:
                    try:
                        with open(target_path, 'w', encoding='utf-8') as f:
                            json.dump(target_data, f, indent=2, ensure_ascii=False)
                        print(f"   ✅ {target_name}: {changed} field(s) updated")
                    except Exception as e:
                        print(f"   ❌ {target_name}: save failed ({e})")
                else:
                    print(f"   ℹ️  {target_name}: no matching IDs / no changes")
        else:
            print(f"\nℹ️ No propagated updates (nothing changed)")
    else:
        print(f"\n🛑 No valid updates to save")

    print(f"\n{'='*60}")
    print(f"📊 MERGE SUMMARY - MT5 FOLDER CREATION")
    print(f"{'='*60}")
    print(f"   Total processed    : {stats['total_processed']}")
    print(f"   ✅ Created folders  : {stats['created']}")
    print(f"   🗑️  Deleted folders  : {stats['deleted']}")
    print(f"   🔧 Updated paths    : {stats['updated']}")
    print(f"    Errors           : {stats['errors']}")
    print(f"{'='*60}")

    return stats

def get_investors_balance(inv_id=None):
    """
    Get account balance for investors by directly reading from already initialized MT5.
    
    Args:
        inv_id: Required - specific investor ID to process.
    
    Returns:
        dict: {
            'investor_id': str,
            'success': bool,
            'status': str,
            'balance': float,
            'message': str,
            'updated_data': dict  # The updated investor data to merge
        }
    """
    
    import os
    import json
    import time
    import tempfile
    from datetime import datetime
    
    # MUST have inv_id for multiprocessing
    if inv_id is None:
        return {
            'investor_id': 'unknown',
            'success': False,
            'status': 'error',
            'balance': None,
            'message': 'inv_id is required for multiprocessing',
            'updated_data': None
        }
    
    result = {
        'investor_id': str(inv_id),
        'success': False,
        'status': 'not_processed',
        'balance': None,
        'message': '',
        'updated_data': None
    }
    
    print(f"\n{'='*60}")
    print(f"💰 GET BALANCE - ID: {inv_id}")
    print(f"{'='*60}")
    
    # Check if fetched investors file exists
    if not os.path.exists(ALL_FETCHED_INVESTORS):
        msg = f"Fetched investors file not found: {ALL_FETCHED_INVESTORS}"
        print(f"❌ {msg}")
        result['message'] = msg
        return result
    
    # Load investors data (read-only, no lock needed for reading)
    try:
        with open(ALL_FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
            investors_data = json.load(f)
        print(f"📋 Loaded investors data with {len(investors_data)} investors")
    except Exception as e:
        print(f"❌ Error loading investors: {e}")
        result['message'] = f"Error loading investors: {e}"
        return result
    
    inv_id_str = str(inv_id)
    
    # Find investor - try both string and integer keys
    investor_data = None
    actual_key = None
    
    if inv_id_str in investors_data:
        investor_data = investors_data[inv_id_str]
        actual_key = inv_id_str
    elif inv_id in investors_data:
        investor_data = investors_data[inv_id]
        actual_key = inv_id
    else:
        # Try to find by converting keys to int
        for key in investors_data.keys():
            try:
                if int(key) == int(inv_id):
                    investor_data = investors_data[key]
                    actual_key = key
                    break
            except (ValueError, TypeError):
                continue
    
    if investor_data is None:
        msg = f"Investor {inv_id} not found in data"
        print(f"❌ {msg}")
        result['message'] = msg
        return result
    
    investor_data = investor_data.copy()  # Work on a copy
    app_status = investor_data.get('application_status', '').strip()
    
    # STRICT SKIP - Only proceed if status is EXACTLY 'just-joined'
    if app_status != 'just-joined':
        print(f"⏭️ ID:{inv_id} → Status: '{app_status}' (not 'just-joined') - SKIPPING")
        result['message'] = f"Status is '{app_status}', not 'just-joined'"
        return result
    
    # ACCOUNT MODE AND DEMO PERMISSION CHECK
    account_mode = investor_data.get('account_mode', '').strip().lower()
    demo_account = investor_data.get('demo_account', '').strip()
    
    print(f"📊 Account mode: {account_mode}, Demo account: {demo_account}")
    
    if account_mode == 'demo':
        if demo_account == '0':
            msg = "DEMO account disabled (demo_account=0)"
            print(f"⏭️ ID:{inv_id} → {msg} - Skipping")
            result['message'] = msg
            return result
        elif demo_account == '1':
            print(f"✅ ID:{inv_id} → DEMO account with demo_account=1 (ENABLED) - Proceeding")
        else:
            msg = f"DEMO account but demo_account not set to '1'"
            print(f"⏭️ ID:{inv_id} → {msg} - Skipping")
            result['message'] = msg
            return result
    elif account_mode == 'real':
        print(f"✅ ID:{inv_id} → REAL account - Proceeding")
    else:
        msg = f"Unknown account mode: {account_mode}"
        print(f"⏭️ ID:{inv_id} → {msg} - Skipping")
        result['message'] = msg
        return result
    
    # Extract credentials (only needed for validation, not for login)
    login_id = investor_data.get('login', '') or investor_data.get('LOGIN_ID', '')
    broker_password = investor_data.get('broker_password', '') or investor_data.get('broker_password', '')
    server = investor_data.get('server', '') or investor_data.get('SERVER', '')
    Terminal_path = investor_data.get('Terminal_path', '')
    email = investor_data.get('email', 'No Email')
    
    print(f"📊 Credentials: Login={login_id}, Server={server}")
    
    if not all([login_id, broker_password, server, Terminal_path]):
        missing = []
        if not login_id: missing.append('login')
        if not broker_password: missing.append('broker_password')
        if not server: missing.append('server')
        if not Terminal_path: missing.append('Terminal_path')
        msg = f"Missing credentials: {', '.join(missing)}"
        print(f"❌ ID:{inv_id} → {msg}")
        result['message'] = msg
        return result
    
    try:
        login_id_int = int(login_id)
    except (ValueError, TypeError):
        msg = f"Invalid LOGIN_ID: {login_id}"
        print(f"❌ ID:{inv_id} → {msg}")
        result['message'] = msg
        return result
    
    # TERMINAL PATH VALIDATION
    if not Terminal_path:
        msg = "Terminal_path is missing"
        print(f"❌ ID:{inv_id} → {msg}")
        result['message'] = msg
        return result
    
    if not os.path.exists(Terminal_path):
        msg = f"Terminal not found: {Terminal_path}"
        print(f"❌ ID:{inv_id} → {msg}")
        result['message'] = msg
        return result
    
    print(f"✅ Terminal path exists: {Terminal_path}")
    
    print(f"\n✅ ID:{inv_id} ({email}) (Login:{login_id_int}) - Getting balance...")
    
    # DIRECT BALANCE RETRIEVAL - NO INITIALIZATION OR LOGIN NEEDED
    balance = None
    currency = None
    success = False
    
    try:
        # Get account info directly from already initialized MT5
        account_info = mt5.account_info()
        
        if account_info is None:
            print(f"   ❌ No account info available - MT5 may not be initialized")
            result['message'] = "MT5 not initialized or no account info"
            return result
        
        # Verify this is the correct account
        if account_info.login != login_id_int:
            print(f"   🛑 Account mismatch: Connected to {account_info.login}, expected {login_id_int}")
            result['message'] = f"Account mismatch: Connected to {account_info.login}, expected {login_id_int}"
            return result
        
        # Determine account mode
        if account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL:
            actual_account_mode = 'real'
        elif account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO:
            actual_account_mode = 'demo'
        elif account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_CONTEST:
            actual_account_mode = 'demo'
        else:
            actual_account_mode = 'unknown'
        
        print(f"   ✅ Connected to account: {account_info.login} ({email})")
        print(f"      → Account type: {actual_account_mode.upper()}")
        
        # Check demo permissions
        if actual_account_mode == 'demo':
            if demo_account == '0':
                print(f"      → ⏭️ SKIPPING: DEMO account disabled")
                result['message'] = "DEMO account disabled"
                return result
            elif demo_account != '1':
                print(f"      → ⏭️ SKIPPING: DEMO account not enabled")
                result['message'] = "DEMO account not enabled"
                return result
        
        # Get balance
        balance = account_info.balance
        currency = account_info.currency
        
        balance_str = f"{balance:.2f}"
        
        # Prepare update data (only fields that changed)
        update_data = {
            'broker_balance': balance_str,
            'application_status': 'just-joined-and-valid_credentials',
            'verified_at': time.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        if investor_data.get('account_mode', '').strip().lower() != actual_account_mode:
            update_data['account_mode'] = actual_account_mode
        
        success = True
        result['success'] = True
        result['status'] = 'just-joined-and-valid_credentials'
        result['balance'] = balance
        result['message'] = f"Balance obtained: {currency} {balance:,.2f}"
        result['updated_data'] = {actual_key: update_data}
        
        print(f"   ✅ Balance obtained: {currency} {balance:,.2f}")
        
        # Save individual result to temp file
        temp_result_file = os.path.join(tempfile.gettempdir(), f"balance_result_{inv_id}.json")
        with open(temp_result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2)
        print(f"   💾 Saved result to: {temp_result_file}")
        
        return result
        
    except Exception as e:
        error_msg = f"Error: {str(e)[:100]}"
        print(f"   ❌ {error_msg}")
        result['message'] = error_msg
        return result
      
def merge_balance_results():
    """
    Merge all individual balance results from temp files back to
    ALL_FETCHED_INVESTORS, then propagate the same updates to every other
    investor file (ALL_INVESTORS, ALL_UPDATED_INVESTORS, INVHARV_FETCHED_INVESTORS,
    HARVHUB_FETCHED_INVESTORS, INVHARV_UPDATED_INVESTORS, HARVHUB_UPDATED_INVESTORS,
    ALL_INVESTORS_BACKUP). Each target file is updated only if the investor ID is found.
    """
    import os
    import json
    import tempfile
    import shutil
    import glob

    print(f"\n{'='*60}")
    print(f"📦 MERGING BALANCE RESULTS")
    print(f"{'='*60}")

    if not os.path.exists(ALL_FETCHED_INVESTORS):
        print(f" Fetched investors file not found")
        return {'total_processed': 0, 'updated': 0, 'errors': 0}

    try:
        with open(ALL_FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
            investors_data = json.load(f)
    except Exception as e:
        print(f" Error loading investors: {e}")
        return {'total_processed': 0, 'updated': 0, 'errors': 0}

    temp_dir = tempfile.gettempdir()
    result_files = glob.glob(os.path.join(temp_dir, "balance_result_*.json"))

    stats = {
        'total_processed': len(result_files),
        'updated': 0,
        'errors': 0
    }

    propagated_updates = {}   # {investor_id: {field: value}}

    print(f"\n📁 Found {len(result_files)} balance result files to merge")

    for result_file in result_files:
        try:
            with open(result_file, 'r', encoding='utf-8') as f:
                result = json.load(f)

            if result.get('success') and result.get('updated_data'):
                investor_id = result['investor_id']
                updated_data = result['updated_data']

                if investor_id in investors_data:
                    new_data = updated_data.get(investor_id, {})
                    old_data = investors_data[investor_id]

                    updated = False
                    for field, value in new_data.items():
                        if field in old_data and value != old_data.get(field):
                            investors_data[investor_id][field] = value
                            updated = True
                            propagated_updates.setdefault(investor_id, {})[field] = value
                            print(f"   🔄 Updated {field} for investor {investor_id}")
                        elif field not in old_data:
                            investors_data[investor_id][field] = value
                            updated = True
                            propagated_updates.setdefault(investor_id, {})[field] = value
                            print(f"   ➕ Added {field} for investor {investor_id}")

                    if updated:
                        stats['updated'] += 1
                        print(f"✅ Merged balance update for investor {investor_id}: {result.get('message', '')[:50]}")
                else:
                    investors_data[investor_id] = updated_data.get(investor_id, {})
                    stats['updated'] += 1
                    propagated_updates[investor_id] = dict(updated_data.get(investor_id, {}))
                    print(f"➕ Added new investor {investor_id}")

            try:
                os.remove(result_file)
            except:
                pass

        except Exception as e:
            stats['errors'] += 1
            print(f"🛑 Error processing {result_file}: {e}")

    if stats['updated'] > 0:
        backup_path = ALL_FETCHED_INVESTORS.replace('.json', '_backup.json')
        if not os.path.exists(backup_path):
            shutil.copy2(ALL_FETCHED_INVESTORS, backup_path)
            print(f"📦 Created backup: {backup_path}")

        with open(ALL_FETCHED_INVESTORS, 'w', encoding='utf-8') as f:
            json.dump(investors_data, f, indent=2)

        print(f"\n💾 Saved {stats['updated']} updates to {ALL_FETCHED_INVESTORS}")

        # Refresh ALL_UPDATED_INVESTORS subset (existing behavior kept)
        updated_investors_data = {}
        for investor_id, investor_data in investors_data.items():
            app_status = investor_data.get('application_status', '').strip().lower()
            if app_status == 'just-joined-and-valid_credentials':
                updated_investors_data[investor_id] = investor_data

        if updated_investors_data:
            with open(ALL_UPDATED_INVESTORS, 'w', encoding='utf-8') as f:
                json.dump(updated_investors_data, f, indent=2)
            print(f"💾 Updated {len(updated_investors_data)} investors to {ALL_UPDATED_INVESTORS}")

        # ------------------------------------------------------------
        # PROPAGATE to every other investor file if the ID is found
        # ------------------------------------------------------------
        if propagated_updates:
            other_targets = [
                ("ALL_INVESTORS", ALL_INVESTORS),
                ("ALL_UPDATED_INVESTORS", ALL_UPDATED_INVESTORS),
                ("INVHARV_FETCHED_INVESTORS", INVHARV_FETCHED_INVESTORS),
                ("HARVHUB_FETCHED_INVESTORS", HARVHUB_FETCHED_INVESTORS),
                ("INVHARV_UPDATED_INVESTORS", INVHARV_UPDATED_INVESTORS),
                ("HARVHUB_UPDATED_INVESTORS", HARVHUB_UPDATED_INVESTORS),
                ("ALL_INVESTORS_BACKUP", ALL_INVESTORS_BACKUP),
            ]

            print(f"\n📤 Propagating balance updates to other investor files...")

            for target_name, target_path in other_targets:
                if not os.path.exists(target_path):
                    print(f"   ℹ️  {target_name}: not found, skipping")
                    continue
                try:
                    with open(target_path, 'r', encoding='utf-8') as f:
                        target_data = json.load(f)
                    if not isinstance(target_data, dict):
                        print(f"   ⚠️  {target_name}: invalid format, skipping")
                        continue
                except Exception as e:
                    print(f"   ⚠️  {target_name}: could not load ({e}), skipping")
                    continue

                changed = 0
                for inv_id, fields in propagated_updates.items():
                    if inv_id not in target_data:
                        continue
                    if not isinstance(target_data[inv_id], dict):
                        continue
                    for field, value in fields.items():
                        if target_data[inv_id].get(field) != value:
                            target_data[inv_id][field] = value
                            changed += 1

                if changed > 0:
                    try:
                        with open(target_path, 'w', encoding='utf-8') as f:
                            json.dump(target_data, f, indent=2, ensure_ascii=False)
                        print(f"   ✅ {target_name}: {changed} field(s) updated")
                    except Exception as e:
                        print(f"   ❌ {target_name}: save failed ({e})")
                else:
                    print(f"   ℹ️  {target_name}: no matching IDs / no changes")
        else:
            print(f"\nℹ️ No propagated updates (nothing changed)")

        print(f"\n📊 Merge Summary:")
        print(f"   ✅ Updated: {stats['updated']}")
        print(f"   🛑 Errors: {stats['errors']}")
        return stats
    else:
        print(f"ℹ️ No updates to merge")
        return stats
       
def verify_investors_balance(inv_id=None):
    """
    Verify balance for investors who have applied for verification.
    
    Args:
        inv_id: Required - specific investor ID to process.
    
    Returns:
        dict: {
            'investor_id': str,
            'success': bool,
            'status': str,
            'balance': float,
            'message': str,
            'updated_data': dict
        }
    """
    
    import os
    import json
    import time
    import tempfile
    import MetaTrader5 as mt5
    
    # MUST have inv_id for multiprocessing
    if inv_id is None:
        return {
            'investor_id': 'unknown',
            'success': False,
            'status': 'error',
            'balance': None,
            'message': 'inv_id is required for multiprocessing',
            'updated_data': None
        }
    
    result = {
        'investor_id': str(inv_id),
        'success': False,
        'status': 'not_processed',
        'balance': None,
        'message': '',
        'updated_data': None
    }
    
    print(f"\n{'='*60}")
    print(f"🔐 BALANCE VERIFICATION - ID: {inv_id}")
    print(f"{'='*60}")
    
    if not os.path.exists(ALL_FETCHED_INVESTORS):
        msg = f"Fetched investors file not found: {ALL_FETCHED_INVESTORS}"
        print(f"❌ {msg}")
        result['message'] = msg
        return result
    
    # Load investors data
    try:
        with open(ALL_FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
            investors_data = json.load(f)
        print(f"📋 Loaded investors data with {len(investors_data)} investors")
    except Exception as e:
        print(f"❌ Error loading investors: {e}")
        result['message'] = f"Error loading investors: {e}"
        return result
    
    inv_id_str = str(inv_id)
    
    # Find investor - try both string and integer keys
    investor_data = None
    actual_key = None
    
    if inv_id_str in investors_data:
        investor_data = investors_data[inv_id_str]
        actual_key = inv_id_str
    elif inv_id in investors_data:
        investor_data = investors_data[inv_id]
        actual_key = inv_id
    else:
        # Try to find by converting keys to int
        for key in investors_data.keys():
            try:
                if int(key) == int(inv_id):
                    investor_data = investors_data[key]
                    actual_key = key
                    break
            except (ValueError, TypeError):
                continue
    
    if investor_data is None:
        msg = f"Investor {inv_id} not found"
        print(f"❌ {msg}")
        result['message'] = msg
        return result
    
    print(f"✅ Found investor with key: {actual_key}")
    investor_data = investor_data.copy()
    
    # Check if applied for verification
    balance_verification_status = investor_data.get('balance_verification', '').strip().lower()
    verification_statuses = ['applied-for-verification', 'applied_for_verification', 'applied']
    
    if balance_verification_status not in verification_statuses:
        msg = f"Not applied for verification (status: {balance_verification_status})"
        print(f"⏭️ {msg}")
        result['message'] = msg
        result['status'] = 'not_applied'
        return result
    
    # CHECK DEMO ACCOUNT SETTINGS
    account_mode = investor_data.get('account_mode', '').strip().lower()
    demo_account = investor_data.get('demo_account', '').strip()
    
    print(f"📊 Account mode: {account_mode}, Demo account: {demo_account}")
    
    if account_mode == 'demo':
        if demo_account == '0':
            msg = "DEMO account disabled (demo_account=0)"
            print(f"⏭️ {msg}")
            result['message'] = msg
            result['status'] = 'demo_disabled'
            return result
        elif demo_account != '1':
            msg = "DEMO account not enabled"
            print(f"⏭️ {msg}")
            result['message'] = msg
            result['status'] = 'demo_not_enabled'
            return result
    
    # CHECK TERMINAL PATH
    Terminal_path = investor_data.get('Terminal_path', '')
    
    if not Terminal_path:
        msg = "Terminal_path is missing"
        print(f"❌ {msg}")
        result['message'] = msg
        return result
    
    if not os.path.exists(Terminal_path):
        msg = f"Terminal not found: {Terminal_path}"
        print(f"❌ {msg}")
        result['message'] = msg
        return result
    
    print(f"✅ Terminal path exists: {Terminal_path}")
    
    # GET BALANCE DIRECTLY - NO LOGIN NEEDED
    try:
        # Just get account info - MT5 is already initialized globally
        account_info = mt5.account_info()
        
        if account_info is None:
            print(f"   ❌ MT5 not initialized or no account info")
            result['message'] = "MT5 not initialized or no account info"
            return result
        
        # Get the balance directly
        balance = account_info.balance
        currency = account_info.currency
        
        # CHECK ACCOUNT MODE FROM MT5
        if account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL:
            actual_account_mode = 'real'
        elif account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO:
            actual_account_mode = 'demo'
        elif account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_CONTEST:
            actual_account_mode = 'demo'
        else:
            actual_account_mode = 'unknown'
        
        print(f"   ✅ Connected to account: {account_info.login}")
        print(f"      → Account type: {actual_account_mode.upper()}")
        print(f"      → Balance: {currency} {balance:,.2f}")
        
        # Verify demo account matches
        if actual_account_mode == 'demo':
            if demo_account == '0':
                msg = "DEMO account disabled in settings"
                print(f"      → ⏭️ SKIPPING: {msg}")
                result['message'] = msg
                result['status'] = 'demo_disabled'
                return result
            elif demo_account != '1':
                msg = "DEMO account not enabled in settings"
                print(f"      → ⏭️ SKIPPING: {msg}")
                result['message'] = msg
                result['status'] = 'demo_not_enabled'
                return result
        
        # Prepare update data (only fields that changed)
        update_data = {
            'broker_balance': f"{balance:.2f}",
            'balance_verification': 'verified',
            'verified_at': time.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        if investor_data.get('account_mode', '').strip().lower() != actual_account_mode:
            update_data['account_mode'] = actual_account_mode
        
        result['success'] = True
        result['status'] = 'verified'
        result['balance'] = balance
        result['message'] = f"Verified: {currency} {balance:,.2f}"
        result['updated_data'] = {actual_key: update_data}
        
        print(f"   ✅ VERIFIED: {currency} {balance:,.2f}")
        
        # Save individual result to temp file
        temp_result_file = os.path.join(tempfile.gettempdir(), f"verify_result_{inv_id}.json")
        with open(temp_result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2)
        
        return result
        
    except Exception as e:
        error_msg = f"Error getting balance: {str(e)[:100]}"
        print(f"   ❌ {error_msg}")
        result['message'] = error_msg
        return result
      
def merge_verify_results():
    """
    Merge all individual verification results from temp files back to
    ALL_FETCHED_INVESTORS, then propagate the same updates to every other
    investor file (ALL_INVESTORS, ALL_UPDATED_INVESTORS, INVHARV_FETCHED_INVESTORS,
    HARVHUB_FETCHED_INVESTORS, INVHARV_UPDATED_INVESTORS, HARVHUB_UPDATED_INVESTORS,
    ALL_INVESTORS_BACKUP). Each target file is updated only if the investor ID is found.
    """
    import os
    import json
    import tempfile
    import shutil
    import glob

    print(f"\n{'='*60}")
    print(f"📦 MERGING VERIFICATION RESULTS")
    print(f"{'='*60}")

    if not os.path.exists(ALL_FETCHED_INVESTORS):
        print(f" Fetched investors file not found")
        return {'total_processed': 0, 'verified': 0, 'errors': 0}

    try:
        with open(ALL_FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
            investors_data = json.load(f)
    except Exception as e:
        print(f" Error loading investors: {e}")
        return {'total_processed': 0, 'verified': 0, 'errors': 0}

    temp_dir = tempfile.gettempdir()
    result_files = glob.glob(os.path.join(temp_dir, "verify_result_*.json"))

    stats = {
        'total_processed': len(result_files),
        'verified': 0,
        'errors': 0
    }

    propagated_updates = {}   # {investor_id: {field: value}}

    print(f"\n📁 Found {len(result_files)} verification result files to merge")

    for result_file in result_files:
        try:
            with open(result_file, 'r', encoding='utf-8') as f:
                result = json.load(f)

            # Only merge if verification was successful and status is 'verified'
            if result.get('success') and result.get('status') == 'verified' and result.get('updated_data'):
                investor_id = result['investor_id']
                updated_data = result['updated_data']

                if investor_id in investors_data:
                    new_data = updated_data.get(investor_id, {})
                    old_data = investors_data[investor_id]

                    updated = False
                    for field, value in new_data.items():
                        if field in old_data and value != old_data.get(field):
                            investors_data[investor_id][field] = value
                            updated = True
                            propagated_updates.setdefault(investor_id, {})[field] = value
                            print(f"   🔄 Updated {field} for investor {investor_id}")
                        elif field not in old_data:
                            investors_data[investor_id][field] = value
                            updated = True
                            propagated_updates.setdefault(investor_id, {})[field] = value
                            print(f"   ➕ Added {field} for investor {investor_id}")

                    if updated:
                        stats['verified'] += 1
                        print(f"✅ Merged verification for investor {investor_id}: {result.get('message', '')[:50]}")
                else:
                    investors_data[investor_id] = updated_data.get(investor_id, {})
                    stats['verified'] += 1
                    propagated_updates[investor_id] = dict(updated_data.get(investor_id, {}))
                    print(f"➕ Added new investor {investor_id}")

            try:
                os.remove(result_file)
            except:
                pass

        except Exception as e:
            stats['errors'] += 1
            print(f"🛑 Error processing {result_file}: {e}")

    if stats['verified'] > 0:
        backup_path = ALL_FETCHED_INVESTORS.replace('.json', '_backup.json')
        if not os.path.exists(backup_path):
            shutil.copy2(ALL_FETCHED_INVESTORS, backup_path)
            print(f"📦 Created backup: {backup_path}")

        with open(ALL_FETCHED_INVESTORS, 'w', encoding='utf-8') as f:
            json.dump(investors_data, f, indent=2)

        print(f"\n💾 Saved {stats['verified']} verification updates to {ALL_FETCHED_INVESTORS}")

        # Refresh ALL_UPDATED_INVESTORS subset (existing behavior kept)
        updated_investors_data = {}
        for investor_id, investor_data in investors_data.items():
            verification_status = investor_data.get('balance_verification', '').strip().lower()
            if verification_status == 'verified':
                updated_investors_data[investor_id] = investor_data

        if updated_investors_data:
            with open(ALL_UPDATED_INVESTORS, 'w', encoding='utf-8') as f:
                json.dump(updated_investors_data, f, indent=2)
            print(f"💾 Updated {len(updated_investors_data)} verified investors to {ALL_UPDATED_INVESTORS}")

        # ------------------------------------------------------------
        # PROPAGATE to every other investor file if the ID is found
        # ------------------------------------------------------------
        if propagated_updates:
            other_targets = [
                ("ALL_INVESTORS", ALL_INVESTORS),
                ("ALL_UPDATED_INVESTORS", ALL_UPDATED_INVESTORS),
                ("INVHARV_FETCHED_INVESTORS", INVHARV_FETCHED_INVESTORS),
                ("HARVHUB_FETCHED_INVESTORS", HARVHUB_FETCHED_INVESTORS),
                ("INVHARV_UPDATED_INVESTORS", INVHARV_UPDATED_INVESTORS),
                ("HARVHUB_UPDATED_INVESTORS", HARVHUB_UPDATED_INVESTORS),
                ("ALL_INVESTORS_BACKUP", ALL_INVESTORS_BACKUP),
            ]

            print(f"\n📤 Propagating verification updates to other investor files...")

            for target_name, target_path in other_targets:
                if not os.path.exists(target_path):
                    print(f"   ℹ️  {target_name}: not found, skipping")
                    continue
                try:
                    with open(target_path, 'r', encoding='utf-8') as f:
                        target_data = json.load(f)
                    if not isinstance(target_data, dict):
                        print(f"   ⚠️  {target_name}: invalid format, skipping")
                        continue
                except Exception as e:
                    print(f"   ⚠️  {target_name}: could not load ({e}), skipping")
                    continue

                changed = 0
                for inv_id, fields in propagated_updates.items():
                    if inv_id not in target_data:
                        continue
                    if not isinstance(target_data[inv_id], dict):
                        continue
                    for field, value in fields.items():
                        if target_data[inv_id].get(field) != value:
                            target_data[inv_id][field] = value
                            changed += 1

                if changed > 0:
                    try:
                        with open(target_path, 'w', encoding='utf-8') as f:
                            json.dump(target_data, f, indent=2, ensure_ascii=False)
                        print(f"   ✅ {target_name}: {changed} field(s) updated")
                    except Exception as e:
                        print(f"   ❌ {target_name}: save failed ({e})")
                else:
                    print(f"   ℹ️  {target_name}: no matching IDs / no changes")
        else:
            print(f"\nℹ️ No propagated updates (nothing changed)")

        print(f"\n📊 Merge Summary:")
        print(f"   ✅ Verified: {stats['verified']}")
        print(f"   🛑 Errors: {stats['errors']}")
        return stats
    else:
        print(f"ℹ️ No verification updates to merge")
        return stats
    
def process_all_fetched_investors_(inv_id):
    """
    WORKER FUNCTION: Handles the entire pipeline for ONE investor.
    Connects directly to MT5 using the investor's credentials from ALL_FETCHED_INVESTORS.
    
    Args:
        inv_id: String investor ID (e.g., "1", "5", etc.)
    """
    # =====================================================================
    # SECTION: WORK IN TIME RANGE CHECK
    # =====================================================================
    
    # Initialize mode_label with default value at the start
    mode_label = "unknown"
    account_mode = "unknown"
    
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
        "is_real_account": False,
        "grid_strategy_enabled": False,
        "ohlc_strategy_enabled": False,
        "within_time_range": False,
        "outside_time_range": False
    }
    
    # =====================================================================
    # SECTION: LOAD INVESTOR DATA FIRST (Always needed)
    # =====================================================================
    investor_data = None
    broker_cfg = None
    inv_str_id = str(inv_id)
    
    try:
        if not os.path.exists(ALL_FETCHED_INVESTORS):
            print(f"[ERROR] ALL_FETCHED_INVESTORS file not found: {ALL_FETCHED_INVESTORS}")
            account_stats["skip_reason"] = "Fetched investors file not found"
            return account_stats
        
        with open(ALL_FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
            all_investors = json.load(f)
        
        investor_data = all_investors.get(inv_str_id)
        
        if not investor_data:
            print(f"[ERROR] Investor ID {inv_id} not found in ALL_FETCHED_INVESTORS")
            account_stats["skip_reason"] = "Investor not found in fetched data"
            return account_stats
        
        print(f"✅ Found investor {inv_id} in ALL_FETCHED_INVESTORS")
        create_investor_mt5_files(inv_id=inv_id)
        
        # Build broker config from investor data
        broker_cfg = {
            'LOGIN_ID': investor_data.get('login'),
            'broker_password': investor_data.get('broker_password'),
            'SERVER': investor_data.get('server'),
            'Terminal_path': investor_data.get('Terminal_path', '')
        }
        
        print(f"   Login: {broker_cfg['LOGIN_ID']}")
        print(f"   Server: {broker_cfg['SERVER']}")
        print(f"   Terminal Path: {broker_cfg['Terminal_path']}")
        
    except Exception as e:
        print(f"[ERROR] Failed to load investor data: {str(e)}")
        account_stats["skip_reason"] = f"Data loading error: {str(e)}"
        return account_stats
    
    # =====================================================================
    # SECTION: MT5 INITIALIZATION (ALWAYS do this first, before any MT5 calls)
    # =====================================================================
    print(f"\n{'='*10} 🔗 MT5 INITIALIZATION FOR {inv_id} {'='*10}")
    
    if not broker_cfg:
        print(f"[ERROR] No broker configuration found for Investor: {inv_id}")
        return account_stats
    
    # CRITICAL FIX: Shutdown any existing MT5 connection first
    try:
        mt5.shutdown()
    except:
        pass
    
    configured_path = broker_cfg.get("Terminal_path", "")
    
    # SINGLE INITIALIZATION ATTEMPT - NO LOGIN NEEDED
    init_successful = False
    
    if configured_path and str(configured_path).strip():
        terminal_path = os.path.abspath(configured_path)
        if os.path.exists(terminal_path):
            print(f"🔗 Initializing {inv_id} MT5")
            if mt5.initialize(path=terminal_path, timeout=10000, portable=True):
                init_successful = True
                print(f"✅ MT5 initialized successfully with terminal path")
            else:
                print(f"Unable to Initialize {inv_id} MT5")
                print(f"🛑 Issue:")
                print(f"{mt5.last_error()}")
                print(f"Terminal Path:")
                print(f"{terminal_path}")
        else:
            print(f"Unable to Process {inv_id} MT5")
            print(f"🛑 Issue:")
            print(f" Terminal path does not exist")
            print(f"Invalid Terminal Path:")
            print(f"{terminal_path}")
    
    # Fallback to default initialization without path
    if not init_successful:
        print(f" Not initialized, Try Login into {inv_id} {terminal_path} manually")
    
    if not init_successful:
        print(f"Unable to Process {inv_id} MT5")
        print(f"🛑 Issue:")
        print(f" Failed to initialize MT5 connection")
        account_stats["skip_reason"] = "MT5 Initialization Failure"
        return account_stats
    
    # =====================================================================
    # GET ACCOUNT INFO (Verify connection works)
    # =====================================================================
    print(f"\n{'='*10} 📊 GETTING ACCOUNT INFO FOR {inv_id} {'='*10}")
    
    # Verify account info directly - already connected via terminal path
    acc = mt5.account_info()
    
    if acc is None:
        print(f"[FAIL] Could not retrieve account information after initialization")
        print(f"       Error: {mt5.last_error()}")
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
        mode_label = "real"
    elif acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO:
        is_real = False
        type_label = "DEMO"
        mode_label = "demo"
    elif acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_CONTEST:
        is_real = False
        type_label = "CONTEST"
        mode_label = "demo"
    elif acc.margin_so_mode == mt5.ACCOUNT_STOPOUT_MODE_MONEY:
        is_real = False
        type_label = "DEMO (MONETARY SO FOOTPRINT)"
        mode_label = "demo"
    else:
        server_upper = acc.server.upper() if acc.server else ""
        if any(indicator in server_upper for indicator in ["DEMO", "STAGE", "TEST", "PRELIVE", "SIMULATION"]):
            is_real = False
            type_label = "DEMO (SERVER STR MATCH)"
            mode_label = "demo"
        else:
            is_real = True
            type_label = "REAL (FALLBACK)"
            mode_label = "real"
    
    if is_real:
        mode_label = "real"
    
    account_stats["account_type"] = type_label
    account_stats["account_mode"] = mode_label
    account_stats["is_real_account"] = is_real
    
    print(f"[{inv_id}] Account ID: {acc.login}")
    print(f"[{inv_id}] Server: '{acc.server}' | Mode Detected: '{mode_label.upper()}' ({type_label})")
    print(f"[{inv_id}] Account Balance: {acc.balance} {acc.currency}")
    print(f"[{inv_id}] Account Leverage: {acc.leverage}")
    
    # Extract structural demo permission policies from investor data
    allow_demo_processing = True
    try:
        demo_flag = investor_data.get("demo_account", "1")
        if str(demo_flag).strip().lower() in ["0", "false"]:
            allow_demo_processing = False
            print(f"[{inv_id}] Registry Flag Loaded: DEMO_ACCOUNT processing is DISABLED for this user.")
        else:
            print(f"[{inv_id}] Registry Flag Loaded: DEMO_ACCOUNT processing is ALLOWED for this user.")
            
        account_mode = investor_data.get("account_mode", "demo")
        print(f"[{inv_id}] Account Mode from data: {account_mode}")
        
    except Exception as json_err:
        print(f"[ERROR] Failed to parse investor configuration: {str(json_err)}")
    
    # Safety policy gate check
    if not is_real and not allow_demo_processing:
        print(f"[ABORT] Account {inv_id} is a DEMO environment, but JSON permissions forbid execution. Skipping.")
        account_stats["execution_skipped"] = True
        account_stats["skip_reason"] = "Execution Blocked: DEMO_ACCOUNT rule is configured to 0"
        return account_stats
  
    # =====================================================================
    # SUCCESS - MT5 CONNECTED, NOW CALL FUNCTIONS
    # =====================================================================
    print(f"\n{'='*10} ✅ MT5 CONNECTION SUCCESSFUL FOR {inv_id} {'='*10}")
    print(f"   Account ID: {acc.login}")
    print(f"   Balance: {acc.balance} {acc.currency}")
    print(f"   Leverage: {acc.leverage}")
    
    create_investor_mt5_files(inv_id=inv_id)
    
    # =====================================================================
    # CLEANUP
    # =====================================================================
    mt5.shutdown()
    print(f"✅ MT5 shutdown complete for investor {inv_id}")
    
    account_stats["success"] = True
    print(f"[SUCCESS] Finished pipeline for Investor: {inv_id} ({mode_label})")
    return account_stats
  
def process_all_fetched_investors(inv_id):
    """
    WORKER FUNCTION: Handles the entire pipeline for ONE investor.
    Connects directly to MT5 using the investor's credentials from ALL_FETCHED_INVESTORS.

    ORDER OF OPERATIONS (critical):
      1. Load investor data (needed to know broker/id/email)
      2. RUN create_investor_mt5_files FIRST → corrects Terminal_path + mt5_folder_name
         and creates the folder if missing.
      3. RELOAD investor data from disk so we pick up the corrected Terminal_path.
      4. MT5 initialize using the corrected path.
      5. get_investors_balance / verify_investors_balance.

    Args:
        inv_id: String investor ID (e.g., "1", "5", etc.)
    """
    # =====================================================================
    # SECTION: WORK IN TIME RANGE CHECK
    # =====================================================================

    # Initialize mode_label with default value at the start
    mode_label = "unknown"
    account_mode = "unknown"

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
        "is_real_account": False,
        "grid_strategy_enabled": False,
        "ohlc_strategy_enabled": False,
        "within_time_range": False,
        "outside_time_range": False
    }

    # =====================================================================
    # SECTION: LOAD INVESTOR DATA FIRST (Always needed)
    # =====================================================================
    investor_data = None
    broker_cfg = None
    inv_str_id = str(inv_id)

    try:
        if not os.path.exists(ALL_FETCHED_INVESTORS):
            print(f"[ERROR] ALL_FETCHED_INVESTORS file not found: {ALL_FETCHED_INVESTORS}")
            account_stats["skip_reason"] = "Fetched investors file not found"
            return account_stats

        with open(ALL_FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
            all_investors = json.load(f)

        investor_data = all_investors.get(inv_str_id)

        if not investor_data:
            print(f"[ERROR] Investor ID {inv_id} not found in ALL_FETCHED_INVESTORS")
            account_stats["skip_reason"] = "Investor not found in fetched data"
            return account_stats

        print(f"✅ Found investor {inv_id} in ALL_FETCHED_INVESTORS")

    except Exception as e:
        print(f"[ERROR] Failed to load investor data: {str(e)}")
        account_stats["skip_reason"] = f"Data loading error: {str(e)}"
        return account_stats

    # =====================================================================
    # SECTION: CREATE/MAINTAIN MT5 FILES  ← MOVED UP, RUNS BEFORE MT5 INIT
    # ---------------------------------------------------------------------
    # This MUST run first so that:
    #   - A missing folder is created.
    #   - A wrong/empty/"NULL" Terminal_path is corrected and persisted.
    #   - mt5_folder_name is always kept in sync.
    #   - The pending → just-joined status transition is applied.
    # After this call, we RELOAD the investor record from disk to pick up
    # the corrected Terminal_path before passing it to mt5.initialize().
    # =====================================================================
    print(f"\n{'='*10} 📦 MT5 FOLDER MAINTENANCE FOR {inv_id} {'='*10}")

    try:
        create_result = create_investor_mt5_files(inv_id=inv_id)
        if create_result:
            print(f"   create_investor_mt5_files → success={create_result.get('success')} "
                  f"created={create_result.get('created')} deleted={create_result.get('deleted')}")
            if create_result.get('message'):
                print(f"   message: {create_result['message']}")
    except Exception as e:
        print(f"[WARN] create_investor_mt5_files raised for {inv_id}: {e}")
        # Non-fatal: continue, but the Terminal_path may still be wrong.

    # ---------------------------------------------------------------------
    # RELOAD investor data from disk to pick up any corrected Terminal_path
    # written by create_investor_mt5_files (its updated_data is merged by
    # the merge step, but on a single-process run we also re-read here as a
    # belt-and-braces measure in case the merge already ran).
    # ---------------------------------------------------------------------
    try:
        with open(ALL_FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
            all_investors = json.load(f)
        refreshed = all_investors.get(inv_str_id)
        if refreshed:
            investor_data = refreshed
            print(f"   🔄 Reloaded investor {inv_id} after folder maintenance")
    except Exception as e:
        print(f"[WARN] Could not reload investor data after folder maintenance: {e}")
        # Keep the previously loaded investor_data

    # Build broker config from (possibly refreshed) investor data
    broker_cfg = {
        'LOGIN_ID': investor_data.get('login'),
        'broker_password': investor_data.get('broker_password'),
        'SERVER': investor_data.get('server'),
        'Terminal_path': investor_data.get('Terminal_path', '')
    }

    print(f"   Login: {broker_cfg['LOGIN_ID']}")
    print(f"   Server: {broker_cfg['SERVER']}")
    print(f"   Terminal Path: {broker_cfg['Terminal_path']}")

    # =====================================================================
    # SECTION: MT5 INITIALIZATION (uses the corrected Terminal_path)
    # =====================================================================
    print(f"\n{'='*10} 🔗 MT5 INITIALIZATION FOR {inv_id} {'='*10}")

    if not broker_cfg:
        print(f"[ERROR] No broker configuration found for Investor: {inv_id}")
        return account_stats

    # CRITICAL: Shutdown any existing MT5 connection first
    try:
        mt5.shutdown()
    except:
        pass

    configured_path = broker_cfg.get("Terminal_path", "")

    # Normalize the "NULL" string to empty for safety
    if configured_path is None or str(configured_path).strip().upper() in ("", "NULL", "NONE"):
        configured_path = ""

    # FIX: Initialize terminal_path with default value BEFORE the if block
    terminal_path = configured_path if configured_path else "No path configured"

    # SINGLE INITIALIZATION ATTEMPT - NO LOGIN NEEDED
    init_successful = False

    if configured_path and str(configured_path).strip():
        terminal_path = os.path.abspath(configured_path)
        if os.path.exists(terminal_path):
            print(f"🔗 Initializing {inv_id} MT5")
            if mt5.initialize(path=terminal_path, timeout=10000, portable=True):
                init_successful = True
                print(f"✅ MT5 initialized successfully with terminal path")
            else:
                print(f"Unable to Initialize {inv_id} MT5")
                print(f"🛑 Issue:")
                print(f"{mt5.last_error()}")
                print(f"Terminal Path:")
                print(f"{terminal_path}")
        else:
            print(f"Unable to Process {inv_id} MT5")
            print(f"🛑 Issue:")
            print(f" Terminal path does not exist")
            print(f"Invalid Terminal Path:")
            print(f"{terminal_path}")

    # Fallback to default initialization without path
    if not init_successful:
        print(f" Not initialized, Try Login into {inv_id} {terminal_path} manually")

    if not init_successful:
        print(f"Unable to Process {inv_id} MT5")
        print(f"🛑 Issue:")
        print(f" Failed to initialize MT5 connection")
        account_stats["skip_reason"] = "MT5 Initialization Failure"
        return account_stats

    # =====================================================================
    # GET ACCOUNT INFO (Verify connection works)
    # =====================================================================
    print(f"\n{'='*10} 📊 GETTING ACCOUNT INFO FOR {inv_id} {'='*10}")

    # Verify account info directly - already connected via terminal path
    acc = mt5.account_info()

    if acc is None:
        print(f"[FAIL] Could not retrieve account information after initialization")
        print(f"       Error: {mt5.last_error()}")
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
        mode_label = "real"
    elif acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO:
        is_real = False
        type_label = "DEMO"
        mode_label = "demo"
    elif acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_CONTEST:
        is_real = False
        type_label = "CONTEST"
        mode_label = "demo"
    elif acc.margin_so_mode == mt5.ACCOUNT_STOPOUT_MODE_MONEY:
        is_real = False
        type_label = "DEMO (MONETARY SO FOOTPRINT)"
        mode_label = "demo"
    else:
        server_upper = acc.server.upper() if acc.server else ""
        if any(indicator in server_upper for indicator in ["DEMO", "STAGE", "TEST", "PRELIVE", "SIMULATION"]):
            is_real = False
            type_label = "DEMO (SERVER STR MATCH)"
            mode_label = "demo"
        else:
            is_real = True
            type_label = "REAL (FALLBACK)"
            mode_label = "real"

    if is_real:
        mode_label = "real"

    account_stats["account_type"] = type_label
    account_stats["account_mode"] = mode_label
    account_stats["is_real_account"] = is_real

    print(f"[{inv_id}] Account ID: {acc.login}")
    print(f"[{inv_id}] Server: '{acc.server}' | Mode Detected: '{mode_label.upper()}' ({type_label})")
    print(f"[{inv_id}] Account Balance: {acc.balance} {acc.currency}")
    print(f"[{inv_id}] Account Leverage: {acc.leverage}")

    # Extract structural demo permission policies from investor data
    allow_demo_processing = True
    try:
        demo_flag = investor_data.get("demo_account", "1")
        if str(demo_flag).strip().lower() in ["0", "false"]:
            allow_demo_processing = False
            print(f"[{inv_id}] Registry Flag Loaded: DEMO_ACCOUNT processing is DISABLED for this user.")
        else:
            print(f"[{inv_id}] Registry Flag Loaded: DEMO_ACCOUNT processing is ALLOWED for this user.")

        account_mode = investor_data.get("account_mode", "demo")
        print(f"[{inv_id}] Account Mode from data: {account_mode}")

    except Exception as json_err:
        print(f"[ERROR] Failed to parse investor configuration: {str(json_err)}")

    # Safety policy gate check
    if not is_real and not allow_demo_processing:
        print(f"[ABORT] Account {inv_id} is a DEMO environment, but JSON permissions forbid execution. Skipping.")
        account_stats["execution_skipped"] = True
        account_stats["skip_reason"] = "Execution Blocked: DEMO_ACCOUNT rule is configured to 0"
        return account_stats

    # =====================================================================
    # SUCCESS - MT5 CONNECTED, NOW CALL REMAINING FUNCTIONS
    # (create_investor_mt5_files already ran at the top)
    # =====================================================================
    print(f"\n{'='*10} ✅ MT5 CONNECTION SUCCESSFUL FOR {inv_id} {'='*10}")
    print(f"   Account ID: {acc.login}")
    print(f"   Balance: {acc.balance} {acc.currency}")
    print(f"   Leverage: {acc.leverage}")

    get_investors_balance(inv_id=inv_id)
    verify_investors_balance(inv_id=inv_id)

    # =====================================================================
    # CLEANUP
    # =====================================================================
    mt5.shutdown()
    print(f"✅ MT5 shutdown complete for investor {inv_id}")

    account_stats["success"] = True
    print(f"[SUCCESS] Finished pipeline for Investor: {inv_id} ({mode_label})")
    return account_stats

def main_once():
    """
    ORCHESTRATOR (Loop Execution): Processes ALL investors from ALL_FETCHED_INVESTORS
    in a continuous loop without any capacity limitations or restrictions.
    """
    # Parse command line arguments for control flags
    run_as_loop = False
    loop_interval = 1  # Default 1 second between loops (matching original)
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
                print(f"Invalid interval value: {arg.split('=')[1]}. Using default 1 second.")
        elif arg.startswith('--max-loops='):
            try:
                max_loops = int(arg.split('=')[1])
            except ValueError:
                print(f"Invalid max-loops value: {arg.split('=')[1]}. Running infinite loops.")
    
    print("\n" + "="*60)
    print("="*60)
    print(f"  Loop Mode: {'ENABLED' if run_as_loop else 'DISABLED'}")
    if run_as_loop:
        print(f"  Interval: {loop_interval}s")
        if max_loops:
            print(f"  Max Loops: {max_loops}")
        else:
            print("  Max Loops: Infinite")
    print("="*60 + "\n")
    
    loop_count = 0
    
    print(f"🚀 Initializing Trading Engine Pool...")
    print(f"🛑  NOTE: All capacity limits have been REMOVED - processing ALL investors regardless of system load")

    while True:
        loop_count += 1
        
        if run_as_loop:
            print("\n" + "="*60)
            print(f"LOOP #{loop_count} STARTED")
            print("="*60)
        
        time_check_result = work_only_in_specific_timerange()
        within_time_range = time_check_result.get("should_work", False)
        
        if within_time_range:
            print(f"✅ System is WITHIN allowed work time range - Fetching data")
            fetch_investors()
        else:
            print("No executions")
        
        try:
            # ============ LOAD INVESTOR IDs FROM ALL_FETCHED_INVESTORS ============
            investor_ids = []
            
            if not os.path.exists(ALL_FETCHED_INVESTORS):
                print(f"[ERROR] ALL_FETCHED_INVESTORS file not found: {ALL_FETCHED_INVESTORS}")
                if not run_as_loop:
                    print("Single execution completed with error. Exiting...")
                    break
                time.sleep(10)
                continue
            
            try:
                with open(ALL_FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
                    investors_data = json.load(f)
                
                # Extract investor IDs from the fetched investors file
                investor_ids = list(investors_data.keys())
                print(f"✅ Loaded {len(investor_ids)} investors from ALL_FETCHED_INVESTORS")
                
            except Exception as e:
                print(f"[ERROR] Failed to load ALL_FETCHED_INVESTORS: {str(e)}")
                if not run_as_loop:
                    break
                time.sleep(10)
                continue
            
            # --- MAIN LOOP EMPTY DATA GUARD ---
            if not investor_ids:
                print(" ⏳ No investors found in ALL_FETCHED_INVESTORS. Sleeping for 10 seconds before next scan...")
                time.sleep(10)
                if not run_as_loop:
                    print("Single execution completed. Exiting...")
                    break
                continue

            # Display system info for awareness only (no limiting)
            cpu_cores = os.cpu_count() or 1
            available_ram_mb = psutil.virtual_memory().available / (1024 * 1024)
            
            print(f"\n🖥️  Hardware Profile -> Cores: {cpu_cores} | Free RAM: {available_ram_mb:.1f}MB")
            print(f"📊 Processing ALL {len(investor_ids)} investors from ALL_FETCHED_INVESTORS without capacity restrictions...")
            print(f"📋 Investor IDs: {investor_ids}")

            # Process ALL investor IDs - NO CAPACITY LIMITS
            active_batch = investor_ids

            print(f"\n--- Cycle Start: Spinning up context pool for {len(active_batch)} workers ---")
            
            # Pool with ALL investors - no capacity checks
            with mp.Pool(processes=len(active_batch)) as pool:
                jobs = []
                for investor_id in active_batch:
                    # Pass the investor ID string directly
                    job = pool.apply_async(process_all_fetched_investors, args=(investor_id,))
                    jobs.append(job)
                
                # Force synchronization bar before closing the pool step block
                results = [job.get() for job in jobs]
                
            # Print summary of results
            print(f"\n--- Cycle Complete. Processed {len(active_batch)} investors. ---")
            successful = sum(1 for r in results if r.get("success", False))
            skipped = sum(1 for r in results if r.get("execution_skipped", False))
            failed = len(results) - successful - skipped
            print(f"📊 Results: ✅ {successful} successful | ⏰ {skipped} skipped | ❌ {failed} failed")
            
            # Print any errors
            for r in results:
                if r.get("error"):
                    print(f"  ❌ Investor {r.get('inv_id')}: {r.get('error')}")
                if r.get("skip_reason"):
                    print(f"  ⏭️  Investor {r.get('inv_id')}: {r.get('skip_reason')}")
            
        except Exception as e:
            print(f"Critical Error in Orchestrator Loop: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(5)
        merge_create_results()
        merge_balance_results()
        merge_verify_results()
        
        if within_time_range:
            sync_and_distribute_investors() 
            restore_empty_investor_files()
            print(f"✅ System is WITHIN allowed work time range - Updating database")
            close_db_browser()
            update_investors()
        
        # Merge all results (these functions now handle the merging safely)
        
          

        # Check loop conditions
        if not run_as_loop:
            # Single execution - exit
            print("Single execution completed. Exiting...")
            break
        
        # Check max loops
        if max_loops and loop_count >= max_loops:
            print(f"Maximum loops ({max_loops}) reached. Exiting...")
            break
        
        # Wait before next iteration
        if run_as_loop and loop_interval > 0:
            print(f"Waiting {loop_interval} seconds before next loop...")
            time.sleep(loop_interval)

def main_loop():
    """
    ORCHESTRATOR (Loop Execution): Processes ALL investors from ALL_FETCHED_INVESTORS
    in a continuous loop without any capacity limitations or restrictions.
    """
    # Parse command line arguments for control flags
    run_as_loop = True
    loop_interval = 1  # Default 1 second between loops (matching original)
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
                print(f"Invalid interval value: {arg.split('=')[1]}. Using default 1 second.")
        elif arg.startswith('--max-loops='):
            try:
                max_loops = int(arg.split('=')[1])
            except ValueError:
                print(f"Invalid max-loops value: {arg.split('=')[1]}. Running infinite loops.")
    
    print("\n" + "="*60)
    print("="*60)
    print(f"  Loop Mode: {'ENABLED' if run_as_loop else 'DISABLED'}")
    if run_as_loop:
        print(f"  Interval: {loop_interval}s")
        if max_loops:
            print(f"  Max Loops: {max_loops}")
        else:
            print("  Max Loops: Infinite")
    print("="*60 + "\n")
    
    loop_count = 0
    
    print(f"🚀 Initializing Trading Engine Pool...")
    print(f"🛑  NOTE: All capacity limits have been REMOVED - processing ALL investors regardless of system load")

    while True:
        loop_count += 1
        
        if run_as_loop:
            print("\n" + "="*60)
            print(f"LOOP #{loop_count} STARTED")
            print("="*60)
        
        time_check_result = work_only_in_specific_timerange()
        within_time_range = time_check_result.get("should_work", False)
        
        if within_time_range:
            print(f"✅ System is WITHIN allowed work time range - Fetching data")
            fetch_investors()
        else:
            print("No executions")
        
        try:
            # ============ LOAD INVESTOR IDs FROM ALL_FETCHED_INVESTORS ============
            investor_ids = []
            
            if not os.path.exists(ALL_FETCHED_INVESTORS):
                print(f"[ERROR] ALL_FETCHED_INVESTORS file not found: {ALL_FETCHED_INVESTORS}")
                if not run_as_loop:
                    print("Single execution completed with error. Exiting...")
                    break
                time.sleep(10)
                continue
            
            try:
                with open(ALL_FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
                    investors_data = json.load(f)
                
                # Extract investor IDs from the fetched investors file
                investor_ids = list(investors_data.keys())
                print(f"✅ Loaded {len(investor_ids)} investors from ALL_FETCHED_INVESTORS")
                
            except Exception as e:
                print(f"[ERROR] Failed to load ALL_FETCHED_INVESTORS: {str(e)}")
                if not run_as_loop:
                    break
                time.sleep(10)
                continue
            
            # --- MAIN LOOP EMPTY DATA GUARD ---
            if not investor_ids:
                print(" ⏳ No investors found in ALL_FETCHED_INVESTORS. Sleeping for 10 seconds before next scan...")
                time.sleep(10)
                if not run_as_loop:
                    print("Single execution completed. Exiting...")
                    break
                continue

            # Display system info for awareness only (no limiting)
            cpu_cores = os.cpu_count() or 1
            available_ram_mb = psutil.virtual_memory().available / (1024 * 1024)
            
            print(f"\n🖥️  Hardware Profile -> Cores: {cpu_cores} | Free RAM: {available_ram_mb:.1f}MB")
            print(f"📊 Processing ALL {len(investor_ids)} investors from ALL_FETCHED_INVESTORS without capacity restrictions...")
            print(f"📋 Investor IDs: {investor_ids}")

            # Process ALL investor IDs - NO CAPACITY LIMITS
            active_batch = investor_ids

            print(f"\n--- Cycle Start: Spinning up context pool for {len(active_batch)} workers ---")
            
            # Pool with ALL investors - no capacity checks
            with mp.Pool(processes=len(active_batch)) as pool:
                jobs = []
                for investor_id in active_batch:
                    # Pass the investor ID string directly
                    job = pool.apply_async(process_all_fetched_investors, args=(investor_id,))
                    jobs.append(job)
                
                # Force synchronization bar before closing the pool step block
                results = [job.get() for job in jobs]
                
            # Print summary of results
            print(f"\n--- Cycle Complete. Processed {len(active_batch)} investors. ---")
            successful = sum(1 for r in results if r.get("success", False))
            skipped = sum(1 for r in results if r.get("execution_skipped", False))
            failed = len(results) - successful - skipped
            print(f"📊 Results: ✅ {successful} successful | ⏰ {skipped} skipped | ❌ {failed} failed")
            
            # Print any errors
            for r in results:
                if r.get("error"):
                    print(f"  ❌ Investor {r.get('inv_id')}: {r.get('error')}")
                if r.get("skip_reason"):
                    print(f"  ⏭️  Investor {r.get('inv_id')}: {r.get('skip_reason')}")
            
        except Exception as e:
            print(f"Critical Error in Orchestrator Loop: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(5)
        merge_create_results()
        merge_balance_results()
        merge_verify_results()
        
        if within_time_range:
            sync_and_distribute_investors() 
            restore_empty_investor_files()
            print(f"✅ System is WITHIN allowed work time range - Updating database")
            close_db_browser()
            update_investors()
        
        # Merge all results (these functions now handle the merging safely)
        
          

        # Check loop conditions
        if not run_as_loop:
            # Single execution - exit
            print("Single execution completed. Exiting...")
            break
        
        # Check max loops
        if max_loops and loop_count >= max_loops:
            print(f"Maximum loops ({max_loops}) reached. Exiting...")
            break
        
        # Wait before next iteration
        if run_as_loop and loop_interval > 0:
            print(f"Waiting {loop_interval} seconds before next loop...")
            time.sleep(loop_interval)


if __name__ == "__main__":
    update_fresh_data_from_fetched_to_all_files()


    
