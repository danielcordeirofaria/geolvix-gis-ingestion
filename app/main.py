"""
Geolvix GIS Ingestion Service — Entry point FastAPI
Responsável por receber arquivos GIS, simplificar geometrias e persistir no PostGIS.
Recurso alocado: 1.0 GB RAM | 0.5 vCPU (SDD seção 4)
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import engine, Base
from app.routers import gis
from app.middleware.request_id import RequestIdMiddleware, RequestIdFilter

settings = get_settings()

# Injeta request_id em todos os logs do serviço
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(request_id)s] [%(levelname)s] %(name)s — %(message)s",
)
logging.getLogger().addFilter(RequestIdFilter())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa e finaliza recursos da aplicação."""
    # No startup: nada a fazer — tabelas são gerenciadas pelo Core Service via Flyway
    yield
    # No shutdown: fecha o pool de conexões do banco
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Microsserviço de ingestão e processamento de arquivos GIS (.kml, .shp, .geojson). "
        "Realiza simplificação de vértices e armazenamento no banco espacial PostGIS. "
        "Uso interno — todas as rotas (exceto /health) exigem X-Internal-Token."
    ),
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

# Request ID — deve ser o primeiro middleware (roda por último no response)
app.add_middleware(RequestIdMiddleware)

# CORS — apenas origens internas do cluster são necessárias
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Routers
app.include_router(gis.router)
