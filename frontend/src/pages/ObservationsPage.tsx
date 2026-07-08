import { CalendarDays, CloudSun, Eye, MapPin, Search, ThermometerSun } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, formatApiError } from "../api/client";
import { EmptyState, ErrorState, LoadingPanel, SkeletonGrid } from "../components/DataState";
import { MetricCard } from "../components/MetricCard";
import { Modal } from "../components/Modal";
import type { Station, StationDetailsResponse, StationSeriesItem, StationSeriesResponse } from "../types";
import { defaultRange, formatDate, formatNumber } from "../utils";

export function ObservationsPage() {
  const range = useMemo(() => defaultRange(7), []);
  const [stations, setStations] = useState<Station[]>([]);
  const [selectedStation, setSelectedStation] = useState<number | "">("");
  const [details, setDetails] = useState<StationDetailsResponse | null>(null);
  const [series, setSeries] = useState<StationSeriesResponse | null>(null);
  const [selectedObservation, setSelectedObservation] = useState<StationSeriesItem | null>(null);
  const [startDate, setStartDate] = useState(range.start);
  const [endDate, setEndDate] = useState(range.end);
  const [search, setSearch] = useState("");
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
        const response = await api.stations({ limit: 500 });
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
      setDetails(null);
      return;
    }
    let active = true;
    async function loadSeries() {
      setSeriesLoading(true);
      setSeriesError(null);
      try {
        const [seriesResponse, detailsResponse] = await Promise.all([
          api.stationSeries({ station_id: Number(selectedStation), start_date: startDate, end_date: endDate }),
          api.stationDetails(Number(selectedStation))
        ]);
        if (active) {
          setSeries(seriesResponse);
          setDetails(detailsResponse);
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
  }, [endDate, selectedStation, startDate]);

  const actualRows = useMemo(() => {
    const query = search.trim().toLowerCase();
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
  }, [search, series?.items, series?.station.name, series?.station.wmo_index]);

  const station = details?.station;
  const stats = details?.stats || {};

  return (
    <section className="pageStack">
      <div className="pageHeader">
        <div>
          <span>Фактическая погода</span>
          <h1>Наблюдения по станциям</h1>
          <p>Выберите город или станцию и период, чтобы увидеть реальную погоду.</p>
        </div>
      </div>

      <div className="filterPanel">
        <label>
          <span>Город или станция</span>
          <select value={selectedStation} onChange={(event) => setSelectedStation(event.target.value ? Number(event.target.value) : "")}>
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
          <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
        </label>
        <label>
          <span>По дату</span>
          <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
        </label>
        <label>
          <span>Поиск</span>
          <div className="inputShell">
            <Search size={17} />
            <input placeholder="Дата или название" value={search} onChange={(event) => setSearch(event.target.value)} />
          </div>
        </label>
      </div>

      {loading ? <SkeletonGrid cards={3} /> : null}
      {error ? <ErrorState text={error} /> : null}

      {!loading && !error ? (
        <>
          <div className="metricGrid">
            <MetricCard icon={MapPin} label="Выбрано" value={station?.wmo_index || "не выбрано"} hint={station?.name} tone="blue" />
            <MetricCard
              icon={CalendarDays}
              label="Период наблюдений"
              value={`${formatDate(String(stats.weather_start_date || ""))}`}
              hint={`до ${formatDate(String(stats.weather_end_date || ""))}`}
              tone="green"
            />
            <MetricCard icon={ThermometerSun} label="Наблюдений" value={formatNumber(stats.weather_rows)} tone="amber" />
            <MetricCard icon={CloudSun} label="Прогнозных записей" value={formatNumber(stats.forecast_rows)} tone="coral" />
          </div>

          <article className="panel">
            <div className="panelHeader">
              <div>
                <span>Список</span>
                <h2>Фактические наблюдения</h2>
              </div>
              <ThermometerSun size={20} />
            </div>

            {seriesLoading ? <LoadingPanel /> : null}
            {seriesError ? <ErrorState text={seriesError} /> : null}

            {!seriesLoading && !seriesError && actualRows.length ? (
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
                          <button
                            className="iconButton"
                            type="button"
                            onClick={() => setSelectedObservation(item)}
                            aria-label="Открыть детали"
                          >
                            <Eye size={17} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}

            {!seriesLoading && !seriesError && !actualRows.length ? (
              <EmptyState title="Наблюдения не найдены" text="Для выбранной станции и периода нет фактических погодных записей." />
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
