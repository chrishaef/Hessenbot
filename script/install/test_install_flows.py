"""Regression tests for installer flows (re-run/resume, apt, TX gate, revert); no hardware, root or network."""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bot_channels  # noqa: E402
import node_config  # noqa: E402

LIB = HERE / "lib"

PREAMBLE = """
set -Eeuo pipefail
export HB_STATE_DIR="$T/state" HB_BACKUP_DIR="$T/backup" HB_LOG_FILE="$T/log" HB_STATUS_FILE="$T/motd"
mkdir -p "$HB_STATE_DIR" "$HB_BACKUP_DIR"
source "@HERE@/wizard.sh"
install() { command install -m "$2" "${@: -2}"; }
"""


def run_wizard_lib(script: str, tmp_path: Path, **env: str) -> subprocess.CompletedProcess:
    full_env = {**os.environ, "T": str(tmp_path), **env}
    body = PREAMBLE.replace("@HERE@", str(HERE)) + textwrap.dedent(script)
    return subprocess.run(["bash", "-c", body], capture_output=True, text=True, env=full_env, check=False)


def write_state(tmp_path: Path, **values: str) -> Path:
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    f = state / "state.env"
    f.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    return f


SAVED = dict(
    MODEM_PRESET="LONG_FAST",
    ANTENNA_OK="1",
    ANTENNA_GAIN="3",
    TX_POWER="24",
    TX_POWER_ACK="24",
    WEB_ADMIN="0",
    HAS_GPS="0",
    BOT_CHANNELS="1",
    LAT="50.1",
    LON="8.6",
    PHASE_A_DONE="1",
)


# --- B1: re-run / resume -----------------------------------------------------------------


def test_rerun_declined_reuse_starts_clean_and_persists_new_answers(tmp_path: Path):
    write_state(tmp_path, **SAVED)
    r = run_wizard_lib(
        """
        DRY_RUN=0 RESUME=0
        confirm() { return 1; }
        ask_all() {
            echo "ENTRY[${MODEM_PRESET}][${ANTENNA_OK}][${WEB_ADMIN}]"
            MODEM_PRESET=SHORT_SLOW ANTENNA_OK=0 WEB_ADMIN=1 TX_POWER=24
        }
        resolve_answers
        echo "REUSE=$REUSE PHASE_A_DONE=$PHASE_A_DONE PRESET=$MODEM_PRESET ANT=$ANTENNA_OK WEB=$WEB_ADMIN"
        """,
        tmp_path,
    )
    assert r.returncode == 0, r.stderr
    assert "ENTRY[][][]" in r.stdout, "old answers must not leak into a fresh run"
    assert "REUSE=0 PHASE_A_DONE=0 PRESET=SHORT_SLOW ANT=0 WEB=1" in r.stdout
    saved = (tmp_path / "state" / "state.env").read_text()
    assert "MODEM_PRESET=SHORT_SLOW" in saved and "ANTENNA_OK=0" in saved and "PHASE_A_DONE=0" in saved


def test_rerun_accepted_reuse_loads_state_and_flags_win(tmp_path: Path):
    write_state(tmp_path, **SAVED)
    r = run_wizard_lib(
        """
        DRY_RUN=0 RESUME=0
        ANTENNA_GAIN=5.5
        confirm() { return 0; }
        ask_all() { echo "ask_all must not run"; exit 9; }
        resolve_answers
        echo "REUSE=$REUSE PHASE_A_DONE=$PHASE_A_DONE PRESET=$MODEM_PRESET GAIN=$ANTENNA_GAIN TX=$TX_POWER ACK=$TX_POWER_ACK CH=$MESHTASTICD_CHANNEL"
        """,
        tmp_path,
    )
    assert r.returncode == 0, r.stderr
    assert "REUSE=1 PHASE_A_DONE=1 PRESET=LONG_FAST GAIN=5.5 TX=24 ACK=24 CH=beta" in r.stdout


def test_resume_uses_state_without_prompting_and_requires_state(tmp_path: Path):
    write_state(tmp_path, **SAVED)
    ok = run_wizard_lib(
        """
        DRY_RUN=0 RESUME=1
        confirm() { echo "confirm must not be called"; exit 9; }
        resolve_answers
        echo "REUSE=$REUSE PHASE_A_DONE=$PHASE_A_DONE"
        """,
        tmp_path,
    )
    assert ok.returncode == 0, ok.stderr
    assert "REUSE=1 PHASE_A_DONE=1" in ok.stdout

    (tmp_path / "state" / "state.env").unlink()
    bad = run_wizard_lib("DRY_RUN=0 RESUME=1\nresolve_answers\n", tmp_path)
    assert bad.returncode != 0


def test_state_roundtrip_keeps_special_characters(tmp_path: Path):
    r = run_wizard_lib(
        """
        LONG_NAME="Node 'A' & Co" MODEM_PRESET=SHORT_SLOW PHASE_A_DONE=0
        state_save "${STATE_VARS[@]}"
        LONG_NAME="" MODEM_PRESET=""
        state_load
        printf '%s|%s\\n' "$LONG_NAME" "$MODEM_PRESET"
        """,
        tmp_path,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "Node 'A' & Co|SHORT_SLOW"


# --- TX power: no hard cap, warning + confirmation above the EU-safe level --------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [("", "14"), ("auto", "14"), ("0", "0"), ("1", "1"), ("14", "14"), ("22", "22"), ("30", "30"), ("max", "30"), ("FULL", "30"), ("07", "7")],
)
def test_normalize_tx_power_accepts_full_power(tmp_path: Path, raw: str, expected: str):
    r = run_wizard_lib(f"normalize_tx_power '{raw}'", tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == expected


@pytest.mark.parametrize("raw", ["31", "-3", "abc", "14.5"])
def test_normalize_tx_power_rejects_out_of_range(tmp_path: Path, raw: str):
    assert run_wizard_lib(f"normalize_tx_power '{raw}'", tmp_path).returncode != 0


def test_tx_power_default_is_safe_and_needs_no_confirmation(tmp_path: Path):
    r = run_wizard_lib(
        """
        DRY_RUN=0 ASSUME_YES=1 ANTENNA_OK=1 ANTENNA_GAIN=3
        ask_tx_power
        echo "TX=$TX_POWER ACK=[$TX_POWER_ACK]"
        """,
        tmp_path,
    )
    assert r.returncode == 0, r.stderr
    assert "TX=14 ACK=[]" in r.stdout
    assert "WARNUNG" not in r.stderr


def test_high_tx_power_requires_confirmation_and_is_not_clamped(tmp_path: Path):
    blocked = run_wizard_lib(
        "DRY_RUN=0 ASSUME_YES=1 ANTENNA_OK=1 ANTENNA_GAIN=3 TX_POWER_REQ=max\nask_tx_power", tmp_path
    )
    assert blocked.returncode != 0
    assert "WARNUNG" in blocked.stderr and "EU-868" in blocked.stderr and "SKY66122" in blocked.stderr
    assert "--accept-tx-power" in blocked.stderr
    accepted = run_wizard_lib(
        """
        DRY_RUN=0 ASSUME_YES=1 ANTENNA_OK=1 ANTENNA_GAIN=3 TX_POWER_REQ=max TX_POWER_ACCEPT=1
        ask_tx_power
        echo "TX=$TX_POWER ACK=$TX_POWER_ACK"
        """,
        tmp_path,
    )
    assert accepted.returncode == 0, accepted.stderr
    assert "TX=30 ACK=30" in accepted.stdout


def test_tx_power_zero_means_region_max_and_needs_confirmation(tmp_path: Path):
    blocked = run_wizard_lib("DRY_RUN=0 ASSUME_YES=1 ANTENNA_OK=1 ANTENNA_GAIN=3 TX_POWER_REQ=0\nask_tx_power", tmp_path)
    assert blocked.returncode != 0
    assert "Regions-Maximum" in blocked.stderr and "NICHT 'aus'" in blocked.stderr
    assert "--accept-tx-power" in blocked.stderr
    accepted = run_wizard_lib(
        """
        DRY_RUN=0 ASSUME_YES=1 ANTENNA_OK=1 ANTENNA_GAIN=3 TX_POWER_REQ=0 TX_POWER_ACCEPT=1
        ask_tx_power
        echo "TX=$TX_POWER ACK=$TX_POWER_ACK"
        """,
        tmp_path,
    )
    assert accepted.returncode == 0, accepted.stderr
    assert "TX=0 ACK=0" in accepted.stdout
    # a saved confirmation for another value does not cover 0; one for exactly 0 does
    stale = run_wizard_lib("DRY_RUN=0 ASSUME_YES=1 ANTENNA_OK=1 TX_POWER=0 TX_POWER_ACK=22\nask_tx_power", tmp_path)
    assert stale.returncode != 0
    saved = run_wizard_lib("DRY_RUN=0 ASSUME_YES=1 ANTENNA_OK=1 TX_POWER=0 TX_POWER_ACK=0\nask_tx_power\necho TX=$TX_POWER", tmp_path)
    assert saved.returncode == 0, saved.stderr
    assert "TX=0" in saved.stdout


def test_tx_power_zero_interactive_declined_asks_again(tmp_path: Path):
    r = run_wizard_lib(
        """
        DRY_RUN=0 ANTENNA_OK=1 ANTENNA_GAIN=3
        n=0
        ask() { n=$((n + 1)); if [[ $n -eq 1 ]]; then REPLY_VALUE=0; else REPLY_VALUE=10; fi; }
        confirm() { return 1; }
        ask_tx_power
        echo "TX=$TX_POWER ACK=[$TX_POWER_ACK] asked=$n"
        """,
        tmp_path,
    )
    assert r.returncode == 0, r.stderr
    assert "TX=10 ACK=[] asked=2" in r.stdout


def test_high_tx_power_warning_mentions_firmware_cap_without_ham(tmp_path: Path):
    r = run_wizard_lib("DRY_RUN=0 ASSUME_YES=1 ANTENNA_OK=1 TX_POWER_REQ=30\nask_tx_power", tmp_path)
    assert r.returncode != 0
    assert "HAM" in r.stderr and "Regionslimit" in r.stderr


def test_high_tx_power_interactive_confirm_yes_and_no(tmp_path: Path):
    yes = run_wizard_lib(
        """
        DRY_RUN=0 ANTENNA_OK=1 ANTENNA_GAIN=3
        ask() { REPLY_VALUE=27; }
        confirm() { echo "CONFIRM: $1" >&2; return 0; }
        ask_tx_power
        echo "TX=$TX_POWER ACK=$TX_POWER_ACK"
        """,
        tmp_path,
    )
    assert yes.returncode == 0, yes.stderr
    assert "TX=27 ACK=27" in yes.stdout and "CONFIRM:" in yes.stderr
    # declining re-asks (no silent clamp): the second answer is 14
    no = run_wizard_lib(
        """
        DRY_RUN=0 ANTENNA_OK=1 ANTENNA_GAIN=3
        n=0
        ask() { n=$((n + 1)); if [[ $n -eq 1 ]]; then REPLY_VALUE=30; else REPLY_VALUE=14; fi; }
        confirm() { return 1; }
        ask_tx_power
        echo "TX=$TX_POWER ACK=[$TX_POWER_ACK] asked=$n"
        """,
        tmp_path,
    )
    assert no.returncode == 0, no.stderr
    assert "TX=14 ACK=[] asked=2" in no.stdout


def test_tx_power_ack_is_bound_to_the_confirmed_value(tmp_path: Path):
    ok = run_wizard_lib(
        'DRY_RUN=0 ASSUME_YES=1 ANTENNA_OK=1 TX_POWER=22 TX_POWER_ACK=22\nask_tx_power\necho "TX=$TX_POWER"', tmp_path
    )
    assert ok.returncode == 0, ok.stderr
    assert "TX=22" in ok.stdout
    stale = run_wizard_lib("DRY_RUN=0 ASSUME_YES=1 ANTENNA_OK=1 TX_POWER=30 TX_POWER_ACK=22\nask_tx_power", tmp_path)
    assert stale.returncode != 0 and "--accept-tx-power" in stale.stderr


def test_tx_power_flags_parse(tmp_path: Path):
    r = run_wizard_lib('parse_args --tx-power max --accept-tx-power\necho "$TX_POWER_REQ$TX_POWER_ACCEPT"', tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "max1"


# --- I1: apt options / conffile -------------------------------------------------------------------


def test_apt_run_never_prompts_and_waits_for_lock(tmp_path: Path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "apt-get"
    fake.write_text(
        '#!/usr/bin/env bash\necho "ARGS: $*" >"$T/apt-args"\necho "FRONTEND: $DEBIAN_FRONTEND" >>"$T/apt-args"\n'
        'if read -t 1 -r _; then echo "STDIN: data" >>"$T/apt-args"; else echo "STDIN: eof" >>"$T/apt-args"; fi\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    r = run_wizard_lib("DRY_RUN=0\napt_run install meshtasticd", tmp_path, PATH=f"{fake_bin}:{os.environ['PATH']}")
    assert r.returncode == 0, r.stderr
    args = (tmp_path / "apt-args").read_text()
    assert "--force-confold" in args and "--force-confdef" in args
    assert "DPkg::Lock::Timeout=300" in args
    assert "install meshtasticd" in args
    assert "FRONTEND: noninteractive" in args
    assert "STDIN: eof" in args


def test_general_config_goes_to_config_d_and_leaves_conffile_untouched(tmp_path: Path):
    etc = tmp_path / "etc"
    etc.mkdir()
    conffile = etc / "config.yaml"
    conffile.write_text("General:\n  MaxNodes: 200\n", encoding="utf-8")
    before = conffile.read_text()
    net = tmp_path / "net"
    net.mkdir()
    (net / "end0").mkdir()
    env = {"MESHTASTICD_ETC": str(etc), "HB_NET_DIR": str(net)}
    r = run_wizard_lib("DRY_RUN=0\nensure_general_config", tmp_path, **env)
    assert r.returncode == 0, r.stderr
    assert conffile.read_text() == before
    assert "MACAddressSource: end0" in (etc / "config.d" / "hessenbot.yaml").read_text()

    # already configured by the user: nothing is written
    conffile.write_text("General:\n  MACAddressSource: wlan0\n", encoding="utf-8")
    (etc / "config.d" / "hessenbot.yaml").unlink()
    r = run_wizard_lib("DRY_RUN=0\nensure_general_config", tmp_path, **env)
    assert r.returncode == 0, r.stderr
    assert not (etc / "config.d" / "hessenbot.yaml").exists()


# --- I2 / I4: TX gate verification ---------------------------------------------------------------


def _fake_node(current_lora: dict[str, Any], chans: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(node_config, "read_channels", lambda iface: chans)
    monkeypatch.setattr(node_config, "read_lora", lambda iface: current_lora)


SPEC = {
    "lora": {"region": "EU_868", "modem_preset": "SHORT_SLOW", "tx_power": 24, "tx_enabled": False},
    "channels": [
        {"index": 0, "role": "PRIMARY", "name": "", "psk": "default"},
        {"index": 1, "role": "SECONDARY", "name": "Mesh Hessen", "psk": "+uTMEaOR7hkqaXv+DROOEd5BhvAIQY/CZ/Hr4soZcOU="},
    ],
}


def _chans_ok() -> list[dict[str, Any]]:
    fp = node_config.psk_fingerprint(node_config.decode_psk(SPEC["channels"][1]["psk"]))
    return [
        {"index": 0, "role": "PRIMARY", "name": "", "psk_fp": "default"},
        {"index": 1, "role": "SECONDARY", "name": "Mesh Hessen", "psk_fp": fp},
    ]


def test_verify_passes_when_node_matches_spec(monkeypatch, capsys):
    _fake_node({"region": "EU_868", "modem_preset": "SHORT_SLOW", "tx_power": 24, "tx_enabled": False}, _chans_ok(), monkeypatch)
    assert node_config.cmd_verify(object(), SPEC) == 0


def test_verify_reports_lora_and_channel_mismatch(monkeypatch, capsys):
    chans = _chans_ok()[:1]
    _fake_node({"region": "UNSET", "modem_preset": "LONG_FAST", "tx_power": 0, "tx_enabled": False}, chans, monkeypatch)
    assert node_config.cmd_verify(object(), SPEC) == node_config.EXIT_MISMATCH
    out = capsys.readouterr().out
    assert "lora.region" in out and "lora.modem_preset" in out and "lora.tx_power" in out
    assert "channel #1: missing" in out


def test_verify_flags_tx_enabled_without_antenna_as_unsafe(monkeypatch, capsys):
    _fake_node({"region": "EU_868", "modem_preset": "SHORT_SLOW", "tx_power": 24, "tx_enabled": True}, _chans_ok(), monkeypatch)
    assert node_config.cmd_verify(object(), SPEC) == node_config.EXIT_TX_UNSAFE
    assert "TX-GATE VERLETZT" in capsys.readouterr().out


def test_verify_allows_tx_enabled_when_spec_enables_it(monkeypatch):
    spec = {**SPEC, "lora": {**SPEC["lora"], "tx_enabled": True}}
    _fake_node({"region": "EU_868", "modem_preset": "SHORT_SLOW", "tx_power": 24, "tx_enabled": True}, _chans_ok(), monkeypatch)
    assert node_config.cmd_verify(object(), spec) == 0


def test_verify_requires_disabled_channel_to_be_off():
    spec = {"channels": [{"index": 2, "role": "DISABLED", "name": "", "psk": "default"}]}
    current = [{"index": 2, "role": "SECONDARY", "name": "HessenTest", "psk_fp": "abcd1234"}]
    assert node_config.channel_mismatches(current, spec)


def test_verify_node_spec_retries_then_succeeds(tmp_path: Path):
    r = run_wizard_lib(
        """
        DRY_RUN=0 VERIFY_SLEEP=0 VERIFY_ATTEMPTS=4
        n=0
        node_cfg() { n=$((n + 1)); [[ $n -ge 3 ]] && return 0 || return 11; }
        verify_node_spec spec.json
        echo "attempts=$n"
        """,
        tmp_path,
    )
    assert r.returncode == 0, r.stderr
    assert "attempts=3" in r.stdout


def test_verify_node_spec_stops_meshtasticd_on_tx_violation(tmp_path: Path):
    r = run_wizard_lib(
        """
        DRY_RUN=0 VERIFY_SLEEP=0 VERIFY_ATTEMPTS=2
        node_cfg() { return 12; }
        systemctl() { echo "systemctl $*" >> "$T/calls"; }
        verify_node_spec spec.json
        """,
        tmp_path,
    )
    assert r.returncode != 0
    assert "TX ist auf der Node AKTIV" in r.stderr
    assert (tmp_path / "calls").read_text().strip() == "systemctl stop meshtasticd"


def test_configure_node_reapplies_when_firmware_forces_tx_on(tmp_path: Path):
    r = run_wizard_lib(
        """
        DRY_RUN=0 SKIP_NODE_CONFIG=0 VERIFY_SLEEP=0 VERIFY_ATTEMPTS=3 ANTENNA_OK=0
        applies=0; verifies=0
        mktemp() { command mktemp "$T/spec.XXXXXX"; }
        write_node_spec() { echo '{}' > "$1"; }
        cleanup_register() { :; }
        wait_for_port_cycle() { return 0; }
        node_cfg() {
            case "$1" in
                inspect) return 0 ;;
                apply) applies=$((applies + 1)); return 0 ;;
                verify) verifies=$((verifies + 1)); [[ $applies -ge 2 ]] && return 0 || return 12 ;;
            esac
        }
        configure_node
        echo "applies=$applies"
        """,
        tmp_path,
    )
    assert r.returncode == 0, r.stderr
    assert "applies=2" in r.stdout
    assert "zweiter Durchlauf" in r.stderr


def test_selftest_info_check_fails_on_open_tx_gate(tmp_path: Path):
    bad = run_wizard_lib(
        """
        ANTENNA_OK=0
        check_node_info $'region=EU_868\\ntx_enabled=true'
        echo "fails=$VERIFY_FAILS"
        """,
        tmp_path,
    )
    assert bad.returncode == 0, bad.stderr
    assert "fails=1" in bad.stdout and "TX-GATE" in bad.stderr

    good = run_wizard_lib(
        """
        ANTENNA_OK=0
        check_node_info $'region=EU_868\\ntx_enabled=false'
        echo "fails=$VERIFY_FAILS"
        """,
        tmp_path,
    )
    assert "fails=0" in good.stdout


# --- I3: existing node identity before the gate ---------------------------------------------------


def _node_state(tmp_path: Path) -> Path:
    d = tmp_path / "meshtasticd" / ".portduino" / "default" / "prefs"
    d.mkdir(parents=True)
    (d / "config.proto").write_bytes(b"\x0a\x02ab")
    return tmp_path / "meshtasticd"


def test_existing_prefs_block_start_without_antenna_or_ack(tmp_path: Path):
    state_dir = _node_state(tmp_path)
    env = {"MESHTASTICD_STATE_DIRS": str(state_dir)}
    blocked = run_wizard_lib("DRY_RUN=0 ANTENNA_OK=0 EXISTING_NODE_ACK=\nguard_existing_node", tmp_path, **env)
    assert blocked.returncode != 0
    assert "nicht gestartet" in blocked.stderr
    acked = run_wizard_lib("DRY_RUN=0 ANTENNA_OK=0 EXISTING_NODE_ACK=1\nguard_existing_node", tmp_path, **env)
    assert acked.returncode == 0, acked.stderr
    antenna = run_wizard_lib("DRY_RUN=0 ANTENNA_OK=1\nguard_existing_node", tmp_path, **env)
    assert antenna.returncode == 0, antenna.stderr


def test_question_aborts_non_interactively_when_prefs_exist(tmp_path: Path):
    state_dir = _node_state(tmp_path)
    r = run_wizard_lib("DRY_RUN=0 ASSUME_YES=1 ANTENNA_OK=0 EXISTING_NODE_ACK=\nask_existing_node", tmp_path, MESHTASTICD_STATE_DIRS=str(state_dir))
    assert r.returncode != 0
    fresh = run_wizard_lib("DRY_RUN=0 ASSUME_YES=1 ANTENNA_OK=0\nask_existing_node", tmp_path, MESHTASTICD_STATE_DIRS=str(tmp_path / "none"))
    assert fresh.returncode == 0, fresh.stderr


def test_reuse_with_existing_prefs_and_no_antenna_asks_instead_of_dying_later(tmp_path: Path):
    state_dir = _node_state(tmp_path)
    write_state(tmp_path, **{**SAVED, "ANTENNA_OK": "0", "TX_POWER": "24", "TX_WINDOW_ACK": "1"})
    env = {"MESHTASTICD_STATE_DIRS": str(state_dir)}
    script = """
        DRY_RUN=0 RESUME=0
        confirm() { echo "ASKED: $1" >&2; return @RC@; }
        resolve_answers
        guard_existing_node
        echo "REUSE=$REUSE ACK=$EXISTING_NODE_ACK"
        """
    yes = run_wizard_lib(script.replace("@RC@", "0"), tmp_path, **env)
    assert yes.returncode == 0, yes.stderr
    assert "meshtasticd trotzdem ohne bestaetigte Antenne" in yes.stderr
    assert "REUSE=1 ACK=1" in yes.stdout
    assert "EXISTING_NODE_ACK=1" in (tmp_path / "state" / "state.env").read_text()

    write_state(tmp_path, **{**SAVED, "ANTENNA_OK": "0", "TX_WINDOW_ACK": "1"})
    no = run_wizard_lib(script.replace("@RC@", "1"), tmp_path, **env)
    assert no.returncode != 0


def test_reuse_skips_prompts_when_gate_was_verified_before_and_on_resume(tmp_path: Path):
    state_dir = _node_state(tmp_path)
    env = {"MESHTASTICD_STATE_DIRS": str(state_dir)}
    write_state(tmp_path, **{**SAVED, "ANTENNA_OK": "0", "NODE_GATE_VERIFIED": "1"})
    verified = run_wizard_lib(
        'DRY_RUN=0 RESUME=0\nconfirm() { [[ "$1" == Gespeicherte* ]]; }\nresolve_answers\nguard_existing_node\necho OK',
        tmp_path,
        **env,
    )
    assert verified.returncode == 0, verified.stderr
    assert "OK" in verified.stdout

    write_state(tmp_path, **{**SAVED, "ANTENNA_OK": "0", "EXISTING_NODE_ACK": "1", "TX_WINDOW_ACK": "1"})
    resume = run_wizard_lib(
        'DRY_RUN=0 RESUME=1\nconfirm() { echo "confirm must not be called"; exit 9; }\nresolve_answers\nguard_existing_node\necho OK',
        tmp_path,
        **env,
    )
    assert resume.returncode == 0, resume.stderr


def test_tx_window_confirmation_required_without_antenna(tmp_path: Path):
    blocked = run_wizard_lib("DRY_RUN=0 ASSUME_YES=1 ANTENNA_OK=0 TX_WINDOW_ACK=\nask_tx_window", tmp_path)
    assert blocked.returncode != 0
    assert "TX" in blocked.stderr and "accept-tx-window" in blocked.stderr
    for setup in ("TX_WINDOW_ACK=1", "NODE_GATE_VERIFIED=1", "ANTENNA_OK=1", "DRY_RUN=1", "SKIP_NODE_CONFIG=1"):
        ok = run_wizard_lib(f"DRY_RUN=0 ASSUME_YES=1 ANTENNA_OK=0 TX_WINDOW_ACK=\n{setup}\nask_tx_window", tmp_path)
        assert ok.returncode == 0, (setup, ok.stderr)


def test_accept_tx_window_flag_sets_both_acks(tmp_path: Path):
    r = run_wizard_lib('parse_args --accept-tx-window\necho "$TX_WINDOW_ACK$EXISTING_NODE_ACK"', tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "11"


def test_node_spec_limits_tx_power_until_antenna_confirmed(tmp_path: Path):
    script = """
        load_channel_defs
        ANTENNA_OK=@A@ TX_POWER=24 RADIO_REGION=EU_868 MODEM_PRESET=SHORT_SLOW HESSENTEST=off LONG_NAME=""
        write_node_spec "$T/spec.json"
        cat "$T/spec.json"
        """
    import json

    off = run_wizard_lib(script.replace("@A@", "0"), tmp_path)
    assert off.returncode == 0, off.stderr
    lora_off = json.loads(off.stdout)["lora"]
    assert lora_off["tx_power"] == 1 and lora_off["tx_enabled"] is False
    on = run_wizard_lib(script.replace("@A@", "1"), tmp_path)
    lora_on = json.loads(on.stdout)["lora"]
    assert lora_on["tx_power"] == 24 and lora_on["tx_enabled"] is True


def test_node_spec_disables_hessentest_only_if_it_carries_our_name(tmp_path: Path):
    import json

    r = run_wizard_lib(
        """
        load_channel_defs
        ANTENNA_OK=0 RADIO_REGION=EU_868 MODEM_PRESET=SHORT_SLOW HESSENTEST=off LONG_NAME=""
        write_node_spec "$T/spec.json"
        cat "$T/spec.json"
        """,
        tmp_path,
    )
    assert r.returncode == 0, r.stderr
    channels = {c["index"]: c for c in json.loads(r.stdout)["channels"]}
    assert channels[2]["role"] == "DISABLED" and channels[2]["only_if_name"] == "HessenTest"
    assert channels[1]["role"] == "SECONDARY"


def test_disabled_entry_with_only_if_name_matches_just_that_channel():
    spec = {"channels": [{"index": 2, "role": "DISABLED", "name": "", "psk": "default", "only_if_name": "HessenTest"}]}
    ours = [{"index": 2, "role": "SECONDARY", "name": "HessenTest", "psk_fp": "abcd1234"}]
    foreign = [{"index": 2, "role": "SECONDARY", "name": "Familie", "psk_fp": "abcd1234"}]
    gone = [{"index": 2, "role": "DISABLED", "name": "", "psk_fp": "-"}]
    assert node_config.channel_mismatches(ours, spec)
    assert not node_config.channel_mismatches(foreign, spec)
    assert not node_config.channel_mismatches(gone, spec)
    assert node_config._disable_applies(ours[0], spec["channels"][0])
    assert not node_config._disable_applies(foreign[0], spec["channels"][0])
    node_config.validate_spec(spec)


# --- I5: resume unit / status -----------------------------------------------------------------------


def test_resume_unit_waits_for_time_sync_and_is_bounded(tmp_path: Path):
    r = run_wizard_lib("render_resume_unit /opt/Hessenbot/script/install/wizard.sh", tmp_path)
    assert r.returncode == 0, r.stderr
    unit = r.stdout
    assert "time-sync.target" in unit
    assert unit.count("ConditionPathExists=") == 2 and "resume.pending" in unit
    assert "--resume --yes --non-interactive --no-reboot" in unit


def test_failure_during_resume_leaves_login_status(tmp_path: Path):
    r = run_wizard_lib(
        """
        DRY_RUN=0 RESUME=1 CURRENT_PHASE=phase-b
        ( die "apt kaputt" ) || true
        """,
        tmp_path,
    )
    assert r.returncode == 0, r.stderr
    status = (tmp_path / "motd").read_text()
    assert "FEHLGESCHLAGEN" in status and "phase-b" in status and "journalctl" in status


def test_failed_resume_does_not_retry_on_every_boot(tmp_path: Path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "resume.pending").write_text("pending\n")
    r = run_wizard_lib('DRY_RUN=0 RESUME=1 CURRENT_PHASE=phase-b\n( die "kaputt" ) || true', tmp_path)
    assert r.returncode == 0, r.stderr
    assert not (tmp_path / "state" / "resume.pending").exists()


def test_no_status_file_for_interactive_failure(tmp_path: Path):
    run_wizard_lib('DRY_RUN=0 RESUME=0\n( die "x" ) || true', tmp_path)
    assert not (tmp_path / "motd").exists()


def test_resume_does_not_ask_for_hardware_or_pi_confirmation(tmp_path: Path):
    r = run_wizard_lib(
        """
        DRY_RUN=0 RESUME=1 ASSUME_YES=1 HAT_PRODUCT=""
        detect_hardware
        """,
        tmp_path,
    )
    assert r.returncode == 0, r.stderr


# --- I7: hardware default ---------------------------------------------------------------------------


def test_hardware_not_assumed_without_eeprom_when_unattended(tmp_path: Path):
    blocked = run_wizard_lib('DRY_RUN=0 ASSUME_YES=1 HAT_PRODUCT=""\ndetect_hardware', tmp_path)
    assert blocked.returncode != 0
    assert "--confirm-hardware" in blocked.stderr
    ok = run_wizard_lib('DRY_RUN=0 ASSUME_YES=1 HW_ACK=1 HAT_PRODUCT=""\ndetect_hardware', tmp_path)
    assert ok.returncode == 0, ok.stderr


def test_hardware_question_defaults_to_no(tmp_path: Path):
    r = run_wizard_lib(
        """
        DRY_RUN=0 HAT_PRODUCT=""
        confirm() { echo "default=$2"; [[ "$2" == "y" ]]; }
        detect_hardware
        """,
        tmp_path,
    )
    assert "default=n" in r.stdout
    assert r.returncode != 0


# --- I6: GPS not offered ------------------------------------------------------------------------------


def test_gps_on_is_rejected_and_never_asked(tmp_path: Path):
    r = subprocess.run(
        ["bash", str(HERE / "wizard.sh"), "--dry-run", "--yes", "--non-interactive", "--gps", "on"],
        capture_output=True,
        text=True,
        env={**os.environ, "TMPDIR": str(tmp_path)},
        check=False,
    )
    assert r.returncode != 0
    assert "GPS" in r.stderr
    ask = run_wizard_lib("HAS_GPS=1\nask_gps\necho $HAS_GPS", tmp_path)
    assert ask.stdout.strip() == "0"


# --- N8 / N9: config.ini and bot channels ----------------------------------------------------------------


def test_hessentest_off_on_rerun_ignores_channel_two_again():
    ini = "[general]\ndefaultChannel = 0\nignoreDefaultChannel = True\nignoreChannels = 3,4\nmessagesChannel = 1\n"
    changes = dict(bot_channels.plan_changes(ini, [1], [0, 1, 2]))
    assert changes == {"ignoreChannels": "2,3,4"}


def test_defined_channel_indices_include_disabled_hessentest(tmp_path: Path):
    r = run_wizard_lib(
        f"""
        CHANNELS_DIR={HERE}/channels.d
        load_channel_defs
        HESSENTEST=off
        defined_channel_indices
        enabled_channel_indices
        """,
        tmp_path,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["0,1,2", "0,1"]


def test_web_admin_host_only_set_when_admin_enabled(tmp_path: Path):
    off = run_wizard_lib('WEB_ADMIN=0 WEB_BIND=0.0.0.0 LAT=1 LON=2\nconfig_ini_assignments', tmp_path)
    assert "webAdmin.enabled=False" in off.stdout and "webAdmin.host" not in off.stdout
    on = run_wizard_lib('WEB_ADMIN=1 WEB_BIND=127.0.0.1 LAT=1 LON=2\nconfig_ini_assignments', tmp_path)
    assert "webAdmin.enabled=True" in on.stdout and "webAdmin.host=127.0.0.1" in on.stdout


# --- revert ----------------------------------------------------------------------------------------------


def test_revert_restores_modified_moved_and_removes_created(tmp_path: Path):
    orig = tmp_path / "boot-config.txt"
    orig.write_text("original\n", encoding="utf-8")
    backup = tmp_path / "boot-config.txt.hessenbot-1"
    backup.write_text("original\n", encoding="utf-8")
    orig.write_text("original\n# hessenbot block\n", encoding="utf-8")
    created = tmp_path / "created.conf"
    created.write_text("x", encoding="utf-8")
    link = tmp_path / "link.yaml"
    link.symlink_to(created)
    moved_dest = tmp_path / "bak" / "lora-old.yaml"
    moved_dest.parent.mkdir()
    moved_dest.write_text("old", encoding="utf-8")
    moved_src = tmp_path / "config.d" / "lora-old.yaml"
    moved_src.parent.mkdir()

    state = tmp_path / "state"
    state.mkdir()
    manifest = state / "manifest"
    manifest.write_text(
        f"MODIFIED\t{orig}\t{backup}\nCREATED\t{created}\nSYMLINK\t{link}\nMOVED\t{moved_src}\t{moved_dest}\nAPT\tmeshtasticd\n",
        encoding="utf-8",
    )
    r = run_wizard_lib("DRY_RUN=0 ASSUME_YES=1\nrevert_install", tmp_path)
    assert r.returncode == 0, r.stderr
    assert orig.read_text() == "original\n"
    assert not created.exists()
    assert not link.is_symlink()
    assert moved_src.read_text() == "old"
    assert not manifest.exists()
    assert list(state.glob("manifest.reverted-*"))


def test_revert_dry_run_changes_nothing(tmp_path: Path):
    created = tmp_path / "created.conf"
    created.write_text("x", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    (state / "manifest").write_text(f"CREATED\t{created}\n", encoding="utf-8")
    r = run_wizard_lib("DRY_RUN=1\nrevert_install", tmp_path)
    assert r.returncode == 0, r.stderr
    assert created.exists() and (state / "manifest").exists()


def test_revert_without_yes_and_no_terminal_aborts(tmp_path: Path):
    created = tmp_path / "created.conf"
    created.write_text("x", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    (state / "manifest").write_text(f"CREATED\t{created}\n", encoding="utf-8")
    r = run_wizard_lib("DRY_RUN=0 NONINTERACTIVE=1\nrevert_install", tmp_path)
    assert r.returncode != 0
    assert created.exists()


# --- misc -------------------------------------------------------------------------------------------------


def test_dry_run_log_uses_unique_temp_file(tmp_path: Path):
    r = subprocess.run(
        ["bash", "-c", f'source "{LIB}/common.sh"; DRY_RUN=1 HB_LOG_FILE=/nonexistent/x; log_init; echo "$HB_LOG_FILE"'],
        capture_output=True,
        text=True,
        env={**os.environ, "TMPDIR": str(tmp_path)},
        check=False,
    )
    assert r.returncode == 0, r.stderr
    path = Path(r.stdout.strip())
    assert path.parent == tmp_path and path.name != "hessenbot-install-dry-run.log"


def test_mac_source_follows_existing_ethernet_interface(tmp_path: Path):
    def pick(*names: str) -> str:
        net = tmp_path / ("net-" + "-".join(names or ("none",)))
        net.mkdir()
        for n in names:
            (net / n).mkdir()
        r = run_wizard_lib("mac_source_iface", tmp_path, HB_NET_DIR=str(net))
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()

    assert pick("end0", "eth0") == "end0"
    assert pick("eth0") == "eth0"
    assert pick() == "end0"


# --- SMLunchen RAK6421 + RAK13302 LoRa config (1:1) ---------------------------------------------------

RADIO_YAML = HERE / "radios.d" / "lora-hat-rak-6421-pi-hat.yaml"


def _yaml_keys(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "Lora:":
            continue
        key, _, value = stripped.partition(":")
        out[key.strip()] = value.strip()
    return out


def test_shipped_radio_config_matches_smlunchen_pins_and_omits_breaking_keys():
    keys = _yaml_keys(RADIO_YAML.read_text(encoding="utf-8"))
    assert keys == {
        "Module": "sx1262",
        "CS": "8",
        "IRQ": "22",
        "Reset": "16",
        "Busy": "24",
        "DIO3_TCXO_VOLTAGE": "true",
        "DIO2_AS_RF_SWITCH": "true",
        "spidev": "spidev0.0",
    }
    for forbidden in ("Enable_Pins", "SX126X_ANT_SW", "SX126X_MAX_POWER"):
        assert forbidden not in keys


def test_radio_profile_uses_hat_autoconf_name_not_stock_slot1_preset(tmp_path: Path):
    r = run_wizard_lib('echo "$RADIO_PRESET_FILE"', tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "lora-hat-rak-6421-pi-hat.yaml"
    assert (HERE / "radios.d" / r.stdout.strip()).is_file()


def test_radio_config_is_written_to_available_d_and_linked_replacing_stock_preset(tmp_path: Path):
    etc = tmp_path / "etc"
    (etc / "config.d").mkdir(parents=True)
    (etc / "available.d").mkdir()
    stock = etc / "available.d" / "lora-RAK6421-13302-slot1.yaml"
    stock.write_text("Lora:\n#  CS: 8\n", encoding="utf-8")
    (etc / "config.d" / stock.name).symlink_to(stock)
    r = run_wizard_lib(
        """
        DRY_RUN=0
        confirm() { return 0; }
        install_radio_config
        link_radio_preset
        """,
        tmp_path,
        MESHTASTICD_ETC=str(etc),
    )
    assert r.returncode == 0, r.stderr
    name = "lora-hat-rak-6421-pi-hat.yaml"
    assert (etc / "available.d" / name).read_text() == RADIO_YAML.read_text()
    link = etc / "config.d" / name
    assert link.is_symlink() and link.resolve() == (etc / "available.d" / name).resolve()
    assert not (etc / "config.d" / stock.name).exists(), "stock preset must not stay active next to ours"
    assert stock.read_text() == "Lora:\n#  CS: 8\n"


def test_radio_config_dry_run_writes_nothing(tmp_path: Path):
    etc = tmp_path / "etc"
    etc.mkdir()
    r = run_wizard_lib("DRY_RUN=1\ninstall_radio_config\nlink_radio_preset", tmp_path, MESHTASTICD_ETC=str(etc))
    assert r.returncode == 0, r.stderr
    assert not any(etc.rglob("*.yaml"))


@pytest.mark.parametrize(
    "journal, ok, fails, needle",
    [
        ("SX126x init result 0\nsx1262 init success", True, 0, "init result 0"),
        ("SX126x init result -2", False, 1, "CS: 8"),
        ("old\nSX126x init result -13", False, 1, "SX126X_MAX_POWER"),
        ("nothing here", True, 0, "Kein 'SX126x init result'"),
    ],
)
def test_check_lora_init_reads_init_result(tmp_path: Path, journal: str, ok: bool, fails: int, needle: str):
    r = run_wizard_lib(
        f"""
        RADIO_PRESET_FILE=lora-hat-rak-6421-pi-hat.yaml
        check_lora_init $'{journal}'
        echo "fails=$VERIFY_FAILS"
        """,
        tmp_path,
    )
    assert r.returncode == 0, r.stderr
    assert f"fails={fails}" in r.stdout
    assert needle in r.stderr
