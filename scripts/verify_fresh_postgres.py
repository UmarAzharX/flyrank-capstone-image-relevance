"""Check migrations and seeding in a temporary PostgreSQL 16 container."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

DATABASE_NAME = 'flyrank_setup_check'
LABEL = 'flyrank.capstone.setup-check'


def scratch_environment(port: int, password: str) -> dict[str, str]:
    if not 1 <= port <= 65535:
        raise ValueError('Invalid temporary port.')
    environment = dict(os.environ)
    environment.update(DATABASE_URL=f'postgresql+psycopg://postgres:{password}@127.0.0.1:{port}/{DATABASE_NAME}',
                       GEMINI_API_KEY='', AI_MAX_CALLS='0', AI_BUDGET_USD='0',
                       ENVIRONMENT='setup-check', PYTHONDONTWRITEBYTECODE='1')
    return environment


def run_command(command: list[str], *, cwd=None, env=None, timeout=60) -> subprocess.CompletedProcess:
    result = subprocess.run(command, cwd=cwd, env=env, timeout=timeout, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Check command failed; raw output withheld.')
    return result


def inspect_database(project: Path) -> dict:
    # Imports happen only in the child after overriding settings through its environment.
    sys.path.insert(0, str(project))
    from sqlalchemy import func, inspect, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import IntegrityError
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from app.config import settings
    from app.database import Base, engine
    from app.models import Image, Tenant

    url = make_url(settings.database_url)
    if (url.drivername != 'postgresql+psycopg' or url.host != '127.0.0.1'
            or url.database != DATABASE_NAME or url.port == 5432
            or settings.gemini_api_key or settings.ai_max_calls != 0):
        raise ValueError('Refusing inspection outside the isolated setup-check database.')
    manifest = json.loads((project / 'data/images.json').read_text(encoding='utf-8'))
    expected = {row['id']: (row['filename'], row['source'], row['source_page_url']) for row in manifest}
    checks = []

    def require(name: str, condition: bool):
        checks.append({'name': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(f'Fresh database check failed: {name}')

    with engine.begin() as connection:
        require('postgresql_16', str(connection.execute(text('SHOW server_version')).scalar()).startswith('16.'))
        require('migration_head', connection.execute(text('SELECT version_num FROM alembic_version')).scalar() == '47b9c01c769a')
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        require('migration_matches_models', not differences)
        tables = inspect(connection).get_table_names()
        require('all_model_tables_present', set(Base.metadata.tables) <= set(tables))
        require('one_seed_tenant', connection.scalar(select(func.count()).select_from(Tenant)) == 1)
        saved = connection.execute(select(Image.external_id, Image.filename, Image.source, Image.source_page_url, Image.processing_status)).all()
        require('fifty_seed_images', len(saved) == len(expected) == 50)
        require('seed_fields_match_manifest', {r.external_id: (r.filename, r.source, r.source_page_url) for r in saved} == expected)
        require('seed_images_pending', all(row.processing_status == 'pending' for row in saved))
        empty_tables = set(Base.metadata.tables) - {'tenants', 'images'}
        require('no_ai_or_processing_records', all(connection.scalar(select(func.count()).select_from(Base.metadata.tables[name])) == 0 for name in empty_tables))
        tenant_id = connection.scalar(select(Tenant.id))
        first = manifest[0]
        duplicate = dict(tenant_id=tenant_id, external_id=first['id'], filename=first['filename'], source=first['source'], source_page_url=first['source_page_url'])
        unique_blocked = False
        try:
            with connection.begin_nested():
                connection.execute(Image.__table__.insert().values(**duplicate))
        except IntegrityError:
            unique_blocked = True
        require('postgresql_rejects_duplicate_image', unique_blocked)
        foreign_key_blocked = False
        try:
            with connection.begin_nested():
                connection.execute(Image.__table__.insert().values(**{**duplicate, 'tenant_id': 999999, 'external_id': 'invalid_tenant_probe'}))
        except IntegrityError:
            foreign_key_blocked = True
        require('postgresql_rejects_missing_tenant', foreign_key_blocked)
        require('constraint_probes_saved_no_images', connection.scalar(select(func.count()).select_from(Image)) == 50)

    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from app.main import app
    with patch('google.genai.Client', side_effect=AssertionError('Gemini is disabled for setup checks.')) as gemini:
        with TestClient(app) as client:
            health = client.get('/health')
            require('api_health_200', health.status_code == 200)
            images = client.get('/images')
            require('api_reads_fifty_images', images.status_code == 200 and len(images.json()) == 50)
            posts = client.get('/posts')
            require('api_starts_without_posts', posts.status_code == 200 and posts.json() == [])
            invalid = client.post('/posts', json={'external_id': 'setup_blank', 'title': ' ', 'content': 'Test'})
            require('api_rejects_blank_title', invalid.status_code == 422)
            payload = {'external_id': 'setup_check_post', 'title': 'Setup check', 'content': 'Temporary database test.'}
            created = client.post('/posts', json=payload)
            require('api_creates_post_in_postgresql', created.status_code == 201)
            require('api_rejects_duplicate_post', client.post('/posts', json=payload).status_code == 409)
            listed = client.get('/posts')
            require('api_saved_exactly_one_fixture_post', listed.status_code == 200 and len(listed.json()) == 1)
        require('no_gemini_client_created', gemini.call_count == 0)
    with engine.connect() as connection:
        require('no_ai_costs_created', connection.scalar(select(func.count()).select_from(Base.metadata.tables['ai_call_costs'])) == 0)
    engine.dispose()
    return {'checks': checks, 'images': 50, 'fixture_posts': 1, 'schema_differences': len(differences), 'ai_calls': 0}


def verify(project: Path, *, report_path: Path | None = None) -> dict:
    project = project.resolve()
    if not (project / 'alembic.ini').is_file() or not (project / 'data/images.json').is_file():
        raise ValueError('Run this check against the capstone repository.')
    token = uuid.uuid4().hex
    name = 'flyrank-setup-check-' + token[:12]
    container_id = None
    report = {'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'passed': False,
              'scope': 'Fresh PostgreSQL 16 container using installed project dependencies. No live Gemini processing.',
              'existing_database_used': False, 'environment_file_changed': False,
              'container_removed': False, 'steps': []}
    stage = 'Docker availability'
    try:
        os_name = run_command(['docker', 'image', 'inspect', '--format', '{{.Os}}', 'postgres:16']).stdout.strip()
        if os_name != 'linux':
            raise ValueError('A local Linux postgres:16 image is required. Start Docker Desktop first.')
        stage = 'Start temporary PostgreSQL'
        docker_env = dict(os.environ, POSTGRES_PASSWORD=token)
        container_id = run_command(['docker', 'run', '--detach', '--pull=never', '--name', name,
                                    '--label', f'{LABEL}={token}', '--env', 'POSTGRES_PASSWORD',
                                    '--env', f'POSTGRES_DB={DATABASE_NAME}',
                                    '--publish', '127.0.0.1::5432', '--tmpfs', '/var/lib/postgresql/data', 'postgres:16'], env=docker_env).stdout.strip()
        if not container_id or any(c not in '0123456789abcdef' for c in container_id):
            raise ValueError('Docker did not return a valid container ID.')
        stage = 'Wait for PostgreSQL'
        deadline = time.monotonic() + 60
        while True:
            ready = subprocess.run(['docker', 'exec', container_id, 'pg_isready', '-h', '127.0.0.1', '-U', 'postgres', '-d', DATABASE_NAME], capture_output=True, timeout=5)
            if ready.returncode == 0:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError('Temporary PostgreSQL did not become ready.')
            time.sleep(1)
        ports = json.loads(run_command(['docker', 'inspect', '--format', '{{json .NetworkSettings.Ports}}', container_id]).stdout)
        bindings = ports['5432/tcp']
        if len(bindings) != 1 or bindings[0]['HostIp'] != '127.0.0.1':
            raise ValueError('Temporary database is not bound exclusively to localhost.')
        port = int(bindings[0]['HostPort'])
        if port == 5432:
            raise ValueError('Temporary database must use a separate port.')
        environment = scratch_environment(port, token)
        python = str(project / '.venv/Scripts/python.exe') if (project / '.venv/Scripts/python.exe').exists() else sys.executable
        for stage, module, arguments in (
                ('Apply migrations', 'alembic', ['upgrade', 'head']),
                ('Repeat migrations', 'alembic', ['upgrade', 'head']),
                ('Seed image records', 'scripts.seed', []),
                ('Repeat seed', 'scripts.seed', [])):
            result = run_command([python, '-B', '-m', module, *arguments], cwd=project, env=environment)
            if module == 'scripts.seed':
                expected = ('Created images: 50', 'Skipped existing images: 0') if stage == 'Seed image records' else ('Created images: 0', 'Skipped existing images: 50')
                if not all(message in result.stdout.splitlines() for message in expected):
                    raise AssertionError('Unexpected seed result.')
            report['steps'].append({'name': stage, 'passed': True})
            print(f'PASS: {stage}', flush=True)
        stage = 'Inspect schema, constraints and API'
        result = run_command([python, '-B', str(Path(__file__).resolve()), '--project-root', str(project), '--inspect-database'], cwd=project, env=environment)
        details = json.loads(result.stdout)
        report.update(details)
        for check in details['checks']:
            print(f"PASS: {check['name']}", flush=True)
        report['passed'] = True
    except Exception as exc:
        report.update(failed_stage=stage, error_class=type(exc).__name__)
        print(f'Setup check stopped at {stage} ({type(exc).__name__}). Raw errors withheld.', flush=True)
    finally:
        if container_id is not None:
            try:
                owner = run_command(['docker', 'inspect', '--format', '{{ index .Config.Labels "' + LABEL + '" }}', container_id]).stdout.strip()
                if owner != token:
                    raise ValueError('Temporary container ownership check failed.')
                run_command(['docker', 'rm', '--force', container_id])
                report['container_removed'] = True
                print('Temporary PostgreSQL container removed.', flush=True)
            except Exception as exc:
                report.update(passed=False, cleanup_error_class=type(exc).__name__)
                print(f'Temporary container cleanup requires attention: {name}', flush=True)
    report_path = report_path or project / 'reports' / ('fresh_postgres_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ') + '.json')
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open('x', encoding='utf-8') as file:
        json.dump(report, file, indent=2)
        file.write('\n')
    print(f'Report saved: {report_path}', flush=True)
    print('Existing capstone database, corpus and app/.env were not changed. No Gemini requests.', flush=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--inspect-database', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.inspect_database:
            print(json.dumps(inspect_database(args.project_root)))
            return 0
        report = verify(args.project_root, report_path=args.output)
        return 0 if report['passed'] else 1
    except Exception as exc:
        print(f'Setup check could not finish ({type(exc).__name__}). Raw errors withheld.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
