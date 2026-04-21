import asyncio
import os

from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

from utils import get_user_name, generate_code

from db import (
    create_wallet,
    get_user_wallets,
    get_history_wallet,
    add_row,
    add_invites,
    get_connection,
    calculate_debts,
    build_debts
)

load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")
if not API_TOKEN:
    raise ValueError("API_TOKEN not set")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- STATES ---
class WalletState(StatesGroup):
    waiting_for_name = State()


class ExpenseState(StatesGroup):
    waiting_for_name = State()
    waiting_for_sum = State()


# --- START ---
@dp.message(F.text == "/start")
async def start(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Новый кошелек", callback_data="wallet:new"),
            InlineKeyboardButton(text="📂 Мои кошельки", callback_data="wallet:existing")
        ]
    ])
    await message.answer("Выбери действие:", reply_markup=kb)


# --- CREATE WALLET ---
@dp.callback_query(F.data == "wallet:new")
async def create_wallet_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите название кошелька:")
    await state.set_state(WalletState.waiting_for_name)


@dp.message(WalletState.waiting_for_name)
async def save_wallet(message: Message, state: FSMContext):
    username = get_user_name(message)

    await create_wallet(message.from_user.id, username, message.text)
    await message.answer(f"✅ Кошелек '{message.text}' создан!")
    await state.clear()

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
    wallet_id = int(callback.data.split(":")[1])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить расход", callback_data=f"wallet:add:{wallet_id}")],
        [InlineKeyboardButton(text="📜 История", callback_data=f"wallet:view:{wallet_id}")],
        [InlineKeyboardButton(text="💰 Баланс", callback_data=f"wallet:balance:{wallet_id}")],
        [InlineKeyboardButton(text="👥 Пригласить", callback_data=f"wallet:invite:{wallet_id}")]
    ])

    await callback.message.answer("Действия:", reply_markup=kb)


# --- ADD EXPENSE ---
@dp.callback_query(F.data.startswith("wallet:add:"))
async def add_expense(callback: CallbackQuery, state: FSMContext):
    wallet_id = int(callback.data.split(":")[2])
    await state.update_data(wallet_id=wallet_id)

    await callback.message.answer("Введите название:")
    await state.set_state(ExpenseState.waiting_for_name)


@dp.message(ExpenseState.waiting_for_name)
async def get_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите сумму:")
    await state.set_state(ExpenseState.waiting_for_sum)


@dp.message(ExpenseState.waiting_for_sum)
async def get_sum(message: Message, state: FSMContext):
    try:
        summ = float(message.text)
    except:
        await message.answer("❌ Введите число (например 5.20)")
        return

    data = await state.get_data()

    await add_row(
        data["wallet_id"],
        message.from_user.id,
        data["name"],
        summ
    )

    await message.answer(f"✅ Добавлено:\n{data['name']} — {summ:.2f}")
    await state.clear()


# --- HISTORY ---
@dp.callback_query(F.data.startswith("wallet:view:"))
async def view_wallet(callback: CallbackQuery):
    wallet_id = int(callback.data.split(":")[2])
    rows = await get_history_wallet(wallet_id)

    if not rows:
        await callback.message.answer("❌ Нет данных")
        return

    text = "📅 Дата       🛒 Название      💰 Сумма\n"
    text += "---------------------------------\n"

    total = 0

    for row in rows:
        dt, name, summ = row[0], row[1], row[2]

        text += f"{dt.strftime('%d/%m/%y')}   {name:<15} {summ:>7.2f}\n"
        total += float(summ)

    text += "---------------------------------\n"
    text += f"Итого:                    {total:>7.2f}"

    await callback.message.answer(
        f"<pre>{text}</pre>",
        parse_mode="HTML"
    )

# --- BALANCE ---
@dp.callback_query(F.data.startswith("wallet:balance:"))
async def show_debts(callback: CallbackQuery):
    wallet_id = int(callback.data.split(":")[2])

    balances = await calculate_debts(wallet_id)
    debts = build_debts(balances)

    if not debts:
        await callback.message.answer("💚 Долгов нет")
        return

    conn = await get_connection()
    cursor = await conn.cursor()

    await cursor.execute(
        "SELECT user_id, user_name FROM wallets_users WHERE wallet_id=%s",
        (wallet_id,)
    )

    users = {row[0]: row[1] for row in await cursor.fetchall()}

    await cursor.close()
    conn.close()

    text = "Кто должен        Кому            Сумма\n"
    text += "------------------------------------------\n"

    for debtor_id, creditor_id, amount in debts:
        debtor = users.get(debtor_id, str(debtor_id))[:15]
        creditor = users.get(creditor_id, str(creditor_id))[:15]

        text += f"{debtor:<16}{creditor:<16}{amount:>8.2f}\n"

    text += "------------------------------------------"

    await callback.message.answer(
        f"<pre>{text}</pre>",
        parse_mode="HTML"
    )


# --- INVITE ---
@dp.callback_query(F.data.startswith("wallet:invite:"))
async def invite(callback: CallbackQuery):
    wallet_id = int(callback.data.split(":")[2])
    code = generate_code()

    await add_invites(wallet_id, code)

    await callback.message.answer(
        f"Код приглашения:\n\n`{code}`\n\nИспользуй /join CODE",
        parse_mode="Markdown"
    )


# --- JOIN ---
@dp.message(F.text.startswith("/join"))
async def join_wallet(message: Message):
    parts = message.text.split()

    if len(parts) < 2:
        await message.answer("❌ Используй: /join CODE")
        return

    code = parts[1].upper()

    conn = await get_connection()
    cursor = await conn.cursor()

    await cursor.execute("SELECT wallet_id FROM invites WHERE code=%s", (code,))
    result = await cursor.fetchone()

    if not result:
        await message.answer("❌ Код неверный")
        return

    wallet_id = int(result[0])

    username = get_user_name(message)

    await cursor.execute(
        "INSERT IGNORE INTO wallets_users (wallet_id, user_id, user_name, accesses) "
        "VALUES (%s, %s, %s, %s)",
        (wallet_id, message.from_user.id, username, "member")
    )

    await conn.commit()

    await cursor.close()
    conn.close()

    await message.answer("✅ Вы подключены!")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())