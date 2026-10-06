"""The face bank: one JSON file that remembers every player's genome (like OOTP's faces.dat).

Keeping genomes means a player's face never changes between runs; only age, build and team are re-applied.
The bank also records which image files SimFace wrote, so it never overwrites pictures it didn't make
(such as a photo pack) unless told to.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .genome import Genome

FORMAT = "simface-bank"
VERSION = 1


class FaceBank:
    def __init__(self, path: str | Path, seed: str = "simface"):
        self.path = Path(path)
        self.data = {"format": FORMAT, "version": VERSION, "seed": seed, "players": {}}
        if self.path.exists():
            loaded = json.loads(self.path.read_text())
            if loaded.get("format") != FORMAT:
                raise ValueError(f"{self.path} is not a SimFace face bank")
            self.data.update(loaded)

    @property
    def seed(self) -> str:
        return self.data["seed"]

    def genome(self, pid: str) -> Genome | None:
        entry = self.data["players"].get(str(pid))
        return Genome.from_dict(entry["genome"]) if entry else None

    def put(self, pid: str, genome: Genome, name: str = "") -> None:
        entry = self.data["players"].setdefault(str(pid), {})
        entry["genome"] = genome.to_dict()
        if name:
            entry["name"] = name

    def mark_written(self, pid: str, filename: str, source: str) -> None:
        entry = self.data["players"].setdefault(str(pid), {})
        entry["file"] = filename
        entry["source"] = source

    def owned_files(self) -> set[str]:
        """Every file name SimFace has written into this folder."""
        return {e["file"] for e in self.data["players"].values() if e.get("file")}

    def __len__(self) -> int:
        return len(self.data["players"])

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".bank-", suffix=".json")
        with os.fdopen(fd, "w") as fh:
            json.dump(self.data, fh, indent=1, sort_keys=True)
        os.replace(tmp, self.path)
