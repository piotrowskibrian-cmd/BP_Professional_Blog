#!/usr/bin/env python3
"""One-time import of the GoDaddy Website Builder blog into Jekyll.

Reads every post from the GoDaddy blog feed, pulls the full post from its
page, converts GoDaddy's rich text (Draft.js) to Markdown, downloads every
image into assets/images/blog/, and writes one file per post into _posts/.
Each post keeps its old address (/f/<slug>/) so existing links still work.

Runs in GitHub Actions (see .github/workflows/import.yml). Safe to re-run:
it overwrites what it wrote before. Standard library only.

  python3 scripts/import_godaddy.py            # live import
  python3 scripts/import_godaddy.py --fixture tests/fixture_posts.json
"""
import argparse
import hashlib
import json
import mimetypes
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

SITE = "https://brianpiotrowski.com"
WEBSITE_ID = "c01faaec-f5ee-4eff-90ce-22a52df5f818"
FEED = f"https://blog.apps.secureserver.net/v1/website/{WEBSITE_ID}/feed"
UA = "Mozilla/5.0 (compatible; BP-site-migration/1.0)"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTS_DIR = os.path.join(ROOT, "_posts")
IMG_DIR = os.path.join(ROOT, "assets", "images", "blog")
IMG_URL = "/assets/images/blog"

EXTRA_IMAGES = {}  # headshot and logo are committed directly in assets/images


# --------------------------------------------------------------- fetching
def get(url, binary=False, tries=4):
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
                ctype = r.headers.get("Content-Type", "")
                return (data, ctype) if binary else data.decode("utf-8")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last}")


def extract_post_json(html):
    i = html.find('"post":{"blogId"')
    if i < 0:
        return None
    s = i + len('"post":')
    depth, in_str, esc = 0, False, False
    for j in range(s, len(html)):
        c = html[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(html[s:j + 1])
    return None


def fetch_post(slug):
    for attempt in range(4):
        html = get(f"{SITE}/f/{slug}")
        post = extract_post_json(html)
        if post and post.get("fullContent"):
            return post
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"could not read post body for {slug}")


# --------------------------------------------------------------- images
def norm_src(src):
    if not src:
        return ""
    src = src.strip()
    if src.startswith("//"):
        src = "https:" + src
    # drop GoDaddy transform suffixes like /:/rs=w:600
    return src.split("/:/")[0]


EXT_BY_TYPE = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
               "image/webp": ".webp", "image/svg+xml": ".svg"}


def download_image(url, dest_no_ext):
    """Download url to dest_no_ext + detected extension. Returns the path."""
    candidates = [url, url + "/:/rs=w:1600", url + "/:/"]
    for u in candidates:
        try:
            data, ctype = get(u, binary=True, tries=2)
        except RuntimeError:
            continue
        ctype = ctype.split(";")[0].strip().lower()
        if not ctype.startswith("image/") or len(data) < 200:
            continue
        ext = EXT_BY_TYPE.get(ctype) or mimetypes.guess_extension(ctype) or ".jpg"
        path = dest_no_ext + ext
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path
    return None


class ImageStore:
    def __init__(self, dirname, offline=False):
        self.dir = os.path.join(IMG_DIR, dirname)
        self.offline = offline
        self.seen = {}
        self.missing = []

    def add(self, src):
        url = norm_src(src)
        if not url:
            return None
        if url in self.seen:
            return self.seen[url]
        n = len(self.seen) + 1
        base = os.path.join(self.dir, f"{n:02d}")
        if self.offline:
            path = base + ".jpg"
        else:
            path = download_image(url, base)
        if not path:
            self.missing.append(url)
            self.seen[url] = None
            return None
        rel = IMG_URL + "/" + os.path.relpath(path, IMG_DIR).replace(os.sep, "/")
        self.seen[url] = rel
        return rel


# --------------------------------------------------------------- Draft.js -> Markdown
MD_ESCAPE = re.compile(r"([\\`*_\[\]<>])")


def esc(text):
    return MD_ESCAPE.sub(r"\\\1", text)


def wrap(text, prefix, suffix):
    """Wrap text in markers, keeping edge whitespace outside them."""
    if not text.strip():
        return text
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    return f"{lead}{prefix}{text.strip()}{suffix}{trail}"


def inline(block, entity_map, plain_styles=()):
    text = block["text"]
    n = len(text)
    styles = [set() for _ in range(n)]
    links = [None] * n
    for r in block.get("inlineStyleRanges", []):
        st = r.get("style")
        if st in plain_styles:
            continue
        for k in range(r["offset"], min(n, r["offset"] + r["length"])):
            styles[k].add(st)
    for r in block.get("entityRanges", []):
        ent = entity_map.get(str(r["key"])) or {}
        if ent.get("type") == "LINK":
            d = ent.get("data") or {}
            href = d.get("url") or d.get("href")
            for k in range(r["offset"], min(n, r["offset"] + r["length"])):
                links[k] = href
    # group runs with identical (styles, link)
    out, k = [], 0
    while k < n:
        key = (frozenset(styles[k]), links[k])
        j = k
        while j < n and (frozenset(styles[j]), links[j]) == key:
            j += 1
        seg = esc(text[k:j])
        st, href = key
        if "ITALIC" in st:
            seg = wrap(seg, "*", "*")
        if "BOLD" in st:
            seg = wrap(seg, "**", "**")
        if "UNDERLINE" in st and not href:
            seg = wrap(seg, "<u>", "</u>")
        if href and seg.strip():
            seg = wrap(seg, "[", f"]({href})")
        out.append(seg)
        k = j
    s = "".join(out)
    # merge adjacent identical markers like **a****b**
    s = s.replace("****", "")
    # line breaks inside a block
    s = re.sub(r"[ \t]*\n[ \t]*", "  \n", s).strip()
    return s


def protect_line_start(s):
    """Stop plain paragraphs from turning into lists or headings."""
    s = re.sub(r"^(\d+)\. ", r"\1\\. ", s)
    s = re.sub(r"^([#>+\-]) ", r"\\\1 ", s)
    return s


def to_markdown(full, images, skip_src=None):
    entity_map = full.get("entityMap", {})
    lines = []
    prev = None
    ol_count = 0
    skipped_hero = False
    for b in full.get("blocks", []):
        t = b["type"]
        if t == "atomic":
            ent = None
            for r in b.get("entityRanges", []):
                ent = entity_map.get(str(r["key"]))
            if ent and ent.get("type") == "IMAGE":
                src = norm_src(ent["data"].get("src"))
                if skip_src and not skipped_hero and src == skip_src:
                    skipped_hero = True
                    continue
                rel = images.add(src)
                if rel:
                    alt = esc(ent["data"].get("alt") or "")
                    lines.append(("p", f"![{alt}]({{{{ '{rel}' | relative_url }}}})"))
            prev = t
            continue
        is_header = t.startswith("header-")
        body = inline(b, entity_map, plain_styles=("BOLD",) if is_header else ())
        if not body.strip():
            prev = t if t.endswith("list-item") else None
            continue
        depth = b.get("depth", 0)
        if t == "unordered-list-item":
            lines.append(("li", "  " * depth + "- " + body))
        elif t == "ordered-list-item":
            ol_count = ol_count + 1 if prev == t else 1
            lines.append(("li", "   " * depth + f"{ol_count}. " + body))
        elif t == "header-one" or t == "header-two":
            lines.append(("p", "## " + body))
        elif t.startswith("header-"):
            lines.append(("p", "### " + body))
        elif t == "blockquote":
            lines.append(("bq", "> " + body.replace("  \n", "  \n> ")))
        else:
            lines.append(("p", protect_line_start(body)))
        prev = t
    # join: list items and quote lines of the same kind stay together
    out = []
    for i, (kind, text) in enumerate(lines):
        if i and not (kind == lines[i - 1][0] and kind in ("li",)):
            if kind == "bq" and lines[i - 1][0] == "bq":
                out.append(">")
            else:
                out.append("")
        out.append(text)
    return "\n".join(out).strip() + "\n"


# --------------------------------------------------------------- writing
def ascii_slug(slug):
    s = urllib.parse.unquote(slug)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or hashlib.md5(slug.encode()).hexdigest()[:8]


def yaml_str(s):
    return json.dumps((s or "").strip(), ensure_ascii=False)


def write_post(post, offline=False):
    slug = post["slug"]
    date = post.get("date") or post.get("publishedDate")
    day = date[:10]
    name = ascii_slug(slug)
    images = ImageStore(name, offline=offline)
    hero_src = norm_src(post.get("featuredImage"))
    hero = images.add(hero_src) if hero_src else None
    full = json.loads(post["fullContent"])
    md = to_markdown(full, images, skip_src=hero_src if hero else None)
    excerpt = re.sub(r"\s+", " ", (post.get("content") or "")).strip()
    if excerpt.endswith("..."):
        excerpt = excerpt[:-3].rstrip() + "…"
    permalink = "/f/" + urllib.parse.unquote(slug) + "/"
    fm = [
        "---",
        f"title: {yaml_str(post['title'])}",
        f"date: {date[:10]} {date[11:19] or '12:00:00'} +0000",
        f"permalink: {yaml_str(permalink)}",
        f"description: {yaml_str(excerpt)}",
    ]
    if hero:
        fm.append(f"image: {yaml_str(hero)}")
    cats = [c.get("name") if isinstance(c, dict) else c for c in post.get("categories") or []]
    if cats:
        fm.append("tags: " + json.dumps(cats, ensure_ascii=False))
    fm.append(f"godaddy_url: {yaml_str(SITE + '/f/' + slug)}")
    fm.append("---")
    os.makedirs(POSTS_DIR, exist_ok=True)
    path = os.path.join(POSTS_DIR, f"{day}-{name}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(fm) + "\n\n" + md)
    return path, images.missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", help="JSON list of post objects (offline test)")
    args = ap.parse_args()

    if args.fixture:
        with open(args.fixture, encoding="utf-8") as f:
            posts = json.load(f)
        for p in posts:
            path, _ = write_post(p, offline=True)
            print("wrote", os.path.relpath(path, ROOT))
        return 0

    feed = json.loads(get(FEED))["feed"]
    print(f"{len(feed)} posts in feed")
    problems, written = [], 0
    for item in feed:
        slug = item["slug"]
        try:
            post = fetch_post(slug)
            path, missing = write_post(post)
            written += 1
            print("wrote", os.path.relpath(path, ROOT))
            for m in missing:
                problems.append(f"{slug}: image not downloaded: {m}")
        except Exception as e:  # noqa: BLE001
            problems.append(f"{slug}: {e}")
            print("FAILED", slug, e, file=sys.stderr)
        time.sleep(0.5)
    for url, dest in EXTRA_IMAGES.items():
        base = os.path.splitext(dest)[0]
        if not download_image(url, base):
            problems.append(f"extra image not downloaded: {url}")

    report = [f"Imported {written} of {len(feed)} posts."] + problems
    with open(os.path.join(ROOT, "scripts", "import_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(report) + "\n")
    print("\n".join(report))
    return 0 if written == len(feed) else 1


if __name__ == "__main__":
    sys.exit(main())
