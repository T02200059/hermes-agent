#!/usr/bin/env python3
"""C05 fleet_add：舰队开户 CLI（O1 = 默认 dry-run，零落盘）。

用法（本机假夹具）::

    python -m owner.scripts.fleet_add \\
      --ldap-uid alice --display-name 爱丽丝 \\
      --open-id ou_alice --fixture /path/to/fixture.yaml

设计：``owner/docs/design/c05-feishu-user-routing/fleet-add.md``。
O2+（真正写 overlay / allowlist / compose）尚未实现；``--apply`` 会拒绝。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Hermes 舰队开户（O1 dry-run 默认；零落盘）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python -m owner.scripts.fleet_add \\\n"
            "    --ldap-uid alice --display-name 爱丽丝 \\\n"
            "    --open-id ou_alice --fixture tests/owner/fixtures/fleet_add_overlay.yaml\n"
        ),
    )
    p.add_argument("--ldap-uid", required=True, help="主键 LDAP uid（= 逻辑 profile）")
    p.add_argument("--display-name", required=True, help="中文展示名")
    p.add_argument(
        "--open-id",
        action="append",
        default=[],
        dest="open_ids",
        help="飞书 ou_*（可多次）；写入 user_profile_routes 与 allowlist 计划",
    )
    p.add_argument(
        "--tenant-user-id",
        action="append",
        default=[],
        dest="tenant_user_ids",
        help="飞书 tenant user_id（可多次；与 ou 一并进 allowlist 计划）",
    )
    p.add_argument(
        "--home-channel",
        default="",
        help="FEISHU_HOME_CHANNEL（优先 oc_* DM chat_id）",
    )
    p.add_argument("--hub-only-feishu", action="store_true")
    p.add_argument("--hub-only-api", action="store_true")
    p.add_argument("--hermes-dir", default="", help="覆盖 docker.hermes_dir")
    p.add_argument("--home-dir", default="", help="覆盖 docker.home_dir")
    p.add_argument("--port", type=int, default=None, help="指定端口；默认 max(已用)+1")
    p.add_argument(
        "--used-port",
        action="append",
        type=int,
        default=[],
        dest="used_ports",
        help="额外已占用端口（夹具；可多次）",
    )
    p.add_argument(
        "--overlay",
        default="",
        help="overlay.yaml 路径（默认 $HERMES_HOME/overlay.yaml）",
    )
    p.add_argument(
        "--fixture",
        default="",
        help="假 overlay YAML（与 --overlay 合并；测试/对话用，无真 key）",
    )
    p.add_argument("--app-id", default="", help="feishu.bots.<app_id>（多 bot 时必填）")
    p.add_argument("--code-dir", default="", help="compose 代码 RO 源路径")
    p.add_argument("--hermes-root", default="", help="推导 profiles 根，默认 /data/hermes")
    p.add_argument("--hub-home", default="", help="Hub HERMES_HOME，默认 /data/hermes")
    p.add_argument(
        "--hub-allow-all",
        action="store_true",
        help="计划中跳过 Hub FEISHU_ALLOWED_USERS 双写（文档钉死 ALLOW_ALL）",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="只打印计划（默认；O1 强制）",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="真正落盘（O2+；当前未实现，会拒绝）",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="stdout 只打 JSON 计划（便于对话/工具消费）",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    # 延迟 import，保证 ``python owner/scripts/fleet_add.py`` 也能跑
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from owner.scripts.fleet_add_lib import (
        DEFAULT_CODE_DIR,
        DEFAULT_HERMES_ROOT,
        DEFAULT_HUB_HOME,
        FleetAddError,
        format_plan_text,
        load_overlay_yaml,
        merge_fixture_overlay,
        plan_fleet_add,
    )

    args = _parse_args(argv)

    if args.apply:
        print(
            "错误: --apply 属 O2+，尚未实现。O1 仅支持 dry-run（默认）。",
            file=sys.stderr,
        )
        return 2

    overlay_path = args.overlay.strip() or str(
        Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")) / "overlay.yaml"
    )
    overlay = load_overlay_yaml(overlay_path)
    if args.fixture.strip():
        fixture = load_overlay_yaml(args.fixture.strip())
        overlay = merge_fixture_overlay(overlay, fixture)

    try:
        plan = plan_fleet_add(
            ldap_uid=args.ldap_uid,
            display_name=args.display_name,
            open_ids=args.open_ids,
            tenant_user_ids=args.tenant_user_ids,
            home_channel=args.home_channel or None,
            hub_only_feishu=args.hub_only_feishu,
            hub_only_api=args.hub_only_api,
            hermes_dir=args.hermes_dir or None,
            home_dir=args.home_dir or None,
            preferred_port=args.port,
            extra_used_ports=args.used_ports,
            overlay=overlay,
            app_id=args.app_id or os.environ.get("FEISHU_APP_ID", ""),
            code_dir=args.code_dir or DEFAULT_CODE_DIR,
            hermes_root=args.hermes_root or DEFAULT_HERMES_ROOT,
            hub_home=args.hub_home or DEFAULT_HUB_HOME,
            hub_allow_all=args.hub_allow_all,
        )
    except FleetAddError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print(format_plan_text(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
