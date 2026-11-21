from __future__ import annotations

import hashlib
import asyncio
import hmac
import os
import re
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

NODE_ID = os.getenv("NODE_ID", "storage-node-local")
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
TOKEN = os.getenv("INTERNAL_TOKEN", "development-only-change-me")
FRAGMENT_RE = re.compile(r"^[a-zA-Z0-9_-]{1,160}$")
WRITES = Counter("fragment_writes_total", "Committed fragment writes")
READS = Counter("fragment_reads_total", "Fragment reads")
NODE_CAPACITY = Gauge("storage_node_capacity_bytes", "Filesystem capacity", ["node_id"])
NODE_USED = Gauge("storage_node_used_bytes", "Filesystem used bytes", ["node_id"])
NODE_AVAILABLE = Gauge("storage_node_available_bytes", "Filesystem available bytes", ["node_id"])
NODE_FRAGMENTS = Gauge("storage_node_fragment_count", "Fragment files present", ["node_id"])
WRITE_LOCK = asyncio.Lock()
ACTIVE_WRITES = 0
RESERVED_BYTES = 0
app = FastAPI(title=f"Storage Node {NODE_ID}")


def path_for(fragment_id: str) -> Path:
    if not FRAGMENT_RE.fullmatch(fragment_id):
        raise HTTPException(400, "Invalid fragment ID")
    return DATA_DIR / fragment_id


def require_token(token: str | None) -> None:
    if not token or not hmac.compare_digest(token, TOKEN):
        raise HTTPException(401, "Invalid internal service credential")


@app.get("/health")
def health():
    return {"status": "healthy", "node_id": NODE_ID}


@app.get("/internal/status")
def status():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    total, used, free = shutil.disk_usage(DATA_DIR)
    count = sum(1 for p in DATA_DIR.iterdir() if p.is_file() and not p.name.startswith("."))
    NODE_CAPACITY.labels(NODE_ID).set(total)
    NODE_USED.labels(NODE_ID).set(used)
    NODE_AVAILABLE.labels(NODE_ID).set(free)
    NODE_FRAGMENTS.labels(NODE_ID).set(count)
    return {"node_id": NODE_ID, "status": "healthy", "capacity_bytes": total,
            "used_bytes": used, "available_bytes": free, "fragment_count": count, "active_writes": ACTIVE_WRITES, "reserved_bytes": RESERVED_BYTES}


@app.put("/internal/fragments/{fragment_id}")
async def put_fragment(fragment_id: str, request: Request, x_internal_token: str | None = Header(None)):
    global ACTIVE_WRITES, RESERVED_BYTES
    require_token(x_internal_token)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    target = path_for(fragment_id)
    try:
        expected_size = int(request.headers.get("content-length", "-1"))
    except ValueError:
        raise HTTPException(400, "Invalid Content-Length")
    if expected_size < 0 or expected_size > 64 * 1024 * 1024:
        raise HTTPException(411, "Content-Length required, maximum fragment size is 64 MiB")
    async with WRITE_LOCK:
        if shutil.disk_usage(DATA_DIR).free - RESERVED_BYTES < expected_size + 1024 * 1024:
            raise HTTPException(507, "Insufficient unreserved storage capacity")
        ACTIVE_WRITES += 1
        RESERVED_BYTES += expected_size
    fd = None
    temp_name = None
    digest = hashlib.sha256()
    size = 0
    try:
        fd, temp_name = tempfile.mkstemp(prefix=".incoming-", dir=DATA_DIR)
        with os.fdopen(fd, "wb") as output:
            fd = None
            async for block in request.stream():
                size += len(block)
                if size > expected_size:
                    raise HTTPException(400, "Body exceeds declared size")
                digest.update(block)
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        if size != expected_size:
            raise HTTPException(400, "Fragment body length mismatch")
        expected_hash = request.headers.get("x-fragment-sha256")
        if expected_hash and not hmac.compare_digest(digest.hexdigest(), expected_hash):
            raise HTTPException(422, "Fragment checksum mismatch")
        os.replace(temp_name, target)
        WRITES.inc()
        return {"fragment_id": fragment_id, "size_bytes": size, "sha256": digest.hexdigest()}
    except BaseException:
        if fd is not None:
            os.close(fd)
        if temp_name is not None:
            try: os.unlink(temp_name)
            except OSError: pass
        raise
    finally:
        if temp_name is not None:
            try: os.unlink(temp_name)
            except OSError: pass
        async with WRITE_LOCK:
            ACTIVE_WRITES -= 1
            RESERVED_BYTES -= expected_size


@app.get("/internal/fragments/{fragment_id}")
def get_fragment(fragment_id: str, x_internal_token: str | None = Header(None)):
    require_token(x_internal_token)
    target = path_for(fragment_id)
    if not target.is_file():
        raise HTTPException(404, "Fragment not found")
    READS.inc()
    content = target.read_bytes()
    return Response(content, media_type="application/octet-stream",
                    headers={"X-Fragment-SHA256": hashlib.sha256(content).hexdigest()})


@app.head("/internal/fragments/{fragment_id}")
def head_fragment(fragment_id: str, x_internal_token: str | None = Header(None)):
    require_token(x_internal_token)
    target = path_for(fragment_id)
    if not target.is_file(): raise HTTPException(404)
    return Response(headers={"Content-Length": str(target.stat().st_size),
                             "X-Fragment-SHA256": hashlib.sha256(target.read_bytes()).hexdigest()})


@app.delete("/internal/fragments/{fragment_id}")
def delete_fragment(fragment_id: str, x_internal_token: str | None = Header(None)):
    require_token(x_internal_token)
    target = path_for(fragment_id)
    if target.exists(): target.unlink()
    return {"deleted": True}


@app.get("/internal/fragments")
def list_fragments(x_internal_token: str | None = Header(None)):
    require_token(x_internal_token)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return {"node_id": NODE_ID, "fragments": [p.name for p in DATA_DIR.iterdir() if p.is_file() and not p.name.startswith(".")]}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
