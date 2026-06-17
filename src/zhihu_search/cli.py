"""命令行入口。

用法：
    zhihu-search serve              # 默认：启动 stdio MCP 服务器
    zhihu-search --check-token      # 验证凭证是否加载成功
    zhihu-search --save-token <s>   # 保存 token 到默认文件
    zhihu-search --clear-token      # 删除凭证文件
    zhihu-search --quota            # 查看今日配额用量
    zhihu-search --probe            # 调用 hot_list(limit=1) 端到端验证
    zhihu-search --version
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from . import __version__, credentials
from .quota import QuotaTracker


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="zhihu-search",
        description=(
            "知乎开放平台的统一 MCP 封装。"
            "默认启动 stdio 服务器；其它参数用于凭证管理和连通性自检。"
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
    p.add_argument(
        "command",
        nargs="?",
        default="serve",
        choices=["serve"],
        help="保留子命令占位（当前固定为 serve）。",
    )
    return p


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


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

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

    # 默认：启动 stdio MCP 服务器
    from .server import main as server_main

    server_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())