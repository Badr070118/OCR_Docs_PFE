import os
from typing import Generator

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://ocr_user:ocr_password@localhost:55432/ocr_db",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    file_name = Column(String, nullable=False)
    data = Column(JSONB, nullable=False)
    raw_text = Column(Text, nullable=True)
    llama_output = Column(Text, nullable=True)
    date_uploaded = Column(DateTime(timezone=True), server_default=func.now())


def create_db_and_tables() -> None:
    # Create the documents table if it does not exist.
    Base.metadata.create_all(bind=engine)
    # Backfill new columns when upgrading existing databases.
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS raw_text TEXT")
        )
        connection.execute(
            text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS llama_output TEXT")
        )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def save_document(
    db: Session, file_name: str, data: dict, raw_text: str | None = None
) -> Document:
    document = Document(file_name=file_name, data=data, raw_text=raw_text)
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def update_llama_output(
    db: Session, document_id: int, llama_output: str
) -> Document | None:
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        return None
    document.llama_output = llama_output
    db.commit()
    db.refresh(document)
    return document


def update_document_data(
    db: Session, document_id: int, data: dict
) -> Document | None:
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        return None
    document.data = data
    db.commit()
    db.refresh(document)
    return document
