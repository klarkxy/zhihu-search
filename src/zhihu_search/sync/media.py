"""知乎图片上传：申请上传、阿里云 OSS 直传、提交、水印轮询。

协议来自知乎媒体上传说明（zhihu-mediacloud-uploader，随 ZhihuSync 一并引用）。
只接受 JPEG、PNG、GIF、WebP、BMP。视频直接拒绝。临时 STS 不进入返回值。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass
from email.utils import formatdate
from urllib.parse import quote, urlsplit

import httpx

from .api import SyncApiError, sync_request
from .content import VIDEO_UNSUPPORTED

SIZE_LIMIT_GIF = 15 * 1024 * 1024
SIZE_LIMIT_OTHER = 30 * 1024 * 1024
MAX_LONG_SIDE = 4 * 4096
MAX_PIXELS = 200_000_000
_OSS_HOST = re.compile(r"^(?:[a-z0-9-]+\.)*aliyuncs\.com$", re.IGNORECASE)
_OSS_BUCKET = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
_IMAGE_HOST = re.compile(r"^(?:[a-z0-9-]+\.)*(?:zhimg\.com|zhihu\.com)$", re.IGNORECASE)
_OSS_EXPIRED = {"InvalidAccessKeyId", "SecurityTokenExpired", "AccessDenied", "InvalidSecurityToken"}
_VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}


class SyncMediaError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class _ImageMeta:
    extension: str
    content_type: str
    width: int
    height: int
    gif: bool


async def upload_image(
    *,
    file_name: str,
    content: bytes,
    scene: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, object]:
    if scene not in {"article", "question", "pin"}:
        raise SyncMediaError("INVALID_INPUT", "scene 必须是 article、question 或 pin。")
    safe_name = file_name.replace("\\", "/").split("/")[-1].strip()
    if not safe_name or any(ord(ch) < 32 or ord(ch) == 127 for ch in safe_name):
        raise SyncMediaError("INVALID_INPUT", "文件名不能为空，也不能含控制字符。")
    suffix = "." + safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    if suffix in _VIDEO_EXT:
        raise SyncMediaError("UNSUPPORTED_TYPE", VIDEO_UNSUPPORTED)
    meta = _sniff(content)
    _validate(meta, len(content))
    md5_hex = hashlib.md5(content).hexdigest()
    md5_b64 = base64.b64encode(hashlib.md5(content).digest()).decode("ascii")
    owns = client is None
    http = client or httpx.AsyncClient(timeout=30.0, follow_redirects=False)
    secrets: list[str] = []
    try:
        headers = {
            "X-Media-Scene-Name": scene,
            "X-Media-Upload-Platform": "web",
            "X-Upload-Content-Type": meta.content_type,
            "X-Upload-Content-Hash": md5_hex,
        }
        apply_body = {
            "template_name": "image-upload-default",
            "media_type": "image",
            "file_name": safe_name,
            "file_extension": meta.extension,
            "file_size": len(content),
        }
        applied, _status = await sync_request(
            "POST",
            "/openapi/media/uploads",
            body=apply_body,
            headers=headers,
            client=http,
        )
        apply = _parse_apply(applied)
        _collect_secrets(apply, secrets)
        state = str(apply.get("upload_state") or "")
        if state == "UPLOAD_SUCCESS":
            extra = apply.get("extra_params") if isinstance(apply.get("extra_params"), dict) else {}
            media_url = _public_url(extra.get("url") if isinstance(extra, dict) else None)
            width = _positive(extra.get("width")) or meta.width
            height = _positive(extra.get("height")) or meta.height
        elif state == "UPLOADING":
            media_url, width, height = await _upload_oss(
                http, apply, content, meta, md5_b64, headers, scene, secrets
            )
        else:
            raise SyncMediaError("API_ERROR", f"申请上传返回 {state or '空状态'}。")
        if not media_url:
            raise SyncMediaError("BAD_RESPONSE", "上传成功但没有可公开的知乎图片 URL。")
        original_key = f"v2-{md5_hex}"
        watermark = await _poll_watermark(http, str(apply.get("session_key") or ""), scene, original_key)
        if watermark:
            return {
                "kind": "image",
                "url": watermark["url"],
                "original_url": media_url,
                "media_id": watermark["token"],
                "width": width,
                "height": height,
                "watermark": True,
            }
        return {
            "kind": "image",
            "url": media_url,
            "media_id": original_key,
            "width": width,
            "height": height,
            "watermark": False,
            "warnings": ["水印处理未完成，已使用未加水印的原图 URL。"],
        }
    except SyncMediaError as exc:
        raise SyncMediaError(exc.code, _redact(str(exc), secrets)) from None
    except SyncApiError as exc:
        raise SyncMediaError(exc.code, _redact(str(exc), secrets)) from None
    finally:
        if owns:
            await http.aclose()


async def _upload_oss(
    http: httpx.AsyncClient,
    apply: dict[str, object],
    content: bytes,
    meta: _ImageMeta,
    md5_b64: str,
    headers: dict[str, str],
    scene: str,
    secrets: list[str],
) -> tuple[str, int, int]:
    if apply.get("vendor_code") != "ali":
        raise SyncMediaError("UNSUPPORTED_VENDOR", "当前只支持阿里云 OSS 直传。")
    ok, code, status = await _put_oss(http, apply, content, meta.content_type, md5_b64)
    if not ok and code in _OSS_EXPIRED:
        refreshed, _status = await sync_request(
            "POST",
            "/openapi/media/uploads",
            body={"template_name": "image-upload-default", "media_type": "image", "session_key": apply.get("session_key")},
            headers=headers,
            client=http,
        )
        apply = _parse_apply(refreshed)
        _collect_secrets(apply, secrets)
        ok, code, status = await _put_oss(http, apply, content, meta.content_type, md5_b64)
    error_log = "" if ok else f"OSS PutObject HTTP {status} code={code}".strip()
    commit_body: dict[str, object] = {
        "media_type": "image",
        "client_upload_state": "UPLOAD_SUCCESS" if ok else "UPLOAD_FAIL",
    }
    if error_log:
        commit_body["error_log"] = error_log
    if apply.get("processes"):
        commit_body["processes"] = apply["processes"]
    commit_url = str(apply.get("commit_address") or f"/openapi/media/uploads/{apply.get('session_key')}")
    auth = apply.get("auth") if isinstance(apply.get("auth"), dict) else {}
    committed, _status = await sync_request(
        "PATCH",
        commit_url,
        body=commit_body,
        headers={
            "X-Media-Scene-Name": scene,
            "X-Media-Upload-Platform": "web",
            "X-Security-Token": str(auth.get("security_token") or ""),
        },
        client=http,
    )
    if not ok:
        raise SyncMediaError("OSS_ERROR", f"云端直传失败：{error_log}")
    if not isinstance(committed, dict) or committed.get("upload_results") != "UPLOAD_SUCCESS":
        raise SyncMediaError("API_ERROR", "提交上传未成功。")
    meta_row = committed.get("media_meta") if isinstance(committed.get("media_meta"), dict) else {}
    return (
        _public_url(committed.get("media_url")),
        _positive(meta_row.get("width")) or meta.width,
        _positive(meta_row.get("height")) or meta.height,
    )


async def _put_oss(
    http: httpx.AsyncClient,
    apply: dict[str, object],
    content: bytes,
    content_type: str,
    md5_b64: str,
) -> tuple[bool, str, int]:
    auth = apply.get("auth") if isinstance(apply.get("auth"), dict) else {}
    address = apply.get("address") if isinstance(apply.get("address"), dict) else {}
    if not auth or not address:
        raise SyncMediaError("BAD_RESPONSE", "申请上传缺少 OSS 凭证或地址。")
    host = _oss_host(str(address.get("endpoint") or ""))
    bucket = str(address.get("bucket_name") or "")
    if not _OSS_BUCKET.match(bucket):
        raise SyncMediaError("BAD_RESPONSE", "OSS bucket 名称不合法。")
    object_name = str(address.get("object_name") or "")
    encoded = "/".join(quote(part, safe="") for part in object_name.split("/"))
    request_host = host if address.get("is_cname") is True else f"{bucket}.{host}"
    url = f"https://{request_host}/{encoded}"
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != request_host or parts.username:
        raise SyncMediaError("OSS_ERROR", "OSS 目标地址不合法。")
    date = formatdate(usegmt=True)
    canonical = f"x-oss-security-token:{auth.get('security_token')}\n/{bucket}/{encoded}"
    to_sign = f"PUT\n{md5_b64}\n{content_type}\n{date}\n{canonical}"
    signature = base64.b64encode(
        hmac.new(str(auth.get("secret_access_key") or "").encode(), to_sign.encode(), hashlib.sha1).digest()
    ).decode("ascii")
    try:
        response = await http.put(
            url,
            content=content,
            headers={
                "Date": date,
                "Content-Type": content_type,
                "Content-MD5": md5_b64,
                "x-oss-security-token": str(auth.get("security_token") or ""),
                "Authorization": f"OSS {auth.get('access_key_id')}:{signature}",
            },
        )
    except httpx.HTTPError as exc:
        raise SyncMediaError("OSS_ERROR", "云端直传失败。") from exc
    if 200 <= response.status_code < 300:
        return True, "", response.status_code
    match = re.search(r"<Code>([^<]+)</Code>", response.text or "", re.IGNORECASE)
    return False, match.group(1).strip() if match else "", response.status_code


async def _poll_watermark(
    http: httpx.AsyncClient,
    image_id: str,
    scene: str,
    original_key: str,
) -> dict[str, str] | None:
    if not image_id:
        return None
    try:
        payload, status = await sync_request(
            "GET",
            f"/openapi/media/images/{quote(image_id, safe='')}/watermark",
            headers={"X-Media-Scene-Name": scene},
            client=http,
        )
    except Exception as exc:
        status = getattr(exc, "http_status", None)
        if isinstance(status, int) and 400 <= status < 500:
            return None
        return None
    if status >= 400 or not isinstance(payload, dict):
        return None
    if payload.get("state") != "success":
        return None
    token = str(payload.get("watermark_image_token") or "")
    url = _public_url(payload.get("watermark_image_url"))
    if url and token and token != original_key:
        return {"token": token, "url": url}
    return None


def _parse_apply(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise SyncMediaError("BAD_RESPONSE", "申请上传的响应不是对象。")
    config = payload.get("upload_config") if isinstance(payload.get("upload_config"), dict) else {}
    media = payload.get("upload_media") if isinstance(payload.get("upload_media"), dict) else {}
    auth = payload.get("upload_auth") if isinstance(payload.get("upload_auth"), dict) else None
    address = config.get("address") if isinstance(config.get("address"), dict) else None
    return {
        "upload_state": payload.get("upload_state") or "",
        "session_key": payload.get("session_key") or "",
        "vendor_code": config.get("vendor_code") or "",
        "commit_address": media.get("commit_address") or "",
        "processes": media.get("processes") or "",
        "extra_params": payload.get("extra_params") if isinstance(payload.get("extra_params"), dict) else {},
        "auth": auth,
        "address": address,
    }


def _collect_secrets(apply: dict[str, object], secrets: list[str]) -> None:
    auth = apply.get("auth")
    if not isinstance(auth, dict):
        return
    for key in ("access_key_id", "secret_access_key", "security_token"):
        value = auth.get(key)
        if isinstance(value, str) and len(value) >= 4:
            secrets.append(value)


def _public_url(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    candidates = [value.get("primary")]
    backups = value.get("backups")
    if isinstance(backups, list):
        candidates.extend(backups)
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate:
            continue
        parts = urlsplit(candidate)
        if (
            parts.scheme == "https"
            and not parts.username
            and parts.hostname
            and _IMAGE_HOST.match(parts.hostname)
        ):
            return candidate
    return ""


def _oss_host(endpoint: str) -> str:
    text = endpoint.strip()
    if text.lower().startswith("http://"):
        raise SyncMediaError("OSS_ERROR", "OSS endpoint 必须使用 HTTPS。")
    host = re.sub(r"^https://", "", text, flags=re.IGNORECASE).strip("/").lower()
    if not _OSS_HOST.match(host):
        raise SyncMediaError("OSS_ERROR", "OSS endpoint 必须是 aliyuncs.com 主机名。")
    return host


def _sniff(buf: bytes) -> _ImageMeta:
    def bad() -> SyncMediaError:
        return SyncMediaError("UNSUPPORTED_TYPE", "只支持 JPEG、PNG、GIF、WebP、BMP。")

    if len(buf) < 12:
        raise bad()
    if buf[4:8] == b"ftyp":
        brand = buf[8:12].decode("ascii", "ignore").lower()
        if brand in {"heic", "heix", "hevc", "hevx", "mif1", "msf1", "avif", "avis"}:
            raise SyncMediaError("NEEDS_TRANSCODE", "暂不支持 HEIC/AVIF，请先转为 JPEG、PNG 或 WebP。")
        raise bad()
    if buf.startswith(b"\x89PNG\r\n\x1a\n") and len(buf) >= 24:
        width = int.from_bytes(buf[16:20], "big")
        height = int.from_bytes(buf[20:24], "big")
        if width and height:
            return _ImageMeta(".png", "image/png", width, height, False)
    if buf.startswith(b"GIF8") and len(buf) >= 10:
        width = buf[6] | (buf[7] << 8)
        height = buf[8] | (buf[9] << 8)
        if width and height:
            return _ImageMeta(".gif", "image/gif", width, height, True)
    if buf.startswith(b"BM") and len(buf) >= 26:
        width = abs(int.from_bytes(buf[18:22], "little", signed=True))
        height = abs(int.from_bytes(buf[22:26], "little", signed=True))
        if width and height:
            return _ImageMeta(".bmp", "image/bmp", width, height, False)
    if buf.startswith(b"RIFF") and buf[8:12] == b"WEBP" and len(buf) >= 30:
        four = buf[12:16]
        if four == b"VP8X":
            width = (buf[24] | (buf[25] << 8) | (buf[26] << 16)) + 1
            height = (buf[27] | (buf[28] << 8) | (buf[29] << 16)) + 1
            return _ImageMeta(".webp", "image/webp", width, height, False)
        if four == b"VP8 ":
            width = (buf[26] | (buf[27] << 8)) & 0x3FFF
            height = (buf[28] | (buf[29] << 8)) & 0x3FFF
            if width and height:
                return _ImageMeta(".webp", "image/webp", width, height, False)
    if buf.startswith(b"\xff\xd8"):
        offset = 2
        while offset + 9 < len(buf):
            if buf[offset] != 0xFF:
                offset += 1
                continue
            marker = buf[offset + 1]
            while marker == 0xFF and offset + 2 < len(buf):
                offset += 1
                marker = buf[offset + 1]
            if marker in {0xD8, 0xD9, 0x01} or 0xD0 <= marker <= 0xD7:
                offset += 2
                continue
            if offset + 3 >= len(buf):
                break
            length = (buf[offset + 2] << 8) | buf[offset + 3]
            if length < 2:
                break
            if 0xC0 <= marker <= 0xCF and marker not in {0xC4, 0xC8, 0xCC} and offset + 8 < len(buf):
                height = (buf[offset + 5] << 8) | buf[offset + 6]
                width = (buf[offset + 7] << 8) | buf[offset + 8]
                if width and height:
                    return _ImageMeta(".jpg", "image/jpeg", width, height, False)
            offset += 2 + length
    raise bad()


def _validate(meta: _ImageMeta, size: int) -> None:
    limit = SIZE_LIMIT_GIF if meta.gif else SIZE_LIMIT_OTHER
    if size > limit:
        raise SyncMediaError("LIMIT_EXCEEDED", f"图片超过 {limit // 1024 // 1024} MB 上限。")
    if max(meta.width, meta.height) > MAX_LONG_SIDE or meta.width * meta.height > MAX_PIXELS:
        raise SyncMediaError("LIMIT_EXCEEDED", "图片尺寸超过上限。")


def _positive(value: object) -> int:
    return value if isinstance(value, int) and value > 0 else 0


def _redact(message: str, secrets: list[str]) -> str:
    text = message
    for secret in secrets:
        text = text.replace(secret, "[REDACTED]")
    return text
