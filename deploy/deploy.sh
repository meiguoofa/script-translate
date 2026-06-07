#!/usr/bin/env bash
# 一键部署脚本：构建前端 + 同步代码 + 安装依赖 + 重启服务
#
# 用法:
#   ./deploy/deploy.sh                    # 全量部署（前端 + 后端 + systemd）
#   ./deploy/deploy.sh --frontend-only    # 只重建并同步前端（最常用）
#   ./deploy/deploy.sh --backend-only     # 只同步后端代码 + 重启 service
#   ./deploy/deploy.sh --skip-install     # 跳过 npm/pip 安装步骤
#   ./deploy/deploy.sh --update-nginx     # 额外同步 deploy/nginx.conf 并 reload
#   ./deploy/deploy.sh --update-systemd   # 额外同步 systemd unit 并 daemon-reload
#   ./deploy/deploy.sh --dry-run          # 只打印将执行的操作
#
# 默认不会动 nginx 配置（线上版本可能与仓库不同），需要时显式加 --update-nginx
#
# 环境变量:
#   DEPLOY_ROOT    部署目标根目录（默认 /opt/script-translate）
#   SERVICE_NAME   systemd 服务名（默认 script-translate）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEPLOY_ROOT="${DEPLOY_ROOT:-/opt/script-translate}"
SERVICE_NAME="${SERVICE_NAME:-script-translate}"

MODE="full"
SKIP_INSTALL=0
DRY_RUN=0
UPDATE_NGINX=0
UPDATE_SYSTEMD=0

for arg in "$@"; do
  case "$arg" in
    --frontend-only) MODE="frontend" ;;
    --backend-only)  MODE="backend" ;;
    --skip-install)  SKIP_INSTALL=1 ;;
    --update-nginx)  UPDATE_NGINX=1 ;;
    --update-systemd) UPDATE_SYSTEMD=1 ;;
    --dry-run)       DRY_RUN=1 ;;
    -h|--help)
      sed -n '2,17p' "$0"
      exit 0
      ;;
    *) echo "未知参数: $arg" >&2; exit 2 ;;
  esac
done

c_blue="\033[1;34m"
c_green="\033[1;32m"
c_yellow="\033[1;33m"
c_reset="\033[0m"

log()  { printf "${c_blue}[deploy]${c_reset} %s\n" "$*"; }
ok()   { printf "${c_green}[ok]${c_reset}     %s\n" "$*"; }
warn() { printf "${c_yellow}[warn]${c_reset}   %s\n" "$*"; }

run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf "  $ %s\n" "$*"
  else
    "$@"
  fi
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "缺少命令: $1" >&2
    exit 1
  fi
}

if [[ $EUID -ne 0 ]]; then
  warn "建议以 root 运行（systemctl / nginx reload 需要 root）。"
fi

log "仓库:    ${REPO_ROOT}"
log "目标:    ${DEPLOY_ROOT}"
log "模式:    ${MODE}"
[[ "$DRY_RUN" -eq 1 ]] && log "DRY-RUN: 仅打印命令"

require_cmd rsync

deploy_frontend() {
  log "==> 构建前端"
  require_cmd npm

  if [[ "$SKIP_INSTALL" -ne 1 ]]; then
    run bash -c "cd '${REPO_ROOT}/frontend' && npm install --no-audit --no-fund"
  else
    log "跳过 npm install"
  fi

  run bash -c "cd '${REPO_ROOT}/frontend' && npm run build"

  log "==> 同步 dist 到 ${DEPLOY_ROOT}/frontend/dist/"
  run mkdir -p "${DEPLOY_ROOT}/frontend/dist"
  run rsync -a --delete \
    "${REPO_ROOT}/frontend/dist/" \
    "${DEPLOY_ROOT}/frontend/dist/"

  ok "前端部署完成"
}

deploy_backend() {
  log "==> 同步后端源码到 ${DEPLOY_ROOT}/backend/"
  run mkdir -p "${DEPLOY_ROOT}/backend"
  # 保留运行时数据：data/ storage/ .env 不被覆盖或删除
  run rsync -a --delete \
    --exclude=".env" \
    --exclude="data/" \
    --exclude="storage/" \
    --exclude="__pycache__/" \
    --exclude="*.pyc" \
    --exclude="*.egg-info/" \
    --exclude=".pytest_cache/" \
    --exclude=".mypy_cache/" \
    "${REPO_ROOT}/backend/" \
    "${DEPLOY_ROOT}/backend/"

  if [[ ! -f "${DEPLOY_ROOT}/backend/.env" ]]; then
    if [[ -f "${REPO_ROOT}/backend/.env.example" ]]; then
      warn ".env 不存在，已从 .env.example 复制（请手动填入 API key）"
      run cp "${REPO_ROOT}/backend/.env.example" "${DEPLOY_ROOT}/backend/.env"
    else
      warn "${DEPLOY_ROOT}/backend/.env 不存在且无 .env.example"
    fi
  fi

  if [[ "$SKIP_INSTALL" -ne 1 ]]; then
    log "==> 安装/更新 Python 依赖到 ${DEPLOY_ROOT}/.venv"
    require_cmd python3
    if [[ ! -x "${DEPLOY_ROOT}/.venv/bin/python" ]]; then
      log "venv 不存在，创建中"
      run python3 -m venv "${DEPLOY_ROOT}/.venv"
    fi
    run "${DEPLOY_ROOT}/.venv/bin/pip" install --upgrade pip
    run "${DEPLOY_ROOT}/.venv/bin/pip" install -e "${DEPLOY_ROOT}/backend"
  else
    log "跳过 pip install"
  fi

  ok "后端代码同步完成"
}

deploy_systemd_unit() {
  if [[ "$UPDATE_SYSTEMD" -ne 1 ]]; then
    return
  fi
  local src="${REPO_ROOT}/deploy/${SERVICE_NAME}.service"
  local dst="/etc/systemd/system/${SERVICE_NAME}.service"
  if [[ ! -f "$src" ]]; then
    warn "未找到 ${src}，跳过 systemd unit 同步"
    return
  fi
  if ! cmp -s "$src" "$dst" 2>/dev/null; then
    log "==> 更新 systemd unit ${dst}"
    run cp "$src" "$dst"
    run systemctl daemon-reload
  else
    log "systemd unit 无变化"
  fi
}

deploy_nginx_conf() {
  if [[ "$UPDATE_NGINX" -ne 1 ]]; then
    return
  fi
  local src="${REPO_ROOT}/deploy/nginx.conf"
  local dst=""
  # 自动检测线上配置应放在哪里
  if [[ -f "/etc/nginx/conf.d/${SERVICE_NAME}.conf" ]]; then
    dst="/etc/nginx/conf.d/${SERVICE_NAME}.conf"
  elif [[ -d /etc/nginx/sites-enabled ]]; then
    dst="/etc/nginx/sites-enabled/${SERVICE_NAME}.conf"
  else
    warn "未识别 nginx 配置目录，请手动维护"
    return
  fi
  if [[ ! -f "$src" ]]; then
    warn "未找到 ${src}，跳过 nginx 配置同步"
    return
  fi
  if cmp -s "$src" "$dst" 2>/dev/null; then
    log "nginx 配置无变化"
    return
  fi
  log "==> 备份并更新 nginx 配置 ${dst}"
  run cp "$dst" "${dst}.bak.$(date +%s)" 2>/dev/null || true
  run cp "$src" "$dst"
  if command -v nginx >/dev/null 2>&1; then
    log "==> nginx -t"
    if ! run nginx -t; then
      warn "nginx -t 失败，回滚配置"
      run cp "${dst}.bak."* "$dst" 2>/dev/null || true
      exit 1
    fi
    log "==> systemctl reload nginx"
    run systemctl reload nginx
  else
    warn "未找到 nginx 命令，请手动 reload"
  fi
}

restart_service() {
  if ! command -v systemctl >/dev/null 2>&1; then
    warn "无 systemctl，跳过服务重启"
    return
  fi
  if ! systemctl list-unit-files --no-legend --no-pager "${SERVICE_NAME}.service" 2>/dev/null \
        | grep -q "^${SERVICE_NAME}\.service"; then
    warn "服务 ${SERVICE_NAME} 未安装，跳过重启"
    return
  fi
  log "==> 重启 ${SERVICE_NAME}"
  run systemctl restart "${SERVICE_NAME}"
  if [[ "$DRY_RUN" -ne 1 ]]; then
    sleep 1
    if systemctl is-active --quiet "${SERVICE_NAME}"; then
      ok "${SERVICE_NAME} 已运行"
    else
      echo "服务启动失败，查看日志:" >&2
      systemctl status "${SERVICE_NAME}" --no-pager -n 20 >&2 || true
      exit 1
    fi
  fi
}

smoke_test() {
  if [[ "$DRY_RUN" -eq 1 ]]; then return; fi
  if ! command -v curl >/dev/null 2>&1; then return; fi
  local port
  port=$(grep -E '^\s*listen\s+[0-9]+' "${REPO_ROOT}/deploy/nginx.conf" 2>/dev/null \
    | head -1 | awk '{print $2}' | tr -d ';' || true)
  port="${port:-8900}"
  log "==> 冒烟测试 http://127.0.0.1:${port}/api/health"
  local code
  code=$(curl -sk -o /dev/null -w "%{http_code}" "http://127.0.0.1:${port}/api/health" || echo "000")
  if [[ "$code" == "200" ]]; then
    ok "/api/health 返回 200"
  else
    warn "/api/health 返回 ${code}（如果 nginx 走 https，可忽略）"
  fi
}

case "$MODE" in
  frontend)
    deploy_frontend
    deploy_nginx_conf
    ;;
  backend)
    deploy_backend
    deploy_systemd_unit
    restart_service
    ;;
  full)
    deploy_frontend
    deploy_backend
    deploy_systemd_unit
    deploy_nginx_conf
    restart_service
    smoke_test
    ;;
esac

ok "部署完成 ✅"