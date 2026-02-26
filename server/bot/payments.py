import logging

from aiogram import Bot, Router
from aiogram.types import (
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from ..database import (
    create_subscription,
    get_module,
    get_user_by_telegram_id,
)

log = logging.getLogger(__name__)
router = Router()


async def send_module_invoice(bot: Bot, chat_id: int, module_id: str):
    module = await get_module(module_id)
    if module is None or module["is_free"]:
        await bot.send_message(chat_id, "Модуль не найден или бесплатный.")
        return

    await bot.send_invoice(
        chat_id=chat_id,
        title=f"Подписка: {module['display_name']}",
        description=f"{module.get('description', '')} — 30 дней",
        payload=f"sub:{module_id}",
        currency="XTR",
        prices=[LabeledPrice(label="30 дней", amount=module["price_stars"])],
        provider_token="",
    )


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery):
    log.info("Pre-checkout: user=%s payload=%s", query.from_user.id, query.invoice_payload)
    await query.answer(ok=True)


@router.message(lambda m: m.successful_payment is not None)
async def on_successful_payment(message: Message):
    payment = message.successful_payment
    payload = payment.invoice_payload  # "sub:fishing"
    log.info("Payment success: user=%s payload=%s amount=%s",
             message.from_user.id, payload, payment.total_amount)

    if not payload.startswith("sub:"):
        return

    module_id = payload.split(":", 1)[1]
    module = await get_module(module_id)
    if module is None:
        await message.answer("Ошибка: модуль не найден.")
        return

    user = await get_user_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer("Ошибка: пользователь не найден. Напишите /start сначала.")
        return

    try:
        await create_subscription(
            user_id=user["id"],
            module_id=module_id,
            days=30,
            stars_paid=payment.total_amount,
            transaction_id=payment.telegram_payment_charge_id,
        )
    except Exception:
        log.exception("Failed to create subscription")
        await message.answer("Ошибка при создании подписки. Обратитесь к разработчику.")
        return

    await message.answer(
        f"Подписка на «{module['display_name']}» активирована на 30 дней!\n"
        f"Перезапустите приложение для применения."
    )
