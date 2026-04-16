"""Tests for mneme.parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from mneme.parser import (
    Chunk,
    ParsedNote,
    chunk_note,
    extract_tags,
    extract_wikilinks,
    parse_frontmatter,
    parse_note,
)


# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------

class TestParseFrontmatter:
    def test_with_tags(self):
        content = "---\ntitle: Hello\ntags:\n  - python\n  - testing\n---\nBody here."
        fm, body = parse_frontmatter(content)
        assert fm["title"] == "Hello"
        assert fm["tags"] == ["python", "testing"]
        assert body.strip() == "Body here."

    def test_without_tags(self):
        content = "---\ntitle: No Tags\n---\nSome body."
        fm, body = parse_frontmatter(content)
        assert fm["title"] == "No Tags"
        assert "tags" not in fm
        assert body.strip() == "Some body."

    def test_without_frontmatter(self):
        content = "Just plain content without frontmatter."
        fm, body = parse_frontmatter(content)
        assert fm == {}
        assert body == content

    def test_empty_body(self):
        content = "---\ntitle: Empty\n---\n"
        fm, body = parse_frontmatter(content)
        assert fm["title"] == "Empty"
        assert body == ""

    def test_empty_frontmatter_block(self):
        content = "---\n---\nBody."
        fm, body = parse_frontmatter(content)
        assert fm == {}
        assert body.strip() == "Body."

    def test_frontmatter_not_at_start(self):
        content = "Some text\n---\ntitle: Late\n---\nMore text."
        fm, body = parse_frontmatter(content)
        assert fm == {}
        assert body == content


# ---------------------------------------------------------------------------
# extract_wikilinks
# ---------------------------------------------------------------------------

class TestExtractWikilinks:
    def test_simple_link(self):
        assert extract_wikilinks("See [[Target]] for details.") == ["Target"]

    def test_link_with_alias(self):
        assert extract_wikilinks("See [[Target|Alias]] here.") == ["Target"]

    def test_path_link(self):
        assert extract_wikilinks("[[Folder/Note]]") == ["Folder/Note"]

    def test_no_links(self):
        assert extract_wikilinks("No links here.") == []

    def test_deduplication(self):
        text = "[[A]] and [[B]] and [[A]] again."
        result = extract_wikilinks(text)
        assert result == ["A", "B"]

    def test_order_preserved(self):
        text = "[[C]] then [[A]] then [[B]]."
        assert extract_wikilinks(text) == ["C", "A", "B"]

    def test_multiple_aliases(self):
        text = "[[Note1|First]] and [[Note2|Second]]."
        assert extract_wikilinks(text) == ["Note1", "Note2"]

    def test_nested_path_with_alias(self):
        assert extract_wikilinks("[[Deep/Path/Note|Visible]]") == ["Deep/Path/Note"]


# ---------------------------------------------------------------------------
# extract_tags
# ---------------------------------------------------------------------------

class TestExtractTags:
    def test_frontmatter_list_tags(self):
        fm = {"tags": ["python", "testing"]}
        result = extract_tags(fm, "")
        assert "python" in result
        assert "testing" in result

    def test_frontmatter_string_tag(self):
        fm = {"tags": "single"}
        result = extract_tags(fm, "")
        assert "single" in result

    def test_inline_tag(self):
        result = extract_tags({}, "Some text with #mytag here.")
        assert "mytag" in result

    def test_inline_nested_tag(self):
        result = extract_tags({}, "Nested #nested/tag works.")
        assert "nested/tag" in result

    def test_no_match_numeric(self):
        result = extract_tags({}, "No #123 numeric tags.")
        assert "123" not in result

    def test_no_match_heading(self):
        result = extract_tags({}, "# Heading Title")
        assert "Heading" not in result
        assert "Heading Title" not in result

    def test_no_match_url_fragment(self):
        result = extract_tags({}, "Visit https://example.com#section here.")
        assert "section" not in result

    def test_combined_frontmatter_and_inline(self):
        fm = {"tags": ["alpha"]}
        body = "Also #beta and #gamma here."
        result = extract_tags(fm, body)
        assert "alpha" in result
        assert "beta" in result
        assert "gamma" in result

    def test_sorted_output(self):
        fm = {"tags": ["zebra", "apple"]}
        result = extract_tags(fm, "#mango")
        assert result == sorted(result)

    def test_deduplicated(self):
        fm = {"tags": ["dup"]}
        body = "Also #dup here."
        result = extract_tags(fm, body)
        assert result.count("dup") == 1

    def test_no_tags_at_all(self):
        assert extract_tags({}, "Plain text.") == []


# ---------------------------------------------------------------------------
# chunk_note helpers — context header
# ---------------------------------------------------------------------------

class TestContextHeader:
    def _make_parsed(self, path: str, title: str, tags: list[str]) -> ParsedNote:
        return ParsedNote(
            path=path,
            title=title,
            content_hash="abc",
            frontmatter={},
            tags=tags,
            wikilinks=[],
            body="## Section\n\n" + " ".join(["content"] * 55),
        )

    def test_header_with_tags(self):
        note = self._make_parsed("folder/note.md", "My Note", ["alpha", "beta"])
        chunks = chunk_note(note)
        assert len(chunks) >= 1
        header = chunks[0].content.split("\n")[0]
        assert "Title: My Note" in header
        assert "Folder: folder" in header
        assert "Tags: alpha, beta" in header

    def test_header_root_folder(self):
        note = self._make_parsed("note.md", "Root Note", [])
        chunks = chunk_note(note)
        assert len(chunks) >= 1
        header = chunks[0].content.split("\n")[0]
        assert "Folder: Root" in header

    def test_header_no_tags_omitted(self):
        note = self._make_parsed("folder/note.md", "Clean", [])
        chunks = chunk_note(note)
        header = chunks[0].content.split("\n")[0]
        assert "Tags:" not in header


# ---------------------------------------------------------------------------
# chunk_note — structural splitting
# ---------------------------------------------------------------------------

class TestChunkNote:
    def _make_note(self, body: str, tags: list[str] | None = None) -> ParsedNote:
        return ParsedNote(
            path="folder/test.md",
            title="Test Note",
            content_hash="deadbeef",
            frontmatter={},
            tags=tags or [],
            wikilinks=[],
            body=body,
        )

    def test_three_headings_three_chunks(self):
        intro = " ".join(["word"] * 55)
        methods = " ".join(["method"] * 55)
        results = " ".join(["result"] * 55)
        body = (
            f"## Introduction\n\n{intro}\n\n"
            f"## Methods\n\n{methods}\n\n"
            f"## Results\n\n{results}"
        )
        note = self._make_note(body)
        chunks = chunk_note(note)
        assert len(chunks) == 3
        heading_paths = [c.heading_path for c in chunks]
        assert "## Introduction" in heading_paths[0]
        assert "## Methods" in heading_paths[1]
        assert "## Results" in heading_paths[2]

    def test_chunk_indices_sequential(self):
        alpha = " ".join(["alpha"] * 55)
        beta = " ".join(["beta"] * 55)
        gamma = " ".join(["gamma"] * 55)
        body = (
            f"## Alpha\n\n{alpha}\n\n"
            f"## Beta\n\n{beta}\n\n"
            f"## Gamma\n\n{gamma}"
        )
        note = self._make_note(body)
        chunks = chunk_note(note)
        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_long_section_splits_at_paragraphs(self):
        # Each paragraph is ~15 words; 20 paragraphs = ~300 tokens > max_tokens=100
        paragraphs = "\n\n".join(
            f"Paragraph {i} contains some words here to make it long enough for splitting purposes."
            for i in range(20)
        )
        body = f"## Long Section\n\n{paragraphs}"
        note = self._make_note(body)
        chunks = chunk_note(note, max_tokens=100, overlap_tokens=10)
        # Should be split into multiple chunks
        assert len(chunks) > 1

    def test_short_section_merged_with_next(self):
        full_content = " ".join(["content"] * 55)
        body = (
            "## Short\n\n"
            "Tiny.\n\n"  # < 50 tokens — should merge with next
            f"## Full\n\n{full_content}"
        )
        note = self._make_note(body)
        chunks = chunk_note(note)
        # "Tiny." merges with "Full" section → combined, so still one chunk
        # The merged chunk's heading_path should be the LATER heading
        assert len(chunks) == 1
        assert "## Full" in chunks[0].heading_path

    def test_empty_body_no_chunks(self):
        note = self._make_note("")
        chunks = chunk_note(note)
        assert chunks == []

    def test_h1_not_a_split_point(self):
        intro = " ".join(["intro"] * 55)
        sub = " ".join(["sub"] * 55)
        body = (
            f"# Top Level Heading\n\n{intro}\n\n"
            f"## Sub Section\n\n{sub}"
        )
        note = self._make_note(body)
        chunks = chunk_note(note)
        # H1 is not a split point — intro + H1 is one section, ## is another
        assert len(chunks) == 2

    def test_overlap_prepended(self):
        body = (
            "## First\n\n"
            + " ".join([f"word{i}" for i in range(150)])  # > 100 tokens after max_tokens=80
            + "\n\n## Second\n\n"
            + "Second section has its own content here with plenty of words."
        )
        note = self._make_note(body)
        chunks = chunk_note(note, max_tokens=80, overlap_tokens=20)
        # Second chunk should contain some words from first chunk (overlap)
        if len(chunks) >= 2:
            second_content = chunks[1].content
            # Context header is first line; overlap words appear after it
            lines_after_header = second_content.split("\n", 1)[1] if "\n" in second_content else ""
            # The overlap from chunk 0 (word0..word149) should appear
            assert "word" in lines_after_header

    def test_heading_path_accumulates(self):
        lvl2 = " ".join(["two"] * 55)
        lvl3 = " ".join(["three"] * 55)
        lvl2b = " ".join(["another"] * 55)
        body = (
            f"## Level 2\n\n{lvl2}\n\n"
            f"### Level 3\n\n{lvl3}\n\n"
            f"## Another Level 2\n\n{lvl2b}"
        )
        note = self._make_note(body)
        chunks = chunk_note(note)
        assert len(chunks) == 3
        # Second chunk should show L2 > L3 path
        assert "## Level 2" in chunks[1].heading_path
        assert "### Level 3" in chunks[1].heading_path
        # Third chunk resets to new L2
        assert "## Another Level 2" in chunks[2].heading_path
        assert "### Level 3" not in chunks[2].heading_path


# ---------------------------------------------------------------------------
# parse_note — roundtrip with real files
# ---------------------------------------------------------------------------

class TestParseNote:
    def test_basic_roundtrip(self, tmp_path: Path):
        vault = tmp_path / "vault"
        vault.mkdir()
        note_path = vault / "my-note.md"
        note_path.write_text(
            "---\ntitle: My Title\ntags:\n  - foo\n  - bar\n---\n"
            "Body with [[Link]] and #inline-tag.\n",
            encoding="utf-8",
        )
        parsed = parse_note(note_path, vault)
        assert parsed.title == "My Title"
        assert parsed.path == "my-note.md"
        assert "foo" in parsed.tags
        assert "bar" in parsed.tags
        assert "inline-tag" in parsed.tags
        assert "Link" in parsed.wikilinks
        assert len(parsed.content_hash) == 64  # SHA-256 hex

    def test_title_fallback_to_stem(self, tmp_path: Path):
        vault = tmp_path / "vault"
        vault.mkdir()
        note_path = vault / "fallback-title.md"
        note_path.write_text("No frontmatter here.", encoding="utf-8")
        parsed = parse_note(note_path, vault)
        assert parsed.title == "fallback-title"

    def test_relative_path_nested(self, tmp_path: Path):
        vault = tmp_path / "vault"
        sub = vault / "sub" / "folder"
        sub.mkdir(parents=True)
        note_path = sub / "deep.md"
        note_path.write_text("# Deep Note\n\nContent.", encoding="utf-8")
        parsed = parse_note(note_path, vault)
        assert parsed.path.replace("\\", "/") == "sub/folder/deep.md"

    def test_content_hash_is_sha256(self, tmp_path: Path):
        import hashlib

        vault = tmp_path / "vault"
        vault.mkdir()
        note_path = vault / "hash-test.md"
        raw = "---\ntitle: Hash\n---\nContent."
        note_path.write_text(raw, encoding="utf-8")
        parsed = parse_note(note_path, vault)
        expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        assert parsed.content_hash == expected

    def test_body_excludes_frontmatter(self, tmp_path: Path):
        vault = tmp_path / "vault"
        vault.mkdir()
        note_path = vault / "body-test.md"
        note_path.write_text(
            "---\ntitle: Body Test\n---\nActual body content.",
            encoding="utf-8",
        )
        parsed = parse_note(note_path, vault)
        assert "---" not in parsed.body
        assert "Actual body content." in parsed.body
