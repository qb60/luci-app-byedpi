#!/usr/bin/env python3
"""Increment PKG_RELEASE, commit the change and tag the new package revision."""

import argparse
from pathlib import Path
import re
import subprocess
import sys


def git(*arguments, directory=None, capture=False):
    return subprocess.run(
        ['git', *arguments], cwd=directory, check=True, text=True,
        stdout=subprocess.PIPE if capture else None,
    )


def next_release():
    root = Path(git('rev-parse', '--show-toplevel', capture=True).stdout.strip())
    git('symbolic-ref', '--quiet', 'HEAD', directory=root, capture=True)

    if git('status', '--porcelain', '--untracked-files=normal', directory=root, capture=True).stdout:
        raise ValueError('Commit or stash your changes before running git next.')

    makefile = root / 'luci-app-byedpi/Makefile'
    original = makefile.read_bytes()
    contents = original.decode('utf-8')
    versions = re.findall(r'^PKG_VERSION:=(\d+\.\d+\.\d+)$', contents, re.MULTILINE)
    revisions = re.findall(r'^PKG_RELEASE:=([1-9]\d*)$', contents, re.MULTILINE)

    if len(versions) != 1 or len(revisions) != 1:
        raise ValueError('Expected one numeric PKG_VERSION and one positive integer PKG_RELEASE in Makefile.')

    revision = int(revisions[0]) + 1
    tag = f'v{versions[0]}-r{revision}'
    existing_tag = subprocess.run(
        ['git', 'show-ref', '--verify', '--quiet', f'refs/tags/{tag}'], cwd=root,
    )
    if existing_tag.returncode == 0:
        raise ValueError(f'Tag {tag} already exists. No files were changed.')
    if existing_tag.returncode != 1:
        raise ValueError('Unable to check existing Git tags.')

    updated = re.sub(r'^PKG_RELEASE:=[1-9]\d*$', f'PKG_RELEASE:={revision}', contents, count=1, flags=re.MULTILINE)
    makefile.write_bytes(updated.encode('utf-8'))
    git('add', '--', 'luci-app-byedpi/Makefile', directory=root)
    try:
        git('commit', '-m', 'build: bump version', directory=root)
    except subprocess.CalledProcessError:
        print('The revision change is retained. Resolve the commit error and commit/tag it manually.', file=sys.stderr)
        raise

    git('tag', tag, directory=root)
    print(f'Created {tag}. To publish this branch and tag, run:')
    print(f'  git push --atomic origin HEAD refs/tags/{tag}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        next_release()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
