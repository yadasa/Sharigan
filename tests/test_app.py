import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import app

class AppTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)

    def test_health_and_static_assets(self):
        self.assertEqual(self.client.get('/health').json()['service'], 'Sharingan')
        for path in ['/', '/static/app.js', '/static/styles.css', '/static/sharingan.svg']:
            self.assertEqual(self.client.get(path).status_code, 200)

    def test_configuration_never_returns_credentials(self):
        with patch('config.setting', side_effect=lambda k,d='': 'private-test-key' if k.endswith(('KEY','TOKEN')) else d):
            response = self.client.get('/configuration')
            self.assertNotIn('private-test-key', response.text)
            self.assertTrue(response.json()['seedance_configured'])
            self.assertTrue(response.json()['preparation_configured'])

    def test_invalid_job_does_not_expose_files(self):
        self.assertEqual(self.client.get('/jobs/not-a-job').status_code, 404)
        self.assertEqual(self.client.get('/jobs/not-a-job/mask-review').status_code, 404)

    def test_generic_reference_form_fields(self):
        schema = app.app.openapi()
        route = schema['paths']['/jobs/{ident}/seedance']['post']
        ref = route['requestBody']['content']['multipart/form-data']['schema']['$ref'].split('/')[-1]
        fields = schema['components']['schemas'][ref]['properties']
        self.assertEqual(set(fields), {'prompt', 'reference', 'second_reference'})
