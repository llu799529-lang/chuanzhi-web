"""质检包：把「模型说了什么」翻译成「这句话能不能在我们自己的知识库里验」。

对外只有一个入口 `verifier.verify(text, entries)`，返回三档标签与逐句明细。
设计取舍见 verifier.py 顶部注释，这里只强调一条：
**它是确定性规则，不是模型自评。** 医疗系统里让被考核方给自己打分，
比不评分更糟。
"""
from . import verifier  # noqa: F401

__all__ = ["verifier"]
