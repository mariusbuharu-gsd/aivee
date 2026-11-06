"""AiVee HTTP API: `uvicorn aivee_api.main:app`.

`create_app(services)` takes fully wired services (tests pass fakes); without them the
lifespan builds the real ones from env: Postgres, the MQTT link to the edge, the Claude
translator and the enrolment models.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aivee_api.alerts.router import router as alerts_router
from aivee_api.accounts.invites import router as invites_router
from aivee_api.audit.router import router as audit_router
from aivee_api.auth.router import router as auth_router
from aivee_api.cameras.router import router as cameras_router
from aivee_api.db.session import make_engine, make_session_factory
from aivee_api.deps import Services
from aivee_api.devices.router import router as devices_router
from aivee_api.edge.live import LiveDetections
from aivee_api.edge.publisher import MqttEdgeLink, RecordingPublisher
from aivee_api.edge.sync import EdgeCommands, EdgeSync, LoggingEdgeCommands, MqttEdgeCommands
from aivee_api.errors import install_handlers
from aivee_api.events.router import router as events_router
from aivee_api.locations.router import router as locations_router
from aivee_api.metrics.cache import MetricsCache
from aivee_api.metrics.router import router as metrics_router
from aivee_api.push.router import router as push_router
from aivee_api.rules.router import router as rules_router
from aivee_api.rules.translator import ClaudeRuleTranslator
from aivee_api.settings import ApiSettings
from aivee_api.staff.adapters import build_enroller
from aivee_api.staff.router import router as staff_router
from aivee_api.zones.router import router as zones_router

log = logging.getLogger(__name__)


@asynccontextmanager
async def _real_services(settings: ApiSettings) -> AsyncIterator[Services]:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    engine = make_engine()
    sessions = make_session_factory(engine)
    metrics = MetricsCache()
    live = LiveDetections()
    task: asyncio.Task[None] | None = None
    commands: EdgeCommands
    if settings.mqtt_enabled:
        link = MqttEdgeLink(settings, metrics, live=live)
        sync = EdgeSync(sessions, link, settings.site, settings.device)
        link.on_connect = sync.publish_all  # the broker gets the full state on every connect
        commands = MqttEdgeCommands(link, settings.site, settings.device)
        task = asyncio.create_task(link.run())
    else:
        sync = EdgeSync(sessions, RecordingPublisher(), settings.site, settings.device)
        commands = LoggingEdgeCommands()
    settings.snapshot_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield Services(
            settings=settings,
            sessions=sessions,
            sync=sync,
            translator=ClaudeRuleTranslator(model=settings.claude_model),
            commands=commands,
            enroller=build_enroller(settings.yolo_weights),
            metrics=metrics,
            live=live,
        )
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await engine.dispose()


def create_app(services: Services | None = None) -> FastAPI:
    settings = services.settings if services else ApiSettings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if services is not None:
            app.state.services = services
            yield
            return
        async with _real_services(settings) as real:
            app.state.services = real
            yield

    app = FastAPI(title="AiVee API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_handlers(app)
    for router in (
        auth_router,
        locations_router,
        invites_router,
        audit_router,
        cameras_router,
        zones_router,
        rules_router,
        events_router,
        devices_router,
        staff_router,
        metrics_router,
        push_router,
        alerts_router,
    ):
        app.include_router(router)

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    if services is not None:
        app.state.services = services  # usable without running the lifespan (unit tests)
    return app


app = create_app()
