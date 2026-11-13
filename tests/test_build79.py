"""Release labels must match actual worker/package identity before packaging."""
import importlib.util,shutil,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('release_check',ROOT/'packaging/release_check.py')
check=importlib.util.module_from_spec(spec);spec.loader.exec_module(check)


class ReleaseIdentity(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.root=Path(folder.name)
        for name in ('src/worker_upgrade.py','src/app.py','src/runtime.py','src/node_client.py','web/index.html'):
            target=self.root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,target)
    def test_current_release_is_consistent(self):
        self.assertEqual(check.release_version(self.root),('2.0.0~dev84',84))
    def test_old_or_duplicate_visible_badge_is_refused(self):
        p=self.root/'web/index.html';text=p.read_text()
        for bad in (text.replace('BUILD 84','BUILD 77'),text+' BUILD 84',text.replace('BUILD 84','')):
            p.write_text(bad)
            with self.assertRaises(ValueError):check.release_version(self.root)
    def test_old_health_monitor_or_transport_version_is_refused(self):
        for name in ('app.py','runtime.py','node_client.py'):
            p=self.root/'src'/name;text=p.read_text();p.write_text(text.replace('2.0.0~dev84','2.0.0~dev77'))
            with self.assertRaises(ValueError):check.release_version(self.root)
            p.write_text(text)
    def test_missing_or_malformed_worker_version_is_refused(self):
        p=self.root/'src/worker_upgrade.py';text=p.read_text()
        for bad in (text.replace('2.0.0~dev84','wrong'),text.replace('VERSION=','OLD_VERSION=')):
            p.write_text(bad)
            with self.assertRaises(ValueError):check.release_version(self.root)
