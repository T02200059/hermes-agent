"""C05 fleet_add：开户计划（O1）/ overlay（O2）/ 宿主机种子+compose（O3）/ up+health（O4）。

设计见 ``owner/docs/design/c05-feishu-user-routing/fleet-add.md`` §5 O1–O4。

主键 = LDAP uid（与主稿 ``fleet_profiles.<ldap_uid>`` 对齐）。
生产 node010 现网路由键仍可能是全名（如 ``yangtianbao``）；切 uid 属另开 Ops。

- **O1** ``plan_fleet_add``：零落盘计划（含三层 compose 草稿与宿主机命令清单）。
- **O2** ``apply_fleet_add``：写 overlay 人卡 + ``user_profile_routes``、目标/Hub
  ``FEISHU_ALLOWED_USERS``、目标 ``FEISHU_HOME_CHANNEL`` / ``platforms.feishu.home_channel``；
  可选备份与回滚说明。**不** compose up、**不** useradd。
- **O3** ``apply_fleet_add_host``：种子 ``profiles/<uid>`` 目录、写三层挂载 compose 文件；
  ``useradd`` 仅在 Linux + ``run_useradd=True`` 时执行，否则 dry 列出 / Darwin 标
  ``unsupported``。**不** ``docker compose up``（属 O4）。
- **O4** ``apply_fleet_add_up``：``docker compose up -d`` + 探活 ``api_server.url``；
  可注入 ``compose_runner`` / ``health_get``（单测 mock，不依赖真 Docker）；
  失败返回结构化错误 + 回滚（compose stop/down）文案。默认 dry 只列命令。
- 默认拒绝写 ``/data/hermes`` 生产路径，除非 ``allow_production=True``。

复用 ``owner.feishu.profile_routing`` 的人卡 / endpoint 解析，不重写加载语义。
"""

from __future__ import annotations

import copy
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Optional, Sequence

from owner.feishu.profile_routing import (
    _endpoint_from_api_server,
    _hub_only_flags,
)

# 现网舰队 API 端口段（见 c05b / fleet-add 设计）
DEFAULT_PORT_BASE = 26026
DEFAULT_PORT_CEILING = 26099
DEFAULT_CODE_DIR = "/data/hermes/hermes-agent"
DEFAULT_VENV_DIR = "/data/hermes/venv-docker"
DEFAULT_HERMES_ROOT = "/data/hermes"
DEFAULT_HUB_HOME = "/data/hermes"  # Hub HERMES_HOME；.env 在此下
DEFAULT_CODE_CONTAINER = "/opt/hermes-agent"
DEFAULT_VENV_CONTAINER = "/opt/venv"
DEFAULT_COMPOSE_IMAGE = "hermes-profile:latest"
DEFAULT_COMPOSE_FILENAME = "docker-compose.fleet-{uid}.yml"

_PORT_IN_URL = re.compile(r":(\d+)(?:/|$)")

# 输出中永不回显真实 api_key
_REDACTED_KEY = "<redacted-reuse-shared-fleet-key>"


class FleetAddError(ValueError):
    """开户计划校验失败（已存在 / 缺字段等）。"""


def default_hermes_dir(ldap_uid: str, hermes_root: str = DEFAULT_HERMES_ROOT) -> str:
    return f"{hermes_root.rstrip('/')}/profiles/{ldap_uid}"


def default_home_dir(ldap_uid: str) -> str:
    return f"/home/{ldap_uid}"


def extract_ports_from_fleet(fleet_profiles: Mapping[str, Any]) -> list[int]:
    """从人卡 ``api_server.url`` 抽出已用端口。"""
    ports: list[int] = []
    for card in fleet_profiles.values():
        if not isinstance(card, dict):
            continue
        ep = _endpoint_from_api_server(card.get("api_server"))
        if not ep:
            continue
        m = _PORT_IN_URL.search(ep["url"])
        if m:
            ports.append(int(m.group(1)))
    return ports


def allocate_port(
    used_ports: Sequence[int],
    *,
    preferred: Optional[int] = None,
    port_base: int = DEFAULT_PORT_BASE,
    port_ceiling: int = DEFAULT_PORT_CEILING,
) -> int:
    """取 ``max(used)+1``；空表则 ``port_base``。跳号不回填（与设计一致）。"""
    if preferred is not None:
        if preferred in used_ports:
            raise FleetAddError(f"端口 {preferred} 已被占用: {sorted(used_ports)}")
        if preferred < port_base or preferred > port_ceiling:
            raise FleetAddError(
                f"端口 {preferred} 不在舰队段 [{port_base}, {port_ceiling}]"
            )
        return preferred
    used = [p for p in used_ports if port_base <= p <= port_ceiling]
    if not used:
        return port_base
    nxt = max(used) + 1
    if nxt > port_ceiling:
        raise FleetAddError(
            f"舰队端口段已满（max={max(used)}，ceiling={port_ceiling}）"
        )
    return nxt


def find_shared_api_key_source(
    fleet_profiles: Mapping[str, Any],
) -> tuple[Optional[str], Optional[str]]:
    """返回 ``(source_uid, api_key_or_None)``；调用方输出须 redact key。"""
    for uid, card in fleet_profiles.items():
        if not isinstance(card, dict):
            continue
        ep = _endpoint_from_api_server(card.get("api_server"))
        if ep and ep.get("api_key"):
            return str(uid), ep["api_key"]
    return None, None


def pick_user_routing(
    overlay: Mapping[str, Any],
    *,
    app_id: str = "",
) -> dict[str, Any]:
    """从 overlay 取 ``feishu.bots.<app_id>.user_routing``；无 bots 则扁平回落。"""
    feishu = overlay.get("feishu")
    if not isinstance(feishu, dict):
        return {}
    bots = feishu.get("bots")
    if isinstance(bots, dict) and bots:
        if not app_id:
            # 单 bot 时宽容取第一个，便于夹具；多 bot 须显式 app_id
            if len(bots) == 1:
                only = next(iter(bots.values()))
                if isinstance(only, dict):
                    ur = only.get("user_routing")
                    return ur if isinstance(ur, dict) else {}
            return {}
        bot = bots.get(app_id)
        if not isinstance(bot, dict):
            return {}
        ur = bot.get("user_routing")
        return ur if isinstance(ur, dict) else {}
    ur = feishu.get("user_routing")
    return ur if isinstance(ur, dict) else {}


def pick_fleet_profiles(overlay: Mapping[str, Any]) -> dict[str, Any]:
    fp = overlay.get("fleet_profiles")
    return dict(fp) if isinstance(fp, dict) else {}


def _normalize_ids(values: Sequence[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for v in values or ():
        s = str(v or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def build_person_card(
    *,
    ldap_uid: str,
    display_name: str,
    port: int,
    api_key_placeholder: str,
    hermes_dir: Optional[str] = None,
    home_dir: Optional[str] = None,
    hub_only_feishu: bool = False,
    hub_only_api: bool = False,
    hermes_root: str = DEFAULT_HERMES_ROOT,
) -> dict[str, Any]:
    """目标态人卡草稿（写入计划；O1 不落盘）。"""
    docker: dict[str, str] = {
        "hermes_dir": hermes_dir or default_hermes_dir(ldap_uid, hermes_root),
        "home_dir": home_dir or default_home_dir(ldap_uid),
    }
    card: dict[str, Any] = {
        "display_name": display_name,
        "ldap": {"uid": ldap_uid},
        "docker": docker,
        "api_server": {
            "url": f"http://127.0.0.1:{port}",
            "api_key": api_key_placeholder,
        },
        "hub_only": {
            "feishu": bool(hub_only_feishu),
            "api": bool(hub_only_api),
        },
    }
    return card


def build_compose_service_draft(
    *,
    ldap_uid: str,
    port: int,
    hermes_dir: str,
    home_dir: str,
    code_dir: str = DEFAULT_CODE_DIR,
    venv_dir: str = DEFAULT_VENV_DIR,
    image: str = DEFAULT_COMPOSE_IMAGE,
) -> dict[str, Any]:
    """目标态 compose 服务草稿：代码/venv RO + home→/root + profiles→/root/.hermes。

    挂载顺序：先 home 再 ``.hermes``，确保 profile 叠在 home 之上。
    **禁止**仅 ``/home/<name>:/root`` 单挂。
    """
    service_name = f"hermes-{ldap_uid}"
    volumes = [
        f"{code_dir}:{DEFAULT_CODE_CONTAINER}:ro",
        f"{venv_dir}:{DEFAULT_VENV_CONTAINER}:ro",
        f"{home_dir}:/root",
        f"{hermes_dir}:/root/.hermes",
    ]
    return {
        "service": service_name,
        "container_name": service_name,
        "image": image,
        "network_mode": "host",
        "ports": [f"127.0.0.1:{port}:{port}"],
        "environment": {
            "HERMES_HOME": "/root/.hermes",
            "HERMES_PROFILE": ldap_uid,
            "FEISHU_CONNECTION_MODE": "send_only",
            # 注：生产 node010 现网 HERMES_PROFILE / 路由键仍可能是全名；
            # 切 LDAP uid 另开 Ops，勿在 O1 改生产。
        },
        "volumes": volumes,
        "notes": [
            "三层挂载：代码/venv RO 共用 + home→/root + profiles→/root/.hermes（.hermes 叠在 home 上）",
            "禁止照抄现网「只挂 /home」单挂模板",
            "O3 只生成草稿/写文件；docker compose up 属 O4",
        ],
    }


def render_compose_yaml(
    draft: Mapping[str, Any],
    *,
    compose_project_comment: str = "",
) -> str:
    """把 ``build_compose_service_draft`` 结果渲成可落盘的 compose YAML（单服务）。

    不执行 docker；不含密钥。``network_mode: host`` 时仍保留 ports 注释供对照。
    """
    import yaml

    svc_name = str(draft.get("service") or "hermes-unknown")
    env = draft.get("environment") or {}
    if not isinstance(env, dict):
        raise FleetAddError("compose.environment 非法")
    volumes = list(draft.get("volumes") or [])
    # 守卫：必须同时有 /root 与 /root/.hermes，且禁止「仅单挂 home」
    has_root = any(str(v).rstrip().endswith(":/root") for v in volumes)
    has_hermes = any("/root/.hermes" in str(v) for v in volumes)
    has_ro_code = any(":ro" in str(v) for v in volumes)
    if not (has_root and has_hermes and has_ro_code):
        raise FleetAddError(
            "compose 必须含三层：代码/venv RO + home→/root + profiles→/root/.hermes"
        )
    # 仅 home→/root、无 profiles 叠挂 → 拒绝
    if has_root and not has_hermes:
        raise FleetAddError("禁止只挂 /home → /root 的单挂模板")

    service_body: dict[str, Any] = {
        "image": draft.get("image") or DEFAULT_COMPOSE_IMAGE,
        "container_name": draft.get("container_name") or svc_name,
        "network_mode": draft.get("network_mode") or "host",
        "environment": {str(k): str(v) for k, v in env.items()},
        "volumes": volumes,
        "restart": "unless-stopped",
    }
    doc: dict[str, Any] = {
        "services": {
            svc_name: service_body,
        }
    }
    header_lines = [
        "# Generated by owner/scripts/fleet_add (O3). 勿手改密钥进仓。",
        "# 三层挂载：代码/venv RO + home→/root + profiles→/root/.hermes",
        "# 禁止现网单挂 /home/<name>:/root。docker compose up 属 O4。",
    ]
    if compose_project_comment:
        header_lines.append(f"# {compose_project_comment}")
    ports = draft.get("ports") or []
    if ports and service_body.get("network_mode") == "host":
        header_lines.append(
            f"# network_mode=host：宿主机直绑端口；对照 ports={ports}"
        )
    body = yaml.safe_dump(
        doc,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    return "\n".join(header_lines) + "\n" + body


def build_seed_plan(
    *,
    ldap_uid: str,
    hermes_dir: str,
    home_dir: str,
    compose_file: str,
    port: int,
) -> dict[str, Any]:
    """O3 种子计划：profiles 目录骨架 + 可选最小 config/.env（无真密钥）。"""
    hermes = hermes_dir.rstrip("/")
    home = home_dir.rstrip("/")
    return {
        "ldap_uid": ldap_uid,
        "directories": [
            hermes,
            f"{hermes}/memories",
            f"{hermes}/logs",
            f"{home}",
        ],
        "files": [
            {
                "path": f"{hermes}/config.yaml",
                "kind": "minimal_config",
                "action": "create_if_missing",
                "note": "最小骨架；无 API/飞书密钥。home_channel 由 O2 写入。",
            },
            {
                "path": f"{hermes}/.env",
                "kind": "dotenv_stub",
                "action": "create_if_missing",
                "note": (
                    "仅占位注释；FEISHU_* 由 O2 apply 写入。"
                    "禁止把真实密钥写进仓内模板。"
                ),
            },
            {
                "path": compose_file,
                "kind": "compose_yaml",
                "action": "write",
                "note": "三层挂载 compose；up 属 O4",
            },
        ],
        "host_commands": [
            {
                "step": "useradd",
                "cmd": (
                    f"id {ldap_uid} >/dev/null 2>&1 || "
                    f"useradd -m -d {home} -s /bin/bash {ldap_uid}"
                ),
                "phase": "O3",
                "requires": "linux+run_useradd",
            },
            {
                "step": "mkdir_home",
                "cmd": f"mkdir -p {home}",
                "phase": "O3",
            },
            {
                "step": "mkdir_profile",
                "cmd": f"mkdir -p {hermes}/memories {hermes}/logs",
                "phase": "O3",
            },
        ],
        "port": port,
        "notes": [
            "增量新人种子；存量 /home/.../.hermes → profiles/ rsync 另开 Ops",
            "Mac 无 useradd：apply-host 标 unsupported，只写目录+compose",
        ],
    }


def minimal_profile_config_yaml() -> str:
    """无密钥的最小 config.yaml 种子。"""
    return (
        "# fleet_add O3 最小种子（无密钥）\n"
        "model:\n"
        "  default: null\n"
        "platforms: {}\n"
    )


def minimal_profile_dotenv_stub() -> str:
    """无密钥的 .env 占位；真 FEISHU_* 由 O2 写。"""
    return (
        "# fleet_add O3 stub — 无真密钥。FEISHU_ALLOWED_USERS / "
        "FEISHU_HOME_CHANNEL 由 O2 apply 写入。\n"
    )


def host_useradd_support() -> dict[str, Any]:
    """探测本机是否可真实执行 useradd（Mac 通常不可）。"""
    import platform
    import shutil

    system = platform.system()
    which = shutil.which("useradd")
    if system == "Darwin" or which is None:
        return {
            "supported": False,
            "system": system,
            "useradd_path": which,
            "status": "unsupported",
            "note": "本机无 Linux useradd；O3 apply-host 跳过真实 useradd，仅列命令",
        }
    return {
        "supported": True,
        "system": system,
        "useradd_path": which,
        "status": "available",
        "note": "须显式 run_useradd=True 才会执行；默认只列命令",
    }


def build_allowlist_plan(
    *,
    ldap_uid: str,
    open_ids: Sequence[str],
    tenant_user_ids: Sequence[str],
    hermes_dir: str,
    hub_home: str = DEFAULT_HUB_HOME,
    hub_allow_all: bool = False,
) -> dict[str, Any]:
    """O2 将写的 FEISHU_ALLOWED_USERS（目标 + Hub）；O1 只计划。"""
    members = _normalize_ids([*open_ids, *tenant_user_ids])
    target_env = f"{hermes_dir.rstrip('/')}/.env"
    hub_env = f"{hub_home.rstrip('/')}/.env"
    plan: dict[str, Any] = {
        "members": members,
        "target_profile_env": {
            "path": target_env,
            "key": "FEISHU_ALLOWED_USERS",
            "value_csv": ",".join(members),
            "action": "set_or_merge",
        },
        "hub_env": {
            "path": hub_env,
            "key": "FEISHU_ALLOWED_USERS",
            "value_csv": ",".join(members),
            "action": "merge_into_existing"
            if not hub_allow_all
            else "skip_hub_allow_all_documented",
            "note": (
                "Hub _admit 在 try_route_inbound_message 之前；"
                "须与 ou 同批写入，禁止等首条私聊被丢弃后再补"
                if not hub_allow_all
                else "Hub 已钉 FEISHU_ALLOW_ALL_USERS，跳过双写 Hub allowlist"
            ),
        },
    }
    return plan


def build_home_channel_plan(
    *,
    ldap_uid: str,
    home_channel: Optional[str],
    open_ids: Sequence[str],
    hermes_dir: str,
) -> dict[str, Any]:
    """O2 将写 FEISHU_HOME_CHANNEL + platforms.feishu.home_channel。"""
    # 优先 oc_*；否则退到第一个 ou_*（与现网 .env 用法一致）
    channel = (home_channel or "").strip()
    if not channel:
        for oid in open_ids:
            if str(oid).startswith("oc_"):
                channel = str(oid)
                break
        if not channel and open_ids:
            channel = str(open_ids[0])
    return {
        "feishu_home_channel": channel or None,
        "target_env": {
            "path": f"{hermes_dir.rstrip('/')}/.env",
            "key": "FEISHU_HOME_CHANNEL",
            "value": channel or None,
            "action": "set" if channel else "defer_until_dm_chat_id",
        },
        "config_yaml": {
            "path": f"{hermes_dir.rstrip('/')}/config.yaml",
            "key_path": "platforms.feishu.home_channel",
            "value": (
                {"platform": "feishu", "chat_id": channel, "name": "Home"}
                if channel
                else None
            ),
            "action": "set" if channel else "defer_until_dm_chat_id",
            "note": "与 /sethome 真相源对齐；禁止默认指望事后手敲 /sethome",
        },
    }



# ---------------------------------------------------------------------------
# O4：compose up + health（可注入 runner；默认 dry 只列）
# ---------------------------------------------------------------------------

DEFAULT_HEALTH_PATHS: tuple[str, ...] = ("/health", "/")
DEFAULT_HEALTH_TIMEOUT_S = 2.0
DEFAULT_HEALTH_RETRIES = 3
DEFAULT_HEALTH_RETRY_SLEEP_S = 0.4


def health_probe_urls(
    api_base: str,
    *,
    paths: Sequence[str] = DEFAULT_HEALTH_PATHS,
) -> list[str]:
    """由 ``api_server.url`` 生成探活 URL 列表（去重保序）。"""
    base = (api_base or "").strip().rstrip("/")
    if not base:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        p = str(raw or "").strip() or "/"
        if not p.startswith("/"):
            p = "/" + p
        url = base if p == "/" else f"{base}{p}"
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def build_up_plan(
    *,
    compose_file: str,
    service_name: str,
    api_url: str,
    port: int,
    health_paths: Sequence[str] = DEFAULT_HEALTH_PATHS,
) -> dict[str, Any]:
    """O4 dry 计划：将执行的 up / health / 失败回滚说明（不执行）。"""
    compose_path = compose_file or "./docker-compose.fleet-unknown.yml"
    svc = service_name or "hermes-unknown"
    base = (api_url or "").rstrip("/") or (
        f"http://127.0.0.1:{port}" if port else "http://127.0.0.1:<port>"
    )
    probes = health_probe_urls(base, paths=health_paths)
    up_cmd = f"docker compose -f {compose_path} up -d {svc}"
    stop_cmd = f"docker compose -f {compose_path} stop {svc}"
    down_cmd = f"docker compose -f {compose_path} down"
    rollback = [
        "回滚（O4 容器级；overlay/种子文件见 O2/O3 备份）：",
        f"  {stop_cmd}",
        f"  # 若需拆掉网络/匿名卷: {down_cmd}",
        "  # 然后按 O3/O2 rollback 恢复 compose / overlay / .env（若本次一并 apply）",
        "  # 本工具不自动 userdel / 不删 profiles 数据",
    ]
    return {
        "phase": "O4",
        "compose_file": compose_path,
        "service": svc,
        "port": port,
        "api_base": base,
        "up_cmd": up_cmd,
        "stop_cmd": stop_cmd,
        "down_cmd": down_cmd,
        "health": {
            "api_base": base,
            "probe_urls": probes,
            "timeout_s": DEFAULT_HEALTH_TIMEOUT_S,
            "retries": DEFAULT_HEALTH_RETRIES,
            "note": "任一路探活 HTTP 2xx 即通过；超时/非 2xx → 结构化失败 + 回滚文案",
        },
        "rollback": rollback,
        "notes": [
            "默认 dry-run 只列出；--apply-up 才执行（可注入 compose_runner / health_get）",
            "单测勿依赖真 Docker daemon；生产 /data/hermes 须 --allow-production",
        ],
    }


def default_compose_runner(
    argv: Sequence[str],
    *,
    cwd: Optional[str] = None,
) -> dict[str, Any]:
    """真实 ``docker compose …`` 子进程（生产路径）；单测应注入 mock。"""
    try:
        proc = subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            text=True,
            cwd=cwd,
        )
    except FileNotFoundError as exc:
        return {
            "returncode": 127,
            "argv": list(argv),
            "stdout_tail": "",
            "stderr_tail": f"docker 不可用: {exc}",
            "error": "docker_not_found",
        }
    except OSError as exc:
        return {
            "returncode": 1,
            "argv": list(argv),
            "stdout_tail": "",
            "stderr_tail": str(exc)[-500:],
            "error": "os_error",
        }
    return {
        "returncode": int(proc.returncode),
        "argv": list(argv),
        "stdout_tail": (proc.stdout or "")[-800:],
        "stderr_tail": (proc.stderr or "")[-800:],
    }


def default_health_get(
    url: str,
    *,
    timeout: float = DEFAULT_HEALTH_TIMEOUT_S,
) -> dict[str, Any]:
    """HTTP GET 探活（stdlib urllib）；单测应注入 mock。"""
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", None) or resp.getcode())
            body = resp.read(256)
            try:
                snip = body.decode("utf-8", errors="replace")
            except Exception:
                snip = ""
            return {
                "ok": 200 <= status < 300,
                "status": status,
                "url": url,
                "body_snip": snip[:200],
            }
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "status": int(exc.code),
            "url": url,
            "error": "http_error",
            "body_snip": str(exc)[:200],
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "url": url,
            "error": type(exc).__name__,
            "body_snip": str(exc)[:200],
        }


def probe_api_health(
    api_base: str,
    *,
    paths: Sequence[str] = DEFAULT_HEALTH_PATHS,
    timeout: float = DEFAULT_HEALTH_TIMEOUT_S,
    retries: int = DEFAULT_HEALTH_RETRIES,
    retry_sleep: float = DEFAULT_HEALTH_RETRY_SLEEP_S,
    health_get: Optional[Callable[..., dict[str, Any]]] = None,
) -> dict[str, Any]:
    """对 ``api_server`` 基址按路径列表探活；可注入 ``health_get(url)`` / ``(url, timeout=)``。"""
    import time

    urls = health_probe_urls(api_base, paths=paths)
    attempts: list[dict[str, Any]] = []
    if not urls:
        return {
            "ok": False,
            "error": "no_probe_urls",
            "message": "缺少 api_server.url，无法探活",
            "attempts": attempts,
        }

    def _call(url: str) -> dict[str, Any]:
        if health_get is None:
            return default_health_get(url, timeout=timeout)
        try:
            return health_get(url, timeout=timeout)
        except TypeError:
            return health_get(url)

    rounds = max(1, int(retries))
    for i in range(rounds):
        for url in urls:
            result = _call(url)
            entry = {"attempt": i + 1, **dict(result)}
            attempts.append(entry)
            if result.get("ok"):
                return {
                    "ok": True,
                    "url": url,
                    "status": result.get("status"),
                    "attempts": attempts,
                }
        if i + 1 < rounds and retry_sleep > 0:
            time.sleep(retry_sleep)
    return {
        "ok": False,
        "error": "health_failed",
        "message": f"探活失败（{rounds} 轮 × {len(urls)} URL）",
        "attempts": attempts,
    }


def build_planned_commands(
    *,
    ldap_uid: str,
    home_dir: str,
    hermes_dir: str,
    service_name: str,
    compose_file: str = "",
    api_url: str = "",
    port: int = 0,
) -> list[dict[str, str]]:
    """将执行的系统命令清单（O1 只列出，不执行）。"""
    compose_path = compose_file or f"./docker-compose.fleet-{ldap_uid}.yml"
    base = (api_url or "").rstrip("/") or (
        f"http://127.0.0.1:{port}" if port else "http://127.0.0.1:<port>"
    )
    return [
        {
            "step": "useradd",
            "cmd": (
                f"id {ldap_uid} >/dev/null 2>&1 || "
                f"useradd -m -d {home_dir} -s /bin/bash {ldap_uid}"
            ),
            "phase": "O3",
            "note": "Linux + --apply-host --run-useradd；Darwin/无二进制 → unsupported",
        },
        {
            "step": "seed_profile",
            "cmd": (
                f"mkdir -p {hermes_dir}/memories {hermes_dir}/logs {home_dir} && "
                f"# 最小 config.yaml / .env stub（无真密钥）"
            ),
            "phase": "O3",
        },
        {
            "step": "write_compose",
            "cmd": f"# 写三层挂载 compose → {compose_path}（服务 {service_name}）",
            "phase": "O3",
        },
        {
            "step": "compose_up",
            "cmd": f"docker compose -f {compose_path} up -d {service_name}",
            "phase": "O4",
        },
        {
            "step": "health",
            "cmd": (
                f"# 探活 {base}/health 或 {base}/ "
                f"（api_server.url；O4 --apply-up 执行）"
            ),
            "phase": "O4",
        },
        {
            "step": "compose_down_on_fail",
            "cmd": (
                f"docker compose -f {compose_path} stop {service_name}  "
                f"# 失败回滚；必要时 down"
            ),
            "phase": "O4",
            "note": "仅健康检查失败或回滚时执行",
        },
    ]


def plan_fleet_add(
    *,
    ldap_uid: str,
    display_name: str,
    open_ids: Sequence[str],
    overlay: Mapping[str, Any],
    tenant_user_ids: Sequence[str] = (),
    home_channel: Optional[str] = None,
    hub_only_feishu: bool = False,
    hub_only_api: bool = False,
    hermes_dir: Optional[str] = None,
    home_dir: Optional[str] = None,
    preferred_port: Optional[int] = None,
    extra_used_ports: Sequence[int] = (),
    app_id: str = "",
    code_dir: str = DEFAULT_CODE_DIR,
    venv_dir: str = DEFAULT_VENV_DIR,
    hermes_root: str = DEFAULT_HERMES_ROOT,
    hub_home: str = DEFAULT_HUB_HOME,
    hub_allow_all: bool = False,
    compose_file: Optional[str] = None,
    port_base: int = DEFAULT_PORT_BASE,
    port_ceiling: int = DEFAULT_PORT_CEILING,
) -> dict[str, Any]:
    """生成完整 dry-run 计划（结构化 dict，可供对话回显 / JSON 打印）。

    **零落盘**：不写 overlay、不 docker、不 useradd、不碰真实密钥文件。
    含 O3 种子计划与三层 compose YAML 草稿（仍不落盘）。
    """
    uid = str(ldap_uid or "").strip()
    name = str(display_name or "").strip()
    if not uid:
        raise FleetAddError("ldap_uid 必填")
    if not name:
        raise FleetAddError("display_name 必填")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", uid):
        raise FleetAddError(
            f"ldap_uid 非法（须像 passwd/LDAP 名）: {uid!r}"
        )

    oids = _normalize_ids(open_ids)
    tids = _normalize_ids(tenant_user_ids)
    if not oids and not tids:
        raise FleetAddError(
            "至少提供一个飞书 ou_* 或 tenant user_id（冷用户可后补，但 O1 计划须有标识）"
        )

    fleet = pick_fleet_profiles(overlay)
    if uid in fleet:
        raise FleetAddError(f"fleet_profiles 已存在键 {uid!r}，拒绝覆盖")

    routing = pick_user_routing(overlay, app_id=app_id)
    existing_routes = routing.get("user_profile_routes") or {}
    if not isinstance(existing_routes, dict):
        existing_routes = {}
    for oid in oids:
        if oid in existing_routes:
            raise FleetAddError(
                f"user_profile_routes 已占用 {oid!r} → {existing_routes[oid]!r}"
            )

    used = extract_ports_from_fleet(fleet)
    used.extend(int(p) for p in extra_used_ports)
    port = allocate_port(
        used,
        preferred=preferred_port,
        port_base=port_base,
        port_ceiling=port_ceiling,
    )

    key_src, _raw_key = find_shared_api_key_source(fleet)
    api_key_meta = {
        "strategy": "reuse_shared_fleet_key",
        "source_profile": key_src,
        "placeholder": _REDACTED_KEY,
        "note": "舰队共用一把；输出永不回显真实 key；无现网源时 O2 须显式注入夹具/运维密钥",
    }

    resolved_hermes = hermes_dir or default_hermes_dir(uid, hermes_root)
    resolved_home = home_dir or default_home_dir(uid)

    card = build_person_card(
        ldap_uid=uid,
        display_name=name,
        port=port,
        api_key_placeholder=_REDACTED_KEY,
        hermes_dir=resolved_hermes,
        home_dir=resolved_home,
        hub_only_feishu=hub_only_feishu,
        hub_only_api=hub_only_api,
        hermes_root=hermes_root,
    )

    route_additions = {oid: uid for oid in oids}
    compose = build_compose_service_draft(
        ldap_uid=uid,
        port=port,
        hermes_dir=resolved_hermes,
        home_dir=resolved_home,
        code_dir=code_dir,
        venv_dir=venv_dir,
    )
    resolved_compose_file = (
        compose_file
        or f"{hermes_root.rstrip('/')}/compose/{DEFAULT_COMPOSE_FILENAME.format(uid=uid)}"
    )
    compose_yaml = render_compose_yaml(
        compose,
        compose_project_comment=f"ldap_uid={uid} port={port}",
    )
    seed = build_seed_plan(
        ldap_uid=uid,
        hermes_dir=resolved_hermes,
        home_dir=resolved_home,
        compose_file=resolved_compose_file,
        port=port,
    )
    allowlist = build_allowlist_plan(
        ldap_uid=uid,
        open_ids=oids,
        tenant_user_ids=tids,
        hermes_dir=resolved_hermes,
        hub_home=hub_home,
        hub_allow_all=hub_allow_all,
    )
    home_ch = build_home_channel_plan(
        ldap_uid=uid,
        home_channel=home_channel,
        open_ids=oids,
        hermes_dir=resolved_hermes,
    )
    api_base = f"http://127.0.0.1:{port}"
    commands = build_planned_commands(
        ldap_uid=uid,
        home_dir=resolved_home,
        hermes_dir=resolved_hermes,
        service_name=compose["service"],
        compose_file=resolved_compose_file,
        api_url=api_base,
        port=port,
    )
    up_plan = build_up_plan(
        compose_file=resolved_compose_file,
        service_name=compose["service"],
        api_url=api_base,
        port=port,
    )

    # 叠加后的路由表预览（不修改入参）
    routes_preview = dict(existing_routes)
    routes_preview.update(route_additions)

    return {
        "mode": "dry-run",
        "phase": "O1",
        "ldap_uid": uid,
        "display_name": name,
        "notes": [
            "默认 dry-run：零落盘（不写 overlay / .env / compose，不 useradd，不 docker up）",
            "逻辑主键 = LDAP uid；生产 node010 现网路由键仍可能是全名——切 uid 另开 Ops",
            "O2 --apply：人卡 + routes + FEISHU_ALLOWED_USERS（ou±tenant）+ home channel",
            "O3 --apply-host：种子 profiles/ + 三层 compose 文件；useradd 默认只列（Mac unsupported）",
            "O4 --apply-up：docker compose up -d + 探活 api_server.url（可注入 mock；本计划不执行）",
        ],
        "person_card": card,
        "overlay_writes": {
            f"fleet_profiles.{uid}": card,
            "user_profile_routes_additions": route_additions,
            "user_profile_routes_preview": routes_preview,
            "feishu_app_id": app_id or None,
        },
        "api_key": api_key_meta,
        "port": {
            "allocated": port,
            "used_before": sorted(set(used)),
            "url": f"http://127.0.0.1:{port}",
        },
        "feishu_allowed_users": allowlist,
        "feishu_home_channel": home_ch,
        "compose": compose,
        "compose_file": resolved_compose_file,
        "compose_yaml": compose_yaml,
        "seed": seed,
        "host_useradd": host_useradd_support(),
        "planned_commands": commands,
        "up": up_plan,
        "hub_only_flags": {
            "feishu": hub_only_feishu,
            "api": hub_only_api,
            "resolved_from_card": list(_hub_only_flags(card)),
        },
    }


def format_plan_text(plan: Mapping[str, Any]) -> str:
    """人类可读回显（对话 / CLI stdout）。"""
    import json

    lines: list[str] = []
    lines.append(f"# fleet_add {plan.get('phase')} · {plan.get('mode')}")
    lines.append(f"ldap_uid: {plan.get('ldap_uid')}")
    lines.append(f"display_name: {plan.get('display_name')}")
    lines.append("")
    for n in plan.get("notes") or []:
        lines.append(f"- {n}")
    lines.append("")
    lines.append("## 人卡草稿 (fleet_profiles)")
    lines.append(json.dumps(plan.get("person_card"), ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("## user_profile_routes 增量")
    lines.append(
        json.dumps(
            (plan.get("overlay_writes") or {}).get("user_profile_routes_additions"),
            ensure_ascii=False,
            indent=2,
        )
    )
    lines.append("")
    lines.append("## 端口")
    lines.append(json.dumps(plan.get("port"), ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("## FEISHU_ALLOWED_USERS 计划")
    lines.append(
        json.dumps(plan.get("feishu_allowed_users"), ensure_ascii=False, indent=2)
    )
    lines.append("")
    lines.append("## FEISHU_HOME_CHANNEL 计划")
    lines.append(
        json.dumps(plan.get("feishu_home_channel"), ensure_ascii=False, indent=2)
    )
    lines.append("")
    lines.append("## compose 三层挂载草稿")
    lines.append(json.dumps(plan.get("compose"), ensure_ascii=False, indent=2))
    lines.append("")
    lines.append(f"## compose 文件路径: {plan.get('compose_file')}")
    lines.append("## compose YAML 预览")
    lines.append(str(plan.get("compose_yaml") or ""))
    lines.append("")
    lines.append("## O3 种子计划")
    lines.append(json.dumps(plan.get("seed"), ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("## useradd 支持探测")
    lines.append(json.dumps(plan.get("host_useradd"), ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("## O4 up + health 计划（本阶段不执行）")
    lines.append(json.dumps(plan.get("up"), ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("## 将执行的命令（O3/O4；本阶段不执行）")
    for c in plan.get("planned_commands") or []:
        lines.append(f"- [{c.get('phase')}/{c.get('step')}] {c.get('cmd')}")
    lines.append("")
    lines.append("## api_key 策略（已脱敏）")
    lines.append(json.dumps(plan.get("api_key"), ensure_ascii=False, indent=2))
    return "\n".join(lines) + "\n"


def load_overlay_yaml(path: str) -> dict[str, Any]:
    """读 overlay YAML 为 dict；缺文件 → {}。不缓存、不写回。"""
    from pathlib import Path

    import yaml

    p = Path(path)
    if not p.is_file():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def merge_fixture_overlay(
    base: Mapping[str, Any],
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    """浅合并顶层键；``fleet_profiles`` / 路由深合并，便于测试夹具。"""
    out: dict[str, Any] = copy.deepcopy(dict(base))
    for k, v in fixture.items():
        if k == "fleet_profiles" and isinstance(v, dict):
            fp = out.setdefault("fleet_profiles", {})
            if not isinstance(fp, dict):
                fp = {}
                out["fleet_profiles"] = fp
            fp.update(copy.deepcopy(v))
        elif k == "feishu" and isinstance(v, dict):
            out["feishu"] = _deep_merge_dict(
                out.get("feishu") if isinstance(out.get("feishu"), dict) else {},
                v,
            )
        else:
            out[k] = copy.deepcopy(v)
    return out


def _deep_merge_dict(
    a: MutableMapping[str, Any], b: Mapping[str, Any]
) -> dict[str, Any]:
    result: dict[str, Any] = copy.deepcopy(dict(a))
    for k, v in b.items():
        if (
            k in result
            and isinstance(result[k], dict)
            and isinstance(v, dict)
        ):
            result[k] = _deep_merge_dict(result[k], v)
        else:
            result[k] = copy.deepcopy(v)
    return result



# ---------------------------------------------------------------------------
# O2 apply：写 overlay + allowlist + home（仍不 docker / useradd）
# ---------------------------------------------------------------------------

PathLike = str | Path

_PRODUCTION_ROOT_PREFIXES = (
    "/data/hermes",
)


def _ts_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def is_production_path(path: PathLike) -> bool:
    """粗判是否落在现网 ``/data/hermes`` 树（拒绝默认 apply）。"""
    try:
        resolved = str(Path(path).expanduser().resolve())
    except OSError:
        resolved = str(Path(path).expanduser())
    for prefix in _PRODUCTION_ROOT_PREFIXES:
        if resolved == prefix or resolved.startswith(prefix + os.sep):
            return True
    # 未存在的路径 resolve 仍可能落在 /data/hermes/...
    raw = str(path)
    for prefix in _PRODUCTION_ROOT_PREFIXES:
        if raw == prefix or raw.startswith(prefix + "/"):
            return True
    return False


def backup_file(path: Path, *, stamp: Optional[str] = None) -> Optional[str]:
    """若文件存在则复制为 ``.bak-fleet-add-<stamp>``；返回备份路径或 None。"""
    if not path.is_file():
        return None
    st = stamp or _ts_stamp()
    bak = path.with_name(path.name + f".bak-fleet-add-{st}")
    shutil.copy2(path, bak)
    return str(bak)


def read_dotenv_file(path: Path) -> dict[str, str]:
    """简易 .env 解析（不处理 export / 多行）；缺文件 → {}。"""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        val = value.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        values[key.strip()] = val
    return values


def merge_csv_ids(existing: str, additions: Sequence[str]) -> str:
    """CSV 去重合并，保序（先已有，后新增）。"""
    seen: set[str] = set()
    out: list[str] = []
    for part in str(existing or "").split(","):
        s = part.strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    for a in additions:
        s = str(a or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return ",".join(out)


def upsert_dotenv_key(path: Path, key: str, value: str) -> dict[str, Any]:
    """设置或替换 .env 中的 ``key=value``；保留其它行与注释。缺文件则创建。

    返回 ``{path, key, created, changed}``。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    created = not path.is_file()
    lines: list[str] = []
    if not created:
        lines = path.read_text(encoding="utf-8").splitlines()
    key_re = re.compile(rf"^\s*{re.escape(key)}\s*=")
    new_line = f"{key}={value}"
    found = False
    changed = created
    out_lines: list[str] = []
    for line in lines:
        if key_re.match(line):
            if line != new_line:
                changed = True
            out_lines.append(new_line)
            found = True
        else:
            out_lines.append(line)
    if not found:
        if out_lines and out_lines[-1].strip():
            out_lines.append("")
        out_lines.append(new_line)
        changed = True
    text = "\n".join(out_lines)
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")
    return {"path": str(path), "key": key, "created": created, "changed": changed}


def deep_set_yaml(data: MutableMapping[str, Any], dotted: str, value: Any) -> None:
    """按 ``a.b.c`` 路径写入；中间缺省建 dict。"""
    parts = [p for p in dotted.split(".") if p]
    if not parts:
        raise FleetAddError("空 key_path")
    cur: MutableMapping[str, Any] = data
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = copy.deepcopy(value)


def load_yaml_dict(path: Path) -> dict[str, Any]:
    import yaml

    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def dump_yaml_dict(path: Path, data: Mapping[str, Any]) -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        dict(data),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    path.write_text(text, encoding="utf-8")


def resolve_shared_api_key(
    overlay: Mapping[str, Any],
    *,
    explicit: Optional[str] = None,
) -> tuple[str, Optional[str]]:
    """返回 ``(api_key, source_uid)``；无源且无显式 → 报错。"""
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip(), None
    fleet = pick_fleet_profiles(overlay)
    src, key = find_shared_api_key_source(fleet)
    if key:
        return key, src
    raise FleetAddError(
        "apply 需要舰队共用 api_key：overlay 无人卡密钥且未传 shared_api_key"
    )


def _ensure_user_routing_slot(
    overlay: MutableMapping[str, Any],
    *,
    app_id: str = "",
) -> tuple[dict[str, Any], str]:
    """确保 ``user_routing`` dict 可写，返回 ``(user_routing, location_desc)``。"""
    feishu = overlay.setdefault("feishu", {})
    if not isinstance(feishu, dict):
        raise FleetAddError("overlay.feishu 不是 mapping，拒绝 apply")
    bots = feishu.get("bots")
    if isinstance(bots, dict) and bots:
        if app_id:
            bot = bots.setdefault(app_id, {})
            if not isinstance(bot, dict):
                raise FleetAddError(f"feishu.bots.{app_id} 不是 mapping")
            ur = bot.setdefault("user_routing", {})
            if not isinstance(ur, dict):
                raise FleetAddError(f"feishu.bots.{app_id}.user_routing 不是 mapping")
            return ur, f"feishu.bots.{app_id}.user_routing"
        if len(bots) == 1:
            only_id, only = next(iter(bots.items()))
            if not isinstance(only, dict):
                raise FleetAddError(f"feishu.bots.{only_id} 不是 mapping")
            ur = only.setdefault("user_routing", {})
            if not isinstance(ur, dict):
                raise FleetAddError(
                    f"feishu.bots.{only_id}.user_routing 不是 mapping"
                )
            return ur, f"feishu.bots.{only_id}.user_routing"
        raise FleetAddError("多 bot overlay 须指定 app_id 才能写 user_profile_routes")
    ur = feishu.setdefault("user_routing", {})
    if not isinstance(ur, dict):
        raise FleetAddError("feishu.user_routing 不是 mapping")
    return ur, "feishu.user_routing"


def apply_fleet_add(
    plan: Mapping[str, Any],
    *,
    overlay_path: PathLike,
    overlay: Optional[Mapping[str, Any]] = None,
    shared_api_key: Optional[str] = None,
    allow_production: bool = False,
    stamp: Optional[str] = None,
) -> dict[str, Any]:
    """按 O1 计划落盘（O2）：overlay + allowlist + home；不 docker、不 useradd。

    ``plan`` 须来自 ``plan_fleet_add``（或等价结构）。
    写盘前备份已有文件；结果含 ``rollback`` 说明。stdout/返回值中 api_key 脱敏。
    """
    uid = str(plan.get("ldap_uid") or "").strip()
    if not uid:
        raise FleetAddError("plan 缺少 ldap_uid")

    overlay_p = Path(overlay_path).expanduser()
    writes_meta = plan.get("overlay_writes") or {}
    allow = plan.get("feishu_allowed_users") or {}
    home_ch = plan.get("feishu_home_channel") or {}

    target_env_path = Path(
        (allow.get("target_profile_env") or {}).get("path")
        or f"{DEFAULT_HERMES_ROOT}/profiles/{uid}/.env"
    )
    hub_env_path = Path(
        (allow.get("hub_env") or {}).get("path") or f"{DEFAULT_HUB_HOME}/.env"
    )
    config_path = Path(
        (home_ch.get("config_yaml") or {}).get("path")
        or f"{DEFAULT_HERMES_ROOT}/profiles/{uid}/config.yaml"
    )

    paths_to_check = [overlay_p, target_env_path, hub_env_path, config_path]
    if not allow_production:
        bad = [str(p) for p in paths_to_check if is_production_path(p)]
        if bad:
            raise FleetAddError(
                "拒绝 apply 到疑似生产路径（/data/hermes/...）。"
                "请改用 temp/fixture 路径，或显式 allow_production=True / --allow-production。"
                f" 命中: {bad}"
            )

    base_overlay = (
        copy.deepcopy(dict(overlay))
        if overlay is not None
        else load_yaml_dict(overlay_p)
    )
    # 再跑冲突检查：以当前盘面为准
    replan_routes = pick_user_routing(
        base_overlay, app_id=str(writes_meta.get("feishu_app_id") or "")
    )
    existing_routes = replan_routes.get("user_profile_routes") or {}
    if not isinstance(existing_routes, dict):
        existing_routes = {}
    additions = writes_meta.get("user_profile_routes_additions") or {}
    if not isinstance(additions, dict):
        raise FleetAddError("plan.overlay_writes.user_profile_routes_additions 非法")
    for oid, target in additions.items():
        if oid in existing_routes and existing_routes[oid] != target:
            raise FleetAddError(
                f"apply 时 user_profile_routes 冲突 {oid!r} → "
                f"已有 {existing_routes[oid]!r}，计划 {target!r}"
            )
    fleet_now = pick_fleet_profiles(base_overlay)
    if uid in fleet_now:
        raise FleetAddError(f"apply 时 fleet_profiles 已存在键 {uid!r}，拒绝覆盖")

    api_key, key_src = resolve_shared_api_key(
        base_overlay, explicit=shared_api_key
    )

    person = copy.deepcopy(plan.get("person_card") or {})
    if not isinstance(person, dict):
        raise FleetAddError("plan.person_card 非法")
    api_server = person.setdefault("api_server", {})
    if not isinstance(api_server, dict):
        raise FleetAddError("person_card.api_server 非法")
    api_server["api_key"] = api_key

    st = stamp or _ts_stamp()
    backups: dict[str, Optional[str]] = {}
    written: list[dict[str, Any]] = []

    # --- overlay ---
    backups["overlay"] = backup_file(overlay_p, stamp=st)
    mut = copy.deepcopy(base_overlay)
    fp = mut.setdefault("fleet_profiles", {})
    if not isinstance(fp, dict):
        raise FleetAddError("overlay.fleet_profiles 不是 mapping")
    fp[uid] = person
    ur, ur_loc = _ensure_user_routing_slot(
        mut, app_id=str(writes_meta.get("feishu_app_id") or "")
    )
    routes = ur.setdefault("user_profile_routes", {})
    if not isinstance(routes, dict):
        raise FleetAddError(f"{ur_loc}.user_profile_routes 不是 mapping")
    routes.update({str(k): str(v) for k, v in additions.items()})
    dump_yaml_dict(overlay_p, mut)
    written.append(
        {
            "kind": "overlay",
            "path": str(overlay_p),
            "fleet_profiles_key": uid,
            "routes_added": dict(additions),
            "user_routing_at": ur_loc,
        }
    )

    # --- allowlist .env（目标 + Hub）---
    members = list(allow.get("members") or [])
    target_action = (allow.get("target_profile_env") or {}).get("action")
    if members and target_action != "skip":
        backups["target_env"] = backup_file(target_env_path, stamp=st)
        existing = read_dotenv_file(target_env_path).get("FEISHU_ALLOWED_USERS", "")
        merged = merge_csv_ids(existing, members)
        meta = upsert_dotenv_key(target_env_path, "FEISHU_ALLOWED_USERS", merged)
        meta["kind"] = "target_allowlist"
        meta["value_csv"] = merged
        written.append(meta)

    hub_info = allow.get("hub_env") or {}
    hub_action = hub_info.get("action")
    if members and hub_action == "merge_into_existing":
        backups["hub_env"] = backup_file(hub_env_path, stamp=st)
        existing = read_dotenv_file(hub_env_path).get("FEISHU_ALLOWED_USERS", "")
        merged = merge_csv_ids(existing, members)
        meta = upsert_dotenv_key(hub_env_path, "FEISHU_ALLOWED_USERS", merged)
        meta["kind"] = "hub_allowlist"
        meta["value_csv"] = merged
        written.append(meta)
    elif hub_action == "skip_hub_allow_all_documented":
        written.append(
            {
                "kind": "hub_allowlist",
                "path": str(hub_env_path),
                "skipped": True,
                "reason": "hub_allow_all",
            }
        )

    # --- home channel：.env + config.yaml ---
    channel = home_ch.get("feishu_home_channel")
    env_action = (home_ch.get("target_env") or {}).get("action")
    if channel and env_action == "set":
        if "target_env" not in backups:
            backups["target_env"] = backup_file(target_env_path, stamp=st)
        meta = upsert_dotenv_key(
            target_env_path, "FEISHU_HOME_CHANNEL", str(channel)
        )
        meta["kind"] = "target_home_channel_env"
        meta["value"] = str(channel)
        written.append(meta)

    cfg_action = (home_ch.get("config_yaml") or {}).get("action")
    cfg_value = (home_ch.get("config_yaml") or {}).get("value")
    if channel and cfg_action == "set" and cfg_value:
        backups["target_config"] = backup_file(config_path, stamp=st)
        cfg = load_yaml_dict(config_path)
        deep_set_yaml(cfg, "platforms.feishu.home_channel", cfg_value)
        dump_yaml_dict(config_path, cfg)
        written.append(
            {
                "kind": "target_home_channel_config",
                "path": str(config_path),
                "key_path": "platforms.feishu.home_channel",
                "value": copy.deepcopy(cfg_value),
            }
        )

    rollback_steps = [
        "回滚（O2 文件级；不涉及容器）：",
    ]
    for label, bak in backups.items():
        if bak:
            # 原路径映射
            orig = {
                "overlay": str(overlay_p),
                "target_env": str(target_env_path),
                "hub_env": str(hub_env_path),
                "target_config": str(config_path),
            }.get(label, "?")
            rollback_steps.append(f"  cp {bak} {orig}")
        else:
            # 新文件：删掉本次新增键 / 文件
            if label == "overlay":
                rollback_steps.append(
                    f"  # overlay 原先不存在：可删 {overlay_p} 或手删 fleet_profiles.{uid} 与新增 routes"
                )
            elif label == "target_env":
                rollback_steps.append(
                    f"  # 目标 .env 原先不存在：可删 {target_env_path} 或手删 FEISHU_* 键"
                )
            elif label == "hub_env":
                rollback_steps.append(
                    f"  # Hub .env 无备份：从 FEISHU_ALLOWED_USERS 去掉 {members}"
                )
            elif label == "target_config":
                rollback_steps.append(
                    f"  # config.yaml 原先不存在：可删 {config_path} 或去掉 platforms.feishu.home_channel"
                )
    rollback_steps.append(
        "  # O2 未起容器 / 未 useradd；无需 docker compose down 或 userdel"
    )

    # 脱敏人卡预览
    card_preview = copy.deepcopy(person)
    if isinstance(card_preview.get("api_server"), dict):
        card_preview["api_server"]["api_key"] = _REDACTED_KEY

    return {
        "mode": "apply",
        "phase": "O2",
        "ldap_uid": uid,
        "display_name": plan.get("display_name"),
        "stamp": st,
        "backups": backups,
        "written": written,
        "rollback": rollback_steps,
        "person_card_written": card_preview,
        "api_key": {
            "strategy": "reuse_shared_fleet_key",
            "source_profile": key_src,
            "placeholder": _REDACTED_KEY,
            "note": "真实 key 已写入 overlay 人卡；本结果永不回显",
        },
        "notes": [
            "O2 已写 overlay + allowlist + home；未 compose up、未 useradd",
            "Hub 改 allowlist 后通常需 reload/重启 gateway 才生效（见设计 F3）",
        ],
    }


def format_apply_text(result: Mapping[str, Any]) -> str:
    """apply 结果人类可读回显（密钥已脱敏）。"""
    import json

    lines: list[str] = []
    lines.append(f"# fleet_add {result.get('phase')} · {result.get('mode')}")
    lines.append(f"ldap_uid: {result.get('ldap_uid')}")
    lines.append(f"display_name: {result.get('display_name')}")
    lines.append(f"stamp: {result.get('stamp')}")
    lines.append("")
    for n in result.get("notes") or []:
        lines.append(f"- {n}")
    lines.append("")
    lines.append("## 已写文件")
    lines.append(json.dumps(result.get("written"), ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("## 备份")
    lines.append(json.dumps(result.get("backups"), ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("## 回滚")
    for step in result.get("rollback") or []:
        lines.append(step if str(step).startswith(" ") or str(step).startswith("回滚") else f"- {step}")
    lines.append("")
    lines.append("## 人卡（脱敏）")
    lines.append(
        json.dumps(result.get("person_card_written"), ensure_ascii=False, indent=2)
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# O3：宿主机种子 + 三层 compose 文件（默认 dry；--apply-host 落盘；不上容器）
# ---------------------------------------------------------------------------


def apply_fleet_add_host(
    plan: Mapping[str, Any],
    *,
    allow_production: bool = False,
    run_useradd: bool = False,
    stamp: Optional[str] = None,
    mock_useradd: bool = False,
) -> dict[str, Any]:
    """O3：按计划种子 ``profiles/<uid>``、写三层 compose 文件；可选 useradd。

    - 默认仍应先经 CLI dry-run 看计划；本函数才真正写目录/文件。
    - 拒绝 ``/data/hermes`` 除非 ``allow_production=True``。
    - ``useradd``：仅当 ``run_useradd=True`` 且本机支持时执行；Darwin / 无二进制 →
      ``status=unsupported``；``mock_useradd=True`` 时在结果里记模拟成功（单测用）。
    - **不** ``docker compose up``（O4）。
    """
    uid = str(plan.get("ldap_uid") or "").strip()
    if not uid:
        raise FleetAddError("plan 缺少 ldap_uid")

    seed = plan.get("seed") or {}
    if not isinstance(seed, dict):
        raise FleetAddError("plan.seed 非法")
    compose_file = str(plan.get("compose_file") or seed.get("files", [{}])[-1].get("path") or "")
    if not compose_file:
        raise FleetAddError("plan 缺少 compose_file")
    compose_yaml = str(plan.get("compose_yaml") or "")
    if not compose_yaml.strip():
        # 容错：从 draft 重渲
        draft = plan.get("compose") or {}
        if not isinstance(draft, dict):
            raise FleetAddError("plan.compose / compose_yaml 皆缺")
        compose_yaml = render_compose_yaml(draft)

    # 守卫：禁止单挂 home
    vols = list((plan.get("compose") or {}).get("volumes") or [])
    if vols:
        has_hermes = any("/root/.hermes" in str(v) for v in vols)
        has_root = any(str(v).rstrip().endswith(":/root") for v in vols)
        if has_root and not has_hermes:
            raise FleetAddError("拒绝单挂 /home→/root 的 compose（须三层）")

    dirs = [str(d) for d in (seed.get("directories") or [])]
    paths_to_check = [Path(compose_file), *[Path(d) for d in dirs]]
    # 也检查 person_card docker paths
    person = plan.get("person_card") or {}
    docker = person.get("docker") if isinstance(person, dict) else {}
    if isinstance(docker, dict):
        for k in ("hermes_dir", "home_dir"):
            if docker.get(k):
                paths_to_check.append(Path(str(docker[k])))

    if not allow_production:
        bad = [str(p) for p in paths_to_check if is_production_path(p)]
        if bad:
            raise FleetAddError(
                "拒绝 apply-host 到疑似生产路径（/data/hermes/...）。"
                "请改用 temp/fixture 路径，或显式 allow_production=True / --allow-production。"
                f" 命中: {bad}"
            )

    st = stamp or _ts_stamp()
    created_dirs: list[str] = []
    written: list[dict[str, Any]] = []
    backups: dict[str, Optional[str]] = {}

    for d in dirs:
        p = Path(d)
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            created_dirs.append(str(p))
        else:
            p.mkdir(parents=True, exist_ok=True)

    # 最小种子文件（create_if_missing）
    hermes_dir = ""
    if isinstance(docker, dict):
        hermes_dir = str(docker.get("hermes_dir") or "")
    if not hermes_dir:
        for d in dirs:
            if "/profiles/" in d.replace("\\", "/") and not d.rstrip("/").endswith(("memories", "logs")):
                # 取最短的 profiles 路径当 hermes_dir
                if not hermes_dir or len(d) < len(hermes_dir):
                    hermes_dir = d

    config_path = Path(hermes_dir) / "config.yaml" if hermes_dir else None
    env_path = Path(hermes_dir) / ".env" if hermes_dir else None

    if config_path is not None:
        if not config_path.is_file():
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(minimal_profile_config_yaml(), encoding="utf-8")
            written.append(
                {
                    "kind": "minimal_config",
                    "path": str(config_path),
                    "created": True,
                }
            )
        else:
            written.append(
                {
                    "kind": "minimal_config",
                    "path": str(config_path),
                    "created": False,
                    "skipped": "already_exists",
                }
            )

    if env_path is not None:
        if not env_path.is_file():
            env_path.parent.mkdir(parents=True, exist_ok=True)
            env_path.write_text(minimal_profile_dotenv_stub(), encoding="utf-8")
            written.append(
                {
                    "kind": "dotenv_stub",
                    "path": str(env_path),
                    "created": True,
                }
            )
        else:
            written.append(
                {
                    "kind": "dotenv_stub",
                    "path": str(env_path),
                    "created": False,
                    "skipped": "already_exists",
                }
            )

    # compose 文件
    compose_p = Path(compose_file)
    backups["compose"] = backup_file(compose_p, stamp=st)
    compose_p.parent.mkdir(parents=True, exist_ok=True)
    compose_p.write_text(compose_yaml, encoding="utf-8")
    written.append(
        {
            "kind": "compose_yaml",
            "path": str(compose_p),
            "service": (plan.get("compose") or {}).get("service"),
            "volumes": list((plan.get("compose") or {}).get("volumes") or []),
        }
    )

    # useradd
    support = host_useradd_support()
    useradd_result: dict[str, Any] = {
        "step": "useradd",
        "cmd": next(
            (
                c.get("cmd")
                for c in (seed.get("host_commands") or [])
                if c.get("step") == "useradd"
            ),
            f"useradd -m -d ... {uid}",
        ),
        "run_useradd_requested": bool(run_useradd),
        "mock": bool(mock_useradd),
        **support,
    }
    if mock_useradd:
        useradd_result["status"] = "mocked"
        useradd_result["executed"] = False
        useradd_result["note"] = "单测/夹具模拟：未调用真实 useradd"
    elif not run_useradd:
        useradd_result["status"] = "skipped_flag_off"
        useradd_result["executed"] = False
        useradd_result["note"] = "未传 run_useradd；仅列出命令（安全默认）"
    elif not support.get("supported"):
        useradd_result["status"] = "unsupported"
        useradd_result["executed"] = False
    else:
        cmd = useradd_result["cmd"]
        # 仅执行计划中的 useradd 行；shell=True 因含 ||
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                check=False,
                capture_output=True,
                text=True,
            )
            useradd_result["executed"] = True
            useradd_result["returncode"] = proc.returncode
            useradd_result["status"] = "ok" if proc.returncode == 0 else "failed"
            # 不回显可能含路径外的噪声过大 stderr 截断
            err = (proc.stderr or "").strip()
            if err:
                useradd_result["stderr_tail"] = err[-500:]
        except OSError as exc:
            useradd_result["executed"] = False
            useradd_result["status"] = "error"
            useradd_result["error"] = str(exc)

    rollback = [
        "回滚（O3 宿主机文件级；不 down 容器——本阶段未 up）：",
    ]
    if backups.get("compose"):
        rollback.append(f"  cp {backups['compose']} {compose_p}")
    else:
        rollback.append(f"  rm -f {compose_p}")
    for d in created_dirs:
        rollback.append(f"  # 本次新建目录（确认无其它数据后）: rm -rf {d}")
    for w in written:
        if w.get("kind") in ("minimal_config", "dotenv_stub") and w.get("created"):
            rollback.append(f"  rm -f {w['path']}")
    rollback.append(
        "  # useradd：若曾 --run-useradd 成功，需运维审慎 userdel（本工具不自动删用户）"
    )
    rollback.append("  # O3 未 docker compose up；无需 compose down")

    return {
        "mode": "apply-host",
        "phase": "O3",
        "ldap_uid": uid,
        "display_name": plan.get("display_name"),
        "stamp": st,
        "created_directories": created_dirs,
        "written": written,
        "backups": backups,
        "useradd": useradd_result,
        "compose_file": str(compose_p),
        "rollback": rollback,
        "notes": [
            "O3 已种子目录 + 三层 compose 文件；未 docker up（O4）",
            "useradd 默认跳过；Linux 需 --run-useradd；Mac 为 unsupported",
            "禁止把真实密钥写入 compose / 种子模板",
        ],
    }


def format_host_apply_text(result: Mapping[str, Any]) -> str:
    """O3 apply-host 结果人类可读回显。"""
    import json

    lines: list[str] = []
    lines.append(f"# fleet_add {result.get('phase')} · {result.get('mode')}")
    lines.append(f"ldap_uid: {result.get('ldap_uid')}")
    lines.append(f"display_name: {result.get('display_name')}")
    lines.append(f"stamp: {result.get('stamp')}")
    lines.append(f"compose_file: {result.get('compose_file')}")
    lines.append("")
    for n in result.get("notes") or []:
        lines.append(f"- {n}")
    lines.append("")
    lines.append("## 新建目录")
    lines.append(json.dumps(result.get("created_directories"), ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("## 已写文件")
    lines.append(json.dumps(result.get("written"), ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("## useradd")
    lines.append(json.dumps(result.get("useradd"), ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("## 回滚")
    for step in result.get("rollback") or []:
        lines.append(
            step
            if str(step).startswith(" ") or str(step).startswith("回滚")
            else f"- {step}"
        )
    return "\n".join(lines) + "\n"



# ---------------------------------------------------------------------------
# O4 apply：compose up + health（门闩 execute；可注入 mock）
# ---------------------------------------------------------------------------


def apply_fleet_add_up(
    plan: Mapping[str, Any],
    *,
    allow_production: bool = False,
    execute: bool = False,
    compose_runner: Optional[Callable[..., dict[str, Any]]] = None,
    health_get: Optional[Callable[..., dict[str, Any]]] = None,
    health_timeout: float = DEFAULT_HEALTH_TIMEOUT_S,
    health_retries: int = DEFAULT_HEALTH_RETRIES,
    health_retry_sleep: float = DEFAULT_HEALTH_RETRY_SLEEP_S,
    health_paths: Sequence[str] = DEFAULT_HEALTH_PATHS,
    stamp: Optional[str] = None,
    require_compose_file: bool = True,
) -> dict[str, Any]:
    """O4：按计划 ``docker compose up -d`` + 探活 ``api_server.url``。

    - ``execute=False``（默认）：只返回将执行的 up/health/回滚说明（零副作用）。
    - ``execute=True``：经 ``compose_runner`` 起容器，再 ``health_get`` 探活。
      未注入时用真实 docker / urllib（单测务必注入 mock，勿依赖本机 daemon）。
    - 拒绝 ``/data/hermes`` 除非 ``allow_production=True``。
    - 健康失败：``ok=False`` + 结构化 ``error`` + 回滚步骤；并尝试 ``stop`` 服务
      （同样经 runner）。
    """
    uid = str(plan.get("ldap_uid") or "").strip()
    if not uid:
        raise FleetAddError("plan 缺少 ldap_uid")

    up = plan.get("up")
    if not isinstance(up, dict) or not up.get("up_cmd"):
        # 容错：从 plan 字段重建
        compose_file = str(plan.get("compose_file") or "")
        draft = plan.get("compose") or {}
        service = str((draft.get("service") if isinstance(draft, dict) else None) or f"hermes-{uid}")
        port_info = plan.get("port") or {}
        port = int((port_info.get("allocated") if isinstance(port_info, dict) else None) or 0)
        person = plan.get("person_card") or {}
        api = person.get("api_server") if isinstance(person, dict) else {}
        api_url = ""
        if isinstance(api, dict):
            api_url = str(api.get("url") or "")
        if not api_url and isinstance(port_info, dict):
            api_url = str(port_info.get("url") or "")
        if not compose_file:
            raise FleetAddError("plan 缺少 compose_file / up")
        up = build_up_plan(
            compose_file=compose_file,
            service_name=service,
            api_url=api_url,
            port=port,
            health_paths=health_paths,
        )

    compose_file = str(up.get("compose_file") or plan.get("compose_file") or "")
    service = str(up.get("service") or f"hermes-{uid}")
    api_base = str(up.get("api_base") or "")
    port = int(up.get("port") or 0)
    up_cmd = str(up.get("up_cmd") or f"docker compose -f {compose_file} up -d {service}")
    stop_cmd = str(up.get("stop_cmd") or f"docker compose -f {compose_file} stop {service}")
    down_cmd = str(up.get("down_cmd") or f"docker compose -f {compose_file} down")
    rollback = list(up.get("rollback") or [])
    if not rollback:
        rollback = [
            "回滚（O4 容器级）：",
            f"  {stop_cmd}",
            f"  # 必要时: {down_cmd}",
        ]

    paths_to_check: list[Path] = []
    if compose_file:
        paths_to_check.append(Path(compose_file))
    person = plan.get("person_card") or {}
    docker = person.get("docker") if isinstance(person, dict) else {}
    if isinstance(docker, dict):
        for k in ("hermes_dir", "home_dir"):
            if docker.get(k):
                paths_to_check.append(Path(str(docker[k])))

    if not allow_production:
        bad = [str(p) for p in paths_to_check if is_production_path(p)]
        if bad:
            raise FleetAddError(
                "拒绝 apply-up 到疑似生产路径（/data/hermes/...）。"
                "请改用 temp/fixture 路径，或显式 allow_production=True / --allow-production。"
                f" 命中: {bad}"
            )

    st = stamp or _ts_stamp()
    planned = {
        "up_cmd": up_cmd,
        "health_probe_urls": list((up.get("health") or {}).get("probe_urls") or health_probe_urls(api_base)),
        "stop_cmd": stop_cmd,
        "down_cmd": down_cmd,
    }

    if not execute:
        return {
            "mode": "dry-run-up",
            "phase": "O4",
            "ok": True,
            "executed": False,
            "ldap_uid": uid,
            "display_name": plan.get("display_name"),
            "stamp": st,
            "compose_file": compose_file,
            "service": service,
            "port": port,
            "api_base": api_base,
            "planned": planned,
            "compose": None,
            "health": None,
            "rollback": rollback,
            "notes": [
                "O4 dry-run：未执行 docker / 未探活；见 planned 与 rollback",
                "加 --apply-up（execute=True）并注入/使用 runner 才会起容器",
            ],
            "error": None,
        }

    compose_p = Path(compose_file) if compose_file else None
    if require_compose_file and (compose_p is None or not compose_p.is_file()):
        err = {
            "code": "compose_file_missing",
            "message": f"compose 文件不存在: {compose_file!r}（先 O3 --apply-host）",
        }
        return {
            "mode": "apply-up",
            "phase": "O4",
            "ok": False,
            "executed": False,
            "ldap_uid": uid,
            "display_name": plan.get("display_name"),
            "stamp": st,
            "compose_file": compose_file,
            "service": service,
            "port": port,
            "api_base": api_base,
            "planned": planned,
            "compose": None,
            "health": None,
            "rollback": rollback,
            "notes": ["O4 中止：缺少 compose 文件"],
            "error": err,
        }

    runner = compose_runner or default_compose_runner
    # argv 形态：docker compose -f <file> up -d <service>
    up_argv = ["docker", "compose", "-f", compose_file, "up", "-d", service]
    try:
        compose_result = runner(up_argv)
    except TypeError:
        # 允许 mock(argv=...) 或 mock(cmd_str)
        try:
            compose_result = runner(up_cmd)
        except TypeError:
            compose_result = runner(list(up_argv))
    if not isinstance(compose_result, dict):
        compose_result = {"returncode": 1, "error": "invalid_runner_result", "raw": str(compose_result)[:200]}

    # 脱敏：不把可能的环境密钥塞进结果
    safe_compose = {
        "returncode": compose_result.get("returncode"),
        "argv": compose_result.get("argv") or up_argv,
        "stdout_tail": str(compose_result.get("stdout_tail") or "")[-800:],
        "stderr_tail": str(compose_result.get("stderr_tail") or "")[-800:],
    }
    if compose_result.get("error"):
        safe_compose["error"] = compose_result.get("error")

    _rc = safe_compose.get("returncode")
    if _rc is None or int(_rc) != 0:
        err = {
            "code": "compose_up_failed",
            "message": "docker compose up 失败",
            "returncode": safe_compose.get("returncode"),
            "stderr_tail": safe_compose.get("stderr_tail"),
        }
        return {
            "mode": "apply-up",
            "phase": "O4",
            "ok": False,
            "executed": True,
            "ldap_uid": uid,
            "display_name": plan.get("display_name"),
            "stamp": st,
            "compose_file": compose_file,
            "service": service,
            "port": port,
            "api_base": api_base,
            "planned": planned,
            "compose": safe_compose,
            "health": None,
            "rollback": rollback,
            "notes": [
                "O4 compose up 失败；未做健康探活",
                "按 rollback 停止残留容器（若有）",
            ],
            "error": err,
        }

    health = probe_api_health(
        api_base,
        paths=health_paths,
        timeout=health_timeout,
        retries=health_retries,
        retry_sleep=health_retry_sleep,
        health_get=health_get,
    )

    if health.get("ok"):
        return {
            "mode": "apply-up",
            "phase": "O4",
            "ok": True,
            "executed": True,
            "ldap_uid": uid,
            "display_name": plan.get("display_name"),
            "stamp": st,
            "compose_file": compose_file,
            "service": service,
            "port": port,
            "api_base": api_base,
            "planned": planned,
            "compose": safe_compose,
            "health": health,
            "rollback": rollback,
            "notes": [
                "O4 已 compose up 且探活通过",
                "回滚说明见 rollback（正常成功路径无需执行）",
            ],
            "error": None,
        }

    # 健康失败 → 尝试 stop
    stop_argv = ["docker", "compose", "-f", compose_file, "stop", service]
    try:
        stop_result = runner(stop_argv)
    except TypeError:
        try:
            stop_result = runner(stop_cmd)
        except TypeError:
            stop_result = {"returncode": 1, "error": "stop_runner_type"}
    if not isinstance(stop_result, dict):
        stop_result = {"returncode": 1, "raw": str(stop_result)[:200]}
    safe_stop = {
        "returncode": stop_result.get("returncode"),
        "argv": stop_result.get("argv") or stop_argv,
        "stderr_tail": str(stop_result.get("stderr_tail") or "")[-400:],
    }

    err = {
        "code": "health_failed",
        "message": health.get("message") or "探活失败",
        "health_error": health.get("error"),
        "attempts_tail": (health.get("attempts") or [])[-4:],
        "auto_stop": safe_stop,
    }
    rb = list(rollback)
    rb.insert(1, f"  # 已尝试自动: {' '.join(stop_argv)} → rc={safe_stop.get('returncode')}")
    return {
        "mode": "apply-up",
        "phase": "O4",
        "ok": False,
        "executed": True,
        "ldap_uid": uid,
        "display_name": plan.get("display_name"),
        "stamp": st,
        "compose_file": compose_file,
        "service": service,
        "port": port,
        "api_base": api_base,
        "planned": planned,
        "compose": safe_compose,
        "health": health,
        "rollback": rb,
        "notes": [
            "O4 探活失败；已尝试 compose stop",
            "请按 rollback 文案确认容器已停，再查 O2/O3 配置",
        ],
        "error": err,
    }


def format_up_apply_text(result: Mapping[str, Any]) -> str:
    """O4 apply-up / dry-run-up 结果人类可读回显。"""
    import json

    lines: list[str] = []
    lines.append(f"# fleet_add {result.get('phase')} · {result.get('mode')}")
    lines.append(f"ok: {result.get('ok')}")
    lines.append(f"executed: {result.get('executed')}")
    lines.append(f"ldap_uid: {result.get('ldap_uid')}")
    lines.append(f"display_name: {result.get('display_name')}")
    lines.append(f"stamp: {result.get('stamp')}")
    lines.append(f"compose_file: {result.get('compose_file')}")
    lines.append(f"service: {result.get('service')}")
    lines.append(f"api_base: {result.get('api_base')}")
    lines.append("")
    for n in result.get("notes") or []:
        lines.append(f"- {n}")
    lines.append("")
    lines.append("## 计划命令")
    lines.append(json.dumps(result.get("planned"), ensure_ascii=False, indent=2))
    lines.append("")
    if result.get("compose") is not None:
        lines.append("## compose 执行")
        lines.append(json.dumps(result.get("compose"), ensure_ascii=False, indent=2))
        lines.append("")
    if result.get("health") is not None:
        lines.append("## health")
        lines.append(json.dumps(result.get("health"), ensure_ascii=False, indent=2))
        lines.append("")
    if result.get("error") is not None:
        lines.append("## error")
        lines.append(json.dumps(result.get("error"), ensure_ascii=False, indent=2))
        lines.append("")
    lines.append("## 回滚")
    for step in result.get("rollback") or []:
        lines.append(
            step
            if str(step).startswith(" ") or str(step).startswith("回滚")
            else f"- {step}"
        )
    return "\n".join(lines) + "\n"
