#!/usr/bin/env python3
# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Point AnkiDroid at this PC's sync server and DOWNLOAD the collection.

Hands-free: Sync settings -> custom sync URL -> log out of any other account
-> log in with the account from ``syncserver.env`` -> "Sync now". UI strings
are AnkiDroid 2.24.1's own English + Polish translations.

The phone only ever downloads. An empty phone gets rslib's automatic full
download. The one dialog that asks for a direction is answered "keep the
server's" only if this run saw the empty-collection placeholder AND the
journal proves the phone talks to THIS server; anything else stops the run
with the screen's text. Exit 0 = the journal shows the phone's
``/sync/download`` and no ``/sync/upload``, and the deck list shows the decks.
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from phone_ui import Phone, Screen, StepError, run

LOG = logging.getLogger("phone_setup_auto")
ENV_FILE = Path.home() / ".config/anki_guard/syncserver.env"
PACKAGE = "com.ichi2.anki"
EXPECTED_DECKS = ("LeetCode", "Ultimate Geography")
SYNC_TIMEOUT_S = 600.0

DRAWER = frozenset({"Open drawer", "Otwórz menu boczne"})
EMPTY = frozenset({"Collection is empty", "Kolekcja jest pusta"})
SYNC_CAT = frozenset({"Sync", "Synchronizacja"})
ACCOUNT = frozenset({"AnkiWeb account", "Konto AnkiWeb"})
CUSTOM = frozenset({"Custom sync server", "Własny serwer synchronizacji"})
URL_ROW = frozenset({"Sync URL", "Adres URL synchronizacji"})
SAVE = frozenset({"Save", "Zapisz"})
LOGIN_OK = frozenset({"Login successful", "Zalogowano pomyślnie"})
SYNC = frozenset({"Sync", "Synchronizuj"})
CONFLICT = frozenset(
    {"Select collection to keep", "Wybierz kolekcję, którą chcesz zachować"},
)
KEEP_REMOTE = frozenset({"AnkiWeb"})
CONFIRM_REMOTE = frozenset(
    {
        "Replace your collection on AnkiDroid with your collection from AnkiWeb?",
        "Czy zastąpić twoją kolekcję AnkiDroid kolekcją z AnkiWeb?",
    },
)
REPLACE = frozenset({"Replace", "Zastąp"})
# The server's tracing output is coloured even in the journal.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_REQUEST = re.compile(r'uri="([^"]+)".*?uid="([^"]*)" client="([^"]*)"')
_JOURNAL = ["--user", "-u", "anki-syncserver", "--no-pager", "-o", "cat", "--since"]


def read_account() -> tuple[str, str, str]:
    """Return (sync URL, user, password) from the server's env file."""
    values: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    user, _, password = values["SYNC_USER1"].partition(":")
    return values["PHONE_SYNC_URL"], user, password


def phone_requests(since: str, user: str) -> list[tuple[str, str]]:
    """Return (uri, client) of each AnkiDroid request by ``user`` since ``since``."""
    journalctl = shutil.which("journalctl") or "/usr/bin/journalctl"
    out = _ANSI.sub("", run([journalctl, *_JOURNAL, since]).stdout)
    found = (m.groups() for m in _REQUEST.finditer(out))
    return [(u, c) for u, uid, c in found if uid == user and "android" in c.lower()]


def open_sync_settings(phone: Phone) -> bool:
    """Cold-start AnkiDroid, open Settings -> Sync; return "collection was empty"."""
    phone.shell("am", "start", "-S", "-W", "-n", f"{PACKAGE}/.IntentHandler")
    screen, drawer = phone.wait_for(lambda s: s.find(descs=DRAWER), "the deck list")
    empty = screen.find(texts=EMPTY) is not None
    LOG.info("deck list reached; collection empty: %s", empty)
    phone.tap(drawer)
    phone.tap(phone.wait_for(lambda s: s.find(rid="nav_settings"), "the drawer")[1])
    phone.tap(
        phone.wait_for(lambda s: s.find(rid="title", texts=SYNC_CAT), "Settings")[1]
    )
    phone.wait_for(lambda s: s.find(rid="title", texts=ACCOUNT), "Sync settings")
    return empty


def open_custom_server(phone: Phone) -> None:
    """Scroll Sync settings until the custom-server row is whole, then open it."""
    for _ in range(6):
        screen = phone.dump()
        row = screen.find(rid="title", texts=CUSTOM)
        if row is not None and screen.summary_of(CUSTOM) is not None:
            phone.tap(row)
            return
        phone.swipe_up()
    msg = "no 'Custom sync server' row in Sync settings"
    raise StepError(msg)


def set_sync_url(phone: Phone, url: str) -> None:
    """Make the custom sync URL exactly ``url``, then return to Sync settings."""
    open_custom_server(phone)
    screen, row = phone.wait_for(
        lambda s: s.find(rid="title", texts=URL_ROW), "the custom server page"
    )
    if screen.summary_of(URL_ROW) != url:
        phone.tap(row)
        _, field = phone.wait_for(lambda s: s.find(rid="edit"), "the URL dialog")
        phone.replace_text(field, url)
        typed = frozenset({url})
        _, save = phone.wait_for(
            lambda s: s.find(rid="edit", texts=typed) and s.find(texts=SAVE),
            "the URL field to read exactly the sync URL",
        )
        phone.tap(save)
        phone.wait_for(lambda s: s.find(rid="summary", texts=typed), "the saved URL")
    LOG.info("custom sync URL is %s", url)
    phone.key("KEYCODE_BACK")
    phone.wait_for(lambda s: s.find(rid="title", texts=ACCOUNT), "Sync settings")


def log_in(phone: Phone, user: str, password: str) -> None:
    """Log out of any other account, log in as ``user``, answer "Sync now"."""
    screen, row = phone.wait_for(
        lambda s: s.find(rid="title", texts=ACCOUNT), "Sync settings"
    )
    if screen.summary_of(ACCOUNT) == user:
        LOG.info("already logged in as %s; syncing from the deck list", user)
        phone.key("KEYCODE_BACK", "KEYCODE_BACK")
        phone.tap(phone.wait_for(lambda s: s.find(descs=SYNC), "the deck list")[1])
        return
    phone.tap(row)
    _, node = phone.wait_for(
        lambda s: s.find(rid="logout_button") or s.find(rid="username"),
        "the account page",
    )
    if node.rid == "logout_button":
        LOG.warning("signing out of the previous account (local sign-out only)")
        phone.tap(node)
    _, name = phone.wait_for(lambda s: s.find(rid="username"), "the login form")
    phone.replace_text(name, user)
    named = frozenset({user})
    _, secret = phone.wait_for(
        lambda s: s.find(rid="username", texts=named) and s.find(rid="password"),
        "the username field to read exactly the user",
    )
    phone.replace_text(secret, password)
    phone.hide_keyboard()
    phone.tap(phone.wait_for(lambda s: s.find(rid="login_button"), "Log in")[1])
    _, outcome = phone.wait_for(
        lambda s: s.find(texts=LOGIN_OK) or s.find(rid="snackbar_text"),
        "the login result",
        60,
    )
    if outcome.rid == "snackbar_text":
        msg = f"login failed: {outcome.text}"
        raise StepError(msg)
    phone.tap(phone.wait_for(lambda s: s.find(rid="button1", texts=SYNC), "'Sync?'")[1])
    LOG.info("logged in as %s; sync started", user)


def answer_conflict(phone: Phone, screen: Screen, *, safe: bool) -> None:
    """Keep the SERVER's collection, but only when the run proved it safe."""
    keep = screen.find(texts=KEEP_REMOTE)
    if not safe or keep is None:
        msg = f"conflict dialog, refusing to choose: {screen.describe()}"
        raise StepError(msg)
    LOG.warning("conflict dialog: keeping the SERVER's collection (download)")
    phone.tap(keep)
    _, confirm = phone.wait_for(
        lambda s: s.find(texts=CONFIRM_REMOTE) and s.find(texts=REPLACE),
        "the 'replace the collection on AnkiDroid' confirmation",
    )
    phone.tap(confirm)


def await_download(phone: Phone, since: str, user: str, *, empty: bool) -> str:
    """Wait for the full download; return AnkiDroid's client string."""
    deadline = time.monotonic() + SYNC_TIMEOUT_S
    while time.monotonic() < deadline:
        requests = phone_requests(since, user)
        if uploads := [u for u, _ in requests if u.startswith("/sync/upload")]:
            msg = f"the phone UPLOADED ({uploads}); restore the server backup"
            raise StepError(msg)
        screen = phone.dump()
        if screen.find(texts=CONFLICT) is not None:
            answer_conflict(phone, screen, safe=empty and bool(requests))
            continue
        pulled = [c for u, c in requests if u.startswith("/sync/download")]
        if pulled and all(screen.has_text_prefix(d) for d in EXPECTED_DECKS):
            return pulled[-1]
        time.sleep(2.0)
    msg = f"no finished download in {SYNC_TIMEOUT_S:.0f}s: {phone.dump().describe()}"
    raise StepError(msg)


def main() -> int:
    """Run the whole flow; 0 on a proven download, 1 otherwise."""
    logging.basicConfig(format="phone_setup_auto: %(message)s", level=logging.INFO)
    since = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    try:
        url, user, password = read_account()
        phone = Phone(PACKAGE)
        empty = open_sync_settings(phone)
        set_sync_url(phone, url)
        log_in(phone, user, password)
        client = await_download(phone, since, user, empty=empty)
    except StepError, OSError, KeyError, subprocess.SubprocessError:
        LOG.exception("STOPPED")
        return 1
    LOG.info('downloaded: /sync/download from client="%s", no upload', client)
    LOG.info("deck list shows: %s", ", ".join(EXPECTED_DECKS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
