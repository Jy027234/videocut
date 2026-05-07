from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("usr"))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False, index=True)
    mfa_totp_secret: Mapped[str | None] = mapped_column(String(80), nullable=True)
    mfa_totp_pending_secret: Mapped[str | None] = mapped_column(String(80), nullable=True)
    mfa_totp_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    memberships: Mapped[list[TenantMember]] = relationship(back_populates="user")


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ten"))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    tenant_type: Mapped[str] = mapped_column(String(24), default="team", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False, index=True)
    plan_code: Mapped[str] = mapped_column(String(48), default="starter", nullable=False)

    members: Mapped[list[TenantMember]] = relationship(back_populates="tenant")
    apps: Mapped[list[TenantApp]] = relationship(back_populates="tenant")


class TenantMember(Base, TimestampMixin):
    __tablename__ = "tenant_members"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_tenant_member"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mem"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="member", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False)

    tenant: Mapped[Tenant] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class TenantInvitation(Base, TimestampMixin):
    __tablename__ = "tenant_invitations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("inv"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="member", nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False, index=True)
    invited_by: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    accepted_user_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Permission(Base, TimestampMixin):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(120), primary_key=True)
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False)


class RolePermission(Base, TimestampMixin):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role", "permission_code", name="uq_role_permission"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("rpe"))
    role: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    permission_code: Mapped[str] = mapped_column(
        ForeignKey("permissions.code"), index=True, nullable=False
    )


class AppModule(Base, TimestampMixin):
    __tablename__ = "app_modules"

    app_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False)
    entry_web: Mapped[str | None] = mapped_column(String(255), nullable=True)
    entry_api: Mapped[str | None] = mapped_column(String(255), nullable=True)
    manifest_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class TenantApp(Base, TimestampMixin):
    __tablename__ = "tenant_apps"
    __table_args__ = (UniqueConstraint("tenant_id", "app_id", name="uq_tenant_app"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("tap"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    app_id: Mapped[str] = mapped_column(ForeignKey("app_modules.app_id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="enabled", nullable=False)
    enabled_by: Mapped[str | None] = mapped_column(String(40), nullable=True)

    tenant: Mapped[Tenant] = relationship(back_populates="apps")
    app: Mapped[AppModule] = relationship()


class ServiceAccount(Base, TimestampMixin):
    __tablename__ = "service_accounts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("svc"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    app_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    scopes_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)


class IntegrationGrant(Base, TimestampMixin):
    __tablename__ = "integration_grants"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("igr"))
    tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    product_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    adapter_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    mode: Mapped[str] = mapped_column(String(24), nullable=False)
    grant_code_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    agentctl_policy_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False, index=True)


class IntegrationConnection(Base, TimestampMixin):
    __tablename__ = "integration_connections"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("icn"))
    tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    product_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    adapter_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    mode: Mapped[str] = mapped_column(String(24), nullable=False)
    agentctl_tenant_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    agentctl_policy_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    platform_service_account_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    environment: Mapped[str | None] = mapped_column(String(40), nullable=True)
    callback_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False, index=True)
    last_token_exchange_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IntegrationRequest(Base, TimestampMixin):
    __tablename__ = "integration_requests"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("irq"))
    tenant_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    product_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    adapter_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    vendor: Mapped[str | None] = mapped_column(String(160), nullable=True)
    mode: Mapped[str] = mapped_column(String(40), nullable=False)
    environment: Mapped[str | None] = mapped_column(String(40), nullable=True)
    callback_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    jwks_uri: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requested_tenants_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    requested_platform_scopes_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    requested_agentctl_scopes_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    requested_agentctl_operations_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    requested_models_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    product_context_contract_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    manifest_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False, index=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    grant_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    connection_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)


class IntegrationDeviceAuthorization(Base, TimestampMixin):
    __tablename__ = "integration_device_authorizations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ida"))
    request_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    device_code_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    user_code_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connection_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class IntegrationTokenExchange(Base):
    __tablename__ = "integration_token_exchanges"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("itx"))
    connection_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    agentctl_token_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    requested_scopes_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    product_operation: Mapped[str | None] = mapped_column(String(120), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(80), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="issued", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class ModelCatalogSyncRun(Base):
    __tablename__ = "model_catalog_sync_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mcs"))
    status: Mapped[str] = mapped_column(String(24), default="succeeded", nullable=False, index=True)
    provider_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    readyz_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    default_provider_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    default_model_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class ModelCatalogEntry(Base, TimestampMixin):
    __tablename__ = "model_catalog_entries"
    __table_args__ = (UniqueConstraint("provider_id", "model_id", name="uq_model_catalog_entry"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mdl"))
    sync_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_catalog_sync_runs.id"), index=True, nullable=True
    )
    provider_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    model_id: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider_class: Mapped[str | None] = mapped_column(String(40), nullable=True)
    capabilities_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fallback_model_hint: Mapped[str | None] = mapped_column(String(160), nullable=True)
    provider_status: Mapped[str] = mapped_column(String(24), default="unknown", nullable=False, index=True)
    policy_tags_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False, index=True)


class ModelVisibilityRule(Base, TimestampMixin):
    __tablename__ = "model_visibility_rules"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mvr"))
    tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    product_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    environment: Mapped[str | None] = mapped_column(String(40), nullable=True)
    data_sensitivity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    caller_type: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    provider_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    annotation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_user_selectable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False, index=True)
    created_by: Mapped[str | None] = mapped_column(String(40), nullable=True)


class ModelKeyEntitlement(Base, TimestampMixin):
    __tablename__ = "model_key_entitlements"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mke"))
    owner_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    purchase_channel: Mapped[str] = mapped_column(String(40), nullable=False)
    product_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    environment: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False, index=True)
    plan_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    quota_rpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quota_tpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quota_daily_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quota_monthly_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_streaming_slots: Mapped[int | None] = mapped_column(Integer, nullable=True)
    allowed_providers_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    allowed_models_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    data_sensitivity_limit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fallback_policy_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    allow_platform_shared_fallback: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    billing_account_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class ModelKeyEntitlementOrder(Base, TimestampMixin):
    __tablename__ = "model_key_entitlement_orders"
    __table_args__ = (
        UniqueConstraint("purchase_channel", "product_id", "order_id", name="uq_model_key_entitlement_order"),
        UniqueConstraint(
            "purchase_channel",
            "product_id",
            "idempotency_key",
            name="uq_model_key_entitlement_order_idempotency",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("meo"))
    order_id: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    entitlement_id: Mapped[str] = mapped_column(
        ForeignKey("model_key_entitlements.id"), index=True, nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    purchase_channel: Mapped[str] = mapped_column(String(40), nullable=False)
    product_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    plan_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    billing_account_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    billing_cycle: Mapped[str | None] = mapped_column(String(24), nullable=True)
    amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(12), nullable=True)
    payment_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payment_status: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    subscription_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    refunded_amount_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="completed", nullable=False, index=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ModelKeyRedemptionCode(Base, TimestampMixin):
    __tablename__ = "model_key_redemption_codes"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mrc"))
    code_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    code_prefix: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    code_suffix: Mapped[str] = mapped_column(String(12), nullable=False)
    batch_id: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    product_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    plan_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False, index=True)
    max_redemptions: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    redeemed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quota_rpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quota_tpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quota_daily_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quota_monthly_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_streaming_slots: Mapped[int | None] = mapped_column(Integer, nullable=True)
    allowed_providers_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    allowed_models_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    data_sensitivity_limit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fallback_policy_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    allow_platform_shared_fallback: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    billing_cycle: Mapped[str | None] = mapped_column(String(24), nullable=True)
    amount_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(12), default="CNY", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ModelKeyRedemption(Base, TimestampMixin):
    __tablename__ = "model_key_redemptions"
    __table_args__ = (
        UniqueConstraint("redemption_code_id", "user_id", name="uq_model_key_redemption_code_user"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mrd"))
    redemption_code_id: Mapped[str] = mapped_column(
        ForeignKey("model_key_redemption_codes.id"), index=True, nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    entitlement_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    order_id: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="redeemed", nullable=False, index=True)
    redeemed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ModelKeyBillingInvoice(Base, TimestampMixin):
    __tablename__ = "model_key_billing_invoices"
    __table_args__ = (
        UniqueConstraint("payment_provider", "invoice_id", name="uq_model_key_billing_invoice_provider_invoice"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mki"))
    invoice_id: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    entitlement_order_id: Mapped[str] = mapped_column(
        ForeignKey("model_key_entitlement_orders.id"), index=True, nullable=False
    )
    entitlement_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    product_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    billing_account_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    subtotal_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tax_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_due_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_paid_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_remaining_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="open", nullable=False, index=True)
    payment_provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    external_invoice_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    hosted_invoice_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    line_items_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ModelKeyBillingRefund(Base, TimestampMixin):
    __tablename__ = "model_key_billing_refunds"
    __table_args__ = (
        UniqueConstraint("payment_provider", "refund_id", name="uq_model_key_billing_refund_provider_refund"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mkr"))
    refund_id: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    entitlement_order_id: Mapped[str] = mapped_column(
        ForeignKey("model_key_entitlement_orders.id"), index=True, nullable=False
    )
    invoice_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    entitlement_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    product_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payment_provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    external_refund_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ModelKeyPaymentGatewayEvent(Base, TimestampMixin):
    __tablename__ = "model_key_payment_gateway_events"
    __table_args__ = (
        UniqueConstraint("payment_provider", "event_id", name="uq_model_key_payment_gateway_event_provider_event"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mpg"))
    payment_provider: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    event_id: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    product_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    order_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="accepted", nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ModelKeyRenewalRun(Base, TimestampMixin):
    __tablename__ = "model_key_renewal_runs"
    __table_args__ = (
        UniqueConstraint("source_order_id", "period_start", name="uq_model_key_renewal_run_source_period"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mrr"))
    source_order_id: Mapped[str] = mapped_column(
        ForeignKey("model_key_entitlement_orders.id"), index=True, nullable=False
    )
    renewal_order_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_key_entitlement_orders.id"), index=True, nullable=True
    )
    tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    product_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    subscription_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="created", nullable=False, index=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ModelKeyCredentialRef(Base, TimestampMixin):
    __tablename__ = "model_key_credential_refs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mkc"))
    entitlement_id: Mapped[str] = mapped_column(
        ForeignKey("model_key_entitlements.id"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    model_mask_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    secret_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    secret_backend: Mapped[str] = mapped_column(String(40), default="env", nullable=False)
    owner_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    sharing_scope: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False, index=True)
    last_health_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ModelKeyAllocation(Base, TimestampMixin):
    __tablename__ = "model_key_allocations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mka"))
    entitlement_id: Mapped[str] = mapped_column(
        ForeignKey("model_key_entitlements.id"), index=True, nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    product_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    adapter_id: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    department_id: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    environment: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    quota_share_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    quota_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False, index=True)


class ModelUsageAttribution(Base):
    __tablename__ = "model_usage_attributions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mua"))
    usage_event_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    owner_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    product_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    adapter_id: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    caller_user_id: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    entitlement_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    credential_ref_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    provider: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    model: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class StudioWorkflowDraft(Base, TimestampMixin):
    __tablename__ = "studio_workflow_drafts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("swd"))
    tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    resource_scope: Mapped[str] = mapped_column(String(40), default="personal", nullable=False)
    source_app: Mapped[str] = mapped_column(String(80), default="studio", nullable=False, index=True)
    workflow_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    draft_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    agentctl_tenant_id: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    agentctl_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    connection_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    workflow_graph_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    agentctl_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    request_payload_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    studio_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class StudioProfileRequest(Base, TimestampMixin):
    __tablename__ = "studio_profile_requests"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("spr"))
    tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    requested_by: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    source_app: Mapped[str] = mapped_column(String(80), default="studio", nullable=False, index=True)
    operation_type: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_payload_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cooling_off_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audit_event_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)


class StudioProfileRequestJob(Base, TimestampMixin):
    __tablename__ = "studio_profile_request_jobs"
    __table_args__ = (UniqueConstraint("profile_request_id", name="uq_studio_profile_request_job"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("spj"))
    tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    profile_request_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    operation_type: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    run_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    audit_event_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)


class StudioProfileDeviceSession(Base, TimestampMixin):
    __tablename__ = "studio_profile_device_sessions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "device_id", name="uq_studio_profile_device_session"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("spd"))
    tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    device_id: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    device_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    location: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False, index=True)
    current: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)


class StudioProfileExportArtifact(Base, TimestampMixin):
    __tablename__ = "studio_profile_export_artifacts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("spe"))
    tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    profile_request_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    job_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    export_format: Mapped[str] = mapped_column(String(24), default="json", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ready", nullable=False, index=True)
    include_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    manifest_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)


class ToolCatalogEntry(Base, TimestampMixin):
    __tablename__ = "tool_catalog_entries"
    __table_args__ = (UniqueConstraint("toolkit_id", "version", name="uq_tool_catalog_toolkit_version"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("tke"))
    toolkit_id: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    version: Mapped[str] = mapped_column(String(40), default="1.0.0", nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    capabilities_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    input_schema_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    output_schema_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    runtime_adapter: Mapped[str | None] = mapped_column(String(120), nullable=True)
    data_sensitivity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    quota_metrics_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    pricing_metrics_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    approval_policy_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    sandbox_policy_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    mcp_server_policy_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False, index=True)
    created_by: Mapped[str | None] = mapped_column(String(40), nullable=True)


class ToolkitArtifact(Base, TimestampMixin):
    __tablename__ = "toolkit_artifacts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("tka"))
    tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    toolkit_id: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    capability: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    artifact_type: Mapped[str] = mapped_column(String(80), default="artifact", nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(160), default="application/octet-stream", nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(80), nullable=True)
    data_class: Mapped[str] = mapped_column(String(32), default="D2", nullable=False)
    retention_policy: Mapped[str] = mapped_column(String(80), default="short_lived", nullable=False)
    access_policy_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    storage_kind: Mapped[str] = mapped_column(String(32), default="inline", nullable=False)
    content_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="ready", nullable=False, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class MCPToolGrant(Base, TimestampMixin):
    __tablename__ = "mcp_tool_grants"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mtg"))
    tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    toolkit_id: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    mcp_server_id: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    mcp_tool_name: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    resource_scope: Mapped[str] = mapped_column(String(160), default="personal", nullable=False)
    allowed_actions_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    allowed_resources_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    data_sensitivity_limit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    approval_policy_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    credential_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False, index=True)
    created_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentFlow(Base, TimestampMixin):
    __tablename__ = "agent_flows"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("afl"))
    tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_app: Mapped[str] = mapped_column(String(80), default="studio", nullable=False, index=True)
    source_draft_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    workflow_id: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    workflow_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    agent_dependencies_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    toolkit_dependencies_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    mcp_grant_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    mcp_grant_snapshot_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    knowledge_dependencies_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    model_policy_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    data_policy_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    visibility: Mapped[str] = mapped_column(String(32), default="private", nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), default="published", nullable=False, index=True)
    created_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentFlowShare(Base, TimestampMixin):
    __tablename__ = "agent_flow_shares"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("afs"))
    flow_id: Mapped[str] = mapped_column(ForeignKey("agent_flows.id"), index=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    share_mode: Mapped[str] = mapped_column(String(40), default="login_required", nullable=False, index=True)
    access_policy_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    quota_policy_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    billing_policy_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    input_data_policy_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    output_data_policy_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    trace_visibility_policy_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)


class AgentFlowShareRun(Base, TimestampMixin):
    __tablename__ = "agent_flow_share_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("afr"))
    share_id: Mapped[str] = mapped_column(ForeignKey("agent_flow_shares.id"), index=True, nullable=False)
    flow_id: Mapped[str] = mapped_column(ForeignKey("agent_flows.id"), index=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    creator_user_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    caller_tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    caller_user_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    trace_id: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    workflow_run_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="accepted", nullable=False, index=True)
    execution_status: Mapped[str] = mapped_column(String(64), default="contract_ready", nullable=False)
    request_payload_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    response_payload_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    usage_summary_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("aud"))
    tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    app_id: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    ip: Mapped[str | None] = mapped_column(String(80), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("use"))
    tenant_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    app_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    metric_code: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    source_event_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
