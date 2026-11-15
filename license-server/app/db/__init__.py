from __future__ import annotations

from ..config import DbSettings
from ..repo.base import Repos


def make_repos(db: DbSettings) -> Repos:
    if db.store == "memory":
        from ..repo.memory import make_memory_repos
        return make_memory_repos()
    from ..repo.mongo import make_mongo_repos
    return make_mongo_repos(db.mongo_url, db.mongo_db)
