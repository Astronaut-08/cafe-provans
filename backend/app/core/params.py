from typing import Annotated

from fastapi import Path

# Id у БД це int4. Без верхньої межі запит /categories/99999999999 доходить до asyncpg
# і закінчується 500 («value out of int32 range»), а так клієнт отримує нормальну 422.
IdPath = Annotated[int, Path(ge=1, le=2_147_483_647, description='Ідентифікатор запису')]
