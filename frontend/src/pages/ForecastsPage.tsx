import {
  BarChart3,
  CalendarDays,
  CloudRain,
  CloudSun,
  Eye,
  LineChart as LineIcon,
  MapPin,
  Search,
  SlidersHorizontal,
  ThermometerSun
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, formatApiError } from "../api/client";
import { EmptyState, ErrorState, LoadingPanel, SkeletonGrid } from "../components/DataState";
import { MetricCard } from "../components/MetricCard";
import { Modal } from "../components/Modal";
import type { Metric, Station, StationSeriesItem, StationSeriesResponse } from "../types";
import { chartNumberDomain, defaultRange, finiteNumber, formatDate, formatNumber, metricLabels, metricUnits } from "../utils";

interface ForecastFilters {
  stationId: number | "";
  startDate: string;
  endDate: string;
  metric: Metric;
  search: string;
}

interface ForecastDaySummary {
  date: string;
  forecastAvgTemp: number | null;
  forecastMinTemp: number | null;
  forecastMaxTemp: number | null;
  forecastPrecipitation: number | null;
  forecastMaxWindSpeed: number | null;
  actualAvgTemp: number | null;
  actualMinTemp: number | null;
  actualMaxTemp: number | null;
  actualPrecipitation: number | null;
}

const defaultFilters = (): ForecastFilters => {
  const range = defaultRange(7);
  return {
    stationId: "",
    startDate: range.start,
    endDate: range.end,
    metric: "avg_temp",
    search: ""
  };
};

function hasForecastData(item: StationSeriesItem) {
  return (
    item.forecast_avg_temp !== null ||
    item.forecast_min_temp !== null ||
    item.forecast_max_temp !== null ||
    item.forecast_precipitation !== null ||
    item.forecast_max_wind_speed !== null
  );
}

function average(values: Array<number | null | undefined>) {
  const numericValues = values.map(finiteNumber).filter((value): value is number => value !== null);
  if (!numericValues.length) {
    return null;
  }
  return numericValues.reduce((sum, value) => sum + value, 0) / numericValues.length;
}

function dailyForecastRows(items: StationSeriesItem[]): ForecastDaySummary[] {
  const grouped = new Map<string, StationSeriesItem[]>();

  for (const item of items) {
    if (!hasForecastData(item)) {
      continue;
    }
    grouped.set(item.observation_date, [...(grouped.get(item.observation_date) || []), item]);
  }

  return Array.from(grouped.entries())
    .sort((left, right) => new Date(right[0]).getTime() - new Date(left[0]).getTime())
    .map(([date, rows]) => ({
      date,
      forecastAvgTemp: average(rows.map((item) => item.forecast_avg_temp)),
      forecastMinTemp: average(rows.map((item) => item.forecast_min_temp)),
      forecastMaxTemp: average(rows.map((item) => item.forecast_max_temp)),
      forecastPrecipitation: average(rows.map((item) => item.forecast_precipitation)),
      forecastMaxWindSpeed: average(rows.map((item) => item.forecast_max_wind_speed)),
      actualAvgTemp: average(rows.map((item) => item.actual_avg_temp)),
      actualMinTemp: average(rows.map((item) => item.actual_min_temp)),
      actualMaxTemp: average(rows.map((item) => item.actual_max_temp)),
      actualPrecipitation: average(rows.map((item) => item.actual_precipitation))
    }));
}

function metricValues(item: ForecastDaySummary, metric: Metric) {
  if (metric === "min_temp") {
    return {
      forecast: item.forecastMinTemp,
      actual: item.actualMinTemp
    };
  }
  if (metric === "max_temp") {
    return {
      forecast: item.forecastMaxTemp,
      actual: item.actualMaxTemp
    };
  }
  if (metric === "precipitation") {
    return {
      forecast: item.forecastPrecipitation,
      actual: item.actualPrecipitation
    };
  }
  return {
    forecast: item.forecastAvgTemp,
    actual: item.actualAvgTemp
  };
}

function weatherValue(value: number | null | undefined, unit: string) {
  return value === null || value === undefined ? "нет данных" : `${formatNumber(value, 1)} ${unit}`;
}

export function ForecastsPage() {
  const [stations, setStations] = useState<Station[]>([]);
  const [filters, setFilters] = useState<ForecastFilters>(() => defaultFilters());
  const [activeFilters, setActiveFilters] = useState<ForecastFilters | null>(null);
  const [series, setSeries] = useState<StationSeriesResponse | null>(null);
  const [selectedForecast, setSelectedForecast] = useState<ForecastDaySummary | null>(null);
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
        end_date: query.endDate
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
    () => {
      const query = activeFilters?.search.trim().toLowerCase() || "";
      return dailyForecastRows(series?.items || []).filter((item) => {
        if (!query) {
          return true;
        }
        const text = `${item.date} ${series?.station.name || ""} ${series?.station.wmo_index || ""}`.toLowerCase();
        return text.includes(query);
      });
    },
    [activeFilters?.search, series?.items, series?.station.name, series?.station.wmo_index]
  );

  const chartData = useMemo(() => {
    return forecastRows
      .slice()
      .sort((left, right) => new Date(left.date).getTime() - new Date(right.date).getTime())
      .map((item) => {
        const values = metricValues(item, selectedMetric);
        return {
          date: formatDate(item.date),
          forecast: values.forecast,
          actual: values.actual
        };
      });
  }, [forecastRows, selectedMetric]);

  const chartDomain = chartNumberDomain(chartData.flatMap((item) => [item.forecast, item.actual]));
  const forecastDays = chartData.filter((item) => item.forecast !== null).length;
  const averageTemp = average(forecastRows.map((item) => item.forecastAvgTemp));
  const rainyDays = forecastRows.filter((item) => Number(item.forecastPrecipitation || 0) > 0).length;
  const maxWind = Math.max(
    ...forecastRows
      .map((item) => item.forecastMaxWindSpeed)
      .filter((value): value is number => typeof value === "number" && Number.isFinite(value)),
    0
  );

  return (
    <section className="pageStack">
      <div className="pageHeader">
        <div>
          <span>Прогнозы</span>
          <h1>Прогноз по станции</h1>
          <p>Выберите станцию и период, чтобы посмотреть прогноз погоды по дням.</p>
        </div>
      </div>

      <form
        className="analysisForm"
        onSubmit={(event) => {
          event.preventDefault();
          void runAnalysis(filters);
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
              <span>Поиск внутри периода</span>
              <div className="inputShell">
                <Search size={17} />
                <input placeholder="Дата или часть названия станции" value={filters.search} onChange={(event) => updateFilter("search", event.target.value)} />
              </div>
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
              icon={MapPin}
              label="Станция"
              value={series?.station.wmo_index || "не выбрано"}
              hint={series?.station.name}
              tone="blue"
            />
            <MetricCard
              icon={CalendarDays}
              label="Дней с прогнозом"
              value={formatNumber(forecastDays)}
              hint={activeFilters ? `${formatDate(activeFilters.startDate)} - ${formatDate(activeFilters.endDate)}` : "период не задан"}
              tone="green"
            />
            <MetricCard
              icon={ThermometerSun}
              label="Средняя температура"
              value={averageTemp === null ? "нет данных" : `${formatNumber(averageTemp, 1)} °C`}
              hint="прогноз за период"
              tone="amber"
            />
            <MetricCard
              icon={CloudRain}
              label="Дней с осадками"
              value={formatNumber(rainyDays)}
              hint={maxWind > 0 ? `ветер до ${formatNumber(maxWind, 1)} м/с` : "ветер не выделяется"}
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
                <span>Тип данных</span>
                <strong>прогноз погоды</strong>
              </div>
              <div>
                <span>Дней в таблице</span>
                <strong>{formatNumber(forecastRows.length)}</strong>
              </div>
            </div>
          </article>

          <article className="panel chartPanel">
            <div className="panelHeader">
              <div>
                <span>Динамика</span>
                <h2>Прогноз по дням</h2>
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
                    <YAxis domain={chartDomain} allowDataOverflow tickFormatter={(value) => formatNumber(value, 1)} />
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
                <span>Список</span>
                <h2>Прогноз погоды</h2>
              </div>
            </div>
            {analysisLoading ? <LoadingPanel /> : null}
            {!analysisLoading && forecastRows.length ? (
              <div className="tableScroll">
                <table>
                  <thead>
                    <tr>
                      <th>Дата</th>
                      <th>Средняя</th>
                      <th>Мин.</th>
                      <th>Макс.</th>
                      <th>Осадки</th>
                      <th>Ветер</th>
                      <th>Детали</th>
                    </tr>
                  </thead>
                  <tbody>
                    {forecastRows.map((item, index) => (
                      <tr key={`${item.date}-${index}`}>
                        <td>{formatDate(item.date)}</td>
                        <td>{weatherValue(item.forecastAvgTemp, "°C")}</td>
                        <td>{weatherValue(item.forecastMinTemp, "°C")}</td>
                        <td>{weatherValue(item.forecastMaxTemp, "°C")}</td>
                        <td>{weatherValue(item.forecastPrecipitation, "мм")}</td>
                        <td>{weatherValue(item.forecastMaxWindSpeed, "м/с")}</td>
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
              <strong>{formatDate(selectedForecast.date)}</strong>
            </div>
            <div>
              <span>Станция</span>
              <strong>{series?.station.name || "нет данных"}</strong>
            </div>
            <div>
              <span>Средняя температура</span>
              <strong>{weatherValue(selectedForecast.forecastAvgTemp, "°C")}</strong>
            </div>
            <div>
              <span>Минимальная температура</span>
              <strong>{weatherValue(selectedForecast.forecastMinTemp, "°C")}</strong>
            </div>
            <div>
              <span>Максимальная температура</span>
              <strong>{weatherValue(selectedForecast.forecastMaxTemp, "°C")}</strong>
            </div>
            <div>
              <span>Осадки</span>
              <strong>{weatherValue(selectedForecast.forecastPrecipitation, "мм")}</strong>
            </div>
            <div>
              <span>Ветер</span>
              <strong>{weatherValue(selectedForecast.forecastMaxWindSpeed, "м/с")}</strong>
            </div>
          </div>
        ) : null}
      </Modal>
    </section>
  );
}
