import unittest
import numpy as np
from core import scan_lsb_conditional, extract_bits

class ConditionalTests(unittest.TestCase):
    def test_all_orders_and_alignment(self):
        image=np.zeros((40,40,4),dtype=np.uint8)
        payload=b'ctfshow{permutation}'
        data=np.concatenate([np.array([1,0,1],dtype=np.uint8),np.unpackbits(np.frombuffer(payload,dtype=np.uint8))])
        seq=[(c,b) for c in (1,0) for b in (4,2,1)]
        for i,v in enumerate(data):
            pix,j=divmod(i,len(seq)); c,b=seq[j]; image[pix//40,pix%40,c] |= int(v)<<b
        hits=scan_lsb_conditional(image,(0,1),(1,2,4),(False,),alignments=True)
        hit=next(x for x in hits if x['channels']==(1,0) and x['bits']==(4,2,1) and x['skip_bits']==3 and not x['little'])
        self.assertTrue(extract_bits(image,hit['channels'],hit['bits'],bit_offset=hit['skip_bits']).startswith(payload))
    def test_large_combinations_rejected(self):
        with self.assertRaises(ValueError): scan_lsb_conditional(np.zeros((1,1,4),dtype=np.uint8),tuple(range(4)),tuple(range(8)))

if __name__=='__main__': unittest.main()
