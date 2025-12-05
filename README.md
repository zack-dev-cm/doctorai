# DoctorAI

Dermatology-first AI triage with an optional therapist mode, image-aware analysis, and verification guardrails.

## Quickstart
- Requirements: Python 3.10+, `OPENAI_API_KEY` in env (reads from `.env` if present). Optional: `GOOGLE_API_KEY` for future Gemini routing. Default models: `gpt-5.1-2025-11-13` for both analysis and verification (reasoning_effort `medium`).
- Install deps: `pip install .`
- Run API + UI: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- Open `http://localhost:8000` for the mini web app. `POST /analyze` accepts `multipart/form-data` (`question`, optional `agent`, optional `image`).

## Endpoint
- `POST /analyze`
  - `question` (text, required)
  - `agent` (`dermatologist` default, or `therapist`)
  - `image` (file, optional)
  - Returns JSON with the original agent output and a verification-corrected reply (OpenEvolve-style safety pass).
- `GET /health` basic health check.

## Architecture
- `app/agents.py` defines the Mixture-of-Experts style profiles (dermatologist default, therapist), structured JSON schema, and a verifier pass that re-scores/guards the answer.
- `app/main.py` hosts FastAPI, static UI, and `/analyze`.
- `app/bot.py` is an async Telegram bot (polling) that sends a Web App button and can ingest text/photos directly, returning the verified JSON as Markdown.
- `web/index.html` is a lightweight TG-style UI with image preview, agent toggle, and verified output view.
- Assets live in `assets/` for branding and onboarding visuals.

## Telegram mini-app
- Env: `TELEGRAM_BOT_TOKEN` (token from BotFather), `WEB_APP_URL` (e.g., your Cloud Run URL).
- Run locally: `TELEGRAM_BOT_TOKEN=xxx WEB_APP_URL=http://localhost:8000 python -m app.bot`
- Bot commands: `/start` (sends Web App button), `/mode dermatologist|therapist` switches agent. Send photo+caption or text to get a verified answer.

## Deployment (Cloud Run)
Based on the `bvis` Cloud Run pattern:
1) Build and push:
```bash
gcloud builds submit --tag gcr.io/$GCP_PROJECT/doctorai:latest
```
2) Deploy:
```bash
gcloud run deploy doctorai \
  --image gcr.io/$GCP_PROJECT/doctorai:latest \
  --platform managed --region $GCP_REGION \
  --set-env-vars OPENAI_API_KEY=${OPENAI_API_KEY},ENVIRONMENT=prod \
  --allow-unauthenticated
```
3) Logs: `gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=doctorai" --limit=50`

## Repo bootstrap
- Public repo can be created with `GITHUB_TOKEN=$DEV_CM_GITHUB_TOKEN gh repo create doctorai --public --source=. --remote=origin --push` (token stays in env).
- Do **not** commit secrets. Use Cloud Run/Secret Manager for keys.

## Testing
- Minimal FastAPI surface; add tests with `pytest` as needed for prompt parsing and response shape.

See `AGENTS.md` for detailed prompt design and `PRD.md` for product scope.*** End Patch
