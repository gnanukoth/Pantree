# TODO: Flask entrypoint
"""Pantree app entrypoint and message processing."""

from typing import Any

from db import insert_inventory_item, insert_preference, log_action
from extraction import extract_facts


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

        write = insert_inventory_item(
            item=item,
            unit=unit,
            delta=delta,
            expires_at=fact.get("expires_at"),
            tags=fact.get("tags"),
        )
        notes = [n for n in (fact.get("note"), write.get("note")) if n]
        reason = " — ".join(notes) if notes else user_message
        action_id = log_action(type=action, item=item, reason=reason)
        results.append(
            {
                "kind": "inventory",
                "inventory_id": write.get("inventory_id"),
                "action_id": action_id,
                "skipped": write.get("skipped", False),
                "insufficient": write.get("insufficient", False),
                "fact": fact,
            }
        )

    return {"message": user_message, "facts": extracted.get("facts") or [], "writes": results}
