# Demo script (3–5 minutes)

1. Start the API and Streamlit using README commands. Point out the active mock/Gemini status.
2. Search `Open P001 latest OPG report`; show report R1002, synthetic patient ID, report date, findings, and evidence excerpt.
3. Search `Open Priya latest OPG report`; select either P001 or P002 only after the UI shows both clarification choices.
4. In Clinical dictation use the microphone or enter `Lower right third molar is horizontally impacted.` Review the transcript, generate the editable report, inspect JSON/provenance, and save it as a draft. Call out that clinician review remains required.
5. In Patient reports explicitly select one report. In AI assistant ask `Summarize her report`, then `Does this report mention a fracture?`; show source evidence and the not-documented response.
6. Open System information and note synthetic data, API/database status, provider mode, and that audio/image processing is not active.
