import unittest, tempfile, json
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch
import mask_review, seedance_bridge
from test_workflow import mocks, prepared

class FaceMeshTests(unittest.TestCase):
    def test_mesh_approval_tracks_overlay_and_audio_without_masks(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p/'workflow-mode.json').write_text('{"mode":"face_mesh"}')
            for n in ['original.mp4','face-landmarks.json','composite-silent.mp4','seedance-input.mp4']:
                (p/n).write_bytes(b'test')
            mask_review.review(p,True,'Full mesh reviewed',mask_review.fingerprint(p))
            mask_review.require_approved(p)
            (p/'seedance-input.mp4').write_bytes(b'changed')
            with self.assertRaises(ValueError):
                mask_review.require_approved(p)

    def test_mesh_submission_does_not_rebuild_depth_input(self):
        with tempfile.TemporaryDirectory() as d, ExitStack() as stack:
            p = Path(d)
            prepared(p)
            (p/'workflow-mode.json').write_text('{"mode":"face_mesh"}')
            post = mocks(stack)
            rebuild = stack.enter_context(patch('audio_workflow.prepare_seedance_video'))
            seedance_bridge.submit(p,'Replace subject','reference.png')
            rebuild.assert_not_called()
            payload = post.call_args.kwargs['json']
            text = payload['content'][0]['text']
            self.assertIn('Remove all face mesh lines',text)
            self.assertNotIn('colored-depth',text)
            self.assertTrue(payload['draft'])
