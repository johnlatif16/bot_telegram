import os
import asyncio
import logging
import tempfile
from functools import partial
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import firebase_admin
from firebase_admin import credentials, firestore

# -------------------- إعداد البيئة --------------------
load_dotenv()  # يقرأ .env من نفس مجلد التشغيل
BOT_TOKEN = os.getenv("BOT_TOKEN")
FIREBASE_KEY_PATH = os.getenv("FIREBASE_KEY_PATH")         # مسار ملف json للمفتاح
FIREBASE_KEY_JSON = os.getenv("FIREBASE_KEY_JSON")         # بديل: محتوى JSON كاملاً (إن رغبت)
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))     # بالثواني

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN غير موجود في ملف .env")

# إذا أعطينا محتوى JSON بدلاً من ملف، احفظه مؤقتاً
if not FIREBASE_KEY_PATH and FIREBASE_KEY_JSON:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    tmp.write(FIREBASE_KEY_JSON.encode("utf-8"))
    tmp.flush()
    FIREBASE_KEY_PATH = tmp.name

if not FIREBASE_KEY_PATH:
    raise ValueError("❌ FIREBASE_KEY_PATH غير موجود في ملف .env أو FIREBASE_KEY_JSON لم يُعطَ")

# -------------------- إعداد Logging --------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# -------------------- تهيئة Firebase --------------------
if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_KEY_PATH)
    firebase_admin.initialize_app(cred)
db = firestore.client()

# -------------------- حالة في الذاكرة --------------------
registered_students: dict[str, int] = {}  # national_id -> telegram_user_id
notified_results: set[str] = set()        # national_id التي تم إرسال نتيجتها

# -------------------- دوال مساعدة (تستخدم run_in_executor لعدم حجب حلقة asyncio) ----
async def _run_blocking(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))

async def load_persistent_state():
    """يحمّل التسجيلات والإشعارات من Firestore إلى الذاكرة عند بدء التشغيل."""
    global registered_students, notified_results
    try:
        docs = await _run_blocking(lambda: list(db.collection('registered_students').stream()))
        for d in docs:
            data = d.to_dict() or {}
            uid = data.get('user_id')
            if uid:
                registered_students[d.id] = uid

        docs = await _run_blocking(lambda: list(db.collection('notifications').stream()))
        for d in docs:
            notified_results.add(d.id)

        logger.info(f"Loaded {len(registered_students)} registered students and {len(notified_results)} notifications.")
    except Exception as e:
        logger.exception("فشل في تحميل الحالة من Firestore: %s", e)

async def save_registered_student(national_id: str, user_id: int):
    """يحفظ التسجيل في Firestore ويحدّث الذاكرة."""
    registered_students[national_id] = user_id
    try:
        await _run_blocking(lambda: db.collection('registered_students').document(national_id).set({
            "user_id": user_id,
            "registered_at": firestore.SERVER_TIMESTAMP
        }))
    except Exception:
        logger.exception("فشل في حفظ registered_students إلى Firestore")

async def mark_notified(national_id: str, user_id: int):
    """توثيق أن الإشعار أُرسل (في Firestore وفي الذاكرة)."""
    notified_results.add(national_id)
    try:
        await _run_blocking(lambda: db.collection('notifications').document(national_id).set({
            "user_id": user_id,
            "sent_at": firestore.SERVER_TIMESTAMP
        }))
    except Exception:
        logger.exception("فشل في حفظ notification إلى Firestore")

async def get_student_from_db(national_id: str):
    """يجلب بيانات الطالب من مجموعة 'students' إن وجدت."""
    try:
        doc = await _run_blocking(lambda: db.collection('students').document(national_id).get())
        if doc.exists:
            return doc.to_dict()
        return None
    except Exception:
        logger.exception("فشل في جلب بيانات الطالب من Firestore")
        return None

async def get_result_from_db(national_id: str):
    try:
        doc = await _run_blocking(lambda: db.collection('results').document(national_id).get())
        if doc.exists:
            return doc.to_dict()
        return None
    except Exception:
        logger.exception("فشل في جلب النتيجة من Firestore")
        return None

# -------------------- دوال البوت --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        '👋 أهلاً! أرسل رقمك القومي (مثلاً 14 رقم) لتسجيله واستلام نتيجتك تلقائيًا.'
    )

async def send_result_message(user_id: int, result: dict, bot):
    """يشكّل ويرسل رسالة النتيجة للشخص."""
    try:
        msg = [
            "🎓 نتيجتك:",
            f"الرقم القومي: {result.get('nationalID', '')}",
            f"الاسم: {result.get('name', '')}",
            f"المرحلة: {result.get('stage', '')}",
            f"الصف: {result.get('gradeLevel', '')}",
            f"الإدارة: {result.get('educationDept', '')}",
            f"المدرسة: {result.get('schoolName', '')}",
            f"ملاحظات: {result.get('notes', '')}",
            "",
            "📌 المواد الأساسية:"
        ]
        for subj in result.get('mainSubjects', []) or []:
            msg.append(f"{subj.get('name','')}: {subj.get('score','')} / {subj.get('outOf','')}")
        msg.append("\n📌 المواد الإضافية:")
        for subj in result.get('additionalSubjects', []) or []:
            msg.append(f"{subj.get('name','')}: {subj.get('score','')} / {subj.get('outOf','')}")
        msg.append(f"\nالمجموع: {result.get('totalScore','')} / {result.get('totalOutOf','')}")
        msg.append(f"النسبة: {result.get('percentage','')}%")
        text = "\n".join(msg)
        await bot.send_message(chat_id=user_id, text=text)
    except Exception:
        logger.exception("فشل في إرسال رسالة النتيجة إلى user_id=%s", user_id)

async def handle_national_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    national_id = update.message.text.strip()
    user_id = update.message.from_user.id

    # فحص سريع لصيغة الرقم القومي (تعديل بحسب نظامك إن أردت)
    if not national_id.isdigit() or len(national_id) < 10:
        await update.message.reply_text("الرقم الظاهر غير صحيح. تأكد من إدخال رقم قومي صالح (أرقام فقط).")
        return

    student = await get_student_from_db(national_id)
    if not student:
        await update.message.reply_text(
            "الرقم القومي غير موجود في قاعدة البيانات، برجاء التحدث مع المطوّر: https://wa.me/201274445091"
        )
        return

    # خزّن التسجيل في Firestore والذاكرة
    await save_registered_student(national_id, user_id)

    # حاول إرسال النتيجة فوراً إن كانت موجودة ولم تُرسل من قبل
    result = await get_result_from_db(national_id)
    if result and national_id not in notified_results:
        await send_result_message(user_id, result, context.bot)
        await mark_notified(national_id, user_id)
        logger.info("تم إرسال النتيجة للطالب بالرقم القومي %s فور التسجيل", national_id)
        return

    # رسالة تأكيد التسجيل
    msg = (
        "✅ تم تسجيلك بنجاح!\n"
        f"الاسم: {student.get('name','')}\n"
        f"المدرسة: {student.get('school','')}\n"
        f"الإدارة: {student.get('admin','')}\n"
        f"المحافظة: {student.get('governorate','')}\n"
        f"الرقم القومي: {national_id}\n"
    )
    await update.message.reply_text(msg)

# -------------------- مهمة background لمراقبة النتائج --------------------
async def check_results_task(app: Application):
    logger.info("Starting background results checker (poll every %s s)", POLL_INTERVAL)
    while True:
        try:
            # جلب كل الوثائق في مجموعة النتائج (يُشغل في ThreadPool لتجنّب الحجب)
            docs = await _run_blocking(lambda: list(db.collection('results').stream()))
            for d in docs:
                national_id = d.id
                if national_id in registered_students and national_id not in notified_results:
                    result = d.to_dict()
                    user_id = registered_students[national_id]
                    # جدولة إرسال الرسالة (نستخدم create_task على app لكي تعمل ضمن حلقة الـ PTB)
                    await app.bot.send_message(chat_id=user_id, text="⏳ تم العثور على نتيجتك، جارٍ إرسال التفاصيل...")
                    await send_result_message(user_id, result, app.bot)
                    await mark_notified(national_id, user_id)
                    logger.info("تم إرسال النتيجة للطالب بالرقم القومي %s (background)", national_id)
        except Exception:
            logger.exception("خطأ في مهمة فحص النتائج الخلفية")
        await asyncio.sleep(POLL_INTERVAL)

# -------------------- post_init لتشغيل المراقب --------------------
async def post_init(app: Application):
    await load_persistent_state()
    # ابدأ المهمة الخلفية (تعمل على نفس حلقة التطبيق)
    app.create_task(check_results_task(app))

# -------------------- main --------------------
def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_national_id))
    app.run_polling()

if __name__ == "__main__":
    main()
