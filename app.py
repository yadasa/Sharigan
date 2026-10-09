"""Local Sharingan studio API. Inspection never starts inference."""
from datetime import datetime, timezone
from pathlib import Path
import json
import shutil
import tempfile
import threading
import uuid

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from config import ROOT
from studio import read_json, write_json, file_hash, readiness, media_info

RUNS = ROOT / 'runs'
RUNS.mkdir(exist_ok=True)
app = FastAPI()
jobs, hd_jobs = {}, {}
lock = threading.RLock()


def start_worker(target, *args):
    threading.Thread(target=target, args=args, daemon=True).start()


def now():
    return datetime.now(timezone.utc).isoformat()


def folder_for(ident):
    if len(ident) != 32 or any(c not in '0123456789abcdef' for c in ident):
        raise HTTPException(404, 'Transformation not found.')
    folder = RUNS / ident
    if not folder.is_dir():
        raise HTTPException(404, 'Transformation not found.')
    return folder


def record(folder, hd=False):
    registry = hd_jobs if hd else jobs
    state = dict(registry.get(folder.name, read_json(folder / ('hd/status.json' if hd else 'status.json'))))
    if state.get('state') == 'running' and folder.name not in registry:
        state.update(state='interrupted', status='Processing was interrupted. Inspect the saved task before starting again.')
    return state or {'id': folder.name, 'state': 'idle', 'status': 'Ready to prepare.'}


def update(folder, hd=False, **values):
    with lock:
        registry = hd_jobs if hd else jobs
        item = registry.setdefault(folder.name, record(folder, hd))
        previous = item.get('status')
        item.update(values, updated_at=now())
        if item.get('status') != previous:
            item.setdefault('events', []).append({'time': item['updated_at'], 'message': item['status'], 'stage': item.get('stage', '')})
            item['events'] = item['events'][-100:]
        target = folder / 'hd' if hd else folder
        target.mkdir(exist_ok=True)
        write_json(target / 'status.json', item)
        return dict(item)


def available(folder):
    if record(folder).get('state') == 'running' or record(folder, True).get('state') == 'running':
        raise HTTPException(409, 'This transformation is processing. Wait for it to finish.')


def unsubmitted(folder):
    if any((folder / name).exists() for name in ['seedance-request.json', 'seedance-response.json']):
        raise HTTPException(409, 'A draft submission was already attempted. Resume its saved task or start a new transformation.')


def check_preparation(mode):
    if mode not in ['depth', 'face_mesh', 'depth_mesh']:
        raise HTTPException(400, 'Unknown preparation mode.')
    configuration = readiness()
    if not configuration['modes'][mode]:
        missing = [c['label'] for c in configuration['checks'] if not c['ready'] and c['id'] in
                   ['python', 'packages', 'rubberband', 'REPLICATE_API_TOKEN'] + (['mesh'] if mode != 'depth' else [])]
        raise HTTPException(409, 'Preparation needs setup: ' + ', '.join(missing) + '. Open API configuration for instructions.')


def save_upload(upload, path, limit=200 * 1024 * 1024):
    size = 0
    with path.open('wb') as out:
        while chunk := upload.file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise HTTPException(400, 'Use a file smaller than 200 MB.')
            out.write(chunk)


def collect(folder, ident, hd=False):
    from seedance_bridge import wait_and_finish
    target = folder / 'hd' if hd else folder
    try:
        wait_and_finish(target, ident, lambda message: update(folder, hd, status=message))
        update(folder, hd, state='done', stage='final' if hd else 'draft',
               status='1080p export ready with original audio.' if hd else 'Draft ready with original audio.')
    except Exception as exc:
        update(folder, hd, state='error', status=str(exc))


@app.get('/')
def index():
    return FileResponse(ROOT / 'static/index.html')


@app.get('/jobs')
def list_jobs():
    items = []
    for folder in RUNS.iterdir():
        if not folder.is_dir() or len(folder.name) != 32 or any(c not in '0123456789abcdef' for c in folder.name):
            continue
        meta = read_json(folder / 'studio.json')
        state = record(folder)
        hd_state = record(folder, True)
        items.append({'id': folder.name, 'name': meta.get('name', 'Untitled transformation'),
                      'created_at': meta.get('created_at', datetime.fromtimestamp(folder.stat().st_mtime, timezone.utc).isoformat()),
                      'state': hd_state['state'] if hd_state['state'] == 'running' else state['state'],
                      'status': hd_state['status'] if hd_state['state'] == 'running' else state['status'],
                      'quality': '1080p' if (folder / 'hd/final-preview.mp4').exists() else 'Draft' if (folder / 'final-preview.mp4').exists() else 'Input'})
    return sorted(items, key=lambda item: item['created_at'], reverse=True)


@app.post('/media/inspect')
def inspect(video: UploadFile = File(...)):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / ('video' + Path(video.filename or '.mp4').suffix.lower())
        save_upload(video, path)
        try:
            return media_info(path, source=True)
        except ValueError as exc:
            raise HTTPException(400, str(exc))


@app.post('/jobs')
def create(video: UploadFile = File(...), prompt: str = Form('person'), provider: str = Form('replicate'),
           mode: str = Form('depth'), name: str = Form('')):
    check_preparation(mode)
    if provider not in ['huggingface', 'replicate', 'replicate-chenxwh']:
        raise HTTPException(400, 'Unknown depth provider.')
    ident = uuid.uuid4().hex
    folder = RUNS / ident
    folder.mkdir()
    src = folder / 'upload.mp4'
    save_upload(video, src)
    try:
        info = media_info(src, source=True)
        if not info['valid']:
            raise ValueError(' '.join(info['issues']))
    except ValueError as exc:
        update(folder, state='error', stage='source', status=str(exc))
        raise HTTPException(400, str(exc))
    write_json(folder / 'studio.json', {'name': name.strip()[:120] or Path(video.filename or 'Untitled transformation').stem[:120],
               'source_name': Path(video.filename or 'source.mp4').name, 'created_at': now(),
               'mode': mode, 'subject': prompt.strip() or 'person', 'provider': provider, 'media': info})
    update(folder, state='running', stage='preparation', status='Preparing the source video.')

    def prepare():
        try:
            callback = lambda message: update(folder, status=message)
            if mode == 'face_mesh':
                from face_mesh import run
                run(src, folder, callback)
            elif mode == 'depth_mesh':
                from face_mesh import run_depth
                run_depth(src, folder, prompt, provider, callback)
            else:
                from pipeline import run
                run(src, folder, prompt, provider, callback)
            update(folder, state='done', stage='review', status='Preparation complete. Review the entire input before generating.')
        except Exception as exc:
            update(folder, state='error', status=str(exc))
    start_worker(prepare)
    return record(folder)


@app.get('/jobs/{ident}')
def get(ident: str):
    return record(folder_for(ident))


@app.post('/jobs/{ident}/name')
def rename(ident: str, name: str = Form(...)):
    folder = folder_for(ident)
    if not name.strip():
        raise HTTPException(400, 'Enter a transformation name.')
    with lock:
        meta = read_json(folder / 'studio.json')
        meta['name'] = name.strip()[:120]
        write_json(folder / 'studio.json', meta)
    return {'name': meta['name']}


@app.get('/jobs/{ident}/details')
def details(ident: str):
    from mask_review import state
    folder = folder_for(ident)
    meta = read_json(folder / 'studio.json')
    mode = meta.get('mode', read_json(folder / 'workflow-mode.json').get('mode', 'depth'))
    names = ['upload.mp4', 'original.mp4', 'seedance-input.mp4', 'depth.mp4', 'mask.mp4',
             'vocals.wav', 'vocals-plus3.wav', 'music.wav', 'final-preview.mp4', 'hd/final-preview.mp4',
             'seedance-result.mp4', 'hd/seedance-result.mp4']
    files = {name: '/runs/' + ident + '/' + name for name in names if (folder / name).exists()}
    form = read_json(folder / 'studio-form.json')
    generation = read_json(folder / 'generation.json')
    attempted = (folder / 'seedance-request.json').exists() or (folder / 'seedance-response.json').exists()
    request = read_json(folder / 'seedance-request.json')
    hd_attempted = (folder / 'hd/request.json').exists() or (folder / 'hd/response.json').exists()
    response = read_json(folder / 'seedance-response.json')
    hd_response = read_json(folder / 'hd/response.json')
    refs = {}
    for name in ['reference', 'second_reference']:
        selected = form.get(name)
        if not selected:
            selected = next((name + ext for ext in ['.png', '.jpg', '.jpeg', '.webp', '.mp4', '.mov'] if (folder / (name + ext)).exists()), None)
        if selected and Path(selected).name == selected and (folder / selected).exists():
            refs[name] = {'file': selected, 'url': '/runs/' + ident + '/' + selected}
    return {'id': ident, 'meta': meta, 'mode': mode, 'job': record(folder), 'hd': record(folder, True),
            'files': files, 'review': state(folder), 'form': form, 'references': refs,
            'generation': {key: generation.get(key) for key in ['request_id', 'prompt', 'model', 'reference_type']},
            'attempted': attempted, 'hd_attempted': hd_attempted,
            'can_repair': mode != 'face_mesh' and 'depth.mp4' in files and not attempted,
            'can_resume': bool(response.get('id')) and 'final-preview.mp4' not in files,
            'can_resume_hd': bool(hd_response.get('id')) and 'hd/final-preview.mp4' not in files,
            'can_hd': bool(request.get('draft') and generation.get('request_id') and 'final-preview.mp4' in files
                           and 'hd/final-preview.mp4' not in files and not hd_attempted),
            'adjustment': read_json(folder / 'duration-adjustment.json'),
            'hd_adjustment': read_json(folder / 'hd/duration-adjustment.json')}


@app.post('/jobs/{ident}/preview')
def preview(ident: str, prompt: str = Form(...), reference: UploadFile = File(...),
            second_reference: UploadFile | None = File(None), subject_one: str = Form(...), subject_two: str = Form('')):
    from mask_review import require_approved, fingerprint
    from seedance_bridge import compose_prompt, validate_videos
    folder = folder_for(ident)
    with lock:
        available(folder)
        unsubmitted(folder)
        try:
            require_approved(folder)
            if not prompt.strip() or not subject_one.strip():
                raise ValueError('Describe the transformation and the subject for the first reference.')
            if second_reference and not subject_two.strip():
                raise ValueError('Describe which subject the second reference replaces.')
            paths = []
            for name, upload in [('reference', reference), ('second_reference', second_reference)]:
                if upload is None:
                    paths.append(None)
                    continue
                suffix = Path(upload.filename or '').suffix.lower()
                allowed = ['.png', '.jpg', '.jpeg', '.webp'] + (['.mp4', '.mov', '.webm'] if name == 'reference' else [])
                if suffix not in allowed:
                    raise ValueError('Use PNG, JPG, WebP or a supported primary video reference.')
                path = folder / (name + suffix)
                save_upload(upload, path)
                if suffix in ['.mp4', '.mov', '.webm']:
                    info = media_info(path)
                    if not info['valid']:
                        raise ValueError(' '.join(info['issues']))
                    if suffix == '.webm':
                        from pipeline import normalize
                        path = folder / (name + '.mp4')
                        normalize(folder / (name + '.webm'), path)
                else:
                    from PIL import Image
                    with Image.open(path) as image:
                        image.verify()
                paths.append(path)
            validate_videos([folder / 'seedance-input.mp4'] + [path for path in paths if path])
            primary_video = paths[0].suffix.lower() in ['.mp4', '.mov']
            primary_token = '@Video2' if primary_video else '@Image1'
            secondary_token = '@Image1' if primary_video else '@Image2'
            creative = prompt.strip() + '\nSubject mapping: ' + primary_token + ' replaces ' + subject_one.strip() + '.'
            if paths[1]:
                creative += ' ' + secondary_token + ' replaces ' + subject_two.strip() + '.'
            exact = compose_prompt(folder, creative, *paths)
            from seedance_bridge import api_base, DEFAULT_MODEL
            from config import setting
            data = {'token': uuid.uuid4().hex, 'prompt': exact, 'creative_prompt': creative,
                    'fingerprint': fingerprint(folder), 'hashes': {path.name: file_hash(path) for path in paths if path},
                    'reference': paths[0].name, 'second_reference': paths[1].name if paths[1] else None,
                    'model': setting('SEEDANCE_MODEL', DEFAULT_MODEL), 'api_base': api_base()}
            write_json(folder / 'draft-preview.json', data)
            write_json(folder / 'studio-form.json', {'prompt': prompt, 'subject_one': subject_one, 'subject_two': subject_two,
                       'reference': data['reference'], 'second_reference': data['second_reference']})
            return {'token': data['token'], 'prompt': exact, 'model': data['model'], 'resolution': '480p',
                    'note': 'Confirming uploads these inputs to the configured media host and starts one paid Seedance draft. Pricing and balance are managed in your provider account.'}
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc))


@app.post('/jobs/{ident}/seedance')
def seedance(ident: str, preview_token: str = Form(...)):
    from mask_review import require_approved, fingerprint
    from seedance_bridge import submit, api_base, DEFAULT_MODEL
    from config import setting
    folder = folder_for(ident)
    with lock:
        available(folder)
        unsubmitted(folder)
        reviewed = read_json(folder / 'draft-preview.json')
        try:
            require_approved(folder)
            if not preview_token or reviewed.get('token') != preview_token:
                raise ValueError('Review a current submission preview first.')
            if reviewed['fingerprint'] != fingerprint(folder) or any(file_hash(folder / name) != digest for name, digest in reviewed['hashes'].items()):
                raise ValueError('An input changed. Review a new submission preview before generating.')
            if reviewed['model'] != setting('SEEDANCE_MODEL', DEFAULT_MODEL) or reviewed['api_base'] != api_base():
                raise ValueError('The API configuration changed. Review a new submission preview.')
        except (ValueError, KeyError, OSError) as exc:
            raise HTTPException(409, str(exc))
        update(folder, state='running', stage='draft', status='Uploading references and submitting the reviewed draft.')
    try:
        request_id = submit(folder, reviewed['creative_prompt'], folder / reviewed['reference'],
                            folder / reviewed['second_reference'] if reviewed['second_reference'] else None,
                            status=lambda message: update(folder, status=message), expected_prompt=reviewed['prompt'])
    except Exception as exc:
        update(folder, state='error', status=str(exc))
        raise HTTPException(502, str(exc))
    update(folder, request_id=request_id, status='Seedance is rendering the draft: ' + request_id)
    start_worker(collect, folder, request_id)
    return record(folder)


@app.post('/jobs/{ident}/repair')
def repair(ident: str):
    from studio import repair_rgb
    folder = folder_for(ident)
    with lock:
        available(folder)
        unsubmitted(folder)
        if not details(ident)['can_repair']:
            raise HTTPException(400, 'This mode has no depth mask to repair. Prepare a new source to rebuild tracking.')
        check_preparation(read_json(folder / 'studio.json').get('mode', 'depth'))
        (folder / 'mask-review.json').unlink(missing_ok=True)
        (folder / 'draft-preview.json').unlink(missing_ok=True)
        update(folder, state='running', stage='preparation', status='Repairing the mask from original video detail.')
    def work():
        try:
            repair_rgb(folder, lambda message: update(folder, status=message))
            update(folder, state='done', stage='review', status='Repair complete. Review the full input again.')
        except Exception as exc:
            update(folder, state='error', status=str(exc))
    start_worker(work)
    return record(folder)


@app.post('/jobs/{ident}/resume')
def resume(ident: str, hd: bool = Form(False)):
    folder = folder_for(ident)
    with lock:
        if record(folder, hd).get('state') == 'running':
            return record(folder, hd)
        available(folder)
        target = folder / 'hd' if hd else folder
        if (target / 'final-preview.mp4').exists():
            return record(folder, hd)
        response = read_json(target / ('response.json' if hd else 'seedance-response.json'))
        if not isinstance(response.get('id'), str) or not response['id']:
            raise HTTPException(409, 'No saved task ID is available. Inspect your ModelArk task list; an uncertain paid request must not be resubmitted.')
        update(folder, hd, state='running', stage='final' if hd else 'draft', status='Collecting the saved task: ' + response['id'])
    start_worker(collect, folder, response['id'], hd)
    return record(folder, hd)


@app.post('/jobs/{ident}/finish')
def finish(ident: str, video: UploadFile = File(...)):
    folder = folder_for(ident)
    with lock:
        available(folder)
        if not (folder / 'upload.mp4').exists():
            raise HTTPException(400, 'The original source is required.')
        if (folder / 'final-preview.mp4').exists():
            raise HTTPException(409, 'This transformation already has a result. Start a new transformation to import a different result.')
        update(folder, state='running', stage='draft', status='Restoring the original soundtrack.')
    target = folder / 'seedance-result.mp4'
    try:
        save_upload(video, target)
        from audio_workflow import finish_preview
        finish_preview(target, folder)
        update(folder, state='done', stage='draft', status='Imported result ready with the original soundtrack.')
    except Exception as exc:
        update(folder, state='error', status=str(exc))
        raise HTTPException(400, str(exc))
    return {'url': '/runs/' + ident + '/final-preview.mp4'}


@app.get('/jobs/{ident}/hd')
def get_hd(ident: str):
    return record(folder_for(ident), True)


@app.post('/jobs/{ident}/hd')
def create_hd(ident: str):
    from seedance_bridge import submit_hd
    folder = folder_for(ident)
    with lock:
        available(folder)
        if not details(ident)['can_hd']:
            raise HTTPException(409, 'A completed direct-API draft is required. Resume any existing 1080p task instead of resubmitting.')
        update(folder, True, state='running', stage='final', status='Submitting the approved draft for 1080p.')
    def work():
        try:
            request_id = submit_hd(folder)
            update(folder, True, request_id=request_id, status='Seedance is rendering 1080p: ' + request_id)
            collect(folder, request_id, True)
        except Exception as exc:
            update(folder, True, state='error', status=str(exc))
    start_worker(work)
    return record(folder, True)


@app.get('/jobs/{ident}/mask-review')
def get_mask_review(ident: str):
    from mask_review import state
    return state(folder_for(ident))


@app.post('/jobs/{ident}/mask-review')
def save_mask_review(ident: str, approved: bool = Form(...), fingerprint: str = Form(...), note: str = Form('')):
    from mask_review import review
    folder = folder_for(ident)
    with lock:
        available(folder)
        unsubmitted(folder)
        try:
            result = review(folder, approved, note, fingerprint)
            (folder / 'draft-preview.json').unlink(missing_ok=True)
            update(folder, stage='review', status='Input approved. Add character references and review the submission.' if approved else 'Input rejected. Repair the mask or prepare a new source.')
            return result
        except ValueError as exc:
            raise HTTPException(409, str(exc))


@app.on_event('startup')
def resume_saved_generations():
    for folder in RUNS.iterdir():
        if not folder.is_dir() or len(folder.name) != 32 or any(c not in '0123456789abcdef' for c in folder.name):
            continue
        for hd in [False, True]:
            target = folder / 'hd' if hd else folder
            response = read_json(target / ('response.json' if hd else 'seedance-response.json'))
            request_id = response.get('id')
            if not isinstance(request_id, str) or not request_id or (target / 'final-preview.mp4').exists():
                continue
            update(folder, hd, state='running', stage='final' if hd else 'draft', status='Resuming collection of saved task: ' + request_id)
            start_worker(collect, folder, request_id, hd)


@app.get('/health')
def health():
    return {'status': 'ok', 'service': 'Sharingan'}


@app.get('/configuration')
def configuration():
    return readiness()


app.mount('/runs', StaticFiles(directory=RUNS), name='runs')
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
