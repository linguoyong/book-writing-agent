# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：把 FastAPI 后端冻成 book-server.exe。

产物是 one-dir（不是 one-file）：onnxruntime 每次启动解压 40MB+ 的 dll 太慢，
而安装包本来就是个目录，没必要为单文件牺牲启动速度。

构建：
    uv run --directory server --group build pyinstaller server/book-server.spec --noconfirm
产物：
    server/dist/book-server/book-server.exe
"""

from PyInstaller.utils.hooks import collect_all, copy_metadata

datas = []
binaries = []
hiddenimports = []

# 这三个包都是「运行时才知道要加载什么」：jieba 读自己目录下的词典、
# sqlite_vec 用 __file__ 找 vec0.dll、fastembed 按模型名动态 import。
for package in ("jieba", "sqlite_vec", "fastembed"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

# 版本号用 importlib.metadata 读：不带上 dist-info 会直接 ImportError
for distribution in (
    "langchain-core",
    "langchain-openai",
    "langgraph",
    "langgraph-checkpoint-sqlite",
    "deepagents",
    "fastapi",
    "pydantic",
    "uvicorn",
):
    try:
        datas += copy_metadata(distribution)
    except Exception:  # noqa: BLE001 - 没装的包跳过，不阻断构建
        pass

# uvicorn 的实现类全是运行期按名字挑的，静态分析看不到
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
]

# 精简：这些没人 import，带上只是让包变大
excludes = [
    "tkinter",
    "matplotlib",
    "pandas",
    "IPython",
    "pytest",
    "PyInstaller",
]

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="book-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="book-server",
)
