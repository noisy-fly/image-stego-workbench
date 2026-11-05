"""从常见载体提取图片，逐张保存并分组，不推断隐写算法。"""
import base64
import binascii
import io
import re
import shutil
import tarfile
import tempfile
import warnings
import zipfile
from pathlib import Path

from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 64 * 1024 * 1024
FORMATS = {'PNG': 'png', 'JPEG': 'jpg', 'BMP': 'bmp', 'GIF': 'gif', 'WEBP': 'webp', 'TIFF': 'tiff'}
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp', '.tif', '.tiff'}


def natural_key(name):
    return [int(v) if v.isdigit() else v.casefold() for v in re.split(r'(\d+)', name)]


def image_extension(data):
    if not data or len(data) > MAX_IMAGE_BYTES: return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                ext = FORMATS.get(image.format); image.verify()
                return ext
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return None


def decode_embedded_image(text):
    if isinstance(text, bytes):
        extension = image_extension(text)
        if extension: return text, extension
        try: text = text.decode('utf-8')
        except UnicodeDecodeError: return None
    if len(text) > MAX_IMAGE_BYTES * 2 + 4096: return None
    compact = ''.join(text.split())
    if not compact: return None
    candidates = []
    if len(compact) % 2 == 0 and re.fullmatch(r'[0-9A-Fa-f]+', compact):
        try: candidates.append(bytes.fromhex(compact))
        except ValueError: pass
    if len(compact) <= (MAX_IMAGE_BYTES * 4 // 3 + 8):
        try: candidates.append(base64.b64decode(compact, validate=True))
        except (binascii.Error, ValueError): pass
    for data in candidates:
        extension = image_extension(data)
        if extension: return data, extension
    return None


def inspect_source(path):
    path = Path(path)
    if not path.is_file(): raise ValueError('请选择存在的文件。')
    if zipfile.is_zipfile(path): return [{'kind': 'zip', 'index': None, 'label': 'ZIP 压缩包中的图片'}]
    if tarfile.is_tarfile(path): return [{'kind': 'tar', 'index': None, 'label': 'TAR 压缩包中的图片'}]
    if path.suffix.casefold() == '.gif':
        with Image.open(path) as image:
            if image.format != 'GIF': raise ValueError('文件不是有效 GIF。')
            return [{'kind': 'gif', 'index': None, 'label': f'GIF 动画（{getattr(image, "n_frames", 1)} 帧）'}]
    try:
        import av
    except ImportError as exc: raise ValueError('未安装视频解码组件 PyAV，无法读取视频。') from exc
    with av.open(str(path)) as container:
        sources = []
        for stream in container.streams:
            if stream.type not in ('video', 'subtitle'): continue
            codec = stream.codec_context.name if stream.codec_context else '未知'
            if stream.type == 'video':
                label = f'视频轨 #{stream.index} · {codec} · {stream.width}×{stream.height}'
            else:
                label = f'字幕轨 #{stream.index} · {codec}（尝试识别图片文本）'
            sources.append({'kind': stream.type, 'index': stream.index, 'label': label})
        if not sources: raise ValueError('未找到视频轨或字幕轨。')
        return sources


def iter_source(path, kind, stream_index, start_time, cancel):
    if kind == 'gif':
        with Image.open(path) as image:
            for i in range(getattr(image, 'n_frames', 1)):
                if cancel(): raise InterruptedError('已取消提取。')
                image.seek(i); yield image.convert('RGBA').copy(), 'png'
        return
    if kind in ('zip', 'tar'):
        archive = zipfile.ZipFile(path) if kind == 'zip' else tarfile.open(path, 'r:*')
        with archive:
            if kind == 'zip':
                members = [m for m in archive.infolist() if not m.is_dir() and Path(m.filename).suffix.casefold() in IMAGE_SUFFIXES]
                members.sort(key=lambda m: natural_key(m.filename))
            else:
                members = [m for m in archive.getmembers() if m.isfile() and Path(m.name).suffix.casefold() in IMAGE_SUFFIXES]
                members.sort(key=lambda m: natural_key(m.name))
            for member in members:
                if cancel(): raise InterruptedError('已取消提取。')
                size = member.file_size if kind == 'zip' else member.size
                if size > MAX_IMAGE_BYTES: raise ValueError('压缩包中有图片超过 64 MiB，已停止提取。')
                source = archive.open(member) if kind == 'zip' else archive.extractfile(member)
                if source is None: continue
                with source: data = source.read(MAX_IMAGE_BYTES + 1)
                extension = image_extension(data)
                if extension: yield data, extension
        return
    import av
    with av.open(str(path)) as container:
        stream = next((s for s in container.streams if s.index == stream_index and s.type == kind), None)
        if stream is None: raise ValueError('所选媒体轨道不存在。')
        if kind == 'video':
            if start_time > 0: container.seek(int(start_time * av.time_base), backward=True)
            for frame in container.decode(stream):
                if cancel(): raise InterruptedError('已取消提取。')
                if start_time > 0:
                    if frame.time is None: raise ValueError('此视频帧缺少时间戳，无法按时间截取。')
                    if frame.time < start_time: continue
                yield frame.to_image(), 'png'
        elif kind == 'subtitle':
            for packet in container.demux(stream):
                if cancel(): raise InterruptedError('已取消提取。')
                if packet.size > MAX_IMAGE_BYTES * 2 + 4096: raise ValueError('字幕数据过大，已停止提取。')
                decoded = decode_embedded_image(bytes(packet)) if packet.size else None
                if decoded: yield decoded
        else: raise ValueError('不支持的来源类型。')


def extract_groups(path, kind, stream_index, output_parent, start=0, count=200, group_size=200,
                   start_time=0, progress=None, cancel=None):
    if start < 0 or not 1 <= count <= 2000 or not 1 <= group_size <= 500 or start_time < 0:
        raise ValueError('起始位置、数量或每组数量超出范围。')
    output_parent = Path(output_parent).resolve()
    if not output_parent.is_dir(): raise ValueError('请选择存在的输出文件夹。')
    root = Path(tempfile.mkdtemp(prefix='图片提取_', dir=output_parent)).resolve()
    groups = []; extracted = 0; cancel = cancel or (lambda: False)
    try:
        for index, (data, extension) in enumerate(iter_source(Path(path), kind, stream_index, start_time, cancel)):
            if cancel(): raise InterruptedError('已取消提取。')
            if index < start: continue
            group_index = extracted // group_size
            if group_index == len(groups):
                (root / f'第{group_index+1:03}组').mkdir(); groups.append([])
            target = root / f'第{group_index+1:03}组' / f'{extracted:06}.{extension}'
            if isinstance(data, bytes): target.write_bytes(data)
            else: data.save(target, format='PNG')
            groups[-1].append(str(target)); extracted += 1
            if progress: progress(extracted, count)
            if extracted == count: break
        if extracted == 0: raise ValueError('没有找到符合条件的图片；普通字幕不会被当作图片。')
        return {'directory': str(root), 'groups': groups, 'count': extracted, 'requested': count}
    except Exception:
        if root.parent == output_parent and root.name.startswith('图片提取_'):
            shutil.rmtree(root)
        raise
