<div align="center">

# 影刃 Q 版 · Windows 桌面挂件

**一个站在屏幕角落的刀客：会呼吸、会眨眼、能被拖着走，还会在你按 WASD 时行走、按空格跳一下，拖到屏幕顶上就挂住晃。**

[![Release](https://img.shields.io/github/v/release/xiao-bu123/yingren-desktop-pet-Q-?style=flat-square&color=4FA3F7&label=release)](https://github.com/xiao-bu123/yingren-desktop-pet-Q-/releases)
[![Platform](https://img.shields.io/badge/Windows-10%20%2F%2011-0078D6?style=flat-square&logo=windows&logoColor=white)](#-系统要求)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](#-从源码运行)
[![PySide6](https://img.shields.io/badge/PySide6-6.6%2B-41CD52?style=flat-square&logo=qt&logoColor=white)](requirements.txt)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)

</div>

<div align="center">
  <img src="docs/demo.gif" width="300" alt="呼吸 → 原地踏步 → 收势回站立">
</div>

<p align="center"><sub>上面这段是真实录屏：呼吸 → 按 D 原地踏步 → 松手收势，全程窗口位置没有动过。</sub></p>

---

##  下载即用（不需要装任何东西）

1. 到 **[Releases](https://github.com/xiao-bu123/yingren-desktop-pet-Q-/releases)** 下载 `yingren-pet-v1.2-win64.zip`（40 MB）
2. 解压，双击 **`影刃Q版.exe`**
3. 如果弹出「Windows 已保护你的电脑」→ 点 **更多信息 → 仍要运行**

> 这只是没买代码签名证书的常规提示。程序不联网、不写注册表、不收集任何数据。

单文件 exe 自带 Python 与 Qt，`settings.ini` 和 `pet.log` 会生成在 exe 旁边。

## 功能拆解

| | |
|---|---|
|  **呼吸** | 3.2 秒一个周期，纵向 1.00→1.02，以**脚底为支点**缩放（不会像气球一样上下飘） |
|  **眨眼** | 每 3~6 秒随机眨一次，闭眼 0.15 秒；睡眠中不眨眼 |
|  **拖着走** | 跟手不做插值，按水平速度左右倾斜 ±6°；松手 0.25s 加速下落 + 回弹，不是瞬移 |
|  **挂在屏幕顶** | 拖到屏幕上边缘松手，他会**单手抓住屏幕**挂住，绕**拳心**做 ±2°、2.6s 的钟摆；单击才松手 |
|  **空格跳跃** | 蓄力 → 腾空 0.5s（最高 70px）→ 落地压扁回弹，落点和起跳点误差 **0px** |
|  **滑杆缩放** | 右键菜单里一条滑杆，22%~35% 连续可调，脚底钉在原地 |
|  **键盘踏步** | 任意窗口按 `W`/`A`/`S`/`D` 原地踏起来，`Shift` 加速；`A` 朝左镜像、`D` 朝右 |
|  **跟着鼠标看** | 只在身体周围 **240px** 的圈里理你：圈内朝光标轻偏 ±3°、水平微移 ±2px，越靠圈边越轻，出圈立刻回正；鼠标停 1 秒也会自己回正 |
|  **会累** | 闲置 5 分钟趴下睡着（呼吸放慢到 4.5s），点一下就叫醒 |
|  **点击穿透** | 只有不透明像素能点，透明区域直接打穿到下层窗口 |
|  **不打扰** | 不进任务栏、不抢焦点、没有控制按钮；所有设置都在右键菜单和托盘里 |

<p align="center">
  <img src="docs/states.png" width="760" alt="站立 / 踏步两帧 / 朝左 / 拖拽 / 睡着">
</p>

<p align="center">
  <img src="docs/hang-jump.png" width="620" alt="悬挂（绕拳心摆动）与腾空的两帧">
  <br>
  <sub>从左到右：挂在屏幕顶、悬挂时的另一帧、空格腾空</sub>
</p>

<p align="center">
  <img src="docs/mouse-follow.png" width="560" alt="鼠标在左边和右边时的轻微倾斜">
  <br>
  <sub>鼠标在左 / 在右：只偏 3°，窗口坐标一动不动</sub>
</p>

<p align="center">
  <img src="docs/follow-range.png" width="620" alt="240px 交互圈：圈内跟随、圈外完全不理会">
  <br>
  <sub>只对进入身体周围 240px 的光标有反应：圈内 60% 满幅，靠边渐弱，出圈回正</sub>
</p>

## 🎮 操作

| 操作 | 行为 |
|---|---|
| 左键按住拖动 | 悬空姿势贴着光标走，按水平速度倾斜 ±6° |
| 松开左键 | 0.25s ease-out 向下落一段 + 缩放 1.02→1.00 回弹 |
| 左键单击 | 睡着时叫醒 / 醒着时眨一次眼；**悬挂时 = 松手落地** |
| 左键双击 | 睡着 ↔ 醒来（悬挂时无反应） |
| 滚轮 | 缩放 ±1%（22%~35%），以脚底为锚点 |
| 右键 | 永远置顶 / 缩放滑杆 / 立即睡觉 / 键盘控制 / 隐藏到托盘 / 退出 |
| `W` `A` `S` `D` | 原地踏步（窗口不动），按住 `Shift` = 跑 |
| `空格` | 原地跳：蓄力 0.12s → 腾空 0.5s → 落地 0.12s，落点精确回到起跳点 |
| 拖到屏幕最顶部松手 | 抓住屏幕上边缘挂住（窗口顶边距可用区顶边 < 24px 时触发） |
| 托盘图标单击 | 显示 / 隐藏 |

<p align="center">
  <img src="docs/menu.png" width="330" alt="右键菜单：滑杆缩放 + 键盘控制开关">
</p>

**悬挂时的规矩**：只有单击角色才会松手（0.35s 自由落体到地面并压扁回弹），直接拖动可以带走；
`空格` / `WASD` / 双击在悬挂时一律无反应，也不会在悬挂中睡着。

## 🛠 从源码运行

```bash
git clone https://github.com/xiao-bu123/yingren-desktop-pet-Q-.git
cd yingren-desktop-pet-Q-
pip install -r requirements.txt
python pet.py
```

Windows 上也可以直接双击 `start.bat`（用 `pythonw` 启动，任务栏里不会多一个黑框）。
想看到实时日志和帧率就用 `start_debug.bat`。

##  系统要求

- Windows 10 / 11 64 位（下载 exe 的用户**不需要**装 Python 或 Qt）
- 从源码运行需要 Python 3.10+ 与 PySide6 6.6+（见 `requirements.txt`）
- 单文件 exe 约 40 MB，内存占用约 110 MB；不写注册表、不联网、不进任务栏

##  换素材

把 `assets/` 里的同名 PNG 换掉即可（1536×1536 透明 PNG），代码会**自动重新计算脚底锚点**，不用改任何数字：

| 文件 | 用途 |
|---|---|
| `idle.png` | 站立睁眼（主姿态） |
| `blink.png` | 站立闭眼（与 idle 除眼睛外完全一致，插帧不会跳） |
| `drag.png` | 悬空，双手举过头顶 |
| `sleep.png` | 侧趴睡着 |
| `walk_01.png` / `walk_02.png` | 原地踏步的两帧（同高、同底边、同中心） |
| `hang.png` | 单手抓住上方（拳心就是悬挂的支点） |
| `jump_air.png` | 腾空，双腿收起 |
| `icon.png` | 托盘图标 256×256 |

某个动作的素材缺失时，只会关掉对应动作并在日志里说明，不影响启动。
打包成 exe 之后想换素材，不用重新打包：在 exe 同目录建一个 `assets/` 放同名图片，就会覆盖内置素材。

##  想调手感

所有参数都在 `pet.py` 顶部的 `CONFIG` 类里：缩放下限/上限、呼吸周期与幅度、眨眼间隔、
踏步帧时长与颠簸幅度、拖拽倾斜增益、落地时长、悬挂触发距离与摆动幅度、跳跃高度与三段时长、
跟随鼠标的**交互圈半径**、倾角与回正时间、初始位置边距……改完重启即可。

##  实现上比较讲究的几处

- **点击穿透**：按「形变包络」（呼吸最高点、倾斜两端、踏步颠簸上下限、悬挂 ±2°、跳跃 0.90~1.03）
  渲染出 `QRegion` 再 `setMask()`，结果按 `(形状族, 缩放, DPI)` 缓存 —— 整套动画过程中遮罩**零重建**，
  也不会被切掉边；透明区域实测 `WindowFromPoint` 命中的是下层窗口。
- **支点**：普通状态绕脚底，悬挂绕**拳心**（绕窗口中心会变成"整块牌子在晃"），绘制和遮罩用同一个支点。
- **帧率**：`PreciseTimer` 驱动，拖拽/踏步 60 帧、静止 30 帧自动切换
  （Windows 的 `CoarseTimer` 会把 33ms 量化成 46.8ms，这点踩过坑）。
- **重绘**：只在姿态真的变化时发生，拖拽时窗口只是位移、倾斜稳定后完全不重绘。
- **键盘**：Win32 `GetAsyncKeyState` 只读轮询（每 2 帧一次），不是全局钩子、不拦截、不注入、不吞字。
- **跟随鼠标**：独立 50ms 采样 + 每帧缓动，只改绘制层，窗口坐标全程不动。
  以身体中心为圆心、240px 为半径圈出交互范围，圈内 60% 满幅、外 40% smoothstep 淡出，
  圈外一律不响应 —— 光标在屏幕另一端也不会把角色拽歪。

实测（1920×1080 / 100% 缩放，i7 级别 CPU）：

| 场景 | CPU（单核） | CPU（全核） | 内存 |
|---|---|---|---|
| 静止（30 帧） | ~2.0% | **0.12%** | 110 MB |
| 原地踏步（60 帧） | ~5.9% | 0.37% | 110 MB |
| 拖拽（60 帧） | ~1.7% | 0.10% | 110 MB |
| 悬挂摇摆（30 帧） | ~1.3% | **0.2%** | 110 MB |

拖拽跟手误差实测 **0.0px**（60 步往返），遮罩重建 0.35ms/次、单帧绘制 0.09ms。

##  打包

```bash
pip install pyinstaller
python build_exe.py      # → dist/影刃Q版.exe（约 40 MB，单文件）
python make_release.py   # → release/yingren-pet-v1.2-win64.zip
```

##  目录结构

```
.
├── pet.py              # 全部逻辑（单文件，中文注释）
├── assets/             # 9 张素材（含 hang / jump_air）
├── docs/               # README 用的图
├── start.bat           # 双击启动（pythonw，无黑框）
├── start_debug.bat     # 带控制台启动，能看 pet.log
├── build_exe.py        # 打包成免安装 exe
├── make_release.py     # 生成 Release 用的 zip
├── requirements.txt
├── CHANGELOG.md
└── LICENSE
```

##  FAQ

**按 WASD 没反应？**
右键菜单看「键盘控制」是不是被关掉了；另外**睡着状态故意不响应键盘**（否则你打字时它会一直醒着），点一下就叫醒。

**怎么让它从屏幕顶上下来？**
单击角色即可松手落地。直接按住拖动也能把它从边缘拿下来。

**托盘里找不到图标？**
Win11 默认把新图标收进「隐藏的图标」，点任务栏那个 `^` 拖出来固定即可。

**怎么彻底退出？**
右键 → 退出，或托盘菜单 → 退出。位置、缩放和键盘开关都会记住。

**第一次启动要等一两秒？**
one-file 打包会把程序解压到 `%TEMP%`，属正常现象。

## 📄 许可与致谢

代码 [MIT](LICENSE)。

角色立绘是《影之刃零》主角「魂」的同人二创，版权归原权利方所有，**仅限个人学习交流、禁止商用**；
MIT 许可不覆盖 `assets/` 下的图片，要用于其他用途请自行替换。

如果你觉得有意思，点个 Star ⭐ 就好。
