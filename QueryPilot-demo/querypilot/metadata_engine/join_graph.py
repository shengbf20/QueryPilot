"""Join graph path finding and SQL join generation."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from querypilot.metadata_engine.join_graph_loader import JoinEdge, JoinGraph


@dataclass(frozen=True)
class ResolvedPath:
    """A resolved join path between two tables."""

    start: str
    end: str
    tables: tuple[str, ...]
    edges: tuple[JoinEdge, ...]


@dataclass
class JoinPlan:
    """Expanded set of tables and edges needed to connect seed tables."""

    tables: list[str]
    edges: list[JoinEdge]
    join_clauses: list[str] = field(default_factory=list)


def _edge_key(edge: JoinEdge) -> str:
    return edge.id


class JoinGraphEngine:
    """Algorithms over a loaded join graph."""

    def __init__(self, graph: JoinGraph) -> None:
        self.graph = graph
        self._adjacency = _build_adjacency(graph)

    def get_neighbors(self, table: str) -> list[str]:
        return self.graph.get_neighbors(table)

    def get_predefined_path(self, path_id: str) -> ResolvedPath | None:
        predefined = self.graph.paths.get(path_id)
        if predefined is None:
            return None
        edges = tuple(self.graph.edges[eid] for eid in predefined.edges)
        return ResolvedPath(
            start=predefined.tables[0],
            end=predefined.tables[-1],
            tables=predefined.tables,
            edges=edges,
        )

    def find_path(self, start: str, end: str) -> ResolvedPath | None:
        if start not in self.graph.tables or end not in self.graph.tables:
            raise KeyError(f"Unknown table: {start if start not in self.graph.tables else end}")
        if start == end:
            return ResolvedPath(start=start, end=end, tables=(start,), edges=())

        queue: deque[str] = deque([start])
        visited = {start}
        parent: dict[str, tuple[str, JoinEdge]] = {}

        while queue:
            current = queue.popleft()
            for neighbor, edge in self._adjacency[current]:
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                parent[neighbor] = (current, edge)
                if neighbor == end:
                    return _reconstruct_path(start, end, parent)
                queue.append(neighbor)

        return None

    def expand_tables(self, seeds: list[str]) -> JoinPlan:
        """Connect seed tables via shortest paths (Steiner-tree approximation)."""
        if not seeds:
            return JoinPlan(tables=[], edges=[])

        unique_seeds = list(dict.fromkeys(seeds))
        for name in unique_seeds:
            if name not in self.graph.tables:
                raise KeyError(f"Unknown table: {name}")

        if len(unique_seeds) == 1:
            return JoinPlan(tables=unique_seeds, edges=[])

        connected = {unique_seeds[0]}
        ordered_tables = [unique_seeds[0]]
        collected_edges: dict[str, JoinEdge] = {}

        pending = set(unique_seeds[1:])
        while pending:
            best: ResolvedPath | None = None
            best_start = ""

            for src in connected:
                for dst in pending:
                    path = self.find_path(src, dst)
                    if path is None:
                        continue
                    if best is None or len(path.edges) < len(best.edges):
                        best = path
                        best_start = src

            if best is None:
                unresolved = ", ".join(sorted(pending))
                raise ValueError(f"Cannot connect tables to component; unresolved: {unresolved}")

            for table in best.tables:
                if table not in connected:
                    connected.add(table)
                    ordered_tables.append(table)

            for edge in best.edges:
                collected_edges[_edge_key(edge)] = edge

            pending = {s for s in pending if s not in connected}

        edges = _order_edges(ordered_tables, list(collected_edges.values()))
        aliases = _default_aliases(ordered_tables, edges)
        join_clauses = self.build_join_clauses(ordered_tables[0], edges, aliases)

        return JoinPlan(tables=ordered_tables, edges=edges, join_clauses=join_clauses)

    def build_join_clauses(
        self,
        base_table: str,
        edges: list[JoinEdge],
        aliases: dict[str, str] | None = None,
    ) -> list[str]:
        aliases = aliases or _default_aliases([base_table], edges)
        clauses: list[str] = []
        joined = {base_table}

        for edge in edges:
            target = _next_table_for_edge(edge, joined)
            if target is None:
                continue
            source = edge.from_table if edge.from_table in joined else edge.to_table
            clause = format_join_clause(edge, source, target, aliases)
            clauses.append(clause)
            joined.add(target)

        return clauses

    def get_join_clause(
        self,
        edge: JoinEdge,
        *,
        from_table: str,
        to_table: str,
        aliases: dict[str, str] | None = None,
    ) -> str:
        aliases = aliases or _default_aliases([from_table, to_table], [edge])
        return format_join_clause(edge, from_table, to_table, aliases)


def _build_adjacency(graph: JoinGraph) -> dict[str, list[tuple[str, JoinEdge]]]:
    adjacency: dict[str, list[tuple[str, JoinEdge]]] = {name: [] for name in graph.tables}
    for edge in graph.edges.values():
        adjacency[edge.from_table].append((edge.to_table, edge))
        adjacency[edge.to_table].append((edge.from_table, edge))
    return adjacency


def _reconstruct_path(
    start: str,
    end: str,
    parent: dict[str, tuple[str, JoinEdge]],
) -> ResolvedPath:
    edges_rev: list[JoinEdge] = []
    tables_rev = [end]
    node = end
    while node != start:
        prev, edge = parent[node]
        edges_rev.append(edge)
        tables_rev.append(prev)
        node = prev

    tables = tuple(reversed(tables_rev))
    edges = tuple(reversed(edges_rev))
    return ResolvedPath(start=start, end=end, tables=tables, edges=edges)


def _order_edges(ordered_tables: list[str], edges: list[JoinEdge]) -> list[JoinEdge]:
    """Order edges to join incrementally from the first table."""
    if not edges:
        return []

    remaining = {edge.id: edge for edge in edges}
    known = {ordered_tables[0]}
    ordered: list[JoinEdge] = []

    while remaining:
        progress = False
        for edge_id, edge in list(remaining.items()):
            if edge.from_table in known and edge.to_table not in known:
                ordered.append(edge)
                known.add(edge.to_table)
                del remaining[edge_id]
                progress = True
            elif edge.to_table in known and edge.from_table not in known:
                ordered.append(edge)
                known.add(edge.from_table)
                del remaining[edge_id]
                progress = True
        if not progress:
            ordered.extend(remaining.values())
            break

    return ordered


def _default_aliases(tables: list[str], edges: list[JoinEdge]) -> dict[str, str]:
    aliases = {table: table for table in tables}
    for edge in edges:
        if edge.alias and edge.to_table == "dim_public":
            aliases[edge.to_table] = edge.alias
        elif edge.alias and edge.from_table == "dim_public":
            aliases[edge.from_table] = edge.alias
    return aliases


def _next_table_for_edge(edge: JoinEdge, joined: set[str]) -> str | None:
    if edge.from_table in joined and edge.to_table not in joined:
        return edge.to_table
    if edge.to_table in joined and edge.from_table not in joined:
        return edge.from_table
    return None


def format_join_clause(
    edge: JoinEdge,
    from_table: str,
    to_table: str,
    aliases: dict[str, str],
) -> str:
    left_alias = aliases.get(from_table, from_table)
    right_alias = aliases.get(to_table, to_table)
    right_table = to_table

    if edge.from_table == from_table and edge.to_table == to_table:
        pairs = edge.join.items()
        filter_alias = right_alias
    elif edge.to_table == from_table and edge.from_table == to_table:
        pairs = ((right, left) for left, right in edge.join.items())
        filter_alias = right_alias
    else:
        raise ValueError(
            f"Edge {edge.id} does not connect {from_table} and {to_table}"
        )

    conditions = [f"{left_alias}.{left_col} = {right_alias}.{right_col}" for left_col, right_col in pairs]

    if edge.filter:
        if to_table == "dim_public":
            for key, value in edge.filter.items():
                conditions.append(f"{filter_alias}.{key} = '{value}'")
        elif from_table == "dim_public":
            for key, value in edge.filter.items():
                conditions.append(f"{left_alias}.{key} = '{value}'")

    on_expr = " AND ".join(conditions)
    return f"JOIN {right_table} AS {right_alias} ON {on_expr}"


def create_join_graph_engine(graph: JoinGraph | None = None) -> JoinGraphEngine:
    if graph is None:
        from querypilot.metadata_engine.join_graph_loader import load_join_graph

        graph = load_join_graph()
    return JoinGraphEngine(graph)
