import tempfile
import unittest
from pathlib import Path
from core import load_image


class BpgImportTest(unittest.TestCase):
    def test_import_real_bpg_and_preserve_source(self):
        path = Path(__file__).parent / 'fixtures' / 'sample.bpg'
        original = path.read_bytes()
        image = load_image(path)
        self.assertEqual(image.shape, (64, 64, 4))
        self.assertEqual(tuple(image[0, 0]), (255, 0, 0, 128))
        self.assertEqual(path.read_bytes(), original)

    def test_invalid_bpg_has_specific_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'invalid.bpg'
            path.write_bytes(b'not a bpg')
            with self.assertRaisesRegex(ValueError, 'BPG'):
                load_image(path)
