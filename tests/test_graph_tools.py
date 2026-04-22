"""Tests for graph building, registry, and export tools."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.fakes import FakeKnowledgeGraph, FakeOntology
from lettria_perseus_mcp.server import (
    build_graph,
    build_graph_from_text,
    interlink_graphs,
    list_local_graphs,
    get_graph_summary,
    get_graph_entities,
    get_graph_relations,
    forget_graph,
    forget_all_graphs,
    export_graph_ttl,
    export_graph_cql,
    _register,
    _GRAPHS,
)


# ---------------------------------------------------------------------------
# build_graph
# ---------------------------------------------------------------------------


class TestBuildGraph:
    def setup_method(self):
        _GRAPHS.clear()

    def teardown_method(self):
        _GRAPHS.clear()

    async def test_basic(self, mock_perseus):
        result = await build_graph(file_paths=["/tmp/doc.txt"])
        assert result["count"] == 1
        assert "graph_id" in result["graphs"][0]
        mock_perseus["build_graph_async"].assert_awaited_once()

    async def test_with_ontology_path(self, mock_perseus):
        await build_graph(
            file_paths=["/tmp/doc.txt"], ontology_path="/tmp/onto.ttl"
        )
        call_kwargs = mock_perseus["build_graph_async"].call_args.kwargs
        assert call_kwargs["ontology_path"] == "/tmp/onto.ttl"

    async def test_graphs_registered(self, mock_perseus):
        result = await build_graph(file_paths=["/tmp/doc.txt"])
        gid = result["graphs"][0]["graph_id"]
        assert gid in _GRAPHS


# ---------------------------------------------------------------------------
# build_graph_from_text
# ---------------------------------------------------------------------------


class TestBuildGraphFromText:
    def setup_method(self):
        _GRAPHS.clear()

    def teardown_method(self):
        _GRAPHS.clear()

    async def test_basic(self, mock_perseus):
        result = await build_graph_from_text(content="Hello world.")
        assert result["count"] == 1

    async def test_temp_file_has_correct_content(self, mock_perseus):
        captured_paths: list[str] = []

        async def capture(*, file_paths, ontology_path=None, **kw):
            captured_paths.extend(file_paths)
            # File should exist at call time
            assert Path(file_paths[0]).read_text() == "Hello world."
            return [FakeKnowledgeGraph()]

        mock_perseus["build_graph_async"].side_effect = capture
        await build_graph_from_text(content="Hello world.")
        assert len(captured_paths) == 1

    async def test_inline_ontology_written(self, mock_perseus):
        ttl = "@prefix ex: <http://example.org/> .\nex:A a ex:Class .\n"

        async def capture(*, file_paths, ontology_path=None, **kw):
            assert ontology_path is not None
            assert Path(ontology_path).read_text() == ttl
            assert ontology_path.endswith("ontology.ttl")
            return [FakeKnowledgeGraph()]

        mock_perseus["build_graph_async"].side_effect = capture
        await build_graph_from_text(content="Some text", ontology_ttl=ttl)

    async def test_size_limit_on_content(self, mock_perseus, monkeypatch):
        monkeypatch.setenv("PERSEUS_INLINE_CONTENT_MAX_BYTES", "5")
        with pytest.raises(ValueError, match="exceeds the inline cap"):
            await build_graph_from_text(content="This is too long")

    async def test_size_limit_on_ontology(self, mock_perseus, monkeypatch):
        monkeypatch.setenv("PERSEUS_INLINE_CONTENT_MAX_BYTES", "5")
        with pytest.raises(ValueError, match="exceeds the inline cap"):
            await build_graph_from_text(content="Hi", ontology_ttl="way too long")


# ---------------------------------------------------------------------------
# interlink_graphs
# ---------------------------------------------------------------------------


class TestInterlinkGraphs:
    def setup_method(self):
        _GRAPHS.clear()

    def teardown_method(self):
        _GRAPHS.clear()

    async def test_basic(self, mock_perseus):
        g1 = _register(FakeKnowledgeGraph())
        g2 = _register(FakeKnowledgeGraph())
        result = await interlink_graphs(graph_ids=[g1, g2])
        assert "merged" in result
        assert result["sources"] == [g1, g2]

    async def test_fewer_than_two_raises(self, mock_perseus):
        g1 = _register(FakeKnowledgeGraph())
        with pytest.raises(ValueError, match="at least two"):
            await interlink_graphs(graph_ids=[g1])


# ---------------------------------------------------------------------------
# Local registry inspection
# ---------------------------------------------------------------------------


class TestLocalRegistryTools:
    def setup_method(self):
        _GRAPHS.clear()

    def teardown_method(self):
        _GRAPHS.clear()

    def test_list_empty(self):
        assert list_local_graphs()["count"] == 0

    def test_list_after_register(self):
        _register(FakeKnowledgeGraph())
        result = list_local_graphs()
        assert result["count"] == 1

    def test_get_summary(self):
        gid = _register(FakeKnowledgeGraph())
        s = get_graph_summary(graph_id=gid)
        assert s["entities"] == 1

    def test_get_entities_pagination(self):
        gid = _register(FakeKnowledgeGraph())
        result = get_graph_entities(graph_id=gid, offset=0, limit=10)
        assert result["total"] == 1
        assert len(result["entities"]) == 1

    def test_get_relations_pagination(self):
        gid = _register(FakeKnowledgeGraph())
        result = get_graph_relations(graph_id=gid, offset=0, limit=10)
        assert result["total"] == 1

    def test_forget_graph(self):
        gid = _register(FakeKnowledgeGraph())
        result = forget_graph(graph_id=gid)
        assert result["removed"] is True
        assert gid not in _GRAPHS

    def test_forget_unknown(self):
        result = forget_graph(graph_id="nope")
        assert result["removed"] is False

    def test_forget_all(self):
        _register(FakeKnowledgeGraph())
        _register(FakeKnowledgeGraph())
        result = forget_all_graphs()
        assert result["removed"] == 2
        assert len(_GRAPHS) == 0


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


class TestExports:
    def setup_method(self):
        _GRAPHS.clear()

    def teardown_method(self):
        _GRAPHS.clear()

    def test_export_ttl(self, tmp_path):
        gid = _register(FakeKnowledgeGraph())
        out = str(tmp_path / "out.ttl")
        result = export_graph_ttl(graph_id=gid, output_path=out)
        assert result["graph_id"] == gid
        assert Path(out).exists()

    def test_export_cql(self, tmp_path):
        gid = _register(FakeKnowledgeGraph())
        out = str(tmp_path / "out.cql")
        result = export_graph_cql(graph_id=gid, output_path=out)
        assert result["graph_id"] == gid
        assert Path(out).exists()
