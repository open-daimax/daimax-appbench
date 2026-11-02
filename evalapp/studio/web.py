"""Local-only Studio routes layered on the existing QuickCheck server."""
import json
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlsplit

from ..quickcheck.web import create_server as quickcheck_server
from .jobs import Jobs


def create_server(settings, root, project_root, config_path=None, port=8766, quickcheck_output=None):
    root = Path(root).resolve()
    jobs = Jobs(root / 'full', project_root, config_path)
    server = quickcheck_server(settings, quickcheck_output or root / 'quickcheck',
                               host='127.0.0.1', port=port, config_path=config_path)
    base = server.RequestHandlerClass

    class Handler(base):
        def do_GET(self):
            if not self.allowed():
                return self.reply(403, {'error': 'origin_not_allowed'})
            route = unquote(urlsplit(self.path).path)
            if route in ('/', '/studio.html'):
                path = Path(__file__).parent / 'static' / 'studio.html'
                if not path.is_file():
                    return self.reply(503, {'error': 'Studio UI not built'})
                return self.reply(200, path.read_bytes(), 'text/html; charset=utf-8')
            if route == '/api/studio/meta':
                return self.reply(200, {'project_root': str(project_root), 'config_path': config_path,
                                       'output': str(root), 'local_only': True})
            if route == '/api/studio/samples':
                import yaml
                items = []
                for path in sorted((Path(project_root) / 'dataset' / 'V2').glob('*/*/sample.yaml')):
                    try:
                        sample = yaml.safe_load(path.read_text(encoding='utf-8'))
                        items.append({'id': sample['sample_id'], 'title': sample.get('title', sample['sample_id']),
                                      'category': path.parent.parent.name, 'requirement': sample.get('requirement', '')})
                    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
                        continue
                return self.reply(200, {'items': items})
            if route == '/api/studio/jobs':
                return self.reply(200, {'items': jobs.list()})
            if route.startswith('/api/studio/jobs/'):
                parts = route.split('/')
                try:
                    job = jobs.get(parts[4])
                    if len(parts) == 5:
                        log = jobs.root / job['id'] / 'output.log'
                        text = ''
                        if log.exists():
                            with log.open('rb') as stream:
                                stream.seek(max(0, log.stat().st_size - 128000))
                                text = stream.read(128000).decode('utf-8', errors='replace')
                        return self.reply(200, {**job, 'log': text})
                except (OSError, ValueError):
                    pass
                return self.reply(404, {'error': 'task_not_found'})
            if route.startswith('/studio-reports/'):
                parts = route.split('/', 3)
                try:
                    job = jobs.get(parts[2])
                    relative = parts[3]
                    # Only frozen report artifacts are public, never the source workspace.
                    if not job['report']:
                        raise FileNotFoundError()
                    boundary = (jobs.root / job['id'] / 'report').resolve()
                    path = (boundary / relative).resolve()
                    path.relative_to(boundary)
                    if not path.is_file():
                        raise FileNotFoundError()
                    return self.reply(200, path.read_bytes(), mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
                except (OSError, ValueError, IndexError):
                    return self.reply(404, {'error': 'report_not_found'})
            return super().do_GET()

        def do_POST(self):
            route = urlsplit(self.path).path
            if not route.startswith('/api/studio/'):
                return super().do_POST()
            if not self.allowed():
                return self.reply(403, {'error': 'origin_not_allowed'})
            if route != '/api/studio/jobs':
                return self.reply(404, {'error': 'not_found'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 32768:
                    raise ValueError('请求体大小无效')
                data = json.loads(self.rfile.read(length))
                return self.reply(202, jobs.submit(data))
            except RuntimeError as exc:
                return self.reply(409, {'error': str(exc)})
            except (ValueError, OSError, TypeError) as exc:
                return self.reply(400, {'error': str(exc)})

    server.RequestHandlerClass = Handler
    server.jobs = jobs
    return server
