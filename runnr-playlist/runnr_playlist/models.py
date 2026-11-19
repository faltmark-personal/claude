from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Track:
    video_id: str
    title: str
    artists: list[str]
    duration_s: int
    liked: bool = False
    artist_ids: list[str] = field(default_factory=list)
    bpm: float | None = None
    bpm_source: str | None = None
    # How this track got into the pool, e.g. "liked", "radio:<seed>", "artist:<name>".
    origin: str = "liked"

    @property
    def artist(self) -> str:
        return ", ".join(self.artists) if self.artists else "Unknown"

    @property
    def label(self) -> str:
        return f"{self.artist} – {self.title}"


@dataclass
class Segment:
    name: str
    duration_s: int
    zone: int


@dataclass
class Workout:
    name: str
    segments: list[Segment]
    description: str = ""

    @property
    def duration_s(self) -> int:
        return sum(s.duration_s for s in self.segments)


@dataclass
class PlannedTrack:
    track: Track
    start_s: int
    zone: int
    segment: str
    effective_bpm: float  # the bpm after half/double-time adjustment

    @property
    def end_s(self) -> int:
        return self.start_s + self.track.duration_s
