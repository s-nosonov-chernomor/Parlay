# app/db/models_all.py
from __future__ import annotations

# Важно: эти импорты "регистрируют" модели в Base.metadata
from app.db.models import *  # noqa
from app.db.models_ui import *  # noqa
from app.db.models_power import *  # noqa
from app.db.models_sources import *  # noqa
