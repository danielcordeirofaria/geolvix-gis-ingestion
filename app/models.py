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

    # Geometria da fazenda completa em WGS84 (SRID 4326) apos simplificacao.
    # Usada na analise NDVI/desmatamento (cobre toda a propriedade).
    geometria = Column(Geometry(geometry_type="POLYGON", srid=4326), nullable=False)
    area_hectares = Column(Numeric(10, 2), nullable=True)

    # Geometria do talhao de producao — subconjunto da fazenda onde a commodity e cultivada.
    # Null ate o operador fazer upload via PATCH /poligono-producao ou copiar via /copiar-fazenda.
    # Usada no polygon_eudr.geojson do Pacote DDS (EUDR FAQ 1.7/1.15).
    # Adicionada pela migration 010_poligono_producao.sql.
    geometria_producao = Column(Geometry(geometry_type="POLYGON", srid=4326), nullable=True)
    area_producao_hectares = Column(Numeric(10, 2), nullable=True)

    # Ponto de localizacao para propriedades/talhoes < 4 ha (EUDR FAQ 1.7).
    # Alternativa ao poligono — o EUDR IS aceita lat/lon simples para areas pequenas.
    # Prioridade no DDS: geometria_producao (poligono) > ponto_producao (ponto).
    # ponto_producao_lat / _lon: duplicadas para leitura pelo Core/Hibernate sem tipo PostGIS.
    # Adicionadas pela migration 011_ponto_producao.sql.
    ponto_producao = Column(Geometry(geometry_type="POINT", srid=4326), nullable=True)
    ponto_producao_lat = Column(Numeric(9, 6), nullable=True)
    ponto_producao_lon = Column(Numeric(11, 6), nullable=True)

    # LGPD — opcionais, criptografados pelo Core Service antes de enviar
    produtor_nome_criptografado = Column(String(512), nullable=True)
    produtor_cpf_criptografado = Column(String(512), nullable=True)

    created_at = Column(TIMESTAMP, default=datetime.datetime.utcnow)
