"""MCP server exposing Lettria Perseus Text-to-Graph operations.

Wraps the `perseus-client` Python SDK as MCP tools. Built graphs are kept in
an in-memory registry keyed by UUID so downstream tools (exports, interlink,
database writes) can reference them without re-building.

Configuration is read from environment variables / a .env file:

    PERSEUS_API_KEY   (required)
    NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD                      (Neo4j export)
    FALKORDB_HOST, FALKORDB_PORT,
    FALKORDB_USERNAME, FALKORDB_PASSWORD, FALKORDB_GRAPH_NAME  (FalkorDB export)
    PERSEUS_INLINE_CONTENT_MAX_BYTES  (cap for inline text tools; default 1 MiB)
    LOGLEVEL          (SDK logging level, default INFO)
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

import perseus_client
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from perseus_client.models import KnowledgeGraph

# Load .env before the SDK's Settings reads env vars.
load_dotenv()

mcp = FastMCP("lettria-perseus")

# In-memory registry of KnowledgeGraph objects built during this session.
# Keyed by short UUIDs so MCP clients can refer to graphs by id.
_GRAPHS: dict[str, KnowledgeGraph] = {}

# Upper bound on the UTF-8 size of inline content accepted by
# `upload_ontology_from_text` / `build_graph_from_text`. Defaults to 1 MiB;
# override via the PERSEUS_INLINE_CONTENT_MAX_BYTES env var.
_DEFAULT_INLINE_MAX_BYTES = 1_048_576


def _inline_max_bytes() -> int:
    raw = os.environ.get("PERSEUS_INLINE_CONTENT_MAX_BYTES")
    if not raw:
        return _DEFAULT_INLINE_MAX_BYTES
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"PERSEUS_INLINE_CONTENT_MAX_BYTES must be an integer, got {raw!r}"
        ) from exc
    if value <= 0:
        raise ValueError(
            "PERSEUS_INLINE_CONTENT_MAX_BYTES must be a positive integer."
        )
    return value


def _check_inline_size(content: str, label: str, path_tool: str) -> None:
    """Raise a descriptive error if inline content exceeds the cap.

    The message is written for the agent reading it — it spells out each
    escape hatch so the model can pick one without prompting the user.
    """
    size = len(content.encode("utf-8"))
    cap = _inline_max_bytes()
    if size > cap:
        raise ValueError(
            f"{label} payload is {size:,} bytes which exceeds the inline cap "
            f"of {cap:,} bytes. Pick one of:\n"
            f"  1. Save it to disk and call `{path_tool}` with the absolute "
            f"path instead.\n"
            f"  2. Register the official filesystem MCP server so the agent "
            f"can write the file itself, then call `{path_tool}`.\n"
            f"  3. Raise PERSEUS_INLINE_CONTENT_MAX_BYTES in the server's "
            f"environment (be mindful of memory / MCP transport overhead "
            f"for very large payloads)."
        )


def _safe_basename(name: str, fallback: str) -> str:
    """Strip directory components and fall back to a default name."""
    base = Path(name).name.strip()
    return base or fallback


def _register(graph: KnowledgeGraph) -> str:
    graph_id = uuid.uuid4().hex[:12]
    _GRAPHS[graph_id] = graph
    return graph_id


def _require(graph_id: str) -> KnowledgeGraph:
    if graph_id not in _GRAPHS:
        raise ValueError(
            f"Unknown graph_id '{graph_id}'. "
            f"Known ids: {list(_GRAPHS.keys()) or '(none)'}"
        )
    return _GRAPHS[graph_id]


def _summary(graph_id: str, graph: KnowledgeGraph) -> dict[str, Any]:
    return {
        "graph_id": graph_id,
        "entities": len(graph.entities),
        "relations": len(graph.relations),
        "documents": len(getattr(graph, "documents", []) or []),
        "namespaces": list((getattr(graph, "namespaces", {}) or {}).keys()),
    }


# ---------------------------------------------------------------------------
# Graph building
# ---------------------------------------------------------------------------


@mcp.tool()
async def build_graph(
    file_paths: list[str],
    ontology_path: str | None = None,
    refresh_graph: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one knowledge graph per input file using Perseus.

    Returns a list of graph summaries. Each summary includes a `graph_id`
    that can be passed to export / interlink / save tools.

    Args:
        file_paths: Local paths (relative to the server's CWD) of source
            documents to ingest.
        ontology_path: Optional local path to an ontology file (TTL/OWL) that
            constrains what gets extracted.
        refresh_graph: If True, bypass server-side caching and re-process.
        metadata: Arbitrary metadata attached to the resulting graph(s).
    """
    graphs = await perseus_client.build_graph_async(
        file_paths=file_paths,
        ontology_path=ontology_path,
        refresh_graph=refresh_graph,
        metadata=metadata,
    )
    summaries = [_summary(_register(g), g) for g in graphs]
    return {"count": len(summaries), "graphs": summaries}


@mcp.tool()
async def build_graph_from_text(
    content: str,
    name: str = "document.txt",
    ontology_ttl: str | None = None,
    refresh_graph: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a graph from inline document text (plus optional inline ontology).

    Use this when the agent has the document text in hand and no filesystem
    MCP server is registered — the content is written to a temp file, passed
    to Perseus, and cleaned up on return. For large corpora, save to disk
    and use `build_graph` instead.

    Args:
        content: The raw document text.
        name: Filename hint for the temp file (controls extension/display
            name in Perseus). Directory components are stripped.
        ontology_ttl: Optional ontology TTL as a string; written to its own
            temp file and passed as `ontology_path`.
        refresh_graph: Forwarded to `build_graph_async`.
        metadata: Forwarded to `build_graph_async`.

    Raises:
        ValueError: If `content` or `ontology_ttl` exceeds
            PERSEUS_INLINE_CONTENT_MAX_BYTES (default 1 MiB).
    """
    _check_inline_size(content, "Document", path_tool="build_graph")
    if ontology_ttl is not None:
        _check_inline_size(ontology_ttl, "Ontology", path_tool="build_graph")

    doc_name = _safe_basename(name, "document.txt")

    with tempfile.TemporaryDirectory() as tmpdir:
        doc_path = Path(tmpdir) / doc_name
        doc_path.write_text(content, encoding="utf-8")

        onto_path: str | None = None
        if ontology_ttl is not None:
            onto_file = Path(tmpdir) / "ontology.ttl"
            onto_file.write_text(ontology_ttl, encoding="utf-8")
            onto_path = str(onto_file)

        graphs = await perseus_client.build_graph_async(
            file_paths=[str(doc_path)],
            ontology_path=onto_path,
            refresh_graph=refresh_graph,
            metadata=metadata,
        )

    summaries = [_summary(_register(g), g) for g in graphs]
    return {"count": len(summaries), "graphs": summaries}


@mcp.tool()
async def interlink_graphs(
    graph_ids: list[str],
    interlinking_key_uris: list[str] | None = None,
    immutable_properties: list[str] | None = None,
    merge_properties_on_conflict: bool = False,
) -> dict[str, Any]:
    """Merge multiple in-memory graphs into a single interlinked graph.

    Args:
        graph_ids: Ids (from `build_graph`) of graphs to merge.
        interlinking_key_uris: Property URIs used to match entities across
            graphs. Defaults to `rdfs:label` when omitted.
        immutable_properties: Properties preserved as-is on conflict.
        merge_properties_on_conflict: If True, merge rather than overwrite
            conflicting property values.
    """
    if len(graph_ids) < 2:
        raise ValueError("interlink_graphs requires at least two graph_ids.")
    graphs = [_require(gid) for gid in graph_ids]
    merged = await perseus_client.interlink_async(
        kbs=graphs,
        interlinking_key_uris=interlinking_key_uris
        or ["http://www.w3.org/2000/01/rdf-schema#label"],
        immutable_properties=immutable_properties,
        merge_properties_on_conflict=merge_properties_on_conflict,
    )
    merged_id = _register(merged)
    return {"merged": _summary(merged_id, merged), "sources": graph_ids}


# ---------------------------------------------------------------------------
# Local graph registry inspection
# ---------------------------------------------------------------------------


@mcp.tool()
def list_local_graphs() -> dict[str, Any]:
    """List graphs currently held in the server's in-memory registry."""
    return {
        "count": len(_GRAPHS),
        "graphs": [_summary(gid, g) for gid, g in _GRAPHS.items()],
    }


@mcp.tool()
def get_graph_summary(graph_id: str) -> dict[str, Any]:
    """Return entity/relation counts and namespace list for a graph."""
    return _summary(graph_id, _require(graph_id))


@mcp.tool()
def get_graph_entities(
    graph_id: str, offset: int = 0, limit: int = 50
) -> dict[str, Any]:
    """Paginate through entities in a graph (JSON-safe dumps)."""
    graph = _require(graph_id)
    total = len(graph.entities)
    slice_ = graph.entities[offset : offset + limit]
    return {
        "graph_id": graph_id,
        "total": total,
        "offset": offset,
        "limit": limit,
        "entities": [e.model_dump(mode="json") for e in slice_],
    }


@mcp.tool()
def get_graph_relations(
    graph_id: str, offset: int = 0, limit: int = 50
) -> dict[str, Any]:
    """Paginate through relations in a graph (JSON-safe dumps)."""
    graph = _require(graph_id)
    total = len(graph.relations)
    slice_ = graph.relations[offset : offset + limit]
    return {
        "graph_id": graph_id,
        "total": total,
        "offset": offset,
        "limit": limit,
        "relations": [r.model_dump(mode="json") for r in slice_],
    }


@mcp.tool()
def forget_graph(graph_id: str) -> dict[str, Any]:
    """Remove a graph from the in-memory registry (does not delete remote data)."""
    existed = _GRAPHS.pop(graph_id, None) is not None
    return {"graph_id": graph_id, "removed": existed}


@mcp.tool()
def forget_all_graphs() -> dict[str, Any]:
    """Clear the entire in-memory graph registry."""
    n = len(_GRAPHS)
    _GRAPHS.clear()
    return {"removed": n}


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


@mcp.tool()
def export_graph_ttl(graph_id: str, output_path: str) -> dict[str, Any]:
    """Write a graph to disk as Turtle (TTL)."""
    graph = _require(graph_id)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    graph.save_ttl(output_path)
    return {"graph_id": graph_id, "output_path": os.path.abspath(output_path)}


@mcp.tool()
def export_graph_cql(
    graph_id: str, output_path: str, strip_prefixes: bool = True
) -> dict[str, Any]:
    """Write a graph to disk as Cypher (CQL) statements."""
    graph = _require(graph_id)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    graph.save_cql(output_path, strip_prefixes=strip_prefixes)
    return {"graph_id": graph_id, "output_path": os.path.abspath(output_path)}


@mcp.tool()
async def save_graph_to_neo4j(
    graph_id: str, strip_prefixes: bool = True
) -> dict[str, Any]:
    """Write a graph to Neo4j using NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD env vars."""
    graph = _require(graph_id)
    await graph.save_to_neo4j_async(strip_prefixes=strip_prefixes)
    return {"graph_id": graph_id, "target": "neo4j", "ok": True}


@mcp.tool()
async def save_graph_to_falkordb(
    graph_id: str, strip_prefixes: bool = True
) -> dict[str, Any]:
    """Write a graph to FalkorDB using FALKORDB_* env vars."""
    graph = _require(graph_id)
    await graph.save_to_falkordb_async(strip_prefixes=strip_prefixes)
    return {"graph_id": graph_id, "target": "falkordb", "ok": True}


# ---------------------------------------------------------------------------
# Remote file operations
# ---------------------------------------------------------------------------


@mcp.tool()
async def upload_file(file_path: str, wait: bool = True) -> dict[str, Any]:
    """Upload a source document to Perseus. Optionally wait for processing."""
    file_ = await perseus_client.upload_file_async(file_path=file_path)
    if wait:
        file_ = await perseus_client.wait_for_file_upload_async(file_id=file_.id)
    return file_.model_dump(mode="json")


@mcp.tool()
async def list_files(
    ids: list[str] | None = None, source_hashes: list[str] | None = None
) -> dict[str, Any]:
    """List files known to Perseus. Filters are optional."""
    files = await perseus_client.find_files_async(
        ids=ids, source_hashes=source_hashes
    )
    return {
        "count": len(files),
        "files": [f.model_dump(mode="json") for f in files],
    }


@mcp.tool()
async def get_file(file_id: str) -> dict[str, Any] | None:
    """Fetch a single file by id."""
    file_ = await perseus_client.find_file_async(id=file_id)
    return file_.model_dump(mode="json") if file_ else None


@mcp.tool()
async def delete_file(file_id: str) -> dict[str, Any]:
    """Delete a file from Perseus."""
    await perseus_client.delete_file_async(file_id=file_id)
    return {"file_id": file_id, "deleted": True}


# ---------------------------------------------------------------------------
# Remote ontology operations
# ---------------------------------------------------------------------------


@mcp.tool()
async def upload_ontology(ontology_path: str, wait: bool = True) -> dict[str, Any]:
    """Upload an ontology (TTL/OWL). Optionally wait for processing."""
    onto = await perseus_client.upload_ontology_async(ontology_path=ontology_path)
    if wait:
        onto = await perseus_client.wait_for_ontology_upload_async(
            ontology_id=onto.id
        )
    return onto.model_dump(mode="json")


@mcp.tool()
async def upload_ontology_from_text(
    content: str, name: str = "ontology.ttl", wait: bool = True
) -> dict[str, Any]:
    """Upload an ontology supplied as an inline TTL string.

    Use this when the agent has drafted the ontology in-chat and no
    filesystem MCP server is registered. The content is written to a temp
    file, uploaded via the SDK, and cleaned up on return. For large
    ontologies, save to disk and use `upload_ontology` instead.

    Args:
        content: The TTL (Turtle) ontology text.
        name: Filename hint stored on the Perseus record. Directory
            components are stripped; extension defaults to `.ttl` if none.
        wait: Block until server-side processing completes.

    Raises:
        ValueError: If `content` exceeds PERSEUS_INLINE_CONTENT_MAX_BYTES
            (default 1 MiB).
    """
    _check_inline_size(content, "Ontology", path_tool="upload_ontology")

    safe_name = _safe_basename(name, "ontology.ttl")
    if not Path(safe_name).suffix:
        safe_name += ".ttl"

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / safe_name
        path.write_text(content, encoding="utf-8")
        onto = await perseus_client.upload_ontology_async(
            ontology_path=str(path)
        )
        if wait:
            onto = await perseus_client.wait_for_ontology_upload_async(
                ontology_id=onto.id
            )

    return onto.model_dump(mode="json")


@mcp.tool()
async def list_ontologies(
    ids: list[str] | None = None, source_hashes: list[str] | None = None
) -> dict[str, Any]:
    """List ontologies known to Perseus."""
    items = await perseus_client.find_ontologies_async(
        ids=ids, source_hashes=source_hashes
    )
    return {
        "count": len(items),
        "ontologies": [o.model_dump(mode="json") for o in items],
    }


@mcp.tool()
async def get_ontology(ontology_id: str) -> dict[str, Any] | None:
    """Fetch a single ontology by id."""
    onto = await perseus_client.find_ontology_async(id=ontology_id)
    return onto.model_dump(mode="json") if onto else None


@mcp.tool()
async def delete_ontology(ontology_id: str) -> dict[str, Any]:
    """Delete an ontology from Perseus."""
    await perseus_client.delete_ontology_async(ontology_id=ontology_id)
    return {"ontology_id": ontology_id, "deleted": True}


# ---------------------------------------------------------------------------
# Remote job operations
# ---------------------------------------------------------------------------


@mcp.tool()
async def submit_job(
    file_id: str, ontology_id: str | None = None
) -> dict[str, Any]:
    """Submit an extraction job for an already-uploaded file."""
    job = await perseus_client.submit_job_async(
        file_id=file_id, ontology_id=ontology_id
    )
    return job.model_dump(mode="json")


@mcp.tool()
async def get_job(job_id: str) -> dict[str, Any] | None:
    """Fetch a single job by id (status included)."""
    job = await perseus_client.find_job_async(id=job_id)
    return job.model_dump(mode="json") if job else None


@mcp.tool()
async def list_jobs(job_ids: list[str]) -> dict[str, Any]:
    """Fetch multiple jobs by id."""
    jobs = await perseus_client.find_jobs_async(ids=job_ids)
    return {
        "count": len(jobs),
        "jobs": [j.model_dump(mode="json") for j in jobs],
    }


@mcp.tool()
async def find_latest_job(
    file_id: str, ontology_id: str | None = None
) -> dict[str, Any] | None:
    """Find the most recent job for a given file (+ optional ontology)."""
    job = await perseus_client.find_latest_job_async(
        file_id=file_id, ontology_id=ontology_id
    )
    return job.model_dump(mode="json") if job else None


@mcp.tool()
async def find_latest_succeeded_job(
    file_id: str, ontology_id: str | None = None
) -> dict[str, Any] | None:
    """Find the most recent successful job for a given file."""
    job = await perseus_client.find_latest_succeeded_job_async(
        file_id=file_id, ontology_id=ontology_id
    )
    return job.model_dump(mode="json") if job else None


@mcp.tool()
async def run_job(
    job_id: str, polling_interval: int = 5, timeout: int = 3600
) -> dict[str, Any]:
    """Block until a submitted job reaches a terminal state, then return it."""
    job = await perseus_client.run_job_async(
        job_id=job_id, polling_interval=polling_interval, timeout=timeout
    )
    return job.model_dump(mode="json")


@mcp.tool()
async def download_job_output(
    job_id: str, output_path: str | None = None
) -> dict[str, Any]:
    """Download a completed job's output JSON to disk. Returns the path."""
    path = await perseus_client.download_job_output_async(
        job_id=job_id, output_path=output_path
    )
    return {"job_id": job_id, "output_path": os.path.abspath(path)}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the MCP server over stdio."""
    if not os.environ.get("PERSEUS_API_KEY"):
        # Fail fast with a helpful message instead of waiting for the first
        # SDK call to explode with a less obvious auth error.
        raise SystemExit(
            "PERSEUS_API_KEY is not set. "
            "Export it in your environment or add it to a .env file."
        )
    mcp.run()


if __name__ == "__main__":
    main()
