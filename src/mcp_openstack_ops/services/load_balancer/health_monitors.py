"""
Load Balancer Health Monitor Management (Octavia)

Public API
----------
get_load_balancer_health_monitors  – list monitors, optionally filtered by pool
set_load_balancer_health_monitor   – create / delete / show / update a monitor

Internal helpers
----------------
_ts(obj, attr)         – safe ISO-8601 timestamp string
_build_monitor_dict    – normalises raw SDK HealthMonitor objects
_find_pool(conn, ...)  – find-or-404 for pools  (replaces 2× manual loop)
_find_monitor(conn, …) – find-or-404 for monitors (replaces 3× manual loop)
"""

from __future__ import annotations

import logging
from typing import Any

from ...connection import get_openstack_connection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALL_ACTIONS:   frozenset[str] = frozenset({"create", "delete", "show", "update"})
_WRITE_ACTIONS: frozenset[str] = frozenset({"create", "delete", "update"})

# Types that support HTTP-specific parameters
_HTTP_TYPES: frozenset[str] = frozenset({"HTTP", "HTTPS"})

# Fields that may be updated (None means "caller did not supply it")
_UPDATE_FIELDS: frozenset[str] = frozenset({
    "name", "delay", "timeout", "max_retries", "max_retries_down",
    "admin_state_up", "http_method", "url_path", "expected_codes",
})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ts(obj: Any, attr: str) -> str | None:
    """Return ISO-8601 string for *attr* on *obj*, or None if absent/None."""
    val = getattr(obj, attr, None)
    return str(val) if val is not None else None


def _build_monitor_dict(monitor: Any) -> dict[str, Any]:
    """Return a normalised dict from a raw SDK HealthMonitor object."""
    return {
        "id":                  monitor.id,
        "name":                getattr(monitor, "name", None),
        "type":                monitor.type,
        "delay":               monitor.delay,
        "timeout":             monitor.timeout,
        "max_retries":         monitor.max_retries,
        "max_retries_down":    getattr(monitor, "max_retries_down", None),
        "admin_state_up":      monitor.admin_state_up,
        "provisioning_status": monitor.provisioning_status,
        "operating_status":    monitor.operating_status,
        "pool_id":             getattr(monitor, "pool_id", None),
        "http_method":         getattr(monitor, "http_method", None),
        "url_path":            getattr(monitor, "url_path", None),
        "expected_codes":      getattr(monitor, "expected_codes", None),
        "created_at":          _ts(monitor, "created_at"),
        "updated_at":          _ts(monitor, "updated_at"),
    }


def _find_pool(conn: Any, pool_name_or_id: str) -> tuple[Any | None, dict | None]:
    """Return ``(pool, None)`` or ``(None, error_dict)``."""
    # SDK find_pool resolves both name and ID
    pool = conn.load_balancer.find_pool(pool_name_or_id)
    if pool is None:
        return None, {"success": False, "message": f"Pool not found: {pool_name_or_id}"}
    return pool, None


def _find_monitor(conn: Any, monitor_name_or_id: str) -> tuple[Any | None, dict | None]:
    """Return ``(monitor, None)`` or ``(None, error_dict)``.

    Octavia SDK does not have a dedicated ``find_health_monitor()`` so we
    iterate once and match on UUID prefix/exact match or name.
    """
    for hm in conn.load_balancer.health_monitors():
        if hm.id == monitor_name_or_id or getattr(hm, "name", "") == monitor_name_or_id:
            return hm, None
    return None, {
        "success": False,
        "message": f"Health monitor not found: {monitor_name_or_id}",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_load_balancer_health_monitors(pool_name_or_id: str = "") -> dict[str, Any]:
    """List health monitors, optionally filtered to a single pool.

    Args:
        pool_name_or_id: Pool name or UUID.  When empty all visible monitors
                         are returned.

    Returns:
        ``{'success': True, 'health_monitors': [...], 'monitor_count': N}``
    """
    try:
        conn = get_openstack_connection()

        pool_id: str | None = None
        if pool_name_or_id:
            pool, err = _find_pool(conn, pool_name_or_id)
            if err:
                return err
            pool_id = pool.id

        monitors = [
            _build_monitor_dict(hm)
            for hm in conn.load_balancer.health_monitors()
            if pool_id is None or getattr(hm, "pool_id", None) == pool_id
        ]

        return {
            "success":       True,
            "health_monitors": monitors,
            "monitor_count": len(monitors),
            "filter":        f"pool: {pool_name_or_id}" if pool_name_or_id else "all",
        }

    except Exception as exc:
        logger.error("Failed to get health monitors: %s", exc)
        return {"success": False, "message": f"Failed to get health monitors: {exc}"}


def set_load_balancer_health_monitor(action: str, **kwargs) -> dict[str, Any]:
    """Manage load-balancer health monitor lifecycle.

    Supported *action* values
    -------------------------
    ``create`` – Create a new health monitor on a pool.
    ``delete`` – Delete a health monitor by name or ID.
    ``show``   – Return full details for one health monitor.
    ``update`` – Modify specific fields; only supplied fields are changed.

    Create parameters (via **kwargs)
    ---------------------------------
    pool_name_or_id : str  – Target pool name or UUID (required).
    monitor_type    : str  – ``HTTP``, ``HTTPS``, ``TCP``, ``PING``,
                             ``UDP-CONNECT``, or ``SCTP`` (default: ``HTTP``).
    delay           : int  – Seconds between checks (default: 10).
    timeout         : int  – Check timeout in seconds (default: 5).
    max_retries     : int  – Retries before UNHEALTHY (default: 3).
    max_retries_down: int  – Retries before DOWN (default: 3).
    admin_state_up  : bool – Enabled state (default: True).
    name            : str  – Optional monitor name.
    http_method     : str  – HTTP verb for HTTP/HTTPS (default: ``GET``).
    url_path        : str  – Path for HTTP/HTTPS (default: ``/``).
    expected_codes  : str  – Accepted codes for HTTP/HTTPS (default: ``200``).

    Update parameters
    -----------------
    monitor_name_or_id : str – Target monitor (required).
    Any subset of the create fields above; only supplied keys are patched.

    Returns:
        Action-specific success dict or ``{'success': False, 'message': '...'}``
    """
    if action not in _ALL_ACTIONS:
        return {
            "success": False,
            "message": (
                f'Unknown action "{action}". '
                f"Supported: {sorted(_ALL_ACTIONS)}"
            ),
        }

    try:
        conn = get_openstack_connection()

        # ------------------------------------------------------------------ create
        if action == "create":
            pool_name_or_id = kwargs.get("pool_name_or_id", "")
            if not pool_name_or_id:
                return {"success": False, "message": "pool_name_or_id is required for create"}

            pool, err = _find_pool(conn, pool_name_or_id)
            if err:
                return err

            monitor_type = kwargs.get("monitor_type", "HTTP").upper()

            attrs: dict[str, Any] = {
                "pool_id":          pool.id,
                "type":             monitor_type,
                "delay":            kwargs.get("delay", 10),
                "timeout":          kwargs.get("timeout", 5),
                "max_retries":      kwargs.get("max_retries", 3),
                "max_retries_down": kwargs.get("max_retries_down", 3),
                "admin_state_up":   kwargs.get("admin_state_up", True),
            }

            if kwargs.get("name"):
                attrs["name"] = kwargs["name"]

            if monitor_type in _HTTP_TYPES:
                attrs["http_method"]    = kwargs.get("http_method", "GET").upper()
                attrs["url_path"]       = kwargs.get("url_path", "/")
                attrs["expected_codes"] = kwargs.get("expected_codes", "200")

            monitor = conn.load_balancer.create_health_monitor(**attrs)
            return {
                "success":       True,
                "message":       "Health monitor created successfully",
                "health_monitor": _build_monitor_dict(monitor),
            }

        # ------------------------------------------------------------------ delete
        if action == "delete":
            monitor_name_or_id = kwargs.get("monitor_name_or_id", "")
            if not monitor_name_or_id:
                return {"success": False, "message": "monitor_name_or_id is required for delete"}

            monitor, err = _find_monitor(conn, monitor_name_or_id)
            if err:
                return err

            conn.load_balancer.delete_health_monitor(monitor)
            return {"success": True, "message": "Health monitor deleted successfully"}

        # ------------------------------------------------------------------ show
        if action == "show":
            monitor_name_or_id = kwargs.get("monitor_name_or_id", "")
            if not monitor_name_or_id:
                return {"success": False, "message": "monitor_name_or_id is required for show"}

            monitor, err = _find_monitor(conn, monitor_name_or_id)
            if err:
                return err

            return {"success": True, "health_monitor": _build_monitor_dict(monitor)}

        # ------------------------------------------------------------------ update
        if action == "update":
            monitor_name_or_id = kwargs.get("monitor_name_or_id", "")
            if not monitor_name_or_id:
                return {"success": False, "message": "monitor_name_or_id is required for update"}

            monitor, err = _find_monitor(conn, monitor_name_or_id)
            if err:
                return err

            # Only include fields the caller explicitly supplied
            update_attrs = {
                k: kwargs[k] for k in _UPDATE_FIELDS if k in kwargs
            }

            # HTTP/HTTPS-specific fields are only meaningful for matching types
            if monitor.type not in _HTTP_TYPES:
                for http_key in ("http_method", "url_path", "expected_codes"):
                    update_attrs.pop(http_key, None)

            if not update_attrs:
                return {
                    "success": False,
                    "message": f"No updatable fields provided. Supported: {sorted(_UPDATE_FIELDS)}",
                }

            updated = conn.load_balancer.update_health_monitor(monitor, **update_attrs)
            return {
                "success":       True,
                "message":       "Health monitor updated successfully",
                "health_monitor": _build_monitor_dict(updated),
            }

    except Exception as exc:
        logger.error("set_load_balancer_health_monitor(%s) failed: %s", action, exc)
        return {"success": False, "message": f"Failed to {action} health monitor: {exc}"}
