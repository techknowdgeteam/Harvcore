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


DEFAULT_MT5_PATH = r"C:\xampp\htdocs\harvcore\mt5\MetaTrader 5"
MT5_DESTINATION_PATH = r"C:\xampp\htdocs\harvcore\mt5"
INV_PATH = r"C:\xampp\htdocs\harvcore\harvox\invharv\usersdata\investors"
DEFAULT_PATH = r"C:\xampp\htdocs\harvcore\harvox"
DEFAULT_ACCOUNTMANAGEMENT = r"C:\xampp\htdocs\harvcore\harvox\invharv\harvcore_accountmanagement.json"
SUSPENDED_ACCOUNTS = r"C:\xampp\htdocs\harvcore\harvox\invharv\suspended_accounts.json"
FETCHED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\invharv\fetched_investors.json"
UPDATED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\invharv\updated_investors.json"

INVHARV_FETCHED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\invharv\fetched_investors.json"
INVHARV_UPDATED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\invharv\updated_investors.json"
HARVHUB_FETCHED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\harvhub\fetched_harvhub_investors.json"
HARVHUB_UPDATED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\harvhub\updated_harvhub_investors.json"
ALL_FETCHED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\fetched_investors.json"
ALL_UPDATED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\updated_investors.json"


def work_only_in_specific_timerange():
    """
    Function: Checks if current time falls within any of the allowed work time ranges
    from default_accountmanagement.json (global setting).
    Function will ONLY work during specified time windows.
    Does NOT need MT5 connection - just checks time configuration.
    
    Looks for 'working_hours' key at the root level of the JSON.
    
    If 'from' or 'to' values parse to 0 (e.g., "0", "0.00", "0:00 am", "00:00"), 
    it overrides all restrictions and assumes work is always allowed.
    
    Returns:
        dict: Statistics about the time range check including whether function should work
    """
    global restricted_timerange_alert
    
    from datetime import datetime
    from pathlib import Path
    import json
    
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
        "json_structure_found": None
    }
    
    # Load default configuration
    default_config = None
    default_config_path = Path(DEFAULT_ACCOUNTMANAGEMENT)
    
    if not default_config_path.exists():
        print(f"    Default config not found: {DEFAULT_ACCOUNTMANAGEMENT}")
        stats["errors"].append(f"Default config not found: {DEFAULT_ACCOUNTMANAGEMENT}")
        stats["processing_success"] = True  
        stats["should_work"] = True  
        stats["json_structure_found"] = "FILE_NOT_FOUND"
        return stats
    
    try:
        with open(default_config_path, 'r', encoding='utf-8') as f:
            default_config = json.load(f)
        print(f"   ✅ Config file loaded successfully")
    except Exception as e:
        print(f"    Error loading default config: {e}")
        stats["errors"].append(f"Error loading default config: {e}")
        stats["processing_success"] = True
        stats["should_work"] = True  
        stats["json_structure_found"] = "ERROR_LOADING"
        return stats
    
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
    print(f"   JSON structure: {stats['json_structure_found']}")
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
    
    print(f"{'='*10} 🏁 COMPLETE {'='*10}\n")
    
    return stats

def fetch_tables_streaming(batch_size=5000):
    """Stream results directly to file without holding all in memory - Hybrid mode: IP first, then VS Code ID fallback"""
    
    def get_local_ip():
        """Get the local IP address of the computer"""
        try:
            # Create a socket connection to determine the local IP
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
        """Extract VS Code machine ID from storage.json"""
        try:
            appdata = os.environ.get("APPDATA", "")
            if not appdata:
                return None
            
            global_storage = os.path.join(appdata, "Code", "User", "globalStorage")
            storage_json_path = os.path.join(global_storage, "storage.json")
            
            if os.path.exists(storage_json_path):
                with open(storage_json_path, 'r', encoding='utf-8') as f:
                    storage_data = json.load(f)
                    
                    # Look for machine ID in various possible keys
                    possible_keys = [
                        'telemetry.machineId',
                        'machineId',
                        'machine.id',
                        'vscode.machineId'
                    ]
                    
                    for key in possible_keys:
                        if key in storage_data:
                            machine_id = storage_data[key]
                            if machine_id:
                                print(f"  🖥️ VS Code Machine ID detected: {machine_id[:32]}...")
                                return machine_id
            
            return None
        except Exception as e:
            print(f"    Error getting VS Code ID: {e}")
            return None
    
    def parse_server_config(config_value):
        """Parse system_server_config from string to dictionary"""
        if config_value is None:
            return {}
        
        # If it's already a dict, use it
        if isinstance(config_value, dict):
            return config_value
        
        # If it's a string, try to parse it
        if isinstance(config_value, str):
            try:
                # First attempt: direct JSON parse
                return json.loads(config_value)
            except json.JSONDecodeError:
                pass
            
            # Second attempt: Use repair_json_field
            try:
                repaired = repair_json_field(config_value)
                if isinstance(repaired, dict):
                    return repaired
            except:
                pass
            
            # Third attempt: Try to evaluate as Python literal
            try:
                import ast
                parsed = ast.literal_eval(config_value)
                if isinstance(parsed, dict):
                    return parsed
            except:
                pass
            
            # If all fails, return empty dict
            print(f"    ⚠️ Could not parse system_server_config")
            return {}
        
        return {}
    
    def extract_user_ids_from_config(config_dict, target_id, id_type="identifier"):
        """Extract user IDs for a specific computer ID (IP or VS Code ID)"""
        if not config_dict or target_id not in config_dict:
            return []
        
        computer_data = config_dict[target_id]
        
        # If it's not a list, return empty
        if not isinstance(computer_data, list):
            print(f"    ⚠️ Data for {id_type} {target_id} is not a list: {type(computer_data)}")
            return []
        
        user_ids = []
        for item in computer_data:
            # Only add if it's a valid ID (int or string that can be converted)
            if isinstance(item, (int, float)):
                # Convert to string for consistent handling
                user_ids.append(str(int(item)))
            elif isinstance(item, str):
                # Try to convert to int if it's numeric
                try:
                    # Check if it's a numeric string
                    if item.strip().isdigit():
                        user_ids.append(str(int(item)))
                    else:
                        # Skip non-numeric strings (like URLs or other text)
                        print(f"    ℹ️ Skipping non-numeric entry: '{item}' for {id_type} {target_id}")
                        continue
                except:
                    print(f"    ℹ️ Skipping invalid entry: '{item}' for {id_type} {target_id}")
                    continue
            elif isinstance(item, dict):
                # Skip dictionary objects (like {"URL": "..."})
                print(f"    ℹ️ Skipping nested object for {id_type} {target_id}: {item}")
                continue
            else:
                # Skip any other types
                print(f"    ℹ️ Skipping unsupported type {type(item)} for {id_type} {target_id}: {item}")
                continue
        
        return user_ids
    
    def denormalize_path_value(value, field_name):
        """Convert underscore-normalized paths back to original path format with backslashes"""
        if value is None:
            return None
        
        # Check if field name contains 'path' (case insensitive)
        if 'path' not in field_name.lower():
            return value
        
        # Only process string values
        if not isinstance(value, str):
            return value
        
        # Convert underscores back to backslashes (ONLY underscores, preserve everything else)
        denormalized = value.replace('_', '\\')
        
        # Handle drive letters: C:\ should remain C:\ (not C:\\)
        import re
        # Fix drive letters (e.g., "C:\" pattern)
        denormalized = re.sub(r'([A-Za-z]):\\', r'\1:\\', denormalized)
        denormalized = re.sub(r'([A-Za-z]):\\', r'\1:\\', denormalized)
        
        # Convert single backslashes to double backslashes for JSON string representation
        denormalized = denormalized.replace('\\', '\\')
        
        # Fix drive letters again after double backslash conversion
        denormalized = re.sub(r'([A-Za-z]):\\', r'\1:\\', denormalized)
        denormalized = re.sub(r'([A-Za-z]):\\', r'\1:\\', denormalized)
        
        return denormalized
    
    def repair_json_field(value):
        """Intelligently detect and repair JSON fields, even if they're escaped or malformed"""
        if value is None:
            return None
        
        # If it's already a dict or list, return as is
        if isinstance(value, (dict, list)):
            return value
        
        # If it's not a string, return original
        if not isinstance(value, str):
            return value
        
        # Trim whitespace
        value = value.strip()
        
        # Check if it looks like JSON (starts with { or [)
        if not (value.startswith('{') or value.startswith('[')):
            # Check if it might be a string representation of JSON
            if (value.startswith('"{') and value.endswith('}"')) or \
               (value.startswith("'{") and value.endswith("}'")) or \
               (value.startswith('"[') and value.endswith(']"')) or \
               (value.startswith("'[") and value.endswith("]'")):
                # Remove outer quotes
                value = value[1:-1]
            
            # Check again after removing quotes
            if not (value.strip().startswith('{') or value.strip().startswith('[')):
                return value  # Not JSON-like, return as is
        
        # Try to parse JSON
        try:
            # First attempt: direct parsing
            return json.loads(value)
        except json.JSONDecodeError:
            pass
        
        # Second attempt: Fix common issues
        try:
            # Replace escaped quotes
            fixed_value = value.replace('\\"', '"').replace("\\'", "'")
            # Fix unescaped newlines in strings
            fixed_value = re.sub(r'(?<!")\n(?!")', '\\n', fixed_value)
            # Fix missing quotes around keys
            fixed_value = re.sub(r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', fixed_value)
            # Fix single quotes to double quotes
            fixed_value = fixed_value.replace("'", '"')
            # Fix trailing commas
            fixed_value = re.sub(r',\s*}', '}', fixed_value)
            fixed_value = re.sub(r',\s*\]', ']', fixed_value)
            # Remove BOM if present
            if fixed_value.startswith('\ufeff'):
                fixed_value = fixed_value[1:]
            
            return json.loads(fixed_value)
        except json.JSONDecodeError:
            pass
        
        # Third attempt: Use ast.literal_eval for Python literals
        try:
            import ast
            result = ast.literal_eval(value)
            # If it parsed successfully, convert to JSON-serializable format
            if isinstance(result, (dict, list, tuple)):
                return result
        except (ValueError, SyntaxError, ImportError):
            pass
        
        # Fourth attempt: Handle nested escaped JSON
        try:
            # Try to unescape multiple times
            unescaped = value
            for _ in range(5):  # Max 5 levels of escaping
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
        
        # Fifth attempt: String to dict conversion for specific patterns
        try:
            # Check if it's a string representation of a dict/list
            if value.startswith('{') and value.endswith('}') or value.startswith('[') and value.endswith(']'):
                # Replace literal string 'NULL' with None
                fixed_value = value.replace(': "NULL"', ': null').replace(': NULL', ': null')
                fixed_value = fixed_value.replace('"NULL"', 'null')
                # Replace 'true'/'false' strings
                fixed_value = fixed_value.replace(': "true"', ': true').replace(': "false"', ': false')
                fixed_value = fixed_value.replace('"true"', 'true').replace('"false"', 'false')
                # Replace decimal strings
                fixed_value = re.sub(r'"(\d+\.\d+)"', r'\1', fixed_value)
                
                return json.loads(fixed_value)
        except json.JSONDecodeError:
            pass
        
        # If all attempts fail, return original string
        return value
    
    def unwrap_and_extract_config_title(accountmanagement_data):
        """
        Remove wrapper key from accountmanagement data and extract config title.
        
        If data is like: {"config_key": {actual_data}} -> 
            Return: {"configuration_title": "config_key", ...actual_data}
        
        If data already has configuration_title field:
            Update it with the wrapper key value (overwrite)
        
        If data is like: {} or {"key": "value"} (no nested dict wrapper) -> 
            Return as is (no extraction)
        
        If data is None or empty -> return {}
        """
        if accountmanagement_data is None:
            return {}
        
        # If it's not a dict, return as is (but wrapped in dict if needed)
        if not isinstance(accountmanagement_data, dict):
            # If it's an empty string or null-like, return empty dict
            if accountmanagement_data == '' or accountmanagement_data == 'null':
                return {}
            return accountmanagement_data
        
        # If dict is empty, return empty dict
        if len(accountmanagement_data) == 0:
            return {}
        
        # Check if the dict has exactly one key and that key's value is a dict
        keys = list(accountmanagement_data.keys())
        
        if len(keys) == 1:
            first_key = keys[0]
            first_value = accountmanagement_data[first_key]
            
            # If the value is a dict (nested structure), unwrap it and extract config title
            if isinstance(first_value, dict):
                print(f"       Extracted config title from wrapper key: '{first_key}'")
                
                # Create new dict with configuration_title and all data from inner dict
                result = dict(first_value)  # Copy all inner data
                result['configuration_title'] = first_key  # Add/extract config title
                
                return result
        
        # Otherwise, return as is (no wrapper to remove)
        return accountmanagement_data
    
    def normalize_gmail_path(value):
        """
        Normalize Gmail-related path segments from backslashes to underscores.
        Specifically targets paths containing \at\gmail\dot\com patterns.
        
        Example:
        Input:  "C:\\xampp\\htdocs\\harvcore\\mt5\\MetaTrader 5 tolulopestandarddemo\\at\\gmail\\dot\\com 2 Deriv\\terminal64.exe"
        Output: "C:\\xampp\\htdocs\\harvcore\\mt5\\MetaTrader 5 tolulopestandarddemo_at_gmail_dot_com 2 Deriv\\terminal64.exe"
        """
        if value is None:
            return None
        
        # Only process string values
        if not isinstance(value, str):
            return value
        
        # Only process if it contains Gmail-related path pattern
        # Pattern: \at\gmail\dot\com or \\at\\gmail\\dot\\com
        import re
        
        # Check if the path contains the Gmail pattern
        if 'at\\gmail\\dot\\com' in value or 'at/gmail/dot/com' in value:
            # Replace the segment \at\gmail\dot\com with _at_gmail_dot_com
            # This preserves the rest of the path structure
            
            # Handle double backslash representation (JSON strings)
            # Pattern: \\at\\gmail\\dot\\com (double backslashes in string)
            if '\\\\at\\\\gmail\\\\dot\\\\com' in value:
                # Replace the entire segment
                value = value.replace('\\\\at\\\\gmail\\\\dot\\\\com', '_at_gmail_dot_com')
            
            # Handle single backslash representation (normal Windows paths)
            elif '\\at\\gmail\\dot\\com' in value:
                value = value.replace('\\at\\gmail\\dot\\com', '_at_gmail_dot_com')
            
            # Handle forward slash representation (Unix-style paths)
            elif '/at/gmail/dot/com' in value:
                value = value.replace('/at/gmail/dot/com', '_at_gmail_dot_com')
            
            # Handle mixed slashes (backslashes in path, but check for any combination)
            else:
                # More flexible pattern matching for various slash combinations
                # Replace \at\gmail\dot\com (with any slash direction)
                pattern = r'[\\/]at[\\/]gmail[\\/]dot[\\/]com'
                value = re.sub(pattern, '_at_gmail_dot_com', value)
        
        return value
    
    def clean_record(record):
        """Clean a record by repairing all fields that might contain JSON and denormalizing paths"""
        cleaned = {}
        for key, value in record.items():
            # First, denormalize path fields if they are strings
            if isinstance(value, str) and len(value) > 0:
                # Denormalize path fields before JSON repair
                value = denormalize_path_value(value, key)
                
                # Attempt to repair JSON fields
                repaired = repair_json_field(value)
                cleaned[key] = repaired
            else:
                cleaned[key] = value
        
        # Process accountmanagement field - NO AUTO-FILLING, just unwrap and extract config title
        if 'accountmanagement' in cleaned:
            accountmanagement = cleaned.get('accountmanagement')
            
            # Unwrap the accountmanagement data and extract configuration title
            cleaned['accountmanagement'] = unwrap_and_extract_config_title(accountmanagement)
            
            # Ensure it's at least an empty dict if None
            if cleaned['accountmanagement'] is None:
                cleaned['accountmanagement'] = {}
        
        # NEW: Normalize Gmail paths in all fields (last section)
        for key, value in cleaned.items():
            # Only process string values
            if isinstance(value, str):
                # Check if it's a path field or contains path-like structure
                if 'path' in key.lower() or isinstance(value, str) and ('\\at\\gmail\\dot\\com' in value or '/at/gmail/dot/com' in value):
                    cleaned[key] = normalize_gmail_path(value)
        
        return cleaned
    
    print("\n" + "="*70)
    print(f"  FETCHING TABLES (HYBRID MODE: IP → VS Code ID)")
    print("="*70)
    print(f"  Start Time  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Batch Size  : {batch_size:,} records per batch")
    print("-"*70)
    
    try:
        # STEP 0: Get identifiers (IP first, then VS Code ID as fallback)
        print("\n🖥️ [0/6] Getting Computer Identifiers...")
        
        # First, try to get local IP
        computer_id = get_local_ip()
        identification_method = None
        user_ids_to_fetch = []
        
        # Fetch system_server_config first to check both identifiers
        print(f"\n🔍 Fetching System Server Configuration...")
        query = "SELECT system_server_config FROM server_account LIMIT 1"
        result = db.execute_query(query)
        
        config_data = {}
        if result.get('status') == 'success':
            rows = result.get('results', [])
            if rows and len(rows) > 0:
                config_value = rows[0].get('system_server_config')
                config_data = parse_server_config(config_value)
                print(f"  ✅ Successfully parsed server configuration")
            else:
                print(f"  No server_account records found")
                return
        else:
            print(f"  Failed to fetch server_account: {result.get('message')}")
            return
        
        # Show current config for debugging
        if config_data:
            print(f"\n  📋 Current Computer Configuration:")
            for comp_id, data in config_data.items():
                if isinstance(data, list):
                    numeric_ids = [item for item in data if isinstance(item, (int, str)) and str(item).isdigit()]
                    # Truncate long IDs for display
                    display_id = comp_id[:30] + "..." if len(comp_id) > 33 else comp_id
                    print(f"     - {display_id}: {len(numeric_ids)} user(s)")
                else:
                    display_id = comp_id[:30] + "..." if len(comp_id) > 33 else comp_id
                    print(f"     - {display_id}: {type(data).__name__} (invalid format)")
        
        # Try IP first
        if computer_id:
            print(f"\n  🔍 Trying IP Address: {computer_id}")
            if computer_id in config_data:
                user_ids_to_fetch = extract_user_ids_from_config(config_data, computer_id, "IP")
                if user_ids_to_fetch:
                    identification_method = 'ip_address'
                    print(f"  ✅ SUCCESS: Found {len(user_ids_to_fetch)} user(s) linked to IP address")
                else:
                    print(f"  ⚠️ IP address found in config but has no valid user IDs assigned")
            else:
                print(f"   IP address NOT FOUND in system_server_config")
        else:
            print(f"   Could not retrieve local IP address")
        
        # If IP didn't work, try VS Code ID as fallback
        if not user_ids_to_fetch:
            print(f"\n  🔄 Falling back to VS Code Machine ID...")
            vscode_id = get_vscode_machine_id()
            
            if vscode_id:
                print(f"  🔍 Trying VS Code ID: {vscode_id[:32]}...")
                if vscode_id in config_data:
                    user_ids_to_fetch = extract_user_ids_from_config(config_data, vscode_id, "VS Code ID")
                    if user_ids_to_fetch:
                        identification_method = 'vscode_machine_id'
                        computer_id = vscode_id
                        print(f"  ✅ SUCCESS: Found {len(user_ids_to_fetch)} user(s) linked to VS Code ID")
                    else:
                        print(f"  ⚠️ VS Code ID found in config but has no valid user IDs assigned")
                else:
                    print(f"   VS Code ID NOT FOUND in system_server_config")
            else:
                print(f"   Could not retrieve VS Code Machine ID")
        
        # Check if we found any valid identifier with users
        if not user_ids_to_fetch:
            print(f"\n{'='*70}")
            print(f"  EXPORT SKIPPED - NO VALID IDENTIFIER WITH USERS")
            print(f"{'='*70}")
            print(f"  Reason: Neither IP address nor VS Code ID is linked to any users")
            print(f"  ℹ️ Please add either your IP address or VS Code ID to")
            print(f"     server_account.system_server_config with associated user IDs")
            print(f"{'='*70}")
            return
        
        print(f"\n  ✅ Using identifier: {identification_method}")
        print(f"  📋 User IDs to fetch: {user_ids_to_fetch[:20]}{'...' if len(user_ids_to_fetch) > 20 else ''}")
        
        # ===== NEW: Fetch and write accountmanagement to DEFAULT_ACCOUNTMANAGEMENT =====
        print(f"\n📝 [NEW] Fetching Account Management from server_account...")
        try:
            # Fetch just the accountmanagement column
            accountmanagement_query = "SELECT accountmanagement FROM server_account LIMIT 1"
            am_result = db.execute_query(accountmanagement_query)
            
            if am_result.get('status') == 'success':
                am_rows = am_result.get('results', [])
                if am_rows and len(am_rows) > 0:
                    accountmanagement_data = am_rows[0].get('accountmanagement')
                    
                    # Parse/repair the JSON
                    if accountmanagement_data:
                        if isinstance(accountmanagement_data, str):
                            parsed_am = repair_json_field(accountmanagement_data)
                        else:
                            parsed_am = accountmanagement_data
                    else:
                        parsed_am = {}
                    
                    # Write to DEFAULT_ACCOUNTMANAGEMENT file
                    os.makedirs(os.path.dirname(DEFAULT_ACCOUNTMANAGEMENT), exist_ok=True)
                    with open(DEFAULT_ACCOUNTMANAGEMENT, 'w', encoding='utf-8') as am_file:
                        json.dump(parsed_am, am_file, default=str, indent=2)
                    
                    print(f"   ✅ Account Management written to: {DEFAULT_ACCOUNTMANAGEMENT}")
                    print(f"   📊 Data size: {len(json.dumps(parsed_am))} bytes")
                else:
                    print(f"   ⚠️ No server_account records found, writing empty dict")
                    os.makedirs(os.path.dirname(DEFAULT_ACCOUNTMANAGEMENT), exist_ok=True)
                    with open(DEFAULT_ACCOUNTMANAGEMENT, 'w', encoding='utf-8') as am_file:
                        json.dump({}, am_file, indent=2)
                    print(f"   ✅ Empty account management written to: {DEFAULT_ACCOUNTMANAGEMENT}")
            else:
                print(f"   ❌ Failed to fetch accountmanagement: {am_result.get('message')}")
                
        except Exception as e:
            print(f"   ❌ Error writing accountmanagement: {str(e)}")
            import traceback
            traceback.print_exc()
        # ===== END NEW SECTION =====
        
        # Step 2: Test Connection and Get Actual Data Columns (excluding analytics column)
        print("\n📡 [2/6] Testing Database Connection & Fetching Schema...")
        
        # Get all columns from insiders table except 'analytics'
        get_columns_query = """
        SELECT COLUMN_NAME 
        FROM information_schema.COLUMNS 
        WHERE TABLE_SCHEMA = DATABASE() 
        AND TABLE_NAME = 'insiders'
        AND COLUMN_NAME != 'analytics'
        ORDER BY ORDINAL_POSITION
        """
        
        columns_result = db.execute_query(get_columns_query)
        columns = []
        
        if columns_result.get('status') == 'success' and columns_result.get('results'):
            for row in columns_result['results']:
                column_name = row.get('COLUMN_NAME', '')
                if column_name and column_name.lower() != 'analytics':
                    columns.append(column_name)
            
            print(f"  📋 Found {len(columns)} columns from schema (excluding 'analytics'): {', '.join(columns[:5])}{'...' if len(columns) > 5 else ''}")
            
            # Test connection with a simple query
            test_query = f"SELECT {', '.join([f'`{col}`' for col in columns[:1]])} FROM insiders LIMIT 1"
            test_result = db.execute_query(test_query)
            
            if test_result.get('status') != 'success':
                print(f"   Connection FAILED: {test_result.get('message')}")
                return
        else:
            # Fallback: try to get columns from data
            print(f"    Could not fetch schema from information_schema, trying SELECT *...")
            test_query = "SELECT * FROM insiders LIMIT 1"
            test_result = db.execute_query(test_query)
            
            if test_result.get('status') != 'success':
                print(f"   Connection FAILED: {test_result.get('message')}")
                return
            
            results = test_result.get('results', [])
            if results and len(results) > 0:
                # Get column names from the first row's keys, excluding 'analytics'
                all_columns = list(results[0].keys())
                columns = [col for col in all_columns if col.lower() != 'analytics']
                print(f"  📋 Found {len(columns)} columns from data (excluding 'analytics'): {', '.join(columns[:5])}{'...' if len(columns) > 5 else ''}")
            else:
                print(f"    No data rows to determine schema")
                columns = []
        
        print(f"   Connection SUCCESSFUL")
        
        # Step 3: Get Total Count (only for the specific user IDs)
        print("\n📊 [3/6] Counting Total Records (filtered by user IDs)...")
        
        # Build IN clause for user IDs
        id_placeholders = ','.join(['%s'] * len(user_ids_to_fetch))
        count_query = f"""
            SELECT COUNT(*) as total 
            FROM insiders 
            WHERE id IN ({id_placeholders})
        """
        
        count_result = db.execute_query(count_query, params=user_ids_to_fetch)
        
        total_rows = 0
        if isinstance(count_result, dict) and count_result.get('status') == 'success':
            results = count_result.get('results', [])
            if results and len(results) > 0:
                total_rows = int(results[0].get('total') or 
                               results[0].get('COUNT(*)') or 
                               results[0].get('count') or 0)
        
        print(f"  📈 Total Records Found (filtered): {total_rows:,}")
        
        if total_rows == 0:
            print(f"    No records found for the specified user IDs. Export skipped.")
            print(f"    User IDs queried: {user_ids_to_fetch[:20]}{'...' if len(user_ids_to_fetch) > 20 else ''}")
            return
        
        # Calculate batches needed
        total_batches = (total_rows + batch_size - 1) // batch_size
        print(f"  📦 Estimated Batches: {total_batches}")
        
        # Step 4: Fetch Server Account Management and Requirements (READ ONLY - NO WRITING)
        print(f"\n⚙️ [4/6] Fetching Server Account Management & Requirements (Read Only)...")
        
        server_acct_query = """
            SELECT 
                accountmanagement,
                min_broker_balance,
                contract_duration
            FROM server_account 
            LIMIT 1
        """
        server_result = db.execute_query(server_acct_query)
        
        default_accountmanagement = None
        
        if server_result.get('status') == 'success':
            server_rows = server_result.get('results', [])
            if server_rows and len(server_rows) > 0:
                server_row = server_rows[0]
                server_acct_management = server_row.get('accountmanagement')
                min_broker_balance = server_row.get('min_broker_balance')
                contract_duration = server_row.get('contract_duration')
                
                # Parse the accountmanagement JSON
                parsed_management = None
                if server_acct_management:
                    try:
                        if isinstance(server_acct_management, str):
                            parsed_management = repair_json_field(server_acct_management)
                        else:
                            parsed_management = server_acct_management
                        
                        if not isinstance(parsed_management, dict):
                            if isinstance(parsed_management, list):
                                parsed_management = {'data': parsed_management}
                            else:
                                parsed_management = {'value': parsed_management}
                    except Exception as e:
                        print(f"    Failed to parse accountmanagement: {str(e)}")
                        parsed_management = {}
                else:
                    parsed_management = {}
                
                if not isinstance(parsed_management, dict):
                    parsed_management = {}
                
                # Add requirements section with fetched values
                requirements = {}
                
                if contract_duration is not None:
                    requirements['contract_duration'] = contract_duration
                else:
                    requirements['contract_duration'] = None
                
                if min_broker_balance is not None:
                    if isinstance(min_broker_balance, Decimal):
                        requirements['min_broker_balance'] = float(min_broker_balance)
                    else:
                        requirements['min_broker_balance'] = min_broker_balance
                else:
                    requirements['min_broker_balance'] = None
                
                parsed_management['requirements'] = requirements
                default_accountmanagement = parsed_management
                
                print(f"   ✅ Server Account Management Loaded (READ ONLY - Not Modified)")
                print(f"  🔍 Server Requirements:")
                print(f"     - contract_duration: {requirements.get('contract_duration')} days")
                print(f"     - min_broker_balance: ${requirements.get('min_broker_balance')}")
                
                # Display existing accountmanagement structure (for reference)
                print(f"  📋 Accountmanagement structure:")
                if parsed_management:
                    # Show first few keys
                    keys = list(parsed_management.keys())
                    if keys:
                        print(f"     Keys: {', '.join(keys[:5])}{'...' if len(keys) > 5 else ''}")
                    if 'configuration_title' in parsed_management:
                        print(f"     Configuration Title: {parsed_management.get('configuration_title')}")
                    if 'export_history' in parsed_management:
                        print(f"     Export History: {len(parsed_management.get('export_history', []))} exports")
                else:
                    print(f"     No existing accountmanagement data")
            else:
                print(f"    No server_account records found")
        else:
            print(f"    Failed to fetch server account management: {server_result.get('message')}")
        
        # Step 5: Prepare Output Directory and Stream Data
        print(f"\n📁 [5/6] Preparing Output Directory for Insiders Data...")
        os.makedirs(os.path.dirname(FETCHED_INVESTORS), exist_ok=True)
        print(f"   Directory ready: {os.path.dirname(FETCHED_INVESTORS)}")
        
        # Step 6: Stream Insiders Data
        print(f"\n📥 [6/6] Streaming Insiders Records to File...")
        print(f"  📌 Note: 'analytics' column is EXCLUDED from export")
        print(f"  🖥️ Using: {identification_method.upper()}: {computer_id if identification_method == 'ip_address' else computer_id[:32] + '...'}")
        print(f"  🎯 Filter: Only user IDs associated with this identifier")
        print(f"  🔧 AccountManagement: Existing data preserved as-is (no modification)")
        print(f"  🔧 AccountManagement: Wrapper keys extracted to 'configuration_title' field (view only)")
        print(f"  🔧 Gmail Path Normalization: Converting \\at\\gmail\\dot\\com to _at_gmail_dot_com")
        print(f"  ⚠️  IMPORTANT: server_account.accountmanagement is NOT modified")
        print("-"*70)
        
        start_time = datetime.now()
        bytes_written = 0
        current_batch = 0
        json_repaired_count = 0
        accountmanagement_unwrapped_count = 0
        path_denormalized_count = 0
        gmail_normalized_count = 0
        
        if not columns:
            print(f"    No columns available for query. Cannot proceed.")
            return
        
        columns = [col for col in columns if col.lower() != 'analytics']
        select_clause = ", ".join([f"`{col}`" for col in columns])
        
        print(f"  📋 Exporting columns: {', '.join(columns[:5])}{'...' if len(columns) > 5 else ''}")
        print(f"  👥 Filtering for {len(user_ids_to_fetch)} specific user IDs")
        
        with open(FETCHED_INVESTORS, 'w', encoding='utf-8') as f:
            # Write opening brace - NO METADATA SECTION
            f.write('{\n')
            first_record = True
            offset = 0
            
            while offset < total_rows:
                current_batch += 1
                batch_start = datetime.now()
                
                query = f"""
                    SELECT {select_clause} 
                    FROM insiders 
                    WHERE id IN ({id_placeholders})
                    ORDER BY id
                    LIMIT {batch_size} OFFSET {offset}
                """
                result = db.execute_query(query, params=user_ids_to_fetch)
                
                if result.get('status') != 'success':
                    print(f"\n   QUERY ERROR at batch {current_batch}: {result.get('message')}")
                    break
                    
                rows = result.get('results', [])
                if not rows:
                    print(f"\n    No rows returned at offset {offset:,}. Stopping.")
                    break
                
                batch_bytes = 0
                for row in rows:
                    record_id = str(row.get('id') or row.get('ID') or f"record_{offset}")
                    
                    if not first_record:
                        f.write(',\n')
                    
                    # Track original accountmanagement state for unwrapping count
                    original_accountmanagement = row.get('accountmanagement')
                    
                    cleaned_row = clean_record(row)
                    
                    # Check if accountmanagement was unwrapped and config title extracted
                    if original_accountmanagement is not None:
                        if isinstance(original_accountmanagement, dict) and len(original_accountmanagement) == 1:
                            first_key = list(original_accountmanagement.keys())[0]
                            if isinstance(original_accountmanagement[first_key], dict):
                                accountmanagement_unwrapped_count += 1
                    
                    # Count path denormalizations
                    for key, value in cleaned_row.items():
                        if 'path' in key.lower() and isinstance(value, str) and '\\' in value:
                            path_denormalized_count += 1
                        
                        # Count Gmail normalizations
                        if isinstance(value, str) and '_at_gmail_dot_com' in value:
                            gmail_normalized_count += 1
                    
                    # Convert special types to JSON-serializable format
                    for key, value in cleaned_row.items():
                        if value is None:
                            cleaned_row[key] = None
                        elif isinstance(value, (datetime, date)):
                            cleaned_row[key] = value.isoformat()
                        elif isinstance(value, Decimal):
                            cleaned_row[key] = float(value)
                    
                    # Count JSON repairs
                    for key, value in cleaned_row.items():
                        if isinstance(value, (dict, list)) and key in row and isinstance(row[key], str):
                            json_repaired_count += 1
                    
                    json_str = json.dumps(cleaned_row, default=str, indent=2)
                    lines = json_str.split('\n')
                    indented_lines = ['    ' + line for line in lines]
                    formatted_json = '\n'.join(indented_lines)
                    
                    line = f'  "{record_id}": {formatted_json}'
                    f.write(line)
                    
                    batch_bytes += len(line.encode('utf-8'))
                    first_record = False
                
                offset += len(rows)
                bytes_written += batch_bytes
                
                batch_time = (datetime.now() - batch_start).total_seconds()
                records_per_sec = len(rows) / batch_time if batch_time > 0 else 0
                
                progress = (offset / total_rows) * 100
                bar_length = 30
                filled = int(bar_length * offset // total_rows) if total_rows > 0 else 0
                bar = '█' * filled + '░' * (bar_length - filled)
                
                print(f"  Batch {current_batch:>3}/{total_batches:<3} [{bar}] {progress:5.1f}% | "
                      f"Records: {offset:>{len(str(total_rows))},}/{total_rows:,} | "
                      f"Speed: {records_per_sec:>6,.0f} rec/s | "
                      f"Size: {bytes_written/1024:>8,.1f} KB")
            
            f.write('\n}')
        
        # NO METADATA SAVING - READ ONLY APPROACH
        
        # Final Summary
        elapsed_time = (datetime.now() - start_time).total_seconds()
        avg_speed = offset / elapsed_time if elapsed_time > 0 else 0
        
        print("-"*70)
        print(f"\n📋 EXPORT SUMMARY")
        print("="*70)
        print(f"   Status           : SUCCESS")
        print(f"  🖥️  Identifier      : {identification_method.upper()}")
        print(f"  🔑 Value           : {computer_id if identification_method == 'ip_address' else computer_id[:32] + '...'}")
        print(f"  👥 Valid User IDs   : {len(user_ids_to_fetch)} users")
        print(f"  📊 Records Exported : {offset:,} / {total_rows:,}")
        print(f"  📦 Batches Used     : {current_batch}")
        print(f"  📋 Schema Columns   : {len(columns)} (excluded 'analytics')")
        print(f"  🔧 JSON Repairs     : {json_repaired_count} fields repaired")
        print(f"  🔄 Path Denormalized: {path_denormalized_count} path fields restored")
        print(f"  🧹 Config Title Extracted: {accountmanagement_unwrapped_count} records")
        print(f"  📧 Gmail Normalized : {gmail_normalized_count} path fields normalized")
        print(f"  💾 File Size        : {bytes_written/1024:,.1f} KB ({bytes_written/1048576:.2f} MB)")
        print(f"  ⏱️  Total Time       : {elapsed_time:.1f} seconds")
        print(f"  ⚡ Average Speed    : {avg_speed:,.0f} records/second")
        print(f"  📁 Output File      : {FETCHED_INVESTORS}")
        print(f"  📁 Account Mgmt File: {DEFAULT_ACCOUNTMANAGEMENT}")
        print(f"  ⚠️  Database         : server_account.accountmanagement NOT modified (read-only)")
        print("="*70)
        print(f"  🕐 Completion Time  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*70)
        
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

def update_tables_streaming(batch_size=5000):
    """Stream updates from JSON to database without holding all in memory
    - Reads from BOTH ALL_UPDATED_INVESTORS and ALL_FETCHED_INVESTORS
    - Merges data from both files
    - Does NOT delete files after updating
    """
    
    print("\n" + "="*70)
    print(f"  UPDATING TABLES")
    print("="*70)
    print(f"  Start Time  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Batch Size  : {batch_size:,} records per batch")
    print("-"*70)
    
    try:
        # Step 1: Read from BOTH source files and merge
        print("\n📁 [1/6] Checking Source Files...")
        
        merged_data = {}
        files_loaded = []
        
        # Check and load ALL_UPDATED_INVESTORS
        if os.path.exists(ALL_UPDATED_INVESTORS):
            try:
                with open(ALL_UPDATED_INVESTORS, 'r', encoding='utf-8') as f:
                    updated_data = json.load(f)
                    if isinstance(updated_data, dict):
                        merged_data.update(updated_data)
                        files_loaded.append('ALL_UPDATED_INVESTORS.json')
                        print(f"   ✅ Loaded from update file: {ALL_UPDATED_INVESTORS}")
                        print(f"      📊 Records: {len(updated_data):,}")
                    else:
                        print(f"   ⚠️ Update file has invalid format (expected dict): {ALL_UPDATED_INVESTORS}")
            except Exception as e:
                print(f"   ⚠️ Error reading update file: {str(e)}")
        else:
            print(f"   ⚠️ Update file not found: {ALL_UPDATED_INVESTORS}")
        
        # Check and load ALL_FETCHED_INVESTORS
        if os.path.exists(ALL_FETCHED_INVESTORS):
            try:
                with open(ALL_FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
                    fetched_data = json.load(f)
                    if isinstance(fetched_data, dict):
                        # Merge, but don't overwrite ALL_UPDATED_INVESTORS data if it exists
                        for key, value in fetched_data.items():
                            if key not in merged_data:
                                merged_data[key] = value
                        files_loaded.append('ALL_FETCHED_INVESTORS.json')
                        print(f"   ✅ Loaded from fetched file: {ALL_FETCHED_INVESTORS}")
                        print(f"      📊 Records: {len(fetched_data):,}")
                    else:
                        print(f"   ⚠️ Fetched file has invalid format (expected dict): {ALL_FETCHED_INVESTORS}")
            except Exception as e:
                print(f"   ⚠️ Error reading fetched file: {str(e)}")
        else:
            print(f"   ⚠️ Fetched file not found: {ALL_FETCHED_INVESTORS}")
        
        if not merged_data:
            print(f"\n   ❌ No data loaded from any source file")
            print(f"   ℹ️ Please run fetch_tables_streaming() first to create the fetched file")
            return
        
        total_investors = len(merged_data)
        print(f"\n  📊 Total Records Merged: {total_investors:,}")
        print(f"  📁 Source Files: {', '.join(files_loaded)}")
        
        # Step 2: Test Database Connection and get table columns
        print("\n📡 [2/6] Testing Database Connection...")
        test_query = "SELECT id FROM insiders LIMIT 1"
        test_result = db.execute_query(test_query)
        
        if test_result.get('status') != 'success':
            print(f"   Connection FAILED: {test_result.get('message')}")
            return
        print(f"   Connection SUCCESSFUL")
        
        # Get all column names from insiders table
        print("\n🔍 Fetching insiders table columns...")
        get_columns_query = """
        SELECT COLUMN_NAME 
        FROM information_schema.COLUMNS 
        WHERE TABLE_SCHEMA = DATABASE() 
        AND TABLE_NAME = 'insiders'
        """
        
        columns_result = db.execute_query(get_columns_query)
        existing_columns = set()
        
        if columns_result.get('status') == 'success' and columns_result.get('results'):
            for row in columns_result['results']:
                column_name = row.get('COLUMN_NAME', '')
                if column_name:
                    existing_columns.add(column_name.lower())
            print(f"   Found {len(existing_columns)} columns in insiders table")
            print(f"  📋 Columns: {', '.join(sorted(existing_columns))}")
        else:
            print(f"    Could not fetch column information")
            existing_columns = set()
        
        # Initialize variables for insiders update
        investors_to_update = {}
        investors_to_skip = []  # Records not in DB (will be skipped, not removed)
        successfully_updated_ids = []
        updated_count = 0
        failed_count = 0
        elapsed_time = 0
        avg_speed = 0
        unmapped_fields = set()
        
        # Helper function to determine if a value should be treated as JSON
        def is_json_field(value):
            """Determine if a value should be stored as JSON in database"""
            if value is None:
                return False
            if isinstance(value, (dict, list)):
                return True
            if isinstance(value, str):
                stripped = value.strip()
                if stripped.startswith('{') and stripped.endswith('}'):
                    return True
                if stripped.startswith('[') and stripped.endswith(']'):
                    return True
            return False
        
        def normalize_path_value(value, field_name):
            """Normalize path values: ONLY replace backslashes with underscores"""
            if value is None:
                return None
            if 'path' not in field_name.lower():
                return value
            if not isinstance(value, str):
                return value
            
            normalized = value.replace('\\', '_')
            if normalized != value:
                print(f"       Normalizing path field '{field_name}':")
                print(f"         Original: {value[:100]}{'...' if len(value) > 100 else ''}")
                print(f"         Normalized: {normalized[:100]}{'...' if len(normalized) > 100 else ''}")
            return normalized
        
        def normalize_execution_start_date(value):
            """Normalize execution_start_date to YYYY-MM-DD format"""
            if value is None or not isinstance(value, str):
                return value
            
            date_formats = [
                "%B %d, %Y",
                "%b %d, %Y",
                "%d-%b-%Y",
                "%Y-%m-%d",
                "%m/%d/%Y",
                "%d/%m/%Y",
                "%Y/%m/%d",
            ]
            
            original_value = value.strip()
            for date_format in date_formats:
                try:
                    parsed_date = datetime.strptime(original_value, date_format)
                    normalized = parsed_date.strftime("%Y-%m-%d")
                    if normalized != original_value:
                        print(f"       Normalizing execution_start_date:")
                        print(f"         Original: {original_value}")
                        print(f"         Normalized: {normalized}")
                    return normalized
                except ValueError:
                    continue
            return value
        
        def normalize_json_value(value):
            """Convert value to proper JSON for database storage"""
            if value is None:
                return None
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            if isinstance(value, str):
                stripped = value.strip()
                if stripped.upper() == 'NULL':
                    return None
                if stripped == '' or stripped == '{}':
                    return '{}'
                if (stripped.startswith('{') and stripped.endswith('}')) or \
                   (stripped.startswith('[') and stripped.endswith(']')):
                    try:
                        json.loads(stripped)
                        return stripped
                    except:
                        return value
            return value
        
        # Step 3: Get existing IDs for validation
        print("\n🔍 [3/6] Fetching Existing Record IDs...")
        existing_ids_query = "SELECT id FROM insiders"
        existing_result = db.execute_query(existing_ids_query)
        
        existing_ids = set()
        if existing_result.get('status') == 'success':
            for row in existing_result.get('results', []):
                existing_ids.add(str(row.get('id')))
        
        print(f"  📊 Existing Records in DB: {len(existing_ids):,}")
        
        # Step 4: Identify which records exist in DB vs not
        print(f"\n📖 [4/6] Processing Records...")
        
        for investor_id, investor_data in merged_data.items():
            if investor_id in existing_ids:
                investors_to_update[investor_id] = investor_data
            else:
                investors_to_skip.append(investor_id)
        
        print(f"  📊 Records to Update (exist in DB): {len(investors_to_update):,}")
        print(f"  ⚠️  Records Skipped (not in DB): {len(investors_to_skip):,}")
        
        if investors_to_skip:
            print(f"     ℹ️ These records will be skipped (not deleted from file)")
            # Show first few skipped IDs
            if len(investors_to_skip) <= 10:
                print(f"     Skipped IDs: {', '.join(investors_to_skip)}")
            else:
                print(f"     Skipped IDs (first 10): {', '.join(investors_to_skip[:10])}...")
        
        # Step 5: Update Database in Batches
        if investors_to_update:
            print(f"\n📤 [5/6] Updating Database Records...")
            print("-"*70)
            
            start_time = datetime.now()
            updated_count = 0
            failed_count = 0
            current_batch = 0
            
            investor_ids = list(investors_to_update.keys())
            total_batches = (len(investor_ids) + batch_size - 1) // batch_size
            
            for i in range(0, len(investor_ids), batch_size):
                current_batch += 1
                batch_start = datetime.now()
                
                batch_ids = investor_ids[i:i + batch_size]
                batch_updates = 0
                batch_failed = 0
                
                for investor_id in batch_ids:
                    investor = investors_to_update[investor_id]
                    
                    # Build UPDATE query dynamically
                    update_parts = []
                    
                    for json_field, value in investor.items():
                        if json_field == 'id':
                            continue
                        
                        if json_field.lower() not in existing_columns:
                            unmapped_fields.add(json_field)
                            continue
                        
                        # Normalize values
                        if json_field.lower() == 'execution_start_date':
                            value = normalize_execution_start_date(value)
                        
                        if 'path' in json_field.lower():
                            value = normalize_path_value(value, json_field)
                        
                        # Handle different value types
                        if is_json_field(value):
                            json_value = normalize_json_value(value)
                            if json_value is None:
                                update_parts.append(f"`{json_field}` = NULL")
                            else:
                                escaped_json = json_value.replace("'", "\\'")
                                update_parts.append(f"`{json_field}` = '{escaped_json}'")
                        elif value is None:
                            update_parts.append(f"`{json_field}` = NULL")
                        elif isinstance(value, bool):
                            db_value = '1' if value else '0'
                            update_parts.append(f"`{json_field}` = {db_value}")
                        elif isinstance(value, (int, float)):
                            update_parts.append(f"`{json_field}` = {value}")
                        elif isinstance(value, str):
                            if value.strip().upper() == 'NULL':
                                update_parts.append(f"`{json_field}` = NULL")
                            else:
                                escaped_value = value.replace("'", "\\'")
                                update_parts.append(f"`{json_field}` = '{escaped_value}'")
                        else:
                            str_value = str(value)
                            escaped_value = str_value.replace("'", "\\'")
                            update_parts.append(f"`{json_field}` = '{escaped_value}'")
                    
                    if not update_parts:
                        continue
                    
                    set_clause = ", ".join(update_parts)
                    query = f"UPDATE insiders SET {set_clause} WHERE id = {int(investor_id)}"
                    
                    result = db.execute_query(query)
                    
                    if result.get('status') == 'success':
                        batch_updates += 1
                        updated_count += 1
                        successfully_updated_ids.append(investor_id)
                    else:
                        batch_failed += 1
                        failed_count += 1
                        print(f"      Failed to update investor {investor_id}: {result.get('message')}")
                
                # Batch progress
                batch_time = (datetime.now() - batch_start).total_seconds()
                records_per_sec = len(batch_ids) / batch_time if batch_time > 0 else 0
                
                progress = ((i + len(batch_ids)) / len(investor_ids)) * 100
                bar_length = 30
                filled = int(bar_length * (i + len(batch_ids)) // len(investor_ids))
                bar = '█' * filled + '░' * (bar_length - filled)
                
                print(f"  Batch {current_batch:>3}/{total_batches:<3} [{bar}] {progress:5.1f}% | "
                      f"Updated: {batch_updates:>4} | Failed: {batch_failed:>3} | "
                      f"Speed: {records_per_sec:>6,.0f} rec/s | "
                      f"Total: {updated_count:>{len(str(len(investor_ids)))},}/{len(investor_ids):,}")
            
            if unmapped_fields:
                print(f"\n    Unmapped/Non-existent fields found (skipped):")
                for field in sorted(unmapped_fields):
                    print(f"     - {field}")
            
            elapsed_time = (datetime.now() - start_time).total_seconds()
            avg_speed = updated_count / elapsed_time if elapsed_time > 0 else 0
        else:
            print(f"\n📤 [5/6] No records to update - skipping insiders update")
        
        # Step 6: DO NOT DELETE OR MODIFY THE SOURCE FILES
        print(f"\n💾 [6/6] Preserving Source Files (No Deletion)...")
        print(f"   ℹ️ Source files preserved")
        print(f"   📊 Total records in merged data: {total_investors:,}")
        print(f"   ✅ Updated successfully: {len(successfully_updated_ids):,}")
        print(f"   ⚠️ Skipped (not in DB): {len(investors_to_skip):,}")
        print(f"   ℹ️ No data was deleted from any file")
        
        
        # Final Summary
        print("-"*70)
        print(f"\n📋 UPDATE SUMMARY")
        print("="*70)
        
        # Insiders Summary
        print(f"\n  📊 INSIDERS UPDATE:")
        if total_investors > 0:
            print(f"     Status              : {'SUCCESS' if failed_count == 0 else 'COMPLETED WITH ERRORS'}")
            print(f"     Source Files        : {', '.join(files_loaded)}")
            print(f"     Total Records       : {total_investors:,}")
            print(f"     Records Updated     : {updated_count:,}")
            print(f"     Records Skipped     : {len(investors_to_skip):,} (not in DB)")
            print(f"     Failed Updates      : {failed_count:,}")
            print(f"     Time                : {elapsed_time:.1f} seconds")
            print(f"     Speed               : {avg_speed:,.0f} records/second")
            print(f"     Files Preserved     : YES (no deletion)")
            
            if successfully_updated_ids:
                print(f"     Sample Updated IDs  : {', '.join(successfully_updated_ids[:5])}{'...' if len(successfully_updated_ids) > 5 else ''}")
            
            if unmapped_fields:
                print(f"\n       Skipped Fields (not in DB):")
                for field in sorted(unmapped_fields)[:10]:
                    print(f"        - {field}")
                if len(unmapped_fields) > 10:
                    print(f"        ... and {len(unmapped_fields) - 10} more")
        else:
            print(f"     Status              : SKIPPED (no data to process)")
        
        print(f"\n  🕐 Completion Time     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*70)
        
    except json.JSONDecodeError as e:
        print(f"\n{'='*70}")
        print(f"   JSON PARSE ERROR")
        print(f"{'='*70}")
        print(f"  Error: {str(e)}")
        print(f"{'='*70}")
        
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

def close_db_browser():
    db.shutdown()
    print(f"\n🔒 Database connection closed.")
    
def create_investor_mt5_files(inv_id=None):
    """
    Creates MT5 terminal folders for investors by copying from DEFAULT_MT5_PATH
    
    Args:
        inv_id: Required - specific investor ID to process (for multiprocessing)
    
    Logic:
        1. If user is suspended/blacklisted -> IGNORE completely (skip immediately)
        2. If folder doesn't exist and user NOT suspended -> CREATE folder, update Terminal_path,
           and if application_status is 'pending', change it to 'just-joined'.
        3. If folder exists and user NOT suspended -> ENSURE Terminal_path is set in record,
           and if application_status is 'pending', change it to 'just-joined'.
    
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
    if not os.path.exists(FETCHED_INVESTORS):
        msg = f"Fetched investors file not found: {FETCHED_INVESTORS}"
        print(f" {msg}")
        result['message'] = msg
        return result
    
    # Load suspended accounts (read-only, no lock needed)
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
            print(f"⚠️ Error loading suspended accounts: {e}")
    else:
        print(f"ℹ️ No suspended accounts file found - all users will be processed normally")
    
    # Load fetched investors data (read-only)
    try:
        with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
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
    
    # RULE 1: If user is suspended/blacklisted -> Skip immediately or clean up
    if investor_id_str in suspended_ids:
        broker = investor_data.get('broker', '').strip()
        investor_id_value = investor_data.get('id', '').strip()
        email = investor_data.get('email', '').strip()
        
        # Create folder name with email format for suspended users
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
                
                # Update the copy
                if 'Terminal_path' in investor_data:
                    investor_data['Terminal_path'] = ''
                
                result['updated_data'] = {inv_id_str: investor_data}
                result['success'] = True
                
                # Save individual result to temp file
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
            msg = f"SUSPENDED ID:{inv_id} - Blacklisted, skipping (no folder to delete)"
            print(f"🚫 {msg}")
            result['message'] = msg
            return result
    
    # Extract broker, id, and email for valid accounts
    broker = investor_data.get('broker', '').strip()
    investor_id_value = investor_data.get('id', '').strip()
    email = investor_data.get('email', '').strip()
    
    if not broker or not investor_id_value:
        msg = f"Investor {inv_id} missing broker or id, skipping"
        print(f"⚠️ {msg}")
        result['message'] = msg
        return result
    
    # Sanitize email for folder name
    if email:
        safe_email = email.replace('@', '_at_').replace('.', '_dot_')
        safe_email = re.sub(r'[<>:"/\\|?*]', '_', safe_email)
        print(f"📧 Email: {email} -> {safe_email}")
    else:
        safe_email = "no_email"
        print(f"⚠️ ID:{inv_id} has no email address - using 'no_email' in folder name")
    
    # Create target paths with email format
    folder_name = f"MetaTrader 5 {safe_email} {investor_id_value} {broker}"
    target_folder = os.path.join(MT5_DESTINATION_PATH, folder_name)
    target_exe = os.path.join(target_folder, "terminal64.exe")
    normalized_path = target_exe.replace('\\', '\\')
    
    folder_exists = os.path.exists(target_folder)
    current_status = investor_data.get('application_status', '')
    
    # RULE 2: If folder exists and user is NOT suspended
    if folder_exists:
        print(f"✓ Folder exists: {folder_name}")
        current_path = investor_data.get('Terminal_path', '')
        
        # Ensure Terminal_path is set correctly
        if not current_path or current_path != normalized_path:
            investor_data['Terminal_path'] = normalized_path
            result['message'] = "Terminal_path updated"
            print(f"   🔧 Terminal_path updated")
        else:
            result['message'] = "Terminal_path verified"
            print(f"   ✓ Terminal_path verified")
        
        # Check application_status: only change if it is exactly "pending"
        if current_status == "pending":
            investor_data['application_status'] = 'just-joined'
            result['message'] += " | Status: pending → just-joined"
            print(f"   🔄 Status: pending → just-joined")
        else:
            print(f"   ℹ️ Status: {current_status} (unchanged)")
        
        investor_data['mt5_folder_name'] = folder_name
        result['success'] = True
        result['created'] = False
        result['updated_data'] = {inv_id_str: investor_data}
        
        # Save individual result to temp file
        temp_result_file = os.path.join(tempfile.gettempdir(), f"create_result_{inv_id}.json")
        with open(temp_result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2)
        
        return result
    
    # RULE 3: If folder is missing -> Create it
    print(f"🆕 Creating new folder: {folder_name}")
    print(f"   Email: {email}")
    print(f"   Broker: {broker}")
    print(f"   ID: {investor_id_value}")
    
    try:
        # Copy default files
        print(f"   📁 Copying from {DEFAULT_MT5_PATH}...")
        shutil.copytree(DEFAULT_MT5_PATH, target_folder, 
                        ignore_dangling_symlinks=True,
                        ignore=shutil.ignore_patterns('*.lock', '*.log'))
        
        # Assign structural data
        investor_data['Terminal_path'] = normalized_path
        investor_data['mt5_folder_name'] = folder_name
        
        # Handle application status condition
        if current_status == "pending":
            investor_data['application_status'] = 'just-joined'
            result['message'] = "Folder created | Status: pending → just-joined"
            print(f"   🔄 Status: pending → just-joined")
        else:
            result['message'] = f"Folder created | Status kept: {current_status}"
            print(f"   ℹ️ Status kept as: {current_status}")
        
        result['success'] = True
        result['created'] = True
        result['updated_data'] = {inv_id_str: investor_data}
        
        print(f"   ✅ Folder created successfully!")
        print(f"   📍 Path: {normalized_path[:100]}...")
        
        # Save individual result to temp file
        temp_result_file = os.path.join(tempfile.gettempdir(), f"create_result_{inv_id}.json")
        with open(temp_result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2)
        
        return result
        
    except Exception as e:
        msg = f"Failed to copy folder: {str(e)[:200]}"
        print(f"    {msg}")
        result['message'] = msg
        
        # Clean up partial folder if it exists
        if os.path.exists(target_folder):
            try:
                shutil.rmtree(target_folder, ignore_errors=True)
                print(f"   🧹 Cleaned up partial folder")
            except:
                pass
        
        return result

def merge_create_results():
    """
    Merge all individual MT5 folder creation results from temp files back to the main JSON file.
    Call this after all multiprocessing tasks are complete.
    
    Returns:
        dict: {
            'total_processed': int,
            'created': int,
            'deleted': int,
            'updated': int,
            'errors': int
        }
    """
    import os
    import json
    import tempfile
    import shutil
    import glob
    
    print(f"\n{'='*60}")
    print(f"📦 MERGING MT5 FOLDER CREATION RESULTS")
    print(f"{'='*60}")
    
    # Load current investors data
    if not os.path.exists(FETCHED_INVESTORS):
        print(f" Fetched investors file not found")
        return {'total_processed': 0, 'created': 0, 'deleted': 0, 'updated': 0, 'errors': 0}
    
    try:
        with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
            investors_data = json.load(f)
        print(f"📋 Loaded current investors data")
    except Exception as e:
        print(f" Error loading investors: {e}")
        return {'total_processed': 0, 'created': 0, 'deleted': 0, 'updated': 0, 'errors': 0}
    
    # Find all temp result files
    temp_dir = tempfile.gettempdir()
    result_files = glob.glob(os.path.join(temp_dir, "create_result_*.json"))
    
    stats = {
        'total_processed': len(result_files),
        'created': 0,
        'deleted': 0,
        'updated': 0,
        'errors': 0
    }
    
    print(f"\n📁 Found {len(result_files)} result files to merge")
    
    for result_file in result_files:
        try:
            with open(result_file, 'r', encoding='utf-8') as f:
                result = json.load(f)
            
            if result.get('success') and result.get('updated_data'):
                investor_id = result['investor_id']
                updated_data = result['updated_data']
                
                if investor_id in updated_data and investor_id in investors_data:
                    # Track statistics
                    if result.get('created'):
                        stats['created'] += 1
                    if result.get('deleted'):
                        stats['deleted'] += 1
                    if not result.get('created') and not result.get('deleted'):
                        stats['updated'] += 1
                    
                    # Update the main data
                    old_data = investors_data[investor_id]
                    new_data = updated_data[investor_id]
                    
                    # Merge only specific fields (preserve other data)
                    for key, value in new_data.items():
                        if value != old_data.get(key):
                            investors_data[investor_id][key] = value
                    
                    print(f"✅ Merged update for investor {investor_id}: {result.get('message', '')[:60]}")
            else:
                stats['errors'] += 1
                print(f"⚠️ Failed result for investor {result.get('investor_id', 'unknown')}: {result.get('message', 'No message')}")
            
            # Delete temp file after processing
            os.remove(result_file)
            
        except Exception as e:
            stats['errors'] += 1
            print(f"⚠️ Error processing {result_file}: {e}")
    
    # Save merged data if there were changes
    if stats['total_processed'] > 0 and stats['errors'] < stats['total_processed']:
        # Create backup
        backup_path = FETCHED_INVESTORS.replace('.json', '_backup.json')
        if not os.path.exists(backup_path):
            shutil.copy2(FETCHED_INVESTORS, backup_path)
            print(f"\n📦 Created backup: {backup_path}")
        
        with open(FETCHED_INVESTORS, 'w', encoding='utf-8') as f:
            json.dump(investors_data, f, indent=2)
        
        print(f"\n💾 Saved merged data to {FETCHED_INVESTORS}")
    else:
        print(f"\n⚠️ No valid updates to save")
    
    # Print summary
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
    Get account balance for investors by initializing MT5 and logging in.
    
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
    if not os.path.exists(FETCHED_INVESTORS):
        msg = f"Fetched investors file not found: {FETCHED_INVESTORS}"
        print(msg)
        result['message'] = msg
        return result
    
    # Load investors data (read-only, no lock needed for reading)
    try:
        with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
            investors_data = json.load(f)
        print(f"📋 Loaded investors data")
    except Exception as e:
        print(f"Error loading investors: {e}")
        result['message'] = f"Error loading investors: {e}"
        return result
    
    inv_id_str = str(inv_id)
    if inv_id_str not in investors_data:
        msg = f"Investor {inv_id} not found in data"
        print(msg)
        result['message'] = msg
        return result
    
    investor_data = investors_data[inv_id_str].copy()  # Work on a copy
    app_status = investor_data.get('application_status', '').strip()
    
    # STRICT SKIP - Only proceed if status is EXACTLY 'just-joined'
    if app_status != 'just-joined':
        print(f"⏭️ ID:{inv_id} → Status: '{app_status}' (not 'just-joined') - SKIPPING")
        result['message'] = f"Status is '{app_status}', not 'just-joined'"
        return result
    
    # ACCOUNT MODE AND DEMO PERMISSION CHECK
    account_mode = investor_data.get('account_mode', '').strip().lower()
    demo_account = investor_data.get('demo_account', '').strip()
    
    if account_mode == 'demo':
        if demo_account == '0':
            print(f"⏭️ ID:{inv_id} → DEMO account but demo_account=0 (DISABLED) - Skipping")
            result['message'] = "DEMO account disabled (demo_account=0)"
            return result
        elif demo_account == '1':
            print(f"✅ ID:{inv_id} → DEMO account with demo_account=1 (ENABLED) - Proceeding")
        else:
            print(f"⚠️ ID:{inv_id} → DEMO account but demo_account not set to '1' - Skipping")
            result['message'] = f"DEMO account but demo_account not set to '1'"
            return result
    elif account_mode == 'real':
        print(f"✅ ID:{inv_id} → REAL account - Proceeding")
    
    # Extract credentials
    login_id = investor_data.get('login', '') or investor_data.get('LOGIN_ID', '')
    password = investor_data.get('password', '') or investor_data.get('PASSWORD', '')
    server = investor_data.get('server', '') or investor_data.get('SERVER', '')
    Terminal_path = investor_data.get('Terminal_path', '')
    email = investor_data.get('email', 'No Email')
    
    if not all([login_id, password, server, Terminal_path]):
        print(f" ID:{inv_id} ({email}) → Missing credentials")
        result['message'] = "Missing credentials"
        return result
    
    try:
        login_id_int = int(login_id)
    except (ValueError, TypeError):
        print(f" ID:{inv_id} ({email}) → Invalid LOGIN_ID: {login_id}")
        result['message'] = f"Invalid LOGIN_ID: {login_id}"
        return result
    
    if not os.path.exists(Terminal_path):
        print(f"ID:{inv_id} ({email}) → Terminal not found at: {Terminal_path}")
        result['message'] = f"Terminal not found: {Terminal_path}"
        return result
    
    print(f"\n ID:{inv_id} ({email}) (Login:{login_id_int}) - Processing...")
    
    # Check MT5 status and login
    already_logged_in_account = None
    actual_account_mode = None
    balance = None
    currency = None
    success = False
    
    try:
        # Try to initialize without path first
        if mt5.initialize():
            account_info = mt5.account_info()
            if account_info is not None:
                already_logged_in_account = account_info.login
                
                if account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL:
                    actual_account_mode = 'real'
                elif account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO:
                    actual_account_mode = 'demo'
                elif account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_CONTEST:
                    actual_account_mode = 'demo'
                else:
                    actual_account_mode = 'unknown'
                
                if account_info.login == login_id_int:
                    print(f"    ALREADY LOGGED IN: {login_id_int} ({email})")
                    print(f"      → Account type: {actual_account_mode.upper()}")
                    
                    if actual_account_mode == 'demo':
                        if demo_account == '0':
                            print(f"      → SKIPPING: DEMO account disabled")
                            mt5.shutdown()
                            result['message'] = "DEMO account disabled"
                            return result
                        elif demo_account != '1':
                            print(f"      → SKIPPING: DEMO account not enabled")
                            mt5.shutdown()
                            result['message'] = "DEMO account not enabled"
                            return result
                    
                    balance = account_info.balance
                    currency = account_info.currency
                    
                    balance_str = f"{balance:.2f}"
                    
                    # Update the copy
                    investor_data['broker_balance'] = balance_str
                    investor_data['application_status'] = 'just-joined-and-valid_credentials'
                    
                    if investor_data.get('account_mode', '').strip().lower() != actual_account_mode:
                        investor_data['account_mode'] = actual_account_mode
                    
                    success = True
                    result['success'] = True
                    result['status'] = 'just-joined-and-valid_credentials'
                    result['balance'] = balance
                    result['message'] = f"Already logged in. Balance: {currency} {balance:,.2f}"
                    result['updated_data'] = {inv_id_str: investor_data}
                    
                    mt5.shutdown()
                    print(f"    ✅ Balance obtained: {currency} {balance:,.2f}")
                    
                    # Save individual result to temp file
                    temp_result_file = os.path.join(tempfile.gettempdir(), f"balance_result_{inv_id}.json")
                    with open(temp_result_file, 'w', encoding='utf-8') as f:
                        json.dump(result, f, indent=2)
                    
                    return result
            mt5.shutdown()
    except Exception as e:
        print(f"    Could not check MT5 status: {e}")
    
    # Fresh login attempt
    if not success:
        print(f"   🔐 FRESH LOGIN: {login_id_int} ({email})")
        
        try:
            if mt5.terminal_info() is not None:
                mt5.shutdown()
            
            if not mt5.initialize(path=Terminal_path, timeout=60000):
                error_msg = mt5.last_error()
                print(f"   INITIALIZATION FAILED: {error_msg}")
                result['message'] = f"MT5 initialization failed: {error_msg}"
                return result
            
            if not mt5.login(login_id_int, password=password, server=server):
                error_msg = mt5.last_error()
                print(f"   LOGIN FAILED: {error_msg}")
                mt5.shutdown()
                result['message'] = f"Login failed: {error_msg}"
                return result
            
            print(f"    FRESH LOGIN SUCCESS: {login_id_int} ({email})")
            
            account_info = mt5.account_info()
            if account_info is None:
                print(f"   No account info after login")
                mt5.shutdown()
                result['message'] = "No account info after login"
                return result
            
            if account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL:
                actual_account_mode = 'real'
            elif account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO:
                actual_account_mode = 'demo'
            elif account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_CONTEST:
                actual_account_mode = 'demo'
            else:
                actual_account_mode = 'unknown'
            
            print(f"      → Account type: {actual_account_mode.upper()}")
            
            if actual_account_mode == 'demo':
                if demo_account == '0':
                    print(f"      → SKIPPING: DEMO account disabled")
                    mt5.shutdown()
                    result['message'] = "DEMO account disabled"
                    return result
                elif demo_account != '1':
                    print(f"      → SKIPPING: DEMO account not enabled")
                    mt5.shutdown()
                    result['message'] = "DEMO account not enabled"
                    return result
            
            balance = account_info.balance
            currency = account_info.currency
            
            balance_str = f"{balance:.2f}"
            investor_data['broker_balance'] = balance_str
            investor_data['application_status'] = 'just-joined-and-valid_credentials'
            
            if investor_data.get('account_mode', '').strip().lower() != actual_account_mode:
                investor_data['account_mode'] = actual_account_mode
            
            result['success'] = True
            result['status'] = 'just-joined-and-valid_credentials'
            result['balance'] = balance
            result['message'] = f"Fresh login successful. Balance: {currency} {balance:,.2f}"
            result['updated_data'] = {inv_id_str: investor_data}
            
            mt5.shutdown()
            print(f"    ✅ Balance obtained: {currency} {balance:,.2f}")
            
            # Save individual result to temp file
            temp_result_file = os.path.join(tempfile.gettempdir(), f"balance_result_{inv_id}.json")
            with open(temp_result_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2)
            
            return result
            
        except Exception as e:
            print(f"   ERROR: {str(e)[:100]}")
            result['message'] = f"Error: {str(e)[:100]}"
            try:
                mt5.shutdown()
            except:
                pass
            return result
    
    return result

def merge_balance_results():
    """
    Merge all individual balance results from temp files back to the main JSON file.
    Call this after all multiprocessing tasks are complete.
    """
    import os
    import json
    import tempfile
    import shutil
    
    print(f"\n{'='*60}")
    print(f"📦 MERGING BALANCE RESULTS")
    print(f"{'='*60}")
    
    # Load current investors data
    if not os.path.exists(FETCHED_INVESTORS):
        print(f" Fetched investors file not found")
        return False
    
    try:
        with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
            investors_data = json.load(f)
    except Exception as e:
        print(f" Error loading investors: {e}")
        return False
    
    # Find all temp result files
    temp_dir = tempfile.gettempdir()
    import glob
    result_files = glob.glob(os.path.join(temp_dir, "balance_result_*.json"))
    
    updated_count = 0
    errors = 0
    
    for result_file in result_files:
        try:
            with open(result_file, 'r', encoding='utf-8') as f:
                result = json.load(f)
            
            if result.get('success') and result.get('updated_data'):
                investor_id = result['investor_id']
                updated_data = result['updated_data']
                
                if investor_id in updated_data:
                    # Update the main data
                    investors_data[investor_id] = updated_data[investor_id]
                    updated_count += 1
                    print(f"✅ Merged update for investor {investor_id}: {result.get('message', '')[:50]}")
            
            # Delete temp file after processing
            os.remove(result_file)
            
        except Exception as e:
            print(f"⚠️ Error processing {result_file}: {e}")
            errors += 1
    
    # Save merged data
    if updated_count > 0:
        # Create backup
        backup_path = FETCHED_INVESTORS.replace('.json', '_backup.json')
        if not os.path.exists(backup_path):
            shutil.copy2(FETCHED_INVESTORS, backup_path)
            print(f"📦 Created backup: {backup_path}")
        
        with open(FETCHED_INVESTORS, 'w', encoding='utf-8') as f:
            json.dump(investors_data, f, indent=2)
        
        print(f"\n💾 Saved {updated_count} updates to {FETCHED_INVESTORS}")
        
        # Also update updated_investors.json with valid credentials
        updated_investors_data = {}
        for investor_id, investor_data in investors_data.items():
            app_status = investor_data.get('application_status', '').strip().lower()
            if app_status == 'just-joined-and-valid_credentials':
                updated_investors_data[investor_id] = investor_data
        
        if updated_investors_data:
            with open(UPDATED_INVESTORS, 'w', encoding='utf-8') as f:
                json.dump(updated_investors_data, f, indent=2)
            print(f"💾 Updated {len(updated_investors_data)} investors to {UPDATED_INVESTORS}")
        
        print(f"\n📊 Merge Summary:")
        print(f"   ✅ Updated: {updated_count}")
        print(f"   ⚠️ Errors: {errors}")
        return True
    else:
        print(f"ℹ️ No updates to merge")
        return False

def verify_investors_balance_old(inv_id=None):
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
    
    if not os.path.exists(FETCHED_INVESTORS):
        msg = f"Fetched investors file not found: {FETCHED_INVESTORS}"
        print(msg)
        result['message'] = msg
        return result
    
    # Load investors data (read-only)
    try:
        with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
            investors_data = json.load(f)
        print(f"📋 Loaded investors data")
    except Exception as e:
        print(f"Error loading investors: {e}")
        result['message'] = f"Error loading investors: {e}"
        return result
    
    inv_id_str = str(inv_id)
    if inv_id_str not in investors_data:
        msg = f"Investor {inv_id} not found"
        print(msg)
        result['message'] = msg
        return result
    
    investor_data = investors_data[inv_id_str].copy()
    balance_verification_status = investor_data.get('balance_verification', '').strip().lower()
    
    verification_statuses = ['applied-for-verification', 'applied_for_verification']
    if balance_verification_status not in verification_statuses:
        result['message'] = f"Not applied for verification (status: {balance_verification_status})"
        return result
    
    account_mode = investor_data.get('account_mode', '').strip().lower()
    demo_account = investor_data.get('demo_account', '').strip()
    
    if account_mode == 'demo':
        if demo_account == '0':
            result['message'] = "DEMO account disabled (demo_account=0)"
            return result
        elif demo_account != '1':
            result['message'] = "DEMO account not enabled"
            return result
    
    login_id = investor_data.get('login', '') or investor_data.get('LOGIN_ID', '')
    password = investor_data.get('password', '') or investor_data.get('PASSWORD', '')
    server = investor_data.get('server', '') or investor_data.get('SERVER', '')
    Terminal_path = investor_data.get('Terminal_path', '')
    email = investor_data.get('email', 'No Email')
    
    if not all([login_id, password, server, Terminal_path]):
        result['message'] = "Missing credentials"
        return result
    
    try:
        login_id_int = int(login_id)
    except (ValueError, TypeError):
        result['message'] = f"Invalid LOGIN_ID: {login_id}"
        return result
    
    if not os.path.exists(Terminal_path):
        result['message'] = f"Terminal not found: {Terminal_path}"
        return result
    
    print(f"\n✅ ID:{inv_id} ({email}) - Verifying...")
    
    try:
        # Try already logged in first
        if mt5.initialize():
            account_info = mt5.account_info()
            if account_info and account_info.login == login_id_int:
                balance = account_info.balance
                currency = account_info.currency
                
                investor_data['broker_balance'] = f"{balance:.2f}"
                investor_data['balance_verification'] = 'verified'
                
                result['success'] = True
                result['status'] = 'verified'
                result['balance'] = balance
                result['message'] = f"Verified (already logged in): {currency} {balance:,.2f}"
                result['updated_data'] = {inv_id_str: investor_data}
                
                mt5.shutdown()
                print(f"    ✅ Verified: {currency} {balance:,.2f}")
                
                # Save individual result to temp file
                temp_result_file = os.path.join(tempfile.gettempdir(), f"verify_result_{inv_id}.json")
                with open(temp_result_file, 'w', encoding='utf-8') as f:
                    json.dump(result, f, indent=2)
                
                return result
            mt5.shutdown()
        
        # Fresh login
        if mt5.terminal_info() is not None:
            mt5.shutdown()
        
        if mt5.initialize(path=Terminal_path, timeout=60000):
            if mt5.login(login_id_int, password=password, server=server):
                account_info = mt5.account_info()
                if account_info:
                    balance = account_info.balance
                    currency = account_info.currency
                    
                    investor_data['broker_balance'] = f"{balance:.2f}"
                    investor_data['balance_verification'] = 'verified'
                    
                    result['success'] = True
                    result['status'] = 'verified'
                    result['balance'] = balance
                    result['message'] = f"Verified (fresh login): {currency} {balance:,.2f}"
                    result['updated_data'] = {inv_id_str: investor_data}
                    
                    mt5.shutdown()
                    print(f"    ✅ Verified: {currency} {balance:,.2f}")
                    
                    # Save individual result to temp file
                    temp_result_file = os.path.join(tempfile.gettempdir(), f"verify_result_{inv_id}.json")
                    with open(temp_result_file, 'w', encoding='utf-8') as f:
                        json.dump(result, f, indent=2)
                    
                    return result
            mt5.shutdown()
            
    except Exception as e:
        print(f"    Error: {str(e)[:100]}")
        result['message'] = f"Error: {str(e)[:100]}"
        try:
            mt5.shutdown()
        except:
            pass
    
    return result
  
def merge_verify_results():
    """
    Merge all individual verification results from temp files back to the main JSON file.
    Call this after all multiprocessing tasks are complete.
    """
    import os
    import json
    import tempfile
    import shutil
    import glob
    
    print(f"\n{'='*60}")
    print(f"📦 MERGING VERIFICATION RESULTS")
    print(f"{'='*60}")
    
    if not os.path.exists(FETCHED_INVESTORS):
        print(f" Fetched investors file not found")
        return False
    
    try:
        with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
            investors_data = json.load(f)
    except Exception as e:
        print(f" Error loading investors: {e}")
        return False
    
    temp_dir = tempfile.gettempdir()
    result_files = glob.glob(os.path.join(temp_dir, "verify_result_*.json"))
    
    updated_count = 0
    errors = 0
    
    for result_file in result_files:
        try:
            with open(result_file, 'r', encoding='utf-8') as f:
                result = json.load(f)
            
            if result.get('success') and result.get('updated_data'):
                investor_id = result['investor_id']
                updated_data = result['updated_data']
                
                if investor_id in updated_data:
                    investors_data[investor_id] = updated_data[investor_id]
                    updated_count += 1
                    print(f"✅ Merged verification for investor {investor_id}: {result.get('message', '')[:50]}")
            
            os.remove(result_file)
            
        except Exception as e:
            print(f"⚠️ Error processing {result_file}: {e}")
            errors += 1
    
    if updated_count > 0:
        backup_path = FETCHED_INVESTORS.replace('.json', '_backup.json')
        if not os.path.exists(backup_path):
            shutil.copy2(FETCHED_INVESTORS, backup_path)
            print(f"📦 Created backup: {backup_path}")
        
        with open(FETCHED_INVESTORS, 'w', encoding='utf-8') as f:
            json.dump(investors_data, f, indent=2)
        
        print(f"\n💾 Saved {updated_count} verification updates to {FETCHED_INVESTORS}")
        
        # Update updated_investors.json with verified investors
        updated_investors_data = {}
        for investor_id, investor_data in investors_data.items():
            verification_status = investor_data.get('balance_verification', '').strip().lower()
            if verification_status == 'verified':
                updated_investors_data[investor_id] = investor_data
        
        if updated_investors_data:
            with open(UPDATED_INVESTORS, 'w', encoding='utf-8') as f:
                json.dump(updated_investors_data, f, indent=2)
            print(f"💾 Updated {len(updated_investors_data)} verified investors to {UPDATED_INVESTORS}")
        
        print(f"\n📊 Merge Summary:")
        print(f"   ✅ Verified: {updated_count}")
        print(f"   ⚠️ Errors: {errors}")
        return True
    else:
        print(f"ℹ️ No verification updates to merge")
        return False

def verify_investors_balance():
    """
    Verify balance for investors who have applied for verification.
    Processes all investors in the FETCHED_INVESTORS file and updates their balance status.
    
    Returns:
        dict: {
            'success': bool,
            'status': str,
            'message': str,
            'verified_count': int,
            'error_count': int,
            'skipped_count': int,
            'updated_data': dict
        }
    """
    
    import os
    import json
    import tempfile
    import shutil
    import MetaTrader5 as mt5
    from datetime import datetime
    
    result = {
        'success': False,
        'status': 'not_processed',
        'message': '',
        'verified_count': 0,
        'error_count': 0,
        'skipped_count': 0,
        'updated_data': {}
    }
    
    # ============ STEP 1: LOAD INVESTORS DATA ============
    if not os.path.exists(FETCHED_INVESTORS):
        msg = f"Fetched investors file not found: {FETCHED_INVESTORS}"
        print(f"❌ {msg}")
        result['message'] = msg
        return result
    
    try:
        with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
            investors_data = json.load(f)
        print(f"📋 Loaded investors data - Total: {len(investors_data)} investors")
    except Exception as e:
        msg = f"Error loading investors: {e}"
        print(f"❌ {msg}")
        result['message'] = msg
        return result
    
    # ============ STEP 2: PROCESS EACH INVESTOR ============
    print(f"\n{'='*60}")
    print(f"🔐 BALANCE VERIFICATION - Processing all investors")
    print(f"{'='*60}")
    
    verified_count = 0
    error_count = 0
    skipped_count = 0
    processed_results = {}
    
    for inv_id_str, investor_data in investors_data.items():
        inv_result = {
            'investor_id': inv_id_str,
            'success': False,
            'status': 'not_processed',
            'balance': None,
            'message': '',
            'updated_data': None
        }
        
        # Check if investor has applied for verification
        balance_verification_status = investor_data.get('balance_verification', '').strip().lower()
        verification_statuses = ['applied-for-verification', 'applied_for_verification']
        
        if balance_verification_status not in verification_statuses:
            inv_result['message'] = f"Not applied for verification (status: {balance_verification_status})"
            inv_result['status'] = 'skipped'
            processed_results[inv_id_str] = inv_result
            skipped_count += 1
            continue
        
        # Check demo account status
        account_mode = investor_data.get('account_mode', '').strip().lower()
        demo_account = investor_data.get('demo_account', '').strip()
        
        if account_mode == 'demo':
            if demo_account == '0':
                inv_result['message'] = "DEMO account disabled (demo_account=0)"
                inv_result['status'] = 'skipped'
                processed_results[inv_id_str] = inv_result
                skipped_count += 1
                continue
            elif demo_account != '1':
                inv_result['message'] = "DEMO account not enabled"
                inv_result['status'] = 'skipped'
                processed_results[inv_id_str] = inv_result
                skipped_count += 1
                continue
        
        # Get credentials
        login_id = investor_data.get('login', '') or investor_data.get('LOGIN_ID', '')
        password = investor_data.get('password', '') or investor_data.get('PASSWORD', '')
        server = investor_data.get('server', '') or investor_data.get('SERVER', '')
        Terminal_path = investor_data.get('Terminal_path', '')
        email = investor_data.get('email', 'No Email')
        
        if not all([login_id, password, server, Terminal_path]):
            inv_result['message'] = "Missing credentials"
            inv_result['status'] = 'error'
            processed_results[inv_id_str] = inv_result
            error_count += 1
            continue
        
        try:
            login_id_int = int(login_id)
        except (ValueError, TypeError):
            inv_result['message'] = f"Invalid LOGIN_ID: {login_id}"
            inv_result['status'] = 'error'
            processed_results[inv_id_str] = inv_result
            error_count += 1
            continue
        
        if not os.path.exists(Terminal_path):
            inv_result['message'] = f"Terminal not found: {Terminal_path}"
            inv_result['status'] = 'error'
            processed_results[inv_id_str] = inv_result
            error_count += 1
            continue
        
        print(f"\n✅ ID:{inv_id_str} ({email}) - Verifying...")
        
        try:
            # Try already logged in first
            if mt5.initialize():
                account_info = mt5.account_info()
                if account_info and account_info.login == login_id_int:
                    balance = account_info.balance
                    currency = account_info.currency
                    
                    investor_data['broker_balance'] = f"{balance:.2f}"
                    investor_data['balance_verification'] = 'verified'
                    investor_data['verified_at'] = datetime.now().isoformat()
                    
                    inv_result['success'] = True
                    inv_result['status'] = 'verified'
                    inv_result['balance'] = balance
                    inv_result['message'] = f"Verified (already logged in): {currency} {balance:,.2f}"
                    inv_result['updated_data'] = {inv_id_str: investor_data}
                    
                    mt5.shutdown()
                    print(f"    ✅ Verified: {currency} {balance:,.2f}")
                    
                    processed_results[inv_id_str] = inv_result
                    verified_count += 1
                    continue
                mt5.shutdown()
            
            # Fresh login
            if mt5.terminal_info() is not None:
                mt5.shutdown()
            
            if mt5.initialize(path=Terminal_path, timeout=60000):
                if mt5.login(login_id_int, password=password, server=server):
                    account_info = mt5.account_info()
                    if account_info:
                        balance = account_info.balance
                        currency = account_info.currency
                        
                        investor_data['broker_balance'] = f"{balance:.2f}"
                        investor_data['balance_verification'] = 'verified'
                        investor_data['verified_at'] = datetime.now().isoformat()
                        
                        inv_result['success'] = True
                        inv_result['status'] = 'verified'
                        inv_result['balance'] = balance
                        inv_result['message'] = f"Verified (fresh login): {currency} {balance:,.2f}"
                        inv_result['updated_data'] = {inv_id_str: investor_data}
                        
                        mt5.shutdown()
                        print(f"    ✅ Verified: {currency} {balance:,.2f}")
                        
                        processed_results[inv_id_str] = inv_result
                        verified_count += 1
                        continue
                mt5.shutdown()
                
        except Exception as e:
            print(f"    ❌ Error: {str(e)[:100]}")
            inv_result['message'] = f"Error: {str(e)[:100]}"
            inv_result['status'] = 'error'
            processed_results[inv_id_str] = inv_result
            error_count += 1
            try:
                mt5.shutdown()
            except:
                pass
            continue
        
        # If we get here, something went wrong
        if inv_result['status'] == 'not_processed':
            inv_result['message'] = "Failed to verify balance"
            inv_result['status'] = 'error'
            processed_results[inv_id_str] = inv_result
            error_count += 1
    
    # ============ STEP 3: SAVE TO TEMP FILE ============
    temp_result_file = os.path.join(tempfile.gettempdir(), f"verify_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(temp_result_file, 'w', encoding='utf-8') as f:
        json.dump(processed_results, f, indent=2)
    print(f"\n💾 Results saved to: {temp_result_file}")
    
    # ============ STEP 4: MERGE UPDATES BACK TO MAIN FILE ============
    print(f"\n{'='*60}")
    print(f"📦 MERGING VERIFICATION RESULTS")
    print(f"{'='*60}")
    
    try:
        # Reload the current data (in case it was modified during processing)
        with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
            current_data = json.load(f)
        
        # Create backup before merging
        
        # Merge verified results
        merge_count = 0
        for inv_id, result_data in processed_results.items():
            if result_data.get('success') and result_data.get('updated_data'):
                if inv_id in result_data['updated_data']:
                    current_data[inv_id] = result_data['updated_data'][inv_id]
                    merge_count += 1
        
        # Save merged data back to main file
        with open(FETCHED_INVESTORS, 'w', encoding='utf-8') as f:
            json.dump(current_data, f, indent=2)
        
        print(f"💾 Merged {merge_count} verification updates to {FETCHED_INVESTORS}")
        
        # ============ STEP 5: UPDATE VERIFIED INVESTORS FILE ============
        updated_investors_data = {}
        for investor_id, investor_data in current_data.items():
            verification_status = investor_data.get('balance_verification', '').strip().lower()
            if verification_status == 'verified':
                updated_investors_data[investor_id] = investor_data
        
        if updated_investors_data:
            
            with open(UPDATED_INVESTORS, 'w', encoding='utf-8') as f:
                json.dump(updated_investors_data, f, indent=2)
            print(f"💾 Updated {len(updated_investors_data)} verified investors to {UPDATED_INVESTORS}")
        
        # ============ STEP 6: SUMMARY ============
        print(f"\n{'='*60}")
        print(f"📊 VERIFICATION SUMMARY")
        print(f"{'='*60}")
        print(f"✅ Verified: {verified_count}")
        print(f"❌ Errors: {error_count}")
        print(f"⏭️  Skipped: {skipped_count}")
        print(f"📁 Results saved to: {temp_result_file}")
        print(f"💾 Main file updated: {FETCHED_INVESTORS}")
        print(f"{'='*60}\n")
        
        # Final result
        result = {
            'success': verified_count > 0,
            'status': 'completed',
            'message': f"Processed {len(processed_results)} investors: {verified_count} verified, {error_count} errors, {skipped_count} skipped",
            'verified_count': verified_count,
            'error_count': error_count,
            'skipped_count': skipped_count,
            'updated_data': processed_results
        }
        
        return result
        
    except Exception as e:
        msg = f"Error during merge: {e}"
        print(f"❌ {msg}")
        result['message'] = msg
        result['verified_count'] = verified_count
        result['error_count'] = error_count
        result['skipped_count'] = skipped_count
        result['updated_data'] = processed_results
        return result
       
def combine_investors_to_all_files():
    """
    Combines investor data from invharv and harvhub into single all-in-one files.
    
    Reads:
        - INVHARV_FETCHED_INVESTORS
        - HARVHUB_FETCHED_INVESTORS
        - INVHARV_UPDATED_INVESTORS
        - HARVHUB_UPDATED_INVESTORS
    
    Writes:
        - ALL_FETCHED_INVESTORS (combined fetched data from both sources)
        - ALL_UPDATED_INVESTORS (combined updated data from both sources)
    
    Returns:
        dict: Statistics about the combination process
    """
    print("\n" + "="*70)
    print(f"  COMBINING INVESTOR FILES")
    print("="*70)
    print(f"  Start Time  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-"*70)
    
    stats = {
        "processing_success": False,
        "fetched": {
            "invharv": {"loaded": False, "count": 0, "path": INVHARV_FETCHED_INVESTORS},
            "harvhub": {"loaded": False, "count": 0, "path": HARVHUB_FETCHED_INVESTORS},
            "combined_count": 0,
            "output_path": ALL_FETCHED_INVESTORS
        },
        "updated": {
            "invharv": {"loaded": False, "count": 0, "path": INVHARV_UPDATED_INVESTORS},
            "harvhub": {"loaded": False, "count": 0, "path": HARVHUB_UPDATED_INVESTORS},
            "combined_count": 0,
            "output_path": ALL_UPDATED_INVESTORS
        },
        "errors": [],
        "timestamp": datetime.now().isoformat()
    }
    
    try:
        # ============================================================
        # 1. COMBINE FETCHED INVESTORS
        # ============================================================
        print("\n📥 [1/2] Combining FETCHED investors...")
        print("-"*40)
        
        combined_fetched = {}
        
        # Load INVHARV fetched
        if os.path.exists(INVHARV_FETCHED_INVESTORS):
            try:
                with open(INVHARV_FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        combined_fetched.update(data)
                        stats["fetched"]["invharv"]["loaded"] = True
                        stats["fetched"]["invharv"]["count"] = len(data)
                        print(f"   ✅ Loaded INVHARV fetched: {len(data):,} records")
                    else:
                        print(f"   ⚠️ INVHARV fetched has invalid format (expected dict)")
                        stats["errors"].append("INVHARV fetched file is not a dict")
            except Exception as e:
                error_msg = f"Error loading INVHARV fetched: {str(e)}"
                print(f"   ❌ {error_msg}")
                stats["errors"].append(error_msg)
        else:
            print(f"   ⚠️ INVHARV fetched file not found: {INVHARV_FETCHED_INVESTORS}")
            stats["errors"].append("INVHARV fetched file not found")
        
        # Load HARVHUB fetched
        if os.path.exists(HARVHUB_FETCHED_INVESTORS):
            try:
                with open(HARVHUB_FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        # Merge without overwriting existing keys (invharv takes priority)
                        for key, value in data.items():
                            if key not in combined_fetched:
                                combined_fetched[key] = value
                        stats["fetched"]["harvhub"]["loaded"] = True
                        stats["fetched"]["harvhub"]["count"] = len(data)
                        print(f"   ✅ Loaded HARVHUB fetched: {len(data):,} records")
                    else:
                        print(f"   ⚠️ HARVHUB fetched has invalid format (expected dict)")
                        stats["errors"].append("HARVHUB fetched file is not a dict")
            except Exception as e:
                error_msg = f"Error loading HARVHUB fetched: {str(e)}"
                print(f"   ❌ {error_msg}")
                stats["errors"].append(error_msg)
        else:
            print(f"   ⚠️ HARVHUB fetched file not found: {HARVHUB_FETCHED_INVESTORS}")
            stats["errors"].append("HARVHUB fetched file not found")
        
        # Write combined fetched file
        if combined_fetched:
            stats["fetched"]["combined_count"] = len(combined_fetched)
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(ALL_FETCHED_INVESTORS), exist_ok=True)
            
            with open(ALL_FETCHED_INVESTORS, 'w', encoding='utf-8') as f:
                json.dump(combined_fetched, f, indent=2, ensure_ascii=False)
            
            print(f"\n   💾 Written combined fetched to: {ALL_FETCHED_INVESTORS}")
            print(f"   📊 Total combined fetched records: {len(combined_fetched):,}")
            
            # Show breakdown
            if stats["fetched"]["invharv"]["loaded"] and stats["fetched"]["harvhub"]["loaded"]:
                overlap = stats["fetched"]["invharv"]["count"] + stats["fetched"]["harvhub"]["count"] - len(combined_fetched)
                if overlap > 0:
                    print(f"   🔄 Overlapping records (invharv kept): {overlap:,}")
        else:
            print(f"\n   ⚠️ No fetched data to combine")
            stats["errors"].append("No fetched data available")
        
        # ============================================================
        # 2. COMBINE UPDATED INVESTORS
        # ============================================================
        print("\n📤 [2/2] Combining UPDATED investors...")
        print("-"*40)
        
        combined_updated = {}
        
        # Load INVHARV updated
        if os.path.exists(INVHARV_UPDATED_INVESTORS):
            try:
                with open(INVHARV_UPDATED_INVESTORS, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        combined_updated.update(data)
                        stats["updated"]["invharv"]["loaded"] = True
                        stats["updated"]["invharv"]["count"] = len(data)
                        print(f"   ✅ Loaded INVHARV updated: {len(data):,} records")
                    else:
                        print(f"   ⚠️ INVHARV updated has invalid format (expected dict)")
                        stats["errors"].append("INVHARV updated file is not a dict")
            except Exception as e:
                error_msg = f"Error loading INVHARV updated: {str(e)}"
                print(f"   ❌ {error_msg}")
                stats["errors"].append(error_msg)
        else:
            print(f"   ⚠️ INVHARV updated file not found: {INVHARV_UPDATED_INVESTORS}")
            stats["errors"].append("INVHARV updated file not found")
        
        # Load HARVHUB updated
        if os.path.exists(HARVHUB_UPDATED_INVESTORS):
            try:
                with open(HARVHUB_UPDATED_INVESTORS, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        # Merge without overwriting existing keys (invharv takes priority)
                        for key, value in data.items():
                            if key not in combined_updated:
                                combined_updated[key] = value
                        stats["updated"]["harvhub"]["loaded"] = True
                        stats["updated"]["harvhub"]["count"] = len(data)
                        print(f"   ✅ Loaded HARVHUB updated: {len(data):,} records")
                    else:
                        print(f"   ⚠️ HARVHUB updated has invalid format (expected dict)")
                        stats["errors"].append("HARVHUB updated file is not a dict")
            except Exception as e:
                error_msg = f"Error loading HARVHUB updated: {str(e)}"
                print(f"   ❌ {error_msg}")
                stats["errors"].append(error_msg)
        else:
            print(f"   ⚠️ HARVHUB updated file not found: {HARVHUB_UPDATED_INVESTORS}")
            stats["errors"].append("HARVHUB updated file not found")
        
        # Write combined updated file
        if combined_updated:
            stats["updated"]["combined_count"] = len(combined_updated)
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(ALL_UPDATED_INVESTORS), exist_ok=True)
            
            with open(ALL_UPDATED_INVESTORS, 'w', encoding='utf-8') as f:
                json.dump(combined_updated, f, indent=2, ensure_ascii=False)
            
            print(f"\n   💾 Written combined updated to: {ALL_UPDATED_INVESTORS}")
            print(f"   📊 Total combined updated records: {len(combined_updated):,}")
            
            # Show breakdown
            if stats["updated"]["invharv"]["loaded"] and stats["updated"]["harvhub"]["loaded"]:
                overlap = stats["updated"]["invharv"]["count"] + stats["updated"]["harvhub"]["count"] - len(combined_updated)
                if overlap > 0:
                    print(f"   🔄 Overlapping records (invharv kept): {overlap:,}")
        else:
            print(f"\n   ⚠️ No updated data to combine")
            stats["errors"].append("No updated data available")
        
        # ============================================================
        # 3. FINAL SUMMARY
        # ============================================================
        stats["processing_success"] = True
        
        print("\n" + "="*70)
        print(f"  COMBINATION SUMMARY")
        print("="*70)
        
        print(f"\n  📥 FETCHED FILES:")
        print(f"     INVHARV  : {'✅' if stats['fetched']['invharv']['loaded'] else '❌'} {stats['fetched']['invharv']['count']:,} records")
        print(f"     HARVHUB  : {'✅' if stats['fetched']['harvhub']['loaded'] else '❌'} {stats['fetched']['harvhub']['count']:,} records")
        print(f"     Combined : {stats['fetched']['combined_count']:,} records")
        print(f"     Output   : {ALL_FETCHED_INVESTORS}")
        
        print(f"\n  📤 UPDATED FILES:")
        print(f"     INVHARV  : {'✅' if stats['updated']['invharv']['loaded'] else '❌'} {stats['updated']['invharv']['count']:,} records")
        print(f"     HARVHUB  : {'✅' if stats['updated']['harvhub']['loaded'] else '❌'} {stats['updated']['harvhub']['count']:,} records")
        print(f"     Combined : {stats['updated']['combined_count']:,} records")
        print(f"     Output   : {ALL_UPDATED_INVESTORS}")
        
        if stats["errors"]:
            print(f"\n  ⚠️ ERRORS/WARNINGS ({len(stats['errors'])}):")
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
    
def process_single_investor_(inv_id):
    """
    WORKER FUNCTION: Only creates MT5 folders if they don't exist
    NO MT5 INITIALIZATION OR LOGIN
    Takes investor ID directly, not folder path
    
    Args:
        inv_id: Investor ID string
        
    Returns:
        dict: Statistics about the operation
    """
    
    account_stats = {
        "inv_id": inv_id, 
        "success": False,
        "folder_created": False,
        "folder_existed": False,
        "error": None
    }
    
    # Just call the folder creation function
    try:
        verify_investors_balance(inv_id=inv_id)
    except Exception as e:
        account_stats["error"] = str(e)
        print(f"Error for {inv_id}: {e}")
    
    return account_stats

def process_single_investor(inv_id):
    """
    WORKER FUNCTION: Processes investor data without MT5 initialization.
    Executes operations ONLY if within allowed time range.
    
    This function processes investors from the FETCHED_INVESTORS file.
    
    Args:
        inv_id: Investor ID string
        
    Returns:
        dict: Statistics about the operation
    """
    import os
    import time
    import json
    from pathlib import Path
    
    account_stats = {
        "inv_id": inv_id, 
        "success": False,
        "within_time_range": False,
        "execution_skipped": False,
        "error": None
    }
    
    # Check if we're allowed to work within current time range
    time_check_result = work_only_in_specific_timerange()
    
    if not time_check_result.get("should_work", False):
        print(f"⏰ Skipping operations for {inv_id} - outside allowed work time range")
        account_stats["execution_skipped"] = True
        account_stats["within_time_range"] = False
        account_stats["success"] = True
        return account_stats
    
    # Within time range - proceed with operations
    account_stats["within_time_range"] = True
    
    try:
        # ============ LOAD INVESTOR DATA FROM FETCHED_INVESTORS ============
        if not os.path.exists(FETCHED_INVESTORS):
            print(f"[ERROR] Fetched investors file not found: {FETCHED_INVESTORS}")
            account_stats["error"] = "Fetched investors file not found"
            return account_stats
        
        try:
            with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
                investors_data = json.load(f)
        except Exception as e:
            print(f"[ERROR] Could not load fetched investors: {e}")
            account_stats["error"] = f"Failed to load investors data: {e}"
            return account_stats
        
        # Get investor data from fetched investors
        investor_data = investors_data.get(inv_id)
        if not investor_data:
            print(f"[ERROR] Investor {inv_id} not found in fetched investors")
            account_stats["error"] = "Investor not found in fetched data"
            return account_stats
        
        # =====================================================================
        # EXECUTE OPERATIONS
        # =====================================================================
        print(f"🔄 Processing investor: {inv_id}")
        
        # Execute the operations only if within time range
        fetch_tables_streaming()
        #create_investor_mt5_files(inv_id=inv_id)
        #get_investors_balance(inv_id=inv_id)
        #verify_investors_balance(inv_id=inv_id)
        combine_investors_to_all_files()
        close_db_browser()
        initialize_browser(force_new=True)
        update_tables_streaming()
        
        account_stats["success"] = True
        print(f"✅ Successfully processed investor: {inv_id}")
        
    except Exception as e:
        account_stats["error"] = str(e)
        print(f"Error for {inv_id}: {e}")
        import traceback
        traceback.print_exc()
    
    return account_stats

def place_orders_parallel():
    """
    ORCHESTRATOR: Processes all investors from fetched_investors.json
    No INV_PATH dependency - dynamically gauges global system RAM and CPU capabilities
    to adjust batch sizing and prevent server resource exhaustion.
    """
    # Check if fetched investors file exists - if not, generate it
    if not os.path.exists(FETCHED_INVESTORS):
        print(f"⚠️ Fetched investors file not found: {FETCHED_INVESTORS}")
        print("🔄 Generating investor data before proceeding...")
        fetch_tables_streaming()
        update_tables_streaming()
        
        # Verify file was created
        if not os.path.exists(FETCHED_INVESTORS):
            print(f" Failed to generate {FETCHED_INVESTORS}")
            return False
        print(f"✅ Successfully generated {FETCHED_INVESTORS}")
    
    # Load investors from JSON
    try:
        with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
            investors_data = json.load(f)
        print(f"📋 Found {len(investors_data)} investors in fetched_investors.json")
    except Exception as e:
        print(f"Error loading investors: {e}")
        return False
    
    if not investors_data:
        print("⚠️ No investor data found, attempting to regenerate...")
        fetch_tables_streaming()
        update_tables_streaming()
        
        # Try loading again
        try:
            with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
                investors_data = json.load(f)
            if not investors_data:
                print(" Still no investor data available")
                return False
        except Exception as e:
            print(f"Error reloading investors: {e}")
            return False

    investor_ids = list(investors_data.keys())

    # --- SENSE HARDWARE SPECS DYNAMICALLY ---
    cpu_cores = os.cpu_count() or 1
    available_ram_bytes = psutil.virtual_memory().available
    available_ram_mb = available_ram_bytes / (1024 * 1024)

    # Base capacity limits based on raw resources
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

    # Subtract active background terminals running in other VS Code instances
    remaining_slots_left = max(0, hardware_max_limit - active_mt5_count)
    
    print(f"📊 Global System Load -> Active MT5 instances in other windows: {active_mt5_count}")
    print(f"🔒 Adjusted Safe Limit for THIS Window: {remaining_slots_left} available slots remaining.")

    if remaining_slots_left == 0:
        print("  SYSTEM AT MAXIMUM SAFE CAPACITY: No resource slots left. Standby to protect VPS.")
        return False

    # --- BATCH LOAD BALANCING SLICE ---
    total_detected = len(investor_ids)
    if total_detected > remaining_slots_left:
        print(f"   OVERLOAD PREVENTED: {total_detected} investors exceeds adjusted limit of {remaining_slots_left}.")
        active_batch = investor_ids[:remaining_slots_left]
        print(f" ⏳ Sliced batch: Processing first {remaining_slots_left} accounts. Deferring remaining {total_detected - remaining_slots_left} accounts.")
    else:
        active_batch = investor_ids

    print(f" 📋 Processing investors: {active_batch}")
    print(f" 🔧 Creating pool with {len(active_batch)} processes...")
    
    # Use a process pool
    try:
        # Use multiprocessing with spawn context (more reliable on Windows)
        mp.set_start_method('spawn', force=True)
        
        with mp.Pool(processes=len(active_batch)) as pool:
            results = pool.map(process_single_investor, active_batch)
        merge_create_results()
        merge_balance_results()
        merge_verify_results()
        #update_tables_streaming()
        
        # Print summary
        successful = sum(1 for r in results if r.get("success", False))
        created = sum(1 for r in results if r.get("folder_created", False))
        existed = sum(1 for r in results if r.get("folder_existed", False))
        
        print(f"\n{'='*60}")
        print(f"📊 SUMMARY:")
        print(f"   Total investors: {len(results)}")
        print(f"   Successful: {successful}")
        print(f"   New folders created: {created}")
        print(f"   Existing folders: {existed}")
        print(f"{'='*60}")
        
        return True
    except Exception as e:
        print(f"Error in parallel processing: {e}")
        # Fallback to sequential processing
        print(" Falling back to sequential processing...")
        results = []
        for inv_id in active_batch:
            result = process_single_investor(inv_id)
            results.append(result)
        
        successful = sum(1 for r in results if r.get("success", False))
        print(f" Sequential: {successful}/{len(results)} successful")
        
        return True

def place_orders_parallel_loop():
    """
    ORCHESTRATOR: Processes all investors from fetched_investors.json
    Runs in a continuous loop. Measures external system terminal loads on every cycle 
    to dynamically scale worker pool slices down if hardware resources become tight.
    """
    print(f"🚀 Starting Perpetual Trading Loop (using fetched_investors.json)...")
    
    # --- BOOT SENSE HARDWARE CAPACITY SPECS ---
    cpu_cores = os.cpu_count() or 1
    available_ram_mb = psutil.virtual_memory().available / (1024 * 1024)

    max_by_cpu = cpu_cores * 4
    max_by_ram = int(available_ram_mb // 300)
    hardware_max_limit = max(1, min(max_by_cpu, max_by_ram))

    print(f"🖥️  Hardware Profile Sensed -> Cores: {cpu_cores} | Free RAM: {available_ram_mb:.1f}MB")
    print(f" 🔧 Hardware Gate: Pre-configuring maximum capacity cap to {hardware_max_limit} accounts.")

    # Initialize pool context safely on Windows
    try:
        mp.set_start_method('spawn', force=True)
    except RuntimeError:
        pass  # Context already set

    # Open permanent worker process slots matching hardware capacity limits
    pool = mp.Pool(processes=hardware_max_limit)
    my_pid = os.getpid()

    try:
        while True:
            try:
                # Check if fetched investors file exists - if not, generate it
                if not os.path.exists(FETCHED_INVESTORS):
                    print(f"⚠️ Fetched investors file not found: {FETCHED_INVESTORS}")
                    print("🔄 Generating investor data before proceeding...")
                    fetch_tables_streaming()
                    update_tables_streaming()
                    
                    # Verify file was created
                    if not os.path.exists(FETCHED_INVESTORS):
                        print(f" Failed to generate {FETCHED_INVESTORS}, retrying in 10 seconds...")
                        time.sleep(10)
                        continue
                    print(f"✅ Successfully generated {FETCHED_INVESTORS}")
                
                # Load investors from JSON
                with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
                    investors_data = json.load(f)
                
                if not investors_data:
                    print("⚠️ No investor data found, attempting to regenerate...")
                    fetch_tables_streaming()
                    update_tables_streaming()
                    
                    # Try loading again
                    try:
                        with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
                            investors_data = json.load(f)
                        if not investors_data:
                            print("⏳ Still no investor data, retrying in 10 seconds...")
                            time.sleep(10)
                            continue
                    except Exception as e:
                        print(f"Error reloading investors: {e}")
                        time.sleep(10)
                        continue
                
                investor_ids = list(investors_data.keys())

                # --- LIVE RUNTIME HARDWARE AUDIT ---
                active_mt5_count = 0
                for proc in psutil.process_iter(['name', 'ppid']):
                    try:
                        pname = proc.info['name'].lower() if proc.info['name'] else ""
                        if "terminal.exe" in pname or "terminal64.exe" in pname:
                            # Exclude processes spawned by this specific script execution channel
                            try:
                                parent = proc.parent()
                                if parent and (parent.pid == my_pid or parent.ppid() == my_pid):
                                    continue
                            except:
                                pass
                            active_mt5_count += 1
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        pass

                # Derive current remaining execution room
                adjusted_capacity = max(0, hardware_max_limit - active_mt5_count)
                current_safe_cap = min(hardware_max_limit, adjusted_capacity)

                if current_safe_cap <= 0:
                    print(f"⏳ [STANDBY] System fully utilized by other terminal instances ({active_mt5_count} running). Retrying pool slice in 3 seconds...")
                    time.sleep(3)
                    continue

                # --- DYNAMIC BATCH ALLOCATION ---
                if len(investor_ids) > current_safe_cap:
                    print(f"   RESOURCE CEILING CEILING APPLIED: Capping active slice loop execution to {current_safe_cap} rows.")
                    active_batch = investor_ids[:current_safe_cap]
                    deferred_count = len(investor_ids) - current_safe_cap
                    print(f" ⏳ Slicing batch: Processing first {current_safe_cap} accounts. {deferred_count} deferred to next loop cycle.")
                else:
                    active_batch = investor_ids

                print(f"\n--- Cycle Start: Processing {len(active_batch)} investors within safe limits ---")
                print(f"   Investors: {active_batch}")
                
                # Use permanent worker channel execution hooks (Async Mapping)
                jobs = []
                for inv_id in active_batch:
                    job = pool.apply_async(process_single_investor, args=(inv_id,))
                    jobs.append(job)
                merge_create_results()
                merge_balance_results()
                merge_verify_results()
                update_tables_streaming()
                
                # Resolve active execution batches concurrently
                results = [job.get() for job in jobs]
                
                successful = sum(1 for r in results if r and r.get("success", False))
                print(f"--- Cycle Complete: {successful}/{len(results)} successful ---")
                
            except Exception as e:
                print(f" Critical Error in Orchestrator Loop: {e}")
                print("   Retrying in 5 seconds...")
                time.sleep(5)
                
            time.sleep(120)

    except KeyboardInterrupt:
        print("\n🛑 Received shutdown signal. Disposing worker process tree gracefully...")
    finally:
        pool.close()
        pool.join()



if __name__ == "__main__":
    place_orders_parallel()
    

if __name__ == "__main__":
    place_orders_parallel()
    
