import { ArrowRight, BarChart3, CloudSun, Database, GitCompareArrows, MapPin, ThermometerSun } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, formatApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, ErrorState, SkeletonGrid } from "../components/DataState";
import { MetricCard } from "../components/MetricCard";
import { StatusBadge } from "../components/StatusBadge";
import type { AnalyticsSummaryResponse, ForecastCoverageResponse, ForecastRunsResponse, StationsResponse } from "../types";
import { defaultRange, formatDate, formatDateTime, formatNumber, isRoleAtLeast, metricLabels } from "../utils";

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
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [summary, runs, stations, coverage, adminCoverage] = await Promise.all([
          api.summary({ start_date: range.start, end_date: range.end, only_with_coordinates: true }),
          api.forecastRuns({ limit: 6 }),
          api.stations({ limit: 500 }),
          api.forecastCoverage({ start_date: range.start, end_date: range.end }),
          isRoleAtLeast(user?.role, "admin") ? api.coverage().catch(() => null) : Promise.resolve(null)
        ]);
        if (active) {
          setData({ summary, runs, stations, coverage, adminCoverage });
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
          <p>Сводка по данным за период {formatDate(range.start)} - {formatDate(range.end)}.</p>
        </div>
        <div className="headerActions">
          <Link className="ghostButton" to="/app/forecasts">
            <CloudSun size={18} />
            Прогнозы
          </Link>
          <Link className="primaryButton" to="/app/analytics">
            <BarChart3 size={18} />
            Аналитика
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
              label="MAE температуры"
              value={avgTempMetric?.mae === null || avgTempMetric?.mae === undefined ? "нет данных" : `${formatNumber(avgTempMetric.mae, 1)} °C`}
              hint={`RMSE ${formatNumber(avgTempMetric?.rmse, 1)}`}
              tone="amber"
            />
            <MetricCard
              icon={Database}
              label="Строк прогноза"
              value={formatNumber(forecastRows)}
              hint={`Факт: ${formatNumber(actualRows)}`}
              tone="coral"
            />
          </div>

          <div className="dashboardGrid">
            <article className="panel">
              <div className="panelHeader">
                <div>
                  <span>Последние проверки</span>
                  <h2>Запуски прогнозов</h2>
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
                        <strong>#{run.id} · {run.model}</strong>
                        <span>
                          {formatDate(run.requested_start_date)} - {formatDate(run.requested_end_date)}
                        </span>
                      </div>
                      <div className="runMeta">
                        <StatusBadge status={run.status} />
                        <small>{formatNumber(run.saved_rows)} строк</small>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="Проверок пока нет" text="Backend не вернул forecast runs для вашего аккаунта." />
              )}
            </article>

            <article className="panel">
              <div className="panelHeader">
                <div>
                  <span>Покрытие</span>
                  <h2>Данные прогноза</h2>
                </div>
              </div>
              {data.coverage?.items.length ? (
                <div className="coverageList">
                  {data.coverage.items.slice(0, 5).map((item) => (
                    <div className="coverageItem" key={`${item.model}-${item.source}-${item.horizon_days}`}>
                      <div>
                        <strong>{item.model}</strong>
                        <span>
                          {item.source}, horizon {item.horizon_days}
                        </span>
                      </div>
                      <div className="barTrack">
                        <span style={{ width: `${Math.min(100, Math.max(6, item.station_count))}%` }} />
                      </div>
                      <small>{formatNumber(item.forecast_rows)} строк</small>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="Покрытия нет" text="За выбранный период forecast coverage пуст." />
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
              <strong>Графики ошибок</strong>
              <span>Средние ошибки, крупные отклонения и динамика.</span>
            </Link>
          </div>

          {data.adminCoverage ? (
            <article className="panel compactPanel">
              <div className="panelHeader">
                <div>
                  <span>Система</span>
                  <h2>Состояние хранилища</h2>
                </div>
                <small>Обновлено {formatDateTime(new Date().toISOString())}</small>
              </div>
              <div className="miniStats">
                {Object.entries(data.adminCoverage)
                  .slice(0, 8)
                  .map(([key, value]) => (
                    <div key={key}>
                      <span>{key}</span>
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
