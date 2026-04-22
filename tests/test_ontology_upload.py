"""Tests for ontology upload tools — the area with the reported TTL issue."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from tests.fakes import FakeOntology
from lettria_perseus_mcp.server import (
    upload_ontology,
    upload_ontology_from_text,
    list_ontologies,
    get_ontology,
    delete_ontology,
    _GRAPHS,
)


# ---------------------------------------------------------------------------
# upload_ontology (path-based)
# ---------------------------------------------------------------------------


class TestUploadOntology:
    async def test_returns_serialised_ontology(self, mock_perseus):
        result = await upload_ontology(ontology_path="/tmp/test.ttl", wait=True)
        assert result["id"] == "onto-1"
        mock_perseus["upload_ontology_async"].assert_awaited_once_with(
            ontology_path="/tmp/test.ttl"
        )
        mock_perseus["wait_for_ontology_upload_async"].assert_awaited_once()

    async def test_skip_wait(self, mock_perseus):
        result = await upload_ontology(ontology_path="/tmp/test.ttl", wait=False)
        assert result["id"] == "onto-1"
        mock_perseus["wait_for_ontology_upload_async"].assert_not_awaited()

    async def test_sdk_error_propagates(self, mock_perseus):
        mock_perseus["upload_ontology_async"].side_effect = RuntimeError("boom")
        with pytest.raises(RuntimeError, match="boom"):
            await upload_ontology(ontology_path="/tmp/bad.ttl")


# ---------------------------------------------------------------------------
# upload_ontology_from_text (inline TTL)
# ---------------------------------------------------------------------------

SAMPLE_TTL = """\
@prefix ex: <http://example.org/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

ex:Person a rdfs:Class .
"""


class TestUploadOntologyFromText:
    async def test_basic_upload(self, mock_perseus):
        result = await upload_ontology_from_text(content=SAMPLE_TTL)
        assert result["id"] == "onto-1"
        mock_perseus["upload_ontology_async"].assert_awaited_once()

    async def test_temp_file_written_with_correct_content(self, mock_perseus):
        """The SDK should receive a path to a file containing the TTL text."""
        captured_path: str | None = None

        async def capture_upload(*, ontology_path: str):
            nonlocal captured_path
            captured_path = ontology_path
            # Verify the temp file exists and is readable at call time
            content = Path(ontology_path).read_text(encoding="utf-8")
            assert content == SAMPLE_TTL
            return FakeOntology()

        mock_perseus["upload_ontology_async"].side_effect = capture_upload
        await upload_ontology_from_text(content=SAMPLE_TTL, wait=False)
        assert captured_path is not None
        assert captured_path.endswith(".ttl")

    async def test_custom_name_preserved(self, mock_perseus):
        """The filename hint should be used for the temp file."""
        async def capture_upload(*, ontology_path: str):
            assert Path(ontology_path).name == "my_onto.ttl"
            return FakeOntology()

        mock_perseus["upload_ontology_async"].side_effect = capture_upload
        await upload_ontology_from_text(
            content=SAMPLE_TTL, name="my_onto.ttl", wait=False
        )

    async def test_directory_stripped_from_name(self, mock_perseus):
        async def capture_upload(*, ontology_path: str):
            assert "/" not in Path(ontology_path).name
            assert Path(ontology_path).name == "onto.ttl"
            return FakeOntology()

        mock_perseus["upload_ontology_async"].side_effect = capture_upload
        await upload_ontology_from_text(
            content=SAMPLE_TTL, name="/etc/evil/onto.ttl", wait=False
        )

    async def test_ttl_extension_appended_if_missing(self, mock_perseus):
        async def capture_upload(*, ontology_path: str):
            assert Path(ontology_path).name == "myonto.ttl"
            return FakeOntology()

        mock_perseus["upload_ontology_async"].side_effect = capture_upload
        await upload_ontology_from_text(
            content=SAMPLE_TTL, name="myonto", wait=False
        )

    async def test_non_ttl_extension_kept(self, mock_perseus):
        """If the user provides .owl, it should NOT get .ttl appended."""
        async def capture_upload(*, ontology_path: str):
            assert Path(ontology_path).name == "onto.owl"
            return FakeOntology()

        mock_perseus["upload_ontology_async"].side_effect = capture_upload
        await upload_ontology_from_text(
            content=SAMPLE_TTL, name="onto.owl", wait=False
        )

    async def test_exceeds_size_limit(self, mock_perseus, monkeypatch):
        monkeypatch.setenv("PERSEUS_INLINE_CONTENT_MAX_BYTES", "10")
        with pytest.raises(ValueError, match="exceeds the inline cap"):
            await upload_ontology_from_text(content=SAMPLE_TTL)

    async def test_wait_true_calls_wait(self, mock_perseus):
        await upload_ontology_from_text(content=SAMPLE_TTL, wait=True)
        mock_perseus["wait_for_ontology_upload_async"].assert_awaited_once()

    async def test_wait_false_skips_wait(self, mock_perseus):
        await upload_ontology_from_text(content=SAMPLE_TTL, wait=False)
        mock_perseus["wait_for_ontology_upload_async"].assert_not_awaited()

    async def test_temp_file_cleaned_up_after_upload(self, mock_perseus):
        """After the tool returns, the temp dir should be gone."""
        captured_path: str | None = None

        async def capture_upload(*, ontology_path: str):
            nonlocal captured_path
            captured_path = ontology_path
            return FakeOntology()

        mock_perseus["upload_ontology_async"].side_effect = capture_upload
        await upload_ontology_from_text(content=SAMPLE_TTL, wait=True)
        assert captured_path is not None
        assert not Path(captured_path).exists(), "Temp file should be cleaned up"


# ---------------------------------------------------------------------------
# list / get / delete ontologies
# ---------------------------------------------------------------------------


class TestOntologyCRUD:
    async def test_list_ontologies(self, mock_perseus):
        result = await list_ontologies()
        assert result["count"] == 1
        assert result["ontologies"][0]["id"] == "onto-1"

    async def test_list_ontologies_with_filters(self, mock_perseus):
        await list_ontologies(ids=["onto-1"], source_hashes=["abc"])
        mock_perseus["find_ontologies_async"].assert_awaited_once_with(
            ids=["onto-1"], source_hashes=["abc"]
        )

    async def test_get_ontology(self, mock_perseus):
        result = await get_ontology(ontology_id="onto-1")
        assert result["id"] == "onto-1"

    async def test_get_ontology_not_found(self, mock_perseus):
        mock_perseus["find_ontology_async"].return_value = None
        result = await get_ontology(ontology_id="missing")
        assert result is None

    async def test_delete_ontology(self, mock_perseus):
        result = await delete_ontology(ontology_id="onto-1")
        assert result["deleted"] is True
        mock_perseus["delete_ontology_async"].assert_awaited_once_with(
            ontology_id="onto-1"
        )
