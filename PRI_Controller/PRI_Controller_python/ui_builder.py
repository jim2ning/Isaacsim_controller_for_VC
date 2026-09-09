# SPDX-FileCopyrightText: Copyright (c) 2022-2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import sys
import json
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import omni.ui as ui
import omni.usd
from isaacsim.gui.components.element_wrappers import (
    CollapsableFrame,
    TextBlock,
)
from isaacsim.gui.components.ui_utils import get_style


# -----------------------------------------------------------------------------
# Config: 1_generate_behavior_scripts.py, 2_apply_script.py, Extension 모두
# scripts/config.json 한 파일만 참조합니다. 경로·파일명·변수는 모두 여기서 결정됩니다.
# -----------------------------------------------------------------------------


class _StdoutToLog:
    """스크립트의 print() 출력을 Extension Output Log로 넘깁니다."""

    def __init__(self, append_fn):
        self._append = append_fn

    def write(self, text):
        if not text:
            return
        for line in text.rstrip().split("\n"):
            self._append(line)

    def flush(self):
        pass


class UIBuilder:
    def __init__(self):
        # UI elements created using a UIElementWrapper from isaacsim.gui.components.element_wrappers
        self.wrapped_ui_elements = []

        # Stage reference
        self._stage: Optional = None

        # UI labels
        self._lbl_status = None
        self._output_block = None
        self._log_lines: list = []

        # PRI 프로젝트 경로 (Extension이 설치된 위치에서 scripts 폴더 찾기)
        self._pri_project_path = None
        self._scripts_dir = None
        self._config = None

    ###################################################################################
    #           The Functions Below Are Called Automatically By extension.py
    ###################################################################################

    def on_menu_callback(self):
        """Callback for when the UI is opened from the toolbar.
        This is called directly after build_ui().
        """
        self._initialize_project_paths()

    def on_timeline_event(self, event):
        """Callback for Timeline events (Play, Pause, Stop)

        Args:
            event (omni.timeline.TimelineEventType): Event Type
        """
        pass

    def on_physics_step(self, step):
        """Callback for Physics Step.
        Physics steps only occur when the timeline is playing

        Args:
            step (float): Size of physics step
        """
        pass

    def on_stage_event(self, event):
        """Callback for Stage Events

        Args:
            event (omni.usd.StageEventType): Event Type
        """
        pass

    def cleanup(self):
        """
        Called when the stage is closed or the extension is hot reloaded.
        Perform any necessary cleanup such as removing active callback functions
        """
        for ui_elem in self.wrapped_ui_elements:
            ui_elem.cleanup()

    def build_ui(self):
        """
        Build a custom UI tool to run PRI scripts.
        This function will be called any time the UI window is closed and reopened.
        """
        self._create_control_panel()

    # ===== Helpers =====
    #
    # 프로젝트 구조:
    #
    #   PROJECT_ROOT/
    #   ├── Scripts/
    #   │   ├── config.json      ← paths, files, usd, json_fields 등
    #   │   ├── 1_generate_behavior_scripts.py
    #   │   └── 2_apply_script.py
    #   ├── Control/             ← config paths.control_dir
    #   │   ├── IO_Control.py
    #   │   ├── Motor_Control.py
    #   │   └── ...
    #   ├── Asset/               ← config paths.asset_dir
    #   │   ├── <mcc_json>       ← config files.mcc_json (예: spring.json)
    #   │   └── <usd_file>       ← config files.usd_file (예: spring_share_0116.usd)
    #   └── PRI_Controller/      ← Extension (현재 코드 위치의 상위)
    #
    def _get_stage(self):
        return omni.usd.get_context().get_stage()

    def _get_project_root_candidates(self):
        """
        Project root 후보 목록. Scripts/config.json 이 존재하는 경로를 사용.
        다른 위치의 프로젝트를 쓰려면 아래 candidates 에 경로를 추가하면 됨.
        """
        extension_file = Path(__file__).resolve()
        project_root_from_extension = extension_file.parent.parent.parent
        project_root_from_extension2 = extension_file.parent.parent
        candidates = [
            project_root_from_extension,
            project_root_from_extension2,
            Path(r"D:\jimin_PRI\HY_PRI_controller_v1.2"),
            Path.home() / "\HY_PRI_controller_v1.2",
        ]
        return candidates

    def _initialize_project_paths(self):
        """PRI 프로젝트 경로를 찾아서 초기화합니다. scripts/config.json 존재 여부로 검사."""
        try:
            for path in self._get_project_root_candidates():
                scripts_dir = path / "Scripts"
                config_file = scripts_dir / "config.json"
                if config_file.exists():
                    self._pri_project_path = path
                    self._scripts_dir = scripts_dir
                    self._load_config()
                    self._append_log(f"[INFO] PRI project path found: {path}")
                    return

            self._append_log("[WARN] PRI project path not found. Project root must contain scripts/config.json.")
        except Exception as e:
            self._append_log(f"[ERROR] Project path init failed: {e}")

    def _load_config(self):
        """config.json 파일을 로드합니다."""
        if not self._scripts_dir:
            return None

        config_file = self._scripts_dir / "config.json"
        if not config_file.exists():
            self._append_log(f"[WARN] Config file not found: {config_file}")
            return None

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                self._config = json.load(f)
            return self._config
        except Exception as e:
            self._append_log(f"[ERROR] Config load failed: {e}")
            return None

    def _create_control_panel(self):
        """PRI Controller UI 패널 생성"""
        frame = CollapsableFrame("PRI Controller", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=6, height=0):
                ui.Label("PRI Isaac Sim Controller", height=24, style={"font_size": 16})
                ui.Spacer(height=4)

                # 상태 표시
                self._lbl_status = ui.Label("Status: Ready", height=18)

                ui.Spacer(height=6)

                # 프로젝트 경로 표시
                ui.Label("Project Path:", height=18)
                with ui.HStack(spacing=5):
                    self._lbl_project_path = ui.Label("(Not found)", height=18, word_wrap=True)
                    ui.Button("Refresh", height=24, width=80, clicked_fn=self._refresh_project_path)

                ui.Spacer(height=6)

                # 버튼들
                ui.Label("Actions:", height=18)
                with ui.VStack(spacing=5):
                    ui.Button(
                        "1. Update Control Files",
                        height=36,
                        clicked_fn=self._run_update_control_files,
                    )
                    ui.Button(
                        "2. Apply Behavior Scripts",
                        height=36,
                        clicked_fn=self._run_apply_scripts,
                    )
                    ui.Button(
                        "3. Apply All (Update + Apply)",
                        height=36,
                        clicked_fn=self._run_all,
                    )

                ui.Spacer(height=6)

                # 출력 패널
                output_frame = CollapsableFrame("Output Log", collapsed=False)
                with output_frame:
                    with ui.VStack(style=get_style(), spacing=5, height=0):
                        self._output_block = TextBlock(
                            "",
                            num_lines=30,
                            tooltip="Script execution output",
                            include_copy_button=True,
                        )

        # 초기 상태 업데이트
        self._update_status()

    def _update_status(self):
        """상태 레이블 업데이트"""
        if self._lbl_status:
            if self._pri_project_path and self._scripts_dir:
                self._lbl_status.text = f"Status: Ready (Project: {self._pri_project_path.name})"
                if self._lbl_project_path:
                    self._lbl_project_path.text = str(self._pri_project_path)
            else:
                self._lbl_status.text = "Status: Project path not found"
                if self._lbl_project_path:
                    self._lbl_project_path.text = "(Not found)"

    def _refresh_project_path(self):
        """프로젝트 경로 다시 찾기"""
        self._initialize_project_paths()
        self._update_status()

    def _append_log(self, text: str):
        """로그에 텍스트 추가"""
        self._log_lines.append(text)
        # 로그 크기 제한
        if len(self._log_lines) > 500:
            self._log_lines = self._log_lines[-500:]
        if self._output_block:
            self._output_block.set_text("\n".join(self._log_lines))

    @contextmanager
    def _capture_stdout_to_log(self):
        """스크립트 실행 중 print()를 Extension Output Log로 리다이렉트"""
        old_stdout, old_stderr = sys.stdout, sys.stderr
        try:
            sys.stdout = _StdoutToLog(self._append_log)
            sys.stderr = _StdoutToLog(self._append_log)
            yield
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr

    def _run_update_control_files(self):
        """1_generate_behavior_scripts.py 실행"""
        if not self._scripts_dir:
            self._append_log("[ERROR] Project path not found. Click Refresh.")
            return

        script_path = self._scripts_dir / "1_generate_behavior_scripts.py"
        if not script_path.exists():
            self._append_log(f"[ERROR] Script file not found: {script_path}")
            return

        self._append_log("\n" + "=" * 60)
        self._append_log("[INFO] Updating Control files...")
        self._append_log("=" * 60)

        try:
            import importlib.util

            with self._capture_stdout_to_log():
                spec = importlib.util.spec_from_file_location("generate_scripts", script_path)
                if spec is None or spec.loader is None:
                    raise ImportError(f"Failed to load script: {script_path}")

                module = importlib.util.module_from_spec(spec)
                sys.path.insert(0, str(self._scripts_dir))
                spec.loader.exec_module(module)

                if hasattr(module, "main"):
                    module.main()
                    self._append_log("[SUCCESS] Control files updated.")
                else:
                    self._append_log("[WARN] main() not found in script.")

        except Exception as e:
            error_msg = f"[ERROR] Control files update failed: {e}\n{traceback.format_exc()}"
            self._append_log(error_msg)
            print(error_msg)

    def _run_apply_scripts(self):
        """2_apply_script.py의 핵심 기능 실행"""
        if not self._scripts_dir:
            self._append_log("[ERROR] Project path not found. Click Refresh.")
            return

        if not self._config:
            self._append_log("[ERROR] Config could not be loaded.")
            return

        script_path = self._scripts_dir / "2_apply_script.py"
        if not script_path.exists():
            self._append_log(f"[ERROR] Script file not found: {script_path}")
            return

        self._append_log("\n" + "=" * 60)
        self._append_log("[INFO] Applying Behavior Scripts...")
        self._append_log("=" * 60)

        try:
            # 현재 stage 확인
            stage = self._get_stage()
            if stage is None:
                self._append_log("[ERROR] No USD stage open. Open a USD file first.")
                return

            # 2_apply_script.py의 함수들을 직접 호출하기 위해
            # 스크립트를 모듈로 로드하고 필요한 전역 변수 설정
            import importlib.util
            import omni.kit.commands
            from pxr import UsdGeom, Sdf, Gf

            # 기존 sys.path에 scripts 디렉토리 추가
            original_path = sys.path[:]
            try:
                sys.path.insert(0, str(self._scripts_dir))

                # 스크립트를 모듈로 로드
                spec = importlib.util.spec_from_file_location("apply_scripts_module", script_path)
                if spec is None or spec.loader is None:
                    raise ImportError(f"Failed to load script: {script_path}")

                # 스크립트 내용을 읽어서 SimulationApp 부분 제거
                script_content = script_path.read_text(encoding='utf-8')

                # SimulationApp 관련 코드 제거
                lines = script_content.split('\n')
                filtered_lines = []
                skip_app = False
                for line in lines:
                    if 'from isaacsim.simulation_app import SimulationApp' in line:
                        skip_app = True
                        continue
                    if skip_app and ('app = SimulationApp' in line or 'SimulationApp(' in line):
                        continue
                    if skip_app and line.strip() == '':
                        skip_app = False
                        continue
                    filtered_lines.append(line)

                # 필터링된 스크립트를 임시 파일로 저장
                import tempfile
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
                    f.write('\n'.join(filtered_lines))
                    temp_script_path = f.name

                try:
                    spec = importlib.util.spec_from_file_location("apply_scripts_module", temp_script_path)
                    module = importlib.util.module_from_spec(spec)

                    # 전역 변수 설정 (모두 scripts/config.json 기준)
                    module._config = self._config
                    module.SCRIPT_DIR = self._scripts_dir
                    module.PROJECT_ROOT = self._pri_project_path
                    module.ASSET_DIR = self._pri_project_path / self._config["paths"]["asset_dir"]
                    module.CONTROL_DIR = self._pri_project_path / self._config["paths"]["control_dir"]
                    module.SERVER_SCRIPT_PATH = self._scripts_dir / self._config["files"]["server_script"]
                    module.SERVER_PRIM_PATH = self._config["usd"]["server_prim_path"]
                    module.JSON_PATH = module.ASSET_DIR / self._config["files"]["mcc_json"]
                    module.CONTROL_SCRIPT_MAPPING = self._config["usd"].get("control_script_mapping", {})
                    module.CONTROL_UNITS = self._config.get("control_units", [])
                    module.JSON_FIELDS = self._config.get("json_fields", {})

                    module.stage = stage
                    module.usd_ctx = omni.usd.get_context()
                    module.omni = omni
                    module.omni_usd = omni.usd
                    module.omni_kit_commands = omni.kit.commands
                    module.UsdGeom = UsdGeom
                    module.Sdf = Sdf
                    module.Gf = Gf
                    module.Path = Path
                    module.json = json
                    module.re = __import__('re')
                    module.defaultdict = __import__('collections').defaultdict
                    module.List = __import__('typing').List
                    module.Dict = __import__('typing').Dict

                    # Temp script would make load_config() look for config.json in Temp dir.
                    # Point __file__ at real script so Path(__file__).parent = scripts/ and config is found.
                    module.__file__ = str(script_path)

                    with self._capture_stdout_to_log():
                        spec.loader.exec_module(module)
                        if hasattr(module, 'apply_behavior_scripts'):
                            self._append_log("[INFO] Applying Behavior Scripts...")
                            module.apply_behavior_scripts(save_layer=False, apply_server=True)
                            self._append_log("[SUCCESS] Behavior Scripts applied.")
                        if hasattr(module, 'apply_axis_id_and_io_from_json'):
                            self._append_log("[INFO] Applying Axis/IO attributes...")
                            module.apply_axis_id_and_io_from_json(save_layer=False, apply_axis=True, apply_io=True)
                            self._append_log("[SUCCESS] Axis/IO attributes applied.")

                finally:
                    # 임시 파일 삭제
                    try:
                        os.unlink(temp_script_path)
                    except:
                        pass

            finally:
                sys.path[:] = original_path

        except Exception as e:
            error_msg = f"[ERROR] Behavior Script apply failed: {e}\n{traceback.format_exc()}"
            self._append_log(error_msg)
            print(error_msg)

    def _run_all(self):
        """모든 작업 순차 실행"""
        self._append_log("\n" + "=" * 60)
        self._append_log("[INFO] Running all (Update + Apply)...")
        self._append_log("=" * 60)

        self._run_update_control_files()
        self._append_log("\n")
        self._run_apply_scripts()

        self._append_log("\n" + "=" * 60)
        self._append_log("[INFO] All done.")
        self._append_log("=" * 60)
