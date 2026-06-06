"""
db.py — persistence backbone.

Two interchangeable backends behind one tiny API:
  - SupabaseStore : writes/reads via Supabase PostgREST over HTTPS (stdlib urllib,
                    no extra pip deps). Used in production.
  - LocalStore    : appends to .candor_data/<table>.jsonl. Fallback only — on
                    Streamlit Cloud this is EPHEMERAL (resets on reboot). It exists
                    so the app never crashes without Supabase, NOT for real storage.

Backend is chosen by env:
  SUPABASE_ENABLED=true + SUPABASE_URL + (SUPABASE_SERVICE_ROLE_KEY | SUPABASE_ANON_KEY)
Keys are read from the environment / Streamlit secrets only — never hard-coded.

Filter convention (both backends): filters={"col": value} means equality.
"""
from __future__ import annotations
import json
import os
import time
import urllib.request
import urllib.parse


def _env(k, d=None):
    return os.environ.get(k, d)


def supabase_enabled() -> bool:
    return (str(_env("SUPABASE_ENABLED", "")).lower() in ("1", "true", "yes")
            and bool(_env("SUPABASE_URL"))
            and bool(_env("SUPABASE_SERVICE_ROLE_KEY") or _env("SUPABASE_ANON_KEY")))


class SupabaseStore:
    backend = "supabase"

    def __init__(self):
        self.url = _env("SUPABASE_URL").rstrip("/")
        self.key = _env("SUPABASE_SERVICE_ROLE_KEY") or _env("SUPABASE_ANON_KEY")

    def _headers(self, prefer=None):
        h = {"apikey": self.key, "Authorization": f"Bearer {self.key}",
             "Content-Type": "application/json"}
        if prefer:
            h["Prefer"] = prefer
        return h

    def insert(self, table, row):
        data = json.dumps(row).encode()
        req = urllib.request.Request(f"{self.url}/rest/v1/{table}", data=data,
                                     headers=self._headers("return=minimal"), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                return r.status in (200, 201, 204)
        except Exception:
            return False

    def select(self, table, filters=None, select="*", limit=None, order=None):
        q = {"select": select}
        for k, v in (filters or {}).items():
            q[k] = f"eq.{v}"
        if order:
            q["order"] = order
        if limit:
            q["limit"] = str(limit)
        url = f"{self.url}/rest/v1/{table}?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                body = r.read().decode()
                return json.loads(body) if body else []
        except Exception:
            return []

    def count(self, table, filters=None):
        q = {"select": "*", "limit": "1"}
        for k, v in (filters or {}).items():
            q[k] = f"eq.{v}"
        url = f"{self.url}/rest/v1/{table}?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers=self._headers("count=exact"), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                cr = r.headers.get("Content-Range", "")
                tail = cr.split("/")[-1] if "/" in cr else ""
                return int(tail) if tail.isdigit() else 0
        except Exception:
            return 0


class LocalStore:
    backend = "local"

    def __init__(self, base=None):
        self.dir = base or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), ".candor_data")
        try:
            os.makedirs(self.dir, exist_ok=True)
        except Exception:
            pass

    def _path(self, table):
        return os.path.join(self.dir, f"{table}.jsonl")

    def insert(self, table, row):
        try:
            with open(self._path(table), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
            return True
        except Exception:
            return False

    def _all(self, table):
        p = self._path(table)
        if not os.path.exists(p):
            return []
        out = []
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        pass
        return out

    def select(self, table, filters=None, select="*", limit=None, order=None):
        rows = self._all(table)
        for k, v in (filters or {}).items():
            rows = [r for r in rows if str(r.get(k)) == str(v)]
        if order:
            col = order.split(".")[0]
            desc = order.endswith(".desc")
            rows = sorted(rows, key=lambda r: r.get(col) or 0, reverse=desc)
        if limit:
            rows = rows[:limit]
        return rows

    def count(self, table, filters=None):
        return len(self.select(table, filters))


_STORE = None
def get_store():
    global _STORE
    if _STORE is None:
        _STORE = SupabaseStore() if supabase_enabled() else LocalStore()
    return _STORE


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
