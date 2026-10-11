"""Recover a stranded demo job only after the operator has stopped all workers."""
import argparse
from dataclasses import dataclass

from sqlalchemy import select

from app.database import SessionLocal
from app.models import ProcessingJob, Tenant

RECOVERY_REASON = 'Worker interrupted; operator confirmed all workers stopped before recovery.'


@dataclass(frozen=True)
class RecoveryResult:
    job_id: int
    before: str
    after: str
    progress: int
    retry_count: int
    changed: bool


def recover_job(job_id: int, *, apply=False, workers_stopped=False, sessions=None) -> RecoveryResult:
    if type(job_id) is not int or job_id < 1:
        raise ValueError('Job ID must be a positive integer.')
    if apply and workers_stopped is not True:
        raise ValueError('Stop the API server and all CLI workers, then confirm with --confirm-workers-stopped.')
    sessions = sessions or SessionLocal
    with sessions.begin() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.name == 'FlyRank Demo').with_for_update())
        if tenant is None:
            raise LookupError('Demo tenant not found.')
        job = db.scalar(select(ProcessingJob).where(
            ProcessingJob.id == job_id, ProcessingJob.tenant_id == tenant.id,
            ProcessingJob.job_type.in_(['vision', 'embedding']),
        ).with_for_update())
        if job is None:
            raise LookupError('Vision or embedding job not found in the demo tenant.')
        if job.status not in ('queued', 'queued_batch', 'running', 'failed'):
            raise ValueError('Only a stranded queued/running job or an already failed job can be recovered.')
        before = job.status
        changed = bool(apply and before != 'failed')
        if changed:
            job.status = 'failed'
            job.failure_reason = RECOVERY_REASON
            db.flush()
        return RecoveryResult(job.id, before, job.status, job.progress, job.retry_count, changed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job_id', type=int)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--confirm-workers-stopped', action='store_true', help='Confirm the API server and every CLI worker are stopped.')
    args = parser.parse_args()
    try:
        result = recover_job(args.job_id, apply=args.apply, workers_stopped=args.confirm_workers_stopped)
    except Exception as exc:
        print(f'Recovery stopped ({type(exc).__name__}).')
        if isinstance(exc, (ValueError, LookupError)):
            print(str(exc))
        return 1
    print(f'Job: {result.job_id}')
    print(f'Status: {result.before} -> {result.after}')
    print(f'Progress preserved: {result.progress}%')
    print(f'Retry count preserved: {result.retry_count}')
    if not args.apply:
        print('Preview only. No records changed.')
    elif result.changed:
        print('Job marked failed. Restart the API, resume the job, then dispatch it again.')
    else:
        print('Job was already failed. Existing failure details were preserved.')
    print('No Gemini requests. Existing costs and completed image/embedding work were preserved.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
