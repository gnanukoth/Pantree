"""Reset the pantry DB and preload a realistic demo household."""

from datetime import date, timedelta

from db import get_db, insert_inventory_item, insert_preference

SOURCE = "seed_demo_data"

# Varied shelf lives: one expired, one expiring tomorrow, plus cookable staples.
ITEMS = [
    {
        "item": "milk",
        "unit": "gallon",
        "quantity": 1,
        "expires_offset_days": -1,
        "tags": ["dairy", "beverage"],
        "description": "refrigerated whole milk, dairy beverage",
    },
    {
        "item": "ice cream",
        "unit": "pint",
        "quantity": 1,
        "expires_offset_days": 1,
        "tags": ["sweet", "dairy", "comfort"],
        "description": "vanilla ice cream dessert, high sugar dairy treat",
    },
    {
        "item": "spinach",
        "unit": "bunch",
        "quantity": 1,
        "expires_offset_days": 5,
        "tags": ["produce", "vegetable", "leafy-green", "fibre-rich"],
        "description": "fresh spinach, leafy green vegetable, high fibre",
    },
    {
        "item": "bread",
        "unit": "loaf",
        "quantity": 1,
        "expires_offset_days": 4,
        "tags": ["baked-goods", "carbs", "pantry-staple"],
        "description": "sliced sandwich bread, baked goods, carbs",
    },
    {
        "item": "eggs",
        "unit": "count",
        "quantity": 12,
        "expires_offset_days": 18,
        "tags": ["eggs", "protein"],
        "description": "fresh chicken eggs, high protein",
    },
    {
        "item": "chicken",
        "unit": "lb",
        "quantity": 2,
        "expires_offset_days": 3,
        "tags": ["meat", "protein"],
        "description": "raw chicken breast, high protein meat",
    },
    {
        "item": "cheddar cheese",
        "unit": "oz",
        "quantity": 8,
        "expires_offset_days": 12,
        "tags": ["dairy", "protein"],
        "description": "aged cheddar cheese, dairy protein",
    },
    {
        "item": "rice",
        "unit": "lb",
        "quantity": 2,
        "expires_offset_days": 180,
        "tags": ["carbs", "grain", "pantry-staple"],
        "description": "uncooked white rice, grain carb pantry staple",
    },
]


def reset_collections() -> dict:
    """Drop inventory, action log, and leftover test/demo preferences."""
    db = get_db()
    inventory_deleted = db["inventory"].delete_many({}).deleted_count
    actions_deleted = db["action_log"].delete_many({}).deleted_count
    prefs_deleted = db["user_preferences"].delete_many({}).deleted_count
    return {
        "inventory_deleted": inventory_deleted,
        "actions_deleted": actions_deleted,
        "preferences_deleted": prefs_deleted,
    }


def _insert_preference(*, type: str, content: str, weight: float, expires_at) -> object:
    return insert_preference(
        type=type,
        content=content,
        weight=weight,
        expires_at=expires_at,
        source_utterance=SOURCE,
    )


def _insert_item(spec: dict, today: date) -> dict:
    expires_at = (today + timedelta(days=spec["expires_offset_days"])).isoformat()
    write = insert_inventory_item(
        item=spec["item"],
        unit=spec["unit"],
        delta=spec["quantity"],
        expires_at=expires_at,
        tags=spec["tags"],
        description=spec["description"],
    )
    return {
        "item": spec["item"],
        "unit": spec["unit"],
        "quantity": spec["quantity"],
        "expires_at": expires_at,
        "inventory_id": write.get("inventory_id"),
    }


def seed() -> dict:
    today = date.today()
    constraint_exp = (today + timedelta(days=10)).isoformat()
    cleared = reset_collections()

    diet_id = _insert_preference(
        type="diet",
        content="fibre-first",
        weight=0.4,
        expires_at=None,
    )
    constraint_id = _insert_preference(
        type="temporary_constraint",
        content="no sugar",
        weight=1.0,
        expires_at=constraint_exp,
    )

    items = [_insert_item(spec, today) for spec in ITEMS]
    return {
        "cleared": cleared,
        "diet_preference_id": diet_id,
        "constraint_preference_id": constraint_id,
        "constraint_expires_at": constraint_exp,
        "items": items,
    }


if __name__ == "__main__":
    summary = seed()
    print("Cleared:")
    for key, value in summary["cleared"].items():
        print(f"  {key}: {value}")
    print("Seeded demo pantry:")
    print(f"  diet preference: fibre-first ({summary['diet_preference_id']})")
    print(
        f"  temporary_constraint: no sugar until {summary['constraint_expires_at']} "
        f"({summary['constraint_preference_id']})"
    )
    for item in summary["items"]:
        print(
            f"  {item['item']} ({item['quantity']} {item['unit']}): expires {item['expires_at']}"
        )
