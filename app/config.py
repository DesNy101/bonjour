from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    secret_key: str = "dev-only-secret-change-me"
    database_url: str = "postgresql://postgres:password@localhost:5432/bonjour"
    admin_name: str = "Bonjour Administrator"
    admin_email: str = ""
    admin_password: str = ""
    setup_key: str = ""  # one-time key that lets the very first Super Admin register (only works while no users exist)
    session_hours: int = 12
    cookie_secure: str = "auto"
    paystack_secret_key: str = ""
    paystack_public_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    sms_provider_key: str = ""
    whatsapp_provider_key: str = ""
    upload_dir: str = "uploads"
    public_base_url: str = "http://localhost:8000"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure.lower() in ("true", "1", "yes"):
            return True
        if self.cookie_secure.lower() in ("false", "0", "no"):
            return False
        return self.is_production

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
