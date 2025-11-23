import calendar
from datetime import datetime
from http.cookies import SimpleCookie
import re
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
import urllib
from .models import Soldier
from .services import run_attendance_for_user
import json

def login_view(request):
    """Entry point: Ask for ID only."""
    if request.method == "POST":
        pid = request.POST.get("personal_id")
        if pid:
            # Get or Create the user
            soldier, created = Soldier.objects.get_or_create(personal_id=pid)
            # Set simple session variable
            request.session['user_id'] = soldier.id
            return redirect('dashboard')
    return render(request, 'login.html')

def dashboard(request):
    """Main UI."""
    if 'user_id' not in request.session:
        return redirect('login')
    
    soldier = Soldier.objects.get(id=request.session['user_id'])
    
    has_cookies = bool(soldier.cookies)
    
    context = {
        'soldier': soldier,
        'has_cookies': has_cookies
    }
    return render(request, 'dashboard.html', context)


def execute_report(request):
    # Note: We need to handle DB access carefully in async views
    
    if 'user_id' not in request.session:
        return redirect('login')
        
    # get_soldier = sync_to_async(Soldier.objects.get)
    soldier = Soldier.objects.get(id=request.session['user_id'])
    
    if not soldier.cookies:
        messages.error(request, "No cookies found. Please update cookies first.")
        return redirect('dashboard')

    results, cookie_updated = run_attendance_for_user(soldier)

    for res in results:
        # Parse "DD.MM.YYYY" to a real datetime object
        res['dt'] = datetime.strptime(res['date'], "%d.%m.%Y").date()
    
    # Sort by the real date object (Ascending)
    results.sort(key=lambda x: x['dt'])

    for res in results:
        res['json_str'] = json.dumps(res, default=str)

    # 3. Prepare Calendar Data
    # We want to display the month(s) involved in the results
    if results:
        start_date = results[0]['dt']
        end_date = results[-1]['dt']
        
        # Identify unique (year, month) pairs involved
        years_months = []
        curr = start_date.replace(day=1)
        while curr <= end_date:
            years_months.append((curr.year, curr.month))
            # Move to next month
            if curr.month == 12:
                curr = curr.replace(year=curr.year + 1, month=1)
            else:
                curr = curr.replace(month=curr.month + 1)
        
        # Create a lookup dictionary for results: { date_obj: result_dict }
        results_map = {r['dt']: r for r in results}
        
        calendar.setfirstweekday(6) # Sunday start
        cal_data = []

        for y, m in years_months:
            month_matrix = calendar.monthcalendar(y, m)
            month_weeks = []
            
            for week in month_matrix:
                week_days = []
                for day_num in week:
                    if day_num == 0:
                        week_days.append(None) # Empty day
                    else:
                        this_date = datetime(y, m, day_num).date()
                        # Check if we have a report for this day
                        status = results_map.get(this_date)
                        
                        week_days.append({
                            'day': day_num,
                            'full_date': this_date,
                            'is_today': this_date == datetime.now().date(),
                            'result': status # Will be None if no report for this day
                        })
                month_weeks.append(week_days)
            
            cal_data.append({
                'name': calendar.month_name[m],
                'year': y,
                'weeks': month_weeks
            })
    else:
        cal_data = []

    context = {
        'results': results,
        'calendars': cal_data,
        'cookie_updated': cookie_updated # <-- Passed to template
    }
    
    return render(request, 'results.html', context)    
    # return render(request, 'results.html', {'results': results})
    
def logout_view(request):
    request.session.flush()
    return redirect('login')


def parse_curl_cookies(curl_command):
    """
    Extracts cookies from a cURL command string.
    Supports -H 'Cookie: ...' AND -b '...' formats.
    """
    cookies = {}
    
    # PATTERN 1: Look for -H "Cookie: ..."
    header_match = re.search(r'[\'"]Cookie:\s?(.+?)[\'"]', curl_command, re.IGNORECASE)
    if header_match:
        raw_cookie = header_match.group(1)
    
    else:
        # PATTERN 2: Look for -b '...' or --cookie '...'
        # This matches -b followed by quotes, capturing everything inside
        cookie_flag_match = re.search(r'(?:-b|--cookie)\s+[\'"](.+?)[\'"]', curl_command, re.IGNORECASE)
        if cookie_flag_match:
            raw_cookie = cookie_flag_match.group(1)
        else:
            return {}

    # Parse the found string
    try:
        parser = SimpleCookie()
        parser.load(raw_cookie)
        for key, morsel in parser.items():
            cookies[key] = morsel.value
    except Exception:
        pass
            
    return cookies


def update_cookies(request):
    """
    Accepts JSON, Raw Cookie String, or cURL command.
    """
    if request.method == "POST":
        raw_data = request.POST.get("cookie_json", "").strip()
        soldier = Soldier.objects.get(id=request.session['user_id'])
        
        final_cookies = {}
        
        # STRATEGY 1: Is it a cURL command? (The best way)
        if "curl " in raw_data.lower() and "cookie" in raw_data.lower():
            final_cookies = parse_curl_cookies(raw_data)
            if not final_cookies:
                messages.error(request, "Detected cURL but couldn't find Cookie header.")

        # STRATEGY 2: Is it JSON?
        elif raw_data.startswith("{") or raw_data.startswith("["):
            try:
                json_data = json.loads(raw_data)
                if isinstance(json_data, list):
                    for c in json_data:
                        final_cookies[c['name']] = c['value']
                else:
                    final_cookies = json_data
            except:
                pass

        # STRATEGY 3: Is it a raw string (key=value; key2=val)?
        if not final_cookies:
            try:
                cookie_parser = SimpleCookie()
                cookie_parser.load(raw_data)
                for key, morsel in cookie_parser.items():
                    final_cookies[key] = morsel.value
            except:
                pass

        if final_cookies:
            # Check for the specific cookie we need
            if 'AppCookie' in final_cookies:
                soldier.cookies = final_cookies
                soldier.save()
                messages.success(request, f"Success! Connected via cURL. (Expires: 2025)")
            else:
                soldier.cookies = final_cookies
                soldier.save()
                messages.warning(request, "Cookies saved, but 'AppCookie' was missing. It might not work.")
        else:
            messages.error(request, "Could not understand the input. Please try 'Copy as cURL'.")
            
    return redirect('dashboard')