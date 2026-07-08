import { GitCompareArrows, LineChart as LineIcon, Search, SlidersHorizontal, Target, ThermometerSun, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, formatApiError } from "../api/client";
import { EmptyState, ErrorState, SkeletonGrid } from "../components/DataState";
import { MetricCard } from "../components/MetricCard";
import { AccuracyBadge } from "../components/StatusBadge";
import type { Metric, Station, StationSeriesResponse } from "../types";
import {
  averageAbsoluteError,
  collapseSeriesRows,
  defaultRange,
  formatDate,
  formatDateTime,
  formatNumber,
  maxAbsoluteErrorPoint,
  metricLabels,
  metricUnits,
  signed
} from "../utils";

interface CompareFilters {
  stationId: number | "";
  startDate: string;
  endDate: string;
  metric: Metric;
  model: string;
  horizon: number | "";
}

const defaultFilters = (): CompareFilters => {
  const range = defaultRange(10);
  return {
    stationId: "",
    startDate: range.start,
    endDate: range.end,
    metric: "avg_temp",
    model: "",
    horizon: ""
  };
};

export function ComparePage() {
  const [stations, setStations] = useState<Station[]>([]);
  const [filters, setFilters] = useState<CompareFilters>(() => defaultFilters());
  const [activeFilters, setActiveFilters] = useState<CompareFilters | null>(null);
  const [series, setSeries] = useState<StationSeriesResponse | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [stationsLoading, setStationsLoading] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasLoaded, setHasLoaded] = useState(false);

  useEffect(() => {
    let active = true;

    async function loadStations() {
      setStationsLoading(true);
      try {
        const response = await api.stations({ limit: 500, with_coordinates_only: true });
        if (active) {
          setStations(response.stations);
        }
      } catch (err) {
        if (active) {
          setError(formatApiError(err));
          setStations([]);
        }
      } finally {
        if (active) {
          setStationsLoading(false);
        }
      }
    }

    void loadStations();
    return () => {
      active = false;
    };
  }, []);

  const selectedMetric = activeFilters?.metric || filters.metric;
  const dailyRows = useMemo(() => collapseSeriesRows(series?.items || [], selectedMetric), [selectedMetric, series?.items]);
  const comparedDays = dailyRows.filter((row) => row.actual !== null && row.forecast !== null).length;
  const forecastDays = dailyRows.filter((row) => row.forecast !== null).length;
  const actualDays = dailyRows.filter((row) => row.actual !== null).length;
  const averageError = averageAbsoluteError(dailyRows);
  const maxErrorPoint = maxAbsoluteErrorPoint(dailyRows);
  const chartData = dailyRows.map((row) => ({
    date: formatDate(row.date),
    forecast: row.forecast,
    actual: row.actual
  }));

  function updateFilter<K extends keyof CompareFilters>(key: K, value: CompareFilters[K]) {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  async function runComparison(query: CompareFilters) {
    if (!query.stationId) {
      setError("Сначала выберите станцию.");
      return;
    }
    if (query.endDate < query.startDate) {
      setError("Дата окончания должна быть не раньше даты начала.");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await api.stationSeries({
        station_id: Number(query.stationId),
        start_date: query.startDate,
        end_date: query.endDate,
        model: query.model.trim() || undefined,
        horizon_days: query.horizon || undefined
      });
      setSeries(response);
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
    setSeries(null);
    setActiveFilters(null);
    setError(null);
    setHasLoaded(false);
  }

  return (
    <section className="pageStack">
      <div className="pageHeader">
        <div>
          <span>Разбор станции</span>
          <h1>Факт против прогноза по дням</h1>
          <p>Здесь один запрос строит ежедневную картину по станции: факт, прогноз, ошибка и дата самого сильного промаха.</p>
        </div>
      </div>

      <form
        className="filterPanel"
        onSubmit={(event) => {
          event.preventDefault();
          void runComparison({ ...filters, model: filters.model.trim() });
        }}
      >
        <label>
          <span>Станция</span>
          <select value={filters.stationId} onChange={(event) => updateFilter("stationId", event.target.value ? Number(event.target.value) : "")}>
            <option value="">Выберите станцию</option>
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
          <button className="primaryButton" type="submit" disabled={loading || stationsLoading}>
            <GitCompareArrows size={18} />
            {loading ? "Сравниваем" : "Показать сравнение"}
          </button>
          <button className="ghostButton" type="button" onClick={handleReset} disabled={loading}>
            Сбросить
          </button>
        </div>
      </form>

      {stationsLoading ? <SkeletonGrid cards={3} /> : null}
      {loading ? <SkeletonGrid cards={4} /> : null}
      {error ? <ErrorState text={error} /> : null}

      {!stationsLoading && !loading && !error && !hasLoaded ? (
        <EmptyState title="Сравнение еще не запущено" text="Выберите станцию и нажмите «Показать сравнение»." />
      ) : null}

      {!stationsLoading && !loading && !error && hasLoaded ? (
        <>
          <div className="metricGrid">
            <MetricCard
              icon={Target}
              label="Сопоставимых дней"
              value={formatNumber(comparedDays)}
              hint={`метрика: ${metricLabels[selectedMetric].toLowerCase()}`}
              tone="blue"
            />
            <MetricCard
              icon={ThermometerSun}
              label="Средняя ошибка"
              value={averageError === null ? "нет данных" : `${formatNumber(averageError, 1)} ${metricUnits[selectedMetric]}`}
              hint={`дней с прогнозом: ${formatNumber(forecastDays)}`}
              tone="green"
            />
            <MetricCard
              icon={TriangleAlert}
              label="Максимальный промах"
              value={
                maxErrorPoint?.error === null || maxErrorPoint?.error === undefined
                  ? "нет данных"
                  : `${formatNumber(Math.abs(Number(maxErrorPoint.error)), 1)} ${metricUnits[selectedMetric]}`
              }
              hint={maxErrorPoint ? formatDate(maxErrorPoint.date) : "дата не определена"}
              tone="amber"
            />
            <MetricCard
              icon={LineIcon}
              label="Дней факта"
              value={formatNumber(actualDays)}
              hint={series?.station.name || "станция не выбрана"}
              tone="coral"
            />
          </div>

          <article className="panel">
            <div className="panelHeader">
              <div>
                <span>Кратко</span>
                <h2>{series?.station.name || "Станция"}</h2>
              </div>
              <GitCompareArrows size={20} />
            </div>
            <div className="detailGrid">
              <div>
                <span>Период</span>
                <strong>
                  {activeFilters ? `${formatDate(activeFilters.startDate)} - ${formatDate(activeFilters.endDate)}` : "нет данных"}
                </strong>
              </div>
              <div>
                <span>Метрика</span>
                <strong>{metricLabels[selectedMetric]}</strong>
              </div>
              <div>
                <span>Самый сильный промах</span>
                <strong>
                  {maxErrorPoint?.error === null || maxErrorPoint?.error === undefined
                    ? "нет данных"
                    : `${formatNumber(Math.abs(Number(maxErrorPoint.error)), 1)} ${metricUnits[selectedMetric]} · ${formatDate(maxErrorPoint.date)}`}
                </strong>
              </div>
              <div>
                <span>Последний использованный запуск</span>
                <strong>{maxErrorPoint?.runAt ? formatDateTime(maxErrorPoint.runAt) : "нет данных"}</strong>
              </div>
            </div>
          </article>

          <article className="panel chartPanel">
            <div className="panelHeader">
              <div>
                <span>Динамика</span>
                <h2>Как расходились факт и прогноз</h2>
              </div>
              <LineIcon size={20} />
            </div>
            {chartData.length ? (
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={18} />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="actual" name="Факт" stroke="#22c55e" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="forecast" name="Прогноз" stroke="#38bdf8" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState title="Данных для графика нет" text="За этот период сервис не вернул сравнимых ежедневных значений." />
            )}
          </article>

          <article className="panel">
            <div className="panelHeader">
              <div>
                <span>По дням</span>
                <h2>Ежедневная таблица сравнения</h2>
              </div>
            </div>
            {dailyRows.length ? (
              <div className="tableScroll">
                <table>
                  <thead>
                    <tr>
                      <th>Дата</th>
                      <th>Прогноз</th>
                      <th>Факт</th>
                      <th>Разница</th>
                      <th>Горизонт</th>
                      <th>Модель</th>
                      <th>Оценка</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dailyRows.map((row) => (
                      <tr key={row.date}>
                        <td>{formatDate(row.date)}</td>
                        <td>
                          {row.forecast === null || row.forecast === undefined
                            ? "нет данных"
                            : `${formatNumber(row.forecast, 1)} ${metricUnits[selectedMetric]}`}
                        </td>
                        <td>
                          {row.actual === null || row.actual === undefined
                            ? "нет данных"
                            : `${formatNumber(row.actual, 1)} ${metricUnits[selectedMetric]}`}
                        </td>
                        <td>{signed(row.error, ` ${metricUnits[selectedMetric]}`)}</td>
                        <td>{row.horizonDays ? `${row.horizonDays} дн.` : "нет данных"}</td>
                        <td>{row.model || "нет данных"}</td>
                        <td>
                          <AccuracyBadge value={row.error === null ? null : Math.abs(Number(row.error))} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState title="Таблица пуста" text="В выбранном периоде нет строк, которые можно сопоставить по станции." />
            )}
          </article>
        </>
      ) : null}
    </section>
  );
}
