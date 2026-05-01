import unittest
import asyncio
import tempfile
from unittest.mock import Mock, AsyncMock, patch, call, MagicMock
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import AppConfig, ScheduleWindowConfig
from app.schedule_client import DownloadResult
from app.scheduler_service import ScheduleRefreshService
from app.schedule_repository import ScheduleRepository


class TestScheduleRefreshService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Создаём временную директорию для тестов, чтобы избежать проблем с правами на Windows
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = self.temp_dir.name

        self.config = AppConfig(
            base_url="",
            buildings={1: 111},
            allowed_rooms={},
            big_room_min_capacity=35,
            update_hours_moscow=[4, 16],
            timezone="Europe/Moscow",
            storage_path=self.storage_path,
            schedule_window=ScheduleWindowConfig(days_before_today=1, days_after_today=30),
            pdf_contact_fields={},
            telegram_bot_token="",
        )
        self.repository = Mock(spec=ScheduleRepository)
        self.service = ScheduleRefreshService(self.config, self.repository)

    def tearDown(self):
        self.temp_dir.cleanup()

    # ----- Тесты _next_run_time -----
    def test_next_run_time_before_first_hour(self):
        config = AppConfig(
            base_url="",
            buildings={1: 111},
            allowed_rooms={},
            big_room_min_capacity=35,
            update_hours_moscow=[4, 16],
            timezone="Europe/Moscow",
            storage_path=self.storage_path,
            schedule_window=ScheduleWindowConfig(days_before_today=1, days_after_today=30),
            pdf_contact_fields={},
            telegram_bot_token="",
        )
        service = ScheduleRefreshService(config, self.repository)
        now = datetime(2026, 3, 10, 3, 0, 0, tzinfo=ZoneInfo("Europe/Moscow"))
        expected = datetime(2026, 3, 10, 4, 0, 0, tzinfo=now.tzinfo)
        self.assertEqual(service._next_run_time(now), expected)

    def test_next_run_time_between_hours(self):
        config = AppConfig(
            base_url="",
            buildings={1: 111},
            allowed_rooms={},
            big_room_min_capacity=35,
            update_hours_moscow=[4, 16],
            timezone="Europe/Moscow",
            storage_path=self.storage_path,
            schedule_window=ScheduleWindowConfig(days_before_today=1, days_after_today=30),
            pdf_contact_fields={},
            telegram_bot_token="",
        )
        service = ScheduleRefreshService(config, self.repository)
        now = datetime(2026, 3, 10, 10, 0, 0, tzinfo=ZoneInfo("Europe/Moscow"))
        expected = datetime(2026, 3, 10, 16, 0, 0, tzinfo=now.tzinfo)
        self.assertEqual(service._next_run_time(now), expected)

    def test_next_run_time_after_last_hour(self):
        config = AppConfig(
            base_url="",
            buildings={1: 111},
            allowed_rooms={},
            big_room_min_capacity=35,
            update_hours_moscow=[4, 16],
            timezone="Europe/Moscow",
            storage_path=self.storage_path,
            schedule_window=ScheduleWindowConfig(days_before_today=1, days_after_today=30),
            pdf_contact_fields={},
            telegram_bot_token="",
        )
        service = ScheduleRefreshService(config, self.repository)
        now = datetime(2026, 3, 10, 20, 0, 0, tzinfo=ZoneInfo("Europe/Moscow"))
        expected = datetime(2026, 3, 11, 4, 0, 0, tzinfo=now.tzinfo)
        self.assertEqual(service._next_run_time(now), expected)

    def test_next_run_time_exactly_at_hour(self):
        config = AppConfig(
            base_url="",
            buildings={1: 111},
            allowed_rooms={},
            big_room_min_capacity=35,
            update_hours_moscow=[4, 16],
            timezone="Europe/Moscow",
            storage_path=self.storage_path,
            schedule_window=ScheduleWindowConfig(days_before_today=1, days_after_today=30),
            pdf_contact_fields={},
            telegram_bot_token="",
        )
        service = ScheduleRefreshService(config, self.repository)
        now = datetime(2026, 3, 10, 4, 0, 0, tzinfo=ZoneInfo("Europe/Moscow"))
        # Следующий запуск должен быть сегодня в 16:00, а не завтра в 4:00
        expected = datetime(2026, 3, 10, 16, 0, 0, tzinfo=now.tzinfo)
        self.assertEqual(service._next_run_time(now), expected)

    def test_next_run_time_empty_hours(self):
        empty_hours_config = AppConfig(
            base_url="",
            buildings={1: 111},
            allowed_rooms={},
            big_room_min_capacity=35,
            update_hours_moscow=[],#пусто
            timezone="Europe/Moscow",
            storage_path=self.storage_path,
            schedule_window=ScheduleWindowConfig(days_before_today=1, days_after_today=30),
            pdf_contact_fields={},
            telegram_bot_token="",
        )
        service = ScheduleRefreshService(empty_hours_config, self.repository)
        now = datetime(2026, 3, 10, 10, 0, 0, tzinfo=ZoneInfo("Europe/Moscow"))
        expected = datetime(2026, 3, 11, 0, 0, 0, tzinfo=now.tzinfo)
        self.assertEqual(service._next_run_time(now), expected)

    # ----- Тесты refresh_now -----
    async def test_refresh_now_success(self):
        # Все зависимости подменяем синхронными моками, так как они вызываются через to_thread
        self.service.client.download_raw_schedule = Mock()
        self.service.processor.trim_payload = Mock()
        self.service.processor.save_trimmed = Mock()
        self.service.repository.refresh = Mock()
        self.service.on_refresh = Mock()

        download_result = Mock(spec=DownloadResult)
        download_result.is_complete.return_value = True
        download_result.payloads = {1: []}
        self.service.client.download_raw_schedule.return_value = download_result

        self.service.processor.trim_payload.return_value = ["trimmed"]
        trimmed_path = Path(self.storage_path) / "trimmed_schedule.json"

        result = await self.service.refresh_now()

        self.assertEqual(result, trimmed_path)
        self.service.client.download_raw_schedule.assert_called_once()
        self.service.processor.trim_payload.assert_called_once_with(download_result.payloads)
        self.service.processor.save_trimmed.assert_called_once_with(["trimmed"], trimmed_path)
        self.service.repository.refresh.assert_called_once_with(["trimmed"])
        self.service.on_refresh.assert_called_once()

    async def test_refresh_now_incomplete_download(self):
        self.service.client.download_raw_schedule = Mock()
        download_result = Mock(spec=DownloadResult)
        download_result.is_complete.return_value = False
        download_result.failed = {1}
        self.service.client.download_raw_schedule.return_value = download_result

        self.service.processor.trim_payload = Mock()
        self.service.processor.save_trimmed = Mock()
        self.service.repository.refresh = Mock()

        result = await self.service.refresh_now()

        self.assertIsNone(result)
        self.service.client.download_raw_schedule.assert_called_once()
        self.service.processor.trim_payload.assert_not_called()
        self.service.processor.save_trimmed.assert_not_called()
        self.service.repository.refresh.assert_not_called()

    async def test_refresh_now_client_exception(self):
        self.service.client.download_raw_schedule = Mock(side_effect=Exception("Network error"))
        self.service.processor.trim_payload = Mock()
        self.service.processor.save_trimmed = Mock()
        self.service.repository.refresh = Mock()

        result = await self.service.refresh_now()
        self.assertIsNone(result)
        self.service.processor.trim_payload.assert_not_called()

    async def test_refresh_now_processor_exception(self):
        self.service.client.download_raw_schedule = Mock()
        download_result = Mock(spec=DownloadResult)
        download_result.is_complete.return_value = True
        download_result.payloads = {1: []}
        self.service.client.download_raw_schedule.return_value = download_result

        self.service.processor.trim_payload = Mock(side_effect=Exception("Trim error"))
        self.service.processor.save_trimmed = Mock()
        self.service.repository.refresh = Mock()

        result = await self.service.refresh_now()
        self.assertIsNone(result)
        self.service.processor.save_trimmed.assert_not_called()
        self.service.repository.refresh.assert_not_called()

    async def test_refresh_now_save_exception(self):
        self.service.client.download_raw_schedule = Mock()
        download_result = Mock(spec=DownloadResult)
        download_result.is_complete.return_value = True
        download_result.payloads = {1: []}
        self.service.client.download_raw_schedule.return_value = download_result

        self.service.processor.trim_payload = Mock(return_value=["trimmed"])
        self.service.processor.save_trimmed = Mock(side_effect=Exception("Save error"))
        self.service.repository.refresh = Mock()

        result = await self.service.refresh_now()
        self.assertIsNone(result)
        self.service.repository.refresh.assert_not_called()

    async def test_refresh_now_repository_exception(self):
        self.service.client.download_raw_schedule = Mock()
        download_result = Mock(spec=DownloadResult)
        download_result.is_complete.return_value = True
        download_result.payloads = {1: []}
        self.service.client.download_raw_schedule.return_value = download_result

        self.service.processor.trim_payload = Mock(return_value=["trimmed"])
        self.service.processor.save_trimmed = Mock()
        self.service.repository.refresh = Mock(side_effect=Exception("Repo error"))

        result = await self.service.refresh_now()
        self.assertIsNone(result)

    # ----- Тесты run_forever -----
    async def test_run_forever_normal_cycle(self):
        """Проверяем, что при нормальной работе refresh_now вызывается один раз и цикл останавливается."""
        self.service._next_run_time = Mock()
        # Устанавливаем время следующего запуска на 0.1 секунды от now
        now = datetime.now(ZoneInfo("Europe/Moscow"))
        future_time = now + timedelta(seconds=0.1)
        self.service._next_run_time.return_value = future_time

        refresh_mock = AsyncMock()
        self.service.refresh_now = refresh_mock

        # Запускаем цикл и даём ему время выполнить одну итерацию
        task = asyncio.create_task(self.service.run_forever())
        await asyncio.sleep(0.15)  # ждём чуть больше, чем таймаут
        self.service.stop()
        await task

        refresh_mock.assert_awaited_once()

    async def test_run_forever_stop_immediately(self):
        self.service.refresh_now = AsyncMock()
        self.service.stop()
        await self.service.run_forever()
        self.service.refresh_now.assert_not_called()
