"""
Load Balancer Advanced Management (Octavia)

Covers availability zones, flavors, providers, and per-project quotas.

Public API
----------
get_load_balancer_availability_zones   – list all AZs
set_load_balancer_availability_zone    – create / delete / show an AZ
get_load_balancer_flavors              – list all LB flavors
set_load_balancer_flavor               – create / delete / show a flavor
get_load_balancer_providers            – list all LB providers
get_load_balancer_quotas               – list all quotas, or one by project
set_load_balancer_quota                – update / reset a project quota

Internal helpers
----------------
_build_zone_dict(zone)     – normalise SDK AvailabilityZone objects
_build_flavor_dict(flavor) – normalise SDK Flavor objects
_build_quota_dict(quota)   – normalise SDK Quota objects  (replaces 3× inline dict)
_find_az(conn, name)       – find-or-404 for availability zones
_find_flavor(conn, id)     – find-or-404 for flavors
"""

from __future__ import annotations

import logging
from typing import Any

from ...connection import get_openstack_connection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AZ_ACTIONS:     frozenset[str] = frozenset({"create", "delete", "show"})
_FLAVOR_ACTIONS: frozenset[str] = frozenset({"create", "delete", "show"})
_QUOTA_ACTIONS:  frozenset[str] = frozenset({"update", "reset"})

# Quota resource types recognised by Octavia
_QUOTA_FIELDS: frozenset[str] = frozenset({
    "load_balancer", "listener", "pool", "health_monitor", "member",
})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_zone_dict(zone: Any) -> dict[str, Any]:
    """Normalise a raw SDK AvailabilityZone object."""
    return {
        "name":                          zone.name,
        "description":                   getattr(zone, "description", None),
        "availability_zone_profile_id":  getattr(zone, "availability_zone_profile_id", None),
        "enabled":                       getattr(zone, "enabled", True),
    }


def _build_flavor_dict(flavor: Any) -> dict[str, Any]:
    """Normalise a raw SDK Flavor object."""
    return {
        "id":                flavor.id,
        "name":              flavor.name,
        "description":       getattr(flavor, "description", None),
        "flavor_profile_id": getattr(flavor, "flavor_profile_id", None),
        "enabled":           getattr(flavor, "enabled", True),
    }


def _build_quota_dict(quota: Any, project_id: str | None = None) -> dict[str, Any]:
    """Normalise a raw SDK Quota object.

    -1 means "unlimited" in Octavia; None means "not set / default".
    """
    return {
        "project_id":    project_id or getattr(quota, "project_id", None),
        "load_balancer": getattr(quota, "load_balancer", None),
        "listener":      getattr(quota, "listener", None),
        "pool":          getattr(quota, "pool", None),
        "health_monitor": getattr(quota, "health_monitor", None),
        "member":        getattr(quota, "member", None),
    }


def _find_az(conn: Any, az_name: str) -> tuple[Any | None, dict | None]:
    """Return ``(zone, None)`` or ``(None, error_dict)``."""
    az = conn.load_balancer.find_availability_zone(az_name)
    if az is None:
        return None, {"success": False, "message": f"Availability zone not found: {az_name}"}
    return az, None


def _find_flavor(conn: Any, flavor_name_or_id: str) -> tuple[Any | None, dict | None]:
    """Return ``(flavor, None)`` or ``(None, error_dict)``."""
    flavor = conn.load_balancer.find_flavor(flavor_name_or_id)
    if flavor is None:
        return None, {"success": False, "message": f"Flavor not found: {flavor_name_or_id}"}
    return flavor, None


# ---------------------------------------------------------------------------
# Availability zones
# ---------------------------------------------------------------------------

def get_load_balancer_availability_zones() -> dict[str, Any]:
    """List all Octavia availability zones visible to the caller.

    Returns:
        ``{'success': True, 'availability_zones': [...], 'zone_count': N}``
    """
    try:
        conn = get_openstack_connection()
        zones = [_build_zone_dict(z) for z in conn.load_balancer.availability_zones()]
        return {"success": True, "availability_zones": zones, "zone_count": len(zones)}
    except Exception as exc:
        logger.error("Failed to get availability zones: %s", exc)
        return {"success": False, "message": f"Failed to get availability zones: {exc}"}


def set_load_balancer_availability_zone(action: str, **kwargs) -> dict[str, Any]:
    """Manage Octavia availability zones.

    Supported *action* values
    -------------------------
    ``create`` – Create a new availability zone.
    ``delete`` – Delete an availability zone by name.
    ``show``   – Return full details for one availability zone.

    Create parameters (via **kwargs)
    ---------------------------------
    name                         : str  – Zone name (required).
    availability_zone_profile_id : str  – Profile UUID (required).
    description                  : str  – Optional description.
    enabled                      : bool – Enabled state (default: True).

    Delete / show parameters
    ------------------------
    az_name : str – Zone name (required).
    """
    if action not in _AZ_ACTIONS:
        return {
            "success": False,
            "message": f'Unknown action "{action}". Supported: {sorted(_AZ_ACTIONS)}',
        }

    try:
        conn = get_openstack_connection()

        # ------------------------------------------------------------------ create
        if action == "create":
            name    = kwargs.get("name", "")
            profile = kwargs.get("availability_zone_profile_id", "")
            if not name or not profile:
                return {
                    "success": False,
                    "message": "name and availability_zone_profile_id are required for create",
                }

            params: dict[str, Any] = {
                k: v for k, v in {
                    "name":                         name,
                    "availability_zone_profile_id": profile,
                    "description":                  kwargs.get("description"),
                    "enabled":                      kwargs.get("enabled", True),
                }.items()
                if v is not None and v != ""
            }

            az = conn.load_balancer.create_availability_zone(**params)
            return {
                "success":           True,
                "message":           f"Availability zone created: {az.name}",
                "availability_zone": _build_zone_dict(az),
            }

        # ------------------------------------------------------------------ delete
        if action == "delete":
            az_name = kwargs.get("az_name", "")
            if not az_name:
                return {"success": False, "message": "az_name is required for delete"}

            az, err = _find_az(conn, az_name)
            if err:
                return err

            # Octavia AZs are identified by name, not UUID
            conn.load_balancer.delete_availability_zone(az.name)
            return {"success": True, "message": f"Availability zone deleted: {az.name}"}

        # ------------------------------------------------------------------ show
        if action == "show":
            az_name = kwargs.get("az_name", "")
            if not az_name:
                return {"success": False, "message": "az_name is required for show"}

            az, err = _find_az(conn, az_name)
            if err:
                return err

            return {"success": True, "availability_zone": _build_zone_dict(az)}

    except Exception as exc:
        logger.error("set_load_balancer_availability_zone(%s) failed: %s", action, exc)
        return {"success": False, "message": f"Failed to {action} availability zone: {exc}"}


# ---------------------------------------------------------------------------
# Flavors
# ---------------------------------------------------------------------------

def get_load_balancer_flavors() -> dict[str, Any]:
    """List all Octavia LB flavors.

    Returns:
        ``{'success': True, 'flavors': [...], 'flavor_count': N}``
    """
    try:
        conn = get_openstack_connection()
        flavors = [_build_flavor_dict(f) for f in conn.load_balancer.flavors()]
        return {"success": True, "flavors": flavors, "flavor_count": len(flavors)}
    except Exception as exc:
        logger.error("Failed to get flavors: %s", exc)
        return {"success": False, "message": f"Failed to get flavors: {exc}"}


def set_load_balancer_flavor(action: str, **kwargs) -> dict[str, Any]:
    """Manage Octavia LB flavors.

    Supported *action* values
    -------------------------
    ``create`` – Create a new flavor.
    ``delete`` – Delete a flavor by name or ID.
    ``show``   – Return full details for one flavor.

    Create parameters (via **kwargs)
    ---------------------------------
    name              : str  – Flavor name (required).
    flavor_profile_id : str  – Profile UUID (required).
    description       : str  – Optional description.
    enabled           : bool – Enabled state (default: True).

    Delete / show parameters
    ------------------------
    flavor_name_or_id : str – Flavor name or UUID (required).
    """
    if action not in _FLAVOR_ACTIONS:
        return {
            "success": False,
            "message": f'Unknown action "{action}". Supported: {sorted(_FLAVOR_ACTIONS)}',
        }

    try:
        conn = get_openstack_connection()

        # ------------------------------------------------------------------ create
        if action == "create":
            name       = kwargs.get("name", "")
            profile_id = kwargs.get("flavor_profile_id", "")
            if not name or not profile_id:
                return {
                    "success": False,
                    "message": "name and flavor_profile_id are required for create",
                }

            params: dict[str, Any] = {
                k: v for k, v in {
                    "name":              name,
                    "flavor_profile_id": profile_id,
                    "description":       kwargs.get("description"),
                    "enabled":           kwargs.get("enabled", True),
                }.items()
                if v is not None and v != ""
            }

            flavor = conn.load_balancer.create_flavor(**params)
            return {
                "success": True,
                "message": f"Flavor created: {flavor.name}",
                "flavor":  _build_flavor_dict(flavor),
            }

        # ------------------------------------------------------------------ delete
        if action == "delete":
            flavor_name_or_id = kwargs.get("flavor_name_or_id", "")
            if not flavor_name_or_id:
                return {"success": False, "message": "flavor_name_or_id is required for delete"}

            flavor, err = _find_flavor(conn, flavor_name_or_id)
            if err:
                return err

            conn.load_balancer.delete_flavor(flavor.id)
            return {"success": True, "message": f"Flavor deleted: {flavor.name}"}

        # ------------------------------------------------------------------ show
        if action == "show":
            flavor_name_or_id = kwargs.get("flavor_name_or_id", "")
            if not flavor_name_or_id:
                return {"success": False, "message": "flavor_name_or_id is required for show"}

            flavor, err = _find_flavor(conn, flavor_name_or_id)
            if err:
                return err

            return {"success": True, "flavor": _build_flavor_dict(flavor)}

    except Exception as exc:
        logger.error("set_load_balancer_flavor(%s) failed: %s", action, exc)
        return {"success": False, "message": f"Failed to {action} flavor: {exc}"}


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

def get_load_balancer_providers() -> dict[str, Any]:
    """List all Octavia provider drivers.

    Returns:
        ``{'success': True, 'providers': [...], 'provider_count': N}``
    """
    try:
        conn = get_openstack_connection()
        providers = [
            {"name": p.name, "description": getattr(p, "description", None)}
            for p in conn.load_balancer.providers()
        ]
        return {"success": True, "providers": providers, "provider_count": len(providers)}
    except Exception as exc:
        logger.error("Failed to get providers: %s", exc)
        return {"success": False, "message": f"Failed to get providers: {exc}"}


# ---------------------------------------------------------------------------
# Quotas
# ---------------------------------------------------------------------------

def get_load_balancer_quotas(project_id: str = "") -> dict[str, Any]:
    """Return quota information.

    Args:
        project_id: When supplied return only that project's quota;
                    otherwise list all project quotas.

    Returns:
        ``{'success': True, 'quotas': [...], 'quota_count': N}``
        (single project also uses the list form for a consistent response shape)
    """
    try:
        conn = get_openstack_connection()

        if project_id:
            quota  = conn.load_balancer.get_quota(project_id)
            quotas = [_build_quota_dict(quota, project_id=project_id)]
        else:
            quotas = [_build_quota_dict(q) for q in conn.load_balancer.quotas()]

        return {"success": True, "quotas": quotas, "quota_count": len(quotas)}

    except Exception as exc:
        logger.error("Failed to get quotas: %s", exc)
        return {"success": False, "message": f"Failed to get quotas: {exc}"}


def set_load_balancer_quota(action: str, **kwargs) -> dict[str, Any]:
    """Manage per-project Octavia quotas.

    Supported *action* values
    -------------------------
    ``update`` – Set specific quota limits for a project.
    ``reset``  – Restore all quotas for a project to system defaults.

    Update parameters (via **kwargs)
    ---------------------------------
    project_id    : str – Target project UUID (required).
    load_balancer : int – Max LB count  (-1 = unlimited).
    listener      : int – Max listener count.
    pool          : int – Max pool count.
    health_monitor: int – Max health-monitor count.
    member        : int – Max member count.
    At least one quota field is required for ``update``.

    Reset parameters
    ----------------
    project_id : str – Target project UUID (required).
    """
    if action not in _QUOTA_ACTIONS:
        return {
            "success": False,
            "message": f'Unknown action "{action}". Supported: {sorted(_QUOTA_ACTIONS)}',
        }

    try:
        conn = get_openstack_connection()
        project_id = kwargs.get("project_id", "")

        if not project_id:
            return {"success": False, "message": "project_id is required"}

        # ------------------------------------------------------------------ update
        if action == "update":
            quota_params = {k: kwargs[k] for k in _QUOTA_FIELDS if k in kwargs}
            if not quota_params:
                return {
                    "success": False,
                    "message": (
                        "At least one quota field is required. "
                        f"Supported: {sorted(_QUOTA_FIELDS)}"
                    ),
                }

            updated = conn.load_balancer.update_quota(project_id, **quota_params)
            return {
                "success":  True,
                "message":  f"Quota updated for project: {project_id}",
                "quota":    _build_quota_dict(updated, project_id=project_id),
            }

        # ------------------------------------------------------------------ reset
        if action == "reset":
            conn.load_balancer.delete_quota(project_id)
            return {
                "success": True,
                "message": f"Quota reset to defaults for project: {project_id}",
            }

    except Exception as exc:
        logger.error("set_load_balancer_quota(%s) failed: %s", action, exc)
        return {"success": False, "message": f"Failed to {action} quota: {exc}"}
