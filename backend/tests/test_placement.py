import pytest

from placement_manager.placement import Node, PlacementError, place_fragments


def nodes(count=8):
    return [Node(f"node-{i}", f"rack-{i}", 1000, 900) for i in range(count)]


def test_places_six_unique_failure_domains_stably():
    first = place_fragments("stripe-a", [10] * 6, nodes())
    second = place_fragments("stripe-a", [10] * 6, nodes())
    assert [n.node_id for n in first] == [n.node_id for n in second]
    assert len({n.failure_domain for n in first}) == 6


def test_excludes_unhealthy_and_capacity_constrained_nodes():
    eligible = [Node("dead", "r1", 1000, 1000, healthy=False)]
    eligible.extend(nodes(6))
    placed = place_fragments("stripe-b", [20] * 6, eligible)
    assert "dead" not in {n.node_id for n in placed}
    too_small = [Node(f"small-{i}", f"r{i}", 100, 2) for i in range(6)]
    with pytest.raises(PlacementError):
        place_fragments("stripe-c", [10] * 6, too_small)


def test_rejects_duplicate_domains_and_high_watermark():
    same_rack = [Node(f"n{i}", "rack", 1000, 900) for i in range(6)]
    with pytest.raises(PlacementError):
        place_fragments("stripe-d", [10] * 6, same_rack)
    full = [Node(f"n{i}", f"rack{i}", 1000, 100) for i in range(6)]
    with pytest.raises(PlacementError):
        place_fragments("stripe-e", [10] * 6, full)
