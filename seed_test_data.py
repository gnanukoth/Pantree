"""Insert a small scoring fixture: one fibre-tagged item, one untagged item, one diet pref."""

from datetime import date, timedelta

from db import get_db, insert_inventory_item, insert_preference

FIBRE_ITEM = "seed_fibre_veg"
PLAIN_ITEM = "seed_plain"
DIET_CONTENT = "fibre-first"


def seed() -> dict:
    """Upsert two inventory docs and one diet preference for scoring tests."""
    expires_at = (date.today() + timedelta(days=14)).isoformat()

    fibre = insert_inventory_item(
        item=FIBRE_ITEM,
        unit="count",
        delta=1,
        expires_at=expires_at,
        tags=["vegetable", "fibre-rich"],
    )
    # Ensure tags are present even if the row already existed from an earlier seed.
    get_db()["inventory"].update_one(
        {"item": FIBRE_ITEM, "unit": "count"},
        {
            "$set": {"status": "active", "insufficient_flag": False, "expires_at": expires_at},
            "$addToSet": {"tags": {"$each": ["vegetable", "fibre-rich"]}},
        },
    )

    plain = insert_inventory_item(
        item=PLAIN_ITEM,
        unit="count",
        delta=1,
        expires_at=expires_at,
        tags=[],
    )
    get_db()["inventory"].update_one(
        {"item": PLAIN_ITEM, "unit": "count"},
        {
            "$set": {
                "status": "active",
                "insufficient_flag": False,
                "expires_at": expires_at,
                "tags": [],
            }
        },
    )

    prefs = get_db()["user_preferences"]
    existing = prefs.find_one({"type": "diet", "content": DIET_CONTENT, "source_utterance": "seed_test_data"})
    if existing:
        pref_id = existing["_id"]
        prefs.update_one({"_id": pref_id}, {"$set": {"weight": 0.8, "expires_at": None}})
    else:
        pref_id = insert_preference(
            type="diet",
            content=DIET_CONTENT,
            weight=0.8,
            expires_at=None,
            source_utterance="seed_test_data",
        )

    return {
        "fibre_inventory_id": fibre.get("inventory_id"),
        "plain_inventory_id": plain.get("inventory_id"),
        "preference_id": pref_id,
        "expires_at": expires_at,
    }


if __name__ == "__main__":
    summary = seed()
    print("Seeded scoring test data:")
    for key, value in summary.items():
        print(f"  {key}: {value}")
