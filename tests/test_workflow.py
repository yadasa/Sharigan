import json
import tempfile
import unittest
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch, Mock
import requests
import mask_review
import seedance_bridge as bridge


def settings(name, default=''):
    return {'SEEDANCE_MODEL': bridge.DEFAULT_MODEL,
            'SEEDANCE_BASE_URL': bridge.DEFAULT_BASE}.get(name, default)


def prepared(folder):
    for name in mask_review.FILES:
        (folder / name).write_bytes(b'original')
    (folder / 'audio-manifest.json').write_text('{}')


def mocks(stack, response=None):
    stack.enter_context(patch('mask_review.require_approved'))
    stack.enter_context(patch('seedance_bridge.credential', return_value='test-key'))
    stack.enter_context(patch('seedance_bridge.setting', side_effect=settings))
    stack.enter_context(patch('seedance_bridge.validate_videos'))
    stack.enter_context(patch('seedance_bridge.upload', side_effect=lambda p: 'https://example.org/' + Path(p).name))
    return stack.enter_context(patch('seedance_bridge.requests.post', return_value=response or Mock(ok=True, json=lambda: {'id': 'task-id'})))


class WorkflowTests(unittest.TestCase):
    def test_prepared_audio_changed_invalidates_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            prepared(folder)
            fingerprint = mask_review.fingerprint(folder)
            mask_review.review(folder, True, 'Entire clip reviewed', fingerprint)
            mask_review.require_approved(folder)
            (folder / 'seedance-input.mp4').write_bytes(b'new audio')
            with self.assertRaises(ValueError):
                mask_review.require_approved(folder)
            with self.assertRaises(ValueError):
                mask_review.review(folder, True, 'stale', fingerprint)

    def test_mask_changed_invalidates_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            prepared(folder)
            fingerprint = mask_review.fingerprint(folder)
            mask_review.review(folder, True, 'Entire clip reviewed', fingerprint)
            (folder / 'mask.mp4').write_bytes(b'changed')
            with self.assertRaises(ValueError):
                mask_review.require_approved(folder)

    def test_existing_submission_not_requeued(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            folder = Path(directory)
            (folder / 'seedance-response.json').write_text('{}')
            post = mocks(stack)
            with self.assertRaises(ValueError):
                bridge.submit(folder, 'prompt', 'reference.png')
            post.assert_not_called()

    def test_image_edit_draft_uses_direct_api(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            folder = Path(directory)
            prepared(folder)
            post = mocks(stack)
            rebuild = stack.enter_context(patch('audio_workflow.prepare_seedance_video'))
            self.assertEqual(bridge.submit(folder, 'Replace one subject', 'identity.png'), 'task-id')
            rebuild.assert_not_called()
            call = post.call_args
            self.assertEqual(call.args[0], bridge.DEFAULT_BASE + '/contents/generations/tasks')
            self.assertEqual(call.kwargs['headers']['Authorization'], 'Bearer test-key')
            payload = call.kwargs['json']
            self.assertTrue(payload['draft'])
            self.assertEqual(payload['resolution'], '480p')
            self.assertEqual(payload['ratio'], 'adaptive')
            self.assertEqual(payload['duration'], -1)
            self.assertEqual(payload['omni_reference_task_type'], 'edit')
            self.assertEqual([x['type'] for x in payload['content']], ['text', 'video_url', 'image_url'])
            self.assertEqual(payload['content'][1]['role'], 'reference_video')
            self.assertEqual(payload['content'][2]['role'], 'reference_image')
            self.assertEqual(payload['content'][1]['video_url']['url'], 'https://example.org/seedance-input.mp4')
            self.assertNotIn('test-key', (folder / 'seedance-request.json').read_text())

    def test_video_identity_remains_video_with_correct_image_number(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            folder = Path(directory)
            prepared(folder)
            post = mocks(stack)
            bridge.submit(folder, 'Replace subject', 'identity.mov', 'second.png')
            payload = post.call_args.kwargs['json']
            self.assertEqual([x['type'] for x in payload['content']], ['text', 'video_url', 'video_url', 'image_url'])
            text = payload['content'][0]['text']
            self.assertIn('@Video2 is only the primary character visual identity reference', text)
            self.assertIn('@Image1 is the secondary character reference', text)
            self.assertNotIn('@Image2', text)

    def test_secondary_image_uses_image2(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            folder = Path(directory)
            prepared(folder)
            post = mocks(stack)
            bridge.submit(folder, 'Replace subjects', 'identity.png', 'second.png')
            self.assertIn('@Image2 is the secondary character reference', post.call_args.kwargs['json']['content'][0]['text'])

    def test_timeout_guard_blocks_duplicate_paid_post(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            folder = Path(directory)
            prepared(folder)
            post = mocks(stack)
            post.side_effect = requests.Timeout('network interrupted')
            with self.assertRaisesRegex(RuntimeError, 'uncertain'):
                bridge.submit(folder, 'Replace', 'identity.png')
            self.assertTrue((folder / 'seedance-request.json').exists())
            with self.assertRaises(ValueError):
                bridge.submit(folder, 'Replace', 'identity.png')
            self.assertEqual(post.call_count, 1)

    def test_rejected_request_is_not_retried(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            folder = Path(directory)
            prepared(folder)
            post = mocks(stack, Mock(ok=False, status_code=403))
            with self.assertRaisesRegex(ValueError, 'HTTP 403'):
                bridge.submit(folder, 'Replace', 'identity.png')
            self.assertEqual(post.call_count, 1)
            self.assertTrue((folder / 'submission-error.json').exists())

    def test_collection_gets_direct_task_and_restores_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            response = Mock(status_code=200, json=lambda: {'status': 'succeeded', 'content': {'video_url': 'https://example.org/result.mp4'}})
            media = Mock(content=b'video')
            with patch('seedance_bridge.credential', return_value='test'), patch('seedance_bridge.setting', side_effect=settings), patch('seedance_bridge.requests.get', side_effect=[response, media]) as get, patch('seedance_bridge.finish_preview') as restore:
                bridge.wait_and_finish(directory, 'fake-id')
                self.assertEqual(get.call_args_list[0].args[0], bridge.DEFAULT_BASE + '/contents/generations/tasks/fake-id')
                self.assertNotIn('headers', get.call_args_list[1].kwargs)
                self.assertEqual((Path(directory) / 'seedance-result.mp4').read_bytes(), b'video')
                restore.assert_called_once()

    def test_failed_task_is_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            response = Mock(status_code=200, json=lambda: {'status': 'failed', 'error': {'code': 'InvalidInput'}})
            with patch('seedance_bridge.credential', return_value='test'), patch('seedance_bridge.requests.get', return_value=response), patch('seedance_bridge.finish_preview') as restore:
                with self.assertRaisesRegex(RuntimeError, 'InvalidInput'):
                    bridge.wait_and_finish(directory, 'task')
                restore.assert_not_called()

    def test_transient_poll_retries_get_only(self):
        with tempfile.TemporaryDirectory() as directory:
            transient = Mock(status_code=503)
            done = Mock(status_code=200, json=lambda: {'status': 'succeeded', 'content': {'video_url': 'https://example.org/video'}})
            with patch('seedance_bridge.credential', return_value='test'), patch('seedance_bridge.requests.get', side_effect=[transient, done, Mock(content=b'video')]) as get, patch('seedance_bridge.requests.post') as post, patch('seedance_bridge.time.sleep'), patch('seedance_bridge.finish_preview'):
                bridge.wait_and_finish(directory, 'task')
                self.assertEqual(get.call_count, 3)
                post.assert_not_called()

    def test_hd_reuses_only_draft_and_original_model(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            folder = Path(directory)
            for name in ['upload.mp4', 'final-preview.mp4']:
                (folder / name).write_bytes(b'test')
            (folder / 'generation.json').write_text(json.dumps({'request_id': 'draft'}))
            (folder / 'seedance-request.json').write_text(json.dumps({'draft': True, 'model': 'original-model'}))
            post = mocks(stack)
            self.assertEqual(bridge.submit_hd(folder), 'task-id')
            payload = post.call_args.kwargs['json']
            self.assertEqual(payload['model'], 'original-model')
            self.assertEqual(payload['content'], [{'type': 'draft_task', 'draft_task': {'id': 'draft'}}])
            self.assertEqual(payload['resolution'], '1080p')
            for forbidden in ['duration', 'ratio', 'generate_audio', 'omni_reference_task_type', 'draft']:
                self.assertNotIn(forbidden, payload)
            with self.assertRaises(ValueError):
                bridge.submit_hd(folder)
            self.assertEqual(post.call_count, 1)

    def test_hd_requires_completed_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'generation.json').write_text('{"request_id":"draft"}')
            (folder / 'seedance-request.json').write_text('{"draft":true}')
            with patch('seedance_bridge.requests.post') as post:
                with self.assertRaises(ValueError):
                    bridge.submit_hd(folder)
                post.assert_not_called()


class VideoValidationTests(unittest.TestCase):
    def video(self, seconds=10, width=854, height=480, rate=24):
        from fractions import Fraction
        stream = Mock(duration=seconds*24, time_base=Fraction(1, 24), width=width, height=height, average_rate=rate)
        source = Mock()
        source.streams.video = [stream]
        source.__enter__ = Mock(return_value=source)
        source.__exit__ = Mock(return_value=False)
        return source

    def test_combined_video_duration_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory)/'source.mp4', Path(directory)/'identity.mp4']
            for p in paths:
                p.write_bytes(b'video')
            with patch('av.open', side_effect=[self.video(25), self.video(10)]):
                with self.assertRaisesRegex(ValueError, 'total at most 30'):
                    bridge.validate_videos(paths)

    def test_valid_source_and_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory)/'source.mp4', Path(directory)/'identity.mov']
            for p in paths:
                p.write_bytes(b'video')
            with patch('av.open', side_effect=[self.video(20), self.video(10)]):
                bridge.validate_videos(paths)

    def test_low_resolution_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'source.mp4'
            path.write_bytes(b'video')
            with patch('av.open', return_value=self.video(width=320, height=240)):
                with self.assertRaisesRegex(ValueError, 'dimensions'):
                    bridge.validate_videos([path])

if __name__ == '__main__':
    unittest.main()
