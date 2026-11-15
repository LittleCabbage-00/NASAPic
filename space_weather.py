"""Archive NOAA's daily maximum Kp and reported X-ray flares in UTC."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
README = ROOT / "README.md"
ARCHIVE = ROOT / "data/space-weather.json"
KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
EVENTS_URL = "https://services.swpc.noaa.gov/json/edited_events.json"
KP_HOURS = set(range(0, 24, 3))
WINDOW_DAYS = 7
START = "<!-- space-weather:start -->"
END = "<!-- space-weather:end -->"


def fetch_records(url):
    request = Request(url, headers={"User-Agent": "NASAPic space weather archive"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=20) as response:
                records = json.load(response)
            if not isinstance(records, list) or not records:
                raise ValueError(f"Expected a nonempty NOAA record list from {url}")
            return records
        except HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (URLError, TimeoutError, ConnectionError):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)


def flare_rank(event):
    level = event["class"]
    return "ABCMX".index(level[0]), float(level[1:])


def flare_report_rank(event):
    # Use a stable tie-break when two observatories report the same class.
    return flare_rank(event), event["peak_utc"], event["observatory"]


def daily_records(kp_rows, event_rows, today):
    kp_by_day = defaultdict(dict)
    for row in kp_rows:
        timestamp = datetime.fromisoformat(row["time_tag"])
        kp = row["Kp"]
        if kp is not None and 0 <= kp <= 9:
            kp_by_day[timestamp.date()][timestamp.hour] = kp

    # NOAA groups several satellite reports of the same flare under one bin.
    events = {}
    for row in event_rows:
        level = row.get("particulars1") or ""
        if row["type"] != "XRA" or not re.fullmatch(r"[ABCMX]\d+(?:\.\d+)?", level):
            continue
        peak = row.get("max_datetime")
        if not peak:
            continue
        event = {
            "id": row["bin"],
            "class": level,
            "begin_utc": row.get("begin_datetime"),
            "peak_utc": peak,
            "end_utc": row.get("end_datetime"),
            "observatory": row["observatory"],
        }
        previous = events.get(event["id"])
        if previous is None or flare_report_rank(event) > flare_report_rank(previous):
            events[event["id"]] = event

    flares_by_day = defaultdict(list)
    for event in events.values():
        day = datetime.fromisoformat(event["peak_utc"]).date()
        flares_by_day[day].append(event)

    output = {}
    for offset in range(WINDOW_DAYS, 0, -1):
        day = today - timedelta(days=offset)
        slots = kp_by_day[day]
        if KP_HOURS.issubset(slots):
            flares = sorted(flares_by_day[day], key=lambda event: (event["peak_utc"], event["id"]))
            output[day.isoformat()] = {"max_kp": max(slots[hour] for hour in KP_HOURS), "flares": flares}
    return output


def update_readme(readme, archive):
    before, block = readme.split(START)
    _, after = block.split(END)
    lines = [
        "", "", "| 日期（UTC） | 最高 Kp | X 射线耀斑 | 最强耀斑 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for day in sorted(archive, reverse=True)[:WINDOW_DAYS]:
        record = archive[day]
        flares = record["flares"]
        strongest = max(flares, key=flare_rank)["class"] if flares else "—"
        lines.append(f'| {day} | {record["max_kp"]:.2f} | {len(flares)} | {strongest} |')
    return before + START + "\n".join([*lines, "", ""]) + END + after


def write_if_changed(path, content):
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = NamedTemporaryFile(dir=path.parent, suffix=".part", delete=False)
    try:
        with temporary:
            temporary.write(content.encode("utf-8"))
        Path(temporary.name).replace(path)
    finally:
        Path(temporary.name).unlink(missing_ok=True)


def main():
    today = datetime.now(timezone.utc).date()
    updates = daily_records(fetch_records(KP_URL), fetch_records(EVENTS_URL), today)
    if not updates:
        raise SystemExit("NOAA has no complete UTC days in the last seven days.")

    archive = json.loads(ARCHIVE.read_text(encoding="utf-8")) if ARCHIVE.exists() else {}
    archive.update(updates)
    readme = update_readme(README.read_text(encoding="utf-8"), archive)
    write_if_changed(ARCHIVE, json.dumps(archive, indent=2, sort_keys=True) + "\n")
    write_if_changed(README, readme)
    print(f"NOAA space weather: {len(updates)} complete Kp days through {max(updates)}")


if __name__ == "__main__":
    main()
