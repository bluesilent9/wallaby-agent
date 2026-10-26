"""Dashboard browser access is independent of Core/node RPC and defaults off."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from configuration import Config
from runtime import apply_config, worker
from transport import ssh_command


class DashboardAccessTests(unittest.TestCase):
    def test_existing_v2_settings_keep_ddns_and_node_choices_dashboard_off(self):
        for ddns in (False, True):
            for node in (False, True):
                with self.subTest(ddns=ddns, node=node), tempfile.TemporaryDirectory() as root:
                    path = Path(root) / 'config.cfg'
                    path.write_text(f'[agent]\nhostname=server.example\nssh_user=wallet-laptop\n[services]\nddns={ddns}\nnode={node}\n')
                    config = Config(root)
                    self.assertEqual(config.values['enabled'], {'ddns': ddns, 'dashboard': False, 'node': node})
                    config.save(config.values)
                    self.assertEqual(Config(root).values, config.values)

    def test_dashboard_enable_and_disable_are_persistent_user_units(self):
        with tempfile.TemporaryDirectory() as root, patch('runtime.ctl') as ctl, patch('runtime.write_status'):
            config = Config(root)
            values = copy.deepcopy(config.values)
            values['hostname'] = 'server.example'
            values['enabled']['dashboard'] = True
            apply_config(config, values)
            calls = [call.args for call in ctl.call_args_list]
            self.assertIn(('enable', 'wallaby-agent-dashboard.service'), calls)
            self.assertIn(('restart', 'wallaby-agent-dashboard.service'), calls)
            self.assertTrue(Config(root).values['enabled']['dashboard'])
            self.assertFalse(Config(root).values['enabled']['node'])
            values = copy.deepcopy(config.values)
            values['enabled']['dashboard'] = False
            apply_config(config, values)
            self.assertIn(('disable', '--now', 'wallaby-agent-dashboard.service'), [call.args for call in ctl.call_args_list])
            self.assertFalse(Config(root).values['enabled']['dashboard'])

    def test_dashboard_and_node_forward_to_different_ipv6_ports(self):
        with tempfile.TemporaryDirectory() as root:
            config = Config(root).values
            config['hostname'] = 'server.example'
            dashboard = ssh_command(config, 'dashboard', 38951, '/tmp/dashboard.sock')
            node = ssh_command(config, 'node', 54321, '/tmp/node.sock')
            self.assertIn('[::1]:38951:[::1]:38951', dashboard)
            self.assertIn('[::1]:54321:[::1]:56443', node)
            self.assertIn('-6', dashboard)
            self.assertIn('StrictHostKeyChecking=yes', dashboard)

    def test_dashboard_worker_does_not_load_cookie_or_start_rpc_client(self):
        class Stop:
            done = False
            def is_set(self): return self.done
            def set(self): self.done = True
            def wait(self, delay): self.done = True; return True
        with tempfile.TemporaryDirectory() as root:
            config = Config(root).values
            config['hostname'] = 'server.example'
            config['enabled']['dashboard'] = True
            stop = Stop()
            tunnel = Mock(port=38951)
            tunnel.alive.return_value = True
            with patch('runtime.threading.Event', return_value=stop), patch('runtime.signal.signal'), patch('runtime.Config') as cfg, patch('runtime.Tunnel', return_value=tunnel), patch('runtime.runtime_dir', return_value=Path(root)), patch('runtime.discover_cookie') as cookie, patch('runtime.NodeClient') as node, patch('runtime.write_status') as status:
                cfg.return_value.values = config
                worker('dashboard')
                cookie.assert_not_called()
                node.assert_not_called()
                self.assertTrue(any(call.args[1] == 'green' for call in status.call_args_list))
                tunnel.close.assert_called_once()
