"""轻量图片提取对话框。"""
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QSpinBox, QVBoxLayout)

from extract_sources import inspect_source, extract_groups


def format_time(seconds):
    if seconds is None: return '未知'
    total_ms = round(seconds * 1000); hours, rest = divmod(total_ms, 3600000)
    minutes, rest = divmod(rest, 60000); whole, ms = divmod(rest, 1000)
    return f'{hours:02}:{minutes:02}:{whole:02}.{ms:03}'


class ExtractWorker(QThread):
    progress = Signal(int, int)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, options, parent=None):
        super().__init__(parent); self.options = options

    def run(self):
        try:
            result = extract_groups(**self.options, progress=self.progress.emit, cancel=self.isInterruptionRequested)
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class ExtractDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner); self.owner = owner; self.worker = None; self.result = None
        self.setWindowTitle('提取并分组图片'); self.resize(700, 470)
        layout = QVBoxLayout(self)
        intro = QLabel('支持视频、GIF、ZIP/TAR，以及字幕内的十六进制 / Base64 图片。请自行设置起点和每组数量。')
        intro.setWordWrap(True); layout.addWidget(intro)
        form = QFormLayout(); layout.addLayout(form)
        self.source = QLineEdit(); self.source.setReadOnly(True)
        source_row = QHBoxLayout(); source_row.addWidget(self.source)
        self.browse_source = QPushButton('选择文件…'); self.browse_source.clicked.connect(self.choose_source); source_row.addWidget(self.browse_source)
        form.addRow('来源文件', source_row)
        self.tracks = QComboBox(); self.tracks.currentIndexChanged.connect(self.update_track); form.addRow('提取来源', self.tracks)
        self.track_info = QLabel('请选择视频轨。'); self.track_info.setWordWrap(True); form.addRow('轨道时间', self.track_info)
        self.mode = QComboBox(); self.mode.addItem('从指定时间 / 位置开始', None)
        self.mode.addItem('最后 N 张视频帧（精确计数）', 'frames'); self.mode.addItem('最后 N 秒视频帧', 'seconds')
        self.mode.currentIndexChanged.connect(self.update_track); form.addRow('提取方式', self.mode)
        self.start_time = QDoubleSpinBox(); self.start_time.setRange(0, 100000000); self.start_time.setDecimals(2); self.start_time.setSuffix(' 秒')
        self.start_time.setToolTip('只对视频轨生效；从该时间开始解码，不会缩放帧。')
        form.addRow('视频起始时间', self.start_time)
        self.end_seconds = QDoubleSpinBox(); self.end_seconds.setRange(0.01, 100000000); self.end_seconds.setDecimals(2); self.end_seconds.setValue(8); self.end_seconds.setSuffix(' 秒')
        self.end_seconds.setToolTip('以所选轨道实际最后一帧的结束时间为基准；可能需要完整扫描视频。')
        form.addRow('提取末尾秒数', self.end_seconds)
        self.start = QSpinBox(); self.start.setRange(0, 10000000); self.start.setToolTip('跳过起点之后的有效图片；从 0 开始计数。')
        form.addRow('跳过前面图片数', self.start)
        self.count = QSpinBox(); self.count.setRange(1, 2000); self.count.setValue(200); form.addRow('最多提取张数', self.count)
        self.group_size = QSpinBox(); self.group_size.setRange(1, 500); self.group_size.setValue(200); form.addRow('每组图片数量', self.group_size)
        self.destination = QLineEdit(); self.destination.setReadOnly(True)
        output_row = QHBoxLayout(); output_row.addWidget(self.destination)
        self.browse_output = QPushButton('选择文件夹…'); self.browse_output.clicked.connect(self.choose_output); output_row.addWidget(self.browse_output)
        form.addRow('保存到', output_row)
        self.status = QLabel('请选择来源和保存文件夹。'); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.progress_bar = QProgressBar(); self.progress_bar.setRange(0, 100); layout.addWidget(self.progress_bar)
        controls = QHBoxLayout(); self.run_button = QPushButton('开始提取'); self.run_button.clicked.connect(self.start_extraction); controls.addWidget(self.run_button)
        self.cancel_button = QPushButton('停止'); self.cancel_button.setEnabled(False); self.cancel_button.clicked.connect(self.cancel); controls.addWidget(self.cancel_button)
        layout.addLayout(controls)
        group_row = QHBoxLayout(); self.groups = QComboBox(); group_row.addWidget(self.groups, 1)
        self.import_button = QPushButton('导入选中组到画布'); self.import_button.setEnabled(False); self.import_button.clicked.connect(self.import_group); group_row.addWidget(self.import_button)
        layout.addLayout(group_row); self.update_track()

    def choose_source(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择来源文件', '', '常见载体 (*.mkv *.mp4 *.mov *.avi *.webm *.gif *.zip *.tar *.tgz *.gz *.srt *.ass);;所有文件 (*)')
        if path: self.set_source(path)

    def set_source(self, path):
        try: tracks = inspect_source(path)
        except Exception as exc:
            QMessageBox.warning(self, '无法读取来源', str(exc)); return
        self.source.setText(str(path)); self.tracks.clear()
        for item in tracks: self.tracks.addItem(item['label'], item)
        self.status.setText('请选择轨道、提取范围和保存文件夹。'); self.update_track()

    def update_track(self):
        item = self.tracks.currentData()
        video = bool(item and item['kind'] == 'video')
        mode = self.mode.currentData()
        if not video and mode is not None:
            self.mode.setCurrentIndex(0); mode = None
        self.mode.setEnabled(video)
        self.start_time.setEnabled(video and mode is None)
        self.start.setEnabled(mode is None)
        self.end_seconds.setEnabled(video and mode == 'seconds')
        if video:
            duration = item.get('duration'); end = item.get('end_time'); source = item.get('timing_source')
            details = f"时长 {format_time(duration)}，结束时间 {format_time(end)}（{source}，可能为估计）" if duration is not None else '轨道时长未知（未使用容器时长替代）'
            if item.get('container_duration') is not None: details += f"；容器时长 {format_time(item['container_duration'])}"
            self.track_info.setText(details)
        else: self.track_info.setText('该来源不使用视频轨道时间。')

    def choose_output(self):
        path = QFileDialog.getExistingDirectory(self, '选择图片组的保存文件夹')
        if path: self.destination.setText(path)

    def start_extraction(self):
        item = self.tracks.currentData(); parent = self.destination.text()
        if not item or not self.source.text() or not parent or not Path(parent).is_dir():
            QMessageBox.information(self, '还需选择', '请先选择来源文件、提取来源和保存文件夹。'); return
        options = {'path': self.source.text(), 'kind': item['kind'], 'stream_index': item['index'],
                   'output_parent': parent, 'start': self.start.value() if self.mode.currentData() is None else 0, 'count': self.count.value(),
                   'group_size': self.group_size.value(), 'start_time': self.start_time.value() if item['kind'] == 'video' and self.mode.currentData() is None else 0,
                   'end_mode': self.mode.currentData(), 'end_seconds': self.end_seconds.value() if self.mode.currentData() == 'seconds' else 0}
        self.result = None; self.groups.clear(); self.import_button.setEnabled(False)
        self.progress_bar.setValue(0)
        if options['end_mode']:
            self.progress_bar.setRange(0, 0)
            self.status.setText('正在扫描所选视频轨，末尾提取可能需要完整解码两遍；可随时停止。')
        else:
            self.progress_bar.setRange(0, 100); self.status.setText('正在提取，结果会写入新建文件夹。')
        self.run_button.setEnabled(False); self.browse_source.setEnabled(False); self.browse_output.setEnabled(False)
        for field in (self.tracks, self.mode, self.start_time, self.end_seconds, self.start, self.count, self.group_size): field.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.worker = ExtractWorker(options, self)
        self.worker.progress.connect(self.update_progress)
        self.worker.succeeded.connect(self.extraction_done); self.worker.failed.connect(self.extraction_failed)
        self.worker.finished.connect(self.thread_finished); self.worker.start()

    def cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption(); self.status.setText('正在停止，请稍候…'); self.cancel_button.setEnabled(False)

    def update_progress(self, done, total):
        if done:
            self.progress_bar.setRange(0, 100); self.progress_bar.setValue(done * 100 // total)

    def thread_finished(self):
        worker = self.worker; self.worker = None
        if worker: worker.deleteLater()
        self.run_button.setEnabled(True); self.browse_source.setEnabled(True); self.browse_output.setEnabled(True)
        for field in (self.tracks, self.start, self.count, self.group_size): field.setEnabled(True)
        self.update_track()
        self.cancel_button.setEnabled(False)

    def extraction_done(self, result):
        self.result = result; self.groups.clear()
        for i, group in enumerate(result['groups']): self.groups.addItem(f'第 {i+1} 组 · {len(group)} 张')
        self.import_button.setEnabled(True)
        suffix = '（已达到张数上限，末尾时间范围内还有更多帧）' if result.get('truncated') else ('（少于设置的最多张数）' if result['count'] < result['requested'] else '')
        self.status.setText(f"已提取 {result['count']} 张，分成 {len(result['groups'])} 组{suffix}。保存位置：{result['directory']}")

    def extraction_failed(self, message):
        self.progress_bar.setRange(0, 100); self.progress_bar.setValue(0)
        self.status.setText('未完成：' + message)

    def import_group(self):
        if self.result is not None and self.groups.currentIndex() >= 0:
            self.owner.load_paths(self.result['groups'][self.groups.currentIndex()])

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.cancel(); event.ignore(); return
        super().closeEvent(event)

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.cancel(); return
        super().reject()
