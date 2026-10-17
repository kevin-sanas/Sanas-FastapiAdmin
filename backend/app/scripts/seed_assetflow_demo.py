"""Populate the existing development database with a repeatable AssetFlow story.

Run from backend/: python -m app.scripts.seed_assetflow_demo --apply
"""

import argparse
import asyncio
import os
from datetime import date
from decimal import Decimal

DEMO_CATEGORIES = (
    ("DEMO-NOTEBOOK", "【演示】笔记本电脑"),
    ("DEMO-DISPLAY", "【演示】显示设备"),
    ("DEMO-NETWORK", "【演示】网络设备"),
    ("DEMO-PERIPHERAL", "【演示】办公外设"),
)

DEMO_ITEMS = (
    ("DEMO-2026-001", "【演示】联想 ThinkPad X1 Carbon", "DEMO-NOTEBOOK", "2026-03-12", "8999.00"),
    ("DEMO-2026-002", "【演示】MacBook Pro 14", "DEMO-NOTEBOOK", "2025-11-05", "14999.00"),
    ("DEMO-2026-003", "【演示】戴尔 U2723QE 显示器", "DEMO-DISPLAY", "2026-01-18", "3299.00"),
    ("DEMO-2026-004", "【演示】思科办公交换机", "DEMO-NETWORK", "2025-09-22", "4580.00"),
    ("DEMO-2026-005", "【演示】爱普生会议投影仪", "DEMO-DISPLAY", "2025-06-16", "6799.00"),
    ("DEMO-2026-006", "【演示】罗技无线键盘", "DEMO-PERIPHERAL", "2024-05-08", "699.00"),
    ("DEMO-2026-007", "【演示】惠普 EliteBook 840", "DEMO-NOTEBOOK", "2026-04-03", "7899.00"),
    ("DEMO-2026-008", "【演示】罗技 MX Master 鼠标", "DEMO-PERIPHERAL", "2026-02-27", "599.00"),
)

DEMO_APPLICATION_KEYS = (
    "demo-v1-001-issue",
    "demo-v1-002-issue",
    "demo-v1-003-issue",
    "demo-v1-003-return",
    "demo-v1-004-repair",
    "demo-v1-005-repair",
    "demo-v1-007-issue",
    "demo-v1-008-issue",
)

LOAN_EXAMPLE_ITEMS = (
    ("DEMO-2026-009", "【演示】华为 MateBook 14", "DEMO-NOTEBOOK"),
    ("DEMO-2026-010", "【演示】明基会议显示屏", "DEMO-DISPLAY"),
)
LOAN_EXAMPLE_KEYS = ("demo-v2-009-issue", "demo-v2-010-issue")


async def seed(
    tenant_id: int, applicant_name: str, reviewer_name: str, apply: bool, loan_examples: bool
) -> None:
    from sqlalchemy import select

    from app.api.v1.module_system.auth.schema import AuthSchema
    from app.api.v1.module_system.user.model import UserModel
    from app.config.setting import settings
    from app.core.database import async_db_session, async_engine
    from app.plugin.module_asset.enums import ApplicationType, ApprovalDecision
    from app.plugin.module_asset.model import (
        AssetApplicationModel,
        AssetCategoryModel,
        AssetItemModel,
    )
    from app.plugin.module_asset.schema import (
        ApplicationCreate,
        ApprovalInput,
        CategoryCreate,
        ItemCreate,
    )
    from app.plugin.module_asset.service import AssetService

    category_codes = {code for code, _ in DEMO_CATEGORIES}
    item_codes = {item[0] for item in DEMO_ITEMS}
    application_keys = set(DEMO_APPLICATION_KEYS)

    try:
        async with async_db_session() as db:
            async with db.begin():
                users = (
                    await db.scalars(
                        select(UserModel).where(
                            UserModel.username.in_((applicant_name, reviewer_name)),
                            UserModel.tenant_id == tenant_id,
                            UserModel.status == "0",
                            UserModel.is_deleted.is_(False),
                        )
                    )
                ).all()
                by_name = {user.username: user for user in users}
                if set(by_name) != {applicant_name, reviewer_name}:
                    raise ValueError("目标租户缺少启用的申请人或审批人账号")
                applicant = by_name[applicant_name]
                reviewer = by_name[reviewer_name]
                if applicant.id == reviewer.id or not applicant.dept_id:
                    raise ValueError("申请人与审批人必须不同，且申请人必须有部门")
                if not applicant.is_superuser or not reviewer.is_superuser:
                    raise ValueError("此演示脚本要求两个已有账号均为超级管理员")

                existing_categories = set(
                    await db.scalars(
                        select(AssetCategoryModel.code).where(
                            AssetCategoryModel.tenant_id == tenant_id,
                            AssetCategoryModel.code.in_(category_codes),
                        )
                    )
                )
                existing_items = set(
                    await db.scalars(
                        select(AssetItemModel.asset_code).where(
                            AssetItemModel.tenant_id == tenant_id,
                            AssetItemModel.asset_code.in_(item_codes),
                        )
                    )
                )
                existing_applications = set(
                    await db.scalars(
                        select(AssetApplicationModel.idempotency_key).where(
                            AssetApplicationModel.tenant_id == tenant_id,
                            AssetApplicationModel.applicant_id == applicant.id,
                            AssetApplicationModel.idempotency_key.in_(application_keys),
                        )
                    )
                )
                if loan_examples:
                    if existing_categories != category_codes:
                        raise ValueError("请先导入基础演示分类，再导入领用闭环示例")
                    loan_item_codes = {item[0] for item in LOAN_EXAMPLE_ITEMS}
                    loan_items = set(
                        await db.scalars(
                            select(AssetItemModel.asset_code).where(
                                AssetItemModel.tenant_id == tenant_id,
                                AssetItemModel.asset_code.in_(loan_item_codes),
                            )
                        )
                    )
                    loan_keys = set(
                        await db.scalars(
                            select(AssetApplicationModel.idempotency_key).where(
                                AssetApplicationModel.tenant_id == tenant_id,
                                AssetApplicationModel.applicant_id == applicant.id,
                                AssetApplicationModel.idempotency_key.in_(LOAN_EXAMPLE_KEYS),
                            )
                        )
                    )
                    if loan_items == loan_item_codes and loan_keys == set(LOAN_EXAMPLE_KEYS):
                        print("领用闭环演示数据已存在；未修改数据库。")
                        return
                    if loan_items or loan_keys:
                        raise ValueError("领用示例只有部分编码或申请键；为保护现有数据，未补写")
                    print("预览：2 件资产、2 笔领用申请，分别展示待交付和待签收。")
                    if not apply:
                        return
                    category_ids = dict(
                        (
                            await db.execute(
                                select(AssetCategoryModel.code, AssetCategoryModel.id).where(
                                    AssetCategoryModel.tenant_id == tenant_id,
                                    AssetCategoryModel.code.in_(category_codes),
                                )
                            )
                        ).all()
                    )
                    applicant_service = AssetService(AuthSchema(user=applicant, db=db))
                    reviewer_service = AssetService(AuthSchema(user=reviewer, db=db))
                    for code, name, category_code in LOAN_EXAMPLE_ITEMS:
                        item = await reviewer_service.create_item(
                            ItemCreate(
                                asset_code=code, name=name, category_id=category_ids[category_code]
                            )
                        )
                        application = await applicant_service.submit(
                            ApplicationCreate(
                                asset_id=item["id"],
                                application_type=ApplicationType.ISSUE,
                                reason="【演示数据】申请领用设备，展示交付与签收步骤。",
                                idempotency_key=f"demo-v2-{code[-3:]}-issue",
                            )
                        )
                        application = await reviewer_service.decide(
                            application["id"],
                            ApprovalInput(
                                review_note="【演示数据】已核对领用申请。",
                                idempotency_key=f"demo-v2-{code[-3:]}-approve",
                            ),
                            ApprovalDecision.APPROVE,
                        )
                        if code.endswith("010"):
                            await reviewer_service.handover(
                                application["loan_id"],
                                "【演示数据】管理员已交付显示屏，等待员工签收。",
                            )
                    print("领用闭环示例已写入：009 待管理员交付，010 待员工签收。")
                    return
                found = existing_categories | existing_items | existing_applications
                if found:
                    if (
                        existing_categories == category_codes
                        and existing_items == item_codes
                        and existing_applications == application_keys
                    ):
                        print("演示数据已存在；未修改数据库。")
                        return
                    raise ValueError("发现部分演示编码或申请键；为保护现有数据，未补写或覆盖")

                print(
                    f"目标开发库：{settings.DATABASE_NAME}；租户：{tenant_id}；"
                    f"申请人：{applicant_name}；审批人：{reviewer_name}"
                )
                if not apply:
                    print("预览：4 个分类、8 件资产、8 笔申请；加 --apply 后写入。")
                    return

                applicant_service = AssetService(AuthSchema(user=applicant, db=db))
                reviewer_service = AssetService(AuthSchema(user=reviewer, db=db))
                categories = {}
                for sort_order, (code, name) in enumerate(DEMO_CATEGORIES, start=1):
                    row = await reviewer_service.create_category(
                        CategoryCreate(code=code, name=name, sort_order=sort_order * 10)
                    )
                    categories[code] = row["id"]

                items = {}
                for code, name, category_code, bought_on, amount in DEMO_ITEMS:
                    row = await reviewer_service.create_item(
                        ItemCreate(
                            asset_code=code,
                            name=name,
                            category_id=categories[category_code],
                            purchase_date=date.fromisoformat(bought_on),
                            purchase_amount=Decimal(amount),
                        )
                    )
                    items[code] = row

                async def submit(code: str, kind: ApplicationType, suffix: str, reason: str):
                    return await applicant_service.submit(
                        ApplicationCreate(
                            asset_id=items[code]["id"],
                            application_type=kind,
                            reason=f"【演示数据】{reason}",
                            idempotency_key=f"demo-v1-{code[-3:]}-{suffix}",
                        )
                    )

                async def decide(app_id: int, key: str, decision: ApprovalDecision, note: str):
                    return await reviewer_service.decide(
                        app_id,
                        ApprovalInput(review_note=f"【演示数据】{note}", idempotency_key=key),
                        decision,
                    )

                await submit(
                    "DEMO-2026-001",
                    ApplicationType.ISSUE,
                    "issue",
                    "新员工申请办公电脑，等待资产管理员审批。",
                )

                issued = await submit(
                    "DEMO-2026-002", ApplicationType.ISSUE, "issue", "研发工作需要移动开发设备。"
                )
                issued = await decide(
                    issued["id"],
                    "demo-v1-002-approve",
                    ApprovalDecision.APPROVE,
                    "已核对设备并批准领用。",
                )
                await reviewer_service.handover(
                    issued["loan_id"], "【演示数据】管理员当面交付笔记本。"
                )
                await applicant_service.receive(issued["loan_id"])

                issued = await submit(
                    "DEMO-2026-003", ApplicationType.ISSUE, "issue", "工位增加一台外接显示器。"
                )
                issued = await decide(
                    issued["id"],
                    "demo-v1-003-issue-approve",
                    ApprovalDecision.APPROVE,
                    "已交付显示器。",
                )
                await reviewer_service.handover(
                    issued["loan_id"], "【演示数据】管理员交付显示器并核对配件。"
                )
                await applicant_service.receive(issued["loan_id"])
                returned = await submit(
                    "DEMO-2026-003", ApplicationType.RETURN, "return", "更换工位，归还显示器。"
                )
                await decide(
                    returned["id"],
                    "demo-v1-003-return-approve",
                    ApprovalDecision.APPROVE,
                    "设备外观检查正常，已入库。",
                )

                repairing = await submit(
                    "DEMO-2026-004", ApplicationType.REPAIR, "repair", "端口连接不稳定，需要检修。"
                )
                await decide(
                    repairing["id"],
                    "demo-v1-004-approve",
                    ApprovalDecision.APPROVE,
                    "已安排网络设备检修。",
                )

                repaired = await submit(
                    "DEMO-2026-005", ApplicationType.REPAIR, "repair", "投影画面偏色，需要校准。"
                )
                await decide(
                    repaired["id"],
                    "demo-v1-005-approve",
                    ApprovalDecision.APPROVE,
                    "已安排投影仪维修。",
                )
                await reviewer_service.complete_repair(
                    repaired["id"], "【演示数据】已校准画面并验收，恢复在库。"
                )

                await reviewer_service.retire(
                    items["DEMO-2026-006"]["id"], items["DEMO-2026-006"]["row_version"]
                )

                rejected = await submit(
                    "DEMO-2026-007", ApplicationType.ISSUE, "issue", "申请备用笔记本电脑。"
                )
                await decide(
                    rejected["id"],
                    "demo-v1-007-reject",
                    ApprovalDecision.REJECT,
                    "当前设备需优先留作公共备用。",
                )

                cancelled = await submit(
                    "DEMO-2026-008", ApplicationType.ISSUE, "issue", "临时外出办公申请鼠标。"
                )
                await applicant_service.cancel(cancelled["id"])

        print("导入完成：4 个分类、8 件资产、8 笔申请；资产概览和业务审计可直接刷新查看。")
    finally:
        await async_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="向现有开发库导入可公开的资产演示数据")
    parser.add_argument("--tenant-id", type=int, default=1)
    parser.add_argument("--applicant", default="admin")
    parser.add_argument("--reviewer", default="super")
    parser.add_argument("--apply", action="store_true", help="实际写入；省略时只预览")
    parser.add_argument("--loan-examples", action="store_true", help="导入待交付和待签收示例")
    args = parser.parse_args()
    if args.tenant_id < 1 or args.applicant == args.reviewer:
        parser.error("租户编号必须为正数，申请人与审批人必须不同")
    if os.getenv("ENVIRONMENT", "dev") != "dev":
        parser.error("演示数据只允许导入 dev 环境")
    os.environ["ENVIRONMENT"] = "dev"
    asyncio.run(seed(args.tenant_id, args.applicant, args.reviewer, args.apply, args.loan_examples))


if __name__ == "__main__":
    main()
