import json
import sys
from pathlib import Path
from collections import Counter, defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))
from lcr.config import settings
from lcr.data.filter import is_district_court, is_procedural, is_year_in_range

dataset_root = settings.dataset_root
print(f'Dataset root: {dataset_root}')

total_criminal = 0
district_criminal = 0
year_105_114_criminal = 0
non_procedural_105_114_criminal = 0

# 用來分案由統計
buckets = defaultdict(list)

for court_dir in dataset_root.iterdir():
    if not court_dir.is_dir() or not court_dir.name.endswith('刑事'):
        continue
    court_name = court_dir.name.removesuffix('刑事')
    is_dist = is_district_court(court_name)
    
    for batch in court_dir.iterdir():
        if not batch.is_dir():
            continue
        for f in batch.iterdir():
            if f.suffix != '.json':
                continue
            total_criminal += 1
            if is_dist:
                district_criminal += 1
            
            try:
                with f.open(encoding='utf-8') as fp:
                    d = json.loads(fp.read(), strict=False)
            except Exception:
                continue
                
            jyear = d.get('JYEAR', '')
            jcase = d.get('JCASE', '')
            title = d.get('JTITLE', '')
            
            if is_year_in_range(jyear, 105, 114):
                year_105_114_criminal += 1
                if is_dist and not is_procedural('criminal', jcase, title):
                    non_procedural_105_114_criminal += 1
                    buckets[title].append(d.get('JID'))

print(f'1. 原始刑事案件總數 (含所有年份、所有審級): {total_criminal:,}')
print(f'2. 地方法院刑事案件總數 (含所有年份): {district_criminal:,}')
print(f'3. 近 10 年 (105-114 年) 刑事案件總數 (不限審級、含程序性): {year_105_114_criminal:,}')
print(f'4. 近 10 年 (105-114 年) 地方法院、排除程序性刑事案件總數 (即候選案件): {non_procedural_105_114_criminal:,}')

# 統計一下分層抽樣（PER_TITLE_CAP = 50）後的筆數
sampled_50 = 0
sampled_200 = 0
for title, jids in buckets.items():
    sampled_50 += min(len(jids), 50)
    sampled_200 += min(len(jids), 200)

print(f'5. 分層抽樣後 (PER_TITLE_CAP = 50) 的總筆數: {sampled_50:,}')
print(f'6. 分層抽樣後 (PER_TITLE_CAP = 200) 的總筆數: {sampled_200:,}')
