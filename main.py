from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from pydantic import BaseModel
from typing import Optional
import sqlite3
import os
import io
import csv
import json
from datetime import datetime
from contextlib import contextmanager
import base64
import httpx
from dotenv import load_dotenv

from fastapi import Depends
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# ── Config ────────────────────────────────────────────────────────────────────
load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.environ.get("FOOD_DIARY_DB", os.path.join(BASE_DIR, "food_diary.db"))

# AI config (Google Gemini)
GEMINI_KEY    = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL  = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

# Single user (auth handled externally by reverse proxy)
USER_UID   = "abeggi"
USER_EMAIL = "abeggi@gmail.com"

# ── Rate Limiter ─────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Food Diary", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Auth Dependency ──────────────────────────────────────────────────────────
async def get_current_user_dict() -> dict:
    """Restituisce l'utente fisso (auth gestita dal reverse proxy)."""
    return {"uid": USER_UID, "email": USER_EMAIL, "is_admin": True}

async def get_current_user(user: dict = Depends(get_current_user_dict)) -> str:
    """Ritorna solo l'UID per compatibilità coi CRUD endpoints."""
    return user["uid"]

async def get_admin_user(user: dict = Depends(get_current_user_dict)) -> str:
    """Verifica che l'utente sia un amministratore e ritorna l'UID."""
    if not user.get("is_admin"):
        raise HTTPException(403, "Access denied: Admin only")
    return user["uid"]

@app.get("/api/me")
@limiter.limit("30/minute")
async def get_me(request: Request, user: dict = Depends(get_current_user_dict)):
    """Restituisce info sull'utente corrente (inclusi i ruoli)."""
    return user

# ── Admin API ─────────────────────────────────────────────────────────────────
@app.get("/api/admin/users")
@limiter.limit("10/minute")
def admin_list_users(request: Request, admin_id: str = Depends(get_admin_user)):
    return [{"uid": USER_UID, "email": USER_EMAIL, "display_name": "Andrea Beggi", "is_allowed": True}]

@app.delete("/api/admin/users/{uid}", status_code=204)
@limiter.limit("10/minute")
def admin_delete_user(request: Request, uid: str, admin_id: str = Depends(get_admin_user)):
    return

# ── DB ────────────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

@contextmanager
def db_conn():
    conn = get_db()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with db_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS entries (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        TEXT    NOT NULL,
                food      TEXT    NOT NULL,
                notes     TEXT    DEFAULT '',
                created   TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS foods (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                name    TEXT    NOT NULL COLLATE NOCASE
            );
            CREATE TABLE IF NOT EXISTS whitelist (
                email   TEXT PRIMARY KEY COLLATE NOCASE,
                added   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            );
        """)
        # Migrations (Add columns if missing)
        try:
            conn.execute("ALTER TABLE entries ADD COLUMN cat TEXT DEFAULT ''")
        except sqlite3.OperationalError: pass
        
        try:
            conn.execute("ALTER TABLE entries ADD COLUMN user_id TEXT DEFAULT 'dev_user'")
        except sqlite3.OperationalError: pass

        try:
            conn.execute("ALTER TABLE foods ADD COLUMN user_id TEXT DEFAULT 'dev_user'")
        except sqlite3.OperationalError: pass
        
        try:
            conn.execute("ALTER TABLE whitelist ADD COLUMN user_id TEXT")
        except sqlite3.OperationalError: pass

        try:
            conn.execute("ALTER TABLE entries ADD COLUMN free_notes TEXT DEFAULT ''")
        except sqlite3.OperationalError: pass

        # Now create indexes on existing/new columns
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_entries_ts ON entries(ts);
            CREATE INDEX IF NOT EXISTS idx_entries_uid ON entries(user_id);
            CREATE INDEX IF NOT EXISTS idx_foods_name ON foods(name);
            CREATE INDEX IF NOT EXISTS idx_foods_uid ON foods(user_id);
        """)

init_db()

# ── Models ────────────────────────────────────────────────────────────────────
class EntryIn(BaseModel):
    ts:    str            # ISO datetime string, e.g. "2025-04-03T12:30"
    food:  str
    cat:   Optional[str] = ""
    notes: Optional[str] = ""
    free_notes: Optional[str] = ""

class EntryUpdate(BaseModel):
    ts:    Optional[str]  = None
    food:  Optional[str]  = None
    cat:   Optional[str]  = None
    notes: Optional[str]  = None
    free_notes: Optional[str]  = None

def parse_ts_or_400(ts: str) -> str:
    value = (ts or "").strip()
    if not value:
        raise HTTPException(400, "ts cannot be empty")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(400, "Invalid ts format. Use ISO datetime, e.g. 2025-04-03T12:30") from exc
    return parsed.strftime("%Y-%m-%dT%H:%M")

# ── Entries ───────────────────────────────────────────────────────────────────
@app.get("/api/entries")
@limiter.limit("60/minute")
def list_entries(
    request: Request,
    date: Optional[str] = Query(None, description="Filter by date YYYY-MM-DD"),
    limit: int = Query(200, le=1000),
    user_id: str = Depends(get_current_user)
):
    with db_conn() as conn:
        if date:
            rows = conn.execute(
                "SELECT * FROM entries WHERE user_id=? AND ts LIKE ? ORDER BY ts DESC LIMIT ?",
                (user_id, f"{date}%", limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM entries WHERE user_id=? ORDER BY ts DESC LIMIT ?",
                (user_id, limit)
            ).fetchall()
        return [dict(r) for r in rows]

@app.post("/api/entries", status_code=201)
@limiter.limit("20/minute")
def add_entry(request: Request, entry: EntryIn, user_id: str = Depends(get_current_user)):
    ts_value = parse_ts_or_400(entry.ts)
    food_name = entry.food.strip()
    if not food_name:
        raise HTTPException(400, "food cannot be empty")
    with db_conn() as conn:
        # upsert into foods catalogue per user
        conn.execute(
            "INSERT OR IGNORE INTO foods(name, user_id) VALUES(?,?)",
            (food_name, user_id)
        )
        cur = conn.execute(
            "INSERT INTO entries(ts, food, cat, notes, free_notes, user_id) VALUES(?,?,?,?,?,?)",
            (ts_value, food_name, entry.cat or "", entry.notes or "", entry.free_notes or "", user_id)
        )
        row = conn.execute(
            "SELECT * FROM entries WHERE id=? AND user_id=?", (cur.lastrowid, user_id)
        ).fetchone()
        return dict(row)

@app.put("/api/entries/{entry_id}")
@limiter.limit("20/minute")
def update_entry(request: Request, entry_id: int, data: EntryUpdate, user_id: str = Depends(get_current_user)):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM entries WHERE id=? AND user_id=?", (entry_id, user_id)
        ).fetchone()
        if not row:
            raise HTTPException(404, "entry not found or access denied")
        ts    = parse_ts_or_400(data.ts) if data.ts is not None else row["ts"]
        food  = data.food  if data.food  is not None else row["food"]
        cat   = data.cat   if data.cat   is not None else row["cat"]
        notes = data.notes if data.notes is not None else row["notes"]
        free_notes = data.free_notes if data.free_notes is not None else row["free_notes"]
        food = food.strip()
        if not food:
            raise HTTPException(400, "food cannot be empty")
        conn.execute(
            "UPDATE entries SET ts=?, food=?, cat=?, notes=?, free_notes=? WHERE id=? AND user_id=?",
            (ts, food, cat, notes, free_notes, entry_id, user_id)
        )
        conn.execute("INSERT OR IGNORE INTO foods(name, user_id) VALUES(?,?)", (food, user_id))
        updated = conn.execute(
            "SELECT * FROM entries WHERE id=? AND user_id=?", (entry_id, user_id)
        ).fetchone()
        return dict(updated)

@app.delete("/api/entries/{entry_id}", status_code=204)
@limiter.limit("20/minute")
def delete_entry(request: Request, entry_id: int, user_id: str = Depends(get_current_user)):
    with db_conn() as conn:
        r = conn.execute(
            "SELECT id FROM entries WHERE id=? AND user_id=?", (entry_id, user_id)
        ).fetchone()
        if not r:
            raise HTTPException(404, "entry not found or access denied")
        conn.execute("DELETE FROM entries WHERE id=?", (entry_id,))

# ── Foods (autocomplete) ──────────────────────────────────────────────────────
@app.get("/api/foods")
@limiter.limit("60/minute")
def search_foods(request: Request, q: str = Query("", min_length=0), user_id: str = Depends(get_current_user)):
    q = q.strip()
    with db_conn() as conn:
        if q:
            pattern = f"%{q}%"
            rows = conn.execute(
                "SELECT name FROM foods WHERE user_id=? AND name LIKE ? ORDER BY name ASC LIMIT 30",
                (user_id, pattern)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT name FROM foods WHERE user_id=? ORDER BY name ASC LIMIT 30",
                (user_id,)
            ).fetchall()
        return [r["name"] for r in rows]
 
@app.get("/api/quantities")
@limiter.limit("60/minute")
def search_quantities(request: Request, q: str = Query("", min_length=0), user_id: str = Depends(get_current_user)):
    q = q.strip()
    with db_conn() as conn:
        if q:
            pattern = f"%{q}%"
            rows = conn.execute(
                "SELECT DISTINCT notes FROM entries WHERE user_id=? AND notes LIKE ? AND notes != '' ORDER BY notes ASC LIMIT 30",
                (user_id, pattern)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT notes FROM entries WHERE user_id=? AND notes != '' ORDER BY notes ASC LIMIT 30",
                (user_id,)
            ).fetchall()
        return [r["notes"] for r in rows]

@app.delete("/api/foods/{name}", status_code=204)
@limiter.limit("20/minute")
def delete_food(request: Request, name: str, user_id: str = Depends(get_current_user)):
    with db_conn() as conn:
        conn.execute("DELETE FROM foods WHERE name=? AND user_id=?", (name, user_id))

# ── Export ────────────────────────────────────────────────────────────────────
@app.get("/api/export/csv")
@limiter.limit("10/minute")
def export_csv(request: Request, user_id: str = Depends(get_current_user)):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT id, ts, food, cat, notes, free_notes, created FROM entries WHERE user_id=? ORDER BY ts ASC",
            (user_id,)
        ).fetchall()
    buf = io.StringIO()
    # UTF-8 BOM per Excel
    buf.write('\ufeff')
    # Formato italiano: separatore punto e virgola
    writer = csv.writer(buf, delimiter=';')
    writer.writerow(["id", "data", "tipo", "ora", "cibo", "quantità", "note_libere", "data_creazione", "ora_creazione"])
    for r in rows:
        # Gestione timestamp pasto (ts)
        try:
            dt_pasto = datetime.fromisoformat(r["ts"])
            d_pasto = dt_pasto.strftime("%d/%m/%Y")
            t_pasto = dt_pasto.strftime("%H:%M")
        except:
            pts = r["ts"].split("T")
            d_pasto = pts[0]
            t_pasto = pts[1] if len(pts) > 1 else ""
        
        # Inserimento categoria (tipo)
        cat_val = r["cat"] if "cat" in r.keys() else ""
        
        # Gestione timestamp creazione (created)
        try:
            # datetime.fromisoformat gestisce anche lo spazio invece della T
            dt_crea = datetime.fromisoformat(r["created"])
            d_crea = dt_crea.strftime("%d/%m/%Y")
            t_crea = dt_crea.strftime("%H:%M:%S")
        except:
            pct = r["created"].split(" ")
            d_crea = pct[0]
            t_crea = pct[1] if len(pct) > 1 else ""
        writer.writerow([r["id"], d_pasto, cat_val, t_pasto, r["food"], r["notes"], r["free_notes"], d_crea, t_crea])
    
    filename = f"food_diary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/api/export/json")
@limiter.limit("10/minute")
def export_json(request: Request, user_id: str = Depends(get_current_user)):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT id, ts, food, cat, notes, free_notes, created FROM entries WHERE user_id=? ORDER BY ts ASC",
            (user_id,)
        ).fetchall()
    data = [dict(r) for r in rows]
    buf = json.dumps(data, ensure_ascii=False, indent=2)
    filename = f"food_diary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    return StreamingResponse(
        iter([buf]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# ── AI Analysis (Google Gemini) ────────────────────────────────────────────────
@app.post("/api/analyze-food-image")
@limiter.limit("5/minute")
async def analyze_food_image(request: Request, file: UploadFile = File(...), admin_id: str = Depends(get_admin_user)):
    if not GEMINI_KEY:
        raise HTTPException(500, "GEMINI_API_KEY non configurata")
    
    contents = await file.read()
    b64_image = base64.b64encode(contents).decode('utf-8')
    
    prompt = (
        "Analizza questa immagine. Se l'immagine non contiene cibo riconoscibile, "
        "restituisci esclusivamente questo JSON: {\"error\": \"no_food\"}\n"
        "Altrimenti, identifica il piatto e restituisci un JSON con questi campi: "
        "'food' (nome del cibo in italiano), "
        "'quantity' (stima porzione, es. '1 piatto', '100g'), "
        "'cat' (una tra: colazione, pranzo, snack, cena, dopocena)."
    )
    
    # Gemini v1beta logic
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": GEMINI_KEY,
        "User-Agent": "curl/7.81.0"
    }
    
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": b64_image
                    }
                }
            ]
        }],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, headers=headers, timeout=60.0)
            resp.raise_for_status()
            data = resp.json()
            
            # Estrai il testo JSON dalla risposta di Gemini
            text_resp = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text_resp)
        except Exception as e:
            raise HTTPException(500, f"Errore Gemini AI: {str(e)}")

# ── Favicon & Manifest ────────────────────────────────────────────────────────
@app.get("/favicon.ico")
async def favicon_ico(): return FileResponse(os.path.join(BASE_DIR, "static", "favicon.ico"))

@app.get("/favicon.svg")
async def favicon_svg(): return FileResponse(os.path.join(BASE_DIR, "static", "favicon.svg"))

@app.get("/favicon-96x96.png")
async def favicon_96(): return FileResponse(os.path.join(BASE_DIR, "static", "favicon-96x96.png"))

@app.get("/apple-touch-icon.png")
async def apple_icon(): return FileResponse(os.path.join(BASE_DIR, "static", "apple-touch-icon.png"))

@app.get("/site.webmanifest")
async def manifest(): return FileResponse(os.path.join(BASE_DIR, "static", "site.webmanifest"))

@app.get("/web-app-manifest-192x192.png")
async def manifest_192(): return FileResponse(os.path.join(BASE_DIR, "static", "web-app-manifest-192x192.png"))

@app.get("/web-app-manifest-512x512.png")
async def manifest_512(): return FileResponse(os.path.join(BASE_DIR, "static", "web-app-manifest-512x512.png"))

# ── Frontend ──────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def index():
    html_path = os.path.join(BASE_DIR, "static", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/settings", response_class=HTMLResponse)
def settings():
    html_path = os.path.join(BASE_DIR, "static", "settings.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

# Static assets mount (fallback)
app.mount("/", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
