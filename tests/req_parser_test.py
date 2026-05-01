import unittest
from datetime import date, time

from app.allocator import RoomAllocator
from app.config import AppConfig, ScheduleWindowConfig
from app.models import BookingRequest, LessonEntry, TimeSlot


def build_config() -> AppConfig:
    return AppConfig(
        base_url="https://example.com/{building_oid}",
        buildings={2: 145, 6: 147},
        allowed_rooms={2: ["140", "318"], 6: ["101"]},
        big_room_min_capacity=35,
        update_hours_moscow=[4, 16],
        timezone="Europe/Moscow",
        storage_path="schedule_data",
        schedule_window=ScheduleWindowConfig(days_before_today=1, days_after_today=30),
        pdf_contact_fields={"contact_name": "A", "contact_phone": "B"},
        telegram_bot_token="",
    )


class TestRoomAllocator(unittest.TestCase):
    def test_allocator_respects_batch_conflicts(self):
        config = build_config()
        entries = [
            LessonEntry(
                date=date(2026, 2, 12),
                building_number=2,
                auditorium="140",
                capacity=42,
                slot=TimeSlot(start=time(7, 30), end=time(9, 0)),
            ),
            LessonEntry(
                date=date(2026, 2, 12),
                building_number=2,
                auditorium="318",
                capacity=30,
                slot=TimeSlot(start=time(12, 0), end=time(13, 30)),
            ),
        ]
        allocator = RoomAllocator(config, entries)

        requests = [
            BookingRequest("Иван Иванов", "Цель", date(2026, 2, 12), time(9, 0), time(10, 0), "any"),
            BookingRequest("Петр Петров", "Цель", date(2026, 2, 12), time(9, 30), time(10, 30), "any"),
        ]

        results = allocator.allocate_batch(requests)

        self.assertEqual(results[0].status, "ok")
        self.assertEqual(results[1].status, "ok")
        self.assertNotEqual(results[0].assigned_room, results[1].assigned_room)

    def test_allocator_handles_no_day(self):
        allocator = RoomAllocator(build_config(), [])
        request = BookingRequest("Иван Иванов", "Цель", date(2026, 2, 12), time(9, 0), time(10, 0), "any")

        result = allocator.allocate_batch([request])[0]

        self.assertEqual(result.status, "no_day_in_schedule")
        self.assertEqual(result.assigned_room, "no day in schedule")


if __name__ == "__main__":
    unittest.main()