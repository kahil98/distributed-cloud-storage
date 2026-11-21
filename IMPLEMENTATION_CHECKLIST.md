# Implementation checklist

This checklist reflects implemented code and checks performed in the project workspace.

## Foundation and storage
- [x] Backend API, storage-node service, React frontend, infrastructure, docs, and tests are present.
- [x] PostgreSQL models and initial Alembic migration cover users, buckets, objects, versions, stripes, fragments, nodes, events, audit records, and capacity reservations.
- [x] Alembic upgrades add per-user quotas/reservations and a PostgreSQL-backed sign-in throttle without dropping existing metadata.
- [x] Six storage services have independent Docker volumes; Compose also defines optional scale-out nodes 7 and 8.
- [x] Reed–Solomon 4+2 encode/decode implementation; all 15 two-fragment loss combinations pass.
- [x] Upload reads bounded stripes and reserves capacity transactionally across gateway processes.
- [x] Download validates fragments, stripes, and the complete object; it stages to a temporary file and streams the response without holding the full object in memory.
- [x] Placement requires healthy nodes in distinct failure domains and considers outstanding reservations.
- [x] Storage nodes verify internal auth and checksums, write atomically, and expose capacity and fragment status.

## Interface and operations
- [x] Two API gateways behind NGINX; Compose includes PostgreSQL, repair/rebalance workers, Prometheus, and Grafana.
- [x] React dashboard supports authentication, multi-file upload, object list/download/delete, six-fragment-per-stripe placement visualization, and checksums.
- [x] Dashboard shows a gateway/node topology with selected stripe placements, upload byte progress and cancel action, account quota/usage, editable admin quotas, and a live admin event feed.
- [x] Each node can expand into its paginated fragment inventory with file, stripe, data/parity type, size, checksum, and offline status; regular users are limited to their own files.
- [x] Successful downloads report fragment availability and decode inputs; the dashboard visualizes parity-assisted reconstruction and the admin event feed records degraded downloads.
- [x] Parity guide explains 4+2 coding and distinguishes rebuilding data for a download from the repair worker writing replacement fragments to nodes.
- [x] Node rows can expand into a paginated fragment inventory; users see their own fragments and admins can inspect all node contents.
- [x] Download responses describe missing and used fragments; the dashboard visualizes parity-assisted stripe reconstruction and records degraded-download events.
- [x] A parity explainer documents the 4+2 recovery steps and distinguishes per-download reconstruction from background fragment repair.
- [x] Admin file view lists all users' objects, filters by user, shows uploader names, and downloads through the existing ownership-checked object API.
- [x] Admin-only demo controls stop/start actual local storage-node containers; Docker API access is isolated to the restricted demo controller.
- [x] Login is throttled after five failed attempts per username for 15 minutes; failures are shared across gateway instances.
- [x] Upload quota reservation is coordinated in PostgreSQL across gateways; new accounts default to 5 GiB and admins can set a byte quota or unlimited.
- [x] Integrity scrubber verifies stored fragment size and SHA-256, marks damaged fragments, and records events for active objects.
- [x] Repair worker keeps per-fragment retry records and applies increasing retry delays up to five minutes.
- [x] Backup and restore guidance covers PostgreSQL metadata and each storage volume as one coordinated recovery set.
- [x] Session role is restored from the authenticated `/api/auth/me` endpoint on page reload, so admin controls remain available after refresh.
- [x] Kubernetes starter manifests and operational workflow docs are present.
- [x] Compose images build and services start; PostgreSQL initial migration exits successfully.
- [x] Frontend production build succeeds and is served by the Compose NGINX frontend.
- [x] `python -m compileall -q backend`, `npm run build`, and `docker compose config --quiet` succeed after the feature changes.
- [x] Alembic upgraded the existing database through `0003_auth_throttle`; PostgreSQL and stored node volumes were retained.
- [x] Admin login, `/api/usage`, `/api/admin/users`, and `/api/admin/events` respond successfully; existing user objects remain available.
- [x] Rebuilt Compose stack starts both gateways, the scrubber and workers, and all six storage nodes; health reports zero unavailable nodes.
- [x] Both gateways start; gateway health and cluster node API respond through NGINX.
- [x] All six configured storage nodes report healthy; Prometheus and Grafana health endpoints respond.
- [x] Live binary upload and download round-trip; SHA-256 matched and all six fragment placements were confirmed.
- [x] Stopped one actual storage-node container through the admin control API; health changed to OFFLINE; started it and observed HEALTHY.
- [x] Repeated the one-node outage after rebuilding: exactly the selected node showed OFFLINE, the other five remained HEALTHY, and all six were healthy after restore.
- [ ] Repair and rebalancing behavior under two simultaneous failures, worker crashes, and concurrent workloads still needs broader integration validation.
- [ ] Quota rejection, upload cancellation, node inventory filtering, offline-node parity reporting, integrity repair, and backup restore still need end-to-end exercise with disposable test data before a class deployment.

## Verified in this workspace
- [x] `python -m compileall -q backend`
- [x] `docker compose config --quiet`
- [x] `PYTHONPATH=backend python -m pytest backend/tests -q` — 10 passed.
- [x] `docker compose up --build -d` — all application images built; services started.
- [x] `GET /health`, `GET /api/cluster/nodes`, dashboard root, Grafana health, and Prometheus health return success.
- [x] One-stripe binary round-trip, manifest six-fragment placement, whole-file SHA-256, and object deletion.
- [x] Actual demo-node stop/start transitions through admin API, with persisted volume retained.
