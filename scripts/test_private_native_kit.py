import hashlib
from pathlib import Path
import stat
import tempfile
import unittest
import warnings
import zipfile

import private_native_kit as kit


class PrivateKitTests(unittest.TestCase):
    def write(self, source, additional=(), mode=None):
        names = ['kit.json', 'tools/awf', 'tools/native-acceptance.test', 'input/manifest.json', 'input/stage/stage.json']
        with warnings.catch_warnings(), zipfile.ZipFile(source, 'w') as stream:
            warnings.simplefilter('ignore', UserWarning)
            for name in names + list(additional):
                entry = zipfile.ZipInfo(name)
                entry.create_system = 3
                entry.external_attr = (mode if mode is not None else stat.S_IFREG | (0o700 if name.startswith('tools/') else 0o600)) << 16
                stream.writestr(entry, b'private fixture')
        source.chmod(0o600)
        return hashlib.sha256(source.read_bytes()).hexdigest()

    def test_approved_bytes_and_private_modes(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as temporary:
            parent = Path(temporary)
            source, destination = parent / 'input.zip', parent / 'unpack'
            digest = self.write(source)
            kit.extract(source, destination, digest)
            for path in destination.rglob('*'):
                expected = 0o700 if path.is_dir() or path.parent.name == 'tools' else 0o600
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), expected)
            with self.assertRaises(ValueError):
                kit.extract(source, destination, digest)

    def test_refuses_unsafe_entries_before_creating_destination(self):
        for names in [('tools/awf',), ('../escape',), ('/etc/passwd',), ('input//manifest.json',), ('input/stage/pi/../escape',), ('input\\escape',), ('unreviewed.sh',), ('input/cache/_cacache/content-v2/ab', 'input/cache/_cacache/content-v2/ab/cd')]:
            with self.subTest(names=names), tempfile.TemporaryDirectory(dir='/tmp') as temporary:
                parent = Path(temporary)
                source, destination = parent / 'input.zip', parent / 'unpack'
                digest = self.write(source, names)
                with self.assertRaises(ValueError):
                    kit.extract(source, destination, digest)
                self.assertFalse(destination.exists())
        for mode in (stat.S_IFLNK | 0o600, stat.S_IFREG | 0o666, stat.S_IFREG | 0o4600, stat.S_IFIFO | 0o600):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(dir='/tmp') as temporary:
                parent = Path(temporary)
                source, destination = parent / 'input.zip', parent / 'unpack'
                digest = self.write(source, mode=mode)
                with self.assertRaises(ValueError):
                    kit.extract(source, destination, digest)
                self.assertFalse(destination.exists())

    def test_refuses_checksum_and_source_or_destination_links(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as temporary:
            parent = Path(temporary)
            source, destination = parent / 'input.zip', parent / 'unpack'
            digest = self.write(source)
            with self.assertRaises(ValueError):
                kit.extract(source, destination, '0' * 64)
            self.assertFalse(destination.exists())
            source.chmod(0o644)
            with self.assertRaises(ValueError):
                kit.extract(source, destination, digest)
            source.chmod(0o600)
            linked = parent / 'linked.zip'
            linked.symlink_to(source)
            with self.assertRaises(OSError):
                kit.extract(linked, destination, digest)
            linked_parent = parent / 'linked-parent'
            linked_parent.symlink_to(parent, target_is_directory=True)
            with self.assertRaises(ValueError):
                kit.extract(source, linked_parent / 'unpack', digest)
            self.assertFalse(destination.exists())

    def test_expansion_budget_is_enforced_before_writes(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as temporary:
            parent = Path(temporary)
            source, destination = parent / 'input.zip', parent / 'unpack'
            digest = self.write(source)
            previous = kit.MAX_BYTES
            try:
                kit.MAX_BYTES = source.stat().st_size  # compressed-size check passes
                with zipfile.ZipFile(source) as stream:
                    entry = stream.infolist()[0]
                    entry.file_size = kit.MAX_BYTES + 1
                    with self.assertRaises(ValueError):
                        kit.extract_entries(stream, destination)
                self.assertFalse(destination.exists())
            finally:
                kit.MAX_BYTES = previous


if __name__ == '__main__':
    unittest.main()
