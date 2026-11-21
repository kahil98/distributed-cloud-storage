from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from metadata.models import CapacityReservation, StorageNode
from placement_manager.placement import Node as PlacementNode, place_fragments


def reserve_placement(engine, stripe_id: str, fragment_sizes: list[int]) -> tuple[str, list[PlacementNode]]:
    """Lock node rows and reserve bytes across gateway/worker processes."""
    with Session(engine) as session, session.begin():
        now = datetime.now(timezone.utc)
        session.execute(delete(CapacityReservation).where(CapacityReservation.expires_at <= now))
        rows = session.scalars(select(StorageNode).order_by(StorageNode.id).with_for_update()).all()
        reserved = dict(session.execute(select(CapacityReservation.node_id,
            func.coalesce(func.sum(CapacityReservation.bytes_reserved), 0))
            .where(CapacityReservation.expires_at > now).group_by(CapacityReservation.node_id)).all())
        candidates = [PlacementNode(row.id, row.failure_domain, row.capacity_bytes, row.available_bytes,
                                    row.status == "HEALTHY", int(reserved.get(row.id, 0))) for row in rows]
        chosen = place_fragments(stripe_id, fragment_sizes, candidates)
        reservation_id = str(uuid.uuid4())
        for node, size in zip(chosen, fragment_sizes):
            session.add(CapacityReservation(id=str(uuid.uuid4()), reservation_id=reservation_id,
                node_id=node.node_id, stripe_id=stripe_id, bytes_reserved=size,
                expires_at=now + timedelta(minutes=10)))
        return reservation_id, chosen


def release_reservations(engine, reservation_id: str) -> None:
    with Session(engine) as session, session.begin():
        session.execute(delete(CapacityReservation).where(CapacityReservation.reservation_id == reservation_id))
