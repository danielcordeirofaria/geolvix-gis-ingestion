"""
Utilitários de segurança para validação de uploads de arquivos GIS.

Proteções implementadas (SDD seção 7):
- XXE / DTD injection em arquivos KML
- Zip Slip / Directory Traversal em Shapefiles (.zip)
- Zip Bomb (limite de tamanho total descompactado)
- Validação de extensão e tamanho máximo (10 MB)
"""
import os
import zipfile
from pathlib import Path
from fastapi import HTTPException, UploadFile, status

ALLOWED_EXTENSIONS = {".kml", ".geojson", ".zip"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_UNZIP_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB descompactado

# Extensões permitidas dentro de um .zip de Shapefile
SHP_ZIP_ALLOWED_EXTENSIONS = {".shp", ".dbf", ".shx", ".prj", ".cpg", ".qpj"}


def validate_file_extension(filename: str) -> str:
    """Valida extensão do arquivo e retorna o tipo detectado: 'kml', 'geojson' ou 'shp'."""
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Formato não suportado '{suffix}'. Use .kml, .geojson ou .zip (Shapefile).",
        )
    if suffix == ".zip":
        return "shp"
    return suffix.lstrip(".")


def validate_file_size(file_size: int) -> None:
    """Valida que o arquivo não ultrapassa o limite de 10 MB."""
    if file_size > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Arquivo muito grande. Tamanho máximo permitido: 10 MB.",
        )


def validate_zip_contents(zip_path: str) -> list[str]:
    """
    Valida o conteúdo de um .zip de Shapefile contra:
    - Zip Slip (path traversal via nomes de arquivos como '../../etc/passwd')
    - Zip Bomb (tamanho total descompactado > 10 MB)
    - Extensões não permitidas dentro do zip

    Retorna lista de nomes de arquivos seguros dentro do zip.
    """
    safe_names = []

    with zipfile.ZipFile(zip_path, "r") as zf:
        total_uncompressed = 0

        for info in zf.infolist():
            # Proteção Zip Slip: resolve o caminho e verifica se fica dentro do diretório raiz
            resolved = Path(os.path.realpath(os.path.join("/tmp", info.filename)))
            if not str(resolved).startswith("/tmp"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Arquivo ZIP contém caminho inválido (possível Zip Slip).",
                )

            # Ignora diretórios
            if info.filename.endswith("/"):
                continue

            # Valida extensão de cada arquivo dentro do zip
            ext = Path(info.filename).suffix.lower()
            if ext not in SHP_ZIP_ALLOWED_EXTENSIONS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"O ZIP contém arquivo com extensão não permitida: '{ext}'.",
                )

            # Proteção Zip Bomb: acumula tamanho descompactado
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_UNZIP_SIZE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="Conteúdo descompactado do ZIP ultrapassa o limite de 10 MB.",
                )

            safe_names.append(info.filename)

    # Verifica presença mínima: .shp e .dbf
    exts_found = {Path(n).suffix.lower() for n in safe_names}
    if ".shp" not in exts_found or ".dbf" not in exts_found:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O ZIP deve conter pelo menos os arquivos .shp e .dbf do Shapefile.",
        )

    return safe_names
