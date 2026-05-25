"""
OpenStack MCP Services

This package re-exports all public service functions grouped by OpenStack
service area.  Sub-modules are imported lazily (PEP 562) so that MCP server
startup time stays low when only a subset of services is used.

Service modules
---------------
core          : Cluster / service health
compute       : Nova – instances, flavours, server groups, events
storage       : Cinder – volumes, snapshots, backups, QoS, groups
network       : Neutron – networks, security groups, floating IPs, routers
load_balancer : Octavia – LBs, listeners, pools, members, HMs, L7, quotas
identity      : Keystone – projects, users, roles, key pairs
orchestration : Heat – stacks
image         : Glance – images, members, metadata, visibility
monitoring    : Quotas, hypervisors, resource usage, availability zones
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------

__all__ = [
    # core
    "get_service_status",

    # compute
    "get_instance_details",
    "get_instance_by_name",
    "get_instance_by_id",
    "search_instances",
    "get_instances_by_status",
    "set_instance",
    "get_flavor_list",
    "set_flavor",
    "get_server_events",
    "get_server_groups",
    "set_server_group",

    # storage
    "get_volume_list",
    "set_volume",
    "get_volume_types",
    "get_volume_snapshots",
    "set_snapshot",
    "set_volume_backups",
    "set_volume_groups",
    "set_volume_qos",
    "get_server_volumes",
    "set_server_volume",

    # network
    "get_network_details",
    "get_security_groups",
    "get_floating_ips",
    "set_floating_ip",
    "get_routers",
    "set_network_ports",
    "set_subnets",

    # load_balancer
    "get_load_balancer_list",
    "get_load_balancer_details",
    "set_load_balancer",
    "get_load_balancer_listeners",
    "set_load_balancer_listener",
    "get_load_balancer_pools",
    "set_load_balancer_pool",
    "get_load_balancer_pool_members",
    "set_load_balancer_pool_member",
    "get_load_balancer_health_monitors",
    "set_load_balancer_health_monitor",
    "get_load_balancer_l7_policies",
    "set_load_balancer_l7_policy",
    "get_load_balancer_l7_rules",
    "set_load_balancer_l7_rule",
    "get_load_balancer_amphorae",
    "set_load_balancer_amphora",
    "get_load_balancer_availability_zones",
    "set_load_balancer_availability_zone",
    "get_load_balancer_flavors",
    "set_load_balancer_flavor",
    "get_load_balancer_providers",
    "get_load_balancer_quotas",
    "set_load_balancer_quota",

    # identity
    "get_project_info",
    "get_project_details",
    "set_project",
    "get_user_list",
    "get_role_assignments",
    "get_keypair_list",
    "set_keypair",

    # orchestration
    "get_heat_stacks",
    "set_heat_stack",

    # image
    "get_image_list",
    "get_image_detail_list",
    "set_image",
    "set_image_members",
    "set_image_metadata",
    "set_image_visibility",

    # monitoring
    "get_resource_monitoring",
    "get_usage_statistics",
    "get_quota",
    "set_quota",
    "get_compute_quota_usage",
    "get_hypervisor_details",
    "get_availability_zones",
]

# ---------------------------------------------------------------------------
# Lazy-import map  { symbol: (sub_module, attr_in_module) }
# Modules are imported only on first attribute access (PEP 562).
# ---------------------------------------------------------------------------

_LAZY: dict[str, tuple[str, str]] = {
    # --- core ---------------------------------------------------------------
    "get_service_status":                   ("core",          "get_service_status"),

    # --- compute ------------------------------------------------------------
    "get_instance_details":                 ("compute",       "get_instance_details"),
    "get_instance_by_name":                 ("compute",       "get_instance_by_name"),
    "get_instance_by_id":                   ("compute",       "get_instance_by_id"),
    "search_instances":                     ("compute",       "search_instances"),
    "get_instances_by_status":              ("compute",       "get_instances_by_status"),
    "set_instance":                         ("compute",       "set_instance"),
    "get_flavor_list":                      ("compute",       "get_flavor_list"),
    "set_flavor":                           ("compute",       "set_flavor"),
    "get_server_events":                    ("compute",       "get_server_events"),
    "get_server_groups":                    ("compute",       "get_server_groups"),
    "set_server_group":                     ("compute",       "set_server_group"),

    # --- storage ------------------------------------------------------------
    "get_volume_list":                      ("storage",       "get_volume_list"),
    "set_volume":                           ("storage",       "set_volume"),
    "get_volume_types":                     ("storage",       "get_volume_types"),
    "get_volume_snapshots":                 ("storage",       "get_volume_snapshots"),
    "set_snapshot":                         ("storage",       "set_snapshot"),
    "set_volume_backups":                   ("storage",       "set_volume_backups"),
    "set_volume_groups":                    ("storage",       "set_volume_groups"),
    "set_volume_qos":                       ("storage",       "set_volume_qos"),
    "get_server_volumes":                   ("storage",       "get_server_volumes"),
    "set_server_volume":                    ("storage",       "set_server_volume"),

    # --- network ------------------------------------------------------------
    "get_network_details":                  ("network",       "get_network_details"),
    "get_security_groups":                  ("network",       "get_security_groups"),
    "get_floating_ips":                     ("network",       "get_floating_ips"),
    "set_floating_ip":                      ("network",       "set_floating_ip"),
    "get_routers":                          ("network",       "get_routers"),
    "set_network_ports":                    ("network",       "set_network_ports"),
    "set_subnets":                          ("network",       "set_subnets"),

    # --- load_balancer ------------------------------------------------------
    "get_load_balancer_list":               ("load_balancer", "get_load_balancer_list"),
    "get_load_balancer_details":            ("load_balancer", "get_load_balancer_details"),
    "set_load_balancer":                    ("load_balancer", "set_load_balancer"),
    "get_load_balancer_listeners":          ("load_balancer", "get_load_balancer_listeners"),
    "set_load_balancer_listener":           ("load_balancer", "set_load_balancer_listener"),
    "get_load_balancer_pools":              ("load_balancer", "get_load_balancer_pools"),
    "set_load_balancer_pool":               ("load_balancer", "set_load_balancer_pool"),
    "get_load_balancer_pool_members":       ("load_balancer", "get_load_balancer_pool_members"),
    "set_load_balancer_pool_member":        ("load_balancer", "set_load_balancer_pool_member"),
    "get_load_balancer_health_monitors":    ("load_balancer", "get_load_balancer_health_monitors"),
    "set_load_balancer_health_monitor":     ("load_balancer", "set_load_balancer_health_monitor"),
    "get_load_balancer_l7_policies":        ("load_balancer", "get_load_balancer_l7_policies"),
    "set_load_balancer_l7_policy":          ("load_balancer", "set_load_balancer_l7_policy"),
    "get_load_balancer_l7_rules":           ("load_balancer", "get_load_balancer_l7_rules"),
    "set_load_balancer_l7_rule":            ("load_balancer", "set_load_balancer_l7_rule"),
    "get_load_balancer_amphorae":           ("load_balancer", "get_load_balancer_amphorae"),
    "set_load_balancer_amphora":            ("load_balancer", "set_load_balancer_amphora"),
    "get_load_balancer_availability_zones": ("load_balancer", "get_load_balancer_availability_zones"),
    "set_load_balancer_availability_zone":  ("load_balancer", "set_load_balancer_availability_zone"),
    "get_load_balancer_flavors":            ("load_balancer", "get_load_balancer_flavors"),
    "set_load_balancer_flavor":             ("load_balancer", "set_load_balancer_flavor"),
    "get_load_balancer_providers":          ("load_balancer", "get_load_balancer_providers"),
    "get_load_balancer_quotas":             ("load_balancer", "get_load_balancer_quotas"),
    "set_load_balancer_quota":              ("load_balancer", "set_load_balancer_quota"),

    # --- identity -----------------------------------------------------------
    "get_project_info":                     ("identity",      "get_project_info"),
    "get_project_details":                  ("identity",      "get_project_details"),
    "set_project":                          ("identity",      "set_project"),
    "get_user_list":                        ("identity",      "get_user_list"),
    "get_role_assignments":                 ("identity",      "get_role_assignments"),
    "get_keypair_list":                     ("identity",      "get_keypair_list"),
    "set_keypair":                          ("identity",      "set_keypair"),

    # --- orchestration ------------------------------------------------------
    "get_heat_stacks":                      ("orchestration", "get_heat_stacks"),
    "set_heat_stack":                       ("orchestration", "set_heat_stack"),

    # --- image --------------------------------------------------------------
    "get_image_list":                       ("image",         "get_image_list"),
    "get_image_detail_list":                ("image",         "get_image_detail_list"),
    "set_image":                            ("image",         "set_image"),
    "set_image_members":                    ("image",         "set_image_members"),
    "set_image_metadata":                   ("image",         "set_image_metadata"),
    "set_image_visibility":                 ("image",         "set_image_visibility"),

    # --- monitoring ---------------------------------------------------------
    "get_resource_monitoring":              ("monitoring",    "get_resource_monitoring"),
    "get_usage_statistics":                 ("monitoring",    "get_usage_statistics"),
    "get_quota":                            ("monitoring",    "get_quota"),
    "set_quota":                            ("monitoring",    "set_quota"),
    "get_compute_quota_usage":              ("monitoring",    "get_compute_quota_usage"),
    "get_hypervisor_details":               ("monitoring",    "get_hypervisor_details"),
    "get_availability_zones":               ("monitoring",    "get_availability_zones"),
}

# Cache: { sub_module_name: module_object }
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
    # Cache on the package namespace — subsequent access is O(1) dict lookup
    globals()[name] = obj
    return obj


# ---------------------------------------------------------------------------
# Static type-checker support (mypy / pyright) — zero runtime cost
# ---------------------------------------------------------------------------

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import get_service_status
    from .compute import (
        get_instance_details, get_instance_by_name, get_instance_by_id,
        search_instances, get_instances_by_status, set_instance,
        get_flavor_list, set_flavor,
        get_server_events, get_server_groups, set_server_group,
    )
    from .storage import (
        get_volume_list, set_volume, get_volume_types, get_volume_snapshots,
        set_snapshot, set_volume_backups, set_volume_groups, set_volume_qos,
        get_server_volumes, set_server_volume,
    )
    from .network import (
        get_network_details, get_security_groups, get_floating_ips,
        set_floating_ip, get_routers, set_network_ports, set_subnets,
    )
    from .load_balancer import (
        get_load_balancer_list, get_load_balancer_details, set_load_balancer,
        get_load_balancer_listeners, set_load_balancer_listener,
        get_load_balancer_pools, set_load_balancer_pool,
        get_load_balancer_pool_members, set_load_balancer_pool_member,
        get_load_balancer_health_monitors, set_load_balancer_health_monitor,
        get_load_balancer_l7_policies, set_load_balancer_l7_policy,
        get_load_balancer_l7_rules, set_load_balancer_l7_rule,
        get_load_balancer_amphorae, set_load_balancer_amphora,
        get_load_balancer_availability_zones, set_load_balancer_availability_zone,
        get_load_balancer_flavors, set_load_balancer_flavor,
        get_load_balancer_providers, get_load_balancer_quotas, set_load_balancer_quota,
    )
    from .identity import (
        get_project_info, get_project_details, set_project,
        get_user_list, get_role_assignments, get_keypair_list, set_keypair,
    )
    from .orchestration import get_heat_stacks, set_heat_stack
    from .image import (
        get_image_list, get_image_detail_list, set_image,
        set_image_members, set_image_metadata, set_image_visibility,
    )
    from .monitoring import (
        get_resource_monitoring, get_usage_statistics,
        get_quota, set_quota, get_compute_quota_usage,
        get_hypervisor_details, get_availability_zones,
    )
