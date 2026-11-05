"""原文件隐藏内容检查：只定位和保存，不解压或运行。"""
from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
                               QTextEdit, QPushButton, QFileDialog, QMessageBox)
from file_inspection import inspect_file, save_candidate


class ScanWorker(QThread):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(object, object)

    def __init__(self, reference, parent=None):
        super().__init__(parent)
        self.reference = reference

    def run(self):
        try:
            result = inspect_file(self.reference, progress=self.progress.emit,
                                  cancel=self.isInterruptionRequested)
            self.result.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


class FileInspectionDialog(QDialog):
    def __init__(self, parent, reference):
        super().__init__(parent)
        self.reference = reference
        self.result = None
        self.worker = None
        self.setWindowTitle('检查原文件中的隐藏内容')
        self.resize(780, 530)
        layout = QVBoxLayout(self)
        hint = QLabel('扫描原始文件中的常见文件头，并检查图片末尾是否有附加数据。')
        hint.setWordWrap(True); layout.addWidget(hint)
        self.status = QLabel('准备检查…'); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.items = QListWidget(); layout.addWidget(self.items, 1)
        self.detail = QTextEdit(); self.detail.setReadOnly(True); self.detail.setMaximumHeight(155); layout.addWidget(self.detail)
        note = QLabel('文件头只是线索，可能误报；未发现也不代表没有隐藏文件。保存候选时会包含该位置之后的全部字节。')
        note.setWordWrap(True); layout.addWidget(note)
        row = QHBoxLayout(); layout.addLayout(row)
        self.save_button = QPushButton('保存选中内容…'); self.save_button.setEnabled(False); row.addWidget(self.save_button)
        self.tail_button = QPushButton('保存图片尾部附加数据…'); self.tail_button.setEnabled(False); row.addWidget(self.tail_button)
        self.items.currentRowChanged.connect(self.show_item)
        self.save_button.clicked.connect(self.save_selected)
        self.tail_button.clicked.connect(self.save_tail)
        QTimer.singleShot(0, self.start_scan)

    def start_scan(self):
        if not self.reference:
            self.status.setText('这张图片没有可检查的原始文件；请先保存并重新导入。'); return
        self.status.setText('正在检查原始文件…')
        self.worker = ScanWorker(self.reference, self)
        self.worker.result.connect(self.show_result)
        self.worker.error.connect(lambda message: self.status.setText('检查失败：' + message))
        self.worker.progress.connect(lambda done, total: self.status.setText(f'正在检查：{done:,} / {total:,} 字节'))
        self.worker.start()

    def show_result(self, result):
        self.result = result
        end = result['image_end']
        tail = result['size'] - end if end is not None else None
        boundary = f'图片末尾附加 {tail:,} 字节' if tail is not None else '无法确定图片结构的结束位置'
        suffix = '；扫描未覆盖全部内容或候选数量已达上限' if result['incomplete'] else ''
        self.status.setText(f"检查完成：发现 {len(result['candidates'])} 条候选；{boundary}{suffix}")
        positions = {'trailing': '图片尾部', 'inside': '图片内部', 'unknown': '位置未确定'}
        for item in result['candidates']:
            confidence = '已验证 ZIP 结构' if item['verified'] else '疑似文件头'
            self.items.addItem(f"{item['kind']} · {positions[item['location']]} · 偏移 {item['offset']:,} (0x{item['offset']:X}) · {confidence}")
        self.tail_button.setEnabled(tail is not None and tail > 0)
        if result['candidates']: self.items.setCurrentRow(0)

    def show_item(self, index):
        self.save_button.setEnabled(self.result is not None and 0 <= index < len(self.result['candidates']))
        if not self.save_button.isEnabled(): self.detail.clear(); return
        item = self.result['candidates'][index]
        lines = [f"从偏移 {item['offset']:,} 开始保存至文件末尾。"]
        if item['verified']:
            lines.append('ZIP 文件结构可读取；以下仅为目录信息，未解压。')
            lines.append('检测到加密标记。' if item['encrypted'] else 'ZIP 条目未检测到加密标记。')
            lines.extend(item['members'])
        else:
            lines.append('仅根据文件头识别，内容可能不是有效文件。')
        self.detail.setPlainText('\n'.join(lines))

    def save_at(self, offset, name):
        path, _ = QFileDialog.getSaveFileName(self, '保存原文件中的数据', name, '所有文件 (*)')
        if not path: return
        try: save_candidate(self.reference, offset, path)
        except Exception as exc: QMessageBox.warning(self, '保存失败', str(exc)); return
        QMessageBox.information(self, '保存完成', '已保存选定位置到原文件末尾的数据。')

    def save_selected(self):
        index = self.items.currentRow()
        if self.result and 0 <= index < len(self.result['candidates']):
            item = self.result['candidates'][index]
            self.save_at(item['offset'], '提取文件.' + item['extension'])

    def save_tail(self):
        if self.result and self.result['image_end'] is not None:
            self.save_at(self.result['image_end'], '图片附加数据.bin')

    def stop_worker(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption(); self.worker.wait()

    def reject(self):
        self.stop_worker(); super().reject()

    def closeEvent(self, event):
        self.stop_worker(); super().closeEvent(event)
