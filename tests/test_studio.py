import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import mask_review
import studio
from pipeline import writer, put, finish
from test_workflow import prepared


class StudioTests(unittest.TestCase):
    def test_local_readiness_keeps_preparation_and_generation_separate(self):
        def setting(key, default=''):
            return 'fake-replicate-token' if key == 'REPLICATE_API_TOKEN' else default
        with patch('studio.setting', side_effect=setting), patch('studio.shutil.which', return_value='rubberband'), patch('studio.mesh_python', return_value=None):
            result = studio.readiness()
        self.assertTrue(result['modes']['depth'])
        self.assertFalse(result['modes']['face_mesh'])
        self.assertFalse(result['modes']['depth_mesh'])
        self.assertFalse(result['generation_ready'])
        self.assertNotIn('fake-replicate-token', str(result))

    def test_placeholder_keys_are_not_reported_ready(self):
        with patch('studio.setting', side_effect=lambda key, default='': 'your_api_key' if key.endswith(('KEY', 'TOKEN')) else default), patch('studio.mesh_python', return_value=None):
            result = studio.readiness()
        self.assertFalse(result['preparation_configured'])
        self.assertFalse(result['seedance_configured'])

    def test_inspection_rejects_silent_source_but_allows_silent_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'silent.mp4'
            container, stream = writer(path, 64, 64)
            for i in range(96):
                put(container, stream, np.zeros((64, 64, 3), dtype=np.uint8), i)
            finish(container, stream)
            source = studio.media_info(path, source=True)
            identity = studio.media_info(path)
        self.assertFalse(source['valid'])
        self.assertIn('audio track', source['issues'][0])
        self.assertTrue(identity['valid'])
        self.assertEqual(identity['duration'], 4)

    def test_failed_repair_invalidates_previous_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            prepared(folder)
            (folder / 'manifest.json').write_text('{"prompt":"person"}')
            (folder / 'draft-preview.json').write_text('{}')
            mask_review.review(folder, True, 'Reviewed', mask_review.fingerprint(folder))
            with patch('raw_masks.segment_raw', side_effect=RuntimeError('Provider unavailable')):
                with self.assertRaisesRegex(RuntimeError, 'Provider unavailable'):
                    studio.repair_rgb(folder)
            self.assertFalse((folder / 'mask-review.json').exists())
            self.assertFalse((folder / 'draft-preview.json').exists())
            self.assertFalse(mask_review.state(folder)['approved'])


if __name__ == '__main__':
    unittest.main()
