"""SQLAlchemy models and connection pool for the local SQLite database."""
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from app.config import DATABASE_URL

class Base(DeclarativeBase):
    pass

class Patient(Base):
    __tablename__ = "patients"
    patient_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    birth_year: Mapped[int] = mapped_column(Integer, nullable=False)

class Report(Base):
    __tablename__ = "reports"
    report_id: Mapped[str] = mapped_column(String, primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id"), nullable=False)
    report_type: Mapped[str] = mapped_column(String, nullable=False)
    date: Mapped[str] = mapped_column(String, nullable=False)
    findings: Mapped[str] = mapped_column(Text, nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)

class SavedDraft(Base):
    __tablename__ = "saved_drafts"
    draft_id: Mapped[str] = mapped_column(String, primary_key=True)
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    edited_report: Mapped[str] = mapped_column(Text, nullable=False)
    clinician_reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
