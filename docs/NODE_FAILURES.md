# Node failures

The gateway's cluster endpoint and repair worker probe each registered storage service. A missed probe changes persisted node status and creates a cluster event. Placement excludes nodes not marked healthy. The repair worker rechecks node health periodically and marks impacted stripes degraded or unavailable according to the number of verified shards.

In Compose, stop a storage service with `docker compose stop storage-node-2` and restore it with `docker compose start storage-node-2`. Six containers on one host do not model separate hardware failures. The web dashboard does not expose a node stop control.
