"""V1-to-V2 compatibility and retirement of the old user tunnel."""
import copy
import json
import os
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from configuration import Config, SERVICES
from runtime import retire_jellyfin


class UpgradeTests(unittest.TestCase):
    def test_v1_migration_preserves_remaining_choices_and_connection_settings(self):
        for ddns in (False, True):
            for node in (False, True):
                with self.subTest(ddns=ddns, node=node), tempfile.TemporaryDirectory() as root:
                    config = Config(root)
                    values = copy.deepcopy(config.values)
                    values.update(hostname='server.example', ssh_user='wallet-laptop',
                                  ssh_port=2222, identity_file='/keys/id_ed25519',
                                  cookie='/bitcoin/.cookie', rpc_port=18332)
                    values['enabled'] = {'ddns': ddns, 'dashboard': False, 'node': node}
                    config.save(values)
                    with config.path.open('a') as stream:
                        stream.write('jellyfin = true\n')
                    migrated = Config(root)
                    self.assertEqual(migrated.values, values)
                    self.assertNotIn('jellyfin', migrated.path.read_text())
                    self.assertEqual(Config(root).values, values)
                    self.assertEqual(migrated.path.stat().st_mode & 0o777, 0o600)

    def test_stops_cached_unit_before_disable_and_removes_old_startup_and_status(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            link = base / 'systemd/user/default.target.wants/wallaby-agent-jellyfin.service'
            link.parent.mkdir(parents=True)
            link.symlink_to('/missing/old-unit.service')
            (base / 'jellyfin.json').write_text('{}')
            with patch.dict(os.environ, XDG_CONFIG_HOME=root), \
                    patch('runtime.subprocess.run', return_value=Mock(returncode=0)) as run, \
                    patch('runtime.ctl') as ctl, patch('runtime.Config') as config, \
                    patch('runtime.runtime_dir', return_value=base):
                retire_jellyfin()
                self.assertEqual([call.args[0] for call in run.call_args_list], [
                    ['systemctl', '--user', 'stop', 'wallaby-agent-jellyfin.service'],
                    ['systemctl', '--user', 'disable', 'wallaby-agent-jellyfin.service'],
                ])
                ctl.assert_called_once_with('daemon-reload')
                config.assert_called_once_with()
            self.assertFalse(link.is_symlink())
            self.assertFalse((base / 'jellyfin.json').exists())

    def test_missing_v1_unit_is_harmless_on_a_fresh_install(self):
        with tempfile.TemporaryDirectory() as root, \
                patch('runtime.subprocess.run', side_effect=[Mock(returncode=x) for x in (5, 4, 1, 1)]), \
                patch('runtime.ctl'), patch('runtime.Config'), \
                patch.dict(os.environ, XDG_CONFIG_HOME=root), \
                patch('runtime.runtime_dir', return_value=Path(root)):
            retire_jellyfin()

    def test_active_or_unreachable_service_manager_failure_is_reported(self):
        for state in (0, 1):
            with self.subTest(state=state), \
                    patch('runtime.subprocess.run', side_effect=[Mock(returncode=1), Mock(returncode=state)]), \
                    self.assertRaises(RuntimeError):
                retire_jellyfin()

    def test_bootstrap_retires_v1_before_starting_monitor(self):
        from app import bootstrap
        calls = []
        with tempfile.TemporaryDirectory() as root, patch('app.runtime_dir',return_value=Path(root)), patch('app.Config',return_value=Config(root)), patch('app.retire_jellyfin', side_effect=lambda: calls.append('retire')), \
                patch('app.ctl', side_effect=lambda *args: calls.append(args)):
            bootstrap()
        self.assertEqual(calls[0], 'retire')
        self.assertIn(('enable', '--now', 'wallaby-agent-monitor.service'), calls)

    def test_configuration_page_has_the_three_supported_services(self):
        class Page(HTMLParser):
            services = []
            def handle_starttag(self, tag, attrs):
                service = dict(attrs).get('data-service')
                if service:
                    self.services.append(service)
        page = Page()
        page.feed((Path(__file__).resolve().parents[1] / 'web/index.html').read_text())
        self.assertEqual(page.services, list(SERVICES))
        self.assertEqual(list(SERVICES), ['ddns', 'dashboard', 'node'])
