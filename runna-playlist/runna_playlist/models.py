from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Track:
    title: str
    artists: list[str]
    duration_s: int
    video_id: str | None = None  # YouTube video id; None until resolved for recommendations
    deezer_id: int | None = None
    liked: bool = False
    bpm: float | None = None
    bpm_source: str | None = None
    # Why this track is a candidate: "liked", "liked-artist", "similar-artist", "radio".
    origin: str = "liked"
    reason: str = ""  # human-readable, e.g. "Similar to Daft Punk"

    @property
    def key(self) -> str:
        if self.video_id:
            return self.video_id
        if self.deezer_id:
            return f"dz:{self.deezer_id}"
        return f"x:{self.artist.lower()}|{self.title.lower()}"

    @property
    def artist(self) -> str:
        return ", ".join(self.artists) if self.artists else "Unknown"

    @property
    def label(self) -> str:
        return f"{self.artist} – {self.title}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["key"] = self.key
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Track":
        fields = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in fields})


@dataclass
class Segment:
    name: str
    duration_s: int
    zone: int
    kind: str = "work"  # warmup | work | recovery | cooldown
    note: str = ""  # e.g. "zone guessed from step type" for imported workouts

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Workout:
    name: str
    segments: list[Segment]
    description: str = ""

    @property
    def duration_s(self) -> int:
        return sum(s.duration_s for s in self.segments)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "duration_s": self.duration_s,
            "segments": [s.to_dict() for s in self.segments],
        }


@dataclass
class Block:
    """A stretch of the workout that gets one tempo target.

    Usually one segment. Runs of intervals too short to hold a song are merged
    into one block (see planner.build_blocks).
    """

    name: str
    start_s: int
    end_s: int
    zone: int
    segment_indexes: list[int] = field(default_factory=list)
    merged: bool = False

    @property
    def duration_s(self) -> int:
        return self.end_s - self.start_s

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["duration_s"] = self.duration_s
        return d
