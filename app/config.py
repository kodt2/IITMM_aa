from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScheduleWindowConfig:
    days_before_today: int
    days_after_today: int


@dataclass(frozen=True)
class AppConfig:
    base_url: str
    buildings: dict[int, int]
    allowed_rooms: dict[int, list[str]]
    big_room_min_capacity: int
    update_hours_moscow: list[int]
    timezone: str
    storage_path: str
    schedule_window: ScheduleWindowConfig
    pdf_contact_fields: dict[str, str]
    telegram_bot_token: str


DEFAULT_CONFIG_PATH = Path("config.json")


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    return AppConfig(
        base_url=raw["base_url"],
        buildings={int(k): int(v) for k, v in raw["buildings"].items()},
        allowed_rooms={int(k): [str(room) for room in v] for k, v in raw["allowed_rooms"].items()},
        big_room_min_capacity=int(raw["big_room_min_capacity"]),
        update_hours_moscow=[int(hour) for hour in raw["update_hours_moscow"]],
        timezone=raw["timezone"],
        storage_path=raw["storage_path"],
        schedule_window=ScheduleWindowConfig(
            days_before_today=int(raw["schedule_window"]["days_before_today"]),
            days_after_today=int(raw["schedule_window"]["days_after_today"]),
        ),
        pdf_contact_fields={str(k): str(v) for k, v in raw["pdf_contact_fields"].items()},
        telegram_bot_token=raw.get("telegram_bot_token", ""),
    )
