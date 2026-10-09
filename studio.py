"""Local studio checks and preparation utilities. No inference on inspection."""
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from config import ROOT, setting


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {} if default is None else default


def write_json(path, data):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temporary.replace(path)


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def mesh_python():
    for relative in ['.venv-face/Scripts/python.exe', '.venv-face/bin/python']:
        candidate = ROOT / relative
        if candidate.exists():
            return candidate
    return None


def readiness():
    def configured(name):
        value = setting(name).strip().lower()
        return bool(value) and not any(s in value for s in ['your_', 'replace_me', 'placeholder'])

    checks = [
        {'id': 'python', 'label': 'Python 3.12 or newer', 'ready': sys.version_info >= (3, 12),
         'help': 'Use Python 3.12 or newer for the server and optional mesh worker.'},
        {'id': 'rubberband', 'label': 'Rubber Band audio tool', 'ready': bool(shutil.which('rubberband')),
         'help': 'Install the Rubber Band CLI and add its executable to PATH, then restart Sharingan.'},
    ]
    missing = [name for name in ['av', 'numpy', 'PIL', 'requests', 'gradio_client', 'scipy', 'cv2']
               if importlib.util.find_spec(name) is None]
    checks.append({'id': 'packages', 'label': 'Preparation packages', 'ready': not missing,
                   'help': 'Install requirements.txt in the server environment.' + (' Missing: ' + ', '.join(missing) if missing else '')})
    for key, label in [('REPLICATE_API_TOKEN', 'Replicate key'), ('SEEDANCE_API_KEY', 'Seedance key')]:
        checks.append({'id': key, 'label': label, 'ready': configured(key),
                       'help': 'Set ' + key + ' in the local .env file and restart Sharingan.'})
    worker = mesh_python()
    mesh_ready = False
    if worker:
        try:
            mesh_ready = subprocess.run([str(worker), '-c', 'import mediapipe,av,PIL,numpy'],
                                        capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pass
    checks.append({'id': 'mesh', 'label': 'Optional face-mesh worker', 'ready': mesh_ready,
                   'help': 'Run bash setup-face-mesh.sh in macOS, Linux or WSL. The worker must run in the same environment as the server.'})
    hosts = [setting('MEDIA_HOST', 'tmpfiles')] + [x.strip() for x in setting('MEDIA_HOST_FALLBACKS').split(',') if x.strip()]
    checks.append({'id': 'hosting', 'label': 'Media hosting configuration',
                   'ready': all(x in ['tmpfiles', 'catbox'] for x in hosts),
                   'help': 'MEDIA_HOST and MEDIA_HOST_FALLBACKS support tmpfiles and catbox.'})
    by_id = {item['id']: item['ready'] for item in checks}
    preparation = all(by_id[x] for x in ['python', 'packages', 'rubberband', 'REPLICATE_API_TOKEN'])
    from seedance_bridge import DEFAULT_MODEL
    return {'checks': checks, 'modes': {'depth': preparation, 'face_mesh': preparation and mesh_ready,
                                      'depth_mesh': preparation and mesh_ready},
            'seedance_configured': by_id['SEEDANCE_API_KEY'],
            'preparation_configured': by_id['REPLICATE_API_TOKEN'],
            'generation_ready': by_id['SEEDANCE_API_KEY'] and by_id['hosting'],
            'model': setting('SEEDANCE_MODEL', DEFAULT_MODEL), 'media_hosts': hosts,
            'note': 'These are local checks. Provider access, balance and hosted model availability have not been verified.'}


def media_info(path, source=False):
    import av
    try:
        with av.open(str(path)) as media:
            if not media.streams.video:
                raise ValueError('Choose a file containing a video stream.')
            video = media.streams.video[0]
            duration = float(video.duration * video.time_base) if video.duration else float((media.duration or 0) / av.time_base)
            info = {'duration': round(duration, 3), 'width': video.width, 'height': video.height,
                    'fps': round(float(video.average_rate or 0), 3), 'audio': bool(media.streams.audio),
                    'bytes': Path(path).stat().st_size}
    except (OSError, av.error.FFmpegError) as exc:
        raise ValueError('This video could not be read. Try exporting an MP4 or MOV.') from exc
    issues = []
    if not 4 <= duration <= (30 if source else 30.05):
        issues.append('Choose a clip between 4 and 30 seconds; trim it in your video editor first.')
    if not video.height or not 0.4 <= video.width / video.height <= 2.5:
        issues.append('Use an aspect ratio between 0.4 and 2.5.')
    if source and not info['audio']:
        issues.append('The source needs an audio track for vocal separation and soundtrack restoration.')
    if source and info['audio']:
        # Verify the original compressed audio can be copied unchanged into MP4.
        # This is especially useful for MOV/WebM codecs; it makes no API calls.
        try:
            with tempfile.TemporaryDirectory() as directory, av.open(str(path)) as audio_source:
                with av.open(str(Path(directory) / 'audio-check.mp4'), 'w') as output:
                    stream = output.add_stream_from_template(audio_source.streams.audio[0])
                    for packet in audio_source.demux(audio=0):
                        if packet.dts is not None:
                            packet.stream = stream
                            output.mux(packet)
                            break
        except (av.error.FFmpegError, ValueError):
            issues.append('The source audio codec cannot be copied unchanged into MP4. Export a source with AAC audio before preparing.')
    if info['bytes'] > 200 * 1024 * 1024:
        issues.append('Use a video smaller than 200 MB.')
    info['issues'] = issues
    info['valid'] = not issues
    return info


def repair_rgb(folder, status=print):
    """Rebuild depth masks from RGB detail and invalidate review before mutation."""
    from raw_masks import segment_raw, clean_border_fragments
    from pipeline import composite
    from audio_workflow import prepare_seedance_video
    folder = Path(folder)
    mode = read_json(folder / 'workflow-mode.json').get('mode', 'depth')
    if mode == 'face_mesh':
        raise ValueError('Face-mesh mode has no subject mask. Prepare the source again to rebuild tracking.')
    if any((folder / name).exists() for name in ['seedance-request.json', 'seedance-response.json']):
        raise ValueError('This input has already been submitted. Start a new transformation to change its guidance.')
    meta = read_json(folder / 'manifest.json')
    if not meta or not (folder / 'depth.mp4').exists():
        raise ValueError('Complete depth preparation before repairing its mask.')
    (folder / 'mask-review.json').unlink(missing_ok=True)
    (folder / 'draft-preview.json').unlink(missing_ok=True)
    repair = folder / 'rgb-repair'
    repair.mkdir(exist_ok=True)
    status('Segmenting the subject from the original video')
    masks = clean_border_fragments(segment_raw(folder / 'original.mp4', repair, meta.get('prompt', 'person')))
    status('Rebuilding the mask while preserving depth colors')
    composite(folder / 'original.mp4', folder / 'depth.mp4', masks, folder, folder / 'upload.mp4')
    if mode == 'depth_mesh':
        worker = mesh_python()
        if not worker:
            raise ValueError('Install the optional face-mesh worker before repairing combined mode.')
        shutil.copy2(folder / 'composite-silent.mp4', folder / 'depth-composite-silent.mp4')
        subprocess.run([str(worker), str(ROOT / 'mesh_worker.py'), str(folder), '--depth'], check=True)
    status('Embedding the pitched vocals in the repaired input')
    prepare_seedance_video(folder)
    meta['mask_method'] = 'SAM 3 on original RGB, preserving depth colors'
    write_json(folder / 'manifest.json', meta)
    status('Repair complete. Review the entire clip and approve the new input.')
