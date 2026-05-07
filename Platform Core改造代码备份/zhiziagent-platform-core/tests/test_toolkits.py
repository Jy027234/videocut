from __future__ import annotations

from fastapi.testclient import TestClient

from zhiziagent_platform_core.app import create_app
from zhiziagent_platform_core.models import StudioWorkflowDraft
from zhiziagent_platform_core.settings import Settings


def _client(tmp_path, **overrides) -> TestClient:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'toolkits.db'}",
        jwt_secret="test-secret",
        app_env="test",
        agentctl_admin_token="test-agentctl-admin",
        bootstrap_admin_token="test-bootstrap-admin",
        **overrides,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str, tenant_name: str = "Toolkit Tenant") -> dict:
    resp = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "password-123",
            "display_name": email.split("@")[0],
            "tenant_name": tenant_name,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _headers(token_payload: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_payload['access_token']}"}


def _create_local_workflow(client: TestClient, token_payload: dict, workflow_id: str) -> None:
    session_factory = client.app.state.SessionLocal
    with session_factory() as db:
        db.add(
            StudioWorkflowDraft(
                tenant_id=token_payload["tenant_id"],
                user_id=token_payload["user_id"],
                owner_user_id=token_payload["user_id"],
                resource_scope="personal",
                source_app="studio",
                workflow_id=workflow_id,
                draft_id=f"draft_{workflow_id}",
                status="published",
                title="Shareable workflow",
                description="Workflow prepared for Agent Flow sharing.",
                workflow_graph_json={
                    "toolkit_dependencies": [
                        {
                            "toolkit_id": "document.parse",
                            "version": "1.0.0",
                            "capability": "document.parse.submit",
                        }
                    ]
                },
            )
        )
        db.commit()


def test_toolkit_catalog_and_mcp_grants_are_tenant_scoped(tmp_path):
    with _client(tmp_path) as client:
        owner = _register(client, "toolkit-owner@example.com")
        headers = _headers(owner)

        catalog = client.get("/toolkits", headers=headers)
        assert catalog.status_code == 200, catalog.text
        toolkit_ids = {item["toolkit_id"] for item in catalog.json()}
        assert {"document.parse", "mcp.github", "video-editing-toolkit"}.issubset(toolkit_ids)
        assert "video.basic" not in toolkit_ids
        document_toolkit = next(item for item in catalog.json() if item["toolkit_id"] == "document.parse")
        assert document_toolkit["runtime_adapter"] == "toolkit.document.jxzt"
        assert document_toolkit["manifest"]["package"] == "智能解析中台"
        assert "document.parse.extract_tables" in document_toolkit["capabilities"]
        video_toolkit = next(item for item in catalog.json() if item["toolkit_id"] == "video-editing-toolkit")
        assert video_toolkit["runtime_adapter"] == "toolkit.video_editing.external_worker"
        assert "video.render.render_final" in video_toolkit["capabilities"]
        assert video_toolkit["manifest"]["runtime"]["adapter"] == "toolkit.video_editing.external_worker"

        mcp_tools = client.get("/mcp-tools", headers=headers)
        assert mcp_tools.status_code == 200, mcp_tools.text
        assert {item["toolkit_id"] for item in mcp_tools.json()} >= {"mcp.github", "mcp.filesystem"}

        grant = client.post(
            "/mcp-tool-grants",
            headers=headers,
            json={
                "toolkit_id": "mcp.github",
                "mcp_server_id": "github-main",
                "mcp_tool_name": "issues.create",
                "resource_scope": "repo:Jy027234/example",
                "allowed_actions": ["read", "write"],
                "allowed_resources": ["repo:Jy027234/example", "issue:*"],
                "credential_ref": "vault://mcp/github-main",
            },
        )
        assert grant.status_code == 201, grant.text
        grant_body = grant.json()
        assert grant_body["tenant_id"] == owner["tenant_id"]
        assert grant_body["owner_type"] == "personal_user"
        assert grant_body["owner_id"] == owner["user_id"]
        assert grant_body["allowed_actions"] == ["read", "write"]
        assert grant_body["credential_configured"] is True
        assert grant_body["credential_ref"] is None

        other = _register(client, "toolkit-other@example.com", "Other Toolkit Tenant")
        other_list = client.get("/mcp-tool-grants", headers=_headers(other))
        assert other_list.status_code == 200, other_list.text
        assert other_list.json() == []


def test_agent_flow_share_keeps_creator_mcp_context_for_external_caller(tmp_path):
    with _client(tmp_path) as client:
        creator = _register(client, "flow-creator@example.com")
        creator_headers = _headers(creator)
        _create_local_workflow(client, creator, "wf_shareable")

        grant = client.post(
            "/mcp-tool-grants",
            headers=creator_headers,
            json={
                "toolkit_id": "mcp.github",
                "mcp_server_id": "github-main",
                "mcp_tool_name": "pull_request.comment",
                "resource_scope": "repo:Jy027234/example",
                "allowed_actions": ["read"],
                "allowed_resources": ["repo:Jy027234/example", "pull_request:*"],
            },
        )
        assert grant.status_code == 201, grant.text
        grant_id = grant.json()["grant_id"]

        flow = client.post(
            "/studio/flows/wf_shareable/publish",
            headers=creator_headers,
            json={
                "title": "Shared document parse flow",
                "visibility": "login_required",
                "toolkit_dependencies": [
                    {
                        "toolkit_id": "document.parse",
                        "version": "1.0.0",
                        "capability": "document.parse.submit",
                    }
                ],
                "mcp_grant_ids": [grant_id],
                "model_policy": {"allowed_models": ["deepseek:*"]},
                "data_policy": {"external_input": "caller_owned"},
            },
        )
        assert flow.status_code == 201, flow.text
        flow_id = flow.json()["flow_id"]

        share = client.post(
            f"/agent-flows/{flow_id}/shares",
            headers=creator_headers,
            json={
                "share_mode": "login_required",
                "quota_policy": {"daily_runs": 20},
                "billing_policy": {"payer": "caller"},
            },
        )
        assert share.status_code == 201, share.text
        share_id = share.json()["share_id"]

        public_share = client.get(f"/agent-flow-shares/{share_id}")
        assert public_share.status_code == 200, public_share.text
        assert public_share.json()["flow"]["owner_id"] == creator["user_id"]

        caller = _register(client, "flow-caller@example.com", "Caller Tenant")
        run = client.post(
            f"/agent-flow-shares/{share_id}/run",
            headers=_headers(caller),
            json={"input": {"prompt": "解析这份合同"}, "trace_id": "trace-share-run"},
        )
        assert run.status_code == 200, run.text
        run_body = run.json()
        assert run_body["execution_status"] == "contract_ready"
        assert run_body["share_context"]["creator_user_id"] == creator["user_id"]
        assert run_body["share_context"]["caller_user_id"] == caller["user_id"]
        assert run_body["product_context"]["billing_scope"] == "share_flow"
        assert run_body["tool_context"]["toolkit_dependencies"][0]["toolkit_id"] == "document.parse"
        assert run_body["mcp_context"]["grant_ids"] == [grant_id]
        assert run_body["mcp_context"]["grant_snapshot"][0]["credential_configured"] is False
        assert run_body["mcp_context"]["tools"][0]["mcp_tool_name"] == "pull_request.comment"
        assert run_body["platform_tool_context"]["platform_context_signature"].startswith("hmac-sha256=")
        assert run_body["platform_tool_context"]["mcp_grant_snapshot"][0]["grant_id"] == grant_id

        verify = client.post(
            "/platform-tool-context/verify",
            headers=creator_headers,
            json={
                "platform_tool_context": run_body["platform_tool_context"],
                "required_toolkit_id": "document.parse",
                "required_version": "1.0.0",
                "required_capability": "document.parse.submit",
                "mcp_server_id": "github-main",
                "mcp_tool_name": "pull_request.comment",
                "action": "read",
                "resource": "repo:Jy027234/example",
            },
        )
        assert verify.status_code == 200, verify.text
        assert verify.json()["valid"] is True

        denied = client.post(
            "/platform-tool-context/verify",
            headers=creator_headers,
            json={
                "platform_tool_context": run_body["platform_tool_context"],
                "mcp_server_id": "github-main",
                "mcp_tool_name": "pull_request.comment",
                "action": "write",
            },
        )
        assert denied.status_code == 200, denied.text
        assert denied.json()["valid"] is False
        assert denied.json()["reason"] == "mcp_action_not_allowed"
        assert run_body["run_id"].startswith("afr_")

        revoked = client.post(
            f"/agent-flow-shares/{share_id}/revoke",
            headers=creator_headers,
            json={"reason": "end of pilot"},
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["status"] == "revoked"
        rerun = client.post(
            f"/agent-flow-shares/{share_id}/run",
            headers=_headers(caller),
            json={"input": {"prompt": "再跑一次"}},
        )
        assert rerun.status_code == 404
