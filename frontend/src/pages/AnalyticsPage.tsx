import { BarChart3, Gauge, LineChart as LineIcon, Medal, PieChart as PieIcon, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import { api, formatApiError } from "../api/client";
import { EmptyState, ErrorState, LoadingPanel, SkeletonGrid } from "../components/DataState";
import { MetricCard } from "../components/MetricCard";
import type {
  AnalyticsSummaryResponse,
  ForecastCoverageResponse,
  Metric,
  Source,
  Station,
  StationSeriesResponse,
  TopErrorsResponse,
  WorstStationsResponse
} from "../types";
import { defaultRange, formatDate, formatNumber, metricLabels, metricUnits, sourceLabel } from "../utils";

interface SourceRating {
  source: Source;
  mae: number | null;
  rmse: number | null;
  points: number;
}

export function AnalyticsPage() {
  const range = useMemo(() => defaultRange(7), []);
  const [startDate, setStartDate] = useState(range.start);
  const [endDate, setEndDate] = useState(range.end);
  const [metric, setMetric] = useState<Metric>("avg_temp");
  const [source, setSource] = useState<Source | "">("");
  const [model, setModel] = useState("");
  const [horizon, setHorizon] = useState<number | "">("");
  const [stations, setStations] = useState<Station[]>([]);
  const [selectedStation, setSelectedStation] = useState<number | "">("");
  const [summary, setSummary] = useState<AnalyticsSummaryResponse | null>(null);
  const [topErrors, setTopErrors] = useState<TopErrorsResponse | null>(null);
  const [worstStations, setWorstStations] = useState<WorstStationsResponse | null>(null);
  const [coverage, setCoverage] = useState<ForecastCoverageResponse | null>(null);
  const [series, setSeries] = useState<StationSeriesResponse | null>(null);
  const [sourceRatings, setSourceRatings] = useState<SourceRating[]>([]);
  const [loading, setLoading] = useState(true);
  const [seriesLoading, setSeriesLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [seriesError, setSeriesError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function loadStations() {
      try {
        const response = await api.stations({ limit: 500, with_coordinates_only: true });
        if (active) {
          setStations(response.stations);
          setSelectedStation((current) => current || response.stations[0]?.id || "");
        }
      } catch {
        if (active) {
          setStations([]);
        }
      }
    }
    void loadStations();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    async function loadAnalytics() {
      setLoading(true);
      setError(null);
      const baseParams = {
        start_date: startDate,
        end_date: endDate,
        model: model || undefined,
        source: source || undefined,
        horizon_days: horizon || undefined
      };

      try {
        const [summaryResponse, topResponse, worstResponse, coverageResponse] = await Promise.all([
          api.summary({ ...baseParams, only_with_coordinates: true }),
          api.topErrors({ ...baseParams, metric, limit: 20, only_with_coordinates: true }),
          api.worstStations({ ...baseParams, metric, limit: 12 }),
          api.forecastCoverage(baseParams)
        ]);

        const ratingSources: Source[] = source ? [source] : ["forecast", "previous_runs"];
        const ratingResults = await Promise.allSettled(
          ratingSources.map(async (ratingSource) => {
            const response = await api.summary({
              ...baseParams,
              source: ratingSource,
              only_with_coordinates: true
            });
            const metricSummary = response.metrics[metric];
            return {
              source: ratingSource,
              mae: metricSummary.mae,
              rmse: metricSummary.rmse,
              points: metricSummary.compared_points
            };
          })
        );

        if (active) {
          setSummary(summaryResponse);
          setTopErrors(topResponse);
          setWorstStations(worstResponse);
          setCoverage(coverageResponse);
          setSourceRatings(
            ratingResults
              .filter((result): result is PromiseFulfilledResult<SourceRating> => result.status === "fulfilled")
              .map((result) => result.value)
          );
        }
      } catch (err) {
        if (active) {
          setError(formatApiError(err));
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadAnalytics();
    return () => {
      active = false;
    };
  }, [endDate, horizon, metric, model, source, startDate]);

  useEffect(() => {
    if (!selectedStation) {
      setSeries(null);
      return;
    }
    let active = true;
    async function loadSeries() {
      setSeriesLoading(true);
      setSeriesError(null);
      try {
        const response = await api.stationSeries({
          station_id: Number(selectedStation),
          start_date: startDate,
          end_date: endDate,
          model: model || undefined,
          source: source || undefined,
          horizon_days: horizon || undefined
        });
        if (active) {
          setSeries(response);
        }
      } catch (err) {
        if (active) {
          setSeriesError(formatApiError(err));
        }
      } finally {
        if (active) {
          setSeriesLoading(false);
        }
      }
    }
    void loadSeries();
    return () => {
      active = false;
    };
  }, [endDate, horizon, model, selectedStation, source, startDate]);

  const metricSummary = summary?.metrics[metric];
  const statusData = useMemo(() => {
    const items = topErrors?.items || [];
    const good = items.filter((item) => Number(item.absolute_error || 0) <= 1).length;
    const warn = items.filter((item) => Number(item.absolute_error || 0) > 1 && Number(item.absolute_error || 0) <= 3).length;
    const bad = Math.max(0, items.length - good - warn);
    return [
      { name: "Точно", value: good, color: "#22c55e" },
      { name: "Заметно", value: warn, color: "#f59e0b" },
      { name: "Сильно", value: bad, color: "#ef4444" }
    ].filter((item) => item.value > 0);
  }, [topErrors?.items]);

  const errorChartData = (topErrors?.items || []).slice(0, 10).map((item) => ({
    name: item.name || item.wmo_index,
    error: item.absolute_error ?? 0,
    date: formatDate(item.forecast_date)
  }));

  const sourceChartData = sourceRatings.map((item) => ({
    source: sourceLabel(item.source),
    mae: item.mae ?? 0,
    rmse: item.rmse ?? 0,
    points: item.points
  }));

  const seriesChartData = (series?.items || [])
    .filter((item) => item.actual_avg_temp !== null || item.forecast_avg_temp !== null)
    .slice(0, 80)
    .map((item) => ({
      date: formatDate(item.observation_date),
      fact: item.actual_avg_temp,
      forecast: item.forecast_avg_temp,
      error: item.error_avg_temp
    }));

  return (
    <section className="pageStack">
      <div className="pageHeader">
        <div>
          <span>Аналитика</span>
          <h1>Панель точности прогнозов</h1>
          <p>Сводные показатели, ошибки, станции и динамика выбранного периода.</p>
        </div>
      </div>

      <div className="filterPanel">
        <label>
          <span>С даты</span>
          <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
        </label>
        <label>
          <span>По дату</span>
          <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
        </label>
        <label>
          <span>Метрика</span>
          <select value={metric} onChange={(event) => setMetric(event.target.value as Metric)}>
            <option value="avg_temp">Средняя температура</option>
            <option value="min_temp">Минимальная температура</option>
            <option value="max_temp">Максимальная температура</option>
            <option value="precipitation">Осадки</option>
          </select>
        </label>
        <label>
          <span>Источник</span>
          <select value={source} onChange={(event) => setSource(event.target.value as Source | "")}>
            <option value="">Все</option>
            <option value="forecast">forecast</option>
            <option value="previous_runs">historical</option>
          </select>
        </label>
        <label className="inputShell">
          <Search size={17} />
          <input placeholder="Модель" value={model} onChange={(event) => setModel(event.target.value)} />
        </label>
        <label>
          <span>Horizon</span>
          <select value={horizon} onChange={(event) => setHorizon(event.target.value ? Number(event.target.value) : "")}>
            <option value="">Все</option>
            {[1, 2, 3, 4, 5, 6, 7].map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
      </div>

      {loading ? <SkeletonGrid cards={4} /> : null}
      {error ? <ErrorState text={error} /> : null}

      {!loading && !error ? (
        <>
          <div className="metricGrid">
            <MetricCard
              icon={Gauge}
              label="Средняя ошибка"
              value={metricSummary?.mae === null || metricSummary?.mae === undefined ? "нет данных" : `${formatNumber(metricSummary.mae, 1)} ${metricUnits[metric]}`}
              hint={metricLabels[metric]}
              tone="blue"
            />
            <MetricCard
              icon={BarChart3}
              label="RMSE"
              value={metricSummary?.rmse === null || metricSummary?.rmse === undefined ? "нет данных" : formatNumber(metricSummary.rmse, 1)}
              hint={`Bias ${formatNumber(metricSummary?.bias, 1)}`}
              tone="green"
            />
            <MetricCard
              icon={Medal}
              label="Сравнений"
              value={formatNumber(metricSummary?.compared_points)}
              hint={`Макс. ошибка ${formatNumber(metricSummary?.max_absolute_error, 1)}`}
              tone="amber"
            />
            <MetricCard
              icon={PieIcon}
              label="Покрытий"
              value={formatNumber(coverage?.returned)}
              hint={`${formatNumber(summary?.totals.forecast_rows)} прогнозных строк`}
              tone="coral"
            />
          </div>

          <div className="chartGrid">
            <article className="panel chartPanel">
              <div className="panelHeader">
                <div>
                  <span>Ошибки</span>
                  <h2>Крупные ошибки</h2>
                </div>
                <BarChart3 size={20} />
              </div>
              {errorChartData.length ? (
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={errorChartData}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} angle={-15} textAnchor="end" height={70} />
                    <YAxis />
                    <Tooltip />
                    <Bar dataKey="error" name="Ошибка" fill="#38bdf8" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <EmptyState title="Ошибок нет" text="Backend не вернул top-errors для выбранных фильтров." />
              )}
            </article>

            <article className="panel chartPanel">
              <div className="panelHeader">
                <div>
                  <span>Источники</span>
                  <h2>Рейтинг точности</h2>
                </div>
                <Medal size={20} />
              </div>
              {sourceChartData.length ? (
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={sourceChartData}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="source" />
                    <YAxis />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="mae" name="MAE" fill="#22c55e" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="rmse" name="RMSE" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <EmptyState title="Рейтинг пуст" text="Нет сравнений по источникам в выбранном периоде." />
              )}
            </article>

            <article className="panel chartPanel">
              <div className="panelHeader">
                <div>
                  <span>Статусы</span>
                  <h2>Распределение ошибок</h2>
                </div>
                <PieIcon size={20} />
              </div>
              {statusData.length ? (
                <ResponsiveContainer width="100%" height={280}>
                  <PieChart>
                    <Pie data={statusData} dataKey="value" nameKey="name" innerRadius={60} outerRadius={95} paddingAngle={4}>
                      {statusData.map((entry) => (
                        <Cell key={entry.name} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <EmptyState title="Статусов нет" text="Нет строк для построения диаграммы." />
              )}
            </article>

            <article className="panel chartPanel">
              <div className="panelHeader">
                <div>
                  <span>Станция</span>
                  <h2>Прогноз и факт</h2>
                </div>
                <LineIcon size={20} />
              </div>
              <div className="inlineFilters">
                <label>
                  <span>Станция</span>
                  <select value={selectedStation} onChange={(event) => setSelectedStation(event.target.value ? Number(event.target.value) : "")}>
                    <option value="">Не выбрана</option>
                    {stations.map((station) => (
                      <option key={station.id} value={station.id}>
                        {station.name} · {station.wmo_index}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {seriesLoading ? <LoadingPanel /> : null}
              {seriesError ? <ErrorState text={seriesError} /> : null}
              {!seriesLoading && !seriesError && seriesChartData.length ? (
                <ResponsiveContainer width="100%" height={280}>
                  <LineChart data={seriesChartData}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={18} />
                    <YAxis />
                    <Tooltip />
                    <Legend />
                    <Line type="monotone" dataKey="fact" name="Факт" stroke="#22c55e" strokeWidth={2} dot={false} />
                    <Line type="monotone" dataKey="forecast" name="Прогноз" stroke="#38bdf8" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              ) : null}
              {!seriesLoading && !seriesError && !seriesChartData.length ? (
                <EmptyState title="Динамика пуста" text="Выбранная станция не имеет сопоставимых строк за период." />
              ) : null}
            </article>
          </div>

          <article className="panel">
            <div className="panelHeader">
              <div>
                <span>Станции</span>
                <h2>Худшие MAE</h2>
              </div>
            </div>
            {worstStations?.items.length ? (
              <div className="tableScroll">
                <table>
                  <thead>
                    <tr>
                      <th>Станция</th>
                      <th>WMO</th>
                      <th>Сравнений</th>
                      <th>MAE</th>
                      <th>Макс. ошибка</th>
                    </tr>
                  </thead>
                  <tbody>
                    {worstStations.items.map((item) => (
                      <tr key={item.station_id}>
                        <td>{item.name}</td>
                        <td>{item.wmo_index}</td>
                        <td>{formatNumber(item.compared_points)}</td>
                        <td>{formatNumber(item.mae, 1)}</td>
                        <td>{formatNumber(item.max_absolute_error, 1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState title="Станций нет" text="Нет агрегированных ошибок по станциям." />
            )}
          </article>
        </>
      ) : null}
    </section>
  );
}
