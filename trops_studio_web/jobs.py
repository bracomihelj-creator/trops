"""Ena poslovna naloga hkrati; polling ne potrebuje AppService zaklepa."""
from __future__ import annotations
import logging
import threading
import time
import uuid
from typing import Any, Callable

log = logging.getLogger(__name__)

class JobManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._active: str | None = None

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._active is not None

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._jobs[job_id]) if job_id in self._jobs else None

    def start(self, label: str, fn: Callable, payload: dict, progress_target: Any) -> dict:
        with self._lock:
            if self._active:
                raise RuntimeError('Druga naloga še teče. Počakaj na zaključek.')
            jid = uuid.uuid4().hex
            self._active = jid
            self._jobs[jid] = dict(id=jid, label=label, state='running', message=label, current=0, total=0, started=time.time())
            # Omejitev spomina; zadnjih 30 rezultatov.
            for old in list(self._jobs)[:-30]:
                del self._jobs[old]

        def progress(message: str, current: int = 0, total: int = 0) -> None:
            with self._lock:
                self._jobs[jid].update(message=str(message), current=current, total=total)

        def work() -> None:
            progress_target.progress_callback = progress
            try:
                result = fn(payload)
                failed = isinstance(result, dict) and result.get('ok') is False
                text = ''
                if isinstance(result, dict):
                    text = str(result.get('error') or result.get('msg') or result.get('message') or '')
                with self._lock:
                    self._jobs[jid].update(
                        state='error' if failed else 'done',
                        result=result,
                        error=(text or 'Naloga ni uspela.') if failed else '',
                        message=text or ('Naloga ni uspela.' if failed else 'Končano.'),
                    )
            except Exception as exc:
                log.exception('Naloga %s ni uspela', label)
                with self._lock:
                    self._jobs[jid].update(state='error', error=str(exc), message=str(exc))
            finally:
                progress_target.progress_callback = None
                with self._lock:
                    self._active = None
        threading.Thread(target=work, name=f'trops-job-{jid[:8]}', daemon=True).start()
        return {'ok': True, 'job_id': jid}
