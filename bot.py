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
print("🔑 BOT_TOKEN:", BOT_TOKEN)
print("🔑 FIREBASE_CREDENTIALS موجود؟", "FIREBASE_CREDENTIALS" in os.environ)

# إعداد الـ logging (خليه DEBUG عشان يطبع كل حاجة)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG
)

# تهيئة Firebase
import json
cred = credentials.Certificate(json.loads(os.environ["FIREBASE_CREDENTIALS"]))
firebase_admin.initialize_app(cred)
db = firestore.client()
print("✅ Firebase initialized")

registered_students = {}
sent_results = set()

# رسالة الترحيب
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("🚀 start() triggered by", update.message.from_user.id)
    await update.message.reply_text(
        '👋 أهلاً بك! أرسل رقمك القومي لتخزين بياناتك واستلام نتيجتك تلقائيًا.'
    )

# دالة إرسال النتيجة
async def send_result_message(user_id, result, bot):
    print(f"📤 Sending result to user_id={user_id}")
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
    print(f"💾 save_national_id() called with national_id={national_id}, user_id={user_id}")

    # التحقق من وجود الطالب في Firebase
    student_ref = db.collection("students").document(national_id)
    student_doc = student_ref.get()
    print("🔍 Firebase student exists?", student_doc.exists)

    if not student_doc.exists:
        await update.message.reply_text(
            "❌ الرقم القومي غير موجود، برجاء التحدث مع المطور https://wa.me/201274445091"
        )
        return

    student = student_doc.to_dict()
    registered_students[national_id] = user_id
    print(f"✅ Registered student {national_id} for user {user_id}")

    # التحقق من النتيجة في Firebase
    result_ref = db.collection("results").document(national_id)
    result_doc = result_ref.get()
    print("🔍 Firebase result exists?", result_doc.exists)

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
    print("👀 on_snapshot triggered with changes:", len(changes))
    for change in changes:
        if change.type.name in ['ADDED', 'MODIFIED']:
            national_id = change.document.id
            result = change.document.to_dict()
            if national_id in registered_students and national_id not in sent_results:
                user_id = registered_students[national_id]
                print(f"📢 Sending new snapshot result for {national_id} to {user_id}")
                asyncio.run(send_result_message(user_id, result, app.bot))
                sent_results.add(national_id)

async def post_init(app: Application):
    print("⚙️ post_init started")
    results_ref = db.collection("results")
    results_ref.on_snapshot(lambda col_snapshot, changes, read_time: on_snapshot(col_snapshot, changes, read_time, app))

def main():
    if not BOT_TOKEN:
        raise ValueError("❌ BOT_TOKEN غير موجود في ملف .env")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_national_id))
    print("▶️ Bot is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
