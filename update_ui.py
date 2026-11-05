"""更新检查的后台执行和中文界面。"""
import shutil
import sys
import tempfile
import threading

from PySide6.QtCore import QObject, Signal, QSettings, QProcess, Qt
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from app_version import APP_VERSION
from updater import fetch_latest, should_prompt, download_installer


class UpdateSignals(QObject):
    checked = Signal(object, str)
    downloaded = Signal(str, str)
    progress = Signal(int, int)


class UpdateController(QObject):
    def __init__(self, owner, settings=None):
        super().__init__(owner); self.owner = owner
        self.settings = settings if settings is not None else QSettings('StegoWorkbench', '图片隐写工作台')
        self.signals = UpdateSignals(self); self.signals.checked.connect(self.checked)
        self.signals.downloaded.connect(self.downloaded); self.signals.progress.connect(self.progress_changed)
        self.checking = False; self.manual_pending = False; self.downloading = False
        self.cancel_event = threading.Event(); self.download_dir = None; self.progress_dialog = None

    def check(self, manual=False):
        if self.checking:
            self.manual_pending = self.manual_pending or manual
            if manual: self.owner.statusBar().showMessage('正在检查更新，请稍候…')
            return
        if self.downloading:
            if manual: self.owner.statusBar().showMessage('正在下载更新。')
            return
        self.checking = True; self.manual_pending = manual
        if manual: self.owner.statusBar().showMessage('正在检查更新…')
        def work():
            try: info, error = fetch_latest(), ''
            except Exception as exc: info, error = None, str(exc)
            try: self.signals.checked.emit(info, error)
            except RuntimeError: pass
        threading.Thread(target=work, daemon=True).start()

    def checked(self, info, error):
        manual = self.manual_pending; self.checking = False; self.manual_pending = False
        if error:
            if manual: QMessageBox.warning(self.owner, '检查更新失败', '无法获取更新信息，请检查网络后重试。\n\n' + error)
            return
        ignored = str(self.settings.value('ignored_release', '') or '')
        try: available = should_prompt(info, APP_VERSION, ignored, manual)
        except ValueError as exc:
            if manual: QMessageBox.warning(self.owner, '检查更新失败', str(exc))
            return
        if not available:
            if manual: QMessageBox.information(self.owner, '检查更新', f'当前已是最新正式版。\n当前版本：{APP_VERSION}')
            return
        self.offer(info)

    def offer(self, info):
        box = QMessageBox(self.owner); box.setWindowTitle('发现新版本'); box.setIcon(QMessageBox.Icon.Information)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(f"发现新版本 {info['tag']}（当前 {APP_VERSION}）。\n\n更新时会下载并校验安装包，然后关闭程序并打开安装向导。画布中未保存的内容将丢失。")
        update = box.addButton('立即更新', QMessageBox.ButtonRole.AcceptRole)
        ignore = box.addButton('忽略此版本', QMessageBox.ButtonRole.DestructiveRole)
        later = box.addButton('以后再说', QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(update); box.setEscapeButton(later); box.exec()
        if box.clickedButton() is ignore:
            self.settings.setValue('ignored_release', info['tag']); self.settings.sync()
            self.owner.statusBar().showMessage(f"已忽略 {info['tag']}，仍可在设置中手动检查。")
        elif box.clickedButton() is update:
            self.start_download(info)

    def start_download(self, info):
        if sys.platform != 'win32':
            QMessageBox.information(self.owner, '无法安装', '当前仅提供 Windows 安装包。'); return
        self.downloading = True; self.cancel_event.clear()
        try: self.download_dir = tempfile.mkdtemp(prefix='stegoworkbench-update-')
        except OSError as exc:
            self.downloading = False; QMessageBox.warning(self.owner, '无法下载更新', str(exc)); return
        self.progress_dialog = QProgressDialog('正在下载并校验安装包…', '取消', 0, 100, self.owner)
        self.progress_dialog.setWindowTitle('更新程序'); self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setMinimumDuration(0); self.progress_dialog.canceled.connect(self.cancel_event.set); self.progress_dialog.show()
        directory = self.download_dir
        def work():
            try:
                path = download_installer(info, directory, progress=self.signals.progress.emit, cancel=self.cancel_event.is_set)
                if self.cancel_event.is_set(): raise InterruptedError('已取消下载。')
                error = ''
            except Exception as exc: path, error = '', str(exc)
            try: self.signals.downloaded.emit(path, error)
            except RuntimeError:
                if not path: shutil.rmtree(directory, ignore_errors=True)
        threading.Thread(target=work, daemon=True).start()

    def progress_changed(self, current, total):
        if self.progress_dialog: self.progress_dialog.setValue(min(99, current * 100 // total))

    def downloaded(self, path, error):
        self.downloading = False
        if self.progress_dialog: self.progress_dialog.close(); self.progress_dialog = None
        if error:
            if self.download_dir: shutil.rmtree(self.download_dir, ignore_errors=True)
            self.download_dir = None
            if self.cancel_event.is_set(): self.owner.statusBar().showMessage('已取消更新下载。')
            else: QMessageBox.warning(self.owner, '更新下载失败', error + '\n请稍后在设置中重试。')
            return
        launched, _ = QProcess.startDetached(path, [])
        if not launched:
            QMessageBox.warning(self.owner, '无法启动安装程序', '下载和校验成功，但无法启动安装向导。\n文件位置：' + path)
            return
        self.owner.close()
