import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import urllib.request

script = Path(__file__).with_name('install-linux.sh').read_text()
source = script.split("<<'AWF_BOOTSTRAP_PY'\n", 1)[1].rsplit('\nAWF_BOOTSTRAP_PY', 1)[0]
api = {'__name__': 'bootstrap_fixture'}
exec(compile(source, 'install-linux.sh', 'exec'), api)

class BootstrapTests(unittest.TestCase):
    def fixture(self):
        version = 'v1.0.0-rc.9'
        return {'schema': 1, 'installerProtocol': 1, 'channel': 'linux-host-v1', 'version': version, 'sourceCommit': 'a' * 40, 'os': 'linux', 'arch': 'amd64', 'libc': 'glibc', 'components': [{'id': 'awf-host', 'version': version, 'artifacts': [{'name': 'awf_' + version + '_linux_amd64.tar.gz', 'url': 'https://github.com/atongrun/agent-workflow/releases/download/' + version + '/awf_' + version + '_linux_amd64.tar.gz', 'format': 'tar.gz', 'sha256': 'b' * 64, 'bytes': 123}]}]}

    def test_exact_publisher_metadata_and_duplicate_rejection(self):
        manifest = self.fixture()
        self.assertEqual(api['select_host'](json.dumps(manifest).encode())[0], manifest)
        with self.assertRaises(ValueError):
            api['select_host'](b'{"schema":1,"schema":1}')
        for field, value in [('url', 'https://example.com/installer'), ('bytes', True), ('sha256', 'guessed')]:
            malformed = self.fixture()
            malformed['components'][0]['artifacts'][0][field] = value
            with self.assertRaises(ValueError):
                api['select_host'](json.dumps(malformed).encode())

    def test_official_asset_redirect_boundary(self):
        handler = api['Redirects']()
        request = urllib.request.Request('https://github.com/atongrun/agent-workflow/releases/download/v1.0.0/awf.tar.gz')
        target = 'https://release-assets.githubusercontent.com/asset?official-signature=fixture'
        self.assertEqual(handler.redirect_request(request, None, 302, '', {}, target).full_url, target)
        for target in ('http://release-assets.githubusercontent.com/asset', 'https://release-assets.githubusercontent.com:444/asset', 'https://:password@release-assets.githubusercontent.com/asset', 'https://example.com/asset'):
            with self.assertRaises(ValueError):
                handler.redirect_request(request, None, 302, '', {}, target)

    def test_safe_extraction_and_identity(self):
        manifest = self.fixture()
        header = bytearray(64)
        header[:6] = b'\x7fELF\x02\x01'
        header[18:20] = b'\x3e\x00'
        identity = {k: manifest[k] for k in ('version', 'sourceCommit', 'os', 'arch')}
        identity.update(schema=1, hostProtocol='v1')
        for bad in ('valid', 'traversal', 'symlink', 'extra', 'duplicate', 'wrong-identity'):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as work:
                directory = Path(work)
                archive = directory / 'fixture.tar.gz'
                with tarfile.open(archive, 'w:gz', format=tarfile.USTAR_FORMAT) as tree:
                    rows = [('awf', bytes(header)), ('build.json', json.dumps(identity if bad != 'wrong-identity' else {}).encode())]
                    if bad == 'traversal': rows.append(('../escape', b'bad'))
                    if bad == 'extra': rows.append(('extra', b'bad'))
                    if bad == 'duplicate': rows.append(rows[0])
                    for name, data in rows:
                        entry = tarfile.TarInfo(name)
                        entry.size = len(data)
                        if bad == 'symlink' and name == 'awf':
                            entry.type = tarfile.SYMTYPE
                            entry.linkname = '/etc/passwd'
                        tree.addfile(entry, io.BytesIO(data))
                if bad == 'valid':
                    self.assertEqual(api['extract_host'](archive, directory, manifest), directory / 'awf')
                else:
                    with self.assertRaises(ValueError):
                        api['extract_host'](archive, directory, manifest)
                self.assertFalse((directory.parent / 'escape').exists())

if __name__ == '__main__':
    unittest.main()
