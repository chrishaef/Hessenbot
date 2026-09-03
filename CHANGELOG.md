# Changelog

Notable changes for Hessenbot (Meshhessen). Format inspired by [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added

- Public **Impressum** (`/impressum`) and **Datenschutz** (`/datenschutz`); footer links; editable via Admin → Web-Admin
- Blitzwatch **web setup**: `!blitzwatch web` / `set` (DM PIN) → `/mein-blitzwatch`
- Admin Blitzwatch UI: NodeDB-backed list, search, editor on top; `publicUrl` for DM links

### Changed

- Blitzwatch mesh help/status clearer (`!blitzwatch` / `!blitzwatch?`)
- Ping/test replies with place, Maidenhead, hops, SNR or MQTT

### Fixed

- Channel PSK save (bytes parsing); inbound channel hash → slot mapping
- `publicUrl` / impressum keys auto-added for existing `config.ini` installs

## Earlier history

See Git commit history on `main` and upstream [meshing-around](https://github.com/SpudGunMan/meshing-around) for older changes.
