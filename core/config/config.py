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
    RABBITMQ_MANAGEMENT_PORT: int = 15672

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

    STRIPE_SECRET_KEY: str = ""
    STRIPE_CHECKOUT_SUCCESS_URL: str = "http://localhost:3000/checkout/success"
    STRIPE_CHECKOUT_CANCEL_URL: str = "http://localhost:3000/checkout/cancel"
    STRIPE_CURRENCY: str = "chf"
    STRIPE_WEBHOOK_SECRET: str = ""

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
REDIS_IDEMPOTENCY_PREFIX = "checkout_idempotency"
REDIS_SSE_ADMIN_ORDERS_CHANNEL = "sse:admin:orders"

CHECKOUT_IDEMPOTENCY_TTL_SECONDS = 3600

EMAIL_QUEUE = "email-queue"

ROLE_RANK_BY_NAME = {"BASIC": 1, "ADMIN": 2}
