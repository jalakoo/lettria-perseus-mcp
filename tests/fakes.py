"""Lightweight stand-ins for perseus-client model objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeOntology:
    id: str = "onto-1"
    name: str = "test.ttl"
    status: str = "completed"

    def model_dump(self, *, mode: str = "json") -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "status": self.status}


@dataclass
class FakeFile:
    id: str = "file-1"
    name: str = "doc.txt"
    status: str = "completed"

    def model_dump(self, *, mode: str = "json") -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "status": self.status}


@dataclass
class FakeEntity:
    uri: str = "http://example.org/Entity1"

    def model_dump(self, *, mode: str = "json") -> dict[str, Any]:
        return {"uri": self.uri}


@dataclass
class FakeRelation:
    uri: str = "http://example.org/rel1"
    source: str = "http://example.org/Entity1"
    target: str = "http://example.org/Entity2"

    def model_dump(self, *, mode: str = "json") -> dict[str, Any]:
        return {"uri": self.uri, "source": self.source, "target": self.target}


@dataclass
class FakeKnowledgeGraph:
    entities: list[FakeEntity] = field(default_factory=lambda: [FakeEntity()])
    relations: list[FakeRelation] = field(default_factory=lambda: [FakeRelation()])
    documents: list[str] = field(default_factory=list)
    namespaces: dict[str, str] = field(default_factory=dict)

    def save_ttl(self, path: str) -> None:
        with open(path, "w") as f:
            f.write("# fake ttl\n")

    def save_cql(self, path: str, *, strip_prefixes: bool = True) -> None:
        with open(path, "w") as f:
            f.write("// fake cql\n")

    async def save_to_neo4j_async(self, *, strip_prefixes: bool = True) -> None:
        self.neo4j_calls = getattr(self, "neo4j_calls", [])
        self.neo4j_calls.append({"strip_prefixes": strip_prefixes})

    async def save_to_falkordb_async(self, *, strip_prefixes: bool = True) -> None:
        self.falkordb_calls = getattr(self, "falkordb_calls", [])
        self.falkordb_calls.append({"strip_prefixes": strip_prefixes})


@dataclass
class FakeJob:
    id: str = "job-1"
    status: str = "succeeded"

    def model_dump(self, *, mode: str = "json") -> dict[str, Any]:
        return {"id": self.id, "status": self.status}
