import datetime
import logging
from concurrent.futures import ThreadPoolExecutor

import httpx
# Ensure these imports match your project structure
from core.selenium_automation import refresh_with_selenium 
from core.models import Soldier
from .loggers import get_ui_logger

logger = get_ui_logger()


# Configuration
WEEKEND = [4, 5]  # Friday(4), Saturday(5)
MAX_WORKERS = 4
BASE_URL = "https://one.prat.idf.il"

def _extract_auth_token(local_storage: dict):
    """
    Attempts to find a Bearer token in local storage.
    Common keys: 'token', 'access_token', 'oidc.user', etc.
    """
    if not local_storage:
        return None
        
    # List of potential keys where the token might be hiding
    potential_keys = ['token', 'access_token', 'id_token', 'jwt']
    
    for key in potential_keys:
        if key in local_storage:
            return local_storage[key]
            
    # If the token is nested inside a JSON string (common in OIDC), 
    # you might need deeper parsing logic here.
    return None

def send_report(client: httpx.Client, date_obj: datetime.date) -> dict:
    url = f"{BASE_URL}/api/Attendance/InsertFutureReport"
    date_str = date_obj.strftime("%d.%m.%Y")
    
    payload = {
        'MainCode': '01',
        'SecondaryCode': '01',
        'Note': '',
        'FutureReportDate': date_str
    }
    
    # Note: We rely on the client's default headers for User-Agent/Auth
    # We only add specific headers for this request here.
    request_headers = {
        "Referer": f"{BASE_URL}/secondaries",
        "Origin": BASE_URL,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8" # Explicitly set content type
    }

    result = {
        "date": date_str,
        "success": False,
        "status": 0,
        "message": "",
        "debug": {}
    }

    try:
        response = client.post(url, data=payload, headers=request_headers)
        result["status"] = response.status_code
        
        # Debug info
        try:
            result["debug"]["response_body"] = response.json()
        except:
            result["debug"]["response_body"] = response.text

        if response.status_code == 200:
            # The API usually returns the string "true" or "false"
            is_true = response.text.strip().lower() == 'true'
            
            if is_true:
                logger.info(f"[SUCCESS] Updated date for [{date_str}]")
                result["success"] = True
                result["message"] = "Reported successfully"
            else:
                logger.error(f"[FAIL] API returned false for [{date_str}]")
                result["message"] = "API returned 'false'"
        else:
            logger.error(f"[ERROR] HTTP {response.status_code} for [{date_str}]")
            result["message"] = f"HTTP {response.status_code}"
            
    except Exception as e:
        logger.error(f"[EXCEPTION] {e}")
        result["message"] = str(e)

    return result

def run_attendance_for_user(soldier: Soldier):
    """
    Orchestrates the attendance reporting process.
    Returns: (results_list, boolean_indicating_if_db_was_updated)
    """
    logger.info(f"Running attendance for soldier {soldier.personal_id}")
     
    # --- 1. Calculate Dates ---
    today = datetime.date.today()
    dates_to_report = []
    i = 0
    while len(dates_to_report) < 8:
        d = today + datetime.timedelta(days=i)
        if d.weekday() not in WEEKEND:
            dates_to_report.append(d)
        i += 1

    # --- 2. Selenium Refresh Strategy ---
    # We explicitly pass the current storage state to Selenium
    fresh_data = refresh_with_selenium(
        soldier.cookies, 
        soldier.local_storage, 
        soldier.session_storage
    )

    db_updated = False
    
    # Prepare the active session data
    active_cookies = soldier.cookies
    active_local_storage = soldier.local_storage
    
    if fresh_data:
        logger.info("Selenium refresh successful. Updating Soldier data.")
        
        # Unpack fresh data
        soldier.cookies = fresh_data['cookies']
        soldier.local_storage = fresh_data.get('local_storage', {})
        soldier.session_storage = fresh_data.get('session_storage', {})
        soldier.save()
        
        active_cookies = soldier.cookies
        active_local_storage = soldier.local_storage
        db_updated = True
    else:
        logger.info("Selenium refresh skipped or failed. Using existing DB data.")

    # --- 3. Prepare HTTP Client ---
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Upgrade-Insecure-Requests": "1"
    }

    # If your site uses Bearer tokens in LocalStorage, inject them here:
    token = _extract_auth_token(active_local_storage)
    if token:
        headers["Authorization"] = f"Bearer {token}"
        logger.info("Injecting Authorization token from Local Storage.")

    results = []

    # --- 4. Execute Reports ---
    # We turn off SSL verify because IDF sites often have cert issues, but be careful.
    with httpx.Client(cookies=active_cookies, headers=headers, verify=False, timeout=30.0) as client:
        
        # A. Pre-flight (Lightweight check to ensure session is valid)
        try:
            client.get(f"{BASE_URL}/secondaries")
        except Exception as e:
            logger.info(f"HTTP Client Pre-flight warning: {e}")

        # B. Send Reports Concurrently
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # We map the client and dates to the function
            future_results = executor.map(lambda d: send_report(client, d), dates_to_report)
            results = list(future_results)

        # C. Post-Flight: Check if HTTP calls rotated the cookies
        # Some servers rotate the session cookie on every request.
        new_jar_cookies = {c.name: c.value for c in client.cookies.jar}
        
        # Merge new jar cookies into existing dictionary to keep non-overlapping ones
        if new_jar_cookies:
            updated_cookies = active_cookies.copy()
            # updated_cookies.update(new_jar_cookies)
            
            # Simple check to see if anything actually changed
            if updated_cookies != active_cookies:
                logger.info("Cookies rotated during HTTP requests. Updating DB.")
                soldier.cookies = updated_cookies
                soldier.save()
                db_updated = True

    return results, db_updated