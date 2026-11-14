from evals.lab_fixture import matches


def test_a_valid_json_or_image_type_alone_is_not_an_ocr_pass():
    assert not matches({"kind": "fundus", "level": 2})
    assert not matches({"kind": "other"})
    assert not matches({"kind": "lab", "items": []})
    assert not matches({"kind": "lab", "items": [{"name": "HbA1c", "value": 7.2}, {"name": "血糖", "value": 8.5}]})


def test_ocr_check_accepts_correct_chinese_or_english_names_and_numeric_strings():
    assert matches({"kind": "lab", "items": [{"name": "糖化血红蛋白", "value": "8.2"}, {"name": "Glucose", "value": 8.5}]})
