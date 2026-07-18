# Baidu VOD BOS URI Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow completed Baidu BOS uploads to create Baidu VOD jobs while preserving compatible item fields and recording BOS metadata.

**Architecture:** Keep the existing `oss_uri` wire field and JSON layout to avoid a migration. Correct only the Baidu VOD route's protocol validation and populate the already-defined BOS metadata fields; the runner continues fetching the public URL.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy asyncio, pytest, httpx ASGITransport, React/TypeScript build.

---

### Task 1: Add endpoint regression coverage

**Files:**
- Create: `backend/tests/test_baidu_vod.py`
- Test: `backend/tests/test_baidu_vod.py`

- [ ] **Step 1: Write a failing BOS creation test**

Create an isolated app with a temporary SQLite database, replace `run_baidu_vod_job` with an async no-op, POST a complete job payload containing `bos://test-bucket/baidu-vod-input/job/00-ep.mp4`, and assert status 201 plus:

```python
item = response.json()["items"][0]
assert item["input_bos_key"] == "baidu-vod-input/job/00-ep.mp4"
assert item["input_bos_uri"] == "bos://test-bucket/baidu-vod-input/job/00-ep.mp4"
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```bash
cd backend && ../.venv/bin/pytest tests/test_baidu_vod.py::test_create_baidu_vod_job_accepts_bos_uri_and_persists_bos_metadata -q
```

Expected: FAIL because the endpoint returns 400 instead of 201.

- [ ] **Step 3: Add rejection coverage**

Add a second test using `oss://legacy-bucket/ep.mp4` and assert status 400 with `bos_uri` in the detail message.

### Task 2: Correct the route validation and persistence

**Files:**
- Modify: `backend/app/routers/baidu_vod.py:333-357`
- Test: `backend/tests/test_baidu_vod.py`

- [ ] **Step 1: Implement the minimum production change**

Use the following validation:

```python
for it in payload.items:
    if not it.oss_uri.startswith("bos://"):
        raise HTTPException(status_code=400, detail=f"非法的视频 bos_uri: {it.oss_uri}")
```

Persist BOS metadata while keeping the legacy compatibility field:

```python
"input_oss_uri": spec.oss_uri,
"input_public_url": spec.public_url,
"input_bos_key": spec.key,
"input_bos_uri": spec.oss_uri,
```

- [ ] **Step 2: Run the focused tests to verify GREEN**

Run:

```bash
cd backend && ../.venv/bin/pytest tests/test_baidu_vod.py -q
```

Expected: both tests pass.

### Task 3: Regression, build, and deployment verification

**Files:**
- Verify: `backend/app/routers/baidu_vod.py`
- Verify: `backend/tests/test_baidu_vod.py`

- [ ] **Step 1: Run the complete backend suite**

```bash
cd backend && ../.venv/bin/pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run the frontend production build**

```bash
cd frontend && npm run build
```

Expected: TypeScript compilation and Vite build exit 0.

- [ ] **Step 3: Deploy the backend change**

Copy the changed route into `/opt/script-translate/backend/app/routers/baidu_vod.py`, restart `script-translate.service`, and confirm it is active. Do not overwrite the user's unrelated modified BOS client.

- [ ] **Step 4: Verify the deployed API**

Run the service health endpoint and confirm HTTP 200, then inspect the service journal for startup errors.

- [ ] **Step 5: Review the final diff**

```bash
git diff --check
git status --short
git diff -- backend/app/routers/baidu_vod.py backend/tests/test_baidu_vod.py
```

Expected: no whitespace errors and only the scoped route/test changes plus pre-existing user work.
