# Self-healing

The repair worker scans persisted stripes, probes node health, and reads fragment contents to verify checksums. If at least four valid shards remain, it attempts to reconstruct each missing or corrupt shard. Replacement placement requires a healthy destination failure domain not already holding another shard from that stripe. If capacity or domains are insufficient, the stripe remains degraded and can be repaired after capacity is added.

The worker is a periodic database scan rather than a durable message queue. Queue visibility, bounded concurrency, retries/backoff, operator controls, and large-scale efficiency remain unfinished.
