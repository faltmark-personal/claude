# Runna → YouTube Music workout playlists

A local web app that turns a running workout (warm-up, intervals, recoveries,
cool-down, each with a heart-rate zone) into a YouTube Music playlist whose
**tempo follows the workout's intensity**. It prefers songs you've liked, fills
gaps with songs by artists you like or similar artists, and saves the playlist to
your account. You then download it to your Garmin watch (built for a Fenix 8 Pro) through Garmin's
YouTube Music watch app.

```
Workout ──► zones ──► BPM ranges ──► pick songs (liked first) ──► preview & edit ──► save to YouTube Music ──► download on watch
```

## Quick start (no terminal needed)

1. Install **Python 3.10+** from [python.org](https://www.python.org/downloads/)
   (on Windows, tick "Add python.exe to PATH").
2. Download this folder (GitHub → Code → Download ZIP) and unzip it.
3. Double-click the launcher:
   - **Mac:** `Start Runna Playlist.command`. The first time, macOS may block it:
     right-click → Open → Open.
   - **Windows:** `Start Runna Playlist.bat`
4. The first launch takes about a minute to install. Then your browser opens the app at
   http://localhost:8765. Keep the small window open while you use it, and close it to stop.

Everything else (entering workouts, connecting YouTube, previewing, editing, saving)
happens in the browser. The app starts with a **demo library** of made-up songs, so you can
try it before connecting anything. Settings, caches and tokens stay on your
computer in `~/.runna-playlist`, and the app only listens to your own machine (127.0.0.1).

<details><summary>Terminal alternative</summary>

```bash
cd runna-playlist
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[ytmusic]'
runna-playlist            # opens http://localhost:8765
```
</details>

## What's official and what isn't

| Piece | How this app uses it | Status |
|---|---|---|
| **Runna** | No export or API exists. Enter workouts by hand (quick-entry text or the step editor). | – |
| **Intervals.icu** | Lists your planned runs and imports them with your *personal API key*. | Official API |
| **FIT workout files** | Upload a structured workout `.fit` (Garmin Connect, TrainingPeaks, Intervals.icu…). | Garmin's open format, read with Garmin's FIT SDK |
| **YouTube Data API v3** | Default account mode: reads your liked music, creates/refills the playlist. | Official. Needs a free Google Cloud OAuth client. Quota-limited |
| **ytmusicapi** | Optional mode: reads YouTube Music likes directly, adds song radio, no quota. | **Unofficial.** Imitates the YouTube Music website using your browser session. May break at any time and may not be allowed by YouTube's terms |
| **Deezer API** | Song BPM lookups and "similar artists". | Official public API, no key |
| **GetSongBPM** | Optional extra BPM source (`GETSONGBPM_API_KEY`). | Official API, free key |
| **Garmin watch** | Not controlled by this app. You download the playlist in the YouTube Music watch app. | Official Garmin/Google app |

Other platforms: TrainingPeaks' API is for approved commercial partners only,
and Garmin Connect and Nike Run Club have no personal API. **Intervals.icu** is the
practical "plan app with a personal API": its calendar can hold your plan, and it
can also push workouts to Garmin.

## Setting up an account

**Official mode (YouTube Data API)**
1. In [Google Cloud Console](https://console.cloud.google.com/), create a project
   and enable **YouTube Data API v3**.
2. Configure the OAuth consent screen (External; add your own Google account as a test user).
3. Create an **OAuth client ID → Web application** with redirect URI
   `http://localhost:8765/api/auth/google/callback`. Download the JSON.
4. In the app: Settings → upload the JSON → **Connect Google account** → Library → **Sync**.

Your liked songs come from YouTube's "Liked videos" list, filtered to the Music category.
Likes made in YouTube Music normally show up there. The default quota is
10,000 units/day. A 15-song playlist costs ~800 units, plus 100 for each
recommended song that has to be found on YouTube.

**ytmusicapi mode (unofficial, optional)**
1. `pip install -e '.[ytmusic]'`
2. Open music.youtube.com while signed in. In developer tools → Network, find a request to `browse` and copy its
   *request headers* (they include your cookie).
3. Settings → paste the headers → **Save & use ytmusicapi** → Library → **Sync**.
   The headers act like a password. They're stored only in your data folder (`ytmusic_browser.json`, mode 600).

**Intervals.icu (optional)**: intervals.icu → Settings → Developer Settings → API key → paste it in Settings here.

## Tempo per zone

Music BPM is *not* matched to heart rate. Each zone gets a tempo range that
matches the effort, and the hard zones are centred on your running cadence. At **163 steps/min**:

| Zone | Effort | Default range | Why |
|---|---|---|---|
| Z1 | Recovery / warm-up / cool-down | 98–121 BPM | relaxed |
| Z2 | Easy aerobic | 121–140 | upbeat, not pushy |
| Z3 | Tempo / steady | 140–158 | driving |
| Z4 | Threshold | 158–170 | on your footstrike |
| Z5 | VO2 max | 170–183 | slightly ahead of your feet |

With **half/double time** on (default), an 82 BPM song counts as 164 (Z4).
Everything is editable in Settings, and "Set ranges from cadence" recalculates
the ranges if your cadence changes. The music follows the workout up *and* down. Recoveries and
cool-downs get calmer music.

## Where BPM comes from (and how reliable it is)

Neither YouTube API provides tempo, so the app tries these in order:
1. **Your own entries** (Library tab: type a BPM in). These always win.
2. **Cache** of earlier lookups (unknown results are retried after 30 days).
3. **Deezer**: matched by artist, title and length. Good for mainstream music. Many
   tracks have no BPM, and remixes or live versions can mismatch.
4. **GetSongBPM**: if `GETSONGBPM_API_KEY` is set.
5. **Preview analysis** (optional, `pip install -e '.[analysis]'` and enable in
   Settings): beat-tracks Deezer's 30-second preview with librosa. Fills gaps, but tempos are estimates.

Published tempos are often off by ×2 or ×½. Half/double matching absorbs most
of that. **Songs with unknown BPM are never placed by tempo.** The Library tab
shows coverage per zone and lets you filter to unknown songs and fill them in.
Note that your first sync looks up every liked song (~0.25 s each); later syncs use the cache.

## How songs are chosen

1. Your liked songs whose tempo fits the zone. Among those, songs nearer the middle of the range rank higher,
   with some variety and no same-artist back-to-back.
2. If a zone runs short: other popular songs by artists you like, then songs by
   **similar artists** (Deezer), then **song radio** from your likes (ytmusicapi mode only).
   Recommendations are cached and only used when liked songs can't fill the time.
3. If still nothing fits, the closest-tempo song is used and flagged ⚠ in the preview.
4. No song appears twice.

## Timing: whole songs vs. exact intervals

The watch plays each song to the end. It doesn't trim songs, crossfade or switch at set
times, so music changes can't land exactly on interval boundaries. The planner:

- plans against the **workout clock** (each segment ends at a fixed time from the
  start), so errors don't add up over the run;
- near the end of each segment, picks the 1–3 songs whose combined length lands closest to
  the boundary (a liked song is still preferred unless it's about a minute worse);
- **groups steps shorter than 2:30** (configurable): runs of short intervals
  (e.g. 8 × 1 min / 1 min) share one tempo (time-weighted, or "hardest zone"),
  and a lone short recovery is folded into the rep before it;
- shows, for every segment, how early or late its music starts (the Timing table), plus total length vs. workout.

Typical result: music changes within about ±30 s of the boundary and total length within
a minute. It can be worse when few songs fit a zone. Distance-based steps are converted to
time at the planned pace, so running faster or slower shifts things.

## Preview and edit

Each song shows its start time, length, BPM (and source), assigned segment/zone, and whether
it's **♥ liked** or a **recommendation** (with the reason). You can:
- **⇄ replace** a song: suggestions that fit the zone, with how the length differs, or search your songs
- **🔒 lock** songs, then **Regenerate** for new picks around them
- move songs up or down (or drag them), remove them, add songs
- change BPM ranges in Settings and regenerate
- **Export CSV**: one YouTube Music link per song. This is the fallback if saving isn't available:
  build the playlist by hand in the app.

## Getting it onto the Fenix 8 Pro

Saving creates the playlist in your YouTube Music account. Downloading it is a separate step on the watch:
1. Install **YouTube Music** from the Connect IQ Store and sign in on the watch (personal account; Brand
   Accounts aren't supported; needs YouTube Music/YouTube Premium).
2. Keep **"Refill the same playlist"** on, so the playlist keeps its name and ID and you only select it on the watch once.
3. On the watch, choose the playlist in the YouTube Music app and sync on **Wi-Fi**.
4. Before the run: pair headphones, **turn shuffle off**, and start the music and the workout together.
   If you pause one, pause the other.

Check the order on the watch the first time. If it reorders playlists, the CSV/table order is still the plan.

## Limits / not in scope

- No live adaptation to heart rate. The playlist is prepared before the run.
- No direct control of the watch, and no song trimming or crossfades.
- No Runna import. Runna has no API or export.
- ytmusicapi mode is unofficial and can stop working without notice.

## Development

```bash
pip install -e '.[dev]'
pytest -q
```

Layout: `workout.py` (text/YAML entry), `fit_import.py`, `intervals_icu.py`,
`zones.py`, `bpm.py`, `recommend.py`, `planner.py`, `sources/` (`youtube_data`,
`ytmusic`, `demo`), `service.py` (app state), `app.py` (FastAPI), `static/` (UI).
Tests use the demo library and stand-in clients, so they never hit the network.
