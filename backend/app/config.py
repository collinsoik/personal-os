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

    spotify_client_id: str = os.getenv("SPOTIFY_CLIENT_ID", "")
    spotify_client_secret: str = os.getenv("SPOTIFY_CLIENT_SECRET", "")
    spotify_redirect_uri: str = os.getenv(
        "SPOTIFY_REDIRECT_URI",
        "http://127.0.0.1:3010/api/oauth/spotify/callback",
    )

    frontend_url: str = os.getenv(
        "FRONTEND_URL",
        "https://personal-os-sage-tau.vercel.app/",
    )


@lru_cache
def settings() -> Settings:
    return Settings()
