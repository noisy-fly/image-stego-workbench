import base64
import io
import tarfile
import tempfile
import unittest
import zipfile
import os
from pathlib import Path
import av
import numpy as np
from PIL import Image
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from app import Main
from extract_dialog import ExtractDialog
from extract_sources import decode_embedded_image, inspect_source, extract_groups


def png_bytes(color):
    data = io.BytesIO()
    Image.new('RGB', (4, 3), color).save(data, format='PNG')
    return data.getvalue()


class ExtractSourceTests(unittest.TestCase):
    def test_subtitle_recognizes_hex_and_base64_without_treating_text_as_image(self):
        data = png_bytes('red')
        self.assertEqual(decode_embedded_image(data), (data, 'png'))
        self.assertEqual(decode_embedded_image(data.hex()), (data, 'png'))
        self.assertEqual(decode_embedded_image(base64.b64encode(data).decode()), (data, 'png'))
        self.assertIsNone(decode_embedded_image('这是一行普通字幕'))
        self.assertIsNone(decode_embedded_image('abcd'))

    def test_zip_sort_group_and_skip_non_image_without_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'input.zip'
            with zipfile.ZipFile(source, 'w') as archive:
                archive.writestr('folder/10.png', png_bytes('blue'))
                archive.writestr('../../2.png', png_bytes('red'))
                archive.writestr('1.png', png_bytes('green'))
                archive.writestr('notes.txt', b'not image')
            self.assertEqual(inspect_source(source)[0]['kind'], 'zip')
            result = extract_groups(source, 'zip', None, temp, start=0, count=3, group_size=2)
            self.assertEqual([len(g) for g in result['groups']], [2, 1])
            self.assertEqual(Image.open(result['groups'][0][0]).getpixel((0,0)), (0,128,0))
            self.assertEqual(Image.open(result['groups'][0][1]).getpixel((0,0)), (255,0,0))
            self.assertTrue(all(Path(p).resolve().is_relative_to(Path(result['directory']).resolve()) for group in result['groups'] for p in group))

    def test_tar_and_gif(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'images.tar'
            with tarfile.open(source, 'w') as archive:
                for i in range(3):
                    data = png_bytes((i, 0, 0)); info = tarfile.TarInfo(f'{i}.png'); info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
            result = extract_groups(source, 'tar', None, temp, start=1, count=2, group_size=1)
            self.assertEqual([len(g) for g in result['groups']], [1, 1])
            self.assertEqual(Image.open(result['groups'][0][0]).getpixel((0,0)), (1,0,0))
            gif = Path(temp) / 'frames.gif'
            frames = [Image.new('RGB', (4,3), color) for color in ('red','green','blue')]
            frames[0].save(gif, save_all=True, append_images=frames[1:], duration=100)
            result = extract_groups(gif, 'gif', None, temp, start=1, count=2, group_size=2)
            self.assertEqual(len(result['groups'][0]), 2)
            self.assertEqual(Image.open(result['groups'][0][0]).convert('RGB').getpixel((0,0)), (0,128,0))

    def test_cancel_cleans_only_new_output(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'input.zip'
            with zipfile.ZipFile(source, 'w') as archive: archive.writestr('a.png', png_bytes('red'))
            with self.assertRaises(InterruptedError):
                extract_groups(source, 'zip', None, temp, cancel=lambda: True)
            self.assertTrue(source.exists())
            self.assertEqual(list(Path(temp).glob('图片提取_*')), [])

    def test_extracts_400_items_into_two_groups(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'many.zip'; payload = png_bytes('red')
            with zipfile.ZipFile(source, 'w') as archive:
                for i in range(400): archive.writestr(f'{i:03}.png', payload)
            result = extract_groups(source, 'zip', None, temp, count=400, group_size=200)
            self.assertEqual([len(group) for group in result['groups']], [200, 200])
            self.assertEqual(Path(result['groups'][1][0]).name, '000200.png')

    def test_video_frames_start_and_group(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'frames.mkv'
            with av.open(str(source), 'w') as container:
                stream = container.add_stream('ffv1', rate=10)
                stream.width = 8; stream.height = 8; stream.pix_fmt = 'bgr0'
                for value in range(6):
                    pixels = np.full((8,8,3), value * 20, dtype=np.uint8)
                    for packet in stream.encode(av.VideoFrame.from_ndarray(pixels, format='rgb24')): container.mux(packet)
                for packet in stream.encode(): container.mux(packet)
            track = inspect_source(source)[0]
            result = extract_groups(source, 'video', track['index'], temp, start_time=0.2, start=1, count=3, group_size=2)
            self.assertEqual([len(g) for g in result['groups']], [2, 1])
            self.assertEqual(Image.open(result['groups'][0][0]).convert('RGB').getpixel((0,0)), (60,60,60))

    def test_dialog_extracts_and_imports_only_selected_group(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'input.zip'
            with zipfile.ZipFile(source, 'w') as archive:
                for i in range(3): archive.writestr(f'{i}.png', png_bytes((i, 0, 0)))
            owner = Main(); dialog = ExtractDialog(owner); dialog.set_source(str(source)); dialog.destination.setText(temp)
            dialog.count.setValue(3); dialog.group_size.setValue(2); dialog.start_extraction()
            self.assertIsNotNone(dialog.worker)
            loop = QEventLoop(); dialog.worker.finished.connect(loop.quit); QTimer.singleShot(10000, loop.quit); loop.exec()
            app.processEvents()
            self.assertIsNotNone(dialog.result)
            self.assertEqual(dialog.groups.count(), 2)
            dialog.groups.setCurrentIndex(1); dialog.import_group()
            self.assertEqual(len(owner.cards), 1)
            self.assertEqual(owner.cards[0].image[0,0,:3].tolist(), [2,0,0])
            dialog.close(); owner.close()


if __name__ == '__main__': unittest.main()
