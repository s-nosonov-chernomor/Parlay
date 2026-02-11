# scripts/print_routes.py
from __future__ import annotations

import os
from pathlib import Path

def load_env():
    # гарантируем корневую папку проекта
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)

    # если используешь python-dotenv:
    try:
        from dotenv import load_dotenv
        load_dotenv(root / ".env")
    except Exception:
        pass

def main():
    load_env()

    # диагностика (на время)
    print("CWD:", os.getcwd())
    print("DB_URL exists:", bool(os.getenv("DB_URL")))
    print("MQTT_HOST exists:", bool(os.getenv("MQTT_HOST")))

    from app.main import app

    for r in app.routes:
        methods = ",".join(sorted(getattr(r, "methods", []) or []))
        path = getattr(r, "path", "")
        name = getattr(r, "name", "")
        if methods and path:
            print(f"{methods:12} {path:40} {name}")

if __name__ == "__main__":
    main()
