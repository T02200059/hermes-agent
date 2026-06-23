"""DashScope image generation backend for Hermes.

Implements an :class:`ImageGenProvider` that calls the DashScope
``multimodal-generation/generation`` endpoint (Qwen-Image / Wan text-to-image).

Configuration (presets, api_key, etc.) is read from ``~/.hermes/patch.yaml``
under ``owner.image_gen.presets`` via the unified owner.patch_config loader
(mtime + 5-minute refresh).

The active preset/model can be selected by:
- passing model=... to the image_generate tool, or
- ``owner.image_gen.model`` in patch.yaml (preferred for owner customizations), or
- falling back to ``image_gen.model`` in config.yaml for compatibility.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from owner.patch_config import _load_patch_owner_config

from agent.image_gen_provider import (
    DEFAULT_ASPECT_RATIO,
    ImageGenProvider,
    error_response,
    resolve_aspect_ratio,
    save_b64_image,
    save_url_image,
    success_response,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
DEFAULT_API_KEY_ENV = "DASHSCOPE_API_KEY"

_ASPECT_RATIO_SIZES = {
    "landscape": "1024*576",  # 16:9
    "portrait": "576*1024",   # 9:16
    "square": "1024*1024",    # 1:1
}


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _get_owner_image_gen_presets() -> Dict[str, Any]:
    """Return ``owner.image_gen.presets`` from patch.yaml."""
    owner_cfg = _load_patch_owner_config()
    image_gen_cfg = owner_cfg.get("image_gen") if isinstance(owner_cfg.get("image_gen"), dict) else {}
    presets = image_gen_cfg.get("presets") if isinstance(image_gen_cfg.get("presets"), dict) else {}
    return presets


def _expand_env(value: Any) -> Any:
    """Expand ``${VAR}`` / ``$VAR`` placeholders in string values."""
    if isinstance(value, str):
        return os.path.expandvars(value)
    return value


def _is_dashscope_preset(cfg: Dict[str, Any]) -> bool:
    """Return True when *cfg* looks like a DashScope preset.

    Heuristic: endpoint is unset or points at a dashscope domain. This keeps
    the dashscope provider from trying to use unrelated presets (e.g.
    openrouter-grok) that may live in the same ``owner.image_gen.presets``
    namespace.
    """
    endpoint = str(cfg.get("endpoint") or DEFAULT_ENDPOINT).strip().lower()
    return "dashscope" in endpoint


def _resolve_preset(model_id: str) -> Optional[Dict[str, Any]]:
    """Find the DashScope preset matching *model_id* by alias or full preset name.

    Returns the merged preset dict with env vars expanded, or ``None`` if no
    match is found.
    """
    if not isinstance(model_id, str) or not model_id.strip():
        return None

    presets = _get_owner_image_gen_presets()
    model_id = model_id.strip()

    # First try to match a preset name exactly.
    preset = presets.get(model_id)
    if isinstance(preset, dict) and _is_dashscope_preset(preset):
        return {k: _expand_env(v) for k, v in preset.items()}

    # Otherwise match by alias.
    for name, cfg in presets.items():
        if not isinstance(cfg, dict) or not _is_dashscope_preset(cfg):
            continue
        aliases = cfg.get("alias") or cfg.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        if model_id in aliases:
            return {k: _expand_env(v) for k, v in cfg.items()}

    return None


def _resolve_configured_model() -> str:
    """Read the active image_gen model, preferring owner.image_gen.model from patch.yaml.

    This is the migration point: owner-specific image_gen selection lives in
    patch.yaml under owner.image_gen.model (or via presets aliases). We still
    fall back to the main config.yaml image_gen.model for compatibility, but
    owner customizations should use patch.yaml + the unified loader.
    """
    # 1. Prefer patch.yaml (unified owner config, with 5min/mtime refresh)
    try:
        from owner.patch_config import _load_patch_owner_config
        owner_cfg = _load_patch_owner_config()
        ig = owner_cfg.get("image_gen") if isinstance(owner_cfg, dict) else None
        if isinstance(ig, dict):
            value = ig.get("model")
            if isinstance(value, str) and value.strip():
                return value.strip()
    except Exception as exc:
        logger.debug("Could not read owner.image_gen.model from patch: %s", exc)

    # 2. Fallback to main config.yaml (for non-owner or legacy setups)
    try:
        from hermes_cli.config import load_config
        cfg = load_config()
        section = cfg.get("image_gen") if isinstance(cfg, dict) else None
        if isinstance(section, dict):
            value = section.get("model")
            if isinstance(value, str) and value.strip():
                return value.strip()
    except Exception as exc:
        logger.debug("Could not read image_gen.model from config.yaml: %s", exc)
    return ""


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class DashScopeImageGenProvider(ImageGenProvider):
    """DashScope ``multimodal-generation/generation`` image backend."""

    @property
    def name(self) -> str:
        return "dashscope"

    @property
    def display_name(self) -> str:
        return "DashScope (Qwen / Wan)"

    def is_available(self) -> bool:
        # Check env var first, then DashScope presets in patch.yaml.
        if os.environ.get(DEFAULT_API_KEY_ENV):
            return True
        presets = _get_owner_image_gen_presets()
        for cfg in presets.values():
            if isinstance(cfg, dict) and _is_dashscope_preset(cfg) and _expand_env(cfg.get("api_key")):
                return True
        return False

    def list_models(self) -> List[Dict[str, Any]]:
        presets = _get_owner_image_gen_presets()
        models: List[Dict[str, Any]] = []
        for preset_name, cfg in presets.items():
            if not isinstance(cfg, dict) or not _is_dashscope_preset(cfg):
                continue
            aliases = cfg.get("alias") or cfg.get("aliases") or []
            if isinstance(aliases, str):
                aliases = [aliases]
            model_id = aliases[0] if aliases else preset_name
            models.append(
                {
                    "id": model_id,
                    "display": cfg.get("display") or preset_name,
                    "speed": cfg.get("speed", ""),
                    "strengths": cfg.get("strengths", ""),
                }
            )
        return models

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": self.display_name,
            "badge": "paid",
            "tag": "DashScope Qwen-Image / Wan text-to-image via owner.image_gen.presets",
            "env_vars": [
                {
                    "key": DEFAULT_API_KEY_ENV,
                    "prompt": "DashScope API key",
                    "url": "https://dashscope.aliyun.com/",
                },
            ],
        }

    def capabilities(self) -> Dict[str, Any]:
        return {
            "modalities": ["text", "image"],
            "max_reference_images": 3,
        }

    def generate(
        self,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        *,
        image_url: Optional[str] = None,
        reference_image_urls: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate an image via DashScope multimodal generation API."""
        aspect = resolve_aspect_ratio(aspect_ratio)

        # Determine active model / preset.
        model_arg = str(kwargs.get("model") or "").strip()
        configured_model = _resolve_configured_model()
        model_id = model_arg or configured_model

        preset = _resolve_preset(model_id) if model_id else None
        if preset is None and configured_model:
            preset = _resolve_preset(configured_model)

        if preset is None:
            return error_response(
                error=(
                    f"No DashScope preset found for model '{model_id}'. "
                    "Add it to owner.image_gen.presets in ~/.hermes/patch.yaml."
                ),
                error_type="missing_preset",
                provider=self.name,
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        endpoint = str(preset.get("endpoint") or DEFAULT_ENDPOINT).strip()
        api_key = str(preset.get("api_key") or "").strip()
        if not api_key:
            api_key = os.environ.get(DEFAULT_API_KEY_ENV, "")
        actual_model = str(preset.get("model") or model_id).strip()

        if not api_key:
            return error_response(
                error=(
                    "DashScope API key not configured. Set "
                    f"{DEFAULT_API_KEY_ENV} or add api_key to the preset."
                ),
                error_type="missing_api_key",
                provider=self.name,
                model=actual_model,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        size = str(preset.get("size") or _ASPECT_RATIO_SIZES.get(aspect, "1024*1024")).strip()

        # Build content: image editing when source images provided, text-to-image otherwise
        content: list = []
        source_images: list = []
        if image_url:
            source_images.append(image_url)
        if reference_image_urls:
            source_images.extend(reference_image_urls)

        # WR-01: honor the advertised reference-image cap instead of shipping an
        # oversized payload and getting an opaque API error back.
        max_ref = int(self.capabilities().get("max_reference_images", 3) or 3)
        if len(source_images) > max_ref:
            return error_response(
                error=f"At most {max_ref} reference images supported; got {len(source_images)}.",
                error_type="invalid_input",
                provider=self.name,
                model=actual_model,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        # WR-02: reject non-http(s)/data source URLs before they enter the
        # payload (DashScope fetches these server-side).
        for img in source_images:
            scheme = urlparse(str(img)).scheme.lower()
            if scheme not in ("http", "https", "data"):
                return error_response(
                    error=f"Unsupported image URL scheme {scheme!r}; only http/https/data are allowed.",
                    error_type="invalid_input",
                    provider=self.name,
                    model=actual_model,
                    prompt=prompt,
                    aspect_ratio=aspect,
                )

        for img in source_images:
            content.append({"image": img})
        content.append({"text": prompt})

        # Use message-based format for newer models (qwen-image-2.0, wan2.6+),
        # fall back to legacy input.prompt format when preset specifies mode: prompt
        preset_mode = str(preset.get("mode") or "message").strip().lower()
        if preset_mode == "prompt":
            # Legacy prompt format — DashScope legacy models don't support image editing
            # via this format, so only use it for text-to-image
            if source_images:
                logger.warning("DashScope preset mode='prompt' does not support image editing; ignoring source images")
            payload: Dict[str, Any] = {
                "model": actual_model,
                "input": {"prompt": prompt},
                "parameters": {"size": size, "n": 1},
            }
        else:
            payload = {
                "model": actual_model,
                "input": {
                    "messages": [
                        {"role": "user", "content": content}
                    ]
                },
                "parameters": {"size": size, "n": 1},
            }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=120,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            resp = exc.response
            status = resp.status_code if resp is not None else 0
            try:
                err_msg = resp.json().get("message", resp.text[:300]) if resp is not None else str(exc)
            except Exception:
                err_msg = resp.text[:300] if resp is not None else str(exc)
            logger.error("DashScope image gen failed (%d): %s", status, err_msg)
            return error_response(
                error=f"DashScope image generation failed ({status}): {err_msg}",
                error_type="api_error",
                provider=self.name,
                model=actual_model,
                prompt=prompt,
                aspect_ratio=aspect,
            )
        except requests.Timeout:
            return error_response(
                error="DashScope image generation timed out (120s)",
                error_type="timeout",
                provider=self.name,
                model=actual_model,
                prompt=prompt,
                aspect_ratio=aspect,
            )
        except requests.ConnectionError as exc:
            return error_response(
                error=f"DashScope connection error: {exc}",
                error_type="connection_error",
                provider=self.name,
                model=actual_model,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        try:
            result = response.json()
        except Exception as exc:
            return error_response(
                error=f"DashScope returned invalid JSON: {exc}",
                error_type="invalid_response",
                provider=self.name,
                model=actual_model,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        output = result.get("output") if isinstance(result, dict) else None
        if not isinstance(output, dict):
            return error_response(
                error="DashScope response missing output field",
                error_type="empty_response",
                provider=self.name,
                model=actual_model,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        task_status = output.get("task_status")
        if task_status and str(task_status).upper() != "SUCCEEDED":
            return error_response(
                error=f"DashScope task status: {task_status}",
                error_type="api_error",
                provider=self.name,
                model=actual_model,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        # Try message-based response format first (qwen-image-2.0, wan2.6+)
        image_ref: Optional[str] = None
        choices = output.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            msg_content = (choices[0].get("message") or {}).get("content")
            if isinstance(msg_content, list) and msg_content and isinstance(msg_content[0], dict):
                img_url = msg_content[0].get("image") or msg_content[0].get("url")
                if img_url:
                    try:
                        saved_path = save_url_image(str(img_url), prefix=f"dashscope_{actual_model}")
                        image_ref = str(saved_path)
                    except Exception as exc:
                        logger.warning("DashScope image URL cache failed (%s); using bare URL.", exc)
                        image_ref = str(img_url)

        # Fallback: legacy results format
        if image_ref is None:
            results = output.get("results")
            if not isinstance(results, list) or not results:
                return error_response(
                    error="DashScope returned no image results",
                    error_type="empty_response",
                    provider=self.name,
                    model=actual_model,
                    prompt=prompt,
                    aspect_ratio=aspect,
                )

            first = results[0]
            if not isinstance(first, dict):
                return error_response(
                    error="DashScope returned malformed image result",
                    error_type="empty_response",
                    provider=self.name,
                    model=actual_model,
                    prompt=prompt,
                    aspect_ratio=aspect,
                )
            b64 = first.get("b64_image")
            url = first.get("url")

            if b64:
                try:
                    saved_path = save_b64_image(b64, prefix=f"dashscope_{actual_model}")
                except Exception as exc:
                    return error_response(
                        error=f"Could not save image to cache: {exc}",
                        error_type="io_error",
                        provider=self.name,
                        model=actual_model,
                        prompt=prompt,
                        aspect_ratio=aspect,
                    )
                image_ref = str(saved_path)
            elif url:
                try:
                    saved_path = save_url_image(url, prefix=f"dashscope_{actual_model}")
                except Exception as exc:
                    logger.warning(
                        "DashScope image URL %s could not be cached (%s); falling back to bare URL.",
                        url,
                        exc,
                    )
                    image_ref = url
                else:
                    image_ref = str(saved_path)
            else:
                return error_response(
                    error="DashScope response contained neither b64_image nor URL",
                    error_type="empty_response",
                    provider=self.name,
                    model=actual_model,
                    prompt=prompt,
                    aspect_ratio=aspect,
                )

        extra: Dict[str, Any] = {"size": size}
        if task_status:
            extra["task_status"] = task_status

        return success_response(
            image=image_ref,
            model=actual_model,
            prompt=prompt,
            aspect_ratio=aspect,
            provider=self.name,
            modality="image" if source_images else "text",
            extra=extra,
        )
