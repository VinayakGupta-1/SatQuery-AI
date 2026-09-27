"""Connected-region labelling on a class raster.

A region is a maximal set of pixels that share one class and touch each other.
Labelling works on horizontal *runs* -- stretches of one class within a row --
rather than on pixels: runs are found per row, runs in consecutive rows that
touch and share a class are merged with union-find, and each merged set is one
region. The cost grows with the number of runs, not the number of pixels, which
keeps a full Sentinel-2 tile tractable without SciPy.

Connectivity is explicit. With 8-connectivity, pixels that touch only at a
corner belong to one region; with 4-connectivity they do not. Neither is more
correct -- a river one pixel wide running diagonally is one object under the
first and many under the second -- so the choice is a parameter and is
reported with the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from app.tools.raster.backends import has_numpy


@dataclass
class Run:
    """One horizontal stretch of a single class: columns ``[start, end)``."""

    row: int
    start: int
    end: int
    group: int


@dataclass
class Region:
    """Size, extent and centroid of one connected region, in pixel space."""

    group: int
    pixels: int
    row_min: int
    row_max: int
    col_min: int
    col_max: int
    row_sum: float
    col_sum: float

    @property
    def centroid(self) -> tuple[float, float]:
        """``(column, row)`` of the region's centre of mass, in pixel units."""
        return self.col_sum / self.pixels, self.row_sum / self.pixels


def find_runs(groups: Any, width: int, height: int, targets: set[int]) -> list[Run]:
    """Return the runs of every target class, ordered by row then column."""
    runs: list[Run] = []
    if has_numpy():
        import numpy

        grid = numpy.asarray(groups).reshape(height, width)
        wanted = numpy.asarray(sorted(targets))
        for row in range(height):
            values = grid[row]
            change = numpy.flatnonzero(values[1:] != values[:-1]) + 1
            starts = numpy.concatenate(([0], change))
            ends = numpy.concatenate((change, [width]))
            classes = values[starts]
            keep = numpy.isin(classes, wanted)
            for start, end, group in zip(starts[keep], ends[keep], classes[keep]):
                runs.append(Run(row, int(start), int(end), int(group)))
        return runs

    for row in range(height):
        offset = row * width
        col = 0
        while col < width:
            group = int(groups[offset + col])
            start = col
            while col < width and int(groups[offset + col]) == group:
                col += 1
            if group in targets:
                runs.append(Run(row, start, col, group))
    return runs


def label_regions(
    runs: Sequence[Run], height: int, connectivity: int = 8
) -> tuple[list[Region], list[int]]:
    """Merge touching runs of one class into regions.

    Returns the regions and, for each run, the index of the region it belongs
    to, so a caller can paint regions back onto a grid without relabelling.
    """
    if connectivity not in (4, 8):
        raise ValueError("connectivity must be 4 or 8")

    parent = list(range(len(runs)))

    def find(index: int) -> int:
        root = index
        while parent[root] != root:
            root = parent[root]
        while parent[index] != root:
            parent[index], index = root, parent[index]
        return root

    def union(a: int, b: int) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[max(root_a, root_b)] = min(root_a, root_b)

    # Index of the first run of every row, so each row is compared only with
    # the one above it.
    first = [0] * (height + 1)
    for run in runs:
        first[run.row + 1] += 1
    for row in range(height):
        first[row + 1] += first[row]

    # Two runs touch when their column ranges overlap (4-connectivity) or
    # overlap or meet at a corner (8-connectivity).
    reach = 0 if connectivity == 8 else 1
    for row in range(1, height):
        above_start, above_end = first[row - 1], first[row]
        scan = above_start
        for current in range(first[row], first[row + 1]):
            run = runs[current]
            while scan < above_end and runs[scan].end < run.start + reach:
                scan += 1
            candidate = scan
            while candidate < above_end and runs[candidate].start <= run.end - reach:
                if runs[candidate].group == run.group:
                    union(candidate, current)
                candidate += 1

    regions: list[Region] = []
    index_of_root: dict[int, int] = {}
    membership: list[int] = []
    for position, run in enumerate(runs):
        root = find(position)
        slot = index_of_root.get(root)
        length = run.end - run.start
        if slot is None:
            slot = len(regions)
            index_of_root[root] = slot
            regions.append(
                Region(
                    group=run.group, pixels=0,
                    row_min=run.row, row_max=run.row,
                    col_min=run.start, col_max=run.end - 1,
                    row_sum=0.0, col_sum=0.0,
                )
            )
        region = regions[slot]
        region.pixels += length
        region.row_min = min(region.row_min, run.row)
        region.row_max = max(region.row_max, run.row)
        region.col_min = min(region.col_min, run.start)
        region.col_max = max(region.col_max, run.end - 1)
        region.row_sum += run.row * length
        # Sum of the column indices start .. end-1.
        region.col_sum += (run.start + run.end - 1) * length / 2.0
        membership.append(slot)

    return regions, membership


__all__ = ["Region", "Run", "find_runs", "label_regions"]
