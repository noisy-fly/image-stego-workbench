"""JSteg v0.3.0 extraction using original bytes, without modifying the carrier."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from PIL import Image, UnidentifiedImageError
from file_inspection import check_source, source_reference

MAX_INPUT = 64 * 1024 * 1024
MAX_PIXELS = 50_000_000
MAX_OUTPUT = 16 * 1024 * 1024


def validate_source(handle, reference):
    check_source(handle, reference)
    try:
        current = source_reference(reference[0])
    except OSError as exc:
        raise ValueError('原文件已移动或删除，请重新导入。') from exc
    if current != reference: raise ValueError('原文件自导入后发生变化，请重新导入。')


def reveal_jsteg(reference, cancel=None):
    if not reference: raise ValueError('这张图片没有原始文件，请先保存并重新导入。')
    cancel = cancel or (lambda: False)
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    program = root / 'vendor' / 'jsteg' / 'jsteg.exe'
    if not program.is_file(): raise ValueError('找不到 JSteg 组件，请重新安装程序。')
    if reference[1] > MAX_INPUT: raise ValueError('图片超过 JSteg 检查上限（64 MiB）。')
    with tempfile.TemporaryDirectory(prefix='stego_jsteg_') as folder:
        source_copy = Path(folder) / 'input.jpg'
        output_file = Path(folder) / 'output.bin'
        with open(reference[0], 'rb') as original:
            validate_source(original, reference)
            if original.read(3) != b'\xff\xd8\xff': raise ValueError('JSteg 提取仅支持 JPEG 原始文件。')
            original.seek(0)
            try:
                with Image.open(original) as image:
                    if image.format != 'JPEG': raise ValueError('JSteg 提取仅支持 JPEG 原始文件。')
                    if image.width * image.height > MAX_PIXELS: raise ValueError('图片超过 JSteg 检查上限（5000 万像素）。')
            except (UnidentifiedImageError, OSError) as exc:
                raise ValueError('JPEG 图片无法读取。') from exc
            original.seek(0)
            with source_copy.open('wb') as snapshot:
                while True:
                    if cancel(): raise InterruptedError('已取消 JSteg 提取。')
                    chunk = original.read(1024 * 1024)
                    if not chunk: break
                    snapshot.write(chunk)
            validate_source(original, reference)
            try:
                with output_file.open('wb') as out:
                    process = subprocess.Popen([str(program), 'reveal', str(source_copy)],
                        stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.PIPE,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    try:
                        import time
                        started = time.monotonic()
                        while True:
                            if cancel(): raise InterruptedError('已取消 JSteg 提取。')
                            if time.monotonic() - started > 60: raise TimeoutError('JSteg 提取超时。')
                            if output_file.stat().st_size > MAX_OUTPUT: raise ValueError('提取内容超过大小上限（16 MiB）。')
                            try:
                                _, stderr = process.communicate(timeout=0.1); break
                            except subprocess.TimeoutExpired: continue
                    finally:
                        if process.poll() is None:
                            process.kill(); process.communicate()
            except OSError as exc:
                raise ValueError('无法运行 JSteg 组件。') from exc
            validate_source(original, reference)
            if process.returncode:
                message = stderr.decode('utf-8', errors='replace').lower()
                if 'does not contain hidden data' in message: raise ValueError('未发现此 JSteg 版本支持的隐藏数据。')
                if 'progressive' in message: raise ValueError('此 JSteg 组件不支持渐进式 JPEG。')
                raise ValueError('JSteg 提取失败：图片格式不受支持、文件损坏或隐藏数据无效。')
            if output_file.stat().st_size > MAX_OUTPUT: raise ValueError('提取内容超过大小上限（16 MiB）。')
            return output_file.read_bytes()


def save_payload(reference, data, destination):
    if not reference: raise ValueError('没有原始文件。')
    source = Path(reference[0]).resolve(); target = Path(destination).resolve()
    def check_target():
        if target == source or (target.exists() and os.path.samefile(source, target)):
            raise ValueError('不能覆盖原始图片，请选择其他文件名。')
    check_target(); temporary = None
    try:
        with open(source, 'rb') as original:
            validate_source(original, reference)
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.stego-jsteg-', delete=False) as output:
                temporary = Path(output.name); output.write(data)
            validate_source(original, reference); check_target()
            os.replace(temporary, target); temporary = None
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)
