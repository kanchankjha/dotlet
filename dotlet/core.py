from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence


SUPPORTED_TYPES = ("A", "AAAA", "CNAME", "MX", "TXT", "NS", "PTR", "SRV", "CAA")
_LABEL = re.compile(r"^(?:[a-zA-Z0-9_](?:[a-zA-Z0-9_-]{0,61}[a-zA-Z0-9_])?|\*)$")
_HOST = re.compile(
    r"^(?=.{1,253}\.?$)(?:[a-zA-Z0-9_](?:[a-zA-Z0-9_-]{0,61}[a-zA-Z0-9_])?\.)*"
    r"[a-zA-Z0-9_](?:[a-zA-Z0-9_-]{0,61}[a-zA-Z0-9_])?\.?$"
)


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Zone:
    id: int
    name: str
    default_ttl: int
    primary_ns: str
    admin_email: str
    serial: int
    refresh: int = 3600
    retry: int = 900
    expire: int = 1209600
    minimum: int = 300


@dataclass(frozen=True)
class Record:
    id: int
    zone_id: int
    name: str
    type: str
    value: str
    ttl: int | None = None


def canonical_zone(value: str) -> str:
    value = value.strip().lower().rstrip(".")
    if not value or not _HOST.fullmatch(value) or "." not in value:
        raise ValidationError("Zone must be a valid DNS name containing at least one dot")
    return value


def canonical_host(value: str, *, allow_at: bool = False) -> str:
    value = value.strip().lower()
    if allow_at and value == "@":
        return value
    value = value.rstrip(".")
    if not value or not _HOST.fullmatch(value):
        raise ValidationError("Invalid DNS name")
    return value


def validate_owner(value: str) -> str:
    value = value.strip().lower().rstrip(".")
    if value == "@":
        return value
    if not value or len(value) > 253 or any(not _LABEL.fullmatch(label) for label in value.split(".")):
        raise ValidationError("Invalid record name")
    return value


def validate_ttl(value: int | str | None, *, optional: bool = False) -> int | None:
    if optional and (value is None or str(value).strip() == ""):
        return None
    try:
        ttl = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValidationError("TTL must be an integer") from exc
    if not 30 <= ttl <= 2147483647:
        raise ValidationError("TTL must be between 30 and 2147483647 seconds")
    return ttl


def validate_networks(value: str) -> list[str]:
    result: list[str] = []
    for raw in re.split(r"[,\s]+", value.strip()):
        if not raw:
            continue
        try:
            result.append(str(ipaddress.ip_network(raw, strict=False)))
        except ValueError as exc:
            raise ValidationError(f"Invalid client network: {raw}") from exc
    if not result:
        raise ValidationError("At least one trusted client network is required")
    return list(dict.fromkeys(result))


def validate_record(record_type: str, value: str) -> tuple[str, str]:
    record_type = record_type.strip().upper()
    value = value.strip()
    if record_type not in SUPPORTED_TYPES:
        raise ValidationError("Unsupported record type")
    if not value or "\n" in value or "\r" in value or "\x00" in value:
        raise ValidationError("Record value is empty or contains a forbidden character")

    if record_type == "A":
        address = ipaddress.ip_address(value)
        if address.version != 4:
            raise ValidationError("A records require an IPv4 address")
        value = str(address)
    elif record_type == "AAAA":
        address = ipaddress.ip_address(value)
        if address.version != 6:
            raise ValidationError("AAAA records require an IPv6 address")
        value = str(address)
    elif record_type in {"CNAME", "NS", "PTR"}:
        value = canonical_host(value) + "."
    elif record_type == "MX":
        parts = value.split()
        if len(parts) != 2 or not parts[0].isdigit() or not 0 <= int(parts[0]) <= 65535:
            raise ValidationError("MX value must be: priority hostname")
        value = f"{int(parts[0])} {canonical_host(parts[1])}."
    elif record_type == "SRV":
        parts = value.split()
        if len(parts) != 4 or any(not item.isdigit() for item in parts[:3]):
            raise ValidationError("SRV value must be: priority weight port target")
        numbers = [int(item) for item in parts[:3]]
        if any(not 0 <= item <= 65535 for item in numbers):
            raise ValidationError("SRV numeric fields must be between 0 and 65535")
        value = f"{numbers[0]} {numbers[1]} {numbers[2]} {canonical_host(parts[3])}."
    elif record_type == "CAA":
        parts = value.split(maxsplit=2)
        if len(parts) != 3 or not parts[0].isdigit() or not 0 <= int(parts[0]) <= 255:
            raise ValidationError('CAA value must be: flags tag value (for example: 0 issue letsencrypt.org)')
        if parts[1] not in {"issue", "issuewild", "iodef"}:
            raise ValidationError("Unsupported CAA tag")
        value = f'{int(parts[0])} {parts[1]} "{_quote(parts[2])}"'
    elif record_type == "TXT":
        if len(value.encode("utf-8")) > 255:
            raise ValidationError("TXT values are limited to 255 UTF-8 bytes in this release")
        value = f'"{_quote(value)}"'
    return record_type, value


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def next_serial(current: int, now: datetime | None = None) -> int:
    today = int((now or datetime.now(timezone.utc)).strftime("%Y%m%d00"))
    if current < today:
        return today
    if current >= 4294967295:
        raise ValidationError("SOA serial has reached its maximum value")
    return current + 1


def zone_filename(zone_name: str) -> str:
    return "db." + re.sub(r"[^a-z0-9.-]", "_", canonical_zone(zone_name))


def render_zone(zone: Zone, records: Sequence[Record]) -> str:
    primary = canonical_host(zone.primary_ns) + "."
    admin = canonical_host(zone.admin_email) + "."
    lines = [
        "; Generated by Dotlet. Manual changes will be overwritten.",
        f"$ORIGIN {zone.name}.",
        f"$TTL {zone.default_ttl}",
        f"@ IN SOA {primary} {admin} (",
        f"    {zone.serial} ; serial",
        f"    {zone.refresh} ; refresh",
        f"    {zone.retry} ; retry",
        f"    {zone.expire} ; expire",
        f"    {zone.minimum} ; minimum",
        ")",
        f"@ IN NS {primary}",
    ]
    for record in sorted(records, key=lambda item: (item.name, item.type, item.value)):
        owner = validate_owner(record.name)
        record_type, value = validate_record(record.type, record.value.strip('"') if record.type == "TXT" and record.value.startswith('"') else record.value)
        ttl = f" {validate_ttl(record.ttl)}" if record.ttl is not None else ""
        lines.append(f"{owner}{ttl} IN {record_type} {value}")
    return "\n".join(lines) + "\n"


def render_named_config(zones: Sequence[Zone], settings: Mapping[str, str], zone_dir: Path) -> str:
    recursion = settings.get("recursion", "no") == "yes"
    networks = validate_networks(settings.get("trusted_networks", "127.0.0.0/8 ::1/128"))
    acl = " ".join(f"{network};" for network in networks)
    lines = [
        "// Generated by Dotlet. Manual changes will be overwritten.",
        f"acl dotlet_trusted {{ {acl} }};",
        "options {",
        '    directory "/var/cache/bind";',
        "    listen-on port 53 { any; };",
        "    listen-on-v6 port 53 { any; };",
        "    allow-query { dotlet_trusted; };",
        f"    recursion {'yes' if recursion else 'no'};",
    ]
    if recursion:
        lines.extend([
            "    allow-recursion { dotlet_trusted; };",
            "    allow-query-cache { dotlet_trusted; };",
            "    dnssec-validation auto;",
        ])
    else:
        lines.append("    allow-query-cache { none; };")
    lines.extend(["};", 'include "/etc/bind/named.conf.default-zones";'])
    for zone in sorted(zones, key=lambda item: item.name):
        lines.extend([
            f'zone "{zone.name}" {{',
            "    type primary;",
            f'    file "{zone_dir / zone_filename(zone.name)}";',
            "    allow-update { none; };",
            "    allow-transfer { none; };",
            "};",
        ])
    return "\n".join(lines) + "\n"


def render_all(zones: Sequence[Zone], records: Iterable[Record], settings: Mapping[str, str], zone_dir: Path) -> dict[str, str]:
    grouped: dict[int, list[Record]] = {zone.id: [] for zone in zones}
    for record in records:
        if record.zone_id in grouped:
            grouped[record.zone_id].append(record)
    output = {"named.conf.generated": render_named_config(zones, settings, zone_dir)}
    for zone in zones:
        output[f"zones/{zone_filename(zone.name)}"] = render_zone(zone, grouped[zone.id])
    return output
