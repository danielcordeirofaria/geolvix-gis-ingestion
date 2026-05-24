"""
Parser de arquivos GIS: KML, GeoJSON e Shapefile (.zip).

Segurança:
- KML: desabilita entidades externas (XXE) via lxml com resolve_entities=False e no_network=True
- SHP: extrai apenas arquivos validados pela funcao validate_zip_contents
- GeoJSON: parse via json stdlib antes de passar ao Shapely
"""
import json
import os
import tempfile
import zipfile
from pathlib import Path

import fiona
from lxml import etree
from shapely.geometry import shape, Polygon, MultiPolygon
from shapely.ops import unary_union

from app.utils.security import validate_zip_contents


def _normalize_to_polygon(geom) -> Polygon:
    """
    Converte qualquer geometria retornada pelo parser em um unico Polygon.
    MultiPolygon e unido via dissolve (unary_union).
    """
    if isinstance(geom, Polygon):
        return geom
    if isinstance(geom, MultiPolygon):
        dissolved = unary_union(geom)
        if not isinstance(dissolved, Polygon):
            raise ValueError("A geometria multi-poligono nao pode ser dissolvida em um unico poligono.")
        return dissolved
    raise ValueError(f"Tipo de geometria nao suportado: {type(geom).__name__}. Use Polygon ou MultiPolygon.")


def parse_geojson(content: bytes) -> Polygon:
    """Faz o parse de um arquivo GeoJSON e retorna o primeiro Polygon encontrado."""
    try:
        data = json.loads(content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"GeoJSON invalido: {e}")

    if data.get("type") == "FeatureCollection":
        features = data.get("features", [])
        if not features:
            raise ValueError("FeatureCollection vazia - nenhuma geometria encontrada.")
        geom_data = features[0]["geometry"]
    elif data.get("type") == "Feature":
        geom_data = data["geometry"]
    else:
        geom_data = data

    geom = shape(geom_data)
    return _normalize_to_polygon(geom)


def parse_kml(content: bytes) -> Polygon:
    """
    Faz o parse de um arquivo KML com protecao contra ataques XXE.
    Utiliza lxml com resolve_entities=False e no_network=True.
    """
    try:
        parser = etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            load_dtd=False,
        )
        root = etree.fromstring(content, parser=parser)
    except etree.XMLSyntaxError as e:
        raise ValueError(f"KML com sintaxe invalida: {e}")

    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    coords_elements = root.findall(".//kml:coordinates", ns)

    if not coords_elements:
        coords_elements = root.findall(".//{*}coordinates")

    if not coords_elements:
        raise ValueError("Nenhuma tag <coordinates> encontrada no KML.")

    coords_text = max(coords_elements, key=lambda el: len(el.text or "")).text.strip()
    coords = []
    for token in coords_text.split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        lon, lat = float(parts[0]), float(parts[1])
        coords.append((lon, lat))

    if len(coords) < 4:
        raise ValueError("KML contem menos de 4 coordenadas - poligono invalido.")

    geom = Polygon(coords)
    return _normalize_to_polygon(geom)


def parse_shapefile_zip(zip_path: str) -> Polygon:
    """
    Extrai e faz o parse de um Shapefile contido em um .zip.
    Antes de extrair, valida o conteudo via validate_zip_contents (Zip Slip + Zip Bomb).
    """
    validate_zip_contents(zip_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmpdir)

        shp_files = list(Path(tmpdir).rglob("*.shp"))
        if not shp_files:
            raise ValueError("Nenhum arquivo .shp encontrado dentro do ZIP.")

        shp_path = str(shp_files[0])
        with fiona.open(shp_path, "r") as src:
            if len(src) == 0:
                raise ValueError("Shapefile vazio - nenhuma feicao encontrada.")
            first_feature = next(iter(src))
            geom = shape(first_feature["geometry"])

        return _normalize_to_polygon(geom)
