import errno
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import native_acl_observation as acl


class ACLTests(unittest.TestCase):
    def test_bounded_numeric_schema(self):
        raw=struct.pack('<I',2)+b''.join(struct.pack('<HHI',tag,7,0xffffffff) for tag in (1,4,32))
        self.assertEqual([e['tag'] for e in acl.decode_acl(raw)['entries']], ['owner','group-owner','other'])
        for bad in (b'', struct.pack('<I',1), raw+b'x', b'x'*4097, struct.pack('<IHHI',2,99,7,0xffffffff)):
            with self.assertRaises(ValueError): acl.decode_acl(bad)

    def test_absence_unsupported_and_failure(self):
        for code,status in ((errno.ENODATA,'absent'),(errno.EOPNOTSUPP,'unsupported'),(errno.ENOENT,'object-absent')):
            with patch.object(os,'getxattr',side_effect=OSError(code,'unlogged')):
                self.assertEqual(acl.snapshot('/approved'),{'access':{'status':status},'default':{'status':status}})
        with patch.object(os,'getxattr',side_effect=OSError(errno.EACCES,'unlogged')):
            with self.assertRaises(ValueError): acl.snapshot('/approved')

    def test_real_private_acl_mode_restore(self):
        with tempfile.TemporaryDirectory(prefix='awf-acl-metadata-',dir=Path(__file__).resolve().parent.parent) as d:
            path=Path(d)/'parent';path.mkdir(mode=0o777);path.chmod(0o777)
            raw=struct.pack('<I',2)+b''.join(struct.pack('<HHI',tag,7,0xffffffff) for tag in (1,4,32))
            os.setxattr(path,'system.posix_acl_default',raw,follow_symlinks=False)
            before=acl.snapshot(path);path.chmod(0o755)
            self.assertEqual(acl.snapshot(path)['default'],before['default'])
            path.chmod(0o777);self.assertEqual(acl.snapshot(path),before)
            child=path/'child';child.mkdir(mode=0o700)
            self.assertEqual(acl.snapshot(child)['default'],before['default'])

    def test_named_access_mask_restore(self):
        with tempfile.TemporaryDirectory(prefix='awf-access-metadata-',dir=Path(__file__).resolve().parent.parent) as d:
            path=Path(d)/'parent';path.mkdir(mode=0o700)
            raw=struct.pack('<I',2)+b''.join(struct.pack('<HHI',tag,7,identifier) for tag,identifier in ((1,0xffffffff),(2,os.geteuid()),(4,0xffffffff),(16,0xffffffff),(32,0xffffffff)))
            os.setxattr(path,'system.posix_acl_access',raw,follow_symlinks=False)
            before=acl.snapshot(path);path.chmod(0o755)
            self.assertEqual(acl.snapshot(path),acl.after_chmod(before,0o755))
            path.chmod(0o777);self.assertEqual(acl.snapshot(path),before)


if __name__=='__main__': unittest.main()
