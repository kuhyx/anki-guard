#!/bin/bash
# ============================================================================
# install.sh -- install anki-guard and its sync server for real use.
#
# Installs into the SYSTEM python's user site-packages (what the units run),
# generates the sync account once (0600, never overwritten), installs and
# starts the user units, publishes the server through the host Caddy edge at
# https://anki.kuhy.duckdns.org/, then verifies both ends answer. Idempotent.
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
# Only Caddy (host network) talks to the server; the phone reaches it over
# HTTPS from any network, so no firewall port is opened for it.
readonly SYNC_HOST="127.0.0.1"
readonly PUBLIC_HOST="anki.kuhy.duckdns.org"
readonly PHONE_SYNC_URL="https://${PUBLIC_HOST}/"
readonly CADDY_SITES="${HOME}/services/gitea/sites"
readonly CADDY_SITE="${CADDY_SITES}/anki.caddy"
readonly CADDY_CONTAINER="gitea-caddy"
readonly CADDYFILE_IN_CONTAINER="/etc/caddy/Caddyfile"
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
    "$SYSTEM_PYTHON" -c 'import anki_guard, earned_time, freedays' || fail "imports"
    [[ -r "$HMAC_KEY" ]] || fail "$HMAC_KEY unreadable -- the ledger cannot be signed"
}

set_env_value() {
    # Replace or append KEY=VALUE in the 0600 env file; SYNC_USER1 is never
    # read or printed here, so the password stays where it is.
    local key="$1" value="$2" tmp
    tmp="$(mktemp "${ENV_FILE}.XXXXXX")"
    grep -v "^${key}=" "$ENV_FILE" > "$tmp" || true
    printf '%s=%s\n' "$key" "$value" >> "$tmp"
    chmod 600 "$tmp"
    mv "$tmp" "$ENV_FILE"
}

write_env() {
    mkdir -p "$CONFIG_DIR" "$DATA_DIR"
    if [[ -f "$ENV_FILE" ]]; then
        log "keeping the existing sync account in $ENV_FILE"
    else
        log "generating the sync account in $ENV_FILE"
        (
            umask 077
            printf 'SYNC_USER1=%s:%s\n' "$SYNC_USER" "$(openssl rand -hex 16)" > "$ENV_FILE"
        )
    fi
    # Also migrates the pre-Caddy file, which bound the LAN address.
    set_env_value SYNC_HOST "$SYNC_HOST"
    set_env_value PHONE_SYNC_URL "$PHONE_SYNC_URL"
}

install_units() {
    log "installing systemd user units into $UNIT_DIR"
    mkdir -p "$UNIT_DIR"
    local unit
    for unit in "${UNITS[@]}"; do
        install -m 644 "$REPO_DIR/$unit" "$UNIT_DIR/"
    done
    systemctl --user daemon-reload
    # The guard is retired (earned_time TUTOR_FROM): only the sync server runs,
    # so the decks stay reachable from the phone, unenforced.
    systemctl --user enable --now anki-syncserver.service
    if systemctl --user is-enabled --quiet anki-guard.timer; then
        log "anki-guard is retired; disabling its timer"
        systemctl --user disable --now anki-guard.timer
    fi
    systemctl --user restart anki-syncserver.service
}

publish_site() {
    command -v docker >/dev/null || fail "docker is required to reload Caddy"
    [[ -d "$CADDY_SITES" ]] || fail "no Caddy site directory at $CADDY_SITES"
    log "publishing ${PUBLIC_HOST} through ${CADDY_CONTAINER}"
    printf '%s\n' \
        "# Managed by anki-guard/install.sh -- do not edit by hand." \
        "${PUBLIC_HOST} {" \
        "	reverse_proxy ${SYNC_HOST}:${SYNC_PORT}" \
        "}" > "$CADDY_SITE"
    # This edge serves every other site too: a snippet that fails validation
    # would take them all down at the next container restart, so it goes.
    if ! docker exec "$CADDY_CONTAINER" caddy validate \
        --config "$CADDYFILE_IN_CONTAINER" >/dev/null 2>&1; then
        rm -f "$CADDY_SITE"
        fail "Caddy rejected $CADDY_SITE -- removed it, nothing reloaded"
    fi
    docker exec "$CADDY_CONTAINER" caddy reload --config "$CADDYFILE_IN_CONTAINER" \
        || fail "caddy reload -- docker logs $CADDY_CONTAINER"
}

wait_for() {
    # wait_for URL TRIES: poll URL every half second until it answers.
    local url="$1" tries="$2" i
    for ((i = 0; i < tries; i++)); do
        curl -fsS -o /dev/null "$url" 2>/dev/null && return 0
        sleep 0.5
    done
    return 1
}

verify_server() {
    log "waiting for the sync server on ${SYNC_HOST}:${SYNC_PORT}"
    wait_for "http://${SYNC_HOST}:${SYNC_PORT}/health" 20 \
        || fail "sync server not listening -- journalctl --user -u anki-syncserver"
    # The first Let's Encrypt certificate can take a minute to issue.
    log "waiting for ${PHONE_SYNC_URL}health"
    wait_for "${PHONE_SYNC_URL}health" 180 \
        || fail "${PHONE_SYNC_URL} does not answer -- docker logs $CADDY_CONTAINER 2>&1 | tail"
    log "phone sync URL: ${PHONE_SYNC_URL}"
}

main() {
    install_anki
    install_package
    write_env
    install_units
    publish_site
    verify_server
    log "done -- phone: scripts/setup_phone.sh ; status: python3 -m anki_guard status"
}

main "$@"
