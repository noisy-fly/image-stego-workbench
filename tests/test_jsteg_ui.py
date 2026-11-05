import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
from app import Analysis, Main
from core import load_image
from file_inspection import source_reference
from jsteg_dialog import JstegDialog

class JstegUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])
    def test_real_worker_preview_and_save(self):
        path=Path(__file__).resolve().parent.parent/'vendor'/'jsteg'/'sample.jpg'
        window=Main(); analysis=Analysis(window,load_image(path),path.name,source_reference(path))
        self.assertIsNotNone(analysis.findChild(QPushButton,'jstegButton'))
        dialog=JstegDialog(analysis, source_reference(path)); dialog.show()
        for _ in range(500):
            self.app.processEvents()
            if dialog.payload is not None or '未能提取' in dialog.status.text(): break
            QTest.qWait(10)
        self.assertEqual(dialog.payload,b'demo{sample}\x00\xffbinary')
        self.assertIn('demo{sample}',dialog.preview.toPlainText())
        with tempfile.TemporaryDirectory() as d:
            output=Path(d)/'payload.bin'
            with patch('jsteg_dialog.QFileDialog.getSaveFileName', return_value=(str(output),'')), patch('jsteg_dialog.QMessageBox.information'):
                dialog.save()
            self.assertEqual(output.read_bytes(),dialog.payload)
        dialog.close(); analysis.close(); window.close()
    def test_no_source(self):
        dialog=JstegDialog(None,None); dialog.start()
        self.assertIn('没有原始文件',dialog.status.text()); dialog.close()
