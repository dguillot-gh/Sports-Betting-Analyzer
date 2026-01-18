"""
In-memory log capture for the Python API.
Add this endpoint to app.py to expose logs via API.
"""
import logging
from collections import deque
from datetime import datetime
from typing import List, Dict, Any

# In-memory log buffer (last 500 entries)
LOG_BUFFER: deque = deque(maxlen=500)


class BufferHandler(logging.Handler):
    """Custom logging handler that stores logs in memory."""
    
    def emit(self, record):
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname.lower(),
            "message": self.format(record),
            "logger": record.name
        }
        LOG_BUFFER.append(log_entry)


def setup_log_capture():
    """Set up the log capture handler on the root logger."""
    handler = BufferHandler()
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(name)s: %(message)s')
    handler.setFormatter(formatter)
    
    # Add to root logger to capture all logs
    logging.getLogger().addHandler(handler)
    
    return handler


def get_logs(level: str = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Get logs from the buffer, optionally filtered by level."""
    logs = list(LOG_BUFFER)
    
    if level and level != "all":
        logs = [l for l in logs if l["level"] == level.lower()]
    
    # Return most recent first
    return list(reversed(logs))[:limit]


# FastAPI endpoint code to add to app.py:
"""
# Add this import at top of app.py:
from log_capture import setup_log_capture, get_logs, LOG_BUFFER

# Call this after app is created:
setup_log_capture()

# Add this endpoint:
@app.get('/logs')
def get_system_logs(level: str = None, limit: int = 100):
    '''Get recent system logs.'''
    logs = get_logs(level, limit)
    return {
        "logs": logs,
        "total": len(LOG_BUFFER),
        "showing": len(logs)
    }
"""
