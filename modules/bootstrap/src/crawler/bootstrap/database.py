"""Shared SQLAlchemy engine construction.

Database bootstrapping remains outside this module because creating application
users is identity-domain behavior, not a framework concern.
"""

from crawler.bootstrap.settings import settings
from sqlmodel import create_engine

engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))
