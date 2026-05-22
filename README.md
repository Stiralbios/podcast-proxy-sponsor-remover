# Podcast Proxy Sponsor Remover

A synchronous Python proxy server that downloads podcast RSS feeds, removes sponsor/ad segments from the audio using Scriberr transcription + LLM detection + FFmpeg, and serves the cleaned episodes over HTTP as a new Atom feed.

**Core philosophy:** Everything is synchronous. No `async`, no `await`, no thread pools. One loop per feed, sequential, easy to reason about.

---

## What It Does

1. **Downloads** upstream RSS/Atom feeds every hour
2. **Downloads** original audio episodes (MP3)
3. **Transcribes** them via [Scriberr](https://github.com/Scriberr) Whisper API
4. **Detects ad segments** with an LLM reading the SRT transcript
5. **Cuts out the ads** with FFmpeg `aselect` filter
6. **Generates a new Atom feed** with cleaned enclosures and preserved GUIDs
7. **Serves** audio + feed over HTTP

If any step of the sponsor-removal pipeline fails (Scriberr down, LLM error, ffmpeg crash), the original file is copied to the output directory unchanged and still included in the feed. The feed never breaks.

---

## Quick Start

### Prerequisites

- Python 3.11+
- `ffmpeg` and `ffprobe` on `$PATH`
- A Scriberr instance for transcription
- An OpenAI-compatible LLM endpoint for ad detection

### 1. Clone and install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e "."
```

### 2. Configure feeds

Edit `config/feeds.yaml`:

```yaml
feeds:
  - feed_url: "https://feed.skeptoid.com/"
    keep_article: 10
    podcast_slug: "skeptoid"
```

| Field | Meaning |
|------|---------|
| `feed_url` | Upstream RSS or Atom URL |
| `keep_article` | How many recent episodes to keep in the proxy feed |
| `podcast_slug` | Directory name on disk (alphanumeric + hyphens only) |

### 3. Set environment variables

Create `.env`:

```bash
# Scriberr transcription service
SCRIBERR_BASE_URL=http://localhost:8080
SCRIBERR_API_KEY=your_scriberr_api_key

# LLM provider (any OpenAI-compatible API)
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=your_openai_api_key
```

### 4. Tune settings

Edit `config/settings.yml`:

```yaml
scriberr_profile_name: "Audiobookself"   # optional Scriberr profile with WhisperX params
scriberr_check_interval: 30              # seconds between Scriberr status polls
llm_max_retry: 3                       # retries when LLM returns invalid JSON
llm_temperature: 0.0                   # deterministic LLM output
inference_model: "gpt-4o-mini"         # model name for the LLM endpoint
inference_reasoning_effort: ~         # null, or "low"/"medium"/"max"
```

### 5. Run

```bash
BASE_URL=http://localhost:3000 python3 src/main.py
```

The server:
- Runs an initial sync on startup (downloads + transcribes + processes)
- Serves feeds at `http://localhost:3000/{podcast_slug}/rss/full.atom`
- Serves audio at `http://localhost:3000/{podcast_slug}/media/{hash}.mp3`
- Re-syncs every hour via APScheduler

---

## Docker

```bash
docker-compose up --build -d
```

The compose file uses `network_mode: host` so the container can reach `localhost:8080` (Scriberr) and the host's LLM endpoint directly. This also means the server listens on host port `3000` directly.

```yaml
services:
  podcast-proxy:
    build: .
    container_name: podcast-proxy
    restart: unless-stopped
    network_mode: host
    env_file:
      - .env
    volumes:
      - ./config:/app/config
      - ./podcasts:/app/podcasts
```

Note: `./config` is **mounted at runtime**, not copied into the image. You can edit `config/feeds.yaml` without rebuilding.

---

## Directory Layout

```
podcast-proxy-sponsor-remover/
├── src/                        # application code
│   ├── main.py                 # entry point: load config, build clients, start server
│   ├── config.py               # Pydantic models + YAML loader for feeds.yaml
│   ├── paths.py                # FeedPaths dataclass: all path construction lives here
│   ├── fetcher.py              # HTTP: download RSS feeds + audio with retry
│   ├── scriberr_api.py         # Scriberr API: upload, start, poll, download SRT
│   ├── llm.py                  # LLM client: detect ad segments from SRT using langchain-openai
│   ├── ffmpeg_segments.py      # FFmpeg wrapper: remove segments via aselect filter
│   ├── processor.py            # AudioProcessor: orchestrates trans → LLM → ffmpeg with checkpoints
│   ├── utils.py                # SRT time ↔ seconds conversion helpers
│   ├── generator.py            # Build new Atom feed from upstream with python-feedgen
│   ├── sync.py                 # THE main loop per feed (download, process, generate)
│   ├── scheduler.py            # APScheduler: hourly intervals + initial sequential sync
│   └── web.py                  # Starlette static file server only
├── config/
│   ├── feeds.yaml              # which podcasts to proxy
│   ├── settings.yml            # tunables (model, intervals, retries)
│   └── user_prompt.txt         # LLM prompt template with {{SRT_CONTENT}} placeholder
├── podcasts/                   # runtime state (gitignored)
│   └── {slug}/
│       ├── old/
│       │   ├── media/          # original downloads
│       │   └── rss/
│       │       └── full.atom   # upstream feed snapshot
│       ├── new/
│       │   ├── media/          # processed (sponsor-free) audio
│       │   └── rss/
│       │       └── full.atom   # generated Atom feed
│       └── metadata/
│           ├── {hash}.srt      # transcript checkpoint
│           └── {hash}.segments.json  # LLM-detected ad segments checkpoint
├── tests/                      # every module has a unit test
│   ├── unit/                   # test_config, test_fetcher, test_generator, etc.
│   └── integration/            # test_sync, test_web
├── .env                        # secrets (API keys, URLs) — copy from .env.example
├── docker-compose.yml          # Docker runtime
├── Dockerfile                  # python:3.13-slim + ffmpeg
└── pyproject.toml
```

---

## The Sponsor-Removal Pipeline

For each episode, the flow is:

```
Upstream feed → Download original MP3 → old/media/{hash}.mp3
                                    ↓
                              Scriberr upload → Wait for transcription
                                    ↓
                              Download SRT → metadata/{hash}.srt
                                    ↓
                              LLM detect ad segments → metadata/{hash}.segments.json
                                    ↓
                         6 segments?   ──Yes──→ ffmpeg aselect cut → new/media/
                           |                     (removes ads, re-encodes to 128k)
                           └──No───→ copy original unchanged
                                    ↓
                              Generate Atom feed
```

**Checkpoint/resume:** if `.srt` already exists, skip Scriberr. If `.segments.json` exists, skip LLM. This makes restarts cheap.

**Fallback:** if any step fails, the original file is copied to `new/media/` and served as-is. The feed remains valid.

**FFmpeg approach:** Uses the `aselect` audio filter to exclude segments, then re-encodes with `libmp3lame -b:a 128k` and re-attaches cover art. This is slower than `-c copy` but produces frame-accurate cuts from arbitrary timestamps.

---

## Coding Guidelines

### YAGNI

- No admin/status page
- No database / ORM / Redis / queue — filesystem is the state
- No async — everything is synchronous (`subprocess`, `requests`, `feedparser`)
- No hot-reload — restart the process to reload config
- No structured logging — `logging.basicConfig` is enough
- No distributed workers — one process, one scheduler thread
- No retry abstraction — `requests` retry adapter for HTTP; log-and-continue for ffmpeg failures
- No plugin pipeline — one concrete `AudioProcessor.process()` function

### DRY

- **Path construction lives in exactly one place:** `FeedPaths` in `paths.py`. Every other module imports it.
- **Filename derivation** (from URL/GUID hash) lives in one helper in `sync.py`.
- If you copy-paste entry-to-feed mapping logic, extract a function.

### Test As You Go

- Write unit tests **immediately after** finishing each module, before starting the next.
- When integration tests find bugs, reproduce them in a unit test first, then fix.
- **Without tests, the module is not done.**

---

## Critical Invariants

These are the most important behaviors to preserve:

1. **GUID preservation** — generated feed MUST use the exact same `entry.id` as the upstream. Podcast clients use this to avoid re-downloads.
2. **Atomic writes** — always write to `.tmp`, then `os.replace()` to the target.
3. **Idempotency** — if `old/media/` file exists with size > 0, skip download. If `new/media/` exists with size > 0, skip ffmpeg.
4. **Partial resilience** — if one entry's pipeline fails, copy the original, log a WARNING, and continue with the rest.
5. **Entry order** — preserve upstream order exactly. Do not sort by processing completion time.
6. **Cleanup** — media and metadata files for entries that fall outside `keep_article` are automatically removed.

---

## Running Tests

```bash
# all tests
pytest tests/ -v

# specific module
pytest tests/unit/test_generator.py -v

# integration tests (no real HTTP calls, fully mocked)
pytest tests/integration/ -v
```

---
## Note
Vibecoded for personal use

## License

[See LICENSE file]
