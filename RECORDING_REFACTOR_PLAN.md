# Recording Refactor Plan

## Summary

本方案用于解决当前“视口性能影响实际录制采样结果”的结构性问题，并为后续 `VRM -> MMD` 骨骼映射模块预留清晰接口。

重构后的目标不是继续在现有 `apply_timer()` 上堆补丁，而是把链路拆成两条职责明确的通道：

```text
原始输入通道
  -> 原始帧缓存
  -> VRM 骨骼预览 / ARKit 面部预览

目标输出通道
  -> 原始帧缓存
  -> 目标骨架类型适配器（ARP / MMD / Generic）
  -> 目标结果求值
  -> 映射后角色预览
  -> 录制缓存 / 离线烘焙
```

其中：

- `VRM 骨骼预览 / ARKit 面部预览` 只用于查看原始输入，不承担录制真值来源。
- `映射后角色预览` 和 `录制` 必须共享同一套“目标结果求值链路”，确保预览结果和最终录制结果一致。
- 录制不再依赖 Blender 视口当下能跑多少 fps，而应依赖“原始输入时间戳 + 统一求值器”。

## Background

当前架构存在三个根因问题：

1. 接收线程只保留最新快照，不保留逐帧历史。
2. `apply_timer()` 在 Blender 主线程里同时承担：
   - 原始预览驱动
   - 目标骨架映射驱动
   - 目标面部映射驱动
   - 录制采样
3. 录制记录的是“主线程本次成功处理到的目标层状态”，不是“原始输入流的完整逐帧结果”。

因此一旦复杂模型把视口拖慢到 `13 fps` 左右：

- 接收线程虽然可能收到更多 VMC / ARKit 包，
- 但主线程只来得及每秒处理约 `13` 次，
- 中间原始帧会被最新快照覆盖，
- 目标层预览和录制都只能拿到这 `13` 次处理结果。

这不是简单的局部性能问题，而是“实时预览调度”和“录制真值采样”没有解耦。

## Goals

### 1. 原始预览链路独立

保留并强化现有中间层预览职责：

- `vmc_link_preview_armature`
- `vmc_link_preview_face_object`

它们只表达“当前收到的原始输入长什么样”，不参与最终录制真值，不受目标映射模块影响。

### 2. 目标预览与录制共用同一求值链路

目标角色预览和最终录制必须共用：

- 同一个原始输入来源
- 同一套目标骨架适配逻辑
- 同一套目标结果求值逻辑

这样才能保证：

- 预览看到的目标姿态与录制回放结果一致
- ARP 和后续 MMD 不会各自维护两套不同运行时逻辑

### 3. 录制真值不再受视口 fps 影响

录制结果应由：

- 原始输入时间戳
- Blender 工程 fps
- 统一目标求值器

共同决定，而不是由 Blender 当前视口是否卡顿决定。

### 4. 为 MMD 目标骨架模块预留正式接口

ARP 不再继续作为通用逻辑里的特例堆叠，后续 MMD 目标骨架应能按同样接口接入。

## Non-Goals

本轮重构不追求：

- 把 `bpy` / RNA 写入移动到后台线程
- 在后台线程直接驱动 Blender 对象
- 实现 ARP FK 动作自动转 IK 控制器
- 解决所有角色特定调优问题

原因很明确：

- Blender 数据写入仍必须留在主线程
- 本轮主目标是录制架构、链路边界和可扩展性

## Target Architecture

## 1. 数据层分离

新增三类运行时数据对象概念：

### A. 原始输入帧 `RawMotionFrame`

表示一次完整输入采样，包含：

- `timestamp`
- `sequence_id`
- `root`
- `waist`
- `bones`
- `vmc_blends`
- `arkit_blends`
- `face_source`

要求：

- 接收线程不再只覆盖单份 `bone_buf / blend_buf`
- 应按时间顺序把 `RawMotionFrame` 推入有界队列或环形缓冲

### B. 目标求值结果 `TargetEvaluatedSample`

表示某一原始输入帧经过目标映射后的结果，包含：

- 对象级 root motion
- 目标骨骼 local/basis 旋转与位置
- 目标 Shape Key 值
- ARP/MMD 专属附加通道
  - 例如 `ik_fk_switch`
  - 后续可扩展 MMD 附加控制量

这个结构应当与 Blender 对象写入解耦，保持纯数据。

### C. 录制会话 `RecordingSession`

表示一次录制状态，至少包含：

- `record_start_frame`
- `record_end_frame`
- `project_fps`
- `raw_frame_store`
- `transition_config`
- `interpolation_config`
- `bake_mode`
- `captured_initial_target_state`

重点：

- 录制时缓存的核心应是原始帧或可重算的求值输入，而不是只缓存“本次主线程恰好算到的目标姿态”

## 2. 两条消费链路

### A. 原始预览消费链路

```text
RawMotionFrame 队列
  -> 取最新可用帧
  -> 原始预览驱动器
  -> vmc_link_preview_armature / vmc_link_preview_face_object
```

特点：

- 允许只显示最新帧
- 允许掉帧
- 优先保证调试观察体验
- 不承担录制真值职责

### B. 目标预览 / 录制统一消费链路

```text
RawMotionFrame
  -> TargetRigAdapter
  -> TargetEvaluationEngine
  -> TargetEvaluatedSample
  -> 目标角色预览应用
  -> 录制缓存 / 停止后烘焙
```

重点：

- `目标角色预览` 和 `录制` 必须调用同一个 `TargetEvaluationEngine`
- 不能再出现：
  - 预览走一套 ARP 实时驱动逻辑
  - 录制走另一套“读取当前对象状态”的逻辑

否则后续仍会继续漂移

## 3. 录制模式重构

建议明确分成两层：

### A. 实时目标预览

职责：

- 让用户看到映射后角色当下结果
- 允许掉帧
- 允许按性能策略降频

它服务“看起来正确”。

### B. 录制真值采集

职责：

- 保留原始输入时间序列
- 与视口 fps 解耦
- 停止录制后统一按工程帧烘焙

它服务“最终结果正确”。

### 推荐默认策略

继续采用：

- 录制时不实时写 Action
- 停止录制后统一烘焙

但把缓存内容从“主线程已求值结果”升级为：

- 原始输入帧序列
- 或者至少是“可重算”的规范化输入帧序列

停止录制后：

1. 以 `record_start_frame` 为锚点
2. 用时间戳换算工程帧号
3. 按统一求值器得到每个工程帧的目标结果
4. 批量烘焙到 Action

## 4. 目标骨架类型适配接口

为 ARP / MMD / Generic 新增统一适配接口。

建议抽象为：

```text
TargetRigAdapter
  detect_target(scene, armature) -> analysis
  build_runtime_context(scene, armature, preview_armature) -> context
  evaluate_frame(raw_frame, context) -> TargetEvaluatedSample
  apply_sample_to_preview(sample, context) -> changed_channels
  collect_record_channels(scene, context) -> channel_specs
  capture_initial_state(scene, context) -> snapshot
  restore_initial_state(scene, context, snapshot)
```

当前实现映射关系：

- `mapping/arp.py`
  - 迁移成 `ARPAdapter`
- 新增 `mapping/mmd.py`
  - 作为 `MMDAdapter`
- 通用骨架路径
  - 保留 `GenericAdapter`

### 这样拆的好处

- ARP 不再污染通用录制主循环
- MMD 可以按同一接口接入
- UI 切换目标骨架类型后，运行时只切换 adapter

## Module Plan

建议按现有仓库边界扩展，而不是回退到单文件：

```text
core/
  state.py
    - 原始帧队列状态
    - 录制会话状态

runtime/
  network.py
    - 收包
    - RawMotionFrame 组帧
    - 原始帧队列写入

  preview_runtime.py          # 可新增
    - 原始预览消费

  target_runtime.py           # 可新增
    - 目标求值
    - 目标预览应用

  recording_runtime.py        # 可新增
    - 录制会话管理
    - 原始帧记录
    - 停止后离线烘焙

mapping/
  mapper.py
    - 通用映射查找

  target_adapter_base.py      # 可新增
    - 适配器接口定义

  arp.py
    - ARPAdapter

  mmd.py
    - MMDAdapter
```

如果不想一次拆太多文件，最小版本也应至少在逻辑上分离成：

- 原始预览函数组
- 目标求值函数组
- 录制会话/烘焙函数组

## Recommended Migration Path

### Phase A. 先抽出统一目标求值器

先不改录制格式，先把“ARP / Generic 实时目标驱动”从 `apply_timer()` 中抽出纯求值逻辑：

- 输入：`RawMotionFrame + TargetRigAdapterContext`
- 输出：`TargetEvaluatedSample`

这样可先解决：

- 目标预览和录制当前是两套语义的问题

### Phase B. 接收层从单快照改为队列

把当前：

- `root_buf`
- `waist_buf`
- `bone_buf`
- `blend_buf`
- `arkit_blend_buf`

这组“最新快照缓存”升级为：

- 最新快照缓存
- 原始帧环形缓冲

最新快照继续服务原始预览；
原始帧环形缓冲服务目标预览和录制。

### Phase C. 录制改为原始帧存档 + 停止后离线烘焙

这是根治视口 fps 影响录制结果的关键步骤。

录制期间：

- 只把 `RawMotionFrame` 记入录制会话
- 不再把“当前对象姿态”当成录制真值

停止录制时：

- 离线重放原始帧
- 调统一求值器
- 烘焙目标骨架和目标面部 Action

### Phase D. 目标骨架类型切换与 MMD 接口接入

在目标求值器稳定后，再把 ARP 从通用 UI 中剥离：

- `GENERIC`
- `ARP`
- `MMD`

后续新增 MMD 时只需要：

1. 补 `MMDAdapter`
2. 补检测 / 自动填充 / 校验 / 预设
3. 接到统一目标求值链路

## UI / Workflow Changes

本轮重构建议同步明确 UI 语义：

### 原始预览区

保留现有中间层面板：

- 创建 / 重建 VRM 预览骨架
- 导入 ARKit 调试面部
- 原始输入数据预览

它只表达：

- “输入是否正常”
- “原始骨骼和面部是否正常”

### 目标预览区

目标对象区表达：

- 当前目标骨架类型
- 当前目标求值状态
- 当前目标预览是否启用

这里的“预览”实际就是：

- 统一目标求值器的实时显示结果

### 录制区

录制区表达：

- 当前录制是否记录原始帧
- 当前录制是否启用起始过渡
- 当前录制是否启用采样间补帧
- 当前录制输出范围

并在说明文案上明确：

- 原始预览掉帧不等于录制丢帧
- 目标预览与录制共享同一套目标求值逻辑

## Validation Plan

### 架构级验证

1. 关闭复杂网格显示，让接收线程维持高频输入。
2. 主线程人为降速到低于输入频率。
3. 确认：
   - 原始帧记录数接近真实输入帧数
   - 目标预览可能掉帧
   - 停止录制后烘焙出来的 Action 仍保持完整帧数

### 功能级验证

1. 仅原始预览
- VRM 骨骼预览和 ARKit 面部预览能继续稳定工作。

2. ARP 目标预览
- 目标角色实时预览与最终录制回放一致。

3. ARP 录制
- 复杂模型低视口 fps 下，录制帧数不再随视口 fps 明显下降。

4. MMD 接口预留
- 在未实现 MMD 运行时前，至少能完成：
  - 目标骨架类型切换
  - MMD adapter 占位
  - 不影响 ARP 现有路径

## Risks

### 1. 纯粹保存原始包会放大后处理成本

离线烘焙阶段会更重，但这是可接受代价，因为它不再与实时视口交互抢主线程。

### 2. 预览结果与录制结果可能出现时序错觉

如果目标预览为流畅性而丢帧，而录制离线烘焙保留更多真实帧，用户可能感知到“录出来比实时看见的更细”。

这不是 bug，而是职责分离后的自然结果，需要在 UI 文案中说明。

### 3. ARP 现有逻辑拆分时有回归风险

尤其是：

- `c_traj` root motion
- IK/FK 切换恢复
- 手指 local basis delta
- 拇指 rest axis remap
- 脚 / 脚趾 delta rotation

这些都必须在 `ARPAdapter` 抽象后逐项回归验证。

## Recommended Decision

建议采用以下正式方向：

1. 保留当前 VRM / ARKit 中间层原始预览链路。
2. 新建“统一目标求值链路”，让目标预览与录制共用同一求值器。
3. 录制改为“原始帧存档 + 停止后离线烘焙”。
4. 引入 `TargetRigAdapter` 接口，把 ARP 从通用路径中抽离。
5. 以同一接口为后续 `VRM -> MMD` 骨骼映射模块预留入口。

按这个方向推进，才能同时解决：

- 视口 fps 影响录制结果
- ARP 路径持续堆叠
- MMD 后续接入缺少边界

## Immediate Next Step

下一步建议不是直接重写全部录制代码，而是先做一个最小可落地版本：

1. 抽出 `TargetEvaluatedSample` 数据结构。
2. 抽出 ARP / Generic 统一目标求值函数。
3. 把当前录制从“记录当前对象状态”改成“记录统一求值器输出”。
4. 再把接收层从单快照升级为原始帧队列。
5. 最后再切换到“停止后离线烘焙原始帧”。

这样风险最可控，也最符合当前项目已经积累的代码状态。
