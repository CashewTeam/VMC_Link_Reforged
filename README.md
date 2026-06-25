# VMC_Link_Reforged

面向 Blender 的实时 VMC / RhyLive ARKit 动捕接收、预览和目标映射插件。

当前阶段：`Alpha`

当前版本：`0.30.63`

项目名：`VMC_Link_Reforged`

项目当前目标是把“原始接收数据 -> 稳定中间层预览 -> 可替换目标映射 -> Blender 录制”这条链路做成可调试、可扩展、可生产验证的工作流。

## 当前状态

### 已验证可用

- VMC 身体数据接收与 VRM 中间层预览。
- RhyLive ARKit 52 Key 接收与 ARKit 调试面部预览。
- 预览层与目标层解耦：预览层只用于查看原始输入，目标层按当前映射和目标骨架类型驱动。
- Auto Rig Pro 目标骨架映射模块已进入可用阶段，支持检测、自动填充、校验、实时预览和录制回放，后续主要进入生产角色调优。
- MMD 形态键映射已具备基础可用状态，`presets/vmc_blend_maps/arona_vmc.json` 与 `presets/arkit_blend_maps/arona_arkit.json` 已通过实时预览验证。
- 目标层录制已拆成独立面板，支持显式帧范围、清空范围关键帧、起始姿态过渡、原始帧缓存、停止后离线烘焙和状态栏保存进度。
- 目标角色实时预览与录制已经开始共用 `TargetEvaluatedSample`，避免预览和录制走两套语义。
- 目标骨架类型分发已接入 `Generic / ARP / MMD`，接收启动和目标绑定阶段会按用户选择的目标类型准备运行时上下文。

优化、修复和性能收敛记录已移到 [优化与修复记录](./docs/OPTIMIZATION_AND_FIX_HISTORY.md)。

### 当前待修复 / 待验证

- 录制功能仍需要真实 VMC / ARKit 接收流下的长时间回放验证。
- ARP 后期编辑辅助待开发：把已录制 FK 腿部动作转换为 `c_foot_ik / c_leg_pole / c_toes_ik` 控制器关键帧，方便脚部 IK 手动修帧。
- 映射模块解耦已完成第一阶段，但 UI 结构仍需要继续收敛成清晰的 `VRM / ARP / MMD` 多目标骨架工作流。
- `VRM -> MMD` 目标骨架模块仍处于落地阶段：当前已有占位入口、默认名表和基础运行时分发，后续需要补齐真实 MMD 骨架检测、校准分支、轴向修正、手脚和手指细节。
- 尚未完成生产环境系统性验证和调试工具收敛。

## 运行链路

### 接收输入

- VMC:
  - `/VMC/Ext/Root/Pos`
  - `/VMC/Ext/Tra/Pos`
  - `/VMC/Ext/Bone/Pos`
  - `/VMC/Ext/Blend/Val`
- RhyLive ARKit:
  - `/Face`

### 预览层

- `vmc_link_preview_armature`
  - VRM 风格中间层骨架。
  - 直接按原始 VMC 骨骼数据驱动。
  - 不受骨骼映射、ARP 映射或目标骨架设置影响。
- `vmc_link_preview_face_object`
  - ARKit 52 Key 调试面部。
  - `面部来源 = RhyLive ARKit` 时直接按 ARKit Key 驱动。
  - 不受表情映射预设影响。

### 目标层

- `vmc_link_armature`
  - 映射后的目标骨架。
  - 当前支持通用骨骼映射，以及 `ARP / MMD` 专用辅助与运行时分发。
- `vmc_link_face_object`
  - 映射后的目标面部。
  - 支持 VMC 表情映射和 ARKit 表情映射。
- `实时驱动目标对象`
  - 开启：预览层和目标层都实时更新。
  - 关闭：只更新预览层，目标层停止写入。

### 根运动

- `固定角色到中心` 开启时忽略 VMC 根位移。
- 关闭时位移来源优先级为：
  1. `Root/Pos`
  2. `Tra/Pos`
  3. `Bone/Pos:Hips`
- 普通目标骨架：位移叠加到目标骨架对象起始位置。
- ARP 目标骨架：位移叠加到 `c_traj.location`，不移动 `rig` 对象，不写入 `c_pos`。

## 映射与预设

当前有三类 JSON 映射预设：

```text
presets/
  bone_maps/
  vmc_blend_maps/
  arkit_blend_maps/
```

### 骨骼映射

- 当前主线：`VRM 中间层 -> 可切换目标骨架`
- 当前目标骨架类型：
  - `VRM / 通用骨架`
  - `Auto Rig Pro`
  - `MMD`
- 内建预设：
  - `presets/bone_maps/arp_fk_humanoid.json`
  - `presets/bone_maps/mmd_humanoid.json`
- 已完成基础边界：
  - `mapping/target_rig.py`
  - `mapping/mmd.py`
- 后续目标：
  - 将 `VRM / 通用骨架` 产品化为一键匹配、校验和内建预设。
  - 补齐 `VRM 中间层 -> MMD` 的检测、校准、轴向修正与角色差异。
  - 继续收敛 `VRM / ARP / MMD` 的 UI 边界。
  - 在真实角色上补齐生产调优。

### 表情映射

- VMC 表情映射：
  - 当前作为兼容和备选链路保留。
  - 已有 MMD 形态键映射表并通过实时预览验证。
- ARKit 表情映射：
  - 后续面部适配主线。
  - 已有 MMD 形态键映射表并通过实时预览验证。

JSON 基本结构：

```json
{
  "version": 1,
  "mapping_kind": "bone",
  "entries": {
    "Hips": "c_root_bend.x"
  }
}
```

`mapping_kind` 可取：

- `bone`
- `vmc_blend`
- `arkit_blend`

## UI 结构

- 主面板：接收器状态、暂停 / 继续 / 停止、接收配置、目标对象绑定。
- 录制面板：录制状态、帧范围、起始过渡、清空范围内关键帧。
- 中间层预览：创建 / 重建 VRM 预览骨架、按目标校准长度、导入 ARKit 调试面部。
- 骨骼映射：目标骨架类型、骨骼预设、手动映射、ARP / MMD 辅助区。
- VMC 表情映射：VMC Blend 到目标 Shape Key。
- ARKit 表情映射：ARKit 52 Key 到目标 Shape Key。
- 数据预览：默认折叠，底部并排显示 VMC 与 ARKit 原始数据。

## 预览对象与集合

插件管理专用集合：

- `VMC_Link`
  - 插件专用集合。
  - VRM 预览骨架和 ARKit 调试面部放在这里。
- `ArkitFace`
  - 从 `assets/Arkitface.blend` 追加的源集合。
  - 只追加该集合，不导入 `.blend` 中的其他无关内容。

VRM 预览骨架：

- 对象名固定为 `VMC_TEST_DUMMY`。
- 创建和重建只搜索 `VMC_Link` 集合，避免影响场景内其他骨架。
- 可按当前目标骨架执行长度校准。

## 性能原则

- UDP 收包和 OSC 解码运行在后台线程。
- Blender RNA 写入保留在主线程，避免线程安全问题。
- 实时预览允许丢帧；录制保存以原始帧缓存和离线烘焙为准。
- 运行时缓存骨引用、映射表、shape key 引用和目标上下文，减少每帧重复查找。
- 目标求值按 dirty bone / dirty blend 增量处理，只写入实际变化的骨骼和 Shape Key。
- 数据预览默认折叠，UI 刷新和 3D 视图 redraw 节流。
- 插件运行时不主动强制 `view_layer.update()`。

具体优化与修复记录见 [优化与修复记录](./docs/OPTIMIZATION_AND_FIX_HISTORY.md)。

## 当前代码结构

```text
vmc_link/
  __init__.py              # 插件入口、版本、依赖检查
  blender_manifest.toml    # Blender 扩展清单
  assets/                  # 内置调试资产
  core/                    # 常量、工具、状态、注册装配
  runtime/                 # Scene 属性、网络接收、驱动循环、录制
  mapping/                 # 通用映射、ARP / MMD 目标骨架模块、目标类型分发
  preview/                 # VRM 预览骨架、ARKit 调试面部
  ui/                      # 面板和 operator
  presets/                 # 内建 / 用户映射预设
  docs/                    # 计划、优化记录和开发文档
  wheels/                  # 打包依赖
```

## 打包与发布

- 当前项目仍处于 `Alpha` 小范围测试阶段。
- 对外分发的 Blender 5.1 扩展包命名固定为：
  - `VMC_Link_Reforged_Alpha_<版本号>_For5.1.zip`
- 版本号取 `blender_manifest.toml` 与 `__init__.py` 中一致的插件版本号。
- 打包时必须保证 `blender_manifest.toml` 位于 zip 根目录，不能再额外包一层外部文件夹。
- 打包内容只包含扩展本体文件与运行依赖，排除本地参考资料和打包垃圾文件。
- 默认纳入：
  - `__init__.py`
  - `blender_manifest.toml`
  - `README.md`
  - `assets/`
  - `core/`
  - `mapping/`
  - `presets/`
  - `preview/`
  - `runtime/`
  - `ui/`
  - `docs/`
  - `wheels/`
- 必须排除：
  - `.git`
  - `__pycache__/`
  - `.DS_Store`
  - `RhyLiveSDK_Unity-main/`
  - 已生成的 `*.zip`
- 当前扩展内部 `id` 仍保持为 `vmc_link`，以避免打破现有测试安装的升级路径。

## 下一步

详细开发计划见 [DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md)。

VRM / MMD 骨骼适配落地计划见 [VRM/MMD 骨骼适配计划](./docs/VRM_MMD_ADAPTATION_PLAN.md)。

近期优先级：

1. 落地 `VRM / MMD` 目标骨架适配分支，优先补齐 MMD 骨架检测、默认映射和校准策略。
2. 保持 VRM / 通用骨架路径复用现有 VRM 预览骨架链路，只补一键匹配和预设。
3. 用真实 VMC / ARKit 接收流验证录制回放，继续确认目标预览和录制结果一致。
4. 进入生产环境验证，继续 debug、性能优化和预设补全。

## 参考项目

- Fork 原项目：[VMC-Link](https://weforge.xyz/partisan/VMC-Link)
- ARKit 面部模型来源：[hinzka/52blendshapes-for-VRoid-face](https://github.com/hinzka/52blendshapes-for-VRoid-face)
- RhyLive Unity SDK：[RhythMoAI/RhyLiveSDK_Unity](https://github.com/RhythMoAI/RhyLiveSDK_Unity)
- Auto-Rig Pro：[Auto-Rig Pro](https://superhivemarket.com/products/auto-rig-pro)
