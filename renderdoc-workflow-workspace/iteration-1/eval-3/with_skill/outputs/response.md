# RenderDoc 甯ф崟鑾?- 鏌ョ湅 Shadow Pass Draw Call

## 鎿嶄綔姝ラ

### 1. 纭缂栬緫鍣ㄧ姸鎬?
```bash
ue-cli --project F:\MyProject\MyProject.uproject editor status
```

- 濡傛灉杩斿洖 `online`锛岀户缁笅涓€姝ャ€?- 濡傛灉杩斿洖 `not_running` 鎴?`zombie`锛岄渶瑕佸厛鍚姩缂栬緫鍣ㄣ€?
### 2. 鍚姩缂栬緫鍣紙濡傛灉鏈繍琛岋級

```bash
# 鍏堟鏌ユ瀯寤哄吋瀹规€?ue-cli --project F:\MyProject\MyProject.uproject editor preflight

# 鍚姩缂栬緫鍣紙闃诲绛夊緟灏辩华锛?ue-cli --project F:\MyProject\MyProject.uproject editor launch
```

### 3. 纭 RenderDoc 鎻掍欢宸插姞杞?
椤圭洰鐨?`DefaultEngine.ini` 闇€瑕佸寘鍚細

```ini
[Plugins]
+EnabledPlugins=RenderDoc
```

楠岃瘉鎻掍欢鏄惁鐢熸晥锛?
```bash
ue-cli editor exec "renderdoc.captureframe"
```

濡傛灉鎻掍欢鏈姞杞斤紝姝ゅ懡浠や細闈欓粯鏃犳晥鏋溿€傞渶瑕佸湪缂栬緫鍣ㄤ腑鎵嬪姩鍚敤锛欵dit 鈫?Plugins 鈫?RenderDoc锛岀劧鍚庨噸鍚紪杈戝櫒銆?
### 4. 锛堝彲閫夛級璋冩暣 Shadow 鐩稿叧 CVar

鍦ㄦ崟鑾峰墠鍙互璋冩暣闃村奖璐ㄩ噺璁剧疆锛岀‘淇濇崟鑾峰埌浣犲叧蹇冪殑 shadow pass锛?
```bash
ue-cli editor cvar set r.ShadowQuality 3
ue-cli editor cvar set r.Shadow.CSM.MaxCascades 4
ue-cli editor cvar get r.ShadowQuality
```

### 5. 鎹曡幏 GPU 甯?
```bash
ue-cli editor exec "renderdoc.captureframe"
```

鎵ц鍚庯紝RenderDoc 浼氳嚜鍔ㄦ墦寮€鎹曡幏鐨?`.rdc` 鏂囦欢锛堝鏋?RenderDoc 宸插畨瑁咃級銆傛崟鑾锋枃浠朵篃淇濆瓨鍦?RenderDoc 鐨勬崟鑾风洰褰曚腑锛堥€氬父涓?`C:\Users\<User>\AppData\Local\Temp\RenderDoc\`锛夈€?
### 6. 锛堝彲閫夛級鎴彇瑙嗗彛鎴浘浣滀负鍙傝€?
```bash
ue-cli screenshot capture --filename before_capture
```

## 鍦?RenderDoc 涓煡鐪?Shadow Pass Draw Call

1. 鍦?RenderDoc 涓墦寮€鎹曡幏鐨?`.rdc` 鏂囦欢銆?2. 鍦?**Event Browser** 涓紝鎵惧埌鏍囪涓?**Shadow** 鐨?pass锛圲E5 閫氬父浼氭湁 `ShadowDepth`銆乣CSMShadow` 绛?pass 鍚嶇О锛夈€?3. 灞曞紑 shadow pass锛屽彲浠ョ湅鍒拌 pass 鍐呯殑鎵€鏈?draw call銆?4. 鐐瑰嚮姣忎釜 draw call 鍙互鏌ョ湅锛?   - **Pipeline State**: 椤剁偣/鍍忕礌鐫€鑹插櫒銆乥lend state 绛?   - **Mesh Viewer**: 璇?draw call 娓叉煋鐨勫嚑浣曚綋
   - **Texture Viewer**: shadow map 鐨勮緭鍑?
### 甯哥敤鍒嗘瀽鏂规硶

- **Draw Call 鏁伴噺**: 鍦?Event Browser 涓暟 shadow pass 涓嬬殑 draw call 鏉＄洰鏁?- **GPU 鑰楁椂**: 鍒囨崲鍒?**Timer Query** 妯″紡鏌ョ湅姣忎釜 draw call 鐨?GPU 鏃堕棿
- **Overdraw**: 鍦?Texture Viewer 涓煡鐪?shadow map锛岀‘璁ゆ槸鍚︽湁涓嶅繀瑕佺殑閲嶅彔缁樺埗

## 鏁呴殰鎺掗櫎

| 闂 | 鍘熷洜 | 瑙ｅ喅鏂规硶 |
|------|------|----------|
| 鍛戒护鎵ц浣嗘棤鎹曡幏 | RenderDoc 鎻掍欢鏈姞杞?| 妫€鏌?`DefaultEngine.ini` 涓?`+EnabledPlugins=RenderDoc`锛涢噸鍚紪杈戝櫒 |
| 鎹曡幏澶辫触锛孌3D 閿欒 | 浣跨敤浜?`-nullrhi` 鎴栨棤澶存ā寮?| 绉婚櫎 `-nullrhi`锛屼娇鐢ㄧ獥鍙ｆā寮?|
| 鎵句笉鍒?`.rdc` 鏂囦欢 | 鏈煡鎹曡幏鐩綍 | 妫€鏌?RenderDoc 璁剧疆鎴栨煡鐪?`%TEMP%\RenderDoc\` |
| RenderDoc UI 鏈墦寮€ | 鏈畨瑁?RenderDoc | 浠?[renderdoc.org](https://renderdoc.org) 瀹夎 |
