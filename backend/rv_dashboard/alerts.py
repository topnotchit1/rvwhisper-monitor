from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser


class AlertParseError(ValueError):
    pass


@dataclass(frozen=True)
class ActiveAlert:
    fingerprint: str
    title: str
    acknowledged: bool
    created_at: str | None


class _AlertListParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.saw_alert_view = False
        self._view_depth = 0
        self._current_classes: set[str] | None = None
        self._current_text: list[str] = []
        self.rows: list[tuple[set[str], str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "div":
            if values.get("id") == "view-alerts":
                self.saw_alert_view = True
                self._view_depth = 1
            elif self._view_depth:
                self._view_depth += 1
        if tag == "li" and self._view_depth and self._current_classes is None:
            self._current_classes = set((values.get("class") or "").split())
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_classes is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "li" and self._current_classes is not None:
            text = " ".join(" ".join(self._current_text).split())
            self.rows.append((self._current_classes, text))
            self._current_classes = None
            self._current_text = []
        if tag == "div" and self._view_depth:
            self._view_depth -= 1


def _created_at(raw: str | None) -> str | None:
    if not raw:
        return None
    for pattern in ("%B %d, %Y %I:%M%p", "%b %d, %Y %I:%M%p"):
        try:
            return datetime.strptime(raw.strip(), pattern).isoformat()
        except ValueError:
            pass
    return raw.strip()


def parse_active_alerts(html: str) -> list[ActiveAlert]:
    """Parse the two read-only active-alert groups from RV Whisper.

    RV Whisper keeps acknowledged alerts active until their trigger condition
    clears. Both acknowledged and unacknowledged rows are therefore returned.
    """
    parser = _AlertListParser()
    parser.feed(html)
    if not parser.saw_alert_view:
        raise AlertParseError("RV Whisper alert list was not present")

    alerts: list[ActiveAlert] = []
    for classes, text in parser.rows:
        title_match = re.search(r"\bAlert:\s*(.+?)(?:\s*-\s*ACKNOWLEDGED|\s+Created:|$)", text, re.IGNORECASE)
        if not title_match:
            continue
        title = title_match.group(1).strip()
        created_match = re.search(r"\bCreated:\s*(.+?)\s+by\b", text, re.IGNORECASE)
        created_at = _created_at(created_match.group(1) if created_match else None)
        acknowledged = "acknowledged-alert" in classes or bool(re.search(r"\bACKNOWLEDGED\b", text, re.IGNORECASE))
        key = hashlib.sha256(f"{title.casefold()}|{created_at or ''}".encode()).hexdigest()[:24]
        alerts.append(ActiveAlert(key, title, acknowledged, created_at))
    return alerts
