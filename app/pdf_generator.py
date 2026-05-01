import re
import logging
from pathlib import Path
from fpdf import FPDF

logger = logging.getLogger(__name__)


class PdfGenerator:
    MONTHS = ["", "января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]
    WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]

    def __init__(self, config=None) -> None:
        self.config = config

    def _safe_format(self, template: str, data: dict) -> str:
        """Безопасная подстановка переменных {key} из словаря data."""
        return re.sub(r'\{(\w+)\}', lambda m: str(data.get(m.group(1), m.group(0))), template)

    def _parse_params(self, args_str: str) -> dict:
        """Парсит строку параметров ключ="значение" или ключ=значение."""
        params = {}
        pattern = r'(\w+)\s*=\s*(?:"([^"]+)"|([^,)]+))'
        for match in re.finditer(pattern, args_str):
            key = match.group(1).strip()
            value = match.group(2) if match.group(2) is not None else match.group(3)
            params[key] = value.strip()
        return params

    def _draw_text(self, pdf: FPDF, args: str, global_vars: dict, item: any, align_map: dict) -> None:
        params = self._parse_params(args)
        data = global_vars.copy()

        if item:
            room_raw = str(item.assigned_room)
            room_match = re.search(r"(.+?)\s*\(\s*корпус\s*(\d+)\s*\)", room_raw, re.IGNORECASE)
            if room_match:
                room_val, building_val = room_match.group(1).strip(), room_match.group(2).strip()
            else:
                room_val, building_val = room_raw, str(getattr(item, 'building', '1'))

            req = item.request
            data.update({
                "date": req.requested_date.day, "month": self.MONTHS[req.requested_date.month],
                "year": req.requested_date.year, "weekday": self.WEEKDAYS[req.requested_date.weekday()],
                "start_time": req.start_time.strftime('%H:%M'), "end_time": req.end_time.strftime('%H:%M'),
                "room": room_val, "building": building_val
            })

        main_text = self._safe_format(params.get('text', ''), data)
        text_end = self._safe_format(params.get('text_end', ''), data)

        if 'offset_down' in params:
            pdf.set_y(pdf.get_y() + int(params['offset_down']))

        x_start = int(params.get('offset_left', pdf.l_margin))
        pdf.set_x(x_start)

        line_height = int(params.get('h', 7))
        available_width = pdf.w - pdf.r_margin - x_start

        if text_end:
            # Текст слева --- Конец справа
            pdf.write(line_height, main_text)
            end_w = pdf.get_string_width(text_end)
            pdf.set_x(pdf.w - pdf.r_margin - end_w)
            pdf.cell(w=end_w, h=line_height, text=text_end, ln=1)
        else:
            align_key = params.get('allign', params.get('align', 'left')).lower()
            if align_key in ['width', 'по_ширине']:
                words = main_text.split()
                if len(words) > 1 and pdf.get_string_width(main_text) < available_width:
                    words_w = sum(pdf.get_string_width(w) for w in words)
                    pdf.word_spacing = (available_width - words_w) / (len(words) - 1)
                    pdf.multi_cell(w=available_width, h=line_height, text=main_text, align='L')
                    pdf.word_spacing = 0
                else:
                    pdf.multi_cell(w=available_width, h=line_height, text=main_text, align='J')
            else:
                pdf.multi_cell(w=available_width, h=line_height, text=main_text, align=align_map.get(align_key, 'L'))

    def generate_rooms(self, allocations: list, output_file: Path, config_filename: str = "pdf_rooms.config") -> Path:
        raw_config = Path(config_filename).read_text(encoding="utf-8").splitlines()

        # 1. Базовые настройки (без глобального сбора корпусов)
        settings_line = next((l for l in raw_config if l.startswith('settings')), "settings()")
        s_params = self._parse_params(settings_line)
        limit = int(s_params.get('items_per_page', 10))

        # 2. Разделение на блоки (Header, Loop, Footer)
        header_lines, loop_lines, footer_lines = [], [], []
        target, in_loop = header_lines, False
        for line in raw_config:
            clean = line.strip()
            if not clean or clean.startswith('settings'): continue
            if "for all_requests:" in clean:
                in_loop, target = True, loop_lines
                continue
            if in_loop and line.strip() and not line.startswith((' ', '\t')):
                in_loop, target = False, footer_lines
            target.append(line)

        # 3. Настройка PDF
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        font_p = Path(__file__).parent.parent / s_params.get('font_path', 'fonts/times.ttf')
        if font_p.exists():
            pdf.add_font("CustomFont", fname=str(font_p))
            pdf.set_font("CustomFont", size=14)
        else:
            pdf.set_font("Helvetica", size=12)

        # 4. Генерация страниц
        chunks = [allocations[i:i + limit] for i in range(0, len(allocations), limit)] if allocations else [[]]

        for chunk in chunks:
            pdf.add_page()

            # --- ЛОКАЛЬНЫЙ СБОР КОРПУСОВ ДЛЯ ТЕКУЩЕЙ СТРАНИЦЫ ---
            page_buildings = set()
            for a in chunk:
                # Извлекаем корпус из строки "105 (корпус 2)"
                m = re.search(r"\(корпус\s*(\d+)\)", str(a.assigned_room), re.IGNORECASE)
                if m:
                    page_buildings.add(m.group(1))
                else:
                    page_buildings.add(str(getattr(a, 'building', '1')))

            sorted_b = sorted(list(page_buildings), key=lambda x: int(x) if x.isdigit() else x)
            page_vars = {"building_list": ", ".join(sorted_b)}
            # --------------------------------------------------

            # Рисуем шапку с локальными переменными страницы
            self._render_block(pdf, header_lines, page_vars)

            # Рисуем цикл
            if loop_lines:
                self._render_block(pdf, loop_lines, page_vars, chunk=chunk)

            # Рисуем подвал внизу страницы
            if footer_lines:
                pdf.set_y(-80)
                self._render_block(pdf, footer_lines, page_vars)

        pdf.output(str(output_file))
        return Path(output_file)

    def _render_block(self, pdf, lines, variables, chunk=None):
        align_map = {'left': 'L', 'center': 'C', 'right': 'R', 'width': 'J', 'по_ширине': 'J'}
        if chunk is not None:
            for item in chunk:
                for line in lines:
                    self._process_line(pdf, line, variables, item, align_map)
        else:
            for line in lines:
                self._process_line(pdf, line, variables, None, align_map)

    def _process_line(self, pdf, line, variables, item, align_map):
        content = line.strip()
        if not content or content.startswith('for '): return

        match = re.match(r'(\w+)\((.*)\)$', content)
        if match:
            cmd, args = match.groups()
            if cmd == 'font':
                p = self._parse_params(args)
                if 'px' in p: pdf.set_font(pdf.font_family, size=int(p['px']))
            elif cmd == 'text':
                self._draw_text(pdf, args, variables, item, align_map)