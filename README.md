# Dotlet

**Small DNS, clear control.**

Dotlet is a lightweight IPv4 and IPv6 DNS server for Ubuntu and Kali Linux. It runs BIND9 and adds a compact web interface for managing zones, records, recursion, and trusted client networks.

## Highlights

- Listens for DNS over UDP and TCP on all IPv4 and IPv6 interfaces.
- Restricts answers and recursion to administrator-defined client networks.
- Manages A, AAAA, CNAME, MX, TXT, NS, PTR, SRV, and CAA records.
- Uses SQLite and Python's standard library; there are no pip, npm, or database-server dependencies.
- Validates configuration with `named-checkconf` and every zone with `named-checkzone`.
- Creates a backup and restores the previous configuration when BIND rejects a reload.
- Runs the UI on loopback by default and includes hardened systemd units.
- Installs BIND9 and all runtime dependencies automatically through APT.

## Install the Debian package

On a Debian-based build host:

```bash
make test
make package
sudo apt install ./dist/dotlet_0.1.0_amd64.deb
```

Use `apt install ./...deb`, not `dpkg -i`, so APT resolves and installs the declared dependencies:

- `bind9`
- `bind9-utils`
- `dnsutils`
- `python3`
- `sudo`
- `systemd`

The installer creates a random `admin` password. It prints the password once and saves it in `/var/lib/dotlet/initial-password`, readable only by root:

```bash
sudo cat /var/lib/dotlet/initial-password
```

Open an SSH tunnel from an administrator workstation:

```bash
ssh -L 8080:127.0.0.1:8080 user@dns-server
```

Then open `http://127.0.0.1:8080`. For permanent remote access, put Dotlet behind an authenticated TLS reverse proxy. Do not expose the plain HTTP management port directly to an untrusted network.

## DNS access

Dotlet binds BIND9 to all IPv4 and IPv6 interfaces, but the initial trusted list contains only loopback networks. Add the LAN's IPv4 and IPv6 CIDRs in **Access and recursion**, save, and select **Validate & apply**.

Open both DNS transports for only those networks, for example with UFW:

```bash
sudo ufw allow from 192.0.2.0/24 to any port 53 proto udp
sudo ufw allow from 192.0.2.0/24 to any port 53 proto tcp
sudo ufw allow from 2001:db8:100::/64 to any port 53 proto udp
sudo ufw allow from 2001:db8:100::/64 to any port 53 proto tcp
```

Recursion is disabled by default. If enabled, it remains limited to the same trusted networks; Dotlet is not designed to create an open public resolver.

## Verification

```bash
systemctl status dotlet-named dotlet
sudo ss -lntup | grep ':53'
dig @192.0.2.53 example.test SOA
dig @192.0.2.53 www.example.test A
dig -6 @2001:db8:100::53 www.example.test AAAA
dig +tcp @192.0.2.53 www.example.test A
```

## Development

Only Python 3.10 or newer is required:

```bash
make test
make run
```

The development command uses `/bin/true` instead of applying BIND configuration. The production service always uses the fixed, root-owned `/usr/libexec/dotlet-apply` helper.

## Files

| Path | Purpose |
|---|---|
| `/etc/default/dotlet` | UI listen address and database path |
| `/etc/bind/dotlet/` | Generated BIND configuration and zone files |
| `/var/lib/dotlet/dotlet.db` | Users, settings, zones, records, and audit trail |
| `/var/lib/dotlet/backups/` | Last-known-good generated configurations |
| `/var/lib/dotlet/initial-password` | First-install password; delete after recording it |

## Removal

Removing or purging the package stops Dotlet but deliberately preserves `/var/lib/dotlet`. DNS data and backups are never silently deleted. Remove that directory manually only after confirming that it is no longer needed.

## Current scope

Dotlet 0.1 is intended for a small internal or lab DNS server. DNSSEC zone signing, secondary-server orchestration, dynamic updates, TLS termination, and detailed query logging are future features.
