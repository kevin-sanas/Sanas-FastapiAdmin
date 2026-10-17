from enum import Enum


class AssetState(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    IN_USE = "IN_USE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class ApplicationType(str, Enum):
    ISSUE = "ISSUE"
    RETURN = "RETURN"
    REPAIR = "REPAIR"


class ApplicationState(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class ApprovalDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class LoanState(str, Enum):
    PENDING_HANDOVER = "PENDING_HANDOVER"
    PENDING_RECEIPT = "PENDING_RECEIPT"
    IN_USE = "IN_USE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
