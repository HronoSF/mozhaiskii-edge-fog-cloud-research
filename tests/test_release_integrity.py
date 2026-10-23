"""Small synthetic manifest checks, not experiment evidence."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

path=Path(__file__).resolve().parents[1]/'scripts/verify_release.py'
spec=importlib.util.spec_from_file_location('release_verifier',path)
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='synthetic-manifest-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'data').write_text('synthetic fixture')
        self.row=hashlib.sha256((self.root/'data').read_bytes()).hexdigest()+'  data\n'
        (self.root/'MANIFEST.sha256').write_text(self.row)

    def test_valid(self):release.check_manifest(self.root)
    def test_changed_file(self):
        (self.root/'data').write_text('corrupt')
        with self.assertRaises(ValueError):release.check_manifest(self.root)
    def test_missing_manifest(self):
        (self.root/'MANIFEST.sha256').unlink()
        with self.assertRaises(ValueError):release.check_manifest(self.root)
    def test_duplicate_path(self):
        (self.root/'MANIFEST.sha256').write_text(self.row*2)
        with self.assertRaises(ValueError):release.check_manifest(self.root)
    def test_traversal(self):
        (self.root/'MANIFEST.sha256').write_text(self.row.replace('  data','  ../escape'))
        with self.assertRaises(ValueError):release.check_manifest(self.root)
    def test_empty(self):
        (self.root/'MANIFEST.sha256').write_text('')
        with self.assertRaises(ValueError):release.check_manifest(self.root)

    def test_untracked_copied_runtime_file_rejected(self):
        (self.root/'tests').mkdir();(self.root/'tests/check.py').write_text('synthetic')
        pins={'root.py':'unused','tests/check.py':'unused'}
        release.check_payload_files(self.root,pins)
        (self.root/'tests/untracked.py').write_text('unexpected input')
        with self.assertRaises(ValueError):release.check_payload_files(self.root,pins)

    def test_ignored_bytecode_is_not_a_payload_input(self):
        (self.root/'tests/__pycache__').mkdir(parents=True)
        (self.root/'tests/__pycache__/cached.pyc').write_bytes(b'synthetic')
        release.check_payload_files(self.root,{'root.py':'unused'})


if __name__=='__main__':unittest.main()
