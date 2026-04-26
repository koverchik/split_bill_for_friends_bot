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

async def get_summ_by_user_wallet(wallet_id):
    conn = await get_connection()
    cursor = await conn.cursor()

    await cursor.execute(
        """
        SELECT SUM(summ), user_id 
        FROM rows WHERE wallet_id=%s 
        GROUP BY user_id
        """,
        (wallet_id,)
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
        SELECT r.id, r.datetime, r.name, r.summ, r.user_id, wu.user_name
        FROM rows r
        JOIN wallets_users wu 
          ON r.wallet_id = wu.wallet_id AND r.user_id = wu.user_id
        WHERE r.wallet_id = %s
        ORDER BY r.datetime DESC
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

async def get_summ_spending_by_user(wallet_id):
    conn = await get_connection()
    cursor = await conn.cursor()

    await cursor.execute(
        """
        SELECT wu.user_id, wu.user_name, COALESCE(SUM(r.summ), 0)
        FROM wallets_users wu
        LEFT JOIN rows r 
            ON wu.user_id = r.user_id AND wu.wallet_id = r.wallet_id
        WHERE wu.wallet_id = %s
        GROUP BY wu.user_id, wu.user_name
        """,
        (wallet_id,)
    )

    rows = await cursor.fetchall()

    await cursor.close()
    conn.close()

    return rows