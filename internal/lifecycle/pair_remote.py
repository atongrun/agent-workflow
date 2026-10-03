# Fixed, bounded AWF pairing receiver. No data from stdin is evaluated as code.
import hashlib, hmac, json, os, re, stat, sys

def run():
    raw = sys.stdin.buffer.read(4097)
    if len(raw) > 4096:
        raise ValueError()
    q = json.loads(raw)
    if set(q) - {'op', 'path', 'challenge', 'token'} or q.get('op') not in ('inspect', 'create'):
        raise ValueError()
    p, challenge = q.get('path', ''), q.get('challenge', '')
    if not isinstance(p, str) or not re.fullmatch(r'/[A-Za-z0-9._/-]{1,1023}', p):
        raise ValueError()
    parts = p.split('/')[1:]
    if any(x in ('', '.', '..') for x in parts) or not re.fullmatch(r'[0-9a-f]{64}', challenge):
        raise ValueError()
    token = q.get('token', '')
    if q['op'] == 'create' and not re.fullmatch(r'[0-9A-F]{64}', token):
        raise ValueError()
    if q['op'] == 'inspect' and token:
        raise ValueError()
    # Traverse using directory handles and O_NOFOLLOW. The destination parent
    # must already exist and be private to the authenticated SSH user.
    parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        st = os.fstat(parent)
        if st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) & 0o077:
            raise ValueError()
        if q['op'] == 'create':
            # Never truncate, replace, chmod, or follow an existing destination.
            # Interrupted writes are retained for explicit operator recovery.
            try:
                fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            except FileExistsError:
                return {'state': 'exists'}
            try:
                os.fchmod(fd, 0o600)
                data = ('AWF_WINDOWS_TOKEN=' + token + '\n').encode('ascii')
                while data:
                    n = os.write(fd, data)
                    if n <= 0:
                        raise OSError()
                    data = data[n:]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(parent)
        try:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        except FileNotFoundError:
            return {'state': 'missing'}
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) != 0o600 or st.st_nlink != 1 or st.st_size > 128:
                raise ValueError()
            data = os.read(fd, 129)
        finally:
            os.close(fd)
        if not re.fullmatch(b'AWF_WINDOWS_TOKEN=[0-9A-F]{64}\n', data):
            raise ValueError()
        key = data[len(b'AWF_WINDOWS_TOKEN='):-1]
        proof = hmac.new(key, challenge.encode('ascii'), hashlib.sha256).hexdigest()
        return {'state': 'present', 'proof': proof}
    finally:
        os.close(parent)

try:
    result = run()
except Exception:
    result = {'state': 'unknown'}
sys.stdout.write(json.dumps(result, separators=(',', ':')) + '\n')
