import calendar
import json
import queue
import threading
import time
import re
import urllib
from datetime import datetime, date
from http.cookies import SimpleCookie

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import StreamingHttpResponse
from django.template.loader import render_to_string

from core.loggers import ThreadQueueHandler, get_ui_logger

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
    response['X-Accel-Buffering'] = 'no'
    return response

def stream_generator(request):
    # 1. Render Loading Screen
    yield render_to_string('loading_terminal.html')

    # Helper for JS
    def format_log(log_entry):
        # 1. Determine Color
        color_class = "text-slate-300"
        if log_entry['level'] == 'success': color_class = "text-emerald-400"
        elif log_entry['level'] == 'error': color_class = "text-red-400"
        elif log_entry['level'] == 'warning': color_class = "text-amber-400"
        
        # 2. Escape content
        timestamp = log_entry['time']
        msg_content = str(log_entry['msg']).replace("'", "\\'") # Escape single quotes for JS
        
        # 3. Build HTML String (Pure Python)
        html_payload = (
            f'<li class="flex space-x-3 group animate-fade-in-up">'
            f'<span class="text-slate-600 flex-shrink-0 select-none w-16 font-mono">{timestamp}</span>'
            f'<div class="{color_class} flex-1 break-words font-mono">{msg_content}</div>'
            f'</li>'
        )
        
        # 4. Return simple JS call
        return f"<script>addLog('{html_payload}');</script>"

    # 2. Setup
    log_queue = queue.Queue()
    results_container = {}
    captured_logs_history = []
    
    # Get ID of the current (Main) thread so we can capture its logs too
    main_thread_id = threading.get_ident()

    # Worker Function
    def worker(soldier_obj):
        try:
            res, updated = run_attendance_for_user(soldier_obj)
            results_container['data'] = (res, updated)
        except Exception as e:
            results_container['error'] = e

    # Acquire Logger
    logger = get_ui_logger()
    handler = None

    try:
        # Initial Log (Manually yielded because handler isn't attached yet)
        start_msg = {'time': datetime.now().strftime("%H:%M:%S"), 'level': 'info', 'msg': 'Initializing...'}
        yield format_log(start_msg)
        captured_logs_history.append(start_msg)

        soldier = Soldier.objects.get(id=request.session['user_id'])
        if not soldier.cookies:
            # ... Error handling ...
            return

        # --- START THREAD ---
        t = threading.Thread(target=worker, args=(soldier,))
        t.start()
        
        # --- ATTACH HANDLER (Monitor Worker AND Main Thread) ---
        # We pass a LIST of thread IDs: [Main, Worker]
        handler = ThreadQueueHandler(log_queue)
        logger.addHandler(handler)

        # Now we can use standard logger in the Main Thread too!
        logger.warning("Background worker started.")

        # --- LOOP 1: WAIT FOR WORKER ---
        while t.is_alive() or not log_queue.empty():
            try:
                log_entry = log_queue.get(timeout=1.0)
                
                captured_logs_history.append(log_entry)
                yield format_log(log_entry)

            except queue.Empty:
                yield " "
                
        if 'error' in results_container:
            raise results_container['error']
        
        results, cookie_updated = results_container.get('data', ([], False))

        if cookie_updated:
            logger.info("Session cookies successfully rotated.")
            request.session['cookie_updated_flag'] = True

        logger.info(f"Processing {len(results)} days of attendance data...")
        
        # Sanitize Results
        processed_results = []
        for res in results:
            clean_res = res.copy()
            if 'date' in clean_res and isinstance(clean_res['date'], (date, datetime)):
                clean_res['date'] = clean_res['date'].strftime("%d.%m.%Y")
            if 'dt' in clean_res: del clean_res['dt']
            processed_results.append(clean_res)

        request.session['report_results'] = processed_results
        
        logger.info("Saving session state...")
        
        # --- SAVE LOGS TO SESSION ---
        # We need to grab whatever is currently in the queue to add to history
        while not log_queue.empty():
            log_entry = log_queue.get()
            captured_logs_history.append(log_entry)
            yield format_log(log_entry)
            
        request.session['execution_logs'] = captured_logs_history
        request.session.save()

        # Final Log
        logger.info("All tasks complete. Redirecting...")

        # --- LOOP 2: FLUSH REMAINING LOGS ---
        # Catch the logs we just generated ("Saving session", "Redirecting")
        while not log_queue.empty():
            log_entry = log_queue.get()
            # We don't append to session history here because session is already saved,
            # but we yield them to the screen so the user sees them.
            yield format_log(log_entry)

        # --- CLEANUP ---
        logger.removeHandler(handler)
        
        # Redirect
        yield "<script>transitionToResults();</script>"
        
        # 2. Wait slightly for the CSS transition (700ms) to mostly finish
        time.sleep(1) 
        
        # 3. Redirect
        yield "<script>window.location.href = '/report/view/';</script>"
    except Exception as e:
        if handler: logger.removeHandler(handler)
        print(f"Stream Error: {e}")
        err_msg = {'time': datetime.now().strftime("%H:%M:%S"), 'level': 'error', 'msg': f"Error: {str(e)}"}
        yield format_log(err_msg)
        yield "<script>window.location.href = '/report/view/';</script>"

def view_report_results(request):
    if 'user_id' not in request.session:
        return redirect('login')

    raw_results = request.session.get('report_results', [])
    results = [r.copy() for r in raw_results]

    cookie_updated = request.session.pop('cookie_updated_flag', False)

    execution_logs = request.session.get('execution_logs', [])
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
        'cookie_updated': cookie_updated ,
        'execution_logs': execution_logs
    }
    
    return render(request, 'results.html', context)