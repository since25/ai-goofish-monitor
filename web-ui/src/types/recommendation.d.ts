export interface RecommendationRow {
  task: string;
  item_id: string;
  title: string;
  price: number | null;
  link: string;
  region: string;
  size: string;
  year: string;
  age: number | null;
  chip: string;
  chip_raw: string | null;
  task_chip: string | null;
  memory: string;
  storage: string;
  battery: string;
  coefficient: number | null;
  depreciation: number;
  retention: number;
  adjusted: number | null;
  resale_1y: number | null;
  loss_1y: number | null;
  loss_low: number | null;
  loss_high: number | null;
  hold_score: number | null;
  value: number | null;
  ai_value_score: number | null;
}

export interface RecommendationSummary {
  generated_at: string;
  valuation_year: number;
  total_items: number;
  ranked_items: number;
  weights: {
    chip: number;
    memory: number;
    storage: number;
  };
  depreciation_by_age: Array<{
    age: number;
    rate: number;
  }>;
  default_depreciation: number;
  depreciation_range: number;
  rows: RecommendationRow[];
  top: RecommendationRow[];
  hold_top: RecommendationRow[];
}
