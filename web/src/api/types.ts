export type Role = "admin" | "member" | "viewer";

export interface User {
  id: string;
  email: string;
  name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface Project {
  id: string;
  slug: string;
  name: string;
  base_url: string;
  description: string;
  config_yaml: string;
  explore_links: boolean;
  llm_provider: string;
  llm_model: string;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
}

export type RunStatus =
  | "queued"
  | "running"
  | "passed"
  | "failed"
  | "errored"
  | "cancelled";

export interface Run {
  id: string;
  project_id: string;
  triggered_by_user_id: string | null;
  target_url: string;
  status: RunStatus;
  error_message: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  scenarios_total: number;
  scenarios_passed: number;
  visual_diffs_count: number;
  a11y_violations_count: number;
}

export interface StepFailure {
  step_index: number;
  step_description: string;
  message: string;
  screenshot_path: string;
}

export interface ScenarioRun {
  id: string;
  name: string;
  description: string;
  passed: boolean;
  duration_seconds: number;
  order_index: number;
  failures: StepFailure[];
}

export interface VisualDiff {
  id: string;
  name: string;
  baseline_path: string;
  current_path: string;
  diff_path: string;
  percent_changed: number;
  threshold: number;
}

export interface A11yViolation {
  id: string;
  page_url: string;
  rule_id: string;
  impact: string;
  description: string;
  sample_selector: string;
  nodes_affected: number;
}

export interface RunDetail extends Run {
  scenarios: ScenarioRun[];
  visual_diffs: VisualDiff[];
  a11y_violations: A11yViolation[];
}
