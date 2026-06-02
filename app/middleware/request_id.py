"""
Middleware de Request ID para rastreamento distribuído.

Lê o header X-Request-ID enviado pelo geolvix-core e injeta no contexto
de logging de cada requisição, permitindo correlacionar logs entre serviços.

Se o header não estiver presente (ex: chamada direta em testes), gera um ID local.
O ID é devolvido no header X-Request-ID da resposta.
"""
import logging
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# ContextVar para armazenar o request ID de forma thread-safe em async
_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    """Retorna o request ID da requisição atual."""
    return _request_id_var.get()


class RequestIdFilter(logging.Filter):
    """
    Filtro de logging que injeta request_id em cada LogRecord.
    Registrado no logger root para funcionar em todos os módulos.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware ASGI que:
      1. Lê X-Request-ID do header (propagado pelo Core) ou gera UUID local
      2. Armazena no ContextVar para uso nos logs
      3. Adiciona X-Request-ID na resposta para rastreamento
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = (
            request.headers.get("X-Request-ID")
            or uuid.uuid4().hex[:12]
        )

        token = _request_id_var.set(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            _request_id_var.reset(token)
