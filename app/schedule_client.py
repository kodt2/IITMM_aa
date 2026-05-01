from __future__ import annotations

import json
import logging
import time
from datetime import date, timedelta, datetime
from pathlib import Path
from typing import Any, Optional
import os

import requests
from requests import RequestException, Timeout, HTTPError

from app.config import AppConfig

logger = logging.getLogger(__name__)


class DownloadResult:
    def __init__(self, payloads: dict[int, list[dict]], used_cache: set[int], failed: set[int]):
        self.payloads = payloads
        self.used_cache = used_cache
        self.failed = failed

    def is_complete(self) -> bool:
        return len(self.failed) == 0


def build_window_dates(today: date, days_before: int, days_after: int) -> tuple[str, str]:
    start = today - timedelta(days=days_before)
    finish = today + timedelta(days=days_after)
    return start.isoformat(), finish.isoformat()


class ScheduleClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.max_retries = getattr(config, 'request_max_retries', 3)
        self.retry_delay = getattr(config, 'request_retry_delay', 1)
        self.cache_max_age_days = getattr(config, 'cache_max_age_days', 7)

    def _find_latest_cached_file(self, building_number: int, output_dir: Path) -> Optional[Path]:
        pattern = f"schedule_building_{building_number}_*.json"
        files = list(output_dir.glob(pattern))
        if not files:
            return None
        # Сортируем по времени модификации (самый свежий последним)
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return files[0]

    def _is_cache_valid(self, file_path: Path) -> bool:
        """Проверяет, не устарел ли кеш (по дате модификации)"""
        if not file_path.exists():
            return False
        mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
        age = datetime.now() - mtime
        return age.days <= self.cache_max_age_days

    def _load_cached_file(self, file_path: Path) -> Optional[list[dict]]:
        try:
            with file_path.open('r', encoding='utf-8') as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.error("Ошибка загрузки кеша из %s: %s", file_path, e)
            return None

    def download_raw_schedule(self, output_dir: Path) -> DownloadResult:
        """Загружает расписание для всех зданий. При неудаче пытается использовать кеш."""
        output_dir.mkdir(parents=True, exist_ok=True)
        start, finish = build_window_dates(
            today=date.today(),
            days_before=self.config.schedule_window.days_before_today,
            days_after=self.config.schedule_window.days_after_today,
        )

        all_payloads: dict[int, list[dict]] = {}
        used_cache: set[int] = set()
        failed: set[int] = set()

        for building_number, building_oid in self.config.buildings.items():
            logger.info("Обработка здания %s", building_number)
            url = self.config.base_url.format(building_oid=building_oid)
            params = {"start": start, "finish": finish, "lng": 1}

            payload = None
            download_succeeded = False

            # Попытки скачать
            for attempt in range(1, self.max_retries + 1):
                try:
                    response = requests.get(url, params=params, timeout=30)
                    response.raise_for_status()
                    payload = response.json()
                    download_succeeded = True

                    # Сохраняем в новый файл
                    filename = (
                        output_dir
                        / f"schedule_building_{building_number}_{start}_to_{finish}.json"
                    )
                    with filename.open("w", encoding="utf-8") as fh:
                        json.dump(payload, fh, ensure_ascii=False, indent=2)
                    logger.debug("Файл сохранён: %s", filename)
                    break  # Успех

                except Timeout as e:
                    logger.warning("Таймаут при запросе здания %s (попытка %d/%d): %s", building_number, attempt, self.max_retries, e)
                except HTTPError as e:
                    if 500 <= e.response.status_code < 600 and attempt < self.max_retries:
                        logger.warning("Серверная ошибка %s для здания %s", e.response.status_code, building_number)
                    else:
                        logger.error("HTTP ошибка при запросе здания %s: %s", building_number, e)
                        break
                except RequestException as e:
                    logger.warning("Ошибка соединения для здания %s (попытка %d/%d): %s", building_number, attempt, self.max_retries, e)
                except json.JSONDecodeError as e:
                    logger.error("Неверный формат JSON от здания %s: %s", building_number, e)
                    break

                if attempt < self.max_retries:
                    sleep_time = self.retry_delay * (2 ** (attempt - 1))
                    logger.info("Ожидание %s с перед повторной попыткой", sleep_time)
                    time.sleep(sleep_time)
            else:
                # Все попытки исчерпаны
                logger.error("Не удалось загрузить данные для здания %s после %d попыток", building_number, self.max_retries)

            if download_succeeded:
                all_payloads[building_number] = payload
            else:
                # Пытаемся взять из кеша
                cached_file = self._find_latest_cached_file(building_number, output_dir)
                if cached_file and self._is_cache_valid(cached_file):
                    cached_payload = self._load_cached_file(cached_file)
                    if cached_payload is not None:
                        logger.info("Использован кеш для здания %s: %s", building_number, cached_file)
                        all_payloads[building_number] = cached_payload
                        used_cache.add(building_number)
                    else:
                        failed.add(building_number)
                else:
                    if cached_file:
                        logger.warning("Кеш для здания %s устарел (файл %s)", building_number, cached_file)
                    else:
                        logger.warning("Нет кеша для здания %s", building_number)
                    failed.add(building_number)

        return DownloadResult(
            payloads=all_payloads,
            used_cache=used_cache,
            failed=failed,
        )