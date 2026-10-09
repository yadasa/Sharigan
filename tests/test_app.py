import io
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch, Mock

from fastapi.testclient import TestClient
from PIL import Image
import app
import mask_review
import seedance_bridge
from test_workflow import prepared, mocks


class AppTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.patcher = patch.object(app, 'RUNS', self.root)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        app.jobs.clear()
        app.hd_jobs.clear()
        self.client = TestClient(app.app)

    def job(self, approved=True):
        folder = self.root / ('a' * 32)
        folder.mkdir()
        prepared(folder)
        (folder / 'studio.json').write_text(json.dumps({'name': 'Example scene', 'mode': 'depth', 'created_at': '2026-10-09T00:00:00Z'}))
        (folder / 'status.json').write_text('{"state":"done","status":"Input ready"}')
        if approved:
            mask_review.review(folder, True, 'Entire clip reviewed', mask_review.fingerprint(folder))
        return folder

    def image(self):
        data = io.BytesIO()
        Image.new('RGB', (16, 16), 'red').save(data, format='PNG')
        return data.getvalue()

    def preview(self, folder, **extra):
        with patch('seedance_bridge.validate_videos'):
            return self.client.post('/jobs/' + folder.name + '/preview',
                                    data={'prompt': 'Replace the person', 'subject_one': 'the person on the left', **extra},
                                    files={'reference': ('identity.png', self.image(), 'image/png')})

    def test_health_and_static_assets(self):
        self.assertEqual(self.client.get('/health').json()['service'], 'Sharingan')
        for path in ['/', '/static/app.js', '/static/styles.css', '/static/sharingan.svg']:
            self.assertEqual(self.client.get(path).status_code, 200)

    def test_configuration_never_returns_credentials(self):
        with patch('studio.setting', side_effect=lambda key, default='': 'private-test-key' if key.endswith(('KEY', 'TOKEN')) else default), patch('studio.mesh_python', return_value=None):
            response = self.client.get('/configuration')
            self.assertNotIn('private-test-key', response.text)
            self.assertTrue(response.json()['seedance_configured'])
            self.assertTrue(response.json()['preparation_configured'])
            self.assertIn('not been verified', response.json()['note'])

    def test_invalid_job_does_not_expose_files(self):
        for path in ['/jobs/not-a-job', '/jobs/not-a-job/mask-review', '/jobs/not-a-job/details']:
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_history_and_rename_are_persisted(self):
        folder = self.job()
        result = self.client.post('/jobs/' + folder.name + '/name', data={'name': 'Rooftop scene'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(json.loads((folder / 'studio.json').read_text())['name'], 'Rooftop scene')
        self.assertEqual(self.client.get('/jobs').json()[0]['name'], 'Rooftop scene')

    def test_interrupted_preparation_is_not_reported_as_running(self):
        folder = self.job()
        (folder / 'status.json').write_text('{"state":"running","status":"Depth processing"}')
        state = self.client.get('/jobs/' + folder.name).json()
        self.assertEqual(state['state'], 'interrupted')

    def test_preview_is_local_and_contains_the_full_prompt(self):
        folder = self.job()
        with patch('seedance_bridge.upload') as upload, patch('seedance_bridge.requests.post') as paid:
            result = self.preview(folder)
        self.assertEqual(result.status_code, 200, result.text)
        prompt = result.json()['prompt']
        self.assertIn('@Image1 replaces the person on the left', prompt)
        self.assertIn('Remove depth colors', prompt)
        self.assertFalse((folder / 'seedance-request.json').exists())
        upload.assert_not_called()
        paid.assert_not_called()

    def test_submission_sends_exactly_the_reviewed_prompt_once(self):
        folder = self.job()
        preview = self.preview(folder).json()
        with ExitStack() as stack:
            paid = mocks(stack)
            stack.enter_context(patch('app.start_worker'))
            response = self.client.post('/jobs/' + folder.name + '/seedance', data={'preview_token': preview['token']})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(paid.call_args.kwargs['json']['content'][0]['text'], preview['prompt'])
            repeat = self.client.post('/jobs/' + folder.name + '/seedance', data={'preview_token': preview['token']})
            self.assertEqual(repeat.status_code, 409)
            self.assertEqual(paid.call_count, 1)

    def test_changed_reference_invalidates_submission_preview(self):
        folder = self.job()
        preview = self.preview(folder).json()
        (folder / 'reference.png').write_bytes(b'changed')
        with patch('seedance_bridge.requests.post') as paid:
            result = self.client.post('/jobs/' + folder.name + '/seedance', data={'preview_token': preview['token']})
            self.assertEqual(result.status_code, 409)
            paid.assert_not_called()

    def test_changed_input_invalidates_submission_preview(self):
        folder = self.job()
        preview = self.preview(folder).json()
        (folder / 'seedance-input.mp4').write_bytes(b'changed')
        with patch('seedance_bridge.requests.post') as paid:
            result = self.client.post('/jobs/' + folder.name + '/seedance', data={'preview_token': preview['token']})
            self.assertEqual(result.status_code, 409)
            paid.assert_not_called()

    def test_unreviewed_input_cannot_create_preview(self):
        folder = self.job(approved=False)
        with patch('seedance_bridge.requests.post') as paid:
            self.assertEqual(self.preview(folder).status_code, 400)
            paid.assert_not_called()

    def test_second_reference_requires_explicit_subject_mapping(self):
        folder = self.job()
        with patch('seedance_bridge.validate_videos'):
            response = self.client.post('/jobs/' + folder.name + '/preview', data={'prompt': 'Replace both', 'subject_one': 'left person'},
                                        files={'reference': ('one.png', self.image()), 'second_reference': ('two.png', self.image())})
        self.assertEqual(response.status_code, 400)
        self.assertIn('second reference replaces', response.json()['detail'])

    def test_resume_collects_existing_task_without_new_paid_request(self):
        folder = self.job()
        (folder / 'seedance-response.json').write_text('{"id":"saved-task"}')
        with patch('app.start_worker') as thread, patch('seedance_bridge.requests.post') as paid:
            result = self.client.post('/jobs/' + folder.name + '/resume')
            self.assertEqual(result.status_code, 200)
            self.assertEqual(thread.call_args.args[1:], (folder, 'saved-task', False))
            paid.assert_not_called()

    def test_uncertain_submission_has_no_resume_or_resubmit(self):
        folder = self.job()
        (folder / 'seedance-request.json').write_text('{}')
        with patch('seedance_bridge.requests.post') as paid:
            self.assertEqual(self.client.post('/jobs/' + folder.name + '/resume').status_code, 409)
            self.assertEqual(self.preview(folder).status_code, 409)
            paid.assert_not_called()

    def test_repair_clears_review_before_worker_starts(self):
        folder = self.job()
        (folder / 'manifest.json').write_text('{"prompt":"person"}')
        with patch('app.check_preparation'), patch('app.start_worker') as thread:
            result = self.client.post('/jobs/' + folder.name + '/repair')
            self.assertEqual(result.status_code, 200, result.text)
            self.assertFalse((folder / 'mask-review.json').exists())
            thread.assert_called_once()

    def test_processing_job_cannot_repair_or_import(self):
        folder = self.job()
        app.jobs[folder.name] = {'state': 'running', 'status': 'Rendering'}
        self.assertEqual(self.client.post('/jobs/' + folder.name + '/repair').status_code, 409)
        self.assertEqual(self.client.post('/jobs/' + folder.name + '/finish', files={'video': ('result.mp4', b'video')}).status_code, 409)

    def test_import_has_no_hd_upgrade_and_both_versions_are_exposed(self):
        folder = self.job()
        (folder / 'final-preview.mp4').write_bytes(b'draft')
        self.assertFalse(self.client.get('/jobs/' + folder.name + '/details').json()['can_hd'])
        with patch('seedance_bridge.requests.post') as paid:
            self.assertEqual(self.client.post('/jobs/' + folder.name + '/hd').status_code, 409)
            paid.assert_not_called()
        (folder / 'hd').mkdir()
        (folder / 'hd/final-preview.mp4').write_bytes(b'hd')
        files = self.client.get('/jobs/' + folder.name + '/details').json()['files']
        self.assertIn('final-preview.mp4', files)
        self.assertIn('hd/final-preview.mp4', files)

    def test_existing_hd_result_cannot_be_billed_again(self):
        folder = self.job()
        (folder / 'final-preview.mp4').write_bytes(b'draft')
        (folder / 'generation.json').write_text('{"request_id":"saved-draft"}')
        (folder / 'seedance-request.json').write_text('{"draft":true}')
        (folder / 'hd').mkdir()
        (folder / 'hd/final-preview.mp4').write_bytes(b'hd')
        self.assertFalse(self.client.get('/jobs/' + folder.name + '/details').json()['can_hd'])
        with patch('seedance_bridge.requests.post') as paid:
            self.assertEqual(self.client.post('/jobs/' + folder.name + '/hd').status_code, 409)
            paid.assert_not_called()

    def test_model_change_requires_a_new_submission_preview(self):
        folder = self.job()
        preview = self.preview(folder).json()
        with patch('config.setting', side_effect=lambda key, default='': 'changed-model' if key == 'SEEDANCE_MODEL' else default), patch('seedance_bridge.requests.post') as paid:
            response = self.client.post('/jobs/' + folder.name + '/seedance', data={'preview_token': preview['token']})
            self.assertEqual(response.status_code, 409)
            paid.assert_not_called()

    def test_webm_identity_is_converted_to_video_before_preview(self):
        folder = self.job()
        def convert(source, target):
            target.write_bytes(b'converted-video')
        with patch('app.media_info', return_value={'valid': True}), patch('pipeline.normalize', side_effect=convert) as normalize, patch('seedance_bridge.validate_videos'):
            response = self.client.post('/jobs/' + folder.name + '/preview', data={'prompt': 'Replace', 'subject_one': 'center person'},
                                        files={'reference': ('identity.webm', b'webm-video', 'video/webm')})
        self.assertEqual(response.status_code, 200, response.text)
        normalize.assert_called_once()
        self.assertIn('@Video2', response.json()['prompt'])
        self.assertEqual((folder / 'reference.webm').read_bytes(), b'webm-video')
        self.assertEqual((folder / 'reference.mp4').read_bytes(), b'converted-video')

    def test_missing_dependencies_block_preparation_before_provider_calls(self):
        with patch('app.readiness', return_value={'modes': {'depth': False}, 'checks': [{'id': 'rubberband', 'ready': False, 'label': 'Rubber Band'}]}), patch('seedance_bridge.requests.post') as paid:
            result = self.client.post('/jobs', files={'video': ('source.mp4', b'video')})
            self.assertEqual(result.status_code, 409)
            paid.assert_not_called()

    def test_generic_reference_fields_are_in_preview_endpoint(self):
        schema = app.app.openapi()
        route = schema['paths']['/jobs/{ident}/preview']['post']
        ref = route['requestBody']['content']['multipart/form-data']['schema']['$ref'].split('/')[-1]
        fields = schema['components']['schemas'][ref]['properties']
        self.assertEqual(set(fields), {'prompt', 'reference', 'second_reference', 'subject_one', 'subject_two'})


if __name__ == '__main__':
    unittest.main()
