"""
Network Resilience & Global DNS Fallback Module for Project Nabih.
Automatically resolves domains via Google DNS (8.8.8.8) and Cloudflare DNS (1.1.1.1)
whenever local ISP DNS servers (e.g. TE-Data/WE DNS in Egypt) drop or fail.
"""

import socket
import anyio
import dns.resolver
from loguru import logger

# Initialize independent DNS resolver using Google and Cloudflare Anycast servers
_dns_resolver = dns.resolver.Resolver(configure=False)
_dns_resolver.nameservers = ["8.8.8.8", "1.1.1.1"]
_dns_resolver.timeout = 3.0
_dns_resolver.lifetime = 5.0

# -----------------------------------------------------------------------------
# 1. Patch anyio.connect_tcp (Used by httpx2, httpcore2, and AsyncOpenAI)
# -----------------------------------------------------------------------------
_orig_anyio_connect_tcp = anyio.connect_tcp


async def _resilient_connect_tcp(remote_host, remote_port, *args, **kwargs):
    if isinstance(remote_host, str) and not remote_host.replace(".", "").isdigit():
        try:
            answers = _dns_resolver.resolve(remote_host, "A")
            if answers:
                remote_host = answers[0].to_text()
        except Exception:
            pass  # Fallback to default system behavior
    return await _orig_anyio_connect_tcp(remote_host, remote_port, *args, **kwargs)


anyio.connect_tcp = _resilient_connect_tcp


# -----------------------------------------------------------------------------
# 2. Patch socket.getaddrinfo (Used by urllib, requests, and standard sockets)
# -----------------------------------------------------------------------------
_orig_socket_gai = socket.getaddrinfo


def _resilient_socket_gai(host, port, *args, **kwargs):
    try:
        return _orig_socket_gai(host, port, *args, **kwargs)
    except socket.gaierror:
        if host and isinstance(host, str) and not host.replace(".", "").isdigit():
            try:
                answers = _dns_resolver.resolve(host, "A")
                if answers:
                    return _orig_socket_gai(answers[0].to_text(), port, *args, **kwargs)
            except Exception:
                pass
        raise


socket.getaddrinfo = _resilient_socket_gai

logger.debug("[NETWORK RESILIENCE] Global DNS Fallback active (Google 8.8.8.8 / Cloudflare 1.1.1.1).")
