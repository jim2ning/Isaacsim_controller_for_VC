import carb
import time
from omni.kit.scripting import BehaviorScript
import omni.usd
from pxr import UsdGeom, Gf, Sdf


class MotorControlV3(BehaviorScript):
    """
    - target_pos + target_rotate 반영 버전
    - 제어 대상 prim 목록을 코드 내부 리스트(self._target_prim_paths)에 하드코딩.
    - 각 prim은 다음 attr를 가진다고 가정:
        * 'target_pos'      : double3 (erver 에서 갱신, 직선축 X/Y/Z 위치)
        * 'target_rotate'   : double  (Server 에서 갱신, 회전축 Tx/Ty/Tz 각도)
        * 'aurora_axis'     : string  (예: "X,Y" 또는 "Tx" 등, 회전축 판단에 사용)
        * 'aurora_axis_id'  : string  (여기서는 직접 사용하진 않음)

    - 이 스크립트는 매 프레임마다:
        1) self._target_prim_paths의 prim들을 순회하면서
        2) 각 prim의 'target_pos'(double3), 'target_rotate'(double)를 읽고
        3) target_pos → translateOp(xformOp:translate)에 반영
        4) target_rotate → rotateOp(xformOp:rotateX/Y/Z/rotateXYZ)에 반영

      예)
        target_pos    = (0, 30, 0)  → translateOp = (0, 30, 0)
        target_rotate = 45          → aurora_axis에 Tx가 있으면 X축 기준 회전 45도

    - 대상 prim에 double3 타입의 'target_pos' / double 타입의 'target_rotate' 가 없으면
      스크립트가 자동으로 생성하고 (0,0,0) / 0.0 으로 초기화한다.
    """

    # ------------------------------------------------
    # 기본 유틸 / 로그
    # ------------------------------------------------
    def _debug_log(self, msg: str):
        try:
            print(msg)
        except Exception:
            pass
        try:
            carb.log_info(msg)
        except Exception:
            pass

    # ------------------------------------------------
    # Lifecycle
    # ------------------------------------------------
    def on_init(self):    
        self._stage = omni.usd.get_context().get_stage()
        if self._stage is None:
            self._debug_log("[MotorControl] Stage is None in on_init")
            return

        # ✅ 여기 리스트에 '제어하고 싶은 prim path'만 계속 추가해서 사용
        self._target_prim_paths = [
                    "/Root/Riveting/Geometry/Riveting_Line/Main_Line/Rivet_Line_1/LMS_Carrier_1",
                    "/Root/Riveting/Geometry/Riveting_Line/Main_Line/Rivet_Line_2/LMS_Carrier_2",
                    "/Root/Riveting/Geometry/Riveting_Line/UnLoader/UnLoader_Robot/Line_Loader",
    ]

        # 전체 스케일 (필요 없으면 1.0으로 고정)
        self._scale = 0.001

        # 성능 모니터링용
        self._perf_window = []  # 최근 N프레임 처리 시간(ms)

        # 초기화 시, 대상 prim들에 target_pos / target_rotate attr 없으면 생성
        for p in self._target_prim_paths:
            prim = self._stage.GetPrimAtPath(p)
            if not prim or not prim.IsValid():
                continue
            self._ensure_target_pos_attr(prim)
            self._ensure_target_rotate_attr(prim)
            self._ensure_aurora_axis_attr(prim)
            self._ensure_aurora_axis_id_attr(prim)

    def on_destroy(self):
        self._debug_log(f"{type(self).__name__}.on_destroy()->{self.prim_path}")

    def on_play(self):
        self._debug_log(f"{type(self).__name__}.on_play()->{self.prim_path}")

    def on_pause(self):
        self._debug_log(f"{type(self).__name__}.on_pause()->{self.prim_path}")

    def on_stop(self):
        self._debug_log(f"{type(self).__name__}.on_stop()->{self.prim_path}")
        # 스탑 시, target_pos / target_rotate 초기화
        # self._clear_all_target_pos()
        self._clear_all_target_rotate()

    # ------------------------------------------------
    # Attr 관련 유틸
    # ------------------------------------------------
    def _ensure_target_pos_attr(self, prim):
        """
        prim에 double3 타입의 'target_pos' attr이 없으면 생성하고 (0,0,0)으로 초기화.
        항상 double3 attr 객체를 반환.
        """
        attr = prim.GetAttribute("target_pos")

        # 타입 체크: double3가 아니면 기존 attr을 삭제하고 새로 만든다.
        if attr and attr.GetTypeName() != Sdf.ValueTypeNames.Double3:
            # 기존 attr이 있지만 타입이 다르면 삭제
            prim.RemoveProperty("target_pos")
            attr = None

        if not attr:
            attr = prim.CreateAttribute(
                "target_pos",
                Sdf.ValueTypeNames.Double3,
                custom=True,
            )
            attr.Set(Gf.Vec3d(0.0, 0.0, 0.0))

        # 값이 None이면 (0,0,0)으로 세팅
        if attr.Get() is None:
            attr.Set(Gf.Vec3d(0.0, 0.0, 0.0))

        return attr

    def _ensure_target_rotate_attr(self, prim):
        """
        prim에 double 타입의 'target_rotate' attr이 없으면 생성하고 0.0으로 초기화.
        항상 double attr 객체를 반환.
        """
        attr = prim.GetAttribute("target_rotate")

        # 타입 체크: double가 아니면 기존 attr을 삭제하고 새로 만든다.
        if attr and attr.GetTypeName() != Sdf.ValueTypeNames.Double:
            # 기존 attr이 있지만 타입이 다르면 삭제
            prim.RemoveProperty("target_rotate")
            attr = None

        if not attr:
            attr = prim.CreateAttribute(
                "target_rotate",
                Sdf.ValueTypeNames.Double,
                custom=True,
            )
            attr.Set(0.0)

        if attr.Get() is None:
            attr.Set(0.0)

        return attr

    def _ensure_aurora_axis_attr(self, prim):
        """
        prim에 string 타입의 'aurora_axis' attr이 없으면 생성하고 ""으로 초기화.
        항상 string attr 객체를 반환.
        """
        attr = prim.GetAttribute("aurora_axis")

        # 타입 체크: string이 아니면 기존 attr을 삭제하고 새로 만든다.
        if attr and attr.GetTypeName() != Sdf.ValueTypeNames.String:
            # 기존 attr이 있지만 타입이 다르면 삭제
            prim.RemoveProperty("aurora_axis")
            attr = None

        if not attr:
            attr = prim.CreateAttribute(
                "aurora_axis",
                Sdf.ValueTypeNames.String,
                custom=True,
            )
            attr.Set("None")

        if attr.Get() is None:
            attr.Set("None")

        return attr

    def _ensure_aurora_axis_id_attr(self, prim):
        """
        prim에 string 타입의 'aurora_axis_id' attr이 없으면 생성하고 ""으로 초기화.
        항상 string attr 객체를 반환.
        """
        attr = prim.GetAttribute("aurora_axis_id")

        # 타입 체크: string이 아니면 기존 attr을 삭제하고 새로 만든다.
        if attr and attr.GetTypeName() != Sdf.ValueTypeNames.String:
            # 기존 attr이 있지만 타입이 다르면 삭제
            prim.RemoveProperty("aurora_axis_id")
            attr = None

        if not attr:
            attr = prim.CreateAttribute(
                "aurora_axis_id",
                Sdf.ValueTypeNames.String,
                custom=True,
            )
            attr.Set("None")

        if attr.Get() is None:
            attr.Set("None")

        return attr

    def _clear_all_target_pos(self):
        """
        시뮬레이션 중단 시 각 대상 prim의 target_pos(double3)를 (0,0,0)으로 초기화.
        """
        if self._stage is None:
            return

        zero = Gf.Vec3d(0.0, 0.0, 0.0)

        for p in self._target_prim_paths:
            prim = self._stage.GetPrimAtPath(p)
            if not prim or not prim.IsValid():
                continue

            attr = self._ensure_target_pos_attr(prim)
            attr.Set(zero)

    def _clear_all_target_rotate(self):
        """
        시뮬레이션 중단 시 각 대상 prim의 target_rotate(double)를 0.0으로 초기화.
        (rotateOp 자체는 건드리지 않음)
        """
        if self._stage is None:
            return

        for p in self._target_prim_paths:
            prim = self._stage.GetPrimAtPath(p)
            if not prim or not prim.IsValid():
                continue

            attr = self._ensure_target_rotate_attr(prim)
            attr.Set(0.0)

    def _get_current_target_pos(self, prim) -> Gf.Vec3d:
        """
        prim의 target_pos(double3) attr 값을 읽어서 Gf.Vec3d로 반환.
        - attr이 없거나 타입이 다르면 double3로 새로 만들고 (0,0,0)을 반환.
        - 값이 시퀀스/Vec3 계열이면 Vec3d로 캐스팅.
        """
        attr = self._ensure_target_pos_attr(prim)
        val = attr.Get()

        if val is None:
            return Gf.Vec3d(0.0, 0.0, 0.0)

        try:
            # 이미 Gf.Vec3d / Vec3f / Vec3h 인 경우
            if isinstance(val, (Gf.Vec3d, Gf.Vec3f, Gf.Vec3h)):
                return Gf.Vec3d(float(val[0]), float(val[1]), float(val[2]))

            # tuple/list/기타 시퀀스인 경우
            if hasattr(val, "__len__") and len(val) == 3:
                return Gf.Vec3d(float(val[0]), float(val[1]), float(val[2]))

        except Exception:
            pass

        # 이상한 값이면 0,0,0
        return Gf.Vec3d(0.0, 0.0, 0.0)

    def _get_current_target_rotate(self, prim) -> float:
        """
        prim의 target_rotate(double) attr 값을 float으로 반환.
        - attr이 없거나 이상한 값이면 0.0 반환.
        """
        attr = self._ensure_target_rotate_attr(prim)
        val = attr.Get()

        if val is None:
            return 0.0

        try:
            return float(val)
        except Exception:
            return 0.0

    def _get_rotation_axis_index_from_aurora_axis(self, prim) -> int:
        """
        prim의 aurora_axis string에서 Tx/Ty/Tz 중 첫 번째로 등장하는 축을 보고
        회전축 index (0:x, 1:y, 2:z)를 결정.
        - 예: "Tx,Ty" → 0, "Ty" → 1, "Tz" → 2
        - 없으면 기본값 1(Y축) 반환.
        """
        attr = prim.GetAttribute("aurora_axis")
        if not attr or attr.GetTypeName() != Sdf.ValueTypeNames.String:
            return 1  # default Y

        raw = attr.Get()
        if not isinstance(raw, str):
            return 1

        tokens = [s.strip().upper() for s in raw.split(",") if s.strip()]
        for t in tokens:
            if t in ("TX", "TY", "TZ"):
                if t == "TX":
                    return 0
                if t == "TY":
                    return 1
                if t == "TZ":
                    return 2

        # Tx/Ty/Tz가 없으면 기본 Y축
        return 1

    def _update_prim_translate_vec(self, prim, vec: Gf.Vec3d):
        """
        prim의 translateOp(xformOp:translate)을 vec(x,y,z)로 설정.
        기존 translateOp가 있으면 값을 덮어쓰고, 없으면 새로 만든다.
        """
        xform = UsdGeom.Xformable(prim)

        # translate op 찾기
        ops = xform.GetOrderedXformOps()
        translate_op = None
        for op in ops:
            if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
                translate_op = op
                break

        # 없으면 새로 하나 만든다
        if translate_op is None:
            translate_op = xform.AddTranslateOp()

        translate_op.Set(Gf.Vec3d(float(vec[0]), float(vec[1]), float(vec[2])))

    def _update_prim_rotate_scalar(self, prim, angle_deg: float):
        """
        prim의 rotateOp를 angle_deg로 설정.
        - 기존에 rotateX/rotateY/rotateZ 가 있으면 그 op에만 angle_deg 세팅.
        - 아니면 rotateXYZ op를 만들고, aurora_axis의 Tx/Ty/Tz 기준으로
          해당 축 component에만 angle_deg 세팅.
        """
        xform = UsdGeom.Xformable(prim)
        ops = xform.GetOrderedXformOps()

        rotate_op = None
        for op in ops:
            optype = op.GetOpType()
            if optype in (
                UsdGeom.XformOp.TypeRotateX,
                UsdGeom.XformOp.TypeRotateY,
                UsdGeom.XformOp.TypeRotateZ,
                UsdGeom.XformOp.TypeRotateXYZ,
            ):
                rotate_op = op
                break

        # 기존 rotateOp가 없으면 rotateXYZ를 새로 만들어 사용
        if rotate_op is None:
            rotate_op = xform.AddRotateXYZOp()
            axis_index = self._get_rotation_axis_index_from_aurora_axis(prim)
            vec = Gf.Vec3d(0.0, 0.0, 0.0)
            vec[axis_index] = float(angle_deg)
            rotate_op.Set(vec)
            return

        optype = rotate_op.GetOpType()

        # rotateX / rotateY / rotateZ 인 경우: 단일 값으로 세팅
        if optype in (
            UsdGeom.XformOp.TypeRotateX,
            UsdGeom.XformOp.TypeRotateY,
            UsdGeom.XformOp.TypeRotateZ,
        ):
            rotate_op.Set(float(angle_deg))
            return

        # rotateXYZ 인 경우: Vec3d의 특정 축 component만 세팅
        if optype == UsdGeom.XformOp.TypeRotateXYZ:
            current = rotate_op.Get()
            if current is None:
                current = Gf.Vec3d(0.0, 0.0, 0.0)

            axis_index = self._get_rotation_axis_index_from_aurora_axis(prim)
            current[axis_index] = float(angle_deg)
            rotate_op.Set(current)
            return

    # ------------------------------------------------
    # 메인 업데이트
    # ------------------------------------------------
    def on_update(self, current_time: float, delta_time: float):
        if self._stage is None:
            return

        start_t = time.perf_counter()

        for p in self._target_prim_paths:
            prim = self._stage.GetPrimAtPath(p)
            if not prim or not prim.IsValid():
                continue

            # 1) double3 target_pos 읽기 (없으면 자동 생성 + (0,0,0))
            target_vec = self._get_current_target_pos(prim)

            # 2) double target_rotate 읽기 (없으면 자동 생성 + 0.0)
            target_rot = self._get_current_target_rotate(prim)

            # 3) 스케일 적용 (translation 에만)
            if self._scale != 1.0:
                target_vec = Gf.Vec3d(
                    target_vec[0] * self._scale,
                    target_vec[1] * self._scale,
                    target_vec[2] * self._scale,
                )

            # 4) translateOp에 반영
            self._update_prim_translate_vec(prim, target_vec)

            # 5) rotateOp에 반영 (aurora_axis 기준 Tx/Ty/Tz 축 사용)
            if abs(target_rot) > 0.000001:
                # 0 근처면 굳이 갱신 안 해도 되지만, 필요하면 조건 제거 가능
                self._update_prim_rotate_scalar(prim, target_rot)
            else:
                # 0일 때도 항상 회전을 0으로 맞추고 싶으면 아래 주석 해제
                # self._update_prim_rotate_scalar(prim, 0.0)
                pass

        end_t = time.perf_counter()
        elapsed_ms = (end_t - start_t) * 1000.0

        self._perf_window.append(elapsed_ms)
        if len(self._perf_window) > 30:
            self._perf_window.pop(0)

        # 20ms 넘으면 경고 로그
        if elapsed_ms > 20.0:
            self._debug_log(
                f"[MotorControl⚠] Frame processing exceeded 20ms: {elapsed_ms:.3f} ms"
            )