from fastapi import FastAPI, HTTPException, Query
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

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.environ.get("FOOD_DIARY_DB", os.path.join(BASE_DIR, "food_diary.db"))

app = FastAPI(title="Food Diary", version="1.0.0")

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
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                name  TEXT    NOT NULL UNIQUE COLLATE NOCASE
            );
            CREATE INDEX IF NOT EXISTS idx_entries_ts ON entries(ts);
            CREATE INDEX IF NOT EXISTS idx_foods_name ON foods(name);
        """)
        # Migration: add 'cat' column if not present
        try:
            conn.execute("ALTER TABLE entries ADD COLUMN cat TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass # column already exists

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
    limit: int = Query(200, le=1000)
):
    with db_conn() as conn:
        if date:
            rows = conn.execute(
                "SELECT * FROM entries WHERE ts LIKE ? ORDER BY ts ASC LIMIT ?",
                (f"{date}%", limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM entries ORDER BY ts DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

@app.post("/api/entries", status_code=201)
def add_entry(entry: EntryIn):
    ts_value = parse_ts_or_400(entry.ts)
    food_name = entry.food.strip()
    if not food_name:
        raise HTTPException(400, "food cannot be empty")
    with db_conn() as conn:
        # upsert into foods catalogue
        conn.execute(
            "INSERT OR IGNORE INTO foods(name) VALUES(?)",
            (food_name,)
        )
        cur = conn.execute(
            "INSERT INTO entries(ts, food, cat, notes) VALUES(?,?,?,?)",
            (ts_value, food_name, entry.cat or "", entry.notes or "")
        )
        row = conn.execute(
            "SELECT * FROM entries WHERE id=?", (cur.lastrowid,)
        ).fetchone()
        return dict(row)

@app.put("/api/entries/{entry_id}")
def update_entry(entry_id: int, data: EntryUpdate):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM entries WHERE id=?", (entry_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "entry not found")
        ts    = parse_ts_or_400(data.ts) if data.ts is not None else row["ts"]
        food  = data.food  if data.food  is not None else row["food"]
        cat   = data.cat   if data.cat   is not None else row["cat"]
        notes = data.notes if data.notes is not None else row["notes"]
        food = food.strip()
        if not food:
            raise HTTPException(400, "food cannot be empty")
        conn.execute(
            "UPDATE entries SET ts=?, food=?, cat=?, notes=? WHERE id=?",
            (ts, food, cat, notes, entry_id)
        )
        conn.execute("INSERT OR IGNORE INTO foods(name) VALUES(?)", (food,))
        updated = conn.execute(
            "SELECT * FROM entries WHERE id=?", (entry_id,)
        ).fetchone()
        return dict(updated)

@app.delete("/api/entries/{entry_id}", status_code=204)
def delete_entry(entry_id: int):
    with db_conn() as conn:
        r = conn.execute(
            "SELECT id FROM entries WHERE id=?", (entry_id,)
        ).fetchone()
        if not r:
            raise HTTPException(404, "entry not found")
        conn.execute("DELETE FROM entries WHERE id=?", (entry_id,))

# ── Foods (autocomplete) ──────────────────────────────────────────────────────
@app.get("/api/foods")
def search_foods(q: str = Query("", min_length=0)):
    q = q.strip()
    with db_conn() as conn:
        if q:
            pattern = f"%{q}%"
            rows = conn.execute(
                "SELECT name FROM foods WHERE name LIKE ? ORDER BY name ASC LIMIT 30",
                (pattern,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT name FROM foods ORDER BY name ASC LIMIT 30"
            ).fetchall()
        return [r["name"] for r in rows]

@app.delete("/api/foods/{name}", status_code=204)
def delete_food(name: str):
    with db_conn() as conn:
        conn.execute("DELETE FROM foods WHERE name=?", (name,))

# ── Export ────────────────────────────────────────────────────────────────────
@app.get("/api/export/csv")
def export_csv():
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT id, ts, food, cat, notes, created FROM entries ORDER BY ts ASC"
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
def export_json():
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT id, ts, food, cat, notes, created FROM entries ORDER BY ts ASC"
        ).fetchall()
    data = [dict(r) for r in rows]
    buf = json.dumps(data, ensure_ascii=False, indent=2)
    filename = f"food_diary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    return StreamingResponse(
        iter([buf]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

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
