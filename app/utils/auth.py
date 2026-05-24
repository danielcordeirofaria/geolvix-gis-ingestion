"""
Autenticação de requisições internas entre microsserviços.
O Core Service deve enviar o cabeçalho X-Internal-Token com o token compartilhado.
"""
from fastapi import Header, HTTPException, status
from app.config import get_settings

settings = get_settings()


async def verify_internal_token(x_internal_token: str = Header(...)):
    """
    Dependency que valida o token interno compartilhado com o Core Service.
    Bloqueia qualquer requisição sem o token correto.
    """
    if x_internal_token != settings.INTERNAL_API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token interno inválido ou ausente.",
        )
