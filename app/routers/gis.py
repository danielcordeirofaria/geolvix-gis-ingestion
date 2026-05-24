"""
Router principal do GIS Ingestion Service.

Endpoints:
  POST /api/v1/gis/upload        — Recebe arquivo GIS, parseia, simplifica e persiste
  GET  /api/v1/gis/{id}/geojson  — Retorna geometria da propriedade em GeoJSON
  GET  /api/v1/gis/health        — Health check sem autenticação (para Docker/Nginx)
"""
import os
import tempfile
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db, get_db_with_tenant
from app.schemas.gis import PropriedadeUploadResponse, PropriedadeGeoJSONResponse
from app.services import file_parser
from app.services.geometry_service import save_propriedade, get_propriedade_geojson
from app.utils.auth import verify_internal_token
from app.utils.security import (
    validate_file_extension,
    validate_file_size,
)

settings = get_settings()

router = APIRouter(prefix="/api/v1/gis", tags=["GIS"])


@router.get("/health", include_in_schema=True)
async def health_check():
    """Health check público — usado pelo Docker Compose e balanceador de carga."""
    return {"status": "ok", "service": settings.APP_NAME, "version": settings.APP_VERSION}


@router.post(
    "/upload",
    response_model=PropriedadeUploadResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_internal_token)],
    summary="Upload de polígono de propriedade rural",
    description=(
        "Recebe um arquivo .kml, .geojson ou .zip (Shapefile), "
        "valida tamanho (max 10 MB), parseia, simplifica vértices e persiste no PostGIS. "
        "Requer cabeçalho X-Internal-Token com o token compartilhado com o Core Service."
    ),
)
async def upload_propriedade(
    file: UploadFile = File(..., description="Arquivo .kml, .geojson ou .zip contendo Shapefile"),
    organizacao_id: int = Form(..., description="ID da organização (tenant) proprietária"),
    nome_propriedade: str = Form(..., min_length=2, max_length=255),
    codigo_car: Optional[str] = Form(None, max_length=100),
    # Campos LGPD opcionais — devem chegar já criptografados (AES-256) pelo Core Service
    produtor_nome_enc: Optional[str] = Form(None, max_length=512),
    produtor_cpf_enc: Optional[str] = Form(None, max_length=512),
):
    # 1. Valida extensão
    file_type = validate_file_extension(file.filename)

    # 2. Lê conteúdo e valida tamanho
    content = await file.read()
    validate_file_size(len(content))

    # 3. Parse da geometria de acordo com o tipo
    try:
        if file_type == "geojson":
            polygon = file_parser.parse_geojson(content)

        elif file_type == "kml":
            polygon = file_parser.parse_kml(content)

        elif file_type == "shp":
            # Shapefile exige gravação em disco para uso do fiona
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            try:
                polygon = file_parser.parse_shapefile_zip(tmp_path)
            finally:
                os.unlink(tmp_path)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Erro ao processar o arquivo geoespacial: {e}",
        )

    # Conta vértices antes da simplificação para retornar no response
    vertices_originais = len(polygon.exterior.coords)

    # 4. Persiste com RLS ativo para o tenant
    async for db in get_db_with_tenant(organizacao_id):
        propriedade = await save_propriedade(
            db=db,
            organizacao_id=organizacao_id,
            nome_propriedade=nome_propriedade,
            polygon=polygon,
            codigo_car=codigo_car,
            produtor_nome_enc=produtor_nome_enc,
            produtor_cpf_enc=produtor_cpf_enc,
        )

    # Recupera vértices pós-simplificação via o objeto salvo
    from geoalchemy2.shape import to_shape
    simplified_geom = to_shape(propriedade.geometria)
    vertices_simplificados = len(simplified_geom.exterior.coords)

    return PropriedadeUploadResponse(
        id=propriedade.id,
        organizacao_id=propriedade.organizacao_id,
        nome_propriedade=propriedade.nome_propriedade,
        codigo_car=propriedade.codigo_car,
        area_hectares=float(propriedade.area_hectares),
        vertices_originais=vertices_originais,
        vertices_simplificados=vertices_simplificados,
        created_at=propriedade.created_at,
    )


@router.get(
    "/{propriedade_id}/geojson",
    response_model=PropriedadeGeoJSONResponse,
    dependencies=[Depends(verify_internal_token)],
    summary="Retorna geometria de uma propriedade em GeoJSON",
)
async def get_geojson(
    propriedade_id: int,
    organizacao_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Retorna a geometria armazenada no PostGIS como GeoJSON para renderização no mapa."""
    async for db in get_db_with_tenant(organizacao_id):
        result = await get_propriedade_geojson(db, propriedade_id)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Propriedade {propriedade_id} não encontrada para esta organização.",
        )

    return PropriedadeGeoJSONResponse(
        id=propriedade_id,
        geojson=result["geojson"],
        area_hectares=result["area_hectares"],
    )
