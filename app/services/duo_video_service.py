import json
import os
import logging
import hashlib
import requests
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import sqlite3


@dataclass
class DuoResource:
    id: str
    name: str
    category: str
    type: str
    url: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None


class DuoVideoResourceIds:
    """
    Duo-Video 资源 ID 枚举占位（可通过资源库 JSON 扩展）。
    说明：这里仅提供结构示例，实际生产请使用资源库 JSON 或在线资源中心导出。
    """
    class TextTemplateId:
        SAMPLE = "270464050694389761"

    class EffectId:
        SAMPLE = "270464037793497089"

    class TransitionId:
        SAMPLE = "270464040000000000"

    class FaceEffectId:
        SAMPLE = "270464033541718017"

    class StickerId:
        SAMPLE = "270402997699280897"

    class TextEffectId:
        SAMPLE = "270464050000000000"


class DuoVideoService:
    """
    Duo-Video 资源服务层（资源库 + 配置映射）。
    """
    def __init__(self, resource_path: Optional[str] = None, cache_dir: Optional[str] = None,
                 logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger("duo_video_service")
        default_path = os.path.join(os.getcwd(), "app", "utils", "duo_resources", "resources.json")
        self.resource_path = resource_path or os.getenv("DUO_VIDEO_RESOURCE_PATH") or (default_path if os.path.exists(default_path) else None)
        self.cache_dir = cache_dir or os.path.join(os.getcwd(), "duo_cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._resources: List[DuoResource] = []
        self._index: Dict[str, List[DuoResource]] = {}
        self._version: Optional[str] = None
        self._use_sqlite = os.getenv("DUO_USE_SQLITE", "0") == "1"
        if self.resource_path:
            self.load_resources(self.resource_path)
            self._load_index_from_cache()
            if self._use_sqlite:
                self._build_sqlite_index()

    def load_resources(self, path_or_url: str) -> None:
        data = None
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            resp = requests.get(path_or_url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        else:
            with open(path_or_url, "r", encoding="utf-8") as f:
                data = json.load(f)

        if isinstance(data, dict):
            self._version = data.get("version") or data.get("updated_at")
            items = data.get("items")
        else:
            items = data
        resources: List[DuoResource] = []
        for item in items or []:
            try:
                resources.append(DuoResource(
                    id=str(item.get("id") or item.get("resource_id") or item.get("effect_id")),
                    name=item.get("name") or item.get("title") or "",
                    category=item.get("category") or item.get("type") or "unknown",
                    type=item.get("type") or item.get("resource_type") or "unknown",
                    url=item.get("url"),
                    meta=item
                ))
            except Exception:
                continue
        self._resources = resources
        # build index by category
        idx: Dict[str, List[DuoResource]] = {}
        for r in self._resources:
            key = r.category or "unknown"
            idx.setdefault(key, []).append(r)
        self._index = idx
        self._persist_index()

    def _index_file(self) -> str:
        return os.path.join(self.cache_dir, "duo_index.json")

    def _sqlite_file(self) -> str:
        return os.path.join(self.cache_dir, "duo_resources.db")

    def _build_sqlite_index(self) -> None:
        try:
            db_path = self._sqlite_file()
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute(
                "CREATE TABLE IF NOT EXISTS resources ("
                "id TEXT, name TEXT, category TEXT, type TEXT, url TEXT, meta TEXT)"
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_cat ON resources(category)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_name ON resources(name)")
            cur.execute("DELETE FROM resources")
            for r in self._resources:
                cur.execute(
                    "INSERT INTO resources (id, name, category, type, url, meta) VALUES (?, ?, ?, ?, ?, ?)",
                    (r.id, r.name or "", r.category or "", r.type or "", r.url or "", json.dumps(r.meta or {}, ensure_ascii=False)),
                )
            conn.commit()
            conn.close()
        except Exception:
            return

    def _persist_index(self) -> None:
        try:
            payload = {
                "version": self._version,
                "categories": {k: [r.id for r in v] for k, v in self._index.items()}
            }
            with open(self._index_file(), "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
        except Exception:
            return

    def _load_index_from_cache(self) -> bool:
        try:
            path = self._index_file()
            if not os.path.exists(path):
                return False
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._version = data.get("version")
            cats = data.get("categories", {})
            idx: Dict[str, List[DuoResource]] = {}
            by_id = {r.id: r for r in self._resources}
            for k, ids in cats.items():
                idx[k] = [by_id[i] for i in ids if i in by_id]
            self._index = idx
            return True
        except Exception:
            return False

    def get_version(self) -> Optional[str]:
        return self._version

    def list_categories(self) -> List[str]:
        return sorted({r.category for r in self._resources if r.category})

    def resource_count(self) -> int:
        return len(self._resources)

    def search(self, category: Optional[str] = None, keyword: Optional[str] = None, limit: int = 50, offset: int = 0) -> List[DuoResource]:
        if self._use_sqlite and os.path.exists(self._sqlite_file()):
            return self._search_sqlite(category, keyword, limit, offset)
        results = self._resources if not category else self._index.get(category, [])
        if keyword:
            kw = keyword.lower()
            results = [r for r in results if kw in (r.name or "").lower() or kw in (r.id or "")]
        if offset < 0:
            offset = 0
        if limit is None or limit <= 0:
            return results[offset:]
        return results[offset:offset + limit]

    def count(self, category: Optional[str] = None, keyword: Optional[str] = None) -> int:
        if self._use_sqlite and os.path.exists(self._sqlite_file()):
            return self._count_sqlite(category, keyword)
        results = self._resources if not category else self._index.get(category, [])
        if keyword:
            kw = keyword.lower()
            results = [r for r in results if kw in (r.name or "").lower() or kw in (r.id or "")]
        return len(results)

    def _search_sqlite(self, category: Optional[str], keyword: Optional[str], limit: int, offset: int) -> List[DuoResource]:
        conn = sqlite3.connect(self._sqlite_file())
        cur = conn.cursor()
        params = []
        where = []
        if category:
            where.append("category = ?")
            params.append(category)
        if keyword:
            where.append("(name LIKE ? OR id LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        sql = "SELECT id, name, category, type, url, meta FROM resources"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.close()
        out = []
        for rid, name, cat, typ, url, meta in rows:
            out.append(DuoResource(id=rid, name=name, category=cat, type=typ, url=url, meta=json.loads(meta or "{}")))
        return out

    def _count_sqlite(self, category: Optional[str], keyword: Optional[str]) -> int:
        conn = sqlite3.connect(self._sqlite_file())
        cur = conn.cursor()
        params = []
        where = []
        if category:
            where.append("category = ?")
            params.append(category)
        if keyword:
            where.append("(name LIKE ? OR id LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        sql = "SELECT COUNT(*) FROM resources"
        if where:
            sql += " WHERE " + " AND ".join(where)
        cur.execute(sql, params)
        count = cur.fetchone()[0]
        conn.close()
        return count

    def get_by_id(self, rid: str) -> Optional[DuoResource]:
        for r in self._resources:
            if r.id == str(rid):
                return r
        return None

    def download_resource(self, url: str) -> Optional[str]:
        try:
            h = hashlib.sha1(url.encode("utf-8")).hexdigest()
            ext = os.path.splitext(url)[1] or ".bin"
            local_path = os.path.join(self.cache_dir, f"{h}{ext}")
            if os.path.exists(local_path):
                return local_path
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            with open(local_path, "wb") as f:
                f.write(resp.content)
            return local_path
        except Exception as e:
            self.logger.warning("download resource failed: %s", e)
            return None

    def build_effects_config(self, duo_config: Dict[str, Any]) -> Dict[str, Any]:
        cfg = {
            "video": {"filters": [], "effects": [], "animations": [], "transitions": [], "masks": [], "keyframes": [], "background": []},
            "text": {"animations": [], "bubbles": [], "effects": []},
            "audio": {"effects": [], "fades": [], "keyframes": []},
            "_duo": {"stickers": [], "green_screen": [], "reverse": [], "lut": [], "text_styles": []}
        }

        def _normalize_name(item: Dict[str, Any]) -> str:
            return item.get("mcp_effect_type") or item.get("mcp_transition") or item.get("name") or item.get("title") or item.get("id")

        for item in duo_config.get("video_effects", []):
            entry = {"type": item.get("mcp_effect_type") or item.get("name") or item.get("id")}
            if item.get("params"):
                entry["params"] = item.get("params")
            if item.get("indexes"):
                entry["indexes"] = item.get("indexes")
            if item.get("track"):
                entry["track"] = item.get("track")
            cfg["video"]["effects"].append(entry)
        for item in duo_config.get("face_effects", []):
            entry = {"type": item.get("mcp_effect_type") or item.get("name") or item.get("id"), "params": item.get("params")}
            if item.get("indexes"):
                entry["indexes"] = item.get("indexes")
            if item.get("track"):
                entry["track"] = item.get("track")
            cfg["video"]["effects"].append(entry)
        for item in duo_config.get("transitions", []):
            entry = {"type": item.get("mcp_transition") or item.get("name") or item.get("id"), "duration": item.get("duration")}
            if item.get("indexes"):
                entry["indexes"] = item.get("indexes")
            if item.get("track"):
                entry["track"] = item.get("track")
            cfg["video"]["transitions"].append(entry)
        for item in duo_config.get("text_templates", []):
            # 映射为文本动画或花字/气泡
            if item.get("effect_id"):
                entry = {"effect_id": item.get("effect_id")}
                if item.get("indexes"):
                    entry["indexes"] = item.get("indexes")
                if item.get("track"):
                    entry["track"] = item.get("track")
                cfg["text"]["effects"].append(entry)
            elif item.get("resource_id"):
                entry = {"effect_id": item.get("resource_id"), "resource_id": item.get("resource_id")}
                if item.get("indexes"):
                    entry["indexes"] = item.get("indexes")
                if item.get("track"):
                    entry["track"] = item.get("track")
                cfg["text"]["bubbles"].append(entry)
            else:
                entry = {
                    "type": item.get("mcp_text_animation_type") or "TextIntro",
                    "name": item.get("mcp_text_animation_name") or item.get("name") or item.get("id")
                }
                if item.get("indexes"):
                    entry["indexes"] = item.get("indexes")
                if item.get("track"):
                    entry["track"] = item.get("track")
                cfg["text"]["animations"].append(entry)
        for item in duo_config.get("text_effects", []):
            entry = {"effect_id": item.get("mcp_text_effect_id") or item.get("effect_id") or item.get("id")}
            if item.get("indexes"):
                entry["indexes"] = item.get("indexes")
            if item.get("track"):
                entry["track"] = item.get("track")
            cfg["text"]["effects"].append(entry)

        # auto map generic items list if provided
        for item in duo_config.get("items", []):
            category = (item.get("category") or "").lower()
            name = _normalize_name(item)
            if "transition" in category or "转场" in category:
                cfg["video"]["transitions"].append({"type": name, "duration": item.get("duration"), "track": item.get("track"), "indexes": item.get("indexes")})
            elif "text" in category or "文字" in category:
                cfg["text"]["animations"].append({"type": item.get("mcp_text_animation_type") or "TextIntro", "name": name, "track": item.get("track"), "indexes": item.get("indexes")})
            elif "face" in category or "人脸" in category:
                cfg["video"]["effects"].append({"type": name, "params": item.get("params"), "track": item.get("track"), "indexes": item.get("indexes")})
            elif "sticker" in category or "贴纸" in category:
                cfg["_duo"]["stickers"].append(item)
            else:
                cfg["video"]["effects"].append({"type": name, "params": item.get("params"), "track": item.get("track"), "indexes": item.get("indexes")})

        cfg["_duo"]["stickers"] = duo_config.get("stickers", [])
        cfg["_duo"]["green_screen"] = duo_config.get("green_screen", [])
        cfg["_duo"]["reverse"] = duo_config.get("reverse", [])
        cfg["_duo"]["lut"] = duo_config.get("lut", [])
        cfg["_duo"]["text_styles"] = duo_config.get("text_styles", [])

        return cfg
