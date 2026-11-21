# Distributed Cloud Storage

An in-progress production-inspired object storage project. The repository includes an authenticated FastAPI gateway, PostgreSQL/Alembic metadata, separate persistent storage-node services, deterministic 4+2 Reed–Solomon stripe logic through `zfec`, capacity-aware weighted rendezvous placement with expiring transactional reservations, registered node membership, repair and rebalance workers, a React dashboard, NGINX routing, Compose, Prometheus/Grafana, and Kubernetes starter manifests.

This work is not production-ready. The implementation checklist records completed checks; see [Known limitations](docs/KNOWN_LIMITATIONS.md), [Architecture](docs/ARCHITECTURE.md), and the [demo guide](docs/DEMO_GUIDE.md) for scope and operation.

## Run the local demonstration

1. Copy `.env.example` to `.env` and replace every placeholder with a unique secret/password. Use URL-safe characters for database passwords (`A-Z`, `a-z`, digits, `_`, `-`).
2. Start the services: `docker compose up --build`.
3. Open the dashboard at <http://localhost:8080>. Sign in with `ADMIN_USERNAME` and `ADMIN_PASSWORD`; regular users can create accounts from the sign-in screen.
4. API documentation: <http://localhost:8080/docs>. Grafana: <http://localhost:3002>. Prometheus: <http://localhost:9091>.

The gateway accepts multipart uploads at `POST /api/objects` with a bearer token. The UI handles sign-in, concurrent multi-file uploads with per-file progress/cancellation, listing, download, and deletion. Selecting multiple files starts each file's striping and fragment placement concurrently. Expand **Inspect 4+2 fragment layout** on any file to see each stripe's D1–D4 and P1–P2 fragments, assigned node, size, and checksum. Open **View fragments** on a node to inspect its stored fragment inventory. The topology view highlights a selected stripe's placements. After a download, the recovery panel shows offline fragments, the four fragments used, and any data rebuilt with parity. The parity guide explains the process; the admin event feed records degraded downloads. Admins can browse files by username and set per-user quotas. New accounts default to 5 GiB; admins can set another MiB value or leave the quota unlimited. Administrators can stop or start actual local node containers from the node list; each node's volume is preserved. For API use, obtain an access token with `POST /api/auth/login` (JSON `username` and `password`) and send `Authorization: Bearer <access_token>`.

The repair worker persists repair status and applies increasing retry delays. The integrity scrubber checks stored fragment sizes and checksums every five minutes by default. See [backup and restore](docs/BACKUP_RESTORE.md) before moving or recovering stored data.

The generated frontend bundle is checked in so Compose can build without fetching npm packages. After editing frontend source, regenerate it with `cd frontend; npm ci; npm run build` (PowerShell) before rebuilding Compose.

To register another reachable node as an administrator, call `POST /api/admin/nodes` with `service_url` and `failure_domain`. The node must run the storage-node app and share `INTERNAL_TOKEN`. Each stripe requires six distinct healthy failure domains with capacity. To add a local Compose node, create a service with its own persistent volume and add its URL and ID to the gateway configuration; do not reuse a storage volume between nodes.

To start the included seventh node, run `docker compose --profile scaleout up -d storage-node-7`. Sign in at the dashboard, copy the bearer token from the `/api/auth/login` response if using the API, then call `POST /api/admin/nodes` with `{"service_url":"http://storage-node-7:8001","failure_domain":"host-7"}`. For Node 8, use `storage-node-8` and a separate failure-domain value. Each profile node owns its own named volume.

## Verification

With Python dependencies available: `python -m pip install -r backend/requirements.txt`, `$env:PYTHONPATH='backend'`, then `python -m pytest backend/tests -q` (PowerShell). Linux/macOS equivalent: `PYTHONPATH=backend python -m pytest backend/tests -q`.

The Python suite covers erasure coding, all 15 two-fragment-loss combinations, placement, storage-node operations, and authentication. Run `docker compose config --quiet` to validate the Compose file. Container and frontend startup status is tracked in [IMPLEMENTATION_CHECKLIST.md](IMPLEMENTATION_CHECKLIST.md).

## Persistent data and limitations

Named volumes `postgres_data`, `storage1`…`storage8`, `prometheus_data`, and `grafana_data` persist through normal restarts. `docker compose down` retains them. `docker compose down -v` deletes all named volumes and stored data.

The storage containers run on one Docker host, so they do not provide physical host or rack fault tolerance. PostgreSQL is one instance. Downloads stage the verified object on temporary disk before streaming. Complete garbage collection, durable rebalance queues, prepared Grafana dashboards, token revocation/refresh, and production security/HA remain incomplete. This is a university/demo prototype.
