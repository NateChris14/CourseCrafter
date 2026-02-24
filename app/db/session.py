from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.settings import settings

# Optimized database engine with connection pooling
engine = create_engine(
    settings.database_url,
    pool_size=20,          # Number of connections to keep in pool
    max_overflow=30,        # Max connections beyond pool size
    pool_pre_ping=True,     # Validate connections
    pool_recycle=3600,     # Recycle connections every hour
    echo=False               # Disable SQL logging for performance
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

