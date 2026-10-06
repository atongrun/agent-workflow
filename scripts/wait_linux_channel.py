#!/usr/bin/env python3
"""Read-only readiness gate for the approved Linux channel, at most ten minutes."""
import hashlib
import time
from urllib.error import HTTPError
import urllib.request

URL='https://raw.githubusercontent.com/atongrun/agent-workflow/awf/linux-v1/distribution/linux-host-v1.json'
SIZE=2737
SHA256='1e431c185859664aecf5d6f04a560dd67ac8137a4f2a7b05c0784aa4c86d31d5'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args):
        raise ValueError('channel redirect refused')


def ready(opener,timeout=15):
    try:
        with opener.open(URL,timeout=timeout) as response:
            data=response.read(SIZE+1)
            if len(data)!=SIZE or hashlib.sha256(data).hexdigest()!=SHA256:
                raise ValueError('published channel differs from the approved immutable RC3 manifest')
        return True
    except HTTPError as error:
        if error.code==404:
            return False
        raise


def main():
    opener=urllib.request.build_opener(NoRedirect())
    deadline=time.monotonic()+600
    print('AWF default phase: waiting for separately verified channel promotion',flush=True)
    while True:
        remaining=deadline-time.monotonic()
        if remaining<=0:
            break
        if ready(opener,min(15,remaining)):
            if time.monotonic()>deadline:
                break
            print('AWF default phase: exact RC3 public channel verified',flush=True)
            return
        remaining=deadline-time.monotonic()
        if remaining<=0:
            break
        time.sleep(min(5,remaining))
    raise RuntimeError('channel readiness timeout; default phase not executed')


if __name__=='__main__':
    main()
