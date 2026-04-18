"""Proxy health probe — validates that configured SOCKS/HTTP proxies can
actually reach the Telegram / WhatsApp APIs they exist to tunnel.

Stdlib only. No dependency on httpx / python-telegram-bot so this module is
usable even when those optional libs aren't installed.

The probe performs a real end-to-end test:
  1. TCP connect to the proxy on its host:port.
  2. Speak the proxy protocol (SOCKS5 / SOCKS4 / HTTP CONNECT).
  3. Ask the proxy to open a tunnel to the target host:443.
  4. Measure latency. Close.

A successful probe means the proxy is live AND can reach the target — which is
exactly what we care about (a "connected" proxy that blackholes Telegram
traffic is useless to us).
"""

from __future__ import annotations

import asyncio
import socket
import struct
import time
from dataclasses import dataclass, asdict
from typing import Any
from urllib.parse import urlparse


# Liveness targets per channel. These are the hosts we actually need to reach
# through the proxy; probing a generic site like example.com wouldn't tell us
# whether Telegram's CDN is reachable from the proxy's egress.
DEFAULT_TARGETS: dict[str, tuple[str, int]] = {
    "telegram": ("api.telegram.org", 443),
    "whatsapp": ("web.whatsapp.com", 443),
    "generic": ("1.1.1.1", 443),
}


@dataclass
class ProxyHealth:
    """Result of a single proxy probe."""

    channel: str              # "telegram" / "whatsapp" / ...
    proxy_url: str            # full configured URL (pre-masking)
    configured: bool          # False if no proxy_url is set
    ok: bool                  # True iff the probe succeeded
    latency_ms: int | None    # round-trip time of the probe, null on failure
    error: str | None         # human-readable failure reason when ok=False
    target: str               # "host:port" we tunneled to
    checked_at: float         # unix timestamp of the probe

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Mask credentials in the proxy_url before shipping to dashboards/logs.
        # A raw socks5://user:pass@host shouldn't leak through the API surface.
        d["proxy_url"] = mask_proxy_url(self.proxy_url)
        return d


def mask_proxy_url(url: str) -> str:
    """Strip credentials from a proxy URL for safe display.

    socks5://alice:hunter2@proxy.example:1080 -> socks5://***@proxy.example:1080
    Passes through unchanged if there are no credentials."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        if parsed.username or parsed.password:
            netloc = parsed.hostname or ""
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            masked = f"{parsed.scheme}://***@{netloc}"
            if parsed.path:
                masked += parsed.path
            return masked
    except Exception:
        pass
    return url


async def check_proxy(
    proxy_url: str,
    channel: str = "generic",
    target: tuple[str, int] | None = None,
    timeout: float = 5.0,
) -> ProxyHealth:
    """Probe `proxy_url` by opening a tunnel to `target` through it.

    Returns a ProxyHealth record. Never raises — all errors surface as
    ok=False with a descriptive `error` string. This keeps callers (status
    panels, background pollers) from needing their own try/except.
    """
    host_port = target or DEFAULT_TARGETS.get(channel, DEFAULT_TARGETS["generic"])
    target_str = f"{host_port[0]}:{host_port[1]}"
    now = time.time()

    if not proxy_url or not proxy_url.strip():
        return ProxyHealth(
            channel=channel, proxy_url="", configured=False,
            ok=False, latency_ms=None, error="no proxy configured",
            target=target_str, checked_at=now,
        )

    try:
        parsed = urlparse(proxy_url)
    except Exception as e:
        return ProxyHealth(
            channel=channel, proxy_url=proxy_url, configured=True,
            ok=False, latency_ms=None, error=f"invalid URL: {e}",
            target=target_str, checked_at=now,
        )

    scheme = (parsed.scheme or "").lower()
    proxy_host = parsed.hostname
    proxy_port = parsed.port
    if not proxy_host or not proxy_port:
        return ProxyHealth(
            channel=channel, proxy_url=proxy_url, configured=True,
            ok=False, latency_ms=None, error="URL missing host/port",
            target=target_str, checked_at=now,
        )

    start = time.perf_counter()
    try:
        if scheme in ("socks5", "socks5h"):
            await asyncio.wait_for(
                _probe_socks5(
                    proxy_host, proxy_port,
                    parsed.username, parsed.password,
                    host_port[0], host_port[1],
                ),
                timeout=timeout,
            )
        elif scheme == "socks4":
            await asyncio.wait_for(
                _probe_socks4(
                    proxy_host, proxy_port,
                    host_port[0], host_port[1],
                ),
                timeout=timeout,
            )
        elif scheme in ("http", "https"):
            await asyncio.wait_for(
                _probe_http_connect(
                    proxy_host, proxy_port,
                    parsed.username, parsed.password,
                    host_port[0], host_port[1],
                ),
                timeout=timeout,
            )
        else:
            return ProxyHealth(
                channel=channel, proxy_url=proxy_url, configured=True,
                ok=False, latency_ms=None,
                error=f"unsupported scheme '{scheme}'",
                target=target_str, checked_at=now,
            )
    except asyncio.TimeoutError:
        return ProxyHealth(
            channel=channel, proxy_url=proxy_url, configured=True,
            ok=False, latency_ms=None,
            error=f"timeout after {timeout:.1f}s",
            target=target_str, checked_at=now,
        )
    except ProxyProbeError as e:
        return ProxyHealth(
            channel=channel, proxy_url=proxy_url, configured=True,
            ok=False, latency_ms=None, error=str(e),
            target=target_str, checked_at=now,
        )
    except (OSError, socket.gaierror) as e:
        # DNS failures, connection refused, network unreachable — all OS-level.
        return ProxyHealth(
            channel=channel, proxy_url=proxy_url, configured=True,
            ok=False, latency_ms=None, error=f"network: {e}",
            target=target_str, checked_at=now,
        )
    except Exception as e:  # pragma: no cover — defensive catch-all
        return ProxyHealth(
            channel=channel, proxy_url=proxy_url, configured=True,
            ok=False, latency_ms=None, error=f"unexpected: {e}",
            target=target_str, checked_at=now,
        )

    latency_ms = int((time.perf_counter() - start) * 1000)
    return ProxyHealth(
        channel=channel, proxy_url=proxy_url, configured=True,
        ok=True, latency_ms=latency_ms, error=None,
        target=target_str, checked_at=now,
    )


class ProxyProbeError(Exception):
    """Protocol-level failure from the proxy itself (not a network error)."""


# ----- Protocol implementations ---------------------------------------------


async def _probe_socks5(
    proxy_host: str, proxy_port: int,
    username: str | None, password: str | None,
    target_host: str, target_port: int,
) -> None:
    """SOCKS5 handshake + CONNECT. Closes the socket on success — we only care
    about whether the CONNECT reply is 0x00 (succeeded)."""
    reader, writer = await asyncio.open_connection(proxy_host, proxy_port)
    try:
        # Method negotiation. 0x00 = no-auth, 0x02 = user/pass.
        if username is not None and password is not None:
            writer.write(b"\x05\x02\x00\x02")
        else:
            writer.write(b"\x05\x01\x00")
        await writer.drain()

        resp = await reader.readexactly(2)
        if resp[0] != 0x05:
            raise ProxyProbeError("not a SOCKS5 proxy (bad version byte)")
        method = resp[1]

        if method == 0xFF:
            raise ProxyProbeError("proxy rejected all auth methods")

        if method == 0x02:
            # Username/password sub-negotiation (RFC 1929).
            if username is None or password is None:
                raise ProxyProbeError("proxy requires auth but none supplied")
            u = username.encode("utf-8")
            p = password.encode("utf-8")
            if len(u) > 255 or len(p) > 255:
                raise ProxyProbeError("auth credential too long")
            writer.write(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
            await writer.drain()
            auth_resp = await reader.readexactly(2)
            if auth_resp[1] != 0x00:
                raise ProxyProbeError("proxy auth rejected")
        elif method != 0x00:
            raise ProxyProbeError(f"proxy chose unexpected auth method {method:#x}")

        # CONNECT request, domain-name addressing (ATYP=0x03).
        host_bytes = target_host.encode("idna")
        if len(host_bytes) > 255:
            raise ProxyProbeError("target host too long for SOCKS5")
        req = (
            b"\x05\x01\x00\x03"
            + bytes([len(host_bytes)]) + host_bytes
            + struct.pack("!H", target_port)
        )
        writer.write(req)
        await writer.drain()

        reply = await reader.readexactly(4)
        if reply[0] != 0x05:
            raise ProxyProbeError("bad reply version from proxy")
        rep = reply[1]
        if rep != 0x00:
            raise ProxyProbeError(_socks5_error(rep))

        # Drain the rest of the BND.ADDR/BND.PORT so we don't leave bytes in
        # the socket buffer (not strictly necessary since we close, but keeps
        # the trace clean if the proxy logs short reads).
        atyp = reply[3]
        if atyp == 0x01:
            await reader.readexactly(4 + 2)
        elif atyp == 0x03:
            length = (await reader.readexactly(1))[0]
            await reader.readexactly(length + 2)
        elif atyp == 0x04:
            await reader.readexactly(16 + 2)
        # Unknown ATYP — don't raise, the CONNECT already succeeded.
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


def _socks5_error(code: int) -> str:
    errors = {
        0x01: "general SOCKS server failure",
        0x02: "connection not allowed by ruleset",
        0x03: "network unreachable",
        0x04: "host unreachable",
        0x05: "connection refused by target",
        0x06: "TTL expired",
        0x07: "command not supported",
        0x08: "address type not supported",
    }
    return errors.get(code, f"SOCKS5 rejected (code {code:#x})")


async def _probe_socks4(
    proxy_host: str, proxy_port: int,
    target_host: str, target_port: int,
) -> None:
    """SOCKS4a CONNECT. Uses 0.0.0.x sentinel IP to indicate hostname follows,
    so we don't have to resolve DNS on the client side (matches SOCKS5h
    semantics and keeps DNS traffic off the client network)."""
    reader, writer = await asyncio.open_connection(proxy_host, proxy_port)
    try:
        # VN=4, CD=1 (CONNECT), DSTPORT, DSTIP=0.0.0.1 (4a marker), USERID="", 0x00, HOST, 0x00
        host_bytes = target_host.encode("idna")
        req = (
            b"\x04\x01"
            + struct.pack("!H", target_port)
            + b"\x00\x00\x00\x01"
            + b"\x00"
            + host_bytes
            + b"\x00"
        )
        writer.write(req)
        await writer.drain()
        resp = await reader.readexactly(8)
        if resp[0] != 0x00:
            raise ProxyProbeError("bad SOCKS4 reply version")
        if resp[1] != 0x5A:
            code = resp[1]
            msgs = {
                0x5B: "SOCKS4 rejected (request failed)",
                0x5C: "SOCKS4 rejected (identd unreachable)",
                0x5D: "SOCKS4 rejected (identd user mismatch)",
            }
            raise ProxyProbeError(msgs.get(code, f"SOCKS4 rejected (code {code:#x})"))
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def _probe_http_connect(
    proxy_host: str, proxy_port: int,
    username: str | None, password: str | None,
    target_host: str, target_port: int,
) -> None:
    """HTTP CONNECT tunnel probe. Reads until the end of the status line + an
    empty line, then bails. We don't need the tunneled data — just the 2xx."""
    reader, writer = await asyncio.open_connection(proxy_host, proxy_port)
    try:
        req_lines = [
            f"CONNECT {target_host}:{target_port} HTTP/1.1",
            f"Host: {target_host}:{target_port}",
        ]
        if username is not None and password is not None:
            import base64
            token = base64.b64encode(
                f"{username}:{password}".encode("utf-8")
            ).decode("ascii")
            req_lines.append(f"Proxy-Authorization: Basic {token}")
        req_lines.append("")
        req_lines.append("")
        writer.write("\r\n".join(req_lines).encode("ascii"))
        await writer.drain()

        # Read the status line (up to \r\n) — keep it short so a hostile proxy
        # can't stream megabytes at us.
        status_line = await reader.readline()
        if not status_line:
            raise ProxyProbeError("proxy closed connection without reply")
        parts = status_line.decode("iso-8859-1", errors="replace").split()
        if len(parts) < 2:
            raise ProxyProbeError(f"malformed status line: {status_line!r}")
        try:
            code = int(parts[1])
        except ValueError:
            raise ProxyProbeError(f"non-numeric status code: {parts[1]!r}")
        if code // 100 != 2:
            raise ProxyProbeError(f"HTTP proxy returned {code}")

        # Drain remaining headers up to the empty line so we leave the socket
        # clean before closing. Bounded to prevent a runaway proxy.
        for _ in range(64):
            line = await reader.readline()
            if not line or line in (b"\r\n", b"\n"):
                break
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
