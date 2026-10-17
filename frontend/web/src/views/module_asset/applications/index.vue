<template>
  <AssetPage
    title="申请与审批"
    :description="
      isReviewer
        ? '查看权限范围内的申请，核对资产后作出审批决定。'
        : '查看自己的领用、归还与维修申请。'
    "
  >
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
            <ElButton
              v-if="hasAuth('module_asset:item:query')"
              type="success"
              plain
              @click="router.push('/asset/items')"
              ><FaSvgIcon icon="ri:add-line" />发起申请</ElButton
            >
            <span class="asset-muted">提交后等待审批，批准后更新资产状态 · 共 {{ total }} 条</span>
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
        empty-text="暂无申请，可前往资产目录提交领用申请"
        @pagination:current-change="onPageChange"
      >
        <ElTableColumn label="申请资产" min-width="200"
          ><template #default="{ row }"
            ><div class="asset-name">{{ row.asset_name }}</div>
            <div class="asset-muted asset-code">{{ row.asset_code }}</div></template
          ></ElTableColumn
        >
        <ElTableColumn label="类型" width="85"
          ><template #default="{ row }">{{
            typeLabels[row.application_type as ApplicationType]
          }}</template></ElTableColumn
        >
        <ElTableColumn prop="applicant_name" label="申请人" min-width="100" />
        <ElTableColumn label="状态 / 领用进度" width="180"
          ><template #default="{ row }"
            ><ElTag :type="colors[row.application_state as ApplicationState]">{{
              applicationLabels[row.application_state as ApplicationState]
            }}</ElTag>
            <div v-if="row.application_type === 'ISSUE' && row.loan_state" class="loan-progress">
              <ElTag size="small" effect="plain" :type="loanColor(row.loan_state)">{{
                loanLabels[row.loan_state as LoanState]
              }}</ElTag>
            </div></template
          ></ElTableColumn
        >
        <ElTableColumn prop="reason" label="申请理由" min-width="180" show-overflow-tooltip />
        <ElTableColumn prop="created_time" label="提交时间" width="175" />
        <ElTableColumn label="操作" min-width="170" fixed="right"
          ><template #default="{ row }"
            ><div class="asset-row-actions">
              <ElTooltip content="申请详情" placement="top"
                ><ElButton
                  class="asset-icon-action"
                  aria-label="申请详情"
                  @click="
                    selected = row;
                    detailVisible = true;
                  "
                  ><FaSvgIcon icon="ri:eye-line" /></ElButton
              ></ElTooltip>
              <template v-if="row.application_state === 'PENDING'">
                <ElTooltip
                  v-if="
                    row.applicant_id === user.basicInfo.id &&
                    hasAuth('module_asset:application:cancel')
                  "
                  content="取消申请"
                  placement="top"
                  ><ElButton
                    type="warning"
                    class="asset-icon-action"
                    aria-label="取消申请"
                    :loading="cancelling === row.id"
                    @click="cancel(row)"
                    ><FaSvgIcon icon="ri:close-circle-line" /></ElButton
                ></ElTooltip>
                <template v-if="row.applicant_id !== user.basicInfo.id"
                  ><ElTooltip
                    v-if="hasAuth('module_asset:application:approve')"
                    :content="row.application_type === 'RETURN' ? '验收归还' : '批准申请'"
                    placement="top"
                    ><ElButton
                      type="primary"
                      class="asset-icon-action"
                      aria-label="批准申请"
                      @click="openAction(row, 'approve')"
                      ><FaSvgIcon icon="ri:check-line" /></ElButton></ElTooltip
                  ><ElTooltip
                    v-if="hasAuth('module_asset:application:reject')"
                    content="驳回申请"
                    placement="top"
                    ><ElButton
                      type="danger"
                      class="asset-icon-action"
                      aria-label="驳回申请"
                      @click="openAction(row, 'reject')"
                      ><FaSvgIcon icon="ri:close-line" /></ElButton></ElTooltip
                ></template>
              </template>
              <template
                v-if="
                  row.application_type === 'ISSUE' &&
                  row.application_state === 'APPROVED' &&
                  row.loan_id
                "
              >
                <ElTooltip
                  v-if="
                    row.loan_state === 'PENDING_HANDOVER' &&
                    row.applicant_id !== user.basicInfo.id &&
                    hasAuth('module_asset:application:approve')
                  "
                  content="确认交付"
                  placement="top"
                >
                  <ElButton
                    type="primary"
                    class="asset-icon-action"
                    aria-label="确认交付"
                    @click="openAction(row, 'handover')"
                    ><FaSvgIcon icon="ri:hand-heart-line"
                  /></ElButton>
                </ElTooltip>
                <ElTooltip
                  v-if="
                    row.loan_state === 'PENDING_RECEIPT' && row.applicant_id === user.basicInfo.id
                  "
                  content="确认签收"
                  placement="top"
                >
                  <ElButton
                    type="success"
                    class="asset-icon-action"
                    aria-label="确认签收"
                    :loading="receiving === row.id"
                    @click="receive(row)"
                    ><FaSvgIcon icon="ri:check-double-line"
                  /></ElButton>
                </ElTooltip>
                <ElTooltip
                  v-if="
                    ['PENDING_HANDOVER', 'PENDING_RECEIPT'].includes(row.loan_state || '') &&
                    row.applicant_id !== user.basicInfo.id &&
                    hasAuth('module_asset:application:approve')
                  "
                  content="撤销交付"
                  placement="top"
                >
                  <ElButton
                    type="danger"
                    class="asset-icon-action"
                    aria-label="撤销交付"
                    @click="openAction(row, 'cancel-handover')"
                    ><FaSvgIcon icon="ri:arrow-go-back-line"
                  /></ElButton>
                </ElTooltip>
                <ElTooltip
                  v-if="
                    row.loan_state === 'IN_USE' &&
                    !row.pending_return_id &&
                    row.applicant_id === user.basicInfo.id &&
                    hasAuth('module_asset:application:create')
                  "
                  content="申请归还"
                  placement="top"
                >
                  <ElButton
                    type="primary"
                    class="asset-icon-action"
                    aria-label="申请归还"
                    @click="openAction(row, 'return')"
                    ><FaSvgIcon icon="ri:inbox-unarchive-line"
                  /></ElButton>
                </ElTooltip>
              </template>
              <ElTooltip
                v-if="
                  row.application_type === 'REPAIR' &&
                  row.application_state === 'APPROVED' &&
                  hasAuth('module_asset:item:manage')
                "
                content="完成维修"
                placement="top"
                ><ElButton
                  type="primary"
                  class="asset-icon-action"
                  aria-label="完成维修"
                  @click="openAction(row, 'complete')"
                  ><FaSvgIcon icon="ri:tools-line" /></ElButton
              ></ElTooltip></div></template
        ></ElTableColumn>
      </FaTable>
    </ElCard>
    <ElDialog
      v-model="actionVisible"
      class="asset-modal"
      :title="currentActionTitle"
      width="min(520px, 94vw)"
      :show-close="!busy"
      :close-on-click-modal="!busy"
      :close-on-press-escape="!busy"
    >
      <p class="asset-dialog-note">
        {{ selected?.asset_name }}（{{ selected?.asset_code }}）<br />申请人：{{
          selected?.applicant_name
        }}
        · {{ selected && typeLabels[selected.application_type] }}<br />申请理由：{{
          selected?.reason
        }}
      </p>
      <ElAlert
        v-if="action === 'approve'"
        :title="
          selected?.application_type === 'ISSUE'
            ? '批准后设备先进入待交付；管理员交付、员工签收后才开始领用。'
            : selected?.application_type === 'RETURN'
              ? '确认验收后，领用记录将完结，设备恢复在库。'
              : '批准后将立即更新资产状态。'
        "
        type="info"
        :closable="false"
        style="margin-bottom: 18px"
      />
      <ElForm ref="actionFormRef" :model="actionForm" label-position="top"
        ><ElFormItem
          :label="
            action === 'reject'
              ? '驳回原因'
              : action === 'complete'
                ? '维修完成说明'
                : action === 'handover'
                  ? '交付说明'
                  : action === 'cancel-handover'
                    ? '撤销原因'
                    : action === 'return'
                      ? '归还原因'
                      : selected?.application_type === 'RETURN'
                        ? '验收记录'
                        : '审批意见（可选）'
          "
          prop="note"
          :rules="
            action === 'approve' && selected?.application_type !== 'RETURN'
              ? []
              : [{ required: true, whitespace: true, message: '请填写说明', trigger: 'blur' }]
          "
          ><ElInput
            v-model="actionForm.note"
            type="textarea"
            :rows="4"
            maxlength="2000"
            show-word-limit /></ElFormItem
      ></ElForm>
      <ElAlert v-if="actionError" :title="actionError" type="error" :closable="false" />
      <template #footer
        ><ElButton :disabled="busy" @click="actionVisible = false">返回</ElButton
        ><ElButton
          :type="action === 'reject' ? 'danger' : 'primary'"
          :loading="busy"
          @click="submitAction"
          >{{ currentActionTitle }}</ElButton
        ></template
      >
    </ElDialog>
    <FaDrawer v-model="detailVisible" class="asset-modal" title="申请详情" size="min(540px, 100vw)">
      <template v-if="selected"
        ><div class="asset-detail-head">
          <h2>{{ selected.asset_name }}</h2>
          <p class="asset-muted">{{ selected.asset_code }}</p>
        </div>
        <FaDescriptions :data="{ ...selected }" :items="detailItems" :column="2" :scrollbar="false">
          <template #application_type="{ row }">{{
            typeLabels[row?.application_type as ApplicationType]
          }}</template>
          <template #application_state="{ row }">
            <ElTag :type="colors[row?.application_state as ApplicationState]">{{
              applicationLabels[row?.application_state as ApplicationState]
            }}</ElTag>
          </template>
        </FaDescriptions>
        <ElDivider content-position="left">申请理由</ElDivider>
        <p class="application-reason">{{ selected.reason }}</p>
        <template v-if="selected.reviewed_at">
          <ElDivider content-position="left">{{
            selected.application_state === "REJECTED" ? "驳回原因" : "审批意见"
          }}</ElDivider>
          <p class="application-reason">{{ selected.review_note || "未填写审批意见" }}</p>
          <p class="asset-muted">{{ selected.reviewer_name }} · {{ selected.reviewed_at }}</p>
        </template>
        <template v-if="selected.application_type === 'ISSUE' && selected.loan_state">
          <ElDivider content-position="left">领用闭环</ElDivider>
          <p>
            <ElTag :type="loanColor(selected.loan_state)">{{
              loanLabels[selected.loan_state]
            }}</ElTag>
          </p>
          <p v-if="selected.pending_return_id" class="application-reason">归还申请待管理员验收</p>
          <p class="asset-muted">
            批准：{{ selected.loan_approved_at || "—" }}<br />管理员交付：{{
              selected.loan_handed_at || "尚未交付"
            }}<br />员工签收：{{
              selected.loan_received_at ||
              (selected.loan_is_legacy ? "历史数据，时间未知" : "尚未签收")
            }}<br />归还验收：{{ selected.loan_returned_at || "尚未归还" }}
          </p>
          <p v-if="selected.loan_close_reason === 'REPAIR'" class="application-reason">
            领用因维修申请完结，设备已移交维修。
          </p>
          <p v-if="selected.loan_close_reason === 'LEGACY_UNKNOWN'" class="application-reason">
            历史领用已结束，结束原因未记录。
          </p>
          <p v-if="selected.loan_handover_note" class="application-reason">
            交付说明：{{ selected.loan_handover_note }}
          </p>
          <p v-if="selected.loan_return_note" class="application-reason">
            归还验收：{{ selected.loan_return_note }}
          </p>
          <p v-if="selected.loan_cancel_reason" class="application-reason">
            撤销原因：{{ selected.loan_cancel_reason }}
          </p>
          <p v-if="selected.loan_is_legacy" class="asset-muted">
            此记录来自旧版申请，历史交付与签收时间未记录。
          </p>
        </template>
        <template v-if="selected.completion_note"
          ><ElDivider content-position="left">维修完成说明</ElDivider>
          <p class="application-reason">{{ selected.completion_note }}</p>
          <p class="asset-muted">完成时间：{{ selected.completed_at }}</p></template
        ></template
      >
    </FaDrawer>
  </AssetPage>
</template>
<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessageBox, type FormInstance } from "element-plus";
import { useUserStore } from "@stores";
import { useAuth } from "@/hooks/core/useAuth";
import {
  AssetAPI,
  applicationLabels,
  loanLabels,
  typeLabels,
  assetError,
  type AssetApplication,
  type ApplicationType,
  type ApplicationState,
  type LoanState,
} from "@/api/module_asset/asset";
import AssetPage from "../components/AssetPage.vue";
import type { SearchFormItem } from "@/components/forms/fa-search-bar/index.vue";
import type { DescriptionsItem } from "@/components/others/fa-descriptions/index.vue";
defineOptions({ name: "AssetApplications" });
const { hasAuth } = useAuth();
const user = useUserStore();
const route = useRoute();
const router = useRouter();
const isReviewer = computed(
  () => hasAuth("module_asset:application:approve") || hasAuth("module_asset:application:reject")
);
const colors: Record<ApplicationState, "warning" | "success" | "danger" | "info" | "primary"> = {
  PENDING: "warning",
  APPROVED: "success",
  REJECTED: "danger",
  CANCELLED: "info",
  COMPLETED: "primary",
};
function loanColor(state: LoanState): "warning" | "success" | "danger" | "info" | "primary" {
  if (state === "PENDING_HANDOVER" || state === "PENDING_RECEIPT") return "warning";
  if (state === "IN_USE") return "primary";
  return state === "COMPLETED" ? "success" : "info";
}
const detailItems: DescriptionsItem[] = [
  { label: "申请类型", prop: "application_type", slot: "application_type" },
  { label: "申请状态", prop: "application_state", slot: "application_state" },
  { label: "申请人", prop: "applicant_name" },
  { label: "提交时间", prop: "created_time" },
  { label: "申请单号", prop: "request_no", span: 2 },
];
const searchItems = computed<SearchFormItem[]>(() => [
  {
    key: "state",
    label: "申请状态",
    type: "select",
    span: 7,
    props: {
      placeholder: "全部申请状态",
      clearable: true,
      options: Object.entries(applicationLabels).map(([value, label]) => ({ value, label })),
    },
  },
]);
function routeState() {
  const value = String(route.query.state || "");
  return value in applicationLabels ? (value as ApplicationState) : undefined;
}
const filters = ref<{ state: ApplicationState | undefined }>({ state: routeState() });
const state = computed({
  get: () => filters.value.state,
  set: (value: ApplicationState | undefined) => (filters.value.state = value),
});
const rows = ref<AssetApplication[]>([]),
  loading = ref(false),
  error = ref(""),
  page = ref(1),
  total = ref(0);
let sequence = 0;
async function load() {
  const current = ++sequence;
  loading.value = true;
  error.value = "";
  try {
    const result = await AssetAPI.applications({
      page_no: page.value,
      page_size: 20,
      application_state: state.value,
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
  state.value = undefined;
  search();
}
watch(
  () => route.query.state,
  () => {
    state.value = routeState();
    search();
  }
);
type Action = "approve" | "reject" | "complete" | "handover" | "cancel-handover" | "return";
const actionTitles: Record<Action, string> = {
  approve: "批准申请",
  reject: "驳回申请",
  complete: "完成维修",
  handover: "确认交付",
  "cancel-handover": "撤销交付",
  return: "提交归还申请",
};
const selected = ref<AssetApplication>(),
  detailVisible = ref(false),
  actionVisible = ref(false),
  action = ref<Action>("approve"),
  busy = ref(false),
  actionError = ref(""),
  actionForm = reactive({ note: "" }),
  actionFormRef = ref<FormInstance>();
let decisionKey = "";
const currentActionTitle = computed(() =>
  action.value === "approve" && selected.value?.application_type === "RETURN"
    ? "验收归还"
    : actionTitles[action.value]
);
function openAction(row: AssetApplication, kind: Action) {
  selected.value = row;
  action.value = kind;
  actionForm.note = "";
  decisionKey = crypto.randomUUID();
  actionError.value = "";
  actionVisible.value = true;
  actionFormRef.value?.clearValidate();
}
async function submitAction() {
  if (!selected.value || busy.value || !(await actionFormRef.value?.validate().catch(() => false)))
    return;
  busy.value = true;
  actionError.value = "";
  try {
    if (action.value === "complete")
      await AssetAPI.completeRepair(selected.value.id, actionForm.note.trim());
    else if (action.value === "handover")
      await AssetAPI.handover(selected.value.loan_id!, actionForm.note.trim());
    else if (action.value === "cancel-handover")
      await AssetAPI.cancelHandover(selected.value.loan_id!, actionForm.note.trim());
    else if (action.value === "return")
      await AssetAPI.submit({
        asset_id: selected.value.asset_id,
        application_type: "RETURN",
        reason: actionForm.note.trim(),
        idempotency_key: decisionKey,
      });
    else
      await AssetAPI.decide(selected.value.id, action.value, {
        review_note: actionForm.note.trim() || null,
        idempotency_key: decisionKey,
      });
    actionVisible.value = false;
    await load();
  } catch (e) {
    actionError.value = assetError(e);
  } finally {
    busy.value = false;
  }
}
const receiving = ref<number>();
async function receive(row: AssetApplication) {
  if (!row.loan_id) return;
  try {
    await ElMessageBox.confirm(
      `确认已收到“${row.asset_name}”及其配件？签收后由你保管。`,
      "确认签收",
      {
        type: "warning",
        confirmButtonText: "确认签收",
        cancelButtonText: "稍后签收",
      }
    );
  } catch {
    return;
  }
  receiving.value = row.id;
  try {
    await AssetAPI.receive(row.loan_id);
    await load();
  } catch (e) {
    error.value = assetError(e);
  } finally {
    receiving.value = undefined;
  }
}
const cancelling = ref<number>();
async function cancel(row: AssetApplication) {
  try {
    await ElMessageBox.confirm(
      `取消“${row.asset_name}”的${typeLabels[row.application_type]}申请？`,
      "取消申请",
      { type: "warning", confirmButtonText: "取消申请", cancelButtonText: "保留申请" }
    );
  } catch {
    return;
  }
  cancelling.value = row.id;
  try {
    await AssetAPI.cancel(row.id);
    await load();
  } catch (e) {
    error.value = assetError(e);
  } finally {
    cancelling.value = undefined;
  }
}
onMounted(load);
</script>
<style scoped>
.asset-detail-head {
  margin-bottom: 20px;
}

.asset-detail-head h2 {
  margin: 0 0 4px;
  font-size: 18px;
}

.application-reason {
  margin-bottom: 24px;
  line-height: 1.8;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.loan-progress {
  margin-top: 6px;
}
</style>
