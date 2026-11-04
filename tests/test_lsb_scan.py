import unittest
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QListWidget, QPushButton, QCheckBox, QSpinBox
from core import scan_lsb, extract_bits
from app import Analysis


def embed(payload, shape, channels, column=False, little=False):
    image = np.zeros((*shape, 4), dtype=np.uint8)
    image[:, :, 3] = 255
    bits = np.unpackbits(np.frombuffer(payload, dtype=np.uint8), bitorder='little' if little else 'big')
    h, w = shape
    for i, bit in enumerate(bits):
        pixel, component = divmod(i, len(channels))
        y, x = (pixel % h, pixel // h) if column else (pixel // w, pixel % w)
        image[y, x, channels[component]] |= bit
    return image


class ScanTests(unittest.TestCase):
    def test_detects_flag_and_parameters(self):
        image = embed(b'flag{hello_123}', (30, 30), [0])
        results = scan_lsb(image)
        self.assertTrue(any(r['channels'] == (0,) and r['bit'] == 0 and not r['column'] and not r['little'] and r['kind'] == 'flag 样式文本' and r['offset'] == 0 for r in results))

    def test_detects_header_in_column_rgb_little_order(self):
        image = embed(b'\x89PNG\r\n\x1a\nhello', (30, 30), [0, 1, 2], column=True, little=True)
        results = scan_lsb(image)
        hit = next(r for r in results if r['channels'] == (0,1,2) and r['column'] and r['little'] and r['kind'] == 'PNG 文件头')
        data = extract_bits(image, hit['channels'], [hit['bit']], hit['column'], hit['little'], bit_offset=hit['offset']*8)
        self.assertTrue(data.startswith(b'\x89PNG\r\n\x1a\n'))

    def test_nonzero_offset_transfers_to_manual_extraction(self):
        image = embed(b'junkflag{valid}', (30, 30), [0])
        hit = next(r for r in scan_lsb(image) if r['kind'] == 'flag 样式文本' and r['channels'] == (0,) and not r['column'] and not r['little'])
        self.assertEqual(hit['offset'], 4)
        data = extract_bits(image, hit['channels'], [hit['bit']], hit['column'], hit['little'], bit_offset=hit['offset']*8)
        self.assertTrue(data.startswith(b'flag{valid}'))

    def test_empty_data_has_no_false_hits(self):
        self.assertEqual(scan_lsb(np.zeros((12, 12, 4), dtype=np.uint8)), [])

    def test_scan_budget_is_enforced(self):
        image = embed(b'01234567flag{later}', (30, 30), [0])
        self.assertFalse(any(r['kind'] == 'flag 样式文本' for r in scan_lsb(image, max_pixels=64)))

    def test_quick_scan_window_passes_preset(self):
        app = QApplication.instance() or QApplication([])
        image = embed(b'flag{ui_test}', (30, 30), [0])
        analysis = Analysis(None, image, '样例')
        captured = []
        analysis.extract = lambda preset: captured.append(preset)
        def interact():
            dialog = next(w for w in app.topLevelWidgets() if isinstance(w, QDialog) and w.windowTitle() == 'LSB 快速检查')
            result_list = dialog.findChild(QListWidget)
            if result_list.count():
                result_list.setCurrentRow(0)
                next(b for b in dialog.findChildren(QPushButton) if b.text().startswith('使用选中')).click()
            dialog.accept()
        QTimer.singleShot(25, interact)
        analysis.quick_scan()
        self.assertTrue(captured)
        self.assertEqual(captured[0]['kind'], 'flag 样式文本')
        analysis.close()

    def test_manual_dialog_uses_scan_parameters(self):
        app = QApplication.instance() or QApplication([])
        image = embed(b'junkflag{valid}', (30,30), [0])
        hit = next(r for r in scan_lsb(image) if r['kind'] == 'flag 样式文本' and r['channels'] == (0,) and not r['column'] and not r['little'])
        analysis = Analysis(None, image, '样例'); captured = []
        def interact():
            dialog = next(w for w in app.topLevelWidgets() if isinstance(w, QDialog) and w.windowTitle() == '提取像素位数据')
            checks = {c.text(): c.isChecked() for c in dialog.findChildren(QCheckBox)}
            spins = dialog.findChildren(QSpinBox)
            captured.append((checks, spins[-1].value()))
            dialog.accept()
        QTimer.singleShot(25, interact); analysis.extract(hit)
        self.assertTrue(captured[0][0]['R']); self.assertFalse(captured[0][0]['G'])
        self.assertTrue(captured[0][0]['第0位']); self.assertEqual(captured[0][1], 32)
        analysis.close()


if __name__ == '__main__': unittest.main()
