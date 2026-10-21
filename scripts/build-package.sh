#!/usr/bin/env bash
# Build only this repository's LuCI package using an official, checksummed SDK.
set -euo pipefail

project_directory=$(cd "$(dirname "$0")/.." && pwd)
openwrt_family=$1
output_directory=$2

mkdir -p "$output_directory"
output_directory=$(cd "$output_directory" && pwd)

build_directory=$(mktemp -d)
trap 'rm -rf "$build_directory"' EXIT

python3 "$project_directory/scripts/openwrt-sdk.py" "$openwrt_family" --output "$build_directory/sdk.json"

python3 - "$build_directory" <<'PYSDK'
import json
from pathlib import Path
import sys

directory = Path(sys.argv[1])
record = json.loads((directory / 'sdk.json').read_text())

for key in ('sdk_url', 'sdk_sha256'):
    (directory / key).write_text(record[key])
PYSDK

sdk_url=$(cat "$build_directory/sdk_url")
sdk_sha256=$(cat "$build_directory/sdk_sha256")

curl --fail --silent --show-error --location --retry 3 --output "$build_directory/sdk.tar" "$sdk_url"
printf '%s  sdk.tar\n' "$sdk_sha256" > "$build_directory/sdk.sha256"

(
    cd "$build_directory"
    sha256sum --check sdk.sha256
)

mkdir "$build_directory/sdk"
tar -xf "$build_directory/sdk.tar" --strip-components=1 -C "$build_directory/sdk"
rm "$build_directory/sdk.tar"

cd "$build_directory/sdk"

test -f feeds.conf || cp feeds.conf.default feeds.conf
./scripts/feeds update -a
./scripts/feeds install -a

cp -a "$project_directory/luci-app-byedpi" package/luci-app-byedpi
printf '\nCONFIG_PACKAGE_luci-app-byedpi=m\n' >> .config

make defconfig
make package/luci-app-byedpi/compile V=s -j2

python3 - "$build_directory/sdk.json" "$output_directory" "$project_directory" <<'PY'
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

record = json.loads(Path(sys.argv[1]).read_text())
output = Path(sys.argv[2])
project = Path(sys.argv[3])
makefile = (project / 'luci-app-byedpi/Makefile').read_text()
version = re.search(r'^PKG_VERSION:=(.+)$', makefile, re.MULTILINE).group(1)
release = re.search(r'^PKG_RELEASE:=(.+)$', makefile, re.MULTILINE).group(1)
extension = 'ipk' if record['family'] == '24.10' else 'apk'
packages = list(Path('bin/packages').rglob(f'luci-app-byedpi*.{extension}'))

if len(packages) != 1:
    raise SystemExit(f'Expected one LuCI package, found {len(packages)}: {packages}')

filename = f'luci-app-byedpi-{version}-r{release}-openwrt-{record["family"]}-all.{extension}'
destination = output / filename
shutil.copyfile(packages[0], destination)

record.update(filename=filename, sha256=hashlib.sha256(destination.read_bytes()).hexdigest())
(output / f'{record["family"]}.json').write_text(json.dumps(record, indent=2) + '\n')
print(f'Built {filename}')
PY
