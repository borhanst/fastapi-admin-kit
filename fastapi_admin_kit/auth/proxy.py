"""Client-IP resolution behind reverse proxies.

By default only the socket peer address is trusted. ``X-Forwarded-For`` is
honoured **only** when the immediate peer is itself a configured trusted
proxy (``AuthConfig(trusted_proxies=[...])``). Without that configuration the
header is attacker-controlled data and must be ignored — otherwise any client
can rotate its rate-limit bucket per request by sending a fresh XFF value.

Entries may be single IPs (``"10.0.0.5"``) or CIDR networks
(``"10.0.0.0/8"``, ``"fd00::/8"``).
"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import Request

UNKNOWN_IP = "unknown"


def parse_trusted_proxies(entries: Any) -> tuple[Any, ...]:
    """Parse config entries into ``ipaddress`` objects (addresses or networks).

    Invalid entries are skipped rather than raising — a typo in a proxy list
    must never take down request handling.
    """
    parsed: list[Any] = []
    for entry in entries or []:
        text = str(entry).strip()
        if not text:
            continue
        try:
            if "/" in text:
                parsed.append(ipaddress.ip_network(text, strict=False))
            else:
                parsed.append(ipaddress.ip_address(text))
        except ValueError:
            continue
    return tuple(parsed)


def get_trusted_proxies(request: Request) -> tuple[Any, ...]:
    """Read ``trusted_proxies`` from app state.

    Supports both the wired dict form (``app.state.admin_config``) and a raw
    ``AdminConfig`` object.
    """
    state = getattr(getattr(request, "app", None), "state", None)
    config = getattr(state, "admin_config", None)
    if isinstance(config, dict):
        entries = config.get("trusted_proxies")
    else:
        entries = getattr(getattr(config, "auth", None), "trusted_proxies", None)
    return parse_trusted_proxies(entries)


def is_trusted(host: str, trusted: tuple[Any, ...]) -> bool:
    """True when *host* is one of the trusted addresses / inside a network."""
    try:
        addr = ipaddress.ip_address(str(host))
    except ValueError:
        return False
    for entry in trusted:
        if isinstance(entry, ipaddress.IPv4Network | ipaddress.IPv6Network):
            if addr in entry:
                return True
        elif addr == entry:
            return True
    return False


def get_client_ip(request: Request) -> str:
    """Resolve the client IP for rate limiting and audit records.

    Resolution rules:

    1. Default: the socket peer address (``request.client.host``).
    2. ``X-Forwarded-For`` is considered ONLY when the peer matches
       ``trusted_proxies``. The chain is walked right-to-left, skipping
       trusted hops; the first untrusted address wins (the client as seen by
       the leftmost trusted proxy).
    3. When every entry in the chain is trusted (or nothing parseable
       remains) fall back to the peer address.
    """
    peer = request.client.host if request.client else UNKNOWN_IP
    trusted = get_trusted_proxies(request)
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded or not trusted or not is_trusted(peer, trusted):
        return peer

    for candidate in reversed([c.strip() for c in forwarded.split(",") if c.strip()]):
        if is_trusted(candidate, trusted):
            continue
        return candidate
    return peer
