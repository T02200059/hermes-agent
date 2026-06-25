"""Runtime patch for the Mixture-of-Agents (MoA) tool.

Replaces the upstream OpenRouter-hardcoded MoA implementation with a
config-driven one that reads ``owner.mixture_of_agents`` from patch.yaml and
routes every model through Hermes' central :func:`resolve_provider_client`.

Why a runtime patch instead of editing ``tools/mixture_of_agents_tool.py``:
  The upstream file lives on ``main`` (PRs #6621 / #1307 / #23940). Editing it
  directly would (a) create a large literal diff that re-conflicts on every
  sync fork and (b) break the two upstream test files
  (``tests/tools/test_mixture_of_agents_tool.py`` and
  ``tests/tools/test_llm_content_none_guard.py``) which reference the
  module-level constants by name. Per ``owner/docs/二次开发规范.md`` §2.1/2.2,
  we keep the upstream source literal-identical and override the *registry
  entry* (handler / check_fn / requires_env) at import time. The upstream
  schema (``MOA_SCHEMA``) is reused unchanged — the LLM still only passes
  ``user_prompt``; model selection is owned by patch.yaml.

Wiring: ``owner.tools.schema_patches`` calls :func:`apply_moa_tool_patch` on
import. ``schema_patches`` is already imported by the three process entry
points (``cli.py``, ``agent/agent_init.py``, ``gateway/run.py``), so no new
wiring is needed.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from agent.auxiliary_client import (
    extract_content_or_reasoning,
    resolve_provider_client,
)
from owner.patch_config import load_patch_config

logger = logging.getLogger(__name__)

# Aggregator system prompt — from the MoA research paper
# (arXiv:2406.04692). Kept identical to the upstream tool so the synthesized
# output quality is unchanged.
_AGGREGATOR_SYSTEM_PROMPT = (
    "You have been provided with a set of responses from various open-source "
    "models to the latest user query. Your task is to synthesize these "
    "responses into a single, high-quality response. It is crucial to "
    "critically evaluate the information provided in these responses, "
    "recognizing that some of it may be biased or incorrect. Your response "
    "should not simply replicate the given answers but should offer a "
    "refined, accurate, and comprehensive reply to the instruction. Ensure "
    "your response is well-structured, coherent, and adheres to the highest "
    "standards of accuracy and reliability.\n\n"
    "Responses from models:"
)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_moa_config() -> Dict[str, Any]:
    """Return the ``owner.mixture_of_agents`` dict from patch.yaml.

    Fail-open: returns ``{}`` if patch.yaml or the section is missing. The
    tool's ``check_fn`` (:func:`check_moa_requirements`) treats an empty dict
    as "unavailable", so the tool simply stays hidden from the agent until the
    owner configures it.
    """
    cfg = load_patch_config()
    moa = cfg.get("mixture_of_agents")
    return moa if isinstance(moa, dict) else {}


def check_moa_requirements() -> bool:
    """Availability gate for the patched MoA tool.

    Replaces the upstream ``OPENROUTER_API_KEY`` check: the tool is available
    iff patch.yaml declares a ``mixture_of_agents`` section with at least one
    reference model and an aggregator model. Per-provider credentials are
    resolved lazily at call time by :func:`resolve_provider_client`, so we do
    not probe them here (matches how the image-gen / approval tools gate).
    """
    cfg = load_moa_config()
    if not cfg:
        return False
    refs = cfg.get("reference_models")
    agg = cfg.get("aggregator_model")
    return (
        isinstance(refs, list)
        and len(refs) >= 1
        and isinstance(agg, dict)
        and bool(agg.get("model"))
        and bool(agg.get("provider"))
    )


# ---------------------------------------------------------------------------
# Provider client helper
# ---------------------------------------------------------------------------

def _get_provider_client(provider: str, model: str):
    """Resolve an async OpenAI-compatible client for ``(provider, model)``.

    Delegates to the central router so auth, base_url, headers, and API-mode
    wrapping (Codex / Anthropic / Gemini native) are handled identically to
    every other auxiliary call. Raises ``ValueError`` if the provider cannot
    be resolved (missing credentials / unknown provider name) so the per-model
    retry loop records a terminal failure for it.
    """
    client, resolved_model = resolve_provider_client(
        provider, model=model, async_mode=True
    )
    if client is None:
        raise ValueError(
            f"Cannot resolve provider client for provider={provider!r} "
            f"model={model!r} (check config.yaml providers / credentials)"
        )
    # Use the provider's own model slug (not OpenRouter's vendor/model form).
    # resolve_provider_client normalizes via normalize_model_for_provider, so
    # resolved_model is already the right string for this endpoint.
    return client, resolved_model or model


def _build_chat_params(
    model: str,
    messages: List[Dict[str, Any]],
    temperature: Optional[float],
    max_tokens: Optional[int],
) -> Dict[str, Any]:
    """Build chat.completions.create kwargs without OpenRouter-specific bits.

    - Drops ``extra_body={"reasoning": {"effort": "xhigh"}}`` — that is an
      OpenRouter-only extension that damodel/deepseek/xiaomi reject.
      Per-model thinking/reasoning toggles are instead controlled via
      ``owner.model_extra_body`` in patch.yaml + owner/extra_body_injection.py,
      which already runs in the chat_completions transport.
    - Per-model temperature comes from patch.yaml (each reference model may
      differ — kimi-k2.7-code is locked to 1.0 by the provider).
    """
    params: Dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if max_tokens is not None:
        params["max_tokens"] = max_tokens
    if temperature is not None:
        params["temperature"] = temperature
    return params


# ---------------------------------------------------------------------------
# Core MoA execution
# ---------------------------------------------------------------------------

async def _run_reference_model_safe(
    model_cfg: Dict[str, Any],
    user_prompt: str,
    max_tokens: int = 32000,
    max_retries: int = 6,
) -> Tuple[str, str, bool]:
    """Run one reference model with retry + graceful-failure handling.

    Returns ``(display_name, content_or_error, success)`` mirroring the
    upstream contract so the orchestrator's result-shaping is unchanged.
    """
    model = str(model_cfg.get("model", "")).strip()
    provider = str(model_cfg.get("provider", "")).strip()
    temperature = model_cfg.get("temperature")
    display = f"{provider}/{model}" if provider else model

    if not model or not provider:
        return display, "missing model/provider in patch.yaml", False

    for attempt in range(max_retries):
        try:
            logger.info(
                "MoA querying %s (attempt %s/%s)", display, attempt + 1, max_retries
            )
            client, resolved_model = _get_provider_client(provider, model)
            params = _build_chat_params(
                resolved_model,
                [{"role": "user", "content": user_prompt}],
                temperature,
                max_tokens,
            )
            response = await client.chat.completions.create(**params)
            content = extract_content_or_reasoning(response)
            if not content:
                # Reasoning-only / empty response — let the retry loop try again
                logger.warning(
                    "%s returned empty content (attempt %s/%s), retrying",
                    display, attempt + 1, max_retries,
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(min(2 ** (attempt + 1), 60))
                    continue
            logger.info("%s responded (%s characters)", display, len(content))
            return display, content, True

        except Exception as e:
            error_str = str(e)
            low = error_str.lower()
            if "invalid" in low:
                logger.warning("%s invalid request error (attempt %s): %s",
                               display, attempt + 1, error_str)
            elif "rate" in low or "limit" in low:
                logger.warning("%s rate limit error (attempt %s): %s",
                               display, attempt + 1, error_str)
            else:
                logger.warning("%s error (attempt %s): %s",
                               display, attempt + 1, error_str)
            if attempt < max_retries - 1:
                sleep_time = min(2 ** (attempt + 1), 60)
                logger.info("Retrying in %ss...", sleep_time)
                await asyncio.sleep(sleep_time)
            else:
                # Terminal failure — full traceback only here (matches upstream
                # discipline: keep retry-path logs concise to avoid log floods).
                err_msg = f"{display} failed after {max_retries} attempts: {error_str}"
                logger.error("%s", err_msg, exc_info=True)
                return display, err_msg, False

    # Should be unreachable (loop returns on success/terminal failure) but keep
    # a defensive return for type safety.
    return display, f"{display} exhausted retries", False


async def _run_aggregator_model(
    agg_cfg: Dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    max_tokens: Optional[int] = None,
) -> str:
    """Run the aggregator model to synthesize the final response."""
    model = str(agg_cfg.get("model", "")).strip()
    provider = str(agg_cfg.get("provider", "")).strip()
    temperature = agg_cfg.get("temperature")
    display = f"{provider}/{model}" if provider else model

    logger.info("MoA running aggregator: %s", display)
    client, resolved_model = _get_provider_client(provider, model)
    params = _build_chat_params(
        resolved_model,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature,
        max_tokens,
    )

    response = await client.chat.completions.create(**params)
    content = extract_content_or_reasoning(response)

    # Retry once on empty content (reasoning-only response), mirroring upstream
    if not content:
        logger.warning("Aggregator %s returned empty content, retrying once", display)
        response = await client.chat.completions.create(**params)
        content = extract_content_or_reasoning(response)

    logger.info("MoA aggregation complete (%s characters)", len(content))
    return content


def _construct_aggregator_prompt(system_prompt: str, responses: List[str]) -> str:
    """Attach enumerated reference responses to the aggregator system prompt."""
    response_text = "\n".join(
        f"{i + 1}. {resp}" for i, resp in enumerate(responses)
    )
    return f"{system_prompt}\n\n{response_text}"


async def mixture_of_agents_tool(user_prompt: str) -> str:
    """Process a complex query using the MoA methodology, config-driven.

    Replaces the upstream OpenRouter-bound implementation. Models, providers,
    temperatures, and retry counts all come from ``owner.mixture_of_agents``
    in patch.yaml.
    """
    start_time = datetime.datetime.now()
    cfg = load_moa_config()

    # Defensive: check_fn should keep us from being dispatched when unset, but
    # a direct call (e.g. __main__ smoke test) can still reach here.
    if not cfg:
        return json.dumps(
            {
                "success": False,
                "response": "MoA not configured: add owner.mixture_of_agents to patch.yaml",
                "error": "missing owner.mixture_of_agents config",
            },
            indent=2,
            ensure_ascii=False,
        )

    ref_cfgs: List[Dict[str, Any]] = list(cfg.get("reference_models") or [])
    agg_cfg: Dict[str, Any] = dict(cfg.get("aggregator_model") or {})
    min_successful = int(cfg.get("min_successful_references", 1) or 1)
    max_retries = int(cfg.get("max_retries", 6) or 6)

    ref_display = [
        f"{c.get('provider', '?')}/{c.get('model', '?')}" for c in ref_cfgs
    ]
    agg_display = f"{agg_cfg.get('provider', '?')}/{agg_cfg.get('model', '?')}"

    try:
        logger.info("Starting Mixture-of-Agents processing (config-driven)...")
        logger.info("Query: %s", user_prompt[:100])
        logger.info(
            "Using %s reference models in 2-layer MoA architecture", len(ref_cfgs)
        )

        # Layer 1: parallel reference responses
        logger.info("Layer 1: Generating reference responses...")
        results = await asyncio.gather(
            *[
                _run_reference_model_safe(
                    c, user_prompt, max_retries=max_retries
                )
                for c in ref_cfgs
            ]
        )

        successful: List[str] = []
        failed: List[str] = []
        for _name, content, ok in results:
            if ok:
                successful.append(content)
            else:
                failed.append(_name)

        logger.info(
            "Reference model results: %s successful, %s failed",
            len(successful), len(failed),
        )
        if failed:
            logger.warning("Failed models: %s", ", ".join(failed))

        if len(successful) < min_successful:
            raise ValueError(
                f"Insufficient successful reference models "
                f"({len(successful)}/{len(ref_cfgs)}). Need at least "
                f"{min_successful} successful responses."
            )

        # Layer 2: aggregate
        logger.info("Layer 2: Synthesizing final response...")
        aggregator_system_prompt = _construct_aggregator_prompt(
            _AGGREGATOR_SYSTEM_PROMPT, successful
        )
        final_response = await _run_aggregator_model(
            agg_cfg, aggregator_system_prompt, user_prompt
        )

        processing_time = (datetime.datetime.now() - start_time).total_seconds()
        logger.info("MoA processing completed in %.2f seconds", processing_time)

        return json.dumps(
            {
                "success": True,
                "response": final_response,
                "models_used": {
                    "reference_models": ref_display,
                    "aggregator_model": agg_display,
                },
            },
            indent=2,
            ensure_ascii=False,
        )

    except Exception as e:
        error_msg = f"Error in MoA processing: {e}"
        logger.error("%s", error_msg, exc_info=True)
        processing_time = (datetime.datetime.now() - start_time).total_seconds()
        return json.dumps(
            {
                "success": False,
                "response": (
                    "MoA processing failed. Please try again or use a single "
                    "model for this query."
                ),
                "models_used": {
                    "reference_models": ref_display,
                    "aggregator_model": agg_display,
                },
                "error": error_msg,
                "processing_time_seconds": processing_time,
            },
            indent=2,
            ensure_ascii=False,
        )


# ---------------------------------------------------------------------------
# Registry patch
# ---------------------------------------------------------------------------

def apply_moa_tool_patch() -> None:
    """Override the registered ``mixture_of_agents`` tool with the config-driven impl.

    Idempotent + fail-open: if the upstream tool module / schema can't be
    imported (e.g. upstream renamed the tool), we log and skip rather than
    crash the process. ``override=True`` is the explicit opt-in that lets us
    replace the existing toolset entry in-place.
    """
    try:
        from tools.registry import registry
        from tools.mixture_of_agents_tool import MOA_SCHEMA
    except Exception as exc:
        logger.debug("MoA tool patch skipped (upstream module unavailable): %s", exc)
        return

    registry.register(
        name="mixture_of_agents",
        toolset="moa",
        schema=MOA_SCHEMA,  # reuse upstream schema — LLM still only passes user_prompt
        handler=lambda args, **kw: mixture_of_agents_tool(
            user_prompt=args.get("user_prompt", "")
        ),
        check_fn=check_moa_requirements,
        requires_env=None,  # was ["OPENROUTER_API_KEY"] upstream — no longer required
        is_async=True,
        emoji="🧠",
        override=True,
    )
    logger.debug("Applied owner MoA tool patch (config-driven, provider-routed)")
