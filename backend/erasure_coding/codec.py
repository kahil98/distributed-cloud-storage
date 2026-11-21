"""Bounded-memory 4+2 Reed-Solomon coding using the zfec implementation."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from zfec import Decoder, Encoder

K, M, N = 4, 2, 6


@dataclass(frozen=True)
class EncodedStripe:
    fragments: tuple[bytes, ...]
    original_size: int
    original_sha256: str


def encode_stripe(data: bytes, k: int = K, m: int = M) -> EncodedStripe:
    if (k, m) != (K, M):
        raise ValueError("This deployment currently supports Reed-Solomon 4+2 only")
    # zfec requires equal-sized data shards. Empty input is represented by six
    # empty fragments; non-empty input receives only the minimal byte padding.
    shard_size = (len(data) + k - 1) // k
    if shard_size == 0:
        parts = [b""] * k
        shards = [b""] * N
    else:
        padded = data + b"\0" * (shard_size * k - len(data))
        parts = [padded[i * shard_size:(i + 1) * shard_size] for i in range(k)]
        shards = Encoder(k, k + m).encode(parts)
    return EncodedStripe(tuple(shards), len(data), hashlib.sha256(data).hexdigest())


def decode_stripe(available_fragments: dict[int, bytes], original_size: int) -> bytes:
    if any(type(i) is not int or i < 0 or i >= N for i in available_fragments):
        raise ValueError("Fragment index must be in range 0..5")
    lengths = {len(value) for value in available_fragments.values()}
    if len(lengths) != 1 or original_size < 0 or (lengths and original_size > next(iter(lengths)) * K):
        raise ValueError("Invalid fragment sizes or original size")
    if len(available_fragments) < K:
        raise ValueError("At least four distinct fragments are required")
    selected = sorted(available_fragments)[:K]
    if any(i < 0 or i >= N for i in selected):
        raise ValueError("Fragment index must be in range 0..5")
    shards = [available_fragments[i] for i in selected]
    if not shards[0]:
        return b""
    recovered = Decoder(K, N).decode(shards, selected)
    return b"".join(recovered)[:original_size]


def reconstruct_fragment(available_fragments: dict[int, bytes], missing_index: int) -> bytes:
    if any(type(i) is not int or not 0 <= i < N for i in available_fragments):
        raise ValueError("Invalid source fragment index")
    if len({len(value) for value in available_fragments.values()}) != 1:
        raise ValueError("Source fragments must have equal sizes")
    if missing_index in available_fragments or not 0 <= missing_index < N:
        raise ValueError("Requested fragment must be a missing index in range 0..5")
    if len(available_fragments) < K:
        raise ValueError("At least four distinct fragments are required")
    selected = sorted(available_fragments)[:K]
    shards = [available_fragments[i] for i in selected]
    if not shards[0]:
        return b""
    data_shards = Decoder(K, N).decode(shards, selected)
    if missing_index < K:
        return data_shards[missing_index]
    # zfec's Python decoder returns the original k primary blocks. Re-encode
    # those recovered blocks to obtain a missing secondary/parity block.
    return Encoder(K, N).encode(data_shards)[missing_index]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_fragment(fragment: bytes, expected_checksum: str) -> bool:
    return sha256(fragment) == expected_checksum
