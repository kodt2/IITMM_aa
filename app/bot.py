from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.models import PdfTemplate

from pathlib import Path
from app.allocator import RoomAllocator
from app.config import AppConfig
from app.pdf_generator import PdfGenerator
from app.request_parser import RequestParser
from app.schedule_processor import ScheduleProcessor
from app.schedule_repository import ScheduleRepository
from app.schedule_manager import ScheduleManager
class State(Enum):
    MAIN = 1
    SCHEDULE_QUERY = 2
    FILE_MODE_SELECT = 3
    FILE_HALL_TEXT = 4
    FILE_EXEMPTION_TEXT = 5
    FILE_TAKE_OUT_TEXT = 6


@dataclass(frozen=True)
class Action:
    SCHEDULE_MODE: str = "mode:schedule"
    FILE_MODE: str = "mode:file"
    GENERATE_FROM_SCHEDULE: str = "schedule:generate_pdf"
    GIVE_RECOMMENDATIONS: str = "schedule:give_RECOMMENDATIONS"
    GENERATE_HALL: str = "file:hall"
    GENERATE_EXEMPTION: str = "file:exemption"
    GENERATE_TAKE_OUT: str = "file:take-out"
    BACK_TO_MAIN: str = "nav:main"

BOT_VERSION = "1.0.2"
BOT_DESCRIPTION = (
            "Multi-mode bot (stub): schedule search and multi-template text-to-PDF generation"
)
logging.basicConfig(
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self, config: AppConfig, repository: ScheduleRepository) -> None:
        self.config = config
        self.pdf_generator = PdfGenerator(config)
        self.manager = ScheduleManager(config,repository)


    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> State:
        """Show entry point with mode selection."""
        keyboard = [
            [InlineKeyboardButton("🔎 Schedule search mode", callback_data=Action.SCHEDULE_MODE)],
            [InlineKeyboardButton("📄 File generation mode", callback_data=Action.FILE_MODE)],
        ]

        target = update.effective_message or update.callback_query.message
        await target.reply_text(
            "Выберите режим:\n"
            "• Поиск в расписании\n"
            "• Создание других служебок",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return State.MAIN


    async def version(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Return bot version and description."""
        await update.effective_message.reply_text(
            f"Version: {BOT_VERSION}\nDescription: {BOT_DESCRIPTION}"
        )

    def file_submode_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🏢 Hall PDF", callback_data=Action.GENERATE_HALL)],
                [
                    InlineKeyboardButton(
                        "🧾 Exemption PDF", callback_data=Action.GENERATE_EXEMPTION
                    )
                ],
                [InlineKeyboardButton("📦 Take-out PDF", callback_data=Action.GENERATE_TAKE_OUT)],
                [InlineKeyboardButton("⬅️ Back to main menu", callback_data=Action.BACK_TO_MAIN)],
            ]
        )

    async def main_mode_router(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> State:
        """Handle top-level mode selection."""
        query = update.callback_query
        await query.answer()

        if query.data == Action.SCHEDULE_MODE:
            await query.edit_message_text(
                "Schedule search mode selected.\n"
                "Send schedule query text (e.g., group, teacher, date)."
            )
            return State.SCHEDULE_QUERY

        if query.data == Action.FILE_MODE:
            await query.edit_message_text(
                "File generation mode selected. Choose a PDF template.",
                reply_markup=self.file_submode_keyboard(),
            )
            return State.FILE_MODE_SELECT

        await query.edit_message_text("Unknown mode. Use /start to begin again.")

    async def schedule_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> State:
        """Stub schedule lookup and show direct PDF generation button."""
        user_query = (update.effective_message.text or "").strip()

        if not user_query:
            await update.effective_message.reply_text("Please send a non-empty schedule query.")
            return State.SCHEDULE_QUERY

        context.user_data["last_schedule_query"] = user_query

        keyboard = [
            [
                InlineKeyboardButton(
                    "🧾 Generate PDF from this schedule",
                    callback_data=Action.GENERATE_FROM_SCHEDULE,)
            ],
            [InlineKeyboardButton("⬅️ Back to main menu", callback_data=Action.BACK_TO_MAIN),
             InlineKeyboardButton("Получить рекомендации", callback_data=Action.GIVE_RECOMMENDATIONS)
             ],
        ]
        result = self.manager.find_schedule(user_query)

        reply_text=""
        for resp in result:
            reply_text+=resp+"\n"
        await update.effective_message.reply_text(
            reply_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return State.SCHEDULE_QUERY

    async def schedule_post_actions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> State:
        """Handle direct schedule-to-PDF generation and back navigation."""
        query = update.callback_query
        await query.answer()

        if query.data == Action.GENERATE_FROM_SCHEDULE:
            # 1. Получаем сохраненный текст последнего запроса
            lookup = context.user_data.get("last_schedule_query")

            if not lookup:
                await query.edit_message_text("Ошибка: не удалось найти последний запрос.")
                return State.SCHEDULE_QUERY

            await query.edit_message_text(f"⏳ Генерирую PDF для запроса: {lookup}...")

            # 2. Определяем путь для сохранения (например, в папку output)
            output_dir = Path("pdf_output")
            output_dir.mkdir(exist_ok=True)  # Создаем папку, если её нет
            pdf_path = output_dir / f"schedule_{update.effective_user.id}.pdf"

            try:
                # 3. Генерируем PDF через ваш ScheduleManager
                # Здесь я использую PdfTemplate.SCHEDULE (замените на ваш актуальный тип)
                generated_file = self.manager.generate_pdf(
                    template_type=PdfTemplate.SCHEDULE,
                    query=lookup,
                    output_path=pdf_path
                )

                # 4. Отправляем файл пользователю
                with open(generated_file, "rb") as doc:
                    await query.message.reply_document(
                        document=doc,
                        filename=f"schedule_{lookup}.pdf",
                        caption=f"✅ Ваше расписание по запросу: {lookup}"
                    )

                await query.message.chat.send_message(
                    "Вы можете продолжить работу в режиме планирования"
                    " или нажать /start для перехода в главное меню."
                )

            except Exception as e:
                await query.message.reply_text(f"❌ Ошибка при генерации PDF: {e}")

            return State.SCHEDULE_QUERY

        if query.data == Action.BACK_TO_MAIN:
            await query.edit_message_text("Возвращаемся в главное меню...")
            return await self.start(update, context)

        return State.SCHEDULE_QUERY

    async def file_mode_router(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> State:
        """Route to concrete file-generation sub-mode."""
        query = update.callback_query
        await query.answer()

        if query.data == Action.GENERATE_HALL:
            await query.edit_message_text("Выбран режим создания служебки на Холл")
            return State.FILE_HALL_TEXT

        if query.data == Action.GENERATE_EXEMPTION:
            await query.edit_message_text("Выбран режим создания служебки Освобождения")
            return State.FILE_EXEMPTION_TEXT

        if query.data == Action.GENERATE_TAKE_OUT:
            await query.edit_message_text("Выбран режим создания служебки Внос-Вынос")
            return State.FILE_TAKE_OUT_TEXT

        if query.data == Action.BACK_TO_MAIN:
            await query.edit_message_text("Возвращаемся в главное меню...")
            return await self.start(update, context)

        return State.FILE_MODE_SELECT


    async def _file_generation_common(
        self,
        update: Update,
        template_name: str,
        output_filename: str,
        stay_in_state: State,
    ) -> State:
        text_data = (update.effective_message.text or "").strip()

        if not text_data:
            await update.effective_message.reply_text("Please send non-empty text input.")
            return stay_in_state

        await update.effective_message.reply_text(
            f"📄 {template_name} PDF generation completed (stub).\n"
            f"Input length: {len(text_data)} chars\n"
            f"Generated file: {output_filename}"
        )
        return stay_in_state


    async def generate_hall_pdf(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> State:
        """Stub Hall PDF generation from text input."""
        return await self._file_generation_common(
            update=update,
            template_name="Hall",
            output_filename="hall_stub.pdf",
            stay_in_state=State.FILE_HALL_TEXT,
        )


    async def generate_exemption_pdf(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> State:
        """Stub Exemption PDF generation from text input."""
        return await self._file_generation_common(
            update=update,
            template_name="Exemption",
            output_filename="exemption_stub.pdf",
            stay_in_state=State.FILE_EXEMPTION_TEXT,
        )


    async def generate_take_out_pdf(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> State:
        """Stub Take-out PDF generation from text input."""
        return await self._file_generation_common(
            update=update,
            template_name="Take-out",
            output_filename="take_out_stub.pdf",
            stay_in_state=State.FILE_TAKE_OUT_TEXT,
        )


    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Stop active conversation."""
        await update.effective_message.reply_text("Отменено. Чтобы начать заново, используйте /start.")
        return ConversationHandler.END


    def build_application(self, token: str) -> Application:
        """Build and configure Telegram application."""
        app = Application.builder().token(token).build()

        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start)],
            states={
                State.MAIN: [CallbackQueryHandler(self.main_mode_router, pattern=r"^mode:")],
                State.SCHEDULE_QUERY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.schedule_search),
                    CallbackQueryHandler(self.schedule_post_actions, pattern=r"^(schedule:|nav:main$)"),
                ],
                State.FILE_MODE_SELECT: [
                    CallbackQueryHandler(self.file_mode_router, pattern=r"^(file:|nav:main$)")
                ],
                State.FILE_HALL_TEXT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.generate_hall_pdf),
                ],
                State.FILE_EXEMPTION_TEXT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.generate_exemption_pdf),
                ],
                State.FILE_TAKE_OUT_TEXT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.generate_take_out_pdf),
                ],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)],
            allow_reentry=True,
        )

        app.add_handler(conv_handler)
        app.add_handler(CommandHandler("version", self.version))
        return app

    async def startup(self) -> None:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            raise RuntimeError("Set TELEGRAM_BOT_TOKEN environment variable")

        # Создаем объект приложения
        app = self.build_application(token)

        logger.info("Starting bot in async mode")

        # Пошаговый асинхронный запуск:
        await app.initialize()
        if app.post_init:
            await app.post_init(app)

        await app.updater.start_polling()
        await app.start()

        logger.info("Bot is now polling for updates")

        # ВАЖНО: Если этот метод — единственное, что держит программу запущенной,
        # нужно добавить бесконечный цикл, иначе приложение завершится сразу после старта.
        # Если же у вас параллельно работает FastAPI/другой сервис, то управление вернется им.