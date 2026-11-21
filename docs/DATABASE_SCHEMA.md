# Database schema

Alembic creates the normalized `users`, `buckets`, `objects`, `object_versions`, `stripes`, `fragments`, `storage_nodes`, `cluster_events`, `repair_jobs`, and `rebalance_jobs` tables. Foreign keys and uniqueness constraints keep object hierarchy and per-stripe fragment indexes coherent. Object-version JSONB manifests preserve the gateway's response representation while fragment records provide queryable placement metadata.

Compose provisions a single PostgreSQL instance and persistent volume. Before production use, configure regular backups and test restore procedures. The single instance is a deployment single point of failure; use a managed HA PostgreSQL service or a reviewed HA cluster for production.
