import struct
from pathlib import Path

def bmp_height_candidate(path):
    p=Path(path)
    with p.open('rb') as f: h=f.read(54)
    if len(h)<54 or h[:2]!=b'BM': return None
    size,offset=struct.unpack_from('<I4xI',h,2); dib,width,height,planes,bpp,compression,stored=struct.unpack_from('<IiiHHII',h,14)
    if dib!=40 or width<=0 or height==0 or planes!=1 or bpp not in (8,24,32) or compression!=0: return None
    stride=((width*bpp+31)//32)*4
    if size!=p.stat().st_size or stored!=size-offset or stride<=0: return None
    rows,remainder=divmod(stored,stride)
    if not abs(height)<rows<=16384 or rows*width>50000000 or remainder>3: return None
    return height, rows if height>0 else -rows, remainder

def bmp_with_height(path,height):
    with open(path,'rb') as f: data=bytearray(f.read())
    struct.pack_into('<i',data,22,height)
    return bytes(data)
