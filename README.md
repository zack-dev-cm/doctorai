# DoctorAI

Dermatology-first AI triage with an optional therapist mode, image-aware analysis, and verification guardrails.

## Quickstart
- Requirements: Python 3.10+, `OPENAI_API_KEY` in env (reads from `.env` if present). Optional: `GOOGLE_API_KEY` for future Gemini routing. Default models: `gpt-4.1-mini` for both analysis and verification.
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

## E2E testing (Playwright)
- Install deps: `npm install && npx playwright install --with-deps`.
- Run the app (`uvicorn app.main:app --host 0.0.0.0 --port 8000`), then `PLAYWRIGHT_BASE_URL=http://localhost:8000 npm run test:e2e`.
- Tests live in `tests/e2e/user-flows.spec.ts`: they mock `/analyze`, simulate dermatologist/therapist flows with image upload, verify followups/triage rendering, check status changes under slower responses, and capture UI screenshots to the test output directory.

## Logging/ops
- API logs show structured events: `analyze_request` (agent, has_image, chars) and `analyze_response` (agent, provisional, confidence).
- To tail Cloud Run logs: `gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=doctorai" --project $GCP_PROJECT --limit=50`

## Deployment (Cloud Run, step-by-step)
Prereqs: `gcloud` authenticated, project/region set (`gcloud config set project ...`), `OPENAI_API_KEY` available, and optional `TELEGRAM_BOT_TOKEN` if you run the bot.

1) Set shell variables (change region if needed):
```bash
export GCP_PROJECT=$(gcloud config get-value project)
export GCP_REGION=us-east1
export IMAGE_TAG=gcr.io/${GCP_PROJECT}/doctorai:latest
```

2) Create or update secrets (one-time; do not hardcode keys):
```bash
echo -n "$OPENAI_API_KEY" | gcloud secrets create doctorai-openai-api-key --data-file=- --replication-policy=automatic || \
echo -n "$OPENAI_API_KEY" | gcloud secrets versions add doctorai-openai-api-key --data-file=-

# Optional Telegram bot token
if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
  echo -n "$TELEGRAM_BOT_TOKEN" | gcloud secrets create doctorai-telegram-bot-token --data-file=- --replication-policy=automatic || \
  echo -n "$TELEGRAM_BOT_TOKEN" | gcloud secrets versions add doctorai-telegram-bot-token --data-file=-
fi
```

3) Build and push the container:
```bash
gcloud builds submit --project "$GCP_PROJECT" --tag "$IMAGE_TAG"
```

4) Deploy to Cloud Run (public URL):
```bash
gcloud run deploy doctorai \
  --project "$GCP_PROJECT" \
  --region "$GCP_REGION" \
  --platform managed \
  --image "$IMAGE_TAG" \
  --allow-unauthenticated \
  --set-env-vars ENVIRONMENT=prod,WEB_APP_URL=https://doctorai-${GCP_PROJECT}.a.run.app \
  --update-secrets OPENAI_API_KEY=doctorai-openai-api-key:latest \
  $( [ -n "$TELEGRAM_BOT_TOKEN" ] && echo --update-secrets TELEGRAM_BOT_TOKEN=doctorai-telegram-bot-token:latest )
```
The service URL is printed after deploy (also: `gcloud run services describe doctorai --region $GCP_REGION --format='value(status.url)'`).

5) Smoke test prod:
```bash
curl -sSf https://YOUR_SERVICE_URL/health
curl -sS -X POST https://YOUR_SERVICE_URL/analyze -F 'question=Small itchy rash, no fever' -F 'agent=dermatologist'
```

6) Run UI E2E against prod (optional):
```bash
PLAYWRIGHT_BASE_URL=https://YOUR_SERVICE_URL npx playwright test
```

7) Tail logs:
```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=doctorai" --limit=50 --order=desc
```

## Repo bootstrap
- Public repo can be created with `GITHUB_TOKEN=$DEV_CM_GITHUB_TOKEN gh repo create doctorai --public --source=. --remote=origin --push` (token stays in env).
- Do **not** commit secrets. Use Cloud Run/Secret Manager for keys.

## Testing
- Minimal FastAPI surface; add tests with `pytest` as needed for prompt parsing and response shape.

See `AGENTS.md` for detailed prompt design and `PRD.md` for product scope.*** End Patch
