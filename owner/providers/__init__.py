"""Owner provider extensions.

- ``credential_helpers`` — prefix-aware env filtering and OAuth expiry checks
  for /providers listing.
- ``damodel`` — Damodel NewAPI proxy ``ProviderProfile`` (registered via the
  bundled ``plugins/model-providers/damodel/`` glue).
- ``deepseek_aliases`` — fold delisted native ``deepseek-v4-flash`` onto
  ``deepseek-flash`` for the DeepSeek provider normalize path.
"""
