from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Node:
    node_id: str
    failure_domain: str
    capacity_bytes: int
    available_bytes: int
    healthy: bool = True
    reserved_bytes: int = 0


class PlacementError(ValueError):
    pass


def place_fragments(stripe_id: str, fragment_sizes: list[int], nodes: list[Node],
                    high_watermark: float = 0.90) -> list[Node]:
    """Weighted rendezvous placement with one fragment per failure domain.

    A weighted rendezvous score favors nodes with more usable capacity, while
    the stable per-stripe hash limits movement when cluster membership changes.
    Eligibility reserves bytes atomically at the caller before fragment writes.
    """
    eligible = [n for n in nodes if n.healthy and n.failure_domain and n.capacity_bytes > 0
                and n.available_bytes - n.reserved_bytes >= max(fragment_sizes, default=0)
                and (n.capacity_bytes - n.available_bytes) / n.capacity_bytes < high_watermark]
    if len({n.failure_domain for n in eligible}) < len(fragment_sizes):
        raise PlacementError(f"Need {len(fragment_sizes)} healthy, sufficiently capacious failure domains")
    selected: list[Node] = []
    used_domains: set[str] = set()
    for index, size in enumerate(fragment_sizes):
        candidates = [n for n in eligible if n.failure_domain not in used_domains
                      and n.available_bytes - n.reserved_bytes >= size]
        if not candidates:
            raise PlacementError("No distinct failure domain has sufficient free capacity")
        def score(node: Node) -> float:
            digest = hashlib.sha256(f"{stripe_id}:{index}:{node.node_id}".encode()).digest()
            uniform = (int.from_bytes(digest[:8], "big") + 1) / (2**64 + 1)
            weight = max(1, node.available_bytes - node.reserved_bytes)
            return -math.log(uniform) / weight
        chosen = min(candidates, key=score)
        selected.append(chosen)
        used_domains.add(chosen.failure_domain)
    return selected
