# Changelog

All notable changes to Dotlet will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.1] - 2026-08-28

### Added
- Initial public release
- Web interface for BIND9 DNS management
- Support for A, AAAA, CNAME, MX, TXT, NS, PTR, SRV, and CAA records
- SQLite-based configuration storage
- Automatic primary-nameserver record maintenance
- Configuration validation with named-checkconf and named-checkzone
- Atomic configuration updates with automatic rollback
- Hardened systemd units
- Debian/Ubuntu package with APT integration

[Unreleased]: https://github.com/kanchankjha/dotlet/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/kanchankjha/dotlet/releases/tag/v0.2.1
