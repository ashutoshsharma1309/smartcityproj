"""CKAN client for the OpenCity Urban Data Portal.

Resources are addressed by package and resource id, and the download URL is
resolved at run time. OpenCity's download URLs embed a content hash, so they
change whenever a publisher re-uploads a file — pinning them in the catalogue
would produce silent 404s months later. The ids are stable.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.exceptions import ExternalServiceError
from app.core.logging import get_logger

logger = get_logger(__name__)


class CKANClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def package_show(self, package_id: str) -> dict[str, Any]:
        url = f"{self.base_url}/api/3/action/package_show"
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
            try:
                response = await client.get(url, params={"id": package_id})
                response.raise_for_status()
                payload = response.json()
            except httpx.HTTPError as exc:
                raise ExternalServiceError(
                    f"CKAN request failed for package '{package_id}'.",
                    details={"url": url, "error": str(exc)},
                ) from exc

        if not payload.get("success"):
            raise ExternalServiceError(
                f"CKAN reported failure for package '{package_id}'.",
                details={"response": str(payload)[:400]},
            )
        return payload["result"]

    async def resource_url(self, package_id: str, resource_id: str) -> str:
        """Resolve the current download URL for a resource id."""
        package = await self.package_show(package_id)
        for resource in package.get("resources", []):
            if resource.get("id") == resource_id:
                url = resource.get("url")
                if not url:
                    raise ExternalServiceError(
                        f"Resource '{resource_id}' has no download URL.",
                        details={"package": package_id},
                    )
                logger.info(
                    "ckan_resource_resolved",
                    package=package_id,
                    resource=resource_id,
                    format=resource.get("format"),
                )
                return str(url)

        available = [r.get("id") for r in package.get("resources", [])]
        raise ExternalServiceError(
            f"Resource '{resource_id}' not found in package '{package_id}'.",
            details={"available_resource_ids": available[:20]},
        )

    async def package_license(self, package_id: str) -> str | None:
        return (await self.package_show(package_id)).get("license_title")
