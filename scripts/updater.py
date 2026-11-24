# -*- coding: utf-8 -*-
"""Self-update for Activity Plan Builder.

Updates replace the skill folder's code/assets with a newer release zip.
User plans (plan.json) always live outside the skill folder, so they are
never touched.
"""
from __future__ import annotations

import shutil
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

VERSION_FILENAME = "VERSION"
FALLBACK_VERSION = "1.0.0"


def current_version(skill_dir: str | Path) -> str:
    path = Path(skill_dir) / VERSION_FILENAME
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    return FALLBACK_VERSION


def download(url: str, dest: Path, timeout: int = 120) -> Path:
    request = urllib.request.Request(url, headers={"User-Agent": "activity-plan-builder-updater/1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()
    dest.write_bytes(data)
    return dest


def _extract_root(zip_path: Path) -> Path:
    """Extract to a temp dir; return the real skill root inside it."""
    extract_dir = Path(tempfile.mkdtemp(prefix="apb-update-"))
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)
    # Find the folder that contains SKILL.md (supports zips with or without a top folder)
    candidates = [p for p in extract_dir.rglob("SKILL.md") if p.is_file()]
    if not candidates:
        raise ValueError("压缩包内找不到 SKILL.md，不是有效的技能包。")
    return candidates[0].parent


def apply_update(target_dir: str | Path, zip_path: str | Path, backup: bool = True) -> dict:
    target = Path(target_dir).expanduser().resolve()
    zip_path = Path(zip_path).expanduser().resolve()
    if not zip_path.exists():
        raise ValueError(f"找不到更新包：{zip_path}")
    if not (target / "SKILL.md").exists():
        raise ValueError(f"目标目录不是技能目录（缺少 SKILL.md）：{target}")

    old_version = current_version(target)
    source_root = _extract_root(zip_path)
    new_version = current_version(source_root)

    if backup:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup_dir = target.parent / f"{target.name}.bak-{stamp}"
        shutil.copytree(
            target, backup_dir,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"),
        )

    for item in source_root.iterdir():
        dest = target / item.name
        if item.is_dir():
            if item.name == "__pycache__":
                continue
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)

    shutil.rmtree(source_root.parent, ignore_errors=True)
    return {"from": old_version, "to": new_version, "target": str(target),
            "backup": str(backup_dir) if backup else ""}


def update_from_url(target_dir: str | Path, url: str, backup: bool = True,
                    timeout: int = 120) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="apb-dl-")) / "release.zip"
    download(url, tmp, timeout=timeout)
    try:
        return apply_update(target_dir, tmp, backup=backup)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
