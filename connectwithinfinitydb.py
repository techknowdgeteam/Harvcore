from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import requests
import time
import signal
import sys
import os
from bs4 import BeautifulSoup
import re
import json
from datetime import datetime
import psutil
import shutil
import traceback
import threading
import subprocess
import tempfile

# ==============================================================================
#  CRITICAL CONFIGURATION
# ==============================================================================
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# Server Configuration
primary_servers = {
    'query_page': 'https://harvhub.42web.io/phpmyadmintemplate.php',
    'fetch': 'https://harvhub.42web.io/phpmyadmin_tablesfetch.php'
}
backup_servers = {
    'query_page': 'https://harvhub.42web.io/phpmyadmintemplate.php',
    'fetch': 'https://harvhub.42web.io/phpmyadmin_tablesfetch.php'
}
server3 = {
    'query_page': 'https://harvhub.42web.io/phpmyadmintemplate.php',
    'fetch': 'https://harvhub.42web.io/phpmyadmin_tablesfetch.php'
}

admin_email = 'ciphercirclex12@gmail.com'
admin_password = '@ciphercircleadminauthenticator#'
temp_download_dir = r'C:\xampp\htdocs\CIPHER\temp_downloads'
json_log_path = r'C:\xampp\htdocs\CIPHER\cipher trader\market\dbserver\connectwithdb.json'

# Global driver and session - SINGLE PERSISTENT INSTANCE
driver = None
session = None
current_servers = primary_servers
_browser_lock = threading.Lock()  # Thread safety for concurrent calls
_is_shutdown = False  # Track if shutdown was explicitly called
# ==============================================================================


def print_header(title, width=70):
    """Print a formatted header."""
    print(f"\n{'='*width}")
    print(f"  {title}")
    print(f"{'='*width}")

def print_step(step_num, total_steps, description):
    """Print a formatted step indicator."""
    print(f"\n   [{step_num}/{total_steps}] {description}")

def print_success(message):
    """Print a success message."""
    print(f"   ✅ {message}")

def print_error(message, details=None):
    """Print an error message with optional details."""
    print(f"   ❌ {message}")
    if details:
        print(f"     └─ Details: {details}")

def print_warning(message):
    """Print a warning message."""
    print(f"   ⚠️  {message}")

def print_info(message):
    """Print an info message."""
    print(f"   ℹ️  {message}")

def print_divider(char="─", width=70):
    """Print a divider line."""
    print(f"  {char*width}")

def is_browser_alive():
    """Check if the browser instance is still alive and responsive."""
    global driver
    
    if driver is None:
        return False
    
    try:
        # Try to get current URL as a heartbeat check
        current_url = driver.current_url
        if current_url and "data:" not in current_url:
            return True
        return False
    except Exception:
        return False

def kill_chrome_processes_and_clean_locks():
    """Force kill all Chrome processes and remove webdriver locks"""
    
    print_info("Cleaning Chrome processes and locks...")
    
    # 1. Kill all Chrome processes using taskkill (more aggressive)
    killed_count = 0
    try:
        # Kill all Chrome processes
        result = subprocess.run(["taskkill", "/f", "/im", "chrome.exe", "/t"], 
                               capture_output=True, text=True)
        if "SUCCESS" in result.stdout or result.returncode == 0:
            killed_count += 1
            print_success("Killed Chrome processes via taskkill")
        
        # Kill all ChromeDriver processes
        result = subprocess.run(["taskkill", "/f", "/im", "chromedriver.exe", "/t"], 
                               capture_output=True, text=True)
        if "SUCCESS" in result.stdout or result.returncode == 0:
            killed_count += 1
            print_success("Killed ChromeDriver processes via taskkill")
        
        if killed_count > 0:
            print_success(f"Killed {killed_count} process group(s)")
            time.sleep(2)  # Wait for processes to fully terminate
    except Exception as e:
        print_warning(f"Error killing processes: {e}")
    
    # 2. Remove the entire .wdm directory
    wdm_dir = os.path.expanduser(r"~\.wdm")
    removed_count = 0
    
    if os.path.exists(wdm_dir):
        try:
            # Try to remove the entire directory
            shutil.rmtree(wdm_dir, ignore_errors=True)
            print_success("Removed entire .wdm directory")
            removed_count += 1
        except Exception as e:
            print_warning(f"Could not remove entire .wdm directory: {e}")
            # Fallback: remove individual lock files
            for root, dirs, files in os.walk(wdm_dir):
                for file in files:
                    if ".wdm-lock" in file and file.endswith(".lock"):
                        lock_path = os.path.join(root, file)
                        try:
                            os.remove(lock_path)
                            removed_count += 1
                            print_success(f"Removed lock: {file}")
                        except Exception as e:
                            print_warning(f"Could not remove {file}: {e}")
    
    if removed_count > 0:
        print_success(f"Removed {removed_count} lock file(s)")
    
    return killed_count > 0 or removed_count > 0

def initialize_browser(force_new=False):
    """
    Initialize Chrome browser in HEADLESS mode - ALWAYS HEADLESS.
    
    Args:
        force_new (bool): If True, creates a new instance even if one exists
    
    Returns:
        bool: True if browser is ready, False otherwise
    """
    global driver, session, current_servers, _is_shutdown
    
    with _browser_lock:
        # If shutdown was explicitly called, don't reuse
        if _is_shutdown and not force_new:
            print_warning("Browser was explicitly shut down. Create new instance by calling with force_new=True")
            return False
        
        # Check if we can reuse existing browser
        if not force_new and is_browser_alive():
            print_info("Reusing existing browser session...")
            try:
                # Verify session is still valid
                driver.get(current_servers['query_page'])
                # Re-sync session cookies
                if session:
                    session.close()
                session = requests.Session()
                for cookie in driver.get_cookies():
                    session.cookies.set(cookie['name'], cookie['value'])
                print_success("Existing browser session reused successfully")
                return True
            except Exception as e:
                print_warning(f"Existing session invalid, restarting...: {str(e)[:100]}")
                try: 
                    driver.quit()
                except: 
                    pass
                driver = None
                session = None
        
        # Clean up any existing Chrome processes before starting new one
        print_info("Cleaning up existing Chrome processes...")
        kill_chrome_processes_and_clean_locks()
        
        print_header("BROWSER INITIALIZATION (HEADLESS MODE)")
        
        # Step 1: Setup Chrome Options - ALWAYS HEADLESS
        print_step(1, 3, "Setting Up Chrome Environment (Headless)")
        
        # Create a temporary directory for this session
        temp_dir = tempfile.mkdtemp(prefix='chrome_selenium_')
        
        chrome_options = Options()
        if os.path.exists(CHROME_PATH):
            chrome_options.binary_location = CHROME_PATH
            print_info(f"Using manual Chrome path: {CHROME_PATH}")
        
        # ALWAYS HEADLESS - THIS IS THE KEY
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--log-level=3")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        chrome_options.add_argument(f"--user-data-dir={temp_dir}")
        
        print_info("🔧 Headless mode enabled")

        # Step 2: Initialize ChromeDriver with retry
        print_step(2, 3, "Initializing ChromeDriver")
        
        # Try multiple times with increasing delays
        max_attempts = 3
        driver_initialized = False
        
        for attempt in range(1, max_attempts + 1):
            try:
                if attempt > 1:
                    print_info(f"Retry attempt {attempt}/{max_attempts}...")
                    # Clean up again before retry
                    kill_chrome_processes_and_clean_locks()
                    time.sleep(2)
                
                # Try to use cached ChromeDriver first
                chromedriver_cache = os.path.expanduser(r"~\.chromedriver_cache")
                chromedriver_exe = os.path.join(chromedriver_cache, "chromedriver.exe")
                
                if os.path.exists(chromedriver_exe):
                    print_info("Using cached ChromeDriver...")
                    service = Service(chromedriver_exe)
                else:
                    print_info("Downloading ChromeDriver (this may take a moment)...")
                    # Install ChromeDriver
                    driver_path = ChromeDriverManager().install()
                    
                    # Cache it for future use
                    try:
                        os.makedirs(chromedriver_cache, exist_ok=True)
                        shutil.copy2(driver_path, chromedriver_exe)
                        print_info(f"Cached ChromeDriver at: {chromedriver_exe}")
                    except:
                        pass
                    
                    service = Service(driver_path)
                
                driver = webdriver.Chrome(service=service, options=chrome_options)
                print_success("ChromeDriver initialized successfully in HEADLESS mode")
                driver_initialized = True
                break  # Success, exit retry loop
                
            except Exception as e:
                error_msg = str(e)
                if attempt < max_attempts:
                    print_warning(f"Attempt {attempt} failed: {error_msg[:100]}")
                    time.sleep(3)
                else:
                    print_error("Failed to initialize ChromeDriver after multiple attempts", error_msg)
                    return False

        if not driver_initialized:
            return False

        # Step 3: Authenticate
        print_step(3, 3, "Authenticating and Accessing Query Page")
        
        server_attempts = [
            (primary_servers, "Primary"),
            (backup_servers, "Backup"),
            (server3, "Server 3")
        ]
        
        for servers, server_type in server_attempts:
            current_servers = servers
            print_info(f"Trying {server_type} server: {servers['query_page']}")
            
            try:
                driver.get(servers['query_page'])
                
                # Inject credentials via LocalStorage
                driver.execute_script(f"localStorage.setItem('admin_email', '{admin_email}');")
                driver.execute_script(f"localStorage.setItem('admin_password', '{admin_password}');")
                
                # Reload to apply credentials
                driver.get(servers['query_page'])
                
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.ID, "sql-query"))
                )
                
                print_success(f"Authenticated on {server_type} server")
                
                # Sync requests session
                if session:
                    session.close()
                session = requests.Session()
                for cookie in driver.get_cookies():
                    session.cookies.set(cookie['name'], cookie['value'])
                
                append_to_json_log(server_type, servers['query_page'])
                _is_shutdown = False  # Reset shutdown flag on successful init
                return True
                
            except Exception as e:
                print_warning(f"{server_type} server failed: {str(e)[:100]}")
                continue

        print_error("All servers failed authentication")
        return False
        
def append_to_json_log(server_type, server_url):
    """Append the server used to the JSON log file."""
    log_entry = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'server_type': server_type,
        'server_url': server_url,
        'status': 'success'
    }
    log_data = []

    try:
        if os.path.exists(json_log_path):
            with open(json_log_path, 'r', encoding='utf-8') as f:
                log_data = json.load(f)
                if not isinstance(log_data, list):
                    log_data = []
    except Exception:
        log_data = []

    if log_data and log_data[-1].get('server_url') == server_url:
        return  # Skip duplicate

    log_data.append(log_entry)

    try:
        os.makedirs(os.path.dirname(json_log_path), exist_ok=True)
        with open(json_log_path, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, indent=2)
    except Exception as e:
        print_warning(f"Failed to write JSON log: {str(e)[:100]}")

def signal_handler(sig, frame):
    """Handle script interruption (Ctrl+C)."""
    print_warning("\nScript interrupted by user. Cleaning up...")
    cleanup()
    sys.exit(0)

def cleanup():
    """Clean up resources before exiting - ONLY closes browser if not already shut down."""
    global driver, session, _is_shutdown
    
    if _is_shutdown:
        print_info("Browser already shut down")
        return
    
    print_header("CLEANUP")
    
    if driver:
        print_info("Clearing browser localStorage...")
        try:
            if driver and "data:" not in driver.current_url:
                driver.execute_script("localStorage.clear();")
                print_success("LocalStorage cleared")
        except Exception as e:
            print_warning(f"Failed to clear localStorage: {e}")
        
        print_info("Closing browser...")
        try:
            driver.quit()
        except:
            pass
        driver = None
        print_success("Browser closed")

    if session:
        try:
            session.close()
        except:
            pass
        session = None
        print_success("HTTP session closed")

    # Cleanup temp directory
    if os.path.exists(temp_download_dir):
        print_info(f"Cleaning temp directory: {temp_download_dir}")
        try:
            for temp_file in os.listdir(temp_download_dir):
                file_path = os.path.join(temp_download_dir, temp_file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            os.rmdir(temp_download_dir)
            print_success("Temp directory removed")
        except Exception as e:
            print_warning(f"Failed to clean temp directory: {e}")
    
    _is_shutdown = True

def shutdown():
    """Explicitly shut down the browser and cleanup - call this when you want to close Chrome."""
    global _is_shutdown
    print_info("Explicit shutdown requested...")
    cleanup()

def check_server_availability(url):
    """Check if a server is available."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive'
        }
        response = requests.head(url, headers=headers, timeout=10, verify=True)
        return response.status_code == 200
    except requests.RequestException:
        return False

def execute_query(sql_query, params=None, reuse_browser=True):
    """Execute SQL query via Selenium browser automation with proper parameter handling.
    
    Args:
        sql_query (str): SQL query string (can contain %s placeholders)
        params (tuple/list, optional): Parameters to substitute for placeholders
        reuse_browser (bool): If True, reuse existing browser instance
    
    Returns:
        dict: Query results with status, message, results, and affected_rows
    """
    global driver, session
    
    # Handle parameters properly
    if params:
        # Convert single param to tuple for consistent handling
        if not isinstance(params, (tuple, list)):
            params = (params,)
        
        # Build final query with proper escaping
        final_sql = sql_query
        for param in params:
            # Find first %s placeholder
            if '%s' not in final_sql:
                break
                
            if param is None:
                final_sql = final_sql.replace('%s', 'NULL', 1)
            elif isinstance(param, bool):
                final_sql = final_sql.replace('%s', '1' if param else '0', 1)
            elif isinstance(param, (int, float)):
                final_sql = final_sql.replace('%s', str(param), 1)
            elif isinstance(param, (dict, list)):
                # Convert dict/list to JSON string
                json_str = json.dumps(param, ensure_ascii=False)
                # Escape for SQL
                escaped = json_str.replace("'", "''").replace("\\", "\\\\")
                final_sql = final_sql.replace('%s', f"'{escaped}'", 1)
            else:
                # String parameter - escape properly
                escaped = str(param).replace("'", "''").replace("\\", "\\\\")
                final_sql = final_sql.replace('%s', f"'{escaped}'", 1)
    else:
        final_sql = sql_query
    
    print_divider()
    
    try:
        # Initialize browser with retry logic
        max_retries = 3
        for attempt in range(max_retries):
            if attempt > 0:
                print_info(f"Retry attempt {attempt + 1}/{max_retries} for browser initialization...")
                time.sleep(3)
                # Clean up before retry
                kill_chrome_processes_and_clean_locks()
            
            if initialize_browser(force_new=True):
                break
            elif attempt == max_retries - 1:
                return {
                    'status': 'error', 
                    'message': 'Browser initialization failed after multiple attempts', 
                    'results': [],
                    'affected_rows': 0
                }

        # Step 4: Inject SQL Query with robust element finding
        print_step(4, 6, "Injecting SQL Query")
        try:
            # Wait for page to be ready with multiple selector attempts
            query_textarea = None
            for selector in ["#sql-query", "textarea#sql-query", "textarea[name='sql-query']"]:
                try:
                    query_textarea = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    break
                except:
                    continue
            
            if not query_textarea:
                # Try to find any textarea on the page
                try:
                    query_textarea = driver.find_element(By.TAG_NAME, "textarea")
                except:
                    pass
            
            if not query_textarea:
                raise Exception("Could not find query textarea")
            
            # Clear and set value using JavaScript (more reliable)
            driver.execute_script("arguments[0].value = '';", query_textarea)
            driver.execute_script("arguments[0].value = arguments[1];", query_textarea, final_sql)
            driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", query_textarea)
            driver.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", query_textarea)
            
            # Small delay to ensure UI updates
            time.sleep(0.5)
            
            # Find execute button with multiple strategies
            execute_button = None
            button_selectors = [
                "//button[text()='Execute Query']",
                "//button[contains(text(), 'Execute')]",
                "//button[@id='execute-query']",
                "//button[@class='execute-query']",
                "//button[@type='submit']",
                "//input[@type='submit' and contains(@value, 'Execute')]"
            ]
            
            for selector in button_selectors:
                try:
                    if selector.startswith("//"):
                        execute_button = driver.find_element(By.XPATH, selector)
                    else:
                        execute_button = driver.find_element(By.CSS_SELECTOR, selector)
                    if execute_button:
                        break
                except:
                    continue
            
            if execute_button:
                # Try JavaScript click first
                driver.execute_script("arguments[0].click();", execute_button)
                print_success("Query injected and executed")
            else:
                print_warning("Execute button not found, attempting form submission...")
                # Try to submit the form directly
                try:
                    driver.execute_script("document.querySelector('form').submit();")
                    print_success("Form submitted")
                except:
                    raise Exception("Could not find execute button or form")
                
        except Exception as e:
            print_error("Failed to inject query", str(e))
            return {
                'status': 'error', 
                'message': f"Query input failed: {str(e)}", 
                'results': [],
                'affected_rows': 0
            }

        # Step 5: Wait for Results
        print_step(5, 6, "Waiting for Server Response")
        results = []
        affected_rows = 0
        
        try:
            is_select = final_sql.strip().upper().startswith("SELECT")
            
            if is_select:
                # Wait for table with multiple possible selectors
                table_found = False
                for selector in ["#query-result table", "#column-data table", ".result-table", ".data-table", "table"]:
                    try:
                        WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                        )
                        table_found = True
                        break
                    except:
                        continue
                
                if table_found:
                    print_success("Result table detected")
                else:
                    # Check if there's an error message
                    try:
                        error_element = driver.find_element(By.CSS_SELECTOR, ".error, #error, .alert-danger, .alert-error")
                        error_text = error_element.text
                        if error_text:
                            return {
                                'status': 'error',
                                'message': error_text,
                                'results': [],
                                'affected_rows': 0
                            }
                    except:
                        pass
                    print_warning("Result table not found, but proceeding...")
            else:
                # For UPDATE, INSERT, DELETE - wait for message
                try:
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.ID, "message"))
                    )
                    print_success("Server response received")
                except:
                    print_info("No explicit response message (may be normal for this query)")
                    
        except Exception as e:
            print_warning(f"Timeout waiting for results: {str(e)[:100]}")
            # Check for errors in page source
            try:
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                error_msg = soup.find('div', class_='error') or soup.find('div', id='error')
                if error_msg:
                    return {
                        'status': 'error',
                        'message': error_msg.text.strip(),
                        'results': [],
                        'affected_rows': 0
                    }
            except:
                pass
            
            return {
                'status': 'success', 
                'results': [{'message': 'Query executed (no visible results)'}],
                'affected_rows': 0
            }

        # Step 6: Parse Results
        print_step(6, 6, "Parsing Query Results")
        
        try:
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # Check for affected rows message first
            msg_element = soup.find('div', id='message')
            if msg_element:
                msg_text = msg_element.get_text().strip()
                # Extract affected rows count
                import re
                match = re.search(r'(\d+)\s+row\(s\) affected', msg_text)
                if match:
                    affected_rows = int(match.group(1))
                    print_success(f"Query affected {affected_rows} row(s)")
            
            container = soup.find('div', id='query-result') or soup.find('div', id='column-data')
            table = container.find('table') if container else soup.find('table')

            if table:
                headers = [th.text.strip() for th in table.find_all('th')]
                
                for row in table.find_all('tr')[1:]:
                    cols = row.find_all('td')
                    if len(cols) > 0:
                        row_dict = {}
                        for i in range(len(cols)):
                            if i < len(headers):
                                row_dict[headers[i]] = cols[i].text.strip()
                        results.append(row_dict)
                
                print_success(f"Parsed {len(results)} rows with {len(headers)} columns")
                
                if headers:
                    print_info(f"Columns: {', '.join(headers[:5])}{'...' if len(headers) > 5 else ''}")
                
            elif not msg_element:
                print_warning("No result table or message found in response")
                results = [{'status': 'executed', 'message': 'Query completed'}]

        except Exception as e:
            print_error("Failed to parse results", str(e))
            return {
                'status': 'error', 
                'message': f"Parse error: {str(e)}", 
                'results': [],
                'affected_rows': 0
            }

        # Summary
        print_divider()
        print_success(f"Query execution complete - {len(results)} results returned")
        print_divider("═")
        
        return {
            'status': 'success', 
            'results': results,
            'affected_rows': affected_rows,
            'message': 'Query executed successfully'
        }

    except Exception as e:
        print_error("Critical error during query execution", str(e))
        print_divider()
        traceback.print_exc()
        return {
            'status': 'error', 
            'message': str(e), 
            'results': [],
            'affected_rows': 0
        }
    
# Register signal handler
signal.signal(signal.SIGINT, signal_handler)
