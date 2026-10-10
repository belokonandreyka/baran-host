"""python3 -m unittest discover -s tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "libexec"))
import seal  # noqa: E402


class SealTest(unittest.TestCase):
    def test_rfc8439_aead_vector(self):
        # RFC 8439, section 2.8.2.
        key = bytes(range(0x80, 0xA0))
        nonce = bytes.fromhex("070000004041424344454647")
        aad = bytes.fromhex("50515253c0c1c2c3c4c5c6c7")
        text = (b"Ladies and Gentlemen of the class of '99: If I could offer you only one tip "
                b"for the future, sunscreen would be it.")
        box = seal.seal(key, text, aad=aad, nonce=nonce)
        self.assertEqual(box[12:28].hex(), "d31a8d34648e60db7b86afbc53ef7ec2")
        self.assertEqual(box[-16:].hex(), "1ae10b594f09e26a7e902ecbd0600691")
        self.assertEqual(seal.open_sealed(key, box, aad=aad), text)

    def test_tampering_is_refused(self):
        key = os.urandom(32)
        box = bytearray(seal.seal(key, "Привіт".encode()))
        box[14] ^= 1
        with self.assertRaises(ValueError):
            seal.open_sealed(key, bytes(box))
        with self.assertRaises(ValueError):
            seal.open_sealed(os.urandom(32), seal.seal(key, b"x"))


if __name__ == "__main__":
    unittest.main()
