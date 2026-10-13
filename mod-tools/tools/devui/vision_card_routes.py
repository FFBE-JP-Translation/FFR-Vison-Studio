"""Vision-card import jobs and lazy previews for the native Studio tab."""
import threading
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

import vision_cards

router = APIRouter(prefix='/api/vision-cards')
_lock = threading.Lock()
_jobs = {}


@router.get('')
def catalog():
    try:
        return vision_cards.catalog()
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(422, str(error)) from error


@router.post('/import')
async def import_cards(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(422, 'Import options must be an object.')
    metadata = body.get('metadataRoot')
    assets = body.get('assetRoots')
    if metadata is not None and not isinstance(metadata, str):
        raise HTTPException(422, 'Metadata folder must be a path.')
    if assets is not None and (not isinstance(assets, list) or any(not isinstance(p, str) for p in assets)):
        raise HTTPException(422, 'Artwork folders must be a list of paths.')
    with _lock:
        for key, value in _jobs.items():
            if value['state'] == 'running':
                return {'job': key}
        for key in list(_jobs)[:-8]:
            del _jobs[key]
        job = uuid.uuid4().hex
        status = {'state': 'running', 'stage': 'Reading card data', 'completed': 0, 'total': 0}
        _jobs[job] = status

    def update(**values):
        with _lock:
            status.update(values)

    def work():
        try:
            result = vision_cards.import_all(metadata, assets, progress=update)
            update(state='done', stage='Import complete', imported=result['imported'],
                   total=len(result['cards']), missingArt=result['missingArt'])
        except Exception as error:
            update(state='failed', stage='Import failed', error=str(error))
    threading.Thread(target=work, daemon=True).start()
    return {'job': job}


@router.get('/import/{job}')
def import_status(job: str):
    with _lock:
        if job not in _jobs:
            raise HTTPException(404, 'Import no longer active. Refresh the catalog.')
        return dict(_jobs[job])


@router.get('/{card_id}/art')
async def artwork(card_id: str, animated: bool = False):
    try:
        path = await run_in_threadpool(vision_cards.card_art, card_id, animated)
        return FileResponse(path, media_type='image/webp' if path.suffix == '.webp' else 'image/png')
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(404, str(error)) from error
