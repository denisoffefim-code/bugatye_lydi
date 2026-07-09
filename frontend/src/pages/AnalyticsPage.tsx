import { BarChart3, Gauge, LineChart as LineIcon, MapPinned, Radar, Search, SlidersHorizontal, Target, Trophy } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, formatApiError } from "../api/client";
import { EmptyState, ErrorState, SkeletonGrid } from "../components/DataState";
import { MetricCard } from "../components/MetricCard";
import type {
  AnalyticsSummaryResponse,
  Metric,
  Station,
  StationSeriesResponse,
  TopErrorsResponse,
  WorstStationsResponse
} from "../types";
import {
  averageAbsoluteError,
  biasSummary,
  chartNumberDomain,
  collapseSeriesRows,
  finiteNumber,
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

const metricOrder: Metric[] = ["avg_temp", "min_temp", "max_temp", "precipitation"];

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
  const [series, setSeries] = useState<StationSeriesResponse | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
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
  const activeMetricCount = metricOrder.filter((metric) => Number(summary?.metrics[metric]?.compared_points || 0) > 0).length;

  const errorChartData = (topErrors?.items || []).slice(0, 8).map((item) => ({
    name: item.name.length > 14 ? `${item.name.slice(0, 14)}...` : item.name,
    error: finiteNumber(item.absolute_error) ?? 0
  }));
  const seriesChartData = dailySeries.map((item) => ({
    date: formatDate(item.date),
    forecast: item.forecast,
    actual: item.actual
  }));
  const errorChartDomain = chartNumberDomain(errorChartData.map((item) => item.error));
  const seriesChartDomain = chartNumberDomain(seriesChartData.flatMap((item) => [item.actual, item.forecast]));

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
    setWarnings([]);

    const baseParams = {
      start_date: query.startDate,
      end_date: query.endDate,
      model: query.model.trim() || undefined,
      horizon_days: query.horizon || undefined
    };

    try {
      const primaryResults = await Promise.allSettled([
        api.summary({ ...baseParams, only_with_coordinates: true })
      ]);
      const secondaryResults = await Promise.allSettled([
        api.topErrors({ ...baseParams, metric: query.metric, limit: 12, only_with_coordinates: true }),
        api.worstStations({ ...baseParams, metric: query.metric, limit: 10 }),
        query.stationId
          ? api.stationSeries({
              ...baseParams,
              station_id: Number(query.stationId)
            })
          : Promise.resolve(null)
      ]);

      const nextWarnings: string[] = [];
      let successCount = 0;

      if (primaryResults[0].status === "fulfilled") {
        setSummary(primaryResults[0].value);
        successCount += 1;
      } else {
        setSummary(null);
        nextWarnings.push(`Сводка периода недоступна: ${formatApiError(primaryResults[0].reason)}`);
      }

      if (secondaryResults[0].status === "fulfilled") {
        setTopErrors(secondaryResults[0].value);
        successCount += 1;
      } else {
        setTopErrors(null);
        nextWarnings.push(`Список крупных ошибок временно недоступен: ${formatApiError(secondaryResults[0].reason)}`);
      }

      if (secondaryResults[1].status === "fulfilled") {
        setWorstStations(secondaryResults[1].value);
        successCount += 1;
      } else {
        setWorstStations(null);
        nextWarnings.push(`Рейтинг станций временно недоступен: ${formatApiError(secondaryResults[1].reason)}`);
      }

      if (secondaryResults[2].status === "fulfilled") {
        setSeries(secondaryResults[2].value);
        if (query.stationId) {
          successCount += 1;
        }
      } else {
        setSeries(null);
        nextWarnings.push(`График по станции временно недоступен: ${formatApiError(secondaryResults[2].reason)}`);
      }

      if (!successCount) {
        setError(nextWarnings[0] || "Не удалось загрузить аналитику.");
        setWarnings([]);
        return;
      }

      setWarnings(nextWarnings);
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
    setSeries(null);
    setError(null);
    setWarnings([]);
    setHasLoaded(false);
  }

  return (
    <section className="pageStack">
      <div className="pageHeader">
        <div>
          <span>Аналитика</span>
          <h1>Разбор точности прогноза</h1>
          <p>Выберите период и параметры, затем запустите анализ, чтобы увидеть ключевые выводы, проблемные станции и ежедневную динамику.</p>
        </div>
      </div>

      <form
        className="analysisForm"
        onSubmit={(event) => {
          event.preventDefault();
          void runAnalytics({ ...filters, model: filters.model.trim() });
        }}
      >
        <div className="filterPanel mainFilters">
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
        </div>

        <div className="formActions">
          <button className="primaryButton analysisButton" type="submit" disabled={loading}>
            <BarChart3 size={18} />
            {loading ? "Строим анализ" : "Показать анализ"}
          </button>
          <button className="ghostButton" type="button" onClick={handleReset} disabled={loading}>
            Сбросить
          </button>
          <button className="ghostButton filterToggle" type="button" onClick={() => setShowAdvanced((current) => !current)}>
            <SlidersHorizontal size={17} />
            Дополнительные параметры
          </button>
        </div>

        {showAdvanced ? (
          <div className="filterPanel advancedPanel">
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
          </div>
        ) : null}
      </form>

      {loading ? <SkeletonGrid cards={4} /> : null}
      {error ? <ErrorState text={error} /> : null}
      {!loading && !error && warnings.length ? <div className="noticeLine">{warnings.join(" ")}</div> : null}

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
              label="Погодных метрик"
              value={formatNumber(activeMetricCount)}
              hint="температура, осадки и сравнения"
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
                <span>Период анализа</span>
                <strong>{activeFilters ? `${formatDate(activeFilters.startDate)} - ${formatDate(activeFilters.endDate)}` : "нет данных"}</strong>
              </div>
              <div>
                <span>Системное смещение</span>
                <strong>{biasSummary(metricSummary?.bias, selectedMetric)}</strong>
              </div>
              <div>
                <span>Активная метрика</span>
                <strong>{metricLabels[selectedMetric]}</strong>
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
                  <BarChart data={errorChartData} margin={{ top: 12, right: 16, bottom: 12, left: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} angle={-12} textAnchor="end" height={70} tickMargin={10} />
                    <YAxis domain={errorChartDomain} allowDataOverflow tickFormatter={(value) => formatNumber(value, 1)} />
                    <Tooltip />
                    <Bar dataKey="error" name="Абсолютная ошибка" fill="#38bdf8" radius={[4, 4, 0, 0]} maxBarSize={38} />
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
                    <LineChart data={seriesChartData} margin={{ top: 12, right: 16, bottom: 8, left: 4 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={18} />
                      <YAxis domain={seriesChartDomain} allowDataOverflow tickFormatter={(value) => formatNumber(value, 1)} />
                      <Tooltip />
                      <Legend />
                      <Line type="linear" dataKey="actual" name="Факт" stroke="#22c55e" strokeWidth={2} dot={false} />
                      <Line type="linear" dataKey="forecast" name="Прогноз" stroke="#38bdf8" strokeWidth={2} dot={false} />
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
        </>
      ) : null}
    </section>
  );
}
