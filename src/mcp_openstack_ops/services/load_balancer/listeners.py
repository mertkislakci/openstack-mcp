"""
Load Balancer Listener Management (Octavia)

Public API
----------
get_load_balancer_listeners  – list listeners for a load balancer
set_load_balancer_listener   – create / delete / update / unset / show / stats

Internal helpers
----------------
_ts(obj, attr)          – safe ISO-8601 timestamp string
_build_listener_dict    – normalises raw SDK Listener objects  (replaces 3× inline dict)
_find_lb(conn, …)       – find-or-404 for load balancers       (replaces 2× inline pattern)
_find_listener(conn, …) – find-or-404 for listeners            (replaces 5× inline pattern)
"""

from __future__ import annotations

import logging
from typing import Any

from ...connection import get_openstack_connection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALL_ACTIONS: frozenset[str] = frozenset({
    "create", "delete", "update", "unset", "show", "stats",
})

# Fields that may be patched in an update operation
_UPDATE_FIELDS: frozenset[str] = frozenset({
    "name", "description", "admin_state_up",
    "connection_limit", "default_pool_id",
})

# Fields that unset clears to their "empty" value
# connection_limit is reset to -1 (unlimited) per Octavia spec — not None
_UNSET_DEFAULTS: dict[str, Any] = {
    "description":      "",
    "connection_limit": -1,   # -1 = unlimited; None would be rejected by API
    "default_pool_id":  None,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ts(obj: Any, attr: str) -> str | None:
    """Return ISO-8601 string for *attr* on *obj*, or None if absent/None."""
    val = getattr(obj, attr, None)
    return str(val) if val is not None else None


def _build_listener_dict(listener: Any) -> dict[str, Any]:
    """Normalise a raw SDK Listener object into a consistent dict."""
    return {
        "id":                  listener.id,
        "name":                listener.name,
        "description":         listener.description,
        "protocol":            listener.protocol,
        "protocol_port":       listener.protocol_port,
        "admin_state_up":      listener.admin_state_up,
        "loadbalancer_id":     listener.loadbalancer_id,
        "default_pool_id":     getattr(listener, "default_pool_id", None),
        "connection_limit":    getattr(listener, "connection_limit", None),
        "provisioning_status": getattr(listener, "provisioning_status", None),
        "operating_status":    getattr(listener, "operating_status", None),
        "created_at":          _ts(listener, "created_at"),
        "updated_at":          _ts(listener, "updated_at"),
    }


def _find_lb(conn: Any, lb_name_or_id: str) -> tuple[Any | None, dict | None]:
    """Return ``(lb, None)`` or ``(None, error_dict)``."""
    lb = conn.load_balancer.find_load_balancer(lb_name_or_id)
    if lb is None:
        return None, {"success": False, "message": f"Load balancer not found: {lb_name_or_id}"}
    return lb, None


def _find_listener(conn: Any, listener_name_or_id: str) -> tuple[Any | None, dict | None]:
    """Return ``(listener, None)`` or ``(None, error_dict)``."""
    listener = conn.load_balancer.find_listener(listener_name_or_id)
    if listener is None:
        return None, {"success": False, "message": f"Listener not found: {listener_name_or_id}"}
    return listener, None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_load_balancer_listeners(lb_name_or_id: str) -> dict[str, Any]:
    """List all listeners attached to a load balancer.

    Args:
        lb_name_or_id: Load-balancer name or UUID (required).

    Returns:
        ``{'success': True, 'load_balancer': {...}, 'listeners': [...], 'listener_count': N}``
    """
    try:
        conn = get_openstack_connection()

        lb, err = _find_lb(conn, lb_name_or_id)
        if err:
            return err

        listeners = [
            _build_listener_dict(l)
            for l in conn.load_balancer.listeners(loadbalancer_id=lb.id)
        ]

        return {
            "success":        True,
            "load_balancer":  {"id": lb.id, "name": lb.name},
            "listeners":      listeners,
            "listener_count": len(listeners),
        }

    except Exception as exc:
        logger.error("Failed to get listeners for LB %s: %s", lb_name_or_id, exc)
        return {"success": False, "message": f"Failed to get load balancer listeners: {exc}"}


def set_load_balancer_listener(action: str, **kwargs) -> dict[str, Any]:
    """Manage load-balancer listener lifecycle.

    Supported *action* values
    -------------------------
    ``create`` – Create a listener on a load balancer.
    ``delete`` – Delete a listener by name or ID.
    ``update`` – Patch specific fields of an existing listener.
    ``unset``  – Reset optional fields back to their defaults.
    ``show``   – Return full details for one listener.
    ``stats``  – Return traffic counters for a listener.

    Create parameters (via **kwargs)
    ---------------------------------
    lb_name_or_id  : str  – Parent load balancer (required).
    name           : str  – Listener name (required).
    protocol       : str  – ``HTTP``, ``HTTPS``, ``TCP``, ``UDP``, etc. (required).
    protocol_port  : int  – Port to listen on (required).
    description    : str  – Optional description.
    admin_state_up : bool – Enabled state (default: True).
    connection_limit : int – Max simultaneous connections (-1 = unlimited).
    default_pool_id  : str – Default backend pool UUID.

    Update / unset / show / delete / stats parameters
    --------------------------------------------------
    listener_name_or_id : str – Target listener (required for all except create).
    Any subset of the create fields above for update; only supplied keys are patched.
    For unset, pass the field names as True flags (e.g. ``description=True``).

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
        logger.info("Managing listener: action=%s", action)

        # ------------------------------------------------------------------ create
        if action == "create":
            name          = kwargs.get("name")
            lb_name_or_id = kwargs.get("lb_name_or_id")
            protocol      = kwargs.get("protocol")
            protocol_port = kwargs.get("protocol_port")

            if not all([name, lb_name_or_id, protocol, protocol_port]):
                return {
                    "success": False,
                    "message": "name, lb_name_or_id, protocol, and protocol_port are required for create",
                }

            lb, err = _find_lb(conn, lb_name_or_id)
            if err:
                return err

            params: dict[str, Any] = {
                k: v for k, v in {
                    "name":             name,
                    "loadbalancer_id":  lb.id,
                    "protocol":         protocol.upper(),
                    "protocol_port":    int(protocol_port),
                    "description":      kwargs.get("description"),
                    "admin_state_up":   kwargs.get("admin_state_up", True),
                    "connection_limit": kwargs.get("connection_limit"),
                    "default_pool_id":  kwargs.get("default_pool_id"),
                }.items()
                if v is not None and v != ""
            }

            listener = conn.load_balancer.create_listener(**params)
            return {
                "success":  True,
                "message":  f"Listener created successfully: {listener.name}",
                "listener": _build_listener_dict(listener),
            }

        # ------------------------------------------------------------------ delete
        if action == "delete":
            listener_name_or_id = kwargs.get("listener_name_or_id", "")
            if not listener_name_or_id:
                return {"success": False, "message": "listener_name_or_id is required for delete"}

            listener, err = _find_listener(conn, listener_name_or_id)
            if err:
                return err

            conn.load_balancer.delete_listener(listener.id)
            return {"success": True, "message": f"Listener deleted successfully: {listener.name}"}

        # ------------------------------------------------------------------ update
        if action == "update":
            listener_name_or_id = kwargs.get("listener_name_or_id", "")
            if not listener_name_or_id:
                return {"success": False, "message": "listener_name_or_id is required for update"}

            listener, err = _find_listener(conn, listener_name_or_id)
            if err:
                return err

            update_params = {k: kwargs[k] for k in _UPDATE_FIELDS if k in kwargs}
            if not update_params:
                return {
                    "success": False,
                    "message": f"No updatable fields provided. Supported: {sorted(_UPDATE_FIELDS)}",
                }

            updated = conn.load_balancer.update_listener(listener.id, **update_params)
            return {
                "success":  True,
                "message":  f"Listener updated successfully: {updated.name}",
                "listener": _build_listener_dict(updated),
            }

        # ------------------------------------------------------------------ unset
        if action == "unset":
            listener_name_or_id = kwargs.get("listener_name_or_id", "")
            if not listener_name_or_id:
                return {"success": False, "message": "listener_name_or_id is required for unset"}

            listener, err = _find_listener(conn, listener_name_or_id)
            if err:
                return err

            # Only clear fields the caller explicitly flagged
            unset_params = {
                field: default
                for field, default in _UNSET_DEFAULTS.items()
                if kwargs.get(field)
            }

            if not unset_params:
                return {
                    "success": False,
                    "message": (
                        "No unset fields specified. "
                        f"Clearable fields: {sorted(_UNSET_DEFAULTS)}"
                    ),
                }

            updated = conn.load_balancer.update_listener(listener.id, **unset_params)
            return {
                "success": True,
                "message": f"Listener settings cleared: {updated.name}",
                "cleared": sorted(unset_params),
            }

        # ------------------------------------------------------------------ show
        if action == "show":
            listener_name_or_id = kwargs.get("listener_name_or_id", "")
            if not listener_name_or_id:
                return {"success": False, "message": "listener_name_or_id is required for show"}

            listener, err = _find_listener(conn, listener_name_or_id)
            if err:
                return err

            return {"success": True, "listener": _build_listener_dict(listener)}

        # ------------------------------------------------------------------ stats
        if action == "stats":
            listener_name_or_id = kwargs.get("listener_name_or_id", "")
            if not listener_name_or_id:
                return {"success": False, "message": "listener_name_or_id is required for stats"}

            listener, err = _find_listener(conn, listener_name_or_id)
            if err:
                return err

            # Outer try-except already handles SDK errors; no nested try needed
            stats = conn.load_balancer.get_listener_statistics(listener.id)
            return {
                "success": True,
                "listener_stats": {
                    "bytes_in":           getattr(stats, "bytes_in", 0),
                    "bytes_out":          getattr(stats, "bytes_out", 0),
                    "active_connections": getattr(stats, "active_connections", 0),
                    "total_connections":  getattr(stats, "total_connections", 0),
                    "request_errors":     getattr(stats, "request_errors", 0),
                },
            }

    except Exception as exc:
        logger.error("set_load_balancer_listener(%s) failed: %s", action, exc)
        return {"success": False, "message": f"Failed to {action} listener: {exc}"}
