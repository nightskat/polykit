from enum import Enum
from dataclasses import dataclass, field

class VendorState(str, Enum):
    NOT_INSTALLED = "not_installed"
    INSTALLED_NOT_AUTHED = "installed_not_authed"
    READY = "ready"
    QUOTA_CAPPED = "quota_capped"

@dataclass(frozen=True)
class VendorProbe:
    name: str
    path: str | None
    authed: bool
    quota_capped: bool
    version: str | None = None
    models: list[str] = field(default_factory=list)
    error: str | None = None

def classify(probe: VendorProbe) -> VendorState:
    # Precedence bám máy trạng thái tuyến tính của spec:
    # not_installed → installed_not_authed → ready → quota_capped.
    # Phải authed trước rồi mới có thể quota_capped (cap khi chưa auth là probe vô nghĩa).
    if probe.path is None:
        return VendorState.NOT_INSTALLED
    if not probe.authed:
        return VendorState.INSTALLED_NOT_AUTHED
    if probe.quota_capped:
        return VendorState.QUOTA_CAPPED
    return VendorState.READY
