#!/usr/bin/env bash
# Hessenbot installer: roll back changes recorded in the manifest (wizard.sh --revert).
# shellcheck shell=bash disable=SC2034,SC2015,SC2153

revert_install() {
    CURRENT_PHASE="revert"
    step "Rueckbau anhand des Manifests"
    [[ -f "$HB_MANIFEST" ]] || die "Kein Manifest unter $HB_MANIFEST (nichts zurueckzubauen)."

    local entries=() line
    mapfile -t entries < <(tac "$HB_MANIFEST")
    log "Folgende Schritte werden rueckgaengig gemacht (neueste zuerst):"
    for line in "${entries[@]}"; do
        log "  $line"
    done
    log "Nicht entfernt werden: apt-Pakete (meshtasticd), /opt/Hessenbot, /var/lib/meshtasticd (Node-Identitaet) und Backups."
    if [[ "$DRY_RUN" != "1" && "$ASSUME_YES" != "1" ]] && ! confirm "Rueckbau jetzt durchfuehren?" n; then
        die "Abgebrochen."
    fi

    local kind a b dest
    dest="$HB_BACKUP_DIR/reverted-$TS"
    for line in "${entries[@]}"; do
        IFS=$'\t' read -r kind a b <<<"$line"
        case "$kind" in
            MODIFIED)
                if [[ -e "$b" || -L "$b" ]]; then
                    run cp -a "$b" "$a"
                else
                    warn "Backup $b fehlt; $a bleibt unveraendert."
                fi
                ;;
            CREATED)
                if [[ -e "$a" || -L "$a" ]]; then
                    run mkdir -p "$dest"
                    run mv "$a" "$dest/$(basename "$a").$(date +%s%N)"
                    log "  $a nach $dest verschoben"
                fi
                ;;
            MOVED)
                [[ -e "$b" ]] && run mv "$b" "$a"
                ;;
            SYMLINK)
                [[ -L "$a" ]] && run rm -f "$a"
                ;;
            UNIT)
                run systemctl disable --now "$a" || true
                ;;
            USER)
                if id "$a" >/dev/null 2>&1 && confirm "Benutzer '$a' entfernen?" n; then
                    run userdel "$a" || true
                fi
                ;;
            APT | BACKUP)
                log "  (informativ) $kind $a"
                ;;
            *)
                warn "Unbekannter Manifest-Eintrag: $line"
                ;;
        esac
    done
    run systemctl daemon-reload || true
    if [[ "$DRY_RUN" != "1" ]]; then
        mv "$HB_MANIFEST" "$HB_MANIFEST.reverted-$TS"
        rm -f "$HB_STATE_FILE"
    fi
    log "Rueckbau abgeschlossen. Ein Neustart ist noetig, falls config.txt zurueckgesetzt wurde."
}
