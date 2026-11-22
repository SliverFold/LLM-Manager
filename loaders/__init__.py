"""Loader registry — the hardware/loader-agnostic core of the manager.

Each loader module implements the Loader interface (see base.py):
  detect()        -> is it installed on this machine? version?
  list_models()   -> what models can it run?
  build_service() -> params -> services.json entry + start/stop scripts
  param_schema    -> what the Start dialog / Add Service wizard renders

Adding a new loader = one new module here + register it in __init__.py.
"""
from .base import Loader, load_platform_config
from .vllm import VllmLoader
from .ollama import OllamaLoader
from .llama_cpp import LlamaCppLoader
from .lmstudio import LMStudioLoader

_REGISTRY = {
    VllmLoader.key: VllmLoader,
    OllamaLoader.key: OllamaLoader,
    LlamaCppLoader.key: LlamaCppLoader,
    LMStudioLoader.key: LMStudioLoader,
}


def all_loaders():
    """One instance of every registered loader."""
    return [cls() for cls in _REGISTRY.values()]


def get_loader(key):
    """Loader instance by key, or None."""
    cls = _REGISTRY.get(key)
    return cls() if cls else None
