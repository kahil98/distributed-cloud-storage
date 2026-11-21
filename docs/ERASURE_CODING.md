# Erasure coding

The codec wraps zfec's C-backed systematic Reed–Solomon implementation with k=4 primary data blocks and n=6 total blocks. `Encoder(4, 6)` emits four systematic data shards and two parity shards. `Decoder(4, 6).decode(shards, indexes)` recovers the four original primary shards; a missing parity shard is then recreated by encoding those recovered primary shards. Each stored fragment has a SHA-256 checksum in metadata. This library API is checked against the [official zfec documentation](https://github.com/tahoe-lafs/zfec).

The source includes tests for all 15 pairs of missing fragments. Those tests still need to run in an environment with zfec installed.
