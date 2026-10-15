"""Optional small Hugging Face text model for local draft structuring."""
from __future__ import annotations

import json
from functools import lru_cache

from pydantic import BaseModel

DEFAULT_LOCAL_MODEL = "google/flan-t5-small"


class LocalModelUnavailable(RuntimeError):
    """The optional local model is not installed, cached, or loadable."""


@lru_cache(maxsize=2)
def _load_pipeline(model_id: str):
    try:
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        import torch
        tokenizer = AutoTokenizer.from_pretrained(model_id)
        model = AutoModelForSeq2SeqLM.from_pretrained(model_id)
        model.eval()
        return tokenizer, model, torch
    except Exception as exc:
        raise LocalModelUnavailable(
            f"Could not load local model '{model_id}' ({type(exc).__name__}). Install the optional local-model dependencies and allow the first model download."
        ) from exc


class LocalDraftAdapter:
    def __init__(self, model: str = DEFAULT_LOCAL_MODEL):
        self.model = model.strip()
        if not self.model or len(self.model) > 150:
            raise LocalModelUnavailable("Enter a valid Hugging Face model ID.")

    def _generate(self, prompt: str) -> str:
        try:
            tokenizer, model, torch = _load_pipeline(self.model)
            inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)
            with torch.inference_mode():
                output = model.generate(**inputs, max_new_tokens=220, do_sample=False)
            return tokenizer.decode(output[0], skip_special_tokens=True)
        except LocalModelUnavailable:
            raise
        except Exception as exc:
            raise LocalModelUnavailable("The local model failed while generating a response.") from exc

    def test_connection(self) -> None:
        self._generate("Return the word OK.")

    def draft(self, transcript: str, schema: type[BaseModel]) -> dict:
        prompt = (
            "Convert the clinician transcript into JSON with keys findings and draft_report. "
            "findings must be a list with one object containing observation, anatomical_site, uncertainty, source_text. "
            "Use null for missing site or uncertainty. Copy the transcript exactly as observation and source_text. "
            "Do not infer or add any clinical facts. Transcript: " + transcript
        )
        raw = self._generate(prompt)
        try:
            parsed = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
            return schema.model_validate(parsed).model_dump()
        except Exception as exc:
            raise LocalModelUnavailable("The local model returned invalid structured output. Try again or use mock mode.") from exc
