import { BarChart3, CalendarDays, CloudRain, Eye, MapPin, Search, SlidersHorizontal, ThermometerSun } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, formatApiError } from "../api/client";
import { EmptyState, ErrorState, LoadingPanel, SkeletonGrid } from "../components/DataState";
import { MetricCard } from "../components/MetricCard";
import { Modal } from "../components/Modal";
import type { Station, StationSeriesItem, StationSeriesResponse } from "../types";
import { defaultRange, finiteNumber, formatDate, formatNumber } from "../utils";

interface ObservationFilters {
  stationId: number | "";
  startDate: string;
  endDate: string;
  search: string;
}

export function ObservationsPage() {
  const range = useMemo(() => defaultRange(7), []);
  const [stations, setStations] = useState<Station[]>([]);
  const [series, setSeries] = useState<StationSeriesResponse | null>(null);
  const [selectedObservation, setSelectedObservation] = useState<StationSeriesItem | null>(null);
  const [filters, setFilters] = useState<ObservationFilters>({
    stationId: "",
    startDate: range.start,
    endDate: range.end,
    search: ""
  });
  const [activeFilters, setActiveFilters] = useState<ObservationFilters | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [loading, setLoading] = useState(true);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [hasAttemptedAnalysis, setHasAttemptedAnalysis] = useState(false);
  const [hasLoaded, setHasLoaded] = useState(false);

  useEffect(() => {
    let active = true;

    async function loadStations() {
      setLoading(true);
      setError(null);
      try {
        const response = await api.stations({ limit: 500 });
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

  function updateFilter<K extends keyof ObservationFilters>(key: K, value: ObservationFilters[K]) {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  async function runAnalysis(query: ObservationFilters) {
    if (!query.stationId) {
      setAnalysisError("Сначала выберите станцию.");
      return;
    }
    if (query.endDate < query.startDate) {
      setAnalysisError("Дата окончания должна быть не раньше даты начала.");
      return;
    }

    setAnalysisLoading(true);
    setAnalysisError(null);
    setHasAttemptedAnalysis(true);
    setSelectedObservation(null);

    try {
      const seriesResponse = await api.stationSeries({
        station_id: Number(query.stationId),
        start_date: query.startDate,
        end_date: query.endDate,
        include_forecast: false
      });
      setSeries(seriesResponse);
      setActiveFilters(query);
      setHasLoaded(true);
    } catch (err) {
      setAnalysisError(formatApiError(err));
    } finally {
      setAnalysisLoading(false);
    }
  }

  function handleReset() {
    setFilters({
      stationId: stations[0]?.id || "",
      startDate: range.start,
      endDate: range.end,
      search: ""
    });
    setActiveFilters(null);
    setSeries(null);
    setSelectedObservation(null);
    setAnalysisError(null);
    setHasAttemptedAnalysis(false);
    setHasLoaded(false);
    setShowAdvanced(false);
  }

  const actualRows = useMemo(() => {
    const query = activeFilters?.search.trim().toLowerCase() || "";
    return (series?.items || []).filter((item) => {
      const hasActual =
        item.actual_avg_temp !== null ||
        item.actual_min_temp !== null ||
        item.actual_max_temp !== null ||
        item.actual_precipitation !== null;
      if (!hasActual) {
        return false;
      }
      if (!query) {
        return true;
      }
      const text = `${item.observation_date} ${series?.station.name || ""} ${series?.station.wmo_index || ""}`.toLowerCase();
      return text.includes(query);
    });
  }, [activeFilters?.search, series?.items, series?.station.name, series?.station.wmo_index]);

  const station = series?.station;
  const averageTempValues = actualRows
    .map((item) => finiteNumber(item.actual_avg_temp))
    .filter((value): value is number => value !== null);
  const averageTemp = averageTempValues.length
    ? averageTempValues.reduce((sum, value) => sum + value, 0) / averageTempValues.length
    : null;
  const rainyDays = actualRows.filter((item) => Number(item.actual_precipitation || 0) > 0).length;
  const temperatureSpan = actualRows
    .map((item) => {
      if (item.actual_min_temp === null || item.actual_max_temp === null) {
        return null;
      }
      const minimum = finiteNumber(item.actual_min_temp);
      const maximum = finiteNumber(item.actual_max_temp);
      if (minimum === null || maximum === null) {
        return null;
      }
      return maximum - minimum;
    })
    .filter((value): value is number => value !== null);
  const maxSpan = temperatureSpan.length ? Math.max(...temperatureSpan) : null;

  return (
    <section className="pageStack">
      <div className="pageHeader">
        <div>
          <span>Фактическая погода</span>
          <h1>Анализ наблюдений по станциям</h1>
          <p>Выберите станцию и период, чтобы посмотреть фактическую погоду по дням.</p>
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
            <span>Город или станция</span>
            <select value={filters.stationId} onChange={(event) => updateFilter("stationId", event.target.value ? Number(event.target.value) : "")}>
              <option value="">Не выбрано</option>
              {stations.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} · {item.wmo_index}
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
        </div>

        <div className="formActions">
          <button className="primaryButton analysisButton" type="submit" disabled={loading || analysisLoading}>
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

      {loading ? <SkeletonGrid cards={3} /> : null}
      {error ? <ErrorState text={error} /> : null}
      {analysisError ? <ErrorState text={analysisError} /> : null}

      {!loading && !error && !hasAttemptedAnalysis ? (
        <EmptyState title="Анализ еще не запущен" text="Выберите параметры выше и нажмите «Показать анализ»." />
      ) : null}

      {!loading && !error && hasAttemptedAnalysis && (analysisLoading || hasLoaded) ? (
        <>
          {analysisLoading ? (
            <SkeletonGrid cards={4} />
          ) : (
            <div className="metricGrid">
              <MetricCard icon={MapPin} label="Станция" value={station?.wmo_index || "не выбрано"} hint={station?.name} tone="blue" />
              <MetricCard
                icon={CalendarDays}
                label="Дней в выборке"
                value={formatNumber(actualRows.length)}
                hint={activeFilters ? `${formatDate(activeFilters.startDate)} - ${formatDate(activeFilters.endDate)}` : "период не задан"}
                tone="green"
              />
              <MetricCard
                icon={ThermometerSun}
                label="Средняя температура"
                value={averageTemp === null ? "нет данных" : `${formatNumber(averageTemp, 1)} °C`}
                hint={maxSpan === null ? "суточный диапазон не рассчитан" : `макс. суточный разброс ${formatNumber(maxSpan, 1)} °C`}
                tone="amber"
              />
              <MetricCard
                icon={CloudRain}
                label="Дней с осадками"
                value={formatNumber(rainyDays)}
                hint={rainyDays ? "зафиксированы осадки" : "осадки не выделяются"}
                tone="coral"
              />
            </div>
          )}

          <article className="panel">
            <div className="panelHeader">
              <div>
                <span>Список</span>
                <h2>Фактические наблюдения</h2>
              </div>
              <ThermometerSun size={20} />
            </div>

            {analysisLoading ? <LoadingPanel text="Получаем фактические наблюдения" /> : null}

            {!analysisLoading && hasLoaded && actualRows.length ? (
              <div className="tableScroll">
                <table>
                  <thead>
                    <tr>
                      <th>Дата</th>
                      <th>Средняя</th>
                      <th>Мин.</th>
                      <th>Макс.</th>
                      <th>Осадки</th>
                      <th>Детали</th>
                    </tr>
                  </thead>
                  <tbody>
                    {actualRows.map((item, index) => (
                      <tr key={`${item.observation_date}-${index}`}>
                        <td>{formatDate(item.observation_date)}</td>
                        <td>{formatNumber(item.actual_avg_temp, 1)} °C</td>
                        <td>{formatNumber(item.actual_min_temp, 1)} °C</td>
                        <td>{formatNumber(item.actual_max_temp, 1)} °C</td>
                        <td>{formatNumber(item.actual_precipitation, 1)} мм</td>
                        <td>
                          <button className="iconButton" type="button" onClick={() => setSelectedObservation(item)} aria-label="Открыть детали">
                            <Eye size={17} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}

            {!analysisLoading && hasLoaded && !actualRows.length ? (
              <EmptyState title="Наблюдения не найдены" text="Для выбранной станции и периода сервис не вернул фактических наблюдений." />
            ) : null}
          </article>
        </>
      ) : null}

      <Modal title="Детали наблюдения" open={Boolean(selectedObservation)} onClose={() => setSelectedObservation(null)}>
        {selectedObservation ? (
          <div className="detailGrid">
            <div>
              <span>Дата</span>
              <strong>{formatDate(selectedObservation.observation_date)}</strong>
            </div>
            <div>
              <span>Станция</span>
              <strong>{series?.station.name || "нет данных"}</strong>
            </div>
            <div>
              <span>Средняя температура</span>
              <strong>{formatNumber(selectedObservation.actual_avg_temp, 1)} °C</strong>
            </div>
            <div>
              <span>Минимум</span>
              <strong>{formatNumber(selectedObservation.actual_min_temp, 1)} °C</strong>
            </div>
            <div>
              <span>Максимум</span>
              <strong>{formatNumber(selectedObservation.actual_max_temp, 1)} °C</strong>
            </div>
            <div>
              <span>Осадки</span>
              <strong>{formatNumber(selectedObservation.actual_precipitation, 1)} мм</strong>
            </div>
          </div>
        ) : null}
      </Modal>
    </section>
  );
}
