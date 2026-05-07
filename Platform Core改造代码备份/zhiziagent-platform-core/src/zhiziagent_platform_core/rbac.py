ROLE_ORDER = {"owner": 0, "admin": 1, "member": 2, "viewer": 3}

DEFAULT_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "owner": ["*"],
    "admin": [
        "tenant.read",
        "tenant.members.write",
        "apps.read",
        "apps.enable",
        "model.catalog.read",
        "model.catalog.sync",
        "model.authorization.read",
        "model.authorization.write",
        "model.directory.read",
        "model.entitlement.read",
        "model.entitlement.write",
        "document.*",
        "toolkit.read",
        "toolkit.admin",
        "toolkit.context.verify",
        "toolkit.artifacts.read",
        "toolkit.artifacts.write",
        "mcp.tools.read",
        "mcp.grants.read",
        "mcp.grants.write",
        "agent_flows.read",
        "agent_flows.write",
        "agent_flows.share",
        "agent_flows.run",
        "service_accounts.manage",
        "audit.read",
        "audit.write",
        "studio.profile.execute",
        "usage.read",
        "scanner.*",
        "project.*",
        "wae.*",
        "agentctl.*",
    ],
    "member": [
        "tenant.read",
        "apps.read",
        "audit.write",
        "scanner.use",
        "scanner.export",
        "scanner.import_to_ops",
        "project.read",
        "project.write",
        "wae.world.read",
        "wae.world.write",
        "wae.session.run",
        "agentctl.run",
        "document.parse",
        "document.read",
        "document.search",
        "toolkit.read",
        "toolkit.artifacts.read",
        "toolkit.artifacts.write",
        "mcp.tools.read",
        "mcp.grants.read",
        "agent_flows.read",
        "agent_flows.run",
    ],
    "viewer": [
        "tenant.read",
        "apps.read",
        "scanner.use",
        "project.read",
        "wae.world.read",
        "document.read",
        "document.search",
        "toolkit.read",
        "toolkit.artifacts.read",
        "mcp.tools.read",
        "agent_flows.read",
        "agent_flows.run",
    ],
}


def has_permission(granted: list[str] | set[str], required: str) -> bool:
    permissions = set(granted)
    if "*" in permissions or required in permissions:
        return True
    parts = required.split(".")
    for index in range(len(parts), 0, -1):
        wildcard = ".".join(parts[:index]) + ".*"
        if wildcard in permissions:
            return True
    return False


def role_rank(role: str) -> int:
    return ROLE_ORDER.get(role, 99)
