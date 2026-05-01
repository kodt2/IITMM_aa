from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Callable
from zoneinfo import ZoneInfo

from app.config import AppConfig
from app.schedule_client import ScheduleClient, DownloadResult
from app.schedule_processor import ScheduleProcessor
from app.schedule_repository import ScheduleRepository

logger = logging.getLogger(__name__)


class ScheduleRefreshService:
    """Периодически обновляет расписание, скачивая и обрабатывая данные."""

    def __init__(self, config: AppConfig, repository: ScheduleRepository) -> None:
        self.config = config
        self.client = ScheduleClient(config)
        self.processor = ScheduleProcessor(config)
        self.repository = repository
        self.on_refresh: Optional[Callable[[], None]] = None
        self._stop_event = asyncio.Event()

    async def refresh_now(self) -> Optional[Path]:
        """
        Немедленно выполняет обновление расписания.
        Возвращает путь к trimmed-файлу при успехе, иначе None.
        """
        storage_dir = Path(self.config.storage_path)
        try:
            storage_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error("Не удалось создать директорию %s: %s", storage_dir, e)
            return None

        raw_dir = storage_dir / "raw"
        trimmed_path = storage_dir / "trimmed_schedule.json"

        try:
            # Загрузка сырых данных (с использованием кеша)
            download_result: DownloadResult = await asyncio.to_thread(
                self.client.download_raw_schedule, raw_dir
            )

            if not download_result.is_complete():
                logger.warning(
                    "Не удалось получить данные для зданий %s, пропускаем обновление",
                    download_result.failed
                )
                # Можно вернуть None или, если хотя бы частичные данные есть, обработать?
                # По логике, репозиторий не обновляем, чтобы не терять старые данные.
                return None

            raw_payload = download_result.payloads
            trimmed = await asyncio.to_thread(self.processor.trim_payload, raw_payload)
            await asyncio.to_thread(self.processor.save_trimmed, trimmed, trimmed_path)
            await asyncio.to_thread(self.repository.refresh, trimmed)

            if self.on_refresh:
                # on_refresh может быть синхронным, оборачиваем в поток
                await asyncio.to_thread(self.on_refresh)

            logger.info("Расписание успешно обновлено, сохранено в %s", trimmed_path)
            return trimmed_path

        except Exception as e:
            logger.exception("Критическая ошибка при обновлении расписания: %s", e)
            return None

    async def run_forever(self) -> None:
        """Бесконечный цикл обновления расписания по расписанию."""
        timezone = ZoneInfo(self.config.timezone)
        logger.info("Сервис обновления расписания запущен, временная зона %s", timezone)

        while not self._stop_event.is_set():
            try:
                now = datetime.now(tz=timezone)
                next_run = self._next_run_time(now)
                wait_seconds = (next_run - now).total_seconds()
                # Защита от отрицательного или слишком малого ожидания
                if wait_seconds <= 0:
                    logger.warning(
                        "Рассчитанное время ожидания %f <= 0, устанавливаем 1 секунду",
                        wait_seconds
                    )
                    wait_seconds = 1.0

                logger.debug("Следующее обновление в %s (через %.2f с)", next_run, wait_seconds)

                # Ожидаем либо таймаут, либо сигнал остановки
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=wait_seconds
                    )
                    # Если дождались stop_event, выходим из цикла
                    break
                except asyncio.TimeoutError:
                    # Время вышло, пора обновлять
                    pass

                await self.refresh_now()

            except Exception as e:
                logger.exception("Необработанная ошибка в цикле обновления: %s", e)
                # Чтобы избежать бесконечного цикла ошибок, делаем паузу
                await asyncio.sleep(60)

        logger.info("Сервис обновления расписания остановлен")

    def _next_run_time(self, now: datetime) -> datetime:
        """Возвращает ближайшее время запуска, строго больше now."""
        sorted_hours = sorted(self.config.update_hours_moscow)
        candidates = []
        for hour in sorted_hours:
            candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            # Если кандидат уже прошёл (включая равенство), берём следующий день
            if candidate <= now:
                candidate += timedelta(days=1)
            candidates.append(candidate)

        if not candidates:
            # Если список часов пуст (не должно быть), ставим следующий день в 00:00
            logger.error("Список update_hours_moscow пуст, используется 00:00 следующего дня")
            return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

        return min(candidates)

    def stop(self) -> None:
        """Сигнал к остановке сервиса."""
        self._stop_event.set()