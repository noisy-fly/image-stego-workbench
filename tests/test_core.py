import unittest
import numpy as np
from core import bit_plane, invert, channel, extract_bits, pair_xor_average, make_pair_groups


class ImageAnalysisTests(unittest.TestCase):
    def test_configurable_pairing(self):
        self.assertEqual(make_pair_groups(8, 2, 'groups'), [[(0, 2), (4, 6)], [(1, 3), (5, 7)]])
        self.assertEqual(make_pair_groups(8, 2, 'subset', 1), [[(1, 3), (5, 7)]])
        self.assertEqual(make_pair_groups(6, 3, 'distance'), [[(0, 3), (1, 4), (2, 5)]])
        with self.assertRaises(ValueError): make_pair_groups(7, 2, 'groups')
    def setUp(self):
        self.image = np.array([[[1, 2, 3, 255], [4, 5, 6, 128]]], dtype=np.uint8)

    def test_bit_plane_and_channel(self):
        self.assertEqual(bit_plane(self.image, 0, 0).tolist(), [[255, 0]])
        self.assertEqual(channel(self.image, 1).tolist(), [[2, 5]])
        self.assertEqual(invert(self.image)[0, 0].tolist(), [254, 253, 252, 255])

    def test_extract_order(self):
        pixels = np.zeros((1, 8, 4), dtype=np.uint8)
        pixels[0, :, 0] = [0, 1, 0, 0, 0, 0, 0, 1]
        self.assertEqual(extract_bits(pixels, [0], [0]), b'A')
        self.assertEqual(extract_bits(pixels, [0], [0], reverse_x=True), b'\x82')
        self.assertEqual(extract_bits(pixels, [0], [0], bit_offset=1), b'')

    def test_pair_xor_average(self):
        frames = [np.array([[x]], dtype=np.uint8) for x in (0, 255, 0, 0)]
        self.assertEqual(pair_xor_average(frames, 129).tolist(), [[127]])
        with self.assertRaises(ValueError):
            pair_xor_average(frames[:3], 129)


if __name__ == '__main__':
    unittest.main()
