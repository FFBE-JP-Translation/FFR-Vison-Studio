"""Publish a complete JSON document without exposing a partial replacement."""
import json
import os
from pathlib import Path
import tempfile
import time


def write_json(path, document, **formatting):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.'+path.name+'.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='') as stream:
            json.dump(document, stream, **formatting)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(20):
            try:
                os.replace(temporary, path)
                break
            except PermissionError as error:
                # Windows readers/scanners can briefly deny delete sharing.
                # Keep the complete temporary file and retry the replacement.
                if getattr(error, 'winerror', None) not in (5, 32, 33) or attempt == 19:
                    raise
                time.sleep(min(.05 * 2**attempt, 1.0))
    finally:
        Path(temporary).unlink(missing_ok=True)
