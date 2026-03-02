import asyncio
import json
import logging
import os
import random
from datetime import datetime
from pathlib import Path
from typing import List, Dict

from playwright.async_api import async_playwright, BrowserContext, Page, Locator
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
ADMIN_IDS = [8196946430]
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
        "🔥 Stake.us Code Claimer Bot – Username Login Edition 2026 🔥\n\n"
        "Commands:\n"
        "/addcode <CODE>          → queue single code\n"
        "/addcodes                → reply with code list\n"
        "/status                  → queue + recent logs\n"
        "/claimnow                → force start claiming\n"
        "/accounts                → check accounts.json in GitLab\n\n"
        "Login now uses username + password (Stake.us 2026 format)."
    )

async def add_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS: return
    if not context.args:
        await update.message.reply_text("Usage: /addcode WEEKLYBOOST")
        return
    code = context.args[0].strip().upper()
    if code not in CODES_QUEUE:
        CODES_QUEUE.append(code)
        await update.message.reply_text(f"✅ Added: {code}  (queue: {len(CODES_QUEUE)})")
    else:
        await update.message.reply_text(f"🔄 Already queued: {code}")

async def add_codes_bulk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS: return
    if not update.message.reply_to_message or not update.message.reply_to_message.text:
        await update.message.reply_text("Reply to message with codes → /addcodes")
        return
    text = update.message.reply_to_message.text
    codes = [c.strip().upper() for c in text.split() if 5 <= len(c.strip()) <= 15 and c.strip().isalnum()]
    new_codes = [c for c in set(codes) if c not in CODES_QUEUE]
    CODES_QUEUE.extend(new_codes)
    await update.message.reply_text(f"🚀 Added {len(new_codes)} new codes. Queue: {len(CODES_QUEUE)}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS: return
    msg = f"📊 Status\nPending codes: {len(CODES_QUEUE)}\n\nLast 10 claims:\n"
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
        logger.info("Queue empty – nothing to claim.")
        return

    if not ACCOUNTS_FILE.exists():
        logger.error("accounts.json missing – cannot claim.")
        return

    with open(ACCOUNTS_FILE, 'r') as f:
        accounts: List[Dict] = json.load(f)

    async with async_playwright() as p:
        for acc in accounts:
            username = acc.get("username") or acc.get("email")  # fallback for old format
            password = acc["password"]

            if not username or not password:
                logger.warning(f"Invalid account entry: {acc}")
                continue

            logger.info(f"Claim session starting for {username}")

            browser = await p.chromium.launch(headless=True)
            context: BrowserContext = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="en-US",
                timezone_id="America/New_York",
            )
            page: Page = await context.new_page()

            try:
                await page.goto("https://stake.us/login", timeout=60000)
                await page.wait_for_timeout(random.randint(4000, 8000))

                # Handle cookie/age gate if present
                try:
                    await page.click("text=Accept All", timeout=10000)
                except:
                    pass

                # Username login – 2026 Stake.us selectors
                username_input: Locator = page.locator(
                    'input[name="username"], input[placeholder*="Username"], input[autocomplete="username"]'
                )
                password_input: Locator = page.locator(
                    'input[name="password"], input[type="password"], input[placeholder*="Password"]'
                )
                submit_btn: Locator = page.locator(
                    'button[type="submit"], button:has-text("Login"), button:has-text("Sign In")'
                )

                if not await username_input.is_visible(timeout=15000):
                    logger.warning(f"Username field not found for {username} – page may have changed")
                    continue

                # Simulate human typing
                await username_input.click()
                await username_input.type(username, delay=random.randint(80, 180))
                await password_input.type(password, delay=random.randint(80, 180))

                await submit_btn.click()
                await page.wait_for_url("**/dashboard**", timeout=45000)

                logger.info(f"Login success: {username}")

                # Go to promotions
                await page.goto("https://stake.us/account/promotions", timeout=30000)
                await page.wait_for_timeout(random.randint(3000, 6000))

                claimed = 0
                for code in CODES_QUEUE.copy():
                    try:
                        code_input = page.locator(
                            'input[placeholder*="Enter code"], input[name*="promo"], input[id*="promo"]'
                        )
                        redeem_btn = page.locator(
                            'button:has-text("Redeem"), button[type="submit"], button:has-text("Claim")'
                        )

                        await code_input.fill(code)
                        await redeem_btn.click()
                        await page.wait_for_timeout(random.randint(6000, 14000))

                        success = await page.query_selector(
                            'text=successfully|bonus added|redeemed|congrats|added to balance'
                        ) is not None

                        error_text = await page.inner_text(
                            '[class*="error"], [class*="toast-error"], [class*="alert-danger"], [class*="notification-error"]'
                        ) or "no error message visible"

                        CLAIM_LOG.append({
                            "time": datetime.utcnow().isoformat(),
                            "account": username,
                            "code": code,
                            "success": success,
                            "message": error_text if not success else "claimed successfully"
                        })

                        if success:
                            claimed += 1
                            CODES_QUEUE.remove(code)
                            logger.info(f"Success: {username} claimed {code}")
                        else:
                            logger.info(f"Fail: {username} → {code} → {error_text}")
                            if "rate limit" in error_text.lower() or "too many" in error_text.lower():
                                logger.warning(f"Rate limit detected – stopping account {username}")
                                break

                    except Exception as e:
                        logger.error(f"Claim exception for {code} on {username}: {e}")

                logger.info(f"{username} finished – claimed {claimed} codes")

            except Exception as e:
                logger.error(f"Session crash for {username}: {e}")
            finally:
                await context.close()
                await browser.close()

            # Delay between accounts – avoid detection
            await asyncio.sleep(random.randint(180, 480))

# ────────────────────────────────────────────────
# WEBHOOK MODE – RAILWAY PERSISTENCE
# ────────────────────────────────────────────────

async def webhook_main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addcode", add_code))
    app.add_handler(CommandHandler("addcodes", add_codes_bulk))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("claimnow", lambda u,c: asyncio.create_task(claim_codes())))

    await app.initialize()
    await app.start()
    await app.updater.start_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        url_path=BOT_TOKEN,
        webhook_url=f"https://{os.environ['RAILWAY_PUBLIC_DOMAIN']}/{BOT_TOKEN}"
    )

    logger.info(f"Webhook active on {os.environ.get('RAILWAY_PUBLIC_DOMAIN')}")

    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(webhook_main())
