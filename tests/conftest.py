"""Shared fixtures for lettria-perseus-mcp tests.

All tests mock the `perseus_client` SDK so no network or API key is needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tests.fakes import (
    FakeFile,
    FakeJob,
    FakeKnowledgeGraph,
    FakeOntology,
)


@pytest.fixture()
def mock_perseus(monkeypatch):
    """Patch `perseus_client` at the server-module level and return the mocks.

    Returns a dict of mock names -> AsyncMock objects so individual tests can
    customise return values or assert call args.
    """
    monkeypatch.setenv("PERSEUS_API_KEY", "test-key")

    mocks: dict[str, AsyncMock] = {}
    target = "lettria_perseus_mcp.server.perseus_client"

    # -- Graph building --
    m = AsyncMock(return_value=[FakeKnowledgeGraph()])
    mocks["build_graph_async"] = m
    monkeypatch.setattr(f"{target}.build_graph_async", m)

    m = AsyncMock(return_value=FakeKnowledgeGraph())
    mocks["interlink_async"] = m
    monkeypatch.setattr(f"{target}.interlink_async", m)

    # -- File operations --
    m = AsyncMock(return_value=FakeFile())
    mocks["upload_file_async"] = m
    monkeypatch.setattr(f"{target}.upload_file_async", m)

    m = AsyncMock(return_value=FakeFile())
    mocks["wait_for_file_upload_async"] = m
    monkeypatch.setattr(f"{target}.wait_for_file_upload_async", m)

    m = AsyncMock(return_value=[FakeFile()])
    mocks["find_files_async"] = m
    monkeypatch.setattr(f"{target}.find_files_async", m)

    m = AsyncMock(return_value=FakeFile())
    mocks["find_file_async"] = m
    monkeypatch.setattr(f"{target}.find_file_async", m)

    m = AsyncMock(return_value=None)
    mocks["delete_file_async"] = m
    monkeypatch.setattr(f"{target}.delete_file_async", m)

    # -- Ontology operations --
    m = AsyncMock(return_value=FakeOntology())
    mocks["upload_ontology_async"] = m
    monkeypatch.setattr(f"{target}.upload_ontology_async", m)

    m = AsyncMock(return_value=FakeOntology())
    mocks["wait_for_ontology_upload_async"] = m
    monkeypatch.setattr(f"{target}.wait_for_ontology_upload_async", m)

    m = AsyncMock(return_value=[FakeOntology()])
    mocks["find_ontologies_async"] = m
    monkeypatch.setattr(f"{target}.find_ontologies_async", m)

    m = AsyncMock(return_value=FakeOntology())
    mocks["find_ontology_async"] = m
    monkeypatch.setattr(f"{target}.find_ontology_async", m)

    m = AsyncMock(return_value=None)
    mocks["delete_ontology_async"] = m
    monkeypatch.setattr(f"{target}.delete_ontology_async", m)

    # -- Job operations --
    m = AsyncMock(return_value=FakeJob())
    mocks["submit_job_async"] = m
    monkeypatch.setattr(f"{target}.submit_job_async", m)

    m = AsyncMock(return_value=FakeJob())
    mocks["find_job_async"] = m
    monkeypatch.setattr(f"{target}.find_job_async", m)

    m = AsyncMock(return_value=[FakeJob()])
    mocks["find_jobs_async"] = m
    monkeypatch.setattr(f"{target}.find_jobs_async", m)

    m = AsyncMock(return_value=FakeJob())
    mocks["find_latest_job_async"] = m
    monkeypatch.setattr(f"{target}.find_latest_job_async", m)

    m = AsyncMock(return_value=FakeJob())
    mocks["find_latest_succeeded_job_async"] = m
    monkeypatch.setattr(f"{target}.find_latest_succeeded_job_async", m)

    m = AsyncMock(return_value=FakeJob())
    mocks["run_job_async"] = m
    monkeypatch.setattr(f"{target}.run_job_async", m)

    m = AsyncMock(return_value="/tmp/output.json")
    mocks["download_job_output_async"] = m
    monkeypatch.setattr(f"{target}.download_job_output_async", m)

    return mocks
