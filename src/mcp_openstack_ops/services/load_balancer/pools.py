"""
Load Balancer Pool and Member Management (Octavia)

Public API
----------
get_load_balancer_pools        – list pools (optionally filtered by listener)
set_load_balancer_pool         – create / delete / update / show a pool
get_load_balancer_pool_members – list members of a pool
set_load_balancer_pool_member  – create / delete / update / show a member

Internal helpers
----------------
_ts(obj, attr)          – safe ISO-8601 timestamp string
_build_pool_dict        – normalises raw SDK Pool objects   (replaces 3× inline dict)
_build_member_dict      – normalises raw SDK Member objects (replaces 5× inline dict)
_find_pool(conn, …)     – find-or-404 via SDK find_pool()  (replaces 5× for-loop)
_find_listener(conn, …) – find-or-404 via SDK find_listener() (replaces 1× for-loop)
_get_member             – get-or-404 wrapping SDK get_member  (replaces 3× try/except)
"""

from __future__ import annotations

import logging
from typing import Any

from ...connection import get_openstack_connection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_POOL_ACTIONS:   frozenset[str] = frozenset({"create", "delete", "update", "show"})
_MEMBER_ACTIONS: frozenset[str] = frozenset({"create", "delete", "update", "show"})

_POOL_UPDATE_FIELDS:   frozenset[str] = frozenset({
    "name", "description", "lb_algorithm", "admin_state_up",
})
_MEMBER_UPDATE_FIELDS: frozenset[str] = frozenset({
    "name", "weight", "admin_state_up", "backup",
    "monitor_address", "monitor_port",
})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ts(obj: Any, attr: str) -> str | None:
    """Return ISO-8601 string for *attr* on *obj*, or None if absent/None."""
    val = getattr(obj, attr, None)
    return str(val) if val is not None else None


def _build_pool_dict(pool: Any, *, members: list | None = None) -> dict[str, Any]:
    """Normalise a raw SDK Pool object into a consistent dict.

    Args:
        pool:    SDK Pool resource.
        members: Pre-fetched member list.  When None, the ``members`` key is
                 omitted (suitable for list responses without N+1 fetching).
    """
    d: dict[str, Any] = {
        "id":                  pool.id,
        "name":                pool.name,
        "description":         pool.description,
        "protocol":            pool.protocol,
        "lb_algorithm":        pool.lb_algorithm,
        "admin_state_up":      pool.admin_state_up,
        "listener_id":         getattr(pool, "listener_id", None),
        "loadbalancer_id":     getattr(pool, "loadbalancer_id", None),
        "provisioning_status": getattr(pool, "provisioning_status", None),
        "operating_status":    getattr(pool, "operating_status", None),
        "created_at":          _ts(pool, "created_at"),
        "updated_at":          _ts(pool, "updated_at"),
    }
    if members is not None:
        d["members"]      = members
        d["member_count"] = len(members)
    return d


def _build_member_dict(member: Any, pool_id: str | None = None) -> dict[str, Any]:
    """Normalise a raw SDK Member object into a consistent dict."""
    return {
        "id":                  member.id,
        "name":                getattr(member, "name", None),
        "address":             member.address,
        "protocol_port":       member.protocol_port,
        "weight":              getattr(member, "weight", 1),
        "admin_state_up":      member.admin_state_up,
        "backup":              getattr(member, "backup", False),
        "monitor_address":     getattr(member, "monitor_address", None),
        "monitor_port":        getattr(member, "monitor_port", None),
        "provisioning_status": getattr(member, "provisioning_status", None),
        "operating_status":    getattr(member, "operating_status", None),
        "pool_id":             pool_id,
        "created_at":          _ts(member, "created_at"),
        "updated_at":          _ts(member, "updated_at"),
    }


def _find_pool(conn: Any, pool_name_or_id: str) -> tuple[Any | None, dict | None]:
    """Return ``(pool, None)`` or ``(None, error_dict)`` using SDK find_pool."""
    pool = conn.load_balancer.find_pool(pool_name_or_id)
    if pool is None:
        return None, {"success": False, "message": f"Pool not found: {pool_name_or_id}"}
    return pool, None


def _find_listener(conn: Any, listener_name_or_id: str) -> tuple[Any | None, dict | None]:
    """Return ``(listener, None)`` or ``(None, error_dict)``."""
    listener = conn.load_balancer.find_listener(listener_name_or_id)
    if listener is None:
        return None, {"success": False, "message": f"Listener not found: {listener_name_or_id}"}
    return listener, None


def _get_member(
    conn: Any, member_id: str, pool: Any
) -> tuple[Any | None, dict | None]:
    """Return ``(member, None)`` or ``(None, error_dict)``.

    Wraps SDK ``get_member`` which raises on not-found; avoids 3× try/except
    blocks using exceptions as control flow.
    """
    try:
        member = conn.load_balancer.get_member(member_id, pool)
        return member, None
    except Exception:
        return None, {"success": False, "message": f"Member not found: {member_id}"}


# ---------------------------------------------------------------------------
# Public API — pools
# ---------------------------------------------------------------------------

def get_load_balancer_pools(
    listener_name_or_id: str = "",
    include_members: bool = False,
) -> dict[str, Any]:
    """List load balancer pools, optionally filtered to one listener.

    Args:
        listener_name_or_id: Listener name or UUID.  When empty all visible
                             pools are returned.
        include_members:     When True, fetch members for each pool (triggers
                             N+1 API calls — use only when member data is
                             needed; default: False).

    Returns:
        ``{'success': True, 'pools': [...], 'pool_count': N}``
    """
    try:
        conn = get_openstack_connection()

        if listener_name_or_id:
            listener, err = _find_listener(conn, listener_name_or_id)
            if err:
                return err
            raw_pools = list(conn.load_balancer.pools(listener_id=listener.id))
        else:
            raw_pools = list(conn.load_balancer.pools())

        pools: list[dict] = []
        for pool in raw_pools:
            if include_members:
                member_list = [
                    _build_member_dict(m, pool_id=pool.id)
                    for m in conn.load_balancer.members(pool_id=pool.id)
                ]
                pools.append(_build_pool_dict(pool, members=member_list))
            else:
                pools.append(_build_pool_dict(pool))

        return {
            "success":    True,
            "pools":      pools,
            "pool_count": len(pools),
            "filter":     f"listener: {listener_name_or_id}" if listener_name_or_id else "all",
        }

    except Exception as exc:
        logger.error("Failed to get pools: %s", exc)
        return {"success": False, "message": f"Failed to get pools: {exc}"}


def set_load_balancer_pool(action: str, **kwargs) -> dict[str, Any]:
    """Manage load-balancer pool lifecycle.

    Supported *action* values
    -------------------------
    ``create`` – Create a pool on a listener.
    ``delete`` – Delete a pool by name or ID.
    ``update`` – Patch specific fields of an existing pool.
    ``show``   – Return full details (including members) for one pool.

    Create parameters (via **kwargs)
    ---------------------------------
    name                 : str  – Pool name (required).
    listener_name_or_id  : str  – Parent listener (required).
    protocol             : str  – ``HTTP``, ``HTTPS``, ``TCP``, ``UDP`` (required).
    lb_algorithm         : str  – ``ROUND_ROBIN``, ``LEAST_CONNECTIONS``,
                                  ``SOURCE_IP`` (default: ``ROUND_ROBIN``).
    description          : str  – Optional description.
    admin_state_up       : bool – Enabled state (default: True).

    Update / show / delete parameters
    -----------------------------------
    pool_name_or_id : str – Target pool name or UUID (required).
    Any subset of the create fields above for update; only supplied keys are patched.
    """
    if action not in _POOL_ACTIONS:
        return {
            "success": False,
            "message": f'Unknown action "{action}". Supported: {sorted(_POOL_ACTIONS)}',
        }

    try:
        conn = get_openstack_connection()

        # ------------------------------------------------------------------ create
        if action == "create":
            name                = kwargs.get("name", "")
            listener_name_or_id = kwargs.get("listener_name_or_id", "")
            protocol            = kwargs.get("protocol", "")
            if not all([name, listener_name_or_id, protocol]):
                return {
                    "success": False,
                    "message": "name, listener_name_or_id, and protocol are required for create",
                }

            listener, err = _find_listener(conn, listener_name_or_id)
            if err:
                return err

            params: dict[str, Any] = {
                k: v for k, v in {
                    "name":            name,
                    "listener_id":     listener.id,
                    "protocol":        protocol.upper(),
                    "lb_algorithm":    kwargs.get("lb_algorithm", "ROUND_ROBIN").upper(),
                    "description":     kwargs.get("description"),
                    "admin_state_up":  kwargs.get("admin_state_up", True),
                }.items()
                if v is not None and v != ""
            }

            pool = conn.load_balancer.create_pool(**params)
            return {
                "success": True,
                "message": f"Pool created successfully: {pool.name}",
                "pool":    _build_pool_dict(pool),
            }

        # ------------------------------------------------------------------ delete
        if action == "delete":
            pool_name_or_id = kwargs.get("pool_name_or_id", "")
            if not pool_name_or_id:
                return {"success": False, "message": "pool_name_or_id is required for delete"}

            pool, err = _find_pool(conn, pool_name_or_id)
            if err:
                return err

            conn.load_balancer.delete_pool(pool)
            return {"success": True, "message": f"Pool deleted successfully: {pool.name}"}

        # ------------------------------------------------------------------ update
        if action == "update":
            pool_name_or_id = kwargs.get("pool_name_or_id", "")
            if not pool_name_or_id:
                return {"success": False, "message": "pool_name_or_id is required for update"}

            pool, err = _find_pool(conn, pool_name_or_id)
            if err:
                return err

            update_params = {k: kwargs[k] for k in _POOL_UPDATE_FIELDS if k in kwargs}

            # Normalise lb_algorithm to upper-case if supplied
            if "lb_algorithm" in update_params:
                update_params["lb_algorithm"] = update_params["lb_algorithm"].upper()

            if not update_params:
                return {
                    "success": False,
                    "message": f"No updatable fields provided. Supported: {sorted(_POOL_UPDATE_FIELDS)}",
                }

            updated = conn.load_balancer.update_pool(pool, **update_params)
            return {
                "success": True,
                "message": f"Pool updated successfully: {updated.name}",
                "pool":    _build_pool_dict(updated),
            }

        # ------------------------------------------------------------------ show
        if action == "show":
            pool_name_or_id = kwargs.get("pool_name_or_id", "")
            if not pool_name_or_id:
                return {"success": False, "message": "pool_name_or_id is required for show"}

            pool, err = _find_pool(conn, pool_name_or_id)
            if err:
                return err

            member_list = [
                _build_member_dict(m, pool_id=pool.id)
                for m in conn.load_balancer.members(pool_id=pool.id)
            ]
            return {"success": True, "pool": _build_pool_dict(pool, members=member_list)}

    except Exception as exc:
        logger.error("set_load_balancer_pool(%s) failed: %s", action, exc)
        return {"success": False, "message": f"Failed to {action} pool: {exc}"}


# ---------------------------------------------------------------------------
# Public API — members
# ---------------------------------------------------------------------------

def get_load_balancer_pool_members(pool_name_or_id: str) -> dict[str, Any]:
    """List all members of a pool.

    Args:
        pool_name_or_id: Pool name or UUID (required).

    Returns:
        ``{'success': True, 'pool': {...}, 'members': [...], 'member_count': N}``
    """
    try:
        conn = get_openstack_connection()

        pool, err = _find_pool(conn, pool_name_or_id)
        if err:
            return err

        members = [
            _build_member_dict(m, pool_id=pool.id)
            for m in conn.load_balancer.members(pool_id=pool.id)
        ]

        return {
            "success":      True,
            "pool":         {"id": pool.id, "name": pool.name, "protocol": pool.protocol},
            "members":      members,
            "member_count": len(members),
        }

    except Exception as exc:
        logger.error("Failed to get pool members: %s", exc)
        return {"success": False, "message": f"Failed to get pool members: {exc}"}


def set_load_balancer_pool_member(action: str, **kwargs) -> dict[str, Any]:
    """Manage pool member lifecycle.

    Supported *action* values
    -------------------------
    ``create`` – Add a backend member to a pool.
    ``delete`` – Remove a member by ID.
    ``update`` – Patch specific fields of an existing member.
    ``show``   – Return full details for one member.

    All actions require **pool_name_or_id** (pool name or UUID).

    Create parameters (via **kwargs)
    ---------------------------------
    pool_name_or_id : str  – Target pool (required).
    address         : str  – Backend IP address (required).
    protocol_port   : int  – Backend port (required, must be > 0).
    name            : str  – Optional member name.
    weight          : int  – Traffic weight (0 = drain; default: 1).
    admin_state_up  : bool – Enabled state (default: True).
    backup          : bool – Backup member flag (default: False).
    monitor_address : str  – Health-check IP override.
    monitor_port    : int  – Health-check port override.

    Update / delete / show parameters
    -----------------------------------
    member_id       : str – Target member UUID (required).
    Any subset of the create fields above for update; only supplied keys are patched.
    """
    if action not in _MEMBER_ACTIONS:
        return {
            "success": False,
            "message": f'Unknown action "{action}". Supported: {sorted(_MEMBER_ACTIONS)}',
        }

    pool_name_or_id = kwargs.get("pool_name_or_id", "")
    if not pool_name_or_id:
        return {"success": False, "message": "pool_name_or_id is required"}

    try:
        conn = get_openstack_connection()

        pool, err = _find_pool(conn, pool_name_or_id)
        if err:
            return err

        # ------------------------------------------------------------------ create
        if action == "create":
            address       = kwargs.get("address", "")
            protocol_port = kwargs.get("protocol_port", 0)

            if not address or not protocol_port or int(protocol_port) <= 0:
                return {
                    "success": False,
                    "message": "address and protocol_port (> 0) are required for create",
                }

            params: dict[str, Any] = {
                k: v for k, v in {
                    "address":        address,
                    "protocol_port":  int(protocol_port),
                    "name":           kwargs.get("name"),
                    "weight":         kwargs.get("weight", 1),
                    "admin_state_up": kwargs.get("admin_state_up", True),
                    "backup":         kwargs.get("backup", False),
                    "monitor_address": kwargs.get("monitor_address"),
                    "monitor_port":   kwargs.get("monitor_port"),
                }.items()
                if v is not None
            }

            member = conn.load_balancer.create_member(pool, **params)
            return {
                "success": True,
                "message": "Pool member created successfully",
                "member":  _build_member_dict(member, pool_id=pool.id),
            }

        # ------------------------------------------------------------------ delete
        if action == "delete":
            member_id = kwargs.get("member_id", "")
            if not member_id:
                return {"success": False, "message": "member_id is required for delete"}

            member, err = _get_member(conn, member_id, pool)
            if err:
                return err

            conn.load_balancer.delete_member(member, pool)
            return {
                "success": True,
                "message": f"Member deleted: {member.address}:{member.protocol_port}",
            }

        # ------------------------------------------------------------------ show
        if action == "show":
            member_id = kwargs.get("member_id", "")
            if not member_id:
                return {"success": False, "message": "member_id is required for show"}

            member, err = _get_member(conn, member_id, pool)
            if err:
                return err

            return {"success": True, "member": _build_member_dict(member, pool_id=pool.id)}

        # ------------------------------------------------------------------ update
        if action == "update":
            member_id = kwargs.get("member_id", "")
            if not member_id:
                return {"success": False, "message": "member_id is required for update"}

            member, err = _get_member(conn, member_id, pool)
            if err:
                return err

            # weight=0 is valid (drain member) — include only explicitly supplied fields
            update_params = {k: kwargs[k] for k in _MEMBER_UPDATE_FIELDS if k in kwargs}

            if not update_params:
                return {
                    "success": False,
                    "message": (
                        "No updatable fields provided. "
                        f"Supported: {sorted(_MEMBER_UPDATE_FIELDS)}"
                    ),
                }

            updated = conn.load_balancer.update_member(member, pool, **update_params)
            return {
                "success": True,
                "message": "Pool member updated successfully",
                "member":  _build_member_dict(updated, pool_id=pool.id),
            }

    except Exception as exc:
        logger.error("set_load_balancer_pool_member(%s) failed: %s", action, exc)
        return {"success": False, "message": f"Failed to {action} pool member: {exc}"}
