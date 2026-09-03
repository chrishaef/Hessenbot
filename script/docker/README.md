# Docker — Hessenbot

Noch kein vollständiges Turnkey-Setup, aber so startest du mit dem **Hessenbot**-Image (nicht Upstream meshing-around).

## Image bauen (empfohlen)

Aus dem Repo-Root:

```sh
docker compose build hessenbot
```

Das nutzt das lokale `Dockerfile` und taggt das Image als `ghcr.io/chrishaef/hessenbot:latest`.

## Fertiges Image von GHCR (nach Release)

Wenn ein Release den Workflow `.github/workflows/docker-image.yml` ausgelöst hat:

```sh
docker pull ghcr.io/chrishaef/hessenbot:latest
# oder ein konkretes Release-Tag, z. B.:
# docker pull ghcr.io/chrishaef/hessenbot:1.1.0
```

GHCR-Namen sind kleingeschrieben (`hessenbot`).

## Netzwerk & starten

```sh
docker network create hessenbot-network

docker compose run meshtasticd
docker compose run hessenbot
docker compose run debug-console
docker compose run ollama
```

Optional Open WebUI:

```sh
docker run -d -p 3000:8080 \
  -e OLLAMA_BASE_URL=http://127.0.0.1:11434 \
  -v open-webui:/app/backend/data \
  --name open-webui --restart always \
  ghcr.io/open-webui/open-webui:main
```

## Hinweise

- `compose.yaml` mountet `.` nach `/app` — dein lokaler Code überschreibt den Container-Inhalt.
- Vor dem Start `config.template` → `config.ini` anpassen (UTF-8). Web-Admin-Passwort setzen oder `HESSENBOT_WEB_PASSWORD`.
- Details: [INSTALL.md](../../INSTALL.md), [README.md](../../README.md)

### Other Stuff

A cool tool to use with RAG creation with open-webui:

- https://github.com/microsoft/markitdown
