#!/bin/bash
# Mac 配置文件备份脚本
# 将各配置文件复制到 ~/projects/settings/mac/ 对应子目录
#
# 用法:
#   backup-configs.sh                   # 正常模式，跳过 .env 等秘密文件
#   backup-configs.sh --no-success-log  # 静默模式，只输出错误日志
#   backup-configs.sh --include-secrets # 同时备份 .env 等秘密文件（opt-in）

set -e

# 参数解析
NO_SUCCESS_LOG=false
INCLUDE_SECRETS=false
for arg in "$@"; do
    case "$arg" in
        --no-success-log)
            NO_SUCCESS_LOG=true
            ;;
        --include-secrets)
            INCLUDE_SECRETS=true
            ;;
    esac
done

# 目标根目录
SETTINGS_DIR="$HOME/projects/settings/mac"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# 计数器
BACKUP_SUCCESS=0
BACKUP_SKIP=0
BACKUP_FAIL=0

log_info() {
    if [[ "$NO_SUCCESS_LOG" == "false" ]]; then
        echo -e "${BLUE}[INFO]${NC} $1"
    fi
}

log_done() {
    if [[ "$NO_SUCCESS_LOG" == "false" ]]; then
        echo -e "${GREEN}[DONE]${NC} $1"
    fi
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

# 备份函数：复制文件到目标目录
# 默认跳过 .env 秘密文件，除非显式传入 --include-secrets
backup_file() {
    local src="$1"
    local dest_dir="$2"

    if [[ "$INCLUDE_SECRETS" == "false" && "$(basename "$src")" == ".env" ]]; then
        log_info "跳过 (秘密文件，使用 --include-secrets 可备份): $src"
        BACKUP_SKIP=$((BACKUP_SKIP + 1))
        return
    fi

    if [[ -f "$src" ]]; then
        mkdir -p "$dest_dir"
        chmod 700 "$dest_dir"
        if cp -X "$src" "$dest_dir/"; then
            log_done "已备份: $src → $dest_dir/"
            BACKUP_SUCCESS=$((BACKUP_SUCCESS + 1))
        else
            log_error "复制失败: $src"
            BACKUP_FAIL=$((BACKUP_FAIL + 1))
        fi
    else
        log_info "跳过 (不存在): $src"
        BACKUP_SKIP=$((BACKUP_SKIP + 1))
    fi
}

# 检查目标目录，不存在则创建，并限制访问权限（0700）
if [[ ! -d "$SETTINGS_DIR" ]]; then
    if ! mkdir -p "$SETTINGS_DIR" 2>/dev/null; then
        log_error "目标目录不存在且无法创建: $SETTINGS_DIR"
        log_info "请检查 rclone 挂载状态或磁盘空间"
        exit 1
    fi
    chmod 700 "$SETTINGS_DIR"
    log_info "已创建目标目录: $SETTINGS_DIR"
else
    chmod 700 "$SETTINGS_DIR"
fi

if [[ ! -w "$SETTINGS_DIR" ]]; then
    log_error "目标目录不可写: $SETTINGS_DIR"
    exit 1
fi

if [[ "$NO_SUCCESS_LOG" == "false" ]]; then
    echo "========================================"
    echo "  Mac 配置文件备份"
    echo "  目标: $SETTINGS_DIR"
    echo "========================================"
    echo
fi

# ========================================
# tmux
# ========================================
log_info "备份 tmux 配置..."
backup_file "$HOME/.tmux.conf" "$SETTINGS_DIR/tmux"

# ========================================
# vim
# ========================================
log_info "备份 vim 配置..."
backup_file "$HOME/.vimrc" "$SETTINGS_DIR/vim"

# ========================================
# zsh
# ========================================
log_info "备份 zsh 配置..."
backup_file "$HOME/.zshrc" "$SETTINGS_DIR/zsh"

# ========================================
# openviking
# ========================================
log_info "备份 openviking 配置..."
backup_file "$HOME/.openviking/ov.conf" "$SETTINGS_DIR/openviking"
backup_file "$HOME/.openviking/ovcli.conf" "$SETTINGS_DIR/openviking"

# ========================================
# profiled (系统级，需要 sudo)
# ========================================
log_info "备份 profiled 脚本..."
mkdir -p "$SETTINGS_DIR/profiled"
chmod 700 "$SETTINGS_DIR/profiled"
if ls /etc/profile.d/*.sh 1>/dev/null 2>&1; then
    if sudo cp /etc/profile.d/*.sh "$SETTINGS_DIR/profiled/" 2>/dev/null; then
        # 恢复用户权限
        sudo chown "$USER:staff" "$SETTINGS_DIR/profiled/"*.sh 2>/dev/null || true
        log_done "已备份: /etc/profile.d/*.sh → $SETTINGS_DIR/profiled/"
        # 统计成功数量（sudo cp 不走 backup_file）
        sh_count=$(ls /etc/profile.d/*.sh 2>/dev/null | wc -l | tr -d ' ')
        BACKUP_SUCCESS=$((BACKUP_SUCCESS + sh_count))
    else
        log_info "跳过 (sudo 失败): /etc/profile.d/"
        BACKUP_SKIP=$((BACKUP_SKIP + 1))
    fi
else
    log_info "跳过 (无 .sh 文件): /etc/profile.d/"
fi

# ========================================
# opencode
# ========================================
log_info "备份 opencode 配置..."
backup_file "$HOME/.config/opencode/.env" "$SETTINGS_DIR/opencode"
backup_file "$HOME/.config/opencode/opencode.json" "$SETTINGS_DIR/opencode"
backup_file "$HOME/.config/opencode/mcp.json" "$SETTINGS_DIR/opencode"
backup_file "$HOME/.config/opencode/settings.json" "$SETTINGS_DIR/opencode"

# ========================================
# hermes
# ========================================
log_info "备份 hermes 配置..."
backup_file "$HOME/.hermes/config.yaml" "$SETTINGS_DIR/hermes"
backup_file "$HOME/.hermes/.env" "$SETTINGS_DIR/hermes"

# ========================================
# clash
# ========================================
log_info "备份 clash 规则配置..."
backup_file "$HOME/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/rules/my-direct.yaml" "$SETTINGS_DIR/clash/rules"
backup_file "$HOME/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/rules/my-proxy.yaml" "$SETTINGS_DIR/clash/rules"

if [[ "$NO_SUCCESS_LOG" == "false" ]]; then
    echo
    echo "========================================"
    echo "  备份完成！"
    echo "  成功: $BACKUP_SUCCESS | 跳过: $BACKUP_SKIP | 失败: $BACKUP_FAIL"
    echo "========================================"
fi

# 返回码：有失败则返回1
if [[ $BACKUP_FAIL -gt 0 ]]; then
    exit 1
fi
