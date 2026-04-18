"""System-wide alert tracking and broadcasting."""

import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, asdict

@dataclass
class Alert:
    id: str
    level: str  # info, warning, error
    title: str
    message: str
    timestamp: str
    channel: Optional[str] = None
    read: bool = False

logger = logging.getLogger(__name__)

class AlertManager:
    def __init__(self, limit: int = 50):
        self._alerts: List[Alert] = []
        self._limit = limit
        self._subscribers: List[Callable[[Alert], None]] = []

    def add_alert(self, level: str, title: str, message: str, channel: Optional[str] = None):
        alert_id = f"alt_{int(datetime.now().timestamp() * 1000)}"
        alert = Alert(
            id=alert_id,
            level=level,
            title=title,
            message=message,
            timestamp=datetime.now().isoformat(),
            channel=channel
        )
        self._alerts.insert(0, alert)
        if len(self._alerts) > self._limit:
            self._alerts.pop()
        
        for sub in self._subscribers:
            try:
                sub(alert)
            except Exception:
                pass
        
        if level == "error":
            logger.error(f"ALERT [{title}]: {message}")
        elif level == "warning":
            logger.warning(f"ALERT [{title}]: {message}")

    def list_alerts(self, unread_only: bool = False) -> List[Dict[str, Any]]:
        if unread_only:
            return [asdict(a) for a in self._alerts if not a.read]
        return [asdict(a) for a in self._alerts]

    def mark_read(self, alert_id: Optional[str] = None):
        if alert_id:
            for a in self._alerts:
                if a.id == alert_id:
                    a.read = True
                    break
        else:
            for a in self._alerts:
                a.read = True

    def subscribe(self, callback: Callable[[Alert], None]):
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[Alert], None]):
        if callback in self._subscribers:
            self._subscribers.remove(callback)

# Global instances
alert_manager = AlertManager()
