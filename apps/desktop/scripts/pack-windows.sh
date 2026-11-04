#!/usr/bin/env bash
# Windows 离线打包：GitHub 不可达时用本地工具集顶掉 electron-builder 的下载。
#
# 依赖 ~/.book-agent/pack-tools/ 下的三样东西（脚本会先检查）：
#   nsis/          NSIS 3.0.4.1 解压目录（含 Bin/makensis.exe）
#   res/           nsis-resources 3.4.1 解压目录（含 plugins/）
#   mirror/        给 electron-builder 当二进制镜像：<release>/<file>
#                  - winCodeSign-2.6.0/winCodeSign-2.6.0.7z
#                  - 7zip@1.0.0/7zip-win-x64.tar.gz
#
# 用法：
#   bash scripts/pack-windows.sh            # 出 NSIS 安装包
#   bash scripts/pack-windows.sh --dir      # 只出目录，用来验证
#
# 输出目录默认 release-win，可用 BOOK_AGENT_OUT 改。
# 注意：重复打包到同一个目录可能撞上 Windows 的文件锁（杀软扫 app.asar），
# 报 EBUSY 时换个目录再跑即可。
#
# 输出目录默认 release-win，可用 BOOK_AGENT_OUT 改。
# 注意：重复打包到同一个目录可能撞上 Windows 的文件锁（杀软扫 app.asar），
# 报 EBUSY 时换个目录再跑即可。
#
# 全部能连外网时不需要这个脚本，直接 `pnpm dist` 即可。

set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
tools="${BOOK_AGENT_PACK_TOOLS:-$HOME/.book-agent/pack-tools}"

need() {
    if [ ! -e "$1" ]; then
        echo "缺少 $1" >&2
        echo "把 NSIS / nsis-resources / winCodeSign / 7zip 解压到 $tools 下再试（见脚本顶部说明）" >&2
        exit 1
    fi
}

need "$tools/nsis/Bin/makensis.exe"
need "$tools/res/plugins"
need "$tools/mirror/winCodeSign-2.6.0/winCodeSign-2.6.0.7z"

cd "$here"

# 1) 前端产物
pnpm build

# 2) 冻结后端（server/dist/book-server）
pnpm build:server

# 3) 起一个本地静态服务当 electron-builder 的二进制镜像
port="${BOOK_AGENT_MIRROR_PORT:-8899}"
python -m http.server "$port" --bind 127.0.0.1 --directory "$tools" >/tmp/book-agent-mirror.log 2>&1 &
mirror_pid=$!
trap 'kill $mirror_pid 2>/dev/null || true' EXIT
sleep 1

to_win() {
    # Git Bash 的 /c/... 路径要转成 C:\...，electron-builder 只认后者
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -w "$1"
    else
        printf '%s' "$1"
    fi
}

extra=()
if [ "${1:-}" = "--dir" ]; then
    extra=(--dir)
else
    extra=(--win --x64)
fi

# 4) 复用已安装的 electron，避免再下一次 100MB
env -u NODE_OPTIONS \
    -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy \
    ELECTRON_BUILDER_BINARIES_ALLOW_HTTP=true \
    ELECTRON_BUILDER_BINARIES_MIRROR="http://127.0.0.1:$port/mirror/" \
    ELECTRON_BUILDER_NSIS_DIR="$(to_win "$tools/nsis")" \
    ELECTRON_BUILDER_NSIS_RESOURCES_DIR="$(to_win "$tools/res")" \
    ./node_modules/.bin/electron-builder "${extra[@]}" \
    -c.electronDist=node_modules/electron/dist \
    -c.directories.output="${BOOK_AGENT_OUT:-release-win}"
