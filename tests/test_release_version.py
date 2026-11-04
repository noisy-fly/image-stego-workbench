import unittest
from release_version import version_from_tag


class ReleaseVersionTests(unittest.TestCase):
    def test_versions(self):
        self.assertEqual(version_from_tag('v1.2.3'), '1.2.3')
        self.assertEqual(version_from_tag('v0.2.0-rc.1'), '0.2.0')

    def test_invalid_versions_are_rejected(self):
        for tag in ('main', 'v1.2', 'v1.2.3;bad', 'v1.2.3-', '1.2.3'):
            with self.subTest(tag=tag), self.assertRaises(ValueError): version_from_tag(tag)


if __name__ == '__main__': unittest.main()
