# Adaptive scoring for ranking pantry items against preferences and history.
"""Rank active inventory using expiry, preferences, waste, and usage."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

# Combined score = weighted sum of the four signals (waste is a penalty).
W_EXPIRY = 3.0
W_PREFERENCE = 2.0
W_USAGE = 0.15
W_WASTE = 1.5

WASTE_WINDOW_DAYS = 30
EXPIRY_REASON_DAYS = 7

_STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "to",
    "for",
    "with",
    "no",
    "not",
    "on",
    "in",
    "at",
    "is",
    "be",
}

# Item tokens that conflict with a restriction/constraint mentioning the group.
_RESTRICTION_GROUPS: dict[str, set[str]] = {
    "dairy": {"milk", "cheese", "butter", "yogurt", "yoghurt", "cream", "whey", "lactose"},
    "lactose": {"milk", "cheese", "butter", "yogurt", "yoghurt", "cream", "whey", "lactose"},
    "gluten": {"bread", "pasta", "wheat", "flour", "couscous", "barley", "rye", "cracker"},
    "wheat": {"bread", "pasta", "wheat", "flour", "couscous", "cracker"},
    "nut": {"almond", "walnut", "peanut", "cashew", "pecan", "hazelnut", "pistachio"},
    "peanut": {"peanut"},
    "shellfish": {"shrimp", "prawn", "crab", "lobster", "clam", "mussel", "oyster", "scallop"},
    "pork": {"pork", "bacon", "ham", "prosciutto"},
    "meat": {
        "chicken",
        "beef",
        "pork",
        "turkey",
        "lamb",
        "bacon",
        "sausage",
        "steak",
        "ham",
    },
    "sugar": {
        "candy",
        "soda",
        "cola",
        "cookie",
        "cake",
        "chocolate",
        "brownie",
        "syrup",
        "donut",
        "doughnut",
        "pastry",
        "dessert",
        "icecream",
    },
}

# Multi-word items that a "no sugar" (etc.) constraint should exclude.
_SUGAR_ITEMS = {
    "ice cream",
    "ice-cream",
    "icecream",
    "soda",
    "cola",
    "candy",
    "cookie",
    "cake",
    "chocolate",
}

# British/American spelling so "fibre-first" matches tag "fiber-rich" and vice versa.
_SPELLING_VARIANTS = {
    "fiber": "fibre",
    "fibers": "fibre",
    "fibres": "fibre",
}


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


def _normalize(text: Any) -> str:
    return " ".join(str(text or "").lower().replace("-", " ").replace("_", " ").split())


def _stem(token: str) -> str:
    return _SPELLING_VARIANTS.get(token, token)


def _tokens(text: Any) -> set[str]:
    return {
        _stem(tok)
        for tok in _normalize(text).split()
        if tok and tok not in _STOPWORDS
    }


def _item_tags(item_doc: dict) -> list[str]:
    raw = item_doc.get("tags") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(tag).strip().lower() for tag in raw if str(tag).strip()]


def _item_name(item_doc: dict) -> str:
    return _normalize(item_doc.get("item", ""))


def _item_tokens(item_doc: dict) -> set[str]:
    name = _item_name(item_doc)
    tokens = _tokens(name)
    if name.endswith("s") and len(name) > 3:
        tokens.add(name[:-1])
    return tokens


def _preference_active(pref: dict, *, today: date) -> bool:
    expires = _to_date(pref.get("expires_at"))
    if expires is None:
        return True
    return expires >= today


def _temporary_constraint_active(pref: dict, *, today: date) -> bool:
    expires = _to_date(pref.get("expires_at"))
    if expires is None:
        return True
    return expires > today


def _overlaps(item_tokens: set[str], text: Any) -> bool:
    other = _tokens(text)
    if not item_tokens or not other:
        return False
    return bool(item_tokens & other) or any(
        t in _normalize(text) or _normalize(text) in t for t in item_tokens if len(t) > 2
    )


def _conflicts_with_constraint(item_doc: dict, content: Any) -> bool:
    """True when a restriction / temporary constraint rules this item out."""
    item_tokens = _item_tokens(item_doc)
    content_norm = _normalize(content)
    content_tokens = _tokens(content)
    if not content_norm:
        return False
    name = _item_name(item_doc)
    if name and name in content_norm:
        return True
    if _overlaps(item_tokens, content):
        return True
    tags = _item_tags(item_doc)
    tag_tokens: set[str] = set()
    for tag in tags:
        tag_tokens |= _tokens(tag)
        if _tag_matches_preference(tag, content):
            return True
    for group, members in _RESTRICTION_GROUPS.items():
        group_mentioned = group in content_tokens or group in content_norm
        if not group_mentioned:
            continue
        if item_tokens & members or tag_tokens & members:
            return True
        if group == "sugar" and name in _SUGAR_ITEMS:
            return True
    return False


def _tag_matches_preference(tag: str, content: Any) -> bool:
    """Substring / keyword overlap between one tag and free-text preference content."""
    content_norm = _normalize(content)
    tag_norm = _normalize(tag)
    if not content_norm or not tag_norm:
        return False
    if tag_norm in content_norm or content_norm in tag_norm:
        return True
    content_tokens = {t for t in _tokens(content) if len(t) > 2}
    tag_tokens = {t for t in _tokens(tag) if len(t) > 2}
    if content_tokens & tag_tokens:
        return True
    if any(tok in tag_norm for tok in content_tokens):
        return True
    if any(tok in content_norm for tok in tag_tokens):
        return True
    return False


def _matches_diet_or_cuisine(item_doc: dict, pref: dict) -> bool:
    """Match active diet/cuisine prefs against the item's tags (not exact equality)."""
    content = pref.get("content")
    for tag in _item_tags(item_doc):
        if _tag_matches_preference(tag, content):
            return True
    return False


VECTOR_INDEX_NAME = "inventory_description_vector"
VECTOR_SCORE_THRESHOLD = 0.64


def _vector_search_item_ids(query_text: str) -> set[Any]:
    """Return inventory _ids whose description embeddings match ``query_text``."""
    from db import get_db

    text = str(query_text or "").strip()
    if not text:
        return set()
    pipeline = [
        {
            "$vectorSearch": {
                "index": VECTOR_INDEX_NAME,
                "path": "description",
                "query": text,
                "numCandidates": 40,
                "limit": 10,
            }
        },
        {
            "$project": {
                "_id": 1,
                "score": {"$meta": "vectorSearchScore"},
            }
        },
    ]
    ids: set[Any] = set()
    for doc in get_db()["inventory"].aggregate(pipeline):
        score = float(doc.get("score") or 0)
        if score >= VECTOR_SCORE_THRESHOLD and doc.get("_id") is not None:
            ids.add(doc["_id"])
    return ids


def preference_match(
    item_doc: dict,
    pref: dict,
    *,
    use_vector_search: bool = False,
    vector_item_ids: Optional[set[Any]] = None,
) -> bool:
    """True when an item matches a diet/cuisine preference.

    If ``use_vector_search`` is true, try Atlas $vectorSearch of the preference
    content against inventory ``description`` embeddings. Tag matching is the
    fallback whenever vector search is off, fails, or does not hit this item.
    """
    if use_vector_search:
        try:
            ids = vector_item_ids
            if ids is None:
                ids = _vector_search_item_ids(pref.get("content"))
            if item_doc.get("_id") in ids:
                return True
        except Exception:
            pass
    return _matches_diet_or_cuisine(item_doc, pref)


def _pref_weight(pref: dict) -> float:
    try:
        return float(pref.get("weight", 1.0))
    except (TypeError, ValueError):
        return 1.0


def _action_item(entry: dict) -> str:
    return _normalize(entry.get("item", ""))


def _action_matches_item(entry: dict, item_doc: dict) -> bool:
    action_item = _action_item(entry)
    name = _item_name(item_doc)
    if not action_item or not name:
        return False
    if action_item == name:
        return True
    # Singular/plural: "eggs" vs "egg"
    if action_item.rstrip("s") == name.rstrip("s"):
        return True
    return False


def _action_when(entry: dict) -> Optional[datetime]:
    return _to_datetime(entry.get("timestamp") or entry.get("created_at"))


def _days_until_expiry(item_doc: dict, *, today: date) -> Optional[int]:
    expires = _to_date(item_doc.get("expires_at"))
    if expires is None:
        return None
    return (expires - today).days


def score_item(
    item_doc: dict,
    preferences: list[dict],
    action_log_entries: list[dict],
    *,
    now: Optional[datetime] = None,
    use_vector_search: bool = False,
    vector_item_ids: Optional[set[Any]] = None,
) -> Optional[dict[str, Any]]:
    """Score one inventory document, or return None if it should be excluded.

    Returns ``{"score": float, "reasons": list[str]}``.
    """
    if not item_doc or item_doc.get("status") != "active":
        return None
    if item_doc.get("insufficient_flag"):
        return None

    now = now or _utcnow()
    today = now.date()
    prefs = list(preferences or [])
    actions = list(action_log_entries or [])

    for pref in prefs:
        pref_type = pref.get("type")
        if pref_type == "restriction" and _preference_active(pref, today=today):
            if _conflicts_with_constraint(item_doc, pref.get("content")):
                return None
        if pref_type == "temporary_constraint" and _temporary_constraint_active(
            pref, today=today
        ):
            if _conflicts_with_constraint(item_doc, pref.get("content")):
                return None

    reasons: list[str] = []

    raw_days = _days_until_expiry(item_doc, today=today)
    if raw_days is None:
        expiry_urgency = 0.0
    else:
        days_clamped = max(0, raw_days)
        expiry_urgency = 1.0 / (days_clamped + 1)
        if raw_days <= 0:
            reasons.append("expires today")
        elif raw_days == 1:
            reasons.append("expires in 1 day")
        elif raw_days <= EXPIRY_REASON_DAYS:
            reasons.append(f"expires in {raw_days} days")

    preference_score = 0.0
    for pref in prefs:
        if pref.get("type") not in ("diet", "cuisine"):
            continue
        if not _preference_active(pref, today=today):
            continue
        if not preference_match(
            item_doc,
            pref,
            use_vector_search=use_vector_search,
            vector_item_ids=vector_item_ids,
        ):
            continue
        weight = _pref_weight(pref)
        preference_score += weight
        label = str(pref.get("content") or "diet").strip()
        reasons.append(f"matches {label} preference")

    waste_cutoff = now - timedelta(days=WASTE_WINDOW_DAYS)
    waste_penalty = 0
    for entry in actions:
        if entry.get("type") != "thrown_away":
            continue
        if not _action_matches_item(entry, item_doc):
            continue
        when = _action_when(entry)
        if when is not None and when < waste_cutoff:
            continue
        waste_penalty += 1
    if waste_penalty:
        reasons.append(f"wasted {waste_penalty}x recently")

    usage_frequency = 0
    for entry in actions:
        if entry.get("type") != "used":
            continue
        if _action_matches_item(entry, item_doc):
            usage_frequency += 1
    if usage_frequency:
        reasons.append(f"used {usage_frequency}x")

    score = (
        W_EXPIRY * expiry_urgency
        + W_PREFERENCE * preference_score
        + W_USAGE * usage_frequency
        - W_WASTE * waste_penalty
    )
    return {"score": score, "reasons": reasons}


def rank_items(
    all_inventory: list[dict],
    preferences: list[dict],
    action_log: list[dict],
    *,
    now: Optional[datetime] = None,
    use_vector_search: bool = False,
) -> list[dict[str, Any]]:
    """Score every active inventory item; return highest score first.

    Items that ``score_item`` excludes (None) are omitted.
    Each result is ``{"item": item_doc, "score": float, "reasons": list[str]}``.
    """
    now = now or _utcnow()
    today = now.date()
    vector_item_ids: Optional[set[Any]] = None
    if use_vector_search:
        try:
            vector_item_ids = set()
            for pref in preferences or []:
                if pref.get("type") not in ("diet", "cuisine"):
                    continue
                if not _preference_active(pref, today=today):
                    continue
                vector_item_ids |= _vector_search_item_ids(pref.get("content"))
        except Exception:
            vector_item_ids = None
    ranked: list[dict[str, Any]] = []
    for item_doc in all_inventory or []:
        result = score_item(
            item_doc,
            preferences,
            action_log,
            now=now,
            use_vector_search=use_vector_search,
            vector_item_ids=vector_item_ids,
        )
        if result is None:
            continue
        ranked.append(
            {
                "item": item_doc,
                "score": result["score"],
                "reasons": result["reasons"],
            }
        )
    ranked.sort(key=lambda row: row["score"], reverse=True)
    return ranked
