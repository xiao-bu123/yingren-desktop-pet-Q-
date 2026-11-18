# -*- coding: utf-8 -*-
"""
组装 Release 用的下载包：release/影刃Q版-vX.Y-win64.zip

先跑 build_exe.py 生成 dist/影刃Q版.exe，再跑这个。
"""

import os
import shutil
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
VERSION = "1.1"
APP_NAME = "影刃Q版"

EXE = os.path.join(ROOT, "dist", APP_NAME + ".exe")
OUT_DIR = os.path.join(ROOT, "release")
STAGE = os.path.join(OUT_DIR, f"{APP_NAME} v{VERSION}")
ZIP = os.path.join(OUT_DIR, f"{APP_NAME}-v{VERSION}-win64.zip")

README = f"""{APP_NAME} v{VERSION}
====================================

怎么用
  1. 双击「{APP_NAME}.exe」，屏幕右下角就会站出一个角色（约 121px 高）。
  2. 按住左键拖着他走，松手会自己往下坠一小段再落地回弹。
  3. 单击：眨眼 / 睡着时叫醒；双击：趴下睡 / 站起来；滚轮：调大小（1% 一步）。
  4. 右键菜单：永远置顶、缩放滑杆、立即睡觉、键盘控制、隐藏到托盘、退出。
  5. 在任意窗口按 W / A / S / D，他会原地踏起步来（窗口不动）；按住 Shift 变成跑。
     A 朝左、D 朝右；松开 0.15 秒内平滑回到站立。
  6. 托盘图标单击 = 显示 / 隐藏；想彻底退出就右键 → 退出。

第一次运行
  · Windows 可能弹「Windows 已保护你的电脑」——点「更多信息」→「仍要运行」。
    这是没有代码签名证书时都会出现的提示；程序不联网、不写注册表、不收集任何数据。
  · 首次启动会比平时慢 1~2 秒（要把程序解压到系统临时目录）。

旁边这几个文件
  · settings.ini  记录位置 / 缩放 / 开关；删掉它就回到默认的右下角。
  · pet.log       启动日志（素材、状态切换、实测帧率），出问题先看它。
  · error.log     只有崩溃时才会出现。
  · 想换素材：在本 exe 同目录新建 assets 文件夹，放 idle / blink / drag / sleep /
    walk_01 / walk_02 / icon 同名 PNG 即可覆盖内置素材（1536×1536 透明 PNG）。

系统要求
  Windows 10 / 11 64 位，不需要安装 Python 或 Qt。
"""


def main() -> int:
    if not os.path.exists(EXE):
        print("没有找到 exe，先运行 build_exe.py")
        return 1
    os.makedirs(OUT_DIR, exist_ok=True)
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    os.makedirs(STAGE)

    shutil.copy2(EXE, STAGE)
    with open(os.path.join(STAGE, "使用说明.txt"), "w", encoding="utf-8-sig") as fh:
        fh.write(README)

    if os.path.exists(ZIP):
        os.remove(ZIP)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in sorted(os.listdir(STAGE)):
            zf.write(os.path.join(STAGE, name), os.path.join(f"{APP_NAME} v{VERSION}", name))

    print(f"下载包：{ZIP}  ({os.path.getsize(ZIP) / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
