"""Markdown: frontmatter YAML + blocos por heading/parágrafo/tabela."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from ..models import Block, ParsedDocument
from ..utils import clean_text, nfc

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_FENCE = re.compile(r"^\s*(```|~~~)")


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.split("\n")
    for i in range(1, min(len(lines), 200)):
        if lines[i].strip() == "---":
            raw = "\n".join(lines[1:i])
            try:
                data = yaml.safe_load(raw) or {}
            except yaml.YAMLError:
                data = {}
            if not isinstance(data, dict):
                data = {}
            return data, "\n".join(lines[i + 1 :])
    return {}, text


def _strip_md_heading(text: str) -> str:
    return re.sub(r"[*_`]+", "", text).strip()


def parse_markdown_text(text: str, fallback_title: str) -> ParsedDocument:
    text = nfc(text).replace("\r\n", "\n")
    fm, body = split_frontmatter(text)

    blocks: list[Block] = []
    stack: list[tuple[int, str]] = []  # (nível, título)
    buf: list[str] = []
    buf_kind = "paragraph"
    in_fence = False
    first_h1: str | None = None

    def heading_path() -> list[str]:
        return [t for _, t in stack]

    def flush() -> None:
        nonlocal buf, buf_kind
        content = clean_text("\n".join(buf))
        if content:
            blocks.append(Block(text=content, heading_path=heading_path(), kind=buf_kind))
        buf, buf_kind = [], "paragraph"

    for line in body.split("\n"):
        if _FENCE.match(line):
            if not in_fence:
                flush()
                buf_kind = "code"
            buf.append(line)
            in_fence = not in_fence
            if not in_fence:
                flush()
            continue
        if in_fence:
            buf.append(line)
            continue

        m = _HEADING.match(line)
        if m:
            flush()
            level, title = len(m.group(1)), _strip_md_heading(m.group(2))
            if level == 1 and first_h1 is None:
                first_h1 = title
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            continue

        stripped = line.strip()
        is_table = stripped.startswith("|")
        if not stripped:
            flush()
            continue
        if stripped in ("---", "***", "___"):
            flush()
            continue
        if is_table and buf_kind != "table":
            flush()
            buf_kind = "table"
        elif not is_table and buf_kind == "table":
            flush()
        buf.append(_IMAGE.sub(lambda mm: mm.group(1), line))
    flush()

    title = str(fm.get("titulo") or fm.get("title") or first_h1 or fallback_title)
    return ParsedDocument(title=title, format="md", blocks=blocks, metadata={"frontmatter": fm} if fm else {})


def parse_markdown(path: Path) -> ParsedDocument:
    return parse_markdown_text(path.read_text(encoding="utf-8", errors="replace"), path.stem)
