import carb
import time
from omni.kit.scripting import BehaviorScript
import omni.usd
from pxr import UsdGeom, Gf, Sdf


class IoControlV3(BehaviorScript):
    """
    IoControlV3

    - self._target_prim_paths 에 들어있는 모든 prim 에 대해 공통 attr 로 모션을 제어한다.
      각 prim 에는 다음 attr 들이 있어야 하며, on_init 시 _reset_all_attr 에서 자동 생성된다.

        * do_server_address     : String  (서버쪽에서만 사용, 여기서는 무시)
        * undo_server_address   : String  (서버쪽에서만 사용, 여기서는 무시)
        * do_client_address     : String  (서버쪽에서만 사용, 여기서는 무시)
        * undo_client_address   : String  (서버쪽에서만 사용, 여기서는 무시)
        * do_action      : Bool    (TTCS 의 position_down 과 같은 역할)
        * undo_action    : Bool    (TTCS 의 position_up   과 같은 역할)
        * prev_do_action : Bool    (rising edge 감지용)
        * prev_undo_action: Bool   (rising edge 감지용)
        * is_moving      : Bool    (현재 모션 진행중 여부)
        * tact_time      : Double  (모션에 걸리는 시간 [초])
        * elapsed_time   : Double  (진행된 시간 [초], 보간용)
        * do_position    : Double3 (do_action 이 True 일 때 목표 translate)
        * undo_position  : Double3 (undo_action 이 True 일 때 목표 translate)

    - 동작 규칙:
        1) do_action 가 False → True (rising edge) 이면:
            - 현재 prim 의 translate 를 start 로 삼고,
            - do_position 으로 tact_time 동안 보간 이동
            - 모션 시작 시:
                * is_moving = True
                * elapsed_time = 0
            - 모션 완료 시:
                * do_action = False
                * is_moving = False
                * elapsed_time = tact_time (또는 0 으로 리셋해도 됨)

        2) undo_action 가 False → True (rising edge) 이면:
            - 현재 prim 의 translate 를 start 로 삼고,
            - undo_position 으로 tact_time 동안 보간 이동
            - 나머지 로직은 do_action 과 동일

    - 한 prim 은 동시에 한 쪽 모션만 수행한다고 가정 (do / undo 는 Aurora 에서 상호 배타적으로 들어옴)
    """

    # ------------------------------------------------------------------
    # 공통 로그 유틸
    # ------------------------------------------------------------------
    def _debug_log(self, msg: str):
        # print 먼저 찍고 carb도 찍는다 (현장 디버깅 편하게)
        try:
            print(msg)
        except Exception:
            pass
        try:
            carb.log_info(msg)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # on_init
    # ------------------------------------------------------------------
    def on_init(self):
        self._debug_log(f"{type(self).__name__}.on_init()->{self.prim_path}")

        # Io 제어 대상 prim 들
        self._target_prim_paths = [
                    "/Root/Riveting/Geometry/Riveting_Line/Loader/Import_Robot/Gripper/Gripper_Left/Left_low",
                    "/Root/Riveting/Geometry/Riveting_Line/Loader/Import_Robot/Gripper/Gripper_Right/Right_low",
                    "/Root/Riveting/Geometry/Riveting_Line/Rivet_1/Press/Press_1",
                    "/Root/Riveting/Geometry/Riveting_Line/Rivet_2/Press/Press_1",
                    "/Root/Riveting/Geometry/Riveting_Line/UnLoader/Export_Robot/Gripper/Gripper_Left/Left_low",
                    "/Root/Riveting/Geometry/Riveting_Line/UnLoader/Export_Robot/Gripper/Gripper_Right/Right_low",
    ]

        # 보정 스케일 (원하면 나중에 position 에 곱해서 쓰도록 확장 가능)
        self._scale = 1.0

        # 성능 모니터링용
        self._perf_window = []  # 최근 N프레임 처리 시간(ms) 모아 평균내기

        # 각 prim 별 모션 상태 저장용
        #   self._motion_state[prim_path] = {
        #       "start": Vec3d,
        #       "goal": Vec3d,
        #       "duration": float,
        #       "tag": "do" or "undo",
        #   }
        self._motion_state = {}

        self._reset_all_attr()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def on_play(self):
        self._debug_log(f"{type(self).__name__}.on_play()->{self.prim_path}")

    def on_pause(self):
        self._debug_log(f"{type(self).__name__}.on_pause()->{self.prim_path}")

    def on_stop(self):
        self._debug_log(f"{type(self).__name__}.on_stop()->{self.prim_path}")
        self._clear_all_attr()
        # 모션 상태도 초기화
        self._motion_state.clear()

    def on_destroy(self):
        self._debug_log(f"{type(self).__name__}.on_destroy()->{self.prim_path}")

    # ------------------------------------------------------------------
    # Attr 유틸
    # ------------------------------------------------------------------
    def _ensure_attr(self, prim, name, sdf_type, default_value):
        """
        prim에 지정 이름의 attribute가 없으면 생성하고, 기본값을 세팅한다.
        생성/획득한 attr 을 반환.
        """
        if not prim or not prim.IsValid():
            carb.log_warn(f"_ensure_attr: invalid prim for {name}")
            return None

        attr = prim.GetAttribute(name)
        if not attr:
            attr = prim.CreateAttribute(name, sdf_type, custom=True)
            if default_value is not None:
                attr.Set(default_value)
        elif default_value is not None and not attr.HasAuthoredValueOpinion():
            attr.Set(default_value)

        return attr

    def _reset_all_attr(self):
        """
        대상 prim 들에 공통 attr 를 모두 생성/초기화.
        """
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            return

        for prim_path in self._target_prim_paths:
            prim = stage.GetPrimAtPath(prim_path)
            if not prim or not prim.IsValid():
                continue

            # Aurora 주소 (서버 측에서만 사용, 여기서는 로직에서 사용하지 않음)
            self._ensure_attr(
                prim, "do_server_address", Sdf.ValueTypeNames.String, ""
            )
            self._ensure_attr(
                prim, "undo_server_address", Sdf.ValueTypeNames.String, ""
            )
            self._ensure_attr(
                prim, "do_client_address", Sdf.ValueTypeNames.String, ""
            )
            self._ensure_attr(
                prim, "undo_client_address", Sdf.ValueTypeNames.String, ""
            )

            # 액션 토글 + 이전값
            self._ensure_attr(
                prim, "do_action", Sdf.ValueTypeNames.Bool, False
            )
            self._ensure_attr(
                prim, "undo_action", Sdf.ValueTypeNames.Bool, False
            )
            self._ensure_attr(
                prim, "prev_do_action", Sdf.ValueTypeNames.Bool, False
            )
            self._ensure_attr(
                prim, "prev_undo_action", Sdf.ValueTypeNames.Bool, False
            )

            # 모션 상태
            self._ensure_attr(
                prim, "is_moving", Sdf.ValueTypeNames.Bool, False
            )
            self._ensure_attr(
                prim, "tact_time", Sdf.ValueTypeNames.Double, 0.0
            )
            self._ensure_attr(
                prim, "elapsed_time", Sdf.ValueTypeNames.Double, 0.0
            )

            # 목표 위치
            self._ensure_attr(
                prim,
                "do_position",
                Sdf.ValueTypeNames.Double3,
                Gf.Vec3d(0.0, 0.0, 0.0),
            )
            self._ensure_attr(
                prim,
                "undo_position",
                Sdf.ValueTypeNames.Double3,
                Gf.Vec3d(0.0, 0.0, 0.0),
            )

    # ------------------------------------------------------------------
    # 상태 리셋용 유틸 (이름은 기존 ltcs 의 _clear_all_target_pos 를 재활용)
    # ------------------------------------------------------------------
    def _clear_all_attr(self):
        """
        시뮬레이션 중단 시 각 대상 prim의 액션/모션 상태를 초기화.
        (이름은 target_pos 이지만 여기서는 attr 들을 리셋하는 역할로 사용)
        """
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            return

        for prim_path in self._target_prim_paths:
            prim = stage.GetPrimAtPath(prim_path)
            if not prim or not prim.IsValid():
                continue

            do_action_attr = prim.GetAttribute("do_action")
            undo_action_attr = prim.GetAttribute("undo_action")
            prev_do_attr = prim.GetAttribute("prev_do_action")
            prev_undo_attr = prim.GetAttribute("prev_undo_action")
            is_moving_attr = prim.GetAttribute("is_moving")
            elapsed_attr = prim.GetAttribute("elapsed_time")

            if do_action_attr:
                do_action_attr.Set(False)
            if undo_action_attr:
                undo_action_attr.Set(False)
            if prev_do_attr:
                prev_do_attr.Set(False)
            if prev_undo_attr:
                prev_undo_attr.Set(False)
            if is_moving_attr:
                is_moving_attr.Set(False)
            if elapsed_attr:
                elapsed_attr.Set(0.0)

    # ------------------------------------------------------------------
    # 공용 Vec3d 유틸 (보간용)
    # ------------------------------------------------------------------
    def _resolve_translate_op(self, prim_path):
        stage = omni.usd.get_context().get_stage()
        if not stage:
            return None
        prim = stage.GetPrimAtPath(prim_path)
        if not prim or not prim.IsValid():
            carb.log_warn(f"Invalid prim for translate op: {prim_path}")
            return None

        xform = UsdGeom.Xformable(prim)
        ops = [
            op
            for op in xform.GetOrderedXformOps()
            if op.GetOpType() == UsdGeom.XformOp.TypeTranslate
        ]
        return ops[0] if ops else xform.AddTranslateOp()

    def _get_trans(self, trans_op):
        if not trans_op:
            return Gf.Vec3d(0.0, 0.0, 0.0)
        v = trans_op.Get()
        if v is None:
            return Gf.Vec3d(0.0, 0.0, 0.0)
        return Gf.Vec3d(float(v[0]), float(v[1]), float(v[2]))

    def _set_trans(self, trans_op, vec3):
        if not trans_op:
            return
        trans_op.Set(Gf.Vec3d(float(vec3[0]), float(vec3[1]), float(vec3[2])))

    def _lerp_vec3(self, a, b, u: float):
        return Gf.Vec3d(
            a[0] + (b[0] - a[0]) * u,
            a[1] + (b[1] - a[1]) * u,
            a[2] + (b[2] - a[2]) * u,
        )

    # ------------------------------------------------------------------
    # on_update
    # ------------------------------------------------------------------
    def on_update(self, current_time: float, delta_time: float):
        """
        매 프레임마다:
        - 각 Target Prim 에 대해 do_action / undo_action 토글 rising edge 감지
        - tact_time 동안 translate 보간 이동
        - 성능 로깅
        """
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            return

        start_t = time.perf_counter()

        # ================= Target Prim 업데이트 ============================
        for prim_path in self._target_prim_paths:
            prim = stage.GetPrimAtPath(prim_path)
            if not prim or not prim.IsValid():
                continue

            # ----- attr 가져오기 -----
            do_action_attr = prim.GetAttribute("do_action")
            undo_action_attr = prim.GetAttribute("undo_action")
            prev_do_action_attr = prim.GetAttribute("prev_do_action")
            prev_undo_action_attr = prim.GetAttribute("prev_undo_action")
            tact_time_attr = prim.GetAttribute("tact_time")
            elapsed_time_attr = prim.GetAttribute("elapsed_time")
            do_position_attr = prim.GetAttribute("do_position")
            undo_position_attr = prim.GetAttribute("undo_position")
            is_moving_attr = prim.GetAttribute("is_moving")

            if (
                    not do_action_attr
                    or not undo_action_attr
                    or not prev_do_action_attr
                    or not prev_undo_action_attr
                    or not tact_time_attr
                    or not elapsed_time_attr
                    or not do_position_attr
                    or not undo_position_attr
                    or not is_moving_attr
            ):
                # attr 가 빠져있으면 스킵 (이론상 여기 안 들어와야 함)
                continue

            # ----- 현재 값 읽기 -----
            do_action = bool(do_action_attr.Get())
            undo_action = bool(undo_action_attr.Get())
            prev_do = bool(prev_do_action_attr.Get())
            prev_undo = bool(prev_undo_action_attr.Get())
            is_moving = bool(is_moving_attr.Get())

            # rising edge 감지
            monitor_do = do_action and (not prev_do)
            monitor_undo = undo_action and (not prev_undo)

            # translate op 확보
            trans_op = self._resolve_translate_op(prim_path)
            if not trans_op:
                continue

            # tact_time 읽기 (0 이하라면 delta_time 으로 강제 1 프레임 처리)
            tact_time_val = tact_time_attr.Get()
            try:
                tact_time = float(tact_time_val) if tact_time_val is not None else 0.0
            except Exception:
                tact_time = 0.0
            if tact_time <= 0.0:
                tact_time = 0.0  # 0.0 이면 한 프레임에 바로 점프 시키는 걸로 해도 됨

            # 목표 위치 읽기
            do_pos_val = do_position_attr.Get()
            undo_pos_val = undo_position_attr.Get()
            do_pos = Gf.Vec3d(0.0, 0.0, 0.0)
            undo_pos = Gf.Vec3d(0.0, 0.0, 0.0)
            if do_pos_val is not None:
                do_pos = Gf.Vec3d(float(do_pos_val[0]), float(do_pos_val[1]), float(do_pos_val[2]))
            if undo_pos_val is not None:
                undo_pos = Gf.Vec3d(float(undo_pos_val[0]), float(undo_pos_val[1]), float(undo_pos_val[2]))

            # ----- do_action rising edge -----
            if monitor_do:
                current_pos = self._get_trans(trans_op)

                # 모션 상태 설정
                duration = tact_time if tact_time > 0.0 else delta_time
                self._motion_state[prim_path] = {
                    "start": Gf.Vec3d(current_pos),
                    "goal": Gf.Vec3d(do_pos),
                    "duration": duration,
                    "tag": "do",
                }

                elapsed_time_attr.Set(0.0)
                is_moving_attr.Set(True)

            # ----- undo_action rising edge -----
            if monitor_undo:
                current_pos = self._get_trans(trans_op)

                duration = tact_time if tact_time > 0.0 else delta_time
                self._motion_state[prim_path] = {
                    "start": Gf.Vec3d(current_pos),
                    "goal": Gf.Vec3d(undo_pos),
                    "duration": duration,
                    "tag": "undo",
                }

                elapsed_time_attr.Set(0.0)
                is_moving_attr.Set(True)

            # ----- 모션 진행 (보간) -----
            is_moving = bool(is_moving_attr.Get())
            motion = self._motion_state.get(prim_path, None)

            if is_moving and motion is not None:
                # 경과 시간 업데이트
                elapsed_val = elapsed_time_attr.Get()
                try:
                    elapsed = float(elapsed_val) if elapsed_val is not None else 0.0
                except Exception:
                    elapsed = 0.0
                elapsed += delta_time
                elapsed_time_attr.Set(elapsed)

                duration = motion.get("duration", delta_time)
                if duration <= 1e-6:
                    duration = delta_time

                u = min(elapsed / duration, 1.0)
                new_pos = self._lerp_vec3(motion["start"], motion["goal"], u)
                self._set_trans(trans_op, new_pos)

                if u >= 1.0:
                    # 모션 완료
                    tag = motion.get("tag", "")
                    if tag == "do":
                        do_action_attr.Set(False)
                    elif tag == "undo":
                        undo_action_attr.Set(False)

                    is_moving_attr.Set(False)
                    # 필요하면 elapsed_time 을 0 으로 리셋 (지금은 duration 으로 남겨둔다)
                    # elapsed_time_attr.Set(0.0)
                    # 상태 제거
                    self._motion_state.pop(prim_path, None)

            # prev 플래그 갱신
            prev_do_action_attr.Set(do_action)
            prev_undo_action_attr.Set(undo_action)

        # ================= 퍼포먼스 측정 ============================
        end_t = time.perf_counter()
        elapsed_ms = (end_t - start_t) * 1000.0

        # 최근 프레임들의 수행 시간 rolling 평균
        self._perf_window.append(elapsed_ms)
        if len(self._perf_window) > 30:
            self._perf_window.pop(0)

        # 만약 20ms 초과 시 경고 출력
        if elapsed_ms > 20.0:
            self._debug_log(
                f"[IoControlV1 ⚠] Frame processing exceeded 20ms: {elapsed_ms:.3f} ms"
            )
