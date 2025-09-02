import json
import asyncio
import logging
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import firebase_admin
from firebase_admin import credentials, db

# تحميل المتغيرات من .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
FIREBASE_CREDENTIALS = os.getenv("FIREBASE_CREDENTIALS")  # محتوى JSON كـ string
FIREBASE_DB_URL = os.getenv("FIREBASE_DB_URL")  # لينك قاعدة البيانات من Firebase

# تهيئة Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate(json.loads(FIREBASE_CREDENTIALS))
    firebase_admin.initialize_app(cred, {
        "databaseURL": FIREBASE_DB_URL
    })

# مراجع لجدولين: الطلاب والنتائج
students_ref = db.reference("students")  # بديل data.json
results_ref = db.reference("results")    # بديل result.json

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

registered_students = {}  # لتخزين user_id لكل رقم قومي
sent_results = set()      # لتخزين الأرقام القومية التي تم إرسال نتائجها

# رسالة الترحيب
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        '👋 أهلاً بك! أرسل رقمك القومي لتخزين بياناتك واستلام نتيجتك تلقائيًا.'
    )

# دالة لإرسال نتيجة مفصلة
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

# حفظ الرقم القومي أو إرسال النتيجة فورًا
async def save_national_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    national_id = update.message.text.strip()
    user_id = update.message.from_user.id

    student = students_ref.child(national_id).get()
    if not student:
        await update.message.reply_text(
            "الرقم القومي غير موجود، برجاء التحدث مع المطور https://wa.me/201274445091"
        )
        return

    registered_students[national_id] = user_id

    # إذا النتيجة موجودة مسبقًا → أرسلها مباشرة
    result = results_ref.child(national_id).get()
    if result and national_id not in sent_results:
        await send_result_message(user_id, result, context.bot)
        sent_results.add(national_id)
        logging.info(f"تم إرسال النتيجة للطالب بالرقم القومي {national_id} فورًا بعد التسجيل")
        return

    # إذا النتيجة غير موجودة بعد → سجل الطالب وأرسل رسالة "تم التخزين"
    msg = f"""✅ تم بنجاح تخزين الرقم القومي الخاص بك وهو: {national_id}

بياناتك هي:
الاسم: {student["name"]}
المدرسة: {student["school"]}
الإدارة: {student["admin"]}
المحافظة: {student["governorate"]}
الرقم القومي: {national_id}
"""
    await update.message.reply_text(msg)

# مراقبة النتائج الجديدة في Firebase
async def monitor_results(app: Application):
    while True:
        current_results = results_ref.get() or {}
        for national_id, result in current_results.items():
            if national_id in registered_students and national_id not in sent_results:
                user_id = registered_students[national_id]
                await send_result_message(user_id, result, app.bot)
                sent_results.add(national_id)
                logging.info(f"تم إرسال النتيجة للطالب بالرقم القومي {national_id}")
        await asyncio.sleep(2)  # تحقق كل ثانيتين

# دالة post_init لتشغيل المراقب بعد بدء التطبيق
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
