import asyncio
import random
import string
import os

from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from db import create_wallet, get_user_wallets, get_history_wallet, add_row, add_invites, get_connection, calculate_debts, build_debts
from dotenv import load_dotenv

load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")

if not API_TOKEN:
    raise ValueError("API_TOKEN not set")

def generate_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

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
            InlineKeyboardButton(text="Создать", callback_data="wallet:new"),
            InlineKeyboardButton(text="Существующий", callback_data="wallet:existing")
        ]
    ])

    await message.answer("Кошелёк👛:", reply_markup=kb)

# --- CREATE WALLET ---
@dp.callback_query(F.data == "wallet:new")
async def create_wallet_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите название кошелька:")
    await state.set_state(WalletState.waiting_for_name)

@dp.message(WalletState.waiting_for_name)
async def save_wallet(message: Message, state: FSMContext):
    wallet_name = message.text
    user_id = message.from_user.id

    await create_wallet(user_id, wallet_name)

    await message.answer(f"✅ Кошелек '{wallet_name}' создан!")

    await state.clear()

# --- EXISTING WALLET ---
@dp.callback_query(F.data == "wallet:existing")
async def show_wallets(callback: CallbackQuery):
    user_id = callback.from_user.id

    wallets = await get_user_wallets(user_id)

    if not wallets:
        await callback.message.answer("❌ У вас нет кошельков")
        return

    buttons = []

    for wallet_id, name in wallets:
        buttons.append([
            InlineKeyboardButton(
                text=name,
                callback_data=f"wallet_select:{wallet_id}"
            )
        ])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.answer(
        "💼 Ваши кошельки:",
        reply_markup=kb
    )

@dp.callback_query(F.data.startswith("wallet_select"))
async def select_wallet(callback: CallbackQuery):
    wallet_id = int(callback.data.split(":")[1])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Добавить запись", callback_data=f"wallet:add:{wallet_id}")
        ],
        [
            InlineKeyboardButton(text="📄 Посмотреть", callback_data=f"wallet:view:{wallet_id}")
        ],
        [
            InlineKeyboardButton(text="💰 Баланс", callback_data=f"wallet:balance:{wallet_id}")
        ],
        [
            InlineKeyboardButton(text="🧑‍🦱 Пригласить", callback_data=f"wallet:invite:{wallet_id}")
        ]
    ])

    await callback.message.answer(
        "Выберите действие:",
        reply_markup=kb
    )

@dp.callback_query(F.data.startswith("wallet:add"))
async def add_expense(callback: CallbackQuery, state: FSMContext):
    wallet_id = int(callback.data.split(":")[2])

    await state.update_data(wallet_id=wallet_id)

    await callback.message.answer("Введите название расхода:")
    await state.set_state(ExpenseState.waiting_for_name)

@dp.message(ExpenseState.waiting_for_sum)
async def get_sum(message: Message, state: FSMContext):
    try:
        summ = float(message.text)
    except:
        await message.answer("❌ Введите число (например 5.20)")
        return

    data = await state.get_data()

    wallet_id = data["wallet_id"]
    name = data["name"]
    user_id = message.from_user.id

    await add_row(wallet_id, user_id, name, summ)

    await message.answer(
        f"✅ Добавлено:\n{name} — {summ:.2f}"
    )

    await state.clear()

@dp.message(ExpenseState.waiting_for_name)
async def get_name(message: Message, state: FSMContext):
    name = message.text

    await state.update_data(name=name)

    await message.answer("Введите сумму:")
    await state.set_state(ExpenseState.waiting_for_sum)

@dp.callback_query(F.data.startswith("wallet:view"))
async def view_wallet(callback: CallbackQuery):
    wallet_id = int(callback.data.split(":")[2])

    rows = await get_history_wallet(wallet_id)

    if not rows:
        await callback.message.answer("📭 Нет записей")
        return

    text = ""
    total = 0

    for dt, name, summ in rows:
        date_str = dt.strftime("%d/%m/%y")

        text += f"{date_str} {name} {summ:.2f}\n"
        total += float(summ)

    text += f"\n💰 Общая сумма: {total:.2f}"

    await callback.message.answer(text)

@dp.callback_query(F.data.startswith("wallet:balance"))
async def show_debts(callback: CallbackQuery):
    wallet_id = int(callback.data.split(":")[2])

    balances = await calculate_debts(wallet_id)
    debts = build_debts(balances)

    if not debts:
        await callback.message.answer("💚 Долгов нет!")
        return

    text = "💸 Долги:\n\n"

    for from_user, to_user, amount in debts:
        text += f"👤 {from_user} → 👤 {to_user}: {amount:.2f}\n"

    await callback.message.answer(text)

@dp.callback_query(F.data.startswith("wallet:invite"))
async def invite(callback: CallbackQuery):
    wallet_id = int(callback.data.split(":")[2])
    code = generate_code()
    await add_invites(wallet_id, code)

    await callback.message.answer(
        f"🔗 Код приглашения:\n\n`{code}`\n\nПередайте его другу",
        parse_mode="Markdown"
    )

@dp.message(F.text.startswith("/join"))
async def join_wallet(message: Message):
    parts = message.text.split()

    if len(parts) < 2:
        await message.answer("❌ Используй: /join CODE")
        return

    code = parts[1].strip()
    user_id = message.from_user.id

    conn = await get_connection()
    cursor = await conn.cursor()

    # проверка кода
    await cursor.execute(
        "SELECT wallet_id FROM invites WHERE code = %s",
        (code,)
    )

    result = await cursor.fetchone()

    if not result:
        await message.answer("❌ Неверный код")
        await cursor.close()
        conn.close()
        return

    wallet_id = result[0]

    # защита от повторного добавления
    await cursor.execute(
        "SELECT 1 FROM wallets_users WHERE wallet_id=%s AND user_id=%s",
        (wallet_id, user_id)
    )

    exists = await cursor.fetchone()

    if exists:
        await message.answer("ℹ️ Вы уже в этом кошельке")
        await cursor.close()
        conn.close()
        return

    # добавление пользователя
    await cursor.execute(
        """
        INSERT INTO wallets_users (wallet_id, user_id, accesses)
        VALUES (%s, %s, %s)
        """,
        (wallet_id, user_id, "member")
    )

    await conn.commit()

    await cursor.close()
    conn.close()

    await message.answer("✅ Вы подключены к кошельку!")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())