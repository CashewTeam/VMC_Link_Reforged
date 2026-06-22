# VMC Link

面向 Blender 的实时动捕接收插件。

当前项目用于接收 `VMC` 与 `RhyLive ARKit` 数据流，在 Blender 视口中实时预览原始数据，并将其驱动到测试骨架或目标模型。项目现阶段的核心目标不是做“通用一键适配所有骨架”，而是先固化一条稳定、可调试、可扩展的实时驱动链路。

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
- 支持创建测试用 `VRM` 风格标准骨架：
  - `Create Dummy Armature`

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

## Create Dummy Armature 的定位

`Create Dummy Armature` 当前会创建一套固定命名的人形测试骨架，用于：

- 验证接收链路是否正常
- 验证 VMC 骨骼映射是否正常
- 验证整体位移、眼球桥接、表情映射等行为
- 作为后续“统一中间层骨架”的雏形

这套骨架当前主要用于调试，但项目计划会进一步固化它的中间层地位，使其成为“外部动捕数据 -> VRM 标准中间骨架 -> 目标骨架/目标表情”的中心节点。

## 当前已知边界

- 当前项目代码仍主要集中在 [main.py](/C:/Users/Con11/AppData/Roaming/Blender%20Foundation/Blender/5.1/extensions/blender_org/vmc_link/main.py)，后续需要模块化。
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

## 仓库文件

- [__init__.py](/C:/Users/Con11/AppData/Roaming/Blender%20Foundation/Blender/5.1/extensions/blender_org/vmc_link/__init__.py)
  - 插件入口与 Blender 注册
- [main.py](/C:/Users/Con11/AppData/Roaming/Blender%20Foundation/Blender/5.1/extensions/blender_org/vmc_link/main.py)
  - 当前主要实现
- [RhyLiveSDK_Unity-main](/C:/Users/Con11/AppData/Roaming/Blender%20Foundation/Blender/5.1/extensions/blender_org/vmc_link/RhyLiveSDK_Unity-main)
  - RhyLive Unity 参考实现

## 建议使用流程

1. 打开插件并配置接收端口
2. 创建或指定测试 `Armature`
3. 指定带 Shape Key 的 `Face Mesh`
4. 选择 `Face Source`
5. 观察 `Data Preview` / `ARKit Preview`
6. 根据目标模型配置三类映射
7. 将映射保存为 JSON 预设
8. 针对新模型加载对应预设继续测试
