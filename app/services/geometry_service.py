"""
Serviço de geometria: simplificação de vértices e persistência no PostGIS.

Fluxo (SDD seção 6, passo 2):
1. Recebe um Shapely Polygon já parseado
2. Aplica ST_Simplify via Shapely (Douglas-Peucker) com tolerância configurável
3. Calcula área em hectares
4. Converte para WKT e persiste no PostGIS via SQLAlchemy + GeoAlchemy2
"""
import math
from shapely.geometry import Polygon, mapping
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
    organizacao_id: int,
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


async def get_propriedade_geojson(db: AsyncSession, propriedade_id: int) -> dict:
    """
    Retorna a geometria de uma propriedade no formato GeoJSON usando ST_AsGeoJSON do PostGIS.
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
