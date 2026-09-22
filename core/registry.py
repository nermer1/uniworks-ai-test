"""모듈 레지스트리 — config의 enabled_modules에 있는 모듈만 import·mount.

계약한(=켜진) 모듈만 실제로 로드된다. 안 켜진 모듈은 import조차 안 하므로
그 모듈의 무거운 의존성(예: 추천의 torch/qdrant)도 안 딸려온다(à la carte).
"""
import importlib

from core.config import enabled_modules

_MODULE_IMPORTS = {
    "ocr": "modules.ocr",
    "recommend": "modules.recommend",
    "approval": "modules.approval",
}


def mount_modules(app) -> list[str]:
    mounted = []
    for name in enabled_modules():
        path = _MODULE_IMPORTS.get(name)
        if not path:
            continue
        mod = importlib.import_module(path)
        mod.register(app)     # 각 모듈이 노출하는 register(app)
        mounted.append(name)
    return mounted
