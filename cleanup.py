# TODO: one-off Atlas cleanup
"""Merge duplicate egg inventory documents left over from insert_one testing.

Run once:
    conda run -n mongoDBHack python cleanup.py
"""

from typing import Any

from db import get_db


def _numeric_quantity(value: Any) -> float:
    """Coerce old nested {delta, unit} quantities and numbers to a float."""
    if isinstance(value, dict):
        raw = value.get("delta", value.get("quantity", 0))
    else:
        raw = value
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _unit_from_doc(doc: dict) -> str:
    if doc.get("unit"):
        return str(doc["unit"])
    qty = doc.get("quantity")
    if isinstance(qty, dict) and qty.get("unit"):
        return str(qty["unit"])
    return "count"


def flatten_nested_quantities() -> list[str]:
    """Rewrite leftover {delta, unit} quantity objects into numeric quantity + unit."""
    coll = get_db()["inventory"]
    updated: list[str] = []
    for doc in coll.find({"quantity": {"$type": "object"}}):
        unit = _unit_from_doc(doc)
        qty = _numeric_quantity(doc.get("quantity"))
        if float(qty).is_integer():
            qty = int(qty)
        coll.update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "item": str(doc.get("item", "")).strip().lower(),
                    "unit": unit,
                    "quantity": qty,
                    "status": doc.get("status") or "active",
                }
            },
        )
        updated.append(str(doc["_id"]))
    return updated


def merge_egg_duplicates() -> dict:
    """Keep one egg doc per unit, summing quantities; delete the rest."""
    coll = get_db()["inventory"]
    eggs = list(coll.find({"item": {"$regex": r"^eggs?$", "$options": "i"}}))

    by_unit: dict[str, list[dict]] = {}
    for doc in eggs:
        by_unit.setdefault(_unit_from_doc(doc), []).append(doc)

    kept: list[str] = []
    deleted: list[str] = []

    for unit, docs in by_unit.items():
        total = sum(_numeric_quantity(d.get("quantity")) for d in docs)
        if total.is_integer():
            total = int(total)
        keeper = docs[0]
        extra_ids = [d["_id"] for d in docs[1:]]

        coll.update_one(
            {"_id": keeper["_id"]},
            {
                "$set": {
                    "item": "egg",
                    "unit": unit,
                    "quantity": total,
                    "status": "active",
                }
            },
        )
        if extra_ids:
            coll.delete_many({"_id": {"$in": extra_ids}})
            deleted.extend(str(i) for i in extra_ids)
        kept.append(f"{keeper['_id']} (egg / {unit} qty={total})")

    return {
        "found": len(eggs),
        "kept": kept,
        "deleted": deleted,
    }


if __name__ == "__main__":
    flattened = flatten_nested_quantities()
    if flattened:
        print(f"Flattened nested quantity on {len(flattened)} document(s).")
    summary = merge_egg_duplicates()
    print(f"Found {summary['found']} egg document(s).")
    for line in summary["kept"]:
        print(f"  kept {line}")
    if summary["deleted"]:
        print(f"Deleted {len(summary['deleted'])} duplicate(s):")
        for _id in summary["deleted"]:
            print(f"  deleted {_id}")
    else:
        print("No duplicates to delete.")
