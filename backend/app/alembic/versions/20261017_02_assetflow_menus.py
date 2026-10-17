"""Register AssetFlow pages, permissions and unassigned business roles."""

from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa

from alembic import op

revision = "20261017_02"
down_revision = "20261017_01"
branch_labels = None
depends_on = None


def identity(kind, key):
    return str(uuid5(NAMESPACE_URL, f"sanas.assetflow/{kind}/{key}"))


# Frozen seed definitions: never import runtime schemas or application models.
PAGES = (
    ("root", "资产管理", 1, None, "AssetFlowRoot", "/asset", None, None),
    (
        "overview",
        "资产概览",
        2,
        "dashboard:query",
        "AssetOverview",
        "/asset/overview",
        "module_asset/overview/index",
        "root",
    ),
    (
        "items",
        "资产目录",
        2,
        "item:query",
        "AssetItems",
        "/asset/items",
        "module_asset/items/index",
        "root",
    ),
    (
        "applications",
        "申请与审批",
        2,
        "application:query",
        "AssetApplications",
        "/asset/applications",
        "module_asset/applications/index",
        "root",
    ),
    (
        "audit",
        "业务审计",
        2,
        "audit:query",
        "AssetAudit",
        "/asset/audit",
        "module_asset/audit/index",
        "root",
    ),
)
PAGE_ICONS = {
    "root": "ri:archive-drawer-line",
    "overview": "ri:pie-chart-line",
    "items": "ri:archive-2-line",
    "applications": "ri:file-list-3-line",
    "audit": "ri:history-line",
}
BUTTONS = (
    ("category_query", "查询分类", "category:query", "items"),
    ("category_create", "新增分类", "category:create", "items"),
    ("item_create", "登记资产", "item:create", "items"),
    ("item_manage", "报废及维修完成", "item:manage", "items"),
    ("application_create", "提交申请", "application:create", "applications"),
    ("application_cancel", "取消本人申请", "application:cancel", "applications"),
    ("application_approve", "批准申请", "application:approve", "applications"),
    ("application_reject", "驳回申请", "application:reject", "applications"),
)
ROLE_SPECS = (
    (
        "asset_employee",
        "资产员工",
        1,
        {
            "root",
            "overview",
            "items",
            "applications",
            "category_query",
            "application_create",
            "application_cancel",
        },
    ),
    ("asset_manager", "资产管理员", 2, {p[0] for p in PAGES} | {b[0] for b in BUTTONS}),
)


def tables():
    if op.get_context().as_sql:
        raise RuntimeError(
            "AssetFlow menu registration requires an online connection for collision checks."
        )
    connection = op.get_bind()
    metadata = sa.MetaData()
    return connection, {
        name: sa.Table(name, metadata, autoload_with=connection)
        for name in ("sys_menu", "sys_role", "sys_role_menus", "sys_user_roles")
    }


def upgrade() -> None:
    connection, schema = tables()
    menu, role, links = (schema[name] for name in ("sys_menu", "sys_role", "sys_role_menus"))
    definitions = [
        {
            "key": key,
            "name": name,
            "type": kind,
            "permission": f"module_asset:{permission}" if permission else None,
            "route_name": route_name,
            "route_path": path,
            "component_path": component,
            "parent": parent,
        }
        for key, name, kind, permission, route_name, path, component, parent in PAGES
    ] + [
        {
            "key": key,
            "name": name,
            "type": 3,
            "permission": f"module_asset:{permission}",
            "route_name": None,
            "route_path": None,
            "component_path": None,
            "parent": parent,
        }
        for key, name, permission, parent in BUTTONS
    ]
    # Validate every collision before inserting any record; preserve manually configured rows.
    existing_menus = {}
    for definition in definitions:
        expected_uuid = identity("menu", definition["key"])
        conditions = [menu.c.uuid == expected_uuid]
        for field in ("permission", "route_name", "route_path"):
            if definition[field]:
                conditions.append(menu.c[field] == definition[field])
        rows = connection.execute(sa.select(menu).where(sa.or_(*conditions))).mappings().all()
        if any(row["uuid"] != expected_uuid for row in rows):
            raise RuntimeError(f"Existing menu conflicts with AssetFlow: {definition['key']}")
        existing_menus[definition["key"]] = rows[0]["id"] if rows else None
    existing_roles = {}
    for code, _, _, _ in ROLE_SPECS:
        found = connection.execute(sa.select(role).where(role.c.code == code)).mappings().first()
        if found and found["uuid"] != identity("role", code):
            raise RuntimeError(f"Existing role conflicts with AssetFlow: {code}")
        existing_roles[code] = found["id"] if found else None
    now = datetime.now()
    common = {
        "status": "0",
        "is_deleted": False,
        "created_time": now,
        "updated_time": now,
        "description": "Sanas AssetFlow menu seed 20261017_02",
    }
    for order, definition in enumerate(definitions, 1):
        key = definition["key"]
        if existing_menus[key] is None:
            values = {
                field: definition[field]
                for field in (
                    "name",
                    "type",
                    "permission",
                    "route_name",
                    "route_path",
                    "component_path",
                )
            }
            result = connection.execute(
                menu.insert().values(
                    **common,
                    **values,
                    uuid=identity("menu", key),
                    order=15 if key == "root" else order,
                    parent_id=existing_menus.get(definition["parent"]),
                    client="pc",
                    redirect="/asset/overview" if key == "root" else None,
                    icon=PAGE_ICONS.get(key),
                    hidden=False,
                    keep_alive=False,
                    always_show=key == "root",
                    affix=False,
                    title=definition["name"],
                )
            )
            existing_menus[key] = result.inserted_primary_key[0]
    for code, name, scope, keys in ROLE_SPECS:
        role_id = existing_roles[code]
        if role_id is None:
            result = connection.execute(
                role.insert().values(
                    **common,
                    uuid=identity("role", code),
                    code=code,
                    name=name,
                    order=20,
                    data_scope=scope,
                )
            )
            role_id = result.inserted_primary_key[0]
        assigned = set(
            connection.scalars(sa.select(links.c.menu_id).where(links.c.role_id == role_id))
        )
        for key in sorted(keys):
            if existing_menus[key] not in assigned:
                connection.execute(
                    links.insert().values(role_id=role_id, menu_id=existing_menus[key])
                )
    # Existing users and user-role bindings are deliberately not part of this seed.


def downgrade() -> None:
    connection, schema = tables()
    menu, role, links, users = (
        schema[name] for name in ("sys_menu", "sys_role", "sys_role_menus", "sys_user_roles")
    )
    keys = [page[0] for page in PAGES] + [button[0] for button in BUTTONS]
    menu_ids = list(
        connection.scalars(
            sa.select(menu.c.id).where(menu.c.uuid.in_([identity("menu", key) for key in keys]))
        )
    )
    role_ids = list(
        connection.scalars(
            sa.select(role.c.id).where(
                role.c.uuid.in_([identity("role", spec[0]) for spec in ROLE_SPECS])
            )
        )
    )
    if connection.execute(sa.select(users).where(users.c.role_id.in_(role_ids)).limit(1)).first():
        raise RuntimeError("AssetFlow roles are assigned to users; unassign them before downgrade.")
    if connection.execute(
        sa
        .select(links)
        .where(
            sa.or_(
                sa.and_(links.c.menu_id.in_(menu_ids), links.c.role_id.not_in(role_ids)),
                sa.and_(links.c.role_id.in_(role_ids), links.c.menu_id.not_in(menu_ids)),
            )
        )
        .limit(1)
    ).first():
        raise RuntimeError("AssetFlow menu grants were customized; review them before downgrade.")
    if connection.execute(
        sa
        .select(menu.c.id)
        .where(menu.c.parent_id.in_(menu_ids), menu.c.id.not_in(menu_ids))
        .limit(1)
    ).first():
        raise RuntimeError("AssetFlow menus contain custom children; review them before downgrade.")
    connection.execute(links.delete().where(links.c.role_id.in_(role_ids)))
    connection.execute(role.delete().where(role.c.id.in_(role_ids)))
    for key in reversed(keys):
        connection.execute(menu.delete().where(menu.c.uuid == identity("menu", key)))
