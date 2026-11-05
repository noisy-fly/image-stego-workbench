from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtWidgets import (QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QTextEdit, QPushButton, QFileDialog, QMessageBox)
from jsteg_extract import reveal_jsteg, save_payload


class JstegWorker(QThread):
    result = Signal(object)
    error = Signal(str)
    def __init__(self, reference, parent=None):
        super().__init__(parent); self.reference = reference
    def run(self):
        try: self.result.emit(reveal_jsteg(self.reference, cancel=self.isInterruptionRequested))
        except Exception as exc: self.error.emit(str(exc))


class JstegDialog(QDialog):
    def __init__(self, parent, reference):
        super().__init__(parent); self.reference = reference; self.worker = None; self.payload = None; self.closing = False
        self.setWindowTitle('JSteg 提取'); self.resize(740, 510)
        box = QVBoxLayout(self)
        hint = QLabel('从 JPEG 原始文件的压缩系数中提取 JSteg v0.3.0 格式数据。不会修改原图。')
        hint.setWordWrap(True); box.addWidget(hint)
        self.status = QLabel('准备提取…'); self.status.setWordWrap(True); box.addWidget(self.status)
        self.preview = QTextEdit(); self.preview.setObjectName('jstegPreview'); self.preview.setReadOnly(True); box.addWidget(self.preview, 1)
        note = QLabel('仅展示前 4096 字节；无结果不代表图片没有其他隐写，部分 JPEG 格式不受支持。')
        note.setWordWrap(True); box.addWidget(note)
        row = QHBoxLayout(); box.addLayout(row)
        self.copy_button = QPushButton('复制文本预览'); self.copy_button.setEnabled(False); row.addWidget(self.copy_button)
        self.save_button = QPushButton('保存完整数据…'); self.save_button.setEnabled(False); row.addWidget(self.save_button)
        self.copy_button.clicked.connect(self.copy_text); self.save_button.clicked.connect(self.save)
        QTimer.singleShot(0, self.start)

    def start(self):
        if self.closing: return
        if not self.reference:
            self.status.setText('这张图片没有原始文件，请先保存并重新导入。'); return
        self.status.setText('正在从 JPEG 压缩数据提取…')
        self.worker = JstegWorker(self.reference, self)
        self.worker.result.connect(self.show_result); self.worker.error.connect(self.show_error); self.worker.start()

    def show_error(self, message):
        if not self.closing: self.status.setText('未能提取：' + message)

    def show_result(self, data):
        if self.closing: return
        self.payload = data; self.status.setText(f'提取完成：{len(data):,} 字节；请检查内容是否符合题意。')
        sample = data[:4096]; text = sample.decode('utf-8', errors='replace')
        self.preview.setPlainText('文本预览（UTF-8）：\n' + text + '\n\n十六进制预览：\n' + sample.hex(' ').upper())
        self.copy_button.setEnabled(bool(sample)); self.save_button.setEnabled(True)

    def copy_text(self):
        if self.payload is not None:
            QApplication.clipboard().setText(self.payload[:4096].decode('utf-8', errors='replace'))
            self.status.setText('已复制前 4096 字节的文本预览。')

    def save(self):
        if self.payload is None: return
        path, _ = QFileDialog.getSaveFileName(self, '保存 JSteg 提取的数据', 'jsteg提取结果.bin', '所有文件 (*)')
        if not path: return
        try: save_payload(self.reference, self.payload, path)
        except Exception as error: QMessageBox.warning(self, '保存失败', str(error)); return
        QMessageBox.information(self, '保存完成', '已保存完整提取数据。')

    def stop_worker(self):
        self.closing = True
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption(); self.worker.wait()

    def reject(self): self.stop_worker(); super().reject()
    def closeEvent(self, event): self.stop_worker(); super().closeEvent(event)
