#!/usr/bin/env python3
"""NN/g videos viewer: scrapes nngroup.com and serves a page listing videos by chosen authors.

Run:  python3 server.py   then open http://localhost:8765
"""
import json
import re
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = "https://www.nngroup.com"
PORT = int(__import__("os").environ.get("PORT", 8765))
HERE = Path(__file__).parent
CACHE_FILE = HERE / "cache.json"
AUTHORS = ["Maria Rosala", "Lola Famulegun", "Sarah Gibbons", "Kate Moran", "Therese Fessenden"]
UA = {"User-Agent": "Mozilla/5.0 (nng-videos-viewer)"}

lock = threading.Lock()


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def load_cache():
    try:
        return json.loads(CACHE_FILE.read_text())
    except Exception:
        return {}


def list_new_video_urls(cache):
    """Walk the listing newest-first, stopping at the first page with nothing new."""
    paths, page = [], 1
    while page <= 50:
        html = fetch(f"{BASE}/articles/?asset=videos&page={page}")
        found = re.findall(r'<h2 class="title"><a href="(/videos/[^"]+)">', html)
        new = [p for p in found if p not in cache and p not in paths]
        if not found:
            break
        paths += new
        if not new:
            break
        page += 1
    return paths


def parse_video(path):
    html = fetch(BASE + path)
    title = re.search(r'<h1 class="article-h1">(.*?)</h1>', html, re.S)
    date = re.search(r'id="gaDataPubDate"[^>]*>([\d-]+)<', html)
    authors = re.search(r'id="gaDataAuthors"[^>]*>(.*?)</span>', html, re.S)
    length = re.search(r'id="gaDataLength"[^>]*>(\d+)<', html)
    summary = re.search(r'<strong>Summary:</strong>&nbsp;(.*?)</p>', html, re.S)
    yt = re.search(r'youtube(?:-nocookie)?\.com/(?:watch\?v=|embed/)(?:video/)?([\w-]{11})', html)
    return {
        "youtube": f"https://www.youtube.com/watch?v={yt.group(1)}" if yt else "",
        "title": unescape(re.sub(r"<[^>]+>", "", title.group(1))).strip() if title else path,
        "url": BASE + path,
        "date": date.group(1) if date else "",
        "minutes": int(length.group(1)) if length else None,
        "authors": [a.strip() for a in unescape(authors.group(1)).split(",")] if authors else [],
        "summary": unescape(re.sub(r"<[^>]+>", "", summary.group(1))).strip() if summary else "",
    }


def get_videos(refresh=True):
    with lock:
        cache = load_cache()
        todo = list_new_video_urls(cache) if refresh else []
        if refresh:  # backfill YouTube links for saved videos by our authors
            todo += [p for p, v in cache.items()
                     if "youtube" not in v and any(a in AUTHORS for a in v["authors"])]
        if todo:
            with ThreadPoolExecutor(max_workers=8) as ex:
                for p, v in zip(todo, ex.map(parse_video, todo)):
                    cache[p] = v
            CACHE_FILE.write_text(json.dumps(cache, indent=1))
        videos = list(cache.values())
    wanted = [v for v in videos if any(a in AUTHORS for a in v["authors"])]
    wanted.sort(key=lambda v: v["date"], reverse=True)
    return {"authors": AUTHORS, "scanned": len(videos), "new": len(todo), "videos": wanted}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/videos"):
            try:
                self.send(200, json.dumps(get_videos("cached" not in self.path)).encode(), "application/json")
            except Exception as e:
                self.send(502, json.dumps({"error": str(e)}).encode(), "application/json")
        elif self.path in ("/", "/index.html"):
            self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        else:
            self.send(404, b"Not found", "text/plain")


if __name__ == "__main__":
    print(f"Listening on port {PORT}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
