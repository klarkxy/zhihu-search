"""命令行入口。

用法：
    zhihu-search [flags...] [command [args...]]

Flags:
    --version, --check-token, --save-token <s>, --clear-token,
    --quota, --reset-quota, --probe

Commands (默认: serve):
    serve              启动 stdio MCP 服务器
    search <query>     搜索知乎内容
    ask <query>        向知乎直答提问
    trending           查看知乎热榜

使用 ``zhihu-search <command> --help`` 查看子命令详细参数。
"""

from __future__ import annotations

import argparse
import asyncio
import json
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
        metavar="{search,ask,trending,serve}",
    )

    # --- serve（显式入口）---
    sub.add_parser("serve", help="启动 stdio MCP 服务器（默认）。")

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

    return p


# ---------------------------------------------------------------------------
# 凭证与诊断工具（保持不变）
# ---------------------------------------------------------------------------


def _print_credentials_info(creds: credentials.Credentials) -> None:
    print(f"OK  Access Secret 来源：{creds.source}")
    if creds.path:
        print(f"    文件：{creds.path}")
    masked = (
        creds.access_secret[:4] + "…" + creds.access_secret[-2:]
        if len(creds.access_secret) > 8
        else "(过短)"
    )
    print(f"    预览：{masked}")


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
        if result.quota is not None:
            payload["quota"] = _quota_to_dict(result.quota)
    else:
        payload["error"] = result.error
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if result.success else 1


def _print_markdown(result: commands.CommandResult, kind: str, **fmt_kw: object) -> int:
    """Markdown 输出：格式化文本 + 配额行。"""
    if not result.success:
        print(f"[错误] {result.error}", file=sys.stderr)
        return 1

    text = ""
    if kind == "search":
        text = formatters.format_search_items(result.data, **fmt_kw)
    elif kind == "ask":
        text = formatters.format_zhida_answer(result.data)
    elif kind == "trending":
        text = formatters.format_hot_items(result.data)

    if text:
        print(text)
    if result.quota is not None:
        print(f"\n{result.quota.to_line()}")
    return 0


# ---------------------------------------------------------------------------
# 子命令异步入口
# ---------------------------------------------------------------------------


async def _run_search(args: argparse.Namespace) -> int:
    result = await commands.run_search(
        query=args.query,
        scope=args.scope,
        count=args.count,
        filter=args.filter,
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

        server_main()
        return 0

    try:
        if args.command == "search":
            return asyncio.run(_run_search(args))
        if args.command == "ask":
            return asyncio.run(_run_ask(args))
        if args.command == "trending":
            return asyncio.run(_run_trending(args))
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
