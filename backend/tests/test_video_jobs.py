import sys
from importlib import import_module, reload

import pytest
from httpx import ASGITransport, AsyncClient


def clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "DOUBAO_API_KEY",
        "DOUBAO_MODELS",
        "TONGYI_API_KEY",
        "ZHIPU_API_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)


def load_create_app():
    module_name = "app.main"
    if module_name in sys.modules:
        module = reload(sys.modules[module_name])
    else:
        module = import_module(module_name)
    return module.create_app


def base_env(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    clear_provider_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/app.db")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("DEFAULT_PROVIDER", "doubao")
    monkeypatch.setenv("DOUBAO_API_KEY", "test-key")
    monkeypatch.setenv("DOUBAO_MODELS", "doubao-seed-1-6-flash-250715")
    monkeypatch.setenv("ACCESS_PASSPHRASE", "test-pass")
    monkeypatch.setenv("LAS_API_KEY", "las-test")
    monkeypatch.setenv("TOS_ACCESS_KEY_ID", "tos-test-id")
    monkeypatch.setenv("TOS_SECRET_ACCESS_KEY", "tos-test-secret")


@pytest.mark.asyncio
async def test_access_verify_accepts_correct_passphrase(tmp_path, monkeypatch):
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        ok = await client.post("/api/access/verify", json={"passphrase": "test-pass"})
        bad = await client.post("/api/access/verify", json={"passphrase": "wrong"})
    assert ok.status_code == 200 and ok.json()["ok"] is True
    assert bad.status_code == 401


@pytest.mark.asyncio
async def test_prompt_templates_default_seeded_and_immutable(tmp_path, monkeypatch):
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        listing = await client.get("/api/prompt-templates")
        assert listing.status_code == 200
        items = listing.json()
        assert any(it["id"] == "default-las" and it["is_default"] for it in items)

        # 401 without passphrase
        no_auth = await client.put(
            "/api/prompt-templates/default-las", json={"name": "x"}
        )
        assert no_auth.status_code == 401

        # default is immutable even with passphrase
        forbid = await client.put(
            "/api/prompt-templates/default-las",
            json={"name": "x"},
            headers={"X-Access-Passphrase": "test-pass"},
        )
        assert forbid.status_code == 400


@pytest.mark.asyncio
async def test_prompt_templates_create_and_update(tmp_path, monkeypatch):
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()
    headers = {"X-Access-Passphrase": "test-pass"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        created = await client.post(
            "/api/prompt-templates",
            json={"name": "自定义A", "content": "你好"},
            headers=headers,
        )
        assert created.status_code == 201
        cid = created.json()["id"]

        updated = await client.put(
            f"/api/prompt-templates/{cid}",
            json={"name": "自定义A2", "content": "你好2"},
            headers=headers,
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "自定义A2"
        assert updated.json()["content"] == "你好2"

        listing = await client.get("/api/prompt-templates")
        names = {it["id"]: it["name"] for it in listing.json()}
        assert names[cid] == "自定义A2"
        assert "default-las" in names


@pytest.mark.asyncio
async def test_video_jobs_upload_url_requires_passphrase(tmp_path, monkeypatch):
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        no_auth = await client.post(
            "/api/video-jobs/upload-url",
            json={"files": [{"filename": "a.mp4", "content_type": "video/mp4"}]},
        )
        assert no_auth.status_code == 401

        ok = await client.post(
            "/api/video-jobs/upload-url",
            json={"files": [{"filename": "a.mp4", "content_type": "video/mp4"}]},
            headers={"X-Access-Passphrase": "test-pass"},
        )
        assert ok.status_code == 200
        body = ok.json()
        assert body["job_id"]
        assert body["entries"][0]["tos_uri"].startswith("tos://test-short-drama/uploads/")
        assert "X-Amz-Signature" in body["entries"][0]["presigned_url"]


@pytest.mark.asyncio
async def test_video_job_completes_via_mocked_las_and_tos(tmp_path, monkeypatch):
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()

    sample_script = "1-1 夜 内 客厅\n人物：A，B\n△ 镜头给到 A。\nA：你好。\nB：你也好。\n"

    class FakeSubmit:
        def __init__(self, task_id):
            self.task_id = task_id
            self.raw = {"metadata": {"task_id": task_id, "task_status": "PENDING"}}

    class FakePoll:
        def __init__(self, status, error=None):
            self.task_status = status
            self.business_code = "0"
            self.error_msg = error
            self.data = {}
            self.raw = {}

    poll_calls = {"n": 0}

    async def fake_submit(self, **kwargs):
        return FakeSubmit("task-mock-1")

    async def fake_poll(self, task_id):
        poll_calls["n"] += 1
        if poll_calls["n"] >= 2:
            return FakePoll("COMPLETED")
        return FakePoll("RUNNING")

    monkeypatch.setattr("app.services.video_script_runner.LASClient.submit", fake_submit)
    monkeypatch.setattr("app.services.video_script_runner.LASClient.poll", fake_poll)

    def fake_list_objects(self, prefix):
        return [{"Key": f"{prefix.rstrip('/')}/script.md", "Size": 1234}]

    def fake_download(self, key):
        return sample_script.encode("utf-8")

    monkeypatch.setattr("app.services.video_script_runner.TOSClient.list_objects", fake_list_objects)
    monkeypatch.setattr("app.services.video_script_runner.TOSClient.download_object", fake_download)
    monkeypatch.setattr(
        "app.services.video_script_runner.LASClient.__init__",
        lambda self, settings: setattr(self, "_settings", settings) or None,
    )

    # 缩短轮询间隔，避免测试卡顿
    import app.services.video_script_runner as runner_mod

    async def _fast_sleep(_):
        return None

    monkeypatch.setattr(runner_mod.asyncio, "sleep", _fast_sleep)

    headers = {"X-Access-Passphrase": "test-pass"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        upload_resp = await client.post(
            "/api/video-jobs/upload-url",
            json={"files": [{"filename": "ep1.mp4", "content_type": "video/mp4"}]},
            headers=headers,
        )
        upload = upload_resp.json()
        job_id = upload["job_id"]
        tos_uri = upload["entries"][0]["tos_uri"]

        create_resp = await client.post(
            "/api/video-jobs",
            json={
                "job_id": job_id,
                "title": "Mock 短剧",
                "video_urls": [tos_uri],
                "original_filenames": ["ep1.mp4"],
                "prompt_template_id": "default-las",
            },
            headers=headers,
        )
        assert create_resp.status_code == 201

        # 等待 background task 完成
        for _ in range(50):
            detail = await client.get(f"/api/video-jobs/{job_id}")
            if detail.json()["status"] in ("completed", "failed"):
                break
            import asyncio
            await asyncio.sleep(0.05)

        body = detail.json()
        assert body["status"] == "completed", body
        assert body["generated_script_id"]
        assert body["prompt_template_name"]

        history = await client.get("/api/video-jobs")
        assert history.status_code == 200
        assert any(j["id"] == job_id for j in history.json())


@pytest.mark.asyncio
async def test_video_job_marks_failed_on_las_error(tmp_path, monkeypatch):
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()

    class FakeSubmit:
        def __init__(self, task_id):
            self.task_id = task_id
            self.raw = {"metadata": {"task_id": task_id, "task_status": "PENDING"}}

    class FakePoll:
        def __init__(self):
            self.task_status = "FAILED"
            self.business_code = "ApiKey.InValid"
            self.error_msg = "boom"
            self.data = None
            self.raw = {}

    async def fake_submit(self, **kwargs):
        return FakeSubmit("task-mock-2")

    async def fake_poll(self, task_id):
        return FakePoll()

    monkeypatch.setattr("app.services.video_script_runner.LASClient.submit", fake_submit)
    monkeypatch.setattr("app.services.video_script_runner.LASClient.poll", fake_poll)
    monkeypatch.setattr(
        "app.services.video_script_runner.LASClient.__init__",
        lambda self, settings: setattr(self, "_settings", settings) or None,
    )

    import app.services.video_script_runner as runner_mod

    async def _fast_sleep(_):
        return None

    monkeypatch.setattr(runner_mod.asyncio, "sleep", _fast_sleep)

    headers = {"X-Access-Passphrase": "test-pass"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        upload = (
            await client.post(
                "/api/video-jobs/upload-url",
                json={"files": [{"filename": "x.mp4", "content_type": "video/mp4"}]},
                headers=headers,
            )
        ).json()
        await client.post(
            "/api/video-jobs",
            json={
                "job_id": upload["job_id"],
                "title": "Fail",
                "video_urls": [upload["entries"][0]["tos_uri"]],
                "prompt_template_id": "default-las",
            },
            headers=headers,
        )
        for _ in range(50):
            detail = await client.get(f"/api/video-jobs/{upload['job_id']}")
            if detail.json()["status"] in ("completed", "failed"):
                break
            import asyncio
            await asyncio.sleep(0.05)
        body = detail.json()
        assert body["status"] == "failed"
        assert body["error_message"]


@pytest.mark.asyncio
async def test_video_job_marks_failed_on_las_business_failure(tmp_path, monkeypatch):
    """LAS metadata.task_status=COMPLETED but data.status=failed -> job failed with failed_video_urls."""

    base_env(monkeypatch, tmp_path)
    app = load_create_app()()

    class FakeSubmit:
        def __init__(self, task_id):
            self.task_id = task_id
            self.raw = {"metadata": {"task_id": task_id, "task_status": "PENDING"}}

    class FakePoll:
        def __init__(self, status, data=None):
            self.task_status = status
            self.business_code = "0"
            self.error_msg = "Task processed successfully"
            self.data = data
            self.raw = {"metadata": {"task_status": status}, "data": data or {}}

    poll_calls = {"n": 0}

    async def fake_submit(self, **kwargs):
        return FakeSubmit("task-biz-fail-1")

    async def fake_poll(self, task_id):
        poll_calls["n"] += 1
        if poll_calls["n"] >= 2:
            return FakePoll(
                "COMPLETED",
                data={
                    "status": "failed",
                    "failed_video_urls": [
                        "tos://test-short-drama/uploads/x/y.mp4"
                    ],
                    "generated_script_count": 0,
                    "input_episode_count": 1,
                },
            )
        return FakePoll("RUNNING")

    monkeypatch.setattr("app.services.video_script_runner.LASClient.submit", fake_submit)
    monkeypatch.setattr("app.services.video_script_runner.LASClient.poll", fake_poll)
    monkeypatch.setattr(
        "app.services.video_script_runner.LASClient.__init__",
        lambda self, settings: setattr(self, "_settings", settings) or None,
    )

    import app.services.video_script_runner as runner_mod

    async def _fast_sleep(_):
        return None

    monkeypatch.setattr(runner_mod.asyncio, "sleep", _fast_sleep)

    headers = {"X-Access-Passphrase": "test-pass"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        upload = (
            await client.post(
                "/api/video-jobs/upload-url",
                json={"files": [{"filename": "a.mp4", "content_type": "video/mp4"}]},
                headers=headers,
            )
        ).json()
        await client.post(
            "/api/video-jobs",
            json={
                "job_id": upload["job_id"],
                "title": "BizFail",
                "video_urls": [upload["entries"][0]["tos_uri"]],
                "prompt_template_id": "default-las",
            },
            headers=headers,
        )
        for _ in range(50):
            detail = await client.get(f"/api/video-jobs/{upload['job_id']}")
            if detail.json()["status"] in ("completed", "failed"):
                break
            import asyncio
            await asyncio.sleep(0.05)
        body = detail.json()
        assert body["status"] == "failed"
        assert "LAS 业务失败" in body["error_message"]
        assert "tos://test-short-drama/uploads/x/y.mp4" in body["error_message"]
    """Re-running create_app must keep existing scripts/cleaned rows untouched and seed prompt only once."""
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()

    # 第一次：列出 prompt + 创建一个自定义 prompt
    headers = {"X-Access-Passphrase": "test-pass"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        before = await client.get("/api/prompt-templates")
        before_count = len(before.json())
        await client.post(
            "/api/prompt-templates",
            json={"name": "k", "content": "v"},
            headers=headers,
        )

    # 第二次创建 app（会再跑一次迁移 + seed）
    app2 = load_create_app()()
    async with AsyncClient(transport=ASGITransport(app=app2), base_url="http://t") as client:
        after = await client.get("/api/prompt-templates")
        after_items = after.json()
        # 默认行只有一条；自定义那条仍然存在
        defaults = [it for it in after_items if it["is_default"]]
        assert len(defaults) == 1
        assert any(it["name"] == "k" for it in after_items)
        assert len(after_items) == before_count + 1
