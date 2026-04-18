"""In-memory structured log buffer."""

import logging
import json
from collections import deque
from datetime import datetime
from typing import Any, Dict, List

class RingLogHandler(logging.Handler):
    """A logging handler that stores recent logs in memory and supports active subscribers."""
    
    def __init__(self, maxlen: int = 1000):
        super().__init__()
        self.maxlen = maxlen
        self.buffer = deque(maxlen=maxlen)
        self.subscribers = []
        
    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            entry = {
                "timestamp": datetime.fromtimestamp(record.created).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": msg,
                "msg_raw": record.getMessage()
            }
            self.buffer.append(entry)
            
            # Notify subscribers
            dead = []
            for sub in self.subscribers:
                try:
                    sub(entry)
                except Exception:
                    dead.append(sub)
            for d in dead:
                self.subscribers.remove(d)
                
        except Exception:
            self.handleError(record)

    def get_logs(self, level: str = None, since: str = None, q: str = None, limit: int = 200) -> List[Dict[str, Any]]:
        """Query buffered logs."""
        results = []
        # Support basic level hierarchy filtering
        levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
        min_level = levels.get(level.upper()) if level else 0
        
        q_lower = q.lower() if q else None
        
        for entry in list(self.buffer):
            # filter level
            if min_level and levels.get(entry["level"], 0) < min_level:
                continue
            # filter since
            if since and entry["timestamp"] < since:
                continue
            # filter text
            if q_lower and q_lower not in entry["message"].lower() and q_lower not in entry["logger"].lower():
                continue
                
            results.append(entry)
            
        return results[-limit:]

# Global buffer singleton
log_buffer = RingLogHandler(maxlen=2000)

def setup_log_buffer():
    """Attach the ring buffer to the root logger."""
    formatter = logging.Formatter("%(message)s")
    log_buffer.setFormatter(formatter)
    logging.getLogger().addHandler(log_buffer)
