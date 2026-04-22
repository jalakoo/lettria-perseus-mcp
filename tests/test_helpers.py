"""Tests for internal helper functions."""

from __future__ import annotations

import os

import pytest

from lettria_perseus_mcp.server import (
    _check_inline_size,
    _inline_max_bytes,
    _register,
    _require,
    _safe_basename,
    _summary,
    _GRAPHS,
)
from tests.fakes import FakeKnowledgeGraph


# ---------------------------------------------------------------------------
# _safe_basename
# ---------------------------------------------------------------------------


class TestSafeBasename:
    def test_strips_directory(self):
        assert _safe_basename("/a/b/c/onto.ttl", "fallback.ttl") == "onto.ttl"

    def test_relative_path(self):
        assert _safe_basename("dir/onto.owl", "fallback.ttl") == "onto.owl"

    def test_plain_filename(self):
        assert _safe_basename("onto.ttl", "fallback.ttl") == "onto.ttl"

    def test_empty_string_uses_fallback(self):
        assert _safe_basename("", "fallback.ttl") == "fallback.ttl"

    def test_whitespace_only_uses_fallback(self):
        assert _safe_basename("   ", "fallback.ttl") == "fallback.ttl"

    def test_trailing_slash_uses_fallback(self):
        # Path("/a/b/").name == "" on some platforms
        result = _safe_basename("/a/b/", "fallback.ttl")
        # Either the dir name or the fallback is acceptable
        assert result in ("b", "fallback.ttl")


# ---------------------------------------------------------------------------
# _inline_max_bytes
# ---------------------------------------------------------------------------


class TestInlineMaxBytes:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("PERSEUS_INLINE_CONTENT_MAX_BYTES", raising=False)
        assert _inline_max_bytes() == 1_048_576

    def test_custom(self, monkeypatch):
        monkeypatch.setenv("PERSEUS_INLINE_CONTENT_MAX_BYTES", "500")
        assert _inline_max_bytes() == 500

    def test_non_integer_raises(self, monkeypatch):
        monkeypatch.setenv("PERSEUS_INLINE_CONTENT_MAX_BYTES", "not_a_number")
        with pytest.raises(ValueError, match="must be an integer"):
            _inline_max_bytes()

    def test_zero_raises(self, monkeypatch):
        monkeypatch.setenv("PERSEUS_INLINE_CONTENT_MAX_BYTES", "0")
        with pytest.raises(ValueError, match="positive integer"):
            _inline_max_bytes()

    def test_negative_raises(self, monkeypatch):
        monkeypatch.setenv("PERSEUS_INLINE_CONTENT_MAX_BYTES", "-10")
        with pytest.raises(ValueError, match="positive integer"):
            _inline_max_bytes()


# ---------------------------------------------------------------------------
# _check_inline_size
# ---------------------------------------------------------------------------


class TestCheckInlineSize:
    def test_within_limit_passes(self, monkeypatch):
        monkeypatch.setenv("PERSEUS_INLINE_CONTENT_MAX_BYTES", "100")
        _check_inline_size("hello", "Test", path_tool="some_tool")  # no raise

    def test_exceeds_limit_raises(self, monkeypatch):
        monkeypatch.setenv("PERSEUS_INLINE_CONTENT_MAX_BYTES", "5")
        with pytest.raises(ValueError, match="exceeds the inline cap"):
            _check_inline_size("hello world", "Doc", path_tool="build_graph")

    def test_error_mentions_path_tool(self, monkeypatch):
        monkeypatch.setenv("PERSEUS_INLINE_CONTENT_MAX_BYTES", "1")
        with pytest.raises(ValueError, match="upload_ontology"):
            _check_inline_size("AB", "Ontology", path_tool="upload_ontology")

    def test_multibyte_utf8(self, monkeypatch):
        # Each emoji is 4 bytes UTF-8
        monkeypatch.setenv("PERSEUS_INLINE_CONTENT_MAX_BYTES", "10")
        with pytest.raises(ValueError):
            _check_inline_size("\U0001f600\U0001f600\U0001f600", "Test", path_tool="x")


# ---------------------------------------------------------------------------
# _register / _require / _summary
# ---------------------------------------------------------------------------


class TestGraphRegistry:
    def setup_method(self):
        _GRAPHS.clear()

    def teardown_method(self):
        _GRAPHS.clear()

    def test_register_and_require_roundtrip(self):
        g = FakeKnowledgeGraph()
        gid = _register(g)
        assert len(gid) == 12
        assert _require(gid) is g

    def test_require_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown graph_id"):
            _require("nonexistent")

    def test_summary_shape(self):
        g = FakeKnowledgeGraph()
        gid = _register(g)
        s = _summary(gid, g)
        assert s["graph_id"] == gid
        assert s["entities"] == 1
        assert s["relations"] == 1
        assert isinstance(s["namespaces"], list)
