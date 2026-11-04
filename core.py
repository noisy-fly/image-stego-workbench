"""独立实现的像素分析操作；所有输入均为原始 8 位像素。"""
import numpy as np
from PIL import Image, ImageOps, ImageFilter


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


def as_rgba(gray):
    return np.array(Image.fromarray(gray).convert('RGBA'))


def process_image(image, operation, **options):
    if operation == 'invert': return invert(image)
    if operation == 'channel': return as_rgba(channel(image, options['component']))
    if operation == 'plane': return as_rgba(bit_plane(image, options['component'], options['bit']))
    if operation == 'gray': return as_rgba(np.asarray(Image.fromarray(image).convert('L')))
    if operation == 'threshold':
        gray = np.asarray(Image.fromarray(image).convert('L'))
        return as_rgba((gray >= options['threshold']).astype(np.uint8) * 255)
    if operation == 'flip_h': return np.ascontiguousarray(image[:, ::-1])
    if operation == 'flip_v': return np.ascontiguousarray(image[::-1])
    if operation == 'rotate_cw': return np.ascontiguousarray(np.rot90(image, -1))
    if operation == 'rotate_ccw': return np.ascontiguousarray(np.rot90(image, 1))
    if operation in ('contrast', 'equalize', 'blur', 'edges'):
        rgb = Image.fromarray(image[:, :, :3])
        if operation == 'contrast': rgb = ImageOps.autocontrast(rgb)
        elif operation == 'equalize': rgb = ImageOps.equalize(rgb)
        elif operation == 'blur': rgb = rgb.filter(ImageFilter.GaussianBlur(options.get('radius', 1)))
        elif operation == 'edges': rgb = rgb.filter(ImageFilter.FIND_EDGES)
        result = image.copy(); result[:, :, :3] = np.asarray(rgb); return result
    raise ValueError('未知的单图操作。')


def combine_images(first, second, operation):
    if first.shape != second.shape: raise ValueError('图片尺寸必须一致。')
    a, b = first[:, :, :3], second[:, :, :3]
    if operation == 'xor': rgb = np.bitwise_xor(a, b)
    elif operation == 'and': rgb = np.bitwise_and(a, b)
    elif operation == 'or': rgb = np.bitwise_or(a, b)
    elif operation == 'add': rgb = (a.astype(np.uint16) + b.astype(np.uint16)).astype(np.uint8)
    elif operation == 'subtract': rgb = (a.astype(np.int16) - b.astype(np.int16)).astype(np.uint8)
    elif operation == 'difference': rgb = np.abs(a.astype(np.int16) - b.astype(np.int16)).astype(np.uint8)
    elif operation == 'mean': rgb = ((a.astype(np.uint16) + b.astype(np.uint16)) // 2).astype(np.uint8)
    else: raise ValueError('未知的双图操作。')
    result = np.empty_like(first); result[:, :, :3] = rgb; result[:, :, 3] = 255
    return result


def aggregate_images(images, operation):
    if len(images) < 2: raise ValueError('至少需要两张图片。')
    if any(im.shape != images[0].shape for im in images): raise ValueError('图片尺寸必须一致。')
    if operation == 'mean':
        total = np.zeros(images[0].shape[:2] + (3,), dtype=np.uint64)
        for im in images: total += im[:, :, :3]
        rgb = (total // len(images)).astype(np.uint8)
    elif operation in ('min', 'max'):
        rgb = images[0][:, :, :3].copy()
        for im in images[1:]:
            (np.minimum if operation == 'min' else np.maximum)(rgb, im[:, :, :3], out=rgb)
    else: raise ValueError('未知的多图统计操作。')
    result = np.empty_like(images[0]); result[:, :, :3] = rgb; result[:, :, 3] = 255
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
