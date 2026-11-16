from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Allergen(Base):
    __tablename__ = 'allergens'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)  # gluten, lactose, nuts ...
    name: Mapped[str] = mapped_column(String(100), nullable=False)
