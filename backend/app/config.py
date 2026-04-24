import os
from functools import lru_cache


class Settings:
    db_path: str = os.getenv("PERSONAL_OS_DB", "/data/personal-os.db")
    write_secret: str = os.getenv("PERSONAL_OS_WRITE_SECRET", "change-me")
    allowed_origins: list[str] = [
        o.strip()
        for o in os.getenv(
            "PERSONAL_OS_ALLOWED_ORIGINS",
            "http://localhost:3000,http://localhost:5173",
        ).split(",")
        if o.strip()
    ]


@lru_cache
def settings() -> Settings:
    return Settings()
