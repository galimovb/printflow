"""Seller photo downloads from the WB CDN with a mirror fallback."""

import asyncio
import re
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit, urlunsplit

import httpx

from .catalog import basket_host_for_nm

MIRROR_DOMAIN = ".wbcontent.net"
NATIVE_DOMAIN = ".wbbasket.ru"
# Highest volume covered by the static basket map in catalog.py.
STATIC_MAP_VOLUME_LIMIT = 14213


class CdnDownloader:
    """One shared connection limit for all cards: hundreds of parallel requests make the CDN drop them."""

    def __init__(self, limit: int, observed_images: Callable[[], Iterable[str]]):
        self.slots = asyncio.Semaphore(max(1, limit))
        self.failed_hosts: set[str] = set()
        self.observed_images = observed_images
        self.volume_hosts: dict[str, str] | None = None

    async def fetch(self, url: str, attempts: int = 3) -> bytes:
        async with self.slots:
            for attempt in range(attempts):
                try:
                    return await self.fetch_once(url)
                except httpx.TransportError:
                    if attempt == attempts - 1:
                        raise
                    await asyncio.sleep(1 + attempt * 2)

    async def fetch_once(self, url: str) -> bytes:
        parts = urlsplit(url)
        mirror = self.mirror(parts)
        async with httpx.AsyncClient(timeout=20 if mirror else 60, follow_redirects=True) as client:
            try:
                target = mirror if mirror and parts.hostname in self.failed_hosts else url
                response = await client.get(target)
                response.raise_for_status()
            except (httpx.TransportError, httpx.HTTPStatusError):
                if not mirror:
                    raise
                # Some networks cannot reach wbbasket.ru; the same paths are served by the mirror.
                self.failed_hosts.add(parts.hostname)
                response = await client.get(mirror)
                response.raise_for_status()
            return response.content

    def mirror(self, parts) -> str | None:
        host = parts.hostname or ""
        if host.startswith("basket-") and host.endswith(NATIVE_DOMAIN):
            return urlunsplit(parts._replace(netloc=host.replace(NATIVE_DOMAIN, MIRROR_DOMAIN)))
        if host.endswith(".geobasket.ru"):
            match = re.search(r"/part\d+/(\d+)/images/", parts.path)
            if match:
                mirror_host = self.volume_host(int(match[1]))
                if mirror_host:
                    return urlunsplit(parts._replace(netloc=mirror_host))
        return None

    def volume_host(self, nm_id: int) -> str | None:
        """Prefer the CDN host actually observed for this volume; the static map misses new IDs."""
        if self.volume_hosts is None:
            self.volume_hosts = {}
            for candidate in self.observed_images():
                observed = urlsplit(candidate)
                volume = re.match(r"/vol(\d+)/", observed.path)
                if volume and re.fullmatch(r"basket-\d+\.(?:wbbasket\.ru|wbcontent\.net)", observed.hostname or ""):
                    self.volume_hosts[volume[1]] = observed.hostname.replace(NATIVE_DOMAIN, MIRROR_DOMAIN)
        volume = nm_id // 100_000
        host = self.volume_hosts.get(str(volume))
        if not host and volume <= STATIC_MAP_VOLUME_LIMIT:
            host = basket_host_for_nm(nm_id).replace(NATIVE_DOMAIN, MIRROR_DOMAIN)
        return host
