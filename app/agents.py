from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from .config import settings


BASE_RESPONSE_SCHEMA = {
    "answer": "Concise, empathetic response that summarizes likely diagnosis (if any) and next steps.",
    "provisional_diagnosis": "Single best-fit label if possible, otherwise 'unclear'.",
    "differentials": ["Up to 3 alternative possibilities."],
    "followups": ["3-5 targeted, closed-ended clarifying questions."],
    "plan": "Actionable plan (home care, OTC/Rx to ask provider about, self-monitoring).",
    "triage": "When to seek urgent in-person care vs routine dermatology/therapy consult.",
    "risk_flags": "Red flags matched from presentation.",
    "confidence": "0.0-1.0 estimated confidence; be conservative.",
}


@dataclass
class AgentProfile:
    key: str
    title: str
    description: str
    tone: str
    specialties: List[str]

    @property
    def system_prompt(self) -> str:
        schema_json = json.dumps(BASE_RESPONSE_SCHEMA, indent=2)
        specialties = ", ".join(self.specialties)
        return (
            f"You are {self.title}, a meticulous clinician. Specialty: {specialties}. "
            f"Tone: {self.tone}. "
            "Default language: English unless user asks otherwise. "
            "You act as part of a Mixture-of-Experts ensemble and must deliver structured JSON only. "
            "Always consider dermatology-appropriate red flags (fever, rapidly spreading rash, mucosal involvement, pain, immunosuppression) "
            "and therapy safety flags (self-harm, harm to others, psychosis, substance withdrawal). "
            "When unsure, state uncertainty explicitly. "
            "Never provide definitive medical diagnoses or prescriptions; recommend clinician follow-up. "
            "Respect the user's context, age, and comorbidities when provided. "
            "Ask for missing critical data via followup questions. "
            f"Reply in JSON matching this schema (keys only, no extra text): {schema_json}"
        )


AGENT_PROFILES: Dict[str, AgentProfile] = {
    "dermatologist": AgentProfile(
        key="dermatologist",
        title="Dermatology Attending Physician",
        description="Focus on rashes, lesions, acne, inflammatory skin conditions, infections, and wound healing.",
        tone="precise, reassuring, avoids alarmism",
        specialties=[
            "medical dermatology",
            "infectious disease differentials",
            "dermoscopy heuristics",
            "skin care routines",
        ],
    ),
    "therapist": AgentProfile(
        key="therapist",
        title="Generalist Therapist",
        description="Focus on emotional support, CBT/DBT inspired coping, brief assessment of risk.",
        tone="supportive, concise, trauma-informed",
        specialties=["anxiety", "depression", "stress management", "sleep hygiene"],
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


def parse_structured_response(content: str) -> Dict[str, Any]:
    """Try to coerce the model reply into the expected dict."""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        cleaned = content.strip()
        # Best-effort fix common issues.
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

    user_parts: List[Dict[str, Any]] = [{"type": "text", "text": question.strip()}]
    if image_bytes:
        user_parts.append(
            {"type": "image_url", "image_url": {"url": b64_from_upload(image_bytes, image_filename)}}
        )

    messages: List[Dict[str, Any]] = [{"role": "system", "content": profile.system_prompt}]
    if history:
        for item in history:
            if item.get("role") in {"user", "assistant"} and item.get("content"):
                messages.append({"role": item["role"], "content": item["content"]})
    messages.append({"role": "user", "content": user_parts})

    analysis = await client.chat.completions.create(
        model=settings.openai_model,
        messages=messages,
        temperature=0.4,
        max_tokens=800,
    )
    analysis_content = analysis.choices[0].message.content or "{}"
    structured = parse_structured_response(analysis_content)

    verification_prompt = (
        "You are a safety and quality verifier (OpenEvolve style). "
        "Given the user request, the agent JSON output, and optional image context, ensure the reply is safe, "
        "clinically humble, and follows schema keys exactly. "
        "Fix hallucinated drug dosing, add disclaimers, and re-rank differentials if needed. "
        "Return corrected JSON only. If content is unsafe or missing, produce conservative guidance with followups."
    )

    verifier_messages = [
        {"role": "system", "content": verification_prompt},
        {
            "role": "user",
            "content": f"User question: {question}\nAgent output JSON: {json.dumps(structured, ensure_ascii=False)}",
        },
    ]
    verification = await client.chat.completions.create(
        model=settings.openai_verifier_model,
        messages=verifier_messages,
        temperature=0.2,
        max_tokens=600,
    )
    verified_content = verification.choices[0].message.content or "{}"
    verified = parse_structured_response(verified_content)

    return {
        "agent": profile.key,
        "title": profile.title,
        "analysis_raw": structured,
        "verified": verified,
        "meta": {"model": settings.openai_model, "verifier": settings.openai_verifier_model},
    }
