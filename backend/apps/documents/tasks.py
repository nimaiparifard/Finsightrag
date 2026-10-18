from celery import shared_task

from . import services


@shared_task(name="documents.run_ingestion_job")
def run_ingestion_job(job_id: str) -> str:
    return services.run_job(job_id).status
