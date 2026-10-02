import tempfile
import unittest
from pathlib import Path

from optpilot.code_artifacts import CodeArtifactStore
from optpilot.storage import LocalEvidenceStore


class StoragePathTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source.py'
        self.source.write_text('pass\n', encoding='utf-8')

    def test_invalid_study_names_cannot_escape_output_root(self):
        root = self.root / 'runs'
        for name in ('../outside', '/outside', r'..\outside', 'C:outside', '', '.', '..'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                LocalEvidenceStore(root, name)
        self.assertFalse(root.exists())

    def test_invalid_artifact_ids_cannot_escape_store(self):
        root = self.root / 'artifacts'
        store = CodeArtifactStore(root)
        for name in ('../outside', '/outside', r'..\outside', 'C:outside', '.', '..'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                store.store_file(self.source, artifact_id=name)
        self.assertFalse(root.exists())

    def test_trial_ids_and_symlinked_trial_directories_are_bounded(self):
        store = LocalEvidenceStore(self.root / 'runs', 'valid-study')
        for name in ('../outside', '/outside', r'..\outside', 'C:outside', '.', '..'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                store.create_trial_workspace(name)
        self.assertEqual(store.create_trial_workspace('trial-1').parent, store.run_dir / 'trials')
        outside = self.root / 'outside'
        outside.mkdir()
        link = store.run_dir / 'trials' / 'linked-trial'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Symlink creation is not available')
        with self.assertRaises(ValueError):
            store.create_trial_workspace('linked-trial')
        self.assertEqual(list(outside.iterdir()), [])

    def test_unicode_names_and_valid_artifact_ids_still_work(self):
        store = LocalEvidenceStore(self.root / 'runs', '实验 study')
        self.assertTrue(store.run_dir.is_dir())
        artifact = CodeArtifactStore(self.root / 'artifacts').store_file(self.source, artifact_id='artifact-1')
        self.assertEqual(artifact['artifact_id'], 'artifact-1')
