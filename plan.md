# Podcast RSS Feed Proxy — Implementation Plan

## Overview

A synchronous Python proxy.
**The main loop (sequential, no async, no parallelism):**
For each configured feed:

1.  Download the upstream RSS/Atom feed.
    
2.  For each new media entry:
    *   Download the original audio into `podcast_slug/old/media/`.
        
    *   Process it through ffmpeg (cut in half) into `podcast_slug/new/media/`.
        
3.  Generate the new Atom feed pointing at the processed files.
    

Served over HTTP as static files only. No API, no admin, no database.

* * *

## Tech Stack

| Concern | Library | Notes |
| --- | --- | --- |
| Config validation | `pydantic` | v2. One model, done. |
| Config file | `pyyaml` | Single `feeds.yaml`. |
| Parse upstream | `feedparser` | Handles RSS 2.0 and Atom. |
| Generate proxy feed | `python-feedgen` | Output is always Atom. |
| HTTP fetch | `requests` (sync) | `stream=True` for audio. |
| Scheduler | `apscheduler` | `BackgroundScheduler`, 1 thread, in-process. |
| Web server | `starlette` + `uvicorn` | Static files only. |
| Audio processing | `ffmpeg` / `ffprobe` | Called via `subprocess.run()`. |

Everything is synchronous. No `async`, no `await`, no event loop, no thread pools per feed.

* * *

## Directory Layout

```
podcast-proxy/
├── config/
│   └── feeds.yaml
├── podcasts/                     # runtime state (gitignore)
│   └── {slug}/
│       ├── old/
│       │   ├── media/            # original audio
│       │   └── rss/
│       │       └── full.atom     # upstream feed snapshot
│       └── new/
│           ├── media/            # processed audio
│           └── full.atom         # generated Atom feed
├── src/
│   ├── config.py                 # Pydantic models + YAML loader
│   ├── paths.py                  # FeedPaths dataclass (DRY)
│   ├── fetcher.py                # download upstream feed + media
│   ├── processor.py              # ffmpeg wrapper
│   ├── generator.py              # build new Atom feed preserving GUIDs
│   ├── sync.py                   # THE main sequential loop
│   ├── scheduler.py              # APScheduler setup
│   └── web.py                    # Starlette static files only
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_config.py
│   │   ├── test_fetcher.py
│   │   ├── test_processor.py
│   │   └── test_generator.py
│   └── integration/
│       ├── test_sync.py
│       └── test_web.py
├── pyproject.toml
└── README.md
```

* * *

## Coding Guidelines

### YAGNI

*   **No admin/status page.**
    
*   **No database / ORM / Redis / queue.** Filesystem is the state.
    
*   **No async.** It adds complexity (`async subprocess` is awkward) and ffmpeg bottlenecks on CPU anyway.
    
*   **No hot-reload.** Restart the process to reload config.
    
*   **No structured logging infrastructure.** `logging.basicConfig` is enough.
    
*   **No distributed workers.** One process, one scheduler thread.
    
*   **No retry abstraction.** `requests` retry adapter for HTTP; log-and-continue for ffmpeg failures.
    
*   **No plugin pipeline.** One concrete `process_audio()` function.
    

### DRY

*   **Path construction lives in exactly one place:** `FeedPaths` in `paths.py`. Every other module imports it.
    
*   **Filename derivation** (from URL/GUID) lives in one helper.
    
*   **If you copy-paste entry-to-feed mapping logic, extract a function.**
    

### Test As You Go

*   Write unit tests **immediately after** finishing each module, before starting the next.
    
*   When integration tests find bugs, reproduce them in a unit test first, then fix.
    
*   **Without tests, the module is not done.**
    

* * *

## Config (`config/feeds.yaml`)

```yaml
feeds:
  - feed_url: "https://example.com/podcast.rss"
    keep_article: 10
    podcast_slug: "my-podcast"
    feed_path: "my-podcast"
```

| Field | Meaning |
| --- | --- |
| `feed_url` | Upstream RSS or Atom URL. |
| `keep_article` | How many recent episodes to keep in the proxy feed. |
| `podcast_slug` | Directory name on disk. Alphanumeric + hyphens only. |
| `feed_path` | URL path prefix. Can differ from `slug`. |

* * *

## The Main Loop (`sync.py`)

This is the heart of the system. Run it once per feed per sync.

```
sync_feed(feed_config):
  paths = FeedPaths(feed_config.podcast_slug)

  # 1. Download upstream feed
  raw_xml, parsed = fetch_feed(feed_config.feed_url)
  save raw_xml to paths.old_rss_file

  # 2. Collect entries to keep
  kept_entries = parsed.entries[:feed_config.keep_article]
  media_mappings = {}

  # 3. For each entry: download original, process audio
  for entry in kept_entries:
      enclosure_url = first_audio_enclosure(entry)
      if not enclosure_url:
          continue

      filename = derive_filename(enclosure_url, entry.id)
      old_path = paths.old_media_dir / filename
      new_path = paths.new_media_dir / filename

      # 3a. Download original if not present
      if not old_path.exists() or old_path.stat().st_size == 0:
          download_media(enclosure_url, old_path)

      # 3b. Process with ffmpeg if not present
      if not new_path.exists() or new_path.stat().st_size == 0:
          process_audio(old_path, new_path)   # writes .tmp, then renames atomically

      media_mappings[enclosure_url] = filename

  # 4. Generate new Atom feed
  #    Only include entries whose new/media/ file exists and is non-empty.
  valid_entries = filter(entries_with_existing_new_media, kept_entries)
  atom_xml = generate_atom(
      feed_config, parsed, valid_entries, media_mappings, base_url
  )
  atomic_write(atom_xml, paths.new_rss_file)
```

**Critical behaviors:**

*   **Idempotency:** If `old/media/` file exists with size > 0, skip download. If `new/media/` file exists with size > 0, skip ffmpeg.
    
*   **Partial resilience:** If one entry's ffmpeg fails, log the error and exclude it from the feed. Continue with the rest. Do not crash the whole sync.
    
*   **Atomic writes:** Always write to `.tmp` next to the target, then `os.replace()`/`os.rename()`.
    
*   **GUID preservation:** The generated feed MUST use the exact same `entry.id` as the upstream. This is the single most important invariant.
    

* * *

## Module-by-Module Plan

### Step 1 — `config.py`

*   `FeedConfig` Pydantic model with validators.
    
*   `AppConfig` model holding `list[FeedConfig]`.
    
*   `load_config(path) -> AppConfig`.
    

**Gotcha:** Use `str` for `feed_url`, not Pydantic `HttpUrl`. Podcast feeds sometimes use non-HTTP schemes or weird URLs that `HttpUrl` rejects.
**Gotcha:** Validate `podcast_slug` rejects `/`, `\`, `..`, spaces at config load time. Crash immediately with a clear message.
**Test:** valid YAML → loads; missing field → `ValidationError`; bad slug → `ValidationError`.

* * *

### Step 2 — `paths.py`

A single dataclass `FeedPaths(slug: str, base_dir: Path)` with properties:

*   `old_media_dir`
    
*   `old_rss_file`
    
*   `new_media_dir`
    
*   `new_rss_file`
    

No path string concatenation anywhere else in the codebase.

* * *

### Step 3 — `fetcher.py`

Two functions:

*   `fetch_feed(url: str) -> tuple[str, FeedParserDict]` — returns raw XML string and parsed feed.
    
*   `download_media(url: str, dest: Path) -> None` — streams to disk.
    

**Critical:** `requests.get(url, stream=True, timeout=600)` for media. Audio files can be 200 MB+; never load into memory.
**Critical:** Mount a `requests.Session` with `HTTPAdapter(retries=Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504]))`. A transient 503 on a big file should not kill the sync.
**Gotcha:** `feedparser.parse()` can take a raw string. Don't pass a file handle.
**Gotcha:** `entry.id` is the GUID. Test with real feeds early — feedparser "repairs" some feeds and you need to verify what `entry.id` actually contains vs. the raw XML.
**Test:** mocked 200 RSS → parsed entries; mocked audio → file on disk with correct size; 404 → raises; timeout → raises.

* * *

### Step 4 — `processor.py`

```python
def process_audio(input_path: Path, output_path: Path) -> None
```

Steps:

1.  `ffprobe` to get duration.
    
2.  Compute half.
    
3.  `ffmpeg -y -i {input} -t {half} -c copy {tmp_output}`.
    
4.  `os.replace(tmp_output, output_path)`.
    

**Critical — timeouts:** If real processing may take 40 min, set `subprocess.run(..., timeout=5400)` (90 min). A hanging ffmpeg must not block the proxy forever.
**Critical — atomic output:** Write to `{output_path}.tmp`, then rename. If the process crashes mid-write, the half-written file is never served.
**Critical — verify output exists and is non-empty after subprocess returns.** FFmpeg exit codes are sometimes misleading.
**Critical — startup check.** At process startup, run `ffmpeg -version` via subprocess. If missing, crash immediately with a clear error before the web server starts.
**Decision:** `-c copy` (fast, no re-encode) vs. re-encode (`-c:a libmp3lame`). `-c copy` only cuts on keyframes. For a simple proxy, `-c copy` is probably enough and is near-instant. Document this choice. If frame-accurate cuts matter later, change one line.
**Test:** 2-second MP3 fixture → output is ~1 second. Missing ffmpeg → clear startup failure.

* * *

### Step 5 — `generator.py`

```python
def generate_atom(
    feed_config: FeedConfig,
    original_parsed: FeedParserDict,
    entries: list[dict],
    media_urls: dict[str, str],
    base_url: str,
) -> str
```

Use `python-feedgen`, load the `podcast` extension.
**Invariant — GUIDs:** After generating, you must be able to parse your own output with `feedparser` and assert `output_entry.id == original_entry.id` character-for-character for every entry. **This is the most important test in the project.**
**Gotcha — GUIDs vs. Atom** `<id>`**:** Atom IDs are technically URIs. If the upstream RSS uses `<guid isPermaLink="false">abc123</guid>` (not a URI), `python-feedgen` may try to escape or alter it when setting `fe.id()`. Inspect the raw XML output, not just the Python object. You may need special handling if GUIDs are not valid URIs.
**Gotcha — dates:** `feedparser` gives `published_parsed` as a `time.struct_time` (naive). Convert to timezone-aware `datetime` before passing to `python-feedgen`, or it will reject them. Assume UTC if no timezone is present.
**Gotcha — author:** Atom requires `<author>`. RSS may not have one. Fallback to the feed title or `"Unknown"` if missing.
**Gotcha — enclosures:** Some entries have multiple enclosures (MP3 + OGG + video). Use the first `audio/*` enclosure. Skip entries with no enclosures entirely.
**Gotcha — feed-level metadata:** Copy the upstream feed title, description, language, image, etc. The proxy feed should look like the original except for the enclosure URLs.
**Test:** fixture entries → generated Atom → re-parsed with feedparser → GUIDs match exactly; entry count respects `keep_article`; every enclosure URL points to `.../new/media/...`.

* * *

### Step 6 — `sync.py`

See the main loop above. One function:

```python
def sync_feed(feed_config: FeedConfig, base_url: str) -> None
```

**Idempotency rule:** Before download or processing, check `path.exists() and path.stat().st_size > 0`. If yes, skip. This makes re-runs safe and cheap.
**Filename derivation:** Derive from the GUID or a hash of the enclosure URL, not the original filename. Some feeds reuse filenames like `episode.mp3` across episodes. Example: `{hashlib.sha256(guid.encode()).hexdigest()[:16]}.mp3`.
**Partial failure:** Wrap each entry's processing in `try/except`. Log at ERROR, skip the entry, continue with the next. The final feed simply omits the failed entry.
**Entry order:** Preserve upstream order exactly. Do not sort by processing completion time.
**Test:** full mocked pipeline → verify directory structure. Run twice → second run does nothing (no HTTP, no ffmpeg). One ffmpeg fails → feed still generated, missing that entry.

* * *

### Step 7 — `scheduler.py`

```python
from apscheduler.schedulers.background import BackgroundScheduler

def start_scheduler(feeds: list[FeedConfig], base_url: str) -> BackgroundScheduler:
    sched = BackgroundScheduler()
    for feed in feeds:
        sched.add_job(
            sync_feed,
            trigger="interval",
            hours=1,
            args=[feed, base_url],
            id=feed.podcast_slug,
            max_instances=1,      # never overlap
            replace_existing=True,
        )
    sched.start()
    # Initial sync: sequential, not parallel
    for feed in feeds:
        try:
            sync_feed(feed, base_url)
        except Exception:
            logger.exception(f"Initial sync failed for {feed.podcast_slug}")
    return sched
```

`BackgroundScheduler` spawns one background thread that manages a thread pool. Each `sync_feed` runs in its own thread when triggered, but since the loop itself is sequential, the main work stays easy to reason about.
**Gotcha:** `max_instances=1` is mandatory. If a sync takes 70 min and the interval is 60, the next trigger is skipped rather than stacking up two concurrent syncs.
**Gotcha:** Initial syncs run sequentially. With long ffmpeg processing (40 min) and multiple feeds, the second feed simply waits for the first. This is intentional — your CPU is already saturated by ffmpeg.

* * *

### Step 8 — `web.py`

```python
from starlette.applications import Starlette
from starlette.staticfiles import StaticFiles

def create_app(podcasts_dir: Path) -> Starlette:
    app = Starlette()
    app.mount("/", StaticFiles(directory=str(podcasts_dir), html=False))
    return app
```

That is the entire web server. No routes. No middleware unless required.
**Gotcha:** `html=False` prevents `index.html` fallback on directory requests.
**Gotcha:** Verify `.atom` returns `application/atom+xml`. Starlette's MIME type inference usually handles this, but test it.
**Gotcha:** `StaticFiles` supports HTTP `Range` requests by default. Large MP3s will stream correctly to podcast clients without loading fully into memory.
**Test:** `TestClient` from `starlette.testclient` — `GET /{slug}/new/full.atom` → 200 + correct Content-Type; `GET /{slug}/new/media/test.mp3` → 200 + `audio/mpeg`; missing file → 404.

* * *

### Step 9 — Entry Point (`main.py`)

```
main():
  config = load_config("config/feeds.yaml")
  create all directories upfront via FeedPaths
  verify ffmpeg is installed (subprocess check, crash if not)
  sched = start_scheduler(config.feeds, BASE_URL)
  app = create_app(Path("podcasts"))
  uvicorn.run(app, host="0.0.0.0", port=8080)
  sched.shutdown(wait=False)
```

**Gotcha:** Initial sync happens inside `start_scheduler()`, before the web server binds. This means `podcasts/` is populated before the first HTTP request. If an upstream is down, the feed is simply missing (or stale from prior run) — log and continue.

* * *

## Critical Checklist (Read Before Coding)

| # | Risk | Mitigation |
| --- | --- | --- |
| 1 | **GUID mismatch** → all clients re-download | Test: parse generated Atom, assert `id` matches upstream exactly. |
| 2 | Non-URI GUIDs break in Atom `<id>` | Inspect raw XML output. Some GUIDs may need URI wrapping. |
| 3 | ffmpeg hangs/blocks forever | `subprocess.run(..., timeout=5400)` minimum. |
| 4 | Crash while writing file → partial/corrupt file | Write to `.tmp`, then `os.replace()`. |
| 5 | Re-downloading unchanged files every hour | Skip if file exists and `st_size > 0`. |
| 6 | Re-processing unchanged files every hour | Skip if `new/media/` file exists and `st_size > 0`. |
| 7 | Feed references missing media | Filter entries: only include those with valid `new/media/` files. |
| 8 | Filename collisions | Derive from GUID hash, not original filename. |
| 9 | Atom requires author, RSS might lack it | Fallback to `"Unknown"` or feed title. |
| 10 | Naive datetimes rejected by python-feedgen | Convert `time.struct_time` → timezone-aware `datetime` (UTC assumed). |
| 11 | Overlapping sync jobs | `max_instances=1` on APScheduler jobs. |
| 12 | Entry order reversed accidentally | Preserve upstream order; do not sort by processing time. |

* * *

## Test Strategy

**Unit tests (one per module):**

*   `test_config.py` — load valid, missing field, bad slug.
    
*   `test_fetcher.py` — mocked HTTP, streaming download, retries on 503.
    
*   `test_processor.py` — small MP3 fixture, verify output duration, verify atomic write.
    
*   `test_generator.py` — fixture entries in, GUIDs match, Atom valid, enclosure URLs correct.
    

**Integration tests:**

*   `test_sync.py` — full mocked pipeline (no real HTTP), verify idempotency on second run, verify partial failure skips entry.
    
*   `test_web.py` — `TestClient`, static file serving, MIME types, 404s.
    

**Fixtures needed:**

*   Minimal valid RSS 2.0 with 3 episodes + enclosures.
    
*   Minimal valid Atom feed with 3 episodes.
    
*   RSS with `isPermaLink="false"` GUIDs.
    
*   MP3 generated by ffmpeg (~2 seconds). Commit small fixtures to `tests/fixtures/`.
    

**Write tests after each module. Do not proceed without them.**

* * *

## Dependencies

```toml
[project]
name = "podcast-proxy"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2",
    "pyyaml",
    "feedparser",
    "feedgen",
    "requests",
    "apscheduler",
    "starlette",
    "uvicorn",
]

[project.optional-dependencies]
dev = [
    "pytest",
    "httpx",      # for Starlette TestClient
]
```

System dependency: `ffmpeg` and `ffprobe` on `$PATH`.