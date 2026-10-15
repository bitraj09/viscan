from fastapi.testclient import TestClient
from app.main import app, SESSIONS

client=TestClient(app)

def setup_function():
    SESSIONS.clear()
    import app.main as module
    module.PROVIDER_SESSIONS.clear()

def test_correct_latest_retrieval():
    r=client.post('/assistant/query',json={"text":"Open P001 latest OPG report","session_id":"t1"})
    assert r.status_code==200 and r.json()['report']['report_id']=='R1002'
    assert r.json()['patient']['patient_id']=='P001'

def test_ambiguous_name_clarifies():
    r=client.post('/assistant/query',json={"text":"Open Priya latest OPG report","session_id":"t2"}).json()
    assert r['status']=='clarification_required' and {p['patient_id'] for p in r['options']}=={'P001','P002'}

def test_draft_preserves_only_supported_text():
    transcript='Lower right third molar is horizontally impacted.'
    d=client.post('/reports/draft',json={"transcript":transcript}).json()
    assert d['findings'][0]['observation']==transcript
    assert 'caries' not in d['draft_report'].lower() and d['requires_clinician_review'] is True

def test_missing_patient_and_report():
    assert client.post('/assistant/query',json={"text":"Open Unknown Person report"}).json()['status']=='not_found'
    assert client.get('/reports/NOPE').status_code==404

def test_followup_context_and_missing_context():
    assert client.post('/assistant/follow-up',json={"text":"Summarize her report","session_id":"none"}).json()['status']=='clarification_required'
    client.post('/assistant/query',json={"text":"Open P001 latest OPG report","session_id":"follow"})
    ans=client.post('/assistant/follow-up',json={"text":"What findings are documented?","session_id":"follow"}).json()
    assert ans['report_id']=='R1002' and 'retained root fragment' in ans['answer'] and ans['source']['report_id']=='R1002'

def test_empty_transcript_rejected_and_uncertainty_preserved():
    assert client.post('/reports/draft',json={"transcript":"  "}).status_code==422
    d=client.post('/reports/draft',json={"transcript":"Possible impacted tooth?"}).json()
    assert d['findings'][0]['uncertainty'] and d['transcript']=='Possible impacted tooth?'

def test_session_isolation_and_explicit_report_selection():
    r=client.post('/assistant/select-report',json={"report_id":"R1001","session_id":"session-a"})
    assert r.status_code==200
    missing=client.post('/assistant/follow-up',json={"text":"Summarize her report","session_id":"session-b"}).json()
    assert missing['status']=='clarification_required'
    answer=client.post('/assistant/follow-up',json={"text":"Summarize her report","session_id":"session-a"}).json()
    assert answer['report_id']=='R1001' and answer['source']['report_id']=='R1001'

def test_save_draft_remains_nonfinal():
    draft=client.post('/reports/draft',json={"transcript":"Tooth 36 restoration noted."}).json()
    result=client.post(f"/reports/draft/{draft['draft_id']}/save",json={"draft":draft,"edited_report":draft['draft_report'],"clinician_reviewed":False})
    assert result.status_code==200
    assert result.json()['finalized'] is False

def test_bad_draft_id_is_rejected():
    draft=client.post('/reports/draft',json={"transcript":"Tooth 36 restoration noted."}).json()
    assert client.post('/reports/draft/wrong/save',json={"draft":draft,"edited_report":"Draft"}).status_code==422

def test_mock_mode_health_and_seed_counts():
    h=client.get('/health').json()
    assert h['counts']=={'patients':5,'reports':10}
    assert h['provider'] in {'mock','gemini'}

def test_claim_guard_rejects_unsupported_model_wording():
    from app.gemini_adapter import claims_supported
    assert claims_supported({'findings':[{'observation':'impacted tooth','anatomical_site':'lower right'}]},'impacted tooth, lower right')
    assert not claims_supported({'findings':[{'observation':'fracture'}]},'No fracture stated')

def test_configured_gemini_failure_is_visible(monkeypatch):
    import app.main as module
    from app.gemini_adapter import GeminiUnavailable
    class BrokenAdapter:
        def __init__(self): pass
        def draft(self, transcript, schema): raise GeminiUnavailable('provider failure')
    monkeypatch.setattr(module, 'active_provider', lambda: 'gemini')
    monkeypatch.setattr(module, 'GeminiAdapter', BrokenAdapter)
    response=client.post('/reports/draft',json={"transcript":"Tooth 36 restoration noted."})
    assert response.status_code==503
    assert 'provider failure' in response.json()['detail']

def test_malformed_model_claim_is_rejected(monkeypatch):
    import app.main as module
    class UnsafeAdapter:
        def __init__(self): pass
        def draft(self, transcript, schema):
            return {"findings":[{"observation":"fracture","anatomical_site":None,"uncertainty":None,"source_text":transcript,"source":"clinician_transcript"}],"draft_report":"fracture"}
    monkeypatch.setattr(module, 'active_provider', lambda: 'gemini')
    monkeypatch.setattr(module, 'GeminiAdapter', UnsafeAdapter)
    response=client.post('/reports/draft',json={"transcript":"Tooth 36 restoration noted."})
    assert response.status_code==503

def test_malformed_request_payload_returns_validation_error():
    assert client.post('/assistant/query',json={"text":""}).status_code==422
    assert client.post('/reports/draft',json={"unexpected":"payload"}).status_code==422

def test_report_chat_handles_site_source_and_unsupported_claim():
    client.post('/assistant/select-report',json={"report_id":"R1002","session_id":"grounded"})
    site=client.post('/assistant/follow-up',json={"text":"Which anatomical site is mentioned?","session_id":"grounded"}).json()
    assert 'upper left region' in site['answer'] and site['source']['report_id']=='R1002'
    source=client.post('/assistant/follow-up',json={"text":"Show the source for that statement","session_id":"grounded"}).json()
    assert 'R1002' in source['answer'] and 'retained root fragment' in source['answer']
    absent=client.post('/assistant/follow-up',json={"text":"Does this report mention a fracture?","session_id":"grounded"}).json()
    assert 'not documented' in absent['answer']

def test_gemini_credentials_are_session_scoped_and_never_returned(monkeypatch):
    import app.main as module
    class HealthyAdapter:
        def __init__(self, api_key=None, model=None):
            assert api_key == 'synthetic-test-key'
            self.model = model
        def test_connection(self): return None
    monkeypatch.setattr(module, 'GeminiAdapter', HealthyAdapter)
    payload={"session_id":"user-a","api_key":"synthetic-test-key","model":"test-model"}
    assert client.post('/settings/gemini/test',json=payload).json()=={"status":"connected","provider":"gemini","model":"test-model"}
    activated=client.post('/settings/gemini/activate',json=payload)
    assert activated.json()=={"status":"active","provider":"gemini","model":"test-model"}
    assert 'synthetic-test-key' not in activated.text
    assert module.PROVIDER_SESSIONS['user-a']=={"api_key":"synthetic-test-key","model":"test-model"}
    assert 'user-b' not in module.PROVIDER_SESSIONS
    assert client.post('/settings/gemini/clear',json={"session_id":"user-a"}).json()['status']=='cleared'
    assert 'user-a' not in module.PROVIDER_SESSIONS
