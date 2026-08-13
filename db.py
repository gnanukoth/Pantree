# TODO: MongoDB connection helpers
"""MongoDB connection and collection helpers for Pantree."""

from datetime import datetime, timezone
from typing import Any, Optional

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.database import Database
import os

load_dotenv()

_client: Optional[MongoClient] = None

DEFAULT_DB_NAME = os.getenv("MONGODB_DB", "pantree")


def get_client() -> MongoClient:
    """Return a shared MongoClient, creating it on first use."""
    global _client
    if _client is None:
        uri = os.getenv("MONGODB_URI")
        if not uri:
            raise ValueError("MONGODB_URI is not set in the environment")
        _client = MongoClient(uri)
    return _client


def get_db(name: Optional[str] = None) -> Database:
    """Return the Pantree database (default: pantree, overridable via MONGODB_DB)."""
    return get_client()[name or DEFAULT_DB_NAME]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- inventory ---

def _item_unit_keys(item: str, unit: Any) -> tuple[str, str]:
    item_key = str(item).strip().lower()
    unit_key = str(unit).strip() if unit is not None else "count"
    return item_key, unit_key


def _coerce_delta(delta: Any) -> float | int:
    try:
        amount = float(delta)
    except (TypeError, ValueError):
        amount = 0.0
    if amount.is_integer():
        return int(amount)
    return amount


def _normalize_tags(tags: Any) -> list[str]:
    """Lowercase, trim, and de-dupe a tags list (or a single string)."""
    if tags is None:
        return []
    if isinstance(tags, str):
        raw = [tags]
    elif isinstance(tags, (list, tuple, set)):
        raw = list(tags)
    else:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for tag in raw:
        key = str(tag).strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def insert_inventory_item(
    item: str,
    unit: str,
    delta: Any,
    expires_at: Any,
    tags: Any = None,
) -> dict[str, Any]:
    """Apply a signed inventory delta for item+unit.

    Purchases (delta >= 0) upsert. Usage (delta < 0) only updates an existing
    row, clamping quantity at 0 and flagging if usage exceeded stock.

    ``tags`` is merged into the existing tags array via $addToSet (never overwritten).

    Returns a dict with inventory_id, skipped, insufficient, and optional note.
    """
    item_key, unit_key = _item_unit_keys(item, unit)
    amount = _coerce_delta(delta)
    tag_list = _normalize_tags(tags)
    coll = get_db()["inventory"]
    match = {"item": item_key, "unit": unit_key}

    if amount < 0:
        existing = coll.find_one(match)
        if existing is None:
            return {
                "inventory_id": None,
                "skipped": True,
                "insufficient": False,
                "note": "item not previously tracked in inventory",
            }

        pipeline: list[dict[str, Any]] = [
            {
                "$set": {
                    "insufficient_flag": {
                        "$lt": [{"$add": ["$quantity", amount]}, 0]
                    },
                    "quantity": {
                        "$max": [0, {"$add": ["$quantity", amount]}]
                    },
                }
            },
            {
                "$set": {
                    "status": {
                        "$cond": {
                            "if": {"$eq": ["$quantity", 0]},
                            "then": "used",
                            "else": "active",
                        }
                    }
                }
            },
        ]
        if tag_list:
            pipeline.append(
                {
                    "$set": {
                        "tags": {
                            "$setUnion": [
                                {"$ifNull": ["$tags", []]},
                                tag_list,
                            ]
                        }
                    }
                }
            )
        coll.update_one(match, pipeline)
        doc = coll.find_one(match)
        insufficient = bool(doc and doc.get("insufficient_flag"))
        note = (
            "used more than tracked inventory — data may be stale"
            if insufficient
            else None
        )
        return {
            "inventory_id": None if doc is None else doc["_id"],
            "skipped": False,
            "insufficient": insufficient,
            "note": note,
        }

    set_on_insert: dict[str, Any] = {
        "expires_at": expires_at,
        "created_at": _utcnow(),
        "insufficient_flag": False,
    }
    # tags live on $addToSet; only default to [] when this write has none.
    if not tag_list:
        set_on_insert["tags"] = []

    update: dict[str, Any] = {
        "$inc": {"quantity": amount},
        "$set": {"status": "active"},
        "$setOnInsert": set_on_insert,
    }
    if tag_list:
        update["$addToSet"] = {"tags": {"$each": tag_list}}

    result = coll.update_one(match, update, upsert=True)
    inventory_id = result.upserted_id
    if inventory_id is None:
        doc = coll.find_one(match)
        inventory_id = None if doc is None else doc["_id"]
    return {
        "inventory_id": inventory_id,
        "skipped": False,
        "insufficient": False,
        "note": None,
    }


def find_inventory(query: Optional[dict] = None, limit: int = 0) -> list[dict]:
    """Find inventory documents matching query (all if omitted)."""
    cursor = get_db()["inventory"].find(query or {})
    if limit:
        cursor = cursor.limit(limit)
    return list(cursor)


def find_inventory_item(item: str) -> Optional[dict]:
    """Find a single inventory document by item name (case-insensitive)."""
    return get_db()["inventory"].find_one({"item": str(item).strip().lower()})


# --- user_preferences ---

def insert_preference(
    type: str,
    content: Any,
    weight: Any,
    expires_at: Any,
    source_utterance: str,
) -> Any:
    """Insert a user preference; returns the inserted _id."""
    doc = {
        "type": type,
        "content": content,
        "weight": weight,
        "expires_at": expires_at,
        "source_utterance": source_utterance,
        "created_at": _utcnow(),
    }
    result = get_db()["user_preferences"].insert_one(doc)
    return result.inserted_id


def find_preferences(query: Optional[dict] = None, limit: int = 0) -> list[dict]:
    """Find preference documents matching query (all if omitted)."""
    cursor = get_db()["user_preferences"].find(query or {})
    if limit:
        cursor = cursor.limit(limit)
    return list(cursor)


def find_preference_by_type(type: str) -> list[dict]:
    """Find preference documents by type."""
    return find_preferences({"type": type})


# --- action_log ---

def log_action(type: str, item: str, reason: str) -> Any:
    """Insert an action log entry; returns the inserted _id."""
    doc = {
        "type": type,
        "item": item,
        "reason": reason,
        "created_at": _utcnow(),
    }
    result = get_db()["action_log"].insert_one(doc)
    return result.inserted_id


def find_actions(query: Optional[dict] = None, limit: int = 0) -> list[dict]:
    """Find action_log documents matching query (all if omitted)."""
    cursor = get_db()["action_log"].find(query or {})
    if limit:
        cursor = cursor.limit(limit)
    return list(cursor)


def find_actions_by_type(type: str) -> list[dict]:
    """Find action_log documents by type."""
    return find_actions({"type": type})
