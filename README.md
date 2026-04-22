# lettria-perseus-mcp

An [MCP](https://modelcontextprotocol.io/) server that exposes [Lettria
Perseus](https://docs.perseus.lettria.net/), Lettria's Text-to-Graph engine,
to MCP-compatible clients (Claude Code, Claude Desktop, Cursor, Zed, etc.).

It wraps the official
[perseus-client](https://pypi.org/project/perseus-client/) Python SDK, so
anything the SDK can do — ingest files, run ontology-driven extraction,
build knowledge graphs, interlink them, and export to Neo4j / FalkorDB /
TTL / Cypher — becomes a callable tool for an LLM agent.

> Status: experimental scaffold. The upstream SDK is a `1.0.0rc` pre-release;
> APIs may shift.

---

## Table of contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running](#running)
- [Tool reference](#tool-reference)
- [Typical workflows](#typical-workflows)
- [Inline text vs. file paths](#inline-text-vs-file-paths)
- [Design notes](#design-notes)
- [Development](#development)
  - [Testing](#testing)
- [License](#license)
- [Related links](#related-links)

---

## Features

- [**29 MCP tools**](#tool-reference) covering the full Perseus workflow:
  - Graph building (`build_graph`) and merging (`interlink_graphs`)
  - An in-memory registry so graphs can be referenced across tool calls
  - Paginated inspection of entities and relations
  - Exports to TTL, Cypher (CQL) files, Neo4j, and FalkorDB
  - Remote file, ontology, and job management
  - Inline-text variants (`build_graph_from_text`,
    `upload_ontology_from_text`) for agents without filesystem access
- **Async throughout** — uses the SDK's `*_async` variants, so long
  extraction jobs don't block the event loop.
- **Safe by default** — `PERSEUS_API_KEY` is required at startup; the server
  refuses to run without it.
- **Pagination for large graphs** — entities and relations are returned in
  slices, keeping tool-call payloads manageable.

---

## Requirements

- Python **3.11+**
- [uv](https://docs.astral.sh/uv/) (for dependency management & running)
- A Perseus API key (see
  [docs.perseus.lettria.net](https://docs.perseus.lettria.net/))
- *(Optional)* Running Neo4j or FalkorDB instance if you want to use the
  database-export tools

---

## Installation

```bash
git clone <this-repo-url> lettria-perseus-mcp
cd lettria-perseus-mcp
uv sync   # optional — uv run will do this on first launch
```

`uv sync` creates `.venv/`, resolves `uv.lock`, and installs:

- `mcp[cli]` — the Model Context Protocol Python SDK
- `perseus-client` — Lettria's Perseus SDK
- `python-dotenv` — loads `.env` before the SDK reads settings

Running it upfront is not required — the MCP client (or any later
`uv run`) will auto-sync on first use — but it's a faster way to surface
dependency resolution errors.

---

## Configuration

The Perseus SDK reads its settings from environment variables (via
pydantic-settings). You have two equivalent ways to supply them; pick
whichever fits how you launch the server.

At minimum, `PERSEUS_API_KEY` must be set. All other variables are optional
— see `sample.env` for the full list (Neo4j, FalkorDB, inline-content
cap, log level).

### Option A — in your MCP client's server config (recommended)

Every MCP client lets you set environment variables on the subprocess it
spawns. This keeps the credential attached to the server registration,
with no extra file to manage. Examples are in the
[Running](#running) section below.

### Option B — in a local `.env` file

Useful during development when you `uv run` the server directly, or when
you don't want secrets inside a client config file:

```bash
cp sample.env .env
$EDITOR .env
```

### Precedence

Process environment variables always win over `.env` values, so a key set
in the MCP client config will override one sitting in `.env`.

### A note on secret hygiene

Both options write your API key to a local file (either `.env` or the
client's JSON config). Treat them the same: don't commit them, and don't
sync them through cloud-backed config directories you wouldn't trust with
a password.

---

## Running

You do **not** need to start the server manually. MCP clients spawn the
subprocess themselves using the command you register below — the `uv`
invocation in the client config is what actually launches the server each
time the client connects.

`uv` will auto-sync the lockfile on first launch, so even `uv sync` is
optional; running it once upfront just surfaces dependency errors earlier.

### Registering with Claude Code

Pass the API key (and any optional DB creds) with `-e KEY=value`:

```bash
claude mcp add lettria-perseus \
  -e PERSEUS_API_KEY=sk-perseus-... \
  -- uv --directory /absolute/path/to/lettria-perseus-mcp run lettria-perseus-mcp
```

Add more `-e` flags for Neo4j / FalkorDB if you plan to use those export
tools.

### Registering with Claude Desktop

Add an entry to `claude_desktop_config.json` and set credentials via the
`env` block:

```jsonc
{
  "mcpServers": {
    "lettria-perseus": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/lettria-perseus-mcp",
        "run",
        "lettria-perseus-mcp"
      ],
      "env": {
        "PERSEUS_API_KEY": "sk-perseus-...",

        // Optional: only if you use `save_graph_to_neo4j`.
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "password",

        // Optional: only if you use `save_graph_to_falkordb`.
        "FALKORDB_HOST": "localhost",
        "FALKORDB_PORT": "6379",
        "FALKORDB_USERNAME": "",
        "FALKORDB_PASSWORD": "",
        "FALKORDB_GRAPH_NAME": "perseus_graph"
      }
    }
  }
}
```

Any other MCP client that can spawn a stdio subprocess supports the same
pattern — consult its docs for the equivalent of `env` / `-e`.

### Optional: smoke-test or Inspector

These are only useful for local debugging — not prerequisites for the MCP
client registrations above.

Smoke-test that the server starts and auth succeeds:

```bash
PERSEUS_API_KEY=sk-perseus-... uv run lettria-perseus-mcp
# Ctrl-C once you see it waiting on stdio.
```

Interactively call each tool via the
[MCP Inspector](https://modelcontextprotocol.io/docs/tools/inspector):

```bash
PERSEUS_API_KEY=sk-perseus-... uv run mcp dev src/lettria_perseus_mcp/server.py
```

---

## Tool reference

Tools are grouped below by concern. Every tool that returns graph data uses
`graph_id` — a short identifier minted when `build_graph` or
`interlink_graphs` succeeds and held in server memory for the lifetime of
the process.

### Graph building

| Tool | Description |
| ---- | ----------- |
| `build_graph(file_paths, ontology_path?, refresh_graph?, metadata?)` | Build one graph per input file. Returns a summary and `graph_id` for each. |
| `build_graph_from_text(content, name?, ontology_ttl?, refresh_graph?, metadata?)` | Inline variant — pass document text (and optional TTL ontology) as strings. Bounded by `PERSEUS_INLINE_CONTENT_MAX_BYTES`. |
| `interlink_graphs(graph_ids, interlinking_key_uris?, immutable_properties?, merge_properties_on_conflict?)` | Merge two or more in-memory graphs on shared entity keys. |

### Local registry inspection

| Tool | Description |
| ---- | ----------- |
| `list_local_graphs()` | List every graph currently held in memory. |
| `get_graph_summary(graph_id)` | Entity / relation / document counts for one graph. |
| `get_graph_entities(graph_id, offset=0, limit=50)` | Paginated entity dump. |
| `get_graph_relations(graph_id, offset=0, limit=50)` | Paginated relation dump. |
| `forget_graph(graph_id)` | Drop a graph from the registry. |
| `forget_all_graphs()` | Drop all graphs from the registry. |

### Exports

| Tool | Description |
| ---- | ----------- |
| `export_graph_ttl(graph_id, output_path)` | Write the graph as Turtle. |
| `export_graph_cql(graph_id, output_path, strip_prefixes=True)` | Write the graph as Cypher statements. |
| `save_graph_to_neo4j(graph_id, strip_prefixes=True)` | Push to Neo4j via `NEO4J_*` env vars. |
| `save_graph_to_falkordb(graph_id, strip_prefixes=True)` | Push to FalkorDB via `FALKORDB_*` env vars. |

### Remote files

| Tool | Description |
| ---- | ----------- |
| `upload_file(file_path, wait=True)` | Upload a source document; optionally block until processed. |
| `list_files(ids?, source_hashes?)` | List remote files. |
| `get_file(file_id)` | Fetch a single file record. |
| `delete_file(file_id)` | Delete a remote file. |

### Remote ontologies

| Tool | Description |
| ---- | ----------- |
| `upload_ontology(ontology_path, wait=True)` | Upload an ontology (TTL/OWL). |
| `upload_ontology_from_text(content, name?, wait=True)` | Inline variant — pass a TTL string directly. Bounded by `PERSEUS_INLINE_CONTENT_MAX_BYTES`. |
| `list_ontologies(ids?, source_hashes?)` | List remote ontologies. |
| `get_ontology(ontology_id)` | Fetch a single ontology record. |
| `delete_ontology(ontology_id)` | Delete a remote ontology. |

### Remote jobs

| Tool | Description |
| ---- | ----------- |
| `submit_job(file_id, ontology_id?)` | Kick off extraction for an uploaded file. |
| `get_job(job_id)` | Fetch a single job (includes status). |
| `list_jobs(job_ids)` | Fetch multiple jobs at once. |
| `find_latest_job(file_id, ontology_id?)` | Most recent job for a file. |
| `find_latest_succeeded_job(file_id, ontology_id?)` | Most recent successful job. |
| `run_job(job_id, polling_interval=5, timeout=3600)` | Block until a job reaches a terminal state. |
| `download_job_output(job_id, output_path?)` | Save a job's output JSON locally. |

---

## Typical workflows

### "Give me a knowledge graph of this directory"

An agent can chain:

1. `build_graph(file_paths=[...])` → gather `graph_id`s
2. `interlink_graphs(graph_ids=[...])` → single merged graph
3. `export_graph_ttl(graph_id, "output/merged.ttl")`

### "Push the graph into my local Neo4j"

1. Ensure `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` are set in `.env`.
2. `build_graph(...)`
3. `save_graph_to_neo4j(graph_id)`

### "Re-use a previous extraction"

1. `list_files()` / `list_ontologies()`
2. `find_latest_succeeded_job(file_id, ontology_id?)`
3. `download_job_output(job_id, "output/job.json")`

---

## Inline text vs. file paths

Some MCP clients (notably Claude Desktop) cannot write files to disk on
their own, which breaks workflows where the agent drafts an ontology or
document in chat and then wants Perseus to ingest it. To avoid forcing
users to install a separate filesystem MCP server for that common case,
the server provides inline variants:

- `build_graph_from_text(content, ...)` — document text as a string.
- `upload_ontology_from_text(content, ...)` — TTL ontology as a string.

Both write the payload to a temp file, call the SDK, and clean up before
returning. No path management required from the agent.

### Size cap

Inline payloads are capped at **`PERSEUS_INLINE_CONTENT_MAX_BYTES`**
(default **1 MiB** / 1,048,576 bytes, measured as UTF-8). Anything larger
is rejected with an error message that lists the three alternatives:

1. Save locally and use the path-based tool
   (`build_graph` / `upload_ontology`).
2. Register the official
   [`@modelcontextprotocol/server-filesystem`](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem)
   server and let the agent write the file itself.
3. Raise the cap via `PERSEUS_INLINE_CONTENT_MAX_BYTES` if you accept the
   memory / MCP-transport overhead.

The cap is deliberately conservative because every byte of inline content
crosses the MCP wire and sits in the model's context. For real-world
corpora (PDFs, multi-megabyte exports), path-based ingestion is always
the right answer.

---

## Design notes

- **Graph state is in-memory.** Restarting the server discards the registry;
  export anything you want to keep. This is deliberate — `KnowledgeGraph`
  objects are Pydantic models that aren't cheap to serialize, and MCP
  servers are meant to be short-lived helpers.
- **Large graphs use pagination.** `get_graph_entities` / `get_graph_relations`
  default to slices of 50 and return `total` so an agent can loop.
- **Secrets stay in env vars.** API keys and database credentials are never
  passed through tool arguments; the SDK reads them via pydantic-settings.
- **Failures surface as tool errors.** `PerseusException`s and validation
  errors propagate up to the MCP client rather than being swallowed.

---

## Development

```bash
# Install + create virtualenv
uv sync

# Run the server
PERSEUS_API_KEY=... uv run lettria-perseus-mcp

# List registered tools without starting stdio
PERSEUS_API_KEY=test uv run python -c "
from lettria_perseus_mcp.server import mcp
for t in mcp._tool_manager.list_tools():
    print(t.name)
"
```

### Testing

Tests mock the `perseus_client` SDK so **no API key or network is needed**.

```bash
# Install dev dependencies (pytest + pytest-asyncio)
uv sync --group dev

# Run the full suite
uv run pytest tests/ -v
```

#### Test structure

```
tests/
├── fakes.py                  # Lightweight stand-ins for SDK models
│                               (FakeOntology, FakeKnowledgeGraph, etc.)
├── conftest.py               # mock_perseus fixture — patches all SDK calls
├── test_helpers.py           # _safe_basename, _inline_max_bytes,
│                               _check_inline_size, graph registry
├── test_ontology_upload.py   # upload_ontology, upload_ontology_from_text,
│                               list/get/delete ontologies
└── test_graph_tools.py       # build_graph, build_graph_from_text,
                                interlink, local registry, exports
```

#### What's covered

| Area | Examples |
| ---- | -------- |
| **Ontology upload (TTL)** | Temp file content, filename sanitization, `.ttl` extension appending, size-limit enforcement, wait/no-wait, cleanup |
| **Graph building** | Path-based and inline-text variants, inline ontology pass-through, size limits |
| **Helpers** | Path traversal in `_safe_basename`, env-var validation, multibyte UTF-8 size checks |
| **Graph registry** | Register/require round-trip, unknown-ID errors, pagination, forget/forget-all |
| **Exports** | TTL and CQL file writing |
| **CRUD tools** | list/get/delete for ontologies, files |

---

## License

MIT — see [LICENSE](LICENSE) for details.

## Related links

- Perseus docs: <https://docs.perseus.lettria.net/>
- `perseus-client` on PyPI: <https://pypi.org/project/perseus-client/>
- Model Context Protocol: <https://modelcontextprotocol.io/>
