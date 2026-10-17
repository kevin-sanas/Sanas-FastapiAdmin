"""Create AssetFlow P0 tables in the existing FastApiAdmin database.

Only asset_* tables are managed by this revision; upstream system tables
must already exist. No application data or menus are seeded here.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261017_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not op.get_context().as_sql:
        inspector = sa.inspect(op.get_bind())
        tables = set(inspector.get_table_names())
        required = {"sys_user", "sys_tenant", "sys_dept"}
        if not required.issubset(tables):
            raise RuntimeError("Initialize the upstream FastApiAdmin schema before this migration.")
        if any(name.startswith("asset_") for name in tables):
            raise RuntimeError("Asset tables already exist; inspect their schema before migrating.")
    op.create_table(
        "asset_category",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("status", sa.String(length=10), nullable=False, comment="状态(0:正常 1:禁用)"),
        sa.Column("description", sa.Text(), nullable=True, comment="备注/描述"),
        sa.Column("created_time", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(), nullable=False, comment="更新时间"),
        sa.Column(
            "is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"
        ),
        sa.Column("deleted_time", sa.DateTime(), nullable=True, comment="删除时间"),
        sa.Column("tenant_id", sa.Integer(), nullable=False, comment="租户ID"),
        sa.Column("created_id", sa.Integer(), nullable=True, comment="创建人ID"),
        sa.Column("updated_id", sa.Integer(), nullable=True, comment="更新人ID"),
        sa.Column("deleted_id", sa.Integer(), nullable=True, comment="删除人ID"),
        sa.ForeignKeyConstraint(
            ["created_id"], ["sys_user.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["deleted_id"], ["sys_user.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["parent_id"], ["asset_category.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["sys_tenant.id"], onupdate="CASCADE", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["updated_id"], ["sys_user.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_asset_category_tenant_code"),
        comment="资产分类",
    )
    op.create_index(
        op.f("ix_asset_category_created_id"), "asset_category", ["created_id"], unique=False
    )
    op.create_index(
        op.f("ix_asset_category_created_time"), "asset_category", ["created_time"], unique=False
    )
    op.create_index(
        op.f("ix_asset_category_deleted_id"), "asset_category", ["deleted_id"], unique=False
    )
    op.create_index(
        op.f("ix_asset_category_deleted_time"), "asset_category", ["deleted_time"], unique=False
    )
    op.create_index(op.f("ix_asset_category_id"), "asset_category", ["id"], unique=False)
    op.create_index(
        op.f("ix_asset_category_is_deleted"), "asset_category", ["is_deleted"], unique=False
    )
    op.create_index(
        op.f("ix_asset_category_parent_id"), "asset_category", ["parent_id"], unique=False
    )
    op.create_index(op.f("ix_asset_category_status"), "asset_category", ["status"], unique=False)
    op.create_index(
        op.f("ix_asset_category_tenant_id"), "asset_category", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_asset_category_updated_id"), "asset_category", ["updated_id"], unique=False
    )
    op.create_index(
        op.f("ix_asset_category_updated_time"), "asset_category", ["updated_time"], unique=False
    )
    op.create_index(op.f("ix_asset_category_uuid"), "asset_category", ["uuid"], unique=True)
    op.create_table(
        "asset_item",
        sa.Column("asset_code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column(
            "asset_state",
            sa.Enum(
                "AVAILABLE",
                "IN_USE",
                "MAINTENANCE",
                "RETIRED",
                name="ck_asset_item_state",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("custodian_id", sa.Integer(), nullable=True),
        sa.Column("custodian_dept_id", sa.Integer(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("purchase_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("status", sa.String(length=10), nullable=False, comment="状态(0:正常 1:禁用)"),
        sa.Column("description", sa.Text(), nullable=True, comment="备注/描述"),
        sa.Column("created_time", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(), nullable=False, comment="更新时间"),
        sa.Column(
            "is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"
        ),
        sa.Column("deleted_time", sa.DateTime(), nullable=True, comment="删除时间"),
        sa.Column("tenant_id", sa.Integer(), nullable=False, comment="租户ID"),
        sa.Column("created_id", sa.Integer(), nullable=True, comment="创建人ID"),
        sa.Column("updated_id", sa.Integer(), nullable=True, comment="更新人ID"),
        sa.Column("deleted_id", sa.Integer(), nullable=True, comment="删除人ID"),
        sa.CheckConstraint(
            "(asset_state = 'IN_USE' AND custodian_id IS NOT NULL AND custodian_dept_id IS NOT NULL) OR (asset_state <> 'IN_USE' AND custodian_id IS NULL AND custodian_dept_id IS NULL)",
            name="ck_asset_item_custody",
        ),
        sa.CheckConstraint(
            "purchase_amount IS NULL OR purchase_amount >= 0", name="ck_asset_item_amount"
        ),
        sa.CheckConstraint("row_version >= 1", name="ck_asset_item_version"),
        sa.ForeignKeyConstraint(["category_id"], ["asset_category.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["created_id"], ["sys_user.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["custodian_dept_id"], ["sys_dept.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["custodian_id"], ["sys_user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["deleted_id"], ["sys_user.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["sys_tenant.id"], onupdate="CASCADE", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["updated_id"], ["sys_user.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "asset_code", name="uq_asset_item_tenant_code"),
        comment="实物资产档案",
    )
    op.create_index(op.f("ix_asset_item_created_id"), "asset_item", ["created_id"], unique=False)
    op.create_index(
        op.f("ix_asset_item_created_time"), "asset_item", ["created_time"], unique=False
    )
    op.create_index(
        op.f("ix_asset_item_custodian_dept_id"), "asset_item", ["custodian_dept_id"], unique=False
    )
    op.create_index(
        op.f("ix_asset_item_custodian_id"), "asset_item", ["custodian_id"], unique=False
    )
    op.create_index(op.f("ix_asset_item_deleted_id"), "asset_item", ["deleted_id"], unique=False)
    op.create_index(
        op.f("ix_asset_item_deleted_time"), "asset_item", ["deleted_time"], unique=False
    )
    op.create_index(op.f("ix_asset_item_id"), "asset_item", ["id"], unique=False)
    op.create_index(op.f("ix_asset_item_is_deleted"), "asset_item", ["is_deleted"], unique=False)
    op.create_index(op.f("ix_asset_item_status"), "asset_item", ["status"], unique=False)
    op.create_index(
        "ix_asset_item_tenant_category", "asset_item", ["tenant_id", "category_id"], unique=False
    )
    op.create_index(
        "ix_asset_item_tenant_custodian", "asset_item", ["tenant_id", "custodian_id"], unique=False
    )
    op.create_index(op.f("ix_asset_item_tenant_id"), "asset_item", ["tenant_id"], unique=False)
    op.create_index(
        "ix_asset_item_tenant_state",
        "asset_item",
        ["tenant_id", "asset_state", "is_deleted"],
        unique=False,
    )
    op.create_index(op.f("ix_asset_item_updated_id"), "asset_item", ["updated_id"], unique=False)
    op.create_index(
        op.f("ix_asset_item_updated_time"), "asset_item", ["updated_time"], unique=False
    )
    op.create_index(op.f("ix_asset_item_uuid"), "asset_item", ["uuid"], unique=True)
    op.create_table(
        "asset_application",
        sa.Column("request_no", sa.String(length=64), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("applicant_id", sa.Integer(), nullable=False),
        sa.Column(
            "application_type",
            sa.Enum(
                "ISSUE",
                "RETURN",
                "REPAIR",
                name="ck_asset_application_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "application_state",
            sa.Enum(
                "PENDING",
                "APPROVED",
                "REJECTED",
                "CANCELLED",
                "COMPLETED",
                name="ck_asset_application_state",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "idempotency_key",
            sa.String(length=128).with_variant(
                mysql.VARCHAR(charset="utf8mb4", collation="utf8mb4_bin", length=128), "mysql"
            ),
            nullable=False,
        ),
        sa.Column("asset_version_at_submit", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("completion_note", sa.Text(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("status", sa.String(length=10), nullable=False, comment="状态(0:正常 1:禁用)"),
        sa.Column("description", sa.Text(), nullable=True, comment="备注/描述"),
        sa.Column("created_time", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(), nullable=False, comment="更新时间"),
        sa.Column(
            "is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"
        ),
        sa.Column("deleted_time", sa.DateTime(), nullable=True, comment="删除时间"),
        sa.Column("tenant_id", sa.Integer(), nullable=False, comment="租户ID"),
        sa.Column("created_id", sa.Integer(), nullable=True, comment="创建人ID"),
        sa.Column("updated_id", sa.Integer(), nullable=True, comment="更新人ID"),
        sa.Column("deleted_id", sa.Integer(), nullable=True, comment="删除人ID"),
        sa.CheckConstraint(
            "(application_state = 'COMPLETED' AND application_type = 'REPAIR' AND completed_at IS NOT NULL AND completion_note IS NOT NULL) OR (application_state <> 'COMPLETED' AND completed_at IS NULL AND completion_note IS NULL)",
            name="ck_asset_application_completion",
        ),
        sa.CheckConstraint("asset_version_at_submit >= 1", name="ck_asset_application_version"),
        sa.ForeignKeyConstraint(["applicant_id"], ["sys_user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["asset_id"], ["asset_item.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["created_id"], ["sys_user.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["deleted_id"], ["sys_user.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["sys_tenant.id"], onupdate="CASCADE", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["updated_id"], ["sys_user.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "applicant_id", "idempotency_key", name="uq_asset_application_request_key"
        ),
        sa.UniqueConstraint("tenant_id", "request_no", name="uq_asset_application_request_no"),
        comment="资产领用归还维修申请",
    )
    op.create_index(
        op.f("ix_asset_application_applicant_id"),
        "asset_application",
        ["applicant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_asset_application_created_id"), "asset_application", ["created_id"], unique=False
    )
    op.create_index(
        op.f("ix_asset_application_created_time"),
        "asset_application",
        ["created_time"],
        unique=False,
    )
    op.create_index(
        op.f("ix_asset_application_deleted_id"), "asset_application", ["deleted_id"], unique=False
    )
    op.create_index(
        op.f("ix_asset_application_deleted_time"),
        "asset_application",
        ["deleted_time"],
        unique=False,
    )
    op.create_index(op.f("ix_asset_application_id"), "asset_application", ["id"], unique=False)
    op.create_index(
        op.f("ix_asset_application_is_deleted"), "asset_application", ["is_deleted"], unique=False
    )
    op.create_index(
        op.f("ix_asset_application_status"), "asset_application", ["status"], unique=False
    )
    op.create_index(
        "ix_asset_application_tenant_asset",
        "asset_application",
        ["tenant_id", "asset_id", "application_state"],
        unique=False,
    )
    op.create_index(
        op.f("ix_asset_application_tenant_id"), "asset_application", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_asset_application_tenant_state",
        "asset_application",
        ["tenant_id", "application_state", "created_time"],
        unique=False,
    )
    op.create_index(
        "ix_asset_application_tenant_user",
        "asset_application",
        ["tenant_id", "applicant_id", "created_time"],
        unique=False,
    )
    op.create_index(
        op.f("ix_asset_application_updated_id"), "asset_application", ["updated_id"], unique=False
    )
    op.create_index(
        op.f("ix_asset_application_updated_time"),
        "asset_application",
        ["updated_time"],
        unique=False,
    )
    op.create_index(op.f("ix_asset_application_uuid"), "asset_application", ["uuid"], unique=True)
    op.create_table(
        "asset_approval",
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("reviewer_id", sa.Integer(), nullable=False),
        sa.Column(
            "decision",
            sa.Enum(
                "APPROVE",
                "REJECT",
                name="ck_asset_approval_decision",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=False),
        sa.Column(
            "idempotency_key",
            sa.String(length=128).with_variant(
                mysql.VARCHAR(charset="utf8mb4", collation="utf8mb4_bin", length=128), "mysql"
            ),
            nullable=True,
        ),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("status", sa.String(length=10), nullable=False, comment="状态(0:正常 1:禁用)"),
        sa.Column("description", sa.Text(), nullable=True, comment="备注/描述"),
        sa.Column("created_time", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(), nullable=False, comment="更新时间"),
        sa.Column(
            "is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"
        ),
        sa.Column("deleted_time", sa.DateTime(), nullable=True, comment="删除时间"),
        sa.Column("tenant_id", sa.Integer(), nullable=False, comment="租户ID"),
        sa.CheckConstraint(
            "decision <> 'REJECT' OR (review_note IS NOT NULL AND length(trim(review_note)) > 0)",
            name="ck_asset_approval_reject_note",
        ),
        sa.ForeignKeyConstraint(["application_id"], ["asset_application.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["sys_user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["sys_tenant.id"], onupdate="CASCADE", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "application_id", name="uq_asset_approval_application"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_asset_approval_request_key"),
        comment="资产单步审批记录",
    )
    op.create_index(
        op.f("ix_asset_approval_created_time"), "asset_approval", ["created_time"], unique=False
    )
    op.create_index(
        op.f("ix_asset_approval_deleted_time"), "asset_approval", ["deleted_time"], unique=False
    )
    op.create_index(op.f("ix_asset_approval_id"), "asset_approval", ["id"], unique=False)
    op.create_index(
        op.f("ix_asset_approval_is_deleted"), "asset_approval", ["is_deleted"], unique=False
    )
    op.create_index(
        op.f("ix_asset_approval_reviewer_id"), "asset_approval", ["reviewer_id"], unique=False
    )
    op.create_index(op.f("ix_asset_approval_status"), "asset_approval", ["status"], unique=False)
    op.create_index(
        op.f("ix_asset_approval_tenant_id"), "asset_approval", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_asset_approval_updated_time"), "asset_approval", ["updated_time"], unique=False
    )
    op.create_index(op.f("ix_asset_approval_uuid"), "asset_approval", ["uuid"], unique=True)
    op.create_table(
        "asset_audit_log",
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("status", sa.String(length=10), nullable=False, comment="状态(0:正常 1:禁用)"),
        sa.Column("description", sa.Text(), nullable=True, comment="备注/描述"),
        sa.Column("created_time", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(), nullable=False, comment="更新时间"),
        sa.Column(
            "is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"
        ),
        sa.Column("deleted_time", sa.DateTime(), nullable=True, comment="删除时间"),
        sa.Column("tenant_id", sa.Integer(), nullable=False, comment="租户ID"),
        sa.ForeignKeyConstraint(["actor_id"], ["sys_user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["application_id"], ["asset_application.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["asset_id"], ["asset_item.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["sys_tenant.id"], onupdate="CASCADE", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="资产业务审计记录",
    )
    op.create_index(
        op.f("ix_asset_audit_log_created_time"), "asset_audit_log", ["created_time"], unique=False
    )
    op.create_index(
        op.f("ix_asset_audit_log_deleted_time"), "asset_audit_log", ["deleted_time"], unique=False
    )
    op.create_index(op.f("ix_asset_audit_log_id"), "asset_audit_log", ["id"], unique=False)
    op.create_index(
        op.f("ix_asset_audit_log_is_deleted"), "asset_audit_log", ["is_deleted"], unique=False
    )
    op.create_index(op.f("ix_asset_audit_log_status"), "asset_audit_log", ["status"], unique=False)
    op.create_index(
        op.f("ix_asset_audit_log_tenant_id"), "asset_audit_log", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_asset_audit_log_updated_time"), "asset_audit_log", ["updated_time"], unique=False
    )
    op.create_index(op.f("ix_asset_audit_log_uuid"), "asset_audit_log", ["uuid"], unique=True)
    op.create_index(
        "ix_asset_audit_tenant_application",
        "asset_audit_log",
        ["tenant_id", "application_id"],
        unique=False,
    )
    op.create_index(
        "ix_asset_audit_tenant_asset_time",
        "asset_audit_log",
        ["tenant_id", "asset_id", "created_time"],
        unique=False,
    )


def downgrade() -> None:
    tables = (
        "asset_audit_log",
        "asset_approval",
        "asset_application",
        "asset_item",
        "asset_category",
    )
    if not op.get_context().as_sql:
        # MySQL DDL is not transactional: reject data loss before the first DROP.
        connection = op.get_bind()
        for name in tables:
            query = sa.select(sa.literal(1)).select_from(sa.table(name)).limit(1)
            if connection.execute(query).first() is not None:
                raise RuntimeError("AssetFlow tables contain data; export it before downgrading.")
    # DROP TABLE removes indexes too; dropping FK indexes first is invalid on MySQL.
    for name in tables:
        op.drop_table(name)
