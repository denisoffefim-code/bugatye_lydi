import { BarChart3, Gauge, LineChart as LineIcon, MapPinned, Radar, Search, SlidersHorizontal, Target, Trophy } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, formatApiError } from "../api/client";
import { EmptyState, ErrorState, SkeletonGrid } from "../components/DataState";
import { MetricCard } from "../components/MetricCard";
import type {
  AnalyticsSummaryResponse,
  ForecastCoverageResponse,
  Metric,
  Station,
  StationSeriesResponse,
  TopErrorsResponse,
  WorstStationsResponse
} from "../types";
import {
  averageAbsoluteError,
  biasSummary,
  collapseSeriesRows,
  defaultRange,
  formatDate,
  formatNumber,
  metricLabels,
  metricUnits
} from "../utils";

interface AnalysisFilters {
  stationId: number | "";
  startDate: string;
  endDate: string;
  metric: Metric;
  model: string;
  horizon: number | "";
}

const defaultFilters = (): AnalysisFilters => {
  const range = defaultRange(14);
  return {
    stationId: "",
    startDate: range.start,
    endDate: range.end,
    metric: "avg_temp",
    model: "",
    horizon: ""
  };
};

export function AnalyticsPage() {
  const [stations, setStations] = useState<Station[]>([]);
  const [filters, setFilters] = useState<AnalysisFilters>(() => defaultFilters());
  const [activeFilters, setActiveFilters] = useState<AnalysisFilters | null>(null);
  const [summary, setSummary] = useState<AnalyticsSummaryResponse | null>(null);
  const [topErrors, setTopErrors] = useState<TopErrorsResponse | null>(null);
  const [worstStations, setWorstStations] = useState<WorstStationsResponse | null>(null);
  const [coverage, setCoverage] = useState<ForecastCoverageResponse | null>(null);
  const [series, setSeries] = useState<StationSeriesResponse | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasLoaded, setHasLoaded] = useState(false);

  useEffect(() => {
    let active = true;

    async function loadStations() {
      try {
        const response = await api.stations({ limit: 500, with_coordinates_only: true });
        if (active) {
          setStations(response.stations);
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

  const selectedMetric = activeFilters?.metric || filters.metric;
  const metricSummary = summary?.metrics[selectedMetric] || null;
  const dailySeries = useMemo(() => collapseSeriesRows(series?.items || [], selectedMetric), [selectedMetric, series?.items]);
  const seriesAverageError = averageAbsoluteError(dailySeries);
  const biggestMiss = topErrors?.items[0] || null;
  const weakestStation = worstStations?.items[0] || null;
  const fullestDataset =
    coverage?.items.slice().sort((left, right) => Number(right.forecast_rows) - Number(left.forecast_rows))[0] || null;
  const modelCount = new Set((coverage?.items || []).map((item) => item.model)).size;
  const horizons = Array.from(new Set((coverage?.items || []).map((item) => item.horizon_days))).sort((left, right) => left - right);

  const errorChartData = (topErrors?.items || []).slice(0, 8).map((item) => ({
    name: item.name.length > 14 ? `${item.name.slice(0, 14)}...` : item.name,
    error: item.absolute_error ?? 0
  }));
  const seriesChartData = dailySeries.map((item) => ({
    date: formatDate(item.date),
    forecast: item.forecast,
    actual: item.actual
  }));

  function updateFilter<K extends keyof AnalysisFilters>(key: K, value: AnalysisFilters[K]) {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  async function runAnalytics(query: AnalysisFilters) {
    if (query.endDate < query.startDate) {
      setError("Дата окончания должна быть не раньше даты начала.");
      return;
    }

    setLoading(true);
    setError(null);

    const baseParams = {
      start_date: query.startDate,
      end_date: query.endDate,
      model: query.model.trim() || undefined,
      horizon_days: query.horizon || undefined
    };

    try {
      const [summaryResponse, topResponse, worstResponse, coverageResponse, seriesResponse] = await Promise.all([
        api.summary({ ...baseParams, only_with_coordinates: true }),
        api.topErrors({ ...baseParams, metric: query.metric, limit: 20, only_with_coordinates: true }),
        api.worstStations({ ...baseParams, metric: query.metric, limit: 12 }),
        api.forecastCoverage(baseParams),
        query.stationId
          ? api.stationSeries({
              ...baseParams,
              station_id: Number(query.stationId)
            })
          : Promise.resolve(null)
      ]);

      setSummary(summaryResponse);
      setTopErrors(topResponse);
      setWorstStations(worstResponse);
      setCoverage(coverageResponse);
      setSeries(seriesResponse);
      setActiveFilters(query);
      setHasLoaded(true);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setLoading(false);
    }
  }

  function handleReset() {
    setFilters(defaultFilters());
    setActiveFilters(null);
    setSummary(null);
    setTopErrors(null);
    setWorstStations(null);
    setCoverage(null);
    setSeries(null);
    setError(null);
    setHasLoaded(false);
  }

  return (
    <section className="pageStack">
      <div className="pageHeader">
        <div>
          <span>Аналитика</span>
          <h1>Разбор точности прогноза</h1>
          <p>Выберите период и параметры, затем по кнопке получите сводку, ключевые выводы, худшие станции и ежедневную динамику.</p>
        </div>
      </div>

      <form
        className="filterPanel"
        onSubmit={(event) => {
          event.preventDefault();
          void runAnalytics({ ...filters, model: filters.model.trim() });
        }}
      >
        <label>
          <span>Станция для графика</span>
          <select value={filters.stationId} onChange={(event) => updateFilter("stationId", event.target.value ? Number(event.target.value) : "")}>
            <option value="">Без станции</option>
            {stations.map((station) => (
              <option key={station.id} value={station.id}>
                {station.name} · {station.wmo_index}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>С даты</span>
          <input type="date" value={filters.startDate} onChange={(event) => updateFilter("startDate", event.target.value)} />
        </label>
        <label>
          <span>По дату</span>
          <input type="date" value={filters.endDate} onChange={(event) => updateFilter("endDate", event.target.value)} />
        </label>
        <label>
          <span>Метрика</span>
          <select value={filters.metric} onChange={(event) => updateFilter("metric", event.target.value as Metric)}>
            <option value="avg_temp">Средняя температура</option>
            <option value="min_temp">Минимальная температура</option>
            <option value="max_temp">Максимальная температура</option>
            <option value="precipitation">Осадки</option>
          </select>
        </label>
        <button className="ghostButton filterToggle" type="button" onClick={() => setShowAdvanced((current) => !current)}>
          <SlidersHorizontal size={17} />
          Дополнительно
        </button>

        {showAdvanced ? (
          <>
            <label>
              <span>Модель</span>
              <div className="inputShell">
                <Search size={17} />
                <input placeholder="Например, gfs_seamless" value={filters.model} onChange={(event) => updateFilter("model", event.target.value)} />
              </div>
            </label>
            <label>
              <span>Горизонт</span>
              <select value={filters.horizon} onChange={(event) => updateFilter("horizon", event.target.value ? Number(event.target.value) : "")}>
                <option value="">Все</option>
                {[1, 2, 3, 4, 5, 6, 7].map((value) => (
                  <option key={value} value={value}>
                    {value} дн.
                  </option>
                ))}
              </select>
            </label>
          </>
        ) : null}

        <div className="formActions">
          <button className="primaryButton" type="submit" disabled={loading}>
            <BarChart3 size={18} />
            {loading ? "Строим анализ" : "Показать анализ"}
          </button>
          <button className="ghostButton" type="button" onClick={handleReset} disabled={loading}>
            Сбросить
          </button>
        </div>
      </form>

      {loading ? <SkeletonGrid cards={4} /> : null}
      {error ? <ErrorState text={error} /> : null}

      {!loading && !error && !hasLoaded ? (
        <EmptyState title="Анализ еще не запущен" text="Выберите параметры выше и нажмите «Показать анализ»." />
      ) : null}

      {!loading && !error && hasLoaded ? (
        <>
          <div className="metricGrid">
            <MetricCard
              icon={Gauge}
              label={`Средняя ошибка · ${metricLabels[selectedMetric]}`}
              value={
                metricSummary?.mae === null || metricSummary?.mae === undefined
                  ? "нет данных"
                  : `${formatNumber(metricSummary.mae, 1)} ${metricUnits[selectedMetric]}`
              }
              hint={biasSummary(metricSummary?.bias, selectedMetric)}
              tone="blue"
            />
            <MetricCard
              icon={Target}
              label="Сравнимых точек"
              value={formatNumber(metricSummary?.compared_points ?? 0)}
              hint={`максимальный промах: ${formatNumber(metricSummary?.max_absolute_error, 1)} ${metricUnits[selectedMetric]}`}
              tone="green"
            />
            <MetricCard
              icon={Trophy}
              label="Худшая станция"
              value={weakestStation?.name || "нет данных"}
              hint={
                weakestStation?.mae === null || weakestStation?.mae === undefined
                  ? "средняя ошибка не рассчитана"
                  : `MAE ${formatNumber(weakestStation.mae, 1)} ${metricUnits[selectedMetric]}`
              }
              tone="amber"
            />
            <MetricCard
              icon={Radar}
              label="Покрытие прогноза"
              value={formatNumber(coverage?.returned ?? 0)}
              hint={fullestDataset ? `${fullestDataset.model}, ${fullestDataset.horizon_days} дн.` : "нет покрытых наборов"}
              tone="coral"
            />
          </div>

          <article className="panel">
            <div className="panelHeader">
              <div>
                <span>Что важно</span>
                <h2>Ключевые выводы по периоду</h2>
              </div>
              <MapPinned size={20} />
            </div>
            <div className="detailGrid">
              <div>
                <span>Крупнейший промах</span>
                <strong>
                  {biggestMiss
                    ? `${biggestMiss.name} · ${formatNumber(biggestMiss.absolute_error, 1)} ${metricUnits[selectedMetric]}`
                    : "нет данных"}
                </strong>
              </div>
              <div>
                <span>Дата крупнейшего промаха</span>
                <strong>{biggestMiss ? formatDate(biggestMiss.forecast_date) : "нет данных"}</strong>
              </div>
              <div>
                <span>Худшая станция по среднему качеству</span>
                <strong>{weakestStation ? `${weakestStation.name} · ${formatNumber(weakestStation.compared_points)} сравн.` : "нет данных"}</strong>
              </div>
              <div>
                <span>Основной набор прогноза</span>
                <strong>
                  {fullestDataset
                    ? `${fullestDataset.model}, ${fullestDataset.horizon_days} дн., ${formatNumber(fullestDataset.station_count)} станций`
                    : "нет данных"}
                </strong>
              </div>
              <div>
                <span>Системное смещение</span>
                <strong>{biasSummary(metricSummary?.bias, selectedMetric)}</strong>
              </div>
              <div>
                <span>Моделей и горизонтов</span>
                <strong>
                  {formatNumber(modelCount)} моделей · {horizons.length ? horizons.join(", ") : "нет"} дн.
                </strong>
              </div>
            </div>
          </article>

          <div className="chartGrid">
            <article className="panel chartPanel">
              <div className="panelHeader">
                <div>
                  <span>Лидеры ошибок</span>
                  <h2>Где прогноз промахнулся сильнее всего</h2>
                </div>
                <BarChart3 size={20} />
              </div>
              {errorChartData.length ? (
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={errorChartData}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} angle={-12} textAnchor="end" height={70} />
                    <YAxis />
                    <Tooltip />
                    <Bar dataKey="error" name="Абсолютная ошибка" fill="#38bdf8" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <EmptyState title="Нет ошибок для графика" text="За выбранный период нет сравнимых записей по этой метрике." />
              )}
            </article>

            <article className="panel chartPanel">
              <div className="panelHeader">
                <div>
                  <span>Станция</span>
                  <h2>{series?.station.name || "Ежедневный факт и прогноз"}</h2>
                </div>
                <LineIcon size={20} />
              </div>
              {seriesChartData.length ? (
                <>
                  <div className="detailGrid">
                    <div>
                      <span>Дней на графике</span>
                      <strong>{formatNumber(seriesChartData.length)}</strong>
                    </div>
                    <div>
                      <span>Средняя ошибка по станции</span>
                      <strong>
                        {seriesAverageError === null ? "нет данных" : `${formatNumber(seriesAverageError, 1)} ${metricUnits[selectedMetric]}`}
                      </strong>
                    </div>
                  </div>
                  <ResponsiveContainer width="100%" height={220}>
                    <LineChart data={seriesChartData}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={18} />
                      <YAxis />
                      <Tooltip />
                      <Legend />
                      <Line type="monotone" dataKey="actual" name="Факт" stroke="#22c55e" strokeWidth={2} dot={false} />
                      <Line type="monotone" dataKey="forecast" name="Прогноз" stroke="#38bdf8" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </>
              ) : (
                <EmptyState
                  title="График не построен"
                  text="Чтобы увидеть ежедневную динамику, выберите станцию и запустите анализ еще раз."
                />
              )}
            </article>
          </div>

          <article className="panel">
            <div className="panelHeader">
              <div>
                <span>Ошибки</span>
                <h2>Крупные расхождения по станциям</h2>
              </div>
            </div>
            {topErrors?.items.length ? (
              <div className="tableScroll">
                <table>
                  <thead>
                    <tr>
                      <th>Станция</th>
                      <th>Дата</th>
                      <th>Модель</th>
                      <th>Горизонт</th>
                      <th>Прогноз</th>
                      <th>Факт</th>
                      <th>Ошибка</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topErrors.items.map((item) => (
                      <tr key={`${item.station_id}-${item.forecast_date}-${item.horizon_days}`}>
                        <td>{item.name}</td>
                        <td>{formatDate(item.forecast_date)}</td>
                        <td>{item.model}</td>
                        <td>{item.horizon_days} дн.</td>
                        <td>{formatNumber(item.forecast_value, 1)}</td>
                        <td>{formatNumber(item.actual_value, 1)}</td>
                        <td>{formatNumber(item.absolute_error, 1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState title="Ошибок нет" text="Сервис не вернул крупных расхождений по выбранным параметрам." />
            )}
          </article>

          <div className="dashboardGrid">
            <article className="panel">
              <div className="panelHeader">
                <div>
                  <span>Станции</span>
                  <h2>Где средняя ошибка выше всего</h2>
                </div>
              </div>
              {worstStations?.items.length ? (
                <div className="tableScroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Станция</th>
                        <th>Сравнений</th>
                        <th>MAE</th>
                        <th>Макс. ошибка</th>
                      </tr>
                    </thead>
                    <tbody>
                      {worstStations.items.map((item) => (
                        <tr key={item.station_id}>
                          <td>{item.name}</td>
                          <td>{formatNumber(item.compared_points)}</td>
                          <td>{formatNumber(item.mae, 1)}</td>
                          <td>{formatNumber(item.max_absolute_error, 1)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState title="Станции не найдены" text="Нет агрегированных ошибок по станциям за этот период." />
              )}
            </article>

            <article className="panel">
              <div className="panelHeader">
                <div>
                  <span>Покрытие</span>
                  <h2>Какие прогнозы реально доступны</h2>
                </div>
              </div>
              {coverage?.items.length ? (
                <div className="tableScroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Модель</th>
                        <th>Горизонт</th>
                        <th>Строк</th>
                        <th>Станций</th>
                        <th>Период</th>
                      </tr>
                    </thead>
                    <tbody>
                      {coverage.items.map((item) => (
                        <tr key={`${item.model}-${item.horizon_days}`}>
                          <td>{item.model}</td>
                          <td>{item.horizon_days} дн.</td>
                          <td>{formatNumber(item.forecast_rows)}</td>
                          <td>{formatNumber(item.station_count)}</td>
                          <td>
                            {formatDate(item.forecast_start_date)} - {formatDate(item.forecast_end_date)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState title="Покрытие пусто" text="Прогнозные наборы за выбранный период не найдены." />
              )}
            </article>
          </div>
        </>
      ) : null}
    </section>
  );
}
