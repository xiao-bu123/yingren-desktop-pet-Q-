# -*- coding: utf-8 -*-
"""
影刃 v2.0 MVP · 对话界面（补丁 01 + 02）

三个窗口：
  • InputWindow     屏幕正下方居中的输入框（不跟角色，和气泡彻底分开）
  • BubbleWindow    头顶气泡（3 行 / 联网轮 5 行、逐字、6 秒、悬停暂停、来源脚注、不接收鼠标）
  • SettingsDialog  key / base_url / model / 测试连接

授权式感知：Ctrl+Alt+P 普通、Ctrl+Alt+S 看屏幕、Ctrl+Alt+F 联网；
消息里带 http(s) 链接时自动允许读链接。默认全关，只在按键的那一轮给。

规矩：主线程只负责画；网络在 chat_core 的工作线程里，回调经 Qt 信号排队回主线程。
"""

from __future__ import annotations

import base64
import re
import sys
import threading
import time

from PySide6.QtCore import (QBuffer, QEvent, QEventLoop, QIODevice, QObject, QPoint,
                            QPointF, QRect, QRectF, QTimer, QPropertyAnimation,
                            Qt, Signal)
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetrics, QGuiApplication,
                           QImage, QPainter, QPainterPath, QPen, QPolygonF,
                           QTextLayout, QTextOption)
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)

import chat_core

# ---- 外观（产品方案 4.3 / 4.4 + 补丁 01） ----
FONT_FAMILY = "Microsoft YaHei"
FONT_POINT = 9.75                 # ≈ 13px @96dpi
BG_COLOR = QColor(18, 18, 20, 230)
TEXT_COLOR = QColor(237, 237, 237)
BORDER_COLOR = QColor(255, 255, 255, 26)
SOURCE_COLOR = QColor(139, 147, 160)
RADIUS = 10
BUBBLE_W = 260
BUBBLE_LINES = 3
BUBBLE_LINES_SEARCH = 5
TRI_W, TRI_H = 9, 8               # 小三角半宽 / 高
PAD_X, PAD_Y = 12, 9
GAP = 8                           # 气泡与头顶的间距

INPUT_MAX_W = 440                 # 输入框宽 = min(440, 可用宽 × 0.5)
INPUT_H = 38
INPUT_BOTTOM = 48                 # 底边距屏幕可用区底边
INPUT_RADIUS = 12
MODE_BTN_W = 78

HOLD_MS = 6000
FADE_IN_MS = 150
FADE_OUT_MS = 300
INPUT_FADE_OUT_MS = 80
ERROR_HOLD_MS = 2600
POLL_HOVER_MS = 100

HOTKEY_SCREEN = "ctrl+alt+s"
HOTKEY_SEARCH = "ctrl+alt+f"


# ============================================================================
# Win32 小工具：抢焦点 / 还焦点 / 热键轮询
# ============================================================================
def _user32():
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes
        return ctypes.windll.user32
    except Exception:
        return None


def _foreground_hwnd() -> int:
    u = _user32()
    try:
        return int(u.GetForegroundWindow()) if u else 0
    except Exception:
        return 0


def _force_foreground(hwnd: int) -> None:
    """把窗口强行提到前台（输入法只认有焦点的窗口，普通 activateWindow 在后台进程里常被拒）。"""
    u = _user32()
    if u is None or not hwnd:
        return
    try:
        import ctypes
        fg = u.GetForegroundWindow()
        tid_fg = u.GetWindowThreadProcessId(fg, None) if fg else 0
        tid_self = ctypes.windll.kernel32.GetCurrentThreadId()
        attached = bool(tid_fg and tid_fg != tid_self and u.AttachThreadInput(tid_self, tid_fg, True))
        try:
            u.SetForegroundWindow(hwnd)
            u.BringWindowToTop(hwnd)
        finally:
            if attached:
                u.AttachThreadInput(tid_self, tid_fg, False)
    except Exception:
        pass


def _restore_foreground(hwnd: int) -> None:
    if hwnd:
        _force_foreground(hwnd)


_VK_ALIASES = {
    "ctrl": 0x11, "control": 0x11, "alt": 0x12, "menu": 0x12, "shift": 0x10,
    "win": 0x5B, "space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09,
}


def _vk_for(part: str) -> int | None:
    part = part.strip().lower()
    if part in _VK_ALIASES:
        return _VK_ALIASES[part]
    if len(part) == 1 and part.isalnum():
        return ord(part.upper())
    if part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
        return 0x70 + int(part[1:]) - 1
    return None


class HotkeyWatcher:
    """只读轮询组合键（不注册全局热键、不拦截按键）。spec 例：ctrl+alt+p / alt+p / f9。"""

    def __init__(self, spec: str):
        self.parts = [p.strip().lower() for p in (spec or "").split("+") if p.strip()]
        self.vks = [_vk_for(p) for p in self.parts]
        self.available = bool(self.parts) and all(self.vks) and _user32() is not None
        self._down = False
        if not self.available:
            chat_core.log(f"热键不可用：{spec!r}")

    def poll(self) -> bool:
        """检测到「刚按下」返回 True（按住不放只触发一次）。"""
        if not self.available:
            return False
        u = _user32()
        try:
            down = all(u.GetAsyncKeyState(vk) & 0x8000 for vk in self.vks)
        except Exception:
            self.available = False
            return False
        rising = down and not self._down
        self._down = down
        return rising


# ============================================================================
# 气泡
# ============================================================================
class BubbleWindow(QWidget):
    """头顶气泡：不可点、不可悬停“吃”事件；悬停靠全局光标判断，且必须「先出去再进来」。"""

    def __init__(self):
        flags = (Qt.WindowType.FramelessWindowHint
                 | Qt.WindowType.Tool
                 | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.WindowTransparentForInput   # 完全不接收鼠标
                 | Qt.WindowType.WindowDoesNotAcceptFocus
                 | Qt.WindowType.NoDropShadowWindowHint)
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedWidth(BUBBLE_W)

        self._font = QFont(FONT_FAMILY)
        self._font.setPointSizeF(FONT_POINT)
        self._line_h = QFontMetrics(self._font).lineSpacing()
        self._source_font = QFont(FONT_FAMILY)
        self._source_font.setPointSizeF(8.25)          # ≈ 11px
        self._source_h = QFontMetrics(self._source_font).height() + 2

        self._text = ""
        self._display = ""
        self._source = ""
        self._max_lines = BUBBLE_LINES
        self._n_lines = 1
        self._body_h = 0
        self._flip = False              # True = 气泡翻到下方，三角朝上
        self._tri_x = BUBBLE_W / 2.0
        self._head = QPoint(0, 0)
        self._foot = QPoint(0, 0)
        self._x_target = 0
        self._y_target = 0
        self._streaming = False
        self._waiting = False

        self._reset_pending = False
        self._pending_text = ""
        self._new_max_lines = BUBBLE_LINES
        self._new_waiting = "…"

        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.timeout.connect(self.fade_out)
        self._hold_remaining = 0
        self._hold_deadline = 0.0

        self._hover_armed = False
        self._hovering = False
        self._hover = QTimer(self)
        self._hover.setInterval(POLL_HOVER_MS)
        self._hover.timeout.connect(self._tick_hover)

        self._follow = QTimer(self)
        self._follow.setInterval(33)
        self._follow.timeout.connect(self._tick_follow)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.finished.connect(self._on_faded)
        self._slide = QPropertyAnimation(self, b"pos", self)
        self._slide.setDuration(FADE_IN_MS)
        self.hide()

    # ---- 文本布局 ----
    def _paragraph_lines(self, paragraph: str) -> int:
        """QTextLayout 只管一个段落：\n 必须自己拆开算。"""
        if not paragraph:
            return 1
        layout = QTextLayout(paragraph, self._font)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        layout.beginLayout()
        count = 0
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(float(BUBBLE_W - PAD_X * 2))
            count += 1
            if count > 30:
                break
        layout.endLayout()
        return max(1, count)

    def _count_lines(self, text: str) -> int:
        if not text:
            return 1
        return max(1, sum(self._paragraph_lines(p) for p in text.split("\n")))

    def _ellipsize(self, text: str) -> str:
        """超过上限：二分出能放下的最长前缀，末尾加「…」。"""
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self._count_lines(text[:mid].rstrip() + "…") <= self._max_lines:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo].rstrip() + "…"

    def _apply_layout(self) -> bool:
        """重排；返回高度是否变了（只有换行/来源行才 resize）。"""
        text = self._text.strip("\n")
        display = text
        if self._count_lines(text) > self._max_lines:
            display = self._ellipsize(text)
        self._display = display
        lines = min(self._max_lines, self._count_lines(display))
        self._n_lines = lines
        src = self._source_h if self._source else 0
        body = PAD_Y * 2 + lines * self._line_h + src
        changed = body != self._body_h
        self._body_h = body
        self.setFixedHeight(body + TRI_H)
        if changed:
            self.resize(BUBBLE_W, body + TRI_H)
        return changed

    # ---- 绘制 ----
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        top = TRI_H if self._flip else 0
        body = QRectF(0, top, BUBBLE_W, self._body_h)
        path = QPainterPath()
        path.addRoundedRect(body, RADIUS, RADIUS)
        cx = self._tri_x
        if self._flip:
            tri = QPolygonF([QPointF(cx - TRI_W, body.top() + 1),
                             QPointF(cx + TRI_W, body.top() + 1),
                             QPointF(cx, 0)])
        else:
            tri = QPolygonF([QPointF(cx - TRI_W, body.bottom() - 1),
                             QPointF(cx + TRI_W, body.bottom() - 1),
                             QPointF(cx, body.bottom() + TRI_H)])
        path.addPolygon(tri)

        painter.setPen(QPen(BORDER_COLOR, 1))
        painter.setBrush(BG_COLOR)
        painter.drawPath(path)

        painter.setPen(QPen(TEXT_COLOR))
        y = top + PAD_Y
        remaining = self._max_lines
        for paragraph in self._display.split("\n"):
            if remaining <= 0:
                break
            if not paragraph:
                y += self._line_h
                remaining -= 1
                continue
            layout = QTextLayout(paragraph, self._font)
            option = QTextOption()
            option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            layout.setTextOption(option)
            layout.beginLayout()
            while remaining > 0:
                line = layout.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(float(BUBBLE_W - PAD_X * 2))
                line.setPosition(QPointF(PAD_X, y))
                line.draw(painter, QPointF(0, 0))
                y += self._line_h
                remaining -= 1
            layout.endLayout()

        if self._source:
            painter.setFont(self._source_font)
            painter.setPen(QPen(SOURCE_COLOR))
            metrics = QFontMetrics(self._source_font)
            text = metrics.elidedText("来源：" + self._source,
                                      Qt.TextElideMode.ElideRight,
                                      BUBBLE_W - PAD_X * 2)
            source_top = top + PAD_Y + self._n_lines * self._line_h + 1
            painter.drawText(QPointF(PAD_X, source_top + metrics.ascent()), text)
        painter.end()

    # ---- 定位 ----
    def _place(self, instant: bool) -> None:
        screen = QGuiApplication.screenAt(self._head) or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        h = self._body_h + TRI_H
        above_y = self._head.y() - GAP - h
        self._flip = above_y < avail.top()
        y = (self._foot.y() + GAP) if self._flip else above_y
        x = self._head.x() - BUBBLE_W // 2
        x = max(avail.left() + 4, min(avail.right() - BUBBLE_W - 4, x))
        y = max(avail.top() + 4, min(avail.bottom() - h - 4, y))
        # 贴边被夹住时，把三角挪到仍然对着头顶的位置（不然会指偏）
        self._tri_x = max(TRI_W + 10, min(BUBBLE_W - TRI_W - 10, self._head.x() - x))
        self._x_target, self._y_target = x, y
        if instant:
            self.move(x, y)
        else:
            self.move(x, self.y())
            if abs(self._y_target - self.y()) > 1 and not self._follow.isActive():
                self._follow.start()
        self.update()

    def _tick_follow(self) -> None:
        if not self.isVisible():
            self._follow.stop()
            return
        gap = self._y_target - self.y()
        if abs(gap) <= 1:
            if self.y() != self._y_target:
                self.move(self._x_target, self._y_target)
            self._follow.stop()
            return
        ny = self.y() + gap * 0.35
        self.move(self._x_target, int(round(ny)))

    # ---- 显示 / 内容 ----
    def show_message(self, text: str, head: QPoint, foot: QPoint, *,
                     streaming: bool = False, hold_ms: int = HOLD_MS,
                     waiting: bool = False, max_lines: int = BUBBLE_LINES,
                     source: str = "") -> None:
        self._max_lines = max_lines
        self._text = text
        self._source = source
        self._waiting = waiting
        self._streaming = streaming
        self._reset_pending = False
        self._pending_text = ""
        self._head, self._foot = QPoint(head), QPoint(foot)
        self._apply_layout()
        self._place(instant=True)
        self._hover_armed = False
        self._hovering = False
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._fade.stop()
        self._fade.setDuration(FADE_IN_MS)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._slide.stop()
        self._slide.setStartValue(QPoint(self.x(), self.y() + 4))
        self._slide.setEndValue(QPoint(self.x(), self.y()))
        self._slide.start()
        self._hover.start()
        if not streaming:
            self.start_hold(hold_ms)

    def start_waiting(self, head: QPoint, foot: QPoint,
                      max_lines: int = BUBBLE_LINES, text: str = "…") -> None:
        self.show_message(text, head, foot, streaming=True, waiting=True,
                          max_lines=max_lines)

    def begin_new(self, head: QPoint, foot: QPoint, *,
                  max_lines: int = BUBBLE_LINES, waiting_text: str = "…") -> None:
        """
        新一轮：旧气泡 0.1s 淡出 → 同一位置换成「…」再淡入。

        永远只有一个气泡窗口；淡出这 100ms 里到达的 token 先攒着，重置后一次性上屏。
        """
        self._new_max_lines = max_lines
        self._new_waiting = waiting_text
        self._pending_text = ""
        self._hold.stop()
        if not self.isVisible():
            self.show_message(waiting_text, head, foot, streaming=True, waiting=True,
                              max_lines=max_lines)
            return
        self._head, self._foot = QPoint(head), QPoint(foot)
        self._reset_pending = True
        self._fade.stop()
        self._fade.setDuration(100)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.start()
        QTimer.singleShot(110, self._apply_reset)

    def _apply_reset(self) -> None:
        if not self._reset_pending:
            return
        self._reset_pending = False
        self._max_lines = self._new_max_lines
        self._source = ""
        self._waiting = not self._pending_text
        self._streaming = True
        self._text = self._pending_text or self._new_waiting
        self._apply_layout()
        self._place(instant=True)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._fade.stop()
        self._fade.setDuration(FADE_IN_MS)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._hover_armed = False
        self._hovering = False
        self._hover.start()

    @property
    def resetting(self) -> bool:
        return self._reset_pending

    def append(self, chunk: str) -> None:
        if not chunk:
            return
        if self._reset_pending:
            self._pending_text += chunk
            return
        if not self.isVisible():
            return
        if self._waiting:
            self._text = ""
            self._waiting = False
        self._text += chunk
        if self._apply_layout():
            self._place(instant=True)      # 长高一行：底边仍然贴着「头顶 - 8」
        self.update()

    def finish(self, text: str, hold_ms: int = HOLD_MS, source: str = "") -> None:
        self._reset_pending = False
        self._text = text
        self._source = source or ""
        self._waiting = False
        self._streaming = False
        self._apply_layout()
        if self.isVisible():
            self._place(instant=True)
        self.update()
        self.start_hold(hold_ms)

    def follow(self, head: QPoint, foot: QPoint) -> None:
        self._head, self._foot = QPoint(head), QPoint(foot)
        if self.isVisible():
            self._place(instant=False)

    # ---- 6 秒 / 悬停 ----
    def start_hold(self, ms: int) -> None:
        self._hold_remaining = ms
        self._hold_deadline = time.monotonic() + ms / 1000.0
        if self._hovering:
            return
        self._hold.start(ms)

    def _pause_hold(self) -> None:
        if self._hold.isActive():
            self._hold_remaining = max(0, int((self._hold_deadline - time.monotonic()) * 1000))
            self._hold.stop()

    def _resume_hold(self) -> None:
        if self._hold_remaining > 0 and not self._hold.isActive() and not self._streaming:
            self.start_hold(self._hold_remaining)

    def _tick_hover(self) -> None:
        if not self.isVisible():
            self._hover.stop()
            return
        inside = self.frameGeometry().contains(QCursor.pos())
        if not inside:
            self._hover_armed = True        # 先在外面出现过，之后进来才算悬停
        hovering = inside and self._hover_armed
        if hovering != self._hovering:
            self._hovering = hovering
            if hovering:
                self._pause_hold()
            else:
                self._resume_hold()

    def fade_out(self) -> None:
        if not self.isVisible():
            return
        self._hold.stop()
        self._fade.stop()
        self._fade.setDuration(FADE_OUT_MS)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _on_faded(self) -> None:
        if self._reset_pending:
            return
        if self.windowOpacity() <= 0.02:
            self.hide()
            self._hover.stop()
            self._follow.stop()

    def hide_bubble(self) -> None:
        self._reset_pending = False
        self._hold.stop()
        self._hover.stop()
        self._follow.stop()
        self.hide()


# ============================================================================
# 输入框（补丁 01：屏幕正下方，不跟角色）
# ============================================================================
class ChatLineEdit(QLineEdit):
    submitted = Signal(str)
    escaped = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._composing = False

    def event(self, event) -> bool:
        # 输入法组字期间按 Enter 是在选词/上屏，不能当成发送
        if event.type() == QEvent.Type.InputMethod:
            self._composing = bool(event.preeditString())
        return super().event(event)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not self._composing:
                self.submitted.emit(self.text())
            event.accept()
            return
        if key == Qt.Key.Key_Escape:
            self.escaped.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source) -> None:
        """粘贴：多行压成一行。"""
        text = source.text().replace("\r", " ").replace("\n", " ")
        self.insert(text)


class InputWindow(QWidget):
    submitted = Signal(str)
    cancelled = Signal()
    closed = Signal()

    def __init__(self):
        flags = (Qt.WindowType.FramelessWindowHint
                 | Qt.WindowType.Tool
                 | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.NoDropShadowWindowHint)
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(INPUT_MAX_W, INPUT_H)

        self._edit = ChatLineEdit(self)
        self._edit.setPlaceholderText("跟他说点什么…")
        self._edit.setStyleSheet(
            f"QLineEdit{{background:transparent;border:none;color:{TEXT_COLOR.name()};"
            f"font-family:'{FONT_FAMILY}';font-size:13px;"
            f"selection-background-color:#2F6FD0;selection-color:#ffffff;}}")

        self._mode_btn = QPushButton("无", self)
        self._mode_btn.setFixedSize(MODE_BTN_W, 24)
        self._mode_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mode_btn.setToolTip("本轮授权：屏幕 / 联网，点一下切换")
        self._mode_btn.clicked.connect(self.cycle_modes)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(PAD_X, 0, 8, 0)
        layout.setSpacing(6)
        layout.addWidget(self._edit, 1)
        layout.addWidget(self._mode_btn)
        self.setFocusProxy(self._edit)

        self._edit.submitted.connect(self._on_submit)
        self._edit.escaped.connect(self._on_esc)
        self._edit.installEventFilter(self)
        self._prev_hwnd = 0
        self._composing = False
        self._closing = False
        self._modes: set[str] = set()
        self._screen = None

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._slide = QPropertyAnimation(self, b"pos", self)
        self._slide.setDuration(FADE_IN_MS)
        self._refresh_mode_btn()
        self.hide()

    # ---- 模式 ----
    def modes(self) -> set[str]:
        return set(self._modes)

    def _refresh_mode_btn(self) -> None:
        if not self._modes:
            text, active = "无", False
        elif self._modes == {"screen"}:
            text, active = "屏幕", True
        elif self._modes == {"search"}:
            text, active = "联网", True
        else:
            text, active = "屏幕·联网", True
        self._mode_btn.setText(text)
        color = "#2F6FD0" if active else "#3A3D44"
        fg = "#DCE6F6" if active else "#8B93A0"
        self._mode_btn.setStyleSheet(
            f"QPushButton{{background:rgba(47,111,208,0.18);border:1px solid {color};"
            f"border-radius:6px;color:{fg};font-family:'{FONT_FAMILY}';font-size:11px;}}"
            if active else
            f"QPushButton{{background:transparent;border:1px solid {color};"
            f"border-radius:6px;color:{fg};font-family:'{FONT_FAMILY}';font-size:11px;}}")

    def toggle_mode(self, name: str) -> None:
        if name in self._modes:
            self._modes.discard(name)
        else:
            self._modes.add(name)
        self._refresh_mode_btn()
        self._activate()

    def cycle_modes(self) -> None:
        if not self._modes:
            self._modes = {"screen"}
        elif self._modes == {"screen"}:
            self._modes = {"search"}
        elif self._modes == {"search"}:
            self._modes = {"screen", "search"}
        else:
            self._modes = set()
        self._refresh_mode_btn()
        self._activate()

    # ---- 绘制 ----
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(
            QRectF(0.5, 0.5, self.width() - 1, self.height() - 1),
            INPUT_RADIUS, INPUT_RADIUS)
        painter.setPen(QPen(BORDER_COLOR, 1))
        painter.setBrush(BG_COLOR)
        painter.drawPath(path)
        painter.end()

    # ---- 打开 / 关闭 ----
    def open_on(self, screen, *, screen_mode: bool = False,
                search_mode: bool = False) -> None:
        if self._closing:
            self._closing = False
            self._fade.stop()
        if self.isVisible():
            self._activate()
            return
        self._screen = screen
        self._modes = set()
        if screen_mode:
            self._modes.add("screen")
        if search_mode:
            self._modes.add("search")
        self._refresh_mode_btn()
        self._prev_hwnd = _foreground_hwnd()
        self._resize_for(screen)
        self._place()
        self._edit.clear()
        self._closing = False
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._fade.stop()
        self._fade.setDuration(FADE_IN_MS)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._slide.stop()
        self._slide.setStartValue(QPoint(self.x(), self.y() + 6))
        self._slide.setEndValue(QPoint(self.x(), self.y()))
        self._slide.start()
        QTimer.singleShot(40, self._activate)      # 等修饰键松开再激活

    def _resize_for(self, screen) -> None:
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        width = int(min(INPUT_MAX_W, max(240, avail.width() * 0.5)))
        self.setFixedSize(width, INPUT_H)

    def _place(self) -> None:
        screen = self._screen or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        x = avail.left() + (avail.width() - self.width()) // 2
        y = avail.top() + avail.height() - INPUT_BOTTOM - self.height()
        self.move(x, y)

    def _activate(self) -> None:
        if not self.isVisible():
            return
        _force_foreground(int(self.winId()))
        self.activateWindow()
        self._edit.setFocus(Qt.FocusReason.OtherFocusReason)

    def _on_submit(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        self._close(restore=True)
        self.submitted.emit(text)

    def _on_esc(self) -> None:
        self._close(restore=True)
        self.cancelled.emit()

    def _close(self, restore: bool) -> None:
        if self._closing:
            return
        self._closing = True
        self.closed.emit()
        self._fade.stop()
        self._fade.setDuration(INPUT_FADE_OUT_MS)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.start()
        QTimer.singleShot(INPUT_FADE_OUT_MS + 15, self._finish_close)
        if restore:
            hwnd = self._prev_hwnd
            QTimer.singleShot(INPUT_FADE_OUT_MS + 30,
                              lambda: _restore_foreground(hwnd))

    def _finish_close(self) -> None:
        if not self._closing:
            return
        self._closing = False
        self._edit.clear()
        self.hide()
        self.setWindowOpacity(1.0)

    def _close_if_unfocused(self) -> None:
        if self._closing or self._composing:
            return
        if not self._edit.hasFocus():
            self._close(restore=False)

    # ---- 输入法组字时不要失焦关闭 ----
    def eventFilter(self, obj, event) -> bool:
        if obj is self._edit:
            etype = event.type()
            if etype == QEvent.Type.InputMethod:
                self._composing = bool(event.preeditString())
            elif etype == QEvent.Type.FocusOut:
                if not self._closing:
                    QTimer.singleShot(100, self._close_if_unfocused)
        return super().eventFilter(obj, event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        if not self._closing:
            QTimer.singleShot(100, self._close_if_unfocused)


# ============================================================================
# 设置
# ============================================================================
class _TestBridge(QObject):
    done = Signal(bool, str)


class SettingsDialog(QDialog):
    saved = Signal()

    def __init__(self, core: chat_core.ChatCore):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self._core = core
        self.setWindowTitle("跟他说句话 · 设置")
        self.setFixedWidth(440)
        self.setStyleSheet("""
            QDialog { background: #17181B; }
            QLabel { color: #D8D8DA; font-family: 'Microsoft YaHei'; font-size: 13px; }
            QLabel#hint { color: #8B93A0; font-size: 11px; }
            QLabel#warn { color: #E0A33A; font-size: 11px; }
            QLineEdit {
                background: #101114; border: 1px solid #2A2C31; border-radius: 6px;
                padding: 7px 9px; color: #EDEDED; font-family: 'Microsoft YaHei'; font-size: 13px;
                selection-background-color: #2F6FD0;
            }
            QPushButton {
                background: #26282D; color: #E8E8EA; border: 1px solid #34363C;
                border-radius: 6px; padding: 6px 16px; font-family: 'Microsoft YaHei'; font-size: 13px;
            }
            QPushButton:hover { background: #303339; }
            QPushButton#primary { background: #2F6FD0; border-color: #2F6FD0; color: #FFFFFF; }
            QPushButton#primary:hover { background: #3A7BE0; }
        """)

        self._key = QLineEdit()
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        self._hint = QLabel("")
        self._hint.setObjectName("hint")
        self._hint.setWordWrap(True)

        self._advanced_btn = QPushButton("高级 ▸")
        self._advanced_btn.setCheckable(True)
        self._advanced_btn.setStyleSheet("QPushButton{border:none;background:transparent;"
                                         "color:#8B93A0;padding:2px 0;text-align:left;}")
        self._advanced_btn.toggled.connect(self._toggle_advanced)

        self._base = QLineEdit()
        self._model = QLineEdit()
        self._advanced = QWidget()
        adv = QVBoxLayout(self._advanced)
        adv.setContentsMargins(0, 4, 0, 0)
        adv.setSpacing(6)
        adv.addWidget(QLabel("base_url"))
        adv.addWidget(self._base)
        adv.addWidget(QLabel("model"))
        adv.addWidget(self._model)
        self._advanced.setVisible(False)

        self._test_btn = QPushButton("测试连接")
        self._test_btn.clicked.connect(self._on_test)
        self._status = QLabel("")
        self._status.setObjectName("hint")

        self._bridge = _TestBridge()
        self._bridge.done.connect(self._on_test_done)
        self._testing = False

        save_btn = QPushButton("保存")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)

        test_row = QHBoxLayout()
        test_row.addWidget(self._test_btn)
        test_row.addWidget(self._status, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(8)
        root.addWidget(QLabel("API key"))
        root.addWidget(self._key)
        root.addWidget(self._hint)
        root.addWidget(self._advanced_btn)
        root.addWidget(self._advanced)
        root.addLayout(test_row)
        root.addSpacing(4)
        root.addLayout(buttons)
        note = QLabel("key 用 Windows DPAPI 加密，只在这台电脑上能解开。")
        note.setObjectName("hint")
        root.addWidget(note)

        self._load()

    def _toggle_advanced(self, on: bool) -> None:
        self._advanced.setVisible(on)
        self._advanced_btn.setText("高级 ▾" if on else "高级 ▸")
        self.adjustSize()

    def _load(self) -> None:
        cfg = self._core.cfg
        self._base.setText(cfg.base_url)
        self._model.setText(cfg.model)
        key, failed = cfg.read_key()
        if failed:
            self._key.clear()
            self._key.setPlaceholderText("sk-…")
            self._hint.setObjectName("warn")
            self._hint.setText("这台电脑上没找到你的 key，重新粘一次。")
        elif key:
            self._key.clear()
            self._key.setPlaceholderText("已保存，留空表示不修改")
            self._hint.setObjectName("hint")
            self._hint.setText("")
        else:
            self._key.setPlaceholderText("sk-…")
            self._hint.setObjectName("hint")
            self._hint.setText("填一个 DeepSeek key 就能用。")
        self._hint.setVisible(bool(self._hint.text()))
        self._hint.style().unpolish(self._hint)
        self._hint.style().polish(self._hint)
        self.adjustSize()

    def _on_test(self) -> None:
        if self._testing:
            return
        self._testing = True
        self._test_btn.setEnabled(False)
        self._status.setObjectName("hint")
        self._status.setText("连接中…")
        base = self._base.text().strip() or self._core.cfg.base_url
        model = self._model.text().strip() or self._core.cfg.model
        key = self._key.text().strip()
        if not key:
            key = self._core.cfg.read_key()[0]

        def work() -> None:
            ok, msg = self._core.test_connection(base, model, key)
            self._bridge.done.emit(ok, msg)

        threading.Thread(target=work, daemon=True).start()

    def _on_test_done(self, ok: bool, msg: str) -> None:
        self._testing = False
        self._test_btn.setEnabled(True)
        self._status.setObjectName("hint" if ok else "warn")
        self._status.setText(msg)
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)

    def _on_save(self) -> None:
        cfg = self._core.cfg
        key = self._key.text().strip()
        try:
            if key:
                cfg.write_key(key)
        except OSError as exc:
            self._status.setObjectName("warn")
            self._status.setText(f"key 保存失败：{exc}")
            return
        cfg.set("base_url", self._base.text().strip() or cfg.base_url)
        cfg.set("model", self._model.text().strip() or cfg.model)
        cfg.save()
        chat_core.log("设置已保存")
        self.saved.emit()
        self.accept()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._load()
        QTimer.singleShot(0, self._center)

    def _center(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = self.frameGeometry()
        geo.moveCenter(screen.availableGeometry().center())
        self.move(geo.topLeft())


# ============================================================================
# 总控
# ============================================================================
class _CoreBridge(QObject):
    """把 chat_core 工作线程里的回调转成 Qt 信号（自动排队回主线程）。"""

    delta = Signal(str)
    final = Signal(str, str)
    error = Signal(object)


def _is_black(pix) -> bool:
    """截图几乎全黑 = 独占全屏，画不出来。"""
    try:
        img = pix.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
        small = img.scaled(32, 32, Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    except Exception:
        return False
    total, count = 0, 0
    for y in range(small.height()):
        for x in range(small.width()):
            total += small.pixelColor(x, y).value()
            count += 1
    return count > 0 and total / count < 8


def _pix_to_png(pix) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pix.save(buffer, "PNG")
    data = bytes(buffer.data())
    buffer.close()
    return data


class ChatController:
    """把 core / 气泡 / 输入框 / 设置 串起来，并告诉 pet 什么时候该安静。"""

    def __init__(self, pet, base_dir: str | None = None):
        self.pet = pet
        self.core = chat_core.ChatCore(base_dir) if base_dir else chat_core.ChatCore()
        self.bubble = BubbleWindow()
        self.input = InputWindow()
        self.settings: SettingsDialog | None = None

        self._hk_normal = HotkeyWatcher(self.core.cfg.hotkey)
        self._hk_screen = HotkeyWatcher(HOTKEY_SCREEN)
        self._hk_search = HotkeyWatcher(HOTKEY_SEARCH)

        self._waiting = False
        self._streaming = False
        self._fail_streak = 0
        self._last_error = ""

        self._bridge = _CoreBridge()
        self._bridge.delta.connect(self._on_delta)
        self._bridge.final.connect(self._on_final)
        self._bridge.error.connect(self._on_error)

        self.input.submitted.connect(self._on_submit)
        self.input.closed.connect(self._on_input_closed)
        QTimer.singleShot(1400, self._maybe_first_hint)

    # ---- 状态给 pet 用 ----
    @property
    def chat_active(self) -> bool:
        return self.input.isVisible() or self._waiting or self._streaming

    @property
    def streaming(self) -> bool:
        return self._streaming

    def poll_hotkey(self) -> None:
        if self.settings is not None and self.settings.isVisible():
            return
        if self.input.isVisible():
            if self._hk_screen.poll():
                self.input.toggle_mode("screen")
            if self._hk_search.poll():
                self.input.toggle_mode("search")
            return
        if self._hk_normal.poll():
            self.open_input()
        elif self._hk_screen.poll():
            self.open_input(screen_mode=True)
        elif self._hk_search.poll():
            self.open_input(search_mode=True)

    def on_pet_moved(self) -> None:
        """只有气泡跟角色；输入框固定在屏幕底部，不跟。"""
        if self.bubble.isVisible():
            head, foot = self.pet.chat_anchor()
            self.bubble.follow(head, foot)

    def on_pet_hidden(self) -> None:
        self.core.cancel()
        self.input._close(restore=False)
        self.bubble.hide_bubble()
        self._waiting = self._streaming = False
        self.pet.set_chat_active(False)

    # ---- 入口 ----
    def open_input(self, screen_mode: bool = False, search_mode: bool = False) -> None:
        if self.settings is not None and self.settings.isVisible():
            return
        key, failed = self.core.cfg.read_key()
        if failed or not key:
            self.open_settings(focus_key=True)
            return
        if screen_mode and not self.core.cfg.vision_enabled:
            self._quick_reply("看不了。")
            return
        if search_mode and not self.core.cfg.search_enabled:
            self._quick_reply("查不了。")
            return
        foot = self.pet.chat_anchor()[1]
        screen = QGuiApplication.screenAt(foot) or QGuiApplication.primaryScreen()
        self.input.open_on(screen, screen_mode=screen_mode, search_mode=search_mode)
        self.pet.set_chat_active(True)

    def _on_input_closed(self) -> None:
        """输入框被 Esc / 失焦 / 发送关掉：没有在等回复就把角色动作还回去。"""
        if not self._waiting and not self._streaming:
            self.pet.set_chat_active(False)

    def open_settings(self, focus_key: bool = False) -> None:
        if self.settings is None:
            self.settings = SettingsDialog(self.core)
            self.settings.saved.connect(self._on_settings_saved)
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()
        if focus_key:
            self.settings._key.setFocus()

    def forget(self) -> None:
        self.core.memory.clear()
        head, foot = self.pet.chat_anchor()
        self.bubble.show_message("……忘了。", head, foot, hold_ms=2000)

    def shutdown(self) -> None:
        self.core.cancel()
        self.input._close(restore=False)
        self.bubble.hide_bubble()

    # ---- 发送 ----
    def _on_submit(self, text: str) -> None:
        modes = self.input.modes()
        if not text:
            return
        self.pet.set_chat_active(True)
        if "screen" in modes:
            if not self.core.cfg.vision_enabled:
                self._quick_reply("看不了。")
                return
            self._capture_and_send(text, modes)
            return
        if "search" in modes and not self.core.cfg.search_enabled:
            self._quick_reply("查不了。")
            return
        self._begin_send(text, modes, None)

    def _quick_reply(self, text: str, hold_ms: int = ERROR_HOLD_MS) -> None:
        head, foot = self.pet.chat_anchor()
        self.bubble.show_message(text, head, foot, hold_ms=hold_ms)
        self._waiting = self._streaming = False
        self.pet.set_chat_active(False)

    def _begin_send(self, text: str, modes: set[str], png: bytes | None) -> None:
        search = "search" in modes
        head, foot = self.pet.chat_anchor()
        self.bubble.begin_new(head, foot,
                              max_lines=BUBBLE_LINES_SEARCH if search else BUBBLE_LINES,
                              waiting_text="查着呢" if search else "…")
        self._waiting = True
        self._streaming = False
        self._dispatch(text, modes, png, 0)

    def _dispatch(self, text: str, modes: set[str], png: bytes | None,
                  attempt: int) -> None:
        if self.core.busy:
            if attempt >= 30:
                self._waiting = False
                self.bubble.finish("等一下。", ERROR_HOLD_MS)
                self.pet.set_chat_active(False)
                return
            self.core.cancel()
            QTimer.singleShot(80, lambda: self._dispatch(text, modes, png, attempt + 1))
            return
        search = "search" in modes
        read_link = bool(re.search(r"https?://\S+", text))
        ok = self.core.send(
            text, self._bridge.delta.emit, self._bridge.final.emit,
            self._bridge.error.emit,
            image_png=png, web_search=search, read_url=read_link)
        if not ok:
            QTimer.singleShot(80, lambda: self._dispatch(text, modes, png, attempt + 1))

    # ---- 截图（只有 Ctrl+Alt+S / 输入框模式灯能触发）----
    def _screen_for_capture(self):
        foot = self.pet.chat_anchor()[1]
        return QGuiApplication.screenAt(foot) or QGuiApplication.primaryScreen()

    def _capture_and_send(self, text: str, modes: set[str]) -> None:
        screen = self._screen_for_capture()
        # 拍之前把自己藏起来 150ms，否则会拍到自己的气泡/角色
        self.pet.hide()
        self.bubble.hide_bubble()
        QTimer.singleShot(150, lambda: self._grab_screen(screen, text, modes))

    def _grab_screen(self, screen, text: str, modes: set[str]) -> None:
        pix = None
        try:
            pix = screen.grabWindow(0) if screen is not None else None
        except Exception as exc:
            chat_core.log(f"截图失败：{exc}")
        self.pet.show()
        if pix is None or pix.isNull():
            self._quick_reply("……没截到。")
            return
        max_px = self.core.cfg.screenshot_max_px
        if max(pix.width(), pix.height()) > max_px:
            pix = pix.scaled(max_px, max_px, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        if _is_black(pix):
            chat_core.log("截图几乎全黑（可能是独占全屏），本轮不发请求")
            self._quick_reply("……你开的是全屏，我看不见。", 4000)
            return
        png = _pix_to_png(pix)
        chat_core.log(f"附带截图 {pix.width()}x{pix.height()}，约 "
                      f"{int(pix.width() * pix.height() / 750)} token")
        self._begin_send(text, modes, png)

    # ---- 回调 ----
    def _on_delta(self, chunk: str) -> None:
        if self._waiting:
            self._waiting = False
            self._streaming = True
            self.pet.set_chat_streaming(True)
        self.bubble.append(chunk)

    def _on_final(self, text: str, source: str = "") -> None:
        self._waiting = self._streaming = False
        self._fail_streak = 0
        self.bubble.finish(text, HOLD_MS, source=source)
        self.pet.set_chat_streaming(False)
        self.pet.set_chat_active(False)

    def _on_error(self, exc: chat_core.ChatError) -> None:
        self._waiting = self._streaming = False
        self.bubble.finish(exc.text, ERROR_HOLD_MS)
        self.pet.set_chat_streaming(False)
        self.pet.set_chat_active(False)
        self._fail_streak += 1
        if self._fail_streak >= 3 and exc.text != self._last_error:
            self._last_error = exc.text
            self.pet.tray_message("一直连不上，点托盘去设置看看")
        if exc.need_key:
            self.open_settings(focus_key=True)

    # ---- 设置保存后 ----
    def _on_settings_saved(self) -> None:
        self._hk_normal = HotkeyWatcher(self.core.cfg.hotkey)
        self._fail_streak = 0

    # ---- 首次提示 ----
    def _maybe_first_hint(self) -> None:
        if not self.core.cfg.first_run_hint:
            return
        if not self.pet.isVisible():
            return
        head, foot = self.pet.chat_anchor()
        self.bubble.show_message("Ctrl+Alt+P，跟我说话", head, foot, hold_ms=5200)
        self.core.cfg.mark_hint_shown()

