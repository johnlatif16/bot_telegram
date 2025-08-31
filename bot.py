import json
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import logging

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# تحميل بيانات الطلاب
with open('data.json', 'r', encoding='utf-8-sig') as f:
    students_data = json.load(f)

registered_students = {}
sent_results = set()

# تحميل نتائج موجودة مسبقًا
try:
    with open('result.json', 'r', encoding='utf-8-sig') as f:
        results = json.load(f)
except FileNotFoundError:
    results = {}

# رسالة الترحيب
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        '👋 أهلاً بك! أرسل رقم جلوسك لتخزين بياناتك واستلام نتيجتك تلقائيًا.'
    )

# دالة لإرسال نتيجة مفصلة
async def send_result_message(user_id, result, bot):
    msg = f"""🎓 نتيجتك:

رقم الجلوس: {result['seatNumber']}
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

# حفظ رقم الجلوس والبيانات أو إرسال النتيجة فورًا
async def save_seat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    seat_number = update.message.text.strip()
    user_id = update.message.from_user.id

    if seat_number not in students_data:
        await update.message.reply_text(
            "رقم الجلوس غير موجود، برجاء التحدث مع المطور https://wa.me/201274445091"
        )
        return

    student = students_data[seat_number]
    registered_students[seat_number] = user_id

    # إذا النتيجة موجودة مسبقًا → أرسلها مباشرة
    if seat_number in results and seat_number not in sent_results:
        await send_result_message(user_id, results[seat_number], context.bot)
        sent_results.add(seat_number)
        logging.info(f"تم إرسال النتيجة للطالب رقم الجلوس {seat_number} فورًا بعد التسجيل")
        return

    # إذا النتيجة غير موجودة بعد → سجل الطالب وأرسل رسالة "تم التخزين"
    msg = f"""✅ تم بنجاح تخزين رقم الجلوس الخاص بك وهو: {seat_number}

بياناتك هي:
الاسم: {student["name"]}
المدرسة: {student["school"]}
الإدارة: {student["admin"]}
المحافظة: {student["governorate"]}
رقم الجلوس: {seat_number}
"""
    await update.message.reply_text(msg)

# مراقبة result.json وإرسال النتائج الجديدة تلقائيًا
async def monitor_results(app: Application):
    global results
    while True:
        try:
            with open('result.json', 'r', encoding='utf-8-sig') as f:
                current_results = json.load(f)
        except FileNotFoundError:
            current_results = {}

        for seat_number, result in current_results.items():
            if seat_number in registered_students and seat_number not in sent_results:
                user_id = registered_students[seat_number]
                await send_result_message(user_id, result, app.bot)
                sent_results.add(seat_number)
                logging.info(f"تم إرسال النتيجة للطالب رقم الجلوس {seat_number}")

        results = current_results
        await asyncio.sleep(2)

# دالة post_init لتشغيل المراقب بعد بدء التطبيق
async def post_init(app: Application):
    asyncio.create_task(monitor_results(app))

def main():
    # ضع التوكن الحقيقي للبوت هنا
    app = Application.builder().token("8377255550:AAH8Q1Kp-V7ic0obBHYdQ9beIHoh_1iS_PQ").post_init(post_init).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_seat))
    app.run_polling()

if __name__ == "__main__":
    main()
