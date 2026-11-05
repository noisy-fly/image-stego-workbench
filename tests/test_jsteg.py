import os
import shutil
import subprocess
import tempfile
from unittest.mock import patch
import unittest
from pathlib import Path
from PIL import Image
from file_inspection import source_reference
from jsteg_extract import reveal_jsteg, save_payload

class JstegTests(unittest.TestCase):
    def test_synthetic_binary_payload_and_no_modification(self):
        path=Path(__file__).resolve().parent.parent/'vendor'/'jsteg'/'sample.jpg'
        original=path.read_bytes(); result=reveal_jsteg(source_reference(path))
        self.assertEqual(result, b'demo{sample}\x00\xffbinary')
        self.assertEqual(path.read_bytes(), original)

    def test_plain_jpeg_invalid_format_and_changed_source(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'normal.jpg'; Image.new('RGB',(32,32),'white').save(p)
            ref=source_reference(p)
            with self.assertRaisesRegex(ValueError, '未发现'): reveal_jsteg(ref)
            p.write_bytes(b'not JPEG')
            with self.assertRaises(ValueError): reveal_jsteg(ref)
            with self.assertRaisesRegex(ValueError, 'JPEG'): reveal_jsteg(source_reference(p))
            with self.assertRaises(ValueError): reveal_jsteg(None)
            progressive=Path(d)/'progressive.jpg'; Image.new('RGB',(32,32),'white').save(progressive, progressive=True)
            with self.assertRaisesRegex(ValueError, '渐进式'): reveal_jsteg(source_reference(progressive))

    def test_detects_source_change_during_extraction(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'copy.jpg'
            shutil.copyfile(Path(__file__).resolve().parent.parent/'vendor'/'jsteg'/'sample.jpg', p)
            reference=source_reference(p); real_popen=subprocess.Popen
            def start_then_change(*args, **kwargs):
                process=real_popen(*args, **kwargs)
                stamp=p.stat().st_mtime_ns + 2_000_000_000
                os.utime(p, ns=(stamp, stamp))
                return process
            with patch('jsteg_extract.subprocess.Popen', side_effect=start_then_change):
                with self.assertRaisesRegex(ValueError, '变化'): reveal_jsteg(reference)

    def test_save_cannot_overwrite_source_or_hardlink(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'source.jpg'; p.write_bytes(b'original'); ref=source_reference(p)
            with self.assertRaises(ValueError): save_payload(ref,b'hello',p)
            link=Path(d)/'link.jpg'; __import__('os').link(p,link)
            with self.assertRaises(ValueError): save_payload(ref,b'hello',link)
            target=Path(d)/'output.bin'; save_payload(ref,b'\x00\xff',target)
            self.assertEqual(target.read_bytes(),b'\x00\xff'); self.assertEqual(p.read_bytes(),b'original')
