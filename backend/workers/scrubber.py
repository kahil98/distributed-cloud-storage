from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from metadata.models import Base, ClusterEvent, Fragment, ObjectVersion, StorageNode, Stripe

DATABASE_URL = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://", 1)
TOKEN = os.environ["INTERNAL_TOKEN"]
engine = create_engine(DATABASE_URL, pool_pre_ping=True)


async def scrub_once(client: httpx.AsyncClient) -> int:
    with Session(engine) as session:
        rows = session.execute(select(Fragment, StorageNode).join(
            StorageNode, StorageNode.id == Fragment.storage_node_id
        ).join(Stripe, Stripe.id == Fragment.stripe_id).join(
            ObjectVersion, ObjectVersion.id == Stripe.version_id
        ).where(Fragment.status == "AVAILABLE", ObjectVersion.status == "AVAILABLE")).all()
        checks = [(fragment.id, fragment.sha256, fragment.size_bytes,
                   node.id, node.service_url, fragment.stripe_id) for fragment, node in rows]

    async def verify(item):
        fragment_id, expected_hash, expected_size, node_id, url, stripe_id = item
        try:
            response = await client.head(f"{url}/internal/fragments/{fragment_id}",
                                         headers={"X-Internal-Token": TOKEN}, timeout=15)
            intact = (response.status_code == 200
                      and response.headers.get("X-Fragment-SHA256") == expected_hash
                      and int(response.headers.get("Content-Length", "-1")) == expected_size)
            return item, intact, None if intact else f"HEAD returned {response.status_code} or checksum/size differed"
        except (httpx.HTTPError, ValueError) as error:
            return item, False, str(error)

    results = await asyncio.gather(*(verify(item) for item in checks))
    damaged = 0
    with Session(engine) as session, session.begin():
        for (fragment_id, _hash, _size, node_id, _url, stripe_id), intact, reason in results:
            if intact:
                continue
            fragment = session.get(Fragment, fragment_id)
            if fragment is None or fragment.status != "AVAILABLE":
                continue
            fragment.status = "LOST"
            stripe = session.get(Stripe, stripe_id)
            if stripe:
                stripe.status = "DEGRADED"
            session.add(ClusterEvent(id=str(uuid.uuid4()), event_type="FRAGMENT_INTEGRITY_FAILURE",
                                     severity="error", component="integrity-scrubber", node_id=node_id,
                                     message=f"Fragment {fragment_id} failed integrity verification",
                                     details={"stripe_id": stripe_id, "fragment_id": fragment_id,
                                              "reason": (reason or "unknown")[:500]}))
            damaged += 1
    return damaged


async def main():
    Base.metadata.create_all(engine)
    interval = int(os.getenv("SCRUB_INTERVAL_SECONDS", "300"))
    async with httpx.AsyncClient() as client:
        while True:
            try:
                count = await scrub_once(client)
                if count:
                    print(f"scrubber: marked {count} damaged fragment(s) for repair", flush=True)
            except Exception as error:
                print(f"scrubber: cycle failed: {error}", flush=True)
            await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(main())
