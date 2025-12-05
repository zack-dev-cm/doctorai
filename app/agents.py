from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from openai import AsyncOpenAI, BadRequestError

from .config import settings

logger = logging.getLogger("doctorai.agent")

# Human-readable schema used in prompts.
RESPONSE_SCHEMA_DOC = {
    "answer": "Summarize likely issue + next steps.",
    "provisional_diagnosis": "Best-fit label or 'unclear'",
    "differentials": ["Up to 3 alternatives"],
    "followups": ["3-5 targeted questions"],
    "plan": "Home care / OTC / clinician asks",
    "triage": "When to seek urgent care",
    "risk_flags": "Red flags detected",
    "confidence": "0.0-1.0 conservative",
}

# Enforced schema for structured outputs (analysis + verification).
RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "doctorai_agent_reply",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "answer": {"type": "string"},
                "provisional_diagnosis": {"type": "string"},
                "differentials": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 3,
                },
                "followups": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 5,
                },
                "plan": {"type": "string"},
                "triage": {"type": "string"},
                "risk_flags": {"type": "string"},
                "confidence": {"type": "string"},
            },
            "required": [
                "answer",
                "provisional_diagnosis",
                "differentials",
                "followups",
                "plan",
                "triage",
                "risk_flags",
                "confidence",
            ],
        },
        "strict": True,
    },
}

SYSTEM_PROMPT_TEMPLATE = (
    "You are {title}. Specialty: {specialties}. Tone: {tone}. Default language: English unless the user changes it.\n"
    "You are part of a Mixture-of-Experts ensemble and must deliver structured JSON only.\n"
    "Always consider dermatology red flags (fever, rapidly spreading rash, mucosal involvement, pain, immunosuppression) "
    "and therapy safety flags (self-harm, harm to others, psychosis, withdrawal).\n"
    "State uncertainty explicitly. Never provide definitive diagnoses or prescriptions; recommend clinician follow-up. "
    "Ask for missing critical data via followups.\n"
    "Reply in JSON matching: {schema_json}"
)

VERIFICATION_PROMPT = (
    "You are a safety and quality verifier (OpenEvolve style).\n"
    "Given the user request, the agent JSON output, and optional image context, ensure the reply is safe, clinically humble, "
    "and follows schema keys exactly. Fix hallucinated drug dosing, add disclaimers, and re-rank differentials if needed. "
    "Return corrected JSON only. If content is unsafe or missing, produce conservative guidance with followups. "
    "Cap confidence unless there is strong objective evidence."
)


@dataclass(frozen=True)
class AgentProfile:
    key: str
    title: str
    description: str
    tone: str
    specialties: Sequence[str]

    @property
    def system_prompt(self) -> str:
        schema_json = json.dumps(RESPONSE_SCHEMA_DOC, indent=2, ensure_ascii=False)
        specialties = ", ".join(self.specialties)
        return SYSTEM_PROMPT_TEMPLATE.format(
            title=self.title,
            specialties=specialties,
            tone=self.tone,
            schema_json=schema_json,
        )


AGENT_PROFILES: Dict[str, AgentProfile] = {
    "dermatologist": AgentProfile(
        key="dermatologist",
        title="Dermatology Attending Physician",
        description="Focus on rashes, lesions, acne, inflammatory skin conditions, infections, and wound healing.",
        tone="precise, reassuring, avoids alarmism",
        specialties=(
            "medical dermatology",
            "infectious disease differentials",
            "dermoscopy heuristics",
            "skin care routines",
        ),
    ),
    "therapist": AgentProfile(
        key="therapist",
        title="Generalist Therapist",
        description="Focus on emotional support, CBT/DBT inspired coping, brief assessment of risk.",
        tone="supportive, concise, trauma-informed",
        specialties=("anxiety", "depression", "stress management", "sleep hygiene"),
    ),
}


def b64_from_upload(file_data: bytes, filename: str | None = None) -> str:
    """Return a data URL string for OpenAI image_url payloads."""
    mime = "image/jpeg"
    if filename:
        suffix = Path(filename).suffix.lower()
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".heic": "image/heic",
        }.get(suffix, mime)
    encoded = base64.b64encode(file_data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def parse_structured_response(content: Any) -> Dict[str, Any]:
    """Coerce the model reply into the expected dict with safe fallbacks."""
    if isinstance(content, dict):
        return content
    text = content or ""
    if not isinstance(text, str):
        try:
            text = json.dumps(text, ensure_ascii=False)
        except Exception:
            text = str(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[len("json") :].strip()
        try:
            return json.loads(cleaned)
        except Exception:
            return {
                "answer": cleaned,
                "provisional_diagnosis": "unclear",
                "differentials": [],
                "followups": [],
                "plan": "",
                "triage": "",
                "risk_flags": "",
                "confidence": "0.0",
            }


def _extract_text_content(message: Any) -> str:
    """Handle text vs. content array returned by the chat endpoint."""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    parts.append(item["text"])
            else:
                if getattr(item, "type", None) == "text" and getattr(item, "text", None):
                    parts.append(item.text)  # type: ignore[attr-defined]
        return "".join(parts)
    return ""


def _build_user_parts(question: str, image_bytes: Optional[bytes], image_filename: Optional[str]) -> List[Dict[str, Any]]:
    parts: List[Dict[str, Any]] = [{"type": "text", "text": question.strip()}]
    if image_bytes:
        parts.append({"type": "image_url", "image_url": {"url": b64_from_upload(image_bytes, image_filename)}})
    return parts


def _build_history(history: Optional[List[Dict[str, str]]]) -> List[Dict[str, str]]:
    trimmed: List[Dict[str, str]] = []
    if not history:
        return trimmed
    for item in history[-8:]:
        if item.get("role") in {"user", "assistant"} and item.get("content"):
            trimmed.append({"role": item["role"], "content": item["content"]})
    return trimmed


async def _chat_with_fallback(
    *,
    client: AsyncOpenAI,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float | None,
    max_tokens: int,
) -> Any:
    """Call chat.completions with schema and retry without unsupported params."""
    params: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": max_tokens,
        "response_format": RESPONSE_FORMAT,
    }
    if temperature is not None:
        params["temperature"] = temperature
    if settings.reasoning_effort:
        params["reasoning_effort"] = settings.reasoning_effort

    try:
        return await client.chat.completions.create(**params)
    except BadRequestError as exc:
        message = (getattr(exc, "message", "") or str(exc)).lower()
        unsupported_temp = "temperature" in message and "unsupported" in message
        unsupported_reason = "reasoning_effort" in message and "unsupported" in message
        if not (unsupported_temp or unsupported_reason):
            raise
        retry_params = {k: v for k, v in params.items() if k not in {"temperature", "reasoning_effort"}}
        logger.warning(
            "chat_retry_without_optional_params",
            extra={
                "model": model,
                "removed_temperature": unsupported_temp,
                "removed_reasoning_effort": unsupported_reason,
            },
        )
        return await client.chat.completions.create(**retry_params)


async def _chat_with_schema(
    *,
    client: AsyncOpenAI,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float,
    max_tokens: int,
) -> Dict[str, Any]:
    completion = await _chat_with_fallback(
        client=client,
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    message = completion.choices[0].message
    parsed = getattr(message, "parsed", None)
    if parsed:
        return parse_structured_response(parsed)
    return parse_structured_response(_extract_text_content(message))


async def run_agent(
    *,
    question: str,
    agent_key: str | None = None,
    image_bytes: Optional[bytes] = None,
    image_filename: Optional[str] = None,
    history: Optional[List[Dict[str, str]]] = None,
    client: Optional[AsyncOpenAI] = None,
) -> Dict[str, Any]:
    client = client or AsyncOpenAI(api_key=settings.openai_api_key)
    key = (agent_key or settings.default_agent or "dermatologist").lower()
    profile = AGENT_PROFILES.get(key, AGENT_PROFILES["dermatologist"])

    user_parts = _build_user_parts(question, image_bytes, image_filename)
    messages: List[Dict[str, Any]] = [{"role": "system", "content": profile.system_prompt}]
    messages.extend(_build_history(history))
    messages.append({"role": "user", "content": user_parts})

    logger.info(
        "agent_request",
        extra={
            "agent": profile.key,
            "model": settings.openai_model,
            "verifier_model": settings.openai_verifier_model,
            "has_image": bool(image_bytes),
            "question_chars": len(question),
        },
    )

    structured = await _chat_with_schema(
        client=client,
        model=settings.openai_model,
        messages=messages,
        temperature=0.4,
        max_tokens=800,
    )

    verifier_messages = [
        {"role": "system", "content": VERIFICATION_PROMPT},
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"User question: {question.strip()}\n"
                        f"Image attached: {'yes' if image_bytes else 'no'}\n"
                        f"Agent output JSON: {json.dumps(structured, ensure_ascii=False)}"
                    ),
                }
            ],
        },
    ]
    if image_bytes:
        verifier_messages[-1]["content"].append(  # type: ignore[index]
            {"type": "image_url", "image_url": {"url": b64_from_upload(image_bytes, image_filename)}}
        )

    verified = await _chat_with_schema(
        client=client,
        model=settings.openai_verifier_model,
        messages=verifier_messages,
        temperature=0.2,
        max_tokens=600,
    )

    return {
        "agent": profile.key,
        "title": profile.title,
        "analysis_raw": structured,
        "verified": verified,
        "meta": {"model": settings.openai_model, "verifier": settings.openai_verifier_model},
    }
