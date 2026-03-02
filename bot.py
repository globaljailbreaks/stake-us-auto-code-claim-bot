import asyncio
import json
import logging
import os
import random
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from playwright.async_api import async_playwright, BrowserContext, Page, Locator, Error as PlaywrightError, TimeoutError as PlaywrightTimeout
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ────────────────────────────────────────────────
# CONFIG
BOT_TOKEN = "8630645115:AAFr7FlWLecuHFjvzs4dwWViVJWhGeZzWbg"
ADMIN_IDS = [8196946430]
ACCOUNTS_FILE = Path("accounts.json")
CODES_QUEUE: List[str] = []
CLAIM_LOG: List[Dict[str, Any]] = []
CURRENT_PAGE: Page | None = None  # Global for 2FA manual input
CURRENT_CONTEXT: BrowserContext | None = None
# ────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    await update.message.reply_text(
        "🔥 Stake.us Code Claimer Bot – Level 3 Manual 2FA Assist 🔥\n\n"
        "Commands:\n"
        "/addcode <CODE>\n"
        "/addcodes (reply to list)\n"
        "/status\n"
        "/claimnow\n"
        "/accounts\n"
        "/entercode 123456   ← when 2FA prompt appears\n"
        "/clearqueue\n\n"
        "Single account: sabrinakatocs\n"
        "Bot pauses at email code prompt → use /entercode to continue"
    )

async def add_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS: return
    if not context.args:
        await update.message.reply_text("Usage: /addcode WEEKLYBOOST")
        return
    code = context.args[0].strip().upper()
    if code not in CODES_QUEUE:
        CODES_QUEUE.append(code)
        await update.message.reply_text(f"✅ Added: {code} (queue: {len(CODES_QUEUE)})")
    else:
        await update.message.reply_text(f"🔄 Already queued.")

async def add_codes_bulk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS: return
    if not update.message.reply_to_message or not update.message.reply_to_message.text:
        await update.message.reply_text("Reply to message with codes → /addcodes")
        return
    text = update.message.reply_to_message.text.upper()
    import re
    raw = re.findall(r'[A-Z0-9]{5,15}', text)
    unique = set(raw)
    new_codes = [c for c in unique if c not in CODES_QUEUE]
    if not new_codes:
        await update.message.reply_text("No new valid codes.")
        return
    CODES_QUEUE.extend(new_codes)
    preview = ', '.join(new_codes[:5]) + ('...' if len(new_codes) > 5 else '')
    await update.message.reply_text(f"🚀 Added {len(new_codes)} codes\nQueue: {len(CODES_QUEUE)}\nAdded: {preview}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS: return
    msg = f"📊 Queue: {len(CODES_QUEUE)}\n\nLast 10 claims:\n"
    for entry in CLAIM_LOG[-10:]:
        msg += f"{entry['time']} | {entry['account'][:8]}... | {entry['code']} | {'✅' if entry['success'] else '❌ '+entry['message'][:50]}\n"
    if not CLAIM_LOG:
        msg += "No claims yet."
    await update.message.reply_text(msg)

async def clear_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS: return
    old = len(CODES_QUEUE)
    CODES_QUEUE.clear()
    await update.message.reply_text(f"Queue cleared ({old} removed).")

async def accounts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS: return
    if not ACCOUNTS_FILE.exists():
        await update.message.reply_text("No accounts.json")
        return
    try:
        with open(ACCOUNTS_FILE, 'r') as f:
            data = json.load(f)
        msg = "Loaded accounts:\n\n"
        for acc in data:
            u = acc.get("username", "unknown")
            p = acc.get("password", "???")[:4] + "..."
            msg += f"• {u} | {p}\n"
        await update.message.reply_text(msg.strip())
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")

async def enter_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS: return
    if not context.args:
        await update.message.reply_text("Usage: /entercode 123456")
        return
    code = context.args[0].strip()
    global CURRENT_PAGE, CURRENT_CONTEXT
    if CURRENT_PAGE is None:
        await update.message.reply_text("No active login waiting for 2FA code.")
        return
    try:
        code_input = CURRENT_PAGE.locator(
            'input[placeholder*="code"], input[name*="verification"], input[type="text"][autocomplete="one-time-code"], input[id*="code"]'
        )
        submit = CURRENT_PAGE.locator(
            'button:has-text("Verify"), button:has-text("Submit"), button[type="submit"], button:has-text("Continue")'
        )
        await code_input.fill(code)
        await submit.click()
        await asyncio.sleep(5)
        if "dashboard" in CURRENT_PAGE.url:
            await update.message.reply_text("✅ Code accepted! Resuming claims...")
            # Resume loop - call claim_codes again or continue from promotions
            await claim_codes()  # restart loop from current state
        else:
            await update.message.reply_text("❌ Code failed – check email and try again")
    except Exception as e:
        await update.message.reply_text(f"Error entering code: {str(e)}")
    finally:
        CURRENT_PAGE = None
        CURRENT_CONTEXT = None

async def safe_claim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        await update.message.reply_text("Starting claim loop on sabrinakatocs...")
        await claim_codes()
        await update.message.reply_text("Claim loop finished.")
    except Exception as e:
        tb = traceback.format_exc()
        error_msg = f"🚨 Claim crashed:\n{str(e)}\n\nTraceback (first 800 chars):\n{tb[:800]}..."
        await update.message.reply_text(error_msg)
        logger.exception("Safe claim crash")

async def claim_codes() -> None:
    global CODES_QUEUE, CLAIM_LOG, CURRENT_PAGE, CURRENT_CONTEXT
    if not CODES_QUEUE:
        logger.info("Queue empty.")
        return

    if not ACCOUNTS_FILE.exists():
        logger.error("accounts.json missing!")
        return

    with open(ACCOUNTS_FILE, 'r') as f:
        accounts = json.load(f)

    async with async_playwright() as p:
        for acc in accounts:
            username = acc.get("username")
            password = acc.get("password")
            if not username or not password:
                continue

            browser = None
            context: BrowserContext | None = None
            page: Page | None = None

            try:
                logger.info(f"Starting claim session for {username}")
                browser = await p.chromium.launch(headless=True, timeout=90000)
                context = await browser.new_context(
                    viewport={"width": 390, "height": 844},
                    user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1",
                    locale="en-US",
                    timezone_id="America/New_York",
                )
                page = await context.new_page()

                await page.goto("https://stake.us/login", timeout=60000, wait_until="domcontentloaded")
                await asyncio.sleep(random.uniform(4, 9))

                # Cookie/age gate
                try:
                    await page.click("text=Accept All", timeout=10000)
                except:
                    pass

                username_loc = page.locator(
                    'input[name="username"], input[placeholder*="Username"], input[type="text"][autocomplete="username"], input[id*="username"]'
                )
                password_loc = page.locator('input[type="password"], input[placeholder*="Password"]')
                submit_loc = page.locator('button[type="submit"], button:has-text("Login"), button:has-text("Sign In")')

                if await username_loc.count() == 0:
                    raise Exception("Username field not found – Stake UI may have changed")

                await username_loc.click()
                await username_loc.type(username, delay=random.uniform(60, 180))
                await password_loc.type(password, delay=random.uniform(60, 180))
                await submit_loc.click()

                await asyncio.sleep(10)  # wait for potential 2FA prompt

                # Detect 2FA prompt
                if await page.locator('text=verification|code sent|enter code|email code').count() > 0:
                    global CURRENT_PAGE, CURRENT_CONTEXT
                    CURRENT_PAGE = page
                    CURRENT_CONTEXT = context
                    await page.screenshot(path="/tmp/login-2fa.png")  # optional debug
                    await context.bot.send_message(
                        chat_id=ADMIN_IDS[0],
                        text="⚠️ 2FA EMAIL CODE REQUIRED for sabrinakatocs!\n\n"
                             "Stake sent a 6-digit code to your email.\n"
                             "Check inbox → reply with /entercode 123456"
                    )
                    return  # pause - wait for manual /entercode

                # If no 2FA - continue
                await page.wait_for_url("**/dashboard**", timeout=120000, wait_until="domcontentloaded")
                logger.info(f"Login success (no 2FA): {username}")

                await page.goto("https://stake.us/account/promotions", timeout=40000)
                await asyncio.sleep(random.uniform(3, 7))

                claimed = 0
                for code in CODES_QUEUE.copy():
                    try:
                        code_loc = page.locator('input[placeholder*="Enter code"], input[name*="promo"], input[id*="promo"]')
                        redeem_loc = page.locator('button:has-text("Redeem"), button[type="submit"], button:has-text("Claim")')

                        await code_loc.fill(code)
                        await redeem_loc.click()
                        await asyncio.sleep(random.uniform(6, 14))

                        success = await page.locator('text=successfully|bonus added|redeemed|congrats').count() > 0
                        error_text = await page.locator('[class*="error"], [class*="toast-error"]').inner_text(timeout=5000) or "no error"

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
                        else:
                            if "rate limit" in error_text.lower():
                                logger.warning("Rate limit detected – stopping")
                                break

                    except Exception as inner_e:
                        logger.error(f"Code {code} error: {inner_e}")

                logger.info(f"{username} finished – claimed {claimed}")

            except Exception as e:
                logger.exception(f"Session crash for {username}: {e}")
            finally:
                if context is not None:
                    try:
                        await context.close()
                    except:
                        pass
                if browser is not None:
                    try:
                        await browser.close()
                    except:
                        pass

            await asyncio.sleep(random.uniform(180, 480))

# ────────────────────────────────────────────────
# WEBHOOK ENTRY
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
    app.add_handler(CommandHandler("entercode", enter_code))

    await app.initialize()
    await app.start()

    webhook_url = f"https://{os.environ['RAILWAY_PUBLIC_DOMAIN']}/{BOT_TOKEN}"
    await app.updater.start_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        url_path=BOT_TOKEN,
        webhook_url=webhook_url
    )

    logger.info(f"Webhook started at {webhook_url}")

    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
