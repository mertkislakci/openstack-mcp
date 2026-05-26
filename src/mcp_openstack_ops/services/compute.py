"""
OpenStack Compute (Nova) Service Functions

Manages instances, flavours, server groups, events, and related compute
resources.  All SDK calls are scoped to the authenticated project;
cross-project access is blocked by the Nova API unless the caller has
admin rights.

Public API
----------
get_instance_details      – paginated / name-filtered instance list
get_instance_by_name      – single instance lookup by name  (uses SDK directly)
get_instance_by_id        – single instance lookup by UUID  (uses SDK directly)
search_instances          – free-text search across instance fields
get_instances_by_status   – SDK server-side status filter
set_instance              – full instance lifecycle management
get_flavor_list           – list available flavours
set_flavor                – create / delete / set_extra_specs a flavour
get_server_events         – server action / event history
get_server_groups         – list server groups
set_server_group          – create / delete / show / list server groups

Internal helpers (not exported)
--------------------------------
_ts, _find_server, _find_network, _find_sg, _find_flavor_obj,
_find_image_obj, _build_flavor_info, _build_instance_dict,
_build_sg_list, _build_network_list
"""

from __future__ import annotations

import logging
from typing import Any

from ..connection import (
    get_openstack_connection,
    get_current_project_id,
    validate_resource_ownership,
    find_resource_by_name_or_id,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_INSTANCE_ACTIONS: frozenset[str] = frozenset({
    "create", "start", "stop", "reboot", "pause", "unpause",
    "suspend", "resume", "delete", "resize", "confirm_resize",
    "revert_resize", "snapshot", "console", "shelve", "unshelve",
    "lock", "unlock", "rescue", "unrescue", "rebuild", "list",
})

_FLAVOR_ACTIONS: frozenset[str] = frozenset({
    "list", "create", "delete", "set_extra_specs",
})

_SERVER_GROUP_ACTIONS: frozenset[str] = frozenset({
    "list", "create", "delete", "show",
})

_VALID_GROUP_POLICIES: frozenset[str] = frozenset({
    "affinity", "anti-affinity", "soft-affinity", "soft-anti-affinity",
})

_MIGRATION_ACTIONS: frozenset[str] = frozenset({
    "migrate", "evacuate", "confirm", "revert",
    "list", "show", "abort", "force_complete",
})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ts(obj: Any, attr: str) -> str | None:
    """Return ISO-8601 string for *attr* on *obj*, or None if absent."""
    val = getattr(obj, attr, None)
    return str(val) if val is not None else None


def _find_server(conn: Any, name_or_id: str) -> tuple[Any | None, dict | None]:
    """Return ``(server, None)`` or ``(None, error_dict)`` via SDK find."""
    server = conn.compute.find_server(name_or_id)
    if server is None:
        return None, {
            "success": False,
            "message": f'Instance "{name_or_id}" not found or not accessible',
        }
    return server, None


def _find_network(conn: Any, name_or_id: str) -> tuple[Any | None, dict | None]:
    """Return ``(network, None)`` or ``(None, error_dict)``."""
    net = conn.network.find_network(name_or_id)
    if net is None:
        return None, {"success": False, "message": f'Network "{name_or_id}" not found'}
    return net, None


def _find_sg(conn: Any, name_or_id: str) -> tuple[Any | None, dict | None]:
    """Return ``(security_group, None)`` or ``(None, error_dict)``."""
    sg = conn.network.find_security_group(name_or_id)
    if sg is None:
        return None, {
            "success": False,
            "message": f'Security group "{name_or_id}" not found',
        }
    return sg, None


def _find_flavor_obj(conn: Any, name_or_id: str) -> tuple[Any | None, dict | None]:
    """Return ``(flavor, None)`` or ``(None, error_dict)``."""
    flavor = conn.compute.find_flavor(name_or_id)
    if flavor is None:
        return None, {"success": False, "message": f'Flavor "{name_or_id}" not found'}
    return flavor, None


def _find_image_obj(conn: Any, name_or_id: str) -> tuple[Any | None, dict | None]:
    """Return ``(image, None)`` or ``(None, error_dict)``."""
    image = conn.image.find_image(name_or_id)
    if image is None:
        return None, {"success": False, "message": f'Image "{name_or_id}" not found'}
    return image, None


def _build_flavor_info(server: Any) -> dict[str, Any]:
    """Extract embedded flavour info from a server object."""
    fl = getattr(server, "flavor", None)
    if not fl:
        return {"id": None, "name": None, "vcpus": 0, "ram": 0, "disk": 0}
    if isinstance(fl, dict):
        return {
            "id":    fl.get("id"),
            "name":  fl.get("original_name", fl.get("name")),
            "vcpus": fl.get("vcpus", 0),
            "ram":   fl.get("ram", 0),
            "disk":  fl.get("disk", 0),
        }
    return {
        "id":    getattr(fl, "id", None),
        "name":  getattr(fl, "original_name", getattr(fl, "name", None)),
        "vcpus": getattr(fl, "vcpus", 0),
        "ram":   getattr(fl, "ram", 0),
        "disk":  getattr(fl, "disk", 0),
    }


def _build_network_list(server: Any) -> list[dict]:
    """Build structured network/address list from server.addresses."""
    networks: list[dict] = []
    for net_name, addrs in (getattr(server, "addresses", {}) or {}).items():
        entry: dict[str, Any] = {"network": net_name, "addresses": []}
        for addr in addrs:
            if isinstance(addr, dict):
                entry["addresses"].append({
                    "addr":     addr.get("addr"),
                    "type":     addr.get("OS-EXT-IPS:type"),
                    "version":  addr.get("version", 4),
                    "mac_addr": addr.get("OS-EXT-IPS-MAC:mac_addr"),
                })
            else:
                entry["addresses"].append({"addr": str(addr), "type": None})
        networks.append(entry)
    return networks


def _build_sg_list(server: Any) -> list[str]:
    """Extract security-group names from a server object."""
    out: list[str] = []
    for sg in getattr(server, "security_groups", []) or []:
        out.append(sg.get("name") if isinstance(sg, dict) else getattr(sg, "name", None))
    return out


def _build_instance_dict(server: Any, conn: Any | None = None) -> dict[str, Any]:
    """Normalise a raw SDK Server object into a consistent dict.

    When *conn* is supplied, image details are fetched from Glance; otherwise
    only the embedded image ID is used.
    """
    # Image info
    image_info: dict[str, Any] = {"id": None, "name": None}
    raw_img = getattr(server, "image", None)
    if raw_img:
        img_id = raw_img.get("id") if isinstance(raw_img, dict) else getattr(raw_img, "id", None)
        image_info["id"] = img_id
        if conn and img_id:
            try:
                img = conn.image.get_image(img_id)
                image_info["name"] = getattr(img, "name", None)
            except Exception as exc:
                logger.warning("Could not fetch image %s: %s", img_id, exc)

    # Volume attachments
    volumes = getattr(server, "attached_volumes",
                      getattr(server, "volumes_attached", []))
    vol_ids = [v.get("id", v) if isinstance(v, dict) else str(v) for v in volumes]

    return {
        "id":                  server.id,
        "name":                getattr(server, "name", None),
        "status":              getattr(server, "status", None),
        "power_state":         getattr(server, "power_state", 0),
        "task_state":          getattr(server, "task_state", None),
        "vm_state":            getattr(server, "vm_state", None),
        "created":             _ts(server, "created_at"),
        "updated":             _ts(server, "updated_at"),
        "launched_at":         _ts(server, "launched_at"),
        "host":                getattr(server, "host", None),
        "hypervisor_hostname": getattr(server, "hypervisor_hostname", None),
        "availability_zone":   getattr(server, "availability_zone", None),
        "flavor":              _build_flavor_info(server),
        "image":               image_info,
        "key_name":            getattr(server, "key_name", None),
        "networks":            _build_network_list(server),
        "security_groups":     _build_sg_list(server),
        "tenant_id":           getattr(server, "tenant_id",
                                       getattr(server, "project_id", None)),
        "user_id":             getattr(server, "user_id", None),
        "metadata":            getattr(server, "metadata", {}),
        "fault":               getattr(server, "fault", None),
        "progress":            getattr(server, "progress", 0),
        "config_drive":        getattr(server, "config_drive", False),
        "locked":              getattr(server, "locked", False),
        "attached_volumes":    vol_ids,
    }


# ---------------------------------------------------------------------------
# Public API — instances
# ---------------------------------------------------------------------------

def get_instance_details(
    instance_names: list[str] | None = None,
    limit: int = 50,
    offset: int = 0,
    include_all: bool = False,
) -> dict[str, Any]:
    """Return paginated instance list scoped to the authenticated project.

    Args:
        instance_names: Filter to these names/UUIDs (optional).
        limit:          Max items per page (1–200, default 50).
        offset:         Items to skip (default 0).
        include_all:    Return all instances ignoring pagination.
    """
    try:
        conn = get_openstack_connection()
        current_project_id = get_current_project_id()

        limit = max(1, min(limit, 200))

        all_servers = [
            s for s in conn.compute.servers(details=True, all_projects=False)
            if validate_resource_ownership(s, "Instance")
        ]

        if instance_names:
            all_servers = [
                s for s in all_servers
                if getattr(s, "name", "") in instance_names or s.id in instance_names
            ]

        total_count = len(all_servers)
        page = all_servers if include_all else all_servers[offset: offset + limit]

        instances: list[dict] = []
        for server in page:
            try:
                instances.append(_build_instance_dict(server, conn))
            except Exception as exc:
                logger.error("Failed to process server %s: %s", server.id, exc)
                instances.append({
                    "id":     server.id,
                    "name":   getattr(server, "name", None),
                    "status": "error",
                    "error":  str(exc),
                })

        result: dict[str, Any] = {
            "instances":    instances,
            "count":        len(instances),
            "total_count":  total_count,
            "limit":        limit,
            "offset":       offset,
            "has_next":     (offset + limit) < total_count,
            "has_prev":     offset > 0,
            "next_offset":  (offset + limit) if (offset + limit) < total_count else None,
            "prev_offset":  max(0, offset - limit) if offset > 0 else None,
        }
        if instance_names:
            result["filtered_by_names"] = instance_names
        return result

    except Exception as exc:
        logger.error("Failed to get instance details: %s", exc)
        return {
            "instances": [], "count": 0, "total_count": 0,
            "success": False, "error": str(exc),
        }


def get_instance_by_name(instance_name: str) -> dict[str, Any] | None:
    """Return one instance dict by name, or None.  Uses SDK find (fast)."""
    try:
        conn = get_openstack_connection()
        server = conn.compute.find_server(instance_name)
        return _build_instance_dict(server, conn) if server else None
    except Exception as exc:
        logger.error("Failed to get instance by name %s: %s", instance_name, exc)
        return None


def get_instance_by_id(instance_id: str) -> dict[str, Any] | None:
    """Return one instance dict by UUID, or None.  Uses SDK find (fast)."""
    try:
        conn = get_openstack_connection()
        server = conn.compute.find_server(instance_id)
        return _build_instance_dict(server, conn) if server else None
    except Exception as exc:
        logger.error("Failed to get instance by ID %s: %s", instance_id, exc)
        return None


def search_instances(
    search_term: str,
    search_fields: list[str] | None = None,
    limit: int = 50,
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    """Free-text search across instance fields.

    Args:
        search_term:     Substring to match (case-insensitive).
        search_fields:   Fields to search: ``name``, ``id``, ``ip``,
                         ``flavor_name``, ``image_name`` (default: name, id).
        limit:           Max results.
        include_inactive: Include non-ACTIVE instances.
    """
    try:
        if search_fields is None:
            search_fields = ["name", "id"]

        all_result = get_instance_details(include_all=True)
        term = search_term.lower()
        matching: list[dict] = []

        for inst in all_result.get("instances", []):
            if not include_inactive and inst.get("status", "").lower() not in ("active", "running"):
                continue

            found = False
            for field in search_fields:
                if field == "ip":
                    for net in inst.get("networks", []):
                        if any(term in (a.get("addr") or "").lower() for a in net.get("addresses", [])):
                            found = True
                            break
                elif field == "flavor_name":
                    found = term in str(inst.get("flavor", {}).get("name") or "").lower()
                elif field == "image_name":
                    found = term in str(inst.get("image", {}).get("name") or "").lower()
                else:
                    found = term in str(inst.get(field) or "").lower()

                if found:
                    break

            if found:
                matching.append(inst)
            if len(matching) >= limit:
                break

        return matching

    except Exception as exc:
        logger.error("Failed to search instances: %s", exc)
        return []


def get_instances_by_status(status: str) -> list[dict[str, Any]]:
    """Return instances matching *status*.  Filtering is done server-side."""
    try:
        conn = get_openstack_connection()
        # Nova supports server-side status filter — avoids fetching all instances
        servers = conn.compute.servers(details=True, status=status.upper(), all_projects=False)
        return [_build_instance_dict(s, conn) for s in servers
                if validate_resource_ownership(s, "Instance")]
    except Exception as exc:
        logger.error("Failed to get instances by status %s: %s", status, exc)
        return []


def set_instance(instance_name: str, action: str, **kwargs) -> dict[str, Any]:
    """Full instance lifecycle management.

    Supported *action* values
    -------------------------
    ``create``         – Provision a new VM.
    ``start``          – Power on a stopped instance.
    ``stop``           – Gracefully power off.
    ``reboot``         – Soft or hard reboot (``type`` kwarg).
    ``pause``          – Freeze in memory.
    ``unpause``        – Resume frozen instance.
    ``suspend``        – Save state to disk.
    ``resume``         – Restore suspended instance.
    ``delete``         – Delete (``force=True`` for force-delete).
    ``resize``         – Live resize to a new flavour (``flavor`` kwarg).
    ``confirm_resize`` – Accept pending resize.
    ``revert_resize``  – Roll back pending resize.
    ``snapshot``       – Create a VM image (``snapshot_name`` kwarg).
    ``console``        – Get console URL (``type`` kwarg, default novnc).
    ``shelve``         – Shelve instance (store image, free compute).
    ``unshelve``       – Restore shelved instance.
    ``lock``           – Prevent accidental operations.
    ``unlock``         – Remove lock.
    ``rescue``         – Boot into rescue image.
    ``unrescue``       – Return from rescue mode.
    ``rebuild``        – Rebuild from a new image (``image`` kwarg).
    ``list``           – Return paginated list (delegates to get_instance_details).
    """
    if action.lower() not in _INSTANCE_ACTIONS:
        return {
            "success": False,
            "message": (
                f'Unknown action "{action}". '
                f"Supported: {sorted(_INSTANCE_ACTIONS)}"
            ),
        }

    try:
        conn = get_openstack_connection()

        # ------------------------------------------------------------------ list
        if action.lower() == "list":
            result = get_instance_details(limit=kwargs.get("limit", 50))
            return {
                "success":     True,
                "instances":   result.get("instances", []),
                "count":       result.get("count", 0),
                "total_count": result.get("total_count", 0),
            }

        # ------------------------------------------------------------------ create
        if action.lower() == "create":
            flavor_name  = kwargs.get("flavor", kwargs.get("flavor_name"))
            image_name   = kwargs.get("image",  kwargs.get("image_name"))
            network_names = kwargs.get("networks", kwargs.get("network_names", []))

            if not flavor_name:
                return {"success": False, "message": "flavor is required for create"}
            if not image_name:
                return {"success": False, "message": "image is required for create"}

            flavor, err = _find_flavor_obj(conn, flavor_name)
            if err:
                return err
            image, err = _find_image_obj(conn, image_name)
            if err:
                return err

            # Resolve networks
            networks: list[dict] = []
            if isinstance(network_names, str):
                network_names = [network_names]
            for net_name in network_names:
                net = find_resource_by_name_or_id(conn.network.networks(), net_name, "Network")
                if not net:
                    return {"success": False, "message": f'Network "{net_name}" not found'}
                networks.append({"uuid": net.id})

            # Build params — skip None/empty
            sg_input = kwargs.get("security_groups", kwargs.get("security_group"))
            if isinstance(sg_input, str):
                sg_input = [sg_input]

            create_params: dict[str, Any] = {
                k: v for k, v in {
                    "name":              instance_name,
                    "flavor_id":         flavor.id,
                    "image_id":          image.id,
                    "networks":          networks or None,
                    "key_name":          kwargs.get("key_name", kwargs.get("keypair")),
                    "security_groups":   [{"name": sg} for sg in sg_input] if sg_input else None,
                    "availability_zone": kwargs.get("availability_zone", kwargs.get("az")),
                    "user_data":         kwargs.get("user_data"),
                    "metadata":          kwargs.get("metadata") or None,
                }.items()
                if v is not None
            }

            server = conn.compute.create_server(**create_params)
            return {
                "success":  True,
                "message":  f'Instance "{instance_name}" creation started',
                "instance": {
                    "id":     server.id,
                    "name":   getattr(server, "name", None),
                    "status": getattr(server, "status", None),
                    "flavor": {"id": flavor.id, "name": getattr(flavor, "name", None)},
                    "image":  {"id": image.id,  "name": getattr(image,  "name", None)},
                },
            }

        # All other actions need an existing server
        server, err = _find_server(conn, instance_name)
        if err:
            return err

        # ------------------------------------------------------------------ simple actions
        simple: dict[str, Any] = {
            "start":    lambda: conn.compute.start_server(server),
            "stop":     lambda: conn.compute.stop_server(server),
            "pause":    lambda: conn.compute.pause_server(server),
            "unpause":  lambda: conn.compute.unpause_server(server),
            "suspend":  lambda: conn.compute.suspend_server(server),
            "resume":   lambda: conn.compute.resume_server(server),
            "shelve":   lambda: conn.compute.shelve_server(server),
            "unshelve": lambda: conn.compute.unshelve_server(server),
            "lock":     lambda: conn.compute.lock_server(server),
            "unlock":   lambda: conn.compute.unlock_server(server),
            "unrescue": lambda: conn.compute.unrescue_server(server),
            "confirm_resize": lambda: conn.compute.confirm_server_resize(server),
            "revert_resize":  lambda: conn.compute.revert_server_resize(server),
        }
        act = action.lower()
        if act in simple:
            simple[act]()
            return {"success": True, "message": f'Instance "{instance_name}" {act} completed'}

        # ------------------------------------------------------------------ reboot
        if act == "reboot":
            conn.compute.reboot_server(server, kwargs.get("type", "SOFT"))
            return {"success": True, "message": f'Instance "{instance_name}" reboot initiated'}

        # ------------------------------------------------------------------ delete
        if act == "delete":
            if kwargs.get("force"):
                conn.compute.force_delete_server(server)
                return {"success": True, "message": f'Instance "{instance_name}" force-deleted'}
            conn.compute.delete_server(server)
            return {"success": True, "message": f'Instance "{instance_name}" deleted'}

        # ------------------------------------------------------------------ resize
        if act == "resize":
            new_flavor_name = kwargs.get("flavor", kwargs.get("new_flavor"))
            if not new_flavor_name:
                return {"success": False, "message": "flavor is required for resize"}
            new_flavor, err = _find_flavor_obj(conn, new_flavor_name)
            if err:
                return err
            conn.compute.resize_server(server, new_flavor.id)
            return {"success": True, "message": f'Resize to "{new_flavor_name}" initiated'}

        # ------------------------------------------------------------------ snapshot
        if act == "snapshot":
            snap_name = kwargs.get("snapshot_name", f"{instance_name}-snapshot")
            snap_id = conn.compute.create_server_image(
                server, name=snap_name, metadata=kwargs.get("metadata", {})
            )
            return {"success": True, "message": f'Snapshot "{snap_name}" initiated', "snapshot_id": snap_id}

        # ------------------------------------------------------------------ console
        if act == "console":
            console = conn.compute.get_server_console_url(server, kwargs.get("type", "novnc"))
            return {"success": True, "console": {"type": kwargs.get("type", "novnc"), "url": console.get("url")}}

        # ------------------------------------------------------------------ rescue
        if act == "rescue":
            rescue_params = {k: v for k, v in {
                "image_id":   kwargs.get("rescue_image_id"),
                "admin_pass": kwargs.get("admin_pass"),
            }.items() if v is not None}
            conn.compute.rescue_server(server, **rescue_params)
            return {"success": True, "message": f'Instance "{instance_name}" in rescue mode'}

        # ------------------------------------------------------------------ rebuild
        if act == "rebuild":
            image_name = kwargs.get("image", kwargs.get("image_name"))
            if not image_name:
                return {"success": False, "message": "image is required for rebuild"}
            image, err = _find_image_obj(conn, image_name)
            if err:
                return err
            rebuild_params = {k: v for k, v in {
                "image_id":           image.id,
                "name":               kwargs.get("new_name", getattr(server, "name", None)),
                "admin_pass":         kwargs.get("admin_pass"),
                "preserve_ephemeral": kwargs.get("preserve_ephemeral", False),
                "metadata":           kwargs.get("metadata"),
            }.items() if v is not None}
            conn.compute.rebuild_server(server, **rebuild_params)
            return {"success": True, "message": f'Rebuild from "{image_name}" initiated'}

    except Exception as exc:
        logger.error("set_instance(%s, %s) failed: %s", instance_name, action, exc)
        return {"success": False, "message": f"Failed to {action} instance: {exc}"}


# ---------------------------------------------------------------------------
# Public API — flavors
# ---------------------------------------------------------------------------

def get_flavor_list() -> list[dict[str, Any]]:
    """List all flavours accessible to the caller."""
    try:
        conn = get_openstack_connection()
        flavors: list[dict] = []
        for flavor in conn.compute.flavors(details=True):
            try:
                extra_specs = dict(getattr(flavor, "extra_specs", {}) or {})
            except Exception:
                extra_specs = {}
            flavors.append({
                "id":           flavor.id,
                "name":         getattr(flavor, "name", None),
                "vcpus":        getattr(flavor, "vcpus", 0),
                "ram":          getattr(flavor, "ram", 0),
                "disk":         getattr(flavor, "disk", 0),
                "ephemeral":    getattr(flavor, "ephemeral", 0),
                "swap":         getattr(flavor, "swap", 0),
                "rxtx_factor":  getattr(flavor, "rxtx_factor", 1.0),
                "is_public":    getattr(flavor, "is_public", True),
                "extra_specs":  extra_specs,
                "description":  getattr(flavor, "description", None),
            })
        return flavors
    except Exception as exc:
        logger.error("Failed to get flavor list: %s", exc)
        return []   # Empty list — callers must handle empty, not fake data


def set_flavor(flavor_name: str, action: str, **kwargs) -> dict[str, Any]:
    """Manage Nova flavours.

    Supported *action* values: ``list``, ``create``, ``delete``, ``set_extra_specs``.
    """
    if action.lower() not in _FLAVOR_ACTIONS:
        return {
            "success": False,
            "message": f'Unknown action "{action}". Supported: {sorted(_FLAVOR_ACTIONS)}',
        }

    try:
        conn = get_openstack_connection()

        if action.lower() == "list":
            flavors = get_flavor_list()
            return {"success": True, "flavors": flavors, "count": len(flavors)}

        if action.lower() == "create":
            create_params: dict[str, Any] = {
                "name":         flavor_name,
                "ram":          int(kwargs.get("ram", kwargs.get("memory", 512))),
                "vcpus":        int(kwargs.get("vcpus", kwargs.get("cpu", 1))),
                "disk":         int(kwargs.get("disk", kwargs.get("root_disk", 1))),
                "ephemeral":    int(kwargs.get("ephemeral", 0)),
                "swap":         int(kwargs.get("swap", 0)),
                "rxtx_factor":  float(kwargs.get("rxtx_factor", 1.0)),
                "is_public":    bool(kwargs.get("is_public", True)),
            }
            if kwargs.get("flavor_id") or kwargs.get("id"):
                create_params["flavorid"] = str(kwargs.get("flavor_id") or kwargs["id"])
            if kwargs.get("description"):
                create_params["description"] = kwargs["description"]

            flavor = conn.compute.create_flavor(**create_params)

            if kwargs.get("extra_specs"):
                try:
                    conn.compute.create_flavor_extra_specs(flavor, kwargs["extra_specs"])
                except Exception as exc:
                    logger.warning("Failed to set extra_specs: %s", exc)

            return {
                "success": True,
                "message": f'Flavor "{flavor_name}" created',
                "flavor": {
                    "id": flavor.id, "name": getattr(flavor, "name", None),
                    "vcpus": getattr(flavor, "vcpus", 0),
                    "ram":   getattr(flavor, "ram",   0),
                    "disk":  getattr(flavor, "disk",  0),
                },
            }

        if action.lower() == "delete":
            flavor = find_resource_by_name_or_id(conn.compute.flavors(), flavor_name, "Flavor")
            if not flavor:
                return {"success": False, "message": f'Flavor "{flavor_name}" not found'}
            conn.compute.delete_flavor(flavor)
            return {"success": True, "message": f'Flavor "{flavor_name}" deleted'}

        if action.lower() == "set_extra_specs":
            flavor, err = _find_flavor_obj(conn, flavor_name)
            if err:
                return err
            extra_specs = kwargs.get("extra_specs")
            if not isinstance(extra_specs, dict):
                return {"success": False, "message": "extra_specs must be a dict"}
            conn.compute.create_flavor_extra_specs(flavor, extra_specs)
            return {"success": True, "message": f'Extra specs updated for "{flavor_name}"',
                    "extra_specs": extra_specs}

    except Exception as exc:
        logger.error("set_flavor(%s, %s) failed: %s", flavor_name, action, exc)
        return {"success": False, "message": f"Failed to {action} flavor: {exc}"}


# ---------------------------------------------------------------------------
# Public API — server events
# ---------------------------------------------------------------------------

def get_server_events(instance_name: str, limit: int = 50) -> dict[str, Any]:
    """Return action/event history for a server."""
    try:
        conn = get_openstack_connection()
        server, err = _find_server(conn, instance_name)
        if err:
            return {**err, "events": []}

        events: list[dict] = []
        try:
            for action in conn.compute.server_actions(server.id):
                entry: dict[str, Any] = {
                    "action":        getattr(action, "action", None),
                    "instance_uuid": getattr(action, "instance_uuid", server.id),
                    "request_id":    getattr(action, "request_id", None),
                    "user_id":       getattr(action, "user_id", None),
                    "project_id":    getattr(action, "project_id", None),
                    "start_time":    _ts(action, "start_time"),
                    "finish_time":   _ts(action, "finish_time"),
                    "message":       getattr(action, "message", None),
                }
                raw_events = getattr(action, "events", None)
                entry["events"] = [
                    {
                        "event":       getattr(e, "event", None),
                        "start_time":  _ts(e, "start_time"),
                        "finish_time": _ts(e, "finish_time"),
                        "result":      getattr(e, "result", None),
                        "traceback":   getattr(e, "traceback", None),
                    }
                    for e in (raw_events or [])
                ]
                events.append(entry)
                if len(events) >= limit:
                    break
        except Exception as exc:
            logger.warning("Could not get server actions for %s: %s", instance_name, exc)

        return {
            "success":     True,
            "server_name": getattr(server, "name", None),
            "server_id":   server.id,
            "events":      events,
            "count":       len(events),
        }

    except Exception as exc:
        logger.error("Failed to get server events for %s: %s", instance_name, exc)
        return {"success": False, "message": f"Failed to get server events: {exc}", "events": []}


# ---------------------------------------------------------------------------
# Public API — server groups
# ---------------------------------------------------------------------------

def get_server_groups() -> list[dict[str, Any]]:
    """List all server groups visible to the caller."""
    try:
        conn = get_openstack_connection()
        groups: list[dict] = []
        for group in conn.compute.server_groups():
            members = list(getattr(group, "members", []) or [])
            groups.append({
                "id":         group.id,
                "name":       getattr(group, "name", None),
                "policies":   list(getattr(group, "policies", [])),
                "members":    members,
                "member_count": len(members),
                "metadata":   getattr(group, "metadata", {}),
                "project_id": getattr(group, "project_id", None),
                "user_id":    getattr(group, "user_id", None),
                "created_at": _ts(group, "created_at"),
                "updated_at": _ts(group, "updated_at"),
            })
        return groups
    except Exception as exc:
        logger.error("Failed to get server groups: %s", exc)
        return []


def set_server_group(group_name: str, action: str, **kwargs) -> dict[str, Any]:
    """Manage Nova server groups.

    Supported *action* values: ``list``, ``create``, ``delete``, ``show``.
    """
    if action.lower() not in _SERVER_GROUP_ACTIONS:
        return {
            "success": False,
            "message": f'Unknown action "{action}". Supported: {sorted(_SERVER_GROUP_ACTIONS)}',
        }

    try:
        conn = get_openstack_connection()

        if action.lower() == "list":
            return {"success": True, "server_groups": get_server_groups()}

        if action.lower() == "create":
            policies = kwargs.get("policies", kwargs.get("policy", ["affinity"]))
            if isinstance(policies, str):
                policies = [policies]
            invalid = [p for p in policies if p not in _VALID_GROUP_POLICIES]
            if invalid:
                return {
                    "success": False,
                    "message": f'Invalid policies: {invalid}. Supported: {sorted(_VALID_GROUP_POLICIES)}',
                }
            group = conn.compute.create_server_group(name=group_name, policies=policies)
            members = list(getattr(group, "members", []) or [])
            return {
                "success": True,
                "message": f'Server group "{group_name}" created',
                "server_group": {
                    "id": group.id, "name": getattr(group, "name", None),
                    "policies": list(getattr(group, "policies", policies)),
                    "members": members,
                },
            }

        # delete / show — need to locate the group
        sg = find_resource_by_name_or_id(conn.compute.server_groups(), group_name, "Server Group")
        if not sg:
            return {"success": False, "message": f'Server group "{group_name}" not found'}

        if action.lower() == "delete":
            conn.compute.delete_server_group(sg)
            return {"success": True, "message": f'Server group "{group_name}" deleted'}

        # show
        members = list(getattr(sg, "members", []) or [])
        return {
            "success": True,
            "server_group": {
                "id":           sg.id,
                "name":         getattr(sg, "name", None),
                "policies":     list(getattr(sg, "policies", [])),
                "members":      members,
                "member_count": len(members),
                "metadata":     getattr(sg, "metadata", {}),
                "project_id":   getattr(sg, "project_id", None),
                "user_id":      getattr(sg, "user_id", None),
                "created_at":   _ts(sg, "created_at"),
                "updated_at":   _ts(sg, "updated_at"),
            },
        }

    except Exception as exc:
        logger.error("set_server_group(%s, %s) failed: %s", group_name, action, exc)
        return {"success": False, "message": f"Failed to {action} server group: {exc}"}
