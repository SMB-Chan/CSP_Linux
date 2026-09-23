#!/usr/bin/env python3
"""Grant intel read access only to this Wacom tablet's event devices."""
import glob
import os
from pathlib import Path
import pwd
import subprocess

if os.geteuid() != 0:
    raise SystemExit('Administrator authentication is required')
uid = pwd.getpwnam('intel').pw_uid
if uid != 1000:
    raise SystemExit('Desktop account differs from the verified setup')
rule = ('# CSP pressure: read-only access for intel to Wacom One 0531:0102.\n'
        'SUBSYSTEM=="input", KERNEL=="event*", ATTRS{idVendor}=="0531", '
        'ATTRS{idProduct}=="0102", ENV{ID_INPUT_TABLET}=="1", '
        'RUN+="/usr/bin/setfacl -m u:1000:r $env{DEVNAME}"\n')
target = Path('/etc/udev/rules.d/99-csp-wacom-pressure.rules')
if target.exists() and target.read_text() != rule:
    raise SystemExit('A different rule already exists; refusing to overwrite it')
target.write_text(rule)
target.chmod(0o644)
subprocess.run(['/usr/bin/udevadm', 'control', '--reload-rules'], check=True)
count = 0
for path in glob.glob('/sys/class/input/event*'):
    p = Path(path)/'device'
    try:
        if (p/'id/vendor').read_text().strip() != '0531': continue
        if (p/'id/product').read_text().strip() != '0102': continue
        bits = int((p/'capabilities/abs').read_text().replace(' ', ''), 16)
        if not bits & (1 << 24): continue
    except OSError:
        continue
    device = '/dev/input/'+Path(path).name
    subprocess.run(['/usr/bin/setfacl', '-m', 'u:1000:r', device], check=True)
    count += 1
print(f'Wacom read permission configured. Current pen devices: {count}')
