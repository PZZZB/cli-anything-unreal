# 鐢?ue-cli 鎴彇 RenderDoc GPU 甯ф潵璋冭瘯 UE5 鏉愯川娓叉煋

## 鍓嶆彁鏉′欢

1. **RenderDoc 鎻掍欢蹇呴』鍦?UE 涓惎鐢ㄣ€?* 鍦ㄩ」鐩殑 `DefaultEngine.ini` 涓坊鍔狅細
   ```ini
   [Plugins]
   +EnabledPlugins=RenderDoc
   ```
   鎴栬€呭湪 UE 缂栬緫鍣ㄤ腑鎵嬪姩鍚敤锛欵dit 鈫?Plugins 鈫?RenderDoc銆?
2. **缂栬緫鍣ㄥ繀椤讳互绐楀彛妯″紡杩愯**锛堜笉鑳戒娇鐢?`-nullrhi`锛夈€俁enderDoc 闇€瑕佺湡瀹炵殑 RHI 鍚庣銆?
3. **瀹夎 RenderDoc 搴旂敤**锛堜粠 [renderdoc.org](https://renderdoc.org) 涓嬭浇锛夛紝鍚﹀垯鎴抚鍚庢棤娉曟墦寮€ `.rdc` 鏂囦欢杩涜鍒嗘瀽銆?
## 姝ラ

### 1. 纭缂栬緫鍣ㄥ湪绾?
```bash
ue-cli editor status
```

濡傛灉缂栬緫鍣ㄦ湭杩愯锛屽厛鍚姩瀹冿細

```bash
ue-cli --project F:\MyProject\MyProject.uproject editor launch --map /Game/Maps/MyMap
```

### 2. 锛堝彲閫夛級鍦ㄦ埅甯у墠璋冩暣娓叉煋鍙傛暟

```bash
# 鏌ョ湅鎴栬缃覆鏌撶浉鍏崇殑 CVar
ue-cli editor cvar get r.ShadowQuality
ue-cli editor cvar set r.ShadowQuality 3
ue-cli editor cvar set r.AntiAliasingMethod 2
```

### 3. 鎴彇 GPU 甯?
```bash
ue-cli editor exec "renderdoc.captureframe"
```

鎵ц鍚庯紝RenderDoc 浼氭埅鍙栦笅涓€甯х殑 GPU 鏁版嵁銆傚鏋?RenderDoc 搴旂敤宸插畨瑁咃紝瀹冧細鑷姩鎵撳紑 `.rdc` 鏂囦欢锛涘惁鍒欐崟鑾锋枃浠朵細淇濆瓨鍒?RenderDoc 鐨勬埅甯х洰褰曪紙閫氬父鏄?`C:\Users\<User>\AppData\Local\Temp\RenderDoc\`锛夈€?
### 4. 锛堝彲閫夛級鎴竴寮犺鍙ｆ埅鍥句綔涓鸿瑙夊弬鑰?
```bash
ue-cli screenshot capture --filename material_before_capture
```

### 5. 鍒嗘瀽鎴抚鏁版嵁

鐢?RenderDoc 搴旂敤鎵撳紑 `.rdc` 鏂囦欢锛屽彲浠ヨ繘琛屼互涓嬪垎鏋愶細

- **Shader 璋冭瘯**锛氶€愯妫€鏌ュ儚绱?椤剁偣鐫€鑹插櫒鐨勬墽琛岋紝瀹氫綅鏉愯川娓叉煋寮傚父
- **Draw Call 妫€鏌?*锛氭壘鍑哄紑閿€澶х殑缁樺埗璋冪敤銆佽繃搴︾粯鍒舵垨鍐椾綑鐘舵€佸垏鎹?- **绾圭悊/娓叉煋鐩爣楠岃瘉**锛氭鏌ヤ腑闂存覆鏌撶洰鏍囨潵璇婃柇瑙嗚浼奖
- **鎬ц兘鍒嗘瀽**锛氭煡鐪嬫瘡涓?Draw Call 鎴?Pass 鐨?GPU 鑰楁椂

濡傛灉瀹夎浜?`renderdoc-mcp` 鎶€鑳斤紝涔熷彲浠ラ€氳繃 CLI 绋嬪簭鍖栧湴鍒嗘瀽 `.rdc` 鏂囦欢銆?
## 瀹屾暣宸ヤ綔娴佺ず渚?
```bash
# 1. 妫€鏌ョ紪杈戝櫒鐘舵€?ue-cli editor status

# 2. 濡傛灉娌¤繍琛岋紝鍚姩缂栬緫鍣ㄥ苟鍔犺浇鐩爣鍏冲崱
ue-cli --project F:\MyProject\MyProject.uproject editor launch --map /Game/Maps/MyMap

# 3. 鏌ョ湅鏈夐棶棰樼殑鏉愯川
ue-cli material analyze /Game/Materials/M_MyProblem

# 4. 鎴彇 GPU 甯?ue-cli editor exec "renderdoc.captureframe"

# 5. 鎴彇瑙嗗彛鎴浘鐣欎綔瀵规瘮
ue-cli screenshot capture --filename before_fix

# 6. 淇鏉愯川...
ue-cli material set-param /Game/Materials/M_MyProblem --name BaseColor --value 1,0,0 --type vector

# 7. 鍐嶆鎴抚瀵规瘮
ue-cli editor exec "renderdoc.captureframe"
ue-cli screenshot capture --filename after_fix
```

## 甯歌闂鎺掓煡

| 闂 | 鍘熷洜 | 瑙ｅ喅鏂规硶 |
|------|------|----------|
| 鍛戒护鎵ц浜嗕絾娌℃湁鎴抚 | RenderDoc 鎻掍欢鏈姞杞?| 妫€鏌?`DefaultEngine.ini` 涓槸鍚︽湁 `+EnabledPlugins=RenderDoc`锛岄噸鍚紪杈戝櫒 |
| 鎴抚澶辫触锛屽嚭鐜?D3D 閿欒 | 浣跨敤浜?`-nullrhi` 鎴栨棤澶存ā寮?| 绉婚櫎 `-nullrhi` 鍚姩鍙傛暟锛屼娇鐢ㄧ獥鍙ｆā寮?|
| 鎵句笉鍒?`.rdc` 鏂囦欢 | 涓嶇‘瀹氭埅甯т繚瀛樼洰褰?| 妫€鏌?RenderDoc 璁剧疆锛屾垨鏌ョ湅 `%TEMP%\RenderDoc\` |
| RenderDoc UI 娌℃湁鑷姩鎵撳紑 | RenderDoc 鏈畨瑁?| 浠?[renderdoc.org](https://renderdoc.org) 瀹夎 RenderDoc |
