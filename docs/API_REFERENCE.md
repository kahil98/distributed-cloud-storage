# API reference

OpenAPI UI is served at `/docs`; JSON is at `/openapi.json`.

| Method | Path | Access | Behavior |
|---|---|---|---|
| POST | `/api/auth/register` | public | Create a user; password must be at least 12 characters. |
| POST | `/api/auth/login` | public | Return a signed bearer token. |
| GET | `/api/usage` | bearer | Return account bytes used, active upload reservations, and configured quota. |
| GET | `/api/cluster/nodes` | public read | Probe registered nodes and update health state. |
| GET | `/api/cluster/nodes/{node_id}/fragments` | bearer | Paginated fragment inventory for a node; regular users only see their own file fragments. |
| POST | `/api/admin/nodes` | admin token | Register a reachable node URL and its failure domain. |
| POST | `/api/admin/nodes/{node_id}/power` | admin bearer, local demo mode | JSON `{"action":"stop"}` or `{"action":"start"}` controls the actual Compose node container through the demo controller. |
| GET | `/api/admin/users` | admin bearer | List users with IDs, usernames, current usage, and quota. |
| PATCH | `/api/admin/users/{user_id}/quota` | admin bearer | Set `{"quota_bytes": 104857600}`; send `null` for unlimited. |
| POST | `/api/objects` | bearer | Multipart upload with field `file`; streams original input in 24 MiB stripes. |
| GET | `/api/objects` | bearer | List current user's objects; admin sees all. Admin may pass `owner_id` to filter. |
| GET | `/api/objects/{id}` | bearer | Read manifest subject to ownership. |
| GET | `/api/objects/{id}/download` | bearer | Verify fragments and reconstruct the original file; `X-Recovery-Details` reports missing, used, and reconstructed fragment indexes. |
| DELETE | `/api/objects/{id}` | bearer | Delete the object's fragments and mark the version deleted; admin may delete any object. |
| GET | `/api/admin/events` | admin bearer | Read paginated cluster events, optionally filtered by severity. |
| GET | `/metrics` | internal | Prometheus metrics endpoint. |

Storage-node internal endpoints include authenticated `PUT`, `GET`, `HEAD`, and `DELETE /internal/fragments/{fragment_id}`, plus `/internal/status`, `/internal/fragments`, and `/metrics`. `X-Internal-Token` is required for fragment access and inventory operations.

Node power control is disabled unless `DEMO_MODE=true`. In Compose, only the demo-controller mounts the Docker socket; it accepts a fixed allowlist of `storage-node-1` through `storage-node-8` and does not provide arbitrary command execution. Keep this controller in the isolated local demonstration environment.

Five failed logins for the same username trigger a 15-minute lockout shared across gateways through PostgreSQL. New accounts default to a 5 GiB quota. Uploads reserve quota before placing each stripe; reservations expire automatically after six hours if a gateway exits unexpectedly.
