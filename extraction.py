# TODO: LLM-based fact extraction
"""Extract structured pantry facts from natural language via Claude."""

import json
import os
import re
from datetime import date
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-5"

EXTRACTION_PROMPT = """You extract structured pantry facts from a user's message for a pantry-tracking app.

Return ONLY valid JSON (no markdown fences, no commentary) with this shape:
{
  "facts": [
    // inventory update — bought or used an item:
    {
      "kind": "inventory",
      "item": "<item name, lowercase singular or common form>",
      "delta": <signed number>,
      "unit": "<free string, e.g. count, lb, oz, cup, gallon>",
      "expires_at": "<YYYY-MM-DD>",
      "action": "bought" | "used",
      "tags": ["<2-4 lowercase tags from the controlled vocabulary>"],
      "description": "<short searchable phrase, e.g. fresh spinach, leafy green vegetable, high fibre>",
      "note": "<optional; include only when amount is uncertain>"
    }
    // OR preference / dietary statement (not an inventory change):
    {
      "kind": "preference",
      "preference_type": "<e.g. diet, dislike, cuisine, restriction, temporary_constraint>",
      "content": "<what the user prefers or avoids>",
      "expires_at": "<YYYY-MM-DD; include for time-bounded constraints, else omit>"
    }
  ]
}

Rules:
- A single message may yield multiple facts; put each in the facts array.
- delta is a signed number: positive for purchases/additions, negative for usage/consumption.
  Examples: "bought 6 eggs" -> delta: 6, unit: "count"; "used 2 eggs" -> delta: -2, unit: "count";
  "used 1/2 pound chicken" -> delta: -0.5, unit: "lb".
- unit is a short free string (count, lb, oz, cup, gallon, etc.). Prefer "count" for discrete items.
- Parse fractions and phrases like "half a pound" into numeric deltas (0.5).
- If the amount used is not clearly stated (e.g. "used the chicken", "finished the milk"),
  default delta to -1, choose a reasonable unit, and set note explaining the uncertainty.
- If a purchase amount is missing, default delta to 1 with an appropriate unit and optional note.
- action should match the sign of delta: "bought" for positive, "used" for negative.
- For every inventory fact (bought or used), include "tags": an array of 2-4 short lowercase
  tags describing the item's food category and dietary properties. Prefer this controlled
  vocabulary so preference matching is reliable:
  vegetable, leafy-green, fruit, produce, grain, carbs, protein, dairy, eggs,
  meat, seafood, baked-goods, pantry-staple, legume, nut, fibre-rich,
  high-protein, comfort, spicy, fermented, frozen, canned, fresh, sweet,
  savory, gluten, herb, oil, beverage.
  Examples: "bought spinach" -> ["produce", "vegetable", "fibre-rich", "leafy-green"];
  "bought bread" -> ["baked-goods", "carbs", "pantry-staple"];
  "bought rice" or "bought pasta" -> ["carbs", "grain", "pantry-staple"];
  "bought chicken" -> ["meat", "protein"];
  "bought cheese" -> ["dairy", "protein"];
  "bought eggs" -> ["eggs", "protein"];
  "bought canned beans" -> ["pantry-staple", "canned", "legume", "protein"].
  Do not invent free-form tags when a vocabulary term fits. Always include tags on inventory facts.
- For every inventory fact, include "description": a short natural-language phrase (about 5–12 words) that names the item and its food qualities for semantic search. Example: "fresh spinach, leafy green vegetable, high fibre". Do not write medical claims.
- For inventory: if the user did not give an expiration date, estimate a reasonable expires_at from today's date based on typical shelf life for that item (e.g. milk ~7 days, bread ~5 days, eggs ~21 days, canned goods ~1 year, fresh produce ~5–14 days).
- For temporary_constraint preferences (e.g. "no sugar for 10 days"), set expires_at to today plus that duration.
- Prefer preference facts when the message is about tastes, diets, allergies, or habits rather than adding/removing pantry stock.
- If nothing pantry-related can be extracted, return {"facts": []}.
- Today's date is {today}.
"""

SYSTEM_PROMPT = EXTRACTION_PROMPT


def _get_client() -> Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set in the environment")
    return Anthropic(api_key=api_key)


def _parse_json_content(text: str) -> dict[str, Any]:
    """Parse JSON from model output, tolerating optional markdown fences."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


def extract_facts(user_message: str) -> dict[str, Any]:
    """Call Claude to extract structured pantry facts from a user message.

    Returns a dict like:
      {"facts": [{"kind": "inventory", "item": ..., "delta": <signed number>,
                  "unit": "count"|"lb"|..., "expires_at": "YYYY-MM-DD",
                  "action": "bought"|"used", "tags": ["vegetable", ...],
                  "description": "...", "note": <optional>}, ...]}
    or preference facts with preference_type / content.
    """
    if not user_message or not str(user_message).strip():
        return {"facts": []}

    system = EXTRACTION_PROMPT.replace("{today}", date.today().isoformat())
    client = _get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system,
        messages=[
            {
                "role": "user",
                "content": user_message.strip(),
            }
        ],
    )

    text_parts = [
        block.text for block in response.content if getattr(block, "type", None) == "text"
    ]
    if not text_parts:
        raise ValueError("Claude returned no text content")

    parsed = _parse_json_content("\n".join(text_parts))
    if "facts" not in parsed or not isinstance(parsed["facts"], list):
        # Allow a bare single fact object as a convenience
        if isinstance(parsed, dict) and (
            "kind" in parsed or "item" in parsed or "preference_type" in parsed
        ):
            return {"facts": [parsed]}
        raise ValueError(f"Unexpected extraction shape: {parsed!r}")
    return parsed
