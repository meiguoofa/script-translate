# Portrait Video Layout Probe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent native portrait OSS videos from repeatedly failing before subtitle burn because remote layout probes exceed fixed local-file timeouts.

**Architecture:** Keep the existing `VideoLayout` and stable pillarbox detection contract. Add a portrait fast path after the canvas size probe, and select longer subprocess timeouts only for HTTP(S) sources; local file behavior and the existing reliable-failure path remain unchanged.

**Tech Stack:** Python 3.12, FFmpeg/ffprobe subprocesses, pytest

---

### Task 1: Add regression tests for portrait fast path and source-specific timeouts

**Files:**
- Modify: `backend/tests/test_ffmpeg_burn.py`

- [ ] **Step 1: Write the failing portrait fast-path test**

```python
def test_probe_video_layout_returns_full_frame_for_portrait_without_crop_probe(
    monkeypatch,
) -> None:
    monkeypatch.setattr(ffmpeg_burn, "probe_video_size", lambda _path: (1080, 1920))

    def fail_probe(*_args, **_kwargs):
        raise AssertionError("portrait video must not run another probe")

    monkeypatch.setattr(ffmpeg_burn, "probe_video_duration_seconds", fail_probe)
    monkeypatch.setattr(ffmpeg_burn, "_probe_crop_sample", fail_probe)

    assert probe_video_layout("portrait.mp4") == VideoLayout.full_frame(1080, 1920)
```

- [ ] **Step 2: Write failing timeout-selection tests**

```python
@pytest.mark.parametrize(
    ("video_path", "expected_timeout"),
    [
        ("episode.mp4", 30),
        ("https://example/episode.mp4", 60),
    ],
)
def test_probe_video_size_uses_source_specific_timeout(
    monkeypatch,
    video_path: str,
    expected_timeout: int,
) -> None:
    calls: list[int] = []

    def fake_run(command, **kwargs):
        calls.append(kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0, stdout="1920,1080\n", stderr="")

    monkeypatch.setattr(ffmpeg_burn.subprocess, "run", fake_run)

    assert ffmpeg_burn.probe_video_size(video_path) == (1920, 1080)
    assert calls == [expected_timeout]


@pytest.mark.parametrize(
    ("video_path", "expected_timeout"),
    [
        ("episode.mp4", 15),
        ("https://example/episode.mp4", 45),
    ],
)
def test_probe_crop_sample_uses_source_specific_timeout(
    monkeypatch,
    video_path: str,
    expected_timeout: int,
) -> None:
    calls: list[int] = []

    def fake_run(command, **kwargs):
        calls.append(kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(ffmpeg_burn.subprocess, "run", fake_run)

    assert ffmpeg_burn._probe_crop_sample(video_path, 10) is None
    assert calls == [expected_timeout]
```

- [ ] **Step 3: Run the new tests and verify RED**

Run:

```bash
PYTHONPATH=backend pytest \
  backend/tests/test_ffmpeg_burn.py::test_probe_video_layout_returns_full_frame_for_portrait_without_crop_probe \
  backend/tests/test_ffmpeg_burn.py::test_probe_video_size_uses_source_specific_timeout \
  backend/tests/test_ffmpeg_burn.py::test_probe_crop_sample_uses_source_specific_timeout -q
```

Expected: five failing cases because portrait videos still invoke duration/crop probes and remote sources still use 30/15-second timeouts.

### Task 2: Implement the minimal layout probe fix

**Files:**
- Modify: `backend/app/services/ffmpeg_burn.py`
- Test: `backend/tests/test_ffmpeg_burn.py`

- [ ] **Step 1: Select longer timeouts for HTTP(S) sources**

In `probe_video_size`, calculate:

```python
timeout_seconds = 60 if video_path.startswith(("http://", "https://")) else 30
```

and pass `timeout=timeout_seconds` to `subprocess.run`.

In `_probe_crop_sample`, calculate:

```python
timeout_seconds = 45 if video_path.startswith(("http://", "https://")) else 15
```

and use it for every retry.

- [ ] **Step 2: Return immediately for a native portrait canvas**

Immediately after constructing `full_frame` in `probe_video_layout`, add:

```python
if canvas_width < canvas_height:
    logger.info(
        "portrait canvas uses full frame without crop detection: "
        "path=%s canvas=%sx%s",
        video_path,
        canvas_width,
        canvas_height,
    )
    return full_frame
```

- [ ] **Step 3: Run the focused tests and verify GREEN**

Run:

```bash
PYTHONPATH=backend pytest backend/tests/test_ffmpeg_burn.py -q
```

Expected: 14 tests pass.

- [ ] **Step 4: Run layout integration regression tests**

Run:

```bash
PYTHONPATH=backend pytest \
  backend/tests/test_ffmpeg_burn.py \
  backend/tests/test_subtitle_erase_translate_layout.py -q
```

Expected: 26 tests pass.

### Task 3: Verify, integrate, and deploy

**Files:**
- Verify: `backend/app/services/ffmpeg_burn.py`
- Verify: `backend/tests/test_ffmpeg_burn.py`

- [ ] **Step 1: Run static and repository verification**

```bash
git diff --check
python -m compileall -q backend/app backend/tests
PYTHONPATH=backend pytest backend/tests -q
```

Record any pre-existing dependency collection failures separately; no new failure may be introduced.

- [ ] **Step 2: Verify the real failed OSS video without downloading it**

From the deployed backend environment, call `probe_video_layout` with the existing public OSS URL and duration `62.647007`. Expected:

```text
VideoLayout(canvas_width=1080, canvas_height=1920, content_x=0, content_y=0, content_width=1080, content_height=1920)
```

The check must not create a local video file or submit translation/MPS work.

- [ ] **Step 3: Commit, fast-forward main, push, and deploy**

Commit the code and tests, fast-forward `main`, push `origin/main`, copy only the changed backend service file to `/opt/script-translate/`, restart `script-translate.service`, and verify:

```bash
systemctl is-active script-translate.service
curl -fsS http://127.0.0.1:8901/api/health
```

Expected: `active` and `{"status":"ok"}`.
