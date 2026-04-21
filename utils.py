import random
import string

def get_user_name(message):
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    tg_username = message.from_user.username

    full_name = " ".join(filter(None, [first_name, last_name]))
    username = full_name if full_name else f"@{tg_username}" if tg_username else "Unknown"

    return username

def generate_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
