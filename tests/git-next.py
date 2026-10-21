"""Exercise the release helper against temporary Git repositories."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path('scripts/git-next.py').resolve()


class NextReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='byedpi-git-next-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'Test Author')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'tag.gpgsign', 'false')
        self.makefile = self.root / 'luci-app-byedpi/Makefile'
        self.makefile.parent.mkdir()
        self.original = b'# Keep formatting\nPKG_VERSION:=0.0.1\n\nPKG_RELEASE:=2\n'
        self.makefile.write_bytes(self.original)
        self.git('add', '.')
        self.git('commit', '-qm', 'Initial commit')
        self.original_head = self.git('rev-parse', 'HEAD').stdout.strip()

    def git(self, *arguments):
        return subprocess.run(['git', *arguments], cwd=self.root, env=self.environment,
                              check=True, text=True, capture_output=True, timeout=10)

    def run_next(self, directory=None):
        return subprocess.run([sys.executable, str(SCRIPT)], cwd=directory or self.root,
                              env=self.environment, text=True, capture_output=True, timeout=10)

    def assert_no_release(self, result):
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git('rev-parse', 'HEAD').stdout.strip(), self.original_head)
        self.assertEqual(self.git('tag', '--list').stdout, '')

    def test_creates_revision_commit_and_tag(self):
        result = self.run_next()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.makefile.read_bytes(), self.original.replace(b'RELEASE:=2', b'RELEASE:=3'))
        self.assertEqual(self.git('log', '-1', '--format=%s').stdout.strip(), 'build: bump version')
        self.assertEqual(self.git('rev-parse', 'v0.0.1-r3').stdout, self.git('rev-parse', 'HEAD').stdout)
        self.assertEqual(self.git('status', '--porcelain').stdout, '')
        self.assertIn('git push --atomic origin HEAD refs/tags/v0.0.1-r3', result.stdout)

    def test_can_be_called_from_subdirectory(self):
        script = self.root / 'scripts/git-next.py'
        script.parent.mkdir()
        script.write_bytes(SCRIPT.read_bytes())
        self.git('add', '.')
        self.git('commit', '-qm', 'Add release helper')
        self.git('config', '--local', 'alias.next', '!python3 scripts/git-next.py')
        result = subprocess.run(['git', 'next'], cwd=self.makefile.parent, env=self.environment,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Created v0.0.1-r3', result.stdout)

    def test_uncommitted_changes_are_rejected(self):
        self.makefile.write_bytes(self.original + b'# Work in progress\n')
        result = self.run_next()
        self.assert_no_release(result)
        self.assertIn('Commit or stash', result.stderr)
        self.assertTrue(self.makefile.read_bytes().endswith(b'# Work in progress\n'))

    def test_staged_changes_are_rejected(self):
        self.makefile.write_bytes(self.original + b'# Staged\n')
        self.git('add', '.')
        self.assert_no_release(self.run_next())

    def test_untracked_files_are_rejected(self):
        (self.root / 'notes.txt').write_text('Do not include this in the release.')
        self.assert_no_release(self.run_next())

    def test_existing_tag_is_not_overwritten(self):
        self.git('tag', 'v0.0.1-r3')
        result = self.run_next()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already exists', result.stderr)
        self.assertEqual(self.makefile.read_bytes(), self.original)
        self.assertEqual(self.git('rev-parse', 'HEAD').stdout.strip(), self.original_head)

    def test_invalid_revision_is_rejected(self):
        self.makefile.write_bytes(self.original.replace(b'RELEASE:=2', b'RELEASE:=auto'))
        self.git('commit', '-qam', 'Invalid metadata')
        self.original_head = self.git('rev-parse', 'HEAD').stdout.strip()
        self.assert_no_release(self.run_next())

    def test_detached_head_is_rejected(self):
        self.git('checkout', '--detach')
        self.assert_no_release(self.run_next())
        self.assertEqual(self.makefile.read_bytes(), self.original)

    def test_failed_commit_keeps_the_change_without_creating_a_tag(self):
        hook = self.root / '.git/hooks/pre-commit'
        hook.write_text('#!/bin/sh\nexit 1\n')
        hook.chmod(0o755)
        result = self.run_next()
        self.assert_no_release(result)
        self.assertIn('revision change is retained', result.stderr)
        self.assertIn(b'PKG_RELEASE:=3', self.makefile.read_bytes())


if __name__ == '__main__':
    unittest.main()
