import os
import asyncpg
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_DSN = os.getenv("DATABASE_URL")
if not DB_DSN:
    raise RuntimeError("DATABASE_URL не задан в .env")

app = FastAPI()

# Разрешаем запросы с твоего фронта
origins = [
    "https://cane4ic.github.io",   # твой GitHub Pages домен
    # сюда потом добавишь домен, где будет настоящий фронт
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db_pool: asyncpg.Pool | None = None


@app.on_event("startup")
async def on_startup():
    global db_pool
    logger.info("Connecting to Postgres from API...")
    db_pool = await asyncpg.create_pool(DB_DSN)
    logger.info("API DB pool created")


@app.on_event("shutdown")
async def on_shutdown():
    global db_pool
    if db_pool:
        await db_pool.close()
        logger.info("API DB pool closed")


class BalanceRequest(BaseModel):
    tg_id: int

class DepositAddressRequest(BaseModel):
    tg_id: int


@app.post("/api/balance")
async def get_balance(req: BalanceRequest):
    """
    Возвращает баланс по Telegram ID.
    """
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT balance_usdt FROM users WHERE tg_id = $1",
            req.tg_id,
        )

    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "balance": float(row["balance_usdt"])
    }


class BalanceChangeRequest(BaseModel):
    tg_id: int
    delta: float   # на сколько изменить баланс (+выигрыш, -ставка)

@app.post("/api/deposit-address")
async def get_deposit_address(req: DepositAddressRequest):
    """
    Возвращает депозит-адрес пользователя по его Telegram ID.
    """
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT da.address
            FROM deposit_addresses da
            JOIN users u ON da.user_id = u.id
            WHERE u.tg_id = $1
            ORDER BY da.assigned_at DESC
            LIMIT 1
            """,
            req.tg_id,
        )

    if not row:
        raise HTTPException(status_code=404, detail="Deposit address not found")

    return {"address": row["address"]}


@app.post("/api/change-balance")
async def change_balance(req: BalanceChangeRequest):
    """
    Изменяет баланс на delta и возвращает новый баланс.
    """
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE users
            SET balance_usdt = GREATEST(0, balance_usdt + $1)
            WHERE tg_id = $2
            RETURNING balance_usdt
            """,
            req.delta,
            req.tg_id,
        )

    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    return {"balance": float(row["balance_usdt"])}


