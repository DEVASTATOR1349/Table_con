import sys
sys.path.insert(0, '/app')
from engine import SheetsClient, TopolEngine
from config import WORKFLOW

c = SheetsClient()
e = TopolEngine(c)

print("=== Scanning all steps ===")
for step in WORKFLOW["steps"]:
    sid, tab = c._resolve(step["trigger"]["source_tab"])
    h = c._get_headers(sid, tab)
    rows = c.get_recent_rows(sid, tab)
    
    # Check trigger
    trigger = step["trigger"]
    sc = trigger.get("status_col", "")
    sv = trigger.get("value", "")
    fields_conf = trigger.get("fields", [])
    cond = trigger.get("conditions", "ANY")
    
    print()
    print("Step {}: {} [{} rows]".format(step["id"], step["name"], len(rows)))
    print("  Source: {} ({} cols)".format(step["trigger"]["source_tab"], len(h)))
    
    hits = 0
    for row in rows:
        match = False
        rn = row.get("_row", "?")
        
        # Status col check
        if sc:
            actual = str(row.get(sc, "")).strip()
            if sv == "filled":
                match = bool(actual and actual not in ("—", "-", ""))
            else:
                match = (actual == sv)
        
        # Fields check
        if fields_conf:
            if isinstance(fields_conf, dict):
                sub_matches = []
                for col, expected in fields_conf.items():
                    actual = str(row.get(col, "")).strip()
                    if str(expected).strip() == "filled":
                        sub_matches.append(bool(actual and actual not in ("—", "-", "")))
                    else:
                        sub_matches.append(actual == str(expected).strip())
                field_match = all(sub_matches) if cond == "ALL" else any(sub_matches)
            else:
                sub_matches = [bool(str(row.get(f, "")).strip() and str(row.get(f, "")).strip() not in ("—", "-", "")) for f in fields_conf]
                field_match = all(sub_matches) if cond == "ALL" else any(sub_matches)
            
            if fields_conf and not sc:
                match = field_match
            elif sc and fields_conf:
                match = match and field_match
        
        if match:
            hits += 1
            if hits <= 3:
                print("  HIT row {}:".format(rn))
                if sc:
                    print("    {} = '{}'".format(sc, str(row.get(sc, ""))[:50]))
                if isinstance(fields_conf, dict):
                    for k, v in fields_conf.items():
                        print("    {} = '{}'".format(k, str(row.get(k, ""))[:50]))
    
    if not hits:
        # Show why last 3 rows don't match
        print("  NO HITS. Sample last 3 rows:")
        for row in rows[-3:]:
            rn = row.get("_row", "?")
            parts = []
            if sc:
                parts.append("{}='{}'".format(sc, str(row.get(sc, ""))[:40]))
            if isinstance(fields_conf, dict):
                for k, v in fields_conf.items():
                    parts.append("{}='{}'".format(k, str(row.get(k, ""))[:40]))
            print("    row {}: {}".format(rn, " | ".join(parts)))
    else:
        print("  Total HITS: {}".format(hits))
