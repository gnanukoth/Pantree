# Pantree — Your pantry insider

**An AI pantry assistant with adaptive, transparent memory** — built for the Persistent Context Sprint Hackathon (MongoDB .Local Build Fest).

Pantree tracks kitchen inventory, remembers standing preferences and time-bound constraints, and takes real action: grocery-list adds for used-up or expiring items, and a throwaway log for unused expired food. Suggestions come from an adaptive score over live MongoDB Atlas data (expiry, preference match, waste, usage) — not static rules. Every reply includes a plain-language explanation of the signals that drove it.

Chat is the input. The product is an agent that **writes** to a live database, **ranks** from behavior that updates over time, and **shows its work**.

U.S. households account for **40–50% of the country’s food waste**. Most inventory apps track what you have, not what you will use — and they do not explain their reasoning. Pantree treats forgetting, not lack of knowledge, as the gap to close.

---

## Agent capabilities

- **Track inventory** from free text (`"bought 6 eggs"`, `"used the last of the bread"`), with units, tags, and descriptions.
- **Update quantities** with atomic upserts, clamped at zero; flag usage that exceeds tracked stock.
- **Remember preferences** — standing diet / dislike / cuisine / restriction, plus time-bound constraints (`"no sugar for 10 days"`). Constraints are hard filters while they last.
- **Stay consistent in chat** — every Claude turn is injected with active preferences and the last three exchanges, so dessert questions still respect “no sugar,” and follow-ups do not blindly repeat expiry warnings.
- **Rank what to use next** from expiry urgency, preference match (tags, with Atlas Automated Embeddings as a fallback), waste history, and usage frequency — recomputed live, no retraining.
- **Suggest meals** grounded in 2–3 items actually in stock, not generic recipes or invented ingredients.
- **Act** — add soon-to-expire or fully used items to a grocery list; log expired unused items to a throwaway log (24-hour dedup).
- **Answer from the right source** — active stock for “what’s in the pantry,” throwaway log for “what should I toss,” grocery list for “what should I buy.”
- **Show its work** — inline reasoning in chat; a viewer for ranking scores, grocery list, and throwaway log.
- **Stay in scope** — pantry management only; no medical or nutrition advice. Conflicts (e.g. dessert vs. an active no-sugar constraint) are named, not silently ignored.

---

## How it works

1. Claude extracts structured facts from the message.
2. MongoDB Atlas persists inventory, `user_preferences`, and `action_log`.
3. Expiry and run-out checks write grocery / throwaway actions.
4. Scoring ranks active items; the reply is generated with system prompt + known preferences + recent conversation + current turn (including pantry snapshot).

---

## Next steps (designed, not built)

- **Cross-session memory** — persist `chat_log` / session summaries so a new process still opens with last time’s context (in-session history is live today).
- **Vector ranking for recipes/actions** — extend Automated Embeddings beyond preference matching.
- **Self-correcting buy amounts** — use waste history to suggest *how much* to repurchase.
- **Scheduled waste reports** — `action_log` is queryable; no notifier yet.

---

## Run locally

```bash
python seed_demo_data.py
python app.py
```

Open [http://localhost:5050](http://localhost:5050). Requires `MONGODB_URI` and `ANTHROPIC_API_KEY` in `.env`.
