"""Direct BytePlus ModelArk Seedance 2.5 tasks. Never retry a paid POST."""
from pathlib import Path
from urllib.parse import quote, urlparse
import concurrent.futures
import json
import shutil
import time
import requests
from config import credential, setting
from media_host import upload
from audio_workflow import finish_preview

DEFAULT_BASE = 'https://ark.ap-southeast.bytepluses.com/api/v3'
DEFAULT_MODEL = 'dreamina-seedance-2-5-260628'
VIDEO_EXTENSIONS = {'.mp4', '.mov'}


def api_base():
    base = setting('SEEDANCE_BASE_URL', DEFAULT_BASE).rstrip('/')
    if urlparse(base).scheme != 'https' or not urlparse(base).netloc:
        raise ValueError('SEEDANCE_BASE_URL must be an HTTPS ModelArk API base URL.')
    return base


def headers():
    return {'Authorization': 'Bearer ' + credential('SEEDANCE_API_KEY'),
            'Content-Type': 'application/json'}


def _save(path, data):
    path.write_text(json.dumps(data, indent=2), encoding='utf-8')


def validate_videos(paths):
    """Reject invalid edit inputs before media upload or paid inference."""
    import av
    total = 0
    for path in paths:
        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        if path.stat().st_size > 200 * 1024 * 1024:
            raise ValueError('Each Seedance input video must be at most 200 MB.')
        with av.open(str(path)) as source:
            if not source.streams.video:
                raise ValueError('An input video has no video stream.')
            stream = source.streams.video[0]
            duration = float(stream.duration * stream.time_base) if stream.duration else float(source.duration / av.time_base)
            if not 4 <= duration <= 30.05:
                raise ValueError('Seedance video-edit inputs must each be 4–30 seconds long.')
            width, height = stream.width, stream.height
            if not (300 <= width <= 6000 and 300 <= height <= 6000
                    and 0.4 <= width / height <= 2.5
                    and 407696 <= width * height <= 8295044):
                raise ValueError('Seedance input dimensions are unsupported. Use at least a 480p-class source with aspect ratio between 0.4 and 2.5.')
            if not stream.average_rate or not 24 <= float(stream.average_rate) <= 60:
                raise ValueError('Seedance input videos must use 24–60 fps.')
            total += duration
    if total > 30.05:
        raise ValueError('The source and identity reference videos must total at most 30 seconds. Use a shorter source or an image identity reference.')


def _create(folder, payload, request_file, response_file):
    """Persist intent before transmission; ambiguous outcomes require inspection."""
    request_path, response_path = folder / request_file, folder / response_file
    auth = headers()
    base = api_base()
    if request_path.exists() or response_path.exists():
        raise ValueError('Submission already attempted. Resume the saved task; inspect an uncertain response before creating another job.')
    with request_path.open('x', encoding='utf-8') as out:
        json.dump(payload, out, indent=2)
    try:
        response = requests.post(base + '/contents/generations/tasks',
                                 headers=auth, json=payload, timeout=90)
    except requests.RequestException as exc:
        raise RuntimeError('Submission outcome is uncertain. Inspect your ModelArk task list before retrying; the saved request prevents duplicate billing.') from exc
    if not response.ok:
        _save(folder / 'submission-error.json', {'http_status': response.status_code})
        raise ValueError(f'Seedance rejected submission (HTTP {response.status_code}). Check ModelArk model access, balance and media requirements. The saved request has not been retried.')
    data = response.json()
    _save(response_path, data)
    ident = data.get('id')
    if not isinstance(ident, str) or not ident:
        raise ValueError('Seedance returned no task ID. Inspect the saved response and ModelArk task list before retrying.')
    return ident


def compose_prompt(folder, prompt, reference, second_reference=None):
    """One prompt builder for preview, CLI and paid submission."""
    from mask_review import is_mesh
    folder = Path(folder)
    description = 'colored-depth composite'
    if is_mesh(folder):
        mode = json.loads((folder / 'workflow-mode.json').read_text())['mode']
        description = 'depth composite with face mesh overlay' if mode == 'depth_mesh' else 'original video with face mesh overlay'
    instructions = ('Video edit: edit @Video1 using the supplied character identity references.\n' +
        prompt.replace('@Audio1', 'the audio embedded in @Video1') +
        '\n@Video1 is the source to edit: ' + description +
        ' with isolated vocals pitched +3 semitones. Use only its embedded speech for performance and lip synchronization. Preserve the source framing, background and timing.')
    video_reference = Path(reference).suffix.lower() in VIDEO_EXTENSIONS
    if video_reference:
        instructions += '\n@Video2 is only the primary character visual identity reference; do not use its voice, performance or timing.'
        if second_reference:
            instructions += ' @Image1 is the secondary character reference.'
    else:
        instructions += '\n@Image1 is the primary character reference.'
        if second_reference:
            instructions += ' @Image2 is the secondary character reference.'
    instructions += '\nRemove depth colors and all guidance overlays from the output. Replace the entire original identity including hair.'
    if is_mesh(folder):
        instructions += ' Remove all face mesh lines; use them only for expression and lip motion guidance.'
    return instructions


def submit(folder, prompt, reference, second_reference=None, status=print, expected_prompt=None):
    from mask_review import require_approved, is_mesh
    folder = Path(folder)
    require_approved(folder)
    if (folder / 'seedance-request.json').exists() or (folder / 'seedance-response.json').exists():
        raise ValueError('This job already has a submission attempt. Resume it; prepare a new job for a deliberate variation.')
    headers()
    api_base()
    if not prompt.strip():
        raise ValueError('A generation prompt is required.')
    if not (folder / 'audio-manifest.json').exists():
        raise ValueError('Audio separation must complete before submission.')
    prepared = folder / 'seedance-input.mp4'
    if not prepared.exists():
        raise ValueError('Prepare the video with embedded vocals and review it before submission.')
    paths = [prepared, Path(reference)]
    if paths[1].suffix.lower() not in VIDEO_EXTENSIONS | {'.png', '.jpg', '.jpeg', '.webp'}:
        raise ValueError('Use a PNG, JPG, WebP, MP4 or MOV primary reference.')
    if second_reference:
        second = Path(second_reference)
        if second.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
            raise ValueError('The second reference must be an image.')
        paths.append(second)
    validate_videos(paths)
    instructions = compose_prompt(folder, prompt, reference, second_reference)
    if expected_prompt is not None and instructions != expected_prompt:
        raise ValueError('The prompt changed. Review a new submission preview before generating.')
    video_reference = paths[1].suffix.lower() in VIDEO_EXTENSIONS
    status('Uploading reviewed video and character references')
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        urls = list(pool.map(upload, paths))
    content = [{'type': 'text', 'text': instructions},
               {'type': 'video_url', 'video_url': {'url': urls[0]}, 'role': 'reference_video'}]
    for path, url in zip(paths[1:], urls[1:]):
        kind = 'video' if path.suffix.lower() in VIDEO_EXTENSIONS else 'image'
        content.append({'type': kind + '_url', kind + '_url': {'url': url}, 'role': 'reference_' + kind})
    payload = {'model': setting('SEEDANCE_MODEL', DEFAULT_MODEL), 'content': content,
               'draft': True, 'resolution': '480p', 'ratio': 'adaptive', 'duration': -1,
               'omni_reference_task_type': 'edit', 'generate_audio': True,
               'watermark': False, 'output_format': 'mp4'}
    require_approved(folder)
    ident = _create(folder, payload, 'seedance-request.json', 'seedance-response.json')
    _save(folder / 'generation.json', {'request_id': ident, 'prompt': instructions,
          'video': 'seedance-result.mp4', 'mode': 'edit', 'reference_type': 'video' if video_reference else 'image',
          'provider': 'BytePlus ModelArk', 'model': payload['model'], 'api_base': api_base()})
    status('Seedance draft submitted: ' + ident)
    return ident


def wait_and_finish(folder, request_id, status=print):
    folder = Path(folder)
    metadata = folder / 'generation.json'
    saved = json.loads(metadata.read_text()) if metadata.exists() else {}
    base = saved.get('api_base') or api_base()
    auth = headers()
    for _ in range(360):
        try:
            response = requests.get(base + '/contents/generations/tasks/' + quote(request_id, safe=''),
                                    headers=auth, timeout=30)
            if response.status_code == 429 or response.status_code >= 500:
                time.sleep(10)
                continue
            response.raise_for_status()
        except (requests.Timeout, requests.ConnectionError):
            time.sleep(10)
            continue
        data = response.json()
        _save(folder / 'provider-status.json', data)
        state = data.get('status')
        if state == 'succeeded':
            url = (data.get('content') or {}).get('video_url')
            if not isinstance(url, str) or urlparse(url).scheme != 'https':
                raise ValueError('Seedance result HTTPS URL missing.')
            media = requests.get(url, timeout=180)
            media.raise_for_status()
            (folder / 'seedance-result.mp4').write_bytes(media.content)
            status('Restoring the complete original source audio')
            finish_preview(folder / 'seedance-result.mp4', folder)
            return
        if state in {'failed', 'cancelled', 'canceled', 'expired'}:
            error = data.get('error') or {}
            code = error.get('code', state) if isinstance(error, dict) else state
            raise RuntimeError('Seedance task failed: ' + str(code))
        status('Seedance · ' + str(state or 'pending'))
        time.sleep(10)
    raise TimeoutError('Seedance is still pending. Task ID saved; resume collection instead of resubmitting.')


def submit_hd(folder):
    """Generate an approved 1080p final from the saved direct-API draft task."""
    folder = Path(folder)
    generation = json.loads((folder / 'generation.json').read_text())
    original = json.loads((folder / 'seedance-request.json').read_text())
    if not original.get('draft') or not (folder / 'final-preview.mp4').exists():
        raise ValueError('A completed draft is required before generating 1080p.')
    if generation.get('api_base') and generation['api_base'] != api_base():
        raise ValueError('Restore SEEDANCE_BASE_URL to the draft API endpoint before completing it.')
    payload = {'model': original['model'], 'content': [{'type': 'draft_task',
               'draft_task': {'id': generation['request_id']}}],
               'resolution': '1080p', 'output_format': 'mp4', 'watermark': False}
    hd = folder / 'hd'
    hd.mkdir(exist_ok=True)
    if not (hd / 'upload.mp4').exists():
        shutil.copy2(folder / 'upload.mp4', hd / 'upload.mp4')
    ident = _create(hd, payload, 'request.json', 'response.json')
    _save(hd / 'generation.json', {'request_id': ident, 'api_base': api_base(), 'model': original['model']})
    return ident

