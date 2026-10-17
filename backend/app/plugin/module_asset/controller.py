from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.api.v1.module_system.auth.schema import AuthSchema
from app.common.response import SuccessResponse
from app.core.dependencies import get_current_user
from app.core.router_class import OperationLogRoute

from .enums import ApplicationState, ApprovalDecision, AssetState
from .monitoring import watch_adapter
from .schema import (
    ApplicationCreate,
    ApprovalInput,
    CancelHandoverInput,
    CategoryCreate,
    HandoverInput,
    ItemCreate,
    RepairComplete,
    RetireInput,
)
from .service import AssetService

AssetRouter = APIRouter(route_class=OperationLogRoute, tags=["资产管理"])
Auth = Annotated[AuthSchema, Depends(get_current_user)]
ObjectId = Annotated[int, Path(gt=0)]
Page = Annotated[int, Query(ge=1)]
Size = Annotated[int, Query(ge=1, le=100)]


@AssetRouter.post("/category/create", summary="创建资产分类")
async def create_category(data: CategoryCreate, auth: Auth):
    return SuccessResponse(data=await AssetService(auth).create_category(data))


@AssetRouter.get("/category/list", summary="查询租户共享分类")
async def list_categories(
    auth: Auth,
    page_no: Page = 1,
    page_size: Size = 20,
    keyword: Annotated[str | None, Query(max_length=128)] = None,
):
    return SuccessResponse(
        data=await AssetService(auth).listing("category", page_no, page_size, keyword=keyword)
    )


@AssetRouter.post("/item/create", summary="登记实物资产")
async def create_item(data: ItemCreate, auth: Auth):
    return SuccessResponse(data=await AssetService(auth).create_item(data))


@AssetRouter.get("/item/list", summary="查询租户共享资产目录")
async def list_items(
    auth: Auth,
    page_no: Page = 1,
    page_size: Size = 20,
    asset_state: AssetState | None = None,
    keyword: Annotated[str | None, Query(max_length=128)] = None,
    category_id: Annotated[int | None, Query(gt=0)] = None,
):
    return SuccessResponse(
        data=await AssetService(auth).listing(
            "item", page_no, page_size, asset_state, keyword=keyword, category_id=category_id
        )
    )


@AssetRouter.get("/item/detail/{id}", summary="资产详情")
async def item_detail(id: ObjectId, auth: Auth):
    return SuccessResponse(data=await AssetService(auth).detail(id))


@AssetRouter.post("/application/create", summary="提交资产申请（不占用资产）")
async def submit_application(data: ApplicationCreate, auth: Auth):
    return SuccessResponse(data=await AssetService(auth).submit(data))


@AssetRouter.get("/application/list", summary="查询本人申请或权限范围内的审批申请")
async def list_applications(
    auth: Auth,
    page_no: Page = 1,
    page_size: Size = 20,
    application_state: ApplicationState | None = None,
):
    return SuccessResponse(
        data=await AssetService(auth).listing("application", page_no, page_size, application_state)
    )


@AssetRouter.post("/application/approve/{id}", summary="批准申请并原子变更资产")
async def approve_application(id: ObjectId, data: ApprovalInput, auth: Auth):
    return SuccessResponse(data=await AssetService(auth).decide(id, data, ApprovalDecision.APPROVE))


@AssetRouter.post("/application/reject/{id}", summary="驳回申请")
async def reject_application(id: ObjectId, data: ApprovalInput, auth: Auth):
    return SuccessResponse(data=await AssetService(auth).decide(id, data, ApprovalDecision.REJECT))


@AssetRouter.post("/application/cancel/{id}", summary="申请人取消待审申请")
async def cancel_application(id: ObjectId, auth: Auth):
    return SuccessResponse(data=await AssetService(auth).cancel(id))


@AssetRouter.post("/application/complete-repair/{id}", summary="登记维修完成")
async def complete_repair(id: ObjectId, data: RepairComplete, auth: Auth):
    return SuccessResponse(data=await AssetService(auth).complete_repair(id, data.completion_note))


@AssetRouter.post("/loan/handover/{id}", summary="管理员确认资产交付")
async def handover_loan(id: ObjectId, data: HandoverInput, auth: Auth):
    return SuccessResponse(data=await AssetService(auth).handover(id, data.note))


@AssetRouter.post("/loan/receive/{id}", summary="领用人本人签收资产")
async def receive_loan(id: ObjectId, auth: Auth):
    return SuccessResponse(data=await AssetService(auth).receive(id))


@AssetRouter.post("/loan/cancel-handover/{id}", summary="撤销待交付资产")
async def cancel_loan_handover(id: ObjectId, data: CancelHandoverInput, auth: Auth):
    return SuccessResponse(data=await AssetService(auth).cancel_handover(id, data.reason))


@AssetRouter.post("/item/retire/{id}", summary="报废在库或维修中的资产")
async def retire_item(id: ObjectId, data: RetireInput, auth: Auth):
    return SuccessResponse(data=await AssetService(auth).retire(id, data.row_version))


@AssetRouter.get("/audit/list", summary="查询资产业务审计")
async def list_audit(
    auth: Auth,
    page_no: Page = 1,
    page_size: Size = 20,
    asset_id: Annotated[int | None, Query(gt=0)] = None,
    keyword: Annotated[str | None, Query(max_length=128)] = None,
):
    return SuccessResponse(
        data=await AssetService(auth).listing(
            "audit", page_no, page_size, asset_id=asset_id, keyword=keyword
        )
    )


@AssetRouter.get("/dashboard/summary", summary="资产状态概览")
async def dashboard(auth: Auth):
    return SuccessResponse(data=await AssetService(auth).summary())


@AssetRouter.get("/dashboard/monitoring", summary="读取本租户允许展示的 Watch 运行状态")
async def monitoring(auth: Auth):
    service = AssetService(auth)
    await service.require("dashboard:query")
    snapshot = await watch_adapter.snapshot(service.tenant_id)
    return SuccessResponse(data=snapshot.model_dump(mode="json"))
