"""Download NASA's Astronomy Picture of the Day or refresh the README gallery."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
from io import BytesIO
import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from PIL import Image, ImageOps, UnidentifiedImageError


API = "https://science.nasa.gov/wp-json/wp/v2/apod-basic"
README = Path(__file__).resolve().with_name("README.md")
ASSETS = Path("assets/apod-week")
START = "<!-- apod-week:start -->"
END = "<!-- apod-week:end -->"
GALLERY_DAYS = 7
DOWNLOAD_DAYS = 5
EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "GIF": ".gif", "WEBP": ".webp", "TIFF": ".tiff"}


class CreditParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.parts.append(" ")


@dataclass(frozen=True)
class Entry:
    day: date
    title: str
    media_type: str
    page: str
    image: str | None
    credit: str


def fetch(url):
    request = Request(url, headers={"User-Agent": "NASAPic (github.com/LittleCabbage-00/NASAPic)"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=18) as response:
                return response.read()
        except HTTPError as error:
            if error.code in (404, 410):
                return None
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (URLError, TimeoutError, ConnectionError):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)


def https_link(value):
    parts = urlsplit(value or "")
    return value if parts.scheme == "https" and parts.hostname else None


def entry_from(row):
    day = date.fromisoformat(row["date"])
    page = https_link(row.get("permalink")) or https_link(row.get("url"))
    if page is None:
        raise ValueError(f"APOD entry {day} has no article link.")

    parser = CreditParser()
    parser.feed(row.get("copyright") or row.get("credit") or "")
    parser.close()
    credit = " ".join("".join(parser.parts).split())
    return Entry(
        day, row["title"], row["media_type"], page,
        https_link(row.get("hdurl")), credit,
    )


def get_entries(count, day=None):
    endpoint = f"{API}/{day:%y%m%d}" if day else f"{API}?per_page={count}"
    data = fetch(endpoint)
    if data is None:
        return []
    records = json.loads(data)
    if day:
        records = [records]
    entries = {entry.day: entry for entry in map(entry_from, records)}
    if day:
        return [entries[day]] if day in entries else []
    return [entries[key] for key in sorted(entries, reverse=True)[:count]]


def write_atomically(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = NamedTemporaryFile(dir=path.parent, suffix=".part", delete=False)
    temp_path = Path(pending.name)
    try:
        with pending:
            pending.write(data)
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def download(entries, output):
    for entry in sorted(entries, key=lambda entry: entry.day):
        if entry.media_type != "image" or entry.image is None:
            print(f"{entry.day}: see {entry.page}")
            continue

        prefix = f"nasa_pic_{entry.day}_"
        if any(path.suffix.lower() in EXTENSIONS.values() for path in output.glob(f"{prefix}*")):
            continue
        data = fetch(entry.image)
        if data is None:
            raise SystemExit(f"APOD image unavailable for {entry.day}: {entry.page}")
        with Image.open(BytesIO(data)) as image:
            suffix = EXTENSIONS.get(image.format)
            image.verify()
        if suffix is None:
            raise SystemExit(f"Unsupported image format for {entry.day}: {entry.page}")

        title = re.sub(r'[<>:"/\\|?*\x00-\x1f\s]+', "_", entry.title)[:90].rstrip(". ")
        path = output / f"{prefix}{title}{suffix}"
        write_atomically(path, data)
        print(path)


def make_thumbnail(entry):
    if entry.image is None:
        return None
    if entry.media_type != "image" and Path(urlsplit(entry.image).path).suffix.lower() not in {
        *EXTENSIONS.values(), ".jpeg", ".tif",
    }:
        return None

    data = fetch(entry.image)
    if data is None:
        return None
    try:
        with Image.open(BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source)
            width, height = image.size
            image.thumbnail((640, 400), Image.Resampling.LANCZOS)
            binary = BytesIO()
            image.convert("RGB").save(binary, format="JPEG", quality=80, optimize=True)
    except UnidentifiedImageError:
        return None
    return binary.getvalue(), width, height


def gallery_row(entry, thumbnail, assets):
    page = escape(entry.page)
    title = escape(entry.title)
    preview = ""
    detail = [f'<a href="{page}"><strong>{title}</strong></a>']
    if entry.media_type != "image":
        detail.append(f'<a href="{page}">打开媒体</a>')
    if thumbnail:
        binary, width, height = thumbnail
        name = f"{sha256(binary).hexdigest()[:20]}.jpg"
        assets[name] = binary
        target = escape(entry.image) if entry.media_type == "image" else page
        preview = f'<a href="{target}"><img src="{ASSETS.as_posix()}/{name}" alt="{title}" width="256"></a>'
        if entry.media_type == "image":
            label = "4K 图像" if min(width, height) >= 2160 and max(width, height) >= 3840 else "查看大图"
            detail.append(f'<a href="{target}">{label}</a> · {width} × {height}')
    elif entry.image and entry.media_type == "image":
        detail.append(f'<a href="{escape(entry.image)}">查看大图</a>')
    if entry.credit:
        detail.append(f"<sub>{escape(entry.credit)}</sub>")
    return f'<tr><th scope="row">{entry.day}</th><td>{preview}</td><td>{"<br>".join(detail)}</td></tr>'


def update_gallery(entries):
    readme = README.read_text(encoding="utf-8")
    introduction, block = readme.split(START)
    old_gallery, instructions = block.split(END)
    previous = re.search(r"<!-- apod-date: (\d{4}-\d{2}-\d{2}) -->", old_gallery)
    latest = entries[0].day
    if previous and date.fromisoformat(previous[1]) > latest:
        print(f"Keeping newer gallery from {previous[1]}; feed ended at {latest}.")
        return

    lines = [
        "", f"<!-- apod-date: {latest} -->", "", "<table>",
        '<thead><tr><th scope="col">日期</th><th scope="col">预览</th><th scope="col">APOD</th></tr></thead>',
        "<tbody>",
    ]
    images = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for entry, thumbnail in zip(entries, pool.map(make_thumbnail, entries)):
            lines.append(gallery_row(entry, thumbnail, images))
    lines += ["</tbody>", "</table>", ""]

    folder = README.parent / ASSETS
    for name, binary in images.items():
        path = folder / name
        if not path.exists() or path.read_bytes() != binary:
            write_atomically(path, binary)
    updated = introduction + START + "\n".join(lines) + END + instructions
    if updated != readme:
        write_atomically(README, updated.encode("utf-8"))
    for old in folder.glob("*.jpg"):
        if old.name not in images and re.fullmatch(r"[0-9a-f]{20}\.jpg", old.name):
            old.unlink()
    print(f"APOD gallery: {entries[-1].day} to {latest}, {len(images)} thumbnails")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("gallery", help="refresh the README gallery")
    downloader = commands.add_parser("download", help="save recent APOD images locally")
    downloader.add_argument("--date", type=date.fromisoformat, help="download one APOD date (YYYY-MM-DD)")
    downloader.add_argument("--output", type=Path, default=Path("downloads"), help="download directory")
    args = parser.parse_args()

    if args.command == "gallery":
        entries = get_entries(GALLERY_DAYS)
        if len(entries) < GALLERY_DAYS:
            raise SystemExit(f"Expected {GALLERY_DAYS} APOD entries, got {len(entries)}.")
        update_gallery(entries)
    else:
        entries = get_entries(DOWNLOAD_DAYS, args.date)
        if not entries:
            raise SystemExit("No APOD entries found for the requested date.")
        download(entries, args.output)


if __name__ == "__main__":
    main()
