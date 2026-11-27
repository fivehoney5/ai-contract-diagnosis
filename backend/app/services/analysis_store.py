"""분석 결과 저장소. DB가 정해지기 전까지 표준 라이브러리 SQLite를 씁니다.

업로드한 원본 파일(계약서, 등기부)은 저장하지 않고, 입력 요약과 결과만 저장합니다.
"""

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


class AnalysisStore:
    def __init__(self, path: Path | str):
        self._path = str(path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._memory = sqlite3.connect(":memory:", check_same_thread=False) if self._path == ":memory:" else None
        with self._conn() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS analyses (
                    analysis_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    grade TEXT,
                    input_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    notes_json TEXT NOT NULL
                )"""
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)

    def _conn(self):
        return _noop(self._memory) if self._memory is not None else closing(self._connect())

    def save(self, analysis_id: str, created_at: str, input_summary: dict, result: dict, notes: list[str]) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO analyses VALUES (?, ?, ?, ?, ?, ?)",
                (
                    analysis_id,
                    created_at,
                    result.get("grade"),
                    json.dumps(input_summary, ensure_ascii=False),
                    json.dumps(result, ensure_ascii=False),
                    json.dumps(notes, ensure_ascii=False),
                ),
            )
            conn.commit()

    def get(self, analysis_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT analysis_id, created_at, input_json, result_json, notes_json FROM analyses WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "analysis_id": row[0],
            "created_at": row[1],
            "input": json.loads(row[2]),
            "result": json.loads(row[3]),
            "notes": json.loads(row[4]),
        }

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT analysis_id, created_at, grade, input_json FROM analyses ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"analysis_id": r[0], "created_at": r[1], "grade": r[2], "address": json.loads(r[3]).get("address")}
            for r in rows
        ]


class _noop:
    """메모리 DB는 연결 하나를 계속 쓰므로 with 블록에서 닫지 않습니다."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self.conn

    def __exit__(self, *exc) -> None:
        return None
