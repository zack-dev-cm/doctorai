from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app import agents


class DummyMessage:
    def __init__(self, *, parsed: Dict[str, Any] | None = None, content: Any = None):
        self.parsed = parsed
        self.content = content


class DummyCompletion:
    def __init__(self, message: DummyMessage):
        self.choices = [type("Choice", (), {"message": message})()]


class DummyCompletions:
    def __init__(self, responses: List[Any]):
        self._responses = responses
        self.calls: List[Dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


class DummyClient:
    def __init__(self, completions: DummyCompletions):
        self.chat = type("Chat", (), {"completions": completions})()


@pytest.mark.asyncio
async def test_chat_with_schema_prefers_parsed_over_text() -> None:
    expected = {"answer": "ok", "provisional_diagnosis": "clear", "differentials": [], "followups": [], "plan": "", "triage": "", "risk_flags": "", "confidence": "0.5"}
    completion = DummyCompletion(DummyMessage(parsed=expected, content={"ignored": True}))
    comps = DummyCompletions([completion])
    client = DummyClient(comps)

    result = await agents._chat_with_schema(
        client=client,  # type: ignore[arg-type]
        model="model",
        messages=[],
        temperature=0.1,
        max_tokens=100,
    )

    assert result == expected


@pytest.mark.asyncio
async def test_chat_with_fallback_strips_optional_params_on_badrequest() -> None:
    req = httpx.Request("POST", "https://api.openai.com/chat/completions")
    bad_resp = httpx.Response(status_code=400, text="temperature unsupported", request=req)
    bad_error = agents.BadRequestError("Temperature unsupported", response=bad_resp, body=None)

    completion = DummyCompletion(DummyMessage(parsed={"answer": "ok", "provisional_diagnosis": "x", "differentials": [], "followups": [], "plan": "", "triage": "", "risk_flags": "", "confidence": "0.1"}))
    comps = DummyCompletions([bad_error, completion])
    client = DummyClient(comps)

    result = await agents._chat_with_schema(
        client=client,  # type: ignore[arg-type]
        model="model",
        messages=[{"role": "system", "content": "hi"}],
        temperature=0.2,
        max_tokens=50,
    )

    assert result["answer"] == "ok"
    first_call = comps.calls[0]
    retry_call = comps.calls[1]
    assert "temperature" in first_call
    assert "temperature" not in retry_call
    assert "reasoning_effort" not in retry_call


@pytest.mark.asyncio
async def test_run_agent_builds_image_and_history(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    analysis_payload = {"answer": "a", "provisional_diagnosis": "p", "differentials": ["d1"], "followups": ["f1"], "plan": "p", "triage": "t", "risk_flags": "r", "confidence": "0.5"}
    verified_payload = {**analysis_payload, "confidence": "0.4"}

    completions = DummyCompletions(
        [
            DummyCompletion(DummyMessage(parsed=analysis_payload)),
            DummyCompletion(DummyMessage(parsed=verified_payload)),
        ]
    )
    client = DummyClient(completions)

    image_bytes = b"fake"
    result = await agents.run_agent(
        question="Test question",
        agent_key="dermatologist",
        image_bytes=image_bytes,
        image_filename="sample.png",
        history=[{"role": "user", "content": "prev"}, {"role": "assistant", "content": "resp"}, {"role": "other", "content": "skip"}],
        client=client,  # type: ignore[arg-type]
    )

    assert result["analysis_raw"]["provisional_diagnosis"] == "p"
    assert result["verified"]["confidence"] == "0.4"

    first_messages = completions.calls[0]["messages"]
    assert any(msg.get("role") == "system" for msg in first_messages)
    user_msgs = [m for m in first_messages if m.get("role") == "user"]
    assert any(isinstance(msg.get("content"), list) for msg in user_msgs)
    assert any(
        part.get("type") == "image_url"
        for msg in user_msgs
        if isinstance(msg.get("content"), list)
        for part in msg["content"]
    )

    verifier_messages = completions.calls[1]["messages"]
    verifier_user = [m for m in verifier_messages if m.get("role") == "user"][0]
    assert any(part.get("type") == "image_url" for part in verifier_user["content"])
    assert "Agent output JSON" in verifier_user["content"][0]["text"]


def test_analyze_endpoint_uses_stubbed_agent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sample = {
        "agent": "dermatologist",
        "title": "Derm",
        "analysis_raw": {"answer": "a"},
        "verified": {"answer": "v", "provisional_diagnosis": "x", "differentials": [], "followups": [], "plan": "", "triage": "", "risk_flags": "", "confidence": "0.1"},
        "meta": {"model": "m", "verifier": "vm"},
    }

    async def fake_run_agent(**kwargs: Any) -> Dict[str, Any]:
        fake_run_agent.called = kwargs  # type: ignore[attr-defined]
        return sample

    monkeypatch.setattr(agents, "run_agent", fake_run_agent)
    monkeypatch.setattr(main, "run_agent", fake_run_agent)
    monkeypatch.setattr(agents.settings, "openai_api_key", "test-key")

    client = TestClient(main.app)
    resp = client.post("/analyze", data={"question": "Hello", "agent": "therapist"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["verification"]["answer"] == "v"
    assert fake_run_agent.called["agent_key"] == "therapist"  # type: ignore[attr-defined]
