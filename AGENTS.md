# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- Profile visuals in `assets/` and the interactive `docs/reactor.html` follow the generation rules in `docs/profile-assets.md`. For profile data, motion, or interaction changes, read `docs/profile-assets.md` and run `python3 -m unittest discover -s tests -v`.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
