import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import tempfile
import unittest
from pathlib import Path
from PIL import Image, PngImagePlugin
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QPushButton
from app import Analysis
from basic_search_dialog import BasicSearchDialog
from core import load_image
from file_inspection import source_reference


class BasicSearchUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def test_search_and_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'x.png'
            metadata = PngImagePlugin.PngInfo(); metadata.add_text('Comment', 'demo{hello}', zip=True)
            Image.new('RGB', (3, 3)).save(path, pnginfo=metadata)
            analysis = Analysis(None, load_image(path), 'x.png', source_reference(path))
            self.assertIsNotNone(analysis.findChild(QPushButton, 'basicSearchButton'))
            dialog = BasicSearchDialog(analysis, source_reference(path))
            dialog.show(); self.app.processEvents()
            loop = QEventLoop(); dialog.worker.finished.connect(loop.quit); QTimer.singleShot(5000, loop.quit); loop.exec()
            self.app.processEvents()
            self.assertTrue(any(item['text'] == 'demo{hello}' for item in dialog.results))
            dialog.items.setCurrentRow(next(i for i, item in enumerate(dialog.results) if item['text'] == 'demo{hello}'))
            dialog.copy_button.click(); self.assertEqual(self.app.clipboard().text(), 'demo{hello}')
            dialog.close(); analysis.close()

    def test_missing_source(self):
        dialog = BasicSearchDialog(None, None); dialog.start_search()
        self.assertIn('没有原始文件', dialog.status.text()); dialog.close()
