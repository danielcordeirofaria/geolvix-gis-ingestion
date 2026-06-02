"""
Testes unitários para app/services/geometry_service.py

Testamos apenas as funções puras simplify_geometry e calculate_area_hectares,
sem banco de dados. Todos os polígonos são construídos com coordenadas geográficas
reais (EPSG:4326) para que a reprojeção para EPSG:6933 funcione corretamente.
"""
import math
import pytest
from shapely.geometry import Polygon

from app.services.geometry_service import simplify_geometry, calculate_area_hectares


# ---------------------------------------------------------------------------
# Fixtures auxiliares
# ---------------------------------------------------------------------------

def poligono_quadrado_simples() -> Polygon:
    """Quadrado pequeno centrado em (-47, -15) — região de Brasília."""
    return Polygon([
        (-47.001, -15.001),
        (-47.001, -14.999),
        (-46.999, -14.999),
        (-46.999, -15.001),
        (-47.001, -15.001),
    ])


def poligono_complexo_muitos_vertices() -> Polygon:
    """
    Polígono circular aproximado com 360 vértices.
    Simula um arquivo GIS importado com resolução alta antes da simplificação.
    """
    import math
    cx, cy, r = -47.0, -15.0, 0.05  # raio em graus (~5 km)
    coords = [
        (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
        for a in range(360)
    ]
    coords.append(coords[0])  # fechar anel
    return Polygon(coords)


def poligono_um_km2() -> Polygon:
    """
    Quadrado de aproximadamente 1 km² centrado em (-47, -15).
    1 grau de latitude ≈ 111 km → 0.009009 graus ≈ 1 km.
    """
    delta = 0.004504  # metade de ~1 km em graus
    return Polygon([
        (-47.0 - delta, -15.0 - delta),
        (-47.0 - delta, -15.0 + delta),
        (-47.0 + delta, -15.0 + delta),
        (-47.0 + delta, -15.0 - delta),
        (-47.0 - delta, -15.0 - delta),
    ])


def triangulo_conhecido() -> Polygon:
    """
    Triângulo retângulo com catetos de ~1 grau × ~1 grau centrado em (-47, -15).
    A área em coordenadas planas seria 0.5 graus², mas após reprojeção para
    EPSG:6933 obteremos a área real em m².
    """
    return Polygon([
        (-47.0, -15.0),
        (-46.0, -15.0),
        (-47.0, -14.0),
        (-47.0, -15.0),
    ])


# ---------------------------------------------------------------------------
# Testes de simplify_geometry
# ---------------------------------------------------------------------------

def test_simplify_geometry_preserva_forma():
    """
    Um polígono simples com 5 vértices deve permanecer válido após simplificação.
    A tolerância padrão (0.00001 graus) não deve degenerar uma forma com lados
    de ~0.002 graus (~200 m), portanto o resultado deve ser um Polygon válido.
    """
    pol = poligono_quadrado_simples()
    resultado = simplify_geometry(pol)

    assert resultado.is_valid, "O polígono simplificado deve ser válido (is_valid=True)"
    assert not resultado.is_empty, "O polígono simplificado não deve ser vazio"
    assert resultado.geom_type == "Polygon", "O resultado deve continuar sendo um Polygon"


def test_simplify_geometry_nao_degenera():
    """
    Um polígono com 360 vértices (círculo aproximado) deve ser simplificado sem
    degenerar em linha ou ponto. preserve_topology=True garante isso.
    O número de vértices simplificados deve ser menor que o original, mas o
    tipo de geometria e a validade devem ser preservados.
    """
    pol = poligono_complexo_muitos_vertices()
    resultado = simplify_geometry(pol)

    # Não deve ser linha (LinearRing, LineString) nem ponto
    assert resultado.geom_type == "Polygon", (
        f"Esperado Polygon, obtido {resultado.geom_type} — geometria degenerou"
    )
    assert resultado.is_valid, "Polígono simplificado deve ser válido"

    vertices_originais = len(pol.exterior.coords)
    vertices_resultado = len(resultado.exterior.coords)
    assert vertices_resultado < vertices_originais, (
        "Simplificação deve reduzir o número de vértices de um círculo com 360 pontos"
    )


def test_simplify_geometry_poligono_muito_pequeno_levanta_erro():
    """
    Um polígono degenerado (área quase zero, menor que a tolerância de simplificação)
    deve levantar ValueError com mensagem explicativa.
    O polígono abaixo tem todos os vértices praticamente no mesmo ponto,
    resultando em geometria vazia após simplificação.
    """
    # Vértices colapsados: triângulo com lados de 0.000001 graus (~0.1 m)
    # muito menor que a tolerância padrão de 0.00001 graus
    epsilon = 0.000001
    pol_degenerade = Polygon([
        (-47.0,         -15.0),
        (-47.0 + epsilon, -15.0),
        (-47.0,         -15.0 + epsilon),
        (-47.0,         -15.0),
    ])

    with pytest.raises(ValueError, match="geometria vazia"):
        simplify_geometry(pol_degenerade)


# ---------------------------------------------------------------------------
# Testes de calculate_area_hectares
# ---------------------------------------------------------------------------

def test_calculate_area_hectares_retorna_positivo():
    """
    A área de qualquer polígono fechado válido deve ser positiva.
    Usamos um quadrado de ~1 km² e verificamos que a área calculada é > 0.
    """
    pol = poligono_um_km2()
    area = calculate_area_hectares(pol)

    assert area > 0, "Área deve ser positiva para um polígono válido"


def test_calculate_area_hectares_triangulo_simples():
    """
    Triângulo retângulo com catetos de ~1 grau × ~1 grau centrado em -47/-15.
    Na projeção Equal Earth (EPSG:6933), 1 grau de latitude ≈ 111 km e
    1 grau de longitude nessa latitude ≈ 96 km.
    Área esperada: 0.5 × 111 000 m × 96 000 m ≈ 5 328 000 000 m² ≈ 532 800 ha.
    Verificamos que o resultado está dentro de ±20% do valor esperado.
    """
    pol = triangulo_conhecido()
    area = calculate_area_hectares(pol)

    area_esperada_ha = 532_800  # valor de referência calculado manualmente
    tolerancia = 0.20  # 20% de margem

    assert area > area_esperada_ha * (1 - tolerancia), (
        f"Área {area} ha muito abaixo do esperado ~{area_esperada_ha} ha"
    )
    assert area < area_esperada_ha * (1 + tolerancia), (
        f"Área {area} ha muito acima do esperado ~{area_esperada_ha} ha"
    )
