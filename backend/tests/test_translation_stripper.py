from app.services.translation_stripper import strip_translation_from_line, strip_translations_from_text


def test_strip_ascii_tail_translation_after_dialogue_separator():
    cleaned, stripped = strip_translation_from_line("艾米丽（局促，低声）：hello(你好)")

    assert stripped is True
    assert cleaned == "艾米丽（局促，低声）：hello"


def test_strip_full_width_tail_translation_after_dialogue_separator():
    cleaned, stripped = strip_translation_from_line("艾米丽：hello（你好）")

    assert stripped is True
    assert cleaned == "艾米丽：hello"


def test_keep_parenthetical_before_dialogue_separator():
    cleaned, stripped = strip_translation_from_line("艾米丽（局促，低声）：hello")

    assert stripped is False
    assert cleaned == "艾米丽（局促，低声）：hello"


def test_keep_scene_parenthetical_without_dialogue_separator():
    cleaned, stripped = strip_translation_from_line("△ 场景说明（不要删除）")

    assert stripped is False
    assert cleaned == "△ 场景说明（不要删除）"


def test_keep_character_list_parentheticals_after_metadata_prefix():
    line = "人物：西蒙·蒙斯普林（Simon Moonspring，白发黑袍狼王）、雷文（Raven，卷发年轻男子）"

    cleaned, stripped = strip_translation_from_line(line)

    assert stripped is False
    assert cleaned == line


def test_keep_inner_dialogue_parenthetical_and_strip_last_translation():
    cleaned, stripped = strip_translation_from_line("伊森: 原文对白 (里面有原始括号)(translation)")

    assert stripped is True
    assert cleaned == "伊森: 原文对白 (里面有原始括号)"


def test_keep_empty_and_no_separator_lines():
    assert strip_translation_from_line("") == ("", False)
    assert strip_translation_from_line("旁白内容(不要删除)") == ("旁白内容(不要删除)", False)


def test_strip_translation_with_trailing_spaces():
    cleaned, stripped = strip_translation_from_line("伊森: hello(你好)   ")

    assert stripped is True
    assert cleaned == "伊森: hello   "


def test_strip_translations_from_text_counts_lines():
    result = strip_translations_from_text("伊森: hello(你好)\n△ 场景说明（保留）\n艾米丽：bye（再见）")

    assert result.line_count == 3
    assert result.stripped_count == 2
    assert result.cleaned_text == "伊森: hello\n△ 场景说明（保留）\n艾米丽：bye"
