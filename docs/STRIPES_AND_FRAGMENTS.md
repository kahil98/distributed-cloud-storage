# Stripes and fragments

The gateway reads up to 24 MiB of original file bytes at a time. It pads the final stripe only enough to make four equal-sized data blocks. A full 24 MiB stripe produces six 6 MiB shards. A 1 MiB stripe produces six 256 KiB shards. Metadata records original stripe length and checksum so downloads remove padding and verify the result. Transport reads, original-data stripes, and stored fragments are separate units.

Encoding is bounded by one stripe, but the current download endpoint buffers the complete object in process memory before responding.
