"""Bridge: import handle_recall_card_action from the hyphens-in-path hook dir.

owner/feishu/ is a normal Python package so feishu.py can do a standard
import.  The actual card-building logic lives in
owner/hooks/qdrant-memory-recall/recall_card.py, which is not
Python-importable because of the hyphens in the directory name.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

_HOOK_DIR = str(Path(__file__).resolve().parent.parent / "hooks" / "qdrant-memory-recall")
if _HOOK_DIR not in sys.path:
    sys.path.insert(0, _HOOK_DIR)
from recall_card import handle_recall_card_action  # noqa: E402

__all__ = ["handle_recall_card_action"]
