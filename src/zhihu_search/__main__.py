"""模块入口：`python -m zhihu_search`。"""

from __future__ import annotations

import sys

# 在 Windows 上强制 UTF-8 输出，避免中文乱码
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover
        pass

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())