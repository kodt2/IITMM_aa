import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import datetime
import tempfile

from app.config import AppConfig
from app.models import AllocationResult, BookingRequest
from app.pdf_generator import PdfGenerator


class TestPdfGenerator(unittest.TestCase):
    def setUp(self):
        self.config = MagicMock(spec=AppConfig)
        self.generator = PdfGenerator(self.config)

        # Создаем тестовые данные БЕЗ кириллицы для совместимости с Helvetica в тестах
        req1 = BookingRequest(
            full_name='User A',
            purpose='Goal',
            requested_date=datetime.date(2026, 3, 24),
            start_time=datetime.time(18, 0),
            end_time=datetime.time(19, 0),
            room_type='502',
            phone=None
        )
        # 'корпус' -> 'bld'
        alloc1 = AllocationResult(request=req1, assigned_room='502 (bld 2)', status='ok')
        object.__setattr__(alloc1, 'building', '2')

        req2 = BookingRequest(
            full_name='User B',
            purpose='Goal',
            requested_date=datetime.date(2026, 3, 25),
            start_time=datetime.time(19, 10),
            end_time=datetime.time(19, 25),
            room_type='502',
            phone=None
        )
        alloc2 = AllocationResult(request=req2, assigned_room='no free room', status='no_free_room')

        self.allocations = [alloc1, alloc2]

    def test_parse_params_various_cases(self):
        """Проверка парсинга параметров с учетом краевых случаев."""
        cases = [
            # Идеальный случай
            ("Текст для PDF, align=left, offset_down=50", "Текст для PDF", {"align": "left", "offset_down": "50"}),
            # Значения в кавычках (содержащие запятые и пробелы)
            ('Заголовок, title="Сложный, текст", size=12', "Заголовок", {"title": "Сложный, текст", "size": "12"}),
            # Отсутствие параметров
            ("Просто строка без параметров", "Просто строка без параметров", {}),
            # Лишние пробелы вокруг '=' и лишние запятые
            ("  Грязная строка  ,  allign = right , b=  2  ", "Грязная строка", {"allign": "right", "b": "2"}),
            # Только один параметр
            ("Строка, offset_left=10", "Строка", {"offset_left": "10"})
        ]

        for args_str, expected_text, expected_params in cases:
            with self.subTest(args_str=args_str):
                text, params = self.generator._parse_params(args_str)
                self.assertEqual(text, expected_text)
                self.assertEqual(params, expected_params)

    def test_draw_text_formatting_and_dates(self):
        """
        Проверка логики подстановки переменных (даты, здания) в _draw_text
        и передачи правильных аргументов в FPDF.multi_cell.
        """
        mock_pdf = MagicMock()
        mock_pdf.l_margin = 10.0
        mock_pdf.get_y.return_value = 100.0

        args_str = "Дата: {date} {month} {year}, день: {weekday}, корп: {building}, align=center, offset_down=10"
        global_vars = {"building_list": "1, 2"}

        # Вызываем отрисовку для первой аллокации (24 марта 2026, вторник, building='2')
        self.generator._draw_text(
            pdf=mock_pdf,
            args=args_str,
            global_vars=global_vars,
            item=self.allocations[0],
            align_map={'center': 'C', 'left': 'L'}
        )

        # Проверяем, что multi_cell вызван с уже отформатированным текстом
        mock_pdf.multi_cell.assert_called_once()
        called_kwargs = mock_pdf.multi_cell.call_args.kwargs

        self.assertEqual(called_kwargs['text'], "Дата: 24 марта 2026, день: вторник, корп: 2")
        self.assertEqual(called_kwargs['align'], 'C')

        # Проверяем, что смещение по Y отработало корректно
        mock_pdf.set_y.assert_called_with(110.0)

    def test_generate_missing_config_raises_error(self):
        """Проверка поведения при отсутствующем файле конфигурации без моков."""
        bad_path = Path("/this/path/definitely/does/not/exist.config")

        with self.assertRaises(FileNotFoundError):
            self.generator.generate(self.allocations, Path("out.pdf"), config_filename=bad_path)

    def test_generate_integration(self):
        """Интеграционный тест: создание реального PDF файла с использованием только Latin-1 символов."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            config_path = tmp_path / "test.config"
            output_pdf = tmp_path / "output.pdf"

            # Используем только ASCII символы, чтобы Helvetica (fallback) не падала
            config_content = (
                "settings(font_path=missing.ttf, items_per_page=1)\n"
                "text(Header. Buildings: {building_list}, align=center)\n"
                "for all_requests:\n"
                "    text(Room: {room}, day: {date}, year: {year}, building: {building}, align=left)\n"
            )
            config_path.write_text(config_content, encoding="utf-8")

            result_path = self.generator.generate(
                allocations=self.allocations,
                output_file=output_pdf,
                config_filename=config_path
            )

            self.assertTrue(result_path.exists())
            self.assertGreater(result_path.stat().st_size, 0)


if __name__ == '__main__':
    unittest.main()