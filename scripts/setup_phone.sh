#!/bin/bash
# ============================================================================
# setup_phone.sh -- point AnkiDroid on the phone at the PC's sync server.
#
# The one irreducible part is tapping through AnkiDroid's settings (the phone
# is not rooted, so its prefs cannot be written). Everything around it is
# scripted: the local-network grants, launching the app, TYPING each value
# into the field you focused (adb input text -- no reading, no retyping), and
# verifying afterwards that a sync from the phone actually reached the server.
#
# Usage:
#   scripts/setup_phone.sh                # grants + guided entry + verify
#   scripts/setup_phone.sh --verify-only  # just the checks, rerunnable
# ============================================================================

set -euo pipefail

readonly ENV_FILE="${HOME}/.config/anki_guard/syncserver.env"
readonly SYNC_PORT=8780
readonly ANKIDROID="com.ichi2.anki"
readonly RETHINK="com.celzero.bravedns"
readonly LOCAL_NET="android.permission.ACCESS_LOCAL_NETWORK"
VERIFY_ONLY=0

log() { printf 'setup_phone: %s\n' "$1" >&2; }
fail() { printf 'setup_phone: FAILED -- %s\n' "$1" >&2; exit 1; }

env_value() {
    sed -n "s/^$1=//p" "$ENV_FILE"
}

load_account() {
    [[ -r "$ENV_FILE" ]] || fail "no $ENV_FILE -- run ./install.sh first"
    local account
    account="$(env_value SYNC_USER1)"
    SYNC_USER="${account%%:*}"
    SYNC_PASS="${account#*:}"
    SYNC_URL="http://$(env_value SYNC_HOST):${SYNC_PORT}/"
    readonly SYNC_USER SYNC_PASS SYNC_URL
}

phone_connected() {
    adb get-state >/dev/null 2>&1
}

grant_local_network() {
    # Android 17 gates every LAN socket behind ACCESS_LOCAL_NETWORK, and
    # Rethink dials on the app's behalf, so BOTH need it (2026-09-27).
    local pkg
    for pkg in "$ANKIDROID" "$RETHINK"; do
        if adb shell pm grant "$pkg" "$LOCAL_NET" 2>/dev/null; then
            log "granted local-network access to $pkg"
        else
            log "WARNING: could not grant $LOCAL_NET to $pkg (not declared, or not installed)"
        fi
    done
}

type_into_phone() {
    # $1 = label, $2 = value. The user focuses the field; Enter types it.
    local label="$1" value="$2"
    read -r -p "Tap the ${label} field on the phone, then press Enter here... " _
    adb shell input text "'${value}'"
    log "typed the ${label}"
}

guided_entry() {
    adb shell monkey -p "$ANKIDROID" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 \
        || log "WARNING: could not launch AnkiDroid"
    cat >&2 <<EOT

In AnkiDroid: Settings -> Sync -> Custom sync server.
  Turn it on, open "Sync url".
EOT
    type_into_phone "sync url" "$SYNC_URL"
    cat >&2 <<EOT
Save it, go back, then tap the sync icon. At the login form:
EOT
    type_into_phone "username" "$SYNC_USER"
    type_into_phone "password" "$SYNC_PASS"
    cat >&2 <<EOT
Log in. If AnkiDroid asks which side to keep, choose the answer agreed
with Claude (the phone UPLOADS: it holds the collection you study in).
Press Enter here once the sync has finished.
EOT
    read -r _
}

verify() {
    local failed=0
    if curl -fsS -o /dev/null "${SYNC_URL}health"; then
        log "PASS server answers on ${SYNC_URL}"
    else
        log "FAIL server does not answer on ${SYNC_URL}"; failed=1
    fi
    if journalctl --user -u anki-syncserver --since today --no-pager \
        | grep -qi 'client=.*android'; then
        log "PASS a sync from AnkiDroid reached the server today"
    else
        log "FAIL no AnkiDroid sync in today's server log"; failed=1
    fi
    if python3 -m anki_guard status; then
        log "PASS anki-guard reads the server's collection"
    else
        log "FAIL anki-guard cannot read the collection"; failed=1
    fi
    return "$failed"
}

main() {
    load_account
    if [[ $VERIFY_ONLY -eq 0 ]]; then
        # The guided entry waits for Enter between fields; a `!` command from
        # Claude Code has no terminal, and read would hit EOF and exit mid-way.
        [[ -t 0 ]] || fail "needs an interactive terminal (run it in a real shell, not via '!')"
        phone_connected || fail "no phone on adb (plug it in, accept USB debugging)"
        grant_local_network
        guided_entry
    fi
    verify || fail "see the FAIL lines above; rerun with --verify-only after fixing"
    log "done"
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --verify-only) VERIFY_ONLY=1; shift ;;
        -h|--help) sed -n '3,14p' "$0"; exit 0 ;;
        *) fail "unknown option: $1" ;;
    esac
done

main
