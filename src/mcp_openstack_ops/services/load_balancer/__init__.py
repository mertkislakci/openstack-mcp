"""
Load Balancer Service Package (Octavia)

Provides full Octavia LB management via lazy-loaded sub-modules.
All public symbols are listed in __all__; private helpers (_*) are excluded.

Sub-modules
-----------
core            : CRUD operations on load-balancer objects
listeners       : Listener (frontend) management
pools           : Pool + member management
health_monitors : Health-monitor configuration
l7_policies     : Layer-7 policy and rule management
management      : AZ, flavor, quota, and provider operations
amphorae        : Amphora instance management
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------

__all__ = [
    # core
    "get_load_balancer_list",
    "get_load_balancer_details",
    "set_load_balancer",
    # listeners
    "get_load_balancer_listeners",
    "set_load_balancer_listener",
    # pools & members
    "get_load_balancer_pools",
    "set_load_balancer_pool",
    "get_load_balancer_pool_members",
    "set_load_balancer_pool_member",
    # health monitors
    "get_load_balancer_health_monitors",
    "set_load_balancer_health_monitor",
    # l7 policies & rules
    "get_load_balancer_l7_policies",
    "set_load_balancer_l7_policy",
    "get_load_balancer_l7_rules",
    "set_load_balancer_l7_rule",
    # management
    "get_load_balancer_availability_zones",
    "set_load_balancer_availability_zone",
    "get_load_balancer_flavors",
    "set_load_balancer_flavor",
    "get_load_balancer_providers",
    "get_load_balancer_quotas",
    "set_load_balancer_quota",
    # amphorae
    "get_load_balancer_amphorae",
    "set_load_balancer_amphora",
]

# ---------------------------------------------------------------------------
# Lazy-import map  →  symbol: (sub_module, attr_in_module)
# Modules are imported only on first attribute access, not at package load.
# This keeps MCP server startup time low when only a subset of tools is used.
# ---------------------------------------------------------------------------

_LAZY: dict[str, tuple[str, str]] = {
    # core
    "get_load_balancer_list":           ("core",            "get_load_balancer_list"),
    "get_load_balancer_details":        ("core",            "get_load_balancer_details"),
    "set_load_balancer":                ("core",            "set_load_balancer"),
    # listeners
    "get_load_balancer_listeners":      ("listeners",       "get_load_balancer_listeners"),
    "set_load_balancer_listener":       ("listeners",       "set_load_balancer_listener"),
    # pools & members
    "get_load_balancer_pools":          ("pools",           "get_load_balancer_pools"),
    "set_load_balancer_pool":           ("pools",           "set_load_balancer_pool"),
    "get_load_balancer_pool_members":   ("pools",           "get_load_balancer_pool_members"),
    "set_load_balancer_pool_member":    ("pools",           "set_load_balancer_pool_member"),
    # health monitors
    "get_load_balancer_health_monitors": ("health_monitors", "get_load_balancer_health_monitors"),
    "set_load_balancer_health_monitor":  ("health_monitors", "set_load_balancer_health_monitor"),
    # l7 policies & rules
    "get_load_balancer_l7_policies":    ("l7_policies",     "get_load_balancer_l7_policies"),
    "set_load_balancer_l7_policy":      ("l7_policies",     "set_load_balancer_l7_policy"),
    "get_load_balancer_l7_rules":       ("l7_policies",     "get_load_balancer_l7_rules"),
    "set_load_balancer_l7_rule":        ("l7_policies",     "set_load_balancer_l7_rule"),
    # management
    "get_load_balancer_availability_zones": ("management",  "get_load_balancer_availability_zones"),
    "set_load_balancer_availability_zone":  ("management",  "set_load_balancer_availability_zone"),
    "get_load_balancer_flavors":        ("management",      "get_load_balancer_flavors"),
    "set_load_balancer_flavor":         ("management",      "set_load_balancer_flavor"),
    "get_load_balancer_providers":      ("management",      "get_load_balancer_providers"),
    "get_load_balancer_quotas":         ("management",      "get_load_balancer_quotas"),
    "set_load_balancer_quota":          ("management",      "set_load_balancer_quota"),
    # amphorae
    "get_load_balancer_amphorae":       ("amphorae",        "get_load_balancer_amphorae"),
    "set_load_balancer_amphora":        ("amphorae",        "set_load_balancer_amphora"),
}

# Cache of already-imported sub-modules  {module_name: module_object}
_MODULE_CACHE: dict[str, object] = {}


def __getattr__(name: str) -> object:
    """Resolve public symbols on first access (PEP 562 lazy imports)."""
    if name not in _LAZY:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    sub_module_name, attr = _LAZY[name]

    if sub_module_name not in _MODULE_CACHE:
        import importlib
        _MODULE_CACHE[sub_module_name] = importlib.import_module(
            f".{sub_module_name}", package=__name__
        )

    obj = getattr(_MODULE_CACHE[sub_module_name], attr)
    # Cache on the package namespace so subsequent access is O(1) dict lookup
    globals()[name] = obj
    return obj


# ---------------------------------------------------------------------------
# Static type-checker support: re-export for IDEs / mypy without runtime cost
# ---------------------------------------------------------------------------

if TYPE_CHECKING:
    from .core import (
        get_load_balancer_list,
        get_load_balancer_details,
        set_load_balancer,
    )
    from .listeners import (
        get_load_balancer_listeners,
        set_load_balancer_listener,
    )
    from .pools import (
        get_load_balancer_pools,
        set_load_balancer_pool,
        get_load_balancer_pool_members,
        set_load_balancer_pool_member,
    )
    from .health_monitors import (
        get_load_balancer_health_monitors,
        set_load_balancer_health_monitor,
    )
    from .l7_policies import (
        get_load_balancer_l7_policies,
        set_load_balancer_l7_policy,
        get_load_balancer_l7_rules,
        set_load_balancer_l7_rule,
    )
    from .management import (
        get_load_balancer_availability_zones,
        set_load_balancer_availability_zone,
        get_load_balancer_flavors,
        set_load_balancer_flavor,
        get_load_balancer_providers,
        get_load_balancer_quotas,
        set_load_balancer_quota,
    )
    from .amphorae import (
        get_load_balancer_amphorae,
        set_load_balancer_amphora,
    )
