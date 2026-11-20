# -*- coding: utf-8 -*-
"""
组装 Release 用的下载包：release/yingren-pet-vX.Y-win64.zip

先跑 build_exe.py 生成 dist/影刃Q版.exe，再跑这个。
"""

import os
import shutil
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
VERSION = "2.0"
APP_NAME = "影刃Q版"

EXE = os.path.join(ROOT, "dist", APP_NAME + ".exe")
OUT_DIR = os.path.join(ROOT, "release")
STAGE = os.path.join(OUT_DIR, f"{APP_NAME} v{VERSION}")
ZIP = os.path.join(OUT_DIR, f"yingren-pet-v{VERSION}-win64.zip")

README = f"""{APP_NAME} v{VERSION}
====================================

怎么用
  1. 双击「{APP_NAME}.exe」，屏幕右下角就会站出一个角色（约 121px 高）。
  2. 按住左键拖着他走，松手会自己往下坠一小段再落地回弹。
  3. 拖到屏幕最顶部松手：他会抓住屏幕上边缘挂住，像钟摆一样轻轻晃。
     悬挂时单击角色才会松手落地，直接拖走也可以。
  4. 在任意窗口按 W / A / S / D，他会原地踏起步来（窗口不动）；按住 Shift 变成跑。
     A 朝左、D 朝右；松开 0.15 秒内平滑回到站立；按空格原地跳一下。
  5. 站着不动时他会朝鼠标方向轻轻偏头（最多 3°），但只理身体周围 240px 以内的鼠标。
  6. 单击：眨眼 / 睡着时叫醒；滚轮：调大小（1% 一步）。
  7. 右键菜单：跟它说句话、忘掉刚才的对话、设置、永远置顶、缩放滑杆、
     立即睡觉、键盘控制、隐藏到托盘、退出。
  8. 托盘图标单击 = 显示 / 隐藏；想彻底退出就右键 → 退出。

第一次使用：先填 key（只填一次）
  · 右键菜单 / 托盘菜单 → 「设置…」→ 粘贴 DeepSeek 的 sk-... → 「测试连接」
    → 显示「通了」后点保存。之后 key 会用 Windows DPAPI 加密存进 chat.ini。
  · 不填 key 也能看他会动，但按对话热键会直接弹设置窗。
  · 换电脑后 DPAPI 解不开，会提示重新粘一次 —— 不是 key 错了。

跟他说话
  · Ctrl+Alt+P  纯聊天
  · Ctrl+Alt+S  聊天 + 允许这一轮看一眼你的屏幕（截图只在内存里，不落盘）
  · Ctrl+Alt+F  聊天 + 允许这一轮联网查（气泡底部会标来源）
  · 双击角色 = Ctrl+Alt+P；输入框在屏幕底部居中，右下角有模式灯可以点。
  · 记得最近 6 轮（24 小时），存在 chat_history.json；右键「忘掉刚才的对话」可清空。
  · 三种授权默认全关，只在你按下的那一轮生效，下一轮自动收回。

第一次运行
  · Windows 可能弹「Windows 已保护你的电脑」——点「更多信息」→「仍要运行」。
    这是没有代码签名证书时都会出现的提示。
  · 首次启动会比平时慢 1~2 秒（要把程序解压到系统临时目录）。
  · 需要联网才能聊天；玩独占全屏游戏时挂件看不见，请改用无边框窗口模式。

旁边这几个文件（都在 exe 同目录自动生成）
  · settings.ini        位置 / 缩放 / 开关；删掉就回到默认的右下角。
  · chat.ini            key（加密）/ 模型 / 温度 / 记忆轮数 / 授权开关。
  · chat_history.json   最近 6 轮对话（明文，可删）。
  · pet.log             挂件日志：素材、状态、实测帧率。
  · chat.log            对话日志：首字耗时、错误、截图尺寸。
  · error.log           只有崩溃时才会出现。
  · 想换素材 / 改人设：在 exe 同目录新建 assets 文件夹，放 idle / blink / drag /
    sleep / walk_01 / walk_02 / hang / jump_air / icon 同名 PNG，或改 persona.md；
    不用重新打包（素材缺失只会关掉对应动作）。

隐私
  · 只有你按 Ctrl+Alt+S 的那一下才会截一次屏，图只在内存里活一次，不落盘、不进记忆。
  · 没有定时截屏、没有后台采集；上下文只发给你自己配置的 API 供应商。
  · 对话内容是明文存在你自己电脑上的，不上传到别处。

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
