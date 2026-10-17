"""AssetFlow 模型与迁移检查；MySQL 用例需显式设置 ASSETFLOW_MYSQL_TESTS=1。

集成用例复用开发库，普通用例结束时回滚；并发用例短暂提交模拟数据，
结束时按主键清理。不新建数据库、不更新既有用户或业务数据。
"""

import asyncio
import importlib.util
import io
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import create_engine, delete, event, func, inspect, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import configure_mappers

from alembic import command
from app.api.v1.module_system.auth.schema import AuthSchema
from app.api.v1.module_system.menu.model import MenuModel
from app.api.v1.module_system.role.model import RoleModel
from app.api.v1.module_system.user.model import UserModel
from app.config.setting import settings
from app.core.base_model import MappedBase
from app.core.exceptions import CustomException
from app.plugin.module_asset.enums import ApplicationType, ApprovalDecision, AssetState
from app.plugin.module_asset.model import (
    AssetApplicationModel,
    AssetApprovalModel,
    AssetAuditLogModel,
    AssetCategoryModel,
    AssetItemModel,
    AssetLoanModel,
)
from app.plugin.module_asset.schema import (
    ApplicationCreate,
    ApprovalInput,
    CategoryCreate,
    ItemCreate,
)
from app.plugin.module_asset.service import AssetService
from app.utils.import_util import ImportUtil

BACKEND = Path(__file__).resolve().parents[1]
ASSET_TABLES = {
    "asset_category",
    "asset_item",
    "asset_application",
    "asset_approval",
    "asset_audit_log",
    "asset_loan",
}
INITIAL_ASSET_TABLES = ASSET_TABLES - {"asset_loan"}


@pytest.fixture(scope="module", autouse=True)
def discover_models():
    ImportUtil.find_models(MappedBase)
    configure_mappers()


@pytest.fixture
def migration():
    spec = importlib.util.spec_from_file_location(
        "asset_migration", BACKEND / "app/alembic/versions/20261017_01_assetflow_tables.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plugin_models_are_discovered():
    models = ImportUtil.find_models(MappedBase)
    assert {m.__tablename__ for m in models if m.__tablename__.startswith("asset_")} == ASSET_TABLES


def test_migration_sql_only_manages_asset_tables(migration):
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="mysql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        migration.upgrade()
    sql = output.getvalue()
    assert set(re.findall(r"CREATE TABLE (\w+)", sql)) == INITIAL_ASSET_TABLES
    assert "DROP TABLE" not in sql and "ALTER TABLE sys_" not in sql
    output.truncate(0)
    output.seek(0)
    with Operations.context(context):
        migration.downgrade()
    drops = re.findall(r"DROP TABLE (\w+)", output.getvalue())
    assert drops == [
        "asset_audit_log",
        "asset_approval",
        "asset_application",
        "asset_item",
        "asset_category",
    ]
    assert "DROP INDEX" not in output.getvalue()


def test_alembic_preserves_preloaded_metadata(monkeypatch):
    metadata = MappedBase.metadata
    original = ImportUtil.find_models

    def find_models(base_class):
        assert base_class.metadata is metadata
        return original(base_class)

    monkeypatch.setattr(ImportUtil, "find_models", find_models)
    config = Config(str(BACKEND / "alembic.ini"), output_buffer=io.StringIO())
    config.set_main_option("script_location", str(BACKEND / "app/alembic"))
    command.upgrade(config, "20261017_01", sql=True)
    assert MappedBase.metadata is metadata
    assert ASSET_TABLES.issubset(metadata.tables)
    assert "sys_user" in metadata.tables


def test_downgrade_checks_all_data_before_dropping(migration, monkeypatch):
    drops = []
    # 审计表为空，审批表有数据时，必须在删除任何表之前停止。
    results = iter([None, (1,)])
    connection = SimpleNamespace(execute=lambda query: SimpleNamespace(first=lambda: next(results)))
    monkeypatch.setattr(
        migration,
        "op",
        SimpleNamespace(
            get_context=lambda: SimpleNamespace(as_sql=False),
            get_bind=lambda: connection,
            drop_table=drops.append,
        ),
    )
    with pytest.raises(RuntimeError, match="contain data"):
        migration.downgrade()
    assert drops == []


@pytest.fixture(scope="module")
def mysql_engine():
    if os.environ.get("ASSETFLOW_MYSQL_TESTS") != "1":
        pytest.skip("Set ASSETFLOW_MYSQL_TESTS=1 to use the existing development MySQL database")
    assert settings.ENVIRONMENT.value == "dev", "Integration checks require the development config"
    assert settings.DATABASE_TYPE == "mysql"
    engine = create_engine(settings.DB_URI)
    with engine.connect() as connection:
        assert ASSET_TABLES.issubset(inspect(connection).get_table_names())
    yield engine
    engine.dispose()


@pytest.fixture
def sample(mysql_engine):
    with mysql_engine.connect() as connection:
        transaction = connection.begin()
        try:
            user = MappedBase.metadata.tables["sys_user"]
            actor = connection.execute(select(user.c.id, user.c.tenant_id).limit(1)).first()
            assert actor is not None, "Initialize upstream seed users before integration checks"
            token = uuid4().hex
            category_id = connection.execute(
                AssetCategoryModel.__table__.insert().values(
                    code=token, name="AssetFlow schema check", tenant_id=actor.tenant_id
                )
            ).inserted_primary_key[0]
            asset_id = connection.execute(
                AssetItemModel.__table__.insert().values(
                    asset_code=token,
                    name="AssetFlow schema check",
                    category_id=category_id,
                    tenant_id=actor.tenant_id,
                )
            ).inserted_primary_key[0]
            yield SimpleNamespace(
                connection=connection,
                actor=actor,
                category_id=category_id,
                asset_id=asset_id,
                token=token,
            )
        finally:
            transaction.rollback()


def application_values(sample, **overrides):
    return {
        "request_no": uuid4().hex,
        "asset_id": sample.asset_id,
        "applicant_id": sample.actor.id,
        "tenant_id": sample.actor.tenant_id,
        "application_type": ApplicationType.ISSUE,
        "reason": "Schema verification",
        "idempotency_key": sample.token,
        "asset_version_at_submit": 1,
        **overrides,
    }


def test_asset_code_is_reserved_after_soft_delete(sample):
    table = AssetItemModel.__table__
    sample.connection.execute(
        table.update().where(table.c.id == sample.asset_id).values(is_deleted=True)
    )
    with pytest.raises(IntegrityError), sample.connection.begin_nested():
        sample.connection.execute(
            table.insert().values(
                asset_code=sample.token,
                name="Duplicate",
                category_id=sample.category_id,
                tenant_id=sample.actor.tenant_id,
            )
        )


@pytest.mark.parametrize(
    "changes, error_number",
    [
        ({"row_version": 0}, 3819),
        ({"purchase_amount": -1}, 3819),
        ({"asset_state": AssetState.IN_USE}, 3819),
        ({"category_id": -1}, 1452),
    ],
)
def test_invalid_asset_values_are_rejected(sample, changes, error_number):
    table = AssetItemModel.__table__
    with pytest.raises(DBAPIError) as failure, sample.connection.begin_nested():
        sample.connection.execute(
            table.update().where(table.c.id == sample.asset_id).values(**changes)
        )
    assert failure.value.orig.args[0] == error_number


def test_application_idempotency_is_unique_and_case_sensitive(sample):
    table = AssetApplicationModel.__table__
    values = application_values(sample, idempotency_key="Key-" + sample.token)
    sample.connection.execute(table.insert().values(**values))
    with pytest.raises(IntegrityError), sample.connection.begin_nested():
        sample.connection.execute(table.insert().values(**{**values, "request_no": uuid4().hex}))
    sample.connection.execute(
        table.insert().values(**{
            **values,
            "request_no": uuid4().hex,
            "idempotency_key": "key-" + sample.token,
        })
    )


def test_completed_application_must_be_a_repair(sample):
    table = AssetApplicationModel.__table__
    with pytest.raises(DBAPIError) as failure, sample.connection.begin_nested():
        sample.connection.execute(
            table.insert().values(
                **application_values(
                    sample,
                    application_state="COMPLETED",
                    completed_at=datetime.now(),
                    completion_note="Done",
                )
            )
        )
    assert failure.value.orig.args[0] == 3819


def test_application_can_only_have_one_approval(sample):
    application_id = sample.connection.execute(
        AssetApplicationModel.__table__.insert().values(**application_values(sample))
    ).inserted_primary_key[0]
    table = AssetApprovalModel.__table__
    values = {
        "application_id": application_id,
        "reviewer_id": sample.actor.id,
        "tenant_id": sample.actor.tenant_id,
        "decision": ApprovalDecision.APPROVE,
        "reviewed_at": datetime.now(),
    }
    sample.connection.execute(table.insert().values(**values))
    with pytest.raises(IntegrityError), sample.connection.begin_nested():
        sample.connection.execute(table.insert().values(**values))


def test_reject_requires_a_reason(sample):
    application_id = sample.connection.execute(
        AssetApplicationModel.__table__.insert().values(**application_values(sample))
    ).inserted_primary_key[0]
    with pytest.raises(DBAPIError) as failure, sample.connection.begin_nested():
        sample.connection.execute(
            AssetApprovalModel.__table__.insert().values(
                application_id=application_id,
                reviewer_id=sample.actor.id,
                tenant_id=sample.actor.tenant_id,
                decision=ApprovalDecision.REJECT,
                reviewed_at=datetime.now(),
                review_note="   ",
            )
        )
    assert failure.value.orig.args[0] == 3819


@asynccontextmanager
async def service_sample(*, committed=False):
    engine = create_async_engine(settings.ASYNC_DB_URI)
    asset_id = category_id = None
    user_ids = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            try:
                tenant_id = await session.scalar(
                    select(MappedBase.metadata.tables["sys_tenant"].c.id).limit(1)
                )
                dept_id = await session.scalar(
                    select(MappedBase.metadata.tables["sys_dept"].c.id).limit(1)
                )
                assert tenant_id and dept_id
                for _ in range(3):
                    result = await session.execute(
                        UserModel.__table__.insert().values(
                            username="__assetflow_verify_" + uuid4().hex,
                            name="Schema verification",
                            password="!disabled-test-account",
                            tenant_id=tenant_id,
                            dept_id=dept_id,
                        )
                    )
                    user_ids.append(result.inserted_primary_key[0])

                def profile(uid, *, admin=False):
                    permissions = [
                        "item:query",
                        "category:query",
                        "application:create",
                        "application:query",
                        "application:cancel",
                    ]
                    role = RoleModel(
                        status="0",
                        data_scope=4,
                        menus=[
                            MenuModel(status="0", permission=f"module_asset:{p}")
                            for p in permissions
                        ],
                    )
                    return UserModel(
                        id=uid,
                        tenant_id=tenant_id,
                        dept_id=dept_id,
                        is_superuser=admin,
                        roles=[role],
                    )

                owner, other, reviewer = [
                    profile(uid, admin=i == 2) for i, uid in enumerate(user_ids)
                ]

                def service(user):
                    return AssetService(AuthSchema(db=session, user=user))

                manager = service(reviewer)
                category = await manager.create_category(
                    CategoryCreate(code=uuid4().hex, name="Test")
                )
                category_id = category["id"]
                item = await manager.create_item(
                    ItemCreate(asset_code=uuid4().hex, name="Test", category_id=category_id)
                )
                asset_id = item["id"]
                yield SimpleNamespace(
                    db=session,
                    engine=engine,
                    owner=owner,
                    other=other,
                    reviewer=reviewer,
                    service=service,
                    item=item,
                    tenant_id=tenant_id,
                )
            finally:
                await session.rollback()
    finally:
        try:
            if committed:
                async with engine.begin() as connection:
                    # 仅清理本用例通过主键跟踪的模拟资产及用户。
                    if asset_id:
                        apps = select(AssetApplicationModel.id).where(
                            AssetApplicationModel.asset_id == asset_id
                        )
                        await connection.execute(
                            delete(AssetAuditLogModel.__table__).where(
                                AssetAuditLogModel.asset_id == asset_id
                            )
                        )
                        await connection.execute(
                            delete(AssetApprovalModel.__table__).where(
                                AssetApprovalModel.application_id.in_(apps)
                            )
                        )
                        await connection.execute(
                            AssetApplicationModel.__table__.update()
                            .where(AssetApplicationModel.asset_id == asset_id)
                            .values(loan_id=None)
                        )
                        await connection.execute(
                            delete(AssetLoanModel.__table__).where(
                                AssetLoanModel.asset_id == asset_id
                            )
                        )
                        await connection.execute(
                            delete(AssetApplicationModel.__table__).where(
                                AssetApplicationModel.asset_id == asset_id
                            )
                        )
                        await connection.execute(
                            delete(AssetItemModel.__table__).where(AssetItemModel.id == asset_id)
                        )
                    if category_id:
                        await connection.execute(
                            delete(AssetCategoryModel.__table__).where(
                                AssetCategoryModel.id == category_id
                            )
                        )
                    if user_ids:
                        await connection.execute(
                            delete(UserModel.__table__).where(UserModel.id.in_(user_ids))
                        )
        finally:
            await engine.dispose()


def request(sample, kind=ApplicationType.ISSUE, key=None):
    return ApplicationCreate(
        asset_id=sample.item["id"],
        application_type=kind,
        reason="Verification",
        idempotency_key=key or uuid4().hex,
    )


def test_issue_return_repair_and_idempotent_replay(mysql_engine):
    async def scenario():
        async with service_sample() as sample:
            owner, manager = sample.service(sample.owner), sample.service(sample.reviewer)
            data = request(sample)
            app = await owner.submit(data)
            assert (await owner.submit(data))["id"] == app["id"]
            assert (await owner.detail(sample.item["id"]))["asset_state"] == AssetState.AVAILABLE
            approval = ApprovalInput(idempotency_key=uuid4().hex)
            await manager.decide(app["id"], approval, ApprovalDecision.APPROVE)
            await manager.decide(app["id"], approval, ApprovalDecision.APPROVE)
            item = await owner.detail(sample.item["id"])
            assert item["asset_state"] == AssetState.RESERVED and item["custodian_id"] is None
            loan_id = (await owner.listing("application", 1, 20))["items"][0]["loan_id"]
            await manager.handover(loan_id, "已交付设备及电源")
            await owner.receive(loan_id)
            item = await owner.detail(sample.item["id"])
            assert (
                item["asset_state"] == AssetState.IN_USE and item["custodian_id"] == sample.owner.id
            )
            for kind in [ApplicationType.RETURN, ApplicationType.REPAIR]:
                app = await owner.submit(request(sample, kind))
                await manager.decide(
                    app["id"],
                    ApprovalInput(review_note="验收设备及配件" if kind == ApplicationType.RETURN else None),
                    ApprovalDecision.APPROVE,
                )
            loan = await sample.db.get(AssetLoanModel, loan_id)
            assert loan.loan_state == "COMPLETED" and loan.return_note == "验收设备及配件"
            assert (await owner.detail(sample.item["id"]))["asset_state"] == AssetState.MAINTENANCE
            await manager.complete_repair(app["id"], "Repaired")
            item = await owner.detail(sample.item["id"])
            assert item["asset_state"] == AssetState.AVAILABLE and item["row_version"] == 6
            assert item["custodian_id"] is None
            assert (
                await sample.db.scalar(
                    select(func.count())
                    .select_from(AssetApprovalModel)
                    .where(
                        AssetApprovalModel.application_id.in_(
                            select(AssetApplicationModel.id).where(
                                AssetApplicationModel.asset_id == sample.item["id"]
                            )
                        )
                    )
                )
                == 3
            )

    asyncio.run(scenario())


def test_approval_permissions_self_approval_and_private_applications(mysql_engine):
    async def scenario():
        async with service_sample() as sample:
            owner, other, manager = (
                sample.service(u) for u in (sample.owner, sample.other, sample.reviewer)
            )
            app = await owner.submit(request(sample))
            with pytest.raises(CustomException) as denied:
                await other.decide(app["id"], ApprovalInput(), ApprovalDecision.APPROVE)
            assert denied.value.status_code == 403
            assert (await owner.listing("application", 1, 20))["total"] == 1
            assert (await other.listing("application", 1, 20))["total"] == 0
            assert (await other.listing("item", 1, 20))["total"] >= 1
            own = await manager.submit(request(sample))
            with pytest.raises(CustomException) as denied:
                await manager.decide(own["id"], ApprovalInput(), ApprovalDecision.APPROVE)
            assert denied.value.status_code == 403
            outsider = UserModel(
                id=sample.reviewer.id, tenant_id=sample.tenant_id + 1000000, is_superuser=True
            )
            with pytest.raises(CustomException) as missing:
                await sample.service(outsider).detail(sample.item["id"])
            assert missing.value.status_code == 404

    asyncio.run(scenario())


def test_approval_failure_rolls_back_asset_application_and_decision(mysql_engine, monkeypatch):
    async def scenario():
        async with service_sample() as sample:
            app = await sample.service(sample.owner).submit(request(sample))

            async def fail(*args, **kwargs):
                raise RuntimeError("injected audit failure")

            monkeypatch.setattr(AssetService, "audit", fail)
            with pytest.raises(RuntimeError, match="injected"):
                await sample.service(sample.reviewer).decide(
                    app["id"], ApprovalInput(), ApprovalDecision.APPROVE
                )
            item = await sample.service(sample.owner).detail(sample.item["id"])
            assert item["asset_state"] == AssetState.AVAILABLE and item["row_version"] == 1
            assert (
                await sample.db.scalar(
                    select(AssetApplicationModel.application_state).where(
                        AssetApplicationModel.id == app["id"]
                    )
                )
                == "PENDING"
            )
            assert (
                await sample.db.scalar(
                    select(func.count())
                    .select_from(AssetApprovalModel)
                    .where(AssetApprovalModel.application_id == app["id"])
                )
                == 0
            )

    asyncio.run(scenario())


def test_concurrent_approvals_only_issue_one_asset(mysql_engine):
    async def scenario():
        async with service_sample(committed=True) as sample:
            first = await sample.service(sample.owner).submit(request(sample))
            second = await sample.service(sample.other).submit(request(sample))
            await sample.db.commit()

            async def approve(app_id):
                try:
                    async with AsyncSession(sample.engine) as session, session.begin():
                        service = AssetService(AuthSchema(db=session, user=sample.reviewer))
                        await service.decide(app_id, ApprovalInput(), ApprovalDecision.APPROVE)
                    return "approved"
                except CustomException as exc:
                    assert exc.status_code == 409
                    return "conflict"

            results = await asyncio.gather(approve(first["id"]), approve(second["id"]))
            assert sorted(results) == ["approved", "conflict"]
            assert (
                await sample.db.scalar(
                    select(func.count())
                    .select_from(AssetApprovalModel)
                    .where(AssetApprovalModel.application_id.in_([first["id"], second["id"]]))
                )
                == 1
            )

    asyncio.run(scenario())


def test_client_cannot_supply_tenant_or_asset_state():
    with pytest.raises(ValidationError):
        ItemCreate(asset_code="X", name="X", category_id=1, tenant_id=2)
    with pytest.raises(ValidationError):
        ItemCreate(asset_code="X", name="X", category_id=1, asset_state="IN_USE")


def test_stale_application_cannot_issue_asset_after_a_return(mysql_engine):
    """即使资产再次变为在库，早于上次领用的旧申请也不能批准。"""

    async def scenario():
        async with service_sample() as sample:
            owner, other, manager = (
                sample.service(u) for u in (sample.owner, sample.other, sample.reviewer)
            )
            stale = await owner.submit(request(sample))
            issued = await other.submit(request(sample))
            await manager.decide(issued["id"], ApprovalInput(), ApprovalDecision.APPROVE)
            loan_id = (await other.listing("application", 1, 20))["items"][0]["loan_id"]
            await manager.handover(loan_id, "交付")
            await other.receive(loan_id)
            returned = await other.submit(request(sample, ApplicationType.RETURN))
            await manager.decide(
                returned["id"], ApprovalInput(review_note="验收完成"), ApprovalDecision.APPROVE
            )
            with pytest.raises(CustomException) as failure:
                await manager.decide(stale["id"], ApprovalInput(), ApprovalDecision.APPROVE)
            assert failure.value.status_code == 409
            assert failure.value.data["reason"] == "ASSET_STATE_CONFLICT"
            item = await owner.detail(sample.item["id"])
            assert item["asset_state"] == AssetState.AVAILABLE and item["row_version"] == 4
            assert (
                await sample.db.scalar(
                    select(AssetApplicationModel.application_state).where(
                        AssetApplicationModel.id == stale["id"]
                    )
                )
                == "PENDING"
            )
            assert (
                await sample.db.scalar(
                    select(func.count())
                    .select_from(AssetApprovalModel)
                    .where(AssetApprovalModel.application_id == stale["id"])
                )
                == 0
            )

    asyncio.run(scenario())


def test_concurrent_retries_create_one_application_and_approval(mysql_engine):
    async def scenario():
        async with service_sample(committed=True) as sample:
            data = request(sample)
            await sample.db.commit()

            async def submit():
                async with AsyncSession(sample.engine) as session, session.begin():
                    service = AssetService(AuthSchema(db=session, user=sample.owner))
                    return (await service.submit(data))["id"]

            first, second = await asyncio.gather(submit(), submit())
            assert first == second
            approval = ApprovalInput(idempotency_key=uuid4().hex)

            async def approve():
                async with AsyncSession(sample.engine) as session, session.begin():
                    service = AssetService(AuthSchema(db=session, user=sample.reviewer))
                    return await service.decide(first, approval, ApprovalDecision.APPROVE)

            results = await asyncio.gather(approve(), approve())
            assert all(row["application_state"] == "APPROVED" for row in results)
            for model in (AssetApplicationModel, AssetApprovalModel):
                query = select(func.count()).select_from(model)
                query = query.where(
                    model.id == first
                    if model is AssetApplicationModel
                    else model.application_id == first
                )
                assert await sample.db.scalar(query) == 1
            assert (
                await sample.db.scalar(
                    select(func.count())
                    .select_from(AssetAuditLogModel)
                    .where(AssetAuditLogModel.asset_id == sample.item["id"])
                )
                == 3
            )  # 登记、提交、批准各一次。
            assert (await sample.service(sample.owner).detail(sample.item["id"]))[
                "row_version"
            ] == 2

    asyncio.run(scenario())


def test_listing_query_count_does_not_grow_with_page_size(mysql_engine):
    """分页和展示名称保持两次 SQL 往返；此用例不是容量或延迟压测。"""

    async def scenario():
        async with service_sample() as sample:
            manager = sample.service(sample.reviewer)
            employee = sample.service(sample.owner)
            for _ in range(12):
                item = await manager.create_item(
                    ItemCreate(
                        asset_code=uuid4().hex,
                        name="Query count check",
                        category_id=sample.item["category_id"],
                    )
                )
                await employee.submit(
                    ApplicationCreate(
                        asset_id=item["id"],
                        application_type=ApplicationType.ISSUE,
                        reason="Query count check",
                        idempotency_key=uuid4().hex,
                    )
                )
            statements = []

            def capture(connection, cursor, statement, parameters, context, executemany):
                if statement.lstrip().upper().startswith("SELECT"):
                    statements.append(statement)

            event.listen(sample.engine.sync_engine, "before_cursor_execute", capture)
            try:
                for resource in ("item", "application", "audit"):
                    for page_size in (1, 100):
                        statements.clear()
                        page = await manager.listing(resource, 1, page_size)
                        assert page["total"] >= 12
                        assert len(page["items"]) == min(page_size, page["total"])
                        assert len(statements) == 2, (resource, page_size, statements)
            finally:
                event.remove(sample.engine.sync_engine, "before_cursor_execute", capture)

    asyncio.run(scenario())


def test_disabled_role_cannot_expand_approval_scope(mysql_engine):
    async def scenario():
        async with service_sample() as sample:
            app = await sample.service(sample.owner).submit(request(sample))
            profile = UserModel(
                id=sample.reviewer.id,
                tenant_id=sample.tenant_id,
                dept_id=sample.owner.dept_id,
                is_superuser=False,
                roles=[
                    RoleModel(
                        status="0",
                        data_scope=1,
                        menus=[
                            MenuModel(status="0", permission="module_asset:application:approve")
                        ],
                    ),
                    RoleModel(status="1", data_scope=4, menus=[]),
                ],
            )
            manager = sample.service(profile)
            assert (await manager.listing("application", 1, 20))["total"] == 0
            with pytest.raises(CustomException) as denied:
                await manager.decide(app["id"], ApprovalInput(), ApprovalDecision.APPROVE)
            assert denied.value.status_code == 404

    asyncio.run(scenario())


def test_cancel_reject_retire_and_key_conflicts(mysql_engine):
    async def scenario():
        async with service_sample() as sample:
            owner, manager = sample.service(sample.owner), sample.service(sample.reviewer)
            data = request(sample)
            app = await owner.submit(data)
            with pytest.raises(CustomException) as duplicate:
                await owner.submit(data.model_copy(update={"reason": "Changed"}))
            assert duplicate.value.status_code == 409
            await owner.cancel(app["id"])
            with pytest.raises(CustomException):
                await manager.decide(app["id"], ApprovalInput(), ApprovalDecision.APPROVE)
            app = await owner.submit(request(sample))
            await manager.decide(
                app["id"], ApprovalInput(review_note="Unavailable"), ApprovalDecision.REJECT
            )
            assert (await owner.detail(sample.item["id"]))["asset_state"] == AssetState.AVAILABLE
            item = await manager.retire(sample.item["id"], 1)
            assert item["asset_state"] == AssetState.RETIRED
            assert (await manager.summary())["RETIRED"] >= 1
            with pytest.raises(CustomException):
                await owner.submit(request(sample))

    asyncio.run(scenario())


def test_http_full_loan_lifecycle(mysql_engine):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.core.dependencies import get_current_user
    from app.core.exceptions import handle_exception
    from app.plugin.module_asset.controller import AssetRouter

    async def scenario():
        async with service_sample() as sample:
            app = FastAPI()
            handle_exception(app)
            app.include_router(AssetRouter, prefix="/asset")
            current = {"user": sample.owner}

            async def auth():
                return AuthSchema(db=sample.db, user=current["user"])

            app.dependency_overrides[get_current_user] = auth
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                item_id = sample.item["id"]
                response = await client.post(
                    "/asset/application/create", json=request(sample).model_dump(mode="json")
                )
                assert response.status_code == 200, response.text
                application_id = response.json()["data"]["id"]
                response = await client.get(f"/asset/item/detail/{item_id}")
                assert response.json()["data"]["asset_state"] == "AVAILABLE"
                response = await client.post(
                    f"/asset/application/approve/{application_id}", json={}
                )
                assert response.status_code == 403
                current["user"] = sample.reviewer
                response = await client.post(
                    f"/asset/application/approve/{application_id}", json={}
                )
                assert response.status_code == 200, response.text
                assert response.json()["data"]["application_state"] == "APPROVED"
                response = await client.get(f"/asset/item/detail/{item_id}")
                assert response.json()["data"]["asset_state"] == "RESERVED"
                assert response.json()["data"]["custodian_id"] is None
                current["user"] = sample.owner
                response = await client.get("/asset/application/list")
                issue = next(
                    row for row in response.json()["data"]["items"]
                    if row["id"] == application_id
                )
                loan_id = issue["loan_id"]
                assert issue["loan_state"] == "PENDING_HANDOVER"
                response = await client.post(f"/asset/loan/receive/{loan_id}")
                assert response.status_code == 409
                current["user"] = sample.reviewer
                response = await client.post(
                    f"/asset/loan/handover/{loan_id}", json={"note": "设备、电源已交付"}
                )
                assert response.status_code == 200, response.text
                assert response.json()["data"]["loan_state"] == "PENDING_RECEIPT"
                response = await client.post(f"/asset/loan/receive/{loan_id}")
                assert response.status_code == 403
                current["user"] = sample.owner
                response = await client.post(f"/asset/loan/receive/{loan_id}")
                assert response.status_code == 200, response.text
                assert response.json()["data"]["loan_state"] == "IN_USE"
                response = await client.get(f"/asset/item/detail/{item_id}")
                assert response.json()["data"]["asset_state"] == "IN_USE"
                assert response.json()["data"]["custodian_id"] == sample.owner.id
                response = await client.post(
                    "/asset/application/create",
                    json=request(sample, ApplicationType.RETURN).model_dump(mode="json"),
                )
                assert response.status_code == 200, response.text
                return_id = response.json()["data"]["id"]
                assert response.json()["data"]["loan_id"] == loan_id
                current["user"] = sample.reviewer
                response = await client.post(
                    f"/asset/application/approve/{return_id}", json={}
                )
                assert response.status_code == 422
                response = await client.post(
                    f"/asset/application/approve/{return_id}",
                    json={"review_note": "外观完好，配件齐全"},
                )
                assert response.status_code == 200, response.text
                response = await client.get(f"/asset/item/detail/{item_id}")
                assert response.json()["data"]["asset_state"] == "AVAILABLE"
                assert response.json()["data"]["custodian_id"] is None
                response = await client.get(f"/asset/audit/list?asset_id={item_id}")
                assert response.status_code == 200, response.text
                actions = {row["action"] for row in response.json()["data"]["items"]}
                assert {
                    "APPLICATION_SUBMITTED", "ISSUE_APPROVED", "LOAN_HANDED_OVER",
                    "LOAN_RECEIVED", "RETURN_APPROVED",
                } <= actions
                current["user"] = sample.owner
                response = await client.get("/asset/application/list")
                issue = next(
                    row for row in response.json()["data"]["items"]
                    if row["id"] == application_id
                )
                assert issue["loan_state"] == "COMPLETED"
                assert issue["loan_return_note"] == "外观完好，配件齐全"

    asyncio.run(scenario())


def test_startup_does_not_auto_create_migrated_tables(monkeypatch):
    from app.core import database

    captured = []

    async def run_sync(callback, **kwargs):
        captured.extend(table.name for table in kwargs["tables"])

    @asynccontextmanager
    async def begin():
        yield SimpleNamespace(run_sync=run_sync)

    monkeypatch.setattr(database, "async_engine", SimpleNamespace(begin=begin))
    asyncio.run(database.create_tables())
    assert "sys_user" in captured
    assert not ASSET_TABLES.intersection(captured)


def test_asset_search_labels_and_audit_filter(mysql_engine):
    async def scenario():
        async with service_sample() as sample:
            manager, employee = sample.service(sample.reviewer), sample.service(sample.owner)
            marker = uuid4().hex
            await manager.create_item(
                ItemCreate(
                    asset_code=uuid4().hex,
                    name=marker + "% ready",
                    category_id=sample.item["category_id"],
                )
            )
            await manager.create_item(
                ItemCreate(
                    asset_code=uuid4().hex,
                    name=marker + " other",
                    category_id=sample.item["category_id"],
                )
            )
            page = await employee.listing("item", 1, 20, keyword=marker + "%")
            assert page["total"] == 1
            assert page["items"][0]["category_name"] == "Test"
            await employee.submit(request(sample))
            applications = await employee.listing("application", 1, 20)
            assert applications["items"][0]["asset_name"] == sample.item["name"]
            assert applications["items"][0]["applicant_name"] == "Schema verification"
            audit = await manager.listing(
                "audit", 1, 20, asset_id=sample.item["id"], keyword=sample.item["asset_code"]
            )
            assert audit["total"] == 2
            assert all(row["asset_id"] == sample.item["id"] for row in audit["items"])

    asyncio.run(scenario())


def test_asset_menu_seed_is_idempotent_and_preserves_user_bindings(mysql_engine, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "asset_menu_seed", BACKEND / "app/alembic/versions/20261017_02_assetflow_menus.py"
    )
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    # Connection 退出时回滚，重复注册检查不能保留任何权限配置变更。
    with mysql_engine.connect() as connection:
        monkeypatch.setattr(
            seed,
            "op",
            SimpleNamespace(
                get_context=lambda: SimpleNamespace(as_sql=False), get_bind=lambda: connection
            ),
        )
        menu = MappedBase.metadata.tables["sys_menu"]
        role = MappedBase.metadata.tables["sys_role"]
        binding = MappedBase.metadata.tables["sys_user_roles"]
        before = connection.execute(select(binding)).all()
        count = connection.scalar(select(func.count()).select_from(menu))
        seed.upgrade()
        seed.upgrade()
        assert connection.scalar(select(func.count()).select_from(menu)) == count
        assert connection.execute(select(binding)).all() == before
        codes = connection.execute(
            select(role.c.code, role.c.data_scope).where(
                role.c.code.in_(["asset_employee", "asset_manager"])
            )
        ).all()
        assert dict(codes) == {"asset_employee": 1, "asset_manager": 2}
        links = MappedBase.metadata.tables["sys_role_menus"]
        employee_permissions = set(
            connection.scalars(
                select(menu.c.permission)
                .join(links, links.c.menu_id == menu.c.id)
                .join(role, role.c.id == links.c.role_id)
                .where(role.c.code == "asset_employee")
            )
        ) - {None}
        assert employee_permissions == {
            "module_asset:dashboard:query",
            "module_asset:item:query",
            "module_asset:category:query",
            "module_asset:application:query",
            "module_asset:application:create",
            "module_asset:application:cancel",
        }
