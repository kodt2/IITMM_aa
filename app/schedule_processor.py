import json
import logging
from datetime import date, time
from pathlib import Path
from typing import Any

from app.config import AppConfig
from app.models import LessonEntry, TimeSlot

logger = logging.getLogger(__name__)

def parse_time(value: str) -> time:
    return time.fromisoformat(value)


class ScheduleProcessor:
    """Converts raw API payload into compact occupancy data."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def _safe_int(self, value: Any, field_name: str, default: int = 0) -> int:
        """Безопасное преобразование в int с возвратом значения по умолчанию."""
        if value is None:
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            logger.warning("Невозможно преобразовать '%s' (поле %s) в int, используется %d", value, field_name, default)
            return default

    def _safe_date(self, date_str: Any, item_index: int, building: int) -> date | None:
        """Безопасный парсинг даты. Возвращает None при ошибке."""
        if not isinstance(date_str, str):
            logger.warning("Здание %s, запись #%d: поле 'date' не строка (%s), пропускаем", building, item_index,
                           type(date_str))
            return None
        try:
            return date.fromisoformat(date_str)
        except ValueError:
            logger.warning("Здание %s, запись #%d: неверный формат даты '%s', пропускаем", building, item_index,
                           date_str)
            return None

    def _safe_time(self, time_str: Any, field: str, item_index: int, building: int) -> time | None:
        """Безопасный парсинг времени. Возвращает None при ошибке."""
        if not isinstance(time_str, str):
            logger.warning("Здание %s, запись #%d: поле '%s' не строка (%s), пропускаем", building, item_index, field,
                           type(time_str))
            return None
        try:
            return parse_time(time_str)
        except ValueError:
            logger.warning("Здание %s, запись #%d: неверный формат времени '%s' в поле '%s', пропускаем", building,
                           item_index, time_str, field)
            return None

    def trim_payload(self, payload_by_building: dict[int, list[dict]]) -> list[LessonEntry]:
        """Преобразует сырой словарь занятий в список LessonEntry.
        Все невалидные записи пропускаются с логированием предупреждения.
        """
        entries: list[LessonEntry] = []

        for building_number, lessons in payload_by_building.items():
            allowed_rooms = set(self.config.allowed_rooms.get(building_number, []))
            if not allowed_rooms:
                logger.info("Для здания %d не заданы разрешённые аудитории (allowed_rooms пуст), все занятия будут отфильтрованы", building_number)

            for idx, item in enumerate(lessons):
                required_fields = ["date", "beginLesson", "endLesson", "auditorium", "auditoriumAmount"]
                missing = [f for f in required_fields if f not in item]
                if missing:
                    logger.warning(
                        "Здание %d, запись #%d: отсутствуют обязательные поля %s, пропускаем",
                        building_number, idx, missing
                    )
                    continue

                room = str(item.get("auditorium", "")).strip()
                if not room:
                    logger.warning("Здание %d, запись #%d: пустой номер аудитории, пропускаем", building_number, idx)
                    continue

                if room not in allowed_rooms:
                    continue

                lesson_date = self._safe_date(item["date"], idx, building_number)
                if lesson_date is None:
                    continue

                start_time = self._safe_time(item["beginLesson"], "beginLesson", idx, building_number)
                end_time = self._safe_time(item["endLesson"], "endLesson", idx, building_number)
                if start_time is None or end_time is None:
                    continue

                capacity = self._safe_int(item.get("auditoriumAmount"), "auditoriumAmount")

                lesson = LessonEntry(
                    date=lesson_date,
                    building_number=building_number,
                    auditorium=room,
                    capacity=capacity,
                    slot=TimeSlot(start=start_time, end=end_time),
                )
                entries.append(lesson)

        return entries

    def save_trimmed(self, entries: list[LessonEntry], output_path: Path) -> None:
        """Сохраняет обработанные записи в JSON."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = [
            {
                "date": item.date.isoformat(),
                "building_number": item.building_number,
                "auditorium": item.auditorium,
                "capacity": item.capacity,
                "begin_lesson": item.slot.start.strftime("%H:%M"),
                "end_lesson": item.slot.end.strftime("%H:%M"),
            }
            for item in entries
        ]
        with output_path.open("w", encoding="utf-8") as fh:
            json.dump(serialized, fh, ensure_ascii=False, indent=2)

    def load_trimmed(self, input_path: Path) -> list[LessonEntry]:
        """Загружает обработанные записи из JSON."""
        with input_path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)

        entries = []
        for idx, item in enumerate(payload):
            # При загрузке ожидаем, что данные корректны, но на всякий случай обработаем ошибки
            try:
                lesson_date = date.fromisoformat(item["date"])
                start = parse_time(item["begin_lesson"])
                end = parse_time(item["end_lesson"])
                entry = LessonEntry(
                    date=lesson_date,
                    building_number=int(item["building_number"]),
                    auditorium=str(item["auditorium"]),
                    capacity=int(item["capacity"]),
                    slot=TimeSlot(start=start, end=end),
                )
                entries.append(entry)
            except (KeyError, ValueError, TypeError) as e:
                logger.error("Ошибка при загрузке записи #%d из %s: %s", idx, input_path, e)
                # Пропускаем битую запись
                continue
        return entries
