"""
Mapeamento ORM das tabelas do PostGIS relevantes para o GIS Ingestion Service.
IDs sao UUID conforme o DDL definido em geolvix-infra/db/migration/001_initial_schema.sql.
"""
import uuid
import datetime

from sqlalchemy import Column, Numeric, String, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geometry
from app.database import Base


class PropriedadeRural(Base):
    __tablename__ = "propriedades_rurais"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
                server_default=text("gen_random_uuid()"))
    # FK para organizacoes.id — constraint garantida pelo banco via migration SQL.
    # Removida do ORM pois o gis-ingestion nao mapeia a tabela organizacoes.
    organizacao_id = Column(UUID(as_uuid=True), nullable=False)
    nome_propriedade = Column(String(255), nullable=False)
    codigo_car = Column(String(100), unique=True, nullable=True)

    # Geometria em WGS84 (SRID 4326) apos simplificacao
    geometria = Column(Geometry(geometry_type="POLYGON", srid=4326), nullable=False)
    area_hectares = Column(Numeric(10, 2), nullable=True)

    # LGPD — opcionais, criptografados pelo Core Service antes de enviar
    produtor_nome_criptografado = Column(String(512), nullable=True)
    produtor_cpf_criptografado = Column(String(512), nullable=True)

    created_at = Column(TIMESTAMP, default=datetime.datetime.utcnow)
