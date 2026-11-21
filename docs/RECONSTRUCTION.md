# Reconstruction

The download path decodes each stripe from any four checksum-verified shard indexes. The repair worker uses the same zfec codec to recreate missing data shards and re-encodes recovered data blocks when it needs to recreate a parity shard. It verifies the reconstructed fragment length and checksum before writing it to a destination node and changing placement metadata.

No repair is reported complete until the destination write succeeds and the metadata transaction records its new location.
