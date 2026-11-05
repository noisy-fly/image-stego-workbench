import io
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from PIL import Image
from file_inspection import source_reference, inspect_file, save_candidate


def png():
    output = io.BytesIO(); Image.new('RGB', (4, 3), 'white').save(output, format='PNG'); return output.getvalue()


def zipped():
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive: archive.writestr('inside.txt', b'hello')
    return output.getvalue()


class FileInspectionTests(unittest.TestCase):
    def test_png_appended_zip_and_safe_export(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'carrier.png'; original = png(); payload = zipped(); path.write_bytes(original + payload)
            ref = source_reference(path); result = inspect_file(ref, chunk_size=7)
            self.assertEqual(result['image_end'], len(original))
            hit = next(x for x in result['candidates'] if x['kind'] == 'ZIP')
            self.assertEqual(hit['offset'], len(original)); self.assertEqual(hit['location'], 'trailing')
            self.assertTrue(hit['verified']); self.assertEqual(hit['members'], ['inside.txt'])
            target = Path(temp) / 'payload.zip'; save_candidate(ref, hit['offset'], target)
            self.assertEqual(target.read_bytes(), payload)
            with self.assertRaises(ValueError): save_candidate(ref, hit['offset'], path)
            self.assertEqual(path.read_bytes(), original + payload)

    def test_other_file_signature_and_png_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'carrier.png'; original = png(); path.write_bytes(original + b'abc%PDF-1.4\n')
            result = inspect_file(source_reference(path))
            hit = next(x for x in result['candidates'] if x['kind'] == 'PDF')
            self.assertEqual(hit['offset'], len(original) + 3); self.assertFalse(hit['verified'])

    def test_jpeg_and_gif_tail_boundaries(self):
        with tempfile.TemporaryDirectory() as temp:
            for kind, ext in [('JPEG', 'jpg'), ('GIF', 'gif')]:
                data = io.BytesIO(); Image.new('RGB', (8,8), 'blue').save(data, format=kind)
                original = data.getvalue(); path = Path(temp) / ('carrier.' + ext)
                path.write_bytes(original + zipped())
                result = inspect_file(source_reference(path))
                self.assertEqual(result['image_end'], len(original))
                self.assertEqual(next(x for x in result['candidates'] if x['kind'] == 'ZIP')['location'], 'trailing')

    def test_no_false_image_end_in_data_and_bad_png(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'bad.png'
            path.write_bytes(b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 100) + b'IDAT' + b'IEND\xaeB`\x82')
            result = inspect_file(source_reference(path)); self.assertIsNone(result['image_end'])

    def test_changed_file_and_absent_source(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'carrier.png'; path.write_bytes(png()); ref = source_reference(path)
            path.write_bytes(png() + b'changed')
            with self.assertRaises(ValueError): inspect_file(ref)
            with self.assertRaises(ValueError): inspect_file(None)


if __name__ == '__main__': unittest.main()
