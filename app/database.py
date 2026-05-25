from sqlalchemy import text
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


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def get_db_with_tenant(organizacao_id: str):
    """
    Sessao com Row-Level Security ativa para o tenant.
    Injeta o UUID da organizacao via SET LOCAL antes de liberar a sessao.
    RESET garantido no finally para nao vazar entre conexoes do pool.
    """
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                text(f"SET LOCAL app.current_organization_id = '{organizacao_id}'")
            )
            yield session
        finally:
            await session.execute(text("RESET app.current_organization_id"))
