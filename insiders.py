import connectwithinfinitydb as db
import json
import os
from datetime import datetime
import time
from webdriver_manager.chrome import ChromeDriverManager

DEFAULT_PATH = r"C:\xampp\htdocs\chronedge\synarex"
FETCHED_INVESTORS = r"C:\xampp\htdocs\chronedge\synarex\fetched_investors.json"
UPDATED_INVESTORS = r"C:\xampp\htdocs\chronedge\synarex\updated_investors.json"

def fetch_insiders_rows():
    try:
        print(f"[ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ] Starting fetch...")
        
        # Ensure correct table name
        query = "SELECT * FROM insiders" 
        result = db.execute_query(query)
        
        if result.get('status') != 'success':
            print(f"QUERY ERROR: {result.get('message')}")
            return
            
        rows = result.get('results', [])

        if not rows:
            print("WARNING: Database returned 'success' but the results list is empty.")
            print("Check if the table 'insiders' actually has rows in the PHP interface.")
            return
            
        print(f"SUCCESS: Fetched {len(rows)} records from 'insiders'")
        
        investors_data = {}
        for row in rows:
            # Safely identify the unique ID for the JSON key
            record_id = str(row.get('id') or row.get('ID') or "")
            if record_id:
                investors_data[record_id] = row
            else:
                # Fallback if no ID is found (uses timestamp as key)
                temp_key = f"unknown_{datetime.now().timestamp()}"
                investors_data[temp_key] = row
        
        # Save to file
        os.makedirs(os.path.dirname(FETCHED_INVESTORS), exist_ok=True)
        with open(FETCHED_INVESTORS, 'w', encoding='utf-8') as f:
            json.dump(investors_data, f, indent=4, default=str)
            
        print(f"DONE: Data saved to {FETCHED_INVESTORS}")
        
    except Exception as e:
        print(f"CRITICAL ERROR in fetch process: {e}")
    finally:
        db.shutdown()


def update_insiders_from_json():
    try:
        print(f"[ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ] Starting update process...")

        if not os.path.exists(UPDATED_INVESTORS):
            print(f"Error: File not found at {UPDATED_INVESTORS}")
            return

        with open(UPDATED_INVESTORS, 'r', encoding='utf-8') as f:
            updated_data = json.load(f)

        for record_key, data in updated_data.items():
            target_id = record_key 
            
            # --- STEP 1: VERIFY IF ID EXISTS ---
            check_query = f"SELECT id FROM insiders WHERE id = '{target_id}'"
            check_result = db.execute_query(check_query)
            
            # The results will now correctly wait for the table before returning []
            if not check_result.get('results'):
                print(f"SKIP: ID '{target_id}' could not be verified. Moving to next...")
                continue

            # --- STEP 2: DATA PREPARATION ---
            # (Date formatting and JSON cleaning logic remains the same)
            def clean_json(val):
                if val is None or val == "NULL": return "{}"
                return json.dumps(val, separators=(',', ':')).replace("'", "''")

            trades_json = clean_json(data.get('trades'))
            unauthorized_json = clean_json(data.get('unauthorized_actions'))

            # --- STEP 3: CONSTRUCT UPDATE ---
            update_query = f"""
                UPDATE insiders 
                SET 
                    server = '{data.get('server', '')}',
                    login = '{data.get('login', '')}',
                    password = '{data.get('password', '')}',
                    application_status = '{data.get('application_status', '')}',
                    broker_balance = {data.get('broker_balance', 0)},
                    profitandloss = {data.get('profitandloss', 0)},
                    contract_days_left = {data.get('contract_days_left', 0)},
                    trades = '{trades_json}',
                    unauthorized_actions = '{unauthorized_json}'
                WHERE id = '{target_id}'
            """.strip()

            print(f"Executing update for ID {target_id}...")
            result = db.execute_query(update_query)
            
            if result.get('status') == 'success':
                print(f"SUCCESS: Updated ID {target_id}")
            else:
                print(f"ERROR: Failed to update ID {target_id}: {result.get('message')}")
            
            # Small pause to prevent rate-limiting by the host
            time.sleep(1)

    except Exception as e:
        print(f"Critical Error: {e}")
    finally:
        db.shutdown()

if __name__ == "__main__":
   update_insiders_from_json()
    