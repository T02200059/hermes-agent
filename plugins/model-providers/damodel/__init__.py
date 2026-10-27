"""[owner] C03 Damodel model-provider plugin — thin registration glue.

Profile lives in ``owner/providers/damodel``; this package exists so the
official ``plugins/model-providers/`` discovery path picks it up.
"""

from __future__ import annotations

from providers import register_provider

from owner.providers.damodel import damodel

# [owner] C03: register damodel into official provider discovery
register_provider(damodel)
