from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)
    display_name: str = Field(min_length=1, max_length=120)
    tenant_name: str = Field(min_length=1, max_length=160)


class LoginRequest(BaseModel):
    email: str
    password: str
    tenant_id: str | None = None
    totp_code: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class TotpSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str
    issuer: str
    account_name: str


class TotpEnableRequest(BaseModel):
    code: str


class TotpDisableRequest(BaseModel):
    current_password: str
    code: str | None = None


class TotpStatusResponse(BaseModel):
    enabled: bool
    pending_setup: bool = False
    enabled_at: datetime | None = None


class SwitchTenantRequest(BaseModel):
    tenant_id: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    tenant_id: str
    role: str
    permissions: list[str]


class UserProfile(BaseModel):
    id: str
    email: str
    display_name: str
    status: str


class TenantProfile(BaseModel):
    id: str
    slug: str
    name: str
    tenant_type: str
    status: str
    plan_code: str


class TenantMemberProfile(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: str
    status: str


class PlatformUserMembershipProfile(BaseModel):
    tenant_id: str
    tenant_slug: str
    tenant_name: str
    tenant_type: str
    tenant_status: str
    role: str
    member_status: str


class PlatformUserDirectoryEntry(BaseModel):
    user_id: str
    email: str
    display_name: str
    status: str
    created_at: datetime
    updated_at: datetime
    memberships: list[PlatformUserMembershipProfile] = Field(default_factory=list)


class MeResponse(BaseModel):
    user: UserProfile
    current_tenant: TenantProfile
    role: str
    permissions: list[str]
    memberships: list[TenantProfile]
    enabled_apps: list[str]


class CreateTenantRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    slug: str | None = Field(default=None, max_length=80)
    tenant_type: str = "team"


class AddMemberRequest(BaseModel):
    email: str
    role: str = "member"


class UpdateMemberRequest(BaseModel):
    role: str | None = None
    status: str | None = None


class AppModuleResponse(BaseModel):
    app_id: str
    name: str
    description: str
    status: str
    entry_web: str | None
    entry_api: str | None
    manifest: dict[str, Any]


class RegisterAppRequest(BaseModel):
    app_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    entry_web: str | None = None
    entry_api: str | None = None
    permissions: list[str] = Field(default_factory=list)
    manifest: dict[str, Any] = Field(default_factory=dict)


class TenantAppResponse(BaseModel):
    app_id: str
    name: str
    status: str
    entry_web: str | None
    entry_api: str | None
    permissions: list[str]


class ToolCatalogEntryResponse(BaseModel):
    catalog_id: str
    toolkit_id: str
    version: str
    display_name: str
    category: str
    capabilities: list[str]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    runtime_adapter: str | None = None
    data_sensitivity: str | None = None
    quota_metrics: list[str]
    pricing_metrics: list[str]
    approval_policy: dict[str, Any]
    sandbox_policy: dict[str, Any]
    mcp_server_policy: dict[str, Any]
    manifest: dict[str, Any] = Field(default_factory=dict)
    status: str
    created_at: datetime
    updated_at: datetime


class ToolkitArtifactCreateRequest(BaseModel):
    tenant_id: str | None = Field(default=None, max_length=40)
    toolkit_id: str = Field(min_length=1, max_length=120)
    capability: str | None = Field(default=None, max_length=160)
    artifact_type: str = Field(default="artifact", min_length=1, max_length=80)
    file_name: str | None = Field(default=None, max_length=255)
    mime_type: str = Field(default="application/octet-stream", min_length=1, max_length=160)
    data_class: str = Field(default="D2", min_length=1, max_length=32)
    retention_policy: str = Field(default="short_lived", min_length=1, max_length=80)
    access_policy: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = Field(default=None, max_length=160)
    trace_id: str | None = Field(default=None, max_length=160)
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    content_base64: str | None = None


class ToolkitArtifactRef(BaseModel):
    artifact_id: str
    artifact_type: str
    owner_tenant_id: str
    created_by_run_id: str
    mime_type: str
    size_bytes: int
    checksum: str
    data_class: str
    retention_policy: str
    access_policy: dict[str, Any]
    download_url: str
    expires_at: datetime | None = None


class ToolkitArtifactResponse(BaseModel):
    artifact_id: str
    tenant_id: str
    owner_type: str
    owner_id: str
    toolkit_id: str
    capability: str | None = None
    artifact_type: str
    file_name: str | None = None
    mime_type: str
    size_bytes: int
    checksum: str
    data_class: str
    retention_policy: str
    access_policy: dict[str, Any]
    storage_kind: str
    status: str
    expires_at: datetime | None = None
    run_id: str | None = None
    trace_id: str | None = None
    metadata: dict[str, Any]
    artifact_ref: ToolkitArtifactRef
    created_at: datetime
    updated_at: datetime


class MCPToolGrantCreateRequest(BaseModel):
    owner_type: Literal["personal_user", "organization", "share_flow"] = "personal_user"
    owner_id: str | None = None
    toolkit_id: str = Field(min_length=1, max_length=120)
    mcp_server_id: str = Field(min_length=1, max_length=120)
    mcp_tool_name: str = Field(min_length=1, max_length=160)
    resource_scope: str = Field(default="personal", min_length=1, max_length=160)
    allowed_actions: list[str] = Field(default_factory=list)
    allowed_resources: list[str] = Field(default_factory=list)
    data_sensitivity_limit: str | None = Field(default=None, max_length=16)
    approval_policy: dict[str, Any] = Field(default_factory=dict)
    credential_ref: str | None = Field(default=None, max_length=255)
    expires_at: datetime | None = None


class MCPToolGrantResponse(BaseModel):
    grant_id: str
    tenant_id: str
    owner_type: str
    owner_id: str
    toolkit_id: str
    mcp_server_id: str
    mcp_tool_name: str
    resource_scope: str
    allowed_actions: list[str]
    allowed_resources: list[str]
    data_sensitivity_limit: str | None = None
    approval_policy: dict[str, Any]
    credential_ref: str | None = None
    credential_configured: bool = False
    expires_at: datetime | None = None
    status: str
    created_by: str | None = None
    approved_by: str | None = None
    revoked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class MCPToolGrantRevokeRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class AgentFlowPublishRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    description: str | None = None
    workflow_version: str | None = Field(default=None, max_length=40)
    toolkit_dependencies: list[dict[str, Any]] = Field(default_factory=list)
    mcp_grant_ids: list[str] = Field(default_factory=list)
    knowledge_dependencies: list[dict[str, Any]] = Field(default_factory=list)
    model_policy: dict[str, Any] = Field(default_factory=dict)
    data_policy: dict[str, Any] = Field(default_factory=dict)
    visibility: Literal["private", "link", "login_required", "marketplace"] = "private"


class AgentFlowResponse(BaseModel):
    flow_id: str
    tenant_id: str
    owner_type: str
    owner_id: str
    title: str
    description: str | None = None
    source_app: str
    source_draft_id: str | None = None
    workflow_id: str
    workflow_version: str | None = None
    agent_dependencies: list[Any]
    toolkit_dependencies: list[Any]
    mcp_grant_ids: list[str]
    mcp_grant_snapshot: list[Any]
    knowledge_dependencies: list[Any]
    model_policy: dict[str, Any]
    data_policy: dict[str, Any]
    visibility: str
    status: str
    created_by: str | None = None
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AgentFlowShareCreateRequest(BaseModel):
    share_mode: Literal["private_invite", "public_link", "login_required", "organization_install"] = "login_required"
    access_policy: dict[str, Any] = Field(default_factory=dict)
    quota_policy: dict[str, Any] = Field(default_factory=dict)
    billing_policy: dict[str, Any] = Field(default_factory=dict)
    input_data_policy: dict[str, Any] = Field(default_factory=dict)
    output_data_policy: dict[str, Any] = Field(default_factory=dict)
    trace_visibility_policy: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None


class AgentFlowShareResponse(BaseModel):
    share_id: str
    flow_id: str
    tenant_id: str
    share_mode: str
    access_policy: dict[str, Any]
    quota_policy: dict[str, Any]
    billing_policy: dict[str, Any]
    input_data_policy: dict[str, Any]
    output_data_policy: dict[str, Any]
    trace_visibility_policy: dict[str, Any]
    status: str
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    created_by: str | None = None
    revoked_by: str | None = None
    revoke_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    flow: AgentFlowResponse | None = None


class AgentFlowShareRunRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = Field(default=None, max_length=160)
    dry_run: bool = False


class AgentFlowShareRunResponse(BaseModel):
    run_id: str
    share_id: str
    flow_id: str
    status: str
    trace_id: str
    execution_status: str
    message: str
    product_context: dict[str, Any]
    share_context: dict[str, Any]
    tool_context: dict[str, Any]
    mcp_context: dict[str, Any]
    platform_tool_context: dict[str, Any]


class PlatformToolContextVerifyRequest(BaseModel):
    platform_tool_context: dict[str, Any]
    required_toolkit_id: str | None = Field(default=None, max_length=120)
    required_version: str | None = Field(default=None, max_length=40)
    required_capability: str | None = Field(default=None, max_length=160)
    mcp_server_id: str | None = Field(default=None, max_length=120)
    mcp_tool_name: str | None = Field(default=None, max_length=160)
    action: str | None = Field(default=None, max_length=120)
    resource: str | None = Field(default=None, max_length=255)


class PlatformToolContextVerifyResponse(BaseModel):
    valid: bool
    reason: str | None = None
    expires_at: datetime | None = None
    product_context: dict[str, Any] = Field(default_factory=dict)
    share_context: dict[str, Any] = Field(default_factory=dict)
    tool_context: dict[str, Any] = Field(default_factory=dict)
    mcp_context: dict[str, Any] = Field(default_factory=dict)


class CreateServiceAccountRequest(BaseModel):
    app_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    scopes: list[str] = Field(default_factory=list)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class RevokeServiceAccountRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class RotateServiceAccountRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ServiceAccountResponse(BaseModel):
    id: str
    tenant_id: str
    app_id: str
    name: str
    scopes: list[str]
    status: str
    created_at: datetime
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    revoked_by: str | None = None
    revoke_reason: str | None = None


class ServiceAccountCreatedResponse(ServiceAccountResponse):
    token: str


class IntegrationGrantCreateRequest(BaseModel):
    tenant_id: str
    product_id: str = Field(min_length=1, max_length=80)
    adapter_id: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=160)
    mode: str = Field(min_length=1, max_length=24)
    agentctl: dict[str, Any] = Field(default_factory=dict)
    expires_in_seconds: int = Field(default=1800, ge=60, le=604800)


class IntegrationRequestCreateRequest(BaseModel):
    tenant_id: str | None = None
    requested_tenants: list[str] = Field(default_factory=list)
    product_id: str = Field(min_length=1, max_length=80)
    adapter_id: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=160)
    vendor: str | None = Field(default=None, max_length=160)
    mode: str = Field(default="self_managed_product", min_length=1, max_length=40)
    environment: str | None = Field(default=None, max_length=40)
    callback_url: str | None = Field(default=None, max_length=255)
    jwks_uri: str | None = Field(default=None, max_length=255)
    requested_platform_scopes: list[str] = Field(default_factory=list)
    requested_agentctl_scopes: list[str] = Field(default_factory=list)
    requested_agentctl_operations: list[str] = Field(default_factory=list)
    requested_models: dict[str, Any] = Field(default_factory=dict)
    product_context_contract: dict[str, Any] = Field(default_factory=dict)
    manifest: dict[str, Any] = Field(default_factory=dict)


class IntegrationRequestResponse(BaseModel):
    request_id: str
    tenant_id: str | None = None
    requested_tenants: list[str]
    product_id: str
    adapter_id: str
    display_name: str
    vendor: str | None = None
    mode: str
    environment: str | None = None
    callback_url: str | None = None
    jwks_uri: str | None = None
    requested_platform_scopes: list[str]
    requested_agentctl_scopes: list[str]
    requested_agentctl_operations: list[str]
    requested_models: dict[str, Any]
    product_context_contract: dict[str, Any]
    manifest: dict[str, Any]
    status: str
    review_note: str | None = None
    grant_id: str | None = None
    connection_id: str | None = None
    created_by: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    rejected_by: str | None = None
    rejected_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class IntegrationRequestApproveRequest(BaseModel):
    tenant_id: str | None = None
    platform_scopes: list[str] | None = None
    agentctl: dict[str, Any] | None = None
    expires_in_seconds: int = Field(default=1800, ge=60, le=604800)
    enable_tenant_app: bool = True
    review_note: str | None = Field(default=None, max_length=1000)


class IntegrationRequestApproveResponse(BaseModel):
    request: IntegrationRequestResponse
    grant: IntegrationGrantResponse
    one_time_code: str
    handoff_url: str


class IntegrationRequestRejectRequest(BaseModel):
    review_note: str = Field(min_length=1, max_length=1000)


class IntegrationGrantResponse(BaseModel):
    grant_id: str
    tenant_id: str
    product_id: str
    adapter_id: str
    display_name: str
    mode: str
    status: str
    agentctl: dict[str, Any]
    expires_at: datetime
    redeemed_at: datetime | None = None
    created_by: str
    created_at: datetime
    install_url: str | None = None


class IntegrationGrantCreatedResponse(IntegrationGrantResponse):
    one_time_code: str


class IntegrationDeviceAuthorizeRequest(IntegrationRequestCreateRequest):
    expires_in_seconds: int = Field(default=900, ge=60, le=3600)


class IntegrationDeviceAuthorizeResponse(BaseModel):
    device_authorization_id: str
    request_id: str
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int = 5


class IntegrationDeviceApproveRequest(BaseModel):
    user_code: str = Field(min_length=1, max_length=32)
    tenant_id: str | None = None
    platform_scopes: list[str] | None = None
    agentctl: dict[str, Any] | None = None
    review_note: str | None = Field(default=None, max_length=1000)


class IntegrationDeviceTokenRequest(BaseModel):
    device_code: str = Field(min_length=1, max_length=255)


class IntegrationGrantRedeemRequest(BaseModel):
    one_time_code: str = Field(min_length=1, max_length=255)
    adapter_id: str = Field(min_length=1, max_length=80)
    environment: str | None = Field(default=None, max_length=40)
    callback_url: str | None = Field(default=None, max_length=255)
    public_key: str | None = None
    operator: dict[str, Any] = Field(default_factory=dict)


class IntegrationServiceAccountCredential(BaseModel):
    token: str
    token_id: str
    scopes: list[str]


class IntegrationConnectionResponse(BaseModel):
    connection_id: str
    tenant_id: str
    product_id: str
    adapter_id: str
    display_name: str
    mode: str
    environment: str | None = None
    callback_url: str | None = None
    public_key: str | None = None
    status: str
    agentctl_tenant_id: str | None = None
    agentctl: dict[str, Any]
    platform_service_account_id: str
    created_at: datetime
    updated_at: datetime
    last_token_exchange_at: datetime | None = None


class IntegrationConnectionRedeemResponse(BaseModel):
    connection_id: str
    platform_core_base_url: str
    agentctl_base_url: str
    tenant_id: str
    product_id: str
    adapter_id: str
    platform_service_account: IntegrationServiceAccountCredential
    agentctl_token_exchange_url: str


class IntegrationAgentctlTokenRequest(BaseModel):
    requested_scopes: list[str] = Field(default_factory=list)
    product_operation: str | None = Field(default=None, max_length=120)
    trace_id: str | None = Field(default=None, max_length=160)


class IntegrationAgentctlTokenResponse(BaseModel):
    agentctl_base_url: str
    access_token: str
    token_id: str
    token_type: str = "bearer"
    expires_in: int
    tenant_id: str
    product_id: str
    adapter_id: str
    allowed_agents: list[str] = Field(default_factory=list)
    allowed_operations: list[str] = Field(default_factory=list)


class IntegrationSmokeCheck(BaseModel):
    key: str
    status: str
    detail: str


class IntegrationSmokeResponse(BaseModel):
    connection_id: str
    connection_status: str
    platform_service_account_id: str
    platform_service_account_status: str
    status: str
    last_token_exchange_at: datetime | None = None
    smoke_trace_id: str | None = None
    token_id: str | None = None
    checks: list[IntegrationSmokeCheck] = Field(default_factory=list)


class IntegrationHandoffResponse(BaseModel):
    connection_id: str
    tenant_id: str
    product_id: str
    adapter_id: str
    mode: str
    status: str
    platform_core_base_url: str
    agentctl_base_url: str
    token_exchange_url: str
    openapi: dict[str, str]
    env_template: dict[str, str]
    token_flow: dict[str, Any]
    agentctl_endpoints: dict[str, Any]
    allowed: dict[str, Any]
    product_context_contract: dict[str, Any]
    agentctl_requirements: dict[str, Any]
    smoke: dict[str, Any]


class StudioAppContext(BaseModel):
    product_id: str
    app_id: str
    legacy_app_id: str
    name: str
    display_name: str
    route_prefix: str
    agentctl_source_app: str
    status: str
    capabilities: list[str] = Field(default_factory=list)
    required_platform_permissions: list[str] = Field(default_factory=list)
    required_agentctl_scopes: list[str] = Field(default_factory=list)
    product_boundary: dict[str, Any] = Field(default_factory=dict)
    enabled_apps: list[str] = Field(default_factory=list)
    backend_product_id: str | None = None


class StudioAgentctlConnectionSummary(BaseModel):
    connection_id: str
    status: str
    product_id: str
    adapter_id: str
    display_name: str
    mode: str
    agentctl_tenant_id: str | None = None
    last_token_exchange_at: datetime | None = None


class StudioAgentctlStatus(BaseModel):
    configured: bool
    base_url: str
    status: str
    detail: str
    connection_count: int = 0
    active_connection_count: int = 0
    connection: StudioAgentctlConnectionSummary | None = None


class StudioModelsContext(BaseModel):
    product_id: str
    status: str
    default_model_hint: str | None = None
    synced_at: datetime | None = None
    models: list[dict[str, Any]] = Field(default_factory=list)


class StudioBootstrapResponse(BaseModel):
    user: UserProfile
    tenant: TenantProfile
    role: str
    permissions: list[str] = Field(default_factory=list)
    app: StudioAppContext
    models: StudioModelsContext
    agentctl: StudioAgentctlStatus


class StudioProfilePlan(BaseModel):
    current_plan_code: str
    pending_plan_code: str | None = None
    status: str = "active"


class StudioProfileDevice(BaseModel):
    device_id: str
    label: str
    status: str
    current: bool = False
    last_seen_at: datetime | None = None
    device_type: str | None = None
    location: str | None = None
    ip_address: str | None = None
    revoked_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class StudioProfileMemory(BaseModel):
    status: str
    scopes: list[str] = Field(default_factory=list)
    clearable: bool = True


StudioProfileOperationType = Literal[
    "plan_request",
    "device_revoke",
    "memory_clear",
    "export_request",
    "migration_request",
    "data_deletion_request",
    "account_closure_request",
]


class StudioProfileOperation(BaseModel):
    operation_id: str
    operation_type: StudioProfileOperationType
    status: Literal[
        "pending",
        "cooling_off",
        "approved",
        "second_review",
        "recovery_window",
        "rejected",
        "canceled",
        "processing",
        "succeeded",
        "failed",
    ]
    user_id: str
    tenant_id: str
    requested_by: str
    requested_at: datetime
    effective_at: datetime | None = None
    cooling_off_seconds: int | None = None
    reason: str | None = None
    source_app: str = "studio"
    audit_event_id: str | None = None
    trace_id: str | None = None
    request_payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StudioProfileResponse(BaseModel):
    user: UserProfile
    tenant: TenantProfile
    role: str
    permissions: list[str] = Field(default_factory=list)
    memberships: list[TenantProfile] = Field(default_factory=list)
    enabled_apps: list[str] = Field(default_factory=list)
    plan: StudioProfilePlan
    devices: list[StudioProfileDevice] = Field(default_factory=list)
    memory: StudioProfileMemory
    pending_operations: list[StudioProfileOperation] = Field(default_factory=list)
    source: str = "api"
    updated_at: datetime | None = None


class StudioProfilePatchRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    locale: str | None = Field(default=None, max_length=40)
    timezone: str | None = Field(default=None, max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StudioPlanRequest(BaseModel):
    target_plan_code: str = Field(min_length=1, max_length=48)
    billing_cycle: Literal["monthly", "annual"] | None = None
    reason: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StudioDeviceRevokeRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=160)
    reason: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StudioMemoryClearRequest(BaseModel):
    scopes: list[str] = Field(default_factory=lambda: ["studio"])
    reason: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StudioExportRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    export_format: Literal["json", "zip"] = Field(default="json", alias="format")
    include: list[str] = Field(default_factory=list)
    include_audit_log: bool = False
    reason: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StudioMigrationRequest(BaseModel):
    target: str | None = Field(default=None, max_length=255)
    target_tenant_id: str | None = Field(default=None, max_length=80)
    target_region: str | None = Field(default=None, max_length=80)
    include: list[str] = Field(default_factory=list)
    reason: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StudioDangerousOperationRequest(BaseModel):
    confirmation: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StudioProfileRequestActionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StudioProfileRequestStatusUpdateRequest(BaseModel):
    status: Literal["processing", "succeeded", "failed"]
    detail: str | None = Field(default=None, max_length=1000)
    external_job_id: str | None = Field(default=None, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StudioProfileRequestJobResponse(BaseModel):
    job_id: str
    profile_request_id: str
    tenant_id: str
    operation_type: StudioProfileOperationType
    status: Literal["queued", "running", "waiting_review", "staged", "succeeded", "failed", "skipped"]
    priority: int = 0
    attempts: int = 0
    max_attempts: int = 3
    run_after: datetime | None = None
    locked_by: str | None = None
    locked_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str | None = None
    trace_id: str | None = None
    audit_event_id: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StudioProfileRequestJobEvidenceResponse(BaseModel):
    evidence_ref: str | None = None
    job_id: str
    profile_request_id: str
    tenant_id: str
    operation_type: StudioProfileOperationType
    request_status: str
    job_status: str
    trace_id: str | None = None
    manifest: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)


class StudioProfileRequestJobRunRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=50)
    request_id: str | None = Field(default=None, max_length=80)
    mode: Literal["dry_run", "apply"] = "dry_run"
    confirm_high_risk: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class StudioProfileRequestJobRunResponse(BaseModel):
    status: Literal["idle", "completed"]
    batch_id: str | None = None
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    retried: int = 0
    waiting_review: int = 0
    staged: int = 0
    jobs: list[StudioProfileRequestJobResponse] = Field(default_factory=list)


class StudioProfileExportArtifactResponse(BaseModel):
    artifact_id: str
    tenant_id: str
    user_id: str
    profile_request_id: str
    job_id: str
    export_format: str
    status: str
    include: list[str] = Field(default_factory=list)
    manifest: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None
    trace_id: str | None = None
    created_at: datetime
    updated_at: datetime


class StudioFrontdeskMessageRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    text: str = Field(min_length=1, max_length=20000)
    context_ref: str | None = Field(default=None, max_length=255)
    intent_hint: dict[str, Any] | None = None
    execute_plan: bool = False
    materialize_action_proposal: bool = False
    use_model_intent: bool = False
    trace_id: str | None = Field(default=None, max_length=160)


class StudioAgentDraftCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    draft_type: Literal["agent", "skill"] | None = None
    kind: Literal["agent", "skill"] | None = None
    title: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, max_length=255)
    natural_language_goal: str | None = Field(default=None, max_length=20000)
    goal: str | None = Field(default=None, max_length=20000)
    description: str | None = Field(default=None, max_length=20000)
    business_context: dict[str, Any] | str | None = None
    constraints: dict[str, Any] | None = None
    requested_outputs: list[str] | None = None
    resource_scope: str | None = Field(default=None, max_length=40)
    owner_user_id: str | None = Field(default=None, max_length=80)
    tenant_id: str | None = Field(default=None, max_length=80)
    tenant: str | None = Field(default=None, max_length=80)
    user_id: str | None = Field(default=None, max_length=80)
    source_app: str | None = Field(default=None, max_length=80)
    use_model: Any | None = None
    trace_id: str | None = Field(default=None, max_length=160)


class StudioAgentDraftDTO(BaseModel):
    draft_id: str | None = None
    kind: str
    status: str
    title: str | None = None
    description: str | None = None
    tenant_id: str | None = None
    user_id: str | None = None
    owner_user_id: str | None = None
    resource_scope: str | None = None
    source_app: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    agentctl: dict[str, Any] = Field(default_factory=dict)
    studio: dict[str, Any] = Field(default_factory=dict)


class StudioAgentDraftListResponse(BaseModel):
    status: str
    detail: str
    drafts: list[StudioAgentDraftDTO] = Field(default_factory=list)
    agentctl: StudioAgentctlStatus
    studio: dict[str, Any] = Field(default_factory=dict)


class StudioAgentDraftActionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    reason: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] | None = None
    trace_id: str | None = Field(default=None, max_length=160)


class StudioAgentTestRunRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    mode: str | None = Field(default="dry_run", max_length=40)
    input: Any | None = None
    inputs: Any | None = None
    prompt: str | None = Field(default=None, max_length=20000)
    message: str | None = Field(default=None, max_length=20000)
    metadata: dict[str, Any] | None = None
    trace_id: str | None = Field(default=None, max_length=160)


class StudioAgentTestRunResponse(BaseModel):
    draft: StudioAgentDraftDTO
    run: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    evidence_ref: str
    trace_id: str
    source: str = "local"
    studio: dict[str, Any] = Field(default_factory=dict)


class StudioWorkflowDraftCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    workflow_id: str | None = Field(default=None, max_length=160)
    draft_id: str | None = Field(default=None, max_length=160)
    title: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, max_length=255)
    natural_language_goal: str | None = Field(default=None, max_length=20000)
    goal: str | None = Field(default=None, max_length=20000)
    description: str | None = Field(default=None, max_length=20000)
    workflow_graph: dict[str, Any] | None = None
    graph: dict[str, Any] | None = None
    canvas: dict[str, Any] | None = None
    nodes: list[dict[str, Any]] | None = None
    edges: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None
    constraints: dict[str, Any] | None = None
    requested_outputs: list[str] | None = None
    resource_scope: str | None = Field(default=None, max_length=40)
    owner_user_id: str | None = Field(default=None, max_length=80)
    tenant_id: str | None = Field(default=None, max_length=80)
    tenant: str | None = Field(default=None, max_length=80)
    user_id: str | None = Field(default=None, max_length=80)
    source_app: str | None = Field(default=None, max_length=80)
    trace_id: str | None = Field(default=None, max_length=160)


class StudioWorkflowDTO(BaseModel):
    workflow_id: str | None = None
    draft_id: str | None = None
    source: str | None = None
    status: str
    title: str | None = None
    description: str | None = None
    tenant_id: str | None = None
    user_id: str | None = None
    owner_user_id: str | None = None
    resource_scope: str | None = None
    source_app: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    workflow_graph: dict[str, Any] | None = None
    agentctl: dict[str, Any] = Field(default_factory=dict)
    studio: dict[str, Any] = Field(default_factory=dict)


class StudioWorkflowListResponse(BaseModel):
    status: str
    detail: str
    workflows: list[StudioWorkflowDTO] = Field(default_factory=list)
    agentctl: StudioAgentctlStatus
    studio: dict[str, Any] = Field(default_factory=dict)


class StudioWorkflowDraftArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    reason: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] | None = None
    trace_id: str | None = Field(default=None, max_length=160)


class StudioWorkflowDraftTestRunRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    mode: str | None = Field(default="dry_run", max_length=40)
    input: Any | None = None
    inputs: Any | None = None
    status: str | None = Field(default=None, max_length=40)
    metadata: dict[str, Any] | None = None
    trace_id: str | None = Field(default=None, max_length=160)


class StudioWorkflowDraftTestRunResponse(BaseModel):
    workflow: StudioWorkflowDTO
    run: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    evidence_ref: str
    trace_id: str
    source: str = "local"
    studio: dict[str, Any] = Field(default_factory=dict)


class StudioWorkflowPublishRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    tool_refs: list[dict[str, Any]] = Field(default_factory=list)
    toolkit_refs: list[str] = Field(default_factory=list)
    mcp_grant_refs: list[str] = Field(default_factory=list)
    mcp_grant_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


class StudioWorkflowAutomationPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool | None = None
    execution_mode: str | None = Field(default=None, max_length=40)
    min_priority: str | None = Field(default=None, max_length=40)
    requires_confirmation: bool | None = None
    max_runs_per_day: int | None = Field(default=None, ge=0)
    max_runs_per_batch: int | None = Field(default=None, ge=0)
    tenant_id: str | None = Field(default=None, max_length=80)
    tenant: str | None = Field(default=None, max_length=80)
    user_id: str | None = Field(default=None, max_length=80)
    owner_user_id: str | None = Field(default=None, max_length=80)
    resource_scope: str | None = Field(default=None, max_length=40)
    metadata: dict[str, Any] | None = None


class StudioWorkflowRunRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    mode: str | None = Field(default=None, max_length=40)
    auto_advance_human: bool | None = None
    input: dict[str, Any] | None = None
    inputs: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    tenant_id: str | None = Field(default=None, max_length=80)
    tenant: str | None = Field(default=None, max_length=80)
    user_id: str | None = Field(default=None, max_length=80)
    owner_user_id: str | None = Field(default=None, max_length=80)
    resource_scope: str | None = Field(default=None, max_length=40)
    source_app: str | None = Field(default=None, max_length=80)
    trace_id: str | None = Field(default=None, max_length=160)


class StudioWorkflowRunResumeRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    workflow_id: str | None = Field(default=None, max_length=160)
    decision: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=5000)
    reviewer: str | None = Field(default=None, max_length=255)
    auto_advance_human: bool | None = None
    metadata: dict[str, Any] | None = None
    tenant_id: str | None = Field(default=None, max_length=80)
    tenant: str | None = Field(default=None, max_length=80)
    user_id: str | None = Field(default=None, max_length=80)
    owner_user_id: str | None = Field(default=None, max_length=80)
    resource_scope: str | None = Field(default=None, max_length=40)
    source_app: str | None = Field(default=None, max_length=80)
    trace_id: str | None = Field(default=None, max_length=160)


class StudioKnowledgeSourceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    source_type: str | None = Field(default=None, max_length=80)
    kind: str | None = Field(default=None, max_length=80)
    title: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=20000)
    uri: str | None = Field(default=None, max_length=2048)
    url: str | None = Field(default=None, max_length=2048)
    metadata: dict[str, Any] | None = None
    resource_scope: str | None = Field(default=None, max_length=40)
    owner_user_id: str | None = Field(default=None, max_length=80)
    tenant_id: str | None = Field(default=None, max_length=80)
    tenant: str | None = Field(default=None, max_length=80)
    user_id: str | None = Field(default=None, max_length=80)
    source_app: str | None = Field(default=None, max_length=80)
    trace_id: str | None = Field(default=None, max_length=160)


class StudioKnowledgeSourceDTO(BaseModel):
    source_id: str | None = None
    document_id: str | None = None
    source_type: str | None = None
    status: str
    ingest_status: str | None = None
    title: str | None = None
    description: str | None = None
    tenant_id: str | None = None
    user_id: str | None = None
    owner_user_id: str | None = None
    resource_scope: str | None = None
    source_app: str | None = None
    chunk_count: int | None = None
    reference_count: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    agentctl: dict[str, Any] = Field(default_factory=dict)
    studio: dict[str, Any] = Field(default_factory=dict)


class StudioKnowledgeSourceListResponse(BaseModel):
    status: str
    detail: str
    sources: list[StudioKnowledgeSourceDTO] = Field(default_factory=list)
    agentctl: StudioAgentctlStatus
    studio: dict[str, Any] = Field(default_factory=dict)


class StudioDriveFileCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = Field(default=None, max_length=160)
    file_id: str | None = Field(default=None, max_length=160)
    object_key: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=255)
    file_name: str | None = Field(default=None, max_length=255)
    content_type: str | None = Field(default=None, max_length=255)
    mime_type: str | None = Field(default=None, max_length=255)
    size_bytes: int | None = Field(default=None, ge=0)
    description: str | None = Field(default=None, max_length=20000)
    status: str | None = Field(default=None, max_length=40)
    tags: list[str] | None = None
    labels: list[str] | None = None
    knowledge_source_ids: list[str] | None = None
    export_artifact_ids: list[str] | None = None
    manifest: dict[str, Any] | None = None
    manifest_json: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    trace_id: str | None = Field(default=None, max_length=160)


class StudioDriveFileDTO(BaseModel):
    id: str
    name: str
    status: str
    content_type: str | None = None
    size_bytes: int | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    knowledge_source_ids: list[str] = Field(default_factory=list)
    export_artifact_ids: list[str] = Field(default_factory=list)
    local_only: bool = False
    trace_id: str | None = None
    source: str = "platform_core_api"
    manifest: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None
    deleted_at: str | None = None


class StudioDriveFileListResponse(BaseModel):
    status: str
    detail: str
    files: list[StudioDriveFileDTO] = Field(default_factory=list)
    source: str = "platform_core_api"
    trace_id: str
    updated_at: str | None = None
    studio: dict[str, Any] = Field(default_factory=dict)


class StudioDriveFileMutationResponse(BaseModel):
    file: StudioDriveFileDTO
    source: str = "platform_core_api"
    trace_id: str
    studio: dict[str, Any] = Field(default_factory=dict)


class ModelCatalogEntryResponse(BaseModel):
    catalog_id: str
    provider_id: str
    model_id: str
    model_hint: str
    display_name: str
    provider_class: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    context_window: int | None = None
    max_output_tokens: int | None = None
    fallback_model_hint: str | None = None
    provider_status: str
    policy_tags: list[str] = Field(default_factory=list)
    is_default: bool = False
    status: str
    updated_at: datetime


class ModelCatalogSyncSummary(BaseModel):
    sync_run_id: str
    status: str
    provider_count: int
    readyz_status: str | None = None
    default_model_hint: str | None = None
    error_detail: str | None = None
    created_at: datetime


class ModelCatalogResponse(BaseModel):
    sync: ModelCatalogSyncSummary | None = None
    entries: list[ModelCatalogEntryResponse] = Field(default_factory=list)


class ModelVisibilityRuleUpsertRequest(BaseModel):
    tenant_id: str
    product_id: str = Field(min_length=1, max_length=80)
    environment: str | None = Field(default=None, max_length=40)
    data_sensitivity: str | None = Field(default=None, max_length=16)
    caller_type: str | None = Field(default=None, max_length=40)
    provider_id: str = Field(min_length=1, max_length=80)
    model_id: str | None = Field(default=None, max_length=120)
    action: Literal["allow", "deny", "default"]
    annotation: str | None = Field(default=None, max_length=255)
    is_user_selectable: bool = True


class ModelVisibilityRuleResponse(BaseModel):
    rule_id: str
    tenant_id: str
    product_id: str
    environment: str | None = None
    data_sensitivity: str | None = None
    caller_type: str | None = None
    provider_id: str
    model_id: str | None = None
    action: str
    annotation: str | None = None
    is_user_selectable: bool
    status: str
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class AuthorizedModelResponse(BaseModel):
    provider_id: str
    model_id: str
    model_hint: str
    display_name: str
    provider_class: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    provider_status: str
    policy_tags: list[str] = Field(default_factory=list)
    authorization_action: str
    annotation: str | None = None
    is_default: bool = False
    is_user_selectable: bool = True
    entitlement_id: str | None = None
    owner_type: str | None = None
    owner_id: str | None = None
    fallback_policy: dict[str, Any] | None = None
    allow_platform_shared_fallback: bool | None = None
    is_shared: bool | None = None
    sharing_scope: str | None = None


class AuthorizedModelsResponse(BaseModel):
    tenant_id: str
    product_id: str
    environment: str | None = None
    data_sensitivity: str | None = None
    caller_type: str | None = None
    default_model_hint: str | None = None
    synced_at: datetime | None = None
    models: list[AuthorizedModelResponse] = Field(default_factory=list)


class ModelKeyCredentialRefResponse(BaseModel):
    credential_ref_id: str
    entitlement_id: str
    provider: str
    model_mask: list[str] = Field(default_factory=list)
    secret_ref: str
    secret_backend: str
    owner_type: str
    owner_id: str
    sharing_scope: str
    status: str
    last_health_status: str | None = None
    last_rotated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ModelKeyCredentialRefMaskedResponse(BaseModel):
    credential_ref_id: str
    entitlement_id: str
    provider: str
    model_mask: list[str] = Field(default_factory=list)
    sharing_scope: str
    status: str
    effective_status: str
    last_health_status: str | None = None
    last_rotated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ModelKeyAllocationCreateRequest(BaseModel):
    product_id: str = Field(min_length=1, max_length=80)
    adapter_id: str | None = Field(default=None, max_length=80)
    user_id: str | None = Field(default=None, max_length=40)
    department_id: str | None = Field(default=None, max_length=80)
    environment: str | None = Field(default=None, max_length=40)
    quota_share_percent: float | None = Field(default=None, ge=0, le=100)
    quota_tokens: int | None = Field(default=None, ge=0)
    priority: int = Field(default=100, ge=0)
    status: Literal["active", "suspended", "revoked"] = "active"


class ModelKeyAllocationResponse(BaseModel):
    allocation_id: str
    entitlement_id: str
    tenant_id: str
    product_id: str
    adapter_id: str | None = None
    user_id: str | None = None
    department_id: str | None = None
    environment: str | None = None
    quota_share_percent: float | None = None
    quota_tokens: int | None = None
    priority: int
    status: str
    created_at: datetime
    updated_at: datetime


class ModelKeyEntitlementCreateRequest(BaseModel):
    purchase_channel: Literal["appstudio", "organization_contract", "admin_grant", "migration"] = "admin_grant"
    product_id: str = Field(min_length=1, max_length=80)
    environment: str | None = Field(default=None, max_length=40)
    status: Literal["pending", "active", "suspended", "expired", "revoked"] = "active"
    plan_code: str | None = Field(default=None, max_length=80)
    quota_rpm: int | None = Field(default=None, ge=0)
    quota_tpm: int | None = Field(default=None, ge=0)
    quota_daily_tokens: int | None = Field(default=None, ge=0)
    quota_monthly_tokens: int | None = Field(default=None, ge=0)
    max_streaming_slots: int | None = Field(default=None, ge=0)
    allowed_providers: list[str] = Field(default_factory=list)
    allowed_models: list[str] = Field(default_factory=list)
    data_sensitivity_limit: str | None = Field(default=None, max_length=16)
    fallback_policy: dict[str, Any] = Field(default_factory=dict)
    allow_platform_shared_fallback: bool = False
    billing_account_id: str | None = Field(default=None, max_length=80)
    approved_by: str | None = Field(default=None, max_length=40)
    expires_at: datetime | None = None


class AppStudioModelEntitlementOrderRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=160)
    product_id: str = Field(default="zhiziagent_studio", min_length=1, max_length=80)
    environment: str | None = Field(default=None, max_length=40)
    status: Literal["pending", "active", "suspended", "expired", "revoked"] = "active"
    plan_code: str | None = Field(default=None, max_length=80)
    quota_rpm: int | None = Field(default=None, ge=0)
    quota_tpm: int | None = Field(default=None, ge=0)
    quota_daily_tokens: int | None = Field(default=None, ge=0)
    quota_monthly_tokens: int | None = Field(default=None, ge=0)
    max_streaming_slots: int | None = Field(default=None, ge=0)
    allowed_providers: list[str] = Field(default_factory=list)
    allowed_models: list[str] = Field(default_factory=list)
    data_sensitivity_limit: str | None = Field(default=None, max_length=16)
    fallback_policy: dict[str, Any] = Field(default_factory=dict)
    allow_platform_shared_fallback: bool = False
    billing_account_id: str | None = Field(default=None, max_length=80)
    billing_cycle: Literal["monthly", "annual"] | None = None
    amount_cents: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=12)
    payment_provider: str | None = Field(default=None, max_length=40)
    payment_status: Literal["unpaid", "pending", "paid", "failed", "partially_refunded", "refunded", "canceled"] = "paid"
    subscription_id: str | None = Field(default=None, max_length=160)
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AppStudioPlanCatalogItem(BaseModel):
    product_id: str
    plan_code: str
    name: str
    price_label: str
    billing_cycle: str | None = None
    amount_cents: int | None = None
    currency: str
    quota_rpm: int | None = None
    quota_tpm: int | None = None
    quota_daily_tokens: int | None = None
    quota_monthly_tokens: int | None = None
    max_streaming_slots: int | None = None
    allowed_providers: list[str] = Field(default_factory=list)
    allowed_models: list[str] = Field(default_factory=list)
    data_sensitivity_limit: str | None = None
    allow_platform_shared_fallback: bool = False
    description: str
    features: list[str] = Field(default_factory=list)
    status: str = "active"


class ModelKeyEntitlementResponse(BaseModel):
    entitlement_id: str
    owner_type: str
    owner_id: str
    purchase_channel: str
    product_id: str
    environment: str | None = None
    status: str
    plan_code: str | None = None
    quota_rpm: int | None = None
    quota_tpm: int | None = None
    quota_daily_tokens: int | None = None
    quota_monthly_tokens: int | None = None
    max_streaming_slots: int | None = None
    allowed_providers: list[str] = Field(default_factory=list)
    allowed_models: list[str] = Field(default_factory=list)
    data_sensitivity_limit: str | None = None
    fallback_policy: dict[str, Any] = Field(default_factory=dict)
    allow_platform_shared_fallback: bool = False
    billing_account_id: str | None = None
    created_by: str | None = None
    approved_by: str | None = None
    expires_at: datetime | None = None
    credential_refs: list[ModelKeyCredentialRefResponse] = Field(default_factory=list)
    allocations: list[ModelKeyAllocationResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ModelKeyPersonalEntitlementResponse(BaseModel):
    entitlement_id: str
    owner_type: str
    owner_id: str
    purchase_channel: str
    product_id: str
    environment: str | None = None
    status: str
    plan_code: str | None = None
    quota_rpm: int | None = None
    quota_tpm: int | None = None
    quota_daily_tokens: int | None = None
    quota_monthly_tokens: int | None = None
    max_streaming_slots: int | None = None
    allowed_providers: list[str] = Field(default_factory=list)
    allowed_models: list[str] = Field(default_factory=list)
    data_sensitivity_limit: str | None = None
    fallback_policy: dict[str, Any] = Field(default_factory=dict)
    allow_platform_shared_fallback: bool = False
    billing_account_id: str | None = None
    created_by: str | None = None
    approved_by: str | None = None
    expires_at: datetime | None = None
    credential_refs: list[ModelKeyCredentialRefMaskedResponse] = Field(default_factory=list)
    allocations: list[ModelKeyAllocationResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class AppStudioModelEntitlementOrderResponse(BaseModel):
    order_id: str
    idempotency_key: str | None = None
    tenant_id: str
    owner_type: str
    owner_id: str
    product_id: str
    plan_code: str | None = None
    billing_account_id: str | None = None
    billing_cycle: str | None = None
    amount_cents: int | None = None
    currency: str | None = None
    payment_provider: str | None = None
    payment_status: str | None = None
    subscription_id: str | None = None
    refunded_amount_cents: int = 0
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    canceled_at: datetime | None = None
    order_status: str
    idempotent_replay: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    entitlement: ModelKeyPersonalEntitlementResponse
    created_at: datetime
    updated_at: datetime


class ModelKeyRedemptionCodeCreateRequest(BaseModel):
    batch_id: str | None = Field(default=None, max_length=80)
    label: str | None = Field(default=None, max_length=160)
    product_id: str = Field(default="zhiziagent_studio", min_length=1, max_length=80)
    plan_code: str | None = Field(default="studio_test", max_length=80)
    max_redemptions: int = Field(default=1, ge=1, le=10000)
    quota_rpm: int | None = Field(default=20, ge=0)
    quota_tpm: int | None = Field(default=120000, ge=0)
    quota_daily_tokens: int | None = Field(default=200000, ge=0)
    quota_monthly_tokens: int | None = Field(default=2000000, ge=0)
    max_streaming_slots: int | None = Field(default=2, ge=0)
    allowed_providers: list[str] = Field(default_factory=list)
    allowed_models: list[str] = Field(default_factory=lambda: ["*"])
    data_sensitivity_limit: str | None = Field(default="D2", max_length=16)
    fallback_policy: dict[str, Any] = Field(default_factory=dict)
    allow_platform_shared_fallback: bool = True
    billing_cycle: Literal["monthly", "annual", "trial"] | None = "trial"
    amount_cents: int = Field(default=0, ge=0)
    currency: str = Field(default="CNY", min_length=3, max_length=12)
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelKeyRedemptionCodeResponse(BaseModel):
    redemption_code_id: str
    code: str | None = None
    code_prefix: str
    code_suffix: str
    batch_id: str | None = None
    label: str | None = None
    product_id: str
    plan_code: str | None = None
    status: str
    max_redemptions: int
    redeemed_count: int
    quota_rpm: int | None = None
    quota_tpm: int | None = None
    quota_daily_tokens: int | None = None
    quota_monthly_tokens: int | None = None
    max_streaming_slots: int | None = None
    allowed_providers: list[str] = Field(default_factory=list)
    allowed_models: list[str] = Field(default_factory=list)
    data_sensitivity_limit: str | None = None
    allow_platform_shared_fallback: bool
    billing_cycle: str | None = None
    amount_cents: int
    currency: str
    expires_at: datetime | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ModelKeyRedemptionRedeemRequest(BaseModel):
    code: str = Field(min_length=8, max_length=120)
    product_id: str | None = Field(default=None, min_length=1, max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelKeyRedemptionRedeemResponse(BaseModel):
    redemption_code_id: str
    redemption_id: str
    order: AppStudioModelEntitlementOrderResponse


class AppStudioModelEntitlementOrderPaymentUpdateRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=40)
    owner_id: str = Field(min_length=1, max_length=80)
    product_id: str = Field(default="zhiziagent_studio", min_length=1, max_length=80)
    payment_status: Literal["unpaid", "pending", "paid", "failed", "partially_refunded", "refunded", "canceled"]
    order_status: Literal["pending", "completed", "failed", "refunded", "canceled"] | None = None
    entitlement_status: Literal["pending", "active", "suspended", "expired", "revoked"] | None = None
    billing_account_id: str | None = Field(default=None, max_length=80)
    subscription_id: str | None = Field(default=None, max_length=160)
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool | None = None
    canceled_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AppStudioBillingInvoiceRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=40)
    owner_id: str = Field(min_length=1, max_length=80)
    product_id: str = Field(default="zhiziagent_studio", min_length=1, max_length=80)
    invoice_id: str = Field(min_length=1, max_length=160)
    amount_cents: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=12)
    invoice_status: Literal["draft", "open", "paid", "void", "uncollectible", "refunded"] = "open"
    billing_account_id: str | None = Field(default=None, max_length=80)
    payment_provider: str | None = Field(default=None, max_length=40)
    external_invoice_id: str | None = Field(default=None, max_length=160)
    hosted_invoice_url: str | None = Field(default=None, max_length=2048)
    invoice_pdf_url: str | None = Field(default=None, max_length=2048)
    subtotal_cents: int | None = Field(default=None, ge=0)
    tax_cents: int | None = Field(default=None, ge=0)
    discount_cents: int | None = Field(default=None, ge=0)
    amount_due_cents: int | None = Field(default=None, ge=0)
    amount_paid_cents: int | None = Field(default=None, ge=0)
    amount_remaining_cents: int | None = Field(default=None, ge=0)
    issued_at: datetime | None = None
    due_at: datetime | None = None
    paid_at: datetime | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    line_items: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AppStudioBillingInvoiceResponse(BaseModel):
    invoice_id: str
    order_id: str
    entitlement_id: str
    tenant_id: str
    owner_type: str
    owner_id: str
    product_id: str
    billing_account_id: str | None = None
    amount_cents: int
    subtotal_cents: int | None = None
    tax_cents: int | None = None
    discount_cents: int | None = None
    amount_due_cents: int | None = None
    amount_paid_cents: int | None = None
    amount_remaining_cents: int | None = None
    currency: str
    status: str
    payment_provider: str
    external_invoice_id: str | None = None
    hosted_invoice_url: str | None = None
    invoice_pdf_url: str | None = None
    issued_at: datetime | None = None
    due_at: datetime | None = None
    paid_at: datetime | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    line_items: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class AppStudioBillingRefundRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=40)
    owner_id: str = Field(min_length=1, max_length=80)
    product_id: str = Field(default="zhiziagent_studio", min_length=1, max_length=80)
    refund_id: str = Field(min_length=1, max_length=160)
    invoice_id: str | None = Field(default=None, max_length=160)
    amount_cents: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=12)
    refund_status: Literal["pending", "succeeded", "failed", "canceled"] = "pending"
    reason: str | None = Field(default=None, max_length=255)
    payment_provider: str | None = Field(default=None, max_length=40)
    external_refund_id: str | None = Field(default=None, max_length=160)
    refunded_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AppStudioBillingRefundResponse(BaseModel):
    refund_id: str
    order_id: str
    invoice_id: str | None = None
    entitlement_id: str
    tenant_id: str
    owner_type: str
    owner_id: str
    product_id: str
    amount_cents: int
    currency: str
    status: str
    reason: str | None = None
    payment_provider: str
    external_refund_id: str | None = None
    refunded_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class AppStudioOrderBillingResponse(BaseModel):
    order: AppStudioModelEntitlementOrderResponse
    invoices: list[AppStudioBillingInvoiceResponse] = Field(default_factory=list)
    refunds: list[AppStudioBillingRefundResponse] = Field(default_factory=list)
    refunded_amount_cents: int = 0


class AppStudioPaymentGatewayEventRequest(BaseModel):
    payment_provider: str = Field(min_length=1, max_length=40)
    event_id: str = Field(min_length=1, max_length=160)
    event_type: str = Field(min_length=1, max_length=120)
    tenant_id: str = Field(min_length=1, max_length=40)
    owner_id: str = Field(min_length=1, max_length=80)
    product_id: str = Field(default="zhiziagent_studio", min_length=1, max_length=80)
    order_id: str | None = Field(default=None, max_length=160)
    idempotency_key: str | None = Field(default=None, max_length=160)
    invoice_id: str | None = Field(default=None, max_length=160)
    invoice_status: Literal["draft", "open", "paid", "void", "uncollectible", "refunded"] | None = None
    refund_id: str | None = Field(default=None, max_length=160)
    refund_status: Literal["pending", "succeeded", "failed", "canceled"] | None = None
    payment_status: Literal["unpaid", "pending", "paid", "failed", "partially_refunded", "refunded", "canceled"] | None = None
    billing_account_id: str | None = Field(default=None, max_length=80)
    subscription_id: str | None = Field(default=None, max_length=160)
    amount_cents: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=12)
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool | None = None
    external_invoice_id: str | None = Field(default=None, max_length=160)
    hosted_invoice_url: str | None = Field(default=None, max_length=2048)
    invoice_pdf_url: str | None = Field(default=None, max_length=2048)
    subtotal_cents: int | None = Field(default=None, ge=0)
    tax_cents: int | None = Field(default=None, ge=0)
    discount_cents: int | None = Field(default=None, ge=0)
    amount_due_cents: int | None = Field(default=None, ge=0)
    amount_paid_cents: int | None = Field(default=None, ge=0)
    amount_remaining_cents: int | None = Field(default=None, ge=0)
    external_refund_id: str | None = Field(default=None, max_length=160)
    reason: str | None = Field(default=None, max_length=255)
    occurred_at: datetime | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    line_items: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class AppStudioPaymentGatewayEventResponse(BaseModel):
    event_id: str
    payment_provider: str
    event_type: str
    tenant_id: str
    owner_id: str
    product_id: str
    order_id: str | None = None
    idempotency_key: str | None = None
    status: str
    resource_type: str | None = None
    resource_id: str | None = None
    idempotent_replay: bool = False
    occurred_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    order: AppStudioModelEntitlementOrderResponse | None = None
    invoice: AppStudioBillingInvoiceResponse | None = None
    refund: AppStudioBillingRefundResponse | None = None
    created_at: datetime
    updated_at: datetime


class AppStudioRenewalRunRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=40)
    product_id: str = Field(default="zhiziagent_studio", min_length=1, max_length=80)
    due_before: datetime | None = None
    dry_run: bool = False
    limit: int = Field(default=50, ge=1, le=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AppStudioRenewalRunItemResponse(BaseModel):
    renewal_run_id: str
    source_order_id: str
    renewal_order_id: str | None = None
    tenant_id: str
    owner_id: str
    product_id: str
    subscription_id: str | None = None
    due_at: datetime
    period_start: datetime
    period_end: datetime
    status: str
    dry_run: bool
    error_detail: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class AppStudioRenewalRunResponse(BaseModel):
    status: str
    dry_run: bool
    due_before: datetime
    scanned_count: int = 0
    created_count: int = 0
    skipped_count: int = 0
    items: list[AppStudioRenewalRunItemResponse] = Field(default_factory=list)


class ModelKeyByokRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=80)
    model_mask: list[str] = Field(default_factory=list)
    secret_ref: str | None = Field(default=None, max_length=255)
    raw_key: str | None = Field(default=None, min_length=1, max_length=8192)
    secret_backend: Literal["env", "vault", "kms", "cloud_secret_manager"] = "vault"
    sharing_scope: Literal["personal_only", "organization_only", "platform_shared"] | None = None
    status: Literal["active", "suspended", "revoked"] = "active"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelKeyPersonalByokRequest(ModelKeyByokRequest):
    entitlement_id: str = Field(min_length=1, max_length=40)


class ModelKeyPersonalByokRotateRequest(BaseModel):
    secret_ref: str | None = Field(default=None, max_length=255)
    raw_key: str | None = Field(default=None, min_length=1, max_length=8192)
    secret_backend: Literal["env", "vault", "kms", "cloud_secret_manager"] = "vault"
    model_mask: list[str] | None = None
    status: Literal["active", "suspended"] = "active"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelKeyPersonalByokStatusUpdateRequest(BaseModel):
    status: Literal["active", "suspended"]
    reason: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelKeyPersonalByokRevokeRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StudioRelayApiKeyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: str = Field(
        min_length=1,
        max_length=120,
        validation_alias=AliasChoices("name", "displayName", "display_name", "label"),
    )
    allowed_products: list[str] = Field(
        default_factory=lambda: ["zhiziagent_studio"],
        validation_alias=AliasChoices("allowed_products", "allowedProducts", "products", "productIds", "product_ids"),
    )
    allowed_models: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("allowed_models", "allowedModels", "models", "modelMask", "model_mask"),
    )
    quota_rpm: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("quota_rpm", "quotaRpm", "rpm"),
    )
    quota_tpm: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("quota_tpm", "quotaTpm", "tpm"),
    )
    quota_daily_tokens: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("quota_daily_tokens", "quotaDailyTokens"),
    )
    quota_monthly_tokens: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("quota_monthly_tokens", "quotaMonthlyTokens"),
    )
    billing_account_id: str | None = Field(
        default=None,
        max_length=80,
        validation_alias=AliasChoices("billing_account_id", "billingAccountId"),
    )
    expires_at: datetime | None = Field(default=None, validation_alias=AliasChoices("expires_at", "expiresAt"))
    metadata: dict[str, Any] = Field(default_factory=dict)


class StudioRelayApiKeyResponse(BaseModel):
    id: str
    key_id: str
    credential_ref_id: str
    entitlement_id: str
    name: str
    status: str
    scope: str = "external_api"
    masked_key: str | None = None
    last_four: str | None = None
    allowed_products: list[str] = Field(default_factory=list)
    allowed_models: list[str] = Field(default_factory=list)
    quota_rpm: int | None = None
    quota_tpm: int | None = None
    quota_daily_tokens: int | None = None
    quota_monthly_tokens: int | None = None
    usage_monthly_tokens: int | None = None
    billing_account_id: str | None = None
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class StudioRelayApiKeysResponse(BaseModel):
    keys: list[StudioRelayApiKeyResponse] = Field(default_factory=list)
    source: str = "platform_core"
    updated_at: datetime | None = None


class StudioRelayApiKeyMutationResponse(BaseModel):
    key: StudioRelayApiKeyResponse
    plain_key: str | None = None
    source: str = "platform_core"


class ModelUsageAttributionRequest(BaseModel):
    usage_event_id: str | None = Field(default=None, max_length=160)
    trace_id: str | None = Field(default=None, max_length=160)
    run_id: str | None = Field(default=None, max_length=160)
    owner_type: Literal["personal_user", "organization"]
    owner_id: str = Field(min_length=1, max_length=80)
    tenant_id: str = Field(min_length=1, max_length=40)
    product_id: str = Field(min_length=1, max_length=80)
    adapter_id: str | None = Field(default=None, max_length=80)
    caller_user_id: str | None = Field(default=None, max_length=80)
    entitlement_id: str | None = Field(default=None, max_length=40)
    credential_ref_id: str | None = Field(default=None, max_length=40)
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=120)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_amount: float | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    status: str = Field(default="succeeded", max_length=40)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelUsageAttributionResponse(BaseModel):
    id: str
    usage_event_id: str | None = None
    trace_id: str | None = None
    run_id: str | None = None
    owner_type: str
    owner_id: str
    tenant_id: str
    product_id: str
    adapter_id: str | None = None
    caller_user_id: str | None = None
    entitlement_id: str | None = None
    credential_ref_id: str | None = None
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_amount: float | None = None
    latency_ms: int | None = None
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ModelUsageSummaryItem(BaseModel):
    provider: str
    model: str
    entitlement_id: str | None = None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    event_count: int
    cost_amount: float | None = None


class ModelUsageEntitlementSummary(BaseModel):
    entitlement_id: str
    product_id: str
    plan_code: str | None = None
    quota_daily_tokens: int | None = None
    quota_monthly_tokens: int | None = None
    used_tokens: int
    used_daily_tokens: int
    used_monthly_tokens: int
    remaining_daily_tokens: int | None = None
    remaining_monthly_tokens: int | None = None
    cost_amount: float | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None


class ModelUsageSummaryResponse(BaseModel):
    owner_type: str = "personal_user"
    owner_id: str
    product_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    event_count: int
    cost_amount: float | None = None
    by_model: list[ModelUsageSummaryItem] = Field(default_factory=list)
    by_entitlement: list[ModelUsageEntitlementSummary] = Field(default_factory=list)


class ModelUsageEventsIngestResponse(BaseModel):
    accepted_count: int
    events: list[ModelUsageAttributionResponse] = Field(default_factory=list)


class ModelKeyHealthEventRequest(BaseModel):
    credential_ref_id: str | None = Field(default=None, max_length=40)
    entitlement_id: str | None = Field(default=None, max_length=40)
    provider: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=120)
    health_status: str = Field(min_length=1, max_length=40)
    latency_ms: int | None = Field(default=None, ge=0)
    error_rate: float | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelKeyHealthEventsIngestResponse(BaseModel):
    accepted_count: int
    updated_credential_ref_ids: list[str] = Field(default_factory=list)


class AgentctlCredentialRefSnapshot(BaseModel):
    credential_ref_id: str
    entitlement_id: str
    provider: str
    model_mask: list[str] = Field(default_factory=list)
    secret_ref: str
    secret_backend: str
    sharing_scope: str
    status: str
    last_health_status: str | None = None
    last_rotated_at: datetime | None = None
    updated_at: datetime


class AgentctlEntitlementSnapshot(BaseModel):
    entitlement_id: str
    owner_type: str
    owner_id: str
    tenant_id: str
    product_id: str
    environment: str | None = None
    status: str
    plan_code: str | None = None
    quota_rpm: int | None = None
    quota_tpm: int | None = None
    quota_daily_tokens: int | None = None
    quota_monthly_tokens: int | None = None
    max_streaming_slots: int | None = None
    allowed_providers: list[str] = Field(default_factory=list)
    allowed_models: list[str] = Field(default_factory=list)
    data_sensitivity_limit: str | None = None
    fallback_policy: dict[str, Any] = Field(default_factory=dict)
    allow_platform_shared_fallback: bool = False
    expires_at: datetime | None = None
    credential_refs: list[AgentctlCredentialRefSnapshot] = Field(default_factory=list)
    allocations: list[ModelKeyAllocationResponse] = Field(default_factory=list)


class AgentctlEntitlementsSyncResponse(BaseModel):
    synced_at: datetime
    entitlements: list[AgentctlEntitlementSnapshot] = Field(default_factory=list)


class CreateInvitationRequest(BaseModel):
    email: str
    role: str = "member"
    expires_in_days: int = Field(default=7, ge=1, le=30)


class InvitationResponse(BaseModel):
    id: str
    tenant_id: str
    email: str
    role: str
    status: str
    invited_by: str
    accepted_user_id: str | None
    expires_at: datetime
    created_at: datetime
    invite_url: str | None = None


class InvitationPublicResponse(BaseModel):
    tenant_id: str
    tenant_name: str
    email: str
    role: str
    status: str
    expires_at: datetime


class AcceptInvitationRequest(BaseModel):
    password: str = Field(min_length=8)
    display_name: str | None = Field(default=None, max_length=120)


class AuditEventRequest(BaseModel):
    tenant_id: str | None = None
    app_id: str | None = None
    action: str = Field(min_length=1, max_length=120)
    resource_type: str | None = None
    resource_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditEventResponse(BaseModel):
    id: str
    tenant_id: str
    actor_type: str
    actor_id: str
    app_id: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    metadata: dict[str, Any]
    created_at: datetime


class UsageEventRequest(BaseModel):
    tenant_id: str | None = None
    app_id: str = Field(min_length=1, max_length=80)
    metric_code: str = Field(min_length=1, max_length=120)
    quantity: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=32)
    source_event_id: str | None = Field(default=None, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None


class UsageEventResponse(BaseModel):
    id: str
    tenant_id: str
    actor_type: str
    actor_id: str
    app_id: str
    metric_code: str
    quantity: float
    unit: str
    source_event_id: str | None
    metadata: dict[str, Any]
    occurred_at: datetime
    created_at: datetime


class UsageSummaryItem(BaseModel):
    metric_code: str
    unit: str
    total_quantity: float
    event_count: int


class ParseBrokerDocumentRequest(BaseModel):
    doc_id: str | None = Field(default=None, max_length=120)
    product_id: str | None = Field(default=None, max_length=80)
    file_name: str = Field(min_length=1, max_length=255)
    media_type: str | None = Field(default=None, max_length=160)
    file_base64: str = Field(min_length=1)
    enable_ocr: bool = False
    options: dict[str, Any] = Field(default_factory=dict)
    quota_key: str | None = Field(default=None, max_length=120)
    quota_units: int = Field(default=1, ge=1)
    trace_id: str | None = Field(default=None, max_length=160)


class ParseBrokerDocumentResponse(BaseModel):
    trace_id: str
    tenant_id: str
    product_id: str
    doc_id: str
    status: str
    parsecore: dict[str, Any]
    audit_event_id: str | None = None
    usage_event_id: str | None = None


class ParseBrokerDocumentSnapshotResponse(BaseModel):
    trace_id: str
    tenant_id: str
    product_id: str
    doc_id: str
    parsecore: dict[str, Any]
    audit_event_id: str | None = None


class ParseBrokerSearchResponse(BaseModel):
    trace_id: str
    tenant_id: str
    product_id: str
    doc_id: str
    query: str
    parsecore: dict[str, Any]
    audit_event_id: str | None = None


class ParseBrokerHealthResponse(BaseModel):
    parsecore_base_url: str
    health: dict[str, Any]


class IntrospectionResponse(BaseModel):
    active: bool
    user_id: str | None = None
    tenant_id: str | None = None
    role: str | None = None
    permissions: list[str] = Field(default_factory=list)
    apps: list[str] = Field(default_factory=list)


class PermissionResponse(BaseModel):
    code: str
    description: str


class RoleResponse(BaseModel):
    role: str
    permissions: list[str]


class PlatformSummaryResponse(BaseModel):
    tenant_id: str
    tenant_name: str
    member_count: int
    enabled_app_count: int
    service_account_count: int
    audit_event_count: int
    usage_event_count: int
    available_app_count: int
    role: str
    permissions: list[str]


class BootstrapStatusResponse(BaseModel):
    initialized: bool
    user_count: int
    tenant_count: int
    app_env: str
    database_kind: str
    platform_admin_configured: bool = False


class BootstrapRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)
    display_name: str = Field(min_length=1, max_length=120)
    tenant_name: str = Field(min_length=1, max_length=160)


class PlatformAdminBootstrapRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)
    display_name: str = Field(min_length=1, max_length=120)
    tenant_name: str = Field(default="ZhiziAgent Platform Admin", min_length=1, max_length=160)
    tenant_slug: str = Field(default="platform-admin", min_length=3, max_length=80)


class ConfigCheckItem(BaseModel):
    key: str
    label: str
    status: str
    detail: str


class ConfigCheckResponse(BaseModel):
    app_env: str
    database_kind: str
    jwt_secret_configured: bool
    auto_create_schema: bool
    cors_origins: list[str]
    warnings: list[str]
    checks: list[ConfigCheckItem]


class MigrationPlanResponse(BaseModel):
    current_strategy: str
    alembic_ready: bool
    commands: list[str]
    notes: list[str]
