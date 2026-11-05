"""独立实现的像素分析操作；所有输入均为原始 8 位像素。"""
import numpy as np
import re
import itertools
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
    if operation == 'constant_xor':
        value = options['value']
        if not 0 <= value <= 255: raise ValueError('异或值必须在 0 到 255 之间。')
        result = image.copy(); result[:, :, :3] ^= np.uint8(value); return result
    if operation == 'low_bits':
        bits = options['bits']
        if not 1 <= bits <= 8: raise ValueError('位数必须在 1 到 8 之间。')
        mask = (1 << bits) - 1
        result = np.empty_like(image); result[:, :, :3] = ((image[:, :, :3] & mask).astype(np.uint16) * 255 // mask).astype(np.uint8)
        result[:, :, 3] = 255; return result
    if operation == 'swap_rb':
        result = image.copy(); result[:, :, :3] = image[:, :, [2, 1, 0]]; return result
    if operation == 'rgb_xor':
        return as_rgba(image[:, :, 0] ^ image[:, :, 1] ^ image[:, :, 2])
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
    elif operation == 'xnor': rgb = np.bitwise_not(np.bitwise_xor(a, b))
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


def extract_bits(image, components, bits, column_first=False, lsb_first=False,
                 reverse_x=False, reverse_y=False, bit_offset=0):
    if not components or not bits or bit_offset < 0: raise ValueError('请选择通道、位，且跳过位数不能为负数。')
    source = image[::-1 if reverse_y else 1, ::-1 if reverse_x else 1]
    if column_first: source = source.transpose(1, 0, 2)
    pixels = source.reshape(-1, source.shape[2])
    values = np.stack([(pixels[:, c] >> b) & 1 for c in components for b in bits], axis=1).reshape(-1)
    values = values[bit_offset:]
    values = values[:len(values) // 8 * 8]
    return np.packbits(values, bitorder='little' if lsb_first else 'big').tobytes()


def scan_lsb(image, max_pixels=65536):
    """检查有限像素前缀，返回可复现的扫描参数和疑似线索。"""
    if image.ndim != 3 or image.shape[2] != 4 or image.dtype != np.uint8 or max_pixels < 1:
        raise ValueError('需要 8 位 RGBA 图片和正数扫描范围。')
    signatures = [('PNG 文件头', b'\x89PNG\r\n\x1a\n'), ('ZIP 文件头', b'PK\x03\x04'),
                  ('GIF 文件头', b'GIF89a'), ('GIF 文件头', b'GIF87a'),
                  ('PDF 文件头', b'%PDF-'), ('7z 文件头', b'7z\xbc\xaf\x27\x1c'),
                  ('RAR 文件头', b'Rar!\x1a\x07'), ('GZIP 文件头', b'\x1f\x8b\x08')]
    channel_sets = [item for size in range(1, 5) for item in itertools.permutations(range(4), size)]
    height, width = image.shape[:2]; count = min(height * width, max_pixels)
    positions = np.arange(count); results = []
    for column in (False, True):
        y, x = (positions % height, positions // height) if column else (positions // width, positions % width)
        pixels = image[y, x]
        for channels in channel_sets:
            for bit in (0, 1):
                values = ((pixels[:, channels] >> bit) & 1).reshape(-1)
                for little in (False, True):
                    data = np.packbits(values[:len(values)//8*8], bitorder='little' if little else 'big').tobytes()
                    hits = [(kind, data.find(signature)) for kind, signature in signatures]
                    pattern = rb'(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9_]{0,31}\{[\x20-\x7a\x7c\x7e]{1,200}\}'
                    matches = re.finditer(pattern, data)
                    for index, match in enumerate(matches):
                        if index >= 16: break
                        hits.insert(index, ('花括号格式文本', match.start()))
                    for kind, offset in hits:
                        if offset >= 0:
                            results.append({'channels': channels, 'bit': bit, 'column': column, 'little': little,
                                            'kind': kind, 'offset': offset, 'preview': data[offset:offset+80]})
    return results


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


def scan_lsb_conditional(image, channels, bits, directions=(False, True), start_bit=0, alignments=True, max_pixels=65536):
    """遍历指定通道、位的排列，返回精确提取参数。"""
    import math
    if not channels or not bits or start_bit < 0: raise ValueError('请选择通道和位，并填写非负跳过位数。')
    total = math.factorial(len(channels))*math.factorial(len(bits))*len(directions)*2*(8 if alignments else 1)
    if total > 4096: raise ValueError(f'需要尝试 {total} 种组合，超过 4096 种上限；请减少通道或位。')
    if image.ndim != 3 or image.shape[2] != 4: raise ValueError('需要 RGBA 图片。')
    result=[]; height,width=image.shape[:2]; per_pixel=len(channels)*len(bits)
    start_pixel=start_bit//per_pixel; count=min(height*width-start_pixel,max_pixels+2)
    if count <= 0: return result
    positions=np.arange(start_pixel,start_pixel+count)
    pattern=rb'(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9_]{0,31}\{[\x20-\x7a\x7c\x7e]{1,200}\}'
    signatures=[('PNG 文件头',b'\x89PNG\r\n\x1a\n'),('ZIP 文件头',b'PK\x03\x04'),('PDF 文件头',b'%PDF-'),('GIF 文件头',b'GIF89a'),('7z 文件头',b'7z\xbc\xaf\x27\x1c')]
    for column in directions:
        y,x=(positions%height,positions//height) if column else (positions//width,positions%width)
        pixels=image[y,x]
        for ch in itertools.permutations(channels):
            for order in itertools.permutations(bits):
                values=np.stack([(pixels[:,c]>>b)&1 for c in ch for b in order],axis=1).reshape(-1)
                for shift in range(8 if alignments else 1):
                    skip=start_bit+shift-start_pixel*per_pixel
                    for little in (False,True):
                        data=np.packbits(values[skip:len(values)-(len(values)-skip)%8],bitorder='little' if little else 'big').tobytes()
                        hits=[(kind,data.find(sig)) for kind,sig in signatures]
                        hits += [('花括号格式文本',m.start()) for m in itertools.islice(re.finditer(pattern,data),16)]
                        for kind,off in hits:
                            if off >= 0:
                                result.append(dict(channels=ch,bits=order,bit=order[0],column=column,little=little,kind=kind,offset=off,skip_bits=start_bit+shift+off*8,preview=data[off:off+80]))
    return result
