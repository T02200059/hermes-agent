"""DeepSeek native model-id aliases for ids delisted from GET /v1/models.

DeepSeek's 2026-09 Flash refresh made ``deepseek-flash`` the public canonical
id. ``GET /v1/models`` now returns only ``deepseek-flash`` and
``deepseek-v4-pro``. The older ``deepseek-v4-flash`` still works on the wire
(server remaps it to ``deepseek-flash``) but Hermes' ``/model`` validation
probes the live listing and soft-warns when the typed id is absent — noisy for
saved defaults / picker rows that still say ``deepseek-v4-flash``.

Folding here mirrors official ``deepseek-chat`` / ``deepseek-reasoner`` →
``deepseek-flash`` in ``hermes_cli.model_normalize``. Damodel and other
aggregators keep their own ids; this map is only applied on the DeepSeek
provider normalize path.
"""

from __future__ import annotations

from typing import MutableMapping

# Delisted-but-still-aliased native ids → current public id.
EXTRA_DEEPSEEK_RETIRED_ALIASES: dict[str, str] = {
    "deepseek-v4-flash": "deepseek-flash",
}


def apply_deepseek_retired_aliases(alias_map: MutableMapping[str, str]) -> None:
    """Merge owner extras into the official retired-alias map (in place)."""
    alias_map.update(EXTRA_DEEPSEEK_RETIRED_ALIASES)
