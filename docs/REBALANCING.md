# Rebalancing

The rebalance worker is enabled after at least seven healthy nodes exist. It compares fragment counts, selects a move from a more-loaded node to a less-loaded eligible node, and excludes failure domains already used by that stripe. It copies the fragment, verifies its checksum, updates fragment and version-manifest placement inside a metadata transaction, then deletes the old copy. It moves at most one fragment each cycle.

The worker runs automatically and has no preview, pause, resume, progress UI, or detailed throughput controls yet. It has not been exercised against a live cluster.
