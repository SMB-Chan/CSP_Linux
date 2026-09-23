#!/usr/bin/env python3
"""Forward this Wacom tablet's evdev reports to PSM Wintab and XWayland.

Cursor motion is left to the desktop (libinput). XTest motion is dropped and
XWarpPointer only updates the X pointer, so map.grab defaults to off.

The event device is opened before dropping sudo privileges. All application
launches, socket traffic, X11 operations and logs run as the invoking user.
By default the bridge grabs the pen device exclusively (EVIOCGRAB) so the
desktop's own tablet mapping cannot move the cursor with a different formula
at the same time; [map] grab = off restores shared operation. The kernel
releases the grab automatically when this process exits.
"""
import argparse
import configparser
import ctypes
import fcntl
import glob
import json
import os
from pathlib import Path
import pwd
import select
import signal
import socket
import struct
import subprocess
import time

EVENT = struct.Struct('llHHi')
PRESSURE_MAX = 32767
EVIOCGRAB = 0x40044590  # _IOW('E', 0x90, int): 1 = exclusive, 0 = shared


def scale(value, low, high, extent):
    if high <= low:
        raise ValueError('Invalid input range')
    return max(0, min(extent, round((value-low)*extent/(high-low))))


def ratio(value, low, high):
    if high <= low:
        return 0.0
    return max(0.0, min(1.0, (value-low)/(high-low)))


# Optional tuning, read from ~/ClipStudio/etc/pentab.conf and re-read while
# running (SIGHUP or a changed file). Defaults reproduce the original
# full-area, linear behaviour exactly.
MAP_MODES = ('full', 'aspect', 'area')
ROTATIONS = (0, 90, 180, 270)
SIDE_BITS = dict(none=0, right=1, middle=2)
DEFAULTS = {
    'map': dict(mode='full', rotate='0', area_x='0', area_y='0',
                area_width='0', area_height='0', grab='off'),
    'pressure': dict(gain='1.0', gamma='1.0', input_floor='0.0',
                     input_ceiling='1.0', output_floor='0.0'),
    'pen': dict(side_button='right'),
}


class Settings:
    """Pen tablet tuning: tablet-to-screen mapping and pressure response."""

    def __init__(self, values=None):
        values = values or {}
        merged = {}
        for section, defaults in DEFAULTS.items():
            given = values.get(section, {})
            merged[section] = dict(defaults, **{k: str(v).strip() for k, v in given.items()
                                                if k in defaults})
        self.mode = merged['map']['mode'].lower()
        if self.mode not in MAP_MODES:
            raise ValueError('不明な map.mode: '+merged['map']['mode'])
        self.rotate = int(float(merged['map']['rotate'])) % 360
        if self.rotate not in ROTATIONS:
            raise ValueError('map.rotate は 0 / 90 / 180 / 270 のいずれかにしてください')
        self.area = tuple(int(float(merged['map'][k])) for k in
                          ('area_x', 'area_y', 'area_width', 'area_height'))
        self.grab = merged['map']['grab'].lower()
        if self.grab not in ('on', 'off'):
            raise ValueError('map.grab は on / off のいずれかにしてください')
        self.gain = self.number(merged['pressure']['gain'], 'pressure.gain', 0.05, 8)
        self.gamma = self.number(merged['pressure']['gamma'], 'pressure.gamma', 0.1, 8)
        self.input_floor = self.number(merged['pressure']['input_floor'],
                                       'pressure.input_floor', 0, 0.99)
        self.input_ceiling = self.number(merged['pressure']['input_ceiling'],
                                         'pressure.input_ceiling', 0.01, 1)
        self.output_floor = self.number(merged['pressure']['output_floor'],
                                        'pressure.output_floor', 0, 0.9)
        if self.input_ceiling <= self.input_floor:
            raise ValueError('pressure.input_ceiling は input_floor より大きくしてください')
        self.side_button = merged['pen']['side_button'].lower()
        if self.side_button not in SIDE_BITS:
            raise ValueError('不明な pen.side_button: '+merged['pen']['side_button'])

    @staticmethod
    def number(text, name, low, high):
        value = float(text)
        if not low <= value <= high:
            raise ValueError(f'{name} は {low}〜{high} の範囲にしてください（入力: {text}）')
        return value

    @classmethod
    def read(cls, path):
        parser = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=('#',))
        parser.read(path, encoding='utf-8')
        return cls({section: dict(parser[section]) for section in parser.sections()})

    def rect(self, width, height, aspect):
        """Screen rectangle (x0, y0, x1, y1) the tablet area maps onto."""
        if self.mode == 'area' and self.area[2] > 0 and self.area[3] > 0:
            x0 = max(0, min(self.area[0], width-1))
            y0 = max(0, min(self.area[1], height-1))
            x1 = max(x0, min(x0+self.area[2]-1, width-1))
            y1 = max(y0, min(y0+self.area[3]-1, height-1))
            return x0, y0, x1, y1
        if self.mode == 'aspect' and aspect > 0:
            if width/height > aspect:
                box = int(round(height*aspect)), height
            else:
                box = width, int(round(width/aspect))
            x0 = (width-box[0])//2
            y0 = (height-box[1])//2
            return x0, y0, x0+box[0]-1, y0+box[1]-1
        return 0, 0, width-1, height-1

    def point(self, raw_x, raw_y, ax, ay, width, height):
        """Map a raw tablet position to screen pixels and PSM/Wintab units."""
        u = ratio(raw_x, ax[1], ax[2])
        v = ratio(raw_y, ay[1], ay[2])
        if self.rotate == 90:
            u, v = 1-v, u
        elif self.rotate == 180:
            u, v = 1-u, 1-v
        elif self.rotate == 270:
            u, v = v, 1-u
        aspect = (ax[2]-ax[1])/(ay[2]-ay[1]) if ay[2] > ay[1] else 0
        x0, y0, x1, y1 = self.rect(width, height, aspect)
        return (round(x0+u*(x1-x0)), round(y0+v*(y1-y0)),
                round((x0+u*(x1-x0))*1000), round((y0+v*(y1-y0))*1000))

    def pressure(self, raw, low, high):
        """Apply the configured sensitivity curve to a raw pressure sample."""
        t = ratio(raw, low, high)
        t = max(0.0, min(1.0, (t-self.input_floor)/(self.input_ceiling-self.input_floor)))
        if self.gamma != 1.0:
            t = t**self.gamma
        t = max(0.0, min(1.0, t*self.gain))
        return round((self.output_floor+t*(1-self.output_floor))*PRESSURE_MAX)

    def describe(self):
        target = f' 領域(x,y,幅,高)={self.area}' if self.mode == 'area' else ''
        return [f'対応マップ: {self.mode}{target} 回転: {self.rotate}° 排他占有: {self.grab}',
                (f'筆圧: 感度={self.gain:g} カーブ={self.gamma:g} '
                 f'反応開始={self.input_floor:g} 最大入力={self.input_ceiling:g} '
                 f'最小出力={self.output_floor:g}'),
                f'サイドスイッチ: {self.side_button}']

    def summary(self):
        return dict(mode=self.mode, rotate=self.rotate, area=list(self.area),
                    grab=self.grab,
                    gain=self.gain, gamma=self.gamma, input_floor=self.input_floor,
                    input_ceiling=self.input_ceiling, output_floor=self.output_floor,
                    side_button=self.side_button)


def read_settings(path):
    mtime = path.stat().st_mtime if path.exists() else 0.0
    return Settings.read(path), mtime


def packet(x, y, pressure, buttons):
    return dict(type='TabletEvent', status=0, buttons=buttons, x=x, y=y,
                z=0, normal_pressure=pressure, tangential_pressure=0)


def send(sock, value):
    data = json.dumps(value, separators=(',', ':')).encode()
    sock.sendall(struct.pack('!I', len(data)) + data)


def receive(sock, count):
    result = b''
    while len(result) < count:
        data = sock.recv(count-len(result))
        if not data:
            raise ConnectionError('PSM disconnected')
        result += data
    return result


def connect():
    sock = socket.create_connection(('127.0.0.1', 40302), timeout=.5)
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        send(sock, dict(type='Hi', name='Wacom evdev pressure bridge 1.0'))
        size = struct.unpack('!I', receive(sock, 4))[0]
        if size > 4096:
            raise ValueError('Invalid PSM handshake length')
        response = json.loads(receive(sock, size))
        if response != dict(type='Hi', compatible=2):
            raise ValueError('Incompatible PSM version: '+repr(response))
        return sock
    except Exception:
        sock.close()
        raise


def find_tablet():
    for event in glob.glob('/sys/class/input/event*'):
        path = Path(event)/'device'
        try:
            if (path/'id/vendor').read_text().strip() != '0531':
                continue
            if (path/'id/product').read_text().strip() != '0102':
                continue
            bits = int((path/'capabilities/abs').read_text().replace(' ', ''), 16)
            if bits & (1 << 24):
                return '/dev/input/'+Path(event).name
        except OSError:
            continue
    raise RuntimeError('Wacom One USB pen device not found')


def axis(source, code):
    return struct.unpack('6i', fcntl.ioctl(source, 0x80184540+code, bytes(24)))


class Pointer:
    def __init__(self):
        self.x = ctypes.CDLL('libX11.so.6')
        self.t = ctypes.CDLL('libXtst.so.6')
        self.x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x.XOpenDisplay.restype = ctypes.c_void_p
        self.x.XDefaultScreen.argtypes = [ctypes.c_void_p]
        self.x.XDefaultScreen.restype = ctypes.c_int
        self.x.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.x.XDisplayHeight.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.x.XFlush.argtypes = [ctypes.c_void_p]
        self.x.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self.x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        self.x.XDefaultRootWindow.restype = ctypes.c_ulong
        self.x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        self.x.XInternAtom.restype = ctypes.c_ulong
        self.x.XGetWindowProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
            ctypes.c_long, ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_void_p)]
        self.x.XFree.argtypes = [ctypes.c_void_p]
        self.t.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
        self.t.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        # XWayland/mutter drops XTest pointer motion; XWarpPointer updates the X
        # pointer only — Wine/GNOME's cursor follows real libinput events.
        self.x.XWarpPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_int, ctypes.c_int]
        self.x.XWarpPointer.restype = ctypes.c_int
        self.x.XQueryPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_uint)]
        self.x.XQueryPointer.restype = ctypes.c_int
        self.x.XGetGeometry.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint)]
        self.x.XGetGeometry.restype = ctypes.c_int
        self.display = self.x.XOpenDisplay(None)
        if not self.display:
            raise RuntimeError('Cannot connect to XWayland')
        self.screen = self.x.XDefaultScreen(self.display)
        self.width = self.x.XDisplayWidth(self.display, self.screen)
        self.height = self.x.XDisplayHeight(self.display, self.screen)
        self.pressed = False
        self.root = self.x.XDefaultRootWindow(self.display)
        self.active_atom = self.x.XInternAtom(self.display, b'_NET_ACTIVE_WINDOW', 0)
        self.class_atom = self.x.XInternAtom(self.display, b'WM_CLASS', 0)
        self.list_atom = self.x.XInternAtom(self.display, b'_NET_CLIENT_LIST', 0)
        self.active_until = 0
        self.active_cached = False

    def property(self, window, atom):
        kind, fmt = ctypes.c_ulong(), ctypes.c_int()
        count, rest = ctypes.c_ulong(), ctypes.c_ulong()
        data = ctypes.c_void_p()
        result = self.x.XGetWindowProperty(self.display, window, atom, 0, 256, 0, 0,
            ctypes.byref(kind), ctypes.byref(fmt), ctypes.byref(count),
            ctypes.byref(rest), ctypes.byref(data))
        try:
            if result or not data or not count.value:
                return None
            if fmt.value == 32:
                ptr = ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))
                items = [ptr[i] for i in range(count.value)]
                return items[0] if len(items) == 1 else items
            if fmt.value == 8:
                return ctypes.string_at(data, count.value)
        finally:
            if data:
                self.x.XFree(data)

    def is_csp(self, window):
        if not window:
            return False
        cls = self.property(window, self.class_atom)
        return isinstance(cls, bytes) and b'clipstudiopaint.exe' in cls.lower()

    def geometry(self, window):
        root = ctypes.c_ulong()
        x, y = ctypes.c_int(), ctypes.c_int()
        w, h = ctypes.c_uint(), ctypes.c_uint()
        bw, depth = ctypes.c_uint(), ctypes.c_uint()
        if self.x.XGetGeometry(self.display, window, ctypes.byref(root),
                               ctypes.byref(x), ctypes.byref(y), ctypes.byref(w),
                               ctypes.byref(h), ctypes.byref(bw), ctypes.byref(depth)):
            return x.value, y.value, w.value, h.value
        return None

    def pointer_xy(self):
        rw, ch = ctypes.c_ulong(), ctypes.c_ulong()
        rx, ry = ctypes.c_int(), ctypes.c_int()
        wx, wy = ctypes.c_int(), ctypes.c_int()
        mask = ctypes.c_uint()
        if not self.x.XQueryPointer(self.display, self.root, ctypes.byref(rw),
                                    ctypes.byref(ch), ctypes.byref(rx), ctypes.byref(ry),
                                    ctypes.byref(wx), ctypes.byref(wy), ctypes.byref(mask)):
            return None
        return rx.value, ry.value

    def csp_windows(self):
        clients = self.property(self.root, self.list_atom) or []
        if not isinstance(clients, (list, tuple)):
            return []
        return [wid for wid in clients if self.is_csp(wid)]

    def pointer_in_csp(self):
        pos = self.pointer_xy()
        if not pos:
            return False
        px, py = pos
        for wid in self.csp_windows():
            g = self.geometry(wid)
            if g and g[0] <= px < g[0] + max(g[2], 1) and g[1] <= py < g[1] + max(g[3], 1):
                return True
        return False

    def csp_active(self):
        now = time.monotonic()
        if now < self.active_until:
            return self.active_cached
        self.active_until = now + .15
        active = self.property(self.root, self.active_atom)
        if self.is_csp(active):
            self.active_cached = True
            return True
        # GNOME/Wine は _NET_ACTIVE_WINDOW に 1x1 の受け皿窓を置くことがある。
        # 本物の別アプリが前面なら外す。空・小窓なら座標で CSP 上かを見る。
        if active:
            cls = self.property(active, self.class_atom)
            g = self.geometry(active)
            if cls and g and g[2] > 2 and g[3] > 2 and not self.is_csp(active):
                self.active_cached = False
                return False
        self.active_cached = self.pointer_in_csp()
        return self.active_cached

    def release(self):
        if self.pressed:
            self.t.XTestFakeButtonEvent(self.display, 1, 0, 0)
            self.x.XFlush(self.display)
            self.pressed = False

    def update(self, x, y, pressed, move=True):
        # move=False: デスクトップ側がカーソル位置を決める（grab=off）。
        # move=True:  排他占有中で、対応マップどおりに動かす。
        if move:
            self.x.XWarpPointer(self.display, 0, self.root, 0, 0, 0, 0, int(x), int(y))
        if pressed != self.pressed:
            self.t.XTestFakeButtonEvent(self.display, 1, int(pressed), 0)
            self.pressed = pressed
        self.x.XFlush(self.display)

    def close(self):
        self.release()
        self.x.XCloseDisplay(self.display)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--launch', action='store_true', help='Launch CSP after dropping sudo privileges')
    ap.add_argument('--seconds', type=int, default=0, help='Optional test duration; 0 runs until stopped')
    ap.add_argument('--watch-pid', type=int, help='Stop when this CSP launcher process exits')
    ap.add_argument('--config', help='Pen settings file (default: ~/ClipStudio/etc/pentab.conf)')
    ap.add_argument('--check', action='store_true',
                    help='Validate the pen settings, print the response table and exit')
    args = ap.parse_args()
    settings_path = Path(args.config) if args.config else Path.home()/'ClipStudio/etc/pentab.conf'
    if args.check:
        try:
            settings = Settings.read(settings_path)
        except Exception as exc:
            print(f'{settings_path}: 設定を読み込めません: {exc}')
            return 2
        print(f'{settings_path}: 設定 OK')
        for line in settings.describe():
            print('  '+line)
        print('  筆圧応答（ペン入力 → CSP に届く値 /32767）:')
        for percent in (0, 10, 25, 50, 75, 90, 100):
            print(f'    {percent:3d}% -> {settings.pressure(percent/100, 0, 1):5d}')
        return 0
    device = find_tablet()
    try:
        source = open(device, 'rb', buffering=0)
    except PermissionError:
        raise SystemExit('Run: sudo python3 ~/ClipStudio/bin/wacom-pressure.py --launch')
    ax, ay, pressure_axis = axis(source, 0), axis(source, 1), axis(source, 24)
    if os.getuid() == 0:
        if 'SUDO_UID' not in os.environ:
            raise SystemExit('Invoke through sudo from your desktop account')
        uid, gid = int(os.environ['SUDO_UID']), int(os.environ['SUDO_GID'])
        user = pwd.getpwuid(uid)
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)
        os.environ.update(HOME=user.pw_dir, USER=user.pw_name, LOGNAME=user.pw_name)
        os.environ.setdefault('XDG_RUNTIME_DIR', '/run/user/'+str(uid))
        os.environ.setdefault('DBUS_SESSION_BUS_ADDRESS', 'unix:path=/run/user/'+str(uid)+'/bus')
    base = Path.home()/'ClipStudio'
    logdir = base/'logs'
    logdir.mkdir(exist_ok=True)
    lock = (logdir/'wacom-pressure.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('The pressure bridge is already running')
    pointer = Pointer()
    config = json.loads((base/'pressure/psm.json').read_text())['preset']
    if (pointer.width, pointer.height) != (config['sys_ext_x'], config['sys_ext_y']):
        pointer.close()
        raise SystemExit('Display geometry changed; update pressure/psm.json before using the bridge')
    statusfile = logdir/'wacom-pressure-status.json'
    status_tmp = statusfile.with_name(statusfile.name+'.tmp')
    log = (logdir/'wacom-pressure.log').open('a', buffering=1)
    def report(message):
        print(message, flush=True)
        log.write(time.strftime('%Y-%m-%d %H:%M:%S ')+message+'\n')
    def stop(signum, frame):
        raise KeyboardInterrupt
    pending = [False]

    def reload(signum, frame):
        pending[0] = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGHUP, reload)
    report(f'Reading {device} as uid={os.getuid()}; pressure={pressure_axis[1]}..{pressure_axis[2]}')
    try:
        settings, settings_mtime = read_settings(settings_path)
    except Exception as exc:
        settings, settings_mtime = Settings(), 0.0
        report(f'ペン設定を読み込めません（{exc}）; 既定値で動作します')
    settings_at = 0.0
    for line in settings.describe():
        report(line)
    grabbed = False

    def apply_grab():
        # 排他占有するとデスクトップ側のカーソルが止まる。このホストでは
        # XWarpPointer は X 座標だけ動き Wine/GNOME の実カーソルには届かない
        # ため、通常は off のまま使う。プロセス終了でカーネルが自動解放する。
        nonlocal grabbed
        want = settings.grab == 'on'
        if want and not grabbed:
            try:
                fcntl.ioctl(source, EVIOCGRAB, 1)
                grabbed = True
                report('ペンデバイスを排他占有しました（デスクトップ側のカーソル移動を停止）')
            except OSError as exc:
                report(f'排他占有に失敗（{exc.strerror or exc}）; 共有のままで動作します')
        elif grabbed and not want:
            try:
                fcntl.ioctl(source, EVIOCGRAB, 0)
            except OSError:
                pass
            grabbed = False
            report('ペンデバイスの排他占有を解除しました')

    apply_grab()
    child = None
    childlog = None
    if args.launch:
        if subprocess.run(['pgrep', '-x', 'CLIPStudioPaint'], stdout=subprocess.DEVNULL).returncode == 0:
            report('CSP is already running; connecting to it')
        else:
            childlog = (logdir/'pressure-csp-launch.log').open('w')
            child = subprocess.Popen([str(base/'bin/csp-launch.sh')], stdout=childlog, stderr=subprocess.STDOUT)
            report('Launched CSP as the desktop user')
    raw_x, raw_y, raw_p = ax[0], ay[0], pressure_axis[0]
    keys = fcntl.ioctl(source, 0x80604518, bytes(96))  # EVIOCGKEY(96)
    def key(code): return bool(keys[code//8] & (1 << (code % 8)))
    prox = key(320) or key(321)
    tip, side = key(330), key(331)
    dirty = False
    sock = None
    sent_prox = None
    retry_at = 0
    began = time.monotonic()
    status_at = 0
    total, maximum = 0, 0
    last = packet(0, 0, 0, 0)
    px = py = None
    try:
        while not args.seconds or time.monotonic()-began < args.seconds:
            now = time.monotonic()
            if args.watch_pid and not Path('/proc/'+str(args.watch_pid)).exists():
                report('CSP session ended; stopping pressure bridge')
                break
            if child is not None and child.poll() is not None:
                report('CSP exited; stopping pressure bridge')
                break
            if pending[0] or now >= settings_at:
                forced, pending[0] = pending[0], False
                settings_at = now+1
                try:
                    mtime = settings_path.stat().st_mtime if settings_path.exists() else 0.0
                except OSError:
                    mtime = settings_mtime
                if forced or mtime != settings_mtime:
                    try:
                        settings, settings_mtime = Settings.read(settings_path), mtime
                        report('ペン設定を再読み込み: '+' / '.join(settings.describe()))
                        apply_grab()
                    except Exception as exc:
                        settings_mtime = mtime  # 同じ壊れた設定は毎秒報告しない
                        report(f'ペン設定の再読み込みに失敗（{exc}）; 直前の設定を維持します')
            if sock is None and now >= retry_at:
                retry_at = now+2
                try:
                    sock = connect()
                    sent_prox = None
                    report('PSM connected: pressure forwarding is ready')
                except (OSError, ValueError):
                    sock = None
            active = pointer.csp_active()
            if not active:
                pointer.release()
                if sock is not None and sent_prox is True:
                    try:
                        send(sock, packet(last['x'], last['y'], 0, 0))
                        send(sock, dict(type='Proximity', value=False))
                        sent_prox = False
                    except OSError:
                        sock.close()
                        sock = None
            if now >= status_at:
                # 設定画面の実機メーターがここを読むため、ペンイベント中は
                # 高頻度（〜20 Hz）で原子的に書き換える。
                status_at = now+.05
                status_tmp.write_text(json.dumps(dict(pid=os.getpid(), connected=sock is not None,
                    device=device, active=active, grabbed=grabbed, packets=total,
                    max_pressure=maximum, last_pressure=last['normal_pressure'],
                    prox=prox, tip=tip, side=side,
                    raw_pressure=raw_p if (prox and tip) else 0,
                    pointer_x=px, pointer_y=py,
                    settings=settings.summary(), config=str(settings_path),
                    updated=time.time()))+'\n')
                os.replace(status_tmp, statusfile)
            ready, _, _ = select.select([source], [], [], .2)
            if not ready:
                continue
            while True:
                raw = source.read(EVENT.size)
                if len(raw) != EVENT.size:
                    raise RuntimeError('Tablet disconnected')
                _, _, kind, code, value = EVENT.unpack(raw)
                if (kind, code) == (0, 3):
                    # SYN_DROPPED: キューが溢れた。クラッシュさせず軸とキーを読み直す。
                    raw_x, raw_y, raw_p = axis(source, 0)[0], axis(source, 1)[0], axis(source, 24)[0]
                    keys = fcntl.ioctl(source, 0x80604518, bytes(96))
                    prox = key(320) or key(321)
                    tip, side = key(330), key(331)
                    dirty = True
                    report('タブレットイベントを取りこぼしたため状態を再同期しました')
                elif kind == 3 and code in (0, 1, 24):
                    if code == 0: raw_x = value
                    elif code == 1: raw_y = value
                    else: raw_p = value
                    dirty = True
                elif kind == 1 and code in (320, 321, 330, 331):
                    if code in (320, 321): prox = bool(value)
                    elif code == 330: tip = bool(value)
                    elif code == 331: side = bool(value)
                    dirty = True
                if (kind, code) == (0, 0) and dirty:
                    dirty = False
                    # Mapping and pressure response come from pentab.conf; its defaults
                    # keep the working full-area mapping with subpixel Wintab coordinates.
                    px, py, wx, wy = settings.point(raw_x, raw_y, ax, ay, pointer.width, pointer.height)
                    p = settings.pressure(raw_p, pressure_axis[1], pressure_axis[2]) if prox and tip else 0
                    down = tip and prox and active
                    side_bit = SIDE_BITS[settings.side_button] if side and prox and active else 0
                    last = packet(wx, wy, p, int(down) | side_bit)
                    if active and sock is not None:
                        try:
                            if prox and sent_prox is not True:
                                send(sock, dict(type='Proximity', value=True))
                                sent_prox = True
                            send(sock, last)
                            if not prox and sent_prox is not False:
                                send(sock, dict(type='Proximity', value=False))
                                sent_prox = False
                            total += 1
                            maximum = max(maximum, p)
                        except OSError:
                            sock.close()
                            sock = None
                            report('PSM disconnected; waiting for CSP')
                    # 排他占有中はデスクトップがカーソルを動かさないため、CSP 外でも
                    # 位置をミラーする。ボタンと Wintab 送信は CSP 前面のときだけ。
                    if (active or grabbed) and (prox or pointer.pressed):
                        pointer.update(px, py, down, move=grabbed)
                ready, _, _ = select.select([source], [], [], 0)
                if not ready:
                    break
    except KeyboardInterrupt:
        report('Pressure bridge stopped')
    finally:
        if grabbed:
            try:
                fcntl.ioctl(source, EVIOCGRAB, 0)
            except OSError:
                pass
            grabbed = False
        if sock is not None:
            try:
                send(sock, packet(last['x'], last['y'], 0, 0))
                send(sock, dict(type='Proximity', value=False))
            except OSError:
                pass
            sock.close()
        pointer.close()
        source.close()
        status_tmp.write_text(json.dumps(dict(pid=os.getpid(), connected=False, stopped=True,
            packets=total, max_pressure=maximum, updated=time.time()))+'\n')
        os.replace(status_tmp, statusfile)
        report(f'Finished: {total} pressure packets, maximum={maximum}/{PRESSURE_MAX}')
        log.close()
        if childlog is not None:
            childlog.close()
        # CSP が終了すると SetContextKindNextBoot が TabletPC へ戻る。次回起動用に
        # Wintab へ書き直す（CSP 未起動時のみ csp-tablet-mode.sh が変更する）。
        try:
            subprocess.run([str(base/'bin/csp-tablet-mode.sh'), 'wintab'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except Exception:
            pass


if __name__ == '__main__':
    main()
