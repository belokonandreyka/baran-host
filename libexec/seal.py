"""ChaCha20-Poly1305 (RFC 8439) in plain Python, for sealing push texts.

The push relay only forwards what it is given; the title and body are sealed
here with a key that only the phone and its own hosts know, and the phone's
notification extension opens them (CryptoKit's ChaChaPoly reads the same
"combined" layout: 12-byte nonce, ciphertext, 16-byte tag).

No dependencies: macOS's python3 has no `cryptography`, and a push is a few
hundred bytes, so speed does not matter.
"""
import os
import struct

AAD = b"baran-push-v1"
MASK = 0xFFFFFFFF


def _rotl(value, count):
    return ((value << count) & MASK) | (value >> (32 - count))


def _quarter(state, a, b, c, d):
    state[a] = (state[a] + state[b]) & MASK; state[d] = _rotl(state[d] ^ state[a], 16)
    state[c] = (state[c] + state[d]) & MASK; state[b] = _rotl(state[b] ^ state[c], 12)
    state[a] = (state[a] + state[b]) & MASK; state[d] = _rotl(state[d] ^ state[a], 8)
    state[c] = (state[c] + state[d]) & MASK; state[b] = _rotl(state[b] ^ state[c], 7)


def _block(key, counter, nonce):
    initial = [0x61707865, 0x3320646E, 0x79622D32, 0x6B206574,
               *struct.unpack("<8L", key), counter, *struct.unpack("<3L", nonce)]
    state = list(initial)
    for _ in range(10):
        _quarter(state, 0, 4, 8, 12); _quarter(state, 1, 5, 9, 13)
        _quarter(state, 2, 6, 10, 14); _quarter(state, 3, 7, 11, 15)
        _quarter(state, 0, 5, 10, 15); _quarter(state, 1, 6, 11, 12)
        _quarter(state, 2, 7, 8, 13); _quarter(state, 3, 4, 9, 14)
    return struct.pack("<16L", *((s + i) & MASK for s, i in zip(state, initial)))


def chacha20(key, counter, nonce, data):
    out = bytearray()
    for at in range(0, len(data), 64):
        stream = _block(key, counter + at // 64, nonce)
        out += bytes(x ^ y for x, y in zip(data[at:at + 64], stream))
    return bytes(out)


def poly1305(key, message):
    r = int.from_bytes(key[:16], "little") & 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF
    s = int.from_bytes(key[16:], "little")
    p = (1 << 130) - 5
    accumulator = 0
    for at in range(0, len(message), 16):
        chunk = message[at:at + 16] + b"\x01"
        accumulator = (accumulator + int.from_bytes(chunk, "little")) * r % p
    return ((accumulator + s) & ((1 << 128) - 1)).to_bytes(16, "little")


def _pad16(data):
    return b"\x00" * (-len(data) % 16)


def _tag(key, nonce, aad, ciphertext):
    one_time = _block(key, 0, nonce)[:32]
    mac_data = (aad + _pad16(aad) + ciphertext + _pad16(ciphertext)
                + struct.pack("<QQ", len(aad), len(ciphertext)))
    return poly1305(one_time, mac_data)


def seal(key, plaintext, aad=AAD, nonce=None):
    """nonce + ciphertext + tag."""
    if len(key) != 32:
        raise ValueError("key must be 32 bytes")
    nonce = nonce or os.urandom(12)
    ciphertext = chacha20(key, 1, nonce, plaintext)
    return nonce + ciphertext + _tag(key, nonce, aad, ciphertext)


def open_sealed(key, sealed, aad=AAD):
    """The plaintext, or ValueError when the box was not sealed with this key."""
    nonce, ciphertext, tag = sealed[:12], sealed[12:-16], sealed[-16:]
    expected = _tag(key, nonce, aad, ciphertext)
    if len(sealed) < 28 or not _equal(expected, tag):
        raise ValueError("not sealed with this key")
    return chacha20(key, 1, nonce, ciphertext)


def _equal(a, b):
    diff = len(a) ^ len(b)
    for x, y in zip(a, b):
        diff |= x ^ y
    return diff == 0
