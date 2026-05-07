# ZhiziAgent Platform Core

`zhiziagent-platform-core` 是 ZhiziAgent 多产品基座服务的第一版，负责统一账号、组织/租户、成员角色、权限、产品模块开通、服务账号和审计日志。

它的定位是：

```text
身份认证入口
+ 租户 / 组织
+ RBAC 权限
+ 产品模块注册
+ 服务账号
+ 审计事件
```

它不接管 `AIProjectOPS`、`world-agent-engine`、`AI-Opportunity-Scanner` 的业务数据。业务产品继续保留自己的业务表，但必须信任 platform-core 签发的用户上下文，并按 `tenant_id` 做数据隔离。

## 当前能力

- `POST /auth/register`：注册用户并创建首个组织。
- `POST /auth/login`：登录并签发平台 JWT。
- `POST /auth/switch-tenant`：切换当前组织。
- `POST /auth/introspect`：业务产品校验当前 token 和权限。
- `GET /auth/me`：当前用户、组织、权限、已开通模块。
- `GET /platform/setup-status`：检查实例是否已初始化。
- `POST /platform/bootstrap`：首次部署时创建首个管理员和组织，只能执行一次。
- `GET /platform/config-check`：检查腾讯云部署前的关键配置。
- `GET /platform/migration-plan`：查看 Alembic 迁移策略和命令。
- `GET /tenants` / `POST /tenants`：组织列表和创建组织。
- `GET /tenants/{tenant_id}/members`：成员列表。
- `POST /tenants/{tenant_id}/members`：添加已注册用户为成员。
- `POST /tenants/{tenant_id}/invitations`：创建成员邀请链接。
- `POST /invitations/{token}/accept`：被邀请成员激活账号并加入组织。
- `GET /apps`：产品模块列表。
- `POST /apps/register`：注册或更新模块 manifest。
- `POST /tenants/{tenant_id}/apps/{app_id}/enable`：为组织开通模块。
- `POST /tenants/{tenant_id}/service-accounts`：签发产品服务账号。
- `POST /tenants/{tenant_id}/service-accounts/{service_account_id}/rotate`：轮换服务账号。
- `POST /tenants/{tenant_id}/service-accounts/{service_account_id}/revoke`：带原因吊销服务账号。
- `POST /integration-grants` / `GET /integration-grants/{grant_id}`：创建和查询一次性接入授权。
- `POST /integration-grants/{grant_id}/redeem`：兑换安装授权并自动创建集成连接。
- `GET /integration-connections` / `GET /integration-connections/{connection_id}`：查看集成连接。
- `POST /integration-connections/{connection_id}/agentctl-token`：用平台服务账号换取短期 agentctl token。
- `GET /integration-connections/{connection_id}/smoke` / `POST /integration-connections/{connection_id}/smoke`：查看或执行接入 smoke test。
- `GET /toolkits` / `GET /toolkits/{toolkit_id}`：读取平台工具包目录。
- `POST /platform-tool-context/verify`：验证运行时签名工具上下文。
- `POST /toolkit-artifacts` / `GET /toolkit-artifacts/{artifact_id}` / `GET /toolkit-artifacts/{artifact_id}/bytes`：登记工具包产物并按租户和服务账号授权读取 bytes。
- `POST /audit/events`：用户或产品服务账号写审计。
- `GET /tenants/{tenant_id}/audit-events`：查看审计事件。
- `POST /usage/events`：用户或产品服务账号写用量事件。
- `GET /tenants/{tenant_id}/usage-events`：查看原始用量事件。
- `GET /tenants/{tenant_id}/usage-summary`：按 metric 和 unit 汇总用量。
- `GET /access/roles` / `GET /access/permissions`：角色和权限矩阵。
- `GET /platform/summary`：当前组织平台汇总。
- `/`：本地管理台 UI。

默认已内置这些模块：

```text
aoc              AI Opportunity Scanner
aiprojectops     AIProjectOPS
wae              World Agent Engine
agentctl         Agent / Model Gateway / Ledger 底座
```

## 本地开发

```powershell
cd E:\IT\zhiziagent-platform-core
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m pytest
python -m uvicorn zhiziagent_platform_core.main:app --app-dir src --reload --port 8010
```

如果希望直接复用 Docker 镜像中的依赖跑测试：

```powershell
docker build --target test -t zhiziagent-platform-core:test .
docker run --rm zhiziagent-platform-core:test
```

本地默认使用 SQLite：

```text
sqlite:///./zhiziagent_platform_core.db
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8010/healthz
Invoke-RestMethod http://127.0.0.1:8010/readyz
```

迁移 smoke：

```powershell
python scripts/platform_core_migration_smoke.py --json
# 或安装后使用：
zhiziagent-platform-core-migration-smoke --json
```

API 文档：

```text
http://127.0.0.1:8010/docs
```

管理台：

```text
http://127.0.0.1:8010/
```

首次打开管理台时，如果数据库还没有用户，页面会自动进入“初始化管理员”模式。初始化完成后再使用“邀请激活”页面添加团队成员。

## 腾讯云部署

第一版推荐在腾讯云 CVM 上用 Docker Compose 部署：

```powershell
cd /opt/zhiziagent-platform-core
cp .env.example .env
# 修改 .env 里的 POSTGRES_PASSWORD 和 ZAP_JWT_SECRET
docker compose --env-file .env -f deploy/docker-compose.tencent.yml up -d --build
```

当前 runtime 容器启动时会先执行 `alembic upgrade head`，再启动 API 进程。

如需启用 `zhiziagent-studio` 个人订单自动续费调度，先为 Studio 签发带 `billing.write`
scope 的服务账号 token，写入 `ZAP_RENEWAL_SERVICE_TOKEN` 和 `ZAP_RENEWAL_TENANT_IDS`，再启用
compose profile：

```powershell
docker compose --env-file .env -f deploy/docker-compose.tencent.yml --profile scheduler up -d --build
```

也可以用宿主机 cron / 云定时任务每小时调用一次：

```powershell
zhiziagent-appstudio-renewals-run --base-url http://127.0.0.1:8000 --tenant-id tenant_001 --json
```

真实支付网关 webhook 入口：

```text
POST /payment-gateways/{provider}/events
```

当前实现 `stripe` 签名验签和归一化，配置示例：

```text
ZAP_PAYMENT_GATEWAY_WEBHOOK_SECRETS={"stripe":{"webhook_secret":"whsec_xxx"}}
```

如果宿主机 `8000` 端口已被其他服务占用，可临时覆盖：

```powershell
$env:PLATFORM_PORT="8001"
docker compose --env-file .env -f deploy/docker-compose.tencent.yml up -d --build
```

如需接真实 agentctl，可额外设置：

```powershell
$env:ZAP_AGENTCTL_BASE_URL="http://host.docker.internal:8080"
$env:ZAP_AGENTCTL_ADMIN_TOKEN="platform-core-agentctl-compat"
```

安全组建议：

```text
22    仅允许你的固定 IP
80    如使用 Nginx/Caddy 反代
443   生产域名 HTTPS
8000  仅 staging 临时开放；正式环境建议不直接暴露
```

更详细的部署步骤见 [docs/tencent-cloud-deployment.md](docs/tencent-cloud-deployment.md)。

## 迁移管理

本地开发默认 `ZAP_AUTO_CREATE_SCHEMA=true`，方便快速迭代。进入腾讯云稳定测试后，建议改用 Alembic：

```bash
alembic revision --autogenerate -m "describe_change"
alembic upgrade head
```

迁移说明见 [docs/migrations.md](docs/migrations.md)。

## 业务产品接入原则

业务产品接入后，不应再从前端信任 `tenant_id`。推荐流程：

```text
前端登录 platform-core
-> 拿到平台 JWT
-> 调业务产品 API 时带 Authorization: Bearer <token>
-> 业务产品调用 /auth/introspect 或本地校验 JWT
-> 使用返回的 tenant_id / user_id / permissions 做业务鉴权
```

服务端产品写审计事件时，用服务账号。当前兼容两种写法，推荐统一使用 Bearer：

```powershell
Invoke-RestMethod http://127.0.0.1:8010/audit/events `
  -Method Post `
  -Headers @{ "Authorization" = "Bearer <zap_svc_token>" } `
  -ContentType "application/json" `
  -Body '{"app_id":"aiprojectops","action":"project.created","resource_type":"project","resource_id":"proj_001"}'
```

兼容旧接入方的 `X-Service-Token`：

```powershell
Invoke-RestMethod http://127.0.0.1:8010/audit/events `
  -Method Post `
  -Headers @{ "X-Service-Token" = "<zap_svc_token>" } `
  -ContentType "application/json" `
  -Body '{"app_id":"aiprojectops","action":"project.created","resource_type":"project","resource_id":"proj_001"}'
```

产品或 agentctl 写用量事件时，服务账号需要 `usage.write`，并且只能写入自己的 `app_id`：

```powershell
Invoke-RestMethod http://127.0.0.1:8010/usage/events `
  -Method Post `
  -Headers @{ "Authorization" = "Bearer <zap_svc_token>" } `
  -ContentType "application/json" `
  -Body '{"app_id":"agentctl","metric_code":"model.tokens.input","quantity":1200,"unit":"token","source_event_id":"trace_001:model_call_001"}'
```

如果某个产品已经自管用户、组织、业务权限和业务数据库，不必强制迁移到 platform-core 账号体系。可选择“产品自管模式”，只接 `agentctl` 的 Agent / Model / Runtime 控制面，必要时再把审计和 usage 汇总回 platform-core。详见 [docs/self-managed-product-mode.md](docs/self-managed-product-mode.md)。

## 下一步

第一版先刻意保持轻量。后续建议按顺序补：

```text
1. AIProjectOPS 产品侧 platform auth middleware
2. 邮箱/短信验证码或外部 OIDC 登录
3. 权限点管理 UI
4. 腾讯云 COS / CLS / 云监控接入
5. AOC / WAE 的产品侧 middleware
```

AIProjectOPS 的准备清单见 [docs/aiprojectops-integration-readiness.md](docs/aiprojectops-integration-readiness.md)。
