import os
import subprocess
import sys
import unittest
from pathlib import Path


class SmokeTest(unittest.TestCase):
    def test_startup_self_check(self):
        env = os.environ.copy(); env['QT_QPA_PLATFORM'] = 'offscreen'
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parent.parent / 'app.py'), '--smoke-test'],
                                env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('SMOKE_OK', result.stdout)


if __name__ == '__main__': unittest.main()
