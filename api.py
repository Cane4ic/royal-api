import os
import asyncpg
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from datetime import datetime
from typing import Optional



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

# --------- НОВОЕ: модель для персональных данных ----------

class PersonalDataRequest(BaseModel):
    tg_id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    birth_date: Optional[str] = None  # формат YYYY-MM-DD из <input type="date">
    gender: Optional[str] = None      # 'male' / 'female' / и т.п.


# делаем эндпоинт с тем же путём, что и на фронте: /api/profile
@app.post("/api/personal-data/save")
async def save_personal_data(req: PersonalDataRequest):
    """
    Сохраняет персональные данные пользователя в таблицу users по tg_id.
    birth_date ожидается в формате 'YYYY-MM-DD' (как отдаёт <input type="date">).
    """
    # 1. Парсим дату, если пришла
    birth_date_db = None
    if req.birth_date:
        try:
            birth_date_db = datetime.strptime(req.birth_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Неверный формат даты. Ожидается YYYY-MM-DD"
            )

    # 2. Обновляем пользователя в БД
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE users
            SET
                first_name = $1,
                last_name  = $2,
                birth_date = $3,
                gender     = $4
            WHERE tg_id = $5
            RETURNING first_name, last_name, birth_date, gender
            """,
            req.first_name,
            req.last_name,
            birth_date_db,
            req.gender,
            req.tg_id,
        )

    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "birth_date": row["birth_date"].isoformat() if row["birth_date"] else None,
        "gender": row["gender"],
    }

class PersonalDataGetRequest(BaseModel):
    tg_id: int


@app.post("/api/personal-data/get")
async def get_personal_data(req: PersonalDataGetRequest):
    """
    Возвращает персональные данные пользователя по tg_id.
    """
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT first_name, last_name, birth_date, gender
            FROM users
            WHERE tg_id = $1
            """,
            req.tg_id,
        )

    if not row:
        # Если юзер ещё не заполнял профиль — просто 404
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        # birth_date в JSON будет "YYYY-MM-DD", что идеально для <input type="date">
        "birth_date": row["birth_date"].isoformat() if row["birth_date"] else None,
        "gender": row["gender"],
    }









