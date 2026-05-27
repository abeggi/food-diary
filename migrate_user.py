import os
import sqlite3
import firebase_admin
from firebase_admin import credentials, auth
from dotenv import load_dotenv

# Config
load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.environ.get("FOOD_DIARY_DB", os.path.join(BASE_DIR, "data/food_diary.db"))
SACC_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")

# User to migrate
TARGET_EMAIL = "abeggi@gmail.com"

def migrate():
    # 1. Firebase Init
    if not SACC_JSON:
        print("Error: FIREBASE_SERVICE_ACCOUNT_JSON not found in .env")
        return
    
    import json
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write(SACC_JSON)
        f_path = f.name
    
    cred = credentials.Certificate(f_path)
    firebase_admin.initialize_app(cred)

    # 2. Find User UID
    try:
        user = auth.get_user_by_email(TARGET_EMAIL)
        new_uid = user.uid
        print(f"Found user {TARGET_EMAIL} with UID: {new_uid}")
    except Exception as e:
        print(f"Error finding user {TARGET_EMAIL}: {str(e)}")
        return

    # 3. Update DB
    db_to_use = DB_PATH
    if not os.path.exists(db_to_use):
        print(f"Database not found at {db_to_use}")
        # Try local fallback
        db_local = os.path.join(BASE_DIR, "food_diary.db")
        if os.path.exists(db_local):
            db_to_use = db_local
            print(f"Using local database: {db_to_use}")
        else:
            return

    conn = sqlite3.connect(db_to_use)
    try:
        # Update entries
        cur = conn.execute("UPDATE entries SET user_id = ? WHERE user_id = 'dev_user'", (new_uid,))
        print(f"Migrated {cur.rowcount} entries to {new_uid}")
        
        # Update foods
        cur = conn.execute("UPDATE foods SET user_id = ? WHERE user_id = 'dev_user'", (new_uid,))
        print(f"Migrated {cur.rowcount} food suggestions to {new_uid}")
        
        conn.commit()
    except Exception as e:
        print(f"DB Error: {str(e)}")
    finally:
        conn.close()
        os.unlink(f_path)

if __name__ == "__main__":
    migrate()
