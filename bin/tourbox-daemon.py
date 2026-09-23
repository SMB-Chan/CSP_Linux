#!/usr/bin/env python3
"""TourBox Lite ドライバ（Linux ネイティブ / root 不要）

公式 TourBox Console は Wine 上でローダーデッドロックして起動しない。
代わりに /dev/ttyACM* を直接開き、アンロック列
(55 00 07 88 94 00 1a fe) を送ると、以降 1 バイト＝1 イベントが
流れてくる（最上位ビットが立っていると解放）。それを X11 の XTEST
拡張で注入する。

注入方式について（実測 2026-09-23）:
  XSendEvent は Wine の X11 ドライバが合成イベントを無視するため
  「送信は成功するのに何も起きない」。XTEST は XWayland/mutter 下でも
  Wine ウィンドウに正しく届く（keyecho.exe で確認済み）。
  よって XTEST を使う。uinput は /dev/uinput が root 専用で使えない。

XTEST はフォーカス中のウィンドウへ送られるグローバル注入なので、
注入前に必ずフォーカス先の WM_CLASS を検査し、対象アプリ以外へ
キーが漏れないようにする。

使い方:
  tourbox-daemon.py                 常駐
  tourbox-daemon.py --scan          生イベントを表示（割り当て確認用）
  tourbox-daemon.py --probe         アンロック応答だけ確認して終了
  tourbox-daemon.py --test ctrl+z   注入経路だけをテスト

設定: ~/ClipStudio/etc/tourbox.conf （SIGHUP で再読み込み）
"""
import argparse
import configparser
import fcntl
import glob
import logging
import os
import re
import select
import signal
import struct
import sys
import termios
import time
import tty

from Xlib import X, XK, Xatom, display
from Xlib.ext import xtest
from Xlib.protocol import event as xev

LOG = logging.getLogger("tourbox")

UNLOCK_COMMAND = bytes.fromhex("5500078894001afe")

# 20 バイト以上の読み出しはデバイス応答フレームで入力イベントではない。
# 0x00 の並びを 'tall' と解釈すると修飾キーが押しっぱなしになるので捨てる。
RESPONSE_FRAME_MIN_BYTES = 20

# コントロール名 -> (押下バイト, 解放バイト)
BUTTON_CODES = {
    "side": (0x01, 0x81),
    "top": (0x02, 0x82),
    "scroll_click": (0x0A, 0x8A),
    "c1": (0x22, 0xA2),
    "c2": (0x23, 0xA3),
    "tall": (0x00, 0x80),
    "short": (0x03, 0x83),
    "dpad_up": (0x10, 0x90),
    "dpad_down": (0x11, 0x91),
    "dpad_left": (0x12, 0x92),
    "dpad_right": (0x13, 0x93),
    "knob_click": (0x37, 0xB7),
    "tour": (0x2A, 0xAA),
    "dial_click": (0x38, 0xB8),
    "scroll_up": (0x49, 0xC9),
    "scroll_down": (0x09, 0x89),
    "knob_cw": (0x44, 0xC4),
    "knob_ccw": (0x04, 0x84),
    "dial_cw": (0x4F, 0xCF),
    "dial_ccw": (0x0F, 0x8F),
}
BYTE_TO_CONTROL = {}
for _name, (_press, _release) in BUTTON_CODES.items():
    BYTE_TO_CONTROL[_press] = (_name, True)
    BYTE_TO_CONTROL[_release] = (_name, False)

ROTARY = {"scroll_up", "scroll_down", "knob_cw", "knob_ccw", "dial_cw", "dial_ccw"}

# 押下/解放イベントを持つ物理ボタン（長押し割り当てが可能）
HOLDABLE = {
    "side", "top", "tall", "short", "c1", "c2", "tour",
    "dpad_up", "dpad_down", "dpad_left", "dpad_right",
    "scroll_click", "knob_click", "dial_click",
}

MODIFIERS = {
    "shift": (XK.XK_Shift_L, X.ShiftMask),
    "ctrl": (XK.XK_Control_L, X.ControlMask),
    "control": (XK.XK_Control_L, X.ControlMask),
    "alt": (XK.XK_Alt_L, X.Mod1Mask),
    "super": (XK.XK_Super_L, X.Mod4Mask),
    "meta": (XK.XK_Super_L, X.Mod4Mask),
    "win": (XK.XK_Super_L, X.Mod4Mask),
}

MOUSE_BUTTONS = {"left": 1, "middle": 2, "right": 3, "back": 8, "forward": 9}

# キー名 -> X keysym 名（大文字小文字や慣用名の吸収）
KEY_ALIASES = {
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "esc": "Escape", "escape": "Escape", "enter": "Return", "return": "Return",
    "tab": "Tab", "space": "space", "backspace": "BackSpace",
    "delete": "Delete", "del": "Delete", "insert": "Insert",
    "home": "Home", "end": "End", "pageup": "Page_Up", "pagedown": "Page_Down",
    "pgup": "Page_Up", "pgdn": "Page_Down", "minus": "minus", "equal": "equal",
    "plus": "plus", "comma": "comma", "dot": "period", "period": "period",
    "slash": "slash", "backslash": "backslash", "semicolon": "semicolon",
    "bracketleft": "bracketleft", "bracketright": "bracketright",
    "quoteleft": "quoteleft", "apostrophe": "apostrophe", "grave": "grave",
}
for _i in range(1, 13):
    KEY_ALIASES["f%d" % _i] = "F%d" % _i

_KEYSYM_NAMES = {}
for _attr, _val in vars(XK).items():
    if _attr.startswith("XK_") and isinstance(_val, int):
        _KEYSYM_NAMES.setdefault(_val, _attr[3:])


def keysym_name(keysym):
    return _KEYSYM_NAMES.get(keysym, hex(keysym))


def keysym_of(name):
    """設定ファイルのキー名を keysym に変換する。"""
    cand = KEY_ALIASES.get(name.lower())
    if cand:
        ks = XK.string_to_keysym(cand)
        if ks:
            return ks
    for variant in (name, name.capitalize(), name.upper(), name.lower()):
        ks = XK.string_to_keysym(variant)
        if ks:
            return ks
    return 0


# ---------------------------------------------------------------------------
# シリアルポート
# ---------------------------------------------------------------------------

def find_port(vendor="cafe", product=None, explicit=None):
    """TourBox の CDC-ACM ポートを探す。"""
    if explicit and explicit != "auto":
        return explicit
    for t in sorted(glob.glob("/sys/class/tty/ttyACM*")):
        up = os.path.dirname(os.path.realpath(os.path.join(t, "device")))
        try:
            with open(os.path.join(up, "idVendor")) as f:
                vid = f.read().strip()
            with open(os.path.join(up, "idProduct")) as f:
                pid = f.read().strip()
        except OSError:
            continue
        if vid.lower() != (vendor or "cafe").lower():
            continue
        if product and pid.lower() != product.lower():
            continue
        return "/dev/" + os.path.basename(t)
    return None


def open_serial(path, baud=115200):
    """termios で raw 8N1 に設定して開く（pyserial 不要）。"""
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    tty.setraw(fd)
    attrs = termios.tcgetattr(fd)
    speed = getattr(termios, "B%d" % baud, None)
    if speed is None:
        LOG.warning("ボーレート %s は使えないので 115200 を使います", baud)
        speed = termios.B115200
    attrs[4] = speed
    attrs[5] = speed
    attrs[2] = (attrs[2] & ~termios.PARENB & ~termios.CSTOPB & ~termios.CSIZE) \
        | termios.CS8 | termios.CLOCAL
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    for bit in (termios.TIOCM_DTR, termios.TIOCM_RTS):
        try:
            fcntl.ioctl(fd, termios.TIOCMBIS, struct.pack("I", bit))
        except OSError:
            pass
    try:                                    # 他プロセスの横入りを防ぐ
        fcntl.ioctl(fd, termios.TIOCEXCL)
    except OSError:
        pass
    termios.tcflush(fd, termios.TCIOFLUSH)
    return fd


def read_bytes(fd, timeout=0.2):
    r, _, _ = select.select([fd], [], [], timeout)
    if not r:
        return b""
    try:
        return os.read(fd, 4096)
    except BlockingIOError:
        return b""


# ---------------------------------------------------------------------------
# アクション
# ---------------------------------------------------------------------------

class Action:
    def __init__(self, mods, keys, wheels, buttons, hold):
        self.mods = mods        # [(keysym, mask)]
        self.keys = keys        # [keysym]
        self.wheels = wheels    # [(x_button, repeat)]
        self.buttons = buttons  # [x_button]
        self.hold = hold

    def __str__(self):
        parts = [keysym_name(ks) for ks, _ in self.mods]
        parts += [keysym_name(k) for k in self.keys]
        parts += ["wheel(b%d)x%d" % (b, n) for b, n in self.wheels]
        parts += ["btn%d" % b for b in self.buttons]
        return ("hold:" if self.hold else "tap:") + "+".join(parts)


def parse_action(text):
    """'ctrl+shift+z' / 'wheel:1' / 'hold:space' / 'btn:right' / 'none' を解析。"""
    text = (text or "").strip()
    if not text or text.lower() == "none":
        return None

    hold = None
    low = text.lower()
    if low.startswith("hold:"):
        hold, text = True, text[5:].strip()
    elif low.startswith("tap:"):
        hold, text = False, text[4:].strip()
    if not text or text.lower() == "none":
        return None

    mods, keys, wheels, buttons = [], [], [], []
    for raw in text.split("+"):
        tok = raw.strip()
        if not tok:
            continue
        lowtok = tok.lower()

        if lowtok.startswith("wheel:") or lowtok.startswith("hwheel:"):
            try:
                val = int(tok.split(":", 1)[1])
            except ValueError:
                LOG.warning("wheel の値が不正: %s", tok)
                continue
            if val == 0:
                continue
            horiz = lowtok.startswith("hwheel:")
            btn = (7 if val > 0 else 6) if horiz else (4 if val > 0 else 5)
            wheels.append((btn, abs(val)))
            continue

        if lowtok.startswith("btn:"):
            name = tok.split(":", 1)[1].strip().lower()
            if name not in MOUSE_BUTTONS:
                LOG.warning("不明なマウスボタン名: %s", name)
                continue
            buttons.append(MOUSE_BUTTONS[name])
            continue

        if lowtok in MODIFIERS:
            mods.append(MODIFIERS[lowtok])
            continue

        ks = keysym_of(tok)
        if not ks:
            LOG.warning("不明なキー名: %s", tok)
            continue
        keys.append(ks)

    if not (mods or keys or wheels or buttons):
        return None
    if hold is None:
        hold = bool(mods) and not (keys or wheels or buttons)
    return Action(mods, keys, wheels, buttons, hold)


# ---------------------------------------------------------------------------
# X11 注入
# ---------------------------------------------------------------------------

class Injector:
    """XTEST でフォーカス中のウィンドウにキー／ボタンを送る。

    XTEST はグローバル注入（フォーカス先に届く）なので、送る直前に
    フォーカス先の WM_CLASS を検査し、対象外なら何も送らない。
    """

    def __init__(self, target_re, inject_any=False,
                 modifier_delay=8, key_hold_ms=30):
        self.d = display.Display()
        self.root = self.d.screen().root
        if not self.d.has_extension("XTEST"):
            raise RuntimeError("X サーバに XTEST 拡張がありません")
        self.target_re = target_re
        self.inject_any = inject_any
        self.modifier_delay = modifier_delay / 1000.0
        self.key_hold_ms = key_hold_ms / 1000.0
        self.keycode_cache = {}
        self._net_active = self.d.intern_atom("_NET_ACTIVE_WINDOW")
        self.held = []              # [(kind, detail, mask)] 全体で押下中
        self.by_control = {}        # control -> [(kind, detail, mask)]
        self._spare_keycode = self._find_spare_keycode()

    FRAME_CLASSES = ("mutter-x11-frames",)

    # -- 補助 -------------------------------------------------------------
    def _find_spare_keycode(self):
        """キーマップに無い keysym 用に、空いている keycode を 1 つ確保する。"""
        try:
            mn = self.d.display.info.min_keycode
            mx = self.d.display.info.max_keycode
            mapping = self.d.get_keyboard_mapping(mn, mx - mn + 1)
            for i, syms in enumerate(mapping):
                if not any(syms):
                    return mn + i
        except Exception as ex:
            LOG.debug("空き keycode の探索に失敗: %s", ex)
        return None

    def keycode(self, keysym):
        """keysym -> keycode。キーマップに無ければ一時的に割り当てる。"""
        if keysym in self.keycode_cache:
            return self.keycode_cache[keysym]
        code = self.d.keysym_to_keycode(keysym)
        if not code and self._spare_keycode:
            # 現在のレイアウトに無いキー（例: JIS 配列での記号）を救済する。
            try:
                self.d.change_keyboard_mapping(self._spare_keycode,
                                               [[keysym] * 8])
                self.d.sync()
                code = self._spare_keycode
                LOG.info("keysym %s をキーコード %d に一時割り当てしました",
                         keysym_name(keysym), code)
            except Exception as ex:
                LOG.warning("キーマップの一時変更に失敗: %s", ex)
        self.keycode_cache[keysym] = code
        return code

    def _wm_class(self, win, depth=0):
        if win is None or depth > 6:
            return None
        try:
            cls = win.get_wm_class()
            if cls and (cls[0] or cls[1]):
                if cls[0] in self.FRAME_CLASSES or cls[1] in self.FRAME_CLASSES:
                    # mutter の装飾フレーム。中の本物のクライアントを探す。
                    inner = self._descend(win)
                    if inner is not None:
                        return inner
                return cls
        except Exception:
            return None
        try:
            parent = win.query_tree().parent
        except Exception:
            return None
        if parent and parent.id not in (self.root.id, 0):
            return self._wm_class(parent, depth + 1)
        return None

    def _descend(self, win, depth=0):
        """装飾フレームの内側にあるクライアントの WM_CLASS を返す。"""
        if depth > 4:
            return None
        try:
            children = win.query_tree().children
        except Exception:
            return None
        for child in children:
            try:
                cls = child.get_wm_class()
            except Exception:
                continue
            if cls and (cls[0] or cls[1]) \
                    and cls[0] not in self.FRAME_CLASSES:
                return cls
            found = self._descend(child, depth + 1)
            if found:
                return found
        return None

    def _allowed(self, cls):
        if not cls:
            return False
        if self.target_re == "*":
            return True
        return bool(re.search(self.target_re, cls[0] or "", re.I)
                    or re.search(self.target_re, cls[1] or "", re.I))

    def target(self):
        """現在のフォーカス先（許可されたウィンドウのみ）。"""
        try:
            focus = self.d.get_input_focus().focus
        except Exception:
            return None
        if isinstance(focus, int) or focus in (X.NONE, X.PointerRoot):
            # フォーカスが根に落ちている場合は _NET_ACTIVE_WINDOW で補う。
            focus = self._active_window()
            if focus is None:
                return None
        cls = self._wm_class(focus)
        if self._allowed(cls):
            return focus
        if self.inject_any:
            return focus
        LOG.debug("フォーカス class=%s は注入対象外", cls)
        return None

    def _active_window(self):
        try:
            prop = self.root.get_full_property(self._net_active, Xatom.WINDOW)
        except Exception:
            return None
        if not prop or not prop.value:
            return None
        return self.d.create_resource_object("window", prop.value[0])

    def top_level(self):
        """マップされているトップレベルウィンドウを列挙する。

        mutter は各ウィンドウを装飾フレームで包むので、フレームの内側に
        ある本物のクライアントも一緒に拾う。
        """
        out = []
        try:
            children = self.root.query_tree().children
        except Exception:
            return out
        for w in children:
            try:
                if w.get_attributes().map_state != X.IsViewable:
                    continue
            except Exception:
                continue
            for cand in (w,) + tuple(self._clients_under(w)):
                try:
                    name = str(cand.get_wm_name() or "")
                    cls = cand.get_wm_class() or ("", "")
                    out.append((cand, name, "%s.%s" % cls))
                except Exception:
                    continue
        return out

    def _clients_under(self, win, depth=0):
        """装飾フレーム配下のクライアントウィンドウを集める。"""
        found = []
        if depth > 3:
            return found
        try:
            children = win.query_tree().children
        except Exception:
            return found
        for child in children:
            try:
                cls = child.get_wm_class()
            except Exception:
                continue
            if cls and (cls[0] or cls[1]) and cls[0] not in self.FRAME_CLASSES:
                found.append(child)
            found.extend(self._clients_under(child, depth + 1))
        return found

    def find_window(self, spec):
        """名前か WM_CLASS の部分一致でウィンドウを探す。"""
        if spec.lower().startswith("0x"):
            return self.d.create_resource_object("window", int(spec, 16))
        needle = spec.lower()
        for w, name, cls in self.top_level():
            if needle in name.lower() or needle in cls.lower():
                return w
        return None

    def focus_window(self, win):
        """EWMH でウィンドウを前面に出す（WM に握り潰されない方法）。"""
        ev = xev.ClientMessage(window=win, client_type=self._net_active,
                               data=(32, [2, X.CurrentTime, 0, 0, 0]))
        try:
            self.root.send_event(ev, event_mask=X.SubstructureRedirectMask
                                 | X.SubstructureNotifyMask)
            self.d.sync()
        except Exception as ex:
            LOG.debug("_NET_ACTIVE_WINDOW の送信に失敗: %s", ex)
        try:                                # 念のため直接も試す
            win.set_input_focus(X.RevertToParent, X.CurrentTime)
            self.d.sync()
        except Exception:
            pass
        time.sleep(0.3)

    # -- XTEST 下位操作 ---------------------------------------------------
    def _fake(self, kind, detail):
        try:
            xtest.fake_input(self.d, kind, detail)
            self.d.sync()
            return True
        except Exception as ex:
            LOG.warning("XTEST 注入に失敗: %s", ex)
            return False

    def _send_key(self, code, press):
        return self._fake(X.KeyPress if press else X.KeyRelease, code)

    def _send_button(self, button, press):
        return self._fake(X.ButtonPress if press else X.ButtonRelease, button)

    def _warp_into(self, win):
        """ホイールはポインタ位置のウィンドウに届くので、必要なら移動する。"""
        try:
            pointer = self.root.query_pointer()
            child = pointer.child
            if child and self._allowed(self._wm_class(child)):
                return                      # すでに対象上にある
            geom = win.get_geometry()
            off = win.translate_coords(self.root, 0, 0)
            x = -off.x + geom.width // 2
            y = -off.y + geom.height // 2
            xtest.fake_input(self.d, X.MotionNotify, x=x, y=y)
            self.d.sync()
            time.sleep(0.01)
        except Exception as ex:
            LOG.debug("ポインタ移動に失敗: %s", ex)

    # -- 公開 API ---------------------------------------------------------
    def press(self, action, control):
        """押し下げ。control 単位で記録し、解放時に同じキーを離す。"""
        win = self.target()
        if win is None:
            LOG.debug("%s: 注入対象なし", control)
            return False
        mine = []

        for keysym, mask in action.mods:
            code = self.keycode(keysym)
            if not code:
                LOG.warning("キーコード不明: %s", keysym_name(keysym))
                continue
            self._send_key(code, True)
            self.held.append(("mod", code, mask))
            mine.append(("mod", code, mask))
            time.sleep(0.002)

        if action.mods and (action.keys or action.wheels or action.buttons):
            time.sleep(self.modifier_delay)

        for keysym in action.keys:
            code = self.keycode(keysym)
            if not code:
                LOG.warning("キーコード不明: %s", keysym_name(keysym))
                continue
            self._send_key(code, True)
            self.held.append(("key", code, 0))
            mine.append(("key", code, 0))
            time.sleep(0.002)

        if action.wheels or action.buttons:
            self._warp_into(win)

        for btn, repeat in action.wheels:
            for _ in range(repeat):
                self._send_button(btn, True)
                self._send_button(btn, False)
                time.sleep(0.002)

        for btn in action.buttons:
            self._send_button(btn, True)
            self.held.append(("btn", btn, 0))
            mine.append(("btn", btn, 0))
            time.sleep(0.002)

        self.by_control[control] = mine
        return True

    def release(self, control):
        """押下時と同じキー／ボタンを離す。"""
        mine = self.by_control.pop(control, None)
        if not mine:
            return
        for kind, detail, mask in reversed(mine):
            if kind == "btn":
                self._send_button(detail, False)
            else:
                self._send_key(detail, False)
            try:
                self.held.remove((kind, detail, mask))
            except ValueError:
                pass
            time.sleep(0.002)

    def release_all(self):
        for control in list(self.by_control):
            self.release(control)

    def tap(self, action, control):
        if not self.press(action, control):
            return False
        time.sleep(self.key_hold_ms)
        self.release(control)
        return True


# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

def cfg_int(dev, key, default):
    """設定値を int で取り出す。壊れていれば既定値に落とす。"""
    try:
        return int(str(dev.get(key, default)).strip())
    except (TypeError, ValueError):
        LOG.warning("%s の値が不正なので既定値 %s を使います", key, default)
        return default


def cfg_bool(dev, key, default=False):
    val = str(dev.get(key, default)).strip().lower()
    return val in ("1", "true", "yes", "on")


DEFAULT_CONFIG = os.path.expanduser("~/ClipStudio/etc/tourbox.conf")

DEFAULTS = r"""
[device]
port = auto
baud = 115200
vendor = cafe
product =
target = ^clipstudiopaint\.exe$
inject_any = false
modifier_delay = 8
key_hold_ms = 30

[profile:default]
side = ctrl+z
top = ctrl+shift+z
tall = hold:alt
short = hold:space
c1 = bracketleft
c2 = bracketright
dpad_up = up
dpad_down = down
dpad_left = left
dpad_right = right
scroll_up = wheel:1
scroll_down = wheel:-1
scroll_click = none
knob_cw = ctrl+wheel:1
knob_ccw = ctrl+wheel:-1
knob_click = none
tour = Escape
dial_cw = hwheel:1
dial_ccw = hwheel:-1
dial_click = none
"""


def load_profile(path=None):
    cfg = configparser.ConfigParser(inline_comment_prefixes=("#",),
                                    interpolation=None)
    cfg.read_string(DEFAULTS)
    if path and os.path.exists(path):
        cfg.read(path)
    elif path:
        LOG.warning("設定 %s が見つからないので既定値を使います", path)

    dev = dict(cfg["device"]) if "device" in cfg else {}
    mapping = {}
    for section in cfg.sections():
        if not section.startswith("profile:"):
            continue
        for key, value in cfg[section].items():
            if "." in key or key in ("window_class", "window_title", "app_id"):
                continue
            if key not in BUTTON_CODES:
                LOG.warning("不明なコントロール名: %s", key)
                continue
            action = parse_action(value)
            if action is not None:
                mapping[key] = action
    return dev, mapping


# ---------------------------------------------------------------------------
# ドライバ本体
# ---------------------------------------------------------------------------

class Driver:
    def __init__(self, args):
        self.args = args
        self.stop = False
        self.reload = False
        self.dev_cfg, self.mapping = load_profile(args.config)
        self.injector = None
        self.fd = None
        self.port = None
        signal.signal(signal.SIGINT, self._sig_stop)
        signal.signal(signal.SIGTERM, self._sig_stop)
        signal.signal(signal.SIGHUP, self._sig_reload)

    def _sig_stop(self, *_):
        self.stop = True

    def _sig_reload(self, *_):
        self.reload = True

    def _rebuild_injector(self):
        dev = self.dev_cfg
        target = dev.get("target") or "*"
        inject_any = cfg_bool(dev, "inject_any")
        md = cfg_int(dev, "modifier_delay", 8)
        kh = cfg_int(dev, "key_hold_ms", 30)
        self.injector = Injector(target, inject_any, md, kh)
        LOG.info("注入先=%s inject_any=%s modifier_delay=%dms", target, inject_any, md)

    def _log_mapping(self):
        LOG.info("割り当て %d 件", len(self.mapping))
        for k in sorted(self.mapping):
            LOG.info("  %-14s = %s", k, self.mapping[k])

    def connect(self):
        port = find_port(self.dev_cfg.get("vendor", "cafe"),
                         self.dev_cfg.get("product") or None,
                         self.dev_cfg.get("port", "auto"))
        if not port:
            return False
        baud = cfg_int(self.dev_cfg, "baud", 115200)
        try:
            self.fd = open_serial(port, baud)
        except PermissionError:
            LOG.error("%s を開けません（dialout グループに入っていますか？）", port)
            return False
        except OSError as ex:
            LOG.error("%s を開けません: %s", port, ex)
            return False
        self.port = port
        os.write(self.fd, UNLOCK_COMMAND)
        time.sleep(0.3)
        resp = read_bytes(self.fd, 1.0)
        if resp:
            LOG.info("%s 接続 OK（応答 %d バイト）", port, len(resp))
        else:
            LOG.warning("%s は開けたがアンロック応答がありません", port)
        return True

    def disconnect(self):
        if self.injector:
            self.injector.release_all()
        if self.fd is not None:
            try:
                fcntl.ioctl(self.fd, termios.TIOCNXCL)
            except OSError:
                pass
            try:
                os.close(self.fd)
            except OSError:
                pass
        self.fd = None
        self.port = None

    def handle_byte(self, b, scan_only=False):
        info = BYTE_TO_CONTROL.get(b)
        if not info:
            LOG.warning("未知のバイト: %02x", b)
            return
        control, is_press = info
        if scan_only:
            print("%02x  %-14s %s" % (b, control, "PRESS" if is_press else "release"),
                  flush=True)
            return
        action = self.mapping.get(control)
        if action is None:
            return

        if action.hold and control in HOLDABLE:
            if is_press:
                if self.injector.press(action, control):
                    LOG.info("%s PRESS -> %s", control, action)
            else:
                self.injector.release(control)
                LOG.info("%s release", control)
        elif is_press:
            if self.injector.tap(action, control):
                LOG.info("%s tap -> %s", control, action)

    def run_scan(self):
        if not self.connect():
            LOG.error("TourBox が見つかりません")
            return 1
        print("ボタンを押す／ダイヤルを回してください（Ctrl+C で終了）", flush=True)
        try:
            while not self.stop:
                data = read_bytes(self.fd, 0.25)
                if not data:
                    continue
                if len(data) >= RESPONSE_FRAME_MIN_BYTES:
                    print("frame %s" % data.hex(" "), flush=True)
                    continue
                for b in data:
                    self.handle_byte(b, scan_only=True)
        except KeyboardInterrupt:
            pass
        finally:
            self.disconnect()
        return 0

    def run(self):
        self._rebuild_injector()
        self._log_mapping()
        delay = 2.0
        while not self.stop:
            if self.reload:
                self.reload = False
                LOG.info("設定を再読み込みします")
                self.dev_cfg, self.mapping = load_profile(self.args.config)
                self.injector.release_all()
                self._rebuild_injector()
                self._log_mapping()

            if self.fd is None:
                if not self.connect():
                    time.sleep(delay)
                    delay = min(delay * 1.5, 10.0)
                    continue
                delay = 2.0

            try:
                data = read_bytes(self.fd, 0.25)
            except OSError as ex:
                LOG.error("読み取りエラー: %s（再接続）", ex)
                self.disconnect()
                continue
            if not data:
                if self.port and not os.path.exists(self.port):
                    LOG.warning("ポート %s が消えました（再接続します）", self.port)
                    self.disconnect()
                continue

            if len(data) >= RESPONSE_FRAME_MIN_BYTES:
                LOG.debug("応答フレーム %d バイトを破棄", len(data))
                continue

            for b in data:
                self.handle_byte(b)

        self.disconnect()
        LOG.info("停止しました")
        return 0


# ---------------------------------------------------------------------------
# サブコマンド
# ---------------------------------------------------------------------------

def _injector_from_cfg(cfg_path, target=None):
    dev, _ = load_profile(cfg_path)
    target = target or dev.get("target") or "*"
    return Injector(target, cfg_bool(dev, "inject_any"),
                    cfg_int(dev, "modifier_delay", 8),
                    cfg_int(dev, "key_hold_ms", 30))


def run_test(action_text, cfg_path, target=None, focus=None):
    action = parse_action(action_text)
    if action is None:
        print("アクションを解釈できません: %r" % action_text)
        return 1
    inj = _injector_from_cfg(cfg_path, target)
    if focus:
        win = inj.find_window(focus)
        if win is None:
            print("ウィンドウが見つかりません: %r" % focus)
            return 1
        inj.focus_window(win)
    print("action = %s" % action)
    print("対象ウィンドウ = %s" % (inj.target() or "見つからない（対象アプリにフォーカスしてください）"))
    if action.hold:
        if not inj.press(action, "test"):
            return 1
        print("2 秒保持します...")
        time.sleep(2.0)
        inj.release("test")
    else:
        if not inj.tap(action, "test"):
            return 1
    print("送信しました")
    return 0


def run_probe(cfg_path):
    dev, _ = load_profile(cfg_path)
    port = find_port(dev.get("vendor", "cafe"), dev.get("product") or None,
                     dev.get("port", "auto"))
    if not port:
        print("TourBox のシリアルポートが見つかりません")
        return 1
    fd = open_serial(port, cfg_int(dev, "baud", 115200))
    os.write(fd, UNLOCK_COMMAND)
    time.sleep(0.3)
    resp = read_bytes(fd, 1.0)
    print("port     = %s" % port)
    print("unlock   = %s" % UNLOCK_COMMAND.hex(" "))
    print("response = %d bytes: %s" % (len(resp), resp.hex(" ")))
    os.close(fd)
    return 0 if resp else 1


def main():
    ap = argparse.ArgumentParser(description="TourBox Lite Linux driver")
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--scan", action="store_true", help="生イベントを表示")
    ap.add_argument("--probe", action="store_true", help="アンロック応答を確認")
    ap.add_argument("--test", metavar="ACTION", help="注入経路のテスト")
    ap.add_argument("--target", metavar="REGEX",
                    help="テスト時に注入を許可する WM_CLASS（設定を上書き）")
    ap.add_argument("--focus", metavar="SPEC",
                    help="テスト前にこのウィンドウへフォーカスを移す")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)

    if args.probe:
        return run_probe(args.config)
    if args.test:
        return run_test(args.test, args.config, args.target, args.focus)

    drv = Driver(args)
    return drv.run_scan() if args.scan else drv.run()


if __name__ == "__main__":
    sys.exit(main())
