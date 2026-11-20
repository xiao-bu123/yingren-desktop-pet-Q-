# -*- coding: utf-8 -*-
"""
把挂件打包成免安装 exe（PyInstaller one-file）。

用法：  python build_exe.py
产物：  dist/影刃Q版.exe     （单文件，双击即用；素材已打包进去）

重新打包前请先关闭正在运行的挂件，否则 exe 会被占用。
"""

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_NAME = "影刃Q版"
BUILD_DIR = os.path.join(ROOT, "_build")
DIST_DIR = os.path.join(ROOT, "dist")
PYLIBS = os.path.join(ROOT, ".pylibs")


def make_icon() -> str:
    """把 assets/icon.png 转成多尺寸 ico（优先 Pillow，退化为 Qt 单尺寸）。"""
    src = os.path.join(ROOT, "assets", "icon.png")
    if not os.path.exists(src):
        return ""
    os.makedirs(BUILD_DIR, exist_ok=True)
    out = os.path.join(BUILD_DIR, "app.ico")
    try:
        from PIL import Image
        img = Image.open(src).convert("RGBA")
        img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        return out
    except Exception:
        pass
    try:
        if PYLIBS and PYLIBS not in sys.path:
            sys.path.insert(0, PYLIBS)
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage
        img = QImage(src).scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
        if img.save(out):
            return out
    except Exception:
        pass
    return ""


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[错误] 没有找到 PyInstaller，请先执行：pip install pyinstaller")
        return 1

    icon = make_icon()
    if icon:
        print(f"[1/3] 图标已生成：{icon}")

    env = dict(os.environ)
    extra = [p for p in (PYLIBS, env.get("PYTHONPATH", "")) if p]
    env["PYTHONPATH"] = os.pathsep.join(extra)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile", "--windowed",
        "--name", APP_NAME,
        "--distpath", DIST_DIR,
        "--workpath", os.path.join(BUILD_DIR, "work"),
        "--specpath", BUILD_DIR,
        "--add-data", f"{os.path.join(ROOT, 'assets')}{os.pathsep}assets",
        "--hidden-import", "chat_core",
        "--hidden-import", "chat_ui",
        "--exclude-module", "tkinter",
        "--exclude-module", "unittest",
        "--exclude-module", "pydoc",
        "--exclude-module", "PySide6.QtQml",
    ]
    if icon:
        cmd += ["--icon", icon]
    cmd.append("pet.py")

    print("[2/3] 开始打包（首次约 1~3 分钟）……")
    code = subprocess.call(cmd, cwd=ROOT, env=env)
    if code != 0:
        print(f"[错误] PyInstaller 退出码 {code}")
        return code

    exe = os.path.join(DIST_DIR, APP_NAME + ".exe")
    if not os.path.exists(exe):
        print("[错误] 没有生成 exe")
        return 1
    print(f"[3/3] 完成：{exe}  ({os.path.getsize(exe) / 1024 / 1024:.1f} MB)")
    print("       把 exe 拷到任意目录双击即可；素材已内置，")
    print("       如需换素材，在 exe 同目录放一个 assets/ 文件夹即可覆盖。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
