"""
Router principal do GIS Ingestion Service.

Endpoints:
  POST /api/v1/gis/upload        — Recebe arquivo GIS, parseia, simplifica e persiste
  GET  /api/v1/gis/{id}/geojson  — Retorna geometria da propriedade em GeoJSON
  GET  /api/v1/gis/health        — Health check sem autenticacao (Docker/Nginx)
"""
import os
import tempfile
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db_with_tenant
from app.schemas.gis import PropriedadeUploadResponse, PropriedadeGeoJSONResponse
from app.services import file_parser
from app.services.geometry_service import save_propriedade, get_propriedade_geojson
from app.utils.auth import verify_internal_token
from app.utils.security import validate_file_extension, validate_file_size

settings = get_settings()

router = APIRouter(prefix="/api/v1/gis", tags=["GIS"])


@router.get("/health")
async def health_check():
    """Health check publico — Docker Compose e balanceador de carga."""
    return {"status": "ok", "service": settings.APP_NAME, "version": settings.APP_VERSION}


@router.post(
    "/upload",
    response_model=PropriedadeUploadResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_internal_token)],
    summary="Upload de poligono de propriedade rural",
)
async def upload_propriedade(
    file: UploadFile = File(...),
    organizacao_id: uuid.UUID = Form(..., description="UUID da organizacao proprietaria"),
    nome_propriedade: str = Form(..., min_length=2, max_length=255),
    codigo_car: Optional[str] = Form(None, max_length=100),
    produtor_nome_enc: Optional[str] = Form(None, max_length=512),
    produtor_cpf_enc: Optional[str] = Form(None, max_length=512),
):
    # 1. Valida extensao
    file_type = validate_file_extension(file.filename)

    # 2. Le conteudo e valida tamanho (10 MB)
    content = await file.read()
    validate_file_size(len(content))

    # 3. Parse da geometria
    try:
        if file_type == "geojson":
            polygon = file_parser.parse_geojson(content)
        elif file_type == "kml":
            polygon = file_parser.parse_kml(content)
        elif file_type == "shp":
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

    vertices_originais = len(polygon.exterior.coords)
    org_id_str = str(organizacao_id)

    # 4. Persiste com RLS ativo
    propriedade = None
    async for db in get_db_with_tenant(org_id_str):
        propriedade = await save_propriedade(
            db=db,
            organizacao_id=organizacao_id,
            nome_propriedade=nome_propriedade,
            polygon=polygon,
            codigo_car=codigo_car,
            produtor_nome_enc=produtor_nome_enc,
            produtor_cpf_enc=produtor_cpf_enc,
        )

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
)
async def get_geojson(
    propriedade_id: uuid.UUID,
    organizacao_id: uuid.UUID,
):
    result = None
    async for db in get_db_with_tenant(str(organizacao_id)):
        result = await get_propriedade_geojson(db, propriedade_id)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Propriedade {propriedade_id} nao encontrada para esta organizacao.",
        )

    return PropriedadeGeoJSONResponse(
        id=propriedade_id,
        geojson=result["geojson"],
        area_hectares=result["area_hectares"],
    )
