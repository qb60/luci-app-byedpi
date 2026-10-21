# Implementation and validation

The starting workspace contained only AGENTS.md. No core package or release
workflow was present to modify. The interface uses an existing
`/etc/init.d/byedpi` without installing a replacement. If the core is missing,
the installer offers to install its native package from DPITrickster releases
with explicit terminal confirmation. Existing installations are checked for
updates, and newer packages are installed only after a separate confirmation.
Declining an update or being
unable to check it does not block the LuCI installation.
The Makefile and workflows still have no core package/source dependency.

Release builds produce two architecture-independent packages: one for OpenWrt
24.10 (IPK), one for 25.12 (APK). Both use LUCI_PKGARCH=all. Each build resolves
one official SDK for its stable family; no router target discovery or processor
matrix is needed. The installer selects by OpenWrt family and verifies SHA-256.
When installing the optional core, only that binary package needs architecture
selection. The installer resolves stable native tags for the OpenWrt family,
checks the exact architecture suffix, and verifies the GitHub asset digest if
available. The filename architecture comes from OpenWrt's DISTRIB_ARCH,
including CPU variants such as aarch64_cortex-a53; APK's generic ABI name
is unsuitable for matching these assets. It does not select generic or
prerelease packages. Existing UCI
configuration is backed up and restored, including on package-manager failure.
Installed and available versions are compared using the package manager's
native comparator, including package revisions. Equal/newer installed versions
are retained. APK updates explicitly request --upgrade; after installation,
package metadata must match the selected version. The installer does not
restart ByeDPI itself; the user can apply the new binary through Service → Restart.
A failed restore retains the backup and reports its path. Consent is read from
terminal stdin or /dev/tty, not from piped script contents.
Downloads suppress progress output. Package index updates show a short status
line on success and their full diagnostic output on failure.
See [releases.md](releases.md) for the publication procedure.

Users install or update with a single `sh <(wget -q -O - URL)` command, following
the documented [Podkop installation flow](https://github.com/itdoginfo/podkop#установка-podkop).
Release preparation embeds the repository in the installer, and the publication
workflow places a ready-to-copy command with the actual URL in the release
description. The user supplies no repository arguments or shell variables.

## Sources inspected

- [ByeDPI-OpenWrt init script](https://github.com/DPITrickster/ByeDPI-OpenWrt/blob/335a51bb8704a8aa3b9e885b3259c6840d7487cc/byedpi/files/byedpi.init)
- [Upstream configuration](https://github.com/DPITrickster/ByeDPI-OpenWrt/blob/335a51bb8704a8aa3b9e885b3259c6840d7487cc/byedpi/files/byedpi.config)
- [Upstream release workflow](https://github.com/DPITrickster/ByeDPI-OpenWrt/blob/335a51bb8704a8aa3b9e885b3259c6840d7487cc/.github/workflows/build.yml)
- [LuCI form API and implementation, 24.10](https://github.com/openwrt/luci/blob/openwrt-24.10/modules/luci-base/htdocs/luci-static/resources/form.js)
- [LuCI view, permission and Save & Apply implementation](https://github.com/openwrt/luci/blob/openwrt-24.10/modules/luci-base/htdocs/luci-static/resources/luci.js)
- [rpcd executable plugin protocol](https://github.com/openwrt/rpcd/blob/master/plugin.c)
- [rpcd UCI session delta paths](https://github.com/openwrt/rpcd/blob/master/include/rpcd/uci.h)
- [ciadpi option syntax and listener defaults](https://github.com/hufrea/byedpi/blob/main/main.c)
- [Modern LuCI uhttpd form example](https://github.com/openwrt/luci/blob/openwrt-24.10/applications/luci-app-uhttpd/htdocs/luci-static/resources/view/uhttpd/uhttpd.js)

The init script reads `main.cmd_opts` globally, including when starting other
sections. The UI therefore warns that custom arguments affect all instances.
`enabled` remains editable because it still selects instances in custom mode.
`debug` is numeric upstream; the requested checkbox retains existing nonzero
levels until explicitly changed. The additional `pidfile` option is included
because the init script supports it. `auto_mode` uses the underscore spelling
read by the init script, rather than the commented `auto-mode` example.
Timeout and offset/position fields accept ByeDPI's compound syntax. Only
plain numeric fields have numeric validators; lists use DynamicList.

## Components

`Makefile` uses luci.mk and the SDK's native packaging format. `jshn`, `uci`
and `jsonfilter` are small standard OpenWrt dependencies, with no interpreter
runtime added by this package. Menu children supply LuCI navigation and browser
history. The service view uses `poll` every five seconds; it updates only
status elements and does not reload the configuration form.

`byedpi.js` declares four specific RPC methods. ACL read permissions cover
`status`, `read` and UCI byedpi. Write permissions cover `action`, `write` and
UCI byedpi. There are no file, exec, wildcard service or wildcard UCI grants.
Service actions are checked against a fixed allowlist. Buttons respect LuCI
write permissions. UI output uses text nodes/textContent rather than HTML.

The executable rpcd plugin queries `service list` in ubus. While running, the
listener is derived from the actual command argv registered with procd, so
unapplied UCI changes do not appear as the running listener. While stopped,
the configured listener is shown. Command arguments consume their own values;
an option argument that looks like `--ip` is not mistaken for an option.
Unknown or ambiguous syntax produces Unknown. Multiple instances produce a
common address/port only if they agree. A successful init start/restart is
followed by a procd running check after one second; subsequent crashes become
visible through polling. Failed starts produce a UI error without exposing
command arguments or log contents.

Form edits use LuCI UCI staging and standard apply/rollback behavior. No
additional restart is issued by the UI. Disabled parameter widgets stay visible
inside disabled fieldsets, and their parse methods skip UCI writes in custom
mode. Unknown options and sections are not removed. Advanced fields use a
native details element inside the standard form, suitable for narrow screens.

The raw editor refuses outstanding form or staged ByeDPI changes. It writes
the decoded JSON content through printf to a private temporary directory under
/etc/config, never to a shell command string. Strict `uci export` uses that
directory and its own delta directory. `cp -p` retains owner/mode; rename
replaces the live file only after validation. SHA-256 revision checks before
and after validation detect outside edits. A directory lock serializes this
plugin's write and service operations. Cleanup traps remove temporary files.
No service restart happens on raw Save or Cancel. Raw Save reloads the browser's
UCI cache and form; the Service tab's Restart applies the saved file explicitly.

## Local checks

Run from this repository's root:

```sh
busybox ash -n luci-app-byedpi/root/usr/libexec/rpcd/luci.byedpi
qjs --std -m tests/frontend.js
python3 tests/backend.py --tools /path/to/host-tools-prefix
```

The host tools prefix contains bin/uci, bin/jshn, share/libubox/jshn.sh and their
shared libraries in lib/. Host builds of official UCI/libubox and QuickJS were
used for these checks. The backend tests run a copy of the real handler under
BusyBox ash, substituting fixed paths into a temporary tree; no system config
is modified. The frontend tests parse all JS files and use lightweight API/DOM
test doubles for mode switching, list widget selection and write preservation.
They are not a browser or an installed LuCI environment.

Executed locally: BusyBox ash syntax check, 15 backend integration tests,
27 frontend checks, 56 release/installer tests, actionlint validation of all
three workflows, and JSON parsing of menu/ACL files. The backend service
tests substitute the init/procd boundary; the file editor tests use real UCI
and jshn. No .ipk/.apk artifact was built in this environment.

## Router acceptance checks still required

For each OpenWrt release, install both packages and check the following in the
default LuCI theme, including a narrow mobile viewport:

1. Services → ByeDPI appears; Service is the default tab; Back/Forward work.
2. Version matches `opkg status byedpi` or `apk info -v byedpi`.
3. procd running/stopped states match the view, including no registered service.
4. Start/Stop/Restart report success and failure; double clicks are blocked.
5. Start on boot matches `byedpi enabled` and survives reboot independently of
   the UCI main.enabled option.
6. Save/Apply/Reset, inline validation and config.change reload work with
   unknown sections/options. Confirm only the init script trigger reloads.
7. Typing custom arguments disables individual fields immediately; clearing
   them enables fields immediately; previously saved values survive.
8. All three UCI lists support adding/removing entries and round-trip as lists.
9. Raw editing preserves comments/newlines; syntax errors and outside edits
   leave the live file intact. Cancel does not write or restart anything.
10. RPC denial and service failures display errors, and a read-only login
    cannot invoke write operations or edit controls.
11. Restart the router and verify persistent UCI settings and autostart state.
12. Check browser console, mobile layout and both native package formats.

## Limits

Full SDK builds, GitHub Actions execution, actual rpcd authorization, router
boot/service behavior and visual browser checks require the target environment
and have not been executed locally. CI is provided, not claimed successful.
A live SDK discovery attempt from this workspace failed because DNS resolution
of downloads.openwrt.org was unavailable. Discovery logic was tested against
local fixtures; SDK filename formats were checked against official listings.
The editor is limited to 64 KiB to stay comfortably below ubus message limits
and shell environment limits on low-memory devices. Existing malformed UCI
can be repaired through the editor if rpcd can still expose the menu; SSH may
be needed if the UCI-based menu dependency itself fails.

The editor uses optimistic revision checks; external writers do not share its
lock. A noncooperating writer changing the file in the final interval between
the last check and rename cannot be serialized by this plugin. Rename is
atomic, but no fsync-based power-loss durability guarantee is provided. A
SIGKILL/power interruption can leave its lock directory behind; remove
`/var/lock/luci-byedpi.lock` after confirming no handler is running (reboot
also clears /var/lock). This does not corrupt the existing config file.

Unknown ciadpi options or shell globbing can prevent reliable listener
reconstruction and are shown as Unknown. Newer ciadpi option syntax may require
updating the conservative parser. The interface manages configuration, service
and autostart only; routing traffic into the proxy remains a separate task.
