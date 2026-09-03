# Security Policy

## Supported versions

Hessenbot is developed as **rolling code** on the `main` branch. Security fixes are applied there; please update regularly (`git pull` / your deploy process).

| Branch / release | Supported |
| ---------------- | --------- |
| `main` (latest)  | Yes       |
| Older commits / forks without updates | No |

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security-sensitive findings (e.g. auth bypass, remote code execution, exposure of secrets, privilege escalation in the web admin).

Prefer one of these:

1. **GitHub Security Advisory** (private): Repository → Security → Advisories → “New draft security advisory” (if enabled for the repo)
2. **Private contact** via a GitHub issue titled `[SECURITY]` **without** exploit details, asking for a secure channel — or open a draft advisory as above

Include what you can safely share:

- Affected version / commit
- Description of the issue and impact
- Steps to reproduce (or a proof-of-concept)
- Whether you plan a public disclosure timeline

You should hear back within a few days when possible. Please give a reasonable time to fix before public disclosure.

## Scope (examples)

In scope:

- Web admin authentication / session handling
- Unauthenticated access to admin-only or node-specific settings
- Injection or path traversal in the Flask UI / file viewers
- Accidental leakage of `config.ini` secrets, API keys, or mesh credentials through the UI or logs exposed by the app

Out of scope / expected behaviour:

- Mesh traffic is radio/MQTT and **not confidential** by design of the network
- Public dashboard showing mesh-derived stats, NodeDB excerpts, BBS posts
- Issues that only affect misconfigured deployments (e.g. `webAdmin` exposed to the internet with a weak password)

## Hardening tips for operators

- Set a strong `[webAdmin]` password (or `HESSENBOT_WEB_PASSWORD`) and `secret_key` / `HESSENBOT_WEB_SECRET`
- Do not commit `config.ini`, credentials, or private keys
- Prefer binding the web UI behind a reverse proxy / VPN when exposing beyond LAN
- Keep Python dependencies and the host OS updated
- Fill in Impressum / contact fields if the portal is public
