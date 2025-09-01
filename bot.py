import json
import asyncio
import logging
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

import firebase_admin
from firebase_admin import credentials, firestore

# تحميل المتغيرات من ملف .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
FIREBASE_CONFIG = os.getenv("FIREBASE_CONFIG")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# تهيئة Firebase من FIREBASE_CONFIG
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN غير موجود في ملف .env")

if not FIREBASE_CONFIG:
    raise ValueError("❌ FIREBASE_CONFIG غير موجود في ملف .env")

if not firebase_admin._apps:
    cred = credentials.Certificate(json.loads(FIREBASE_CONFIG))
    firebase_admin.initialize_app(cred)

db = firestore.client()

registered_students = {}  # user_id لكل رقم قومي
sent_results = set()      # الأرقام القومية اللي اتبعتت نتائجها


# رسالة الترحيب
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً بك! أرسل رقمك القومي لتخزين بياناتك واستلام نتيجتك تلقائيًا."
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
    for subj in result["mainSubjects"]:
        msg += f"{subj['name']}: {subj['score']} / {subj['outOf']}\n"

    msg += "\n📌 المواد الإضافية:\n"
    for subj in result["additionalSubjects"]:
        msg += f"{subj['name']}: {subj['score']} / {subj['outOf']}\n"

    msg += f"\nالمجموع: {result['totalScore']} / {result['totalOutOf']}\n"
    msg += f"النسبة: {result['percentage']}%"

    await bot.send_message(chat_id=user_id, text=msg)


# تسجيل الرقم القومي أو إرسال النتيجة فورًا
async def save_national_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    national_id = update.message.text.strip()
    user_id = update.message.from_user.id

    # تحقق من وجود الطالب
    student_ref = db.collection("students").document(national_id)
    student_doc = student_ref.get()
    if not student_doc.exists:
        await update.message.reply_text(
            "الرقم القومي غير موجود، برجاء التحدث مع المطور https://wa.me/201274445091"
        )
        return

    student = student_doc.to_dict()
    registered_students[national_id] = user_id

    # تحقق من النتيجة
    result_ref = db.collection("results").document(national_id)
    result_doc = result_ref.get()

    if result_doc.exists and national_id not in sent_results:
        await send_result_message(user_id, result_doc.to_dict(), context.bot)
        sent_results.add(national_id)
        logging.info(f"تم إرسال النتيجة للطالب {national_id} مباشرة بعد التسجيل")
        return

    msg = f"""✅ تم تخزين الرقم القومي الخاص بك: {national_id}

بياناتك:
الاسم: {student["name"]}
المدرسة: {student["school"]}
الإدارة: {student["admin"]}
المحافظة: {student["governorate"]}
الرقم القومي: {national_id}
"""
    await update.message.reply_text(msg)


# متابعة النتائج الجديدة في Firestore
async def monitor_results(app: Application):
    global sent_results
    while True:
        results_ref = db.collection("results").stream()
        for doc in results_ref:
            national_id = doc.id
            result = doc.to_dict()
            if national_id in registered_students and national_id not in sent_results:
                user_id = registered_students[national_id]
                await send_result_message(user_id, result, app.bot)
                sent_results.add(national_id)
                logging.info(f"📩 تم إرسال النتيجة للطالب {national_id}")
        await asyncio.sleep(2)


# تشغيل المراقبة بعد بدء التطبيق
async def post_init(app: Application):
    asyncio.create_task(monitor_results(app))


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_national_id))
    app.run_polling()


if __name__ == "__main__":
    main()
