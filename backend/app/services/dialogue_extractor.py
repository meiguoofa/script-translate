import re
from dataclasses import dataclass


DIALOGUE_RE = re.compile(
    r"^(?P<speaker>[^\s（(：:]+?)"
    r"(?:[（(](?P<paren>[^）)]*)[）)])?"
    r"[：:](?P<dialogue>.+)$"
)

SCENE_PREFIXES = ("△", "[", "【")


@dataclass(slots=True)
class ExtractedLine:
    line_no: int
    raw_line: str
    speaker: str | None
    parenthetical: str | None
    dialogue: str | None
    is_dialogue: bool


def extract_script_lines(raw_text: str) -> list[ExtractedLine]:
    extracted: list[ExtractedLine] = []
    for index, raw_line in enumerate(raw_text.split("\n"), start=1):
        stripped = raw_line.strip()
        if stripped == "":
            extracted.append(
                ExtractedLine(
                    line_no=index,
                    raw_line="",
                    speaker=None,
                    parenthetical=None,
                    dialogue=None,
                    is_dialogue=False,
                )
            )
            continue

        if stripped.startswith(SCENE_PREFIXES) or stripped.startswith("人物："):
            extracted.append(
                ExtractedLine(
                    line_no=index,
                    raw_line=stripped,
                    speaker=None,
                    parenthetical=None,
                    dialogue=None,
                    is_dialogue=False,
                )
            )
            continue

        match = DIALOGUE_RE.match(stripped)
        if match:
            extracted.append(
                ExtractedLine(
                    line_no=index,
                    raw_line=stripped,
                    speaker=match.group("speaker").strip(),
                    parenthetical=(match.group("paren") or None),
                    dialogue=match.group("dialogue").strip(),
                    is_dialogue=True,
                )
            )
            continue

        extracted.append(
            ExtractedLine(
                line_no=index,
                raw_line=stripped,
                speaker=None,
                parenthetical=None,
                dialogue=None,
                is_dialogue=False,
            )
        )

    return extracted
