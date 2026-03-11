from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

DATABASE_URL = "sqlite:///./chat_app.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}  # SQLite only
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency to get DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    """Create all tables in the database."""
    from app.models.user import User
    from app.models.message import Message
    from app.models.private_room import PrivateRoom
    Base.metadata.create_all(bind=engine)
    _run_migrations()


def _run_migrations():
    """Fix any data issues from older versions."""
    try:
        with engine.connect() as conn:
            now = datetime.utcnow().isoformat()
            conn.execute(text(f"UPDATE users SET created_at = '{now}' WHERE created_at IS NULL"))
            # Add is_admin column if not exists
            try:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0"))
            except Exception:
                pass  # Column already exists
            # Make first user admin automatically
            conn.execute(text("UPDATE users SET is_admin = 1 WHERE id = (SELECT MIN(id) FROM users)"))
            conn.commit()
    except Exception as e:
        print(f"Migration warning: {e}")
