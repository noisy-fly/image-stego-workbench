"""针对 PNG IHDR 单一宽度或高度被修改的有限修复。"""
import io
import struct
import zlib
from PIL import Image

MAX_DIMENSION = 16384
MAX_PIXELS = 50_000_000
MAX_FILE_SIZE = 256 * 1024 * 1024


def repair_png_dimensions(data):
    if len(data) < 33 or data[:16] != b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR': return None
    header = bytearray(data[12:29]); expected = int.from_bytes(data[29:33], 'big')
    if zlib.crc32(header) == expected: return None
    width, height = struct.unpack('>II', header[4:12]); candidates = []
    for label, offset, other in (('宽度', 4, height), ('高度', 8, width)):
        if not 1 <= other <= MAX_DIMENSION: continue
        for value in range(1, min(MAX_DIMENSION, MAX_PIXELS // other) + 1):
            header[offset:offset+4] = struct.pack('>I', value)
            if zlib.crc32(header) == expected: candidates.append((label, offset, value))
        header[4:12] = struct.pack('>II', width, height)
    if len(candidates) != 1: return None
    label, offset, value = candidates[0]
    fixed = bytearray(data); fixed[12+offset:16+offset] = struct.pack('>I', value)
    try:
        with Image.open(io.BytesIO(fixed)) as image:
            image.load()
    except (OSError, ValueError, Image.DecompressionBombError): return None
    old = width if label == '宽度' else height
    return bytes(fixed), f'{label} {old} → {value}'
