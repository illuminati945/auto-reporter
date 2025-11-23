from concurrent.futures import ThreadPoolExecutor
import datetime
import httpx
import time
import asyncio
from core.models import Soldier

WEEKEND = [4, 5]  # Friday(4), Saturday(5)

def send_report(client, date_obj):
    url = "https://one.prat.idf.il/api/Attendance/InsertFutureReport"
    date_str = date_obj.strftime("%d.%m.%Y")
    
    payload = {
        'MainCode': '01',
        'SecondaryCode': '01',
        'Note': '',
        'FutureReportDate': date_str
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://one.prat.idf.il/secondaries",
        "Origin": "https://one.prat.idf.il"
    }

    result = {
        "date": date_str,
        "success": False,
        "status": 0,
        "message": "",
        "debug": {
            "url": url,
            "payload": payload,
            "response_body": None
        }
    }

    try:
        response = client.post(url, data=payload, headers=headers)
        result["status"] = response.status_code
        
        try:
            result["debug"]["response_body"] = response.json()
            result["debug"]["content"] = response.content
        except:
            result["debug"]["response_body"] = response.text

        if response.status_code == 200:
            result["success"] = response.text == 'true'
            result["message"] = response.content
        else:
            result["message"] = f"HTTP {response.status_code}"
            
    except Exception as e:
        result["message"] = str(e)
        result["debug"]["response_body"] = "Connection Error"

    return result

def run_attendance_for_user(soldier: Soldier, max_workers: int = 4) -> tuple:
    """
    Returns: (results_list, cookie_updated_boolean)
    """
    today = datetime.date.today()
    dates_to_report = []
    
    i = 0
    while len(dates_to_report) < 8:
        d = today + datetime.timedelta(days=i)
        if d.weekday() not in WEEKEND:
            dates_to_report.append(d)
        i += 1
        
    original_cookies = soldier.cookies
    results = []
    cookie_updated = False

    # Use the client for the entire session
    with httpx.Client(cookies=original_cookies, verify=False, timeout=30.0) as client:
        
        # --- STEP 1: THE "PRE-FLIGHT" REFRESH ---
        print("Performing pre-flight refresh (Visiting Homepage)...")
        try:
            refresh_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Upgrade-Insecure-Requests": "1"
            }
            client.get("https://one.prat.idf.il/secondaries", headers=refresh_headers)
            print("Pre-flight complete.")
        except Exception as e:
            print(f"Pre-flight warning: {e}")

        # --- STEP 2: SEND REPORTS ---
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_results = executor.map(lambda d: send_report(client, d), dates_to_report)
            results = list(future_results)
            
            # --- STEP 3: SAVE NEW COOKIES ---
            new_cookies = {}
            try:
                for cookie in client.cookies.jar:
                    new_cookies[cookie.name] = cookie.value
            except Exception:
                pass

            if new_cookies and new_cookies != original_cookies:
                print(f"DETECTED COOKIE CHANGE. Updating database...")
                soldier.cookies = new_cookies
                soldier.save()
                cookie_updated = True # Flag as true
            else:
                print("Cookies are unchanged.")

    return results, cookie_updated