from __future__ import annotations

import asyncio
import copy
import os
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from metadata.models import Base, ClusterEvent, Fragment, ObjectVersion, RebalanceJob, StorageNode, Stripe
from placement_manager.placement import Node as PlacementNode, PlacementError, place_fragments
from erasure_coding.codec import sha256

DATABASE_URL = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://", 1)
TOKEN = os.environ["INTERNAL_TOKEN"]


async def rebalance_once(client: httpx.AsyncClient, engine) -> bool:
    with Session(engine) as session:
        active_fragment = select(Fragment.storage_node_id, func.count()).join(Stripe).join(ObjectVersion).where(
            ObjectVersion.status == "AVAILABLE").group_by(Fragment.storage_node_id)
        node_counts = dict(session.execute(active_fragment).all())
        nodes = session.scalars(select(StorageNode).where(StorageNode.status == "HEALTHY")).all()
        if len(nodes) < 7: return False
        low = min(nodes, key=lambda n: node_counts.get(n.id, 0))
        high = max(nodes, key=lambda n: node_counts.get(n.id, 0))
        if node_counts.get(high.id, 0) <= node_counts.get(low.id, 0) + 1: return False
        candidates = session.scalars(select(Fragment).join(Stripe).join(ObjectVersion).where(
            ObjectVersion.status == "AVAILABLE", Fragment.storage_node_id == high.id)).all()
        node_map = {n.id: n for n in nodes}
        node_specs = [PlacementNode(n.id, n.failure_domain, n.capacity_bytes, n.available_bytes, True) for n in nodes]
        for fragment in candidates:
            stripe_fragments = session.scalars(select(Fragment).where(Fragment.stripe_id == fragment.stripe_id)).all()
            occupied_domains = {node_map[f.storage_node_id].failure_domain for f in stripe_fragments
                                if f.id != fragment.id and f.storage_node_id in node_map}
            allowed = [n for n in node_specs if n.node_id != high.id and n.failure_domain not in occupied_domains]
            try:
                target = place_fragments(f"move:{fragment.id}", [fragment.size_bytes], allowed)[0]
            except PlacementError:
                continue
            source = node_map[high.id]
            try:
                read = await client.get(f"{source.service_url}/internal/fragments/{fragment.id}",
                                        headers={"X-Internal-Token": TOKEN})
                if read.status_code != 200 or sha256(read.content) != fragment.sha256: continue
                written = await client.put(f"{node_map[target.node_id].service_url}/internal/fragments/{fragment.id}",
                                           content=read.content, headers={"X-Internal-Token": TOKEN,
                                                                         "X-Fragment-SHA256": fragment.sha256})
                written.raise_for_status()
                if written.json().get("sha256") != fragment.sha256:
                    await client.delete(f"{node_map[target.node_id].service_url}/internal/fragments/{fragment.id}",
                                        headers={"X-Internal-Token": TOKEN})
                    continue
            except httpx.HTTPError:
                continue
            source_id = source.id
            target_id = target.node_id
            job = RebalanceJob(id=str(uuid.uuid4()), fragment_id=fragment.id, source_node=source_id,
                               destination_node=target_id, status="COMPLETED", bytes_transferred=len(read.content),
                               completed_at=datetime.now(timezone.utc))
            fragment.storage_node_id = target_id
            stripe = session.get(Stripe, fragment.stripe_id)
            version = session.get(ObjectVersion, stripe.version_id)
            manifest = copy.deepcopy(version.manifest)
            for stripe_manifest in manifest["stripes"]:
                if stripe_manifest["stripe_id"] == stripe.id:
                    for fragment_manifest in stripe_manifest["fragments"]:
                        if fragment_manifest["fragment_id"] == fragment.id:
                            fragment_manifest["node_id"] = target_id
                            fragment_manifest["node"] = node_map[target_id].service_url
            version.manifest = manifest
            session.add(job)
            session.add(ClusterEvent(id=str(uuid.uuid4()), event_type="FRAGMENT_REBALANCED", severity="info",
                                     component="rebalance-worker", node_id=target_id,
                                     message=f"Moved fragment {fragment.id}",
                                     details={"source": source_id, "destination": target_id,
                                              "bytes": len(read.content)}))
            session.commit()
            # Delete only after the new placement is durable in metadata.
            try:
                await client.delete(f"{source.service_url}/internal/fragments/{fragment.id}",
                                    headers={"X-Internal-Token": TOKEN})
            except httpx.HTTPError:
                pass
            return True
    return False


async def main():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    async with httpx.AsyncClient(timeout=120) as client:
        while True:
            try:
                await rebalance_once(client, engine)
            except Exception as error:
                print(f"rebalance_worker: cycle failed: {error}", flush=True)
            await asyncio.sleep(int(os.getenv("REBALANCE_INTERVAL_SECONDS", "30")))


if __name__ == "__main__": asyncio.run(main())
