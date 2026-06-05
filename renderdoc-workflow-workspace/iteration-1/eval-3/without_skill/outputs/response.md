# RenderDoc 帧捕获与 Shadow Pass Draw Call 检查指南

## 前提条件

- 安装 [RenderDoc](https://renderdoc.org/) (推荐 v1.x 最新稳定版)
- UE5 项目路径: `F:\MyProject\MyProject.uproject`
- 确保项目使用 D3D11 或 D3D12 或 Vulkan RHI（RenderDoc 不支持 DirectX 12 之外的所有后端）

---

## 方法一：通过 RenderDoc GUI 启动捕获

1. 打开 RenderDoc
2. 在 Launch Application 标签页中填写：
   - **Executable**: UE5 Editor 的可执行文件路径，通常为：
     ```
     C:\Program Files\Epic Games\UE_5.X\Engine\Binaries\Win64\UnrealEditor.exe
     ```
     或者如果是从源码编译的引擎：
     ```
     <EngineRoot>\Binaries\Win64\UnrealEditor.exe
     ```
   - **Working Directory**: 引擎的 Win64 目录
   - **Command line arguments**:
     ```
     F:\MyProject\MyProject.uproject
     ```
3. 确认 **API Validation** 可选开启（有助于发现渲染问题）
4. 点击 **Launch** 启动项目
5. 等待项目加载完成，进入你想要捕获的场景
6. 按 **F12**（默认快捷键）或点击 RenderDoc 浮动工具栏上的 Capture 按钮捕获一帧
7. 捕获完成后，在 RenderDoc 的 Capture 列表中双击打开该帧

## 方法二：通过命令行启动捕获

```cmd
"C:\Path\To\renderdoccmd.exe" capture "C:\Path\To\UnrealEditor.exe" F:\MyProject\MyProject.uproject
```

或者在 PowerShell 中：

```powershell
& "C:\Program Files\RenderDoc\renderdoccmd.exe" capture "C:\Path\To\UnrealEditor.exe" "F:\MyProject\MyProject.uproject"
```

## 方法三：注入已运行的进程

1. 先正常启动 UE5 Editor 并打开项目
2. 打开 RenderDoc，在 **Inject into Process** 中选择 `UnrealEditor.exe`
3. 注入后使用 F12 捕获

---

## 查看 Shadow Pass Draw Call 的步骤

1. 打开捕获的帧后，进入 **Event Browser**（左侧面板）
2. 在 Event Browser 中找到 Shadow 相关的 Render Pass / Draw Call：
   - 搜索关键词：`Shadow`、`ShadowDepth`、`Csm`（Cascaded Shadow Map）
   - UE5 的 Shadow Pass 通常在以下阶段：
     - **Cascaded Shadow Maps (CSM)** - 方向光阴影
     - **SpotLightShadowMap** / **PointLightShadowMap** - 局部光源阴影
     - 以 `ShadowDepth` 或 `ShadowPass` 命名的 Draw Call
3. 选中 Shadow 相关的 Draw Call 后：
   - **Pipeline State** 标签页：查看顶点着色器、像素着色器（Shadow Pass 通常为空像素着色器或仅输出深度）
   - **Mesh Viewer** 标签页：查看该 Draw Call 的几何体
   - **Texture Viewer** 标签页：查看输出的 Shadow Map 纹理
   - **API Inspector**：查看完整的渲染状态
4. 在 **Event Browser** 顶部过滤栏中输入 `shadow`（大小写不敏感）可快速过滤出所有 Shadow 相关事件

### Shadow Pass 常见 Draw Call 特征

| 特征 | 说明 |
|------|------|
| 像素着色器 | 通常为 `ShadowDepthPixelShader` 或 null PS |
| 输出 | Depth/Shadow Map 纹理（通常为 R32_FLOAT 或 R16_FLOAT） |
| 渲染目标 | 无颜色输出，仅深度 |
| Draw Call 名称 | 包含 `Shadow`、`Csm`、`ShadowDepth` |

---

## 注意事项

- 如果捕获失败，确认项目使用的 RHI 被 RenderDoc 支持。可在 UE5 启动参数中强制指定：`-dx12` 或 `-vulkan`
- 大型场景捕获可能较慢，建议先简化场景
- 捕获文件 (.rdc) 可能较大，注意磁盘空间
- 如果使用 D3D12，某些 UE5 的渲染特性（如 Nanite、Virtual Shadow Maps）可能在 RenderDoc 中显示为多个间接 Draw Call
