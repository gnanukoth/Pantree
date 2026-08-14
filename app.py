# TODO: Flask entrypoint
"""Pantree app entrypoint and message processing."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from bson import ObjectId
from flask import Flask, jsonify, request, send_from_directory

from actions import (
    add_to_grocery_list,
    check_expired_items,
    check_expiring_items,
    get_grocery_list,
    get_throwaway_log,
)
from db import (
    find_actions,
    find_inventory,
    find_preferences,
    get_db,
    insert_inventory_item,
    insert_preference,
    log_action,
)
from extraction import MODEL, _get_client, extract_facts
from prompts import SYSTEM_PROMPT
from scoring import rank_items

app = Flask(__name__, static_folder="static")

CHAT_HISTORY: list[dict[str, str]] = []
STANDING_PREF_TYPES = ("diet", "dislike", "cuisine", "restriction")


def reset_history() -> None:
    """Clear in-memory session chat so demos start clean."""
    CHAT_HISTORY.clear()


reset_history()


def process_message(user_message: str) -> dict[str, Any]:
    """Extract facts from a user message and persist them to MongoDB.

    Inventory facts -> insert_inventory_item + log_action.
    Preference facts -> insert_preference.

    Returns the extracted payload plus per-fact write results (inserted ids).
    """
    extracted = extract_facts(user_message)
    results: list[dict[str, Any]] = []

    for fact in extracted.get("facts") or []:
        kind = fact.get("kind")
        if kind is None:
            if "preference_type" in fact or (
                "content" in fact and "item" not in fact and "delta" not in fact
            ):
                kind = "preference"
            else:
                kind = "inventory"

        if kind == "preference":
            pref_id = insert_preference(
                type=fact.get("preference_type") or fact.get("type") or "general",
                content=fact.get("content"),
                weight=fact.get("weight", 1.0),
                expires_at=fact.get("expires_at"),
                source_utterance=user_message,
            )
            results.append(
                {
                    "kind": "preference",
                    "preference_id": pref_id,
                    "fact": fact,
                }
            )
            continue

        # inventory update
        item = fact.get("item")
        delta = fact.get("delta", fact.get("quantity", 0))
        unit = fact.get("unit", "count")
        action = fact.get("action")
        if not action:
            action = "bought" if float(delta or 0) >= 0 else "used"

        description = fact.get("description")
        if not description and item:
            tags = fact.get("tags") or []
            tag_bit = ", ".join(str(t) for t in tags if t)
            description = f"{item}, {tag_bit}" if tag_bit else str(item)

        write = insert_inventory_item(
            item=item,
            unit=unit,
            delta=delta,
            expires_at=fact.get("expires_at"),
            tags=fact.get("tags"),
            description=description,
        )
        # Usage often comes back with a guessed unit (loaf vs count); apply
        # the delta to the active row for this item name if the first write skipped.
        if write.get("skipped") and action == "used" and item:
            tracked = get_db()["inventory"].find_one(
                {"item": str(item).strip().lower(), "status": "active"}
            )
            if tracked and str(tracked.get("unit")) != str(unit):
                write = insert_inventory_item(
                    item=item,
                    unit=tracked.get("unit"),
                    delta=delta,
                    expires_at=fact.get("expires_at"),
                    tags=fact.get("tags"),
                    description=description,
                )
        notes = [n for n in (fact.get("note"), write.get("note")) if n]
        reason = " — ".join(notes) if notes else user_message
        action_id = log_action(type=action, item=item, reason=reason)
        grocery_id = None
        if action == "used" and write.get("ran_out"):
            grocery_id = add_to_grocery_list(
                get_db(),
                item,
                reason="ran out — used up",
            )
        results.append(
            {
                "kind": "inventory",
                "inventory_id": write.get("inventory_id"),
                "action_id": action_id,
                "grocery_added": bool(grocery_id),
                "skipped": write.get("skipped", False),
                "insufficient": write.get("insufficient", False),
                "ran_out": write.get("ran_out", False),
                "fact": fact,
            }
        )

    return {"message": user_message, "facts": extracted.get("facts") or [], "writes": results}


def _jsonable(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _action_public(doc: dict) -> dict[str, Any]:
    out = _jsonable(doc)
    if isinstance(out, dict) and "_id" in out and "id" not in out:
        out["id"] = out["_id"]
    return out


def _ranked_payload(ranked: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for row in ranked[:limit]:
        item = row.get("item") or {}
        payload.append(
            {
                "item": item.get("item"),
                "quantity": item.get("quantity"),
                "unit": item.get("unit"),
                "expires_at": _jsonable(item.get("expires_at")),
                "tags": item.get("tags") or [],
                "description": item.get("description"),
                "score": row.get("score"),
                "reasons": list(row.get("reasons") or []),
            }
        )
    return payload


def _to_date(value: Any) -> date | None:
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


def _format_pref_day(value: Any) -> str:
    day = _to_date(value)
    if day is None:
        return ""
    return day.strftime("%b %d").replace(" 0", " ")


def _active_preferences_block() -> str:
    """Standing prefs plus unexpired temporary constraints, as a prompt block."""
    today = date.today()
    lines: list[str] = []
    seen: set[tuple[str, str]] = set()
    for pref in find_preferences() or []:
        pref_type = str(pref.get("type") or "").strip().lower()
        content = str(pref.get("content") or "").strip()
        if not content:
            continue
        if pref_type in STANDING_PREF_TYPES:
            pass
        elif pref_type == "temporary_constraint":
            expires = _to_date(pref.get("expires_at"))
            if expires is None or expires <= today:
                continue
        else:
            continue
        key = (pref_type, content.lower())
        if key in seen:
            continue
        seen.add(key)
        if pref_type == "temporary_constraint":
            until = _format_pref_day(pref.get("expires_at"))
            until_bit = f" until {until}" if until else ""
            lines.append(f"- {content}{until_bit} (active constraint)")
            continue
        try:
            weight = float(pref.get("weight", 1.0))
        except (TypeError, ValueError):
            weight = 1.0
        label = pref_type
        lines.append(f"- {content} {label} (weight {weight:g})")
    if not lines:
        return "Known user preferences:\n- (none recorded)"
    return "Known user preferences:\n" + "\n".join(lines)


def _recent_conversation_block() -> str:
    """Last 6 CHAT_HISTORY entries (up to 3 exchanges) as a prompt block."""
    recent = CHAT_HISTORY[-6:]
    if not recent:
        return "Recent conversation:\n(none yet this session)"
    lines = []
    for entry in recent:
        role = entry.get("role") or "user"
        message = " ".join(str(entry.get("message") or "").split())
        if len(message) > 280:
            message = message[:277] + "..."
        lines.append(f"{role}: {message}")
    return "Recent conversation:\n" + "\n".join(lines)


def generate_response(user_message: str) -> tuple[str, list[str], list[dict[str, Any]]]:
    """Extract facts, rank inventory, and produce a natural-language reply.

    Returns ``(reply_text, reasons, ranked_payload)``.
    """
    writes: dict[str, Any]
    try:
        writes = process_message(user_message)
    except Exception:
        writes = {"facts": []}

    db = get_db()
    try:
        check_expired_items(db)
        check_expiring_items(db)
    except Exception:
        pass

    ranked: list[dict[str, Any]] = []
    try:
        ranked = rank_items(
            find_inventory(),
            find_preferences(),
            find_actions(),
            use_vector_search=True,
        )
    except Exception:
        ranked = []

    top = _ranked_payload(ranked)
    reasons: list[str] = []
    for row in top:
        name = row.get("item") or "item"
        for signal in row.get("reasons") or []:
            reasons.append(f"{name}: {signal}")

    grocery = [_action_public(d) for d in get_grocery_list(db)[:15]]
    throwaway = [_action_public(d) for d in get_throwaway_log(db)[:15]]
    expired_stock = [
        {
            "item": doc.get("item"),
            "quantity": doc.get("quantity"),
            "unit": doc.get("unit"),
            "expires_at": _jsonable(doc.get("expires_at")),
            "status": doc.get("status"),
        }
        for doc in find_inventory({"status": "expired"})
    ]

    prefs_block = _active_preferences_block()
    history_block = _recent_conversation_block()
    pantry_snapshot = {
        "extracted_facts": writes.get("facts") or [],
        "top_ranked_items": top,
        "in_stock": [
            {
                "item": row["item"].get("item"),
                "quantity": row["item"].get("quantity"),
                "unit": row["item"].get("unit"),
                "tags": row["item"].get("tags") or [],
            }
            for row in ranked
            if row.get("item")
        ][:12],
        "grocery_list": [
            {"item": row.get("item"), "reason": row.get("reason")} for row in grocery
        ],
        "throwaway_log": [
            {
                "item": row.get("item"),
                "reason": row.get("reason"),
                "when": row.get("timestamp") or row.get("created_at"),
            }
            for row in throwaway
        ],
        "expired_inventory": expired_stock,
    }
    current_turn = (
        "Current user message:\n"
        f"{user_message}\n\n"
        "Pantry snapshot for this turn (active stock only in in_stock / "
        "top_ranked_items; expired unused items are in throwaway_log):\n"
        + json.dumps(pantry_snapshot, default=str)
    )
    client = _get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"{prefs_block}\n\n"
                    f"{history_block}\n\n"
                    f"{current_turn}"
                ),
            }
        ],
    )
    text_parts = [
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ]
    reply = "\n".join(text_parts).strip() or "I could not generate a reply just now."
    CHAT_HISTORY.append({"role": "user", "message": user_message})
    CHAT_HISTORY.append({"role": "agent", "message": reply})
    return reply, reasons, top


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = str(data.get("message") or "").strip()
    if not message:
        return jsonify({"reply": "Say something about your pantry or what to cook.", "reasons": [], "ranked": []})
    reply, reasons, ranked = generate_response(message)
    return jsonify({"reply": reply, "reasons": reasons, "ranked": ranked})


@app.route("/rankings")
def rankings_view():
    try:
        ranked = rank_items(
            find_inventory(),
            find_preferences(),
            find_actions(),
            use_vector_search=True,
        )
    except Exception:
        ranked = []
    return jsonify({"ranked": _ranked_payload(ranked, limit=20)})


@app.route("/actions")
def actions_view():
    db = get_db()
    grocery = [_action_public(d) for d in get_grocery_list(db)[:25]]
    throwaway = [_action_public(d) for d in get_throwaway_log(db)[:25]]
    return jsonify({"grocery_list": grocery, "throwaway_log": throwaway})


if __name__ == "__main__":
    reset_history()
    app.run(host="0.0.0.0", port=5050, debug=True)
