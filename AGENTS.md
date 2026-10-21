# AGENTS.md

## Project overview

This repository contains OpenWrt packages for ByeDPI and its LuCI web interface.

The main components are:

- `byedpi/` — ByeDPI package, configuration files, and init scripts.
- `luci-app-byedpi/` — LuCI web interface for managing ByeDPI.
- `docs/tasks/` — implementation specifications for individual development tasks.

Before modifying code, inspect the existing repository structure and relevant files. Do not assume that all listed directories already exist.

## General rules

- Prefer simple, maintainable solutions.
- Follow existing OpenWrt and LuCI conventions.
- Avoid unnecessary abstractions and dependencies.
- Do not rewrite working code unless required by the task.
- Keep changes focused on the requested functionality.
- Preserve backward compatibility whenever possible.
- Do not modify unrelated files.

## OpenWrt compatibility

- Target OpenWrt 24.10 and 25.12.
- Support the package management systems used by the targeted releases.
- Use standard OpenWrt build and packaging conventions.
- Use UCI for persistent configuration.
- Use procd and the existing init scripts for service management.
- Do not introduce a separate service management mechanism.

## LuCI development

- Use modern JavaScript-based LuCI views.
- Prefer standard LuCI APIs and components.
- Do not use legacy Lua CBI for new interfaces.
- Follow standard LuCI menu and RPC ACL conventions.
- Use the LuCI translation mechanism for user-facing strings.
- Support both desktop and mobile layouts.
- Avoid third-party frontend frameworks.

## Configuration

- Treat `/etc/config/byedpi` as the authoritative configuration source.
- Preserve existing UCI options and unknown configuration sections.
- Avoid destructive configuration migrations.
- Respect the behavior of the existing ByeDPI init script.
- Never silently discard user configuration.

## Security

- Apply the principle of least privilege to RPC permissions.
- Validate input before modifying configuration files.
- Avoid shell injection vulnerabilities.
- Do not expose arbitrary command execution through LuCI.
- Do not allow unrestricted filesystem access.
- Never log credentials or other sensitive information.

## Validation

After making changes:

- Check syntax and formatting where tooling is available.
- Verify compatibility with existing configuration formats.
- Run relevant builds and tests when possible.
- Review changes for unintended modifications.
- Do not claim tests passed unless they were actually executed.
- Report any checks that could not be performed.

## Task execution

- Read the relevant task specification before implementation.
- Inspect the existing code before choosing an approach.
- Implement the requested functionality rather than stopping at a plan.
- Make reasonable implementation decisions independently.
- Ask for clarification only when an ambiguity prevents correct implementation.
- Do not introduce unrelated improvements.

## Completion report

At the end of each task, provide:

1. Summary of implemented changes.
2. List of important modified or created files.
3. Build and installation instructions, when applicable.
4. Validation results.
5. Known limitations or remaining issues.
