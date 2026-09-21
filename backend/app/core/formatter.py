import re


class ResponseFormatter:
    """Applies provider-independent cleanup before responses reach the API."""

    @staticmethod
    def format(text: str) -> str:
        # Indentation and repeated spaces are meaningful in code, lists and tables.
        # Formatting must never change the program represented by an answer.
        return text.replace("\r\n", "\n").strip()
