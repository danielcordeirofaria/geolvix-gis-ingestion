"""
Serviço de geometria: simplificação de vértices e persistência no PostGIS.

Fluxo (SDD seção 6, passo 2):
1. Recebe um Shapely Polygon já parseado
2. Aplica ST_Simplify via Shapely (Douglas-Peucker) com tolerância configurável
3. Calcula área em hectares
4. Converte para WKT e persiste no PostGIS via SQLAlchemy + GeoAlchemy2
"""
import math
from shapely.geometry import Polygon, Point, mapping
from shapely.ops import transform
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.shape import from_shape

from app.config import get_settings
from app.models import PropriedadeRural

settings = get_settings()


def simplify_geometry(polygon: Polygon) -> Polygon:
    """
    Simplifica o polígono usando o algoritmo Douglas-Peucker (equivalente ao ST_Simplify do PostGIS).
    Tolerância em graus decimais (padrão: ~1m na linha do Equador).
    preserve_topology=True evita que o polígono degenere em linha ou ponto.
    """
    simplified = polygon.simplify(
        tolerance=settings.GEOMETRY_SIMPLIFY_TOLERANCE,
        preserve_topology=True,
    )
    if simplified.is_empty:
        raise ValueError("A simplificação resultou em uma geometria vazia. Verifique o polígono enviado.")
    return simplified


def calculate_area_hectares(polygon: Polygon) -> float:
    """
    Calcula a área aproximada em hectares.
    Usa a fórmula da elipsoide WGS84 via projeção local (Mollweide equi-área).
    Para propriedades rurais brasileiras, a precisão é suficiente para exibição no painel.
    """
    import pyproj
    from shapely.ops import transform as shp_transform

    # Projeção de área equivalente (EPSG:6933 — Equal Earth)
    wgs84 = pyproj.CRS("EPSG:4326")
    equal_area = pyproj.CRS("EPSG:6933")
    project = pyproj.Transformer.from_crs(wgs84, equal_area, always_xy=True).transform

    projected = shp_transform(project, polygon)
    area_m2 = projected.area
    return round(area_m2 / 10_000, 2)  # m² → hectares


async def save_propriedade(
    db: AsyncSession,
    organizacao_id,  # uuid.UUID
    nome_propriedade: str,
    polygon: Polygon,
    codigo_car: str | None = None,
    produtor_nome_enc: str | None = None,
    produtor_cpf_enc: str | None = None,
) -> PropriedadeRural:
    """
    Persiste a propriedade rural no PostGIS após simplificação.
    O RLS já estará ativo na sessão (injetado pelo get_db_with_tenant).
    """
    simplified = simplify_geometry(polygon)
    area_ha = calculate_area_hectares(simplified)

    # Converte Shapely → GeoAlchemy2 WKBElement (SRID 4326)
    geom_wkb = from_shape(simplified, srid=4326)

    propriedade = PropriedadeRural(
        organizacao_id=organizacao_id,
        nome_propriedade=nome_propriedade,
        codigo_car=codigo_car or None,
        geometria=geom_wkb,
        area_hectares=area_ha,
        produtor_nome_criptografado=produtor_nome_enc,
        produtor_cpf_criptografado=produtor_cpf_enc,
    )

    db.add(propriedade)
    await db.commit()
    await db.refresh(propriedade)

    return propriedade


async def get_propriedade_geojson(db: AsyncSession, propriedade_id) -> dict:  # uuid.UUID
    """
    Retorna a geometria da fazenda completa em GeoJSON via ST_AsGeoJSON do PostGIS.
    Usada pelo Satellite Worker para análise NDVI e pelo DDS como polygon_farm.geojson.
    """
    result = await db.execute(
        text(
            "SELECT ST_AsGeoJSON(geometria)::json AS geojson, area_hectares "
            "FROM propriedades_rurais WHERE id = :id"
        ),
        {"id": propriedade_id},
    )
    row = result.fetchone()
    if not row:
        return None
    return {"geojson": row.geojson, "area_hectares": float(row.area_hectares)}


# ── Talhão de produção ────────────────────────────────────────────────────────

async def save_producao_polygon(
    db: AsyncSession,
    propriedade_id,  # uuid.UUID
    polygon: Polygon,
) -> dict:
    """
    Persiste o polígono do talhão de produção em geometria_producao.

    Aplica a mesma simplificação Douglas-Peucker da fazenda para manter consistência.
    Calcula e salva area_producao_hectares.

    Ref: EUDR FAQ 1.7/1.15 — o talhão representa apenas a área produtiva,
    não o perímetro total da fazenda.
    """
    simplified = simplify_geometry(polygon)
    area_ha = calculate_area_hectares(simplified)
    geom_wkb = from_shape(simplified, srid=4326)

    vertices_originais = len(polygon.exterior.coords)
    vertices_simplificados = len(simplified.exterior.coords)

    await db.execute(
        text(
            "UPDATE propriedades_rurais "
            "SET geometria_producao = ST_GeomFromWKB(:geom, 4326), "
            "    area_producao_hectares = :area "
            "WHERE id = :id"
        ),
        {"geom": geom_wkb.desc, "area": area_ha, "id": str(propriedade_id)},
    )
    await db.commit()

    return {
        "id": propriedade_id,
        "area_producao_hectares": area_ha,
        "vertices_originais": vertices_originais,
        "vertices_simplificados": vertices_simplificados,
    }


async def get_producao_geojson(db: AsyncSession, propriedade_id) -> dict | None:
    """
    Retorna o GeoJSON da localização de produção via ST_AsGeoJSON.

    Lógica de prioridade (EUDR FAQ 1.7/1.15):
      1. geometria_producao (polígono) — se existir, retorna com tipo="POLIGONO"
      2. ponto_producao (ponto)        — fallback para propriedades < 4 ha, tipo="PONTO"
      3. None — nenhuma localização de produção cadastrada

    Retorna dict com: geojson, tipo ("POLIGONO" ou "PONTO"), area_producao_hectares (None para ponto).
    Usado pelo DdsPackageService para gerar polygon_eudr.geojson.
    """
    # Prioridade 1: polígono de produção
    result = await db.execute(
        text(
            "SELECT ST_AsGeoJSON(geometria_producao)::json AS geojson, "
            "       area_producao_hectares "
            "FROM propriedades_rurais "
            "WHERE id = :id AND geometria_producao IS NOT NULL"
        ),
        {"id": str(propriedade_id)},
    )
    row = result.fetchone()
    if row:
        return {
            "geojson": row.geojson,
            "area_producao_hectares": float(row.area_producao_hectares),
            "tipo": "POLIGONO",
        }

    # Prioridade 2: ponto de produção (< 4 ha, EUDR FAQ 1.7)
    result = await db.execute(
        text(
            "SELECT ST_AsGeoJSON(ponto_producao)::json AS geojson, "
            "       ponto_producao_lat, ponto_producao_lon "
            "FROM propriedades_rurais "
            "WHERE id = :id AND ponto_producao IS NOT NULL"
        ),
        {"id": str(propriedade_id)},
    )
    row = result.fetchone()
    if row:
        return {
            "geojson": row.geojson,
            "area_producao_hectares": None,  # ponto não tem área calculável
            "tipo": "PONTO",
        }

    return None


async def save_ponto_producao(
    db: AsyncSession,
    propriedade_id,  # uuid.UUID
    latitude: float,
    longitude: float,
) -> dict | None:
    """
    Persiste o ponto de localização do talhão de produção (EUDR FAQ 1.7).

    Usado para propriedades/talhões com área < 4 ha, onde o EUDR IS aceita
    um único ponto lat/lon em vez de polígono completo.

    Salva:
      - ponto_producao: GEOMETRY(Point, 4326) no PostGIS para operações espaciais
      - ponto_producao_lat / ponto_producao_lon: colunas decimais para leitura pelo Core

    Idempotente — sobrescreve se ponto já existia.
    Retorna None se a propriedade não for encontrada.
    """
    result = await db.execute(
        text(
            "UPDATE propriedades_rurais "
            "SET ponto_producao     = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), "
            "    ponto_producao_lat = :lat, "
            "    ponto_producao_lon = :lon "
            "WHERE id = :id "
            "RETURNING id"
        ),
        {"lat": latitude, "lon": longitude, "id": str(propriedade_id)},
    )
    row = result.fetchone()
    if not row:
        return None
    await db.commit()
    return {
        "id": propriedade_id,
        "latitude": latitude,
        "longitude": longitude,
    }


async def copiar_fazenda_como_producao(db: AsyncSession, propriedade_id) -> dict | None:
    """
    Copia geometria (fazenda completa) para geometria_producao sem nenhum upload adicional.

    Caso de uso: quando a área produtiva é toda a fazenda — o operador não precisa
    de um shapefile separado do talhão. Resolve o Gap 1 de UX (SDD Seção 6.2).

    Retorna None se a propriedade não for encontrada.
    """
    result = await db.execute(
        text(
            "UPDATE propriedades_rurais "
            "SET geometria_producao = geometria, "
            "    area_producao_hectares = area_hectares "
            "WHERE id = :id "
            "RETURNING area_hectares"
        ),
        {"id": str(propriedade_id)},
    )
    row = result.fetchone()
    if not row:
        return None
    await db.commit()
    return {
        "id": propriedade_id,
        "area_producao_hectares": float(row.area_hectares),
    }


# ── Talhões de Produção (Decisão 21) ─────────────────────────────────────────

async def save_talhao_polygon(
    db: AsyncSession,
    talhao_id,  # uuid.UUID
    polygon: Polygon,
) -> dict:
    """
    Persiste o polígono do talhão de produção na tabela talhoes_producao.
    Aplica simplificação Douglas-Peucker e calcula area_hectares.
    """
    simplified = simplify_geometry(polygon)
    area_ha = calculate_area_hectares(simplified)
    geom_wkb = from_shape(simplified, srid=4326)

    vertices_originais = len(polygon.exterior.coords)
    vertices_simplificados = len(simplified.exterior.coords)

    await db.execute(
        text(
            "UPDATE talhoes_producao "
            "SET geometria     = ST_GeomFromWKB(:geom, 4326), "
            "    area_hectares = :area "
            "WHERE id = :id"
        ),
        {"geom": geom_wkb.desc, "area": area_ha, "id": str(talhao_id)},
    )
    await db.commit()

    return {
        "id": talhao_id,
        "area_hectares": area_ha,
        "vertices_originais": vertices_originais,
        "vertices_simplificados": vertices_simplificados,
    }


async def get_talhao_geojson(db: AsyncSession, talhao_id) -> dict | None:
    """
    Retorna o GeoJSON da localização do talhão via ST_AsGeoJSON.

    Prioridade (EUDR FAQ 1.7/1.15):
      1. geometria (polígono) → tipo="POLIGONO"
      2. ponto_producao (ponto) → tipo="PONTO" (talhões < 4 ha)
      3. None → localização não cadastrada
    """
    # Prioridade 1: polígono
    result = await db.execute(
        text(
            "SELECT ST_AsGeoJSON(geometria)::json AS geojson, area_hectares "
            "FROM talhoes_producao "
            "WHERE id = :id AND geometria IS NOT NULL AND deleted_at IS NULL"
        ),
        {"id": str(talhao_id)},
    )
    row = result.fetchone()
    if row:
        return {
            "geojson": row.geojson,
            "area_hectares": float(row.area_hectares),
            "tipo": "POLIGONO",
        }

    # Prioridade 2: ponto (< 4 ha)
    result = await db.execute(
        text(
            "SELECT ST_AsGeoJSON(ponto_producao)::json AS geojson, "
            "       ponto_producao_lat, ponto_producao_lon "
            "FROM talhoes_producao "
            "WHERE id = :id AND ponto_producao IS NOT NULL AND deleted_at IS NULL"
        ),
        {"id": str(talhao_id)},
    )
    row = result.fetchone()
    if row:
        return {
            "geojson": row.geojson,
            "area_hectares": None,
            "tipo": "PONTO",
        }

    return None


async def save_ponto_talhao(
    db: AsyncSession,
    talhao_id,  # uuid.UUID
    latitude: float,
    longitude: float,
) -> dict | None:
    """Persiste o ponto de localização do talhão (< 4 ha, EUDR FAQ 1.7)."""
    result = await db.execute(
        text(
            "UPDATE talhoes_producao "
            "SET ponto_producao     = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), "
            "    ponto_producao_lat = :lat, "
            "    ponto_producao_lon = :lon "
            "WHERE id = :id AND deleted_at IS NULL "
            "RETURNING id"
        ),
        {"lat": latitude, "lon": longitude, "id": str(talhao_id)},
    )
    row = result.fetchone()
    if not row:
        return None
    await db.commit()
    return {"id": talhao_id, "latitude": latitude, "longitude": longitude}


async def copiar_fazenda_para_talhao(
    db: AsyncSession,
    talhao_id,      # uuid.UUID
    propriedade_id, # uuid.UUID
) -> dict | None:
    """
    Copia a geometria da fazenda completa como polígono do talhão.
    Caso de uso: toda a fazenda é produtiva para essa commodity.
    """
    result = await db.execute(
        text(
            "UPDATE talhoes_producao t "
            "SET geometria     = pr.geometria, "
            "    area_hectares = pr.area_hectares "
            "FROM propriedades_rurais pr "
            "WHERE t.id = :talhao_id "
            "  AND t.propriedade_id = :propriedade_id "
            "  AND t.deleted_at IS NULL "
            "RETURNING t.id, pr.area_hectares"
        ),
        {"talhao_id": str(talhao_id), "propriedade_id": str(propriedade_id)},
    )
    row = result.fetchone()
    if not row:
        return None
    await db.commit()
    return {"id": talhao_id, "area_hectares": float(row.area_hectares)}
