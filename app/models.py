from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from datetime import datetime
from typing import Literal
from enum import Enum

class PdfTemplate(Enum):
    SCHEDULE = "schedule"
    HALL = "hall"
    EXEMPTION = "exemption"
    TAKE_OUT = "take_out"

RoomType = Literal["any", "big", "big2", "big6", "any2", "any6"]


@dataclass(frozen=True)
class BookingRequest:
    """Incoming user request from Telegram."""

    full_name: str
    purpose: str
    requested_date: date
    start_time: time
    end_time: time
    room_type: str
    phone: str | None = None


@dataclass(frozen=True)
class TimeSlot:
    start: time
    end: time


@dataclass
class LessonEntry:
    """Trimmed schedule entry used for allocation logic only."""

    date: date
    building_number: int
    auditorium: str
    capacity: int
    slot: TimeSlot


@dataclass(frozen=True)
class AllocationResult:
    request: BookingRequest
    assigned_room: str
    status: Literal["ok", "no_free_room", "no_day_in_schedule"]


@dataclass(frozen=True)
class RoomCandidate:
    building_number: int
    room: str
    capacity: int