import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from PySide6.QtWidgets import QApplication, QPushButton
from PySide6.QtTest import QTest
from app import Analysis, Main
from file_inspection import source_reference
from hex_editor import HexEditorDialog

class HexEditorUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def test_edit_save_and_canvas_undo(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'original.png'; result = Path(directory)/'edited.png'
            Image.new('RGB',(4,3),'red').save(source)
            with source.open('ab') as handle: handle.write(b'A')
            original = source.read_bytes(); w = Main(); w.load_paths([str(source)])
            analysis = Analysis(w, w.cards[0].image, source.name, source_reference(source))
            self.assertIsNotNone(analysis.findChild(QPushButton, 'hexEditorButton'))
            def run(dialog):
                pos = len(dialog.model.bytes)-1
                self.assertTrue(dialog.model.setData(dialog.model.index(pos//16, pos%16+1), '42'))
                with patch('hex_editor.QFileDialog.getSaveFileName', return_value=(str(result),'')), patch('hex_editor.QMessageBox.information'):
                    dialog.save()
                    for _ in range(500):
                        self.app.processEvents()
                        if result.exists() and len(w.cards) == 2: break
                        QTest.qWait(10)
            with patch.object(HexEditorDialog, 'exec', run): analysis.edit_hex()
            self.assertEqual(len(w.cards),2); self.assertEqual(result.read_bytes(),original[:-1]+b'B')
            self.assertEqual(source.read_bytes(),original); self.assertEqual(w.cards[-1].source_ref,source_reference(result))
            w.undo(); self.assertEqual(len(w.cards),1); w.redo(); self.assertEqual(w.cards[-1].source_ref,source_reference(result))
            analysis.close(); w.close()

    def test_generated_picture_is_explained(self):
        w=Main(); analysis=Analysis(w, __import__('numpy').zeros((2,2,4), dtype='uint8'), 'generated')
        with patch('app.QMessageBox.warning') as warning:
            analysis.edit_hex(); self.assertIn('没有原始文件', warning.call_args.args[2])
        analysis.close(); w.close()
