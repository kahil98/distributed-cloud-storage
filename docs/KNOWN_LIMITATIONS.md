# Known limitations

The current repository is a production-inspired, single-host reference implementation. It is not yet a production-hardened storage service.

- A process crash after fragments are written but before metadata commit can leave unreferenced fragment files. Error paths clean up, but a periodic orphan-fragment collector is still needed.
- Repair and rebalancing run as periodic workers without a durable work queue, operator pause controls, or complete crash recovery.
- Multi-node deletion can be retried manually after a partial failure; lifecycle garbage collection and a deletion retry worker are not implemented.
- Object version rows exist, but version replacement, resumable upload sessions, and bucket management APIs are not implemented.
- Authentication uses signed bearer tokens and scrypt password hashes. Token revocation/refresh, rate limiting, TLS termination, and production secret rotation need deployment-specific implementation.
- The dashboard is a basic operational UI; event history and a cluster topology graph are still missing. Administrator node controls stop/start actual local Compose containers through a demo-only controller; the controller requires the Docker socket and must remain disabled outside the isolated local demonstration setup.
- Prometheus metrics cover gateway upload/encoded bytes and storage-node fragment reads/writes. A broader alert set and operational Grafana dashboard need to be added.
- Kubernetes manifests are starter manifests, not a validated multi-host deployment. Dynamic node discovery, backup/restore drills, and PostgreSQL high availability remain out of scope.
- Downloads stage the complete verified object to local temporary disk before streaming it to the client. This bounds memory and lets the gateway verify the full object before sending headers, but requires temporary disk space roughly equal to the object size.
- Capacity reservations expire after ten minutes. Long-running writes can outlive the lease; lease renewal is not implemented yet.
