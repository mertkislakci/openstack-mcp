"""
OpenStack Core / Cluster Management Functions

Public API
----------
get_service_status – probe each OpenStack service and return availability +
                     detailed counts; optionally scoped to one service name.

Internal helpers
----------------
_ts(obj, attr)              – safe ISO-8601 timestamp
_heat_check(conn)           – probe Heat via SDK service catalog, no raw HTTP
_get_instance_resources     – aggregate vCPU/RAM from active instances (replaces
                               2× duplicate flavor-lookup loops)
_service_endpoint(conn, svc)– resolve endpoint from SDK service catalog
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..connection import get_openstack_connection

logger = logging.getLogger(__name__)

# Services probed by default
_SUPPORTED_SERVICES: tuple[str, ...] = (
    "compute", "network", "volume", "image", "identity", "orchestration",
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ts() -> str:
    """Return current UTC time as an ISO-8601 string."""
    import datetime
    return datetime.datetime.utcnow().isoformat() + "Z"


def _service_endpoint(conn: Any, service_type: str) -> str | None:
    """Return the public endpoint for *service_type* from the SDK catalog."""
    try:
        return conn.endpoint_for(service_type=service_type, interface="public")
    except Exception:
        return None


def _heat_check(conn: Any) -> dict[str, Any]:
    """Probe the Heat (orchestration) service via the OpenStack SDK.

    Uses the SDK's ``orchestration`` proxy rather than raw ``requests``
    so that auth, endpoint discovery, and TLS are handled automatically.
    Returns a status dict compatible with the other per-service dicts.
    """
    result: dict[str, Any] = {
        "available": False,
        "endpoint":  None,
        "details":   {},
        "last_check": _ts(),
    }
    try:
        stacks = list(conn.orchestration.stacks())
        result["available"] = True
        result["endpoint"]  = _service_endpoint(conn, "orchestration")

        stack_statuses: dict[str, int] = {}
        for s in stacks:
            st = getattr(s, "stack_status", "UNKNOWN")
            stack_statuses[st] = stack_statuses.get(st, 0) + 1

        # Engine health (admin only — silently skip if forbidden)
        engines: dict[str, Any] = {}
        try:
            svc_list = list(conn.orchestration.services())
            up   = sum(1 for s in svc_list if getattr(s, "status", "") == "up")
            down = len(svc_list) - up
            engines = {
                "total": len(svc_list),
                "up":    up,
                "down":  down,
                "summary": f"{up}/{len(svc_list)} engines up",
            }
        except Exception:
            engines = {"summary": "engines status unavailable (admin required)"}

        result["details"] = {
            "stacks":         len(stacks),
            "stack_statuses": stack_statuses,
            "engines":        engines,
            "api_version":    "v1",
        }

    except Exception as exc:
        result["error"] = str(exc)

    return result


def _get_instance_resources(conn: Any, instances: list) -> tuple[int, int]:
    """Return ``(total_vcpus_used, total_ram_mb_used)`` by summing flavour
    data across *instances*.

    This is a single helper that replaces the 2× duplicate flavour-lookup
    loops that previously appeared in the hypervisor and quota sections.
    """
    vcpus_used = 0
    ram_mb_used = 0

    # Build a flavour cache to avoid repeated API calls for the same flavour
    flavor_cache: dict[str, Any] = {}

    for server in instances:
        try:
            flavor_id: str | None = None
            raw_flavor = getattr(server, "flavor", None)
            if isinstance(raw_flavor, dict):
                flavor_id = raw_flavor.get("id")
            elif raw_flavor is not None:
                flavor_id = getattr(raw_flavor, "id", None)

            if not flavor_id:
                continue

            if flavor_id not in flavor_cache:
                try:
                    flavor_cache[flavor_id] = conn.compute.get_flavor(flavor_id)
                except Exception:
                    # Deleted / private flavour — try listing as fallback
                    flavor_cache[flavor_id] = None
                    for f in conn.compute.flavors():
                        if f.id == flavor_id or getattr(f, "name", "") == flavor_id:
                            flavor_cache[flavor_id] = f
                            break

            flavor = flavor_cache.get(flavor_id)
            if flavor:
                vcpus_used  += getattr(flavor, "vcpus", 0) or 0
                ram_mb_used += getattr(flavor, "ram",   0) or 0

        except Exception as exc:
            logger.warning("Could not resolve resources for server %s: %s",
                           getattr(server, "id", "?"), exc)

    return vcpus_used, ram_mb_used


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_service_status(service_name: str = "") -> dict[str, Any]:
    """Probe OpenStack service availability and return structured status.

    Args:
        service_name: One of ``compute``, ``network``, ``volume``, ``image``,
                      ``identity``, ``orchestration``.  When empty, all
                      services are probed and a summary dict is returned.

    Returns:
        When *service_name* is empty:
            ``{ "<service>": { "available": bool, "endpoint": str|None,
                                "details": dict, "last_check": str }, … }``

        When *service_name* is given:
            ``{ "success": bool, "service_status": { … } }``
    """
    try:
        conn = get_openstack_connection()

        # ------------------------------------------------------------------ all services
        if not service_name:
            result: dict[str, Any] = {}
            for svc in _SUPPORTED_SERVICES:
                result[svc] = _probe_service(conn, svc)
            return result

        # ------------------------------------------------------------------ single service
        service_name = service_name.lower()
        if service_name not in _SUPPORTED_SERVICES:
            return {
                "success":            False,
                "error":              f"Unsupported service: {service_name!r}",
                "supported_services": list(_SUPPORTED_SERVICES),
            }

        status = _probe_service(conn, service_name)
        return {"success": status.get("available", False), "service_status": status}

    except Exception as exc:
        logger.error("get_service_status failed: %s", exc)
        return {
            "success": False,
            "error":   str(exc),
            "service": service_name or "all",
        }


def _probe_service(conn: Any, service: str) -> dict[str, Any]:
    """Probe a single *service* and return a status dict.

    Never raises — errors are captured in the returned dict.
    """
    t0 = time.monotonic()
    base: dict[str, Any] = {
        "available":  False,
        "endpoint":   _service_endpoint(conn, service),
        "details":    {},
        "last_check": _ts(),
    }

    try:
        if service == "compute":
            hypervisors = list(conn.compute.hypervisors())
            services    = list(conn.compute.services())
            flavors     = list(conn.compute.flavors())
            instances   = list(conn.compute.servers(all_projects=False))
            vcpus_used, ram_mb_used = _get_instance_resources(conn, instances)
            base["available"] = True
            base["details"] = {
                "hypervisors":      len(hypervisors),
                "compute_services": len(services),
                "flavors":          len(flavors),
                "instances":        len(instances),
                "vcpus_used":       vcpus_used,
                "ram_mb_used":      ram_mb_used,
            }

        elif service == "network":
            networks = list(conn.network.networks())
            agents   = list(conn.network.agents())
            base["available"] = True
            base["details"] = {
                "networks":         len(networks),
                "agents":           len(agents),
                "external_networks": sum(1 for n in networks if getattr(n, "is_router_external", False)),
                "private_networks":  sum(1 for n in networks if not getattr(n, "is_router_external", False)),
            }

        elif service == "volume":
            volumes      = list(conn.volume.volumes())
            volume_types = list(conn.volume.types())
            base["available"] = True
            base["details"] = {
                "volumes":           len(volumes),
                "volume_types":      len(volume_types),
                "available_volumes": sum(1 for v in volumes if v.status == "available"),
                "in_use_volumes":    sum(1 for v in volumes if v.status == "in-use"),
            }

        elif service == "image":
            images = list(conn.image.images())
            base["available"] = True
            base["details"] = {
                "images":         len(images),
                "active_images":  sum(1 for i in images if i.status == "active"),
                "public_images":  sum(1 for i in images if getattr(i, "visibility", "") == "public"),
                "private_images": sum(1 for i in images if getattr(i, "visibility", "") == "private"),
            }

        elif service == "identity":
            projects = list(conn.identity.projects())
            users    = list(conn.identity.users())
            roles    = list(conn.identity.roles())
            base["available"] = True
            base["details"] = {
                "projects":         len(projects),
                "enabled_projects": sum(1 for p in projects if p.is_enabled),
                "users":            len(users),
                "roles":            len(roles),
            }

        elif service == "orchestration":
            heat_result = _heat_check(conn)
            base.update(heat_result)  # merges available, details, error

    except Exception as exc:
        base["available"] = False
        base["error"]     = str(exc)

    base["probe_seconds"] = round(time.monotonic() - t0, 3)
    return base
