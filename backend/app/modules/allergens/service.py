from collections.abc import Sequence

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.allergen import Allergen
from app.dependencies import get_db


class AllergenService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self) -> Sequence[Allergen]:
        result = await self.session.scalars(select(Allergen).order_by(Allergen.name, Allergen.id))
        return result.all()


def get_allergen_service(session: AsyncSession = Depends(get_db)) -> AllergenService:
    return AllergenService(session)
