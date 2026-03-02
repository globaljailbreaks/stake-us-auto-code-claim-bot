import asyncio
import json
import logging
import os
import random
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from playwright.async_api import async_playwright, BrowserContext, Page, Locator, TimeoutError as PlaywrightTimeout
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ────────────────────────────────────────────────
# CONFIG – YOUR VALUES
BOT_TOKEN = "8630645115:AAFr7FlWLecuHFjvzs4dwWViVJWhGeZzWbg"
ADMIN_IDS = [8196946430]
ACCOUNTS_FILE = Path("accounts.json")
CODES_QUEUE: List[str] = []
CLAIM_LOG: List[Dict[str, Any]] = []
# ────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    await update.message.reply_text(
        "🔥 Stake.us Code Claimer Bot – Fixed & Hardened 2026 🔥\n\n"
        "Commands:\n"
        "/addcode <CODE>          – Add single code\n"
        "/addcodes                – Reply to message with codes\n"
        "/status                  – Queue + recent claims\n"
        "/claimnow                – Start claiming\n"
        "/accounts                – Show loaded accounts\n"
        "/clearqueue              – Empty code queue\n\n"
        "Single account loaded: sabrinakatocs"
    )

async def add_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS: return
    if not context.args:
        await update.message.reply_text("Usage: /addcode WEEKLYBOOST")
        return
    code = context.args[0].strip().upper()
    if code not in CODES_QUEUE:
        CODES_QUEUE.append(code)
        await update.message.reply_text(f"✅ Added → {code} (queue: {len(CODES_QUEUE)})")
    else:
        await update.message.reply_text(f"🔄 Already queued: {code}")

async def add_codes_bulk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS: return
    if not update.message.reply_to_message or not update.message.reply_to_message.text:
        await update.message.reply_text("Reply to a message with codes → /addcodes")
        return

    text = update.message.reply_to_message.text.upper()
    import re
    raw = re.findall(r'[A-Z0-9]{5,15}', text)  # robust alphanumeric 5–15 chars
    unique = set(raw)
    new_codes = [c for c in unique if c not in CODES_QUEUE]

    if not new_codes:
        await update.message.reply_text("No new valid codes found.")
        return

    CODES_QUEUE.extend(new_codes)
    preview = ', '.join(new_codes[:5]) + ('...' if len(new_codes) > 5 else '')
    await update.message.reply_text(
        f"🚀 Added {len(new_codes)} new codes\n"
        f"Queue now: {len(CODES_QUEUE)}\n"
        f"Added: {preview}"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS: return
    msg = f"📊 Queue: {len(CODES_QUEUE)} pending\n\nLast 10 claims:\n"
    for entry in CLAIM_LOG[-10:]:
        t = entry["time"]
        acc = entry["account"][:8] + "..."
        code = entry["code"]
        res = "✅" if entry["success"] else f"❌ {entry['message'][:50]}"
        msg += f"{t} | {acc} | {code} | {res}\n"
    if not CLAIM_LOG:
        msg += "No claims yet."
    await update.message.reply_text(msg)

async def clear_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS: return
    old = len(CODES_QUEUE)
    CODES_QUEUE.clear()
    await update.message.reply_text(f"Queue cleared. Removed {old} codes.")

async def accounts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS: return
    if not ACCOUNTS_FILE.exists():
        await update.message.reply_text("accounts.json missing.")
        return
    try:
        with open(ACCOUNTS_FILE, 'r') as f:
            data = json.load(f)
        msg = "Loaded accounts:\n\n"
        for acc in data:
            u = acc.get("username", "unknown")
            p = acc.get("password", "???")[:4] + "..."
            msg += f"• Username: {u} | Pass: {p}\n"
        await update.message.reply_text(msg.strip() or "No accounts loaded.")
    except Exception as e:
        await update.message.reply_text(f"Error reading file: {str(e)}")

async def safe_claim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        await update.message.reply_text("Starting claim loop...")
        await claim_codes()
        await update.message.reply_text("Claim loop finished.")
    except Exception as e:
        error_msg = f"🚨 Claim crashed: {str(e)[:200]}"
        await update.message.reply_text(error_msg)
        logger.exception("Claim handler exception")

async def claim_codes() -> None:
    global CODES_QUEUE, CLAIM_LOG
    if not CODES_QUEUE:
        logger.info("Queue empty.")
        return

    if not ACCOUNTS_FILE.exists():
        logger.error("accounts.json missing!")
        return

    with open(ACCOUNTS_FILE, 'r') as f:
        accounts: List[Dict] = json.load(f)

    async with async_playwright() as p:
        for acc in accounts:
            username = acc.get("username")
            password = acc.get("password")

            if not username or not password:
                logger.warning(f"Invalid account: {acc}")
                continue

            logger.info(f"Starting claim for {username}")

            try:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    viewport={"width": 390, "height": 844},  # mobile-like to save mem
                    user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
                    locale="en-US",
                    timezone_id="America/New_York",
                )
                page = await context.new_page()

                await page.goto("https://stake.us/login", timeout=60000)
                await asyncio.sleep(random.uniform(4, 8))

                # Username login – robust 2026 selectors
                username_loc = page.locator(
                    'input[name="username"], input[placeholder*="Username"], input[type="text"][autocomplete="username"], input[id*="username"]'
                )
                password_loc = page.locator(
                    'input[name="password"], input[type="password"], input[placeholder*="Password"]'
                )
                submit_loc = page.locator(
                    'button[type="submit"], button:has-text("Login"), button:has-text("Sign In"), button:has-text("Continue")'
                )

                if not await username_loc.count():
                    raise Exception("Username field not found – Stake UI changed")

                # Human-like typing
                await username_loc.click()
                for char in username:
                    await username_loc.type(char, delay=random.uniform(60, 180))
                await password_loc.type(password, delay=random.uniform(60, 180))

                await submit_loc.click()
                await page.wait_for_url("**/dashboard**", timeout=90000)

                logger.info(f"Login OK: {username}")

                await page.goto("https://stake.us/account/promotions", timeout=30000)
                await asyncio.sleep(random.uniform(3, 7))

                claimed = 0
                for code in CODES_QUEUE.copy():
                    try:
                        code_loc = page.locator(
                            'input[placeholder*="Enter code"], input[name*="promo"], input[id*="promo"], input[type="text"][autocomplete="off"]'
                        )
                        redeem_loc = page.locator(
                            'button:has-text("Redeem"), button[type="submit"], button:has-text("Claim"), button:has-text("Apply")'
                        )

                        await code_loc.fill(code)
                        await redeem_loc.click()
                        await asyncio.sleep(random.uniform(6, 14))

                        success = await page.locator(
                            'text=successfully|bonus added|redeemed|congrats|balance updated'
                        ).count() > 0

                        error_text = await page.locator(
                            '[class*="error"], [class*="toast-error"], [class*="alert-danger"], [role="alert"]'
                        ).inner_text(timeout=5000) or "no error visible"

                        CLAIM_LOG.append({
                            "time": datetime.utcnow().isoformat(),
                            "account": username,
                            "code": code,
                            "success": success,
                            "message": error_text if not success else "claimed"
                        })

                        if success:
                            claimed += 1
                            CODES_QUEUE.remove(code)
                            logger.info(f"Claim success: {code}")
                        else:
                            logger.info(f"Claim fail: {code} → {error_text}")
                            if "rate limit" in error_text.lower() or "too many" in error_text.lower():
                                logger.warning("Rate limit – stopping account")
                                break

                    except PlaywrightTimeout:
                        logger.warning(f"Timeout on code {code}")
                    except Exception as e:
                        logger.error(f"Code error {code}: {e}")

                logger.info(f"{username} done – claimed {claimed}")

            except Exception as e:
                logger.exception(f"Session crash for {username}: {e}")
            finally:
                await context.close()
                await browser.close()

            await asyncio.sleep(random.uniform(180, 480))  # 3–8 min delay

# ────────────────────────────────────────────────
# WEBHOOK ENTRY – RAILWAY
# ────────────────────────────────────────────────

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addcode", add_code))
    app.add_handler(CommandHandler("addcodes", add_codes_bulk))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("accounts", accounts))
    app.add_handler(CommandHandler("clearqueue", clear_queue))
    app.add_handler(CommandHandler("claimnow", safe_claim))

    await app.initialize()
    await app.start()

    webhook_url = f"https://{os.environ['RAILWAY_PUBLIC_DOMAIN']}/{BOT_TOKEN}"
    await app.updater.start_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        url_path=BOT_TOKEN,
        webhook_url=webhook_url
    )

    logger.info(f"Webhook started → {webhook_url}")

    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
