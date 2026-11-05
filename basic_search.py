"""Search original bytes and readable image metadata for simple flag-like text."""
import re
from PIL import Image, ExifTags, UnidentifiedImageError
from file_inspection import check_source

NAME = rb'[A-Za-z][A-Za-z0-9_-]{0,63}'
BODY = rb'[\x20-\x7a\x7c\x7e]{1,256}'
PATTERN = NAME + rb'\{' + BODY + rb'\}'
ASCII = re.compile(PATTERN)
TEXT = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,63}\{[\x20-\x7a\x7c\x7e]{1,256}\}')
# ASCII-compatible characters encoded as UTF-16, independent of byte alignment.
def wide_pattern(little):
    def byte_set(chars):
        return (b'[' + chars + b']\x00') if little else (b'\x00[' + chars + b']')
    first = byte_set(b'A-Za-z')
    rest = byte_set(b'A-Za-z0-9_-')
    body = byte_set(rb'\x20-\x7a\x7c\x7e')
    left, right = (b'\x7b\x00', b'\x7d\x00') if little else (b'\x00\x7b', b'\x00\x7d')
    return re.compile(first + b'(?:' + rest + b'){0,63}' + re.escape(left) + b'(?:' + body + b'){1,256}' + re.escape(right))

PATTERNS = ((ASCII, 'ASCII/UTF-8', 'ascii'), (wide_pattern(True), 'UTF-16LE', 'utf-16le'), (wide_pattern(False), 'UTF-16BE', 'utf-16be'))
OVERLAP = 2 * (64 + 2 + 256)
MAX_RESULTS = 256


def search_basic(reference, chunk_size=1024 * 1024, progress=None, cancel=None):
    if not reference: raise ValueError('这张图片没有原始文件，请先保存并重新导入。')
    if chunk_size < 1: raise ValueError('扫描块大小无效。')
    cancel = cancel or (lambda: False)
    matches = []; seen = set(); truncated = False
    def add(text, source, offset, encoding):
        nonlocal truncated
        key = (text, source, offset)
        if key in seen: return
        seen.add(key)
        if len(matches) >= MAX_RESULTS: truncated = True; return
        matches.append(dict(text=text, source=source, offset=offset, encoding=encoding))
    with open(reference[0], 'rb') as handle:
        check_source(handle, reference)
        total = reference[1]; position = 0; carry = b''; processed = 0
        while position < total:
            if cancel(): raise InterruptedError('已取消搜索。')
            data = handle.read(min(chunk_size, total - position))
            if not data: break
            position += len(data); block = carry + data; base = position - len(block)
            safe_end = position if position == total else max(processed, position - OVERLAP)
            found = []
            for pattern, label, codec in PATTERNS:
                for match in pattern.finditer(block):
                    start = base + match.start()
                    if processed <= start < safe_end:
                        found.append((start, match.group().decode(codec), label))
            for start, text, label in sorted(found): add(text, '原始文件', start, label)
            processed = safe_end
            carry = block[max(0, processed - base):]
            if progress: progress(position, total)
            if truncated: break
        if not truncated and not cancel():
            try:
                handle.seek(0)
                with Image.open(handle) as image:
                    values = list(image.info.items())
                    values.extend((ExifTags.TAGS.get(k, str(k)), v) for k, v in image.getexif().items())
                    for key, value in values:
                        if isinstance(value, str):
                            for match in TEXT.finditer(value[:1024 * 1024]):
                                add(match.group(), '图片属性：' + str(key), None, '文本')
                        if truncated: break
            except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
                pass
        if cancel(): raise InterruptedError('已取消搜索。')
        check_source(handle, reference)
    matches.sort(key=lambda x: (x['offset'] is None, x['offset'] or 0, x['text']))
    return {'matches': matches, 'size': total, 'scanned': position, 'truncated': truncated}
