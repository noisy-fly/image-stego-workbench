"""独立实现的像素分析操作；所有输入均为原始 8 位像素。"""
import numpy as np
from PIL import Image


def make_pair_groups(count, step=1, mode='subset', offset=0):
    if count < 2 or step < 1 or offset < 0 or offset >= step:
        raise ValueError('图片数量、步长或组号无效。')
    if mode == 'distance':
        if count % (step * 2):
            raise ValueError('指定间隔配对要求图片数为间隔的两倍的整数倍，避免遗漏图片。')
        return [[(base + i, base + step + i) for base in range(0, count, step * 2) for i in range(step)]]
    if mode not in ('subset', 'groups'):
        raise ValueError('不支持的配对方式。')
    offsets = range(step) if mode == 'groups' else [offset]
    groups = []
    for start in offsets:
        indexes = list(range(start, count, step))
        if len(indexes) < 2 or len(indexes) % 2:
            raise ValueError(f'第 {start + 1} 组有 {len(indexes)} 张图片，必须为至少 2 张的偶数，请调整范围或步长。')
        groups.append(list(zip(indexes[::2], indexes[1::2])))
    return groups


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
