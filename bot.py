import os
import json
import asyncio
import logging
from functools import partial
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import firebase_admin
from firebase_admin import credentials, firestore

# -------------------- إعداد البيئة --------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
FIREBASE_KEY_JSON = os.getenv("FIREBASE_KEY_JSON")
FIREBASE_KEY_PATH = os.getenv("FIREBASE_KEY_PATH")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN غير موجود في ملف .env")

if not FIREBASE_KEY_JSON and not FIREBASE_KEY_PATH:
    raise ValueError("❌ يجب تحديد FIREBASE_KEY_JSON أو FIREBASE_KEY_PATH في ملف .env")

# -------------------- تهيئة Firebase --------------------
if not firebase_admin._apps:
    if FIREBASE_KEY_JSON:
        service_account_info = json.loads(FIREBASE_KEY_JSON)
        if "private_key" in service_account_info:
            service_account_info["private_key"] = service_account_info["private_key"].replace("\\n", "\n")
        cred = credentials.Certificate(service_account_info)
    else:
        cred = credentials.Certificate(FIREBASE_KEY_PATH)
    firebase_admin.initialize_app(cred)

db = firestore.client()

# -------------------- إعداد Logging --------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# -------------------- حالة في الذاكرة --------------------
registered_students: dict[str, int] = {}  # national_id -> telegram_user_id
notified_results: set[str] = set()        # national_id التي تم إرسال نتيجتها

# -------------------- دوال Firestore (async-safe) --------------------
async def _run_blocking(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))

async def load_persistent_state():
    global registered_students, notified_results
    try:
        docs = await _run_blocking(lambda: list(db.collection("registered_students").stream()))
        for d in docs:
            data = d.to_dict() or {}
            uid = data.get("user_id")
            if uid:
                registered_students[d.id] = uid

        docs = await _run_blocking(lambda: list(db.collection("notifications").stream()))
        for d in docs:
            notified_results.add(d.id)

        logger.info("Loaded %d registered students and %d notifications.",
                    len(registered_students), len(notified_results))
    except Exception as e:
        logger.exception("فشل تحميل الحالة من Firestore: %s", e)

async def save_registered_student(national_id: str, user_id: int):
    registered_students[national_id] = user_id
    try:
        await _run_blocking(lambda: db.collection("registered_students").document(national_id).set({
            "user_id": user_id,
            "registered_at": firestore.SERVER_TIMESTAMP
        }))
    except Exception:
        logger.exception("فشل في حفظ registered_students إلى Firestore")

async def mark_notified(national_id: str, user_id: int):
    notified_results.add(national_id)
    try:
        await _run_blocking(lambda: db.collection("notifications").document(national_id).set({
            "user_id": user_id,
            "sent_at": firestore.SERVER_TIMESTAMP
        }))
    except Exception:
        logger.exception("فشل في حفظ notification إلى Firestore")

async def get_student_from_db(national_id: str):
    try:
        doc = await _run_blocking(lambda: db.collection("students").document(national_id).get())
        return doc.to_dict() if doc.exists else None
    except Exception:
        logger.exception("فشل في جلب بيانات الطالب من Firestore")
        return None

async def get_result_from_db(national_id: str):
    try:
        doc = await _run_blocking(lambda: db.collection("results").document(national_id).get())
        return doc.to_dict() if doc.exists else None
    except Exception:
        logger.exception("فشل في جلب النتيجة من Firestore")
        return None

# -------------------- دوال البوت --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً! أرسل رقمك القومي (14 رقم) أو رقم جلوسك لتسجيله واستلام نتيجتك تلقائيًا."
    )

async def send_result_message(user_id: int, result: dict, bot):
    try:
        msg = [
            "🎓 نتيجتك:",
            f"الاسم: {result.get('name', '')}",
            f"المرحلة: {result.get('stage', '')}",
            f"الصف: {result.get('gradeLevel', '')}",
            f"الإدارة: {result.get('educationDept', '')}",
            f"المدرسة: {result.get('schoolName', '')}",
            f"ملاحظات: {result.get('notes', '')}",
            "",
            "📌 المواد الأساسية:"
        ]
        for subj in result.get("mainSubjects", []) or []:
            msg.append(f"{subj.get('name','')}: {subj.get('score','')} / {subj.get('outOf','')}")
        msg.append("\n📌 المواد الإضافية:")
        for subj in result.get("additionalSubjects", []) or []:
            msg.append(f"{subj.get('name','')}: {subj.get('score','')} / {subj.get('outOf','')}")
        msg.append(f"\nالمجموع: {result.get('totalScore','')} / {result.get('totalOutOf','')}")
        msg.append(f"النسبة: {result.get('percentage','')}%")

        text = "\n".join(msg)
        await bot.send_message(chat_id=user_id, text=text)
    except Exception:
        logger.exception("فشل في إرسال رسالة النتيجة إلى user_id=%s", user_id)

async def handle_student_identifier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    identifier = update.message.text.strip()
    user_id = update.message.from_user.id

    student = None
    national_id = None
    is_national_id = False

    # ✅ لو دخل 14 رقم -> اعتبره رقم قومي
    if identifier.isdigit() and len(identifier) == 14:
        doc = await _run_blocking(lambda: db.collection("students").document(identifier).get())
        if doc.exists:
            student = doc.to_dict()
            national_id = doc.id
            is_national_id = True

    # ✅ لو مش رقم قومي -> ابحث بالـ seatNumber
    if not student:
        docs = await _run_blocking(lambda: db.collection("students")
                                   .where("seatNumber", "==", identifier).stream())
        for d in docs:
            student = d.to_dict()
            national_id = d.id   # الرقم القومي
            is_national_id = False
            break

    if not student or not national_id:
        await update.message.reply_text("⚠️ لم يتم العثور على الطالب. تأكد من الرقم القومي أو رقم الجلوس.")
        return

    # سجل الطالب
    await save_registered_student(national_id, user_id)

    # لو فيه نتيجة ابعتها
    result = await get_result_from_db(national_id)
    if result and national_id not in notified_results:
        await send_result_message(user_id, result, context.bot)
        await mark_notified(national_id, user_id)
        return

    # ✅ الرسالة حسب نوع الإدخال
    if is_national_id:
        msg = (
            "✅ تم تسجيلك بنجاح!\n"
            f"الاسم: {student.get('name','')}\n"
            f"المدرسة: {student.get('school','')}\n"
            f"الإدارة: {student.get('admin','')}\n"
            f"المحافظة: {student.get('governorate','')}\n"
            f"الرقم القومي: {national_id}\n"
        )
    else:
        msg = (
            "✅ تم تسجيلك بنجاح!\n"
            f"الاسم: {student.get('name','')}\n"
            f"المدرسة: {student.get('school','')}\n"
            f"الإدارة: {student.get('admin','')}\n"
            f"المحافظة: {student.get('governorate','')}\n"
            f"رقم الجلوس: {student.get('seatNumber','')}\n"
        )

    await update.message.reply_text(msg)

# -------------------- مهمة background لفحص النتائج --------------------
async def check_results_task(app: Application):
    logger.info("بدء مهمة فحص النتائج كل %s ثانية", POLL_INTERVAL)
    while True:
        try:
            docs = await _run_blocking(lambda: list(db.collection("results").stream()))
            for d in docs:
                national_id = d.id
                if national_id in registered_students and national_id not in notified_results:
                    result = d.to_dict()
                    user_id = registered_students[national_id]
                    await send_result_message(user_id, result, app.bot)
                    await mark_notified(national_id, user_id)
                    logger.info("📤 تم إرسال النتيجة للطالب %s (background)", national_id)
        except Exception:
            logger.exception("خطأ في مهمة فحص النتائج الخلفية")
        await asyncio.sleep(POLL_INTERVAL)

# -------------------- post_init --------------------
async def post_init(app: Application):
    await load_persistent_state()
    app.create_task(check_results_task(app))

# -------------------- main --------------------
def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_student_identifier))
    app.run_polling()

if __name__ == "__main__":
    main()
