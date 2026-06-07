from app.services.dialogue_extractor import extract_script_lines


def test_extract_script_lines_marks_dialogue_and_scene_lines():
    raw_text = "\n".join(
        [
            "【第1集】",
            "[1]-1 场景：外景 城郊露天停车场 夜",
            "△ 白色轿车停在昏暗的停车场角落",
            "艾米丽（局促，低声）：อีธาน พอแค่นี้ดีกว่าไหม ที่นี่คนเยอะเกินไป",
            "伊森:กลับไปในรถ",
            "",
        ]
    )

    lines = extract_script_lines(raw_text)

    assert [line.line_no for line in lines] == [1, 2, 3, 4, 5, 6]
    assert lines[0].is_dialogue is False
    assert lines[1].is_dialogue is False
    assert lines[2].is_dialogue is False
    assert lines[3].is_dialogue is True
    assert lines[3].speaker == "艾米丽"
    assert lines[3].parenthetical == "局促，低声"
    assert lines[3].dialogue == "อีธาน พอแค่นี้ดีกว่าไหม ที่นี่คนเยอะเกินไป"
    assert lines[4].is_dialogue is True
    assert lines[4].speaker == "伊森"
    assert lines[4].dialogue == "กลับไปในรถ"
    assert lines[5].raw_line == ""
    assert lines[5].is_dialogue is False
