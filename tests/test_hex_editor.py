import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from file_inspection import source_reference
from hex_editor import HexModel, read_source, save_edited

class HexEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def test_hex_and_ascii_edit_and_headers(self):
        model = HexModel(b'\x89PNG\r\n\x1a\nabc')
        self.assertEqual(model.data(model.index(0, 1)), '89')
        self.assertEqual(model.data(model.index(0, 17)), '.')
        self.assertIsNotNone(model.data(model.index(0, 1), Qt.ItemDataRole.BackgroundRole))
        self.assertTrue(model.setData(model.index(0, 9), '41'))
        self.assertEqual(model.data(model.index(0, 25)), 'A')
        self.assertTrue(model.setData(model.index(0, 26), 'Z'))
        self.assertEqual(model.data(model.index(0, 10)), '5A')
        self.assertFalse(model.setData(model.index(0, 1), 'zz'))
        self.assertFalse(model.setData(model.index(0, 16), 'ff'))

    def test_save_new_image_and_original_protection(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'x.png'; dst=Path(d)/'new.png'; Image.new('RGB',(3,2),'red').save(src)
            ref=source_reference(src); raw=read_source(ref); original=src.read_bytes()
            with self.assertRaises(ValueError): save_edited(ref, raw, src)
            hardlink=Path(d)/'hardlink.png'; os.link(src, hardlink)
            with self.assertRaises(ValueError): save_edited(ref, raw, hardlink)
            with self.assertRaises(ValueError): save_edited(ref, b'broken', dst)
            self.assertFalse(dst.exists()); self.assertEqual(src.read_bytes(), original)
            image, new_ref=save_edited(ref, raw, dst)
            self.assertEqual(image.shape, (2,3,4)); self.assertEqual(Path(new_ref[0]),dst); self.assertEqual(src.read_bytes(), original)
            src.write_bytes(original+b'x')
            with self.assertRaises(ValueError): save_edited(ref, raw, Path(d)/'other.png')
