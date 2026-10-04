# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Entry point: ``python -m anki_guard`` (only ever run, never imported)."""

import sys

from anki_guard._cli import main

sys.exit(main())
