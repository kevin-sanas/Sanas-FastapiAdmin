<template>
  <AssetPage title="资产概览" description="资产台账、待办申请与后端运行状态。" variant="overview">
    <template #actions
      ><ElButton :loading="loading" @click="load">刷新概览</ElButton
      ><ElButton
        v-if="hasAuth('module_asset:item:query')"
        type="primary"
        @click="router.push('/asset/items')"
        >查看资产目录</ElButton
      ></template
    >
    <ElAlert
      v-if="error"
      class="asset-error"
      :title="error"
      type="error"
      show-icon
      :closable="false"
      ><ElButton text @click="load">重新加载</ElButton></ElAlert
    >
    <ElCard v-loading="loading" class="asset-overview-card" shadow="hover">
      <template #header>
        <div class="asset-panel-title">
          <h2>资产状态分布</h2>
          <ElTag effect="plain" type="info">共 {{ total ?? "—" }} 件</ElTag>
        </div>
      </template>
      <template v-if="summary">
        <div class="asset-summary-grid">
          <div v-for="state in states" :key="state">
            <button
              class="asset-summary-button"
              :disabled="!hasAuth('module_asset:item:query')"
              @click="router.push({ path: '/asset/items', query: { asset_state: state } })"
            >
              <FaStatsCard
                :title="assetLabels[state]"
                :count="summary[state]"
                description="件资产 · 点击查看"
                :icon="stateIcons[state]"
                :icon-style="stateIconStyles[state]"
                :show-arrow="hasAuth('module_asset:item:query')"
              />
            </button>
          </div>
        </div>
        <div v-if="total" class="asset-distribution" aria-label="资产状态占比">
          <span
            v-for="state in states"
            :key="state"
            :class="`distribution-${state}`"
            :style="{ flexGrow: summary[state] }"
            :title="`${assetLabels[state]} ${summary[state]} 件`"
          />
        </div>
        <ElEmpty
          v-if="total === 0"
          description="还没有资产，登记第一件设备即可开始管理。"
          :image-size="90"
        />
      </template>
      <ElSkeleton v-else :rows="3" :loading="loading" animated />
    </ElCard>
    <ElCard v-if="canApplications" class="asset-overview-card" shadow="hover">
      <template #header>
        <div class="asset-panel-title">
          <h2>待处理申请</h2>
          <ElButton
            link
            type="primary"
            @click="router.push({ path: '/asset/applications', query: { state: 'PENDING' } })"
            >查看全部 <FaSvgIcon icon="ri:arrow-right-s-line"
          /></ElButton>
        </div>
      </template>
      <ElAlert v-if="applicationError" :title="applicationError" type="error" :closable="false" />
      <ElTable v-else :data="pending" empty-text="当前没有待审批申请">
        <ElTableColumn label="资产" min-width="170"
          ><template #default="{ row }"
            ><div class="asset-name">{{ row.asset_name }}</div>
            <span class="asset-muted">{{ row.asset_code }}</span></template
          ></ElTableColumn
        >
        <ElTableColumn label="申请类型" width="110"
          ><template #default="{ row }">{{
            typeLabels[row.application_type as ApplicationType]
          }}</template></ElTableColumn
        >
        <ElTableColumn prop="applicant_name" label="申请人" width="120" />
        <ElTableColumn prop="reason" label="申请理由" min-width="180" show-overflow-tooltip />
        <ElTableColumn prop="created_time" label="提交时间" width="175" />
      </ElTable>
    </ElCard>
    <WatchStatus />
  </AssetPage>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { useAuth } from "@/hooks/core/useAuth";
import {
  AssetAPI,
  assetLabels,
  assetError,
  typeLabels,
  type AssetState,
  type AssetApplication,
  type ApplicationType,
} from "@/api/module_asset/asset";
import AssetPage from "../components/AssetPage.vue";
import WatchStatus from "../components/WatchStatus.vue";
defineOptions({ name: "AssetOverview" });
const router = useRouter();
const { hasAuth } = useAuth();
const states: AssetState[] = ["AVAILABLE", "RESERVED", "IN_USE", "MAINTENANCE", "RETIRED"];
const stateIcons: Record<AssetState, string> = {
  AVAILABLE: "ri:archive-2-line",
  RESERVED: "ri:hand-coin-line",
  IN_USE: "ri:user-received-line",
  MAINTENANCE: "ri:tools-line",
  RETIRED: "ri:inbox-unarchive-line",
};
const stateIconStyles: Record<AssetState, string> = {
  AVAILABLE: "bg-success",
  RESERVED: "bg-warning",
  IN_USE: "bg-primary",
  MAINTENANCE: "bg-warning",
  RETIRED: "bg-info",
};
const summary = ref<Record<AssetState, number>>();
const total = computed(() =>
  summary.value ? Object.values(summary.value).reduce((a, b) => a + b, 0) : undefined
);
const pending = ref<AssetApplication[]>([]);
const loading = ref(false);
const error = ref("");
const applicationError = ref("");
const canApplications = computed(() =>
  ["query", "approve", "reject"].some((p) => hasAuth(`module_asset:application:${p}`))
);
async function load() {
  if (loading.value) return;
  loading.value = true;
  error.value = "";
  applicationError.value = "";
  const results = await Promise.allSettled([
    AssetAPI.summary(),
    canApplications.value
      ? AssetAPI.applications({ page_no: 1, page_size: 6, application_state: "PENDING" })
      : Promise.resolve(null),
  ]);
  const [stats, applications] = results;
  if (stats.status === "fulfilled") summary.value = stats.value;
  else {
    error.value = assetError(stats.reason);
    summary.value = undefined;
  }
  if (applications.status === "fulfilled") pending.value = applications.value?.items ?? [];
  else applicationError.value = assetError(applications.reason);
  loading.value = false;
}
onMounted(load);
</script>
<style scoped lang="scss">
.asset-overview-card + .asset-overview-card,
.asset-overview-card + :deep(.watch-panel) {
  margin-top: 12px;
}

.asset-overview-card :deep(.el-card__header) {
  padding: 16px 20px;
}

.asset-overview-card :deep(.asset-panel-title) {
  margin: 0;
}

.asset-overview-card h2 {
  font-size: 16px;
}

.asset-summary-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
}
@media (width <= 1200px) {
  .asset-summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (width <= 640px) {
  .asset-summary-grid {
    grid-template-columns: 1fr;
  }
}

.asset-summary-button {
  width: 100%;
  padding: 0;
  text-align: left;
  cursor: pointer;
  background: transparent;
  border: 0;
}

.asset-summary-button:disabled {
  cursor: default;
}

.asset-summary-button:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
}

.asset-summary-button :deep(.fa-card) {
  height: 108px;
}

.asset-distribution {
  display: flex;
  gap: 3px;
  height: 6px;
  margin: 16px 0 0;
  overflow: hidden;
  border-radius: 4px;
}

.asset-distribution span {
  flex-basis: 0;
  min-width: 0;
}

.distribution-AVAILABLE {
  background: var(--el-color-success);
}

.distribution-RESERVED {
  background: var(--el-color-warning);
}

.distribution-IN_USE {
  background: var(--el-color-primary);
}

.distribution-MAINTENANCE {
  background: var(--el-color-warning);
}

.distribution-RETIRED {
  background: var(--el-color-info);
}
</style>
