"""Expose analysis variants as PNG files for desktop drag and internal canvas drops."""
import re
import tempfile
import uuid
from pathlib import Path
from PIL import Image
from PySide6.QtCore import QMimeData, QUrl, Qt
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QApplication, QListWidget, QAbstractItemView, QMessageBox

VARIANT_MIME = 'application/x-stego-variant'


def variant_mime(name, array):
    app = QApplication.instance()
    if not hasattr(app, '_variant_drag_directory'):
        app._variant_drag_directory = tempfile.TemporaryDirectory(prefix='stego-drag-')
    clean = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', name).strip(' .')[:60] or '图片'
    path = Path(app._variant_drag_directory.name) / (clean + '_' + uuid.uuid4().hex[:8] + '.png')
    Image.fromarray(array).save(path, format='PNG')
    mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(str(path))]); mime.setData(VARIANT_MIME, name.encode('utf-8'))
    return mime


class VariantList(QListWidget):
    def __init__(self, analysis):
        super().__init__(); self.analysis=analysis
        self.setDragEnabled(True); self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
    def startDrag(self, supported_actions):
        row=self.currentRow()
        if not 0 <= row < len(self.analysis.variants): return
        name, array=self.analysis.variants[row]
        try: mime = variant_mime(name,array)
        except Exception as error:
            QMessageBox.warning(self, '无法拖出图片', str(error)); return
        drag=QDrag(self); drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)
