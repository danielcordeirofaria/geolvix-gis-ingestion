"""
Router principal do GIS Ingestion Service.

Endpoints — Fazenda completa:
  POST /api/v1/gis/upload                        — Upload do polígono da fazenda
  GET  /api/v1/gis/{id}/geojson                  — GeoJSON da fazenda (análise NDVI)

Endpoints — Talhão de produção (EUDR FAQ 1.7/1.15):
  POST /api/v1/gis/{id}/producao/upload          — Upload do polígono do talhão (>= 4 ha)
  GET  /api/v1/gis/{id}/producao/geojson         — GeoJSON do talhão (polygon_eudr.geojson)
  POST /api/v1/gis/{id}/producao/copiar-fazenda  — Copia fazenda como talhão (sem upload extra)
  POST /api/v1/gis/{id}/producao/ponto           — Informa ponto lat/lon (< 4 ha, FAQ 1.7)

  GET  /api/v1/gis/health                        — Health check (Docker/balanceador)
"""
import os
import tempfile
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db_with_tenant
from app.schemas.gis import (
    PropriedadeUploadResponse, PropriedadeGeoJSONResponse,
    ProducaoUploadResponse, ProducaoGeoJSONResponse, CopiarFazendaResponse,
    PontoProducaoResponse,
)
from app.services import file_parser
from app.services.geometry_service import (
    save_propriedade, get_propriedade_geojson,
    save_producao_polygon, get_producao_geojson, copiar_fazenda_como_producao,
    save_ponto_producao,
)
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
    summary="GeoJSON da fazenda completa (análise NDVI / polygon_farm.geojson)",
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


# ── Talhão de produção ────────────────────────────────────────────────────────

@router.post(
    "/{propriedade_id}/producao/upload",
    response_model=ProducaoUploadResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_internal_token)],
    summary="Upload do polígono do talhão de produção (polygon_eudr.geojson)",
)
async def upload_producao(
    propriedade_id: uuid.UUID,
    file: UploadFile = File(...),
    organizacao_id: uuid.UUID = Form(..., description="UUID da organizacao (validacao de tenant)"),
):
    """
    Persiste o polígono do talhão de produção na coluna geometria_producao.

    O talhão representa apenas a área onde a commodity é cultivada — não o perímetro
    total da fazenda. É o polígono que constará no polygon_eudr.geojson da DDS.

    Ref: EUDR FAQ 1.7/1.15.
    """
    file_type = validate_file_extension(file.filename)
    content = await file.read()
    validate_file_size(len(content))

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
            detail=f"Erro ao processar o arquivo geoespacial do talhão: {e}",
        )

    result = None
    async for db in get_db_with_tenant(str(organizacao_id)):
        # Verifica que a propriedade existe antes de salvar o talhão
        existing = await get_propriedade_geojson(db, propriedade_id)
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Propriedade {propriedade_id} nao encontrada para esta organizacao.",
            )
        result = await save_producao_polygon(db, propriedade_id, polygon)

    return ProducaoUploadResponse(
        id=result["id"],
        area_producao_hectares=result["area_producao_hectares"],
        vertices_originais=result["vertices_originais"],
        vertices_simplificados=result["vertices_simplificados"],
    )


@router.get(
    "/{propriedade_id}/producao/geojson",
    response_model=ProducaoGeoJSONResponse,
    dependencies=[Depends(verify_internal_token)],
    summary="GeoJSON do talhão de produção (polygon_eudr.geojson da DDS)",
)
async def get_producao_geojson_endpoint(
    propriedade_id: uuid.UUID,
    organizacao_id: uuid.UUID,
):
    """
    Retorna o GeoJSON do talhão de produção já armazenado.

    HTTP 404 se geometria_producao ainda não foi cadastrada (operador deve fazer
    upload via /producao/upload ou copiar via /producao/copiar-fazenda primeiro).
    """
    result = None
    async for db in get_db_with_tenant(str(organizacao_id)):
        result = await get_producao_geojson(db, propriedade_id)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Localização de produção não encontrada para a propriedade {propriedade_id}. "
                "Para fazendas >= 4 ha: faça upload via /producao/upload ou copie via /producao/copiar-fazenda. "
                "Para fazendas < 4 ha: informe as coordenadas via /producao/ponto (EUDR FAQ 1.7)."
            ),
        )

    return ProducaoGeoJSONResponse(
        id=propriedade_id,
        geojson=result["geojson"],
        area_producao_hectares=result.get("area_producao_hectares"),
        tipo=result.get("tipo", "POLIGONO"),
    )


@router.post(
    "/{propriedade_id}/producao/ponto",
    response_model=PontoProducaoResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_internal_token)],
    summary="Informa ponto lat/lon para talhão < 4 ha (EUDR FAQ 1.7)",
)
async def informar_ponto_producao(
    propriedade_id: uuid.UUID,
    organizacao_id: uuid.UUID = Form(..., description="UUID da organizacao (validacao de tenant)"),
    latitude: float = Form(..., description="Latitude WGS84 (-90 a 90)", ge=-90.0, le=90.0),
    longitude: float = Form(..., description="Longitude WGS84 (-180 a 180)", ge=-180.0, le=180.0),
):
    """
    Informa o ponto de geolocalização do talhão de produção para propriedades < 4 ha.

    Conforme EUDR FAQ 1.7, talhões com área inferior a 4 ha podem usar um único ponto
    lat/lon em vez de polígono completo. O ponto é armazenado como GEOMETRY(Point, 4326)
    no PostGIS e exportado como GeoJSON Point no polygon_eudr.geojson do Pacote DDS.

    Idempotente — sobrescreve se ponto já existia.
    Não interfere com geometria_producao (polígono) se existir — o polígono tem prioridade.
    """
    # Validação básica de domínio geográfico do Brasil
    if not (-34.0 <= latitude <= 6.0):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Latitude {latitude} está fora do domínio geográfico do Brasil (-34° a 6°).",
        )
    if not (-74.0 <= longitude <= -28.0):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Longitude {longitude} está fora do domínio geográfico do Brasil (-74° a -28°).",
        )

    result = None
    async for db in get_db_with_tenant(str(organizacao_id)):
        # Verifica que a propriedade existe antes de salvar
        existing = await get_propriedade_geojson(db, propriedade_id)
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Propriedade {propriedade_id} nao encontrada para esta organizacao.",
            )
        result = await save_ponto_producao(db, propriedade_id, latitude, longitude)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Propriedade {propriedade_id} nao encontrada.",
        )

    return PontoProducaoResponse(
        id=result["id"],
        latitude=result["latitude"],
        longitude=result["longitude"],
        message=(
            f"Ponto de produção salvo com sucesso: lat={latitude:.6f}, lon={longitude:.6f}. "
            "Para propriedades >= 4 ha, considere fazer upload do polígono completo."
        ),
    )


@router.post(
    "/{propriedade_id}/producao/copiar-fazenda",
    response_model=CopiarFazendaResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_internal_token)],
    summary="Copia a fazenda completa como talhão de produção (sem upload extra)",
)
async def copiar_fazenda_endpoint(
    propriedade_id: uuid.UUID,
    organizacao_id: uuid.UUID = Form(..., description="UUID da organizacao"),
):
    """
    Copia geometria → geometria_producao sem nenhum upload adicional.

    Caso de uso: quando a área produtiva é toda a fazenda — o operador não tem
    um shapefile separado do talhão. Resolve o caso mais comum sem fricção extra.

    Idempotente: pode ser chamado múltiplas vezes; sobrescreve geometria_producao.
    """
    result = None
    async for db in get_db_with_tenant(str(organizacao_id)):
        result = await copiar_fazenda_como_producao(db, propriedade_id)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Propriedade {propriedade_id} nao encontrada para esta organizacao.",
        )

    return CopiarFazendaResponse(
        id=result["id"],
        area_producao_hectares=result["area_producao_hectares"],
        message="Geometria da fazenda copiada como talhão de produção com sucesso.",
    )
