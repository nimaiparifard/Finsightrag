from django.core.management.base import BaseCommand

from apps.evaluation.services import import_runs


class Command(BaseCommand):
    help = "Import evaluation result JSON files produced by `finsight eval`."

    def add_arguments(self, parser):  # type: ignore[no-untyped-def]
        parser.add_argument("--dir", default=None)

    def handle(self, *args, **opts):  # type: ignore[no-untyped-def]
        self.stdout.write(f"imported {import_runs(opts['dir'])} run(s)")
