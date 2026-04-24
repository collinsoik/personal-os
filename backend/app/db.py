from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


_engine = create_engine(
    f"sqlite:///{settings().db_path}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def init_db() -> None:
    # Models are imported here so they register with Base.metadata.
    from . import models  # noqa: F401

    Base.metadata.create_all(_engine)


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
