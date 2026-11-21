# Download workflow

The gateway authorizes the object owner, loads its version manifest, fetches each fragment from its recorded node, and checks the fragment SHA-256. If at least four distinct shard indexes remain verified, zfec reconstructs the primary data shards and the gateway trims each stripe to its original size. The final whole-file SHA-256 must match metadata before response bytes are returned. Verified stripes are staged in a temporary file, then streamed to the client and removed after the response completes. This bounds memory while requiring temporary disk space roughly equal to the object size.

Downloads survive up to two missing fragments per stripe while four verified shards remain.
