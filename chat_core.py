# -*- coding: utf-8 -*-
"""
影刃 v2.0 MVP · 对话内核（命令行与桌宠共用）

职责：配置（chat.ini）、key 加密（Windows DPAPI）、记忆（chat_history.json）、
SSE 流式请求、错误映射、格式清理、命令行入口。

这个文件**不 import PySide6**：`python chat_core.py` 应该能单独跑起来，
桌宠那边只负责把 token 画到气泡里。

约定：
  • 网络请求在后台线程里跑，回调可能发生在非主线程 —— Qt 侧必须走信号转发。
  • 所有异常都先过 map_error()，上层只显示中文短句，绝不转发服务端原文。
  • 配置文件由本文件自己读写，绝不过 QSettings。
"""

from __future__ import annotations

import base64
import configparser
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import urlsplit

# ----------------------------------------------------------------------------
# 目录约定（与 pet.py 一致：exe / 脚本旁边就是数据目录）
# ----------------------------------------------------------------------------
FROZEN = bool(getattr(sys, "frozen", False))
BASE_DIR = (os.path.dirname(os.path.abspath(sys.executable)) if FROZEN
            else os.path.dirname(os.path.abspath(__file__)))

CONFIG_FILE = "chat.ini"
HISTORY_FILE = "chat_history.json"
PERSONA_PATH = os.path.join("assets", "persona.md")
LOG_FILE = "chat.log"

VERSION = "2.0-MVP"

# ----------------------------------------------------------------------------
# 系统提示：人设之外必须补的三段（见产品方案 5.2）
# 这三段写在代码里，不放在 persona.md —— 改人设的人不该顺手把它删掉。
# ----------------------------------------------------------------------------
SYSTEM_EXTRA = """【运行环境】
你运行在用户 Windows 桌面右下角的小挂件里。
默认你看不见他的屏幕、看不到他的游戏，只能看见他主动打给你的字。
只有他把东西推到你面前时——一张截图、一个链接、一句「去查」——你才看得见那一样，就这一次。
上一次的看不见。他没给的看不见。
你没有声音，你打出来的字就是你说的话。不要描述动作，不要写括号旁白。

【回复长度】
一次 1～2 句，40 字以内，最多 3 行。想多说的，忍住。
只有主人明确让你联网查的时候，才可以放宽到 5 行 / 80 字。
没有例外，问什么都不用写长，讲不清楚就反问。

【格式】
不要用 Markdown：不要 **加粗**、# 标题、- 列表、`代码`。
不要用表情符号。需要分行就直接换行。"""

# 人设文件缺失时的兜底（保证不会因此起不来）
FALLBACK_PERSONA = (
    "你是「魂」，一个话不多的刀客。说话短、平、带一点冷幽默，不客套，不叫「您」。"
)


# ============================================================================
# 1. 日志
# ============================================================================
def log(message: str) -> None:
    """写 chat.log（超过 2MB 时截断重来，避免无限长）。只记文件，不往终端刷。"""
    path = os.path.join(BASE_DIR, LOG_FILE)
    stamp = datetime.now().strftime("%m-%d %H:%M:%S")
    try:
        if os.path.exists(path) and os.path.getsize(path) > 2 * 1024 * 1024:
            os.replace(path, path + ".old")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {message}\n")
    except OSError:
        pass


# ============================================================================
# 2. DPAPI —— key 不明文落盘（只在本机、本用户下能解开）
# ============================================================================
if sys.platform.startswith("win"):
    import ctypes
    import ctypes.wintypes as _wt

    class _DataBlob(ctypes.Structure):
        _fields_ = [("cbData", _wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32

    _crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob), _wt.LPCWSTR, ctypes.POINTER(_DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, _wt.DWORD, ctypes.POINTER(_DataBlob)]
    _crypt32.CryptProtectData.restype = _wt.BOOL
    _crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.POINTER(_wt.LPWSTR), ctypes.POINTER(_DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, _wt.DWORD, ctypes.POINTER(_DataBlob)]
    _crypt32.CryptUnprotectData.restype = _wt.BOOL
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p

    def _make_blob(data: bytes):
        buf = ctypes.create_string_buffer(data, len(data))
        return _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def _take_blob(blob: "_DataBlob") -> bytes:
        try:
            return ctypes.string_at(blob.pbData, blob.cbData)
        finally:
            _kernel32.LocalFree(ctypes.cast(blob.pbData, ctypes.c_void_p))

    def dpapi_encrypt(text: str) -> str:
        """明文 -> base64(DPAPI 密文)。失败抛 OSError。"""
        data = text.encode("utf-8")
        in_blob, _buf = _make_blob(data)
        out_blob = _DataBlob()
        ok = _crypt32.CryptProtectData(
            ctypes.byref(in_blob), "yingren-chat", None, None, None, 0,
            ctypes.byref(out_blob))
        if not ok:
            raise OSError("CryptProtectData 失败")
        return base64.b64encode(_take_blob(out_blob)).decode("ascii")

    def dpapi_decrypt(cipher_b64: str) -> str | None:
        """base64(DPAPI 密文) -> 明文；解不开（换了电脑 / 换了用户）返回 None。"""
        try:
            data = base64.b64decode(cipher_b64, validate=True)
        except (ValueError, TypeError):
            return None
        if not data:
            return None
        in_blob, _buf = _make_blob(data)
        out_blob = _DataBlob()
        ok = _crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob))
        if not ok:
            return None
        try:
            return _take_blob(out_blob).decode("utf-8", "replace")
        except Exception:
            return None
else:                                                    # pragma: no cover
    def dpapi_encrypt(text: str) -> str:
        raise OSError("当前平台不支持 DPAPI")

    def dpapi_decrypt(cipher_b64: str) -> str | None:
        return None


# ============================================================================
# 3. 配置 —— chat.ini（自己读写，绝不过 QSettings）
# ============================================================================
CONFIG_DEFAULTS = {
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-flash",
    "key_cipher": "",
    "key_plain": "",
    "temperature": "0.95",
    "max_tokens": "72",
    "max_turns": "6",
    "history_hours": "24",
    "timeout_connect": "10",
    "timeout_stall": "20",
    "hotkey": "ctrl+alt+p",
    "first_run_hint": "1",
    # ---- 补丁 02：授权式感知 ----
    "vision_enabled": "1",
    "search_enabled": "1",
    "max_tokens_search": "180",
    "timeout_stall_search": "40",
    "screenshot_max_px": "1600",
}

_TEMPLATE = """\
[chat]
# 只填这一行就能用：把 sk-... 粘在等号后面（也可以启动桌宠，在设置窗里填）
key_plain =
# 设置窗保存后 key 会写成加密的 key_cipher；有 cipher 时忽略 plain
key_cipher =
base_url = https://api.deepseek.com/v1
# deepseek-flash 支持图片输入和联网工具；换成 deepseek-chat 会失去这两项
model = deepseek-flash
temperature = 0.95
max_tokens = 72
max_turns = 6
history_hours = 24
timeout_connect = 10
timeout_stall = 20
hotkey = ctrl+alt+p
first_run_hint = 1
# 授权式感知：关掉后按 Ctrl+Alt+S / F 直接拒绝
vision_enabled = 1
search_enabled = 1
max_tokens_search = 180
timeout_stall_search = 40
screenshot_max_px = 1600
"""


class ChatConfig:
    """chat.ini 的读写。字段见产品方案 8.8。"""

    def __init__(self, base_dir: str = BASE_DIR):
        self.base_dir = base_dir
        self.path = os.path.join(base_dir, CONFIG_FILE)
        self._parser = configparser.ConfigParser(interpolation=None)
        if not os.path.exists(self.path):
            self._write_template()
        try:
            self._parser.read(self.path, encoding="utf-8")
        except (configparser.Error, OSError, UnicodeDecodeError) as exc:
            log(f"chat.ini 读取失败（{exc}），本次使用默认值")
            self._parser = configparser.ConfigParser(interpolation=None)
        if not self._parser.has_section("chat"):
            self._parser.add_section("chat")

    # ---- 基础读写 ----
    def _write_template(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as fh:
                fh.write(_TEMPLATE)
            log(f"已生成配置模板：{self.path}")
        except OSError as exc:
            log(f"配置模板写入失败（{exc}）")

    def get(self, key: str, default: str | None = None) -> str:
        fallback = CONFIG_DEFAULTS.get(key, "") if default is None else default
        try:
            return self._parser.get("chat", key, fallback=fallback)
        except (configparser.Error, ValueError):
            return fallback

    def set(self, key: str, value: str) -> None:
        if not self._parser.has_section("chat"):
            self._parser.add_section("chat")
        self._parser.set("chat", key, str(value))

    def save(self) -> None:
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                self._parser.write(fh)
            os.replace(tmp, self.path)
        except OSError as exc:
            log(f"chat.ini 保存失败（{exc}）")

    # ---- 类型化字段 ----
    def get_int(self, key: str, lo: int, hi: int) -> int:
        fallback = int(CONFIG_DEFAULTS.get(key, lo))
        try:
            value = int(float(self.get(key)))
        except (TypeError, ValueError):
            return fallback
        return max(lo, min(hi, value))

    def get_float(self, key: str, lo: float, hi: float) -> float:
        fallback = float(CONFIG_DEFAULTS.get(key, lo))
        try:
            value = float(self.get(key))
        except (TypeError, ValueError):
            return fallback
        return max(lo, min(hi, value))

    @property
    def base_url(self) -> str:
        return (self.get("base_url") or CONFIG_DEFAULTS["base_url"]).strip().rstrip("/")

    @property
    def model(self) -> str:
        return (self.get("model") or CONFIG_DEFAULTS["model"]).strip()

    @property
    def temperature(self) -> float:
        return self.get_float("temperature", 0.0, 2.0)

    @property
    def max_tokens(self) -> int:
        return self.get_int("max_tokens", 8, 4096)

    @property
    def max_turns(self) -> int:
        return self.get_int("max_turns", 1, 50)

    @property
    def history_hours(self) -> int:
        return self.get_int("history_hours", 1, 24 * 30)

    @property
    def timeout_connect(self) -> float:
        return self.get_float("timeout_connect", 1.0, 120.0)

    @property
    def timeout_stall(self) -> float:
        return self.get_float("timeout_stall", 2.0, 300.0)

    @property
    def hotkey(self) -> str:
        return (self.get("hotkey") or "ctrl+alt+p").strip().lower()

    @property
    def first_run_hint(self) -> bool:
        return self.get("first_run_hint").strip() not in ("0", "false", "False", "")

    @property
    def vision_enabled(self) -> bool:
        return self.get("vision_enabled").strip() not in ("0", "false", "False", "")

    @property
    def search_enabled(self) -> bool:
        return self.get("search_enabled").strip() not in ("0", "false", "False", "")

    @property
    def max_tokens_search(self) -> int:
        return self.get_int("max_tokens_search", 16, 4096)

    @property
    def timeout_stall_search(self) -> float:
        return self.get_float("timeout_stall_search", 2.0, 300.0)

    @property
    def screenshot_max_px(self) -> int:
        return self.get_int("screenshot_max_px", 320, 8192)

    def mark_hint_shown(self) -> None:
        self.set("first_run_hint", "0")
        self.save()

    # ---- key ----
    def read_key(self) -> tuple[str, bool]:
        """
        返回 (key, 解密失败)。

        有 key_cipher 但解不开（换了电脑 / 换了 Windows 用户）时返回 ("", True)，
        上层要提示「这台电脑上没找到你的 key」，而不是「key 不对」。
        """
        cipher = (self.get("key_cipher") or "").strip()
        if cipher:
            plain = dpapi_decrypt(cipher)
            if plain is None:
                return "", True
            return plain.strip(), False
        return (self.get("key_plain") or "").strip(), False

    def write_key(self, key: str) -> None:
        key = (key or "").strip()
        if key:
            self.set("key_cipher", dpapi_encrypt(key))
            self.set("key_plain", "")
        else:
            self.set("key_cipher", "")
            self.set("key_plain", "")
        self.save()


# ============================================================================
# 4. 记忆 —— 6 轮 / 24 小时 / 成对 / 坏了就当空
# ============================================================================
class Memory:
    """chat_history.json：最近若干轮对话，供下一次请求拼上下文。"""

    def __init__(self, path: str, max_turns: int = 6, hours: int = 24):
        self.path = path
        self.max_turns = max(1, int(max_turns))
        self.hours = max(1, int(hours))
        self._messages: list[dict] = []
        self.load()

    # ---- 磁盘 ----
    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            self._messages = []
            return
        messages = data.get("messages") if isinstance(data, dict) else None
        if not isinstance(messages, list):
            log("chat_history.json 结构不认识，按空历史处理")
            self._messages = []
            return
        cleaned = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            ts = item.get("ts")
            if role not in ("user", "assistant") or not isinstance(content, str):
                continue
            if not isinstance(ts, (int, float)):
                continue
            cleaned.append({"role": role, "content": content, "ts": float(ts)})
        self._messages = cleaned
        self.prune()

    def _save(self) -> None:
        payload = {"version": 1, "messages": self._messages}
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError as exc:
            log(f"记忆写入失败（{exc}）")

    # ---- 规则 ----
    def prune(self, now: float | None = None) -> None:
        """
        顺序不能变：先逐条按 ts 过滤 → 再裁到 6 轮 → 再砍掉头部孤立的 assistant。

        逐条过滤而不是整文件丢：跨零点聊的那段，第二天上午还应该接得上。
        """
        now = time.time() if now is None else now
        cutoff = now - self.hours * 3600
        msgs = [m for m in self._messages if m["ts"] >= cutoff]

        max_messages = self.max_turns * 2
        if len(msgs) > max_messages:
            msgs = msgs[-max_messages:]

        while msgs and msgs[0]["role"] != "user":
            msgs.pop(0)
        # 尾巴上单独一条 user 说明上次回答没写完（崩溃 / 取消），丢掉，免得出现两个 user 连排
        while msgs and msgs[-1]["role"] != "assistant":
            msgs.pop()

        self._messages = msgs

    def messages(self) -> list[dict]:
        """给接口用的消息列表（只留 role / content）。"""
        return [{"role": m["role"], "content": m["content"]} for m in self._messages]

    def add(self, user_text: str, assistant_text: str) -> None:
        now = time.time()
        self._messages.append({"role": "user", "content": user_text, "ts": now})
        self._messages.append({"role": "assistant", "content": assistant_text, "ts": now})
        self.prune(now)
        self._save()

    def clear(self) -> None:
        self._messages = []
        self._save()
        log("记忆已清空")


# ============================================================================
# 5. 错误映射 —— 上层只拿中文短句
# ============================================================================
ERROR_TEXT = {
    400: "设置里有项填错了。",
    401: "key 不对。",
    402: "额度没了。",
    429: "太快了，等会。",
}
TEXT_BROKEN = "……断了。"
TEXT_STALL = "……没声了。"
TEXT_EMPTY = "……"
TEXT_OTHER = "……出问题了。"
TEXT_LONG_THINK = "……它想太久了。"


class ChatError(Exception):
    """带「中文文案 + 归类」的异常：need_key=True 时只有设置窗能救。"""

    def __init__(self, text: str, kind: str = "other", status: int | None = None,
                 need_key: bool = False):
        super().__init__(text)
        self.text = text
        self.kind = kind              # conn / stall / http / stream / other / nokey
        self.status = status
        self.need_key = need_key


def _hint_from_message(message: str) -> int | None:
    """把服务端英文 message 归类成状态码（不外传原文）。"""
    m = (message or "").lower()
    if not m:
        return None
    if "insufficient" in m or "balance" in m or "quota" in m:
        return 402
    if "rate limit" in m or "too many" in m or "requests" in m and "limit" in m:
        return 429
    if "authentication" in m or "api key" in m or "unauthorized" in m or "no such user" in m:
        return 401
    if "model" in m or "parameter" in m or "invalid request" in m or "bad request" in m:
        return 400
    return None


def map_status(status: int, message: str = "") -> ChatError:
    """HTTP 状态码 / 流内 error -> ChatError。"""
    hint = _hint_from_message(message)
    code = hint if hint else status
    if code in ERROR_TEXT:
        return ChatError(ERROR_TEXT[code], kind="http", status=code,
                         need_key=(code == 401))
    if 500 <= code < 600:
        return ChatError("它那边坏了。", kind="http", status=code)
    return ChatError(TEXT_OTHER, kind="http", status=status)


def map_stream_error(obj) -> ChatError:
    """流里 `data: {"error": {...}}` —— 这条必须单独判，否则只会变成「……出问题了」。"""
    if isinstance(obj, dict):
        message = str(obj.get("message") or obj.get("type") or "")
        code = obj.get("code")
        if isinstance(code, str):
            message = message + " " + code
        return map_status(int(_hint_from_message(message) or 0), message)
    return ChatError(TEXT_OTHER, kind="stream")


def map_error(exc: BaseException) -> ChatError:
    """所有异常的最后一道关。"""
    if isinstance(exc, ChatError):
        return exc
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return ChatError(TEXT_STALL, kind="stall")
    if isinstance(exc, urllib.error.HTTPError):
        body = ""
        try:
            body = exc.read(4000).decode("utf-8", "replace")
        except Exception:
            pass
        return map_status(exc.code, body)
    if isinstance(exc, urllib.error.URLError):
        return ChatError(TEXT_BROKEN, kind="conn")
    if isinstance(exc, (ConnectionError, socket.gaierror, OSError)):
        return ChatError(TEXT_BROKEN, kind="conn")
    return ChatError(TEXT_OTHER, kind="other")


# ============================================================================
# 6. 回复清理 —— 长度、Markdown、空回复
# ============================================================================
_SENTENCE_ENDS = "。！？!?；;"


def strip_markdown(text: str) -> str:
    """回复定稿时一次性剥掉 ** # ` >，流式阶段原样显示。"""
    lines = []
    for raw in (text or "").replace("\r", "").split("\n"):
        line = raw.strip()
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^>\s*", "", line)
        line = re.sub(r"^[-*+]\s+", "", line)
        line = line.replace("**", "").replace("__", "").replace("`", "")
        lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines).strip()


def fit_last_sentence(text: str) -> str:
    """
    被 max_tokens 截断时，退到最后一个整句再加「…」。

    宁可少一句，也不能让半句上屏；一个标点都没有就硬截 40 字。
    """
    if not text:
        return text
    idx = max(text.rfind(ch) for ch in _SENTENCE_ENDS)
    if idx >= len(text) - 1:
        return text
    if idx >= 0:
        return text[:idx + 1] + "…"
    return text[:40].rstrip() + "…"


_GREETING_PATTERNS = ("您好", "很高兴为您服务", "作为ai", "作为 ai", "有什么可以帮")


def _check_persona_smell(text: str) -> None:
    """出现客服腔只记日志，不改写 —— 拿去改人设。"""
    low = text.lower()
    for pat in _GREETING_PATTERNS:
        if pat in low:
            log(f"人设可疑：回复里出现「{pat}」")
            break


# ============================================================================
# 7. ChatCore —— 真正的请求
# ============================================================================
class _Cancelled(Exception):
    pass


def _domain(url: str) -> str:
    """从 URL 取域名（来源脚注用）。"""
    try:
        host = urlsplit(url).netloc
    except (ValueError, TypeError):
        return ""
    host = host.split("@")[-1].split(":")[0].lower()
    return host[4:] if host.startswith("www.") else host


def _source_from(*holders) -> str:
    """从流式对象里找来源：annotations[].url_citation.url / sources[].site_name。"""
    for holder in holders:
        if not isinstance(holder, dict):
            continue
        for ann in holder.get("annotations") or []:
            if not isinstance(ann, dict):
                continue
            citation = ann.get("url_citation") or {}
            if isinstance(citation, dict):
                if citation.get("url"):
                    return _domain(str(citation["url"])) or str(citation["url"])
                if citation.get("title"):
                    return str(citation["title"])
            if ann.get("url"):
                return _domain(str(ann["url"])) or str(ann["url"])
        for src in holder.get("sources") or []:
            if not isinstance(src, dict):
                continue
            if src.get("site_name"):
                return str(src["site_name"])
            if src.get("url"):
                return _domain(str(src["url"]))
    return ""


class ChatCore:
    """一次只跑一个请求；回调发生在工作线程，Qt 侧必须转成信号。"""

    def __init__(self, base_dir: str = BASE_DIR):
        self.base_dir = base_dir
        self.cfg = ChatConfig(base_dir)
        self.memory = Memory(os.path.join(base_dir, HISTORY_FILE),
                             self.cfg.max_turns, self.cfg.history_hours)
        self.system_prompt = self._build_system_prompt()
        self._busy = False
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._response = None
        self._gen = 0                   # 每轮一个代号：旧线程的回调/清理不能污染新一轮

    # ---- 启动时构建一次：每次现读文件会破坏前缀缓存 ----
    def _build_system_prompt(self) -> str:
        # exe 打包后资产在 sys._MEIPASS；exe 同目录的 assets/ 优先（方便改人设不用重新打包）
        candidates = [os.path.join(self.base_dir, PERSONA_PATH)]
        bundle = getattr(sys, "_MEIPASS", "")
        if bundle:
            candidates.append(os.path.join(bundle, PERSONA_PATH))
        persona = ""
        for path in candidates:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    persona = fh.read().strip()
                break
            except OSError:
                continue
        if not persona:
            log(f"人设文件缺失：{candidates[-1]}（使用兜底人设）")
            persona = FALLBACK_PERSONA
        return persona + "\n\n" + SYSTEM_EXTRA

    # ---- 状态 ----
    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    def cancel(self) -> None:
        """取消：置标志位 + 关连接，两件都要做（只置标志位线程会卡在 read 上）。"""
        self._cancel.set()
        resp = self._response
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

    # ---- 发送 ----
    def send(self, text: str, on_delta, on_final, on_error, *,
             image_png: bytes | None = None,
             web_search: bool = False,
             read_url: bool = False) -> bool:
        """
        异步发送一条用户消息。返回 False 表示上一轮还没结束。

        on_delta(str)              流式片段（原样，可能带 Markdown）
        on_final(text, source)     定稿；source 只在联网轮有值（域名）
        on_error(ChatError)

        补丁 02：image_png 只在授权截图的那一轮传；web_search / read_url 决定
        本轮请求体里声明哪个工具（不声明 = 模型没法用，这就是"授权"的唯一实现）。
        """
        with self._lock:
            if self._busy:
                return False
            self._busy = True
            self._gen += 1
            gen = self._gen
        self._cancel.clear()
        t0 = time.monotonic()
        threading.Thread(
            target=self._run,
            args=(gen, text, on_delta, on_final, on_error, t0,
                  image_png, web_search, read_url),
            name="ChatCore", daemon=True).start()
        return True

    def _run(self, gen: int, text: str, on_delta, on_final, on_error, t0: float,
             image_png: bytes | None, web_search: bool, read_url: bool) -> None:
        try:
            raw, finish, source = self._stream(
                text, on_delta, t0, image_png, web_search, read_url)
            shown = self._finalize(raw, finish, web_search)
            if gen != self._gen or self._cancel.is_set():
                raise _Cancelled()
            mem_text = text + ("\n（附了一张屏幕截图）" if image_png else "")
            self.memory.add(mem_text, shown)
            log(f"回答完成：{len(shown)} 字，用时 {time.monotonic() - t0:.2f}s"
                + (f"，来源 {source}" if source else "")
                + ("，联网轮" if web_search else ""))
            on_final(shown, source)
        except _Cancelled:
            log(f"请求已取消（gen={gen}）")
        except ChatError as exc:
            log(f"请求失败：kind={exc.kind} status={exc.status} text={exc.text}")
            if gen == self._gen:
                on_error(exc)
        except Exception as exc:                                  # pragma: no cover
            log(f"未预期异常：{type(exc).__name__}: {exc}")
            if gen == self._gen:
                on_error(map_error(exc))
        finally:
            with self._lock:
                if self._gen == gen:
                    self._busy = False

    def _finalize(self, raw: str, finish: str | None, web_search: bool = False) -> str:
        text = strip_markdown(raw)
        if finish == "length":
            text = fit_last_sentence(text) if raw.strip() else TEXT_LONG_THINK
        if not text.strip():
            text = "没查到。" if web_search else TEXT_EMPTY
        _check_persona_smell(text)
        return text

    @staticmethod
    def _status_line(image: bool, web: bool, link: bool) -> str:
        """本轮「给了什么」只进 user 消息，不进 system（一改 system 前缀缓存就废）。"""
        if image and web:
            return "【本轮：给你看了截图，也允许联网。】\n"
        if image:
            return "【本轮：主人给你看了一张屏幕截图。】\n"
        if web:
            return "【本轮：主人允许你联网查。】\n"
        if link:
            return "【本轮：主人给你看了一个链接。】\n"
        return "【本轮：什么都没给你。】\n"

    # ---- 流式请求 ----
    def _stream(self, user_text: str, on_delta, t0: float,
                image_png: bytes | None = None,
                web_search: bool = False,
                read_url: bool = False) -> tuple[str, str | None, str]:
        key, decrypt_failed = self.cfg.read_key()
        if decrypt_failed:
            raise ChatError("这台电脑上没找到你的 key。", kind="nokey", need_key=True)
        if not key:
            raise ChatError("还没填 key。", kind="nokey", need_key=True)

        has_link = bool(re.search(r"https?://\S+", user_text or ""))
        content_text = self._status_line(bool(image_png), web_search, has_link) + user_text
        if image_png:
            b64 = base64.b64encode(image_png).decode("ascii")
            user_content = [
                {"type": "text", "text": content_text},
                {"type": "image_url",
                 "image_url": {"url": "data:image/png;base64," + b64}},
            ]
        else:
            user_content = content_text

        payload = {
            "model": self.cfg.model,
            "messages": ([{"role": "system", "content": self.system_prompt}]
                         + self.memory.messages()
                         + [{"role": "user", "content": user_content}]),
            "stream": True,
            "temperature": self.cfg.temperature,
            "max_tokens": (self.cfg.max_tokens_search if web_search
                           else self.cfg.max_tokens),
            # 2026-11 起 deepseek 两个模型思考模式默认开启；不显式关掉，
            # max_tokens=72 会被思维链吃光，回复是空的，temperature 也不生效。
            "thinking": {"type": "disabled"},
        }
        tools = []
        if web_search:
            tools.append({"type": "deepseek_web_search"})
        if read_url or has_link:
            tools.append({"type": "deepseek_read_url"})
        if tools:
            payload["tools"] = tools

        stall = (self.cfg.timeout_stall_search if web_search
                 else self.cfg.timeout_stall)
        url = self.cfg.base_url + "/chat/completions"
        req = urllib.request.Request(
            url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json",
                     "Accept": "text/event-stream",
                     "Authorization": "Bearer " + key,
                     "User-Agent": f"YingRenPet/{VERSION}"})

        try:
            resp = urllib.request.urlopen(req, timeout=self.cfg.timeout_connect)
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read(4000).decode("utf-8", "replace")
            except Exception:
                pass
            raise map_status(exc.code, body) from exc
        except urllib.error.URLError as exc:
            raise ChatError(TEXT_BROKEN, kind="conn") from exc
        except (socket.timeout, TimeoutError) as exc:
            raise ChatError(TEXT_STALL, kind="stall") from exc
        except OSError as exc:
            raise ChatError(TEXT_BROKEN, kind="conn") from exc

        self._response = resp
        # 连接已经建立，把读超时换成「多久没新字算卡死」（urlopen 的超时只管到连接）
        try:
            resp.fp.raw._sock.settimeout(stall)
        except Exception:
            pass

        full: list[str] = []
        finish: str | None = None
        source = ""
        first = True
        try:
            while True:
                if self._cancel.is_set():
                    raise _Cancelled()
                try:
                    line = resp.readline()
                except (socket.timeout, TimeoutError) as exc:
                    if self._cancel.is_set():
                        raise _Cancelled() from exc
                    raise ChatError(TEXT_STALL, kind="stall") from exc
                except Exception as exc:
                    if self._cancel.is_set():
                        raise _Cancelled() from exc
                    raise ChatError(TEXT_BROKEN, kind="conn") from exc
                if not line:
                    break
                text = line.decode("utf-8", "replace").strip()
                if not text or not text.startswith("data:"):
                    continue
                body = text[5:].strip()
                if body == "[DONE]":
                    break
                try:
                    obj = json.loads(body)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                # 流内错误必须第一件事就判（HTTP 200 里也会塞 error）
                if obj.get("error"):
                    raise map_stream_error(obj["error"])
                choices = obj.get("choices") or []
                if choices:
                    choice = choices[0] if isinstance(choices[0], dict) else {}
                    delta_obj = choice.get("delta") or {}
                    delta = delta_obj.get("content") or ""
                    if delta:
                        if first:
                            first = False
                            log(f"首字 {time.monotonic() - t0:.2f}s")
                        full.append(delta)
                        on_delta(delta)
                    if choice.get("finish_reason"):
                        finish = choice["finish_reason"]
                    source = _source_from(obj, choice, delta_obj) or source
                else:
                    source = _source_from(obj) or source
        finally:
            try:
                resp.close()
            except Exception:
                pass
            if self._response is resp:
                self._response = None

        return "".join(full), finish, source

    # ---- 设置窗的「测试连接」 ----
    def test_connection(self, base_url: str | None = None, model: str | None = None,
                        key: str | None = None) -> tuple[bool, str]:
        """同步请求一个最小 payload，只看通不通。"""
        if key is None:
            key, failed = self.cfg.read_key()
            if failed:
                return False, "这台电脑上没找到你的 key。"
        if not key:
            return False, "还没填 key。"
        base = (base_url or self.cfg.base_url).rstrip("/")
        payload = {
            "model": model or self.cfg.model,
            "messages": [{"role": "user", "content": "在吗"}],
            "stream": False,
            "temperature": 0.2,
            "max_tokens": 8,
            "thinking": {"type": "disabled"},
        }
        req = urllib.request.Request(
            base + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + key,
                     "User-Agent": f"YingRenPet/{VERSION}"})
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout_connect) as resp:
                raw = resp.read(8192)
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read(4000).decode("utf-8", "replace")
            except Exception:
                pass
            return False, map_status(exc.code, body).text
        except (socket.timeout, TimeoutError):
            return False, TEXT_STALL
        except (urllib.error.URLError, OSError):
            return False, TEXT_BROKEN
        try:
            obj = json.loads(raw.decode("utf-8", "replace"))
            if obj.get("error"):
                return False, map_stream_error(obj["error"]).text
            obj["choices"][0]["message"]["content"]
        except Exception:
            return False, TEXT_OTHER
        return True, f"通了（{payload['model']}）。"


# ============================================================================
# 8. 命令行 —— 阶段一的验证入口
# ============================================================================
class _StreamCleaner:
    """终端里也把 ** / ` / 行首 # > 过滤掉（和定稿的清理规则一致）。"""

    def __init__(self):
        self._line_start = True
        self._skip_space = False

    def feed(self, chunk: str) -> str:
        out = []
        for ch in chunk:
            if ch in ("*", "`", "\r"):
                continue
            if self._line_start:
                if ch in "#>":
                    self._skip_space = True
                    continue
                if ch == " " and self._skip_space:
                    self._skip_space = False
                    continue
                self._skip_space = False
            out.append(ch)
            if ch == "\n":
                self._line_start = True
            else:
                self._line_start = False
        return "".join(out)


def _cli() -> int:
    core = ChatCore()
    key, failed = core.cfg.read_key()
    if failed:
        print("这台电脑上没找到你的 key，重新粘一次。")
    if not key:
        print("还没填 key。")
        print(f"把 key 粘到 {core.cfg.path} 的 key_plain= 后面，或先启动桌宠在设置窗里填。")
        return 0

    print(f"影刃 v{VERSION} · 模型 {core.cfg.model} · /reset 清空记忆 · /quit 退出")
    cleaner = _StreamCleaner()
    while True:
        try:
            line = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("/quit", "/exit", "/q"):
            break
        if line == "/reset":
            core.memory.clear()
            print("（忘了刚才的话。）")
            continue

        print("他> ", end="", flush=True)
        done = threading.Event()

        def on_delta(chunk: str) -> None:
            sys.stdout.write(cleaner.feed(chunk))
            sys.stdout.flush()

        def on_final(_text: str, source: str = "") -> None:
            if source:
                print(f"\n（来源：{source}）")
            else:
                print()
            done.set()

        def on_error(exc: ChatError) -> None:
            print()
            print(exc.text)
            done.set()

        core.send(line, on_delta, on_final, on_error)
        done.wait()
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
