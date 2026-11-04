import sys
import re
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import Qt, QTimer, QPointF, QEvent
from PySide6.QtGui import QImage, QPixmap, QPainterPath, QPen, QColor, QAction, QMouseEvent
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QMessageBox, QGraphicsView, QGraphicsScene,
    QGraphicsPixmapItem, QGraphicsTextItem, QMenu, QDialog, QListWidget, QListWidgetItem,
    QSplitter, QSpinBox, QComboBox, QCheckBox, QTextEdit, QInputDialog,
    QGraphicsEllipseItem, QGraphicsPathItem)
from PySide6.QtGui import QIcon
from core import load_image, bit_plane, channel, invert, extract_bits, pair_xor_average, make_pair_groups


def natural_key(value):
    return [int(s) if s.isdigit() else s.casefold() for s in re.split(r'(\d+)', value)]


def pixmap(array, width=0, height=0):
    data = np.ascontiguousarray(array)
    h, w = data.shape[:2]
    fmt = QImage.Format.Format_Grayscale8 if data.ndim == 2 else QImage.Format.Format_RGBA8888
    image = QImage(data.data, w, h, data.strides[0], fmt).copy()
    result = QPixmap.fromImage(image)
    return result.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation) if width else result


def save_image(parent, array):
    path, _ = QFileDialog.getSaveFileName(parent, '保存结果', '结果.png', 'PNG 图片 (*.png)')
    if path:
        Image.fromarray(array).save(path)


class Analysis(QDialog):
    def __init__(self, parent, image, title):
        super().__init__(parent)
        self.image = image
        self.setWindowTitle('图片分析 — ' + title)
        self.resize(1050, 760)
        layout = QVBoxLayout(self)
        self.name = QLabel('原图')
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(340)
        self.preview.setStyleSheet('background:#171d28; border-radius:8px;')
        layout.addWidget(self.name)
        layout.addWidget(self.preview, 1)
        self.variants = [('原图', image), ('反色', invert(image))]
        for c, name in enumerate(('红', '绿', '蓝', '透明度')):
            self.variants.append((name + '通道', channel(image, c)))
            for b in range(8):
                self.variants.append((f'{name}通道 · 第 {b} 位', bit_plane(image, c, b)))
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setFlow(QListWidget.Flow.LeftToRight)
        self.list.setWrapping(False)
        self.list.setIconSize(__import__('PySide6').QtCore.QSize(115, 75))
        self.list.setFixedHeight(150)
        for name, variant in self.variants:
            item = QListWidgetItem(QIcon(pixmap(variant, 115, 75)), name)
            self.list.addItem(item)
        self.list.currentRowChanged.connect(self.show_variant)
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        for label, callback in [('保存当前图片', self.save), ('提取 LSB 数据', self.extract)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.list.setCurrentRow(0)

    def show_variant(self, row):
        if row < 0:
            return
        name, image = self.variants[row]
        self.name.setText(name)
        self.preview.setPixmap(pixmap(image, max(400, self.preview.width()-20), max(300, self.preview.height()-20)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'list'):
            self.show_variant(self.list.currentRow())

    def save(self):
        save_image(self, self.variants[self.list.currentRow()][1])

    def extract(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('提取像素位数据')
        dialog.resize(700, 500)
        box = QVBoxLayout(dialog)
        box.addWidget(QLabel('选择通道与位：按所选通道顺序依次读取每个像素。'))
        row = QHBoxLayout()
        checks = []
        for name in 'RGBA':
            c = QCheckBox(name)
            c.setChecked(name in 'RGB')
            row.addWidget(c)
            checks.append(c)
        box.addLayout(row)
        bit = QSpinBox(); bit.setRange(0, 7); bit.setPrefix('位：'); box.addWidget(bit)
        column = QCheckBox('按列扫描（默认按行）'); box.addWidget(column)
        little = QCheckBox('每字节低位先写入'); box.addWidget(little)
        output = QTextEdit(); output.setReadOnly(True); box.addWidget(output)
        data = [b'']
        def run():
            components = [i for i, c in enumerate(checks) if c.isChecked()]
            if not components:
                QMessageBox.warning(dialog, '提示', '请至少选择一个通道。'); return
            data[0] = extract_bits(self.image, components, [bit.value()], column.isChecked(), little.isChecked())
            sample = data[0][:4096]
            output.setPlainText('前 4096 字节（十六进制）：\n' + sample.hex(' ') + '\n\n文本预览：\n' + sample.decode('utf-8', errors='replace'))
        def export():
            path, _ = QFileDialog.getSaveFileName(dialog, '保存提取数据', '提取结果.bin', '所有文件 (*)')
            if path: Path(path).write_bytes(data[0])
        b = QPushButton('提取并预览'); b.clicked.connect(run); box.addWidget(b)
        b = QPushButton('保存提取数据'); b.clicked.connect(export); box.addWidget(b)
        dialog.exec()


class Card(QGraphicsPixmapItem):
    def __init__(self, parent, image, title):
        super().__init__(pixmap(image, 72, 48))
        self.setShapeMode(QGraphicsPixmapItem.ShapeMode.BoundingRectShape)
        self.owner, self.image, self.title = parent, image, title
        self.links = []
        self.setFlags(self.GraphicsItemFlag.ItemIsMovable | self.GraphicsItemFlag.ItemIsSelectable | self.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.label = QGraphicsTextItem(title[:12], self)
        self.label.setScale(0.8)
        self.label.setDefaultTextColor(Qt.GlobalColor.white)
        self.label.setPos(0, 49)
        self.timer = QTimer(); self.timer.setSingleShot(True); self.timer.timeout.connect(self.hover_preview)

    def mouseDoubleClickEvent(self, event):
        self.timer.stop(); Analysis(self.owner, self.image, self.title).exec()

    def hoverEnterEvent(self, event):
        self.timer.start(1000); super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.timer.stop(); self.owner.tip.hide(); super().hoverLeaveEvent(event)

    def hover_preview(self):
        self.owner.tip.setPixmap(pixmap(self.image, 320, 220))
        self.owner.tip.adjustSize(); self.owner.tip.move(__import__('PySide6').QtGui.QCursor.pos() + __import__('PySide6').QtCore.QPoint(15, 15)); self.owner.tip.show()

    def contextMenuEvent(self, event):
        self.timer.stop(); self.owner.tip.hide()
        menu = QMenu(); menu.addAction('打开图片分析', lambda: Analysis(self.owner, self.image, self.title).exec())
        menu.addAction('保存图片', lambda: save_image(self.owner, self.image))
        menu.addAction('从画布移除', lambda: self.owner.remove_card(self))
        menu.exec(event.screenPos())

    def itemChange(self, change, value):
        if change == self.GraphicsItemChange.ItemPositionHasChanged and hasattr(self, 'links'):
            for link in self.links: link.update_paths()
        return super().itemChange(change, value)


class Operation(QGraphicsEllipseItem):
    def __init__(self, owner, sources):
        super().__init__(0, 0, 34, 34)
        self.owner, self.sources, self.output = owner, sources, None
        self.paths = []
        self.setBrush(QColor('#d9f1ed')); self.setPen(QPen(QColor('#57c4b4'), 2))
        self.setFlags(self.GraphicsItemFlag.ItemIsSelectable)
        label = QGraphicsTextItem('+', self); label.setDefaultTextColor(QColor('#174f49')); label.setPos(5, -5)
        label.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        for source in sources: source.links.append(self)

    def update_paths(self):
        for item in self.paths:
            if item.scene(): item.scene().removeItem(item)
        self.paths.clear()
        starts = [s.scenePos() + QPointF(s.boundingRect().width(), s.boundingRect().height()/2) for s in self.sources]
        midpoint = sum(starts, QPointF()) / len(starts)
        if self.output:
            rect = self.output.boundingRect(); outpos = self.output.scenePos()
            end = outpos + QPointF(0 if outpos.x() >= midpoint.x() else rect.width(), rect.height()/2)
            starts = [s.scenePos() + QPointF(s.boundingRect().width() if end.x() >= s.scenePos().x() else 0,
                                             s.boundingRect().height()/2) for s in self.sources]
            midpoint = sum(starts, QPointF()) / len(starts)
        else:
            end = QPointF(max(p.x() for p in starts) + 160, midpoint.y())
        guide = QPainterPath(midpoint); reach = max(20, abs(end.x() - midpoint.x()) * .45) * (1 if end.x() >= midpoint.x() else -1)
        guide.cubicTo(midpoint + QPointF(reach, 0), end - QPointF(reach, 0), end)
        center = guide.pointAtPercent(.5)
        self.setPos(center - QPointF(17, 17))
        pairs = [(p, center) for p in starts] + [(center, end)]
        for start, end in pairs:
            path = QPainterPath(start); dx = max(15, abs(end.x()-start.x())/2) * (1 if end.x() >= start.x() else -1)
            path.cubicTo(start + QPointF(dx, 0), end - QPointF(dx, 0), end)
            if start == center:
                direction = 1 if end.x() >= start.x() else -1
                path.moveTo(end + QPointF(-10*direction, -5)); path.lineTo(end); path.lineTo(end + QPointF(-10*direction, 5))
            item = QGraphicsPathItem(path); item.setPen(QPen(QColor('#58b4ac'), 2)); item.setZValue(-1)
            self.owner.canvas.scene().addItem(item); self.paths.append(item)


class Canvas(QGraphicsView):
    def __init__(self, owner):
        super().__init__(); self.owner = owner; self.setScene(QGraphicsScene(self)); self.setAcceptDrops(True)
        self.setSceneRect(0, 0, 3000, 2000)
        self.setStyleSheet('background:#1a202c; border:0;')
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.auto_timer = QTimer(self); self.auto_timer.setInterval(25); self.auto_timer.timeout.connect(self.auto_scroll)
        self.drag_position = None
        QTimer.singleShot(0, lambda: (self.horizontalScrollBar().setValue(0), self.verticalScrollBar().setValue(0)))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
    def dropEvent(self, event):
        self.owner.load_paths([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]); event.acceptProposedAction()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self.itemAt(event.position().toPoint()) is None:
            self.drag_position = event.position(); self.auto_timer.start()

    def mouseMoveEvent(self, event):
        if self.auto_timer.isActive(): self.drag_position = event.position()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.auto_timer.stop(); self.drag_position = None
        super().mouseReleaseEvent(event)

    def auto_scroll(self):
        if self.drag_position is None: return
        edge = 75
        def speed(pos, size):
            if pos < edge: return -max(1, min(30, int((edge-pos)*.4)))
            if pos > size-edge: return max(1, min(30, int((pos-(size-edge))*.4)))
            return 0
        dx = speed(self.drag_position.x(), self.viewport().width())
        dy = speed(self.drag_position.y(), self.viewport().height())
        if not dx and not dy: return
        h, v = self.horizontalScrollBar(), self.verticalScrollBar()
        previous = (h.value(), v.value()); h.setValue(h.value()+dx); v.setValue(v.value()+dy)
        if previous != (h.value(), v.value()):
            pos = self.drag_position
            event = QMouseEvent(QEvent.Type.MouseMove, pos, self.viewport().mapToGlobal(pos.toPoint()),
                                Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(self.viewport(), event)


class PairDialog(QDialog):
    def __init__(self, parent, names):
        super().__init__(parent); self.names = names; self.groups = None
        self.setWindowTitle('配置批量配对'); self.resize(650, 420)
        box = QVBoxLayout(self)
        box.addWidget(QLabel(f'已选 {len(names)} 张图片，按文件名自然排序。序号以当前选择的第一张为第 1 张。'))
        self.mode = QComboBox()
        self.mode.addItems(['抽取指定组后相邻配对', '按步长分组，各组分别配对并输出', '固定间隔分块配对'])
        box.addWidget(self.mode)
        self.step = QSpinBox(); self.step.setRange(1, max(1, len(names)//2)); self.step.setPrefix('步长 / 间隔：'); self.step.setValue(1); box.addWidget(self.step)
        self.offset = QSpinBox(); self.offset.setRange(1, 1); self.offset.setPrefix('选择第几组（从 1 开始）：'); box.addWidget(self.offset)
        self.threshold = QSpinBox(); self.threshold.setRange(0, 255); self.threshold.setValue(129); self.threshold.setPrefix('二值化阈值：'); box.addWidget(self.threshold)
        box.addWidget(QLabel('配对预览（每组展示前 4 对；计算前请核对）：'))
        self.preview = QTextEdit(); self.preview.setReadOnly(True); box.addWidget(self.preview)
        buttons = QHBoxLayout(); run = QPushButton('开始计算'); cancel = QPushButton('取消')
        run.clicked.connect(self.confirm); cancel.clicked.connect(self.reject); buttons.addWidget(run); buttons.addWidget(cancel); box.addLayout(buttons)
        self.mode.currentIndexChanged.connect(self.refresh); self.step.valueChanged.connect(self.refresh); self.offset.valueChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.offset.setMaximum(self.step.value()); self.offset.setEnabled(self.mode.currentIndex() == 0)
        modes = ['subset', 'groups', 'distance']
        try:
            self.groups = make_pair_groups(len(self.names), self.step.value(), modes[self.mode.currentIndex()], self.offset.value()-1)
            lines = []
            for i, group in enumerate(self.groups):
                examples = '；'.join(f'{self.names[a]} ↔ {self.names[b]}' for a, b in group[:4])
                lines.append(f'第 {i+1} 组：{len(group)} 对\n{examples}')
            self.preview.setPlainText('\n\n'.join(lines))
        except ValueError as exc:
            self.groups = None; self.preview.setPlainText('无法配对：' + str(exc))

    def confirm(self):
        if self.groups is None:
            QMessageBox.warning(self, '配对设置无效', '请先调整设置，使每组都能完整配对。'); return
        self.accept()


class Main(QMainWindow):
    def __init__(self):
        super().__init__(); self.cards = []; self.operations = []; self.setWindowTitle('图片隐写工作台'); self.resize(1200, 800)
        self.tip = QLabel(None, Qt.WindowType.ToolTip); self.tip.setStyleSheet('background:#111;padding:6px;')
        panel = QWidget(); self.setCentralWidget(panel); layout = QVBoxLayout(panel)
        title = QLabel('图片隐写工作台'); title.setStyleSheet('font-size:23px;font-weight:700;'); layout.addWidget(title)
        layout.addWidget(QLabel('空白处拖动框选，靠近边缘自动滚动 · 图片可拖动，+ 自动居中 · 双击图片分析'))
        toolbar = QHBoxLayout()
        for text, func in [('导入图片', self.browse), ('创建配对 +', self.create_pairs), ('对选中 + 执行 XOR', self.apply_xor), ('选中图片：批量 XOR 平均', self.average_selected), ('图形工作流', self.workflow), ('从文件批量处理', self.average)]:
            button = QPushButton(text); button.clicked.connect(func); toolbar.addWidget(button)
        toolbar.addStretch(); layout.addLayout(toolbar)
        self.canvas = Canvas(self); layout.addWidget(self.canvas)
        self.statusBar().showMessage('准备就绪')
        select_all = QAction(self); select_all.setShortcut('Ctrl+A'); select_all.triggered.connect(self.select_all); self.addAction(select_all)

    def select_all(self):
        for item in self.cards + self.operations: item.setSelected(True)

    def browse(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '导入图片', '', '图片 (*.png *.bmp *.jpg *.jpeg *.gif *.tif *.tiff *.webp);;所有文件 (*)')
        self.load_paths(paths)

    def workflow(self):
        from workflow import Workflow
        Workflow(self).exec()

    def load_paths(self, paths):
        errors = []
        for path in sorted(paths, key=lambda p: natural_key(Path(p).name)):
            try: self.add_card(load_image(path), Path(path).name)
            except Exception as e: errors.append(f'{Path(path).name}: {e}')
        if errors: QMessageBox.warning(self, '部分图片无法打开', '\n'.join(errors[:10]))
        self.statusBar().showMessage(f'画布中有 {len(self.cards)} 张图片')

    def add_card(self, image, title):
        card = Card(self, image, title); self.canvas.scene().addItem(card)
        i = len(self.cards); card.setPos(30 + (i % 10)*110, 30 + (i // 10)*90); self.cards.append(card)
        return card

    def remove_card(self, card):
        if card.links:
            QMessageBox.information(self, '无法移除', '此图片已连接处理节点，请先保留它。'); return
        self.cards.remove(card); self.canvas.scene().removeItem(card)

    def selected_cards(self):
        return sorted((c for c in self.cards if c.isSelected()), key=lambda c: natural_key(c.title))

    def create_operation(self, sources):
        op = Operation(self, sources); self.canvas.scene().addItem(op); self.operations.append(op)
        op.update_paths(); return op

    def create_pairs(self):
        cards = self.selected_cards()
        if len(cards) < 2 or len(cards) % 2:
            QMessageBox.information(self, '创建配对', '请先框选偶数张图片（至少两张），将按文件名自然排序后两两配对。'); return
        self.canvas.scene().clearSelection()
        for i in range(0, len(cards), 2): self.create_operation(cards[i:i+2])
        self.statusBar().showMessage(f'已创建 {len(cards)//2} 个待处理节点；框选 + 后选择操作')

    def apply_xor(self):
        operations = [op for op in self.operations if op.isSelected()]
        if not operations:
            QMessageBox.information(self, '选择处理节点', '请先框选一个或多个 + 节点。'); return
        for op in operations:
            if op.output is not None:
                QMessageBox.warning(self, '已有结果', '所选节点已有结果，不能重复处理。'); return
            a, b = (c.image for c in op.sources)
            if a.shape != b.shape:
                QMessageBox.warning(self, '尺寸不一致', '选中节点中的图片尺寸不一致，未执行任何操作。'); return
        for op in operations:
            a, b = (c.image for c in op.sources)
            result = np.bitwise_xor(a, b); result[:, :, 3] = 255
            out = self.add_card(result, 'XOR 结果'); out.setPos(op.pos() + QPointF(100, 0))
            op.output = out; out.links.append(op); op.update_paths()
        self.statusBar().showMessage(f'已完成 {len(operations)} 个 XOR')

    def selected_pair_average(self, threshold):
        cards = self.selected_cards()
        result = pair_xor_average([c.image for c in cards], threshold)
        return np.array(Image.fromarray(result).convert('RGBA'))

    def average_selected(self):
        cards = self.selected_cards()
        if len(cards) < 2:
            QMessageBox.information(self, '选择图片', '请先框选至少两张图片。'); return
        self.run_batch([c.title for c in cards], lambda index: cards[index].image)

    def run_batch(self, names, get_image):
        dialog = PairDialog(self, names)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        try:
            results = []
            for group in dialog.groups:
                frames = [get_image(index) for pair in group for index in pair]
                result = pair_xor_average(frames, dialog.threshold.value())
                results.append(np.array(Image.fromarray(result).convert('RGBA')))
            for i, result in enumerate(results): self.add_card(result, f'第{i+1}组 XOR 平均')
            self.statusBar().showMessage(f'已完成 {len(results)} 组、{sum(map(len, dialog.groups))} 对图片')
        except Exception as e: QMessageBox.warning(self, '处理失败', str(e))

    def average(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '选择图片', '', '图片 (*.png *.bmp *.jpg *.jpeg *.tif *.tiff)')
        if not paths: return
        paths = sorted(paths, key=lambda p: natural_key(Path(p).name))
        self.run_batch([Path(p).name for p in paths], lambda index: load_image(paths[index]))

    def xor(self):
        selected = [c for c in self.cards if c.isSelected()]
        if len(selected) != 2:
            QMessageBox.information(self, '选择图片', '请按住 Ctrl 选中两张尺寸相同的图片。'); return
        a, b = [c.image for c in selected]
        if a.shape != b.shape:
            QMessageBox.warning(self, '尺寸不一致', '两张图片必须具有相同尺寸。'); return
        result = np.bitwise_xor(a, b); result[:, :, 3] = 255
        self.add_card(result, '两图 XOR')


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet('QWidget {font-family: "Microsoft YaHei UI"; font-size: 13px;} QPushButton {padding: 8px 14px;}')
    window = Main(); window.show(); sys.exit(app.exec())


if __name__ == '__main__': main()
