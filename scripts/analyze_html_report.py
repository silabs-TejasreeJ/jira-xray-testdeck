from collections import Counter, defaultdict
from pathlib import Path
import re

p = Path(r"c:\Users\tejammul\Desktop\first_run_autojoin.HTM")
text = p.read_text(encoding="utf-8", errors="replace")

row_re = re.compile(
    r'<tbody class="([a-z]+) results-table-row">\s*<tr>\s*'
    r'<td class="col-time">([^<]*)</td>\s*'
    r'<td class="col-result">([^<]+)</td>\s*'
    r'<td class="col-name">([^<]+)</td>',
    re.I,
)
cid_re = re.compile(r"_C(\d{4,})\b|\bC(\d{5,})\b")

rows = row_re.findall(text)
print("parsed rows", len(rows))
print("outcomes", Counter(r[0] for r in rows))
print("results", Counter(r[2] for r in rows))

by_cid = defaultdict(list)
no_cid = 0
for outcome, time, result, name in rows:
    m = cid_re.search(name)
    phase = "call"
    if name.endswith("::setup"):
        phase = "setup"
    elif name.endswith("::teardown"):
        phase = "teardown"
    if not m:
        no_cid += 1
        print("NO CID", result, name[-120:])
        continue
    cid = "C" + (m.group(1) or m.group(2))
    by_cid[cid].append((result, phase, name.split("::")[-2] if "::" in name else name))

print("unique cids", len(by_cid), "no_cid", no_cid)
for cid, items in list(by_cid.items())[:12]:
    print(cid, items)
