import re
import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters
)

# ================== TOKEN ==================
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

# ==========================================
CUSTOM_ORDER = "0123456789abcdefghijklmnopqrstuvwxyz"


def version_key_custom(version, user_last_char):
    idx = version.lower().find(user_last_char.lower()) + 1
    if idx <= 0:
        idx = 0
    chars = version[idx:].lower()
    key = []
    for c in chars:
        if c in CUSTOM_ORDER:
            key.append(CUSTOM_ORDER.index(c))
        else:
            key.append(-1)
    return tuple(key)


def get_best_versions(versions, user_input):
    last_char = user_input[-1]
    version_keys = [(v, version_key_custom(v, last_char)) for v in versions]
    max_key = max([k for v, k in version_keys])
    best_versions = [v for v, k in version_keys if k == max_key]
    return best_versions


def filter_by_date_and_download(rows, best_versions):
    version_date_link_download_map = {}

    for row in rows:
        a_tag = row.select_one("a.text-light")
        if not a_tag:
            continue

        version = a_tag.get_text(strip=True)
        if version not in best_versions:
            continue

        download_link_tag = row.select_one("a.btn[href]")
        link = download_link_tag["href"] if download_link_tag else "لینک پیدا نشد"

        downloads = 0
        downloads_td = row.select_one("td.downloads")
        if downloads_td:
            try:
                downloads = int(re.sub(r"\D", "", downloads_td.get_text()))
            except:
                downloads = 0

        for td in row.find_all("td"):
            date_obj = None
            data_order = td.get("data-order")

            if data_order and re.match(r"\d{4}-\d{2}-\d{2}", data_order):
                date_obj = datetime.strptime(data_order[:10], "%Y-%m-%d").date()
            else:
                txt = td.get_text(strip=True)
                if re.match(r"\d{4}-\d{2}-\d{2}", txt):
                    date_obj = datetime.strptime(txt[:10], "%Y-%m-%d").date()

            if date_obj:
                version_date_link_download_map.setdefault(version, []).append(
                    (date_obj, link, downloads)
                )

    if not version_date_link_download_map:
        return [], {}

    max_date = None
    best_version_final = {}

    for version, items in version_date_link_download_map.items():
        for date_obj, link, downloads in items:
            if not max_date or date_obj > max_date:
                max_date = date_obj
                best_version_final = {version: (link, downloads)}
            elif date_obj == max_date:
                if version not in best_version_final or downloads > best_version_final[version][1]:
                    best_version_final[version] = (link, downloads)

    return list(best_version_final.keys()), best_version_final


# ================== BOT HANDLERS ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📱 *شماره مدل گوشی خود را کامل وارد کنید:*\n\n"
        "📝 *راهنما:*\n"
        "1️⃣ به تنظیمات گوشی بروید\n"
        "2️⃣ وارد «درباره تلفن» شوید\n"
        "3️⃣ بخش «اطلاعات سخت‌افزار» را ببینید\n"
        "4️⃣ شماره مدل را اینجا ارسال کنید\n\n"
        "⚠️ *توجه:*\n"
        "`LgH_860` یا `Lg-h860`\n"
        "باید به این صورت وارد شود:\n"
        "`Lgh860`\n\n"
        "✅ *مثال صحیح:* `Lgh860`"
    )

    await update.message.reply_text(
        text,
        parse_mode="MarkdownV2"
    )


async def check_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    if not user_input:
        await update.message.reply_text("❌ لطفا مدل را وارد کنید")
        return

    context.user_data["model"] = user_input
    await update.message.reply_text("⏳ در حال پیدا کردن فریمورها...")

    url = f"https://lgrom.com/firmware/{user_input}"

    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        r.raise_for_status()
    except:
        await update.message.reply_text("❌ مدل وارد شده معتبر نیست یا فریموری وجود ندارد")
        return

    soup = BeautifulSoup(r.text, "html.parser")
    tbody = soup.select_one("tbody.text-gray-600.fw-bold")

    if not tbody:
        await update.message.reply_text("❌ جدول فریمورها پیدا نشد")
        return

    rows = tbody.find_all("tr")
    if not rows:
        await update.message.reply_text("❌ فریموری پیدا نشد")
        return

    context.user_data["rows"] = rows

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تایید برای پیدا کردن بهترین ورژن", callback_data="extract_versions")]
    ])

    await update.message.reply_text(
        "✅ فریمورها پیدا شد\nبرای ادامه تایید کنید",
        reply_markup=keyboard
    )


async def extract_versions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⏳ در حال استخراج ورژن‌ها...")

    rows = context.user_data.get("rows", [])
    model = context.user_data.get("model", "")

    versions = []
    for row in rows:
        a = row.select_one("a.text-light")
        if a:
            versions.append(a.get_text(strip=True))

    if not versions:
        await query.edit_message_text("❌ فریموری پیدا نشد")
        return

    best_versions = get_best_versions(versions, model)

    if len(best_versions) == 1:
        final_versions, data = filter_by_date_and_download(rows, best_versions)
        msg = "🔹 بهترین ورژن:\n"
        for v in final_versions:
            link, _ = data[v]
            msg += f"{v}\n{link}\n"
        await query.edit_message_text(msg)
    else:
        context.user_data["best_versions"] = best_versions
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ بررسی جدیدترین تاریخ", callback_data="extract_newest_date")]
        ])
        await query.edit_message_text(
            "⚠️ چند ورژن مشابه پیدا شد\nبرای بررسی جدیدترین تایید کنید",
            reply_markup=keyboard
        )


async def extract_newest_date_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⏳ در حال بررسی...")

    rows = context.user_data.get("rows", [])
    best_versions = context.user_data.get("best_versions", [])

    final_versions, data = filter_by_date_and_download(rows, best_versions)

    if not final_versions:
        await query.edit_message_text("❌ نتیجه‌ای پیدا نشد")
        return

    msg = "🔹 بهترین ورژن نهایی:\n"
    for v in final_versions:
        link, _ = data[v]
        msg += f"{v}\n{link}\n"

    await query.edit_message_text(msg)


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_model))
    app.add_handler(CallbackQueryHandler(extract_versions_callback, pattern="extract_versions"))
    app.add_handler(CallbackQueryHandler(extract_newest_date_callback, pattern="extract_newest_date"))

    print("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
