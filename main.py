from fastapi import FastAPI, HTTPException, Query, UploadFile, File
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
import firebase_admin
from firebase_admin import credentials, auth
from fastapi import Depends, Header

# ── Config ────────────────────────────────────────────────────────────────────
load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.environ.get("FOOD_DIARY_DB", os.path.join(BASE_DIR, "food_diary.db"))

# AI config (Google Gemini)
GEMINI_KEY    = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL  = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
ADMIN_EMAIL   = os.environ.get("ADMIN_EMAIL", "abeggi@gmail.com")

# Firebase admin init
FIREBASE_SACC_PATH = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
if FIREBASE_SACC_PATH and os.path.exists(FIREBASE_SACC_PATH):
    cred = credentials.Certificate(FIREBASE_SACC_PATH)
    firebase_admin.initialize_app(cred)
elif os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON"):
    # Carica da stringa JSON (utile per Docker/Env)
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write(os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON"))
        f_path = f.name
    cred = credentials.Certificate(f_path)
    firebase_admin.initialize_app(cred)
else:
    # Modalità sviluppo senza firebase service account
    print("Warning: FIREBASE_SERVICE_ACCOUNT non configurato. Autenticazione disattivata.")

app = FastAPI(title="Food Diary", version="1.0.0")

# ── Auth Dependency ──────────────────────────────────────────────────────────
async def get_current_user(authorization: Optional[str] = Header(None)):
    """Estrae e verifica il token Firebase, o restituisce un utente mock in dev mode."""
    if not authorization:
        # Se non c'è header, in modalità dev usiamo un utente di default
        if not firebase_admin._apps:
            return "dev_user"
        raise HTTPException(401, "Missing authorization header")
    
    token = authorization.replace("Bearer ", "")
    try:
        if not firebase_admin._apps:
             return "dev_user" # fallback anche se il token c'è ma firebase non è init
        decoded_token = auth.verify_id_token(token)
        return decoded_token['uid']
    except Exception as e:
        raise HTTPException(401, f"Invalid token: {str(e)}")

async def get_admin_user(authorization: Optional[str] = Header(None)):
    """Verifica che l'utente sia un amministratore."""
    if not authorization and not firebase_admin._apps:
        return "dev_user" # admin in dev mode
    
    token = (authorization or "").replace("Bearer ", "")
    try:
        decoded_token = auth.verify_id_token(token)
        user_email = decoded_token.get('email', '')
        if user_email == ADMIN_EMAIL:
            return decoded_token['uid']
        raise HTTPException(403, "Access denied: Admin only")
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        raise HTTPException(401, f"Invalid token: {str(e)}")

@app.get("/api/me")
async def get_me(authorization: Optional[str] = Header(None)):
    """Restituisce info sull'utente corrente (inclusi i ruoli)."""
    if not authorization and not firebase_admin._apps:
        return {"uid": "dev_user", "email": "dev@local", "is_admin": True}
    
    token = authorization.replace("Bearer ", "")
    try:
        decoded_token = auth.verify_id_token(token)
        return {
            "uid": decoded_token['uid'],
            "email": decoded_token.get('email', ''),
            "is_admin": decoded_token.get('email') == ADMIN_EMAIL
        }
    except:
        raise HTTPException(401)

# ── Admin API ─────────────────────────────────────────────────────────────────
@app.get("/api/admin/users")
def admin_list_users(admin_id: str = Depends(get_admin_user)):
    """Elenca tutti gli utenti registrati su Firebase (per l'admin)."""
    if not firebase_admin._apps:
        return [{"uid": "dev_user", "email": "dev@local", "display_name": "Dev User"}]
    
    users = []
    page = auth.list_users()
    while page:
        for user in page.users:
            users.append({
                "uid": user.uid,
                "email": user.email,
                "display_name": user.display_name,
                "created": datetime.fromtimestamp(user.user_metadata.creation_timestamp / 1000).isoformat() if user.user_metadata.creation_timestamp else None
            })
        page = page.get_next_page()
    return users

@app.delete("/api/admin/users/{uid}", status_code=204)
def admin_delete_user(uid: str, admin_id: str = Depends(get_admin_user)):
    """Elimina definitivamente un utente da Firebase e rimuove i suoi dati dal DB."""
    if not firebase_admin._apps:
        # Dev mode mock delete
        return
        
    try:
        # 1. Firebase delete
        auth.delete_user(uid)
        
        # 2. Database cleanup
        with db_conn() as conn:
            conn.execute("DELETE FROM entries WHERE user_id=?", (uid,))
            conn.execute("DELETE FROM foods WHERE user_id=?", (uid,))
            
    except Exception as e:
        raise HTTPException(500, f"Errore durante l'eliminazione: {str(e)}")

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

class EntryUpdate(BaseModel):
    ts:    Optional[str]  = None
    food:  Optional[str]  = None
    cat:   Optional[str]  = None
    notes: Optional[str]  = None

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
def list_entries(
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
def add_entry(entry: EntryIn, user_id: str = Depends(get_current_user)):
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
            "INSERT INTO entries(ts, food, cat, notes, user_id) VALUES(?,?,?,?,?)",
            (ts_value, food_name, entry.cat or "", entry.notes or "", user_id)
        )
        row = conn.execute(
            "SELECT * FROM entries WHERE id=? AND user_id=?", (cur.lastrowid, user_id)
        ).fetchone()
        return dict(row)

@app.put("/api/entries/{entry_id}")
def update_entry(entry_id: int, data: EntryUpdate, user_id: str = Depends(get_current_user)):
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
        food = food.strip()
        if not food:
            raise HTTPException(400, "food cannot be empty")
        conn.execute(
            "UPDATE entries SET ts=?, food=?, cat=?, notes=? WHERE id=? AND user_id=?",
            (ts, food, cat, notes, entry_id, user_id)
        )
        conn.execute("INSERT OR IGNORE INTO foods(name, user_id) VALUES(?,?)", (food, user_id))
        updated = conn.execute(
            "SELECT * FROM entries WHERE id=?", (entry_id,)
        ).fetchone()
        return dict(updated)

@app.delete("/api/entries/{entry_id}", status_code=204)
def delete_entry(entry_id: int, user_id: str = Depends(get_current_user)):
    with db_conn() as conn:
        r = conn.execute(
            "SELECT id FROM entries WHERE id=? AND user_id=?", (entry_id, user_id)
        ).fetchone()
        if not r:
            raise HTTPException(404, "entry not found or access denied")
        conn.execute("DELETE FROM entries WHERE id=?", (entry_id,))

# ── Foods (autocomplete) ──────────────────────────────────────────────────────
@app.get("/api/foods")
def search_foods(q: str = Query("", min_length=0), user_id: str = Depends(get_current_user)):
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
def search_quantities(q: str = Query("", min_length=0), user_id: str = Depends(get_current_user)):
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
def delete_food(name: str, user_id: str = Depends(get_current_user)):
    with db_conn() as conn:
        conn.execute("DELETE FROM foods WHERE name=? AND user_id=?", (name, user_id))

# ── Export ────────────────────────────────────────────────────────────────────
@app.get("/api/export/csv")
def export_csv(user_id: str = Depends(get_current_user)):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT id, ts, food, cat, notes, created FROM entries WHERE user_id=? ORDER BY ts ASC",
            (user_id,)
        ).fetchall()
    buf = io.StringIO()
    # UTF-8 BOM per Excel
    buf.write('\ufeff')
    # Formato italiano: separatore punto e virgola
    writer = csv.writer(buf, delimiter=';')
    writer.writerow(["id", "data", "tipo", "ora", "cibo", "quantità", "data_creazione", "ora_creazione"])
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
        writer.writerow([r["id"], d_pasto, cat_val, t_pasto, r["food"], r["notes"], d_crea, t_crea])
    
    filename = f"food_diary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/api/export/json")
def export_json(user_id: str = Depends(get_current_user)):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT id, ts, food, cat, notes, created FROM entries WHERE user_id=? ORDER BY ts ASC",
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
async def analyze_food_image(file: UploadFile = File(...), user_id: str = Depends(get_current_user)):
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
