"""
Geolvix GIS Ingestion Service — Entry point FastAPI
Responsável por receber arquivos GIS, simplificar geometrias e persistir no PostGIS.
Recurso alocado: 1.0 GB RAM | 0.5 vCPU (SDD seção 4)
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import engine, Base
from app.routers import gis

settings = get_settings()


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
