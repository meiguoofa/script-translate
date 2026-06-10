from dataclasses import dataclass


@dataclass(slots=True)
class StripResult:
    cleaned_text: str
    line_count: int
    stripped_count: int


def strip_translation_from_line(line: str) -> tuple[str, bool]:
    stripped_right = line.rstrip()
    trailing = line[len(stripped_right) :]
    separator_index = max(stripped_right.rfind(":"), stripped_right.rfind("："))
    if separator_index == -1:
        return line, False

    if stripped_right.endswith(")"):
        open_char = "("
        close_char = ")"
    elif stripped_right.endswith("）"):
        open_char = "（"
        close_char = "）"
    else:
        return line, False

    depth = 0
    start_index = -1
    for index in range(len(stripped_right) - 1, separator_index, -1):
        char = stripped_right[index]
        if char == close_char:
            depth += 1
        elif char == open_char:
            depth -= 1
            if depth == 0:
                start_index = index
                break

    if start_index <= separator_index:
        return line, False

    return stripped_right[:start_index].rstrip() + trailing, True


def strip_translations_from_text(text: str) -> StripResult:
    lines = text.split("\n")
    cleaned_lines: list[str] = []
    stripped_count = 0
    for line in lines:
        cleaned_line, stripped = strip_translation_from_line(line)
        cleaned_lines.append(cleaned_line)
        if stripped:
            stripped_count += 1

    return StripResult(
        cleaned_text="\n".join(cleaned_lines),
        line_count=len(lines),
        stripped_count=stripped_count,
    )
