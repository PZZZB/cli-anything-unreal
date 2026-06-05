# RenderDoc GPU Frame Capture & Screenshot Workflow

Your editor is running on port **30010**. Here is the step-by-step workflow to capture a RenderDoc GPU frame and take a screenshot for comparison.

## Prerequisites

1. **RenderDoc plugin must be loaded in UE.** Verify the project's `DefaultEngine.ini` includes:
   ```ini
   [Plugins]
   +EnabledPlugins=RenderDoc
   ```
   If missing, add it and restart the editor.

2. **Editor must be running in windowed mode** (not `-nullrhi`). RenderDoc requires a real RHI backend to capture frames.

## Step-by-Step Workflow

### Step 1: Verify the Editor is Online

```bash
ue-cli --port 30010 editor status
```

Expected response: `"online"`. If not online, troubleshoot before proceeding.

### Step 2: Capture a RenderDoc GPU Frame

```bash
ue-cli --port 30010 editor exec "renderdoc.captureframe"
```

This triggers RenderDoc to capture the next rendered frame. After execution:
- RenderDoc opens the capture file (`.rdc`) in its UI if installed and the plugin auto-launches it.
- The capture is also saved to the RenderDoc capture directory (typically `C:\Users\<User>\AppData\Local\Temp\RenderDoc\`).

If the command executes but no capture appears, the RenderDoc plugin is likely not loaded. Check `DefaultEngine.ini` as noted in the prerequisites.

### Step 3: Take a Screenshot for Visual Comparison

```bash
ue-cli --port 30010 screenshot capture --filename screenshot_for_comparison
```

This captures the current editor viewport as an image file. Use it alongside the `.rdc` capture to compare visual output with GPU draw call data.

## Full Command Sequence

```bash
# 1. Verify editor is reachable
ue-cli --port 30010 editor status

# 2. Capture a GPU frame via RenderDoc
ue-cli --port 30010 editor exec "renderdoc.captureframe"

# 3. Take a viewport screenshot for visual reference
ue-cli --port 30010 screenshot capture --filename screenshot_for_comparison
```

## Analyzing the Capture

The `.rdc` file can be analyzed with:

- **`renderdoc-mcp` skill** (if available) for programmatic analysis of draw calls, shader debugging, and texture inspection.
- **RenderDoc application** manually opened 鈥?navigate to the capture directory and load the `.rdc` file.

Common analysis tasks for shader debugging:
- **Shader debugging**: Inspect pixel/vertex shader execution step by step.
- **Draw call inspection**: Identify expensive draw calls, overdraw, or redundant state changes.
- **Texture/RT verification**: Check intermediate render targets to diagnose visual artifacts.

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Command executes but no capture | RenderDoc plugin not loaded | Check `DefaultEngine.ini` has `+EnabledPlugins=RenderDoc`; restart editor |
| Capture fails with D3D error | `-nullrhi` or headless mode | Remove `-nullrhi` from launch args; use windowed mode |
| Can't find the `.rdc` file | Unknown capture directory | Check RenderDoc settings or look in `%TEMP%\RenderDoc\` |
| RenderDoc UI doesn't open | RenderDoc not installed | Install RenderDoc from renderdoc.org |
| Screenshot fails | Editor window not visible or minimized | Ensure editor is in foreground, retry |
| Connection refused | Editor not running on port 30010 | Run `ue-cli editor list` to discover running instances |
