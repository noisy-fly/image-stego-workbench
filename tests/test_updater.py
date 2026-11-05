import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from updater import version_key, parse_release, should_prompt, download_installer, GitHubRedirect


class Response(io.BytesIO):
    def __init__(self, payload, url='https://github.com/noisy-fly/image-stego-workbench/releases/download/v0.3.0/StegoWorkbench-Setup.exe'):
        super().__init__(payload); self.url = url
    def geturl(self): return self.url


class UpdaterTests(unittest.TestCase):
    def release(self, payload=b'installer'):
        return {'tag_name':'v0.3.0','draft':False,'prerelease':False,'html_url':'https://github.com/noisy-fly/image-stego-workbench/releases/tag/v0.3.0',
                'assets':[{'name':'StegoWorkbench-Setup.exe','size':len(payload),'digest':'sha256:'+hashlib.sha256(payload).hexdigest(),
                           'browser_download_url':'https://github.com/noisy-fly/image-stego-workbench/releases/download/v0.3.0/StegoWorkbench-Setup.exe'}]}

    def test_versions(self):
        self.assertGreater(version_key('v0.10.0'), version_key('v0.9.9'))
        self.assertGreater(version_key('v0.3.0'), version_key('v0.3.0-rc.1'))
        self.assertGreater(version_key('v0.3.0-rc.10'), version_key('v0.3.0-rc.2'))
        with self.assertRaises(ValueError): version_key('latest')

    def test_ignore_only_exact_version_manual_bypasses(self):
        info = parse_release(self.release())
        self.assertFalse(should_prompt(info, '0.2.0', 'v0.3.0', manual=False))
        self.assertTrue(should_prompt(info, '0.2.0', 'v0.3.0', manual=True))
        self.assertTrue(should_prompt(info, '0.2.0', 'v0.2.9', manual=False))
        self.assertFalse(should_prompt(info, '0.3.0', '', manual=True))

    def test_release_rejects_untrusted_or_missing_checksum(self):
        release = self.release(); release['assets'][0]['browser_download_url'] = 'https://evil.example/a.exe'
        with self.assertRaises(ValueError): parse_release(release)
        release = self.release(); release['assets'][0]['digest'] = None
        with self.assertRaises(ValueError): parse_release(release)

    def test_download_hash_and_mismatch(self):
        payload = b'installer'; info = parse_release(self.release(payload))
        with tempfile.TemporaryDirectory() as temp, patch('updater.open_https', return_value=Response(payload)):
            self.assertEqual(Path(download_installer(info, temp)).read_bytes(), payload)
        with tempfile.TemporaryDirectory() as temp, patch('updater.open_https', return_value=Response(b'badbytes!')):
            with self.assertRaises(ValueError): download_installer(info, temp)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_download_cancellation_removes_partial_file(self):
        payload = b'installer'; info = parse_release(self.release(payload))
        with tempfile.TemporaryDirectory() as temp, patch('updater.open_https', return_value=Response(payload)):
            with self.assertRaises(InterruptedError): download_installer(info, temp, cancel=lambda: True)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_untrusted_redirect_is_rejected(self):
        with self.assertRaises(ValueError):
            GitHubRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.example/setup.exe')


if __name__ == '__main__': unittest.main()
