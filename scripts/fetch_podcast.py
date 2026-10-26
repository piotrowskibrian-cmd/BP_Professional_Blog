#!/usr/bin/env python3
"""Pull the podcast's Riverside RSS feed into the site before each build.

Writes _data/podcast.json (show info + episode list) and one page per
episode in _episodes/. Both are generated, so they're not committed.
Run by .github/workflows/deploy.yml on every build and once a day.

  python3 scripts/fetch_podcast.py                 # use feed from _config.yml
  python3 scripts/fetch_podcast.py --file feed.rss # offline test
"""
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IT = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"


def feed_url():
    with open(os.path.join(ROOT, "_config.yml"), encoding="utf-8") as f:
        m = re.search(r'^\s+feed:\s*"([^"]+)"', f.read(), re.M)
    if not m:
        sys.exit("podcast.feed not found in _config.yml")
    return m.group(1)


def fetch(url):
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "brianpiotrowski.com site build"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(5 * (attempt + 1))
    sys.exit(f"could not fetch podcast feed: {last}")


def text(el, tag):
    x = el.find(tag)
    return (x.text or "").strip() if x is not None and x.text else ""


def clean_html(s):
    s = re.sub(r"<p>\s*(<br\s*/?>)?\s*</p>", "", s or "")
    s = re.sub(r"<(script|style|iframe)[^>]*>.*?</\1>", "", s, flags=re.S | re.I)
    return s.strip()


def plain(s, limit=None):
    t = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    t = re.sub(r"\s+", " ", t).strip()
    if limit and len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
    return t


def duration(raw):
    raw = (raw or "").strip()
    if not raw:
        return ""
    if raw.isdigit():
        s = int(raw)
    else:
        parts = [int(p) for p in raw.split(":") if p.isdigit()]
        s = 0
        for p in parts:
            s = s * 60 + p
    h, m = divmod(s // 60, 60)
    return f"{h} hr {m} min" if h else f"{m} min"


def slugify(s):
    s = html.unescape(s).lower()
    s = re.sub(r"[’'`]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:80].rstrip("-")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    args = ap.parse_args()
    data = open(args.file, "rb").read() if args.file else fetch(feed_url())
    ch = ET.fromstring(data).find("channel")
    img = ch.find(IT + "image")
    show = {
        "title": text(ch, "title"),
        "description": plain(text(ch, "description") or text(ch, IT + "summary")),
        "image": img.get("href") if img is not None else "",
        "episodes": [],
    }
    out_dir = os.path.join(ROOT, "_episodes")
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(out_dir):
        if f.endswith(".md"):
            os.remove(os.path.join(out_dir, f))
    used = set()
    for it in ch.findall("item"):
        title = text(it, "title")
        enc = it.find("enclosure")
        audio = enc.get("url") if enc is not None else ""
        if not title or not audio:
            continue
        try:
            dt = parsedate_to_datetime(text(it, "pubDate"))
        except Exception:  # noqa: BLE001
            continue
        desc = clean_html(text(it, CONTENT + "encoded") or text(it, "description"))
        eimg = it.find(IT + "image")
        num = text(it, IT + "episode")
        m = re.search(r"CS\s*#\s*(\d+)", title)
        if not num and m:
            num = m.group(1)
        # "Topic | Guest | CS #24" -> topic + guest
        parts = [p.strip() for p in title.split("|")]
        topic = parts[0]
        guest = parts[1] if len(parts) > 2 else ""
        slug = slugify(f"{num + '-' if num else ''}{guest or topic}") or "episode"
        while slug in used:
            slug += "-2"
        used.add(slug)
        ep = {
            "title": title,
            "topic": topic,
            "guest": guest,
            "number": num,
            "date": dt.strftime("%Y-%m-%d"),
            "audio": audio,
            "duration": duration(text(it, IT + "duration")),
            "image": eimg.get("href") if eimg is not None else show["image"],
            "summary": plain(desc, 220),
            "slug": slug,
            "url": f"/podcast/{slug}/",
        }
        show["episodes"].append(ep)
        front = {k: ep[k] for k in ("title", "topic", "guest", "number", "date",
                                    "audio", "duration", "image", "summary")}
        front["description"] = ep["summary"]
        with open(os.path.join(out_dir, slug + ".md"), "w", encoding="utf-8") as f:
            f.write("---\n")
            for k, v in front.items():
                f.write(f"{k}: {json.dumps(v, ensure_ascii=False)}\n")
            f.write("---\n\n" + desc + "\n")
    show["episodes"].sort(key=lambda e: e["date"], reverse=True)
    os.makedirs(os.path.join(ROOT, "_data"), exist_ok=True)
    with open(os.path.join(ROOT, "_data", "podcast.json"), "w", encoding="utf-8") as f:
        json.dump(show, f, ensure_ascii=False, indent=1)
    print(f"{len(show['episodes'])} episodes")


if __name__ == "__main__":
    main()
