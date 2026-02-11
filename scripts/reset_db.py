# scripts/reset_db.py
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# грузим .env из корня проекта (где запускаешь скрипт)
load_dotenv()

db_url = os.getenv("DB_URL")
if not db_url:
    raise SystemExit("DB_URL is missing. Create .env in project root and set DB_URL=...")

engine = create_engine(db_url, pool_pre_ping=True)

with engine.begin() as conn:
    conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE;"))
    conn.execute(text("CREATE SCHEMA public;"))
    conn.execute(text("GRANT ALL ON SCHEMA public TO public;"))
    conn.execute(text("COMMENT ON SCHEMA public IS 'standard public schema';"))

print("OK: public schema reset")
