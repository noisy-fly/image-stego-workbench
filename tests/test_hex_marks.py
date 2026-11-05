import io
import unittest
import zipfile
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from hex_editor import HexModel, find_marks

class MarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def test_partial_zip_and_exact_zip_have_different_labels(self):
        data=b'xPK\x03\x03yPK\x03\x04z'
        marks=find_marks(data)['marks']
        suspect=next(x for x in marks if x['offset']==1)
        exact=next(x for x in marks if x['offset']==6)
        self.assertIn('疑似', suspect['label']); self.assertEqual(suspect['actual'], b'PK\x03\x03')
        self.assertEqual(suspect['expected'], b'PK\x03\x04'); self.assertNotIn('疑似', exact['label'])
        model=HexModel(data); self.assertIsNotNone(model.data(model.index(0,2), Qt.ItemDataRole.BackgroundRole))
        self.assertIn('疑似', model.data(model.index(0,2), Qt.ItemDataRole.ToolTipRole))

    def test_damaged_zip_with_valid_central_directory(self):
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z: z.writestr('note.txt', b'example')
        data=bytearray(buf.getvalue()); data[:4]=b'BAD!'
        marks=find_marks(bytes(data))['marks']
        suspect=next(m for m in marks if m['offset']==0 and '中央目录' in m['label'])
        self.assertEqual(suspect['actual'], b'BAD!'); self.assertEqual(suspect['expected'], b'PK\x03\x04')

    def test_other_single_byte_damaged_headers(self):
        data = b'\x88PNG\r\n\x1a\n' + b'gap' + b'PZ\x03\x04'
        marks = find_marks(data)['marks']
        self.assertTrue(any(m['offset'] == 0 and '疑似 PNG' in m['label'] and m['expected'] == b'\x89PNG\r\n\x1a\n' for m in marks))
        self.assertTrue(any(m['offset'] == 11 and '疑似 ZIP' in m['label'] for m in marks))

    def test_no_guesses_for_unrelated_data(self):
        self.assertEqual(find_marks(b'only ordinary text')['marks'], [])
