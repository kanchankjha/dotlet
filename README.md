# Dotlet

**Small DNS, clear control.**

Dotlet is a lightweight IPv4 and IPv6 DNS server for Ubuntu and Kali Linux. It runs BIND9 and adds a compact web interface for managing zones, records, recursion, and trusted client networks.

## Highlights

- Listens for DNS over UDP and TCP on all IPv4 and IPv6 interfaces.
- Automatically maintains primary-nameserver A/AAAA records as Linux interface addresses change.
- Restricts answers and recursion to administrator-defined client networks.
- Manages A, AAAA, CNAME, MX, TXT, NS, PTR, SRV, and CAA records.
- Uses SQLite and Python's standard library; there are no pip, npm, or database-server dependencies.
- Validates configuration with `named-checkconf` and every zone with `named-checkzone`.
- Creates a backup and restores the previous configuration when BIND rejects a reload.
- Runs the UI on loopback by default and includes hardened systemd units.
- Installs BIND9 and all runtime dependencies automatically through APT.

## Installation

### Option 1: install from a Git checkout

Clone the repository on an Ubuntu, Kali, or Debian host and run the checkout installer:

```bash
git clone https://github.com/kanchankjha/dotlet.git
cd dotlet
./install.sh
```

The script refreshes APT metadata, builds a local `.deb`, and asks APT to install it. APT installs BIND9 and every other declared runtime dependency automatically. The package lifecycle remains managed by APT even though it was built from source.

The installer resolves BIND utilities from the distribution's `PATH`, so it supports both Ubuntu and Kali filesystem layouts. It copies the generated package into a temporary APT-readable directory before installation.

To use existing package indexes without running `apt-get update`:

```bash
./install.sh --no-update
```

Pull updates and run the installer again to upgrade a checkout installation:

```bash
git pull --ff-only
./install.sh
```

Do not pipe an internet download directly into a root shell. Review the checked-out source and installer before running it.

### Option 2: build and install the Debian package manually

On a Debian-based build host:

```bash
make test
make package
sudo apt install "./dist/dotlet_0.2.0_$(dpkg --print-architecture).deb"
```

If you obtained a prebuilt Dotlet `.deb`, the same `apt install ./dotlet_VERSION_ARCH.deb` command can install it without a source checkout.

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

## Automatic nameserver addresses

In **Access and interface sync**, enable **Automatically synchronize the primary nameserver**. The default interface value `*` follows all eligible current interfaces and automatically discovers new interfaces within 15 seconds.

For every zone whose primary DNS hostname belongs to that zone, Dotlet maintains A and AAAA records for eligible host addresses. For example, `ns1.home.arpa` receives managed records named `ns1` in the `home.arpa` zone. Managed records are visible in the record table and are updated through the same validation, atomic apply, and rollback workflow as manual changes.

Wildcard mode excludes loopback, down interfaces, common container interfaces, link-local addresses, and tentative, deprecated, or temporary IPv6 addresses. To include a normally excluded virtual interface, enter its exact name instead of `*`. If no eligible addresses remain, Dotlet keeps the last published addresses so an in-zone nameserver does not become invalid.

The interval is configurable in `/etc/default/dotlet`:

```text
DOTLET_SYNC_INTERVAL=15
```

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

Dotlet 0.2 is intended for a small internal or lab DNS server. DNSSEC zone signing, secondary-server orchestration, dynamic updates, TLS termination, and detailed query logging are future features.
