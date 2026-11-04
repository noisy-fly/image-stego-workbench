import unittest
import numpy as np
from core import bit_plane, invert, channel, extract_bits, pair_xor_average


class ImageAnalysisTests(unittest.TestCase):
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

    def test_pair_xor_average(self):
        frames = [np.array([[x]], dtype=np.uint8) for x in (0, 255, 0, 0)]
        self.assertEqual(pair_xor_average(frames, 129).tolist(), [[127]])
        with self.assertRaises(ValueError):
            pair_xor_average(frames[:3], 129)


if __name__ == '__main__':
    unittest.main()
