import io
import tempfile
import unittest
from pathlib import Path
from PIL import Image, PngImagePlugin
from file_inspection import source_reference
from basic_search import search_basic


class BasicSearchTests(unittest.TestCase):
    def test_bytes_cross_blocks_and_encodings(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'x.bin'
            p.write_bytes(b'\x00' * 13 + b'ctfshow{hello_123}' + b'\x00' + 'team{wide}'.encode('utf-16le') + b'\x00' + 'abc{big}'.encode('utf-16be'))
            result = search_basic(source_reference(p), chunk_size=16)
            self.assertTrue({('ctfshow{hello_123}', 13), ('team{wide}', 31), ('abc{big}', 53)} <= {(x['text'], x['offset']) for x in result['matches']})

    def test_compressed_png_text(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'x.png'
            meta = PngImagePlugin.PngInfo(); meta.add_text('Comment', 'flag{compressed_metadata}', zip=True)
            Image.new('RGB', (3, 3)).save(p, pnginfo=meta)
            result = search_basic(source_reference(p), chunk_size=32)
            self.assertTrue(any(x['text'] == 'flag{compressed_metadata}' and x['offset'] is None for x in result['matches']))

    def test_source_changed_and_no_reference(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'x'; p.write_bytes(b'one'); ref = source_reference(p); p.write_bytes(b'two more')
            with self.assertRaises(ValueError): search_basic(ref)
            with self.assertRaises(ValueError): search_basic(None)
