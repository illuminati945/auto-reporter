import re
import time
import logging
from typing import Dict, Optional, Any
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# --- Constants ---
TARGET_URL = "https://one.prat.idf.il/"
WAF_WAIT_TIME = 5
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/115.0.0.0 Safari/537.36"
)

def _setup_driver() -> webdriver.Chrome:
    """Configures and initializes the Headless Chrome driver."""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument(f"user-agent={USER_AGENT}")

    service = None
    try:
        from selenium.webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
    except ImportError:
        service = Service()
    
    return webdriver.Chrome(service=service, options=options)

def _inject_cookies(driver: webdriver.Chrome, cookies: Dict[str, str]) -> None:
    """Injects cookies into the browser."""
    if not cookies:
        return
    print(f"Injecting {len(cookies)} cookies...", flush=True)
    for name, value in cookies.items():
        try:
            driver.add_cookie({
                'name': name, 'value': value, 'path': '/', 'secure': True
            })
        except Exception as e:
            print(f"Warning: Failed to inject cookie '{name}': {e}")

def _inject_storage(driver: webdriver.Chrome, data: Dict[str, str], storage_type: str) -> None:
    """
    Injects data into localStorage or sessionStorage using JS.
    storage_type must be 'localStorage' or 'sessionStorage'.
    """
    if not data:
        return
        
    print(f"Injecting {len(data)} items into {storage_type}...", flush=True)
    try:
        # We use execute_script with arguments to safely handle quotes/special chars
        for key, value in data.items():
            driver.execute_script(
                f"window.{storage_type}.setItem(arguments[0], arguments[1]);", 
                key, 
                value
            )
    except Exception as e:
        print(f"Warning: Failed to inject {storage_type}: {e}")

def _get_storage_data(driver: webdriver.Chrome, storage_type: str) -> Dict[str, str]:
    """Extracts all data from localStorage or sessionStorage."""
    try:
        return driver.execute_script(f"return {{...window.{storage_type}}};")
    except Exception as e:
        print(f"Warning: Could not retrieve {storage_type}: {e}")
        return {}

def refresh_with_selenium(
    cookies: Dict[str, str], 
    local_storage: Optional[Dict[str, str]] = None, 
    session_storage: Optional[Dict[str, str]] = None
) -> Optional[Dict[str, Any]]:
    """
    Restores Cookies, LocalStorage, and SessionStorage, visits the site,
    and returns the fresh (potentially updated) session data.
    """
    print("Starting Selenium Preflight...", flush=True)
    driver = None
    
    try:
        driver = _setup_driver()
        
        # 1. Navigate to domain (Required for Same-Origin Policy)
        print(f"Navigating to {TARGET_URL}...")
        driver.get(TARGET_URL)
        
        # 2. Inject state (Cookies + Storage)
        _inject_cookies(driver, cookies)
        _inject_storage(driver, local_storage or {}, "localStorage")
        _inject_storage(driver, session_storage or {}, "sessionStorage")
        
        # 3. Refresh to force the app to load using the injected data
        print("Refreshing page to trigger app load with injected state...")
        driver.refresh()
        
        # 4. Wait for App Load / WAF
        time.sleep(WAF_WAIT_TIME)
        
        # 5. Validation Check
        current_url = driver.current_url.lower()
        if "login" in current_url or "signin" in current_url:
            print("Refresh Failed: Redirected to login page.")
            return None

        # 6. Harvest Fresh Data
        fresh_data = {
            'cookies': {c['name']: c['value'] for c in driver.get_cookies()},
            'local_storage': _get_storage_data(driver, "localStorage"),
            'session_storage': _get_storage_data(driver, "sessionStorage")
        }
        

        fresh_data['cookies'] = clean_cookies(fresh_data['cookies'])
        fresh_data['session_storage'] = clean_cookies(fresh_data['session_storage'])
        
        print(f"Success. Captured {len(fresh_data['cookies'])} Cookies.")

        return fresh_data

    except Exception as e:
        print(f"Selenium Error: {e}")
        return None
    finally:
        if driver:
            driver.quit()


def clean_cookies(cookie_dict: dict) -> dict:
    """
    Removes tracking cookies and aggressive MSAL/Azure AD temporary artifacts.
    """
    clean_dict = {}
    
    # 1. Standard Junk (Analytics/Ads)
    junk_prefixes = (
        '_ga', '_gid', '_gat', 'amp_', '_fbp', 
        'ai_', 'ai_user', 'ai_session', 
        'hj', '_hj', 'intercom', 'ut', '_gcl'
    )

    # 2. MSAL (Microsoft Auth) Transient Tokens
    # These contain UUIDs in the key name and are only needed DURING the handshake.
    # Examples: 
    # msal.{uuid}.nonce.id_token.{uuid}
    # msal.{uuid}.request.state.{uuid}
    # msal.{uuid}.authority.{uuid}
    msal_transient_pattern = re.compile(r'msal\..*\.(nonce|state|request|authority|credential)\.')

    for name, value in cookie_dict.items():
        name_lower = name.lower()

        # Check standard junk
        if any(name_lower.startswith(p) for p in junk_prefixes):
            continue
            
        # Check specific matches
        if name in ['cookie_consent', 'OptanonConsent']:
            continue

        # Check MSAL Transient Artifacts
        if msal_transient_pattern.search(name_lower):
            # We skip these. They are "use-once" tokens for the login flow.
            # The actual session is held in 'AppCookie' or the main 'id_token' without the 'nonce' part.
            continue
            
        clean_dict[name] = value
        
    return clean_dict