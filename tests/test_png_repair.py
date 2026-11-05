import io
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from png_repair import repair_png_dimensions


def damaged_png(axis):
    out = io.BytesIO(); Image.new('RGBA', (23, 37), 'red').save(out, format='PNG')
    data = bytearray(out.getvalue()); start = 16 if axis == 'width' else 20
    data[start:start+4] = (7).to_bytes(4, 'big')
    return bytes(data)

class RepairTests(unittest.TestCase):
    def test_repair_one_dimension_preserves_everything_else(self):
        for axis in ('width', 'height'):
            data = damaged_png(axis) + b'payload'
            fixed, description = repair_png_dimensions(data)
            start = 16 if axis == 'width' else 20
            self.assertEqual(fixed[:start], data[:start]); self.assertEqual(fixed[start+4:], data[start+4:])
            self.assertIn('7', description)
            with Image.open(io.BytesIO(fixed)) as image:
                image.load(); self.assertEqual(image.size, (23, 37))

    def test_unknown_damage_is_not_repaired(self):
        out = io.BytesIO(); Image.new('RGB', (10, 10)).save(out, format='PNG')
        clean = out.getvalue(); self.assertIsNone(repair_png_dimensions(clean))
        bad = bytearray(clean); bad[24] = 0
        self.assertIsNone(repair_png_dimensions(bad))
        self.assertIsNone(repair_png_dimensions(b'not png'))

if __name__ == '__main__': unittest.main()
