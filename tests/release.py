"""Offline tests for universal packages, release assembly and installation."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pty
import subprocess
import tempfile
import textwrap
import unittest
from unittest.mock import patch


def load_script(name, filename):
    specification = importlib.util.spec_from_file_location(name, filename)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


sdk_script = load_script('openwrt_sdk', 'scripts/openwrt-sdk.py')
release_script = load_script('prepare_release', 'scripts/prepare-release.py')


class SDKTests(unittest.TestCase):
    def setUp(self):
        self.pages = {sdk_script.DOWNLOADS: '<a href="24.10.4/">old</a><a href="24.10.5/">stable</a>'
                      '<a href="25.12.0/">stable</a><a href="25.12.1-rc1/">rc</a>'}

        for version in ('24.10.5', '25.12.0'):
            filename = f'openwrt-sdk-{version}-x86-64_gcc-13.3.0_musl.Linux-x86_64.tar.zst'
            url = sdk_script.DOWNLOADS + version + '/targets/x86/64/sha256sums'
            self.pages[url] = 'a' * 64 + ' *' + filename + '\n'

        self.mock = patch.object(sdk_script, 'fetch_text', side_effect=lambda url: self.pages[url])
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def test_latest_stable_sdk_is_selected(self):
        record = sdk_script.resolve_sdk('24.10')
        self.assertEqual(record['openwrt_version'], '24.10.5')
        self.assertEqual(record['family'], '24.10')
        self.assertNotIn('architecture', record)
        self.assertNotIn('target', record)

    def test_second_family_is_resolved(self):
        self.assertEqual(sdk_script.resolve_sdk('25.12')['openwrt_version'], '25.12.0')

    def test_unsupported_family_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            sdk_script.resolve_sdk('23.05')

    def test_missing_sdk_is_rejected(self):
        self.pages[sdk_script.DOWNLOADS + '24.10.5/targets/x86/64/sha256sums'] = ''
        with self.assertRaisesRegex(ValueError, 'Expected one SDK'):
            sdk_script.resolve_sdk('24.10')

    def test_invalid_sdk_checksum_is_rejected(self):
        url = sdk_script.DOWNLOADS + '24.10.5/targets/x86/64/sha256sums'
        self.pages[url] = self.pages[url].replace('a' * 64, 'invalid')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            sdk_script.resolve_sdk('24.10')


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='byedpi-release-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.artifacts = self.root / 'artifacts'
        self.artifacts.mkdir()
        self.output = self.root / 'release'

        for family, version, extension in [('24.10', '24.10.5', 'ipk'), ('25.12', '25.12.0', 'apk')]:
            filename = f'luci-app-byedpi-1.0.0-r1-openwrt-{family}-all.{extension}'
            package = self.artifacts / filename
            package.write_bytes(b'package fixture')
            record = {
                'family': family, 'openwrt_version': version,
                'sdk_url': 'https://downloads.openwrt.org/sdk.tar.zst',
                'sdk_sha256': 'a' * 64, 'filename': filename,
                'sha256': hashlib.sha256(package.read_bytes()).hexdigest(),
            }
            (self.artifacts / f'{family}.json').write_text(json.dumps(record))

        self.record_path = self.artifacts / '24.10.json'
        self.completed = json.loads(self.record_path.read_text())
        self.package = self.artifacts / self.completed['filename']

    def prepare(self):
        release_script.prepare_release(self.artifacts, self.output)

    def test_release_contains_packages_and_metadata_without_installer(self):
        self.prepare()
        self.assertFalse((self.output / 'install.sh').exists())
        self.assertNotIn('install.sh', (self.output / 'SHA256SUMS').read_text())
        self.assertEqual(len(list(self.output.glob('*.ipk'))), 1)
        self.assertEqual(len(list(self.output.glob('*.apk'))), 1)
        self.assertEqual(len((self.output / 'packages.tsv').read_text().splitlines()), 3)
        self.assertTrue((self.output / 'build-info.json').is_file())
        self.assertTrue((self.output / 'SHA256SUMS').is_file())

    def test_missing_family_is_rejected(self):
        self.record_path.unlink()
        with self.assertRaisesRegex(ValueError, 'Missing builds'):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_corrupt_package_is_rejected(self):
        self.package.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            self.prepare()

    def test_mismatched_sdk_version_is_rejected(self):
        self.completed['openwrt_version'] = '25.12.0'
        self.record_path.write_text(json.dumps(self.completed))
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.prepare()

    def test_wrong_package_format_is_rejected(self):
        self.completed['filename'] = self.completed['filename'].replace('.ipk', '.apk')
        self.record_path.write_text(json.dumps(self.completed))
        with self.assertRaisesRegex(ValueError, 'Invalid package filename'):
            self.prepare()


class ReleaseTagTests(unittest.TestCase):
    def validate(self, tag):
        workflow = Path('.github/workflows/release.yml').read_text()
        source = textwrap.dedent(workflow.split("python3 - <<'PY'\n", 1)[1].split('          PY\n', 1)[0])
        with tempfile.TemporaryDirectory(prefix='byedpi-release-tag-') as directory:
            root = Path(directory)
            (root / 'luci-app-byedpi').mkdir()
            (root / 'luci-app-byedpi/Makefile').write_text('PKG_VERSION:=0.0.1\nPKG_RELEASE:=2\n')
            output = root / 'output'
            result = subprocess.run(['python3', '-c', source], cwd=root,
                                    env=dict(os.environ, RELEASE_TAG=tag, GITHUB_OUTPUT=str(output)),
                                    capture_output=True, text=True, timeout=10)
            return result, output.read_text() if output.exists() else ''

    def test_version_and_matching_revision_tags_are_accepted(self):
        for tag in ('v0.0.1', 'v0.0.1-r2'):
            with self.subTest(tag=tag):
                result, output = self.validate(tag)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output, f'tag={tag}\n')

    def test_incorrect_version_or_revision_is_rejected(self):
        for tag in ('v0.0.2', 'v0.0.1-r1', 'v0.0.1-r0', 'v0.0.1-r2-extra'):
            with self.subTest(tag=tag):
                result, output = self.validate(tag)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('must equal', result.stderr)
                self.assertEqual(output, '')


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='byedpi-installer-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.commands = self.root / 'bin'
        self.commands.mkdir()
        self.assets = self.root / 'assets'
        self.assets.mkdir()
        self.log = self.root / 'commands.log'
        self.release_file = self.root / 'openwrt_release'
        self.service = self.root / 'byedpi'
        self.service.write_text('#!/bin/sh\nexit 0\n')
        self.service.chmod(0o755)
        self.config = self.root / 'config'
        self.config.write_text("config byedpi 'main'\n")
        self.installer = self.root / 'install.sh'
        source = Path('install.sh').read_text()

        for original, replacement in [('/etc/openwrt_release', self.release_file),
                                      ('/etc/init.d/byedpi', self.service),
                                      ('/usr/bin/ciadpi', self.service),
                                      ('/etc/config/byedpi', self.config),
                                      ('/dev/tty', self.root / 'no-tty'),
                                      ('/tmp/luci-byedpi-install.XXXXXX', self.root / 'download.XXXXXX'),
                                      ('/etc/init.d/rpcd', self.commands / 'rpcd')]:
            source = source.replace(original, str(replacement))

        self.installer.write_text(source)
        self.env = dict(os.environ, PATH=str(self.commands) + ':' + os.environ['PATH'],
                        INSTALLER_LOG=str(self.log), FIXTURE_ASSETS=str(self.assets),
                        TEST_ARCHITECTURE='x86_64', TEST_CORE_SERVICE=str(self.service),
                        TEST_CORE_CONFIG=str(self.config), TEST_CORE_VERSION=str(self.root / 'core-version'))

        self.command('id', '#!/bin/sh\nprintf "0\\n"\n')
        self.command('curl', '''#!/usr/bin/env python3
import os
from pathlib import Path
import shutil
import sys
arguments = sys.argv[1:]
destination = arguments[arguments.index('--output') + 1]
url = arguments[-1]
with open(os.environ['INSTALLER_LOG'], 'a') as output:
    output.write('download ' + url + '\\n')
    output.write('download-options ' + ' '.join(arguments[:-1]) + '\\n')
source = Path(os.environ['FIXTURE_ASSETS']) / url.rsplit('/', 1)[-1]
if destination == '-':
    sys.stdout.buffer.write(source.read_bytes())
else:
    shutil.copyfile(source, destination)
''')

        self.command('wget', (self.commands / 'curl').read_text().replace("'--output'", "'-O'"))

        jsonfilter_mock = '''#!/usr/bin/env python3
import json
from pathlib import Path
import re
import sys
arguments = sys.argv[1:]
value = json.loads(Path(arguments[arguments.index('-i') + 1]).read_text())
expression = arguments[arguments.index('-e') + 1]
if expression == '@[@.draft=false && @.prerelease=false].tag_name':
    values = [item['tag_name'] for item in value if not item['draft'] and not item['prerelease']]
elif expression == '@.assets[*].name':
    values = [asset['name'] for asset in value['assets']]
else:
    name = re.fullmatch(r'@\\.assets\\[@\\.name="([^"]+)"\\]\\.digest', expression).group(1)
    values = [asset.get('digest') for asset in value['assets'] if asset['name'] == name]
for value in values:
    if value is not None:
        print(value)
'''
        if os.environ.get('JSONFILTER_BINARY'):
            jsonfilter_mock = '#!/bin/sh\nexec "$JSONFILTER_BINARY" "$@"\n'
        self.command('jsonfilter', jsonfilter_mock)
        self.env['TEST_JSONFILTER_SOURCE'] = str(self.root / 'jsonfilter-template')
        (self.root / 'jsonfilter-template').write_text(jsonfilter_mock)

        self.command('mock-core-install', '''#!/usr/bin/env python3
import os
from pathlib import Path
import sys
if os.environ.get('OMIT_CORE_FILES') != '1':
    service = Path(os.environ['TEST_CORE_SERVICE'])
    service.write_text('#!/bin/sh\\nexit 0\\n')
    service.chmod(0o755)
Path(os.environ['TEST_CORE_CONFIG']).write_text("config byedpi 'main'\\n# package default\\n")
if os.environ.get('CORE_PACKAGE_EXIT', '0') == '0' and os.environ.get('SKIP_VERSION_CHANGE') != '1':
    filename = next(Path(arg).name for arg in sys.argv[1:] if Path(arg).name.startswith('byedpi_'))
    version = filename[len('byedpi_'):].rsplit('_' + os.environ['TEST_ARCHITECTURE'] + '.', 1)[0]
    Path(os.environ['TEST_CORE_VERSION']).write_text(version)
sys.exit(int(os.environ.get('CORE_PACKAGE_EXIT', '0')))
''')

        self.command('mock-version-compare', '''#!/usr/bin/env python3
import re
import sys
left, operator, right = sys.argv[1:]
numbers = lambda value: tuple(int(number) for number in re.findall(r'\\d+', value))
comparison = (numbers(left) > numbers(right)) - (numbers(left) < numbers(right))
if operator == 'apk':
    print({-1: '<', 0: '=', 1: '>'}[comparison])
else:
    sys.exit(0 if (comparison > 0 if operator in ('gt', '>>') else comparison == 0) else 1)
''')

        manager_script = '''#!/bin/sh
printf '%s %s\\n' "${0##*/}" "$*" >> "$INSTALLER_LOG"
if [ "$1" = print-architecture ]; then
    printf 'arch all 1\\narch %s 10\\n' "$TEST_ARCHITECTURE"
elif [ "$1" = --print-arch ]; then
    printf '%s\\n' "${TEST_APK_ARCHITECTURE:-$TEST_ARCHITECTURE}"
elif [ "$1" = update ]; then
    printf 'repository index download\\n'
    printf 'package index summary\\n' >&2
    exit "${UPDATE_EXIT:-0}"
elif [ "$1" = status ] || [ "$1" = info ]; then
    version=
    [ ! -f "$TEST_CORE_VERSION" ] || version=$(cat "$TEST_CORE_VERSION")
    if [ -n "$version" ]; then
        if [ "$1" = status ]; then
            printf 'Version: %s\\n' "$version"
        else
            printf 'byedpi-%s\\n' "$version"
        fi
    fi
elif [ "$1" = compare-versions ]; then
    mock-version-compare "$2" "$3" "$4"
    exit $?
elif [ "$1" = version ]; then
    mock-version-compare "$3" apk "$4"
    exit $?
fi
if [ "$1" = install ] || [ "$1" = add ]; then
    case "$*" in
        */byedpi_*) mock-core-install "$@"; exit $? ;;
        *jsonfilter*)
            cp "$TEST_JSONFILTER_SOURCE" "${0%/*}/jsonfilter"
            chmod 755 "${0%/*}/jsonfilter"
            ;;
    esac
    exit "${PACKAGE_EXIT:-0}"
fi
'''
        self.command('opkg', manager_script)
        self.command('apk', manager_script)
        self.command('rpcd', '#!/bin/sh\nprintf "rpcd %s\\n" "$*" >> "$INSTALLER_LOG"\n')
        self.configure()

    def command(self, name, source):
        path = self.commands / name
        path.write_text(source)
        path.chmod(0o755)

    def configure(self, version='24.10.5'):
        # Deliberately omit DISTRIB_ARCH and DISTRIB_TARGET: neither is required.
        self.release_file.write_text(f"DISTRIB_RELEASE='{version}'\n")
        family = '.'.join(version.split('.')[:2])
        extension = 'ipk' if version.startswith('24.10') else 'apk'
        self.filename = f'luci-app-byedpi-1.0.0-r1-openwrt-{family}-all.{extension}'
        self.package = self.assets / self.filename
        self.package.write_bytes(b'package fixture')
        checksum = hashlib.sha256(self.package.read_bytes()).hexdigest()
        self.manifest = self.assets / 'packages.tsv'
        self.manifest.write_text(f'{family}\t{self.filename}\t{checksum}\n')

    def run_command(self, arguments, answer=None):
        if answer is None:
            return subprocess.run(arguments, stdin=subprocess.DEVNULL, text=True,
                                  capture_output=True, env=self.env, timeout=10)

        terminal, input_fd = pty.openpty()
        try:
            os.write(terminal, answer.encode())
            return subprocess.run(arguments, stdin=input_fd, text=True,
                                  capture_output=True, env=self.env, timeout=10)
        finally:
            os.close(input_fd)
            os.close(terminal)

    def run_installer(self, tag='latest', answer=None):
        return self.run_command(['busybox', 'ash', str(self.installer), 'example/luci-app-byedpi', tag], answer)

    def prepare_core(self, family='24.10', architecture='x86_64', digest=True):
        self.service.unlink()
        with self.release_file.open('a') as release:
            release.write(f"DISTRIB_ARCH='{architecture}'\n")
        self.env['TEST_ARCHITECTURE'] = architecture
        extension = 'ipk' if family == '24.10' else 'apk'
        self.core_filename = f'byedpi_0.17.3-r1_{architecture}.{extension}'
        self.core_package = self.assets / self.core_filename
        self.core_package.write_bytes(b'core package fixture')
        releases = [
            {'tag_name': 'v0.17.3-generic', 'draft': False, 'prerelease': False},
            {'tag_name': f'v0.17.4-{family}', 'draft': False, 'prerelease': True},
            {'tag_name': 'v0.17.3-23.05', 'draft': False, 'prerelease': False},
            {'tag_name': f'v0.17.3-{family}', 'draft': False, 'prerelease': False},
        ]
        (self.assets / 'releases?per_page=100').write_text(json.dumps(releases))
        self.core_release = self.assets / f'v0.17.3-{family}'
        self.core_release.write_text(json.dumps({'assets': [{
            'name': self.core_filename,
            'digest': 'sha256:' + hashlib.sha256(self.core_package.read_bytes()).hexdigest() if digest else None,
        }]}))

    def prepare_update(self, installed_version='0.17.2-r1', family='24.10'):
        if family == '25.12':
            self.configure(version='25.12.0')
        self.prepare_core(family=family)
        self.service.write_text('#!/bin/sh\nexit 0\n')
        self.service.chmod(0o755)
        Path(self.env['TEST_CORE_VERSION']).write_text(installed_version)

    def assert_not_installed(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        log = self.log.read_text() if self.log.exists() else ''
        self.assertNotIn('opkg install', log)
        self.assertNotIn('apk add', log)
        self.assertNotIn('rpcd restart', log)

    def test_opkg_exact_match_and_core_configuration_preserved(self):
        original = self.config.read_bytes()
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('opkg install', self.log.read_text())
        self.assertIn('rpcd restart', self.log.read_text())
        self.assertEqual(self.config.read_bytes(), original)

    def test_apk_installation(self):
        self.configure(version='25.12.0')
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('apk add --allow-untrusted', self.log.read_text())

    def test_same_stable_family_fallback(self):
        self.configure(version='24.10.4')
        self.assertEqual(self.run_installer().returncode, 0)

    def test_specific_release_tag(self):
        self.assertEqual(self.run_installer('v1.0.0').returncode, 0)
        self.assertIn('/releases/download/v1.0.0/', self.log.read_text())

    def test_specific_revision_tag(self):
        self.assertEqual(self.run_installer('v1.0.0-r2').returncode, 0)
        self.assertIn('/releases/download/v1.0.0-r2/', self.log.read_text())

    def test_checksum_mismatch_prevents_installation(self):
        self.package.write_bytes(b'corrupted download')
        self.assert_not_installed(self.run_installer())

    def test_unlisted_openwrt_family_prevents_installation(self):
        self.manifest.write_text(self.manifest.read_text().replace('24.10', '25.12'))
        self.assert_not_installed(self.run_installer())

    def test_missing_service_prevents_downloads(self):
        self.service.unlink()
        result = self.run_installer()
        self.assert_not_installed(result)
        self.assertIn('interactive terminal', result.stderr)
        self.assertFalse(self.log.exists())

    def test_ambiguous_manifest_is_rejected(self):
        self.manifest.write_text(self.manifest.read_text() * 2)
        self.assert_not_installed(self.run_installer())

    def test_path_traversal_filename_is_rejected(self):
        self.manifest.write_text(self.manifest.read_text().replace(self.filename, '../outside.ipk'))
        self.assert_not_installed(self.run_installer())

    def test_snapshot_is_rejected(self):
        self.configure(version='24.10-SNAPSHOT')
        self.assert_not_installed(self.run_installer())

    def test_package_manager_failure_is_not_reported_as_success(self):
        self.env['PACKAGE_EXIT'] = '1'
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('Installed successfully', result.stdout)
        self.assertNotIn('rpcd restart', self.log.read_text())

    def test_wget_only_router(self):
        source = self.installer.read_text().replace('command -v curl >/dev/null 2>&1', 'false')
        self.installer.write_text(source)
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('download-options -q -O', self.log.read_text())

    def test_curl_disables_progress_but_keeps_errors(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--silent --show-error', self.log.read_text())

    def test_successful_index_update_hides_repository_output(self):
        for version in ('24.10.5', '25.12.5'):
            with self.subTest(version=version):
                self.configure(version)
                result = self.run_installer()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('Updating package lists...', result.stdout)
                self.assertNotIn('repository index download', result.stdout + result.stderr)
                self.assertNotIn('package index summary', result.stdout + result.stderr)

    def test_failed_index_update_shows_diagnostics_and_stops(self):
        self.env['UPDATE_EXIT'] = '3'
        for version in ('24.10.5', '25.12.5'):
            with self.subTest(version=version):
                self.configure(version)
                result = self.run_installer()
                self.assertEqual(result.returncode, 3)
                self.assertIn('repository index download', result.stderr)
                self.assertIn('package index summary', result.stderr)
                self.assert_not_installed(result)

    def test_missing_download_prevents_installation(self):
        self.package.unlink()
        self.assert_not_installed(self.run_installer())

    def test_wrong_package_format_is_rejected(self):
        self.manifest.write_text(self.manifest.read_text().replace('.ipk', '.apk'))
        self.assert_not_installed(self.run_installer())

    def test_router_architecture_and_target_are_not_used(self):
        with self.release_file.open('a') as release:
            release.write("DISTRIB_ARCH='mips_24kc'\nDISTRIB_TARGET='ath79/generic'\n")

        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(self.filename, self.log.read_text())

    def run_one_line_installation(self, answer=None):
        (self.assets / 'install.sh').write_text(self.installer.read_text())

        return self.run_command([
            'busybox', 'ash', '-c',
            'sh <(wget -q -O - https://raw.githubusercontent.com/qb60/luci-app-byedpi/main/install.sh)',
        ], answer)

    def test_one_line_installation_without_arguments(self):
        result = self.run_one_line_installation()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('opkg install', self.log.read_text())
        self.assertIn('Installed successfully', result.stdout)
        self.assertIn('download https://raw.githubusercontent.com/qb60/luci-app-byedpi/main/install.sh', self.log.read_text())
        self.assertIn('download https://github.com/qb60/luci-app-byedpi/releases/latest/download/packages.tsv', self.log.read_text())

    def test_one_line_apk_installation_without_arguments(self):
        self.configure(version='25.12.0')
        result = self.run_one_line_installation()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('apk add --allow-untrusted', self.log.read_text())

    def test_core_installation_precedes_interface_and_preserves_configuration(self):
        self.prepare_core(architecture='mips_24kc')
        self.config.chmod(0o640)
        original = self.config.read_bytes()
        result = self.run_installer(answer='yes\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.log.read_text()
        install_log = '\n'.join(line for line in log.splitlines() if line.startswith('opkg install'))
        self.assertLess(install_log.index('/' + self.core_filename), install_log.index('/' + self.filename))
        self.assertIn('/releases/download/v0.17.3-24.10/', log)
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o640)
        self.assertEqual(log.count('opkg update'), 1)

    def test_core_apk_uses_openwrt_cpu_variant_instead_of_generic_abi(self):
        self.configure(version='25.12.0')
        self.prepare_core(family='25.12', architecture='aarch64_cortex-a53')
        self.env['TEST_APK_ARCHITECTURE'] = 'aarch64'
        result = self.run_installer(answer='y\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('aarch64_cortex-a53.apk', self.log.read_text())

    def test_core_apk_requires_openwrt_architecture_metadata(self):
        self.configure(version='25.12.5')
        self.prepare_core(family='25.12', architecture='aarch64_cortex-a53')
        self.release_file.write_text("DISTRIB_RELEASE='25.12.5'\n")
        result = self.run_installer(answer='y\n')
        self.assert_not_installed(result)
        self.assertIn('architecture from OpenWrt metadata', result.stderr)

    def test_fresh_core_installation_creates_the_default_configuration(self):
        self.prepare_core()
        self.config.unlink()
        result = self.run_installer(answer='y\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('# package default', self.config.read_text())

    def test_declining_core_installation_changes_nothing(self):
        self.prepare_core()
        self.assert_not_installed(self.run_installer(answer='n\n'))
        self.assertFalse(self.log.exists())

    def test_empty_confirmation_does_not_install(self):
        self.prepare_core()
        self.assert_not_installed(self.run_installer(answer='\n'))
        self.assertFalse(self.log.exists())

    def test_core_checksum_failure_does_not_install_any_package(self):
        self.prepare_core()
        self.core_package.write_bytes(b'corrupt')
        self.assert_not_installed(self.run_installer(answer='y\n'))

    def test_core_architecture_must_match_exactly(self):
        self.prepare_core(architecture='mips_24kc')
        self.core_release.write_text(self.core_release.read_text().replace('mips_24kc', 'mipsel_24kc'))
        self.assert_not_installed(self.run_installer(answer='y\n'))

    def test_failed_core_installation_restores_configuration_and_stops(self):
        self.prepare_core()
        original = self.config.read_bytes()
        self.env['CORE_PACKAGE_EXIT'] = '1'
        result = self.run_installer(answer='y\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.config.read_bytes(), original)
        self.assertNotIn('/' + self.filename, '\n'.join(line for line in self.log.read_text().splitlines() if line.startswith('opkg install')))
        self.assertNotIn('rpcd restart', self.log.read_text())

    def test_missing_service_files_after_core_installation_stop_the_interface(self):
        self.prepare_core()
        self.env['OMIT_CORE_FILES'] = '1'
        result = self.run_installer(answer='y\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('rpcd restart', self.log.read_text())

    def test_one_line_installation_can_prompt_for_core(self):
        self.prepare_core()
        result = self.run_one_line_installation(answer='y\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('/' + self.core_filename, self.log.read_text())

    def test_confirmation_can_use_the_terminal_instead_of_stdin(self):
        self.prepare_core()
        (self.root / 'no-tty').write_text('y\n')
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_core_installation_without_a_published_digest(self):
        self.prepare_core(digest=False)
        result = self.run_installer(answer='y\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('does not provide a digest', result.stdout)

    def test_jsonfilter_is_installed_when_needed(self):
        self.prepare_core()
        (self.commands / 'jsonfilter').unlink()
        result = self.run_installer(answer='y\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('opkg install jsonfilter', self.log.read_text())

    def test_failed_configuration_restore_retains_the_backup(self):
        self.prepare_core()
        original = self.config.read_bytes()
        self.command('cp', '''#!/bin/sh
case "$2" in
    */byedpi.config.backup) exit 1 ;;
esac
/usr/bin/cp "$@"
''')
        result = self.run_installer(answer='y\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Backup retained at', result.stderr)
        backups = list(self.root.glob('download.*/byedpi.config.backup'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        self.assertNotIn('rpcd restart', self.log.read_text())

    def test_available_core_update_requires_confirmation_and_preserves_settings(self):
        self.prepare_update()
        original = self.config.read_bytes()
        result = self.run_installer(answer='y\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('0.17.2-r1 -> 0.17.3-r1', result.stdout)
        self.assertIn('ByeDPI versions: installed 0.17.2-r1 | repository 0.17.3-r1', result.stdout)
        self.assertEqual(Path(self.env['TEST_CORE_VERSION']).read_text(), '0.17.3-r1')
        self.assertEqual(self.config.read_bytes(), original)
        self.assertIn('opkg compare-versions 0.17.3-r1 >> 0.17.2-r1', self.log.read_text())

    def test_declined_core_update_still_installs_the_interface(self):
        self.prepare_update()
        result = self.run_installer(answer='n\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('opkg install', self.log.read_text())
        self.assertNotIn(self.core_filename, self.log.read_text())
        self.assertEqual(Path(self.env['TEST_CORE_VERSION']).read_text(), '0.17.2-r1')

    def test_enter_skips_the_optional_core_update(self):
        self.prepare_update()
        result = self.run_installer(answer='\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('update skipped', result.stdout)
        self.assertNotIn(self.core_filename, self.log.read_text())

    def test_current_core_is_not_reinstalled(self):
        for family in ('24.10', '25.12'):
            with self.subTest(family=family):
                self.prepare_update(installed_version='0.17.3-r1', family=family)
                result = self.run_installer()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout.startswith('Installing LuCI for ByeDPI...\nChecking installed and available ByeDPI versions...\n'))
                self.assertIn('ByeDPI versions: installed 0.17.3-r1 | repository 0.17.3-r1', result.stdout)
                self.assertIn(f'Downloading {self.filename}...', result.stdout)
                self.assertIn('LuCI package checksum verified.', result.stdout)
                self.assertNotIn(': OK', result.stdout)
                self.assertIn('ByeDPI versions match. No update is needed.', result.stdout)
                self.assertNotIn('Update?', result.stdout)
                self.assertNotIn(self.core_filename, self.log.read_text())

    def test_newer_installed_core_is_not_downgraded(self):
        self.prepare_update(installed_version='0.17.10-r1')
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('Update?', result.stdout)
        self.assertIn('Installed ByeDPI is newer than the repository version. No update is needed.', result.stdout)
        self.assertNotIn(self.core_filename, self.log.read_text())

    def test_package_revision_update_is_offered(self):
        self.prepare_update(installed_version='0.17.3-r0')
        result = self.run_installer(answer='n\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('0.17.3-r0 -> 0.17.3-r1', result.stdout)

    def test_apk_core_update_uses_upgrade_and_native_comparison(self):
        self.prepare_update(family='25.12')
        result = self.run_installer(answer='yes\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('apk info -e -v byedpi', self.log.read_text())
        self.assertIn('apk version -t 0.17.3-r1 0.17.2-r1', self.log.read_text())
        self.assertIn('apk add --allow-untrusted --upgrade', self.log.read_text())

    def test_apk_update_finds_the_router_cpu_variant(self):
        self.configure(version='25.12.5')
        self.prepare_core(family='25.12', architecture='aarch64_cortex-a53')
        self.service.write_text('#!/bin/sh\nexit 0\n')
        self.service.chmod(0o755)
        Path(self.env['TEST_CORE_VERSION']).write_text('0.17.2-r1')
        self.env['TEST_APK_ARCHITECTURE'] = 'aarch64'
        original = self.config.read_bytes()
        result = self.run_installer(answer='y\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('0.17.2-r1 -> 0.17.3-r1', result.stdout)
        self.assertIn(self.core_filename, self.log.read_text())
        self.assertEqual(self.config.read_bytes(), original)

    def test_no_terminal_skips_update_but_keeps_installing_the_interface(self):
        self.prepare_update()
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('update skipped', result.stdout)
        self.assertNotIn(self.core_filename, self.log.read_text())

    def test_update_lookup_failure_does_not_block_the_interface(self):
        self.prepare_update()
        (self.assets / 'releases?per_page=100').unlink()
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Unable to check ByeDPI updates', result.stdout)
        self.assertNotIn(self.core_filename, self.log.read_text())

    def test_successful_package_command_must_actually_update_the_core(self):
        self.prepare_update()
        original = self.config.read_bytes()
        self.env['SKIP_VERSION_CHANGE'] = '1'
        result = self.run_installer(answer='y\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('did not install the requested', result.stderr)
        self.assertEqual(self.config.read_bytes(), original)
        self.assertNotIn('rpcd restart', self.log.read_text())


if __name__ == '__main__':
    unittest.main()
