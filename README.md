# VMC Link

面向 Blender 的实时动捕接收插件。

当前版本：`0.14.2`

项目当前重点不是做“任意来源一键适配任意骨架”，而是先把一条稳定、可调试、可扩展的实时驱动链路固化下来。现在这条链路已经明确拆成两部分：

- 预览层：
  - `VRM` 风格预览骨架
  - `ARKit 52 Key` 预览面部
  - 始终按原始接收数据直接驱动
  - 不受手动映射和映射预设影响
- 目标层：
  - 用户指定的目标骨架与目标面部
  - 继续通过骨骼映射 / VMC 表情映射 / ARKit 表情映射驱动
  - 受 `实时驱动目标对象` 开关控制

## 当前能力

- 接收 `VMC` 数据：
  - `/VMC/Ext/Root/Pos`
  - `/VMC/Ext/Tra/Pos`
  - `/VMC/Ext/Bone/Pos`
  - `/VMC/Ext/Blend/Val`
- 接收 `RhyLive ARKit` 数据：
  - `/Face`
- 支持两种面部来源：
  - `VMC`
  - `RhyLive ARKit`
- 支持三套映射与 JSON 预设：
  - `骨骼映射`
  - `VMC 表情映射`
  - `ARKit 表情映射`
- 支持 `Auto Rig Pro` 骨架辅助工具：
  - `检查 ARP 骨架`
  - `应用标准 ARP 映射`
  - `校验当前映射`
  - 内建 `arp_fk_humanoid.json` 骨骼预设
  - 仅驱动标准 `c_*` FK 控制骨，不写入 ARP 输出骨
  - 接收时自动切换四肢 FK，停止时恢复原 IK/FK 状态
  - 基于接收开始时姿态进行矩阵空间重定向
  - 逐骨校准 VRM T Pose 与 ARP A Pose，只保留目标骨 roll 差异
  - 手指控制骨使用局部 basis delta 驱动，避免 ARP 第一节手指父级结构导致无输入时自转
  - 拇指额外按 VRM/ARP rest 轴转换局部旋转，避免 VRM 内弯映射成 ARP 外翻
  - OSC 收包与解码运行在后台线程，Blender 数据写入保留在主线程
  - ARP 目标使用缓存骨引用和局部旋转批量提交，不主动强制依赖图求值
- 支持固定中间层预览对象：
  - `创建/重建 VRM 预览骨架`
  - `按目标骨架校准长度`
  - 校准会先重建标准 VRM T Pose，再按左右大腿根平均点到上臂根部的肩高整体缩放，并只微调四肢主链长度
  - 缩放后会对齐预览骨架与目标骨架的骨盆点，避免对象原点缩放导致整体下移
  - 缩放和长度编辑提交后都会刷新并重新对齐骨盆点，避免矩阵延迟导致校准位置下沉
  - 最终位置偏移会一次性烘焙进预览骨架数据，预览对象 `location` 会归零，避免接收根运动时覆盖校准位置
  - 位置烘焙后会强制刷新 armature pose 数据，并校验对象位置归零与骨盆点对齐，失败时直接报错
  - 手掌按手腕到四根主指指根平均距离校准，手指各节按 ARP 对应控制骨长度校准
  - `导入 ARKit 调试面部`
- 支持预览层与目标层解耦：
  - 预览层继续实时更新
  - 可单独关闭目标层实时写入
- 支持 `固定角色到中心`：
  - 勾选时忽略 VMC 根位移，角色固定在场景中心/开始位置
  - 取消勾选后预览骨架和目标骨架都会按 VMC `Root/Pos`、`Tra/Pos` 或 `Hips` 位置移动
  - ARP 目标骨架取消勾选后只把位移写入 `c_traj.location`，保持 `rig` 对象和 `c_pos` 默认不动，避免只有 Armature modifier 绑定的网格与骨架脱节
  - 当 `Root/Pos` 或 `Tra/Pos` 存在但位置为零时，会自动回退到 `Bone/Pos:Hips`，避免零 Root 挡住真实角色位移
- 支持录制目标层关键帧
- 支持中文化 UI

## ARP 性能策略

- 后台线程只负责 UDP 收包、OSC 解码和更新纯 Python 缓冲，不访问 Blender RNA。
- Blender 主线程只复制最新一帧缓冲并写入预览对象和目标对象。
- VRM 预览骨架的姿态矩阵使用 `Bone.convert_local_to_pose()` 递归计算，不为读取预览结果强制刷新依赖图。
- ARP 映射、骨引用和 T Pose / A Pose 校准结果在接收会话开始时缓存。
- 目标控制骨直接写局部旋转，并跳过未变化的骨骼。
- 插件运行时不调用 `view_layer.update()`；视口依赖图由 Blender 按绘制节奏统一求值。

## 当前运行方式

### 1. 身体链路

身体部分始终使用 `VMC` 数据。

- 预览层根位移优先级：
  1. `Root/Pos`
  2. `Tra/Pos`
  3. `Bone/Pos` 中的 `Hips`
- 目标层根运动：
  - `固定角色到中心` 开启时忽略位置位移，目标对象保持在接收开始位置
  - `固定角色到中心` 关闭时，位置来源优先级为 `Root/Pos`、`Tra/Pos`、`Bone/Pos:Hips`
  - 若 `Root/Pos` 或 `Tra/Pos` 的位置为零且存在 `Hips`，会使用 `Hips` 作为位移来源
  - 普通目标骨架以接收首帧为基准叠加到目标对象开始位置
  - ARP 目标骨架以接收首帧为基准叠加到 `c_traj.location`，不移动 `rig` 对象，不写入 `c_pos`
  - 使用 `Bone/Pos:Hips` 时只使用位置，不把 Hips 旋转写成对象根旋转
- 预览骨架：
  - 直接按原始 VMC 骨骼名和内建别名匹配驱动
  - 不读取 Scene 上的手动映射 override
  - schema 2 增加独立 `UpperChest`，避免与 `Chest` 重复写入
- 目标骨架：
  - 使用手动映射、自动别名匹配和缓存映射驱动
  - 检测到 ARP 时自动应用严格标准控制骨映射

### 2. 面部链路

面部来源由 `面部来源` 决定：

- `VMC`
  - 使用 `/VMC/Ext/Blend/Val`
  - 驱动目标面部时读取 `VMC 表情映射`
  - 当前作为兼容与备选链路保留
- `RhyLive ARKit`
  - 使用 `/Face`
  - 按固定 `ARKit 52 Key` 顺序解析
  - 预览面部直接按 ARKit Key 同名或规范化匹配驱动
  - 驱动目标面部时读取 `ARKit 表情映射`
  - 后续面部适配的主线将优先围绕 `ARKit -> MMD` 展开

### 3. 预览层与目标层

- `实时驱动目标对象` 开启时：
  - 预览层更新
  - 目标层更新
- `实时驱动目标对象` 关闭时：
  - 预览层继续更新
  - 目标层停止写入

这意味着当前项目的调试顺序已经可以稳定分成两步：

1. 先验证预览层是否正确接收和解释原始数据
2. 再验证目标层映射是否正确

## 当前 UI 结构

### 主面板

主面板标题：`接收器配置`

主面板当前负责：

- 启停接收器
- 开始 / 停止录制
- 接收地址与端口配置
- `面部来源`
- `应用频率 (Hz)`
- `实时驱动目标对象`
- 目标骨架 / 目标面部绑定
- `重建目标映射`

### 中间层预览面板

`中间层预览` 面板当前是核心调试入口，负责：

- `VRM 预览骨架`
  - 创建 / 重建标准预览骨架
  - 显示必需骨骼覆盖率
  - 显示手指骨骼覆盖率
  - 显示根位移来源
  - 显示缺失骨骼
- `ARKit 52-Key 预览面部`
  - 导入调试面部
  - 显示当前面部来源
  - 显示 ARKit 键覆盖率
  - 显示调试资产状态

### 数据预览面板

`数据预览` 面板当前位于最底部，并且默认折叠。

- 面板内左右并排显示：
  - `VMC 原始流`
  - `RhyLive OSC /Face`
- 作为二级调试功能使用
- 不再占据主面板主要空间

## 预览对象与集合

插件当前会管理一套专用集合结构：

- `VMC_Link`
  - 插件专用集合
  - 预览骨架与 ARKit 调试集合都放在这里
- `ArkitFace`
  - 从 `assets/Arkitface.blend` 中追加导入的源集合
  - 会被挂到 `VMC_Link` 下

### VRM 预览骨架

- 骨架对象名固定为 `VMC_TEST_DUMMY`
- 创建和重建都只操作 `VMC_Link` 集合里的该预览骨架
- 不会再全局搜索和删除其他相似骨架

### ARKit 调试面部

- 资产来源：
  - `assets/Arkitface.blend`
- 只会追加其中名为 `ArkitFace` 的集合
- 不会把该 `.blend` 里的其他无关内容一起导入

## Scene 属性语义

### 目标层对象

- `vmc_link_armature`
  - 映射后的目标骨架
- `vmc_link_face_object`
  - 映射后的目标面部

### 预览层对象

- `vmc_link_preview_armature`
  - VRM 预览骨架
- `vmc_link_preview_face_object`
  - ARKit 预览面部

### 兼容迁移

为兼容老场景，插件在注册时和文件加载后会尝试自动迁移：

- 如果旧的目标骨架槽里放的是中间层骨架：
  - 自动迁移到 `vmc_link_preview_armature`
- 如果旧的目标面部槽里放的是 ARKit 调试面部：
  - 自动迁移到 `vmc_link_preview_face_object`

## 映射与预设

### 三类映射

- 骨骼映射：
  - `VMC Bone Name -> Blender Bone Name`
- VMC 表情映射：
  - `VMC Blend Name -> Blender Shape Key Name`
- ARKit 表情映射：
  - `ARKit Key -> Blender Shape Key Name`

### 预设目录

```text
presets/
  bone_maps/
  vmc_blend_maps/
  arkit_blend_maps/
```

### JSON 结构

```json
{
  "version": 1,
  "mapping_kind": "bone",
  "entries": {
    "Hips": "c_hips.x"
  }
}
```

`mapping_kind` 可取：

- `bone`
- `vmc_blend`
- `arkit_blend`

## 当前性能状态

近期已经对实时预览链路做过一轮性能优化：

- 不再每个接收周期强制重绘整个 `VIEW_3D`
- UI 刷新做了节流，数据预览默认折叠
- 预览骨架和预览面部增加独立缓存，避免每帧重复做名字匹配
- UDP 收包与 OSC 解码已移到后台线程
- 主线程只复制最新一帧数据，并执行必要的 Blender RNA 写入
- 主线程取样前会等待极短的接收静默窗口，降低半帧骨骼数据被应用到目标层的概率
- ARP 运行时缓存骨引用、映射表和 T Pose / A Pose 校准结果
- ARP 目标骨架改为局部旋转提交，跳过未变化骨骼
- ARP 目标层会先过滤源姿态的小角度高频变化，再对目标骨做自适应滤波，大角度动作保持直接跟随
- ARP 手指、脚和脚趾使用相对起始姿态的 delta 旋转，避免直接套用 VRM 源骨绝对轴向
- 每帧运行时不主动调用 `view_layer.update()`，避免插件额外强制依赖图求值

当前如果视口性能仍有瓶颈，优先需要继续排查的是：

- 高骨骼数目标骨架的实时驱动成本
- 大量 Shape Key 目标面部的实时写入成本
- 数据预览面板展开时的文本绘制成本
- 是否需要给目标层增加独立的驱动频率上限，避免目标骨架每个接收帧都触发完整姿态求值

## 当前边界

- 当前预览层只管理一套标准 VRM 预览骨架和一套 ARKit 调试面部
- 当前预览面部只在 `面部来源 = RhyLive ARKit` 时实时驱动
- 当前还没有内建：
  - `ARKit 52 Key -> MMD` 专用预设
  - 面向 `ARKit -> MMD` 的完整专用工作流
  - 更高级的批量自动重映射工具

## 当前代码结构

插件目录已经从根目录单文件模块调整为分层包结构：

```text
vmc_link/
  __init__.py
  blender_manifest.toml
  assets/
  core/
  mapping/
  presets/
  preview/
  runtime/
  ui/
  wheels/
```

主要职责划分：

- `__init__.py`
  - Blender 插件入口、版本信息、依赖检查和主面板壳
- `core/bootstrap.py`
  - 模块装配、注册 / 反注册、UI 委托
- `core/constants.py`
  - 默认值、枚举、ARKit 52 Key、集合名、骨骼别名
- `core/helpers.py`
  - 名称规范化、矩阵 / 四元数工具、Shape Key 工具
- `core/state.py`
  - 运行时缓存、接收线程句柄、线程锁、调试状态
- `runtime/properties.py`
  - Scene 属性注册、兼容迁移、load_post 迁移钩子
- `runtime/network.py`
  - UDP 接收器、OSC dispatcher、后台收包线程、原始缓存更新
- `runtime/driver.py`
  - 接收定时器、预览层驱动、目标层驱动、录制、暂停 / 停止恢复
- `mapping/mapper.py`
  - 通用骨骼 / 表情映射、别名匹配、缓存重建
- `mapping/arp.py`
  - Auto Rig Pro 检测、标准 FK 映射、校验、运行时映射生成、T/A 姿态校准
- `mapping/preset_store.py`
  - JSON 预设扫描、加载、保存
- `preview/dummy_vrm.py`
  - VRM 预览骨架创建 / 重建、ARKit 调试面部导入、`VMC_Link` 集合管理
- `ui/main_panel.py`
  - 接收器配置、暂停 / 继续 / 停止、目标对象绑定
- `ui/intermediate_panel.py`
  - 中间层预览对象状态、VRM / ARKit 创建入口
- `ui/mapping_panel.py`
  - 骨骼映射、表情映射、ARP 辅助区、预设入口
- `ui/preview_panel.py`
  - 底部折叠式 VMC / ARKit 数据预览
- `ui/operators.py`
  - UI 操作符、预设操作、ARP 操作、中间层操作

## 下一阶段重点

当前阶段已经把：

- 接收
- 预览
- 目标驱动
- 中间层对象管理
- 预设
- 基础性能问题

收敛成了稳定的基础框架。

下一阶段的重点应转向：

- `VRM 中间层 -> Auto Rig Pro` 的生产级调试与性能收敛
- `ARKit 52 Key -> MMD Shape Key` 面部适配
- 面向实际目标模型的 built-in 预设
- 映射完整性诊断与调试工具

其中：

- `ARKit -> MMD` 是后续主要面部开发方向
- `VMC -> 形态键映射` 继续保留，但作为备选方案，不作为后续主线

## 参考项目

- Fork 原项目：
  - [VMC-Link](https://weforge.xyz/partisan/VMC-Link)
- ARKit 面部模型来源：
  - [hinzka/52blendshapes-for-VRoid-face](https://github.com/hinzka/52blendshapes-for-VRoid-face)
- RhyLive Unity SDK：
  - [RhythMoAI/RhyLiveSDK_Unity](https://github.com/RhythMoAI/RhyLiveSDK_Unity)
- Auto-Rig Pro：
  - [Auto-Rig Pro](https://superhivemarket.com/products/auto-rig-pro)
