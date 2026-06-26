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

## Blender MCP Bone Sampling
Use Blender MCP for pose debugging before changing mapping math. Keep reads non-destructive.

- Resolve the loaded add-on package from `sys.modules`; in Blender extensions it is commonly `bl_ext.user_default.vmc_link`, not plain `vmc_link`.
- For single-frame checks, read `scene.vmc_link_preview_armature`, `scene.vmc_link_armature`, and the relevant mapping module, then inspect `pose.bones`.
- For live receiver sampling, do not call `time.sleep()` in Blender code because it blocks the main thread and can freeze incoming data. Register a `bpy.app.timers` callback and sample every `0.05-0.1s` for `1-2s`.
- Store temporary samples in `bpy.app.driver_namespace`, for example `vmc_link_limb_sample_state`, then run a second MCP call to summarize them.
- Compare preview and target bones by world axes, not only quaternion numbers: `obj.matrix_world @ pose_bone.matrix`, then inspect normalized `X/Y/Z` axes, head, tail, and local rotation.
- For MMD/ARP issues, record the active target type, runtime strategy, root-motion target, user config, and actual runtime map before interpreting pose data.

Minimal sampling pattern:

```python
import bpy, time
state = {"start": time.perf_counter(), "samples": [], "done": False}
bpy.app.driver_namespace["vmc_link_sample_state"] = state

def tick():
    scene = bpy.context.scene
    preview = scene.vmc_link_preview_armature
    target = scene.vmc_link_armature
    bpy.context.view_layer.update()
    state["samples"].append({
        "t": time.perf_counter() - state["start"],
        "preview": preview.name if preview else "",
        "target": target.name if target else "",
    })
    if time.perf_counter() - state["start"] >= 2.0:
        state["done"] = True
        return None
    return 0.1

bpy.app.timers.register(tick, first_interval=0.0)
```

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
