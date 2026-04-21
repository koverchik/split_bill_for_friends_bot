import aiomysql
import os

from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "db": os.getenv("DB_NAME"),
}

async def get_connection():
    return await aiomysql.connect(**DB_CONFIG)

async def create_wallet(user_id, username, name):
    conn = await get_connection()
    cursor = await conn.cursor()

    await cursor.execute(
        "INSERT INTO wallets (name) VALUES (%s)",
        (name,)
    )
    wallet_id = cursor.lastrowid

    await cursor.execute(
        "INSERT INTO wallets_users (wallet_id, user_id, user_name, accesses) VALUES (%s, %s, %s, %s)",
        (wallet_id, user_id, username, "owner")
    )

    await conn.commit()

    await cursor.close()
    conn.close()

    return wallet_id

async def get_user_wallets(user_id):
    conn = await get_connection()
    cursor = await conn.cursor()

    await cursor.execute(
        """
        SELECT w.id, w.name
        FROM wallets w
        JOIN wallets_users wu ON w.id = wu.wallet_id
        WHERE wu.user_id = %s
        """,
        (user_id,)
    )

    rows = await cursor.fetchall()

    await cursor.close()
    conn.close()

    return rows

async def get_history_wallet(wallet_id):
    conn = await get_connection()
    cursor = await conn.cursor()

    await cursor.execute(
        """
        SELECT datetime, name, summ
        FROM rows
        WHERE wallet_id = %s
        ORDER BY datetime DESC
        """,
        (wallet_id,)
    )

    rows = await cursor.fetchall()

    await cursor.close()
    conn.close()

    return rows

async def add_row(wallet_id, user_id, name, summ):
    conn = await get_connection()
    cursor = await conn.cursor()

    await cursor.execute(
        """
        INSERT INTO rows (datetime, name, summ, user_id, wallet_id) 
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            datetime.now(),
            name,
            summ,
            user_id,
            wallet_id
        )
    )

    await conn.commit()

    await cursor.close()
    conn.close()

    return True

async def add_invites(wallet_id, code):
    conn = await get_connection()
    cursor = await conn.cursor()

    await cursor.execute(
        "DELETE FROM invites WHERE wallet_id = %s",
        (wallet_id,)
    )

    await cursor.execute(
        "INSERT INTO invites (wallet_id, code, created_at) VALUES (%s, %s, %s)",
        (wallet_id, code, datetime.now())
    )
    await conn.commit()

    await cursor.close()
    conn.close()

    return True

async def calculate_debts(wallet_id):
    conn = await get_connection()
    cursor = await conn.cursor()

    # участники
    await cursor.execute(
        "SELECT user_id FROM wallets_users WHERE wallet_id=%s",
        (wallet_id,)
    )
    users = [u[0] for u in await cursor.fetchall()]

    if not users:
        return []

    # расходы
    await cursor.execute(
        """
        SELECT user_id, SUM(summ)
        FROM rows
        WHERE wallet_id=%s
        GROUP BY user_id
        """,
        (wallet_id,)
    )

    spent = {row[0]: float(row[1]) for row in await cursor.fetchall()}

    await cursor.close()
    conn.close()

    # общий баланс
    total = sum(spent.get(u, 0) for u in users)
    per_person = total / len(users)

    # считаем баланс
    balances = {}
    for u in users:
        balances[u] = spent.get(u, 0) - per_person

    return balances

def build_debts(balances):
    creditors = []
    debtors = []

    for user, balance in balances.items():
        if balance > 0:
            creditors.append([user, balance])
        elif balance < 0:
            debtors.append([user, -balance])

    result = []

    for d_user, d_amount in debtors:
        for c_user, c_amount in creditors:

            if d_amount == 0:
                break

            pay = min(d_amount, c_amount)

            result.append((d_user, c_user, pay))

            d_amount -= pay
            c_amount -= pay

    return result