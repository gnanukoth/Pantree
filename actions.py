# Grocery list and throwaway log from inventory expiry.
"""Scan inventory for soon-to-expire and already-expired items; log actions."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import re
from typing import Any, Optional

from pymongo.database import Database

DEDUPE_HOURS = 24


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    return None


def _to_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            day = _to_date(text)
            if day is None:
                return None
            return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _action_when(entry: dict) -> Optional[datetime]:
    return _to_datetime(entry.get("timestamp") or entry.get("created_at"))


def _item_key(item: Any) -> str:
    return str(item or "").strip().lower()


def _has_recent_action(
    db: Database,
    action_type: str,
    item: Any,
    *,
    now: datetime,
    hours: int = DEDUPE_HOURS,
) -> bool:
    """True if action_log already has this *same* type and item within the window.

    Type is required: a recent thrown_away must not block a grocery_added
    (or vice versa) when the item is thrown away and then rebought the same day.
    """
    key = _item_key(item)
    if not key or not action_type:
        return False
    cutoff = now - timedelta(hours=hours)
    query = {
        "type": action_type,
        "item": {"$regex": f"^{re.escape(key)}$", "$options": "i"},
    }
    for entry in db["action_log"].find(query):
        when = _action_when(entry)
        if when is None:
            continue
        if when >= cutoff:
            return True
    return False


def _write_action(
    db: Database,
    *,
    type: str,
    item: str,
    reason: str,
    note: Any = None,
    now: Optional[datetime] = None,
) -> Any:
    ts = now or _utcnow()
    doc = {
        "type": type,
        "item": item,
        "timestamp": ts,
        "reason": reason,
        "note": note,
    }
    result = db["action_log"].insert_one(doc)
    return result.inserted_id


def add_to_grocery_list(
    db: Database,
    item: str,
    reason: str = "ran out — used up",
    *,
    now: Optional[datetime] = None,
) -> bool:
    """Log grocery_added for an item, skipping if one exists within 24 hours.

    Returns True when a new grocery_added row was written.
    """
    ts = now or _utcnow()
    key = _item_key(item)
    if not key:
        return False
    if _has_recent_action(db, "grocery_added", key, now=ts):
        return False
    _write_action(
        db,
        type="grocery_added",
        item=key,
        reason=reason,
        note=None,
        now=ts,
    )
    return True


def _expiry_reason(days: int) -> str:
    if days <= 0:
        return "expires today"
    if days == 1:
        return "expires in 1 day"
    return f"expires in {days} days"


def check_expiring_items(db: Database, days_threshold: int = 2) -> list[str]:
    """Log grocery_added for active items expiring within ``days_threshold`` days.

    Skips items that already have a grocery_added action in the last 24 hours.
    Returns the list of item names newly added.
    """
    now = _utcnow()
    today = now.date()
    horizon = today + timedelta(days=days_threshold)
    added: list[str] = []

    for doc in db["inventory"].find({"status": "active"}):
        exp = _to_date(doc.get("expires_at"))
        if exp is None:
            continue
        if exp < today or exp > horizon:
            continue
        item = _item_key(doc.get("item"))
        if not item:
            continue
        # Dedupe grocery_added only — a same-day thrown_away must not block this.
        if _has_recent_action(db, "grocery_added", item, now=now):
            continue
        days = (exp - today).days
        add_to_grocery_list(db, item, reason=_expiry_reason(days), now=now)
        added.append(item)
    return added


def check_expired_items(db: Database) -> list[str]:
    """Mark past-due active items expired and log thrown_away.

    Skips writing a duplicate thrown_away action within 24 hours, but still
    sets status to expired. Returns item names that were newly logged.
    """
    now = _utcnow()
    today = now.date()
    logged: list[str] = []

    for doc in db["inventory"].find({"status": "active"}):
        exp = _to_date(doc.get("expires_at"))
        if exp is None or exp >= today:
            continue
        item = _item_key(doc.get("item"))
        if not item:
            continue
        db["inventory"].update_one({"_id": doc["_id"]}, {"$set": {"status": "expired"}})
        # Dedupe thrown_away only — a same-day grocery_added must not block this.
        if _has_recent_action(db, "thrown_away", item, now=now):
            continue
        _write_action(
            db,
            type="thrown_away",
            item=item,
            reason="expired unused",
            note=None,
            now=now,
        )
        logged.append(item)
    return logged


def _recent_first(entries: list[dict]) -> list[dict]:
    def sort_key(entry: dict) -> datetime:
        when = _action_when(entry)
        if when is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        return when

    return sorted(entries, key=sort_key, reverse=True)


def get_grocery_list(db: Database) -> list[dict]:
    """Return grocery_added action_log rows, most recent first."""
    return _recent_first(list(db["action_log"].find({"type": "grocery_added"})))


def get_throwaway_log(db: Database) -> list[dict]:
    """Return thrown_away action_log rows, most recent first."""
    return _recent_first(list(db["action_log"].find({"type": "thrown_away"})))
