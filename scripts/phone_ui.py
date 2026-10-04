#!/usr/bin/env python3
# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Drive a native Android app over adb by what is ON screen, never by guesses.

Every tap targets a node found in a fresh ``uiautomator dump`` (by
resource-id, exact text or content-desc) and taps its bounds' centre; every
wait re-dumps until the expected node appears or fails with the screen's
text. Input goes to display 0 (``-d 0``): on this phone a bare ``input``
can land on another session's virtual display.

Typed text travels over adb's STDIN, not argv, so a password never sits in a
process list or in a ``CalledProcessError`` message.
"""

from __future__ import annotations

from dataclasses import dataclass
import html
import logging
import re
import shlex
import shutil
import subprocess
import sys
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

LOG = logging.getLogger("phone_ui")
_NODE = re.compile(r"<node ([^>]*?)/?>")
_ATTR = re.compile(r'([\w-]+)="([^"]*)"')
_BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
# Only shell-inert characters: `input text` turns %s into a space and the
# value passes through the phone's sh. Anything else is refused, not mangled.
SAFE_TEXT = re.compile(r"[A-Za-z0-9._:/@+-]+")
# Google Password Manager's "save password?" sheet after a login: declined,
# never "Save", so the run never stores the sync password anywhere.
SAVE_PROMPT_NO = frozenset({"Not now", "Nie teraz"})


class StepError(RuntimeError):
    """The phone is not on the screen the flow expects; stop, never guess."""


@dataclass(frozen=True)
class Node:
    """One view from a uiautomator dump."""

    text: str
    rid: str
    desc: str
    package: str
    secret: bool
    bounds: tuple[int, int, int, int]

    @property
    def centre(self) -> tuple[int, int]:
        """Return the point a tap on this node should hit."""
        left, top, right, bottom = self.bounds
        return (left + right) // 2, (top + bottom) // 2


@dataclass(frozen=True)
class Screen:
    """The nodes of one dump, in document order."""

    nodes: tuple[Node, ...]

    def find(
        self,
        *,
        rid: str = "",
        texts: frozenset[str] = frozenset(),
        descs: frozenset[str] = frozenset(),
    ) -> Node | None:
        """Return the first node matching every given criterion."""
        for node in self.nodes:
            if rid and node.rid != rid:
                continue
            if texts and node.text not in texts:
                continue
            if descs and node.desc not in descs:
                continue
            return node
        return None

    def has_text_prefix(self, prefix: str) -> bool:
        """Say whether any node's text starts with ``prefix``."""
        return any(node.text.startswith(prefix) for node in self.nodes)

    def summary_of(self, titles: frozenset[str]) -> str | None:
        """Return the summary line of the preference row titled ``titles``."""
        found = False
        for node in self.nodes:
            if found and node.rid == "summary":
                return node.text
            if found and node.rid == "title":
                return None
            found = found or (node.rid == "title" and node.text in titles)
        return None

    def describe(self) -> str:
        """Visible text for a failure message; password fields are skipped."""
        parts = [n.text or n.desc for n in self.nodes if not n.secret]
        return " | ".join(p for p in parts if p)[:1500]


def run(
    cmd: list[str],
    *,
    stdin: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a local command with a timeout, capturing text output."""
    return subprocess.run(
        cmd,
        input=stdin,
        check=check,
        capture_output=True,
        text=True,
        timeout=60,
    )


def parse_dump(xml: str) -> Screen:
    """Turn ``uiautomator dump`` XML into a Screen (regex: flat, trusted shape)."""
    nodes: list[Node] = []
    for match in _NODE.finditer(xml):
        attrs = {k: html.unescape(v) for k, v in _ATTR.findall(match.group(1))}
        box = _BOUNDS.fullmatch(attrs.get("bounds", ""))
        if box is None:
            continue
        left, top, right, bottom = (int(g) for g in box.groups())
        nodes.append(
            Node(
                text=attrs.get("text", ""),
                rid=attrs.get("resource-id", "").rpartition("/")[2],
                desc=attrs.get("content-desc", ""),
                package=attrs.get("package", ""),
                secret=attrs.get("password") == "true",
                bounds=(left, top, right, bottom),
            ),
        )
    return Screen(tuple(nodes))


class Phone:
    """adb access to the one connected phone (``ANDROID_SERIAL`` picks one)."""

    def __init__(self, package: str) -> None:
        """Resolve adb and remember which app every dump must belong to."""
        adb = shutil.which("adb")
        if adb is None:
            msg = "adb is not installed (pacman -S android-tools)"
            raise StepError(msg)
        self._adb = adb
        self._package = package

    def shell(self, *args: str) -> str:
        """Run one command on the phone and return its stdout."""
        return run([self._adb, "shell", *args]).stdout

    def dump(self, *, dismiss: bool = True) -> Screen:
        """Dump the UI; refuse a dump that is not the app's window."""
        # Straight to stdout: a dump FILE on shared storage would keep the
        # login form's password field in plain text after the run.
        xml = run([self._adb, "exec-out", "uiautomator", "dump", "/dev/tty"]).stdout
        screen = parse_dump(xml)
        if not any(n.package == self._package for n in screen.nodes):
            later = screen.find(texts=SAVE_PROMPT_NO)
            if dismiss and later is not None and later.package.startswith("com.google"):
                self.tap(later)
                time.sleep(1.0)
                return self.dump(dismiss=False)
            msg = f"the screen is not {self._package}: {screen.describe()}"
            raise StepError(msg)
        return screen

    def tap(self, node: Node) -> None:
        """Tap the centre of a node from the current dump."""
        x, y = node.centre
        self.shell("input", "-d", "0", "tap", str(x), str(y))

    def key(self, *codes: str) -> None:
        """Send key events to display 0."""
        self.shell("input", "-d", "0", "keyevent", *codes)

    def hide_keyboard(self) -> None:
        """Close the soft keyboard if (and only if) it is up: BACK would leave."""
        if "mInputShown=true" in self.shell("dumpsys", "input_method"):
            self.key("KEYCODE_BACK")

    def swipe_up(self) -> None:
        """Scroll the content one half-screen down."""
        self.shell("input", "-d", "0", "swipe", "540", "1800", "540", "900", "400")

    def replace_text(self, field: Node, value: str) -> None:
        """Focus ``field``, clear it, type ``value`` (over stdin, never argv)."""
        if not SAFE_TEXT.fullmatch(value):
            msg = "a value has characters adb `input text` cannot type safely"
            raise StepError(msg)
        self.tap(field)
        self.shell(
            "input", "-d", "0", "keycombination", "KEYCODE_CTRL_LEFT", "KEYCODE_A"
        )
        self.key("KEYCODE_DEL")
        line = f"input -d 0 text {shlex.quote(value)}\n"
        typed = run([self._adb, "shell"], stdin=line, check=False)
        if typed.returncode != 0:
            msg = f"typing into {field.rid or 'a field'} failed (value withheld)"
            raise StepError(msg)

    def wait_for(
        self,
        found: Callable[[Screen], Node | None],
        what: str,
        timeout: float = 20.0,
    ) -> tuple[Screen, Node]:
        """Re-dump until ``found`` returns a node; fail with the screen's text."""
        deadline = time.monotonic() + timeout
        while True:
            screen = self.dump()
            node = found(screen)
            if node is not None:
                return screen, node
            if time.monotonic() > deadline:
                msg = f"timed out waiting for {what}; screen shows: {screen.describe()}"
                raise StepError(msg)
            time.sleep(1.0)


def main() -> int:
    """Log what the phone shows right now (a debugging aid for the flow)."""
    logging.basicConfig(format="phone_ui: %(message)s", level=logging.INFO)
    try:
        screen = Phone(sys.argv[1] if len(sys.argv) > 1 else "com.ichi2.anki").dump()
    except StepError, OSError, subprocess.SubprocessError:
        LOG.exception("could not read the screen")
        return 1
    for node in screen.nodes:
        if (node.text or node.desc) and not node.secret:
            LOG.info("%r %s %r %s", node.text, node.rid, node.desc, node.bounds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
