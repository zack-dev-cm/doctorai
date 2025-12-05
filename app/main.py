from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agents import run_agent
from .config import settings

app = FastAPI(
    title="DoctorAI",
    description="Dermatology-focused AI with therapist option and verification guardrail.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = Path(__file__).parent.parent / "web"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


class AnalysisResponse(BaseModel):
    agent: str
    title: str
    result: dict
    verification: dict
    meta: dict


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "environment": settings.environment}


@app.get("/")
async def root() -> FileResponse:
    index_path = static_dir / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="UI not built yet.")
    return FileResponse(index_path)


@app.post("/analyze")
async def analyze(
    question: str = Form(..., description="User question or concern"),
    agent: Optional[str] = Form(None, description="Agent key (dermatologist|therapist)"),
    history: Optional[str] = Form(None, description="Optional JSON chat history"),
    image: Optional[UploadFile] = File(None, description="Optional image for analysis"),
) -> JSONResponse:
    if not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is required.")
    if not question or not question.strip():
        raise HTTPException(status_code=400, detail="Question is required.")

    image_bytes = await image.read() if image else None
    hist_payload: List[dict] | None = None
    if history:
        import json

        try:
            hist_payload = json.loads(history)
        except Exception as exc:  # pragma: no cover - defensive parsing
            raise HTTPException(status_code=400, detail=f"Invalid history JSON: {exc}") from exc

    result = await run_agent(
        question=question.strip(),
        agent_key=agent,
        image_bytes=image_bytes,
        image_filename=image.filename if image else None,
        history=hist_payload,
    )

    payload = AnalysisResponse(
        agent=result["agent"],
        title=result["title"],
        result=result["analysis_raw"],
        verification=result["verified"],
        meta=result["meta"],
    )
    return JSONResponse(content=payload.model_dump())


def run() -> None:
    """Allow `python -m app.main` to run the server."""
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    run()
