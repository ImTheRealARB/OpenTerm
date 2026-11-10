"""One outbound-network guard (server-side request forgery, SSRF): which addresses a user-influenced URL may reach.

Used by the webhook channel (address literals only, no network) and by the AI web tools (`read_url`: resolve the name here, check every address,
then connect to the address we checked). A name that points inside this machine or its network is refused: loopback, private ranges, link-local
(cloud metadata 169.254.169.254), carrier-grade NAT 100.64/10, multicast, reserved and unspecified addresses, and the IPv6 forms of all of them,
including IPv4 hidden in IPv4-mapped (::ffff:127.0.0.1), NAT64, 6to4 and Teredo addresses.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

IP = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], Awaitable[list[str]]]  # (host, port) -> addresses; tests pass a fake, nothing else touches DNS

CGNAT = ipaddress.ip_network("100.64.0.0/10")  # carrier-grade NAT: not "global", but spelled out so the rule is visible
NAT64 = ipaddress.ip_network("64:ff9b::/96")
LOCAL_SUFFIXES = (".localhost", ".internal", ".local", ".localdomain", ".home.arpa", ".lan", ".intranet", ".corp")


class Blocked(ValueError):
    """The URL or an address it resolves to is not allowed. The message is safe to show to the user and the model."""


def _embedded_v4(ip: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    out = []
    if ip.ipv4_mapped:
        out.append(ip.ipv4_mapped)
    if ip.sixtofour:
        out.append(ip.sixtofour)
    if ip.teredo:
        out.extend(ip.teredo)  # (server, client)
    if ip in NAT64:
        out.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    if ip.packed[:12] == b"\x00" * 12 and int(ip) > 1:  # deprecated IPv4-compatible ::a.b.c.d
        out.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return out


def blocked_ip(ip: IP) -> bool:
    """True when this address must not be contacted."""
    if isinstance(ip, ipaddress.IPv6Address) and any(blocked_ip(v4) for v4 in _embedded_v4(ip)):
        return True
    if isinstance(ip, ipaddress.IPv4Address) and ip in CGNAT:
        return True
    return (not ip.is_global or ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast
            or ip.is_reserved or ip.is_unspecified or getattr(ip, "is_site_local", False))


def parse_host_literal(host: str) -> IP | None:
    """An IP address written as a literal, including the legacy IPv4 spellings browsers accept (decimal 2130706433, octal 0177.0.0.1,
    hex 0x7f.1, short 127.1). None when `host` is a name."""
    h = host.strip("[]")
    try:
        return ipaddress.ip_address(h.split("%", 1)[0])
    except ValueError:
        pass
    if h and all(c in "0123456789abcdefABCDEFxX." for c in h) and any(c.isdigit() for c in h) and ":" not in h:
        try:
            return ipaddress.IPv4Address(socket.inet_aton(h))  # inet_aton reads decimal, octal, hex and short forms the way a browser does
        except OSError:
            pass
    return None


def private_name(host: str) -> bool:
    h = host.lower().rstrip(".")
    return h == "localhost" or "." not in h or h.endswith(LOCAL_SUFFIXES)


def private_host(host: str) -> bool:
    """Webhook-style check with no network: a well-known local name or an address literal that is not public."""
    h = host.lower().rstrip(".")
    if h == "localhost" or h.endswith(LOCAL_SUFFIXES[:3]):
        return True
    ip = parse_host_literal(h)
    return blocked_ip(ip) if ip is not None else False


async def system_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(i[4][0] for i in infos))


async def public_addresses(host: str, port: int, resolver: Resolver | None = None) -> list[IP]:
    """The addresses to connect to for `host`: every one of them public, else Blocked. A name that resolves to even one private address is
    refused (a mixed answer is how a rebinding attack starts)."""
    lit = parse_host_literal(host)
    if lit is not None:
        if blocked_ip(lit):
            raise Blocked("THAT ADDRESS IS ON A PRIVATE OR RESERVED NETWORK")
        return [lit]
    if private_name(host):
        raise Blocked("THAT HOST NAME IS LOCAL OR PRIVATE")
    try:
        raw = await (resolver or system_resolver)(host, port)
    except (OSError, UnicodeError) as e:
        raise Blocked(f"COULD NOT RESOLVE THE HOST ({type(e).__name__})") from None
    ips: list[IP] = []
    for a in raw:
        try:
            ips.append(ipaddress.ip_address(a.split("%", 1)[0]))
        except ValueError:
            raise Blocked("THE HOST RESOLVED TO AN INVALID ADDRESS") from None
    if not ips:
        raise Blocked("THE HOST DID NOT RESOLVE")
    if any(blocked_ip(i) for i in ips):
        raise Blocked("THE HOST RESOLVES TO A PRIVATE OR RESERVED ADDRESS")
    return ips


def check_public_url(url: str, ports: tuple[int, ...] = (80, 443)) -> tuple[str, str, int]:
    """Shape checks with no network: http or https, a host, no credentials, an allowed port. Returns (scheme, host, port)."""
    if len(url) > 2000 or any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise Blocked("THE URL IS TOO LONG OR HAS SPACES OR CONTROL CHARACTERS")
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError:
        raise Blocked("THE URL IS NOT VALID") from None
    if u.scheme not in ("http", "https"):
        raise Blocked("ONLY http AND https URLS ARE ALLOWED")
    if not u.hostname:
        raise Blocked("THE URL HAS NO HOST")
    if u.username is not None or u.password is not None:
        raise Blocked("URLS WITH A USER NAME OR PASSWORD ARE NOT ALLOWED")
    port = port or (443 if u.scheme == "https" else 80)
    if port not in ports:
        raise Blocked(f"PORT {port} IS NOT ALLOWED (ONLY {' AND '.join(map(str, ports))})")
    return u.scheme, u.hostname.lower().rstrip("."), port
