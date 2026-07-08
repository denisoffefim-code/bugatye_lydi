import {
  ArrowRight,
  BarChart3,
  CalendarClock,
  Database,
  Gauge,
  Layers3,
  MapPin,
  ShieldCheck,
  ThermometerSun,
  UserRound
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, formatApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, ErrorState, SkeletonGrid } from "../components/DataState";
import { MetricCard } from "../components/MetricCard";
import type { AnalyticsSummaryResponse, ForecastCoverageResponse, Metric, StationsResponse } from "../types";
import {
  biasSummary,
  coverageLabel,
  defaultRange,
  formatDate,
  formatDateTime,
  formatNumber,
  isPrivilegedRole,
  metricLabels,
  roleLabel
} from "../utils";

interface DashboardData {
  summary: AnalyticsSummaryResponse | null;
  stations: StationsResponse | null;
  coverage: ForecastCoverageResponse | null;
  adminCoverage: Record<string, number | string | null> | null;
}

const metricOrder: Metric[] = ["avg_temp", "min_temp", "max_temp", "precipitation"];

export function DashboardPage() {
  const { user } = useAuth();
  const [data, setData] = useState<DashboardData>({
    summary: null,
    stations: null,
    coverage: null,
    adminCoverage: null
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const range = useMemo(() => defaultRange(30), []);
  const showRole = isPrivilegedRole(user?.role);

  useEffect(() => {
    let active = true;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [summary, stations, coverage, adminCoverage] = await Promise.all([
          api.summary({ start_date: range.start, end_date: range.end, only_with_coordinates: true }),
          api.stations({ limit: 500 }),
          api.forecastCoverage({ start_date: range.start, end_date: range.end }),
          showRole ? api.coverage() : Promise.resolve(null)
        ]);

        if (!active) {
          return;
        }

        setData({
          summary,
          stations,
          coverage,
          adminCoverage
        });
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
  }, [range.end, range.start, showRole]);

  const coverageItems = data.coverage?.items || [];
  const totalComparedPoints = metricOrder.reduce(
    (sum, metric) => sum + Number(data.summary?.metrics[metric]?.compared_points || 0),
    0
  );
  const modelCount = new Set(coverageItems.map((item) => item.model)).size;
  const horizons = Array.from(new Set(coverageItems.map((item) => item.horizon_days))).sort((left, right) => left - right);
  const firstForecastDate = coverageItems
    .map((item) => item.forecast_start_date)
    .filter((value): value is string => Boolean(value))
    .sort()[0];
  const lastForecastDates = coverageItems
    .map((item) => item.forecast_end_date)
    .filter((value): value is string => Boolean(value))
    .sort();
  const lastForecastDate = lastForecastDates[lastForecastDates.length - 1];
  const mainDataset =
    coverageItems.slice().sort((left, right) => Number(right.forecast_rows) - Number(left.forecast_rows))[0] || null;
  const avgTempMetric = data.summary?.metrics.avg_temp || null;
  const forecastRows = data.summary?.totals.forecast_rows ?? 0;
  const actualRows = data.summary?.totals.actual_rows ?? 0;
  const riskiestMetric =
    metricOrder
      .map((metric) => ({
        metric,
        max: data.summary?.metrics[metric]?.max_absolute_error ?? null
      }))
      .filter((item) => item.max !== null)
      .sort((left, right) => Number(right.max) - Number(left.max))[0] || null;

  return (
    <section className="pageStack">
      <div className="pageHeader">
        <div>
          <span>Личный кабинет</span>
          <h1>{user?.full_name || "Пользователь"}</h1>
          <p>
            Рабочая сводка SkyCast за период {formatDate(range.start)} - {formatDate(range.end)}: что уже загружено,
            сколько есть сравнений и где можно быстро перейти к анализу.
          </p>
        </div>
        <div className="headerActions">
          <Link className="ghostButton" to="/app/compare">
            <ThermometerSun size={18} />
            Разбор станции
          </Link>
          <Link className="primaryButton" to="/app/analytics">
            <BarChart3 size={18} />
            Открыть аналитику
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
              icon={Gauge}
              label="Сравнений"
              value={formatNumber(totalComparedPoints)}
              hint="по всем доступным метрикам"
              tone="green"
            />
            <MetricCard
              icon={ThermometerSun}
              label="Ошибка температуры"
              value={avgTempMetric?.mae === null || avgTempMetric?.mae === undefined ? "нет данных" : `${formatNumber(avgTempMetric.mae, 1)} °C`}
              hint={biasSummary(avgTempMetric?.bias, "avg_temp")}
              tone="amber"
            />
            <MetricCard
              icon={Layers3}
              label="Моделей прогноза"
              value={formatNumber(modelCount)}
              hint={horizons.length ? `горизонты: ${horizons.join(", ")} дн.` : "горизонты пока не определены"}
              tone="coral"
            />
          </div>

          <div className="dashboardGrid">
            <article className="panel">
              <div className="panelHeader">
                <div>
                  <span>Профиль</span>
                  <h2>Данные аккаунта</h2>
                </div>
                <UserRound size={20} />
              </div>
              <div className="detailGrid">
                <div>
                  <span>Имя</span>
                  <strong>{user?.full_name || "нет данных"}</strong>
                </div>
                <div>
                  <span>Почта</span>
                  <strong>{user?.email || "нет данных"}</strong>
                </div>
                {showRole ? (
                  <div>
                    <span>Уровень доступа</span>
                    <strong>{roleLabel(user?.role)}</strong>
                  </div>
                ) : null}
                <div>
                  <span>Последний вход</span>
                  <strong>{formatDateTime(user?.last_login_at)}</strong>
                </div>
                <div>
                  <span>Аккаунт создан</span>
                  <strong>{formatDateTime(user?.created_at)}</strong>
                </div>
                <div>
                  <span>Статус</span>
                  <strong>{user?.is_active ? "активен" : "отключен"}</strong>
                </div>
              </div>
            </article>

            <article className="panel">
              <div className="panelHeader">
                <div>
                  <span>Наличие данных</span>
                  <h2>Что уже есть в системе</h2>
                </div>
                <Database size={20} />
              </div>
              <div className="detailGrid">
                <div>
                  <span>Прогнозных строк</span>
                  <strong>{formatNumber(forecastRows)}</strong>
                </div>
                <div>
                  <span>Фактических строк</span>
                  <strong>{formatNumber(actualRows)}</strong>
                </div>
                <div>
                  <span>Первый день прогноза</span>
                  <strong>{formatDate(firstForecastDate)}</strong>
                </div>
                <div>
                  <span>Последний день прогноза</span>
                  <strong>{formatDate(lastForecastDate)}</strong>
                </div>
                <div>
                  <span>Основной набор</span>
                  <strong>{mainDataset ? `${mainDataset.model}, ${mainDataset.horizon_days} дн.` : "нет данных"}</strong>
                </div>
                <div>
                  <span>Станций в покрытии</span>
                  <strong>{formatNumber(mainDataset?.station_count ?? 0)}</strong>
                </div>
              </div>
            </article>
          </div>

          <div className="dashboardGrid">
            <article className="panel">
              <div className="panelHeader">
                <div>
                  <span>Главное</span>
                  <h2>Короткие выводы по периоду</h2>
                </div>
                <CalendarClock size={20} />
              </div>
              <div className="detailGrid">
                <div>
                  <span>Наиболее рискованная метрика</span>
                  <strong>{riskiestMetric ? metricLabels[riskiestMetric.metric] : "нет данных"}</strong>
                </div>
                <div>
                  <span>Максимальный промах</span>
                  <strong>
                    {riskiestMetric?.max === null || riskiestMetric?.max === undefined
                      ? "нет данных"
                      : `${formatNumber(riskiestMetric.max, 1)} ${riskiestMetric.metric === "precipitation" ? "мм" : "°C"}`}
                  </strong>
                </div>
                <div>
                  <span>Смещение по температуре</span>
                  <strong>{biasSummary(avgTempMetric?.bias, "avg_temp")}</strong>
                </div>
                <div>
                  <span>Сравнений по температуре</span>
                  <strong>{formatNumber(avgTempMetric?.compared_points ?? 0)}</strong>
                </div>
              </div>
            </article>

            <article className="panel">
              <div className="panelHeader">
                <div>
                  <span>Наборы прогноза</span>
                  <h2>Самые наполненные варианты</h2>
                </div>
                <ArrowRight size={20} />
              </div>
              {coverageItems.length ? (
                <div className="coverageList">
                  {coverageItems.slice(0, 5).map((item) => (
                    <div className="coverageItem" key={`${item.model}-${item.horizon_days}`}>
                      <div>
                        <strong>{item.model}</strong>
                        <span>
                          {item.horizon_days} дн. · {formatNumber(item.station_count)} станций
                        </span>
                      </div>
                      <div className="runMeta">
                        <strong>{formatNumber(item.forecast_rows)}</strong>
                        <small>
                          {formatDate(item.forecast_start_date)} - {formatDate(item.forecast_end_date)}
                        </small>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="Покрытие пусто" text="Пока нет наборов прогноза, которые можно анализировать." />
              )}
            </article>
          </div>

          <div className="quickGrid">
            <Link className="quickTile" to="/app/analytics">
              <BarChart3 size={22} />
              <strong>Полный анализ периода</strong>
              <span>Запустите разбор по датам, метрике и станции по кнопке.</span>
            </Link>
            <Link className="quickTile" to="/app/compare">
              <ThermometerSun size={22} />
              <strong>Разбор одной станции</strong>
              <span>Посмотрите ежедневный факт, прогноз и ошибку без ручного сопоставления строк.</span>
            </Link>
            <Link className="quickTile" to="/app/forecasts">
              <Database size={22} />
              <strong>Архив прогнозов</strong>
              <span>Проверьте, какие загрузки уже попали в систему и с каким покрытием.</span>
            </Link>
          </div>

          {showRole && data.adminCoverage ? (
            <article className="panel compactPanel">
              <div className="panelHeader">
                <div>
                  <span>Служебно</span>
                  <h2>Операционная сводка</h2>
                </div>
                <ShieldCheck size={20} />
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
        </>
      ) : null}
    </section>
  );
}
