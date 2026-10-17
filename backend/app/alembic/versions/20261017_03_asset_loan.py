"""Track handover, receipt and return for each approved asset issue."""

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "20261017_03"
down_revision = "20261017_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_asset_item_state", "asset_item", type_="check")
    op.create_check_constraint(
        "ck_asset_item_state",
        "asset_item",
        "asset_state IN ('AVAILABLE', 'RESERVED', 'IN_USE', 'MAINTENANCE', 'RETIRED')",
    )
    op.create_table(
        "asset_loan",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uuid", sa.String(64), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_time", sa.DateTime(), nullable=False),
        sa.Column("updated_time", sa.DateTime(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_time", sa.DateTime()),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("sys_tenant.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_id", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL")),
        sa.Column("updated_id", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL")),
        sa.Column("deleted_id", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL")),
        sa.Column(
            "asset_id",
            sa.Integer(),
            sa.ForeignKey("asset_item.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "issue_application_id",
            sa.Integer(),
            sa.ForeignKey("asset_application.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "borrower_id",
            sa.Integer(),
            sa.ForeignKey("sys_user.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("loan_state", sa.String(24), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=False),
        sa.Column("handed_at", sa.DateTime()),
        sa.Column("handover_actor_id", sa.Integer(), sa.ForeignKey("sys_user.id")),
        sa.Column("handover_note", sa.Text()),
        sa.Column("received_at", sa.DateTime()),
        sa.Column("returned_at", sa.DateTime()),
        sa.Column("return_actor_id", sa.Integer(), sa.ForeignKey("sys_user.id")),
        sa.Column("return_note", sa.Text()),
        sa.Column("close_reason", sa.String(20)),
        sa.Column("cancel_reason", sa.Text()),
        sa.Column("is_legacy", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "loan_state IN ('PENDING_HANDOVER', 'PENDING_RECEIPT', 'IN_USE', 'COMPLETED', 'CANCELLED')",
            name="ck_asset_loan_state",
        ),
        sa.UniqueConstraint("tenant_id", "issue_application_id", name="uq_asset_loan_issue"),
        sa.UniqueConstraint("uuid", name="uq_asset_loan_uuid"),
        comment="资产领用闭环记录",
    )
    op.create_index(
        "ix_asset_loan_tenant_asset_state", "asset_loan", ["tenant_id", "asset_id", "loan_state"]
    )
    op.create_index(
        "ix_asset_loan_tenant_borrower", "asset_loan", ["tenant_id", "borrower_id", "loan_state"]
    )
    for column in (
        "created_id",
        "created_time",
        "deleted_id",
        "deleted_time",
        "id",
        "is_deleted",
        "status",
        "tenant_id",
        "updated_id",
        "updated_time",
        "uuid",
    ):
        op.create_index(f"ix_asset_loan_{column}", "asset_loan", [column], unique=column == "uuid")
    op.add_column("asset_application", sa.Column("loan_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_asset_application_loan",
        "asset_application",
        "asset_loan",
        ["loan_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_asset_application_loan_id", "asset_application", ["loan_id"])

    # Historical approvals predate physical handover tracking. Retain them as
    # explicitly marked legacy records; never invent handover or signature times.
    db = op.get_bind()
    applications = (
        db
        .execute(
            sa.text("""
        SELECT a.id, a.tenant_id, a.asset_id, a.applicant_id, a.application_type,
               a.asset_version_at_submit,
               a.created_time, a.updated_time, p.reviewed_at,
               i.asset_state, i.custodian_id
        FROM asset_application a
        JOIN asset_item i ON i.id = a.asset_id AND i.tenant_id = a.tenant_id
        LEFT JOIN asset_approval p ON p.application_id = a.id AND p.tenant_id = a.tenant_id
        WHERE a.application_state = 'APPROVED' AND a.application_type IN ('ISSUE', 'RETURN')
        ORDER BY a.tenant_id, a.asset_id, a.id
    """)
        )
        .mappings()
        .all()
    )
    issues = [row for row in applications if row["application_type"] == "ISSUE"]
    returns = [row for row in applications if row["application_type"] == "RETURN"]
    paired = {}
    for return_app in returns:
        candidates = [
            issue
            for issue in issues
            if issue["tenant_id"] == return_app["tenant_id"]
            and issue["asset_id"] == return_app["asset_id"]
            and issue["applicant_id"] == return_app["applicant_id"]
            and issue["id"] < return_app["id"]
            and issue["asset_version_at_submit"] + 1 == return_app["asset_version_at_submit"]
            and issue["id"] not in paired
        ]
        if len(candidates) == 1:
            paired[candidates[0]["id"]] = return_app
    latest_issue = {}
    for issue in issues:
        latest_issue[(issue["tenant_id"], issue["asset_id"])] = issue["id"]
    now = datetime.now()
    for issue in issues:
        return_app = paired.get(issue["id"])
        active = (
            not return_app
            and latest_issue[(issue["tenant_id"], issue["asset_id"])] == issue["id"]
            and issue["asset_state"] == "IN_USE"
            and issue["custodian_id"] == issue["applicant_id"]
        )
        loan_uuid = str(uuid4())
        db.execute(
            sa.text("""
            INSERT INTO asset_loan
            (uuid, status, created_time, updated_time, is_deleted, tenant_id, created_id,
             asset_id, issue_application_id, borrower_id, loan_state, approved_at,
             returned_at, close_reason, is_legacy)
            VALUES (:uuid, '0', :created_time, :updated_time, false, :tenant_id, :created_id,
                    :asset_id, :issue_id, :borrower_id, :loan_state, :approved_at,
                    :returned_at, :close_reason, true)
        """),
            {
                "uuid": loan_uuid,
                "created_time": issue["created_time"],
                "updated_time": now,
                "tenant_id": issue["tenant_id"],
                "created_id": issue["applicant_id"],
                "asset_id": issue["asset_id"],
                "issue_id": issue["id"],
                "borrower_id": issue["applicant_id"],
                "loan_state": "IN_USE" if active else "COMPLETED",
                "approved_at": issue["reviewed_at"] or issue["updated_time"],
                "returned_at": return_app["reviewed_at"] if return_app else None,
                "close_reason": None if active else ("RETURN" if return_app else "LEGACY_UNKNOWN"),
            },
        )
        loan_id = db.scalar(
            sa.text("SELECT id FROM asset_loan WHERE uuid=:uuid"), {"uuid": loan_uuid}
        )
        db.execute(
            sa.text("UPDATE asset_application SET loan_id=:loan_id WHERE id=:id"),
            {"loan_id": loan_id, "id": issue["id"]},
        )
        if return_app:
            db.execute(
                sa.text("UPDATE asset_application SET loan_id=:loan_id WHERE id=:id"),
                {"loan_id": loan_id, "id": return_app["id"]},
            )


def downgrade() -> None:
    db = op.get_bind()
    if db.scalar(sa.text("SELECT COUNT(*) FROM asset_loan")):
        raise RuntimeError("领用记录已存在；为保留业务历史，禁止回退此迁移。")
    if db.scalar(sa.text("SELECT COUNT(*) FROM asset_item WHERE asset_state='RESERVED'")):
        raise RuntimeError("待交付资产仍存在；禁止回退此迁移。")
    op.drop_constraint("fk_asset_application_loan", "asset_application", type_="foreignkey")
    op.drop_index("ix_asset_application_loan_id", table_name="asset_application")
    op.drop_column("asset_application", "loan_id")
    op.drop_index("ix_asset_loan_tenant_borrower", table_name="asset_loan")
    op.drop_index("ix_asset_loan_tenant_asset_state", table_name="asset_loan")
    op.drop_table("asset_loan")
    op.drop_constraint("ck_asset_item_state", "asset_item", type_="check")
    op.create_check_constraint(
        "ck_asset_item_state",
        "asset_item",
        "asset_state IN ('AVAILABLE', 'IN_USE', 'MAINTENANCE', 'RETIRED')",
    )
