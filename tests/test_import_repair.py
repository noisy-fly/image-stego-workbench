import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import tempfile
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from app import Main
from test_png_repair import damaged_png
from file_inspection import source_reference
import unittest

class ImportRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def test_import_keeps_original_and_reports_repair(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'broken.png'; original = damaged_png('height') + b'tail'; path.write_bytes(original)
            w = Main()
            with patch('app.QMessageBox.information') as notice:
                w.load_paths([str(path)])
            notice.assert_called_once()
            self.assertEqual(w.cards[0].image.shape[:2], (37, 23))
            self.assertEqual(w.cards[0].source_ref, source_reference(path))
            self.assertEqual(path.read_bytes(), original)
            self.assertIn('已修复', w.cards[0].title)
            w.close()

    def test_unrecognized_damage_does_not_create_card(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'broken.png'; path.write_bytes(b'not an image')
            w = Main()
            with patch('app.QMessageBox.warning') as warning: w.load_paths([str(path)])
            warning.assert_called_once(); self.assertEqual(w.cards, []); w.close()

if __name__ == '__main__': unittest.main()
