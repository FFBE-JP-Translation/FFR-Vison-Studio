"""Protect byte fidelity and shared-cache publication under actual processes."""
import hashlib
import json
import multiprocessing
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ffbe_effect_bundle as effects
from ffbe_effects.conversion_io import file_lock


def compress_worker(folder):
    effects.COMPRESSION_CACHE=Path(folder)
    original=zlib.compress
    def tracked(raw,level):
        with (Path(folder)/'compressions.txt').open('a') as stream: stream.write('compressed\n')
        return original(raw,level)
    effects.zlib.compress=tracked
    _,data=effects._compress_page(bytes(range(256))*8192,{})
    assert zlib.decompress(data)==bytes(range(256))*8192


def hold_lock(path,ready):
    import time
    with file_lock(path):
        ready.set()
        time.sleep(60)


class Acceleration(unittest.TestCase):
    def test_parallel_workers_compress_shared_page_once(self):
        with tempfile.TemporaryDirectory() as folder:
            context=multiprocessing.get_context('spawn')
            workers=[context.Process(target=compress_worker,args=(folder,)) for _ in range(3)]
            for worker in workers: worker.start()
            for worker in workers:
                worker.join(20)
                if worker.is_alive(): worker.terminate(); worker.join(); self.fail('compression cache deadlocked')
                self.assertEqual(worker.exitcode,0)
            self.assertEqual((Path(folder)/'compressions.txt').read_text().splitlines(),['compressed'])

    def test_corrupt_cached_bytes_are_rebuilt_losslessly(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(effects,'COMPRESSION_CACHE',Path(folder)):
            raw=b'test pixels'*1000
            key,data=effects._compress_page(raw,{})
            self.assertEqual(data,zlib.compress(raw,9))
            target=Path(folder)/('zlib9-'+key+'.z')
            for corrupt in (b'broken',zlib.compress(b'wrong'),data+b'trailing',data[:-2]):
                target.write_bytes(corrupt)
                self.assertEqual(effects._compress_page(raw,{})[1],data)
            with patch.object(effects.zlib,'compress',side_effect=AssertionError('cache should be reused')):
                self.assertEqual(effects._compress_page(raw,{})[1],data)

    def test_abandoned_process_lock_is_released(self):
        with tempfile.TemporaryDirectory() as folder:
            context=multiprocessing.get_context('spawn')
            ready=context.Event()
            path=str(Path(folder)/'asset.lock')
            worker=context.Process(target=hold_lock,args=(path,ready));worker.start()
            try: self.assertTrue(ready.wait(10))
            finally: worker.terminate();worker.join(10)
            with file_lock(path): pass

    def test_precompressed_zip_entries_preserve_all_extracted_bytes(self):
        import zipfile
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'bundle.zip'
            files={'atlas.bgra.z':zlib.compress(b'pixels'*1000,9),'spec.json':b'{"frames":20}'}
            effects._write_archive(target,files)
            with zipfile.ZipFile(target) as archive:
                self.assertEqual({n:archive.read(n) for n in archive.namelist()},files)
                self.assertEqual(archive.getinfo('atlas.bgra.z').compress_type,zipfile.ZIP_STORED)
                self.assertEqual(archive.getinfo('spec.json').compress_type,zipfile.ZIP_DEFLATED)


if __name__=='__main__':unittest.main()
