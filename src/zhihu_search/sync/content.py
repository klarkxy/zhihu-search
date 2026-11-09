"""把文章、提问和想法适配成知乎发布 HTML，并组装发布请求。

转换规则来自知乎官方同步助手（Zhihu/ZhihuSync，MIT，author zhihu）的
conversion / publish 说明：长度超限不截断，公式定界符内侧空白不 trim，
危险 HTML 不进入输出。代码语言 id 列表取自上游 ``code-languages.md``。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Mapping
from urllib.parse import quote, urlsplit

VIDEO_UNSUPPORTED = "当前知乎发布流程暂不支持视频，请移除视频后重新提交。"

LIMITS = {
    "question_title_min": 4,
    "question_title_max": 51,
    "pin_title_max": 50,
    "article_title_max": 100,
    "article_body_min": 9,
    "article_body_max": 100_000,
    "pin_body_max": 2_000,
    "pin_images_max": 18,
    "pin_topics_max": 10,
    "article_topics_max": 3,
    "question_topics_max": 5,
    "caption_max": 140,
}

ARTICLE_COMMENT_PERMISSIONS = ("all", "nobody", "followee", "censor", "follower")
PIN_COMMENT_PERMISSIONS = ("all", "nobody", "followee", "censor", "follower_n_days")
ARTICLE_CREATION_STATEMENTS = (
    "spoiler",
    "medical_advice",
    "fictional_creation",
    "contain_finance",
    "ai_creation",
)

# Upstream code-languages.md ids. jsx and raw are intentionally absent.
SUPPORTED_LANGS = frozenset(
    """
    abap abnf actionscript ada adl agda ahk alloy antlr apacheconf apl applescript
    arduino as as3 asciidoc aspectj asy at autoit awk basemake bash bat bbcode bc
    befunge bib blitzbasic blitzmax bnf boo boogie brainfuck bro bugs c c++ c#
    ca65 cadl camkes cbmbas ceylon cfengine3 cfm cfs chai chapel cheetah cirru clay
    clojure clojurescript cmake cobol cobolfree coffee-script common-lisp
    componentpascal console control coq cpp cpp-objdump cpsa crmsh croc cryptol
    csharp csound csound-document csound-score css cuda cython d d-objdump darcs
    dart debcontrol debian delphi dg diff django docker dpatch dtd duel dylan
    dylan-console dylanlid ebnf ecl eiffel elixir elm emacslisp erb erl erlang
    evoque factor fancy fantom felix fortran foxpro fsharp gas genshi glsl gnuplot
    go golo gooddata-cl gosu groff groovy gst haml handlebars haskell haxeml html
    httpd hy idl idris igor inform6 inform7 ini io ioke irb jade java js json julia
    jvm kal kconfig koka kotlin lagda lasso lhs lidr lighty lisp live-script llvm
    logos logtalk lua make mako mason mask matlab md minid modelica modula2 monkey
    moocode moon mscgen mupad mxml mysql nasm newlisp nginx nim nit nixos nsis
    numpy objdump-c objdump-cpp objdump-d objdump-nasm objective-c objective-j
    ocaml octave odin ooc opa openedge pacmanconf pan pawn perl php pig pike
    pkgconfig plpgsql postscript powershell prolog properties protobuf psql puppet
    py pycon pypylog pytb python python3 qbasic r rake rb rbcon rebol red redcode
    registry resources robotframework rq rql rst rts rust sass scala scaml scheme
    scilab scss sh shell smarty snobol sourceslist sp sparql sql squidconf sre stan
    swift swig systemverilog tads3 tap tcl tcsh tea termcap terminfo terraform text
    textile thrift todotxt trac-wiki treetop ts turtle twig urbiscript v vala
    vb.net vctreestatus velocity verilog vgl vhdl vim x10 xml xquery xslt xtend
    xul+mozpreproc yaml yaml+jinja zephir
    """.split()
)

_DANGEROUS_TAG = re.compile(
    r"<\s*/?\s*(script|iframe|object|embed|svg|style|link|meta|base|form|video|audio|frame|frameset|applet)\b",
    re.IGNORECASE,
)
_DANGEROUS_ATTR = re.compile(r"\bon[a-z]+\s*=", re.IGNORECASE)
_DANGEROUS_URL = re.compile(r"(javascript|vbscript|data)\s*:", re.IGNORECASE)
_TOPIC_URL = re.compile(r"^/topic/(\d+)(?:/|$)")
_RING_URL = re.compile(r"^/ring/host/(\d+)(?:/|$)")
_ZHIHU_HOST = re.compile(r"^(?:[a-z0-9-]+\.)*(?:zhimg\.com|zhihu\.com)$", re.IGNORECASE)
_FENCE = re.compile(r"^```([^\n`]*)\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_HR = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})\s*$")
_UL = re.compile(r"^[-*+]\s+(.*)$")
_OL = re.compile(r"^\d+\.\s+(.*)$")
_QUOTE = re.compile(r"^>\s?(.*)$")
_VIDEO_EXT = re.compile(r"\.(mp4|mov|webm|mkv|avi|m4v)(?:$|\?)", re.IGNORECASE)


def prepare_content(draft: Mapping[str, object] | object) -> dict[str, object]:
    """规范化草稿并生成知乎 HTML。``can_publish`` 为假时不得发布。"""
    issues: list[dict[str, str]] = []
    if not isinstance(draft, Mapping):
        return _failed("input.invalid", "草稿必须是对象。")
    normalized = _normalize_draft(draft, issues)
    ctx = _Ctx(content_type=normalized["type"])
    title = _normalize_title(normalized, ctx)
    normalized["title"] = title
    body = str(normalized["body"])
    if _VIDEO_EXT.search(body) and ("![" in body or "<video" in body.lower()):
        ctx.error("video.unsupported", VIDEO_UNSUPPORTED)
        ctx.suppress = True
    if "<video" in body.lower():
        ctx.error("video.unsupported", VIDEO_UNSUPPORTED)
        ctx.suppress = True

    if normalized["format"] == "html":
        html = _sanitize_html(body, ctx)
    else:
        if _dangerous_markdown(body):
            ctx.error("html.dangerous", "正文含有不允许的标签、事件属性或危险 URL，已停止转换。")
            ctx.suppress = True
            html = ""
        else:
            html = _markdown_to_html(body, ctx)

    if ctx.content_type == "pin":
        html, topic_count = _inject_pin_topics(html)
    else:
        topic_count = 0
    html = _render_images(html, ctx, normalized)
    if ctx.suppress:
        html = ""
    counts = {
        "title_chars": len(title),
        "body_chars": plain_text_length(html),
        "images": len(normalized["images"]) if normalized["type"] == "pin" else len(ctx.body_images),
        "topics": topic_count if normalized["type"] == "pin" else len(normalized["settings"].get("topics") or []),
    }
    _check_body_length(normalized, counts["body_chars"], ctx)
    _check_pin_media(normalized, ctx)
    if normalized["type"] == "pin" and topic_count > LIMITS["pin_topics_max"]:
        ctx.error("topics.too-many", f"想法话题最多 {LIMITS['pin_topics_max']} 个，当前 {topic_count} 个。")
    _validate_settings(normalized, ctx)
    issues.extend(ctx.issues)
    can_publish = not any(item["severity"] == "error" for item in issues)
    return {
        "draft": normalized,
        "html": "" if not can_publish and ctx.suppress else html,
        "issues": issues,
        "can_publish": can_publish,
        "counts": counts,
    }


def build_publish_request(prepared: Mapping[str, object]) -> dict[str, object]:
    """把校验通过的结果映射为 publish OpenAPI 请求体。不改写正文字段。"""
    if not isinstance(prepared, Mapping) or prepared.get("can_publish") is not True:
        raise ValueError("需要 can_publish 为 true 的校验结果，且用户已确认预览。")
    draft = prepared.get("draft")
    html = prepared.get("html")
    if not isinstance(draft, Mapping) or not isinstance(html, str):
        raise ValueError("校验结果缺少 draft 或 html。")
    settings = draft.get("settings") if isinstance(draft.get("settings"), Mapping) else {}
    content_type = str(draft.get("type") or "")
    envelope: dict[str, object] = {
        "type": content_type,
        "confirmed": True,
        "confirm_note": "confirmed by user after local preview",
    }
    if content_type == "article":
        content: dict[str, object] = {
            "title": draft.get("title") or "",
            "html": html,
            "comment_permission": settings.get("comment_permission") or "all",
            "table_of_contents_enabled": bool(settings.get("table_of_contents_enabled") or False),
        }
        if settings.get("creation_statement"):
            content["creation_statement"] = settings["creation_statement"]
        topics = _topic_tokens(settings.get("topics") or [], LIMITS["article_topics_max"])
        if topics:
            content["topics"] = topics
    elif content_type == "question":
        content = {"title": draft.get("title") or "", "html": html}
        topics = _topic_tokens(settings.get("topics") or [], LIMITS["question_topics_max"])
        if topics:
            content["topics"] = topics
    elif content_type == "pin":
        content = {
            "html": html,
            "comment_permission": settings.get("comment_permission") or "all",
        }
        title = str(draft.get("title") or "")
        if title:
            content["title"] = title
        images = [
            {"url": str(item.get("url") or "")}
            for item in (draft.get("images") or [])
            if isinstance(item, Mapping) and str(item.get("url") or "")
        ]
        link_card = draft.get("link_card")
        if images:
            content["images"] = images
        elif isinstance(link_card, Mapping) and link_card.get("url"):
            content["linkcard"] = {
                "data_content_type": link_card.get("content_type") or "common_url",
                "data_content_id": str(link_card.get("content_id") or "0"),
                "url": link_card.get("url"),
                "data_draft_title": link_card.get("title") or "",
                "data_draft_cover": link_card.get("cover") or "",
                "is_from_forward": bool(link_card.get("is_from_forward") or False),
            }
        if settings.get("creation_statement") == "ai_creation":
            content["creation_statement"] = "ai_creation"
        ring = _ring_id(settings.get("ring"))
        if ring:
            content["ring"] = ring
    else:
        raise ValueError(f"不支持的内容形态：{content_type}")
    envelope["content"] = content
    return envelope


def plain_text_length(html: str) -> int:
    """按纯文本码点计数，不含标签和属性。"""

    class _Text(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []

        def handle_data(self, data: str) -> None:
            self.parts.append(data)

    parser = _Text()
    parser.feed(html or "")
    parser.close()
    return len("".join(parser.parts))


def normalize_code_lang(raw: str | None) -> str:
    if not raw:
        return ""
    ident = raw.strip().lower()
    return ident if ident in SUPPORTED_LANGS else ""


@dataclass
class _ImageRef:
    src: str
    caption: str
    resolved: dict[str, object] | None = None


@dataclass
class _Ctx:
    content_type: str
    issues: list[dict[str, str]] = field(default_factory=list)
    body_images: list[_ImageRef] = field(default_factory=list)
    suppress: bool = False
    pin_note: bool = False
    image_seq: int = 0

    @property
    def pin(self) -> bool:
        return self.content_type == "pin"

    def error(self, code: str, message: str) -> None:
        self.issues.append({"severity": "error", "code": code, "message": message})

    def warning(self, code: str, message: str) -> None:
        self.issues.append({"severity": "warning", "code": code, "message": message})

    def note_pin(self) -> None:
        if self.pin and not self.pin_note:
            self.pin_note = True
            self.warning("pin.rich-text", "想法正文只保留纯文本段落和文字链接，其余格式已降级。")


def _failed(code: str, message: str) -> dict[str, object]:
    return {
        "draft": {},
        "html": "",
        "issues": [{"severity": "error", "code": code, "message": message}],
        "can_publish": False,
        "counts": {"title_chars": 0, "body_chars": 0, "images": 0, "topics": 0},
    }


def _normalize_draft(raw: Mapping[str, object], issues: list[dict[str, str]]) -> dict[str, object]:
    content_type = str(_pick(raw, "type", "content_type") or "").strip()
    if content_type not in {"article", "question", "pin"}:
        issues.append({"severity": "error", "code": "type.invalid", "message": "type 必须是 article、question 或 pin。"})
        content_type = "article"
    fmt = str(_pick(raw, "format", "body_format") or "markdown").strip()
    if fmt not in {"markdown", "html"}:
        issues.append({"severity": "error", "code": "format.invalid", "message": "format 必须是 markdown 或 html。"})
        fmt = "markdown"
    title = raw.get("title")
    body = raw.get("body")
    draft: dict[str, object] = {
        "type": content_type,
        "title": title if isinstance(title, str) else "",
        "body": body if isinstance(body, str) else "",
        "format": fmt,
        "images": _normalize_images(raw.get("images"), issues),
        "link_card": _normalize_link_card(_pick(raw, "link_card", "linkCard"), issues),
        "settings": _normalize_settings(_pick(raw, "settings") or {}, issues),
    }
    if not isinstance(title, str):
        issues.append({"severity": "error", "code": "title.invalid", "message": "标题必须是字符串。"})
    if not isinstance(body, str):
        issues.append({"severity": "error", "code": "body.invalid", "message": "正文必须是字符串。"})
    return draft


def _normalize_images(value: object, issues: list[dict[str, str]]) -> list[dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        issues.append({"severity": "warning", "code": "input.bad-images", "message": "images 必须是数组，已忽略。"})
        return []
    images: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        url = str(_pick(item, "url") or "")
        original = _pick(item, "original_url", "originalUrl")
        image: dict[str, object] = {"url": url}
        if isinstance(original, str) and original:
            image["original_url"] = original
        for src, dest in (("width", "width"), ("height", "height")):
            number = item.get(src)
            if isinstance(number, int) and number > 0:
                image[dest] = number
        if item.get("watermark") is True:
            image["watermark"] = True
        elif item.get("watermark") is False:
            image["watermark"] = False
        media_id = _pick(item, "media_id", "mediaId")
        if isinstance(media_id, str) and media_id:
            image["media_id"] = media_id
        if url:
            images.append(image)
    return images


def _normalize_link_card(value: object, issues: list[dict[str, str]]) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        issues.append({"severity": "warning", "code": "input.bad-linkcard", "message": "link_card 必须是对象，已忽略。"})
        return None
    url = str(value.get("url") or "").strip()
    if not url:
        issues.append({"severity": "warning", "code": "input.bad-linkcard", "message": "link_card 缺少 url，已忽略。"})
        return None
    card: dict[str, object] = {"url": url}
    for src, dest in (
        ("title", "title"),
        ("cover", "cover"),
        ("content_type", "content_type"),
        ("contentType", "content_type"),
        ("content_id", "content_id"),
        ("contentId", "content_id"),
    ):
        text = value.get(src)
        if isinstance(text, str) and text and dest not in card:
            card[dest] = text
    if value.get("is_from_forward") is True or value.get("isFromForward") is True:
        card["is_from_forward"] = True
    return card


def _normalize_settings(value: object, issues: list[dict[str, str]]) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        issues.append({"severity": "warning", "code": "input.bad-settings", "message": "settings 必须是对象，已忽略。"})
        return {}
    settings: dict[str, object] = {}
    permission = _pick(value, "comment_permission", "commentPermission")
    if isinstance(permission, str) and permission:
        settings["comment_permission"] = permission
    statement = _pick(value, "creation_statement", "creationStatement")
    if isinstance(statement, str) and statement:
        settings["creation_statement"] = statement
    toc = _pick(value, "table_of_contents_enabled", "tableOfContentsEnabled")
    if toc is not None:
        settings["table_of_contents_enabled"] = toc is True
    topics = value.get("topics")
    if isinstance(topics, list):
        settings["topics"] = [item.strip() for item in topics if isinstance(item, str) and item.strip()]
    ring = value.get("ring")
    if isinstance(ring, str) and ring.strip():
        settings["ring"] = ring.strip()
    return settings


def _normalize_title(draft: dict[str, object], ctx: _Ctx) -> str:
    title = str(draft["title"])
    if ctx.content_type == "question":
        title = title.rstrip()
        if title and not re.search(r"[？?]\s*$", title):
            title += "？"
    if "\n" in title or "\r" in title:
        ctx.error("title.multiline", "标题禁止换行。")
    length = len(title)
    if ctx.content_type == "question":
        if length == 0:
            ctx.error("title.required", "提问标题必填。")
        elif length < LIMITS["question_title_min"] or length > LIMITS["question_title_max"]:
            ctx.error("title.too-long" if length > LIMITS["question_title_max"] else "title.too-short",
                      f"提问标题 4～51 字（含结尾问号），当前 {length} 字。")
        if len(re.findall(r"[？?]", title)) > 1:
            ctx.warning("title.multi-question", "标题含多个问号，请确认只表达一个明确问题。")
    elif ctx.content_type == "pin":
        if length > LIMITS["pin_title_max"]:
            ctx.error("title.too-long", f"想法标题最多 {LIMITS['pin_title_max']} 字，当前 {length} 字。")
    else:
        if length == 0:
            ctx.error("title.required", "文章标题必填。")
        if length > LIMITS["article_title_max"]:
            ctx.error("title.too-long", f"文章标题最多 {LIMITS['article_title_max']} 字，当前 {length} 字。")
    return title


def _check_body_length(draft: dict[str, object], body_chars: int, ctx: _Ctx) -> None:
    if ctx.content_type == "article":
        if body_chars < LIMITS["article_body_min"]:
            ctx.error("body.too-short", f"文章正文至少 {LIMITS['article_body_min']} 字（纯文本），当前 {body_chars} 字。")
        if body_chars > LIMITS["article_body_max"]:
            ctx.error("body.too-long", f"文章正文最多 {LIMITS['article_body_max']} 字（纯文本），当前 {body_chars} 字。")
    elif ctx.content_type == "pin":
        if body_chars > LIMITS["pin_body_max"]:
            ctx.error("body.too-long", f"想法正文最多 {LIMITS['pin_body_max']} 字（纯文本），当前 {body_chars} 字。")
        images = draft.get("images") or []
        has_media = bool(images) or bool(draft.get("link_card"))
        if body_chars == 0 and not has_media:
            ctx.error("body.required", "想法正文、图片或链接卡片至少需要一项有效内容。")
        elif body_chars == 0:
            ctx.error("body.required", "想法正文不能为空，请补充正文后再发布。")


def _check_pin_media(draft: dict[str, object], ctx: _Ctx) -> None:
    if ctx.content_type != "pin":
        return
    images = [item for item in draft["images"] if isinstance(item, dict)]
    for image in images:
        if not _is_zhihu_image(str(image.get("url") or "")):
            ctx.error("image.unsafe-url", "想法图片的发布 URL 必须是 HTTPS 知乎图片地址。")
    if len(images) > LIMITS["pin_images_max"]:
        ctx.error("images.too-many", f"想法独立图片最多 {LIMITS['pin_images_max']} 张，当前 {len(images)} 张。")
    if images and draft.get("link_card"):
        ctx.error("pin.media-linkcard-exclusive", "当前不支持 单条想法中同时包括链接卡片 与  图片")
    card = draft.get("link_card")
    if isinstance(card, dict):
        if not _is_http_url(str(card.get("url") or "")):
            ctx.error("linkcard.url-unsafe", "链接卡片 url 必须是 http(s) 地址。")
        cover = str(card.get("cover") or "")
        if cover and not _is_zhihu_image(cover):
            ctx.error("linkcard.cover-unsafe", "链接卡片封面必须是 HTTPS 知乎图片地址。")


def _validate_settings(draft: dict[str, object], ctx: _Ctx) -> None:
    settings = draft["settings"]
    content_type = ctx.content_type
    if content_type == "question":
        for key, label in (
            ("comment_permission", "评论权限"),
            ("creation_statement", "创作声明"),
            ("table_of_contents_enabled", "目录"),
            ("ring", "圈子"),
        ):
            if key in settings:
                ctx.warning(f"settings.unsupported-{key}", f"提问不支持{label}，发布时会忽略。")
    if content_type == "article" and "ring" in settings:
        ctx.warning("settings.unsupported-ring", "文章不支持圈子，发布时会忽略。")
    topics = settings.get("topics") or []
    if topics:
        if content_type == "pin":
            ctx.warning("settings.unsupported-topics", "想法话题写在正文的 #话题名# 里，发布时会忽略 settings.topics。")
        else:
            maximum = LIMITS["article_topics_max"] if content_type == "article" else LIMITS["question_topics_max"]
            invalid = [item for item in topics if not _zhihu_path(str(item), _TOPIC_URL)]
            if invalid:
                ctx.error("topics.invalid", "话题必须是 https://www.zhihu.com/topic/{token}/... 链接。")
            if len(topics) > maximum:
                label = "文章" if content_type == "article" else "提问"
                ctx.error("topics.too-many", f"{label}话题最多 {maximum} 个，当前 {len(topics)} 个。")
    permission = settings.get("comment_permission")
    if isinstance(permission, str) and content_type != "question":
        allowed = PIN_COMMENT_PERMISSIONS if content_type == "pin" else ARTICLE_COMMENT_PERMISSIONS
        if permission not in allowed:
            ctx.error("comment-permission.invalid", f"当前形态不支持评论权限 {permission}。")
    statement = settings.get("creation_statement")
    if isinstance(statement, str):
        if content_type == "pin" and statement != "ai_creation":
            ctx.error("creation-statement.invalid", "想法只支持 ai_creation 创作声明。")
        elif content_type == "article" and statement not in ARTICLE_CREATION_STATEMENTS:
            ctx.error("creation-statement.invalid", f"不支持的创作声明：{statement}。")
    ring = settings.get("ring")
    if isinstance(ring, str) and content_type == "pin" and not _zhihu_path(ring, _RING_URL):
        ctx.error("ring.invalid", "圈子必须是 https://www.zhihu.com/ring/host/{id} 链接。")


def _dangerous_markdown(body: str) -> bool:
    visible = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    if _DANGEROUS_TAG.search(visible) or _DANGEROUS_ATTR.search(visible):
        return True
    for match in re.finditer(r"\(([^)\s]+)\)", visible):
        if _DANGEROUS_URL.search(match.group(1)):
            return True
    return False


def _markdown_to_html(body: str, ctx: _Ctx) -> str:
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        fence = _FENCE.match(line)
        if fence:
            lang = normalize_code_lang(fence.group(1))
            index += 1
            code: list[str] = []
            while index < len(lines) and not _FENCE.match(lines[index]):
                code.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            text = "\n".join(code)
            if ctx.pin:
                ctx.note_pin()
                blocks.append(f"<p>{_escape(text)}</p>" if text else "<p><br></p>")
            else:
                blocks.append(f'<pre lang="{_escape(lang)}">{_escape(text)}</pre>')
            continue
        if not line.strip():
            blanks = 0
            while index < len(lines) and not lines[index].strip():
                blanks += 1
                index += 1
            if blanks >= 2 and blocks:
                blocks.append("<p><br></p>")
            continue
        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            inner = _render_inlines(heading.group(2), ctx)
            if ctx.pin:
                ctx.note_pin()
                blocks.append(f"<p>{inner}</p>")
            else:
                if level > 2:
                    ctx.warning("heading.downgraded", "超过二级的标题已按三级标题输出。")
                tag = "h2" if level == 1 else "h3"
                blocks.append(f"<{tag}>{inner}</{tag}>")
            index += 1
            continue
        if _HR.match(line):
            if ctx.pin:
                ctx.note_pin()
            else:
                blocks.append("<hr />")
            index += 1
            continue
        if _QUOTE.match(line):
            quoted: list[str] = []
            while index < len(lines) and _QUOTE.match(lines[index]):
                quoted.append(_QUOTE.match(lines[index]).group(1))  # type: ignore[union-attr]
                index += 1
            inner = "<br>".join(_render_inlines(part, ctx) for part in quoted)
            if ctx.pin:
                ctx.note_pin()
                blocks.append(f"<p>{inner}</p>")
            else:
                blocks.append(f"<blockquote>{inner}</blockquote>")
            continue
        if _UL.match(line) or _OL.match(line):
            ordered = bool(_OL.match(line))
            items: list[str] = []
            pattern = _OL if ordered else _UL
            while index < len(lines) and pattern.match(lines[index]):
                items.append(pattern.match(lines[index]).group(1))  # type: ignore[union-attr]
                index += 1
            rendered_items = [_render_inlines(item, ctx) for item in items]
            if ctx.pin:
                ctx.note_pin()
                blocks.extend(f"<p>{item}</p>" for item in rendered_items)
            else:
                tag = "ol" if ordered else "ul"
                blocks.append(f"<{tag}>{''.join(f'<li>{item}</li>' for item in rendered_items)}</{tag}>")
            continue
        if _is_table(lines, index):
            table, index = _read_table(lines, index, ctx)
            blocks.append(table)
            continue
        paragraph: list[str] = []
        while index < len(lines) and lines[index].strip() and not _starts_block(lines[index]):
            paragraph.append(lines[index].strip())
            index += 1
        blocks.append(_paragraph_html(paragraph, ctx))
    return "".join(blocks)


def _starts_block(line: str) -> bool:
    return bool(
        _FENCE.match(line)
        or _HEADING.match(line)
        or _HR.match(line)
        or _QUOTE.match(line)
        or _UL.match(line)
        or _OL.match(line)
    )


def _is_table(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines) or "|" not in lines[index]:
        return False
    return bool(re.match(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", lines[index + 1]))


def _read_table(lines: list[str], index: int, ctx: _Ctx) -> tuple[str, int]:
    if ctx.pin:
        ctx.note_pin()
        text = _escape(lines[index])
        index += 1
        while index < len(lines) and "|" in lines[index] and lines[index].strip():
            index += 1
        return f"<p>{text}</p>", index
    header = _split_row(lines[index])
    index += 2
    rows = [header]
    while index < len(lines) and "|" in lines[index] and lines[index].strip():
        rows.append(_split_row(lines[index]))
        index += 1
    html_rows: list[str] = []
    for row_index, row in enumerate(rows):
        tag = "th" if row_index == 0 else "td"
        cells = "".join(f"<{tag}>{_escape(cell)}</{tag}>" for cell in row)
        html_rows.append(f"<tr>{cells}</tr>")
    table = (
        '<table data-draft-node="block" data-draft-type="table" '
        'data-size="normal" data-row-style="normal"><tbody>'
        + "".join(html_rows)
        + "</tbody></table>"
    )
    return table, index


def _split_row(line: str) -> list[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [cell.strip() for cell in text.split("|")]


def _paragraph_html(lines: list[str], ctx: _Ctx) -> str:
    if len(lines) == 1:
        formula = _only_block_formula(lines[0])
        if formula is not None:
            if ctx.pin:
                ctx.note_pin()
                return f"<p>{_escape(lines[0])}</p>"
            return _formula_img(formula, block=True)
    inner = "<br>".join(_render_inlines(line, ctx) for line in lines)
    return f"<p>{inner}</p>" if inner else "<p><br></p>"


def _only_block_formula(line: str) -> str | None:
    match = re.fullmatch(r"\$\$([\s\S]+)\$\$", line.strip())
    if not match:
        return None
    return match.group(1)


def _render_inlines(text: str, ctx: _Ctx) -> str:
    parts: list[str] = []
    cursor = 0
    pattern = re.compile(
        r"(`[^`\n]+`)"
        r"|(\$\$[\s\S]+?\$\$)"
        r"|(\$[^\$\n]+?\$)"
        r"|(!\[[^\]]*\]\([^)\s]+\))"
        r"|(\[[^\]]+\]\([^)\s]+\))"
        r"|(\*\*[^*\n]+\*\*|__[^_\n]+__)"
        r"|(\*[^*\n]+\*|(?<![\w])_[^_\n]+_(?![\w]))"
    )
    for match in pattern.finditer(text):
        if match.start() > cursor:
            parts.append(_escape_and_topics(text[cursor:match.start()], ctx))
        token = match.group(0)
        if token.startswith("`"):
            if ctx.pin:
                ctx.note_pin()
                parts.append(_escape(token[1:-1]))
            else:
                parts.append(f"<code>{_escape(token[1:-1])}</code>")
        elif token.startswith("$$"):
            if ctx.pin:
                ctx.note_pin()
                parts.append(_escape(token))
            else:
                parts.append(_formula_img(token[2:-2], block=True))
        elif token.startswith("$"):
            if ctx.pin:
                ctx.note_pin()
                parts.append(_escape(token))
            else:
                parts.append(_formula_img(token[1:-1], block=False))
        elif token.startswith("!"):
            parts.append(_image_token(token, ctx))
        elif token.startswith("["):
            parts.append(_link_token(token, ctx))
        elif token.startswith("**") or token.startswith("__"):
            inner = token[2:-2]
            if ctx.pin:
                ctx.note_pin()
                parts.append(_render_inlines(inner, ctx))
            else:
                parts.append(f"<b>{_render_inlines(inner, ctx)}</b>")
        else:
            inner = token[1:-1]
            if ctx.pin:
                ctx.note_pin()
                parts.append(_render_inlines(inner, ctx))
            else:
                parts.append(f"<i>{_render_inlines(inner, ctx)}</i>")
        cursor = match.end()
    if cursor < len(text):
        parts.append(_escape_and_topics(text[cursor:], ctx))
    return "".join(parts)


def _escape_and_topics(text: str, ctx: _Ctx) -> str:
    if not ctx.pin or "#" not in text:
        return _escape(text)
    pieces: list[str] = []
    cursor = 0
    for match in re.finditer(r"#([^\s#<>]{1,36})#", text):
        pieces.append(_escape(text[cursor:match.start()]))
        name = f"#{match.group(1)}#"
        pieces.append(
            f'<a class="hash_tag" data-topic-name="{_escape(name)}">{_escape(name)}</a>'
        )
        cursor = match.end()
    pieces.append(_escape(text[cursor:]))
    return "".join(pieces)


def _inject_pin_topics(html: str) -> tuple[str, int]:
    return html, html.count('class="hash_tag"')


def _image_token(token: str, ctx: _Ctx) -> str:
    match = re.fullmatch(r"!\[([^\]]*)\]\(([^)\s]+)\)", token)
    if not match:
        return _escape(token)
    caption, src = match.group(1), match.group(2)
    if _DANGEROUS_URL.search(src):
        ctx.error("html.dangerous", "图片地址不受支持，已停止转换。")
        ctx.suppress = True
        return ""
    ref = _ImageRef(src=src, caption=caption)
    ctx.body_images.append(ref)
    token_id = ctx.image_seq
    ctx.image_seq += 1
    return f"ZHIHUIMG{token_id}PLACEHOLDER"


def _link_token(token: str, ctx: _Ctx) -> str:
    match = re.fullmatch(r"\[([^\]]+)\]\(([^)\s]+)\)", token)
    if not match:
        return _escape(token)
    label, href = match.group(1), match.group(2)
    if not _is_http_url(href) or _DANGEROUS_URL.search(href):
        if _DANGEROUS_URL.search(href):
            ctx.error("html.dangerous", "链接地址不受支持，已停止转换。")
            ctx.suppress = True
            return ""
        ctx.error("link.invalid", f"链接必须是 http(s) 地址：{href}")
        return _escape(label)
    safe_href = _escape(href)
    safe_label = _escape(label)
    if ctx.pin:
        return (
            f'<a href="{safe_href}" data-insert-way="force" data-draft-node="inline" '
            f'data-draft-type="text-link" data-draft-title="{safe_label}">{safe_label}</a>'
        )
    return f'<a href="{safe_href}">{safe_label}</a>'


def _formula_img(latex: str, *, block: bool) -> str:
    encoded = quote(latex, safe="-_.!~*'()")
    kind = "2" if block else "1"
    return (
        f'<img eeimg="{kind}" src="//www.zhihu.com/equation?tex={encoded}" '
        f'alt="{_escape(latex)}" />'
    )


def _render_images(html: str, ctx: _Ctx, draft: dict[str, object]) -> str:
    _resolve_images(ctx, draft)
    if ctx.pin and ctx.body_images:
        moved = [ref.resolved for ref in ctx.body_images if ref.resolved and ref.resolved.get("url")]
        if moved:
            ctx.warning("pin.body-image-moved", "想法正文不支持内嵌图片，已将正文图片移入独立媒体区。")
            existing = [
                image for image in draft["images"]
                if not any(ref.resolved is image for ref in ctx.body_images)
            ]
            draft["images"] = existing + moved
        html = re.sub(r"ZHIHUIMG\d+PLACEHOLDER", "", html)
        return html

    def replace(match: re.Match[str]) -> str:
        ref = ctx.body_images[int(match.group(1))]
        return _img_tag(ref, ctx)

    return re.sub(r"ZHIHUIMG(\d+)PLACEHOLDER", replace, html)


def _resolve_images(ctx: _Ctx, draft: dict[str, object]) -> None:
    uploaded = [item for item in draft["images"] if isinstance(item, dict)]
    unused = set(range(len(uploaded)))
    for ref in ctx.body_images:
        matched = _match_image(ref.src, uploaded, unused)
        if matched is None and _is_zhihu_image(ref.src):
            ref.resolved = {"url": ref.src, "original_url": ref.src}
            continue
        if matched is None:
            ctx.error("image.unresolved", f"正文图片还没有知乎上传结果：{ref.src or '(空)'}。请先上传后再发布。")
            continue
        unused.remove(matched)
        ref.resolved = uploaded[matched]
    if not ctx.pin:
        for index in unused:
            image = uploaded[index]
            ctx.warning("image.unused", f"已上传图片未在正文引用：{image.get('original_url') or image.get('url')}。")


def _match_image(src: str, uploaded: list[dict[str, object]], unused: set[int]) -> int | None:
    target = _norm_src(src)
    for index in list(unused):
        original = uploaded[index].get("original_url")
        if isinstance(original, str) and _norm_src(original) == target:
            return index
    for index in list(unused):
        original = uploaded[index].get("original_url")
        if not original or (isinstance(original, str) and _norm_src(original) == target):
            return index
    return None


def _img_tag(ref: _ImageRef, ctx: _Ctx) -> str:
    image = ref.resolved
    if not image or not image.get("url"):
        return ""
    url = str(image["url"])
    if not _is_zhihu_image(url):
        ctx.error("image.unsafe-url", "正文图片的发布 URL 必须是 HTTPS 知乎图片地址。")
        return ""
    caption = ref.caption or ""
    if len(caption) > LIMITS["caption_max"]:
        ctx.error("image.caption-too-long", f"图片说明超过 {LIMITS['caption_max']} 字。")
        return ""
    width = image.get("width")
    size = "small" if isinstance(width, int) and 0 < width < 343 else "normal"
    attrs = [
        f'src="{_escape(url)}"',
        f'data-caption="{_escape(caption)}"',
        f'data-size="{size}"',
    ]
    if isinstance(width, int):
        attrs.append(f'data-rawwidth="{width}"')
    height = image.get("height")
    if isinstance(height, int):
        attrs.append(f'data-rawheight="{height}"')
    if image.get("watermark") is True:
        attrs.append('data-watermark="watermark"')
    elif image.get("watermark") is False:
        attrs.append('data-watermark="original"')
    original = str(image.get("original_url") or "")
    attrs.append(
        f'data-original-src="{_escape(original)}"' if _is_zhihu_image(original) else 'data-original-src=""'
    )
    attrs.extend(['data-watermark-src=""', 'data-private-watermark-src=""'])
    return f"<img {' '.join(attrs)} />"


class _HtmlSanitizer(HTMLParser):
    def __init__(self, ctx: _Ctx) -> None:
        super().__init__(convert_charrefs=True)
        self.ctx = ctx
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, end=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, end=True)

    def handle_endtag(self, tag: str) -> None:
        if self.skip:
            self.skip -= 1
            return
        if tag in {"p", "h2", "h3", "b", "i", "ol", "ul", "li", "blockquote", "pre", "code", "sup", "a", "table", "tbody", "tr", "th", "td"}:
            if self.ctx.pin and tag in {"h2", "h3", "li", "pre"}:
                self.parts.append("</p>")
                return
            if self.ctx.pin and tag not in {"p", "a"}:
                return
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        self.parts.append(_escape_and_topics(data, self.ctx) if self.ctx.pin else _escape(data))

    def _start(self, tag: str, attrs: list[tuple[str, str | None]], *, end: bool) -> None:
        if self.skip:
            self.skip += 1
            return
        mapping = {name.lower(): value or "" for name, value in attrs}
        if tag in {"script", "iframe", "object", "embed", "svg", "style", "video", "audio"} or any(
            name.startswith("on") for name in mapping
        ):
            self.ctx.error("html.dangerous", "正文含有不允许的标签或事件属性，已停止转换。")
            self.ctx.suppress = True
            self.skip += 0 if end else 1
            return
        if tag == "br":
            self.parts.append("<br>")
            return
        if tag == "hr":
            if self.ctx.pin:
                self.ctx.note_pin()
            else:
                self.parts.append("<hr />")
            return
        if tag == "img":
            self.parts.append(self._img(mapping))
            return
        if tag == "a":
            self.parts.append(self._anchor(mapping))
            return
        if tag == "pre":
            lang = normalize_code_lang(mapping.get("lang"))
            if self.ctx.pin:
                self.ctx.note_pin()
                self.parts.append("<p>")
            else:
                self.parts.append(f'<pre lang="{_escape(lang)}">')
            return
        if tag in {"h2", "h3", "b", "i", "ol", "ul", "li", "blockquote", "code", "table", "tbody", "tr", "th", "td"}:
            if self.ctx.pin:
                self.ctx.note_pin()
                if tag in {"h2", "h3", "li"}:
                    self.parts.append("<p>")
                return
            self.parts.append(f"<{tag}>")
            return
        if tag == "p":
            self.parts.append("<p>")
            return
        if tag == "sup":
            self.parts.append(self._sup(mapping))
            return
        if tag not in {"span", "div", "font"}:
            self.ctx.warning("html.downgraded", f"不支持的标签 {tag} 已降级为文本。")
        elif tag in {"span", "div", "font"}:
            self.ctx.warning("html.downgraded", f"不支持的标签 {tag} 已去掉，文本已保留。")

    def _img(self, attrs: dict[str, str]) -> str:
        src = attrs.get("src", "").strip()
        if _DANGEROUS_URL.search(src):
            self.ctx.error("html.dangerous", "图片地址不受支持，已停止转换。")
            self.ctx.suppress = True
            return ""
        eeimg = attrs.get("eeimg", "")
        if eeimg in {"1", "2"}:
            alt = attrs.get("alt", "")
            if src and not re.match(r"^(https?:)?//www\.zhihu\.com/equation\?", src, re.IGNORECASE):
                return _formula_img(alt, block=eeimg == "2")
            return f'<img eeimg="{eeimg}" src="{_escape(src)}" alt="{_escape(alt)}" />'
        ref = _ImageRef(src=src, caption=attrs.get("data-caption") or attrs.get("alt") or "")
        self.ctx.body_images.append(ref)
        token = self.ctx.image_seq
        self.ctx.image_seq += 1
        return f"ZHIHUIMG{token}PLACEHOLDER"

    def _anchor(self, attrs: dict[str, str]) -> str:
        href = attrs.get("href", "").strip()
        if not _is_http_url(href) or _DANGEROUS_URL.search(href):
            self.ctx.error("html.dangerous" if _DANGEROUS_URL.search(href) else "link.invalid", "链接地址不受支持。")
            if _DANGEROUS_URL.search(href):
                self.ctx.suppress = True
            return ""
        classes = set(attrs.get("class", "").split())
        if "hash_tag" in classes or "zed-topic" in classes:
            name = attrs.get("data-topic-name") or ""
            extra = f' data-topic-id="{_escape(attrs["data-topic-id"])}"' if attrs.get("data-topic-id") else ""
            return f'<a class="hash_tag" data-topic-name="{_escape(name)}"{extra}>'
        if self.ctx.pin or attrs.get("data-draft-type") == "text-link":
            title = _escape(attrs.get("data-draft-title") or "")
            return (
                f'<a href="{_escape(href)}" data-insert-way="force" data-draft-node="inline" '
                f'data-draft-type="text-link" data-draft-title="{title}">'
            )
        if attrs.get("data-draft-type") == "link-card":
            return (
                f'<a href="{_escape(href)}" data-draft-node="block" data-draft-type="link-card" '
                f'data-draft-title="{_escape(attrs.get("data-draft-title", ""))}" '
                f'data-draft-cover="{_escape(attrs.get("data-draft-cover", ""))}">'
            )
        return f'<a href="{_escape(href)}">'

    def _sup(self, attrs: dict[str, str]) -> str:
        if attrs.get("data-draft-type") != "reference":
            self.ctx.warning("unsupported.sup", "非注释的 sup 已降级为文本。")
            return ""
        if self.ctx.content_type != "article":
            self.ctx.error("reference.unsupported", "提问和想法不支持注释。")
            return ""
        text = attrs.get("data-text", "")
        url = attrs.get("data-url", "")
        if not text and not url:
            self.ctx.error("reference.empty", "注释需要 data-text 或 data-url。")
            return ""
        if url and not _is_http_url(url):
            self.ctx.error("reference.bad-url", "注释链接必须是 http(s)。")
            return ""
        numero = attrs.get("data-numero", "")
        return (
            '<sup data-text="%s" data-url="%s" data-draft-node="inline" '
            'data-draft-type="reference" data-numero="%s">'
            % (_escape(text), _escape(url), _escape(numero))
        )


def _sanitize_html(body: str, ctx: _Ctx) -> str:
    parser = _HtmlSanitizer(ctx)
    parser.feed(body)
    parser.close()
    return "" if ctx.suppress else "".join(parser.parts)


def _topic_tokens(values: object, maximum: int) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    if not isinstance(values, list):
        return found
    for value in values:
        token = _zhihu_path(str(value), _TOPIC_URL)
        if not token or token in seen:
            continue
        seen.add(token)
        found.append({"topic_id": "", "topic_token": token, "topic_name": ""})
        if len(found) >= maximum:
            break
    return found


def _ring_id(value: object) -> dict[str, str] | None:
    if not isinstance(value, str):
        return None
    ring_id = _zhihu_path(value, _RING_URL)
    if not ring_id:
        return None
    return {"ring_id": ring_id, "ring_name": ""}


def _zhihu_path(value: str, pattern: re.Pattern[str]) -> str:
    try:
        parts = urlsplit(value)
    except ValueError:
        return ""
    if parts.scheme != "https" or parts.username or parts.password or parts.port:
        return ""
    if parts.hostname != "www.zhihu.com":
        return ""
    match = pattern.match(parts.path or "")
    return match.group(1) if match else ""


def _is_http_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return parts.scheme in {"http", "https"} and bool(parts.hostname) and not parts.username


def _is_zhihu_image(value: str) -> bool:
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and not parts.username
        and not parts.password
        and bool(parts.hostname)
        and bool(_ZHIHU_HOST.match(parts.hostname))
    )


def _norm_src(value: str) -> str:
    text = value.strip().replace("\\", "/")
    text = re.sub(r"^file://", "", text, flags=re.IGNORECASE)
    return text.lower()


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _pick(mapping: Mapping[str, object], *names: str) -> object:
    for name in names:
        if name in mapping:
            return mapping[name]
    return None
