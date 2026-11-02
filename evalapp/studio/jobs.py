"""Persisted, single-flight evaluation jobs using the public CLI."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


class Jobs:
    def __init__(self, root, project_root, config_path=None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.project_root = Path(project_root).resolve()
        self.config_path = str(Path(config_path).resolve()) if config_path else None
        self.lock = threading.RLock()
        self.process = None
        self.thread = None
        self.active = None
        for job in self.list():
            if job['status'] in ('queued', 'running'):
                job.update(status='interrupted', finished_at=now())
                self.save(job)

    def save(self, job):
        path = self.root / job['id'] / 'job.json'
        path.parent.mkdir(exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
        temp.replace(path)

    def get(self, job_id):
        if not re.fullmatch(r'full_[0-9a-f]{32}', job_id):
            raise FileNotFoundError()
        return json.loads((self.root / job_id / 'job.json').read_text())

    def list(self):
        result = []
        for path in self.root.glob('full_*/job.json'):
            try:
                result.append(json.loads(path.read_text()))
            except (OSError, ValueError):
                continue
        return sorted(result, key=lambda j: j['created_at'], reverse=True)

    def command(self, data, job_id):
        if not isinstance(data, dict):
            raise ValueError('请求必须是 JSON 对象')
        mode = data.get('mode', 'url')
        if mode not in ('url', 'project', 'apk', 'app', 'workspace'):
            raise ValueError('不支持的评测目标')
        target = data.get('target', '')
        if not isinstance(target, str) or not target.strip() or len(target) > 4096:
            raise ValueError('请输入评测目标')
        target = target.strip()
        platform = data.get('platform', 'web')
        if platform not in ('web', 'android', 'ios'):
            raise ValueError('不支持的平台')
        if mode == 'url':
            from urllib.parse import urlsplit
            parsed = urlsplit(target)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username:
                raise ValueError('请输入 http(s) URL')
            platform = 'web'
        else:
            path = Path(target).expanduser()
            if not path.is_absolute():
                path = self.project_root / path
            if not path.exists() or (mode in ('project', 'workspace', 'app') and not path.is_dir()):
                raise ValueError('目标路径不存在或类型不匹配（路径位于运行控制台的机器）')
            if mode == 'apk' and (not path.is_file() or path.suffix.lower() != '.apk'):
                raise ValueError('请选择 APK 文件')
            target = str(path.resolve())
        ids = data.get('sample_ids', [])
        if not isinstance(ids, list) or not ids or len(ids) > 200 or any(not isinstance(x, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', x) for x in ids):
            raise ValueError('请选择至少一个有效样本')
        workers = data.get('workers', 1)
        if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 8:
            raise ValueError('并发数应为 1–8')
        cmd = [sys.executable, '-m', 'evalapp.cli']
        if self.config_path:
            cmd += ['--config', self.config_path]
        cmd += ['evaluate', '--no-open-report', '--sample-ids', ','.join(ids), '--workers', str(workers)]
        workspace = self.root / job_id / 'workspace'
        if mode == 'workspace':
            samples = Path(data.get('samples_dir') or self.project_root / 'dataset' / 'V2').expanduser().resolve()
            if not samples.is_dir():
                raise ValueError('样本集目录不存在')
            cmd += ['--workspace', target, '--samples-dir', str(samples), '--platform', platform]
            workspace = Path(target)
        else:
            # CLI artifact mode discovers samples from the repository dataset.
            from ..commands._artifact_prep import discover_sample
            for sample_id in ids:
                discover_sample(sample_id)
            cmd += ['--' + mode, target, '--output', str(workspace)]
            if mode in ('url', 'project'):
                cmd += ['--platform', platform]
        return cmd, workspace

    def submit(self, data):
        with self.lock:
            if self.active:
                raise RuntimeError('已有完整评测正在运行，请等待完成')
            job_id = 'full_' + uuid.uuid4().hex
            cmd, workspace = self.command(data, job_id)
            job = dict(id=job_id, name=str(data.get('name') or data['target'])[:200], status='queued',
                       created_at=now(), request=data, workspace=str(workspace), report=False)
            self.save(job)
            self.active = job_id
            self.thread = threading.Thread(target=self.run, args=(job, cmd), daemon=True)
            self.thread.start()
            return job.copy()

    def run(self, job, cmd):
        import time
        started = time.time()
        try:
            with self.lock:
                job.update(status='running', started_at=now())
                self.save(job)
            with (self.root / job['id'] / 'output.log').open('wb') as log:
                env = {**os.environ, 'PYTHONUNBUFFERED': '1', 'NO_COLOR': '1'}
                # Resolve this checkout even when an editable installation points elsewhere.
                env['PYTHONPATH'] = str(Path(__file__).resolve().parents[2]) + os.pathsep + env.get('PYTHONPATH', '')
                self.process = subprocess.Popen(cmd, cwd=self.project_root, stdout=log, stderr=subprocess.STDOUT, env=env)
                code = self.process.wait()
            report = Path(job['workspace']) / 'report.html'
            fresh = report.is_file() and report.stat().st_mtime >= started
            if fresh:
                self.snapshot_report(job)
            job.update(status='completed' if code == 0 and fresh else 'failed', returncode=code, report=fresh)
            if code == 0 and not fresh:
                job['error'] = '评测未生成新报告，请查看日志检查样本、模型或环境配置。'
        except Exception as exc:
            job.update(status='failed', error=str(exc))
        finally:
            with self.lock:
                job['finished_at'] = now()
                self.save(job)
                self.process = None
                self.active = None

    def snapshot_report(self, job):
        """Freeze generated artifacts so re-evaluating a workspace preserves history."""
        workspace = Path(job['workspace']).resolve()
        destination = self.root / job['id'] / 'report'
        destination.mkdir(exist_ok=True)
        shutil.copy2(workspace / 'report.html', destination / 'report.html')
        directories = [workspace / 'report']
        for sample_id in job.get('request', {}).get('sample_ids', []):
            directories.extend(workspace / sample_id / name for name in ('screenshots', 'e2e_reports'))
        for directory in directories:
            if not directory.is_dir() or directory.is_symlink():
                continue
            for parent, dirs, filenames in os.walk(directory, followlinks=False):
                dirs[:] = [name for name in dirs if not (Path(parent) / name).is_symlink()]
                for name in filenames:
                    source = Path(parent) / name
                    if source.is_symlink():
                        continue
                    source.resolve().relative_to(workspace)
                    target = destination / source.relative_to(workspace)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)

    def close(self):
        # Keep the parent alive until the evaluator has persisted its report.
        if self.thread:
            self.thread.join()
