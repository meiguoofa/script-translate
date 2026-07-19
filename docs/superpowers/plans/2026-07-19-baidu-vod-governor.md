# Baidu VOD Governor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce account-wide Baidu VOD QPS and episode concurrency with safe transient-error retries and visible runtime limits.

**Architecture:** Create one application-scoped governor that owns the shared request limiter and both concurrency semaphores. Inject it into every Baidu VOD runner/client so all jobs share the same limits, while preserving legacy request and database fields.

**Tech Stack:** Python 3.12, FastAPI, asyncio, httpx, pytest, React, TypeScript, Vite

---

### Task 1: Application-scoped governor

- [ ] Add failing tests for shared QPS acquisition, Job concurrency, episode concurrency, and slot release.
- [ ] Add validated global QPS and episode concurrency settings.
- [ ] Implement `BaiduVodGovernor` and attach one instance to FastAPI application state.
- [ ] Run focused tests and commit.

### Task 2: Safe HTTP retry policy

- [ ] Add failing tests for POST/GET 429, GET network/5xx, POST network/5xx, retry exhaustion, and `Retry-After`.
- [ ] Add structured `BaiduVodApiError` and a four-attempt request loop.
- [ ] Acquire a global QPS token before every HTTP attempt and keep logs free of credentials.
- [ ] Run focused tests and commit.

### Task 3: Runner and API integration

- [ ] Add failing runner tests proving no more than three episode pipelines execute concurrently.
- [ ] Replace module-global Job semaphore usage with Governor Job/episode contexts.
- [ ] Add the protected runtime-limits endpoint and preserve optional legacy `qps` request compatibility.
- [ ] Persist the effective global QPS for create, retry, and rerun entrypoints.
- [ ] Run focused router/runner tests and commit.

### Task 4: Frontend runtime-limit display

- [ ] Remove editable and submitted Job QPS state.
- [ ] Add the runtime-limits API type/client and display the three values read-only.
- [ ] Ignore legacy saved `qps` form data.
- [ ] Run the production frontend build and commit.

### Task 5: Verification and deployment

- [ ] Run the full backend suite, frontend production build, and `git diff --check`.
- [ ] Merge and push the verified branch.
- [ ] Query running Baidu VOD jobs; stop and record any active IDs without automatically rerunning them.
- [ ] Deploy from the isolated worktree and verify systemd, health, runtime limits, frontend output, and startup logs.
