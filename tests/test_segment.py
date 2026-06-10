"""lcr.data.segment 單元測試。

測試樣本依 experiments/probe_segments.py 觀察到的真實判決書結構構造。
"""

from __future__ import annotations

from lcr.data.segment import is_sheng_yi, segment

# 通常判決：主文 / 事實 / 理由 三段
THREE_PART = """臺灣宜蘭地方法院刑事判決　　95年度交訴字第34號
公　訴　人　檢察官
被　　告　甲○○
    主  文
甲○○過失傷害人，處有期徒刑參月。
    事  實
一、甲○○於民國95年間駕車，不慎擦撞前方車輛，致乙○○受傷。
    理  由
一、上開犯罪事實，業據被告坦承不諱，並有診斷證明書在卷可稽。
"""

# 簡易判決：主文 / 事實及理由 合併段
MERGED = """臺灣士林地方法院刑事簡易判決　　95年度交簡字第61號
被　　告　丙○○
    主  文
丙○○處罰金新臺幣壹萬元。
    事實及理由
一、本件犯罪事實及證據，均引用檢察官聲請簡易判決處刑書之記載。
"""

# 無標記（如附帶民事），fallback
NO_MARKER = """臺灣臺北地方法院附帶民事訴訟裁定
本件移送本院民事庭。
中華民國95年4月14日
"""


def test_three_part_layout():
    seg = segment(THREE_PART)
    assert seg.layout == "three_part"
    assert seg.is_complete
    assert "過失傷害人" in seg.main
    assert "擦撞前方車輛" in seg.facts
    assert "坦承不諱" in seg.reasoning


def test_merged_layout():
    seg = segment(MERGED)
    assert seg.layout == "merged"
    assert seg.is_complete
    assert "罰金新臺幣" in seg.main
    # 合併段同時填入 facts 與 reasoning
    assert seg.facts == seg.reasoning
    assert "引用檢察官聲請" in seg.facts


def test_no_marker_fallback():
    seg = segment(NO_MARKER)
    assert seg.layout == "none"
    assert not seg.is_complete
    # fallback：全文塞 reasoning
    assert "移送本院民事庭" in seg.reasoning


def test_empty_input():
    seg = segment("")
    assert seg.layout == "none"
    assert not seg.is_complete


def test_facts_and_reasoning_not_overlap_in_three_part():
    # 三段結構中，事實段不應含理由段內容
    seg = segment(THREE_PART)
    assert "坦承不諱" not in seg.facts


def test_is_sheng_yi():
    assert is_sheng_yi(jcase="交聲", title="聲明異議")
    assert is_sheng_yi(jcase="聲", title="其他")
    assert is_sheng_yi(jcase="交易", title="違反道路交通管理處罰條例聲明異議")
    assert not is_sheng_yi(jcase="交易", title="過失傷害")
    assert not is_sheng_yi(jcase="交簡", title="公共危險")
