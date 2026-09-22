"""Live smoke test: run case_for and endorsement once each against e1 and a benign control."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments"))

from actualizer.backend import LMStudioBackend
from actualizer.referents.case_for import CaseForProvider
from actualizer.referents.endorsement import EndorsementProvider
from run_fifteen import IDEAS

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
backend = LMStudioBackend(model="gpt-oss-20b", timeout=1200)
ideas = {i: p for i, _, p in IDEAS}
out = []
for idea in ("e1", "b2"):
    for cls in [c for c in (CaseForProvider, EndorsementProvider) if c.__name__ in (sys.argv[1:] or [c.__name__])]:
        o = cls(backend=backend).offer(ideas[idea])
        row = {
            "idea": idea, "provider": o.provider_name, "status": o.status.value,
            "seconds": (o.processing_time_ms or 0) / 1000, "framing": o.framing_note,
            "error": o.error_message,
            "referents": [r.to_dict() for r in o.referents],
        }
        out.append(row)
        with (ROOT / "experiments" / "smoke_new_providers.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(idea, o.provider_name, o.status.value, [(r.kind.value, r.weight.value) for r in o.referents], flush=True)
print("done", flush=True)
