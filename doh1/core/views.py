import calendar
import json
import time
import re
import urllib
from datetime import datetime, date
from http.cookies import SimpleCookie

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import StreamingHttpResponse
from django.template.loader import render_to_string

from .models import Soldier
from .services import run_attendance_for_user

# ---------------------------------------------------------
# AUTHENTICATION & DASHBOARD
# ---------------------------------------------------------

def login_view(request):
    """Entry point: Ask for ID only."""
    if request.method == "POST":
        pid = request.POST.get("personal_id")
        if pid:
            soldier, created = Soldier.objects.get_or_create(personal_id=pid)
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

def logout_view(request):
    request.session.flush()
    return redirect('login')

# ---------------------------------------------------------
# COOKIE MANAGEMENT
# ---------------------------------------------------------

def update_cookies(request):
    if request.method == "POST":
        soldier = Soldier.objects.get(id=request.session['user_id'])
        final_cookies = {}
        final_local = {}
        final_session = {}
        
        # --- METHOD 1: File Upload ---
        if 'cookie_file' in request.FILES:
            try:
                uploaded_file = request.FILES['cookie_file']
                file_content = uploaded_file.read().decode('utf-8')
                json_data = json.loads(file_content)
                
                if isinstance(json_data, dict) and "cookies" in json_data:
                    if isinstance(json_data["cookies"], list):
                        for c in json_data["cookies"]:
                            final_cookies[c['name']] = c['value']
                    if "localStorage" in json_data:
                        final_local = json_data["localStorage"]
                    if "sessionStorage" in json_data:
                        final_session = json_data["sessionStorage"]
                elif isinstance(json_data, list):
                    for c in json_data:
                        final_cookies[c['name']] = c['value']
                elif isinstance(json_data, dict):
                    final_cookies = json_data
                    
                messages.success(request, f"Imported state! Cookies: {len(final_cookies)}")
            except Exception as e:
                messages.error(request, f"File error: {str(e)}")
                return redirect('dashboard')

        # --- METHOD 2: Text Paste ---
        elif 'cookie_json' in request.POST:
            raw_data = request.POST.get("cookie_json", "").strip()
            
            if raw_data.startswith("{") or raw_data.startswith("["):
                try:
                    json_data = json.loads(raw_data)
                    if isinstance(json_data, dict) and "cookies" in json_data:
                         for c in json_data["cookies"]:
                            final_cookies[c['name']] = c['value']
                         final_local = json_data.get("localStorage", {})
                         final_session = json_data.get("sessionStorage", {})
                    elif isinstance(json_data, list):
                        for c in json_data:
                            final_cookies[c['name']] = c['value']
                    else:
                        final_cookies = json_data
                except:
                    pass
            
            if not final_cookies and raw_data:
                try:
                    cookie_parser = SimpleCookie()
                    cookie_parser.load(raw_data)
                    for key, morsel in cookie_parser.items():
                        final_cookies[key] = morsel.value
                except:
                    pass

        if final_cookies:
            soldier.cookies = final_cookies
            soldier.local_storage = final_local
            soldier.session_storage = final_session
            soldier.save()
            if 'cookie_file' not in request.FILES:
                messages.success(request, "Session state updated successfully!")
        else:
            messages.warning(request, "No valid data found.")
            
    return redirect('dashboard')

# ---------------------------------------------------------
# STREAMING REPORT LOGIC
# ---------------------------------------------------------

def execute_report(request):
    if 'user_id' not in request.session:
        return redirect('login')
    
    response = StreamingHttpResponse(
        stream_generator(request), 
        content_type='text/html'
    )
    response['Cache-Control'] = 'no-cache'
    return response


def stream_generator(request):
    yield render_to_string('loading_terminal.html')
    
    def log(message, status="info"):
        color = "text-slate-300"
        if status == "success": color = "text-green-400"
        elif status == "error": color = "text-red-400"
        elif status == "warning": color = "text-yellow-400"
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        return f"""
        <script>
            addLog('<span class="{color}">[{timestamp}]</span> {message}');
        </script>
        """

    try:
        yield log("Initializing user session...", "info")
        soldier = Soldier.objects.get(id=request.session['user_id'])
        
        if not soldier.cookies:
            yield log("Error: No cookies found.", "error")
            time.sleep(1.5)
            yield "<script>window.location.href = '/dashboard/';</script>"
            return

        yield log(f"User identified: {soldier.personal_id}", "success")
        yield log("Starting Selenium engine...", "warning")
        
        # Run logic
        results, cookie_updated = run_attendance_for_user(soldier)
        
        yield log("Automation finished. Processing results...", "info")

        if cookie_updated:
            yield log("Session rotated. Cookies updated in database.", "success")
            request.session['cookie_updated_flag'] = True

        # Sanitize data for session storage
        processed_results = []
        for res in results:
            clean_res = res.copy()
            # Ensure date is string
            if 'date' in clean_res and isinstance(clean_res['date'], (date, datetime)):
                clean_res['date'] = clean_res['date'].strftime("%d.%m.%Y")
            # Remove any non-serializable keys
            if 'dt' in clean_res: 
                del clean_res['dt']
            processed_results.append(clean_res)
            
        request.session['report_results'] = processed_results
        request.session.save()
        
        yield log("Generating calendar...", "info")
        time.sleep(0.5) 
        
        yield log("Done! Redirecting...", "success")
        yield "<script>window.location.href = '/report/view/';</script>"

    except Exception as e:
        print(f"Streaming Error: {e}")
        yield log(f"Critical Error: {str(e)}", "error")


def view_report_results(request):
    if 'user_id' not in request.session:
        return redirect('login')

    raw_results = request.session.get('report_results', [])
    results = [r.copy() for r in raw_results]

    cookie_updated = request.session.pop('cookie_updated_flag', False)
    
    # 2. Process Results (Date Parsing & Sorting)
    for res in results:
        if 'date' in res and res['date']:
            try:
                res['dt'] = datetime.strptime(res['date'], "%d.%m.%Y").date()
            except (ValueError, TypeError):
                res['dt'] = datetime.now().date()
        else:
            res['dt'] = datetime.now().date()
    
    results.sort(key=lambda x: x.get('dt', datetime.max.date()))

    for res in results:
        res['json_str'] = json.dumps(res, default=str)

    # 3. Calendar Logic
    cal_data = []
    
    if results:
        start_date = results[0]['dt']
        end_date = results[-1]['dt']
        
        years_months = []
        curr = start_date.replace(day=1)
        
        while curr <= end_date:
            years_months.append((curr.year, curr.month))
            if curr.month == 12:
                curr = curr.replace(year=curr.year + 1, month=1)
            else:
                curr = curr.replace(month=curr.month + 1)
        
        results_map = {r['dt']: r for r in results}
        
        calendar.setfirstweekday(6) # Sunday start

        for y, m in years_months:
            month_matrix = calendar.monthcalendar(y, m)
            month_weeks = []
            
            for week in month_matrix:
                week_days = []
                for day_num in week:
                    if day_num == 0:
                        week_days.append(None)
                    else:
                        this_date = date(y, m, day_num)
                        status = results_map.get(this_date)
                        
                        week_days.append({
                            'day': day_num,
                            'full_date': this_date,
                            'is_today': this_date == date.today(),
                            'result': status
                        })
                month_weeks.append(week_days)
            
            cal_data.append({
                'name': calendar.month_name[m],
                'year': y,
                'weeks': month_weeks
            })

    context = {
        'results': results,
        'calendars': cal_data,
        'cookie_updated': cookie_updated 
    }
    
    return render(request, 'results.html', context)