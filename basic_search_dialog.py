from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QListWidget, QPushButton
from basic_search import search_basic


class SearchWorker(QThread):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(object, object)

    def __init__(self, reference, parent=None):
        super().__init__(parent); self.reference = reference

    def run(self):
        try:
            self.result.emit(search_basic(self.reference, progress=self.progress.emit, cancel=self.isInterruptionRequested))
        except Exception as exc:
            self.error.emit(str(exc))


class BasicSearchDialog(QDialog):
    def __init__(self, parent, reference):
        super().__init__(parent); self.reference = reference; self.worker = None; self.results = []
        self.setWindowTitle('基本信息快速搜索'); self.resize(760, 420)
        box = QVBoxLayout(self)
        hint = QLabel('搜索原文件中的普通文本、UTF-16 文本和可读取的图片文本属性，查找名称{内容}格式。')
        hint.setWordWrap(True); box.addWidget(hint)
        self.status = QLabel('准备搜索…'); self.status.setWordWrap(True); box.addWidget(self.status)
        self.items = QListWidget(); self.items.setObjectName('basicSearchResults'); box.addWidget(self.items)
        note = QLabel('结果只是候选；最多显示 256 条。未发现不代表没有隐写，像素位数据请使用 LSB 检查。')
        note.setWordWrap(True); box.addWidget(note)
        self.copy_button = QPushButton('复制选中内容'); self.copy_button.setEnabled(False); box.addWidget(self.copy_button)
        self.copy_button.clicked.connect(self.copy_selected)
        self.items.currentRowChanged.connect(lambda row: self.copy_button.setEnabled(0 <= row < len(self.results)))
        QTimer.singleShot(0, self.start_search)

    def start_search(self):
        if not self.reference:
            self.status.setText('这张图片没有原始文件，请先保存并重新导入。'); return
        self.worker = SearchWorker(self.reference, self)
        self.worker.result.connect(self.show_result)
        self.worker.error.connect(lambda message: self.status.setText('搜索失败：' + message))
        self.worker.progress.connect(lambda done, total: self.status.setText(f'正在搜索：{done:,} / {total:,} 字节'))
        self.worker.start()

    def show_result(self, result):
        self.results = result['matches']
        suffix = '；候选达到上限，结果可能不完整' if result['truncated'] else ''
        self.status.setText(f"搜索完成：发现 {len(self.results)} 条候选{suffix}" if self.results else '搜索完成：未发现符合格式的文本')
        for item in self.results:
            position = f"偏移 {item['offset']:,} (0x{item['offset']:X})" if item['offset'] is not None else '解码后的属性'
            self.items.addItem(f"{item['text']}  ·  {item['source']}  ·  {position}  ·  {item['encoding']}")
        if self.results: self.items.setCurrentRow(0)

    def copy_selected(self):
        row = self.items.currentRow()
        if 0 <= row < len(self.results):
            QApplication.clipboard().setText(self.results[row]['text'])
            self.status.setText('已复制选中的候选文本。')

    def stop_worker(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption(); self.worker.wait()

    def reject(self):
        self.stop_worker(); super().reject()

    def closeEvent(self, event):
        self.stop_worker(); super().closeEvent(event)
