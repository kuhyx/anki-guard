#!/bin/bash
# ============================================================================
# install.sh -- install anki-guard and its sync server for real use.
#
# Installs into the SYSTEM python's user site-packages (what the units run),
# generates the sync account once (0600, never overwritten), installs and
# starts the user units, then verifies the server answers. Idempotent.
# ============================================================================

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_DIR
readonly SYSTEM_PYTHON="/usr/bin/python3"
readonly UNIT_DIR="${HOME}/.config/systemd/user"
readonly CONFIG_DIR="${HOME}/.config/anki_guard"
readonly ENV_FILE="${CONFIG_DIR}/syncserver.env"
readonly DATA_DIR="${HOME}/.local/share/anki_guard"
readonly HMAC_KEY="/etc/workout-locker/hmac.key"
readonly SYNC_USER="kuhy"
readonly SYNC_PORT=8780
readonly UNITS=(anki-syncserver.service anki-guard.service anki-guard.timer)

log() { printf 'install: %s\n' "$1" >&2; }
fail() { printf 'install: FAILED -- %s\n' "$1" >&2; exit 1; }

install_anki() {
    # The sync server is the system anki package; anki-git is an AUR build,
    # so a missing one is the user's `yay` to run, not something to guess at.
    "$SYSTEM_PYTHON" -c 'import anki.syncserver' 2>/dev/null \
        || fail "no anki python package: run  ! yay -S anki-git"
}

install_package() {
    log "installing into the system python's user site-packages"
    "$SYSTEM_PYTHON" -m pip install --user --break-system-packages -q -e "$REPO_DIR" \
        || fail "pip install"
    "$SYSTEM_PYTHON" -c 'import anki_guard, earned_time' || fail "imports"
    [[ -r "$HMAC_KEY" ]] || fail "$HMAC_KEY unreadable -- the ledger cannot be signed"
}

lan_address() {
    # The source address of the default route: the NIC the phone reaches.
    local route
    route="$(ip -4 route get 1.1.1.1)"
    [[ $route =~ src\ ([0-9.]+) ]] || fail "no default-route IPv4 address"
    printf '%s' "${BASH_REMATCH[1]}"
}

write_env() {
    mkdir -p "$CONFIG_DIR" "$DATA_DIR"
    if [[ -f "$ENV_FILE" ]]; then
        log "keeping the existing sync account in $ENV_FILE"
        return
    fi
    log "generating the sync account in $ENV_FILE"
    (
        umask 077
        printf 'SYNC_USER1=%s:%s\nSYNC_HOST=%s\n' \
            "$SYNC_USER" "$(openssl rand -hex 16)" "$(lan_address)" > "$ENV_FILE"
    )
}

install_units() {
    log "installing systemd user units into $UNIT_DIR"
    mkdir -p "$UNIT_DIR"
    local unit
    for unit in "${UNITS[@]}"; do
        install -m 644 "$REPO_DIR/$unit" "$UNIT_DIR/"
    done
    systemctl --user daemon-reload
    systemctl --user enable --now anki-syncserver.service anki-guard.timer
    systemctl --user restart anki-syncserver.service
}

verify_server() {
    local host
    host="$(sed -n 's/^SYNC_HOST=//p' "$ENV_FILE")"
    log "waiting for the sync server on ${host}:${SYNC_PORT}"
    local _
    for _ in {1..20}; do
        if curl -fsS -o /dev/null "http://${host}:${SYNC_PORT}/health" 2>/dev/null; then
            log "listening on http://${host}:${SYNC_PORT}/"
            return
        fi
        sleep 0.5
    done
    fail "sync server not listening -- journalctl --user -u anki-syncserver"
}

main() {
    install_anki
    install_package
    write_env
    install_units
    verify_server
    log "done -- phone: scripts/setup_phone.sh ; status: python3 -m anki_guard status"
}

main "$@"
