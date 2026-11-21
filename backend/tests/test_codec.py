import itertools

from erasure_coding.codec import encode_stripe, decode_stripe, reconstruct_fragment, sha256


def test_all_two_fragment_loss_combinations():
    original = bytes(range(256)) * 37 + b"tail"
    encoded = encode_stripe(original)
    assert len(encoded.fragments) == 6
    for missing in itertools.combinations(range(6), 2):
        available = {i: shard for i, shard in enumerate(encoded.fragments) if i not in missing}
        assert decode_stripe(available, len(original)) == original
        assert reconstruct_fragment(available, missing[0]) == encoded.fragments[missing[0]]
    assert sha256(original) == encoded.original_sha256


def test_empty_and_small_binary_stripes():
    for value in (b"", b"\x00", b"\xff" * 1024, bytes(range(251))):
        encoded = encode_stripe(value)
        assert decode_stripe(dict(enumerate(encoded.fragments[:4])), len(value)) == value


def test_insufficient_fragments_rejected():
    try:
        decode_stripe({0: b"a", 1: b"b", 2: b"c"}, 3)
        assert False, "expected ValueError"
    except ValueError:
        pass
