"""In-memory structured log buffer + optional JSON formatter."""

import logging
import json
from collections import deque
from datetime import datetime
from typing import Any, Dict, List

# Reserved LogRecord attributes — anything else on `record.__dict__` is user
# metadata (passed via `logger.info("...", extra={...})`) and gets folded into
# the JSON payload so it survives through to stdout / log shippers.
_RESERVED_LOGRECORD_ATTRS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
}


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record.

    Fields: timestamp (ISO-8601 UTC), level, logger, message, plus any extra
    kwargs attached to the record. Exceptions are serialized as a string block
    under `exc_info` so log shippers can index them.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Fold in user-supplied `extra={...}` fields.
        for k, v in record.__dict__.items():
            if k in _RESERVED_LOGRECORD_ATTRS or k.startswith("_"):
                continue
            try:
                json.dumps(v)  # cheap serializability probe
                payload[k] = v
            except (TypeError, ValueError):
                payload[k] = repr(v)

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


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


def configure_root_logger(level: int, log_format: str = "text") -> None:
    """Configure the root logger's stream handler.

    Default is the existing human-readable format. Pass ``log_format="json"``
    to switch stdout to one JSON document per line — useful for container
    deployments that ship logs to Loki / Elastic / Datadog / etc.

    This is idempotent: repeated calls reconfigure the stream handler in place
    rather than stacking new ones.
    """
    root = logging.getLogger()
    root.setLevel(level)

    # Drop any prior stream handler we attached so level/format changes apply
    # cleanly across reload (e.g. tests, TUI restart). Ring buffer handler is
    # left alone — it's attached separately by setup_log_buffer().
    for h in list(root.handlers):
        if isinstance(h, logging.StreamHandler) and not isinstance(h, RingLogHandler):
            root.removeHandler(h)

    handler = logging.StreamHandler()
    if log_format.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        ))
    root.addHandler(handler)
