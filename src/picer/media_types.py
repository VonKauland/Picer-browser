"""Public immutable media playback snapshot."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AnimationState:
    active: bool = False
    playing: bool = False
    frame: int = 0
    count: int = 0
    duration: int = 0
