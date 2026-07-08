export type Role = "viewer" | "analyst" | "admin" | string;
export type Source = "forecast";
export type Metric = "avg_temp" | "min_temp" | "max_temp" | "precipitation";

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface AuthTokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_at: string;
  user: User;
}

export interface Station {
  id: number;
  wmo_index: string;
  name: string;
  country: string | null;
  latitude: number | null;
  longitude: number | null;
  elevation_m: number | null;
  noaa_station_id: string | null;
}

export interface StationDetailsResponse {
  station: Station & { coordinates_updated_at?: string | null };
  stats: Record<string, number | string | null>;
}

export interface StationsResponse {
  total: number;
  returned: number;
  stations: Station[];
}

export interface ForecastRun {
  id: number;
  provider: string;
  model: string;
  source: Source;
  requested_archive_horizon_days: number | null;
  status: string;
  run_at: string;
  requested_start_date: string;
  requested_end_date: string;
  requested_station_count: number;
  created_at: string;
  completed_at: string | null;
  error_message: string | null;
  saved_rows: number;
  saved_stations: number;
  saved_horizon_days: number[];
}

export interface ForecastRunsResponse {
  returned: number;
  runs: ForecastRun[];
}

export interface MetricSummary {
  compared_points: number;
  mae: number | null;
  rmse: number | null;
  bias: number | null;
  max_absolute_error: number | null;
}

export interface AnalyticsSummaryResponse {
  start_date: string;
  end_date: string;
  model: string | null;
  source: Source | null;
  horizon_days: number | null;
  metrics: Record<Metric, MetricSummary>;
  totals: Record<string, number | string | null>;
}

export interface TopErrorItem {
  station_id: number;
  wmo_index: string;
  name: string;
  country: string | null;
  latitude: number | null;
  longitude: number | null;
  forecast_date: string;
  horizon_days: number;
  provider: string;
  model: string;
  source: Source;
  run_at: string;
  forecast_value: number | null;
  actual_value: number | null;
  signed_error: number | null;
  absolute_error: number | null;
  error_rank: number;
}

export interface TopErrorsResponse {
  metric: Metric;
  start_date: string;
  end_date: string;
  model: string | null;
  source: Source | null;
  horizon_days: number | null;
  returned: number;
  items: TopErrorItem[];
}

export interface WorstStationItem {
  station_id: number;
  wmo_index: string;
  name: string;
  country: string | null;
  latitude: number | null;
  longitude: number | null;
  compared_points: number;
  mae: number | null;
  max_absolute_error: number | null;
}

export interface WorstStationsResponse {
  metric: Metric;
  start_date: string;
  end_date: string;
  model: string | null;
  source: Source | null;
  horizon_days: number | null;
  returned: number;
  items: WorstStationItem[];
}

export interface StationSeriesItem {
  observation_date: string;
  source: Source | null;
  provider: string | null;
  model: string | null;
  run_at: string | null;
  horizon_days: number | null;
  actual_avg_temp: number | null;
  forecast_avg_temp: number | null;
  error_avg_temp: number | null;
  actual_min_temp: number | null;
  forecast_min_temp: number | null;
  error_min_temp: number | null;
  actual_max_temp: number | null;
  forecast_max_temp: number | null;
  error_max_temp: number | null;
  actual_precipitation: number | null;
  forecast_precipitation: number | null;
  error_precipitation: number | null;
  forecast_max_wind_speed: number | null;
}

export interface StationSeriesResponse {
  station: Pick<Station, "id" | "wmo_index" | "name" | "country" | "latitude" | "longitude">;
  start_date: string;
  end_date: string;
  model: string | null;
  source: Source | null;
  horizon_days: number | null;
  returned: number;
  items: StationSeriesItem[];
}

export interface ForecastCoverageItem {
  model: string;
  source: Source;
  horizon_days: number;
  forecast_rows: number;
  run_count: number;
  station_count: number;
  forecast_start_date: string | null;
  forecast_end_date: string | null;
  avg_temp_rows: number;
  min_temp_rows: number;
  max_temp_rows: number;
  precipitation_rows: number;
  max_wind_speed_rows: number;
}

export interface ForecastCoverageResponse {
  start_date: string | null;
  end_date: string | null;
  model: string | null;
  source: Source | null;
  horizon_days: number | null;
  returned: number;
  items: ForecastCoverageItem[];
}
