# Upload workflow

An authenticated client posts multipart field `file` through NGINX. The gateway reads 24 MiB stripes, calculates the whole-file SHA-256, encodes each stripe, refreshes node status, chooses six distinct nodes, and concurrently writes fragments with the internal service token. Node writes use a temporary file, fsync, and atomic rename. After all writes commit, one PostgreSQL transaction records the object, version, stripe, fragment mapping, event, and audit entry. Detected write or metadata errors trigger best-effort fragment cleanup.

An abrupt gateway termination between physical writes and metadata commit can leave orphan fragments; automated orphan collection is pending.
