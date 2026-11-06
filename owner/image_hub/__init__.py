"""
Image Hub — multi-platform image generation backend.

Supports three API modes configured via **presets** in
``overlay.yaml → image_gen`` (loaded by ``hermes_cli`` under ``config.owner``):

* ``dashscope-message`` — DashScope multimodal-generation API
  (qwen-image-2.0, wan2.6-t2i, etc.)
* ``openai-image`` — OpenAI ``/images/generations``-compatible endpoints
  (xAI, etc.)
* ``openai-chat`` — Chat Completions with ``modalities: ["image"]``
  (OpenRouter image models, etc.)

Preset switching via model alias
=================================
Set ``current`` in overlay.yaml to the active preset name.

The agent can **switch presets entirely** by passing a ``model`` string
that matches a preset's ``name`` or ``alias`` list. For example:

* ``model="wan"`` → matches ``dashscope-wan`` preset (via ``alias: [wan]``)
* ``model="qwen-pro"`` → matches the configured qwen-pro preset alias
* ``model="dashscope-qwen"`` → matches ``dashscope-qwen`` preset (via name)
* ``model="qwen-image-2.0"`` → no alias match, used as model name on current
  preset

If ``model`` does not match any preset name or alias, it is used directly as
the model ID for the currently-active preset.

Image editing (i2i) source images
=================================
For image-to-image presets (e.g. ``dashscope-image-edit`` with
``qwen-image-edit-plus``), pass ``image_url=`` with either:

* a public ``http://`` or ``https://`` URL, or
* a local filesystem path (auto-encoded to a ``data:`` URI), or
* a pre-encoded ``data:...;base64,...`` URI.

Local paths are transparently encoded to base64 data URIs by
:meth:`ImageHubProvider.generate` (see
:func:`_maybe_local_to_data_uri`). Files larger than ~9.5MB are NOT
auto-encoded — pre-upload them somewhere and pass the URL instead.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
import re
from pathlib import Path
from typing import Any, Optional

import requests

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
# Aspect-ratio → dimension string (same mapping for all modes; formatting
# differs: DashScope uses "*", OpenAI uses "x").
# ---------------------------------------------------------------------------

_SIZES = {
    "landscape": "1024x768",
    "square": "1024x1024",
    "portrait": "768x1024",
}

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _expand_env(s: str) -> str:
    """Expand ``${VAR}`` references in *s* using ``os.environ``.

    Unresolved references are left verbatim so callers can detect them.
    """
    return re.sub(r"\${([^}]+)}", lambda m: os.environ.get(m.group(1), m.group(0)), s)


def _read_overlay_image_gen() -> dict:
    """Read the profile's overlay section, without a legacy-file fallback.

    ``apply_owner_overlay`` has already put this under ``config.owner``; using
    the same read-only loader keeps profile scope and secret resolution in
    Hermes' existing config boundary. An invalid overlay returns ``{}`` and
    never falls through to credentials in the retired legacy config file.
    """
    from hermes_cli.config import load_config_readonly

    owner = load_config_readonly().get("owner", {})
    config = owner.get("image_gen", {}) if isinstance(owner, dict) else {}
    return dict(config) if isinstance(config, dict) else {}


def _maybe_local_to_data_uri(value: Optional[str]) -> Optional[str]:
    """If *value* is a local filesystem path, convert to a ``data:`` URI.

    Some backends (notably DashScope's multimodal-generation API used by
    qwen-image-edit-plus) only accept **public HTTP(S) URLs** or
    **base64 data URIs** as source images. Passing a raw local path
    produces a 400 ``InvalidParameter`` error.

    This helper transparently upgrades local paths so the caller doesn't
    have to think about it. Behavior:

    * ``None`` / empty → returned unchanged.
    * ``http://`` / ``https://`` / ``data:`` prefix → returned unchanged.
    * Otherwise treated as a local path. Sensitive paths are rejected using
      the shared Hermes read guard. If a non-sensitive file is readable, it
      is returned as ``data:<mime>;base64,<...>``. Other read failures return
      the original value so the downstream backend can report them.
    """
    if not value or not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return value
    lower = stripped.lower()
    if lower.startswith(("http://", "https://", "data:")):
        return value
    try:
        from agent.file_safety import raise_if_read_blocked

        raise_if_read_blocked(stripped)
        path = Path(stripped).expanduser()
        if not path.is_file():
            return value
        # Cap at ~9.5MB to keep data URI well under the 10MB URL length
        # limit most HTTP gateways impose. Larger files would need a
        # hosted URL anyway.
        size = path.stat().st_size
        if size > 9_500_000:
            logger.debug(
                "image source %s is %d bytes (>9.5MB); not auto-encoding",
                path, size,
            )
            return value
        mime, _ = mimetypes.guess_type(str(path))
        if not mime:
            mime = "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    except ValueError:
        # A policy rejection must reach the tool response; silently forwarding
        # the path would defeat the guard and could leak a secret upstream.
        raise
    except Exception as exc:
        logger.debug("Could not auto-encode local path %s: %s", stripped, exc)
        return value


def _cache_prefix(model_id: str) -> str:
    """Return a filesystem-safe, bounded cache prefix for a model identifier."""
    safe_model = re.sub(r"[^A-Za-z0-9._-]+", "_", str(model_id)).strip("._")
    return f"imagehub_{(safe_model or 'model')[:80]}"


def _resolve_active_preset() -> Optional[dict]:
    """Resolve the currently-active preset dict, with ``${VAR}`` expanded.

    Reads ``presets`` and ``current`` from overlay's ``image_gen`` section,
    returns the matching preset (with api_key expanded). Returns None when
    no valid preset can be resolved.
    """
    cfg = _read_overlay_image_gen()
    presets = cfg.get("presets") or {}
    current_name = cfg.get("current", "")

    if not isinstance(current_name, str) or not current_name.strip():
        logger.debug("image-hub: no 'current' preset set in overlay.yaml image_gen")
        return None

    preset = presets.get(current_name.strip())
    if not isinstance(preset, dict):
        logger.debug("image-hub: preset '%s' not found in overlay.yaml", current_name)
        return None

    # Deep-copy and expand env vars in api_key
    result = dict(preset)
    raw_key = result.get("api_key", "")
    if isinstance(raw_key, str):
        result["api_key"] = _expand_env(raw_key.strip())
    return result


def _resolve_presets() -> dict[str, dict]:
    """Return all presets as a dict, with api_key expanded."""
    cfg = _read_overlay_image_gen()
    presets = cfg.get("presets") or {}
    if not isinstance(presets, dict):
        return {}
    expanded: dict[str, dict] = {}
    for name, p in presets.items():
        if isinstance(p, dict):
            resolved = dict(p)
            raw_key = resolved.get("api_key", "")
            if isinstance(raw_key, str):
                resolved["api_key"] = _expand_env(raw_key.strip())
            expanded[name] = resolved
    return expanded


def _list_preset_model_entries() -> list[dict[str, Any]]:
    """Build a model list from all presets for ``list_models()``."""
    entries: list[dict[str, Any]] = []
    for name, preset in _resolve_presets().items():
        model_id = preset.get("model", "unknown")
        mode = preset.get("mode", "?")
        entries.append({
            "id": model_id,
            "display": f"{name} ({model_id})",
            "speed": "~varies",
            "strengths": f"Preset '{name}' — mode={mode}",
        })
    return entries


def _match_preset_by_alias(alias_str: str) -> Optional[dict]:
    """Traverse all presets, matching *alias_str* against alias list or preset name.

    Returns the matched preset dict (with api_key expanded), or None.
    """
    presets = _resolve_presets()
    for name, preset in presets.items():
        if not isinstance(preset, dict):
            continue
        # Check preset name
        if name == alias_str:
            return preset
        # Check alias list
        aliases = preset.get("alias", [])
        if isinstance(aliases, list) and alias_str in aliases:
            return preset
        if isinstance(aliases, str) and aliases == alias_str:
            return preset
    return None


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class ImageHubProvider(ImageGenProvider):
    """Multi-platform image generation backend with preset switching + alias matching.

    All config comes from ``overlay.yaml → image_gen`` (``config.owner`` at runtime):

    * ``current`` — name of the active preset
    * ``presets`` — dict of named presets, each containing:
        - ``mode``: ``"dashscope-message"`` | ``"openai-image"`` | ``"openai-chat"``
        - ``endpoint``: API URL (full URL, no path appended by the plugin)
        - ``model``: default model id
        - ``api_key``: plain text or ``${ENV_VAR}`` reference
        - ``alias``: (optional) list of alias strings for preset switching
    """

    @property
    def name(self) -> str:
        return "image-hub"

    @property
    def display_name(self) -> str:
        preset = _resolve_active_preset()
        if preset:
            cfg = _read_overlay_image_gen()
            cur = cfg.get("current", "")
            return f"Image Hub ({cur})"
        return "Image Hub"

    def tool_parameter_overrides(self) -> dict[str, dict[str, Any]]:
        """Advertise the configured presets, without dumping their credentials."""
        from owner.image_hub.schema import tool_parameter_overrides

        choices = []
        for name, preset in (_read_overlay_image_gen().get("presets") or {}).items():
            if not isinstance(preset, dict):
                continue
            choices.append(name)
            aliases = preset.get("alias") or []
            choices.extend([aliases] if isinstance(aliases, str) else aliases)
        return tool_parameter_overrides(choices)

    def capabilities(self) -> dict[str, Any]:
        return {
            "modalities": ["text", "image"],
            "max_reference_images": 3,
        }

    def is_available(self) -> bool:
        preset = _resolve_active_preset()
        if not preset:
            return False
        return bool(preset.get("api_key"))

    def list_models(self) -> list[dict[str, Any]]:
        return _list_preset_model_entries()

    def get_setup_schema(self) -> dict[str, Any]:
        preset = _resolve_active_preset()
        cur_model = preset.get("model", "?") if preset else "?"
        return {
            "name": "Image Hub",
            "badge": "paid" if preset else "unconfigured",
            "tag": f"Multi-platform image gen — preset={cur_model} — config via overlay.yaml image_gen",
            "env_vars": [],
        }

    def generate(
        self,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        *,
        image_url: Optional[str] = None,
        reference_image_urls: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        prompt = (prompt or "").strip()
        aspect = resolve_aspect_ratio(aspect_ratio)

        if not prompt:
            return error_response(
                error="Prompt is required and must be a non-empty string",
                error_type="invalid_argument",
                provider="image-hub",
                aspect_ratio=aspect,
            )

        try:
            # Match the official provider contract: image_url counts toward
            # the total cap and takes precedence over additional references.
            raw_sources = ([image_url] if isinstance(image_url, str) else [])
            if isinstance(reference_image_urls, (list, tuple)):
                raw_sources.extend(reference_image_urls)
            source_images = [
                _maybe_local_to_data_uri(url) or url
                for url in raw_sources[:3]
                if isinstance(url, str) and url.strip()
            ]
        except ValueError as exc:
            return error_response(
                error=str(exc),
                error_type="invalid_argument",
                provider="image-hub",
                aspect_ratio=aspect,
            )

        # ── If model arg is provided, try alias matching ──────────────
        model_from_args = (
            str(kwargs.get("model", "")).strip()
            if isinstance(kwargs.get("model"), str) and kwargs["model"].strip()
            else ""
        )
        matched_preset = None
        if model_from_args:
            matched_preset = _match_preset_by_alias(model_from_args)

        if matched_preset:
            # Alias matched — use the matched preset's config
            api_key = matched_preset.get("api_key", "")
            endpoint = (matched_preset.get("endpoint") or "").strip()
            mode = matched_preset.get("mode", "dashscope-message").strip()
            # Use the matched preset's model (not the alias string)
            actual_model = matched_preset.get("model", model_from_args).strip()
        else:
            # No alias match → use current preset (model_from_args overrides the model id)
            preset = _resolve_active_preset()
            if not preset:
                return error_response(
                    error=(
                        "No active preset configured. Set image_gen.current "
                        "to a valid preset name in overlay.yaml."
                    ),
                    error_type="config_error",
                    provider="image-hub",
                    aspect_ratio=aspect,
                )

            api_key = preset.get("api_key", "")
            endpoint = (preset.get("endpoint") or "").strip()
            mode = (preset.get("mode") or "dashscope-message").strip()

            if model_from_args:
                actual_model = model_from_args
            else:
                actual_model = (preset.get("model") or "unknown").strip()

        # ── Validate resolved values ──────────────────────────────────
        if not api_key:
            return error_response(
                error=(
                    "No api_key in preset. Check the ${VAR} reference "
                    "is set in the environment."
                ),
                error_type="auth_required",
                provider="image-hub",
                aspect_ratio=aspect,
            )

        if not endpoint:
            return error_response(
                error="No endpoint in preset.",
                error_type="config_error",
                provider="image-hub",
                aspect_ratio=aspect,
            )

        size_raw = _SIZES.get(aspect, _SIZES["square"])

        # ── Dispatch by mode ──────────────────────────────────────────
        if mode == "dashscope-message":
            return self._generate_dashscope(
                prompt=prompt,
                model_id=actual_model,
                endpoint=endpoint,
                api_key=api_key,
                size_raw=size_raw,
                aspect=aspect,
                source_images=source_images,
            )
        elif mode == "openai-image":
            if source_images:
                return error_response(
                    error=(
                        f"Mode '{mode}' does not support image-to-image "
                        "or reference images."
                    ),
                    error_type="unsupported_operation",
                    provider="image-hub",
                    model=actual_model,
                    aspect_ratio=aspect,
                )
            return self._generate_openai(
                prompt=prompt,
                model_id=actual_model,
                endpoint=endpoint,
                api_key=api_key,
                size_raw=size_raw,
                aspect=aspect,
            )
        elif mode == "openai-chat":
            if source_images:
                return error_response(
                    error=(
                        f"Mode '{mode}' does not support image-to-image "
                        "or reference images."
                    ),
                    error_type="unsupported_operation",
                    provider="image-hub",
                    model=actual_model,
                    aspect_ratio=aspect,
                )
            return self._generate_openai_chat(
                prompt=prompt,
                model_id=actual_model,
                endpoint=endpoint,
                api_key=api_key,
                size_raw=size_raw,
                aspect=aspect,
            )
        else:
            return error_response(
                error=(
                    f"Unknown image_gen mode '{mode}'. "
                    f"Supported: dashscope-message, openai-image, openai-chat"
                ),
                error_type="config_error",
                provider="image-hub",
                model=actual_model,
                prompt=prompt,
                aspect_ratio=aspect,
            )

    # ------------------------------------------------------------------
    # DashScope multimodal-generation API
    # ------------------------------------------------------------------

    def _generate_dashscope(
        self,
        *,
        prompt: str,
        model_id: str,
        endpoint: str,
        api_key: str,
        size_raw: str,
        aspect: str,
        source_images: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        size_dash = size_raw.replace("x", "*")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        content: list[dict[str, Any]] = []
        if source_images:
            for img in source_images:
                content.append({"image": img})
        content.append({"text": prompt})

        payload = {
            "model": model_id,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": content,
                    }
                ]
            },
            "parameters": {
                "size": size_dash,
                "n": 1,
            },
        }

        try:
            response = requests.post(
                endpoint, headers=headers, json=payload, timeout=120,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            resp = exc.response
            status = resp.status_code if resp is not None else 0
            try:
                err_msg = (
                    resp.json().get("error", {}).get("message", resp.text[:300])
                    if resp is not None else str(exc)
                )
            except Exception:
                err_msg = resp.text[:300] if resp is not None else str(exc)
            logger.error("ImageHub (DashScope) failed (%d): %s", status, err_msg)
            return error_response(
                error=f"Image generation failed ({status}): {err_msg}",
                error_type="api_error",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )
        except requests.Timeout:
            return error_response(
                error="Image generation timed out (120s)",
                error_type="timeout",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )
        except requests.ConnectionError as exc:
            return error_response(
                error=f"Image generation connection error: {exc}",
                error_type="connection_error",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )
        except requests.RequestException as exc:
            return error_response(
                error=f"Image generation request failed: {exc}",
                error_type="connection_error",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        try:
            result = response.json()
        except Exception as exc:
            return error_response(
                error=f"DashScope returned invalid JSON: {exc}",
                error_type="invalid_response",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        # Parse: output.choices[0].message.content[0].image → URL
        output = result.get("output", {}) if isinstance(result, dict) else {}
        choices = output.get("choices", []) if isinstance(output, dict) else []
        if not choices:
            return error_response(
                error="DashScope returned no image data in response",
                error_type="empty_response",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        first = choices[0]
        message = first.get("message", {}) if isinstance(first, dict) else {}
        content = message.get("content", []) if isinstance(message, dict) else []
        if not content:
            return error_response(
                error="DashScope response missing message content",
                error_type="empty_response",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        image_url = None
        for item in content:
            if isinstance(item, dict) and item.get("image"):
                image_url = item["image"]
                break

        if not image_url:
            return error_response(
                error="DashScope response contained no image URL",
                error_type="empty_response",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        # Download (URL expires in 24h) and save to local cache
        try:
            saved_path = save_url_image(
                image_url, prefix=_cache_prefix(model_id), timeout=30,
            )
            image_ref = str(saved_path)
        except Exception as exc:
            return error_response(
                error=f"Could not download/save image from DashScope: {exc}",
                error_type="io_error",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        return success_response(
            image=image_ref,
            model=model_id,
            prompt=prompt,
            aspect_ratio=aspect,
            provider="image-hub",
            extra={"size": size_raw},
        )

    # ------------------------------------------------------------------
    # OpenAI /images/generations compatible API
    # ------------------------------------------------------------------

    def _generate_openai(
        self,
        *,
        prompt: str,
        model_id: str,
        endpoint: str,
        api_key: str,
        size_raw: str,
        aspect: str,
    ) -> dict[str, Any]:
        # endpoint is the full URL (no appending /images/generations)
        api_url = endpoint

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model_id,
            "prompt": prompt,
            "n": 1,
            "size": size_raw,
        }

        try:
            response = requests.post(
                api_url, headers=headers, json=payload, timeout=120,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            resp = exc.response
            status = resp.status_code if resp is not None else 0
            try:
                err_msg = (
                    resp.json().get("error", {}).get("message", resp.text[:300])
                    if resp is not None else str(exc)
                )
            except Exception:
                err_msg = resp.text[:300] if resp is not None else str(exc)
            logger.error("ImageHub (OpenAI) failed (%d): %s", status, err_msg)
            return error_response(
                error=f"Image generation failed ({status}): {err_msg}",
                error_type="api_error",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )
        except requests.Timeout:
            return error_response(
                error="Image generation timed out (120s)",
                error_type="timeout",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )
        except requests.ConnectionError as exc:
            return error_response(
                error=f"Image generation connection error: {exc}",
                error_type="connection_error",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )
        except requests.RequestException as exc:
            return error_response(
                error=f"Image generation request failed: {exc}",
                error_type="connection_error",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        try:
            result = response.json()
        except Exception as exc:
            return error_response(
                error=f"API returned invalid JSON: {exc}",
                error_type="invalid_response",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        # Parse: data[0].b64_json or data[0].url
        data = result.get("data", []) if isinstance(result, dict) else []
        if not data:
            return error_response(
                error="API returned no image data",
                error_type="empty_response",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        first = data[0] if isinstance(data, list) else {}
        if not isinstance(first, dict):
            return error_response(
                error="API returned an invalid image entry",
                error_type="invalid_response",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )
        b64 = first.get("b64_json")
        url = first.get("url")

        if b64:
            try:
                saved_path = save_b64_image(b64, prefix=_cache_prefix(model_id))
            except Exception as exc:
                return error_response(
                    error=f"Could not save image to cache: {exc}",
                    error_type="io_error",
                    provider="image-hub",
                    model=model_id,
                    prompt=prompt,
                    aspect_ratio=aspect,
                )
            image_ref = str(saved_path)
        elif url:
            # Save URL-based result to local cache
            try:
                saved_path = save_url_image(
                    url, prefix=_cache_prefix(model_id), timeout=30,
                )
                image_ref = str(saved_path)
            except Exception as exc:
                return error_response(
                    error=f"Could not download/save image from URL: {exc}",
                    error_type="io_error",
                    provider="image-hub",
                    model=model_id,
                    prompt=prompt,
                    aspect_ratio=aspect,
                )
        else:
            return error_response(
                error="Response contained neither b64_json nor URL",
                error_type="empty_response",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        return success_response(
            image=image_ref,
            model=model_id,
            prompt=prompt,
            aspect_ratio=aspect,
            provider="image-hub",
            extra={"size": size_raw},
        )

    # ------------------------------------------------------------------
    # OpenAI Chat Completions with modalities (OpenRouter image models)
    # ------------------------------------------------------------------

    def _generate_openai_chat(
        self,
        *,
        prompt: str,
        model_id: str,
        endpoint: str,
        api_key: str,
        size_raw: str,
        aspect: str,
    ) -> dict[str, Any]:
        """Generate image via Chat Completions with ``modalities: ["image"]``.

        Used by OpenRouter and other providers that expose image generation
        through the chat completions endpoint.

        Response format:
        ``choices[0].message.images[0].imageUrl.url`` → data:image/png;base64,...
        """
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model_id,
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "modalities": ["image"],
        }

        try:
            response = requests.post(
                endpoint, headers=headers, json=payload, timeout=120,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            resp = exc.response
            status = resp.status_code if resp is not None else 0
            try:
                err_msg = (
                    resp.json().get("error", {}).get("message", resp.text[:300])
                    if resp is not None else str(exc)
                )
            except Exception:
                err_msg = resp.text[:300] if resp is not None else str(exc)
            logger.error("ImageHub (OpenAI Chat) failed (%d): %s", status, err_msg)
            return error_response(
                error=f"Image generation failed ({status}): {err_msg}",
                error_type="api_error",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )
        except requests.Timeout:
            return error_response(
                error="Image generation timed out (120s)",
                error_type="timeout",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )
        except requests.ConnectionError as exc:
            return error_response(
                error=f"Image generation connection error: {exc}",
                error_type="connection_error",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )
        except requests.RequestException as exc:
            return error_response(
                error=f"Image generation request failed: {exc}",
                error_type="connection_error",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        try:
            result = response.json()
        except Exception as exc:
            return error_response(
                error=f"API returned invalid JSON: {exc}",
                error_type="invalid_response",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        # Parse: choices[0].message.images[0].imageUrl.url
        choices = result.get("choices", []) if isinstance(result, dict) else []
        choice = choices[0] if isinstance(choices, list) and choices else {}
        message = choice.get("message", {}) if isinstance(choice, dict) else {}
        images = message.get("images", []) if isinstance(message, dict) else []

        if not images:
            return error_response(
                error=(
                    "API returned no images in response. "
                    "Check that the model supports image generation via chat completions."
                ),
                error_type="empty_response",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        first_image = images[0] if isinstance(images, list) and images else images
        if not isinstance(first_image, dict):
            return error_response(
                error="API returned an invalid image entry",
                error_type="invalid_response",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )
        # Handle both snake_case (image_url) and camelCase (imageUrl)
        url_container = first_image.get("image_url") or first_image.get("imageUrl") or {}
        image_url_data = url_container.get("url", "") if isinstance(url_container, dict) else ""

        if not image_url_data:
            return error_response(
                error="Response contained image entry but no url",
                error_type="empty_response",
                provider="image-hub",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        if image_url_data.startswith("data:"):
            # Data URL — extract base64 and save
            try:
                b64_data = image_url_data.split(",", 1)[1]
                saved_path = save_b64_image(b64_data, prefix=_cache_prefix(model_id))
                image_ref = str(saved_path)
            except Exception as exc:
                return error_response(
                    error=f"Could not save image from data URL: {exc}",
                    error_type="io_error",
                    provider="image-hub",
                    model=model_id,
                    prompt=prompt,
                    aspect_ratio=aspect,
                )
        else:
            # Regular URL — download and save
            try:
                saved_path = save_url_image(
                    image_url_data, prefix=_cache_prefix(model_id), timeout=30,
                )
                image_ref = str(saved_path)
            except Exception as exc:
                return error_response(
                    error=f"Could not download/save image from URL: {exc}",
                    error_type="io_error",
                    provider="image-hub",
                    model=model_id,
                    prompt=prompt,
                    aspect_ratio=aspect,
                )

        return success_response(
            image=image_ref,
            model=model_id,
            prompt=prompt,
            aspect_ratio=aspect,
            provider="image-hub",
            extra={"size": size_raw},
        )


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------


def register(ctx: Any) -> None:
    """Register this provider with the image gen registry."""
    ctx.register_image_gen_provider(ImageHubProvider())
