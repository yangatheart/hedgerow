"""HedgeRow MVP — API + static frontend."""
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import advice, crops, risk_engine, weather
from .db import get_conn, init_db

FRONTEND = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")

@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


app = FastAPI(title="HedgeRow MVP", version="0.1.0", lifespan=lifespan,
              docs_url=None if os.environ.get("DATABASE_URL") else "/docs", redoc_url=None)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


def now_iso() -> str:
    # microseconds so "profile changed after last assessment" comparisons are exact
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


# --------------------------------------------------------------------------- auth
# Onboarding starts with an anonymous session so farmers can try setup without signing up.
# Saving the profile (and everything after it) requires an email + password account.
# Tokens and passwords are stored only as hashes; every farm query is scoped to the user.

SESSION_DAYS = 30
PBKDF2_ITERATIONS = 600_000
_failed_logins: dict[str, list[float]] = {}  # email -> failure times (simple in-memory throttle)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        # still do the work so unknown emails take the same time as wrong passwords
        hashlib.pbkdf2_hmac("sha256", password.encode(), b"0" * 16, PBKDF2_ITERATIONS)
        return False
    _, iters, salt, digest = stored.split("$")
    test = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
    return hmac.compare_digest(test.hex(), digest)


def _new_session(conn, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    conn.execute("INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                 (_hash(token), user_id, now.isoformat(), (now + timedelta(days=SESSION_DAYS)).isoformat()))
    return token


def _token(authorization: str) -> str:
    return authorization.removeprefix("Bearer ").strip()


def current_session(authorization: str = Header(default="")) -> dict:
    token = _token(authorization)
    if not token:
        raise HTTPException(401, "Missing session token")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT u.id, u.email FROM sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.token_hash=? AND s.expires_at > ?", (_hash(token), now_iso())).fetchone()
    if not row:
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    return {"id": row["id"], "email": row["email"], "token_hash": _hash(token)}


def current_user(session: dict = Depends(current_session)) -> int:
    return session["id"]


def registered_user(session: dict = Depends(current_session)) -> int:
    if not session["email"]:
        raise HTTPException(403, "Please create an account or sign in to continue.")
    return session["id"]


def require_account(conn, user_id: int) -> None:
    row = conn.execute("SELECT email FROM users WHERE id=?", (user_id,)).fetchone()
    if not row or not row["email"]:
        raise HTTPException(403, "Please create an account or sign in to continue.")


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=200)

    def clean_email(self) -> str:
        e = self.email.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e):
            raise HTTPException(422, "Please enter a valid email address.")
        return e


@app.post("/api/session")
def create_session():
    """Anonymous session used during onboarding, before an account exists."""
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO users(created_at) VALUES (?)", (now_iso(),))
        return {"token": _new_session(conn, cur.lastrowid)}


@app.get("/api/me")
def me(session: dict = Depends(current_session)):
    return {"email": session["email"], "registered": bool(session["email"])}


@app.post("/api/auth/register")
def register(body: Credentials, session: dict = Depends(current_session)):
    """Turn the current anonymous session's user into an account (keeps any draft farm)."""
    email = body.clean_email()
    if session["email"]:
        raise HTTPException(400, "You're already signed in.")
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise HTTPException(409, "An account with this email already exists. Please sign in instead.")
        conn.execute("UPDATE users SET email=?, password_hash=? WHERE id=?",
                     (email, hash_password(body.password), session["id"]))
    return {"email": email, "registered": True}


@app.post("/api/auth/login")
def login(body: Credentials, authorization: str = Header(default="")):
    email = body.clean_email()
    now = time.time()
    recent = [t for t in _failed_logins.get(email, []) if now - t < 900]
    if len(recent) >= 5:
        raise HTTPException(429, "Too many attempts. Please wait 15 minutes and try again.")
    with get_conn() as conn:
        user = conn.execute("SELECT id, password_hash FROM users WHERE email=?", (email,)).fetchone()
        if not verify_password(body.password, user["password_hash"] if user else None):
            _failed_logins[email] = recent + [now]
            raise HTTPException(401, "Email or password is incorrect.")
        _failed_logins.pop(email, None)
        # Bring over a draft farm started anonymously on this device, if the account has none yet.
        anon = conn.execute("SELECT u.id FROM sessions s JOIN users u ON u.id=s.user_id "
                            "WHERE s.token_hash=? AND u.email IS NULL", (_hash(_token(authorization)),)).fetchone()
        if anon:
            has_farm = conn.execute("SELECT 1 FROM farms WHERE user_id=?", (user["id"],)).fetchone()
            if not has_farm:
                conn.execute("UPDATE farms SET user_id=? WHERE user_id=?", (user["id"], anon["id"]))
            conn.execute("DELETE FROM users WHERE id=?", (anon["id"],))
        return {"token": _new_session(conn, user["id"]), "email": email}


@app.post("/api/auth/logout")
def logout(session: dict = Depends(current_session)):
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (session["token_hash"],))
    return {"ok": True}


@app.delete("/api/me")
def delete_me(user_id: int = Depends(current_user)):
    """Privacy: delete the account and all farm data."""
    with get_conn() as conn:
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    return {"deleted": True}


# --------------------------------------------------------------------------- models

ProductionType = Literal["vegetables", "fruit", "field_crops", "herbs", "flowers", "grass_pasture",
                         "hay_forage", "livestock", "other"]


class ProductionItemIn(BaseModel):
    type: str
    name: str = Field(min_length=1, max_length=80)
    area_or_count: Optional[float] = None
    unit: Optional[str] = None
    planting_date: Optional[str] = None
    growth_stage: Optional[str] = None


class ConditionsIn(BaseModel):
    water_access: Optional[str] = None
    irrigation_type: Optional[str] = None
    soil_type: Optional[str] = None
    drainage: Optional[str] = None
    waterlogging_history: Optional[str] = None
    soil_moisture_observation: Optional[str] = None
    pesticide_use: Optional[Literal["none", "some", "unsure"]] = None


class PesticideIn(BaseModel):
    product: str = Field(min_length=1, max_length=120)
    amount: Optional[float] = Field(default=None, ge=0)
    unit: Optional[Literal["ml", "L", "g", "kg"]] = None
    per: Optional[str] = Field(default=None, max_length=40)
    crop: Optional[str] = Field(default=None, max_length=80)


class FarmIn(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    location_label: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    timezone: Optional[str] = None
    size_category: Optional[Literal["small", "medium", "large"]] = None
    area_value: Optional[float] = Field(default=None, ge=0)
    area_unit: Optional[Literal["ha", "acres"]] = None
    production_types: Optional[list[ProductionType]] = None
    production_items: Optional[list[ProductionItemIn]] = None
    main_concern: Optional[str] = None
    conditions: Optional[ConditionsIn] = None
    pesticides: Optional[list[PesticideIn]] = None
    onboarding_step: Optional[int] = Field(default=None, ge=1, le=5)
    status: Optional[Literal["draft", "complete"]] = None


class FeedbackIn(BaseModel):
    useful: Optional[bool] = None
    action_taken: Optional[bool] = None
    outcome_notes: Optional[str] = Field(default=None, max_length=1000)


class FollowUpIn(BaseModel):
    key: str
    value: str
    item: Optional[str] = None


FARM_COLS = ["name", "location_label", "latitude", "longitude", "timezone", "size_category", "area_value",
             "area_unit", "main_concern", "onboarding_step", "status"]
COND_COLS = ["water_access", "irrigation_type", "soil_type", "drainage", "waterlogging_history",
             "soil_moisture_observation", "pesticide_use"]


# --------------------------------------------------------------------------- farm helpers

def load_farm(conn, farm_id: int, user_id: int) -> dict:
    row = conn.execute("SELECT * FROM farms WHERE id=? AND user_id=?", (farm_id, user_id)).fetchone()
    if not row:
        raise HTTPException(404, "Farm not found")
    farm = dict(row)
    farm["production_types"] = json.loads(farm["production_types"] or "[]")
    farm["production_items"] = [dict(r) for r in conn.execute(
        "SELECT * FROM production_items WHERE farm_id=? ORDER BY id", (farm_id,))]
    cond = conn.execute("SELECT * FROM farm_conditions WHERE farm_id=?", (farm_id,)).fetchone()
    farm["conditions"] = {k: (cond[k] if cond else None) for k in COND_COLS}
    farm["pesticides"] = [dict(r) for r in conn.execute(
        "SELECT id, product, amount, unit, per, crop FROM pesticide_uses WHERE farm_id=? ORDER BY id", (farm_id,))]
    return farm


def apply_farm_update(conn, farm_id: int, body: FarmIn):
    data = body.model_dump(exclude_unset=True)
    sets = {k: data[k] for k in FARM_COLS if k in data}
    if "production_types" in data:
        sets["production_types"] = json.dumps(data["production_types"] or [])
    sets["updated_at"] = now_iso()
    conn.execute(f"UPDATE farms SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), farm_id))
    if "production_items" in data:
        conn.execute("DELETE FROM production_items WHERE farm_id=?", (farm_id,))
        for p in data["production_items"] or []:
            conn.execute(
                "INSERT INTO production_items(farm_id, type, name, area_or_count, unit, planting_date, growth_stage) "
                "VALUES (?,?,?,?,?,?,?)",
                (farm_id, p["type"], p["name"].strip(), p.get("area_or_count"), p.get("unit"),
                 p.get("planting_date"), p.get("growth_stage")))
    if "conditions" in data and data["conditions"] is not None:
        upsert_conditions(conn, farm_id, data["conditions"])
    if "pesticides" in data:
        conn.execute("DELETE FROM pesticide_uses WHERE farm_id=?", (farm_id,))
        for p in data["pesticides"] or []:
            conn.execute("INSERT INTO pesticide_uses(farm_id, product, amount, unit, per, crop) VALUES (?,?,?,?,?,?)",
                         (farm_id, p["product"].strip(), p.get("amount"), p.get("unit"), p.get("per"), p.get("crop")))


def upsert_conditions(conn, farm_id: int, values: dict):
    conn.execute("INSERT OR IGNORE INTO farm_conditions(farm_id) VALUES (?)", (farm_id,))
    vals = {k: v for k, v in values.items() if k in COND_COLS}
    if vals:
        conn.execute(f"UPDATE farm_conditions SET {', '.join(f'{k}=?' for k in vals)} WHERE farm_id=?",
                     (*vals.values(), farm_id))


# --------------------------------------------------------------------------- farm endpoints

@app.get("/api/geocode")
def geocode(q: str, user_id: int = Depends(current_user)):
    if len(q.strip()) < 2:
        return {"results": []}
    try:
        return {"results": weather.geocode(q.strip())}
    except Exception:
        raise HTTPException(503, "Location search is temporarily unavailable. You can enter coordinates instead.")


@app.get("/api/farms")
def list_farms(user_id: int = Depends(current_user)):
    with get_conn() as conn:
        rows = conn.execute("SELECT id FROM farms WHERE user_id=? ORDER BY id", (user_id,)).fetchall()
        return {"farms": [load_farm(conn, r["id"], user_id) for r in rows]}


@app.post("/api/farms")
def create_farm(body: FarmIn, user_id: int = Depends(current_user)):
    with get_conn() as conn:
        ts = now_iso()
        if body.status == "complete":
            require_account(conn, user_id)
        cur = conn.execute("INSERT INTO farms(user_id, created_at, updated_at) VALUES (?,?,?)", (user_id, ts, ts))
        conn.execute("INSERT INTO farm_conditions(farm_id) VALUES (?)", (cur.lastrowid,))
        apply_farm_update(conn, cur.lastrowid, body)
        return load_farm(conn, cur.lastrowid, user_id)


@app.get("/api/farms/{farm_id}")
def get_farm(farm_id: int, user_id: int = Depends(current_user)):
    with get_conn() as conn:
        return load_farm(conn, farm_id, user_id)


@app.put("/api/farms/{farm_id}")
def update_farm(farm_id: int, body: FarmIn, user_id: int = Depends(current_user)):
    with get_conn() as conn:
        load_farm(conn, farm_id, user_id)  # ownership check
        if body.status == "complete":
            require_account(conn, user_id)
        apply_farm_update(conn, farm_id, body)
        return load_farm(conn, farm_id, user_id)


@app.delete("/api/farms/{farm_id}")
def delete_farm(farm_id: int, user_id: int = Depends(current_user)):
    with get_conn() as conn:
        load_farm(conn, farm_id, user_id)
        conn.execute("DELETE FROM farms WHERE id=?", (farm_id,))
    return {"deleted": True}


@app.post("/api/farms/{farm_id}/follow-up")
def answer_follow_up(farm_id: int, body: FollowUpIn, user_id: int = Depends(registered_user)):
    """Targeted follow-up question answered from a risk card."""
    with get_conn() as conn:
        farm = load_farm(conn, farm_id, user_id)
        if body.key in COND_COLS:
            upsert_conditions(conn, farm_id, {body.key: body.value})
        elif body.key == "growth_stage":
            for p in farm["production_items"]:
                if body.item is None or p["name"] == body.item:
                    conn.execute("UPDATE production_items SET growth_stage=? WHERE id=?", (body.value, p["id"]))
        else:
            raise HTTPException(400, "Unknown follow-up field")
        conn.execute("UPDATE farms SET updated_at=? WHERE id=?", (now_iso(), farm_id))
    return {"ok": True}


# --------------------------------------------------------------------------- dashboard / risks

def _load_run(conn, farm_id: int, run_id: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM risk_assessments WHERE farm_id=? AND run_id=? ORDER BY priority_score DESC, id",
                        (farm_id, run_id)).fetchall()
    return [_assessment_out(conn, r) for r in rows]


def _assessment_out(conn, r) -> dict:
    a = dict(r)
    for k in ("evidence", "caveats", "missing_inputs"):
        a[k] = json.loads(a[k] or "[]")
    recs = []
    for rec in conn.execute("SELECT * FROM recommendations WHERE assessment_id=? ORDER BY id", (a["id"],)):
        rec = dict(rec)
        fb = conn.execute("SELECT useful, action_taken, outcome_notes, created_at FROM feedback "
                          "WHERE recommendation_id=? ORDER BY id DESC LIMIT 1", (rec["id"],)).fetchone()
        rec["feedback"] = dict(fb) if fb else None
        recs.append(rec)
    a["recommendations"] = recs
    return a


def run_assessment(conn, farm: dict, wx: dict) -> str:
    results = risk_engine.assess(farm, farm["conditions"], wx["data"])
    run_id = uuid.uuid4().hex
    ts = now_iso()
    for a in results:
        cur = conn.execute(
            "INSERT INTO risk_assessments(farm_id, run_id, hazard, title, level, priority_score, applies_to, "
            "window_start, window_end, evidence, caveats, missing_inputs, weather_snapshot_id, model_version, "
            "assessed_at, valid_until) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (farm["id"], run_id, a["hazard"], a["title"], a["level"], a["priority_score"], a["applies_to"],
             a["window_start"], a["window_end"], json.dumps(a["evidence"]), json.dumps(a["caveats"]),
             json.dumps(a["missing_inputs"]), wx["snapshot_id"], risk_engine.MODEL_VERSION, ts, a["valid_until"]))
        for rec in a["recommendations"]:
            conn.execute(
                "INSERT INTO recommendations(assessment_id, action, rationale, urgency, applicability, caveat, valid_until) "
                "VALUES (?,?,?,?,?,?,?)",
                (cur.lastrowid, rec["action"], rec["rationale"], rec["urgency"],
                 rec["applicability"] or a["applies_to"], rec["caveat"], a["valid_until"]))
    conn.commit()
    return run_id


def _farm_state(conn, farm_id: int, user_id: int, refresh: bool = False) -> dict:
    """Farm + weather + current risk run (re-assessed when weather, profile or rules changed)."""
    farm = load_farm(conn, farm_id, user_id)
    wx = weather.get_weather(conn, farm, force=refresh)
    assessments, assessed_at = [], None
    if wx["data"]:
        last = conn.execute(
            "SELECT run_id, assessed_at, valid_until, weather_snapshot_id, model_version FROM risk_assessments "
            "WHERE farm_id=? ORDER BY id DESC LIMIT 1", (farm_id,)).fetchone()
        reuse = (last and last["weather_snapshot_id"] == wx["snapshot_id"]
                 and last["model_version"] == risk_engine.MODEL_VERSION
                 and last["assessed_at"] > farm["updated_at"] and last["valid_until"] > now_iso())
        run_id = last["run_id"] if reuse else run_assessment(conn, farm, wx)
        assessments = _load_run(conn, farm_id, run_id)
        assessed_at = assessments[0]["assessed_at"] if assessments else now_iso()
    summary = weather.summarize(wx["data"]) if wx["data"] else None
    measured = weather.measured_rain(farm["latitude"], farm["longitude"]) if wx["data"] else None
    return {"farm": farm, "wx": wx, "summary": summary, "measured": measured,
            "assessments": assessments, "assessed_at": assessed_at}


def _today(summary: dict | None) -> date:
    t = ((summary or {}).get("current") or {}).get("time")
    return date.fromisoformat(t[:10]) if t else datetime.now(timezone.utc).date()


def _crop_items(farm: dict) -> list[dict]:
    return [p for p in farm["production_items"] if p["type"] != "livestock"]


def _crop_advice(state: dict, item: dict) -> dict:
    return advice.crop_advice(item, crops.match_crop(item["name"]), state["summary"], state["measured"],
                              state["assessments"], _today(state["summary"]))


def _crop_widget(a: dict) -> dict:
    w = a.get("water") or {}
    return {"id": a["item"]["id"], "name": a["item"]["name"], "emoji": a["guide"]["emoji"],
            "guide_name": a["guide"]["name"], "in_guide": a["in_guide"], "stage": a["stage"]["label"],
            "needs_planting_date": a["stage"].get("needs_planting_date", False),
            "water_status": w.get("status"), "add_l_per_m2": w.get("add_l_per_m2"),
            "alerts": len(a["weather_ahead"])}


def _weather_out(state: dict) -> dict:
    wx = state["wx"]
    return {"status": wx["status"], "fetched_at": wx["fetched_at"], "error": wx["error"], "source": wx.get("source"),
            "summary": state["summary"], "measured_rain": state["measured"]}


@app.get("/api/farms/{farm_id}/dashboard")
def dashboard(farm_id: int, refresh: bool = False, user_id: int = Depends(registered_user)):
    with get_conn() as conn:
        st = _farm_state(conn, farm_id, user_id, refresh)
        farm = st["farm"]
        return {
            "farm": farm,
            "weather": _weather_out(st),
            "assessments": st["assessments"],
            "assessed_at": st["assessed_at"],
            "model_version": risk_engine.MODEL_VERSION,
            "hints": risk_engine.missing_hints(farm, farm["conditions"]),
            "crops": [_crop_widget(_crop_advice(st, i)) for i in _crop_items(farm)],
        }


@app.get("/api/farms/{farm_id}/crops/{item_id}")
def crop_page(farm_id: int, item_id: int, user_id: int = Depends(registered_user)):
    with get_conn() as conn:
        st = _farm_state(conn, farm_id, user_id)
        item = next((i for i in _crop_items(st["farm"]) if i["id"] == item_id), None)
        if not item:
            raise HTTPException(404, "Crop not found")
        mine = [p for p in st["farm"]["pesticides"] if not p["crop"] or p["crop"].lower() == item["name"].lower()]
        return {"farm": {k: st["farm"][k] for k in ("id", "name", "location_label")},
                "weather": _weather_out(st), "advice": _crop_advice(st, item),
                "pesticides": mine, "pesticide_use": st["farm"]["conditions"]["pesticide_use"],
                "caveat": crops.UK_CAVEAT, "model_version": risk_engine.MODEL_VERSION}


class ItemUpdate(BaseModel):
    planting_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    growth_stage: Optional[str] = Field(default=None, max_length=40)


@app.put("/api/farms/{farm_id}/items/{item_id}")
def update_item(farm_id: int, item_id: int, body: ItemUpdate, user_id: int = Depends(registered_user)):
    with get_conn() as conn:
        farm = load_farm(conn, farm_id, user_id)
        if not any(i["id"] == item_id for i in farm["production_items"]):
            raise HTTPException(404, "Crop not found")
        vals = body.model_dump(exclude_unset=True)
        if vals:
            conn.execute(f"UPDATE production_items SET {', '.join(f'{k}=?' for k in vals)} WHERE id=?",
                         (*vals.values(), item_id))
            conn.execute("UPDATE farms SET updated_at=? WHERE id=?", (now_iso(), farm_id))
    return {"ok": True}


@app.get("/api/assessments/{assessment_id}")
def get_assessment(assessment_id: int, user_id: int = Depends(registered_user)):
    with get_conn() as conn:
        r = conn.execute("SELECT a.* FROM risk_assessments a JOIN farms f ON f.id=a.farm_id "
                         "WHERE a.id=? AND f.user_id=?", (assessment_id, user_id)).fetchone()
        if not r:
            raise HTTPException(404, "Assessment not found")
        return _assessment_out(conn, r)


@app.post("/api/recommendations/{rec_id}/feedback")
def give_feedback(rec_id: int, body: FeedbackIn, user_id: int = Depends(registered_user)):
    with get_conn() as conn:
        r = conn.execute("SELECT r.id FROM recommendations r JOIN risk_assessments a ON a.id=r.assessment_id "
                         "JOIN farms f ON f.id=a.farm_id WHERE r.id=? AND f.user_id=?", (rec_id, user_id)).fetchone()
        if not r:
            raise HTTPException(404, "Recommendation not found")
        prev = conn.execute("SELECT useful, action_taken, outcome_notes FROM feedback WHERE recommendation_id=? "
                            "ORDER BY id DESC LIMIT 1", (rec_id,)).fetchone()
        merged = dict(prev) if prev else {"useful": None, "action_taken": None, "outcome_notes": None}
        merged.update(body.model_dump(exclude_unset=True))
        for k in ("useful", "action_taken"):  # store booleans as 0/1 (portable across SQLite/Postgres)
            if isinstance(merged[k], bool):
                merged[k] = int(merged[k])
        conn.execute("INSERT INTO feedback(recommendation_id, useful, action_taken, outcome_notes, created_at) "
                     "VALUES (?,?,?,?,?)",
                     (rec_id, merged["useful"], merged["action_taken"], merged["outcome_notes"], now_iso()))
        if merged["action_taken"]:
            conn.execute("UPDATE recommendations SET status='done' WHERE id=?", (rec_id,))
        return {"ok": True, "feedback": merged}


@app.get("/api/farms/{farm_id}/history")
def history(farm_id: int, user_id: int = Depends(registered_user)):
    """Past elevated alerts (medium/high) and any recommendation feedback."""
    with get_conn() as conn:
        load_farm(conn, farm_id, user_id)
        rows = conn.execute(
            "SELECT * FROM risk_assessments WHERE farm_id=? AND (level != 'low' OR id IN "
            "(SELECT r.assessment_id FROM recommendations r JOIN feedback fb ON fb.recommendation_id=r.id)) "
            "ORDER BY assessed_at DESC, priority_score DESC LIMIT 100", (farm_id,)).fetchall()
        items = [_assessment_out(conn, r) for r in rows]
        # Collapse repeated identical alerts (same hazard+level+window) to the newest one.
        seen, out = set(), []
        for a in items:
            key = (a["hazard"], a["level"], a["window_start"])
            if key in seen and not any(r["feedback"] for r in a["recommendations"]):
                continue
            seen.add(key)
            out.append(a)
        return {"history": out}


# --------------------------------------------------------------------------- static frontend

@app.get("/api/health")
def health():
    return {"ok": True, "model_version": risk_engine.MODEL_VERSION}


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.api_route("/", methods=["GET", "HEAD"])
def index():
    return FileResponse(os.path.join(FRONTEND, "index.html"))
