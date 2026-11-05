"""Small, bounded original-file hex editor and safe export."""
import io
import os
import zipfile
import tempfile
from pathlib import Path
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QThread, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableView,
                               QPushButton, QFileDialog, QMessageBox, QAbstractItemView, QHeaderView,
                               QListWidget, QSplitter, QWidget)
from file_inspection import SIGNATURES, check_source, source_reference
from core import load_image

MAX_BYTES = 16 * 1024 * 1024
MARKS = [(signature, kind + ' 文件头', QColor('#d8f2e4')) for kind, signature, _ in SIGNATURES]
MARKS += [(b'BM', 'BMP 文件头（候选）', QColor('#d8f2e4')),
          (b'BPG\xfb', 'BPG 文件头', QColor('#d8f2e4')),
          (b'II*\x00', 'TIFF 文件头（小端）', QColor('#d8f2e4')),
          (b'MM\x00*', 'TIFF 文件头（大端）', QColor('#d8f2e4')),
          (b'\x00\x00\x00\x00IEND\xaeB`\x82', 'PNG IEND 结束块', QColor('#ffe6c7')),
          (b'\xff\xd9', 'JPEG 结束标记（候选）', QColor('#ffe6c7')),
          (b'PK\x05\x06', 'ZIP 中央目录结束记录（候选）', QColor('#ffe6c7'))]


ZIP_HEADER = b'PK\x03\x04'
SUSPECT_COLOR = QColor('#ffe0e0')
MAX_MARKS = 512


def find_marks(data):
    """Return bounded signature candidates; these are not proof of valid files."""
    found = []; seen = set(); truncated = False
    def add(offset, actual, expected, label, color):
        nonlocal truncated
        key = (offset, label)
        if key in seen: return
        seen.add(key)
        if len(found) >= MAX_MARKS * 2:
            truncated = True; return
        found.append(dict(offset=offset, actual=bytes(actual), expected=bytes(expected), label=label, color=color))
    for signature, label, color in MARKS:
        start = 0
        while not truncated:
            offset = data.find(signature, start)
            if offset < 0: break
            add(offset, signature, signature, label, color); start = offset + 1
    # A one-byte difference is only a heuristic, never proof of file type.
    for signature, label, _ in MARKS:
        if truncated: break
        if '文件头' not in label or len(signature) < 4: continue
        for index in range(len(signature)):
            prefix, suffix = signature[:index], signature[index + 1:]
            seed, shift = (prefix, 0) if len(prefix) >= len(suffix) else (suffix, index + 1)
            start = 0
            while not truncated:
                position = data.find(seed, start)
                if position < 0: break
                offset = position - shift; start = position + 1
                if offset < 0 or offset + len(signature) > len(data): continue
                sample = data[offset:offset + len(signature)]
                if sample[index] != signature[index] and sample[:index] == prefix and sample[index + 1:] == suffix:
                    add(offset, sample, signature, '疑似 ' + label + '（单字节不同）', SUSPECT_COLOR)
    if not truncated:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for entry in archive.infolist():
                    offset = entry.header_offset
                    if 0 <= offset <= len(data) - 4 and data[offset:offset + 4] != ZIP_HEADER:
                        add(offset, data[offset:offset + 4], ZIP_HEADER, '疑似 ZIP 受损文件头（中央目录线索）', SUSPECT_COLOR)
                    if truncated: break
        except (zipfile.BadZipFile, OSError, ValueError, OverflowError): pass
    if data[:6] in (b'GIF87a', b'GIF89a') and data[-1:] == b'\x3b':
        add(len(data)-1, b'\x3b', b'\x3b', 'GIF 文件末尾标记（候选）', QColor('#ffe6c7'))
    found.sort(key=lambda item: (item['offset'], item['label']))
    if len(found) > MAX_MARKS: truncated = True
    return {'marks': found[:MAX_MARKS], 'truncated': truncated}


class MarkWorker(QThread):
    ready = Signal(object)
    def __init__(self, data, parent=None):
        super().__init__(parent); self.data = data
    def run(self):
        try: self.ready.emit(find_marks(self.data))
        except Exception as error: self.ready.emit({'marks': [], 'truncated': False, 'error': str(error)})


def read_source(reference):
    if not reference: raise ValueError('这张图片没有原始文件，请先保存并重新导入。')
    with open(reference[0], 'rb') as source:
        check_source(source, reference)
        if reference[1] > MAX_BYTES: raise ValueError('文件超过十六进制编辑上限（16 MiB）。')
        data = source.read(MAX_BYTES + 1)
        check_source(source, reference)
    return data


def save_edited(reference, data, destination):
    if not reference: raise ValueError('没有原始文件。')
    source = Path(reference[0]).resolve(); target = Path(destination).resolve()
    def check_target():
        if target == source or (target.exists() and os.path.samefile(source, target)):
            raise ValueError('不能覆盖原始图片，请选择其他文件名。')
    check_target()
    with open(source, 'rb') as original: check_source(original, reference)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=target.suffix, prefix='.stego-hex-', delete=False) as output:
            temporary = Path(output.name); output.write(data)
        try: image = load_image(temporary)
        except Exception as error: raise ValueError('修改后的文件无法解码为图片，请检查后再添加到画布。') from error
        with open(source, 'rb') as original: check_source(original, reference)
        check_target(); os.replace(temporary, target); temporary = None
        return image, source_reference(target)
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)


class HexModel(QAbstractTableModel):
    def __init__(self, data, parent=None):
        super().__init__(parent); self.bytes = bytearray(data); self.changed = False
        self.font = QFont('Consolas', 10); self.extra_marks = []

    def rowCount(self, parent=QModelIndex()): return (len(self.bytes) + 15) // 16 if not parent.isValid() else 0
    def columnCount(self, parent=QModelIndex()): return 33 if not parent.isValid() else 0
    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal: return None
        if section == 0: return '偏移'
        return f'{(section - 1) % 16:X}' if section < 17 else f'{section - 17:X}'

    def flags(self, index):
        flags = super().flags(index)
        if index.isValid() and 0 < index.column() < 33 and self.offset(index) < len(self.bytes):
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def offset(self, index):
        col = index.column()
        return index.row() * 16 + ((col - 1) if col <= 16 else (col - 17))

    def mark(self, offset):
        for item in self.extra_marks:
            if item['offset'] <= offset < item['offset'] + len(item['actual']):
                return item['label'], item['color']
        for start in range(max(0, offset - 3), offset + 1):
            sample = self.bytes[start:start + 4]
            if len(sample) == 4 and sample[:3] == b'PK\x03' and sample != ZIP_HEADER:
                return '疑似 ZIP 受损文件头（字节相近）', SUSPECT_COLOR
        for sig, label, color in MARKS:
            for start in range(max(0, offset - len(sig) + 1), offset + 1):
                if self.bytes[start:start + len(sig)] == sig: return label, color
        if self.bytes[:6] in (b'GIF87a', b'GIF89a') and offset == len(self.bytes) - 1 and self.bytes[offset] == 0x3b:
            return 'GIF 文件末尾标记（候选）', QColor('#ffe6c7')
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid(): return None
        col = index.column()
        if role == Qt.ItemDataRole.FontRole: return self.font
        if col == 0:
            return f'{index.row() * 16:08X}' if role == Qt.ItemDataRole.DisplayRole else None
        pos = self.offset(index)
        if pos >= len(self.bytes): return None
        value = self.bytes[pos]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return f'{value:02X}' if col <= 16 else (chr(value) if 32 <= value <= 126 else ('' if role == Qt.ItemDataRole.EditRole else '.'))
        if role == Qt.ItemDataRole.TextAlignmentRole: return int(Qt.AlignmentFlag.AlignCenter)
        if role in (Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ToolTipRole, Qt.ItemDataRole.ForegroundRole):
            found = self.mark(pos)
            if found:
                if role == Qt.ItemDataRole.ForegroundRole: return QColor('#202020')
                return found[1] if role == Qt.ItemDataRole.BackgroundRole else found[0]
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not index.isValid() or index.column() == 0: return False
        pos = self.offset(index)
        if pos >= len(self.bytes): return False
        text = str(value)
        if index.column() <= 16:
            if len(text) != 2 or any(c not in '0123456789abcdefABCDEF' for c in text): return False
            number = int(text, 16)
        else:
            if len(text) != 1 or not 32 <= ord(text) <= 126: return False
            number = ord(text)
        if self.bytes[pos] != number:
            self.bytes[pos] = number; self.changed = True
            reach = max(len(sig) for sig, _, _ in MARKS) - 1
            first = max(0, (pos - reach) // 16); last = min(self.rowCount() - 1, (pos + reach) // 16)
            self.dataChanged.emit(self.index(first, 1), self.index(last, 32))
        return True


class HexEditorDialog(QDialog):
    def __init__(self, parent, reference, on_add):
        super().__init__(parent); self.reference = reference; self.on_add = on_add
        self.setWindowTitle('十六进制编辑'); self.resize(1320, 610)
        box = QVBoxLayout(self)
        hint = QLabel('双击字节编辑：左侧十六进制（两位），右侧 ASCII（可打印字符）；绿色为常见文件头，橙色为文件尾或结束标记候选。')
        hint.setWordWrap(True); box.addWidget(hint)
        content = QSplitter(Qt.Orientation.Horizontal); box.addWidget(content, 1)
        self.table = QTableView(); self.table.setObjectName('hexTable')
        self.model = HexModel(read_source(reference), self); self.table.setModel(self.model)
        self.table.verticalHeader().setVisible(False); self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        header = self.table.horizontalHeader(); header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header.setMinimumSectionSize(1)
        self.table.setColumnWidth(0, 90)
        for i in range(1, 17): self.table.setColumnWidth(i, 35)
        ascii_width = max(11, QFontMetrics(self.model.font).horizontalAdvance('M') + 3)
        for i in range(17, 33): self.table.setColumnWidth(i, ascii_width)
        content.addWidget(self.table)
        side = QWidget(); sidebox = QVBoxLayout(side); sidebox.setContentsMargins(4, 0, 0, 0)
        sidebox.addWidget(QLabel('文件头 / 尾线索（点击跳转）'))
        self.mark_status = QLabel('正在查找…'); self.mark_status.setWordWrap(True); sidebox.addWidget(self.mark_status)
        self.mark_list = QListWidget(); self.mark_list.setObjectName('hexMarkList'); sidebox.addWidget(self.mark_list, 1)
        self.mark_detail = QLabel('选择线索查看字节。'); self.mark_detail.setWordWrap(True)
        self.mark_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); sidebox.addWidget(self.mark_detail)
        content.addWidget(side); content.setStretchFactor(0, 4); content.setStretchFactor(1, 2); content.setSizes([950, 370])
        self.marks = []; self.mark_worker = None; self.mark_revision = 0; self.scan_revision = 0; self.closing = False
        self.refresh_timer = QTimer(self); self.refresh_timer.setSingleShot(True); self.refresh_timer.setInterval(250)
        self.refresh_timer.timeout.connect(self.start_mark_scan)
        self.model.dataChanged.connect(self.bytes_changed)
        self.mark_list.currentRowChanged.connect(self.select_mark)
        QTimer.singleShot(0, self.start_mark_scan)
        row = QHBoxLayout(); box.addLayout(row)
        self.status = QLabel(f'共 {len(self.model.bytes):,} 字节；仅覆盖现有字节，不支持增删。')
        row.addWidget(self.status, 1)
        self.save_button = QPushButton('另存并添加到画布'); self.save_button.clicked.connect(self.save); row.addWidget(self.save_button)

    def bytes_changed(self, *args):
        self.mark_revision += 1
        self.model.extra_marks = []; self.marks = []; self.mark_list.clear(); self.mark_detail.setText('线索正在更新…')
        self.table.viewport().update()
        self.mark_status.setText('字节已修改，正在更新线索…')
        self.refresh_timer.start()

    def start_mark_scan(self):
        if self.closing: return
        if self.mark_worker and self.mark_worker.isRunning(): return
        self.scan_revision = self.mark_revision
        self.mark_worker = MarkWorker(bytes(self.model.bytes), self)
        self.mark_worker.ready.connect(self.show_marks)
        self.mark_worker.finished.connect(self.mark_scan_finished)
        self.mark_worker.start()

    def mark_scan_finished(self):
        if self.scan_revision != self.mark_revision: self.refresh_timer.start()

    def show_marks(self, result):
        if self.scan_revision != self.mark_revision: return
        if result.get('error'):
            self.mark_status.setText('线索搜索失败：' + result['error']); return
        self.marks = result['marks']; self.mark_list.clear()
        self.model.extra_marks = [m for m in self.marks if '疑似' in m['label']]
        self.table.viewport().update()
        for item in self.marks:
            self.mark_list.addItem(f"0x{item['offset']:X} · {item['label']}")
        suffix = '；达到 512 条上限' if result['truncated'] else ''
        self.mark_status.setText(f"发现 {len(self.marks)} 条线索{suffix}；疑似结果可能误报。")
        self.mark_detail.setText('选择线索查看字节。')

    def select_mark(self, row):
        if not 0 <= row < len(self.marks): return
        item = self.marks[row]; offset = item['offset']
        actual = item['actual'].hex(' ').upper(); expected = item['expected'].hex(' ').upper()
        text = f"{item['label']}\n偏移：0x{offset:X}（{offset}）\n实际字节：{actual}"
        if item['actual'] != item['expected']: text += f"\n标准文件头：{expected}\n仅为候选，请结合文件结构确认。"
        self.mark_detail.setText(text)
        index = self.model.index(offset // 16, offset % 16 + 1)
        self.table.setCurrentIndex(index); self.table.scrollTo(index)

    def stop_worker(self):
        self.closing = True
        self.refresh_timer.stop()
        if self.mark_worker and self.mark_worker.isRunning(): self.mark_worker.wait()

    def save(self):
        original = Path(self.reference[0]); suggested = str(original.with_name(original.stem + '_编辑' + original.suffix))
        path, _ = QFileDialog.getSaveFileName(self, '保存编辑后的图片', suggested, '所有文件 (*)')
        if not path: return
        try:
            image, ref = save_edited(self.reference, self.model.bytes, path)
            self.on_add(image, Path(path).name, ref)
        except Exception as error:
            QMessageBox.warning(self, '无法添加图片', str(error)); return
        self.model.changed = False
        self.stop_worker()
        QMessageBox.information(self, '已添加到画布', '修改已另存为新文件，并添加到画布。原文件未修改。')
        self.accept()

    def reject(self):
        if self.model.changed and QMessageBox.question(self, '放弃修改', '还有未保存的修改，确定关闭吗？') != QMessageBox.StandardButton.Yes: return
        self.stop_worker(); super().reject()

    def closeEvent(self, event):
        if self.model.changed and QMessageBox.question(self, '放弃修改', '还有未保存的修改，确定关闭吗？') != QMessageBox.StandardButton.Yes:
            event.ignore(); return
        self.stop_worker(); super().closeEvent(event)
