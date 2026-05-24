"""
Mapeamento ORM das tabelas do PostGIS relevantes para o GIS Ingestion Service.
Espelha o DDL definido no SDD (seção 3.2) — fonte de verdade é o Core Service/Flyway.
"""
from sqlalchemy import BigInteger, Boolean, Column, ForeignKey, Numeric, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB
from geoalchemy2 import Geometry
from app.database import Base
import datetime


class PropriedadeRural(Base):
    __tablename__ = "propriedades_rurais"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    organizacao_id = Column(BigInteger, ForeignKey("organizacoes.id", ondelete="CASCADE"), nullable=False)
    nome_propriedade = Column(String(255), nullable=False)
    codigo_car = Column(String(100), unique=True, nullable=True)

    # Geometria armazenada em WGS84 (SRID 4326) após simplificação
    geometria = Column(Geometry(geometry_type="POLYGON", srid=4326), nullable=False)
    area_hectares = Column(Numeric(10, 2), nullable=True)

    # LGPD — dados opcionais de produtores, criptografados na camada de serviço
    produtor_nome_criptografado = Column(String(512), nullable=True)
    produtor_cpf_criptografado = Column(String(512), nullable=True)

    created_at = Column(TIMESTAMP, default=datetime.datetime.utcnow)
