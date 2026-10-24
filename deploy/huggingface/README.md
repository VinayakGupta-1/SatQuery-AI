---
title: SatQuery AI
emoji: 🛰️
colorFrom: indigo
colorTo: green
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Ask questions about satellite imagery in plain language
---

# SatQuery AI

Ask a question about a place, such as *"How healthy is the vegetation around
Pune?"*, *"Find areas affected by flooding in Kochi in August 2024"* or
*"How much forest was lost near Hosur between 2019 and 2025?"*. SatQuery finds
the Sentinel-2 or Sentinel-1 imagery itself, decides which analysis answers the
question, checks that the imagery can support it, and returns an answer with a
map, findings, a confidence breakdown and an execution trace. You can also
upload your own GeoTIFFs.

Principle: **the model proposes, deterministic code decides.**

- Source code: https://github.com/VinayakGupta-1/SatQuery-AI
- API documentation: `/docs` on this Space's URL

This demo runs without sign-in. Results are kept in memory and disappear when
the Space restarts or goes to sleep after a period without visitors; the first
visit after that takes a minute while it wakes up.
