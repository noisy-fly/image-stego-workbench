"""检查原始文件字节中的候选文件，绝不自动解压或执行。"""
import os
import struct
import tempfile
import zipfile
from pathlib import Path

SIGNATURES = (
    ('ZIP', b'PK\x03\x04', 'zip'), ('RAR', b'Rar!\x1a\x07', 'rar'),
    ('7z', b'7z\xbc\xaf\x27\x1c', '7z'), ('GZIP', b'\x1f\x8b\x08', 'gz'),
    ('BZIP2', b'BZh', 'bz2'), ('XZ', b'\xfd7zXZ\x00', 'xz'),
    ('PDF', b'%PDF-', 'pdf'), ('PNG', b'\x89PNG\r\n\x1a\n', 'png'),
    ('JPEG', b'\xff\xd8\xff', 'jpg'), ('GIF', b'GIF87a', 'gif'), ('GIF', b'GIF89a', 'gif'),
    ('SQLite', b'SQLite format 3\x00', 'sqlite'), ('ELF', b'\x7fELF', 'elf'),
    ('OGG', b'OggS\x00', 'ogg'),
)
MAX_SCAN = 512 * 1024 * 1024
MAX_CANDIDATES = 512


def source_reference(path):
    path = Path(path).resolve(strict=True); stat = path.stat()
    if not path.is_file(): raise ValueError('来源不是普通文件。')
    return (str(path), stat.st_size, stat.st_mtime_ns)


def check_source(handle, reference):
    stat = os.fstat(handle.fileno())
    if (stat.st_size, stat.st_mtime_ns) != (reference[1], reference[2]):
        raise ValueError('原文件自导入后发生变化，请重新导入再检查。')


def png_boundary(handle, size):
    handle.seek(0)
    if handle.read(8) != b'\x89PNG\r\n\x1a\n': return None
    position = 8
    chunks = 0
    while position + 12 <= size and chunks < 100000:
        handle.seek(position); header = handle.read(8)
        if len(header) != 8: return None
        length, kind = struct.unpack('>I4s', header)
        end = position + length + 12
        if end > size: return None
        if kind == b'IEND':
            if length != 0: return None
            handle.seek(position + 8)
            return end if handle.read(4) == b'\xaeB`\x82' else None
        position = end
        chunks += 1
    return None


def jpeg_boundary(handle, size):
    handle.seek(0)
    if handle.read(2) != b'\xff\xd8': return None
    in_scan = False; markers = 0
    while handle.tell() < size and markers < 100000:
        if in_scan:
            block_start = handle.tell(); block = handle.read(min(65536, size - block_start))
            index = block.find(b'\xff')
            if index < 0: continue
            handle.seek(block_start + index + 1)
        elif handle.read(1) != b'\xff': return None
        marker = handle.read(1)
        while marker == b'\xff': marker = handle.read(1)
        if not marker: return None
        code = marker[0]; markers += 1
        if in_scan and (code == 0 or 0xd0 <= code <= 0xd7): continue
        if code == 0xd9: return handle.tell()
        if code == 0x01 or code == 0xd8 or 0xd0 <= code <= 0xd7: continue
        length_bytes = handle.read(2)
        if len(length_bytes) != 2: return None
        length = int.from_bytes(length_bytes, 'big')
        if length < 2 or handle.tell() + length - 2 > size: return None
        handle.seek(length - 2, os.SEEK_CUR)
        in_scan = code == 0xda
    return None


def gif_boundary(handle, size):
    handle.seek(0); header = handle.read(13)
    if len(header) != 13 or header[:6] not in (b'GIF87a', b'GIF89a'): return None
    if header[10] & 0x80: handle.seek(3 * (2 ** ((header[10] & 7) + 1)), os.SEEK_CUR)
    def blocks():
        while handle.tell() < size:
            length = handle.read(1)
            if not length: return False
            if length[0] == 0: return True
            if handle.tell() + length[0] > size: return False
            handle.seek(length[0], os.SEEK_CUR)
        return False
    while handle.tell() < size:
        marker = handle.read(1)
        if marker == b'\x3b': return handle.tell()
        if marker == b'\x21':
            if not handle.read(1) or not blocks(): return None
        elif marker == b'\x2c':
            descriptor = handle.read(9)
            if len(descriptor) != 9: return None
            if descriptor[8] & 0x80: handle.seek(3 * (2 ** ((descriptor[8] & 7) + 1)), os.SEEK_CUR)
            if not handle.read(1) or not blocks(): return None
        else: return None
    return None


def inspect_file(reference, chunk_size=1024*1024, max_scan=MAX_SCAN, progress=None, cancel=None):
    if not reference: raise ValueError('这张图片没有可检查的原始文件；请先保存并重新导入。')
    if chunk_size < 1 or max_scan < 1: raise ValueError('扫描范围无效。')
    cancel = cancel or (lambda: False)
    with open(reference[0], 'rb') as handle:
        check_source(handle, reference); size = reference[1]
        image_end = png_boundary(handle, size) or jpeg_boundary(handle, size) or gif_boundary(handle, size)
        limit = min(size, max_scan); handle.seek(0); found = []; seen = set(); carry = b''; pos = 0
        overlap = max(len(signature) for _, signature, _ in SIGNATURES) - 1
        while pos < limit and len(found) < MAX_CANDIDATES:
            if cancel(): raise InterruptedError('已取消检查。')
            data = handle.read(min(chunk_size, limit - pos))
            if not data: break
            block = carry + data; base = pos - len(carry)
            for kind, signature, extension in SIGNATURES:
                index = block.find(signature)
                while index >= 0:
                    offset = base + index; key = (kind, offset)
                    if offset > 0 and key not in seen:
                        seen.add(key)
                        location = 'trailing' if image_end is not None and offset >= image_end else ('inside' if image_end is not None else 'unknown')
                        found.append({'kind': kind, 'extension': extension, 'offset': offset, 'location': location,
                                      'verified': False, 'members': [], 'encrypted': None})
                        if len(found) >= MAX_CANDIDATES: break
                    index = block.find(signature, index + 1)
                if len(found) >= MAX_CANDIDATES: break
            pos += len(data); carry = block[-overlap:]
            if progress: progress(pos, size)
        if size <= 128 * 1024 * 1024 and any(item['kind'] == 'ZIP' for item in found):
            try:
                handle.seek(0)
                with zipfile.ZipFile(handle) as archive:
                    entries = archive.infolist()
                    if entries:
                        first = min(entry.header_offset for entry in entries)
                        for item in found:
                            if item['kind'] == 'ZIP' and item['offset'] == first:
                                item['verified'] = True
                                item['members'] = [entry.filename for entry in entries[:30]]
                                item['encrypted'] = any(entry.flag_bits & 1 for entry in entries)
            except (zipfile.BadZipFile, OSError, ValueError, OverflowError): pass
        check_source(handle, reference)
    found.sort(key=lambda item: (item['offset'], item['kind']))
    return {'size': size, 'scanned': pos, 'image_end': image_end, 'candidates': found,
            'incomplete': pos < size or len(found) >= MAX_CANDIDATES}


def save_candidate(reference, offset, destination):
    if not reference: raise ValueError('没有可读取的原始文件。')
    target = Path(destination).resolve(); source = Path(reference[0]).resolve()
    if target == source or (target.exists() and os.path.samefile(target, source)):
        raise ValueError('不能覆盖原始图片。')
    if not 0 <= offset < reference[1]: raise ValueError('候选位置超出文件范围。')
    temporary = None
    try:
        with open(source, 'rb') as handle:
            check_source(handle, reference); handle.seek(offset)
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.stego-', delete=False) as output:
                temporary = Path(output.name)
                while True:
                    chunk = handle.read(1024*1024)
                    if not chunk: break
                    output.write(chunk)
            check_source(handle, reference)
        if target == source or (target.exists() and os.path.samefile(target, source)):
            raise ValueError('不能覆盖原始图片。')
        os.replace(temporary, target); temporary = None
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)
