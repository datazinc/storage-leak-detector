#!/usr/bin/env python3
"""Copy frontend/dist to src/sldd/web for packaging. Run before python -m build."""

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST = ROOT / "frontend" / "dist"
PKG_WEB = ROOT / "src" / "sldd" / "web"

if not FRONTEND_DIST.is_dir():
    raise SystemExit("frontend/dist not found. Run: cd frontend && npm run build")

if PKG_WEB.exists():
    shutil.rmtree(PKG_WEB)
PKG_WEB.mkdir(parents=True)
for f in FRONTEND_DIST.iterdir():
    dest = PKG_WEB / f.name
    if f.is_dir():
        shutil.copytree(f, dest)
    else:
        shutil.copy2(f, dest)
print(f"Copied frontend/dist -> src/sldd/web")
