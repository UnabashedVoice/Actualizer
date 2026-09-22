"""
Live check: does the shared citation guardrail actually change output on the
two providers where invention was observed (case_for, counter_instrumentalization)?
Runs each once against e2, the idea whose earlier dossier contained a
mistitled Kershaw citation and an unplaceable WHO guideline.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments"))

from actualizer.backend import LMStudioBackend
from actualizer.referents.case_for import CaseForProvider
from actualizer.referents.counter_instrumentalization import CounterInstrumentalizationProvider
from run_fifteen import IDEAS

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
backend = LMStudioBackend(model="gpt-oss-20b", timeout=1200)
proposal = {i: p for i, _, p in IDEAS}["e2"]

out_path = ROOT / "experiments" / "smoke_citation_guardrail.jsonl"
for cls in (CaseForProvider, CounterInstrumentalizationProvider):
    o = cls(backend=backend).offer(proposal)
    row = {
        "provider": o.provider_name, "status": o.status.value,
        "seconds": (o.processing_time_ms or 0) / 1000,
        "referents": [r.to_dict() for r in o.referents],
    }
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(o.provider_name, o.status.value, [r["sources"] for r in row["referents"]], flush=True)
print("done", flush=True)
