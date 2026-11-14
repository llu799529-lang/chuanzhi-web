"""无身份信息的合成化验单：验证识图与结构化数值，不代表临床准确率。"""
import io

from PIL import Image, ImageDraw, ImageFont


def image_bytes() -> bytes:
    img = Image.new("RGB", (1000, 420), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
    lines = ["SYNTHETIC LAB REPORT - DEMO ONLY",
             "Item              Result        Unit           Reference",
             "Glucose           8.5           mmol/L         3.9-6.1",
             "HbA1c             8.2           %              4.0-6.0",
             "Hemoglobin        135           g/L            115-150"]
    for i, line in enumerate(lines):
        draw.text((28, 28 + i * 68), line, font=font, fill="black")
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def matches(data: dict) -> bool:
    def has(terms, value):
        for item in data.get("items") or []:
            if any(t.lower() in str(item.get("name", "")).lower() for t in terms):
                try:
                    if abs(float(item["value"]) - value) < 0.01:
                        return True
                except (ValueError, TypeError, KeyError):
                    pass
        return False
    return (data.get("kind") == "lab" and has(["HbA1c", "糖化"], 8.2)
            and has(["Glucose", "血糖", "葡萄糖"], 8.5))
