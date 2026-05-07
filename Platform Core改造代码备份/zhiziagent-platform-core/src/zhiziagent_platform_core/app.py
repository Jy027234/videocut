from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from . import __version__
from .database import build_engine, build_session_factory, init_database
from .openapi import install_openapi_extensions
from .routers import (
    access,
    apps,
    audit,
    auth,
    integrations,
    invitations,
    model_center,
    model_entitlements,
    parse_broker,
    payment_webhooks,
    platform,
    public_docs,
    service_accounts,
    studio,
    tenants,
    toolkit_artifacts,
    toolkits,
    usage,
)
from .seed import seed_defaults
from .settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _ = app
        if settings.auto_create_schema:
            init_database(engine)
        else:
            with session_factory() as db:
                seed_defaults(db)
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Identity, tenant, RBAC, module registry, service account, and audit base service.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.SessionLocal = session_factory

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz", tags=["System"])
    def healthz() -> dict:
        return {"status": "ok", "version": __version__, "env": settings.app_env}

    @app.get("/readyz", tags=["System"])
    def readyz() -> dict:
        with session_factory() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ready"}

    @app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
    def favicon() -> RedirectResponse:
        return RedirectResponse(url="/favicon.svg")

    @app.api_route("/studio-app", methods=["GET", "HEAD"], include_in_schema=False)
    def studio_app_redirect() -> RedirectResponse:
        return RedirectResponse(url="/studio-app/")

    @app.api_route(
        "/studio-app/{path:path}",
        methods=["GET", "HEAD"],
        include_in_schema=False,
    )
    async def studio_app_proxy(path: str, request: Request) -> Response:
        target_path = f"/{path}" if path else "/"
        target_url = httpx.URL(settings.studio_app_proxy_base_url.rstrip("/") + target_path)
        if request.url.query:
            target_url = target_url.copy_with(query=request.url.query.encode())

        forwarded_headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in {"host", "connection", "content-length", "transfer-encoding"}
        }
        try:
            async with httpx.AsyncClient(timeout=settings.studio_app_proxy_timeout_seconds) as client:
                upstream = await client.request(
                    request.method,
                    target_url,
                    headers=forwarded_headers,
                )
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=503,
                detail="ZhiziAgent Studio is not available from Platform Core.",
            ) from exc

        response_headers = {
            key: value
            for key, value in upstream.headers.items()
            if key.lower()
            not in {
                "connection",
                "content-encoding",
                "content-length",
                "transfer-encoding",
            }
        }
        return Response(
            content=b"" if request.method == "HEAD" else upstream.content,
            status_code=upstream.status_code,
            headers=response_headers,
            media_type=upstream.headers.get("content-type"),
        )

    app.include_router(auth.router)
    app.include_router(tenants.router)
    app.include_router(apps.router)
    app.include_router(access.router)
    app.include_router(platform.router)
    app.include_router(invitations.router)
    app.include_router(integrations.router)
    app.include_router(public_docs.router)
    app.include_router(model_center.router)
    app.include_router(model_entitlements.router)
    app.include_router(payment_webhooks.router)
    app.include_router(parse_broker.router)
    app.include_router(toolkits.router)
    app.include_router(toolkit_artifacts.router)
    app.include_router(studio.router)
    app.include_router(service_accounts.router)
    app.include_router(audit.router)
    app.include_router(usage.router)

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="platform-ui")

    install_openapi_extensions(app)

    return app


app = create_app()
