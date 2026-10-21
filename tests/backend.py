"""Integration tests with real jshn, UCI and BusyBox ash, in a temporary tree.

Usage: python3 tests/backend.py --tools /path/to/openwrt-host-tools
The prefix must contain bin/{jshn,uci} and share/libubox/jshn.sh.
Only server-controlled paths are substituted in a temporary copy of the plugin.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

parser = argparse.ArgumentParser()
parser.add_argument('--tools', required=True, type=Path)
args, remaining = parser.parse_known_args()
TOOLS = args.tools.resolve()
PLUGIN = Path('luci-app-byedpi/root/usr/libexec/rpcd/luci.byedpi').read_text()


class BackendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='byedpi-test-')
        self.root = Path(self.tmp.name)
        self.config = self.root / 'etc/config/byedpi'
        self.config.parent.mkdir(parents=True)
        (self.root / 'var/lock').mkdir(parents=True)
        self.initial = "# retain comments\n\nconfig byedpi 'main'\n\toption enabled '1'\n\tlist split '1'\n\tlist split '2+s'\n\nconfig other 'unknown'\n\toption keep 'yes'\n\n"
        self.config.write_text(self.initial)
        self.config.chmod(0o640)
        source = PLUGIN.replace('/usr/share/libubox/jshn.sh', str(TOOLS / 'share/libubox/jshn.sh'))
        for prefix in ['/etc/config', '/var/lock', '/tmp/.uci', '/var/run/rpcd', '/tmp/run/rpcd']:
            source = source.replace(prefix, str(self.root) + prefix)
        self.plugin = self.root / 'plugin'

        # Only the service/procd boundary is mocked; the handler itself runs as ash.
        self.commands = self.root / 'commands'
        self.commands.mkdir()
        self.actions = self.root / 'actions'
        init = self.root / 'init'
        init.write_text('#!/bin/sh\nprintf "%s\\n" "$1" >> "' + str(self.actions) + '"\nexit "${INIT_EXIT:-0}"\n')
        init.chmod(0o755)
        (self.commands / 'ubus').write_text('#!/bin/sh\nprintf \'%s\\n\' \'{"byedpi":{"instances":{}}}\'\n')
        (self.commands / 'jsonfilter').write_text('#!/bin/sh\ncat >/dev/null\nprintf "%s\\n" "${RUNNING:-true}"\n')
        for command in self.commands.iterdir():
            command.chmod(0o755)
        source = source.replace('/etc/init.d/byedpi', str(init))
        self.plugin.write_text(source)
        self.env = dict(os.environ, PATH=str(self.commands) + ':' + str(TOOLS / 'bin') + ':' + os.environ['PATH'],
                        LD_LIBRARY_PATH=str(TOOLS / 'lib'))

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, method, **data):
        result = subprocess.run(['busybox', 'ash', str(self.plugin), 'call', method],
                                input=json.dumps(data) + '\n', text=True, capture_output=True,
                                env=self.env, check=True)
        self.assertEqual(result.stderr, '')
        return json.loads(result.stdout)

    def save(self, content, revision=None):
        if revision is None:
            revision = hashlib.sha256(self.config.read_bytes()).hexdigest()
        return self.call('write', content=content, revision=revision)

    def test_read_preserves_bytes_and_revision(self):
        result = self.call('read')
        self.assertTrue(result['ok'])
        self.assertEqual(result['content'], self.initial)
        self.assertEqual(result['revision'], hashlib.sha256(self.initial.encode()).hexdigest())

    def test_valid_write_preserves_format_permissions_unknown_sections(self):
        content = self.initial.replace("enabled '1'", "enabled '0'") + '# end\n\n'
        self.assertTrue(self.save(content)['ok'])
        self.assertEqual(self.config.read_text(), content)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o640)
        self.assertEqual(list(self.config.parent.glob('.byedpi-luci.*')), [])

    def test_invalid_syntax_does_not_replace_file(self):
        self.assertFalse(self.save("config byedpi 'unclosed\n")['ok'])
        self.assertEqual(self.config.read_text(), self.initial)

    def test_stale_revision_does_not_replace_external_changes(self):
        token = self.call('read')['revision']
        self.config.write_text(self.initial + '# external\n')
        self.assertFalse(self.save(self.initial, token)['ok'])
        self.assertTrue(self.config.read_text().endswith('# external\n'))

    def test_pending_uci_changes_block_read_and_write(self):
        delta = self.root / 'var/run/rpcd/uci-session/byedpi'
        delta.parent.mkdir(parents=True)
        delta.write_text('byedpi.main.enabled=0\n')
        self.assertFalse(self.call('read')['ok'])
        self.assertFalse(self.save(self.initial)['ok'])

    def test_lock_blocks_concurrent_write(self):
        (self.root / 'var/lock/luci-byedpi.lock').mkdir()
        self.assertFalse(self.save(self.initial)['ok'])

    def test_shell_metacharacters_are_literal_data(self):
        marker = self.root / 'INJECTED'
        content = self.initial + f'# $(touch {marker}) `touch {marker}` ; & |\n'
        self.assertTrue(self.save(content)['ok'])
        self.assertFalse(marker.exists())
        self.assertEqual(self.config.read_text(), content)

    def test_symlink_is_rejected(self):
        other = self.root / 'other'
        self.config.rename(other)
        self.config.symlink_to(other)
        self.assertFalse(self.call('read')['ok'])
        self.assertFalse(self.save(self.initial)['ok'])

    def test_size_limit(self):
        self.assertFalse(self.save('#' + 'x' * 65536)['ok'])

    def test_unknown_action_is_rejected(self):
        self.assertFalse(self.call('action', action='start; touch /tmp/injected')['ok'])

    def test_unknown_method_is_rejected(self):
        self.assertFalse(self.call('execute')['ok'])

    def test_allowed_actions_call_the_existing_init_script(self):
        for action in ['start', 'stop', 'restart', 'enable', 'disable']:
            self.assertTrue(self.call('action', action=action)['ok'])
        self.assertEqual(self.actions.read_text().splitlines(), ['start', 'stop', 'restart', 'enable', 'disable'])

    def test_init_failure_is_reported(self):
        self.env['INIT_EXIT'] = '1'
        self.assertFalse(self.call('action', action='start')['ok'])

    def test_zero_init_exit_without_running_instance_is_reported(self):
        self.env['RUNNING'] = 'false'
        self.assertFalse(self.call('action', action='start')['ok'])

    def test_editor_does_not_restart_service(self):
        self.assertTrue(self.call('read')['ok'])
        self.assertTrue(self.save(self.initial + '# edited\n')['ok'])
        self.assertFalse(self.actions.exists())


if __name__ == '__main__':
    unittest.main(argv=['backend.py'] + remaining)
