import json
import asyncio
import logging
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import firebase_admin
from firebase_admin import credentials, firestore

# تحميل المتغيرات من .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
FIREBASE_CREDENTIALS = os.getenv("FIREBASE_CREDENTIALS")  # محتوى JSON كـ string

# تهيئة Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate(json.loads(FIREBASE_CREDENTIALS))
    firebase_admin.initialize_app(cred)

# Firestore client
db = firestore.client()

# مراجع لمجموعتين (collections): students و results
students_ref = db.collection("students")
results_ref = db.collection("results")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

registered_students = {}
sent_results = set()

# رسالة الترحيب
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        '👋 أهلاً بك! أرسل رقمك القومي لتخزين بياناتك واستلام نتيجتك تلقائيًا.'
    )

# إرسال نتيجة
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

# تخزين الرقم القومي
async def save_national_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    national_id = update.message.text.strip()
    user_id = update.message.from_user.id

    student_doc = students_ref.document(national_id).get()
    if not student_doc.exists:
        await update.message.reply_text(
            "الرقم القومي غير موجود، برجاء التحدث مع المطور https://wa.me/201274445091"
        )
        return

    student = student_doc.to_dict()
    registered_students[national_id] = user_id

    # لو النتيجة موجودة
    result_doc = results_ref.document(national_id).get()
    if result_doc.exists and national_id not in sent_results:
        await send_result_message(user_id, result_doc.to_dict(), context.bot)
        sent_results.add(national_id)
        logging.info(f"تم إرسال النتيجة للطالب {national_id} فورًا بعد التسجيل")
        return

    # رسالة تخزين بيانات
    msg = f"""✅ تم بنجاح تخزين الرقم القومي الخاص بك وهو: {national_id}

بياناتك هي:
الاسم: {student["name"]}
المدرسة: {student["school"]}
الإدارة: {student["admin"]}
المحافظة: {student["governorate"]}
الرقم القومي: {national_id}
"""
    await update.message.reply_text(msg)

# متابعة النتائج الجديدة
async def monitor_results(app: Application):
    while True:
        results = results_ref.stream()
        for doc in results:
            national_id = doc.id
            result = doc.to_dict()
            if national_id in registered_students and national_id not in sent_results:
                user_id = registered_students[national_id]
                await send_result_message(user_id, result, app.bot)
                sent_results.add(national_id)
                logging.info(f"تم إرسال النتيجة للطالب {national_id}")
        await asyncio.sleep(2)

# post_init
async def post_init(app: Application):
    asyncio.create_task(monitor_results(app))

def main():
    if not BOT_TOKEN:
        raise ValueError("❌ BOT_TOKEN غير موجود في ملف .env")
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_national_id))
    app.run_polling()

if __name__ == "__main__":
    main()
