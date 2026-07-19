import asyncio
import random

import httpx
import pytest

from app.config import Settings
import app.services.baidu_vod_client as vod_client_module
from app.services.baidu_vod_client import BaiduVodApiError, BaiduVodClient


class StubGovernor:
    def __init__(self):
        self.acquisitions = 0

    async def acquire_request(self) -> None:
        self.acquisitions += 1


def client_settings() -> Settings:
    return Settings(
        _env_file=None,
        BAIDU_ACCESS_KEY_ID="test-ak",
        BAIDU_ACCESS_KEY_SECRET="test-sk",
    )


def install_transport(monkeypatch, handler) -> None:
    real_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def factory(**kwargs):
        return real_async_client(transport=transport, **kwargs)

    monkeypatch.setattr(
        "app.services.baidu_vod_client.httpx.AsyncClient",
        factory,
    )


def capture_retry_delays(monkeypatch) -> list[float]:
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(random, "uniform", lambda _start, _end: 0.0)
    return delays


@pytest.mark.asyncio
async def test_request_acquires_global_qps_token(monkeypatch):
    governor = StubGovernor()
    install_transport(
        monkeypatch,
        lambda _request: httpx.Response(200, json={"ok": True}),
    )
    client = BaiduVodClient(client_settings(), governor=governor)

    result = await client._request("GET", "/test")

    assert result == {"ok": True}
    assert governor.acquisitions == 1


@pytest.mark.asyncio
async def test_post_retries_429_and_counts_each_attempt_against_qps(monkeypatch):
    governor = StubGovernor()
    attempts = 0

    def handler(_request):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(429, json={"message": "slow down"})
        return httpx.Response(200, json={"ok": True})

    install_transport(monkeypatch, handler)
    delays = capture_retry_delays(monkeypatch)
    client = BaiduVodClient(client_settings(), governor=governor)

    assert await client._request("POST", "/test", body={"x": 1}) == {"ok": True}
    assert attempts == 3
    assert governor.acquisitions == 3
    assert delays == [1.0, 2.0]


@pytest.mark.asyncio
async def test_retry_after_header_overrides_backoff_and_is_capped(monkeypatch):
    attempts = 0

    def handler(_request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "45"})
        return httpx.Response(200, json={"ok": True})

    install_transport(monkeypatch, handler)
    delays = capture_retry_delays(monkeypatch)
    client = BaiduVodClient(client_settings(), governor=StubGovernor())

    await client._request("GET", "/test")

    assert delays == [30.0]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_kind", ["response", "network"])
async def test_get_retries_transient_failures(monkeypatch, failure_kind):
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            if failure_kind == "network":
                raise httpx.ConnectError("temporary", request=request)
            return httpx.Response(503, json={"message": "temporary"})
        return httpx.Response(200, json={"ok": True})

    install_transport(monkeypatch, handler)
    capture_retry_delays(monkeypatch)
    client = BaiduVodClient(client_settings(), governor=StubGovernor())

    assert await client._request("GET", "/test") == {"ok": True}
    assert attempts == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_kind", ["response", "network"])
async def test_post_does_not_retry_ambiguous_transient_failures(
    monkeypatch, failure_kind
):
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        if failure_kind == "network":
            raise httpx.ConnectError("ambiguous", request=request)
        return httpx.Response(503, json={"message": "ambiguous"})

    install_transport(monkeypatch, handler)
    capture_retry_delays(monkeypatch)
    client = BaiduVodClient(client_settings(), governor=StubGovernor())

    with pytest.raises(vod_client_module.BaiduVodApiError) as exc_info:
        await client._request("POST", "/test", body={"x": 1})

    assert attempts == 1
    assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_get_exhausts_four_attempts_and_raises_retryable_error(monkeypatch):
    attempts = 0

    def handler(_request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, json={"message": "still unavailable"})

    install_transport(monkeypatch, handler)
    delays = capture_retry_delays(monkeypatch)
    client = BaiduVodClient(client_settings(), governor=StubGovernor())

    with pytest.raises(vod_client_module.BaiduVodApiError) as exc_info:
        await client._request("GET", "/test")

    assert attempts == 4
    assert delays == [1.0, 2.0, 4.0]
    assert exc_info.value.status_code == 503
    assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_non_retryable_4xx_fails_once(monkeypatch):
    attempts = 0

    def handler(_request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(403, json={"message": "denied"})

    install_transport(monkeypatch, handler)
    capture_retry_delays(monkeypatch)
    client = BaiduVodClient(client_settings(), governor=StubGovernor())

    with pytest.raises(vod_client_module.BaiduVodApiError) as exc_info:
        await client._request("GET", "/test")

    assert attempts == 1
    assert exc_info.value.status_code == 403
    assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_fetch_poll_continues_after_exhausted_retryable_error(monkeypatch):
    client = BaiduVodClient(client_settings(), governor=StubGovernor())
    retryable_error = BaiduVodApiError(
        method="GET",
        path="/v2/tasks/fetch-1",
        status_code=503,
        detail="temporary",
        retryable=True,
    )
    results = iter(
        [
            retryable_error,
            {
                "status": "SUCCESS",
                "mediaFetchTaskInfo": {"mediaBasicInfo": {"mediaId": "media-1"}},
            },
        ]
    )

    async def fake_query(_task_id):
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(client, "query_fetch_task", fake_query)
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    assert await client.wait_for_fetch_media("fetch-1") == "media-1"


@pytest.mark.asyncio
async def test_translation_poll_fails_immediately_on_non_retryable_api_error(
    monkeypatch,
):
    client = BaiduVodClient(client_settings(), governor=StubGovernor())
    denied = BaiduVodApiError(
        method="GET",
        path="/v2/translation/project/p/tasks",
        status_code=403,
        detail="denied",
        retryable=False,
    )

    async def fake_query(*_args, **_kwargs):
        raise denied

    async def forbidden_sleep(_delay):
        raise AssertionError("non-retryable errors must not keep polling")

    monkeypatch.setattr(client, "query_tasks", fake_query)
    monkeypatch.setattr(asyncio, "sleep", forbidden_sleep)

    with pytest.raises(BaiduVodApiError) as exc_info:
        await client.wait_for_task("project-1", "task-1")

    assert exc_info.value is denied
