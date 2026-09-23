#!/usr/bin/python3
"""TourBox Lite の既存ドライバー向けキー設定画面。"""
import configparser
import datetime
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, GLib

BASE = Path.home() / 'ClipStudio'
CONF = BASE / 'etc/tourbox.conf'
WRAPPER = BASE / 'bin/tourbox-daemon.sh'
CONTROLS = [
 ('side','サイド'),('top','トップ'),('tall','トール（縦長）'),('short','ショート'),
 ('c1','C1'),('c2','C2'),('tour','Tour'),
 ('scroll_up','スクロール ↑'),('scroll_down','スクロール ↓'),('scroll_click','スクロール 押す'),
 ('knob_cw','ノブ 時計回り'),('knob_ccw','ノブ 反時計回り'),('knob_click','ノブ 押す'),
 ('dpad_up','十字 上'),('dpad_down','十字 下'),('dpad_left','十字 左'),('dpad_right','十字 右'),
 ('dial_cw','ダイヤル 時計回り'),('dial_ccw','ダイヤル 反時計回り'),('dial_click','ダイヤル 押す')]
PRESETS = ['none','ctrl+z','ctrl+shift+z','hold:alt','hold:space','bracketleft','bracketright',
           'b','e','p','Escape','ctrl+s','wheel:1','wheel:-1','ctrl+wheel:1','ctrl+wheel:-1']
ALIASES = dict(up='Up',down='Down',left='Left',right='Right',esc='Escape',escape='Escape',
 enter='Return',return_='Return',tab='Tab',space='space',backspace='BackSpace',delete='Delete',
 home='Home',end='End',pageup='Page_Up',pagedown='Page_Down')

def validate(control, value):
    if value == 'none': return
    if value.startswith(('hold:', 'tap:')):
        if value.startswith('hold:') and control.endswith(('_cw','_ccw','_up','_down')) and not control.startswith('dpad'):
            raise ValueError('回転操作には長押しを設定できません')
        value = value.split(':',1)[1]
    if not value: raise ValueError('キーを指定してください（無効は none）')
    for token in value.split('+'):
        if token in ('ctrl','control','shift','alt','super','meta','win'): continue
        if re.fullmatch(r'(?:h?wheel):(?:-?[1-9][0-9]?)', token): continue
        if token in ('btn:left','btn:middle','btn:right','btn:back','btn:forward'): continue
        name = ALIASES.get(token.lower(), token)
        if not token or not any(Gdk.keyval_from_name(n) not in (0, 0xffffff) for n in (name,name.capitalize(),name.upper(),name.lower())):
            raise ValueError('不明なキー: ' + token)

def updated_config(original, values):
    cfg = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=('#',))
    cfg.read_string(original)
    profiles = [s for s in cfg.sections() if s.startswith('profile:')]
    if profiles != ['profile:default']:
        raise ValueError('複数プロファイルの設定は、この画面では編集できません')
    result = []; active = False; written = set()
    for line in original.splitlines():
        if line.strip().startswith('['):
            if active:
                result += [f'{k} = {v}' for k,v in values.items() if k not in written]
            active = line.strip() == '[profile:default]'
        match = re.match(r'^\s*(\w+)\s*=',line) if active else None
        if match and match[1] in values:
            key = match[1]
            tail = line.split('=', 1)[1]
            comment = tail.split('#', 1)[1].strip() if '#' in tail else ''
            line = f'{key} = {values[key]}' + (f'  # {comment}' if comment else '')
            written.add(key)
        result.append(line)
    if active: result += [f'{k} = {v}' for k,v in values.items() if k not in written]
    return '\n'.join(result) + '\n'

class Settings(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='local.clipstudio.TourBoxSettings')
        self.connect('activate',self.activate)
    def activate(self, app):
        if self.get_active_window(): self.get_active_window().present(); return
        win = Gtk.ApplicationWindow(application=self,title='TourBox キー設定 — CSP')
        win.set_default_size(650,760)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12)
        for side in ('top','bottom','start','end'): getattr(box,'set_margin_'+side)(18)
        win.set_child(box)
        label = Gtk.Label(label='TourBox Lite • CLIP STUDIO PAINT',xalign=0)
        label.add_css_class('title-2'); box.append(label)
        box.append(Gtk.Label(label='キーを入力、または候補を選び「保存して適用」を押してください。\nCSP が前面にあるときだけ動作します。実機にない操作は無視されます。',xalign=0,wrap=True))
        scroll = Gtk.ScrolledWindow(vexpand=True); box.append(scroll)
        grid = Gtk.Grid(column_spacing=20,row_spacing=7); scroll.set_child(grid)
        cfg = configparser.ConfigParser(interpolation=None,inline_comment_prefixes=('#',)); cfg.read(CONF)
        self.entries = {}
        for i,(key,label) in enumerate(CONTROLS):
            grid.attach(Gtk.Label(label=label,xalign=0),0,i,1,1)
            combo = Gtk.ComboBoxText.new_with_entry(); combo.set_hexpand(True)
            for value in PRESETS: combo.append_text(value)
            combo.get_child().set_text(cfg.get('profile:default',key,fallback='none'))
            grid.attach(combo,1,i,1,1); self.entries[key] = combo.get_child()
        box.append(Gtk.Label(label='例: ctrl+z（元に戻す） / b（ブラシ） / hold:space（押している間だけ手のひら）\nbracketleft / bracketright（[ / ]） / none（無効）',xalign=0,wrap=True))
        self.status = Gtk.Label(xalign=0,wrap=True); box.append(self.status)
        row = Gtk.Box(spacing=10); box.append(row)
        save = Gtk.Button(label='保存して適用'); save.add_css_class('suggested-action'); save.connect('clicked',self.save); row.append(save)
        start = Gtk.Button(label='入力転送を起動'); start.connect('clicked',self.start); row.append(start)
        stop = Gtk.Button(label='停止'); stop.connect('clicked',lambda _: self.command('--stop')); row.append(stop)
        self.command('--status'); win.present()
    def command(self,*args):
        result = subprocess.run([str(WRAPPER),*args],capture_output=True,text=True,timeout=6)
        self.status.set_text((result.stdout + result.stderr).strip())
        return result.returncode
    def start(self,*_): self.command()
    def save(self,*_):
        try:
            values = {k:e.get_text().strip() or 'none' for k,e in self.entries.items()}
            for k,v in values.items(): validate(k,v)
            text = updated_config(CONF.read_text(),values)
            backup = BASE / 'backups/tourbox'; backup.mkdir(parents=True,exist_ok=True)
            shutil.copy2(CONF,backup / ('tourbox-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.conf'))
            fd,temp = tempfile.mkstemp(dir=CONF.parent,prefix='.tourbox-')
            try:
                with os.fdopen(fd,'w') as f: f.write(text)
                os.replace(temp,CONF)
            finally:
                if os.path.exists(temp): os.unlink(temp)
            if self.command('--status') == 0: self.command('--reload')
            else: self.command()
            self.status.set_text('保存しました。CSP を前面に出して TourBox を試してください。\n'+self.status.get_text())
        except Exception as e: self.status.set_text('保存できませんでした: '+str(e))

if __name__ == '__main__': Settings().run()
