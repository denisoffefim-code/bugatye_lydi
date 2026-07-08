import { ArrowRight, BarChart3, CloudSun, Database, GitCompareArrows, MapPin, ThermometerSun } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, formatApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, ErrorState, SkeletonGrid } from "../components/DataState";
import { MetricCard } from "../components/MetricCard";
import { StatusBadge } from "../components/StatusBadge";
import type { AnalyticsSummaryResponse, ForecastCoverageResponse, ForecastRunsResponse, StationsResponse } from "../types";
import { coverageLabel, defaultRange, formatDate, formatDateTime, formatNumber, isRoleAtLeast, metricLabels, sourceLabel } from "../utils";

interface DashboardData {
  summary: AnalyticsSummaryResponse | null;
  runs: ForecastRunsResponse | null;
  stations: StationsResponse | null;
  coverage: ForecastCoverageResponse | null;
  adminCoverage: Record<string, number | string | null> | null;
}

export function DashboardPage() {
  const { user } = useAuth();
  const [data, setData] = useState<DashboardData>({
    summary: null,
    runs: null,
    stations: null,
    coverage: null,
    adminCoverage: null
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const range = useMemo(() => defaultRange(7), []);

  useEffect(() => {
    let active = true;
    const settle = async <T,>(promise: Promise<T>, label: string): Promise<T | null> => {
      const timeout = new Promise<null>((resolve) => {
        window.setTimeout(() => resolve(null), 12000);
      });

      try {
        return await Promise.race([promise, timeout]);
      } catch (err) {
        console.warn(`SkyCast dashboard request failed: ${label}`, err);
        return null;
      }
    };

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [summary, runs, stations, coverage, adminCoverage] = await Promise.all([
          settle(api.summary({ start_date: range.start, end_date: range.end, only_with_coordinates: true }), "summary"),
          settle(api.forecastRuns({ limit: 6 }), "checks"),
          settle(api.stations({ limit: 500 }), "stations"),
          settle(api.forecastCoverage({ start_date: range.start, end_date: range.end }), "coverage"),
          isRoleAtLeast(user?.role, "admin") ? settle(api.coverage(), "service overview") : Promise.resolve(null)
        ]);
        if (active) {
          setData({ summary, runs, stations, coverage, adminCoverage });
          if (!summary && !runs && !stations && !coverage) {
            setError("Не удалось быстро получить данные кабинета. Сервис ответил, но данные загружаются слишком долго.");
          }
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
  }, [range.end, range.start, user?.role]);

  const avgTempMetric = data.summary?.metrics.avg_temp;
  const precipitationMetric = data.summary?.metrics.precipitation;
  const totals = data.summary?.totals || {};
  const forecastRows = totals.forecast_rows ?? 0;
  const actualRows = totals.actual_rows ?? 0;
  const comparisonPoints = avgTempMetric?.compared_points ?? 0;

  return (
    <section className="pageStack">
      <div className="pageHeader">
        <div>
          <span>Личный кабинет</span>
          <h1>Здравствуйте, {user?.full_name || "пользователь"}</h1>
          <p>Короткая сводка за период {formatDate(range.start)} - {formatDate(range.end)}.</p>
        </div>
        <div className="headerActions">
          <Link className="ghostButton" to="/app/forecasts">
            <CloudSun size={18} />
            Прогнозы
          </Link>
          <Link className="primaryButton" to="/app/analytics">
            <BarChart3 size={18} />
            Графики
          </Link>
        </div>
      </div>

      {loading ? <SkeletonGrid cards={4} /> : null}
      {error ? <ErrorState text={error} /> : null}

      {!loading && !error ? (
        <>
          <div className="metricGrid">
            <MetricCard icon={MapPin} label="Станций" value={formatNumber(data.stations?.total ?? 0)} tone="blue" />
            <MetricCard
              icon={GitCompareArrows}
              label="Сравнений"
              value={formatNumber(comparisonPoints)}
              hint={metricLabels.avg_temp}
              tone="green"
            />
            <MetricCard
              icon={ThermometerSun}
              label="Ошибка температуры"
              value={avgTempMetric?.mae === null || avgTempMetric?.mae === undefined ? "нет данных" : `${formatNumber(avgTempMetric.mae, 1)} °C`}
              hint="средняя разница"
              tone="amber"
            />
            <MetricCard
              icon={Database}
              label="Прогнозных записей"
              value={formatNumber(forecastRows)}
              hint={`фактических записей: ${formatNumber(actualRows)}`}
              tone="coral"
            />
          </div>

          <div className="dashboardGrid">
            <article className="panel">
              <div className="panelHeader">
                <div>
                  <span>Последнее</span>
                  <h2>Проверки прогноза</h2>
                </div>
                <Link className="textLink" to="/app/forecasts">
                  Открыть <ArrowRight size={16} />
                </Link>
              </div>
              {data.runs?.runs.length ? (
                <div className="runList">
                  {data.runs.runs.map((run) => (
                    <div className="runRow" key={run.id}>
                      <div>
                        <strong>Проверка #{run.id} · {run.model}</strong>
                        <span>
                          {formatDate(run.requested_start_date)} - {formatDate(run.requested_end_date)}
                        </span>
                      </div>
                      <div className="runMeta">
                        <StatusBadge status={run.status} />
                        <small>{formatNumber(run.saved_rows)} записей</small>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="Проверок пока нет" text="За этот период прогнозы еще не найдены." />
              )}
            </article>

            <article className="panel">
              <div className="panelHeader">
                <div>
                  <span>Наличие данных</span>
                  <h2>Где есть прогноз</h2>
                </div>
              </div>
              {data.coverage?.items.length ? (
                <div className="coverageList">
                  {data.coverage.items.slice(0, 5).map((item) => (
                    <div className="coverageItem" key={`${item.model}-${item.source}-${item.horizon_days}`}>
                      <div>
                        <strong>{item.model}</strong>
                        <span>
                          {sourceLabel(item.source)}, {item.horizon_days} дн.
                        </span>
                      </div>
                      <div className="barTrack">
                        <span style={{ width: `${Math.min(100, Math.max(6, item.station_count))}%` }} />
                      </div>
                      <small>{formatNumber(item.forecast_rows)} записей</small>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="Данных пока нет" text="За выбранный период прогнозы не найдены." />
              )}
            </article>
          </div>

          <div className="quickGrid">
            <Link className="quickTile" to="/app/compare">
              <GitCompareArrows size={22} />
              <strong>Сравнить прогноз и факт</strong>
              <span>Откройте таблицу различий по выбранной станции.</span>
            </Link>
            <Link className="quickTile" to="/app/observations">
              <ThermometerSun size={22} />
              <strong>Фактическая погода</strong>
              <span>Просмотрите сохраненные наблюдения.</span>
            </Link>
            <Link className="quickTile" to="/app/analytics">
              <BarChart3 size={22} />
              <strong>Графики точности</strong>
              <span>Средние ошибки, крупные отклонения и динамика.</span>
            </Link>
          </div>

          {data.adminCoverage ? (
            <article className="panel compactPanel">
              <div className="panelHeader">
                <div>
                  <span>Система</span>
                  <h2>Служебная сводка</h2>
                </div>
                <small>Обновлено {formatDateTime(new Date().toISOString())}</small>
              </div>
              <div className="miniStats">
                {Object.entries(data.adminCoverage)
                  .slice(0, 8)
                  .map(([key, value]) => (
                    <div key={key}>
                      <span>{coverageLabel(key)}</span>
                      <strong>{formatNumber(value)}</strong>
                    </div>
                  ))}
              </div>
            </article>
          ) : null}

          {precipitationMetric?.compared_points === 0 ? (
            <div className="noticeLine">Осадки пока не сравнивались в выбранном периоде.</div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
