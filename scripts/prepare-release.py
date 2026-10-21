#!/usr/bin/env python3
"""Check complete build coverage and prepare release assets and installer metadata."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


def prepare_release(artifact_directory, output_directory, repository):
    if not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Expected repository in owner/name format')

    expected_families = {'24.10', '25.12'}
    records = {}

    for record_path in artifact_directory.rglob('*.json'):
        record = json.loads(record_path.read_text())

        family = record['family']

        if family in records or family not in expected_families:
            raise ValueError(f'Unexpected or duplicate OpenWrt family: {family}')

        if not re.fullmatch(re.escape(family) + r'\.\d+', record['openwrt_version']):
            raise ValueError(f'SDK version does not match OpenWrt family: {family}')

        filename = record['filename']

        extension = 'ipk' if family == '24.10' else 'apk'

        if not re.fullmatch(r'luci-app-byedpi-[A-Za-z0-9_.-]+-openwrt-' + re.escape(family) + r'-all\.' + extension, filename):
            raise ValueError(f'Invalid package filename: {filename}')

        package = record_path.parent / filename

        if hashlib.sha256(package.read_bytes()).hexdigest() != record['sha256']:
            raise ValueError(f'Package checksum mismatch: {filename}')

        records[family] = (record, package)

    if set(records) != expected_families:
        raise ValueError(f'Missing builds: {sorted(expected_families - set(records))}')

    output_directory.mkdir(parents=True, exist_ok=False)
    manifest = ['# openwrt_family\tfilename\tsha256']

    for record, package in sorted(records.values(), key=lambda item: item[0]['family']):
        shutil.copyfile(package, output_directory / record['filename'])
        manifest.append('\t'.join(record[key] for key in
                                  ('family', 'filename', 'sha256')))

    (output_directory / 'packages.tsv').write_text('\n'.join(manifest) + '\n')
    build_info = [record for record, _ in sorted(records.values(), key=lambda item: item[0]['family'])]
    (output_directory / 'build-info.json').write_text(json.dumps(build_info, indent=2) + '\n')

    installer = Path('scripts/install.sh').read_text()
    installer = installer.replace("DEFAULT_REPOSITORY=''", f"DEFAULT_REPOSITORY='{repository}'", 1)
    (output_directory / 'install.sh').write_text(installer)

    checksum_lines = [f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}'
                      for path in sorted(output_directory.iterdir())]
    (output_directory / 'SHA256SUMS').write_text('\n'.join(checksum_lines) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repository', required=True)
    arguments = parser.parse_args()

    prepare_release(arguments.artifacts, arguments.output, arguments.repository)


if __name__ == '__main__':
    main()
