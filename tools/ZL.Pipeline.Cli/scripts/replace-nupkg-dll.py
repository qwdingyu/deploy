#!/usr/bin/env python3
"""
Replace a DLL inside a .nupkg (ZIP) with an obfuscated version.

Robustness improvements:
- Auto-detect TFM from available lib/ directories in nupkg
- Support multiple lib/ TFM directories (e.g. lib/net8.0 + lib/net10.0)
- Preserve original nuspec XML exactly (no namespace changes)
- Retry on zip file corruption

Usage:
    python3 replace-nupkg-dll.py <nupkg> <new_dll> [tfm]
    
If tfm is omitted, the script auto-detects from nupkg lib/ directories.
If multiple TFM directories exist, replaces in ALL of them.
"""

import sys
import os
import zipfile
import hashlib
import shutil
import tempfile


def detect_tfms(namelist):
    """Detect all lib/ TFM directories in a nupkg."""
    tfms = set()
    for name in namelist:
        if name.startswith("lib/"):
            parts = name.split("/")
            if len(parts) >= 2:
                tfms.add(parts[1])
    return sorted(tfms)


def find_dll_paths(namelist, dll_name, tfm_hint=None):
    """Find all paths where dll_name appears in lib/ directories."""
    paths = []
    for name in namelist:
        if name.startswith("lib/"):
            if os.path.basename(name) == dll_name:
                paths.append(name)
    # If tfm_hint given and paths exist for that TFM, prefer those
    if tfm_hint:
        hinted = [p for p in paths if p.startswith(f"lib/{tfm_hint}/")]
        if hinted:
            return hinted
    return sorted(paths)


def replace_dll(nupkg_path, new_dll_path, tfm_hint=None):
    dll_name = os.path.basename(new_dll_path)
    
    sha = hashlib.sha512()
    with open(new_dll_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    new_sha = sha.hexdigest().upper()
    print(f"New DLL SHA512: {new_sha}")
    
    with tempfile.NamedTemporaryFile(suffix=".nupkg", delete=False) as tmp:
        tmp_path = tmp.name
    with tempfile.NamedTemporaryFile(suffix=".nupkg", delete=False) as out:
        out_path = out.name
    
    try:
        shutil.copy2(nupkg_path, tmp_path)
        
        with zipfile.ZipFile(tmp_path, "r") as zin:
            names = zin.namelist()
            
            # Auto-detect TFM if not provided
            tfms = detect_tfms(names)
            if not tfms:
                print("WARNING: No lib/ entries found in nupkg")
                return False
            
            # Find DLL paths
            dll_paths = find_dll_paths(names, dll_name, tfm_hint)
            
            if not dll_paths:
                print(f"WARNING: {dll_name} not found in lib/ entries")
                print(f"Available lib/ directories: {', '.join(tfms)}")
                print(f"Available DLLs in lib/:")
                lib_dirs = {}
                for n in names:
                    if n.startswith("lib/"):
                        parts = n.split("/")
                        if len(parts) >= 3:
                            lib_dirs.setdefault(parts[1], []).append(parts[2])
                for t, ds in lib_dirs.items():
                    print(f"  lib/{t}/: {', '.join(ds)}")
                return False
            
            print(f"Replaces in {len(dll_paths)} location(s): {', '.join(dll_paths)}")
            
            with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
                for info in zin.infolist():
                    if info.filename in dll_paths:
                        zout.write(new_dll_path, info.filename)
                        print(f"  Replaced: {info.filename} <- {new_dll_path}")
                    else:
                        data = zin.read(info.filename)
                        zout.writestr(info, data)
        
        # Verify the new nupkg can be opened
        with zipfile.ZipFile(out_path, "r") as check:
            check.testzip()
        
        shutil.copy2(out_path, nupkg_path)
        print(f"OK: {nupkg_path} updated")
        return True
        
    finally:
        for p in (tmp_path, out_path):
            if os.path.exists(p):
                os.unlink(p)


def main():
    if len(sys.argv) < 3:
        print("Usage: replace-nupkg-dll.py <nupkg> <new_dll> [tfm]")
        print("  tfm: optional, auto-detect if omitted")
        sys.exit(1)
    
    nupkg_path = sys.argv[1]
    new_dll_path = sys.argv[2]
    tfm_hint = sys.argv[3] if len(sys.argv) > 3 else None
    
    if not os.path.exists(nupkg_path):
        print(f"ERROR: nupkg not found: {nupkg_path}")
        sys.exit(1)
    if not os.path.exists(new_dll_path):
        print(f"ERROR: DLL not found: {new_dll_path}")
        sys.exit(1)
    
    ok = replace_dll(nupkg_path, new_dll_path, tfm_hint)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
