"""
Load Balancer L7 Policy and Rule Management (Octavia)

Public API
----------
get_load_balancer_l7_policies  – list policies, optionally filtered by listener
set_load_balancer_l7_policy    – create / delete / update / show a policy
get_load_balancer_l7_rules     – list rules for a policy
set_load_balancer_l7_rule      – create / delete / update / show a rule

Internal helpers
----------------
_ts(obj, attr)         – safe ISO-8601 timestamp string
_build_policy_dict     – normalises raw SDK L7Policy objects
_build_rule_dict       – normalises raw SDK L7Rule objects
_find_listener(conn)   – find-or-404 for listeners  (replaces 2× inline pattern)
_find_policy(conn)     – find-or-404 for L7 policies (replaces 4× inline pattern)
"""

from __future__ import annotations

import logging
from typing import Any

from ...connection import get_openstack_connection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_POLICY_ACTIONS: frozenset[str] = frozenset({"create", "delete", "update", "show"})
_RULE_ACTIONS:   frozenset[str] = frozenset({"create", "delete", "update", "show"})

# Valid Octavia L7 policy action types
_POLICY_ACTION_TYPES: frozenset[str] = frozenset({
    "REJECT", "REDIRECT_TO_POOL", "REDIRECT_TO_URL", "REDIRECT_PREFIX",
})

# Fields that may be patched in update operations
_POLICY_UPDATE_FIELDS: frozenset[str] = frozenset({
    "name", "description", "position", "admin_state_up",
    "redirect_pool_id", "redirect_url", "redirect_prefix",
})
_RULE_UPDATE_FIELDS: frozenset[str] = frozenset({
    "type", "compare_type", "key", "value", "invert", "admin_state_up",
})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ts(obj: Any, attr: str) -> str | None:
    """Return ISO-8601 string for *attr* on *obj*, or None if absent/None."""
    val = getattr(obj, attr, None)
    return str(val) if val is not None else None


def _build_policy_dict(policy: Any) -> dict[str, Any]:
    """Normalise a raw SDK L7Policy object into a consistent dict."""
    return {
        "id":                  policy.id,
        "name":                getattr(policy, "name", None),
        "description":         getattr(policy, "description", None),
        "listener_id":         policy.listener_id,
        "action":              policy.action,
        "position":            policy.position,
        "redirect_pool_id":    getattr(policy, "redirect_pool_id", None),
        "redirect_url":        getattr(policy, "redirect_url", None),
        "redirect_prefix":     getattr(policy, "redirect_prefix", None),
        "admin_state_up":      policy.admin_state_up,
        "provisioning_status": policy.provisioning_status,
        "operating_status":    policy.operating_status,
        "created_at":          _ts(policy, "created_at"),
        "updated_at":          _ts(policy, "updated_at"),
    }


def _build_rule_dict(rule: Any) -> dict[str, Any]:
    """Normalise a raw SDK L7Rule object into a consistent dict."""
    return {
        "id":                  rule.id,
        "l7policy_id":         getattr(rule, "l7policy_id", None),
        "type":                rule.type,
        "compare_type":        rule.compare_type,
        "key":                 getattr(rule, "key", None),
        "value":               rule.value,
        "invert":              getattr(rule, "invert", False),
        "admin_state_up":      rule.admin_state_up,
        "provisioning_status": rule.provisioning_status,
        "operating_status":    rule.operating_status,
        "created_at":          _ts(rule, "created_at"),
        "updated_at":          _ts(rule, "updated_at"),
    }


def _find_listener(conn: Any, listener_name_or_id: str) -> tuple[Any | None, dict | None]:
    """Return ``(listener, None)`` or ``(None, error_dict)``."""
    listener = conn.load_balancer.find_listener(listener_name_or_id)
    if listener is None:
        return None, {"success": False, "message": f"Listener not found: {listener_name_or_id}"}
    return listener, None


def _find_policy(conn: Any, policy_name_or_id: str) -> tuple[Any | None, dict | None]:
    """Return ``(policy, None)`` or ``(None, error_dict)``."""
    policy = conn.load_balancer.find_l7_policy(policy_name_or_id)
    if policy is None:
        return None, {"success": False, "message": f"L7 policy not found: {policy_name_or_id}"}
    return policy, None


# ---------------------------------------------------------------------------
# Public API — policies
# ---------------------------------------------------------------------------

def get_load_balancer_l7_policies(listener_name_or_id: str = "") -> dict[str, Any]:
    """List L7 policies, optionally scoped to one listener.

    Args:
        listener_name_or_id: Listener name or UUID.  When empty all visible
                             policies are returned.

    Returns:
        ``{'success': True, 'l7_policies': [...], 'policy_count': N}``
    """
    try:
        conn = get_openstack_connection()

        if listener_name_or_id:
            listener, err = _find_listener(conn, listener_name_or_id)
            if err:
                return err
            raw = list(conn.load_balancer.l7_policies(listener_id=listener.id))
        else:
            raw = list(conn.load_balancer.l7_policies())

        policies = [_build_policy_dict(p) for p in raw]
        return {
            "success":      True,
            "l7_policies":  policies,
            "policy_count": len(policies),
            "filter":       f"listener: {listener_name_or_id}" if listener_name_or_id else "all",
        }

    except Exception as exc:
        logger.error("Failed to get L7 policies: %s", exc)
        return {"success": False, "message": f"Failed to get L7 policies: {exc}"}


def set_load_balancer_l7_policy(action: str, **kwargs) -> dict[str, Any]:
    """Manage L7 policy lifecycle.

    Supported *action* values
    -------------------------
    ``create`` – Create a new policy on a listener.
    ``delete`` – Delete a policy by name or ID.
    ``update`` – Patch specific fields of an existing policy.
    ``show``   – Return full details for one policy.

    Create parameters (via **kwargs)
    ---------------------------------
    listener_name_or_id : str  – Target listener (required).
    policy_action       : str  – ``REJECT``, ``REDIRECT_TO_POOL``,
                                 ``REDIRECT_TO_URL``, or ``REDIRECT_PREFIX``
                                 (default: ``REJECT``).
    name                : str  – Optional policy name.
    description         : str  – Optional description.
    position            : int  – Evaluation order (default: 1).
    admin_state_up      : bool – Enabled state (default: True).
    redirect_pool_id    : str  – Pool UUID for REDIRECT_TO_POOL.
    redirect_url        : str  – URL for REDIRECT_TO_URL.
    redirect_prefix     : str  – URL prefix for REDIRECT_PREFIX.

    Update / show / delete parameters
    -----------------------------------
    policy_name_or_id : str – Target policy (required).
    Any subset of the create fields above; only supplied keys are patched.

    Returns:
        Action-specific success dict or ``{'success': False, 'message': '...'}``
    """
    if action not in _POLICY_ACTIONS:
        return {
            "success": False,
            "message": (
                f'Unknown action "{action}". '
                f"Supported: {sorted(_POLICY_ACTIONS)}"
            ),
        }

    try:
        conn = get_openstack_connection()

        # ------------------------------------------------------------------ create
        if action == "create":
            listener_name_or_id = kwargs.get("listener_name_or_id", "")
            if not listener_name_or_id:
                return {"success": False, "message": "listener_name_or_id is required for create"}

            listener, err = _find_listener(conn, listener_name_or_id)
            if err:
                return err

            policy_action = kwargs.get("policy_action", "REJECT").upper()
            if policy_action not in _POLICY_ACTION_TYPES:
                return {
                    "success": False,
                    "message": (
                        f'Unknown policy_action "{policy_action}". '
                        f"Supported: {sorted(_POLICY_ACTION_TYPES)}"
                    ),
                }

            params: dict[str, Any] = {
                k: v for k, v in {
                    "listener_id":      listener.id,
                    "action":           policy_action,
                    "name":             kwargs.get("name"),
                    "description":      kwargs.get("description"),
                    "position":         kwargs.get("position", 1),
                    "admin_state_up":   kwargs.get("admin_state_up", True),
                    "redirect_pool_id": kwargs.get("redirect_pool_id"),
                    "redirect_url":     kwargs.get("redirect_url"),
                    "redirect_prefix":  kwargs.get("redirect_prefix"),
                }.items()
                if v is not None and v != ""
            }

            policy = conn.load_balancer.create_l7_policy(**params)
            return {
                "success":   True,
                "message":   "L7 policy created successfully",
                "l7_policy": _build_policy_dict(policy),
            }

        # ------------------------------------------------------------------ delete
        if action == "delete":
            policy_name_or_id = kwargs.get("policy_name_or_id", "")
            if not policy_name_or_id:
                return {"success": False, "message": "policy_name_or_id is required for delete"}

            policy, err = _find_policy(conn, policy_name_or_id)
            if err:
                return err

            conn.load_balancer.delete_l7_policy(policy.id)
            return {"success": True, "message": "L7 policy deleted successfully"}

        # ------------------------------------------------------------------ show
        if action == "show":
            policy_name_or_id = kwargs.get("policy_name_or_id", "")
            if not policy_name_or_id:
                return {"success": False, "message": "policy_name_or_id is required for show"}

            policy, err = _find_policy(conn, policy_name_or_id)
            if err:
                return err

            return {"success": True, "l7_policy": _build_policy_dict(policy)}

        # ------------------------------------------------------------------ update
        if action == "update":
            policy_name_or_id = kwargs.get("policy_name_or_id", "")
            if not policy_name_or_id:
                return {"success": False, "message": "policy_name_or_id is required for update"}

            policy, err = _find_policy(conn, policy_name_or_id)
            if err:
                return err

            update_params = {k: kwargs[k] for k in _POLICY_UPDATE_FIELDS if k in kwargs}
            if not update_params:
                return {
                    "success": False,
                    "message": f"No updatable fields provided. Supported: {sorted(_POLICY_UPDATE_FIELDS)}",
                }

            updated = conn.load_balancer.update_l7_policy(policy.id, **update_params)
            return {
                "success":   True,
                "message":   "L7 policy updated successfully",
                "l7_policy": _build_policy_dict(updated),
            }

    except Exception as exc:
        logger.error("set_load_balancer_l7_policy(%s) failed: %s", action, exc)
        return {"success": False, "message": f"Failed to {action} L7 policy: {exc}"}


# ---------------------------------------------------------------------------
# Public API — rules
# ---------------------------------------------------------------------------

def get_load_balancer_l7_rules(policy_name_or_id: str) -> dict[str, Any]:
    """List L7 rules belonging to a policy.

    Args:
        policy_name_or_id: L7 policy name or UUID (required).

    Returns:
        ``{'success': True, 'l7_rules': [...], 'rule_count': N, 'l7_policy': {...}}``
    """
    try:
        conn = get_openstack_connection()

        policy, err = _find_policy(conn, policy_name_or_id)
        if err:
            return err

        rules = [
            _build_rule_dict(r)
            for r in conn.load_balancer.l7_rules(l7_policy=policy.id)
        ]

        return {
            "success":    True,
            "l7_policy":  {"id": policy.id, "name": getattr(policy, "name", None)},
            "l7_rules":   rules,
            "rule_count": len(rules),
        }

    except Exception as exc:
        logger.error("Failed to get L7 rules: %s", exc)
        return {"success": False, "message": f"Failed to get L7 rules: {exc}"}


def set_load_balancer_l7_rule(action: str, **kwargs) -> dict[str, Any]:
    """Manage L7 rule lifecycle.

    Supported *action* values
    -------------------------
    ``create`` – Add a rule to a policy.
    ``delete`` – Remove a rule by ID.
    ``update`` – Patch specific fields of an existing rule.
    ``show``   – Return full details for one rule.

    Create parameters (via **kwargs)
    ---------------------------------
    policy_name_or_id : str  – Parent policy (required).
    value             : str  – Match value (required).
    type              : str  – ``PATH``, ``HOST_NAME``, ``HEADER``,
                               ``COOKIE``, ``FILE_TYPE`` (default: ``PATH``).
    compare_type      : str  – ``STARTS_WITH``, ``ENDS_WITH``, ``CONTAINS``,
                               ``EQUAL_TO``, ``REGEX`` (default: ``STARTS_WITH``).
    key               : str  – Header/cookie name for HEADER/COOKIE types.
    invert            : bool – Negate the match (default: False).
    admin_state_up    : bool – Enabled state (default: True).

    Delete / update / show parameters
    -----------------------------------
    rule_id           : str – Target rule UUID (required).
    policy_name_or_id : str – Parent policy (required for delete/update/show).

    Returns:
        Action-specific success dict or ``{'success': False, 'message': '...'}``
    """
    if action not in _RULE_ACTIONS:
        return {
            "success": False,
            "message": (
                f'Unknown action "{action}". '
                f"Supported: {sorted(_RULE_ACTIONS)}"
            ),
        }

    try:
        conn = get_openstack_connection()

        # ------------------------------------------------------------------ create
        if action == "create":
            policy_name_or_id = kwargs.get("policy_name_or_id", "")
            value             = kwargs.get("value", "")
            if not policy_name_or_id or not value:
                return {"success": False, "message": "policy_name_or_id and value are required for create"}

            policy, err = _find_policy(conn, policy_name_or_id)
            if err:
                return err

            params: dict[str, Any] = {
                k: v for k, v in {
                    "l7policy_id":    policy.id,
                    "type":           kwargs.get("type", "PATH"),
                    "compare_type":   kwargs.get("compare_type", "STARTS_WITH"),
                    "value":          value,
                    "key":            kwargs.get("key"),
                    "invert":         kwargs.get("invert", False),
                    "admin_state_up": kwargs.get("admin_state_up", True),
                }.items()
                if v is not None
            }

            rule = conn.load_balancer.create_l7_rule(**params)
            return {
                "success": True,
                "message": "L7 rule created successfully",
                "l7_rule": _build_rule_dict(rule),
            }

        # ------------------------------------------------------------------ delete
        if action == "delete":
            rule_id           = kwargs.get("rule_id", "")
            policy_name_or_id = kwargs.get("policy_name_or_id", "")
            if not rule_id or not policy_name_or_id:
                return {"success": False, "message": "rule_id and policy_name_or_id are required for delete"}

            policy, err = _find_policy(conn, policy_name_or_id)
            if err:
                return err

            conn.load_balancer.delete_l7_rule(rule_id, l7_policy=policy.id)
            return {"success": True, "message": "L7 rule deleted successfully"}

        # ------------------------------------------------------------------ show
        if action == "show":
            rule_id           = kwargs.get("rule_id", "")
            policy_name_or_id = kwargs.get("policy_name_or_id", "")
            if not rule_id or not policy_name_or_id:
                return {"success": False, "message": "rule_id and policy_name_or_id are required for show"}

            policy, err = _find_policy(conn, policy_name_or_id)
            if err:
                return err

            rule = conn.load_balancer.get_l7_rule(rule_id, l7_policy=policy.id)
            if not rule:
                return {"success": False, "message": f"L7 rule not found: {rule_id}"}

            return {"success": True, "l7_rule": _build_rule_dict(rule)}

        # ------------------------------------------------------------------ update
        if action == "update":
            rule_id           = kwargs.get("rule_id", "")
            policy_name_or_id = kwargs.get("policy_name_or_id", "")
            if not rule_id or not policy_name_or_id:
                return {"success": False, "message": "rule_id and policy_name_or_id are required for update"}

            policy, err = _find_policy(conn, policy_name_or_id)
            if err:
                return err

            update_params = {k: kwargs[k] for k in _RULE_UPDATE_FIELDS if k in kwargs}
            if not update_params:
                return {
                    "success": False,
                    "message": f"No updatable fields provided. Supported: {sorted(_RULE_UPDATE_FIELDS)}",
                }

            updated = conn.load_balancer.update_l7_rule(
                rule_id, l7_policy=policy.id, **update_params
            )
            return {
                "success": True,
                "message": "L7 rule updated successfully",
                "l7_rule": _build_rule_dict(updated),
            }

    except Exception as exc:
        logger.error("set_load_balancer_l7_rule(%s) failed: %s", action, exc)
        return {"success": False, "message": f"Failed to {action} L7 rule: {exc}"}
