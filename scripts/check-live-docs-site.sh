#!/usr/bin/env bash
# Verify the public Fleet handbook responds after deploy (requires outbound HTTPS).
set -euo pipefail
BASE="${1:-https://fleet.forgesdlc.com}"

echo "==> GET ${BASE}/"
curl -fsS "${BASE}/" | grep -q "Learn 101" || {
  echo "home page missing Learn 101 marker" >&2
  exit 1
}

echo "==> GET ${BASE}/schemas/openapi.json"
OPENAPI="$(curl -fsS "${BASE}/schemas/openapi.json")"
echo "$OPENAPI" | grep -q '"operationId"' || {
  echo "OpenAPI missing operationId fields" >&2
  exit 1
}
echo "$OPENAPI" | grep -q '"description"' || {
  echo "OpenAPI missing per-operation description fields" >&2
  exit 1
}
echo "$OPENAPI" | grep -q "uploadJobWorkspace" || {
  echo "OpenAPI missing uploadJobWorkspace operationId" >&2
  exit 1
}
echo "$OPENAPI" | grep -q "application/octet-stream" || {
  echo "OpenAPI missing binary upload media type (application/octet-stream)" >&2
  exit 1
}

echo "==> GET ${BASE}/docs-learn-101-06-first-fleet-job.html"
curl -fsS "${BASE}/docs-learn-101-06-first-fleet-job.html" | grep -q "docker_argv" || {
  echo "first job page missing docker_argv" >&2
  exit 1
}
curl -fsS "${BASE}/docs-learn-101-06-first-fleet-job.html" | grep -q "201" || {
  echo "first job page missing HTTP 201 reference" >&2
  exit 1
}

echo "==> GET ${BASE}/schemas/job-create-request.schema.json"
curl -fsS -o /dev/null "${BASE}/schemas/job-create-request.schema.json"

echo "==> GET ${BASE}/schemas/workspace-upload-response.schema.json"
curl -fsS -o /dev/null "${BASE}/schemas/workspace-upload-response.schema.json"

echo "check-live-docs-site: OK (${BASE})"
