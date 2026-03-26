from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    API_PORT: int = 8000

    DB_HOST: str
    DB_PORT: int = 5432
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str

    RABBITMQ_HOST: str
    RABBITMQ_PORT: int = 5672
    RABBITMQ_USER: str
    RABBITMQ_PASSWORD: str

    REDIS_HOST: str
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""

    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    SMTP_HOST: str
    SMTP_PORT: int = 587
    SMTP_USER: str
    SMTP_PASSWORD: str
    EMAIL_FROM: str

    GOOGLE_CLIENT_ID: str

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()

# Application constants (not read from environment; keep next to settings for one import surface)
COOKIE_AUTH = "auth"
COOKIE_AUTH_RESET = "auth_reset"
COOKIE_ANON_SESSION = "anon_session"

AUTH_COOKIE_MAX_AGE = 259200
RESET_COOKIE_MAX_AGE = 900
RESET_CODE_REDIS_TTL = 600

ANON_SESSION_TTL_SECONDS = 14400
PRODUCT_CACHE_TTL_SECONDS = 86400

REDIS_SESSION_PREFIX = "session"
REDIS_PRODUCT_PREFIX = "product"

EMAIL_QUEUE = "email-queue"

ROLE_RANK_BY_NAME = {"BASIC": 1, "ADMIN": 2}

# Rate limiting (per path + IP; see core.security.rate_limit)
RATE_LIMIT_LOGIN_MAX_REQUESTS = 5
RATE_LIMIT_LOGIN_WINDOW_SECONDS = 300
RATE_LIMIT_FORGET_PASSWORD_MAX_REQUESTS = 3
RATE_LIMIT_FORGET_PASSWORD_WINDOW_SECONDS = 3600
RATE_LIMIT_VALIDATE_CODE_MAX_REQUESTS = 10
RATE_LIMIT_VALIDATE_CODE_WINDOW_SECONDS = 300

RATE_LIMIT_MENU_BOOTSTRAP_MAX_REQUESTS = 30
RATE_LIMIT_MENU_BOOTSTRAP_WINDOW_SECONDS = 60
RATE_LIMIT_CART_MUTATION_MAX_REQUESTS = 60
RATE_LIMIT_CART_MUTATION_WINDOW_SECONDS = 60
