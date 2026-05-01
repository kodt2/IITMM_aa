from __future__ import annotations

from pathlib import Path

from app.allocator import RoomAllocator
from app.config import AppConfig
from app.pdf_generator import PdfGenerator
from app.request_parser import RequestParser
from app.schedule_processor import ScheduleProcessor
from allocator import *
from enum import Enum
from schedule_repository import ScheduleRepository
import locale
from models import PdfTemplate



class ScheduleManager:
    def __init__(self, config: AppConfig, repository: ScheduleRepository) -> None:
        self.config = config
        self.pdf_generator = PdfGenerator(config)
        self.repository = repository
        self.allocator = RoomAllocator(config, self.repository.entries)

    def refresh_allocator(self):
        self.allocator = RoomAllocator(self.config, self.repository.entries)

    def find_schedule(self, query: str)  -> list[str]:
        rows = query.split("\n")
        requests = [RequestParser.parse_line(row) for row in rows]
        allocations = self.allocator.allocate_batch(requests)
        locale.setlocale(locale.LC_ALL, 'ru_RU.UTF-8')
        return [
            f"{item.request.full_name} "
            f"{item.request.requested_date.strftime('%d %B')} "
            f"{item.request.start_time.strftime('%H:%M')}-{item.request.end_time.strftime('%H:%M')}: "
            f"{item.assigned_room}"
            for item in allocations
        ]
    def generate_recommendations(self, query: str):
        return

    def generate_pdf(self, template_type: PdfTemplate, query: str, output_path: Path) -> Path:
        """
        Метод вызывается после подтверждения пользователем.
        query - это тот же текст, который подавался в find_schedule.
        """
        # 1. Повторяем логику получения данных (как в find_schedule)
        rows = query.split("\n")
        requests = [RequestParser.parse_line(row) for row in rows]
        allocations = self.allocator.allocate_batch(requests)

        # 2. Определяем имя файла конфигурации в зависимости от типа шаблона
        config_files = {
            PdfTemplate.SCHEDULE: "pdf_rooms.config",
            # Здесь можно добавить другие конфиги
        }

        config_file = config_files.get(template_type, "pdf_rooms.config")

        # 3. Генерируем файл через ваш PdfGenerator
        return self.pdf_generator.generate_rooms(
            allocations = sorted(allocations, key=lambda x: x.request.requested_date),
            output_file=output_path,
            config_filename=config_file
        )
