# Repository Guidelines

## Project Structure & Module Organization
This repository is a Blender add-on for VMC-based motion and face driving. Core entry points live in `__init__.py` and `blender_manifest.toml`.

- `core/`: shared constants, bootstrap, and low-level helpers
- `runtime/`: receiver, driver, recording, and target runtime logic
- `mapping/`: VRM, ARP, MMD, and generic target mapping modules
- `preview/`: intermediate preview rig and face preview behavior
- `ui/`: Blender panels and operators
- `presets/`: JSON presets for bone maps and blendshape maps
- `assets/`: bundled debug/preview assets
- `docs/`: development plans, fix history, and design notes

Avoid editing `RhyLiveSDK_Unity-main/` unless the task explicitly targets that vendor snapshot.

## Build, Test, and Development Commands
Use lightweight static checks before handing work off:

```bash
python3 -m py_compile __init__.py core/*.py runtime/*.py mapping/*.py preview/*.py ui/*.py
git diff --check
python3 -m json.tool presets/bone_maps/arp_fk_humanoid.json
```

- `py_compile`: catches import and syntax errors across the add-on
- `git diff --check`: catches whitespace and patch formatting issues
- `json.tool`: validates edited preset JSON files

Runtime validation is done in Blender by reloading the add-on and testing preview, mapping, and recording flows against real target rigs.

## Coding Style & Naming Conventions
Use Python with 4-space indentation and ASCII by default. Keep module boundaries intact instead of collapsing logic into `__init__.py`.

- User-facing UI text should stay in Chinese
- Internal identifiers stay stable: `bl_idname`, property keys, module names
- Prefer explicit names such as `target_runtime`, `mapping/mmd.py`, `preview/*`
- Use `apply_patch` for manual edits and `rg` for searches

Do not add broad fallback behavior that hides real rig or mapping bugs.

## Testing Guidelines
There is no separate automated test suite yet. Every change should include:

- static compile validation
- JSON validation when presets change
- targeted Blender manual verification for the affected path (`VRM`, `ARP`, or `MMD`)

When touching preview or recording, ensure both still use the same correction chain.

## Commit & Pull Request Guidelines
Recent history favors short, imperative commit subjects, often in Chinese, for example: `修正小臂旋转` or `Document target preview and recording consistency`.

- Keep commits scoped to one feature or one bugfix
- Mention affected rig path in the description when relevant: `VRM`, `ARP`, `MMD`, `录制`
- Include screenshots or pose comparisons for UI, preview, or mapping changes
- Note manual Blender verification steps and any preset files updated

## Versioning
Follow `0.Y.Z` during active development:

- new feature: `Y + 1`
- bug fix: `Z + 1`
- breaking change: bump `X`, but keep major `0` before first stable release
