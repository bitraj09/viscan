"""Professional Streamlit dashboard for the VI-SCAN synthetic-data demo."""
import json, uuid
from urllib.parse import urlparse
import requests
import streamlit as st
from app.voice_component import voice_input

st.set_page_config(page_title="VI-SCAN AI", page_icon="🦷", layout="wide", initial_sidebar_state="collapsed")
API = st.sidebar.text_input("Backend URL", "http://127.0.0.1:8000")
if "sid" not in st.session_state: st.session_state.sid = str(uuid.uuid4())
if "history" not in st.session_state: st.session_state.history = []
st.markdown("""
<style>
:root { --ink:#153247; --muted:#607584; --teal:#087f86; --line:#dce7eb; --paper:#f4f7f8; }
.stApp, [data-testid="stAppViewContainer"] { background:var(--paper)!important; color:var(--ink)!important }
[data-testid="stHeader"] { background:var(--paper)!important }
[data-testid="stSidebar"] { background:#fff!important; border-right:1px solid var(--line) }
[data-testid="stSidebarContent"] { padding:1.1rem .85rem 1.5rem }
.brand {font-size:1.3rem;font-weight:800;color:var(--ink);letter-spacing:.015em}
.brand span {color:var(--teal)}
.subtle {color:var(--muted);font-size:.9rem}
h1 {color:var(--ink)!important;font-size:2rem!important;letter-spacing:-.035em!important;padding-top:.15rem!important}
h2,h3 {color:var(--ink)!important;letter-spacing:-.02em}
div[data-testid="stMetric"] {background:#fff!important;border:1px solid var(--line);border-radius:14px;padding:15px 17px;box-shadow:0 2px 8px #17394a08}
div[data-testid="stMetric"] *, div[data-testid="stMetricLabel"], div[data-testid="stMetricValue"] {color:var(--ink)!important;opacity:1!important}
div.stButton>button, [data-testid="stBaseButton-secondary"] {min-height:2.55rem;border-radius:9px;border:1px solid #c9d8de!important;background:#fff!important;color:var(--ink)!important;transition:all .15s ease}
div.stButton>button:hover, [data-testid="stBaseButton-secondary"]:hover {border-color:var(--teal)!important;color:var(--teal)!important;background:#f4fbfa!important}
div.stButton>button[kind="primary"], [data-testid="stBaseButton-primary"], [data-testid="stFormSubmitButton"] button {background:var(--teal)!important;color:#fff!important;border:0!important}
div.stButton>button[kind="primary"]:hover, [data-testid="stBaseButton-primary"]:hover {background:#076c72!important}
.stTextInput input, .stTextArea textarea, [data-baseweb="select"] > div {background:#fff!important;color:var(--ink)!important;border-radius:9px!important}
[data-testid="stSidebar"] .stRadio [role="radiogroup"] {gap:.18rem}
[data-testid="stSidebar"] .stRadio [role="radiogroup"] label {padding:.48rem .65rem;border-radius:8px;color:#405968}
[data-testid="stSidebar"] .stRadio [role="radiogroup"] label:hover {background:#f2f7f8}
.hero {padding:1.35rem 1.5rem;margin:.2rem 0 1.1rem;background:#fff;border:1px solid var(--line);border-radius:16px;box-shadow:0 3px 12px #17394a08}
.hero-kicker {font-size:.74rem;font-weight:750;letter-spacing:.1em;text-transform:uppercase;color:var(--teal);margin-bottom:.4rem}
.hero-title {font-size:1.45rem;font-weight:750;color:var(--ink);letter-spacing:-.03em}
.hero-copy {color:var(--muted);margin-top:.35rem;max-width:760px;line-height:1.55}
.evidence {border-left:3px solid var(--teal);background:#edf8f7;padding:11px 14px;border-radius:0 9px 9px 0;color:#254452}
@media(max-width:700px) { h1 {font-size:1.65rem!important} .hero {padding:1rem} .hero-title {font-size:1.2rem} }
</style>
""", unsafe_allow_html=True)

def navigate_to(target):
    st.session_state["workspace_nav"] = target
    st.query_params["view"] = target

with st.sidebar:
    st.markdown('<div class="brand">VI<span>·</span>SCAN AI</div>',unsafe_allow_html=True)
    st.caption("Clinical documentation workspace")
    pages=["Dashboard","Patient reports","Clinical dictation","AI assistant","Settings","System information"]
    initial=st.query_params.get("view","Dashboard")
    if initial not in pages: initial="Dashboard"
    if "workspace_nav" not in st.session_state:
        st.session_state["workspace_nav"]=initial
    page=st.radio("Workspace",pages,key="workspace_nav",label_visibility="collapsed")
    st.query_params["view"]=page
    st.divider()
    try:
        health=requests.get(f"{API}/health",timeout=2).json()
        try: current_provider=requests.get(f"{API}/settings/provider/{st.session_state.sid}",timeout=2).json()['provider']
        except Exception: current_provider=health['provider']
        st.success(f"{current_provider.title()} mode · API online")
    except Exception:
        health=None; st.error("API offline")
    st.caption("Synthetic records only · Demo environment")

def api_post(path, body):
    try:
        r=requests.post(f"{API}/{path}",json=body,timeout=25)
        if r.status_code >= 400:
            try: detail=r.json().get('detail','Request could not be completed.')
            except Exception: detail='Request could not be completed.'
            st.error(detail); return None
        return r.json()
    except requests.RequestException:
        st.error("The backend could not be reached. Confirm that the API is running."); return None

def show_report(result):
    if result.get('status')=='clarification_required':
        st.warning(result['message'])
        for p in result['options']:
            if st.button(f"Select {p['name']} · {p['patient_id']}",key=f"choose_{p['patient_id']}"):
                chosen=api_post('assistant/query',{"text":f"Open {p['patient_id']} latest OPG report","session_id":st.session_state.sid})
                if chosen: st.session_state.selected_result=chosen; st.rerun()
    elif result.get('status')=='ok':
        patient,report=result['patient'],result['report']
        st.markdown(f"### {patient['name']} <span class='subtle'>· {patient['patient_id']}</span>",unsafe_allow_html=True)
        a,b,c=st.columns(3); a.metric("Report",report['report_id']); b.metric("Type",report['report_type']); c.metric("Report date",report['date'])
        st.markdown("**Documented findings**")
        for finding in report['findings']: st.write("• "+finding)
        st.markdown(f"<div class='evidence'><b>Source evidence · {report['report_id']}</b><br>{report['excerpt']}</div>",unsafe_allow_html=True)
    else: st.info(result.get('message','No matching report.'))

st.markdown("# "+page)
if page=="Dashboard":
    st.markdown("<section class='hero'><div class='hero-kicker'>Clinical documentation workspace</div><div class='hero-title'>Welcome to VI-SCAN AI</div><div class='hero-copy'>Find synthetic dental reports, prepare transcript-grounded drafts, and ask questions backed by report evidence. All records in this demo are fictional.</div></section>",unsafe_allow_html=True)
    if health:
        left,middle,right=st.columns(3)
        try: dashboard_provider=requests.get(f"{API}/settings/provider/{st.session_state.sid}",timeout=2).json()['provider']
        except Exception: dashboard_provider=health['provider']
        left.metric("Synthetic patients",health['counts']['patients']); middle.metric("Synthetic reports",health['counts']['reports']); right.metric("AI provider",dashboard_provider.title())
    st.subheader("Quick actions")
    cols=st.columns(3)
    for col,label,target in zip(cols,["Find a patient report","Draft from dictation","Ask about a report"],["Patient reports","Clinical dictation","AI assistant"]):
        with col:
            st.markdown(f"**{label}**")
            st.button("Open workspace",key="quick_"+target,on_click=navigate_to,args=(target,))
    st.subheader("Recent synthetic reports")
    try:
        people=requests.get(f"{API}/patients",timeout=3).json()['items']
        recent=[]
        for p in people:
            recent.extend(requests.get(f"{API}/patients/{p['patient_id']}/reports",timeout=3).json()['items'])
        for r in sorted(recent,key=lambda x:x['date'],reverse=True)[:5]: st.write(f"**{r['date']}** · {r['report_type']} · `{r['report_id']}` · {r['excerpt']}")
    except Exception: st.info("Recent reports are unavailable while the backend is offline.")
elif page=="Patient reports":
    st.caption("Say or type a request such as ‘Open Priya Sharma’s latest OPG report’. Ambiguous matches require an explicit choice.")
    st.markdown("**Voice search** · say the patient name and report type")
    report_voice=voice_input(key="report_search_voice")
    if report_voice and report_voice.get("transcript") and report_voice.get("event_id") != st.session_state.get("last_report_voice_event"):
        st.session_state.last_report_voice_event=report_voice["event_id"]
        st.session_state.report_search_command=report_voice["transcript"]
        voice_match=api_post('assistant/query',{"text":report_voice["transcript"],"session_id":st.session_state.sid})
        if voice_match: st.session_state.selected_result=voice_match
    st.caption("Voice search submits the recognized words to the synthetic patient index. Check the transcript below; you can edit and search again.")
    with st.form("patient_search"):
        cmd=st.text_input("Search command",placeholder="Open Priya Sharma's latest OPG report",key="report_search_command")
        submitted=st.form_submit_button("Search reports",type="primary")
    if submitted and cmd:
        result=api_post('assistant/query',{"text":cmd,"session_id":st.session_state.sid})
        if result: st.session_state.selected_result=result
    if st.session_state.get('selected_result'): show_report(st.session_state.selected_result)
    with st.expander("Browse synthetic patients"):
        try:
            people=requests.get(f"{API}/patients",timeout=3).json()['items']
            selected=st.selectbox("Patient",people,format_func=lambda p:f"{p['name']} · {p['patient_id']}")
            if st.button("List reports",key="list_reports"):
                st.session_state.patient_reports=requests.get(f"{API}/patients/{selected['patient_id']}/reports",timeout=3).json()['items']
            for r in st.session_state.get('patient_reports',[]):
                if st.button(f"{r['date']} · {r['report_type']} · {r['report_id']}",key="report_"+r['report_id']):
                    x=requests.get(f"{API}/reports/{r['report_id']}",timeout=3).json()
                    st.session_state.selected_result={"status":"ok","patient":selected,"report":x,"source":{"report_id":x['report_id'],"excerpt":x['excerpt']}}
                    api_post('assistant/select-report',{"report_id":r['report_id'],"session_id":st.session_state.sid})
                    st.rerun()
        except Exception: st.info("Patient list unavailable.")
elif page=="Clinical dictation":
    st.caption("Speak the clinical observation or type it. Review and correct the recognized words before generating a draft.")
    st.markdown("**Voice dictation** · English (India)")
    voice_result=voice_input(key="dictation_voice")
    if voice_result and voice_result.get("transcript") and voice_result.get("event_id") != st.session_state.get("last_voice_event"):
        st.session_state.last_voice_event=voice_result["event_id"]
        st.session_state.transcript_input=voice_result["transcript"]
    st.caption("Your browser performs speech recognition and returns text to this app. Microphone permission is required; typed entry is always available.")
    transcript=st.text_area("Clinician transcript",placeholder="Lower right third molar is horizontally impacted.",height=130,key="transcript_input")
    if st.button("Generate draft",type="primary"):
        if not transcript.strip(): st.warning("Enter a transcript first.")
        else:
            draft=api_post('reports/draft',{"transcript":transcript,"session_id":st.session_state.sid})
            if draft: st.session_state.draft=draft
    if st.session_state.get('draft'):
        d=st.session_state.draft
        st.caption("Draft generated by "+{"gemini":"Gemini","local":"Hugging Face local model","mock":"deterministic mock provider"}.get(d.get("provider"),d.get("provider","mock")))
        st.info("Draft · clinician review required")
        findings=d['findings']
        for i,f in enumerate(findings):
            a,b,c=st.columns([2,2,2])
            f['observation']=a.text_input("Observation",f['observation'],key=f"obs_{i}")
            f['anatomical_site']=b.text_input("Anatomical site",f.get('anatomical_site') or "",key=f"site_{i}") or None
            f['uncertainty']=c.text_input("Uncertainty",f.get('uncertainty') or "",key=f"unc_{i}") or None
        d['draft_report']=st.text_area("Editable report wording",d['draft_report'],height=90,key="draft_text")
        st.caption("Source transcript remains attached. Review before use; this draft cannot be finalized here.")
        st.json(d)
        if st.button("Save draft"):
            saved=api_post(f"reports/draft/{d['draft_id']}/save",{"draft":d,"edited_report":d['draft_report'],"clinician_reviewed":False})
            if saved: st.success(f"Saved draft {saved['draft_id']}.")
elif page=="AI assistant":
    st.caption("Answers use the selected report and display its evidence. Select a report in Patient reports first.")
    if st.button("Reset conversation context"):
        api_post('assistant/reset',{"text":"reset","session_id":st.session_state.sid}); st.session_state.history=[]; st.success("Context cleared.")
    for item in st.session_state.history:
        with st.chat_message(item['role']):
            st.write(item['text'])
            if item.get('evidence'): st.caption(item['evidence'])
    question=st.chat_input("Ask about the selected report")
    if question:
        st.session_state.history.append({"role":"user","text":question})
        response=api_post('assistant/follow-up',{"text":question,"session_id":st.session_state.sid})
        if response:
            evidence=""
            if response.get('source'): evidence=f"Source {response['source']['report_id']}: {response['source']['excerpt']}"
            st.session_state.history.append({"role":"assistant","text":response.get('answer',response.get('message','No response.')),"evidence":evidence})
            st.rerun()
elif page=="Settings":
    try:
        current=requests.get(f"{API}/settings/provider/{st.session_state.sid}",timeout=3).json()
    except Exception:
        current={"provider":"mock","model":"deterministic-mock"}
    st.markdown("<section class='hero'><div class='hero-kicker'>Model control</div><div class='hero-title'>Choose how drafts are generated</div><div class='hero-copy'>Provider changes apply to this browser session. Patient lookup and report evidence remain deterministic and local.</div></section>",unsafe_allow_html=True)
    st.info(f"Active: **{current['provider'].title()}** · `{current['model']}`")
    provider=st.radio("Draft provider",["local","gemini"],format_func=lambda x:"Local · Hugging Face" if x=="local" else "Gemini · Google",horizontal=True,key="provider_choice")
    if provider=="local":
        model=st.text_input("Hugging Face model",value=st.session_state.get("local_model","google/flan-t5-small"),key="local_model_input",help="Small text-to-text model; runs on CPU and downloads the first time you test it.")
        st.caption("Local inference keeps transcript text on this machine. First use needs internet to download the model unless it is already cached.")
        payload={"session_id":st.session_state.sid,"provider":"local","model":model.strip()}
        disabled=not model.strip()
    else:
        model=st.text_input("Gemini model",value=st.session_state.get("gemini_model","gemini-3.8-flash"),key="gemini_model_input")
        key=st.text_input("Gemini API key",type="password",key="gemini_key_input",placeholder="Paste key; it stays masked")
        payload={"session_id":st.session_state.sid,"provider":"gemini","model":model.strip(),"api_key":key.strip()}
        disabled=not key.strip() or not model.strip()
        st.caption("Gemini sends the draft transcript to Google. The key is held in backend memory for this session and never stored in the database.")
    left,right=st.columns(2)
    if left.button("Test and activate",type="primary",disabled=disabled):
        if provider=="gemini":
            endpoint=urlparse(API)
            secure_endpoint=endpoint.scheme=="https" or endpoint.hostname in {"localhost","127.0.0.1","::1"}
            if not secure_endpoint:
                st.error("Use a local backend or HTTPS before sending a Gemini key.")
                tested=None
            else: tested=api_post("settings/provider/test",payload)
        else: tested=api_post("settings/provider/test",payload)
        if tested and api_post("settings/provider/activate",payload):
            st.session_state.local_model=model.strip() if provider=="local" else st.session_state.get("local_model")
            if provider=="gemini":
                st.session_state.gemini_model=model.strip()
                st.session_state.pop("gemini_key_input",None)
            st.success(f"{provider.title()} connected and active · {model.strip()}")
            st.rerun()
    if right.button("Use deterministic mode"):
        api_post("settings/gemini/clear",{"session_id":st.session_state.sid})
        st.success("Deterministic mode is active for this session.")
        st.rerun()
    st.caption("A model connection test makes a real inference request. The local model is optional; install the dependencies in `requirements-local.txt` before selecting it.")
elif page=="System information":
    if health:
        st.success("Backend healthy")
        try:
            session_provider=requests.get(f"{API}/settings/provider/{st.session_state.sid}",timeout=3).json()
        except Exception: session_provider={"provider":health['provider'],"model":health['model']}
        provider=session_provider['provider']
        model=session_provider['model']
        st.write(f"**Provider:** {provider} · **Model:** {model} · **Database:** {health['database']}")
        st.json(health['counts'])
    else: st.error("Backend health check failed. Start FastAPI and retry.")
    st.markdown("**Demo safety boundary:** synthetic records only; no authentication, real patient data, or image analysis. Browser speech recognition is provided for dictation. Do not use for clinical care.")
    st.markdown("API documentation: [OpenAPI /docs](http://127.0.0.1:8000/docs)")
st.divider()
st.caption("VI-SCAN AI · Synthetic-data demonstration · Drafts require clinician review")
