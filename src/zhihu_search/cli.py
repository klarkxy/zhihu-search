"""命令行入口。

用法：
    zhihu-search [flags...] [command [args...]]

Flags:
    --version, --check-token, --save-token <s>, --clear-token,
    --quota, --reset-quota, --probe

Commands (默认: serve):
    serve              启动可配置工具目录的 stdio MCP 服务器
    openwebui          启动 OpenAPI 工具服务器
    search <query>     搜索知乎内容
    ask <query>        向知乎直答提问
    trending           查看知乎热榜
    user-*             查询用户公开内容、关注与收藏
    pdf-* / ppt-*      上传文件、创建任务、查询任务状态
    oauth-*            生成授权 URL、交换 OAuth access token

使用 ``zhihu-search <command> --help`` 查看子命令详细参数。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from . import __version__, commands, credentials, formatters
from .quota import QuotaSnapshot, QuotaTracker


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="zhihu-search",
        description=(
            "知乎开放平台的统一 CLI + MCP 封装。"
            "默认启动 stdio MCP 服务器；也可通过子命令直接搜索、提问、查看热榜。"
        ),
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"zhihu-search {__version__}",
    )
    p.add_argument(
        "--check-token",
        action="store_true",
        help="打印凭证来源并退出。",
    )
    p.add_argument(
        "--save-token",
        metavar="SECRET",
        help="保存 Access Secret 到默认凭证文件并退出。",
    )
    p.add_argument(
        "--clear-token",
        action="store_true",
        help="删除凭证文件并退出。",
    )
    p.add_argument(
        "--quota",
        action="store_true",
        help="打印今日配额用量并退出。",
    )
    p.add_argument(
        "--reset-quota",
        action="store_true",
        help="把今日计数清零并退出。",
    )
    p.add_argument(
        "--probe",
        action="store_true",
        help="调用 hot_list(limit=1) 一次，打印响应。用于端到端验证。",
    )

    # 子命令
    sub = p.add_subparsers(
        dest="command",
        metavar="{search,ask,trending,user-*,pdf-*,ppt-*,oauth-*,serve,openwebui}",
    )

    # --- serve（显式入口）---
    serve = sub.add_parser("serve", help="启动 stdio MCP 服务器（默认）。")
    serve.add_argument(
        "--tools",
        metavar="PROFILE_OR_LIST",
        default=None,
        help=(
            "工具开关：compact（默认）、full，或逗号分隔的工具名；"
            "也可设置 ZHIHU_MCP_TOOLS。"
        ),
    )

    # --- openwebui ---
    ow = sub.add_parser("openwebui", help="启动 Open WebUI OpenAPI 工具服务器。")
    ow.add_argument("--host", default="127.0.0.1", help="监听地址。")
    ow.add_argument("--port", type=int, default=8000, help="监听端口。")
    ow.add_argument(
        "--api-key",
        default=None,
        help="可选 API key。设置后工具接口要求 Authorization: Bearer <key>。",
    )

    # --- search ---
    sp = sub.add_parser("search", help="搜索知乎内容。")
    sp.add_argument("query", help="搜索关键词，2-100 字符。")
    sp.add_argument(
        "--scope", choices=["zhihu", "web"], default="zhihu",
        help="搜索范围：zhihu（站内）/ web（全网）。",
    )
    sp.add_argument(
        "--count", type=int, default=10,
        help="返回条数（zhihu 上限 10，web 上限 20）。",
    )
    sp.add_argument(
        "--filter", default="",
        help="高级筛选表达式，仅 scope=web 时生效。",
    )
    sp.add_argument(
        "--search-db",
        choices=["all", "realtime", "static"],
        default="all",
        help="全网搜索索引范围，仅 scope=web 时生效。",
    )
    sp.add_argument(
        "--format", choices=["markdown", "json"], default="markdown",
        help="输出格式。",
    )

    # --- ask ---
    ap = sub.add_parser("ask", help="向知乎直答提问。")
    ap.add_argument("query", help="问题内容。")
    ap.add_argument(
        "--model", choices=["fast", "thinking", "agent"], default="fast",
        help="模型档位：fast（快速）/ thinking（深度思考）/ agent（Agent）。",
    )
    ap.add_argument(
        "--format", choices=["markdown", "json"], default="markdown",
        help="输出格式。",
    )

    # --- trending ---
    tp = sub.add_parser("trending", help="查看知乎热榜。")
    tp.add_argument(
        "--limit", type=int, default=30,
        help="返回条数，上限 30。",
    )
    tp.add_argument(
        "--format", choices=["markdown", "json"], default="markdown",
        help="输出格式。",
    )

    # --- 知乎用户数据 ---
    ucp = sub.add_parser("user-contents", help="获取用户公开创作内容。")
    ucp.add_argument(
        "--content-type",
        choices=["all", "answer", "article", "zvideo", "pin", "question"],
        default="all",
        help="内容类型。",
    )
    ucp.add_argument(
        "--offset", default="0",
        help="分页偏移；可直接使用返回的 Paging.NextOffset。",
    )
    ucp.add_argument("--limit", type=int, default=20, help="返回数量，最大 50。")
    ucp.add_argument(
        "--sort-field", choices=["like_count", "ts"], default="ts",
        help="排序字段。",
    )
    ucp.add_argument(
        "--sort-order", choices=["asc", "desc"], default="desc",
        help="排序方向。",
    )
    ucp.add_argument(
        "--oauth-token", default="",
        help=(
            "可选：已授权用户的 OAuth token；优先建议设置"
            " ZHIHU_OAUTH_TOKEN，均留空则查询本人。"
        ),
    )
    ucp.add_argument(
        "--format", choices=["markdown", "json"], default="markdown",
        help="输出格式。",
    )

    ufp = sub.add_parser("user-followees", help="获取用户公开关注列表。")
    ufp.add_argument(
        "--offset", default="0",
        help="分页偏移；可直接使用返回的 Paging.NextOffset。",
    )
    ufp.add_argument("--limit", type=int, default=20, help="返回数量，最大 50。")
    ufp.add_argument(
        "--oauth-token", default="",
        help="可选 OAuth token；也可设置 ZHIHU_OAUTH_TOKEN。",
    )
    ufp.add_argument(
        "--format", choices=["markdown", "json"], default="markdown",
        help="输出格式。",
    )

    ucol = sub.add_parser("user-collections", help="获取用户近期公开收藏。")
    ucol.add_argument("--limit", type=int, default=20, help="返回数量。")
    ucol.add_argument(
        "--oauth-token", default="",
        help="可选 OAuth token；也可设置 ZHIHU_OAUTH_TOKEN。",
    )
    ucol.add_argument(
        "--format", choices=["markdown", "json"], default="markdown",
        help="输出格式。",
    )

    ufl = sub.add_parser("user-favlists", help="获取用户收藏夹列表。")
    ufl.add_argument("--limit", type=int, default=20, help="返回数量。")
    ufl.add_argument(
        "--oauth-token", default="",
        help="可选 OAuth token；也可设置 ZHIHU_OAUTH_TOKEN。",
    )
    ufl.add_argument(
        "--format", choices=["markdown", "json"], default="markdown",
        help="输出格式。",
    )

    flc = sub.add_parser("favlist-contents", help="获取指定收藏夹的公开内容。")
    flc_id = flc.add_mutually_exclusive_group(required=True)
    flc_id.add_argument("--url-token", type=int, help="收藏夹 URL 标识。")
    flc_id.add_argument("--id", type=int, help="收藏夹 ID。")
    flc.add_argument(
        "--offset", default="0",
        help="分页偏移；可直接使用返回的 Paging.NextOffset。",
    )
    flc.add_argument("--limit", type=int, default=20, help="返回数量。")
    flc.add_argument(
        "--oauth-token", default="",
        help="可选 OAuth token；也可设置 ZHIHU_OAUTH_TOKEN。",
    )
    flc.add_argument(
        "--format", choices=["markdown", "json"], default="markdown",
        help="输出格式。",
    )

    # --- PDF / PPT 异步任务 ---
    pdu = sub.add_parser("pdf-upload", help="上传本机 PDF 文件并返回 file_id。")
    pdu.add_argument("file", help="本机 PDF 文件路径（最大 100MB）。")
    pdu.add_argument(
        "--format", choices=["markdown", "json"], default="markdown",
        help="输出格式。",
    )

    pdc = sub.add_parser("pdf-create", help="使用 file_id 创建 PDF 解析任务。")
    pdc.add_argument("file_id", help="pdf-upload 返回的 file_id。")
    pdc.add_argument("--idempotency-key", default="", help="可选幂等键。")
    pdc.add_argument(
        "--format", choices=["markdown", "json"], default="markdown",
        help="输出格式。",
    )

    pds = sub.add_parser("pdf-status", help="查询 PDF 解析任务状态。")
    pds.add_argument("task_id", help="PDF 解析任务 ID。")
    pds.add_argument(
        "--format", choices=["markdown", "json"], default="markdown",
        help="输出格式。",
    )

    ptc = sub.add_parser("ppt-create", help="根据知乎内容创建 PPT 生成任务。")
    ptc.add_argument("resource_url", help="知乎回答或专栏文章链接。")
    ptc.add_argument("--pages", type=int, default=12, help="生成页数，范围 6-21。")
    ptc.add_argument("--idempotency-key", default="", help="可选幂等键。")
    ptc.add_argument(
        "--format", choices=["markdown", "json"], default="markdown",
        help="输出格式。",
    )

    pts = sub.add_parser("ppt-status", help="查询 PPT 生成任务状态。")
    pts.add_argument("task_id", help="PPT 生成任务 ID。")
    pts.add_argument(
        "--format", choices=["markdown", "json"], default="markdown",
        help="输出格式。",
    )

    # --- OAuth（不依赖开放平台 Access Secret）---
    oau = sub.add_parser("oauth-url", help="生成知乎 OAuth 授权 URL。")
    oau.add_argument("app_id", help="知乎 OAuth app_id。")
    oau.add_argument("redirect_uri", help="申请时登记的回调地址。")

    oat = sub.add_parser("oauth-token", help="用 authorization_code 换取 access token。")
    oat.add_argument("app_id", help="知乎 OAuth app_id。")
    oat.add_argument("redirect_uri", help="申请时登记的回调地址。")
    oat.add_argument("code", help="回调参数 authorization_code 的值。")
    oat.add_argument(
        "--app-key",
        default=None,
        help=(
            "OAuth app_key。为避免出现在命令历史中，建议改用"
            " ZHIHU_OAUTH_APP_KEY 环境变量。"
        ),
    )

    return p


# ---------------------------------------------------------------------------
# 凭证与诊断工具（保持不变）
# ---------------------------------------------------------------------------


def _print_credentials_info(creds: credentials.Credentials) -> None:
    # This output is often captured by an Agent or CI log.  The source is
    # enough to diagnose precedence without disclosing any part of the secret
    # or the user-specific credentials path.
    print(f"OK  Access Secret 已配置（来源：{creds.source}）")


async def _probe() -> int:
    """调用一次 hot_list(limit=1) 验证全链路。"""
    creds = credentials.load()
    from .upstream.http_client import ZhihuRestClient

    client = ZhihuRestClient(creds.access_secret)
    try:
        result = await client.hot_list(limit=1)
    finally:
        await client.aclose()
    print(result.quota.to_line())
    items = (result.data or {}).get("Items") or []
    if not items:
        print("(返回为空 items)")
        return 1
    item = items[0]
    print(f"\n第 1 条：{item.get('Title')}\n链接：{item.get('Url')}")
    return 0


def _show_quota() -> int:
    tracker = QuotaTracker()
    snap = tracker.snapshot()
    print(snap.to_line())
    print()
    print(snap.to_block())
    return 0


# ---------------------------------------------------------------------------
# 输出工具
# ---------------------------------------------------------------------------


def _quota_to_dict(snapshot: QuotaSnapshot | None) -> dict | None:
    if snapshot is None:
        return None
    breakers = {}
    for kind, brk in (snapshot.breakers or {}).items():
        breakers[kind] = {"state": brk.state, "remaining_cooldown": brk.remaining_cooldown}
    return {
        "by_kind": snapshot.by_kind,
        "breakers": breakers,
        "reset_at": snapshot.reset_at,
    }


def _print_json(result: commands.CommandResult, kind: str) -> int:
    """JSON 输出：stdout 只输出 JSON，不混任何提示文本。"""
    payload: dict = {"success": result.success, "kind": kind}
    if result.success:
        payload["data"] = result.data or {}
    else:
        payload["error"] = result.error
    if result.quota is not None:
        payload["quota"] = _quota_to_dict(result.quota)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if result.success else 1


def _print_markdown(result: commands.CommandResult, kind: str, **fmt_kw: object) -> int:
    """Markdown 输出：格式化文本 + 配额行。"""
    if not result.success:
        print(f"[错误] {result.error}", file=sys.stderr)
        if result.quota is not None:
            print(result.quota.to_line(), file=sys.stderr)
        return 1

    text = ""
    if kind == "search":
        text = formatters.format_search_items(result.data, **fmt_kw)
    elif kind == "ask":
        text = formatters.format_zhida_answer(result.data)
    elif kind == "trending":
        text = formatters.format_hot_items(result.data)
    elif kind == "user_contents":
        text = formatters.format_content_items(result.data, heading="知乎用户内容")
    elif kind == "user_followees":
        text = formatters.format_followees(result.data)
    elif kind == "user_collections":
        text = formatters.format_content_items(result.data, heading="知乎近期收藏")
    elif kind == "user_favlists":
        text = formatters.format_favlists(result.data)
    elif kind == "favlist_contents":
        text = formatters.format_content_items(result.data, heading="知乎收藏夹内容")
    elif kind == "pdf_upload":
        text = formatters.format_upload_result(result.data)
    elif kind in {"pdf_create", "pdf_status"}:
        text = formatters.format_task_status(result.data, "PDF")
    elif kind in {"ppt_create", "ppt_status"}:
        text = formatters.format_task_status(result.data, "PPT")

    if text:
        print(text)
    if result.quota is not None:
        print(f"\n{result.quota.to_line()}")
    return 0


def _resolve_oauth_token(value: str) -> str | None:
    """Prefer an explicit token, then the non-persistent environment value."""
    return value or os.environ.get("ZHIHU_OAUTH_TOKEN") or None


# ---------------------------------------------------------------------------
# 子命令异步入口
# ---------------------------------------------------------------------------


async def _run_search(args: argparse.Namespace) -> int:
    result = await commands.run_search(
        query=args.query,
        scope=args.scope,
        count=args.count,
        filter=args.filter,
        search_db=args.search_db,
    )
    if args.format == "json":
        return _print_json(result, "search")
    return _print_markdown(result, "search", scope=args.scope)


async def _run_ask(args: argparse.Namespace) -> int:
    result = await commands.run_ask(query=args.query, model=args.model)
    if args.format == "json":
        return _print_json(result, "ask")
    return _print_markdown(result, "ask")


async def _run_trending(args: argparse.Namespace) -> int:
    result = await commands.run_trending(limit=args.limit)
    if args.format == "json":
        return _print_json(result, "trending")
    return _print_markdown(result, "trending")


async def _run_user_contents(args: argparse.Namespace) -> int:
    result = await commands.run_user_contents(
        content_type=args.content_type,
        offset=args.offset,
        limit=args.limit,
        sort_field=args.sort_field,
        sort_order=args.sort_order,
        oauth_token=_resolve_oauth_token(args.oauth_token),
    )
    if args.format == "json":
        return _print_json(result, "user_contents")
    return _print_markdown(result, "user_contents")


async def _run_user_followees(args: argparse.Namespace) -> int:
    result = await commands.run_user_followees(
        offset=args.offset,
        limit=args.limit,
        oauth_token=_resolve_oauth_token(args.oauth_token),
    )
    if args.format == "json":
        return _print_json(result, "user_followees")
    return _print_markdown(result, "user_followees")


async def _run_user_collections(args: argparse.Namespace) -> int:
    result = await commands.run_user_collections(
        limit=args.limit,
        oauth_token=_resolve_oauth_token(args.oauth_token),
    )
    if args.format == "json":
        return _print_json(result, "user_collections")
    return _print_markdown(result, "user_collections")


async def _run_user_favlists(args: argparse.Namespace) -> int:
    result = await commands.run_user_favlists(
        limit=args.limit,
        oauth_token=_resolve_oauth_token(args.oauth_token),
    )
    if args.format == "json":
        return _print_json(result, "user_favlists")
    return _print_markdown(result, "user_favlists")


async def _run_favlist_contents(args: argparse.Namespace) -> int:
    result = await commands.run_favlist_contents(
        favlist_url_token=args.url_token,
        favlist_id=args.id,
        offset=args.offset,
        limit=args.limit,
        oauth_token=_resolve_oauth_token(args.oauth_token),
    )
    if args.format == "json":
        return _print_json(result, "favlist_contents")
    return _print_markdown(result, "favlist_contents")


async def _run_pdf_upload(args: argparse.Namespace) -> int:
    result = await commands.run_pdf_upload(file_path=args.file)
    if args.format == "json":
        return _print_json(result, "pdf_upload")
    return _print_markdown(result, "pdf_upload")


async def _run_pdf_create(args: argparse.Namespace) -> int:
    result = await commands.run_pdf_create(
        file_id=args.file_id,
        idempotency_key=args.idempotency_key or None,
    )
    if args.format == "json":
        return _print_json(result, "pdf_create")
    return _print_markdown(result, "pdf_create")


async def _run_pdf_status(args: argparse.Namespace) -> int:
    result = await commands.run_pdf_status(task_id=args.task_id)
    if args.format == "json":
        return _print_json(result, "pdf_status")
    return _print_markdown(result, "pdf_status")


async def _run_ppt_create(args: argparse.Namespace) -> int:
    result = await commands.run_ppt_create(
        resource_url=args.resource_url,
        num_pages=args.pages,
        idempotency_key=args.idempotency_key or None,
    )
    if args.format == "json":
        return _print_json(result, "ppt_create")
    return _print_markdown(result, "ppt_create")


async def _run_ppt_status(args: argparse.Namespace) -> int:
    result = await commands.run_ppt_status(task_id=args.task_id)
    if args.format == "json":
        return _print_json(result, "ppt_status")
    return _print_markdown(result, "ppt_status")


def _run_oauth_url(args: argparse.Namespace) -> int:
    from .oauth import build_authorize_url

    print(build_authorize_url(app_id=args.app_id, redirect_uri=args.redirect_uri))
    return 0


async def _run_oauth_token(args: argparse.Namespace) -> int:
    from .oauth import exchange_access_token

    app_key = args.app_key or os.environ.get("ZHIHU_OAUTH_APP_KEY")
    if not app_key:
        print(
            "FAIL  缺少 OAuth app_key；请设置 ZHIHU_OAUTH_APP_KEY"
            " 或显式传 --app-key。",
            file=sys.stderr,
        )
        return 1
    payload = await exchange_access_token(
        app_id=args.app_id,
        app_key=app_key,
        redirect_uri=args.redirect_uri,
        code=args.code,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    # --- flags（优先处理，与旧版行为一致） ---
    if args.save_token:
        path = credentials.save(args.save_token)
        print(f"OK  已保存到 {path}")
        return 0

    if args.clear_token:
        if credentials.clear():
            print("OK  凭证文件已删除")
        else:
            print("OK  凭证文件本来就不存在")
        return 0

    if args.check_token:
        try:
            creds = credentials.load()
        except credentials.CredentialsError as e:
            print(f"FAIL  {e}", file=sys.stderr)
            return 1
        _print_credentials_info(creds)
        return 0

    if args.quota:
        return _show_quota()

    if args.reset_quota:
        QuotaTracker().reset()
        print("OK  今日计数已清零")
        return 0

    if args.probe:
        try:
            return asyncio.run(_probe())
        except credentials.CredentialsError as e:
            print(f"FAIL  {e}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"FAIL  探测失败：{e}", file=sys.stderr)
            return 2

    # --- 子命令（未指定则默认 serve） ---
    if args.command is None or args.command == "serve":
        from .server import main as server_main

        try:
            server_main(tool_selection=getattr(args, "tools", None))
        except ValueError as e:
            print(f"FAIL  MCP 工具配置错误：{e}", file=sys.stderr)
            return 2
        return 0

    if args.command == "openwebui":
        from .openwebui import main as openwebui_main

        openwebui_main(host=args.host, port=args.port, api_key=args.api_key)
        return 0

    try:
        if args.command == "oauth-url":
            return _run_oauth_url(args)
        if args.command == "oauth-token":
            return asyncio.run(_run_oauth_token(args))
        if args.command == "search":
            return asyncio.run(_run_search(args))
        if args.command == "ask":
            return asyncio.run(_run_ask(args))
        if args.command == "trending":
            return asyncio.run(_run_trending(args))
        if args.command == "user-contents":
            return asyncio.run(_run_user_contents(args))
        if args.command == "user-followees":
            return asyncio.run(_run_user_followees(args))
        if args.command == "user-collections":
            return asyncio.run(_run_user_collections(args))
        if args.command == "user-favlists":
            return asyncio.run(_run_user_favlists(args))
        if args.command == "favlist-contents":
            return asyncio.run(_run_favlist_contents(args))
        if args.command == "pdf-upload":
            return asyncio.run(_run_pdf_upload(args))
        if args.command == "pdf-create":
            return asyncio.run(_run_pdf_create(args))
        if args.command == "pdf-status":
            return asyncio.run(_run_pdf_status(args))
        if args.command == "ppt-create":
            return asyncio.run(_run_ppt_create(args))
        if args.command == "ppt-status":
            return asyncio.run(_run_ppt_status(args))
    except credentials.CredentialsError as e:
        print(f"FAIL  凭证错误：{e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"FAIL  命令执行失败：{e}", file=sys.stderr)
        return 2

    # 不应到达这里
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
