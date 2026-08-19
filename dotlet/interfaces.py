from __future__ import annotations

import ipaddress
import json
import shutil
import subprocess
import sys
import threading
from typing import Mapping, Sequence

from .store import Store, validate_interfaces


VIRTUAL_PREFIXES = ("docker", "veth", "virbr", "br-", "podman", "cni", "flannel")
REJECTED_FLAGS = {"tentative", "deprecated", "dadfailed", "temporary"}


def parse_interface_addresses(
    payload: Sequence[Mapping[str, object]],
    interfaces: str,
    *,
    include_ipv4: bool,
    include_ipv6: bool,
) -> list[str]:
    selected = validate_interfaces(interfaces)
    wildcard = selected == ["*"]
    selected_names = set(selected)
    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for item in payload:
        name = str(item.get("ifname", ""))
        interface_flags = {str(flag).upper() for flag in item.get("flags", [])}  # type: ignore[arg-type]
        if not name or name == "lo" or "UP" not in interface_flags:
            continue
        if wildcard:
            if name.startswith(VIRTUAL_PREFIXES):
                continue
        elif name not in selected_names:
            continue
        for raw_info in item.get("addr_info", []):  # type: ignore[union-attr]
            info = dict(raw_info)  # type: ignore[arg-type]
            family = info.get("family")
            if family == "inet" and not include_ipv4:
                continue
            if family == "inet6" and not include_ipv6:
                continue
            if family not in {"inet", "inet6"} or info.get("scope") in {"host", "link"}:
                continue
            flags = {str(flag).lower() for flag in info.get("flags", [])}
            if flags & REJECTED_FLAGS or any(bool(info.get(flag)) for flag in REJECTED_FLAGS):
                continue
            try:
                address = ipaddress.ip_address(str(info.get("local", "")))
            except ValueError:
                continue
            if address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified:
                continue
            addresses.add(address)
    return [str(address) for address in sorted(addresses, key=lambda address: (address.version, int(address)))]


def discover_interface_addresses(settings: Mapping[str, str]) -> list[str]:
    command = shutil.which("ip")
    if command is None:
        raise FileNotFoundError("Required command 'ip' was not found; install iproute2")
    result = subprocess.run(
        [command, "-j", "address", "show"],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "ip address discovery failed").strip())
    return parse_interface_addresses(
        json.loads(result.stdout),
        settings.get("sync_interfaces", "*"),
        include_ipv4=settings.get("sync_ipv4", "yes") == "yes",
        include_ipv6=settings.get("sync_ipv6", "yes") == "yes",
    )


class InterfaceSync:
    def __init__(self, store: Store, apply_command: list[str], apply_lock: threading.Lock, interval: float = 15.0):
        self.store = store
        self.apply_command = apply_command
        self.apply_lock = apply_lock
        self.interval = max(2.0, interval)
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="dotlet-interface-sync", daemon=True)
        self.pending_apply = False
        self.sync_lock = threading.Lock()

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
        self.thread.join(timeout=3)

    def wake(self) -> None:
        self.wake_event.set()

    def sync_once(self, *, force_apply: bool = False) -> int:
        with self.sync_lock:
            _, _, settings = self.store.snapshot()
            if settings.get("auto_sync", "no") != "yes":
                return 0
            addresses = discover_interface_addresses(settings)
            if not addresses:
                raise RuntimeError("No eligible interface addresses found; keeping the last published addresses")
            changed = self.store.sync_primary_addresses(addresses)
            self.pending_apply = self.pending_apply or bool(changed) or force_apply
            if self.pending_apply:
                with self.apply_lock:
                    result = subprocess.run(
                        self.apply_command,
                        text=True,
                        capture_output=True,
                        timeout=45,
                        check=False,
                    )
                if result.returncode:
                    raise RuntimeError((result.stderr or result.stdout or "automatic apply failed").strip())
                self.pending_apply = False
            return changed

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.sync_once()
            except Exception as exc:
                print(f"Dotlet interface sync: {exc}", file=sys.stderr, flush=True)
            self.wake_event.wait(self.interval)
            self.wake_event.clear()
