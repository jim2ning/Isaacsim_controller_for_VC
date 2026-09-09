# PRI Controller Extension

Isaac Sim에서 MCC JSON과 USD를 이용해 Behavior Script를 자동 적용하는 Extension입니다.  
아래 **Control**, **Scripts**, **config.json** 구조를 기준으로 동작합니다.

---

## 1. Control 폴더

**경로:** 프로젝트 루트 `/Control`  
**역할:** USD prim에 붙는 Behavior Script (Python) 파일들. 시뮬레이션 재생 시 각 prim의 동작을 제어합니다.

| 파일 | 용도 |
|------|------|
| `IO_Control.py` | IO 제어 (do/undo position, tact_time 기반 보간 이동) |
| `Motor_Control.py` | 모터 제어 (aurora_axis_id 등) |
| `Vacuum_Control.py` | 진공 제어 |
| `Test_Control.py` | 테스트 제어 |

- 각 스크립트는 **`_target_prim_paths`** 리스트로 제어할 prim 경로를 가집니다.
- 이 리스트는 **Scripts**의 `1_generate_behavior_scripts.py`가 **config.json + MCC JSON**을 보고 자동으로 갱신합니다.
- 사용자는 Control 파일의 로직만 수정하고, **prim 경로 목록은 config + MCC JSON 기준으로 자동 반영**되도록 두는 것이 좋습니다.

---

## 2. PRI_Controller (Extension) 폴더

**경로:** 프로젝트 루트 `/PRI_Controller`  
**역할:** Isaac Sim에 붙는 Extension. UI에서 “Control 갱신”과 “Behavior Script 적용”을 실행합니다.

```
PRI_Controller/
├── config/
│   └── extension.toml    # Extension 메타데이터, python.module 이름
├── data/
│   ├── icon.png
│   └── preview.png
├── docs/
│   ├── CHANGELOG.md
│   └── README.md
└── PRI_Controller_python/
    ├── __init__.py
    ├── extension.py      # Extension 진입점, 메뉴/창 등록
    ├── global_variables.py  # EXTENSION_TITLE 등
    ├── ui_builder.py     # PRI Controller 패널 UI, 1/2/3번 버튼 및 로그
    └── README.md         # Extension 로딩/사용 요약
```

- **extension.py:** 툴바 메뉴에 “PRI Controller” 추가, 창 표시/숨김, `UIBuilder` 호출.
- **ui_builder.py:**  
  - 프로젝트 루트 찾기 (`scripts/config.json` 존재 여부 기준)  
  - **1. Update Control Files** → `scripts/1_generate_behavior_scripts.py` 실행  
  - **2. Apply Behavior Scripts** → `scripts/2_apply_script.py` 기능 실행 (열린 Stage + config.json)  
  - **3. Apply All** → 1번 후 2번 순서 실행  
  - Output Log에 스크립트/Extension 메시지 표시 (영문 메시지 사용).

Extension은 **Scripts**와 **Control**을 “같은 프로젝트 루트 아래”에 두고, **config.json** 한 파일만 참조합니다.

---

## 3. Scripts 폴더

**경로:** 프로젝트 루트 `/scripts` (또는 `Scripts` — config.json의 `paths.scripts_dir`와 일치하면 됨)  
**역할:** Control 파일 갱신과 USD 적용 자동화. **모두 `scripts/config.json` 한 파일을 참조합니다.**

| 파일 | 역할 |
|------|------|
| **config.json** | **사용자가 수정해서 쓰는 설정 파일.** 경로, 파일명, JSON 필드 매핑, USD prim 매핑 등 전체 동작을 결정합니다. (아래 4절에서 상세 설명) |
| 1_generate_behavior_scripts.py | MCC JSON을 읽어 Control 폴더의 `_target_prim_paths` 등을 갱신. USD는 사용하지 않음. |
| 2_apply_script.py | 열린 USD Stage + config.json + MCC JSON을 사용해 Behavior Script 연결 및 Axis/IO 속성 적용. |
| sample_config.json | config.json 예시/템플릿. 복사해 config.json으로 쓰거나 참고용. |

- **1번:** `config.json`의 `paths`, `files.mcc_json`, `control_units`, `json_fields` 등으로 MCC JSON을 읽고, Control별로 prim 경로를 나눈 뒤 각 Control 파일의 `_target_prim_paths`를 덮어씁니다.
- **2번:** `config.json`의 `paths`, `files`, `usd`, `json_fields`, `usd_attributes` 등을 사용해 스크립트를 USD prim에 붙이고, Axis ID / IO 주소·위치·tact_time 등을 JSON 기준으로 설정합니다.

---

## 4. config.json — 사용자가 수정해서 사용하는 설정 파일

**위치:** `scripts/config.json`  
**중요:** Extension과 1/2번 스크립트는 **이 파일만** 읽습니다. MCC JSON 파일명, USD 파일명, 폴더 경로, JSON 컬럼명, USD prim 경로 등 **모두 여기서 결정**되므로, 프로젝트/장비마다 **반드시 수정해서 사용**해야 합니다.

### 4.1 `paths` — 폴더 경로

프로젝트 루트 기준 **상대 경로**입니다. 실제 폴더 이름과 맞춰야 합니다.

```json
"paths": {
  "asset_dir": "asset",      // MCC JSON, USD 파일이 있는 폴더 (예: asset 또는 Asset)
  "control_dir": "Control",  // Control 스크립트 폴더
  "scripts_dir": "scripts"   // config.json, 1/2번 스크립트가 있는 폴더
}
```

- **asset_dir:** `files.mcc_json`, `files.usd_file`이 들어 있는 디렉터리.
- **control_dir:** `IO_Control.py`, `Motor_Control.py` 등이 있는 디렉터리.
- **scripts_dir:** 보통 `scripts` 또는 `Scripts`. Extension은 이 폴더에 `config.json`이 있어야 프로젝트를 “찾은” 것으로 인식합니다.

### 4.2 `files` — 파일 이름

**asset_dir / scripts_dir 기준** 파일 이름만 적습니다 (경로 아님).

```json
"files": {
  "mcc_json": "spring.json",           // MCC JSON 파일명 (asset_dir 아래)
  "usd_file": "spring_share_0116.usd", // 열/적용할 USD 파일명 (asset_dir 아래)
  "io_control": "IO_Control.py",
  "vacuum_control": "Vacuum_Control.py",
  "motor_control": "Motor_Control.py",
  "test_control": "Test_Control.py",
  "server_script": "Sever_Control.py"  // scripts_dir 아래 서버용 스크립트 (필요 시)
}
```

- **mcc_json / usd_file:** 장비/프로젝트마다 바꿔야 합니다. 다른 MCC나 USD를 쓰면 여기만 수정하면 됩니다.
- **server_script:** 2번 적용 시 서버 prim에 붙일 스크립트. 없으면 해당 항목 비활성화하거나 파일만 두고 사용하지 않아도 됩니다.

### 4.3 `usd` — USD prim 매핑

```json
"usd": {
  "server_prim_path": "/Root",
  "control_script_mapping": {
    "IO_Control.py": "/World/Behavior_Scripts/Mesh/IO",
    "Motor_Control.py": "/World/Behavior_Scripts/Mesh/Motor",
    "Vacuum_Control.py": "/World/Behavior_Scripts/Mesh/Vacuum",
    "Test_Control.py": "/World/Behavior_Scripts/Mesh/Test"
  }
}
```

- **server_prim_path:** 서버 스크립트를 붙일 prim.
- **control_script_mapping:** “어떤 Control 파일을 USD의 어떤 prim에 붙일지” 매핑.  
  USD 씬 구조가 다르면 (예: Mesh가 없거나 경로가 다르면) **반드시 실제 경로에 맞게 수정**해야 합니다.

### 4.4 `control_units` / `control_unit_mapping`

```json
"control_units": ["Motor", "IO"],
"control_unit_mapping": {
  "IO": "io_control",
  "Motor": "motor_control"
}
```

- **control_units:** MCC JSON에서 사용하는 제어 유닛 종류. 여기 나열된 것만 1/2번에서 처리합니다. (예: Vacuum, Test 추가 가능)
- **control_unit_mapping:** JSON의 ControlUnit 값 → config의 `files` 키 매핑. Control 파일 이름과 맞추면 됩니다.

### 4.5 `json_fields` — MCC JSON 컬럼 이름 매핑

MCC JSON의 **컬럼 이름이 프로젝트/도구마다 다를 수** 있으므로, 여기서 “어떤 JSON 필드를 무엇으로 쓸지” 지정합니다.

```json
"json_fields": {
  "prim_path": "PrimPath",
  "drive_source": "DriveSource",
  "control_unit": "Remark",   // 예: TwinOps는 "Remark"에 IO/Motor 저장
  "action": "Action",
  "code": "Code",
  "tx": "Tx", "ty": "Ty", "tz": "Tz",
  "rx": "Rx", "ry": "Ry", "rz": "Rz",
  "dist_mm": "DistMm",
  "duration": "Duration",
  "tact_time_sec": "TactTimeSec",
  "elapsed_time_address": "ElapsedTimeAddress"
}
```

- **prim_path:** prim 경로가 들어 있는 컬럼. 보통 `PrimPath` 또는 `Prim Path`.
- **control_unit:** IO/Motor 등 구분이 들어 있는 컬럼. **실제 JSON 컬럼명과 반드시 일치시켜야** 1/2번이 제대로 분류합니다. (예: `ControlUnit` vs `Remark`)
- **action, code, tx~rz, dist_mm, duration, tact_time_sec:** 동작/위치/시간 등. JSON 스키마가 다르면 여기만 바꾸면 됩니다.

### 4.6 `usd_attributes` — USD 속성 이름

USD prim에 붙는 속성 이름을 프로젝트/파이프라인에 맞게 바꿀 때 사용합니다. 기본값만 써도 동작합니다.

```json
"usd_attributes": {
  "axis_id": "aurora_axis_id",
  "do_address": "do_address",
  "undo_address": "undo_address",
  "do_position": "do_position",
  "undo_position": "undo_position",
  "tact_time": "tact_time",
  "elapsed_time_address": "elapsed_time_address",
  "init_translate": "user:init:translate",
  "init_rotate": "user:init:rotate",
  "scripting_scripts": "omni:scripting:scripts"
}
```

### 4.7 config.json 수정 시 체크리스트

- [ ] **paths:** 실제 폴더 이름과 일치하는지 (asset vs Asset, scripts vs Scripts 등)
- [ ] **files.mcc_json, files.usd_file:** 사용할 MCC JSON / USD 파일명으로 변경했는지
- [ ] **usd.control_script_mapping:** 현재 USD 씬의 prim 경로와 일치하는지
- [ ] **control_units:** 사용하는 제어 유닛만 나열했는지
- [ ] **json_fields.control_unit:** MCC JSON에서 IO/Motor 등이 들어 있는 **실제 컬럼명**과 일치하는지

---

## 5. 전체 구조 요약

```
프로젝트 루트/
├── Control/           ← config.paths.control_dir
│   ├── IO_Control.py
│   ├── Motor_Control.py
│   └── ...
├── asset/             ← config.paths.asset_dir
│   ├── <mcc_json>     ← config.files.mcc_json
│   └── <usd_file>     ← config.files.usd_file
├── scripts/           ← config.paths.scripts_dir
│   ├── config.json    ← 사용자가 수정해서 사용
│   ├── 1_generate_behavior_scripts.py
│   ├── 2_apply_script.py
│   └── sample_config.json (참고용)
└── PRI_Controller/    ← Extension
    ├── config/extension.toml
    └── PRI_Controller_python/
        ├── extension.py
        └── ui_builder.py
```

- **Extension:** `scripts/config.json`이 있는 폴더의 상위를 “프로젝트 루트”로 인식합니다.
- **1번 스크립트:** config.json + MCC JSON으로 Control 폴더의 `_target_prim_paths` 등을 갱신합니다.
- **2번 스크립트:** 열린 USD + config.json + MCC JSON으로 스크립트와 속성을 적용합니다.

새 MCC/USD를 쓰거나, 다른 장비/프로젝트로 옮길 때는 **config.json만 정리해서 수정**하면 Control·Scripts·Extension 코드는 그대로 둬도 됩니다.
