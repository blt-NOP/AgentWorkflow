"""个人论文库：SQLite 本地文件，不需要数据库服务。"""
from contextlib import contextmanager
from datetime import datetime
import json
import sqlite3
from uuid import uuid4
from . import memory


@contextmanager
def connect():
    memory.DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(memory.DATA / "library.sqlite3")
    db.row_factory = sqlite3.Row
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS papers (
            paper_id TEXT PRIMARY KEY, title TEXT NOT NULL, year INTEGER,
            doi TEXT NOT NULL DEFAULT '', abstract TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        # 只迁移一次旧 JSON，保留原文件作备份；删除论文后不会重新导入。
        if db.execute("PRAGMA user_version").fetchone()[0] == 0:
            old = memory.DATA / "library.json"
            if old.exists():
                for paper in json.loads(old.read_text(encoding="utf-8")):
                    _save(db, paper)
            db.execute("PRAGMA user_version = 1")
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _save(db, paper):
    title = paper["title"].strip()
    if not title:
        raise ValueError("论文标题不能为空")
    doi = paper.get("doi", "").strip().lower().removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    paper_id = paper.get("paper_id") or ""
    same = db.execute("SELECT paper_id FROM papers WHERE doi=?", (doi,)).fetchone() if doi else None
    if same:
        if paper_id and paper_id != same[0]:
            raise ValueError("该 DOI 已属于另一篇论文，请编辑原记录")
        paper_id = same[0]
    paper_id = paper_id or str(uuid4())
    stamp = datetime.now().isoformat(timespec="seconds")
    db.execute("""INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(paper_id) DO UPDATE SET title=excluded.title, year=excluded.year,
        doi=excluded.doi, abstract=excluded.abstract, notes=excluded.notes, updated_at=excluded.updated_at""",
        (paper_id, title, paper.get("year"), doi, paper.get("abstract", ""), paper.get("notes", ""), stamp, stamp))
    return dict(db.execute("SELECT * FROM papers WHERE paper_id=?", (paper_id,)).fetchone())


def list_papers(query=""):
    with connect() as db:
        rows = db.execute("SELECT * FROM papers WHERE title LIKE ? OR doi LIKE ? OR notes LIKE ? ORDER BY updated_at DESC, rowid DESC",
                          tuple(f"%{query}%" for _ in range(3))).fetchall()
        return [dict(row) for row in rows]


def get_paper(paper_id):
    with connect() as db:
        row = db.execute("SELECT * FROM papers WHERE paper_id=?", (paper_id,)).fetchone()
        return dict(row) if row else None


def save_paper(paper):
    with connect() as db:
        return _save(db, paper)


def import_papers(papers):
    with connect() as db:
        return [_save(db, paper) for paper in papers]


def delete_paper(paper_id):
    with connect() as db:
        return db.execute("DELETE FROM papers WHERE paper_id=?", (paper_id,)).rowcount > 0
