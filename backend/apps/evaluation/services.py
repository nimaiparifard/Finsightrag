import json
from pathlib import Path

from django.conf import settings

from .models import EvalRun


def import_runs(directory: str | None = None) -> int:
    """Load result files written by `finsight eval`. Idempotent per (file, mtime)."""
    root = Path(directory or settings.EVAL_RESULTS_DIR)
    created = 0
    for f in sorted(root.glob("*.json")):
        mtime = f.stat().st_mtime
        if EvalRun.objects.filter(source_file=f.name, source_mtime=mtime).exists():
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        EvalRun.objects.create(config_name=data["config"], n_questions=data["n"], metrics=data["metrics"],
                               source_file=f.name, source_mtime=mtime, dataset=data.get("dataset", "financebench"))
        created += 1
    return created
