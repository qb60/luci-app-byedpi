#!/usr/bin/env python3
"""Resolve one official SDK for an architecture-independent LuCI package."""

import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


DOWNLOADS = 'https://downloads.openwrt.org/releases/'
SUPPORTED_FAMILIES = ('24.10', '25.12')


class ReleaseLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.versions = set()

    def handle_starttag(self, tag, attributes):
        if tag == 'a':
            href = dict(attributes).get('href', '')

            if re.fullmatch(r'\d+\.\d+\.\d+/', href):
                self.versions.add(href.rstrip('/'))


def fetch_text(url):
    for attempt in range(3):
        try:
            with urlopen(url, timeout=60) as response:
                return response.read().decode('utf-8')
        except HTTPError as error:
            if error.code == 404 or attempt == 2:
                raise
        except (URLError, TimeoutError):
            if attempt == 2:
                raise

        time.sleep(attempt + 1)


def resolve_sdk(family):
    if family not in SUPPORTED_FAMILIES:
        raise ValueError(f'Unsupported OpenWrt family: {family}')

    releases = ReleaseLinks()
    releases.feed(fetch_text(DOWNLOADS))
    versions = [version for version in releases.versions if version.startswith(family + '.')]

    if not versions:
        raise ValueError(f'No stable OpenWrt release found for {family}')

    version = max(versions, key=lambda value: tuple(map(int, value.split('.'))))

    # Only the SDK build host matters here. Its output has LUCI_PKGARCH=all
    # and works on every router architecture within the selected OpenWrt family.
    sdk_directory = f'{DOWNLOADS}{version}/targets/x86/64/'
    candidates = []

    for line in fetch_text(sdk_directory + 'sha256sums').splitlines():
        fields = line.split()

        if len(fields) != 2:
            continue

        checksum, filename = fields[0], fields[1].lstrip('*')

        if re.fullmatch(r'openwrt-sdk-[a-zA-Z0-9_.+-]+[.-]Linux-x86_64\.tar\.(?:xz|zst)', filename):
            if not re.fullmatch(r'[0-9a-f]{64}', checksum):
                raise ValueError(f'Invalid SDK checksum for OpenWrt {version}')

            candidates.append((filename, checksum))

    if len(candidates) != 1:
        raise ValueError(f'Expected one SDK for OpenWrt {version}, found {len(candidates)}')

    filename, checksum = candidates[0]

    return {
        'family': family,
        'openwrt_version': version,
        'sdk_url': sdk_directory + filename,
        'sdk_sha256': checksum,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('family', choices=SUPPORTED_FAMILIES)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()

    arguments.output.write_text(json.dumps(resolve_sdk(arguments.family), indent=2) + '\n')


if __name__ == '__main__':
    main()
