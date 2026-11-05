from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def decode_bpg(path):
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    decoder = root / 'vendor' / 'bpg' / 'bpgdec.exe'
    if not decoder.is_file():
        raise ValueError('找不到 BPG 解码器，请重新安装程序。')
    try:
        with tempfile.TemporaryDirectory(prefix='stego_bpg_') as directory:
            source = Path(directory) / 'input.bpg'
            output = Path(directory) / 'output.png'
            shutil.copyfile(path, source)
            result = subprocess.run([str(decoder), '-o', str(output), str(source)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode or not output.is_file():
                raise ValueError('BPG 图片解码失败，文件可能损坏或格式不受支持。')
            from PIL import Image
            import numpy as np
            with Image.open(output) as image:
                return np.array(image.convert('RGBA'), dtype=np.uint8)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError('BPG 图片解码失败，无法启动解码器或解码超时。') from error
