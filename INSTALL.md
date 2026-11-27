# INSTALL.md

## Table of Contents

- [Raspberry Pi + RAK6421/RAK13302 (native one-command install)](#raspberry-pi--rak6421rak13302-native-one-command-install)
- [Manual Install](#manual-install)
- [Docker Installation](#docker-installation)
- [Requirements](#requirements)
- [install.sh](#installsh)
  - [Purpose](#purpose)
  - [Usage](#usage)
  - [What it does](#what-it-does)
  - [When to use](#when-to-use)
  - [Note](#note)
- [update.sh](#updatesh)
  - [Purpose](#purpose-1)
  - [Usage](#usage-1)
  - [What it does](#what-it-does-1)
  - [When to use](#when-to-use-1)
  - [Note](#note-1)
- [launch.sh](#launchsh)
  - [Purpose](#purpose-2)
  - [How to Use](#how-to-use)
  - [What it does](#what-it-does-2)
  - [Note](#note-2)

---

## Raspberry Pi + RAK6421/RAK13302 (native one-command install)

Target: Raspberry Pi 4B, Raspberry Pi OS Lite 64-bit (Debian 13 Trixie), RAK6421 HAT with RAK13302 (1 W) in slot 1, SPI, region EU_868. No Docker.

```sh
curl -fsSL https://raw.githubusercontent.com/chrishaef/Hessenbot/main/bootstrap.sh -o /tmp/hb-bootstrap.sh
sudo bash /tmp/hb-bootstrap.sh
```

Review the script first if you like; it is safe to pipe (`curl ... | sudo bash`) because all prompts are read from `/dev/tty`.

What happens:

1. `bootstrap.sh` installs git/curl, clones or fast-forwards `/opt/Hessenbot` and starts `script/install/wizard.sh`.
2. Wizard asks: modem preset (default Europe Short Slow), node names, optional `HessenTest` channel (#2, default no), bot channels, location, web admin, antenna, antenna gain and TX power.
3. Phase A: base packages, `/boot/firmware/config.txt` managed block (`dtparam=spi=on`, `dtoverlay=spi0-0cs`, `dtparam=i2c_arm=on`, `dtparam=i2c_vc=on`, `dtoverlay=i2c0` for HAT EEPROM detection, and the `i2c-dev` module; UART/`disable-bt` are only needed for GPS, which is not part of this version), `/etc/hessenbot/env` (0600). Reboot if needed; the install resumes automatically via `hessenbot-install-resume.service`.
4. Phase B: `meshtasticd` from the OBS repo (`Debian_13`), the LoRa pin config `/etc/meshtasticd/available.d/lora-hat-rak-6421-pi-hat.yaml` (see below), Python 3.13 venv, `config.ini`, node channels (#0 primary, #1 "Mesh Hessen" always, #2 optional), systemd units (`meshtasticd`, `mesh_bot`), self-test.

LoRa hardware config (RAK6421 + RAK13302, Slot 1): the installer writes the config from [SMLunchen/rak6421_rpi_hat_meshtastic_1W](https://github.com/SMLunchen/rak6421_rpi_hat_meshtastic_1W) 1:1 to `/etc/meshtasticd/available.d/lora-hat-rak-6421-pi-hat.yaml` (the name meshtasticd's HAT autodetection looks for) and links it into `config.d`; the shipped copy is `script/install/radios.d/lora-hat-rak-6421-pi-hat.yaml`.

```yaml
Lora:
  Module: sx1262
  CS: 8
  IRQ: 22
  Reset: 16
  Busy: 24
  DIO3_TCXO_VOLTAGE: true
  DIO2_AS_RF_SWITCH: true
  spidev: spidev0.0
```

- `CS: 8` is required: with `spi0-0cs` there is no hardware chip select, and the stock `lora-RAK6421-13302-slot1.yaml` has CS commented out, which ends in `SX126x init result -2`. The installer therefore does not use the stock preset (an old link to it in `config.d` is moved to the backup directory).
- Do **not** set `Enable_Pins`, `SX126X_ANT_SW` or `SX126X_MAX_POWER`: `SX126X_ANT_SW: 13` blocks the TX path (no RF output although packets are counted), `SX126X_MAX_POWER: 30` causes `init result -13` (SPI timeout).
- TX power: meshtasticd reports about 22 dBm, which is the SX1262 chip power. The SKY66122 PA (about +13 dB) is switched via `DIO2_AS_RF_SWITCH`, no extra GPIO control is needed. The power at the antenna connector is therefore well above the configured `lora.tx_power`; observe the regional limits for your antenna.
- `General.MACAddressSource` is written to `config.d/hessenbot.yaml` (`end0` on Raspberry Pi OS Bookworm/Trixie, `eth0` on older images) so the node id stays stable.
- The self-test reads `SX126x init result` from the journal (0 = ok, -2 = check CS/SPI, -13 = remove `SX126X_ANT_SW`/`SX126X_MAX_POWER`).

Channels and bot: the bot serves only the channels you pick, using the existing `ignoreChannels`, `ignoreDefaultChannel` and `messagesChannel` keys. If you re-run with HessenTest off and channel #2 on the node is still named `HessenTest`, the installer disables it on the node; a channel #2 with any other name is left alone.

TX safety: `lora.tx_enabled` stays `false` until you confirm an antenna is attached; the installer does not cap `tx_power`. The installer reads the node back after configuring it and aborts if TX is active without a confirmed antenna; in that case it also stops `meshtasticd` automatically.

**TX window on first configuration:** the firmware switches TX on when the region is set for the first time, so the installer applies the TX gate (`tx_enabled=false`) in a second pass right after the first node restart. Until then the node can transmit briefly (for example a NodeInfo broadcast). **Connect the antenna (or a 50 ohm load) to the RAK13302 before running the installer.** If you answer "Antenna: no", the wizard warns and asks for confirmation (default no; unattended: `--accept-tx-window`), and it keeps `tx_power` at 1 dBm until you release TX.

**TX power (no hard cap):** the wizard asks for `lora.tx_power` in dBm, 1 to 30, default 14; `max` selects full power (30; the firmware limits it to what the hardware supports). Unattended: `--tx-power 22` or `--tx-power max`. Values above 14 dBm can exceed the EU 868 limits (depending on the sub-band 14 or 27 dBm ERP, 1-10 % duty cycle), and with the RAK13302 PA (SKY66122, about +13 dB via `DIO2_AS_RF_SWITCH`) the power at the antenna is well above the setting. For such values the wizard shows this warning and requires confirmation (default no; declining asks again, nothing is clamped silently). With `--yes` it aborts unless you also pass `--accept-tx-power`. The antenna gain is only used in the warning. The confirmation is remembered for that exact value only (state file), so changing the value asks again. You are responsible for complying with local regulations.

**Changing TX power later:** web admin, tab *Node Settings* (`/node-settings`), section *Sendeleistung (LoRa)*. It reads and writes `lora.tx_power` on the connected node (0-30 dBm, 30 = full power, 0 = firmware default) with the same warning; raising or keeping a value above 14 dBm that you change needs the confirmation checkbox, lowering to 14 or less does not.

To release TX later (antenna attached; use the `tx_power` from the final notes): `sudo /opt/Hessenbot/venv/bin/meshtastic --host localhost --set lora.tx_power 14 --set lora.tx_enabled true`.

Re-runs: the wizard remembers your answers (`/var/lib/hessenbot-install/state.env`, no secrets). If you decline to reuse them you are asked everything again. If a reboot-resume fails, the reason is shown at the next login (`/etc/motd.d/50-hessenbot-install`). The resume unit is not retried on every boot; start the wizard again (or `wizard.sh --resume`). The unit stays until the install succeeds; follow it with `journalctl -u hessenbot-install-resume -f`. When you reuse saved answers without an antenna and the node already has stored settings, you are asked to acknowledge that before `meshtasticd` starts (skipped once the installer has verified TX off on that node).

An existing node identity (`/var/lib/meshtasticd`) must be acknowledged before `meshtasticd` is started, because its old settings may transmit.

Hardware: without a RAK6421 HAT EEPROM hit the wizard asks whether the hardware is a RAK6421 + RAK13302 (default no); use `--confirm-hardware` together with `--yes`. After the install, the summary lists `config.ini` overrides the installer applied (channels, web admin). In non-interactive mode set the web admin password via `HESSENBOT_WEB_PASSWORD`; otherwise use the interactive prompt. The summary prints the node ID; request MeshHessen MQTT access with it in the MQTT web admin.

Options (`sudo bash /opt/Hessenbot/script/install/wizard.sh ...`):

| Flag | Meaning |
|------|---------|
| `--dry-run` | Print the plan, change nothing (no root needed via `bootstrap.sh --dry-run`) |
| `--yes`, `--non-interactive` | Accept defaults / take values from flags (`--preset`, `--long-name`, `--short-name`, `--hessentest`, `--bot-channels`, `--lat`, `--lon`, `--web-admin`, `--antenna`, `--antenna-gain`, `--tx-power`) |
| `--meshtasticd-channel beta\|alpha\|daily` | OBS repository channel for `meshtasticd` (default `beta`; the signing key fingerprint is pinned, a new key needs explicit confirmation) |
| `--install-dir DIR` | Bot install directory (default `/opt/Hessenbot`; the wizard must run from there) |
| `--accept-tx-power` | Unattended: confirm a `--tx-power` above 14 dBm (possible EU 868 limit violation; needed with `--yes`) |
| `--accept-tx-window` | Unattended: accept the short TX window without antenna and start `meshtasticd` with existing node settings (needed with `--yes` and `--antenna no`) |
| `--confirm-hardware` | Confirm RAK6421 + RAK13302 (Slot 1) without a HAT EEPROM hit (for `--yes`) |
| `--revert` | Undo changes recorded in `/var/lib/hessenbot-install/manifest` (files are moved to `/var/backups/hessenbot/`, apt packages and node identity are kept; add `--yes` to skip the confirmation) |
| `--resume`, `--no-reboot` | Continue after reboot / do not reboot automatically |
| `--skip-meshtasticd`, `--skip-node-config` | Skip those steps |

`bootstrap.sh --legacy` keeps the previous venv + `config.ini` behaviour. `install.sh --nope` removes the bot after a typed `yes` confirmation and a backup tarball in `/var/backups/hessenbot/`.

Log: `/var/log/hessenbot-install.log` (0600, PSKs and passwords masked). Notes: `/opt/Hessenbot/install_notes.txt`.

### Remote clients (Companion app, MeshHessen client, MeshMonitor) -> meshtasticd :4403

**Security first.** The meshtasticd TCP API (`4403`) has **no authentication and no TLS**. Anyone who can reach the port can read and change the node (channel keys, config, factory reset, TX settings). Never forward it through your router and never expose it to the internet. Use LAN and/or Tailscale only.

Facts (from the meshtasticd source):

- meshtasticd already listens on `0.0.0.0:4403` (IPv4 only). There is no bind-address option, so there is nothing to "fix" in `config.yaml`; the only control is a firewall. The installer does not configure a firewall, and Raspberry Pi OS ships none, so on a fresh install `4403` is reachable from your whole LAN (and over Tailscale). The Hessenbot bot itself connects via `localhost` and is unaffected by firewall rules.
- Optional: `General: APIPort: <1024-65535>` in `/etc/meshtasticd/config.d/*.yaml` moves the port (then use `hostname = localhost:<port>` in `config.ini`). It is not a security measure.
- **meshtasticd serves exactly one TCP API client at a time.** A new connection force-closes the previous one. `mesh_bot` reconnects automatically (watchdog, about 20 to 35 s), so a Companion/MeshMonitor session and the bot will keep kicking each other off. The Meshtastic web UI of meshtasticd (`https://<pi>/`, port 443 by default) is a separate path and not affected by this single-client rule.

Restrict the port with UFW (helper, never opens to the world):

```sh
sudo bash /opt/Hessenbot/script/install/remote-access.sh status
sudo bash /opt/Hessenbot/script/install/remote-access.sh lan --enable          # own subnet, auto-detected (or: lan 192.168.1.0/24)
sudo bash /opt/Hessenbot/script/install/remote-access.sh tailscale              # tailscale0 only
sudo bash /opt/Hessenbot/script/install/remote-access.sh close                  # remove these rules again
```

`--enable` switches UFW on if it is inactive and allows SSH (22/tcp) first. With UFW active everything else incoming is denied, so also allow what you use (for example the web admin: `sudo ufw allow from 192.168.1.0/24 to any port 5000 proto tcp`). Manual equivalent: `sudo ufw allow from 192.168.1.0/24 to any port 4403 proto tcp` or `sudo ufw allow in on tailscale0 to any port 4403 proto tcp`; verify with `ss -ltn '( sport = :4403 )'` and from the client (`meshtastic --host <pi-ip> --info`).

Running several clients at once: native multi-connect is not enough. Either stop the bot while you configure (`sudo systemctl stop mesh_bot`, then `start`), or put a multiplexer in front, for example the Virtual Node of MeshMonitor (MeshMonitor is the only direct client on `4403`; Companion/MeshHessen connect to MeshMonitor's virtual-node port). Virtual nodes block admin messages by default, so settings changes then go through MeshMonitor or a direct, temporary connection.

---

## Manual Install

Install all required dependencies using pip:

```sh
pip install -r requirements.txt
```

Copy the configuration template and edit as needed:

```sh
cp config.template config.ini
```

---

## Docker Installation

See [script/docker/README.md](script/docker/README.md) for Docker-based setup instructions.  
Docker is recommended for Windows or if you want an isolated environment.

---

## Requirements

- **Python 3.8 or later** (Python 3.13+ supported in Docker)
- All dependencies are listed in `requirements.txt` and can be installed with:
  ```sh
  pip install -r requirements.txt
  ```
- To enable emoji in the Debian/Ubuntu console:
  ```sh
  sudo apt-get install fonts-noto-color-emoji
  ```
- For Ollama LLM support, see the prompts during `install.sh` or visit [https://ollama.com](https://ollama.com).

---

## install.sh

### Purpose

`install.sh` automates installation, configuration, and service setup for **Hessenbot**. It is designed for Linux systems (Debian/Ubuntu/Raspberry Pi and embedded devices).

### Usage

Run from the project root directory:

```sh
bash install.sh
```

To uninstall:

```sh
bash install.sh --nope
```

### What it does

- Checks for existing installations and permissions.
- Optionally moves the project to `/opt/Hessenbot`.
- Installs Python and pip if missing (unless on embedded systems).
- Adds the current user (or a dedicated `meshbot` user) to necessary groups for serial and Bluetooth access.
- Copies and configures systemd service files for running the bot as a service.
- Sets up configuration files, updating latitude/longitude automatically.
- Offers to create and activate a Python virtual environment, or install dependencies system-wide.
- Installs optional components (emoji fonts, Ollama LLM) if desired.
- Sets permissions for log and data directories.
- Optionally installs and enables the bot as a systemd service.
- Provides post-installation notes and commands in `install_notes.txt`.
- Offers to reboot the system to complete setup.

### When to use

- For first-time installation of Hessenbot.
- When migrating to a new device or environment.
- After cloning or updating the repository to set up dependencies and services.

### Note

- You may be prompted for input during installation (e.g., for embedded mode, virtual environment, or optional features).
- Review and edit the script if you have custom requirements or are running on a non-standard system.

---

## update.sh

### Purpose

`update.sh` is an update and maintenance script for **Hessenbot**. It automates the process of safely updating your codebase, backing up data, and merging configuration changes.

### Usage

Run from the project root directory:

```sh
bash update.sh
```
Or, after making it executable:
```sh
chmod +x update.sh
./update.sh
```

### What it does

- Stops running Mesh Bot services to prevent conflicts during update.
- Fetches and pulls the latest changes from the GitHub repository (using `git pull --rebase`).
- Handles git conflicts, offering to reset to the latest remote version if needed.
- Copies a custom scheduler template if not already present.
- Backs up the `data/` directory (and `custom_scheduler.py` if present) to a compressed archive.
- Merges your existing configuration with new defaults using `script/configMerge.py`, and logs the process.
- Restarts services if they were stopped for the update.
- Provides status messages and logs for troubleshooting.

### When to use

- To update your Mesh Bot installation to the latest version.
- Before making significant changes or troubleshooting, as it creates a backup of your data.

### Note

- Review `ini_merge_log.txt` and `config_new.ini` after running for any configuration changes or errors.
- You may be prompted if git conflicts are detected.

---

## launch.sh

### Purpose

`launch.sh` is a convenience script for starting Hessenbot or generating reports within the Python virtual environment. It ensures the correct environment is activated and the appropriate script is run.

### How to Use

From your project root, run one of the following commands:

- Launch Hessenbot (mesh_bot):  
  ```sh
  bash launch.sh mesh
  ```
- Generate HTML report:  
  ```sh
  bash launch.sh html
  ```
- Generate HTML5 report:  
  ```sh
  bash launch.sh html5
  ```
- Add a favorite (calls `script/addFav.py`):  
  ```sh
  bash launch.sh add
  ```

### What it does

- Ensures you are in the project directory.
- Copies `config.template` to `config.ini` if no config exists.
- Activates the Python virtual environment (`venv`).
- Runs the selected Python script based on your argument.
- Deactivates the virtual environment when done.

### Note

- The script requires a Python virtual environment (`venv`) to be present in the project directory.
- If `venv` is missing, the script will exit with an error message.
- Always provide an argument (`mesh`, `html`, `html5`, or `add`) to specify what you want to launch.

## Troubleshooting

### Permissions Issues

If you encounter errors related to file or directory permissions (e.g., "Permission denied" or services failing to start):

- Ensure you are running installation scripts with sufficient privileges (use `sudo` if needed).
- The `logs`, `data`, and `config.ini` files must be owned by the user running the bot (often `meshbot` or your current user).
- You can manually reset permissions using the provided script:

  ```sh
  sudo bash etc/set-permissions.sh meshbot
  ```

- If you moved the project directory, re-run the permissions script to update ownership.

- For systemd service issues, check logs with:
  ```sh
  sudo journalctl -u mesh_bot.service
  ```

If problems persist, double-check that the user specified in your service files matches the owner of the project files and directories.