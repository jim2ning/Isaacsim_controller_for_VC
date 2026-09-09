"""
Behavior Script 생성 스크립트

JSON 파일(MCC)을 읽어서 Control 파일들의 _target_prim_paths를 자동으로 업데이트합니다.
ControlUnit 필드를 기반으로 Motor, IO, Vacuum 등으로 분류하여 처리합니다.
"""

import json
import re
from pathlib import Path
from collections import defaultdict


def load_config():
    """scripts/config.json 을 로드합니다. 경로·파일명·변수는 이 파일 하나에서만 참조합니다. base_config.json 은 템플릿용."""
    config_path = Path(__file__).parent / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Config 파일을 찾을 수 없습니다: {config_path}")
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_json(json_file_path):
    """JSON 파일을 로드합니다."""
    with open(json_file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def extract_existing_prim_paths(file_content):
    """
    파일에서 기존 self._target_prim_paths 리스트의 prim path들을 추출합니다.
    
    Args:
        file_content: 파일 내용 문자열
        
    Returns:
        list: 추출된 prim path 리스트
    """
    existing_paths = []
    
    # self._target_prim_paths = [ ... ] 패턴 찾기
    pattern = r'self\._target_prim_paths\s*=\s*\[(.*?)\]'
    match = re.search(pattern, file_content, re.DOTALL)
    
    if match:
        list_content = match.group(1)
        # 각 라인에서 문자열 추출
        for line in list_content.split('\n'):
            line = line.strip()
            # 주석 제거
            if '#' in line:
                line = line[:line.index('#')].strip()
            # 빈 라인 스킵
            if not line:
                continue
            # 문자열 추출 (따옴표 제거)
            if line.startswith('"') and line.endswith('"'):
                path = line[1:-1]
                existing_paths.append(path)
            elif line.startswith("'") and line.endswith("'"):
                path = line[1:-1]
                existing_paths.append(path)
    
    return existing_paths


def update_prim_paths_in_file(file_path, new_prim_paths):
    """
    Control 파일의 self._target_prim_paths 리스트에 새로운 prim path들을 추가합니다.
    기존 경로는 유지하고, 중복은 제거합니다.
    
    Args:
        file_path: 업데이트할 Control 파일 경로
        new_prim_paths: 추가할 prim path 리스트
        
    Returns:
        bool: 성공 여부
    """
    if not file_path.exists():
        print(f"[WARN] File not found: {file_path}")
        return False
    
    # 파일 읽기
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 파일이 비어있으면 스킵
    if not content.strip():
        print(f"[WARN] File is empty: {file_path}")
        return False
    
    # 기존 prim paths 추출
    existing_paths = extract_existing_prim_paths(content)
    
    # self._target_prim_paths가 없으면 스킵
    if 'self._target_prim_paths' not in content:
        print(f"[WARN] self._target_prim_paths not found: {file_path}")
        return False
    
    # 기존 경로와 새 경로 합치기 (중복 제거)
    all_paths = list(set(existing_paths + new_prim_paths))
    all_paths.sort()
    
    # self._target_prim_paths = [ ... ] 패턴 찾아서 교체
    # 줄 단위로 매칭하여 들여쓰기 보존
    lines = content.split('\n')
    new_lines = []
    in_prim_list = False
    list_indent = ''
    list_end_indent = ''
    
    for line in lines:
        # self._target_prim_paths = [ 시작 라인 찾기
        if 'self._target_prim_paths' in line and '=' in line and '[' in line:
            in_prim_list = True
            # 들여쓰기 계산
            list_indent = ' ' * (len(line) - len(line.lstrip()))
            list_end_indent = ' ' * max(0, len(list_indent) - 4)
            new_lines.append(line)
            continue
        
        # 리스트 내부인 경우 기존 내용은 건너뛰기
        if in_prim_list:
            # 닫는 괄호 ] 찾기
            stripped = line.lstrip()
            if stripped.startswith(']'):
                # 새 리스트 내용 삽입
                for path in all_paths:
                    new_lines.append(f'{list_indent}            "{path}",')
                new_lines.append(f'{list_end_indent}]')
                in_prim_list = False
                continue
            continue
        
        # 일반 라인은 그대로 추가
        new_lines.append(line)
    
    new_content = '\n'.join(new_lines)
    
    # 파일 쓰기
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    return True


def build_io_control_mapping_from_json(data, target_prim_paths):
    """
    IO_Control의 _target_prim_paths에 해당하는 prim들의 do_position, undo_position, tact_time 매핑을 생성합니다.
    ControlUnit 필드를 사용하여 IO 항목만 필터링합니다.
    
    Args:
        data: JSON rows 데이터
        target_prim_paths: IO_Control의 _target_prim_paths 목록 (set)
        
    Returns:
        dict: prim_path -> (do_position, undo_position, tact_time) 매핑
    """
    # Config 로드
    config = load_config()
    json_fields = config.get("json_fields", {})
    
    prim_path_field = json_fields.get("prim_path", "PrimPath")
    control_unit_field = json_fields.get("control_unit", "ControlUnit")
    
    io_control_mapping = {}
    prim_actions = defaultdict(list)
    
    for row in data:
        prim_path = row.get(prim_path_field)
        if not prim_path or prim_path not in target_prim_paths:
            continue
        
        control_unit = row.get(control_unit_field, "")
        # ControlUnit이 "IO"인 경우만 처리
        if control_unit != "IO":
            continue
        
        action = row.get(json_fields.get("action", "Action"), "")
        tx = row.get(json_fields.get("tx", "Tx"), 0)
        ty = row.get(json_fields.get("ty", "Ty"), 0)
        tz = row.get(json_fields.get("tz", "Tz"), 0)
        dist_mm = row.get(json_fields.get("dist_mm", "DistMm"), 0.0)
        duration = row.get(json_fields.get("duration", "Duration"), 0.0)
        tact_time_sec = row.get(json_fields.get("tact_time_sec", "TactTimeSec"), 0.0)
        
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
            if "down" in action_lower:
                down_action = action
            elif "up" in action_lower:
                up_action = action
        
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
    
    return io_control_mapping


def update_control_files_from_json(json_file, io_control_file, vacuum_control_file, motor_control_file, usd_file=None):
    """
    JSON 데이터를 기반으로 각 Control 파일의 self._target_prim_paths에 prim path를 추가합니다.
    ControlUnit 필드를 사용하여 Motor, IO, Vacuum 등으로 분류합니다.
    
    Args:
        json_file: MCC JSON 파일 경로
        io_control_file: IO_Control 파일 경로
        vacuum_control_file: Vacuum_Control 파일 경로
        motor_control_file: Motor_Control 파일 경로
        usd_file: USD 파일 경로 (옵션, 미사용)
    """
    # Config 로드
    config = load_config()
    control_units = config.get("control_units", ["Motor", "IO", "Vacuum"])
    json_fields = config.get("json_fields", {})
    
    # JSON 필드 이름
    prim_path_field = json_fields.get("prim_path", "PrimPath")
    control_unit_field = json_fields.get("control_unit", "ControlUnit")
    action_field = json_fields.get("action", "Action")
    motion_field = "Motion"
    
    # JSON 데이터 로드
    json_data = load_json(json_file)
    
    # JSON 구조 처리: rows 배열 추출
    if isinstance(json_data, dict) and "rows" in json_data:
        data = json_data["rows"]
    elif isinstance(json_data, list):
        data = json_data
    else:
        print("[ERROR] JSON file format invalid.")
        return
    
    # ControlUnit별로 prim path 분류 (동적 딕셔너리 사용)
    control_unit_paths = {unit: [] for unit in control_units}
    
    print("=" * 80)
    print("JSON analysis and classification (by ControlUnit)")
    print("=" * 80)
    
    for idx, item in enumerate(data, 1):
        control_unit = item.get(control_unit_field, "")
        prim_path = item.get(prim_path_field, item.get("prim path"))
        action = item.get(motion_field, item.get(action_field, item.get("action", "Unknown")))
        
        # prim path가 없거나 null인 경우 스킵
        if not prim_path or prim_path == "null" or prim_path == "":
            continue
        
        # ControlUnit이 config의 control_units 리스트에 있는지 확인
        control_unit = str(control_unit).strip()
        if control_unit in control_units:
            if prim_path not in control_unit_paths[control_unit]:
                control_unit_paths[control_unit].append(prim_path)
                print(f"[{idx}] {control_unit} - {prim_path}")
        else:
            # ControlUnit이 없거나 유효하지 않은 경우, 기본값으로 Motor 처리
            if control_unit == "":
                control_unit = "Motor"
            if control_unit not in control_unit_paths:
                control_unit_paths[control_unit] = []
            if prim_path not in control_unit_paths[control_unit]:
                control_unit_paths[control_unit].append(prim_path)
                print(f"[{idx}] {control_unit} (default) - {prim_path}")
    
    print("=" * 80)
    print("Classification done:")
    for unit in control_units:
        count = len(control_unit_paths.get(unit, []))
        if count > 0:
            print(f"  - {unit}: {count}")
    print("=" * 80)
    
    # 각 Control 파일 업데이트 (ControlUnit 기반)
    print("\n" + "=" * 80)
    print("Updating Control files...")
    print("=" * 80)
    
    # ControlUnit -> Control 파일 매핑
    files_config = config.get("files", {})
    control_unit_mapping = config.get("control_unit_mapping", {})
    control_file_mapping = {}
    
    base_dir = Path(__file__).parent
    project_root = base_dir.parent
    control_dir = project_root / config["paths"]["control_dir"]
    
    for unit in control_units:
        # config에서 매핑을 가져오고, 없으면 자동 생성 (fallback)
        file_key = control_unit_mapping.get(unit, f"{unit.lower()}_control")
        if file_key in files_config:
            control_file_mapping[unit] = control_dir / files_config[file_key]
    
    # 각 ControlUnit별로 파일 업데이트
    for control_unit in control_units:
        paths = control_unit_paths.get(control_unit, [])
        control_file = control_file_mapping.get(control_unit)
        
        if control_file and paths:
            print(f"\n[INFO] Updating {control_unit} Control... ({len(paths)} paths)")
            if update_prim_paths_in_file(control_file, paths):
                print(f"[SUCCESS] {control_unit} Control updated")
            else:
                print(f"[ERROR] {control_unit} Control update failed")
        elif control_file:
            print(f"\n[SKIP] {control_unit} Control - no paths to add")
        else:
            print(f"\n[WARN] {control_unit} Control file path not found")
    
    print("\n" + "=" * 80)
    print("Control files update done!")
    print("=" * 80)

def main():
    # Config 파일 로드
    config = load_config()
    
    # 파일 경로 설정
    base_dir = Path(__file__).parent
    project_root = base_dir.parent
    
    asset_dir = project_root / config["paths"]["asset_dir"]
    control_dir = project_root / config["paths"]["control_dir"]
    
    json_file = asset_dir / config["files"]["mcc_json"]
    io_control_file = control_dir / config["files"]["io_control"]
    vacuum_control_file = control_dir / config["files"]["vacuum_control"]
    motor_control_file = control_dir / config["files"]["motor_control"]
    usd_file = asset_dir / config["files"]["usd_file"]
    
    # 파일 존재 확인
    if not json_file.exists():
        print(f"[ERROR] JSON file not found: {json_file}")
        return
    
    if not io_control_file.exists():
        print(f"[ERROR] IO_Control file not found: {io_control_file}")
        return
    
    if not motor_control_file.exists():
        print(f"[ERROR] Motor_Control file not found: {motor_control_file}")
        return
    
    # Control 파일 업데이트
    try:
        update_control_files_from_json(
            str(json_file),
            io_control_file,
            vacuum_control_file,
            motor_control_file,
            usd_file=usd_file if usd_file.exists() else None
        )
    except Exception as e:
        print(f"\n[ERROR] Error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
