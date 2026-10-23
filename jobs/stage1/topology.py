"""
jobs/stage1/topology.py

Infers a service dependency graph from a set of correlated log events.

Algorithm:
1. Sort ERROR/WARN/CRITICAL events by timestamp ASC.
2. For each pair (A, B) where B.timestamp - A.timestamp ≤ 5s and
   A.service ≠ B.service, add/increment edge A→B.
3. Run DFS cycle detection; break cycles by removing the lowest-weight edge.
4. Assign roles based on in-degree and timestamp order:
   - in-degree 0 (or earliest error) → root_cause
   - depth 1 → propagated_error
   - depth 2+ → symptom
   - not in any path → unaffected
"""

from collections import defaultdict, deque
from datetime import timedelta

import structlog

from db.models import LogEvent

log = structlog.get_logger()

_EDGE_WINDOW_SECONDS = 5
_ANOMALY_LEVELS = {"ERROR", "WARN", "CRITICAL"}


class TopologyInferrer:
    def infer(self, events: list[LogEvent]) -> dict:
        """
        Return a topology dict:
        {
            "adjacency": {service: [neighbour, ...]},
            "edge_weights": {"A→B": count},
            "node_roles": {service: "root_cause"|"propagated_error"|"symptom"|"unaffected"},
            "error_counts": {service: int},
        }
        """
        anomaly_events = sorted(
            [e for e in events if e.level in _ANOMALY_LEVELS],
            key=lambda e: e.event_timestamp,
        )

        if not anomaly_events:
            return self._single_node_result(events)

        # Collect all services
        all_services = list({e.service_name for e in events})
        anomaly_services = list({e.service_name for e in anomaly_events})

        # Count errors per service
        error_counts: dict[str, int] = defaultdict(int)
        for e in anomaly_events:
            error_counts[e.service_name] += 1

        # Build edge weights from temporal proximity
        edge_weights: dict[tuple[str, str], int] = defaultdict(int)
        window = timedelta(seconds=_EDGE_WINDOW_SECONDS)

        for i, ea in enumerate(anomaly_events):
            for eb in anomaly_events[i + 1 :]:
                delta = eb.event_timestamp - ea.event_timestamp
                if delta > window:
                    break
                if ea.service_name != eb.service_name:
                    edge_weights[(ea.service_name, eb.service_name)] += 1

        # Build adjacency list from edges
        adjacency: dict[str, set[str]] = defaultdict(set)
        for src, dst in edge_weights:
            adjacency[src].add(dst)

        # Break cycles
        edge_weights = self._break_cycles(adjacency, edge_weights)

        # Rebuild adjacency after cycle breaking
        adjacency = defaultdict(set)
        for src, dst in edge_weights:
            adjacency[src].add(dst)

        # Compute roles
        node_roles = self._assign_roles(anomaly_services, adjacency, anomaly_events)

        # Add unaffected services
        for svc in all_services:
            if svc not in node_roles:
                node_roles[svc] = "unaffected"

        return {
            "adjacency": {k: sorted(v) for k, v in adjacency.items()},
            "edge_weights": {f"{src}→{dst}": w for (src, dst), w in edge_weights.items()},
            "node_roles": node_roles,
            "error_counts": dict(error_counts),
        }

    def _break_cycles(
        self,
        adjacency: dict[str, set[str]],
        edge_weights: dict[tuple[str, str], int],
    ) -> dict[tuple[str, str], int]:
        """Remove the lowest-weight back edge to break each cycle."""
        visited: set[str] = set()
        rec_stack: set[str] = set()
        result = dict(edge_weights)

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for neighbour in list(adjacency.get(node, [])):
                if neighbour not in visited:
                    if dfs(neighbour):
                        return True
                elif neighbour in rec_stack:
                    # Found a back edge — remove it
                    edge = (node, neighbour)
                    if edge in result:
                        del result[edge]
                        adjacency[node].discard(neighbour)
                        log.debug("cycle_broken", edge=f"{node}→{neighbour}")
                    return False
            rec_stack.discard(node)
            return False

        all_nodes = set(adjacency.keys()) | {d for dsts in adjacency.values() for d in dsts}
        for node in all_nodes:
            if node not in visited:
                dfs(node)

        return result

    def _assign_roles(
        self,
        services: list[str],
        adjacency: dict[str, set[str]],
        anomaly_events: list[LogEvent],
    ) -> dict[str, str]:
        """
        Assign roles using longest-path depth from root nodes (topological sort DP).

        root_cause — in-degree 0 (longest-path depth 0)
        propagated_error — longest-path depth 1
        symptom — longest-path depth 2+

        Longest path is used so that services reachable via an intermediate service
        (e.g. root→A→B) are assigned a deeper role even if a shortcut edge (root→B)
        also exists due to the sliding time window.
        """
        # Compute in-degree among the anomaly-service subgraph
        in_degree: dict[str, int] = {svc: 0 for svc in services}
        for src, dsts in adjacency.items():
            if src in in_degree:
                for dst in dsts:
                    if dst in in_degree:
                        in_degree[dst] = in_degree.get(dst, 0) + 1

        roots = [svc for svc, deg in in_degree.items() if deg == 0]
        if not roots:
            earliest = min(anomaly_events, key=lambda e: e.event_timestamp)
            roots = [earliest.service_name]

        # Topological sort (Kahn's algorithm)
        all_nodes = set(services)
        indeg = dict(in_degree)
        topo_queue: deque[str] = deque(n for n in all_nodes if indeg.get(n, 0) == 0)
        topo_order: list[str] = []
        while topo_queue:
            node = topo_queue.popleft()
            topo_order.append(node)
            for nb in adjacency.get(node, []):
                if nb in all_nodes:
                    indeg[nb] -= 1
                    if indeg[nb] == 0:
                        topo_queue.append(nb)

        # DP: longest path distance from any root
        dist: dict[str, int] = {svc: 0 for svc in roots}
        for node in topo_order:
            d = dist.get(node, 0)
            for nb in adjacency.get(node, []):
                if nb in all_nodes:
                    dist[nb] = max(dist.get(nb, 0), d + 1)

        roles: dict[str, str] = {}
        for svc in services:
            d = dist.get(svc, 0)
            if d == 0:
                roles[svc] = "root_cause"
            elif d == 1:
                roles[svc] = "propagated_error"
            else:
                roles[svc] = "symptom"

        return roles

    def _single_node_result(self, events: list[LogEvent]) -> dict:
        services = list({e.service_name for e in events})
        if not services:
            return {
                "adjacency": {},
                "edge_weights": {},
                "node_roles": {},
                "error_counts": {},
            }
        roles = {svc: "root_cause" for svc in services[:1]}
        roles.update({svc: "unaffected" for svc in services[1:]})
        return {
            "adjacency": {},
            "edge_weights": {},
            "node_roles": roles,
            "error_counts": {},
        }
