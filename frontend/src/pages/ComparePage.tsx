import { CheckCircle2, GitCompareArrows, Search, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, formatApiError } from "../api/client";
import { EmptyState, ErrorState, LoadingPanel, SkeletonGrid } from "../components/DataState";
import { AccuracyBadge } from "../components/StatusBadge";
import type { Source, Station, StationSeriesItem, StationSeriesResponse } from "../types";
import { defaultRange, formatDate, formatNumber, signed, sourceLabel } from "../utils";

interface CompareRow {
  label: string;
  forecast: number | null;
  actual: number | null;
  unit: string;
  threshold: [number, number];
}

export function ComparePage() {
  const range = useMemo(() => defaultRange(7), []);
  const [stations, setStations] = useState<Station[]>([]);
  const [selectedStation, setSelectedStation] = useState<number | "">("");
  const [series, setSeries] = useState<StationSeriesResponse | null>(null);
  const [startDate, setStartDate] = useState(range.start);
  const [endDate, setEndDate] = useState(range.end);
  const [source, setSource] = useState<Source | "">("");
  const [model, setModel] = useState("");
  const [horizon, setHorizon] = useState<number | "">("");
  const [forecastKey, setForecastKey] = useState("");
  const [actualKey, setActualKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [seriesLoading, setSeriesLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [seriesError, setSeriesError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function loadStations() {
      setLoading(true);
      setError(null);
      try {
        const response = await api.stations({ limit: 500, with_coordinates_only: true });
        if (active) {
          setStations(response.stations);
          setSelectedStation(response.stations[0]?.id || "");
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
    void loadStations();
    return () => {
      active = false;
    };
  }, []);

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
          source: source || undefined,
          model: model || undefined,
          horizon_days: horizon || undefined
        });
        if (active) {
          setSeries(response);
          setForecastKey("");
          setActualKey("");
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

  const forecastOptions = useMemo(
    () =>
      (series?.items || [])
        .map((item, index) => ({ item, key: String(index) }))
        .filter(({ item }) => item.forecast_avg_temp !== null || item.forecast_precipitation !== null),
    [series?.items]
  );

  const actualOptions = useMemo(
    () =>
      (series?.items || [])
        .map((item, index) => ({ item, key: String(index) }))
        .filter(({ item }) => item.actual_avg_temp !== null || item.actual_precipitation !== null),
    [series?.items]
  );

  const selectedForecast = forecastOptions.find((option) => option.key === (forecastKey || forecastOptions[0]?.key))?.item || null;
  const selectedActual = actualOptions.find((option) => option.key === (actualKey || actualOptions[0]?.key))?.item || null;

  const rows = buildRows(selectedForecast, selectedActual);
  const scoredRows = rows.filter((row) => row.forecast !== null && row.actual !== null);
  const averageError = scoredRows.length
    ? scoredRows.reduce((sum, row) => sum + Math.abs(Number(row.forecast) - Number(row.actual)), 0) / scoredRows.length
    : null;
  const goodCount = scoredRows.filter((row) => getStatusValue(row) <= row.threshold[0]).length;
  const warnCount = scoredRows.filter((row) => {
    const value = getStatusValue(row);
    return value > row.threshold[0] && value <= row.threshold[1];
  }).length;
  const badCount = scoredRows.length - goodCount - warnCount;

  return (
    <section className="pageStack">
      <div className="pageHeader">
        <div>
          <span>Сравнение</span>
          <h1>Прогноз против факта</h1>
          <p>Выберите прогнозную запись и фактическое наблюдение по одной станции.</p>
        </div>
      </div>

      <div className="filterPanel">
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
        <label>
          <span>С даты</span>
          <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
        </label>
        <label>
          <span>По дату</span>
          <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
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

      {loading ? <SkeletonGrid cards={3} /> : null}
      {error ? <ErrorState text={error} /> : null}

      {!loading && !error ? (
        <>
          <article className="panel">
            <div className="panelHeader">
              <div>
                <span>Выбор</span>
                <h2>{series?.station.name || "Станция"}</h2>
              </div>
              <GitCompareArrows size={20} />
            </div>

            {seriesLoading ? <LoadingPanel /> : null}
            {seriesError ? <ErrorState text={seriesError} /> : null}

            {!seriesLoading && !seriesError ? (
              <div className="compareSelectors">
                <label>
                  <span>Прогноз</span>
                  <select value={forecastKey || forecastOptions[0]?.key || ""} onChange={(event) => setForecastKey(event.target.value)}>
                    {forecastOptions.map(({ item, key }) => (
                      <option key={key} value={key}>
                        {formatDate(item.observation_date)} · {item.model || "модель"} · {sourceLabel(item.source)} · h{item.horizon_days ?? "-"}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Факт</span>
                  <select value={actualKey || actualOptions[0]?.key || ""} onChange={(event) => setActualKey(event.target.value)}>
                    {actualOptions.map(({ item, key }) => (
                      <option key={key} value={key}>
                        {formatDate(item.observation_date)}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            ) : null}

            {!seriesLoading && !seriesError && (!forecastOptions.length || !actualOptions.length) ? (
              <EmptyState title="Недостаточно данных" text="Для сравнения нужны прогноз и факт в выбранном периоде." />
            ) : null}
          </article>

          {selectedForecast && selectedActual ? (
            <>
              <div className="metricGrid">
                <article className="metricCard tone-blue">
                  <div className="metricIcon">
                    <CheckCircle2 size={22} />
                  </div>
                  <div>
                    <span>Точных совпадений</span>
                    <strong>{formatNumber(goodCount)}</strong>
                    <small>по доступным параметрам</small>
                  </div>
                </article>
                <article className="metricCard tone-amber">
                  <div className="metricIcon">
                    <GitCompareArrows size={22} />
                  </div>
                  <div>
                    <span>Средняя разница</span>
                    <strong>{averageError === null ? "нет данных" : formatNumber(averageError, 1)}</strong>
                    <small>без смешивания единиц</small>
                  </div>
                </article>
                <article className="metricCard tone-coral">
                  <div className="metricIcon">
                    <XCircle size={22} />
                  </div>
                  <div>
                    <span>Сильные ошибки</span>
                    <strong>{formatNumber(badCount)}</strong>
                    <small>заметные: {formatNumber(warnCount)}</small>
                  </div>
                </article>
              </div>

              <article className="panel">
                <div className="panelHeader">
                  <div>
                    <span>Аналитическая карточка</span>
                    <h2>
                      {formatDate(selectedForecast.observation_date)} vs {formatDate(selectedActual.observation_date)}
                    </h2>
                  </div>
                </div>
                <div className="tableScroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Показатель</th>
                        <th>Прогноз</th>
                        <th>Факт</th>
                        <th>Разница</th>
                        <th>Оценка</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row) => {
                        const diff = row.forecast !== null && row.actual !== null ? Number(row.forecast) - Number(row.actual) : null;
                        return (
                          <tr key={row.label}>
                            <td>{row.label}</td>
                            <td>{formatValue(row.forecast, row.unit)}</td>
                            <td>{formatValue(row.actual, row.unit)}</td>
                            <td>{signed(diff, row.unit)}</td>
                            <td>
                              <AccuracyBadge value={diff === null ? null : Math.abs(diff)} />
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </article>
            </>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function buildRows(forecast: StationSeriesItem | null, actual: StationSeriesItem | null): CompareRow[] {
  return [
    {
      label: "Средняя температура",
      forecast: forecast?.forecast_avg_temp ?? null,
      actual: actual?.actual_avg_temp ?? null,
      unit: " °C",
      threshold: [1, 3]
    },
    {
      label: "Минимальная температура",
      forecast: forecast?.forecast_min_temp ?? null,
      actual: actual?.actual_min_temp ?? null,
      unit: " °C",
      threshold: [1, 3]
    },
    {
      label: "Максимальная температура",
      forecast: forecast?.forecast_max_temp ?? null,
      actual: actual?.actual_max_temp ?? null,
      unit: " °C",
      threshold: [1, 3]
    },
    {
      label: "Осадки",
      forecast: forecast?.forecast_precipitation ?? null,
      actual: actual?.actual_precipitation ?? null,
      unit: " мм",
      threshold: [1, 5]
    },
    {
      label: "Максимальная скорость ветра",
      forecast: forecast?.forecast_max_wind_speed ?? null,
      actual: null,
      unit: " м/с",
      threshold: [2, 5]
    }
  ];
}

function getStatusValue(row: CompareRow) {
  if (row.forecast === null || row.actual === null) {
    return Number.POSITIVE_INFINITY;
  }
  return Math.abs(Number(row.forecast) - Number(row.actual));
}

function formatValue(value: number | null, unit: string) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "нет данных";
  }
  return `${formatNumber(value, 1)}${unit}`;
}
