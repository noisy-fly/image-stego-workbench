import base64
import io
import tarfile
import tempfile
import unittest
import zipfile
import os
from unittest.mock import patch
from pathlib import Path
from fractions import Fraction
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

    def test_last_frames_and_seconds_and_track_duration(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'two.mkv'
            with av.open(str(source), 'w') as container:
                one = container.add_stream('ffv1', rate=10); two = container.add_stream('ffv1', rate=10)
                for stream in (one, two): stream.width = 8; stream.height = 8; stream.pix_fmt = 'bgr0'
                for i in range(8):
                    for stream, limit in ((one, 8), (two, 4)):
                        if i >= limit: continue
                        frame = av.VideoFrame.from_ndarray(np.full((8,8,3), i*20, dtype=np.uint8), format='rgb24')
                        for packet in stream.encode(frame): container.mux(packet)
                for stream in (one, two):
                    for packet in stream.encode(): container.mux(packet)
            tracks = inspect_source(source)
            self.assertAlmostEqual(tracks[0]['duration'], 0.8, places=2)
            self.assertAlmostEqual(tracks[1]['duration'], 0.4, places=2)
            result = extract_groups(source, 'video', tracks[1]['index'], temp, count=2, group_size=2, end_mode='frames')
            values = [Image.open(p).convert('RGB').getpixel((0,0))[0] for p in result['groups'][0]]
            self.assertEqual(values, [40, 60])
            result = extract_groups(source, 'video', tracks[1]['index'], temp, count=10, group_size=10, end_mode='seconds', end_seconds=0.2)
            values = [Image.open(p).convert('RGB').getpixel((0,0))[0] for p in result['groups'][0]]
            self.assertEqual(values, [40, 60])
            truncated = extract_groups(source, 'video', tracks[1]['index'], temp, count=1, group_size=1, end_mode='seconds', end_seconds=0.2)
            self.assertTrue(truncated['truncated'])

    def test_video_track_duration_does_not_trust_container_fallback(self):
        from extract_sources import track_timing
        class Stream:
            metadata = {}; time_base = 0.001; duration = 10000; start_time = None
        info = track_timing(Stream(), container_duration=10.0)
        self.assertIsNone(info['duration'])
        self.assertEqual(info['container_duration'], 10.0)

    def test_last_seconds_uses_timestamps_not_nominal_fps(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'variable.mkv'
            with av.open(str(source), 'w') as container:
                stream = container.add_stream('ffv1', rate=10)
                stream.width = 8; stream.height = 8; stream.pix_fmt = 'bgr0'
                for pts in (0, 1, 3, 7):
                    frame = av.VideoFrame.from_ndarray(np.full((8,8,3), pts*20, dtype=np.uint8), format='rgb24')
                    frame.pts = pts; frame.time_base = Fraction(1, 10)
                    for packet in stream.encode(frame): container.mux(packet)
                for packet in stream.encode(): container.mux(packet)
            track = inspect_source(source)[0]
            result = extract_groups(source, 'video', track['index'], temp, count=10, group_size=10, end_mode='seconds', end_seconds=0.3)
            values = [Image.open(p).convert('RGB').getpixel((0,0))[0] for p in result['groups'][0]]
            self.assertEqual(values, [140])

    def test_dialog_shows_selected_track_duration_and_tail_controls(self):
        app = QApplication.instance() or QApplication([])
        owner = Main(); dialog = ExtractDialog(owner)
        tracks = [
            {'kind':'video','index':0,'label':'主轨','duration':1039.349,'end_time':1039.349,'timing_source':'轨道元数据','container_duration':1039.371},
            {'kind':'video','index':2,'label':'第二轨','duration':1030.967,'end_time':1030.967,'timing_source':'轨道元数据','container_duration':1039.371},
        ]
        with patch('extract_dialog.inspect_source', return_value=tracks): dialog.set_source('example.mkv')
        dialog.tracks.setCurrentIndex(1)
        self.assertIn('00:17:10.967', dialog.track_info.text())
        self.assertIn('00:17:19.371', dialog.track_info.text())
        dialog.mode.setCurrentIndex(1)
        self.assertFalse(dialog.start_time.isEnabled()); self.assertFalse(dialog.start.isEnabled())
        dialog.mode.setCurrentIndex(2); self.assertTrue(dialog.end_seconds.isEnabled())
        dialog.close(); owner.close(); app.processEvents()

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
