from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import VARCHAR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin, TenantMixin, UserMixin

from .enums import ApplicationState, ApplicationType, ApprovalDecision, AssetState, LoanState


class AssetCategoryModel(ModelMixin, TenantMixin, UserMixin):
    """逐件资产的分类；分类编码在租户内不可重复。"""

    __tablename__ = "asset_category"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_asset_category_tenant_code"),
        {"comment": "资产分类", "info": {"migration_managed": True}},
    )

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset_category.id", ondelete="RESTRICT"), index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AssetItemModel(ModelMixin, TenantMixin, UserMixin):
    """一件实物一条记录；业务状态独立于框架的 status 字段。"""

    __tablename__ = "asset_item"
    __table_args__ = (
        UniqueConstraint("tenant_id", "asset_code", name="uq_asset_item_tenant_code"),
        CheckConstraint("row_version >= 1", name="ck_asset_item_version"),
        CheckConstraint(
            "purchase_amount IS NULL OR purchase_amount >= 0", name="ck_asset_item_amount"
        ),
        CheckConstraint(
            "(asset_state = 'IN_USE' AND custodian_id IS NOT NULL "
            "AND custodian_dept_id IS NOT NULL) OR "
            "(asset_state <> 'IN_USE' AND custodian_id IS NULL AND custodian_dept_id IS NULL)",
            name="ck_asset_item_custody",
        ),
        Index("ix_asset_item_tenant_state", "tenant_id", "asset_state", "is_deleted"),
        Index("ix_asset_item_tenant_category", "tenant_id", "category_id"),
        Index("ix_asset_item_tenant_custodian", "tenant_id", "custodian_id"),
        {"comment": "实物资产档案", "info": {"migration_managed": True}},
    )

    asset_code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("asset_category.id", ondelete="RESTRICT"), nullable=False
    )
    asset_state: Mapped[AssetState] = mapped_column(
        Enum(
            AssetState,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="ck_asset_item_state",
        ),
        default=AssetState.AVAILABLE,
        nullable=False,
    )
    custodian_id: Mapped[int | None] = mapped_column(
        ForeignKey("sys_user.id", ondelete="RESTRICT"), index=True
    )
    custodian_dept_id: Mapped[int | None] = mapped_column(
        ForeignKey("sys_dept.id", ondelete="RESTRICT"), index=True
    )
    row_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    purchase_date: Mapped[date | None] = mapped_column(Date)
    purchase_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))


class AssetApplicationModel(ModelMixin, TenantMixin, UserMixin):
    """单件资产申请，提交申请不改变资产状态。"""

    __tablename__ = "asset_application"
    __table_args__ = (
        UniqueConstraint("tenant_id", "request_no", name="uq_asset_application_request_no"),
        UniqueConstraint(
            "tenant_id", "applicant_id", "idempotency_key", name="uq_asset_application_request_key"
        ),
        CheckConstraint("asset_version_at_submit >= 1", name="ck_asset_application_version"),
        CheckConstraint(
            "(application_state = 'COMPLETED' AND application_type = 'REPAIR' "
            "AND completed_at IS NOT NULL AND completion_note IS NOT NULL) OR "
            "(application_state <> 'COMPLETED' AND completed_at IS NULL AND completion_note IS NULL)",
            name="ck_asset_application_completion",
        ),
        Index(
            "ix_asset_application_tenant_state", "tenant_id", "application_state", "created_time"
        ),
        Index("ix_asset_application_tenant_user", "tenant_id", "applicant_id", "created_time"),
        Index("ix_asset_application_tenant_asset", "tenant_id", "asset_id", "application_state"),
        {"comment": "资产领用归还维修申请", "info": {"migration_managed": True}},
    )

    request_no: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset_item.id", ondelete="RESTRICT"), nullable=False
    )
    applicant_id: Mapped[int] = mapped_column(
        ForeignKey("sys_user.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    application_type: Mapped[ApplicationType] = mapped_column(
        Enum(
            ApplicationType,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="ck_asset_application_type",
        ),
        nullable=False,
    )
    application_state: Mapped[ApplicationState] = mapped_column(
        Enum(
            ApplicationState,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="ck_asset_application_state",
        ),
        default=ApplicationState.PENDING,
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    # MySQL 默认排序规则可能忽略大小写；请求键按不透明字符串精确匹配。
    idempotency_key: Mapped[str] = mapped_column(
        String(128).with_variant(VARCHAR(128, charset="utf8mb4", collation="utf8mb4_bin"), "mysql"),
        nullable=False,
    )
    asset_version_at_submit: Mapped[int] = mapped_column(Integer, nullable=False)
    loan_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset_loan.id", ondelete="RESTRICT"), index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    completion_note: Mapped[str | None] = mapped_column(Text)


class AssetLoanModel(ModelMixin, TenantMixin, UserMixin):
    """一笔批准领用对应一条可追踪的交付、签收和归还记录。"""

    __tablename__ = "asset_loan"
    __table_args__ = (
        UniqueConstraint("tenant_id", "issue_application_id", name="uq_asset_loan_issue"),
        Index("ix_asset_loan_tenant_asset_state", "tenant_id", "asset_id", "loan_state"),
        Index("ix_asset_loan_tenant_borrower", "tenant_id", "borrower_id", "loan_state"),
        {"comment": "资产领用闭环记录", "info": {"migration_managed": True}},
    )

    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset_item.id", ondelete="RESTRICT"), nullable=False
    )
    issue_application_id: Mapped[int] = mapped_column(
        ForeignKey("asset_application.id", ondelete="RESTRICT"), nullable=False
    )
    borrower_id: Mapped[int] = mapped_column(
        ForeignKey("sys_user.id", ondelete="RESTRICT"), nullable=False
    )
    loan_state: Mapped[LoanState] = mapped_column(
        Enum(
            LoanState,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="ck_asset_loan_state",
        ),
        nullable=False,
    )
    approved_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    handed_at: Mapped[datetime | None] = mapped_column(DateTime)
    handover_actor_id: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id"))
    handover_note: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime | None] = mapped_column(DateTime)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime)
    return_actor_id: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id"))
    return_note: Mapped[str | None] = mapped_column(Text)
    close_reason: Mapped[str | None] = mapped_column(String(20))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    is_legacy: Mapped[bool] = mapped_column(default=False, nullable=False)


class AssetApprovalModel(ModelMixin, TenantMixin):
    """一份申请最多一项不可覆盖的终局审批决定。"""

    __tablename__ = "asset_approval"
    __table_args__ = (
        UniqueConstraint("tenant_id", "application_id", name="uq_asset_approval_application"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_asset_approval_request_key"),
        CheckConstraint(
            "decision <> 'REJECT' OR (review_note IS NOT NULL AND length(trim(review_note)) > 0)",
            name="ck_asset_approval_reject_note",
        ),
        {"comment": "资产单步审批记录", "info": {"migration_managed": True}},
    )

    application_id: Mapped[int] = mapped_column(
        ForeignKey("asset_application.id", ondelete="RESTRICT"), nullable=False
    )
    reviewer_id: Mapped[int] = mapped_column(
        ForeignKey("sys_user.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    decision: Mapped[ApprovalDecision] = mapped_column(
        Enum(
            ApprovalDecision,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="ck_asset_approval_decision",
        ),
        nullable=False,
    )
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128).with_variant(VARCHAR(128, charset="utf8mb4", collation="utf8mb4_bin"), "mysql")
    )


class AssetAuditLogModel(ModelMixin, TenantMixin):
    """业务变更快照；由业务服务追加写入，不提供编辑删除接口。"""

    __tablename__ = "asset_audit_log"
    __table_args__ = (
        Index("ix_asset_audit_tenant_asset_time", "tenant_id", "asset_id", "created_time"),
        Index("ix_asset_audit_tenant_application", "tenant_id", "application_id"),
        {"comment": "资产业务审计记录", "info": {"migration_managed": True}},
    )

    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset_item.id", ondelete="RESTRICT"), nullable=False
    )
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset_application.id", ondelete="RESTRICT")
    )
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id", ondelete="RESTRICT"))
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    before_json: Mapped[dict | None] = mapped_column(JSON)
    after_json: Mapped[dict | None] = mapped_column(JSON)
