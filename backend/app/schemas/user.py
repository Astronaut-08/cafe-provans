from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime

class User(BaseModel):
    id: int
    phone: str
    full_name: str
    role: Literal['admin', 'waiter', 'chef'] = 'waiter'
    location_id: int
    created_at: datetime = Field(default_factory=datetime.now)