"""Load modules that are specified in the configuration file"""
import importlib
import inspect
import logging
from enum import Enum
from typing import List, Protocol, runtime_checkable

from dataall.core.config import config

log = logging.getLogger(__name__)

_MODULE_PREFIX = "dataall.modules"
_IMPORTED = []


class ImportMode(Enum):
    """Defines importing mode

    Since there are different infrastructure components that requires only part
    of functionality to be loaded, there should be different loading modes

    Keys represent loading mode while value a suffix im module loading.
    For example, API will try to load a graphql functionality under a module directory
    The values represent a submodule and should exist
    """

    API = "api"
    CDK = "cdk"
    TASKS = "tasks"


@runtime_checkable
class ModuleInterface(Protocol):
    """
    An interface of the module. The implementation should be part of __init__.py of the module
    Contains an API that will be called from core part
    """

    def initialize(self, modes: List[ImportMode]):
        # Initialize the module
        ...

    def has_allocated_resources(self, session, environment_uri):
        # Check if the module has allocated resources
        ...


class _CompositeModuleInterface:
    """
    An implementation of ModuleInterface that combines all imported interfaces
    Needed just not to expose the imported modules
    """

    def initialize(self, modes: List[ImportMode]):
        for module in _IMPORTED:
            module.initialize(modes)

    def has_allocated_resources(self, session, environment_uri):
        """
        Check if the imported modules has allocated resources
        """
        for module in _IMPORTED:
            if module.has_allocated_resources(session, environment_uri):
                return True
        return False


all_modules = _CompositeModuleInterface()


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
    for name, props in modules.items():
        active = props["active"]

        if not active:
            raise ValueError(f"Status is not defined for {name} module")

        if active.lower() != "true":
            log.info(f"Module {name} is not active. Skipping...")
            continue

        if active.lower() == "true" and not _import_module(name):
            raise ValueError(f"Couldn't find module {name} under modules directory")

        log.info(f"Module {name} is loaded")

    log.info("Initiating all modules")
    all_modules.initialize(modes)

    log.info("All modules have been imported and initiated")


def _import_module(name):
    try:
        module = importlib.import_module(f"{_MODULE_PREFIX}.{name}")
        _inspect_module_interface(module)

        return True
    except ModuleNotFoundError:
        return False


def _inspect_module_interface(module):
    classes = inspect.getmembers(module, inspect.isclass)
    for class_name, _class in classes:
        if issubclass(_class, ModuleInterface):
            _IMPORTED.append(_class())
            return

    raise ImportError(f"No class implementing ModuleInterface in {module}")
