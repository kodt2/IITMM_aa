import datetime
import unittest
from unittest.mock import patch, Mock, call
import tempfile
import json
from pathlib import Path
import logging

import requests

from app.schedule_client import ScheduleClient
from app.config import AppConfig, ScheduleWindowConfig
from app.schedule_client import build_window_dates
from  datetime import date

# Тестовые данные для разных зданий (минимальные, только необходимые поля)
BUILDING_RESPONSES = {
    2: [
        {
            "auditorium": "328",
            "auditoriumAmount": 150,
            "beginLesson": "07:30",
            "building": "Корпус № 2",
            "buildingOid": 145,
            "date": "2026-02-16",
            "endLesson": "09:00",
        }
    ],
    4: [
        {
            "auditorium": "202",
            "auditoriumAmount": 150,
            "beginLesson": "07:30",
            "building": "Корпус № 4",
            "buildingOid": 148,
            "date": "2026-02-16",
            "endLesson": "09:00",
        }
    ],
    6: [
        {
            "auditorium": "513",
            "auditoriumAmount": 150,
            "beginLesson": "07:30",
            "building": "Корпус № 6",
            "buildingOid": 147,
            "date": "2026-02-16",
            "endLesson": "09:00",
        }
    ],
}


class TestScheduleClient(unittest.TestCase):
    def _make_cache_filename(self, building_num: int, day_delta: int) -> str:
        """Возвращает имя файла кеша, которое ожидает клиент для указанного здания."""
        start, finish = build_window_dates(
            today=date.today() - datetime.timedelta(days=day_delta),
            days_before=self.config.schedule_window.days_before_today,
            days_after=self.config.schedule_window.days_after_today,
        )
        return f"schedule_building_{building_num}_{start}_to_{finish}.json"
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name)

        self.config = AppConfig(
            base_url="http://example.com/{building_oid}",
            buildings={2: 123, 4: 132, 6: 355},
            allowed_rooms={2: [], 6: [], 4: []},  # не важны для клиента
            big_room_min_capacity=35,
            update_hours_moscow=[4, 16],
            timezone="Europe/Moscow",
            storage_path="tests/test_schedule_data",
            schedule_window=ScheduleWindowConfig(days_before_today=1, days_after_today=30),
            pdf_contact_fields={},
            telegram_bot_token=""
        )
        self.client = ScheduleClient(self.config)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _mock_response(self, status_code=200, json_data=None, exc=None):
        """Вспомогательный метод для создания мока ответа requests."""
        mock_resp = Mock()
        if exc:
            pass
        mock_resp.status_code = status_code
        if json_data is not None:
            mock_resp.json.return_value = json_data
        mock_resp.raise_for_status = Mock() if status_code < 400 else Mock(side_effect=requests.exceptions.HTTPError(response=mock_resp))
        return mock_resp

    # ---- Тесты ----

    @patch("requests.get")
    def test_successful_download_all(self, mock_get):
        """Все здания успешно скачиваются с первой попытки."""
        def side_effect(url, *args, **kwargs):
            for building_num, oid in self.config.buildings.items():
                if str(oid) in url:
                    resp = Mock()
                    resp.status_code = 200
                    resp.json.return_value = BUILDING_RESPONSES[building_num]
                    resp.raise_for_status = Mock()
                    return resp
            return self._mock_response(404)

        mock_get.side_effect = side_effect

        self.client.max_retries = 1

        result = self.client.download_raw_schedule(self.output_dir)

        self.assertTrue(result.is_complete())
        self.assertEqual(len(result.payloads), 3)
        self.assertEqual(result.used_cache, set())
        self.assertEqual(result.failed, set())
        files = list(self.output_dir.glob("*.json"))
        self.assertEqual(len(files), 3)

    @patch("requests.get")
    def test_partial_failure_with_cache(self, mock_get):
        """Одно здание не скачалось, но есть свежий кеш."""
        def side_effect(url, *args, **kwargs):
            for building_num, oid in self.config.buildings.items():
                if str(oid) in url:
                    if building_num == 4:
                        # Серверная ошибка
                        resp = Mock()
                        resp.status_code = 500
                        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=resp)
                        return resp
                    else:
                        resp = Mock()
                        resp.status_code = 200
                        resp.json.return_value = BUILDING_RESPONSES[building_num]
                        resp.raise_for_status = Mock()
                        return resp
            return self._mock_response(404)

        mock_get.side_effect = side_effect
        self.client.max_retries = 1

        from datetime import datetime, timedelta
        today = datetime.now().date()
        start = (today - timedelta(days=1)).isoformat()
        finish = (today + timedelta(days=30)).isoformat()
        cache_file = self.output_dir / f"schedule_building_4_{start}_to_{finish}.json"
        cache_data = [{"auditorium": "202-cached", "auditoriumAmount": 150, "beginLesson": "07:30"}]
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache_data, f)

        self.client.cache_max_age_days = 7

        result = self.client.download_raw_schedule(self.output_dir)

        self.assertTrue(result.is_complete())
        self.assertIn(4, result.used_cache)
        self.assertEqual(result.failed, set())
        self.assertEqual(len(result.payloads), 3)
        self.assertEqual(result.payloads[4], cache_data)

    @patch("requests.get")
    def test_all_fail_no_cache(self, mock_get):
        """Все здания возвращают ошибку, кеша нет."""
        def side_effect(*args, **kwargs):
            resp = Mock()
            resp.status_code = 500
            resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=resp)
            return resp

        mock_get.side_effect = side_effect
        self.client.max_retries = 1

        result = self.client.download_raw_schedule(self.output_dir)

        self.assertFalse(result.is_complete())
        self.assertEqual(result.failed, {2, 4, 6})
        self.assertEqual(result.used_cache, set())
        self.assertEqual(result.payloads, {})

    @patch("requests.get")
    def test_retry_on_timeout(self, mock_get):
        """Проверяем, что при таймауте делаются повторные попытки и в итоге успех."""
        call_count = 0

        def side_effect(url, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            for building_num, oid in self.config.buildings.items():
                if str(oid) in url:
                    if building_num == 2:
                        if call_count <= 2:
                            raise requests.exceptions.Timeout("Connection timeout")
                        else:
                            resp = Mock()
                            resp.status_code = 200
                            resp.json.return_value = BUILDING_RESPONSES[2]
                            resp.raise_for_status = Mock()
                            return resp
                    else:
                        resp = Mock()
                        resp.status_code = 200
                        resp.json.return_value = BUILDING_RESPONSES[building_num]
                        resp.raise_for_status = Mock()
                        return resp
            return self._mock_response(404)

        mock_get.side_effect = side_effect
        self.client.max_retries = 3

        result = self.client.download_raw_schedule(self.output_dir)

        self.assertTrue(result.is_complete())
        self.assertEqual(result.failed, set())
        self.assertEqual(mock_get.call_count, 5)

    @patch("requests.get")
    def test_http_4xx_no_retry(self, mock_get):
        """При клиентской ошибке 4xx повторные попытки не делаются."""
        def side_effect(url, *args, **kwargs):
            for building_num, oid in self.config.buildings.items():
                if str(oid) in url:
                    if building_num == 2:
                        resp = Mock()
                        resp.status_code = 404
                        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=resp)
                        return resp
                    else:
                        resp = Mock()
                        resp.status_code = 200
                        resp.json.return_value = BUILDING_RESPONSES[building_num]
                        resp.raise_for_status = Mock()
                        return resp
            return self._mock_response(404)

        mock_get.side_effect = side_effect
        self.client.max_retries = 3

        result = self.client.download_raw_schedule(self.output_dir)

        self.assertFalse(result.is_complete())
        self.assertEqual(result.failed, {2})
        self.assertEqual(result.used_cache, set())
        calls_for_2 = [call for call in mock_get.call_args_list if "123" in str(call)]  # oid 123 для здания 2
        self.assertEqual(len(calls_for_2), 1)

    @patch("requests.get")
    def test_corrupted_cache(self, mock_get):
        """Повреждённый кеш игнорируется."""
        def side_effect(*args, **kwargs):
            resp = Mock()
            resp.status_code = 500
            resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=resp)
            return resp

        mock_get.side_effect = side_effect
        self.client.max_retries = 1

        cache_file = self.output_dir / self._make_cache_filename(4,0)
        cache_file.write_text("this is not json", encoding="utf-8")

        result = self.client.download_raw_schedule(self.output_dir)

        self.assertFalse(result.is_complete())
        self.assertEqual(result.failed, {2, 4, 6})
        self.assertEqual(result.used_cache, set())

    @patch("requests.get")
    def test_cache_expired(self, mock_get):
        """Устаревший кеш не используется."""
        def side_effect(*args, **kwargs):
            resp = Mock()
            resp.status_code = 500
            resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=resp)
            return resp

        mock_get.side_effect = side_effect
        self.client.max_retries = 1
        self.client.cache_max_age_days = 1

        from datetime import datetime, timedelta
        cache_file = self.output_dir / self._make_cache_filename(4,-2)
        cache_file.write_text('[{"auditorium": "202"}]', encoding="utf-8")
        old_time = (datetime.now() - timedelta(days=2)).timestamp()
        import os
        os.utime(cache_file, (old_time, old_time))

        result = self.client.download_raw_schedule(self.output_dir)

        self.assertFalse(result.is_complete())
        self.assertEqual(result.failed, {2, 4, 6})
        self.assertEqual(result.used_cache, set())

    @patch("requests.get")
    def test_logging_on_cache_use(self, mock_get):
        """Проверяем, что при использовании кеша логируется предупреждение."""
        def side_effect(url, *args, **kwargs):
            for building_num, oid in self.config.buildings.items():
                if str(oid) in url:
                    if building_num == 4:
                        resp = Mock()
                        resp.status_code = 500
                        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=resp)
                        return resp
                    else:
                        resp = Mock()
                        resp.status_code = 200
                        resp.json.return_value = BUILDING_RESPONSES[building_num]
                        resp.raise_for_status = Mock()
                        return resp
            return self._mock_response(404)

        mock_get.side_effect = side_effect
        self.client.max_retries = 1

        cache_file = self.output_dir / self._make_cache_filename(4,0)
        cache_data = [{"auditorium": "202-cached"}]
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache_data, f)

        with self.assertLogs('app.schedule_client', level='INFO') as log:
            result = self.client.download_raw_schedule(self.output_dir)

        self.assertTrue(any("Использован кеш для здания 4" in message for message in log.output))


if __name__ == "__main__":
    unittest.main()