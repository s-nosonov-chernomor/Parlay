from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.settings import get_settings
settings = get_settings()

engine = create_engine(
    settings.db_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
