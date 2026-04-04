"""Support for the XT lights."""

from __future__ import annotations
from typing import cast
from dataclasses import dataclass
from tuya_device_handlers.definition.light import (
    TuyaLightDefinition,
    get_default_definition,
)
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .util import (
    restrict_descriptor_category,
)
from .multi_manager.multi_manager import (
    XTConfigEntry,
    MultiManager,
    XTDevice,
)
from .const import (
    TUYA_DISCOVERY_NEW,
    XTDPCode,
    XTMultiManagerPostSetupCallbackPriority,
)
from .ha_tuya_integration.tuya_integration_imports import (
    TuyaLightEntity,
    TuyaLightEntityDescription,
    TuyaDPCode,
)
from .entity import (
    XTEntity,
    XTEntityDescriptorManager,
)


@dataclass(frozen=True)
class XTLightEntityDescription(TuyaLightEntityDescription):
    """Describe an Tuya light entity."""

    brightness_max: TuyaDPCode | XTDPCode | None = None  # type: ignore
    brightness_min: TuyaDPCode | XTDPCode | None = None  # type: ignore
    brightness: (  # type: ignore
        TuyaDPCode | tuple[TuyaDPCode, ...] | XTDPCode | tuple[XTDPCode, ...] | None
    ) = None
    color_data: (  # type: ignore
        TuyaDPCode | tuple[TuyaDPCode, ...] | XTDPCode | tuple[XTDPCode, ...] | None
    ) = None
    color_mode: TuyaDPCode | XTDPCode | None = None  # type: ignore
    color_temp: (  # type: ignore
        TuyaDPCode | tuple[TuyaDPCode, ...] | XTDPCode | tuple[XTDPCode, ...] | None
    ) = None

    # duplicate the entity if handled by another integration
    ignore_other_dp_code_handler: bool = False

    def get_entity_instance(
        self,
        device: XTDevice,
        device_manager: MultiManager,
        description: XTLightEntityDescription,
        definition: TuyaLightDefinition,
    ) -> XTLightEntity:
        return XTLightEntity(
            device=device,
            device_manager=device_manager,
            description=XTLightEntityDescription(**description.__dict__),
            definition=definition,
        )


LIGHTS: dict[str, tuple[XTLightEntityDescription, ...]] = {
    "dbl": (
        XTLightEntityDescription(
            key=XTDPCode.LIGHT,
            translation_key="light",
            brightness=XTDPCode.BRIGHT_VALUE,
        ),
    ),
    "msp": (
        XTLightEntityDescription(
            key=XTDPCode.LIGHT,
            translation_key="light",
            entity_category=EntityCategory.CONFIG,
        ),
    ),
}


async def async_setup_entry(
    hass: HomeAssistant, entry: XTConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up tuya light dynamically through tuya discovery."""
    hass_data = entry.runtime_data
    this_platform = Platform.LIGHT

    if entry.runtime_data.multi_manager is None or hass_data.manager is None:
        return

    supported_descriptors, externally_managed_descriptors = cast(
        tuple[
            dict[str, tuple[XTLightEntityDescription, ...]],
            dict[str, tuple[XTLightEntityDescription, ...]],
        ],
        XTEntityDescriptorManager.get_platform_descriptors(
            LIGHTS,
            entry.runtime_data.multi_manager,
            XTLightEntityDescription,
            this_platform,
        ),
    )

    @callback
    def async_add_generic_entities(device_map) -> None:
        if hass_data.manager is None:
            return
        entities: list[XTLightEntity] = []
        device_ids = [*device_map]
        for device_id in device_ids:
            if device := hass_data.manager.device_map.get(device_id):
                generic_dpcodes = XTEntity.get_generic_dpcodes_for_this_platform(
                    device, this_platform
                )
                for dpcode in generic_dpcodes:
                    description = XTLightEntityDescription(
                        key=dpcode,
                        translation_key="xt_generic_light",
                        translation_placeholders={
                            "name": XTEntity.get_human_name(dpcode)
                        },
                        entity_registry_enabled_default=False,
                        entity_registry_visible_default=False,
                    )
                    if definition := get_default_definition(
                        device=device,
                        switch_dpcode=description.key,
                        brightness_dpcode=description.brightness,
                        brightness_max_dpcode=description.brightness_max,
                        brightness_min_dpcode=description.brightness_min,
                        color_data_dpcode=description.color_data,
                        color_mode_dpcode=description.color_mode,
                        color_temp_dpcode=description.color_temp,
                        fallback_color_data_mode=description.fallback_color_data_mode,
                    ):
                        entities.append(
                            XTLightEntity.get_entity_instance(
                                device=device,
                                device_manager=hass_data.manager,
                                description=description,
                                definition=definition,
                            )
                        )
        async_add_entities(entities)

    @callback
    def async_discover_device(device_map, restrict_dpcode: str | None = None) -> None:
        """Discover and add a discovered tuya light."""
        if hass_data.manager is None:
            return
        entities: list[XTLightEntity] = []
        device_ids = [*device_map]
        for device_id in device_ids:
            if device := hass_data.manager.device_map.get(device_id):
                if category_descriptions := XTEntityDescriptorManager.get_category_descriptors(
                    supported_descriptors, device.category
                ):
                    externally_managed_dpcodes = (
                        XTEntityDescriptorManager.get_category_keys(
                            externally_managed_descriptors.get(device.category)
                        )
                    )
                    if restrict_dpcode is not None:
                        category_descriptions = cast(
                            tuple[XTLightEntityDescription, ...],
                            restrict_descriptor_category(
                                category_descriptions, [restrict_dpcode]
                            ),
                        )
                    entities.extend(
                        XTLightEntity.get_entity_instance(
                            device=device,
                            device_manager=hass_data.manager,
                            description=description,
                            definition=definition,
                        )
                        for description in category_descriptions
                        if (
                            XTEntity.supports_description(
                                device,
                                this_platform,
                                description,
                                True,
                                externally_managed_dpcodes,
                            )
                            and (
                                definition := get_default_definition(
                                    device=device,
                                    switch_dpcode=description.key,
                                    brightness_dpcode=description.brightness,
                                    brightness_max_dpcode=description.brightness_max,
                                    brightness_min_dpcode=description.brightness_min,
                                    color_data_dpcode=description.color_data,
                                    color_mode_dpcode=description.color_mode,
                                    color_temp_dpcode=description.color_temp,
                                    fallback_color_data_mode=description.fallback_color_data_mode,
                                )
                            )
                        )
                    )
                    entities.extend(
                        XTLightEntity.get_entity_instance(
                            device=device,
                            device_manager=hass_data.manager,
                            description=description,
                            definition=definition,
                        )
                        for description in category_descriptions
                        if (
                            XTEntity.supports_description(
                                device,
                                this_platform,
                                description,
                                False,
                                externally_managed_dpcodes,
                            )
                            and (
                                definition := get_default_definition(
                                    device=device,
                                    switch_dpcode=description.key,
                                    brightness_dpcode=description.brightness,
                                    brightness_max_dpcode=description.brightness_max,
                                    brightness_min_dpcode=description.brightness_min,
                                    color_data_dpcode=description.color_data,
                                    color_mode_dpcode=description.color_mode,
                                    color_temp_dpcode=description.color_temp,
                                    fallback_color_data_mode=description.fallback_color_data_mode,
                                )
                            )
                        )
                    )

        async_add_entities(entities)
        if restrict_dpcode is None:
            hass_data.manager.add_post_setup_callback(
                XTMultiManagerPostSetupCallbackPriority.PRIORITY_LAST,
                async_add_generic_entities,
                device_map,
            )

    hass_data.manager.register_device_descriptors(this_platform, supported_descriptors)
    async_discover_device([*hass_data.manager.device_map])

    entry.async_on_unload(
        async_dispatcher_connect(hass, TUYA_DISCOVERY_NEW, async_discover_device)
    )


class XTLightEntity(XTEntity, TuyaLightEntity):
    """XT light device."""

    def __init__(
        self,
        device: XTDevice,
        device_manager: MultiManager,
        description: XTLightEntityDescription,
        definition: TuyaLightDefinition,
    ) -> None:
        super(XTLightEntity, self).__init__(device, device_manager, description)
        super(XTEntity, self).__init__(
            device=device,
            device_manager=device_manager,  # type: ignore
            description=description,
            definition=definition,
        )
        self.device = device
        self.device_manager = device_manager
        self.entity_description = description

    @staticmethod
    def get_entity_instance(
        device: XTDevice,
        device_manager: MultiManager,
        description: XTLightEntityDescription,
        definition: TuyaLightDefinition,
    ) -> XTLightEntity:
        if hasattr(description, "get_entity_instance") and callable(
            getattr(description, "get_entity_instance")
        ):
            return description.get_entity_instance(
                device=device,
                device_manager=device_manager,
                description=description,
                definition=definition,
            )
        return XTLightEntity(
            device=device,
            device_manager=device_manager,
            description=XTLightEntityDescription(**description.__dict__),
            definition=definition,
        )
