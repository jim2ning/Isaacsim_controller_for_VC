"""
Isaac Sim Behavior Script 적용 스크립트

USD 파일에 Behavior Script를 적용하고, JSON 데이터를 기반으로 prim 속성을 설정합니다.
- Python Scripting 패널의 "Scripts" 슬롯만 사용
- Extra Properties / Raw USD Properties에 불필요한 script 속성 미생성
"""

from isaacsim.simulation_app import SimulationApp
app = SimulationApp({"headless": False})

import re
import json
from pathlib import Path
from typing import List, Dict
from collections import defaultdict
import omni.usd
import omni.kit.commands
from pxr import UsdGeom, Sdf, Gf


# =========================================================
# 경로 설정
# =========================================================
def load_config():
    """scripts/config.json 을 로드합니다. 경로·파일명·변수는 이 파일 하나에서만 참조합니다. base_config.json 은 템플릿용."""
    config_path = Path(__file__).parent / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Config 파일을 찾을 수 없습니다: {config_path}")
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

# Config 파일 로드
_config = load_config()

# 경로 설정
SCRIPT_DIR = Path(__file__).parent.absolute()
PROJECT_ROOT = SCRIPT_DIR.parent
ASSET_DIR = PROJECT_ROOT / _config["paths"]["asset_dir"]
USD_PATH = ASSET_DIR / _config["files"]["usd_file"]
CONTROL_DIR = PROJECT_ROOT / _config["paths"]["control_dir"]
SERVER_SCRIPT_PATH = SCRIPT_DIR / _config["files"]["server_script"]
SERVER_PRIM_PATH = _config["usd"]["server_prim_path"]
JSON_PATH = ASSET_DIR / _config["files"]["mcc_json"]

# Control 파일과 USD 경로 매핑
CONTROL_SCRIPT_MAPPING = _config["usd"].get("control_script_mapping", {})

# ControlUnit 리스트
CONTROL_UNITS = _config.get("control_units", [])
if not CONTROL_UNITS:
    print("[WARN] config.json: control_units missing or empty.")
else:
    print(f"[INFO] ControlUnits from config: {CONTROL_UNITS}")

# JSON 필드 이름 매핑
JSON_FIELDS = _config.get("json_fields", {
    "prim_path": "PrimPath",
    "drive_source": "DriveSource",
    "control_unit": "ControlUnit",
    "action": "Action",
    "code": "Code",
    "tx": "Tx",
    "ty": "Ty",
    "tz": "Tz",
    "rx": "Rx",
    "ry": "Ry",
    "rz": "Rz",
    "dist_mm": "DistMm",
    "duration": "Duration",
    "tact_time_sec": "TactTimeSec",
    "elapsed_time_address": "ElapsedTimeAddress"
})

# =========================================================
# Stage 로드
# =========================================================
usd_ctx = omni.usd.get_context()
if not usd_ctx.open_stage(str(USD_PATH)):
    print(f"[ERROR] Failed to open USD file: {USD_PATH}")
    app.close()

stage = usd_ctx.get_stage()
if stage is None:
    print("[ERROR] Stage is None")
    app.close()

print(f"[INFO] Successfully loaded USD file: {USD_PATH}")

# =========================================================
# 헬퍼
# =========================================================
def get_or_add_translate_op(prim):
    xf = UsdGeom.Xformable(prim)
    for op in xf.GetOrderedXformOps():
        if op.GetOpName().startswith("xformOp:translate"):
            return op
    return xf.AddTranslateOp()


def get_or_add_rotate_op(prim):
    xf = UsdGeom.Xformable(prim)
    for op in xf.GetOrderedXformOps():
        if op.GetOpName().startswith("xformOp:rotateXYZ"):
            return op
    return xf.AddRotateXYZOp()


def get_prim(path: str):
    """USD prim을 안전하게 가져옵니다."""
    prim = omni.usd.get_prim_at_path(path)
    return prim if prim and prim.IsValid() else None


def ensure_prim_path(prim_path: str):
    """
    USD 경로에 prim이 없으면 생성합니다. 부모 경로도 함께 생성합니다.
    
    Args:
        prim_path: 생성할 prim 경로
        
    Returns:
        생성된 또는 기존 prim 객체
    """
    prim = get_prim(prim_path)
    if prim is not None:
        return prim
    
    # 경로를 분리하여 부모부터 생성
    path_parts = prim_path.strip("/").split("/")
    current_path = ""
    
    for part in path_parts:
        if current_path:
            current_path += "/" + part
        else:
            current_path = "/" + part
        
        existing_prim = get_prim(current_path)
        if existing_prim is None:
            # Xform 타입으로 생성
            stage.DefinePrim(current_path, "Xform")
            print(f"[INFO] Created prim: {current_path}")
    
    return get_prim(prim_path)


def _ensure_init_pose_attrs(prim):
    """prim에 초기 위치/회전 속성을 설정합니다."""
    if not prim.HasAttribute("user:init:translate"):
        t_op = get_or_add_translate_op(prim)
        pos = t_op.Get() or Gf.Vec3d(0, 0, 0)
        prim.CreateAttribute(
            "user:init:translate", Sdf.ValueTypeNames.Double3
        ).Set(pos)

    if not prim.HasAttribute("user:init:rotate"):
        r_op = get_or_add_rotate_op(prim)
        rot = r_op.Get() or Gf.Vec3f(0, 0, 0)
        prim.CreateAttribute(
            "user:init:rotate", Sdf.ValueTypeNames.Float3
        ).Set(rot)


# =========================================================
# Behavior Script 적용 헬퍼
# =========================================================
def _extract_class_name(script_path: Path) -> str:
    """스크립트 파일에서 BehaviorScript 클래스 이름을 추출합니다."""
    for line in script_path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*class\s+(\w+)\(BehaviorScript\):", line)
        if m:
            return m.group(1)
    return script_path.stem


def _ensure_python_scripting_component(prim):
    """Python Scripting Component(OmniScriptingAPI)를 prim에 적용합니다."""
    path_str = str(prim.GetPath())
    omni.kit.commands.execute(
        "ApplyScriptingAPICommand",
        paths=[path_str],
    )


def _set_python_script_asset(prim, script_path: Path):
    """
    Python Scripting 패널의 'Scripts' 슬롯에 해당하는 omni:scripting:scripts 속성을 설정합니다.
    custom=True를 사용하지 않아 Extra Properties에 표시되지 않고 Python Scripting Component로 관리됩니다.
    """
    _ensure_python_scripting_component(prim)

    attr = prim.GetAttribute("omni:scripting:scripts")
    if not attr:
        attr = prim.CreateAttribute(
            "omni:scripting:scripts",
            Sdf.ValueTypeNames.AssetArray,
        )

    asset_array = Sdf.AssetPathArray([str(script_path)])
    attr.Set(asset_array)


def _attach_script(prim_path: str, script_path: Path) -> bool:
    """
    prim에 Behavior Script를 연결합니다.
    
    Args:
        prim_path: Script를 연결할 prim 경로
        script_path: Behavior Script 파일 경로
        
    Returns:
        bool: 성공 여부
    """
    prim = ensure_prim_path(prim_path)
    if prim is None:
        print(f"[ERROR] Failed to create or find prim: {prim_path}")
        return False

    if not script_path.exists():
        print(f"[WARN] Script file missing: {script_path}")
        return False

    _ensure_init_pose_attrs(prim)
    _set_python_script_asset(prim, script_path.resolve())

    class_name = _extract_class_name(script_path)
    print(f"[APPLY] {prim_path} <= {script_path.name} ({class_name})")
    return True


def load_json_data(json_path: Path):
    """JSON 파일을 로드하고 rows 데이터 반환"""
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and "rows" in data:
            return data["rows"]
        elif isinstance(data, list):
            return data
        else:
            print("[WARN] JSON file format invalid.")
            return []
    except Exception as e:
        print(f"[ERROR] JSON load failed: {e}")
        return []


def extract_target_prim_paths_from_io_control(io_control_file: Path) -> List[str]:
    """
    IO_Control 파일에서 _target_prim_paths 리스트를 추출합니다.
    
    Args:
        io_control_file: IO_Control 파일 경로
        
    Returns:
        list: 추출된 prim path 리스트
    """
    if not io_control_file.exists():
        return []
    
    try:
        content = io_control_file.read_text(encoding='utf-8')
        # self._target_prim_paths = [ ... ] 패턴 찾기
        pattern = r'self\._target_prim_paths\s*=\s*\[(.*?)\]'
        match = re.search(pattern, content, re.DOTALL)
        
        if not match:
            print("[WARN] _target_prim_paths pattern not found.")
            return []
        
        list_content = match.group(1)
        paths = []
        for line in list_content.split('\n'):
            original_line = line
            line = line.strip()
            # 주석 제거
            if '#' in line:
                line = line[:line.index('#')].strip()
            # 빈 라인 스킵
            if not line:
                continue
            # 끝의 쉼표 제거
            line = line.rstrip(',').strip()
            # 문자열 추출 (따옴표 제거)
            if line.startswith('"') and line.endswith('"'):
                path = line[1:-1]
                paths.append(path)
                print(f"[DEBUG] Prim path: '{path}' (from: '{original_line.strip()}')")
            elif line.startswith("'") and line.endswith("'"):
                path = line[1:-1]
                paths.append(path)
                print(f"[DEBUG] Prim path: '{path}' (from: '{original_line.strip()}')")
            else:
                print(f"[WARN] Parse failed for line: '{original_line.strip()}'")
        
        return paths
    except Exception as e:
        print(f"[WARN] Failed to extract prim paths from IO_Control: {e}")
        return []


def build_io_control_mapping_from_json(rows, target_prim_paths):
    """
    IO_Control의 _target_prim_paths에 해당하는 prim들의 do_position, undo_position, tact_time 매핑을 생성합니다.
    
    Args:
        rows: JSON rows 데이터
        target_prim_paths: IO_Control의 _target_prim_paths 목록 (set)
        
    Returns:
        dict: prim_path -> (do_position, undo_position, tact_time) 매핑
    """
    io_control_mapping = {}
    prim_actions = defaultdict(list)
    
    for row in rows:
        prim_path = row.get("PrimPath")
        if not prim_path or prim_path not in target_prim_paths:
            continue
        
        control_unit = row.get(JSON_FIELDS["control_unit"], "")
        # ControlUnit이 "IO"인 경우만 처리
        if control_unit != "IO":
            continue
        
        action = row.get("Action", "")
        tx = row.get("Tx", 0)
        ty = row.get("Ty", 0)
        tz = row.get("Tz", 0)
        dist_mm = row.get("DistMm", 0.0)
        duration = row.get("Duration", 0.0)
        tact_time_sec = row.get("TactTimeSec", 0.0)
        
        prim_actions[prim_path].append({
            "action": action,
            "tx": tx, "ty": ty, "tz": tz,
            "dist_mm": dist_mm,
            "duration": duration,
            "tact_time_sec": tact_time_sec,
        })
    
    # 각 prim에 대해 Down/Up action 쌍 찾기
    for prim_path, actions in prim_actions.items():
        down_action = None
        up_action = None
        
        for action in actions:
            action_lower = action["action"].lower()
            tx, ty, tz = action.get("tx", 0), action.get("ty", 0), action.get("tz", 0)
            
            # Down 액션 판단: 액션 이름 또는 방향 벡터로 판단
            is_down = (
                "down" in action_lower or 
                "downward" in action_lower or
                "내려" in action["action"] or
                "press-fit" in action_lower or
                ("press" in action_lower and ("내려" in action["action"] or tz < 0)) or
                tz < 0
            )
            
            # Up 액션 판단: 액션 이름 또는 방향 벡터로 판단
            is_up = (
                "up" in action_lower or 
                "upward" in action_lower or
                "올라" in action["action"] or
                tz > 0
            )
            
            if is_down and not down_action:
                down_action = action
                print(f"[DEBUG] Down action: {prim_path} -> {action['action']} (Tz={tz})")
            elif is_up and not up_action:
                up_action = action
                print(f"[DEBUG] Up action: {prim_path} -> {action['action']} (Tz={tz})")
        
        if down_action and up_action:
            # do_position 계산 (Down 액션: DistMm * 방향 벡터, mm를 m로 변환)
            do_dist_m = down_action["dist_mm"] / 1000.0
            do_position = (
                do_dist_m * down_action["tx"],
                do_dist_m * down_action["ty"],
                do_dist_m * down_action["tz"]
            )
            
            # undo_position 계산 (Up 액션: DistMm * 방향 벡터, mm를 m로 변환)
            undo_dist_m = up_action["dist_mm"] / 1000.0
            undo_position = (
                undo_dist_m * up_action["tx"],
                undo_dist_m * up_action["ty"],
                undo_dist_m * up_action["tz"]
            )
            
            # tact_time 계산 (Duration 또는 TactTimeSec 중 큰 값 사용)
            tact_time = max(
                down_action.get("duration", 0.0),
                down_action.get("tact_time_sec", 0.0),
                up_action.get("duration", 0.0),
                up_action.get("tact_time_sec", 0.0)
            )
            
            io_control_mapping[prim_path] = (do_position, undo_position, tact_time)
            print(f"[INFO] IO Control mapping: {prim_path} -> "
                  f"do_pos={do_position}, undo_pos={undo_position}, tact_time={tact_time}")
        else:
            # 매핑 실패 시 디버깅 정보 출력
            action_names = [a["action"] for a in actions]
            print(f"[WARN] No Down/Up action pair for {prim_path}.")
            print(f"       Actions found: {action_names}")
            if not down_action:
                print("       No Down action")
            if not up_action:
                print("       No Up action")
    
    return io_control_mapping


def set_io_position_and_tact_time(prim_path: str, do_position: tuple, undo_position: tuple, tact_time: float):
    """
    prim에 do_position, undo_position, tact_time 속성을 설정합니다.
    BehaviorScript가 적용되기 전에 실행되므로 attribute를 직접 생성하고 값을 설정합니다.
    IO_Control의 _ensure_attr()는 HasAuthoredValueOpinion()이 True이면 덮어쓰지 않으므로,
    여기서 설정한 값이 유지됩니다.
    
    Args:
        prim_path: 속성을 설정할 prim 경로
        do_position: do_position 값 (tuple)
        undo_position: undo_position 값 (tuple)
        tact_time: tact_time 값 (float)
        
    Returns:
        bool: 성공 여부
    """
    prim = get_prim(prim_path)
    if not prim or not prim.IsValid():
        print(f"[WARN] Prim not found: {prim_path}")
        return False
    
    # do_position 속성 설정
    do_pos_attr = prim.GetAttribute("do_position")
    if not do_pos_attr:
        do_pos_attr = prim.CreateAttribute(
            "do_position",
            Sdf.ValueTypeNames.Double3,
            custom=True
        )
    do_pos_attr.Set(Gf.Vec3d(do_position[0], do_position[1], do_position[2]))
    print(f"[SET] {prim_path} -> do_position={do_position}")
    
    # undo_position 속성 설정
    undo_pos_attr = prim.GetAttribute("undo_position")
    if not undo_pos_attr:
        undo_pos_attr = prim.CreateAttribute(
            "undo_position",
            Sdf.ValueTypeNames.Double3,
            custom=True
        )
    undo_pos_attr.Set(Gf.Vec3d(undo_position[0], undo_position[1], undo_position[2]))
    print(f"[SET] {prim_path} -> undo_position={undo_position}")
    
    # tact_time 속성 설정
    tact_time_attr = prim.GetAttribute("tact_time")
    if not tact_time_attr:
        tact_time_attr = prim.CreateAttribute(
            "tact_time",
            Sdf.ValueTypeNames.Double,
            custom=True
        )
    tact_time_attr.Set(float(tact_time))
    print(f"[SET] {prim_path} -> tact_time={tact_time}")
    
    return True


def apply_io_control_attributes_from_json():
    """
    JSON 파일에서 IO Control용 do_position, undo_position, tact_time을 읽어서
    IO_Control의 _target_prim_paths에 해당하는 prim들에 설정합니다.
    """
    if not JSON_PATH.exists():
        print(f"[WARN] JSON file not found: {JSON_PATH}")
        return
    
    io_control_file = CONTROL_DIR / "IO_Control_Final.py"
    if not io_control_file.exists():
        print(f"[WARN] IO_Control file not found: {io_control_file}")
        return
    
    # IO_Control_Final.py에서 target_prim_paths 추출
    target_prim_paths = extract_target_prim_paths_from_io_control(io_control_file)
    if not target_prim_paths:
        print("[WARN] target_prim_paths not found in IO_Control.")
        return
    
    print(f"[INFO] Extracted {len(target_prim_paths)} prim paths from IO_Control")
    
    # JSON 데이터 로드
    rows = load_json_data(JSON_PATH)
    if not rows:
        print("[WARN] Could not read data from JSON.")
        return
    
    print(f"[INFO] Loaded {len(rows)} rows from JSON")
    
    # IO Control 매핑 생성
    target_prim_paths_set = set(target_prim_paths)
    io_control_mapping = build_io_control_mapping_from_json(rows, target_prim_paths_set)
    
    if not io_control_mapping:
        print("[WARN] Could not build IO Control mapping.")
        return
    
    print(f"[INFO] IO Control mapping built for {len(io_control_mapping)} prims")
    
    # 각 prim에 attribute 설정
    success_count = 0
    for prim_path, io_data in io_control_mapping.items():
        do_pos, undo_pos, tact_time = io_data
        if set_io_position_and_tact_time(prim_path, do_pos, undo_pos, tact_time):
            success_count += 1
    
    print(f"[INFO] IO Control attributes set on {success_count} prims")


# =========================================================
# Axis ID / IO Address + Position 적용 (JSON 기반, 선택 기능)
# =========================================================
def _parse_axis_from_tx_ty_tz_rx_ry_rz(tx, ty, tz, rx, ry, rz):
    """
    Tx, Ty, Tz, Rx, Ry, Rz 값으로부터 축 정보 문자열을 생성합니다.
    
    Args:
        tx, ty, tz: 이동 축 값
        rx, ry, rz: 회전 축 값
        
    Returns:
        str: 축 정보 문자열 (예: "X,Y,Z")
    """
    axes = []
    if tx != 0:
        axes.append("X")
    if ty != 0:
        axes.append("Y")
    if tz != 0:
        axes.append("Z")
    if rx != 0:
        axes.append("Rx")
    if ry != 0:
        axes.append("Ry")
    if rz != 0:
        axes.append("Rz")
    return ",".join(axes) if axes else None


def _build_axis_and_io_mappings_from_json(rows):
    """
    JSON rows 데이터로부터 axis_id 및 IO address 매핑을 생성합니다.
    
    Args:
        rows: JSON rows 데이터
        
    Returns:
        tuple: (axis_mapping, io_mapping)
            - axis_mapping: prim_path -> axis_id
            - io_mapping: prim_path -> (do_addr, undo_addr, do_pos, undo_pos, tact_time, elapsed_time_addr)
    """
    axis_mapping = {}
    io_mapping = {}
    prim_actions = defaultdict(list)

    for row in rows:
        prim_path = row.get("PrimPath")
        if not prim_path:
            continue

        code = row.get(JSON_FIELDS["code"], "")
        drive_source = row.get(JSON_FIELDS["drive_source"], "")
        control_unit = row.get(JSON_FIELDS["control_unit"], "")
        action = row.get(JSON_FIELDS["action"], "")
        tx = row.get(JSON_FIELDS["tx"], 0)
        ty = row.get(JSON_FIELDS["ty"], 0)
        tz = row.get(JSON_FIELDS["tz"], 0)
        rx = row.get(JSON_FIELDS["rx"], 0)
        ry = row.get(JSON_FIELDS["ry"], 0)
        rz = row.get(JSON_FIELDS["rz"], 0)
        dist_mm = row.get(JSON_FIELDS["dist_mm"], 0.0)
        duration = row.get(JSON_FIELDS["duration"], 0.0)
        tact_time_sec = row.get(JSON_FIELDS["tact_time_sec"], 0.0)
        elapsed_time_address = row.get(JSON_FIELDS["elapsed_time_address"], None)

        prim_actions[prim_path].append({
            "code": code,
            "drive_source": drive_source,
            "control_unit": control_unit,
            "action": action,
            "tx": tx, "ty": ty, "tz": tz,
            "rx": rx, "ry": ry, "rz": rz,
            "dist_mm": dist_mm,
            "duration": duration,
            "tact_time_sec": tact_time_sec,
            "elapsed_time_address": elapsed_time_address,
        })

    # ControlUnit에 따라 prim 분류
    motor_prims = []
    io_prims = []
    vacuum_prims = []

    for prim_path, actions in prim_actions.items():
        # ControlUnit 값으로 분류 (config의 control_units 리스트 사용)
        control_units_in_actions = set(a.get("control_unit", "") for a in actions if a.get("control_unit"))
        
        if "IO" in control_units_in_actions:
            io_prims.append((prim_path, actions))
        elif "Vacuum" in control_units_in_actions:
            vacuum_prims.append((prim_path, actions))
        else:
            # 기본값은 Motor로 처리
            motor_prims.append((prim_path, actions))

    # Motor 제어 prim들에 순차 axis ID 부여
    axis_counter = 1
    for prim_path, actions in motor_prims:
        first_action = actions[0]
        axis_str = _parse_axis_from_tx_ty_tz_rx_ry_rz(
            first_action["tx"], first_action["ty"], first_action["tz"],
            first_action["rx"], first_action["ry"], first_action["rz"]
        )
        if axis_str:
            axis_id = f"Axis{axis_counter}"
            axis_mapping[prim_path] = axis_id
            print(f"[INFO] Axis mapping: {prim_path} -> {axis_id} (axis: {axis_str})")
            axis_counter += 1

    # IO 제어 prim들에 IO Address / Position / tact_time / elapsed_time 매핑 생성
    for prim_path, actions in io_prims:
        down_action = None
        up_action = None

        for a in actions:
            action_lower = a["action"].lower()
            tx, ty, tz = a.get("tx", 0), a.get("ty", 0), a.get("tz", 0)
            
            # Down 액션 판단
            is_down = (
                "down" in action_lower or 
                "downward" in action_lower or
                "내려" in a["action"] or
                "press-fit" in action_lower or
                ("press" in action_lower and ("내려" in a["action"] or tz < 0)) or
                tz < 0
            )
            
            # Up 액션 판단
            is_up = (
                "up" in action_lower or 
                "upward" in action_lower or
                "올라" in a["action"] or
                tz > 0
            )
            
            if is_down and not down_action:
                down_action = a
            if is_up and not up_action:
                up_action = a

        if not (down_action and up_action):
            # 매핑 실패 시 디버깅 정보 출력
            action_names = [a["action"] for a in actions]
            print(f"[WARN] No Down/Up action pair for {prim_path}.")
            print(f"       Actions found: {action_names}")
            if not down_action:
                print("       No Down action")
            if not up_action:
                print("       No Up action")
            continue

        # Code 필드: 비어 있으면 0 사용 (do_position/undo_position/tact_time은 Code 없이도 적용)
        try:
            do_addr = int(down_action["code"]) if down_action.get("code") else 0
        except (ValueError, TypeError):
            do_addr = 0
        try:
            undo_addr = int(up_action["code"]) if up_action.get("code") else 0
        except (ValueError, TypeError):
            undo_addr = 0
        if not (do_addr or undo_addr) and (down_action.get("code") or up_action.get("code")):
            print(f"[WARN] {prim_path} Code parse failed: down_code={down_action.get('code')}, up_code={up_action.get('code')} -> using 0")

        do_dist_m = down_action["dist_mm"] / 1000.0
        do_position = (
            do_dist_m * down_action["tx"],
            do_dist_m * down_action["ty"],
            do_dist_m * down_action["tz"],
        )

        undo_dist_m = up_action["dist_mm"] / 1000.0
        undo_position = (
            undo_dist_m * up_action["tx"],
            undo_dist_m * up_action["ty"],
            undo_dist_m * up_action["tz"],
        )

        tact_time = max(
            down_action.get("duration", 0.0),
            down_action.get("tact_time_sec", 0.0),
            up_action.get("duration", 0.0),
            up_action.get("tact_time_sec", 0.0),
        )

        elapsed_time_addr = None
        if down_action.get("elapsed_time_address"):
            try:
                elapsed_time_addr = int(down_action["elapsed_time_address"])
            except (ValueError, TypeError):
                pass
        elif up_action.get("elapsed_time_address"):
            try:
                elapsed_time_addr = int(up_action["elapsed_time_address"])
            except (ValueError, TypeError):
                pass

        io_mapping[prim_path] = (
            do_addr,
            undo_addr,
            do_position,
            undo_position,
            tact_time,
            elapsed_time_addr,
        )
        elapsed_info = f", elapsed_time_address={elapsed_time_addr}" if elapsed_time_addr else ""
        print(
            f"[INFO] IO 매핑: {prim_path} -> do={do_addr}, undo={undo_addr}, "
            f"do_pos={do_position}, undo_pos={undo_position}, tact_time={tact_time}{elapsed_info}"
        )

    return axis_mapping, io_mapping


def _set_axis_id(prim_path: str, axis_id: str):
    """
    prim에 aurora_axis_id 속성을 설정합니다.
    
    Args:
        prim_path: 속성을 설정할 prim 경로
        axis_id: 설정할 axis ID
        
    Returns:
        bool: 성공 여부
    """
    prim = get_prim(prim_path)
    if not prim or not prim.IsValid():
        print(f"[WARN] Prim not found: {prim_path}")
        return False

    attr = prim.GetAttribute("aurora_axis_id")
    if not attr:
        attr = prim.CreateAttribute(
            "aurora_axis_id",
            Sdf.ValueTypeNames.String,
            custom=True,
        )

    attr.Set(axis_id)
    print(f"[SET] {prim_path} -> aurora_axis_id = '{axis_id}'")
    return True


def _set_io_address(
    prim_path: str,
    do_address: int,
    undo_address: int,
    do_position: tuple,
    undo_position: tuple,
    tact_time: float,
    elapsed_time_address: int | None = None,
):
    """
    prim에 IO 관련 속성들을 설정합니다.
    
    Args:
        prim_path: 속성을 설정할 prim 경로
        do_address: do_address 값
        undo_address: undo_address 값
        do_position: do_position 값 (tuple)
        undo_position: undo_position 값 (tuple)
        tact_time: tact_time 값
        elapsed_time_address: elapsed_time_address 값 (옵션)
        
    Returns:
        bool: 성공 여부
    """
    prim = get_prim(prim_path)
    if not prim or not prim.IsValid():
        print(f"[WARN] Prim not found: {prim_path}")
        return False

    # do_address
    do_attr = prim.GetAttribute("do_address")
    if not do_attr:
        do_attr = prim.CreateAttribute(
            "do_address",
            Sdf.ValueTypeNames.String,
            custom=True,
        )
    do_attr.Set(str(do_address))

    # undo_address
    undo_attr = prim.GetAttribute("undo_address")
    if not undo_attr:
        undo_attr = prim.CreateAttribute(
            "undo_address",
            Sdf.ValueTypeNames.String,
            custom=True,
        )
    undo_attr.Set(str(undo_address))

    # do_position
    do_pos_attr = prim.GetAttribute("do_position")
    if not do_pos_attr:
        do_pos_attr = prim.CreateAttribute(
            "do_position",
            Sdf.ValueTypeNames.Double3,
            custom=True,
        )
    do_pos_attr.Set(Gf.Vec3d(do_position[0], do_position[1], do_position[2]))

    # undo_position
    undo_pos_attr = prim.GetAttribute("undo_position")
    if not undo_pos_attr:
        undo_pos_attr = prim.CreateAttribute(
            "undo_position",
            Sdf.ValueTypeNames.Double3,
            custom=True,
        )
    undo_pos_attr.Set(Gf.Vec3d(undo_position[0], undo_position[1], undo_position[2]))

    # tact_time
    tact_time_attr = prim.GetAttribute("tact_time")
    if not tact_time_attr:
        tact_time_attr = prim.CreateAttribute(
            "tact_time",
            Sdf.ValueTypeNames.Double,
            custom=True,
        )
    tact_time_attr.Set(float(tact_time))

    # elapsed_time_address (옵션)
    if elapsed_time_address is not None:
        elapsed_time_addr_attr = prim.GetAttribute("elapsed_time_address")
        if not elapsed_time_addr_attr:
            elapsed_time_addr_attr = prim.CreateAttribute(
                "elapsed_time_address",
                Sdf.ValueTypeNames.String,
                custom=True,
            )
        elapsed_time_addr_attr.Set(str(elapsed_time_address))

    elapsed_info = f", elapsed_time_address={elapsed_time_address}" if elapsed_time_address is not None else ""
    print(
        f"[SET] {prim_path} -> do_address={do_address}, undo_address={undo_address}, "
        f"do_position={do_position}, undo_position={undo_position}, tact_time={tact_time}{elapsed_info}"
    )
    return True


def apply_axis_id_from_json(save_layer: bool = False):
    """
    JSON 파일을 읽어서 Motor 관련 prim에 aurora_axis_id(Axis1, Axis2, ...)를 설정합니다.
    
    Args:
        save_layer: True면 USD 파일 저장
    """
    if not JSON_PATH.exists():
        print(f"[WARN] JSON file not found: {JSON_PATH}")
        return

    print("\n" + "=" * 60)
    print("Axis ID (from JSON, apply_axis_id_from_json)")
    print("=" * 60 + "\n")

    rows = load_json_data(JSON_PATH)
    if not rows:
        print("[WARN] Could not read data from JSON.")
        return

    print(f"[INFO] Found {len(rows)} rows.")
    axis_mapping, _ = _build_axis_and_io_mappings_from_json(rows)

    print(f"[INFO] Setting Axis ID... ({len(axis_mapping)} prims)")
    axis_count = 0
    for prim_path, axis_id in axis_mapping.items():
        if _set_axis_id(prim_path, axis_id):
            axis_count += 1
    print(f"[INFO] Axis ID set on {axis_count} prims\n")

    if save_layer:
        try:
            stage.GetRootLayer().Save()
            print("[INFO] Stage saved (Axis included)")
        except Exception as e:
            print(f"[WARN] Stage save failed: {e}")


def apply_io_from_json(save_layer: bool = False):
    """
    JSON 파일을 읽어서 IO(ControlUnit="IO") 관련 prim에 IO 속성들을 설정합니다.
    
    Args:
        save_layer: True면 USD 파일 저장
    """
    if not JSON_PATH.exists():
        print(f"[WARN] JSON file not found: {JSON_PATH}")
        return

    print("\n" + "=" * 60)
    print("IO Address and Position (from JSON, apply_io_from_json)")
    print("=" * 60 + "\n")

    rows = load_json_data(JSON_PATH)
    if not rows:
        print("[WARN] Could not read data from JSON.")
        return

    print(f"[INFO] Found {len(rows)} rows.")
    _, io_mapping = _build_axis_and_io_mappings_from_json(rows)

    print(f"[INFO] Setting IO Address and Position... ({len(io_mapping)} prims)")
    io_count = 0
    for prim_path, io_data in io_mapping.items():
        if len(io_data) == 6:
            do_addr, undo_addr, do_pos, undo_pos, tact_time, elapsed_time_addr = io_data
        else:
            do_addr, undo_addr, do_pos, undo_pos, tact_time = io_data[:5]
            elapsed_time_addr = None

        if _set_io_address(
            prim_path, do_addr, undo_addr, do_pos, undo_pos, tact_time, elapsed_time_addr
        ):
            io_count += 1

    print(f"[INFO] IO Address/Position set on {io_count} prims\n")

    if save_layer:
        try:
            stage.GetRootLayer().Save()
            print("[INFO] Stage saved (IO included)")
        except Exception as e:
            print(f"[WARN] Stage save failed: {e}")


def apply_axis_id_and_io_from_json(
    save_layer: bool = False,
    apply_axis: bool = True,
    apply_io: bool = True,
):
    """
    JSON 파일을 읽어서 Motor와 IO prim에 속성을 한 번에 설정합니다.
    - Motor prim: aurora_axis_id (Axis1, Axis2, ...)
    - IO prim: do_address, undo_address, do_position, undo_position, tact_time, elapsed_time_address
    
    Args:
        save_layer: True면 USD 파일 저장
        apply_axis: True면 Axis ID 설정
        apply_io: True면 IO 속성 설정
    """
    if not JSON_PATH.exists():
        print(f"[WARN] JSON file not found: {JSON_PATH}")
        return

    print("\n" + "=" * 60)
    print("Axis ID and IO Address (from JSON, apply_axis_id_and_io_from_json)")
    print("=" * 60 + "\n")

    rows = load_json_data(JSON_PATH)
    if not rows:
        print("[WARN] Could not read data from JSON.")
        return

    print(f"[INFO] Found {len(rows)} rows.")
    axis_mapping, io_mapping = _build_axis_and_io_mappings_from_json(rows)

    # Axis ID 설정 (Motor 전용)
    if apply_axis:
        print(f"[INFO] Setting Axis ID... ({len(axis_mapping)} prims)")
        axis_count = 0
        for prim_path, axis_id in axis_mapping.items():
            if _set_axis_id(prim_path, axis_id):
                axis_count += 1
        print(f"[INFO] Axis ID set on {axis_count} prims\n")
    else:
        print("[INFO] Axis ID skipped (apply_axis=False)")

    # IO Address 및 Position 설정 (ControlUnit="IO" 전용)
    if apply_io:
        print(f"[INFO] Setting IO Address and Position... ({len(io_mapping)} prims)")
        io_count = 0
        for prim_path, io_data in io_mapping.items():
            if len(io_data) == 6:
                do_addr, undo_addr, do_pos, undo_pos, tact_time, elapsed_time_addr = io_data
            else:
                do_addr, undo_addr, do_pos, undo_pos, tact_time = io_data[:5]
                elapsed_time_addr = None

            if _set_io_address(
                prim_path, do_addr, undo_addr, do_pos, undo_pos, tact_time, elapsed_time_addr
            ):
                io_count += 1

        print(f"[INFO] IO Address/Position set on {io_count} prims\n")
    else:
        print("[INFO] IO Address/Position skipped (apply_io=False)")

    if save_layer:
        try:
            stage.GetRootLayer().Save()
            print("[INFO] Stage saved (Axis/IO included)")
        except Exception as e:
            print(f"[WARN] Stage save failed: {e}")


def _extract_control_unit_from_filename(filename: str) -> str:
    """
    파일명에서 ControlUnit을 추출합니다.
    예: "IO_Control.py" -> "IO", "Motor_Control.py" -> "Motor"
    
    Args:
        filename: 파일명
        
    Returns:
        str: 추출된 ControlUnit
    """
    # 파일명에서 확장자 제거
    name_without_ext = Path(filename).stem
    
    # 패턴: {ControlUnit}_Control 또는 {ControlUnit}Control
    for unit in CONTROL_UNITS:
        if name_without_ext.startswith(unit) and ("_Control" in name_without_ext or "Control" in name_without_ext):
            return unit
    
    # 매칭되지 않으면 파일명의 첫 부분을 ControlUnit으로 사용
    parts = name_without_ext.split("_")
    if parts:
        return parts[0]
    
    return ""


def _generate_usd_prim_path(control_unit: str) -> str:
    """
    ControlUnit으로부터 USD prim 경로를 생성합니다.
    기본 패턴: /World/Behavior_Scripts/Mesh/{ControlUnit}
    
    Args:
        control_unit: ControlUnit 이름
        
    Returns:
        str: USD prim 경로
    """
    return f"/World/Behavior_Scripts/Mesh/{control_unit}"


def _gather_tasks() -> List[Dict[str, str]]:
    """
    Control 폴더의 파일들을 자동으로 스캔하여 작업 목록을 생성합니다.
    config의 control_units를 참고하여 매칭합니다.
    
    Returns:
        list: 작업 목록 (각 항목은 prim_path, script_path, control_unit, filename 포함)
    """
    tasks: List[Dict[str, str]] = []
    
    # Control 폴더에서 모든 .py 파일 찾기
    if not CONTROL_DIR.exists():
        print(f"[WARN] Control dir not found: {CONTROL_DIR}")
        return tasks
    
    control_files = list(CONTROL_DIR.glob("*.py"))
    
    if not control_files:
        print(f"[WARN] No .py files in Control folder: {CONTROL_DIR}")
        return tasks
    
    print(f"[INFO] Found {len(control_files)} files in Control folder")
    
    # 각 파일 처리
    for script_path in control_files:
        script_filename = script_path.name
        
        # Server script는 제외
        if script_filename == _config["files"]["server_script"]:
            continue
        
        # 파일이 비어있으면 스킵
        if script_path.stat().st_size == 0:
            print(f"[SKIP] Empty file: {script_filename}")
            continue
        
        # 파일명에서 ControlUnit 추출
        control_unit = _extract_control_unit_from_filename(script_filename)
        
        if not control_unit:
            print(f"[WARN] Could not extract ControlUnit from {script_filename}. Skipping.")
            continue
        
        # ControlUnit이 config의 control_units에 있는지 확인
        if control_unit not in CONTROL_UNITS:
            print(f"[WARN] ControlUnit '{control_unit}' of {script_filename} not in config. Skipping.")
            continue
        
        # USD prim 경로 결정 (config에 있으면 사용, 없으면 자동 생성)
        if script_filename in CONTROL_SCRIPT_MAPPING:
            usd_prim_path = CONTROL_SCRIPT_MAPPING[script_filename]
            print(f"[INFO] Using config path: {script_filename} -> {usd_prim_path}")
        else:
            usd_prim_path = _generate_usd_prim_path(control_unit)
            print(f"[INFO] Auto path: {script_filename} -> {usd_prim_path}")
        
        tasks.append({
            "prim_path": usd_prim_path,
            "script_path": str(script_path),
            "control_unit": control_unit,
            "filename": script_filename
        })
        print(f"[TASK] {usd_prim_path} <= {script_filename} ({control_unit})")
    
    return tasks


# =========================================================
# Behavior Script 적용 Controller
# =========================================================
def apply_behavior_scripts(save_layer: bool = False, apply_server: bool = True):
    """
    Behavior Script를 USD 파일의 prim에 적용합니다.
    
    Args:
        save_layer: True면 USD 파일 저장
        apply_server: True면 MeshServerV1도 적용
    """
    tasks = _gather_tasks()
    
    # MeshServerV1 적용
    if apply_server and SERVER_SCRIPT_PATH.exists():
        # /Root prim이 없으면 생성
        root_prim = get_prim(SERVER_PRIM_PATH)
        if root_prim is None:
            root_prim = stage.DefinePrim(SERVER_PRIM_PATH, "Xform")
            print(f"[INFO] Created prim: {SERVER_PRIM_PATH}")
        
        if _attach_script(SERVER_PRIM_PATH, SERVER_SCRIPT_PATH):
            print(f"[INFO] MeshServerV1 applied to {SERVER_PRIM_PATH}")
    elif apply_server:
        print(f"[WARN] Server script not found: {SERVER_SCRIPT_PATH}")
    
    if not tasks:
        print("[WARN] No Control Scripts to apply.")
        if not apply_server:
            return
    else:
        ok = 0
        for t in tasks:
            prim_path = t["prim_path"]
            script_path = Path(t["script_path"])
            if _attach_script(prim_path, script_path):
                ok += 1
        print(f"[DONE] Control Scripts: {ok}/{len(tasks)} applied")

    if save_layer:
        try:
            stage.GetRootLayer().Save()
            print("[INFO] Stage saved")
        except Exception as e:
            print(f"[WARN] Stage save failed: {e}")


# =========================================================
# MAIN
# =========================================================
if __name__ == "__main__":
    # Behavior Script 적용
    apply_behavior_scripts(save_layer=False, apply_server=True)

    # JSON 기반 Axis ID / IO Address 설정
    apply_axis_id_and_io_from_json(save_layer=False, apply_axis=True, apply_io=True)

    print("[INFO] Behavior scripts applied. Isaac Sim UI running...")

    # 타임라인 자동 재생
    try:
        import omni.timeline
        tl = omni.timeline.get_timeline_interface()
        if not tl.is_playing():
            tl.play()
            print("[INFO] Timeline play triggered.")
    except Exception as e:
        print(f"[WARN] Timeline play trigger failed: {e}")

    # Isaac Sim 유지 루프
    while app.is_running():
        app.update()

    print("[INFO] Isaac Sim closed.")
