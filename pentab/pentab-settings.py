#!/usr/bin/python3
"""ペンタブレット（Wacom One M）の設定画面 — 感度・対応マップ・サイドスイッチ。

設定は ~/ClipStudio/etc/pentab.conf に保存され、動作中の転送プログラム
(wacom-pressure.py) が 1 秒以内に読み直します。CLIP STUDIO PAINT 本体の
ファイルは読み書きしません。
"""
import configparser
import datetime
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import time
import traceback
import warnings
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, GLib

# GTK 4.22 は ComboBoxText.append と set/get_active_id を非推奨と警告するだけなので抑止する
warnings.filterwarnings('ignore', category=DeprecationWarning,
                        message=r'Gtk\.(ComboBoxText\.append|ComboBox\.(set|get)_active_id) is deprecated')

BASE = Path.home()/'ClipStudio'
CONF = BASE/'etc/pentab.conf'
WRAPPER = BASE/'bin/pentab.sh'
BRIDGE = BASE/'bin/wacom-pressure.py'
STATUS = BASE/'logs/wacom-pressure-status.json'
EVENT = struct.Struct('llHHi')

spec = importlib.util.spec_from_file_location('bridge', BRIDGE)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

MODES = [('full', '画面全体'),
         ('aspect', 'アスペクト比を維持（描いた円が円になる）'),
         ('area', '画面の一部（領域を指定）')]
ROTATIONS = [('0', '回転なし'), ('90', '90°'), ('180', '180°'), ('270', '270°')]
SIDES = [('right', '右クリック（既定）'), ('middle', '中クリック'), ('none', '何もしない')]
PRESETS = [('standard', '標準（線形）', 1.0, 1.0),
           ('soft', 'やわらかい：弱い力から濃く', 1.15, 0.7),
           ('firm', 'かため：強く押して濃く', 0.9, 1.5),
           ('custom', 'カスタム（下のスライダーで調整）', None, None)]
SLIDERS = [('gain', '感度（筆圧の強さ）', 0.2, 3.0, 0.05),
           ('gamma', 'カーブ（1 未満でやわらかい）', 0.3, 3.0, 0.05),
           ('input_floor', '反応開始（これ以下の筆圧は無視）', 0.0, 0.3, 0.01),
           ('input_ceiling', '最大入力（ここで筆圧いっぱい）', 0.4, 1.0, 0.01),
           ('output_floor', '最小出力（線の始まりのかすれ防止）', 0.0, 0.3, 0.01)]
QUICK = [('右半分', lambda w, h: (w//2, 0, w-w//2, h)),
         ('左半分', lambda w, h: (0, 0, w//2, h)),
         ('中央 2/3', lambda w, h: (w//6, h//6, w-w//3, h-h//3)),
         ('上半分', lambda w, h: (0, 0, w, h//2))]


def read_conf():
    parser = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=('#',))
    parser.read(CONF, encoding='utf-8')
    return {section: dict(parser[section]) for section in parser.sections()}


def updated_config(original, values):
    """行内の日本語コメントを残したまま、値だけ差し替えた設定テキストを作る。"""
    result, section, written = [], None, set()
    for line in original.splitlines():
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            if section in values:
                result += [f'{k} = {v}' for k, v in values[section].items()
                           if (section, k) not in written]
            section = stripped[1:-1]
        elif section in values:
            match = re.match(r'^([A-Za-z_]\w*)\s*=(.*)$', line)
            if match and match.group(1) in values[section]:
                key, tail = match.group(1), match.group(2)
                comment = tail.split('#', 1)[1].strip() if '#' in tail else ''
                line = f'{key} = {values[section][key]}' + (f'  # {comment}' if comment else '')
                written.add((section, key))
        result.append(line)
    if section in values:
        result += [f'{k} = {v}' for k, v in values[section].items()
                   if (section, k) not in written]
    return '\n'.join(result)+'\n'


class PenSettings(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='local.clipstudio.PenTabletSettings')
        self.raw = 0
        self.tip = False
        self.prox = False
        self.fd = None
        self.pmin, self.pmax = 0, 4095
        self.last_pen = None

    # ---------- 画面 ----------
    def do_activate(self):
        if self.get_active_window():
            self.get_active_window().present()
            return
        try:
            self.build()
        except Exception:
            traceback.print_exc()
            self.quit()

    def build(self):
        win = Gtk.ApplicationWindow(application=self, title='ペンタブレット設定 — CSP')
        win.set_default_size(880, 1000)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(box, 'set_margin_'+side)(18)
        win.set_child(box)
        title = Gtk.Label(label='Wacom One M • CLIP STUDIO PAINT', xalign=0)
        title.add_css_class('title-2')
        box.append(title)
        self.info = Gtk.Label(xalign=0, wrap=True)
        self.info.add_css_class('dim-label')
        box.append(self.info)
        self.scroll = Gtk.ScrolledWindow(vexpand=True)
        box.append(self.scroll)
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.scroll.set_child(column)
        column.append(self.frame('対応マップ（タブレット → 画面）', self.build_map()))
        column.append(self.frame('筆圧の感度とカーブ', self.build_pressure()))
        column.append(self.frame('ペンのボタン', self.build_pen()))
        column.append(self.frame('実機テスト（ペンに触れて確認）', self.build_test()))

        self.status = Gtk.Label(xalign=0, wrap=True)
        box.append(self.status)
        row = Gtk.Box(spacing=10)
        box.append(row)
        save = Gtk.Button(label='保存して適用')
        save.add_css_class('suggested-action')
        save.connect('clicked', self.save)
        row.append(save)
        revert = Gtk.Button(label='保存前の値に戻す')
        revert.connect('clicked', lambda *_: self.load())
        row.append(revert)
        default = Gtk.Button(label='既定（導入時の描き味）')
        default.connect('clicked', self.reset)
        row.append(default)
        reload = Gtk.Button(label='転送プログラムに読み直させる')
        reload.connect('clicked', lambda *_: self.command('--reload'))
        row.append(reload)

        self.load()
        self.info.set_text(self.info.get_text()+' ／ タブレット: '+self.open_tablet())
        self.refresh()
        GLib.timeout_add_seconds(2, self.refresh)
        GLib.timeout_add(50, self.poll_status)
        win.present()

    def frame(self, label, child):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        heading = Gtk.Label(label=label, xalign=0)
        heading.add_css_class('heading')
        box.append(heading)
        box.append(child)
        return box

    @staticmethod
    def combo(items):
        combo = Gtk.ComboBoxText()
        for value, label in items:
            combo.append(value, label)
        return combo

    def build_map(self):
        grid = Gtk.Grid(column_spacing=16, row_spacing=8)
        self.mode = self.combo(MODES)
        self.mode.connect('changed', self.map_changed)
        self.rotate = self.combo(ROTATIONS)
        self.rotate.connect('changed', self.redraw_preview)
        grid.attach(Gtk.Label(label='範囲', xalign=0), 0, 0, 1, 1)
        grid.attach(self.mode, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label='タブレットの回転', xalign=0), 0, 1, 1, 1)
        grid.attach(self.rotate, 1, 1, 1, 1)
        self.area = {}
        labels = [('area_x', '領域の左端 X'), ('area_y', '領域の上端 Y'),
                  ('area_width', '領域の幅'), ('area_height', '領域の高さ')]
        for index, (key, label) in enumerate(labels):
            spin = Gtk.SpinButton.new_with_range(0, 8192, 10)
            spin.set_hexpand(True)
            spin.connect('value-changed', self.redraw_preview)
            grid.attach(Gtk.Label(label=label, xalign=0), 0, 2+index, 1, 1)
            grid.attach(spin, 1, 2+index, 1, 1)
            self.area[key] = spin
        quick = Gtk.Box(spacing=6)
        for label, rect in QUICK:
            button = Gtk.Button(label=label)
            button.connect('clicked', self.quick_area, rect)
            quick.append(button)
        grid.attach(Gtk.Label(label='よく使う領域', xalign=0), 0, 6, 1, 1)
        grid.attach(quick, 1, 6, 1, 1)
        hint = Gtk.Label(xalign=0, wrap=True,
                         label='「アスペクト比を維持」ではタブレットの 216×135 mm と画面 16:9 の形の差が'
                               '左右の余りになり、その代わり描いた円が円になります。')
        hint.add_css_class('dim-label')
        grid.attach(hint, 0, 7, 2, 1)
        self.grab = Gtk.CheckButton(label='ペンデバイスを排他占有する（デスクトップ側のカーソル移動を止める）')
        self.grab.set_active(True)
        self.grab.set_tooltip_text(
            'オンではこのプログラムの式だけがカーソルを動かします。'
            'オフではデスクトップ側のペン対応マップも同時にカーソルを動かすため、'
            '両者の式が違うと（アスペクト比維持のときなど）カーソルが2個に分裂して見えます。')
        grid.attach(self.grab, 0, 8, 2, 1)
        self.preview = Gtk.DrawingArea()
        self.preview.set_draw_func(self.draw_preview)
        self.preview.set_size_request(420, 250)
        self.preview.set_halign(Gtk.Align.CENTER)
        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        holder.append(grid)
        holder.append(self.preview)
        return holder

    def build_pressure(self):
        grid = Gtk.Grid(column_spacing=16, row_spacing=6)
        self.preset = self.combo([(key, label) for key, label, _, _ in PRESETS])
        self.preset.connect('changed', self.preset_changed)
        grid.attach(Gtk.Label(label='プリセット', xalign=0), 0, 0, 1, 1)
        grid.attach(self.preset, 1, 0, 1, 1)
        self.scales, self.readouts = {}, {}
        for row, (key, label, low, high, step) in enumerate(SLIDERS, start=1):
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, low, high, step)
            scale.set_hexpand(True)
            scale.set_draw_value(False)
            scale.connect('value-changed', self.slider_changed)
            readout = Gtk.Label(label='', xalign=1, width_chars=6)
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
            grid.attach(scale, 1, row, 1, 1)
            grid.attach(readout, 2, row, 1, 1)
            self.scales[key], self.readouts[key] = scale, readout
        self.curve = Gtk.DrawingArea()
        self.curve.set_draw_func(self.draw_curve)
        self.curve.set_size_request(240, 240)
        self.curve.set_valign(Gtk.Align.START)
        holder = Gtk.Box(spacing=16)
        grid.set_hexpand(True)
        holder.append(grid)
        holder.append(self.curve)
        return holder

    def build_pen(self):
        grid = Gtk.Grid(column_spacing=16, row_spacing=6)
        self.side = self.combo(SIDES)
        grid.attach(Gtk.Label(label='サイドスイッチ（ペン軸のボタン）', xalign=0), 0, 0, 1, 1)
        grid.attach(self.side, 1, 0, 1, 1)
        hint = Gtk.Label(xalign=0, wrap=True,
                         label='ここで決まるのはペン入力として送るボタン番号です。'
                               'そのボタンに CSP の機能を割り当てるには、CSP 側の「環境設定 → ショートカット」'
                               'でマウスのボタンを設定してください。ペン先は常に左クリックです。')
        hint.add_css_class('dim-label')
        grid.attach(hint, 0, 1, 2, 1)
        return grid

    def build_test(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.meter = Gtk.LevelBar(min_value=0, max_value=1)
        self.meter.set_size_request(-1, 18)
        box.append(self.meter)
        self.test_label = Gtk.Label(xalign=0, wrap=True)
        box.append(self.test_label)
        return box

    # ---------- 値 ----------
    def values(self):
        return {'map': {'mode': self.mode.get_active_id() or 'full',
                        'rotate': self.rotate.get_active_id() or '0',
                        'grab': 'on' if self.grab.get_active() else 'off',
                        **{key: str(int(spin.get_value())) for key, spin in self.area.items()}},
                'pressure': {key: f'{scale.get_value():g}' for key, scale in self.scales.items()},
                'pen': {'side_button': self.side.get_active_id() or 'right'}}

    def current(self):
        return bridge.Settings(self.values())

    def load(self):
        conf = read_conf()
        mapping, pressure = conf.get('map', {}), conf.get('pressure', {})
        self.mode.set_active_id(mapping.get('mode', 'full'))
        self.rotate.set_active_id(str(int(float(mapping.get('rotate', '0')))))
        self.grab.set_active(str(mapping.get('grab', 'on')).strip().lower() != 'off')
        for key, spin in self.area.items():
            spin.set_value(float(mapping.get(key, '0')))
        for key, scale in self.scales.items():
            scale.set_value(float(pressure.get(key, bridge.DEFAULTS['pressure'][key])))
        self.side.set_active_id(conf.get('pen', {}).get('side_button', 'right'))
        self.sync_preset()
        self.map_changed()
        self.status.set_text(f'{CONF} の内容を表示しています。')

    def reset(self, *_):
        self.mode.set_active_id('full')
        self.rotate.set_active_id('0')
        self.grab.set_active(True)
        for spin in self.area.values():
            spin.set_value(0)
        for key, scale in self.scales.items():
            scale.set_value(float(bridge.DEFAULTS['pressure'][key]))
        self.side.set_active_id('right')
        self.sync_preset()
        self.map_changed()
        self.status.set_text('既定値を表示しています。「保存して適用」を押すと反映されます。')

    def preset_changed(self, *_):
        active = self.preset.get_active_id()
        for key, _, gain, gamma in PRESETS:
            if key == active and gain is not None:
                self.scales['gain'].set_value(gain)
                self.scales['gamma'].set_value(gamma)
        self.redraw()

    def sync_preset(self):
        gain, gamma = self.scales['gain'].get_value(), self.scales['gamma'].get_value()
        chosen = 'custom'
        for key, _, preset_gain, preset_gamma in PRESETS:
            if preset_gain is not None and abs(gain-preset_gain) < 1e-6 and abs(gamma-preset_gamma) < 1e-6:
                chosen = key
                break
        self.preset.handler_block_by_func(self.preset_changed)
        self.preset.set_active_id(chosen)
        self.preset.handler_unblock_by_func(self.preset_changed)

    def slider_changed(self, *_):
        self.sync_preset()
        self.redraw()

    def map_changed(self, *_):
        area = self.mode.get_active_id() == 'area'
        for spin in self.area.values():
            spin.set_sensitive(area)
        self.redraw_preview()

    def quick_area(self, _button, rect):
        width, height = self.screen_size()
        self.mode.set_active_id('area')
        for key, value in zip(('area_x', 'area_y', 'area_width', 'area_height'), rect(width, height)):
            self.area[key].set_value(value)
        self.map_changed()

    def redraw(self):
        for key, scale in self.scales.items():
            self.readouts[key].set_label(f'{scale.get_value():.2f}')
        self.curve.queue_draw()

    def redraw_preview(self, *_):
        self.redraw()
        self.preview.queue_draw()

    # ---------- 描画 ----------
    @staticmethod
    def screen_size():
        display = Gdk.Display.get_default()
        if display:
            monitors = display.get_monitors()
            if monitors.get_n_items():
                geometry = monitors.get_item(0).get_geometry()
                return geometry.width, geometry.height
        return 1920, 1080

    def draw_preview(self, _area, cr, width, height):
        screen_w, screen_h = self.screen_size()
        pad = 10
        factor = min((width-2*pad)/screen_w, (height-2*pad)/screen_h)
        box_w, box_h = screen_w*factor, screen_h*factor
        left, top = (width-box_w)/2, (height-box_h)/2
        cr.set_source_rgb(.25, .25, .28)
        cr.rectangle(left, top, box_w, box_h)
        cr.fill()
        try:
            settings = self.current()
        except ValueError:
            return
        x0, y0, x1, y1 = settings.rect(screen_w, screen_h, 21600/13500)
        cr.set_source_rgb(.35, .65, .95)
        cr.rectangle(left+x0*factor, top+y0*factor, (x1-x0+1)*factor, (y1-y0+1)*factor)
        cr.fill()
        cr.set_source_rgb(1, 1, 1)
        cr.set_font_size(11)
        cr.move_to(left+4, top+box_h-6)
        cr.show_text(f'{settings.mode}  {x1-x0+1}×{y1-y0+1} px  (+{x0}, +{y0})')

    def draw_curve(self, _area, cr, width, height):
        pad = 30
        plot_w, plot_h = width-2*pad, height-2*pad
        cr.set_source_rgb(.88, .88, .91)
        cr.set_line_width(1)
        for step in (0, .25, .5, .75, 1):
            cr.move_to(pad, pad+plot_h*step)
            cr.line_to(pad+plot_w, pad+plot_h*step)
            cr.move_to(pad+plot_w*step, pad)
            cr.line_to(pad+plot_w*step, pad+plot_h)
            cr.stroke()
        try:
            settings = self.current()
        except ValueError:
            return
        cr.set_source_rgb(.2, .45, .85)
        cr.set_line_width(2.5)
        for index in range(101):
            t = index/100
            y = pad+plot_h-(settings.pressure(t, 0, 1)/bridge.PRESSURE_MAX)*plot_h
            if index:
                cr.line_to(pad+t*plot_w, y)
            else:
                cr.move_to(pad, y)
        cr.stroke()
        t = bridge.ratio(self.raw, self.pmin, self.pmax)
        out = settings.pressure(self.raw, self.pmin, self.pmax)/bridge.PRESSURE_MAX
        cr.set_source_rgb(.9, .3, .2 if self.tip else .55)
        cr.arc(pad+t*plot_w, pad+plot_h-out*plot_h, 5, 0, 6.2832)
        cr.fill()
        cr.set_source_rgb(.4, .4, .42)
        cr.set_font_size(10)
        cr.move_to(4, pad+8)
        cr.show_text('出力 100%')
        cr.move_to(10, pad+plot_h+4)
        cr.show_text('0%')
        cr.move_to(pad+plot_w-40, height-6)
        cr.show_text('ペン筆圧 →')

    # ---------- 実機 ----------
    def open_tablet(self):
        try:
            device = bridge.find_tablet()
            self.fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
            axis = bridge.axis(self.fd, 24)
            self.pmin, self.pmax = axis[1], axis[2]
            GLib.io_add_watch(self.fd, GLib.PRIORITY_DEFAULT, GLib.IOCondition.IN, self.on_event)
            return f'{device}（筆圧 {self.pmin}〜{self.pmax}）'
        except Exception as exc:
            self.fd = None
            return f'読み込めません（{exc}）'

    def on_event(self, _fd, _condition):
        try:
            while True:
                raw = os.read(self.fd, EVENT.size*64)
                if not raw:
                    break
                for offset in range(0, len(raw)-EVENT.size+1, EVENT.size):
                    _, _, kind, code, value = EVENT.unpack_from(raw, offset)
                    if kind == 3 and code == 24:
                        self.raw = value
                    elif kind == 1 and code in (320, 321):
                        self.prox = bool(value)
                    elif kind == 1 and code == 330:
                        self.tip = bool(value)
        except BlockingIOError:
            pass
        except OSError:
            return False
        self.redraw()
        self.update_meter()
        return True

    def update_meter(self):
        try:
            settings = self.current()
            out = settings.pressure(self.raw, self.pmin, self.pmax) if self.tip else 0
        except ValueError:
            out = 0
        self.meter.set_value(out/bridge.PRESSURE_MAX)
        state = 'ペン先：接触' if self.tip else ('ペン先：ホバー' if self.prox else 'ペン：範囲外')
        self.test_label.set_text(f'{state} ／ 生の筆圧 {self.raw} / {self.pmax} → '
                                 f'CSP に届く値 {out} / {bridge.PRESSURE_MAX}'
                                 f'（{(out/bridge.PRESSURE_MAX)*100:.0f}%）')

    # ---------- 状態 ----------
    def bridge_status(self):
        try:
            state = json.loads(STATUS.read_text())
        except (OSError, ValueError):
            return '転送プログラム: 状態不明', None
        pid = state.get('pid')
        if not (pid and Path(f'/proc/{pid}').exists()):
            return '転送プログラム: 停止中（CSP 起動時に自動で始まります）', None
        text = (f'転送プログラム: 稼働中 PID {pid} ／ PSM 接続 '
                f'{"あり" if state.get("connected") else "なし"} ／ CSP 前面 '
                f'{"はい" if state.get("active") else "いいえ"} ／ 排他占有 '
                f'{"はい" if state.get("grabbed") else "いいえ"} ／ 送信 {state.get("packets")} パケット')
        return text, state.get('settings')

    def poll_status(self):
        # 転送プログラムの稼働中はペンデバイスを排他占有していて evdev の
        # 直接読み取りにイベントが届かないため、状態ファイル（約 20 Hz 更新）
        # からペンの状態を読む。停止中は on_event の evdev 読み取りが動く。
        try:
            state = json.loads(STATUS.read_text())
        except (OSError, ValueError):
            return True
        pid = state.get('pid')
        live = (bool(pid) and not state.get('stopped')
                and Path(f'/proc/{pid}').exists()
                and time.time()-state.get('updated', 0) < 2)
        if not live or state.get('raw_pressure') is None:
            return True
        pen = (state.get('raw_pressure', 0), bool(state.get('prox')), bool(state.get('tip')))
        if pen != self.last_pen:
            self.last_pen = pen
            self.raw, self.prox, self.tip = pen
            self.redraw()
            self.update_meter()
        return True

    def refresh(self):
        text, applied = self.bridge_status()
        screen_w, screen_h = self.screen_size()
        self.info.set_text(f'画面 {screen_w}×{screen_h} px ／ タブレット 216×135 mm ／ {text}')
        self.update_meter()
        try:
            shown = self.current().summary()
        except ValueError:
            shown = None
        if applied and shown and applied != shown:
            self.status.set_text('反映待ち: 動作中の転送プログラムは別の値で動いています。'
                                 '「保存して適用」を押すと即座に切り替わります（数秒で自動反映されます）。')
        return True

    def command(self, *args):
        try:
            result = subprocess.run([str(WRAPPER), *args], capture_output=True, text=True, timeout=10)
            self.status.set_text((result.stdout+result.stderr).strip()
                                 or f'実行しました: {WRAPPER} {" ".join(args)}')
            return result.returncode
        except Exception as exc:
            self.status.set_text(f'実行できませんでした: {exc}')
            return 1

    def save(self, *_):
        try:
            values = self.values()
            settings = bridge.Settings(values)  # 保存前に転送プログラムと同じ検証を通す
            text = updated_config(CONF.read_text(), values)
            backup = BASE/'backups/pentab'
            backup.mkdir(parents=True, exist_ok=True)
            shutil.copy2(CONF, backup/('pentab-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.conf'))
            fd, temp = tempfile.mkstemp(dir=CONF.parent, prefix='.pentab-')
            try:
                with os.fdopen(fd, 'w') as handle:
                    handle.write(text)
                os.replace(temp, CONF)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
            self.command('--reload')
            self.status.set_text('保存しました: '+' / '.join(settings.describe())
                                 + '\nCSP を前面に出してペンで描いて確認してください。'
                                 + f'（変更前の設定は {backup} に保存）')
        except Exception as exc:
            self.status.set_text('保存できませんでした: '+str(exc))

    def do_shutdown(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
        Gtk.Application.do_shutdown(self)


if __name__ == '__main__':
    PenSettings().run()
