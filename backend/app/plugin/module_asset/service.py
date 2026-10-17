from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.api.v1.module_system.auth.schema import AuthSchema
from app.api.v1.module_system.user.model import UserModel
from app.core.dependencies import AuthPermission
from app.core.exceptions import CustomException
from app.core.permission import Permission

from .enums import ApplicationState, ApplicationType, ApprovalDecision, AssetState, LoanState
from .model import (
    AssetApplicationModel as Application,
)
from .model import (
    AssetApprovalModel as Approval,
)
from .model import (
    AssetAuditLogModel as Audit,
)
from .model import (
    AssetCategoryModel as Category,
)
from .model import (
    AssetItemModel as Item,
)
from .model import AssetLoanModel as Loan
from .schema import ApplicationCreate, ApprovalInput, CategoryCreate, ItemCreate


def conflict(reason: str, message: str) -> CustomException:
    return CustomException(msg=message, code=40901, status_code=409, data={"reason": reason})


class AssetService:
    """资产命令复用请求事务；内部保存点保证异常被捕获后也不会提交半次操作。"""

    def __init__(self, auth: AuthSchema):
        self.auth = auth
        self.db = auth.db
        if not auth.user:
            raise CustomException(msg="请先登录", code=10401, status_code=401)
        self.user = auth.user
        self.tenant_id = self.user.tenant_id

    async def require(self, *permissions: str):
        await AuthPermission([f"module_asset:{permission}" for permission in permissions])(
            self.auth
        )

    async def scoped_query(self, model, query):
        # 仅将活动角色交给上游的数据范围计算，避免停用角色扩大权限。
        # 该视图不修改请求中缓存的 ORM 用户和角色关联。
        principal = SimpleNamespace(
            id=self.user.id,
            dept_id=self.user.dept_id,
            is_superuser=self.user.is_superuser,
            roles=[role for role in self.user.roles if role.status == "0" and not role.is_deleted],
        )
        scope = SimpleNamespace(user=principal, db=self.db, check_data_scope=True)
        return await Permission(model, scope).filter_query(query)

    async def row(self, model, object_id: int, *, lock=False, scoped=False):
        query = select(model.__table__).where(
            model.id == object_id, model.tenant_id == self.tenant_id, model.is_deleted.is_(False)
        )
        if scoped:
            query = await self.scoped_query(model, query)
        if lock:
            query = query.with_for_update()
        result = (await self.db.execute(query)).mappings().first()
        if result is None:
            raise CustomException(msg="记录不存在或无权访问", code=40401, status_code=404)
        return dict(result)

    def creation(self):
        return {"tenant_id": self.tenant_id, "created_id": self.user.id}

    async def audit(self, asset_id, action, before, after, application_id=None):
        await self.db.execute(
            Audit.__table__.insert().values(
                tenant_id=self.tenant_id,
                asset_id=asset_id,
                application_id=application_id,
                actor_id=self.user.id,
                action=action,
                before_json=before,
                after_json=after,
            )
        )

    @staticmethod
    def snapshot(item):
        return {
            key: item[key]
            for key in ("asset_state", "custodian_id", "custodian_dept_id", "row_version")
        }

    async def create_category(self, data: CategoryCreate):
        await self.require("category:create")
        try:
            async with self.db.begin_nested():
                if data.parent_id:
                    await self.row(Category, data.parent_id)
                result = await self.db.execute(
                    Category.__table__.insert().values(**data.model_dump(), **self.creation())
                )
                return await self.row(Category, result.inserted_primary_key[0])
        except IntegrityError as exc:
            raise conflict("CATEGORY_CODE_EXISTS", "分类编码已存在或关联记录不可用") from exc

    async def create_item(self, data: ItemCreate):
        await self.require("item:create")
        try:
            async with self.db.begin_nested():
                category = await self.row(Category, data.category_id)
                if category["status"] != "0":
                    raise conflict("CATEGORY_DISABLED", "分类已停用")
                result = await self.db.execute(
                    Item.__table__.insert().values(**data.model_dump(), **self.creation())
                )
                item = await self.row(Item, result.inserted_primary_key[0])
                await self.audit(item["id"], "ASSET_CREATED", None, self.snapshot(item))
                return item
        except IntegrityError as exc:
            raise conflict("ASSET_CODE_EXISTS", "资产编码已存在或关联记录不可用") from exc

    async def submit(self, data: ApplicationCreate):
        await self.require("application:create")
        table = Application.__table__
        key_query = select(table).where(
            table.c.tenant_id == self.tenant_id,
            table.c.applicant_id == self.user.id,
            table.c.idempotency_key == data.idempotency_key,
        )

        def replay(existing):
            if any(
                existing[key] != getattr(data, key)
                for key in ("asset_id", "application_type", "reason")
            ):
                raise conflict("IDEMPOTENCY_KEY_REUSED", "请求键已用于其他申请内容")
            return dict(existing)

        existing = (await self.db.execute(key_query)).mappings().first()
        if existing:
            return replay(existing)
        try:
            async with self.db.begin_nested():
                item = await self.row(Item, data.asset_id)
                self.validate_application(item, data.application_type, self.user.id)
                loan_id = None
                if data.application_type == ApplicationType.RETURN:
                    loan = await self.open_loan(item["id"], lock=True)
                    if (
                        loan["loan_state"] != LoanState.IN_USE
                        or loan["borrower_id"] != self.user.id
                    ):
                        raise conflict("LOAN_STATE_CONFLICT", "仅已签收的保管人可申请归还")
                    pending_return = await self.db.scalar(
                        select(Application.id)
                        .where(
                            Application.tenant_id == self.tenant_id,
                            Application.loan_id == loan["id"],
                            Application.application_type == ApplicationType.RETURN,
                            Application.application_state == ApplicationState.PENDING,
                            Application.is_deleted.is_(False),
                        )
                        .with_for_update()
                    )
                    if pending_return:
                        raise conflict("RETURN_ALREADY_PENDING", "已有待审批的归还申请")
                    loan_id = loan["id"]
                result = await self.db.execute(
                    table.insert().values(
                        **data.model_dump(),
                        **self.creation(),
                        applicant_id=self.user.id,
                        request_no=uuid4().hex,
                        asset_version_at_submit=item["row_version"],
                        loan_id=loan_id,
                    )
                )
                app_id = result.inserted_primary_key[0]
                await self.audit(
                    item["id"],
                    "APPLICATION_SUBMITTED",
                    None,
                    {"application_state": "PENDING"},
                    app_id,
                )
                return await self.row(Application, app_id)
        except IntegrityError as exc:
            # 当前读可看到并发提交刚写入的请求，即使事务隔离级别为 REPEATABLE READ。
            existing = (await self.db.execute(key_query.with_for_update())).mappings().first()
            if existing:
                return replay(existing)
            raise conflict("APPLICATION_CONFLICT", "申请写入冲突，请重试") from exc

    @staticmethod
    def validate_application(item, kind, applicant_id):
        if item["status"] != "0":
            raise conflict("ASSET_DISABLED", "资产已停用")
        allowed = {
            ApplicationType.ISSUE: {AssetState.AVAILABLE},
            ApplicationType.RETURN: {AssetState.IN_USE},
            ApplicationType.REPAIR: {AssetState.AVAILABLE, AssetState.IN_USE},
        }
        if item["asset_state"] not in allowed[kind]:
            raise conflict("ASSET_STATE_CONFLICT", "资产当前状态不支持该申请")
        if item["asset_state"] == AssetState.IN_USE and item["custodian_id"] != applicant_id:
            raise CustomException(msg="只有当前保管人可申请归还或维修", code=10403, status_code=403)

    async def open_loan(self, asset_id: int, *, lock=False):
        query = select(Loan.__table__).where(
            Loan.tenant_id == self.tenant_id,
            Loan.asset_id == asset_id,
            Loan.loan_state.in_((
                LoanState.PENDING_HANDOVER,
                LoanState.PENDING_RECEIPT,
                LoanState.IN_USE,
            )),
            Loan.is_deleted.is_(False),
        )
        if lock:
            query = query.with_for_update()
        rows = (await self.db.execute(query)).mappings().all()
        if len(rows) != 1:
            raise conflict("LOAN_STATE_CONFLICT", "未找到唯一的有效领用记录，请联系资产管理员")
        return dict(rows[0])

    async def change_asset(self, item, state, custodian_id=None, dept_id=None):
        result = await self.db.execute(
            update(Item.__table__)
            .where(
                Item.id == item["id"],
                Item.tenant_id == self.tenant_id,
                Item.is_deleted.is_(False),
                Item.row_version == item["row_version"],
                Item.asset_state == item["asset_state"],
            )
            .values(
                asset_state=state,
                custodian_id=custodian_id,
                custodian_dept_id=dept_id,
                row_version=Item.row_version + 1,
                updated_id=self.user.id,
            )
        )
        if result.rowcount != 1:
            raise conflict("ASSET_STATE_CONFLICT", "资产已被其他操作改变，请刷新后重试")
        return await self.row(Item, item["id"])

    async def decide(self, app_id: int, data: ApprovalInput, decision: ApprovalDecision):
        await self.require(
            "application:approve" if decision == ApprovalDecision.APPROVE else "application:reject"
        )
        if decision == ApprovalDecision.REJECT and not data.review_note:
            raise CustomException(msg="驳回原因不能为空", code=42201, status_code=422)
        try:
            async with self.db.begin_nested():
                app = await self.row(Application, app_id, lock=True, scoped=True)
                if app["applicant_id"] == self.user.id:
                    raise CustomException(msg="不能审批自己的申请", code=10403, status_code=403)
                if app["application_state"] != ApplicationState.PENDING:
                    existing = (
                        (
                            await self.db.execute(
                                select(Approval.__table__)
                                .where(
                                    Approval.application_id == app_id,
                                    Approval.tenant_id == self.tenant_id,
                                )
                                .with_for_update()
                            )
                        )
                        .mappings()
                        .first()
                    )
                    if (
                        existing
                        and data.idempotency_key
                        and existing["idempotency_key"] == data.idempotency_key
                        and existing["reviewer_id"] == self.user.id
                        and existing["decision"] == decision
                        and existing["review_note"] == data.review_note
                    ):
                        return app
                    raise conflict("APPLICATION_ALREADY_PROCESSED", "申请已处理")
                before = {"application_state": app["application_state"]}
                after = {"application_state": "REJECTED"}
                if decision == ApprovalDecision.APPROVE:
                    item = await self.row(Item, app["asset_id"], lock=True)
                    self.validate_application(item, app["application_type"], app["applicant_id"])
                    if item["row_version"] != app["asset_version_at_submit"]:
                        raise conflict(
                            "ASSET_STATE_CONFLICT", "申请提交后资产已发生变更，请重新申请"
                        )
                    custodian_id = dept_id = None
                    state = AssetState.AVAILABLE
                    loan = None
                    if app["application_type"] == ApplicationType.ISSUE:
                        applicant = (
                            (
                                await self.db.execute(
                                    select(UserModel.__table__).where(
                                        UserModel.id == app["applicant_id"],
                                        UserModel.tenant_id == self.tenant_id,
                                        UserModel.is_deleted.is_(False),
                                        UserModel.status == "0",
                                    )
                                )
                            )
                            .mappings()
                            .first()
                        )
                        if not applicant or not applicant["dept_id"]:
                            raise conflict("APPLICANT_UNAVAILABLE", "申请人已停用或尚未设置部门")
                        state = AssetState.RESERVED
                    elif app["application_type"] == ApplicationType.RETURN:
                        if not data.review_note or not data.review_note.strip():
                            raise CustomException(
                                msg="归还验收记录不能为空", code=42201, status_code=422
                            )
                        loan = await self.open_loan(item["id"], lock=True)
                        if (
                            loan["id"] != app["loan_id"]
                            or loan["borrower_id"] != app["applicant_id"]
                            or loan["loan_state"] != LoanState.IN_USE
                        ):
                            raise conflict("LOAN_STATE_CONFLICT", "归还申请与当前领用记录不匹配")
                    elif app["application_type"] == ApplicationType.REPAIR:
                        state = AssetState.MAINTENANCE
                        if item["asset_state"] == AssetState.IN_USE:
                            loan = await self.open_loan(item["id"], lock=True)
                            if loan["borrower_id"] != app["applicant_id"]:
                                raise conflict("LOAN_STATE_CONFLICT", "维修申请与当前保管人不匹配")
                    changed = await self.change_asset(item, state, custodian_id, dept_id)
                    before.update(self.snapshot(item))
                    after = {**self.snapshot(changed), "application_state": "APPROVED"}
                await self.db.execute(
                    update(Application.__table__)
                    .where(
                        Application.id == app_id,
                        Application.tenant_id == self.tenant_id,
                        Application.application_state == ApplicationState.PENDING,
                    )
                    .values(application_state=after["application_state"], updated_id=self.user.id)
                )
                await self.db.execute(
                    Approval.__table__.insert().values(
                        tenant_id=self.tenant_id,
                        application_id=app_id,
                        reviewer_id=self.user.id,
                        decision=decision,
                        reviewed_at=datetime.now(),
                        **data.model_dump(),
                    )
                )
                if decision == ApprovalDecision.APPROVE:
                    now = datetime.now()
                    if app["application_type"] == ApplicationType.ISSUE:
                        result = await self.db.execute(
                            Loan.__table__.insert().values(
                                **self.creation(),
                                asset_id=app["asset_id"],
                                issue_application_id=app_id,
                                borrower_id=app["applicant_id"],
                                loan_state=LoanState.PENDING_HANDOVER,
                                approved_at=now,
                            )
                        )
                        await self.db.execute(
                            update(Application.__table__)
                            .where(Application.id == app_id)
                            .values(loan_id=result.inserted_primary_key[0])
                        )
                        before["loan_state"] = None
                        after["loan_state"] = LoanState.PENDING_HANDOVER.value
                    elif loan and app["application_type"] in (
                        ApplicationType.RETURN,
                        ApplicationType.REPAIR,
                    ):
                        await self.db.execute(
                            update(Loan.__table__)
                            .where(Loan.id == loan["id"], Loan.loan_state == LoanState.IN_USE)
                            .values(
                                loan_state=LoanState.COMPLETED,
                                returned_at=now
                                if app["application_type"] == ApplicationType.RETURN
                                else None,
                                return_actor_id=self.user.id
                                if app["application_type"] == ApplicationType.RETURN
                                else None,
                                return_note=data.review_note
                                if app["application_type"] == ApplicationType.RETURN
                                else None,
                                close_reason=app["application_type"].value,
                                updated_id=self.user.id,
                            )
                        )
                        before["loan_state"] = LoanState.IN_USE.value
                        after["loan_state"] = LoanState.COMPLETED.value
                action = (
                    f"{app['application_type'].value}_APPROVED"
                    if decision == ApprovalDecision.APPROVE
                    else "APPLICATION_REJECTED"
                )
                await self.audit(app["asset_id"], action, before, after, app_id)
                return await self.row(Application, app_id)
        except IntegrityError as exc:
            raise conflict("APPROVAL_CONFLICT", "审批请求键或审批记录冲突") from exc

    async def cancel(self, app_id: int):
        await self.require("application:cancel")
        async with self.db.begin_nested():
            app = await self.row(Application, app_id, lock=True)
            if app["applicant_id"] != self.user.id:
                raise CustomException(msg="只有申请人可以取消申请", code=10403, status_code=403)
            if app["application_state"] != ApplicationState.PENDING:
                raise conflict("APPLICATION_ALREADY_PROCESSED", "仅待审申请可取消")
            await self.db.execute(
                update(Application.__table__)
                .where(Application.id == app_id)
                .values(application_state=ApplicationState.CANCELLED, updated_id=self.user.id)
            )
            await self.audit(
                app["asset_id"],
                "APPLICATION_CANCELLED",
                {"application_state": "PENDING"},
                {"application_state": "CANCELLED"},
                app_id,
            )
            return await self.row(Application, app_id)

    async def handover(self, loan_id: int, note: str):
        await self.require("application:approve")
        async with self.db.begin_nested():
            loan = await self.row(Loan, loan_id)
            if loan["borrower_id"] == self.user.id:
                raise CustomException(msg="不能向自己交付资产", code=10403, status_code=403)
            await self.row(Application, loan["issue_application_id"], scoped=True)
            item = await self.row(Item, loan["asset_id"], lock=True)
            loan = await self.row(Loan, loan_id, lock=True)
            if (
                loan["loan_state"] != LoanState.PENDING_HANDOVER
                or item["asset_state"] != AssetState.RESERVED
            ):
                raise conflict("LOAN_STATE_CONFLICT", "资产不在待交付状态")
            await self.db.execute(
                update(Loan.__table__)
                .where(Loan.id == loan_id, Loan.loan_state == LoanState.PENDING_HANDOVER)
                .values(
                    loan_state=LoanState.PENDING_RECEIPT,
                    handed_at=datetime.now(),
                    handover_actor_id=self.user.id,
                    handover_note=note,
                    updated_id=self.user.id,
                )
            )
            await self.audit(
                item["id"],
                "LOAN_HANDED_OVER",
                {"loan_state": LoanState.PENDING_HANDOVER.value},
                {"loan_state": LoanState.PENDING_RECEIPT.value},
                loan["issue_application_id"],
            )
            return await self.row(Loan, loan_id)

    async def receive(self, loan_id: int):
        await self.require("application:create")
        async with self.db.begin_nested():
            loan = await self.row(Loan, loan_id)
            if loan["borrower_id"] != self.user.id:
                raise CustomException(msg="只有领用人本人可以签收", code=10403, status_code=403)
            item = await self.row(Item, loan["asset_id"], lock=True)
            loan = await self.row(Loan, loan_id, lock=True)
            if (
                loan["loan_state"] != LoanState.PENDING_RECEIPT
                or item["asset_state"] != AssetState.RESERVED
            ):
                raise conflict("LOAN_STATE_CONFLICT", "资产不在待签收状态")
            applicant = (
                (
                    await self.db.execute(
                        select(UserModel.__table__).where(
                            UserModel.id == self.user.id,
                            UserModel.tenant_id == self.tenant_id,
                            UserModel.is_deleted.is_(False),
                            UserModel.status == "0",
                        )
                    )
                )
                .mappings()
                .first()
            )
            if not applicant or not applicant["dept_id"]:
                raise conflict("APPLICANT_UNAVAILABLE", "领用人已停用或尚未设置部门")
            changed = await self.change_asset(
                item, AssetState.IN_USE, applicant["id"], applicant["dept_id"]
            )
            await self.db.execute(
                update(Loan.__table__)
                .where(Loan.id == loan_id, Loan.loan_state == LoanState.PENDING_RECEIPT)
                .values(
                    loan_state=LoanState.IN_USE, received_at=datetime.now(), updated_id=self.user.id
                )
            )
            await self.audit(
                item["id"],
                "LOAN_RECEIVED",
                {**self.snapshot(item), "loan_state": LoanState.PENDING_RECEIPT.value},
                {**self.snapshot(changed), "loan_state": LoanState.IN_USE.value},
                loan["issue_application_id"],
            )
            return await self.row(Loan, loan_id)

    async def cancel_handover(self, loan_id: int, reason: str):
        await self.require("application:approve")
        async with self.db.begin_nested():
            loan = await self.row(Loan, loan_id)
            if loan["borrower_id"] == self.user.id:
                raise CustomException(msg="不能撤销自己的交付流程", code=10403, status_code=403)
            await self.row(Application, loan["issue_application_id"], scoped=True)
            item = await self.row(Item, loan["asset_id"], lock=True)
            loan = await self.row(Loan, loan_id, lock=True)
            if (
                loan["loan_state"] not in (LoanState.PENDING_HANDOVER, LoanState.PENDING_RECEIPT)
                or item["asset_state"] != AssetState.RESERVED
            ):
                raise conflict("LOAN_STATE_CONFLICT", "仅待交付或待签收记录可撤销")
            changed = await self.change_asset(item, AssetState.AVAILABLE)
            await self.db.execute(
                update(Loan.__table__)
                .where(Loan.id == loan_id)
                .values(
                    loan_state=LoanState.CANCELLED,
                    close_reason="CANCELLED",
                    cancel_reason=reason,
                    updated_id=self.user.id,
                )
            )
            await self.audit(
                item["id"],
                "LOAN_CANCELLED",
                {**self.snapshot(item), "loan_state": loan["loan_state"].value},
                {**self.snapshot(changed), "loan_state": LoanState.CANCELLED.value},
                loan["issue_application_id"],
            )
            return await self.row(Loan, loan_id)

    async def complete_repair(self, app_id: int, note: str):
        await self.require("item:manage")
        async with self.db.begin_nested():
            app = await self.row(Application, app_id, lock=True, scoped=True)
            if (
                app["application_type"] != ApplicationType.REPAIR
                or app["application_state"] != ApplicationState.APPROVED
            ):
                raise conflict("APPLICATION_STATE_CONFLICT", "仅已批准的维修申请可完成维修")
            item = await self.row(Item, app["asset_id"], lock=True)
            if (
                item["asset_state"] != AssetState.MAINTENANCE
                or item["row_version"] != app["asset_version_at_submit"] + 1
            ):
                raise conflict("ASSET_STATE_CONFLICT", "资产已不处于本次维修状态")
            changed = await self.change_asset(item, AssetState.AVAILABLE)
            await self.db.execute(
                update(Application.__table__)
                .where(Application.id == app_id)
                .values(
                    application_state=ApplicationState.COMPLETED,
                    completed_at=datetime.now(),
                    completion_note=note,
                    updated_id=self.user.id,
                )
            )
            await self.audit(
                item["id"], "REPAIR_COMPLETED", self.snapshot(item), self.snapshot(changed), app_id
            )
            return await self.row(Application, app_id)

    async def retire(self, item_id: int, version: int):
        await self.require("item:manage")
        async with self.db.begin_nested():
            item = await self.row(Item, item_id, lock=True)
            if (
                item["asset_state"] not in {AssetState.AVAILABLE, AssetState.MAINTENANCE}
                or item["row_version"] != version
            ):
                raise conflict("ASSET_STATE_CONFLICT", "资产状态或版本已变化，无法报废")
            changed = await self.change_asset(item, AssetState.RETIRED)
            await self.audit(item_id, "ASSET_RETIRED", self.snapshot(item), self.snapshot(changed))
            return changed

    def display_columns(self, model):
        def label(source, field, reference, name):
            return (
                select(getattr(source, field))
                .where(source.id == reference, source.tenant_id == self.tenant_id)
                .correlate(model.__table__)
                .scalar_subquery()
                .label(name)
            )

        if model is Item:
            return [
                label(Category, "name", Item.category_id, "category_name"),
                label(UserModel, "name", Item.custodian_id, "custodian_name"),
                select(UserModel.name)
                .join(Loan, Loan.borrower_id == UserModel.id)
                .where(
                    Loan.asset_id == Item.id,
                    Loan.tenant_id == self.tenant_id,
                    Loan.loan_state.in_((LoanState.PENDING_HANDOVER, LoanState.PENDING_RECEIPT)),
                )
                .correlate(Item.__table__)
                .scalar_subquery()
                .label("reserved_for_name"),
            ]
        if model is Application:
            pending_return = Application.__table__.alias("pending_return")
            columns = [
                label(Item, "name", Application.asset_id, "asset_name"),
                label(Item, "asset_code", Application.asset_id, "asset_code"),
                label(UserModel, "name", Application.applicant_id, "applicant_name"),
                select(Approval.review_note)
                .where(
                    Approval.application_id == Application.id, Approval.tenant_id == self.tenant_id
                )
                .correlate(Application.__table__)
                .scalar_subquery()
                .label("review_note"),
                select(Approval.reviewed_at)
                .where(
                    Approval.application_id == Application.id, Approval.tenant_id == self.tenant_id
                )
                .correlate(Application.__table__)
                .scalar_subquery()
                .label("reviewed_at"),
                select(UserModel.name)
                .join(Approval, Approval.reviewer_id == UserModel.id)
                .where(
                    Approval.application_id == Application.id,
                    Approval.tenant_id == self.tenant_id,
                    UserModel.tenant_id == self.tenant_id,
                )
                .correlate(Application.__table__)
                .scalar_subquery()
                .label("reviewer_name"),
                select(pending_return.c.id)
                .where(
                    pending_return.c.loan_id == Application.loan_id,
                    pending_return.c.tenant_id == self.tenant_id,
                    pending_return.c.application_type == ApplicationType.RETURN,
                    pending_return.c.application_state == ApplicationState.PENDING,
                    pending_return.c.is_deleted.is_(False),
                )
                .correlate(Application.__table__)
                .scalar_subquery()
                .label("pending_return_id"),
            ]
            for field in (
                "loan_state",
                "approved_at",
                "handed_at",
                "handover_note",
                "received_at",
                "returned_at",
                "return_note",
                "close_reason",
                "cancel_reason",
                "is_legacy",
            ):
                columns.append(
                    select(getattr(Loan, field))
                    .where(Loan.id == Application.loan_id, Loan.tenant_id == self.tenant_id)
                    .correlate(Application.__table__)
                    .scalar_subquery()
                    .label("loan_state" if field == "loan_state" else f"loan_{field}")
                )
            return columns
        if model is Audit:
            return [
                label(Item, "name", Audit.asset_id, "asset_name"),
                label(Item, "asset_code", Audit.asset_id, "asset_code"),
                label(UserModel, "name", Audit.actor_id, "actor_name"),
            ]
        return []

    async def listing(
        self,
        resource: str,
        page: int,
        size: int,
        state=None,
        keyword=None,
        category_id=None,
        asset_id=None,
    ):
        models = {"category": Category, "item": Item, "application": Application, "audit": Audit}
        model = models[resource]
        await self.require(
            f"{resource}:query",
            *(["application:approve", "application:reject"] if resource == "application" else []),
        )
        query = select(model.__table__, *self.display_columns(model)).where(
            model.tenant_id == self.tenant_id, model.is_deleted.is_(False)
        )
        if resource == "application":
            try:
                await self.require("application:approve", "application:reject")
            except CustomException:
                query = query.where(Application.applicant_id == self.user.id)
            else:
                query = await self.scoped_query(model, query)
            if state:
                query = query.where(Application.application_state == state)
        elif resource == "item" and state:
            query = query.where(Item.asset_state == state)
        if keyword:
            if resource == "category":
                query = query.where(
                    or_(
                        Category.name.contains(keyword, autoescape=True),
                        Category.code.contains(keyword, autoescape=True),
                    )
                )
            elif resource == "item":
                query = query.where(
                    or_(
                        Item.name.contains(keyword, autoescape=True),
                        Item.asset_code.contains(keyword, autoescape=True),
                    )
                )
            elif resource == "audit":
                query = query.where(
                    Audit.asset_id.in_(
                        select(Item.id).where(
                            Item.tenant_id == self.tenant_id,
                            or_(
                                Item.name.contains(keyword, autoescape=True),
                                Item.asset_code.contains(keyword, autoescape=True),
                            ),
                        )
                    )
                )
        if resource == "item" and category_id:
            query = query.where(Item.category_id == category_id)
        if resource == "audit" and asset_id:
            query = query.where(Audit.asset_id == asset_id)
        total = await self.db.scalar(select(func.count()).select_from(query.subquery()))
        rows = (
            await self.db.execute(
                query.order_by(model.id.desc()).offset((page - 1) * size).limit(size)
            )
        ).mappings()
        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "page_no": page,
            "page_size": size,
        }

    async def detail(self, item_id: int):
        await self.require("item:query")
        await self.row(Item, item_id)
        query = select(Item.__table__, *self.display_columns(Item)).where(
            Item.id == item_id, Item.tenant_id == self.tenant_id
        )
        return dict((await self.db.execute(query)).mappings().one())

    async def summary(self):
        await self.require("dashboard:query")
        rows = await self.db.execute(
            select(Item.asset_state, func.count())
            .where(Item.tenant_id == self.tenant_id, Item.is_deleted.is_(False))
            .group_by(Item.asset_state)
        )
        counts = dict(rows.all())
        return {state.value: counts.get(state, 0) for state in AssetState}
