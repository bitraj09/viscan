"""Environment-backed application configuration."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
PROVIDER = os.getenv("LLM_PROVIDER", "mock").strip().lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
APP_ENV = os.getenv("APP_ENV", "development")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(ROOT / 'data' / 'viscan.db').as_posix()}")

def active_provider() -> str:
    return "gemini" if PROVIDER == "gemini" and GEMINI_API_KEY else "mock"
