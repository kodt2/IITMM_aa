import unittest
from datetime import date, time
from app.allocator import RoomAllocator
from app.config import AppConfig, ScheduleWindowConfig
from app.models import BookingRequest, LessonEntry, TimeSlot, AllocationResult


def build_config() -> AppConfig:
    return AppConfig(
        base_url="https://example.com/{building_oid}",
        buildings={2: 145, 6: 147},
        allowed_rooms={
            2: ["140", "318", "201", "502", "324"],
            6: ["101"],
        },
        big_room_min_capacity=35,
        update_hours_moscow=[4, 16],
        timezone="Europe/Moscow",
        storage_path="schedule_data",
        schedule_window=ScheduleWindowConfig(days_before_today=1, days_after_today=30),
        pdf_contact_fields={"contact_name": "A", "contact_phone": "B"},
        telegram_bot_token="",
    )


class TestRoomAllocator(unittest.TestCase):

    def setUp(self):
        self.config = build_config()
        # Создаем базовое расписание: 24 марта, корпус 2, комната 324 занята первой парой
        self.entries = [
            LessonEntry(
                date=date(2026, 3, 24),
                building_number=2,
                auditorium="324",
                capacity=50,
                slot=TimeSlot(start=time(7, 30), end=time(9, 0)),
            ),
            # Комната 502 полностью свободна в этот день
            LessonEntry(
                date=date(2026, 3, 24),
                building_number=2,
                auditorium="502",
                capacity=60,
                slot=TimeSlot(start=time(7, 30), end=time(9, 0)),
            )
        ]

    def test_grid_expansion_logic(self):
        """
        Проверка 'магнитной сетки': запрос на 18:00-21:00 должен заблокировать
        две пары целиком (18:00-19:30 и 19:40-21:10) вместе с перерывом.
        """
        allocator = RoomAllocator(self.config, self.entries)

        # Запрос А: 18:00 - 19:00 (задевает только первую вечернюю пару)
        # Запрос Б: 19:10 - 19:25 (попадает в 'хвост' той же пары после расширения)
        requests = [
            BookingRequest("User A", "Goal", date(2026, 3, 24), time(18, 0), time(19, 0), "502"),
            BookingRequest("User B", "Goal", date(2026, 3, 24), time(19, 10), time(19, 25), "502"),
        ]

        results = allocator.allocate_batch(requests)

        print(results)

        self.assertEqual(results[0].status, "ok", "Первый запрос должен быть одобрен")
        self.assertEqual(results[1].status, "no_free_room",
                         "Второй запрос должен отклониться, так как первая бронь расширилась до 19:30")

    def test_break_time_booking(self):
        """
        Проверка бронирования строго на перемене.
        Большая перемена: 12:20 - 13:00.
        """
        allocator = RoomAllocator(self.config, self.entries)

        # Запрос строго внутри перерыва не должен конфликтовать с парами до и после
        request = BookingRequest(
            "User", "Break Event", date(2026, 3, 24),
            time(12, 30), time(12, 50), "324"
        )

        results = allocator.allocate_batch([request])
        self.assertEqual(results[0].status, "ok", "Бронирование на перемене должно быть разрешено")

    def test_example_from_user(self):
        """
        Тест примера из вопроса:
        a a a 24.03 18:00 21:00 big2
        a a a 24.03 18:00 21:00 big
        """
        allocator = RoomAllocator(self.config, self.entries)
        requests = [
            BookingRequest("a", "a", date(2026, 3, 24), time(18, 0), time(21, 0), "big2"),
            BookingRequest("a", "a", date(2026, 3, 24), time(18, 0), time(21, 0), "big"),
        ]

        results = allocator.allocate_batch(requests)

        self.assertEqual(results[0].status, "ok")
        self.assertEqual(results[1].status, "ok")
        # Проверяем, что выданы разные комнаты
        self.assertNotEqual(results[0].assigned_room, results[1].assigned_room)

    def test_partial_overlap_with_lesson(self):
        """
        Если в расписании стоит пара 7:30-9:00, а пользователь просит 8:50-9:10.
        Система должна увидеть конфликт с существующим расписанием.
        """
        allocator = RoomAllocator(self.config, self.entries)
        # Комната 324 занята парой 7:30-9:00 (см. setUp)
        request = BookingRequest(
            "User", "Goal", date(2026, 3, 24),
            time(8, 55), time(9, 0o5), "324"
        )

        results = allocator.allocate_batch([request])
        self.assertEqual(results[0].status, "no_free_room", "Должен быть конфликт с парой в расписании")


if __name__ == "__main__":
    unittest.main()