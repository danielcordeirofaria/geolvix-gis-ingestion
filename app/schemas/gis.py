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


class ErrorResponse(BaseModel):
    detail: str
