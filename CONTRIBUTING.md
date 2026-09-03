# Contributing to Hessenbot

Thanks for helping improve Hessenbot (Meshhessen Meshtastic bot).

## How we work

- Development is **rolling** on `main` — small, focused pull requests are preferred.
- This project is a fork of [SpudGunMan/meshing-around](https://github.com/SpudGunMan/meshing-around); Meshhessen / DE-EU behaviour lives mainly under `modules/` and the Flask portal.

## Before you start

1. Read [README.md](README.md) and [INSTALL.md](INSTALL.md).
2. Copy `config.template` → `config.ini` (UTF-8). **Never commit** `config.ini`, passwords, API keys, or private data.
3. See [modules/README.md](modules/README.md) for module layout.

## Development setup

```sh
git clone https://github.com/chrishaef/Hessenbot.git
cd Hessenbot
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config.template config.ini
```

Run relevant tests:

```sh
python3 -m pytest modules/test_blitzwatch.py -q
python3 modules/test_bot.py
```

## Pull requests

1. Fork the repo and create a branch from `main`.
2. Keep changes scoped (one topic per PR).
3. Match existing code style (German UI strings where the portal already uses German).
4. Update docs (`README.md`, `config.template`, tooltips) when behaviour or config keys change.
5. Open a PR against `chrishaef/Hessenbot` `main` with a short summary and how you tested.

## Reporting bugs / ideas

- Use GitHub Issues (bug / feature templates if available).
- For **security** issues, see [SECURITY.md](SECURITY.md) — do not post exploits publicly.

## Code of conduct

Please follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
