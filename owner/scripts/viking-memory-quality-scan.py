#!/usr/bin/env python3
"""
OpenViking Memory Quality Scanner + Auto-Fixer
================================================
Tier 1: Objective, knowledge-free quality checks.
  - Detects non-Chinese (PT/ES/IT/FR/DE) memory files via stopword density
  - Translates to zh-CN via LLM API
  - Writes back via OpenViking content/write API
  - Outputs JSON summary (empty = silent, non-empty = report)

Designed for cron no_agent=True: stdout is the report.
Silent when no issues found.

Usage:
  python3 viking-memory-quality-scan.py [--dry-run] [--verbose]
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from typing import Dict, List, Optional, Tuple

import requests

# ============================================================
# Configuration
# ============================================================

# OpenViking API
OV_API = os.environ.get("OV_API", "http://127.0.0.1:1933")
OV_ROOT_KEY = os.environ.get("OV_ROOT_KEY", "")
OV_USER_ID = os.environ.get("OV_USER_ID", "yangtb")

# LLM API for translation (volcengine ark, OpenAI-compatible)
LLM_API_BASE = os.environ.get("LLM_API_BASE", "https://ark.cn-beijing.volces.com/api/coding/v3")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "ark-code-latest")

# Scan settings
MEMORY_BASE = f"viking://user/{OV_USER_ID}/memories/"
EXCLUDE_DIRS = {"events", "peers"}
MIN_STOPWORD_HITS = 3
MIN_DENSITY = 0.10

# Retry settings
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # seconds
REQUEST_TIMEOUT = 30  # seconds

# Logging
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, stream=sys.stderr)
logger = logging.getLogger("viking-mq")

# ============================================================
# Stopword tables (from OpenViking language.py)
# ============================================================

LATIN_STOPWORDS: Dict[str, set] = {
    "pt": set(
        "a as com da de do documento e este esta o os para "
        "preferências preferencias projeto que um uma usuário usuario".split()
    ),
    "es": set(
        "con de del documento el esta este la las los para "
        "preferencias proyecto que un una usuario y".split()
    ),
    "it": set(
        "che con da del della di documento e il la le non per "
        "preferenze progetto questo questa un una utente".split()
    ),
    "fr": set(
        "avec ce cette de des document du et la le les pour "
        "préférences projet que un une utilisateur".split()
    ),
    "de": set(
        "benutzer das der die diese dieser dokument ein eine "
        "für ist mit nicht projekt und zu".split()
    ),
}

LATIN_ACCENT_PATTERNS: Dict[str, re.Pattern] = {
    "pt": re.compile(r"[áâãàçéêíóôõú]"),
    "es": re.compile(r"[áéíóúüñ¿¡]"),
    "it": re.compile(r"[àèéìòù]"),
    "fr": re.compile(r"[àâæçéèêëîïôœùûüÿ]"),
    "de": re.compile(r"[äöüß]"),
}


# ============================================================
# Language Detection
# ============================================================

def detect_non_chinese(text: str) -> Optional[Dict]:
    """Detect if text is non-Chinese based on Latin stopword density.

    Returns dict with language/score/density if non-Chinese detected, else None.
    """
    words = re.findall(r"[a-z\u00c0-\u024f]+", text.lower())
    if len(words) < 3:
        return None

    scores: Dict[str, int] = {}
    for lang, stopwords in LATIN_STOPWORDS.items():
        hits = sum(1 for w in words if w in stopwords)
        accent_bonus = len(LATIN_ACCENT_PATTERNS[lang].findall(text.lower()))
        scores[lang] = hits + accent_bonus

    zh_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    total_signal = zh_chars + len(re.findall(r"[A-Za-z\u00c0-\u024f]", text))

    best_lang, best_score = max(scores.items(), key=lambda x: x[1])

    if best_score < MIN_STOPWORD_HITS:
        return None

    density = best_score / max(len(words), 1)
    if density < MIN_DENSITY:
        return None

    return {
        "language": best_lang,
        "stopword_hits": best_score,
        "density": round(density, 3),
        "zh_ratio": round(zh_chars / max(total_signal, 1), 3),
        "word_count": len(words),
    }


# ============================================================
# OpenViking API Client (with retry)
# ============================================================

class OVClient:
    """OpenViking API client with retry and auto user-key resolution."""

    def __init__(self, api: str, root_key: str, user_id: str):
        self.api = api.rstrip("/")
        self.root_key = root_key
        self.user_id = user_id
        self._user_key: Optional[str] = None
        self._session = requests.Session()

    def _get_user_key(self) -> str:
        """Resolve user-scoped API key via admin endpoint."""
        if self._user_key:
            return self._user_key

        headers = {"Authorization": f"Bearer {self.root_key}"}
        for attempt in range(MAX_RETRIES):
            try:
                resp = self._session.get(
                    f"{self.api}/api/v1/admin/accounts/default/users",
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                )
                if resp.status_code == 200:
                    users = resp.json().get("result", [])
                    for u in users:
                        if u.get("user_id") == self.user_id:
                            key = u.get("api_key", "")
                            if key:
                                self._user_key = key
                                return key
                    # User not found, try to register
                    logger.warning(f"User '{self.user_id}' not found, attempting registration")
                    resp = self._session.post(
                        f"{self.api}/api/v1/admin/accounts/default/users",
                        headers={**headers, "Content-Type": "application/json"},
                        json={"user_id": self.user_id, "role": "admin"},
                        timeout=REQUEST_TIMEOUT,
                    )
                    if resp.status_code == 200:
                        result = resp.json().get("result", {})
                        key = result.get("user_key", "")
                        if key:
                            self._user_key = key
                            return key
                    logger.error(f"Failed to register user: {resp.status_code} {resp.text[:200]}")
                else:
                    logger.warning(f"List users attempt {attempt+1}: {resp.status_code}")
            except requests.RequestException as e:
                logger.warning(f"List users attempt {attempt+1} error: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BASE_DELAY * (2 ** attempt))

        raise RuntimeError(f"Failed to resolve user API key for '{self.user_id}'")

    @property
    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_user_key()}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        """Make API request with retry."""
        url = f"{self.api}{path}"
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        last_exc = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = self._session.request(method, url, headers=self.headers, **kwargs)
                if resp.status_code in (429, 502, 503, 504):
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(f"{method} {path} got {resp.status_code}, retry {attempt+1}/{MAX_RETRIES} in {delay}s")
                    time.sleep(delay)
                    continue
                return resp
            except requests.RequestException as e:
                last_exc = e
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(f"{method} {path} error: {e}, retry {attempt+1}/{MAX_RETRIES} in {delay}s")
                time.sleep(delay)
        if last_exc:
            raise last_exc
        raise RuntimeError(f"Exhausted retries for {method} {path}")

    def ls(self, uri: str) -> List[dict]:
        resp = self._request("GET", "/api/v1/fs/ls", params={"uri": uri})
        if resp.status_code != 200:
            logger.error(f"ls {uri}: {resp.status_code} {resp.text[:200]}")
            return []
        return resp.json().get("result", [])

    def read_content(self, uri: str) -> str:
        resp = self._request("GET", "/api/v1/content/read", params={"uri": uri})
        if resp.status_code != 200:
            logger.error(f"read {uri}: {resp.status_code} {resp.text[:200]}")
            return ""
        result = resp.json().get("result", "")
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            return result.get("content", "")
        return str(result)

    def write_content(self, uri: str, content: str) -> bool:
        resp = self._request("POST", "/api/v1/content/write", json={"uri": uri, "content": content})
        if resp.status_code != 200:
            logger.error(f"write {uri}: {resp.status_code} {resp.text[:200]}")
            return False
        data = resp.json()
        return data.get("status") == "ok"

    def collect_memory_uris(self, base_path: str) -> List[Tuple[str, str]]:
        """Recursively collect all memory file URIs, excluding events/ and peers/."""
        result: List[Tuple[str, str]] = []

        def _walk(path: str):
            entries = self.ls(path)
            for entry in entries:
                uri = entry.get("uri", "")
                is_dir = entry.get("isDir", False)
                name = uri.rstrip("/").split("/")[-1]

                if is_dir:
                    if name in EXCLUDE_DIRS:
                        continue
                    _walk(uri)
                elif not name.startswith("."):
                    rel = uri.replace(f"viking://user/{self.user_id}/memories/", "")
                    # Double-check exclusion
                    parts = rel.split("/")
                    if any(p in EXCLUDE_DIRS for p in parts):
                        continue
                    result.append((rel, uri))

        _walk(base_path)
        return result


# ============================================================
# LLM Translation Client (with retry)
# ============================================================

class LLMTranslator:
    """OpenAI-compatible LLM client for translation."""

    def __init__(self, api_base: str, api_key: str, model: str):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._session = requests.Session()

    def translate(self, content: str, source_lang: str) -> Optional[str]:
        """Translate memory content to zh-CN, preserving markdown structure."""
        prompt = f"""You are a memory content translator. Translate the following memory content from {source_lang} to Chinese (zh-CN).

Rules:
- Preserve ALL markdown formatting: headings (##), bullets (-), code blocks (```), inline code (`).
- Preserve ALL technical terms: tool names, file paths, IP addresses, variable names, function names.
- Preserve ALL structural elements: ## Situation, ## Approach, ## Reflect, etc.
- Only translate natural language text.
- Keep the translation concise and professional.
- Do NOT add any explanation, commentary, or notes.
- Output ONLY the translated content, nothing else.

Content to translate:

{content}"""

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a precise translator for AI agent memory content. Output only the translation."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "max_tokens": 8192,
        }

        last_exc = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = self._session.post(
                    f"{self.api_base}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=120,
                )
                if resp.status_code == 429:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(f"LLM rate limited, retry {attempt+1}/{MAX_RETRIES} in {delay}s")
                    time.sleep(delay)
                    continue
                if resp.status_code != 200:
                    logger.error(f"LLM API {resp.status_code}: {resp.text[:300]}")
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                    continue

                data = resp.json()
                translated = data["choices"][0]["message"]["content"].strip()

                # Sanity check: translated content should not be empty
                if not translated:
                    logger.error("LLM returned empty translation")
                    continue

                # Sanity check: translated content should have Chinese characters
                if not re.search(r"[\u4e00-\u9fff]", translated):
                    logger.warning(f"Translation has no Chinese characters, may have failed")
                    # Still return it - the content might be mostly code/paths

                return translated

            except (requests.RequestException, KeyError, IndexError) as e:
                last_exc = e
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(f"LLM translate error: {e}, retry {attempt+1}/{MAX_RETRIES} in {delay}s")
                time.sleep(delay)

        if last_exc:
            logger.error(f"Translation failed after {MAX_RETRIES} retries: {last_exc}")
        return None


# ============================================================
# Main Scanner + Fixer
# ============================================================

def scan_and_fix(dry_run: bool = False, verbose: bool = False) -> dict:
    """Main entry: scan all memories, detect non-Chinese, translate and fix.

    Returns summary dict.
    """
    if verbose:
        logger.setLevel(logging.DEBUG)

    summary = {
        "scanned": 0,
        "flagged": 0,
        "translated": 0,
        "errors": 0,
        "details": [],
    }

    # Initialize clients
    try:
        ov = OVClient(OV_API, OV_ROOT_KEY, OV_USER_ID)
        translator = LLMTranslator(LLM_API_BASE, LLM_API_KEY, LLM_MODEL)
    except Exception as e:
        logger.error(f"Failed to initialize clients: {e}")
        summary["errors"] = 1
        summary["details"].append({"error": f"Init failed: {e}"})
        return summary

    # Collect all memory URIs
    logger.info(f"Collecting memory URIs from {MEMORY_BASE} ...")
    all_uris = ov.collect_memory_uris(MEMORY_BASE)
    summary["scanned"] = len(all_uris)
    logger.info(f"Found {len(all_uris)} memory files (excl events/peers)")

    if not all_uris:
        logger.info("No memory files found, exiting")
        return summary

    # Scan each file
    flagged: List[dict] = []
    for rel, uri in all_uris:
        try:
            content = ov.read_content(uri)
            if not content or len(content) < 10:
                continue

            detection = detect_non_chinese(content)
            if detection:
                flagged.append({
                    "path": rel,
                    "uri": uri,
                    "detection": detection,
                    "content": content,
                })
                logger.info(
                    f"FLAGGED: {rel} | lang={detection['language']} "
                    f"density={detection['density']} zh_ratio={detection['zh_ratio']}"
                )
        except Exception as e:
            logger.error(f"Error scanning {rel}: {e}")
            summary["errors"] += 1

    summary["flagged"] = len(flagged)
    logger.info(f"Flagged: {len(flagged)} non-Chinese files")

    if not flagged:
        logger.info("No issues found, exiting silently")
        return summary

    if dry_run:
        logger.info("Dry run mode, skipping translation")
        for f in flagged:
            summary["details"].append({
                "path": f["path"],
                "uri": f["uri"],
                "action": "would_translate",
                "language": f["detection"]["language"],
                "density": f["detection"]["density"],
            })
        return summary

    # Translate and fix each flagged file
    for f in flagged:
        rel = f["path"]
        uri = f["uri"]
        content = f["content"]
        lang = f["detection"]["language"]

        logger.info(f"Translating {rel} ({lang}) ...")

        # Skip if content is too short (likely already corrupted/placeholder)
        if len(content) < 20:
            logger.warning(f"Skipping {rel}: content too short ({len(content)} chars), likely corrupted")
            summary["errors"] += 1
            summary["details"].append({
                "path": rel,
                "uri": uri,
                "action": "skipped",
                "reason": f"content too short ({len(content)} chars)",
                "language": lang,
            })
            continue

        translated = translator.translate(content, lang)
        if not translated:
            logger.error(f"Translation failed for {rel}")
            summary["errors"] += 1
            summary["details"].append({
                "path": rel,
                "uri": uri,
                "action": "translation_failed",
                "language": lang,
            })
            continue

        # Write back
        success = ov.write_content(uri, translated)
        if success:
            summary["translated"] += 1
            summary["details"].append({
                "path": rel,
                "uri": uri,
                "action": "translated",
                "language": lang,
                "density": f["detection"]["density"],
                "original_length": len(content),
                "translated_length": len(translated),
            })
            logger.info(f"OK: {rel} translated and written ({len(content)} -> {len(translated)} chars)")
        else:
            summary["errors"] += 1
            summary["details"].append({
                "path": rel,
                "uri": uri,
                "action": "write_failed",
                "language": lang,
            })
            logger.error(f"Write failed for {rel}")

    return summary


# ============================================================
# CLI Entry
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="OpenViking Memory Quality Scanner")
    parser.add_argument("--dry-run", action="store_true", help="Scan only, no translation")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    args = parser.parse_args()

    summary = scan_and_fix(dry_run=args.dry_run, verbose=args.verbose)

    # Output: JSON to stdout (for cron), human-readable to stderr
    if args.json or not sys.stdin.isatty():
        # In cron context (no tty), output JSON to stdout
        if summary["flagged"] > 0 or summary["errors"] > 0:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        # Silent when no issues
    else:
        # Interactive: human readable
        print(f"\n=== Viking Memory Quality Scan ===")
        print(f"Scanned: {summary['scanned']}")
        print(f"Flagged: {summary['flagged']}")
        print(f"Translated: {summary['translated']}")
        print(f"Errors: {summary['errors']}")
        if summary["details"]:
            print("\nDetails:")
            for d in summary["details"]:
                print(f"  {d}")


if __name__ == "__main__":
    main()
