"""Local barcode and QR recognition; results are never opened automatically."""
import numpy as np
from PIL import Image
import zxingcpp
from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QListWidget, QTextEdit, QPushButton


def scan_codes(image):
    if image.ndim == 2:
        source = Image.fromarray(np.ascontiguousarray(image))
    else:
        source = Image.fromarray(np.ascontiguousarray(image))
        if source.mode == 'RGBA':
            background = Image.new('RGBA', source.size, 'white')
            source = Image.alpha_composite(background, source).convert('RGB')
        else: source = source.convert('RGB')
    results = zxingcpp.read_barcodes(source)
    return [{'format': str(item.format), 'text': item.text} for item in results]


class Worker(QThread):
    result = Signal(object)
    error = Signal(str)
    def __init__(self, image, parent): super().__init__(parent); self.image=image
    def run(self):
        try: self.result.emit(scan_codes(self.image))
        except Exception as error: self.error.emit(str(error))


class BarcodeDialog(QDialog):
    def __init__(self, parent, image):
        super().__init__(parent); self.image=image; self.worker=None; self.results=[]; self.closing=False
        self.setWindowTitle('二维码 / 条形码识别'); self.resize(680,450)
        box=QVBoxLayout(self); note=QLabel('识别当前显示的图片，所有内容只在本机处理；链接仅显示，不会自动打开。'); note.setWordWrap(True); box.addWidget(note)
        self.status=QLabel('准备识别…'); box.addWidget(self.status)
        self.items=QListWidget(); box.addWidget(self.items)
        self.preview=QTextEdit(); self.preview.setReadOnly(True); box.addWidget(self.preview)
        self.copy=QPushButton('复制选中内容'); self.copy.setEnabled(False); box.addWidget(self.copy)
        self.items.currentRowChanged.connect(self.select); self.copy.clicked.connect(self.copy_selected)
        QTimer.singleShot(0,self.start)
    def start(self):
        if self.closing: return
        self.status.setText('正在识别…'); self.worker=Worker(self.image,self)
        self.worker.result.connect(self.show_result); self.worker.error.connect(lambda message:self.status.setText('识别失败：'+message)); self.worker.start()
    def show_result(self, results):
        if self.closing: return
        self.results=results; self.status.setText(f'识别到 {len(results)} 个码' if results else '未识别到二维码或条形码；可尝试调整图片或通道。')
        for item in results: self.items.addItem(item['format'] + ' · ' + item['text'][:100])
        if results: self.items.setCurrentRow(0)
    def select(self, row):
        valid=0 <= row < len(self.results); self.copy.setEnabled(valid); self.preview.setPlainText(self.results[row]['text'] if valid else '')
    def copy_selected(self):
        row=self.items.currentRow()
        if 0 <= row < len(self.results): QApplication.clipboard().setText(self.results[row]['text'])
    def stop(self):
        self.closing=True
        if self.worker and self.worker.isRunning(): self.worker.wait()
    def reject(self): self.stop(); super().reject()
    def closeEvent(self,event): self.stop(); super().closeEvent(event)
