from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite+aiosqlite:///./adrobot.db"
    keitaro_mode: str = "demo"
    keitaro_url: str = ""
    keitaro_api_key: str = ""
    operator_password: str = ""
    cookie_secure: bool = False
    frontend_origin: str = "http://127.0.0.1:5173"


@lru_cache
def settings():
    return Settings()
