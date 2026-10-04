#!/bin/bash
# ============================================================================
# setup_phone.sh -- point AnkiDroid on the phone at the PC's sync server.
#
# Fully automatic, no taps: the phone is not rooted, so AnkiDroid's prefs are
# set through its own UI, driven over adb by scripts/phone_setup_auto.py (every
# tap targets a node found in a fresh uiautomator dump). It sets the custom
# sync URL, signs out of any other account, logs in with the account from
# syncserver.env and DOWNLOADS the server's collection -- it never uploads.
#
# Usage:
#   scripts/setup_phone.sh                # grants + automatic setup + verify
#   scripts/setup_phone.sh --verify-only  # just the checks, rerunnable
# ============================================================================

set -euo pipefail

readonly ENV_FILE="${HOME}/.config/anki_guard/syncserver.env"
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
    # The public HTTPS URL install.sh publishes: the same from any network.
    SYNC_URL="$(env_value PHONE_SYNC_URL)"
    [[ -n "$SYNC_URL" ]] || fail "no PHONE_SYNC_URL in $ENV_FILE -- rerun ./install.sh"
    readonly SYNC_USER SYNC_URL
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
    # A notification-permission prompt mid-sync would be a system window the
    # automatic flow refuses to touch; answer it up front.
    adb shell pm grant "$ANKIDROID" android.permission.POST_NOTIFICATIONS 2>/dev/null \
        || log "WARNING: could not grant POST_NOTIFICATIONS to $ANKIDROID"
}

auto_setup() {
    # The password stays inside the Python flow: read from the env file, typed
    # over adb's stdin, never echoed or put in an argv.
    python3 "$(dirname "$0")/phone_setup_auto.py" \
        || fail "automatic AnkiDroid setup stopped (reason above)"
}

verify() {
    local failed=0
    if curl -fsS -o /dev/null "${SYNC_URL}health"; then
        log "PASS server answers on ${SYNC_URL}"
    else
        log "FAIL server does not answer on ${SYNC_URL}"; failed=1
    fi
    # sed: the server's log lines carry ANSI colour codes even in the journal.
    # Read whole first: `grep -q` exiting early would SIGPIPE the producers,
    # and pipefail would turn a match into a failure.
    local journal
    journal="$(journalctl --user -u anki-syncserver --since today --no-pager \
        | sed 's/\x1b\[[0-9;]*m//g')"
    if grep -qiE "uid=\"${SYNC_USER}\" client=\"[^\"]*android" <<< "$journal"; then
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
        phone_connected || fail "no phone on adb (plug it in, accept USB debugging)"
        grant_local_network
        auto_setup
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
