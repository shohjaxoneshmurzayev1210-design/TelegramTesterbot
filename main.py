import asyncio
import random
import json
import logging
import re
import os
import sqlite3

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web

# =========================================================
# CONFIG & SETTINGS
# =========================================================
TOKEN = "8810890132:AAEDf47oemfd-ascu4R8b4tOPFUBlewg9bY" 
QUIZ_TIME = 50
ADMIN_PASSWORD = "^02-25-Kin"

ADMIN_CHAT_ID = 7626126897  
CARD_NUMBER = "5614 6818 1629 8438"
CARD_OWNER = "Shmurzayev Shohjaxon"
VIP_PRICE = "5,000 so'm"

PROMOCODES = {
    "Last-F-70": "To'liq VIP",
    "Kin-602-25": "To'liq VIP"
}

SUBJECTS = {
    "Falsafa": "Falsafa.docx",
    "MT-V-A": "Mtuzilma.docx",
    "Dasturlash": "Dasturlash.docx",
    "Dinshunoslik": "Dinshunoslik.docx",
    "Ingliz tili-{Di}": "Ingliz2.docx",
    "Ingliz tili-{KIN}": "Ingliz.docx",
    "Fizika": "Fizika.docx"  
}

ENGLISH_PDF_PATH = "Ingliz_javoblar.pdf"
ANSWERS_JSON_PATH = "Fizika_answers.json"  

try:
    from parser import get_quizzes, get_quizzes_programming, get_quizzes_english_pdf_docx, get_quizzes_by_letters
except ImportError:
    def get_quizzes(p): return []
    def get_quizzes_programming(p): return []
    def get_quizzes_english_pdf_docx(d, p): return []
    def get_quizzes_by_letters(p, j): return []

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

FIREWORK_EFFECT = "5046509860389126442"
SUCCESS_MESSAGES = ["🎉 TO'G'RI JAVOB!", "✨ SUPER!", "🏆 AJOYIB!", "🔥 ZO'R ISH!"]

# =========================================================
# FSM STATES (To'lov holatlari)
# =========================================================
class PaymentStates(StatesGroup):
    waiting_for_promo = State()
    waiting_for_receipt = State()

# =========================================================
# MA'LUMOTLAR BAZASI (SQLITE) - Railway uchun data/ papkasida
# =========================================================
DB_PATH = "data/database.db"

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vip_users (
            user_id INTEGER PRIMARY KEY
        )
    """)
    conn.commit()
    conn.close()

init_db()

def is_vip(user_id: int):
    if user_id in temp_allowed_users: return True
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM vip_users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        return row is not None
    except:
        return False

def save_vip_id_to_db(user_id: int):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO vip_users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        conn.close()
        logging.info(f"Foydalanuvchi bazaga VIP qilib qo'shildi: {user_id}")
    except Exception as e:
        logging.error(f"VIP ID saqlashda xatolik: {e}")

# =========================================================
# UTILS & SESSION MANAGEMENT
# =========================================================
user_sessions = {}
temp_allowed_users = set()

def load_allowed_ids():
    try:
        with open("users.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            return sorted([int(i) for i in data.get("allowed_ids", [])])
    except: return []

ALLOWED_IDS = load_allowed_ids()

def is_allowed(user_id: int):
    if user_id in temp_allowed_users: return True
    if not ALLOWED_IDS: return False  
    
    low, high = 0, len(ALLOWED_IDS) - 1
    while low <= high:
        mid = (low + high) // 2
        if ALLOWED_IDS[mid] == user_id: return True
        elif ALLOWED_IDS[mid] < user_id: low = mid + 1
        else: high = mid - 1
    return False

def format_quiz_text(text):
    code_indicators = [';', '{', '}', 'print(', 'cout', 'int ', 'public ', 'void ', 'def ', 'class ']
    if any(ind in text for ind in code_indicators):
        return f"<code>{text}</code>"
    return text

# =========================================================
# KEYBOARDS
# =========================================================
def get_courses_menu():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="🎓 1-kurs"))
    builder.add(types.KeyboardButton(text="🔒 2-kurs"))
    builder.add(types.KeyboardButton(text="🔒 3-kurs"))
    builder.add(types.KeyboardButton(text="🔒 4-kurs"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_subjects_menu():
    builder = ReplyKeyboardBuilder()
    for subject in SUBJECTS.keys():
        builder.add(types.KeyboardButton(text=f"📚 {subject}"))
    builder.add(types.KeyboardButton(text="⬅️ Kurslar ro'yxatiga qaytish"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_pay_inline_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Obuna bo'lish (To'lov)", callback_data="buy_vip")
    builder.button(text="🔑 Promokod kiritish", callback_data="enter_promo")
    builder.adjust(1)
    return builder.as_markup()

def get_payment_flow_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ To'lov qildim", callback_data="paid_clicked")
    builder.button(text="❌ Bekor qilish", callback_data="cancel_payment")
    builder.adjust(1)
    return builder.as_markup()

# =========================================================
# BOT INITIALIZATION
# =========================================================
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# =========================================================
# ADMIN & AUTH HANDLERS
# =========================================================
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    await message.answer("🔑 <b>Admin tasdiqlash.</b>\nIltimos, maxfiy kodni yuboring:", parse_mode="HTML")

@dp.message(F.text == ADMIN_PASSWORD)
async def process_admin_code(message: types.Message):
    temp_allowed_users.add(message.from_user.id)
    await message.answer("✅ <b>Ruxsat berildi!</b>\nEndi botdan to'liq foydalanishingiz mumkin.", 
                         reply_markup=get_courses_menu(), parse_mode="HTML")

# =========================================================
# VIP & PROMO CALLBACK HANDLERS
# =========================================================
@dp.callback_query(F.data == "enter_promo")
async def promo_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(PaymentStates.waiting_for_promo)
    await callback.message.answer(
        "🔑 <b>Promokod kiritish tizimi</b>\n\nIltimos, amaldagi promo-kodni yuboring:", 
        parse_mode="HTML"
    )

@dp.message(StateFilter(PaymentStates.waiting_for_promo))
async def process_promo(message: types.Message, state: FSMContext):
    code = message.text.strip()
    if code in PROMOCODES:
        save_vip_id_to_db(message.from_user.id)
        await state.clear()
        await message.answer(
            f"🎉 <b>Ajoyib!</b> <code>{code}</code> promokodi tasdiqlandi.\n"
            f"Sizga barcha fanlardan muvaffaqiyatli VIP ruxsat berildi! 🚀\n\n"
            f"<b>Ro'yxatdan o'tish muvaffaqiyatli yakunlandi, testlarda omad!</b>",
            reply_markup=get_courses_menu(),
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "❌ <b>Noto'g'ri yoki eskirgan promokod!</b>\nQaytadan urinib ko'ring yoki /start bosing.",
            parse_mode="HTML"
        )

@dp.callback_query(F.data == "buy_vip")
async def buy_vip_callback(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    
    pay_text = (
        f"💳 <b>BOTDAN TO'LIQ FOYDALANISH UCHUN OBUNA</b>\n\n"
        f"Sizning ID: <code>{user_id}</code>\n"
        f"To'lov summasi: <b>{VIP_PRICE}</b>\n\n"
        f"📌 <b>Karta ma'lumotlari:</b>\n"
        f"💳 Karta: <code>{CARD_NUMBER}</code>\n"
        f"👤 Egalik qiluvchi: <b>{CARD_OWNER}</b>\n\n"
        f"⚠️ <i>To'lovni amalga oshirgach, pastdagi 'To'lov qildim' tugmasini bosing va chek rasmini yuboring!</i>"
    )
    await callback.message.answer(pay_text, reply_markup=get_payment_flow_keyboard(), parse_mode="HTML")

@dp.callback_query(F.data == "paid_clicked")
async def paid_clicked_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(PaymentStates.waiting_for_receipt)
    await callback.message.answer(
        "📸 <b>Ajoyib! Endi to'lov chekini (rasm ko'rinishida) yuboring:</b>\n"
        "Biz chekni tekshirib, tez fursatda ruxsat beramiz.",
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "cancel_payment")
async def cancel_payment_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("To'lov jarayoni bekor qilindi.", show_alert=True)
    await state.clear()
    await callback.message.answer("🏠 Bosh sahifa", reply_markup=get_courses_menu())

@dp.message(StateFilter(PaymentStates.waiting_for_receipt), F.photo)
async def process_receipt(message: types.Message, state: FSMContext):
    user = message.from_user
    photo_id = message.photo[-1].file_id
    
    admin_markup = InlineKeyboardBuilder()
    admin_markup.button(text="✅ Tasdiqlash (VIP berish)", callback_data=f"approve_vip_{user.id}")
    admin_markup.button(text="❌ Rad etish", callback_data=f"reject_vip_{user.id}")
    admin_markup.adjust(1)

    try:
        await bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=photo_id,
            caption=f"💰 <b>Yangi to'lov cheki keldi!</b>\n\n"
                    f"👤 Foydalanuvchi: <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
                    f"🆔 ID: <code>{user.id}</code>\n"
                    f"Username: @{user.username if user.username else 'Yo\'q'}",
            reply_markup=admin_markup.as_markup(),
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"Adminga chek yuborishda xato: {e}")

    await state.clear()
    await message.answer(
        "⏳ <b>Iltimos, bir necha daqiqa kuting!</b>\n"
        "To'lovni tekshirish 10 daqiqadan 1 soatgacha cho'zilishi mumkin. "
        "Tasdiqlanishi bilan sizga xabar yuboramiz va barcha fanlar ochiladi! 🕰",
        reply_markup=get_courses_menu(),
        parse_mode="HTML"
    )

@dp.message(StateFilter(PaymentStates.waiting_for_receipt))
async def process_receipt_invalid(message: types.Message):
    await message.answer("⚠️ Iltimos, to'lov chekini faqat <b>rasm (photo)</b> ko'rinishida yuboring!")

@dp.callback_query(F.data.startswith("approve_vip_"))
async def approve_vip(callback: types.CallbackQuery):
    target_user_id = int(callback.data.split("_")[2])
    save_vip_id_to_db(target_user_id)
    
    await callback.answer("Foydalanuvchiga VIP ruxsat berildi!", show_alert=True)
    await callback.message.edit_caption(caption=callback.message.caption + "\n\n🟢 <b>TASDIQLANDI (VIP BERILDI)</b>", parse_mode="HTML")
    
    try:
        await bot.send_message(
            chat_id=target_user_id,
            text="🚀 <b>To'lov qabul qilindi, testda omad!</b>\n"
                 "Barcha fanlar va kurslar siz uchun to'liq ochildi. Boshlashingiz mumkin!",
            reply_markup=get_courses_menu(),
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"Userga tasdiq yuborilmadi: {e}")

@dp.callback_query(F.data.startswith("reject_vip_"))
async def reject_vip(callback: types.CallbackQuery):
    target_user_id = int(callback.data.split("_")[2])
    
    await callback.answer("To'lov rad etildi.", show_alert=True)
    await callback.message.edit_caption(caption=callback.message.caption + "\n\n🔴 <b>RAD ETILDI</b>", parse_mode="HTML")
    
    try:
        await bot.send_message(
            chat_id=target_user_id,
            text="❌ <b>To'lovingiz tasdiqlanganicha yo'q!</b>\n"
                 "Yuborilgan chek xato yoki mablag' kelib tushmagan bo'lishi mumkin. "
                 "Muammo bo'lsa adminga murojaat qiling.\n"
                 f"👤 Admin ID: <code>{ADMIN_CHAT_ID}</code>",
            reply_markup=get_courses_menu(),
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"Userga rad javobi yuborilmadi: {e}")

# =========================================================
# MAIN HANDLERS
# =========================================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    if not is_allowed(user_id):
        return await message.answer(
            f"🚫 <b>Ruxsat berilmagan!</b>\nID: <code>{user_id}</code>\n\nAdmin bo'lsangiz /admin buyrug'ini yozing.",
            parse_mode="HTML"
        )
    
    # VIP Obuna tekshiruvi
    if not is_vip(user_id):
        text_vip = (
            f"👋 Assalomu alaykum, {message.from_user.first_name}!\n"
            f"🆔 Sizning ID: <code>{user_id}</code>\n\n"
            f"💰 <b>Ushbu botdan foydalanish PULLIK!</b>\n"
            f"Botdan to'liq foydalananish narxi: <b>{VIP_PRICE}</b>\n\n"
            f"Siz botdan hozircha foydalana olmaysiz. Tizimga obuna bo'lishingiz yoki maxsus promo-kodga ega bo'lishingiz lozim.\n\n"
            f"⚠️ Muammo yuzaga kelsa adminga murojaat qiling:\n"
            f"👤 Admin ID: <code>{ADMIN_CHAT_ID}</code>"
        )
        return await message.answer(text_vip, reply_markup=get_pay_inline_keyboard(), parse_mode="HTML")

    await message.answer(
        f"🎓 <b>PROFESSIONAL TEST BOT</b>\n\nAssalomu alaykum, {message.from_user.first_name}!\nIltimos, o'qish kursingizni tanlang:",
        reply_markup=get_courses_menu(), parse_mode="HTML"
    )

@dp.message(F.text.in_({"🔒 2-kurs", "🔒 3-kurs", "🔒 4-kurs"}))
async def locked_courses(message: types.Message):
    if not is_allowed(message.from_user.id): return
    await message.answer("🚧 <b>Ushbu kurs testlari yaqin kunlarda tizimga to'liq qo'shiladi!</b>", parse_mode="HTML")

@dp.message(F.text == "🎓 1-kurs")
async def show_1st_year_subjects(message: types.Message):
    if not is_allowed(message.from_user.id): return
    if not is_vip(message.from_user.id):
        return await cmd_start(message)
        
    await message.answer("📚 <b>1-kurs fanlari ro'yxati:</b>\nKanalizatsiya qilingan fanlardan birini tanlang:", reply_markup=get_subjects_menu(), parse_mode="HTML")

@dp.message(F.text == "⬅️ Kurslar ro'yxatiga qaytish")
async def back_to_courses(message: types.Message):
    if not is_allowed(message.from_user.id): return
    await message.answer("🎓 O'quv kursingizni tanlang:", reply_markup=get_courses_menu())

@dp.message(F.text.startswith("📚 "))
async def choose_count(message: types.Message):
    if not is_allowed(message.from_user.id): return
    if not is_vip(message.from_user.id):
        return await cmd_start(message)
    
    subject_name = message.text.replace("📚 ", "").strip()
    file_path = SUBJECTS.get(subject_name)

    try:
        if subject_name == "Dasturlash": 
            all_tests = get_quizzes_programming(file_path)
        elif subject_name == "Ingliz tili-{KIN}":
            all_tests = get_quizzes_english_pdf_docx(file_path, ENGLISH_PDF_PATH)
        elif subject_name == "Fizika":
            all_tests = get_quizzes_by_letters(file_path, ANSWERS_JSON_PATH) 
        else: 
            all_tests = get_quizzes(file_path)
            
        if not all_tests: 
            return await message.answer("⚠️ Savollar topilmadi.")

        total_count = len(all_tests)
        builder = ReplyKeyboardBuilder()
        for count in [20, 25, 30, 50, 100]:
            if count <= total_count: 
                builder.add(types.KeyboardButton(text=f"⚙️ {subject_name}:{count}"))

        builder.add(types.KeyboardButton(text=f"🚀 {subject_name} - Barchasi ({total_count})"))
        
        if subject_name == "Ingliz tili-{KIN}":
            builder.add(types.KeyboardButton(text=f"📋 {subject_name} - Javoblar"))
        
        builder.add(types.KeyboardButton(text="⬅️ Orqaga"))
        builder.adjust(2)

        await message.answer(
            f"🎯 <b>Fan:</b> {subject_name}\n📊 <b>Jami:</b> {total_count} ta", 
            reply_markup=builder.as_markup(resize_keyboard=True), 
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"choose_count xatosi: {e}")
        await message.answer("❌ Ma'lumotlarni o'qishda xatolik.")

@dp.message(F.text == "⬅️ Orqaga")
async def back_to_home(message: types.Message): 
    await show_1st_year_subjects(message)

@dp.message(F.text.startswith("📋 "))
async def show_all_answers(message: types.Message):
    if not is_allowed(message.from_user.id): return
    if not is_vip(message.from_user.id): return await cmd_start(message)
    
    subject_name = message.text.replace("📋 ", "").replace(" - Javoblar", "").strip()
    
    if subject_name == "Ingliz tili-{KIN}":
        try:
            file_path = SUBJECTS[subject_name]
            all_tests = get_quizzes_english_pdf_docx(file_path, ENGLISH_PDF_PATH)
            
            if not all_tests:
                return await message.answer("⚠️ Javoblar topilmadi.")
            
            answer_text = f"📋 <b>{subject_name} - Barcha javoblar</b>\n\n"
            
            for idx, test in enumerate(all_tests, 1):
                correct_option = test['options'][test['correct']]
                pdf_answer = test.get('pdf_answer', '')
                
                answer_text += f"{idx}. <b>{correct_option}</b>"
                if pdf_answer:
                    answer_text += f" ({pdf_answer})"
                answer_text += "\n"
                
                if idx % 50 == 0 and idx < len(all_tests):
                    await message.answer(answer_text, parse_mode="HTML")
                    answer_text = ""
                    await asyncio.sleep(0.5)
            
            if answer_text:
                await message.answer(answer_text, parse_mode="HTML")
                
        except Exception as e:
            logging.error(f"show_all_answers xatosi: {e}")
            await message.answer("❌ Javoblarni ko'rsatishda xatolik.")

@dp.message(F.text.startswith("⚙️ ") | F.text.startswith("🚀 "))
async def init_quiz(message: types.Message):
    if not is_allowed(message.from_user.id): return
    if not is_vip(message.from_user.id): return await cmd_start(message)

    try:
        if message.text.startswith("🚀 "):
            subject = message.text.split("🚀 ")[1].split(" - ")[0].strip()
            count = int(re.search(r"\((\d+)\)", message.text).group(1))
        else:
            raw = message.text.replace("⚙️ ", "")
            subject, c = raw.split(":")
            count = int(c)

        file_path = SUBJECTS[subject]
        
        if subject == "Dasturlash": 
            all_tests = get_quizzes_programming(file_path)
        elif subject == "Ingliz tili-{KIN}":
            all_tests = get_quizzes_english_pdf_docx(file_path, ENGLISH_PDF_PATH)
        elif subject == "Fizika":
            all_tests = get_quizzes_by_letters(file_path, ANSWERS_JSON_PATH) 
        else: 
            all_tests = get_quizzes(file_path)
            
        if not all_tests:
            return await message.answer("⚠️ Testlar yuklanmadi!")
            
        selected = random.sample(all_tests, min(count, len(all_tests)))
        user_sessions[message.from_user.id] = {
            "subject": subject, 
            "tests": selected, 
            "current_index": 0,
            "correct_answers": 0, 
            "current_poll_id": None
        }

        builder = ReplyKeyboardBuilder()
        builder.add(types.KeyboardButton(text="🛑 Testni to'xtatish"))
        if subject == "Ingliz tili-{KIN}":
            builder.add(types.KeyboardButton(text="👁️ Javobni ko'rish"))
        builder.adjust(1)

        await message.answer(
            f"🚀 <b>{subject}</b> boshlandi!", 
            reply_markup=builder.as_markup(resize_keyboard=True), 
            parse_mode="HTML"
        )
        await send_next_test(message.from_user.id)
    except Exception as e: 
        logging.error(f"init_quiz xatosi: {e}")
        await message.answer("❌ Xatolik yuz berdi.")

@dp.message(F.text == "👁️ Javobni ko'rish")
async def show_current_answer(message: types.Message):
    user_id = message.from_user.id
    session = user_sessions.get(user_id)
    
    if not session:
        return await message.answer("⚠️ Hozirda test ishlamayapti.")
    
    if session["subject"] != "Ingliz tili-{KIN}":
        return await message.answer("⚠️ Bu funksiya faqat Ingliz tili-{KIN} uchun mavjud.")
    
    idx = session["current_index"]
    if idx >= len(session["tests"]):
        return await message.answer("⚠️ Test tugagan.")
    
    current_test = session["tests"][idx]
    pdf_answer = current_test.get('pdf_answer', 'Topilmadi')
    correct_option = current_test['options'][current_test['correct']]
    
    await message.answer(
        f"👁️ <b>Joriy savol javobi:</b>\n\n"
        f"✅ To'g'ri javob: <b>{correct_option}</b>\n"
        f"📄 PDF dan: <code>{pdf_answer}</code>",
        parse_mode="HTML"
    )

# =========================================================
# CORE LOGIC: SEND NEXT TEST
# =========================================================
async def send_next_test(user_id):
    session = user_sessions.get(user_id)
    if not session: return

    idx, tests = session["current_index"], session["tests"]
    if idx >= len(tests): return await show_results(user_id)

    q = tests[idx]
    
    try:
        if not q.get("options") or len(q["options"]) < 2:
            raise ValueError("Variantlar yetarli emas yoki xato formatlangan.")

        options = [str(opt)[:100] for opt in q["options"]]
        correct_text = options[q["correct"]]
        random.shuffle(options)
        correct_id = options.index(correct_text)
        session["current_correct_id"] = correct_id

        q_text = format_quiz_text(q['question'].strip())
        
        if len(q_text) > 250:
            await bot.send_message(user_id, f"<b>Savol {idx + 1}/{len(tests)}:</b>\n\n{q_text}", parse_mode="HTML")
            poll_q = "To'g'ri javobni tanlang:"
        else:
            poll_q = f"({idx + 1}/{len(tests)}) {q['question']}"

        poll = await bot.send_poll(
            chat_id=user_id, 
            question=poll_q[:300], 
            options=options,
            correct_option_id=correct_id, 
            type="quiz", 
            is_anonymous=False, 
            open_period=QUIZ_TIME
        )
        session["current_poll_id"] = poll.poll.id

    except Exception as e:
        logging.error(f"Test yuborishda xatolik (Savol #{idx+1}): {e}")
        
        err_msg = (
            f"⚠️ <b>Xato test aniqlandi va o'tkazib yuborildi!</b>\n"
            f"📝 <b>Savol {idx + 1}:</b> <i>{q.get('question', 'Matn yoqi')}</i>\n"
            f"❌ <b>Xatolik sababi:</b> <code>{str(e)}</code>"
        )
        try:
            await bot.send_message(user_id, err_msg, parse_mode="HTML")
        except:
            pass
            
        session["current_index"] += 1
        await asyncio.sleep(1.0)
        await send_next_test(user_id)

@dp.poll_answer()
async def handle_poll_answer(poll_answer: types.PollAnswer):
    user_id = poll_answer.user.id
    session = user_sessions.get(user_id)
    if not session or poll_answer.poll_id != session["current_poll_id"]: return

    if poll_answer.option_ids[0] == session["current_correct_id"]:
        session["correct_answers"] += 1
        try: 
            await bot.send_message(user_id, random.choice(SUCCESS_MESSAGES), message_effect_id=FIREWORK_EFFECT)
        except: 
            pass
    else:
        await bot.send_message(user_id, "❌ Noto'g'ri javob!")

    session["current_index"] += 1
    await asyncio.sleep(1.2)
    await send_next_test(user_id)

async def show_results(user_id):
    session = user_sessions.get(user_id)
    if not session: return
    correct, total = session["correct_answers"], len(session["tests"])
    score = (correct / total) * 40

    await bot.send_message(
        user_id, 
        f"🏁 <b>YAKUNLANDI</b>\n✅ To'g'ri: {correct}\n🏆 Ball: {score:.1f}/40",
        parse_mode="HTML", 
        reply_markup=get_subjects_menu()
    )
    user_sessions.pop(user_id, None)

@dp.message(F.text == "🛑 Testni to'xtatish")
async def stop_quiz(message: types.Message):
    user_sessions.pop(message.from_user.id, None)
    await message.answer("🛑 Test to'xtatildi.", reply_markup=get_subjects_menu())


# =========================================================
# WEB SERVER & MAIN RUNNER (Railway Port moslashuvi)
# =========================================================
async def handle_home(request):
    return web.Response(text="Bot is running smoothly on Polling mode with custom HTTP bridge!")

async def main():
    logging.info("--- Bot ishga tushirilmoqda ---")
    
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("--- Eski Webhook muvaffaqiyatli o'chirildi (Conflict hal etildi) ---")
    
    asyncio.create_task(dp.start_polling(bot))
    
    app = web.Application()
    app.router.add_get("/", handle_home)
    
    port = int(os.environ.get("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    
    logging.info(f"--- Veb server {port}-portda ishga tushdi ---")
    await site.start()
    
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot to'xtatildi.")