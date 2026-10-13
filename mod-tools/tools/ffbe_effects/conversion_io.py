"""Process-safe offline caches. Locks are released by the OS after interruption."""
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
import time


@contextmanager
def file_lock(path, *, blocking=True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            if stream.seek(0, 2) == 0:
                stream.write(b'\0'); stream.flush()
            while True:
                try:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as error:
                    if error.errno not in (13, 11, 36): raise
                    if not blocking: raise RuntimeError('Another conversion already owns '+str(path)) from error
                    time.sleep(.1)
            try: yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError as error:
                raise RuntimeError('Another conversion already owns '+str(path)) from error
            try: yield
            finally: fcntl.flock(stream, fcntl.LOCK_UN)


def atomic_bytes(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def atomic_png(image, path):
    import io
    data = io.BytesIO()
    image.save(data, format='PNG')
    atomic_bytes(path, data.getvalue())
