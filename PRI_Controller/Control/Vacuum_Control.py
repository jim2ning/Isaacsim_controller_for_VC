import carb
from omni.kit.scripting import BehaviorScript
import omni.usd
from pxr import Sdf


class VacuumControlV1(BehaviorScript):
    """
    VacuumControlV1
    - target prim 리스트에 대해:
        * vacuum (Bool)
        * vacuum_address (String)
      attribute를 보장 생성
    - on_stop 시 모든 vacuum = False 초기화
    """

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def on_init(self):
        self._target_prim_paths = [
                    "/Root/Riveting/Geometry/Riveting_Line/Loader/Import_Robot/Gripper/Gripper_Left/Left_low/Left_low_vacuum",
                    "/Root/Riveting/Geometry/Riveting_Line/Loader/Import_Robot/Gripper/Gripper_Right/Right_low/Right_low_vaccum",
    ]

        self._ensure_all_attrs()

    def on_play(self):
        self._ensure_all_attrs()
        pass

    def on_pause(self):
        pass

    def on_stop(self):
        self._reset_all_vacuum_false()

    def on_destroy(self):
        pass

    # ------------------------------------------------------------------
    # attr helpers
    # ------------------------------------------------------------------
    def _ensure_attr(self, prim, name, sdf_type, default_value):
        if not prim or not prim.IsValid():
            return None

        attr = prim.GetAttribute(name)
        if not attr:
            attr = prim.CreateAttribute(name, sdf_type, custom=True)
            if default_value is not None:
                attr.Set(default_value)
        elif default_value is not None and not attr.HasAuthoredValueOpinion():
            attr.Set(default_value)

        return attr

    def _ensure_all_attrs(self):
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            return

        for prim_path in self._target_prim_paths:
            prim = stage.GetPrimAtPath(prim_path)
            if not prim or not prim.IsValid():
                continue

            # vacuum ON/OFF
            self._ensure_attr(
                prim,
                "vacuum",
                Sdf.ValueTypeNames.Bool,
                False,
            )

            # Aurora address (string)
            self._ensure_attr(
                prim,
                "vacuum_server_address",
                Sdf.ValueTypeNames.String,
                "",
            )
            self._ensure_attr(
                prim,
                "vacuum_client_address",
                Sdf.ValueTypeNames.String,
                "",
            )

    # ------------------------------------------------------------------
    # reset helpers
    # ------------------------------------------------------------------
    def _reset_all_vacuum_false(self):
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            return

        for prim_path in self._target_prim_paths:
            prim = stage.GetPrimAtPath(prim_path)
            if not prim or not prim.IsValid():
                continue

            attr = prim.GetAttribute("vacuum")
            if attr:
                attr.Set(False)