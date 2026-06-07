from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid


class PropriedadeUploadResponse(BaseModel):
    id: uuid.UUID
    organizacao_id: uuid.UUID
    nome_propriedade: str
    codigo_car: Optional[str] = None
    area_hectares: float
    vertices_originais: int
    vertices_simplificados: int
    created_at: datetime

    model_config = {"from_attributes": True}


class PropriedadeGeoJSONResponse(BaseModel):
    id: uuid.UUID
    geojson: dict
    area_hectares: float


# ── Talhão de produção ────────────────────────────────────────────────────────

class ProducaoUploadResponse(BaseModel):
    """Resposta ao fazer upload do polígono do talhão de produção."""
    id: uuid.UUID
    area_producao_hectares: float
    vertices_originais: int
    vertices_simplificados: int


class ProducaoGeoJSONResponse(BaseModel):
    """
    GeoJSON do talhão de produção — usado no polygon_eudr.geojson do Pacote DDS.

    tipo: "POLIGONO" ou "PONTO" — indica se a geometria retornada é polígono ou ponto.
    area_producao_hectares: null quando tipo="PONTO" (ponto não tem área calculável).
    """
    id: uuid.UUID
    geojson: dict
    area_producao_hectares: Optional[float] = None
    tipo: str = "POLIGONO"  # "POLIGONO" ou "PONTO"


class PontoProducaoResponse(BaseModel):
    """Resposta ao informar o ponto de localização para propriedades < 4 ha (EUDR FAQ 1.7)."""
    id: uuid.UUID
    latitude: float
    longitude: float
    message: str


class CopiarFazendaResponse(BaseModel):
    """Resposta ao copiar a geometria da fazenda como talhão de produção."""
    id: uuid.UUID
    area_producao_hectares: float
    message: str


class ErrorResponse(BaseModel):
    detail: str
