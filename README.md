# In Falsus — 오픈소스 한글패치

## 번역 작업 이력 (모델 크레딧)

- **1~63화, 86화 이후**: DeepSeek V4.1 Flash가 번역과 교정을 모두 담당했습니다.
- **64~85화**: Opus 5가 별도의 교정 단계 없이 직접 번역했습니다.
- 패치 제작자로서 직접 플레이해가며 실시간으로 수동 검수를 진행하고 있습니다.

## 이 프로젝트의 원칙

이 저장소는 다음 원칙을 지킵니다.

- **저작권이 있는 원본 콘텐츠는 절대 배포하지 않습니다.** 이 저장소가
  담고 있는 것은 우리가 직접 작성한 한국어 번역 텍스트(`translation/`),
  도구 코드(`tools/`), 문서(`docs/`)뿐입니다. 게임의 스크립트·이미지·
  폰트·바이너리 등 원본 콘텐츠는 단 한 바이트도 커밋되지 않으며, 이런
  파일들은 각자 소유한 게임 사본에서 실행 시점에 로컬로 추출되어
  `work/`, `patch/`, `backups/`에 생성됩니다 — 이 세 디렉터리는 모두
  `.gitignore`에 등록되어 있고 절대 배포되지 않습니다. 이 도구를 쓰려면
  In Falsus를 정식으로 소유하고 있어야 합니다.
- **한국어 번역은 완전한 오픈소스입니다.** `translation/` 아래의 모든
  파일은 게임 원문을 전혀 포함하지 않는, 우리가 직접 작성한 창작물이며
  누구나 자유롭게 읽고 검토하고 고칠 수 있습니다. 오탈자 수정, 어색한
  문장 개선, 누락된 항목 번역 등 기여는 언제나 환영합니다.
- **게임에 DLL이나 코드를 주입하지 않습니다.** `GameAssembly.dll`이나
  다른 실행 코드를 패치하거나 후킹하거나 여기에 무언가를 주입하는 일은
  하지 않습니다. 이 도구가 건드리는 것은 오직 게임이 이미 제공하는
  데이터 파일(에셋 번들, `resources.assets` 등)뿐이며, 그마저도 이미
  게임 자체에 존재하는 다국어 데이터 구조 안의 값을 채워 넣는 것에
  그칩니다. 네이티브 IL2CPP 스위치문을 패치해야 진짜 한국어 로케일을
  활성화할 수 있다는 사실을 알고 있지만(§4.7 참고), 이는 위험 부담이
  크다고 판단해 의도적으로 하지 않습니다.
- **패치는 순수한 에셋 교체(swap)입니다.** 이 도구가 만드는 패치는
  텍스트 문자열 필드와 폰트 바이너리를 게임이 원래 쓰던 포맷 그대로
  교체하는 것뿐입니다. 새 로직을 추가하거나, 실행 파일을 수정하거나,
  게임의 동작 방식을 바꾸는 일은 전혀 없습니다. 패치 적용은 파일을
  게임 설치 폴더 위에 그대로 덮어쓰는 것으로 끝나며, 같은 이유로
  `restore` 한 번이면 원본으로 완전히 되돌릴 수 있습니다.

이 번역 전략은 **"영어 로케일에 얹어가기(English-locale carry)"**
방식입니다: 게임은 계속 *영어* 로케일로 실행하되, `English` 문자열
필드 자체를 한국어 텍스트로 채웁니다. 네이티브 코드를 패치할 필요가
없습니다(한국어 로케일은 데이터 구조상으로는 연결되어 있지만 네이티브
스위치문에서 비활성화되어 있습니다 — 아래 "왜 한국어 로케일을 직접
켜지 않는가?" 참고).

---

**In Falsus**(lowiro)의 비주얼노벨 파트를 추출·번역·재조립하기 위한
도구와 문서입니다. 게임을 손상시키지 않고 작동합니다.

이 게임은 Unity 6000.3(IL2CPP) 타이틀로, 데이터 구조상 이미 5개 언어
(영어, 일본어, 한국어, 중국어 번체, 중국어 간체)를 지원하도록 설계되어
있습니다. 하지만 출시된 빌드에는 **한국어 문자열이 비어 있고**, 설정
화면에도 한국어 옵션이 노출되어 있지 않습니다. 이 도구는 번역 가능한
모든 문자열을 일반 JSON으로 추출하고, 번역자가 한국어를 채워 넣은 뒤,
원래 포맷 그대로 다시 패킹할 수 있게 해줍니다.

## 1. 요구 사항

```bash
cd tools
python3 -m venv ../.venv
../.venv/bin/pip install -r requirements.txt   # UnityPy
```

## 2. 게임 설치 위치 찾기

이 도구는 게임 설치 위치를 자동으로 탐지합니다(Windows/WSL/macOS의
흔한 Steam 라이브러리 경로를 탐색합니다). 직접 지정할 수도 있습니다:

```bash
# 플래그로 지정
../.venv/bin/python tools/ifalsus.py --game-path "D:\SteamLibrary\steamapps\common\In Falsus" locate
# (WSL에서는: /mnt/d/SteamLibrary/steamapps/common/In Falsus)

# 환경 변수로 지정
export INFALSUS_GAME_PATH="/mnt/d/SteamLibrary/steamapps/common/In Falsus"
```

`locate`는 도구가 찾아낸 모든 정보를 출력합니다: 번들 디렉터리, SAM
디렉터리, 각 데이터 에셋이 들어 있는 번들.

## 3. 명령어 개요

**평소에는 두 개의 명령어만 있으면 됩니다:**

```bash
.venv/bin/python tools/ifalsus.py unpack   # 게임 -> 번역 가능한 파일
# ...translation/ko/*.txt 와 translation/*.tsv 를 번역...
.venv/bin/python tools/ifalsus.py repack   # 번역 파일 -> patch/
```

`unpack`은 모든 `extract-*` 단계를 실행하고, 이미 커밋되어 있는 한국어
번역을 `work/`에 자동으로 합쳐 줍니다. `repack`은 `translation/`을
`work/`로 동기화하고, 무결성 검사(`verify`)를 실행한 뒤, 문제가
발견되면 **아무것도 쓰지 않고 그 자리에서 중단**합니다(그래도 강행하고
싶다면 `--skip-verify`). 검사를 통과하면 텍스트 계열 `pack-*` 단계를
모두 실행해 바로 배포 가능한 `patch/`를 만들어 냅니다. 폰트는 번역/패킹
루프에 포함되지 않는 일회성 바이너리 교체 작업입니다 — §4.6의
`pack-fonts` 참고.

아래 표는 `unpack`/`repack`이 내부적으로 실행하는 단계들입니다. 개별
명령어는 한 단계만 따로 실행하고 싶을 때만 직접 쓰면 됩니다(예: 문구
하나 고친 뒤 UI 문자열만 다시 패킹하는 경우).

| 명령어               | 방향 | 하는 일 |
|-----------------------|-----------|--------------|
| `unpack`               | 출력       | 아래 모든 `extract-*` 단계를 실행한 뒤 `translation/`을 `work/`로 동기화 |
| `repack`               | 출력       | 동기화 → `verify` → 아래 텍스트 `pack-*` 단계를 모두 실행 |
| `locate`              | 읽기      | 탐지된 게임 경로 출력 |
| `index`               | 읽기      | 모든 AssetBundle을 한 번 스캔(`work/bundle_index.json`에 캐시, 재개 가능) |
| `extract-scripts`     | 출력       | SAM 스크립트 파일 290개를 복호화해 `work/scripts/`로 |
| `pack-scripts`        | 출력       | 수정된 스크립트를 다시 암호화해 `patch/`로 (선택 사항; EN-locale 방식에서는 필요 없음) |
| `extract-translations`| 출력       | 대사 테이블을 `work/translations/`로 덤프 |
| `extract-context`     | 출력       | 화자 정보를 스토리별 파일에 병합 |
| `pack-translations`   | 출력       | 수정된 대사를 `patch/`로 패킹 |
| `extract-names`       | 출력       | 캐릭터 이름 테이블을 `work/names/names.json`으로 덤프 |
| `pack-names`          | 출력       | 수정된 이름을 `patch/`로 패킹 |
| `extract-ui-strings`  | 출력       | UI 텍스트(`StringsMapping`)를 `work/ui_strings/`로 덤프 (`work/il2cpp_dlls/` 필요, §4.5 참고) |
| `pack-ui-strings`     | 출력       | 수정된 UI 문자열을 `patch/infalsus_Data/resources.assets`로 패킹 |
| `extract-fonts`       | 출력       | 내장 폰트를 `work/fonts/`로 추출 |
| `list-fonts`          | 읽기      | 폰트 패밀리와 로케일별 폰트 세트 표시 |
| `pack-fonts`          | 출력       | 내장 폰트 바이너리를 교체 → `patch/` |
| `verify`              | 읽기      | 무결성 검사(커버리지, 개수, 폰트 유효성) |
| `restore`             | 입력       | `backups/`에서 모든 원본 파일 복원 |

번역자용 보조 스크립트:

| 스크립트                        | 하는 일 |
|-------------------------------|--------------|
| `tools/dump_jp.py <NNN>`      | 스토리를 `id [화자] 일본어` 형태로 출력 (루비 태그 제거) |
| `tools/apply_ko.py <NNN> <f>`| 번역된 줄을 `translation/ko/<NNN>.txt`에 병합 |
| `tools/ko_io.py export\|sync` | `translation/`과 `work/` 사이에서 한국어 텍스트를 이동 |

`translation/ko/<NNN>.txt`는 `<id><TAB><korean>` 형태로 한 줄에 한
항목씩 들어 있으며, 텍스트 안의 줄바꿈은 `⏎`(U+23CE)로 표시합니다.
대사창은 최대 3줄까지 표시할 수 있으며, 일본어 원문의 줄 수와 반드시
같을 필요는 없습니다.

모든 `pack-*` 명령어는 작업공간의 **`patch/` 디렉터리**(게임 디렉터리
구조를 그대로 반영)에만 결과물을 씁니다 — **게임 설치 폴더에는 절대
쓰지 않습니다.** 이 덕분에 `patch/`는 그대로 배포 가능합니다: zip으로
묶으면 사용자가 게임 루트 위에 압축을 풀기만 하면 됩니다. 패치를
만들기 전에 이 도구는 건드리는 파일마다 게임의 현재 사본을
`backups/`에 백업해 두므로(`restore`로 적용한 패치를 되돌릴 수
있습니다), 모든 pack 명령어는 `--dry-run`을 지원해 실제로 쓰지 않고
검증만 할 수도 있습니다.

## 4. 게임이 스토리 콘텐츠를 저장하는 방식

### 4.1 디렉터리 구조

```
In Falsus/
└── infalsus_Data/
    ├── StreamingAssets/
    │   ├── aa/
    │   │   ├── catalog.bin               # Unity Addressables 카탈로그 (바이너리)
    │   │   └── StandaloneWindows64/      # *.bundle 파일 1804개 (해시 이름)
    │   └── sam/                          # GUID로 이름 붙은 파일 10,346개, 암호화됨
    └── il2cpp_data/                      # GameAssembly.dll은 설치 루트에 있음
```

### 4.2 SAM 스크립트 파일 (`StreamingAssets/sam/`)

비주얼노벨 스크립트는 고정된 8바이트 반복 XOR 키로 암호화된 일반
텍스트 파일입니다:

```
key: f0 16 28 4b 7d 9e c3 a5        (복호화 = 암호화: 양방향 XOR 동일)
```

`StreamingAssetsMapping.asset`(`Assets/BuildSpecificAssets/release/StreamingAssetsMapping.asset`
경로의 Addressables 에셋)이 모든 파일의 `FullLookupPath` → `Guid`를
매핑하며, 실제 파일은 확장자 없이 `sam/<Guid>`에 위치합니다. 스크립트
파일은 경로가 `.sps`(스토리 스크립트 236개), `.spp`(2개:
`names.spp`, `common.spp`), `.spi`(애니메이션 조각 52개)로 끝나는
290개 항목입니다. 나머지 약 1만 개 파일은 오디오(`.wav`/`.ogg`)와
악곡 차트(`.spc`)로, 이들은 *다른* 암호화 방식을 쓰며 이 도구가
건드리지 **않습니다.**

복호화된 스크립트 예시:

```
include "scripts/names.spp"
include "scripts/common.spp"

"scene_start"
{
	bg_init $schoolHallA $bgRight
	screen_textbox show 1.0
	char_show "ayame" $charShowCenter
	...
}

id 167-001
s `I sent a message out to everyone in AARC.`

id 167-007
s $Ay `"Friend! Good. You're here!"`
```

스크립트 문법 요약:

- `id NNN-NNN` — 뒤따라오는 대사에 고유한 텍스트 id를 부여합니다.
  **번역 테이블에도 같은 id가 존재하며**(4.3 참고), 이 id가 스크립트와
  로케일별 텍스트를 이어 주는 연결고리입니다.
- `s \`text\`` — 대사 줄(내레이션). `s $Xy \`text\`` — 화자가 있는
  대사 줄; `$Xy`는 `names.spp`에서 풀리는 별칭입니다(예:
  `alias $Ay "Ayame"`).
- `phone message left|right $Xy \`text\`` — 폰 채팅 대사(마찬가지로
  id가 붙음).
- `choice "name" "label" { ... }` — 선택지 블록; 여기서 선택지
  라벨은 단순 문자열(출시 스크립트에서는 숫자)이며 로케일화되어 있지
  않습니다.
- 그 외 명령어들(모두 번역 대상이 아닌 연출/연기 지시):
  `bg_init`, `bgm`, `sfx`,
  `char_show/char_clothes/char_expression/char_bind/char_eyes`, `show`,
  `hide`, `move`, `color`, `tint`, `invoke`, `delay`, `wait`, `cancel`,
  `screen_textbox`, `fastforward`, `alias`, `include`, 블록
  `"name" { ... }`.
- **모든 `s` 줄에는 `id`가 있고, 모든 스크립트 id는 번역 테이블에
  존재합니다**(스크립트 id 17994개, 테이블 항목 18015개 — 테이블 항목
  중 21개는 사용되지 않음). 인라인 영어 텍스트는 어디까지나 폴백일
  뿐입니다.

### 4.3 대사 텍스트: `StoryTranslationDetails.asset`

Addressables 주소는
`Assets/BuildSpecificAssets/release/StoryTranslationDetails.asset`
(빌드 25416896 기준으로는 `115644c65e7b0db39ef14d00db334253.bundle`
번들 안에 있습니다 — **번들 파일 이름은 빌드마다 바뀌므로 항상 주소로
찾아야 합니다**).

필드 하나짜리 단일 `MonoBehaviour`(ScriptableObject)입니다:

```csharp
public List<StringMapping> Translations;   // 18,015개 항목

public struct StringMapping {
    public string Id;            // "001-001" ~ "236-029" — 스크립트의 `id`와 일치
    public string English;
    public string Japanese;
    public string Korean;        // 출시 빌드에서는 비어 있음
    public string ChineseTC;
    public string ChineseSC;
}
```

이것이 **유일한 로케일별 대사 소스**입니다. 실행 시점에
`StoryCommandProcessor`가 `Strings.GetDynamic(StoryText, id)`를
호출하며, 테이블에 현재 로케일용 문자열이 비어 있지 않으면 그것을
표시하고, 그렇지 않으면 스크립트에 적힌 인라인 텍스트(영어)를
표시합니다.

참고 사항:

- 일본어 칼럼에는 `<ruby>…<rt>…</rt></ruby>` 마크업(후리가나 주석)이
  들어 있습니다 — 번역자는 이를 참고해서 읽되, 결과물은 마크업 없는
  순수한 한국어여야 합니다(EN 칼럼에는 애초에 마크업이 없습니다).
- `.sps` 스크립트는 번역자에게 여전히 중요한 자료입니다: 각 줄의
  **화자**, 연출, 장면 맥락을 알려 줍니다. `extract-context`가
  `SpeakerRaw`/`SpeakerAlias`/`Script` 정보를 스토리별 JSON 파일에
  병합해 줍니다.

### 4.4 캐릭터 이름: `DynamicStringMapping.asset`

Addressables 주소는
`Assets/BuildSpecificAssets/release/DynamicStringMapping.asset`입니다.
여러 문자열 테이블을 담고 있는데, 대사창에서 쓰이는 것은 이것입니다:

```
rawStoryNameTypeMapping: { Ids: [{Value: "Nia"}, ...],           # 원본 이름 129개
                           IdValues: [{English, Japanese, Korean, ...}, ...] }
```

실행 시점 흐름: 스크립트의 `s $Ni` → 별칭 `$Ni` → `"Nia"`
(`names.spp`에서) → `rawStoryNameTypeMapping`에서 원본 이름
`"Nia"`를 조회 → 현재 로케일용 표시 이름(일본어의 경우 `ニア`).

129개 한국어 필드가 전부 비어 있습니다. 같은 에셋에는
`songIdTitleTypeMapping`, `songIdArtistTypeMapping`,
`cardNameTypeMapping` 등도 들어 있는데, 이들은 **게임플레이 문자열이므로
건드리지 않아야 합니다.** `pack-names`는 오직
`rawStoryNameTypeMapping`만 수정합니다.

이 도구가 건드리지 않는 그 밖의 이름/문자열 테이블:

- **스토리 타이틀 카드**: 로케일별 PNG
  `sp-story/assets/text/<name>_<jp|en|hans|hant>.png` — 텍스트가 아닌
  이미지입니다. 한국어 버전이 아예 없어서 EN 로케일에서는 영어 이미지로
  폴백됩니다. 이 프로젝트의 범위 밖입니다.

### 4.5 UI 문자열: `StringsMapping` (`infalsus_Data/resources.assets`)

허브 라벨, 버튼, 타임라인/곡 선택/제작 화면 텍스트, 설정 항목 이름,
튜토리얼 문구 등 모든 UI 텍스트는 하나의 `Str.StringsMapping`
ScriptableObject(실행 시점에 `Resources.Load("StringsMapping")`으로
로드됨)에서 나옵니다. 평평한 `List<TextMapping>` 구조로, 각 항목은
`{Key (Str.Strings.Key 열거형, int), English, Japanese, Korean,
TraditionalChinese, SimplifiedChinese, HasMappingBitMask}`입니다. 이
빌드 기준 1,261개 항목이 있으며, 모든 `Korean` 필드가 비어서
출시됩니다. 직접 문자열 검색으로 확인됨: `SELECT SONG`, `VIEW
TIMELINE`, `RECIPES`, `CARDS`, `CONTINUE`, `UNREAD`, `The First Lie`
같은 챕터 제목 등이 전부 여기에 들어 있습니다.

이 에셋은 이 도구의 다른 모든 명령어가 다루는 Addressables 번들 시스템
(`StreamingAssets/aa/`)에 **속해 있지 않습니다** — 메인 IL2CPP 데이터
파일의 일부이며, addressable 번들과 달리 **임베디드 Unity
typetree가 없어서**(빌드 시점에 스트립되는 것이 IL2CPP 메인 데이터
파일의 일반적인 특성입니다) UnityPy가 기본 설정만으로는 이 안의
MonoBehaviour를 읽을 수 없습니다.

읽고 쓸 수 있게 만들기 위한 **일회성 설정**: 자신의 게임에 있는
`GameAssembly.dll` + `global-metadata.dat`로부터
[Cpp2IL](https://github.com/SamboyCoding/Cpp2IL)을 이용해 스텁
("DummyDLL") 어셈블리를 생성하고(`dummydll` 출력 형식), 이를
`work/il2cpp_dlls/`에 둡니다(gitignore 대상; 각자의 설치본에서
재생성하며, 절대 재배포되지 않습니다):

```bash
Cpp2IL --game-path "<In Falsus 설치 디렉터리>" \
    --output-as dummydll --output-to work/il2cpp_dlls
```

`pip install TypeTreeGeneratorAPI`(이미 `requirements.txt`에 포함)가
이 DLL들을 UnityPy가 쓸 수 있는 typetree generator로 바꿔 주는 네이티브
바인딩을 제공합니다 — 이는 UnityPy가 IL2CPP 바이너리를 직접 파싱하려는
경로(`load_il2cpp`)와는 *다른* 경로이며, 그 경로는 현재 이 게임의
Unity 6000.3.9f1 / il2cpp 메타데이터 v39 빌드에서 실패합니다
(`Fatal Exception initializing LibCpp2IL!` — LibCpp2IL 쪽의 상위
호환성 문제이며, 이쪽에서 고칠 수 있는 부분이 아닙니다).
`load_dll()`로 DummyDLL을 불러오면 이 문제를 완전히 우회해서 깔끔하게
동작합니다.

`extract-ui-strings`는 각 항목에 열거형 멤버 이름도 함께 붙여
줍니다(`Hub_SelectSong`, `Recipes_Upper`, `TimeOfDay_LateNightUpper`
등). 이 이름은 `work/il2cpp_dlls/Str.Strings.cs`(위 Cpp2IL 단계 이후
`Str.dll`을 예를 들어 `ilspycmd`로 디컴파일한 일반 텍스트 파일)에서
파싱합니다. 이 라벨은 순전히 번역자가 보기 편하라고 붙이는 것일
뿐입니다. `pack-ui-strings`는 이름이 아니라 원시 정수 `Key`로 항목을
매칭하므로, 패킹 자체에는 이 라벨이 필요 없습니다.

```bash
.venv/bin/python tools/ifalsus.py extract-ui-strings
# -> work/ui_strings/ui_strings.json, ui_strings.tsv (Key, KeyName, English, Japanese, Korean)
#    -- gitignore 대상; 다른 work/ 파일과 마찬가지로 원본 영어/일본어를 담고 있음
.venv/bin/python tools/ko_io.py sync
# -> translation/ui_strings.tsv(커밋된 한국어, Key + KeyName만 있고
#    게임 원문은 없음)를 work/ui_strings/ui_strings.json의 Korean 칼럼으로 끌어옴
.venv/bin/python tools/ifalsus.py pack-ui-strings [--locale-map Korean->English] [--dry-run]
# -> patch/infalsus_Data/resources.assets (게임 설치 폴더는 절대 아님)
```

`translation/ui_strings.tsv`가 이 데이터의 커밋된 원본입니다 —
`translation/names.tsv`와 같은 `<id><TAB>...<TAB>korean>` 형태로 직접
수정해서 번역하고, 패킹 전에 `ko_io.py sync`를 실행하면 됩니다.
`ko_io.py export`는 그 반대 방향으로, `work/ui_strings/ui_strings.json`에
현재 들어 있는 한국어를 커밋된 TSV로 되돌려 씁니다 — 이 파일이 처음
만들어질 때 쓰인 방법이며, TSV가 아니라 `work/` 사본을 직접 수정했을
때만 다시 필요합니다.

다른 모든 곳과 동일한 EN-locale-carry 전략을 씁니다: `pack-ui-strings`는
`Korean` 칼럼을 `English` 필드(게임이 영어 로케일로 실행되는 한
실제로 화면에 표시되는 필드)로 복사하고, `Korean` 필드 자체는 건드리지
않습니다 — 게임의 로케일 자체를 바꾸려는 시도는 하지 않습니다(왜
그런지는 §4.7 참고). 패치 적용은 다른 모든 파일과 마찬가지로
`resources.assets`를 그 자리에서 그대로 덮어쓰는 것뿐입니다 —
`globalgamemanagers.assets`는 건드리거나 배포되는 일 없이 참조만
됩니다(패치된 파일 사본을 따로 떼어내 디버깅용으로 다시 열 때만 옆에
있어야 하며, 그럴 때 UnityPy가 재파싱 과정에서 그 파일을 참조로
따라갑니다).

### 4.6 폰트 (FastText)

게임은 모든 텍스트를 **FastText**(HarfBuzz 셰이핑 + FreeType로 원본
폰트 바이너리에서 실행 시점에 SDF 래스터화)로 렌더링합니다. 폰트
데이터:

- 번들 하나(`FastTextFontFamily`/`FastTextAsset` MonoScript 상호
  참조로 찾음)에 `FastTextAsset` ScriptableObject 25개(`Identifier` +
  `RawBytes` = **원본 TTF/OTF 바이트**)와 `FastTextFontFamily`
  ScriptableObject 12개가 들어 있습니다.
- 한 패밀리는 `fontAssets[6]`을 가지며, 슬롯은 스타일별로 인덱싱됩니다:
  `0=Regular, 1=Bold, 2=Italic(미사용), 3=Light, 4=Medium, 5=SemiBold`.
- `supportsLocalization=1`인 패밀리는
  `nonEnglishLocalizationToFontSet[4]`도 가지고 있습니다(영어 외
  로케일마다 하나씩: 일본어, 한국어, 중국어 번체, 중국어 간체 —
  **한국어는 이미 `NotoSerifKR-Regular`/`NotoSerifKR-Bold`로 완전히
  연결되어 있습니다**).

EN-locale 접근 방식과 관련 있는 패밀리들:

| 패밀리 | EN 기본 폰트 | 쓰이는 곳 |
|--------|---------------|---------|
| `DefaultFontSet` | Supreme-Regular/Bold/Medium | 일반 EN UI |
| `StoryTextFontSet` | Supreme-Regular/Bold/Medium | 스토리 UI (JP/CN 텍스트 오브젝트) |
| `StylisedTitleFontSet` | BaiJamjuree-* 5가지 굵기 | 대사창 **이름표**, 타이틀 |
| `NumberFontSet` | BaiJamjuree-* | 곳곳의 숫자 |
| `ShinGOFontSet` | OT-PUDShinGoPr6N-Regular, AP-OTF-UDShinGoPr6N-DeBold/Light | 일부 허브/곡 선택/제작 화면 UI |

대사 텍스트 자체(스토리 씬의 `StorySegmentText`)는 `ForceSupreme`
패밀리를 참조하며, 이것의 EN 기본 폰트 역시 Supreme-*입니다.

`ShinGOFontSet`은 나머지 네 패밀리와는 별개의 사안입니다:
`supportsLocalization=0`이고 `nonEnglishLocalizationToFontSet`이
**아예 없습니다**(네 슬롯 모두 `pid:0`). 즉 어떤 경우에도 로케일에
따라 폰트를 바꾸지 않으므로, `StringsMapping`의 UI 문자열만 패치해서는
(§4.5) 이 패밀리를 참조하는 UI 요소들이 해결되지 않습니다 — 이
패밀리만의 EN 기본 폰트 바이너리(Supreme-*/BaiJamjuree-*와는 완전히
다른 별도의 세트)도 다른 것들과 마찬가지로 교체해야 합니다.

EN 기본 폰트들에는 한글이 전혀 들어 있지 않으므로, **EN 기본 폰트
바이너리를 교체하지 않으면** EN 로케일에서 표시되는 한국어 텍스트는
전부 tofu(네모 글자)로 나옵니다.

**이 프로젝트는 NanumBarunGothic**(네이버)을 사용합니다. 고딕(산세리프)
계열 서체라서 이 서체가 대체하는 Supreme-*/BaiJamjuree-* 서체들의
디자인과 어울립니다. 게임에 이미 내장된 `NotoSerifKR`은 *세리프*
서체라서 UI 전체의 인상이 달라지므로 쓰지 않았습니다.
NanumBarunGothic은 자유로운 사용·수정·재배포를 허용하는 라이선스(OFL)를
따르므로, 이 저장소는 **수정된 폰트 바이너리를 직접 포함합니다**:
`fonts/`에 세 가지 굵기(`NanumBarunGothic.ttf`,
`NanumBarunGothicBold.ttf`, `NanumBarunGothicLight.ttf`)와 라이선스
원문 `fonts/NanumBarunGothic-LICENSE.txt`가 들어 있습니다(패치 재배포
시 라이선스는 반드시 함께 동봉해야 합니다).

> **폰트 세로 메트릭 패치 (패치 제작 노트).** 원본 NanumBarunGothic은
> 행 높이(세로 메트릭)가 교체 대상이던 원본 폰트들보다 좁습니다
> (참고: Supreme 1.35 em, BaiJamjuree 1.25 em, NanumBarunGothic
> 1.15 em). 게임의 FastText는 실행 시점에 **폰트 자체의 세로
> 메트릭**으로 줄 높이를 계산하기 때문에, 카드 이름처럼 `\n`으로 두
> 줄이 되는 텍스트에서 한국어 줄 간격이 거의 0에 가깝게 붙어 보이는
> 문제가 있었습니다. 그래서 `fonts/`의 세 폰트는 `hhea`/`OS/2`의
> `ascender`와 `descender`를 키우고 `lineGap`은 그대로 두었습니다
> (unitsPerEm 1000):
>
> | 메트릭 | 기본값 (배포 전) | 패치 후 (`fonts/`) |
> |---|---|---|
> | `hhea.ascender` / `descender` / `lineGap` | 850 / -299 / 0 | 1350 / -550 / 0 |
> | `OS/2.sTypoAscender` / `sTypoDescender` / `sTypoLineGap` | 850 / -300 / 0 | 1350 / -550 / 0 |
> | `OS/2.usWinAscent` / `usWinDescent` | 850 / 300 | 1350 / 550 |
>
> `lineGap`은 이 게임의 FastText가 줄 간격 계산에 반영하지 않아
> 0으로 두었습니다. 이 패치는 패킹 스크립트가 아니라 폰트 파일 자체에
> 반영되어 있으므로, 아래 `pack-fonts`는 `fonts/`의 파일을 그대로 쓰면
> 됩니다. 원본(기본) 폰트가 필요하면 `tools/fetch_fonts.sh`로 받을 수
> 있습니다(이 경우 위 메트릭 패치는 적용되지 않고 기본값이 됩니다).

```bash
.venv/bin/python tools/ifalsus.py pack-fonts \
    --set Supreme-Regular=fonts/NanumBarunGothic.ttf \
    --set Supreme-Bold=fonts/NanumBarunGothicBold.ttf \
    --set Supreme-Medium=fonts/NanumBarunGothicBold.ttf \
    --set BaiJamjuree-Regular=fonts/NanumBarunGothic.ttf \
    --set BaiJamjuree-Bold=fonts/NanumBarunGothicBold.ttf \
    --set BaiJamjuree-Light=fonts/NanumBarunGothicLight.ttf \
    --set BaiJamjuree-Medium=fonts/NanumBarunGothicBold.ttf \
    --set BaiJamjuree-SemiBold=fonts/NanumBarunGothicBold.ttf \
    --set OT-PUDShinGoPr6N-Regular=fonts/NanumBarunGothic.ttf \
    --set AP-OTF-UDShinGoPr6N-DeBold=fonts/NanumBarunGothicBold.ttf \
    --set AP-OTF-UDShinGoPr6N-Light=fonts/NanumBarunGothicLight.ttf
```

굵기 매핑은 Regular→Regular, Light→Light, Bold/Medium/SemiBold→Bold
입니다(Nanum에는 Medium이나 SemiBold가 따로 없습니다).

`pack-fonts --preset notokr`는 다운로드 없이 쓸 수 있는 대안으로 남겨
두었으며, 게임에 이미 내장된 `NotoSerifKR` 바이트를 그대로 씁니다.

트레이드오프(문서화된, 받아들인 사항): EN 기본 폰트들은 영어 로케일의
*모든* UI가 공유하므로, UI 전체가 대체 폰트로 렌더링됩니다. 이것이
가장 단순하고 안정적인 방식입니다. 컴포넌트별로 정교하게 폰트를 따로
지정하는 것도 나중에 가능하지만, 그러려면 씬 프리팹을 건드려야 합니다.

### 4.7 언어 선택 내부 구조 (왜 EN-locale 방식을 쓰는가)

디컴파일로 확인한 사실입니다(Cpp2IL, IL2CPP 메타데이터 v39, Unity
6000.3.9f1):

- `Str.Strings.Localization` 열거형: `Unset=0, English=1, Japanese=2,
  Korean=3, ChineseTC=4, ChineseSC=5`.
- 저장된 로케일 설정(PlayerPrefs의 int 값)은
  `Strings.SetDefaultLocalization`을 통해 적용되는데, 이 함수의 switch
  문은 **영어/일본어/중국어 번체/중국어 간체만** 처리합니다 —
  `Korean`은 영어로 폴백됩니다(raw IL로 직접 확인: 대상 값이 1, 2,
  4, 5뿐입니다).
- 설정 화면 드롭다운의 선택지는 4개짜리 정적 배열에서 옵니다
  (`_Tg._zWA`: EN/JP/TC/SC) — 한국어는 의도적으로 제거되어 있고,
  인덱스↔로케일 매퍼(`_xf`/`_Xf`)에도 마찬가지로 한국어 케이스가
  없습니다.
- 그럼에도 한국어는 그 외의 모든 곳에 이미 배선되어 있습니다: 열거형,
  `Settings_Korean` UI 문자열 키, 모든 문자열 테이블의 로케일별
  필드, 로케일별 **폰트 세트**, 그리고 데이터 전반에 비어 있는
  `Korean` 필드들.

진짜 한국어 로케일을 활성화하려면 `GameAssembly.dll`의 네이티브
IL2CPP switch문을 패치해야 하는데, 이는 위험하다고 판단해 하지
않습니다. EN-locale-carry 방식은 **네이티브 패치가 전혀 필요
없습니다.**

## 5. 번역 작업 흐름

이미 진행된 번역이 따르고 있는 용어·캐릭터 말투 결정은
`docs/glossary.md`와 `docs/characters.md`를 참고하세요.

```bash
# 0. 최초 1회
.venv/bin/python tools/ifalsus.py unpack
.venv/bin/python tools/ifalsus.py pack-fonts --set ...   # §4.6 참고 (NanumBarunGothic; 1회성)

# 1. 번역: tools/dump_jp.py로 읽고, tools/apply_ko.py로 씀
#    원본 소스는 translation/ko/<NNN>.txt, translation/names.tsv,
#    translation/ui_strings.tsv, translation/card_names.tsv,
#    translation/encounter_names.tsv, translation/recipe_names.tsv

# 2. 패킹 -- 동기화, 무결성 검사를 거친 뒤 patch/에 씀 (게임 폴더는
#    절대 수정하지 않으며, 검사에 실패하면 repack이 아무것도 쓰지 않고 중단됨)
.venv/bin/python tools/ifalsus.py repack

# 3. 수동으로 적용: patch/의 내용을 게임 루트 위에 복사
#      예:  cp -r patch/infalsus_Data "$INFALSUS_GAME_PATH/"

# 4. 게임을 실행(영어 로케일)해서 스토리 장면을 확인

# 언제든 롤백 가능 (backups/의 원본으로 게임을 복원)
.venv/bin/python tools/ifalsus.py restore
```

`repack`은 `Korean` 필드가 **비어 있지 않은 경우에만** 그 값을
`English` 필드로 복사합니다 — 아직 번역되지 않은 줄은 원래 영어
그대로 남습니다. 한국어 로케일이 언젠가 네이티브로 활성화된다면
`--locale-map Korean->Korean`을 대신 쓰면 됩니다.

## 6. 저장소 구조

이 프로젝트가 배포하는 것은 **한국어 번역, (수정된) 폰트, 도구,
문서**뿐입니다 — 게임 원본 콘텐츠는 그 외에는 아무것도 없습니다:

```
translation/                    # 우리의 결과물 -- 우리가 배포하는 번역 데이터
├── ko/<NNN>.txt                 # 한국어 스크립트, `<id><TAB><korean>`
├── names.tsv                    # 한국어 캐릭터 이름, `<raw><TAB><korean>`
├── ui_strings.tsv               # 한국어 UI 텍스트, `<Key><TAB><KeyName><TAB><korean>`
├── card_names.tsv               # 카드 이름, `<Id><TAB><IdStr><TAB><korean>`
├── encounter_names.tsv          # 조우/Reflect 제목, `<Id><TAB><IdStr><TAB><korean>`
└── recipe_names.tsv             # 설계도(레시피) 이름, `<Id><TAB><IdStr><TAB><korean>`
fonts/                          # 행간이 패치된 NanumBarunGothic + 라이선스 (§4.6)
tools/                          # 추출 / 패킹 / QA 도구
docs/                           # 작업 흐름, 스타일 가이드, 용어집, 캐릭터 정보
```

아래는 전부 **로컬 게임 설치본에서 생성되는, gitignore 대상이며 절대
재배포되지 않는** 파일들입니다 — 원본 게임의 스크립트와 에셋을
담고 있습니다:

```
work/                           # 추출된, 도구가 다루는 데이터
├── bundle_index.json            # 캐시된 번들 스캔 결과 (지우면 다시 스캔)
├── scripts/                     # 복호화된 .sps/.spp/.spi (번역자 참고용)
├── translations/by_story/<NNN>.json   # JP/EN/CN + 화자 정보 + 우리 한국어
├── names/names.json             # 전체 캐릭터 이름 테이블
├── ui_strings/ui_strings.json   # 모든 UI 문자열의 JP/EN/CN + 우리 한국어
├── il2cpp_dlls/                  # Cpp2IL DummyDLL, UI 문자열 읽기/쓰기에 필요
└── fonts/                       # 추출된 TTF/OTF + fonts.json
patch/                          # 패킹 결과물; 게임 디렉터리 구조를 그대로 반영
backups/                        # 이 도구가 덮어쓸 모든 파일의 원본
```

`extract-*` 명령어들과 그 뒤에 `tools/ko_io.py sync`(이 저장소의
한국어를 다시 써 넣음)를 실행하면 언제든 `work/`를 다시 생성할 수
있습니다.

## 7. 알려진 제약 사항 / 주의할 점

- **번들 파일 이름은 빌드마다 바뀝니다.** 항상 에셋을 Addressables
  주소로 찾아야 합니다(이 도구는 그렇게 하고 있습니다; 게임이
  업데이트되면 `index`를 다시 실행하세요).
- **이름표 색상**: 스토리 이름표는 *표시되는* 이름을 접두사로
  매칭해서 배경색을 고릅니다(`ni`/`me`/`ay`/`ir`/`st` 또는 일본어
  형태). 한국어 이름은 이 매칭에 걸리지 않으므로 캐릭터별 이름표
  색상이 기본 머티리얼로 대체됩니다. 미관상의 문제일 뿐이며, 네이티브
  패치로만 고칠 수 있습니다(이 프로젝트 범위 밖).
- **설정 드롭다운에 한국어가 없음**: EN-locale 방식에서는 게임이
  계속 영어로 실행되므로 바꿀 것이 없습니다.
- **타이틀 카드는 이미지입니다** — 챕터 타이틀 PNG는 영어 그대로
  남습니다.
- **`sam` 폴더는 모든 로케일이 공유합니다** — `.sps`의 인라인
  영어는 테이블 셀이 비어 있을 때 *모든* 로케일에 쓰이는 폴백
  텍스트입니다. 이유를 확실히 알지 못한다면 `.sps` 파일을 직접
  수정하지 마세요; `pack-scripts`는 완결성을 위해 존재할 뿐입니다.
- **백업은 1회성입니다**: `backups/`는 항상 각 파일의 *최초로 관찰된*
  (원본) 사본을 담고 있습니다. `restore`는 패치가 적용된 게임을 원래
  상태로 되돌립니다.
- **`pack-*`는 게임 디렉터리를 절대 건드리지 않습니다** — 결과물은
  `patch/`로 나가며, 수동 복사를 통해 적용(및 배포)됩니다.
- UnityPy는 번들을 원래의 압축 방식 그대로 저장합니다(`packer="original"`);
  재조립된 번들이 정상적으로 로드되는지(구조, 컨테이너, 내용까지)
  검증을 마쳤습니다. 이후 UnityPy 버전이 문제를 일으킨다면 버전을
  고정하세요.
