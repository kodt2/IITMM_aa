from typing import List
from app.models import LessonEntry
class ScheduleRepository:
    """Хранит расписание в памяти и предоставляет доступ к нему."""

    def __init__(self):
        self._entries: list[LessonEntry] = []

    @property
    def entries(self) -> list[LessonEntry]:
        """Возвращает текущее расписание в памяти."""
        return self._entries

    def refresh(self, new_entries: list[LessonEntry]) -> None:
        """Обновляет расписание в памяти после загрузки и обработки новых данных."""
        self._entries = new_entries