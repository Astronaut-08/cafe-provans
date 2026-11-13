from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    '''Base class for all database models.'''
    pass

from models.location import Location
from models.user import User