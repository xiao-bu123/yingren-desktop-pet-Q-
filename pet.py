# -*- coding: utf-8 -*-
"""
桌面挂件「影刃 Q 版」——单文件 PySide6 实现。

功能：无边框 / 透明背景 / 永远置顶 / 不占任务栏 / 透明区域鼠标穿透 /
呼吸、眨眼、拖拽、落地回弹、闲置入睡、滚轮缩放、位置记忆、托盘与右键菜单。

直接运行：  pythonw pet.py      （或双击 start.bat）
"""

from __future__ import annotations

import math
import os
import random
import sys
import time
import traceback
from datetime import datetime

# ----------------------------------------------------------------------------
# 目录约定
#   • 源码运行：脚本目录 = 数据目录（.pylibs 里的 PySide6 会被自动加进 sys.path）
#   • 打包成 exe：exe 所在目录 = 数据目录（assets / settings.ini / pet.log 都放这儿，
#     方便直接换素材）；打包进 exe 的只读资源在 BUNDLE_DIR，作为素材兜底
# ----------------------------------------------------------------------------
FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    BUNDLE_DIR = getattr(sys, "_MEIPASS", BASE_DIR)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = BASE_DIR
    _BUNDLED_LIBS = os.path.join(BASE_DIR, ".pylibs")
    if os.path.isdir(_BUNDLED_LIBS) and _BUNDLED_LIBS not in sys.path:
        sys.path.insert(0, _BUNDLED_LIBS)

from PySide6.QtCore import (QEvent, QPoint, QPointF, QRect, QRectF, QSettings,
                            QSize, Qt, QTimer)
from PySide6.QtGui import (QBitmap, QCursor, QGuiApplication, QIcon, QPainter,
                           QPixmap, QRegion)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMenu,
                               QMessageBox, QSlider, QSystemTrayIcon, QWidget,
                               QWidgetAction)


# ============================================================================
# 1. CONFIG —— 所有可调参数集中在这里（缩放、周期、阈值……），改这里即可
# ============================================================================
class CONFIG:
    """全局常量区：修改表现只需改这一块。"""

    VERSION = "1.2"
    APP_NAME = "影刃 Q 版"
    SETTINGS_ORG = "ShadowBladePet"
    SETTINGS_APP = "DesktopPet"

    # ---- 尺寸与缩放 ----
    # 素材为 1536px，这里按 512 的「设计尺寸」等比缩放。
    # 角色可见高度 ≈ 画布 * 0.844，所以：22% ≈ 95px 高、28% ≈ 121px、35% ≈ 151px。
    # 需求：最大不超过「原 0.7 倍（约 300px 高）」的 50%，即角色最高约 150px。
    BASE_SIZE = 512                 # 素材的设计尺寸
    ZOOM_DEFAULT = 0.28             # 默认缩放：512 * 0.28 ≈ 143px 画布（角色约 121px 高）
    ZOOM_MIN = 0.22                 # 最小：约 95px 高
    ZOOM_MAX = 0.35                 # 最大：约 151px 高（= 原来 300px 的一半）
    ZOOM_STEP = 0.01                # 滚轮每格 1%
    ZOOM_SLIDER_W = 200             # 菜单里缩放滑杆控件的宽（含百分比标签）
    ZOOM_SLIDER_H = 36              # 高
    TOP_HEADROOM = 0.03             # 窗口顶部预留空间（给呼吸/回弹向上膨胀，避免被裁掉）

    # ---- 帧率 ----
    FPS = 60                        # 拖拽 / 走路时 60 帧
    IDLE_FPS = 30                   # 站着不动时降到 30 帧省 CPU
    MAX_DT = 0.1                    # 单帧最大时间步，防止卡顿后动画跳变
    FPS_LOG_SECONDS = 5.0           # 每隔多久往 pet.log 写一行实测帧率

    # ---- 呼吸 ----
    BREATH_PERIOD_IDLE = 3.2        # 站立呼吸周期（秒）
    BREATH_AMP_IDLE = 0.02          # 纵向缩放 1.00 -> 1.02
    IDLE_LIFT_MAX = 1.0             # 呼吸时整体上移 0~1px
    BREATH_PERIOD_SLEEP = 4.5       # 睡着时呼吸周期放慢
    BREATH_AMP_SLEEP = 0.015        # 幅度 1.00 -> 1.015（相对 0.98 基准）
    SLEEP_SCALE = 0.98              # 睡着时整体缩到 0.98

    # ---- 眨眼 ----
    BLINK_MIN = 3.0                 # 随机间隔下限（秒）
    BLINK_MAX = 6.0                 # 随机间隔上限（秒）
    BLINK_DURATION = 0.15           # 闭眼停留时间（秒）

    # ---- 闲置入睡 ----
    SLEEP_TIMEOUT = 300.0           # 无交互 5 分钟进入 SLEEP
    SLEEP_CHECK_MS = 2000           # 闲置检测节拍

    # ---- 原地踏步 / 奔跑（键盘） ----
    RUN_FRAME_WALK = 0.15           # 走：每帧停留（秒）
    RUN_FRAME_RUN = 0.09            # 跑：每帧停留（秒）
    RUN_BOUNCE = 3.0                # 走：上下颠簸 ±3px
    RUN_BOUNCE_FAST = 4.0           # 跑：±4px
    RUN_LEAN = 4.0                  # 走：前倾 4°
    RUN_LEAN_FAST = 6.0             # 跑：6°
    RUN_SQUASH = 0.97               # 落地帧纵向压扁
    RUN_STRETCH = 1.02              # 腾空帧纵向拉伸
    RUN_BLEND_SECONDS = 0.15        # 起步 / 收势的缓动时长
    KEY_POLL_FRAMES = 2             # 每 2 帧（约 33ms）轮询一次键盘
    KB_VK = {"A": 0x41, "D": 0x44, "W": 0x57, "S": 0x53, "SHIFT": 0x10, "SPACE": 0x20}

    # ---- 顶部悬挂 ----
    HANG_TRIGGER_PX = 24            # 窗口顶边距屏幕可用区顶边小于这个值 → 悬挂
    HANG_ENTER_SECONDS = 0.2        # 贴顶缓动时长
    HANG_SWAY_DEG = 2.0             # 钟摆幅度
    HANG_SWAY_PERIOD = 2.6          # 摆动周期（秒）
    HANG_FALL_SECONDS = 0.35        # 松手自由落体到地面的时长
    HANG_HAND_X = 0.4535            # hang.png 里拳心的归一化 x（会自动按 alpha 实测覆盖）
    HANG_HAND_Y = 0.0299            # 拳心最高点的归一化 y

    # ---- 跳跃 ----
    JUMP_HEIGHT = 70                # 抛物最高点（px）
    JUMP_CROUCH = 0.12              # 蓄力时长
    JUMP_AIR = 0.50                 # 腾空时长
    JUMP_LAND = 0.12                # 落地缓冲时长
    JUMP_COOLDOWN = 0.15            # 落地后可再跳的间隔
    JUMP_SQUASH = 0.90              # 落地压扁
    JUMP_CROUCH_SCALE = 0.92        # 蓄力压扁
    JUMP_CROUCH_SINK = 4.0          # 蓄力时下沉（绘制层 px）
    JUMP_STRETCH = 1.03             # 腾空拉伸
    JUMP_NEAR_GROUND = 40           # 离地小于这个高度就用小缓冲，不走自由落体

    # ---- 跟随鼠标（IDLE 时朝光标方向轻轻偏头） ----
    FOLLOW_SAMPLE_MS = 50           # 采样间隔（独立定时器，不塞进渲染节拍）
    FOLLOW_RADIUS = 240             # 交互半径（px，以身体中心为圆心）：出圈完全不反应
    FOLLOW_FADE_START = 0.6         # 半径的这个比例以内满幅，往外平滑淡出到 0
    FOLLOW_TILT_SPAN = 120          # 水平偏移多少 px 到达最大倾角
    FOLLOW_SHIFT_SPAN = 170         # 水平偏移多少 px 到达最大水平微移
    FOLLOW_TILT_MAX = 3.0           # 最大倾角（度）
    FOLLOW_SHIFT_MAX = 2.0          # 最大水平微移（px）
    FOLLOW_EASE = 0.15              # 每帧缓动系数
    FOLLOW_IDLE_RESET = 1.0         # 鼠标静止多久后回正（秒）

    # ---- 拖拽 ----
    DRAG_TILT_MAX = 6.0             # 最大倾斜角（度）
    DRAG_TILT_PER_PXPS = 0.0125     # 每 (px/秒) 水平速度对应的倾斜角（480px/s ≈ 6°）
    DRAG_TILT_EASE = 0.5            # 倾斜跟随系数（0.5 = 更快跟上）
    DRAG_STOP_PXPS = 20.0           # 低于该水平速度视为静止（px/秒）

    # ---- 落地 ----
    DROP_DURATION = 0.25            # 落地过渡时长（秒）
    DROP_FALL_RATIO = 0.09          # 下落距离 = 角色宽度 * 该比例
    DROP_SCALE_FROM = 1.02          # 落地回弹起始缩放

    # ---- 点击判定 ----
    CLICK_MOVE_TOLERANCE = 4        # 位移小于 4px 视为单击而非拖拽
    DRAG_ARM_MS = 100               # 按住超过该时长才进入拖拽姿势
    WAKE_GRACE_SECONDS = 1.0        # 刚叫醒后的宽限期，避免双击立刻又睡回去

    # ---- 初始位置（相对屏幕可用区域） ----
    MARGIN_RIGHT = 60               # 距屏幕右边缘
    MARGIN_BOTTOM = 40              # 距任务栏上沿

    # ---- 状态 -> 素材 ----
    # DROP 是「松手落地」的过渡帧，沿用悬空姿势（drag），落地后立刻回 IDLE。
    # run_a / run_b 是原地踏步的两帧（walk_01 / walk_02），交替播放。
    STATE_ASSET = {
        "idle": "idle",
        "blink": "blink",
        "drag": "drag",
        "sleep": "sleep",
        "drop": "drag",
        "run_a": "walk_01",
        "run_b": "walk_02",
        "hang": "hang",
        "jump": "jump_air",
    }

    # ---- 文件 ----
    # 只认 exe / 脚本旁边的 assets/（以及打包进 exe 的那一份），不再回退到源码目录，
    # 避免发布后误读别的文件夹里同名图片。
    ASSET_DIRS = ("assets",)
    ASSET_PATTERNS = {
        "idle":  ("idle*.png", "assassin_base_final*.png", "*base_final*.png", "*睁眼*.png"),
        "blink": ("blink*.png", "01_闭眼*.png", "*闭眼*.png"),
        "drag":  ("drag*.png", "03_悬空*.png", "*悬空*.png"),
        "sleep": ("sleep*.png", "04_趴睡*.png", "*趴睡*.png"),
        "walk_01": ("walk_01*.png", "*迈步1*.png"),
        "walk_02": ("walk_02*.png", "*迈步2*.png"),
        "hang": ("hang*.png", "*悬挂*.png", "*抓*.png"),
        "jump_air": ("jump_air*.png", "*jump*air*.png", "*腾空*.png"),
        "icon":  ("icon*.png", "icon.ico"),
    }
    # 这几张缺失时只关掉对应动作，不阻塞程序启动
    OPTIONAL_ASSETS = ("walk_01", "walk_02", "hang", "jump_air")
    LOG_FILE = "pet.log"
    ERROR_FILE = "error.log"
    SETTINGS_FILE = "settings.ini"
    SINGLE_INSTANCE_KEY = "ShadowBladePet.SingleInstance.v1"


# 状态常量
IDLE, BLINK, DRAG, SLEEP, DROP = "idle", "blink", "drag", "sleep", "drop"
RUN_A, RUN_B = "run_a", "run_b"
RUN_STATES = (RUN_A, RUN_B)
HANG, JUMP = "hang", "jump"


# ============================================================================
# 2. 日志与小工具
# ============================================================================
_LOG_HANDLE = None


def _log_file_path() -> str:
    return os.path.join(BASE_DIR, CONFIG.LOG_FILE)


def log(message: str) -> None:
    """打印到控制台并实时写入 pet.log（pythonw 下没有控制台，日志能救命）。"""
    global _LOG_HANDLE
    stamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{stamp}] {message}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        if _LOG_HANDLE is None:
            # 第二个实例只追加，避免把正在运行的那个实例的日志清空
            _LOG_HANDLE = open(_log_file_path(), "a", encoding="utf-8")
        _LOG_HANDLE.write(line + "\n")
        _LOG_HANDLE.flush()
    except Exception:
        pass


def reset_log() -> None:
    """主实例启动时清空 pet.log，重新记录本次运行。"""
    global _LOG_HANDLE
    flush_log()
    try:
        _LOG_HANDLE = open(_log_file_path(), "w", encoding="utf-8")
    except Exception:
        _LOG_HANDLE = None


def flush_log() -> None:
    """关闭日志文件（退出时调用）。"""
    global _LOG_HANDLE
    try:
        if _LOG_HANDLE is not None:
            _LOG_HANDLE.flush()
            _LOG_HANDLE.close()
    except Exception:
        pass
    _LOG_HANDLE = None


def _install_excepthook() -> None:
    """全局异常兜底：写 error.log，绝不让程序静默退出。"""

    def _hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            with open(os.path.join(BASE_DIR, CONFIG.ERROR_FILE), "a", encoding="utf-8") as fh:
                fh.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n{text}")
        except Exception:
            pass
        try:
            sys.stderr.write(text)
            sys.stderr.flush()
        except Exception:
            pass

    sys.excepthook = _hook


# ============================================================================
# 2.5 键盘轮询 —— Win32 GetAsyncKeyState 只读查询，不拦截、不装依赖
# ============================================================================
class KeyPoller:
    """
    用 GetAsyncKeyState 只读轮询按键，用来让角色「原地踏步」。

    这不是全局钩子：不拦截按键、不吞字、不需要管理员权限，
    其他程序的输入完全不受影响。非 Windows 或调用失败时静默禁用。
    """

    def __init__(self):
        self.available = False
        self._user32 = None
        if not sys.platform.startswith("win"):
            log("非 Windows 平台，键盘控制已禁用")
            return
        try:
            import ctypes
            self._user32 = ctypes.windll.user32
            self._user32.GetAsyncKeyState(CONFIG.KB_VK["A"])     # 试调一次
            self.available = True
        except Exception as exc:                                  # pragma: no cover
            log(f"键盘轮询不可用（{exc}），键盘控制已禁用")

    def pressed(self) -> set[str]:
        """返回当前按下的键名集合；任何异常都会永久禁用轮询。"""
        if not self.available:
            return set()
        try:
            return {name for name, vk in CONFIG.KB_VK.items()
                    if self._user32.GetAsyncKeyState(vk) & 0x8000}
        except Exception as exc:                                  # pragma: no cover
            self.available = False
            log(f"键盘轮询失败（{exc}），键盘控制已禁用")
            return set()


# ============================================================================
# 3. load_assets —— 加载四张姿态图 + 托盘图标，缺文件时抛错
# ============================================================================
def _find_asset(patterns: tuple[str, ...]) -> str | None:
    """
    在各候选目录里按通配模式找文件，返回第一个命中的绝对路径。

    先找 exe / 脚本所在目录（用户可自行替换素材），再找打包进 exe 的只读资源。
    """
    import fnmatch

    roots = [BASE_DIR]
    if BUNDLE_DIR != BASE_DIR:
        roots.append(BUNDLE_DIR)

    for root in roots:
        for rel in CONFIG.ASSET_DIRS:
            folder = os.path.normpath(os.path.join(root, rel))
            if not os.path.isdir(folder):
                continue
            try:
                names = sorted(os.listdir(folder))
            except OSError:
                continue
            for pattern in patterns:
                for name in names:
                    if fnmatch.fnmatch(name.lower(), pattern.lower()):
                        return os.path.join(folder, name)
    return None


def _compute_anchor(pixmap: QPixmap) -> tuple[float, float, tuple[float, float, float, float]]:
    """
    用 idle 图的 alpha 计算「脚底中心」锚点与不透明包围盒。

    返回 (anchor_x, anchor_y, bbox) —— 均为 0~1 的归一化比例。
    anchor_x 取最底部 6% 区域的水平中心，保证形变时以双脚为支点。
    """
    width, height = pixmap.width(), pixmap.height()
    mask = pixmap.mask()                        # 1bit：alpha > 0 的像素为 1
    full = QRegion(mask).boundingRect()
    if full.isNull():
        return 0.5, 0.94, (0.0, 0.0, 1.0, 1.0)

    band_top = full.top() + int(full.height() * 0.94)
    band_h = max(1, full.bottom() - band_top + 1)
    band = QBitmap(mask.copy(0, band_top, width, band_h))
    band_rect = QRegion(band).boundingRect()
    anchor_x = ((band_rect.center().x() + 0.5) / width) if not band_rect.isNull() else 0.5
    anchor_y = (full.bottom() + 1) / height

    bbox = (full.left() / width, full.top() / height,
            (full.right() + 1) / width, (full.bottom() + 1) / height)
    return anchor_x, anchor_y, bbox


def _steps(low: float, high: float, step: float) -> tuple[float, ...]:
    """把 [low, high] 按步长切成采样点（含两端）。"""
    values = []
    v = low
    while v <= high + 1e-9:
        values.append(round(v, 3))
        v += step
    if not values or values[-1] < high - 1e-9:
        values.append(round(high, 3))
    return tuple(values)


def _compute_hand_pivot(pixmap: QPixmap) -> tuple[float, float]:
    """
    用 hang.png 最顶部 3% 的 alpha 算「拳心」——悬挂钟摆的支点。

    不能直接用窗口顶部中心：这只手在画布 x≈0.45 处，绕中心转手会沿屏幕边横移。
    返回 (x, y)，均为 0~1 的归一化比例；y 取角色最高点（手顶）。
    """
    width, height = pixmap.width(), pixmap.height()
    mask = pixmap.mask()
    full = QRegion(mask).boundingRect()
    if full.isNull():
        return CONFIG.HANG_HAND_X, CONFIG.HANG_HAND_Y

    band_h = max(2, int(height * 0.03))
    band = QBitmap(mask.copy(0, full.top(), width, band_h))
    band_rect = QRegion(band).boundingRect()
    hand_x = ((band_rect.center().x() + 0.5) / width) if not band_rect.isNull() else CONFIG.HANG_HAND_X
    return hand_x, (full.top() + 1) / height


def load_assets() -> tuple[dict[str, QPixmap], tuple[float, float],
                           tuple[float, float, float, float], str]:
    """
    加载全部素材；必需素材缺失抛 FileNotFoundError（不用占位图硬跑）。

    walk_01 / walk_02 是可选的：缺了只关掉键盘走路，不影响启动。
    """
    assets: dict[str, QPixmap] = {}
    missing: list[str] = []
    optional_missing: list[str] = []
    icon_path = ""

    for key, patterns in CONFIG.ASSET_PATTERNS.items():
        path = _find_asset(patterns)
        if not path:
            if key in CONFIG.OPTIONAL_ASSETS:
                optional_missing.append(key)
            else:
                missing.append(f"{key}（{' / '.join(patterns)}）")
            continue
        pixmap = QPixmap(path)
        if pixmap.isNull():
            raise FileNotFoundError(f"素材无法解码：{path}")
        assets[key] = pixmap
        if key == "icon":
            icon_path = path
        log(f"已加载 {key:<7} <- {path}  ({pixmap.width()}x{pixmap.height()})")

    if missing:
        raise FileNotFoundError(
            "缺少素材文件，请把下列图片放到 assets/ 目录后重试：\n\n  "
            + "\n  ".join(missing)
        )

    if optional_missing:
        log(f"可选素材缺失：{', '.join(optional_missing)} —— 键盘走路功能将关闭")

    anchor_x, anchor_y, bbox = _compute_anchor(assets["idle"])
    log(f"锚点（脚底中心）= ({anchor_x:.4f}, {anchor_y:.4f})，包围盒 = {bbox}")
    return assets, (anchor_x, anchor_y), bbox, icon_path


# ============================================================================
# 4. PetWindow —— 窗口、绘制、动画、拖拽、菜单
# ============================================================================
class PetWindow(QWidget):
    """角色挂件主窗口：负责状态机、动画、鼠标交互和右键菜单。"""

    def __init__(self, assets: dict[str, QPixmap], anchor: tuple[float, float],
                 bbox: tuple[float, float, float, float]):
        super().__init__(None)

        self._assets = assets
        self._anchor_norm = anchor
        self._bbox = bbox
        self._settings = self._open_settings()

        # ---- 读取上次的设置（先读，窗口标志要依赖「是否置顶」） ----
        self._zoom = float(self._settings.value("zoom", CONFIG.ZOOM_DEFAULT))
        self._on_top = bool(self._settings.value("on_top", True, type=bool))
        if not (CONFIG.ZOOM_MIN <= self._zoom <= CONFIG.ZOOM_MAX):
            self._zoom = CONFIG.ZOOM_DEFAULT

        # ---- 窗口属性：无边框 / 透明 / 置顶 / 不进任务栏 / 不抢焦点 ----
        flags = (Qt.WindowType.FramelessWindowHint
                 | Qt.WindowType.Tool                       # Tool：不进任务栏、不占 Alt+Tab
                 | Qt.WindowType.NoDropShadowWindowHint
                 | Qt.WindowType.WindowDoesNotAcceptFocus)
        if self._on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)

        # ---- 运行状态 ----
        self.state = IDLE
        self._sy = 1.0                  # 当前纵向缩放（呼吸 / 踏步挤压）
        self._lift = 0.0                # 当前整体上移像素（呼吸 / 颠簸）
        self._bounce = 0.0              # 踏步时的上下颠簸（正数 = 向下）
        self._tilt = 0.0                # 当前倾斜角（度）
        self._facing = 1                # 朝向：1 = 朝右，-1 = 朝左（镜像绘制）
        self._phase = 0.0               # 呼吸相位（秒）
        self._dropped_t = 0.0
        self._drop_from = QPointF()
        self._drop_to = QPointF()
        self._drop_tilt_from = 0.0
        self._follow_tilt = 0.0         # 跟随鼠标的当前倾角（缓动值）
        self._follow_shift = 0.0        # 跟随鼠标的当前水平微移（px）
        self._follow_target_tilt = 0.0
        self._follow_target_shift = 0.0
        self._mouse_last_pos = QCursor.pos()
        self._mouse_last_move_ts = 0.0
        self._last_tick = time.monotonic()
        self._last_interact = time.monotonic()
        self._pix_cache: dict[tuple[str, int, float], QPixmap] = {}
        self._mask_cache: dict[tuple, QRegion] = {}
        self._mask_key_applied: tuple | None = None
        self._mask_frozen = False       # 拖滑杆 / 拖拽时冻结遮罩重建
        self._tray = None
        self._tray_hint_shown = False

        # ---- 键盘踏步 / 跳跃 ----
        self._kb_poller = KeyPoller()
        self._kb_available = self._kb_poller.available and all(
            key in self._assets for key in CONFIG.OPTIONAL_ASSETS)
        self._kb_enabled = bool(self._settings.value("keyboard", True, type=bool)) and self._kb_available
        if self._kb_poller.available:
            missing = [k for k in CONFIG.OPTIONAL_ASSETS if k not in self._assets]
            if missing:
                log(f"缺少可选素材：{', '.join(missing)} —— 对应动作已自动关闭")
        self._keys: set[str] = set()
        self._prev_keys: set[str] = set()
        self._run_t = 0.0
        self._run_blend = 0.0
        self._run_frame = RUN_A
        self._key_frame = 0

        # ---- 顶部悬挂 / 跳跃 ----
        self._hang_possible = "hang" in self._assets
        self._jump_possible = "jump_air" in self._assets
        self._hand_norm = (_compute_hand_pivot(self._assets["hang"])
                           if self._hang_possible
                           else (CONFIG.HANG_HAND_X, CONFIG.HANG_HAND_Y))
        self._hand_px = QPointF(0.0, 0.0)
        self._hang_t = 0.0               # 进入 / 摆动计时
        self._hang_enter = False         # 正在贴顶缓动
        self._hang_from = QPointF()
        self._hang_to = QPointF()
        self._hang_amp = 0.0             # 摆动振幅（0 → HANG_SWAY_DEG 渐入）
        self._jump_phase = ""            # crouch / air / land
        self._jump_t = 0.0
        self._jump_y0 = 0.0              # 起跳时窗口 y
        self._jump_ready_at = 0.0        # 冷却结束时间
        self._jump_interrupted = False   # 半空被鼠标接住，松手要落回地面
        self._drop_curve = "settle"      # settle = 小缓冲；gravity = 自由落体
        self._drop_seconds = CONFIG.DROP_DURATION

        # ---- 性能统计 ----
        self._fps_frames = 0
        self._fps_since = time.monotonic()
        self._paint_sig: tuple | None = None

        # ---- 拖拽 / 点击 ----
        self._press_global = QPoint()
        self._grab_offset = QPointF()   # 鼠标 - 窗口左上角
        self._pressed = False
        self._moved = False
        self._drag_accum_x = 0.0        # 本帧窗口水平位移累计（算倾斜速度用）
        self._last_wake_time = -999.0

        # ---- 几何 ----
        self._canvas_w = 0
        self._canvas_h = 0
        self._pad_top = 0
        self._anchor_px = QPointF(0.0, 0.0)

        self._relayout()
        self._restore_position()

        # ---- 定时器 ----
        self._tick_timer = QTimer(self)
        # 必须用 PreciseTimer：Windows 上 CoarseTimer 会被拉到 15.6ms 的整数倍，
        # 33ms 实际会变成 46.8ms（约 21 帧），走路时手感发肉。
        self._tick_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._tick_timer.setInterval(max(4, int(round(1000.0 / CONFIG.FPS))))
        self._tick_timer.timeout.connect(self._on_tick)

        self._blink_timer = QTimer(self)
        self._blink_timer.setSingleShot(True)
        self._blink_timer.timeout.connect(self._start_blink)

        self._drag_arm_timer = QTimer(self)
        self._drag_arm_timer.setSingleShot(True)
        self._drag_arm_timer.timeout.connect(self._arm_drag)

        self._sleep_timer = QTimer(self)
        self._sleep_timer.setInterval(CONFIG.SLEEP_CHECK_MS)
        self._sleep_timer.timeout.connect(self._check_idle)

        # 跟随鼠标：独立 50ms 采样，不塞进渲染节拍
        self._follow_timer = QTimer(self)
        self._follow_timer.setInterval(CONFIG.FOLLOW_SAMPLE_MS)
        self._follow_timer.timeout.connect(self._sample_mouse)

        self._set_state(IDLE, force_mask=True)
        self._schedule_blink()
        self._sync_tick_rate()
        self._tick_timer.start()
        self._sleep_timer.start()
        self._follow_timer.start()
        self._last_tick = time.monotonic()

        log(f"窗口尺寸 = {self.width()}x{self.height()}（画布 {self._canvas_w}，顶部留白 {self._pad_top}），"
            f"缩放 = {self._zoom:.2f}，键盘控制 = {'开' if self._kb_enabled else '关'}")

    # ---------------------------------------------------------------- 设置
    def _open_settings(self) -> QSettings:
        """QSettings 用 INI 存在脚本目录，便于随手查看/备份。"""
        path = os.path.join(BASE_DIR, CONFIG.SETTINGS_FILE)
        try:
            if not os.access(BASE_DIR, os.W_OK):
                raise OSError
        except OSError:
            path = os.path.join(os.path.expanduser("~"), ".shadowblade_pet.ini")
        return QSettings(path, QSettings.Format.IniFormat)

    def save_settings(self) -> None:
        """保存位置 / 缩放 / 置顶 / 键盘控制 / 可见性。

        悬挂时脚底在屏幕外，存的是「同一水平位置的地面点」，
        下次启动会正常站在地上，而不是挂回屏幕顶。
        """
        if self.state == HANG:
            foot = self._ground_foot()
        else:
            foot = self.foot_world()
        s = self._settings
        s.setValue("pos_x", round(foot.x(), 1))
        s.setValue("pos_y", round(foot.y(), 1))
        s.setValue("zoom", round(self._zoom, 4))
        s.setValue("on_top", self._on_top)
        s.setValue("keyboard", self._kb_enabled)
        s.setValue("visible", self.isVisible())
        s.sync()

    # ---------------------------------------------------------------- 几何
    def _relayout(self) -> None:
        """按当前缩放重算窗口尺寸、画布矩形、脚底锚点与悬挂支点（像素坐标）。"""
        self._zoom = max(CONFIG.ZOOM_MIN, min(CONFIG.ZOOM_MAX, self._zoom))
        canvas = max(64, int(round(CONFIG.BASE_SIZE * self._zoom)))
        pad = max(1, int(math.ceil(canvas * CONFIG.TOP_HEADROOM)))
        self._canvas_w = canvas
        self._canvas_h = canvas
        self._pad_top = pad
        self._anchor_px = QPointF(self._anchor_norm[0] * canvas, pad + self._anchor_norm[1] * canvas)
        self._hand_px = QPointF(self._hand_norm[0] * canvas, pad + self._hand_norm[1] * canvas)
        self.setFixedSize(canvas, canvas + pad)
        self._pix_cache.clear()

    def _pivot_px(self) -> QPointF:
        """
        形变支点：普通状态是脚底（站着呼吸/踏步都不会飘），
        悬挂时是拳心（吊着晃，手才不会沿屏幕边横移）。
        """
        return self._hand_px if self.state == HANG else self._anchor_px

    def hand_world(self) -> QPointF:
        """拳心（悬挂支点）的屏幕坐标。"""
        return QPointF(self.x() + self._hand_px.x(), self.y() + self._hand_px.y())

    def foot_world(self) -> QPointF:
        """脚底锚点的屏幕坐标。"""
        return QPointF(self.x() + self._anchor_px.x(), self.y() + self._anchor_px.y())

    def _move_foot_to(self, point: QPointF) -> None:
        """把脚底锚点移动到指定屏幕坐标。"""
        self.move(int(round(point.x() - self._anchor_px.x())),
                  int(round(point.y() - self._anchor_px.y())))

    def _default_foot(self) -> QPointF:
        """默认位置：主屏右下角，距右边缘 60px、距任务栏上沿 40px（按角色可见轮廓算）。"""
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        right = avail.right() + 1 - CONFIG.MARGIN_RIGHT
        bottom = avail.bottom() + 1 - CONFIG.MARGIN_BOTTOM
        # 让「可见轮廓」右边缘对齐，而不是画布右边缘
        self.move(int(round(right - self._bbox[2] * self._canvas_w)),
                  int(round(bottom - self._anchor_px.y())))
        return self.foot_world()

    def _restore_position(self) -> None:
        """还原上次位置；屏幕已断开则回落到主屏右下角。"""
        sx = self._settings.value("pos_x", None)
        sy = self._settings.value("pos_y", None)
        if sx is None or sy is None:
            self._default_foot()
            log("首次启动：使用主屏右下角默认位置")
            return
        try:
            foot = QPointF(float(sx), float(sy))
        except (TypeError, ValueError):
            self._default_foot()
            return
        point = QPoint(int(round(foot.x())), int(round(foot.y())))
        screen = QGuiApplication.screenAt(point)
        if screen is None or not screen.availableGeometry().adjusted(-40, -40, 40, 40).contains(point):
            self._default_foot()
            log("上次的位置不在任何已连接的屏幕上，已回落到主屏右下角")
            return
        self._move_foot_to(foot)
        log(f"还原位置：脚底锚点 = ({foot.x():.0f}, {foot.y():.0f})")

    # ---------------------------------------------------------------- 素材
    def _pixmap_for_asset(self, asset_key: str) -> QPixmap:
        """取当前缩放 / DPI 下的缓存位图（按素材名缓存）。"""
        dpr = max(1.0, self.devicePixelRatioF())
        key = (asset_key, self._canvas_w, round(dpr, 2))
        cached = self._pix_cache.get(key)
        if cached is not None:
            return cached

        source = self._assets[asset_key]
        physical = QSize(max(1, int(round(self._canvas_w * dpr))),
                         max(1, int(round(self._canvas_h * dpr))))
        scaled = source.scaled(physical, Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        scaled.setDevicePixelRatio(dpr)
        self._pix_cache[key] = scaled
        return scaled

    def _current_asset_key(self) -> str:
        """
        当前该画哪张图。

        跳跃三阶段用的素材不一样：蓄力 / 落地用 idle（压扁），只有腾空才用 jump_air，
        否则蹲下时还是“腿收起来”的姿势，看着很怪。
        """
        if self.state == JUMP and self._jump_phase != "air":
            return "idle"
        key = CONFIG.STATE_ASSET.get(self.state, "idle")
        return key if key in self._assets else "idle"

    def _current_pixmap(self) -> QPixmap | None:
        return self._pixmap_for_asset(self._current_asset_key())

    # ---------------------------------------------------------------- 遮罩
    def _mask_family(self) -> str:
        """
        遮罩按「形状族 + 朝向」缓存。

        朝向必须算进缓存键：绘制时所有状态都会按 _facing 做水平镜像（刀会换到另一侧），
        如果遮罩只按「朝右」建，镜像后的刀/身体就落在遮罩外被整块切掉。
        """
        if self.state in RUN_STATES:
            fam = "run"
        elif self.state in (DRAG, DROP):
            fam = "drag"
        elif self.state == SLEEP:
            fam = "sleep"
        elif self.state == HANG:
            fam = "hang"
        elif self.state == JUMP:
            fam = "jump"
        else:
            fam = "idle"
        return fam + ("_l" if self._facing < 0 else "")

    def _mask_spec(self):
        """
        返回该族的形状包络：(纵向缩放采样, 颠簸列表, 倾斜采样, 素材列表, 是否镜像)。

        采样必须「密」：只取两端点的话，细长物体（刀鞘、手指）在中间角度会落在两次采样
        之间，被整根切掉——「按 A 之后刀消失」就是这么来的。所有采样会画进同一张遮罩画布，
        最后只取一次 QRegion，所以加密的代价很低。
        """
        fam = self._mask_family()
        base = fam[:-2] if fam.endswith("_l") else fam
        mirror = self._facing < 0
        if base == "run":
            return ((CONFIG.RUN_SQUASH, CONFIG.RUN_STRETCH),
                    (-CONFIG.RUN_BOUNCE_FAST, CONFIG.RUN_BOUNCE_FAST),
                    _steps(-CONFIG.RUN_LEAN_FAST, CONFIG.RUN_LEAN_FAST, 2.0),
                    ("walk_01", "walk_02"), mirror)
        if base == "drag":
            return ((1.0, CONFIG.DROP_SCALE_FROM), (0.0,),
                    _steps(-CONFIG.DRAG_TILT_MAX, CONFIG.DRAG_TILT_MAX, 2.0),
                    ("drag",), mirror)
        if base == "sleep":
            return ((CONFIG.SLEEP_SCALE,
                     CONFIG.SLEEP_SCALE * (1.0 + CONFIG.BREATH_AMP_SLEEP)), (0.0,),
                    (0.0,), ("sleep",), mirror)
        if base == "hang":
            return ((1.0,), (0.0,),
                    _steps(-CONFIG.HANG_SWAY_DEG, CONFIG.HANG_SWAY_DEG, 0.5),
                    ("hang",), mirror)
        if base == "jump":
            # 蓄力/落地用 idle（压到 0.90 且下沉 4px），腾空用 jump_air（拉到 1.03）
            return (_steps(CONFIG.JUMP_SQUASH, CONFIG.JUMP_STRETCH, 0.02),
                    (0.0, CONFIG.JUMP_CROUCH_SINK), (0.0,),
                    ("idle", "jump_air"), mirror)
        return ((1.0, 1.0 + CONFIG.BREATH_AMP_IDLE), (0.0,),
                _steps(-CONFIG.FOLLOW_TILT_MAX, CONFIG.FOLLOW_TILT_MAX, 0.5),
                ("idle",), mirror)

    def _mask_pivot(self) -> QPointF:
        """遮罩包络用的支点，必须和绘制时的支点一致（悬挂是拳心）。"""
        return self._hand_px if self.state == HANG else self._anchor_px

    def _build_mask_region(self, spec) -> QRegion:
        """
        把该族所有形变采样画进同一张遮罩画布，取一次 alpha 蒙版，再外扩 1px。

        画布不参与变换：translate(支点) → 变换 → translate(-支点)，
        所以悬挂绕拳心转、其它状态绕脚底转，画布位置都固定。
        外扩 1px 是为了盖住抗锯齿的半透明边缘（QPixmap.mask() 的阈值是 alpha>127）。
        """
        sys_values, bounces, tilts, asset_keys, mirror = spec
        pivot = self._mask_pivot()
        canvas_origin = QPointF(0.0, float(self._pad_top))

        envelope = QPixmap(self.size())
        envelope.fill(Qt.GlobalColor.transparent)
        painter = QPainter(envelope)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        for asset_key in asset_keys:
            if asset_key not in self._assets:
                continue
            pixmap = self._pixmap_for_asset(asset_key)
            for tilt in tilts:
                for bounce in bounces:
                    for sy in sys_values:
                        painter.save()
                        painter.translate(pivot.x(), pivot.y() + bounce)
                        if abs(tilt) > 0.01:
                            painter.rotate(tilt)
                        if mirror:
                            painter.scale(-1.0, 1.0)
                        if abs(sy - 1.0) > 1e-4:
                            painter.scale(1.0, sy)
                        painter.translate(-pivot.x(), -pivot.y())
                        painter.drawPixmap(canvas_origin, pixmap)
                        painter.restore()
        painter.end()

        region = QRegion(envelope.mask())
        grown = region
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            grown = grown.united(region.translated(dx, dy))
        # IDLE 还要覆盖跟随鼠标的 ±FOLLOW_SHIFT_MAX 水平微移
        if self._mask_family().startswith("idle"):
            pad = int(math.ceil(CONFIG.FOLLOW_SHIFT_MAX))
            for dx in range(1, pad + 1):
                grown = grown.united(region.translated(dx, 0)).united(region.translated(-dx, 0))
        return grown

    def _update_mask(self, force: bool = False) -> None:
        """
        应用窗口遮罩：只有不透明像素可点击，透明区域完全穿透。

        结果按 (形状族, 缩放, DPI) 缓存，命中就直接复用——
        所以踏步换帧、呼吸、拖拽倾斜全程都不会重建遮罩。
        """
        if self._mask_frozen:
            return
        dpr = max(1.0, self.devicePixelRatioF())
        key = (self._mask_family(), round(self._zoom, 3), round(dpr, 2))
        if not force and key == self._mask_key_applied:
            return

        region = self._mask_cache.get(key)
        if region is None:
            region = self._build_mask_region(self._mask_spec())
            self._mask_cache[key] = region
        self.setMask(region)
        self._mask_key_applied = key

    def event(self, event) -> bool:
        """处理 DPI 变化（例如把挂件拖到另一块缩放不同的屏幕）。"""
        if event.type() == QEvent.Type.DevicePixelRatioChange:
            self._pix_cache.clear()
            self._mask_cache.clear()
            self._mask_key_applied = None
            self._update_mask(force=True)
            self.update()
        return super().event(event)

    # ---------------------------------------------------------------- 状态机
    def _set_state(self, state: str, force_mask: bool = False, quiet: bool = False) -> None:
        """切换状态并换图（每个状态对应各自素材）。"""
        changed = state != self.state
        self.state = state
        if changed:
            # 离开站立/眨眼就把跟随鼠标的形变清掉，回到 IDLE 时再从 0 缓动进来，不会跳
            if state not in (IDLE, BLINK):
                self._follow_tilt = 0.0
                self._follow_shift = 0.0
                self._follow_target_tilt = 0.0
                self._follow_target_shift = 0.0
            # IDLE 与 BLINK 共用同一条呼吸曲线：切换时保留相位与形变，
            # 否则每眨一次眼，角色都会「抽」一下。
            if state == SLEEP:
                self._phase = 0.0
                self._sy, self._lift, self._tilt, self._bounce = CONFIG.SLEEP_SCALE, 0.0, 0.0, 0.0
            elif state == DRAG:
                self._phase = 0.0
                self._sy, self._lift, self._tilt, self._bounce = 1.0, 0.0, 0.0, 0.0
            elif state == DROP:
                self._lift = 0.0
            elif state == HANG:
                # 悬挂不做呼吸缩放（会被看成手在伸缩），只保留摆动
                self._phase = 0.0
                self._sy, self._lift, self._bounce = 1.0, 0.0, 0.0
                self._hang_amp = 0.0
            elif state == JUMP:
                self._phase = 0.0
                self._lift, self._bounce = 0.0, 0.0
        self._update_mask(force=force_mask)
        self._paint_sig = None
        self.update()
        if changed:
            self._sync_tick_rate()
            if not quiet:
                log(f"状态 -> {state}")

    # ---------------------------------------------------------------- 帧率
    def _desired_fps(self) -> int:
        """静止（站立 / 眨眼 / 睡觉 / 悬挂）用 30 帧，其余（拖拽 / 踏步 / 跳跃）用 60 帧。"""
        if self.state in (IDLE, BLINK, SLEEP, HANG) and not self._keys:
            return CONFIG.IDLE_FPS
        return CONFIG.FPS

    def _sync_tick_rate(self) -> None:
        """按当前状态切换定时器频率，静止时省 CPU。"""
        interval = max(4, int(round(1000.0 / self._desired_fps())))
        if self._tick_timer.interval() != interval:
            self._tick_timer.setInterval(interval)
            # 换挡后重新开始统计，日志里的实测帧率才对应「当前这一档」
            self._fps_frames = 0
            self._fps_since = time.monotonic()

    # ---------------------------------------------------------------- 键盘（踏步 / 跳跃）
    def _poll_keys(self) -> None:
        """每 2 帧轮询一次按键；只在需要时才碰 Win32 API。"""
        if not self._kb_enabled:
            if self._keys:
                self._keys = set()
            return
        # 拖拽 / 落地 / 睡觉 / 悬挂：完全收不到键盘指令
        # （悬挂时只有「单击角色」才会松手，空格/WASD 一律不动）
        if self.state in (DRAG, DROP, SLEEP, HANG):
            if self._keys:
                self._keys = set()
            return

        keys = self._kb_poller.pressed()
        pressed = keys - self._keys          # 上升沿：按住不放只触发一次
        self._keys = keys

        # 记录 A / D 的「最后按下」，决定朝向（W / S 保持上一次朝向）
        for name in pressed:
            if name == "A":
                self._facing = -1
            elif name == "D":
                self._facing = 1

        if "SPACE" in pressed:
            self._try_jump()

        if keys & {"A", "D", "W", "S"}:
            self._last_interact = time.monotonic()
            if self.state not in RUN_STATES and self.state != JUMP:
                self._enter_run()

    # ---------------------------------------------------------------- 原地跳跃
    def _try_jump(self) -> None:
        """空格：上升沿触发，落地冷却期内/不该跳的状态一律忽略。"""
        if not self._jump_possible:
            return
        if self.state in (DRAG, DROP, SLEEP, HANG, JUMP):
            return
        if time.monotonic() < self._jump_ready_at:
            return
        self._start_jump()

    def _start_jump(self) -> None:
        """起跳：记下地面 y，先蓄力，再腾空，最后落地缓冲。"""
        self._blink_timer.stop()
        self._jump_phase = "crouch"
        self._jump_t = 0.0
        self._jump_y0 = float(self.y())
        self._sy, self._lift, self._tilt, self._bounce = 1.0, 0.0, 0.0, 0.0
        self._run_t = 0.0
        self._last_interact = time.monotonic()
        self._set_state(JUMP, force_mask=True)

    def _tick_jump(self, dt: float) -> None:
        """三阶段：蓄力 0.12s → 腾空 0.50s（抛物线）→ 落地 0.12s。窗口只做垂直移动。"""
        self._jump_t += dt
        if self._jump_phase == "crouch":
            t = min(1.0, self._jump_t / CONFIG.JUMP_CROUCH)
            self._sy = 1.0 - (1.0 - CONFIG.JUMP_CROUCH_SCALE) * t
            self._bounce = CONFIG.JUMP_CROUCH_SINK * t
            if t >= 1.0:
                self._jump_phase = "air"
                self._jump_t = 0.0
                self._bounce = 0.0
        elif self._jump_phase == "air":
            t = min(1.0, self._jump_t / CONFIG.JUMP_AIR)
            # -4h·t(1-t)：t=0 与 t=1 都是 0，最高点在正中间，落点精确回到起跳位置
            offset = -4.0 * CONFIG.JUMP_HEIGHT * t * (1.0 - t)
            self._move_to(QPointF(float(self.x()), self._jump_y0 + offset))
            self._sy = 1.0 + (CONFIG.JUMP_STRETCH - 1.0) * math.sin(math.pi * t)
            if t >= 1.0:
                self._jump_phase = "land"
                self._jump_t = 0.0
                self._sy = CONFIG.JUMP_SQUASH
                self._move_to(QPointF(float(self.x()), self._jump_y0))
        else:  # land
            t = min(1.0, self._jump_t / CONFIG.JUMP_LAND)
            self._sy = CONFIG.JUMP_SQUASH + (1.0 - CONFIG.JUMP_SQUASH) * t
            if t >= 1.0:
                self._sy = 1.0
                self._jump_ready_at = time.monotonic() + CONFIG.JUMP_COOLDOWN
                if self._kb_enabled and (self._keys & {"A", "D", "W", "S"}):
                    self._enter_run()
                else:
                    self._set_state(IDLE, force_mask=True)
                    self._schedule_blink()

    # ---------------------------------------------------------------- 顶部悬挂
    def _screen_avail(self) -> QRect:
        """当前所在屏幕的可用区域。"""
        center = self.frameGeometry().center()
        screen = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def _ground_top_y(self) -> float:
        """站在地面时的窗口 y（脚底贴 avail.bottom()-2）。"""
        return float(self._screen_avail().bottom() - 2) - self._anchor_px.y()

    def _ground_foot(self) -> QPointF:
        """地面脚底点：悬挂时用来做位置记忆。"""
        return QPointF(self.foot_world().x(), float(self._screen_avail().bottom() - 2))

    def _near_screen_top(self) -> bool:
        """窗口顶边离屏幕可用区顶边小于阈值 → 认为「拖到了顶部」。"""
        avail = self._screen_avail()
        return (self.y() - avail.top()) < CONFIG.HANG_TRIGGER_PX

    def _enter_hang(self) -> None:
        """贴顶悬挂：0.2s 缓动，让拳心正好落在屏幕顶边。"""
        if not self._hang_possible:
            return
        self._blink_timer.stop()
        self._keys = set()
        self._hang_from = QPointF(float(self.x()), float(self.y()))
        target_y = self._screen_avail().top() - self._hand_px.y()
        self._hang_to = QPointF(float(self.x()), target_y)
        self._hang_t = 0.0
        self._hang_enter = True
        self._hang_amp = 0.0
        self._sy, self._lift, self._bounce, self._tilt = 1.0, 0.0, 0.0, 0.0
        self._set_state(HANG, force_mask=True)

    def _tick_hang(self, dt: float) -> None:
        """进入缓动 + 钟摆摆动（支点在拳心，所以是「吊着晃」不是「整块牌子晃」）。"""
        if self._hang_enter:
            self._hang_t += dt
            t = min(1.0, self._hang_t / CONFIG.HANG_ENTER_SECONDS)
            ease = 1.0 - (1.0 - t) ** 2
            pos = self._hang_from + (self._hang_to - self._hang_from) * ease
            self._move_to(pos)
            if t >= 1.0:
                self._hang_enter = False
                self._hang_t = 0.0
                self._move_to(self._hang_to)
            return

        self._hang_t += dt
        # 振幅 0 → 2° 渐入，避免一挂上去就猛地一摆
        self._hang_amp = min(CONFIG.HANG_SWAY_DEG, self._hang_amp + dt * 4.0)
        angle = self._hang_amp * math.sin(
            2.0 * math.pi * self._hang_t / CONFIG.HANG_SWAY_PERIOD)
        self._tilt = angle
        self._sy = 1.0
        self._lift = 0.0
        self._bounce = 0.0

    def _release_hang(self) -> None:
        """松手：从屏幕顶自由落体到地面，落地压扁回弹，然后回 IDLE。"""
        self._drop_curve = "gravity"
        self._drop_seconds = CONFIG.HANG_FALL_SECONDS
        self._drop_from = QPointF(float(self.x()), float(self.y()))
        self._drop_to = QPointF(float(self.x()), self._ground_top_y())
        self._drop_tilt_from = self._tilt
        self._dropped_t = 0.0
        self._tilt = 0.0
        self._hang_enter = False
        self._hang_amp = 0.0
        self._last_interact = time.monotonic()
        self._set_state(DROP)

    def _enter_run(self) -> None:
        """进入踏步：换走路帧、停掉眨眼、频率提到 60 帧。"""
        self._blink_timer.stop()
        self._run_t = 0.0
        self._run_blend = 0.0
        self._run_frame = RUN_A
        self._set_state(RUN_A)
        self._sync_tick_rate()

    def _tick_run(self, dt: float) -> None:
        """原地踏步：两帧交替 + 颠簸 + 挤压 + 前倾，全部只在绘制层发生。"""
        keys = self._keys
        moving = bool(keys & {"A", "D", "W", "S"})
        fast = "SHIFT" in keys

        if moving:
            self._run_blend = min(1.0, self._run_blend + dt / CONFIG.RUN_BLEND_SECONDS)
        else:
            self._run_blend = max(0.0, self._run_blend - dt / CONFIG.RUN_BLEND_SECONDS)
            if self._run_blend <= 0.0:
                # 收势完毕：形变全部归零，平滑回到 idle
                self._sy, self._lift, self._tilt, self._bounce = 1.0, 0.0, 0.0, 0.0
                self._run_t = 0.0
                self._set_state(IDLE, force_mask=True)
                self._schedule_blink()
                return

        frame_seconds = CONFIG.RUN_FRAME_RUN if fast else CONFIG.RUN_FRAME_WALK
        self._run_t += dt
        while self._run_t >= frame_seconds:
            self._run_t -= frame_seconds
            self._run_frame = RUN_B if self._run_frame == RUN_A else RUN_A
            if self._run_frame != self.state:
                self._set_state(self._run_frame, quiet=True)

        # 相位 0 = 刚落地，相位 1 = 腾空
        p = self._run_t / frame_seconds if frame_seconds > 0 else 0.0
        wave = math.cos(math.pi * p)                       # 1 -> -1
        bounce = (CONFIG.RUN_BOUNCE_FAST if fast else CONFIG.RUN_BOUNCE) * wave
        mid = (CONFIG.RUN_SQUASH + CONFIG.RUN_STRETCH) * 0.5
        spread = (CONFIG.RUN_STRETCH - CONFIG.RUN_SQUASH) * 0.5
        sy = mid - spread * wave                           # 落地 0.97 / 腾空 1.02
        lean = CONFIG.RUN_LEAN_FAST if fast else CONFIG.RUN_LEAN

        blend = self._run_blend
        self._bounce = bounce * blend
        self._sy = 1.0 + (sy - 1.0) * blend
        self._lift = 0.0
        self._tilt = (lean if self._facing > 0 else -lean) * blend

    def _start_blink(self) -> None:
        """播放一次眨眼（仅 IDLE 有效，踏步时不眨眼）。"""
        if self.state != IDLE:
            return
        self._set_state(BLINK)
        QTimer.singleShot(int(CONFIG.BLINK_DURATION * 1000), self._end_blink)

    def _end_blink(self) -> None:
        if self.state == BLINK:
            self._set_state(IDLE)
        self._schedule_blink()

    def _schedule_blink(self) -> None:
        """随机 3~6 秒后眨一次眼；睡眠 / 拖拽 / 踏步中不排期。"""
        self._blink_timer.stop()
        if self.state in (IDLE, BLINK):
            delay = int(random.uniform(CONFIG.BLINK_MIN, CONFIG.BLINK_MAX) * 1000)
            self._blink_timer.start(delay)

    def _check_idle(self) -> None:
        """闲置超时进入睡眠（踏步期间不算闲置）。"""
        if self.state in RUN_STATES:
            return
        if self.state in (IDLE, BLINK) and (time.monotonic() - self._last_interact) >= CONFIG.SLEEP_TIMEOUT:
            self.go_sleep()

    def go_sleep(self) -> None:
        # 悬挂 / 跳跃中不允许入睡：否则会「躺着挂在半空」或者躺在跳起来的半空
        if self.state in (SLEEP, HANG, JUMP):
            return
        self._blink_timer.stop()
        self._keys = set()
        self._set_state(SLEEP)
        self.save_settings()

    def wake_up(self, blink: bool = False) -> None:
        """醒来（点击/拖动/菜单叫醒）。"""
        if self.state == SLEEP:
            self._set_state(IDLE)
        self._last_interact = time.monotonic()
        if blink and self.state == IDLE:
            self._start_blink()

    def toggle_sleep(self) -> None:
        """双击 / 菜单：睡着 <-> 醒来。"""
        self._last_interact = time.monotonic()
        if self.state == SLEEP:
            self._set_state(IDLE)
            self._schedule_blink()
        else:
            self.go_sleep()

    # ---------------------------------------------------------------- 跟随鼠标
    def _follow_center(self) -> QPointF:
        """交互圈的圆心：角色身体中心（脚底往上半个可见高度），不是脚底。"""
        body_h = (self._bbox[3] - self._bbox[1]) * self._canvas_h
        foot = self.foot_world()
        return QPointF(foot.x(), foot.y() - body_h * 0.5)

    def _sample_mouse(self) -> None:
        """
        每 50ms 采一次光标，算出「朝光标方向」的目标倾角与水平微移。

        只在 IDLE / BLINK 生效：奔跑有固定前倾、拖拽有速度倾斜、睡觉/悬挂/跳跃都不该有反应。
        鼠标停住超过 FOLLOW_IDLE_RESET 秒，目标归零，角色慢慢回正。

        交互范围：以身体中心为圆心、FOLLOW_RADIUS 为半径的圆。
        圈外一律不反应（光标离得再远也不会把角色拽歪），
        圈内靠外的那部分平滑淡出，避免光标跨过边界时角色「啪」地弹正。
        """
        pos = QCursor.pos()
        now = time.monotonic()
        if pos != self._mouse_last_pos:
            self._mouse_last_pos = pos
            self._mouse_last_move_ts = now

        if self.state not in (IDLE, BLINK) or now - self._mouse_last_move_ts > CONFIG.FOLLOW_IDLE_RESET:
            self._follow_target_tilt = 0.0
            self._follow_target_shift = 0.0
            return

        center = self._follow_center()
        dx = pos.x() - center.x()
        dy = pos.y() - center.y()
        dist = math.hypot(dx, dy)

        radius = max(1.0, float(CONFIG.FOLLOW_RADIUS))
        if dist >= radius:
            self._follow_target_tilt = 0.0
            self._follow_target_shift = 0.0
            return

        inner = radius * max(0.0, min(0.95, CONFIG.FOLLOW_FADE_START))
        if dist <= inner:
            fade = 1.0
        else:
            u = (dist - inner) / max(1e-6, radius - inner)
            fade = 1.0 - u * u * (3.0 - 2.0 * u)      # smoothstep 淡出

        self._follow_target_tilt = (
            max(-1.0, min(1.0, dx / CONFIG.FOLLOW_TILT_SPAN))
            * CONFIG.FOLLOW_TILT_MAX * fade)
        self._follow_target_shift = (
            max(-1.0, min(1.0, dx / CONFIG.FOLLOW_SHIFT_SPAN))
            * CONFIG.FOLLOW_SHIFT_MAX * fade)

    def _tick_follow(self) -> None:
        """每帧把当前倾角 / 微移缓动逼近目标（IDLE 固定 30 帧，所以 0.15 的手感是稳定的）。"""
        self._follow_tilt += (self._follow_target_tilt - self._follow_tilt) * CONFIG.FOLLOW_EASE
        self._follow_shift += (self._follow_target_shift - self._follow_shift) * CONFIG.FOLLOW_EASE
        self._tilt = self._follow_tilt

    # ---------------------------------------------------------------- 缩放
    def set_zoom(self, zoom: float, light: bool = False) -> None:
        """
        以脚底为锚点缩放：窗口尺寸变、脚不动。

        light=True 用于滑杆拖动过程中：只重排 + 重绘，不重建遮罩、不写盘，
        松手后再统一 _update_mask(force=True) 并保存。
        """
        zoom = max(CONFIG.ZOOM_MIN, min(CONFIG.ZOOM_MAX, zoom))
        if abs(zoom - self._zoom) < 1e-4:
            return
        if self.state == HANG:
            # 悬挂时手脚都没有意义：保持「手贴屏幕顶」和水平位置不变
            hand_x = self.hand_world().x()
            top = float(self._screen_avail().top())
            self._zoom = zoom
            self._relayout()
            self._move_to(QPointF(hand_x - self._hand_px.x(), top - self._hand_px.y()))
        else:
            foot = self.foot_world()
            self._zoom = zoom
            self._relayout()
            self._move_foot_to(foot)
        if not light:
            self._update_mask(force=True)
            self.save_settings()
        self.update()

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, event) -> None:
        pixmap = self._current_pixmap()
        if pixmap is None:
            return
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing
                               | QPainter.RenderHint.SmoothPixmapTransform, True)
        # 支点：普通状态是脚底（往上长），悬挂是拳心（吊着晃）
        pivot = self._pivot_px()
        px, py = pivot.x(), pivot.y()
        painter.translate(px, py - self._lift + self._bounce)
        if abs(self._tilt) > 0.01:
            painter.rotate(self._tilt)                  # 前倾 / 拖拽倾斜 / 钟摆
        if self._facing < 0:
            painter.scale(-1.0, 1.0)                    # 朝左：水平镜像
        if abs(self._sy - 1.0) > 1e-4:
            painter.scale(1.0, self._sy)                # 呼吸 / 踏步 / 跳跃挤压
        painter.translate(-px, -py)
        # 跟随鼠标的水平微移只作用在绘制位置，绝不改窗口坐标（否则会抖）
        painter.drawPixmap(QPointF(self._follow_shift, float(self._pad_top)), pixmap)
        painter.end()

    # ---------------------------------------------------------------- 动画节拍
    def _on_tick(self) -> None:
        now = time.monotonic()
        dt = min(CONFIG.MAX_DT, now - self._last_tick)
        self._last_tick = now
        if dt <= 0:
            return

        # 键盘：每 2 帧（约 33ms）才碰一次 API
        self._key_frame = (self._key_frame + 1) % max(1, CONFIG.KEY_POLL_FRAMES)
        if self._key_frame == 0:
            self._poll_keys()

        if self.state in (IDLE, BLINK):
            self._phase += dt
            k = 0.5 - 0.5 * math.cos(2 * math.pi * self._phase / CONFIG.BREATH_PERIOD_IDLE)
            self._sy = 1.0 + CONFIG.BREATH_AMP_IDLE * k
            self._lift = CONFIG.IDLE_LIFT_MAX * k
            self._bounce = 0.0
            self._tick_follow()

        elif self.state == SLEEP:
            self._phase += dt
            k = 0.5 - 0.5 * math.cos(2 * math.pi * self._phase / CONFIG.BREATH_PERIOD_SLEEP)
            self._sy = CONFIG.SLEEP_SCALE * (1.0 + CONFIG.BREATH_AMP_SLEEP * k)
            self._lift = 0.0
            self._bounce = 0.0

        elif self.state in RUN_STATES:
            self._tick_run(dt)

        elif self.state == HANG:
            self._tick_hang(dt)

        elif self.state == JUMP:
            self._tick_jump(dt)

        elif self.state == DRAG:
            self._tick_drag(dt)

        elif self.state == DROP:
            if self._tick_drop(dt):
                return

        self._update_mask()
        self._maybe_repaint()
        self._track_fps(now)

    def _maybe_repaint(self) -> None:
        """
        只有「画面真的变了」才重绘：按量化后的姿态做签名比较。

        拖拽时窗口只是移动、倾斜稳定后姿态不变，就完全不需要重绘；
        呼吸时 0.001 的缩放差（约 0.14px）肉眼看不出，可以省掉大量重绘。
        """
        signature = (self.state, round(self._sy, 3), round(self._tilt, 1),
                     round(self._lift, 1), round(self._bounce, 1),
                     round(self._follow_shift, 1), self._facing)
        if signature != self._paint_sig:
            self._paint_sig = signature
            self.update()

    def _track_fps(self, now: float) -> None:
        """每 5 秒往 pet.log 写一行实测帧率，方便排查掉帧。"""
        self._fps_frames += 1
        elapsed = now - self._fps_since
        if elapsed < CONFIG.FPS_LOG_SECONDS:
            return
        fps = self._fps_frames / elapsed
        log(f"FPS 实测 {fps:.1f} / 目标 {self._desired_fps()} · 状态 {self.state}"
            f" · 遮罩缓存 {len(self._mask_cache)}")
        self._fps_frames = 0
        self._fps_since = now

    def _tick_drag(self, dt: float) -> None:
        """
        拖拽期间只负责倾斜——位置已经在 mouseMoveEvent 里直接跟手了，
        这里再动窗口就会「追尾」造成橡皮筋感。
        """
        if not self._pressed:               # 兜底：丢掉了松开事件也不会卡在悬空姿势
            self._drag_accum_x = 0.0
            if self.state == DRAG and self._hang_possible and self._near_screen_top():
                self._enter_hang()
            else:
                self._start_drop(interrupted=self._jump_interrupted)
            return

        # 本帧累计的水平位移换算成速度（px/秒），倾斜与帧率无关
        velocity = self._drag_accum_x / dt if dt > 0 else 0.0
        self._drag_accum_x = 0.0
        if abs(velocity) < CONFIG.DRAG_STOP_PXPS:
            goal = 0.0
        else:
            goal = max(-CONFIG.DRAG_TILT_MAX,
                       min(CONFIG.DRAG_TILT_MAX, velocity * CONFIG.DRAG_TILT_PER_PXPS))
        self._tilt += (goal - self._tilt) * CONFIG.DRAG_TILT_EASE

    def _drop_target(self, current: QPointF) -> QPointF:
        """落地目标：向下小落一段，并保证角色不会被落到屏幕外。"""
        fall = self._canvas_w * CONFIG.DROP_FALL_RATIO
        target = QPointF(current.x(), current.y() + fall)
        screen = QGuiApplication.screenAt(QPoint(int(target.x()), int(target.y()))) \
            or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        # foot_world().y() 就是角色可见的最低点（锚点即脚底）
        max_top = avail.bottom() - 2 - self._anchor_px.y()
        if target.y() > max_top:
            target.setY(max_top)
        return target

    def _tick_drop(self, dt: float) -> bool:
        """
        落地过渡，两种曲线：
          settle  —— ease-out 小缓冲（普通松手，落 13px 就停）
          gravity —— ease-in 自由落体（悬挂松手，从屏幕顶一路砸到地面）
        """
        self._dropped_t += dt
        t = min(1.0, self._dropped_t / max(0.01, self._drop_seconds))
        if self._drop_curve == "gravity":
            ease = t * t                      # 越落越快
        else:
            ease = 1.0 - (1.0 - t) ** 2       # 越落越慢
        pos = self._drop_from + (self._drop_to - self._drop_from) * ease
        self._move_to(pos)
        if self._drop_curve == "gravity":
            # 落地瞬间再压扁，靠后面的回弹收尾
            self._sy = 1.0 - (1.0 - CONFIG.JUMP_SQUASH) * min(1.0, t * 1.5)
        else:
            self._sy = CONFIG.DROP_SCALE_FROM - (CONFIG.DROP_SCALE_FROM - 1.0) * ease
        self._tilt = self._drop_tilt_from * (1.0 - ease)
        if t >= 1.0:
            self._sy, self._tilt = 1.0, 0.0
            self._bounce = 0.0
            self._drop_curve = "settle"
            self._drop_seconds = CONFIG.DROP_DURATION
            self._set_state(IDLE, force_mask=True)
            self._schedule_blink()
            self.save_settings()
            return True
        return False

    # ---------------------------------------------------------------- 鼠标
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self._show_menu()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return

        self._last_interact = time.monotonic()
        self._pressed = True
        self._moved = False
        self._press_global = event.globalPosition().toPoint()
        self._grab_offset = QPointF(self._press_global) - QPointF(self.x(), self.y())
        self._drag_accum_x = 0.0

        # 跳跃中按住：拖动优先，立刻打断跳跃把它接住（松手再落到地面）
        if self.state == JUMP:
            self._jump_interrupted = True
            self._jump_phase = ""
            self._begin_drag()
            self._drag_arm_timer.start(CONFIG.DRAG_ARM_MS)
            return

        self.wake_up()                       # 睡着时一按即醒
        # 按住的瞬间不立刻换成悬空姿势：位移超过阈值或按住超过 100ms 才进入 DRAG，
        # 这样单击 / 双击不会出现「举起双手」的闪烁。
        self._drag_arm_timer.start(CONFIG.DRAG_ARM_MS)

    def mouseMoveEvent(self, event) -> None:
        if not self._pressed:
            return
        pos = event.globalPosition()
        delta = pos.toPoint() - self._press_global
        if abs(delta.x()) > CONFIG.CLICK_MOVE_TOLERANCE or abs(delta.y()) > CONFIG.CLICK_MOVE_TOLERANCE:
            if not self._moved:
                self._moved = True
                self._last_interact = time.monotonic()
            if self.state != DRAG:
                self._begin_drag()

        if self.state == DRAG:
            # 直接贴着光标走（不做插值），延迟 ≤ 1 个鼠标事件；
            # 位置只在这里改，_tick_drag 不再动窗口，避免一帧里 move 两次。
            target = pos - self._grab_offset
            self._drag_accum_x += target.x() - self.x()
            self._move_to(target)

    def _move_to(self, target: QPointF) -> None:
        """只在坐标真的变了的时候才调 move()，避免无意义的窗口重排。"""
        nx, ny = int(round(target.x())), int(round(target.y()))
        if nx != self.x() or ny != self.y():
            self.move(nx, ny)

    def _begin_drag(self) -> None:
        """进入拖拽：换悬空姿势、停掉眨眼、以当前光标重算抓取点（不跳）。"""
        self._drag_arm_timer.stop()
        self._blink_timer.stop()
        self._drag_accum_x = 0.0
        self._grab_offset = QPointF(QCursor.pos()) - QPointF(self.x(), self.y())
        # 从悬挂 / 跳跃里被拖走时，把摆动状态清干净
        self._hang_enter = False
        self._hang_amp = 0.0
        self._tilt = 0.0
        self._set_state(DRAG)

    def _arm_drag(self) -> None:
        """按住 100ms 后（即使没移动）也进入拖拽姿势。"""
        if self._pressed and self.state != DRAG:
            self._begin_drag()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._pressed:
            return
        self._pressed = False
        self._drag_arm_timer.stop()
        self._last_interact = time.monotonic()
        self._drag_accum_x = 0.0

        # 悬挂中点一下 = 松手掉下去
        if self.state == HANG:
            self._release_hang()
            return

        if self.state != DRAG:
            # 没进入拖拽 -> 单击
            self._handle_click()
            return

        # 拖到屏幕顶部松手 -> 挂上去（不再走 13px 的小缓冲）
        if self._hang_possible and not self._jump_interrupted and self._near_screen_top():
            self._enter_hang()
            return

        # 真正的拖拽结束 -> DROP
        self._start_drop(interrupted=self._jump_interrupted)

    def _start_drop(self, interrupted: bool = False) -> None:
        """
        从当前高度开始下落。

        普通松手 = 13px 小缓冲（保持原有手感）；
        半空中被接住又放开 = 落到地面（离地近就还是小缓冲）。
        """
        self._jump_interrupted = False
        self._drop_from = QPointF(float(self.x()), float(self.y()))
        if interrupted:
            self._drop_to = QPointF(float(self.x()), self._ground_top_y())
            dist = self._drop_to.y() - self._drop_from.y()
            if dist > CONFIG.JUMP_NEAR_GROUND:
                self._drop_curve = "gravity"
                self._drop_seconds = 0.25 + 0.10 * min(1.0, dist / 900.0)
            else:
                self._drop_curve = "settle"
                self._drop_seconds = CONFIG.DROP_DURATION
                self._drop_to = self._drop_target(self._drop_from)
        else:
            self._drop_curve = "settle"
            self._drop_seconds = CONFIG.DROP_DURATION
            self._drop_to = self._drop_target(self._drop_from)
        self._drop_tilt_from = self._tilt
        self._dropped_t = 0.0
        self._set_state(DROP)

    def _handle_click(self) -> None:
        """单击：苏醒 / 随机眨一次眼。"""
        self._last_interact = time.monotonic()
        if self.state == SLEEP:              # 睡着时点一下直接醒
            self._last_wake_time = time.monotonic()
            self._set_state(IDLE, force_mask=True)
            self._start_blink()
        elif self.state in (IDLE, BLINK):    # 醒着时点一下随机眨一次眼
            self._start_blink()

    def mouseDoubleClickEvent(self, event) -> None:
        """双击：睡着 <-> 醒来（悬挂状态下只认单击松手，双击忽略）。"""
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.state == HANG:
            event.accept()
            return
        self._pressed = False
        self._drag_arm_timer.stop()
        self._last_interact = time.monotonic()
        now = time.monotonic()

        if (now - self._last_wake_time) <= CONFIG.WAKE_GRACE_SECONDS:
            # 刚被这次双击的第一下叫醒：保持清醒，不要立刻又睡回去
            if self.state != IDLE:
                self._set_state(IDLE, force_mask=True)
            self._start_blink()
            return

        if self.state == SLEEP:
            self._last_wake_time = now
            self._set_state(IDLE, force_mask=True)
            self._start_blink()
        else:
            self.go_sleep()
        event.accept()

    def wheelEvent(self, event) -> None:
        """滚轮缩放，每格 1%，以脚底为锚点。"""
        steps = event.angleDelta().y() / 120.0
        if abs(steps) < 1e-6:
            return
        self._last_interact = time.monotonic()
        self.set_zoom(round(self._zoom + steps * CONFIG.ZOOM_STEP, 3))
        event.accept()

    # ---------------------------------------------------------------- 菜单
    def _menu_qss(self) -> str:
        """深色半透明、圆角 8px 的菜单样式。"""
        return """
        QMenu {
            background-color: rgba(28, 30, 34, 238);
            color: #EDEFF3;
            border: 1px solid rgba(255, 255, 255, 30);
            border-radius: 8px;
            padding: 6px;
        }
        QMenu::item {
            padding: 6px 26px 6px 24px;
            border-radius: 5px;
            background: transparent;
        }
        QMenu::item:selected { background-color: rgba(92, 124, 196, 200); }
        QMenu::item:disabled { color: rgba(237, 239, 243, 110); }
        QMenu::separator { height: 1px; background: rgba(255, 255, 255, 26); margin: 5px 8px; }
        QMenu::indicator { width: 14px; height: 14px; left: 6px; }
        QMenu::indicator:checked {
            background-color: #8FB4FF;
            border-radius: 3px;
            border: 1px solid #C7D8FF;
        }
        QMenu::indicator:unchecked {
            background: transparent;
            border: 1px solid rgba(255, 255, 255, 70);
            border-radius: 3px;
        }
        QMenu::right-arrow { width: 10px; height: 10px; }
        """

    def _prepare_menu(self, menu: QMenu) -> None:
        menu.clear()
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        menu.setStyleSheet(self._menu_qss())

    # ---------------------------------------------------------------- 缩放滑杆
    def _make_zoom_action(self, menu: QMenu) -> QWidgetAction:
        """
        把一条横向滑杆塞进菜单：拖动时实时缩放，松手才重建遮罩 + 存盘。

        拖动期间先 clearMask()，这样窗口随缩放变大时不会被旧遮罩切掉边；
        松手立刻按新尺寸重建遮罩，穿透照旧。
        """
        holder = QWidget(menu)
        holder.setFixedSize(CONFIG.ZOOM_SLIDER_W, CONFIG.ZOOM_SLIDER_H)
        holder.setStyleSheet("background: transparent;")

        layout = QHBoxLayout(holder)
        layout.setContentsMargins(12, 6, 10, 6)
        layout.setSpacing(8)

        slider = QSlider(Qt.Orientation.Horizontal, holder)
        slider.setRange(int(round(CONFIG.ZOOM_MIN * 100)), int(round(CONFIG.ZOOM_MAX * 100)))
        slider.setSingleStep(1)
        slider.setPageStep(2)
        slider.setValue(int(round(self._zoom * 100)))
        slider.setFixedHeight(20)
        slider.setStyleSheet("""
            QSlider { background: transparent; }
            QSlider::groove:horizontal {
                height: 4px; background: #4A4A4A; border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                height: 4px; background: #4FA3F7; border-radius: 2px;
            }
            QSlider::handle:horizontal {
                width: 16px; height: 16px; margin: -6px 0;
                border-radius: 8px; background: #FFFFFF; border: 2px solid #4FA3F7;
            }
        """)

        label = QLabel(f"{slider.value()}%", holder)
        label.setFixedWidth(36)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        label.setStyleSheet("color: #EDEFF3; background: transparent; font-size: 12px;")

        layout.addWidget(slider, 1)
        layout.addWidget(label, 0)

        def on_press() -> None:
            self._mask_frozen = True
            self.clearMask()

        def on_value(value: int) -> None:
            label.setText(f"{value}%")
            self.set_zoom(value / 100.0, light=True)

        def on_release() -> None:
            self._mask_frozen = False
            self._update_mask(force=True)
            self.save_settings()
            log(f"缩放 -> {self._zoom * 100:.0f}%（{self._canvas_w}px）")

        slider.sliderPressed.connect(on_press)
        slider.valueChanged.connect(on_value)
        slider.sliderReleased.connect(on_release)

        # 菜单被关掉（例如拖动中途按 Esc）也要恢复遮罩，避免一直处于"无遮罩"状态
        if not getattr(menu, "_zoom_hide_hooked", False):
            menu._zoom_hide_hooked = True
            menu.aboutToHide.connect(self._end_zoom_drag)

        action = QWidgetAction(menu)
        action.setDefaultWidget(holder)
        menu._zoom_holder_ref = holder          # 防止被 GC 掉
        menu._zoom_action_ref = action
        return action

    def _end_zoom_drag(self) -> None:
        """结束滑杆拖动：恢复遮罩、存盘（重复调用安全）。"""
        if not self._mask_frozen:
            return
        self._mask_frozen = False
        self._update_mask(force=True)
        self.save_settings()

    def _add_zoom_slider(self, menu: QMenu) -> None:
        menu.addAction(self._make_zoom_action(menu))

    # ---------------------------------------------------------------- 菜单内容
    def _add_keyboard_toggle(self, menu: QMenu) -> None:
        act = menu.addAction("键盘控制")
        act.setCheckable(True)
        act.setChecked(self._kb_enabled)
        act.setEnabled(self._kb_available)
        act.triggered.connect(lambda _=False: self.set_keyboard_enabled(not self._kb_enabled))

    def fill_menu(self, menu: QMenu) -> None:
        """右键菜单内容：置顶 / 缩放滑杆 / 睡觉 / 键盘控制 / 隐藏 / 退出。"""
        self._prepare_menu(menu)

        act_top = menu.addAction("永远置顶")
        act_top.setCheckable(True)
        act_top.setChecked(self._on_top)
        act_top.triggered.connect(lambda _=False: self.set_on_top(not self._on_top))

        menu.addSeparator()
        self._add_zoom_slider(menu)

        act_sleep = menu.addAction("叫醒" if self.state == SLEEP else "立即睡觉")
        act_sleep.setEnabled(self.state not in (HANG, JUMP))
        act_sleep.triggered.connect(lambda _=False: self.toggle_sleep())
        self._add_keyboard_toggle(menu)

        menu.addSeparator()
        menu.addAction("隐藏到托盘").triggered.connect(self.hide_to_tray)
        menu.addAction("退出").triggered.connect(self.quit_app)

    def fill_tray_menu(self, menu: QMenu) -> None:
        """托盘菜单内容：显示/隐藏、缩放滑杆、睡觉、键盘控制、退出。"""
        self._prepare_menu(menu)
        menu.addAction("隐藏挂件" if self.isVisible() else "显示挂件").triggered.connect(
            self.toggle_visible)
        self._add_zoom_slider(menu)
        act_sleep = menu.addAction("叫醒" if self.state == SLEEP else "立即睡觉")
        act_sleep.setEnabled(self.state not in (HANG, JUMP))
        act_sleep.triggered.connect(lambda _=False: self.toggle_sleep())
        self._add_keyboard_toggle(menu)
        menu.addSeparator()
        menu.addAction("退出").triggered.connect(self.quit_app)

    def set_keyboard_enabled(self, enabled: bool) -> None:
        """开关键盘控制；关掉后完全不再调用 Win32 API。"""
        if enabled and not self._kb_available:
            return
        self._kb_enabled = enabled
        self._keys = set()
        if not enabled and self.state in RUN_STATES:
            self._run_blend = 0.0
            self._set_state(IDLE, force_mask=True)
            self._schedule_blink()
        self.save_settings()
        log(f"键盘控制 -> {'开' if enabled else '关'}")

    def _show_menu(self) -> None:
        self._last_interact = time.monotonic()
        menu = QMenu(self)
        self.fill_menu(menu)
        menu.exec(QCursor.pos())
        menu.deleteLater()

    def set_on_top(self, on_top: bool) -> None:
        """切换永远置顶（切换后保持当前坐标）。"""
        if on_top == self._on_top:
            return
        self._on_top = on_top
        pos = QPoint(self.x(), self.y())
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on_top)
        self.move(pos)
        self.show()
        self.save_settings()
        log(f"永远置顶 -> {on_top}")

    # ---------------------------------------------------------------- 托盘 / 退出
    def attach_tray(self, tray) -> None:
        self._tray = tray

    def hide_to_tray(self) -> None:
        """隐藏到托盘：停止动画节拍，几乎不占 CPU。"""
        self._tick_timer.stop()
        self._blink_timer.stop()
        self._follow_timer.stop()
        self._keys = set()
        self.hide()
        self.save_settings()
        log("已隐藏到托盘")
        if self._tray is not None and not self._tray_hint_shown:
            self._tray_hint_shown = True
            self._tray.showMessage(CONFIG.APP_NAME, "挂件已收进托盘，单击托盘图标可以叫回来。",
                                   QSystemTrayIcon.MessageIcon.Information, 2500)

    def show_pet(self) -> None:
        """显示并置前（也用于「再次启动时把已有窗口提到最前」）。"""
        self.show()
        self.raise_()
        self._last_tick = time.monotonic()
        self._fps_since = self._last_tick
        self._fps_frames = 0
        self._keys = set()
        if not self._tick_timer.isActive():
            self._sync_tick_rate()
            self._tick_timer.start()
        if not self._follow_timer.isActive():
            self._mouse_last_move_ts = 0.0
            self._follow_timer.start()
        self._last_interact = time.monotonic()
        if self.state == IDLE:
            self._schedule_blink()
        self.save_settings()

    def toggle_visible(self) -> None:
        if self.isVisible():
            self.hide_to_tray()
        else:
            self.show_pet()

    def quit_app(self) -> None:
        self.save_settings()
        if self._tray is not None:
            self._tray.hide()
        self._tick_timer.stop()
        QApplication.quit()

    def closeEvent(self, event) -> None:
        self.save_settings()
        super().closeEvent(event)


# ============================================================================
# 5. TrayIcon —— 系统托盘
# ============================================================================
class TrayIcon(QSystemTrayIcon):
    """托盘图标：显示/隐藏、缩放、立即睡觉、退出。"""

    def __init__(self, pet: PetWindow, icon_path: str):
        super().__init__(QIcon(icon_path))
        self._pet = pet
        self.setToolTip(CONFIG.APP_NAME)

        self._menu = QMenu()
        self._menu.aboutToShow.connect(lambda: self._pet.fill_tray_menu(self._menu))
        self.setContextMenu(self._menu)

        self.activated.connect(self._on_activated)
        self._pet.attach_tray(self)
        self.show()

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._pet.toggle_visible()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._pet.toggle_visible()


# ============================================================================
# 6. 单实例
# ============================================================================
class SingleInstance:
    """用 QLocalServer 做单实例：第二次启动时把已有窗口提到最前。"""

    def __init__(self, key: str, on_activate):
        self._key = key
        self._on_activate = on_activate
        self._server: QLocalServer | None = None
        self._sockets: list[QLocalSocket] = []

    def is_primary(self) -> bool:
        socket = QLocalSocket()
        socket.connectToServer(self._key)
        if socket.waitForConnected(300):
            socket.write(b"show")
            socket.flush()
            socket.waitForBytesWritten(500)
            socket.disconnectFromServer()
            return False

        QLocalServer.removeServer(self._key)
        self._server = QLocalServer()
        if not self._server.listen(self._key):
            log(f"单实例锁创建失败：{self._server.errorString()}（不影响运行）")
            return True
        self._server.newConnection.connect(self._on_new_connection)
        return True

    def _on_new_connection(self) -> None:
        while self._server and self._server.hasPendingConnections():
            conn = self._server.nextPendingConnection()
            conn.readyRead.connect(lambda: self._read(conn))
            conn.disconnected.connect(conn.deleteLater)
            self._sockets.append(conn)
            self._on_activate()

    @staticmethod
    def _read(conn: QLocalSocket) -> None:
        conn.readAll()


# ============================================================================
# 7. main —— 启动、单实例、异常兜底
# ============================================================================
def main() -> int:
    _install_excepthook()

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setApplicationName(CONFIG.SETTINGS_APP)
    app.setOrganizationName(CONFIG.SETTINGS_ORG)
    app.setQuitOnLastWindowClosed(False)   # 窗口隐藏到托盘时不要退出

    holder: dict[str, PetWindow] = {}

    def activate_existing() -> None:
        pet = holder.get("pet")
        if pet is not None:
            pet.show_pet()

    instance = SingleInstance(CONFIG.SINGLE_INSTANCE_KEY, activate_existing)
    if not instance.is_primary():
        log("已有实例在运行，已请求它显示到最前。")
        flush_log()
        return 0

    reset_log()                                 # 主实例：清空并开始记录本次运行
    log(f"{CONFIG.APP_NAME} v{CONFIG.VERSION} 启动（PySide6 · {sys.platform}）")

    try:
        assets, anchor, bbox, icon_path = load_assets()
    except Exception as exc:                    # 缺素材等致命错误：弹窗提示
        msg = str(exc)
        log("启动失败：" + msg)
        flush_log()
        QMessageBox.critical(None, CONFIG.APP_NAME + " 启动失败", msg)
        return 1

    pet = PetWindow(assets, anchor, bbox)
    holder["pet"] = pet
    pet.show_pet()

    app.setWindowIcon(QIcon(icon_path))
    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = TrayIcon(pet, icon_path)
    else:
        log("系统托盘不可用，跳过托盘图标（右键菜单仍可使用）")

    app.aboutToQuit.connect(pet.save_settings)
    app.aboutToQuit.connect(flush_log)
    code = app.exec()
    if tray is not None:
        tray.hide()
    return code


if __name__ == "__main__":
    sys.exit(main())
