import unittest

from jarvis_relay import magic_packet


class RelayTests(unittest.TestCase):
    def test_magic_packet(self):
        packet = magic_packet("AA:BB:CC:DD:EE:FF")
        self.assertEqual(len(packet), 102)
        self.assertEqual(packet[:6], b"\xff" * 6)
        self.assertEqual(packet[6:12], bytes.fromhex("AABBCCDDEEFF"))

    def test_invalid_mac(self):
        with self.assertRaises(ValueError):
            magic_packet("nope")


if __name__ == "__main__":
    unittest.main()
