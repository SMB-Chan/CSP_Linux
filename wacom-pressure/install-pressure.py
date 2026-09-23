#!/usr/bin/env python3
"""Install the tested native Wintab library into the CSP Wine prefix."""
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

source = Path(__file__).resolve().parent
home = Path.home()
base = home/'ClipStudio'
if subprocess.run(['pgrep', '-x', 'CLIPStudioPaint'], stdout=subprocess.DEVNULL).returncode == 0:
    raise SystemExit('Close CSP before installing pressure support')
backup = base/'pressure-backups'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
backup.mkdir(parents=True)
prefix = base/'prefix'
system_dll = prefix/'drive_c/windows/system32/wintab32.dll'
local = prefix/'drive_c/users/intel/AppData/Local'
launch = base/'bin/csp-launch.sh'
pressure = base/'pressure'
pressure.mkdir(exist_ok=True)
local.mkdir(parents=True, exist_ok=True)
targets = [system_dll, launch, local/'psm.json', base/'bin/wacom-pressure.py', pressure/'psm.json']
manifest = []
for index, target in enumerate(targets):
    entry = {'path':str(target), 'existed':target.exists()}
    if target.exists():
        saved = backup/(str(index)+'-'+target.name)
        shutil.copy2(target, saved)
        entry.update(backup=str(saved), sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    manifest.append(entry)
(backup/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
shutil.copy2(source/'test/wintab32.dll', system_dll)
shutil.copy2(source/'test/psm.json', local/'psm.json')
shutil.copy2(source/'test/psm.json', pressure/'psm.json')
shutil.copy2(source/'wacom-pressure.py', base/'bin/wacom-pressure.py')
shutil.copy2(source/'PSM-LICENSE', pressure/'PSM-LICENSE')
shutil.copy2(source/'PSM-SOURCE.txt', pressure/'PSM-SOURCE.txt')
text = launch.read_text()
marker = '# Wacom pressure forwarding via Pain Studio Mask\n'
if marker not in text:
    needle = '. "$HOME/ClipStudio/env.sh"\n'
    assert text.count(needle) == 1
    text = text.replace(needle, needle+'\n'+marker+'export PSM_LOG_FILE="$(winepath -w "$CSP_HOME/logs/psm.log" 2>/dev/null)"\n', 1)
    launch.write_text(text)
(pressure/'last-backup.txt').write_text(str(backup)+'\n')
print('Installed PSM DLL and evdev pressure bridge')
print('Backup:',backup)
