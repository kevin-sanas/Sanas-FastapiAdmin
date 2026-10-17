# Sanas AssetFlow P0 数据库设计

> 状态：2026-10-17 已实现六张业务表、17 个后端 API，以及资产概览、资产目录、申请审批、业务审计四个前端页面。最新迁移版本为 `20261017_03`，菜单和独立业务角色已注册。基线：FastApiAdmin `v3.0` / `362f005924700157b390b1224142b3cfa276f426`；使用现有开发库 `fastapiadmin`，没有创建额外数据库。

## 1. 范围与关键规则

- P0 管理单件实物资产、分类、领用/归还/维修申请、单人单步审批、业务审计和看板统计。
- 一条资产申请只针对一件资产；多资产批量申请、库存 SKU/仓库、可配置多级审批属于后续范围。
- 提交申请只创建 `PENDING` 记录，不占用或改变资产。审批批准时才在同一事务中转换资产及申请状态并写审批和审计记录。
- 业务表复用 `ModelMixin` 的 id、uuid、软删除和创建/更新时间；复用 `TenantMixin`、`UserMixin`。框架 `status` 表示记录可用性，不承载资产/申请业务状态。
- 所有业务读取和写入都要按当前租户约束；用户、部门引用需要验证归属及可用性。审批接口后端必须校验权限，不能依赖前端隐藏按钮。
- 用户已确认：同一租户共享资产目录；普通员工只能查询自己的申请；审批人按接口权限及活动角色的数据范围查询和处理申请。资产目录不按记录创建人过滤。所有资产状态变更仍须校验相应业务操作权限。
- 申请人只可为本人提交领用/归还/维修申请；P0 为单级审批。审批人必须拥有相应后端权限，并且不得审批自己提交的申请。

## 2. 领域状态

### 资产状态 `asset_state`

| 状态 | 含义 | 允许的主要转移 |
|---|---|---|
| `AVAILABLE` | 在库，可申请领用 | 领用批准 → `RESERVED`；管理员报废 → `RETIRED` |
| `RESERVED` | 领用已批准，等待交付与签收 | 员工签收 → `IN_USE`；管理员撤销交付 → `AVAILABLE` |
| `IN_USE` | 由一名保管人领用 | 归还批准 → `AVAILABLE`；维修批准 → `MAINTENANCE` |
| `MAINTENANCE` | 维修中，不可领用 | 维修完成 → `AVAILABLE`；管理员报废 → `RETIRED` |
| `RETIRED` | 已报废，终态 | 无 |

### 申请状态 `application_state`

普通申请：`PENDING → APPROVED / REJECTED / CANCELLED`。仅申请人可取消尚未审批的申请。

维修申请：批准后资产进入 `MAINTENANCE`，申请暂留 `APPROVED`；维修完成操作将申请改为 `COMPLETED` 并将资产转为 `AVAILABLE`。只有维修申请允许 `APPROVED → COMPLETED`。

| 申请类型 | 提交时资产前置状态 | 批准时原子结果 |
|---|---|---|
| `ISSUE` 领用 | `AVAILABLE` | `RESERVED`，新建待交付领用记录；员工签收后进入 `IN_USE` 并成为保管人 |
| `RETURN` 归还 | `IN_USE`，申请人为当前保管人 | 管理员填写验收记录后变为 `AVAILABLE`，清空保管人并完结关联领用记录 |
| `REPAIR` 维修 | `AVAILABLE` 或 `IN_USE` | `MAINTENANCE`，清空保管人 |

提交与审批之间资产可能被其他操作改变；批准时必须再次检查当前状态，过期申请不能覆盖较新的资产状态。

领用记录 `asset_loan.loan_state` 为 `PENDING_HANDOVER → PENDING_RECEIPT → IN_USE → COMPLETED`。管理员可在待交付或待签收时撤销，转为 `CANCELLED` 并释放资产。被驳回的归还申请保留领用中状态；历史领用补录为 `is_legacy=1`，交付与签收时间未知，不推测。

## 3. 表结构建议

字段类型为逻辑类型，落实时按 SQLAlchemy 2 与 MySQL 当前驱动映射；主表继承字段不重复列出。

### `asset_category` — 资产分类

| 字段 | 类型 | 约束/说明 |
|---|---|---|
| `code` | `String(64)` | 必填；与 `tenant_id` 组成唯一键 |
| `name` | `String(128)` | 必填；列表搜索索引按实际查询补充 |
| `parent_id` | `Integer?` | 自引用 `asset_category.id`，删除父分类限制有子分类 |
| `sort_order` | `Integer` | 默认 0 |

继承 `ModelMixin`、`TenantMixin`、`UserMixin`。分类被资产引用时禁止物理删除；默认使用软删除，并阻止新资产选择已删除分类。

### `asset_item` — 单件资产

| 字段 | 类型 | 约束/说明 |
|---|---|---|
| `asset_code` | `String(64)` | 必填；`(tenant_id, asset_code)` 唯一，编码不回收 |
| `name` | `String(128)` | 必填 |
| `category_id` | `Integer` | FK `asset_category.id`，必填 |
| `asset_state` | `String(20)` | `AVAILABLE` / `RESERVED` / `IN_USE` / `MAINTENANCE` / `RETIRED` |
| `custodian_id` | `Integer?` | FK `sys_user.id`；仅 `IN_USE` 时非空 |
| `custodian_dept_id` | `Integer?` | FK `sys_dept.id`；仅 `IN_USE` 时非空，由服务层验证部门关系 |
| `row_version` | `Integer` | 默认 1；每次有效状态/责任变更递增，用于比较并交换 |
| `purchase_date` | `Date?` | 可选 |
| `purchase_amount` | `Numeric(12,2)?` | 可选；不得使用浮点数表示金额 |

继承 `ModelMixin`、`TenantMixin`、`UserMixin`。索引：`(tenant_id, asset_state, is_deleted)`、`(tenant_id, category_id)`、`(tenant_id, custodian_id)`。`asset_state` 与框架 `status` 不可混用。将来若需要维持“资产与分类同租户”的数据库级约束，可考虑复合外键；P0 先由服务验证引用租户，避免引入额外复合键复杂度。

### `asset_application` — 资产申请

| 字段 | 类型 | 约束/说明 |
|---|---|---|
| `request_no` | `String(64)` | 必填；`(tenant_id, request_no)` 唯一 |
| `asset_id` | `Integer` | FK `asset_item.id`，必填 |
| `applicant_id` | `Integer` | FK `sys_user.id`，必填 |
| `application_type` | `String(16)` | `ISSUE` / `RETURN` / `REPAIR` |
| `application_state` | `String(16)` | `PENDING` / `APPROVED` / `REJECTED` / `CANCELLED` / `COMPLETED` |
| `reason` | `Text` | 申请理由；长度在 API 层限制 |
| `idempotency_key` | `String(128)` | 创建申请请求键；`(tenant_id, applicant_id, idempotency_key)` 唯一 |
| `asset_version_at_submit` | `Integer` | 提交时版本，供审批时识别期间变更；不能替代批准时的 CAS |
| `loan_id` | `Integer?` | FK `asset_loan.id`；批准后的领用申请及其归还申请共用同一笔领用记录 |
| `completed_at` | `DateTime?` | 维修完成时间 |
| `completion_note` | `Text?` | 维修完成备注 |

继承 `ModelMixin`、`TenantMixin`、`UserMixin`。主要索引：`(tenant_id, application_state, created_time)`、`(tenant_id, applicant_id, created_time)`、`(tenant_id, asset_id, application_state)`。重复请求键若对应相同申请内容则返回原申请；键相同但内容不同返回幂等冲突。

### `asset_loan` — 领用闭环

每笔批准的领用申请对应一条领用记录，保存资产、申请、领用人、当前进度、批准/交付/签收/验收时间，以及交付说明、验收记录、完结或撤销原因。`(tenant_id, issue_application_id)` 唯一。新记录批准时为待交付；管理员确认交付后待本人签收；签收时资产才记为领用中；归还验收后标记完结。旧数据标记 `is_legacy`，保留未知历史环节。

### `asset_approval` — 单步审批决定

| 字段 | 类型 | 约束/说明 |
|---|---|---|
| `application_id` | `Integer` | FK `asset_application.id`；每申请最多一条终局决定，唯一 |
| `reviewer_id` | `Integer` | FK `sys_user.id`，必填 |
| `decision` | `String(16)` | `APPROVE` / `REJECT` |
| `review_note` | `Text?` | 驳回理由必填；批准意见可选 |
| `reviewed_at` | `DateTime` | 决定时间 |
| `idempotency_key` | `String(128)?` | 可选审批请求键；唯一范围按 `(tenant_id, idempotency_key)` |

继承 `ModelMixin`、`TenantMixin`。拒绝理由、申请状态及审批决定在同一事务提交。已存在审批决定时禁止覆盖；重复同键请求可返回既有结果。

### `asset_audit_log` — 业务审计记录

| 字段 | 类型 | 约束/说明 |
|---|---|---|
| `asset_id` | `Integer` | FK `asset_item.id`，必填 |
| `application_id` | `Integer?` | FK `asset_application.id`，审批/申请动作时填写 |
| `actor_id` | `Integer?` | FK `sys_user.id`；系统动作可为空 |
| `action` | `String(32)` | 如 `ASSET_CREATED`、`ISSUE_APPROVED`、`RETURN_APPROVED`、`REPAIR_COMPLETED`、`ASSET_RETIRED` |
| `before_json` | `JSON?` | 变更前的必要业务字段快照 |
| `after_json` | `JSON?` | 变更后的必要业务字段快照 |

继承 `ModelMixin`、`TenantMixin`。按 `(tenant_id, asset_id, created_time)`、`(tenant_id, application_id)` 索引。记录采用追加写入，不提供编辑/删除 API；快照只记录业务所需字段与 ID，不复制用户凭据或不必要个人信息。

## 4. 约束、事务与并发

### 数据库约束

- `asset_category`: `UNIQUE (tenant_id, code)`。
- `asset_item`: `UNIQUE (tenant_id, asset_code)`；FK 分类、保管人、部门；软删除记录仍占用编码，避免历史编码重用。
- `asset_application`: `UNIQUE (tenant_id, request_no)`、`UNIQUE (tenant_id, applicant_id, idempotency_key)`；FK 资产和申请人。
- `asset_loan`: `UNIQUE (tenant_id, issue_application_id)`；FK 资产、领用申请和领用人。
- `asset_approval`: `UNIQUE (tenant_id, application_id)`、`UNIQUE (tenant_id, idempotency_key)`；FK 申请和审批人。
- 所有关联删除默认 `RESTRICT` 或保留软删除语义，避免删除资产后失去审批、审计关联。
- MySQL 唯一键受列长度、字符集与排序规则影响；实施时检查库字符集/索引长度并验证 ORM 自动命名和 DDL。

### 批准事务

批准接口复用同一个 `AuthSchema.db` / 请求 `AsyncSession`，由 `db_getter()` 的 `session.begin()` 统一提交/回滚。Service 按以下顺序执行：

1. 校验申请租户、当前为 `PENDING`、申请人和审批人不同、审批权限有效。
2. 条件更新申请：仅将 `PENDING` 更新为批准/驳回目标；更新行数不是 1 即视为竞争或非法状态。
3. 对批准动作使用资产 CAS：条件包含资产 ID、租户、预期 `asset_state`、`row_version` 和未软删除；更新状态、保管人并令 `row_version = row_version + 1`。更新行数不是 1 时抛业务冲突，整个事务回滚。
4. 写入唯一审批决定和业务审计快照；CAS 或唯一约束冲突均回滚以上更新。
5. 返回确定的业务错误码，例如 `APPLICATION_ALREADY_PROCESSED`、`ASSET_STATE_CONFLICT`、`IDEMPOTENCY_KEY_REUSED`，不把 SQL/驱动异常直接返回客户端。

驳回只更新申请状态、审批和审计，不改变资产。维修完成按 `asset_state=MAINTENANCE` 与当前版本做 CAS，再将申请改为 `COMPLETED`、资产改为 `AVAILABLE`、写审计。事务保证不会出现“批准但未占用”或“资产已变更但无审计”。

## 5. P0 接口映射

以下 17 个接口通过动态插件扫描注册，复用现有响应、登录依赖与服务端权限校验：

| 方法 | 路径建议 | 行为 |
|---|---|---|
| `GET` | `/api/v1/asset/category/list` | 按租户查询分类 |
| `POST` | `/api/v1/asset/category/create` | 创建分类 |
| `GET` | `/api/v1/asset/item/list` | 分页/过滤资产 |
| `POST` | `/api/v1/asset/item/create` | 建立资产档案 |
| `GET` | `/api/v1/asset/item/detail/{id}` | 资产详情及申请摘要 |
| `POST` | `/api/v1/asset/application/create` | 提交领用、归还或维修申请；要求幂等键 |
| `GET` | `/api/v1/asset/application/list` | 按申请人/状态/类型查询 |
| `POST` | `/api/v1/asset/application/approve/{id}` | 批准并执行状态转换 |
| `POST` | `/api/v1/asset/application/reject/{id}` | 驳回并记录原因 |
| `POST` | `/api/v1/asset/application/cancel/{id}` | 申请人取消待审申请 |
| `POST` | `/api/v1/asset/application/complete-repair/{id}` | 完成维修并恢复在库 |
| `POST` | `/api/v1/asset/loan/handover/{id}` | 管理员确认交付，填写交付说明 |
| `POST` | `/api/v1/asset/loan/receive/{id}` | 领用人本人签收，资产正式进入领用中 |
| `POST` | `/api/v1/asset/loan/cancel-handover/{id}` | 管理员撤销未签收的交付并释放资产 |
| `POST` | `/api/v1/asset/item/retire/{id}` | 管理员报废在库或维修中的资产 |
| `GET` | `/api/v1/asset/audit/list` | 分页查询业务审计 |
| `GET` | `/api/v1/asset/dashboard/summary` | 按租户及数据权限汇总资产状态 |

服务端权限字符串、菜单和页面已登记。业务冲突返回 HTTP 409，`data.reason` 标识具体原因；权限不足返回 403，不存在或不在数据范围的对象返回 404。资产和分类列表支持关键字搜索，资产列表可按分类/状态过滤，审计列表可按资产筛选；查询返回资产、分类、人员名称及审批意见，便于前端展示。

## 6. 实施决定与剩余边界

1. **维修与报废**：按 P0 设计采用 `module_asset:item:manage` 权限手动完成维修或报废，维修必须填写完成备注；报废只允许在库或维修中的资产。未引入维修工单或独立报废审批流。
2. **租户**：租户 ID 和操作人从已认证用户提取，输入模型禁止额外字段，客户端不能传入租户、保管人或资产初始状态。业务外键引用先按租户校验；`sys_dept` 本身没有租户字段，领用部门从同租户有效申请人的 `dept_id` 读取。跨租户引用的数据库级复合外键尚未加入。
3. **时间**：沿用上游 `datetime.now()` 及不带时区的 `DateTime`，输出遵循框架格式；服务部署需保持统一时区。多时区部署前仍需明确 UTC 转换方案。
4. **迁移**：首个业务版本为 `20261017_01`，仅管理五张 `asset_*` 表，依赖上游系统表已存在。修复了迁移入口重置元数据导致缓存模型遗漏的问题。业务表标记 `migration_managed`，启动时的 `create_all()` 跳过这些表，确保必须执行迁移。
5. **升级与回退**：升级前检查系统表与已有资产表，避免覆盖已有结构；降级前检查全部业务表是否为空，有数据时拒绝降级。本次验证了离线升降级 SQL及降级保护，没有在实际开发库执行删除表的降级。
6. **幂等与一致性**：请求键在 MySQL 使用 `utf8mb4_bin` 区分大小写；审批锁定申请和资产后执行版本条件更新。业务服务使用请求 `AsyncSession` 和保存点，任何后续审批/审计异常会撤销本次命令的全部变更。
7. **角色与界面**：迁移 `20261017_02` 新增 13 个菜单/权限节点及两个独立角色；保留现有用户与用户角色绑定。`asset_employee`（资产员工）可查询租户目录并管理本人申请，数据范围为本人；`asset_manager`（资产管理员）可登记、审批、维修完成、报废和审计，审批数据范围默认为本部门。通过系统管理给用户分配相应角色后，重新登录生效。两种角色均不能审批本人申请。
8. **此前验证范围**：`20261017_02` 阶段曾完成后端测试、前端规范检查、构建及浏览器操作验证；本次领用闭环改动的验证结果另见下文，不沿用旧结果。

## 7. 改动位置与验证结果

| 文件 | 作用 |
|---|---|
| `backend/app/plugin/module_asset/model.py`、`enums.py` | 六张业务表、业务状态枚举、外键、唯一键、CHECK 和查询索引 |
| `backend/app/plugin/module_asset/schema.py` | 输入约束；租户及生命周期字段禁止由客户端注入 |
| `backend/app/plugin/module_asset/service.py` | 分类/资产登记、共享目录、申请、审批、归还、维修、报废、审计和统计 |
| `backend/app/plugin/module_asset/controller.py` | 按上游扫描规则注册 17 个 API，复用登录依赖、响应和操作日志路由 |
| `backend/app/alembic/versions/20261017_01_assetflow_tables.py` | 独立、固定的升降级结构快照及保护，不导入未来可变 ORM 定义 |
| `backend/app/alembic/env.py`、`backend/app/core/database.py` | 保留已注册元数据；首次启动跳过迁移管理的业务表 |
| `backend/tests/test_asset_models.py` | 模型/迁移、真实 MySQL 约束、业务服务、HTTP 和并发检查 |
| `backend/app/alembic/versions/20261017_02_assetflow_menus.py` | 菜单、权限及未绑定用户的独立角色；检查同名冲突及回退引用 |
| `backend/app/alembic/versions/20261017_03_asset_loan.py` | 新建领用闭环记录并关联旧申请；历史交付与签收时间保持未知 |
| `frontend/web/src/api/module_asset/asset.ts` | 类型化资产 API、状态显示词典 |
| `frontend/web/src/views/module_asset/` | 四个业务页面及共用页面布局；表单校验、权限按钮、加载与失败状态 |

此前 `20261017_02` 阶段后端完整测试目录结果：**37 项通过，0 跳过**，其中资产模块 27 项、健康探针 10 项。覆盖重复资产编码（含软删除）、非法资产字段、申请幂等及键冲突、同申请重复审批、驳回原因、申请人自审/普通用户越权、跨租户查询、本人申请隔离、停用角色的数据范围、领用归还维修链路、审计失败回滚、两笔并发审批竞争同一资产、HTTP 申请/审批、关键字转义与展示字段、菜单注册幂等和员工权限集合。新增旧申请版本冲突、同键并发提交/审批及分页查询次数回归检查。

自动化 HTTP 用例通过测试认证上下文调用真实控制器和服务。另通过上游自带快速登录建立真实浏览器会话，完成以下验证：超级管理员登记分类/资产；临时员工查看共享目录、提交领用且看不到管理/审批操作；管理员批准后保管人更新并生成审计；驳回原因必填并能由申请人读取。未验证密码/验证码登录和 Redis 令牌刷新。OpenAPI 包含 14 个资产路由，未登录访问资产列表返回 401。

升级前后原有 27 张表的结构指纹及记录数量一致。结构比较未发现五张资产表与 ORM 之间的差异；检查完成后五张资产表均为空，模拟用户剩余数为 0。普通测试事务回滚；并发用例仅短暂提交自己生成的数据，结束时按主键清理。

浏览器检查覆盖桌面及 390px 手机宽度，确认审批弹窗可操作且页面没有横向溢出；新页面使用现有主题变量，支持浅色和深色主题。临时员工、分类、资产、申请及其测试会话均已清理，浏览器已恢复管理员会话。上游远程 Logo 图片的加载错误仍可见，未改动其站点资源配置。

## 8. 运行与复现

在仓库的 `backend` 目录安装依赖、配置 `env/.env.dev` 后执行：

```powershell
$env:PYTHONIOENCODING = 'utf-8'
$env:ENVIRONMENT = 'dev'
# 上游系统表需先完成首次初始化；本机开发库已完成。
.\.venv\Scripts\python.exe main.py upgrade --env=dev
.\.venv\Scripts\python.exe main.py run --env=dev
```

Swagger：<http://127.0.0.1:8001/api/v1/docs>；接口前缀 `/api/v1/asset`。需本机 MySQL 与 Redis 可用，配置沿用 Git 忽略的 `backend/env/.env.dev`。

前端在 `frontend/web` 目录执行 `corepack pnpm dev --host 127.0.0.1`，访问 <http://127.0.0.1:5180/web#/asset/overview>。已有登录会话可能缓存旧菜单，重新登录后在“资产管理”下查看四个页面。普通用户由超级管理员在“系统管理 → 用户管理”分配“资产员工”或“资产管理员”角色；迁移不会自动给现有用户绑定这些角色。

本机生产构建命令（覆盖上游远程默认地址）：

```powershell
$env:VITE_API_BASE_URL = 'http://127.0.0.1:8001'
$env:VITE_APP_WS_ENDPOINT = 'ws://127.0.0.1:8001'
corepack pnpm run build
```

产物在 `frontend/web/dist`。静态托管时路径为 `/web`，需要把 `/api/v1` 反向代理到后端；本轮没有对外部署。已对新增前端文件执行 ESLint、Stylelint、Prettier 检查；`build` 包含完整 `vue-tsc --noEmit`。

针对性检查：

```powershell
$env:ASSETFLOW_MYSQL_TESTS = '1'
.\.venv\Scripts\python.exe -m pytest tests/test_asset_models.py -q
```

此命令会在当前开发库执行可回滚的模拟数据检查；并发用例短暂提交并清理自身数据。未显式设置该变量时只运行不连接数据库的检查，MySQL 用例跳过。不要指向生产库。

菜单迁移须在线连接数据库检查已有配置冲突，不支持离线生成完整 `head` SQL；结构迁移本身可单独生成 `20261017_01` 的离线 SQL。菜单回退遇到已绑定用户的业务角色、自定义授权或自定义子菜单时拒绝执行，以保留用户配置；本轮未对实际库执行回退。

服务权限包括 `module_asset:category:query/create`、`module_asset:item:query/create/manage`、`module_asset:application:create/query/approve/reject/cancel`、`module_asset:audit:query` 和 `module_asset:dashboard:query`；斜线表示多个独立权限字符串。所有写操作仍由服务端单独检查相应权限。

## 9. 工程质量阶段

仓库根目录提供 `check_assetflow.ps1`，使用现有后端虚拟环境和 Corepack，无需创建额外数据库。脚本失败立即停止，并在退出时恢复调用前的工作目录和相关进程环境变量；不执行代码自动修复、迁移、服务启动、提交或发布。

```powershell
# 从仓库根目录执行
# 默认：不访问 MySQL；后端测试 16 通过、21 跳过，再检查前端规范与类型。
.\check_assetflow.ps1

# 完整本机检查：启用开发库、构建，并检查已运行的服务。
.\check_assetflow.ps1 -WithMySQL -Build -ServiceUrl http://127.0.0.1:8001
```

- 后端 Ruff 范围为资产插件、迁移、修改的基础设施、健康探针与整个测试目录；前端规范范围为新增资产 API 和五个 Vue 文件，全前端类型检查由 `vue-tsc` 执行。
- `-WithMySQL` 使用 `.env.dev` 和进程环境指定的现有开发库。普通用例回滚，并发用例按自己创建的主键清理数据；不要指向生产库。未指定时，即使调用进程已设置 `ASSETFLOW_MYSQL_TESTS=1`，脚本仍主动关闭数据库用例。
- `-Build` 默认将 API 和 WebSocket 地址指向 `127.0.0.1:8001`，产物为 `frontend/web/dist`；其他目标可用 `-ApiBaseUrl https://example.com` 指定。构建和前端开发继续使用同一个已安装的依赖目录。没有部署动作。
- `-ServiceUrl` 只读检查存活、就绪和未登录资产列表，预期分别为 200、200、401；不配置该参数便不连接运行服务，且检查请求绕过系统代理。
- `-Python` 可指定其他已安装项目依赖的解释器；默认使用 `backend/.venv/Scripts/python.exe`。

2026-10-17 的领用闭环验收经 Web 页面完成申请、审批、交付、签收、归还与验收；数据库核对同一领用记录的关联、状态和 7 条业务审计后，已清理本次专用数据。项目检查脚本在现有开发库下报告后端 37 个用例通过、1 条 SQLAlchemy 外键排序警告；前端格式、静态检查和类型检查通过。页面验收使用开发环境快捷登录切换测试角色，不覆盖密码和验证码登录。

修复上游 `tests/test_main.py` 缺少 `test_client` 的问题。健康探针测试使用真实路由及可控的数据库/Redis 替身，不运行应用初始化或调度器，不连接真实依赖。覆盖正常状态、单项故障、缺少 Redis、关闭依赖和探测超时；探针故障返回 503，而存活检查继续返回 200。实际依赖是否可达另由在线检查确认。

健康探针的数据库和 Redis 探测分别设置 3 秒超时，异常响应只返回稳定的故障标识，日志记录异常类型，避免回传驱动错误中的连接信息；存活响应的 OpenAPI 类型改为布尔值，与实际返回一致。未模拟断开或停止本机正在使用的数据库/Redis。

新增三项资产回归检查：资产领用后归还，旧申请即使遇到再次在库也因版本过期而不能批准；两个独立连接并发重试同一请求键，只生成一份申请、一份审批及对应审计；资产、申请、审计列表的页大小从 1 调整为 100，均为两次 SQL 往返（计数与数据）。查询次数检查使用 12 条模拟资产并回滚，不代表大规模容量、响应延迟或数据库内部扫描成本。

资产状态与看板统计仍从 MySQL 实时读取，未加入 Redis 业务缓存。现阶段没有测得需要缓存的查询瓶颈；Redis 继续承载上游会话等基础能力。未计算测试覆盖率，未执行容量压测或 Docker 部署，不提供相应指标。

## 10. Sanas Watch 只读联动（2026-10-17）

监控链路为 Watch HTTP 探测 → AssetFlow 存活/就绪接口；展示链路为资产概览 → AssetFlow 自身认证接口 → 后端读取 Watch `/metrics`。不读取另一项目的 SQLite，不在浏览器保存 Watch 密钥，不新增数据库或表。

- `backend/app/plugin/module_asset/monitoring.py` 使用现有 HTTPX 与 Prometheus 文本解析器。解析器已安装且已锁定为 `prometheus-client==0.24.1`，此次将它补为显式生产依赖；依赖锁检查通过，无需重新安装本机依赖。
- 新接口 `GET /api/v1/asset/dashboard/monitoring` 复用登录及 `module_asset:dashboard:query` 权限。仅按当前用户租户读取服务端配置的监控编号及本地展示名称，不接受浏览器传入上游地址、监控编号或租户。未配置租户返回 `not_configured`，不返回其他租户的状态。
- `frontend/web/src/views/module_asset/components/WatchStatus.vue` 在资产概览展示状态、本次成功响应耗时与 24 小时在线率。在线率直接使用上游 `monitor_uptime_ratio{window="1d"}`，按已观测时长计算，不等同于扩展面板的按探测次数统计成功率。无样本为未知，失败时不将旧响应耗时显示为本次成功耗时。
- 同一后端进程每 15 秒最多拉取一次，合并并发刷新；失败也缓存 15 秒。总拉取时间限制 3 秒，解压后响应上限 1 MiB，禁用环境代理和重定向，非本机地址默认要求 HTTPS。部署准备阶段新增默认关闭的 `SANAS_WATCH_ALLOW_INSECURE_HTTP`，仅为管理员明确配置的可信容器网络提供 HTTP 例外。错误仅记录异常类型，不回传原始指标、目标 URL、上游标签或密钥。
- 返回 `disabled / not_configured / live / stale / unavailable`。故障时保留最多 5 分钟的成功快照，页面明确标记为上次状态，超过期限清空旧状态。`fetched_at` 是 UTC 指标读取时间，不是每个监控的最后心跳时间；`live` 表示本次指标源读取成功，具体监控仍可能为 DOWN/PENDING/MAINTENANCE/未知。缓存为进程内缓存，多 worker 各自拉取。

默认关闭联动。部署时在后端 `env/.env.dev`（其他环境使用对应文件）中配置下列字段并重启后端；下列值为配置示意，密钥须在 Watch 的 API Keys 管理中创建并自行填入：

```dotenv
SANAS_WATCH_ENABLED=true
SANAS_WATCH_BASE_URL=http://127.0.0.1:3001
SANAS_WATCH_API_KEY=<专用API密钥>
SANAS_WATCH_MONITORS={"1":{"4":"AssetFlow · 存活","5":"AssetFlow · 就绪"}}
```

监控编号必须以实际 Watch 记录为准，JSON 外层键是 AssetFlow 租户编号。本机已在原 Watch 数据库中配置持续监控 4（`/api/v1/common/health/`）及 5（`/api/v1/common/health/ready/`），间隔 30 秒、超时 10 秒、只接受 200，当前均正常。这是交付后保留的联动配置，不是临时验收数据。专用密钥名 `AssetFlow metrics integration`，有效期至 2027-10-17；只写入已被 Git 忽略的后端环境文件。到期前在 Watch 创建替代密钥、更新后端配置并重启，再撤销旧密钥。未绑定外部通知渠道。

本阶段检查：

- Ruff、改动范围 ESLint/Stylelint/Prettier、完整 `vue-tsc` 与生产构建通过；`uv lock --check --offline --python .venv/Scripts/python.exe` 通过。
- 真实浏览器登录后，新增接口返回 200/live 和监控 4、5，连续请求复用相同读取时间；未登录访问返回 401。返回字段未包含 Watch URL、认证头或密钥。未创建其他租户或普通用户账户进行 HTTP 权限回归。
- 通过隔离进程中的可控读取函数检查解析、非有限延迟、租户投影、10 个并发调用合并为 1 次读取、失败缓存、旧快照到期、首次失败及关闭配置；不连接数据库，不使用真实密钥作为故障用例。此阶段未运行全量资产/MySQL 回归套件。
- 浏览器桌面与 390px 手机宽度下，两项服务均显示正常；手机面板实际宽度与内容宽度均 336px，无内部横向溢出。生产产物仍位于 `frontend/web/dist`，启动方式与前述章节相同。
- 页面控制台仍有上游远程 Logo 图片加载失败（`service.fastapiadmin.com`）记录，未将整页控制台声明为零错误；新增联动接口和面板正常。
- 未停止或故障注入真实 MySQL、Redis、Watch 服务；远端 HTTPS、Docker 跨容器网络和多 worker 尚未实测。Docker 中本机回环地址需按实际服务网络改为可达的地址；远端生产链路需配置 HTTPS。本阶段没有提交、推送或部署。

统一历史清理、大规模性能验证和公开部署仍待后续阶段处理。

本机 Docker 部署入口及构建网络阻塞见 [部署说明](08-deployment-guide.md)。当前开发进程与数据未切换，不能把部署准备作为容器运行验收通过。

## 11. 源码依据

- 基础字段、租户、创建/更新用户：`backend/app/core/base_model.py`（`ModelMixin`、`TenantMixin`、`UserMixin`）。
- 业务示例模型：`backend/app/plugin/module_example/demo/model.py`。
- 请求事务和会话：`backend/app/core/dependencies.py:21-29`（`db_getter`）；审批 Service 应复用 `AuthSchema.db`。
- 权限过滤：`backend/app/core/dependencies.py:236-294`（`AuthPermission`）、`backend/app/core/permission.py`。
- 建表与模型元数据：`backend/app/core/database.py:115-132`；迁移发现：`backend/app/alembic/env.py:17-44`。
- 插件动态发现：`backend/app/core/discover.py`；上游架构和基线细节见 `docs/01-upstream-analysis.md`。

## 12. 可公开的资产演示数据

`backend/app/scripts/seed_assetflow_demo.py` 是独立的开发环境导入入口，不随服务启动自动执行，也不创建数据库或账号。它调用资产模块现有的创建、申请、审批、交付、签收、归还验收、维修完成和报废服务，因此申请状态、保管人和审计记录来自同一套业务规则。数据只引用目标租户已有且启用的两个超级管理员账号；默认 `admin` 提交申请并签收，`super` 审批和交付。仓库中没有账号密码或本机数据库内容。

从 `backend` 目录运行：

```powershell
.\.venv\Scripts\python.exe -m app.scripts.seed_assetflow_demo
.\.venv\Scripts\python.exe -m app.scripts.seed_assetflow_demo --apply
.\.venv\Scripts\python.exe -m app.scripts.seed_assetflow_demo --loan-examples --apply
```

首条命令只预览；第二条写入当前 `.env.dev` 指向的已有开发库。其他租户可指定 `--tenant-id`、`--applicant` 和 `--reviewer`，两个账号必须属于同一租户、具有超级管理员权限，申请人还需有部门。脚本拒绝 `ENVIRONMENT` 为非 `dev` 的运行环境。

这组数据使用固定的 `DEMO-` 编码和 `【演示】` 名称，包括 4 个分类、8 件资产、8 笔申请，展示在库、领用中、维修中、已报废，以及待审、批准、驳回、取消、维修完成等流程。再次运行时，完整数据直接跳过；若只找到部分演示编码或申请键，脚本会停止，保留已有记录和用户之后的操作。导入在一个数据库事务内完成。

追加 `--loan-examples --apply` 会在已有演示分类下新增 `DEMO-2026-009` 和 `DEMO-2026-010` 两件资产及领用申请，分别停在“待管理员交付”和“待员工签收”，方便在页面继续完成操作。它使用独立的 `demo-v2-` 请求键；原有 8 件资产及申请即使已被操作，也不会被覆盖。若追加示例只存在一部分，脚本会停止，不自行修复或重写。
