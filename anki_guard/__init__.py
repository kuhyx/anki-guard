# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""anki-guard: credit a day once Anki's own studied-today figure reaches 20 min.

AnkiDroid syncs to a self-hosted ``anki --syncserver`` on the PC; this package
reads the server's copy of the collection and publishes an HMAC-signed credit
row that earned_time's ``anki`` earner turns into gaming and shutdown time.
"""
