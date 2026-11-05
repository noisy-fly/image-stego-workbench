"""Small, bounded original-file hex editor and safe export."""
import os
import tempfile
from pathlib import Path
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableView,
                               QPushButton, QFileDialog, QMessageBox, QAbstractItemView, QHeaderView)
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
        self.font = QFont('Consolas', 10)

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
        if role in (Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ToolTipRole):
            found = self.mark(pos)
            if found: return found[1] if role == Qt.ItemDataRole.BackgroundRole else found[0]
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
        self.table = QTableView(); self.table.setObjectName('hexTable')
        self.model = HexModel(read_source(reference), self); self.table.setModel(self.model)
        self.table.verticalHeader().setVisible(False); self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        header = self.table.horizontalHeader(); header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 90)
        for i in range(1, 17): self.table.setColumnWidth(i, 35)
        for i in range(17, 33): self.table.setColumnWidth(i, 25)
        box.addWidget(self.table)
        row = QHBoxLayout(); box.addLayout(row)
        self.status = QLabel(f'共 {len(self.model.bytes):,} 字节；仅覆盖现有字节，不支持增删。')
        row.addWidget(self.status, 1)
        self.save_button = QPushButton('另存并添加到画布'); self.save_button.clicked.connect(self.save); row.addWidget(self.save_button)

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
        QMessageBox.information(self, '已添加到画布', '修改已另存为新文件，并添加到画布。原文件未修改。')
        self.accept()

    def reject(self):
        if self.model.changed and QMessageBox.question(self, '放弃修改', '还有未保存的修改，确定关闭吗？') != QMessageBox.StandardButton.Yes: return
        super().reject()

    def closeEvent(self, event):
        if self.model.changed and QMessageBox.question(self, '放弃修改', '还有未保存的修改，确定关闭吗？') != QMessageBox.StandardButton.Yes:
            event.ignore(); return
        super().closeEvent(event)
