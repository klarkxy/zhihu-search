"""知乎 OAuth helper contract tests."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from zhihu_search.oauth import (
    OAUTH_ACCESS_TOKEN_URL,
    OAUTH_AUTHORIZE_URL,
    build_authorize_url,
    exchange_access_token,
)
from zhihu_search.upstream.base import (
    InvalidArguments,
    RateLimited,
    UpstreamTimeout,
    UpstreamUnavailable,
)


def test_build_authorize_url_uses_only_documented_parameters() -> None:
    redirect_uri = "https://client.example/callback?source=知乎 登录"
    url = build_authorize_url("app 123", redirect_uri)
    parsed = urlparse(url)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == OAUTH_AUTHORIZE_URL
    assert parse_qs(parsed.query) == {
        "redirect_uri": [redirect_uri],
        "app_id": ["app 123"],
        "response_type": ["code"],
    }
    assert "state" not in parsed.query
    assert "scope" not in parsed.query


@pytest.mark.parametrize(
    ("app_id", "redirect_uri"),
    [
        ("", "https://client.example/callback"),
        ("app-id", ""),
    ],
)
def test_build_authorize_url_rejects_missing_required_values(
    app_id: str, redirect_uri: str
) -> None:
    with pytest.raises(InvalidArguments):
        build_authorize_url(app_id, redirect_uri)


@pytest.mark.asyncio
async def test_exchange_access_token_form_post_and_plain_dict() -> None:
    payload = {
        "access_token": "oauth-access-token",
        "token_type": "Bearer",
        "expires_in": 3600,
    }
    with respx.mock(assert_all_called=True) as router:
        route = router.post(OAUTH_ACCESS_TOKEN_URL).mock(
            return_value=httpx.Response(200, json=payload)
        )
        async with httpx.AsyncClient() as client:
            result = await exchange_access_token(
                "app-id",
                "app-key",
                "https://client.example/callback?source=zhihu",
                "authorization-code",
                client=client,
            )
            assert not client.is_closed

    request = route.calls.last.request
    assert request.method == "POST"
    assert request.headers["Content-Type"].startswith(
        "application/x-www-form-urlencoded"
    )
    assert parse_qs(request.content.decode()) == {
        "app_id": ["app-id"],
        "app_key": ["app-key"],
        "grant_type": ["authorization_code"],
        "redirect_uri": [
            "https://client.example/callback?source=zhihu"
        ],
        "code": ["authorization-code"],
    }
    assert result == payload
    assert type(result) is dict


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing_value",
    ["app_id", "app_key", "redirect_uri", "code"],
)
async def test_exchange_access_token_rejects_missing_required_value(
    missing_value: str
) -> None:
    values = {
        "app_id": "app-id",
        "app_key": "app-key",
        "redirect_uri": "https://client.example/callback",
        "code": "authorization-code",
    }
    values[missing_value] = ""
    with pytest.raises(InvalidArguments, match=missing_value):
        await exchange_access_token(**values)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"token_type": "Bearer", "expires_in": 3600},
        {"access_token": "token", "expires_in": 3600},
        {
            "access_token": "token",
            "token_type": "Bearer",
        },
        {
            "access_token": "token",
            "token_type": "Bearer",
            "expires_in": "3600",
        },
    ],
)
async def test_exchange_access_token_validates_required_response_fields(
    payload
) -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(OAUTH_ACCESS_TOKEN_URL).mock(
            return_value=httpx.Response(200, json=payload)
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(UpstreamUnavailable):
                await exchange_access_token(
                    "app-id",
                    "app-key",
                    "https://client.example/callback",
                    "authorization-code",
                    client=client,
                )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (400, InvalidArguments),
        (401, InvalidArguments),
        (429, RateLimited),
        (500, UpstreamUnavailable),
    ],
)
async def test_exchange_access_token_maps_http_failures(
    status: int, error_type: type[Exception]
) -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(OAUTH_ACCESS_TOKEN_URL).mock(
            return_value=httpx.Response(
                status,
                json={"error_description": "invalid authorization code"},
                headers={"Retry-After": "2.5"},
            )
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(error_type) as exc_info:
                await exchange_access_token(
                    "app-id",
                    "app-key",
                    "https://client.example/callback",
                    "authorization-code",
                    client=client,
                )

    if status == 429:
        assert exc_info.value.retry_after == 2.5


@pytest.mark.asyncio
async def test_exchange_access_token_maps_timeout() -> None:
    async def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    transport = httpx.MockTransport(timeout_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(UpstreamTimeout):
            await exchange_access_token(
                "app-id",
                "app-key",
                "https://client.example/callback",
                "authorization-code",
                client=client,
            )


@pytest.mark.asyncio
async def test_exchange_access_token_rejects_non_json_success() -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(OAUTH_ACCESS_TOKEN_URL).mock(
            return_value=httpx.Response(200, text="<html>bad gateway</html>")
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(UpstreamUnavailable, match="非 JSON"):
                await exchange_access_token(
                    "app-id",
                    "app-key",
                    "https://client.example/callback",
                    "authorization-code",
                    client=client,
                )
