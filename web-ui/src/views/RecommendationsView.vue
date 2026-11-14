<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowUpRight,
  BadgePercent,
  RefreshCw,
  Sparkles,
  TimerReset,
  Wallet,
} from 'lucide-vue-next'
import { getRecommendationSummary } from '@/api/recommendations'
import type { RecommendationRow, RecommendationSummary } from '@/types/recommendation.d.ts'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

const { t, locale } = useI18n()

const summary = ref<RecommendationSummary | null>(null)
const isLoading = ref(false)
const error = ref<Error | null>(null)
const activeTab = ref('buy')
const selectedTask = ref('all')
const topN = ref('20')

const topOptions = ['10', '20', '50', '100']

const rows = computed(() => summary.value?.rows ?? [])
const tasks = computed(() => Array.from(new Set(rows.value.map((row) => row.task))).sort())
const limit = computed(() => Number(topN.value))

const filteredRows = computed(() => {
  if (selectedTask.value === 'all') return rows.value
  return rows.value.filter((row) => row.task === selectedTask.value)
})

const buyRows = computed(() =>
  filteredRows.value
    .filter((row) => row.value !== null)
    .slice()
    .sort((a, b) => (b.value ?? 0) - (a.value ?? 0))
    .slice(0, limit.value),
)

const holdRows = computed(() =>
  filteredRows.value
    .filter((row) => row.hold_score !== null)
    .slice()
    .sort((a, b) => (b.hold_score ?? 0) - (a.hold_score ?? 0))
    .slice(0, limit.value),
)

const detailRows = computed(() =>
  filteredRows.value
    .slice()
    .sort((a, b) => (b.value ?? -1) - (a.value ?? -1) || a.task.localeCompare(b.task)),
)

const bestBuy = computed(() => buyRows.value[0] ?? null)
const bestHold = computed(() => holdRows.value[0] ?? null)

function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-'
  return `¥${new Intl.NumberFormat(locale.value).format(Math.round(value))}`
}

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-'
  return `${Math.round(value * 100)}%`
}

function formatScore(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return '-'
  return value.toFixed(digits)
}

function formatAge(age: number | null | undefined): string {
  if (age === null || age === undefined) return '-'
  return t('recommendations.table.years', { count: age })
}

function formatLossRange(row: RecommendationRow): string {
  if (row.loss_low === null || row.loss_high === null) return '-'
  return `${formatMoney(row.loss_low)}～${formatMoney(row.loss_high)}`
}

function formatConfig(row: RecommendationRow): string {
  return `${row.chip} / ${row.memory} / ${row.storage}`
}

const SHANGHAI_REGION = '上海'

function isShanghai(row: RecommendationRow): boolean {
  return row.region === SHANGHAI_REGION
}

function formatGeneratedAt(value: string | undefined): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString(locale.value)
}

async function loadRecommendations() {
  isLoading.value = true
  error.value = null
  try {
    summary.value = await getRecommendationSummary({ top: 200 })
  } catch (e) {
    error.value = e instanceof Error ? e : new Error(String(e))
    summary.value = null
  } finally {
    isLoading.value = false
  }
}

onMounted(loadRecommendations)
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
      <div>
        <h1 class="text-2xl font-bold text-gray-800">{{ t('recommendations.title') }}</h1>
        <p class="mt-2 text-sm text-slate-500">{{ t('recommendations.description') }}</p>
        <p v-if="summary" class="mt-1 text-xs text-slate-400">
          {{ t('recommendations.generatedAt', { time: formatGeneratedAt(summary.generated_at) }) }}
        </p>
      </div>
      <Button variant="outline" :disabled="isLoading" @click="loadRecommendations">
        <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': isLoading }" />
        {{ t('recommendations.refresh') }}
      </Button>
    </div>

    <div v-if="error" class="app-alert-error" role="alert">
      <strong class="font-bold">{{ t('common.error') }}</strong>
      <span class="block sm:inline">{{ error.message }}</span>
    </div>

    <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Card class="app-surface border-none">
        <CardContent class="flex items-start gap-4 p-5">
          <div class="rounded-2xl bg-primary/10 p-3 text-primary">
            <Sparkles class="h-5 w-5" />
          </div>
          <div>
            <p class="text-xs font-bold uppercase tracking-wider text-slate-400">{{ t('recommendations.summary.total') }}</p>
            <p class="mt-1 text-2xl font-black text-slate-900">{{ summary?.total_items ?? '-' }}</p>
            <p class="mt-1 text-xs text-slate-500">
              {{ t('recommendations.summary.ranked', { count: summary?.ranked_items ?? 0 }) }}
            </p>
          </div>
        </CardContent>
      </Card>

      <Card class="app-surface border-none">
        <CardContent class="flex items-start gap-4 p-5">
          <div class="rounded-2xl bg-emerald-500/10 p-3 text-emerald-600">
            <BadgePercent class="h-5 w-5" />
          </div>
          <div class="min-w-0">
            <p class="text-xs font-bold uppercase tracking-wider text-slate-400">{{ t('recommendations.summary.bestBuy') }}</p>
            <p class="mt-1 truncate text-lg font-black text-slate-900">
              {{ bestBuy ? formatConfig(bestBuy) : '-' }}
            </p>
            <p class="mt-1 text-xs text-slate-500">
              {{ bestBuy ? formatMoney(bestBuy.price) : '-' }} · {{ t('recommendations.table.value') }}
              {{ bestBuy ? formatScore(bestBuy.value) : '-' }}
            </p>
          </div>
        </CardContent>
      </Card>

      <Card class="app-surface border-none">
        <CardContent class="flex items-start gap-4 p-5">
          <div class="rounded-2xl bg-amber-500/10 p-3 text-amber-600">
            <TimerReset class="h-5 w-5" />
          </div>
          <div class="min-w-0">
            <p class="text-xs font-bold uppercase tracking-wider text-slate-400">{{ t('recommendations.summary.bestHold') }}</p>
            <p class="mt-1 truncate text-lg font-black text-slate-900">
              {{ bestHold ? formatConfig(bestHold) : '-' }}
            </p>
            <p class="mt-1 text-xs text-slate-500">
              {{ t('recommendations.summary.bestHoldDetail', { loss: bestHold ? formatMoney(bestHold.loss_1y) : '-' }) }}
            </p>
          </div>
        </CardContent>
      </Card>

      <Card class="app-surface border-none">
        <CardContent class="flex items-start gap-4 p-5">
          <div class="rounded-2xl bg-blue-500/10 p-3 text-blue-600">
            <Wallet class="h-5 w-5" />
          </div>
          <div>
            <p class="text-xs font-bold uppercase tracking-wider text-slate-400">{{ t('recommendations.summary.depreciation') }}</p>
            <p class="mt-1 text-2xl font-black text-slate-900">{{ summary?.valuation_year ?? '-' }}</p>
            <p class="mt-1 text-xs text-slate-500">{{ t('recommendations.summary.depreciationHint') }}</p>
          </div>
        </CardContent>
      </Card>
    </div>

    <Card class="app-surface border-none">
      <CardContent class="flex flex-col gap-3 p-4 lg:flex-row lg:items-center lg:justify-between">
        <div class="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div class="w-full sm:w-[240px]">
            <Select v-model="selectedTask">
              <SelectTrigger>
                <SelectValue :placeholder="t('recommendations.filters.task')" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{{ t('recommendations.filters.allTasks') }}</SelectItem>
                <SelectItem v-for="task in tasks" :key="task" :value="task">{{ task }}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="w-full sm:w-[140px]">
            <Select v-model="topN">
              <SelectTrigger>
                <SelectValue :placeholder="t('recommendations.filters.top')" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="option in topOptions" :key="option" :value="option">
                  {{ t('recommendations.filters.topOption', { count: option }) }}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <p class="text-xs text-slate-500">{{ t('recommendations.note') }}</p>
      </CardContent>
    </Card>

    <Tabs v-model="activeTab">
      <TabsList class="grid w-full grid-cols-3 lg:w-auto">
        <TabsTrigger value="buy">{{ t('recommendations.tabs.buy') }}</TabsTrigger>
        <TabsTrigger value="hold">{{ t('recommendations.tabs.hold') }}</TabsTrigger>
        <TabsTrigger value="detail">{{ t('recommendations.tabs.detail') }}</TabsTrigger>
      </TabsList>

      <TabsContent value="buy">
        <Card class="app-surface overflow-hidden border-none">
          <CardContent class="p-0">
            <div v-if="isLoading" class="p-10 text-center text-sm text-slate-500">
              {{ t('recommendations.table.loading') }}
            </div>
            <div v-else-if="buyRows.length === 0" class="p-10 text-center text-sm text-slate-500">
              {{ t('recommendations.table.empty') }}
            </div>
            <Table v-else class="min-w-[900px]">
              <TableHeader class="bg-slate-50/70">
                <TableRow>
                  <TableHead class="w-16 text-center">{{ t('recommendations.table.rank') }}</TableHead>
                  <TableHead>{{ t('recommendations.table.task') }}</TableHead>
                  <TableHead class="text-center">{{ t('recommendations.table.region') }}</TableHead>
                  <TableHead>{{ t('recommendations.table.config') }}</TableHead>
                  <TableHead class="text-right">{{ t('recommendations.table.price') }}</TableHead>
                  <TableHead class="text-center">{{ t('recommendations.table.age') }}</TableHead>
                  <TableHead class="text-center">{{ t('recommendations.table.retention') }}</TableHead>
                  <TableHead class="text-center">{{ t('recommendations.table.adjusted') }}</TableHead>
                  <TableHead class="text-center">{{ t('recommendations.table.value') }}</TableHead>
                  <TableHead class="min-w-[260px]">{{ t('recommendations.table.item') }}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow
                  v-for="(row, index) in buyRows"
                  :key="row.item_id"
                  :class="isShanghai(row) ? 'bg-amber-50/70' : ''"
                >
                  <TableCell class="text-center">
                    <Badge :variant="index < 3 ? 'default' : 'secondary'">{{ index + 1 }}</Badge>
                  </TableCell>
                  <TableCell class="font-semibold text-slate-700">{{ row.task }}</TableCell>
                  <TableCell class="text-center">
                    <Badge v-if="isShanghai(row)" class="border-transparent bg-amber-500 text-white">
                      {{ row.region }}
                    </Badge>
                    <span v-else class="text-slate-600">{{ row.region }}</span>
                  </TableCell>
                  <TableCell class="whitespace-nowrap text-slate-600">{{ formatConfig(row) }}</TableCell>
                  <TableCell class="text-right font-bold text-slate-900">{{ formatMoney(row.price) }}</TableCell>
                  <TableCell class="text-center text-slate-600">{{ formatAge(row.age) }}</TableCell>
                  <TableCell class="text-center text-slate-600">{{ formatPercent(row.retention) }}</TableCell>
                  <TableCell class="text-center font-mono text-slate-600">{{ formatScore(row.adjusted, 3) }}</TableCell>
                  <TableCell class="text-center">
                    <span class="text-base font-black text-emerald-600">{{ formatScore(row.value) }}</span>
                  </TableCell>
                  <TableCell>
                    <a
                      :href="row.link"
                      target="_blank"
                      rel="noreferrer"
                      class="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
                    >
                      <span class="line-clamp-2">{{ row.title }}</span>
                      <ArrowUpRight class="h-3.5 w-3.5 shrink-0" />
                    </a>
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </TabsContent>

      <TabsContent value="hold">
        <Card class="app-surface overflow-hidden border-none">
          <CardContent class="p-0">
            <div v-if="isLoading" class="p-10 text-center text-sm text-slate-500">
              {{ t('recommendations.table.loading') }}
            </div>
            <div v-else-if="holdRows.length === 0" class="p-10 text-center text-sm text-slate-500">
              {{ t('recommendations.table.empty') }}
            </div>
            <Table v-else class="min-w-[1100px]">
              <TableHeader class="bg-slate-50/70">
                <TableRow>
                  <TableHead class="w-16 text-center">{{ t('recommendations.table.rank') }}</TableHead>
                  <TableHead>{{ t('recommendations.table.task') }}</TableHead>
                  <TableHead class="text-center">{{ t('recommendations.table.region') }}</TableHead>
                  <TableHead>{{ t('recommendations.table.config') }}</TableHead>
                  <TableHead class="text-right">{{ t('recommendations.table.price') }}</TableHead>
                  <TableHead class="text-center">{{ t('recommendations.table.age') }}</TableHead>
                  <TableHead class="text-center">{{ t('recommendations.table.depreciation') }}</TableHead>
                  <TableHead class="text-right">{{ t('recommendations.table.resale') }}</TableHead>
                  <TableHead class="text-right">{{ t('recommendations.table.loss') }}</TableHead>
                  <TableHead class="text-center">{{ t('recommendations.table.lossRange') }}</TableHead>
                  <TableHead class="text-center">{{ t('recommendations.table.holdScore') }}</TableHead>
                  <TableHead class="min-w-[260px]">{{ t('recommendations.table.item') }}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow
                  v-for="(row, index) in holdRows"
                  :key="row.item_id"
                  :class="isShanghai(row) ? 'bg-amber-50/70' : ''"
                >
                  <TableCell class="text-center">
                    <Badge :variant="index < 3 ? 'default' : 'secondary'">{{ index + 1 }}</Badge>
                  </TableCell>
                  <TableCell class="font-semibold text-slate-700">{{ row.task }}</TableCell>
                  <TableCell class="text-center">
                    <Badge v-if="isShanghai(row)" class="border-transparent bg-amber-500 text-white">
                      {{ row.region }}
                    </Badge>
                    <span v-else class="text-slate-600">{{ row.region }}</span>
                  </TableCell>
                  <TableCell class="whitespace-nowrap text-slate-600">{{ formatConfig(row) }}</TableCell>
                  <TableCell class="text-right font-bold text-slate-900">{{ formatMoney(row.price) }}</TableCell>
                  <TableCell class="text-center text-slate-600">{{ formatAge(row.age) }}</TableCell>
                  <TableCell class="text-center text-slate-600">{{ formatPercent(row.depreciation) }}</TableCell>
                  <TableCell class="text-right text-slate-600">{{ formatMoney(row.resale_1y) }}</TableCell>
                  <TableCell class="text-right font-bold text-rose-600">{{ formatMoney(row.loss_1y) }}</TableCell>
                  <TableCell class="text-center text-xs text-slate-500">{{ formatLossRange(row) }}</TableCell>
                  <TableCell class="text-center">
                    <span class="text-base font-black text-amber-600">{{ formatScore(row.hold_score) }}</span>
                  </TableCell>
                  <TableCell>
                    <a
                      :href="row.link"
                      target="_blank"
                      rel="noreferrer"
                      class="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
                    >
                      <span class="line-clamp-2">{{ row.title }}</span>
                      <ArrowUpRight class="h-3.5 w-3.5 shrink-0" />
                    </a>
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </TabsContent>

      <TabsContent value="detail">
        <Card class="app-surface overflow-hidden border-none">
          <CardContent class="p-0">
            <div v-if="isLoading" class="p-10 text-center text-sm text-slate-500">
              {{ t('recommendations.table.loading') }}
            </div>
            <div v-else-if="detailRows.length === 0" class="p-10 text-center text-sm text-slate-500">
              {{ t('recommendations.table.empty') }}
            </div>
            <Table v-else class="min-w-[1200px]">
              <TableHeader class="bg-slate-50/70">
                <TableRow>
                  <TableHead>{{ t('recommendations.table.task') }}</TableHead>
                  <TableHead class="text-center">{{ t('recommendations.table.region') }}</TableHead>
                  <TableHead class="text-center">{{ t('recommendations.table.year') }}</TableHead>
                  <TableHead class="text-center">{{ t('recommendations.table.chip') }}</TableHead>
                  <TableHead class="text-center">{{ t('recommendations.table.memory') }}</TableHead>
                  <TableHead class="text-center">{{ t('recommendations.table.storage') }}</TableHead>
                  <TableHead class="text-center">{{ t('recommendations.table.battery') }}</TableHead>
                  <TableHead class="text-right">{{ t('recommendations.table.price') }}</TableHead>
                  <TableHead class="text-center">{{ t('recommendations.table.coefficient') }}</TableHead>
                  <TableHead class="text-center">{{ t('recommendations.table.retention') }}</TableHead>
                  <TableHead class="text-center">{{ t('recommendations.table.value') }}</TableHead>
                  <TableHead class="text-right">{{ t('recommendations.table.loss') }}</TableHead>
                  <TableHead class="min-w-[260px]">{{ t('recommendations.table.item') }}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow
                  v-for="row in detailRows"
                  :key="row.item_id"
                  :class="isShanghai(row) ? 'bg-amber-50/70' : ''"
                >
                  <TableCell class="font-semibold text-slate-700">{{ row.task }}</TableCell>
                  <TableCell class="text-center">
                    <Badge v-if="isShanghai(row)" class="border-transparent bg-amber-500 text-white">
                      {{ row.region }}
                    </Badge>
                    <span v-else class="text-slate-600">{{ row.region }}</span>
                  </TableCell>
                  <TableCell class="text-center text-slate-600">{{ row.year }}</TableCell>
                  <TableCell class="text-center text-slate-600">{{ row.chip }}</TableCell>
                  <TableCell class="text-center text-slate-600">{{ row.memory }}</TableCell>
                  <TableCell class="text-center text-slate-600">{{ row.storage }}</TableCell>
                  <TableCell class="text-center text-slate-600">{{ row.battery }}</TableCell>
                  <TableCell class="text-right font-bold text-slate-900">{{ formatMoney(row.price) }}</TableCell>
                  <TableCell class="text-center font-mono text-slate-600">{{ formatScore(row.coefficient, 3) }}</TableCell>
                  <TableCell class="text-center text-slate-600">{{ formatPercent(row.retention) }}</TableCell>
                  <TableCell class="text-center font-bold text-emerald-600">{{ formatScore(row.value) }}</TableCell>
                  <TableCell class="text-right text-rose-600">{{ formatMoney(row.loss_1y) }}</TableCell>
                  <TableCell>
                    <a
                      :href="row.link"
                      target="_blank"
                      rel="noreferrer"
                      class="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
                    >
                      <span class="line-clamp-2">{{ row.title }}</span>
                      <ArrowUpRight class="h-3.5 w-3.5 shrink-0" />
                    </a>
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </TabsContent>
    </Tabs>
  </div>
</template>
