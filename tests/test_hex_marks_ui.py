import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from file_inspection import source_reference
from hex_editor import HexEditorDialog

class MarkUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])
    def wait_for(self, predicate):
        for _ in range(200):
            self.app.processEvents()
            if predicate(): return
            QTest.qWait(10)
        self.fail('界面未完成线索刷新')
    def test_compact_navigation_and_refresh(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'x.png'; Image.new('RGB',(3,3)).save(path)
            with path.open('ab') as handle: handle.write(b'PK\x03\x03')
            dialog=HexEditorDialog(None, source_reference(path), lambda *args: None); dialog.show()
            self.wait_for(lambda: any('疑似 ZIP' in x['label'] for x in dialog.marks))
            self.assertLess(dialog.table.columnWidth(17), dialog.table.columnWidth(1))
            row=next(i for i,x in enumerate(dialog.marks) if '疑似 ZIP' in x['label'])
            hit=dialog.marks[row]; dialog.mark_list.setCurrentRow(row)
            self.assertIn('50 4B 03 03',dialog.mark_detail.text())
            self.assertIn('50 4B 03 04',dialog.mark_detail.text())
            self.assertEqual(dialog.model.offset(dialog.table.currentIndex()),hit['offset'])
            pos=hit['offset']+3; self.assertTrue(dialog.model.setData(dialog.model.index(pos//16,pos%16+1),'04'))
            self.wait_for(lambda: any(x['offset']==hit['offset'] and x['actual']==b'PK\x03\x04' for x in dialog.marks))
            self.assertFalse(any(x['offset']==hit['offset'] and '疑似 ZIP' in x['label'] for x in dialog.marks))
            dialog.model.changed=False; dialog.close()
