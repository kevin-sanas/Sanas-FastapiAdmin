<template>
  <AssetPage title="资产目录" description="按件管理实物资产。同一租户的员工可查询并申请领用。">
    <FaSearchBar
      v-model="filters"
      class="asset-search"
      :items="searchItems"
      :show-expand="false"
      @search="search"
      @reset="reset"
    />
    <ElCard shadow="hover" class="fa-table-card asset-table-card">
      <FaTableHeader layout="refresh,size,fullscreen,settings" :loading="loading" @refresh="load">
        <template #left>
          <div class="asset-table-actions">
            <ElButton
              v-if="hasAuth('module_asset:item:create')"
              type="success"
              plain
              @click="openCreate"
              ><FaSvgIcon icon="ri:add-line" />登记资产</ElButton
            >
            <ElButton
              v-if="hasAuth('module_asset:category:create')"
              type="primary"
              plain
              @click="categoryVisible = true"
              ><FaSvgIcon icon="ri:folder-add-line" />新增分类</ElButton
            >
            <span class="asset-muted">同一租户可查询并申请领用 · 共 {{ total }} 件</span>
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
        :pagination="{ current: page, size, total }"
        :pagination-options="{ pageSizes: [10, 20, 50] }"
        :empty-text="
          keyword || state ? '没有符合条件的资产，请调整筛选条件' : '还没有资产，请先登记设备'
        "
        @pagination:current-change="onPageChange"
        @pagination:size-change="onSizeChange"
      >
        <ElTableColumn label="资产" min-width="210"
          ><template #default="{ row }"
            ><ElButton link type="primary" @click="showDetail(row.id)">{{ row.name }}</ElButton>
            <div class="asset-muted asset-code">{{ row.asset_code }}</div></template
          ></ElTableColumn
        >
        <ElTableColumn label="分类" prop="category_name" min-width="120" />
        <ElTableColumn label="状态" width="110"
          ><template #default="{ row }"
            ><ElTag :type="stateColors[row.asset_state as AssetState]" effect="light">{{
              assetLabels[row.asset_state as AssetState]
            }}</ElTag></template
          ></ElTableColumn
        >
        <ElTableColumn label="保管人" min-width="120"
          ><template #default="{ row }">{{
            row.custodian_name || (row.reserved_for_name ? `待交付：${row.reserved_for_name}` : "—")
          }}</template></ElTableColumn
        >
        <ElTableColumn label="登记时间" prop="created_time" width="175" />
        <ElTableColumn label="操作" min-width="205" fixed="right"
          ><template #default="{ row }"
            ><div class="asset-row-actions">
              <ElTooltip v-if="canRequest(row, 'ISSUE')" content="申请领用" placement="top"
                ><ElButton
                  type="primary"
                  class="asset-icon-action"
                  aria-label="申请领用"
                  @click="openRequest(row, 'ISSUE')"
                  ><FaSvgIcon icon="ri:hand-coin-line" /></ElButton
              ></ElTooltip>
              <ElTooltip v-if="canRequest(row, 'RETURN')" content="申请归还" placement="top"
                ><ElButton
                  type="primary"
                  class="asset-icon-action"
                  aria-label="申请归还"
                  @click="openRequest(row, 'RETURN')"
                  ><FaSvgIcon icon="ri:arrow-go-back-line" /></ElButton
              ></ElTooltip>
              <ElTooltip v-if="canRequest(row, 'REPAIR')" content="申请维修" placement="top"
                ><ElButton
                  class="asset-icon-action"
                  aria-label="申请维修"
                  @click="openRequest(row, 'REPAIR')"
                  ><FaSvgIcon icon="ri:tools-line" /></ElButton
              ></ElTooltip>
              <ElTooltip
                v-if="
                  hasAuth('module_asset:item:manage') &&
                  ['AVAILABLE', 'MAINTENANCE'].includes(row.asset_state)
                "
                content="报废资产"
                placement="top"
                ><ElButton
                  type="danger"
                  class="asset-icon-action"
                  aria-label="报废资产"
                  :loading="retiring === row.id"
                  @click="retire(row)"
                  ><FaSvgIcon icon="ri:delete-bin-6-line" /></ElButton
              ></ElTooltip></div></template
        ></ElTableColumn>
      </FaTable>
    </ElCard>

    <ElDialog
      class="asset-modal"
      v-model="createVisible"
      title="登记资产"
      width="min(540px, 94vw)"
      :show-close="!busy"
      :close-on-click-modal="!busy"
      :close-on-press-escape="!busy"
    >
      <ElForm ref="formRef" :model="form" :rules="rules" label-position="top" class="asset-form">
        <ElFormItem label="资产编码" prop="asset_code"
          ><ElInput v-model="form.asset_code" maxlength="64" placeholder="例如：IT-2026-001"
        /></ElFormItem>
        <ElFormItem label="资产名称" prop="name"
          ><ElInput v-model="form.name" maxlength="128" placeholder="例如：研发笔记本电脑"
        /></ElFormItem>
        <ElFormItem label="资产分类" prop="category_id"
          ><ElSelect
            v-model="form.category_id"
            filterable
            remote
            :remote-method="searchCategories"
            :loading="categoriesLoading"
            placeholder="输入分类名称搜索"
            ><ElOption
              v-for="category in categories"
              :key="category.id"
              :value="category.id"
              :label="category.name" /></ElSelect
          ><span v-if="categoryTotal > 100" class="asset-muted"
            >当前展示前 100 个结果，请输入名称缩小范围。</span
          ></ElFormItem
        >
        <ElFormItem label="购入日期"
          ><ElDatePicker
            v-model="form.purchase_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="可选"
        /></ElFormItem>
        <ElFormItem label="购入金额（元）"
          ><ElInputNumber
            v-model="form.purchase_amount"
            :min="0"
            :max="9999999999.99"
            :precision="2"
            :controls="false"
            placeholder="可选"
        /></ElFormItem>
      </ElForm>
      <ElAlert v-if="submitError" :title="submitError" type="error" :closable="false" />
      <template #footer
        ><ElButton :disabled="busy" @click="createVisible = false">取消</ElButton
        ><ElButton type="primary" :loading="busy" @click="create">登记资产</ElButton></template
      >
    </ElDialog>
    <ElDialog
      class="asset-modal"
      v-model="categoryVisible"
      title="新增资产分类"
      width="min(440px, 94vw)"
      :show-close="!categoryBusy"
      :close-on-click-modal="!categoryBusy"
      :close-on-press-escape="!categoryBusy"
    >
      <ElForm ref="categoryFormRef" :model="categoryForm" label-position="top" class="asset-form"
        ><ElFormItem
          label="分类编码"
          prop="code"
          :rules="[{ required: true, message: '请输入分类编码', trigger: 'blur' }]"
          ><ElInput v-model="categoryForm.code" maxlength="64" /></ElFormItem
        ><ElFormItem
          label="分类名称"
          prop="name"
          :rules="[{ required: true, message: '请输入分类名称', trigger: 'blur' }]"
          ><ElInput v-model="categoryForm.name" maxlength="128" /></ElFormItem
      ></ElForm>
      <ElAlert v-if="categoryError" :title="categoryError" type="error" :closable="false" />
      <template #footer
        ><ElButton :disabled="categoryBusy" @click="categoryVisible = false">取消</ElButton
        ><ElButton type="primary" :loading="categoryBusy" @click="createCategory"
          >新增分类</ElButton
        ></template
      >
    </ElDialog>
    <ElDialog
      class="asset-modal"
      v-model="requestVisible"
      :title="`申请${typeLabels[requestType]}`"
      width="min(500px, 94vw)"
      :show-close="!busy"
      :close-on-click-modal="!busy"
      :close-on-press-escape="!busy"
    >
      <p class="asset-dialog-note">
        {{ selected?.name }}（{{
          selected?.asset_code
        }}）<br />提交后等待审批，资产状态会在批准后更新。
      </p>
      <ElForm ref="requestFormRef" :model="requestForm" label-position="top"
        ><ElFormItem
          label="申请理由"
          prop="reason"
          :rules="[
            { required: true, whitespace: true, message: '请填写申请理由', trigger: 'blur' },
          ]"
          ><ElInput
            v-model="requestForm.reason"
            type="textarea"
            :rows="4"
            maxlength="2000"
            show-word-limit /></ElFormItem
      ></ElForm>
      <ElAlert v-if="submitError" :title="submitError" type="error" :closable="false" />
      <template #footer
        ><ElButton :disabled="busy" @click="requestVisible = false">取消</ElButton
        ><ElButton type="primary" :loading="busy" @click="submitRequest"
          >提交申请</ElButton
        ></template
      >
    </ElDialog>
    <FaDrawer v-model="detailVisible" class="asset-modal" title="资产详情" size="min(540px, 100vw)">
      <div v-loading="detailLoading">
        <ElAlert v-if="detailError" :title="detailError" type="error" :closable="false" />
        <template v-if="detail"
          ><div class="asset-detail-head">
            <h2>{{ detail.name }}</h2>
            <p class="asset-muted">{{ detail.asset_code }}</p>
          </div>
          <FaDescriptions :data="{ ...detail }" :items="detailItems" :column="2" :scrollbar="false">
            <template #asset_state="{ row }"
              ><ElTag :type="stateColors[row?.asset_state as AssetState]">{{
                assetLabels[row?.asset_state as AssetState]
              }}</ElTag></template
            >
            <template #category_name="{ row }">{{ row?.category_name || "—" }}</template>
            <template #custodian_name="{ row }">{{
              row?.custodian_name ||
              (row?.reserved_for_name ? `待交付：${row.reserved_for_name}` : "—")
            }}</template>
            <template #purchase_date="{ row }">{{ row?.purchase_date || "未填写" }}</template>
            <template #purchase_amount="{ row }">{{
              row?.purchase_amount == null
                ? "未填写"
                : `¥ ${Number(row?.purchase_amount).toLocaleString("zh-CN", { minimumFractionDigits: 2 })}`
            }}</template>
          </FaDescriptions>
          <ElButton
            v-if="hasAuth('module_asset:audit:query')"
            class="asset-detail-audit"
            type="primary"
            plain
            @click="
              router.push({
                path: '/asset/audit',
                query: { asset_id: detail.id, asset_name: detail.name },
              })
            "
            ><FaSvgIcon icon="ri:history-line" />查看业务审计</ElButton
          ></template
        >
      </div>
    </FaDrawer>
  </AssetPage>
</template>
<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useDebounceFn } from "@vueuse/core";
import { ElMessageBox, type FormInstance, type FormRules } from "element-plus";
import { useUserStore } from "@stores";
import { useAuth } from "@/hooks/core/useAuth";
import {
  AssetAPI,
  assetLabels,
  stateColors,
  typeLabels,
  assetError,
  type AssetState,
  type AssetItem,
  type Category,
  type ItemInput,
  type ApplicationType,
} from "@/api/module_asset/asset";
import AssetPage from "../components/AssetPage.vue";
import type { SearchFormItem } from "@/components/forms/fa-search-bar/index.vue";
import type { DescriptionsItem } from "@/components/others/fa-descriptions/index.vue";
defineOptions({ name: "AssetItems" });
const detailItems: DescriptionsItem[] = [
  { label: "资产状态", prop: "asset_state", slot: "asset_state" },
  { label: "资产分类", prop: "category_name", slot: "category_name" },
  { label: "保管人", prop: "custodian_name", slot: "custodian_name" },
  { label: "购入日期", prop: "purchase_date", slot: "purchase_date" },
  { label: "购入金额", prop: "purchase_amount", slot: "purchase_amount" },
  { label: "登记时间", prop: "created_time" },
];
const { hasAuth } = useAuth();
const user = useUserStore();
const route = useRoute();
const router = useRouter();
function routeState() {
  const value = String(route.query.asset_state || "");
  return value in assetLabels ? (value as AssetState) : undefined;
}
const filters = ref<{ keyword: string; state: AssetState | undefined }>({
  keyword: "",
  state: routeState(),
});
const keyword = computed({
  get: () => filters.value.keyword,
  set: (value: string) => (filters.value.keyword = value),
});
const state = computed({
  get: () => filters.value.state,
  set: (value: AssetState | undefined) => (filters.value.state = value),
});
const searchItems = computed<SearchFormItem[]>(() => [
  {
    key: "keyword",
    label: "资产",
    type: "input",
    span: 7,
    props: { placeholder: "请输入资产编码或名称", clearable: true, maxlength: 128 },
  },
  {
    key: "state",
    label: "资产状态",
    type: "select",
    span: 6,
    props: {
      placeholder: "全部状态",
      clearable: true,
      options: Object.entries(assetLabels).map(([value, label]) => ({ value, label })),
    },
  },
]);
const rows = ref<AssetItem[]>([]),
  page = ref(1),
  size = ref(20),
  total = ref(0);
const loading = ref(false),
  error = ref(""),
  busy = ref(false),
  submitError = ref("");
let sequence = 0;
async function load() {
  const current = ++sequence;
  loading.value = true;
  error.value = "";
  try {
    const result = await AssetAPI.items({
      page_no: page.value,
      page_size: size.value,
      keyword: keyword.value.trim() || undefined,
      asset_state: state.value,
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
function onSizeChange(value: number) {
  size.value = value;
  search();
}
function reset() {
  keyword.value = "";
  state.value = undefined;
  search();
}
watch(
  () => route.query.asset_state,
  () => {
    state.value = routeState();
    search();
  }
);
const categories = ref<Category[]>([]),
  categoryTotal = ref(0),
  categoriesLoading = ref(false);
let categorySequence = 0;
async function loadCategories(value?: string) {
  if (!hasAuth("module_asset:category:query")) return;
  const current = ++categorySequence;
  categoriesLoading.value = true;
  try {
    const result = await AssetAPI.categories(value);
    if (current === categorySequence) {
      categories.value = result.items.filter((c) => c.status === "0");
      categoryTotal.value = result.total;
    }
  } catch (e) {
    submitError.value = assetError(e);
  } finally {
    if (current === categorySequence) categoriesLoading.value = false;
  }
}
const searchCategories = useDebounceFn(loadCategories, 300);
const createVisible = ref(false),
  formRef = ref<FormInstance>();
const emptyForm = () => ({
  asset_code: "",
  name: "",
  category_id: undefined as number | undefined,
  purchase_date: null as string | null,
  purchase_amount: undefined as number | undefined,
});
const form = reactive(emptyForm());
const rules: FormRules = {
  asset_code: [{ required: true, whitespace: true, message: "请输入资产编码", trigger: "blur" }],
  name: [{ required: true, whitespace: true, message: "请输入资产名称", trigger: "blur" }],
  category_id: [{ required: true, message: "请选择分类", trigger: "change" }],
};
function openCreate() {
  Object.assign(form, emptyForm());
  submitError.value = "";
  createVisible.value = true;
  void loadCategories();
  formRef.value?.clearValidate();
}
async function create() {
  if (!(await formRef.value?.validate().catch(() => false)) || busy.value) return;
  busy.value = true;
  submitError.value = "";
  try {
    await AssetAPI.createItem({
      ...form,
      asset_code: form.asset_code.trim(),
      name: form.name.trim(),
      category_id: form.category_id!,
      purchase_amount: form.purchase_amount ?? null,
    } satisfies ItemInput);
    createVisible.value = false;
    search();
  } catch (e) {
    submitError.value = assetError(e);
  } finally {
    busy.value = false;
  }
}
const categoryVisible = ref(false),
  categoryBusy = ref(false),
  categoryError = ref(""),
  categoryFormRef = ref<FormInstance>();
const categoryForm = reactive({ code: "", name: "" });
async function createCategory() {
  if (!(await categoryFormRef.value?.validate().catch(() => false)) || categoryBusy.value) return;
  categoryBusy.value = true;
  categoryError.value = "";
  try {
    const category = await AssetAPI.createCategory({
      ...categoryForm,
      code: categoryForm.code.trim(),
      name: categoryForm.name.trim(),
      parent_id: null,
      sort_order: 0,
    });
    categoryVisible.value = false;
    categoryForm.code = "";
    categoryForm.name = "";
    await loadCategories();
    if (!categories.value.some((c) => c.id === category.id)) categories.value.unshift(category);
    form.category_id = category.id;
  } catch (e) {
    categoryError.value = assetError(e);
  } finally {
    categoryBusy.value = false;
  }
}
const selected = ref<AssetItem>(),
  requestVisible = ref(false),
  requestType = ref<ApplicationType>("ISSUE"),
  requestForm = reactive({ reason: "" }),
  requestFormRef = ref<FormInstance>();
let requestKey = "";
function canRequest(item: AssetItem, kind: ApplicationType) {
  if (!hasAuth("module_asset:application:create") || item.status !== "0") return false;
  if (kind === "ISSUE") return item.asset_state === "AVAILABLE";
  if (kind === "RETURN")
    return item.asset_state === "IN_USE" && item.custodian_id === user.basicInfo.id;
  return (
    item.asset_state === "AVAILABLE" ||
    (item.asset_state === "IN_USE" && item.custodian_id === user.basicInfo.id)
  );
}
function openRequest(item: AssetItem, kind: ApplicationType) {
  selected.value = item;
  requestType.value = kind;
  requestForm.reason = "";
  requestKey = crypto.randomUUID();
  submitError.value = "";
  requestVisible.value = true;
  requestFormRef.value?.clearValidate();
}
async function submitRequest() {
  if (!selected.value || !(await requestFormRef.value?.validate().catch(() => false)) || busy.value)
    return;
  busy.value = true;
  submitError.value = "";
  try {
    await AssetAPI.submit({
      asset_id: selected.value.id,
      application_type: requestType.value,
      reason: requestForm.reason.trim(),
      idempotency_key: requestKey,
    });
    requestVisible.value = false;
    await load();
  } catch (e) {
    submitError.value = assetError(e);
  } finally {
    busy.value = false;
  }
}
const retiring = ref<number>();
async function retire(item: AssetItem) {
  try {
    await ElMessageBox.confirm(`确认报废“${item.name}”？报废后不能恢复为可领用状态。`, "报废资产", {
      type: "warning",
      confirmButtonText: "确认报废",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  retiring.value = item.id;
  try {
    await AssetAPI.retire(item.id, item.row_version);
    await load();
  } catch (e) {
    error.value = assetError(e);
  } finally {
    retiring.value = undefined;
  }
}
const detailVisible = ref(false),
  detailLoading = ref(false),
  detailError = ref(""),
  detail = ref<AssetItem>();
let detailSequence = 0;
async function showDetail(id: number) {
  const current = ++detailSequence;
  detailVisible.value = true;
  detail.value = undefined;
  detailError.value = "";
  detailLoading.value = true;
  try {
    const result = await AssetAPI.detail(id);
    if (current === detailSequence) detail.value = result;
  } catch (e) {
    if (current === detailSequence) detailError.value = assetError(e);
  } finally {
    if (current === detailSequence) detailLoading.value = false;
  }
}
onMounted(load);
</script>
