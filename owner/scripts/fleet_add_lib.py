"""C05 fleet_add：开户计划（O1 dry-run）与落盘（O2 apply）。

设计见 ``owner/docs/design/c05-feishu-user-routing/fleet-add.md`` §5 O1/O2。

主键 = LDAP uid（与主稿 ``fleet_profiles.<ldap_uid>`` 对齐）。
生产 node010 现网路由键仍可能是全名（如 ``yangtianbao``）；切 uid 属另开 Ops。

- **O1** ``plan_fleet_add``：零落盘计划。
- **O2** ``apply_fleet_add``：写 overlay 人卡 + ``user_profile_routes``、目标/Hub
  ``FEISHU_ALLOWED_USERS``、目标 ``FEISHU_HOME_CHANNEL`` / ``platforms.feishu.home_channel``；
  可选备份与回滚说明。**不** compose up、**不** useradd。
- 默认拒绝写 ``/data/hermes`` 生产路径，除非 ``allow_production=True``。

复用 ``owner.feishu.profile_routing`` 的人卡 / endpoint 解析，不重写加载语义。
"""

from __future__ import annotations

import copy
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
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
            "value": (
                {"platform": "feishu", "chat_id": channel, "name": "Home"}
                if channel
                else None
            ),
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
            "默认 dry-run：零落盘（不写 overlay / .env / compose，不 useradd，不 docker up）",
            "逻辑主键 = LDAP uid；生产 node010 现网路由键仍可能是全名——切 uid 另开 Ops",
            "O2 --apply 才写：人卡 + routes + FEISHU_ALLOWED_USERS（ou±tenant）+ home channel；仍不 docker/useradd",
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
