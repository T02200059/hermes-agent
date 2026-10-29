"""C05 fleet_add O1：开户 dry-run 计划内核（零落盘）。

设计见 ``owner/docs/design/c05-feishu-user-routing/fleet-add.md`` §5 O1。

主键 = LDAP uid（与主稿 ``fleet_profiles.<ldap_uid>`` 对齐）。
生产 node010 现网路由键仍可能是全名（如 ``yangtianbao``）；切 uid 属另开 Ops，
本模块 **不**改生产、**不**写 overlay / compose / passwd。

复用 ``owner.feishu.profile_routing`` 的人卡 / endpoint 解析，不重写加载语义。
"""

from __future__ import annotations

import copy
import re
from typing import Any, Mapping, MutableMapping, Optional, Sequence

from owner.feishu.profile_routing import (
    _endpoint_from_api_server,
    _hub_only_flags,
)

# 现网舰队 API 端口段（见 c05b / fleet-add 设计）
DEFAULT_PORT_BASE = 26026
DEFAULT_PORT_CEILING = 26099
DEFAULT_CODE_DIR = "/data/hermes/hermes-agent"
DEFAULT_HERMES_ROOT = "/data/hermes"
DEFAULT_HUB_HOME = "/data/hermes"  # Hub HERMES_HOME；.env 在此下

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
) -> dict[str, Any]:
    """目标态 compose 服务草稿：代码 RO + home→/root + profiles→/root/.hermes。"""
    service_name = f"hermes-{ldap_uid}"
    return {
        "service": service_name,
        "container_name": service_name,
        "ports": [f"127.0.0.1:{port}:{port}"],
        "environment": {
            "HERMES_HOME": "/root/.hermes",
            "HERMES_PROFILE": ldap_uid,
            "FEISHU_CONNECTION_MODE": "send_only",
            # 注：生产 node010 现网 HERMES_PROFILE / 路由键仍可能是全名；
            # 切 LDAP uid 另开 Ops，勿在 O1 改生产。
        },
        "volumes": [
            f"{code_dir}:/opt/hermes-agent:ro",
            f"{home_dir}:/root",
            f"{hermes_dir}:/root/.hermes",
        ],
        "notes": [
            "三层挂载：代码 RO + home→/root + profiles→/root/.hermes（.hermes 叠在 home 上）",
            "禁止照抄现网「只挂 /home」单挂模板",
        ],
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
            "value": {"chat_id": channel} if channel else None,
            "action": "set" if channel else "defer_until_dm_chat_id",
            "note": "与 /sethome 真相源对齐；禁止默认指望事后手敲 /sethome",
        },
    }


def build_planned_commands(
    *,
    ldap_uid: str,
    home_dir: str,
    hermes_dir: str,
    service_name: str,
) -> list[dict[str, str]]:
    """将执行的系统命令清单（O1 只列出，不执行）。"""
    return [
        {
            "step": "useradd",
            "cmd": f"id {ldap_uid} >/dev/null 2>&1 || useradd -m -d {home_dir} -s /bin/bash {ldap_uid}",
            "phase": "O3",
        },
        {
            "step": "seed_profile",
            "cmd": f"mkdir -p {hermes_dir} && # 种子 config/sqlite 骨架（模板另议）",
            "phase": "O3",
        },
        {
            "step": "write_compose",
            "cmd": f"# 生成/追加 compose 服务 {service_name}（双挂载草稿见 plan.compose）",
            "phase": "O3",
        },
        {
            "step": "compose_up",
            "cmd": f"docker compose up -d {service_name}",
            "phase": "O4",
        },
        {
            "step": "health",
            "cmd": "# 探活 api_server.url / health（localhost 端口见人卡）",
            "phase": "O4",
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
    hermes_root: str = DEFAULT_HERMES_ROOT,
    hub_home: str = DEFAULT_HUB_HOME,
    hub_allow_all: bool = False,
    port_base: int = DEFAULT_PORT_BASE,
    port_ceiling: int = DEFAULT_PORT_CEILING,
) -> dict[str, Any]:
    """生成完整 dry-run 计划（结构化 dict，可供对话回显 / JSON 打印）。

    **零落盘**：不写 overlay、不 docker、不 useradd、不碰真实密钥文件。
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
    commands = build_planned_commands(
        ldap_uid=uid,
        home_dir=resolved_home,
        hermes_dir=resolved_hermes,
        service_name=compose["service"],
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
            "O1 仅计划：零落盘（不写 overlay / .env / compose，不 useradd，不 docker up）",
            "逻辑主键 = LDAP uid；生产 node010 现网路由键仍可能是全名——切 uid 另开 Ops",
            "开户要点（O2 才真正写）：ou + 已知 tenant user_id → FEISHU_ALLOWED_USERS；一开始设 home channel",
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
        "planned_commands": commands,
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
    lines.append("## compose 双挂草稿")
    lines.append(json.dumps(plan.get("compose"), ensure_ascii=False, indent=2))
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
