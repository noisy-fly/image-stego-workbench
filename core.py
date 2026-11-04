"""独立实现的像素分析操作；所有输入均为原始 8 位像素。"""
import numpy as np
from PIL import Image


def load_image(path):
    with Image.open(path) as image:
        return np.array(image.convert('RGBA'), dtype=np.uint8)


def bit_plane(image, component, bit):
    return ((image[:, :, component] >> bit) & 1) * np.uint8(255)


def channel(image, component):
    return image[:, :, component].copy()


def invert(image):
    result = image.copy()
    result[:, :, :3] = 255 - result[:, :, :3]
    return result


def extract_bits(image, components, bits, column_first=False, lsb_first=False):
    source = image.transpose(1, 0, 2) if column_first else image
    pixels = source.reshape(-1, source.shape[2])
    values = np.stack([(pixels[:, c] >> b) & 1 for c in components for b in bits], axis=1).reshape(-1)
    values = values[:len(values) // 8 * 8]
    return np.packbits(values, bitorder='little' if lsb_first else 'big').tobytes()


def pair_xor_average(frames, threshold=129):
    if not frames or len(frames) % 2:
        raise ValueError('需要偶数张图片，且至少两张。')
    size = frames[0].shape[:2]
    total = np.zeros(size, dtype=np.uint32)
    for first, second in zip(frames[::2], frames[1::2]):
        if first.shape[:2] != size or second.shape[:2] != size:
            raise ValueError('所有图片尺寸必须一致。')
        a = np.asarray(Image.fromarray(first).convert('L')) if first.ndim == 3 else first
        b = np.asarray(Image.fromarray(second).convert('L')) if second.ndim == 3 else second
        total += np.bitwise_xor(a >= threshold, b >= threshold)
    return (total * 255 // (len(frames) // 2)).astype(np.uint8)
