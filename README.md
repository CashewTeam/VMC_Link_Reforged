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
  - 支持可配置的起始姿态过渡：从接收会话启动时保存的目标初始姿态，过渡到过渡结束帧对应的有效动捕姿态。
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
  - 录制阶段会缓存 `RawMotionFrame` 原始帧，停止录制后按原始时间戳离线重建目标采样并统一烘焙到 Action。
  - 实时目标预览只消费最新一帧原始输入，不再为追赶积压队列而在主线程重放整批历史帧；录制仍保留完整原始帧序列用于离线烘焙。
  - 停止录制或停止接收后会重新绑定录制 Action，不删除已写入数据。
  - 停止录制后的保存流程已拆成“准备保存 -> 重建采样 -> 写入动作曲线”三段，并在 Blender 状态栏持续显示进度条；录制前状态恢复、视图层刷新和目标上下文构建也不再挤在进度条出现之前同步卡住主线程。
  - MMD / ARP 目标骨架路径会在接收上下文里预编译 rest quaternion、inverse quaternion 和起始 basis inverse；实时求值阶段不再每帧重复做四元数求逆、多级 context 查表和脏骨集合重复构造。
  - ARP 非 `local_basis_delta` 路径现在直接消费 VMC 原始世界旋转，不再先递归重建 `source pose matrix` 再从矩阵里取四元数，减少主线程 `convert_local_to_pose()`、`Matrix.LocRotScale()` 和中间矩阵分配。
  - ARP 目标 pose 依赖链在 fallback 情况下现在直接复用 Blender 当前 `pose_bone.matrix`，不再为未改写且无当前帧约束依赖的父链骨骼递归重建姿态矩阵；同时移除了已废弃的 `preview_bone_data / target_bone_data` 会话上下文字典复制。
  - 表情链路现在只会把“数值实际发生变化”的 VMC / ARKit key 标记为脏并送入主线程；目标 Shape Key 求值和 ARKit 预览面部写入都改为按脏 key 增量处理，不再每次表情包到达都整表遍历。
  - 身体链路现在也只会在 Root / Tra / Bone 姿态实际变化时才标记 body dirty 和 dirty bone；上游重复发送同样的骨骼包时，不再白跑预览骨架、目标骨架和根运动链路。
  - 目标样本应用阶段已经统一按接收会话初始化后的 `QUATERNION` 旋转模式写入，不再在每个对象/骨骼写入时重复分支判断 `rotation_mode` 或保留 Euler 转换路径，减少实时目标驱动最内层循环的 RNA 读取和旋转转换开销。
  - 目标样本应用阶段现在直接复用求值阶段塞入 sample 的 `pose_bone / ik_fk_pose_bone / key_block` 引用，不再在实时主链里重复 `pose.bones.get(...)`、`shape_keys` 存在性判断和按名回查。
  - `apply_target_sample()` 里对象/骨骼位置与四元数的缓存比较现在直接按分量对 `mathutils` 值做比较，只有真的发生写入时才构造缓存 tuple，减少实时目标应用最内层循环的临时 tuple 分配。
  - 接收线程现在会同步维护 canonical 骨骼缓冲；主线程实时链路不再每 tick 对当前 `bone_buf` 重做整表规范化。
  - 目标骨骼与 Shape Key 的实时应用阶段开始直接复用 sample 内的 `pose_bone / key_block` 引用，减少主线程按名称重复回查 RNA 集合。
  - ARP 目标链路现在会在接收上下文内预编译 source 分组入口、IK/FK 控制骨列表和约束依赖映射，减少主线程每帧重建字典和重复扫描 constraint 列表。
  - 目标对象起始世界分解、世界逆旋转，以及 ARP 目标骨起始平移/缩放现在会缓存到接收上下文里，减少主线程每帧 `decompose()`、`to_translation()`、`to_scale()` 和 `to_3x3().inverted()`。
  - canonical 骨骼输入在运行时求值中会优先走直接 key 命中，避免 `get_vmc_bone_pose()` 在主链上重复构建大小写/规范化查找表。
  - `TargetEvaluatedSample` 的对象和骨骼项不再冗余保存 `rotation_mode` 字符串，应用阶段也直接复用已有 `Vector / Quaternion`，减少主线程字符串分配和 mathutils 复制。
  - 目标层实时应用已去掉未被录制链路消费的 `driven_bones / driven_shapes` 集合构建，以及 `record_current_sample()` 的历史无效参数，减少主线程每帧临时集合和参数传递开销。
  - ARP 与预览路径现在会在接收上下文里缓存骨骼 `Bone` 引用、`matrix_local` 和父骨本地矩阵，减少实时求值阶段反复读取静态 RNA 数据和父链本地矩阵。
  - `runtime/driver.py` 中已经退出实时主链的旧 ARP 直驱实现和重复 helper 已移除，避免继续维护两套目标驱动路径，也减少后续排查性能热点时的噪音。
  - `TargetEvaluatedSample` 现在改为按需填充通道：实时求值阶段不再默认复制对象 / 骨骼的当前位置和 basis 旋转，只在确实要写入该通道时才放进 sample；录制转换阶段再补齐默认值，减少主线程每帧的 `location.copy()` 和 `matrix_basis.to_quaternion()`。
  - ARP 实时求值现在只为“后续父链 / 约束依赖真的会用到”的目标骨生成完整 pose matrix，叶子骨不再无差别执行第二次 `convert_local_to_pose()` 和 `Matrix.LocRotScale()`。
  - 录制转换阶段不再因为 `dict.get(default)` 的默认参数提前求值而无条件生成对象四元数或骨骼 basis 四元数，减少离线重建和停止录制保存时的额外 mathutils 开销。
  - 录制阶段现在会在开始录制时缓存目标对象和目标骨骼的 `rotation_mode`，离线重建和保存时不再每帧回查接收前 snapshot 里的旋转模式。
  - 预览骨架和预览骨骼的 `rotation_mode = QUATERNION` 现在只会在接收上下文初始化后设置一次，不再在实时预览每帧重复写同一个 RNA 属性。
  - 目标对象和实时驱动涉及到的目标骨骼现在也会在接收上下文初始化后一次性切到 `QUATERNION`，停止接收时仍复用原有快照恢复，减少实时驱动阶段每帧 `Quaternion -> Euler` 转换开销。
  - 主线程消费实时输入时不再先把整段 `raw_frame_queue` 复制成 Python 列表或逐帧 `popleft()` 再取最后一帧，而是直接读取 `deque` 最后一帧后整队列清空，只保留最新输入，减少高输入速率下的无效内存分配、Python 层循环和历史帧搬运。
  - 接收线程现在会把“身体姿态 / VMC 表情 / ARKit 表情”更新类型一起写入 `raw_frame`；主线程会按脏类型只运行必要的预览和目标子链路，例如 ARKit-only 输入不再白跑整套 VRM / ARP 骨骼求值，身体-only 输入也不再白跑目标 Shape Key 求值。
  - 在按脏类型增量驱动的基础上，主线程现在还会区分“这批 VMC 表情是否真的会驱动骨骼”：VRM 预览骨架只有存在眼球骨时才会因 `Look*` 表情更新而重跑骨骼链路，ARP 目标骨架则不会再因 VMC 表情变化误触发整套骨骼矩阵求值。
  - `VMC blend` 现在进一步拆成“眼球 `Look*`”和“普通表情”两类脏标记；嘴型、开心、生气等普通表情更新不再触发任何预览/目标骨骼链路，只有真正影响眼球骨的 `Look*` 更新才会触发 Generic / MMD 眼球骨路径。
  - 接收线程现在也会维护 canonical VMC 表情缓冲；实时预览、目标眼球 `Look*` 求值以及 VMC Shape Key 写入会优先直接消费 canonical key，减少主线程每帧对 blend alias 的字符串遍历和重复匹配。
  - 目标层实时应用现在会在接收会话内缓存“上次已写入”的对象位移、对象旋转、骨骼位移、骨骼旋转、IK/FK 开关和 Shape Key 数值；主线程比较时优先走纯 Python 缓存，避免每帧为同一批目标通道反复回读 Blender RNA 当前值。
  - 预览层实时应用现在也会缓存“上次已写入”的预览骨架对象位移、对象旋转、预览骨骼旋转和 ARKit 调试面部 Shape Key 数值，减少 `_apply_preview_armature()` / `_apply_preview_face()` 每帧重复回读 Blender RNA。
  - 预览骨架对象位移、对象旋转、骨骼旋转和眼球旋转的缓存比较现在也直接按分量对 `mathutils` 值做比较，只在真的发生写入时才构造缓存 tuple；同时 `dirty_bone_names` 改为在主线程入口只构造一次并同时复用到预览层和目标层，继续压缩实时驱动最内层循环的临时对象分配。
  - 实时主循环里的预览层和目标层应用现在会明确返回“这帧是否真的写入了 Blender RNA”；`apply_timer()` 只在确实发生预览/目标写入，或录制计数需要更新 UI 时才触发 `VIEW_3D` redraw，不再因为跑过一轮缓存比较就无条件刷新整个 3D 视图侧栏和视口。
  - `tag_view3d_ui_redraw()` 现在会缓存当前窗口布局里的 `VIEW_3D` area 列表，只有 window/screen 结构变化或缓存失效时才重建，不再在每次 redraw 时重新遍历所有 window 和 area。
  - 目标骨架求值链路现在会在接收上下文里预编译 `source -> runtime entry / group index` 查找表；当本帧只有少量 `dirty_bone_names` 时，Generic / MMD 会直接命中对应 source entry，ARP 也只会进入受影响的 runtime group，不再每帧先扫描整套目标骨架入口再逐条跳过。
  - VRM 预览骨架链路现在也会在预览上下文里缓存 `source -> runtime entry` 索引；当本帧只有少量 `dirty_bone_names` 时，预览层不再先扫描整套中间骨架入口，而是直接命中对应 source entry 后再做旋转求值和写入。
  - ARP 目标骨架链路现在进一步去掉了“先找受影响 group、再进组判脏 source”的双层循环；当本帧只有少量 `dirty_bone_names` 时，会直接按 `ARP_RUNTIME_SOURCE_ORDER` 命中受影响的 runtime entry 顺序执行，减少 group 生成、组内 membership 判断和嵌套 Python 循环。
  - ARP runtime entry 现在还会预编译“是否有父骨”和“是否需要生成 effective pose matrix”两个布尔标记；实时求值内层循环不再每骨重复做 `parent is None` 和 `target_name in required_pose_targets` 判断，进一步收缩 `convert_local_to_pose()` 前后的分支开销。
  - 运行时上下文里已不再保留只为构建阶段服务的 `arp_required_pose_targets` 死字段；同时预览层和 Generic 目标层在按 `dirty_bone_names` 直达 entry 后，也移除了循环内重复的二次 membership 判断，继续压缩最内层 Python 分支和无用字段访问。
  - ARP 约束辅助链路现在会在求值入口先取出 `copy_transforms / child_of / copy_location` 三类约束映射，并把这些 dict 引用直接沿递归和单骨流程往下传；不再在 `_calculate_arp_target_pose_matrix()` 及其辅助函数里反复 `context.get(...)` 查表。
  - ARP 单骨求值现在会在每次 entry 循环开始先取一次当前 `raw_pose`，局部旋转和世界旋转两条分支都直接复用它；同时已移除不再使用的 `_source_local_rotation_from_raw()` 和按骨名回查的 `_source_world_rotation_from_raw()`，减少 helper 往返和重复骨骼输入查表。
  - Generic / MMD 目标骨架求值不再每帧把接收上下文里的 runtime entry 再包一层新的 `tuple(...)`；同时已移除未使用的 `_remap_local_delta_between_rest_axes()` 旧 helper，继续清理热路径中的无效对象构造和死代码噪音。
  - `apply_timer()` 在直接消费实时缓冲、未走 `raw_frame_queue` 时，不再先把 `dirty_bone_names / dirty_vmc_blend_names / dirty_arkit_blend_names` 三个脏集合各复制成一份新的 tuple；现在直接接管旧 set 引用后再把全局缓冲重置到新 set，减少主线程每帧的无意义容器复制。
  - 接收器空闲、没有任何新数据和脏状态时，`apply_timer()` 不再默认按约 10Hz 触发 3D 视图 redraw；现在只有在确实存在最近数据包、预览面板“最近数据包 xx 秒前”这类时间文案可能变化时才会低频刷新，空闲刷新频率也降到了约 1Hz。
  - ARP 目标求值现在会在接收上下文里预编译每个 source -> target entry 的静态运行时元数据，并复用 `source_pose_matrices / target_pose_matrices / desired_target_matrices` scratch dict，减少主线程每帧的字典分配、静态骨骼元数据解包和重复查找。
  - 接收线程现在会把“本批真正更新了哪些 canonical 骨骼”一起写入 `raw_frame`；预览层、Generic、MMD 和 ARP 目标骨骼求值都会按这份 `dirty_bone_names` 跳过未变化骨骼，所以当本批只有 Root/Tra 或少量骨骼更新时，不再整套重算全部骨骼旋转。
  - 目标层求值现在把“根运动更新”和“骨骼旋转更新”拆开：`body_dirty=True` 但 `dirty_bone_names` 为空时，只会更新目标根运动，不再顺带触发整套 ARP / Generic / MMD 骨骼旋转求值。
  - 仅使用中间层预览、未绑定任何目标对象时，主线程现在会在预览更新后直接早退，不再继续创建和应用空的目标 sample。
  - 预览面部与目标面部现在会缓存 source key 到 `KeyBlock` 的直接引用，不再在实时链路每帧重复 `key_blocks.get(name)`。
  - 开始录制后会缓存目标骨骼 `PoseBone` 引用和目标 Shape Key `KeyBlock` 引用，离线重建与初始采样不再反复 `pose.get()` / `key_blocks.get()`。
- 目标层统一求值链路已开始落地：
  - 已新增 `runtime/target_runtime.py`，抽出 `TargetEvaluatedSample` 数据结构。
  - 目标角色实时预览与录制采样已开始共用统一目标求值结果，不再各自直接读取当前对象状态。
  - 当前已覆盖 `Generic / ARP / MMD` 三类目标骨架运行时入口，以及目标 Shape Key 路径。
  - 接收层已开始维护原始输入帧队列；目标预览与录制可按原始帧时间戳消费队列结果。
  - 停止录制后会按原始帧时间戳离线重建目标结果并统一烘焙。
  - ARP 目标层当前已直接按原始 `bones` 求值，不再依赖预览 VRM 骨架当前 pose 作为运行时真值来源。
  - 已新增 `mapping/target_rig.py` 与 `mapping/mmd.py`，开始建立 `Generic / ARP / MMD` 目标骨架适配边界。
  - `mapping/target_rig.py` 当前已统一承接目标骨架类型选择、默认映射应用、报告清理，以及运行时驱动策略/会话准备/运行时名表分发。
  - 骨骼映射面板已加入“目标骨架类型”切换，以及 MMD 的检查 / 自动填充 / 校验入口。
- 目标骨架类型当前会影响运行时策略选择：
  - `ARP` 会启用专用路径。
  - `MMD` 已接入独立运行时入口，根位移写入 `センター` 骨；骨骼旋转已改为按起始 pose delta 和目标骨 rest 轴重映射求值，后续继续做角色级轴向调优。
- 接收启动阶段和目标骨架绑定阶段也会遵守“目标骨架类型”选择，不再默认偷偷套用 ARP 标准映射。

### 当前待修复 / 待验证

- 录制功能仍需要真实 VMC / ARKit 接收流下的长时间回放验证。
- ARP 后期编辑辅助待开发：把已录制 FK 腿部动作转换为 `c_foot_ik / c_leg_pole / c_toes_ik` 控制器关键帧，方便脚部 IK 手动修帧。
- 映射模块解耦已完成第一阶段，但 UI 结构仍偏向 ARP，后续需要继续收敛成更清晰的多目标骨架工作流。
- `VRM -> MMD` 目标骨架模块已完成基础分析入口、默认骨骼名表、内建骨骼预设、UI 辅助入口，以及独立运行时入口；当前已把根位移接到 `センター` 骨，并接入基于起始 pose delta 的专用旋转求值，后续继续做真实角色轴向调优。
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

- 当前主线：`VRM 中间层 -> Auto Rig Pro`
- 内建预设：
  - `presets/bone_maps/arp_fk_humanoid.json`
  - `presets/bone_maps/mmd_humanoid.json`
- 已完成基础边界：
  - `mapping/target_rig.py`
  - `mapping/mmd.py`
- 后续目标：
  - 继续收敛 ARP / MMD / Generic 的 UI 边界。
  - 继续调优 `VRM 中间层 -> MMD` 的轴向修正与角色差异。
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
- 运行时缓存骨引用、映射表和预览对象引用，减少每帧重复查找。
- 预览骨架与通用目标骨架会在接收上下文里预编译 source -> pose bone runtime entry，减少主线程每帧 `find_bone_name()` 和 `pose[...]` 解析。
- 预览层、ARP、MMD 和通用目标链路会在接收上下文里预计算 bone rest quaternion / inverse quaternion，并拆分 VMC 的位置 / 旋转转换，减少主线程每帧 `matrix_local.to_quaternion()`、`inverted()` 和无用的 `Vector` 分配。
- `TargetEvaluatedSample` 当前在实时链路内直接保留 `Vector / Quaternion`，只在录制缓存阶段再转换成纯数值结构，减少主线程实时预览时的 tuple <-> mathutils 来回装箱。
- 接收线程会同步维护 canonical 骨骼缓冲，主线程实时驱动不再每 tick 对当前骨骼缓冲整表规范化。
- 实时目标应用阶段开始直接复用 sample 内的 `pose_bone / key_block` 引用，减少主线程按名称重复回查 Blender RNA 集合。
- 主线程在存在原始帧队列时不再先额外复制一次当前缓冲快照，避免“先复制再丢弃”的无效分配。
- ARP 目标链路会在接收上下文内预编译 source 分组入口、IK/FK 控制骨列表和约束依赖映射，减少主线程每帧重建字典以及重复扫描 `COPY_TRANSFORMS / CHILD_OF / COPY_LOCATION` 约束。
- 目标对象起始世界分解、世界逆旋转，以及 ARP 目标骨起始平移/缩放会缓存到接收上下文里，减少主线程每帧 `decompose()`、`to_translation()`、`to_scale()` 和 `to_3x3().inverted()`。
- canonical 骨骼输入在运行时求值中会优先走直接 key 命中，避免 `get_vmc_bone_pose()` 在主链上重复构建大小写/规范化查找表。
- `TargetEvaluatedSample` 的对象和骨骼项不再冗余保存 `rotation_mode` 字符串，应用阶段也直接复用已有 `Vector / Quaternion`，减少主线程字符串分配和 mathutils 复制。
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
  mapping/                 # 通用映射、ARP / MMD 目标骨架模块、目标类型分发
  preview/                 # VRM 预览骨架、ARKit 调试面部
  ui/                      # 面板和 operator
  presets/                 # 内建 / 用户映射预设
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

近期优先级：

1. 用真实 VMC / ARKit 接收流验证录制回放，继续修复录制边界问题。
2. 继续收敛统一目标求值链路在真实接收流下的稳定性，确保目标预览和录制结果一致。
3. 继续调优 `VRM -> MMD` 目标骨架的轴向修正、手脚和手指细节。
4. 进入生产环境验证，继续 debug、性能优化和预设补全。

## 参考项目

- Fork 原项目：[VMC-Link](https://weforge.xyz/partisan/VMC-Link)
- ARKit 面部模型来源：[hinzka/52blendshapes-for-VRoid-face](https://github.com/hinzka/52blendshapes-for-VRoid-face)
- RhyLive Unity SDK：[RhythMoAI/RhyLiveSDK_Unity](https://github.com/RhythMoAI/RhyLiveSDK_Unity)
- Auto-Rig Pro：[Auto-Rig Pro](https://superhivemarket.com/products/auto-rig-pro)
