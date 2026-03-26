from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.logger.logger import logger
from core.postgresql.postgresql import postgresql
from core.rabbitmq.rabbitmq import rabbitmq
from core.redis.redis import redis_cache
from routes.auth.router import router as auth_router
from routes.cart.router import router as cart_router
from routes.menu.router import router as menu_router
from routes.users.router import router as users_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting service connections...")

    await postgresql.connect()
    await redis_cache.connect()
    await rabbitmq.connect()

    logger.info("All services connected successfully.")

    yield

    await postgresql.disconnect()
    await redis_cache.disconnect()
    await rabbitmq.disconnect()


app = FastAPI(
    lifespan=lifespan,
    title="FastAPI Template",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(users_router, prefix="/users", tags=["users"])
app.include_router(menu_router, prefix="/menu", tags=["menu"])
app.include_router(cart_router, prefix="/cart", tags=["cart"])
