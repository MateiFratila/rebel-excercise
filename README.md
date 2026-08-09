# Rebel Dot Support

Semantic technical-support application with a React interface, FastAPI API, PostgreSQL/pgvector retrieval, guarded OpenAI fallback, durable embedding jobs, and shared-password sessions.

## Prerequisites

- Docker Desktop with Compose v2
- Python 3.12 and `uv` 0.12.3 for host development
- Node.js 22 for host frontend development
- An OpenAI API key for embedding and fallback requests

Install host dependencies and the Playwright browser once after cloning:

```bash
cd backend && uv sync --locked && cd ..
cd frontend && npm ci && npx playwright install chromium && cd ..
```

## Run with Docker Compose

Create the ignored runtime configuration:

```bash
cp .env.example .env
cd backend
uv sync --locked
uv run python -c 'import sys; from argon2 import PasswordHasher; print(PasswordHasher().hash(sys.argv[1]))' 'choose-a-password'
cd ..
```

Put the generated value in `SHARED_PASSWORD_HASH` in `.env` using single quotes so Compose preserves the hash's `$` characters, configure `OPENAI_API_KEY`, and replace the example database password in both `DATABASE_URL` and `POSTGRES_PASSWORD` with the same value. Do not put the cleartext shared password in any file.

Start the production-like core topology:

```bash
docker compose up --build -d --wait
open http://localhost:8000
```

The same non-root image runs the API, PostgreSQL polling runner, and one-shot migration command. PostgreSQL data is stored in a named volume. Stop the stack with:

```bash
docker compose down
```

Add `-v` only when intentionally deleting local database data.

## Host Development

Run PostgreSQL, then use separate host-oriented backend settings:

```bash
docker compose up -d --wait postgres
cp backend/.env.example backend/.env
cd backend
uv sync --locked
uv run alembic upgrade head
cd ..
make backend-dev
```

Configure the key and password hash in `backend/.env`. In another terminal:

```bash
make frontend-dev
```

Open `http://127.0.0.1:5173`. Host development keeps the embedding runner inside the API process. To run Vite inside Compose instead:

```bash
docker compose --profile dev up --build -d --wait
```

## Authentication

This challenge uses one operator-distributed password, not user identity or role-based authorization. The backend stores only an Argon2id password hash and SHA-256 digests of random session tokens. Browser sessions use an `HttpOnly`, `SameSite=Strict` cookie with a fixed seven-day lifetime. Local HTTP may set `SESSION_COOKIE_SECURE=false`; every non-local environment requires secure cookies, and production requires HTTPS origins.

Changing the password hash affects new logins. Existing opaque sessions remain valid until logout, revocation, or expiry.

## Knowledge Management

After login, use **Knowledge** to:

1. Create a collection matching the configured embedding model and dimensions.
2. Import or edit FAQ items.
3. Queue an embedding job and monitor it in **Jobs**.
4. Activate the collection only after readiness reports no pending items.

FAQ updates are incremental and optimistic. PostgreSQL is authoritative for queued/running job state; the runner safely reclaims stale work. Local answers return canonical FAQ text verbatim. Deactivation is soft and excludes the item from active retrieval.

## Models and Routing

- Embeddings: `text-embedding-3-small`, 1536 dimensions
- Fallback/scope model: `gpt-5.4-mini`
- Scope taxonomy: `general-technical-support-v1`
- Local similarity threshold: `0.84`
- Top-to-second margin: `0.08`
- Scope confidence threshold: `0.75`

The operating point is selected by the versioned evaluation suite with local precision prioritized over recall. Reproduce the committed deterministic evidence without live provider calls:

```bash
make evaluation
```

See [the evaluation report](backend/evaluation/reports/support-routing-v1.deterministic.md) for metrics, weak cases, and limitations. Deterministic observations are regression evidence, not live-provider or production-latency measurements.

Provider requests use the configured timeout and bounded SDK exponential retries (`OPENAI_MAX_RETRIES=2` by default). After those attempts are exhausted, the runner records the batch failure and continues durable job processing without duplicating successful items.

## Observability

Application logs are structured JSON with timestamp, level, event, request ID, route, status, and latency where applicable. Redaction removes fields whose names may contain passwords, tokens, cookies, API keys, questions, answers, or secrets. Normal logs never contain request bodies or answer text.

Prometheus exposition is available at `GET /metrics`. It includes bounded-label HTTP, active-session/authentication, route, top-similarity, guardrail, provider, and embedding-job metrics. Question logs include safe collection and configured model versions. Token and estimated-cost collectors are present but remain zero because the current strict LangChain structured-output adapter does not retain provider usage metadata; the offline evaluation report contains recorded usage comparisons.

Liveness is `GET /health/live`. Readiness is `GET /health/ready` and remains `503` until a compatible active collection exists.

## Failure Behavior

| Status | Meaning                                                  |
| ------ | -------------------------------------------------------- |
| `401`  | Invalid password or missing, expired, or revoked session |
| `403`  | Browser origin is not allowed                            |
| `404`  | Administration resource does not exist                   |
| `409`  | Concurrent edit or incompatible collection state         |
| `422`  | Invalid request or rejected input guardrail              |
| `429`  | Login or provider rate limit                             |
| `502`  | Invalid provider output                                  |
| `503`  | Database, runner, or provider unavailable                |
| `504`  | Provider timeout                                         |

Errors expose stable codes and request IDs but not dependency details.

## Verification

```bash
make check
make evaluation
make compose-smoke
make security
```

`make compose-smoke` uses isolated ports and volumes, builds the production image, runs fresh migrations, waits for API/runner health, verifies SPA delivery, checks non-root execution, proves all process roles use one image digest, and cleans up. It uses no live OpenAI request.

CI also runs an empty-migration check, Playwright, dependency audits, Gitleaks, the Compose smoke, and a Trivy high/critical image scan.

## Architecture

[architecture.md](architecture.md) is the governing design and [implementation.md](implementation.md) is the delivery ledger. The challenge requirements file is intentionally untracked because its supplied credential must not enter Git history.
