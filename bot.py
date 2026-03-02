import asyncio
import json
import logging
import os
import random
from datetime import datetime
from pathlib import Path
from typing import List, Dict

from playwright.async_api import async_playwright, BrowserContext, Page
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ────────────────────────────────────────────────
# CONFIG – YOUR VALUES LOCKED IN
BOT_TOKEN = "8630645115:AAFr7FlWLecuHFjvzs4dwWViVJWhGeZzWbg"
ADMIN_IDS = [8196946430]  # only you control it
ACCOUNTS_FILE = Path("accounts.json")
CODES_QUEUE: List[str] = []
CLAIM_LOG: List[Dict] = []
# ────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    await update.message.reply_text(
        "🔥 Stake.us Code Claimer Bot – Proxy-Free 2026 Edition 🔥\n\n"
        "Commands:\n"
        "/addcode <CODE>          → queue single code\n"
        "/addcodes                → reply to message with code list\n"
        "/status                  → queue + recent logs\n"
        "/claimnow                → force start claiming\n"
        "/accounts                → check or update accounts.json via GitLab\n\n"
        "No proxies – using Railway outbound IP. Rotate deployment if banned."
    )

async def add_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS: return
    if not context.args:
        await update.message.reply_text("Usage: /addcode WEEKLYBOOST")
        return
    code = context.args[0].strip().upper()
    if code not in CODES_QUEUE:
        CODES_QUEUE.append(code)
        await update.message.reply_text(f"✅ Added: {code}  (queue now {len(CODES_QUEUE)})")
    else:
        await update.message.reply_text(f"🔄 {code} already queued.")

async def add_codes_bulk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS: return
    if not update.message.reply_to_message or not update.message.reply_to_message.text:
        await update.message.reply_text("Reply to a message containing codes with /addcodes")
        return
    text = update.message.reply_to_message.text
    codes = [c.strip().upper() for c in text.splitlines() + text.split() if 5 <= len(c.strip()) <= 15 and c.strip().isalnum()]
    new_codes = [c for c in set(codes) if c not in CODES_QUEUE]
    CODES_QUEUE.extend(new_codes)
    await update.message.reply_text(f"🚀 Added {len(new_codes)} new codes. Queue size: {len(CODES_QUEUE)}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS: return
    msg = f"📊 Status\nQueue: {len(CODES_QUEUE)} codes pending\n\nLast 10 claims:\n"
    for entry in CLAIM_LOG[-10:]:
        t = entry["time"]
        acc = entry["account"][:8] + "..."
        code = entry["code"]
        res = "✅" if entry["success"] else f"❌ {entry['message'][:40]}"
        msg += f"{t} | {acc} | {code} | {res}\n"
    if not CLAIM_LOG:
        msg += "No claims yet."
    await update.message.reply_text(msg)

async def claim_codes() -> None:
    global CODES_QUEUE, CLAIM_LOG
    if not CODES_QUEUE:
        logger.info("No codes in queue.")
        return

    if not ACCOUNTS_FILE.exists():
        logger.error("accounts.json missing!")
        return

    with open(ACCOUNTS_FILE, 'r') as f:
        accounts: List[Dict] = json.load(f)

    async with async_playwright() as p:
        for acc in accounts:
            email = acc["email"]
            password = acc["password"]

            logger.info(f"Starting session for {email}")

            browser = await p.chromium.launch(headless=True)  # NO PROXY
            context: BrowserContext = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="en-US",
                timezone_id="America/New_York",
                # Add more stealth later if needed
            )
            page: Page = await context.new_page()

            try:
                await page.goto("https://stake.us/", timeout=60000)
                await page.wait_for_timeout(random.randint(4000, 9000))

                # Login flow – update selectors if Stake changes UI
                await page.click("text=Login", timeout=30000)
                await page.fill('input[name="email"]', email)
                await page.fill('input[name="password"]', password)
                await page.click('button[type="submit"]')
                await page.wait_for_url("**/dashboard**", timeout=60000)

                await page.goto("https://stake.us/account/promotions")

                claimed = 0
                for code in CODES_QUEUE.copy():
                    try:
                        await page.fill('input[placeholder*="Enter code"], input[name*="promo"]', code)
                        await page.click('button:has-text("Redeem"), button[type="submit"]')
                        await page.wait_for_timeout(random.randint(5000, 12000))

                        success = await page.query_selector('text=success|bonus added|redeemed') is not None
                        error = await page.inner_text('[class*="error"], [class*="toast-error"], [class*="alert"]') or "no message"

                        CLAIM_LOG.append({
                            "time": datetime.utcnow().isoformat(),
                            "account": email,
                            "code": code,
                            "success": success,
                            "message": error if not success else "claimed"
                        })

                        if success:
                            claimed += 1
                            CODES_QUEUE.remove(code)
                        else:
                            if "rate limit" in error.lower() or "too many" in error.lower():
                                logger.warning(f"Rate limit hit on {email} – stopping this account")
                                break

                    except Exception as e:
                        logger.error(f"Claim error {code} on {email}: {e}")

                logger.info(f"{email} → claimed {claimed} codes")

            except Exception as e:
                logger.error(f"Full session crash for {email}: {e}")
            finally:
                await context.close()
                await browser.close()

            await asyncio.sleep(random.randint(180, 420))  # 3–7 min delay between accounts

# ────────────────────────────────────────────────
# WEBHOOK MODE FOR RAILWAY PERSISTENCE – NO POLLING
# ────────────────────────────────────────────────

async def webhook_main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addcode", add_code))
    app.add_handler(CommandHandler("addcodes", add_codes_bulk))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("claimnow", lambda u,c: asyncio.create_task(claim_codes())))

    # Webhook setup – Railway provides PORT & domain
    await app.initialize()
    await app.start()
    await app.updater.start_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        url_path=BOT_TOKEN,
        webhook_url=f"https://{os.environ['RAILWAY_PUBLIC_DOMAIN']}/{BOT_TOKEN}"
    )

    logger.info(f"Webhook started on {os.environ.get('RAILWAY_PUBLIC_DOMAIN')}")

    # Keep alive forever
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(webhook_main())
