# Capturing a RenderDoc GPU Frame in Unreal Engine 5

## Capturing a GPU Frame with RenderDoc

### Method 1: Using the RenderDoc UI

1. **Launch RenderDoc** and ensure it is running before starting the UE5 editor.
2. **Attach to the Unreal process**: In RenderDoc, click the "Launch" or "Attach" button. If the editor is already running, use File > Attach to Running Instance and select the Unreal Editor process.
3. **Capture a frame**: Press `F12` (default capture key) or click the "Capture" button in RenderDoc while the UE5 viewport is in focus. This will capture the next full frame rendered by the GPU.
4. The capture will appear in the capture list in RenderDoc's bottom-left panel. Double-click it to open and inspect draw calls, shaders, textures, and pipeline state.

### Method 2: Using UE5's Built-in RenderDoc Integration

UE5 has a built-in RenderDoc plugin that simplifies the workflow:

1. **Enable the plugin**: Go to Edit > Plugins, search for "RenderDoc", and enable it. Restart the editor if prompted.
2. **Capture from the viewport**: In the Slate viewport toolbar, click the RenderDoc icon (a small bug icon) or use the keyboard shortcut `Ctrl+Shift+PrintScreen` to capture the current frame.
3. The capture file (`.rdc`) will be saved to the RenderDoc capture path and automatically opened in the RenderDoc UI if it is installed.

### Method 3: Command Line / Programmatic Capture

If the editor is running on a debug port (e.g., 30010), you can use the `ue-cli` tool or UE5's console commands:

- Open the console (`~` key) in the UE5 viewport and type:
  ```
  RenderDoc.CaptureFrame
  ```
- Or use the Python/Blueprint scripting layer to trigger a capture programmatically.

## Taking a Screenshot for Comparison

### Method 1: UE5 High-Resolution Screenshot

1. In the viewport, click the dropdown arrow next to the viewport name (e.g., "Perspective").
2. Select **High Resolution Screenshot**.
3. Configure the resolution multiplier and capture settings.
4. Click **Capture**. The screenshot is saved to `<Project>/Saved/Screenshots/`.

### Method 2: Console Command

Open the console and type:
```
HighResShot 2
```
The `2` is the resolution multiplier. The screenshot is saved to the project's `Saved/Screenshots/` directory.

### Method 3: Standard Screenshot

- Press `F9` in the viewport for a quick screenshot, saved to `Saved/Screenshots/`.
- Or use `PrintScreen` for a basic capture to clipboard.

## Typical Debugging Workflow

1. **Take a screenshot** of the problematic frame first 鈥?this gives you the "what it looks like" reference.
2. **Capture a RenderDoc frame** 鈥?this gives you the "why it looks like that" by exposing all GPU state, draw calls, and shader code.
3. **Compare**: Use the screenshot to identify which pixels are wrong, then use the RenderDoc capture to trace those pixels back through the rendering pipeline to find the root cause (e.g., wrong shader constants, incorrect blend mode, missing texture binding).

## Common Shader Debugging Tips

- In RenderDoc, use the **Pixel History** tool on a pixel of interest to see all the draw calls that contributed to its final value.
- Use the **Shader Viewer** to inspect the compiled HLSL/bytecode and set breakpoints for pixel debugging.
- Use the **Texture Viewer** to inspect render targets at each draw call step.
- If using UE5's virtual shadow maps or nanite, note that these use compute shaders which appear in the "Compute" section rather than the standard draw call list.

## File Locations

| Output | Default Path |
|--------|-------------|
| RenderDoc captures | `%USERPROFILE%/RenderDoc/` or configured capture directory |
| UE5 screenshots | `<Project>/Saved/Screenshots/` |
| UE5 shader source | Requires `r.ShaderDevelopmentMode=1` and `r.DumpShaderSource=1` in console variables |
