"""Build finetune_rsvqa.ipynb from finetune_rsvqa.py.

The script is the source: it can be run, diffed and tested like any Python
file. Its ``# %%`` markers become notebook cells, and ``# %% [markdown]``
cells become markdown with the leading ``# `` removed::

    python finetune/build_notebook.py
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "finetune_rsvqa.py")
TARGET = os.path.join(HERE, "finetune_rsvqa.ipynb")


def cells_from(text: str) -> list[dict]:
    cells: list[dict] = []
    kind, lines = None, []

    def flush() -> None:
        body = "\n".join(lines).strip("\n")
        if kind is not None and body:
            if kind == "markdown":
                body = "\n".join(line[2:] if line.startswith("# ") else line.lstrip("#") for line in body.split("\n"))
            source = [line + "\n" for line in body.split("\n")]
            source[-1] = source[-1].rstrip("\n")
            cell = {"cell_type": kind, "id": f"cell-{len(cells)}", "metadata": {}, "source": source}
            if kind == "code":
                cell.update(execution_count=None, outputs=[])
            cells.append(cell)

    for line in text.split("\n"):
        if line.startswith("# %%"):
            flush()
            kind, lines = ("markdown" if "[markdown]" in line else "code"), []
        else:
            lines.append(line)
    flush()
    return cells


def main() -> None:
    with open(SOURCE, encoding="utf-8") as handle:
        cells = cells_from(handle.read())
    notebook = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    with open(TARGET, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(notebook, handle, indent=1, ensure_ascii=False)
        handle.write("\n")
    print(f"{TARGET}: {len(cells)} cells")


if __name__ == "__main__":
    main()
