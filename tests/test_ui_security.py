import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from optpilot.ui.server import UiState, _encode_id, _handler_factory, run_ui


class UiBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runs = self.root / 'runs'
        self.runs.mkdir()
        self.state = UiState(cwd=self.root, catalog_roots=[self.root], run_roots=[self.runs])
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), _handler_factory(self.state))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_serves_ui_and_static_files(self):
        self.assertEqual(self.request('GET', '/')[0], 200)
        self.assertEqual(self.request('GET', '/static/app.js')[0], 200)

    def test_static_parent_paths_are_not_served(self):
        self.assertEqual(self.request('GET', '/static/../server.py')[0], 404)
        self.assertEqual(self.request('GET', '/static/../../config.py')[0], 404)

    def test_run_ids_are_scoped_to_configured_roots(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'study_spec.json').write_text('{}', encoding='utf-8')
        self.assertEqual(self.request('GET', f'/api/runs/{_encode_id(outside)}')[0], 404)
        inside = self.runs / 'inside'
        inside.mkdir()
        (inside / 'study_spec.json').write_text('{}', encoding='utf-8')
        self.assertEqual(self.request('GET', f'/api/runs/{_encode_id(inside)}')[0], 200)

    def test_run_metadata_symlinks_do_not_read_outside_files(self):
        run = self.runs / 'linked-metadata'
        run.mkdir()
        (run / 'study_spec.json').write_text('{}', encoding='utf-8')
        external = self.root / 'external.json'
        external.write_text('{"private_marker": "outside"}', encoding='utf-8')
        try:
            for name in ('summary.json', 'observations.jsonl', 'trials.jsonl', 'artifacts.jsonl'):
                (run / name).symlink_to(external)
        except (OSError, NotImplementedError):
            self.skipTest('Symlink creation is not available')
        for suffix in ('', '/observations', '/trials', '/artifacts'):
            status, body = self.request('GET', f'/api/runs/{_encode_id(run)}{suffix}')
            self.assertEqual(status, 200)
            self.assertNotIn('private_marker', json.dumps(json.loads(body)))

    def test_run_directory_symlinks_are_not_listed(self):
        external = self.root / 'external-run'
        external.mkdir()
        (external / 'study_spec.json').write_text('{}', encoding='utf-8')
        try:
            (self.runs / 'linked-run').symlink_to(external, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Symlink creation is not available')
        status, body = self.request('GET', '/api/runs')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['runs'], [])

    def test_foreign_origin_and_host_are_rejected(self):
        for headers in ({'Origin': 'https://example.org'}, {'Host': 'example.org'}, {'Sec-Fetch-Site': 'cross-site'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request('GET', '/api/health', headers=headers)[0], 403)
                with patch.object(self.state, 'launch_study') as launch:
                    self.assertEqual(self.request('POST', '/api/studies/launch', '{}', headers)[0], 403)
                    launch.assert_not_called()

    def test_mutations_require_bounded_json_objects(self):
        endpoint = '/api/studies/validate'
        self.assertEqual(self.request('POST', endpoint, '{}', {'Content-Type': 'text/plain'})[0], 415)
        for payload in ('[]', 'null', '{'):
            self.assertEqual(self.request('POST', endpoint, payload, {'Content-Type': 'application/json'})[0], 400)
        self.assertEqual(self.request('POST', endpoint, '{}', {'Content-Type': 'application/json', 'Content-Length': '1000001'})[0], 413)
        with patch('optpilot.ui.server._validate_study', return_value={'valid': True}):
            self.assertEqual(self.request('POST', endpoint, '{"study_path":"test.yaml"}', {'Content-Type': 'application/json'})[0], 200)

    def test_remote_bind_is_rejected_before_startup(self):
        with self.assertRaisesRegex(ValueError, 'unauthenticated UI'):
            run_ui(host='0.0.0.0')
