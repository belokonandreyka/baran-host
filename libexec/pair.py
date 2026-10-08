#!/usr/bin/env python3
"""Shows a QR code that adds this machine to the Baran iOS app.

Run it on the machine you want to connect to, then in the app: + → Scan QR.

  baran pair                  new key for the phone + QR with everything
  baran pair --no-key         QR with the address only; pick the key in the app
  baran pair --host 10.0.0.5  address the phone should use (default: this
                              machine's address on the local network)
  baran pair --port 2222 --name NAS --user me --command herdr

By default it creates a fresh ed25519 key, appends its public half to
~/.ssh/authorized_keys (comment "baran <date>", so it is easy to find
and remove) and puts the private half into the QR code only: it is never left
on disk. Whoever photographs the code can log in as you, so show it only to
your own phone; it is wiped from the screen when you press Enter.

Needs nothing but Python 3 and ssh-keygen.
"""
import argparse
import base64
import getpass
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

# --- QR code: byte mode, error correction L, after Nayuki's reference encoder.

ECC_PER_BLOCK = [7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28,
                 28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30]
BLOCKS = [1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8,
          8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25]

EXP, LOG = [0] * 512, [0] * 256
_x = 1
for _i in range(255):
    EXP[_i], LOG[_x] = _x, _i
    _x = (_x << 1) ^ (0x11D if _x & 0x80 else 0)
for _i in range(255, 512):
    EXP[_i] = EXP[_i - 255]


def gf_mul(a, b):
    return EXP[LOG[a] + LOG[b]] if a and b else 0


def rs_divisor(degree):
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = gf_mul(root, 2)
    return result


def rs_remainder(data, divisor):
    result = [0] * len(divisor)
    for byte in data:
        factor = byte ^ result.pop(0)
        result.append(0)
        for i, coefficient in enumerate(divisor):
            result[i] ^= gf_mul(coefficient, factor)
    return result


def raw_modules(version):
    result = (16 * version + 128) * version + 64
    if version >= 2:
        aligns = version // 7 + 2
        result -= (25 * aligns - 10) * aligns - 55
        if version >= 7:
            result -= 36
    return result


def data_codewords(version):
    return raw_modules(version) // 8 - ECC_PER_BLOCK[version - 1] * BLOCKS[version - 1]


def qr_matrix(payload):
    """Rows of booleans (True = dark) for the smallest code that holds `payload`."""
    for version in range(1, 41):
        count_bits = 8 if version <= 9 else 16
        if 4 + count_bits + 8 * len(payload) <= 8 * data_codewords(version):
            break
    else:
        raise ValueError("too much data for a QR code")
    capacity = data_codewords(version)
    bits = [0, 1, 0, 0] + [len(payload) >> i & 1 for i in range(count_bits - 1, -1, -1)]
    for byte in payload:
        bits += [byte >> i & 1 for i in range(7, -1, -1)]
    bits += [0] * min(4, capacity * 8 - len(bits))
    bits += [0] * (-len(bits) % 8)
    data = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    data += [0xEC, 0x11] * capacity
    data = data[:capacity]

    blocks_count, ecc_len = BLOCKS[version - 1], ECC_PER_BLOCK[version - 1]
    total = raw_modules(version) // 8
    short_blocks = blocks_count - total % blocks_count
    short_len = total // blocks_count
    divisor = rs_divisor(ecc_len)
    blocks, at = [], 0
    for i in range(blocks_count):
        chunk = data[at:at + short_len - ecc_len + (0 if i < short_blocks else 1)]
        at += len(chunk)
        ecc = rs_remainder(chunk, divisor)
        if i < short_blocks:
            chunk = chunk + [0]
        blocks.append(chunk + ecc)
    codewords = []
    for i in range(len(blocks[0])):
        for j, block in enumerate(blocks):
            if i != short_len - ecc_len or j >= short_blocks:
                codewords.append(block[i])

    size = version * 4 + 17
    dark = [[False] * size for _ in range(size)]
    fixed = [[False] * size for _ in range(size)]

    def put(x, y, value):
        if 0 <= x < size and 0 <= y < size:
            dark[y][x] = bool(value)
            fixed[y][x] = True

    for i in range(size):
        put(6, i, i % 2 == 0)
        put(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                put(cx + dx, cy + dy, max(abs(dx), abs(dy)) not in (2, 4))
    if version > 1:
        aligns = version // 7 + 2
        step = 26 if version == 32 else (version * 4 + aligns * 2 + 1) // (aligns * 2 - 2) * 2
        positions = [6] + sorted(size - 7 - i * step for i in range(aligns - 1))
        last = len(positions) - 1
        for i, cx in enumerate(positions):
            for j, cy in enumerate(positions):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        put(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)
    if version >= 7:
        remainder = version
        for _ in range(12):
            remainder = (remainder << 1) ^ ((remainder >> 11) * 0x1F25)
        version_bits = version << 12 | remainder
        for i in range(18):
            bit = version_bits >> i & 1
            put(size - 11 + i % 3, i // 3, bit)
            put(i // 3, size - 11 + i % 3, bit)

    def put_format(mask):
        value = 1 << 3 | mask  # error correction level L
        remainder = value
        for _ in range(10):
            remainder = (remainder << 1) ^ ((remainder >> 9) * 0x537)
        format_bits = (value << 10 | remainder) ^ 0x5412
        bit = lambda i: format_bits >> i & 1
        for i in range(6):
            put(8, i, bit(i))
        put(8, 7, bit(6))
        put(8, 8, bit(7))
        put(7, 8, bit(8))
        for i in range(9, 15):
            put(14 - i, 8, bit(i))
        for i in range(8):
            put(size - 1 - i, 8, bit(i))
        for i in range(8, 15):
            put(8, size - 15 + i, bit(i))
        put(8, size - 8, True)

    put_format(0)  # reserves the cells
    at = 0
    for right in range(size - 1, 0, -2):
        if right <= 6:
            right -= 1
        for vertical in range(size):
            for j in range(2):
                x = right - j
                upward = (right + 1) & 2 == 0
                y = size - 1 - vertical if upward else vertical
                if not fixed[y][x] and at < len(codewords) * 8:
                    dark[y][x] = bool(codewords[at >> 3] >> (7 - (at & 7)) & 1)
                    at += 1

    masks = [
        lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
        lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
        lambda x, y: x * y % 2 + x * y % 3 == 0, lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
        lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
    ]

    def apply(mask):
        for y in range(size):
            for x in range(size):
                if not fixed[y][x] and masks[mask](x, y):
                    dark[y][x] = not dark[y][x]

    def penalty():
        """Long runs, 2×2 blocks and an uneven dark share make a code harder to read."""
        score = 0
        for lines in (dark, list(zip(*dark))):
            for line in lines:
                run = 1
                for a, b in zip(line, line[1:]):
                    run = run + 1 if a == b else 1
                    score += 3 if run == 5 else 1 if run > 5 else 0
        for y in range(size - 1):
            for x in range(size - 1):
                if dark[y][x] == dark[y][x + 1] == dark[y + 1][x] == dark[y + 1][x + 1]:
                    score += 3
        share = sum(map(sum, dark)) * 100 // (size * size)
        return score + abs(share - 50) // 5 * 10

    best = None
    for mask in range(8):
        apply(mask)
        put_format(mask)
        score = penalty()
        if best is None or score < best[0]:
            best = (score, mask)
        apply(mask)  # undo
    apply(best[1])
    put_format(best[1])
    return dark


def render(matrix, quiet=2):
    """Two rows per text line, dark on white whatever the terminal theme is."""
    size = len(matrix) + 2 * quiet
    cell = lambda x, y: (0 <= x - quiet < len(matrix) and 0 <= y - quiet < len(matrix)
                         and matrix[y - quiet][x - quiet])
    lines = []
    for y in range(0, size, 2):
        row = "".join(" ▄▀█"[2 * cell(x, y) + cell(x, y + 1)] for x in range(size))
        lines.append("\033[30;107m" + row + "\033[0m")
    return "\n".join(lines)


# --- Pairing


def local_address():
    """The address other devices on the network reach this machine at."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))  # picks the outgoing interface; sends nothing
        return probe.getsockname()[0]
    except OSError:
        return socket.gethostname()
    finally:
        probe.close()


def new_key(authorized_keys):
    """Authorizes a fresh key and returns its private half as one base64 line."""
    comment = "baran " + time.strftime("%Y-%m-%d")
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "key")
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", comment, "-f", path], check=True)
        private = open(path).read()
        public = open(path + ".pub").read().strip()
    os.makedirs(os.path.dirname(authorized_keys), mode=0o700, exist_ok=True)
    existing = open(authorized_keys).read() if os.path.exists(authorized_keys) else ""
    with open(os.open(authorized_keys, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a") as out:
        out.write(("" if not existing or existing.endswith("\n") else "\n") + public + "\n")
    return seed_of(private), comment


def seed_of(private):
    """The 32-byte ed25519 seed of an unencrypted OpenSSH key, base64. The app
    rebuilds the key file from it, so the code stays small (41 modules, not 69)."""
    blob = base64.b64decode("".join(line for line in private.splitlines() if not line.startswith("-----")))
    at = len(b"openssh-key-v1\0")

    def field():
        nonlocal at
        size = int.from_bytes(blob[at:at + 4], "big")
        at += 4 + size
        return blob[at - size:at]

    field(), field(), field()   # cipher, kdf, kdf options: none for a fresh key
    at += 4                     # number of keys
    field()                     # public key
    section = field()
    at, blob = 8, section       # skip the two check words
    if field() != b"ssh-ed25519":
        raise ValueError("not an ed25519 key")
    field()                     # public half
    return base64.b64encode(field()[:32]).decode()


def main():
    parser = argparse.ArgumentParser(description="QR code that adds this machine to the Baran iOS app.")
    parser.add_argument("--host", default=None, help="address the phone connects to")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--user", default=getpass.getuser())
    parser.add_argument("--name", default=socket.gethostname().split(".")[0])
    parser.add_argument("--command", default="herdr" if shutil.which("herdr") else "",
                        help="typed after login (default: herdr when it is installed)")
    parser.add_argument("--no-key", action="store_true", help="leave the key out; choose one in the app")
    parser.add_argument("--authorized-keys", default=os.path.expanduser("~/.ssh/authorized_keys"),
                        help=argparse.SUPPRESS)
    options = parser.parse_args()

    code = {"herdr": 1, "n": options.name, "h": options.host or local_address(), "p": options.port,
            "u": options.user, "c": options.command}
    comment = None
    if not options.no_key:
        code["s"], comment = new_key(options.authorized_keys)
    matrix = qr_matrix(json.dumps(code, separators=(",", ":"), ensure_ascii=False).encode())

    width = len(matrix) + 4
    columns = shutil.get_terminal_size().columns
    if columns < width:
        print(f"The terminal is {columns} columns wide and the code needs {width}: widen the window "
              "or shrink the font, then run this again.", file=sys.stderr)
        if comment:
            print(f"A key was already added to {options.authorized_keys} ({comment}); "
                  "remove that line if you do not rerun.", file=sys.stderr)
        return 1
    print(render(matrix))
    print(f"\n{code['n']}: {code['u']}@{code['h']}:{code['p']}" + (f", then `{code['c']}`" if code["c"] else ""))
    if comment:
        print(f"New key authorized in {options.authorized_keys} as \"{comment}\".")
        print("The code holds its private half: show it to your own phone only.")
    print("In the Baran app: + → Scan QR.")
    if sys.stdin.isatty():
        input("Press Enter to wipe the code from the screen. ")
        sys.stdout.write("\033[2J\033[3J\033[H")
    return 0


if __name__ == "__main__":
    sys.exit(main())
