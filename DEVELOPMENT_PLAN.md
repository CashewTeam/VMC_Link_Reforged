# Development Plan

## 目标摘要

当前项目的下一阶段目标不是继续向单文件里堆功能，而是把现有实时动捕链路整理成可长期维护、可测试、可扩展的结构。

核心方向：

1. 模块化现有插件
2. 固化 `Create Dummy Armature` 生成的 `VRM` 风格骨架为固定中间层
3. 固化 `ARKit 52 Key` 为固定脸部中间层
4. 以 `Auto Rig Pro` 人形骨架为当前唯一优先适配骨架
5. 以 `MMD` 标准 Shape Key 为当前唯一优先适配面部标准
6. 参考 `Auto Rig Pro` 的 remap/humanoid/preset 设计，建立本项目自己的重映射模块

## 当前状态

项目已经具备这些基础能力：

- VMC 身体数据接收
- RhyLive ARKit `/Face` 数据接收
- 根位移与骨骼旋转实时驱动
- VMC / ARKit 表情实时驱动
- 原始数据预览
- 三套映射面板
- 三套 JSON 映射预设
- 固定 `VRM Intermediate Rig`
- `Intermediate Layers` 状态面板

并且已经完成当前阶段的两项基础整理：

- 路线一：模块化改造
- 路线二：中间层固化

当前代码不再集中在单一文件中，运行时逻辑已拆分为：

- `constants.py`
- `properties.py`
- `network.py`
- `runtime.py`
- `mapping.py`
- `presets.py`
- `dummy_vrm.py`
- `ui_main.py`
- `ui_preview.py`
- `ui_mapping.py`
- `ui_intermediate.py`

## 路线一：模块化改造（已完成当前阶段）

### 目标

降低单文件复杂度，明确运行时数据流、UI、映射、预设、测试骨架之间的边界。

### 建议拆分

建议逐步拆成以下模块：

- `network.py`
  - socket 生命周期
  - VMC / ARKit dispatcher
  - 包接收与原始缓存
- `runtime.py`
  - apply timer
  - 根位移、骨骼旋转、表情驱动
  - 录制
- `mapping.py`
  - 骨骼别名
  - VMC blend 别名
  - ARKit blend 匹配
  - 映射缓存重建
- `presets.py`
  - 三套 JSON 预设
  - 目录扫描
  - 导入导出
- `dummy_vrm.py`
  - 创建固定中间层骨架
  - 骨架结构常量
- `ui_main.py`
  - 主面板
- `ui_preview.py`
  - 数据预览面板
- `ui_mapping.py`
  - 三套映射面板
- `properties.py`
  - Scene 属性注册与反注册
- `constants.py`
  - ARKit 52 Key
  - 默认端口
  - face source
  - 其他枚举常量

### 执行原则

- 先抽常量和 helper
- 再抽纯逻辑模块
- 最后拆 UI 和注册
- 每一步都保持功能可运行，不做一次性大重写

## 路线二：固化 VRM 中间层（已完成当前阶段）

### 目标

把当前 `Create Dummy Armature` 从“测试工具”升级为“标准中间层骨架”。

### 设计方向

身体输入链路：

`VMC / ARKit / 其他来源 -> VRM 中间层`

身体输出链路：

`VRM 中间层 -> Auto Rig Pro 目标骨架`

脸部输入链路：

`RhyLive /Face -> ARKit 52 Key 中间层`

脸部输出链路：

`ARKit 52 Key 中间层 -> MMD Shape Key / 目标面部`

### 为什么要这样做

- 当前 VMC 数据天然更接近 VRM / humanoid 命名
- 当前 RhyLive 面部数据天然就是 ARKit 52 Key 语义
- 中间层固定后，数据接收与目标模型适配可以解耦
- 调试时可以先验证中间层是否正确，再验证目标重映射是否正确
- 新增其他目标骨架时，只需要做“中间层 -> 目标”的适配

### 需要补强的能力

- 固定的中间层骨架定义文档
- 固定的 ARKit 52 Key 面部中间层文档
- 可重复创建、可复用、可检测的中间层对象
- 明确区分：
  - 接收骨架
  - 中间层骨架
  - 目标骨架
- 明确区分：
  - ARKit 原始数据
  - ARKit 52 Key 中间层
  - 目标 Shape Key 标准
- 为中间层增加更直接的调试状态显示

### 当前已落地

- `main.py` 已收敛为装配层
- `Create Dummy Armature` 已升级为面板中的 `Create Intermediate Rig`
- 新增中间层识别逻辑
- 新增中间层重建逻辑
- 新增 `Intermediate Layers` 面板
- 新增骨骼覆盖率、缺失骨骼、ARKit 覆盖率状态显示

## 路线三：当前适配目标收敛

### 当前只做

- 骨架目标：`Auto Rig Pro` 生成人形骨架
- 面部目标：`MMD` 标准 Shape Key
- 面部中间层：`ARKit 52 Key`

### 当前不做

- 通用非人形骨架适配
- 多套骨架标准并行维护
- 多套面部标准并行自动适配

### 原则

当前阶段宁可把：

- `VRM 中间层 -> Auto Rig Pro`
- `ARKit 52 Key -> MMD Shape Key`
- `VMC Blend -> MMD Shape Key`

做深、做稳定、做可保存、做可调试，

也不要过早扩到更多标准，导致系统边界失控。

## 路线四：重映射模块设计

## 参考对象

本机 Auto Rig Pro 目录中存在明确可参考的结构：

- 扩展注册入口会单独注册 `auto_rig_remap`
- 存在独立 remap 模块：
  - `src/auto_rig_remap.py`
- 存在 humanoid rig 相关操作：
  - `src/auto_rig_ge.py`
- 存在映射预设导入导出概念：
  - import preset
  - export preset
  - custom preset path

参考目录：

`'/Users/con11/Library/Application Support/Blender/5.1/extensions/user_default/auto_rig_pro_master'`

### 从 Auto Rig Pro 借鉴的不是“具体实现”，而是这些产品能力

- 重映射模块独立存在
- 有明确的 source rig / target rig 概念
- 支持预设导入导出
- 支持 built-in preset + custom preset
- 支持 rest pose / 调整 / 同步选择 / 验证流程
- humanoid 作为统一抽象层

### 本项目建议新增的重映射能力

第一阶段：

- `VRM 中间层骨骼 -> Auto Rig Pro 骨骼` 映射表
- `VMC Blend -> MMD Shape Key` 映射表
- `ARKit 52 Key -> MMD Shape Key` 映射表
- 针对 Auto Rig Pro 的 built-in 骨骼预设
- 针对 MMD 面部的 built-in 表情预设
- 提供一个固定 ARKit 调试面部模型作为面部链路基准

第二阶段：

- 中间层到目标骨架的批量自动匹配
- 映射完整性检查
- 缺失骨骼 / 缺失 Shape Key 提示
- rest pose / 坐标轴 / 根节点偏移调试工具

第三阶段：

- 专用 ARP 适配导向 UI
- 一键创建：
  - 中间层
  - ARP 重映射
  - MMD 面部映射

## 近期开发顺序建议

### Phase 1：结构整理（已完成）

- 抽离常量、属性、网络、映射、UI
- 保持现有功能不变
- 为后续中间层重映射预留模块边界

### Phase 2：中间层固化（已完成）

- 固化 Dummy Armature 的骨架定义
- 明确它是 `VRM Intermediate Rig`
- 固化 `ARKit 52 Key` 为固定脸部中间层
- 固化 [Arkitface.blend](./assets/Arkitface.blend) 为 ARKit 面部调试基准模型
- 增加识别与重建逻辑
- 为中间层增加专门面板与状态显示

### Phase 3：Auto Rig Pro 骨骼适配

- 新增 `VRM Intermediate -> Auto Rig Pro` 重映射表
- 先做手动映射 + JSON 预设
- 再做 Auto Rig Pro built-in preset
- 增加映射检查和缺失提示

### Phase 4：MMD 面部适配

- 明确 MMD 目标 Shape Key 名单
- 分别建立：
  - `VMC -> MMD`
  - `ARKit 52 Key -> MMD`
- 提供 built-in MMD 面部预设

### Phase 5：调试与验证

- 中间层驱动可视化
- ARKit 52 Key 中间层预览状态
- 当前根位移来源显示
- 当前脸部来源显示
- 当前使用的映射预设显示
- 缺失映射诊断报告

## 验收标准

当以下目标都满足时，可认为当前阶段开发目标达成：

- 项目完成模块化拆分，主逻辑不再集中于单一文件
- `Create Dummy Armature` 被正式定义为固定中间层骨架
- `VMC / ARKit -> VRM 中间层` 链路稳定
- `RhyLive /Face -> ARKit 52 Key 中间层` 链路稳定
- `VRM 中间层 -> Auto Rig Pro` 骨骼适配可配置、可保存、可复用
- `VMC / ARKit 52 Key -> MMD Shape Key` 面部适配可配置、可保存、可复用
- 所有核心映射均支持预设
- 调试时可以快速定位问题发生在：
  - 数据源
  - 中间层
  - 骨骼重映射
  - 面部重映射

## 当前结论

项目已经跨过“能收数据、能预览、能基本驱动”的阶段，并完成了路线一、路线二的基础工程收敛。

下一步最重要的不是继续横向加来源，而是围绕：

- Auto Rig Pro 骨骼
- MMD 面部
- 可维护的重映射模块

把现有能力整理成一条稳定的生产级开发路线。
