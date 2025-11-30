import logging
import threading
from datetime import datetime

# 1. The Custom Handler
class ThreadQueueHandler(logging.Handler):
    """
    Pushes log records to a queue, but only if they originate 
    from the specific worker thread we are monitoring.
    """
    def __init__(self, queue, target_thread_id):
        super().__init__()
        self.queue = queue
        self.target_thread_id = target_thread_id

    def emit(self, record):
        # Filter: Only capture logs from the specific worker thread
        if record.thread == self.target_thread_id:
            try:
                log_entry = {
                    'msg': self.format(record),
                    'level': record.levelname.lower(),
                    'time': datetime.now().strftime("%H:%M:%S")
                }
                self.queue.put(log_entry)
            except Exception:
                self.handleError(record)

# 2. The Getter
def get_ui_logger():
    """
    Returns the shared logger instance. 
    We do NOT add handlers here anymore. Handlers are ephemeral 
    and added/removed dynamically by the view.
    """
    logger = logging.getLogger('ui_logger')
    logger.setLevel(logging.DEBUG)
    
    # Optional: Add a console handler for server-side debugging if empty
    if not logger.handlers:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
        logger.addHandler(console)
        
    return logger