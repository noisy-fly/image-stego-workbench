import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import unittest
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPointF, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
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

    def test_batch_pairs_layout_and_undo(self):
        w = Main(); cards = []
        for i in range(20):
            cards.append(w.add_card(np.full((2, 2, 4), 255, dtype=np.uint8), f'{i:03}.png'))
        w.make_pairs(cards, [[(i, i+2), (i+1, i+3)] for i in range(0, 20, 4)])
        self.assertEqual(len(w.operations), 10)
        self.assertEqual([c.title for c in w.operations[0].sources], ['000.png', '002.png'])
        for i, card in enumerate(w.cards):
            for other in w.cards[i+1:]:
                self.assertFalse(card.sceneBoundingRect().intersects(other.sceneBoundingRect()))
            for op in w.operations:
                self.assertFalse(card.sceneBoundingRect().intersects(op.sceneBoundingRect()))
        w.undo(); self.assertEqual(len(w.operations), 0); self.assertEqual(len(w.cards), 20)
        w.redo(); self.assertEqual(len(w.operations), 10)
        w.close()

    def test_copy_paste_and_undo(self):
        w = Main(); card = w.add_card(np.full((3, 3, 4), 123, dtype=np.uint8), '原图')
        card.setSelected(True); w.copy_selection(); w.paste_selection()
        self.assertEqual(len(w.cards), 2)
        np.testing.assert_array_equal(w.cards[1].image, w.cards[0].image)
        w.undo(); self.assertEqual(len(w.cards), 1)
        w.redo(); self.assertEqual(len(w.cards), 2)
        QApplication.clipboard().clear()
        w.close()

    def test_delete_linked_image_undo_restores_links(self):
        w = Main()
        a = w.add_card(np.full((2, 2, 4), 255, dtype=np.uint8), 'a')
        b = w.add_card(np.full((2, 2, 4), 255, dtype=np.uint8), 'b')
        op = w.create_operation([a, b]); op.setSelected(True); w.apply_xor()
        w.canvas.scene().clearSelection(); a.setSelected(True); w.delete_selection()
        self.assertEqual((len(w.cards), len(w.operations)), (2, 0))
        w.undo(); self.assertEqual((len(w.cards), len(w.operations)), (3, 1))
        self.assertIsNotNone(w.operations[0].output)
        w.close()

    def test_paste_external_image(self):
        from PySide6.QtGui import QImage, QColor
        w = Main(); image = QImage(2, 2, QImage.Format.Format_RGBA8888); image.fill(QColor(7, 8, 9, 255))
        QApplication.clipboard().setImage(image); w.paste_selection()
        self.assertEqual(w.cards[0].image[0, 0].tolist(), [7, 8, 9, 255])
        QApplication.clipboard().clear(); w.close()

    def test_keyboard_shortcuts(self):
        w = Main(); w.show(); w.activateWindow(); w.canvas.setFocus(); self.app.processEvents()
        w.add_card(np.full((2, 2, 4), 255, dtype=np.uint8), 'a')
        QTest.keyClick(w.canvas, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(w.canvas, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(w.canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(w.cards), 2)
        QTest.keyClick(w.canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(w.cards), 1)
        QTest.keyClick(w.canvas, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(w.cards), 2)
        QApplication.clipboard().clear(); w.close()

    def test_process_selected_and_undo(self):
        w = Main(); card = w.add_card(np.full((2, 2, 4), [1, 2, 3, 255], dtype=np.uint8), 'a')
        card.setSelected(True); w.apply_single('invert', '反色')
        self.assertEqual(w.cards[-1].image[0, 0].tolist(), [254, 253, 252, 255])
        self.assertEqual(len(w.operations), 1)
        w.undo(); self.assertEqual((len(w.cards), len(w.operations)), (1, 0))
        w.redo(); self.assertEqual((len(w.cards), len(w.operations)), (2, 1))
        w.close()

    def test_batch_plus_combine(self):
        w = Main()
        a = w.add_card(np.full((2, 2, 4), [1, 3, 5, 255], dtype=np.uint8), 'a')
        b = w.add_card(np.full((2, 2, 4), [3, 1, 7, 255], dtype=np.uint8), 'b')
        op = w.create_operation([a, b]); op.setSelected(True); w.apply_combine('and', '按位与')
        self.assertEqual(w.cards[-1].image[0, 0].tolist(), [1, 1, 5, 255])
        w.undo(); self.assertEqual((len(w.cards), len(w.operations)), (2, 1))
        self.assertIsNone(w.operations[0].output); w.close()

    def test_pair_existing_result_and_undo(self):
        w = Main()
        a = w.add_card(np.full((2, 2, 4), 255, dtype=np.uint8), 'a')
        b = w.add_card(np.full((2, 2, 4), 255, dtype=np.uint8), 'b')
        op = w.create_operation([a, b]); op.setSelected(True); w.apply_xor()
        result = op.output
        w.make_pairs([result, b], [[(0, 1)]])
        self.assertEqual(len(w.operations), 2)
        self.assertIn(op, result.links)
        w.undo(); self.assertEqual(len(w.operations), 1); self.assertIsNotNone(w.operations[0].output)
        w.close()

    def test_aggregate_and_undo(self):
        w = Main()
        for v in [20, 40, 120]:
            c = w.add_card(np.full((2, 2, 4), v, dtype=np.uint8), str(v)); c.setSelected(True)
        w.apply_aggregate('mean', '平均')
        self.assertEqual(w.cards[-1].image[0, 0].tolist(), [60, 60, 60, 255])
        w.undo(); self.assertEqual(len(w.cards), 3); w.close()

    def test_menu_dispatches_correct_operation(self):
        w = Main(); c = w.add_card(np.array([[[10, 20, 30, 255]]], dtype=np.uint8), 'a'); c.setSelected(True)
        menu = w.module_menu(); single = menu.actions()[0].menu()
        next(action for action in single.actions() if action.text() == '反色').trigger()
        self.assertEqual(w.cards[-1].image[0, 0].tolist(), [245, 235, 225, 255]); w.close()

    def test_canvas_zoom_shortcuts_and_limits(self):
        w = Main(); w.show(); w.activateWindow(); w.canvas.setFocus(); self.app.processEvents()
        before = w.canvas.transform().m11()
        QTest.keyClick(w.canvas, Qt.Key.Key_Equal, Qt.KeyboardModifier.ControlModifier)
        self.assertGreater(w.canvas.transform().m11(), before)
        QTest.keyClick(w.canvas, Qt.Key.Key_Minus, Qt.KeyboardModifier.ControlModifier)
        self.assertAlmostEqual(w.canvas.transform().m11(), before)
        for _ in range(50): w.canvas.zoom(1.25)
        self.assertLessEqual(w.canvas.transform().m11(), 4.0)
        QTest.keyClick(w.canvas, Qt.Key.Key_0, Qt.KeyboardModifier.ControlModifier)
        self.assertAlmostEqual(w.canvas.transform().m11(), 1.0)
        QTest.keyClick(w.canvas, Qt.Key.Key_Plus, Qt.KeyboardModifier.ControlModifier)
        self.assertGreater(w.canvas.transform().m11(), 1.0)
        w.close()

    def test_zoomed_rubberband_selects_cards_and_keeps_pixels(self):
        w = Main(); w.show(); self.app.processEvents()
        a = w.add_card(np.full((10, 10, 4), [1, 2, 3, 255], dtype=np.uint8), 'a')
        b = w.add_card(np.full((10, 10, 4), [4, 5, 6, 255], dtype=np.uint8), 'b')
        w.canvas.setTransformationAnchor(w.canvas.ViewportAnchor.NoAnchor); w.canvas.zoom(1.25)
        w.canvas.horizontalScrollBar().setValue(0); w.canvas.verticalScrollBar().setValue(0)
        view = w.canvas.viewport(); start = QPointF(w.canvas.mapFromScene(5, 5)); end = QPointF(w.canvas.mapFromScene(230, 120))
        for kind, pos, button, buttons in [(QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
                (QEvent.Type.MouseMove, end, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
                (QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)]:
            self.app.sendEvent(view, QMouseEvent(kind, pos, pos, button, buttons, Qt.KeyboardModifier.NoModifier))
        self.assertEqual(len(w.selected_cards()), 2)
        self.assertEqual(a.image[0, 0].tolist(), [1, 2, 3, 255]); w.close()


if __name__ == '__main__': unittest.main()
