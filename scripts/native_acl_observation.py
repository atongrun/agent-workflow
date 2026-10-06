"""Bounded numeric ACL observations; never set or remove any ACL."""
import errno
import copy
import os
import struct

MAX_ACL_BYTES = 4096
TAGS = {1: 'owner', 2: 'user', 4: 'group-owner', 8: 'group', 16: 'mask', 32: 'other'}


def decode_acl(data):
    if len(data) < 4 or len(data) > MAX_ACL_BYTES or (len(data)-4) % 8 or struct.unpack_from('<I', data)[0] != 2:
        raise ValueError('acl_schema')
    entries = []
    for offset in range(4, len(data), 8):
        tag, permissions, identifier = struct.unpack_from('<HHI', data, offset)
        if tag not in TAGS or permissions > 7:
            raise ValueError('acl_schema')
        entries.append(dict(tag=TAGS[tag], permissions=permissions,
                            id=identifier if tag in (2, 8) else None))
    return dict(status='present', entries=entries)


def snapshot(target):
    result = {}
    for kind in ('access', 'default'):
        try:
            data = os.getxattr(target, 'system.posix_acl_'+kind) if isinstance(target, int) else os.getxattr(target, 'system.posix_acl_'+kind, follow_symlinks=False)
            result[kind] = decode_acl(data)
        except OSError as error:
            if error.errno == errno.ENODATA:
                result[kind] = dict(status='absent')
            elif error.errno in (errno.ENOTSUP, errno.EOPNOTSUPP):
                result[kind] = dict(status='unsupported')
            elif error.errno == errno.ENOENT:
                result[kind] = dict(status='object-absent')
            else:
                raise ValueError('acl_observation_unavailable') from None
    return result


def after_chmod(original, mode):
    expected = copy.deepcopy(original)
    access = expected['access']
    if access['status'] == 'present':
        has_mask = any(e['tag'] == 'mask' for e in access['entries'])
        permissions = {'owner': (mode >> 6) & 7, 'other': mode & 7,
                       'mask' if has_mask else 'group-owner': (mode >> 3) & 7}
        for entry in access['entries']:
            if entry['tag'] in permissions:
                entry['permissions'] = permissions[entry['tag']]
    return expected


PARENTS = ('/', '/opt', '/usr', '/usr/local', '/usr/local/bin')
PI_CHAIN = ('/opt/pi-cli', '/opt/pi-cli/lib', '/opt/pi-cli/lib/node_modules',
            '/opt/pi-cli/lib/node_modules/@earendil-works',
            '/opt/pi-cli/lib/node_modules/@earendil-works/pi-coding-agent')


def collect():
    rows = []
    for name in PARENTS+PI_CHAIN:
        try:
            rows.append(dict(path=name, acl=snapshot(name)))
        except (OSError, ValueError):
            rows.append(dict(path=name, observationUnavailable='acl_observation_unavailable'))
    return rows
