"""Tests for the Pi installer helpers (no hardware, no root, no network)."""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bot_channels  # noqa: E402
import ini_set  # noqa: E402
import node_config  # noqa: E402

REPO = HERE.parent.parent
MESH_HESSEN_PSK = "+uTMEaOR7hkqaXv+DROOEd5BhvAIQY/CZ/Hr4soZcOU="
HESSENTEST_PSK = "kjp6baIF6IjlCzCclbazHVMscV0J7JYHMmSY4xOlVyw="

SAMPLE = textwrap.dedent(
    """\
    # header comment
    [interface]
    type = serial
    # hostname = meshtastic.local
    # mac = 00:11:22:33:44:55

    [general]
    defaultChannel = 0
    ignoreDefaultChannel = True
    ignoreChannels = 2,3,4 
    messagesChannel = 1

    [webAdmin]
    enabled = False
    """
)


def test_ini_set_replaces_active_key_and_keeps_comments():
    out, changed = ini_set.set_value(SAMPLE, "interface", "type", "tcp")
    assert changed
    assert "type = tcp\n" in out
    assert "# header comment" in out and "# mac = 00:11:22:33:44:55" in out


def test_ini_set_inserts_after_commented_example():
    out, changed = ini_set.set_value(SAMPLE, "interface", "hostname", "localhost")
    assert changed
    lines = out.splitlines()
    i = lines.index("# hostname = meshtastic.local")
    assert lines[i + 1] == "hostname = localhost"


def test_ini_set_noop_when_value_equal():
    out, changed = ini_set.set_value(SAMPLE, "webAdmin", "enabled", "False")
    assert not changed and out == SAMPLE


def test_ini_set_section_and_key_case_insensitive():
    out, changed = ini_set.set_value(SAMPLE, "WEBADMIN", "ENABLED", "True")
    assert changed
    assert "enabled = True" in out


def test_ini_set_appends_missing_key_and_section():
    out, _ = ini_set.set_value(SAMPLE, "general", "newKey", "x")
    assert ini_set.get_value(out, "general", "newKey") == "x"
    out2, _ = ini_set.set_value(SAMPLE, "brandNew", "a", "b")
    assert out2.rstrip().endswith("[brandNew]\na = b")


def test_ini_set_file_roundtrip_and_get(tmp_path: Path):
    f = tmp_path / "config.ini"
    f.write_text(SAMPLE, encoding="utf-8")
    assert ini_set.main([str(f), "--set", "interface.type=tcp", "--set", "location.lat=50.1"]) == 0
    assert ini_set.get_value(f.read_text(), "interface", "type") == "tcp"
    assert ini_set.get_value(f.read_text(), "location", "lat") == "50.1"
    assert ini_set.main([str(f), "--get", "general.messagesChannel"]) == 0
    assert ini_set.main([str(f), "--get", "general.doesNotExist"]) == 3


def test_ini_set_preserves_crlf():
    text = SAMPLE.replace("\n", "\r\n")
    out, _ = ini_set.set_value(text, "interface", "hostname", "localhost")
    assert "\n" not in out.replace("\r\n", "")


@pytest.mark.parametrize(
    "selected,existing,expect",
    [
        ([1], [0, 1], []),  # default: nothing to touch
        ([1], [0, 1, 2], []),
        ([1, 2], [0, 1, 2], [("ignoreChannels", "3,4")]),
        ([0], [0, 1], [("ignoreChannels", "1,2,3,4"), ("ignoreDefaultChannel", "False")]),
        ([0, 1], [0, 1], [("ignoreDefaultChannel", "False")]),
        ([2], [0, 1, 2], [("ignoreChannels", "1,3,4"), ("messagesChannel", "2")]),
    ],
)
def test_bot_channel_mapping_against_template(selected, existing, expect):
    template = (REPO / "config.template").read_text(encoding="utf-8")
    assert bot_channels.plan_changes(template, selected, existing) == expect


def test_bot_channels_apply_writes_only_existing_keys(tmp_path: Path):
    f = tmp_path / "config.ini"
    f.write_text((REPO / "config.template").read_text(encoding="utf-8"), encoding="utf-8")
    assert bot_channels.main([str(f), "--selected", "0,1", "--existing", "0,1", "--apply"]) == 0
    text = f.read_text(encoding="utf-8")
    assert ini_set.get_value(text, "general", "ignoreDefaultChannel") == "False"
    assert ini_set.get_value(text, "general", "messagesChannel") == "1"


def test_bot_channels_rejects_empty_selection(tmp_path: Path):
    f = tmp_path / "config.ini"
    f.write_text(SAMPLE, encoding="utf-8")
    assert bot_channels.main([str(f), "--selected", "", "--existing", "0,1"]) == 2


def test_node_spec_validation():
    spec = {
        "lora": {"region": "EU_868", "modem_preset": "SHORT_SLOW", "tx_power": 24, "tx_enabled": False},
        "channels": [
            {"index": 0, "role": "PRIMARY", "name": "", "psk": "default"},
            {"index": 1, "role": "SECONDARY", "name": "Mesh Hessen", "psk": MESH_HESSEN_PSK},
            {"index": 2, "role": "SECONDARY", "name": "HessenTest", "psk": HESSENTEST_PSK},
        ],
    }
    node_config.validate_spec(spec)
    bad = {"channels": [{"index": 1, "role": "SECONDARY", "name": "x" * 12, "psk": "default"}]}
    with pytest.raises(ValueError):
        node_config.validate_spec(bad)
    with pytest.raises(ValueError):
        node_config.validate_spec({"lora": {"tx_power": 99}})


def test_node_conflict_detection_and_psk_not_exposed():
    spec = {
        "channels": [
            {"index": 0, "role": "PRIMARY", "name": "", "psk": "default"},
            {"index": 1, "role": "SECONDARY", "name": "Mesh Hessen", "psk": MESH_HESSEN_PSK},
        ]
    }
    fp = node_config.psk_fingerprint(node_config.decode_psk(MESH_HESSEN_PSK))
    assert MESH_HESSEN_PSK not in fp and len(fp) == 8
    same = [
        {"index": 0, "role": "PRIMARY", "name": "", "psk_fp": "default"},
        {"index": 1, "role": "SECONDARY", "name": "Mesh Hessen", "psk_fp": fp},
    ]
    assert node_config.find_conflicts(same, spec) == []
    other = [
        {"index": 0, "role": "PRIMARY", "name": "", "psk_fp": "default"},
        {"index": 1, "role": "SECONDARY", "name": "Other", "psk_fp": "deadbeef"},
    ]
    assert len(node_config.find_conflicts(other, spec)) == 1
    unused = [{"index": 1, "role": "DISABLED", "name": "", "psk_fp": "-"}]
    assert node_config.find_conflicts(unused, spec) == []


def _bash(script: str, **env: str) -> subprocess.CompletedProcess:
    full_env = {**os.environ, "INSTALL_LIB_DIR": str(HERE / "lib"), **env}
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=full_env, check=False)


def test_channel_defs_pass_validation():
    r = _bash(
        f"""
        set -Eeuo pipefail
        source "$INSTALL_LIB_DIR/common.sh"
        source "$INSTALL_LIB_DIR/channels.sh"
        CHANNELS_DIR={HERE}/channels.d
        load_channel_defs
        printf '%s|' "${{CHAN_INDEX[@]}}"; echo
        printf '%s|' "${{CHAN_NAME[@]}}"; echo
        """
    )
    assert r.returncode == 0, r.stderr
    idx, names = r.stdout.strip().splitlines()
    assert idx == "0|1|2|"
    assert names == "|Mesh Hessen|HessenTest|"


def test_node_spec_written_0600_and_psks_masked_in_logs(tmp_path: Path):
    spec = tmp_path / "spec.json"
    r = _bash(
        f"""
        set -Eeuo pipefail
        source "$INSTALL_LIB_DIR/common.sh"
        source "$INSTALL_LIB_DIR/channels.sh"
        CHANNELS_DIR={HERE}/channels.d
        HB_LOG_FILE={tmp_path}/log; : > "$HB_LOG_FILE"
        load_channel_defs
        RADIO_REGION=EU_868 MODEM_PRESET=SHORT_SLOW TX_POWER=24 ANTENNA_OK=0 HESSENTEST=on LONG_NAME="Test Node" SHORT_NAME=TST
        write_node_spec {spec}
        stat -c %a {spec}
        log "psk is {MESH_HESSEN_PSK}"
        """
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "600"
    import json

    data = json.loads(spec.read_text())
    assert [c["index"] for c in data["channels"]] == [0, 1, 2]
    assert data["lora"]["tx_enabled"] is False
    assert MESH_HESSEN_PSK not in r.stderr
    assert MESH_HESSEN_PSK not in (tmp_path / "log").read_text()


def test_boot_config_block_is_idempotent(tmp_path: Path):
    cfg = tmp_path / "config.txt"
    cfg.write_text("# base\ndtparam=audio=on\n\n[all]\n#dtparam=spi=on\n", encoding="utf-8")
    r = _bash(
        f"""
        set -Eeuo pipefail
        source "$INSTALL_LIB_DIR/common.sh"
        source "$INSTALL_LIB_DIR/pi_boot.sh"
        render_boot_config {cfg} > {tmp_path}/one
        cp {tmp_path}/one {cfg}
        render_boot_config {cfg} > {tmp_path}/two
        HAS_GPS=1 render_boot_config {cfg} > {tmp_path}/gps
        """
    )
    assert r.returncode == 0, r.stderr
    one = (tmp_path / "one").read_text()
    assert one == (tmp_path / "two").read_text()
    assert one.count("# >>> hessenbot") == 1
    for line in ("dtparam=spi=on", "dtoverlay=spi0-0cs", "dtparam=i2c_arm=on", "dtparam=i2c_vc=on", "dtoverlay=i2c0"):
        assert line in one
    assert "enable_uart" not in one
    assert "enable_uart=1" in (tmp_path / "gps").read_text()


def test_mesh_bot_unit_waits_for_meshtasticd():
    r = _bash(
        """
        source "$INSTALL_LIB_DIR/services.sh"
        render_mesh_bot_unit meshbot meshbot /opt/Hessenbot "/usr/bin/bash /opt/Hessenbot/launch.sh mesh" 1 1
        """
    )
    assert r.returncode == 0
    unit = r.stdout
    assert "Wants=network-online.target meshtasticd.service" in unit
    assert "wait-for-port.sh localhost 4403 60" in unit
    assert "EnvironmentFile=-/etc/hessenbot/env" in unit
    assert "Requires=" not in unit


def test_wizard_dry_run_non_interactive(tmp_path: Path):
    r = subprocess.run(
        ["bash", str(HERE / "wizard.sh"), "--dry-run", "--yes", "--non-interactive"],
        capture_output=True,
        text=True,
        env={**os.environ, "TMPDIR": str(tmp_path)},
        check=False,
    )
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "DRY-RUN beendet" in out
    assert "Kanal #1" in out
    assert MESH_HESSEN_PSK not in out
    assert "TX:              AUS" in out
