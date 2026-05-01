import unittest
import json
import tempfile
import logging
from pathlib import Path
from datetime import date, time
from unittest.mock import Mock, patch

from app.config import AppConfig, ScheduleWindowConfig
from app.schedule_processor import ScheduleProcessor
from app.models import LessonEntry, TimeSlot


class TestScheduleProcessor(unittest.TestCase):
    def setUp(self):
        # Создаём конфигурацию с разрешёнными аудиториями для двух зданий
        self.config = AppConfig(
            base_url="",
            buildings={2: 123, 4: 456},
            allowed_rooms={
                2: ["328", "436", "513"],
                4: ["201", "202"],
            },
            big_room_min_capacity=35,
            update_hours_moscow=[4, 16],
            timezone="Europe/Moscow",
            storage_path="/tmp",
            schedule_window=ScheduleWindowConfig(days_before_today=1, days_after_today=30),
            pdf_contact_fields={},
            telegram_bot_token="",
        )
        self.processor = ScheduleProcessor(self.config)

        # Пример корректных входных данных
        self.valid_payload = {
            2: [
                {
                    "date": "2026-02-16",
                    "beginLesson": "07:30",
                    "endLesson": "09:00",
                    "auditorium": "328",
                    "auditoriumAmount": 150,
                },
                {
                    "date": "2026-02-16",
                    "beginLesson": "09:10",
                    "endLesson": "10:40",
                    "auditorium": "436",
                    "auditoriumAmount": 24,
                },
            ],
            4: [
                {
                    "date": "2026-02-16",
                    "beginLesson": "07:30",
                    "endLesson": "09:00",
                    "auditorium": "201",
                    "auditoriumAmount": 50,
                },
            ],
        }

    def test_trim_payload_success(self):
        """Должен корректно преобразовать валидные данные."""
        result = self.processor.trim_payload(self.valid_payload)

        self.assertEqual(len(result), 3)

        # Проверяем первую запись
        entry = result[0]
        self.assertEqual(entry.date, date(2026, 2, 16))
        self.assertEqual(entry.building_number, 2)
        self.assertEqual(entry.auditorium, "328")
        self.assertEqual(entry.capacity, 150)
        self.assertEqual(entry.slot.start, time(7, 30))
        self.assertEqual(entry.slot.end, time(9, 0))

    def test_trim_payload_filter_unauthorized_rooms(self):
        """Аудитории не из allowed_rooms должны отбрасываться."""
        # Добавляем запись с неразрешённой аудиторией
        payload = {
            2: [
                {
                    "date": "2026-02-16",
                    "beginLesson": "07:30",
                    "endLesson": "09:00",
                    "auditorium": "999",  # не разрешена
                    "auditoriumAmount": 150,
                },
                *self.valid_payload[2],  # разрешённые
            ]
        }
        result = self.processor.trim_payload(payload)
        self.assertEqual(len(result), 2)  # только разрешённые

    def test_trim_payload_missing_field(self):
        """Если отсутствует обязательное поле, запись пропускается с логом."""
        payload = {
            2: [
                {
                    "date": "2026-02-16",
                    "beginLesson": "07:30",
                    # нет endLesson
                    "auditorium": "328",
                    "auditoriumAmount": 150,
                }
            ]
        }
        with self.assertLogs('app.schedule_processor', level='WARNING') as log:
            result = self.processor.trim_payload(payload)
        self.assertEqual(len(result), 0)
        self.assertTrue(any("отсутствуют обязательные поля ['endLesson']" in msg for msg in log.output))

    def test_trim_payload_invalid_date(self):
        """Неверный формат даты -> пропуск записи с логом."""
        payload = {
            2: [
                {
                    "date": "2026-02-30",  # несуществующая дата
                    "beginLesson": "07:30",
                    "endLesson": "09:00",
                    "auditorium": "328",
                    "auditoriumAmount": 150,
                }
            ]
        }
        with self.assertLogs('app.schedule_processor', level='WARNING') as log:
            result = self.processor.trim_payload(payload)
        self.assertEqual(len(result), 0)
        self.assertTrue(any("неверный формат даты '2026-02-30'" in msg for msg in log.output))

    def test_trim_payload_invalid_time(self):
        """Неверный формат времени -> пропуск записи с логом."""
        payload = {
            2: [
                {
                    "date": "2026-02-16",
                    "beginLesson": "7:30",  # должен быть 07:30 для fromisoformat
                    "endLesson": "09:00",
                    "auditorium": "328",
                    "auditoriumAmount": 150,
                }
            ]
        }
        with self.assertLogs('app.schedule_processor', level='WARNING') as log:
            result = self.processor.trim_payload(payload)
        self.assertEqual(len(result), 0)
        self.assertTrue(any("неверный формат времени '7:30'" in msg for msg in log.output))

    def test_trim_payload_capacity_non_numeric(self):
        """Если auditoriumAmount не число, capacity становится 0 и логируется."""
        payload = {
            2: [
                {
                    "date": "2026-02-16",
                    "beginLesson": "07:30",
                    "endLesson": "09:00",
                    "auditorium": "328",
                    "auditoriumAmount": "N/A",
                }
            ]
        }
        with self.assertLogs('app.schedule_processor', level='WARNING') as log:
            result = self.processor.trim_payload(payload)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].capacity, 0)
        self.assertTrue(any("Невозможно преобразовать 'N/A'" in msg for msg in log.output))

    def test_trim_payload_empty_allowed_rooms_logs(self):
        """Если для здания allowed_rooms пуст, логируется предупреждение и все записи фильтруются."""
        # Изменяем конфиг для этого теста
        self.config.allowed_rooms[2] = []
        processor = ScheduleProcessor(self.config)

        payload = {
            2: self.valid_payload[2],
            4: self.valid_payload[4],
        }

        with self.assertLogs('app.schedule_processor', level='INFO') as log:
            result = processor.trim_payload(payload)

        # Должны быть только записи здания 4
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].building_number, 4)
        self.assertTrue(any("Для здания 2 не заданы разрешённые аудитории" in msg for msg in log.output))

    def test_trim_payload_skip_empty_room(self):
        """Если auditorium пустая строка, запись пропускается."""
        payload = {
            2: [
                {
                    "date": "2026-02-16",
                    "beginLesson": "07:30",
                    "endLesson": "09:00",
                    "auditorium": "",
                    "auditoriumAmount": 150,
                }
            ]
        }
        with self.assertLogs('app.schedule_processor', level='WARNING') as log:
            result = self.processor.trim_payload(payload)
        self.assertEqual(len(result), 0)
        self.assertTrue(any("пустой номер аудитории" in msg for msg in log.output))

    def test_trim_payload_field_not_string(self):
        """Если поле даты или времени не строка, запись пропускается."""
        payload = {
            2: [
                {
                    "date": 20260216,  # число
                    "beginLesson": "07:30",
                    "endLesson": "09:00",
                    "auditorium": "328",
                    "auditoriumAmount": 150,
                }
            ]
        }
        with self.assertLogs('app.schedule_processor', level='WARNING') as log:
            result = self.processor.trim_payload(payload)
        self.assertEqual(len(result), 0)
        self.assertTrue(any("поле 'date' не строка" in msg for msg in log.output))

    def test_save_and_load_trimmed(self):
        """Проверка сохранения и загрузки trimmed-файла."""
        entries = self.processor.trim_payload(self.valid_payload)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            path = Path(tmp.name)

        try:
            self.processor.save_trimmed(entries, path)
            loaded = self.processor.load_trimmed(path)

            self.assertEqual(len(loaded), len(entries))
            for orig, loaded_entry in zip(entries, loaded):
                self.assertEqual(orig.date, loaded_entry.date)
                self.assertEqual(orig.building_number, loaded_entry.building_number)
                self.assertEqual(orig.auditorium, loaded_entry.auditorium)
                self.assertEqual(orig.capacity, loaded_entry.capacity)
                self.assertEqual(orig.slot.start, loaded_entry.slot.start)
                self.assertEqual(orig.slot.end, loaded_entry.slot.end)
        finally:
            path.unlink(missing_ok=True)

    def test_load_trimmed_corrupted_file(self):
        """При загрузке повреждённого файла битые записи пропускаются, остальные загружаются."""
        entries = self.processor.trim_payload(self.valid_payload)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            path = Path(tmp.name)

        try:
            # Сохраняем, затем портим одну запись
            self.processor.save_trimmed(entries, path)
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Удаляем обязательное поле у первой записи
            del data[0]['date']
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f)

            with self.assertLogs('app.schedule_processor', level='ERROR') as log:
                loaded = self.processor.load_trimmed(path)
            self.assertEqual(len(loaded), 2)  # 3 записи, одна битая
            self.assertTrue(any("Ошибка при загрузке записи #0" in msg for msg in log.output))
        finally:
            path.unlink(missing_ok=True)

    # --- Новые тесты для покрытия указанных минусов ---

    def test_trim_payload_multiple_slots_same_room(self):
        """Несколько записей для одной аудитории в разные временные слоты должны все сохраниться."""
        payload = {
            2: [
                {
                    "date": "2026-02-16",
                    "beginLesson": "07:30",
                    "endLesson": "09:00",
                    "auditorium": "328",
                    "auditoriumAmount": 150,
                },
                {
                    "date": "2026-02-16",
                    "beginLesson": "09:10",
                    "endLesson": "10:40",
                    "auditorium": "328",
                    "auditoriumAmount": 150,
                },
                {
                    "date": "2026-02-17",
                    "beginLesson": "07:30",
                    "endLesson": "09:00",
                    "auditorium": "328",
                    "auditoriumAmount": 150,
                },
            ]
        }
        result = self.processor.trim_payload(payload)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].slot.start, time(7, 30))
        self.assertEqual(result[1].slot.start, time(9, 10))

    def test_trim_payload_start_equals_end(self):
        """Если beginLesson == endLesson, запись всё равно создаётся (слот нулевой длины)."""
        payload = {
            2: [
                {
                    "date": "2026-02-16",
                    "beginLesson": "07:30",
                    "endLesson": "07:30",
                    "auditorium": "328",
                    "auditoriumAmount": 150,
                }
            ]
        }
        result = self.processor.trim_payload(payload)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].slot.start, time(7, 30))
        self.assertEqual(result[0].slot.end, time(7, 30))

    def test_trim_payload_overlapping_slots(self):
        """Перекрывающиеся по времени слоты для одной аудитории обрабатываются обычным образом (обе записи сохраняются)."""
        payload = {
            2: [
                {
                    "date": "2026-02-16",
                    "beginLesson": "07:30",
                    "endLesson": "09:00",
                    "auditorium": "328",
                    "auditoriumAmount": 150,
                },
                {
                    "date": "2026-02-16",
                    "beginLesson": "08:00",
                    "endLesson": "10:00",
                    "auditorium": "328",
                    "auditoriumAmount": 150,
                },
            ]
        }
        result = self.processor.trim_payload(payload)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].slot.start, time(7, 30))
        self.assertEqual(result[1].slot.start, time(8, 0))


if __name__ == "__main__":
    unittest.main()