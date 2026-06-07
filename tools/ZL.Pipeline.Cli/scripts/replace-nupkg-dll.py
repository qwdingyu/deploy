#!/usr/bin/env python3
"""
Replace a DLL inside a .nupkg (ZIP) with an obfuscated version.
Preserves the original nuspec XML exactly (no namespace changes).

Usage:
    python3 replace-nupkg-dll.py <nupkg> <new_dll> <tfm>

Example:
    python3 scripts/replace-nupkg-dll.py \\
        artifacts/packages/ZL.PFLite.2.0.1.nupkg \\
        obfuscated/ZL.PFLite/ZL.PFLite.dll \\
        net8.0
"""

import sys
import os
import zipfile
import hashlib
import shutil
import tempfile


def main():
    if len(sys.argv) < 4:
        print("Usage: replace-nupkg-dll.py <nupkg> <new_dll> <tfm>")
        sys.exit(1)

    nupkg_path = sys.argv[1]
    new_dll_path = sys.argv[2]
    tfm = sys.argv[3]  # e.g. net8.0

    if not os.path.exists(nupkg_path):
        print(f"ERROR: nupkg not found: {nupkg_path}")
        sys.exit(1)
    if not os.path.exists(new_dll_path):
        print(f"ERROR: DLL not found: {new_dll_path}")
        sys.exit(1)

    dll_name = os.path.basename(new_dll_path)
    target_path = f"lib/{tfm}/{dll_name}"

    # Compute SHA512 of new DLL
    sha = hashlib.sha512()
    with open(new_dll_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    new_sha = sha.hexdigest().upper()
    print(f"New DLL SHA512: {new_sha}")

    # Work on a temp copy
    with tempfile.NamedTemporaryFile(suffix=".nupkg", delete=False) as tmp:
        tmp_path = tmp.name
    with tempfile.NamedTemporaryFile(suffix=".nupkg", delete=False) as out:
        out_path = out.name

    try:
        shutil.copy2(nupkg_path, tmp_path)

        # Read old nupkg, write new one (to properly replace, not append)
        with zipfile.ZipFile(tmp_path, "r") as zin:
            with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
                names = zin.namelist()
                if target_path not in names:
                    print(f"WARNING: {target_path} not found in nupkg")
                    print(f"Available lib/ entries:")
                    for n in names:
                        if n.startswith("lib/"):
                            print(f"  {n}")
                    sys.exit(1)

                replaced = False
                for info in zin.infolist():
                    if info.filename == target_path:
                        zout.write(new_dll_path, target_path)
                        replaced = True
                        print(f"Replaced: {target_path} <- {new_dll_path}")
                    else:
                        data = zin.read(info.filename)
                        zout.writestr(info, data)

                if not replaced:
                    print("ERROR: Could not replace DLL")
                    sys.exit(1)

        # Copy back
        shutil.copy2(out_path, nupkg_path)
        print(f"OK: {nupkg_path} updated")

    finally:
        for p in (tmp_path, out_path):
            if os.path.exists(p):
                os.unlink(p)


if __name__ == "__main__":
    main()
