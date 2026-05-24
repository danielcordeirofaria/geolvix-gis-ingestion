from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """Dependency que fornece uma sessão de banco com o contexto de tenant injetado."""
    async with AsyncSessionLocal() as session:
        yield session


async def get_db_with_tenant(organizacao_id: int) -> AsyncSession:
    """
    Dependency que fornece uma sessão com o Row-Level Security (RLS) do tenant ativo.
    Executa SET LOCAL app.current_organization_id antes de liberar a sessão.
    O RESET é garantido no finally para não vazar para outras conexões do pool (HikariCP-safe).
    """
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                f"SET LOCAL app.current_organization_id = '{organizacao_id}'"
            )
            yield session
        finally:
            await session.execute("RESET app.current_organization_id")
