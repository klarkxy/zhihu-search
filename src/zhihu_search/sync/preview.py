"""生成本地预览页。预览不是发布内容。"""

from __future__ import annotations

import html
import subprocess
from datetime import datetime
from pathlib import Path


def render_preview(prepared: dict[str, object]) -> str:
    draft = prepared.get("draft") if isinstance(prepared.get("draft"), dict) else {}
    title = html.escape(str(draft.get("title") or "（无标题）"))
    content_type = html.escape(str(draft.get("type") or ""))
    body = str(prepared.get("html") or "")
    images = draft.get("images") if isinstance(draft.get("images"), list) else []
    figures: list[str] = []
    if content_type == "pin":
        for image in images:
            if not isinstance(image, dict):
                continue
            url = str(image.get("url") or "")
            if url.startswith("https://"):
                figures.append(f'<figure><img src="{html.escape(url, quote=True)}" alt=""></figure>')
    issue_rows = []
    for issue in prepared.get("issues") or []:
        if not isinstance(issue, dict):
            continue
        issue_rows.append(
            "<li>[{severity}] {code}：{message}</li>".format(
                severity=html.escape(str(issue.get("severity") or "")),
                code=html.escape(str(issue.get("code") or "")),
                message=html.escape(str(issue.get("message") or "")),
            )
        )
    issues = "<ul>" + "".join(issue_rows) + "</ul>" if issue_rows else "<p>没有校验问题。</p>"
    can_publish = "可以进入确认发布" if prepared.get("can_publish") else "还不能发布"
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
body {{ font-family: sans-serif; max-width: 42rem; margin: 2rem auto; line-height: 1.6; }}
.banner {{ background: #fff7e6; border: 1px solid #ffd591; padding: .75rem 1rem; }}
img {{ max-width: 100%; }}
pre {{ overflow: auto; background: #f6f6f6; padding: .75rem; }}
</style>
</head>
<body>
<p class="banner">本地预览，尚未发布到知乎。类型：{content_type}。{can_publish}。</p>
<h1>{title}</h1>
<article>{body}</article>
{''.join(figures)}
<section><h2>校验</h2>{issues}</section>
</body>
</html>
"""


def write_preview_files(directory: Path, html_text: str, prepared: dict[str, object]) -> Path:
    preview_dir = directory / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    latest = preview_dir / "latest.html"
    latest.write_text(html_text, encoding="utf-8")
    (preview_dir / f"{stamp}-preview.html").write_text(html_text, encoding="utf-8")
    validate_dir = directory / "validate"
    validate_dir.mkdir(parents=True, exist_ok=True)
    import json

    payload = json.dumps(prepared, ensure_ascii=False, indent=2)
    (validate_dir / "latest.json").write_text(payload, encoding="utf-8")
    (validate_dir / f"{stamp}-result.json").write_text(payload, encoding="utf-8")
    return latest


def ensure_git_exclude(directory: Path) -> str | None:
    """若输出目录在 Git 工作区且未被忽略，写入 ``.git/info/exclude``。"""
    try:
        root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=directory if directory.is_dir() else directory.parent,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if root.returncode != 0:
        return None
    worktree = Path(root.stdout.strip())
    try:
        relative = directory.resolve().relative_to(worktree.resolve())
    except ValueError:
        return None
    pattern = "/" + relative.as_posix().strip("/") + "/"
    check = subprocess.run(
        ["git", "check-ignore", "-q", "--", str(directory)],
        cwd=worktree,
        check=False,
        capture_output=True,
        text=True,
    )
    if check.returncode == 0:
        return None
    exclude = worktree / ".git" / "info" / "exclude"
    try:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        current = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
        if pattern not in current.splitlines():
            with exclude.open("a", encoding="utf-8") as handle:
                if current and not current.endswith("\n"):
                    handle.write("\n")
                handle.write(pattern + "\n")
    except OSError:
        return f"无法写入 .git/info/exclude，请不要提交 {pattern}"
    return None


def try_open_browser(path: Path) -> bool:
    try:
        completed = subprocess.run(["xdg-open", str(path)], check=False, capture_output=True)
    except OSError:
        return False
    return completed.returncode == 0
