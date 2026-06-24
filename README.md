# VMC Link

面向 Blender 的实时 VMC / RhyLive ARKit 动捕接收、预览和目标映射插件。

当前版本：`0.15.0`

项目当前目标是把“原始接收数据 -> 稳定中间层预览 -> 可替换目标映射 -> Blender 录制”这条链路做成可调试、可扩展、可生产验证的工作流。

## 当前状态

### 已验证可用

- VMC 身体数据接收与 VRM 中间层预览。
- RhyLive ARKit 52 Key 接收与 ARKit 调试面部预览。
- 预览层与目标层解耦：预览层不读取任何用户映射，目标层按映射驱动。
- Auto Rig Pro 目标骨架映射模块已进入可用阶段：
  - 标准 ARP 控制骨检测、自动填充和校验可用。
  - 实时预览驱动已完成多轮抖动、姿态差、手指、脚部和根运动修复。
  - ARP 目标根位移只写入 `c_traj.location`，保持 `rig` 对象和 `c_pos` 默认不动。
  - 当前状态可进入生产环境验证，后续主要是具体角色调优和边界问题修复。
- MMD 形态键映射已具备基础可用状态：
  - `presets/vmc_blend_maps/arona_vmc.json`
  - `presets/arkit_blend_maps/arona_arkit.json`
  - VMC 与 ARKit 两套表情映射在实时预览状态下已验证可用。
- 目标层动作录制完成基础修复：
  - 录制已拆分为独立面板，主面板不再混放录制按钮。
  - 支持显式录制开始帧 / 结束帧，到达结束帧后自动停止。
  - 支持清空当前录制目标在指定范围内的录制关键帧，不影响范围外和无关手工通道。
  - 支持可配置的起始姿态过渡：从开始录制时当前目标静止姿态，过渡到首个有效动捕样本。
  - 开始录制时会为目标骨架和目标面部准备 Action。
  - 每个接收采样会先把目标层当前骨骼姿态和 Shape Key 值缓存到内存轨道。
  - 录制会复用当前 Action；没有 Action 时才创建。
  - 录制期间会临时从目标对象解绑 Action，停止录制时统一烘焙 fcurve，避免 Action 评估把 ARP 控制骨覆盖回 A Pose。
  - 录制会按接收开始前的骨骼 `rotation_mode` 写入旋转曲线，避免运行时 quaternion 模式与回放时 XYZ 模式不匹配。
  - ARP 录制会同步写入手脚 IK/FK 开关关键帧，保证 FK 控制骨曲线在回放时实际驱动下半身。
  - 录制帧号按真实录制时间和 Blender 工程 FPS 换算，不再按接收采样数逐帧递增。
  - 停止录制重新绑定 Action 时会同步绑定 Blender 5.1 action slot，避免 layered action 有数据但不参与回放。
  - Shape Key 录制会写入 Shape Keys 数据块对应的 `KEY` action slot，避免误写到对象 slot 后无法回放。
  - 录制 tick 跨过多个工程帧时会按前后采样插值补齐中间帧，避免保存后的 Action 出现跳帧和台阶型关键帧。
  - 录制补帧已提升为样本级插值：位置与 Shape Key 线性补帧，骨骼旋转按 quaternion slerp 补帧后再写回原旋转模式，避免 Euler 分量补帧带来的局部不均匀。
  - 录制烘焙后的关键帧统一写为 `LINEAR` 插值，避免默认 `BEZIER` 缓动继续制造不均匀曲线段。
  - 录制阶段不再实时扫描和更新 `keyframe_points`，避免录制越久视口越卡。
  - 停止录制或停止接收后会重新绑定录制 Action，不删除已写入数据。

### 当前待修复 / 待验证

- 录制功能仍需要真实 VMC / ARKit 接收流下的长时间回放验证。
- ARP 后期编辑辅助待开发：把已录制 FK 腿部动作转换为 `c_foot_ik / c_leg_pole / c_toes_ik` 控制器关键帧，方便脚部 IK 手动修帧。
- 映射 UI 仍偏向 ARP，需要拆分为可切换目标骨架类型的结构。
- 尚未实现 VRM -> MMD 标准骨骼映射模块。
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
  - 当前支持通用骨骼映射与 ARP 专用映射辅助。
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

- 当前主线：`VRM 中间层 -> Auto Rig Pro`
- 内建预设：
  - `presets/bone_maps/arp_fk_humanoid.json`
- 后续目标：
  - 解耦 ARP 专用逻辑。
  - UI 增加目标骨架类型切换。
  - 新增 `VRM 中间层 -> MMD 标准骨骼` 映射模块。

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
- 骨骼映射：骨骼预设、手动映射、ARP 辅助区。
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
- 运行时缓存骨引用、映射表和预览对象引用，减少每帧重复查找。
- 只写入发生变化的骨骼 / Shape Key。
- 数据预览默认折叠，UI 刷新节流。
- 插件运行时不主动强制 `view_layer.update()`。

## 当前代码结构

```text
vmc_link/
  __init__.py              # 插件入口、版本、依赖检查
  blender_manifest.toml    # Blender 扩展清单
  assets/                  # 内置调试资产
  core/                    # 常量、工具、状态、注册装配
  runtime/                 # Scene 属性、网络接收、驱动循环、录制
  mapping/                 # 通用映射、预设、ARP 映射模块
  preview/                 # VRM 预览骨架、ARKit 调试面部
  ui/                      # 面板和 operator
  presets/                 # 内建 / 用户映射预设
  wheels/                  # 打包依赖
```

## 下一步

详细开发计划见 [DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md)。

近期优先级：

1. 用真实 VMC / ARKit 接收流验证录制回放，继续修复录制边界问题。
2. 拆分映射模块和 UI，加入目标骨架类型切换，为 MMD 骨骼映射做准备。
3. 新增 `VRM -> MMD` 骨骼映射模块。
4. 进入生产环境验证，继续 debug、性能优化和预设补全。

## 参考项目

- Fork 原项目：[VMC-Link](https://weforge.xyz/partisan/VMC-Link)
- ARKit 面部模型来源：[hinzka/52blendshapes-for-VRoid-face](https://github.com/hinzka/52blendshapes-for-VRoid-face)
- RhyLive Unity SDK：[RhythMoAI/RhyLiveSDK_Unity](https://github.com/RhythMoAI/RhyLiveSDK_Unity)
- Auto-Rig Pro：[Auto-Rig Pro](https://superhivemarket.com/products/auto-rig-pro)
