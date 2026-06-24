DEFAULT_PORT = 39539
DEFAULT_BIND_ADDRESS = "127.0.0.1"
DEFAULT_RATE_HZ = 60
DEFAULT_ARKIT_PORT = 17890

LOC_EPS = 1e-5
ROT_EPS = 1e-6
SHAPE_EPS = 1e-4
RECEIVER_FRAME_QUIET_WINDOW_SEC = 0.003
RECEIVER_FRAME_MAX_DEFER_SEC = 0.012
ARP_ROTATION_FILTER_DEADBAND_DEG = 0.08
ARP_ROTATION_FILTER_MIN_ALPHA = 0.12
ARP_ROTATION_FILTER_FAST_ANGLE_DEG = 3.0

BIND_MODE_THIS_PC = "THIS_PC"
BIND_MODE_LOCAL_NET = "LOCAL_NET"
BIND_MODE_CUSTOM = "CUSTOM"

FACE_SOURCE_VMC = "VMC"
FACE_SOURCE_RHYLIVE_ARKIT = "RHYLIVE_ARKIT"

DUMMY_ARMATURE_NAME = "VMC_TEST_DUMMY"
DUMMY_DELETE_OLD = True
DEBUG_LOGGING = False
PLUGIN_COLLECTION_NAME = "VMC_Link"
ARKIT_ASSET_COLLECTION_NAME = "ArkitFace"

INTERMEDIATE_RIG_ROLE = "vrm_intermediate_rig"
ARKIT_PREVIEW_FACE_ROLE = "arkit_intermediate_face"
INTERMEDIATE_RIG_SCHEMA_VERSION = 2
INTERMEDIATE_RIG_PROP_ROLE = "vmc_link_role"
INTERMEDIATE_RIG_PROP_SCHEMA = "vmc_link_schema_version"


BONE_ALIASES = {
    "Hips": ["hips", "pelvis", "root"],
    "Spine": ["spine", "spine1", "spine_01"],
    "Chest": ["chest", "spine2", "spine_02"],
    "UpperChest": ["upperchest", "upper chest", "spine3", "spine_03"],
    "Neck": ["neck"],
    "Head": ["head"],
    "LeftEye": [
        "lefteye",
        "lefteyebone",
        "eye_l",
        "eye.l",
        "l_eye",
        "eyel",
        "left_eye",
        "left eye",
        "faceeye_l",
        "face_eye_l",
        "eyeleft",
    ],
    "RightEye": [
        "righteye",
        "righteyebone",
        "eye_r",
        "eye.r",
        "r_eye",
        "eyer",
        "right_eye",
        "right eye",
        "faceeye_r",
        "face_eye_r",
        "eyeright",
    ],
    "LeftShoulder": ["leftshoulder", "left shoulder", "shoulder_l", "shoulder.l"],
    "RightShoulder": ["rightshoulder", "right shoulder", "shoulder_r", "shoulder.r"],
    "LeftUpperArm": ["leftupperarm", "left arm", "upperarm_l", "upperarm.l"],
    "LeftLowerArm": [
        "leftlowerarm",
        "left elbow",
        "lowerarm_l",
        "lowerarm.l",
        "forearm_l",
        "forearm.l",
        "leftforearm",
        "left forearm",
    ],
    "LeftHand": ["lefthand", "left wrist", "hand_l", "hand.l", "wrist_l", "wrist.l"],
    "RightUpperArm": ["rightupperarm", "right arm", "upperarm_r", "upperarm.r"],
    "RightLowerArm": [
        "rightlowerarm",
        "right elbow",
        "lowerarm_r",
        "lowerarm.r",
        "forearm_r",
        "forearm.r",
        "rightforearm",
        "right forearm",
    ],
    "RightHand": ["righthand", "right wrist", "hand_r", "hand.r", "wrist_r", "wrist.r"],
    "LeftUpperLeg": ["leftupperleg", "left leg", "leftupleg", "upperleg_l", "upperleg.l", "thigh_l", "thigh.l"],
    "LeftLowerLeg": ["leftlowerleg", "left knee", "lowerleg_l", "lowerleg.l", "calf_l", "calf.l"],
    "LeftFoot": ["leftfoot", "left ankle", "foot_l", "foot.l", "ankle_l", "ankle.l"],
    "LeftToeBase": ["lefttoebase", "left toe", "lefttoes", "toes_l", "toes.l"],
    "RightUpperLeg": ["rightupperleg", "right leg", "rightupleg", "upperleg_r", "upperleg.r", "thigh_r", "thigh.r"],
    "RightLowerLeg": ["rightlowerleg", "right knee", "lowerleg_r", "lowerleg.r", "calf_r", "calf.r"],
    "RightFoot": ["rightfoot", "right ankle", "foot_r", "foot.r", "ankle_r", "ankle.r"],
    "RightToeBase": ["righttoebase", "right toe", "righttoes", "toes_r", "toes.r"],
}

_FINGER_SPECS = {
    "Thumb": "thumb",
    "IndexFinger": "f_index",
    "MiddleFinger": "f_middle",
    "RingFinger": "f_ring",
    "LittleFinger": "f_pinky",
}

_FINGER_SEGMENTS = ("proximal", "intermediate", "distal")


def _build_finger_aliases(side_suffix: str):
    aliases = {}
    side_name = "left" if side_suffix == "L" else "right"
    side = side_suffix.lower()

    for finger_name, blender_prefix in _FINGER_SPECS.items():
        short_name = finger_name.replace("Finger", "").lower()
        is_thumb = finger_name == "Thumb"

        for joint_pos, segment in enumerate(_FINGER_SEGMENTS):
            vmc_idx = joint_pos if is_thumb else joint_pos + 1
            vmc_name = f"{finger_name}{vmc_idx}_{side_suffix}"

            row = [
                vmc_name.lower(),
                f"{side_name}{short_name}{segment}",
            ]

            for idx in (joint_pos, joint_pos + 1):
                row.append(f"{blender_prefix}.{idx:02d}.{side}")
                row.append(f"{blender_prefix}_{idx:02d}_{side}")
                if not is_thumb:
                    row.append(f"{short_name}.{idx:02d}.{side}")
                    row.append(f"{short_name}_{idx:02d}_{side}")

            aliases[vmc_name] = row

    return aliases


BONE_ALIASES.update(_build_finger_aliases("L"))
BONE_ALIASES.update(_build_finger_aliases("R"))


BLEND_ALIASES = {
    "A": ["A", "a", "MTH_A", "mouth_a", "vrc.v_aa", "Viseme_AA", "viseme_aa"],
    "I": ["I", "i", "MTH_I", "mouth_i", "vrc.v_ih", "Viseme_IH", "viseme_ih"],
    "U": ["U", "u", "MTH_U", "mouth_u", "vrc.v_ou", "Viseme_OU", "viseme_ou"],
    "E": ["E", "e", "MTH_E", "mouth_e", "vrc.v_e", "Viseme_E", "viseme_e"],
    "O": ["O", "o", "MTH_O", "mouth_o", "vrc.v_oh", "Viseme_OH", "viseme_oh"],
    "CH": ["CH", "ch", "MTH_CH", "mouth_ch", "vrc.v_ch", "Viseme_CH", "viseme_ch"],
    "DD": ["DD", "dd", "MTH_DD", "mouth_dd", "vrc.v_dd", "Viseme_DD", "viseme_dd"],
    "FF": ["FF", "ff", "MTH_FF", "mouth_ff", "vrc.v_ff", "Viseme_FF", "viseme_ff"],
    "KK": ["KK", "kk", "MTH_KK", "mouth_kk", "vrc.v_kk", "Viseme_KK", "viseme_kk"],
    "NN": ["NN", "nn", "MTH_NN", "mouth_nn", "vrc.v_nn", "Viseme_NN", "viseme_nn"],
    "PP": ["PP", "pp", "MTH_PP", "mouth_pp", "vrc.v_pp", "Viseme_PP", "viseme_pp"],
    "RR": ["RR", "rr", "MTH_RR", "mouth_rr", "vrc.v_rr", "Viseme_RR", "viseme_rr"],
    "SIL": ["SIL", "sil", "MTH_SIL", "mouth_sil", "vrc.v_sil", "Viseme_SIL", "viseme_sil"],
    "SS": ["SS", "ss", "MTH_SS", "mouth_ss", "vrc.v_ss", "Viseme_SS", "viseme_ss"],
    "TH": ["TH", "th", "MTH_TH", "mouth_th", "vrc.v_th", "Viseme_TH", "viseme_th"],
    "Fun": ["Fun", "fun", "MTH_Fun", "Smile", "smile", "Happy", "happy", "face happy"],
    "Joy": ["Joy", "joy", "VMC_Joy", "face joy", "face happy"],
    "Sorrow": ["Sorrow", "sorrow", "Sad", "sad", "VMC_Sorrow", "face sad"],
    "Angry": ["Angry", "angry", "VMC_Angry", "face angry"],
    "Surprise": ["Surprise", "surprise", "Surprised", "surprised", "VMC_Surprise", "face surprised"],
    "Sad": ["Sad", "sad", "face sad"],
    "Surprised": ["Surprised", "surprised", "face surprised"],
    "Blink": ["Blink", "blink", "blink both", "EYE_Close", "eyeBlink", "EyeBlink", "vrc.blink", "EyeClose"],
    "Blink_L": [
        "Blink_L",
        "BlinkLeft",
        "blink_l",
        "blinkleft",
        "EYE_Close_L",
        "eyeBlinkLeft",
        "EyeBlinkLeft",
        "eyeBlink_L",
        "EyeBlink_L",
        "vrc.blink_left",
        "vrc.blink.L",
        "vrc.lowerlid_left",
        "eyeCloseLeft",
    ],
    "Blink_R": [
        "Blink_R",
        "BlinkRight",
        "blink_r",
        "blinkright",
        "EYE_Close_R",
        "eyeBlinkRight",
        "EyeBlinkRight",
        "eyeBlink_R",
        "EyeBlink_R",
        "vrc.blink_right",
        "vrc.blink.R",
        "vrc.lowerlid_right",
        "eyeCloseRight",
    ],
    "LookUp": ["LookUp", "lookUp", "look_up", "look up", "EYE_LookUp", "eyeLookUp", "vrc.look_up", "vrc.lookUp", "vrc.look.U"],
    "LookDown": ["LookDown", "lookDown", "look_down", "look down", "EYE_LookDown", "eyeLookDown", "vrc.look_down", "vrc.lookDown", "vrc.look.D"],
    "LookLeft": ["LookLeft", "lookLeft", "look_left", "look left", "EYE_LookLeft", "eyeLookLeft", "vrc.look_left", "vrc.lookLeft", "vrc.look.L"],
    "LookRight": ["LookRight", "lookRight", "look_right", "look right", "EYE_LookRight", "eyeLookRight", "vrc.look_right", "vrc.lookRight", "vrc.look.R"],
    "LookUp_L": ["LookUp_L", "LookUpLeft", "lookUpLeft", "eyeLookUpLeft", "EyeLookUpLeft", "vrc.lookUp.L"],
    "LookUp_R": ["LookUp_R", "LookUpRight", "lookUpRight", "eyeLookUpRight", "EyeLookUpRight", "vrc.lookUp.R"],
    "LookDown_L": ["LookDown_L", "LookDownLeft", "lookDownLeft", "eyeLookDownLeft", "EyeLookDownLeft", "vrc.lookDown.L"],
    "LookDown_R": ["LookDown_R", "LookDownRight", "lookDownRight", "eyeLookDownRight", "EyeLookDownRight", "vrc.lookDown.R"],
    "LookLeft_L": ["LookLeft_L", "LookLeftLeft", "lookLeftLeft", "eyeLookLeftLeft", "EyeLookLeftLeft", "eyeLookOutLeft"],
    "LookLeft_R": ["LookLeft_R", "LookLeftRight", "lookLeftRight", "eyeLookLeftRight", "EyeLookLeftRight", "eyeLookInRight"],
    "LookRight_L": ["LookRight_L", "LookRightLeft", "lookRightLeft", "eyeLookRightLeft", "EyeLookRightLeft", "eyeLookInLeft"],
    "LookRight_R": ["LookRight_R", "LookRightRight", "lookRightRight", "eyeLookRightRight", "EyeLookRightRight", "eyeLookOutRight"],
    "BrowsDownUp": ["BrowsDownUp", "BRW_Up", "BrowUp", "browUp", "BrowsUp", "brows_up", "brow_raise", "browInnerUp", "eyebrow_up"],
    "BrowInnerUp": ["BrowInnerUp", "browInnerUp", "brow_inner_up", "brow up", "BRW_Up"],
    "BrowDown_L": ["BrowDown_L", "BrowDownLeft", "browDownLeft", "brow_down_l", "brow down left", "BRW_Down_L"],
    "BrowDown_R": ["BrowDown_R", "BrowDownRight", "browDownRight", "brow_down_r", "brow down right", "BRW_Down_R"],
    "BrowOuterUp_L": ["BrowOuterUp_L", "BrowOuterUpLeft", "browOuterUpLeft", "brow_outer_up_l", "brow outer up left", "BRW_Up_L"],
    "BrowOuterUp_R": ["BrowOuterUp_R", "BrowOuterUpRight", "browOuterUpRight", "brow_outer_up_r", "brow outer up right", "BRW_Up_R"],
}


ARKIT_BLENDSHAPE_KEYS = [
    "browDownLeft",
    "browDownRight",
    "browInnerUp",
    "browOuterUpLeft",
    "browOuterUpRight",
    "cheekPuff",
    "cheekSquintLeft",
    "cheekSquintRight",
    "eyeBlinkLeft",
    "eyeBlinkRight",
    "eyeLookDownLeft",
    "eyeLookDownRight",
    "eyeLookInLeft",
    "eyeLookInRight",
    "eyeLookOutLeft",
    "eyeLookOutRight",
    "eyeLookUpLeft",
    "eyeLookUpRight",
    "eyeSquintLeft",
    "eyeSquintRight",
    "eyeWideLeft",
    "eyeWideRight",
    "jawForward",
    "jawLeft",
    "jawOpen",
    "jawRight",
    "mouthClose",
    "mouthDimpleLeft",
    "mouthDimpleRight",
    "mouthFrownLeft",
    "mouthFrownRight",
    "mouthFunnel",
    "mouthLeft",
    "mouthLowerDownLeft",
    "mouthLowerDownRight",
    "mouthPressLeft",
    "mouthPressRight",
    "mouthPucker",
    "mouthRight",
    "mouthRollLower",
    "mouthRollUpper",
    "mouthShrugLower",
    "mouthShrugUpper",
    "mouthSmileLeft",
    "mouthSmileRight",
    "mouthStretchLeft",
    "mouthStretchRight",
    "mouthUpperUpLeft",
    "mouthUpperUpRight",
    "noseSneerLeft",
    "noseSneerRight",
    "tongueOut",
]

MAPPING_KIND_BONE = "bone"
MAPPING_KIND_VMC_BLEND = "vmc_blend"
MAPPING_KIND_ARKIT_BLEND = "arkit_blend"

PRESET_NONE_ID = "__NONE__"
PRESET_SCHEMA_VERSION = 1

MAPPING_KIND_LABELS = {
    MAPPING_KIND_BONE: "骨骼映射",
    MAPPING_KIND_VMC_BLEND: "VMC 表情映射",
    MAPPING_KIND_ARKIT_BLEND: "ARKit 表情映射",
}

MAPPING_PRESET_SUBDIRS = {
    MAPPING_KIND_BONE: "bone_maps",
    MAPPING_KIND_VMC_BLEND: "vmc_blend_maps",
    MAPPING_KIND_ARKIT_BLEND: "arkit_blend_maps",
}

MAPPING_PRESET_PROP_NAMES = {
    MAPPING_KIND_BONE: ("vmc_link_bone_map_preset", "vmc_link_bone_map_save_name"),
    MAPPING_KIND_VMC_BLEND: ("vmc_link_vmc_blend_preset", "vmc_link_vmc_blend_save_name"),
    MAPPING_KIND_ARKIT_BLEND: ("vmc_link_arkit_blend_preset", "vmc_link_arkit_blend_save_name"),
}

INTERMEDIATE_REQUIRED_BONES = (
    "Hips",
    "Spine",
    "Chest",
    "UpperChest",
    "Neck",
    "Head",
    "LeftEye",
    "RightEye",
    "LeftShoulder",
    "LeftUpperArm",
    "LeftLowerArm",
    "LeftHand",
    "RightShoulder",
    "RightUpperArm",
    "RightLowerArm",
    "RightHand",
    "LeftUpperLeg",
    "LeftLowerLeg",
    "LeftFoot",
    "LeftToeBase",
    "RightUpperLeg",
    "RightLowerLeg",
    "RightFoot",
    "RightToeBase",
)

INTERMEDIATE_OPTIONAL_BONES = tuple(
    f"{finger_name}{joint_idx}_{side_suffix}"
    for side_suffix in ("L", "R")
    for finger_name, joint_indices in (
        ("Thumb", (0, 1, 2)),
        ("IndexFinger", (1, 2, 3)),
        ("MiddleFinger", (1, 2, 3)),
        ("RingFinger", (1, 2, 3)),
        ("LittleFinger", (1, 2, 3)),
    )
    for joint_idx in joint_indices
)
