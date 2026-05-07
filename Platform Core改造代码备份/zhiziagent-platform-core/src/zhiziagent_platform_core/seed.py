from sqlalchemy.orm import Session

from .models import AppModule, Permission, RolePermission, ToolCatalogEntry
from .rbac import DEFAULT_ROLE_PERMISSIONS

DEFAULT_PERMISSIONS: dict[str, str] = {
    "*": "All platform and product permissions.",
    "platform.admin": "Manage platform-level configuration.",
    "tenant.read": "Read tenant profile and current membership.",
    "tenant.members.write": "Invite, update, or remove tenant members.",
    "apps.read": "Read available and enabled app modules.",
    "apps.enable": "Enable or disable app modules for a tenant.",
    "model.catalog.read": "Read synchronized model catalog entries.",
    "model.catalog.sync": "Synchronize model catalog from agentctl.",
    "model.authorization.read": "Read model visibility rules.",
    "model.authorization.write": "Create or update model visibility rules.",
    "model.directory.read": "Read authorized model directory for a product.",
    "model.entitlement.read": "Read tenant model key entitlements and usage attribution.",
    "model.entitlement.write": "Create or update tenant model key entitlements.",
    "model.entitlement.sync_all": "Allow agentctl to synchronize model key entitlements across tenants.",
    "agentctl.entitlements.sync": "Synchronize model key entitlement snapshots into agentctl.",
    "agentctl.entitlements.write": "Write model key usage and health facts from agentctl.",
    "document.*": "All platform document parsing permissions.",
    "document.parse": "Submit documents to the platform parse broker.",
    "document.read": "Read parsed document snapshots through the platform parse broker.",
    "document.search": "Search parsed document content through the platform parse broker.",
    "service_accounts.manage": "Create and revoke service accounts.",
    "audit.read": "Read tenant audit events.",
    "audit.write": "Write audit events.",
    "usage.read": "Read tenant usage events.",
    "usage.write": "Write tenant usage events.",
    "billing.write": "Update product billing and payment status events.",
    "toolkit.read": "Read available platform toolkits.",
    "toolkit.admin": "Manage platform toolkit catalog entries.",
    "toolkit.context.verify": "Verify signed platform_tool_context envelopes for runtime execution.",
    "toolkit.artifacts.read": "Read authorized toolkit artifact metadata and bytes.",
    "toolkit.artifacts.write": "Create authorized toolkit artifact metadata and inline bytes.",
    "mcp.tools.read": "Read authorized MCP tool catalog entries.",
    "mcp.grants.read": "Read MCP tool grants for a tenant or user.",
    "mcp.grants.write": "Create or revoke MCP tool grants.",
    "agent_flows.read": "Read published agent flows and shares.",
    "agent_flows.write": "Publish agent flows.",
    "agent_flows.share": "Create and revoke agent flow shares.",
    "agent_flows.run": "Run shared agent flows.",
    "studio.profile.execute": "Run approved ZhiziAgent Studio profile request jobs.",
    "studio.profile.execute_high_risk": "Stage high-risk ZhiziAgent Studio profile request jobs after second approval.",
    "scanner.*": "All AI Opportunity Scanner permissions.",
    "scanner.use": "Use AI Opportunity Scanner.",
    "scanner.export": "Export scanner assets.",
    "scanner.import_to_ops": "Send scanner output to AIProjectOPS.",
    "project.*": "All AIProjectOPS permissions.",
    "project.read": "Read projects and tasks.",
    "project.write": "Create or update projects and tasks.",
    "project.admin": "Manage AIProjectOPS settings.",
    "wae.*": "All World Agent Engine permissions.",
    "wae.world.read": "Read WAE worlds.",
    "wae.world.write": "Create or update WAE worlds.",
    "wae.session.run": "Run WAE sessions.",
    "agentctl.*": "All agentctl control-plane permissions.",
    "agentctl.run": "Run approved agentctl tasks.",
}


DEFAULT_APPS: list[dict] = [
    {
        "app_id": "aoc",
        "name": "AI Opportunity Scanner",
        "description": "Enterprise AI opportunity scanning and AIOS asset export.",
        "entry_web": "/apps/aoc",
        "entry_api": None,
            "permissions": ["scanner.use", "scanner.export", "scanner.import_to_ops", "usage.write"],
    },
    {
        "app_id": "aiprojectops",
        "name": "AIProjectOPS",
        "description": "AI native project execution hub.",
        "entry_web": "/apps/aiprojectops",
        "entry_api": "http://aiprojectops-api:8000",
            "permissions": ["project.read", "project.write", "project.admin", "usage.write"],
    },
    {
        "app_id": "wae",
        "name": "World Agent Engine",
        "description": "Text-to-interactive-world engine and simulation product.",
        "entry_web": "/apps/wae",
        "entry_api": "http://wae-api:8000",
            "permissions": ["wae.world.read", "wae.world.write", "wae.session.run", "usage.write"],
    },
    {
        "app_id": "agentctl",
        "name": "agentctl",
        "description": "Shared AI runtime, Model Gateway, RunSpec, Ledger, and Evidence base.",
        "entry_web": "/apps/agentctl",
        "entry_api": "http://agentctl:8765",
            "permissions": [
                "agentctl.run",
                "agentctl.*",
                "agentctl.entitlements.sync",
                "agentctl.entitlements.write",
                "toolkit.context.verify",
                "toolkit.artifacts.read",
                "toolkit.artifacts.write",
                "studio.profile.execute",
                "studio.profile.execute_high_risk",
                "usage.write",
            ],
    },
    {
        "app_id": "zhiziagent_studio",
        "name": "ZhiziAgent Studio",
        "description": "Personal agent, skill, workflow, and model entitlement workspace.",
        "entry_web": "/studio",
        "entry_api": "/studio",
            "permissions": [
                "agentctl.run",
                "model.directory.read",
                "model.entitlement.write",
                "billing.write",
                "toolkit.read",
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
                "usage.write",
            ],
    },
    {
        "app_id": "parsecore",
        "name": "ParseCore Document Service",
        "description": "Shared document parsing, OCR, chunking, and search broker.",
        "entry_web": "/apps/parsecore",
        "entry_api": "/platform/parse",
            "permissions": ["document.parse", "document.read", "document.search", "usage.write"],
    },
]


DEFAULT_TOOLKITS: list[dict] = [
    {
        "toolkit_id": "document.parse",
        "version": "1.0.0",
        "display_name": "智能解析中台 / JXZT Document Parse Toolkit",
        "category": "document",
        "capabilities": [
            "document.parse.submit",
            "document.parse.status",
            "document.parse.read",
            "document.parse.search",
            "document.parse.extract_tables",
            "document.parse.ocr",
        ],
        "input_schema": {
            "type": "object",
            "required": ["document"],
            "properties": {
                "document": {
                    "type": "object",
                    "required": ["file_name"],
                    "properties": {
                        "file_name": {"type": "string"},
                        "media_type": {"type": "string"},
                        "file_base64": {"type": "string"},
                        "object_ref": {"type": "string"},
                        "source_url": {"type": "string"},
                    },
                    "oneOf": [
                        {"required": ["file_base64"]},
                        {"required": ["object_ref"]},
                        {"required": ["source_url"]},
                    ],
                },
                "parse_options": {
                    "type": "object",
                    "properties": {
                        "enable_ocr": {"type": "boolean", "default": True},
                        "extract_tables": {"type": "boolean", "default": True},
                        "chunk_strategy": {
                            "type": "string",
                            "enum": ["semantic", "page", "heading"],
                            "default": "semantic",
                        },
                        "language_hint": {"type": "string"},
                    },
                },
                "callback": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "secret_ref": {"type": "string"},
                    },
                },
            },
        },
        "output_schema": {
            "type": "object",
            "required": ["doc_id", "trace_id", "status"],
            "properties": {
                "doc_id": {"type": "string"},
                "trace_id": {"type": "string"},
                "status": {"type": "string"},
                "total_pages": {"type": "integer"},
                "parser_used": {"type": "string"},
                "chunks": {"type": "array", "items": {"type": "object"}},
                "tables": {"type": "array", "items": {"type": "object"}},
                "artifact_refs": {"type": "array", "items": {"type": "string"}},
                "usage": {"type": "object"},
            },
        },
        "runtime_adapter": "toolkit.document.jxzt",
        "data_sensitivity": "D2",
        "quota_metrics": ["document.pages", "document.ocr_pages", "document.bytes"],
        "pricing_metrics": ["document.pages", "document.ocr_pages"],
        "approval_policy": {"external_source_url_requires_allowlist": True},
        "sandbox_policy": {
            "network": "platform_internal_only",
            "max_file_mb": 100,
            "allowed_input_refs": ["file_base64", "object_ref", "source_url"],
        },
    },
    {
        "toolkit_id": "video-editing-toolkit",
        "version": "0.1.0-p0",
        "display_name": "Video Editing Toolkit",
        "category": "video_editing",
        "capabilities": [
            "video.asset_ingest.probe_media",
            "video.asset_ingest.normalize_asset",
            "video.asset_ingest.extract_audio",
            "video.asset_ingest.extract_frames",
            "video.asset_ingest.build_asset_index",
            "video.analysis.detect_scenes",
            "video.analysis.analyze_frames",
            "video.analysis.check_visual_quality",
            "audio.speech.transcribe",
            "audio.speech.align_subtitles",
            "audio.speech.check_audio_quality",
            "video.project_edit.create_project",
            "video.project_edit.inspect_assets",
            "video.project_edit.generate_edit_plan",
            "video.project_edit.apply_timeline_patch",
            "video.project_edit.render_preview",
            "video.project_edit.compare_versions",
            "video.project_edit.rollback_version",
            "video.render.render_preview",
            "video.render.render_final",
            "video.delivery.generate_variants",
            "video.delivery.package_artifacts",
            "video.delivery.create_delivery_manifest",
        ],
        "input_schema": {
            "type": "object",
            "required": ["capability", "input"],
            "properties": {
                "capability": {"type": "string"},
                "input": {"type": "object"},
                "artifact_refs": {"type": "array", "items": {"type": "object"}},
                "platform_tool_context": {"type": "object"},
            },
        },
        "output_schema": {
            "type": "object",
            "required": ["status"],
            "properties": {
                "status": {"type": "string"},
                "output": {"type": "object"},
                "artifact_refs": {"type": "array", "items": {"type": "object"}},
                "usage_metrics": {"type": "object"},
                "trace_ref": {"type": "string"},
            },
        },
        "runtime_adapter": "toolkit.video_editing.external_worker",
        "data_sensitivity": "D3",
        "quota_metrics": [
            "input_bytes",
            "output_bytes",
            "media_duration_seconds",
            "frame_count",
            "render_seconds",
            "worker_cpu_seconds",
        ],
        "pricing_metrics": ["media_duration_seconds", "render_seconds", "transcript_minutes"],
        "approval_policy": {
            "requires_confirmation_for": [
                "video.render.render_final",
                "video.delivery.package_artifacts",
                "video.delivery.create_delivery_manifest",
            ],
            "high_sensitivity_default": "disabled",
        },
        "sandbox_policy": {
            "deployment": "external_independent_package",
            "artifact_contract": "artifact_ref_only",
            "input_source": "platform_core_toolkit_artifacts_or_object_storage",
            "network": "platform_internal_only",
            "return_local_paths": False,
        },
    },
    {
        "toolkit_id": "mcp.github",
        "version": "1.0.0",
        "display_name": "GitHub MCP Toolkit",
        "category": "mcp",
        "capabilities": ["mcp.github.read", "mcp.github.write"],
        "runtime_adapter": "mcp.github",
        "data_sensitivity": "D2",
        "quota_metrics": ["mcp.tool_calls"],
        "pricing_metrics": ["mcp.tool_calls"],
        "approval_policy": {"write_requires_confirmation": True},
        "sandbox_policy": {"network": "mcp_server_only"},
        "mcp_server_policy": {
            "resource_granularity": ["repo", "branch", "issue", "pull_request"],
            "actions": ["read", "write"],
        },
    },
    {
        "toolkit_id": "mcp.filesystem",
        "version": "1.0.0",
        "display_name": "Filesystem MCP Toolkit",
        "category": "mcp",
        "capabilities": ["mcp.filesystem.read", "mcp.filesystem.write"],
        "runtime_adapter": "mcp.filesystem",
        "data_sensitivity": "D3",
        "quota_metrics": ["mcp.tool_calls", "filesystem.bytes_read", "filesystem.bytes_written"],
        "pricing_metrics": ["mcp.tool_calls"],
        "approval_policy": {"write_requires_confirmation": True},
        "sandbox_policy": {"path_scope": "grant_required", "network": "deny"},
        "mcp_server_policy": {
            "resource_granularity": ["directory", "extension", "file_size"],
            "actions": ["read", "write"],
        },
    },
]


def seed_defaults(db: Session) -> None:
    for code, description in DEFAULT_PERMISSIONS.items():
        if db.get(Permission, code) is None:
            db.add(Permission(code=code, description=description))

    for role, permissions in DEFAULT_ROLE_PERMISSIONS.items():
        for permission in permissions:
            exists = (
                db.query(RolePermission)
                .filter(
                    RolePermission.role == role,
                    RolePermission.permission_code == permission,
                )
                .first()
            )
            if exists is None:
                db.add(RolePermission(role=role, permission_code=permission))

    for item in DEFAULT_APPS:
        app = db.get(AppModule, item["app_id"])
        manifest = {
            "app_id": item["app_id"],
            "name": item["name"],
            "entry": {"web": item["entry_web"], "api": item["entry_api"]},
            "permissions": item["permissions"],
        }
        if app is None:
            db.add(
                AppModule(
                    app_id=item["app_id"],
                    name=item["name"],
                    description=item["description"],
                    entry_web=item["entry_web"],
                    entry_api=item["entry_api"],
                    manifest_json=manifest,
                )
            )
        else:
            app.name = item["name"]
            app.description = item["description"]
            app.entry_web = item["entry_web"]
            app.entry_api = item["entry_api"]
            app.manifest_json = manifest

    for item in DEFAULT_TOOLKITS:
        exists = (
            db.query(ToolCatalogEntry)
            .filter(
                ToolCatalogEntry.toolkit_id == item["toolkit_id"],
                ToolCatalogEntry.version == item["version"],
            )
            .first()
        )
        if exists is None:
            db.add(
                ToolCatalogEntry(
                    toolkit_id=item["toolkit_id"],
                    version=item["version"],
                    display_name=item["display_name"],
                    category=item["category"],
                    capabilities_json=item["capabilities"],
                    input_schema_json=item.get("input_schema", {}),
                    output_schema_json=item.get("output_schema", {}),
                    runtime_adapter=item.get("runtime_adapter"),
                    data_sensitivity=item.get("data_sensitivity"),
                    quota_metrics_json=item.get("quota_metrics", []),
                    pricing_metrics_json=item.get("pricing_metrics", []),
                    approval_policy_json=item.get("approval_policy", {}),
                    sandbox_policy_json=item.get("sandbox_policy", {}),
                    mcp_server_policy_json=item.get("mcp_server_policy", {}),
                    status="active",
                )
            )
        else:
            exists.display_name = item["display_name"]
            exists.category = item["category"]
            exists.capabilities_json = item["capabilities"]
            exists.input_schema_json = item.get("input_schema", {})
            exists.output_schema_json = item.get("output_schema", {})
            exists.runtime_adapter = item.get("runtime_adapter")
            exists.data_sensitivity = item.get("data_sensitivity")
            exists.quota_metrics_json = item.get("quota_metrics", [])
            exists.pricing_metrics_json = item.get("pricing_metrics", [])
            exists.approval_policy_json = item.get("approval_policy", {})
            exists.sandbox_policy_json = item.get("sandbox_policy", {})
            exists.mcp_server_policy_json = item.get("mcp_server_policy", {})
            exists.status = "active"

    for row in db.query(ToolCatalogEntry).filter(ToolCatalogEntry.category == "video").all():
        row.status = "external"
        row.runtime_adapter = None
        row.sandbox_policy_json = {
            "deployment": "external_independent_package",
            "note": "Video toolkits are not implemented in Platform Core.",
        }

    db.commit()
