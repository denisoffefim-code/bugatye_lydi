import { CloudSun, Eye, Filter, Search, SlidersHorizontal } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, formatApiError } from "../api/client";
import { EmptyState, ErrorState, LoadingPanel, SkeletonGrid } from "../components/DataState";
import { Modal } from "../components/Modal";
import { StatusBadge } from "../components/StatusBadge";
import type { ForecastRun, ForecastRunsResponse, Source, Station, StationSeriesResponse } from "../types";
import { defaultRange, formatDate, formatDateTime, formatNumber, sourceLabel, statusLabel } from "../utils";

type SortKey = "run_at" | "saved_rows" | "requested_station_count" | "status";

export function ForecastsPage() {
  const range = useMemo(() => defaultRange(7), []);
  const [runs, setRuns] = useState<ForecastRunsResponse | null>(null);
  const [stations, setStations] = useState<Station[]>([]);
  const [series, setSeries] = useState<StationSeriesResponse | null>(null);
  const [selectedRun, setSelectedRun] = useState<ForecastRun | null>(null);
  const [selectedStation, setSelectedStation] = useState<number | "">("");
  const [startDate, setStartDate] = useState(range.start);
  const [endDate, setEndDate] = useState(range.end);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [source, setSource] = useState<Source | "">("");
  const [sortBy, setSortBy] = useState<SortKey>("run_at");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [loading, setLoading] = useState(true);
  const [seriesLoading, setSeriesLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [seriesError, setSeriesError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [runResponse, stationResponse] = await Promise.all([
          api.forecastRuns({ limit: 200 }),
          api.stations({ limit: 500, with_coordinates_only: true })
        ]);
        if (active) {
          setRuns(runResponse);
          setStations(stationResponse.stations);
          setSelectedStation((current) => current || stationResponse.stations[0]?.id || "");
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
    void load();
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
          source: source || undefined
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
  }, [endDate, selectedStation, source, startDate]);

  const filteredRuns = useMemo(() => {
    const query = search.trim().toLowerCase();
    return [...(runs?.runs || [])]
      .filter((run) => {
        const text = `${run.id} ${run.provider} ${run.model} ${run.source} ${run.status}`.toLowerCase();
        const matchesSearch = !query || text.includes(query);
        const matchesStatus = !status || run.status === status;
        const matchesSource = !source || run.source === source;
        const matchesDate = run.requested_end_date >= startDate && run.requested_start_date <= endDate;
        return matchesSearch && matchesStatus && matchesSource && matchesDate;
      })
      .sort((a, b) => {
        if (sortBy === "run_at") {
          return new Date(b.run_at).getTime() - new Date(a.run_at).getTime();
        }
        if (sortBy === "status") {
          return a.status.localeCompare(b.status);
        }
        return Number(b[sortBy]) - Number(a[sortBy]);
      });
  }, [endDate, runs?.runs, search, sortBy, source, startDate, status]);

  const statuses = useMemo(() => Array.from(new Set((runs?.runs || []).map((run) => run.status))).sort(), [runs?.runs]);
  const forecastRows = (series?.items || []).filter((item) => item.forecast_avg_temp !== null || item.forecast_precipitation !== null);

  return (
    <section className="pageStack">
      <div className="pageHeader">
        <div>
          <span>Прогнозы</span>
          <h1>Прогнозы по городам</h1>
          <p>Выберите город и период, чтобы посмотреть сохраненные прогнозы.</p>
        </div>
      </div>

      <div className="filterPanel mainFilters">
        <label>
          <span>Город</span>
          <select value={selectedStation} onChange={(event) => setSelectedStation(event.target.value ? Number(event.target.value) : "")}>
            <option value="">Не выбран</option>
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
        <button className="ghostButton filterToggle" type="button" onClick={() => setShowAdvanced((current) => !current)}>
          <SlidersHorizontal size={17} />
          Дополнительные параметры
        </button>
      </div>

      {showAdvanced ? (
        <div className="filterPanel advancedPanel">
          <label className="inputShell">
            <Search size={17} />
            <input placeholder="Название, номер или состояние" value={search} onChange={(event) => setSearch(event.target.value)} />
          </label>
        <label>
          <span>Тип данных</span>
          <select value={source} onChange={(event) => setSource(event.target.value as Source | "")}>
            <option value="">Все</option>
            <option value="forecast">Новые прогнозы</option>
            <option value="previous_runs">Прошлые прогнозы</option>
          </select>
        </label>
        <label>
          <span>Состояние</span>
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">Все</option>
            {statuses.map((item) => (
              <option key={item} value={item}>
                {statusLabel(item)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Сортировка</span>
          <select value={sortBy} onChange={(event) => setSortBy(event.target.value as SortKey)}>
            <option value="run_at">Дата запуска</option>
            <option value="saved_rows">Записи</option>
            <option value="requested_station_count">Станции</option>
            <option value="status">Состояние</option>
          </select>
        </label>
        </div>
      ) : null}

      {loading ? <SkeletonGrid cards={3} /> : null}
      {error ? <ErrorState text={error} /> : null}

      {!loading && !error ? (
        <>
          <div className="forecastCards">
            {filteredRuns.slice(0, 6).map((run) => (
              <article className="forecastCard" key={run.id}>
                <div className="cardTop">
                  <CloudSun size={22} />
                  <StatusBadge status={run.status} />
                </div>
                <h2>Проверка #{run.id}</h2>
                <p>
                  {run.model} · {sourceLabel(run.source)} · {formatDateTime(run.run_at)}
                </p>
                <div className="forecastStats">
                  <span>
                    <strong>{formatNumber(run.saved_rows)}</strong>
                    записей
                  </span>
                  <span>
                    <strong>{formatNumber(run.saved_stations)}</strong>
                    станций
                  </span>
                  <span>
                    <strong>{run.saved_horizon_days?.join(", ") || "нет"}</strong>
                    дней
                  </span>
                </div>
                <button className="ghostButton fullWidth" type="button" onClick={() => setSelectedRun(run)}>
                  <Eye size={17} />
                  Подробнее
                </button>
              </article>
            ))}
          </div>

          {!filteredRuns.length ? <EmptyState title="Прогнозы не найдены" text="Измените выбранные даты или параметры." /> : null}

          <article className="panel">
            <div className="panelHeader">
              <div>
                  <span>Список</span>
                  <h2>Проверки прогнозов</h2>
              </div>
              <Filter size={20} />
            </div>
            <div className="tableScroll">
              <table>
                <thead>
                  <tr>
                    <th>Номер</th>
                    <th>Вариант прогноза</th>
                    <th>Тип данных</th>
                    <th>Период</th>
                    <th>Состояние</th>
                    <th>Записей</th>
                    <th>Детали</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRuns.map((run) => (
                    <tr key={run.id}>
                      <td>#{run.id}</td>
                      <td>{run.model}</td>
                      <td>{sourceLabel(run.source)}</td>
                      <td>
                        {formatDate(run.requested_start_date)} - {formatDate(run.requested_end_date)}
                      </td>
                      <td>
                        <StatusBadge status={run.status} />
                      </td>
                      <td>{formatNumber(run.saved_rows)}</td>
                      <td>
                        <button className="iconButton" type="button" onClick={() => setSelectedRun(run)} aria-label="Открыть детали">
                          <Eye size={17} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </article>

          <article className="panel">
            <div className="panelHeader">
              <div>
                <span>По городу</span>
                <h2>Значения прогноза</h2>
              </div>
              <SlidersHorizontal size={20} />
            </div>

            {seriesLoading ? <LoadingPanel /> : null}
            {seriesError ? <ErrorState text={seriesError} /> : null}
            {!seriesLoading && !seriesError && forecastRows.length ? (
              <div className="tableScroll">
                <table>
                  <thead>
                    <tr>
                      <th>Дата</th>
                      <th>Вариант прогноза</th>
                      <th>Тип данных</th>
                      <th>Дней вперед</th>
                      <th>Температура</th>
                      <th>Мин.</th>
                      <th>Макс.</th>
                      <th>Осадки</th>
                      <th>Ветер</th>
                    </tr>
                  </thead>
                  <tbody>
                    {forecastRows.map((item, index) => (
                      <tr key={`${item.observation_date}-${item.horizon_days}-${item.model}-${index}`}>
                        <td>{formatDate(item.observation_date)}</td>
                        <td>{item.model || "нет данных"}</td>
                        <td>{sourceLabel(item.source)}</td>
                        <td>{item.horizon_days ?? "нет данных"}</td>
                        <td>{formatNumber(item.forecast_avg_temp, 1)} °C</td>
                        <td>{formatNumber(item.forecast_min_temp, 1)} °C</td>
                        <td>{formatNumber(item.forecast_max_temp, 1)} °C</td>
                        <td>{formatNumber(item.forecast_precipitation, 1)} мм</td>
                        <td>{formatNumber(item.forecast_max_wind_speed, 1)} м/с</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            {!seriesLoading && !seriesError && !forecastRows.length ? (
              <EmptyState title="Нет прогнозных значений" text="Для выбранной станции и периода прогнозные записи не найдены." />
            ) : null}
          </article>
        </>
      ) : null}

      <Modal title={selectedRun ? `Проверка #${selectedRun.id}` : "Проверка прогноза"} open={Boolean(selectedRun)} onClose={() => setSelectedRun(null)}>
        {selectedRun ? (
          <div className="detailGrid">
            <div>
              <span>Поставщик данных</span>
              <strong>{selectedRun.provider}</strong>
            </div>
            <div>
              <span>Вариант прогноза</span>
              <strong>{selectedRun.model}</strong>
            </div>
            <div>
              <span>Тип данных</span>
              <strong>{sourceLabel(selectedRun.source)}</strong>
            </div>
            <div>
              <span>Дата проверки</span>
              <strong>{formatDateTime(selectedRun.run_at)}</strong>
            </div>
            <div>
              <span>Запрошено станций</span>
              <strong>{formatNumber(selectedRun.requested_station_count)}</strong>
            </div>
            <div>
              <span>Сохранено станций</span>
              <strong>{formatNumber(selectedRun.saved_stations)}</strong>
            </div>
            <div>
              <span>Сохранено записей</span>
              <strong>{formatNumber(selectedRun.saved_rows)}</strong>
            </div>
            <div>
              <span>Завершено</span>
              <strong>{formatDateTime(selectedRun.completed_at)}</strong>
            </div>
            {selectedRun.error_message ? (
              <div className="detailWide">
                <span>Ошибка</span>
                <strong>{selectedRun.error_message}</strong>
              </div>
            ) : null}
          </div>
        ) : null}
      </Modal>
    </section>
  );
}
