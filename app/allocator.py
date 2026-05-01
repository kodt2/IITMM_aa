from __future__ import annotations

from collections import defaultdict
from datetime import date, time

from app.config import AppConfig
from app.models import AllocationResult, BookingRequest, LessonEntry, RoomCandidate


def time_overlap(start_a: time, end_a: time, start_b: time, end_b: time) -> bool:
    """Строгое пересечение. Границы (например 14:30 и 14:30) не считаются пересечением."""
    return max(start_a, start_b) < min(end_a, end_b)


class RoomAllocator:
    # Жесткая сетка академических пар.
    # Время на переменах между ними система будет считать "свободным" по умолчанию.
    STANDARD_SLOTS = [
        (time(7, 30), time(9, 0)),
        (time(9, 10), time(11, 40)),
        (time(11, 50), time(12, 20)),
        (time(13, 0), time(14, 30)),
        (time(14, 40), time(16, 10)),
        (time(16, 20), time(17, 50)),
        (time(18, 0), time(19, 30)),
        (time(19, 40), time(21, 10)),
    ]

    def __init__(self, config: AppConfig, schedule_entries: list[LessonEntry]) -> None:
        self.config = config
        self.schedule_entries = schedule_entries
        self.busy_by_date_room = self._build_busy_index(schedule_entries)
        self.capacity_by_room = self._build_capacity_index(schedule_entries)

    @staticmethod
    def _build_busy_index(
            schedule_entries: list[LessonEntry],
    ) -> dict[tuple[date, int, str], list[tuple[time, time]]]:
        busy: dict[tuple[date, int, str], list[tuple[time, time]]] = defaultdict(list)
        for entry in schedule_entries:
            busy[(entry.date, entry.building_number, entry.auditorium)].append(
                (entry.slot.start, entry.slot.end)
            )
        return busy

    @staticmethod
    def _build_capacity_index(
            schedule_entries: list[LessonEntry],
    ) -> dict[tuple[int, str], int]:
        capacity: dict[tuple[int, str], int] = {}
        for entry in schedule_entries:
            key = (entry.building_number, entry.auditorium)
            capacity[key] = max(capacity.get(key, 0), entry.capacity)
        return capacity

    def allocate_batch(self, requests: list[BookingRequest]) -> list[AllocationResult]:
        results: list[AllocationResult] = []
        reserved_in_batch: dict[tuple[date, int, str], list[tuple[time, time]]] = defaultdict(list)
        schedule_days = {item.date for item in self.schedule_entries}

        for request in requests:
            if request.requested_date not in schedule_days:
                results.append(
                    AllocationResult(
                        request=request,
                        assigned_room="no day in schedule",
                        status="no_day_in_schedule",
                    )
                )
                continue

            room = self._find_free_room(request, reserved_in_batch)
            if room is None:
                results.append(
                    AllocationResult(
                        request=request,
                        assigned_room="no free room",
                        status="no_free_room",
                    )
                )
                continue

            key = (request.requested_date, room.building_number, room.room)

            # РАСШИРЕНИЕ БРОНИ:
            # Защищаем академические пары от фрагментации.
            # Если запрос был чисто на перемену, он останется в рамках перемены.
            block_start, block_end = self._expand_to_grid(request.start_time, request.end_time)
            reserved_in_batch[key].append((block_start, block_end))

            results.append(
                AllocationResult(
                    request=request,
                    assigned_room=f"{room.room} (корпус {room.building_number})",
                    status="ok",
                )
            )

        return results

    def _expand_to_grid(self, req_start: time, req_end: time) -> tuple[time, time]:
        """
        Если пользовательский запрос пересекается с академической парой,
        мы резервируем эту пару целиком, чтобы избежать "огрызков".
        """
        block_start = req_start
        block_end = req_end

        for slot_start, slot_end in self.STANDARD_SLOTS:
            if time_overlap(req_start, req_end, slot_start, slot_end):
                block_start = min(block_start, slot_start)
                block_end = max(block_end, slot_end)

        return block_start, block_end

    def _find_free_room(
            self,
            request: BookingRequest,
            reserved_in_batch: dict[tuple[date, int, str], list[tuple[time, time]]],
    ) -> RoomCandidate | None:
        candidates = self._select_candidates(request.room_type)

        for candidate in candidates:
            key = (request.requested_date, candidate.building_number, candidate.room)
            # Собираем занятость: из оригинального расписания + уже выданные в этом батче брони
            busy_slots = self.busy_by_date_room.get(key, []) + reserved_in_batch.get(key, [])

            # Ищем хотя бы одно пересечение
            # Внутри _find_free_room или перед его вызовом
            exp_start, exp_end = self._expand_to_grid(request.start_time, request.end_time)

            conflict = any(
                time_overlap(exp_start, exp_end, start, end)
                for start, end in busy_slots
            )
            if not conflict:
                return candidate

        return None

    def _select_candidates(self, room_type: str) -> list[RoomCandidate]:
        all_candidates = [
            RoomCandidate(building_number=b, room=r, capacity=cap)
            for (b, r), cap in self.capacity_by_room.items()
        ]

        if room_type == "any":
            priority = {6: 0, 2: 1, 4: 2}
            return sorted(
                all_candidates,
                key=lambda x: (priority.get(x.building_number, 999), x.capacity)
            )
        if room_type == "any2":
            return sorted(
                [c for c in all_candidates if c.building_number == 2],
                key=lambda x: x.capacity
            )
        if room_type == "any6":
            return sorted(
                [c for c in all_candidates if c.building_number == 6],
                key=lambda x: x.capacity
            )
        if room_type == "big":
            priority = {6: 0, 2: 1, 4: 2}
            candidates = [c for c in all_candidates if c.capacity >= self.config.big_room_min_capacity]
            return sorted(candidates, key=lambda x: (priority.get(x.building_number, 999), x.room))
        if room_type == "big2":
            candidates = [c for c in all_candidates if
                          c.building_number == 2 and c.capacity >= self.config.big_room_min_capacity]
            return sorted(candidates, key=lambda x: x.room)
        if room_type == "big6":
            candidates =[c for c in all_candidates if
                    c.building_number == 6 and c.capacity >= self.config.big_room_min_capacity]
            return sorted(candidates, key=lambda x: x.room)

        target = str(room_type)
        return [candidate for candidate in all_candidates if candidate.room == target]