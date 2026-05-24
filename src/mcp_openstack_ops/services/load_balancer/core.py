"""
OpenStack Load Balancer Core Functions (Octavia)

Public API
----------
get_load_balancer_list    – paginated / full list scoped to current project
get_load_balancer_details – deep view (listeners → pools → members)
set_load_balancer         – create / delete / update / failover / stats / status

Internal helpers
----------------
_ts(obj, attr)    – safe ISO-8601 timestamp string (None if missing)
_build_lb_dict    – shared field map for LB resource objects
_find_lb          – find-or-404 pattern; avoids 5× repeated boilerplate
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ...connection import get_openstack_connection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supported actions – validated before any network call
# ---------------------------------------------------------------------------

_WRITE_ACTIONS: frozenset[str] = frozenset({"create", "delete", "update", "failover"})
_READ_ACTIONS:  frozenset[str] = frozenset({"stats", "status"})
_ALL_ACTIONS:   frozenset[str] = _WRITE_ACTIONS | _READ_ACTIONS

# Updatable fields for the "update" action
_UPDATE_FIELDS: frozenset[str] = frozenset({"name", "description", "admin_state_up"})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ts(obj: Any, attr: str) -> str | None:
    """Return ISO-8601 string for *attr* on *obj*, or None if absent/None."""
    val = getattr(obj, attr, None)
    return str(val) if val is not None else None


def _build_lb_dict(lb: Any) -> dict[str, Any]:
    """Normalise a raw SDK LoadBalancer object into a consistent dict."""
    return {
        "id":                   lb.id,
        "name":                 lb.name,
        "description":          lb.description,
        "vip_address":          lb.vip_address,
        "vip_port_id":          lb.vip_port_id,
        "vip_subnet_id":        lb.vip_subnet_id,
        "vip_network_id":       lb.vip_network_id,
        "provisioning_status":  lb.provisioning_status,
        "operating_status":     lb.operating_status,
        "admin_state_up":       lb.admin_state_up,
        "project_id":           lb.project_id,
        "provider":             getattr(lb, "provider", None),
        "created_at":           _ts(lb, "created_at"),
        "updated_at":           _ts(lb, "updated_at"),
    }


def _find_lb(conn: Any, lb_name_or_id: str) -> tuple[Any | None, dict | None]:
    """Return ``(lb_object, None)`` on success or ``(None, error_dict)`` when not found.

    Usage::

        lb, err = _find_lb(conn, name_or_id)
        if err:
            return err
    """
    lb = conn.load_balancer.find_load_balancer(lb_name_or_id)
    if lb is None:
        return None, {
            "success": False,
            "message": f"Load balancer not found: {lb_name_or_id}",
        }
    return lb, None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_load_balancer_list(
    limit: int = 50,
    offset: int = 0,
    include_all: bool = False,
    include_listeners: bool = True,
) -> dict[str, Any]:
    """Return load balancers scoped to the current project.

    Args:
        limit:             Max items to return (1–200).  Ignored when
                           *include_all* is True.
        offset:            Items to skip for pagination.
        include_all:       Return every LB without pagination.
        include_listeners: Attach a listener summary to each LB.  Set to
                           False to avoid N+1 API calls when only basic
                           data is needed.

    Returns:
        ``{'success': True, 'load_balancers': [...], 'summary': {...}}``
    """
    try:
        conn = get_openstack_connection()
        project_id = conn.current_project_id
        t0 = time.monotonic()

        # SDK supports project_id filter – avoids fetching all tenants' LBs
        all_lbs = list(conn.load_balancer.load_balancers(project_id=project_id))

        if not include_all:
            limit = max(1, min(limit, 200))
            page = all_lbs[offset: offset + limit]
        else:
            page = all_lbs

        lb_details: list[dict] = []
        for lb in page:
            try:
                entry = _build_lb_dict(lb)
                if include_listeners:
                    listeners = list(conn.load_balancer.listeners(loadbalancer_id=lb.id))
                    entry["listeners"] = [
                        {
                            "id":            l.id,
                            "name":          l.name,
                            "protocol":      l.protocol,
                            "protocol_port": l.protocol_port,
                            "admin_state_up": l.admin_state_up,
                        }
                        for l in listeners
                    ]
                    entry["listener_count"] = len(entry["listeners"])
                lb_details.append(entry)
            except Exception as exc:
                logger.warning("Failed to enrich LB %s: %s", lb.id, exc)
                lb_details.append({"id": lb.id, "name": lb.name, "error": str(exc)})

        elapsed = round(time.monotonic() - t0, 3)
        summary: dict[str, Any] = {
            "total_returned":           len(lb_details),
            "project_id":               project_id,
            "processing_time_seconds":  elapsed,
        }
        if not include_all:
            summary.update({
                "limit":          limit,
                "offset":         offset,
                "total_available": len(all_lbs),
                "has_more":        (offset + limit) < len(all_lbs),
            })

        logger.info("Retrieved %d LBs for project %s in %.3fs", len(lb_details), project_id, elapsed)
        return {"success": True, "load_balancers": lb_details, "summary": summary}

    except Exception as exc:
        logger.error("Failed to list load balancers: %s", exc)
        return {"success": False, "message": f"Failed to list load balancers: {exc}"}


def get_load_balancer_details(lb_name_or_id: str) -> dict[str, Any]:
    """Return a deep view of one load balancer (listeners → pools → members).

    Args:
        lb_name_or_id: Load-balancer name or UUID.

    Returns:
        ``{'success': True, 'load_balancer': {...}}`` with nested topology.
    """
    try:
        conn = get_openstack_connection()

        lb, err = _find_lb(conn, lb_name_or_id)
        if err:
            return err

        lb_dict = _build_lb_dict(lb)

        listeners = list(conn.load_balancer.listeners(loadbalancer_id=lb.id))
        listener_details = []
        for listener in listeners:
            pools = list(conn.load_balancer.pools(listener_id=listener.id))
            pool_list = []
            for pool in pools:
                members = list(conn.load_balancer.members(pool_id=pool.id))
                pool_list.append({
                    "id":            pool.id,
                    "name":          pool.name,
                    "protocol":      pool.protocol,
                    "lb_algorithm":  pool.lb_algorithm,
                    "admin_state_up": pool.admin_state_up,
                    "members": [
                        {
                            "id":            m.id,
                            "address":       m.address,
                            "protocol_port": m.protocol_port,
                        }
                        for m in members
                    ],
                    "member_count": len(members),
                })
            listener_details.append({
                "id":            listener.id,
                "name":          listener.name,
                "protocol":      listener.protocol,
                "protocol_port": listener.protocol_port,
                "admin_state_up": listener.admin_state_up,
                "pools":         pool_list,
                "pool_count":    len(pool_list),
            })

        lb_dict["listeners"]      = listener_details
        lb_dict["listener_count"] = len(listener_details)

        return {"success": True, "load_balancer": lb_dict}

    except Exception as exc:
        logger.error("Failed to get LB details for %s: %s", lb_name_or_id, exc)
        return {"success": False, "message": f"Failed to get load balancer details: {exc}"}


def set_load_balancer(action: str, **kwargs) -> dict[str, Any]:
    """Mutate or query a load balancer.

    Supported *action* values
    -------------------------
    ``create``   – Provision a new load balancer.
    ``delete``   – Delete (with optional cascade).
    ``update``   – Modify name / description / admin_state_up.
    ``failover`` – Initiate LB failover.
    ``stats``    – Return traffic counters.
    ``status``   – Return provisioning / operating status.

    Args:
        action:   One of the supported values above.
        **kwargs: Action-specific parameters (see per-action docs below).

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
            name          = kwargs.get("name")
            vip_subnet_id = kwargs.get("vip_subnet_id")
            if not name or not vip_subnet_id:
                return {
                    "success": False,
                    "message": "name and vip_subnet_id are required for create",
                }

            # Build params – skip None AND empty-string values
            lb_params = {
                k: v for k, v in {
                    "name":               name,
                    "vip_subnet_id":      vip_subnet_id,
                    "description":        kwargs.get("description"),
                    "admin_state_up":     kwargs.get("admin_state_up", True),
                    "provider":           kwargs.get("provider"),
                    "flavor_id":          kwargs.get("flavor_id"),
                    "availability_zone":  kwargs.get("availability_zone"),
                }.items()
                if v is not None and v != ""
            }

            lb = conn.load_balancer.create_load_balancer(**lb_params)
            return {
                "success":       True,
                "message":       f"Load balancer created: {lb.name}",
                "load_balancer": _build_lb_dict(lb),
            }

        # ------------------------------------------------------------------ delete
        if action == "delete":
            lb_name_or_id = kwargs.get("lb_name_or_id", "")
            if not lb_name_or_id:
                return {"success": False, "message": "lb_name_or_id is required for delete"}

            lb, err = _find_lb(conn, lb_name_or_id)
            if err:
                return err

            conn.load_balancer.delete_load_balancer(
                lb.id, cascade=kwargs.get("cascade", False)
            )
            return {"success": True, "message": f"Load balancer deleted: {lb.name}"}

        # ------------------------------------------------------------------ update
        if action == "update":
            lb_name_or_id = kwargs.get("lb_name_or_id", "")
            if not lb_name_or_id:
                return {"success": False, "message": "lb_name_or_id is required for update"}

            lb, err = _find_lb(conn, lb_name_or_id)
            if err:
                return err

            update_params = {k: kwargs[k] for k in _UPDATE_FIELDS if k in kwargs}
            if not update_params:
                return {
                    "success": False,
                    "message": f"No updatable fields provided. Supported: {sorted(_UPDATE_FIELDS)}",
                }

            updated = conn.load_balancer.update_load_balancer(lb.id, **update_params)
            return {
                "success":       True,
                "message":       f"Load balancer updated: {updated.name}",
                "load_balancer": _build_lb_dict(updated),
            }

        # ------------------------------------------------------------------ failover
        if action == "failover":
            lb_name_or_id = kwargs.get("lb_name_or_id", "")
            if not lb_name_or_id:
                return {"success": False, "message": "lb_name_or_id is required for failover"}

            lb, err = _find_lb(conn, lb_name_or_id)
            if err:
                return err

            conn.load_balancer.failover_load_balancer(lb.id)
            return {"success": True, "message": f"Load balancer failover initiated: {lb.name}"}

        # ------------------------------------------------------------------ stats
        if action == "stats":
            lb_name_or_id = kwargs.get("lb_name_or_id", "")
            if not lb_name_or_id:
                return {"success": False, "message": "lb_name_or_id is required for stats"}

            lb, err = _find_lb(conn, lb_name_or_id)
            if err:
                return err

            stats = conn.load_balancer.get_load_balancer_statistics(lb.id)
            return {
                "success": True,
                "load_balancer_stats": {
                    "bytes_in":           getattr(stats, "bytes_in", 0),
                    "bytes_out":          getattr(stats, "bytes_out", 0),
                    "active_connections": getattr(stats, "active_connections", 0),
                    "total_connections":  getattr(stats, "total_connections", 0),
                },
            }

        # ------------------------------------------------------------------ status
        if action == "status":
            lb_name_or_id = kwargs.get("lb_name_or_id", "")
            if not lb_name_or_id:
                return {"success": False, "message": "lb_name_or_id is required for status"}

            lb, err = _find_lb(conn, lb_name_or_id)
            if err:
                return err

            return {
                "success": True,
                "load_balancer_status": {
                    "id":                  lb.id,
                    "name":                lb.name,
                    "provisioning_status": lb.provisioning_status,
                    "operating_status":    lb.operating_status,
                    "admin_state_up":      lb.admin_state_up,
                    "vip_address":         lb.vip_address,
                },
            }

    except Exception as exc:
        logger.error("set_load_balancer(%s) failed: %s", action, exc)
        return {"success": False, "message": f"Failed to {action} load balancer: {exc}"}
