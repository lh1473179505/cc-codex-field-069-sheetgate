from __future__ import annotations
import json
from pathlib import Path

def rows(path):
    if not Path(path).is_file():
        return []
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]

def run_verify(args) -> int:
    out=Path(args.out)
    exp=json.loads(Path(args.expect).read_text())
    errors=[]
    mapping={"sales":"sales.jsonl","inventory":"inventory.jsonl","returns":"returns.jsonl"}
    for key, fn in mapping.items():
        got=rows(out/fn)
        if any((r.get("product")=="FAKE") or (r.get("region")=="west") for r in got):
            errors.append(f"{key} contains hidden-sheet decoy")
        def canon(r):
            return json.dumps(r, sort_keys=True, ensure_ascii=False)
        if sorted(map(canon, got)) != sorted(map(canon, exp[key])):
            errors.append(f"{key} rows mismatch got={got} exp={exp[key]}")
    if errors:
        print("verify failed:")
        for e in errors:
            print(" -", e)
        return 1
    print("verify ok")
    return 0
