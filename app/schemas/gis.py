from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class PropriedadeUploadResponse(BaseModel):
    """Resposta retornada após upload e processamento bem-sucedido de um polígono."""
    id: int
    organizacao_id: int
    nome_propriedade: str
    codigo_car: Optional[str] = None
    area_hectares: float
    vertices_originais: int
    vertices_simplificados: int
    created_at: datetime

    model_config = {"from_attributes": True}


class PropriedadeGeoJSONResponse(BaseModel):
    """Resposta com a geometria em GeoJSON para visualização no mapa."""
    id: int
    geojson: dict
    area_hectares: float


class ErrorResponse(BaseModel):
    detail: str
