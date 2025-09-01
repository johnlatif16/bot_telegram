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

registered_students = {}  # لتخزين user_id لكل رقم قومي
sent_results = set()      # لتخزين الأرقام القومية التي تم إرسال نتائجها

# تحميل نتائج موجودة مسبقًا
try:
    with open('result.json', 'r', encoding='utf-8-sig') as f:
        results = json.load(f)
except FileNotFoundError:
    results = {}

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

    if national_id not in students_data:
        await update.message.reply_text(
            "الرقم القومي غير موجود، برجاء التحدث مع المطور https://wa.me/201274445091"
        )
        return

    student = students_data[national_id]
    registered_students[national_id] = user_id

    # إذا النتيجة موجودة مسبقًا → أرسلها مباشرة
    if national_id in results and national_id not in sent_results:
        await send_result_message(user_id, results[national_id], context.bot)
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

# مراقبة result.json وإرسال النتائج الجديدة تلقائيًا
async def monitor_results(app: Application):
    global results
    while True:
        try:
            with open('result.json', 'r', encoding='utf-8-sig') as f:
                current_results = json.load(f)
        except FileNotFoundError:
            current_results = {}

        # أرسل النتائج لكل الطلاب المسجلين الذين لم تُرسل لهم بعد
        for national_id, result in current_results.items():
            if national_id in registered_students and national_id not in sent_results:
                user_id = registered_students[national_id]
                await send_result_message(user_id, result, app.bot)
                sent_results.add(national_id)
                logging.info(f"تم إرسال النتيجة للطالب بالرقم القومي {national_id}")

        results = current_results
        await asyncio.sleep(2)  # تحقق كل ثانيتين

# دالة post_init لتشغيل المراقب بعد بدء التطبيق
async def post_init(app: Application):
    asyncio.create_task(monitor_results(app))

def main():
    # ضع التوكن الحقيقي للبوت هنا
    app = Application.builder().token("8377255550:AAE03B8AdlZwiz812j6_HL57ggEJyJNOk_k").post_init(post_init).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_national_id))
    app.run_polling()

if __name__ == "__main__":
    main()
