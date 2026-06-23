# VMC Link

面向 Blender 的实时动捕接收插件。

当前项目用于接收 `VMC` 与 `RhyLive ARKit` 数据流，在 Blender 视口中实时预览原始数据，并将其驱动到测试骨架或目标模型。项目现阶段的核心目标不是做“通用一键适配所有骨架”，而是先固化一条稳定、可调试、可扩展的实时驱动链路。

当前可以把系统理解成两条中间层：

- 身体中间层：`VRM` 风格标准骨架
- 面部中间层：`ARKit 52 Key` 标准表情系数

## 当前能力

- 接收 `VMC` 数据：
  - `/VMC/Ext/Root/Pos`
  - `/VMC/Ext/Tra/Pos`
  - `/VMC/Ext/Bone/Pos`
  - `/VMC/Ext/Blend/Val`
- 接收 `RhyLive ARKit` 数据：
  - `/Face`
- 支持两种脸部来源：
  - `VMC`
  - `RhyLive ARKit`
- 支持原始数据预览：
  - `Data Preview`
  - `ARKit Preview`
- 支持实时驱动：
  - `VMC Bone -> Blender Bone`
  - `VMC Blend -> Blender Shape Key`
  - `ARKit Blend -> Blender Shape Key`
- 支持三套映射配置与独立 JSON 预设：
  - `Bone Mapping`
  - `VMC Blend Mapping`
  - `ARKit Blend Mapping`
- 支持创建和重建固定 `VRM Intermediate Rig`：
  - `Create Intermediate Rig`
  - `Rebuild Intermediate Rig`

## 当前工作方式

### 1. 身体驱动

身体部分始终使用 `VMC` 数据。

- 根位移优先级：
  1. `Root/Pos`
  2. `Tra/Pos`
  3. `Bone/Pos` 中的 `Hips`
- 骨骼旋转：
  - 由 `Bone/Pos` 驱动
  - 通过别名表和手动映射查找目标骨骼

### 2. 脸部驱动

脸部来源由 `Face Source` 决定：

- `VMC`
  - 使用 `/VMC/Ext/Blend/Val`
  - 通过 `VMC Blend Mapping` 驱动目标 Shape Key
- `RhyLive ARKit`
  - 使用 `/Face`
  - 按 Unity 参考项目中的固定 52 个 ARKit Key 顺序解析
  - 通过 `ARKit Blend Mapping` 驱动目标 Shape Key

当前脸部链路的中间层不是“某个目标模型的 Shape Key 名单”，而是固定的 `ARKit 52 Key` 系数集合。也就是说：

`RhyLive /Face -> ARKit 52 Key 中间层 -> 目标 Shape Key`

### 3. 实时预览

- `Live Preview Targets` 开启时：
  - 实时将接收数据写入骨骼 / Shape Key
- 关闭时：
  - 只接收并显示数据，不驱动目标对象

## 面板说明

### 主面板

`VMC Link`

- 启停接收器
- 录制
- 接收地址与端口配置
- `Face Source`
- `Apply Rate (Hz)`
- 目标 `Armature`
- 目标 `Face Mesh`
- `Create Dummy Armature`
- `Rebuild Mapping`
- `Intermediate Layers`

### 子面板

- `Data Preview`
  - 显示 VMC 原始根、骨骼、Blend 数据
- `ARKit Preview`
  - 显示 RhyLive `/Face` 52 项 ARKit 系数
- `Bone Mapping`
  - 管理 VMC 骨骼到 Blender 骨骼的映射
- `VMC Blend Mapping`
  - 管理 VMC 表情到 Blender Shape Key 的映射
- `ARKit Blend Mapping`
  - 管理 ARKit 52 Key 到 Blender Shape Key 的映射
- `Intermediate Layers`
  - 显示 `VRM Intermediate Rig` 识别状态
  - 显示 ARKit 52 Key 中间层覆盖率与调试资产状态

## 映射与预设

### 三类映射

- 骨骼映射：
  - `VMC Bone Name -> Blender Bone Name`
- VMC 表情映射：
  - `VMC Blend Name -> Blender Shape Key Name`
- ARKit 表情映射：
  - `ARKit Key -> Blender Shape Key Name`

### 预设存储位置

插件会在目录下自动创建：

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

## VRM Intermediate Rig 的定位

当前面板里显示为 `Create Intermediate Rig`，对应的实现仍兼容历史 operator `Create Dummy Armature`。

它当前会创建一套固定命名的人形标准骨架，用于：

- 验证接收链路是否正常
- 验证 VMC 骨骼映射是否正常
- 验证整体位移、眼球桥接、表情映射等行为
- 作为正式固定的 `VRM Intermediate Rig`

当前这套骨架已经被固化为中间层，并补充了：

- 识别逻辑
- 重建逻辑
- 中间层状态面板
- 骨骼覆盖率与缺失提示

## ARKit 面部中间层与调试资产

除了骨骼中间层，项目当前还存在一套固定的面部中间层：

- `ARKIT_BLENDSHAPE_KEYS` 中定义的 52 个 ARKit 标准表情键

它的用途是：

- 作为 `RhyLive /Face` 的统一接收格式
- 作为 `ARKit Blend Mapping` 的统一源键集合
- 作为后续 `ARKit -> MMD` 或其他面部标准适配的固定中间层

项目内附带一个用于调试和预览的标准 ARKit 面部文件：

- [Arkitface.blend](/C:/Users/Con11/AppData/Roaming/Blender%20Foundation/Blender/5.1/extensions/blender_org/vmc_link/assets/Arkitface.blend)

这个文件的用途建议固定为：

- 验证 `/Face` 52 项系数接收是否正常
- 验证 `ARKit Blend Mapping` 是否正常
- 作为 ARKit 面部调试基准模型
- 在适配 `MMD` 面部前，先验证 ARKit 中间层本身没有问题

## 当前已知边界

- 当前项目已经完成首轮模块化，`main.py` 只负责装配与注册，主要逻辑已拆分到 `constants.py`、`properties.py`、`network.py`、`runtime.py`、`mapping.py`、`presets.py`、`dummy_vrm.py` 和各个 `ui_*.py` 模块。
- 当前支持的实时数据来源主要是：
  - `VMC`
  - `RhyLive ARKit OSC /Face`
- 当前并未实现“适配所有第三方骨架标准”。
- 当前开发重点不是直接适配所有模型，而是先稳定：
  - 中间层骨架
  - 映射系统
  - 预设系统
  - 调试能力

## 当前开发目标

当前优先适配目标：

- 骨架：`Auto Rig Pro` 生成人形骨架
- 面部：`MMD` 标准 Shape Key

暂不作为当前阶段目标：

- 其他骨架标准
- 其他面部命名标准
- 完整通用自动重定向系统

## 开发参考

项目后续重映射模块将重点参考本机 Auto Rig Pro 扩展目录中的相关实现：

- Auto Rig Pro 入口注册中包含独立重映射模块：
  - `src/auto_rig_remap.py`
- 该插件已有明确的：
  - 重映射模块拆分
  - humanoid 绑定概念
  - 映射预设导入/导出
  - 自定义预设目录

参考目录：

`C:\Users\Con11\AppData\Roaming\Blender Foundation\Blender\5.1\extensions\user_default\auto_rig_pro_master`

## 相关项目

- Fork 原项目：
  - [VMC-Link](https://weforge.xyz/partisan/VMC-Link)
- ARKit 面部模型来源：
  - [hinzka/52blendshapes-for-VRoid-face](https://github.com/hinzka/52blendshapes-for-VRoid-face)
- RhyLive Unity SDK：
  - [RhythMoAI/RhyLiveSDK_Unity](https://github.com/RhythMoAI/RhyLiveSDK_Unity)
- Auto-Rig Pro：
  - [Auto-Rig Pro](https://superhivemarket.com/products/auto-rig-pro)

## 仓库文件

- [__init__.py](/C:/Users/Con11/AppData/Roaming/Blender%20Foundation/Blender/5.1/extensions/blender_org/vmc_link/__init__.py)
  - 插件入口与 Blender 注册
- [main.py](/C:/Users/Con11/AppData/Roaming/Blender%20Foundation/Blender/5.1/extensions/blender_org/vmc_link/main.py)
  - 模块装配与注册入口
- `constants.py` / `properties.py` / `network.py` / `runtime.py`
  - 常量、Scene 属性、网络接收、运行时驱动
- `mapping.py` / `presets.py`
  - 映射查找、缓存重建、JSON 预设
- `dummy_vrm.py` / `ui_intermediate.py`
  - `VRM Intermediate Rig` 创建、识别、重建与状态面板
- `ui_main.py` / `ui_preview.py` / `ui_mapping.py`
  - 主面板、预览面板、映射面板
- [RhyLiveSDK_Unity-main](/C:/Users/Con11/AppData/Roaming/Blender%20Foundation/Blender/5.1/extensions/blender_org/vmc_link/RhyLiveSDK_Unity-main)
  - RhyLive Unity 参考实现
- [Arkitface.blend](/C:/Users/Con11/AppData/Roaming/Blender%20Foundation/Blender/5.1/extensions/blender_org/vmc_link/assets/Arkitface.blend)
  - ARKit 52 Shape Key 标准调试面部模型

## 建议使用流程

1. 打开插件并配置接收端口
2. 创建或指定测试 `Armature`
3. 指定带 Shape Key 的 `Face Mesh`
4. 选择 `Face Source`
5. 观察 `Data Preview` / `ARKit Preview`
6. 根据目标模型配置三类映射
7. 将映射保存为 JSON 预设
8. 针对新模型加载对应预设继续测试

如果是做 ARKit 面部调试，建议优先使用 [Arkitface.blend](/C:/Users/Con11/AppData/Roaming/Blender%20Foundation/Blender/5.1/extensions/blender_org/vmc_link/assets/Arkitface.blend) 验证 `ARKit 52 Key -> Shape Key` 链路，再继续做 `MMD` 面部适配。
