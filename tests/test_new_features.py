import unittest
import numpy as np
import zxingcpp
from core import concatenate_images
from barcode_scan import scan_codes

class NewFeatureTests(unittest.TestCase):
    def test_qr_and_code128(self):
        for fmt, text in [(zxingcpp.BarcodeFormat.QRCode, 'https://example.org/a'), (zxingcpp.BarcodeFormat.Code128, 'ABC123456')]:
            image=np.asarray(zxingcpp.create_barcode(text,fmt).to_image(scale=5))
            found=scan_codes(image)
            self.assertTrue(any(item['text']==text for item in found), (fmt,found))
        self.assertEqual(scan_codes(np.full((40,40),255,dtype=np.uint8)), [])

    def test_join_without_gaps_or_resize(self):
        a=np.full((2,3,4),10,dtype=np.uint8); b=np.full((2,2,4),20,dtype=np.uint8)
        result=concatenate_images([a,b],'horizontal')
        self.assertEqual(result.shape,(2,5,4)); np.testing.assert_array_equal(result[:,:3],a); np.testing.assert_array_equal(result[:,3:],b)
        with self.assertRaises(ValueError): concatenate_images([a,b],'vertical')
        c=np.full((1,3,4),30,dtype=np.uint8); result=concatenate_images([a,c],'vertical')
        self.assertEqual(result.shape,(3,3,4)); np.testing.assert_array_equal(result[2:],c)
