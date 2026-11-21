from __future__ import annotations

import asyncio
import copy
import hashlib
import os
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from erasure_coding.codec import K, reconstruct_fragment, sha256
from metadata.models import Base, ClusterEvent, Fragment, ObjectVersion, RepairJob, StorageNode, Stripe
from placement_manager.placement import Node as PlacementNode, PlacementError, place_fragments

DATABASE_URL = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://", 1)
TOKEN = os.environ["INTERNAL_TOKEN"]
engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def record_repair(session: Session, stripe_id: str, fragment_index: int, status: str,
                  valid_indexes: list[int], destination: str | None = None,
                  error: str | None = None):
    job = session.scalar(select(RepairJob).where(
        RepairJob.stripe_id == stripe_id,
        RepairJob.fragment_index == fragment_index
    ).order_by(RepairJob.created_at.desc()))
    if job is None:
        job = RepairJob(id=str(uuid.uuid4()), stripe_id=stripe_id,
                        fragment_index=fragment_index, attempt_count=0)
        session.add(job)
    job.status = status
    job.attempt_count += 1
    job.source_nodes = {"fragment_indexes": sorted(valid_indexes)}
    job.destination_node = destination
    job.error_message = error[:1000] if error else None
    job.created_at = datetime.now(timezone.utc)


def repair_due(session: Session, stripe_id: str, fragment_index: int) -> bool:
    job = session.scalar(select(RepairJob).where(
        RepairJob.stripe_id == stripe_id,
        RepairJob.fragment_index == fragment_index
    ).order_by(RepairJob.created_at.desc()))
    if job is None or job.status == "COMPLETED":
        return True
    backoff = min(300, 15 * (2 ** min(max(job.attempt_count - 1, 0), 5)))
    created_at = job.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created_at).total_seconds() >= backoff


async def repair_once(client: httpx.AsyncClient) -> int:
    repaired = 0
    with Session(engine) as session:
        # Keep the same row-lock order as the gateway placement and health paths.
        registered = [(n.id, n.service_url) for n in session.scalars(select(StorageNode).order_by(StorageNode.id)).all()]
    probes = await asyncio.gather(*(client.get(url + "/internal/status", timeout=5) for _,url in registered),
                                  return_exceptions=True)
    with Session(engine) as session, session.begin():
        for (node_id, _url), response in zip(registered, probes):
            node = session.scalar(select(StorageNode).where(StorageNode.id == node_id).with_for_update())
            previous_status = node.status
            healthy = not isinstance(response, Exception) and response.status_code == 200
            now = datetime.now(timezone.utc)
            if healthy:
                status = response.json()
                node.status = "HEALTHY"
                node.capacity_bytes = status["capacity_bytes"]
                node.used_bytes = status["used_bytes"]
                node.available_bytes = status["available_bytes"]
                node.last_heartbeat = now
            else:
                last_seen = node.last_heartbeat
                if last_seen and last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=timezone.utc)
                node.status = ("HEALTHY" if last_seen and
                               (now - last_seen).total_seconds() < 12 else "OFFLINE")
            if previous_status != node.status:
                session.add(ClusterEvent(id=str(uuid.uuid4()), event_type="NODE_HEALTH_CHANGED",
                                         severity="info" if node.status == "HEALTHY" else "error", component="cluster-manager",
                                         node_id=node_id, message=f"Node {node_id} changed to {node.status}"))
    with Session(engine) as session:
        stripes = session.scalars(select(Stripe).join(ObjectVersion).where(ObjectVersion.status == "AVAILABLE")).all()
        node_by_id = {n.id: n for n in session.scalars(select(StorageNode)).all()}
        for stripe in stripes:
            fragments = session.scalars(select(Fragment).where(Fragment.stripe_id == stripe.id)).all()
            valid: dict[int, bytes] = {}
            lost: list[Fragment] = []
            for fragment in fragments:
                node = node_by_id.get(fragment.storage_node_id)
                if not node or node.status != "HEALTHY":
                    lost.append(fragment); continue
                try:
                    response = await client.get(f"{node.service_url}/internal/fragments/{fragment.id}",
                                                headers={"X-Internal-Token": TOKEN})
                    if response.status_code == 200 and sha256(response.content) == fragment.sha256:
                        valid[fragment.fragment_index] = response.content
                    else:
                        lost.append(fragment)
                except httpx.HTTPError:
                    lost.append(fragment)
            if not lost: continue
            if len(valid) < K:
                stripe.status = "UNAVAILABLE"
                for fragment in lost:
                    if not repair_due(session, stripe.id, fragment.fragment_index):
                        continue
                    record_repair(session, stripe.id, fragment.fragment_index, "QUEUED",
                                  list(valid), error="Waiting for at least four verified source fragments")
                continue
            used_domains = {node_by_id[f.storage_node_id].failure_domain for f in fragments
                            if f not in lost and f.storage_node_id in node_by_id}
            for fragment in lost:
                if not repair_due(session, stripe.id, fragment.fragment_index):
                    continue
                candidates = [PlacementNode(n.id, n.failure_domain, n.capacity_bytes, n.available_bytes,
                                             n.status == "HEALTHY") for n in node_by_id.values()
                              if n.status == "HEALTHY" and n.failure_domain not in used_domains]
                try:
                    destination = place_fragments(f"repair:{stripe.id}:{fragment.fragment_index}",
                                                  [fragment.size_bytes], candidates)[0]
                except PlacementError:
                    stripe.status = "DEGRADED"
                    record_repair(session, stripe.id, fragment.fragment_index, "QUEUED",
                                  list(valid), error="No healthy destination node with available capacity")
                    continue
                body = reconstruct_fragment(valid, fragment.fragment_index)
                if len(body) != fragment.size_bytes or sha256(body) != fragment.sha256:
                    stripe.status = "UNAVAILABLE"
                    record_repair(session, stripe.id, fragment.fragment_index, "QUEUED",
                                  list(valid), error="Reconstructed fragment failed checksum validation")
                    continue
                target = node_by_id[destination.node_id]
                try:
                    response = await client.put(f"{target.service_url}/internal/fragments/{fragment.id}",
                                                content=body, headers={"X-Internal-Token": TOKEN,
                                                                       "X-Fragment-SHA256": fragment.sha256})
                    response.raise_for_status()
                    if response.json().get("sha256") != fragment.sha256:
                        stripe.status = "DEGRADED"
                        record_repair(session, stripe.id, fragment.fragment_index, "QUEUED",
                                      list(valid), target.id, "Destination reported a different checksum")
                        continue
                except httpx.HTTPError:
                    stripe.status = "DEGRADED"
                    record_repair(session, stripe.id, fragment.fragment_index, "QUEUED",
                                  list(valid), target.id, "Destination node write failed")
                    continue
                previous = fragment.storage_node_id
                fragment.storage_node_id = target.id
                fragment.status = "AVAILABLE"
                version = session.get(ObjectVersion, stripe.version_id)
                manifest = copy.deepcopy(version.manifest)
                for stripe_manifest in manifest["stripes"]:
                    if stripe_manifest["stripe_id"] == stripe.id:
                        for fragment_manifest in stripe_manifest["fragments"]:
                            if fragment_manifest["fragment_id"] == fragment.id:
                                fragment_manifest["node_id"] = target.id
                                fragment_manifest["node"] = target.service_url
                version.manifest = manifest
                used_domains.add(target.failure_domain)
                record_repair(session, stripe.id, fragment.fragment_index, "COMPLETED",
                              list(valid), target.id)
                session.add(ClusterEvent(id=str(uuid.uuid4()), event_type="FRAGMENT_REPAIR_COMPLETED",
                                         severity="info", component="repair-worker", node_id=target.id,
                                         message=f"Reconstructed fragment {fragment.id}",
                                         details={"stripe_id": stripe.id, "from_node": previous,
                                                  "to_node": target.id, "sha256": fragment.sha256}))
                repaired += 1
            stripe.status = "HEALTHY" if len(fragments) == K + 2 and all(
                f.status == "AVAILABLE" and
                node_by_id.get(f.storage_node_id) and node_by_id[f.storage_node_id].status == "HEALTHY"
                for f in fragments) else "DEGRADED"
        session.commit()
    return repaired


async def main():
    Base.metadata.create_all(engine)
    async with httpx.AsyncClient(timeout=90) as client:
        while True:
            try:
                count = await repair_once(client)
                if count: print(f"repair_worker: committed {count} repaired fragments", flush=True)
            except Exception as error:
                print(f"repair_worker: cycle failed: {error}", flush=True)
            await asyncio.sleep(int(os.getenv("REPAIR_INTERVAL_SECONDS", "15")))


if __name__ == "__main__": asyncio.run(main())
