"""化验单数值核验：识别错的数字要被拦下来提醒核对，正常的报告不能被误报。"""
import ai_analysis
import lab_check


def chk(name, value, unit="", ref="", flag="normal"):
    return lab_check.check_item({"name": name, "value": value, "unit": unit, "ref": ref, "flag": flag})


def test_unit_mixup_glucose_110_mmol():
    c = chk("空腹血糖", "110", "mmol/L", "3.9-6.1", "high")
    assert c and c["kind"] == "unit" and "mg/dL" in c["text"] and "6.1" in c["text"]


def test_unit_mixups_other_analytes():
    assert "mmol/mol" in chk("糖化血红蛋白", "65", "%", "4-6", "high")["text"]
    assert "g/dL" in chk("血红蛋白", "13.5", "g/L", "130-175")["text"]
    c = chk("肌酐", "0.9", "μmol/L", "57-111", "low")
    assert c["kind"] == "unit" and "mg/dL" in c["text"]


def test_decimal_slip_and_impossible_values():
    assert chk("钾", "41", "mmol/L", "3.5-5.3", "high")["kind"] == "decimal"
    assert chk("钠", "1400", "mmol/L", "137-147", "high")["kind"] == "decimal"
    assert chk("钾", "999", "mmol/L", "3.5-5.3", "high")["kind"] == "range"
    wbc = chk("白细胞", "5000", "10^9/L", "3.5-9.5", "high")         # 美式报告的 /μL 计数
    assert wbc["kind"] == "unit" and "/μL" in wbc["text"]


def test_reference_range_in_other_unit():
    c = chk("葡萄糖", "6.1", "mmol/L", "70-110")
    assert c and c["kind"] == "ref" and "mg/dL" in c["text"]


def test_flag_contradictions():
    assert chk("空腹血糖", "5.2", "mmol/L", "3.9-6.1", "high")["kind"] == "flag"
    assert chk("甘油三酯", "3.5", "mmol/L", "0.45-1.7", "normal")["kind"] == "flag"
    assert "↑" in chk("尿酸", "520↑", "μmol/L", "208-428", "normal")["text"]
    assert chk("尿酸", "520 H", "μmol/L", "208-428", "normal")["kind"] == "flag"


def test_unknown_analyte_uses_magnitude_only():
    assert chk("叶酸", "900", "ng/mL", "3-17", "high")["kind"] == "magnitude"
    assert chk("叶酸", "25", "ng/mL", "3-17", "high") is None
    # 正常就会高出几十上百倍的指标不做数量级检查（心梗时的肌钙蛋白、重症感染时的 C 反应蛋白）
    assert chk("超敏肌钙蛋白T", "2000", "ng/L", "<14", "high") is None
    assert chk("C反应蛋白", "1200", "mg/L", "0-10", "high") is None


def test_missing_unit_is_inferred_from_the_reference_range():
    c = chk("空腹血糖", "110", "", "3.9-6.1", "high")
    assert c and c["kind"] == "unit" and "推断为 mmol/L" in c["text"] and "mg/dL" in c["text"]
    assert chk("甘油三酯", "20", "", "0.45-1.7", "high") is None          # 重度高甘油三酯血症是真的，不能误报


def test_lookalike_names_are_not_matched_to_the_wrong_analyte():
    assert chk("红细胞沉降率", "35", "mm/h", "0-20", "high") is None
    assert chk("白细胞介素-6", "50", "pg/mL", "0-7", "high") is None
    assert chk("空腹血糖", "6.1", "mmol/L", "3.9-6.1", "high") is None     # 正好等于界值不判


def test_normal_reports_are_not_flagged():
    rows = [("空腹血糖", "7.8", "mmol/L", "3.9-6.1", "high"), ("糖化血红蛋白", "7.6", "%", "4.0-6.0", "high"),
            ("总胆固醇", "5.9", "mmol/L", "<5.2", "high"), ("低密度脂蛋白胆固醇", "3.8", "mmol/L", "<3.4", "high"),
            ("肌酐", "78", "μmol/L", "57-111", "normal"), ("血红蛋白", "135", "g/L", "130-175", "normal"),
            ("葡萄糖", "140", "mg/dL", "70-110", "high"), ("尿糖", "阴性", "", "阴性", "normal"),
            ("谷丙转氨酶", "820", "U/L", "9-50", "high"), ("尿微量白蛋白", "<0.5", "mg/L", "0-30", "normal"),
            ("白细胞", "6.2", "×10⁹/L", "3.5～9.5", "normal"), ("血小板", "1,200", "10^9/L", "125-350", "high"),
            ("平均红细胞血红蛋白浓度", "330", "g/L", "316-354", "normal"), ("尿钾", "40", "mmol/L", "", "normal"),
            ("非高密度脂蛋白胆固醇", "4.6", "mmol/L", "<4.1", "high"), ("白细胞", "5600", "/μL", "3500-9500", "normal")]
    assert [r[0] for r in rows if chk(*r)] == []


def test_lab_report_carries_checks_end_to_end():
    out = ai_analysis._norm_lab({"items": [
        {"name": "空腹血糖", "value": "110", "unit": "mmol/L", "ref": "3.9-6.1", "flag": "high"},
        {"name": "糖化血红蛋白", "value": "7.6", "unit": "%", "ref": "4-6", "flag": "high"}]})
    assert out["value_checks"] == 1 and "check" in out["items"][0] and "check" not in out["items"][1]
