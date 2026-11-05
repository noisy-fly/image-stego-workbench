import tempfile,unittest,zipfile,io,struct
from pathlib import Path
from PIL import Image
from bmp_repair import bmp_height_candidate,bmp_with_height
from file_inspection import inspect_file,source_reference

class NewTests(unittest.TestCase):
 def test_bmp_candidate(self):
  with tempfile.TemporaryDirectory() as temp:
   p=Path(temp)/'a.bmp'; Image.new('RGB',(30,50)).save(p); b=bytearray(p.read_bytes()); struct.pack_into('<i',b,22,20); p.write_bytes(b)
   self.assertEqual(bmp_height_candidate(p),(20,50,0)); self.assertEqual(Image.open(io.BytesIO(bmp_with_height(p,50))).size,(30,50)); self.assertEqual(p.read_bytes(),b)
 def test_zip_corrupt_header(self):
  with tempfile.TemporaryDirectory() as temp:
   p=Path(temp)/'a.png'; Image.new('RGB',(4,4)).save(p); prefix=p.read_bytes(); out=io.BytesIO()
   with zipfile.ZipFile(out,'w') as z:z.writestr('a.txt','hello')
   archive=bytearray(out.getvalue()); archive[:4]=b'XXXX'; p.write_bytes(prefix+archive)
   found=inspect_file(source_reference(p))['candidates']; self.assertTrue(any(x['kind']=='原始图片' for x in found)); self.assertTrue(any(x.get('directory_valid') and x['offset']==len(prefix) for x in found))

if __name__=='__main__':unittest.main()
