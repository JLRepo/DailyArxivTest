import argparse
import datetime as dt
import json
import os
import sqlite3
import ssl
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Optional

BASE_URL = "https://export.arxiv.org/api/query"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


def repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def load_env(path: str) -> dict:
    env = {}
    if not os.path.exists(path):
        return env
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def load_config(path: str) -> dict:
    defaults = {
        "category": "cs.CV",
        "keywords": ["video", "retrieval", "3d", "agent", "representation"],
        "max_results": 50,
        "abstract_max_chars": 320,
        "use_proxy": False,
    }
    if not os.path.exists(path):
        return defaults
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for k, v in defaults.items():
        data.setdefault(k, v)
    return data


def build_query(category: str, from_dt: dt.datetime, to_dt: dt.datetime) -> str:
    from_str = from_dt.strftime("%Y%m%d%H%M")
    to_str = to_dt.strftime("%Y%m%d%H%M")
    return f"cat:{category} AND submittedDate:[{from_str} TO {to_str}]"


def ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        import certifi  # type: ignore

        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    return ctx


def urlopen_request(req: urllib.request.Request, use_proxy: bool) -> bytes:
    if use_proxy:
        with urllib.request.urlopen(req, timeout=20, context=ssl_context()) as resp:
            return resp.read()

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl_context()),
    )
    with opener.open(req, timeout=20) as resp:
        return resp.read()


def fetch_atom(params: dict, use_proxy: bool) -> bytes:
    url = BASE_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "daily-arxiv-paper/0.1"})
    return urlopen_request(req, use_proxy)


def parse_entries(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    entries = []
    for e in root.findall("atom:entry", ATOM_NS):
        title = (e.findtext("atom:title", default="", namespaces=ATOM_NS) or "").strip()
        summary = (e.findtext("atom:summary", default="", namespaces=ATOM_NS) or "").strip()
        id_url = (e.findtext("atom:id", default="", namespaces=ATOM_NS) or "").strip()
        published = (e.findtext("atom:published", default="", namespaces=ATOM_NS) or "").strip()
        updated = (e.findtext("atom:updated", default="", namespaces=ATOM_NS) or "").strip()
        link_url = ""
        for link in e.findall("atom:link", ATOM_NS):
            if link.get("rel") == "alternate":
                link_url = link.get("href") or ""
                break
        arxiv_id = id_url.rsplit("/", 1)[-1] if id_url else ""
        entries.append(
            {
                "id": arxiv_id,
                "title": " ".join(title.split()),
                "summary": " ".join(summary.split()),
                "url": link_url or id_url,
                "published": published,
                "updated": updated,
            }
        )
    return entries


def keyword_match(text: str, keywords: list[str]) -> bool:
    text_l = text.lower()
    for kw in keywords:
        if kw.lower() in text_l:
            return True
    return False


def filter_entries(entries: list[dict], keywords: list[str]) -> list[dict]:
    out = []
    for e in entries:
        blob = f"{e['title']}\n{e['summary']}"
        if keyword_match(blob, keywords):
            out.append(e)
    return out


def shorten(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def format_message(
    entries: list[dict], keywords: list[str], since_hours: int, abstract_max_chars: int
) -> str:
    header = (
        f"arXiv cs.CV (last {since_hours}h) | keywords: {', '.join(keywords)}\n"
        f"Matches: {len(entries)}"
    )
    if not entries:
        return header + "\nNo matches."

    limit = 20
    show = entries[:limit]
    blocks = []
    for e in show:
        snippet = shorten(e["summary"], abstract_max_chars)
        blocks.append(f"*{e['title']}*\n{e['url']}\n{snippet}")

    if len(entries) > limit:
        blocks.append(f"... and {len(entries) - limit} more.")

    return header + "\n\n" + "\n\n".join(blocks)


def send_slack(webhook_url: str, text: str, use_proxy: bool) -> None:
    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=payload, headers={"Content-Type": "application/json"}
    )
    _ = urlopen_request(req, use_proxy)


def db_path(root: str) -> str:
    return os.path.join(root, "data", "arxiv.db")


def init_db(root: str) -> sqlite3.Connection:
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    conn = sqlite3.connect(db_path(root))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stars (
            id TEXT PRIMARY KEY,
            title TEXT,
            url TEXT,
            abstract TEXT,
            added_at TEXT
        )
        """
    )
    conn.commit()
    return conn


def fetch_by_id(arxiv_id: str, use_proxy: bool) -> Optional[dict]:
    params = {"id_list": arxiv_id}
    xml_bytes = fetch_atom(params, use_proxy)
    entries = parse_entries(xml_bytes)
    return entries[0] if entries else None


def cmd_fetch(args: argparse.Namespace) -> int:
    root = repo_root()
    env = load_env(os.path.join(root, ".env"))
    cfg = load_config(os.path.join(root, "config.json"))

    now = dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(hours=args.since_hours)
    query = build_query(cfg["category"], since, now)

    params = {
        "search_query": query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": str(cfg["max_results"]),
    }
    xml_bytes = fetch_atom(params, cfg["use_proxy"])
    entries = parse_entries(xml_bytes)
    matches = filter_entries(entries, cfg["keywords"])

    text = format_message(matches, cfg["keywords"], args.since_hours, cfg["abstract_max_chars"])
    print(text)

    if not args.dry_run:
        webhook = env.get("SLACK_WEBHOOK_URL")
        if not webhook:
            print("Missing SLACK_WEBHOOK_URL in .env", file=sys.stderr)
            return 2
        send_slack(webhook, text, cfg["use_proxy"])
    return 0


def cmd_star(args: argparse.Namespace) -> int:
    root = repo_root()
    cfg = load_config(os.path.join(root, "config.json"))
    conn = init_db(root)
    entry = fetch_by_id(args.arxiv_id, cfg["use_proxy"])
    if not entry:
        print("Paper not found.", file=sys.stderr)
        return 1
    conn.execute(
        "INSERT OR REPLACE INTO stars (id, title, url, abstract, added_at) VALUES (?, ?, ?, ?, ?)",
        (
            entry["id"],
            entry["title"],
            entry["url"],
            entry["summary"],
            dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    print(f"Starred {entry['id']}: {entry['title']}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    root = repo_root()
    conn = init_db(root)
    cur = conn.execute(
        "SELECT id, title, url, added_at FROM stars ORDER BY added_at DESC"
    )
    rows = cur.fetchall()
    if not rows:
        print("No starred papers.")
        return 0
    for r in rows:
        print(f"{r[0]} | {r[1]}\n{r[2]}\n{r[3]}\n")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    root = repo_root()
    conn = init_db(root)
    q = f"%{args.query.lower()}%"
    cur = conn.execute(
        """
        SELECT id, title, url, added_at FROM stars
        WHERE lower(title) LIKE ? OR lower(abstract) LIKE ?
        ORDER BY added_at DESC
        """,
        (q, q),
    )
    rows = cur.fetchall()
    if not rows:
        print("No matches in stars.")
        return 0
    for r in rows:
        print(f"{r[0]} | {r[1]}\n{r[2]}\n{r[3]}\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="daily_arxiv_paper")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser("fetch", help="Fetch latest papers and send to Slack")
    p_fetch.add_argument("--since-hours", type=int, default=24)
    p_fetch.add_argument("--dry-run", action="store_true")
    p_fetch.set_defaults(func=cmd_fetch)

    p_star = sub.add_parser("star", help="Star a paper by arXiv id")
    p_star.add_argument("arxiv_id")
    p_star.set_defaults(func=cmd_star)

    p_list = sub.add_parser("list", help="List starred papers")
    p_list.set_defaults(func=cmd_list)

    p_search = sub.add_parser("search", help="Search in starred papers")
    p_search.add_argument("query")
    p_search.set_defaults(func=cmd_search)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
