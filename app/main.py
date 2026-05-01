from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.bot_stub import TelegramBotStub
from app.config import load_config
from app.scheduler_service import ScheduleRefreshService
from schedule_repository import ScheduleRepository
from bot import TelegramBot
from schedule_manager import ScheduleManager
from app.models import LessonEntry, TimeSlot
from datetime import  datetime

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="UNN room allocation service")
    parser.add_argument(
        "mode",
        choices=["refresh", "scheduler", "allocate", "pdf", "run"],
        help="Mode of operation",
    )
    parser.add_argument("--config", default="config.json", help="Path to config")
    parser.add_argument("--request", action="append", default=[], help="Request line")
    parser.add_argument("--pdf-path", default="output/report.pdf", help="Path to output PDF")
    return parser


async def main() -> None:
    args = build_parser().parse_args()
    config = load_config(Path(args.config))

    if args.mode == "refresh":
        path = await ScheduleRefreshService(config,ScheduleRepository()).refresh_now()
        print(f"Trimmed schedule saved: {path}")
        return

    if args.mode == "scheduler":
        await ScheduleRefreshService(config,ScheduleRepository()).run_forever()
        return

    bot = TelegramBotStub(config)

    if args.mode == "allocate":
        for row in bot.handle_allocation_requests(args.request):
            print(row)
        return

    if args.mode == "run":
        repository = ScheduleRepository()
        with open("schedule_data/trimmed_schedule.json", "r", encoding="utf-8") as f:
            trimmed_raw = json.load(f)
        trimmed_objects = []
        for d in trimmed_raw:
            # Извлекаем время из ключей begin_lesson и end_lesson
            # Формат в вашем JSON "14:40", поэтому используем "%H:%M"
            start_t = datetime.strptime(d['begin_lesson'], "%H:%M").time()
            end_t = datetime.strptime(d['end_lesson'], "%H:%M").time()

            entry = LessonEntry(
                date=datetime.strptime(d['date'], "%Y-%m-%d").date(),
                building_number=int(d['building_number']),
                auditorium=str(d['auditorium']),
                capacity=int(d['capacity']),
                slot=TimeSlot(start=start_t, end=end_t)
            )
            trimmed_objects.append(entry)

        repository.refresh(trimmed_objects)

        manager = ScheduleManager(config, repository)
        refresh_service = ScheduleRefreshService(config, repository)
        refresh_service.on_refresh = manager.refresh_allocator
        bot = TelegramBot(config, repository)
        await asyncio.gather(
            refresh_service.run_forever(),
            bot.startup()
        )
        return

    if args.mode == "pdf":
        pdf_path = bot.handle_pdf_requests(args.request, Path(args.pdf_path))
        print(f"Report saved: {pdf_path}")


if __name__ == "__main__":
    asyncio.run(main())
