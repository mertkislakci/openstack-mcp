"""
Load Balancer Amphora Management

Provides operations on Octavia amphora instances:
  get_load_balancer_amphorae  – list amphorae (optionally filtered by LB)
  set_load_balancer_amphora   – configure / failover / show a single amphora

Private helpers
---------------
_build_amphora_dict  – normalises raw SDK amphora objects into a consistent dict;
                       used by both public functions to avoid duplication.
"""

from __future__ import annotations

import logging
from typing import Any

from ...connection import get_openstack_connection

logger = logging.getLogger(__name__)

# Actions that mutate state – require ALLOW_MODIFY_OPERATIONS guard upstream
_WRITE_ACTIONS: frozenset[str] = frozenset({"configure", "failover"})
_READ_ACTIONS: frozenset[str] = frozenset({"show"})
_ALL_ACTIONS: frozenset[str] = _WRITE_ACTIONS | _READ_ACTIONS

# Fields not supported by the SDK – surfaced with a clear message instead of
# silently returning None.
_UNSUPPORTED_ACTIONS: frozenset[str] = frozenset({"delete", "stats"})


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _build_amphora_dict(amphora: Any) -> dict[str, Any]:
    """Return a normalised dict from an SDK Amphora resource object.

    All timestamp fields are coerced to ISO-8601 strings; missing attributes
    default to None so callers never see AttributeError.
    """
    def _ts(attr: str) -> str | None:
        val = getattr(amphora, attr, None)
        return str(val) if val is not None else None

    return {
        "id":               amphora.id,
        # Octavia SDK uses 'loadbalancer_id' (no underscore between 'load' and 'balancer')
        "loadbalancer_id":  getattr(amphora, "loadbalancer_id", None),
        "compute_id":       getattr(amphora, "compute_id", None),
        "lb_network_ip":    getattr(amphora, "lb_network_ip", None),
        "vrrp_ip":          getattr(amphora, "vrrp_ip", None),
        "ha_ip":            getattr(amphora, "ha_ip", None),
        "vrrp_port_id":     getattr(amphora, "vrrp_port_id", None),
        "ha_port_id":       getattr(amphora, "ha_port_id", None),
        "cert_expiration":  getattr(amphora, "cert_expiration", None),
        "cert_busy":        getattr(amphora, "cert_busy", False),
        "role":             getattr(amphora, "role", None),
        "status":           getattr(amphora, "status", None),
        "cached_zone":      getattr(amphora, "cached_zone", None),
        "image_id":         getattr(amphora, "image_id", None),
        "compute_flavor":   getattr(amphora, "compute_flavor", None),
        "created_at":       _ts("created_at"),
        "updated_at":       _ts("updated_at"),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_load_balancer_amphorae(lb_name_or_id: str = "") -> dict[str, Any]:
    """List amphora instances, optionally filtered to a single load balancer.

    Args:
        lb_name_or_id: Load-balancer name or ID.  When empty, all amphorae
                       visible to the project are returned.

    Returns:
        ``{'success': True, 'amphorae': [...], 'amphora_count': N}``
        or ``{'success': False, 'message': '...'}`` on failure.
    """
    try:
        conn = get_openstack_connection()

        if lb_name_or_id:
            lb = conn.load_balancer.find_load_balancer(lb_name_or_id)
            if not lb:
                return {
                    "success": False,
                    "message": f"Load balancer not found: {lb_name_or_id}",
                }
            raw = list(conn.load_balancer.amphorae(loadbalancer_id=lb.id))
        else:
            raw = list(conn.load_balancer.amphorae())

        amphorae = [_build_amphora_dict(a) for a in raw]
        return {
            "success":       True,
            "amphorae":      amphorae,
            "amphora_count": len(amphorae),
        }

    except Exception as exc:
        logger.error("Failed to get amphorae: %s", exc)
        return {"success": False, "message": f"Failed to get amphorae: {exc}"}


def set_load_balancer_amphora(action: str, amphora_id: str = "", **kwargs) -> dict[str, Any]:
    """Perform an operation on a single amphora.

    Supported *action* values
    -------------------------
    ``show``      – Return full details for the amphora.
    ``configure`` – Push updated configuration to the amphora VM.
    ``failover``  – Initiate a failover (creates a replacement amphora).

    ``delete`` and ``stats`` are **not** supported by the OpenStack SDK and
    will return an explanatory error rather than raising.

    Args:
        action:     One of ``show``, ``configure``, ``failover``.
        amphora_id: UUID of the target amphora (required for all actions).
        **kwargs:   Accepted for backwards compatibility; ``amphora_id`` may
                    also be passed as a keyword argument.

    Returns:
        Action-specific success dict, or ``{'success': False, 'message': '...'}``
        on failure.
    """
    # Support legacy callers that pass amphora_id via **kwargs
    amphora_id = amphora_id or kwargs.get("amphora_id", "")

    # Validate action early – before touching the network
    if action in _UNSUPPORTED_ACTIONS:
        return {
            "success": False,
            "message": (
                f'Action "{action}" is not supported by the OpenStack SDK. '
                f"Available actions: {sorted(_ALL_ACTIONS)}"
            ),
        }

    if action not in _ALL_ACTIONS:
        return {
            "success": False,
            "message": (
                f'Unknown action "{action}". '
                f"Supported: {sorted(_ALL_ACTIONS)}"
            ),
        }

    if not amphora_id:
        return {"success": False, "message": "amphora_id is required"}

    try:
        conn = get_openstack_connection()

        if action == "show":
            amphora = conn.load_balancer.get_amphora(amphora_id)
            if not amphora:
                return {"success": False, "message": f"Amphora not found: {amphora_id}"}
            return {"success": True, "amphora": _build_amphora_dict(amphora)}

        if action == "failover":
            conn.load_balancer.failover_amphora(amphora_id)
            return {
                "success": True,
                "message": f"Amphora failover initiated: {amphora_id}",
            }

        if action == "configure":
            conn.load_balancer.configure_amphora(amphora_id)
            return {
                "success": True,
                "message": f"Amphora configuration updated: {amphora_id}",
            }

    except Exception as exc:
        logger.error("Failed to %s amphora %s: %s", action, amphora_id, exc)
        return {"success": False, "message": f"Failed to {action} amphora: {exc}"}
