#!/usr/bin/env python3
"""Which page texts are missing in which language (IDEA-13).

    python3 check_i18n.py          # all languages
    python3 check_i18n.py fi       # one

Lists, per language: keys English has but the language lacks (they show in English), keys the
language has that English doesn't (typos or leftovers), and whether its user guide exists.
Also: keys the page or the build use that are not in en.yaml (they would show as the bare key).
"""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
I18N = ROOT / "data" / "i18n"
en = yaml.safe_load((I18N / "en.yaml").read_text(encoding="utf-8"))

used = set()
for f in ["src/map_template.html", "src/make_map.py", "build.py"]:
    s = (ROOT / f).read_text(encoding="utf-8")
    used |= set(re.findall(r"\{\{(\w+)\}\}", s))                       # {{key}} in the page
    used |= set(re.findall(r"\bT\(\s*\"(\w+)\"\s*[,)]", s))          # T("key", …) in the script
    used |= set(re.findall(r"\bi18n\.t\(\s*\w+,\s*\"(\w+)\"", s))     # i18n.t(tx, "key", …)
used.discard("key")                                                # the word in comments: {{key}}
used |= {"weekdays_short", "_locale", "part_morning", "part_afternoon", "part_evening",
         "opt_fastest", "opt_fewest_changes", "opt_fewest_hotels",      # looked up indirectly
         "veh_train", "veh_night_train", "veh_ferry", "veh_night_ferry", "veh_bus", "veh_metro",
         "chip_metro", "chip_ferry", "chip_night_ferry", "co2_no_flight", "co2_less", "co2_same", "co2_more"}
problems = 0
missing_en = sorted(k for k in used if k not in en)
if missing_en:
    problems += 1
    print("Used but not in en.yaml:", ", ".join(missing_en))
unused = sorted(k for k in en if k not in used and not k.startswith("_"))
if unused:
    print("In en.yaml but not used:", ", ".join(unused))

langs = sys.argv[1:] or sorted(p.stem for p in I18N.glob("*.yaml") if p.stem != "en")
for lang in langs:
    f = I18N / f"{lang}.yaml"
    d = yaml.safe_load(f.read_text(encoding="utf-8")) if f.exists() else {}
    d = d or {}
    gaps = [k for k in en if k not in d]
    extra = [k for k in d if k not in en]
    guide = (ROOT / "src" / "guide" / f"{lang}.html").exists()
    print(f"\n{lang}: {len(en) - len(gaps)}/{len(en)} texts, user guide {'yes' if guide else 'NO (English shown)'}")
    if gaps:
        print("  missing (shown in English):", ", ".join(gaps))
    if extra:
        problems += 1
        print("  not in English (typo?):", ", ".join(extra))
sys.exit(1 if problems else 0)
