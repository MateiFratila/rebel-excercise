# Semantic FAQ Assistant Implementation Plan

> Status: Mandatory delivery complete
> Current phase: Phase 8 complete; optional Phases 9-10 deferred
> Requirements baseline: [requirements.md](requirements.md)
> Governing architecture: [architecture.md](architecture.md)
> Last updated: 2026-08-09

## 1. Governance

This document is the executable delivery plan. [requirements.md](requirements.md) is immutable; [architecture.md](architecture.md) governs technical decisions. Update the architecture before implementing a conflicting boundary or contract, then update this plan's scope, sequence, and status.

A phase is complete only when its implementation and gate are complete. Mandatory delivery ends at the Phase 8 gate. Celery/Redis and live Azure are time-boxed extensions and do not block core acceptance.

Status markers:

- `[ ]` not started
- `[-]` in progress
- `[x]` complete
- `[~]` deferred time-boxed extension

## 2. Accepted Delivery Decisions

- Mandatory: FastAPI, React ask/admin UI, shared-password opaque sessions, PostgreSQL/pgvector, HTTP FAQ administration, incremental embeddings, LangGraph routing, guardrails, Docker Compose, CI, tests, and evaluation.
- Time-boxed: Celery with Redis broker and live Azure deployment with Bicep/CD.
- Local FAQ matches return the canonical stored answer verbatim.
- In-domain means general technical support: account support plus software, hardware, networking, devices, security, and developer-tool troubleshooting.
- Initial providers are `text-embedding-3-small` and `gpt-5.4-mini`, isolated behind ports.
- Similarity thresholds are provisional until calibrated from a labeled evaluation dataset.
- PostgreSQL is authoritative for embedding jobs. Core HTTP behavior returns `202` before a database-backed runner performs embedding work.

## 3. Delivery Phases

### Phase 0: Source of Truth

- [x] Reconcile canonical local answers, technical-support scope, initial models, LangGraph, and evaluation-based threshold calibration in the architecture.
- [x] Define Celery/Redis and live Azure as time-boxed extensions.
- [x] Define the core database-backed runner behind `TaskDispatcher`.
- [x] Create this implementation plan with phase status and gates.
- [x] Gate: architecture and implementation commitments agree, with no change to [requirements.md](requirements.md).

### Phase 1: Repository and Quality Foundation

- [x] Scaffold `backend/` for Python 3.12, FastAPI, SQLAlchemy 2, Alembic, LangChain/LangGraph, pgvector, and tests.
- [x] Scaffold `frontend/` for Node 22, TypeScript, React, Vite, Vitest, and React Testing Library.
- [x] Add `infra/bicep/`, `.github/workflows/`, and root container files without implementing optional deployment scope yet.
- [x] Add deterministic manifests, `.env.example`, `.gitignore`, editor settings, and task aliases. All secrets remain placeholders.
- [x] Establish Ruff, strict mypy, pytest/coverage, ESLint, strict TypeScript, Vitest, and secret/dependency scanning.
- [x] Add a minimal FastAPI composition root, React application shell, and pull-request CI workflow.
- [x] Gate: dependency installation, static checks, dependency audits, tests, frontend production build, non-root image build, Compose health smoke, secret scan, and responsive UI inspection pass.

### Phase 2: Contracts, Settings, and Persistence

- [x] Define domain types and ports for collections, FAQ items, jobs, sessions, retrieval, routing, providers, repositories, guardrails, and task dispatch.
- [x] Define transport schemas separately from ORM models, including the stable error envelope and `local | openai | compliance` answer source.
- [x] Implement typed settings with startup validation for database, OpenAI, model/dimension, collection, sessions, origins, thresholds, retries, limits, and logs.
- [x] Add Alembic migrations for pgvector, `faq_collections`, `faq_items`, `embedding_jobs`, and `auth_sessions`, including required constraints and cosine search support.
- [x] Extract exactly 33 FAQ records from the immutable requirements into a validated fixture without copying its OpenAI key.
- [x] Implement asynchronous SQLAlchemy repositories and atomic transaction boundaries.
- [x] Gate: empty-database migration, idempotent 33-record import, constraint tests, and repository integration tests pass.

### Phase 3: Shared-Password Authentication

- [x] Verify the configured shared password with Argon2id and apply generic failures plus configurable per-IP throttling.
- [x] Generate opaque session tokens with at least 256 random bits; persist only SHA-256 digests with an absolute seven-day expiry.
- [x] Implement `POST`, `GET`, and `DELETE /auth/session` with the required cookie flags and revocation behavior.
- [x] Protect all non-health application/admin routes through `Depends(get_session)`.
- [x] Validate `Origin` on login and state-changing requests; redact all credential material from logs.
- [x] Gate: login, cookie, status, expiry, revocation, logout, CSRF, throttling, and credential-exposure contract tests pass.

### Phase 4: Knowledge Administration and Retrieval

- [x] Implement normalization and stable content hashing without mutating canonical source content.
- [x] Implement the LangChain OpenAI embedding adapter with batching, dimensions checks, bounded retry/timeout handling, and deterministic test fakes.
- [x] Implement collection/item services and authenticated list, create, bulk upsert, optimistic patch, soft deactivate, readiness, and activation endpoints.
- [x] Implement durable embedding jobs and the core database-backed runner; return `202` plus `Location` before work begins.
- [x] Embed only new or changed content and make claiming, restart recovery, and vector writes idempotent.
- [x] Implement active-collection top-three pgvector cosine search using similarity `1 - distance`, excluding stale/inactive vectors.
- [x] Gate: create, import, queue, complete, activate, and retrieve succeeds; unchanged imports cause no embedding request; known paraphrases rank in the top three.

### Phase 5: Router, Guardrails, and Answer Providers

- [x] Implement schema/size validation, Unicode/whitespace normalization, injection/exfiltration heuristics, and safe reason enums.
- [x] Implement a structured general technical-support `ScopeClassifier` behind a port with a versioned taxonomy and deterministic fake.
- [x] Build the typed LangGraph workflow: normalize, guard, classify, retrieve, evaluate, route, compose, and validate.
- [x] Implement configurable confidence policy using top similarity, candidate margin, scope confidence, and data-quality signals.
- [x] Return canonical local answers without a chat call; use constrained `gpt-5.4-mini` fallback only for unmatched in-domain support.
- [x] Return the exact deterministic compliance text for out-of-domain requests.
- [x] Validate provider output and reject malformed content, leaked secrets/prompts, or unsupported account-action claims.
- [x] Wire `POST /ask-question` to stable schemas, request IDs, redacted logs, and safe dependency-error mappings.
- [x] Gate: table-driven workflow and API tests cover every local, OpenAI, compliance, guardrail, provider, and dependency edge; local answers make no chat call.

### Phase 6: React Application

- [x] Freeze the OpenAPI contract and establish one typed frontend client boundary without duplicating backend policy.
- [x] Build password login, session restoration, logout, and credentialed requests without Web Storage credentials.
- [x] Build the ask view with stable loading layout, validation, source/match presentation, request ID, and safe errors.
- [x] Build administration for collections/items, JSON import, edits/deactivation, job polling, readiness, and activation with complete empty/conflict/failure states.
- [x] Serve the production Vite build through FastAPI; use an allowlisted credentialed development path only locally.
- [x] Gate: component and Playwright tests cover login, reload persistence, local/compliance answers, import/embed/activate/retrieve, conflicts, and logout; no browser credential leakage occurs.

### Phase 7: Evaluation and Calibration

- [x] Create a versioned dataset separate from the 33 source records with paraphrases, near-neighbors, technical fallback, compliance, malformed, and injection cases.
- [x] Build a repeatable runner reporting Recall@1/3, MRR, route precision/recall, false-local rate, scope accuracy/F1, guardrail rates, schema validity, latency, tokens, and cost.
- [x] Sweep similarity and margin thresholds, prioritizing local-route precision and minimizing false local answers.
- [x] Record dataset/model/prompt/collection versions, selected operating point, known weak cases, and subjective fallback review.
- [x] Replace provisional defaults with measured settings and retain a deterministic no-live-OpenAI regression subset for CI.
- [x] Gate: one command reproduces the report and the selected thresholds have recorded evidence.

### Phase 8: Containers, CI, Observability, and Documentation

- [x] Build one multi-stage, non-root image for compiled React assets plus API and runner commands.
- [x] Add Compose for API, PostgreSQL/pgvector, core runner, migration job, and optional Vite with health-based startup and named volumes.
- [x] Complete CI for backend/frontend checks, tests, empty migration, Compose smoke, production build, image scan, and secret scan without live OpenAI calls.
- [x] Add structured logs and metrics for requests, routes, scores, auth, providers, tokens/cost, and jobs, with redaction tests.
- [x] Document setup, authentication limitations, management, models, thresholds, evaluation, failures, and exact local commands.
- [x] Gate: a clean clone reaches a healthy authenticated app through documented commands; Compose smoke and Playwright pass; every mandatory claim maps to executable evidence.

Phase 8 evidence on 2026-08-09: `make check` passed 76 backend tests at 90.72% coverage, 12 component tests, the production build, and 4 Playwright workflows against a fresh migrated database with no Alembic drift. `make evaluation`, `make security`, and `make compose-smoke` passed; the smoke proved real login/session/logout, one image digest, and non-root API/runner processes. Gitleaks found no history or working-tree leaks, exact challenge-key confinement passed, and Trivy found no fixed high/critical image vulnerabilities.

### Phase 9: Time-Boxed Celery/Redis Extension

- [~] Begin only after the Phase 8 gate; use Redis solely as Celery broker while PostgreSQL remains authoritative.
- [ ] Add a Celery `TaskDispatcher`, idempotent batch tasks, bounded retries, stale-job reconciliation, health/logging, and Compose `async` profile.
- [ ] Test publication failure, Redis restart, worker crash, duplicate delivery, malformed vectors, and durable recovery.
- [ ] Gate: the same admin and Playwright contracts pass with Celery; disabling the profile leaves the core runner functional.

### Phase 10: Time-Boxed Azure and CD Extension

- [~] Begin only after the reproducible image and Compose smoke gate.
- [ ] Add Bicep for ACR, Container Apps, PostgreSQL/pgvector, Log Analytics, managed identity, secrets, networking, and migration job.
- [ ] Add approved `main` deployment through GitHub OIDC, immutable commit-SHA image, migration, revision update, and authenticated smoke.
- [ ] Add alerts, dashboards, rollback documentation, and explicit single-replica/ephemeral-Redis limitations.
- [ ] Gate: Bicep validation/what-if, live HTTPS smoke, queryable logs, and rollback rehearsal pass with no long-lived Azure credential.

## 4. Final Acceptance

- [x] Run static checks; unit, contract, integration, and Playwright tests; empty migration; 33-record import; all routes; session/CSRF cases; incremental jobs; failure behavior; evaluation regression; and image/Compose smoke.
- [x] Audit requirement traceability so every claimed capability has executable evidence.
- [x] Verify the challenge OpenAI key exists nowhere outside immutable [requirements.md](requirements.md), including history and generated artifacts.
- [x] Mark this plan complete only after the mandatory Phase 8 gate; report optional extension status separately.

## 5. Verification Commands

These commands become stable contracts during Phase 1:

```bash
cd backend
uv sync --all-extras
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

```bash
cd frontend
npm ci
npm run lint
npm run typecheck
npm run test -- --run
npm run build
```

```bash
docker compose up --build --wait
```

## 6. Parallel Work and Risks

After Phase 2 contracts stabilize, authentication, retrieval, router policy, and the React shell may proceed in parallel using fakes. Docker/CI and evaluation-data authoring can mature alongside feature work, but threshold selection waits for completed real retrieval and routes.

Primary controls:

- Enforce the Phase 8 core stop line so optional infrastructure cannot delay completion.
- Keep password/session values out of storage, bundles, URLs, and logs; document the absence of identity and roles.
- Bound OpenAI cost through incremental batches, deterministic test fakes, retries, timeouts, and usage metrics.
- Treat cosine score as a ranking signal, never a probability; select thresholds from measured data.
- Version the broad support taxonomy and boundary examples to control scope drift.
- Prevent duplicate asynchronous work with durable transitions, atomic claims, hashes, and idempotent writes.
