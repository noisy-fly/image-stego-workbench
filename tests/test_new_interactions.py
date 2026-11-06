import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import numpy as np
import zxingcpp
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app import Main, Analysis
from barcode_scan import BarcodeDialog
from core import load_image
from file_inspection import source_reference
from hex_editor import HexEditorDialog, PAGE_BYTES
from variant_drag import VARIANT_MIME, variant_mime

class InteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])
    def wait_for(self, check, limit=500):
        for _ in range(limit):
            self.app.processEvents()
            if check(): return
            QTest.qWait(10)
        self.fail('操作未完成')
    def test_variant_mime_file_and_canvas_drop_undo(self):
        arr=np.array([[0,255],[128,1]],dtype=np.uint8); mime=variant_mime('红通道 · 第 0 位',arr)
        self.assertTrue(mime.hasFormat(VARIANT_MIME)); path=Path(mime.urls()[0].toLocalFile())
        np.testing.assert_array_equal(np.asarray(Image.open(path)),arr)
        w=Main(); w.show(); self.app.processEvents()
        event=QDropEvent(QPointF(140,130),Qt.DropAction.CopyAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
        w.canvas.dropEvent(event)
        self.assertEqual(len(w.cards),1); np.testing.assert_array_equal(w.cards[0].image[:,:,0],arr)
        self.assertTrue(w.cards[0].generated); self.assertIsNone(w.cards[0].source_ref)
        w.undo(); self.assertEqual(len(w.cards),0); w.redo(); self.assertEqual(len(w.cards),1)
        w.close()
    def test_barcode_dialog_and_join_ui(self):
        code=np.asarray(zxingcpp.create_barcode('https://example.org/path',zxingcpp.BarcodeFormat.QRCode).to_image(scale=5))
        dialog=BarcodeDialog(None,code); dialog.show()
        self.wait_for(lambda:bool(dialog.results))
        self.assertEqual(dialog.preview.toPlainText(),'https://example.org/path'); dialog.close()
        w=Main(); a=np.full((2,3,4),7,dtype='uint8'); b=np.full((2,2,4),9,dtype='uint8')
        c1=w.add_card(a,'a'); c2=w.add_card(b,'b'); c1.setSelected(True); c2.setSelected(True)
        w.show_analysis(c1); self.assertFalse(next(iter(w._analyses)).isModal())
        next(iter(w._analyses)).close()
        w.apply_join('horizontal'); self.assertEqual(w.cards[-1].image.shape,(2,5,4))
        np.testing.assert_array_equal(w.cards[-1].image[:,:3],a); w.undo(); self.assertEqual(len(w.cards),2)
        w.close()
    def test_pair_join(self):
        w=Main(); a=np.full((2,3,4),11,dtype='uint8'); b=np.full((2,2,4),22,dtype='uint8')
        c1=w.add_card(a,'a'); c2=w.add_card(b,'b'); op=w.create_operation([c1,c2]); op.setSelected(True)
        w.apply_combine('join_horizontal','横向拼接')
        self.assertIsNotNone(op.output); np.testing.assert_array_equal(op.output.image,np.concatenate([a,b],axis=1))
        w.undo(); self.assertEqual(len(w.cards),2); w.close()

    def test_large_hex_load_and_navigation(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'large.png'; Image.new('RGB',(3,3)).save(path)
            with path.open('ab') as f: f.truncate(20*1024*1024)
            ref=source_reference(path); dialog=HexEditorDialog(None,ref,lambda *args:None); dialog.show()
            self.assertLessEqual(dialog.model.rowCount(),PAGE_BYTES//16)
            self.wait_for(lambda:len(dialog.model.bytes)==ref[1],1500)
            self.assertEqual(dialog.model.rowCount(),PAGE_BYTES//16)
            dialog.goto_offset(ref[1]-1); self.assertEqual(dialog.model.offset(dialog.table.currentIndex()),ref[1]-1)
            self.assertEqual(dialog.model.data(dialog.model.index(0,0)),f'{dialog.model.page_start:08X}')
            self.assertTrue(dialog.model.setData(dialog.table.currentIndex(), '41'))
            saved=Path(d)/'saved.png'; added=[]; dialog.on_add=lambda *args: added.append(args)
            with patch('hex_editor.QFileDialog.getSaveFileName',return_value=(str(saved),'')), patch('hex_editor.QMessageBox.information'):
                dialog.save(); self.wait_for(lambda:bool(added), 1500)
            self.assertEqual(saved.stat().st_size,ref[1])
            with saved.open('rb') as f: f.seek(-1,2); self.assertEqual(f.read(),b'A')
            with path.open('rb') as f: f.seek(-1,2); self.assertEqual(f.read(),b'\x00')
            dialog.close()
