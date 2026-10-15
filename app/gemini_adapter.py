"""Optional official Google Gen AI adapter. Never exposes credentials to clients."""
from __future__ import annotations
import json, re
from pydantic import BaseModel, ValidationError
from app.config import GEMINI_API_KEY, GEMINI_MODEL

class GeminiUnavailable(RuntimeError):
    """Provider unavailable or returned invalid output."""

class GeminiAdapter:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = (api_key or GEMINI_API_KEY).strip()
        self.model = (model or GEMINI_MODEL).strip()
        if not self.api_key:
            raise GeminiUnavailable("Gemini is selected but GEMINI_API_KEY is not configured.")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise GeminiUnavailable("Install google-genai to use Gemini mode.") from exc
        self.types = types
        # This demo's configured environment proxy is an unavailable local sink.
        # Keep the direct-network choice scoped to Gemini SDK traffic only.
        self.client = genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(
                timeout=20000,
                client_args={"trust_env": False},
                async_client_args={"trust_env": False},
            ),
        )

    def json_response(self, prompt: str, schema: type[BaseModel]) -> dict:
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self.types.GenerateContentConfig(
                    response_mime_type="application/json", response_schema=schema,
                    system_instruction="Use only supplied text. Do not add dental claims absent from it. Return valid structured data.",
                ),
            )
            parsed = json.loads(response.text or "")
            return schema.model_validate(parsed).model_dump()
        except Exception as exc:
            raise GeminiUnavailable("Gemini request failed or returned invalid structured output.") from exc

    def draft(self, transcript: str, schema: type[BaseModel]) -> dict:
        return self.json_response(
            "Create one conservative draft from this clinician transcript. Preserve the observation. "
            "Set anatomical_site only to words explicitly present. Preserve uncertainty. "
            "Do not add facts. Transcript: " + transcript,
            schema,
        )

    def summarize(self, report: dict, schema: type[BaseModel]) -> dict:
        return self.json_response(
            "Answer using only this report. If not stated, say not documented. Include evidence excerpt. "
            + json.dumps(report, ensure_ascii=False), schema,
        )

    def test_connection(self) -> None:
        """Make a small real request; return only after the configured model responds."""
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents="Reply with the single word OK.",
                config=self.types.GenerateContentConfig(temperature=0, max_output_tokens=8),
            )
            if not (response.text or "").strip():
                raise ValueError("Empty response")
        except Exception as exc:
            code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
            raw_detail = str(getattr(exc, "message", "") or exc)
            # Provider diagnostics are useful, but credentials must never be echoed.
            safe_detail = raw_detail.replace(self.api_key, "[redacted key]")
            safe_detail = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[redacted key]", safe_detail)
            safe_detail = re.sub(r"(?i)(x-goog-api-key|api[_ -]?key)\s*[:=]\s*[^&\s,]+", r"\1=[redacted]", safe_detail)
            safe_detail = re.sub(r"\s+", " ", safe_detail).strip()[:280]
            detail = safe_detail.casefold()
            if "api_key_invalid" in detail or "api key not valid" in detail:
                message = "Gemini rejected this API key. Check that it is active, copied without extra characters, and belongs to a project with Gemini API access."
            elif code in (401, 400):
                message = f"Gemini rejected the request (HTTP {code}). Check the key and model name."
            elif code == 402:
                message = "Gemini rejected the request because the project's prepaid balance is exhausted (HTTP 402). Check billing in AI Studio."
            elif code == 403:
                message = "Google denied this key/project (HTTP 403). " + (safe_detail or "Check the project's Gemini API access and key restrictions.")
            elif code == 404:
                message = f"Gemini could not find model '{self.model}' (HTTP 404). Choose a model available to this project."
            elif code == 429:
                message = "Gemini quota or rate limit was reached (HTTP 429). Check the project's limits and retry later."
            elif code in (408, 504) or "timeout" in type(exc).__name__.casefold():
                message = "The Gemini connection timed out. Check network or proxy access and retry."
            elif isinstance(code, int) and code >= 500:
                message = f"Gemini is temporarily unavailable (HTTP {code}). Retry shortly."
            elif any(token in type(exc).__name__.casefold() for token in ("connect", "network", "proxy")):
                message = "Could not reach Gemini. Check internet, firewall, or proxy access and retry."
            else:
                message = "Gemini connection test failed before a response was received. Check network access and the selected model."
            raise GeminiUnavailable(message) from exc

def claims_supported(output: dict, source_text: str) -> bool:
    """Conservative guard: model clinical field content must occur in supplied evidence."""
    source = re.sub(r"[^a-z0-9]+", " ", source_text.casefold()).strip()
    for finding in output.get("findings", []):
        for key in ("observation", "anatomical_site"):
            value = finding.get(key)
            if value:
                normalized = re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()
                if normalized and normalized not in source:
                    return False
                if normalized:
                    start = source.find(normalized)
                    preceding = source[max(0, start - 35):start]
                    if re.search(r"\b(no|not|without|negative for|denies|absent)\b", preceding):
                        return False
    return True
