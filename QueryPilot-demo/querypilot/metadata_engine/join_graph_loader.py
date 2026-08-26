"""Load and parse join graph metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from querypilot.config import get_settings


@dataclass(frozen=True)
class JoinRule:
    id: str
    description: str


@dataclass(frozen=True)
class GraphTable:
    name: str
    alias: str
    layer: str
    primary_key: tuple[str, ...]
    role: str = ""


@dataclass(frozen=True)
class JoinEdge:
    id: str
    from_table: str
    to_table: str
    edge_type: str
    join: dict[str, str]
    cardinality: str = ""
    alias: str = ""
    filter: dict[str, str] = field(default_factory=dict)
    rules: tuple[str, ...] = ()


@dataclass(frozen=True)
class JoinPath:
    id: str
    description: str
    tables: tuple[str, ...]
    edges: tuple[str, ...]


@dataclass
class JoinGraph:
    rules: dict[str, JoinRule]
    tables: dict[str, GraphTable]
    edges: dict[str, JoinEdge]
    paths: dict[str, JoinPath]

    def get_neighbors(self, table: str) -> list[str]:
        neighbors: list[str] = []
        for edge in self.edges.values():
            if edge.from_table == table:
                neighbors.append(edge.to_table)
            elif edge.to_table == table:
                neighbors.append(edge.from_table)
        return sorted(set(neighbors))


def load_join_graph(path: Path | None = None) -> JoinGraph:
    path = path or (get_settings().metadata_dir / "join_graph.yaml")
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    rules = {
        item["id"]: JoinRule(id=item["id"], description=item["description"])
        for item in raw.get("join_rules", [])
    }

    tables: dict[str, GraphTable] = {}
    for name, info in raw.get("tables", {}).items():
        tables[name] = GraphTable(
            name=name,
            alias=info["alias"],
            layer=info["layer"],
            primary_key=tuple(info["primary_key"]),
            role=info.get("role", ""),
        )

    edges: dict[str, JoinEdge] = {}
    for item in raw.get("edges", []):
        edges[item["id"]] = JoinEdge(
            id=item["id"],
            from_table=item["from"],
            to_table=item["to"],
            edge_type=item["type"],
            join=dict(item["join"]),
            cardinality=item.get("cardinality", ""),
            alias=item.get("alias", ""),
            filter=dict(item.get("filter", {})),
            rules=tuple(item.get("rules", [])),
        )

    paths: dict[str, JoinPath] = {}
    for path_id, info in raw.get("paths", {}).items():
        paths[path_id] = JoinPath(
            id=path_id,
            description=info["description"],
            tables=tuple(info["tables"]),
            edges=tuple(info["edges"]),
        )

    return JoinGraph(rules=rules, tables=tables, edges=edges, paths=paths)
