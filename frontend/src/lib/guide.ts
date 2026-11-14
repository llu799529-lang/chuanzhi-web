/**
 * 使用指南与工作台「新手指南」共用的示例文字。
 * 只填进输入框、不自动提交：是否调用模型由用户决定（示例按钮不替用户花额度）。
 * backend/tests/test_hospital_gate.py 会核对：红旗示例必须命中急症规则，其余示例不能命中。
 */
export interface SymptomSample {
  label: string;
  text: string;
  /** 红旗示例：命中急症规则时直接给急症指引，不调用大模型 */
  red?: boolean;
}

export const SYMPTOM_SAMPLES: SymptomSample[] = [
  { label: "眼部示例", text: "糖尿病 8 年，最近一个月看东西有点模糊，空腹血糖 8 左右，上次查眼底是两年前。" },
  { label: "一般示例", text: "头晕三天，早上起床和突然站起来时明显，没有胸痛，也没有手脚无力。" },
  { label: "红旗示例", text: "我胸口疼，出了一身冷汗，还放射到左肩", red: true },
];

export const AGENT_SAMPLES: string[] = [
  "我有糖尿病 6 年，最近看东西模糊，需要做哪些检查？",
  "糖化血红蛋白 8.2、空腹血糖 9.1，这个结果要紧吗？",
  "糖尿病患者多久查一次眼底比较合适？",
];
