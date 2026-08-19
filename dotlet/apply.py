from __future__ import annotations

import argparse
import grp
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .core import render_all, zone_filename
from .store import Store


def run_checked(command: list[str]) -> None:
    result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=30)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "command failed").strip())


def find_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise FileNotFoundError(
            f"Required command '{name}' was not found in PATH. "
            "Install or repair the bind9 and bind9-utils packages."
        )
    return path


def set_bind_permissions(path: Path) -> None:
    try:
        bind_gid = grp.getgrnam("bind").gr_gid
    except KeyError:
        bind_gid = os.getgid()
    for item in [path, *path.rglob("*")]:
        item.chmod(0o750 if item.is_dir() else 0o640)
        if os.geteuid() == 0:
            os.chown(item, 0, bind_gid)


def apply(database: Path, target: Path, backup_root: Path, *, checkconf: str, checkzone: str, rndc: str, reload_server: bool = True) -> None:
    if os.geteuid() != 0 and os.environ.get("DOTLET_ALLOW_UNPRIVILEGED_APPLY") != "1":
        raise PermissionError("dotlet-apply must run as root")
    store = Store(database)
    zones, records, settings = store.snapshot()
    output = render_all(zones, records, settings, target / "zones")
    target.parent.mkdir(parents=True, exist_ok=True)
    backup_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".dotlet-candidate-", dir=target.parent))
    previous = target.parent / f".dotlet-previous-{os.getpid()}"
    try:
        for relative, content in output.items():
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
            destination.chmod(0o640)
        run_checked([checkconf, str(staging / "named.conf.generated")])
        for zone in zones:
            run_checked([checkzone, zone.name, str(staging / "zones" / zone_filename(zone.name))])
        backup: Path | None = None
        if target.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            backup = backup_root / stamp
            shutil.copytree(target, backup)
            os.replace(target, previous)
        os.replace(staging, target)
        set_bind_permissions(target)
        try:
            if reload_server:
                run_checked([rndc, "reconfig"])
                run_checked([rndc, "reload"])
        except Exception:
            failed = target.parent / f".dotlet-failed-{os.getpid()}"
            os.replace(target, failed)
            if previous.exists():
                os.replace(previous, target)
                set_bind_permissions(target)
            shutil.rmtree(failed, ignore_errors=True)
            try:
                if reload_server and target.exists():
                    run_checked([rndc, "reconfig"])
            except Exception:
                pass
            raise
        if previous.exists():
            shutil.rmtree(previous)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if previous.exists():
            shutil.rmtree(previous, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(prog="dotlet-apply")
    parser.add_argument("--database", default="/var/lib/dotlet/dotlet.db")
    parser.add_argument("--target", default="/etc/bind/dotlet")
    parser.add_argument("--backups", default="/var/lib/dotlet/backups")
    parser.add_argument("--install", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    apply(
        Path(args.database),
        Path(args.target),
        Path(args.backups),
        checkconf=find_tool("named-checkconf"),
        checkzone=find_tool("named-checkzone"),
        rndc=find_tool("rndc"),
        reload_server=not args.install,
    )
    print("Dotlet configuration applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
