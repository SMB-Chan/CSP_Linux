#!/usr/bin/env python3
"""Report which Windows PE files in a directory are .NET assemblies.

Used to decide whether Clip Studio Paint needs a real .NET Framework runtime
(dotnet48) or whether Wine's built-in mscoree/mono is enough.
"""
import os
import struct
import sys


def is_dotnet(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            data = fh.read(1 << 20)
        if data[:2] != b"MZ":
            return False
        pe_off = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe_off:pe_off + 4] != b"PE\0\0":
            return False
        coff = pe_off + 4
        nsec, = struct.unpack_from("<H", data, coff + 2)
        opt_size, = struct.unpack_from("<H", data, coff + 16)
        magic, = struct.unpack_from("<H", data, coff + 20)
        pe32plus = magic == 0x20B
        # data directory #14 (COM descriptor) index differs by magic
        dd_off = coff + 20 + (112 if pe32plus else 96) + 14 * 8
        rva, size = struct.unpack_from("<II", data, dd_off)
        return rva != 0 and size != 0
    except (OSError, struct.error):
        return False


def main() -> int:
    roots = sys.argv[1:] or ["."]
    found = 0
    for root in roots:
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                if not name.lower().endswith((".exe", ".dll")):
                    continue
                path = os.path.join(dirpath, name)
                if is_dotnet(path):
                    print(path)
                    found += 1
    print(f"# {found} .NET assemblies", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
