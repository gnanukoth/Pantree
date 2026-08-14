# Pantree — Your pantry insider

**An AI pantry assistant with adaptive, transparent memory** — built for the Persistent Context Sprint Hackathon (MongoDB .Local Build Fest).

Pantree is an AI kitchen assistant that tracks inventory, remembers user preferences and time-bound dietary constraints, and takes real action: automatically adding used and expiring items to a grocery list and logging unused, expired items to a throwaway log. Rather than static rules, every suggestion is produced by an adaptive scoring function that weighs expiry urgency, preference match, and past waste/usage patterns computed live from MongoDB Atlas, and every response includes a plain-language explanation of exactly which signals drove it — transparency by design, not a bolted-on dashboard. Built to directly address a persistent, expensive problem (U.S. households are responsible for 40–50% of the country's food waste), it demonstrates genuine agent memory and action-taking rather than a chatbot wrapped around a database, with cross-session context and broader vector-search-driven ranking scoped as clear next steps beyond today's build.

---

## What it does

Pantree tracks what's in your kitchen, remembers your preferences and constraints over time, and takes real action on that data — adding expiring and used-up items to a grocery list, logging unused-and-expired items, and adjusting future suggestions based on what actually happened, not just what was said once. Every suggestion comes with a one-line explanation of exactly which signals drove it.

Chat is the input method. The product is an agent that **writes** to a live database, **ranks** decisions from signals that update as your behavior does, and **shows its work** for every suggestion and action.

---

## The problem

Household food waste accounts for **40–50% of all food wasted in the United States**, and nearly a third of the U.S. food supply still goes unsold or uneaten each year. Existing “smart fridge” and inventory apps solve half the problem: they track what you have, but not what you'll actually use it for — and none of them explain their reasoning, so users have no way to trust or correct what the system believes about them.

---

## The differentiator

Most pantry and nutrition apps are inventory trackers with a chat interface bolted on. Pantree inverts that:

- Chat is just how you talk to it.
- The agent persists inventory, preferences, and actions in MongoDB Atlas.
- Ranking is an adaptive function over live history, not a one-shot prompt.
- Transparency is a design constraint on every response, not a dashboard feature.

---

## What's implemented

Built and running within the hackathon window:

- **Structured extraction** — Free-text messages (`"bought 6 eggs"`, `"used half a pound of chicken"`) are parsed into inventory deltas with units, tags, and descriptions via Claude.
- **Correct inventory arithmetic** — Quantity updates via atomic upserts, clamped at zero, with flags when reported usage exceeds tracked stock.
- **Preference and constraint memory** — Standing preferences (diet, dislikes) and time-bound constraints (e.g. `"no sugar for 10 days"`) are stored with expiry and applied as **hard filters** during ranking, not just soft nudges.
- **Adaptive scoring** — A weighted function combining expiry urgency, preference match, waste history, and usage frequency, recomputed live from stored data — no retraining, no static rules.
- **Automatic action-taking** — Expiring items and items that run out from usage are added to a grocery list; expired unused items are logged to a throwaway log. Both paths are idempotent against duplicate runs (24-hour dedup).
- **Inline reasoning** — Every suggestion is paired with the specific signals that produced it.
- **MongoDB Atlas throughout** — Persistence for inventory, `user_preferences`, and `action_log`, with an initial pass at **Automated Embeddings** for semantic preference matching alongside a tag-based fallback.

---

## What's designed but not implemented

Time-boxed out, not abandoned. Everything above is real and running; these are scoped next steps:

- **Cross-session memory** — A `chat_log` + `session_summaries` design where each new session opens with a short summary of what mattered last time — the most direct expression of persistent context.
- **Full vector-search-driven matching** — Extending Automated Embeddings from preference matching to recipe/action ranking broadly, replacing tag heuristics entirely.
- **Self-correcting purchase quantities** — Using waste history to suggest how much to buy next time, not just whether to suggest an item.
- **Notification / scheduling** — The weekly waste-report concept exists at the data level (queryable from `action_log`) but is not wired to a scheduler.

---

## How it scales

The core mechanism — **score = f(live signals from stored history)** — does not change shape as it grows. More users means more documents, not more logic: MongoDB's document model and indexing handle that natively, and Atlas Vector Search scales semantic matching without a separate embedding service to maintain.

The harder scaling question is behavioral, not technical. As history accumulates, the scoring function's waste and usage terms become more reliable, meaning the system should get more accurate with more data and time — not just more expensive to run.

---

## Impact

The USDA/EPA joint national target is to cut U.S. food waste in half by 2030, and consumer education interventions have been shown to reduce household food waste by roughly 10–25% in controlled studies. Pantree's bet is narrow but concrete: most food waste isn't a knowledge problem, it's a **forgetting** problem — people buy in good faith and then lose track. A system that remembers on their behalf, and explains why it's nudging a particular action, targets exactly that gap rather than asking users to change habits wholesale.

---

## Run locally

```bash
python seed_demo_data.py
python app.py
```

Open [http://localhost:5050](http://localhost:5050). Requires `MONGODB_URI` and `ANTHROPIC_API_KEY` in `.env`.
