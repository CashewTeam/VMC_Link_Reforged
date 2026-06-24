import json
import os

from ..core import constants
from . import mapper as mapping


_PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))

_preset_items_cache = {
    constants.MAPPING_KIND_BONE: [],
    constants.MAPPING_KIND_VMC_BLEND: [],
    constants.MAPPING_KIND_ARKIT_BLEND: [],
}


def mapping_preset_dir(kind: str) -> str:
    try:
        subdir = constants.MAPPING_PRESET_SUBDIRS[kind]
    except KeyError as exc:
        raise KeyError(f"未知映射类型：{kind}") from exc
    return os.path.join(_PROJECT_ROOT, "presets", subdir)


def ensure_mapping_preset_dir(kind: str) -> str:
    path = mapping_preset_dir(kind)
    os.makedirs(path, exist_ok=True)
    return path


def mapping_preset_prop_names(kind: str):
    try:
        return constants.MAPPING_PRESET_PROP_NAMES[kind]
    except KeyError as exc:
        raise KeyError(f"未知映射类型：{kind}") from exc


def get_mapping_preset_selection(scene, kind: str) -> str:
    preset_prop, _ = mapping_preset_prop_names(kind)
    return str(getattr(scene, preset_prop, constants.PRESET_NONE_ID))


def set_mapping_preset_selection(scene, kind: str, value: str):
    preset_prop, _ = mapping_preset_prop_names(kind)
    setattr(scene, preset_prop, value)


def get_mapping_preset_save_name(scene, kind: str) -> str:
    _, save_prop = mapping_preset_prop_names(kind)
    return str(getattr(scene, save_prop, ""))


def scan_mapping_presets(kind: str):
    preset_dir = ensure_mapping_preset_dir(kind)
    items = [(constants.PRESET_NONE_ID, "无", f"未选择{mapping.mapping_kind_label(kind)}预设")]
    names = sorted(
        file_name
        for file_name in os.listdir(preset_dir)
        if file_name.lower().endswith(".json") and os.path.isfile(os.path.join(preset_dir, file_name))
    )
    for file_name in names:
        label = os.path.splitext(file_name)[0]
        items.append((file_name, label, f"加载{mapping.mapping_kind_label(kind)}预设“{label}”"))
    _preset_items_cache[kind] = items
    return items


def enum_mapping_preset_items(kind: str):
    items = _preset_items_cache.get(kind) or []
    if not items:
        items = scan_mapping_presets(kind)
    return items


def enum_bone_map_preset_items(_self, _context):
    return enum_mapping_preset_items(constants.MAPPING_KIND_BONE)


def enum_vmc_blend_preset_items(_self, _context):
    return enum_mapping_preset_items(constants.MAPPING_KIND_VMC_BLEND)


def enum_arkit_blend_preset_items(_self, _context):
    return enum_mapping_preset_items(constants.MAPPING_KIND_ARKIT_BLEND)


def refresh_all_mapping_preset_caches():
    for kind in constants.MAPPING_KIND_LABELS:
        scan_mapping_presets(kind)


def sanitize_mapping_preset_filename(name: str) -> str:
    safe = str(name).strip().replace("/", "_").replace("\\", "_")
    if not safe:
        return ""
    if not safe.lower().endswith(".json"):
        safe += ".json"
    return safe


def mapping_preset_payload(scene, kind: str):
    return {
        "version": constants.PRESET_SCHEMA_VERSION,
        "mapping_kind": kind,
        "entries": mapping.collect_mapping_entries(scene, kind),
    }


def load_mapping_preset_payload(payload, kind: str):
    if not isinstance(payload, dict):
        raise RuntimeError("预设 JSON 必须是对象")
    if payload.get("version") != constants.PRESET_SCHEMA_VERSION:
        raise RuntimeError(f"不支持的预设版本：{payload.get('version')}")
    if payload.get("mapping_kind") != kind:
        raise RuntimeError(f"预设类型不匹配：期望 {mapping.mapping_kind_label(kind)}")
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        raise RuntimeError("预设 JSON 的 entries 字段必须是对象")
    return entries


def save_mapping_preset(scene, kind: str):
    file_name = sanitize_mapping_preset_filename(get_mapping_preset_save_name(scene, kind))
    if not file_name:
        raise RuntimeError("保存名称不能为空")

    preset_dir = ensure_mapping_preset_dir(kind)
    path = os.path.join(preset_dir, file_name)
    payload = mapping_preset_payload(scene, kind)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    scan_mapping_presets(kind)
    set_mapping_preset_selection(scene, kind, file_name)
    return file_name


def load_mapping_preset(scene, kind: str):
    file_name = get_mapping_preset_selection(scene, kind)
    if file_name == constants.PRESET_NONE_ID:
        raise RuntimeError("请先选择要加载的预设")

    path = os.path.join(ensure_mapping_preset_dir(kind), file_name)
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    entries = load_mapping_preset_payload(payload, kind)
    mapping.apply_mapping_entries(scene, kind, entries)

    if kind == constants.MAPPING_KIND_BONE:
        mapping.invalidate_bone_map_cache()
    else:
        mapping.invalidate_blend_map_cache()
    mapping.rebuild_maps(scene)
    return file_name


def refresh_mapping_presets(scene, kind: str):
    items = scan_mapping_presets(kind)
    current = get_mapping_preset_selection(scene, kind)
    valid_ids = {item[0] for item in items}
    if current not in valid_ids:
        set_mapping_preset_selection(scene, kind, constants.PRESET_NONE_ID)
