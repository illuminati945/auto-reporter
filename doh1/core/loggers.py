import logging
import queue
from datetime import datetime

class ThreadQueueHandler(logging.Handler):
    """
    Pushes log records to a queue.
    If allowed_thread_ids is None, it captures logs from ALL threads (Promiscuous Mode).
    """
    def __init__(self, log_queue, allowed_thread_ids=None):
        super().__init__()
        self.log_queue = log_queue
        
        if allowed_thread_ids:
            # Convert to set for O(1) lookups
            self.allowed_thread_ids = set(allowed_thread_ids) if isinstance(allowed_thread_ids, (list, tuple)) else {allowed_thread_ids}
        else:
            self.allowed_thread_ids = None

    def emit(self, record):
        # Capture if (Mode is Promiscuous) OR (Thread is explicitly allowed)
        if self.allowed_thread_ids is None or record.thread in self.allowed_thread_ids:
            try:
                log_entry = {
                    'msg': self.format(record),
                    'level': record.levelname.lower(),
                    'time': datetime.now().strftime("%H:%M:%S")
                }
                self.log_queue.put(log_entry)
            except Exception:
                self.handleError(record)

# get_ui_logger function remains the same...
def get_ui_logger():
    logger = logging.getLogger('ui_logger')
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
        logger.addHandler(console)
    return logger