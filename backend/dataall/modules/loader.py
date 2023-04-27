"""Load modules that are specified in the configuration file"""
import importlib
import logging
import sys
from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import List, Type, Set

from dataall.core.config import config

log = logging.getLogger(__name__)

_MODULE_PREFIX = "dataall.modules"


class ImportMode(Enum):
    """Defines importing mode

    Since there are different infrastructure components that requires only part
    of functionality to be loaded, there should be different loading modes
    """

    API = auto()
    CDK = auto()
    HANDLERS = auto()


class ModuleInterface(ABC):
    """
    An interface of the module. The implementation should be part of __init__.py of the module
    Contains an API that will be called from core part
    """
    @staticmethod
    @abstractmethod
    def is_supported(modes: List[ImportMode]) -> bool:
        """
        Return True if the module interface supports any of the ImportMode and should be loaded
        """
        raise NotImplementedError("is_supported is not implemented")

    @staticmethod
    @abstractmethod
    def name() -> str:
        """
        Returns name of the module. Should be the same if it's specified in the config file
        """
        raise NotImplementedError("name is not implemented")

    @staticmethod
    def depends_on() -> List[Type['ModuleInterface']]:
        """
        It describes on what modules this ModuleInterface depends on.
        It will be used to eventually load these module dependencies. Even if a dependency module is not active
        in the config file.

        The default value is no dependencies
        """
        return []


def load_modules(modes: List[ImportMode]) -> None:
    """
    Loads all modules from the config
    Loads only requested functionality (submodules) using the mode parameter
    """
    try:
        modules = config.get_property("modules")
    except KeyError:
        log.info('"modules" has not been found in the config file. Nothing to load')
        return

    log.info("Found %d modules that have been found in the config", len(modules))

    inactive = set()
    in_config = set()
    for name, props in modules.items():
        in_config.add(name)
        if "active" not in props:
            raise ValueError(f"Status is not defined for {name} module")

        active = props["active"]

        if not active:
            log.info(f"Module {name} is not active. Skipping...")
            inactive.add(name)
            continue

        if not _import_module(name):
            raise ValueError(f"Couldn't find module {name} under modules directory")

        log.info(f"Module {name} is loaded")

    modules = ModuleInterface.__subclasses__()
    for module in modules:
        if module.is_supported(modes):
            module()

    _check_loading_correct()
    _describe_loading(in_config, inactive)

    log.info("All modules have been imported")


def _import_module(name):
    try:
        importlib.import_module(f"{_MODULE_PREFIX}.{name}")
        return True
    except ModuleNotFoundError:
        return False


def _check_loading_correct(in_config: Set[str]):
    """
    To avoid unintentional loading (without ModuleInterface) we can check all loaded modules.
    Unintentional/incorrect loading might happen if module A has a direct reference to module B without declaring it
    in ModuleInterface. Doing so, this might lead to a problem when a module interface require to load something during
    initialization. But since ModuleInterface is not initializing properly (using depends_on)
    some functionality may work wrongly.
    """

    expected_load = set(in_config)
    for module in ModuleInterface.__subclasses__():
        for dependency in module.depends_on():
            expected_load.add(dependency.name())

    for module in ModuleInterface.__subclasses__():
        if module.name() not in expected_load:
            raise ImportError(f"ModuleInterface has not been initialized for module {module.name()}")

    for module in sys.modules.keys():
        if module.startswith(_MODULE_PREFIX):
            name = module.lstrip(_MODULE_PREFIX).split(".")[0]
            if name not in expected_load:
                raise ImportError(f"The package {module} has been imported, but it doesn't contain ModuleInterface")


def _describe_loading(in_config: Set[str], inactive: Set[str]):
    modules = ModuleInterface.__subclasses__()
    for module in modules:
        name = module.name()
        log.debug(f"The {name} module was loaded")
        if name in inactive:
            log.info(f"There is a module that depends on {module.name()}. " +
                     "The module has been loaded despite it's inactive.")
        elif name not in in_config:
            log.info(f"There is a module that depends on {module.name()}. " +
                     "The module has been loaded despite it's not specified in the configuration file.")

