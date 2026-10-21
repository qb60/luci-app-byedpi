#!/bin/sh
# Install the LuCI interface; install or update ByeDPI only with explicit consent.
set -eu
set -f

DEFAULT_REPOSITORY=''
repository=${1:-$DEFAULT_REPOSITORY}
release_tag=${2:-latest}
temporary_directory=
configuration_backup=
package_lists_updated=0
install_core=0
core_update=0
CORE_REPOSITORY=DPITrickster/ByeDPI-OpenWrt

fail() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

cleanup() {
    # Retain the backup if restoring the user's configuration fails.
    restore_configuration || return 1
    [ -z "$temporary_directory" ] || rm -rf "$temporary_directory"
}

restore_configuration() {
    [ -n "$configuration_backup" ] || return 0

    if ! cp -p "$configuration_backup" /etc/config/byedpi; then
        printf 'Unable to restore the configuration. Backup retained at %s\n' "$configuration_backup" >&2
        return 1
    fi

    configuration_backup=
}

trap cleanup EXIT
trap 'exit 1' HUP INT TERM

download() {
    download_url=$1
    destination=$2

    if command -v curl >/dev/null 2>&1; then
        curl --fail --location --retry 3 --output "$destination" "$download_url"
    elif command -v wget >/dev/null 2>&1; then
        wget -O "$destination" "$download_url"
    else
        fail 'Install wget or curl with HTTPS support first.'
    fi
}

byedpi_installed() {
    [ -x /etc/init.d/byedpi ] && [ -x /usr/bin/ciadpi ] && [ -f /etc/config/byedpi ]
}

confirm_action() {
    answer=

    if [ -t 0 ]; then
        IFS= read -r answer || answer=
    elif ( : < /dev/tty ) 2>/dev/null; then
        IFS= read -r answer < /dev/tty || answer=
    else
        printf '\nNo interactive terminal; confirmation was not received.\n' >&2
        return 1
    fi

    case "$answer" in
        y|Y|yes|YES|Yes) return 0 ;;
        *) return 1 ;;
    esac
}

confirm_core_installation() {
    printf 'ByeDPI is not installed. Install it from %s? [y/N]: ' "$CORE_REPOSITORY"
    confirm_action || fail 'Installation cancelled. No packages were installed.'
    install_core=1
}

update_package_lists() {
    [ "$package_lists_updated" = 0 ] || return 0
    "$package_manager" update || return $?
    package_lists_updated=1
}

install_package() {
    if [ "$package_manager" = opkg ]; then
        opkg install "$1"
    else
        # Local SDK packages are not signed by the OpenWrt distribution key.
        apk add --allow-untrusted "$1"
    fi
}

resolve_byedpi_package() {
    # Only the machine-code package needs architecture selection.
    if [ "$package_manager" = apk ]; then
        architecture=$(apk --print-arch) || fail 'Unable to determine the APK architecture.'
    else
        architecture=${DISTRIB_ARCH:-}
        opkg print-architecture | awk -v architecture="$architecture" \
            '$1 == "arch" && $2 == architecture { found = 1 } END { exit !found }' ||
            fail 'OpenWrt metadata and opkg architecture disagree.'
    fi

    printf '%s\n' "$architecture" | grep -Eq '^[A-Za-z0-9_-]+$' || fail 'Unable to determine the ByeDPI package architecture.'


    api_url="https://api.github.com/repos/$CORE_REPOSITORY"
    download "$api_url/releases?per_page=100" "$temporary_directory/core-releases.json" ||
        fail 'Unable to query ByeDPI releases. Check the connection and GitHub API rate limit.'

    stable_tags=$(jsonfilter -i "$temporary_directory/core-releases.json" \
        -e '@[@.draft=false && @.prerelease=false].tag_name') || fail 'No stable ByeDPI release metadata was returned.'
    core_tag=

    for candidate in $stable_tags; do
        case "$candidate" in
            *-"$release_family")
                version_tag=${candidate%-*}
                if printf '%s\n' "$version_tag" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$'; then
                    core_tag=$candidate
                    break
                fi
                ;;
        esac
    done

    [ -n "$core_tag" ] || fail "No native stable ByeDPI release was found for OpenWrt $release_family."

    download "$api_url/releases/tags/$core_tag" "$temporary_directory/core-release.json" ||
        fail 'Unable to download ByeDPI release metadata.'

    asset_names=$(jsonfilter -i "$temporary_directory/core-release.json" -e '@.assets[*].name') ||
        fail 'No packages were found in the ByeDPI release.'
    core_filename=

    for candidate in $asset_names; do
        case "$candidate" in
            byedpi_*_"$architecture"."$package_extension")
                [ -z "$core_filename" ] || fail 'More than one matching ByeDPI package was found.'
                core_filename=$candidate
                ;;
        esac
    done

    [ -n "$core_filename" ] || fail "No ByeDPI package is available for OpenWrt $release_family / $architecture."
    printf '%s\n' "$core_filename" | grep -Eq '^byedpi_[A-Za-z0-9_.+-]+\.(ipk|apk)$' || fail 'Invalid ByeDPI package filename.'

    core_digest=$(jsonfilter -i "$temporary_directory/core-release.json" \
        -e "@.assets[@.name=\"$core_filename\"].digest" 2>/dev/null) || core_digest=
    [ "$core_digest" != null ] || core_digest=

    printf '%s\t%s\t%s\t%s\n' "$core_tag" "$architecture" "$core_filename" "$core_digest" > "$temporary_directory/core-package.tsv"
}

ensure_jsonfilter() {
    # jsonfilter is a standard OpenWrt dependency of our LuCI package as well.
    if ! command -v jsonfilter >/dev/null 2>&1; then
        update_package_lists
        if [ "$package_manager" = opkg ]; then
            opkg install jsonfilter
        else
            apk add jsonfilter
        fi
        command -v jsonfilter >/dev/null 2>&1 || fail 'Unable to install jsonfilter for reading GitHub release metadata.'
    fi
}

load_core_package() {
    IFS="$(printf '\t')" read -r core_tag architecture core_filename core_digest < "$temporary_directory/core-package.tsv"
}

installed_core_version() {
    if [ "$package_manager" = opkg ]; then
        opkg status byedpi 2>/dev/null | sed -n 's/^Version: //p' | head -n 1
    else
        apk info -e -v byedpi 2>/dev/null | sed -n 's/^byedpi-//p' | head -n 1
    fi
}

core_version_matches() {
    if [ "$package_manager" = opkg ]; then
        case "$2" in
            gt) operator='>>' ;;
            eq) operator='=' ;;
            *) return 1 ;;
        esac
        opkg compare-versions "$1" "$operator" "$3"
    else
        comparison=$(apk version -t "$1" "$3") || return 1
        case "$2:$comparison" in
            'gt:>'|'eq:=') return 0 ;;
            *) return 1 ;;
        esac
    fi
}

check_core_update() {
    installed_version=$(installed_core_version)
    if [ -z "$installed_version" ]; then
        printf 'Unable to determine the installed ByeDPI version; skipping its update check.\n'
        return 0
    fi

    ensure_jsonfilter
    # A failed optional update lookup must not block the LuCI installation.
    if ! (
        trap - EXIT
        resolve_byedpi_package
    ); then
        printf 'Unable to check ByeDPI updates; keeping the installed version.\n'
        return 0
    fi

    load_core_package
    available_version=${core_filename#byedpi_}
    available_version=${available_version%_"$architecture"."$package_extension"}

    if core_version_matches "$available_version" gt "$installed_version"; then
        printf 'ByeDPI update available: %s -> %s. Update? [y/N]: ' "$installed_version" "$available_version"
        if confirm_action; then
            install_core=1
            core_update=1
        else
            printf 'ByeDPI update skipped. Continuing with the LuCI interface.\n'
        fi
    fi
}

install_byedpi() {
    if [ ! -f "$temporary_directory/core-package.tsv" ]; then
        ensure_jsonfilter
        resolve_byedpi_package
    fi
    load_core_package

    if [ "$core_update" = 1 ]; then
        printf 'Updating ByeDPI to %s for %s...\n' "$available_version" "$architecture"
    else
        printf 'Installing ByeDPI %s for %s...\n' "$core_tag" "$architecture"
    fi
    download "https://github.com/$CORE_REPOSITORY/releases/download/$core_tag/$core_filename" \
        "$temporary_directory/$core_filename" || fail 'Unable to download the ByeDPI package.'

    if [ -n "$core_digest" ]; then
        core_checksum=${core_digest#sha256:}
        [ "$core_digest" != "$core_checksum" ] && printf '%s\n' "$core_checksum" | grep -Eq '^[0-9a-f]{64}$' ||
            fail 'Invalid SHA-256 digest in the ByeDPI release metadata.'
        printf '%s  %s\n' "$core_checksum" "$core_filename" > "$temporary_directory/core.sha256"
        (cd "$temporary_directory" && sha256sum -c core.sha256) || fail 'ByeDPI checksum verification failed.'
    else
        printf 'The ByeDPI release does not provide a digest; using its GitHub HTTPS download.\n'
    fi

    if [ -e /etc/config/byedpi ] || [ -L /etc/config/byedpi ]; then
        [ -f /etc/config/byedpi ] && [ ! -L /etc/config/byedpi ] || fail 'The existing ByeDPI configuration is not a regular file.'
        cp -p /etc/config/byedpi "$temporary_directory/byedpi.config.backup" || fail 'Unable to back up the existing ByeDPI configuration.'
        configuration_backup="$temporary_directory/byedpi.config.backup"
    fi

    update_package_lists
    if [ "$package_manager" = apk ] && [ "$core_update" = 1 ]; then
        apk add --allow-untrusted --upgrade "$temporary_directory/$core_filename"
    else
        install_package "$temporary_directory/$core_filename"
    fi
    restore_configuration || exit 1
    byedpi_installed || fail 'ByeDPI installation did not provide the expected service files. Repair the service before continuing.'

    if [ "$core_update" = 1 ]; then
        updated_version=$(installed_core_version)
        [ -n "$updated_version" ] && core_version_matches "$updated_version" eq "$available_version" ||
            fail 'The package manager did not install the requested ByeDPI version.'
    fi
}

[ "$(id -u)" = 0 ] || fail 'Run this installer as root on the router.'

printf '%s\n' "$repository" | grep -Eq '^[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+$' ||
    fail 'Specify the GitHub repository: sh install.sh OWNER/REPOSITORY [RELEASE_TAG]'

printf '%s\n' "$release_tag" | grep -Eq '^(latest|v[0-9]+\.[0-9]+\.[0-9]+)$' ||
    fail 'The release tag must be latest or vMAJOR.MINOR.PATCH.'

[ -r /etc/openwrt_release ] || fail 'This system does not provide /etc/openwrt_release.'
. /etc/openwrt_release

openwrt_version=${DISTRIB_RELEASE:-}

case "$openwrt_version" in
    24.10.*) release_family=24.10; package_manager=opkg; package_extension=ipk ;;
    25.12.*) release_family=25.12; package_manager=apk; package_extension=apk ;;
    *) fail "Unsupported OpenWrt release: $openwrt_version (stable 24.10 or 25.12 required)." ;;
esac

printf '%s\n' "$openwrt_version" | grep -Eq '^(24\.10|25\.12)\.[0-9]+$' ||
    fail 'Development snapshots and release candidates require a matching manual build.'

command -v "$package_manager" >/dev/null 2>&1 || fail "Package manager $package_manager was not found."
command -v sha256sum >/dev/null 2>&1 || fail 'sha256sum was not found.'

if ! byedpi_installed; then
    confirm_core_installation
fi

if [ "$release_tag" = latest ]; then
    release_url="https://github.com/$repository/releases/latest/download"
else
    release_url="https://github.com/$repository/releases/download/$release_tag"
fi

temporary_directory=$(mktemp -d /tmp/luci-byedpi-install.XXXXXX) || fail 'Unable to create a temporary directory.'
download "$release_url/packages.tsv" "$temporary_directory/packages.tsv" || fail 'Unable to download the release manifest.'

# One architecture-independent package is published for each stable family.
selection=$(awk -F '\t' -v family="$release_family" '
    /^#/ { next }
    NF == 3 && $1 == family { selected = $0; count++ }
    END {
        if (count == 1) print selected
        else exit 1
    }' "$temporary_directory/packages.tsv") || fail 'No unique package exists for this OpenWrt family.'

tab=$(printf '\t')
IFS="$tab" read -r build_family filename checksum <<EOF
$selection
EOF

printf '%s\n' "$filename" | grep -Eq "^luci-app-byedpi-[A-Za-z0-9_.-]+\.$package_extension\$" || fail 'Invalid package filename in the release manifest.'
printf '%s\n' "$checksum" | grep -Eq '^[0-9a-f]{64}$' || fail 'Invalid package checksum in the release manifest.'

printf 'OpenWrt: %s\nPackage family: %s\n' "$openwrt_version" "$build_family"

download "$release_url/$filename" "$temporary_directory/$filename" || fail 'Unable to download the package.'
printf '%s  %s\n' "$checksum" "$filename" > "$temporary_directory/package.sha256"

(
    cd "$temporary_directory"
    sha256sum -c package.sha256
) || fail 'Checksum verification failed. The package was not installed.'

if [ "$install_core" = 0 ]; then
    check_core_update
fi

if [ "$install_core" = 1 ]; then
    install_byedpi
fi

update_package_lists
install_package "$temporary_directory/$filename"

/etc/init.d/rpcd restart

printf '\nInstalled successfully. Open Services -> ByeDPI in LuCI.\n'
