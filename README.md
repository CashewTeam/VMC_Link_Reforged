# VMC_Link_Reforged

面向 Blender 的实时 VMC / RhyLive ARKit 动捕接收、预览、目标映射与录制插件。

当前阶段：`Beta`

当前版本：`1.0.6`

## 插件能做什么

- 接收 VMC 身体数据与 RhyLive ARKit 面部数据
- 实时显示 VRM 骨架预览与 ARKit 调试面部预览
- 将中间层数据映射到 `VRM / 通用骨架`、`Auto Rig Pro`、`MMD` 目标骨架
- 将表情映射到目标 Shape Key
- 录制骨骼与形态键，并在停止后离线烘焙到 Blender Action

## 当前状态

当前版本已经进入 `Beta`：

- `VRM / 通用骨架` 目标映射可用
- `Auto Rig Pro` 映射链路可用，后续以生产角色调优为主
- `MMD` 骨架与形态键适配已落地，后续以细节调试和真实角色验证为主
- 录制链路可用，支持帧范围、起始姿态过渡、范围清帧、离线烘焙

当前主要剩余工作：

- FK 录制结果到 IK 控制器的后处理转换
- 不同生产角色、长时录制与复杂场景下的继续调试和收敛

优化与修复过程文档已归档到 [docs/OPTIMIZATION_AND_FIX_HISTORY.md](./docs/OPTIMIZATION_AND_FIX_HISTORY.md)。

## 安装

1. 从发布包安装 Blender 扩展 zip。
2. 在 Blender 中打开 `编辑 > 偏好设置 > 扩展`。
3. 选择“从磁盘安装”，安装 `VMC_Link_Reforged_Beta_<版本号>_For5.1.zip`。
4. 安装后在 `3D 视图 > 侧边栏 > VMC Link` 打开面板。

## 快速开始

### 1. 启动接收

在主面板中：

- 设置接收地址、端口、面部来源和应用频率
- 点击 `开始接收`
- 如需临时停流，使用 `暂停接收`
- 如需结束并恢复到接收前状态，使用 `停止接收`

### 2. 创建预览层

在 `中间层预览` 面板中：

- 点击 `创建/重建 VRM 预览骨架`
- 点击 `导入 ARKit 调试面部`
- 如有目标骨架，可执行预览骨架长度校准

预览层只用于查看原始输入，不受映射设置影响。

### 3. 绑定目标对象

在 `目标对象` 区域中绑定：

- `目标骨架`
- `目标面部`

然后选择目标骨架类型：

- `VRM / 通用骨架`
- `Auto Rig Pro`
- `MMD`

### 4. 应用映射

在 `骨骼映射` 面板中：

- 先选择目标骨架类型
- 使用对应的检查、自动填充或标准映射按钮
- 必要时手动修改映射表

在表情映射面板中：

- 配置 `VMC Blend -> Shape Key`
- 或配置 `ARKit 52 Key -> Shape Key`

### 5. 实时预览

- 开启 `实时驱动目标对象`：目标角色会实时跟随输入
- 关闭该选项：只保留中间层预览，目标角色停止写入
- `固定角色到中心` 开启时忽略根位移；关闭后会按映射表中的根运动目标骨驱动角色位移

## 录制教程

`录制` 面板支持实际动捕工作流：

1. 设定 `录制开始帧` 和 `录制结束帧`
2. 按需开启 `起始姿态过渡`
3. 如需重录，先执行 `清空范围内关键帧`
4. 点击 `开始录制`

录制行为：

- 开始录制前会自动把时间线切到录制开始帧
- 开始录制会自动启动或继续接收
- 录制期间缓存目标结果，不实时写 Action
- 达到结束帧或手动停止后，自动停止接收并离线烘焙关键帧
- 保存阶段会在 Blender 状态栏显示进度

## 运行逻辑

- 预览层：查看原始输入
- 目标层：查看映射后的角色结果
- 目标预览与录制共用同一条目标求值链路

这意味着：

- 预览看到的目标角色结果，应与最终录制结果保持一致
- 任何 ARP / MMD / VRM 专用矫正，都必须发生在目标求值阶段，而不是在预览和录制里各写一套

## 目录结构

```text
vmc_link/
  __init__.py
  blender_manifest.toml
  assets/
  core/
  docs/
  mapping/
  presets/
  preview/
  runtime/
  ui/
  wheels/
```

## 打包与发布

- 当前对外分发包命名固定为：
  - `VMC_Link_Reforged_Beta_<版本号>_For5.1.zip`
- 版本号以 `blender_manifest.toml` 和 `__init__.py` 为准
- `blender_manifest.toml` 必须位于 zip 根目录
- 打包内容只包含扩展本体和运行依赖

默认纳入：

- `AGENTS.md`
- `__init__.py`
- `blender_manifest.toml`
- `README.md`
- `assets/`
- `core/`
- `docs/`
- `mapping/`
- `presets/`
- `preview/`
- `runtime/`
- `ui/`
- `wheels/`

必须排除：

- `.git`
- `__pycache__/`
- `.DS_Store`
- `RhyLiveSDK_Unity-main/`
- 已生成的 `*.zip`

## 文档说明

- 当前面向用户的主文档就是本 README
- 已完成阶段的开发计划已归档到 `docs/archive/`
- 当前不再把旧计划文档继续作为未来新功能文档使用

## 参考

- Fork 原项目：[VMC-Link](https://weforge.xyz/partisan/VMC-Link)
- ARKit 面部模型来源：[hinzka/52blendshapes-for-VRoid-face](https://github.com/hinzka/52blendshapes-for-VRoid-face)
- RhyLive Unity SDK：[RhythMoAI/RhyLiveSDK_Unity](https://github.com/RhythMoAI/RhyLiveSDK_Unity)
- Auto-Rig Pro：[Auto-Rig Pro](https://superhivemarket.com/products/auto-rig-pro)
