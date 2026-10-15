"""Synthetic-data dental assistant API. All demo behavior is deterministic."""
from __future__ import annotations
import json, os, re, sqlite3, uuid
from contextlib import contextmanager, asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator
from app.config import active_provider, GEMINI_MODEL
from app.gemini_adapter import GeminiAdapter, GeminiUnavailable, claims_supported
from app.local_adapter import LocalDraftAdapter, LocalModelUnavailable, DEFAULT_LOCAL_MODEL
from app.db import Base, engine
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB_PATH = Path(os.getenv("VIS_SCAN_DB", str(DATA / "viscan.db")))

class QueryRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    session_id: str = Field(default="default", min_length=1, max_length=80)

class DraftRequest(BaseModel):
    transcript: str = Field(min_length=1, max_length=3000)
    session_id: str = Field(default="default", min_length=1, max_length=80)

    @field_validator("transcript")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Transcript cannot be blank")
        return value.strip()

class Finding(BaseModel):
    observation: str
    anatomical_site: str | None = None
    uncertainty: str | None = None
    source_text: str = ""
    source: str = "clinician_transcript"

class DraftReport(BaseModel):
    draft_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    findings: list[Finding]
    draft_report: str
    transcript: str
    requires_clinician_review: bool = True
    status: str = "draft"
    modality_notice: str = "Generated from text transcript only; no image was analyzed."
    provider: str = "mock"

class FollowUpRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    session_id: str = Field(default="default", min_length=1, max_length=80)

class SaveDraftRequest(BaseModel):
    draft: DraftReport
    edited_report: str = Field(min_length=1, max_length=5000)
    clinician_reviewed: bool = False

class SelectReportRequest(BaseModel):
    report_id: str = Field(min_length=1, max_length=30)
    session_id: str = Field(default="default", min_length=1, max_length=80)

@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # The SQLAlchemy engine owns connection pooling; compact parameterized DB-API
    # statements keep this synthetic-data demo explicit and easy to audit.
    pooled = engine.raw_connection()
    db = pooled.driver_connection
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        pooled.close()

def init_db():
    database_url = make_url(os.getenv("DATABASE_URL", "sqlite:///./data/viscan.db"))
    if database_url.get_backend_name() == "sqlite" and database_url.database not in (None, ":memory:"):
        database_file = Path(database_url.database)
        if not database_file.is_absolute(): database_file = Path.cwd() / database_file
        database_file.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    with connect() as db:
        db.executescript("CREATE TABLE IF NOT EXISTS patients(patient_id TEXT PRIMARY KEY,name TEXT NOT NULL,birth_year INTEGER NOT NULL); CREATE TABLE IF NOT EXISTS reports(report_id TEXT PRIMARY KEY,patient_id TEXT NOT NULL REFERENCES patients(patient_id),report_type TEXT NOT NULL,date TEXT NOT NULL,findings TEXT NOT NULL,excerpt TEXT NOT NULL); CREATE TABLE IF NOT EXISTS saved_drafts(draft_id TEXT PRIMARY KEY,transcript TEXT NOT NULL,payload TEXT NOT NULL,edited_report TEXT NOT NULL,clinician_reviewed INTEGER NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);")
        count = db.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
        if not count:
            entries = json.loads((DATA / "synthetic_reports.json").read_text(encoding="utf-8"))
            for p in {e['patient_id']: e for e in entries}.values():
                db.execute("INSERT INTO patients VALUES(?,?,?)", (p['patient_id'], p['name'], p['birth_year']))
            for e in entries:
                db.execute("INSERT INTO reports VALUES(?,?,?,?,?,?)", (e['report_id'],e['patient_id'],e['report_type'],e['date'],json.dumps(e['findings']),e['excerpt']))
        db.commit()

def patient_search(query: str = "", patient_id: str | None = None) -> list[dict[str, Any]]:
    with connect() as db:
        if patient_id:
            rows = db.execute("SELECT * FROM patients WHERE patient_id=?", (patient_id.upper(),)).fetchall()
        else:
            q = query.casefold().strip()
            rows = db.execute("SELECT * FROM patients ORDER BY name").fetchall()
            rows = [r for r in rows if q in r['name'].casefold() or q in r['patient_id'].casefold()]
        return [dict(r) for r in rows]

def list_reports(patient_id: str, report_type: str | None = None) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("SELECT * FROM reports WHERE patient_id=? ORDER BY date DESC, report_id", (patient_id,)).fetchall()
        result = [dict(r) for r in rows if not report_type or r['report_type'].casefold() == report_type.casefold()]
        for r in result: r['findings'] = json.loads(r['findings'])
        return result

def get_report(report_id: str) -> dict[str, Any] | None:
    with connect() as db:
        r = db.execute("SELECT r.*,p.name,p.birth_year FROM reports r JOIN patients p USING(patient_id) WHERE report_id=?", (report_id.upper(),)).fetchone()
        if not r: return None
        result = dict(r); result['findings'] = json.loads(result['findings']); return result

def parse_retrieval(text: str) -> dict[str, Any]:
    t = text.strip()
    pid = re.search(r'\bP\d{3}\b', t, re.I)
    report_type = next((typ for typ in ('OPG','BITEWING') if typ.casefold() in t.casefold()), None)
    latest = bool(re.search(r'\b(latest|most recent|newest)\b',t,re.I))
    # Remove command words/type/date qualifiers; preserve name phrases for exact substring matching.
    q = re.sub(r"(?i)\b(open|show|find|retrieve|load|the|latest|most recent|newest|report|patient|dental|dated|for|of|my)\b", " ", t)
    if report_type: q = re.sub(report_type, " ", q, flags=re.I)
    q = re.sub(r"'s\b", " ", q, flags=re.I)
    q = re.sub(r"[^\w\s]", " ", q)
    return {"intent":"retrieve_report", "patient_id":pid.group(0).upper() if pid else None, "query":re.sub(r"\s+"," ",q).strip(), "report_type":report_type, "latest":latest}

def retrieve(text: str) -> dict[str, Any]:
    parsed = parse_retrieval(text)
    matches = patient_search(parsed['query'], parsed['patient_id'])
    if len(matches) > 1:
        return {"status":"clarification_required","message":"More than one synthetic patient matches. Select the intended patient.","options":[{"patient_id":p['patient_id'],"name":p['name']} for p in matches]}
    if not matches:
        return {"status":"not_found","message":"No matching synthetic patient was found."}
    patient = matches[0]
    reports = list_reports(patient['patient_id'], parsed['report_type'])
    if not reports:
        return {"status":"not_found","message":"No matching report was found for this synthetic patient.","patient":patient}
    report = reports[0]
    return {"status":"ok","intent":parsed['intent'],"patient":patient,"report":report,"source":{"report_id":report['report_id'],"excerpt":report['excerpt']}}

def create_draft(transcript: str) -> DraftReport:
    raw = transcript.strip()
    if not raw or len(raw) < 5:
        return DraftReport(findings=[],draft_report="Transcript is too brief or unclear to structure. Please review and clarify.",transcript=raw)
    # Keep the clinician's exact words; no medical inference or normalization.
    uncertainty = "unclear or hedged wording preserved" if re.search(r'\b(possible|possibly|maybe|unclear|uncertain)\b|\?', raw, re.I) else None
    site_match = re.search(r'\b(upper|lower)\s+(left|right)\s+(?:third\s+molar|quadrant|region|anterior teeth)\b|\btooth\s+\d{1,2}\b', raw, re.I)
    site = site_match.group(0) if site_match else None
    # Avoid broad clinical paraphrase: one observation contains the exact transcript.
    return DraftReport(findings=[Finding(observation=raw, anatomical_site=site, uncertainty=uncertainty, source_text=raw)],draft_report=f"Clinician-provided observation: {raw}",transcript=raw)

def generate_draft(transcript: str, session_id: str = "default") -> DraftReport:
    configured = PROVIDER_SESSIONS.get(session_id)
    provider = configured.get("provider") if configured else active_provider()
    if provider == "local":
        model_id = configured.get("model", DEFAULT_LOCAL_MODEL) if configured else DEFAULT_LOCAL_MODEL
        class LocalDraft(BaseModel):
            findings: list[Finding]
            draft_report: str
        try:
            result = LocalDraftAdapter(model_id).draft(transcript, LocalDraft)
            if not claims_supported(result, transcript):
                raise LocalModelUnavailable("Local model output included wording not supported by the transcript; review or use mock mode.")
            return DraftReport(findings=result['findings'], draft_report=result['draft_report'], transcript=transcript, provider="local")
        except LocalModelUnavailable as exc:
            raise GeminiUnavailable(str(exc)) from exc
    if provider != "gemini":
        return create_draft(transcript)
    class GeminiDraft(BaseModel):
        findings: list[Finding]
        draft_report: str
    try:
        adapter = GeminiAdapter(api_key=configured.get("api_key"), model=configured.get("model")) if configured else GeminiAdapter()
        result = adapter.draft(transcript, GeminiDraft)
        if not claims_supported(result, transcript):
            raise GeminiUnavailable("Gemini output included wording not supported by the transcript; review or use mock mode.")
        return DraftReport(findings=result['findings'], draft_report=result['draft_report'], transcript=transcript, provider="gemini")
    except GeminiUnavailable:
        raise

def save_draft(req: SaveDraftRequest) -> dict:
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO saved_drafts(draft_id,transcript,payload,edited_report,clinician_reviewed) VALUES(?,?,?,?,?)", (req.draft.draft_id, req.draft.transcript, req.draft.model_dump_json(), req.edited_report, int(req.clinician_reviewed)))
        db.commit()
    return {"status":"saved","draft_id":req.draft.draft_id,"clinician_reviewed":req.clinician_reviewed,"finalized":False}

SESSIONS: dict[str, dict[str, Any]] = {}
PROVIDER_SESSIONS: dict[str, dict[str, str]] = {}

def follow_up(text: str, session_id: str) -> dict[str, Any]:
    ctx = SESSIONS.get(session_id)
    if not ctx or not ctx.get('report_id'):
        return {"status":"clarification_required","message":"Select a patient report first so I can ground the answer."}
    report = get_report(ctx['report_id'])
    if not report: return {"status":"not_found","message":"The selected report is no longer available."}
    t = text.casefold()
    if "source" in t or "evidence" in t or "cite" in t:
        answer = f"Source excerpt for report {report['report_id']}: {report['excerpt']}"
    elif "anatomical site" in t or "which site" in t or "where" in t:
        answer = "Site wording documented in the report: " + " ".join(report['findings'])
    elif any(x in t for x in ("summar", "tell me about", "describe")):
        answer = f"Report {report['report_id']} ({report['report_type']}, {report['date']}) documents: " + " ".join(report['findings'])
    elif "finding" in t or "documented" in t:
        answer = "Documented findings: " + " ".join(report['findings'])
    elif "mention" in t or "does this report" in t or "does the report" in t:
        ignored={"does","this","the","report","mention","mentions","a","an","any","about","is","there","in","it","have","has"}
        terms=[w for w in re.findall(r"[a-z0-9]+",t) if w not in ignored]
        matched=[f for f in report['findings'] if terms and all(term in f.casefold() for term in terms)]
        answer=("The report documents: " + " ".join(matched)) if matched else "That information is not documented in the selected report."
    else:
        answer = "That information is not documented in the selected report."
    SESSIONS[session_id]['previous_action'] = 'follow_up'
    return {"status":"ok","answer":answer,"patient_id":report['patient_id'],"report_id":report['report_id'],"source":{"report_id":report['report_id'],"excerpt":report['excerpt']}}

@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield

app = FastAPI(title="VI-SCAN AI — Voice-First Dental Assistant", version="1.0.0", description="Synthetic-data-only demo; deterministic mock provider.", lifespan=lifespan)

@app.get('/health')
def health():
    init_db()
    with connect() as db:
        counts = {"patients":db.execute("SELECT COUNT(*) FROM patients").fetchone()[0],"reports":db.execute("SELECT COUNT(*) FROM reports").fetchone()[0]}
    return {"status":"ok","provider":active_provider(),"model":GEMINI_MODEL if active_provider()=='gemini' else "deterministic-mock","mode":"Gemini" if active_provider()=='gemini' else "deterministic mock; synthetic data only","database":"connected","counts":counts}

@app.get('/patients')
def patients(q: str = ""):
    init_db(); return {"items":patient_search(q)}

@app.get('/patients/{patient_id}/reports')
def patient_reports(patient_id: str):
    init_db()
    if not patient_search(patient_id=patient_id): raise HTTPException(404,"Patient not found")
    return {"items":list_reports(patient_id.upper())}

@app.get('/reports/{report_id}')
def report_endpoint(report_id: str):
    init_db(); r=get_report(report_id)
    if not r: raise HTTPException(404,"Report not found")
    return r

@app.post('/assistant/query')
def assistant_query(req: QueryRequest):
    init_db(); result=retrieve(req.text)
    if result['status']=='ok':
        SESSIONS[req.session_id]={"patient_id":result['patient']['patient_id'],"report_id":result['report']['report_id'],"previous_action":"retrieve","source":result['source']}
    return result

@app.post('/assistant/follow-up')
def assistant_follow_up(req: FollowUpRequest):
    init_db(); return follow_up(req.text,req.session_id)

@app.post('/assistant/select-report')
def select_report(req: SelectReportRequest):
    init_db(); report=get_report(req.report_id)
    if not report: raise HTTPException(404,"Report not found")
    source={"report_id":report['report_id'],"excerpt":report['excerpt']}
    SESSIONS[req.session_id]={"patient_id":report['patient_id'],"report_id":report['report_id'],"previous_action":"select_report","source":source}
    return {"status":"ok","patient_id":report['patient_id'],"report_id":report['report_id'],"source":source}

@app.post('/reports/draft', response_model=DraftReport)
def draft_endpoint(req: DraftRequest):
    try: return generate_draft(req.transcript, req.session_id)
    except GeminiUnavailable as exc: raise HTTPException(503,str(exc)) from exc

class GeminiSettingsRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=80)
    api_key: str = Field(min_length=10, max_length=300)
    model: str = Field(default=GEMINI_MODEL, min_length=1, max_length=100)

class GeminiSessionRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=80)

class ProviderSettingsRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=80)
    provider: str = Field(pattern="^(gemini|local)$")
    model: str = Field(min_length=1, max_length=150)
    api_key: str | None = Field(default=None, min_length=10, max_length=300)

@app.get('/settings/provider/{session_id}')
def provider_status(session_id: str):
    config = PROVIDER_SESSIONS.get(session_id)
    return {"provider": config.get("provider") if config else active_provider(),
            "model": config.get("model") if config else (GEMINI_MODEL if active_provider() == "gemini" else "deterministic-mock")}

@app.post('/settings/provider/test')
def test_provider(req: ProviderSettingsRequest):
    try:
        if req.provider == "gemini":
            if not req.api_key:
                raise HTTPException(422, "Enter a Gemini API key to test this provider.")
            GeminiAdapter(api_key=req.api_key, model=req.model).test_connection()
        else:
            LocalDraftAdapter(model=req.model).test_connection()
        return {"status": "connected", "provider": req.provider, "model": req.model}
    except GeminiUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except LocalModelUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc

@app.post('/settings/provider/activate')
def activate_provider(req: ProviderSettingsRequest):
    if req.provider == "gemini" and not req.api_key:
        raise HTTPException(422, "Enter a Gemini API key to activate this provider.")
    PROVIDER_SESSIONS[req.session_id] = {"provider": req.provider, "model": req.model}
    if req.provider == "gemini":
        PROVIDER_SESSIONS[req.session_id]["api_key"] = req.api_key
    return {"status": "active", "provider": req.provider, "model": req.model}

@app.post('/settings/gemini/test')
def test_gemini(req: GeminiSettingsRequest):
    try:
        GeminiAdapter(api_key=req.api_key, model=req.model).test_connection()
        return {"status":"connected", "provider":"gemini", "model":req.model}
    except GeminiUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc

@app.post('/settings/gemini/activate')
def activate_gemini(req: GeminiSettingsRequest):
    PROVIDER_SESSIONS[req.session_id] = {"api_key":req.api_key, "model":req.model}
    return {"status":"active", "provider":"gemini", "model":req.model}

@app.post('/settings/gemini/clear')
def clear_gemini(req: GeminiSessionRequest):
    PROVIDER_SESSIONS.pop(req.session_id, None)
    return {"status":"cleared", "provider":"mock"}

@app.post('/reports/draft/{draft_id}/save')
def save_draft_endpoint(draft_id: str, req: SaveDraftRequest):
    if draft_id != req.draft.draft_id: raise HTTPException(422,"Draft ID does not match request payload")
    return save_draft(req)

@app.post('/assistant/reset')
def reset_assistant(req: FollowUpRequest):
    SESSIONS.pop(req.session_id, None)
    return {"status":"ok","message":"Assistant context cleared."}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('app.main:app',host='127.0.0.1',port=8000,reload=False)
