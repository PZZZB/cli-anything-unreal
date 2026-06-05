# 鐢?ue-cli 鎴彇 RenderDoc GPU 甯ф暟鎹?
褰撲綘鐨?UE5 鏉愯川娓叉煋缁撴灉涓嶅鏃讹紝鍙互鐢?RenderDoc 鎴彇涓€甯?GPU 鏁版嵁鏉ヨ皟璇曘€備互涓嬫槸瀹屾暣鐨勬搷浣滄祦绋嬨€?
## 鍓嶆彁鏉′欢

### 1. 鍚敤 RenderDoc 鎻掍欢

椤圭洰鐨?`DefaultEngine.ini` 蹇呴』鍖呭惈锛?
```ini
[Plugins]
+EnabledPlugins=RenderDoc
```

鎴栬€呭湪 UE 缂栬緫鍣ㄤ腑鎵嬪姩鍚敤锛欵dit 鈫?Plugins 鈫?RenderDoc銆?
楠岃瘉鎻掍欢鏄惁鍔犺浇鎴愬姛锛?
```bash
ue-cli editor exec "renderdoc.captureframe"
```

濡傛灉鎻掍欢缂哄け锛岃鍛戒护浼氶潤榛樻棤鏁堟灉銆?
### 2. 缂栬緫鍣ㄥ繀椤讳互绐楀彛妯″紡杩愯

RenderDoc 闇€瑕佺湡瀹炵殑 RHI 鍚庣锛屼笉鑳戒娇鐢?`-nullrhi` 妯″紡鍚姩銆?
## 瀹屾暣鎿嶄綔姝ラ

### Step 1锛氭鏌ョ紪杈戝櫒鐘舵€?
```bash
ue-cli editor status
```

- 杩斿洖 `online` 鈫?缁х画涓嬩竴姝?- 杩斿洖 `not_running` 鈫?闇€瑕佸厛鍚姩缂栬緫鍣?
### Step 2锛氬惎鍔ㄧ紪杈戝櫒锛堝闇€锛?
```bash
# 鍏堝仛 preflight 妫€鏌?ue-cli --project F:\MyGame\MyGame.uproject editor preflight

# 鍚姩缂栬緫鍣紝鎵撳紑鐩爣鍦板浘
ue-cli --project F:\MyGame\MyGame.uproject editor launch --map /Game/Maps/MyMap
```

### Step 3锛氾紙鍙€夛級璋冩暣娓叉煋鍙傛暟

鍦ㄦ埅甯у墠鍙互璋冩暣 console variable 鏉ユ帶鍒舵覆鏌撹涓猴細

```bash
ue-cli editor cvar set r.ShadowQuality 3
ue-cli editor cvar set r.AntiAliasingMethod 2
```

### Step 4锛氭埅鍙?GPU 甯?
```bash
ue-cli editor exec "renderdoc.captureframe"
```

鎵ц鍚庯紝RenderDoc 浼氳嚜鍔ㄦ墦寮€ UI 骞跺姞杞芥埅鍙栫殑 `.rdc` 鏂囦欢銆傛埅鍙栨枃浠跺悓鏃朵繚瀛樺埌 RenderDoc 鐨勬埅鍙栫洰褰曪紙閫氬父鏄?`C:\Users\<User>\AppData\Local\Temp\RenderDoc\`锛夈€?
### Step 5锛氾紙鍙€夛級鎴浘浣滀负瑙嗚鍙傜収

```bash
ue-cli screenshot capture --filename before_capture
```

閰嶅悎 `.rdc` 鎴抚鏁版嵁锛屾埅鍥惧彲浠ヤ綔涓鸿瑙夊鐓у弬鑰冦€?
## 鐢?RenderDoc 鍒嗘瀽鎴抚

鎴彇鐨?`.rdc` 鏂囦欢鍙互鐢ㄤ互涓嬫柟寮忓垎鏋愶細

- **Shader 璋冭瘯**锛氶€愯鎵ц鍍忕礌/椤剁偣鐫€鑹插櫒锛屾鏌ヤ腑闂村€?- **Draw Call 妫€鏌?*锛氬畾浣嶉珮寮€閿€鐨勭粯鍒惰皟鐢ㄣ€佽繃搴︾粯鍒舵垨鍐椾綑鐘舵€佸垏鎹?- **绾圭悊/RT 楠岃瘉**锛氭鏌ヤ腑闂存覆鏌撶洰鏍囨潵璇婃柇瑙嗚寮傚父
- **鎬ц兘鍒嗘瀽**锛氭煡鐪嬫瘡涓?Draw Call 鎴?Pass 鐨?GPU 鑰楁椂

濡傛灉浣犳湁 `renderdoc-mcp` 鎶€鑳藉彲鐢紝涔熷彲浠ョ洿鎺ョ敤瀹冩潵鍒嗘瀽 `.rdc` 鏂囦欢銆?
## 甯歌闂鎺掓煡

| 闂 | 鍘熷洜 | 瑙ｅ喅鏂规硶 |
|------|------|----------|
| 鍛戒护鎵ц浣嗘病鏈夋埅甯?| RenderDoc 鎻掍欢鏈姞杞?| 妫€鏌?`DefaultEngine.ini` 鏄惁鏈?`+EnabledPlugins=RenderDoc`锛涢噸鍚紪杈戝櫒 |
| 鎴抚澶辫触骞舵姤 D3D 閿欒 | 浣跨敤浜?`-nullrhi` 鎴栨棤澶存ā寮?| 绉婚櫎 `-nullrhi`锛屼娇鐢ㄧ獥鍙ｆā寮忓惎鍔?|
| 鎵句笉鍒?`.rdc` 鏂囦欢 | 涓嶇‘瀹氭埅鍙栫洰褰?| 鏌ョ湅 RenderDoc 璁剧疆鎴栨鏌?`%TEMP%\RenderDoc\` |
| RenderDoc UI 娌℃湁鎵撳紑 | 鏈畨瑁?RenderDoc | 浠?[renderdoc.org](https://renderdoc.org) 瀹夎 RenderDoc |
