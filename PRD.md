# DoctorAI PRD

## Goal
Deliver a dermatology-first AI assistant with therapist fallback that ingests text + images, asks clarifying questions, and returns safe, verified triage guidance suitable for a Telegram mini-app style experience.

## Users & Jobs
- **Patients / consumers**: quick, private triage for skin issues; understand urgency and home-care steps.
- **Therapy-seekers**: brief emotional support and coping suggestions when skin agent is not relevant.
- **Clinicians (lightweight)**: use as pre-visit intake for history gathering.

## Scope (v0)
- `/analyze` endpoint accepting `multipart/form-data` (`question`, optional `image`, optional `agent`).
- Default agent: dermatologist; alt: therapist.
- Structured JSON response with followups, provisional diagnosis, differentials, plan, triage, risk flags, confidence.
- OpenEvolve-style verification pass to enforce safety and humility.
- Web/TG-friendly UI: agent toggle, text field, image upload + preview, verified output panels.
- Docker/Cloud Run deploy script guidance.

## Out of scope (v0)
- EHR integration, PHI storage.
- Payments, auth, persistent user profiles.
- Full Telegram bot wiring (API-ready but not included).

## Requirements
- **Accuracy/Safety**: default dermatologist prompt; verification must downgrade risky recs.
- **Latency**: target <8s end-to-end for single image/text on gpt-5.1-2025-11-13.
- **Internationalization**: English default; agents respond in user language if requested.
- **Observability**: health endpoint; logs through Cloud Run.
- **Configurability**: models set via env; easy swap to Gemini when available.

## UX
- Bold dark theme; agent chips; visible followup questions; confidence indicator.
- Inline image preview and stateful status label.
- Error messaging for missing question or API failures.

## Deployment
- Containerized via `Dockerfile`; Cloud Run commands in `README.md`.
- Secrets via env/Secret Manager (`OPENAI_API_KEY`, optional `GOOGLE_API_KEY`).
- Repo creation via `DEV_CM_GITHUB_TOKEN` (manual command in README).

## Success metrics
- <2% unsafe outputs in QA set (manual review).
- Followup relevance rating ≥4/5 in pilot.
- p95 latency <10s on Cloud Run.

## Risks & mitigations
- **Hallucinated treatments** → verification pass + conservative prompts.
- **Poor image quality** → UI guide image + followups ask for clarity.
- **Scope creep** → therapist agent limited to triage/support, not treatment.

## Next steps
- Add Telegram bot surface and widget cards.
- Add test harness that scores JSON shape and red-flag coverage.
- Add model fallback to `gpt-5.1`/Gemini for robust multimodal analysis.
