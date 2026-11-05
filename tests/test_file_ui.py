import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import tempfile
import io
import unittest
import zipfile
from pathlib import Path
from PIL import Image
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from app import Main
from file_dialog import FileInspectionDialog
from file_inspection import source_reference

class FileUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def test_import_copy_undo_and_dialog(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'x.png'
            Image.new('RGB', (2, 2)).save(path)
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive: archive.writestr('hello.txt', 'hello')
            with path.open('ab') as output: output.write(stream.getvalue())
            w = Main(); w.load_paths([str(path)])
            ref = source_reference(path)
            self.assertEqual(w.cards[0].source_ref, ref)
            w.cards[0].setSelected(True); w.copy_selection(); w.paste_selection()
            self.assertEqual(w.cards[-1].source_ref, ref)
            w.undo(); w.redo(); self.assertEqual(w.cards[-1].source_ref, ref)
            dialog = FileInspectionDialog(w, ref); dialog.show()
            for _ in range(100):
                self.app.processEvents()
                if dialog.result is not None: break
                QTest.qWait(10)
            self.assertIsNotNone(dialog.result)
            self.assertTrue(dialog.tail_button.isEnabled())
            self.assertTrue(any(c['kind'] == 'ZIP' and c['verified'] for c in dialog.result['candidates']))
            dialog.reject(); w.close(); self.app.clipboard().clear()

if __name__ == '__main__': unittest.main()
