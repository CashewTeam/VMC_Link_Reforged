from ..core import constants
from . import arp as mapping_arp
from . import mapper as mapping
from . import mmd as mapping_mmd
from . import vrm as mapping_vrm


TARGET_RIG_GENERIC = "generic"
TARGET_RIG_ARP = "arp"
TARGET_RIG_MMD = "mmd"

RUNTIME_STRATEGY_GENERIC = "generic"
RUNTIME_STRATEGY_ARP = "arp"
RUNTIME_STRATEGY_MMD = "mmd"

SUPPORTED_TARGET_RIGS = (
    TARGET_RIG_GENERIC,
    TARGET_RIG_ARP,
    TARGET_RIG_MMD,
)

SUPPORTED_RUNTIME_STRATEGIES = (
    RUNTIME_STRATEGY_GENERIC,
    RUNTIME_STRATEGY_ARP,
    RUNTIME_STRATEGY_MMD,
)


class TargetRigAdapter:
    __slots__ = (
        "rig_id",
        "label",
        "builtin_preset_file",
        "runtime_strategy",
        "_analyze_armature",
        "_is_detected",
        "_apply_standard_scene_mapping",
        "_clear_scene_report",
        "_build_runtime_mapping",
        "_build_calibration_mapping",
        "_prepare_receiver_session",
    )

    def __init__(
        self,
        rig_id: str,
        label: str,
        builtin_preset_file: str,
        runtime_strategy: str,
        analyze_armature,
        is_detected,
        apply_standard_scene_mapping,
        clear_scene_report,
        build_runtime_mapping,
        build_calibration_mapping,
        prepare_receiver_session,
    ):
        self.rig_id = rig_id
        self.label = label
        self.builtin_preset_file = builtin_preset_file
        self.runtime_strategy = runtime_strategy
        self._analyze_armature = analyze_armature
        self._is_detected = is_detected
        self._apply_standard_scene_mapping = apply_standard_scene_mapping
        self._clear_scene_report = clear_scene_report
        self._build_runtime_mapping = build_runtime_mapping
        self._build_calibration_mapping = build_calibration_mapping
        self._prepare_receiver_session = prepare_receiver_session

    def analyze_armature(self, arm_obj):
        return self._analyze_armature(arm_obj)

    def is_detected(self, analysis: dict) -> bool:
        return bool(self._is_detected(analysis or {}))

    def apply_standard_scene_mapping(self, scene):
        return self._apply_standard_scene_mapping(scene)

    def clear_scene_report(self, scene):
        self._clear_scene_report(scene)

    def build_runtime_mapping(self, scene, arm_obj):
        return self._build_runtime_mapping(scene, arm_obj)

    def build_calibration_mapping(self, scene, arm_obj):
        return self._build_calibration_mapping(scene, arm_obj)

    def prepare_receiver_session(self, scene):
        return self._prepare_receiver_session(scene)


GENERIC_CALIBRATION_REQUIRED_SOURCES = (
    "LeftUpperArm",
    "RightUpperArm",
    "LeftUpperLeg",
    "RightUpperLeg",
)


def _generic_resolved_targets(arm_obj, scene=None):
    analysis = mapping_vrm.analyze_armature(arm_obj)
    resolved_targets = dict(analysis.get("resolved_default_targets", {}))
    if not scene:
        return resolved_targets

    for source_name in (*constants.INTERMEDIATE_REQUIRED_BONES, *constants.INTERMEDIATE_OPTIONAL_BONES):
        actual_name = mapping.find_bone_name(arm_obj, source_name, scene)
        if actual_name:
            resolved_targets[source_name] = actual_name
    return resolved_targets


def _generic_analyze_armature(arm_obj):
    analysis = mapping_vrm.analyze_armature(arm_obj)
    resolved_targets = dict(analysis.get("resolved_default_targets", {}))
    calibration_missing = [
        source_name
        for source_name in GENERIC_CALIBRATION_REQUIRED_SOURCES
        if source_name not in resolved_targets
    ]
    analysis["is_generic"] = bool(analysis.get("is_target_valid"))
    analysis["calibration_required_missing"] = calibration_missing
    analysis["calibration_supported"] = bool(analysis.get("is_target_valid")) and not calibration_missing
    return analysis


def _generic_is_detected(analysis: dict) -> bool:
    return bool(analysis.get("is_vrm"))


def _generic_apply_standard_scene_mapping(scene):
    arm_obj = getattr(scene, "vmc_link_armature", None)
    if not mapping.has_pose_bones(arm_obj):
        raise RuntimeError("请先绑定目标骨架")
    filled = mapping.autofill_empty_manual_overrides(scene, arm_obj)
    mapping.invalidate_bone_map_cache()
    return {
        "filled": int(filled),
        "target_name": getattr(arm_obj, "name", ""),
    }


def _noop_clear_scene_report(_scene):
    return


def _empty_runtime_mapping(_scene, _arm_obj):
    return {}


def _generic_build_calibration_mapping(scene, arm_obj):
    if not mapping.has_pose_bones(arm_obj):
        raise RuntimeError("请先绑定目标骨架")

    resolved_targets = _generic_resolved_targets(arm_obj, scene)
    missing = [
        source_name
        for source_name in GENERIC_CALIBRATION_REQUIRED_SOURCES
        if source_name not in resolved_targets
    ]
    if missing:
        raise RuntimeError("当前 VRM / 通用骨架缺少校准所需骨骼: " + ", ".join(missing))
    return resolved_targets


def _arp_build_calibration_mapping(_scene, arm_obj):
    analysis = mapping_arp.analyze_armature(arm_obj)
    if not analysis.get("is_target_valid"):
        raise RuntimeError("请先绑定目标骨架")
    if not analysis.get("is_arp"):
        raise RuntimeError("当前目标骨架不是可识别的 Auto Rig Pro 标准控制骨架")
    return {
        source_name: analysis["resolved_default_targets"][source_name]
        for source_name in mapping_arp.ARP_RUNTIME_SOURCE_ORDER
        if source_name in analysis["resolved_default_targets"]
    }


def _mmd_build_calibration_mapping(scene, arm_obj):
    analysis = mapping_mmd.analyze_armature(arm_obj)
    if not analysis.get("is_target_valid"):
        raise RuntimeError("请先绑定目标骨架")
    if not analysis.get("is_mmd"):
        raise RuntimeError("当前目标骨架不是可识别的 MMD 标准骨架")

    runtime_map = mapping_mmd.build_runtime_mapping(scene, arm_obj)
    missing = [
        source_name
        for source_name in GENERIC_CALIBRATION_REQUIRED_SOURCES
        if source_name not in runtime_map
    ]
    if missing:
        raise RuntimeError("当前 MMD 骨架缺少校准所需映射: " + ", ".join(missing))
    return runtime_map


def _noop_prepare_receiver_session(scene):
    return analyze_scene_target(scene)


_ADAPTERS = {
    TARGET_RIG_GENERIC: TargetRigAdapter(
        rig_id=TARGET_RIG_GENERIC,
        label="VRM / 通用骨架",
        builtin_preset_file=mapping_vrm.VRM_BUILTIN_PRESET_FILE,
        runtime_strategy=RUNTIME_STRATEGY_GENERIC,
        analyze_armature=_generic_analyze_armature,
        is_detected=_generic_is_detected,
        apply_standard_scene_mapping=_generic_apply_standard_scene_mapping,
        clear_scene_report=mapping_vrm.clear_scene_report,
        build_runtime_mapping=_empty_runtime_mapping,
        build_calibration_mapping=_generic_build_calibration_mapping,
        prepare_receiver_session=_noop_prepare_receiver_session,
    ),
    TARGET_RIG_ARP: TargetRigAdapter(
        rig_id=TARGET_RIG_ARP,
        label="Auto Rig Pro",
        builtin_preset_file=mapping_arp.ARP_BUILTIN_PRESET_FILE,
        runtime_strategy=RUNTIME_STRATEGY_ARP,
        analyze_armature=mapping_arp.analyze_armature,
        is_detected=lambda analysis: bool(analysis.get("is_arp")),
        apply_standard_scene_mapping=mapping_arp.apply_standard_scene_mapping,
        clear_scene_report=mapping_arp.clear_scene_report,
        build_runtime_mapping=mapping_arp.build_runtime_mapping,
        build_calibration_mapping=_arp_build_calibration_mapping,
        prepare_receiver_session=mapping_arp.prepare_receiver_session,
    ),
    TARGET_RIG_MMD: TargetRigAdapter(
        rig_id=TARGET_RIG_MMD,
        label="MMD",
        builtin_preset_file=mapping_mmd.MMD_BUILTIN_PRESET_FILE,
        runtime_strategy=RUNTIME_STRATEGY_MMD,
        analyze_armature=mapping_mmd.analyze_armature,
        is_detected=lambda analysis: bool(analysis.get("is_mmd")),
        apply_standard_scene_mapping=mapping_mmd.apply_standard_scene_mapping,
        clear_scene_report=mapping_mmd.clear_scene_report,
        build_runtime_mapping=mapping_mmd.build_runtime_mapping,
        build_calibration_mapping=_mmd_build_calibration_mapping,
        prepare_receiver_session=_noop_prepare_receiver_session,
    ),
}


def adapter_by_id(rig_id: str) -> TargetRigAdapter:
    return _ADAPTERS.get(str(rig_id).strip().lower(), _ADAPTERS[TARGET_RIG_GENERIC])


def scene_target_rig_type(scene) -> str:
    requested = str(getattr(scene, "vmc_link_target_rig_type", "GENERIC")).strip().lower()
    if requested in SUPPORTED_TARGET_RIGS:
        return requested
    return TARGET_RIG_GENERIC


def scene_target_adapter(scene) -> TargetRigAdapter:
    return adapter_by_id(scene_target_rig_type(scene))


def analyze_scene_target(scene, arm_obj=None):
    if arm_obj is None and scene is not None:
        arm_obj = getattr(scene, "vmc_link_armature", None)
    adapter = scene_target_adapter(scene)
    analysis = adapter.analyze_armature(arm_obj)
    if adapter.rig_id == TARGET_RIG_GENERIC or adapter.is_detected(analysis):
        resolved_rig = adapter.rig_id
    else:
        resolved_rig = TARGET_RIG_GENERIC
    runtime_strategy = adapter_by_id(resolved_rig).runtime_strategy
    return {
        "selected_rig": adapter.rig_id,
        "selected_adapter": adapter,
        "analysis": analysis,
        "resolved_rig": resolved_rig,
        "resolved_adapter": adapter_by_id(resolved_rig),
        "runtime_strategy": runtime_strategy,
    }


def resolve_scene_runtime_rig(scene, arm_obj):
    return analyze_scene_target(scene, arm_obj)["resolved_rig"]


def resolve_scene_runtime_strategy(scene, arm_obj):
    return analyze_scene_target(scene, arm_obj)["runtime_strategy"]


def resolve_target_rig(arm_obj, target_context=None) -> str:
    if target_context is not None:
        target_rig = str(target_context.get("target_rig", "")).strip().lower()
        if target_rig in SUPPORTED_TARGET_RIGS:
            return target_rig
    if mapping_arp.analyze_armature(arm_obj).get("is_arp"):
        return TARGET_RIG_ARP
    if mapping_mmd.analyze_armature(arm_obj).get("is_mmd"):
        return TARGET_RIG_MMD
    return TARGET_RIG_GENERIC


def resolve_runtime_strategy(arm_obj, target_context=None) -> str:
    if target_context is not None:
        strategy = str(target_context.get("target_runtime_strategy", "")).strip().lower()
        if strategy in SUPPORTED_RUNTIME_STRATEGIES:
            return strategy
    return adapter_by_id(resolve_target_rig(arm_obj, target_context)).runtime_strategy


def analyze_target_rig(arm_obj):
    arp_analysis = mapping_arp.analyze_armature(arm_obj)
    mmd_analysis = mapping_mmd.analyze_armature(arm_obj)
    resolved_rig = TARGET_RIG_GENERIC
    if arp_analysis.get("is_arp"):
        resolved_rig = TARGET_RIG_ARP
    elif mmd_analysis.get("is_mmd"):
        resolved_rig = TARGET_RIG_MMD
    return {
        "arp": arp_analysis,
        "mmd": mmd_analysis,
        "resolved_runtime_rig": resolved_rig,
        "resolved_runtime_strategy": adapter_by_id(resolved_rig).runtime_strategy,
    }


def clear_all_scene_reports(scene):
    for rig_id in (TARGET_RIG_GENERIC, TARGET_RIG_ARP, TARGET_RIG_MMD):
        adapter_by_id(rig_id).clear_scene_report(scene)


def apply_selected_scene_mapping(scene, arm_obj=None, fallback_to_generic: bool = False):
    from . import mapper as mapping

    if arm_obj is None and scene is not None:
        arm_obj = getattr(scene, "vmc_link_armature", None)
    if not mapping.has_pose_bones(arm_obj):
        return None

    selected = analyze_scene_target(scene, arm_obj)
    selected_adapter = selected["selected_adapter"]
    if selected_adapter.rig_id != TARGET_RIG_GENERIC and selected_adapter.is_detected(selected["analysis"]):
        return selected_adapter.apply_standard_scene_mapping(scene)

    if fallback_to_generic:
        return _ADAPTERS[TARGET_RIG_GENERIC].apply_standard_scene_mapping(scene)
    return None


def build_runtime_mapping_for_scene(scene, arm_obj=None):
    if arm_obj is None and scene is not None:
        arm_obj = getattr(scene, "vmc_link_armature", None)
    selected = analyze_scene_target(scene, arm_obj)
    resolved_adapter = selected["resolved_adapter"]
    return resolved_adapter.build_runtime_mapping(scene, arm_obj)


def build_calibration_mapping_for_scene(scene, arm_obj=None):
    if arm_obj is None and scene is not None:
        arm_obj = getattr(scene, "vmc_link_armature", None)
    if not mapping.has_pose_bones(arm_obj):
        raise RuntimeError("请先绑定目标骨架")

    selected = analyze_scene_target(scene, arm_obj)
    selected_adapter = selected["selected_adapter"]
    if selected_adapter.rig_id != TARGET_RIG_GENERIC and not selected_adapter.is_detected(selected["analysis"]):
        if selected_adapter.rig_id == TARGET_RIG_ARP:
            raise RuntimeError("当前目标骨架未识别为 Auto Rig Pro，请先检查 ARP 骨架或切换到 VRM / 通用骨架")
        if selected_adapter.rig_id == TARGET_RIG_MMD:
            raise RuntimeError("当前目标骨架未识别为 MMD，请先检查 MMD 骨架或切换到 VRM / 通用骨架")
    runtime_map = selected_adapter.build_calibration_mapping(scene, arm_obj)
    if not runtime_map:
        raise RuntimeError(f"当前 {selected_adapter.label} 没有可用于校准的骨骼映射")
    return {
        "selected_rig": selected_adapter.rig_id,
        "selected_adapter": selected_adapter,
        "analysis": selected["analysis"],
        "runtime_map": runtime_map,
    }


def prepare_scene_receiver_session(scene):
    selected = analyze_scene_target(scene)
    return selected["selected_adapter"].prepare_receiver_session(scene)
