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

def insert_inventory_item(item: str, quantity: Any, expires_at: Any) -> Any:
    """Insert an inventory document; returns the inserted _id."""
    doc = {
        "item": item,
        "quantity": quantity,
        "expires_at": expires_at,
        "created_at": _utcnow(),
    }
    result = get_db()["inventory"].insert_one(doc)
    return result.inserted_id


def find_inventory(query: Optional[dict] = None, limit: int = 0) -> list[dict]:
    """Find inventory documents matching query (all if omitted)."""
    cursor = get_db()["inventory"].find(query or {})
    if limit:
        cursor = cursor.limit(limit)
    return list(cursor)


def find_inventory_item(item: str) -> Optional[dict]:
    """Find a single inventory document by item name."""
    return get_db()["inventory"].find_one({"item": item})


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
