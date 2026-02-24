import asyncio
import logging
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from fastapi import FastAPI

from .bot import handlers as bot_handlers
from .bot import payments as bot_payments
from .bot.webhook import router as webhook_router, set_dispatcher
from .config import get_settings
from .routers import app as app_router
from .routers import auth as auth_router
from .routers import items as items_router
from .routers import modules as modules_router
from .routers import notify as notify_router
from .routers import prices as prices_router
from .scraper.wiki import scrape_wiki

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


async def _wiki_scheduler():
    """Run wiki scraper daily."""
    while True:
        try:
            await scrape_wiki()
        except Exception:
            log.exception("Wiki scheduler error")
        await asyncio.sleep(86400)  # 24 hours


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Telegram bot setup
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()
    dp.include_router(bot_handlers.router)
    dp.include_router(bot_payments.router)

    set_dispatcher(dp, bot)
    notify_router.set_bot(bot)

    # Set webhook (only for production HTTPS URLs)
    webhook_url = f"{settings.server_url}{settings.webhook_path}"
    if settings.server_url.startswith("https://"):
        await bot.set_webhook(webhook_url)
        log.info("Webhook set: %s", webhook_url)
    else:
        log.warning("Skipping webhook setup (non-HTTPS URL: %s)", settings.server_url)

    # Start wiki scraper in background
    scraper_task = asyncio.create_task(_wiki_scheduler())

    yield

    # Cleanup
    scraper_task.cancel()
    if settings.server_url.startswith("https://"):
        await bot.delete_webhook()
    await bot.session.close()


app = FastAPI(title="MJ Port API", version="1.0.0", lifespan=lifespan)

# Include routers
app.include_router(auth_router.router)
app.include_router(items_router.router)
app.include_router(prices_router.router)
app.include_router(modules_router.router)
app.include_router(notify_router.router)
app.include_router(app_router.router)
app.include_router(webhook_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
