"""Small browser speech-recognition control for Streamlit dictation."""
from pathlib import Path

import streamlit.components.v1 as components

_component = components.declare_component(
    "viscan_voice_input",
    path=str(Path(__file__).parent / "voice_frontend"),
)


def voice_input(key: str = "voice_input"):
    """Return {transcript, event_id} after browser speech recognition completes."""
    return _component(key=key, default=None)
