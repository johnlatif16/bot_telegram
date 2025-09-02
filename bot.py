import asyncio
import logging
import os
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# تحميل المتغيرات من ملف .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# إعداد الـ logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# تهيئة Firebase
import json, os
cred = credentials.Certificate(json.loads(os.environ["FIREBASE_CREDENTIALS"]))
firebase_admin.initialize_app(cred)
db = firestore.client()

registered_students = {}  # لتخزين user_id لكل رقم قومي
sent_results = set()      # لتخزين الأرقام القومية التي تم إرسال نتائجها

# رسالة الترحيب
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        '👋 أهلاً بك! أرسل رقمك القومي لتخزين بياناتك واستلام نتيجتك تلقائيًا.'
    )

# دالة إرسال النتيجة
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
    for subj in result['mainSubjects']:
        msg += f"{subj['name']}: {subj['score']} / {subj['outOf']}\n"

    msg += "\n📌 المواد الإضافية:\n"
    for subj in result['additionalSubjects']:
        msg += f"{subj['name']}: {subj['score']} / {subj['outOf']}\n"

    msg += f"\nالمجموع: {result['totalScore']} / {result['totalOutOf']}\n"
    msg += f"النسبة: {result['percentage']}%"
    await bot.send_message(chat_id=user_id, text=msg)

# حفظ الرقم القومي أو إرسال النتيجة
async def save_national_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    national_id = update.message.text.strip()
    user_id = update.message.from_user.id

    # التحقق من وجود الطالب في Firebase
    student_ref = db.collection("students").document(national_id)
    student_doc = student_ref.get()
    if not student_doc.exists:
        await update.message.reply_text(
            "❌ الرقم القومي غير موجود، برجاء التحدث مع المطور https://wa.me/201274445091"
        )
        return

    student = student_doc.to_dict()
    registered_students[national_id] = user_id

    # التحقق من النتيجة في Firebase
    result_ref = db.collection("results").document(national_id)
    result_doc = result_ref.get()
    if result_doc.exists and national_id not in sent_results:
        await send_result_message(user_id, result_doc.to_dict(), context.bot)
        sent_results.add(national_id)
        logging.info(f"📩 تم إرسال النتيجة للطالب {national_id} فورًا بعد التسجيل")
        return

    msg = f"""✅ تم تخزين الرقم القومي الخاص بك: {national_id}

بياناتك هي:
الاسم: {student["name"]}
المدرسة: {student["school"]}
الإدارة: {student["admin"]}
المحافظة: {student["governorate"]}
"""
    await update.message.reply_text(msg)

# مراقبة النتائج الجديدة في Firebase
def on_snapshot(col_snapshot, changes, read_time, app):
    for change in changes:
        if change.type.name == 'ADDED' or change.type.name == 'MODIFIED':
            national_id = change.document.id
            result = change.document.to_dict()
            if national_id in registered_students and national_id not in sent_results:
                user_id = registered_students[national_id]
                asyncio.run(send_result_message(user_id, result, app.bot))
                sent_results.add(national_id)
                logging.info(f"📩 تم إرسال النتيجة للطالب {national_id} من Firebase")

async def post_init(app: Application):
    results_ref = db.collection("results")
    results_ref.on_snapshot(lambda col_snapshot, changes, read_time: on_snapshot(col_snapshot, changes, read_time, app))

def main():
    if not BOT_TOKEN:
        raise ValueError("❌ BOT_TOKEN غير موجود في ملف .env")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_national_id))
    app.run_polling()

if __name__ == "__main__":
    main()
