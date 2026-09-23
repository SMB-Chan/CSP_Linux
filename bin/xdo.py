#!/usr/bin/env python3
"""Small X11 helper for driving the Clip Studio Paint installer GUI.

Subcommands:
  list                 list top-level windows (id, name, class, geometry)
  shot ID [out.png]    screenshot a window with ImageMagick
  click ID X Y         click at window-relative coordinates
  key ID KEYSYM        focus a window and send a key (Return, Tab, Escape, ...)
  type ID TEXT         focus a window and type ASCII text
"""
import subprocess
import sys
import time

from Xlib import X, XK, display
from Xlib.ext import xtest

d = display.Display()
root = d.screen().root


def top_level():
    out = []
    for w in root.query_tree().children:
        try:
            attrs = w.get_attributes()
            if attrs.map_state != X.IsViewable:
                continue
            name = w.get_wm_name() or ""
            cls = w.get_wm_class() or ("", "")
            geo = w.get_geometry()
            pos = w.translate_coords(root, 0, 0)
            out.append((w, str(name), "%s.%s" % (cls[0], cls[1]),
                        (-pos.x, -pos.y, geo.width, geo.height)))
        except Exception:
            continue
    return out


def cmd_list():
    for w, name, cls, (x, y, ww, hh) in top_level():
        print("0x%x | %-40s | %-30s | %dx%d+%d+%d" % (w.id, name[:40], cls[:30], ww, hh, x, y))


def find(spec):
    if spec.startswith("0x"):
        return d.create_resource_object("window", int(spec, 16))
    target = spec.lower()
    for w, name, cls, geo in top_level():
        if target in name.lower() or target in cls.lower():
            return w
    raise SystemExit("no window matching %r" % spec)


def focus(w):
    w.set_input_focus(X.RevertToParent, X.CurrentTime)
    w.configure(stack_mode=X.Above)
    d.sync()
    time.sleep(0.3)


def cmd_shot(spec, out):
    w = find(spec)
    subprocess.run(["import", "-window", "0x%x" % w.id, out], check=True)
    print(out)


def cmd_click(spec, rx, ry):
    """Click at window-relative coordinates.

    Sends the events straight to the window: under XWayland the compositor
    drops XTest pointer injection, so SendEvent is the reliable path.
    """
    import Xlib.protocol.event as pev
    w = find(spec)
    focus(w)
    origin = w.translate_coords(root, 0, 0)
    ox, oy = -origin.x, -origin.y
    rootx, rooty = ox + int(rx), oy + int(ry)
    common = dict(time=X.CurrentTime, root=root, window=w, child=X.NONE,
                  same_screen=1, root_x=rootx, root_y=rooty,
                  event_x=int(rx), event_y=int(ry))
    w.send_event(pev.MotionNotify(detail=0, state=0, **common))
    d.sync()
    time.sleep(0.15)
    w.send_event(pev.ButtonPress(detail=1, state=0, **common))
    d.sync()
    time.sleep(0.05)
    w.send_event(pev.ButtonRelease(detail=1, state=0x100, **common))
    d.sync()
    print("clicked %s at %d,%d (root %d,%d)" % (spec, int(rx), int(ry), rootx, rooty))


def send_key(w, keysym, shift=False):
    import Xlib.protocol.event as pev
    code = d.keysym_to_keycode(keysym)
    if not code:
        return False
    state = 0x1 if shift else 0
    w.send_event(pev.KeyPress(detail=code, state=state, root=root, window=w,
                              child=X.NONE, same_screen=1, root_x=1, root_y=1,
                              event_x=1, event_y=1, time=X.CurrentTime))
    d.sync()
    time.sleep(0.03)
    w.send_event(pev.KeyRelease(detail=code, state=state, root=root, window=w,
                                child=X.NONE, same_screen=1, root_x=1, root_y=1,
                                event_x=1, event_y=1, time=X.CurrentTime))
    d.sync()
    time.sleep(0.03)
    return True


def cmd_key(spec, keysym_name):
    w = find(spec)
    focus(w)
    keysym = XK.string_to_keysym(keysym_name)
    if not keysym:
        raise SystemExit("unknown keysym %r" % keysym_name)
    if not send_key(w, keysym):
        raise SystemExit("no keycode for %r" % keysym_name)
    print("sent %s to %s" % (keysym_name, spec))


def cmd_type(spec, text):
    w = find(spec)
    focus(w)
    for ch in text:
        keysym = XK.string_to_keysym(ch)
        if not keysym:
            print("cannot type %r" % ch)
            continue
        shift = ch.isupper() or ch in '~!@#$%^&*()_+{}|:"<>?'
        if not send_key(w, keysym, shift):
            print("cannot type %r" % ch)
    print("typed %r" % text)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    if cmd == "list":
        cmd_list()
    elif cmd == "shot":
        cmd_shot(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "/tmp/shot.png")
    elif cmd == "click":
        cmd_click(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "key":
        cmd_key(sys.argv[2], sys.argv[3])
    elif cmd == "type":
        cmd_type(sys.argv[2], " ".join(sys.argv[3:]))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
