#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   GCP_PROJECT=your-project GCP_REGION=us-east1 ./scripts/deploy_cloud_run.sh
# Requires gcloud auth + OPENAI_API_KEY in env/Secret Manager.

: "${GCP_PROJECT:?Set GCP_PROJECT}"
: "${GCP_REGION:=us-east1}"
: "${IMAGE_TAG:=gcr.io/${GCP_PROJECT}/doctorai:latest}"

echo "Building ${IMAGE_TAG}..."
gcloud builds submit --project "${GCP_PROJECT}" --tag "${IMAGE_TAG}"

echo "Deploying to Cloud Run..."
gcloud run deploy doctorai \
  --project "${GCP_PROJECT}" \
  --image "${IMAGE_TAG}" \
  --region "${GCP_REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars "OPENAI_API_KEY=${OPENAI_API_KEY}" \
  --set-env-vars "ENVIRONMENT=prod"

echo "Done. Fetch service URL with:"
echo "gcloud run services describe doctorai --project ${GCP_PROJECT} --region ${GCP_REGION} --format='value(status.url)'"
