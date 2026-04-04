from __future__ import annotations
from typing import Any, cast, TYPE_CHECKING
from datetime import datetime, timedelta
from ...const import (
    VirtualFunctions,
    DescriptionVirtualFunction,
    LOGGER,  # noqa: F401
    XTMultiManagerProperties,
)
import custom_components.xtend_tuya.multi_manager.shared.shared_classes as shared
import custom_components.xtend_tuya.multi_manager.shared.merging_manager as merging_manager

import custom_components.xtend_tuya.sensor as sensor

if TYPE_CHECKING:
    import custom_components.xtend_tuya.multi_manager.multi_manager as mm


class XTVirtualFunctionHandler:
    def __init__(self, multi_manager: mm.MultiManager) -> None:
        self.descriptors_with_virtual_function = {}
        self.multi_manager = multi_manager

    def register_device_descriptors(self, name: str, descriptors):
        descriptors_with_vf = {}
        for category in descriptors:
            description_list_vf: list = []
            category_item = descriptors[category]
            if isinstance(category_item, tuple):
                for description in category_item:
                    if (
                        hasattr(description, "virtual_function")
                        and description.virtual_function is not None
                    ):
                        description_list_vf.append(description)

            else:
                # category is directly a descriptor
                if (
                    hasattr(category_item, "virtual_function")
                    and category_item.virtual_function is not None
                ):
                    description_list_vf.append(category_item)

            if len(description_list_vf) > 0:
                descriptors_with_vf[category] = tuple(description_list_vf)

        if len(descriptors_with_vf) > 0:
            self.descriptors_with_virtual_function[name] = descriptors_with_vf

    def get_category_virtual_functions(
        self, category: str
    ) -> list[DescriptionVirtualFunction]:
        to_return = []
        for virtual_function in VirtualFunctions:
            if virtual_function.name is None or virtual_function.value is None:
                continue
            for descriptor in self.descriptors_with_virtual_function.values():
                if descriptions := descriptor.get(category):
                    for description in descriptions:
                        if (
                            description.virtual_function is not None
                            and description.virtual_function & virtual_function.value
                        ):
                            # This virtual_state is applied to this key, let's return it
                            found_virtual_function = DescriptionVirtualFunction(
                                key=description.key,
                                virtual_function_name=virtual_function.name,
                                virtual_function_value=VirtualFunctions(virtual_function.value),
                                vf_reset_state=(
                                    description.vf_reset_state
                                    if description.vf_reset_state is not None
                                    else []
                                ),
                                vf_history_import_dpcodes=(
                                    description.vf_history_import_dpcodes
                                    if description.vf_history_import_dpcodes is not None
                                    else []
                                ),
                            )
                            to_return.append(found_virtual_function)
        return to_return

    def process_virtual_function(self, device_id: str, commands: list[dict[str, Any]]):
        device: shared.XTDevice | None = self.multi_manager.device_map.get(
            device_id, None
        )
        if not device:
            return
        for command in commands:
            virtual_function: DescriptionVirtualFunction = command["virtual_function"]
            """command_code: str = command["code"]
            command_value: Any = command["value"]"""
            match virtual_function.virtual_function_value:
                case VirtualFunctions.FUNCTION_RESET_STATE:
                    needs_update = False
                    for state_to_reset in virtual_function.vf_reset_state:
                        if state_to_reset in device.status:
                            device.status[state_to_reset] = 0
                            needs_update = True
                    if needs_update:
                        self.multi_manager.multi_device_listener.update_device(device)
                case VirtualFunctions.FUNCTION_IMPORT_ELECTRICAL_HISTORY:
                    now = datetime.now()
                    beginning_of_this_hour = now.replace(minute=0, second=0, microsecond=0)
                    six_days_ago = now.replace(hour=0) - timedelta(days=6)
                    seven_days_ago = now.replace(hour=0) - timedelta(days=7)
                    five_years_and_six_days_ago = six_days_ago.replace(year=six_days_ago.year - 5)
                    result_days = (
                        self.multi_manager.get_device_consumption_statistics_by_day(
                            device_id=device_id,
                            start_day=five_years_and_six_days_ago.strftime("%Y%m%d"),
                            end_day=seven_days_ago.strftime("%Y%m%d"),
                        )
                    )
                    result_hours = (
                        self.multi_manager.get_device_consumption_statistics_by_hour(
                            device_id=device_id,
                            start_day_and_hour=six_days_ago.strftime("%Y%m%d%H"),
                            end_day_and_hour=beginning_of_this_hour.strftime("%Y%m%d%H"),
                        )
                    )
                    overall_result = cast(
                        dict[str, dict[float, float]],
                        merging_manager.XTMergingManager.smart_merge(
                            result_days if result_days is not None else {},
                            result_hours if result_hours is not None else {},
                        ),
                    )
                    all_energy_sensors: dict[str, list[sensor.XTSensorEntity]] = cast(
                        dict[str, list[sensor.XTSensorEntity]],
                        self.multi_manager.get_general_property(
                            XTMultiManagerProperties.ENERGY_SENSOR, {}
                        ),
                    )
                    if device_id in all_energy_sensors:
                        for energy_sensor in all_energy_sensors[device_id]:
                            energy_sensor.import_consumption_history(overall_result)
