import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import unittest
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPointF, QEvent
from PySide6.QtGui import QMouseEvent
from app import Main


class CanvasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_link_moves_and_xor_uses_original_pixels(self):
        w = Main()
        a = w.add_card(np.full((2, 2, 4), [1, 2, 3, 255], dtype=np.uint8), 'a')
        b = w.add_card(np.full((2, 2, 4), [3, 2, 1, 255], dtype=np.uint8), 'b')
        link = w.create_operation([a, b])
        before = link.paths[0].path().pointAtPercent(0)
        a.setPos(200, 200)
        self.assertNotEqual(before, link.paths[0].path().pointAtPercent(0))
        link.setSelected(True)
        w.apply_xor()
        self.assertEqual(w.cards[-1].image[0, 0].tolist(), [2, 0, 2, 255])
        w.close()

    def test_natural_order_and_selected_batch(self):
        w = Main()
        for name, value in [('2.png', 255), ('10.png', 0), ('1.png', 0), ('11.png', 0)]:
            c = w.add_card(np.full((1, 1, 4), [value, value, value, 255], dtype=np.uint8), name)
            c.setSelected(True)
        result = w.selected_pair_average(129)
        self.assertEqual(result[0, 0, 0], 127)
        w.close()

    def test_rubber_band_selects_transparent_images(self):
        w = Main(); w.show(); self.app.processEvents()
        for name in ('a', 'b'):
            w.add_card(np.zeros((10, 10, 4), dtype=np.uint8), name)
        view = w.canvas.viewport(); start = QPointF(5, 5); end = QPointF(230, 120)
        for event, pos, button, buttons in [
            (QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
            (QEvent.Type.MouseMove, end, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
            (QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton),
        ]:
            self.app.sendEvent(view, QMouseEvent(event, pos, pos, button, buttons, Qt.KeyboardModifier.NoModifier))
        self.assertEqual(len(w.selected_cards()), 2)
        w.close()

    def test_selection_scrolls_and_keeps_selecting(self):
        w = Main(); w.resize(700, 450); w.show(); self.app.processEvents()
        for i in range(100): w.add_card(np.full((8, 8, 4), 255, dtype=np.uint8), str(i))
        view = w.canvas.viewport(); start = QPointF(5, 5); end = QPointF(250, view.height()-2)
        def send(kind, pos, button, buttons):
            self.app.sendEvent(view, QMouseEvent(kind, pos, pos, button, buttons, Qt.KeyboardModifier.NoModifier))
        send(QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
        send(QEvent.Type.MouseMove, end, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
        for _ in range(15): w.canvas.auto_scroll()
        self.assertGreater(w.canvas.verticalScrollBar().value(), 0)
        send(QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
        self.assertTrue(w.cards[40].isSelected())
        w.close()

    def test_operation_centers_when_sources_and_output_move(self):
        w = Main()
        a = w.add_card(np.full((2, 2, 4), 255, dtype=np.uint8), 'a')
        b = w.add_card(np.full((2, 2, 4), 255, dtype=np.uint8), 'b')
        op = w.create_operation([a, b]); op.setSelected(True); w.apply_xor()
        old = op.pos(); op.output.setPos(700, 400)
        self.assertNotEqual(old, op.pos())
        old = op.pos(); a.setPos(30, 300)
        self.assertNotEqual(old, op.pos())
        w.close()


if __name__ == '__main__': unittest.main()
