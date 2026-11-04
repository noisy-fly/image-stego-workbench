"""小型可视化工作流，节点连接按用户选择顺序建立。"""
from pathlib import Path
import math
import numpy as np
from PIL import Image
from PySide6.QtCore import Qt, QLineF, QPointF
from PySide6.QtGui import QPen, QPolygonF
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsTextItem, QGraphicsLineItem,
    QFileDialog, QMessageBox, QInputDialog)
from core import load_image, invert, bit_plane, pair_xor_average


class Node(QGraphicsRectItem):
    def __init__(self, title, operation, data=None):
        super().__init__(0, 0, 175, 64)
        self.title, self.operation, self.data = title, operation, data
        self.setBrush(Qt.GlobalColor.white)
        self.setFlags(self.GraphicsItemFlag.ItemIsMovable | self.GraphicsItemFlag.ItemIsSelectable | self.GraphicsItemFlag.ItemSendsGeometryChanges)
        label = QGraphicsTextItem(title, self); label.setDefaultTextColor(Qt.GlobalColor.black); label.setPos(8, 16)
        self.edges = []

    def itemChange(self, change, value):
        if change == self.GraphicsItemChange.ItemPositionHasChanged and hasattr(self, 'edges'):
            for edge in self.edges: edge.update_line()
        return super().itemChange(change, value)


class Edge(QGraphicsLineItem):
    def __init__(self, source, target):
        super().__init__(); self.source, self.target = source, target
        self.setPen(QPen(Qt.GlobalColor.darkCyan, 3)); self.setZValue(-1)
        source.edges.append(self); target.edges.append(self); self.update_line()

    def update_line(self):
        self.setLine(QLineF(self.source.scenePos().x()+175, self.source.scenePos().y()+32,
                            self.target.scenePos().x(), self.target.scenePos().y()+32))

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        line = self.line(); angle = math.atan2(line.dy(), line.dx()); end = line.p2()
        points = [end, end - QPointF(12*math.cos(angle-0.45), 12*math.sin(angle-0.45)),
                  end - QPointF(12*math.cos(angle+0.45), 12*math.sin(angle+0.45))]
        painter.setBrush(Qt.GlobalColor.darkCyan); painter.drawPolygon(QPolygonF(points))


class Workflow(QDialog):
    def __init__(self, parent):
        super().__init__(parent); self.owner = parent; self.nodes = []; self.edges = []
        self.setWindowTitle('图像处理流程'); self.resize(1100, 700)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('添加节点后拖动排列；按住 Ctrl 先选来源、再选目标，点击连接。选择结果节点后运行。'))
        toolbar = QHBoxLayout()
        for title, action in [('图片输入', self.input_image), ('反色', lambda: self.add('反色', 'invert')),
            ('位平面', self.plane), ('两图 XOR', lambda: self.add('两图 XOR', 'xor')),
            ('相邻帧 XOR 平均', self.sequence), ('连接所选节点', self.connect_nodes), ('运行所选节点', self.run)]:
            b = QPushButton(title); b.clicked.connect(action); toolbar.addWidget(b)
        layout.addLayout(toolbar)
        self.scene = QGraphicsScene(self); self.view = QGraphicsView(self.scene); self.view.setSceneRect(0, 0, 2200, 1500)
        self.view.setStyleSheet('background:#e9edf3;'); layout.addWidget(self.view)
        self.order = []; self.scene.selectionChanged.connect(self.remember_selection)

    def remember_selection(self):
        selected = [n for n in self.nodes if n.isSelected()]
        self.order = [n for n in self.order if n in selected]
        for node in selected:
            if node not in self.order: self.order.append(node)

    def add(self, title, operation, data=None):
        n = Node(title, operation, data); self.scene.addItem(n); n.setPos(40 + len(self.nodes)*35, 40 + len(self.nodes)*65)
        self.nodes.append(n)

    def input_image(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择输入图片', '', '图片 (*.png *.bmp *.jpg *.jpeg *.tif *.tiff)')
        if path: self.add('输入：' + Path(path).name[:14], 'input', path)

    def sequence(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '选择偶数张图片，按文件名排序', '', '图片 (*.png *.bmp *.jpg *.jpeg *.tif *.tiff)')
        if not paths: return
        threshold, ok = QInputDialog.getInt(self, '二值化阈值', '灰度值大于或等于该值为白色：', 129, 0, 255)
        if ok: self.add(f'相邻帧 XOR 平均（{len(paths)} 张）', 'sequence', (sorted(paths, key=lambda p: Path(p).name.casefold()), threshold))

    def plane(self):
        choice, ok = QInputDialog.getItem(self, '选择位平面', '通道：', ['红', '绿', '蓝', '透明度'], 0, False)
        if not ok: return
        bit, ok = QInputDialog.getInt(self, '选择位平面', '位（0 为最低位）：', 0, 0, 7)
        if ok: self.add(f'{choice}通道第 {bit} 位', 'plane', (['红', '绿', '蓝', '透明度'].index(choice), bit))

    def connect_nodes(self):
        if len(self.order) != 2:
            QMessageBox.information(self, '连接节点', '请按住 Ctrl 依次选择来源节点和目标节点。'); return
        source, target = self.order
        if source == target or any(e.source == source and e.target == target for e in self.edges): return
        edge = Edge(source, target); self.edges.append(edge); self.scene.addItem(edge)
        self.scene.clearSelection()

    def calculate(self, node, visiting):
        if node in visiting: raise ValueError('流程中存在循环连接。')
        visiting = visiting | {node}
        inputs = [self.calculate(e.source, visiting) for e in self.edges if e.target == node]
        if node.operation == 'input':
            if inputs: raise ValueError('图片输入节点不接受连接。')
            return load_image(node.data)
        if node.operation == 'sequence':
            if inputs: raise ValueError('多帧节点不接受连接。')
            paths, threshold = node.data
            result = pair_xor_average([load_image(p) for p in paths], threshold)
            return np.array(Image.fromarray(result).convert('RGBA'))
        expected = 2 if node.operation == 'xor' else 1
        if len(inputs) != expected: raise ValueError(f'{node.title}需要 {expected} 个输入，当前有 {len(inputs)} 个。')
        if node.operation == 'invert': return invert(inputs[0])
        if node.operation == 'plane': return np.array(Image.fromarray(bit_plane(inputs[0], *node.data)).convert('RGBA'))
        if inputs[0].shape != inputs[1].shape: raise ValueError('两张图片尺寸必须一致。')
        result = np.bitwise_xor(inputs[0], inputs[1]); result[:, :, 3] = 255; return result

    def run(self):
        if len(self.order) != 1:
            QMessageBox.information(self, '运行流程', '请只选择一个结果节点。'); return
        try:
            result = self.calculate(self.order[0], set())
            self.owner.add_card(result, '流程结果', generated=True)
            QMessageBox.information(self, '运行完成', '结果已添加到主画布。')
        except Exception as exc:
            QMessageBox.warning(self, '运行失败', str(exc))
