"""Markdown parser for Obsidian notes — frontmatter, wikilinks, tags, chunking."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?\n?)---\s*\n?", re.DOTALL)


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from Obsidian note content.

    Returns:
        (metadata_dict, body_without_frontmatter)
        If no frontmatter is found, returns ({}, content).
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}, content

    raw_yaml = match.group(1)
    try:
        metadata = yaml.safe_load(raw_yaml) or {}
    except yaml.YAMLError:
        metadata = {}

    if not isinstance(metadata, dict):
        metadata = {}

    body = content[match.end():]
    return metadata, body


# ---------------------------------------------------------------------------
# Wikilinks
# ---------------------------------------------------------------------------

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
_WIKILINK_DISPLAY_RE = re.compile(r"\[\[([^\]|]+)\|([^\]]+)\]\]|\[\[([^\]]+)\]\]")


def strip_wikilink_brackets(text: str) -> str:
    """Replace [[Target|Alias]] with Alias, and [[Target]] with Target.

    Removes the [[ ]] syntax that is meaningless to embedding models,
    keeping only the human-readable text.
    """
    def _replace(m: re.Match) -> str:
        if m.group(2):  # [[Target|Alias]] -> Alias
            return m.group(2)
        return m.group(3)  # [[Target]] -> Target
    return _WIKILINK_DISPLAY_RE.sub(_replace, text)


def extract_wikilinks(text: str) -> list[str]:
    """Extract unique wikilink targets from text (order-preserving dedup).

    [[Target]]        -> ["Target"]
    [[Target|Alias]]  -> ["Target"]  (alias discarded)
    [[Path/Target]]   -> ["Path/Target"]
    """
    seen: set[str] = set()
    result: list[str] = []
    for m in _WIKILINK_RE.finditer(text):
        target = m.group(1).strip()
        if target not in seen:
            seen.add(target)
            result.append(target)
    return result


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

_INLINE_TAG_RE = re.compile(r"(?:^|\s)#([a-zA-Z][\w/-]*)", re.MULTILINE)


def extract_tags(frontmatter: dict, body: str) -> list[str]:
    """Collect tags from frontmatter and inline #tags.

    - frontmatter["tags"] may be a list or a single string
    - Inline tags: #tag, #nested/tag  (no match for #123, ## headings, URLs)
    - Returns sorted, deduplicated list
    """
    tags: set[str] = set()

    # Frontmatter tags
    fm_tags = frontmatter.get("tags", [])
    if isinstance(fm_tags, str):
        fm_tags = [fm_tags]
    if isinstance(fm_tags, list):
        for t in fm_tags:
            if t:
                tags.add(str(t).strip())

    # Inline tags
    for m in _INLINE_TAG_RE.finditer(body):
        tags.add(m.group(1))

    return sorted(tags)


# ---------------------------------------------------------------------------
# ParsedNote
# ---------------------------------------------------------------------------

@dataclass
class ParsedNote:
    path: str           # relative path inside vault
    title: str          # filename without .md (or frontmatter title)
    content_hash: str   # SHA-256 of entire raw file content
    frontmatter: dict
    tags: list[str]
    wikilinks: list[str]
    body: str           # content without frontmatter


def parse_note(file_path: Path, vault_root: Path) -> ParsedNote:
    """Read and parse a single Obsidian note.

    Args:
        file_path:  Absolute path to the .md file.
        vault_root: Absolute path to the vault root (for relative path calc).
    """
    raw = file_path.read_text(encoding="utf-8-sig")  # handles BOM on Windows

    content_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    relative_path = file_path.relative_to(vault_root).as_posix()

    frontmatter, body = parse_frontmatter(raw)

    title = frontmatter.get("title") or file_path.stem

    wikilinks = extract_wikilinks(body)
    tags = extract_tags(frontmatter, body)

    return ParsedNote(
        path=relative_path,
        title=title,
        content_hash=content_hash,
        frontmatter=frontmatter,
        tags=tags,
        wikilinks=wikilinks,
        body=body,
    )


# ---------------------------------------------------------------------------
# Chunk
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    content: str        # chunk text including context header
    heading_path: str   # e.g. "# Über mich > ## Tech-Stack"
    chunk_index: int    # position within the note


# Matches H2–H6 headings at the start of a line
_HEADING_SPLIT_RE = re.compile(r"^(#{2,6})\s+(.+)", re.MULTILINE)


def _count_tokens(text: str) -> int:
    """Simple whitespace-based token count."""
    return len(text.split())


def _build_context_header(parsed: ParsedNote) -> str:
    """Build the semantic context header prepended to every chunk."""
    parts = parsed.path.replace("\\", "/").split("/")
    folder = parts[0] if len(parts) > 1 else "Root"
    tags_str = ", ".join(parsed.tags) if parsed.tags else ""
    header = f"[Title: {parsed.title} | Folder: {folder}"
    if tags_str:
        header += f" | Tags: {tags_str}"
    header += "]"
    return header


def _update_heading_path(current_path: list[tuple[int, str]], level: int, heading: str) -> list[tuple[int, str]]:
    """Return updated heading stack after encountering a heading of given level."""
    # Remove entries at same or deeper level
    new_path = [(lvl, txt) for lvl, txt in current_path if lvl < level]
    new_path.append((level, heading))
    return new_path


def _heading_path_str(path: list[tuple[int, str]]) -> str:
    if not path:
        return ""
    return " > ".join("#" * lvl + " " + txt for lvl, txt in path)


def _split_section(text: str, max_tokens: int, overlap_tokens: int, prev_tail: str) -> list[str]:
    """Split a large section at double-newlines, applying overlap."""
    paragraphs = re.split(r"\n\n+", text.strip())
    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = _count_tokens(prev_tail)

    for para in paragraphs:
        para_tokens = _count_tokens(para)
        if current_tokens + para_tokens > max_tokens and current_parts:
            chunk_text = "\n\n".join(current_parts)
            chunks.append(chunk_text)
            # build overlap from tail of current chunk
            tail_words = chunk_text.split()[-overlap_tokens:]
            current_parts = [" ".join(tail_words), para] if tail_words else [para]
            current_tokens = _count_tokens("\n\n".join(current_parts))
        else:
            current_parts.append(para)
            current_tokens += para_tokens

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks if chunks else [text]


def chunk_note(parsed: ParsedNote, max_tokens: int = 1000, overlap_tokens: int = 100) -> list[Chunk]:
    """Split a ParsedNote into semantically meaningful Chunks.

    Splitting rules:
    - Split at H2–H6 headings (## to ######)
    - H1 headings are NOT split points (treated as part of the section text)
    - Sections > max_tokens: split at double-newlines
    - Sections < 50 tokens: merge with next section
    - Overlap: prepend last overlap_tokens words from previous chunk
    - Empty chunks are skipped
    """
    context_header = _build_context_header(parsed)
    body = parsed.body

    # Split body into (heading_line, section_text) pairs
    # heading_line is None for the intro section before first heading
    sections: list[tuple[str | None, int, str]] = []  # (heading_text, heading_level, body_text)

    last_end = 0
    heading_stack: list[tuple[int, str]] = []
    current_stack_at_section: list[list[tuple[int, str]]] = []

    # Find all H2–H6 headings and collect sections
    raw_sections: list[tuple[list[tuple[int, str]], str]] = []
    prev_pos = 0
    prev_stack: list[tuple[int, str]] = []

    for m in _HEADING_SPLIT_RE.finditer(body):
        hashes = m.group(1)
        level = len(hashes)
        heading_text = m.group(2).strip()

        # Text before this heading belongs to the previous section
        section_text = body[prev_pos:m.start()]
        raw_sections.append((list(prev_stack), section_text))

        prev_stack = _update_heading_path(prev_stack, level, heading_text)
        prev_pos = m.end() + 1  # skip the newline after the heading line

    # Remaining text after last heading
    raw_sections.append((list(prev_stack), body[prev_pos:]))

    # Now build chunks, handling merging of short sections and splitting of long ones
    pending_sections: list[tuple[list[tuple[int, str]], str]] = []
    for stack, text in raw_sections:
        stripped = text.strip()
        if not stripped:
            continue
        pending_sections.append((stack, stripped))

    # Merge short sections with next
    merged: list[tuple[list[tuple[int, str]], str]] = []
    i = 0
    while i < len(pending_sections):
        stack, text = pending_sections[i]
        tokens = _count_tokens(text)
        if tokens < 50 and i + 1 < len(pending_sections):
            # merge with next
            next_stack, next_text = pending_sections[i + 1]
            pending_sections[i + 1] = (next_stack, text + "\n\n" + next_text)
            i += 1
            continue
        merged.append((stack, text))
        i += 1

    # Build final chunks
    chunks: list[Chunk] = []
    prev_chunk_tail = ""

    for stack, text in merged:
        heading_path = _heading_path_str(stack)
        tokens = _count_tokens(text)

        if tokens > max_tokens:
            # Split at paragraphs
            sub_texts = _split_section(text, max_tokens, overlap_tokens, prev_chunk_tail)
        else:
            sub_texts = [text]

        # Only apply outer overlap for non-split sections.
        # _split_section handles overlap internally via prev_tail.
        apply_outer_overlap = len(sub_texts) == 1

        for sub_text in sub_texts:
            sub_text = sub_text.strip()
            if not sub_text:
                continue

            # Prepend overlap from previous chunk
            overlap_prefix = ""
            if apply_outer_overlap and prev_chunk_tail:
                tail_words = prev_chunk_tail.split()
                if len(tail_words) > overlap_tokens:
                    tail_words = tail_words[-overlap_tokens:]
                if tail_words:
                    overlap_prefix = " ".join(tail_words) + "\n\n"

            # Strip [[wikilink]] brackets — meaningless to embedding models
            clean_text = strip_wikilink_brackets(overlap_prefix + sub_text)
            full_content = context_header + "\n" + clean_text

            chunks.append(Chunk(
                content=full_content,
                heading_path=heading_path,
                chunk_index=len(chunks),
            ))

            prev_chunk_tail = sub_text

    return chunks
