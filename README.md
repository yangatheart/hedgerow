# HedgeRow — Smart Agriculture MVP

A working MVP of the PRD (`Smart_Agriculture_System_MVP.docx`, v1.0, 12 Oct 2026).
**Not in this build (by request):** notifications (FR-09). Hosting is a basic Render setup (below), with no monitoring or backups yet.

## Run

```bash
./run.sh            # creates .venv on first run, serves http://localhost:8000
cd backend && ../.venv/bin/python -m pytest -q   # 42 tests: risk rules, API, accounts, data sources, crop advice
```

Locally it uses SQLite (`backend/agri.db`). Set `DATABASE_URL=postgresql://...` to use PostgreSQL. The tests pass on both.

## Deploy (Render)

`render.yaml` defines a free web service plus a free PostgreSQL database.

1. Sign in at render.com with GitHub.
2. **New + → Blueprint**, pick this repo, then **Apply**. Render creates `hedgerow` and `hedgerow-db` and links them.
3. Every push to `main` redeploys automatically.

Free-tier limits: the app sleeps after 15 min idle (about 30 s to wake), and the free database expires after 30 days.
Upgrade the database (about $7/mo) before real farmers use it.

## What's built

| PRD item | Where |
|---|---|
| 5-step quick setup with conditional crop/livestock follow-ups, skip, saved progress (FR-01/02/03) | `frontend/app.js` → `setup()` |
| Live weather + timestamps, stale/unavailable states (FR-04) | `backend/app/weather.py` (Open-Meteo, free, no key) |
| Versioned rule engine, evidence and model version stored (FR-05) | `backend/app/risk_engine.py` (`rules-2026.10-v1`) |
| Recommendations with action, reason, urgency, valid-until, applicability, caveat (FR-06) | same |
| Dashboard: farm summary, weather, risk cards, top actions, freshness (FR-07) | `dashboard()` |
| Useful / not useful, "I did this", outcome notes (FR-08) | risk detail page |
| "Improve your alerts" hints and targeted follow-up questions (FR-10) | `missing_hints()`, `missing_inputs` |
| History, profile editing, delete farm / delete all data | History and Profile tabs |

**Hazards:** heavy rainfall/waterlogging, drought/water deficit (ET₀ vs rain), crop heat, frost,
livestock heat (THI), storms and strong wind, and late-blight weather for potato/tomato only (Hutton criteria).

## Crop pages and tailored advice (v2)

- **Carrot design:** pages are drawn as one carrot (inline SVG). Feathery leaves stand in front of a hedgerow and rows of vegetables above ground, and a watercolour-style root with gentle bends runs down through crops, advice and actions.
- **Pesticide question:** setup step 3 asks "Which pesticides do you use, and how much?" (product, amount, unit, how often, which crop). Crop pages show them, with gentler alternatives.
- **Easy-to-read crop pages:** a water glass fills with how much to add this week (full = 25 L/m²), sun and temperature gauges, and fold-out details, pests and sources.
- **Planting date:** asked per crop in setup step 2, and editable on each crop page. It sets the growth stage and harvest window.
- **Sun and rain for the postcode:** the UK postcode is looked up exactly with postcodes.io. Past-7-day rain is **measured** at the nearest Environment Agency rain gauge (England). Elsewhere it falls back to the weather model.
- **Crop guide** (`backend/app/crops.py`): 15 UK crops with FAO-56 crop coefficients and stage lengths, sunlight, temperature, pH, harvest time, pests with bio-friendly controls, feeds and cited sources. Unknown crops get general values.
- **Tailored advice** (`backend/app/advice.py`): water to add = ET₀ × Kc − rain, in L/m², and it waits if rain is due. Also sunlight vs the crop's need, the temperature range, and crop-specific measures for upcoming storms, frost, heat and heavy rain.
- **Weather sources** (`backend/app/sources.py`): Open-Meteo first, with **MET Norway** as the free automatic fallback (Render's shared IP gets 429s from Open-Meteo). With MET, sunshine (from cloud cover), ET₀ (Hargreaves) and gusts are estimated and labelled as such. Set `WEATHER_PROVIDER=met` to force it.

## Stack (MVP simplifications vs PRD §9)

- FastAPI + **PostgreSQL** in production and SQLite locally (plain-SQL schema per PRD §8).
- Vanilla-JS single-page app served by FastAPI. No build step; it can move to React/Next later.
- **Accounts:** setup can be started anonymously. Email + password is required at the review step to save the farm,
  and to see the dashboard. Passwords use PBKDF2-SHA256 (600k iterations). Sessions last 30 days and are stored hashed.
  Failed logins are throttled (5 per 15 min per email). No password reset yet, since that needs an email provider.

## Before a real pilot (PRD §14)

- All thresholds in `risk_engine.THRESHOLDS` are **illustrative placeholders** and need agronomist review for the pilot region.
- Confirm the weather provider's licence and coverage. Open-Meteo is free for non-commercial use.
