import { BarChart3, CalendarDays, CloudSun, Eye, Layers3, LineChart as LineIcon, Search, SlidersHorizontal } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, formatApiError } from "../api/client";
import { EmptyState, ErrorState, LoadingPanel, SkeletonGrid } from "../components/DataState";
import { MetricCard } from "../components/MetricCard";
import { Modal } from "../components/Modal";
import type { Metric, Station, StationSeriesItem, StationSeriesResponse } from "../types";
import { chartNumberDomain, defaultRange, formatDate, formatDateTime, formatNumber, metricLabels, metricUnits } from "../utils";

interface ForecastFilters {
  stationId: number | "";
  startDate: string;
  endDate: string;
  metric: Metric;
  model: string;
  horizon: number | "";
}

const defaultFilters = (): ForecastFilters => {
  const range = defaultRange(7);
  return {
    stationId: "",
    startDate: range.start,
    endDate: range.end,
    metric: "avg_temp",
    model: "",
    horizon: ""
  };
};

function hasForecastData(item: StationSeriesItem) {
  return (
    item.forecast_avg_temp !== null ||
    item.forecast_min_temp !== null ||
    item.forecast_max_temp !== null ||
    item.forecast_precipitation !== null
  );
}

function metricValues(item: StationSeriesItem, metric: Metric) {
  if (metric === "min_temp") {
    return {
      forecast: item.forecast_min_temp,
      actual: item.actual_min_temp
    };
  }
  if (metric === "max_temp") {
    return {
      forecast: item.forecast_max_temp,
      actual: item.actual_max_temp
    };
  }
  if (metric === "precipitation") {
    return {
      forecast: item.forecast_precipitation,
      actual: item.actual_precipitation
    };
  }
  return {
    forecast: item.forecast_avg_temp,
    actual: item.actual_avg_temp
  };
}

export function ForecastsPage() {
  const [stations, setStations] = useState<Station[]>([]);
  const [filters, setFilters] = useState<ForecastFilters>(() => defaultFilters());
  const [activeFilters, setActiveFilters] = useState<ForecastFilters | null>(null);
  const [series, setSeries] = useState<StationSeriesResponse | null>(null);
  const [selectedForecast, setSelectedForecast] = useState<StationSeriesItem | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [stationsLoading, setStationsLoading] = useState(true);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasLoaded, setHasLoaded] = useState(false);

  useEffect(() => {
    let active = true;

    async function loadStations() {
      setStationsLoading(true);
      setError(null);
      try {
        const response = await api.stations({ limit: 500, with_coordinates_only: true });
        if (!active) {
          return;
        }

        setStations(response.stations);
        setFilters((current) => ({
          ...current,
          stationId: current.stationId || response.stations[0]?.id || ""
        }));
      } catch (err) {
        if (active) {
          setStations([]);
          setError(formatApiError(err));
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

  function updateFilter<K extends keyof ForecastFilters>(key: K, value: ForecastFilters[K]) {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  async function runAnalysis(query: ForecastFilters) {
    if (!query.stationId) {
      setError("Сначала выберите станцию.");
      return;
    }
    if (query.endDate < query.startDate) {
      setError("Дата окончания должна быть не раньше даты начала.");
      return;
    }

    setAnalysisLoading(true);
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
      setSeries(null);
      setError(formatApiError(err));
    } finally {
      setAnalysisLoading(false);
    }
  }

  function handleReset() {
    const next = defaultFilters();
    next.stationId = stations[0]?.id || "";
    setFilters(next);
    setActiveFilters(null);
    setSeries(null);
    setSelectedForecast(null);
    setError(null);
    setHasLoaded(false);
    setShowAdvanced(false);
  }

  const selectedMetric = activeFilters?.metric || filters.metric;
  const forecastRows = useMemo(
    () =>
      (series?.items || [])
        .filter(hasForecastData)
        .slice()
        .sort((left, right) => {
          const dateDiff = new Date(right.observation_date).getTime() - new Date(left.observation_date).getTime();
          if (dateDiff !== 0) {
            return dateDiff;
          }
          return new Date(right.run_at || 0).getTime() - new Date(left.run_at || 0).getTime();
        }),
    [series?.items]
  );

  const chartData = useMemo(() => {
    const grouped = new Map<
      string,
      {
        forecastValues: number[];
        actualValues: number[];
        variants: number;
      }
    >();

    for (const item of forecastRows) {
      const current = grouped.get(item.observation_date) || {
        forecastValues: [],
        actualValues: [],
        variants: 0
      };
      const values = metricValues(item, selectedMetric);
      if (typeof values.forecast === "number") {
        current.forecastValues.push(values.forecast);
      }
      if (typeof values.actual === "number") {
        current.actualValues.push(values.actual);
      }
      current.variants += 1;
      grouped.set(item.observation_date, current);
    }

    return Array.from(grouped.entries())
      .sort((left, right) => new Date(left[0]).getTime() - new Date(right[0]).getTime())
      .map(([date, value]) => ({
        date: formatDate(date),
        forecast: value.forecastValues.length
          ? value.forecastValues.reduce((sum, item) => sum + item, 0) / value.forecastValues.length
          : null,
        actual: value.actualValues.length ? value.actualValues.reduce((sum, item) => sum + item, 0) / value.actualValues.length : null,
        variants: value.variants
      }));
  }, [forecastRows, selectedMetric]);

  const chartDomain = chartNumberDomain(chartData.flatMap((item) => [item.forecast, item.actual]));
  const forecastDays = chartData.filter((item) => item.forecast !== null).length;
  const modelNames = Array.from(new Set(forecastRows.map((item) => item.model).filter((value): value is string => Boolean(value))));
  const horizonValues = forecastRows.map((item) => item.horizon_days).filter((value): value is number => value !== null);
  const averageHorizon = horizonValues.length ? horizonValues.reduce((sum, value) => sum + value, 0) / horizonValues.length : null;
  const updateMoments = forecastRows.map((item) => item.run_at).filter((value): value is string => Boolean(value)).sort();
  const latestUpdateValue = updateMoments[updateMoments.length - 1];
  const dominantModelEntry =
    Array.from(
      forecastRows.reduce((accumulator, item) => {
        if (item.model) {
          accumulator.set(item.model, (accumulator.get(item.model) || 0) + 1);
        }
        return accumulator;
      }, new Map<string, number>())
    ).sort((left, right) => right[1] - left[1])[0] || null;
  const availableHorizons = Array.from(new Set(horizonValues)).sort((left, right) => left - right);

  return (
    <section className="pageStack">
      <div className="pageHeader">
        <div>
          <span>Прогнозы</span>
          <h1>Прогноз по станции</h1>
          <p>Выберите станцию, период и метрику, чтобы посмотреть прогнозные значения по дням, моделям и горизонтам.</p>
        </div>
      </div>

      <form
        className="analysisForm"
        onSubmit={(event) => {
          event.preventDefault();
          void runAnalysis({ ...filters, model: filters.model.trim() });
        }}
      >
        <div className="filterPanel mainFilters">
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
        </div>

        <div className="formActions">
          <button className="primaryButton analysisButton" type="submit" disabled={stationsLoading || analysisLoading}>
            <BarChart3 size={18} />
            {analysisLoading ? "Строим анализ" : "Показать анализ"}
          </button>
          <button className="ghostButton" type="button" onClick={handleReset} disabled={analysisLoading}>
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

      {stationsLoading ? <SkeletonGrid cards={3} /> : null}
      {analysisLoading ? <SkeletonGrid cards={4} /> : null}
      {error ? <ErrorState text={error} /> : null}

      {!stationsLoading && !analysisLoading && !error && !hasLoaded ? (
        <EmptyState title="Анализ еще не запущен" text="Выберите станцию и нажмите «Показать анализ»." />
      ) : null}

      {!stationsLoading && !analysisLoading && !error && hasLoaded ? (
        <>
          <div className="metricGrid">
            <MetricCard
              icon={CloudSun}
              label="Дней с прогнозом"
              value={formatNumber(forecastDays)}
              hint={series?.station.name || "станция не выбрана"}
              tone="blue"
            />
            <MetricCard
              icon={Layers3}
              label="Моделей в выборке"
              value={formatNumber(modelNames.length)}
              hint={dominantModelEntry ? `чаще всего: ${dominantModelEntry[0]}` : "модель не выделяется"}
              tone="green"
            />
            <MetricCard
              icon={CalendarDays}
              label="Средний горизонт"
              value={averageHorizon === null ? "нет данных" : `${formatNumber(averageHorizon, 1)} дн.`}
              hint={availableHorizons.length ? `варианты: ${availableHorizons.join(", ")} дн.` : "горизонты не определены"}
              tone="amber"
            />
            <MetricCard
              icon={LineIcon}
              label="Последнее обновление"
              value={latestUpdateValue ? formatDate(latestUpdateValue) : "нет данных"}
              hint={latestUpdateValue ? formatDateTime(latestUpdateValue) : "дата обновления не найдена"}
              tone="coral"
            />
          </div>

          <article className="panel">
            <div className="panelHeader">
              <div>
                <span>Кратко</span>
                <h2>{series?.station.name || "Станция"}</h2>
              </div>
              <CloudSun size={20} />
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
                <span>Основная модель</span>
                <strong>{dominantModelEntry ? `${dominantModelEntry[0]} · ${formatNumber(dominantModelEntry[1])} знач.` : "нет данных"}</strong>
              </div>
              <div>
                <span>Горизонты в выборке</span>
                <strong>{availableHorizons.length ? `${availableHorizons.join(", ")} дн.` : "нет данных"}</strong>
              </div>
            </div>
          </article>

          <article className="panel chartPanel">
            <div className="panelHeader">
              <div>
                <span>Динамика</span>
                <h2>Средний прогноз по дням</h2>
              </div>
              <BarChart3 size={20} />
            </div>
            {chartData.length ? (
              <>
                <div className="detailGrid">
                  <div>
                    <span>Точек на графике</span>
                    <strong>{formatNumber(chartData.length)}</strong>
                  </div>
                  <div>
                    <span>Метрика</span>
                    <strong>{metricLabels[selectedMetric]}</strong>
                  </div>
                </div>
                <ResponsiveContainer width="100%" height={280}>
                  <LineChart data={chartData} margin={{ top: 12, right: 16, bottom: 8, left: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={18} />
                    <YAxis domain={chartDomain} allowDataOverflow={false} />
                    <Tooltip />
                    <Legend />
                    <Line type="linear" dataKey="forecast" name="Прогноз" stroke="#38bdf8" strokeWidth={2} dot={false} />
                    <Line type="linear" dataKey="actual" name="Факт" stroke="#22c55e" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </>
            ) : (
              <EmptyState title="График не построен" text="В выбранном периоде сервис не вернул прогнозных значений по этой метрике." />
            )}
          </article>

          <article className="panel">
            <div className="panelHeader">
              <div>
                <span>По строкам</span>
                <h2>Прогнозные значения</h2>
              </div>
            </div>
            {analysisLoading ? <LoadingPanel /> : null}
            {!analysisLoading && forecastRows.length ? (
              <div className="tableScroll">
                <table>
                  <thead>
                    <tr>
                      <th>Дата</th>
                      <th>Модель</th>
                      <th>Горизонт</th>
                      <th>Средняя</th>
                      <th>Мин.</th>
                      <th>Макс.</th>
                      <th>Осадки</th>
                        <th>Обновлен</th>
                      <th>Детали</th>
                    </tr>
                  </thead>
                  <tbody>
                    {forecastRows.map((item, index) => (
                      <tr key={`${item.observation_date}-${item.model || "model"}-${item.horizon_days || "h"}-${index}`}>
                        <td>{formatDate(item.observation_date)}</td>
                        <td>{item.model || "нет данных"}</td>
                        <td>{item.horizon_days === null ? "нет данных" : `${item.horizon_days} дн.`}</td>
                        <td>{item.forecast_avg_temp === null ? "нет данных" : `${formatNumber(item.forecast_avg_temp, 1)} °C`}</td>
                        <td>{item.forecast_min_temp === null ? "нет данных" : `${formatNumber(item.forecast_min_temp, 1)} °C`}</td>
                        <td>{item.forecast_max_temp === null ? "нет данных" : `${formatNumber(item.forecast_max_temp, 1)} °C`}</td>
                        <td>{item.forecast_precipitation === null ? "нет данных" : `${formatNumber(item.forecast_precipitation, 1)} мм`}</td>
                        <td>{formatDateTime(item.run_at)}</td>
                        <td>
                          <button className="iconButton" type="button" onClick={() => setSelectedForecast(item)} aria-label="Открыть детали">
                            <Eye size={17} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}

            {!analysisLoading && !forecastRows.length ? (
              <EmptyState title="Прогнозы не найдены" text="Для выбранной станции и периода сервис не вернул прогнозных значений." />
            ) : null}
          </article>
        </>
      ) : null}

      <Modal title="Детали прогноза" open={Boolean(selectedForecast)} onClose={() => setSelectedForecast(null)}>
        {selectedForecast ? (
          <div className="detailGrid">
            <div>
              <span>Дата</span>
              <strong>{formatDate(selectedForecast.observation_date)}</strong>
            </div>
            <div>
              <span>Станция</span>
              <strong>{series?.station.name || "нет данных"}</strong>
            </div>
            <div>
              <span>Модель</span>
              <strong>{selectedForecast.model || "нет данных"}</strong>
            </div>
            <div>
              <span>Горизонт</span>
              <strong>{selectedForecast.horizon_days === null ? "нет данных" : `${selectedForecast.horizon_days} дн.`}</strong>
            </div>
            <div>
              <span>Обновлен</span>
              <strong>{formatDateTime(selectedForecast.run_at)}</strong>
            </div>
            <div>
              <span>Средняя температура</span>
              <strong>{selectedForecast.forecast_avg_temp === null ? "нет данных" : `${formatNumber(selectedForecast.forecast_avg_temp, 1)} °C`}</strong>
            </div>
            <div>
              <span>Минимальная температура</span>
              <strong>{selectedForecast.forecast_min_temp === null ? "нет данных" : `${formatNumber(selectedForecast.forecast_min_temp, 1)} °C`}</strong>
            </div>
            <div>
              <span>Максимальная температура</span>
              <strong>{selectedForecast.forecast_max_temp === null ? "нет данных" : `${formatNumber(selectedForecast.forecast_max_temp, 1)} °C`}</strong>
            </div>
            <div>
              <span>Осадки</span>
              <strong>
                {selectedForecast.forecast_precipitation === null ? "нет данных" : `${formatNumber(selectedForecast.forecast_precipitation, 1)} мм`}
              </strong>
            </div>
          </div>
        ) : null}
      </Modal>
    </section>
  );
}
