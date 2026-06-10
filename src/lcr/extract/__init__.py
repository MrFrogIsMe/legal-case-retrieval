"""抽取模組子套件。

三層架構：
  regex_extractor.py   → 法條、金額、日期（規則型，0 成本）
  llama_extractor.py   → 判決結果、刑度、事實摘要（本地 Llama）
  openai_extractor.py  → GPT batch 抽取（付費，作為對比/補強）
"""
