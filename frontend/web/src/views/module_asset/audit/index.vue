<template>
  <AssetPage title="业务审计" description="追踪资产状态、保管关系和申请处理的变化。">
    <FaSearchBar
      v-model="filters"
      class="asset-search"
      :items="searchItems"
      :show-expand="false"
      @search="search"
      @reset="resetFilters"
    />
    <ElCard shadow="hover" class="fa-table-card asset-table-card">
      <FaTableHeader layout="refresh,size,fullscreen,settings" :loading="loading" @refresh="load">
        <template #left>
          <div class="asset-table-actions">
            <ElTag v-if="assetId" closable @close="clearAsset">{{
              route.query.asset_name || `资产 ${assetId}`
            }}</ElTag>
            <span class="asset-muted">记录资产、申请和保管关系的变更 · 共 {{ total }} 条</span>
          </div>
        </template>
      </FaTableHeader>
      <ElAlert
        v-if="error"
        class="asset-error"
        :title="error"
        type="error"
        show-icon
        :closable="false"
        ><ElButton text @click="load">重试</ElButton></ElAlert
      >
      <FaTable
        :loading="loading"
        :data="rows"
        :pagination="{ current: page, size: 20, total }"
        :pagination-options="{ layout: 'total, prev, pager, next' }"
        empty-text="暂无业务审计，资产登记和状态变更后将在这里留痕"
        @pagination:current-change="onPageChange"
      >
        <ElTableColumn prop="created_time" label="操作时间" width="175" />
        <ElTableColumn label="资产" min-width="200"
          ><template #default="{ row }"
            ><div class="asset-name">{{ row.asset_name }}</div>
            <span class="asset-muted asset-code">{{ row.asset_code }}</span></template
          ></ElTableColumn
        >
        <ElTableColumn label="操作" min-width="135"
          ><template #default="{ row }">{{
            actions[row.action] || row.action
          }}</template></ElTableColumn
        >
        <ElTableColumn label="操作人" min-width="110"
          ><template #default="{ row }">{{ row.actor_name || "系统" }}</template></ElTableColumn
        >
        <ElTableColumn label="变化" min-width="320"
          ><template #default="{ row }">
            <div v-if="changedFields(row).length" class="audit-transition">
              <template v-for="change in changedFields(row).slice(0, 1)" :key="change.key">
                <span class="audit-field">{{ change.label }}</span>
                <ElTag size="small" type="info" effect="plain">{{ change.before }}</ElTag>
                <FaSvgIcon icon="ri:arrow-right-line" class="audit-arrow" />
                <ElTag
                  size="small"
                  :type="statusColor(change.key, change.rawAfter)"
                  effect="light"
                  >{{ change.after }}</ElTag
                >
              </template>
              <ElTooltip
                v-if="changedFields(row).length > 1"
                :content="extraChanges(row)"
                placement="top"
              >
                <ElTag size="small" type="info" effect="plain"
                  >+{{ changedFields(row).length - 1 }} 项</ElTag
                >
              </ElTooltip>
            </div>
            <span v-else class="asset-muted">无状态变更</span>
          </template></ElTableColumn
        >
        <ElTableColumn label="详情" width="90" fixed="right"
          ><template #default="{ row }"
            ><ElTooltip content="查看变更详情" placement="top"
              ><ElButton
                class="asset-icon-action"
                aria-label="查看变更详情"
                @click="
                  selected = row;
                  visible = true;
                "
                ><FaSvgIcon icon="ri:eye-line" /></ElButton></ElTooltip></template
        ></ElTableColumn>
      </FaTable>
    </ElCard>
    <FaDrawer v-model="visible" class="asset-modal" title="变更详情" size="min(620px, 100vw)"
      ><template v-if="selected"
        ><h2>{{ actions[selected.action] || selected.action }}</h2>
        <p>{{ selected.asset_name }}（{{ selected.asset_code }}）</p>
        <p class="asset-muted">{{ selected.actor_name || "系统" }} · {{ selected.created_time }}</p>
        <ElTable
          :data="changedFields(selected)"
          style="margin-top: 24px"
          empty-text="没有可展示的字段变化"
          ><ElTableColumn prop="label" label="字段" min-width="100" /><ElTableColumn
            label="变更前"
            min-width="140"
            ><template #default="{ row }"
              ><ElTag size="small" type="info" effect="plain">{{ row.before }}</ElTag></template
            ></ElTableColumn
          ><ElTableColumn label="变更后" min-width="140"
            ><template #default="{ row }"
              ><ElTag size="small" :type="statusColor(row.key, row.rawAfter)">{{
                row.after
              }}</ElTag></template
            ></ElTableColumn
          ></ElTable
        ></template
      ></FaDrawer
    >
  </AssetPage>
</template>
<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  AssetAPI,
  assetError,
  assetLabels,
  applicationLabels,
  loanLabels,
  stateColors,
  type AuditLog,
  type AssetState,
  type ApplicationState,
  type LoanState,
} from "@/api/module_asset/asset";
import AssetPage from "../components/AssetPage.vue";
import type { SearchFormItem } from "@/components/forms/fa-search-bar/index.vue";
defineOptions({ name: "AssetAudit" });
const route = useRoute(),
  router = useRouter();
const filters = ref({ keyword: "" });
const keyword = computed({
  get: () => filters.value.keyword,
  set: (value: string) => (filters.value.keyword = value),
});
const searchItems: SearchFormItem[] = [
  {
    key: "keyword",
    label: "资产",
    type: "input",
    span: 7,
    props: { placeholder: "请输入资产编码或名称", clearable: true, maxlength: 128 },
  },
];
const rows = ref<AuditLog[]>([]),
  page = ref(1),
  total = ref(0),
  loading = ref(false),
  error = ref(""),
  selected = ref<AuditLog>(),
  visible = ref(false);
let sequence = 0;
const assetId = computed(() => {
  const value = Number(route.query.asset_id);
  return Number.isSafeInteger(value) && value > 0 ? value : undefined;
});
const actions: Record<string, string> = {
  ASSET_CREATED: "登记资产",
  APPLICATION_SUBMITTED: "提交申请",
  ISSUE_APPROVED: "批准领用",
  RETURN_APPROVED: "批准归还",
  REPAIR_APPROVED: "批准维修",
  APPLICATION_REJECTED: "驳回申请",
  APPLICATION_CANCELLED: "取消申请",
  LOAN_HANDED_OVER: "确认交付",
  LOAN_RECEIVED: "员工签收",
  LOAN_CANCELLED: "撤销交付",
  REPAIR_COMPLETED: "维修完成",
  ASSET_RETIRED: "报废资产",
};
function valueLabel(key: string, value: unknown) {
  if (value == null) return key === "custodian_id" ? "无保管人" : "无记录";
  if (key === "asset_state") return assetLabels[value as AssetState] || String(value);
  if (key === "application_state")
    return applicationLabels[value as ApplicationState] || String(value);
  if (key === "loan_state") return loanLabels[value as LoanState] || String(value);
  return `人员 #${String(value)}`;
}
function statusColor(
  key: string,
  value: unknown
): "success" | "primary" | "warning" | "danger" | "info" {
  if (key === "asset_state") return stateColors[value as AssetState] || "info";
  if (key === "application_state") {
    const colors: Record<ApplicationState, "success" | "primary" | "warning" | "danger" | "info"> =
      {
        PENDING: "warning",
        APPROVED: "success",
        REJECTED: "danger",
        CANCELLED: "info",
        COMPLETED: "primary",
      };
    return colors[value as ApplicationState] || "info";
  }
  if (key === "loan_state") {
    if (value === "PENDING_HANDOVER" || value === "PENDING_RECEIPT") return "warning";
    if (value === "IN_USE") return "primary";
    if (value === "COMPLETED") return "success";
    return "info";
  }
  return "primary";
}
function changes(row: AuditLog) {
  const labels: Record<string, string> = {
    asset_state: "资产状态",
    application_state: "申请状态",
    loan_state: "领用进度",
    custodian_id: "保管人",
  };
  return Object.entries(labels)
    .filter(([key]) => key in (row.before_json || {}) || key in (row.after_json || {}))
    .map(([key, label]) => ({
      key,
      label,
      before: valueLabel(key, row.before_json?.[key]),
      after: valueLabel(key, row.after_json?.[key]),
      rawAfter: row.after_json?.[key],
    }));
}
function changedFields(row: AuditLog) {
  return changes(row).filter((change) => change.before !== change.after);
}
function extraChanges(row: AuditLog) {
  return changedFields(row)
    .slice(1)
    .map((change) => `${change.label}：${change.before} → ${change.after}`)
    .join("；");
}
async function load() {
  const current = ++sequence;
  loading.value = true;
  error.value = "";
  try {
    const result = await AssetAPI.audit({
      page_no: page.value,
      page_size: 20,
      asset_id: assetId.value,
      keyword: keyword.value.trim() || undefined,
    });
    if (current === sequence) {
      rows.value = result.items;
      total.value = result.total;
    }
  } catch (e) {
    if (current === sequence) error.value = assetError(e);
  } finally {
    if (current === sequence) loading.value = false;
  }
}
function search() {
  page.value = 1;
  void load();
}
function onPageChange(value: number) {
  page.value = value;
  void load();
}
function resetFilters() {
  keyword.value = "";
  search();
}
function clearAsset() {
  void router.replace({ path: "/asset/audit" });
}
watch(assetId, search);
onMounted(load);
</script>
<style scoped lang="scss">
.audit-transition {
  display: flex;
  gap: 6px;
  align-items: center;
  white-space: nowrap;
}

.audit-field {
  min-width: 52px;
  color: var(--el-text-color-secondary);
}

.audit-arrow {
  flex: none;
  color: var(--el-text-color-placeholder);
}
</style>
