# AI鍙嬪ソ鐨勬搷浣渦e鍩哄缓



## 浼樼偣

鎴戦€夋嫨鐨勬槸CLI+Skill鐨勬柟鍚戯紝浣嗘暣浣撹璁℃槸绔欏湪Agent鐨勮搴﹀幓鍋氱殑锛?
- 闄嶄綆浜虹被鍙備笌銆備笉闇€瑕佷汉绫绘墜鍔ㄥ姞瑁呬换浣曚笢瑗匡紝瑁呭ソcli+skill灏卞彲鐢紝闇€瑕佸畨瑁呯幆澧?濡倁e鎻掍欢锛夌瓑閮界敱AI鑷姩澶勭悊銆?
- 涓嶉渶瑕佸厛鍚姩缂栬緫鍣ㄣ€傚鍦ㄥ井淇′笂璇达細鈥濆府鎴戞墦寮€杩欎釜ue椤圭洰锛屾埅涓猤ame view鐨勫浘鈥滐紝鈥滃府鎴戠紪璇戣繖涓猽e椤圭洰鈥濓紝鑷姩瀹屾垚銆?
- 鏃犵獥鍙ｆā寮忥紝鎿嶄綔ue瀹规槗瑙﹀彂涓€浜涙秷鎭脊绐楋紝agent鎿嶄綔涓嶄簡瀵艰嚧鍗℃銆傛湰椤圭洰閮借閬?瑙ｅ喅鎺変簡锛孉I鍙嬪ソ鐨勬棤寮圭獥妯″紡銆?
- 閲嶅啓浜嗕竴浜涗笉绗﹀悎AI鎰熺煡鐨勫姛鑳斤紝姣斿鎴浘闇€瑕佽Е鍙戞覆鏌撶嚎绋嬫墽琛岋紝闇€瑕佹妸绐楀彛甯﹀埌鍓嶅彴锛屾湰椤圭洰瀹屽叏閲嶅啓鎴浘鍔熻兘瑙勯伩銆?


## 瀹炵幇鏋舵瀯

鍜屼富娴佹柟妗堢浉浼硷紝浠呯粏寰笉鍚屻€?
搴曞眰閫氳繃 UE 鑷甫鐨?**Remote Control 鎻掍欢** + **UObject 鍙嶅皠绯荤粺**鍔ㄦ€佽幏鍙?API锛屽鏉備换鍔＄敤**python鑴氭湰**瀹屾垚銆?
### 鏋舵瀯鍥?
```
鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹?           Coding Agent (Claude / Cursor)            鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                        鈹?bash
                        鈻?鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹?            ue-cli (CLI)                鈹?鈹?         鍛戒护璺敱 / --json / --port / Skill          鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?           鈹?鏋勫缓鏈?                     鈹?缂栬緫鏈?           鈻?                            鈻?   鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?            鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?   鈹? UAT / UBT   鈹?            鈹?HTTP Remote Control 鈹?   鈹? (subprocess)鈹?            鈹?  localhost:30010+  鈹?   鈹?compile/cook 鈹?            鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?   鈹?  /package   鈹?                       鈹?   鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                       鈻?                         鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                         鈹?      Unreal Editor (杩涚▼)       鈹?                         鈹?                                鈹?                         鈹?  UObject 鍙嶅皠 (TFieldIterator) 鈹?                         鈹?         鈻?          鈻?         鈹?                         鈹?         鈹?          鈹?         鈹?                         鈹?  PythonScript   CliAnything    鈹?                         鈹?    Plugin  鈼€鈹€鈹€  Bridge (C++)   鈹?                         鈹? (鎵ц娉ㄥ叆.py)  (GetClassInfo,  鈹?                         鈹?                 Viewport, ...) 鈹?                         鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?```

鏁翠綋鏋舵瀯鍩轰簬鍥涗釜鍏抽敭鏀拺锛?
**1. 鍙屽悗绔?*銆傛瀯寤烘湡鎿嶄綔锛堢紪璇?C++銆乧ook銆佹墦鍖咃級璧?subprocess 璋冪敤 UAT/UBT锛屾棤闇€ editor锛涚紪杈戞湡鎿嶄綔锛堟煡鍦烘櫙銆佹敼鏉愯川銆佹埅鍥撅級璧?Remote Control HTTP REST锛堥粯璁?`localhost:30010`锛夈€侰LI 鏍规嵁鍛戒护鑷姩璺敱銆?
**2. 鍔ㄦ€佸彂鐜板弽灏?API**銆傚湪寮曟搸渚ф彃浠堕噷鑷繁瀹炵幇 `GetClassInfo(ClassName)`鈥斺€旂敤 UE 鐨?`TFieldIterator`锛圖etails 闈㈡澘鍚屼竴濂楁満鍒讹級鐩存帴閬嶅巻 `UClass` 鐨勫睘鎬?鍑芥暟锛屽簭鍒楀寲鎴?JSON銆侰LI 灞傚湪姝や箣涓婂仛**娓愯繘寮忔姭闇?*鐨勪簩娆″皝瑁咃紙璇﹁宸紓涓€锛夈€?
**3. Python 鑴氭湰娉ㄥ叆妯″紡**銆傚姝ヤ笟鍔★紙濡?鏀逛竴涓潗璐ㄨ妭鐐瑰苟閲嶈繛"锛夋墦鍖呮垚鍔ㄦ€佺敓鎴愮殑 Python 鑴氭湰锛岄€氳繃 `exec_python_file` 涓€娆℃€у湪 editor 閲屾墽琛屽畬锛岀粨鏋滀互 JSON 杩斿洖銆備竴娆?HTTP 寰€杩斿畬鎴愬姝ユ搷浣溿€?
**4. CliAnythingBridge 鎻掍欢锛堝紩鎿庝晶 C++ 鎵╁睍锛?*銆傚皝瑁呬竴浜涘紩鎿庝腑涓嶉€氳繃鍙嶅皠鏆撮湶鐨凙PI锛屼緥濡傚師鐗堣幏鍙栨潗璐ㄧ紪璇戦敊璇笉鏆撮湶鐨勶紝杩樻槸闇€瑕侀€氳繃鎻掍欢鏆撮湶锛?
![image-20260420142644079](SHARE.assets/image-20260420142644079.png)



---

## 宸紓涓€锛欰PI 鎶湶鐨勬笎杩涘紡璁捐

### 闂

AI鎿嶄綔UE鐪熺殑鍙粰宸ュ叿灏辫浜嗕箞锛烾E缂栬緫鍣ㄥ畬鍏ㄦ槸缁欎汉绫昏璁＄殑銆?
鏈変竴娈垫椂闂达紝AI鐢╬ython鑴氭湰鎿嶄綔ue锛屽悇绉嶆姤閿?..鎶ラ敊AI鍐嶅皾璇曞叾浠栨柟寮忓張鎶ラ敊锛屽啀璇?..

鎬濊€?..浜虹被鏄€庝箞鍋氱殑銆?

鎯宠淇敼鍦烘櫙涓煇涓猘ctor鐨勬煇涓睘鎬э紝鎴戜滑鍏堬細

1. 璺宠浆鍒癘utliner闈㈡澘锛屾悳绱㈡壘鍒拌鏀圭殑鐗╀綋锛岄€変腑
2. Detail闈㈡澘閲屽睍绀轰簡鍙互淇敼鐨勫睘鎬?3. 淇敼

姣忎竴姝ュ睍绀虹殑鍐呭閮芥槸娓愯繘鐨勶紝閬垮厤涓€娆＄粰澶涓婁笅鏂囥€?
鍙互鎿嶄綔鐨勫唴瀹硅儗鍚嶶E閮介€氳繃鍙嶅皠鏈哄埗鏆撮湶缁欑敤鎴风殑锛屽彲鏀圭殑鍐呭鏄‘瀹氱殑锛屼笉鐢ㄧ寽娴嬨€?
鏍稿績鎬濊矾锛氬儚缂栬緫鍣ㄩ潰鏉块偅鏍凤紝娓愯繘寮忔毚闇茬粰AI鑳芥敼鐨勪笢瑗裤€?
### editor api-discover 宸ヤ綔娴?
鏍稿績鏄犲皠锛?*浜虹被鐐归€?Actor 鈫?閫?Component 鈫?鏀?Property** 杩欎笁姝ワ紝瀵瑰簲 CLI 涓夋潯鍛戒护銆傛瘡涓€姝ョ殑杩斿洖閮界洿鎺ュ甫鍑轰笅涓€姝ヨ鐢ㄧ殑璺緞銆?
涓嬮潰鏄幇鍦轰慨鏀瑰満鏅钩琛屽厜 `Intensity` 鐨勫畬鏁磋繃绋嬶細

#### Step 1 鈥?鎵?actor锛堝搴?World Outliner锛?
```bash
$ ue-cli --json scene list --class DirectionalLight
{
  "actors": [
    { "path": ".../VSMPerfTest:PersistentLevel.DirectionalLight_0", ... },
    ...
  ]
}
```

#### Step 2 鈥?api-discover \<actor\>锛堝搴旈€変腑 actor 鍚庣湅 Details 闈㈡澘椤堕儴锛?
```bash
$ ue-cli --json editor api-discover \
    "/Game/Test/VSMPerfTest.VSMPerfTest:PersistentLevel.DirectionalLight_0"

{
  "class": "DirectionalLight",
  "components": [
    {
      "name": "LightComponent0",
      "class": "DirectionalLightComponent",
      "path":  ".../DirectionalLight_0.LightComponent0",
      "is_root": true, "is_native": true
    }
  ],
  "hint": "To inspect a component, run: api-discover <component.path>"
}
```

#### Step 3 鈥?api-discover \<component.path\>锛堝搴旈€変腑 component 鐪嬩笅鏂瑰瓧娈靛垪琛級

```bash
$ ue-cli --json editor api-discover \
    ".../DirectionalLight_0.LightComponent0" -m intensity

{
  "class": "DirectionalLightComponent",
  "properties": ["Intensity", "IndirectLightingIntensity", "VolumetricScatteringIntensity", ...],
  "functions":  ["SetIntensity", ...],
  "component":    ".../DirectionalLight_0.LightComponent0",
  "owning_actor": ".../DirectionalLight_0"
}
```

#### Step 4 鈥?api-discover -d Intensity锛堝搴?hover 鏌愪釜瀛楁鐪嬭鎯咃級(鍙€?

```bash
$ ue-cli --json editor api-discover \
    ".../DirectionalLight_0.LightComponent0" -d Intensity

{
  "items": [{
    "kind": "property", "name": "Intensity",
    "detail": {
      "type": "float",  "owner": "LightComponentBase",
      "category": "Light",
      "tooltip": "Total energy that the light emits.",
      "read": true,  "write": true
    }
  }]
}
```

#### Step 5 鈥?scene property 璇诲啓锛堝搴斿湪 Details 闈㈡澘閲屾敼鍊硷級

```bash
# 璇?$ ue-cli --json scene property \
    ".../DirectionalLight_0.LightComponent0" Intensity
{ "Intensity": 10 }

# 鍐?$ ue-cli --json scene property \
    ".../DirectionalLight_0.LightComponent0" Intensity=20.0
{ "status": "ok" }

# 楠?$ ue-cli --json scene property \
    ".../DirectionalLight_0.LightComponent0" Intensity
{ "Intensity": 20 }
```

---

## 宸紓浜岋細鏃犲脊绐楀伐浣滄祦

### 闂

| 鍚姩UE閬囧埌寮圭獥                                               | 鍦ㄧ紪杈戝櫒涓搷浣滃唴瀹规椂                                         |
| ------------------------------------------------------------ | ------------------------------------------------------------ |
| ![image-20260420163258763](SHARE.assets/image-20260420163258763.png) | ![image-20260420163515631](SHARE.assets/image-20260420163515631.png) |

閬囧埌涔嬪悗AI鐩存帴鍗℃...闇€瑕佷汉绫讳粙鍏ャ€?


### 鏃犲脊绐楀伐浣滄祦

#### 榛樿鏃犲ご妯″紡鍚姩

- Preflight Check 鈥?鍚姩鍓嶆嫤鎴?
    鍚姩鍓嶅仛涓夐」妫€鏌ワ紝鍙戠幇闂鐩存帴鎷︿綇涓嶈鍚姩锛?
  | 瀛愭鏌?        | 鎷︽埅鐨勫脊绐?                                                  |
  | -------------- | ------------------------------------------------------------ |
  | 寮曟搸鏋勫缓妫€鏌?  | exe 缂哄け/鎹熷潖銆乵odules 涓嶅畬鏁?                               |
  | 椤圭洰鏋勫缓妫€鏌?  | BuildId 涓嶅尮閰?鈥?杩欐槸 "modules built with a different engine |
  | Remote Control | 缂哄皯閰嶇疆鏃惰嚜鍔ㄨˉ鍐欙紝閬垮厤 API 杩炰笉涓婇厤缃?                     |

    妫€鏌ュ埌閿欒鏃讹紝杩斿洖瀵瑰簲鐨勯敊璇紝AI鑷鍐冲畾淇宸ヤ綔銆?
- 缂栬緫UE鏃跺脊绐楋細鍚姩ue鏃剁敤`UnrealEditor.exe <project.uproject> -nosplash -unattended` 鍙傛暟銆?


---

## 宸紓涓夛細鏇村ソ鐨勮嚜鍔ㄥ寲

### 闂-鎴浘

UE 鑷姩鍖栨埅鍥剧殑甯歌鍋氭硶鏄帶鍒跺彴鍛戒护 `HighResShot` 鎴?`TakeScreenshot`銆傚疄闄呬娇鐢ㄤ腑閬囧埌闄愬埗锛?
- 闇€瑕佺紪杈戝櫒鑾峰緱鐒︾偣锛岃Е鍙戞覆鏌撴洿鏂?


### 瑙ｅ喅锛氭敼璧?Win32 GDI 鎶?HWND

`core/win32_editor_capture.py` 鐩存帴閫氳繃 Windows API 鎶撶紪杈戝櫒涓荤獥鍙ｏ細

```python
def capture_hwnd_to_png(hwnd: int, output_path: Path, crop_rect=None) -> bool:
    # 鍚敤 PROCESS_PER_MONITOR_DPI_AWARE锛岄伩鍏?UI scaling 骞叉壈
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    # PrintWindow + PW_RENDERFULLCONTENT锛屽洖閫€鍒?BitBlt
    # 璇?DIB bits 鍚庣敤 Pillow 瀵煎嚭 PNG
```

鎻掍欢绔仛浜嗕竴浜涜幏鍙杇ame view绐楀彛鐨勯€昏緫锛岀‘淇濆彧鎴埌game view銆?


## 鍏朵粬

- **`compress_for_agent()`**锛氳嚜鍔ㄥ帇缂╂埅鍥撅紝鍑忓皯token銆?- **`capture_screenshot_atlas()`**锛氬甯у悎鎴愪節瀹牸 PNG锛屽甫甯у彿 label銆傜敤浜庡垽鏂?鏁堟灉鏄笉鏄湪鍔?鈥斺€斿崟甯у浘鐗囨棤娉曞弽鏄犲姩鐢昏涓猴紝atlas 鍚堟垚鍚庝竴鐩簡鐒躲€?- ......



涓嶄竴涓€璇存槑锛屾牳蹇冩€濊矾灏辨槸鍑忓皯浜虹被鐨勫弬涓庯紝浼樺寲AI鐨勪娇鐢ㄦ晥鐜囥€?
---



# 闄愬埗

- 鍙祴浜嗕竴浜涙垜甯哥敤鐨勫姛鑳姐€傚叾浠栨搷浣滆摑鍥俱€佽祫浜ф垜寰堝皯鐢紝鍔熻兘涓嶅畬鍠勶紝宸ヤ綔娴佹病鏈夋鏌ヨ繃銆備絾璁捐鎬濊矾浼氱被浼笺€?- 鏈€杩戦噸鏋勪簡涓嬶紝鍙堜笉鏄壒鍒ǔ瀹氫簡銆傞渶瑕佽鐩栨洿鍏ㄩ潰鐨勫崟鍏冩祴璇曪紝鍜宔2e娴嬭瘯銆?- 娓愯繘寮忓伐浣滄祦鏈夌偣澶弗鏍间簡锛屾渶杩戝彂鐜版湁鏃跺€欐ā鍨嬬‘瀹炲彲浠ヤ竴娆″啓濂絧ython鑴氭湰锛屽伐浣滄祦浣滀负琛ュ厖寤鸿杈冨ソ銆備絾瀵逛簬鑷畾涔夊紩鎿庢潵璇达紝妯″瀷澶╃敓涓嶇煡閬撴墍鏈夋敼鍔紝宸ヤ綔娴佽繕鏄渶绋冲Ε鐨勬柟娉曘€?
