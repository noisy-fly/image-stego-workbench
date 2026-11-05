import sys
import io
import itertools
import re
import uuid
import os
from pathlib import Path

import numpy as np
from PIL import Image
from app_version import APP_VERSION
from PySide6.QtCore import Qt, QTimer, QPointF, QEvent, QMimeData, QRectF
from PySide6.QtGui import QImage, QPixmap, QPainterPath, QPen, QColor, QAction, QMouseEvent
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QMessageBox, QGraphicsView, QGraphicsScene,
    QGraphicsPixmapItem, QGraphicsTextItem, QMenu, QDialog, QListWidget, QListWidgetItem,
    QSplitter, QSpinBox, QComboBox, QCheckBox, QTextEdit, QInputDialog,
    QGraphicsEllipseItem, QGraphicsPathItem)
from PySide6.QtGui import QIcon
from core import (load_image, bit_plane, channel, invert, extract_bits, pair_xor_average,
                  make_pair_groups, process_image, combine_images, aggregate_images, scan_lsb)


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
    def __init__(self, parent, image, title, source_ref=None):
        super().__init__(parent)
        self.image = image
        self.source_ref = source_ref
        self.setWindowTitle('图片分析 — ' + title)
        self.resize(1050, 760)
        layout = QVBoxLayout(self)
        search_button = QPushButton('基本信息快速搜索')
        search_button.setObjectName('basicSearchButton')
        search_button.clicked.connect(self.basic_search)
        top = QHBoxLayout(); top.addWidget(search_button)
        hex_button = QPushButton('十六进制编辑'); hex_button.setObjectName('hexEditorButton')
        hex_button.clicked.connect(self.edit_hex); top.addWidget(hex_button); layout.addLayout(top)
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
        for label, callback in [('保存当前图片', self.save), ('检查隐藏文件', self.inspect_original), ('LSB 快速检查', self.quick_scan), ('条件 LSB 检查', self.conditional_scan), ('手动提取位数据', self.extract)]:
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

    def basic_search(self):
        from basic_search_dialog import BasicSearchDialog
        BasicSearchDialog(self, self.source_ref).exec()

    def edit_hex(self):
        from hex_editor import HexEditorDialog
        def add_to_canvas(image, title, reference):
            owner = self.parent()
            before = owner.snapshot()
            owner.add_card(image, title, source_ref=reference)
            owner.remember(before)
            owner.statusBar().showMessage('已将编辑后的图片添加到画布')
        try: HexEditorDialog(self, self.source_ref, add_to_canvas).exec()
        except (OSError, ValueError) as error: QMessageBox.warning(self, '无法打开十六进制编辑', str(error))

    def inspect_original(self):
        from file_dialog import FileInspectionDialog
        FileInspectionDialog(self, self.source_ref).exec()

    def quick_scan(self):
        dialog = QDialog(self); dialog.setWindowTitle('LSB 快速检查'); dialog.resize(820, 600)
        box = QVBoxLayout(dialog)
        box.addWidget(QLabel('检查前 65,536 个像素；按行 / 按列、RGBA 通道排列、第 0/1 位及两种字节位序。'))
        box.addWidget(QLabel('识别少量常见文件头和名称{内容}格式文本；候选可能误报，未发现不代表没有隐写。'))
        status = QLabel('正在检查…'); box.addWidget(status)
        results_list = QListWidget(); box.addWidget(results_list)
        preview = QTextEdit(); preview.setReadOnly(True); preview.setMaximumHeight(145); box.addWidget(preview)
        button = QPushButton('使用选中结果的参数提取完整数据'); button.setEnabled(False); box.addWidget(button)
        results = []
        def run():
            try:
                results.extend(scan_lsb(self.image))
            except Exception as exc:
                status.setText('检查失败：' + str(exc)); return
            status.setText(f'检查完成：发现 {len(results)} 条候选线索' if results else '检查完成：没有发现上述范围内的线索')
            for item in results:
                channels = ''.join('RGBA'[i] for i in item['channels'])
                order = '按列' if item['column'] else '按行'
                packing = '低位先装入' if item['little'] else '高位先装入'
                results_list.addItem(f"{item['kind']} · {channels} 第 {item['bit']} 位 · {order} · {packing} · 字节偏移 {item['offset']}")
        def show_result(index):
            button.setEnabled(index >= 0)
            if index < 0: preview.clear(); return
            data = results[index]['preview']
            preview.setPlainText('命中位置起的预览（最多 80 字节）：\n文本：' + data.decode('utf-8', errors='replace') + '\n十六进制：' + data.hex(' '))
        def open_extract():
            index = results_list.currentRow()
            if index >= 0: self.extract(results[index])
        results_list.currentRowChanged.connect(show_result); button.clicked.connect(open_extract)
        QTimer.singleShot(0, run); dialog.exec()

    def conditional_scan(self):
        from conditional_lsb import ConditionalDialog
        ConditionalDialog(self, self.image, self.extract).exec()

    def extract(self, preset=None):
        if not isinstance(preset, dict): preset = {}
        dialog = QDialog(self)
        dialog.setWindowTitle('提取像素位数据')
        dialog.resize(700, 500)
        box = QVBoxLayout(dialog)
        box.addWidget(QLabel('选择通道和位，并设置读取顺序。'))
        row = QHBoxLayout()
        checks = []
        for name in 'RGBA':
            c = QCheckBox(name)
            c.setChecked('RGBA'.index(name) in preset.get('channels', (0, 1, 2)))
            row.addWidget(c)
            checks.append(c)
        box.addLayout(row)
        order_row = QHBoxLayout(); order_row.addWidget(QLabel('通道顺序：'))
        channel_order = QComboBox(); channel_order.setObjectName('channelOrder')
        channel_order.addItems([''.join(order) for order in itertools.permutations('RGBA')])
        selected = preset.get('channels', (0, 1, 2))
        preferred = ''.join('RGBA'[i] for i in selected) + ''.join('RGBA'[i] for i in range(4) if i not in selected)
        channel_order.setCurrentText(preferred); order_row.addWidget(channel_order)
        order_row.addWidget(QLabel('仅使用勾选的通道')); box.addLayout(order_row)
        bit_row = QHBoxLayout(); bit_checks = []
        for i in range(8):
            check = QCheckBox(f'第{i}位'); check.setChecked(i in preset.get('bits', (preset.get('bit', 0),))); bit_checks.append(check); bit_row.addWidget(check)
        box.addLayout(bit_row)
        from PySide6.QtWidgets import QLineEdit
        bit_order = QLineEdit(','.join(str(i) for i in preset.get('bits', tuple(range(8)))))
        bit_order.setPlaceholderText('例如 4,2,1；其他未选中的位可省略')
        bit_order.setObjectName('bitOrder'); box.addWidget(QLabel('位的读取顺序（逗号分隔，仅使用勾选的位）：')); box.addWidget(bit_order)
        column = QCheckBox('按列扫描（默认按行）'); column.setChecked(preset.get('column', False)); box.addWidget(column)
        reverse_x = QCheckBox('水平反向扫描（从右向左）'); box.addWidget(reverse_x)
        reverse_y = QCheckBox('垂直反向扫描（从下向上）'); box.addWidget(reverse_y)
        little = QCheckBox('每字节低位先写入'); little.setChecked(preset.get('little', False)); box.addWidget(little)
        offset = QSpinBox(); offset.setRange(0, 1000000000); offset.setPrefix('跳过前面的位数：'); offset.setValue(preset.get('skip_bits', preset.get('offset', 0) * 8)); box.addWidget(offset)
        if preset: box.addWidget(QLabel('已载入候选参数，提取从该线索的字节偏移处开始。'))
        output = QTextEdit(); output.setReadOnly(True); box.addWidget(output)
        data = [b'']
        def run():
            components = ['RGBA'.index(name) for name in channel_order.currentText() if checks['RGBA'.index(name)].isChecked()]
            selected_bits = [i for i, c in enumerate(bit_checks) if c.isChecked()]
            try: bits = [int(v.strip()) for v in bit_order.text().replace('，', ',').split(',') if v.strip()]
            except ValueError: QMessageBox.warning(dialog, '提示', '位顺序请填写 0 到 7，用逗号分隔。'); return
            if len(bits) != len(set(bits)) or any(i not in range(8) for i in bits) or any(i not in bits for i in selected_bits):
                QMessageBox.warning(dialog, '提示', '位顺序不得重复，并须包含全部勾选的位（0 到 7）。'); return
            bits = [i for i in bits if i in selected_bits]
            if not components or not bits:
                QMessageBox.warning(dialog, '提示', '请至少选择一个通道和一个位。'); return
            data[0] = extract_bits(self.image, components, bits, column.isChecked(), little.isChecked(),
                                   reverse_x.isChecked(), reverse_y.isChecked(), offset.value())
            sample = data[0][:4096]
            output.setPlainText('前 4096 字节（十六进制）：\n' + sample.hex(' ') + '\n\n文本预览：\n' + sample.decode('utf-8', errors='replace'))
        def export():
            path, _ = QFileDialog.getSaveFileName(dialog, '保存提取数据', '提取结果.bin', '所有文件 (*)')
            if path: Path(path).write_bytes(data[0])
        b = QPushButton('提取并预览'); b.clicked.connect(run); box.addWidget(b)
        b = QPushButton('保存提取数据'); b.clicked.connect(export); box.addWidget(b)
        dialog.exec()


class Card(QGraphicsPixmapItem):
    def __init__(self, parent, image, title, generated=False, source_ref=None):
        super().__init__(pixmap(image, 72, 48))
        self.setShapeMode(QGraphicsPixmapItem.ShapeMode.BoundingRectShape)
        self.owner, self.image, self.title, self.generated = parent, image, title, generated
        self.source_ref = source_ref
        self.links = []
        self.setFlags(self.GraphicsItemFlag.ItemIsMovable | self.GraphicsItemFlag.ItemIsSelectable | self.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.label = QGraphicsTextItem(title[:12], self)
        self.label.setScale(0.8)
        self.label.setDefaultTextColor(Qt.GlobalColor.white)
        self.label.setPos(0, 49)
        self.timer = QTimer(); self.timer.setSingleShot(True); self.timer.timeout.connect(self.hover_preview)

    def mouseDoubleClickEvent(self, event):
        self.timer.stop(); Analysis(self.owner, self.image, self.title, self.source_ref).exec()

    def hoverEnterEvent(self, event):
        self.timer.start(1000); super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.timer.stop(); self.owner.tip.hide(); super().hoverLeaveEvent(event)

    def hover_preview(self):
        self.owner.tip.setPixmap(pixmap(self.image, 320, 220))
        self.owner.tip.adjustSize(); self.owner.tip.move(__import__('PySide6').QtGui.QCursor.pos() + __import__('PySide6').QtCore.QPoint(15, 15)); self.owner.tip.show()

    def contextMenuEvent(self, event):
        self.timer.stop(); self.owner.tip.hide()
        menu = QMenu(); menu.addAction('打开图片分析', lambda: Analysis(self.owner, self.image, self.title, self.source_ref).exec())
        if not self.isSelected():
            self.owner.canvas.scene().clearSelection(); self.setSelected(True)
        modules = self.owner.module_menu(); modules.setTitle('处理模块'); menu.addMenu(modules)
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
        for source in sources: source.links.append(self)

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        painter.setPen(QPen(QColor('#174f49'), 2.5))
        painter.drawLine(10, 17, 24, 17); painter.drawLine(17, 10, 17, 24)

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
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.auto_timer = QTimer(self); self.auto_timer.setInterval(25); self.auto_timer.timeout.connect(self.auto_scroll)
        self.drag_position = None
        self.move_before = None; self.move_positions = None
        QTimer.singleShot(0, lambda: (self.horizontalScrollBar().setValue(0), self.verticalScrollBar().setValue(0)))

    def zoom(self, factor):
        current = self.transform().m11()
        target = max(0.2, min(4.0, current * factor))
        self.scale(target / current, target / current)
        self.owner.statusBar().showMessage(f'画布缩放：{round(target * 100)}%')

    def reset_zoom(self):
        self.resetTransform(); self.owner.statusBar().showMessage('画布缩放：100%')

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
    def dropEvent(self, event):
        self.owner.load_paths([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]); event.acceptProposedAction()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.itemAt(event.position().toPoint()) is not None:
            self.move_before = self.owner.snapshot()
            self.move_positions = [(c.pos().x(), c.pos().y()) for c in self.owner.cards]
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self.itemAt(event.position().toPoint()) is None:
            self.drag_position = event.position(); self.auto_timer.start()

    def mouseMoveEvent(self, event):
        if self.auto_timer.isActive(): self.drag_position = event.position()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.auto_timer.stop(); self.drag_position = None
        super().mouseReleaseEvent(event)
        if self.move_before is not None and self.move_positions != [(c.pos().x(), c.pos().y()) for c in self.owner.cards]:
            self.owner.remember(self.move_before)
        self.move_before = None; self.move_positions = None

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.NoModifier and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.owner.select_direction('input' if event.key() == Qt.Key.Key_Left else 'output')
            event.accept(); return
        super().keyPressEvent(event)

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
    def __init__(self, parent, names, graph=False):
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
        if graph: self.threshold.hide()
        box.addWidget(QLabel('配对预览（每组展示前 4 对；计算前请核对）：'))
        self.preview = QTextEdit(); self.preview.setReadOnly(True); box.addWidget(self.preview)
        buttons = QHBoxLayout(); run = QPushButton('创建配对' if graph else '开始计算'); cancel = QPushButton('取消')
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
        self.undo_stack = []; self.redo_stack = []; self.clipboard_cards = []; self.clipboard_token = ''
        self.tip = QLabel(None, Qt.WindowType.ToolTip); self.tip.setStyleSheet('background:#111;padding:6px;')
        panel = QWidget(); self.setCentralWidget(panel); layout = QVBoxLayout(panel)
        title = QLabel('图片隐写工作台'); title.setStyleSheet('font-size:17pt;font-weight:700;'); layout.addWidget(title)
        layout.addWidget(QLabel('拖动框选 · 双击图片分析 · Ctrl + / − 缩放画布'))
        toolbar = QHBoxLayout()
        for text, func in [('导入图片', self.browse), ('单图分析', self.open_analysis), ('创建配对 +', self.create_pairs)]:
            button = QPushButton(text); button.clicked.connect(func); toolbar.addWidget(button, 1)
        for text, menu in [('单图处理', self.single_menu()), ('双图组合', self.combine_menu()),
                           ('多图统计', self.statistics_menu()), ('更多工具', self.more_menu()), ('设置', self.settings_menu())]:
            button = QPushButton(text); button.setMenu(menu); toolbar.addWidget(button, 1)
        layout.addLayout(toolbar)
        self.canvas = Canvas(self); layout.addWidget(self.canvas)
        from update_ui import UpdateController
        self.updater = UpdateController(self)
        self.direction_context = None; self.changing_direction = False
        self.canvas.scene().selectionChanged.connect(self.selection_changed)
        self.statusBar().showMessage('准备就绪')
        for key, callback in [('Ctrl+A', self.select_all), ('Ctrl+C', self.copy_selection), ('Ctrl+V', self.paste_selection),
                              ('Ctrl+Z', self.undo), ('Ctrl+Shift+Z', self.redo), ('Ctrl+Y', self.redo), ('Delete', self.delete_selection),
                              ('Ctrl++', lambda: self.canvas.zoom(1.25)), ('Ctrl+=', lambda: self.canvas.zoom(1.25)),
                              ('Ctrl+-', lambda: self.canvas.zoom(0.8)), ('Ctrl+0', self.canvas.reset_zoom)]:
            action = QAction(self); action.setShortcut(key); action.triggered.connect(callback); self.addAction(action)

    @staticmethod
    def add_menu_action(parent, text, callback):
        action = parent.addAction(text); action.triggered.connect(callback)

    def single_menu(self):
        single = QMenu('单图处理（选中图片）', self); add = self.add_menu_action
        for label, key in [('灰度', 'gray'), ('反色', 'invert'), ('水平翻转', 'flip_h'), ('垂直翻转', 'flip_v'),
                           ('顺时针旋转 90°', 'rotate_cw'), ('逆时针旋转 90°', 'rotate_ccw'),
                           ('自动对比度', 'contrast'), ('直方图均衡', 'equalize'), ('边缘检测', 'edges')]:
            add(single, label, lambda checked=False, k=key, name=label: self.apply_single(k, name))
        add(single, '阈值二值化…', self.ask_threshold)
        add(single, '高斯模糊…', self.ask_blur)
        add(single, '批量提取通道…', self.ask_channel)
        add(single, '查看某个位平面…', self.ask_plane)
        add(single, '最低若干位增强显示…', self.ask_low_bits)
        add(single, 'RGB 像素异或固定数值…', self.ask_constant_xor)
        add(single, 'RGB 三通道相互异或', lambda: self.apply_single('rgb_xor', 'RGB通道异或'))
        add(single, '交换红蓝通道', lambda: self.apply_single('swap_rb', '交换红蓝'))
        return single

    def combine_menu(self):
        combine = QMenu('双图组合（选中 + 节点）', self); add = self.add_menu_action
        for label, key in [('按位异或 XOR', 'xor'), ('异或后反相 XNOR', 'xnor'), ('按位与 AND', 'and'), ('按位或 OR', 'or'),
                           ('绝对差值', 'difference'), ('相加（溢出回绕）', 'add'),
                           ('相减（前图减后图，溢出回绕）', 'subtract'), ('两图平均', 'mean')]:
            add(combine, label, lambda checked=False, k=key, name=label: self.apply_combine(k, name))
        return combine

    def statistics_menu(self):
        multi = QMenu('多图统计（选中图片）', self); add = self.add_menu_action
        for label, key in [('逐像素平均', 'mean'), ('逐像素最小值', 'min'), ('逐像素最大值', 'max')]:
            add(multi, label, lambda checked=False, k=key, name=label: self.apply_aggregate(k, name))
        add(multi, '配对 XOR 后平均…', self.average_selected)
        return multi

    def more_menu(self):
        menu = QMenu('更多工具', self)
        self.add_menu_action(menu, '从文件提取并分组图片…', self.open_extract_dialog)
        self.add_menu_action(menu, '图形工作流', self.workflow)
        self.add_menu_action(menu, '从文件批量配对并平均…', self.average)
        return menu

    def settings_menu(self):
        menu = QMenu('设置', self)
        version = menu.addAction(f'当前版本：{APP_VERSION}'); version.setEnabled(False)
        menu.addSeparator()
        self.add_menu_action(menu, '检测更新', lambda: self.updater.check(manual=True))
        return menu

    def open_extract_dialog(self):
        from extract_dialog import ExtractDialog
        ExtractDialog(self).exec()

    def module_menu(self):
        menu = QMenu(self)
        for submenu in (self.single_menu(), self.combine_menu(), self.statistics_menu()): menu.addMenu(submenu)
        return menu

    def open_analysis(self):
        cards = self.selected_cards()
        if len(cards) != 1:
            QMessageBox.information(self, '单图分析', '请选择一张图片，或直接双击图片。'); return
        Analysis(self, cards[0].image, cards[0].title, cards[0].source_ref).exec()

    def ask_channel(self):
        labels = ['红', '绿', '蓝', '透明度']
        name, ok = QInputDialog.getItem(self, '批量提取通道', '选择要生成的灰度通道：', labels, 0, False)
        if ok: self.apply_single('channel', name + '通道', component=labels.index(name))

    def ask_threshold(self):
        value, ok = QInputDialog.getInt(self, '阈值二值化', '灰度值大于或等于阈值为白色：', 129, 0, 255)
        if ok: self.apply_single('threshold', f'二值化 {value}', threshold=value)

    def ask_blur(self):
        value, ok = QInputDialog.getDouble(self, '高斯模糊', '模糊半径（像素）：', 1.0, 0, 100, 1)
        if ok: self.apply_single('blur', f'高斯模糊 {value}', radius=value)

    def ask_plane(self):
        labels = ['红', '绿', '蓝', '透明度']
        name, ok = QInputDialog.getItem(self, '位平面', '选择通道：', labels, 0, False)
        if not ok: return
        bit, ok = QInputDialog.getInt(self, '位平面', '选择位（0 是最低位）：', 0, 0, 7)
        if ok: self.apply_single('plane', f'{name}通道第{bit}位', component=labels.index(name), bit=bit)

    def ask_low_bits(self):
        bits, ok = QInputDialog.getInt(self, '最低位增强显示', '提取 RGB 各通道最低几位并拉伸到 0–255：', 2, 1, 8)
        if ok: self.apply_single('low_bits', f'最低{bits}位增强', bits=bits)

    def ask_constant_xor(self):
        value, ok = QInputDialog.getInt(self, '像素异或固定数值', 'RGB 各通道与该数值逐位异或（十进制）：', 1, 0, 255)
        if ok: self.apply_single('constant_xor', f'异或{value}', value=value)

    def apply_single(self, operation, label, **options):
        cards = self.selected_cards()
        if not cards:
            QMessageBox.information(self, '选择图片', '请先选择一张或多张图片。'); return
        try: results = [process_image(card.image, operation, **options) for card in cards]
        except Exception as exc: QMessageBox.warning(self, '处理失败', str(exc)); return
        before = self.snapshot(); self.canvas.scene().clearSelection()
        for card, result in zip(cards, results):
            op = self.create_operation([card]); out = self.add_card(result, label + ' 结果', generated=True)
            op.output = out; out.links.append(op); op.update_paths(); out.setSelected(True)
        self.remember(before); self.statusBar().showMessage(f'{label}：已处理 {len(results)} 张图片')

    def apply_aggregate(self, operation, label):
        cards = self.selected_cards()
        if len(cards) < 2:
            QMessageBox.information(self, '选择图片', '请先选择至少两张图片。'); return
        try: result = aggregate_images([c.image for c in cards], operation)
        except Exception as exc: QMessageBox.warning(self, '处理失败', str(exc)); return
        before = self.snapshot(); self.canvas.scene().clearSelection()
        result_card = self.add_card(result, label + ' 结果', generated=True); result_card.setSelected(True)
        self.remember(before); self.statusBar().showMessage(f'{label}：已统计 {len(cards)} 张图片')

    def snapshot(self):
        indices = {card: i for i, card in enumerate(self.cards)}
        cards = [(c.image, c.title, c.pos().x(), c.pos().y(), c.isSelected(), c.generated, c.source_ref) for c in self.cards]
        operations = [([indices[c] for c in op.sources], indices[op.output] if op.output is not None else None, op.isSelected()) for op in self.operations]
        return cards, operations, self.canvas.sceneRect()

    def remember(self, before):
        self.undo_stack.append(before); self.undo_stack = self.undo_stack[-25:]; self.redo_stack.clear()

    def restore(self, state):
        cards, operations, rect = state
        self.tip.hide()
        for card in self.cards: card.timer.stop()
        self.canvas.scene().clear(); self.cards = []; self.operations = []
        self.canvas.setSceneRect(rect)
        for image, title, x, y, selected, generated, source_ref in cards:
            card = Card(self, image, title, generated, source_ref); self.canvas.scene().addItem(card); self.cards.append(card)
            card.setPos(x, y); card.setSelected(selected)
        for sources, output, selected in operations:
            op = self.create_operation([self.cards[i] for i in sources]); op.setSelected(selected)
            if output is not None:
                op.output = self.cards[output]; op.output.links.append(op); op.update_paths()

    def undo(self):
        if not self.undo_stack: self.statusBar().showMessage('没有可撤销的操作'); return
        self.redo_stack.append(self.snapshot()); self.restore(self.undo_stack.pop()); self.statusBar().showMessage('已撤销')

    def redo(self):
        if not self.redo_stack: self.statusBar().showMessage('没有可重做的操作'); return
        self.undo_stack.append(self.snapshot()); self.restore(self.redo_stack.pop()); self.statusBar().showMessage('已重做')

    def copy_selection(self):
        cards = self.selected_cards()
        if not cards: self.statusBar().showMessage('请先选择图片'); return
        self.clipboard_cards = [(c.image, c.title, c.generated, c.source_ref) for c in cards]
        self.clipboard_token = uuid.uuid4().hex
        mime = QMimeData(); mime.setData('application/x-stego-workbench', self.clipboard_token.encode())
        if len(cards) == 1: mime.setImageData(pixmap(cards[0].image).toImage())
        QApplication.clipboard().setMimeData(mime)
        self.statusBar().showMessage(f'已复制 {len(cards)} 张图片')

    def paste_selection(self):
        mime = QApplication.clipboard().mimeData()
        if mime.hasUrls():
            self.load_paths([url.toLocalFile() for url in mime.urls() if url.isLocalFile()]); return
        if mime.hasFormat('application/x-stego-workbench') and bytes(mime.data('application/x-stego-workbench')).decode() == self.clipboard_token:
            copies = self.clipboard_cards
        elif mime.hasImage():
            image = QApplication.clipboard().image().convertToFormat(QImage.Format.Format_RGBA8888)
            data = np.frombuffer(image.bits(), dtype=np.uint8).reshape(image.height(), image.bytesPerLine())[:, :image.width()*4].reshape(image.height(), image.width(), 4).copy()
            copies = [(data, '剪贴板图片', False, None)]
        else:
            self.statusBar().showMessage('剪贴板中没有可粘贴的图片'); return
        before = self.snapshot(); self.canvas.scene().clearSelection()
        for image, title, generated, source_ref in copies:
            card = self.add_card(image, title + ' 副本', generated=generated, source_ref=source_ref); card.setSelected(True)
        self.remember(before); self.statusBar().showMessage(f'已粘贴 {len(copies)} 张图片')

    def delete_selection(self):
        cards = [c for c in self.cards if c.isSelected()]
        ops = [op for op in self.operations if op.isSelected() or any(c in op.sources or c is op.output for c in cards)]
        if not cards and not ops: return
        before = self.snapshot()
        for op in ops:
            for card in op.sources + ([op.output] if op.output is not None else []):
                if op in card.links: card.links.remove(op)
            for path in op.paths: self.canvas.scene().removeItem(path)
            self.canvas.scene().removeItem(op); self.operations.remove(op)
        for card in cards:
            card.timer.stop(); self.canvas.scene().removeItem(card); self.cards.remove(card)
        self.remember(before); self.statusBar().showMessage('已从画布删除，Ctrl+Z 可撤销')

    def select_all(self):
        for item in self.cards + self.operations: item.setSelected(True)
        self.canvas.setFocus()

    def selection_changed(self):
        if not self.changing_direction: self.direction_context = None

    def select_direction(self, direction):
        if self.direction_context is None:
            selected = {c for c in self.cards if c.isSelected()}
            operations = [op for op in self.operations if op.isSelected()]
            if not selected and not operations:
                self.statusBar().showMessage('请先选择图片或处理节点'); return
            sources = {c for op in operations for c in op.sources}
            outputs = {op.output for op in operations if op.output is not None}
            sources.update(c for c in selected if not c.generated)
            outputs.update(c for c in selected if c.generated)
            self.direction_context = (sources, outputs)
        targets = self.direction_context[0 if direction == 'input' else 1]
        if not targets:
            self.statusBar().showMessage('当前选中范围没有对应的输入图片' if direction == 'input' else '当前选中范围没有处理结果'); return
        self.changing_direction = True
        try:
            self.canvas.scene().clearSelection()
            for card in targets: card.setSelected(True)
        finally: self.changing_direction = False
        self.statusBar().showMessage(f'已选中 {len(targets)} 张' + ('输入图片' if direction == 'input' else '处理结果'))

    def browse(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '导入图片', '', '图片 (*.png *.bmp *.jpg *.jpeg *.gif *.tif *.tiff *.webp *.bpg);;所有文件 (*)')
        self.load_paths(paths)

    def workflow(self):
        from workflow_canvas import Workflow
        Workflow(self).exec()

    def load_paths(self, paths):
        before = self.snapshot(); old_count = len(self.cards)
        errors = []; repairs = []
        for path in sorted(paths, key=lambda p: natural_key(Path(p).name)):
            try:
                from file_inspection import source_reference
                ref = source_reference(path); repair = None
                try:
                    image = load_image(path)
                    from bmp_repair import bmp_height_candidate, bmp_with_height
                    candidate = bmp_height_candidate(path)
                    if candidate:
                        old, height, extra = candidate
                        answer = QMessageBox.question(self, '发现 BMP 高度异常', f'{Path(path).name} 的高度为 {old}，文件数据约可容纳 {height} 行（剩余 {extra} 字节）。这只是推测，多余数据也可能是隐藏内容。是否使用候选高度导入？原文件不会修改。')
                        if answer == QMessageBox.StandardButton.Yes:
                            image = load_image(io.BytesIO(bmp_with_height(path, height))); repair = f'高度 {old} → {height}（根据数据长度推测）'
                except (OSError, ValueError):
                    if Path(path).suffix.lower() == '.bpg': raise
                    from png_repair import repair_png_dimensions, MAX_FILE_SIZE
                    if ref[1] > MAX_FILE_SIZE: raise ValueError('图片读取失败，文件超过自动修复大小上限（256 MiB）。')
                    with open(path, 'rb') as source: repaired = repair_png_dimensions(source.read(MAX_FILE_SIZE + 1))
                    if not repaired: raise ValueError('图片无法读取，也未找到唯一可靠的 PNG 宽高修复结果。')
                    data, repair = repaired; image = load_image(io.BytesIO(data))
                if source_reference(path) != ref: raise ValueError('文件在导入时发生变化，请重试。')
                self.add_card(image, Path(path).name + ('（已修复）' if repair else ''), source_ref=ref)
                if repair: repairs.append(f'{Path(path).name}：{repair}')
            except Exception as e: errors.append(f'{Path(path).name}: {e}')
        if errors: QMessageBox.warning(self, '部分图片无法打开', '\n'.join(errors[:10]))
        if repairs:
            QMessageBox.information(self, '已自动修复并导入', '\n'.join(repairs[:10]) + '\n修复仅用于显示，原文件保持不变；检查隐藏文件时仍读取原文件。')
        if len(self.cards) != old_count: self.remember(before)
        self.statusBar().showMessage(f'画布中有 {len(self.cards)} 张图片' + (f'，自动修复 {len(repairs)} 张' if repairs else ''))

    def add_card(self, image, title, generated=False, source_ref=None):
        card = Card(self, image, title, generated, source_ref); self.canvas.scene().addItem(card)
        i = 0
        occupied = [c.sceneBoundingRect().adjusted(-10, -10, 10, 28) for c in self.cards]
        occupied += [op.sceneBoundingRect().adjusted(-10, -10, 10, 10) for op in self.operations]
        while True:
            x, y = 30 + (i % 10)*110, 30 + (i // 10)*90
            rect = QRectF(x, y, 72, 70)
            if not any(rect.intersects(other) for other in occupied): break
            i += 1
        card.setPos(x, y); self.cards.append(card); self.expand_scene(x+160, y+150)
        return card

    def expand_scene(self, x, y):
        rect = self.canvas.sceneRect()
        self.canvas.setSceneRect(rect.united(QRectF(0, 0, x, y)))

    def remove_card(self, card):
        if card.links:
            QMessageBox.information(self, '无法移除', '此图片已连接处理节点，请先保留它。'); return
        before = self.snapshot(); card.timer.stop(); self.cards.remove(card); self.canvas.scene().removeItem(card); self.remember(before)

    def selected_cards(self):
        return sorted((c for c in self.cards if c.isSelected()), key=lambda c: natural_key(c.title))

    def create_operation(self, sources):
        op = Operation(self, sources); self.canvas.scene().addItem(op); self.operations.append(op)
        op.update_paths(); return op

    def create_pairs(self):
        cards = self.selected_cards()
        if len(cards) < 2:
            QMessageBox.information(self, '创建配对', '请先框选至少两张图片。'); return
        dialog = PairDialog(self, [c.title for c in cards], graph=True)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        self.make_pairs(cards, dialog.groups)

    def make_pairs(self, cards, groups):
        pairs = [pair for group in groups for pair in group]
        before = self.snapshot()
        chosen = {cards[i] for pair in pairs for i in pair}
        others = [c for c in self.cards if c not in chosen]
        origin_x = max([c.sceneBoundingRect().right() + 200 for c in others] +
                       [op.sceneBoundingRect().right() + 200 for op in self.operations] + [-70]) + 100
        origin_y = 30
        self.canvas.scene().clearSelection()
        for index, (a, b) in enumerate(pairs):
            x, y = origin_x + (index % 3)*380, origin_y + (index // 3)*165
            cards[a].setPos(x, y); cards[b].setPos(x, y+75)
            self.create_operation([cards[a], cards[b]])
        self.expand_scene(origin_x+3*380, origin_y+((len(pairs)+2)//3)*165+150)
        self.remember(before)
        self.statusBar().showMessage(f'已创建 {len(pairs)} 个待处理节点；框选 + 后选择操作')

    def apply_xor(self):
        self.apply_combine('xor', 'XOR')

    def apply_combine(self, operation, label):
        operations = [op for op in self.operations if op.isSelected()]
        if not operations:
            QMessageBox.information(self, '选择处理节点', '请先框选一个或多个 + 节点。'); return
        before = self.snapshot()
        for op in operations:
            if op.output is not None:
                QMessageBox.warning(self, '已有结果', '所选节点已有结果，不能重复处理。'); return
            a, b = (c.image for c in op.sources)
            if a.shape != b.shape:
                QMessageBox.warning(self, '尺寸不一致', '选中节点中的图片尺寸不一致，未执行任何操作。'); return
        for op in operations:
            a, b = (c.image for c in op.sources)
            result = combine_images(a, b, operation)
            out = self.add_card(result, label + ' 结果', generated=True); out.setPos(op.pos() + QPointF(100, 0))
            op.output = out; out.links.append(op); op.update_paths()
        self.remember(before)
        self.statusBar().showMessage(f'已完成 {len(operations)} 个{label}')

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
            before = self.snapshot()
            for i, result in enumerate(results): self.add_card(result, f'第{i+1}组 XOR 平均', generated=True)
            self.remember(before)
            self.statusBar().showMessage(f'已完成 {len(results)} 组、{sum(map(len, dialog.groups))} 对图片')
        except Exception as e: QMessageBox.warning(self, '处理失败', str(e))

    def average(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '选择图片', '', '图片 (*.png *.bmp *.jpg *.jpeg *.tif *.tiff *.bpg)')
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
        self.add_card(result, '两图 XOR', generated=True)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet('QWidget {font-family: "Microsoft YaHei UI"; font-size: 10pt;} QPushButton {padding: 8px 14px;}')
    if '--smoke-test' in sys.argv:
        from workflow_canvas import Workflow
        from extract_dialog import ExtractDialog
        from extract_sources import inspect_source, extract_groups
        import av
        import tempfile
        from app_version import APP_VERSION
        expected_version = os.environ.get('STEGO_EXPECT_VERSION')
        if expected_version and APP_VERSION != expected_version: raise ValueError('安装版版本号不匹配。')
        bpg_sample = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'vendor' / 'bpg' / 'sample.bpg'
        assert tuple(load_image(bpg_sample)[0, 0]) == (255, 0, 0, 128)
        image = np.full((4, 4, 4), 255, dtype=np.uint8)
        window = Main(); window.add_card(image, '测试.png')
        analysis = Analysis(window, image, '测试.png'); flow = Workflow(window); extractor = ExtractDialog(window)
        assert len(analysis.variants) == 38 and flow.scene is not None and extractor is not None and av.time_base > 0
        with tempfile.TemporaryDirectory() as temp:
            from basic_search import search_basic
            from file_inspection import source_reference
            basic_sample = Path(temp) / 'basic.bin'; basic_sample.write_bytes(b'demo{smoke}')
            assert search_basic(source_reference(basic_sample))['matches'][0]['text'] == 'demo{smoke}'
            from hex_editor import HexEditorDialog
            hex_sample = Path(temp) / 'hex.png'; Image.new('RGB', (2, 2), 'red').save(hex_sample)
            hex_dialog = HexEditorDialog(window, source_reference(hex_sample), lambda *args: None)
            assert hex_dialog.model.data(hex_dialog.model.index(0, 1)) == '89'
            hex_dialog.close()
            video = str(Path(temp) / 'smoke.mkv')
            with av.open(video, 'w') as container:
                stream = container.add_stream('ffv1', rate=10)
                stream.width = 8; stream.height = 8; stream.pix_fmt = 'bgr0'
                for value in (40, 80, 123):
                    frame = av.VideoFrame.from_ndarray(np.full((8, 8, 3), value, dtype=np.uint8), format='rgb24')
                    for packet in stream.encode(frame): container.mux(packet)
                for packet in stream.encode(): container.mux(packet)
            track = inspect_source(video)[0]
            result = extract_groups(video, 'video', track['index'], temp, count=1, group_size=1, end_mode='frames')
            with Image.open(result['groups'][0][0]) as extracted:
                assert extracted.convert('RGB').getpixel((0, 0)) == (123, 123, 123)
        if sys.stdout is not None: print('SMOKE_OK', flush=True)
        return
    window = Main(); window.show(); QTimer.singleShot(1200, lambda: window.updater.check(manual=False)); sys.exit(app.exec())


if __name__ == '__main__': main()
