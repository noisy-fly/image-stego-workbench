import unittest
import numpy as np
from core import process_image, combine_images, aggregate_images


class ModuleTests(unittest.TestCase):
    def setUp(self):
        self.a = np.array([[[250, 2, 4, 20], [1, 4, 8, 255]]], dtype=np.uint8)
        self.b = np.array([[[10, 3, 5, 120], [2, 6, 4, 255]]], dtype=np.uint8)

    def test_combination_overflow_and_order(self):
        self.assertEqual(combine_images(self.a, self.b, 'add')[0, 0].tolist(), [4, 5, 9, 255])
        self.assertEqual(combine_images(self.a, self.b, 'subtract')[0, 0].tolist(), [240, 255, 255, 255])
        self.assertEqual(combine_images(self.a, self.b, 'difference')[0, 0].tolist(), [240, 1, 1, 255])
        self.assertEqual(combine_images(self.a, self.b, 'and')[0, 0].tolist(), [10, 2, 4, 255])
        with self.assertRaises(ValueError): combine_images(self.a, self.b[:, :1], 'xor')

    def test_unary_preserves_alpha_and_plane_is_visible(self):
        self.assertEqual(process_image(self.a, 'invert')[0, 0].tolist(), [5, 253, 251, 20])
        self.assertEqual(process_image(self.a, 'plane', component=3, bit=2)[0, :, 0].tolist(), [255, 255])
        self.assertEqual(process_image(self.a, 'threshold', threshold=128)[0, 0, 3], 255)
        self.assertEqual(process_image(self.a, 'rotate_cw').shape, (2, 1, 4))

    def test_multi_statistics(self):
        self.assertEqual(aggregate_images([self.a, self.b], 'mean')[0, 0].tolist(), [130, 2, 4, 255])
        self.assertEqual(aggregate_images([self.a, self.b], 'max')[0, 0].tolist(), [250, 3, 5, 255])
        self.assertEqual(aggregate_images([self.a, self.b], 'min')[0, 0].tolist(), [10, 2, 4, 255])
        with self.assertRaises(ValueError): aggregate_images([self.a, self.b[:, :1]], 'mean')

if __name__ == '__main__': unittest.main()
