"""lcr.data.filter 單元測試（通用版：刑事 + 民事程序性排除 + 年份過濾）。"""

from __future__ import annotations

from lcr.data.filter import (
    is_civil_procedural,
    is_criminal_procedural,
    is_district_court,
    is_procedural,
    is_year_in_range,
)

# --- 刑事程序性 ---

def test_criminal_procedural_jcase_sheng():
    assert is_criminal_procedural("交聲", "聲明異議")
    assert is_criminal_procedural("聲", "其他")

def test_criminal_procedural_title():
    assert is_criminal_procedural("易", "定應執行刑")
    assert is_criminal_procedural("易", "宣告沒收")
    assert is_criminal_procedural("交易", "聲明異議")

def test_criminal_substantive_kept():
    assert not is_criminal_procedural("交易", "過失傷害")
    assert not is_criminal_procedural("交訴", "公共危險")
    assert not is_criminal_procedural("易", "詐欺")


# --- 民事程序性 ---

def test_civil_procedural_jcase():
    assert is_civil_procedural("司促", "支付命令")
    assert is_civil_procedural("司票", "本票裁定")
    assert is_civil_procedural("除", "除權判決")
    assert is_civil_procedural("消債更", "更生事件")
    assert is_civil_procedural("聲", "聲請事件")

def test_civil_procedural_title_patterns():
    assert is_civil_procedural("北簡", "支付命令")
    assert is_civil_procedural("北簡", "給付信用卡消費款")
    assert is_civil_procedural("北簡", "清償借款")
    assert is_civil_procedural("訴", "公示催告")
    assert is_civil_procedural("訴", "確定訴訟費用額")

def test_civil_retain_override():
    # 「清償借款」通常排除，但若同時含「損害賠償」則保留
    assert not is_civil_procedural("訴", "損害賠償")
    assert not is_civil_procedural("訴", "侵權行為損害賠償")
    assert not is_civil_procedural("北簡", "損害賠償(交通)")
    assert not is_civil_procedural("訴", "遷讓房屋等")
    assert not is_civil_procedural("訴", "離婚")
    assert not is_civil_procedural("訴", "分割共有物")
    assert not is_civil_procedural("訴", "給付工程款")

def test_civil_substantive_kept():
    assert not is_civil_procedural("訴", "侵權行為損害賠償（交通）")
    assert not is_civil_procedural("重訴", "返還不當得利")


# --- 統一入口 ---

def test_is_procedural_routing():
    assert is_procedural("criminal", "交聲", "聲明異議")
    assert is_procedural("civil", "司促", "支付命令")
    assert not is_procedural("criminal", "交易", "過失傷害")
    assert not is_procedural("civil", "訴", "損害賠償")


# --- 年份 ---

def test_year_in_range():
    assert is_year_in_range("105")
    assert is_year_in_range("110")
    assert is_year_in_range("114")
    assert not is_year_in_range("104")   # 剛好在下限外
    assert not is_year_in_range("115")   # 剛好在上限外
    assert not is_year_in_range("99")
    assert not is_year_in_range("")
    assert not is_year_in_range("abc")


# --- 法院類型 ---

def test_is_district_court():
    assert is_district_court("臺灣士林地方法院")
    assert is_district_court("三重簡易庭")
    assert not is_district_court("最高法院")
    assert not is_district_court("臺灣高等法院")
