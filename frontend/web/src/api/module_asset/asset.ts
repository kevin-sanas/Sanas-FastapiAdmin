import { request } from "@utils";

export type AssetState = "AVAILABLE" | "RESERVED" | "IN_USE" | "MAINTENANCE" | "RETIRED";
export type LoanState =
  | "PENDING_HANDOVER"
  | "PENDING_RECEIPT"
  | "IN_USE"
  | "COMPLETED"
  | "CANCELLED";
export type ApplicationType = "ISSUE" | "RETURN" | "REPAIR";
export type ApplicationState = "PENDING" | "APPROVED" | "REJECTED" | "CANCELLED" | "COMPLETED";
export interface WatchSnapshot {
  state: "disabled" | "not_configured" | "live" | "stale" | "unavailable";
  fetched_at: string | null;
  age_seconds: number | null;
  monitors: {
    id: number;
    name: string;
    status: "up" | "down" | "pending" | "maintenance" | "unknown";
    response_ms: number | null;
    uptime_24h_percent: number | null;
  }[];
}
export interface AssetPage<T> {
  items: T[];
  total: number;
  page_no: number;
  page_size: number;
}
export interface Category {
  id: number;
  code: string;
  name: string;
  parent_id: number | null;
  status: string;
}
export interface AssetItem {
  id: number;
  asset_code: string;
  name: string;
  category_id: number;
  category_name: string | null;
  asset_state: AssetState;
  custodian_id: number | null;
  custodian_name: string | null;
  reserved_for_name: string | null;
  custodian_dept_id: number | null;
  row_version: number;
  status: string;
  purchase_date: string | null;
  purchase_amount: number | null;
  created_time: string;
}
export interface AssetApplication {
  id: number;
  request_no: string;
  asset_id: number;
  asset_name: string;
  asset_code: string;
  applicant_id: number;
  applicant_name: string;
  application_type: ApplicationType;
  application_state: ApplicationState;
  reason: string;
  created_time: string;
  completed_at: string | null;
  completion_note: string | null;
  review_note: string | null;
  reviewed_at: string | null;
  reviewer_name: string | null;
  loan_id: number | null;
  loan_state: LoanState | null;
  loan_approved_at: string | null;
  loan_handed_at: string | null;
  loan_handover_note: string | null;
  loan_received_at: string | null;
  loan_returned_at: string | null;
  loan_return_note: string | null;
  loan_close_reason: string | null;
  loan_cancel_reason: string | null;
  loan_is_legacy: boolean | null;
  pending_return_id: number | null;
}
export interface AuditLog {
  id: number;
  asset_id: number;
  asset_name: string;
  asset_code: string;
  actor_name: string | null;
  action: string;
  created_time: string;
  before_json: Record<string, unknown> | null;
  after_json: Record<string, unknown> | null;
}
export interface AssetQuery {
  page_no: number;
  page_size: number;
  asset_state?: AssetState;
  keyword?: string;
  category_id?: number;
}
export interface ItemInput {
  asset_code: string;
  name: string;
  category_id: number;
  purchase_date: string | null;
  purchase_amount: number | null;
}

async function get<T>(path: string, params?: object): Promise<T> {
  const response = await request<ApiResponse<T>>({ url: `/asset/${path}`, method: "get", params });
  return response.data.data as T;
}
async function post<T>(path: string, data: object): Promise<T> {
  const response = await request<ApiResponse<T>>({ url: `/asset/${path}`, method: "post", data });
  return response.data.data as T;
}
export const AssetAPI = {
  monitoring: () => get<WatchSnapshot>("dashboard/monitoring"),
  summary: () => get<Record<AssetState, number>>("dashboard/summary"),
  categories: (keyword?: string) =>
    get<AssetPage<Category>>("category/list", { page_no: 1, page_size: 100, keyword }),
  createCategory: (data: {
    name: string;
    code: string;
    parent_id: number | null;
    sort_order: number;
  }) => post<Category>("category/create", data),
  items: (query: AssetQuery) => get<AssetPage<AssetItem>>("item/list", query),
  detail: (id: number) => get<AssetItem>(`item/detail/${id}`),
  createItem: (data: ItemInput) => post<AssetItem>("item/create", data),
  submit: (data: {
    asset_id: number;
    application_type: ApplicationType;
    reason: string;
    idempotency_key: string;
  }) => post<AssetApplication>("application/create", data),
  applications: (query: {
    page_no: number;
    page_size: number;
    application_state?: ApplicationState;
  }) => get<AssetPage<AssetApplication>>("application/list", query),
  decide: (
    id: number,
    action: "approve" | "reject",
    data: { review_note: string | null; idempotency_key: string }
  ) => post<AssetApplication>(`application/${action}/${id}`, data),
  cancel: (id: number) => post<AssetApplication>(`application/cancel/${id}`, {}),
  completeRepair: (id: number, completion_note: string) =>
    post<AssetApplication>(`application/complete-repair/${id}`, { completion_note }),
  handover: (id: number, note: string) => post(`loan/handover/${id}`, { note }),
  receive: (id: number) => post(`loan/receive/${id}`, {}),
  cancelHandover: (id: number, reason: string) => post(`loan/cancel-handover/${id}`, { reason }),
  retire: (id: number, row_version: number) =>
    post<AssetItem>(`item/retire/${id}`, { row_version }),
  audit: (query: { page_no: number; page_size: number; asset_id?: number; keyword?: string }) =>
    get<AssetPage<AuditLog>>("audit/list", query),
};

export const assetLabels: Record<AssetState, string> = {
  AVAILABLE: "在库",
  RESERVED: "待交付",
  IN_USE: "领用中",
  MAINTENANCE: "维修中",
  RETIRED: "已报废",
};
export const loanLabels: Record<LoanState, string> = {
  PENDING_HANDOVER: "待管理员交付",
  PENDING_RECEIPT: "待员工签收",
  IN_USE: "领用中",
  COMPLETED: "已完结",
  CANCELLED: "交付已撤销",
};
export const applicationLabels: Record<ApplicationState, string> = {
  PENDING: "待审批",
  APPROVED: "已批准",
  REJECTED: "已驳回",
  CANCELLED: "已取消",
  COMPLETED: "维修完成",
};
export const typeLabels: Record<ApplicationType, string> = {
  ISSUE: "领用",
  RETURN: "归还",
  REPAIR: "维修",
};
export const stateColors: Record<AssetState, "success" | "primary" | "warning" | "info"> = {
  AVAILABLE: "success",
  RESERVED: "warning",
  IN_USE: "primary",
  MAINTENANCE: "warning",
  RETIRED: "info",
};
export function assetError(error: unknown): string {
  return error instanceof Error ? error.message : "操作失败，请稍后重试";
}
