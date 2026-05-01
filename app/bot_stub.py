from __future__ import annotations

from pathlib import Path

from app.allocator import RoomAllocator
from app.config import AppConfig
from app.pdf_generator import PdfGenerator
from app.request_parser import RequestParser
from app.schedule_processor import ScheduleProcessor


class TelegramBotStub:
    """Skeleton for future Telegram bot integration."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.processor = ScheduleProcessor(config)
        self.pdf_generator = PdfGenerator(config)

    def handle_allocation_requests(self, lines: list[str]) -> list[str]:
        entries = self.processor.load_trimmed(Path(self.config.storage_path) / "trimmed_schedule.json")
        requests = [RequestParser.parse_line(line) for line in lines]
        allocator = RoomAllocator(self.config, entries)
        allocations = allocator.allocate_batch(requests)
        return [f"{item.request.full_name}: {item.assigned_room}" for item in allocations]

    def handle_pdf_requests(self, lines: list[str], output_pdf: Path) -> Path:
        entries = self.processor.load_trimmed(Path(self.config.storage_path) / "trimmed_schedule.json")
        requests = [RequestParser.parse_line(line) for line in lines]
        allocator = RoomAllocator(self.config, entries)
        allocations = allocator.allocate_batch(requests)
        self.pdf_generator.generate(allocations, output_pdf)
        return output_pdf
