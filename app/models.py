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
    """
    Fazenda completa. Geometria usada exclusivamente para análise NDVI/desmatamento.
    Os polígonos e pontos de produção foram migrados para TalhaoProducao (migration 012).
    """
    __tablename__ = "propriedades_rurais"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
                server_default=text("gen_random_uuid()"))
    # FK para organizacoes.id — constraint garantida pelo banco via migration SQL.
    organizacao_id = Column(UUID(as_uuid=True), nullable=False)
    nome_propriedade = Column(String(255), nullable=False)
    codigo_car = Column(String(100), unique=True, nullable=True)

    # Geometria da fazenda completa em WGS84 (SRID 4326) após simplificação.
    # Usada na análise NDVI/desmatamento — cobre toda a propriedade.
    geometria = Column(Geometry(geometry_type="POLYGON", srid=4326), nullable=False)
    area_hectares = Column(Numeric(10, 2), nullable=True)

    # LGPD — opcionais, criptografados pelo Core Service antes de enviar
    produtor_nome_criptografado = Column(String(512), nullable=True)
    produtor_cpf_criptografado = Column(String(512), nullable=True)

    created_at = Column(TIMESTAMP, default=datetime.datetime.utcnow)


class TalhaoProducao(Base):
    """
    Talhão de produção — subconjunto produtivo de uma fazenda para uma commodity específica.

    Uma fazenda pode ter N talhões (ex: Talhão Soja Norte + Talhão Café Sul),
    cada um com sua própria geometria de produção exportada no polygon_eudr.geojson da DDS.

    Ref: Decisão 21 (Junho/2026) — Modelo Multi-Talhão / Multi-Commodity.
    Ref: EUDR FAQ 1.7/1.15 — a DDS deve referenciar o talhão produtivo, não a fazenda.
    """
    __tablename__ = "talhoes_producao"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
                server_default=text("gen_random_uuid()"))
    # FK para propriedades_rurais.id — constraint garantida pelo banco via migration 012.
    propriedade_id = Column(UUID(as_uuid=True), nullable=False)

    nome = Column(String(255), nullable=False)
    commodity_type = Column(String(50), nullable=False)

    # Polígono do talhão de produção (>= 4 ha) — exportado no polygon_eudr.geojson.
    # Null até o operador fazer upload via POST /talhoes/{id}/upload.
    geometria = Column(Geometry(geometry_type="POLYGON", srid=4326), nullable=True)
    area_hectares = Column(Numeric(10, 2), nullable=True)

    # Ponto de localização para talhões < 4 ha (EUDR FAQ 1.7).
    # Prioridade no DDS: geometria (polígono) > ponto_producao.
    # ponto_producao_lat/_lon: duplicatas para leitura pelo Core/Hibernate sem tipo PostGIS.
    ponto_producao = Column(Geometry(geometry_type="POINT", srid=4326), nullable=True)
    ponto_producao_lat = Column(Numeric(9, 6), nullable=True)
    ponto_producao_lon = Column(Numeric(11, 6), nullable=True)

    created_at = Column(TIMESTAMP, default=datetime.datetime.utcnow)
