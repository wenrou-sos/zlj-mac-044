/* ============================================================
 * 印刷厂生产管理系统 —— Vue 3 + Element Plus（无构建，CDN 本地化）
 * ============================================================ */
const { createApp, ref, reactive, computed, onMounted, watch, nextTick } = Vue;
const { ElMessage, ElMessageBox } = ElementPlus;

/* ---------------- 常量 ---------------- */
const ORDER_STATUS = {
    pending:   { label: '待排产', type: 'info' },
    prepress:  { label: '印前中', type: '' },
    printing:  { label: '印刷中', type: 'warning' },
    binding:   { label: '装订中', type: 'success' },
    completed: { label: '已完成', type: 'success' },
    rework:    { label: '返工中', type: 'danger' },
};
const STAGE_STATUS = {
    not_started: { label: '未开始', type: 'info' },
    in_progress: { label: '进行中', type: '' },
    done:        { label: '已完成', type: 'success' },
    rework:      { label: '返工中', type: 'danger' },
};
const STAGES = [
    { key: 'prepress', label: '印前', status: 'prepress_status', progress: 'prepress_progress', note: 'prepress_note' },
    { key: 'printing', label: '印刷', status: 'printing_status', progress: 'printing_progress', note: 'printing_note' },
    { key: 'binding',  label: '装订', status: 'binding_status',  progress: 'binding_progress',  note: 'binding_note' },
];
const PAPER_TYPES = { coated: '铜版纸', offset: '胶版纸', whiteboard: '白卡纸', kraft: '牛皮纸', special: '特种纸' };
const MACHINE_STATUS = { running: { label: '生产中', type: 'success' }, idle: { label: '空闲', type: 'info' }, maintenance: { label: '维保中', type: 'warning' } };
const REWORK_STATUS = { open: { label: '待处理', type: 'danger' }, processing: { label: '返工中', type: 'warning' }, closed: { label: '已闭环', type: 'success' } };
const REWORK_REASONS = { color: '色差', register: '套印不准', scratch: '划伤/脏点', binding: '装订错误', material: '材料问题', other: '其他' };
const WARNING_LEVEL = {
    overdue:   { label: '已逾期', type: 'danger' },
    urgent:    { label: '紧急', type: 'danger' },
    warning:   { label: '预警', type: 'warning' },
    normal:    { label: '正常', type: 'success' },
    completed: { label: '已完工', type: 'info' },
};

/* ---------------- API 封装 ---------------- */
async function api(method, url, body) {
    const opt = { method, headers: {} };
    if (body !== undefined) {
        opt.headers['Content-Type'] = 'application/json';
        opt.body = JSON.stringify(body);
    }
    const res = await fetch('/api' + url, opt);
    if (!res.ok) {
        let msg = `请求失败 (${res.status})`;
        try {
            const data = await res.json();
            if (data.detail) msg = data.detail;
            else msg = Object.entries(data).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join('；') : v}`).join('；');
        } catch (e) { /* ignore */ }
        throw new Error(msg);
    }
    if (res.status === 204) return null;
    return res.json();
}

const apiGet = (url) => api('GET', url);
const apiPost = (url, body) => api('POST', url, body || {});
const apiPut = (url, body) => api('PUT', url, body);
const apiPatch = (url, body) => api('PATCH', url, body);
const apiDel = (url) => api('DELETE', url);

function todayStr() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/* ============================================================
 * 视图一：生产看板
 * ============================================================ */
const Dashboard = {
    template: `
    <div v-loading="loading">
      <el-row :gutter="16">
        <el-col :span="6" v-for="card in cards" :key="card.key">
          <div class="stat-card" @click="card.to && go(card.to)">
            <div class="icon" :style="{ background: card.color }">{{ card.icon }}</div>
            <div>
              <div class="num">{{ card.value }}</div>
              <div class="label">{{ card.label }}</div>
            </div>
          </div>
        </el-col>
      </el-row>

      <el-row :gutter="16" style="margin-top:16px">
        <el-col :span="16">
          <div class="panel">
            <div class="panel-title">交期预警
              <el-radio-group v-model="warnTab" size="small">
                <el-radio-button label="overdue">逾期 ({{ data.overdue_orders.length }})</el-radio-button>
                <el-radio-button label="urgent">紧急 ≤2天</el-radio-button>
                <el-radio-button label="warning">预警 ≤5天</el-radio-button>
              </el-radio-group>
            </div>
            <el-table :data="warnList" size="small" @row-click="openOrder" style="cursor:pointer" empty-text="暂无该级别预警订单，干得漂亮！">
              <el-table-column prop="order_no" label="订单编号" width="160"></el-table-column>
              <el-table-column prop="product_name" label="产品名称" min-width="200"></el-table-column>
              <el-table-column prop="customer_name" label="客户" width="180"></el-table-column>
              <el-table-column label="状态" width="100">
                <template #default="{ row }">
                  <el-tag :type="ORDER_STATUS[row.status].type" size="small">{{ ORDER_STATUS[row.status].label }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="due_date" label="交期" width="120"></el-table-column>
              <el-table-column label="剩余天数" width="110">
                <template #default="{ row }">
                  <span :class="daysClass(row.days_left)">{{ daysText(row.days_left) }}</span>
                </template>
              </el-table-column>
            </el-table>
          </div>

          <div class="panel">
            <div class="panel-title">近 7 日机台排产负荷（计划产量 / 份）</div>
            <div class="bar-chart">
              <div class="bar-wrap" v-for="d in data.weekly_load" :key="d.date">
                <div class="bar" :style="{ height: barHeight(d.planned_qty) + '%' }">
                  <span class="bar-val" v-if="d.planned_qty">{{ formatNum(d.planned_qty) }}</span>
                </div>
                <span class="bar-label">{{ d.date }}</span>
              </div>
            </div>
          </div>
        </el-col>

        <el-col :span="8">
          <div class="panel">
            <div class="panel-title">订单状态分布</div>
            <el-row :gutter="10">
              <el-col :span="8" v-for="(c, k) in data.status_counts" :key="k" style="margin-bottom:10px">
                <div style="text-align:center;border:1px solid #ebeef5;border-radius:8px;padding:10px 4px;cursor:pointer"
                     @click="$emit('go-orders', k)">
                  <div style="font-size:22px;font-weight:700" :style="{ color: ORDER_STATUS[k] ? '#303133' : '#999' }">{{ c }}</div>
                  <div class="muted">{{ ORDER_STATUS[k] ? ORDER_STATUS[k].label : k }}</div>
                </div>
              </el-col>
            </el-row>
          </div>

          <div class="panel">
            <div class="panel-title">机台概况</div>
            <el-row :gutter="10">
              <el-col :span="12" v-for="m in machines" :key="m.id" style="margin-bottom:10px">
                <div class="machine-card">
                  <div class="m-name">{{ m.name }}</div>
                  <div class="m-type">{{ m.machine_type }}</div>
                  <el-tag :type="MACHINE_STATUS[m.status].type" size="small">{{ MACHINE_STATUS[m.status].label }}</el-tag>
                </div>
              </el-col>
            </el-row>
          </div>

          <div class="panel">
            <div class="panel-title">
              纸张低库存
              <el-button link type="primary" size="small" @click="$emit('go', 'papers')">去处理 →</el-button>
            </div>
            <div v-if="!data.low_papers.length" class="muted">所有纸张库存均高于安全线</div>
            <div v-for="p in data.low_papers" :key="p.id" style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px dashed #ebeef5">
              <div>
                <div style="font-weight:600">{{ p.name }}</div>
                <div class="muted">{{ p.paper_type_display }} · {{ p.spec }}</div>
              </div>
              <div style="text-align:right">
                <div style="color:#f56c6c;font-weight:700">{{ formatNum(p.stock) }} 张</div>
                <div class="muted">安全线 {{ formatNum(p.safety_stock) }}</div>
              </div>
            </div>
          </div>
        </el-col>
      </el-row>
    </div>`,
    emits: ['go', 'go-orders', 'open-order'],
    setup(_, { emit }) {
        const loading = ref(false);
        const warnTab = ref('overdue');
        const data = reactive({
            summary: {}, status_counts: {}, overdue_orders: [], urgent_orders: [],
            warning_orders: [], low_papers: [], stage_stats: {}, weekly_load: [],
        });
        const machines = ref([]);

        const cards = computed(() => [
            { key: 'active', label: '在制订单', value: data.summary.active_orders ?? '-', icon: '📋', color: '#409eff', to: null },
            { key: 'overdue', label: '逾期订单', value: data.summary.overdue_count ?? '-', icon: '🚨', color: '#f56c6c', to: null },
            { key: 'rework', label: '未闭环返工', value: data.summary.open_rework_count ?? '-', icon: '🔧', color: '#e6a23c', to: 'reworks' },
            { key: 'low', label: '纸张低库存', value: data.summary.low_paper_count ?? '-', icon: '📦', color: '#909399', to: 'papers' },
        ]);

        const warnList = computed(() => ({
            overdue: data.overdue_orders, urgent: data.urgent_orders, warning: data.warning_orders,
        }[warnTab.value]));

        const maxLoad = computed(() => Math.max(1, ...data.weekly_load.map(d => d.planned_qty)));
        const barHeight = (v) => Math.round(v / maxLoad.value * 100);

        function daysText(d) { return d < 0 ? `逾期 ${-d} 天` : `剩 ${d} 天`; }
        function daysClass(d) { return d < 0 ? 'due-overdue' : d <= 2 ? 'due-urgent' : 'due-warning'; }
        function formatNum(n) { return Number(n).toLocaleString(); }
        function go(name) { emit('go', name); }
        function openOrder(row) { emit('open-order', row.id); }

        onMounted(async () => {
            loading.value = true;
            try {
                const [d, ms] = await Promise.all([apiGet('/dashboard/'), apiGet('/machines/')]);
                Object.assign(data, d);
                machines.value = ms;
                if (!data.overdue_orders.length) {
                    if (data.urgent_orders.length) warnTab.value = 'urgent';
                    else if (data.warning_orders.length) warnTab.value = 'warning';
                }
            } catch (e) { ElMessage.error(e.message); } finally { loading.value = false; }
        });

        return {
            loading, warnTab, data, machines, cards, warnList, ORDER_STATUS, MACHINE_STATUS,
            barHeight, daysText, daysClass, formatNum, go, openOrder,
        };
    },
};

/* 组件占位，后续文件片段注册 */
window.__APP_COMPONENTS__ = { Dashboard };

/* ============================================================
 * 视图二：订单管理
 * ============================================================ */
const Orders = {
    template: `
    <div v-loading="loading">
      <div class="panel">
        <el-form :inline="true" @submit.prevent>
          <el-form-item label="关键字">
            <el-input v-model="filters.keyword" placeholder="订单编号 / 产品名称" clearable style="width:200px" @keyup.enter="load"></el-input>
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="filters.status" placeholder="全部" clearable style="width:130px" @change="load">
              <el-option v-for="(s, k) in ORDER_STATUS" :key="k" :label="s.label" :value="k"></el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="交期">
            <el-select v-model="filters.warning" placeholder="全部" clearable style="width:130px" @change="load">
              <el-option label="已逾期" value="overdue"></el-option>
              <el-option label="紧急(≤2天)" value="urgent"></el-option>
              <el-option label="预警(≤5天)" value="warning"></el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="客户">
            <el-select v-model="filters.customer" placeholder="全部" clearable filterable style="width:180px" @change="load">
              <el-option v-for="c in customers" :key="c.id" :label="c.name" :value="c.id"></el-option>
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="load">查询</el-button>
            <el-button @click="reset">重置</el-button>
            <el-button type="success" @click="openCreate">+ 新建订单</el-button>
          </el-form-item>
        </el-form>

        <el-table :data="orders" @row-click="openDetail" style="cursor:pointer" border stripe>
          <el-table-column prop="order_no" label="订单编号" width="150"></el-table-column>
          <el-table-column prop="product_name" label="产品名称" min-width="190"></el-table-column>
          <el-table-column prop="customer_name" label="客户" width="170"></el-table-column>
          <el-table-column label="印数/用纸" width="160">
            <template #default="{ row }">
              <div>{{ formatNum(row.quantity) }} 份</div>
              <div class="muted">{{ formatNum(row.paper_consumption) }} 张</div>
              <div style="font-size:12px" :style="{ color: row.remaining_qty > 0 ? '#e6a23c' : '#67c23a' }">
                已领 {{ formatNum(row.received_qty) }} / 未领 {{ formatNum(row.remaining_qty) }}
              </div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="ORDER_STATUS[row.status].type" size="small">{{ ORDER_STATUS[row.status].label }}</el-tag>
              <el-badge v-if="row.open_rework_count" :value="'返'+row.open_rework_count" type="danger" style="margin-left:6px" />
            </template>
          </el-table-column>
          <el-table-column label="工序进度" width="230">
            <template #default="{ row }">
              <div v-if="row.progress">
                <div class="stage-timeline">
                  <template v-for="(st, i) in STAGES" :key="st.key">
                    <div class="stage-step" :class="stageClass(row, st.key)">
                      {{ st.label }}
                    </div>
                  </template>
                </div>
                <div class="progress-cell" v-if="activeStage(row)">
                  <el-progress :percentage="row.progress[activeStage(row).progress]" :status="progressStatus(row, activeStage(row).key)" :stroke-width="10"></el-progress>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="order_date" label="下单" width="110"></el-table-column>
          <el-table-column label="交期 / 剩余" width="130">
            <template #default="{ row }">
              <div>{{ row.due_date }}</div>
              <div :class="row.warning_level==='overdue' ? 'due-overdue' : row.warning_level==='urgent' ? 'due-urgent' : row.warning_level==='warning' ? 'due-warning' : ''">
                {{ row.days_left === null ? '已完工' : (row.days_left < 0 ? '逾期'+(-row.days_left)+'天' : '剩'+row.days_left+'天') }}
              </div>
            </template>
          </el-table-column>
          <el-table-column label="预警" width="90">
            <template #default="{ row }">
              <el-tag :type="WARNING_LEVEL[row.warning_level].type" size="small" effect="dark">{{ WARNING_LEVEL[row.warning_level].label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click.stop="openDetail(row)">详情</el-button>
              <el-button link type="warning" size="small" @click.stop="openEdit(row)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 新建/编辑订单 -->
      <el-dialog v-model="formVisible" :title="editing ? '编辑订单' : '新建订单'" width="620px">
        <el-form :model="form" label-width="92px">
          <el-form-item label="订单编号" required>
            <el-input v-model="form.order_no" :disabled="editing" placeholder="如 DD20260915-09"></el-input>
          </el-form-item>
          <el-form-item label="客户" required>
            <el-select v-model="form.customer" filterable placeholder="选择客户" style="width:100%">
              <el-option v-for="c in customers" :key="c.id" :label="c.name" :value="c.id"></el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="产品名称" required>
            <el-input v-model="form.product_name"></el-input>
          </el-form-item>
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="印数(份)" required>
                <el-input-number v-model="form.quantity" :min="1" :step="500" style="width:100%"></el-input-number>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="用纸量(张)">
                <el-input-number v-model="form.paper_consumption" :min="0" :step="100" style="width:100%"></el-input-number>
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="用纸" required>
            <el-select v-model="form.paper" filterable placeholder="选择纸张" style="width:100%">
              <el-option v-for="p in papers" :key="p.id"
                :label="p.name + ' ' + p.spec + '（库存 ' + formatNum(p.stock) + '张）'" :value="p.id"></el-option>
            </el-select>
          </el-form-item>
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="下单日期" required>
                <el-date-picker v-model="form.order_date" type="date" value-format="YYYY-MM-DD" style="width:100%"></el-date-picker>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="交货日期" required>
                <el-date-picker v-model="form.due_date" type="date" value-format="YYYY-MM-DD" style="width:100%"></el-date-picker>
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="备注">
            <el-input v-model="form.remark" type="textarea" :rows="2"></el-input>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="formVisible=false">取消</el-button>
          <el-button type="primary" @click="saveOrder">保存</el-button>
        </template>
      </el-dialog>

      <!-- 订单详情抽屉 -->
      <el-drawer v-model="detailVisible" size="62%" :title="'订单详情 — ' + (detail.order_no || '')">
        <template v-if="detail.id">
          <el-descriptions :column="3" border size="small" style="margin-bottom:16px">
            <el-descriptions-item label="客户">{{ detail.customer_name }}</el-descriptions-item>
            <el-descriptions-item label="产品">{{ detail.product_name }}</el-descriptions-item>
            <el-descriptions-item label="状态">
              <el-tag :type="ORDER_STATUS[detail.status].type" size="small">{{ ORDER_STATUS[detail.status].label }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="印数">{{ formatNum(detail.quantity) }} 份</el-descriptions-item>
            <el-descriptions-item label="用纸">{{ detail.paper_name }} / {{ formatNum(detail.paper_consumption) }} 张</el-descriptions-item>
            <el-descriptions-item label="交期">
              {{ detail.due_date }}
              <el-tag :type="WARNING_LEVEL[detail.warning_level].type" size="small" effect="dark" style="margin-left:6px">
                {{ detail.days_left === null ? '已完工' : WARNING_LEVEL[detail.warning_level].label + (detail.days_left<0 ? ' '+(-detail.days_left)+'天' : ' '+detail.days_left+'天') }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="备注" :span="3">{{ detail.remark || '—' }}</el-descriptions-item>
          </el-descriptions>

          <div class="panel" style="box-shadow:none;border:1px solid #ebeef5">
            <div class="panel-title">工序进度（印前 → 印刷 → 装订）
              <el-button type="primary" size="small" @click="openProgress">更新进度</el-button>
            </div>
            <el-row :gutter="16">
              <el-col :span="8" v-for="st in STAGES" :key="st.key">
                <el-card shadow="never" style="text-align:center">
                  <div style="font-weight:600;margin-bottom:8px">{{ st.label }}</div>
                  <el-tag :type="STAGE_STATUS[detail.progress[st.status]].type" size="small">{{ STAGE_STATUS[detail.progress[st.status]].label }}</el-tag>
                  <el-progress :percentage="detail.progress[st.progress]" :status="progressStatus(detail, st.key)" style="margin-top:12px"></el-progress>
                  <div class="muted" style="margin-top:6px;min-height:32px">{{ detail.progress[st.note] || '—' }}</div>
                </el-card>
              </el-col>
            </el-row>
          </div>

          <div class="panel" style="box-shadow:none;border:1px solid #ebeef5;margin-top:16px">
            <div class="panel-title">纸张领料（{{ detail.paper_name }}）
              <span>
                <el-button type="warning" size="small" plain @click="openReceive" :disabled="detail.remaining_qty <= 0">分批领料</el-button>
                <el-button type="warning" size="small" @click="receiveAll" :disabled="detail.remaining_qty <= 0">一键领足</el-button>
              </span>
            </div>
            <el-row :gutter="12" style="margin-bottom:10px;text-align:center">
              <el-col :span="6">
                <div class="muted">用纸量</div>
                <div style="font-size:18px;font-weight:700">{{ formatNum(detail.paper_consumption) }} 张</div>
              </el-col>
              <el-col :span="6">
                <div class="muted">已领</div>
                <div style="font-size:18px;font-weight:700;color:#67c23a">{{ formatNum(detail.received_qty) }} 张</div>
              </el-col>
              <el-col :span="6">
                <div class="muted">未领</div>
                <div style="font-size:18px;font-weight:700" :style="{ color: detail.remaining_qty > 0 ? '#e6a23c' : '#67c23a' }">
                  {{ formatNum(detail.remaining_qty) }} 张
                </div>
              </el-col>
              <el-col :span="6">
                <div class="muted">当前库存</div>
                <div style="font-size:18px;font-weight:700" :style="{ color: detail.paper_stock < detail.remaining_qty ? '#f56c6c' : '#303133' }">
                  {{ formatNum(detail.paper_stock) }} 张
                </div>
              </el-col>
            </el-row>
            <el-progress :percentage="receivePercent" :status="detail.remaining_qty <= 0 ? 'success' : ''"></el-progress>
            <el-alert v-if="detail.remaining_qty > 0 && detail.paper_stock < detail.remaining_qty"
              type="error" :closable="false" style="margin-top:10px"
              :title="'库存不足：未领 ' + formatNum(detail.remaining_qty) + ' 张，当前库存 ' + formatNum(detail.paper_stock) + ' 张，还差 ' + formatNum(detail.remaining_qty - detail.paper_stock) + ' 张'"></el-alert>
            <el-table :data="detail.paper_transactions" size="small" border max-height="220" style="margin-top:10px" empty-text="暂无领料记录">
              <el-table-column prop="tx_date" label="日期" width="110"></el-table-column>
              <el-table-column label="类型" width="80">
                <template #default="{ row }">
                  <el-tag :type="row.tx_type==='in' ? 'success' : 'warning'" size="small">{{ row.tx_type_display }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="数量(张)" width="120">
                <template #default="{ row }">
                  <span :style="{ color: row.tx_type==='in' ? '#67c23a' : '#e6a23c', fontWeight: 600 }">
                    {{ row.tx_type === 'in' ? '+' : '-' }}{{ formatNum(row.quantity) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="note" label="备注" min-width="180"></el-table-column>
            </el-table>
          </div>

          <el-row :gutter="16" style="margin-top:16px">
            <el-col :span="13">
              <div class="panel" style="box-shadow:none;border:1px solid #ebeef5">
                <div class="panel-title">机台排产
                  <el-button type="primary" size="small" @click="openSchedule">+ 排产</el-button>
                </div>
                <el-table :data="detail.schedules" size="small" border empty-text="暂无排产">
                  <el-table-column prop="planned_date" label="日期" width="100"></el-table-column>
                  <el-table-column prop="shift" label="班次" width="64"></el-table-column>
                  <el-table-column prop="machine_name" label="机台" min-width="150"></el-table-column>
                  <el-table-column label="计划/实际" width="120">
                    <template #default="{ row }">
                      {{ formatNum(row.planned_qty) }} / {{ formatNum(row.actual_qty) }}
                    </template>
                  </el-table-column>
                  <el-table-column label="完成" width="70">
                    <template #default="{ row }">
                      <el-checkbox :model-value="row.done" @click.stop="toggleSchedule(row)"></el-checkbox>
                    </template>
                  </el-table-column>
                </el-table>
              </div>
            </el-col>
            <el-col :span="11">
              <div class="panel" style="box-shadow:none;border:1px solid #ebeef5">
                <div class="panel-title">返工跟踪
                  <el-button type="danger" size="small" plain @click="openRework">+ 返工单</el-button>
                </div>
                <el-timeline v-if="detail.reworks.length">
                  <el-timeline-item v-for="r in detail.reworks" :key="r.id"
                    :type="r.status==='closed' ? 'success' : r.status==='processing' ? 'warning' : 'danger'"
                    :timestamp="r.found_at + ' 发现' + (r.closed_at ? ' / '+r.closed_at+' 闭环' : '')">
                    <div style="font-weight:600">
                      {{ r.stage_display }} · {{ r.reason_display }} · {{ formatNum(r.qty) }}份
                      <el-tag :type="REWORK_STATUS[r.status].type" size="small" style="margin-left:6px">{{ r.status_display }}</el-tag>
                    </div>
                    <div class="muted" style="margin:4px 0">{{ r.description }}</div>
                    <div v-if="r.result" style="font-size:13px">处理结果：{{ r.result }}</div>
                    <div class="muted" style="font-size:12px">责任人：{{ r.handler || '—' }}</div>
                  </el-timeline-item>
                </el-timeline>
                <div v-else class="muted">暂无返工记录</div>
              </div>
            </el-col>
          </el-row>
        </template>
      </el-drawer>

      <!-- 分批领料 -->
      <el-dialog v-model="receiveDialog" :title="'订单领料 — ' + (detail.order_no || '')" width="480px">
        <el-form label-width="90px">
          <el-form-item label="纸张">
            <span>{{ detail.paper_name }}</span>
          </el-form-item>
          <el-form-item label="领料进度">
            <span>
              已领 <b style="color:#67c23a">{{ formatNum(detail.received_qty) }}</b> 张 /
              用纸量 {{ formatNum(detail.paper_consumption) }} 张，
              未领 <b style="color:#e6a23c">{{ formatNum(detail.remaining_qty) }}</b> 张
            </span>
          </el-form-item>
          <el-form-item label="当前库存">
            <span :style="{ color: detail.paper_stock < detail.remaining_qty ? '#f56c6c' : '#303133', fontWeight: 600 }">
              {{ formatNum(detail.paper_stock) }} 张
            </span>
            <span v-if="detail.paper_stock < detail.remaining_qty" style="color:#f56c6c;font-size:12px;margin-left:8px">
              还差 {{ formatNum(detail.remaining_qty - detail.paper_stock) }} 张
            </span>
          </el-form-item>
          <el-form-item label="本次领料" required>
            <el-input-number v-model="receiveForm.quantity" :min="1" :max="detail.remaining_qty" :step="500" style="width:100%"></el-input-number>
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="receiveForm.note" placeholder="生产领料"></el-input>
          </el-form-item>
          <el-alert v-if="receiveForm.quantity > detail.paper_stock" type="error" :closable="false"
            :title="'库存不足：本次需领 ' + formatNum(receiveForm.quantity) + ' 张，当前库存 ' + formatNum(detail.paper_stock) + ' 张，还差 ' + formatNum(receiveForm.quantity - detail.paper_stock) + ' 张'"></el-alert>
        </el-form>
        <template #footer>
          <el-button @click="receiveDialog=false">取消</el-button>
          <el-button type="warning" @click="doReceive">确认领料</el-button>
        </template>
      </el-dialog>

      <!-- 更新工序进度 -->
      <el-dialog v-model="progressDialog" title="更新工序进度" width="560px">
        <el-form label-width="70px">
          <el-form-item v-for="st in STAGES" :key="st.key" :label="st.label">
            <div style="width:100%">
              <el-radio-group v-model="pform[st.status]" size="small" style="margin-bottom:10px">
                <el-radio-button v-for="(ss, sk) in STAGE_STATUS" :key="sk" :label="sk"
                  :disabled="sk==='rework' || (sk==='done' && !canMarkDone(st.key))">{{ ss.label }}</el-radio-button>
              </el-radio-group>
              <el-slider v-model="pform[st.progress]" :show-input="true" :max="100"></el-slider>
              <el-input v-model="pform[st.note]" placeholder="工序说明（如：正在调墨/待覆膜）" size="small" style="margin-top:6px"></el-input>
            </div>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="progressDialog=false">取消</el-button>
          <el-button type="primary" @click="saveProgress">保存</el-button>
        </template>
      </el-dialog>

      <!-- 排产对话框 -->
      <el-dialog v-model="schedDialog" title="新增排产" width="500px">
        <el-form :model="sform" label-width="82px">
          <el-form-item label="机台" required>
            <el-select v-model="sform.machine" style="width:100%">
              <el-option v-for="m in machines" :key="m.id" :label="m.name+'（'+m.machine_type+'）'" :value="m.id"></el-option>
            </el-select>
          </el-form-item>
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="计划日期" required>
                <el-date-picker v-model="sform.planned_date" type="date" value-format="YYYY-MM-DD" style="width:100%"></el-date-picker>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="班次">
                <el-select v-model="sform.shift" style="width:100%">
                  <el-option label="白班" value="白班"></el-option>
                  <el-option label="夜班" value="夜班"></el-option>
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="计划产量">
                <el-input-number v-model="sform.planned_qty" :min="0" :step="1000" style="width:100%"></el-input-number>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="实际产量">
                <el-input-number v-model="sform.actual_qty" :min="0" :step="1000" style="width:100%"></el-input-number>
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="备注">
            <el-input v-model="sform.remark" placeholder="如：专色印刷 / 待纸"></el-input>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="schedDialog=false">取消</el-button>
          <el-button type="primary" @click="saveSchedule">保存</el-button>
        </template>
      </el-dialog>

      <!-- 返工单对话框 -->
      <el-dialog v-model="reworkDialog" title="登记返工单" width="520px">
        <el-form :model="rform" label-width="82px">
          <el-form-item label="返工工序" required>
            <el-select v-model="rform.stage" style="width:100%">
              <el-option v-for="st in STAGES" :key="st.key" :label="st.label" :value="st.key"></el-option>
            </el-select>
          </el-form-item>
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="返工原因" required>
                <el-select v-model="rform.reason" style="width:100%">
                  <el-option v-for="(v, k) in REWORK_REASONS" :key="k" :label="v" :value="k"></el-option>
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="返工数量" required>
                <el-input-number v-model="rform.qty" :min="1" :step="100" style="width:100%"></el-input-number>
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="责任人">
            <el-input v-model="rform.handler"></el-input>
          </el-form-item>
          <el-form-item label="发现日期" required>
            <el-date-picker v-model="rform.found_at" type="date" value-format="YYYY-MM-DD" style="width:100%"></el-date-picker>
          </el-form-item>
          <el-form-item label="问题描述" required>
            <el-input v-model="rform.description" type="textarea" :rows="3"></el-input>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="reworkDialog=false">取消</el-button>
          <el-button type="danger" @click="saveRework">提交返工单</el-button>
        </template>
      </el-dialog>
    </div>`,
    props: ['autoStatus'],
    emits: ['refresh-dashboard'],
    setup(props, { emit }) {
        const loading = ref(false);
        const orders = ref([]);
        const customers = ref([]);
        const papers = ref([]);
        const machines = ref([]);
        const filters = reactive({ keyword: '', status: '', warning: '', customer: '' });

        const formVisible = ref(false);
        const editing = ref(null);
        const form = reactive({ order_no: '', customer: null, product_name: '', quantity: 5000, paper: null, paper_consumption: 0, order_date: todayStr(), due_date: '', remark: '' });

        const detailVisible = ref(false);
        const detail = ref({});

        const progressDialog = ref(false);
        const pform = reactive({});

        const schedDialog = ref(false);
        const sform = reactive({ machine: null, planned_date: todayStr(), shift: '白班', planned_qty: 0, actual_qty: 0, remark: '' });

        const reworkDialog = ref(false);
        const rform = reactive({ stage: 'printing', reason: 'color', qty: 100, handler: '', found_at: todayStr(), description: '' });

        const receiveDialog = ref(false);
        const receiveForm = reactive({ quantity: 0, note: '' });

        // 领料进度百分比（已领/用纸量）
        const receivePercent = computed(() => {
            const total = detail.value.paper_consumption || 0;
            if (!total) return 0;
            return Math.min(100, Math.round((detail.value.received_qty || 0) / total * 100));
        });

        function formatNum(n) { return Number(n || 0).toLocaleString(); }

        function stageClass(row, key) {
            const s = row.progress[key + '_status'];
            if (s === 'done') return 'done';
            if (s === 'rework') return 'rework';
            if (s === 'in_progress') return 'active';
            return '';
        }
        function activeStage(row) {
            return STAGES.find(st => row.progress[st.status] === 'in_progress' || row.progress[st.status] === 'rework');
        }
        function progressStatus(row, key) {
            const s = row.progress[key + '_status'];
            if (s === 'rework') return 'exception';
            if (s === 'done') return 'success';
            return '';
        }

        // 工序顺序：印刷完成要求印前完成；装订完成要求印前、印刷都完成
        function canMarkDone(stage) {
            if (stage === 'prepress') return true;
            if (stage === 'printing') return pform['prepress_status'] === 'done';
            return pform['prepress_status'] === 'done' && pform['printing_status'] === 'done';
        }

        async function load() {
            loading.value = true;
            try {
                const qs = new URLSearchParams();
                Object.entries(filters).forEach(([k, v]) => v && qs.append(k, v));
                orders.value = await apiGet('/orders/?' + qs.toString());
            } catch (e) { ElMessage.error(e.message); } finally { loading.value = false; }
        }
        function reset() {
            Object.assign(filters, { keyword: '', status: '', warning: '', customer: '' });
            load();
        }

        function openCreate() {
            editing.value = null;
            Object.assign(form, { order_no: '', customer: null, product_name: '', quantity: 5000, paper: null, paper_consumption: 0, order_date: todayStr(), due_date: '', remark: '' });
            formVisible.value = true;
        }
        function openEdit(row) {
            editing.value = row;
            Object.assign(form, {
                order_no: row.order_no, customer: row.customer, product_name: row.product_name,
                quantity: row.quantity, paper: row.paper, paper_consumption: row.paper_consumption,
                order_date: row.order_date, due_date: row.due_date, remark: row.remark || '',
            });
            formVisible.value = true;
        }
        async function saveOrder() {
            if (!form.order_no || !form.customer || !form.product_name || !form.paper || !form.due_date) {
                ElMessage.warning('请填写完整必填项'); return;
            }
            try {
                if (editing.value) {
                    await apiPatch('/orders/' + editing.value.id + '/', {
                        customer: form.customer, product_name: form.product_name, quantity: form.quantity,
                        paper: form.paper, paper_consumption: form.paper_consumption,
                        order_date: form.order_date, due_date: form.due_date, remark: form.remark,
                    });
                    ElMessage.success('订单已更新');
                } else {
                    await apiPost('/orders/', { ...form });
                    ElMessage.success('订单已创建，工序进度已自动初始化');
                }
                formVisible.value = false;
                load();
                emit('refresh-dashboard');
            } catch (e) { ElMessage.error(e.message); }
        }

        async function openDetail(rowOrId) {
            const id = typeof rowOrId === 'number' ? rowOrId : rowOrId.id;
            try {
                detail.value = await apiGet('/orders/' + id + '/');
                detailVisible.value = true;
            } catch (e) { ElMessage.error(e.message); }
        }
        async function refreshDetail() {
            detail.value = await apiGet('/orders/' + detail.value.id + '/');
        }

        function openProgress() {
            const p = detail.value.progress;
            STAGES.forEach(st => {
                pform[st.status] = p[st.status];
                pform[st.progress] = p[st.progress];
                pform[st.note] = p[st.note] || '';
            });
            progressDialog.value = true;
        }
        async function saveProgress() {
            try {
                // 已完成必须 100；未开始必须 0
                for (const st of STAGES) {
                    if (pform[st.status] === 'done') pform[st.progress] = 100;
                    if (pform[st.status] === 'not_started') pform[st.progress] = 0;
                }
                await apiPatch('/orders/' + detail.value.id + '/progress/', { ...pform });
                ElMessage.success('工序进度已更新');
                progressDialog.value = false;
                await refreshDetail();
                load();
                emit('refresh-dashboard');
            } catch (e) { ElMessage.error(e.message); }
        }

        function openSchedule() {
            Object.assign(sform, { machine: machines.value[0]?.id || null, planned_date: todayStr(), shift: '白班', planned_qty: detail.value.quantity, actual_qty: 0, remark: '' });
            schedDialog.value = true;
        }
        async function saveSchedule() {
            if (!sform.machine) { ElMessage.warning('请选择机台'); return; }
            try {
                await apiPost('/schedules/', { order: detail.value.id, ...sform });
                ElMessage.success('排产已添加');
                schedDialog.value = false;
                await refreshDetail();
            } catch (e) { ElMessage.error(e.message); }
        }
        async function toggleSchedule(row) {
            try {
                const done = !row.done;
                await apiPatch('/schedules/' + row.id + '/', {
                    done,
                    actual_qty: done && !row.actual_qty ? row.planned_qty : row.actual_qty,
                });
                ElMessage.success(done ? '已标记完成' : '已取消完成');
                await refreshDetail();
            } catch (e) { ElMessage.error(e.message); }
        }

        function openRework() {
            Object.assign(rform, { stage: 'printing', reason: 'color', qty: 100, handler: '', found_at: todayStr(), description: '' });
            reworkDialog.value = true;
        }

        // ---------- 订单领料 ----------
        function openReceive() {
            // 默认带出全部未领数量，可改为分批；库存不足时对话框会提示还差多少张
            Object.assign(receiveForm, { quantity: detail.value.remaining_qty, note: '' });
            receiveDialog.value = true;
        }
        async function receiveAll() {
            try {
                await ElMessageBox.confirm(
                    `将按未领数量一次性领料出库 ${formatNum(detail.value.remaining_qty)} 张（${detail.value.paper_name}），确认？`,
                    '一键领足', { type: 'warning', confirmButtonText: '确认领料', cancelButtonText: '取消' });
            } catch (e) { return; }
            await submitReceive(null);  // 不传数量 = 服务端按全部未领出库
        }
        async function doReceive() {
            if (!receiveForm.quantity || receiveForm.quantity <= 0) {
                ElMessage.warning('请填写领料数量'); return;
            }
            await submitReceive(receiveForm.quantity);
        }
        async function submitReceive(qty) {
            try {
                const body = { note: receiveForm.note };
                if (qty) body.quantity = qty;
                const updated = await apiPost('/orders/' + detail.value.id + '/receive_paper/', body);
                detail.value = updated;  // 服务端返回最新订单（含已领/未领/库存/流水）
                ElMessage.success(updated.receive_message || '领料成功');
                receiveDialog.value = false;
                load();
                emit('refresh-dashboard');
            } catch (e) { ElMessage.error(e.message); }
        }
        async function saveRework() {
            if (!rform.description) { ElMessage.warning('请填写问题描述'); return; }
            try {
                await apiPost('/reworks/', { order: detail.value.id, ...rform });
                ElMessage.success('返工单已登记，订单已转入返工状态');
                reworkDialog.value = false;
                await refreshDetail();
                load();
                emit('refresh-dashboard');
            } catch (e) { ElMessage.error(e.message); }
        }

        watch(() => props.autoStatus, (v) => { if (v) { filters.status = v; load(); } });

        onMounted(async () => {
            if (props.autoStatus) filters.status = props.autoStatus;
            [customers.value, papers.value, machines.value] = await Promise.all([
                apiGet('/customers/'), apiGet('/papers/'), apiGet('/machines/'),
            ]);
            load();
        });

        return {
            loading, orders, customers, papers, machines, filters,
            formVisible, editing, form, detailVisible, detail,
            progressDialog, pform, schedDialog, sform, reworkDialog, rform,
            receiveDialog, receiveForm, receivePercent,
            ORDER_STATUS, STAGE_STATUS, STAGES, REWORK_STATUS, REWORK_REASONS, WARNING_LEVEL,
            formatNum, stageClass, activeStage, progressStatus, canMarkDone,
            load, reset, openCreate, openEdit, saveOrder, openDetail,
            openProgress, saveProgress, openSchedule, saveSchedule, toggleSchedule,
            openRework, saveRework, openReceive, receiveAll, doReceive,
        };
    },
};
window.__APP_COMPONENTS__.Orders = Orders;

/* ============================================================
 * 视图三：纸张材料（库存 + 出入库流水）
 * ============================================================ */
const Papers = {
    template: `
    <div v-loading="loading">
      <div class="panel">
        <div class="panel-title">
          纸张库存
          <el-button type="primary" size="small" @click="openEdit(null)">+ 新增纸张</el-button>
        </div>
        <el-table :data="papers" border stripe>
          <el-table-column prop="name" label="纸张名称" width="150"></el-table-column>
          <el-table-column label="类型" width="100">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">{{ PAPER_TYPES[row.paper_type] }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="spec" label="规格(克重/尺寸)" min-width="160"></el-table-column>
          <el-table-column label="库存(张)" width="140">
            <template #default="{ row }">
              <span :style="{ color: row.is_low ? '#f56c6c' : '#303133', fontWeight: row.is_low ? 700 : 600 }">
                {{ formatNum(row.stock) }}
              </span>
              <el-tag v-if="row.is_low" type="danger" size="small" effect="dark" style="margin-left:6px">低库存</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="safety_stock" label="安全库存" width="110">
            <template #default="{ row }">{{ formatNum(row.safety_stock) }}</template>
          </el-table-column>
          <el-table-column label="单价(元/张)" width="120">
            <template #default="{ row }">{{ Number(row.unit_price).toFixed(4) }}</template>
          </el-table-column>
          <el-table-column label="库存金额(元)" width="130">
            <template #default="{ row }">{{ formatNum(Math.round(row.stock * row.unit_price)) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="230" fixed="right">
            <template #default="{ row }">
              <el-button link type="success" size="small" @click="openStock(row,'in')">入库</el-button>
              <el-button link type="warning" size="small" @click="openStock(row,'out')">出库</el-button>
              <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="panel">
        <div class="panel-title">出入库流水</div>
        <el-table :data="txs" border size="small" max-height="420">
          <el-table-column prop="tx_date" label="日期" width="120"></el-table-column>
          <el-table-column label="类型" width="80">
            <template #default="{ row }">
              <el-tag :type="row.tx_type==='in' ? 'success' : 'warning'" size="small">{{ row.tx_type_display }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="paper_name" label="纸张" min-width="180"></el-table-column>
          <el-table-column label="数量(张)" width="120">
            <template #default="{ row }">
              <span :style="{ color: row.tx_type==='in' ? '#67c23a' : '#e6a23c', fontWeight: 600 }">
                {{ row.tx_type === 'in' ? '+' : '-' }}{{ formatNum(row.quantity) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="order_no" label="关联订单" width="160">
            <template #default="{ row }">{{ row.order_no || '—' }}</template>
          </el-table-column>
          <el-table-column prop="note" label="备注" min-width="160"></el-table-column>
        </el-table>
      </div>

      <!-- 新增/编辑纸张 -->
      <el-dialog v-model="formVisible" :title="editing ? '编辑纸张' : '新增纸张'" width="480px">
        <el-form :model="form" label-width="110px">
          <el-form-item label="纸张名称" required><el-input v-model="form.name"></el-input></el-form-item>
          <el-form-item label="类型" required>
            <el-select v-model="form.paper_type" style="width:100%">
              <el-option v-for="(v, k) in PAPER_TYPES" :key="k" :label="v" :value="k"></el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="规格"><el-input v-model="form.spec" placeholder="如 157g/889×1194"></el-input></el-form-item>
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="库存(张)">
                <el-input-number v-model="form.stock" :min="0" :step="500" style="width:100%" :disabled="editing"></el-input-number>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="安全库存">
                <el-input-number v-model="form.safety_stock" :min="0" :step="500" style="width:100%"></el-input-number>
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="单价(元/张)">
            <el-input-number v-model="form.unit_price" :min="0" :step="0.05" :precision="4" style="width:100%"></el-input-number>
          </el-form-item>
          <div v-if="editing" class="muted" style="padding-left:110px">库存数量请通过入库/出库操作变更，以保证流水完整</div>
        </el-form>
        <template #footer>
          <el-button @click="formVisible=false">取消</el-button>
          <el-button type="primary" @click="save">保存</el-button>
        </template>
      </el-dialog>

      <!-- 入/出库 -->
      <el-dialog v-model="stockVisible" :title="(stockType==='in'?'纸张入库':'纸张出库') + ' — ' + (stockRow?.name||'')" width="440px">
        <el-form :model="stockForm" label-width="90px">
          <el-form-item label="当前库存">
            <span style="font-weight:600">{{ stockRow ? formatNum(stockRow.stock) : '' }} 张</span>
          </el-form-item>
          <el-form-item :label="stockType==='in' ? '入库数量' : '出库数量'" required>
            <el-input-number v-model="stockForm.quantity" :min="1" :step="500" style="width:100%"></el-input-number>
          </el-form-item>
          <el-form-item v-if="stockType==='out'" label="关联订单">
            <el-select v-model="stockForm.order" clearable filterable placeholder="可选（仅列出使用该纸张的订单）" style="width:100%">
              <el-option v-for="o in orderOptions" :key="o.id"
                :label="o.order_no + ' ' + o.product_name + '（未领 ' + formatNum(o.remaining_qty) + ' 张）'" :value="o.id"></el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="stockForm.note" :placeholder="stockType==='in' ? '采购入库' : '生产领料'"></el-input>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="stockVisible=false">取消</el-button>
          <el-button :type="stockType==='in' ? 'success' : 'warning'" @click="doStock">确认</el-button>
        </template>
      </el-dialog>
    </div>`,
    emits: ['refresh-dashboard'],
    setup(_, { emit }) {
        const loading = ref(false);
        const papers = ref([]);
        const txs = ref([]);
        const activeOrders = ref([]);

        const formVisible = ref(false);
        const editing = ref(null);
        const form = reactive({ name: '', paper_type: 'coated', spec: '', stock: 0, safety_stock: 0, unit_price: 0.1 });

        const stockVisible = ref(false);
        const stockType = ref('in');
        const stockRow = ref(null);
        const stockForm = reactive({ quantity: 500, order: null, note: '' });

        // 出库可关联的订单：仅限用纸为当前纸张的订单（服务端同样校验，防挂错纸）
        const orderOptions = computed(() => {
            if (!stockRow.value) return [];
            return activeOrders.value.filter(o => o.paper === stockRow.value.id);
        });

        function formatNum(n) { return Number(n || 0).toLocaleString(); }

        async function load() {
            loading.value = true;
            try {
                [papers.value, txs.value, activeOrders.value] = await Promise.all([
                    apiGet('/papers/'), apiGet('/paper-transactions/'),
                    apiGet('/orders/').then(os => os.filter(o => o.status !== 'completed')),
                ]);
            } catch (e) { ElMessage.error(e.message); } finally { loading.value = false; }
        }

        function openEdit(row) {
            editing.value = row;
            if (row) Object.assign(form, { name: row.name, paper_type: row.paper_type, spec: row.spec, stock: Number(row.stock), safety_stock: Number(row.safety_stock), unit_price: Number(row.unit_price) });
            else Object.assign(form, { name: '', paper_type: 'coated', spec: '', stock: 0, safety_stock: 0, unit_price: 0.1 });
            formVisible.value = true;
        }
        async function save() {
            if (!form.name) { ElMessage.warning('请填写纸张名称'); return; }
            try {
                if (editing.value) {
                    await apiPatch('/papers/' + editing.value.id + '/', {
                        name: form.name, paper_type: form.paper_type, spec: form.spec,
                        safety_stock: form.safety_stock, unit_price: form.unit_price,
                    });
                } else {
                    await apiPost('/papers/', { ...form });
                }
                ElMessage.success('已保存');
                formVisible.value = false;
                load();
                emit('refresh-dashboard');
            } catch (e) { ElMessage.error(e.message); }
        }

        function openStock(row, type) {
            stockRow.value = row;
            stockType.value = type;
            Object.assign(stockForm, { quantity: 500, order: null, note: '' });
            stockVisible.value = true;
        }
        async function doStock() {
            try {
                const url = `/papers/${stockRow.value.id}/${stockType.value === 'in' ? 'stock_in' : 'stock_out'}/`;
                await apiPost(url, { quantity: stockForm.quantity, order: stockForm.order, note: stockForm.note });
                ElMessage.success(stockType.value === 'in' ? '入库成功' : '出库成功');
                stockVisible.value = false;
                load();
                emit('refresh-dashboard');
            } catch (e) { ElMessage.error(e.message); }
        }

        onMounted(load);
        return {
            loading, papers, txs, activeOrders, PAPER_TYPES,
            formVisible, editing, form, stockVisible, stockType, stockRow, stockForm, orderOptions,
            formatNum, openEdit, save, openStock, doStock,
        };
    },
};
window.__APP_COMPONENTS__.Papers = Papers;

/* ============================================================
 * 视图四：机台排产（甘特式日历视图 + 机台管理）
 * ============================================================ */
const Schedules = {
    template: `
    <div v-loading="loading">
      <div class="panel">
        <el-form :inline="true" @submit.prevent>
          <el-form-item label="日期">
            <el-date-picker v-model="curDate" type="date" value-format="YYYY-MM-DD" @change="loadSchedules"></el-date-picker>
          </el-form-item>
          <el-form-item>
            <el-button @click="shiftDay(-1)">← 前一天</el-button>
            <el-button @click="curDate = todayStr(); loadSchedules()">今天</el-button>
            <el-button @click="shiftDay(1)">后一天 →</el-button>
          </el-form-item>
          <el-form-item style="float:right">
            <el-button type="primary" @click="openCreate()">+ 新增排产</el-button>
            <el-button @click="mDialog=true">机台管理</el-button>
          </el-form-item>
        </el-form>

        <!-- 日历式排产表：行=机台，单元格=当天任务 -->
        <el-table :data="machineRows" border>
          <el-table-column label="机台" width="230" fixed>
            <template #default="{ row }">
              <div style="font-weight:600">{{ row.name }}</div>
              <div class="muted">{{ row.machine_type }}</div>
              <el-tag :type="MACHINE_STATUS[row.status].type" size="small" style="margin-top:4px">{{ MACHINE_STATUS[row.status].label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column :label="curDate + ' 排产任务'">
            <template #default="{ row }">
              <div v-if="!row.items.length" class="muted">— 无排产 —</div>
              <div v-for="item in row.items" :key="item.id" class="schedule-item"
                   :class="{ done: item.done }">
                <div style="flex:1">
                  <el-tag size="small" :type="item.shift==='夜班' ? 'info' : 'warning'" effect="plain" style="margin-right:6px">{{ item.shift }}</el-tag>
                  <strong>{{ item.order_no }}</strong>
                  <span class="muted"> · {{ item.product_name }}</span>
                  <div class="muted" style="margin-top:2px">
                    计划 {{ formatNum(item.planned_qty) }} /
                    实际 <span :style="{color: item.actual_qty >= item.planned_qty ? '#67c23a' : '#e6a23c'}">{{ formatNum(item.actual_qty) }}</span>
                    <span v-if="item.remark"> · {{ item.remark }}</span>
                  </div>
                </div>
                <div style="display:flex;flex-direction:column;gap:4px">
                  <el-button link :type="item.done ? 'info' : 'success'" size="small" @click="toggleDone(item)">
                    {{ item.done ? '撤销完成' : '完成' }}
                  </el-button>
                  <el-button link type="primary" size="small" @click="openCreate(item)">编辑</el-button>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="当日负荷" width="200">
            <template #default="{ row }">
              <div>计划 {{ formatNum(row.planTotal) }} 份</div>
              <el-progress :percentage="row.planTotal ? Math.round(row.actualTotal / row.planTotal * 100) : 0"
                           :status="row.actualTotal >= row.planTotal && row.planTotal ? 'success' : ''" style="margin-top:4px"></el-progress>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 排产编辑 -->
      <el-dialog v-model="formVisible" :title="editing ? '编辑排产' : '新增排产'" width="520px">
        <el-form :model="form" label-width="86px">
          <el-form-item label="机台" required>
            <el-select v-model="form.machine" style="width:100%">
              <el-option v-for="m in machines" :key="m.id" :label="m.name + '（' + m.machine_type + '）'" :value="m.id" :disabled="m.status==='maintenance'"></el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="订单" required>
            <el-select v-model="form.order" filterable style="width:100%">
              <el-option v-for="o in activeOrders" :key="o.id"
                :label="o.order_no + ' ' + o.product_name + '（' + formatNum(o.quantity) + '份）'" :value="o.id"></el-option>
            </el-select>
          </el-form-item>
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="计划日期" required>
                <el-date-picker v-model="form.planned_date" type="date" value-format="YYYY-MM-DD" style="width:100%"></el-date-picker>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="班次">
                <el-select v-model="form.shift" style="width:100%">
                  <el-option label="白班" value="白班"></el-option>
                  <el-option label="夜班" value="夜班"></el-option>
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="计划产量">
                <el-input-number v-model="form.planned_qty" :min="0" :step="1000" style="width:100%"></el-input-number>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="实际产量">
                <el-input-number v-model="form.actual_qty" :min="0" :step="1000" style="width:100%"></el-input-number>
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="备注"><el-input v-model="form.remark" placeholder="如：专色 / 覆膜后加工"></el-input></el-form-item>
        </el-form>
        <template #footer>
          <el-button v-if="editing" type="danger" @click="remove">删除</el-button>
          <el-button @click="formVisible=false">取消</el-button>
          <el-button type="primary" @click="save">保存</el-button>
        </template>
      </el-dialog>

      <!-- 机台管理 -->
      <el-dialog v-model="mDialog" title="机台管理" width="560px">
        <el-button type="primary" size="small" style="margin-bottom:10px" @click="openMachine(null)">+ 新增机台</el-button>
        <el-table :data="machines" border size="small">
          <el-table-column prop="name" label="机台名称" min-width="170"></el-table-column>
          <el-table-column prop="machine_type" label="机型" min-width="150"></el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-select v-model="row.status" size="small" @change="changeMachineStatus(row)">
                <el-option v-for="(s, k) in MACHINE_STATUS" :key="k" :label="s.label" :value="k"></el-option>
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openMachine(row)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-dialog>

      <el-dialog v-model="mFormVisible" :title="mEditing ? '编辑机台' : '新增机台'" width="420px">
        <el-form :model="mform" label-width="80px">
          <el-form-item label="名称" required><el-input v-model="mform.name"></el-input></el-form-item>
          <el-form-item label="机型"><el-input v-model="mform.machine_type" placeholder="如 对开四色胶印机"></el-input></el-form-item>
          <el-form-item label="状态">
            <el-select v-model="mform.status" style="width:100%">
              <el-option v-for="(s, k) in MACHINE_STATUS" :key="k" :label="s.label" :value="k"></el-option>
            </el-select>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="mFormVisible=false">取消</el-button>
          <el-button type="primary" @click="saveMachine">保存</el-button>
        </template>
      </el-dialog>
    </div>`,
    setup() {
        const loading = ref(false);
        const machines = ref([]);
        const schedules = ref([]);
        const activeOrders = ref([]);
        const curDate = ref(todayStr());

        const formVisible = ref(false);
        const editing = ref(null);
        const form = reactive({ machine: null, order: null, planned_date: todayStr(), shift: '白班', planned_qty: 0, actual_qty: 0, remark: '', done: false });

        const mDialog = ref(false);
        const mFormVisible = ref(false);
        const mEditing = ref(null);
        const mform = reactive({ name: '', machine_type: '', status: 'idle' });

        function formatNum(n) { return Number(n || 0).toLocaleString(); }

        const machineRows = computed(() => machines.value.map(m => {
            const items = schedules.value.filter(s => s.machine === m.id);
            const planTotal = items.reduce((a, i) => a + Number(i.planned_qty), 0);
            const actualTotal = items.reduce((a, i) => a + Number(i.actual_qty), 0);
            return { ...m, items, planTotal, actualTotal };
        }));

        async function loadMachines() { machines.value = await apiGet('/machines/'); }
        async function loadSchedules() {
            schedules.value = await apiGet('/schedules/?date=' + curDate.value);
        }
        async function load() {
            loading.value = true;
            try {
                await loadMachines();
                await loadSchedules();
                activeOrders.value = (await apiGet('/orders/')).filter(o => o.status !== 'completed');
            } finally { loading.value = false; }
        }
        function shiftDay(delta) {
            const d = new Date(curDate.value);
            d.setDate(d.getDate() + delta);
            curDate.value = d.toISOString().slice(0, 10);
            loadSchedules();
        }

        function openCreate(item) {
            editing.value = item || null;
            if (item) Object.assign(form, {
                machine: item.machine, order: item.order, planned_date: item.planned_date,
                shift: item.shift, planned_qty: item.planned_qty, actual_qty: item.actual_qty,
                remark: item.remark, done: item.done,
            });
            else Object.assign(form, {
                machine: machines.value[0]?.id || null, order: activeOrders.value[0]?.id || null,
                planned_date: curDate.value, shift: '白班', planned_qty: 0, actual_qty: 0,
                remark: '', done: false,
            });
            formVisible.value = true;
        }
        async function save() {
            if (!form.machine || !form.order) { ElMessage.warning('请选择机台和订单'); return; }
            try {
                if (editing.value) await apiPatch('/schedules/' + editing.value.id + '/', { ...form });
                else await apiPost('/schedules/', { ...form });
                ElMessage.success('已保存，机台状态已同步');
                formVisible.value = false;
                load();
            } catch (e) { ElMessage.error(e.message); }
        }
        async function remove() {
            try {
                await apiDel('/schedules/' + editing.value.id + '/');
                ElMessage.success('已删除');
                formVisible.value = false;
                load();
            } catch (e) { ElMessage.error(e.message); }
        }
        async function toggleDone(item) {
            const done = !item.done;
            await apiPatch('/schedules/' + item.id + '/', {
                done, actual_qty: done && !item.actual_qty ? item.planned_qty : item.actual_qty,
            });
            ElMessage.success(done ? '任务完成' : '已撤销');
            load();
        }

        async function changeMachineStatus(row) {
            await apiPatch('/machines/' + row.id + '/', { status: row.status });
            ElMessage.success('机台状态已更新');
        }
        function openMachine(row) {
            mEditing.value = row;
            if (row) Object.assign(mform, { name: row.name, machine_type: row.machine_type, status: row.status });
            else Object.assign(mform, { name: '', machine_type: '', status: 'idle' });
            mFormVisible.value = true;
        }
        async function saveMachine() {
            if (!mform.name) { ElMessage.warning('请输入名称'); return; }
            try {
                if (mEditing.value) await apiPatch('/machines/' + mEditing.value.id + '/', { ...mform });
                else await apiPost('/machines/', { ...mform });
                ElMessage.success('已保存');
                mFormVisible.value = false;
                loadMachines();
            } catch (e) { ElMessage.error(e.message); }
        }

        onMounted(load);
        return {
            loading, machines, schedules, activeOrders, curDate, machineRows,
            formVisible, editing, form, mDialog, mFormVisible, mEditing, mform,
            MACHINE_STATUS, formatNum, todayStr,
            loadSchedules, shiftDay, openCreate, save, remove, toggleDone,
            changeMachineStatus, openMachine, saveMachine,
        };
    },
};
window.__APP_COMPONENTS__.Schedules = Schedules;

/* ============================================================
 * 视图五：返工跟踪
 * ============================================================ */
const Reworks = {
    template: `
    <div v-loading="loading">
      <el-row :gutter="16" style="margin-bottom:16px">
        <el-col :span="8">
          <div class="stat-card"><div class="icon" style="background:#f56c6c">⚠️</div>
            <div><div class="num">{{ count.open }}</div><div class="label">待处理</div></div></div>
        </el-col>
        <el-col :span="8">
          <div class="stat-card"><div class="icon" style="background:#e6a23c">🔧</div>
            <div><div class="num">{{ count.processing }}</div><div class="label">返工中</div></div></div>
        </el-col>
        <el-col :span="8">
          <div class="stat-card"><div class="icon" style="background:#67c23a">✅</div>
            <div><div class="num">{{ count.closed }}</div><div class="label">本月已闭环</div></div></div>
        </el-col>
      </el-row>

      <div class="panel">
        <div class="panel-title">返工单列表
          <el-radio-group v-model="filter" size="small" @change="load">
            <el-radio-button label="">全部</el-radio-button>
            <el-radio-button label="open">待处理</el-radio-button>
            <el-radio-button label="processing">返工中</el-radio-button>
            <el-radio-button label="closed">已闭环</el-radio-button>
          </el-radio-group>
        </div>
        <el-table :data="reworks" border stripe @row-click="openDetail" style="cursor:pointer">
          <el-table-column prop="id" label="单号" width="70">
            <template #default="{ row }">#{{ row.id }}</template>
          </el-table-column>
          <el-table-column label="订单" min-width="240">
            <template #default="{ row }">
              <div style="font-weight:600">{{ row.order_no }}</div>
              <div class="muted">{{ row.product_name }}</div>
            </template>
          </el-table-column>
          <el-table-column label="返工工序" width="90">
            <template #default="{ row }">
              <el-tag size="small">{{ row.stage_display }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="原因" width="110">
            <template #default="{ row }">{{ row.reason_display }}</template>
          </el-table-column>
          <el-table-column label="数量" width="100">
            <template #default="{ row }">{{ formatNum(row.qty) }} 份</template>
          </el-table-column>
          <el-table-column prop="handler" label="责任人" width="120">
            <template #default="{ row }">{{ row.handler || '—' }}</template>
          </el-table-column>
          <el-table-column label="发现/闭环" width="190">
            <template #default="{ row }">
              <div>{{ row.found_at }} 发现</div>
              <div class="muted">{{ row.closed_at ? row.closed_at + ' 闭环' : '未闭环' }}</div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="REWORK_STATUS[row.status].type" size="small" effect="dark">{{ row.status_display }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.status==='open'" link type="warning" size="small" @click.stop="advance(row)">开始返工</el-button>
              <el-button v-if="row.status!=='closed'" link type="success" size="small" @click.stop="openClose(row)">闭环</el-button>
              <el-button link type="primary" size="small" @click.stop="openDetail(row)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 返工详情 -->
      <el-drawer v-model="detailVisible" size="46%" :title="'返工单 #' + (detail.id || '')">
        <template v-if="detail.id">
          <el-descriptions :column="2" border size="small" style="margin-bottom:16px">
            <el-descriptions-item label="订单">{{ detail.order_no }}</el-descriptions-item>
            <el-descriptions-item label="产品">{{ detail.product_name }}</el-descriptions-item>
            <el-descriptions-item label="返工工序">{{ detail.stage_display }}</el-descriptions-item>
            <el-descriptions-item label="返工原因">{{ detail.reason_display }}</el-descriptions-item>
            <el-descriptions-item label="返工数量">{{ formatNum(detail.qty) }} 份</el-descriptions-item>
            <el-descriptions-item label="责任人">{{ detail.handler || '—' }}</el-descriptions-item>
            <el-descriptions-item label="发现日期">{{ detail.found_at }}</el-descriptions-item>
            <el-descriptions-item label="状态">
              <el-tag :type="REWORK_STATUS[detail.status].type" size="small">{{ detail.status_display }}</el-tag>
            </el-descriptions-item>
          </el-descriptions>
          <div class="panel" style="box-shadow:none;border:1px solid #ebeef5;margin-bottom:14px">
            <div class="panel-title">问题描述</div>
            <div style="line-height:1.7">{{ detail.description }}</div>
          </div>
          <div class="panel" style="box-shadow:none;border:1px solid #ebeef5;margin-bottom:14px">
            <div class="panel-title">处理结果
              <el-button v-if="detail.status!=='closed'" type="success" size="small" @click="openClose(detail)">填写结果并闭环</el-button>
            </div>
            <div v-if="detail.result" style="line-height:1.7">{{ detail.result }}</div>
            <div v-else class="muted">尚未填写</div>
            <div v-if="detail.closed_at" class="muted" style="margin-top:8px">闭环日期：{{ detail.closed_at }}</div>
          </div>
          <el-button v-if="detail.status==='open'" type="warning" @click="advance(detail)">开始返工</el-button>
        </template>
      </el-drawer>

      <!-- 闭环对话框 -->
      <el-dialog v-model="closeVisible" title="返工闭环" width="480px">
        <el-form :model="closeForm" label-width="86px">
          <el-form-item label="处理结果" required>
            <el-input v-model="closeForm.result" type="textarea" :rows="4" placeholder="说明返工措施、复检结果"></el-input>
          </el-form-item>
          <el-form-item label="闭环日期">
            <el-date-picker v-model="closeForm.closed_at" type="date" value-format="YYYY-MM-DD" style="width:100%"></el-date-picker>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="closeVisible=false">取消</el-button>
          <el-button type="success" @click="doClose">确认闭环</el-button>
        </template>
      </el-dialog>
    </div>`,
    emits: ['refresh-dashboard'],
    setup(_, { emit }) {
        const loading = ref(false);
        const reworks = ref([]);
        const filter = ref('');
        const count = reactive({ open: 0, processing: 0, closed: 0 });

        const detailVisible = ref(false);
        const detail = ref({});
        const closeVisible = ref(false);
        const closeForm = reactive({ result: '', closed_at: todayStr() });
        let closingId = null;

        function formatNum(n) { return Number(n || 0).toLocaleString(); }

        async function load() {
            loading.value = true;
            try {
                const url = filter.value ? '/reworks/?status=' + filter.value : '/reworks/';
                reworks.value = await apiGet(url);
                const all = filter.value ? reworks.value : reworks.value;
                const allData = filter.value ? await apiGet('/reworks/') : reworks.value;
                count.open = allData.filter(r => r.status === 'open').length;
                count.processing = allData.filter(r => r.status === 'processing').length;
                const month = todayStr().slice(0, 7);
                count.closed = allData.filter(r => r.status === 'closed' && (r.closed_at || '').startsWith(month)).length;
            } catch (e) { ElMessage.error(e.message); } finally { loading.value = false; }
        }

        async function openDetail(row) {
            detail.value = await apiGet('/reworks/' + row.id + '/');
            detailVisible.value = true;
        }
        async function advance(row) {
            await apiPatch('/reworks/' + row.id + '/', { status: 'processing' });
            ElMessage.success('返工单已进入返工中，工序与订单状态已联动');
            load();
            emit('refresh-dashboard');
        }
        function openClose(row) {
            closingId = row.id;
            Object.assign(closeForm, { result: row.result || '', closed_at: todayStr() });
            closeVisible.value = true;
        }
        async function doClose() {
            if (!closeForm.result) { ElMessage.warning('请填写处理结果'); return; }
            try {
                await apiPatch('/reworks/' + closingId + '/', { status: 'closed', ...closeForm });
                ElMessage.success('返工单已闭环，订单工序状态已恢复');
                closeVisible.value = false;
                detailVisible.value = false;
                load();
                emit('refresh-dashboard');
            } catch (e) { ElMessage.error(e.message); }
        }

        onMounted(load);
        return {
            loading, reworks, filter, count, detailVisible, detail,
            closeVisible, closeForm, REWORK_STATUS,
            formatNum, load, openDetail, advance, openClose, doClose,
        };
    },
};
window.__APP_COMPONENTS__.Reworks = Reworks;

/* ============================================================
 * 应用外壳：侧边栏 + 视图切换
 * ============================================================ */
const App = {
    template: `
    <div class="layout">
      <aside class="sidebar">
        <div class="logo">🖨️ 印厂生产管理
          <span class="sub">PRINTING ERP</span>
        </div>
        <div class="menu">
          <div v-for="m in menus" :key="m.key" class="menu-item"
               :class="{ active: current === m.key }" @click="switchView(m.key)">
            <span>{{ m.icon }}</span>{{ m.label }}
          </div>
        </div>
        <div class="footer">演示数据 · SQLite<br>© 2026 印刷厂</div>
      </aside>
      <div class="main">
        <div class="topbar">
          <div class="title">{{ currentMenu.label }}</div>
          <div class="muted">今天是 {{ today }}（{{ weekday }}）</div>
        </div>
        <div class="content">
          <dashboard v-if="current==='dashboard'" :key="dashKey"
                     @go="switchView" @go-orders="goOrdersWithStatus" @open-order="openOrder"></dashboard>
          <orders v-else-if="current==='orders'" ref="ordersRef" :key="'orders'+ordersKey" :autoStatus="orderFilter"></orders>
          <papers v-else-if="current==='papers'" :key="'papers'+papersKey"></papers>
          <schedules v-else-if="current==='schedules'" key="schedules"></schedules>
          <reworks v-else-if="current==='reworks'" :key="'reworks'+reworksKey"></reworks>
        </div>
      </div>
    </div>`,
    setup() {
        const current = ref('dashboard');
        const dashKey = ref(0);
        const ordersKey = ref(0);
        const papersKey = ref(0);
        const reworksKey = ref(0);
        const orderFilter = ref('');
        const ordersRef = ref(null);

        const menus = [
            { key: 'dashboard', label: '生产看板', icon: '📊' },
            { key: 'orders', label: '订单管理', icon: '📋' },
            { key: 'papers', label: '纸张材料', icon: '📦' },
            { key: 'schedules', label: '机台排产', icon: '🏭' },
            { key: 'reworks', label: '返工跟踪', icon: '🔧' },
        ];
        const currentMenu = computed(() => menus.find(m => m.key === current.value));
        const today = todayStr();
        const weekday = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][new Date().getDay()];

        function switchView(key) {
            if (!menus.some(m => m.key === key)) return;
            current.value = key;
            if (key === 'dashboard') dashKey.value++;
        }
        function goOrdersWithStatus(status) {
            orderFilter.value = status;
            current.value = 'orders';
            ordersKey.value++;
        }
        async function openOrder(id) {
            current.value = 'orders';
            ordersKey.value++;
            await nextTick();
            ordersRef.value?.openDetail(id);
        }

        return { current, currentMenu, menus, today, weekday, dashKey, ordersKey, papersKey, reworksKey,
                 orderFilter, ordersRef, switchView, goOrdersWithStatus, openOrder };
    },
};

const app = createApp(App);
Object.entries(window.__APP_COMPONENTS__).forEach(([name, comp]) => app.component(name, comp));
app.use(ElementPlus, { locale: window.ElementPlusLocaleZhCn });
app.mount('#app');
