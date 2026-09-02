"""
Everysearch — GitHub Releases 確認と差し替え準備
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from app_paths import (
    APP_VERSION,
    GITHUB_REPO,
    detect_install_root,
    ensure_install_dirs,
    local_app_install_root,
    read_version,
    write_version_file,
)


@dataclass
class ReleaseInfo:
    tag: str
    version: str
    name: str
    body: str
    asset_name: str
    asset_url: str
    html_url: str


def _parse_version(text: str) -> tuple[int, ...]:
    t = (text or "").strip().lstrip("vV")
    parts = re.findall(r"\d+", t)
    if not parts:
        return (0,)
    return tuple(int(x) for x in parts)


def version_is_newer(remote: str, local: str) -> bool:
    return _parse_version(remote) > _parse_version(local)


def fetch_latest_release(repo: str = GITHUB_REPO, timeout: float = 20.0) -> ReleaseInfo:
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"Everysearch-Updater/{APP_VERSION}",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    tag = str(data.get("tag_name") or "")
    version = tag.lstrip("vV")
    assets = data.get("assets") or []
    asset_name = ""
    asset_url = ""
    # Prefer Everysearch.exe, then zip containing the name
    for a in assets:
        name = str(a.get("name") or "")
        low = name.lower()
        if low == "everysearch.exe" or (
            low.startswith("everysearch") and low.endswith(".exe")
        ):
            asset_name = name
            asset_url = str(a.get("browser_download_url") or "")
            break
    if not asset_url:
        for a in assets:
            name = str(a.get("name") or "")
            if name.lower().endswith(".zip") and "everysearch" in name.lower():
                asset_name = name
                asset_url = str(a.get("browser_download_url") or "")
                break
    if not asset_url and assets:
        a = assets[0]
        asset_name = str(a.get("name") or "")
        asset_url = str(a.get("browser_download_url") or "")

    if not asset_url:
        raise RuntimeError(
            "最新 Release にダウンロード用 asset（Everysearch.exe 等）がありません。"
        )

    return ReleaseInfo(
        tag=tag,
        version=version or tag,
        name=str(data.get("name") or tag),
        body=str(data.get("body") or ""),
        asset_name=asset_name,
        asset_url=asset_url,
        html_url=str(data.get("html_url") or f"https://github.com/{repo}/releases"),
    )


def download_file(url: str, dest: Path, timeout: float = 120.0) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"Everysearch-Updater/{APP_VERSION}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out)


def prepare_staging_exe(asset_path: Path, staging_dir: Path) -> Path:
    """zip なら展開して Everysearch.exe を探し、staging/Everysearch.exe に置く。"""
    staging_dir.mkdir(parents=True, exist_ok=True)
    target = staging_dir / "Everysearch.exe"
    if asset_path.suffix.lower() == ".exe":
        shutil.copy2(asset_path, target)
        return target

    if asset_path.suffix.lower() == ".zip":
        import zipfile

        extract_to = staging_dir / "_extract"
        if extract_to.exists():
            shutil.rmtree(extract_to, ignore_errors=True)
        extract_to.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(asset_path, "r") as zf:
            zf.extractall(extract_to)
        found = None
        for p in extract_to.rglob("Everysearch.exe"):
            found = p
            break
        if found is None:
            raise RuntimeError("zip 内に Everysearch.exe が見つかりません")
        shutil.copy2(found, target)
        return target

    raise RuntimeError(f"未対応の asset: {asset_path.name}")


def write_update_runner(
    install_root: Path,
    *,
    new_version: str,
    wait_pid: int,
) -> Path:
    """
    本体終了後に current↔previous を差し替え、新 EXE を起動する bat を書く。
    """
    ensure_install_dirs(install_root)
    runner = install_root / "update_runner.bat"
    current = install_root / "current"
    previous = install_root / "previous"
    staging_exe = install_root / "staging" / "Everysearch.exe"
    # CP932-safe: ASCII only in bat body
    lines = [
        "@echo off",
        "chcp 932 >nul",
        "setlocal",
        f'cd /d "{install_root}"',
        f"echo Waiting for PID {wait_pid} ...",
        f'powershell -NoProfile -Command "try {{ Wait-Process -Id {wait_pid} -Timeout 60 -ErrorAction SilentlyContinue }} catch {{}}"',
        "timeout /t 1 /nobreak >nul",
        "if exist previous\\Everysearch.exe.bak del /f /q previous\\Everysearch.exe.bak",
        "if exist previous\\Everysearch.exe move /y previous\\Everysearch.exe previous\\Everysearch.exe.bak >nul",
        "if exist current\\Everysearch.exe move /y current\\Everysearch.exe previous\\Everysearch.exe >nul",
        "if exist current\\version.txt move /y current\\version.txt previous\\version.txt >nul",
        f'copy /y "{staging_exe}" "current\\Everysearch.exe" >nul',
        f'echo {new_version}> current\\version.txt',
        "start \"\" \"current\\Everysearch.exe\"",
        "exit /b 0",
    ]
    text = "\r\n".join(lines) + "\r\n"
    # Write as CP932 for cmd
    try:
        runner.write_bytes(text.encode("cp932", errors="replace"))
    except Exception:
        runner.write_text(text, encoding="utf-8")
    return runner


def apply_update_and_restart(release: ReleaseInfo) -> str:
    """
    DL→staging→runner 起動→呼び出し元は終了すること。
    戻り値: ユーザー向けメッセージ（成功準備完了）
    """
    install_root = detect_install_root() or local_app_install_root()
    ensure_install_dirs(install_root)
    staging = install_root / "staging"
    # clear staging lightly
    for p in staging.glob("*"):
        try:
            if p.is_file():
                p.unlink()
        except OSError:
            pass

    tmp = staging / release.asset_name
    download_file(release.asset_url, tmp)
    exe = prepare_staging_exe(tmp, staging)
    write_version_file(staging / "version.txt", release.version)

    # Ensure current exists (first update from odd layout)
    current = install_root / "current"
    current.mkdir(parents=True, exist_ok=True)
    if getattr(sys, "frozen", False):
        cur_exe = Path(sys.executable).resolve()
        dest = current / "Everysearch.exe"
        if cur_exe != dest and not dest.is_file():
            try:
                shutil.copy2(cur_exe, dest)
            except OSError:
                pass
        if not (current / "version.txt").is_file():
            write_version_file(current / "version.txt", read_version())

    runner = write_update_runner(
        install_root, new_version=release.version, wait_pid=os.getpid()
    )
    import subprocess

    creationflags = 0
    if sys.platform == "win32":
        creationflags = 0x00000008 | 0x00000200  # DETACHED | NEW_GROUP
    subprocess.Popen(
        [os.environ.get("COMSPEC", "cmd.exe"), "/c", str(runner)],
        cwd=str(install_root),
        creationflags=creationflags,
        close_fds=True,
    )
    return (
        f"更新を準備しました（{release.version}）。\n"
        "アプリを終了すると差し替えが実行され、同じショートカットで新版が起動します。"
    )
