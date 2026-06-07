def detect_language(text: str) -> str | None:
    if not text.strip():
        return None

    arabic = sum(1 for char in text if "\u0600" <= char <= "\u06ff")
    thai = sum(1 for char in text if "\u0e00" <= char <= "\u0e7f")
    han = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    latin = sum(1 for char in text if char.isascii() and char.isalpha())

    counts = {
        "ar": arabic,
        "th": thai,
        "zh": han,
        "en": latin,
    }
    lang, score = max(counts.items(), key=lambda item: item[1])
    return lang if score > 0 else None
