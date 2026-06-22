import re


class ResponseFormatter:
    """Applies provider-independent cleanup before responses reach the API."""

    @staticmethod
    def format(text: str) -> str:
        lines = [
            re.sub(r"[ \t]+", " ", line).strip()
            for line in text.strip().splitlines()
        ]
        clean_lines = []
        previous_was_blank = False
        for line in lines:
            is_blank = not line
            if is_blank and previous_was_blank:
                continue
            clean_lines.append(line)
            previous_was_blank = is_blank
        return "\n".join(clean_lines).strip()
