from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QComboBox, QSpinBox, QPushButton, QListWidget, QTextEdit
from core import scan_lsb_conditional

class Worker(QThread):
    done = Signal(object)
    failed = Signal(str)
    def __init__(self, image, args, parent):
        super().__init__(parent); self.image=image; self.args=args
    def run(self):
        try: self.done.emit(scan_lsb_conditional(self.image, **self.args))
        except Exception as exc: self.failed.emit(str(exc))

class ConditionalDialog(QDialog):
    def __init__(self, parent, image, extract):
        super().__init__(parent); self.image=image; self.extract=extract; self.worker=None; self.results=[]
        self.setWindowTitle('条件 LSB 检查'); self.resize(850,650); box=QVBoxLayout(self)
        box.addWidget(QLabel('选中的通道和位均按所有顺序排列；每次使用全部勾选项。'))
        row=QHBoxLayout(); row.addWidget(QLabel('通道：')); self.channels=[]
        for i,n in enumerate('RGBA'):
            c=QCheckBox(n); c.setChecked(i<3); self.channels.append(c); row.addWidget(c)
        box.addLayout(row); row=QHBoxLayout(); row.addWidget(QLabel('位：')); self.bits=[]
        for i in range(8):
            c=QCheckBox(str(i)); c.setChecked(i==0); self.bits.append(c); row.addWidget(c)
        box.addLayout(row); row=QHBoxLayout(); row.addWidget(QLabel('扫描方向：')); self.direction=QComboBox(); self.direction.addItems(['按行和按列','仅按行','仅按列']); row.addWidget(self.direction)
        row.addWidget(QLabel('从第几位开始：')); self.offset=QSpinBox(); self.offset.setRange(0,1000000000); row.addWidget(self.offset); box.addLayout(row)
        self.align=QCheckBox('尝试起点后的 0～7 位对齐（耗时约增加 8 倍）'); self.align.setChecked(True); box.addWidget(self.align)
        box.addWidget(QLabel('每种组合从起点起最多检查 65,536 个像素；自动检查两种字节位序。'))
        self.status=QLabel('选择条件后开始'); box.addWidget(self.status)
        self.start=QPushButton('开始检查'); self.start.clicked.connect(self.run_scan); box.addWidget(self.start)
        self.list=QListWidget(); box.addWidget(self.list); self.preview=QTextEdit(); self.preview.setReadOnly(True); self.preview.setMaximumHeight(130); box.addWidget(self.preview)
        self.open=QPushButton('使用选中参数提取完整数据'); self.open.setEnabled(False); self.open.clicked.connect(self.open_result); box.addWidget(self.open); self.list.currentRowChanged.connect(self.select)
    def run_scan(self):
        channels=tuple(i for i,c in enumerate(self.channels) if c.isChecked()); bits=tuple(i for i,c in enumerate(self.bits) if c.isChecked())
        dirs=((False,True),(False,),(True,))[self.direction.currentIndex()]
        self.results=[]; self.list.clear(); self.start.setEnabled(False); self.status.setText('正在检查，请稍候…')
        self.worker=Worker(self.image,dict(channels=channels,bits=bits,directions=dirs,start_bit=self.offset.value(),alignments=self.align.isChecked()),self)
        self.worker.done.connect(self.show_results); self.worker.failed.connect(self.fail); self.worker.finished.connect(lambda:self.start.setEnabled(True)); self.worker.start()
    def fail(self,message): self.status.setText('检查失败：'+message)
    def show_results(self,results):
        self.results=results; self.status.setText(f'检查完成：{len(results)} 条候选；结果可能误报，未发现不代表没有隐写。')
        for item in results:
            self.list.addItem("%s · %s · 位 %s · %s · %s · 跳过 %d 位" % (item['kind'],''.join('RGBA'[i] for i in item['channels']),','.join(map(str,item['bits'])),'按列' if item['column'] else '按行','低位先' if item['little'] else '高位先',item['skip_bits']))
    def select(self,i):
        self.open.setEnabled(0<=i<len(self.results))
        if 0<=i<len(self.results):
            data=self.results[i]['preview']; self.preview.setPlainText(data.decode('utf8',errors='replace')+'\n\n'+data.hex(' '))
    def open_result(self):
        i=self.list.currentRow()
        if 0<=i<len(self.results): self.extract(self.results[i])
    def reject(self):
        if self.worker and self.worker.isRunning(): self.status.setText('检查仍在进行，请等待完成后关闭。'); return
        super().reject()
    def closeEvent(self,event):
        if self.worker and self.worker.isRunning(): self.status.setText('检查仍在进行，请等待完成后关闭。'); event.ignore(); return
        super().closeEvent(event)
