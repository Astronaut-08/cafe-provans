from decimal import Decimal
from typing import Annotated

from pydantic import PlainSerializer

# Усередині рахуємо Decimal (без похибок округлення), а в JSON віддаємо звичайним числом (180.0),
# бо так зручніше фронтенду: без Number("180.00"). Суми завжди рахує бекенд, фронтенд лише показує.
Money = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used='json')]
