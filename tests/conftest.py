import os


REQUIRED_ENV_DEFAULTS = {
    "DB_HOST": "localhost",
    "DB_USER": "postgres",
    "DB_PASSWORD": "postgres",
    "DB_NAME": "self_checkout",
    "RABBITMQ_HOST": "localhost",
    "RABBITMQ_USER": "guest",
    "RABBITMQ_PASSWORD": "guest",
    "REDIS_HOST": "localhost",
    "SECRET_KEY": "test-secret-key",
    "SMTP_HOST": "localhost",
    "SMTP_USER": "user",
    "SMTP_PASSWORD": "pass",
    "EMAIL_FROM": "noreply@example.com",
    "GOOGLE_CLIENT_ID": "test-google-client-id",
}


for key, value in REQUIRED_ENV_DEFAULTS.items():
    os.environ.setdefault(key, value)
