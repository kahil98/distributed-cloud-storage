from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import uuid
import asyncio
import time
import tempfile
from urllib.parse import quote
from starlette.background import BackgroundTask
from datetime import datetime, timezone, timedelta

import httpx
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from fastapi.responses import StreamingResponse, FileResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

from erasure_coding.codec import K, M, decode_stripe, encode_stripe, sha256
from metadata.models import AuditLog, AuthRateLimit, Base, Bucket, ClusterEvent, Fragment, Object, ObjectVersion, StorageNode, Stripe, UserQuotaReservation
from placement_manager.placement import PlacementError
from metadata.models import User
from metadata.models import CapacityReservation
from metadata.capacity import reserve_placement, release_reservations
from security.auth import current_user, hash_password, issue_token, verify_password

STRIPE_BYTES = int(os.getenv("STRIPE_BYTES", str(24 * 1024 * 1024)))
TOKEN = os.getenv("INTERNAL_TOKEN", "development-only-change-me")
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"
DEMO_CONTROLLER_URL = os.getenv("DEMO_CONTROLLER_URL", "http://demo-controller:8010")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://storage:storage@localhost:5432/storage")
engine = create_engine(DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1), pool_pre_ping=True)
NODE_URLS = os.getenv("STORAGE_NODES", "").split(",")
NODE_IDS = os.getenv("STORAGE_NODE_IDS", ",".join(f"storage-node-{i}" for i in range(1, len(NODE_URLS) + 1))).split(",")
_domain_values = os.getenv("NODE_FAILURE_DOMAINS", ",".join(f"{node}=domain-{node}" for node in NODE_IDS)).split(",")
FAILURE_DOMAINS = ({part.split("=", 1)[0]: part.split("=", 1)[1] for part in _domain_values if "=" in part}
                   if any("=" in part for part in _domain_values) else dict(zip(NODE_IDS, _domain_values)))
app = FastAPI(title="Distributed Cloud Storage API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["https://kahil98.github.io"],
                   allow_credentials=False, allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
                   allow_headers=["Authorization", "Content-Type"],
                   expose_headers=["X-Recovery-Details"], max_age=3600)
logger = logging.getLogger("gateway")
_upload_health_lock = asyncio.Lock()
_last_upload_health_refresh = 0.0
UPLOADS = Counter("object_uploads_total", "Completed uploads")
ENCODED = Counter("erasure_encoded_bytes_total", "Encoded fragment bytes")


def is_deadlock(error: OperationalError) -> bool:
    return getattr(getattr(error, "orig", None), "sqlstate", None) == "40P01"


async def refresh_upload_health_once():
    """Coalesce health checks when a batch starts several uploads together."""
    global _last_upload_health_refresh
    if time.monotonic() - _last_upload_health_refresh < 3:
        return
    async with _upload_health_lock:
        if time.monotonic() - _last_upload_health_refresh < 3:
            return
        await refresh_cluster_state()
        _last_upload_health_refresh = time.monotonic()


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)


class NodeRegistration(BaseModel):
    service_url: str = Field(min_length=8, max_length=500)
    failure_domain: str = Field(min_length=1, max_length=100)


class NodePowerAction(BaseModel):
    action: str = Field(pattern=r"^(start|stop)$")


class QuotaUpdate(BaseModel):
    quota_bytes: int | None = Field(default=None, ge=0, le=109951162777600)


def reserve_user_quota(user_id: str, reservation_id: str, delta_bytes: int):
    """Reserve bytes under a user-row lock so concurrent gateways share the quota."""
    now = datetime.now(timezone.utc)
    with Session(engine) as session, session.begin():
        user = session.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None:
            raise HTTPException(401, "Account no longer exists")
        used = session.scalar(select(func.coalesce(func.sum(ObjectVersion.size_bytes), 0))
                              .join(Object, Object.id == ObjectVersion.object_id)
                              .where(Object.owner_id == user_id, ObjectVersion.status == "AVAILABLE")) or 0
        active = session.scalar(select(func.coalesce(func.sum(UserQuotaReservation.bytes_reserved), 0))
                                .where(UserQuotaReservation.user_id == user_id,
                                       UserQuotaReservation.expires_at > now)) or 0
        quota = user.quota_bytes
        if quota is not None and int(used) + int(active) + delta_bytes > quota:
            raise HTTPException(413, f"Account storage quota exceeded ({int(used)} of {quota} bytes used)")
        own = session.get(UserQuotaReservation, reservation_id)
        if own:
            own.bytes_reserved += delta_bytes
            own.expires_at = now + timedelta(hours=6)
        else:
            session.add(UserQuotaReservation(id=reservation_id, user_id=user_id,
                                             bytes_reserved=delta_bytes,
                                             expires_at=now + timedelta(hours=6)))


def release_user_quota(reservation_id: str):
    with Session(engine) as session, session.begin():
        row = session.get(UserQuotaReservation, reservation_id)
        if row:
            session.delete(row)


def record_login_failure(username: str):
    now = datetime.now(timezone.utc)
    for _ in range(2):
        try:
            with Session(engine) as session, session.begin():
                row = session.scalar(select(AuthRateLimit).where(
                    AuthRateLimit.username == username).with_for_update())
                if row is None:
                    session.add(AuthRateLimit(username=username, failures=1, window_started_at=now))
                else:
                    if row.window_started_at < now - timedelta(minutes=15):
                        row.failures = 0
                        row.window_started_at = now
                        row.locked_until = None
                    row.failures += 1
                    if row.failures >= 5:
                        row.locked_until = now + timedelta(minutes=15)
            return
        except Exception:
            if _ == 1:
                raise


def clear_login_failures(username: str):
    with Session(engine) as session, session.begin():
        row = session.get(AuthRateLimit, username)
        if row:
            session.delete(row)


@app.post("/api/auth/register")
def register(body: Credentials):
    with Session(engine) as session, session.begin():
        if session.scalar(select(User.id).where(User.username == body.username)):
            raise HTTPException(409, "Username already exists")
        user = User(id=str(uuid.uuid4()), username=body.username, password_hash=hash_password(body.password), role="user")
        session.add(user)
        session.flush()
        session.add(Bucket(id=str(uuid.uuid4()), name=f"u-{user.id.replace('-', '')}", owner_id=user.id,
                           access_policy={"private": True}))
        token = issue_token(user)
    return {"access_token": token, "token_type": "bearer", "role": "user"}


@app.post("/api/auth/login")
def login(body: Credentials):
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        throttle = session.get(AuthRateLimit, body.username)
        if throttle and throttle.locked_until and throttle.locked_until > now:
            retry_after = max(1, int((throttle.locked_until - now).total_seconds()))
            raise HTTPException(429, "Too many failed sign-in attempts. Try again in 15 minutes.",
                                headers={"Retry-After": str(retry_after)})
        user = session.scalar(select(User).where(User.username == body.username))
        if not user or not verify_password(body.password, user.password_hash):
            record_login_failure(body.username)
            raise HTTPException(401, "Invalid username or password")
        clear_login_failures(body.username)
        return {"access_token": issue_token(user), "token_type": "bearer", "role": user.role}


@app.get("/api/auth/me")
def who_am_i(claims=Depends(current_user)):
    return {"user_id": claims["sub"], "role": claims.get("role", "user")}


@app.get("/health")
async def health():
    return {"status": "healthy", "gateway": os.getenv("GATEWAY_ID", "gateway")}


async def node_status(client: httpx.AsyncClient, url: str):
    try:
        response = await client.get(url.rstrip("/") + "/internal/status", timeout=5)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError:
        return None


@app.get("/api/cluster/nodes")
async def nodes():
    states = await refresh_cluster_state()
    return {"nodes": states, "unavailable": len([s for s in states if s["status"] != "HEALTHY"])}


@app.get("/api/cluster/nodes/{node_id}/fragments")
def node_fragments(node_id: str, limit: int = Query(100, ge=1, le=500),
                   offset: int = Query(0, ge=0), claims=Depends(current_user)):
    with Session(engine) as session:
        node = session.get(StorageNode, node_id)
        if node is None:
            raise HTTPException(404, "Storage node not found")
        query = (select(Fragment, Stripe.stripe_index, ObjectVersion.id, ObjectVersion.manifest, Object.object_key,
                        Object.owner_id, ObjectVersion.status)
                 .join(Stripe, Stripe.id == Fragment.stripe_id)
                 .join(ObjectVersion, ObjectVersion.id == Stripe.version_id)
                 .join(Object, Object.id == ObjectVersion.object_id)
                 .where(Fragment.storage_node_id == node_id, ObjectVersion.status != "DELETED"))
        if claims.get("role") != "admin":
            query = query.where(Object.owner_id == claims["sub"])
        total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = session.execute(query.order_by(ObjectVersion.created_at.desc(), Stripe.stripe_index,
                                              Fragment.fragment_index).offset(offset).limit(limit)).all()
        output = []
        for fragment, stripe_index, version_id, manifest, object_key, owner_id, version_status in rows:
            output.append({"fragment_id": fragment.id, "object_id": version_id,
                           "filename": manifest.get("filename") or object_key.rsplit("/", 1)[-1],
                           "owner_id": owner_id, "stripe_index": stripe_index,
                           "fragment_index": fragment.fragment_index, "fragment_type": fragment.fragment_type,
                           "size_bytes": fragment.size_bytes, "sha256": fragment.sha256,
                           "fragment_status": fragment.status,
                           "storage_status": "NODE_OFFLINE" if node.status != "HEALTHY" else fragment.status,
                           "version_status": version_status})
        return {"node_id": node_id, "node_status": node.status, "total": int(total),
                "offset": offset, "limit": limit, "fragments": output}


async def refresh_cluster_state():
    with Session(engine) as session:
        registered = [(n.id, n.service_url) for n in session.scalars(select(StorageNode).order_by(StorageNode.id)).all()]
    known = {node_id: url for node_id, url in registered}
    for node_id, url in zip(NODE_IDS, NODE_URLS): known.setdefault(node_id, url)
    entries = list(known.items())
    async with httpx.AsyncClient() as client:
        states = await asyncio.gather(*(node_status(client, u) for _, u in entries))
    with Session(engine) as session, session.begin():
        for index, ((expected_id, url), state) in enumerate(zip(entries, states)):
            node_id = state["node_id"] if state else expected_id
            record = session.scalar(select(StorageNode).where(StorageNode.id == node_id).with_for_update())
            if record is None:
                record = StorageNode(id=node_id, hostname=node_id, service_url=url,
                                     failure_domain=FAILURE_DOMAINS.get(node_id, node_id))
                session.add(record)
            previous_status = record.status
            record.service_url = url
            now = datetime.now(timezone.utc)
            if state:
                record.status = "HEALTHY"
                record.capacity_bytes = state["capacity_bytes"]
                record.used_bytes = state["used_bytes"]
                record.available_bytes = state["available_bytes"]
                record.last_heartbeat = now
            else:
                last_seen = record.last_heartbeat
                if last_seen and last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=timezone.utc)
                # A single slow probe should not mark a working node offline.
                record.status = ("HEALTHY" if last_seen and
                                 (now - last_seen).total_seconds() < 12 else "OFFLINE")
            if previous_status != record.status:
                session.add(ClusterEvent(id=str(uuid.uuid4()), event_type="NODE_HEALTH_CHANGED",
                                         severity="info" if record.status == "HEALTHY" else "error", component="cluster-manager",
                                         node_id=node_id, message=f"Node {node_id} changed to {record.status}"))
    with Session(engine) as session:
        saved = {n.id: n for n in session.scalars(select(StorageNode)).all()}
        counts = dict(session.execute(select(Fragment.storage_node_id, func.count())
                                      .group_by(Fragment.storage_node_id)).all())
        reserved = dict(session.execute(select(CapacityReservation.node_id, func.coalesce(func.sum(CapacityReservation.bytes_reserved), 0))
                                        .where(CapacityReservation.expires_at > datetime.now(timezone.utc))
                                        .group_by(CapacityReservation.node_id)).all())
    output = []
    for index, state in enumerate(states):
        node_id = entries[index][0]
        if state:
            output.append({**state, "node_id": node_id, "status": "HEALTHY",
                           "reserved_bytes": int(reserved.get(node_id, 0))})
        else:
            record = saved[node_id]
            last_seen = record.last_heartbeat
            if last_seen and last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            display_status = ("SUSPECT" if record.status == "OFFLINE" and last_seen and
                              (datetime.now(timezone.utc) - last_seen).total_seconds() < 12 else record.status)
            output.append({"node_id": node_id, "status": display_status, "capacity_bytes": record.capacity_bytes,
                           "used_bytes": record.used_bytes, "available_bytes": record.available_bytes,
                           "fragment_count": counts.get(node_id, 0),
                           "reserved_bytes": int(reserved.get(node_id, 0))})
    return output


async def cleanup_fragments(records: list[dict], current_id: str | None = None,
                            current_nodes: list[str] | None = None):
    async with httpx.AsyncClient(timeout=20) as client:
        deletes = []
        for stripe in records:
            for fragment in stripe["fragments"]:
                deletes.append(client.delete(fragment["node"] + f"/internal/fragments/{fragment['fragment_id']}",
                                             headers={"X-Internal-Token": TOKEN}))
        if current_id and current_nodes:
            for index, url in enumerate(current_nodes):
                deletes.append(client.delete(url + f"/internal/fragments/{current_id}-{index}",
                                             headers={"X-Internal-Token": TOKEN}))
        if deletes: await asyncio.gather(*deletes, return_exceptions=True)


@app.post("/api/admin/nodes")
async def register_node(body: NodeRegistration, claims=Depends(current_user)):
    if claims.get("role") != "admin": raise HTTPException(403, "Administrator role required")
    async with httpx.AsyncClient() as client:
        status = await node_status(client, body.service_url)
    if not status: raise HTTPException(400, "Storage node did not return a valid status")
    node_id = status["node_id"]
    with Session(engine) as session, session.begin():
        node = session.get(StorageNode, node_id)
        if node is None:
            node = StorageNode(id=node_id, hostname=node_id, service_url=body.service_url,
                               failure_domain=body.failure_domain)
            session.add(node)
        node.service_url = body.service_url
        node.failure_domain = body.failure_domain
        node.capacity_bytes = status["capacity_bytes"]
        node.used_bytes = status["used_bytes"]
        node.available_bytes = status["available_bytes"]
        node.status = "HEALTHY"
        node.last_heartbeat = datetime.now(timezone.utc)
        session.add(ClusterEvent(id=str(uuid.uuid4()), event_type="NODE_JOINED", severity="info",
                                 component="cluster-manager", node_id=node_id,
                                 message=f"Storage node {node_id} joined the cluster"))
        session.add(AuditLog(id=str(uuid.uuid4()), actor_id=claims["sub"], action="storage_node.register",
                             target_type="storage_node", target_id=node_id,
                             details={"service_url": body.service_url, "failure_domain": body.failure_domain}))
    return {"node_id": node_id, "status": "HEALTHY", "failure_domain": body.failure_domain}


@app.post("/api/admin/nodes/{node_id}/power")
async def node_power(node_id: str, body: NodePowerAction, claims=Depends(current_user)):
    if claims.get("role") != "admin": raise HTTPException(403, "Administrator role required")
    if not DEMO_MODE: raise HTTPException(403, "Node power controls are disabled outside local demo mode")
    if node_id not in set(NODE_IDS) | {"storage-node-7", "storage-node-8"}:
        raise HTTPException(404, "Unknown demo storage node")
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.post(f"{DEMO_CONTROLLER_URL}/nodes/{node_id}/{body.action}",
                                         headers={"X-Demo-Control-Token": TOKEN})
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPError as error:
        raise HTTPException(503, "Demo node controller is unavailable") from error
    event_type = "NODE_STARTED" if body.action == "start" else "NODE_STOPPED"
    with Session(engine) as session, session.begin():
        session.add(ClusterEvent(id=str(uuid.uuid4()), event_type=event_type,
                                 severity="info" if result["running"] else "warning",
                                 component="demo-controller", node_id=node_id,
                                 message=f"Administrator {'started' if result['running'] else 'stopped'} {node_id}"))
        session.add(AuditLog(id=str(uuid.uuid4()), actor_id=claims["sub"], action=f"storage_node.{body.action}",
                             target_type="storage_node", target_id=node_id,
                             details={"changed": result["changed"], "demo_mode": True}))
    return result


@app.post("/api/objects")
async def upload(request: Request, file: UploadFile = File(...), claims=Depends(current_user)):
    await refresh_upload_health_once()
    safe_filename = (file.filename or "upload.bin").replace("\\", "/").split("/")[-1]
    safe_filename = safe_filename.replace('"', "_").replace("\r", "_").replace("\n", "_")[:255] or "upload.bin"
    with Session(engine) as session:
        url_for_node = {n.id: n.service_url.rstrip("/") for n in session.scalars(select(StorageNode)).all()}
    object_id = str(uuid.uuid4())
    quota_reservation_id = str(uuid.uuid4())
    file_hash = hashlib.sha256()
    total = 0
    stripe_count = 0
    records = []
    async with httpx.AsyncClient(timeout=120) as client:
        while True:
            if await request.is_disconnected():
                await cleanup_fragments(records)
                release_user_quota(quota_reservation_id)
                raise HTTPException(499, "Upload cancelled by client")
            raw = await file.read(STRIPE_BYTES)
            if not raw: break
            total += len(raw); file_hash.update(raw)
            encoded = encode_stripe(raw)
            stripe_id = f"{object_id}-{stripe_count}"
            fragment_sizes = [len(fragment) for fragment in encoded.fragments]
            try:
                reserve_user_quota(claims["sub"], quota_reservation_id, len(raw))
            except HTTPException:
                await cleanup_fragments(records)
                release_user_quota(quota_reservation_id)
                raise
            try:
                reservation_id, selected = reserve_placement(engine, stripe_id, fragment_sizes)
            except PlacementError as error:
                await cleanup_fragments(records)
                release_user_quota(quota_reservation_id)
                raise HTTPException(503, f"No safe fragment placement available: {error}") from error
            try:
                destinations = [url_for_node[node.node_id] for node in selected]
                writes = []
                for index, fragment in enumerate(encoded.fragments):
                    fragment_id = f"{stripe_id}-{index}"
                    writes.append(client.put(destinations[index] + f"/internal/fragments/{fragment_id}",
                                             content=fragment, headers={"X-Internal-Token": TOKEN, "X-Fragment-SHA256": sha256(fragment)}))
                results = await asyncio.gather(*writes, return_exceptions=True)
                if any(isinstance(r, Exception) or r.status_code >= 300 for r in results):
                    await cleanup_fragments(records, stripe_id, destinations)
                    release_user_quota(quota_reservation_id)
                    raise HTTPException(503, f"Stripe {stripe_count} failed to commit on all six nodes")
                if await request.is_disconnected():
                    await cleanup_fragments(records, stripe_id, destinations)
                    release_user_quota(quota_reservation_id)
                    raise HTTPException(499, "Upload cancelled by client")
                records.append({"stripe": stripe_count, "stripe_id": stripe_id,
                            "original_size_bytes": len(raw), "fragment_size_bytes": len(encoded.fragments[0]),
                            "original_sha256": encoded.original_sha256,
                            "fragments": [{"index": i, "type": "data" if i < K else "parity",
                                           "node": destinations[i], "node_id": selected[i].node_id,
                                           "fragment_id": f"{stripe_id}-{i}",
                                           "size_bytes": len(encoded.fragments[i]), "sha256": sha256(encoded.fragments[i])}
                                          for i in range(K + M)]})
                ENCODED.inc(sum(map(len, encoded.fragments)))
                stripe_count += 1
            finally:
                release_reservations(engine, reservation_id)
    if await request.is_disconnected():
        await cleanup_fragments(records)
        release_user_quota(quota_reservation_id)
        raise HTTPException(499, "Upload cancelled by client")
    result = {"id": object_id, "owner_id": claims["sub"], "filename": safe_filename, "size_bytes": total,
              "sha256": file_hash.hexdigest(), "stripes": records}
    try:
        for attempt in range(4):
            try:
                with Session(engine) as session, session.begin():
                    bucket_name = f"u-{claims['sub'].replace('-', '')}"
                    bucket = session.scalar(select(Bucket).where(Bucket.name == bucket_name))
                    if bucket is None:
                        session.execute(pg_insert(Bucket).values(
                            id=str(uuid.uuid4()), name=bucket_name, owner_id=claims["sub"],
                            access_policy={"private": True}
                        ).on_conflict_do_nothing(index_elements=[Bucket.name]))
                        bucket = session.scalar(select(Bucket).where(Bucket.name == bucket_name))
                    obj = Object(id=object_id, bucket_id=bucket.id, object_key=f"{object_id}/{result['filename']}", owner_id=claims["sub"])
                    version = ObjectVersion(id=object_id, object_id=object_id, version_number=1, size_bytes=total,
                                            sha256=result["sha256"], stripe_size_bytes=STRIPE_BYTES, manifest=result)
                    session.add_all([obj, version]); session.flush()
                    obj.current_version_id = version.id
                    for sm in records:
                        sr = Stripe(id=sm["stripe_id"], version_id=version.id, stripe_index=sm["stripe"],
                                    original_size_bytes=sm["original_size_bytes"],
                                    encoded_fragment_size_bytes=sm["fragment_size_bytes"],
                                    original_sha256=sm["original_sha256"], coding_parameters={"k": K, "m": M})
                        session.add(sr)
                    # Flush stripe rows before fragments because the models have no ORM relationships.
                    session.flush()
                    for sm in records:
                        for fm in sm["fragments"]:
                            session.add(Fragment(id=fm["fragment_id"], stripe_id=sm["stripe_id"],
                                                 fragment_index=fm["index"], fragment_type=fm["type"],
                                                 size_bytes=fm["size_bytes"], sha256=fm["sha256"],
                                                 storage_node_id=fm["node_id"]))
                    session.add(ClusterEvent(id=str(uuid.uuid4()), event_type="UPLOAD_COMPLETED", severity="info",
                                             component=os.getenv("GATEWAY_ID", "gateway"), object_id=object_id,
                                             message=f"Uploaded {result['filename']} with {len(records)} stripes"))
                    session.add(AuditLog(id=str(uuid.uuid4()), actor_id=claims["sub"], action="object.upload",
                                         target_type="object", target_id=object_id,
                                         details={"size_bytes": total, "sha256": result["sha256"]}))
                break
            except OperationalError as error:
                if not is_deadlock(error) or attempt == 3:
                    raise
                logger.warning("Retrying upload metadata commit after PostgreSQL deadlock (attempt %s)", attempt + 1)
                await asyncio.sleep(0.05 * (attempt + 1))
    except Exception as error:
        await cleanup_fragments(records)
        release_user_quota(quota_reservation_id)
        logger.exception("Upload metadata commit failed for object %s", object_id)
        raise HTTPException(500, "Could not commit upload metadata; stored fragments were cleaned up") from error
    release_user_quota(quota_reservation_id)
    UPLOADS.inc()
    return result


@app.on_event("startup")
def initialize_metadata():
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        for node_id, url in zip(NODE_IDS, NODE_URLS):
            if session.get(StorageNode, node_id) is None:
                session.add(StorageNode(id=node_id, hostname=node_id, service_url=url,
                                        failure_domain=FAILURE_DOMAINS.get(node_id, node_id), status="UNKNOWN"))
    username = os.getenv("ADMIN_USERNAME")
    password = os.getenv("ADMIN_PASSWORD")
    if username and password:
        with Session(engine) as session, session.begin():
            admin = session.scalar(select(User).where(User.username == username))
            if admin is None:
                session.add(User(id=str(uuid.uuid4()), username=username,
                                 password_hash=hash_password(password), role="admin"))
            elif not verify_password(password, admin.password_hash):
                # Keep the configured bootstrap credential in sync for existing installs.
                admin.password_hash = hash_password(password)


@app.get("/api/objects")
async def list_objects(owner_id: str | None = Query(None), claims=Depends(current_user)):
    with Session(engine) as session:
        query = select(ObjectVersion.manifest).join(Object, Object.id == ObjectVersion.object_id)
        query = query.where(ObjectVersion.status == "AVAILABLE")
        if claims.get("role") != "admin": query = query.where(Object.owner_id == claims["sub"])
        elif owner_id: query = query.where(Object.owner_id == owner_id)
        return list(session.scalars(query.order_by(ObjectVersion.created_at.desc())).all())


@app.get("/api/admin/users")
def list_users(claims=Depends(current_user)):
    if claims.get("role") != "admin": raise HTTPException(403, "Administrator role required")
    with Session(engine) as session:
        rows = session.scalars(select(User).order_by(User.username)).all()
        output = []
        for user in rows:
            used = session.scalar(select(func.coalesce(func.sum(ObjectVersion.size_bytes), 0))
                                  .join(Object, Object.id == ObjectVersion.object_id)
                                  .where(Object.owner_id == user.id, ObjectVersion.status == "AVAILABLE")) or 0
            output.append({"id": user.id, "username": user.username, "used_bytes": int(used),
                           "quota_bytes": user.quota_bytes})
        return output


@app.get("/api/usage")
def account_usage(claims=Depends(current_user)):
    with Session(engine) as session:
        user = session.get(User, claims["sub"])
        if user is None: raise HTTPException(401, "Account no longer exists")
        used = session.scalar(select(func.coalesce(func.sum(ObjectVersion.size_bytes), 0))
                              .join(Object, Object.id == ObjectVersion.object_id)
                              .where(Object.owner_id == user.id, ObjectVersion.status == "AVAILABLE")) or 0
        pending = session.scalar(select(func.coalesce(func.sum(UserQuotaReservation.bytes_reserved), 0))
                                 .where(UserQuotaReservation.user_id == user.id,
                                        UserQuotaReservation.expires_at > datetime.now(timezone.utc))) or 0
        return {"used_bytes": int(used), "reserved_bytes": int(pending), "quota_bytes": user.quota_bytes}


@app.patch("/api/admin/users/{user_id}/quota")
def update_user_quota(user_id: str, body: QuotaUpdate, claims=Depends(current_user)):
    if claims.get("role") != "admin": raise HTTPException(403, "Administrator role required")
    with Session(engine) as session, session.begin():
        user = session.get(User, user_id)
        if user is None: raise HTTPException(404, "User not found")
        user.quota_bytes = body.quota_bytes
        session.add(AuditLog(id=str(uuid.uuid4()), actor_id=claims["sub"], action="user.quota.update",
                             target_type="user", target_id=user_id,
                             details={"quota_bytes": body.quota_bytes}))
    return {"user_id": user_id, "quota_bytes": body.quota_bytes}


@app.get("/api/objects/{object_id}")
async def object_info(object_id: str, claims=Depends(current_user)):
    with Session(engine) as session:
        query = select(ObjectVersion.manifest).join(Object, Object.id == ObjectVersion.object_id).where(
            ObjectVersion.id == object_id, ObjectVersion.status == "AVAILABLE")
        if claims.get("role") != "admin": query = query.where(Object.owner_id == claims["sub"])
        value = session.scalar(query)
    if value is None: raise HTTPException(404, "Object not found")
    return value


@app.get("/api/objects/{object_id}/download")
async def download(object_id: str, claims=Depends(current_user)):
    with Session(engine) as session:
        query = select(ObjectVersion.manifest).join(Object, Object.id == ObjectVersion.object_id).where(
            ObjectVersion.id == object_id, ObjectVersion.status == "AVAILABLE")
        if claims.get("role") != "admin": query = query.where(Object.owner_id == claims["sub"])
        meta = session.scalar(query)
    if not meta: raise HTTPException(404, "Object not found in this gateway catalog")
    # Stage verified stripes on disk so memory stays bounded and a failed stripe
    # can still return an HTTP error before response headers are sent.
    fd, output_path = tempfile.mkstemp(prefix="verified-download-")
    digest = hashlib.sha256()
    recovery = {"filename": meta["filename"], "total_stripes": len(meta["stripes"]),
                "degraded_stripe_count": 0, "parity_stripe_count": 0,
                "reconstructed_data_fragment_count": 0, "stripes": [], "details_truncated": False}
    try:
        with os.fdopen(fd, "wb") as output:
            async with httpx.AsyncClient(timeout=120) as client:
                for stripe in meta["stripes"]:
                    fragments = stripe["fragments"]

                    async def probe(frag):
                        try:
                            response = await client.head(
                                frag["node"] + f"/internal/fragments/{frag['fragment_id']}",
                                headers={"X-Internal-Token": TOKEN})
                            intact = (response.status_code == 200
                                      and response.headers.get("X-Fragment-SHA256") == frag["sha256"]
                                      and int(response.headers.get("Content-Length", "-1")) == frag["size_bytes"])
                            return frag["index"], intact
                        except httpx.HTTPError:
                            return frag["index"], False
                        except ValueError:
                            return frag["index"], False

                    probe_results = await asyncio.gather(*(probe(frag) for frag in fragments))
                    head_available = {index for index, intact in probe_results if intact}
                    unavailable = {index for index, intact in probe_results if not intact}
                    available = {}
                    for frag in fragments:
                        index = frag["index"]
                        if index not in head_available:
                            continue
                        try:
                            response = await client.get(
                                frag["node"] + f"/internal/fragments/{frag['fragment_id']}",
                                headers={"X-Internal-Token": TOKEN})
                            if (response.status_code == 200 and len(response.content) == frag["size_bytes"]
                                    and sha256(response.content) == frag["sha256"]):
                                available[index] = response.content
                            else:
                                unavailable.add(index)
                        except httpx.HTTPError:
                            unavailable.add(index)
                        if len(available) == K:
                            break
                    if len(available) < K:
                        raise HTTPException(503, f"Stripe {stripe['stripe']} has fewer than four verified fragments")
                    used_indexes = sorted(available)[:K]
                    rebuilt_data = [index for index in range(K) if index not in used_indexes]
                    parity_used = any(index >= K for index in used_indexes)
                    if unavailable:
                        recovery["degraded_stripe_count"] += 1
                        recovery["parity_stripe_count"] += int(parity_used)
                        recovery["reconstructed_data_fragment_count"] += len(rebuilt_data)
                        recovery["stripes"].append({
                            "stripe": stripe["stripe"],
                            "used_indexes": used_indexes,
                            "missing_indexes": sorted(unavailable),
                            "reconstructed_data_indexes": rebuilt_data,
                            "parity_used": parity_used,
                            "fragments": [{"index": fragment["index"], "type": fragment["type"],
                                           "node_id": fragment["node_id"],
                                           "status": "USED" if fragment["index"] in used_indexes else
                                                    "MISSING" if fragment["index"] in unavailable else "AVAILABLE"}
                                          for fragment in fragments],
                        })
                    raw = decode_stripe(available, stripe["original_size_bytes"])
                    if sha256(raw) != stripe["original_sha256"]:
                        raise HTTPException(500, "Stripe checksum mismatch")
                    digest.update(raw)
                    output.write(raw)
        if digest.hexdigest() != meta["sha256"]:
            raise HTTPException(500, "Object checksum mismatch")
        recovery_json = json.dumps(recovery, separators=(",", ":"))
        recovery_header = base64.urlsafe_b64encode(recovery_json.encode()).decode().rstrip("=")
        while len(recovery_header) > 6000 and recovery["stripes"]:
            recovery["stripes"].pop()
            recovery["details_truncated"] = True
            recovery_json = json.dumps(recovery, separators=(",", ":"))
            recovery_header = base64.urlsafe_b64encode(recovery_json.encode()).decode().rstrip("=")
        if recovery["degraded_stripe_count"]:
            with Session(engine) as session, session.begin():
                session.add(ClusterEvent(
                    id=str(uuid.uuid4()), event_type="DEGRADED_DOWNLOAD_RECOVERED",
                    severity="warning" if recovery["parity_stripe_count"] else "info",
                    component=os.getenv("GATEWAY_ID", "gateway"), object_id=object_id,
                    message=(f"Downloaded {meta['filename']} with parity reconstruction"
                             if recovery["parity_stripe_count"] else
                             f"Downloaded {meta['filename']} with missing fragments"),
                    details={"filename": meta["filename"],
                             "degraded_stripe_count": recovery["degraded_stripe_count"],
                             "parity_stripe_count": recovery["parity_stripe_count"],
                             "reconstructed_data_fragment_count": recovery["reconstructed_data_fragment_count"]},
                ))
        return FileResponse(output_path, filename=meta["filename"], media_type="application/octet-stream",
                            headers={"X-Content-SHA256": meta["sha256"],
                                     "X-Recovery-Details": recovery_header,
                                     "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                                     "Pragma": "no-cache"},
                            background=BackgroundTask(os.unlink, output_path))
    except BaseException:
        os.unlink(output_path)
        raise



@app.delete("/api/objects/{object_id}")
async def delete_object(object_id: str, claims=Depends(current_user)):
    with Session(engine) as session:
        query = select(ObjectVersion).join(Object, Object.id == ObjectVersion.object_id).where(ObjectVersion.id == object_id)
        if claims.get("role") != "admin": query = query.where(Object.owner_id == claims["sub"])
        version = session.scalar(query)
        if version is None: raise HTTPException(404, "Object not found")
        manifest = version.manifest
        fragments = [(f, session.get(StorageNode, f["node_id"]))
                     for stripe in manifest["stripes"] for f in stripe["fragments"]]
    async with httpx.AsyncClient(timeout=30) as client:
        checks = await asyncio.gather(*(client.head(node.service_url + f"/internal/fragments/{frag['fragment_id']}",
                    headers={"X-Internal-Token": TOKEN}) if node else asyncio.sleep(0, result=None)
                    for frag,node in fragments), return_exceptions=True)
        if any(isinstance(check, Exception) or check is None or check.status_code not in (200, 404) for check in checks):
            raise HTTPException(503, "Cannot confirm every fragment node is reachable; object was not deleted")
        with Session(engine) as session, session.begin():
            row = session.get(ObjectVersion, object_id)
            row.status = "DELETING"
        results = await asyncio.gather(*(client.delete(node.service_url + f"/internal/fragments/{frag['fragment_id']}",
                            headers={"X-Internal-Token": TOKEN}) for frag,node in fragments if node), return_exceptions=True)
    successful = all(not isinstance(result, Exception) and result.status_code < 300 for result in results)
    with Session(engine) as session, session.begin():
        row = session.get(ObjectVersion, object_id)
        row.status = "DELETED" if successful else "DEGRADED"
        session.add(ClusterEvent(id=str(uuid.uuid4()), event_type="OBJECT_DELETED" if successful else "OBJECT_DELETE_INCOMPLETE",
                                 severity="info" if successful else "warning", component=os.getenv("GATEWAY_ID", "gateway"),
                                 object_id=object_id, message="Object fragment deletion completed" if successful else "Some fragment deletes failed"))
        session.add(AuditLog(id=str(uuid.uuid4()), actor_id=claims["sub"], action="object.delete",
                             target_type="object", target_id=object_id, details={"complete": successful}))
    if not successful: raise HTTPException(503, "Some fragments could not be deleted; object is marked degraded")
    return {"deleted": True, "object_id": object_id}


@app.get("/api/admin/events")
def get_events(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
               severity: str | None = None, claims=Depends(current_user)):
    if claims.get("role") != "admin": raise HTTPException(403, "Administrator role required")
    query = select(ClusterEvent).order_by(ClusterEvent.timestamp.desc()).offset(offset).limit(limit)
    if severity: query = query.where(ClusterEvent.severity == severity)
    with Session(engine) as session:
        rows = session.scalars(query).all()
        return [{"id": e.id, "type": e.event_type, "severity": e.severity, "component": e.component,
                 "node_id": e.node_id, "object_id": e.object_id, "message": e.message,
                 "details": e.details, "timestamp": e.timestamp} for e in rows]


@app.get("/metrics")
def metrics(): return StreamingResponse(iter([generate_latest()]), media_type=CONTENT_TYPE_LATEST)
