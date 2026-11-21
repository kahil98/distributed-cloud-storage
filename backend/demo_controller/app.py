from __future__ import annotations

import json
import hmac
import os
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Header, HTTPException

TOKEN = os.getenv("DEMO_CONTROL_TOKEN", "")
PROJECT = os.getenv("COMPOSE_PROJECT_NAME", "distributed-cloud-storage")
ALLOWED_NODES = {f"storage-node-{i}" for i in range(1, 9)}
app = FastAPI(title="Local demo node controller")


def authorize(token: str | None) -> None:
    if not TOKEN or not token or not hmac.compare_digest(token, TOKEN):
        raise HTTPException(401, "Invalid demo control credential")


async def find_container(client: httpx.AsyncClient, node_id: str) -> dict:
    if node_id not in ALLOWED_NODES:
        raise HTTPException(404, "Unknown demo storage node")
    filters = quote(json.dumps({"label": [
        f"com.docker.compose.project={PROJECT}",
        f"com.docker.compose.service={node_id}",
    ]}), safe="")
    response = await client.get(f"/containers/json?all=1&filters={filters}")
    response.raise_for_status()
    candidates = [c for c in response.json()
                  if c.get("Labels", {}).get("com.docker.compose.project") == PROJECT
                  and c.get("Labels", {}).get("com.docker.compose.service") == node_id]
    if not candidates:
        raise HTTPException(404, "Node container is not present in this Compose project")
    if len(candidates) > 1:
        raise HTTPException(409, "More than one matching node container was found")
    return candidates[0]


@app.get("/health")
def health():
    return {"status": "healthy", "mode": "local-demo-only"}


@app.post("/nodes/{node_id}/{action}")
async def control_node(node_id: str, action: str, x_demo_control_token: str | None = Header(None)):
    authorize(x_demo_control_token)
    if action not in {"start", "stop"}:
        raise HTTPException(400, "Action must be start or stop")
    async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds="/var/run/docker.sock"),
                                 base_url="http://docker", timeout=20) as client:
        container = await find_container(client, node_id)
        if action == "stop" and container.get("State") != "running":
            return {"node_id": node_id, "running": False, "changed": False}
        if action == "start" and container.get("State") == "running":
            return {"node_id": node_id, "running": True, "changed": False}
        response = await client.post(f"/containers/{container['Id']}/{action}?t=5")
        if response.status_code not in (204, 304):
            raise HTTPException(502, f"Docker could not {action} the storage node")
    return {"node_id": node_id, "running": action == "start", "changed": True}
