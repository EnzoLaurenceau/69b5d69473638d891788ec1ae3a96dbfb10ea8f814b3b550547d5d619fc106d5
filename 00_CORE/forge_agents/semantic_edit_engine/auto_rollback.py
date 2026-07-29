from __future__ import annotations
import logging
import uuid
import datetime
from dataclasses import dataclass, field
from pathlib import Path
from contextlib import contextmanager

logger = logging.getLogger(__name__)

FORGE_ROOT = Path(__file__).parent.parent.parent.parent
SNAPSHOT_DIR = FORGE_ROOT / ".nexus" / "see_snapshots"

@dataclass
class Snapshot:
    snapshot_id: str
    file_path: Path
    content: str
    timestamp: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    metadata: dict = field(default_factory=dict)

class AutoRollback:
    def __init__(self, snapshot_dir: Path = None):
        self.snapshot_dir = snapshot_dir or SNAPSHOT_DIR
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.history: dict[str, Snapshot] = {}

    def create_snapshot(self, file_path: Path) -> Snapshot:
        content = ""
        if file_path.exists():
            content = file_path.read_text(encoding="utf-8", errors="replace")
        sid = str(uuid.uuid4())
        snap = Snapshot(
            snapshot_id=sid,
            file_path=file_path,
            content=content,
            metadata={
                "size": len(content),
                "mtime": file_path.stat().st_mtime if file_path.exists() else 0
            }
        )
        self.history[sid] = snap
        return snap

    def rollback(self, snapshot: Snapshot) -> bool:
        try:
            if snapshot.content:
                snapshot.file_path.write_text(snapshot.content, encoding="utf-8")
            else:
                if snapshot.file_path.exists():
                    snapshot.file_path.unlink()
            logger.info(f"ROLLBACK|SUCCESS|file={snapshot.file_path}")
            return True
        except Exception as e:
            logger.error(f"ROLLBACK|FAIL|file={snapshot.file_path}|err={e}")
            return False

    def verify(self, file_path: Path) -> bool:
        if not file_path.exists():
            return False
        if file_path.suffix == ".py":
            try:
                compile(file_path.read_text(encoding="utf-8"), file_path.name, "exec")
                return True
            except Exception as e:
                logger.error(f"VERIFY|FAIL|file={file_path}|err={e}")
                return False
        return True

    @contextmanager
    def transaction(self, file_path: Path):
        snap = self.create_snapshot(file_path)
        try:
            yield snap
            if not self.verify(file_path):
                raise ValueError("Compilation check failed post-modification")
        except Exception as e:
            logger.error(f"TRANSACTION|FAIL|Rolling back changes: {e}")
            self.rollback(snap)
            raise

_manager = AutoRollback()

def get_rollback_manager() -> AutoRollback:
    return _manager

def transactional_edit(file_path: Path, new_content: str) -> bool:
    mgr = get_rollback_manager()
    try:
        with mgr.transaction(file_path):
            file_path.write_text(new_content, encoding="utf-8")
            return True
    except Exception:
        return False
