from __future__ import annotations
from datetime import datetime
from app.models import BookingRequest
import re


class RequestParser:
    """Parses lines in format: Имя Фамилия Цель дд.мм чч:мм чч:мм тип."""

    DATE_RE = re.compile(r"\b\d{2}\.\d{2}\b")
    TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")

    @staticmethod
    def parse_line(line: str) -> BookingRequest:
        # --- ищем дату ---
        date_match = RequestParser.DATE_RE.search(line)
        if not date_match:
            raise ValueError("Date not found")

        date_value = datetime.strptime(date_match.group(), "%d.%m").date()
        date_value = date_value.replace(year=datetime.now().year)

        # --- ищем время ---
        times = RequestParser.TIME_RE.findall(line)
        if len(times) < 2:
            print(line)
            raise ValueError("Expected start and end time")

        parsed_times = [
            datetime.strptime(t, "%H:%M").time()
            for t in times[:2]
        ]

        start_time, end_time = sorted(parsed_times)

        if start_time == end_time:
            raise ValueError("Start and end time must be different")

        # --- убираем дату и время из строки ---
        cleaned = RequestParser.DATE_RE.sub("", line)
        cleaned = RequestParser.TIME_RE.sub("", cleaned)

        parts = cleaned.split()

        if len(parts) < 4:
            raise ValueError("Cannot parse name/purpose/type")

        full_name = f"{parts[0]} {parts[1]}"
        room_type = parts[-1]
        purpose = " ".join(parts[2:-1])

        return BookingRequest(
            full_name=full_name,
            purpose=purpose,
            requested_date=date_value,
            start_time=start_time,
            end_time=end_time,
            room_type=room_type,
        )
