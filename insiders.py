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
INV_PATH = r"C:\xampp\htdocs\harvcore\harvox\usersdata\investors"
DEFAULT_PATH = r"C:\xampp\htdocs\harvcore\harvox"
DEFAULT_ACCOUNTMANAGEMENT = r"C:\xampp\htdocs\harvcore\harvox\harvcore_accountmanagement.json"
SUSPENDED_ACCOUNTS = r"C:\xampp\htdocs\harvcore\harvox\suspended_accounts.json"
FETCHED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\fetched_investors.json"
UPDATED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\updated_investors.json"


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
        print(f"   ❌ Default config not found: {DEFAULT_ACCOUNTMANAGEMENT}")
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
        print(f"   ❌ Error loading default config: {e}")
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
        print(f"   ❌ No 'working_hours' key found at root level")
        stats["json_structure_found"] = "NO_WORKING_HOURS_KEY"
        time_ranges = []
    
    # Parse time strings (e.g., "12:00 am" or "12:30 pm" or "21:00" or "0:00 am")
    def parse_time_string(time_str):
        # Handle edge cases like raw numbers or floats passed as strings/ints
        time_str_clean = str(time_str).lower().strip().replace(" ", "")
        
        # Absolute raw check for simple zero strings before stripping am/pm modifiers
        if time_str_clean in ["0", "0.00", "0.0", "00:00"]:
            return 0, 0
            
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
        
        if is_pm and hour != 12:
            hour += 12
        elif is_am and hour == 12:
            hour = 0
        
        return hour, minute
    
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
            
            # FIRST: Safely parse and check ALL windows for any true 0 value override rule
            for idx, time_range in enumerate(time_ranges):
                if "from" in time_range and "to" in time_range:
                    try:
                        f_hour, f_min = parse_time_string(time_range["from"])
                        t_hour, t_min = parse_time_string(time_range["to"])
                        
                        # If either from or to side evaluates strictly to 0 hours and 0 minutes
                        if (f_hour == 0 and f_min == 0) or (t_hour == 0 and t_min == 0):
                            print(f"   ⚠️ Window {idx + 1} evaluated to a '0' or '0.00' condition ({time_range['from']} -> {time_range['to']}).")
                            print(f"   👉 Always Work Rule Activated! Restrictions completely bypassed.")
                            zero_override_triggered = True
                            break
                    except Exception:
                        # Fallback simple text check if parsing crashes on weird data types
                        from_clean = str(time_range["from"]).lower().replace(" ", "").replace("am", "").replace("pm", "")
                        to_clean = str(time_range["to"]).lower().replace(" ", "").replace("am", "").replace("pm", "")
                        if from_clean in ["0", "0.00", "0.0", "00:00", "0:00"] or to_clean in ["0", "0.00", "0.0", "00:00", "0:00"]:
                            zero_override_triggered = True
                            break
            
            # SECOND: Process active time windows ONLY if no zero rule was triggered
            if not zero_override_triggered:
                current_time_minutes = current_time.hour * 60 + current_time.minute
                
                for idx, time_range in enumerate(time_ranges):
                    if "from" in time_range and "to" in time_range:
                        try:
                            # Parse start time
                            start_hour, start_minute = parse_time_string(time_range["from"])
                            # Parse end time
                            end_hour, end_minute = parse_time_string(time_range["to"])
                            
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
                                print(f"   ❌ Window {idx + 1}: {time_range['from']} - {time_range['to']}  OUTSIDE")
                                
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
        print(f"   ❌ Error processing time ranges: {e}")
    
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
        
        if denormalized != value:
            print(f"       Denormalized path field '{field_name}':")
            print(f"         Normalized: {value[:100]}{'...' if len(value) > 100 else ''}")
            print(f"         Restored: {denormalized[:100]}{'...' if len(denormalized) > 100 else ''}")
        
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
        
        return cleaned
    
    def save_metadata_to_default_accountmanagement(computer_id, user_ids_to_fetch, total_rows, export_timestamp, identification_method):
        """Save export metadata to the default accountmanagement field in server_account table"""
        try:
            print(f"\n💾 Saving metadata to default server_account.accountmanagement...")
            
            # First, fetch current server_account data
            query = "SELECT accountmanagement FROM server_account LIMIT 1"
            result = db.execute_query(query)
            
            current_management = {}
            if result.get('status') == 'success' and result.get('results'):
                row = result['results'][0]
                if row.get('accountmanagement'):
                    try:
                        if isinstance(row['accountmanagement'], str):
                            current_management = repair_json_field(row['accountmanagement'])
                        elif isinstance(row['accountmanagement'], dict):
                            current_management = row['accountmanagement']
                        else:
                            current_management = {}
                    except:
                        current_management = {}
            
            # Ensure current_management is a dict
            if not isinstance(current_management, dict):
                current_management = {}
            
            # Create metadata object (this is the "_metadata" that was previously in the file)
            metadata = {
                'computer_id': computer_id,
                'identification_method': identification_method,
                'user_ids_filtered': user_ids_to_fetch,
                'export_timestamp': export_timestamp,
                'total_records': total_rows,
                'batch_size': batch_size,
                'auto_fill_accountmanagement': False,
                'config_title_extraction': True,
                'export_history': current_management.get('export_history', [])
            }
            
            # Add to history (keep last 10 exports)
            export_record = {
                'computer_id': computer_id,
                'export_timestamp': export_timestamp,
                'total_records': total_rows,
                'user_ids_count': len(user_ids_to_fetch)
            }
            metadata['export_history'].insert(0, export_record)
            if len(metadata['export_history']) > 10:
                metadata['export_history'] = metadata['export_history'][:10]
            
            # Preserve existing data like requirements and configuration_title
            if 'requirements' in current_management:
                metadata['requirements'] = current_management['requirements']
            if 'configuration_title' in current_management:
                metadata['configuration_title'] = current_management['configuration_title']
            
            # Update the server_account table
            update_query = """
                UPDATE server_account 
                SET accountmanagement = %s 
                WHERE id = (SELECT MIN(id) FROM server_account)
            """
            
            metadata_json = json.dumps(metadata, default=str, indent=2)
            update_result = db.execute_query(update_query, params=(metadata_json,))
            
            if update_result.get('status') == 'success':
                print(f"  ✅ Metadata saved successfully to default accountmanagement")
                print(f"  📊 Export history now contains {len(metadata['export_history'])} records")
                return True
            else:
                print(f"  ⚠️ Failed to save metadata: {update_result.get('message')}")
                return False
                
        except Exception as e:
            print(f"  ⚠️ Error saving metadata: {str(e)}")
            return False
    
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
                print(f"  ❌ IP address NOT FOUND in system_server_config")
        else:
            print(f"  ❌ Could not retrieve local IP address")
        
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
                    print(f"  ❌ VS Code ID NOT FOUND in system_server_config")
            else:
                print(f"  ❌ Could not retrieve VS Code Machine ID")
        
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
        
        # Step 4: Fetch Server Account Management and Requirements (FOR REFERENCE ONLY - NOT USED FOR AUTO-FILL)
        print(f"\n⚙️ [4/6] Fetching Server Account Management & Requirements (Reference Only)...")
        
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
                
                print(f"   Server Account Management Loaded (REFERENCE ONLY - NOT USED FOR AUTO-FILL)")
                print(f"  🔍 Server Requirements (Reference):")
                print(f"     - contract_duration: {requirements.get('contract_duration')} days")
                print(f"     - min_broker_balance: ${requirements.get('min_broker_balance')}")
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
        print(f"  🔧 AccountManagement: Empty values remain as {{}} (no auto-fill)")
        print(f"  🔧 AccountManagement: Wrapper keys extracted to 'configuration_title' field")
        print(f"  💾 Metadata: Will be saved to default server_account.accountmanagement (not in export file)")
        print("-"*70)
        
        start_time = datetime.now()
        bytes_written = 0
        current_batch = 0
        json_repaired_count = 0
        accountmanagement_unwrapped_count = 0
        path_denormalized_count = 0
        
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
        
        # Save metadata to default accountmanagement after successful export
        export_timestamp = datetime.now().isoformat()
        save_metadata_to_default_accountmanagement(computer_id, user_ids_to_fetch, total_rows, export_timestamp, identification_method)
        
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
        print(f"  💾 File Size        : {bytes_written/1024:,.1f} KB ({bytes_written/1048576:.2f} MB)")
        print(f"  ⏱️  Total Time       : {elapsed_time:.1f} seconds")
        print(f"  ⚡ Average Speed    : {avg_speed:,.0f} records/second")
        print(f"  📁 Output File      : {FETCHED_INVESTORS}")
        print(f"  💾 Metadata Saved   : server_account.accountmanagement (default)")
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
    """Stream updates from UPDATED_INVESTORS JSON to database without holding all in memory"""
    
    print("\n" + "="*70)
    print(f"  UPDATING TABLES")
    print("="*70)
    print(f"  Start Time  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Batch Size  : {batch_size:,} records per batch")
    print("-"*70)
    
    try:
        # Step 1: Check if update file exists
        print("\n📁 [1/7] Checking Update File...")
        file_exists = os.path.exists(UPDATED_INVESTORS)
        
        if file_exists:
            file_size = os.path.getsize(UPDATED_INVESTORS)
            print(f"   Update file found: {UPDATED_INVESTORS}")
            print(f"  📦 File Size: {file_size/1024:,.1f} KB ({file_size/1048576:.2f} MB)")
        else:
            print(f"    Update file not found: {UPDATED_INVESTORS}")
        
        # Step 2: Test Database Connection and get table columns
        print("\n📡 [2/7] Testing Database Connection...")
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
        investors_data = {}
        total_investors = 0
        investors_to_update = {}
        investors_to_remove = []
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
                # Check if string represents a JSON object/array
                stripped = value.strip()
                if stripped.startswith('{') and stripped.endswith('}'):
                    return True
                if stripped.startswith('[') and stripped.endswith(']'):
                    return True
            return False
        
        def normalize_path_value(value, field_name):
            """Normalize path values: ONLY replace backslashes with underscores, preserve EVERYTHING else (spaces, colons, etc.)"""
            if value is None:
                return None
            
            # Check if field name contains 'path' (case insensitive)
            if 'path' not in field_name.lower():
                return value
            
            # Only process string values
            if not isinstance(value, str):
                return value
            
            # IMPORTANT: ONLY replace backslash characters with underscore
            # Do NOT replace colons, spaces, forward slashes, or any other characters
            normalized = value.replace('\\', '_')
            
            # Debug print to see what's happening
            if normalized != value:
                print(f"       Normalizing path field '{field_name}':")
                print(f"         Original: {value}")
                print(f"         Normalized: {normalized}")
                print(f"         Changes: Only backslashes replaced with underscores")
            
            return normalized
        
        def normalize_execution_start_date(value):
            """Normalize execution_start_date from 'May 22, 2026' format to '2026-05-23' format"""
            if value is None:
                return None
            
            # If it's not a string, return as is
            if not isinstance(value, str):
                return value
            
            # Try to parse date in various formats
            date_formats = [
                "%B %d, %Y",  # May 22, 2026
                "%b %d, %Y",  # May 22, 2026 (abbreviated month)
                "%d-%b-%Y",   # 22-May-2026
                "%Y-%m-%d",   # 2026-05-22 (already in correct format)
                "%m/%d/%Y",   # 05/22/2026
                "%d/%m/%Y",   # 22/05/2026
                "%Y/%m/%d",   # 2026/05/22
            ]
            
            original_value = value.strip()
            
            for date_format in date_formats:
                try:
                    parsed_date = datetime.strptime(original_value, date_format)
                    # Convert to YYYY-MM-DD format
                    normalized = parsed_date.strftime("%Y-%m-%d")
                    if normalized != original_value:
                        print(f"       Normalizing execution_start_date:")
                        print(f"         Original: {original_value}")
                        print(f"         Normalized: {normalized}")
                    return normalized
                except ValueError:
                    continue
            
            # If no format matches, return original value (maybe it's already in correct format or different)
            return value
        
        def normalize_json_value(value):
            """Convert value to proper JSON for database storage"""
            if value is None:
                return None
            
            # If it's already a dict or list, dump to JSON string
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            
            # If it's a string, try to parse it as JSON
            if isinstance(value, str):
                stripped = value.strip()
                # Handle "NULL" string - treat as NULL
                if stripped.upper() == 'NULL':
                    return None
                # Handle empty string or "{}" - treat as empty JSON object
                if stripped == '' or stripped == '{}':
                    return '{}'
                # Try to parse as JSON to validate
                if (stripped.startswith('{') and stripped.endswith('}')) or \
                   (stripped.startswith('[') and stripped.endswith(']')):
                    try:
                        # Validate it's proper JSON
                        json.loads(stripped)
                        return stripped
                    except:
                        # If parsing fails, treat as regular string
                        return value
            return value
        
        # Step 3: Process insiders data only if file exists and is not empty
        if file_exists:
            # Get file size to check if empty
            file_size = os.path.getsize(UPDATED_INVESTORS)
            
            if file_size > 0:
                # Step 3: Get existing IDs for validation
                print("\n🔍 [3/7] Fetching Existing Record IDs...")
                existing_ids_query = "SELECT id FROM insiders"
                existing_result = db.execute_query(existing_ids_query)
                
                existing_ids = set()
                if existing_result.get('status') == 'success':
                    for row in existing_result.get('results', []):
                        existing_ids.add(str(row.get('id')))
                
                print(f"  📊 Existing Records in DB: {len(existing_ids):,}")
                
                # Step 4: Parse JSON and identify records to process
                print(f"\n📖 [4/7] Reading Update File...")
                
                # Read entire JSON
                with open(UPDATED_INVESTORS, 'r', encoding='utf-8') as f:
                    investors_data = json.load(f)
                
                total_investors = len(investors_data)
                print(f"  📊 Total Investors in File: {total_investors:,}")
                
                # Identify which records need updating (exist in DB) and which to remove
                for investor_id, investor_data in investors_data.items():
                    if investor_id in existing_ids:
                        investors_to_update[investor_id] = investor_data
                    else:
                        investors_to_remove.append(investor_id)
                
                print(f"   Records to Update: {len(investors_to_update):,}")
                print(f"  🗑️  Records Not in DB: {len(investors_to_remove):,}")
                
                # Step 5: Update Database in Batches (only if there are records to update)
                if investors_to_update:
                    print(f"\n📤 [5/7] Updating Database Records...")
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
                            
                            # Build UPDATE query dynamically based on available fields
                            update_parts = []
                            
                            # Process ALL fields from the investor JSON
                            for json_field, value in investor.items():
                                # Skip the id field as it's used in WHERE clause
                                if json_field == 'id':
                                    continue
                                
                                # Check if this column exists in the database
                                if json_field.lower() not in existing_columns:
                                    unmapped_fields.add(json_field)
                                    continue
                                
                                # Make a copy of original value for debugging
                                original_value = value
                                
                                # Normalize execution_start_date if this is the field
                                if json_field.lower() == 'execution_start_date':
                                    value = normalize_execution_start_date(value)
                                
                                # Normalize path values BEFORE any other processing
                                if 'path' in json_field.lower():
                                    value = normalize_path_value(value, json_field)
                                
                                # Handle JSON fields intelligently
                                if is_json_field(value):
                                    # This is a JSON field - normalize and store as JSON
                                    json_value = normalize_json_value(value)
                                    
                                    if json_value is None:
                                        update_parts.append(f"`{json_field}` = NULL")
                                    else:
                                        # Escape single quotes for SQL
                                        escaped_json = json_value.replace("'", "\\'")
                                        update_parts.append(f"`{json_field}` = '{escaped_json}'")
                                    
                                elif value is None:
                                    # Set to NULL
                                    update_parts.append(f"`{json_field}` = NULL")
                                    
                                elif isinstance(value, bool):
                                    # Boolean values
                                    db_value = '1' if value else '0'
                                    update_parts.append(f"`{json_field}` = {db_value}")
                                    
                                elif isinstance(value, (int, float)):
                                    # Numeric values - no quotes needed
                                    update_parts.append(f"`{json_field}` = {value}")
                                    
                                elif isinstance(value, str):
                                    # Check if string is "NULL" (should be treated as SQL NULL)
                                    if value.strip().upper() == 'NULL':
                                        update_parts.append(f"`{json_field}` = NULL")
                                    else:
                                        # Regular string - escape single quotes
                                        escaped_value = value.replace("'", "\\'")
                                        update_parts.append(f"`{json_field}` = '{escaped_value}'")
                                    
                                else:
                                    # Any other type - convert to string
                                    str_value = str(value)
                                    escaped_value = str_value.replace("'", "\\'")
                                    update_parts.append(f"`{json_field}` = '{escaped_value}'")
                            
                            # Skip if no fields to update
                            if not update_parts:
                                print(f"       No valid fields to update for investor {investor_id}")
                                continue
                            
                            # Build complete query with embedded values
                            set_clause = ", ".join(update_parts)
                            query = f"UPDATE insiders SET {set_clause} WHERE id = {int(investor_id)}"
                            
                            # Execute the query
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
                        
                        # Progress bar
                        progress = ((i + len(batch_ids)) / len(investor_ids)) * 100
                        bar_length = 30
                        filled = int(bar_length * (i + len(batch_ids)) // len(investor_ids))
                        bar = '█' * filled + '░' * (bar_length - filled)
                        
                        print(f"  Batch {current_batch:>3}/{total_batches:<3} [{bar}] {progress:5.1f}% | "
                              f"Updated: {batch_updates:>4} | Failed: {batch_failed:>3} | "
                              f"Speed: {records_per_sec:>6,.0f} rec/s | "
                              f"Total: {updated_count:>{len(str(len(investor_ids)))},}/{len(investor_ids):,}")
                    
                    # Show unmapped fields warning
                    if unmapped_fields:
                        print(f"\n    Unmapped/Non-existent fields found (skipped):")
                        for field in sorted(unmapped_fields):
                            print(f"     - {field}")
                    
                    # Update timing
                    elapsed_time = (datetime.now() - start_time).total_seconds()
                    avg_speed = updated_count / elapsed_time if elapsed_time > 0 else 0
                else:
                    print(f"\n📤 [5/7] No records to update - skipping insiders update")
                
                # Step 6: Clean JSON file - Remove ALL processed records
                print(f"\n🧹 [6/7] Cleaning JSON File...")
                
                # Combine all IDs to remove: non-existing + successfully updated
                all_ids_to_remove = investors_to_remove + successfully_updated_ids
                total_removed = len(all_ids_to_remove)
                
                if all_ids_to_remove and investors_data:
                    # Remove all processed records from the dictionary
                    for investor_id in all_ids_to_remove:
                        if investor_id in investors_data:
                            del investors_data[investor_id]
                    
                    # Write the cleaned data back to the file
                    with open(UPDATED_INVESTORS, 'w', encoding='utf-8') as f:
                        json.dump(investors_data, f, indent=2, ensure_ascii=False)
                    
                    print(f"   Cleaned JSON file successfully")
                    print(f"  🗑️  Total Removed: {total_removed:,}")
                    print(f"     - Non-existing records: {len(investors_to_remove):,}")
                    print(f"     - Successfully updated: {len(successfully_updated_ids):,}")
                    print(f"  📊 Remaining in File: {len(investors_data):,}")
                    
                    # Recalculate file size
                    new_file_size = os.path.getsize(UPDATED_INVESTORS)
                    print(f"  📦 New File Size: {new_file_size/1024:,.1f} KB ({new_file_size/1048576:.2f} MB)")
                else:
                    print(f"    No records to remove from file")
            else:
                print(f"\n  Update file is empty (0 bytes)")
                print(f"  Skipping insiders update - no data to process")
        else:
            print(f"\n  No update file found")
            print(f"  Skipping insiders update")
        
        # Step 7: Update account management data in server_account table
        # THIS RUNS REGARDLESS OF INSIDERS UPDATE
        print(f"\n📋 [7/7] Updating Server Account Management Data...")
        print("-"*70)
        
        try:
            # Read the DEFAULT_ACCOUNTMANAGEMENT JSON file
            if os.path.exists(DEFAULT_ACCOUNTMANAGEMENT):
                with open(DEFAULT_ACCOUNTMANAGEMENT, 'r', encoding='utf-8') as f:
                    account_management_data = json.load(f)
                
                file_size_kb = os.path.getsize(DEFAULT_ACCOUNTMANAGEMENT)/1024
                print(f"   Found account management file: {DEFAULT_ACCOUNTMANAGEMENT}")
                print(f"  📦 File Size: {file_size_kb:,.1f} KB")
                
                # DEBUG: Print first few lines of JSON data
                print(f"\n  🔍 DEBUG: Account Management JSON Preview:")
                json_preview = json.dumps(account_management_data, ensure_ascii=False)[:200]
                print(f"     {json_preview}...")
                
                # Get server_account table columns
                get_server_columns_query = """
                SELECT COLUMN_NAME 
                FROM information_schema.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'server_account'
                """
                
                server_columns_result = db.execute_query(get_server_columns_query)
                server_columns = set()
                
                if server_columns_result.get('status') == 'success' and server_columns_result.get('results'):
                    for row in server_columns_result['results']:
                        column_name = row.get('COLUMN_NAME', '')
                        if column_name:
                            server_columns.add(column_name.lower())
                    print(f"\n  📋 Server account columns found: {', '.join(sorted(server_columns))}")
                else:
                    print(f"    Could not fetch server_account columns")
                
                # Check if columns exist in server_account table
                columns_to_update = []
                if 'accountmanagement' in server_columns:
                    columns_to_update.append('accountmanagement')
                    print(f"  ✓ Found column: accountmanagement")
                else:
                    print(f"  ✗ 'accountmanagement' column NOT found in server_account table")
                
                if 'accountmanagement_configs' in server_columns:
                    columns_to_update.append('accountmanagement_configs')
                    print(f"  ✓ Found column: accountmanagement_configs")
                else:
                    print(f"  ✗ 'accountmanagement_configs' column NOT found in server_account table")
                
                if not columns_to_update:
                    print(f"    No target columns found in server_account table")
                    print(f"    Skipping account management update")
                else:
                    # STORE THE EXACT JSON DATA AS IS - NO MODIFICATIONS
                    # Convert to JSON string exactly as read
                    account_management_json = json.dumps(account_management_data, ensure_ascii=False)
                    
                    print(f"\n  🔍 DEBUG: JSON string length: {len(account_management_json)} characters")
                    print(f"  🔍 DEBUG: JSON string preview: {account_management_json[:100]}...")
                    
                    # Escape single quotes for SQL safety
                    escaped_json = account_management_json.replace("'", "\\'")
                    
                    # Check if there are any records in server_account
                    check_records_query = "SELECT COUNT(*) as record_count FROM server_account"
                    records_check = db.execute_query(check_records_query)
                    
                    print(f"\n  🔍 DEBUG: Records check result: {records_check}")
                    
                    if records_check.get('status') == 'success' and records_check.get('results'):
                        try:
                            record_count_value = records_check['results'][0].get('record_count', 0)
                            if isinstance(record_count_value, str):
                                record_count_value = int(record_count_value)
                            record_count = record_count_value
                            print(f"  📊 Found {record_count:,} record(s) in server_account")
                        except (ValueError, TypeError) as e:
                            print(f"    Could not determine record count: {e}")
                            record_count = 0
                        
                        if record_count > 0:
                            # Build UPDATE query for all available columns
                            set_clauses = []
                            for col in columns_to_update:
                                set_clauses.append(f"`{col}` = '{escaped_json}'")
                            
                            # CRITICAL FIX: Add WHERE clause to update ALL rows (or specify which rows)
                            # Since you want to update all records, use WHERE 1=1
                            update_account_query = f"""
                            UPDATE server_account 
                            SET {', '.join(set_clauses)}
                            WHERE 1=1
                            """
                            
                            print(f"\n  🔍 DEBUG: Executing UPDATE query:")
                            print(f"     {update_account_query[:200]}...")
                            
                            update_result = db.execute_query(update_account_query)
                            
                            print(f"  🔍 DEBUG: Update result: {update_result}")
                            
                            if update_result.get('status') == 'success':
                                # Try to get affected rows from different possible locations in the result
                                rows_affected = update_result.get('affected_rows', 0)
                                
                                # If affected_rows is 0, try to get it from message
                                if rows_affected == 0 and 'message' in update_result:
                                    import re
                                    message = update_result.get('message', '')
                                    match = re.search(r'(\d+)\s+row', message)
                                    if match:
                                        rows_affected = int(match.group(1))
                                        print(f"  🔍 DEBUG: Extracted affected rows from message: {rows_affected}")
                                
                                print(f"   ✅ Updated account management data for {rows_affected:,} record(s)")
                                print(f"   Columns updated: {', '.join(columns_to_update)}")
                                
                                # Verify the update by reading back the data
                                verify_query = f"SELECT accountmanagement FROM server_account LIMIT 1"
                                verify_result = db.execute_query(verify_query)
                                if verify_result.get('status') == 'success' and verify_result.get('results'):
                                    first_record = verify_result['results'][0].get('accountmanagement', '')
                                    if first_record:
                                        print(f"  🔍 DEBUG: Verification - First {min(100, len(first_record))} chars of updated data: {first_record[:100]}...")
                                    else:
                                        print(f"  ⚠️ Verification - No data found in accountmanagement column!")
                            else:
                                print(f"   ❌ Failed to update: {update_result.get('message')}")
                        else:
                            # Insert new record if table is empty
                            print(f"  📝 No records found, inserting new record...")
                            
                            # Build INSERT query for all available columns
                            columns_str = ', '.join([f"`{col}`" for col in columns_to_update])
                            values_str = ', '.join([f"'{escaped_json}'" for _ in columns_to_update])
                            
                            insert_account_query = f"""
                            INSERT INTO server_account ({columns_str}) 
                            VALUES ({values_str})
                            """
                            
                            print(f"  🔍 DEBUG: Executing INSERT query:")
                            print(f"     {insert_account_query[:200]}...")
                            
                            insert_result = db.execute_query(insert_account_query)
                            
                            print(f"  🔍 DEBUG: Insert result: {insert_result}")
                            
                            if insert_result.get('status') == 'success':
                                print(f"   ✅ Inserted account management data into server_account")
                                print(f"   Columns inserted: {', '.join(columns_to_update)}")
                            else:
                                print(f"   ❌ Failed to insert: {insert_result.get('message')}")
                    else:
                        print(f"    Could not check records in server_account")
                        print(f"    Query result: {records_check}")
            else:
                print(f"    Default account management file not found: {DEFAULT_ACCOUNTMANAGEMENT}")
                print(f"    Skipping account management update")
                
        except Exception as e:
            print(f"   ❌ Error updating account management: {str(e)}")
            import traceback
            traceback.print_exc()
        
        # Final Summary
        print("-"*70)
        print(f"\n📋 UPDATE SUMMARY")
        print("="*70)
        
        # Insiders Summary
        print(f"\n  📊 INSIDERS UPDATE:")
        if file_exists and 'total_investors' in locals() and total_investors > 0:
            print(f"     Status              : {'SUCCESS' if failed_count == 0 else 'COMPLETED WITH ERRORS'}")
            print(f"     Original in File    : {total_investors:,}")
            if 'total_removed' in locals():
                print(f"     Total Removed       : {total_removed:,}")
                print(f"        - Non-existing   : {len(investors_to_remove):,}")
                print(f"        - Successfully Updated: {len(successfully_updated_ids):,}")
            print(f"     Failed Updates      : {failed_count:,}")
            if 'investors_data' in locals():
                print(f"     Final in File       : {len(investors_data):,}")
            print(f"     Time                : {elapsed_time:.1f} seconds")
            print(f"     Speed               : {avg_speed:,.0f} records/second")
            
            if unmapped_fields:
                print(f"\n       Skipped Fields (not in DB):")
                for field in sorted(unmapped_fields)[:10]:
                    print(f"        - {field}")
                if len(unmapped_fields) > 10:
                    print(f"        ... and {len(unmapped_fields) - 10} more")
        else:
            print(f"     Status              : SKIPPED (no data to process)")
        
        # Account Management Summary
        print(f"\n  📋 ACCOUNT MANAGEMENT UPDATE:")
        if os.path.exists(DEFAULT_ACCOUNTMANAGEMENT):
            # Check if update or insert was successful
            account_status = "CHECKED"
            columns_updated = []
            rows_affected = 0
            
            if 'update_result' in locals() and update_result.get('status') == 'success':
                account_status = "UPDATED"
                rows_affected = update_result.get('affected_rows', 0)
                if rows_affected == 0 and 'message' in update_result:
                    import re
                    match = re.search(r'(\d+)\s+row', update_result.get('message', ''))
                    if match:
                        rows_affected = int(match.group(1))
                if 'columns_to_update' in locals():
                    columns_updated = columns_to_update
            elif 'insert_result' in locals() and insert_result.get('status') == 'success':
                account_status = "INSERTED"
                rows_affected = 1
                if 'columns_to_update' in locals():
                    columns_updated = columns_to_update
            
            print(f"     Status              : {account_status}")
            print(f"     Rows Affected       : {rows_affected}")
            print(f"     Source File         : {DEFAULT_ACCOUNTMANAGEMENT}")
            print(f"     File Size           : {os.path.getsize(DEFAULT_ACCOUNTMANAGEMENT)/1024:,.1f} KB")
            print(f"     Target Columns      : {', '.join(columns_updated) if columns_updated else 'None found'}")
            print(f"     Data Type           : JSON (stored exactly as provided)")
        else:
            print(f"     Status              : SKIPPED (file not found)")
        
        print(f"\n  🕐 Completion Time     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*70)
        
    except json.JSONDecodeError as e:
        print(f"\n{'='*70}")
        print(f"   JSON PARSE ERROR")
        print(f"{'='*70}")
        print(f"  Error: {str(e)}")
        print(f"  File : {UPDATED_INVESTORS}")
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
        inv_id: Optional - specific investor ID to process. If None, processes all investors.
    
    Logic:
        1. If user is suspended/blacklisted -> IGNORE completely (skip immediately)
        2. If folder doesn't exist and user NOT suspended -> CREATE folder, update Terminal_path,
           and if application_status is 'pending', change it to 'just-joined'.
        3. If folder exists and user NOT suspended -> ENSURE Terminal_path is set in record,
           and if application_status is 'pending', change it to 'just-joined'.
    
    Returns:
        tuple: (created_count, deleted_count, skipped_count, error_count)
    """
    
    print(f"\n{'='*60}")
    print(f"📦 CREATE/MAINTAIN MT5 FILES")
    if inv_id:
        print(f"   Target: {inv_id}")
    print(f"{'='*60}")
    
    # Check if source MT5 folder exists
    if not os.path.exists(DEFAULT_MT5_PATH) or not os.path.isdir(DEFAULT_MT5_PATH):
        print(f" Source MT5 folder not found: {DEFAULT_MT5_PATH}")
        return (0, 0, 0, 1)
    
    # Check if fetched investors file exists
    if not os.path.exists(FETCHED_INVESTORS):
        print(f" Fetched investors file not found: {FETCHED_INVESTORS}")
        return (0, 0, 0, 1)
    
    # Load suspended accounts
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
            print(f" Error loading suspended accounts: {e}")
    else:
        print(f" No suspended accounts file found - all users will be processed normally")
    
    # Load fetched investors data
    try:
        with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
            investors_data = json.load(f)
        print(f"📋 Loaded {len(investors_data)} investors from file")
    except Exception as e:
        print(f" Error loading investors: {e}")
        return (0, 0, 0, 1)
    
    # Filter investors if inv_id is specified
    if inv_id:
        inv_id_str = str(inv_id)
        if inv_id_str not in investors_data:
            print(f" Investor {inv_id} not found in data")
            return (0, 0, 0, 1)
        investors_to_process = {inv_id_str: investors_data[inv_id_str]}
    else:
        investors_to_process = investors_data
    
    # Ensure MT5 destination directory exists
    os.makedirs(MT5_DESTINATION_PATH, exist_ok=True)
    
    # Statistics
    created = 0
    deleted = 0
    skipped = 0
    errors = 0
    suspended_skipped = 0
    path_updates = 0  
    status_updates = 0  # Track applications turned from pending -> just-joined
    investors_modified = False
    
    for investor_id, investor_data in investors_to_process.items():
        investor_id_str = str(investor_id)
        
        # RULE 1: If user is suspended/blacklisted -> Skip immediately (or clean up files if present)
        if investor_id_str in suspended_ids:
            broker = investor_data.get('broker', '').strip()
            investor_id_value = investor_data.get('id', '').strip()
            folder_name = f"MetaTrader 5 {broker} {investor_id_value}" if broker and investor_id_value else ""
            target_folder = os.path.join(MT5_DESTINATION_PATH, folder_name) if folder_name else None
            
            if target_folder and os.path.exists(target_folder):
                try:
                    print(f"🗑️  SUSPENDED ID:{investor_id} - Deleting active folder for blacklisted user...")
                    shutil.rmtree(target_folder, ignore_errors=True)
                    deleted += 1
                    if 'Terminal_path' in investors_data[investor_id]:
                        investors_data[investor_id]['Terminal_path'] = ''
                        investors_modified = True
                except Exception as e:
                    errors += 1
                    print(f"    Failed to delete folder: {str(e)[:100]}")
            else:
                print(f"🚫 SUSPENDED ID:{investor_id} - Blacklisted, skipping immediately")
                suspended_skipped += 1
            continue
        
        # Extract broker and id for valid accounts
        broker = investor_data.get('broker', '').strip()
        investor_id_value = investor_data.get('id', '').strip()
        
        if not broker or not investor_id_value:
            print(f" Investor {investor_id} missing broker or id, skipping")
            skipped += 1
            continue
        
        # Create target paths
        folder_name = f"MetaTrader 5 {broker} {investor_id_value}"
        target_folder = os.path.join(MT5_DESTINATION_PATH, folder_name)
        target_exe = os.path.join(target_folder, "terminal64.exe")
        normalized_path = target_exe.replace('\\', '\\')
        
        folder_exists = os.path.exists(target_folder)
        current_status = investor_data.get('application_status', '')
        
        # RULE 2: If folder exists and user is NOT suspended (Verify path regardless of application status)
        if folder_exists:
            current_path = investor_data.get('Terminal_path', '')
            
            # Ensure Terminal_path is set correctly regardless of application status
            if not current_path or current_path != normalized_path:
                investors_data[investor_id]['Terminal_path'] = normalized_path
                investors_modified = True
                path_updates += 1
                print(f"🔧 ID:{investor_id} → Terminal_path fixed to: {normalized_path[:60]}...")
            else:
                print(f"✓ ID:{investor_id} → Terminal_path verified")
            
            # Check application_status: only change if it is exactly "pending"
            if current_status == "pending":
                investors_data[investor_id]['application_status'] = 'just-joined'
                investors_modified = True
                status_updates += 1
                print(f"🔄 ID:{investor_id} → application_status converted from 'pending' to 'just-joined'")
            
            skipped += 1
            continue
        
        # RULE 3: If folder is missing and user is NOT suspended -> Create missing setup
        print(f"🆕 ID:{investor_id} ({broker} {investor_id_value}) - Folder missing. Recreating...")
        
        try:
            # Copy default files
            shutil.copytree(DEFAULT_MT5_PATH, target_folder, 
                            ignore_dangling_symlinks=True,
                            ignore=shutil.ignore_patterns('*.lock', '*.log'))
            
            # Assign structural data
            investors_data[investor_id]['Terminal_path'] = normalized_path
            
            # Handle application status condition
            if current_status == "pending":
                investors_data[investor_id]['application_status'] = 'just-joined'
                status_updates += 1
                print(f"   application_status converted from 'pending' to 'just-joined'")
            else:
                print(f"   application_status kept intact as '{current_status}'")
                
            investors_modified = True
            created += 1
            print(f"   📍 Target: {normalized_path[:60]}...")
            
        except Exception as e:
            errors += 1
            print(f"    Failed to copy folder: {str(e)[:100]}")
            if os.path.exists(target_folder):
                shutil.rmtree(target_folder, ignore_errors=True)
    
    # Save updated JSON state cleanly back to disk
    if investors_modified:
        try:
            with open(FETCHED_INVESTORS, 'w', encoding='utf-8') as f:
                json.dump(investors_data, f, indent=2)
            print(f"\n💾 Saved investor adjustments to {FETCHED_INVESTORS}")
        except Exception as e:
            print(f" Failed to save investor data: {e}")
    
    # Summary Output Data
    print(f"\n{'='*60}")
    print(f"📊 SUMMARY")
    print(f"{'='*60}")
    print(f"   Created folders      : {created}")
    print(f"   🗑️  Deleted folders      : {deleted}")
    print(f"   ⏭️  Skipped (existing)   : {skipped}")
    print(f"   🔧 Path updates         : {path_updates}")
    print(f"   🔄 Status transitions   : {status_updates} (pending -> just-joined)")
    print(f"   🚫 Suspended (ignored)  : {suspended_skipped}")
    print(f"   Errors               : {errors}")
    print(f"{'='*60}")
    
    return (created, deleted, skipped, errors)

def get_investors_balance():
    """
    Get account balance for investors by initializing MT5 and logging in.
    
    Properly distinguishes between:
    - Already logged in (MT5 already running with this investor's account)
    - Fresh login (MT5 initialized and logged in now)
    - Login failed (could not authenticate)
    
    NEW: Checks account mode and demo permissions before processing.
    - If account_mode is "real" → proceed
    - If account_mode is "demo" AND demo_account == "1" → proceed
    - If account_mode is "demo" AND demo_account == "0" → skip
    - If account_mode is unknown/null → check both possibilities
    
    ONLY processes investors with EXACT 'just-joined' status. On success, updates:
    - broker_balance with current account balance
    - application_status to 'just-joined-and-valid_credentials'
    
    Then COPIES investors with 'just-joined-and-valid_credentials' status to updated_investors.json
    (without removing them from fetched_investors.json)
    
    Returns:
        bool: True if at least one investor balance was updated, False otherwise
    """
    
    print(f"\n{'='*60}")
    print(f"💰 GET BALANCES")
    print(f"{'='*60}")
    
    # Check if fetched investors file exists
    if not os.path.exists(FETCHED_INVESTORS):
        print(f"Fetched investors file not found: {FETCHED_INVESTORS}")
        return False
    
    # Load fetched investors data
    try:
        with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
            investors_data = json.load(f)
        print(f"📋 Loaded {len(investors_data)} investors from fetched_investors.json")
    except Exception as e:
        print(f"Error loading investors: {e}")
        return False
    
    # Load existing updated investors data
    updated_investors_data = {}
    if os.path.exists(UPDATED_INVESTORS):
        try:
            with open(UPDATED_INVESTORS, 'r', encoding='utf-8') as f:
                updated_investors_data = json.load(f)
            print(f"📋 Loaded {len(updated_investors_data)} investors from updated_investors.json")
        except Exception as e:
            print(f" Warning: Could not load updated_investors.json: {e}")
    
    # Statistics
    processed = 0
    updated = 0
    skipped = 0
    errors = 0
    already_logged_in_count = 0
    fresh_login_count = 0
    failed_login_count = 0
    demo_skipped = 0
    
    investors_modified = False
    
    # STRICT CHECK: Only exact 'just-joined' status
    for investor_id, investor_data in investors_data.items():
        app_status = investor_data.get('application_status', '').strip()
        
        # STRICT SKIP - Only proceed if status is EXACTLY 'just-joined'
        if app_status != 'just-joined':
            print(f"⏭️ ID:{investor_id} → Status: '{app_status}' (not 'just-joined') - SKIPPING")
            skipped += 1
            continue
        
        # ============================================================
        # ACCOUNT MODE AND DEMO PERMISSION CHECK
        # ============================================================
        account_mode = investor_data.get('account_mode', '').strip().lower()
        demo_account = investor_data.get('demo_account', '').strip()
        
        # Check if demo account is allowed
        if account_mode == 'demo':
            if demo_account == '0':
                print(f"⏭️ ID:{investor_id} → DEMO account but demo_account=0 (DISABLED) - Skipping")
                demo_skipped += 1
                continue
            elif demo_account == '1':
                print(f"✅ ID:{investor_id} → DEMO account with demo_account=1 (ENABLED) - Proceeding")
            else:
                print(f"⚠️ ID:{investor_id} → DEMO account but demo_account not set to '1' (value: {demo_account}) - Skipping")
                demo_skipped += 1
                continue
        elif account_mode == 'real':
            print(f"✅ ID:{investor_id} → REAL account - Proceeding")
        else:
            # account_mode is unknown/null - check both possibilities
            print(f"⚠️ ID:{investor_id} → account_mode not set or unknown: '{account_mode}'")
            print(f"   → Will check credentials first, then determine account type from MT5")
            # Don't skip - let MT5 determine the actual account type
        
        # Extract credentials
        login_id = investor_data.get('login', '') or investor_data.get('LOGIN_ID', '')
        password = investor_data.get('password', '') or investor_data.get('PASSWORD', '')
        server = investor_data.get('server', '') or investor_data.get('SERVER', '')
        Terminal_path = investor_data.get('Terminal_path', '')
        
        if not all([login_id, password, server, Terminal_path]):
            print(f" ID:{investor_id} → Missing credentials")
            skipped += 1
            continue
        
        # Validate login_id
        try:
            login_id_int = int(login_id)
        except (ValueError, TypeError):
            print(f" ID:{investor_id} → Invalid LOGIN_ID: {login_id}")
            skipped += 1
            continue
        
        # Check terminal exists
        if not os.path.exists(Terminal_path):
            print(f"ID:{investor_id} → Terminal not found at: {Terminal_path}")
            errors += 1
            continue
        
        print(f"\n ID:{investor_id} (Login:{login_id_int}) - Processing...")
        
        # Step 1: Check if MT5 is already running and logged in with this account
        mt5_already_running = False
        already_logged_in_account = None
        actual_account_mode = None
        
        try:
            # Try to initialize without path first (use existing running instance)
            if mt5.initialize():
                account_info = mt5.account_info()
                if account_info is not None:
                    already_logged_in_account = account_info.login
                    
                    # Determine actual account mode from MT5
                    if account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL:
                        actual_account_mode = 'real'
                    elif account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO:
                        actual_account_mode = 'demo'
                    elif account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_CONTEST:
                        actual_account_mode = 'demo'
                    else:
                        actual_account_mode = 'unknown'
                    
                    if account_info.login == login_id_int:
                        # CASE 1: Already logged in with this exact account
                        print(f"    ALREADY LOGGED IN STATUS: Investor {login_id_int} is already logged into MT5")
                        print(f"      → Account type detected: {actual_account_mode.upper()}")
                        
                        # Re-check demo permission after detecting actual account type
                        if actual_account_mode == 'demo':
                            if demo_account == '0':
                                print(f"      → SKIPPING: DEMO account detected but demo_account=0 (DISABLED)")
                                demo_skipped += 1
                                mt5.shutdown()
                                continue
                            elif demo_account != '1':
                                print(f"      → SKIPPING: DEMO account detected but demo_account not set to '1'")
                                demo_skipped += 1
                                mt5.shutdown()
                                continue
                            else:
                                print(f"      → DEMO account with demo_account=1 (ENABLED) - Proceeding")
                        
                        # Get account info directly
                        balance = account_info.balance
                        currency = account_info.currency
                        
                        # Update broker_balance
                        balance_str = f"{balance:.2f}"
                        current_balance = investor_data.get('broker_balance', 'NULL')
                        
                        if current_balance != balance_str:
                            investor_data['broker_balance'] = balance_str
                            print(f"    Balance (already logged in): {currency} {balance:,.2f}")
                            updated += 1
                        
                        # Update status
                        old_status = investor_data.get('application_status', 'unknown')
                        investor_data['application_status'] = 'just-joined-and-valid_credentials'
                        
                        # Update account_mode in JSON if it was unknown
                        if investor_data.get('account_mode', '').strip().lower() != actual_account_mode:
                            investor_data['account_mode'] = actual_account_mode
                            print(f"      → Updated account_mode to: {actual_account_mode}")
                        
                        investors_modified = True
                        print(f"   📝 Status: {old_status} → just-joined-and-valid_credentials")
                        
                        processed += 1
                        already_logged_in_count += 1
                        mt5.shutdown()
                        continue
                    else:
                        # Different account is logged in
                        print(f"    WARNING: Different investor {already_logged_in_account} is currently logged into MT5")
                        mt5.shutdown()
                else:
                    # MT5 initialized but no account info (not logged in)
                    print(f"    MT5 is running but no account is logged in")
                    mt5.shutdown()
            else:
                # MT5 not running, need fresh initialization
                print(f"    MT5 is not running - will need fresh initialization")
        except Exception as e:
            print(f"    Could not check MT5 status: {e}")
        
        # Step 2: If not already logged in, try fresh login
        if already_logged_in_account != login_id_int:
            print(f"   🔐 FRESH LOGIN ATTEMPT: Investor {login_id_int} is NOT already logged in")
            print(f"      → Will initialize MT5 and login with credentials")
            
            try:
                # Shutdown any existing connection
                if mt5.terminal_info() is not None:
                    mt5.shutdown()
                
                # Initialize MT5 with specific terminal path
                print(f"      → Initializing MT5 at: {Terminal_path}")
                if not mt5.initialize(path=Terminal_path, timeout=60000):
                    error_msg = mt5.last_error()
                    print(f"   INITIALIZATION FAILED: {error_msg}")
                    print(f"      → COULD NOT LOGIN - MT5 failed to start")
                    failed_login_count += 1
                    errors += 1
                    continue
                
                print(f"      → MT5 initialized successfully")
                
                # Attempt login
                print(f"      → Attempting login with credentials...")
                if not mt5.login(login_id_int, password=password, server=server):
                    error_msg = mt5.last_error()
                    print(f"   LOGIN FAILED: {error_msg}")
                    print(f"      → Investor {login_id_int} could not authenticate")
                    mt5.shutdown()
                    failed_login_count += 1
                    errors += 1
                    continue
                
                # Successful fresh login
                print(f"    FRESH LOGIN SUCCESS: Successfully logged in as {login_id_int}")
                fresh_login_count += 1
                
                # Get account info
                account_info = mt5.account_info()
                if account_info is None:
                    print(f"   No account info after login")
                    mt5.shutdown()
                    errors += 1
                    continue
                
                # Determine actual account mode from MT5
                if account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL:
                    actual_account_mode = 'real'
                elif account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO:
                    actual_account_mode = 'demo'
                elif account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_CONTEST:
                    actual_account_mode = 'demo'
                else:
                    actual_account_mode = 'unknown'
                
                print(f"      → Account type detected: {actual_account_mode.upper()}")
                
                # Check demo permission after login
                if actual_account_mode == 'demo':
                    if demo_account == '0':
                        print(f"      → SKIPPING: DEMO account detected but demo_account=0 (DISABLED)")
                        demo_skipped += 1
                        mt5.shutdown()
                        continue
                    elif demo_account != '1':
                        print(f"      → SKIPPING: DEMO account detected but demo_account not set to '1'")
                        demo_skipped += 1
                        mt5.shutdown()
                        continue
                    else:
                        print(f"      → DEMO account with demo_account=1 (ENABLED) - Proceeding")
                
                # Get balance
                balance = account_info.balance
                currency = account_info.currency
                
                # Update broker_balance
                balance_str = f"{balance:.2f}"
                current_balance = investor_data.get('broker_balance', 'NULL')
                
                if current_balance != balance_str:
                    investor_data['broker_balance'] = balance_str
                    print(f"    Balance (fresh login): {currency} {balance:,.2f}")
                    updated += 1
                else:
                    print(f"    Balance unchanged: {currency} {balance:,.2f}")
                
                # Update status
                old_status = investor_data.get('application_status', 'unknown')
                investor_data['application_status'] = 'just-joined-and-valid_credentials'
                
                # Update account_mode in JSON if it was unknown or different
                if investor_data.get('account_mode', '').strip().lower() != actual_account_mode:
                    investor_data['account_mode'] = actual_account_mode
                    print(f"      → Updated account_mode to: {actual_account_mode}")
                
                investors_modified = True
                print(f"   📝 Status: {old_status} → just-joined-and-valid_credentials")
                
                processed += 1
                
                # Cleanup after fresh login
                mt5.shutdown()
                print(f"      → MT5 session closed")
                
            except Exception as e:
                print(f"   ERROR during fresh login: {str(e)[:100]}")
                failed_login_count += 1
                errors += 1
                try:
                    mt5.shutdown()
                except:
                    pass
    
    # Save updated fetched_investors.json (with updated statuses and balances)
    if investors_modified:
        try:
            backup_path = FETCHED_INVESTORS.replace('.json', '_backup.json')
            if not os.path.exists(backup_path):
                import shutil
                shutil.copy2(FETCHED_INVESTORS, backup_path)
                print(f"\n📦 Created backup: {backup_path}")
            
            with open(FETCHED_INVESTORS, 'w', encoding='utf-8') as f:
                json.dump(investors_data, f, indent=2)
            print(f"💾 Saved updated data to {FETCHED_INVESTORS}")
        except Exception as e:
            print(f"Save failed: {e}")
    
    # ============================================================
    # COPY investors with 'just-joined-and-valid_credentials' to updated_investors.json
    # This runs AFTER all processing and updating is done
    # ============================================================
    print(f"\n{'='*60}")
    print(f"📋 COPYING VALID CREDENTIALS INVESTORS TO UPDATED_INVESTORS.JSON")
    print(f"{'='*60}")
    
    copied_count = 0
    for investor_id, investor_data in investors_data.items():
        app_status = investor_data.get('application_status', '').strip().lower()
        
        # Check if investor has valid credentials status
        if app_status == 'just-joined-and-valid_credentials':
            # Copy to updated_investors.json (overwrite if exists)
            updated_investors_data[investor_id] = investor_data.copy()
            copied_count += 1
            print(f" COPIED ID:{investor_id} to updated_investors.json")
    
    # Save updated_investors.json
    if copied_count > 0:
        try:
            # Create backup of updated_investors.json if it exists
            if os.path.exists(UPDATED_INVESTORS):
                backup_updated_path = UPDATED_INVESTORS.replace('.json', '_backup.json')
                if not os.path.exists(backup_updated_path):
                    import shutil
                    shutil.copy2(UPDATED_INVESTORS, backup_updated_path)
                    print(f"📦 Created backup of updated_investors.json: {backup_updated_path}")
            
            with open(UPDATED_INVESTORS, 'w', encoding='utf-8') as f:
                json.dump(updated_investors_data, f, indent=2)
            print(f"💾 Saved {len(updated_investors_data)} investors to {UPDATED_INVESTORS}")
            print(f"📋 New investors copied: {copied_count}")
        except Exception as e:
            print(f"Failed to save updated_investors.json: {e}")
    else:
        print(f" No investors with 'just-joined-and-valid_credentials' status found to copy")
    
    # Print summary with demo skips
    print(f"\n{'='*60}")
    print(f"✅ GET BALANCES SUMMARY")
    print(f"{'='*60}")
    print(f" Processed: {processed}")
    print(f" Updated: {updated}")
    print(f" Demo accounts skipped (disabled): {demo_skipped}")
    print(f" Skipped (non 'just-joined' status): {skipped}")
    print(f" Errors: {errors}")
    print(f"🔄 Already logged in: {already_logged_in_count}")
    print(f"🔐 Fresh logins: {fresh_login_count}")
    print(f" Failed logins: {failed_login_count}")
    
    # Final cleanup
    try:
        if mt5.terminal_info() is not None:
            mt5.shutdown()
    except:
        pass
    
    return updated > 0

def verify_investors_balance():
    """
    Verify balance for investors who have applied for verification.
    
    NEW: Checks account mode and demo permissions before processing.
    - If account_mode is "real" → proceed
    - If account_mode is "demo" AND demo_account == "1" → proceed
    - If account_mode is "demo" AND demo_account == "0" → skip
    - If account_mode is unknown/null → check both possibilities
    
    Processes investors with balance_verification status = 'applied-for-verification' or 'applied_for_verification'
    
    For each such investor:
    - Gets current account balance using MT5
    - Updates broker_balance with the current balance
    - Changes balance_verification status to 'verified'
    
    Then COPIES these verified investors to updated_investors.json
    (without removing them from fetched_investors.json)
    
    Returns:
        bool: True if at least one investor balance was verified, False otherwise
    """
    
    print(f"\n{'='*60}")
    print(f"🔐 BALANCE VERIFICATION")
    print(f"{'='*60}")
    
    # Check if fetched investors file exists
    if not os.path.exists(FETCHED_INVESTORS):
        print(f"Fetched investors file not found: {FETCHED_INVESTORS}")
        return False
    
    # Load fetched investors data (SOURCE)
    try:
        with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
            investors_data = json.load(f)
        print(f"📋 Loaded {len(investors_data)} investors from fetched_investors.json")
    except Exception as e:
        print(f"Error loading investors: {e}")
        return False
    
    # Statistics
    processed = 0
    verified = 0
    skipped = 0
    errors = 0
    already_logged_in_count = 0
    fresh_login_count = 0
    failed_login_count = 0
    demo_skipped = 0
    
    investors_modified = False
    
    # Define valid verification statuses to process
    verification_statuses = ['applied-for-verification', 'applied_for_verification']
    
    for investor_id, investor_data in investors_data.items():
        balance_verification_status = investor_data.get('balance_verification', '').strip().lower()
        
        # Skip if not applied for verification
        if balance_verification_status not in verification_statuses:
            if balance_verification_status:
                print(f"⏭️ ID:{investor_id} → Balance Verification Status: {balance_verification_status}")
            continue
        
        # ============================================================
        # NEW: ACCOUNT MODE AND DEMO PERMISSION CHECK
        # ============================================================
        account_mode = investor_data.get('account_mode', '').strip().lower()
        demo_account = investor_data.get('demo_account', '').strip()
        
        # Check if demo account is allowed
        if account_mode == 'demo':
            if demo_account == '0':
                print(f"⏭️ ID:{investor_id} → DEMO account but demo_account=0 (DISABLED) - Skipping verification")
                demo_skipped += 1
                continue
            elif demo_account == '1':
                print(f"✅ ID:{investor_id} → DEMO account with demo_account=1 (ENABLED) - Proceeding with verification")
            else:
                print(f"⚠️ ID:{investor_id} → DEMO account but demo_account not set to '1' (value: {demo_account}) - Skipping verification")
                demo_skipped += 1
                continue
        elif account_mode == 'real':
            print(f"✅ ID:{investor_id} → REAL account - Proceeding with verification")
        else:
            # account_mode is unknown/null - check both possibilities
            print(f"⚠️ ID:{investor_id} → account_mode not set or unknown: '{account_mode}'")
            print(f"   → Will check credentials first, then determine account type from MT5")
            # Don't skip - let MT5 determine the actual account type
        
        # Extract credentials
        login_id = investor_data.get('login', '') or investor_data.get('LOGIN_ID', '')
        password = investor_data.get('password', '') or investor_data.get('PASSWORD', '')
        server = investor_data.get('server', '') or investor_data.get('SERVER', '')
        Terminal_path = investor_data.get('Terminal_path', '')
        
        if not all([login_id, password, server, Terminal_path]):
            print(f" ID:{investor_id} → Missing credentials")
            skipped += 1
            continue
        
        # Validate login_id
        try:
            login_id_int = int(login_id)
        except (ValueError, TypeError):
            print(f" ID:{investor_id} → Invalid LOGIN_ID: {login_id}")
            skipped += 1
            continue
        
        # Check terminal exists
        if not os.path.exists(Terminal_path):
            print(f" ID:{investor_id} → Terminal not found at: {Terminal_path}")
            errors += 1
            continue
        
        print(f"\n✅ ID:{investor_id} (Login:{login_id_int}) - Balance Verification in Progress...")
        
        # Check if already logged in with this account
        already_logged_in_account = None
        actual_account_mode = None
        
        try:
            if mt5.initialize():
                account_info = mt5.account_info()
                if account_info is not None:
                    already_logged_in_account = account_info.login
                    
                    # Determine actual account mode from MT5
                    if account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL:
                        actual_account_mode = 'real'
                    elif account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO:
                        actual_account_mode = 'demo'
                    elif account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_CONTEST:
                        actual_account_mode = 'demo'
                    else:
                        actual_account_mode = 'unknown'
                    
                    if account_info.login == login_id_int:
                        print(f"    ✅ Already logged in as {login_id_int}")
                        print(f"      → Account type detected: {actual_account_mode.upper()}")
                        
                        # NEW: Re-check demo permission after detecting actual account type
                        if actual_account_mode == 'demo':
                            if demo_account == '0':
                                print(f"      → SKIPPING VERIFICATION: DEMO account detected but demo_account=0 (DISABLED)")
                                demo_skipped += 1
                                mt5.shutdown()
                                continue
                            elif demo_account != '1':
                                print(f"      → SKIPPING VERIFICATION: DEMO account detected but demo_account not set to '1'")
                                demo_skipped += 1
                                mt5.shutdown()
                                continue
                            else:
                                print(f"      → DEMO account with demo_account=1 (ENABLED) - Proceeding with verification")
                        
                        balance = account_info.balance
                        currency = account_info.currency
                        
                        balance_str = f"{balance:.2f}"
                        investor_data['broker_balance'] = balance_str
                        investor_data['balance_verification'] = 'verified'
                        
                        # Update account_mode in JSON if it was unknown
                        if investor_data.get('account_mode', '').strip().lower() != actual_account_mode:
                            investor_data['account_mode'] = actual_account_mode
                            print(f"      → Updated account_mode to: {actual_account_mode}")
                        
                        investors_modified = True
                        
                        print(f"    💰 Balance: {currency} {balance:,.2f}")
                        print(f"    📝 Status: {balance_verification_status} → verified")
                        
                        processed += 1
                        verified += 1
                        already_logged_in_count += 1
                        mt5.shutdown()
                        continue
                mt5.shutdown()
        except Exception as e:
            print(f"    Could not check MT5 status: {e}")
        
        # Fresh login attempt
        print(f"    🔐 Fresh login for {login_id_int}...")
        
        try:
            if mt5.terminal_info() is not None:
                mt5.shutdown()
            
            if not mt5.initialize(path=Terminal_path, timeout=60000):
                error_msg = mt5.last_error()
                print(f"     INITIALIZATION FAILED: {error_msg}")
                failed_login_count += 1
                errors += 1
                continue
            
            if not mt5.login(login_id_int, password=password, server=server):
                error_msg = mt5.last_error()
                print(f"     LOGIN FAILED: {error_msg}")
                mt5.shutdown()
                failed_login_count += 1
                errors += 1
                continue
            
            print(f"    ✅ Fresh login successful")
            fresh_login_count += 1
            
            account_info = mt5.account_info()
            if account_info is None:
                print(f"     No account info after login")
                mt5.shutdown()
                errors += 1
                continue
            
            # Determine actual account mode from MT5
            if account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL:
                actual_account_mode = 'real'
            elif account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO:
                actual_account_mode = 'demo'
            elif account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_CONTEST:
                actual_account_mode = 'demo'
            else:
                actual_account_mode = 'unknown'
            
            print(f"      → Account type detected: {actual_account_mode.upper()}")
            
            # NEW: Check demo permission after login
            if actual_account_mode == 'demo':
                if demo_account == '0':
                    print(f"      → SKIPPING VERIFICATION: DEMO account detected but demo_account=0 (DISABLED)")
                    demo_skipped += 1
                    mt5.shutdown()
                    continue
                elif demo_account != '1':
                    print(f"      → SKIPPING VERIFICATION: DEMO account detected but demo_account not set to '1'")
                    demo_skipped += 1
                    mt5.shutdown()
                    continue
                else:
                    print(f"      → DEMO account with demo_account=1 (ENABLED) - Proceeding with verification")
            
            balance = account_info.balance
            currency = account_info.currency
            
            balance_str = f"{balance:.2f}"
            investor_data['broker_balance'] = balance_str
            investor_data['balance_verification'] = 'verified'
            
            # Update account_mode in JSON if it was unknown or different
            if investor_data.get('account_mode', '').strip().lower() != actual_account_mode:
                investor_data['account_mode'] = actual_account_mode
                print(f"      → Updated account_mode to: {actual_account_mode}")
            
            investors_modified = True
            
            print(f"    💰 Balance: {currency} {balance:,.2f}")
            print(f"    📝 Status: {balance_verification_status} → verified")
            
            processed += 1
            verified += 1
            
            mt5.shutdown()
            
        except Exception as e:
            print(f"     ERROR: {str(e)[:100]}")
            failed_login_count += 1
            errors += 1
            try:
                mt5.shutdown()
            except:
                pass
    
    # Save updated fetched_investors.json (SOURCE - update the status and balance)
    if investors_modified:
        with open(FETCHED_INVESTORS, 'w', encoding='utf-8') as f:
            json.dump(investors_data, f, indent=2)
        print(f"\n💾 Updated fetched_investors.json")
    
    # COPY verified investors to updated_investors.json (RESULT)
    print(f"\n{'='*60}")
    print(f"📋 COPYING VERIFIED INVESTORS TO UPDATED_INVESTORS.JSON")
    print(f"{'='*60}")
    
    # Build updated_investors.json with ONLY verified investors
    updated_investors_data = {}
    copied_count = 0
    
    for investor_id, investor_data in investors_data.items():
        balance_verification_status = investor_data.get('balance_verification', '').strip().lower()
        
        if balance_verification_status == 'verified':
            updated_investors_data[investor_id] = investor_data.copy()
            copied_count += 1
            print(f"✅ COPIED ID:{investor_id} to updated_investors.json")
    
    # Save updated_investors.json (RESULT - overwrite with fresh data)
    if copied_count > 0:
        with open(UPDATED_INVESTORS, 'w', encoding='utf-8') as f:
            json.dump(updated_investors_data, f, indent=2)
        print(f"💾 Saved {copied_count} verified investors to updated_investors.json")
    else:
        print(f"⚠️ No verified investors to copy")
    
    # Print summary with demo skips
    print(f"\n{'='*60}")
    print(f"✅ BALANCE VERIFICATION SUMMARY")
    print(f"{'='*60}")
    print(f"✅ Verified: {verified}")
    print(f" Demo accounts skipped (disabled): {demo_skipped}")
    print(f" Errors: {errors}")
    print(f"🔄 Already logged in: {already_logged_in_count}")
    print(f"🔐 Fresh logins: {fresh_login_count}")
    print(f" Failed logins: {failed_login_count}")
    
    # Final cleanup
    try:
        if mt5.terminal_info() is not None:
            mt5.shutdown()
    except:
        pass
    
    return verified > 0

def process_single_invest(inv_id):
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
        create_investor_mt5_files(inv_id=inv_id)
        
    except Exception as e:
        account_stats["error"] = str(e)
        print(f"Error for {inv_id}: {e}")
    
    return account_stats

def process_single_investor(inv_id):
    """
    WORKER FUNCTION: Only creates MT5 folders if they don't exist and executes
    other operations ONLY if within allowed time range.
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
        account_stats["success"] = True  # Consider this as "successfully skipped"
        return account_stats
    
    # Within time range - proceed with operations
    account_stats["within_time_range"] = True
    
    try:
        # Execute the operations only if within time range
        #update_tables_streaming()
        fetch_tables_streaming()
        create_investor_mt5_files(inv_id=inv_id)
        get_investors_balance()
        verify_investors_balance()
        close_db_browser()
        initialize_browser(force_new=True)
        update_tables_streaming()
        
        account_stats["success"] = True
        
    except Exception as e:
        account_stats["error"] = str(e)
        print(f"Error for {inv_id}: {e}")
    
    return account_stats


def place_orders_parallel():
    """
    ORCHESTRATOR: Processes all investors from fetched_investors.json
    No INV_PATH dependency - dynamically gauges global system RAM and CPU capabilities
    to adjust batch sizing and prevent server resource exhaustion.
    """
    # Check if fetched investors file exists
    if not os.path.exists(FETCHED_INVESTORS):
        print(f"Fetched investors file not found: {FETCHED_INVESTORS}")
        return False
    
    # Load investors from JSON
    try:
        with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
            investors_data = json.load(f)
        print(f"📋 Found {len(investors_data)} investors in fetched_investors.json")
    except Exception as e:
        print(f"Error loading investors: {e}")
        return False
    
    if not investors_data:
        update_tables_streaming()
        fetch_tables_streaming()
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
                # Check if fetched investors file exists
                if not os.path.exists(FETCHED_INVESTORS):
                    print(f"  Fetched investors file not found: {FETCHED_INVESTORS}")
                    print("   Retrying in 10 seconds...")
                    time.sleep(10)
                    continue
                
                # Load investors from JSON
                with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
                    investors_data = json.load(f)
                
                if not investors_data:
                    update_tables_streaming()
                    fetch_tables_streaming()
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
    fetch_tables_streaming()
    
