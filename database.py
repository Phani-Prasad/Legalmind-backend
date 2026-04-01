"""
Legaify - Database Layer
SQLite-backed document store using SQLModel.
Replaces the previous in-memory DOC_STORE dict.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import SQLModel, Field, Session, create_engine, select

# ── Database Setup ─────────────────────────────────────────────────────────────

DATABASE_URL = "sqlite:///./legalmind.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}  # required for SQLite + FastAPI
)

def init_db():
    """Create all tables if they don't exist."""
    # Import models here to ensure they are registered with SQLModel metadata
    from auth import User 
    SQLModel.metadata.create_all(engine)


# ── Models ─────────────────────────────────────────────────────────────────────

class Document(SQLModel, table=True):
    """Stores uploaded document text for RAG-lite chat and summarization."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    filename: str
    text: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── CRUD Helpers ───────────────────────────────────────────────────────────────

def save_document(filename: str, text: str) -> str:
    """
    Persist a new document and return its unique ID.
    Also runs cleanup of documents older than 24 hours.
    """
    doc = Document(filename=filename, text=text)
    with Session(engine) as session:
        session.add(doc)
        session.commit()
        session.refresh(doc)
        doc_id = doc.id

    # Cleanup stale docs in the background (non-blocking)
    _cleanup_old_documents()

    return doc_id


def get_document(doc_id: str) -> Optional[Document]:
    """
    Retrieve a document by ID.
    Returns None if not found.
    """
    with Session(engine) as session:
        return session.get(Document, doc_id)


def _cleanup_old_documents(max_age_hours: int = 24):
    """
    Delete documents older than max_age_hours.
    Called automatically on each new upload.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    with Session(engine) as session:
        old_docs = session.exec(
            select(Document).where(Document.created_at < cutoff)
        ).all()
        for doc in old_docs:
            session.delete(doc)
        session.commit()
