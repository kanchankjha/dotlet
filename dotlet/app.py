from __future__ import annotations

import argparse
import html
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from . import __version__
from .core import SUPPORTED_TYPES, ValidationError
from .store import Store, random_password


CSS = """
:root{color-scheme:light;--ink:#14213d;--muted:#65738a;--blue:#325ee6;--pale:#eef3ff;--line:#dce3ee;--bad:#a32828}
*{box-sizing:border-box}body{margin:0;background:#f6f8fb;color:var(--ink);font:15px/1.45 system-ui,-apple-system,sans-serif}
header{background:#101a33;color:white;padding:15px 5vw;display:flex;align-items:center;justify-content:space-between}
.brand{font-size:22px;font-weight:760;letter-spacing:-.4px}.brand i{font-style:normal;color:#6ee7dc}.wrap{max-width:1120px;margin:28px auto;padding:0 20px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:18px}.card{background:white;border:1px solid var(--line);border-radius:13px;padding:20px;box-shadow:0 4px 18px #1620400a}
h1,h2,h3{margin:0 0 14px}h1{font-size:25px}h2{font-size:18px}h3{font-size:15px}.muted{color:var(--muted)}
label{display:block;font-size:13px;font-weight:650;margin:11px 0 4px}input,select,textarea{width:100%;border:1px solid #bdc8d8;border-radius:8px;padding:9px 10px;background:white;color:var(--ink)}textarea{min-height:105px;resize:vertical}
button,.button{display:inline-block;border:0;border-radius:8px;background:var(--blue);color:white;padding:9px 14px;text-decoration:none;font-weight:650;cursor:pointer}button.secondary{background:#e9eef8;color:var(--ink)}button.danger{background:#fff0f0;color:var(--bad);border:1px solid #f2c4c4}
.actions{display:flex;gap:9px;align-items:center;flex-wrap:wrap}.top-actions{margin-bottom:18px}.flash{border-radius:9px;padding:11px 14px;margin-bottom:17px;background:#e8f8f1;color:#176443}.flash.error{background:#fff0f0;color:var(--bad)}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:9px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}.mono{font-family:ui-monospace,SFMono-Regular,monospace}.pill{display:inline-block;padding:2px 8px;border-radius:99px;background:var(--pale);font-size:12px}.right{margin-left:auto}
.login{max-width:390px;margin:10vh auto}.empty{padding:25px;text-align:center;color:var(--muted)}footer{text-align:center;color:var(--muted);padding:30px}form.inline{display:inline}.record-value{max-width:410px;overflow-wrap:anywhere}@media(max-width:650px){.hide-small{display:none}header{padding:13px 18px}.wrap{padding:0 12px}}
"""


def dns_listener_up(family: int, address: str) -> bool:
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(0.15)
    try:
        sock.connect((address, 53))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def page(title: str, body: str, *, authenticated: bool = False) -> bytes:
    logout = '<form class="inline" method="post" action="/logout"><button class="secondary">Sign out</button></form>' if authenticated else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)} · Dotlet</title><style>{CSS}</style></head><body><header><div class="brand"><i>•</i> dotlet</div>{logout}</header><main class="wrap">{body}</main><footer>Dotlet {__version__} · Small DNS, clear control.</footer></body></html>""".encode()


class DotletServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], store: Store, apply_command: list[str]):
        super().__init__(address, Handler)
        self.store = store
        self.apply_command = apply_command
        self.sessions: dict[str, tuple[str, str, float]] = {}


class Handler(BaseHTTPRequestHandler):
    server: DotletServer

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/healthz":
            self._json({"status": "ok", "version": __version__})
            return
        if path == "/login":
            self._login_page()
            return
        session = self._session()
        if not session:
            self._redirect("/login")
            return
        if path == "/":
            self._dashboard(session)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        form = self._form()
        if path == "/login":
            self._login(form)
            return
        session = self._session()
        if not session:
            self._redirect("/login")
            return
        if path == "/logout":
            self._logout()
            return
        if not secrets.compare_digest(form.get("csrf", ""), session[1]):
            self.send_error(HTTPStatus.FORBIDDEN, "CSRF validation failed")
            return
        actor = session[0]
        try:
            if path == "/zones/add":
                self.server.store.add_zone(form.get("name", ""), form.get("ttl", "300"), form.get("primary_ns", ""), form.get("admin_email", ""), actor)
                self._redirect("/?ok=" + quote("Zone added. Apply changes to publish it."))
            elif path == "/zones/delete":
                self.server.store.delete_zone(int(form["zone_id"]), actor)
                self._redirect("/?ok=" + quote("Zone deleted. Apply changes to publish it."))
            elif path == "/records/add":
                self.server.store.add_record(int(form["zone_id"]), form.get("name", "@"), form.get("type", ""), form.get("value", ""), form.get("ttl"), actor)
                self._redirect("/?ok=" + quote("Record added. Apply changes to publish it."))
            elif path == "/records/delete":
                self.server.store.delete_record(int(form["record_id"]), actor)
                self._redirect("/?ok=" + quote("Record deleted. Apply changes to publish it."))
            elif path == "/settings":
                self.server.store.update_settings(form.get("recursion") == "yes", form.get("trusted_networks", ""), actor)
                self._redirect("/?ok=" + quote("Settings saved. Apply changes to publish them."))
            elif path == "/apply":
                result = subprocess.run(self.server.apply_command, text=True, capture_output=True, timeout=45, check=False)
                if result.returncode:
                    raise RuntimeError((result.stderr or result.stdout or "Apply command failed").strip())
                self._redirect("/?ok=" + quote("Configuration validated and applied successfully."))
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except (KeyError, ValueError, ValidationError, RuntimeError, sqlite3.IntegrityError, subprocess.TimeoutExpired) as exc:
            self._redirect("/?error=" + quote(str(exc)))

    def _dashboard(self, session: tuple[str, str, float]) -> None:
        zones, records, settings = self.server.store.snapshot()
        ipv4_up = dns_listener_up(socket.AF_INET, "127.0.0.1")
        ipv6_up = dns_listener_up(socket.AF_INET6, "::1")
        query = parse_qs(urlparse(self.path).query)
        notice = ""
        if query.get("ok"):
            notice = f'<div class="flash">{html.escape(query["ok"][0])}</div>'
        elif query.get("error"):
            notice = f'<div class="flash error">{html.escape(query["error"][0])}</div>'
        csrf = html.escape(session[1])
        zone_options = "".join(f'<option value="{z.id}">{html.escape(z.name)}</option>' for z in zones)
        record_rows = "".join(
            f"<tr><td>{html.escape(next(z.name for z in zones if z.id == r.zone_id))}</td><td class=mono>{html.escape(r.name)}</td><td><span class=pill>{r.type}</span></td><td class='mono record-value'>{html.escape(r.value)}</td><td>{r.ttl or 'default'}</td><td><form class=inline method=post action=/records/delete><input type=hidden name=csrf value='{csrf}'><input type=hidden name=record_id value='{r.id}'><button class=danger>Delete</button></form></td></tr>"
            for r in records
        ) or '<tr><td colspan="6" class="empty">No records yet.</td></tr>'
        zone_rows = "".join(
            f"<tr><td><strong>{html.escape(z.name)}</strong></td><td>{z.default_ttl}s</td><td class=mono>{z.serial}</td><td><form class=inline method=post action=/zones/delete><input type=hidden name=csrf value='{csrf}'><input type=hidden name=zone_id value='{z.id}'><button class=danger>Delete</button></form></td></tr>"
            for z in zones
        ) or '<tr><td colspan="4" class="empty">Create your first zone below.</td></tr>'
        audits = "".join(f"<tr><td>{html.escape(row['created_at'])}</td><td>{html.escape(row['actor'])}</td><td>{html.escape(row['action'])}</td><td>{html.escape(row['detail'])}</td></tr>" for row in self.server.store.audits(12))
        types = "".join(f"<option>{item}</option>" for item in SUPPORTED_TYPES)
        checked = " checked" if settings.get("recursion") == "yes" else ""
        no_zone = " disabled" if not zones else ""
        v4_status = '<span class=pill>IPv4 listening</span>' if ipv4_up else '<span class="pill">IPv4 offline</span>'
        v6_status = '<span class=pill>IPv6 listening</span>' if ipv6_up else '<span class="pill">IPv6 offline</span>'
        body = f"""{notice}<div class="actions top-actions"><div><h1>DNS control</h1><div class=muted>{len(zones)} zones · {len(records)} records &nbsp; {v4_status} {v6_status}</div></div><form class="right inline" method=post action=/apply><input type=hidden name=csrf value="{csrf}"><button>Validate &amp; apply</button></form></div>
        <section class=card><h2>Zones</h2><table><thead><tr><th>Zone</th><th>TTL</th><th>SOA serial</th><th></th></tr></thead><tbody>{zone_rows}</tbody></table></section>
        <div class=grid style="margin-top:18px"><section class=card><h2>Add zone</h2><form method=post action=/zones/add><input type=hidden name=csrf value="{csrf}"><label>Zone name</label><input name=name placeholder="example.test" required><label>Primary nameserver</label><input name=primary_ns placeholder="ns1.example.test" required><label>SOA administrator</label><input name=admin_email placeholder="hostmaster.example.test" required><label>Default TTL</label><input name=ttl type=number value=300 min=30 required><div style="margin-top:15px"><button>Add zone</button></div></form></section>
        <section class=card><h2>Add record</h2><form method=post action=/records/add><input type=hidden name=csrf value="{csrf}"><label>Zone</label><select name=zone_id{no_zone}>{zone_options}</select><div class=grid><div><label>Name</label><input name=name value="@" required></div><div><label>Type</label><select name=type>{types}</select></div></div><label>Value</label><input name=value placeholder="192.0.2.10" required><label>TTL <span class=muted>(blank uses zone default)</span></label><input name=ttl type=number min=30><div style="margin-top:15px"><button{no_zone}>Add record</button></div></form></section></div>
        <section class=card style="margin-top:18px"><h2>Records</h2><div style="overflow-x:auto"><table><thead><tr><th>Zone</th><th>Name</th><th>Type</th><th>Value</th><th>TTL</th><th></th></tr></thead><tbody>{record_rows}</tbody></table></div></section>
        <div class=grid style="margin-top:18px"><section class=card><h2>Access and recursion</h2><form method=post action=/settings><input type=hidden name=csrf value="{csrf}"><label><input style="width:auto" type=checkbox name=recursion value=yes{checked}> Enable recursive resolution for trusted clients</label><label>Trusted IPv4/IPv6 networks</label><textarea class=mono name=trusted_networks required>{html.escape(settings.get('trusted_networks',''))}</textarea><p class=muted>Dotlet listens on every interface but answers only these networks.</p><button>Save settings</button></form></section>
        <section class=card><h2>Recent changes</h2><div style="overflow:auto;max-height:350px"><table><thead><tr><th>Time</th><th>User</th><th>Action</th><th>Detail</th></tr></thead><tbody>{audits}</tbody></table></div></section></div>"""
        self._html(page("Dashboard", body, authenticated=True))

    def _login_page(self, error: str = "") -> None:
        message = f'<div class="flash error">{html.escape(error)}</div>' if error else ""
        body = f"""<section class="card login"><h1>Welcome to Dotlet</h1><p class=muted>Sign in to manage DNS zones and records.</p>{message}<form method=post action=/login><label>Username</label><input name=username autocomplete=username required autofocus><label>Password</label><input name=password type=password autocomplete=current-password required><div style="margin-top:17px"><button>Sign in</button></div></form></section>"""
        self._html(page("Sign in", body))

    def _login(self, form: dict[str, str]) -> None:
        username = form.get("username", "")
        if not self.server.store.authenticate(username, form.get("password", "")):
            time.sleep(0.4)
            self._login_page("Invalid username or password")
            return
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        self.server.sessions[token] = (username, csrf, time.time() + 8 * 3600)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/")
        self.send_header("Set-Cookie", f"dotlet_session={token}; Path=/; HttpOnly; SameSite=Strict")
        self.end_headers()

    def _logout(self) -> None:
        cookie = self._cookies()
        self.server.sessions.pop(cookie.get("dotlet_session", ""), None)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/login")
        self.send_header("Set-Cookie", "dotlet_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict")
        self.end_headers()

    def _session(self) -> tuple[str, str, float] | None:
        token = self._cookies().get("dotlet_session", "")
        session = self.server.sessions.get(token)
        if not session or session[2] < time.time():
            self.server.sessions.pop(token, None)
            return None
        return session

    def _cookies(self) -> dict[str, str]:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        return {key: morsel.value for key, morsel in cookie.items()}

    def _form(self) -> dict[str, str]:
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 65536)
        except ValueError:
            length = 0
        values = parse_qs(self.rfile.read(length).decode("utf-8", "replace"), keep_blank_values=True)
        return {key: items[-1] for key, items in values.items()}

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def _html(self, content: bytes, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(content)

    def _json(self, value: object) -> None:
        content = json.dumps(value).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dotlet")
    parser.add_argument("--database", default=os.environ.get("DOTLET_DATABASE", "/var/lib/dotlet/dotlet.db"))
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the Dotlet web service")
    serve.add_argument("--listen", default=os.environ.get("DOTLET_LISTEN", "127.0.0.1:8080"))
    password = sub.add_parser("set-password", help="create or update an administrator")
    password.add_argument("username")
    password.add_argument("--password-stdin", action="store_true")
    sub.add_parser("init", help="initialize the database")
    initial = sub.add_parser("init-admin", help="create the first administrator only when no user exists")
    initial.add_argument("username", default="admin", nargs="?")
    args = parser.parse_args(argv)
    store = Store(args.database)
    store.initialize()
    if args.command == "init":
        return 0
    if args.command == "init-admin":
        if store.has_users():
            return 0
        generated = random_password()
        store.set_password(args.username, generated)
        print(generated)
        return 0
    if args.command == "set-password":
        entered = sys.stdin.readline().rstrip("\n") if args.password_stdin else random_password()
        store.set_password(args.username, entered)
        if not args.password_stdin:
            print(entered)
        return 0
    host, port = args.listen.rsplit(":", 1)
    command = os.environ.get("DOTLET_APPLY_COMMAND", "sudo -n /usr/libexec/dotlet-apply").split()
    server = DotletServer((host, int(port)), store, command)
    print(f"Dotlet {__version__} listening on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
