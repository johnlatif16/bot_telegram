import os
import asyncio
import logging
import json
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import firebase_admin
from firebase_admin import credentials, firestore

# -------------------- إعداد البيئة --------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
FIREBASE_CONFIG = os.getenv("FIREBASE_CONFIG")  # JSON كامل من متغير البيئة

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN غير موجود في ملف .env")
if not FIREBASE_CONFIG:
    raise ValueError("❌ FIREBASE_CONFIG فارغ!")

# -------------------- إعداد Logging --------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# -------------------- تهيئة Firebase --------------------
try:
    cred_dict = json.loads(FIREBASE_CONFIG)
except json.JSONDecodeError as e:
    raise ValueError("❌ FIREBASE_CONFIG غير صالح JSON!") from e

cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

# -------------------- تخزين البيانات في الذاكرة --------------------
registered_students = {}  # user_id لكل رقم قومي
sent_results = set()      # الأرقام القومية التي تم إرسال نتائجها

# -------------------- دوال Firebase --------------------
def get_student(national_id):
    doc = db.collection('students').document(national_id).get()
    return doc.to_dict() if doc.exists else None

def register_student(national_id, user_id):
    db.collection('registered_students').document(national_id).set({
        "user_id": user_id
    })
    registered_students[national_id] = user_id

def get_result(national_id):
    doc = db.collection('results').document(national_id).get()
    return doc.to_dict() if doc.exists else None

# -------------------- دوال البوت --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        '👋 أهلاً بك! أرسل رقمك القومي لتخزين بياناتك واستلام نتيجتك تلقائيًا.'
    )

async def send_result_message(user_id, result, bot):
    msg = f"""🎓 نتيجتك:

الرقم القومي: {result['nationalID']}
الاسم: {result['name']}
المرحلة: {result['stage']}
الصف: {result['gradeLevel']}
الإدارة: {result['educationDept']}
المدرسة: {result['schoolName']}
ملاحظات: {result['notes']}

📌 المواد الأساسية:
"""
    for subj in result.get('mainSubjects', []):
        msg += f"{subj['name']}: {subj['score']} / {subj['outOf']}\n"

    msg += "\n📌 المواد الإضافية:\n"
    for subj in result.get('additionalSubjects', []):
        msg += f"{subj['name']}: {subj['score']} / {subj['outOf']}\n"

    msg += f"\nالمجموع: {result['totalScore']} / {result['totalOutOf']}\n"
    msg += f"النسبة: {result['percentage']}%"
    await bot.send_message(chat_id=user_id, text=msg)

async def save_national_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    national_id = update.message.text.strip()
    user_id = update.message.from_user.id

    student = get_student(national_id)
    if not student:
        await update.message.reply_text(
            "الرقم القومي غير موجود، برجاء التحدث مع المطور https://wa.me/201274445091"
        )
        return

    register_student(national_id, user_id)

    result = get_result(national_id)
    if result and national_id not in sent_results:
        await send_result_message(user_id, result, context.bot)
        sent_results.add(national_id)
        logging.info(f"تم إرسال النتيجة للطالب بالرقم القومي {national_id} فورًا بعد التسجيل")
    else:
        # لو النتيجة مش موجودة بعد
        msg = f"""✅ تم بنجاح تخزين الرقم القومي الخاص بك وهو: {national_id}

بياناتك هي:
الاسم: {student.get('name', '')}
المدرسة: {student.get('school', '')}
الإدارة: {student.get('admin', '')}
المحافظة: {student.get('governorate', '')}
الرقم القومي: {national_id}
"""
        await update.message.reply_text(msg)

# -------------------- مراقبة النتائج الجديدة --------------------
def monitor_results(app: Application):
    results_ref = db.collection('results')

    def on_snapshot(col_snapshot, changes, read_time):
        for change in changes:
            if change.type.name in ('ADDED', 'MODIFIED'):
                national_id = change.document.id
                result = change.document.to_dict()
                if national_id in registered_students and national_id not in sent_results:
                    user_id = registered_students[national_id]
                    asyncio.create_task(send_result_message(user_id, result, app.bot))
                    sent_results.add(national_id)
                    logging.info(f"تم إرسال النتيجة للطالب بالرقم القومي {national_id}")

    results_ref.on_snapshot(on_snapshot)

# -------------------- post_init لتشغيل المراقب --------------------
async def post_init(app: Application):
    monitor_results(app)

# -------------------- main --------------------
def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_national_id))
    app.run_polling()

if __name__ == "__main__":
    main()
