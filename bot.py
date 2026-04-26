import asyncio
import os
from aiogram.exceptions import TelegramBadRequest
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from aiogram.filters import Command
from utils import get_user_name, generate_code

from db import (
    create_wallet,
    get_user_wallets,
    get_history_wallet,
    add_row,
    add_invites,
    get_connection,
    get_summ_spending_by_user
)

load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")
if not API_TOKEN:
    raise ValueError("API_TOKEN not set")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# 👉 хранение выбранного кошелька
user_active_wallet = {}

# --- START ---
@dp.message(Command("start"))
async def start(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Новый кошелек", callback_data="wallet:new"),
            InlineKeyboardButton(text="📂 Мои кошельки", callback_data="wallet:existing")
        ]
    ])
    await message.answer("Выберите действие:", reply_markup=kb)


# --- CREATE WALLET (без FSM) ---
@dp.callback_query(F.data == "wallet:new")
async def create_wallet_start(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("Напиши название кошелька:\nНапример: Дом")


@dp.message()
async def handle_text(message: Message):
    text = message.text.strip()

    # --- СОЗДАНИЕ КОШЕЛЬКА ---
    if text.lower().startswith("кошелек "):
        name = text.split(" ", 1)[1]
        username = get_user_name(message)

        await create_wallet(message.from_user.id, username, name)
        await message.answer(f"✅ Кошелек '{name}' создан!")
        return

    # --- ДОБАВЛЕНИЕ РАСХОДА ---
    if text.startswith("+"):
        parts = text[1:].strip().split(" ", 1)

        if len(parts) < 2:
            await message.answer("❗ Формат: + сумма название\nПример: + 500 еда")
            return

        try:
            summ = float(parts[0].replace(",", "."))
        except:
            await message.answer("❌ Неверная сумма")
            return

        name = parts[1]
        user_id = message.from_user.id

        wallet_id = user_active_wallet.get(user_id)

        if not wallet_id:
            await message.answer("❗ Сначала выбери кошелек")
            return

        await add_row(wallet_id, user_id, name, summ)

        await message.answer(f"✅ Добавлено: {name} — {summ:.2f}")
        return


# --- SHOW WALLETS ---
@dp.callback_query(F.data == "wallet:existing")
async def show_wallets(callback: CallbackQuery):
    wallets = await get_user_wallets(callback.from_user.id)

    if not wallets:
        await callback.message.answer("❌ У тебя нет кошельков")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=name, callback_data=f"wallet_select:{wid}")]
        for wid, name in wallets
    ])

    await callback.message.answer("Выбери кошелек:", reply_markup=kb)


@dp.callback_query(F.data.startswith("wallet_select:"))
async def select_wallet(callback: CallbackQuery):
    await callback.answer()

    wallet_id = int(callback.data.split(":")[1])
    user_active_wallet[callback.from_user.id] = wallet_id

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить расход", callback_data=f"wallet:add:{wallet_id}")],
        [InlineKeyboardButton(text="📊 История", callback_data=f"wallet:view:{wallet_id}")],
        [InlineKeyboardButton(text="💰 Баланс", callback_data=f"wallet:balance:{wallet_id}")],
        [InlineKeyboardButton(text="👥 Пригласить", callback_data=f"wallet:invite:{wallet_id}")]
    ])

    await callback.message.answer("Действия:", reply_markup=kb)


# --- ADD EXPENSE (инструкция вместо FSM) ---
@dp.callback_query(F.data.startswith("wallet:add:"))
async def add_expense(callback: CallbackQuery):
    await callback.answer()

    await callback.message.answer(
        "Напиши расход в формате:\n\n+ 500 еда"
    )


# --- VIEW WALLET ---
ROWS_PER_PAGE = 10

@dp.callback_query(F.data.startswith("wallet:view:"))
async def view_wallet(callback: CallbackQuery):
    parts = callback.data.split(":")
    wallet_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0

    rows = await get_history_wallet(wallet_id)

    if not rows:
        await callback.message.answer("❌ Нет данных")
        return

    start = page * ROWS_PER_PAGE
    end = start + ROWS_PER_PAGE
    page_rows = rows[start:end]

    text = "📅 Дата   👤 Кто        🛒 Название          💰 Сумма\n"
    text += "-" * 60 + "\n"

    for row in page_rows:
        row_id, dt, name, summ, user_id, user_name = row

        text += f"{dt.strftime('%d/%m/%y'):<10} {(user_name or '???'):<10} {name[:20]:<20} {summ:>10.2f}\n"

    text += "-" * 60 + "\n"
    text += f"Страница: {page + 1}"

    buttons = []

    if page > 0:
        buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"wallet:view:{wallet_id}:{page - 1}"))

    if end < len(rows):
        buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"wallet:view:{wallet_id}:{page + 1}"))

    kb = InlineKeyboardMarkup(inline_keyboard=[buttons] if buttons else [])

    try:
        await callback.message.edit_text(
            f"<pre>{text}</pre>",
            parse_mode="HTML",
            reply_markup=kb
        )
    except TelegramBadRequest:
        await callback.answer("Ты уже на этой странице")


# --- BALANCE ---
@dp.callback_query(F.data.startswith("wallet:balance:"))
async def show_debts(callback: CallbackQuery):
    wallet_id = int(callback.data.split(":")[2])

    balances = await get_summ_spending_by_user(wallet_id)
    target_id = callback.from_user.id

    target_user = next((u for u in balances if u[0] == target_id), None)

    if not target_user:
        await callback.message.answer("❌ Нет данных")
        return

    others = [u for u in balances if u[0] != target_id]
    _, target_name, target_sum = target_user

    text = "Кто должен       Кому           Сумма\n"
    text += "-" * 40 + "\n"

    for user_id, name, summ in others:
        diff = target_sum / len(balances) - summ / len(balances)

        if diff > 0:
            text += f"{name:<15}{target_name:<15}{diff:>8.2f}\n"
        else:
            text += f"{target_name:<15}{name:<15}{abs(diff):>8.2f}\n"

    await callback.message.answer(f"<pre>{text}</pre>", parse_mode="HTML")


# --- INVITE ---
@dp.callback_query(F.data.startswith("wallet:invite:"))
async def invite(callback: CallbackQuery):
    wallet_id = int(callback.data.split(":")[2])
    code = generate_code()

    await add_invites(wallet_id, code)

    await callback.message.answer(
        f"Код приглашения:\n\n`{code}`\n\nВведи: /join {code}",
        parse_mode="Markdown"
    )


# --- JOIN ---
@dp.message(Command("join"))
async def join_wallet(message: Message):
    parts = message.text.split()

    if len(parts) < 2:
        await message.answer("❗ Использование: /join CODE")
        return

    code = parts[1].upper()

    conn = await get_connection()
    cursor = await conn.cursor()

    await cursor.execute("SELECT wallet_id FROM invites WHERE code=%s", (code,))
    result = await cursor.fetchone()

    if not result:
        await message.answer("❌ Неверный код")
        return

    wallet_id = int(result[0])
    username = get_user_name(message)

    await cursor.execute(
        "INSERT IGNORE INTO wallets_users (wallet_id, user_id, user_name, accesses) VALUES (%s, %s, %s, %s)",
        (wallet_id, message.from_user.id, username, "member")
    )

    await conn.commit()

    await cursor.close()
    conn.close()

    await message.answer("✅ Ты присоединился!")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())