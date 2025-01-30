"""Monitor Docker main component."""

import asyncio
import logging
from datetime import timedelta

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.const import (
    CONF_MONITORED_CONDITIONS,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_URL,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryNotReady,
    ConfigEntryError,
    ConfigEntryAuthFailed,
)
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.reload import async_setup_reload_service

from .config_flow import DockerConfigFlow
from .const import (
    API,
    CONF_CERTPATH,
    CONF_CONTAINERS,
    CONF_CONTAINERS_EXCLUDE,
    CONF_MEMORYCHANGE,
    CONF_PRECISION_CPU,
    CONF_PRECISION_MEMORY_MB,
    CONF_PRECISION_MEMORY_PERCENTAGE,
    CONF_PRECISION_NETWORK_KB,
    CONF_PRECISION_NETWORK_MB,
    CONF_PREFIX,
    CONF_RENAME,
    CONF_RENAME_ENITITY,
    CONF_RETRY,
    CONF_SENSORNAME,
    CONF_SWITCHENABLED,
    CONF_SWITCHNAME,
    CONF_BUTTONENABLED,
    CONF_BUTTONNAME,
    CONFIG,
    CONTAINER_INFO_ALLINONE,
    DEFAULT_NAME,
    DEFAULT_RETRY,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SENSORNAME,
    DEFAULT_SWITCHNAME,
    DEFAULT_BUTTONNAME,
    DOMAIN,
    MONITORED_CONDITIONS_LIST,
    PRECISION,
)
from .helpers import DockerAPI

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BUTTON, Platform.SENSOR, Platform.SWITCH]

DOCKER_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_PREFIX, default=""): cv.string,
        vol.Optional(CONF_URL, default=None): vol.Any(cv.string, None),
        vol.Optional(
            CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
        ): cv.positive_int,
        vol.Optional(CONF_MONITORED_CONDITIONS, default=[]): vol.All(
            cv.ensure_list,
            [vol.In(MONITORED_CONDITIONS_LIST)],
        ),
        vol.Optional(CONF_CONTAINERS, default=[]): cv.ensure_list,
        vol.Optional(CONF_CONTAINERS_EXCLUDE, default=[]): cv.ensure_list,
        vol.Optional(CONF_RENAME, default={}): dict,
        vol.Optional(CONF_RENAME_ENITITY, default=False): cv.boolean,
        vol.Optional(CONF_SENSORNAME, default=DEFAULT_SENSORNAME): cv.string,
        vol.Optional(CONF_SWITCHENABLED, default=True): vol.Any(
            cv.boolean, cv.ensure_list(cv.string)
        ),
        vol.Optional(CONF_BUTTONENABLED, default=False): vol.Any(
            cv.boolean, cv.ensure_list(cv.string)
        ),
        vol.Optional(CONF_SWITCHNAME, default=DEFAULT_SWITCHNAME): cv.string,
        vol.Optional(CONF_BUTTONNAME, default=DEFAULT_BUTTONNAME): cv.string,
        vol.Optional(CONF_CERTPATH, default=""): cv.string,
        vol.Optional(CONF_RETRY, default=DEFAULT_RETRY): cv.positive_int,
        vol.Optional(CONF_MEMORYCHANGE, default=100): cv.positive_int,
        vol.Optional(CONF_PRECISION_CPU, default=PRECISION): cv.positive_int,
        vol.Optional(CONF_PRECISION_MEMORY_MB, default=PRECISION): cv.positive_int,
        vol.Optional(
            CONF_PRECISION_MEMORY_PERCENTAGE, default=PRECISION
        ): cv.positive_int,
        vol.Optional(CONF_PRECISION_NETWORK_KB, default=PRECISION): cv.positive_int,
        vol.Optional(CONF_PRECISION_NETWORK_MB, default=PRECISION): cv.positive_int,
    }
)

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.All(cv.ensure_list, [vol.Any(DOCKER_SCHEMA)])}, extra=vol.ALLOW_EXTRA
)


#################################################################
async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Will setup the Monitor Docker platform."""

    if DOMAIN not in config:
        return True  # To continue with async_setup_entry

    # Now go through all possible entries, we support 1 or more docker hosts (untested)
    for entry in config[DOMAIN]:
        # Default MONITORED_CONDITIONS_LIST also contains allinone, so we need to fix it up here
        if len(entry[CONF_MONITORED_CONDITIONS]) == 0:
            # Add whole list, including allinone. Make a copy, no reference
            entry[CONF_MONITORED_CONDITIONS] = MONITORED_CONDITIONS_LIST.copy()
            # remove the allinone
            entry[CONF_MONITORED_CONDITIONS].remove(CONTAINER_INFO_ALLINONE)

        # Check if CONF_MONITORED_CONDITIONS has only ALLINONE, then expand to all
        if (
            len(entry[CONF_MONITORED_CONDITIONS]) == 1
            and CONTAINER_INFO_ALLINONE in entry[CONF_MONITORED_CONDITIONS]
        ):
            entry[CONF_MONITORED_CONDITIONS] = list(MONITORED_CONDITIONS_LIST) + list(
                [CONTAINER_INFO_ALLINONE]
            )

        # Convert the entry to a config_entry
        name = entry.get(CONF_NAME)
        _LOGGER.debug("Starting config entry flow for %s with config %s", name, entry)
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_IMPORT},
                data=entry,
            )
        )
        return True

    return True


#################################################################
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up this integration using UI."""

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    api = None

    try:
        api = DockerAPI(hass, entry.data)
        await api.init()
        await api.run()

        hass.data[DOMAIN][entry.data[CONF_NAME]] = {}
        hass.data[DOMAIN][entry.data[CONF_NAME]][CONFIG] = entry.data
        hass.data[DOMAIN][entry.data[CONF_NAME]][API] = api

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except ConfigEntryAuthFailed:
        # if api:
        #     await api.destroy()
        raise
    except Exception as err:
        _LOGGER.error(
            "[%s]: Failed to setup, error=%s", entry.data[CONF_NAME], str(err)
        )
        if api:
            await api.destroy()
        raise ConfigEntryNotReady(f"Failed to setup {err}") from err

    return True


#################################################################
async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""

    _LOGGER.debug("async_unload_entry")

    await hass.data[DOMAIN][entry.data[CONF_NAME]][API].destroy()

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


#################################################################
async def async_reset_platform(hass: HomeAssistant, integration_name: str) -> None:
    """Reload the integration."""
    if DOMAIN not in hass.data:
        _LOGGER.error("Monitor_docker not loaded")


#################################################################
async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.debug(
        "Attempting migrating configuration from version %s.%s",
        entry.version,
        entry.minor_version,
    )

    class MigrateError(ConfigEntryError):
        """Error to indicate there is was an error in version migration."""

    installed_version = DockerConfigFlow.VERSION
    installed_minor_version = DockerConfigFlow.MINOR_VERSION

    new_data = {**entry.data}
    # new_options = {**entry.options}  # Note used

    if entry.version > installed_version:
        _LOGGER.warning(
            "Downgrading major version from %s to %s is not allowed",
            entry.version,
            installed_version,
        )
        return False

    if (
        entry.version == installed_version
        and entry.minor_version > installed_minor_version
    ):
        _LOGGER.warning(
            "Downgrading minor version from %s.%s to %s.%s is not allowed",
            entry.version,
            entry.minor_version,
            installed_version,
            installed_minor_version,
        )
        return False

    # Fake update function, just as an example
    # def data_1_1_to_1_2(data: dict):
    #     OLD_CERTPATH = "old_certpath_key"
    #     if certpath := data.pop("OLD_CERTPATH", None):
    #         data[CONF_CERTPATH] = certpath
    #         return data
    #     raise MigrateError(f'Could not find "{OLD_CERTPATH}" in data')

    try:
        if entry.version == 1:
            pass
            # Verison 1.1 to 1.2
            # if entry.minor_version == 1:
            #     new_data = data_1_1_to_1_2(new_data)
            #     entry.minor_version = 2
            # Version 1.2 to 2.0
            # if entry.minor_version == 2:
            #     new_data = data_1_2_to_2_0(new_data)
            #     entry.version = 2
            #     entry.minor_version = 0
        # if entry.version == 2:
        #     ...
    except MigrateError as err:
        _LOGGER.error(
            "Error while upgrading from version %s.%s to %s.%s",
            entry.version,
            entry.minor_version,
            installed_version,
            installed_minor_version,
        )
        _LOGGER.error(str(err))
        return False

    hass.config_entries.async_update_entry(
        entry,
        data=new_data,
        # options=new_options,
        version=installed_version,
        minor_version=installed_minor_version,
    )
    _LOGGER.info(
        "Migration configuration from version %s.%s to %s.%s successful",
        entry.version,
        entry.minor_version,
        installed_version,
        installed_minor_version,
    )
    return True
