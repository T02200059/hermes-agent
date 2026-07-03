#!/usr/bin/env python3
"""
HN Daily - 每日 Hacker News 技术摘要
- 获取 Top N 新闻
- 生成中文一句话摘要
- 推送飞书卡片 (interactive)
- 本地归档

Usage:
    python3 ~/.hermes/scripts/hn_daily.py
"""

from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# ------------------------------------------------------------------
# Defaults & constants
# ------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent

# Profile-aware HERMES_HOME when running inside the hermes-agent repo.
try:
    from hermes_constants import get_hermes_home  # type: ignore

    _HERMES_HOME: Path = get_hermes_home()
except Exception:  # pragma: no cover - standalone fallback
    _HERMES_HOME = Path.home() / ".hermes"

DEFAULT_CONFIG_DIR = _HERMES_HOME / "hn_daily"

HN_BASE_URL = "https://hacker-news.firebaseio.com/v0"
FEISHU_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_MESSAGE_URL = "https://open.feishu.cn/open-apis/im/v1/messages"
FEISHU_TOKEN_REFRESH_CODES: Tuple[int, ...] = (99991663, 99991661)

DEFAULT_TOP_N = 20
DEFAULT_TIMEOUT_TOP_STORIES = 15
DEFAULT_TIMEOUT_ITEM = 8
DEFAULT_MAX_WORKERS = 8
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_BASE = 2.0
DEFAULT_TOKEN_EXPIRY_BUFFER = 300
DEFAULT_CARD_TEMPLATE = "blue"
DEFAULT_TIMEZONE = "CST"

DEFAULT_CONFIG: Dict[str, Any] = {
    "hn": {"top_n": DEFAULT_TOP_N},
    "http": {
        "top_stories_timeout": DEFAULT_TIMEOUT_TOP_STORIES,
        "item_timeout": DEFAULT_TIMEOUT_ITEM,
        "max_workers": DEFAULT_MAX_WORKERS,
        "retries": DEFAULT_RETRIES,
        "backoff_base": DEFAULT_BACKOFF_BASE,
    },
    "feishu": {
        "token_url": FEISHU_TOKEN_URL,
        "message_url": FEISHU_MESSAGE_URL,
        "token_refresh_codes": list(FEISHU_TOKEN_REFRESH_CODES),
    },
    "card": {
        "template": DEFAULT_CARD_TEMPLATE,
        "timezone": DEFAULT_TIMEZONE,
    },
    "output": {
        "save_dir": str(DEFAULT_CONFIG_DIR / "archive"),
    },
}

CATEGORIES_SEARCH_PATHS = [
    DEFAULT_CONFIG_DIR / "categories.json",
    SCRIPT_DIR / "hn_daily" / "categories.json",
]

USER_AGENT = "hn-daily-bot/1.0 (+https://github.com/NousResearch/hermes-agent)"


# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------

def setup_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger("hn_daily")


logger = setup_logging()


# ------------------------------------------------------------------
# Config helpers
# ------------------------------------------------------------------

def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge override into base."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(
    config_dir: Optional[Path] = None,
    defaults: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Load config from JSON, merge secrets, apply defaults.

    Secrets are expected to be a flat or nested JSON file. Nested sections are
    merged into the matching config section; flat keys are placed at top level.
    """
    cfg = dict(defaults or DEFAULT_CONFIG)
    config_dir = config_dir or DEFAULT_CONFIG_DIR
    config_path = config_dir / "config.json"
    secrets_path = config_dir / ".secrets.json"

    if config_path.exists():
        try:
            user_cfg = json.loads(config_path.read_text(encoding="utf-8"))
            cfg = _deep_merge(cfg, user_cfg)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {config_path}: {exc}") from exc
    else:
        logger.warning("Config file not found, using defaults: %s", config_path)

    if secrets_path.exists():
        try:
            secrets = json.loads(secrets_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {secrets_path}: {exc}") from exc

        for key, value in secrets.items():
            if isinstance(value, dict) and key in cfg and isinstance(cfg[key], dict):
                cfg[key] = _deep_merge(cfg[key], value)
            else:
                cfg[key] = value

    return cfg


def require_feishu_config(cfg: Dict[str, Any]) -> Dict[str, str]:
    """Return validated Feishu config or raise ValueError."""
    feishu = cfg.get("feishu", {})
    app_id = feishu.get("app_id", "")
    app_secret = feishu.get("app_secret", "")
    chat_id = feishu.get("chat_id", "")
    if not app_id or not app_secret or not chat_id:
        raise ValueError("feishu.app_id, feishu.app_secret, and feishu.chat_id are required")
    return {
        "app_id": app_id,
        "app_secret": app_secret,
        "chat_id": chat_id,
        "token_url": feishu.get("token_url", FEISHU_TOKEN_URL),
        "message_url": feishu.get("message_url", FEISHU_MESSAGE_URL),
        "token_refresh_codes": tuple(feishu.get("token_refresh_codes", FEISHU_TOKEN_REFRESH_CODES)),
    }


# ------------------------------------------------------------------
# Category rules
# ------------------------------------------------------------------

@dataclass(frozen=True)
class CategoryRule:
    name: str
    mode: str  # "any" or "all"
    keywords: List[str]
    also_any: List[str]
    template: str

    def matches(self, title_lower: str) -> bool:
        if self.mode == "any":
            return any(_keyword_matches(title_lower, kw) for kw in self.keywords)
        if self.mode == "all":
            if not all(_keyword_matches(title_lower, kw) for kw in self.keywords):
                return False
            if self.also_any:
                return any(_keyword_matches(title_lower, kw) for kw in self.also_any)
            return True
        logger.warning("Unknown rule mode %r for rule %r", self.mode, self.name)
        return False


def _keyword_matches(text: str, keyword: str) -> bool:
    """Case-insensitive substring match.

    The category rules are intentionally broad (e.g. "postgres" should match
    "PostgreSQL"), so we use simple substring matching rather than strict word
    boundaries. Callers list specific enough keywords to keep false positives
    low.
    """
    keyword = keyword.strip().lower()
    if not keyword:
        return False
    return keyword in text.lower()


def load_categories(
    search_paths: Optional[List[Path]] = None,
) -> Tuple[List[CategoryRule], str]:
    """Load category rules from the first available JSON file.

    Returns (rules, default_summary).
    """
    search_paths = search_paths or CATEGORIES_SEARCH_PATHS
    for path in search_paths:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                raw_rules = data.get("rules", [])
                rules = [
                    CategoryRule(
                        name=r.get("name", f"rule_{i}"),
                        mode=r.get("mode", "any"),
                        keywords=[str(k).lower() for k in r.get("keywords", [])],
                        also_any=[str(k).lower() for k in r.get("also_any", [])],
                        template=r.get("template", ""),
                    )
                    for i, r in enumerate(raw_rules)
                ]
                default = data.get("default", "Hacker News 社区讨论的技术话题或工具分享。")
                logger.debug("Loaded %d category rules from %s", len(rules), path)
                return rules, default
            except (json.JSONDecodeError, OSError) as exc:
                raise ValueError(f"Failed to load categories from {path}: {exc}") from exc

    raise FileNotFoundError(
        f"No categories file found. Searched: {', '.join(str(p) for p in search_paths)}"
    )


def generate_summary(title: str, url: str, rules: List[CategoryRule], default: str) -> str:
    """Generate a one-sentence Chinese summary based on category rules."""
    title_lower = title.lower()
    for rule in rules:
        if rule.matches(title_lower):
            return rule.template
    return default


# ------------------------------------------------------------------
# HN data model & fetch
# ------------------------------------------------------------------

@dataclass(frozen=True)
class HNItem:
    id: int
    title: str
    url: str
    score: int
    comments: int
    summary: str

    @classmethod
    def from_raw(cls, raw: Dict[str, Any], rules: List[CategoryRule], default: str) -> Optional[HNItem]:
        item_id = raw.get("id")
        title = raw.get("title", "Unknown")
        if not item_id or not title:
            return None
        url = raw.get("url") or f"https://news.ycombinator.com/item?id={item_id}"
        return cls(
            id=int(item_id),
            title=title,
            url=url,
            score=int(raw.get("score", 0) or 0),
            comments=int(raw.get("descendants", 0) or 0),
            summary=generate_summary(title, url, rules, default),
        )


def _with_retry(
    max_retries: int = DEFAULT_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
    exceptions: Tuple[type, ...] = (requests.RequestException,),
):
    """Decorator that retries a function on transient failures."""
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Optional[Exception] = None
            for attempt in range(max_retries):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_retries - 1:
                        sleep = backoff_base ** attempt
                        logger.warning(
                            "%s failed (attempt %d/%d): %s. Retrying in %.1fs...",
                            fn.__name__, attempt + 1, max_retries, exc, sleep,
                        )
                        time.sleep(sleep)
            raise last_exc or RuntimeError(f"{fn.__name__} failed after {max_retries} attempts")
        return wrapper
    return decorator


@_with_retry()
def _fetch_top_story_ids(
    session: requests.Session,
    base_url: str,
    timeout: int,
) -> List[int]:
    url = f"{base_url}/topstories.json"
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    return [int(i) for i in resp.json()]


def _fetch_item(
    session: requests.Session,
    item_id: int,
    base_url: str,
    timeout: int,
) -> Optional[Dict[str, Any]]:
    url = f"{base_url}/item/{item_id}.json"
    try:
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, json.JSONDecodeError) as exc:
        logger.warning("Failed to fetch item %s: %s", item_id, exc)
        return None


def fetch_top_items(
    session: requests.Session,
    top_n: int,
    base_url: str,
    top_stories_timeout: int,
    item_timeout: int,
    max_workers: int,
    rules: List[CategoryRule],
    default_summary: str,
) -> List[HNItem]:
    """Fetch Top N HN stories and return ordered HNItem list."""
    logger.info("Fetching HN Top %d...", top_n)
    ids = _fetch_top_story_ids(session, base_url, top_stories_timeout)
    ids = ids[:top_n]

    items: List[HNItem] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_item, session, iid, base_url, item_timeout): iid for iid in ids}
        for future in as_completed(futures):
            raw = future.result()
            if raw:
                item = HNItem.from_raw(raw, rules, default_summary)
                if item:
                    items.append(item)

    id_order = {iid: idx for idx, iid in enumerate(ids)}
    items.sort(key=lambda x: id_order.get(x.id, len(ids)))
    logger.info("Fetched %d/%d items", len(items), len(ids))
    return items[:top_n]


# ------------------------------------------------------------------
# Formatting
# ------------------------------------------------------------------

def build_card(
    items: List[HNItem],
    date_str: str,
    template: str = DEFAULT_CARD_TEMPLATE,
    timezone: str = DEFAULT_TIMEZONE,
) -> Dict[str, Any]:
    """Build a Feishu interactive card (schema 2.0)."""
    elements: List[Dict[str, Any]] = []
    for i, item in enumerate(items, 1):
        md_content = (
            f"**{i}. [{item.title}]({item.url})**  \n"
            f"{item.score}↑ {item.comments}💬  ·  {item.summary}"
        )
        elements.append({"tag": "markdown", "content": md_content})
        if i < len(items):
            elements.append({"tag": "hr"})

    elements.append({"tag": "hr"})
    elements.append({
        "tag": "markdown",
        "content": (
            f"\n*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M %Z')} "
            f"· 来源: [Hacker News](https://news.ycombinator.com)*"
        ).replace("%Z", timezone),
    })

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "content": f"📰 Hacker News 每日技术摘要 | {date_str}",
                "tag": "plain_text",
            },
            "template": template,
        },
        "body": {"elements": elements},
    }


def build_markdown(
    items: List[HNItem],
    date_str: str,
    top_n: int,
    timezone: str = DEFAULT_TIMEZONE,
) -> str:
    """Build markdown archive content."""
    lines = [
        f"# Hacker News 每日技术摘要 | {date_str}",
        f"> 来源: news.ycombinator.com | Top {top_n} 精选\n",
    ]
    for i, item in enumerate(items, 1):
        lines.append(f"{i:2d}. [{item.title}]({item.url})")
        lines.append(f"    {item.score}↑ {item.comments}💬  · {item.summary}")
    lines.append(
        f"\n---\n生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M %Z')}".replace("%Z", timezone)
    )
    return "\n".join(lines)


# ------------------------------------------------------------------
# Feishu push
# ------------------------------------------------------------------

class FeishuAPIError(Exception):
    """Raised when Feishu API returns an error."""

    def __init__(self, message: str, code: Optional[int] = None):
        super().__init__(message)
        self.code = code


class TokenManager:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        token_url: str,
        session: requests.Session,
        expiry_buffer: int = DEFAULT_TOKEN_EXPIRY_BUFFER,
    ):
        if not app_id or not app_secret:
            raise ValueError("app_id and app_secret are required")
        self.app_id = app_id
        self.app_secret = app_secret
        self.token_url = token_url
        self.session = session
        self.expiry_buffer = expiry_buffer
        self._token: Optional[str] = None
        self._expire: float = 0.0

    @_with_retry()
    def get(self) -> str:
        now = time.time()
        if self._token and self._expire > now + self.expiry_buffer:
            return self._token

        resp = self.session.post(
            self.token_url,
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()

        if result.get("code") != 0:
            raise FeishuAPIError(
                f"Token request failed: {result}", code=result.get("code")
            )

        token = result.get("tenant_access_token")
        if not token:
            raise FeishuAPIError("No tenant_access_token in response")

        self._token = token
        expire = result.get("expire")
        if not isinstance(expire, (int, float)) or expire <= 0:
            raise FeishuAPIError(f"Invalid expire value: {expire!r}")
        self._expire = now + int(expire)
        return token

    def invalidate(self) -> None:
        self._token = None
        self._expire = 0.0


@_with_retry()
def _push_once(
    session: requests.Session,
    message_url: str,
    card: Dict[str, Any],
    chat_id: str,
    token: str,
) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    params = {"receive_id_type": "chat_id"}
    body = {
        "receive_id": chat_id,
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False),
    }
    resp = session.post(message_url, params=params, json=body, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def push_feishu_card(
    session: requests.Session,
    card: Dict[str, Any],
    cfg: Dict[str, Any],
) -> bool:
    """Push card to Feishu with token refresh on auth errors."""
    feishu = require_feishu_config(cfg)
    tm = TokenManager(
        app_id=feishu["app_id"],
        app_secret=feishu["app_secret"],
        token_url=feishu["token_url"],
        session=session,
    )

    token = tm.get()
    refresh_codes = feishu["token_refresh_codes"]

    try:
        result = _push_once(session, feishu["message_url"], card, feishu["chat_id"], token)
        if result.get("code") == 0:
            logger.info("Feishu card push success")
            return True

        if result.get("code") in refresh_codes:
            logger.warning("Feishu token expired, refreshing...")
            tm.invalidate()
            token = tm.get()
            result = _push_once(session, feishu["message_url"], card, feishu["chat_id"], token)
            if result.get("code") == 0:
                logger.info("Feishu card push success after token refresh")
                return True

        logger.error("Feishu push failed: %s", result)
    except (requests.RequestException, FeishuAPIError) as exc:
        logger.error("Feishu push error: %s", exc)

    return False


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def save_archive(content: str, save_dir: Path, date_str: str) -> Path:
    save_dir = save_dir.expanduser().resolve()
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / f"hn_{date_str}.md"
    save_path.write_text(content, encoding="utf-8")
    return save_path


def main() -> bool:
    logger.info("Starting HN Daily")

    cfg = load_config()
    top_n = int(cfg.get("hn", {}).get("top_n", DEFAULT_TOP_N))
    http_cfg = cfg.get("http", {})
    card_cfg = cfg.get("card", {})
    output_cfg = cfg.get("output", {})

    rules, default_summary = load_categories()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    # 1. Fetch
    items = fetch_top_items(
        session=session,
        top_n=top_n,
        base_url=cfg.get("hn", {}).get("base_url", HN_BASE_URL),
        top_stories_timeout=int(http_cfg.get("top_stories_timeout", DEFAULT_TIMEOUT_TOP_STORIES)),
        item_timeout=int(http_cfg.get("item_timeout", DEFAULT_TIMEOUT_ITEM)),
        max_workers=int(http_cfg.get("max_workers", DEFAULT_MAX_WORKERS)),
        rules=rules,
        default_summary=default_summary,
    )
    if not items:
        logger.error("No items fetched, abort.")
        return False

    # 2. Build outputs
    date_str = datetime.now().strftime("%Y-%m-%d")
    card = build_card(
        items,
        date_str,
        template=card_cfg.get("template", DEFAULT_CARD_TEMPLATE),
        timezone=card_cfg.get("timezone", DEFAULT_TIMEZONE),
    )
    markdown = build_markdown(
        items,
        date_str,
        top_n=top_n,
        timezone=card_cfg.get("timezone", DEFAULT_TIMEZONE),
    )

    # 3. Save locally
    save_dir = Path(output_cfg.get("save_dir", str(DEFAULT_CONFIG_DIR / "archive")))
    save_path = save_archive(markdown, save_dir, date_str)
    logger.info("Saved archive: %s", save_path)

    # 4. Push Feishu
    ok = push_feishu_card(session, card, cfg)
    if ok:
        logger.info("Done.")
    else:
        logger.warning("Card push failed, content saved locally.")

    return ok


if __name__ == "__main__":
    try:
        ok = main()
    except Exception as exc:
        logger.exception("HN Daily failed: %s", exc)
        sys.exit(1)
    sys.exit(0 if ok else 1)
